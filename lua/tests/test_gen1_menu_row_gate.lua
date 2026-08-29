--[[
  lua/tests/test_gen1_menu_row_gate.lua — the SLINK row in the START menu, and nothing else.

  The companion patch now appends a row to the START menu. That is a structural change to a
  menu the player uses constantly, so it ships INERT first: selecting SLINK falls through to
  CloseStartMenu exactly as EXIT does, because the dispatch chain in the home bank ends after
  `cp 5` and everything past it closes the menu. The panel it will eventually open is a
  separate step which cannot break the menu if it goes wrong.

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
    if byte >= 0x80 and byte <= 0x99 then return string.char(byte - 0x80 + 65) end
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

-- ── selecting it is harmless ─────────────────────────────────────────────────
if reached then
    t.hold("A", 8)
    for _ = 1, 60 do t.step(nil) end
    t.check("selecting SLINK closes the menu instead of doing something",
            menu_is_closed(),
            "the row is meant to be INERT in this increment — it falls through to "
            .. "CloseStartMenu exactly as EXIT does")
end

-- ── EXIT still works, i.e. its index did not move ────────────────────────────
t.check("the menu reopens", open_menu(), "could not reopen the START menu")
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
