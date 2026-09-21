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
--   * walking is pacing in place for encounters, holding a direction into a door, or a
--     BFS path over a collision grid parsed out of the ROM itself (see PATHS) -- every step
--     verified by G.pos, every path refusing to start from the wrong tile.
--   * terminals are RAM observables. Never a frame count, and never a one-sided one: a faint
--     needs a positive-to-zero HP transition plus the engine's own faint counter, and a PC
--     round trip needs the party record KEY back, not merely a count that returned to where it
--     started.
--
-- WHAT IS NOT PINNED (each leg repeats its own; nothing is hidden):
--   * The battle BAG now IS pinned — Right, A, Right, Right, A, A from the action menu, with
--     the balls read back from CFRU's own EWRAM pocket (docs/gen3/probes/
--     census_rr_faint_v3b_catch_2026-09-21.txt, 2026-09-21). wild_catch was OPEN for exactly
--     as long as that sequence did not exist; it is a run leg now.
--   * The PC STORAGE menu is still unpinned. It is attempted anyway, because its keyed oracle
--     cannot pass on a wrong press — unlike a count-only one.
--   * NOT map geometry, any more. RR ships no pret source but its map headers parse, so the
--     Pokémon Center walk is a BFS over the collision grid read out of the ROM (see PATHS),
--     to the same standard as the FireRed driver's paths. The screenshot estimate that
--     preceded it, and the SLINK_RR_PC_TILE knob that existed to correct it, are both gone:
--     a guess with a knob on it is still a guess.
--
-- RESUME: SLINK_GEN3_PLAY_FROM=<leg name> skips every leg before it. Because each leg loads its
-- own declared savestate, resuming is exact: there is no "assume the previous leg left the
-- right situation" hand-off anywhere in this file. SLINK_STATE overrides the FIRST leg's state
-- only (an operator trying a different capture); later legs always load what they declare.
--
-- Environment: SLINK_ROOT, SLINK_GEN3_CHECKPOINT, SLINK_GEN3_TITLE=radical_red (see
-- gen3_boot_check.lua), SLINK_STATE (path or bare file name), SLINK_STATE_DIR (default
-- E:/Howard/Bizhawk/GBA/State), SLINK_GEN3_PLAY_FROM, SLINK_SHADOW.

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(WT, "SLINK_ROOT unset — launch via the gen3 fixture/gate tooling")
local G = dofile(WT .. "/lua/tests/gen3_boot_check.lua")
local PL = dofile(WT .. "/lua/tests/playlib.lua")

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
-- RR Poke Balls are NOT in the vanilla SaveBlock1 pocket: the CFRU expanded bag puts them
-- at a fixed EWRAM base, 50 RAW ItemSlots of {u16 itemId, u16 quantity}
-- (docs/gen3/research/rr_bag_layout.md; lua/games/gen3_frlge.lua:311-314 radical_red
-- BALL_POCKET_ADDR / BALL_POCKET_ENC=false, i.e. no XOR key).
local BALL_POCKET_ADDR    = 0x0203C354
local ITEM_POKE_BALL      = 4

-- DUO-PRECEDENT CONSTANTS, NOT PROFILE FACTS. These two live in no profile and no checkpoint:
-- they are the values lua/tests/duo/scenario_explode.lua:27-28 and lua/tests/mkstate.lua:34-35
-- carry, re-validated by hand against this RR build when those scenarios were written. Treat a
-- mismatch as a build change, not as a bug here: the only thing that depends on them is
-- detecting the action-select menu, and every leg's actual terminal is a profile fact.
local CTRL_ADDR   = 0x03004FE0          -- gBattlerControllerFuncs[0]
local ACTION_MENU = 0x0802E439          -- the action-select controller function

local function battle_outcome() return memory.read_u8(BATTLE_OUTCOME_ADDR) end
local function player_faints() return memory.read_u8(BATTLE_RESULTS_ADDR + FAINTS_OFF) end
--- The PLAYER battler's HP. Battler 0 is the player side in singles; gBattleMons[0] is what the
--- explode duo reads for exactly this purpose (scenario_explode.lua:50-52).
local function player_bmon_hp() return memory.read_u16_le(BATTLE_MONS_ADDR + BM_HP) end
local function player_bmon_maxhp() return memory.read_u16_le(BATTLE_MONS_ADDR + BM_MAXHP) end
local function at_action_menu() return memory.read_u32_le(CTRL_ADDR) == ACTION_MENU end
--- (itemId, quantity) of ball-pocket slot 0.
local function ball_slot0()
    return memory.read_u16_le(BALL_POCKET_ADDR), memory.read_u16_le(BALL_POCKET_ADDR + 2)
end

-- ── PATHS: parsed from the RR BINARY, never from a screenshot ─────────────────────────────────
-- RR has no pret map source, but it does have map data, and that is not the same thing as
-- having none: the headers parse. Pokemon Center 1F (group 5, map 4) was read straight out of
-- patch/build/slink_RR.gba -- gMapGroups 0x083526A8 -> the group 5 / map 4 header 0x08350E30 ->
-- layout 0x082D5990 (15x10) -> blocks 0x082D5864, with the tileset metatile attributes at
-- 0x082AFFB4 / 0x082B4A50. The ONLY MB_PC (0x83) metatile on the map is (11,1), so the
-- approach tile is (11,2) facing Up -- FireRed's tile after all.
--
-- The earlier greedy walk failed not because the target was wrong but because a greedy walker
-- cannot see a wall: column 11 is collision at rows 6-7, and NPCs stand at (10,6) and (12,5).
-- This is a BFS over the parsed collision grid with the NPC spawn tiles blocked, which is the
-- same standard the FireRed driver holds its paths to.
--
--   collision rows 0-9   "#.#############" / "###########P###" / "....###..##...." /
--                        "....#######...." / "..............." / "..............." /
--                        "#..........##.." / "...........##.." / "..............." /
--                        "###############"      (P = the PC metatile at (11,1))
--   NPC spawn tiles      (2,3) (4,7) (7,2) (8,2) (10,6) (12,5)
--
-- REPRODUCE IT, do not trust this comment. tools/gba_map.py (card T2) is the shared parser
-- that emits entries like this one from any FR-based ROM, and it re-derives every number above
-- independently:
--
--   python tools/gba_map.py patch/build/slink_RR.gba --map 5.4 --bfs 11,8 11,2 --          --find-behaviour 0x83
--   -> map 5.4: 15x10, 4 warps, 20 objects, 0 coords, 0 bg
--      behaviour 0x83 tiles: [(11, 1)]
--      bfs (11, 8) -> (11, 2): ['Left','Up','Left','Up','Up','Up','Right','Right','Up','Up']
--
-- tests/unit/test_gen3_rr_scripted_play.py re-walks the dirs below against the same grid, so
-- the path cannot drift away from the map it came from.
local PATHS = {
    pokecenter_start_to_pc = {
        map = "PokemonCenter_1F (group 5, map 4)",
        from = { 11, 8 },            -- where slink_pokecenter_full.State stands
        to = { 11, 2 },              -- the approach tile below the PC metatile (11,1)
        dirs = { "Left", "Up", "Left", "Up", "Up", "Up", "Right", "Right", "Up", "Up" },
    },
}

-- Bind the shared scripted-play runtime (lua/tests/playlib.lua): the in_battle polarity
-- wrapper, on_field, the A-only mash, the nil-safe map id, state_path and the leg runner
-- all live there now, with the Gen 3 helper module and the game facts injected.
local play = PL.bind(G, {
    paths            = PATHS,
    party_count_addr = PARTY_COUNT_ADDR,
    obj_events       = 0x02036E38,   -- gObjectEvents (RR keeps the vanilla address,
                                     -- reference_rr_object_events)
    state_dir        = "E:/Howard/Bizhawk/GBA/State",
})

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
    local snap = { n = play.party_count(), keys = {}, order = {} }
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

--- Hold `dir` into a door/edge until the SaveBlock1 map id changes, then wait for the field to
--- settle. Returns ok, detail.
---
--- BOTH map reads must be VALID. G.map returns -1,-1 whenever the SaveBlock1 pointer is not a
--- sane EWRAM address (mid-warp, mid-load), and an unreadable map compared against a readable
--- one looks exactly like a warp. Treating that as success would let this leg pass while the
--- engine was in the middle of nothing at all.
local function hold_until_map_change(cp, dir, budget)
    local from = play.readable_mapid(cp)
    if from == nil then
        return false, "the SaveBlock1 map id is unreadable before the warp (G.map = -1,-1)"
    end
    for _ = 1, (budget or 30) do
        if play.readable_mapid(cp) ~= nil and play.readable_mapid(cp) ~= from then break end
        for _ = 1, 24 do joypad.set({ [dir] = true }); G.advance() end
        if play.readable_mapid(cp) == from then for _ = 1, 2 do G.tap("A", 3, 13) end end
    end
    joypad.set({})
    local to = play.readable_mapid(cp)
    if to == nil then
        return false, string.format("the map id went unreadable and never came back (from %d)", from)
    end
    if to == from then
        return false, string.format("map never changed from %d", from)
    end
    local settled = false
    for _ = 1, 900 do                       -- the warp fade must actually finish
        if play.on_field(cp) and play.readable_mapid(cp) ~= nil then settled = true; break end
        G.advance()
    end
    if not settled then
        return false, string.format("map %d -> %d but the field never settled "
                                    .. "(in_battle=%s callback2_ok=%s)", from, to,
                                    tostring(play.in_battle(cp)), tostring(G.pred_ok(cp, "callback2")))
    end
    return true, string.format("map %d -> %d", from, to)
end

--- Leave whatever battle we are in (or return immediately if we are not in one).
local function leave_battle(cp, taps)
    return play.mash_a(taps or 900, function() return play.on_field(cp) end)
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

local LEGS = {}

--- Shared precondition: on the walkable field with a readable map id.
local function check_on_field(cp)
    if play.in_battle(cp) then return "a battle is in progress" end
    if not play.on_field(cp) then return "not on the walkable field (callback2 is not CB2_Overworld)" end
    if play.readable_mapid(cp) == nil then return "the SaveBlock1 map id is unreadable" end
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
        if not play.in_battle(cp) then
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
                tostring(play.in_battle(cp)), tostring(G.pred_ok(cp, "callback2")), battle_outcome()))
        end
        local px, py = G.pos(cp)     -- G.pos returns TWO values; capture or a later arg eats them
        G.phase("field", string.format("map=%s at=(%d,%d) outcome=%d",
                                       tostring(play.readable_mapid(cp)), px, py, battle_outcome()))
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
        if play.readable_mapid(cp) == nil then return "the SaveBlock1 map id is unreadable" end
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
            if not pace(cp, 4000, function() return play.in_battle(cp) end) then
                G.shot("stuck")
                local px, py = G.pos(cp)
                G.finish(false, string.format(
                    "wild_faint: no wild encounter while pacing (cycle %d, map=%s at=(%d,%d)) — "
                    .. "SLINK_STATE must be a state standing in TALL GRASS",
                    enc, tostring(play.readable_mapid(cp)), px, py))
            end
            -- THE FAINT ORACLE. A zero HP read on its own proves nothing: gBattleMons is stale
            -- between battles and zero is also what an uninitialised struct reads. So require a
            -- POSITIVE-TO-ZERO TRANSITION, both samples taken while inBattle is set, and then
            -- corroborate with the engine's own gBattleResults.playerFaintCounter.
            local saw_positive = false
            local saw_zero = false
            local turns = 0
            local function sample()
                if not play.in_battle(cp) then return end
                local hp, maxhp = player_bmon_hp(), player_bmon_maxhp()
                if maxhp == 0 then return end        -- struct not loaded: not a reading
                if hp > 0 then saw_positive = true
                elseif saw_positive then saw_zero = true end
            end
            while play.in_battle(cp) and turns < 40 do
                turns = turns + 1
                play.mash_a(60, function()
                    sample(); return at_action_menu() or not play.in_battle(cp)
                end)
                if not play.in_battle(cp) then break end
                G.tap("A", 3, 13)       -- FIGHT  (gActionSelectionCursor resets per battle)
                G.tap("A", 3, 13)       -- move slot 1
                for _ = 1, 120 do
                    sample()
                    if at_action_menu() or not play.in_battle(cp) then break end
                    G.tap("A", 3, 13)
                end
            end
            if not leave_battle(cp, 900) then
                G.shot("stuck")
                G.finish(false, string.format(
                    "wild_faint: encounter %d never returned to the field (in_battle=%s)",
                    enc, tostring(play.in_battle(cp))))
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
            faints_before, player_faints(), play.party_count()))
    end,
}

-- ── leg: wild_catch ────────────────────────────────────────────────────────────────────────
-- PINNED PHYSICALLY 2026-09-21, after a research round that started with this leg OPEN because
-- no RR bag sequence existed anywhere in the tree. It does now.
LEGS[#LEGS + 1] = {
    name = "wild_catch",
    state = "slink_prebattle_balls.State",
    exercises = { "capture_wild", "battle_end" },
    source = {
        "docs/gen3/probes/census_rr_faint_v3b_catch_2026-09-21.txt (INPUT PIN: at the action menu Right (BAG), A, Right, Right (Items -> Key Items -> Poke Balls), A (select), A (use); the throw resolved to Gotcha! ~900 frames later)",
        "docs/gen3/research/rr_bag_layout.md (RR balls live at fixed EWRAM 0x0203C354, 50 raw ItemSlots of {u16 id, u16 qty}; Poke Ball is item 4 -- NOT the vanilla SaveBlock1 pocket, which is why the FR bag handling does not carry over)",
        "lua/tests/mkstate_gen3_rr_fill.lua (SLINK_GIVE_BALLS writes that pocket; it produced slink_prebattle_balls.State)",
        "docs/gen3_engine_sites.md capture_wild row (rr PINNED 0802D824/+4, Cmd_givecaughtmon immediately after BL GiveMonToPlayer)",
        "lua/games/gen3_frlge.lua:206,311-314 (radical_red BATTLE_OUTCOME_ADDR 0x02023E8A; BALL_POCKET_ADDR 0x0203C354, BALL_POCKET_ENC=false)",
    },
    -- The fixture IS the precondition. A run that opens the BAG with no balls in it wanders
    -- through a menu it cannot use and fails 400 frames later with something misleading, so
    -- read the pocket first and say the one useful thing instead.
    check = function(cp)
        local id, qty = ball_slot0()
        if id ~= ITEM_POKE_BALL or qty == 0 then
            return string.format(
                "the RR ball pocket (0x%08X) slot 0 holds item %d x%d, not Poke Ball (id %d) "
                .. "with qty > 0 -- make the balls state first: run "
                .. "lua/tests/mkstate_gen3_rr_fill.lua with SLINK_GIVE_BALLS and save it as "
                .. "slink_prebattle_balls.State", BALL_POCKET_ADDR, id, qty, ITEM_POKE_BALL)
        end
        return nil
    end,
    run = function(cp)
        local before_party = play.party_count()
        local _, balls = ball_slot0()
        G.phase("balls", string.format("pocket slot 0 = Poke Ball x%d, party=%d",
                                       balls, before_party))

        if not play.in_battle(cp) then
            if not pace(cp, 4000, function() return play.in_battle(cp) end) then
                G.shot("stuck")
                G.finish(false, "wild_catch: no wild encounter while pacing -- "
                             .. "slink_prebattle_balls.State must be standing in TALL GRASS")
            end
        end

        -- One throw per ball. A MISS returns to the action menu, so the whole sequence simply
        -- runs again; the bound is the fixture ball count, never a frame count.
        local throws = 0
        for _ = 1, math.min(balls, 5) do
            if not play.in_battle(cp) then break end
            if not play.mash_a(200, function()
                return at_action_menu() or not play.in_battle(cp)
            end) then
                G.shot("stuck")
                G.finish(false, string.format(
                    "wild_catch: the action menu never appeared (throw %d)", throws + 1))
            end
            if not play.in_battle(cp) then break end     -- it fled, or our mon fainted
            throws = throws + 1
            -- THE PINNED SEQUENCE (see the census receipt cited above). Each press is a
            -- separate tap on the 16-frame native-menu cadence, never a held direction: the
            -- pocket tabs advance one per press.
            G.tap("Right", 3, 20)       -- action menu: FIGHT -> BAG
            G.tap("A", 3, 20)           -- open the BAG
            G.tap("Right", 3, 20)       -- pocket: Items -> Key Items
            G.tap("Right", 3, 20)       -- pocket: Key Items -> Poke Balls
            G.tap("A", 3, 20)           -- select the Poke Ball
            G.tap("A", 3, 20)           -- use it
            -- The throw animation plus the catch text ran ~900 frames on the receipt; a miss
            -- comes back to the action menu instead.
            play.mash_a(400, function()
                return battle_outcome() ~= 0 or at_action_menu()
            end)
            if battle_outcome() == B_OUTCOME_CAUGHT then break end
            G.phase("throw-missed", string.format("throw %d: outcome=%d, back at the menu",
                                                  throws, battle_outcome()))
        end

        if battle_outcome() ~= B_OUTCOME_CAUGHT then
            G.shot("stuck")
            G.finish(false, string.format(
                "wild_catch: %d throw(s) and gBattleOutcome is %d, not %d (B_OUTCOME_CAUGHT)",
                throws, battle_outcome(), B_OUTCOME_CAUGHT))
        end
        -- Let the catch text finish before reading the party: the acquisition happens inside
        -- Cmd_givecaughtmon, which runs while that text is still up.
        play.mash_a(600, function() return play.on_field(cp) end)

        local after_party = play.party_count()
        if before_party < 6 then
            if after_party ~= before_party + 1 then
                G.shot("stuck")
                G.finish(false, string.format(
                    "wild_catch: outcome says caught but the party went %d -> %d; with room in "
                    .. "the party the caught mon must land in it", before_party, after_party))
            end
            G.phase("caught", string.format("outcome=%d, party %d -> %d after %d throw(s)",
                                            battle_outcome(), before_party, after_party, throws))
        else
            -- A full party sends the catch to a box (that is the pc_move site). There is no
            -- decrypt-free box-count observable pinned for RR, so this branch is REPORTED, not
            -- asserted -- see the pc_move_full_party leg.
            G.phase("caught", string.format(
                "outcome=%d with a full party (%d): the mon went to a box, which this leg "
                .. "cannot read back", battle_outcome(), before_party))
        end
    end,
}

-- ── leg: pc_move_full_party (OPEN) ─────────────────────────────────────────────────────────
LEGS[#LEGS + 1] = {
    name = "pc_move_full_party",
    state = "slink_prebattle.State",
    exercises = { "pc_move", "mon_given" },
    open = true,
    open_reason = "SendMonToPC (RR: the compressed-storage detour at 090B6E38) only runs on an "
               .. "ACQUISITION that cannot fit in the party — a catch or a gift with SIX party "
               .. "mons. wild_catch now supplies the catch, but no savestate in the family "
               .. "carries a full party, and RR 58-byte CompressedPokemon boxes have no "
               .. "decrypt-free count observable pinned, so the result could not be read back "
               .. "even if it fired",
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
    state = "slink_pokecenter_full.State",
    exercises = { "pc_deposit", "pc_box_place", "pc_withdraw" },
    source = {
        "lua/tests/mkstate.lua:270-300 (the pokecenter state family is captured inside a map the companion patch recognises as a Pokémon Center 1F — it spawns its trade NPC there, which is how the state is verified); slink_pokecenter_full.State stands at (11,8) with a party of 3",
        "patch/build/slink_RR.gba parsed directly: gMapGroups 0x083526A8 -> group 5 map 4 header 0x08350E30 -> layout 0x082D5990 (15x10) -> blocks 0x082D5864, tileset attributes 0x082AFFB4 / 0x082B4A50; the only MB_PC (0x83) metatile is (11,1), approach (11,2)",
        "docs/gen3_engine_sites.md pc_deposit row (rr PINNED 0809315C/+8, TryStorePartyMonInBox +0x80 with R0==1)",
        "docs/gen3_engine_sites.md pc_box_place row (rr PINNED 08093018/+8; RR IN-PLACE wrapper, capture 08093020, SetBoxMonAt detours to 090B6CA4)",
        "docs/gen3_engine_sites.md pc_withdraw row (rr PINNED 08092FF2/+6; RR IN-PLACE, party sentinel 25 not vanilla 14)",
        "lua/tests/duo/duo_main.lua:23-24 (PID/OTID offsets — the party record key this leg's oracle follows)",
    },
    check = check_on_field,
    run = function(cp)
        -- BFS-pinned from the parsed map (see PATHS above), not a greedy walk toward a
        -- screenshot estimate: follow() asserts the start tile and verifies every step.
        play.follow(cp, "pokecenter_start_to_pc", "pc_ops")
        G.tap("Up", 2, 13)               -- face the (solid) PC metatile without stepping onto it

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
            if play.party_count() < before.n then deposited = true; break end
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
            if play.party_count() > mid.n then withdrawn = true; break end
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
            if play.on_field(cp) then out_ok = true; break end
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

local function run()
    play.main(LEGS, {
        name   = "gen3_rr_scripted_play",   -- patch/build/gen3_rr_scripted_play_result.txt
        budget = 900000,
        -- No boot step: RR's maps are unmapped, so there is no walk from a fixture battery to
        -- any of these situations. Every leg names the savestate the runner loads for it.
        shadow = {
            script = WT .. "/lua/gen3/shadow_run.lua",
            result = WT .. "/patch/build/gen3_rr_scripted_play_result.txt",
            name   = "SLink-gen3-rr-shadow-poll",
        },
    })
end

if (debug.getinfo(1, "S").source or "") == "main" then run() end

return {
    LEGS = LEGS,
    PATHS = PATHS,
    play = play,
    -- The gen3_boot_check instance THIS module bound. `dofile` re-executes, so a second dofile
    -- would hand a caller a different M with its own frame budget; exporting ours is the only
    -- way an out-of-emulator harness can reset the budget the legs actually spend.
    boot_check = G,
    pace = pace,
    state_path = play.state_path,
    hold_until_map_change = hold_until_map_change,
    party_snapshot = party_snapshot,
    slot_key = slot_key,
}
