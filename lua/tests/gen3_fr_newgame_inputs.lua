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
-- ┌── †UNVERIFIED ────────────────────────────────────────────────────────────────────────────┐
-- │ EVERY INPUT IN THE INTRO LEGS IS A GUESS. pret/pokefirered is NOT in the local pret cache │
-- │ (E:/Google Drive/SLink/.cache/pret/ holds pokered/pokeyellow/pokecrystal/pokegold/        │
-- │ pokeheartgold/pokeplatinum only) and this tree ships no pokefirered.sym, so neither the   │
-- │ naming screen's callback nor its menu geometry can be pinned. Specifically UNVERIFIED:    │
-- │   †1  "A on the gender prompt selects BOY" (the default row).                             │
-- │   †2  "the player-name screen is a preset list whose first row below the cursor is a      │
-- │        canned name, so Down+A accepts a preset and never opens the keyboard."             │
-- │   †3  "the rival-name screen has the same shape, so Down+A accepts a preset there too."   │
-- │   †4  the FRAME COUNTS that place legs †2/†3 — there is no engine signal here to key off, │
-- │        so the two menus are reached by elapsed frames. Retune with the env vars above.    │
-- │ Everything AFTER the intro is signalled, not timed: the walk out is keyed to the          │
-- │ SaveBlock1 map id and the save to the flash sector counter, so a mistuned intro fails     │
-- │ loudly on a budget rather than writing a fixture from the wrong game state.               │
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
-- SIGNALLED, not timed: two map changes (bedroom -> ground floor -> town), read from the
-- SaveBlock1 pointer chain the way lua/memory_gba.lua:1109-1114 does. Sweeping sideways when
-- southward progress stalls is mkstate.lua's door drill (lua/tests/mkstate.lua, the town kind)
-- with the direction flipped: stairs and the front door are each one specific column.
local function mapid() local g, n = G.map(cp); return g * 256 + n end
local start_map = mapid()
G.phase("walk-out", string.format("map=%d", start_map))

local seen, count = { [start_map] = true }, 1
local left, amp = true, 1
for _ = 1, 40 do
    if count >= 3 then break end       -- bedroom, ground floor, town
    local was = mapid()
    for _ = 1, 8 do G.tap("Down", 12, 2) end   -- a direction must be HELD to walk, not tapped
    local now = mapid()
    if now ~= was then
        if not seen[now] then seen[now] = true; count = count + 1 end
        G.phase("map-change", string.format("map=%d->%d (%d seen)", was, now, count))
        amp = 1
    else
        for _ = 1, 3 * amp do G.tap(left and "Left" or "Right", 12, 2) end
        left = not left
        amp = amp + 1
    end
end

if count < 3 then
    G.shot("stuck")
    G.finish(false, string.format("never walked out of the house: %d maps seen, last=%d. The "
                               .. "fixture must be made OUTSIDE, on encounter-free town ground "
                               .. "(tools/mkstates.py's `town` rule). See "
                               .. "patch/build/gen3_stuck.png", count, mapid()))
end

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
