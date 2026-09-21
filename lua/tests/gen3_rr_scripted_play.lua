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
-- LANE RECEIPT (docs/gen3/probes/shadow_rr_play_2026-09-21.txt, 2026-09-21, first run of this
-- driver). PHYSICAL observer fires from natural play: battle_begin x4, battle_end x5,
-- whiteout x1, map_load x1 (door warp 769 -> 1284), save x1. And one NEGATIVE that matters:
-- wild_faint drove the player battler to 0 HP and the battle to outcome=2, yet the pinned
-- vanilla Cmd_tryfaintmon site (0x080213C8) NEVER FIRED. RR's faint path is therefore not the
-- vanilla one; re-pinning it is an OPEN research item owned elsewhere, not this driver's job.
-- wild_faint still runs and still proves the engine-side faint happened — see its oracle.
--
-- HOW IT DIFFERS FROM THE FIRERED DRIVER (lua/tests/gen3_scripted_play.lua). There is NO pret
-- source for RR's maps, so no walk in this file may be BFS-pinned. Consequences, applied
-- throughout:
--   * legs start from SAVESTATES, not from a walked-to position. EVERY leg declares the state
--     it needs in `state` and the driver LOADS it before running that leg (the first lane run
--     ran door_warp on whatever wild_faint left behind and failed with "map never changed from
--     1024" — that is the bug this rule exists to kill), then validates the loaded situation
--     with `check` before a single button is pressed.
--   * walking is minimal, bounded and RAM-verified: pacing in place for encounters, holding a
--     direction into a door, or walk_to()'s greedy axis-at-a-time approach, every step checked
--     against G.pos / G.map. No direction list is asserted to be a correct route.
--   * terminals are RAM observables. Never a frame count, and never a one-sided one: a faint
--     needs a positive-to-zero HP transition plus the engine's own faint counter, and a PC
--     round trip needs the party record KEY back, not merely a count that returned to where it
--     started.
--
-- WHAT IS NOT PINNED (each leg repeats its own; nothing is hidden):
--   * RR/CFRU menu navigation. No proven RR input sequence exists anywhere in lua/tests/duo/*
--     or lua/tests/test_live_*.lua for the battle BAG (searched 2026-09-21: the only bag work
--     in the tree is Gen 1's, lua/tests/duo/duo_gen1_main.lua) — so wild_catch is OPEN, not
--     mashed-and-hoped. The PC storage menu is likewise unpinned but IS attempted, because its
--     keyed oracle cannot pass on a wrong press.
--   * RR's Pokémon Center 1F tile layout. The FireRed approach tile (11,2) is WRONG on RR: the
--     first lane run stopped at (11,8)/(10,7) on map 1284. The default below is the coordinator's
--     screenshot estimate (15,7), approached facing Up — AN ESTIMATE, not a pin. It is verified
--     by walking there and interacting; when it is wrong the leg fails loudly and names
--     SLINK_RR_PC_TILE="x,y".
--
-- RESUME: SLINK_GEN3_PLAY_FROM=<leg name> skips every leg before it. Because each leg loads its
-- own declared savestate, resuming is exact: there is no "assume the previous leg left the
-- right situation" hand-off anywhere in this file. SLINK_STATE overrides the FIRST leg's state
-- only (an operator trying a different capture); later legs always load what they declare.
--
-- Environment: SLINK_ROOT, SLINK_GEN3_CHECKPOINT, SLINK_GEN3_TITLE=radical_red (see
-- gen3_boot_check.lua), SLINK_STATE (path or bare file name), SLINK_STATE_DIR (default
-- E:/Howard/Bizhawk/GBA/State), SLINK_GEN3_PLAY_FROM, SLINK_SHADOW, SLINK_RR_PC_TILE.

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(WT, "SLINK_ROOT unset — launch via the gen3 fixture/gate tooling")
local G = dofile(WT .. "/lua/tests/gen3_boot_check.lua")

-- ── RR RAM observables ─────────────────────────────────────────────────────────────────────
-- PROFILE FACTS: these come from the radical_red profile (lua/games/gen3_frlge.lua:192-260 /
-- data/games/gen3_rr/profile.json). CFRU keeps the vanilla EWRAM battle globals; that is stated
-- in the profile and relied on by the shipping client, not assumed here.
local PARTY_COUNT_ADDR    = 0x02024029  -- radical_red.PARTY_COUNT_ADDR (gPlayerPartyCount)
local PARTY_BASE          = 0x02024284  -- radical_red.PARTY_BASE (gPlayerParty)
local BATTLE_MONS_ADDR    = 0x02023BE4  -- radical_red.BATTLE_MONS_ADDR (gBattleMons)
local BATTLE_OUTCOME_ADDR = 0x02023E8A  -- radical_red.BATTLE_OUTCOME_ADDR (gBattleOutcome)
local BATTLE_RESULTS_ADDR = 0x03004F90  -- radical_red.BATTLE_RESULTS_ADDR (gBattleResults)
local FAINTS_OFF          = 0x00        -- radical_red.BATTLE_RESULTS_PLAYER_FAINTS_OFF
local MON_SIZE            = 100         -- vanilla 100-byte party record (lua/tests/duo/duo_main.lua)
local OFF_PID, OFF_OTID   = 0x00, 0x04  -- lua/tests/duo/duo_main.lua:23-24
local BM_HP, BM_MAXHP     = 0x28, 0x2C  -- struct BattlePokemon (lua/tests/duo/scenario_explode.lua:25-26)
local B_OUTCOME_CAUGHT    = 7           -- pret include/constants/battle.h:82

-- DUO-PRECEDENT CONSTANTS, NOT PROFILE FACTS. These two live in no profile and no checkpoint:
-- they are the values lua/tests/duo/scenario_explode.lua:27-28 and lua/tests/mkstate.lua:34-35
-- carry, re-validated by hand against this RR build when those scenarios were written. Treat a
-- mismatch as a build change, not as a bug here: the only thing that depends on them is
-- detecting the action-select menu, and every leg's actual terminal is a profile fact.
local CTRL_ADDR   = 0x03004FE0          -- gBattlerControllerFuncs[0]
local ACTION_MENU = 0x0802E439          -- the action-select controller function

local function party_count() return memory.read_u8(PARTY_COUNT_ADDR) end
local function battle_outcome() return memory.read_u8(BATTLE_OUTCOME_ADDR) end
local function player_faints() return memory.read_u8(BATTLE_RESULTS_ADDR + FAINTS_OFF) end
--- The PLAYER battler's HP. Battler 0 is the player side in singles; gBattleMons[0] is what the
--- explode duo reads for exactly this purpose (scenario_explode.lua:50-52).
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

--- The SaveBlock1 map id, or nil when the pointer is not yet a sane EWRAM address (G.map
--- returns -1,-1 then). nil is NOT a map: every caller must treat it as "unreadable".
local function mapid(cp)
    local g, n = G.map(cp)
    if g < 0 or n < 0 then return nil end
    return g * 256 + n
end

-- ── party records: the keyed PC oracle's raw material ──────────────────────────────────────

local function slot_base(i) return PARTY_BASE + i * MON_SIZE end

--- "PID:OTID" for party slot `i` — the same identity key the duo harness uses to follow a mon
--- across party moves (lua/tests/duo/duo_main.lua:86-98). Unique in practice and, crucially,
--- SURVIVES the box round trip that RR's 58-byte CompressedPokemon does not preserve byte for
--- byte, which is why the oracle below compares keys for the travelling mon and bytes only for
--- the ones that stayed.
local function slot_key(i)
    return string.format("%08X:%08X", memory.read_u32_le(slot_base(i) + OFF_PID),
                                      memory.read_u32_le(slot_base(i) + OFF_OTID))
end

--- The whole 100-byte record of slot `i` as a hex string (25 little-endian words).
local function slot_bytes(i)
    local parts = {}
    for w = 0, (MON_SIZE // 4) - 1 do
        parts[#parts + 1] = string.format("%08X", memory.read_u32_le(slot_base(i) + w * 4))
    end
    return table.concat(parts)
end

--- { n = party_count, keys = {key -> record hex}, order = {key, ...} }. Keyed, not indexed:
--- a deposit compacts the party, so slot numbers move and only keys are stable.
local function party_snapshot()
    local snap = { n = party_count(), keys = {}, order = {} }
    for i = 0, snap.n - 1 do
        local k = slot_key(i)
        snap.keys[k] = slot_bytes(i)
        snap.order[#snap.order + 1] = k
    end
    return snap
end

local function keylist(snap) return table.concat(snap.order, ",") end

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

--- Hold `dir` into a door/edge until the SaveBlock1 map id changes, then wait for the field to
--- settle. Returns ok, detail.
---
--- BOTH map reads must be VALID. G.map returns -1,-1 whenever the SaveBlock1 pointer is not a
--- sane EWRAM address (mid-warp, mid-load), and an unreadable map compared against a readable
--- one looks exactly like a warp. Treating that as success would let this leg pass while the
--- engine was in the middle of nothing at all.
local function hold_until_map_change(cp, dir, budget)
    local from = mapid(cp)
    if from == nil then
        return false, "the SaveBlock1 map id is unreadable before the warp (G.map = -1,-1)"
    end
    for _ = 1, (budget or 30) do
        if mapid(cp) ~= nil and mapid(cp) ~= from then break end
        for _ = 1, 24 do joypad.set({ [dir] = true }); G.advance() end
        if mapid(cp) == from then for _ = 1, 2 do G.tap("A", 3, 13) end end
    end
    joypad.set({})
    local to = mapid(cp)
    if to == nil then
        return false, string.format("the map id went unreadable and never came back (from %d)", from)
    end
    if to == from then
        return false, string.format("map never changed from %d", from)
    end
    local settled = false
    for _ = 1, 900 do                       -- the warp fade must actually finish
        if on_field(cp) and mapid(cp) ~= nil then settled = true; break end
        G.advance()
    end
    if not settled then
        return false, string.format("map %d -> %d but the field never settled "
                                    .. "(in_battle=%s callback2_ok=%s)", from, to,
                                    tostring(in_battle(cp)), tostring(G.pred_ok(cp, "callback2")))
    end
    return true, string.format("map %d -> %d", from, to)
end

--- Leave whatever battle we are in (or return immediately if we are not in one).
local function leave_battle(cp, taps)
    return mash_a(cp, taps or 900, function() return on_field(cp) end)
end

-- ── the legs ───────────────────────────────────────────────────────────────────────────────
--
-- Leg contract:
--   name         unique; the SLINK_GEN3_PLAY_FROM key
--   state        the savestate the DRIVER loads before running it (never inherited)
--   check(cp)    nil when the loaded situation is right, else the reason it is not
--   exercises    site kinds from docs/gen3_engine_sites.md's 23-kind list
--   source       citations
--   run(cp)      absent on an `open` leg, which the loop skips

local PLAY_FROM = os.getenv("SLINK_GEN3_PLAY_FROM")
if PLAY_FROM == "" then PLAY_FROM = nil end

local LEGS = {}

--- Shared precondition: on the walkable field with a readable map id.
local function check_on_field(cp)
    if in_battle(cp) then return "a battle is in progress" end
    if not on_field(cp) then return "not on the walkable field (callback2 is not CB2_Overworld)" end
    if mapid(cp) == nil then return "the SaveBlock1 map id is unreadable" end
    return nil
end

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
    -- REFUSES to start on the field. This leg's whole product is the battle->field TRANSITION;
    -- starting already outside a battle would sail through every terminal below without the
    -- engine ever executing ReturnFromBattleToOverworld, and report PASS for nothing.
    check = function(cp)
        if not in_battle(cp) then
            return "already on the field — this leg needs a battle in progress "
                .. "(slink_prebattle.State), the transition out of it IS the artifact"
        end
        return nil
    end,
    run = function(cp)
        if not leave_battle(cp, 1200) then
            G.shot("stuck")
            G.finish(false, string.format(
                "battle_to_field: the battle never ended (in_battle=%s callback2_ok=%s outcome=%d)",
                tostring(in_battle(cp)), tostring(G.pred_ok(cp, "callback2")), battle_outcome()))
        end
        local px, py = G.pos(cp)     -- G.pos returns TWO values; capture or a later arg eats them
        G.phase("field", string.format("map=%s at=(%d,%d) outcome=%d",
                                       tostring(mapid(cp)), px, py, battle_outcome()))
    end,
}

-- ── leg: wild_faint ────────────────────────────────────────────────────────────────────────
LEGS[#LEGS + 1] = {
    name = "wild_faint",
    state = "slink_prebattle.State",
    exercises = { "faint", "battle_begin", "battle_end" },
    source = {
        "lua/tests/mkstate.lua:143-180 (slink_prebattle.State is captured IN TALL GRASS, the last in-grass position before an encounter — so pacing here is a real wild-encounter source)",
        "docs/gen3_engine_sites.md faint row (rr PINNED 080213C4/+4, Cmd_tryfaintmon after the PLAYER faint-counter store) — NOTE the lane negative in this file's header: that vanilla site did NOT fire on RR even though this leg's oracle passed, so RR's faint path is elsewhere (OPEN, owned outside this driver)",
        "lua/games/gen3_frlge.lua:138-142 + data/games/gen3_rr/profile.json BATTLE_RESULTS_ADDR (gBattleResults.playerFaintCounter @ +0) — the ENGINE's own faint tally, which a host HP poke does not move",
        "lua/tests/duo/scenario_explode.lua:22-28,50-52 (gBattleMons[0] = the player battler; hp @ +0x28, maxHP @ +0x2C)",
    },
    check = function(cp)
        if mapid(cp) == nil then return "the SaveBlock1 map id is unreadable" end
        return nil     -- prebattle is mid-encounter by construction; run() clears it first
    end,
    run = function(cp)
        if not leave_battle(cp, 1200) then
            G.shot("stuck")
            G.finish(false, "wild_faint: could not get back to the field from the loaded state")
        end
        local faints_before = player_faints()
        local ENCOUNTERS = 12
        local fainted = false
        for enc = 1, ENCOUNTERS do
            if not pace(cp, 4000, function() return in_battle(cp) end) then
                G.shot("stuck")
                local px, py = G.pos(cp)
                G.finish(false, string.format(
                    "wild_faint: no wild encounter while pacing (cycle %d, map=%s at=(%d,%d)) — "
                    .. "SLINK_STATE must be a state standing in TALL GRASS",
                    enc, tostring(mapid(cp)), px, py))
            end
            -- THE FAINT ORACLE. A zero HP read on its own proves nothing: gBattleMons is stale
            -- between battles and zero is also what an uninitialised struct reads. So require a
            -- POSITIVE-TO-ZERO TRANSITION, both samples taken while inBattle is set, and then
            -- corroborate with the engine's own gBattleResults.playerFaintCounter.
            local saw_positive = false
            local saw_zero = false
            local turns = 0
            local function sample()
                if not in_battle(cp) then return end
                local hp, maxhp = player_bmon_hp(), player_bmon_maxhp()
                if maxhp == 0 then return end        -- struct not loaded: not a reading
                if hp > 0 then saw_positive = true
                elseif saw_positive then saw_zero = true end
            end
            while in_battle(cp) and turns < 40 do
                turns = turns + 1
                mash_a(cp, 60, function()
                    sample(); return at_action_menu() or not in_battle(cp)
                end)
                if not in_battle(cp) then break end
                G.tap("A", 3, 13)       -- FIGHT  (gActionSelectionCursor resets per battle)
                G.tap("A", 3, 13)       -- move slot 1
                for _ = 1, 120 do
                    sample()
                    if at_action_menu() or not in_battle(cp) then break end
                    G.tap("A", 3, 13)
                end
            end
            if not leave_battle(cp, 900) then
                G.shot("stuck")
                G.finish(false, string.format(
                    "wild_faint: encounter %d never returned to the field (in_battle=%s)",
                    enc, tostring(in_battle(cp))))
            end
            if saw_zero and player_faints() > faints_before then fainted = true; break end
            G.phase("survived", string.format(
                "encounter %d: hp_positive=%s hp_zero=%s faints %d->%d outcome=%d",
                enc, tostring(saw_positive), tostring(saw_zero),
                faints_before, player_faints(), battle_outcome()))
        end
        if not fainted then
            G.shot("stuck")
            G.finish(false, string.format(
                "wild_faint: no witnessed player faint in %d wild encounters (playerFaintCounter "
                .. "%d -> %d). The party mon in this savestate may simply keep winning — RR's "
                .. "starting party is whatever the battery save carries, and nothing here weakens "
                .. "it. Re-run with a save whose lead is under-levelled for the route.",
                ENCOUNTERS, faints_before, player_faints()))
        end
        G.phase("fainted", string.format(
            "player battler went positive -> 0 HP in battle; playerFaintCounter %d -> %d; party=%d",
            faints_before, player_faints(), party_count()))
    end,
}

-- ── leg: wild_catch (OPEN) ─────────────────────────────────────────────────────────────────
-- An open leg carries no run body: the loop logs `open_reason` and skips it, and it is NOT
-- counted as reached.
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
        "docs/gen3/probes/shadow_rr_play_2026-09-21.txt (PHYSICAL: map_load x1, 769 -> 1284, when this leg ran from its own state)",
        "docs/gen3_engine_sites.md map_load row (CB2_LoadMap2's normal branch; the warp is the only natural source of it)",
        "lua/games/gen3_frlge.lua:258 (radical_red SB1_PTR_ADDR 0x03003840 — the map id G.map reads)",
    },
    check = check_on_field,
    run = function(cp)
        local ok, detail = hold_until_map_change(cp, "Up", 30)
        if not ok then
            G.shot("stuck")
            local px, py = G.pos(cp)
            G.finish(false, string.format(
                "door_warp: %s (at (%d,%d)) — SLINK_STATE must be slink_door.State (standing in "
                .. "front of a Pokémon Center door, facing north)", detail, px, py))
        end
        local px, py = G.pos(cp)
        G.phase("warped", string.format("%s at=(%d,%d)", detail, px, py))
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
        "docs/gen3/probes/shadow_rr_play_2026-09-21.txt (lane run: the player stands at (11,8) on map 1284; FireRed's (11,2) is NOT the RR PC tile)",
        "docs/gen3_engine_sites.md pc_deposit row (rr PINNED 0809315C/+8, TryStorePartyMonInBox +0x80 with R0==1)",
        "docs/gen3_engine_sites.md pc_box_place row (rr PINNED 08093018/+8; RR IN-PLACE wrapper, capture 08093020, SetBoxMonAt detours to 090B6CA4)",
        "docs/gen3_engine_sites.md pc_withdraw row (rr PINNED 08092FF2/+6; RR IN-PLACE, party sentinel 25 not vanilla 14)",
        "lua/tests/duo/duo_main.lua:23-24 (PID/OTID offsets — the party record key this leg's oracle follows)",
    },
    check = check_on_field,
    run = function(cp)
        -- The PC's approach tile. RR's Pokémon Center layout is NOT pinned (no map data
        -- exists). The default is the coordinator's screenshot estimate — the PC terminals sit
        -- right of the nurse's counter, roughly 4 right and 2 up from the (11,8) landing tile,
        -- so (15,7) facing Up. AN ESTIMATE: it is verified by walking there and interacting,
        -- and when it is wrong this leg says so instead of wandering.
        local tx, ty = 15, 7
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
                .. "map %s. RR's Pokemon Center layout is unpinned (the default is a screenshot "
                .. "estimate) — set SLINK_RR_PC_TILE=\"x,y\"", tx, ty, px, py, tostring(mapid(cp))))
        end
        G.tap("Up", 2, 13)               -- face the (solid) PC counter without stepping onto it

        -- THE KEYED ORACLE. CFRU's storage menu rows are unpinned, so the presses are a bounded
        -- sweep (A, with a Down nudge every fourth attempt). None of that is trusted: the only
        -- thing that counts is that ONE NAMED PARTY RECORD left the party and THE SAME ONE came
        -- back, with every other record byte-identical. A count that merely returns to where it
        -- started — deposit A then withdraw B, or release A and withdraw something else — FAILS
        -- here, which is the whole reason a count-only oracle was not good enough.
        local before = party_snapshot()
        if before.n < 2 then
            G.finish(false, string.format(
                "pc_ops: the party holds %d mon — the oracle needs at least 2 (one to deposit, "
                .. "one to prove the others were left byte-identical)", before.n))
        end

        local deposited = false
        for i = 1, 120 do
            if i % 4 == 0 then G.tap("Down", 3, 13) end
            G.tap("A", 3, 20)
            if party_count() < before.n then deposited = true; break end
        end
        if not deposited then
            G.shot("stuck")
            G.finish(false, string.format(
                "pc_ops: gPlayerPartyCount never dropped from %d — the CFRU storage rows are "
                .. "unpinned (see this leg's comment) and the sweep did not find DEPOSIT",
                before.n))
        end
        local mid = party_snapshot()
        if mid.n ~= before.n - 1 then
            G.finish(false, string.format(
                "pc_ops: deposit moved the party count %d -> %d; exactly -1 is required "
                .. "(anything else is not one deposit)", before.n, mid.n))
        end
        local gone = nil
        for _, k in ipairs(before.order) do
            if mid.keys[k] == nil then
                if gone then
                    G.finish(false, string.format(
                        "pc_ops: deposit removed more than one record (%s and %s) from [%s]",
                        gone, k, keylist(before)))
                end
                gone = k
            end
        end
        if not gone then
            G.finish(false, string.format(
                "pc_ops: the party count dropped but every key is still present ([%s] -> [%s]) "
                .. "— that is not a deposit", keylist(before), keylist(mid)))
        end
        G.phase("deposited", string.format("party %d -> %d, key %s left the party",
                                           before.n, mid.n, gone))

        local withdrawn = false
        for i = 1, 120 do
            if i % 4 == 0 then G.tap("Down", 3, 13) end
            G.tap("A", 3, 20)
            if party_count() > mid.n then withdrawn = true; break end
        end
        if not withdrawn then
            G.shot("stuck")
            G.finish(false, string.format(
                "pc_ops: gPlayerPartyCount never rose from %d (withdraw)", mid.n))
        end
        local after = party_snapshot()
        if after.n ~= mid.n + 1 then
            G.finish(false, string.format(
                "pc_ops: withdraw moved the party count %d -> %d; exactly +1 is required",
                mid.n, after.n))
        end
        if after.keys[gone] == nil then
            G.finish(false, string.format(
                "pc_ops: the withdrawn mon is NOT the deposited one. Deposited %s; the party now "
                .. "holds [%s]. A released-and-replaced mon, or withdrawing a different box mon, "
                .. "is not a PC round trip", gone, keylist(after)))
        end
        -- The travelling record itself may differ byte for byte (RR stores a 58-byte
        -- CompressedPokemon, so the round trip is lossy by design); the ones that STAYED must
        -- not have moved a single byte.
        for _, k in ipairs(before.order) do
            if k ~= gone then
                if after.keys[k] == nil then
                    G.finish(false, string.format(
                        "pc_ops: record %s left the party during the round trip ([%s] -> [%s])",
                        k, keylist(before), keylist(after)))
                end
                if after.keys[k] ~= before.keys[k] then
                    G.finish(false, string.format(
                        "pc_ops: record %s is not byte-identical after the round trip", k))
                end
            end
        end
        G.phase("withdrawn", string.format("party %d -> %d, key %s is back; %d other records "
                                           .. "byte-identical", mid.n, after.n, gone, before.n - 1))

        -- Backing out is part of the leg, not an afterthought: a leg that leaves the storage UI
        -- up has not returned the engine to the field, and saying nothing about it would hand
        -- the next run a broken starting point.
        local out_ok = false
        for _ = 1, 40 do
            if on_field(cp) then out_ok = true; break end
            G.tap("B", 3, 20)
        end
        if not out_ok then
            G.shot("stuck")
            G.finish(false, "pc_ops: never returned to the field after the round trip "
                         .. "(the storage UI is still up)")
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
    check = check_on_field,
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
        local found = false
        for i, leg in ipairs(LEGS) do
            if leg.name == PLAY_FROM then from_idx = i; found = true; break end
        end
        if not found then G.finish(false, "SLINK_GEN3_PLAY_FROM names no leg: " .. PLAY_FROM) end
        G.phase("resume", "from=" .. PLAY_FROM)
    end

    -- P3 shadow observer beside this driver when SLINK_SHADOW is set (the same block as
    -- lua/tests/gen3_scripted_play.lua and lua/tests/duo/duo_main.lua): read-only, SHADOW lines
    -- land in patch/build/gen3_rr_scripted_play_result.shadow.log. A driver that ran the whole
    -- play and silently observed NOTHING is worse than a failure, so every start and poll error
    -- is fatal here rather than a logged shrug.
    local shadow_err = nil
    if os.getenv("SLINK_SHADOW") then
        local okshd, shd = pcall(dofile, WT .. "/lua/gen3/shadow_run.lua")
        if not okshd or not shd then
            G.finish(false, "shadow: dofile of lua/gen3/shadow_run.lua failed: " .. tostring(shd))
        end
        local okst, st = pcall(shd.start, { duo = {
            result = WT .. "/patch/build/gen3_rr_scripted_play_result.txt", player = "a" } })
        if not okst or not st then
            G.finish(false, "shadow: observer start failed: " .. tostring(st))
        end
        G.phase("shadow", "observer started admitted_by=" .. tostring(st.admitted_by))
        event.onframeend(function()
            if shadow_err then return end          -- report the FIRST error, then stop retrying
            local ok, err = pcall(st.poll)
            if not ok then shadow_err = tostring(err) end
        end, "SLink-gen3-rr-shadow-poll")
    end

    -- SLINK_STATE overrides the FIRST leg's declared state only; every later leg loads its own.
    local override = state_path(os.getenv("SLINK_STATE"))

    local reached, skipped = {}, {}
    for i = from_idx, #LEGS do
        local leg = LEGS[i]
        if leg.open then
            G.phase("skip-open", leg.name .. ": " .. tostring(leg.open_reason))
            skipped[#skipped + 1] = leg.name
        else
            -- PRECONDITION, ENFORCED. Load this leg's own state (never inherit the previous
            -- leg's situation) and then check it before pressing anything.
            local state = (i == from_idx and override) or state_path(leg.state)
            if not pcall(savestate.load, state) then
                G.finish(false, string.format("%s: savestate.load failed: %s", leg.name, state))
            end
            G.idle(30)
            G.phase("leg-state", string.format("%s <- %s", leg.name, state))
            local why = leg.check and leg.check(cp)
            if why then
                G.shot("stuck")
                G.finish(false, string.format("%s: precondition failed after loading %s: %s",
                                              leg.name, state, why))
            end

            G.phase("leg-start", leg.name)
            leg.run(cp)
            if shadow_err then
                G.finish(false, "shadow: poll failed during " .. leg.name .. ": " .. shadow_err)
            end
            G.phase("leg-done", leg.name)
            reached[#reached + 1] = leg.name
        end
    end

    if shadow_err then G.finish(false, "shadow: poll failed: " .. shadow_err) end
    G.finish(true, string.format("reached: %s | open (skipped): %s",
                                 table.concat(reached, ","), table.concat(skipped, ",")))
end

if (debug.getinfo(1, "S").source or "") == "main" then run() end

return {
    LEGS = LEGS,
    -- The gen3_boot_check instance THIS module bound. `dofile` re-executes, so a second dofile
    -- would hand a caller a different M with its own frame budget; exporting ours is the only
    -- way an out-of-emulator harness can reset the budget the legs actually spend.
    boot_check = G,
    walk_to = walk_to,
    pace = pace,
    state_path = state_path,
    hold_until_map_change = hold_until_map_change,
    party_snapshot = party_snapshot,
    slot_key = slot_key,
}
