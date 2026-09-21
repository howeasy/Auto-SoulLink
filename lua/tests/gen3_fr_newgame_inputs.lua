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
-- Optional tuning knobs, because the legs below are TIMED, not signalled (see the warning):
--   SLINK_GEN3_FR_INTRO      frames of A/Start mashing before the player-name menu (2700)
--   SLINK_GEN3_FR_NAME_GAP   frames between the player-name and rival-name menus (1500)
--
-- ┌── Intro legs: TIMED, verified PHYSICALLY 2026-09-21 ─────────────────────────────────────┐
-- │ The intro legs (copyright, Oak, gender, two naming screens) are placed by elapsed frames  │
-- │ and their menu geometry is not pinned from source; they were VERIFIED by outcome on FR   │
-- │ US 1.0 (docs/gen3/probes/makefr_firered_town_2026-09-21.txt): the run reached the field  │
-- │ on 2F at (6,6) with a male sprite (†1 BOY) and a preset name (trainer "JONN", †2/†3),    │
-- │ twice with the default frame counts (†4). A mistuned intro still fails loudly: the walk   │
-- │ out is keyed to SaveBlock1 coordinates/map id and the save to the flash sector counter.   │
-- │ The walk out (leg 6) is PINNED from pret/pokefirered c75f352 map data, see below.         │
-- │ Radical Red is NOT driven by this script (its fixture is an imported real save); its      │
-- │ extra intro textboxes on 2F / on the way to 1F are what the stalled-step A presses absorb. │
-- └───────────────────────────────────────────────────────────────────────────────────────────┘

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(WT, "SLINK_ROOT unset — launch via tools/gen3_fixtures.py")
local G = dofile(WT .. "/lua/tests/gen3_boot_check.lua")   -- helpers only; it does not self-run

G.open("gen3_fr_newgame")
pcall(client.speedmode, 6399)
G.budget = 120000

local INTRO = tonumber(os.getenv("SLINK_GEN3_FR_INTRO") or "") or 2700
local NAME_GAP = tonumber(os.getenv("SLINK_GEN3_FR_NAME_GAP") or "") or 1500

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

-- ── leg 1 †1 †4: copyright, Oak's speech, the gender prompt ─────────────────────────────────
-- A on the 16-frame cadence advances text and takes each prompt's default row; Start skips
-- the attract cutscene. Stops early if the field is somehow already up.
G.phase("intro", "frames=" .. INTRO)
G.mash(INTRO, function() return G.pred_ok(cp, "callback2") end)

-- ── leg 2 †2: the player-name screen — Down then A takes the first preset ───────────────────
G.phase("name-player", "†UNVERIFIED Down+A = first preset name")
G.tap("Down", 3, 20)
G.tap("A", 3, 60)

-- ── leg 3 †4: "So it's <NAME>!", then Oak introduces the rival ───────────────────────────────
G.phase("name-gap", "frames=" .. NAME_GAP)
G.mash(NAME_GAP, function() return G.pred_ok(cp, "callback2") end)

-- ── leg 4 †3: the rival-name screen — same shape ────────────────────────────────────────────
G.phase("name-rival", "†UNVERIFIED Down+A = first preset name")
G.tap("Down", 3, 20)
G.tap("A", 3, 60)

-- ── leg 5: Oak's wrap-up, then the player wakes in the bedroom ──────────────────────────────
if not G.boot_to_field(cp, 9000) then
    G.shot("stuck")
    local cb2 = G.pred(cp, "callback2")
    G.finish(false, string.format("the intro never handed control to the field (callback2=%08X). "
                               .. "The †UNVERIFIED legs above are the suspect: retune "
                               .. "SLINK_GEN3_FR_INTRO / SLINK_GEN3_FR_NAME_GAP and see "
                               .. "patch/build/gen3_stuck.png", cb2))
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
local function mapid() local g, n = G.map(cp); return g * 256 + n end
local start_map = mapid()
G.phase("walk-out", string.format("map=%d", start_map))

local DELTA = { Up = { 0, -1 }, Down = { 0, 1 }, Left = { -1, 0 }, Right = { 1, 0 } }
local function step(dir)
    local x, y = G.pos(cp)
    local want_x, want_y = x + DELTA[dir][1], y + DELTA[dir][2]
    for attempt = 1, 6 do
        for _ = 1, 12 do joypad.set({ [dir] = true }); G.advance() end
        G.idle(4)
        local nx, ny = G.pos(cp)
        if nx == want_x and ny == want_y then return true end
        if mapid() ~= start_map then return true end     -- the warp tile took us
        -- Not moved: a textbox or script owns the player. Clear it, then retry the step.
        for _ = 1, 4 do G.tap("A", 3, 13) end
        x, y = G.pos(cp)
        want_x, want_y = x + DELTA[dir][1], y + DELTA[dir][2]
    end
    return false
end
-- FRLG stairs and doors are ARROW warps: the warp fires when the player presses INTO the
-- warp tile from the adjacent walkable tile (2F stairs at (8-9,2-3) are collision, so the
-- path ends at (10,2) and the exit is Left; the door row is entered by Down).
local function leg(name, path, from_map, exit_dir)
    start_map = from_map
    G.phase(name, string.format("map=%d from=(%d,%d)", start_map, G.pos(cp)))
    for _, dir in ipairs(path) do
        if not step(dir) then
            G.shot("stuck")
            G.finish(false, string.format("%s: step %s never moved the player at (%d,%d) map=%d; "
                                       .. "see patch/build/gen3_stuck.png", name, dir, G.pos(cp), mapid()))
        end
    end
    -- press into the warp, then wait for the map to change and the fade to settle
    for _ = 1, 20 do
        if mapid() ~= from_map then break end
        for _ = 1, 16 do joypad.set({ [exit_dir] = true }); G.advance() end
        if mapid() == from_map then for _ = 1, 2 do G.tap("A", 3, 13) end end   -- RR textbox
    end
    for _ = 1, 600 do
        if mapid() ~= from_map and G.pred_ok(cp, "palette_fade_active") then G.idle(16); return end
        G.advance()
    end
    G.shot("stuck")
    G.finish(false, string.format("%s: end of path, pressed %s, but map is %d (from %d) at (%d,%d)",
                                  name, exit_dir, mapid(), from_map, G.pos(cp)))
end

-- Any intro textbox still open on 2F (RR) is cleared by the first stalled step.
leg("2F->1F", { "Right", "Up", "Up", "Right", "Right", "Right", "Up", "Up" }, mapid(), "Left")
leg("1F->town", { "Down", "Down", "Down", "Down", "Down", "Down", "Left", "Left", "Left", "Left",
                  "Left", "Left" }, mapid(), "Down")
G.phase("map-change", string.format("map=%d", mapid()))

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
G.phase("outside", string.format("map=%d", mapid()))

-- ── leg 7: the in-game save, same driver the boot check uses ────────────────────────────────
local ok, before, after = G.save_via_menu(cp, domain)
if not ok then
    G.finish(false, string.format("the in-game save never advanced the sector counter (%d -> %d)",
                                  before, after))
end

pcall(client.saveram)
G.idle(60)
G.phase("flushed")
G.finish(true, string.format("map=%d counter %d -> %d", mapid(), before, after))
