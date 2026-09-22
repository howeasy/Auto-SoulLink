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
local JSON = dofile(WT .. "/lua/json_codec.lua")
local Reads = dofile(WT .. "/lua/gen3/reads.lua")
local profile_file = assert(io.open(WT .. "/data/games/gen3_rr/profile.json", "rb"))
local profile = assert(JSON.decode(profile_file:read("a"))).titles.radical_red
profile_file:close()
assert(profile.admitted and profile.derived.CFRU_COMPRESSED_BOX
       and profile.derived.CFRU_NO_ENCRYPT, "RR compressed box profile is not admitted")
local box_bases = assert(profile.derived.CFRU_BOX_BASES)
local box_count = assert(profile.derived.BOXES_PER_STORE)
local box_stride = assert(profile.derived.COMPRESSED_MON_SIZE)
assert(#box_bases == box_count and box_stride == Reads.COMPRESSED_MON_SIZE,
       "RR compressed box layout disagrees with reads.lua")
local function read_bytes(addr, count)
    local bytes = {}
    for i = 1, count do bytes[i] = memory.read_u8(addr + i - 1) end
    return bytes
end
local reader = Reads.new(profile, {
    read_u8 = memory.read_u8, read_u32 = memory.read_u32_le, read_bytes = read_bytes,
})

-- ── RR RAM observables ─────────────────────────────────────────────────────────────────────
-- PROFILE FACTS: these come from the radical_red profile (lua/games/gen3_frlge.lua:192-260 /
-- data/games/gen3_rr/profile.json). CFRU keeps the vanilla EWRAM battle globals; that is stated
-- in the profile and relied on by the shipping client, not assumed here.
local PARTY_COUNT_ADDR    = 0x02024029  -- radical_red.PARTY_COUNT_ADDR (gPlayerPartyCount)
local PARTY_BASE          = 0x02024284  -- radical_red.PARTY_BASE (gPlayerParty)
local BATTLE_MONS_ADDR    = 0x02023BE4  -- radical_red.BATTLE_MONS_ADDR (gBattleMons)
local BATTLE_OUTCOME_ADDR = 0x02023E8A  -- radical_red.BATTLE_OUTCOME_ADDR (gBattleOutcome)
local BATTLE_RESULTS_ADDR = 0x03004F90  -- radical_red.BATTLE_RESULTS_ADDR (gBattleResults)
local ENEMY_BASE          = assert(profile.ram.ENEMY_BASE)
local BATTLER_INDEX_ADDR  = assert(profile.ram.BATTLER_PARTY_INDEXES_ADDR)
local BATTLER_POS_ADDR    = 0x02023BD6  -- gBattlerPositions (pret pokefirered.sym:81)
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
local play

-- These are game-fact projections; playlib still owns the generic keyed comparison and pacing.
-- reads.lua decodes each 0x3A-byte compressed record from profile.derived.CFRU_BOX_BASES.
local function owned_snapshot(label)
    local party = play.party_snapshot()
    local mons, why = reader.read_party()
    if not mons or #mons ~= party.n then
        G.finish(false, label .. ": unreadable party: " .. tostring(why))
    end
    local owned = {party = party, mons = {}, boxes = {}}
    for i, mon in ipairs(mons) do
        local key = reader.key(mon)
        if mon.species == 0 or mon.has_species ~= 1 or owned.mons[key]
           or key ~= party.order[i] then
            G.finish(false, label .. ": ambiguous or invalid party record " .. key)
        end
        owned.mons[key] = {species = mon.species, personality = mon.personality}
    end
    for box = 0, box_count - 1 do
        local records, bad = reader.read_box(box)
        if not records then G.finish(false, label .. ": unreadable box: " .. tostring(bad)) end
        for slot, mon in ipairs(records) do
            if mon.species ~= 0 then
                local key = reader.key(mon)
                if mon.has_species ~= 1 or owned.mons[key] or owned.boxes[key] then
                    G.finish(false, label .. ": ambiguous or invalid box record " .. key)
                end
                local addr = box_bases[box + 1] + (slot - 1) * box_stride
                owned.boxes[key] = {box = box, slot = slot - 1, species = mon.species,
                                    personality = mon.personality,
                                    raw = string.char(table.unpack(read_bytes(addr, box_stride)))}
            elseif mon.has_species ~= 0 then
                G.finish(false, label .. ": empty box record has species flag")
            end
        end
    end
    return owned
end

local function boxes_unchanged(label, before, after, except)
    for key, old in pairs(before) do
        if key ~= except then
            local new = after[key]
            if not new or old.box ~= new.box or old.slot ~= new.slot or old.raw ~= new.raw then
                G.finish(false, label .. ": box record changed or disappeared: " .. key)
            end
        end
    end
    for key in pairs(after) do
        if key ~= except and not before[key] then
            G.finish(false, label .. ": unexpected box addition: " .. key)
        end
    end
end

local function field_ready(cp)
    return play.on_field(cp) and G.pred_ok(cp, "script_context_status")
           and G.pred_ok(cp, "field_controls_locked")
end

local function stable_field(cp, expected_map, x, y, budget)
    local stable = 0
    for _ = 1, budget do
        local px, py = G.pos(cp)
        if field_ready(cp) and play.map(cp) == expected_map
           and (x == nil or (px == x and py == y)) then
            stable = stable + 1
            if stable >= 16 then return true end
        else
            stable = 0
        end
        G.advance()
    end
    return false
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
--   python tools/gba_map.py patch/build/slink_RR.gba --map 5.4 --bfs 7,8 11,2 --find-behaviour 0x83
--   -> map 5.4: 15x10, 4 warps, 20 objects, 0 coords, 0 bg
--      behaviour 0x83 tiles: [(11, 1)]
--      bfs (7, 8) -> (11, 2): ['Up','Up','Up','Up','Right','Right','Right','Right','Up','Up']
--
-- tests/unit/test_gen3_rr_scripted_play.py re-walks the dirs below against the same grid, so
-- the path cannot drift away from the map it came from.
local PATHS = {
    pokecenter_start_to_pc = {
        map = "PokemonCenter_1F (group 5, map 4)",
        from = { 7, 8 },             -- where slink_pokecenter_full.State stands (the PLAIN
                                     -- slink_pokecenter.State is at (11,8), after its own walk)
        to = { 11, 2 },              -- the approach tile below the PC metatile (11,1)
        dirs = { "Up", "Up", "Up", "Up", "Right", "Right", "Right", "Right", "Up", "Up" },
    },
}

-- ── the Gen 3 binding ────────────────────────────────────────────────────────────────────────
-- playlib holds no host call and no game fact (Codex review cx-67a6e199): no memory, joypad,
-- client, event, savestate or dofile appears in it. Everything it needs arrives here.
local H = {
    advance = G.advance, idle = G.idle, tap = G.tap, pos = G.pos,
    phase = G.phase, finish = G.finish, shot = G.shot, open = G.open,
    checkpoint = G.checkpoint,
    press      = function(buttons) joypad.set(buttons); G.advance() end,
    speed_max  = function() client.speedmode(6399) end,
    set_budget = function(n) G.budget = n end,

    -- nil when the SaveBlock1 pointer is not a sane EWRAM address (G.map's -1,-1): playlib
    -- compares map ids and must never read "cannot read" as "changed".
    map = function(cp)
        local g, n = G.map(cp)
        if g < 0 or n < 0 then return nil end
        return g * 256 + n
    end,

    -- POLARITY: the in_battle row is a mask with expect=0, so G.pred_ok is TRUE when we are
    -- NOT in a battle (data/games/gen3_rr/write_checkpoint.json radical_red.predicates).
    in_battle   = function(cp) return not G.pred_ok(cp, "in_battle") end,
    on_field    = function(cp)
        return G.pred_ok(cp, "in_battle") and G.pred_ok(cp, "callback2")
    end,
    scene_quiet = function(cp)
        return G.pred_ok(cp, "script_context_status") and G.pred_ok(cp, "field_controls_locked")
    end,

    party_count = function() return memory.read_u8(PARTY_COUNT_ADDR) end,
    party_key = function(i)
        local base = PARTY_BASE + i * MON_SIZE
        return string.format("%08X:%08X", memory.read_u32_le(base + OFF_PID),
                                          memory.read_u32_le(base + OFF_OTID))
    end,
    party_record = function(i)
        local base = PARTY_BASE + i * MON_SIZE
        local parts = {}
        for w = 0, (MON_SIZE // 4) - 1 do
            parts[#parts + 1] = string.format("%08X", memory.read_u32_le(base + w * 4))
        end
        return table.concat(parts)
    end,
    load_state  = function(path) return (pcall(savestate.load, path)) end,
    save_state  = function(path) return (pcall(savestate.save, path)) end,
    register_frame_end = function(fn, name)
        -- Return what the host returned, and NOTHING else. `id or name` fabricated a handle
        -- whenever onframeend returned nil, which sailed past playlib's "was it registered?"
        -- check and then handed a NAME to unregisterbyid (Codex cx-bc675fa4). An observer
        -- nobody polls must fail the run, not look registered.
        local ok, id = pcall(event.onframeend, fn, name)
        if not ok then return nil end
        return id
    end,
    unregister_frame_end = function(id) pcall(event.unregisterbyid, id) end,
    observer = function(result)
        local ok, shd = pcall(dofile, WT .. "/lua/gen3/shadow_run.lua")
        if not ok or not shd then return nil, "dofile lua/gen3/shadow_run.lua: " .. tostring(shd) end
        local ok2, st = pcall(shd.start, { duo = { result = result, player = "a" } })
        if not ok2 or not st then return nil, "shadow_run.start: " .. tostring(st) end
        return {
            poll   = st.poll,
            status = function() return st.parts.signals:status() end,
            detail = "admitted_by=" .. tostring(st.admitted_by),
        }
    end,
}

play = PL.bind(H, {
    paths     = PATHS,
    state_dir = "E:/Howard/Bizhawk/GBA/State",
    -- How RR fights a battle a walk did not choose: the action cursor resets to FIGHT, so A, A
    -- is move slot 1 and A advances the text afterwards. A Gen 3 fact, injected rather than
    -- assumed by the library.
    -- Input policy, not library policy: which button dismisses a textbox and which advances a
    -- scripted scene are per-game facts, same as opts.battle (Codex cx-bc675fa4).
    clear_dialogue = function() for _ = 1, 4 do G.tap("A", 3, 13) end end,
    advance_scene  = function() G.tap("A", 2, 10) end,
    -- Backing out of a menu, one press. playlib owns the RULE (dismiss until the field
    -- appears, keep dismissing through the exit textbox, settle, re-check); the button and its
    -- spacing are ours.
    menu_back = function(_, gap) G.tap("B", 3, gap or 20) end,
    battle = function(cp, budget)
        if not play.mash_a(budget or 1200, function() return not H.in_battle(cp) end) then
            return false
        end
        return play.wait_scene_settled(cp, 1800)
    end,
})

-- The keyed PC oracle's reasoning lives in playlib (party_snapshot / departed_key /
-- survivors_intact); only these READS are RR's, and they are injected above as party_key and
-- party_record. PID:OTID is the identity the duo harness follows a mon by
-- (lua/tests/duo/duo_main.lua:86-98): plaintext, and it survives the box round trip that RR's
-- 58-byte CompressedPokemon makes lossy for the record's bytes.

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
    if play.map(cp) == nil then return "the SaveBlock1 map id is unreadable" end
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
                                       tostring(play.map(cp)), px, py, battle_outcome()))
    end,
}

-- ── leg: wild_faint ────────────────────────────────────────────────────────────────────────
LEGS[#LEGS + 1] = {
    name = "wild_faint",
    state = "slink_prebattle.State",
    exercises = { "faint", "battle_begin", "battle_end" },
    source = {
        "lua/tests/mkstate.lua:143-180 (slink_prebattle.State is captured IN TALL GRASS, the last in-grass position before an encounter — so pacing here is a real wild-encounter source)",
        "data/games/gen3_rr/engine_signals.json faint row (RR cleanup completion 0909EED2; old vanilla Cmd_tryfaintmon site did not fire on RR)",
        "lua/games/gen3_frlge.lua:138-142 + data/games/gen3_rr/profile.json BATTLE_RESULTS_ADDR (gBattleResults.playerFaintCounter @ +0) — the ENGINE's own faint tally, which a host HP poke does not move",
        "lua/tests/duo/scenario_explode.lua:22-28,50-52 (gBattleMons[0] = the player battler; hp @ +0x28, maxHP @ +0x2C)",
    },
    check = function(cp)
        if play.map(cp) == nil then return "the SaveBlock1 map id is unreadable" end
        return nil     -- prebattle is mid-encounter by construction; run() clears it first
    end,
    run = function(cp)
        if not leave_battle(cp, 1200) then
            G.shot("stuck")
            G.finish(false, "wild_faint: could not get back to the field from the loaded state")
        end
        local ENCOUNTERS = 12
        local fainted = false
        local last_baseline = 0
        for enc = 1, ENCOUNTERS do
            if not pace(cp, 4000, function() return play.in_battle(cp) end) then
                G.shot("stuck")
                local px, py = G.pos(cp)
                G.finish(false, string.format(
                    "wild_faint: no wild encounter while pacing (cycle %d, map=%s at=(%d,%d)) — "
                    .. "SLINK_STATE must be a state standing in TALL GRASS",
                    enc, tostring(play.map(cp)), px, py))
            end
            -- THE FAINT ORACLE. A zero HP read on its own proves nothing: gBattleMons is stale
            -- between battles and zero is also what an uninitialised struct reads. So require a
            -- POSITIVE-TO-ZERO TRANSITION, both samples taken while inBattle is set, and then
            -- corroborate with the engine's own gBattleResults.playerFaintCounter.
            local saw_positive = false
            local saw_zero = false
            local turns = 0
            local battler_key, battler_slot, baseline
            local function sample()
                if not play.in_battle(cp) then return end
                local hp, maxhp = player_bmon_hp(), player_bmon_maxhp()
                if maxhp == 0 then return end        -- struct not loaded: not a reading
                local slot = memory.read_u8(BATTLER_INDEX_ADDR)
                if (memory.read_u8(BATTLER_POS_ADDR) & 1) ~= 0 or slot >= play.party_count() then
                    G.finish(false, "wild_faint: battler 0 is not a readable player party mon")
                end
                local key = H.party_key(slot)
                if hp > 0 and not saw_positive then
                    battler_slot, battler_key = slot, key
                    baseline = player_faints()  -- RR resets this counter at EACH battle start
                    last_baseline = baseline
                    saw_positive = true
                elseif saw_positive and (slot ~= battler_slot or key ~= battler_key) then
                    G.finish(false, "wild_faint: the sampled player battler changed identity")
                elseif hp == 0 and saw_positive then
                    saw_zero = true
                end
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
            if saw_zero and player_faints() > baseline then fainted = true; break end
            G.phase("survived", string.format(
                "encounter %d: hp_positive=%s hp_zero=%s faints %d->%d outcome=%d key=%s",
                enc, tostring(saw_positive), tostring(saw_zero),
                last_baseline, player_faints(), battle_outcome(), tostring(battler_key)))
        end
        if not fainted then
            G.shot("stuck")
            G.finish(false, string.format(
                "wild_faint: no witnessed player faint in %d wild encounters (playerFaintCounter "
                .. "%d -> %d). The party mon in this savestate may simply keep winning — RR's "
                .. "starting party is whatever the battery save carries, and nothing here weakens "
                .. "it. Re-run with a save whose lead is under-levelled for the route.",
                ENCOUNTERS, last_baseline, player_faints()))
        end
        G.phase("fainted", string.format(
            "same player battler went positive -> 0 HP; playerFaintCounter %d -> %d; party=%d",
            last_baseline, player_faints(), play.party_count()))
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
        "data/games/gen3_rr/engine_signals.json capture_wild row (RR replacement capture at 0907DD88 after GiveMonToPlayer; old vanilla site is displaced)",
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
        local before = owned_snapshot("wild_catch before")
        local before_party = before.party.n
        local source_map = play.map(cp)
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
        if battle_outcome() ~= 0 then
            G.finish(false, "wild_catch: battle outcome was not 0 before this catch")
        end
        local enemy, bad = reader.decode_party_mon(read_bytes(ENEMY_BASE, MON_SIZE))
        if not enemy or enemy.species == 0 or enemy.has_species ~= 1 then
            G.finish(false, "wild_catch: unreadable enemy identity: " .. tostring(bad))
        end

        -- One throw per ball. A MISS returns to the action menu, so the whole sequence simply
        -- runs again; the bound is the fixture ball count, never a frame count.
        local throws = 0
        for _ = 1, math.min(balls, 5) do
            if not play.in_battle(cp) then break end
            -- WAIT FOR THE ACTION MENU ITSELF. The lane pressed the bag sequence into the
            -- battle INTRO (slink_prebattle_balls.State is captured mid-intro) and reported
            -- "ball not thrown, pocket still 5": the old condition was "menu OR not in battle",
            -- and the second half let the sequence fire while no menu was up. Only the menu
            -- means the menu.
            local menu = false
            for _ = 1, 300 do
                if at_action_menu() then menu = true; break end
                if not play.in_battle(cp) then break end
                G.tap("A", 3, 13)
            end
            if not play.in_battle(cp) then break end     -- it fled, or our mon fainted
            if not menu then
                G.shot("stuck")
                G.finish(false, string.format(
                    "wild_catch: the action menu never appeared (throw %d); CTRL reads 0x%08X, "
                    .. "not the action-select controller 0x%08X",
                    throws + 1, memory.read_u32_le(CTRL_ADDR), ACTION_MENU))
            end
            throws = throws + 1
            -- The pocket baseline is taken BEFORE a single button is pressed: the ball leaves
            -- the pocket on the very press that ends the sequence, so reading it afterwards
            -- races the thing it is meant to witness.
            local _, qty_before = ball_slot0()
            -- THE PINNED SEQUENCE, WITH THE PROBE'S OWN TIMING. Buttons alone were not enough:
            -- run 15 still reported "ball not thrown, pocket 5" with the presses right and a
            -- flat ~16-frame cadence. The probe that PHYSICALLY threw a ball
            -- (lua/tests/probe_gen3_rr_bag.lua, script
            -- "menu,Right,wait16,A,wait90,Right,wait20,Right,wait20,A,wait30,A,wait900")
            -- spaces them unevenly for a reason: CFRU's bag takes ~90 frames to open after the
            -- A, and each pocket tab needs ~20 frames to settle. On a 16-frame cadence the two
            -- Rights land during the fade and are eaten, so the cursor never leaves the ITEMS
            -- pocket and the final A uses nothing.
            --
            -- Mirrored exactly: G.tap(btn, 3, 13) is the probe's own press (3 held + 13 idle),
            -- and the idle after each is the probe's waitN.
            G.tap("Right", 3, 13); G.idle(16)   -- action menu: FIGHT -> BAG
            G.tap("A", 3, 13);     G.idle(90)   -- open the BAG (the slow one)
            G.tap("Right", 3, 13); G.idle(20)   -- pocket: Items -> Key Items
            G.tap("Right", 3, 13); G.idle(20)   -- pocket: Key Items -> Poke Balls
            G.tap("A", 3, 13);     G.idle(30)   -- select the Poke Ball
            G.tap("A", 3, 13)                   -- use it
            -- THE THROW WITNESS IS THE POCKET, NOT THE MENU. Lane run: all five throws were
            -- called misses at 170-frame spacing, which is this leg judging the result before
            -- the ball animation had even started — the action-select controller is still the
            -- last thing written, so "the menu is back" reads true immediately. The physical
            -- probe needed ~900 frames after the second A to reach "Gotcha!".
            --
            -- A thrown ball is SPENT: the quantity at slot 0 decrements. That is an engine
            -- fact rather than a timing guess, so wait for it FIRST and only then judge.
            local thrown = false
            for _ = 1, 300 do
                local _, q = ball_slot0()
                if q < qty_before then thrown = true; break end
                G.advance()
            end
            if not thrown then
                G.shot("stuck")
                G.finish(false, string.format(
                    "wild_catch: ball not thrown on throw %d — the pocket still holds %d, so "
                    .. "the pinned bag sequence never reached USE", throws, qty_before))
            end
            -- The ball is in the air now. A catch ends the battle (outcome ~= 0); a miss hands
            -- control back to the action menu, and that only counts once the ball is gone.
            play.mash_a(1200, function()
                return battle_outcome() ~= 0 or at_action_menu()
            end)
            local _, qty_after = ball_slot0()
            if battle_outcome() == B_OUTCOME_CAUGHT then
                G.phase("throw-caught", string.format("throw %d: outcome=%d balls %d -> %d",
                                                      throws, battle_outcome(), qty_before, qty_after))
                break
            end
            G.phase("throw-missed", string.format(
                "throw %d: outcome=%d balls %d -> %d, back at the menu",
                throws, battle_outcome(), qty_before, qty_after))
        end

        if battle_outcome() ~= B_OUTCOME_CAUGHT then
            G.shot("stuck")
            G.finish(false, string.format(
                "wild_catch: %d throw(s) and gBattleOutcome is %d, not %d (B_OUTCOME_CAUGHT)",
                throws, battle_outcome(), B_OUTCOME_CAUGHT))
        end
        -- A caught outcome is not an acquisition oracle. Require a settled field and a new
        -- PID/species in the owned party or compressed boxes; GiveMonToPlayer changes OTID.
        if not play.mash_a(2400, function() return play.on_field(cp) end)
           or not stable_field(cp, source_map, nil, nil, 1200) then
            G.finish(false, "wild_catch: caught outcome never returned to a controllable field")
        end
        local after = owned_snapshot("wild_catch after")
        local after_party = after.party.n
        local new_count, new_place, new_box_key = 0, nil, nil
        for key, old in pairs(before.mons) do
            local kept = after.mons[key]
            if not kept or kept.species ~= old.species then
                G.finish(false, "wild_catch: existing party mon changed identity: " .. key)
            end
        end
        for key, mon in pairs(after.mons) do
            if not before.mons[key] then
                if mon.personality ~= enemy.personality or mon.species ~= enemy.species then
                    G.finish(false, "wild_catch: new party mon is not the caught enemy")
                end
                new_count, new_place = new_count + 1, "party"
            end
        end
        for key, mon in pairs(after.boxes) do
            if not before.boxes[key] then
                if mon.personality ~= enemy.personality or mon.species ~= enemy.species then
                    G.finish(false, string.format("wild_catch: new boxed mon is not the caught "
                        .. "enemy (pid=%08X species=%d, expected pid=%08X species=%d)",
                        mon.personality, mon.species, enemy.personality, enemy.species))
                end
                new_count, new_place, new_box_key = new_count + 1, "box", key
            end
        end
        boxes_unchanged("wild_catch", before.boxes, after.boxes, new_box_key)
        if new_count ~= 1 then
            G.finish(false, "wild_catch: caught outcome has no unique new owned record")
        end
        if before_party < 6 then
            if after_party ~= before_party + 1 or new_place ~= "party" then
                G.shot("stuck")
                G.finish(false, string.format(
                    "wild_catch: outcome says caught but the party went %d -> %d; with room in "
                    .. "the party the caught mon must land in it", before_party, after_party))
            end
            G.phase("caught", string.format("outcome=%d, party %d -> %d after %d throw(s)",
                                            battle_outcome(), before_party, after_party, throws))
        else
            if after_party ~= before_party or new_place ~= "box" then
                G.finish(false, "wild_catch: full-party catch did not add exactly one boxed mon")
            end
            G.phase("caught", string.format(
                "outcome=%d with a full party (%d): the matching mon was read back in a box",
                battle_outcome(), before_party))
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
               .. "carries a full party. The ROM-pinned compressed boxes are readable; the "
               .. "missing full-party fixture and live lane keep this kind OPEN",
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
        if play.map(cp) ~= 769 then
            G.finish(false, "door_warp: source is not the pinned outside map 769")
        end
        local ok, detail = play.enter_warp(cp, "Up", 30)
        if not ok then
            G.shot("stuck")
            local px, py = G.pos(cp)
            G.finish(false, string.format(
                "door_warp: %s (at (%d,%d)) — SLINK_STATE must be slink_door.State (standing in "
                .. "front of a Pokémon Center door, facing north)", detail, px, py))
        end
        -- The shared warp helper proves a transition, not which map won a second fade.
        -- This fixture's physical receipt fixes both map ids and the inside rest tile.
        if not stable_field(cp, 1284, 7, 8, 300) then
            G.finish(false, "door_warp: destination is not stable, controllable map 1284 at (7,8)")
        end
        local px, py = G.pos(cp)
        G.phase("warped", string.format("%s at=(%d,%d)", detail, px, py))
    end,
}

-- ── PC storage menu helpers, shared by pc_ops and pc_release ────────────────────────────────
-- FIVE A PRESSES reach the storage menu, not one: interact -> "booted up the PC" -> the PC
-- list -> row 0 (Someone's PC) -> "Accessed Someone's PC." -> "Pokemon Storage System opened."
-- The census timings are ~120 frames between them, 180 before the menu settles; those are what
-- this mirrors (docs/gen3/probes/census_rr_pc_deposit_2026-09-21.txt).
local function pc_press(btn, wait)
    G.tap(btn, 3, 13)
    G.idle(wait or 120)
end
local function open_storage_menu()
    for _ = 1, 5 do pc_press("A", 120) end
    G.idle(60)                  -- the census waited 180 in total before the menu
end
-- THE COUNT IS A LIE WHILE THE PC IS OPEN. The census read party=3 throughout the storage
-- screen even after TryStorePartyMonInBox fired: gPlayerPartyCount is recomputed on exit. So
-- every assertion in a PC leg is made on the FIELD, never in the menu, and "leave the PC" is
-- part of the operation rather than tidying up after. The leaving itself is playlib's
-- leave_menu: on_field goes true while the PC's exit textbox is still up, and stopping there
-- shifts every press of the NEXT open by one (PHYSICAL r5b/r5c -- the "withdraw" half deposited
-- again). The rule is shared; the button and the spacing are the binding's.
local function leave_storage(cp, label)
    play.leave_menu(cp, label, { flush = 5, flush_gap = 27, settle = 60 })
end

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
        "docs/gen3/probes/census_rr_pc_deposit_2026-09-21.txt (PHYSICAL: the five-A PC flow reaches Task_DepositMenu and TryStorePartyMonInBox; gPlayerPartyCount is NOT updated until the PC is closed)",
        "docs/gen3/research/rr_pc_menu.md (RR keeps the vanilla five-option storage menu with title-case labels; the earlier all-caps string search was a false negative)",
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
        local before_world = owned_snapshot("pc_ops before")
        local before = before_world.party
        if before.n < 2 then
            G.finish(false, string.format(
                "pc_ops: the party holds %d mon — the oracle needs at least 2 (one to deposit, "
                .. "one to prove the others were left byte-identical). "
                .. "slink_pokecenter_full.State carries three", before.n))
        end

        -- THE PINNED PC FLOW, FROM A PHYSICAL CENSUS.
        -- docs/gen3/probes/census_rr_pc_deposit_2026-09-21.txt drove this exact sequence on the
        -- RR companion and watched the engine reach it, hook by hook:
        --   CreatePCMenu -> ShowPokemonStorageSystemPC -> Task_PCMainMenu -> EnterPokeStorage
        --   -> Task_InitPokeStorage -> CB2_PokeStorage -> Task_DepositMenu
        --   -> TryStorePartyMonInBox (1 hit)
        -- docs/gen3/research/rr_pc_menu.md explains why the earlier "the labels are not in the
        -- ROM" finding was wrong: the search was case-blind. RR keeps the vanilla five-option
        -- table (sMainMenuTexts at ROM0x003CDA20) with TITLE-CASE labels -- Withdraw at
        -- 0x001B5859, Deposit at 0x001B586C, Move at 0x001B587E -- and retains
        -- ShowPokemonStorageSystemPC, EnterPokeStorage and Task_DepositMenu byte-for-byte.
        --
        -- DEPOSIT: Down, A picks Deposit (row 1 of Withdraw/Deposit/Move/Move Items/See Ya);
        -- Down, A picks the party mon after the lead; A confirms Store.
        open_storage_menu()
        pc_press("Down", 20); pc_press("A", 180)     -- Deposit -> EnterPokeStorage
        pc_press("Down", 20); pc_press("A", 120)     -- party slot 1 -> its context menu
        pc_press("A", 120)                           -- Store -> "Deposit in which BOX?" chooser
        pc_press("A", 240)                           -- commit box 0 -> TryStorePartyMonInBox
                                                     -- (R9: STORE opens the chooser; the census
                                                     -- pressed A, A after the slot popup)
        leave_storage(cp, "pc_ops")

        local mid_world = owned_snapshot("pc_ops after deposit")
        local mid = mid_world.party
        if mid.n ~= before.n - 1 then
            G.shot("stuck")
            G.finish(false, string.format(
                "pc_ops: after the deposit and leaving the PC the party count is %d, not %d. "
                .. "The pinned flow (5x A, Down+A, Down+A, A) reached TryStorePartyMonInBox in "
                .. "the census; if it did not here, compare against "
                .. "docs/gen3/probes/census_rr_pc_deposit_2026-09-21.txt", mid.n, before.n - 1))
        end
        local gone = nil
        for _, k in ipairs(before.order) do
            if mid.keys[k] == nil then
                if gone then
                    G.finish(false, string.format(
                        "pc_ops: the deposit removed more than one record (%s and %s) from [%s]",
                        gone, k, play.keylist(before)))
                end
                gone = k
            end
        end
        if not gone then
            G.finish(false, string.format(
                "pc_ops: the count dropped but every key is still present ([%s] -> [%s]) -- "
                .. "that is not a deposit", play.keylist(before), play.keylist(mid)))
        end
        if gone ~= before.order[2] then
            G.finish(false, "pc_ops: the deposited mon was not selected party slot 1")
        end
        if not mid_world.boxes[gone] then
            G.finish(false, "pc_ops: selected mon did not appear in a compressed box")
        end
        local kept, changed = play.survivors_intact(before, mid, gone)
        if not kept then G.finish(false, "pc_ops deposit: " .. changed) end
        boxes_unchanged("pc_ops deposit", before_world.boxes, mid_world.boxes, gone)
        G.phase("deposited", string.format("party %d -> %d, key %s left the party",
                                           before.n, mid.n, gone))

        -- WITHDRAW: the same menu with the cursor on row 0. NOT physically observed -- the
        -- census's Task_WithdrawMon hook stayed silent because the run stopped after the
        -- deposit -- so this half is the documented analogue of the pinned half, and its
        -- terminal is the keyed oracle below rather than any press count.
        G.tap("Up", 2, 13)                           -- face the PC again
        open_storage_menu()
        pc_press("A", 180)                           -- Withdraw (row 0: PHYSICAL census_pc7,
                                                     -- the menu reopens on row 0; an Up wraps
                                                     -- the cursor to See Ya)
        pc_press("A", 120)                           -- box 0 slot 0 -> its context menu
        pc_press("A", 240)                           -- Withdraw
        leave_storage(cp, "pc_ops")

        local after_world = owned_snapshot("pc_ops after withdraw")
        local after = after_world.party
        if after.n ~= mid.n + 1 then
            G.shot("stuck")
            G.finish(false, string.format(
                "pc_ops: after the withdraw the party count is %d, not %d. The withdraw half "
                .. "is the UNOBSERVED analogue of the pinned deposit (see this leg's comment); "
                .. "a census of Task_WithdrawMon is what would pin it", after.n, mid.n + 1))
        end
        if after.keys[gone] == nil then
            G.shot("stuck")
            G.finish(false, string.format(
                "pc_ops: the withdrawn mon is NOT the deposited one. Deposited %s; the party "
                .. "now holds [%s]. A released-and-replaced mon, or a different box mon, is "
                .. "not a round trip", gone, play.keylist(after)))
        end
        if after_world.boxes[gone] then
            G.finish(false, "pc_ops: withdraw copied the selected mon and left it boxed")
        end
        boxes_unchanged("pc_ops withdraw", before_world.boxes, after_world.boxes)
        -- The travelling record may differ byte for byte (RR stores a 58-byte
        -- CompressedPokemon, so the round trip is lossy BY DESIGN); the ones that STAYED must
        -- not have moved a single byte.
        for _, k in ipairs(before.order) do
            if k ~= gone then
                if after.keys[k] == nil then
                    G.finish(false, string.format(
                        "pc_ops: record %s left the party during the round trip ([%s] -> [%s])",
                        k, play.keylist(before), play.keylist(after)))
                end
                if after.keys[k] ~= before.keys[k] then
                    G.finish(false, string.format(
                        "pc_ops: record %s is not byte-identical after the round trip", k))
                end
            end
        end
        G.phase("withdrawn", string.format("party %d -> %d, key %s is back; %d other records "
                                           .. "byte-identical", mid.n, after.n, gone,
                                           before.n - 1))
    end,
}

-- ── leg: pc_release ────────────────────────────────────────────────────────────────────────
-- pc_release_begin/pc_release fire inside ReleaseMon, reached from the SAME selected-mon popup
-- pc_ops uses to STORE (STORE / SUMMARY / MARK / RELEASE / CANCEL), so the walk here is pc_ops's
-- own route with three Downs and a different final row. RR keeps FR's entry 0x08093218 and
-- completion 0x08093256 for this pair (docs/gen3/research/fr_pc_flow_and_pc_move_sites.md rows
-- ~89 and ~103) — but RR's release UI equivalence to vanilla is UNVERIFIED beyond those two
-- entry addresses (same doc, row ~110: "release is not in the receipt's observed function
-- list"). This leg's press sequence is pret-SOURCE-PINNED (not a guess, unlike the FR driver's
-- own pc_release leg, lua/tests/gen3_scripted_play.lua:1263-1267, which presses its
-- confirmation as a single A and says outright "THE CONFIRMATION IS NOT PINNED"); the physical
-- lane run is what proves RR's copy of that UI actually behaves the way the pinned FR source
-- says it does.
LEGS[#LEGS + 1] = {
    name = "pc_release",
    state = "slink_pokecenter_full.State",
    exercises = { "pc_release_begin", "pc_release" },
    source = {
        "docs/gen3/research/fr_pc_flow_and_pc_move_sites.md (rows ~89/~103: RR keeps FR's "
            .. "pc_release_begin entry 0x08093218 and pc_release completion 0x08093256; row "
            .. "~110: RR equivalence is UNVERIFIED beyond those two addresses)",
        "docs/gen3_engine_sites.md pc_release_begin row (ReleaseMon entry, called after "
            .. "permission/confirmation in Task_ReleaseMon) and pc_release row (ReleaseMon+0x3E, "
            .. "after purge, before display refresh)",
        "src/pokemon_storage_system_data.c:1761-1805 (SetMenuTextsForMon, OPTION_DEPOSIT: "
            .. "SetMenuText order is STORE, then the common tail SUMMARY, MARK, RELEASE, CANCEL "
            .. "-- rows 0..4, so Down x3 from STORE lands on RELEASE)",
        "src/pokemon_storage_system_tasks.c:1008-1019 (MENU_TEXT_RELEASE case: "
            .. "SetPokeStorageTask(Task_ReleaseMon) when the mon can be moved)",
        "src/pokemon_storage_system_tasks.c:1255-1305 (Task_ReleaseMon: state 0 prints "
            .. "MSG_RELEASE_POKE and calls ShowYesNoWindow(1); state 1's "
            .. "Menu_ProcessInputNoWrapClearOnChoose returns 0 for YES/confirm, 1 or "
            .. "MENU_B_PRESSED for NO/decline; state 3 calls ReleaseMon() -- the "
            .. "pc_release_begin/pc_release pair)",
        "src/pokemon_storage_system_tasks.c:2595-2599 (ShowYesNoWindow(cursorPos): "
            .. "CreateYesNoMenu then Menu_MoveCursorNoWrapAround(cursorPos) -- pos 1 IS the NO "
            .. "row; every OTHER ShowYesNoWindow call in this file passes 0 (lines 1620, 1946, "
            .. "2005), so release is the one prompt that starts on NO on purpose, and "
            .. "Menu_MoveCursorNoWrapAround does not wrap -- Up is required to reach YES, a "
            .. "plain A confirms NO and declines the release)",
        "src/pokemon_storage_system_tasks.c:1307-1339 (states 4/5/6/7: exactly two more JOY_NEW "
            .. "waits -- MSG_WAS_RELEASED then MSG_BYE_BYE -- before CompactPartySlots and the "
            .. "return to Task_PokeStorageMain)",
        "lua/tests/mkstate.lua:270-300 (slink_pokecenter_full.State: party of 3 at (11,8))",
    },
    check = check_on_field,
    run = function(cp)
        -- Same BFS-pinned approach to the PC as pc_ops (see PATHS above); each leg loads its
        -- own declared savestate, so this leg walks there itself rather than inheriting pc_ops's
        -- position.
        play.follow(cp, "pokecenter_start_to_pc", "pc_release")
        G.tap("Up", 2, 13)               -- face the (solid) PC metatile without stepping onto it

        local before_world = owned_snapshot("pc_release before")
        local before = before_world.party
        if before.n < 2 then
            G.finish(false, string.format(
                "pc_release: the party holds %d mon; DEPOSIT mode (which is how the party-side "
                .. "popup is reached) refuses at one, and the oracle needs a survivor to prove "
                .. "byte-identical", before.n))
        end

        open_storage_menu()
        pc_press("Down", 20); pc_press("A", 180)                 -- Deposit -> party view
        pc_press("Down", 20); pc_press("Down", 20)                -- lead -> slot 1 -> slot 2
        pc_press("A", 120)                                        -- slot 2 (the third mon) -> popup

        -- THE POPUP ORDER IS SOURCE-PINNED, not the FR driver's row count: SetMenuTextsForMon's
        -- OPTION_DEPOSIT branch calls SetMenuText(MENU_TEXT_STORE), then the shared tail always
        -- adds SUMMARY, MARK, RELEASE, CANCEL in that order (pokemon_storage_system_data.c
        -- :1761-1805). Rows are 0=STORE 1=SUMMARY 2=MARK 3=RELEASE 4=CANCEL, so three Downs from
        -- the freshly-opened popup (which starts on STORE) land on RELEASE.
        for _ = 1, 3 do pc_press("Down", 20) end                  -- STORE -> SUMMARY -> MARK -> RELEASE
        pc_press("A", 120)                                        -- RELEASE -> Task_ReleaseMon,
                                                                   -- ShowYesNoWindow(1) (NO default)

        -- THE CONFIRMATION. ShowYesNoWindow's argument is the initial cursor position, and
        -- release passes 1 (NO) while every other Yes/No box in this same file passes 0 (YES) --
        -- a deliberate default, not an oversight. Menu_MoveCursorNoWrapAround does not wrap, so
        -- from NO the only way to reach YES (choice 0, which Task_ReleaseMon's own switch
        -- confirms is the release branch) is Up, then A. This is the fix over the FR driver's
        -- pc_release leg, which presses A alone and documents that press as unpinned; reading
        -- ShowYesNoWindow's own call site pins it.
        pc_press("Up", 20)                                        -- off the NO default, onto YES
        pc_press("A", 240)                                        -- confirm -> ReleaseMon() fires
                                                                   -- (pc_release_begin/pc_release)

        -- THE TWO FOLLOW-UP MESSAGES, BOUNDED BY THE STATE MACHINE ITSELF: Task_ReleaseMon has
        -- exactly two more JOY_NEW waits between the confirm and the return to
        -- Task_PokeStorageMain -- MSG_WAS_RELEASED, then MSG_BYE_BYE (which is what triggers
        -- CompactPartySlots). Two A presses, not a guessed count.
        pc_press("A", 180)                                        -- dismiss "was released"
        pc_press("A", 240)                                        -- dismiss "Bye-bye" -> compact
        leave_storage(cp, "pc_release")

        local after_world = owned_snapshot("pc_release after")
        local after = after_world.party
        if after.n ~= before.n - 1 then
            G.shot("stuck")
            G.finish(false, string.format(
                "pc_release: the party count is %d, not %d after the pinned RELEASE route -- "
                .. "compare against the confirmation sequence in this leg's source citations "
                .. "(Up onto YES, then A, then two more A's for the follow-up messages)",
                after.n, before.n - 1))
        end
        local gone, why = play.departed_key(before, after)
        if not gone then G.finish(false, "pc_release: " .. why) end
        -- Down, Down from the lead selects slot 2 (the third mon) -- before.order is built in
        -- party-slot order, so the targeted key is before.order[3].
        if gone ~= before.order[3] then
            G.finish(false, string.format(
                "pc_release: slot 2 (key %s, selected by Down,Down from the lead) was targeted "
                .. "but %s left instead -- the popup navigation reached the wrong mon or the "
                .. "wrong row", before.order[3], gone))
        end
        local ok, bad = play.survivors_intact(before, after, gone)
        if not ok then G.finish(false, "pc_release: " .. bad) end
        if after_world.boxes[gone] then
            G.finish(false, "pc_release: selected mon was deposited instead of released")
        end
        boxes_unchanged("pc_release", before_world.boxes, after_world.boxes)
        -- The box census proves no storage transfer. The observer's release entry/completion
        -- pair is separate site evidence; playlib's health check does not assert that pair.
        G.phase("released", string.format(
            "party %d -> %d, key %s gone from party and every box; boxes unchanged",
            before.n, after.n, gone))
    end,
}

-- ── leg: save ──────────────────────────────────────────────────────────────────────────────
LEGS[#LEGS + 1] = {
    name = "save",
    -- Each RR leg loads its own state. This one proves a save attempt completed for the
    -- overworld fixture; it does not claim to persist the preceding catch or PC effects.
    state = "slink_overworld.State",
    exercises = { "save" },
    source = {
        "lua/tests/gen3_boot_check.lua save_via_menu (START-menu row search, complete validated slot and SaveRAM flush)",
        "data/games/gen3_rr/write_checkpoint.json radical_red.anchors.try_saving_data (TrySavingData, identical clean/companion bytes)",
        "docs/gen3/research/rr_site_reachability.md (TrySavingData keeps its vanilla callers on RR)",
    },
    check = check_on_field,
    run = function(cp)
        local domain = select(1, G.flash_domain())
        if not domain then G.finish(false, "save: no flash memory domain") end
        local ok, before, after, why = G.save_via_menu(cp, domain)
        if not ok then
            G.finish(false, string.format("save: %s (%d -> %d)", tostring(why), before, after))
        end
        G.phase("save-complete", string.format("fixture counter %d -> %d", before, after))
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
    party_snapshot = play.party_snapshot,
}
