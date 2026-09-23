-- lua/core/deferred.lua -- the deferred command FIFO, shared by every generation.
--
-- Lifted from lua/gen1/client.lua:717-822 (run_deferred). Policy only; every byte that moves
-- goes through an injected executor, and each command runs inside pcall between exec.arm() and
-- exec.disarm() (disarm again after the pcall, as Gen 1 does, so a throw never leaves it armed).
--
--   Q = Deferred.new{ exec = {...}, memorial_box = int, send, log, hud, identity, read_party }
--   exec.arm(), exec.disarm()                      the "overworld" write window (+ allow ranges)
--   exec.faint_slot(slot, cmd_name)                force_faint / force_explode at the checkpoint
--   exec.deposit(key, slot_hint)       -> true | nil, reason
--   exec.withdraw(key, stats, nickname) -> true | nil, reason   (base stats: the executor's job)
--   exec.memorialize(key, slot_hint)   -> true | nil, reason
--   exec.stats_of(mon) -> stats table  (optional; default { level = m.level, maxHP = m.max_hp })
--   exec.rescan()                      (optional; after a successful move)
-- send/log/hud/identity/read_party may be left out: Session.new binds its own (session.lua).
--
-- Gate: Q:run(gate, frame, game_over) asks gate() -> ok, why only when the queue is non-empty
-- (Session's gate = writes_enabled and connected and game.checkpoint_ok()). One command per call.
-- Keyed replies keep cmd.key (what the server tracks), even when a retired alias moved the
-- physical key: box_mon_failed, stats_cache, sync_retrieve_done/_failed, memorialize_done/_failed.
-- Tail retry ONLY on the exact reasons "party full" (budget = queue length at the first refusal
-- + 1) and "last party mon" (unbounded; dropped silently once game_over is latched).
--
-- DELIBERATE DELTA FROM GEN 1 (docs/gen3/PLAN.md:57, R9; §5.4): Gen 1 sends stats_cache BEFORE
-- boxes:deposit (gen1/client.lua:761), so a refused deposit still told the server the mon was
-- in flight. Here the stats are SNAPSHOTTED before the deposit (party-only fields are zeroed by
-- the move) and stats_cache is SENT only after the executor confirms it; a refusal sends
-- box_mon_failed and no stats_cache. Gen 1 adopts this when it re-binds.
--
-- Can Gen 1 bind it unchanged? Its run_deferred body is this code with self.boxes:* and
-- writes:faint_party_slot as the executors, box_count - 1 as memorial_box and
-- rom.base_stats_for resolved inside its withdraw closure. Q.items is the plain array Gen 1
-- tests read as client.deferred (alias it). Only the stats_cache ordering above changes.
local Deferred = {}
Deferred.__index = Deferred

local EXEC = { "arm", "disarm", "faint_slot", "deposit", "withdraw", "memorialize" }

local function nick_label(key, nickname)
    if nickname and nickname ~= "" then return nickname end
    return key and key:sub(1, 8) or "?"
end

local function default_stats(m) return { level = m.level, maxHP = m.max_hp } end

function Deferred.new(p)
    local exec = assert(p and p.exec, "deferred: exec required")
    for _, n in ipairs(EXEC) do assert(exec[n] ~= nil, "deferred: exec." .. n .. " required") end
    return setmetatable({ items = {}, exec = exec, memorial_box = p.memorial_box, send = p.send,
                          log = p.log, hud = p.hud, identity = p.identity, read_party = p.read_party,
                          hold = nil }, Deferred)
end

function Deferred:push(cmd) self.items[#self.items + 1] = cmd end
function Deferred:size() return #self.items end

-- n, why, age (frames), head command name -- for the tick HUD line (PLAN §5.4). why is nil when
-- nothing has been refused since the last command finished.
function Deferred:pending(frame)
    local n = #self.items
    if n == 0 then return 0, nil, 0, nil end
    local h = self.hold
    return n, h and h.why, h and (frame - h.since) or 0, self.items[1].cmd
end

local function held(self, frame, why)
    if self.hold then self.hold.why = why else self.hold = { why = why, since = frame } end
end

function Deferred:run(gate, frame, game_over)
    if #self.items == 0 then self.hold = nil; return false end
    local open, gate_why = gate()
    if not open then held(self, frame, gate_why or "gate closed"); return false end
    local exec, id = self.exec, self.identity
    local log = self.log or function() end
    local send = self.send or function() return false end
    local function show(...) if self.hud then self.hud.show(...) end end
    local function find(key)
        local party = self.read_party and self.read_party() or nil
        if not id then return nil end
        return id:find_party_slot(key, party)
    end
    local function rescan() if exec.rescan then exec.rescan() end end

    local cmd = table.remove(self.items, 1)
    local requeued
    -- A retired alias (a rejected key_change) names the OLD key; the executor gets the key the
    -- cartridge holds and the evidence-validated slot. Evidence failure is TERMINAL for it: the
    -- executor's own key lookup would find whichever record carries the duplicated key.
    local r = id and id:retired(cmd.key)
    local phys, hint, refused = r and r.new_key or cmd.key, nil, nil
    if r then
        local slot, _, _, why = find(cmd.key)
        hint, refused = slot, (not slot) and (why or "retired record not found") or nil
    end
    local ok, err = pcall(function()
        exec.arm()
        if refused and (cmd.cmd == "box_mon" or cmd.cmd == "memorialize") then
            log(cmd.cmd .. " refused for the retired key: " .. refused .. " " .. tostring(cmd.key))
            send(cmd.cmd .. "_failed", { key = cmd.key, reason = refused })
        elseif cmd.cmd == "force_faint" or cmd.cmd == "force_explode" then
            local slot, _, _, why = find(cmd.key)
            if slot then
                exec.faint_slot(slot, cmd.cmd)
                show("!! " .. nick_label(cmd.key, cmd.nickname) .. " KO'd", 255, 80, 80, 360)
            else
                -- left the party before the checkpoint, or no longer names one mon: no byte
                -- moves. The protocol has no force_faint NACK.
                log(cmd.cmd .. " dropped at the checkpoint: " .. (why or "key not in party")
                    .. " " .. tostring(cmd.key))
            end
        elseif cmd.cmd == "box_mon" then
            local slot, mon = find(cmd.key)
            local stats = slot and (exec.stats_of or default_stats)(mon) or nil  -- BEFORE the move
            local done, reason = exec.deposit(phys, hint)
            if not done then
                send("box_mon_failed", { key = cmd.key, reason = reason or "deposit refused" })
                show("X Box fail: " .. nick_label(cmd.key, mon and mon.nickname), 255, 80, 80, 240)
            else
                if stats then send("stats_cache", { key = cmd.key, stats = stats }) end  -- AFTER it
                rescan()
                show("↓ " .. nick_label(cmd.key, mon and mon.nickname) .. " boxed", 100, 180, 255, 200)
            end
        elseif cmd.cmd == "party_mon" then
            local done, reason = exec.withdraw(cmd.key, cmd.stats, cmd.nickname)
            if done then
                send("sync_retrieve_done", { key = cmd.key })
                rescan()
                show("↑ " .. nick_label(cmd.key, cmd.nickname) .. " unboxed", 100, 255, 160, 200)
            elseif reason == "party full" and (cmd.full_retries or 0) < (cmd.full_budget or (#self.items + 1)) then
                -- Whiteout rebuild: the server queues party_mon BEFORE the memorializes that free
                -- a slot, and sync_retrieve_failed is final there -- wait at the TAIL, bounded by
                -- the queue length seen at the first refusal.
                cmd.full_budget = cmd.full_budget or (#self.items + 1)
                cmd.full_retries = (cmd.full_retries or 0) + 1
                self.items[#self.items + 1] = cmd
                requeued = "party full"
                log("party_mon " .. tostring(cmd.key) .. ": party full, retry " .. cmd.full_retries
                    .. "/" .. cmd.full_budget .. " after the queue")
            else
                send("sync_retrieve_failed", { key = cmd.key, reason = reason or "withdraw refused" })
            end
        elseif cmd.cmd == "memorialize" then
            local _, mem_mon = find(cmd.key)
            local done, reason = exec.memorialize(phys, hint)
            if done then
                send("memorialize_done", { key = cmd.key, box = self.memorial_box })
                rescan()
                if id then id:forget(cmd.key) end
                show("† " .. nick_label(cmd.key, mem_mon and mem_mon.nickname) .. " buried", 255, 140, 40, 300)
            elseif reason == "last party mon" and game_over then
                log("memorialize dropped: last mon after game over " .. tostring(cmd.key))
            elseif reason == "last party mon" then
                -- block until a party_mon lands -- at the TAIL: the rebuild that makes the
                -- memorial legal is itself queued behind this command (A5)
                self.items[#self.items + 1] = cmd
                requeued = "last party mon"
            else
                send("memorialize_failed", { key = cmd.key, reason = reason or "memorial refused" })
                show("X Mem fail: " .. nick_label(cmd.key, mem_mon and mem_mon.nickname), 255, 80, 80, 300)
            end
        end
        exec.disarm()
    end)
    exec.disarm()
    if not ok then log("deferred " .. tostring(cmd.cmd) .. " failed: " .. tostring(err)) end
    if requeued then held(self, frame, requeued) else self.hold = nil end
    return true
end

return Deferred
