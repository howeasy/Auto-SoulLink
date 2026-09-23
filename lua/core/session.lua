-- lua/core/session.lua -- the generation-neutral client shell (P4 C4-1).
--
-- Lifted from lua/gen1/client.lua: send/seq :171-182, validate/pause :317-358, ack_cancel
-- :361-365, generic commands :480-596, hello gate :1804-1826, signal drain + failure banner
-- :1828-1845, alias observation :1852-1858, tick/safe :1859-1863, receive loop :1864-1876.
-- No BizHawk global and no memory write anywhere under lua/core: everything is injected, and
-- only the driver's executors (deferred exec.*, game.battle_write) move bytes.
--
--   S = Session.new{ net, json, hud, log, tag, player, game, identity, deferred }
--   S.send(event, fields) -> bool       S:validate() -> ok, why       S:handle_command(cmd)
--   S:start()  S:frame_end()  S:stop()  S:battle_pending_count()  S:drop_battle_writes(why)
--   state the driver may read/set: writes_enabled, hello_sent, game_over, config, resolved_areas,
--   seeded, pending_safe (set it on battle end; `safe` goes out once out of battle)
--
-- The game driver (the ONLY generation seam; docs/gen3/research/p4_gen1_contract_map.md §3.2):
--   required: frame() -> int; read_party() -> party|nil, why (mons carry .slot);
--     game_is_live() -> bool, why; hello_ready() -> bool, why (live AND (in battle OR checkpoint),
--     plus any version hold); hello_fields() -> table; tick_fields() -> table|nil (nil = no tick);
--     in_battle() -> bool; checkpoint_ok() -> bool, why
--   optional: save_cleared() -> bool; on_reset(); start() -> signals (drain/close/failure/
--     handler_error); on_signal(sig); frame_hooks = { fn, ... } (after the signal drain);
--     pre_pump() (before net.pump: Gen 1's panel service); on_disconnect(); after_receive()
--     (pcall'd, before the deferred run: Gen 1's trade_tick); play_sound(gen3_se_id);
--     commands = { [name] = fn(cmd) -> consumed? }; battle_write(entry, slot, mon, ending)
--       -> "done" | "hold", why | nil.
--
-- Command dispatch: noop; then game.commands[name] (returns true to CONSUME, false/nil to fall
-- through -- how Gen 1's receptionist show_menu, RR's trade/native/rival/explode, Gen 1's
-- known_keys bookkeeping on key_change_ack and its APEX pending_keys plug in); then
-- force_faint/force_explode routing; then box_mon/party_mon/memorialize (always deferred); then
-- the generic set. With no driver
-- handler, the prompts get the cancel sentinels and apply_trade is logged and ignored: no
-- write, no reply (the disabled-foundation write guard, docs/gen3/PLAN.md §10).
--
-- In-battle force_* (owner ruling 2026-09-23: vanilla FRLG behaves as Radical Red does today):
-- the key must resolve to one party slot; then, in battle and with a game.battle_write, the
-- command joins the core-owned pending-battle-write set, flushed every frame through
-- battle_write(entry, slot, mon, false): "done" removes it (bench mon), "hold" keeps it (the
-- active battler) with its reason and age on the tick HUD line, nil hands it to the deferred
-- checkpoint queue. Held entries are alias-aware (resolved through identity, including the
-- pending key_change alias; rewritten to the new key on key_change_ack). When the battle ends
-- each held entry gets one last battle_write(..., true); anything not "done" is deferred.
-- Which frames a battle write may land on is the driver's safety predicate, never the core's.
local Session = { TICK_INTERVAL = 30, VALIDATE_EVERY = 60, MAX_INVALID = 5, PENDING_HUD_FRAMES = 600 }

local CANCEL = { show_choices = { "menu_result", "choice", 127 }, show_menu = { "menu_result", "choice", 0 },
                 choose_mon = { "mon_chosen", "slot", 7 } }
local DEFERRED_CMDS = { box_mon = true, party_mon = true, memorialize = true }

local function hud_color(cmd)
    if type(cmd.color) == "table" then return cmd.color[1], cmd.color[2], cmd.color[3], cmd.duration end
    return cmd.r, cmd.g, cmd.b, cmd.frames
end

function Session.new(p)
    local net, json, hud = assert(p.net, "net"), assert(p.json, "json"), assert(p.hud, "hud")
    local game, identity, deferred = assert(p.game, "game"), assert(p.identity, "identity"), assert(p.deferred, "deferred")
    local tag, sink = p.tag or "[SLink]", p.log or function() end
    local function log(msg) sink(tag .. " " .. msg) end

    local self = {
        player = p.player, seq = 0, frame = 0, hello_sent = false,
        writes_enabled = false, invalid_streak = 0, gate_revoked = false, game_over = false,
        resolved_areas = {}, seeded = false, config = {}, pending_safe = false,
        battle_pending = {}, signals = nil, signal_failure_shown = false,
        game = game, identity = identity, deferred = deferred,
    }

    local function send(name, fields)
        if not net.connected() then
            log("drop " .. name .. ": not connected")
            return false
        end
        self.seq = self.seq + 1
        local msg = fields or {}
        msg.event, msg.player, msg.seq = name, self.player, self.seq
        net.send(json.encode(msg))
        return true
    end
    self.send = send
    -- the queue's shared seams are the session's own unless the caller bound others
    deferred.send = deferred.send or send
    deferred.log = deferred.log or log
    deferred.hud = deferred.hud or hud
    deferred.identity = deferred.identity or identity
    deferred.read_party = deferred.read_party or game.read_party

    -- ── the writes gate: pause, never drop ─────────────────────────────────────────
    function self:validate()
        local ok, why = game.game_is_live()
        if ok then
            self.invalid_streak = 0
            if not self.writes_enabled then
                log(self.gate_revoked and "writes re-enabled after a live validation" or "writes ENABLED")
                self.writes_enabled, self.gate_revoked = true, false
            end
        else
            self.invalid_streak = self.invalid_streak + 1
            -- the save was cleared (reset / new game): the next hello is a new session, and every
            -- alias pointed at a record that is gone with it
            if game.save_cleared and game.save_cleared() then
                self.hello_sent = false
                identity:clear()
                if game.on_reset then game.on_reset() end
            end
            if self.invalid_streak >= Session.MAX_INVALID and self.writes_enabled then
                -- the queues survive: an unreadable party is a transient the engine creates
                -- itself, and every command re-finds its key at the checkpoint anyway
                self.writes_enabled, self.gate_revoked = false, true
                log("writes PAUSED: " .. tostring(why))
            end
        end
        return ok, why
    end

    -- ── in-battle writes ───────────────────────────────────────────────────────────
    local function resolve(key, party)
        local slot, mon, _, why = identity:find_party_slot(key, party)
        local a = identity.pending
        if not slot and not why and a and a.old_key == key then slot, mon, why = identity:observe_one(a, party) end
        return slot, mon, why
    end

    function self:battle_pending_count() return #self.battle_pending end

    function self:drop_battle_writes(why)
        for _, e in ipairs(self.battle_pending) do
            log(e.cmd .. " dropped (" .. tostring(why) .. ") " .. tostring(e.key))
        end
        self.battle_pending = {}
    end

    local function flush_battle_writes()
        if #self.battle_pending == 0 then return end
        local ending = not game.in_battle()
        local party = game.read_party()
        local keep = {}
        for _, e in ipairs(self.battle_pending) do
            local slot, mon, why
            if party then slot, mon, why = resolve(e.key, party) end
            local res, rwhy
            if why then
                log(e.cmd .. " refused in battle: " .. why .. " " .. tostring(e.key))
                res = "done"
            elseif not self.writes_enabled then
                -- a paused gate holds battle writes too (Gen 1 on_battle_loop_head gates on
                -- writes_enabled, gen1/client.lua:1376): nothing lands while identity is unsure
                res, rwhy = "hold", self.gate_revoked and "writes paused" or "writes not enabled yet"
            elseif not party then
                res, rwhy = "hold", "party unreadable"
            elseif not slot then
                res, rwhy = "hold", "key not in party"      -- e.g. a borrowed party
            else
                res, rwhy = game.battle_write(e, slot, mon, ending)
            end
            if res == "hold" and not ending then
                e.why, e.since = rwhy or "held", e.since or self.frame
                keep[#keep + 1] = e
            elseif res ~= "done" then
                deferred:push({ cmd = e.cmd, key = e.key, nickname = e.nickname })
            end
        end
        self.battle_pending = keep
    end

    local function route_force(cmd)
        local c = cmd.cmd
        local entry = { cmd = c, key = cmd.key, nickname = cmd.nickname }
        local party = game.read_party()
        if not party then
            -- unreadable now (e.g. a naming prompt before the record lands): the checkpoint
            -- re-finds the key; a server command is never resent
            deferred:push(entry)
            return
        end
        local slot, _, _, why = identity:find_party_slot(cmd.key, party)
        if why then log(c .. ": " .. why .. " " .. tostring(cmd.key)) return end
        if not slot then log(c .. ": key not in party " .. tostring(cmd.key)) return end
        if game.battle_write and game.in_battle() then
            self.battle_pending[#self.battle_pending + 1] = entry  -- flushed this frame
        else
            deferred:push(entry)
        end
    end

    -- ── inbound commands ───────────────────────────────────────────────────────────
    function self:handle_command(cmd)
        local c = cmd.cmd
        if c == "noop" then return end
        local own = game.commands and game.commands[c]
        if own and own(cmd) then return end
        if c == "force_faint" or c == "force_explode" then return route_force(cmd) end
        if DEFERRED_CMDS[c] then deferred:push(cmd) return end
        local cancel = CANCEL[c]
        if cancel then
            send(cancel[1], { token = cmd.token, [cancel[2]] = cancel[3] })
        elseif c == "msgbox" or c == "gui_prompt" then
            local r, g, b, f = hud_color(cmd)
            hud.prompt(cmd.text, r, g, b, f)
        elseif c == "hud_show" then
            local r, g, b, f = hud_color(cmd)
            hud.show(cmd.text, r, g, b, f)
        elseif c == "play_sound" then
            if game.play_sound then game.play_sound(cmd.sound) end
        elseif c == "resolved_areas" then
            self.resolved_areas = {}
            for _, a in ipairs(cmd.areas or {}) do self.resolved_areas[a] = true end
            self.seeded = true
        elseif c == "unresolve_area" then
            self.resolved_areas[cmd.area_id] = nil
        elseif c == "key_change_ack" then
            if identity:ack(cmd.old_key) and cmd.new_key then
                -- the server now tracks the new key: held battle writes follow it
                for _, e in ipairs(self.battle_pending) do
                    if e.key == cmd.old_key then e.key = cmd.new_key end
                end
            end
        elseif c == "key_change_rejected" then
            identity:reject(cmd.old_key, game.read_party())
            log("key_change rejected: " .. tostring(cmd.reason) .. " " .. tostring(cmd.old_key))
            hud.show("IDENTITY CHANGE REFUSED: " .. tostring(cmd.reason or "collision"), 255, 64, 64, 600)
        elseif c == "config" then
            self.config = cmd
        elseif c == "game_over" then
            -- the server's game_over carries no sound of its own: the client supplies the cue
            if game.play_sound then game.play_sound(26) end -- SE_FAILURE
            hud.set_game_over()
            self.game_over = true
        elseif c == "rebuild_start" then
            hud.set_rebuilding(cmd.text)
        elseif c == "rebuild_done" then
            hud.clear_rebuilding()
        else
            log("unhandled command " .. tostring(c))
        end
    end

    -- ── hello / tick ───────────────────────────────────────────────────────────────
    function self:send_hello()
        local f = game.hello_fields() or {}
        if f.writes_enabled == nil then f.writes_enabled = self.writes_enabled end
        self.hello_sent = send("hello", f)
    end

    function self:send_tick()
        local f = game.tick_fields()
        if f then send("tick", f) end
    end

    -- PLAN §5.4: a stuck hold is diagnosable from the screen -- what, why, for how long.
    local function report_holds()
        local parts = {}
        local n, why, age, head = deferred:pending(self.frame)
        if n > 0 and why and age >= Session.PENDING_HUD_FRAMES then
            parts[#parts + 1] = string.format("%s x%d %ds (%s)", tostring(head), n, math.floor(age / 60), why)
        end
        for _, e in ipairs(self.battle_pending) do
            local held = self.frame - (e.since or self.frame)
            if held >= Session.PENDING_HUD_FRAMES then
                parts[#parts + 1] = string.format("%s %ds (%s)", e.cmd, math.floor(held / 60), tostring(e.why))
                break
            end
        end
        if #parts > 0 then
            hud.show("SLink held: " .. table.concat(parts, "; "), 255, 200, 80, Session.TICK_INTERVAL)
        end
    end

    -- ── per-frame driver ───────────────────────────────────────────────────────────
    function self:start()
        if game.start then self.signals = game.start() end
    end

    function self:frame_end()
        self.frame = game.frame()
        if game.pre_pump then game.pre_pump() end
        net.pump()
        local connected = net.connected()
        if not connected then
            self.hello_sent = false
            if game.on_disconnect then game.on_disconnect() end
        end
        -- pump, THEN hello: the reconnect hello is the first line of a new connection
        -- (tests/unit/test_connector_reconnect.py:5-8)
        if connected and not self.hello_sent and game.hello_ready() then self:send_hello() end
        connected = connected and self.hello_sent
        if self.frame % Session.VALIDATE_EVERY == 0 then self:validate() end
        local sigs = self.signals
        for _, sig in ipairs(sigs and sigs:drain() or {}) do
            local ok, err = pcall(game.on_signal, sig)
            if not ok then log("signal " .. tostring(sig.kind) .. ": " .. tostring(err)) end
        end
        if sigs and sigs.handler_error then
            log("hook handler error: " .. tostring(sigs.handler_error))
            sigs.handler_error = nil
        end
        if sigs and sigs.failure and not self.signal_failure_shown then
            self.signal_failure_shown = true
            log("ENGINE SIGNALS STOPPED: " .. tostring(sigs.failure))
            hud.show("SLINK: engine hooks stopped - restart Lua, send slink_lua.log", 255, 60, 60, 1800)
        end
        for _, fn in ipairs(game.frame_hooks or {}) do fn() end
        if identity:active() then
            local party = game.read_party()
            if party then identity:observe(party) end
        end
        if self.frame % Session.TICK_INTERVAL == 0 then
            if connected then self:send_tick() end
            report_holds()
        end
        if self.pending_safe and connected and not game.in_battle() then
            self.pending_safe = false
            send("safe", {})
        end
        while true do
            local line = net.receive()
            if not line then break end
            local ok, reply = pcall(json.decode, line)
            if ok and type(reply) == "table" and type(reply.commands) == "table" then
                for _, cmd in ipairs(reply.commands) do
                    local hok, herr = pcall(self.handle_command, self, cmd)
                    if not hok then log("command " .. tostring(cmd and cmd.cmd) .. ": " .. tostring(herr)) end
                end
            else
                log("unreadable reply line")
            end
        end
        if game.after_receive then
            local ok, err = pcall(game.after_receive)
            if not ok then log("after_receive: " .. tostring(err)) end
        end
        flush_battle_writes()
        self:run_deferred()
    end

    function self:run_deferred()
        return deferred:run(function()
            if not self.writes_enabled then
                return false, self.gate_revoked and "writes paused" or "writes not enabled yet"
            end
            if not net.connected() then return false, "not connected" end
            return game.checkpoint_ok()
        end, self.frame, self.game_over)
    end

    function self:stop()
        if self.signals then self.signals:close() end
    end

    return self
end

return Session
