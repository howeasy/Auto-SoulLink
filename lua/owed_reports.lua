-- Reports the server must receive (review 2026-09-24 MAJOR-1): the post-DONE trade_done / nothing-changed,
-- an uncertain declaration, a withdrawn offer. Each is kept until the server has ANSWERED the line that
-- carried it. server/server.py answers every line of a connection with exactly one {"commands"} line, in
-- order (_respond), so the n-th reply line answers the n-th line sent. A reply the server gave WITHOUT
-- processing the line (the identity/admission gate's {"cmd": "noop", "refused": ...}) answers nothing:
-- that report is sent again once a later reply comes back unrefused (OMP review of 15f1e786). A
-- connection that dies first (lua/connector.lua disconnect empties its send queue, and a line the OS took
-- may still never arrive) forgets its line numbers, and every unanswered report goes again after the next
-- hello. The server takes a replay idempotently (a trade report is matched by token and settled once,
-- state.py _handle_trade_done). An unreadable reply only delays a retirement, never loses a report.
-- Shared by lua/gen1/client.lua and lua/gen2/client.lua; `list` is the client's trade_owed.
local OwedReports = {}

local function refused(commands)
    for _, c in ipairs(commands) do
        if type(c) == "table" and c.refused ~= nil and c.refused ~= false then return true end
    end
    return false
end

function OwedReports.new()
    local self = { list = {}, lines = 0, replies = 0, paused = false }

    -- every line the client hands the transport on this connection
    function self:line_sent() self.lines = self.lines + 1 end

    -- every reply line, readable or not: it answers the next line in order
    function self:line_received() self.replies = self.replies + 1 end

    -- a readable reply's command list (after line_received): retires the report its line carried, or,
    -- refused, marks it unsent and holds every resend until the server answers a line normally again
    function self:answer(commands)
        local no = refused(commands)
        self.paused = no
        for i, e in ipairs(self.list) do
            if e.line == self.replies then
                if no then e.line = nil else table.remove(self.list, i) end
                return
            end
        end
    end

    -- Per frame, and after each new report. Called every frame the socket is down, so a reply line
    -- still queued from the dead connection (drained the same frame) never counts on the next one:
    -- the connector waits RECONNECT_FRAMES before reconnecting.
    function self:step(connected, ready, send)
        if not connected then
            self.lines, self.replies, self.paused = 0, 0, false
            for _, e in ipairs(self.list) do e.line = nil end
            return
        end
        if not ready or self.paused then return end
        for _, e in ipairs(self.list) do
            if not e.line then
                if not send(e.event, e.fields) then return end -- keep the order: the rest waits
                e.line = self.lines
            end
        end
    end

    return self
end

return OwedReports
