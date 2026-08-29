--[[
  lua/tests/test_gen1_menu_row_gate.lua — the SLINK row in the START menu, and nothing else.

  The companion patch appends a row to the START menu and opens a full-screen panel from it.
  The row landed inert first, on purpose, and this gate grew with it -- so it still checks
  everything about the ROW (drawn, inside a resized box, reachable, no existing index moved)
  and now also everything about the PANEL (opens, tells the client it may paint, times out
  rather than hanging when no client is attached, and gives the screen back).

  WHAT HAS TO BE TRUE, and each of these is a way the change could go wrong rather than a
  restatement of the change:

    * the row is DRAWN -- the redirect at DrawStartMenu's tail runs and PlaceString reaches
      the tile map
    * EXIT is still drawn, in its original place. The stub prints both; a stub that printed
      only SLINK would look correct in a screenshot of the last row.
    * the box GREW. Without the two height patches the new row is drawn outside the border.
    * the cursor can REACH it. home/start_menu.asm wraps with its own hardcoded counts,
      separate from wMaxMenuItem, so a row can be visible and unselectable.
    * selecting it is HARMLESS and closes the menu.
    * EXIT still closes the menu, i.e. its index did not move.
    * the game still runs afterwards.

      python tools/run_gb_gate.py lua/tests/test_gen1_menu_row_gate.lua --rom red_patched --target town
--]]

local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gatelib.lua")
local t = G.start("test_gen1_menu_row_gate")
local M = t.M
local fmt = string.format

local TILEMAP = 0xC3A0            -- wTileMap; NOT shifted in Yellow, and R/B share it
local SCREEN_W = 20
local CUR_MENU = 0xCC26           -- wCurrentMenuItem
local MAX_MENU = 0xCC28           -- wMaxMenuItem
local WATCHED  = 0xCC29           -- wMenuWatchedKeys

-- Gen 1 charset: 'A' is $80, so a letter is $80 + (c - 'A'). Verified against the ROM's
-- own "POKéDEX@" which reads 8F 8E 8A BA 83 84 97 50.
local function decode(byte)
    if byte >= 0x80 and byte <= 0x99 then return string.char(byte - 0x80 + 65) end  -- A-Z
    if byte >= 0xA0 and byte <= 0xB9 then return string.char(byte - 0xA0 + 97) end  -- a-z
    -- Digits are the $F6-$FF block, NOT anywhere near the letters. Decoding only letters
    -- made every number on the panel read as dots, and this gate then reported that the
    -- staged rows had not appeared when they plainly had.
    if byte >= 0xF6 and byte <= 0xFF then return string.char(byte - 0xF6 + 48) end  -- 0-9
    if byte == 0xF3 then return "/" end
    if byte == 0x7F then return " " end
    return "."
end

local function row_text(row)
    local out = {}
    for col = 0, SCREEN_W - 1 do
        out[#out + 1] = decode(M.read_u8(TILEMAP + row * SCREEN_W + col))
    end
    return table.concat(out)
end

local function screen_rows()
    local rows = {}
    for r = 0, 17 do rows[r] = row_text(r) end
    return rows
end

local function find_row(rows, needle)
    for r = 0, 17 do
        if rows[r]:find(needle, 1, true) then return r end
    end
    return nil
end

local function open_menu()
    for _ = 1, 40 do t.step(nil) end
    t.hold("Start", 8)
    for _ = 1, 40 do t.step(nil) end
    return M.read_u8(WATCHED) == 0xCB     -- the START menu's watched-key mask
end

--- Is the menu GONE? Read the screen, not wMenuWatchedKeys.
---
--- wMenuWatchedKeys is set when the menu opens and simply left behind when it closes --
--- nothing clears it -- so "watched ~= 0xCB" reports every closed menu as still open. The
--- tile map is the honest signal: CloseStartMenu ends in CloseTextDisplay, which restores
--- the map underneath, so the menu's own text stops being on screen.
--- Make sure the START menu is up, WITHOUT toggling it if it already is.
---
--- Closing the panel returns to RedisplayStartMenu, so the menu is already open at that
--- point and pressing START would close it. The first version of the staging test did
--- exactly that and then reported that the patch never asked the client to paint.
local function ensure_menu_open()
    for _ = 1, 6 do
        if find_row(screen_rows(), "EXIT") then return true end
        t.hold("Start", 8)
        for _ = 1, 40 do t.step(nil) end
    end
    return find_row(screen_rows(), "EXIT") ~= nil
end

local function menu_is_closed()
    local rows = screen_rows()
    return find_row(rows, "EXIT") == nil and find_row(rows, "SLINK") == nil
end

-- ── the menu is open at all ──────────────────────────────────────────────────
t.check("the START menu opened", open_menu(),
        fmt("wMenuWatchedKeys = 0x%02X, expected 0xCB — every check below is "
            .. "meaningless if the menu is not up", M.read_u8(WATCHED)))

local rows = screen_rows()
for r = 0, 17 do t.log(fmt("[menu] row %2d |%s|", r, rows[r])) end

-- ── drawn, and not at EXIT's expense ─────────────────────────────────────────
local slink_row = find_row(rows, "SLINK")
local exit_row = find_row(rows, "EXIT")
t.check("the SLINK row is drawn", slink_row ~= nil,
        "the DrawStartMenu tail redirect did not reach PlaceString")
t.check("EXIT is still drawn", exit_row ~= nil,
        "the stub prints BOTH; only printing SLINK would still look right on the last row")
if slink_row and exit_row then
    t.check("SLINK is below EXIT", slink_row > exit_row,
            fmt("SLINK on row %d, EXIT on row %d — appending is what keeps every existing "
                .. "menu index where it was", slink_row, exit_row))
    t.check("they are one menu row apart", slink_row - exit_row == 2,
            fmt("%d tile rows apart, expected 2", slink_row - exit_row))
end

-- ── the box grew to contain it ───────────────────────────────────────────────
-- The border column sits just left of the menu text. If the box were not resized the new
-- row would be drawn past the bottom edge with no border beside it.
if slink_row then
    local border = M.read_u8(TILEMAP + slink_row * SCREEN_W + 10)
    t.check("the menu box border runs beside the SLINK row", border ~= 0x7F and border ~= 0,
            fmt("tile at (10,%d) is 0x%02X — the box was not made taller", slink_row, border))
end

-- The menu has one more item once the player owns the Pokedex, and DrawStartMenu patches
-- BOTH counts. Which one applies is derived from the drawn menu rather than assumed: an
-- early-game fixture has no Pokedex, and hardcoding the with-Pokedex index made this gate
-- fail against a perfectly good patch.
local has_dex = find_row(rows, "DEX") ~= nil
local want_items = has_dex and 8 or 7
local slink_index = want_items - 1
t.log(fmt("[menu] Pokedex present=%s -> %d items, SLINK is index %d",
          tostring(has_dex), want_items, slink_index))
t.check("wMaxMenuItem counts the extra row", M.read_u8(MAX_MENU) == want_items,
        fmt("got %d, expected %d", M.read_u8(MAX_MENU), want_items))

-- ── the cursor can reach it ──────────────────────────────────────────────────
-- home/start_menu.asm wraps with hardcoded counts that are SEPARATE from wMaxMenuItem, so
-- without those two patches the row is visible and unselectable.
local reached = false
for _ = 1, 12 do
    t.hold("Down", 6)
    for _ = 1, 10 do t.step(nil) end
    if M.read_u8(CUR_MENU) == slink_index then reached = true break end
end
t.check("the cursor can be moved onto the SLINK row", reached,
        fmt("wCurrentMenuItem never reached %d (stopped at %d) — the home-bank wrap "
            .. "constants are separate from wMaxMenuItem and gate reachability",
            slink_index, M.read_u8(CUR_MENU)))

-- ── selecting it opens the panel, and the panel gives the screen back ────────
-- The panel takes the whole screen using StartMenu_TrainerInfo's own sequence, so what is
-- under test is both halves: that it appears at all, and that everything it borrowed comes
-- back. A panel that draws correctly and then leaves the map screen wrecked is worse than
-- no panel.
local PANEL_STATE = 0xDEE2 + 9
if reached then
    t.hold("A", 8)
    -- Give it long enough to clear the screen, miss the stage timeout (~90 frames) and
    -- settle on the fallback.
    local saw_panel = false
    for _ = 1, 240 do
        t.step(nil)
        if find_row(screen_rows(), "SOUL LINK") then saw_panel = true break end
    end
    t.check("selecting SLINK opens the panel", saw_panel,
            "no SOUL LINK title appeared — the dispatch trampoline did not reach bank $3F")

    t.check("the panel announces itself to the client", M.read_u8(PANEL_STATE) ~= 0,
            fmt("panel state is %d — the client is never told it may paint",
                M.read_u8(PANEL_STATE)))

    -- No client is attached in this gate, so the stage wait must TIME OUT rather than hang.
    local fell_back = false
    for _ = 1, 300 do
        t.step(nil)
        if find_row(screen_rows(), "NO CLIENT") then fell_back = true break end
    end
    t.check("with no client attached it falls back instead of hanging", fell_back,
            "the stage wait never timed out")

    -- Close it. PRESS UNTIL IT CLOSES rather than pressing once and hoping: the panel
    -- spends up to 90 frames waiting for a client and another 20 settling before it will
    -- look at the joypad, and a single early press lands in that window and is discarded.
    -- The first version of this check pressed A about two frames after the panel opened
    -- and then blamed the patch for not closing.
    local closed = false
    for _ = 1, 12 do
        t.hold("A", 6)
        for _ = 1, 40 do t.step(nil) end
        if find_row(screen_rows(), "SOUL LINK") == nil then closed = true break end
    end
    t.check("a button press closes the panel", closed,
            "still on screen after 12 presses")
    t.check("the panel hands the screen back", find_row(screen_rows(), "SOUL LINK") == nil,
            "the panel is still on screen after a button press")
    t.check("the panel clears its state on the way out",
            M.read_u8(PANEL_STATE) == 0,
            fmt("panel state left at %d — a client would keep painting over the map",
                M.read_u8(PANEL_STATE)))
end

-- ── the client can paint it ──────────────────────────────────────────────────
-- The handshake is the whole feature: the patch blanks the screen and says AWAIT, the
-- client paints the tile map, the patch reveals it. This gate stands in for the client,
-- calling the SAME M.panelStage the real one does -- so what is under test is the painter
-- and the handshake, not a re-implementation of them.
t.check("the menu is up for the staging test", ensure_menu_open(),
        "the START menu is not showing")
do
    for _ = 1, 12 do
        if M.read_u8(CUR_MENU) == slink_index then break end
        t.hold("Down", 6)
        for _ = 1, 10 do t.step(nil) end
    end
    t.hold("A", 6)

    -- Wait for the patch to hand the screen over, then paint through the real helper.
    local awaited = false
    for _ = 1, 120 do
        t.step(nil)
        if M.panelIsAwaitingStage() then awaited = true break end
    end
    t.check("the patch asks the client to paint", awaited,
            "panel state never reached AWAIT")

    if awaited then
        M.panelStage({"SLINK TEST", "", "PAIRS 3/5", "BADGES 2/8", "DEAD ZONES 1",
                      "", "-VIRIDIAN FOREST"})
        t.check("staging sets the handshake to STAGED",
                M.read_u8(PANEL_STATE) == 2,
                fmt("state is %d after panelStage", M.read_u8(PANEL_STATE)))

        -- The patch reveals whatever is in the tile map once staging completes.
        local shown = false
        for _ = 1, 200 do
            t.step(nil)
            if find_row(screen_rows(), "PAIRS 3/5") then shown = true break end
        end
        t.check("what the client painted is what the panel shows", shown,
                "the staged rows never appeared")
        t.check("the fallback was painted over", find_row(screen_rows(), "NO CLIENT") == nil,
                "NO CLIENT is still visible under the staged page")
        t.check("a later row landed too", find_row(screen_rows(), "VIRIDIAN FOREST") ~= nil,
                "only the first rows were painted")

        for r = 0, 8 do t.log(fmt("[staged] %2d |%s|", r, row_text(r))) end
    end

    -- Close it again so the checks below start from a menu, not a panel.
    for _ = 1, 12 do
        t.hold("A", 6)
        for _ = 1, 40 do t.step(nil) end
        if find_row(screen_rows(), "PAIRS") == nil then break end
    end
end

-- ── EXIT still works, i.e. its index did not move ────────────────────────────
t.check("the menu is up again", ensure_menu_open(),
        "the START menu is not showing")
local rows2 = screen_rows()
local exit2 = find_row(rows2, "EXIT")
if exit2 then
    -- Walk to EXIT's index and select it.
    for _ = 1, 12 do
        if M.read_u8(CUR_MENU) == slink_index - 1 then break end
        t.hold("Down", 6)
        for _ = 1, 10 do t.step(nil) end
    end
    t.check("the cursor reaches EXIT's index", M.read_u8(CUR_MENU) == slink_index - 1,
            fmt("wanted %d, stalled at %d", slink_index - 1, M.read_u8(CUR_MENU)))
    t.hold("A", 8)
    for _ = 1, 60 do t.step(nil) end
    t.check("EXIT still closes the menu", menu_is_closed(),
            "EXIT's index moved — appending was supposed to leave every existing "
            .. "index untouched")
end

-- ── the game survives ────────────────────────────────────────────────────────
local X, Y = M.MAP_ID_ADDR + 4, M.MAP_ID_ADDR + 3
local x0, y0 = M.read_u8(X), M.read_u8(Y)
local moved = false
for i = 1, 8 do
    t.hold(({"Right", "Left"})[(i % 2) + 1], 24, function()
        return M.read_u8(X) ~= x0 or M.read_u8(Y) ~= y0
    end)
    if M.read_u8(X) ~= x0 or M.read_u8(Y) ~= y0 then moved = true break end
end
t.check("the player still walks after all that", moved,
        fmt("stuck at (%d,%d) — a broken menu can leave the overworld loop wedged", x0, y0))

t.finish(fmt("SLINK row at %s, EXIT at %s", tostring(slink_row), tostring(exit_row)))
