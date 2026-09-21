-- SFX arbiter: one sound cue per frame.
--
-- Several sites can request a sound in the same frame (a terminal KO batch asks for the linked-KO
-- cue, the generic server play_sound, and the game-over cue). The Lua m4a SE1 poke is
-- last-write-wins (no busy test), and the native mailbox queues a second opcode behind the first
-- and posts it on the next pump, so whichever cue ran last (or drained last) was the one heard, by
-- accident of command ordering. Collect the requests, play the highest-priority one once at frame
-- end. The winner keeps its own route flag: only cues the caller marks `native_ok` may take the
-- companion mailbox (a queued native sound pumped before a completion consumer overwrites that
-- operation's ack fields — see mailbox.lua post()/pump() and the client's poll order).
--
-- ponytail: per-frame arbitration only — no cross-frame queue (a losing cue is dropped, not
-- deferred), and how the engine itself mixes a native PlaySE is unverified. Add a queue if a
-- dropped cue ever turns out to matter.

local A = {}

--- Create an arbiter.
-- `ranks` maps sound id -> priority number; ids absent from the table rank 0 (generic).
-- Pass the caller's own SE constants (they are ROM-profile dependent), never literals.
-- Returns {request = f(sound), flush = f(sink)}:
--   request(sound, native_ok)  record a cue for this frame (nil is ignored); native_ok marks
--                   a cue that may go through the companion mailbox
--   flush(sink)     call sink(sound, native_ok) once with the winner, then clear. Ties keep the first
--                   request, so a same-priority duplicate coalesces to one call. Nothing
--                   requested = sink is not called at all.
function A.new(ranks)
    local self = {}
    local best, best_rank, best_native = nil, nil, false
    function self.request(sound, native_ok)
        if sound == nil then return end
        local rank = ranks[sound] or 0
        if best == nil or rank > best_rank then best, best_rank, best_native = sound, rank, native_ok and true or false end
    end
    function self.flush(sink)
        local s, n = best, best_native
        best, best_rank, best_native = nil, nil, false
        if s ~= nil then sink(s, n) end
    end
    return self
end

return A
