-- gen3_rr_scripted_play.lua — natural-play driver for Radical Red (card gen3-P3-C3-7).
--
-- WHY THIS EXISTS. The six RR duo scenarios never reach the semantic engine sites: they either
-- inject commands through the companion patch or drive host-side RAM writes, so the pinned
-- bodies are never executed by the ENGINE (docs/gen3/research/shadow_explode_battle_end.md,
-- whole file). The pins themselves are fine — every non-liveness RR function keeps its vanilla
-- callers (docs/gen3/research/rr_site_reachability.md), exec hooks deliver 900/900 at tested
-- addresses (lua/tests/probe_gen3_exec_addr.lua), and the pinned battle_end hook 0x08015BD0
-- fired exactly once when a real battle returned to the field
-- (docs/gen3/probes/census_rr_battle_2026-09-21.txt run B). PLAN §5.7 wants a natural-play
-- SOURCE per artifact; this is RR's.
--
-- HOW IT DIFFERS FROM THE FIRERED DRIVER (lua/tests/gen3_scripted_play.lua). There is NO pret
-- source for RR's maps, so no walk in this file may be BFS-pinned. Consequences, applied
-- throughout:
--   * legs start from SAVESTATES, not from a walked-to position. SLINK_STATE selects one
--     (default slink_prebattle.State, the in-tall-grass state tools/mkstates.py captures —
--     lua/tests/mkstate.lua kind="battle"). Every leg declares the state it needs in `state`.
--   * walking is minimal, bounded and RAM-verified: pacing in place for encounters, holding a
--     direction into a door, or walk_to()'s greedy axis-at-a-time approach, every step checked
--     against G.pos / G.map. No direction list is asserted to be a correct route.
--   * terminals are RAM observables (gMain.inBattle, gMain.callback2, SaveBlock1 map id,
--     gPlayerPartyCount, gBattleMons HP, the flash save counter). Never a frame count.
--
-- WHAT IS NOT PINNED (each leg repeats its own; nothing is hidden):
--   * RR/CFRU menu navigation. No proven RR input sequence exists anywhere in lua/tests/duo/*
--     or lua/tests/test_live_*.lua for the battle BAG (searched 2026-09-21: the only bag work
--     in the tree is Gen 1's, lua/tests/duo/duo_gen1_main.lua) — so wild_catch is OPEN, not
--     mashed-and-hoped. The PC storage menu is likewise unpinned but IS attempted, because its
--     terminal (gPlayerPartyCount moving down then back up) is an unambiguous RAM witness that
--     cannot pass on a wrong press.
--   * RR's Pokémon Center 1F tile layout. walk_to()'s PC target defaults to FireRed's
--     (11,2) approach tile and is overridable with SLINK_RR_PC_TILE="x,y" — a calibration
--     knob, not configuration: the map data that would settle it does not exist.
--
-- RESUME: SLINK_GEN3_PLAY_FROM=<leg name> skips every leg before it. Each leg's `state` field
-- names the savestate to pass as SLINK_STATE when starting there; loading it is this script's
-- job (unlike the FR driver, where the coordinator owned it).
--
-- Environment: SLINK_ROOT, SLINK_GEN3_CHECKPOINT, SLINK_GEN3_TITLE=radical_red (see
-- gen3_boot_check.lua), SLINK_STATE (path or bare file name), SLINK_STATE_DIR (default
-- E:/Howard/Bizhawk/GBA/State), SLINK_GEN3_PLAY_FROM, SLINK_SHADOW, SLINK_RR_PC_TILE.

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(WT, "SLINK_ROOT unset — launch via the gen3 fixture/gate tooling")
local G = dofile(WT .. "/lua/tests/gen3_boot_check.lua")

-- ── RR RAM observables ─────────────────────────────────────────────────────────────────────
-- Every address below is the radical_red profile's own (lua/games/gen3_frlge.lua:192-260) and
-- is the same constant the duo scenarios use (lua/tests/duo/scenario_explode.lua:22-28,
-- lua/tests/mkstate.lua:28-36). CFRU keeps the vanilla EWRAM battle globals; that is stated in
-- the profile and relied on by the shipping client, not assumed here.
local PARTY_COUNT_ADDR    = 0x02024029  -- radical_red.PARTY_COUNT_ADDR (gPlayerPartyCount)
local BATTLE_MONS_ADDR    = 0x02023BE4  -- radical_red.BATTLE_MONS_ADDR (gBattleMons)
local BM_HP               = 0x28        -- scenario_explode.lua:25 (struct BattlePokemon.hp)
local BM_MAXHP            = 0x2C        -- scenario_explode.lua:26
local BATTLE_OUTCOME_ADDR = 0x02023E8A  -- radical_red.BATTLE_OUTCOME_ADDR (gBattleOutcome)
local CTRL_ADDR           = 0x03004FE0  -- gBattlerControllerFuncs[0] (scenario_explode.lua:27)
local ACTION_MENU         = 0x0802E439  -- action-select controller (scenario_explode.lua:28)
local B_OUTCOME_CAUGHT    = 7           -- pret include/constants/battle.h:82

local function party_count() return memory.read_u8(PARTY_COUNT_ADDR) end
local function battle_outcome() return memory.read_u8(BATTLE_OUTCOME_ADDR) end
--- The PLAYER battler's current HP. Battler 0 is the player side in singles; gBattleMons[0] is
--- what the explode duo reads for exactly this purpose (scenario_explode.lua:50-52).
local function player_bmon_hp() return memory.read_u16_le(BATTLE_MONS_ADDR + BM_HP) end
local function player_bmon_maxhp() return memory.read_u16_le(BATTLE_MONS_ADDR + BM_MAXHP) end
local function at_action_menu() return memory.read_u32_le(CTRL_ADDR) == ACTION_MENU end

--- POLARITY: the `in_battle` predicate is (gMain+1081 & 2) with expect=0
--- (data/games/gen3_rr/write_checkpoint.json radical_red.predicates.in_battle), so
--- G.pred_ok(cp,"in_battle") is TRUE when we are NOT in a battle. Wrapped once here so no leg
--- has to get that inversion right twice.
local function in_battle(cp) return not G.pred_ok(cp, "in_battle") end
local function on_field(cp)
    return G.pred_ok(cp, "in_battle") and G.pred_ok(cp, "callback2")
end

local function mapid(cp) local g, n = G.map(cp); return g * 256 + n end

-- ── movement primitives (bounded, RAM-verified, never route-asserting) ─────────────────────

--- Pace up/down on the spot for up to `frames`, stopping the moment `stop()` is true. The same
--- 64-frame Up/Down cadence tools/mkstates.py uses to provoke a wild encounter in tall grass
--- (lua/tests/mkstate.lua:157-170) — it stays inside the grass patch instead of walking out of
--- it, which is the only property we need and the only one we can verify without map data.
local function pace(cp, frames, stop)
    for i = 1, frames do
        if stop and stop() then joypad.set({}); return true end
        local phase = i % 64
        if phase < 28 then joypad.set({ Up = true })
        elseif phase < 32 then joypad.set({})
        elseif phase < 60 then joypad.set({ Down = true })
        else joypad.set({}) end
        G.advance()
    end
    joypad.set({})
    return stop and stop() or false
end

--- A-only mash on the 16-frame native-menu cadence (reference_bizhawk_gate_drivers), stopping
--- on `stop()`. Deliberately NOT G.mash: that one also pulses Start, which opens the START menu
--- once the field comes back — exactly where several legs end.
local function mash_a(cp, taps, stop)
    for _ = 1, taps do
        if stop and stop() then return true end
        G.tap("A", 3, 13)
    end
    return stop and stop() or false
end

--- Greedy axis-at-a-time walk to a target tile, every step verified by G.pos. NOT a route: with
--- no RR map data there is nothing to BFS, so this closes the larger coordinate gap first, taps
--- A when a step does not move us (textbox), and sidesteps onto the other axis when it stays
--- blocked. Bounded; returns false rather than flailing.
-- ponytail: greedy, no pathfinder — upgrade to BFS only if RR map data ever becomes available.
local function walk_to(cp, tx, ty, budget)
    for _ = 1, (budget or 48) do
        local x, y = G.pos(cp)
        if x == tx and y == ty then return true end
        local dir
        if x < tx then dir = "Right" elseif x > tx then dir = "Left"
        elseif y < ty then dir = "Down" else dir = "Up" end
        for _ = 1, 12 do joypad.set({ [dir] = true }); G.advance() end
        G.idle(4)
        local nx, ny = G.pos(cp)
        if nx == x and ny == y then
            for _ = 1, 2 do G.tap("A", 3, 13) end     -- a textbox owns the field: clear it
            local alt
            if dir == "Right" or dir == "Left" then alt = (y < ty) and "Down" or "Up"
            else alt = (x < tx) and "Right" or "Left" end
            for _ = 1, 12 do joypad.set({ [alt] = true }); G.advance() end
            G.idle(4)
        end
    end
    joypad.set({})
    local x, y = G.pos(cp)
    return x == tx and y == ty
end

--- Hold `dir` into a door/edge until the SaveBlock1 map id changes. The only map-change witness
--- available without RR warp tables, and the same one mkstate.lua's town kind trusts (:250-268).
local function hold_until_map_change(cp, dir, budget)
    local from = mapid(cp)
    for _ = 1, (budget or 30) do
        if mapid(cp) ~= from then break end
        for _ = 1, 24 do joypad.set({ [dir] = true }); G.advance() end
        if mapid(cp) == from then for _ = 1, 2 do G.tap("A", 3, 13) end end
    end
    joypad.set({})
    if mapid(cp) == from then return false, from end
    for _ = 1, 900 do                       -- let the warp fade finish before the next leg
        if on_field(cp) then break end
        G.advance()
    end
    return true, from
end

--- Leave whatever battle we are in (or return immediately if we are not in one). Every leg that
--- starts from slink_prebattle.State needs this, because that state IS mid-encounter.
local function leave_battle(cp, taps)
    return mash_a(cp, taps or 900, function() return on_field(cp) end)
end

-- ── the legs ───────────────────────────────────────────────────────────────────────────────

local PLAY_FROM = os.getenv("SLINK_GEN3_PLAY_FROM")
if PLAY_FROM == "" then PLAY_FROM = nil end

local LEGS = {}

-- ── leg: battle_to_field ───────────────────────────────────────────────────────────────────
-- The one leg with a PHYSICAL receipt already in hand: the census run drove exactly this and
-- the pinned battle_end hook fired once, at the ReturnFromBattleToOverworld entry frame.
LEGS[#LEGS + 1] = {
    name = "battle_to_field",
    state = "slink_prebattle.State",
    exercises = { "battle_end", "frame_control" },
    source = {
        "docs/gen3/probes/census_rr_battle_2026-09-21.txt (run B: battle_end 0x08015BD0 hits=1 at frame 2484, == ReturnFromBattleToOverworld's own entry frame; run A: CB2_Overworld resumes at 2497)",
        "docs/gen3_engine_sites.md battle_end row (rr/rr_companion PINNED 08015BCC/+4; capture is after the inBattle clear, before the final SetMainCallback2)",
        "data/games/gen3_rr/write_checkpoint.json radical_red.predicates.in_battle / .callback2",
    },
    run = function(cp)
        if not in_battle(cp) then
            G.phase("battle_to_field", "not in a battle at state load — nothing to return from")
        end
        if not leave_battle(cp, 1200) then
            G.shot("stuck")
            G.finish(false, string.format(
                "battle_to_field: never returned to the field (in_battle=%s callback2_ok=%s)",
                tostring(in_battle(cp)), tostring(G.pred_ok(cp, "callback2"))))
        end
        -- G.pos returns TWO values: capture them, or a later format arg silently eats them
        -- (the same trap probe_gen3_battle_census.lua:62 documents).
        local px, py = G.pos(cp)
        G.phase("field", string.format("map=%d at=(%d,%d) outcome=%d",
                                       mapid(cp), px, py, battle_outcome()))
    end,
}

-- ── leg: wild_faint ────────────────────────────────────────────────────────────────────────
LEGS[#LEGS + 1] = {
    name = "wild_faint",
    state = "slink_prebattle.State",
    exercises = { "faint", "battle_begin", "battle_end" },
    source = {
        "lua/tests/mkstate.lua:143-180 (slink_prebattle.State is captured IN TALL GRASS, the last in-grass position before an encounter — so pacing here is a real wild-encounter source)",
        "docs/gen3_engine_sites.md faint row (rr PINNED 080213C4/+4, Cmd_tryfaintmon after the PLAYER faint-counter store) — only an ENGINE-executed faint reaches it, which is why the faint duo (host HP writes, lua/memory_gba.lua:1275+) never did",
        "lua/tests/duo/scenario_explode.lua:22-28,50-52 (gBattleMons[0] = the player battler; hp @ +0x28, maxHP @ +0x2C)",
        "lua/games/gen3_frlge.lua:198-207 (radical_red BATTLE_MONS_ADDR / PARTY_COUNT_ADDR)",
    },
    run = function(cp)
        leave_battle(cp, 1200)          -- start-from-prebattle: clear the loaded encounter first
        local ENCOUNTERS = 12
        local fainted = false
        for enc = 1, ENCOUNTERS do
            if not pace(cp, 4000, function() return in_battle(cp) end) then
                G.shot("stuck")
                G.finish(false, string.format(
                    "wild_faint: no wild encounter while pacing (cycle %d, map=%d at=(%d,%d)) — "
                    .. "SLINK_STATE must be a state standing in TALL GRASS",
                    enc, mapid(cp), G.pos(cp)))
            end
            -- FIGHT -> move slot 1, then let the turn run. gActionSelectionCursor resets per
            -- battle, so A at the action menu is FIGHT and the next A is move slot 1 — the same
            -- default-cursor assumption the FR driver states as a RISK. What the wild mon does
            -- back is not controlled; that is the whole point (we need it to win).
            local turns = 0
            while in_battle(cp) and turns < 40 do
                turns = turns + 1
                mash_a(cp, 60, function() return at_action_menu() or not in_battle(cp) end)
                if not in_battle(cp) then break end
                G.tap("A", 3, 13)       -- FIGHT
                G.tap("A", 3, 13)       -- move slot 1
                -- Watch for the player mon hitting 0 HP DURING the battle: after the battle
                -- ends gBattleMons is stale, so a post-hoc read would prove nothing.
                for _ = 1, 120 do
                    if in_battle(cp) and player_bmon_maxhp() > 0 and player_bmon_hp() == 0 then
                        fainted = true
                    end
                    if at_action_menu() or not in_battle(cp) then break end
                    G.tap("A", 3, 13)
                end
            end
            leave_battle(cp, 900)
            if fainted then break end
            G.phase("survived", string.format("encounter %d ended without a player faint "
                                              .. "(outcome=%d)", enc, battle_outcome()))
        end
        if not fainted then
            G.shot("stuck")
            G.finish(false, string.format(
                "wild_faint: the player battler never reached 0 HP in %d wild encounters. The "
                .. "party mon in this savestate may simply keep winning — RR's starting party is "
                .. "whatever the battery save carries, and nothing here weakens it. Re-run with a "
                .. "save whose lead is under-levelled for the route.", ENCOUNTERS))
        end
        G.phase("fainted", string.format("player battler HP hit 0; party=%d outcome=%d",
                                         party_count(), battle_outcome()))
    end,
}

-- ── leg: wild_catch (OPEN) ─────────────────────────────────────────────────────────────────
-- An open leg carries no run body: the run loop logs `open_reason` and skips it.
LEGS[#LEGS + 1] = {
    name = "wild_catch",
    state = "slink_prebattle.State",
    exercises = { "capture_wild" },
    open = true,
    open_reason = "no proven RR input sequence for the battle BAG exists: a search of "
               .. "lua/tests/duo/* and lua/tests/test_live_*.lua (2026-09-21) found bag "
               .. "navigation only for Gen 1 (lua/tests/duo/duo_gen1_main.lua), and CFRU "
               .. "replaces the FireRed bag UI, so the FR driver's pinned Right->B_ACTION_USE_ITEM "
               .. "toggle cannot be carried over. Terminal when it is pinned: "
               .. "gBattleOutcome == 7 (B_OUTCOME_CAUGHT) at 0x02023E8A",
    source = {
        "docs/gen3_engine_sites.md capture_wild row (rr PINNED 0802D824/+4, Cmd_givecaughtmon immediately after BL GiveMonToPlayer)",
        "lua/games/gen3_frlge.lua:206 (radical_red BATTLE_OUTCOME_ADDR 0x02023E8A)",
        "lua/tests/duo/duo_gen1_main.lua:243-246 (the ONLY bag-input precedent in the tree, and it is Gen 1)",
    },
}

-- ── leg: pc_move_full_party (OPEN) ─────────────────────────────────────────────────────────
LEGS[#LEGS + 1] = {
    name = "pc_move_full_party",
    state = "slink_prebattle.State",
    exercises = { "pc_move", "mon_given" },
    open = true,
    open_reason = "SendMonToPC (RR: the compressed-storage detour at 090B6E38) only runs on an "
               .. "ACQUISITION that cannot fit in the party — a catch or a gift with six party "
               .. "mons. It therefore inherits wild_catch's unpinned bag sequence, plus a "
               .. "six-mon party this savestate family does not guarantee",
    source = {
        "docs/gen3_engine_sites.md pc_move row (rr PINNED 090B6E9A/+6; entry/trampoline 08040B90 -> 090B6E38, CFRU compressed-PC acquisition)",
        "docs/gen3_engine_sites.md mon_given row (rr PINNED 0907D7F8/+8, RR replacement common POP at 0907D800; R0 = party(0)/PC(1)/failure(2))",
    },
}

-- ── leg: door_warp ─────────────────────────────────────────────────────────────────────────
LEGS[#LEGS + 1] = {
    name = "door_warp",
    state = "slink_door.State",
    exercises = { "map_load" },
    source = {
        "lua/tests/mkstate.lua:216-246 (slink_door.State: outside a Pokémon Center door, player facing NORTH — captured before any movement, so holding Up is the whole warp)",
        "docs/gen3_engine_sites.md map_load row (CB2_LoadMap2's normal branch; the warp is the only natural source of it)",
        "lua/games/gen3_frlge.lua:258 (radical_red SB1_PTR_ADDR 0x03003840 — the map id G.map reads)",
    },
    run = function(cp)
        local ok, from = hold_until_map_change(cp, "Up", 30)
        if not ok then
            G.shot("stuck")
            G.finish(false, string.format(
                "door_warp: map never changed from %d at (%d,%d) — SLINK_STATE must be "
                .. "slink_door.State (standing in front of a Pokémon Center door, facing north)",
                from, G.pos(cp)))
        end
        G.phase("warped", string.format("map %d -> %d at=(%d,%d)", from, mapid(cp), G.pos(cp)))
    end,
}

-- ── leg: pc_ops ────────────────────────────────────────────────────────────────────────────
-- The PC storage FRONTEND, which is exactly what the boxsync duo bypasses: OP_DEPOSIT_MON /
-- OP_WITHDRAW_MON call CreateCompressedMonFromBoxMon and compact the party directly
-- (patch/src/handlers.c:2079-2123), so a passing boxsync run cannot fire any of the six pinned
-- PC sites (docs/gen3/research/shadow_explode_battle_end.md, boxsync row). Only a human-style
-- menu deposit does.
LEGS[#LEGS + 1] = {
    name = "pc_ops",
    state = "slink_pokecenter.State",
    exercises = { "pc_deposit", "pc_box_place", "pc_withdraw" },
    source = {
        "lua/tests/mkstate.lua:270-300 (slink_pokecenter.State is inside a map the companion patch recognises as a Pokémon Center 1F — it spawns its trade NPC there, which is how the state is verified)",
        "docs/gen3_engine_sites.md pc_deposit row (rr PINNED 0809315C/+8, TryStorePartyMonInBox +0x80 with R0==1)",
        "docs/gen3_engine_sites.md pc_box_place row (rr PINNED 08093018/+8; RR IN-PLACE wrapper, capture 08093020, SetBoxMonAt detours to 090B6CA4)",
        "docs/gen3_engine_sites.md pc_withdraw row (rr PINNED 08092FF2/+6; RR IN-PLACE, party sentinel 25 not vanilla 14)",
        "lua/games/gen3_frlge.lua:199 (radical_red PARTY_COUNT_ADDR 0x02024029 — the deposit/withdraw witness)",
    },
    run = function(cp)
        -- The PC's tile. FireRed's PokemonCenter_1F puts the PC counter at (11,1) with (11,2)
        -- the approach tile; RR's layout is NOT pinned (no map data exists), so this is a
        -- calibration knob, overridable when the state lands somewhere else.
        local tx, ty = 11, 2
        local want = os.getenv("SLINK_RR_PC_TILE")
        if want and want ~= "" then
            local a, b = want:match("^(%-?%d+),(%-?%d+)$")
            if a then tx, ty = tonumber(a), tonumber(b) end
        end
        if not walk_to(cp, tx, ty, 48) then
            G.shot("stuck")
            local px, py = G.pos(cp)
            G.finish(false, string.format(
                "pc_ops: could not reach the PC approach tile (%d,%d); stopped at (%d,%d) on "
                .. "map %d. RR's Pokemon Center layout is unpinned — set SLINK_RR_PC_TILE=\"x,y\"",
                tx, ty, px, py, mapid(cp)))
        end
        G.tap("Up", 2, 13)               -- face the (solid) PC counter without stepping onto it

        -- CFRU's storage menu rows are NOT pinned. So: mash A, and every fourth attempt nudge
        -- the cursor Down first, so the run sweeps the rows instead of hammering row 0. The
        -- ONLY thing that counts as success is gPlayerPartyCount actually moving — a wrong
        -- press cannot fake that.
        local before = party_count()
        if before < 1 then
            G.finish(false, "pc_ops: party is empty at the PC; nothing to deposit")
        end
        local deposited = false
        for i = 1, 120 do
            if i % 4 == 0 then G.tap("Down", 3, 13) end
            G.tap("A", 3, 20)
            if party_count() < before then deposited = true; break end
        end
        if not deposited then
            G.shot("stuck")
            G.finish(false, string.format(
                "pc_ops: gPlayerPartyCount never dropped from %d — the CFRU storage rows are "
                .. "unpinned (see this leg's comment) and the sweep did not find DEPOSIT",
                before))
        end
        G.phase("deposited", string.format("party %d -> %d", before, party_count()))

        local after_deposit = party_count()
        local withdrawn = false
        for i = 1, 120 do
            if i % 4 == 0 then G.tap("Down", 3, 13) end
            G.tap("A", 3, 20)
            if party_count() > after_deposit then withdrawn = true; break end
        end
        if not withdrawn then
            G.shot("stuck")
            G.finish(false, string.format(
                "pc_ops: gPlayerPartyCount never rose from %d (withdraw)", after_deposit))
        end
        G.phase("withdrawn", string.format("party %d -> %d", after_deposit, party_count()))
        for _ = 1, 30 do                 -- back out to the field for whatever leg follows
            if on_field(cp) then break end
            G.tap("B", 3, 20)
        end
    end,
}

-- ── leg: save ──────────────────────────────────────────────────────────────────────────────
LEGS[#LEGS + 1] = {
    name = "save",
    state = "slink_overworld.State",
    exercises = { "save" },
    source = {
        "lua/tests/gen3_boot_check.lua save_via_menu (START-menu row search + flash sector-counter witness; no guessed menu row)",
        "data/games/gen3_rr/write_checkpoint.json radical_red.anchors.try_saving_data (TrySavingData, identical clean/companion bytes)",
        "docs/gen3/research/rr_site_reachability.md (TrySavingData keeps its vanilla callers on RR)",
    },
    run = function(cp)
        local domain = select(1, G.flash_domain())
        if not domain then G.finish(false, "save: no flash memory domain") end
        local ok, before, after = G.save_via_menu(cp, domain)
        if not ok then
            G.finish(false, string.format("save: counter never advanced (%d -> %d)", before, after))
        end
        pcall(client.saveram)
        G.phase("saved", string.format("counter %d -> %d", before, after))
    end,
}

-- ── run ────────────────────────────────────────────────────────────────────────────────────

local DEFAULT_STATE_DIR = "E:/Howard/Bizhawk/GBA/State"

--- SLINK_STATE may be an absolute path or a bare file name; a bare name resolves against
--- SLINK_STATE_DIR (the directory tools/mkstates.py writes into).
local function state_path(name)
    if not name or name == "" then return nil end
    if name:find("[/\\]") then return name end
    return (os.getenv("SLINK_STATE_DIR") or DEFAULT_STATE_DIR) .. "/" .. name
end

local function run()
    G.open("gen3_rr_scripted_play")      -- patch/build/gen3_rr_scripted_play_result.txt
    pcall(client.speedmode, 6399)
    G.budget = 900000
    local cp, title = G.checkpoint()
    G.phase("start", "title=" .. tostring(title))

    local from_idx = 1
    if PLAY_FROM then
        for i, leg in ipairs(LEGS) do
            if leg.name == PLAY_FROM then from_idx = i; break end
        end
    end

    -- A savestate is the starting point, not a cold boot: RR's maps are unmapped, so there is
    -- no walk from a fixture battery to any of these situations. Default to the leg we start
    -- at, so SLINK_GEN3_PLAY_FROM alone puts the right state up.
    local state = state_path(os.getenv("SLINK_STATE")) or state_path(LEGS[from_idx].state)
    if state then
        local ok = pcall(savestate.load, state)
        if not ok then G.finish(false, "savestate.load failed: " .. state) end
        G.phase("state", "loaded " .. state)
        G.idle(30)
    elseif not G.boot_to_field(cp, 9000) then
        G.shot("stuck")
        G.finish(false, string.format("boot: never reached the field (callback2=%08X)",
                                      G.pred(cp, "callback2")))
    end

    -- P3 shadow observer beside this driver when SLINK_SHADOW is set (the same block as
    -- lua/tests/gen3_scripted_play.lua and lua/tests/duo/duo_main.lua): read-only, SHADOW lines
    -- land in patch/build/gen3_rr_scripted_play_result.shadow.log.
    if os.getenv("SLINK_SHADOW") then
        local okshd, shd = pcall(dofile, WT .. "/lua/gen3/shadow_run.lua")
        if okshd and shd then
            local okst, st = pcall(shd.start, { duo = {
                result = WT .. "/patch/build/gen3_rr_scripted_play_result.txt", player = "a" } })
            if okst and st then
                G.phase("shadow", "observer started admitted_by=" .. tostring(st.admitted_by))
                event.onframeend(function() pcall(st.poll) end, "SLink-gen3-rr-shadow-poll")
            else
                G.phase("shadow", "observer start failed: " .. tostring(st))
            end
        else
            G.phase("shadow", "shadow_run dofile failed: " .. tostring(shd))
        end
    end

    if PLAY_FROM then
        G.phase("resume", "from=" .. PLAY_FROM .. " state=" .. tostring(state))
    end

    local reached = {}
    for i = from_idx, #LEGS do
        local leg = LEGS[i]
        if leg.open then
            G.phase("skip-open", leg.name .. ": " .. tostring(leg.open_reason))
        else
            G.phase("leg-start", leg.name .. " (state=" .. tostring(leg.state) .. ")")
            leg.run(cp)
            G.phase("leg-done", leg.name)
        end
        reached[#reached + 1] = leg.name
    end

    G.finish(true, "reached: " .. table.concat(reached, ","))
end

if (debug.getinfo(1, "S").source or "") == "main" then run() end

return { LEGS = LEGS, walk_to = walk_to, pace = pace, state_path = state_path }
