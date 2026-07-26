-- scenario_infopanel.lua — END-TO-END for the native SOULLINK panel (ROADMAP §6, step 4).
--
-- This is the only test that exercises the WHOLE chain with nothing faked:
--   real server -> link_panel command -> production client stages it into EWRAM ->
--   companion patch draws it -> START-menu row opens it -> A pages -> B closes.
--
-- Everything before this proved a piece: test_live_infoscreen draws a FIXTURE, test_link_panel
-- builds a payload with no emulator. Neither would notice if the two never met — if the client
-- ignored link_panel, or staged it in a shape the patch rejects, both would still be green.
--
-- Runner: links A slot0 <-> B slot0, then writes the go-file. Both sides assert symmetrically.
return function(ctx)
    local log = ctx.log
    if not ctx.wait_go() then return false, "no go-file" end

    local SI   = 0x0203FD44          -- SlinkInfo: +0 enable +1 opened +2 drawn +3 lines +4 page +5 pages
    local LINE = SI + 8              -- u8[8][32], FR-encoded, 0xFF-terminated
    local SC2  = 0x03000F9C          -- sScriptContext2Enabled
    local SPLICE = 5                 -- the SOULLINK row's index once spliced (see test_live_startmenu)

    local function tap(btn, n)
        for i = 1, (n or 30) do
            if i <= 3 then joypad.set({ [btn] = true }) end
            coroutine.yield()
        end
    end
    local function row_len(i)
        local n = 0
        while n < 32 and memory.read_u8(LINE + i * 32 + n) ~= 0xFF do n = n + 1 end
        return n
    end

    -- 1. The client must stage a panel built from REAL server data, and turn the row on.
    -- Wait for a PAIR specifically, not merely for a non-empty panel: the server sends its first
    -- link_panel before the runner injects the link, so a `lines > 0` check would be satisfied by
    -- the "no linked pairs yet" placeholder and prove nothing about the payload crossing.
    -- The runner injects THREE pairs, so a full first page is 6 rows of pair data.
    if not ctx.wait_until(function()
            return (memory.read_u8(SI + 3) >= 6 and memory.read_u8(LINE + 32) == 0xFE) or nil
        end, 7200, "the linked pairs staged into EWRAM") then
        return false, "client never staged the linked pair (lines=" ..
                      memory.read_u8(SI + 3) .. ") — link_panel not sent, or not handled"
    end
    local lines, pages = memory.read_u8(SI + 3), memory.read_u8(SI + 5)
    log(string.format("panel staged: lines=%d pages=%d enable=%d", lines, pages,
                      memory.read_u8(SI)))
    if memory.read_u8(SI) ~= 1 then return false, "the SOULLINK row was never enabled" end

    -- 2. The linked pair must render AS A PAIR: two rows, the second flagged as a continuation
    -- (its slot starts with the 0xFE field separator = empty label). That flag is what draws the
    -- tie bracket, and it is the difference between "a pair" and "two unrelated mons".
    if lines < 2 then return false, "expected at least 2 rows for one linked pair, got " .. lines end
    if memory.read_u8(LINE) == 0xFE then
        return false, "first row of a pair must carry the area label"
    end
    if memory.read_u8(LINE + 32) ~= 0xFE then
        return false, "second row is not marked as a pair continuation — no bracket would draw"
    end
    if row_len(0) < 6 or row_len(1) < 6 then
        return false, "pair rows look empty — the server sent no usable mon data"
    end
    log("linked pair rendered as a pair (row 2 marked continuation)")
    -- 3 pairs (6 rows) + 3 summary rows = 9 rows at 6 per page = 2 pages. Without a second page
    -- the pagination step below would be vacuous.
    if pages < 2 then return false, "expected 2 pages from 3 linked pairs, got " .. pages end

    -- 3. Open it the way a player does: START -> the SOULLINK row.
    tap("Start", 90)
    for _ = 1, SPLICE do tap("Down", 12) end
    tap("A", 60)
    if not ctx.wait_until(function() return memory.read_u8(SC2) ~= 0 or nil end, 600,
                          "panel to open from the menu row") then
        return false, "choosing the row never opened the panel"
    end
    ctx.frames(30)
    -- ...and the screen must not be black. The engine fades to black for any start-menu action it
    -- does not recognise; the patch undoes that. Asserted here too because this is the only test
    -- that opens the panel with a REAL client attached, where the timing differs.
    local lit = 0
    for i = 1, 15 do if memory.read_u16_le(0x05000000 + i * 2) ~= 0 then lit = lit + 1 end end
    log(string.format("panel open: lines=%d page=%d pages=%d nonblack=%d/15",
        memory.read_u8(SI + 3), memory.read_u8(SI + 4), memory.read_u8(SI + 5), lit))
    if lit < 8 then return false, "screen faded to black behind the panel" end
    -- Keep a picture of the panel showing REAL run data. Nothing above proves it looks right —
    -- only that it drew what was intended — so this is for human review.
    pcall(function()
        client.screenshot(ctx.duo.wt .. "/patch/build/duo_infopanel_" .. ctx.player .. ".png")
    end)

    -- 4. A pages forward. The client re-stages and re-arms the patch's frame-hook open, so the
    -- page byte must advance and the panel must come back up.
    local page0 = memory.read_u8(SI + 4)
    tap("A", 60)
    local paged = ctx.wait_until(function()
        return memory.read_u8(SI + 4) ~= page0 or nil
    end, 900, "page to advance")
    if not paged then return false, "A did not advance the page" end
    log(string.format("paged %d -> %d", page0, memory.read_u8(SI + 4)))
    if not ctx.wait_until(function() return memory.read_u8(SC2) ~= 0 or nil end, 900,
                          "next page to open") then
        return false, "the next page never opened"
    end

    -- 5. B closes for good and releases the field — a player who cannot get out of this screen is
    -- stuck in a locked overworld.
    ctx.frames(30)
    tap("B", 60)
    if not ctx.wait_until(function() return memory.read_u8(SC2) == 0 or nil end, 900,
                          "field released") then
        return false, "B did not close the panel — field left locked"
    end
    log("B closed the panel and released the field")
    return true
end
