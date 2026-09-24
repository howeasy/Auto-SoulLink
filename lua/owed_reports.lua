-- Reports the server must receive (review 2026-09-24 MAJOR-1): the post-DONE trade_done / nothing-changed,
-- an uncertain declaration, a withdrawn offer. Each is kept until the server has ANSWERED the line that
-- carried it. server/server.py answers every line of a connection with exactly one {"commands"} line, in
-- order (_respond), so the n-th reply line acknowledges the n-th line sent. A connection that dies first
-- (lua/connector.lua disconnect empties its send queue, and a line the OS took may still never arrive)
-- forgets its line numbers, and every unanswered report goes again after the next hello. The server takes
-- a replay idempotently (a trade report is matched by token and settled once, state.py _handle_trade_done).
-- A missed reply line only delays a retirement, never loses a report.
-- Shared by lua/gen1/client.lua and lua/gen2/client.lua; `list` is the client's trade_owed.
local OwedReports = {}

function OwedReports.new()
    local self = { list = {}, lines = 0, replies = 0 }

    -- every line the client hands the transport on this connection
    function self:line_sent() self.lines = self.lines + 1 end

    -- every reply line; reports go out in list order, so the answered ones are a prefix
    function self:reply_received()
        self.replies = self.replies + 1
        local head = self.list[1]
        while head and head.line and head.line <= self.replies do
            table.remove(self.list, 1)
            head = self.list[1]
        end
    end

    -- Per frame, and after each new report. Called every frame the socket is down, so a reply line
    -- still queued from the dead connection (drained the same frame) never counts on the next one:
    -- the connector waits RECONNECT_FRAMES before reconnecting.
    function self:step(connected, ready, send)
        if not connected then
            self.lines, self.replies = 0, 0
            for _, e in ipairs(self.list) do e.line = nil end
            return
        end
        if not ready then return end
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
