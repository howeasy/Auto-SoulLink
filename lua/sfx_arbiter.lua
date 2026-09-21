-- SFX arbiter: one sound cue per frame.
--
-- Several sites can request a sound in the same frame (a terminal KO batch asks for the linked-KO
-- cue, the generic server play_sound, and the game-over cue). Both delivery routes are
-- last-write-wins — the Lua m4a SE1 poke overwrites the player with no busy test, and the native
-- mailbox has a single slot — so whichever cue happened to run last was the one heard, by accident
-- of command ordering. Collect the requests, play the highest-priority one once at frame end.
--
-- ponytail: per-frame arbitration only — no cross-frame queue (a losing cue is dropped, not
-- deferred), and how the engine itself mixes a native PlaySE is unverified. Add a queue if a
-- dropped cue ever turns out to matter.

local A = {}

--- Create an arbiter.
-- `ranks` maps sound id -> priority number; ids absent from the table rank 0 (generic).
-- Pass the caller's own SE constants (they are ROM-profile dependent), never literals.
-- Returns {request = f(sound), flush = f(sink)}:
--   request(sound)  record a cue for this frame (nil is ignored)
--   flush(sink)     call sink(sound) once with the winner, then clear. Ties keep the first
--                   request, so a same-priority duplicate coalesces to one call. Nothing
--                   requested = sink is not called at all.
function A.new(ranks)
    local self = {}
    local best, best_rank = nil, nil
    function self.request(sound)
        if sound == nil then return end
        local rank = ranks[sound] or 0
        if best == nil or rank > best_rank then best, best_rank = sound, rank end
    end
    function self.flush(sink)
        local s = best
        best, best_rank = nil, nil
        if s ~= nil then sink(s) end
    end
    return self
end

return A
