--[[
  lua/tests/test_gen1_menu_row_gate.lua — the SLINK row in the START menu and the panel
  behind it, driven by the REWRITTEN client (lua/gen1/*), not by memory_gb.lua.

  WHAT CHANGED FROM THE OLD GATE. It used to stand in for the client: it painted the
  panel itself through the old client's helper, so the painter it proved was the gate's own
  call and the handshake it proved had no client in it. Here the gate is only the SERVER: rows
  arrive as a real `link_panel` reply on t.replies, lua/gen1/client.lua hands them to
  lua/gen1/panel.lua, and panel:service() decides — from the mailbox alone — whether it is
  allowed to paint. Every frame therefore drives t.client:frame_end(); nothing else would
  make the real handler run.

  WHAT HAS TO BE TRUE, each of them a way the change could go wrong:

    * the row is DRAWN, EXIT is still drawn in its original place, and SLINK is exactly two
      tile rows below it (appending is what keeps every existing menu index where it was);
    * the box GREW — without the two height patches the new row lands outside the border;
    * the cursor can REACH it (home/start_menu.asm wraps on hardcoded counts that are
      SEPARATE from wMaxMenuItem, so a row can be visible and unselectable);
    * with NOTHING held, the panel falls back to "NO CLIENT" and leaves +9 at AWAIT — the
      patch's timeout does not clear it (slink.asm:319-335), and a client that treated that
      stale AWAIT as an invitation would paint over a revealed screen;
    * a reply that arrives AFTER the client's own 60-frame deadline paints nothing;
    * that same reply, HELD, paints on the next open, within that open's deadline;
    * A turns the page, B closes and resets the page byte;
    * EXIT still closes the menu and the player still walks.

      python tools/run_gb_gate.py lua/tests/test_gen1_menu_row_gate.lua --rom red_patched --target town
--]]

local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gate.lua")
local t = G.start("test_gen1_menu_row_gate")
local fmt = string.format
local json, ram = t.parts.json, t.parts.profile.ram
-- Mailbox addresses come from the module under test rather than a second copy of $DEE2+n:
-- a gate with its own constants can only ever agree with itself.
local Panel = dofile(t.ROOT .. "/lua/gen1/panel.lua")
local Center = dofile(t.ROOT .. "/lua/tests/gen1_rb_center_inputs.lua")

local COLS, SCREEN_ROWS = Panel.COLS, Panel.ROWS
local TILEMAP = assert(ram.wTileMap, "wTileMap missing from profile")
-- The mailbox itself moves on an overlay-admitted cartridge (profile.trade.mailbox, PLAN
-- A4/M3); STATE/PAGE/PAGES are ABI-fixed offsets from it (+9/+10/+11), derived from Panel's own
-- exported vanilla constants rather than a second copy of the offset numbers.
local MAILBOX = t.parts.profile.trade and t.parts.profile.trade.mailbox or Panel.MAILBOX
local STATE = MAILBOX + (Panel.STATE - Panel.MAILBOX)
local PAGE  = MAILBOX + (Panel.PAGE - Panel.MAILBOX)
local PAGES = MAILBOX + (Panel.PAGES - Panel.MAILBOX)

local function read(addr) return memory.read_u8(addr, "System Bus") end
local function at(symbol) return read(assert(ram[symbol], symbol .. " missing from profile")) end
local function state() return read(STATE) end

-- Every step runs the real client for that frame. panel:service() is the FIRST thing
-- frame_end does, which is the only reason a paint can land while the player sits in a menu
-- with the overworld write checkpoint long behind them.
local function step(buttons)
    t.step(buttons or {})   -- {} releases the previously held button
    t.client:frame_end()
end
local function idle(n) for _ = 1, n do step({}) end end
local function press(button, frames)
    for _ = 1, frames or 6 do step({ [button] = true }) end
    idle(6)
end
local function wait(predicate, frames)
    for _ = 1, frames do
        if predicate() then return true end
        step({})
    end
    return predicate() and true or false
end
--- Press until it TAKES. SlinkWaitForButton settles 20 frames before it looks at the joypad
--- (slink.asm:305-317) and HandleMenuInput polls on its own cadence, so a single pulse lands
--- inside a window that discards it. Three separate checks in the old gate were caught by
--- this; the loop is the fix, not a retry-until-green.
local function press_until(button, predicate, tries, settle)
    for _ = 1, tries or 12 do
        if predicate() then return true end
        press(button, 6)
        if wait(predicate, settle or 40) then return true end
    end
    return predicate() and true or false
end

local function row_text(r) return Center.row(read, TILEMAP, r * COLS, COLS) end
local function find_row(needle)
    for r = 0, SCREEN_ROWS - 1 do
        if row_text(r):find(needle, 1, true) then return r end
    end
    return nil
end
local function on_screen(text) return Center.has_tiles(read, TILEMAP, text) end
local function dump(tag, first, last)
    for r = first, last do t.log(fmt("[%s] row %2d |%s|", tag, r, row_text(r))) end
end
local function reply(command)
    t.replies[#t.replies + 1] = assert(json.encode({ commands = { command } }))
end

-- A TWO-PAGE payload so the page turn has somewhere to go, and one row of each shape the
-- server actually emits (_build_link_panel): a count with a slash, a dead-zone row with a
-- leading dash. Both were invisible to a letters-only tile decoder.
local PAGED = { "SLINK TEST", "", "PAIRS 3/5", "BADGES 2/8", "DEAD ZONES 1",
                "", "-VIRIDIAN FOREST" }
for i = #PAGED + 1, 26 do PAGED[i] = fmt("ROW %d", i) end
local LAST_ON_PAGE1, FIRST_ON_PAGE2 = "ROW 18", "ROW 19"

local slink_row, exit_row, slink_index

local ok, err = xpcall(function()
    -- The loopback server is "connected" for the whole run: client.lua clears the held rows
    -- on a dropped link (rows outlive neither the link nor the save), so a gate that left
    -- t.online false would watch every reply evaporate a frame after it arrived.
    t.online = true
    t.client:frame_end()

    -- ── the menu is up at all ────────────────────────────────────────────────────────
    -- Read the SCREEN, not wMenuWatchedKeys: nothing clears that byte when a menu closes,
    -- so it reports every closed menu as open. It is also absent from profile.ram, and the
    -- rewrite's rule is that addresses come from the profile.
    local function menu_open() return find_row("EXIT") ~= nil end
    local function menu_closed() return find_row("EXIT") == nil and find_row("SLINK") == nil end
    idle(30)
    t.check("the START menu opened", press_until("Start", menu_open, 6, 40),
            "no EXIT row on screen — every check below is meaningless if the menu is not up")
    dump("menu", 0, SCREEN_ROWS - 1)

    -- ── drawn, and not at EXIT's expense ─────────────────────────────────────────────
    slink_row, exit_row = find_row("SLINK"), find_row("EXIT")
    t.check("the SLINK row is drawn", slink_row ~= nil,
            "the DrawStartMenu tail redirect did not reach PlaceString")
    t.check("EXIT is still drawn", exit_row ~= nil,
            "the stub prints BOTH; only printing SLINK would still look right on the last row")
    if slink_row and exit_row then
        t.check("SLINK is two tile rows below EXIT", slink_row - exit_row == 2,
                fmt("SLINK on row %d, EXIT on row %d (%d apart, expected 2)",
                    slink_row, exit_row, slink_row - exit_row))
    end

    -- ── the box grew to contain it ───────────────────────────────────────────────────
    -- The border column sits just left of the menu text; without the two height patches the
    -- row is drawn past the bottom edge with no border beside it.
    if slink_row then
        local border = read(TILEMAP + slink_row * COLS + 10)
        t.check("the menu box border runs beside the SLINK row", border ~= 0x7F and border ~= 0,
                fmt("tile at (10,%d) is 0x%02X — the box was not made taller", slink_row, border))
    end

    -- The menu gains a row once the player owns the Pokedex and DrawStartMenu patches BOTH
    -- counts, so which one applies is DERIVED from the drawn menu rather than assumed: an
    -- early-game fixture has no Pokedex, and hardcoding the with-Pokedex count once made this
    -- gate fail against a perfectly good patch.
    local has_dex = find_row("DEX") ~= nil
    local want_items = has_dex and 8 or 7
    slink_index = want_items - 1
    t.log(fmt("[menu] Pokedex present=%s -> %d items, SLINK is index %d",
              tostring(has_dex), want_items, slink_index))
    t.check("wMaxMenuItem counts the extra row", at("wMaxMenuItem") == want_items,
            fmt("got %d, expected %d", at("wMaxMenuItem"), want_items))

    -- ── the cursor can reach it ──────────────────────────────────────────────────────
    local function cursor_on(index)
        return press_until("Down", function() return at("wCurrentMenuItem") == index end, 12, 10)
    end
    t.check("the cursor can be moved onto the SLINK row", cursor_on(slink_index),
            fmt("wCurrentMenuItem stopped at %d, wanted %d — the home-bank wrap constants are "
                .. "separate from wMaxMenuItem and gate reachability",
                at("wCurrentMenuItem"), slink_index))

    --- Open the panel from the menu. "Open" is the mailbox leaving CLOSED, or the fallback
    --- title reaching the tile map — whichever the patch gets to first.
    local function open_panel()
        t.check("the menu is up for the panel", press_until("Start", menu_open, 6, 40),
                "the START menu is not showing")
        cursor_on(slink_index)
        return press_until("A", function()
            return state() ~= Panel.CLOSED or on_screen("SOUL LINK")
        end, 12, 40)
    end

    -- ── OPEN 1: nothing held, so the fallback has to hold the screen ─────────────────
    t.check("selecting SLINK opens the panel", open_panel(),
            "no SOUL LINK title and no mailbox transition — the dispatch trampoline did not "
            .. "reach bank $3F")
    t.check("the panel announces itself to the client", wait(function() return state() == Panel.AWAIT end, 120),
            fmt("panel state is %d — the client is never told it may paint", state()))
    local await_seen = t.frame
    t.check("with no client rows it falls back instead of hanging",
            wait(function() return on_screen("NO CLIENT") end, 300),
            "the stage wait never timed out onto the fallback")
    -- The patch's timeout leaves the state alone (slink.asm:334-335). That is the whole
    -- reason panel.lua measures its own deadline from the transition IT observed.
    -- F.COMPANION.panel_stage_timeout is the exact ABI number (90, same on both foundations,
    -- PLAN M3 B5); the margin just clears it comfortably.
    local STAGE_TIMEOUT = t.facts.COMPANION.panel_stage_timeout
    idle(math.max(0, (STAGE_TIMEOUT + 30) - (t.frame - await_seen)))
    t.check(fmt("+9 is still AWAIT after the patch's %d-frame stage timeout", STAGE_TIMEOUT),
            state() == Panel.AWAIT,
            fmt("state=%d after %d frames of AWAIT", state(), t.frame - await_seen))
    t.check("nothing was staged with no rows held", read(PAGES) == 0,
            fmt("+11 = %d with no payload", read(PAGES)))

    -- ── a reply that misses the deadline paints NOTHING ──────────────────────────────
    -- This is the assertion the patch cannot make for itself: it has no clock the client can
    -- read, so "is this AWAIT still fresh" is answered only in panel.lua. The reply below is
    -- well past DEADLINE frames old by the time service() sees it.
    reply({ cmd = "link_panel", rows = PAGED })
    idle(t.facts.COMPANION.panel_deadline + 60)
    t.check("a reply after the deadline is not painted", not on_screen("PAIRS 3/5"),
            fmt("a %d-frame-old AWAIT was painted over a revealed fallback",
                t.frame - await_seen))
    t.check("the revealed fallback survived the late reply", on_screen("NO CLIENT"),
            "NO CLIENT was overwritten")
    t.check("the late reply never reached STAGED", state() == Panel.AWAIT,
            fmt("state=%d", state()))

    -- ── close, and the held rows come back on the NEXT open ──────────────────────────
    t.check("a button press closes the fallback panel",
            press_until("B", function() return not on_screen("SOUL LINK") end, 12, 40),
            "still on screen after 12 presses")
    t.check("the panel clears its state on the way out", state() == Panel.CLOSED,
            fmt("panel state left at %d — a client would keep painting over the map", state()))

    -- ── OPEN 2: the held rows stage INSIDE the deadline ──────────────────────────────
    t.check("the panel opens again", open_panel(), "the second open never reached the panel")
    local staged = wait(function() return on_screen("PAIRS 3/5") end, 300)
    t.check("rows held from the late reply stage on the next open", staged,
            fmt("state=%d +11=%d — held rows were dropped instead of kept",
                state(), read(PAGES)))
    t.check("staging sets the handshake to STAGED", state() == Panel.STAGED,
            fmt("state is %d after the client painted", state()))
    t.check("the client tells the patch how many pages there are", read(PAGES) == 2,
            fmt("published %d pages for 26 rows", read(PAGES)))
    t.check("the fallback was painted over", not on_screen("NO CLIENT"),
            "NO CLIENT is still visible under the staged page")
    t.check("a later row landed too", on_screen("VIRIDIAN FOREST"),
            "only the first rows were painted")
    t.check("the whole first page is on screen", on_screen(LAST_ON_PAGE1),
            "row 18 did not land — the page is short")
    t.check("page 2 is NOT on screen yet", not on_screen(FIRST_ON_PAGE2),
            "a row from the next page leaked onto the first")
    dump("page 1", 0, 8)

    -- ── A turns the page ─────────────────────────────────────────────────────────────
    -- The turn is the SAME handshake as the open (slink.asm:248-271 keeps STAGED, bumps +10,
    -- whites out and jumps back to .page, which rewrites AWAIT) — so a torn page is
    -- impossible on a turn for the same reason it is on an open, and panel.lua has to read
    -- STAGED->AWAIT as a fresh invitation rather than a persisting one.
    -- Watch +10, not +9. AWAIT on a turn can be a ONE-FRAME state: the patch writes it and
    -- our own service() answers with STAGED inside the same frame_end, so a poll that samples
    -- +9 between steps can legitimately never see it. +10 is written once and only cleared at
    -- dismissal, and the page-2 content below is what proves the AWAIT actually happened.
    local re_awaited = press_until("A", function() return read(PAGE) == 1 end, 12, 30)
    t.check("A asks for another page", re_awaited,
            fmt("page byte is %d, state=%d — the panel never turned", read(PAGE), state()))
    if re_awaited then
        t.check("the second page is on screen", wait(function() return on_screen(FIRST_ON_PAGE2) end, 300),
                fmt("row 19 never appeared after the page turn (state=%d)", state()))
        t.check("the first page is gone", not on_screen("PAIRS 3/5"),
                "page 1 is still showing underneath page 2")
        dump("page 2", 0, 8)
    end

    -- ── B closes from a page ─────────────────────────────────────────────────────────
    -- On the LAST page A closes too; B must close from ANYWHERE, which is the whole reason
    -- the panel does not use WaitForTextScrollButtonPress (it cannot tell the two apart).
    t.check("B closes the panel from a page",
            press_until("B", function()
                return not on_screen("PAIRS 3/5") and not on_screen(FIRST_ON_PAGE2)
            end, 12, 40),
            "B did not close the panel")
    t.check("closing resets the page for next time", read(PAGE) == 0,
            fmt("page byte left at %d", read(PAGE)))
    t.check("closing resets the handshake", state() == Panel.CLOSED,
            fmt("panel state left at %d", state()))

    -- ── EXIT still works, i.e. its index did not move ────────────────────────────────
    t.check("the menu is up again", press_until("Start", menu_open, 6, 40),
            "the START menu is not showing")
    t.check("the cursor reaches EXIT's index", cursor_on(slink_index - 1),
            fmt("wanted %d, stalled at %d", slink_index - 1, at("wCurrentMenuItem")))
    press("A", 8)
    idle(60)
    t.check("EXIT still closes the menu", menu_closed(),
            "EXIT's index moved — appending was supposed to leave every existing index alone")

    -- ── the game survives ────────────────────────────────────────────────────────────
    local x0, y0 = at("wXCoord"), at("wYCoord")
    local function moved() return at("wXCoord") ~= x0 or at("wYCoord") ~= y0 end
    for i = 1, 8 do
        if moved() then break end
        press(({ "Right", "Left" })[(i % 2) + 1], 24)
    end
    t.check("the player still walks after all that", moved(),
            fmt("stuck at (%d,%d) — a broken menu can leave the overworld loop wedged", x0, y0))
end, debug.traceback)

if not ok then t.check("menu row / panel gate sequence", false, tostring(err)) end
t.finish(fmt("SLINK row at %s, EXIT at %s", tostring(slink_row), tostring(exit_row)))
