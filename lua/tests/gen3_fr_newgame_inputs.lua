-- gen3_fr_newgame_inputs.lua — scripted NEW GAME on vanilla FireRed to the first save point.
--
-- Produces the battery save tools/gen3_fixtures.py `make-fr` imports as
-- tests/fixtures/gen3/firered_town.sav: cold boot -> NEW GAME -> intro -> out of the house
-- into Pallet Town -> in-game SAVE -> flush. Writes
-- patch/build/gen3_fr_newgame_result.txt ending in `RESULT: PASS|FAIL`.
--
--   python tools/gen3_fixtures.py make-fr --rom <FireRed.gba> --out tests/fixtures/gen3/firered_town.sav
--
-- Environment: SLINK_ROOT, SLINK_GEN3_CHECKPOINT, SLINK_GEN3_TITLE (see gen3_boot_check.lua).
--
-- ┌── Intro legs: WITNESS-DRIVEN (card C4-LGF2, coordinator steer 2026-09-23) ────────────────┐
-- │ Originally TIMED (fixed elapsed-frame waits tuned once on FR, verified PHYSICALLY          │
-- │ 2026-09-21). That broke on LeafGreen: the SCREENS and CHOICES are identical (same          │
-- │ pret pokefirered engine, same naming-screen behaviour) but the ELAPSED FRAME COUNT to      │
-- │ reach the gender prompt and each naming screen differs by title -- so a frame budget       │
-- │ tuned on FR landed the input a beat early/late on LG. Replaced with the same "wait for      │
-- │ the engine's own task/callback2, never a frame guess" shape c1507b7d already used for the  │
-- │ START-menu SAVE row: mash A/Start (safe on every plain textbox) until                      │
-- │ Task_OakSpeech_HandleGenderInput or CB2_NamingScreen is the active task/callback2           │
-- │ (lua/tests/gen3_title_syms.lua, checked against both pret .sym files), THEN press the      │
-- │ pinned choice ONCE. Only the button sequence itself is still unverified from source (†1     │
-- │ BOY, †2/†3 Down+A = first preset name) -- never the timing, on either title now.            │
-- │ The walk out (leg 6) is PINNED from pret/pokefirered c75f352 map data, see below.           │
-- │ Radical Red is NOT driven by this script (its fixture is an imported real save); its        │
-- │ extra intro textboxes on 2F / on the way to 1F are what the stalled-step A presses absorb.  │
-- └───────────────────────────────────────────────────────────────────────────────────────────┘

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(WT, "SLINK_ROOT unset — launch via tools/gen3_fixtures.py")
local G = dofile(WT .. "/lua/tests/gen3_boot_check.lua")   -- helpers only; it does not self-run
local PL = dofile(WT .. "/lua/tests/playlib.lua")
local Syms = dofile(WT .. "/lua/tests/gen3_title_syms.lua")

-- TITLE: same "global, else env, else firered" shape gen3_scripted_play.lua uses, so every
-- existing FireRed caller (neither global nor env set) keeps byte-for-byte behaviour.
local TITLE = SLINK_GEN3_TITLE or os.getenv("SLINK_GEN3_TITLE")
if not TITLE or TITLE == "" then TITLE = "firered" end
local S = Syms.for_title(TITLE)
local TASK_SIZE = 40   -- gTasks entry size (gen3_scripted_play.lua's own TASK_SIZE, S.TASKS_BASE)

--- Is the task at `addr` the currently active one? Same gTasks[] scan shape as
--- gen3_scripted_play.lua's own party_task(): func u32 @+0, isActive u8 @+4.
local function task_active(addr)
    if not addr then return false end
    for slot = 0, 15 do
        local base = S.TASKS_BASE + slot * TASK_SIZE
        if memory.read_u8(base + 4) ~= 0 and memory.read_u32_le(base) == addr then
            return true
        end
    end
    return false
end

local function callback2_is(addr)
    return addr ~= nil and memory.read_u32_le(S.GMAIN_CALLBACK2_ADDR) == addr
end
-- The step walker and the press-into-warp come from the shared scripted-play runtime
-- (lua/tests/playlib.lua). This script binds only what those two need: playlib holds no host
-- call and no game fact of its own (Codex review cx-67a6e199), and a walk that never fights
-- needs no battle policy, no observer and no savestates.
local play = PL.bind({
    advance = G.advance, idle = G.idle, tap = G.tap, pos = G.pos,
    phase = G.phase, finish = G.finish, shot = G.shot, open = G.open,
    checkpoint = G.checkpoint,
    press = function(buttons) joypad.set(buttons); G.advance() end,
    map = function(cp)
        local g, n = G.map(cp)
        if g < 0 or n < 0 then return nil end
        return g * 256 + n
    end,
    in_battle = function(cp) return not G.pred_ok(cp, "in_battle") end,
    on_field  = function(cp)
        return G.pred_ok(cp, "in_battle") and G.pred_ok(cp, "callback2")
    end,
}, {
    -- The stalled-step recovery this walk depends on: RR adds intro dialogue on 2F and on the
    -- way down to 1F where FireRed has none.
    clear_dialogue = function() for _ = 1, 4 do G.tap("A", 3, 13) end end,
    advance_scene  = function() G.tap("A", 2, 10) end,
})

G.open("gen3_fr_newgame")
pcall(client.speedmode, 6399)
G.budget = 120000

local cp, title = G.checkpoint()
G.phase("start", "title=" .. tostring(title))

local domain, seen = G.flash_domain()
if not domain then
    G.finish(false, "no flash memory domain of 0x20000 bytes; domains: " .. tostring(seen))
end
if G.save_counter(domain) >= 0 then
    G.finish(false, "the battery already holds a save — make-fr must cold boot onto an erased "
                 .. "SaveRAM directory, or the intro never runs and NEW GAME is never reached")
end
G.phase("domain", domain .. " (erased battery, cold boot)")

-- ── leg 1 †1: copyright, Oak's speech, the gender prompt (witness-driven) ────────────────────
-- A on the 16-frame cadence advances every preceding textbox (safe: a plain message only
-- needs A, Start only skips the attract cutscene); stop the instant the gender-prompt task
-- itself becomes active, then press A ONCE -- a deliberate select, not a press that happens to
-- land inside a blind mash. Stops early if the field is somehow already up.
local GENDER_TASK = S.TASK_OAKSPEECH_GENDER_INPUT
G.phase("intro", "waiting for the gender-prompt task")
if not G.mash(90000, function()
    return G.pred_ok(cp, "callback2") or task_active(GENDER_TASK)
end) then
    G.shot("stuck")
    G.finish(false, "the gender-prompt task never became active (Task_OakSpeech_HandleGenderInput)")
end
if task_active(GENDER_TASK) then
    G.tap("A", 3, 20)   -- †1 BOY, the default cursor position
end

-- ── leg 2 †2: the player-name screen — Down then A takes the first preset ───────────────────
-- Mash through the gender-confirm/name-prompt text until the naming screen's own callback
-- (CB2_NamingScreen) is up, then commit the preset -- no elapsed-frame guess either side.
local NAMING_CB2 = S.CB2_NAMING_SCREEN
G.phase("name-player", "waiting for the naming screen")
if not G.mash(90000, function() return callback2_is(NAMING_CB2) end) then
    G.shot("stuck")
    G.finish(false, "the player-naming screen never opened (CB2_NamingScreen)")
end
G.tap("Down", 3, 20)
G.tap("A", 3, 60)
if not G.mash(9000, function() return not callback2_is(NAMING_CB2) end) then
    G.shot("stuck")
    G.finish(false, "the player-naming screen never closed after Down+A")
end

-- ── leg 3: "So it's <NAME>!", then Oak introduces the rival ─────────────────────────────────
-- ── leg 4 †3: the rival-name screen — same shape, same witness, reused for the SECOND time
-- CB2_NamingScreen comes up (the address does not distinguish player vs. rival; order does).
G.phase("name-rival", "waiting for the naming screen")
if not G.mash(90000, function() return callback2_is(NAMING_CB2) end) then
    G.shot("stuck")
    G.finish(false, "the rival-naming screen never opened (CB2_NamingScreen)")
end
G.tap("Down", 3, 20)
G.tap("A", 3, 60)
if not G.mash(9000, function() return not callback2_is(NAMING_CB2) end) then
    G.shot("stuck")
    G.finish(false, "the rival-naming screen never closed after Down+A")
end

-- ── leg 5: Oak's wrap-up, then the player wakes in the bedroom ──────────────────────────────
if not G.boot_to_field(cp, 9000) then
    G.shot("stuck")
    local cb2 = G.pred(cp, "callback2")
    G.finish(false, string.format("the intro never handed control to the field (callback2=%08X); "
                               .. "see patch/build/gen3_stuck.png", cb2))
end

-- ── leg 6: out of the bedroom, down the stairs, out the front door into Pallet Town ─────────
-- PINNED from pret/pokefirered c75f352 (the .sym source): NEW GAME spawns on
-- MAP_PALLET_TOWN_PLAYERS_HOUSE_2F at (6,6) (src/new_game.c:84); the 2F stairs warp is (10,2)
-- -> 1F warp 2 at (10,2) (data/maps/PalletTown_PlayersHouse_2F/map.json); the 1F front door is
-- (4,8)/(5,8) -> PALLET_TOWN warp 0 at (6,7), MOM stands at (8,4) (PlayersHouse_1F/map.json).
-- Each leg is the BFS over the layout collision bits (data/layouts/*/map.bin, bits 10-11) with
-- MOM's tile blocked. Every step is verified by the SaveBlock1 coordinates; a step that does
-- not move the player is treated as a textbox (Radical Red adds intro dialogue on 2F and on
-- the way down to 1F) and cleared with A before the step is retried.
local function mapid() return play.map(cp) end
local start_map = mapid()
G.phase("walk-out", string.format("map=%s", tostring(start_map)))

-- FRLG stairs and doors are ARROW warps: the warp fires when the player presses INTO the
-- warp tile from the adjacent walkable tile (2F stairs at (8-9,2-3) are collision, so the
-- path ends at (10,2) and the exit is Left; the door row is entered by Down).
--
-- playlib.step with `want` set: each step must land EXACTLY one tile along the direction, not
-- merely move. This walk is the one place where an unexpected displacement means the timed
-- intro above went somewhere else entirely, so the stricter test is the right one. A step that
-- does not move is treated as a textbox (Radical Red adds intro dialogue on 2F and on the way
-- down to 1F) and cleared with A before the step is retried; a mid-step wild encounter is
-- impossible indoors, so the walker's encounter absorber never fires here.
local function leg(name, path, from_map, exit_dir)
    start_map = from_map
    G.phase(name, string.format("map=%s from=%s", tostring(start_map), play.at(cp)))
    for _, dir in ipairs(path) do
        -- enc=false: this walk is indoors, where no wild battle can start, so the
        -- walker must not carry an encounter policy it would never use.
        if not play.step(cp, dir, start_map, true, false) then
            G.shot("stuck")
            G.finish(false, string.format("%s: step %s never moved the player at %s map=%s; "
                                       .. "see patch/build/gen3_stuck.png",
                                          name, dir, play.at(cp), tostring(mapid())))
        end
    end
    if play.enter_warp(cp, exit_dir, 20) then return end
    G.shot("stuck")
    G.finish(false, string.format("%s: end of path, pressed %s, but map is %s (from %s) at %s",
                                  name, exit_dir, tostring(mapid()), tostring(from_map), play.at(cp)))
end

-- Any intro textbox still open on 2F (RR) is cleared by the first stalled step.
leg("2F->1F", { "Right", "Up", "Up", "Right", "Right", "Right", "Up", "Up" }, mapid(), "Left")
leg("1F->town", { "Down", "Down", "Down", "Down", "Down", "Down", "Left", "Left", "Left", "Left",
                  "Left", "Left" }, mapid(), "Down")
G.phase("map-change", string.format("map=%s", tostring(mapid())))

-- Settle back into a quiet field before opening the menu.
local settled = false
for _ = 1, 900 do
    if G.pred_ok(cp, "callback2") and G.pred_ok(cp, "palette_fade_active")
       and G.pred_ok(cp, "script_context_status") then
        settled = true
        break
    end
    G.advance()
end
if not settled then
    G.shot("stuck")
    G.finish(false, "the warp into town never settled into a quiet field")
end
G.phase("outside", string.format("map=%s", tostring(mapid())))

-- ── leg 7: the in-game save, same driver the boot check uses ────────────────────────────────
-- save_via_menu validates the new slot (unique ids, one slot, checksums) and flushes.
local ok, before, after, why = G.save_via_menu(cp, domain)
if not ok then
    G.finish(false, string.format("the in-game save failed: %s (counter %s -> %s)",
                                  tostring(why), tostring(before), tostring(after)))
end
G.idle(60)
G.phase("flushed")
G.finish(true, string.format("map=%s counter %d -> %d", tostring(mapid()), before, after))
