-- scenario_gen3_infopanel.lua — infopanel_gen3 (RR companion): the SOULLINK panel end to end.
--
-- A tees the session's command handler for link_panel (read-only: it logs the rows the server
-- sent, "PANEL_ROWS <json>", and passes the command on) and says PANEL_TEE; only then does the
-- runner link the slot pairs both fixtures hold, so the next link_panel is the one recorded here.
-- A waits for the client to stage it (SlinkInfo: lines, pages), then opens the panel the way a
-- player does -- START, cursor down to the SOULLINK row, A (patch/src/handlers.c
-- slink_startmenu_cb bumps `opened`, drive_info draws) -- logs what was drawn (every staged line
-- and the header slot, raw bytes) and closes it with A; then opens it again and closes it with
-- B. The oracle decodes the bytes with the Python charmap and compares them to the last
-- PANEL_ROWS before the open (tools/e2e_duo.py gen3_panel_problems). B idles.
--
-- Fixture: rr_town (one mon, NO Pokedex yet). handlers.c slink_setup_start_menu splices the
-- SOULLINK row only into the 6-row menu; once the Pokedex is owned the stock menu has 7 rows and
-- the row is never added (live on rr_battle2: count=7 order=0,1,2,3,4,5,6 -- a product finding,
-- reported, not worked around). Paging is not exercised: the START-row path always re-stages
-- page 1 (lua/gen3/entry.lua panel_closed reports "closed" only, TODO C4-7).
--
-- Addresses: SlinkInfo is the pack's native.INFO (handlers.c:262, +0 enable +1 opened +2 drawn
-- +3 lines +4 page +5 pages +6 gen, +8 line[8][32]); sScriptContext2Enabled handlers.c:532. The
-- START menu's count/order (0x020370F5/0x020370F6) were located live on RR by
-- test_live_startmenu.lua; the cursor byte sits at pret's 0x020370F4 (sStartMenuCursorPos,
-- pokefirered.sym) and is PROVEN here at runtime: every Down must move it by exactly one row.
local SC2 = 0x03000F9C
local CURSOR, COUNT, ORDER = 0x020370F4, 0x020370F5, 0x020370F6
local SOULLINK_ACTION = 8          -- the hijacked dead action id (test_live_soullinkmenu.lua)

local function u8(a) return memory.read_u8(a, "System Bus") end
local function hex(addr, n)
    local out = {}
    for i = 0, n - 1 do out[#out + 1] = string.format("%02X", u8(addr + i)) end
    return table.concat(out)
end
local function vram_hash()
    local h = 0
    for a = 0x06000000, 0x0600FFFF, 4 do h = (h * 31 + memory.read_u32_le(a, "System Bus")) % 0x7FFFFFFF end
    return string.format("%08X", h)
end

local function open_panel(ctx, N, n)
    local SI = N.INFO
    if not ctx.wait_until(function() return ctx.on_field() and u8(SC2) == 0 end, 60, "a free field") then
        return false, "the field never freed before open " .. n
    end
    ctx.frames(30)
    local o0, v0 = u8(SI + 1), vram_hash()
    ctx.G.tap("Start", 2, 60)
    local count = u8(COUNT)
    local target, order = nil, {}
    for i = 0, count - 1 do
        order[#order + 1] = u8(ORDER + i)
        if u8(ORDER + i) == SOULLINK_ACTION then target = i end
    end
    ctx.log(ctx.fmt("START_MENU %d count=%d order=%s cursor=%d", n, count, table.concat(order, ","), u8(CURSOR)))
    if not target then return false, "no SOULLINK row in the START menu (count " .. count .. ")" end
    for _ = 1, count do
        local c = u8(CURSOR)
        if c == target then break end
        ctx.G.tap("Down", 2, 14)
        if u8(CURSOR) ~= (c + 1) % count then
            return false, ctx.fmt("the START cursor moved %d -> %d on Down (count %d)", c, u8(CURSOR), count)
        end
    end
    if u8(CURSOR) ~= target then return false, "the cursor never reached the SOULLINK row" end
    ctx.G.tap("A", 2, 10)
    local up = ctx.wait_until(function()
        return u8(SI + 1) ~= o0 and u8(SI + 2) == u8(SI + 1) and u8(SC2) ~= 0
    end, 30, "the panel open " .. n)
    if not up then
        return false, ctx.fmt("no panel: opened %d->%d drawn %d sc2 %d", o0, u8(SI + 1), u8(SI + 2), u8(SC2))
    end
    ctx.frames(120)
    ctx.log(ctx.fmt("PANEL_OPEN %d opened=%d->%d drawn=%d sc2=%d lines=%d page=%d pages=%d vram=%s->%s",
                    n, o0, u8(SI + 1), u8(SI + 2), u8(SC2), u8(SI + 3), u8(SI + 4), u8(SI + 5), v0, vram_hash()))
    for i = 0, u8(SI + 3) - 1 do ctx.log(ctx.fmt("PANEL_LINE %d %d %s", n, i, hex(SI + 8 + i * 32, 32))) end
    ctx.log(ctx.fmt("PANEL_SLOT7 %d %s", n, hex(SI + 8 + 7 * 32, 32)))
    return true
end

local function close_panel(ctx, n, button)
    ctx.G.tap(button, 2, 10)
    local down = ctx.wait_until(function() return u8(SC2) == 0 end, 30, "the panel close " .. n)
    ctx.log(ctx.fmt("PANEL_CLOSED %d button=%s sc2=%d", n, button, u8(SC2)))
    if not down then return false, button .. " did not close the panel" end
    return true
end

return function(ctx)
    if not ctx.rr then return false, "infopanel_gen3 is the RR companion's panel" end
    if ctx.player == "b" then
        if not ctx.wait_go() then return false, "no go-file" end
        ctx.wait_until(ctx.partner_done, 900, "A's panel run")
        return true, "idle"
    end
    local JSON = dofile(ctx.D.wt .. "/lua/json_codec.lua")
    local f = assert(io.open(ctx.D.wt .. "/data/games/gen3_rr/profile.json", "rb"))
    local N = JSON.decode(f:read("a")).native
    f:close()
    local rows
    local raw = ctx.session.handle_command
    ctx.session.handle_command = function(self, cmd)
        if type(cmd) == "table" and cmd.cmd == "link_panel" and type(cmd.rows) == "table" then
            rows = cmd.rows
            ctx.log("PANEL_ROWS " .. JSON.encode(rows))
        end
        return raw(self, cmd)
    end
    ctx.log("PANEL_TEE")
    if not ctx.wait_go() then return false, "no go-file" end
    local staged = ctx.wait_until(function()
        if not (rows and #rows >= 5 and rows[1]:find("|", 1, true)) then return false end   -- a pair row
        local pages = (#rows + 5) // 6
        return u8(N.INFO + 5) == pages and u8(N.INFO + 3) == math.min(6, #rows)
    end, 120, "the linked panel staged")
    if not staged then
        return false, ctx.fmt("panel not staged: rows=%s lines=%d pages=%d", tostring(rows and #rows),
                              u8(N.INFO + 3), u8(N.INFO + 5))
    end
    ctx.frames(60)
    for n, button in ipairs({ "A", "B" }) do
        local ok, why = open_panel(ctx, N, n)
        if not ok then return false, why end
        ok, why = close_panel(ctx, n, button)
        if not ok then return false, why end
        ctx.frames(90)
    end
    return true, ctx.fmt("panel drawn from %d server rows, closed by A and by B", #rows)
end
