-- lua/gen2/client.lua — the Gen 2 Soul Link client, as a state machine over injected parts.
--
-- P3b rules qualification only. lua/gen1/client.lua is the standard: this file mirrors its
-- structure (outbound, wire shapes, writes gate, inbound commands, signals -> events,
-- hello/tick, per-frame driver) and every place it differs carries a `Gen 2:` reason.
-- Contract: docs/protocol.md. Evidence comes from the parts: the candidate graph is MODEL; the
-- production graph (Entry.build, admitted Crystal) binds the U1/U2 PHYSICAL receipts.
--
-- Parts (all injected; lua/gen2/entry.lua build / build_candidate compose them):
--   reads    lua/gen2/reads.lua     WRAM/SRAM decoders
--   wire     lua/gen2/wire.lua      decoded record -> docs/protocol.md §4 shapes (refuses eggs)
--   signals  factory(authority) -> the lua/gen2/signals.lua binder (typed events + latches)
--   writes   lua/gen2/writes.lua    bench faint behind the shared write permit
--   boxes    lua/gen2/boxes.lua     B.executor: deposit/withdraw/memorialize (nil: box commands NACK)
--   safety   checkpoint, :check(kind) -> ok, why (lua/gen2_write_safety.lua: only a U2-receipted
--            write kind in the held checkpoint frame)
--   checkpoint_pc  production only: the checkpoint PC hooked for writes + hello readiness
--   net      lua/connector.lua      newline-JSON TCP (send/receive/pump/connected)
--   json/hud/io                     as Gen 1
--
-- Events come from the binder's latches only (capture, whiteout, PC ops, NPC trade,
-- evolution) or from a binder observation settled against one read (faint, battle start/end,
-- save, reset); nothing is inferred by polling. A binder refusal is logged once per reason. Writes happen only inside the armed permit at the
-- checkpoint. P4 native sound and SLINK trade are not here: those commands get the protocol's
-- "nothing happened" replies (handle_command) and request_sfx_local is the sound seam. The
-- native panel (P4.1f) is the optional p.panel (lua/gen2/panel.lua); nil means no panel.
local Client = { TICK_INTERVAL = 30, VALIDATE_EVERY = 60, MAX_INVALID = 5, MAX_PENDING_FRAMES = 600,
                 MAX_HELD = 64 }

-- Gen 2: the wild battle types whose failure dead-zones the map are exactly the ones the
-- binder links to the map's area (signals.lua final_event: NORMAL 0, FISH 4, TREE 8);
-- roamer/contest/scripted battles resolve their own namespace or nothing (O-17, O-18).
local AREA_BATTLE_TYPES = { [0] = true, [4] = true, [8] = true }
-- The protocol NACK of each box command (docs/protocol.md §5). The executor (p.boxes, lua/gen2/boxes.lua
-- B.executor) runs them at the checkpoint; a kind the U2 receipt never proved is refused there, with its name.
local BOX_NACK = { box_mon = "box_mon_failed", party_mon = "sync_retrieve_failed",
                   memorialize = "memorialize_failed" }
local BOX_OPEN = "Gen 2 box executor not composed"
-- The U2 write kind whose held checkpoint the hello snapshot and the bench faint wait for.
local PARTY_HP = "party_hp"

local function nick_label(key, nickname)
    if nickname and nickname ~= "" then return nickname end
    return key and key:sub(1, 8) or "?"
end

function Client.new(p)
    local HelloSession = assert(p.hello_session, "shared hello_session factory required")
    local ReplyDispatch = assert(p.reply_dispatch, "shared reply_dispatch factory required")
    local reads, wire, writes, safety, boxes = p.reads, p.wire, p.writes, p.safety, p.boxes
    local signals_factory = assert(p.signals, "Gen 2 signals factory required")
    local net, json, hud, io = p.net, p.json, p.hud, p.io
    local profile, sites, area_map = p.profile, p.sites, p.area_map
    local log = p.log or function(...) end
    local panel = p.panel -- P4.1f panel: lua/gen2/panel.lua, or nil (no panel)
    local c = profile.constants
    local arr = json.array -- tag lists so an empty one encodes as [] not {}

    local self = {
        player = p.player, rom_type = p.rom_type, rom_sha1 = p.rom_sha1,
        -- Gen 2: one pairing foundation for all three packs (O-16; gen2_gsc.py game_id)
        foundation = "gen2_gsc", artifact_kind = "clean",
        seq = 0, frame = 0, hello_sent = false,
        writes_enabled = false, invalid_streak = 0, gate_revoked = false,
        box_cache = {}, resolved_areas = {}, config = {}, deferred = {},
        battle = nil, has_pokeballs = false, nuzlocke_announced = false, signals = nil,
        -- Gen 2: the binder needs an operation authority (signals.lua header); the client
        -- owns it as a reset epoch, bumped at every reset/reload boundary.
        epoch = 0,
        -- Gen 2: the binder's faint names the record (same-frame key); the latch holds it
        -- until that record reads HP 0 (UpdateFaintedPlayerMon runs before the copy-back)
        faint_latches = {}, refusals_logged = {},
        pending_rescan = false, key_alias = nil, retired_alias = {},
        -- Gen 2: messages observed before this connection's hello (see send)
        held = {}, held_full = false, last_frame = nil,
        -- Gen 2 (gen2-box-durability): backing withdraws whose box copy waits for a native SAVE
        -- ({key, armed}); a pending SaveBox after an active-box edit (OMP BOX F2, recorded, not blocking)
        settle = {}, box_save_pending = false,
    }

    -- ── outbound ─────────────────────────────────────────────────────────────────────
    local function send(event, fields)
        if not net.connected() then
            log("[SLink-gen2] drop " .. event .. ": not connected")
            return false
        end
        -- Gen 2: nothing but the hello reaches the server before a hello is queued for this
        -- connection/identity (Gen 1 gates tick/safe on the same readiness). The candidate
        -- checkpoint refuses in the overworld, so that can be minutes: earlier messages wait
        -- in order and follow the hello (frame_end); a reset/reload boundary, an identity change
        -- and a savestate load drop them (drop_held; the load through abandon_timeline).
        if event ~= "hello" and not (self.hello_session and self.hello_session:status().ready) then
            if #self.held >= Client.MAX_HELD then
                log("[SLink-gen2] drop " .. event .. ": pre-hello queue full")
                -- a lost capture/faint/deposit is a transition the hello snapshot cannot rebuild:
                -- the player sees it once per filled queue, not only the log
                if not self.held_full then
                    self.held_full = true
                    hud.show("SLINK EVENTS LOST - SEE LOG", 255, 64, 64, 600)
                end
            else
                self.held[#self.held + 1] = { event = event, fields = fields }
            end
            return false
        end
        self.seq = self.seq + 1
        local msg = fields or {}
        msg.event, msg.player, msg.seq = event, self.player, self.seq
        return net.send(json.encode(msg)) ~= false
    end
    self.send = send

    -- Gen 2: held messages belong to the save and the timeline that produced them.
    local function drop_held(why)
        if #self.held > 0 then
            log("[SLink-gen2] " .. #self.held .. " pre-hello message(s) dropped: " .. why)
        end
        self.held, self.held_full = {}, false
    end

    -- Gen 2: a few point scalars (wBattleScriptFlags) exist only as the engine-site pack's
    -- point symbols, not profile.ram; both carry bank + address.
    local points = {}
    for _, site in pairs(sites) do
        for name, pt in pairs(site.point_symbols or {}) do points[name] = pt end
    end
    local function wram_bytes(name, n)
        local pt = points[name] or { addr = profile.ram[name], bank = profile.ram_bank[name] }
        if not pt.addr or not pt.bank then return nil, "no WRAM coordinates for " .. name end
        if io.bank_valid(pt.bank, pt.addr, n) ~= true then return nil, name .. ": WRAM bank unavailable" end
        local bytes = io.read_range(pt.addr, n, "System Bus")
        if type(bytes) ~= "table" or #bytes ~= n then return nil, name .. ": unreadable" end
        return bytes
    end
    local function wram_byte(name)
        local b, why = wram_bytes(name, 1)
        return b and b[1], why
    end

    -- ── reads → wire shapes ──────────────────────────────────────────────────────────
    -- Gen 2: the key is wire.mon_key (DDDD:OOOO:SS over the decoded record), the same
    -- function every snapshot entry uses; test_gen2_client pins it to gen2_codec.key.
    local mon_key = wire.mon_key

    local function current_party() return reads.read_party() end

    -- Gen 2: eggs stay off the wire until they hatch (O-15). Each entry keeps its own
    -- `slot`, so omitting an egg shifts no index. Any other wire refusal fails the whole
    -- snapshot closed: a partial party would read as a release to the server.
    local function party_entries(party, active, stages)
        local out = arr({})
        for _, m in ipairs(party.mons) do
            if not m.is_egg then
                local e, why = wire.party_entry(m, active, stages)
                if not e then return nil, "slot " .. tostring(m.slot) .. ": " .. tostring(why) end
                out[#out + 1] = e
            end
        end
        return out
    end

    local function snapshot_party()
        local party, why = current_party()
        if not party then return nil, why end
        local battle = reads.read_battle()
        if not battle then return nil, "battle state unreadable" end
        local active = battle.mode ~= 0 and battle.active_slot or nil
        local stages = active and reads.read_stat_stages("player") or nil
        local out
        out, why = party_entries(party, active, stages and stages.wire or nil)
        if not out then
            if self.snapshot_refusal ~= why then
                self.snapshot_refusal = why
                log("[SLink-gen2] party snapshot refused: " .. tostring(why))
            end
            return nil, why
        end
        self.snapshot_refusal = nil
        return out, battle
    end

    local function enemy_party(battle)
        if battle.mode == 0 then return arr({}) end
        local foe = reads.read_battle_mon("enemy")
        local stages = reads.read_stat_stages("enemy")
        local e = foe and wire.foe_entry(foe, stages and stages.wire or nil)
        return arr({ e })
    end

    -- Gen 2: the Ball pocket holds only balls (reads.read_pocket "balls"); Gen 1 needed an
    -- item-id set because its balls share the one bag list.
    local function ball_count()
        local pocket = reads.read_pocket("balls")
        local n = 0
        if pocket then for _, it in ipairs(pocket.entries) do n = n + it.quantity end end
        return n
    end

    -- Gen 2: maps are (group, number); area_map is keyed group*256+number.
    local function area_of()
        local map = reads.read_map()
        if not map then return "", "" end
        local a = area_map[tostring(map.group * 256 + map.number)]
        if a then return a.area_id, a.name end
        return "", "map_" .. map.group .. "_" .. map.number
    end

    local function announce_nuzlocke_start()
        if self.nuzlocke_announced then return end
        self.nuzlocke_announced = true
        hud.nuzlocke_start("Nuzlocke Start!")
        self:request_sfx_local(95)
    end

    local function pc_boxes_wire()
        local out = arr({})
        for _, e in ipairs(self.box_cache) do out[#out + 1] = e end
        return out
    end

    -- Gen 2: fourteen boxes, the current one authoritative in the active sBox shadow and the
    -- rest in their backing SRAM boxes (reads.lua read_box); eggs omitted as in the party.
    function self:rescan_boxes()
        local cur = reads.read_current_box_num()
        if cur == nil then return self.box_cache end
        local cache = {}
        for box = 0, c.NUM_BOXES - 1 do
            local mons = box == cur and reads.read_active_box() or reads.read_storage_box(box)
            for _, m in ipairs(mons and mons.mons or {}) do
                local e = (not m.is_egg) and wire.box_entry(m, box) or nil
                if e then cache[#cache + 1] = e end
            end
        end
        self.box_cache = cache
        return cache
    end

    -- ── the writes gate (R-4, W-6) ───────────────────────────────────────────────────
    local function game_is_live()
        local party, why = current_party()
        if not party then return false, "party unreadable: " .. tostring(why) end
        local player = reads.read_player()
        if not player then return false, "player unreadable" end
        if player.ot_id == 0 and party.count == 0 then return false, "pre-game (title/new game)" end
        return true
    end

    local function hello_identity()
        local player = reads.read_player()
        local id = player and player.ot_id
        if type(id) ~= "number" or id % 1 ~= 0 or id < 0 or id > 65535 then
            return nil, "player identity unavailable"
        end
        -- Gen 2: no save-version stamp in the key (Gen 1's is pureRGB's wGameInternalVersion)
        return table.concat({ tostring(self.player), self.foundation, self.artifact_kind,
                              tostring(self.rom_sha1), tostring(id) }, "|")
    end

    -- One reset path: the hello session, the binder's latches and every client latch go
    -- together, so nothing observed before a reset/reload can settle after it.
    function self:boundary(kind, why)
        self.epoch = self.epoch + 1
        if self.signals then self.signals:boundary(kind) end
        self.faint_latches, self.battle, self.pending_rescan = {}, nil, false
        self.key_alias, self.retired_alias = nil, {}
        drop_held("the " .. kind .. " boundary")
        self.hello_session:invalidate(why or kind)
    end

    -- A savestate load or rewind abandons the timeline (R4 S2). Unlike boundary(), which keeps
    -- what the engine finalized before a natural in-engine reset/reload, nothing observed on the
    -- timeline the player left may be published on the one they resumed: queued binder batches,
    -- pending acquisition/faint latches, the battle context and held messages all go, and the
    -- epoch moves so a settled observation stamped before the load is stale.
    function self:abandon_timeline(why)
        self.epoch = self.epoch + 1
        if self.signals then self.signals:abandon(why) end
        self.faint_latches, self.deferred = {}, {}
        self.battle, self.pending_safe, self.pending_rescan = nil, false, true
        -- A delayed retirement may be lost after rewinding a key change; retaining its alias could faint another record.
        self.key_alias, self.retired_alias = nil, {}
        drop_held(why)
        -- Hello readiness names the still-open TCP connection and player OT, not a frame epoch;
        -- a changed OT invalidates it in hello_session:step. The next tick reports the resumed
        -- party and the pending rescan attempts to refresh its boxes before that tick.
    end

    function self:validate()
        local ok, why = game_is_live()
        if ok then
            self.invalid_streak = 0
            if not self.writes_enabled and not self.gate_revoked then
                self.writes_enabled = true
                log("[SLink-gen2] writes ENABLED")
            end
            if self.gate_revoked then
                self.gate_revoked, self.writes_enabled = false, true
                log("[SLink-gen2] writes re-enabled after a live validation")
            end
        else
            self.invalid_streak = self.invalid_streak + 1
            local player = reads.read_player()
            if player and player.ot_id == 0 then self:boundary("reset", "save_reset") end
            if self.invalid_streak >= Client.MAX_INVALID and self.writes_enabled then
                self.writes_enabled, self.gate_revoked = false, true
                log("[SLink-gen2] writes PAUSED: " .. tostring(why))
            end
        end
        return ok, why
    end

    -- ── inbound commands ─────────────────────────────────────────────────────────────
    local function ack_cancel(cmd)
        if cmd.cmd == "show_choices" then send("menu_result", { token = cmd.token, choice = 127 })
        elseif cmd.cmd == "show_menu" then send("menu_result", { token = cmd.token, choice = 0 })
        elseif cmd.cmd == "choose_mon" then send("mon_chosen", { token = cmd.token, slot = 7 }) end
    end

    -- Returns slot, mon, party, why; `why` = "ambiguous key" when two slots answer.
    -- ponytail: Gen 1's frozen record-evidence latch is not ported: both Gen 2 key_change
    -- sources (NPC trade, evolution) are refused by the binder when the old or new full key
    -- names a second record, and two answering slots refuse here. Ceiling: a record leaving
    -- and an identical one arriving before the ack (Gen 1 cx-fc0d91b7); port it if that bites.
    local function find_party_slot(key)
        local party = current_party()
        if not party then return nil end
        local target = self.retired_alias[key] or key
        local slot, mon
        for _, m in ipairs(party.mons) do
            if not m.is_egg and mon_key(m) == target then
                if slot then return nil, nil, party, "ambiguous key" end
                slot, mon = m.slot, m
            end
        end
        return slot, mon, party
    end

    local function hud_color(cmd)
        if type(cmd.color) == "table" then return cmd.color[1], cmd.color[2], cmd.color[3], cmd.duration end
        return cmd.r, cmd.g, cmd.b, cmd.frames
    end

    -- Gen 2: the native-SFX seam (P4). No Gen 2 cartridge has a sound mailbox yet, so every
    -- request is "unavailable", logged once, exactly Gen 1's no-panel path.
    function self:request_sfx_local(gen3_id)
        if not self.sfx_unavailable_logged then
            self.sfx_unavailable_logged = true
            log("[SLink-gen2] play_sound: no native sound path on Gen 2 yet (P4)")
        end
    end

    function self:handle_command(cmd)
        local c_ = cmd.cmd
        if c_ == "noop" then return end
        if c_ == "force_faint" or c_ == "force_explode" then
            -- Gen 2: supports_explode_mode() is False; a stray explode is the bench faint.
            local slot, mon, party, why = find_party_slot(cmd.key)
            if why then log("[SLink-gen2] " .. c_ .. ": " .. why .. " " .. tostring(cmd.key)) return end
            local entry = { cmd = c_, key = cmd.key, nickname = cmd.nickname }
            if not party then self.deferred[#self.deferred + 1] = entry return end
            if not slot then log("[SLink-gen2] " .. c_ .. ": key not in party " .. tostring(cmd.key)) return end
            local battle = reads.read_battle()
            if battle and battle.mode ~= 0 and battle.active_slot == slot then
                -- Gen 2: no qualified in-battle write site (writes.lua header). Ask the writer
                -- anyway so its refusal is what the player sees; the command then waits for
                -- the checkpoint, where the mon is benched (protocol §5: deferred to battle end).
                local ok, err = pcall(function() return writes:faint_active_battler() end)
                if not ok then
                    log("[SLink-gen2] " .. c_ .. " held for the checkpoint: " .. tostring(err) .. " " .. cmd.key)
                    hud.show("KO held: " .. nick_label(cmd.key, mon and mon.nickname) .. " is battling", 255, 160, 64, 300)
                end
            end
            self.deferred[#self.deferred + 1] = entry
            return
        end
        if BOX_NACK[c_] then
            if not boxes then
                log("[SLink-gen2] " .. c_ .. " refused: " .. BOX_OPEN .. " " .. tostring(cmd.key))
                send(BOX_NACK[c_], { key = cmd.key, reason = BOX_OPEN })
                return
            end
            -- Gen 1 parity: queued in arrival order with the faints; run one per checkpoint hold
            self.deferred[#self.deferred + 1] = { cmd = c_, key = cmd.key, nickname = cmd.nickname }
            return
        end
        if c_ == "replace_rival_team" then
            -- Gen 2: gen2_gsc.rival_trainer_ids() is empty, so this is never queued; it must
            -- still be NACKed (protocol §5)
            send("rival_team_replaced", { trainer_id = cmd.trainer_id, species_ids = arr({}), error = "unsupported" })
        elseif c_ == "msgbox" or c_ == "gui_prompt" then
            local r, g, b, f = hud_color(cmd)
            hud.prompt(cmd.text, r, g, b, f)
        elseif c_ == "hud_show" then
            local r, g, b, f = hud_color(cmd)
            hud.show(cmd.text, r, g, b, f)
        elseif c_ == "play_sound" then
            self:request_sfx_local(cmd.sound)
        elseif c_ == "resolved_areas" then
            self.resolved_areas = {}
            for _, a in ipairs(cmd.areas or {}) do self.resolved_areas[a] = true end
            self.seeded = true
        elseif c_ == "unresolve_area" then
            self.resolved_areas[cmd.area_id] = nil
        elseif c_ == "key_change_ack" then
            local a = self.key_alias
            if a and a.old_key == cmd.old_key then self.key_alias = nil end
        elseif c_ == "key_change_rejected" then
            -- the cartridge cannot roll back; the retirement the server queues under the old
            -- key must find the mon by the key it physically holds now
            local a = self.key_alias
            if a and a.old_key == cmd.old_key then
                self.retired_alias[a.old_key] = a.new_key
                self.key_alias = nil
            end
            log("[SLink-gen2] key_change rejected: " .. tostring(cmd.reason) .. " " .. tostring(cmd.old_key))
            hud.show("IDENTITY CHANGE REFUSED: " .. tostring(cmd.reason or "collision"), 255, 64, 64, 600)
        elseif c_ == "config" then
            self.config = cmd
        elseif c_ == "game_over" then
            self:request_sfx_local(26)
            hud.set_game_over()
            self.game_over = true
        elseif c_ == "rebuild_start" then
            hud.set_rebuilding(cmd.text)
        elseif c_ == "rebuild_done" then
            hud.clear_rebuilding()
        elseif c_ == "show_choices" or c_ == "show_menu" or c_ == "choose_mon" then
            ack_cancel(cmd) -- Gen 2: no native picker until P4
        elseif c_ == "apply_trade" then
            -- Gen 2: no SLINK trade path until P4: "nothing changed" with the pre-trade key (§5)
            local slot, mon = find_party_slot(cmd.old_key)
            send("trade_done", { token = cmd.token, slot = slot or cmd.slot, new_key = cmd.old_key,
                                 new_species = mon and mon.species_id or 0 })
        elseif c_ == "link_panel" then
            -- P4.1f panel: held until the cartridge asks for it (panel.lua); no panel = nothing happened
            if panel then
                local pok, perr = panel:hold(cmd.rows)
                if not pok then log("[SLink-gen2] link_panel: " .. tostring(perr)) end
            end
        elseif c_ == "trade_mask" or c_ == "trade_offer_ack"
               or c_ == "ghost_pos" or c_ == "pending_keys" then
            -- Gen 2: P4 trade/panel/presence (pending_keys feeds Gen 1's APEX set only)
        else
            log("[SLink-gen2] unknown command " .. tostring(c_))
        end
    end

    -- Deferred queue: one command per frame, only at the verified checkpoint, inside the permit.
    function self:run_deferred()
        local armed
        for i, s in ipairs(self.settle) do if s.armed then armed = armed or i end end
        if (#self.deferred == 0 and not armed) or not self.writes_enabled or not net.connected() then return end
        local safe = safety.check(PARTY_HP)
        if not safe then return end
        if armed then
            -- one op per hold: the saved party now holds the mon, so its backing copy goes (full-record
            -- match); a reset before the save left it in the box only, and settle is a no-op
            local s = table.remove(self.settle, armed)
            local done, why = boxes.settle(s.key)
            log("[SLink-gen2] box copy settle " .. s.key .. ": " .. (done and "done" or tostring(why)))
            return
        end
        local cmd = table.remove(self.deferred, 1)
        if BOX_NACK[cmd.cmd] then return self:run_box(cmd) end
        local slot, mon, _, why = find_party_slot(cmd.key)
        if not slot then
            -- the mon left the party before the checkpoint (PC deposit) or its key is ambiguous
            log("[SLink-gen2] " .. cmd.cmd .. " dropped at the checkpoint: " .. (why or "key not in party")
                .. " " .. tostring(cmd.key))
            return
        end
        local battle = reads.read_battle()
        -- Gen 2: faint_party_slot takes the battle snapshot and refuses the active slot and
        -- any linked/special battle itself; the client never pre-empts that decision.
        local snapshot = battle and { mode = battle.mode, battle_type = battle.battle_type,
                                      active_slot = battle.active_slot, link_mode = wram_byte("wLinkMode") } or nil
        local ok, err = pcall(function()
            writes:arm("overworld")
            writes:faint_party_slot(slot, snapshot)
            writes:disarm()
        end)
        writes:disarm()
        if ok then
            hud.show("!! " .. nick_label(cmd.key, cmd.nickname or (mon and mon.nickname)) .. " KO'd", 255, 80, 80, 360)
        else
            -- no force_faint NACK exists (protocol §5): the refusal is logged and shown, never
            -- reported as a KO
            log("[SLink-gen2] " .. cmd.cmd .. " refused by the write gate: " .. tostring(err) .. " " .. cmd.key)
            hud.show("X KO refused: " .. nick_label(cmd.key, mon and mon.nickname), 255, 80, 80, 300)
        end
    end

    -- One box command inside the held checkpoint (lua/gen1/client.lua run_deferred is the reference):
    -- stats_cache before a deposit; replies keep cmd.key (what the server tracks) while the executor
    -- looks the mon up by the key the cartridge holds (a rejected key change's alias). Tail requeues
    -- (A5): a rebuild's party_mon refused "party full" waits behind the memorials that free a slot,
    -- bounded by the queue length at its first refusal; a memorial of the last party mon waits for a
    -- party_mon, or is dropped after game_over.
    function self:run_box(cmd)
        local phys = self.retired_alias[cmd.key] or cmd.key
        local _, mon = find_party_slot(cmd.key)
        local name = nick_label(cmd.key, cmd.nickname or (mon and mon.nickname))
        if cmd.cmd == "box_mon" then
            if mon then send("stats_cache", { key = cmd.key, stats = { level = mon.level, maxHP = mon.max_hp } }) end
            local done, why = boxes.deposit(phys)
            if done then
                -- F2: the active sBox half persists only at SaveBox (a native save or box change); a reset
                -- before it reverts the deposit, which the reconnect reconcile heals. Recorded, not blocking.
                self.box_save_pending = true
                self.pending_rescan = true
                hud.show("↓ " .. name .. " boxed", 100, 180, 255, 200)
            else
                log("[SLink-gen2] box_mon refused: " .. tostring(why) .. " " .. cmd.key)
                send("box_mon_failed", { key = cmd.key, reason = tostring(why) })
                hud.show("X Box fail: " .. name, 255, 80, 80, 240)
            end
        elseif cmd.cmd == "party_mon" then
            local done, why = boxes.withdraw(phys, { defer_backing = true })
            if done and why then
                -- F1: the backing copy stays until a native SAVE persists the party (never a loss)
                self.settle[#self.settle + 1] = { key = phys, armed = false }
                log("[SLink-gen2] party_mon " .. cmd.key .. ": " .. why)
            elseif done then
                self.box_save_pending = true
            end
            if done then
                self.pending_rescan = true
                send("sync_retrieve_done", { key = cmd.key })
                hud.show("↑ " .. name .. " unboxed", 100, 255, 160, 200)
            elseif why == "party full" and (cmd.full_retries or 0) < (cmd.full_budget or (#self.deferred + 1)) then
                cmd.full_budget = cmd.full_budget or (#self.deferred + 1)
                cmd.full_retries = (cmd.full_retries or 0) + 1
                self.deferred[#self.deferred + 1] = cmd
                log("[SLink-gen2] party_mon " .. cmd.key .. ": party full, retry " .. cmd.full_retries .. "/"
                    .. cmd.full_budget .. " after the queue")
            else
                log("[SLink-gen2] party_mon refused: " .. tostring(why) .. " " .. cmd.key)
                send("sync_retrieve_failed", { key = cmd.key, reason = tostring(why) })
            end
        else
            local done, why = boxes.memorialize(phys)
            if done then
                self.pending_rescan, self.retired_alias[cmd.key] = true, nil
                send("memorialize_done", { key = cmd.key, box = boxes.memorial_box })
                hud.show("† " .. name .. " buried", 255, 140, 40, 300)
            elseif why == "last party mon" and self.game_over then
                log("[SLink-gen2] memorialize dropped: last mon after game over " .. cmd.key)
            elseif why == "last party mon" then
                self.deferred[#self.deferred + 1] = cmd
            else
                log("[SLink-gen2] memorialize refused: " .. tostring(why) .. " " .. cmd.key)
                send("memorialize_failed", { key = cmd.key, reason = tostring(why) })
                hud.show("X Mem fail: " .. name, 255, 80, 80, 300)
            end
        end
    end

    -- ── signals → events ─────────────────────────────────────────────────────────────
    local function announce_whiteout()
        self:request_sfx_local(22)
        send("whiteout", {})
    end

    -- Gen 2: a capture arrives complete from the binder (acquisition latch + final name),
    -- so there is no pending acquisition to settle as in Gen 1's settle_pending_change.
    local function publish_capture(ev)
        local m = ev.mon
        local key = not m.is_egg and mon_key(m) or nil
        if key == nil or key ~= m.key then
            log("[SLink-gen2] capture refused: " .. (m.is_egg and "unhatched egg"
                or "key disagreement " .. tostring(key) .. " vs " .. tostring(m.key)))
            if self.battle then self.battle.capture_refused = true end
            return
        end
        -- Gen 2: the hatch is the gift (O-15, gift_daycare); roamer (legend_<species>, O-17)
        -- and contest (national_park_contest, O-18) ids come from the binder unchanged
        local gift = ev.acquisition == "egg_hatch"
        local in_box = ev.destination == "box"
        send("capture", { key = key, area_id = ev.area_id, species_id = m.species_id, level = m.level,
                          hp = m.hp, maxHP = m.max_hp, nickname = m.nickname, held_item_id = m.held_item,
                          gift = gift, in_box = in_box, stats = { level = m.level, maxHP = m.max_hp } })
        if self.battle and not gift then self.battle.captured = true end
        self.resolved_areas[ev.area_id] = true
        if in_box then self.pending_rescan = true end
    end

    function self:on_observation(ev)
        local k = ev.site_id
        if k == "wild_ready" then
            local area_id, name = area_of()
            local foe = reads.read_battle_mon("enemy")
            local battle = reads.read_battle()
            local scripted = wram_byte("wBattleScriptFlags")
            self.battle = { wild = true, area_id = area_id, species = foe and foe.species_id,
                            level = foe and foe.level, captured = false,
                            -- Gen 2 (N3-3): the binder's count of acquisitions it refused after
                            -- the engine inserted a mon, stamped in engine order on each observation
                            refused_base = ev.refused_acquisitions,
                            -- scripted/static and special types resolve nothing (as the binder)
                            resolves = battle ~= nil and AREA_BATTLE_TYPES[battle.battle_type] == true
                                       and scripted ~= nil and math.floor(scripted / 128) % 2 == 0 }
            if self.battle.resolves and self.has_pokeballs and self.seeded and area_id ~= ""
               and not self.resolved_areas[area_id] then
                hud.show("** NEW ENCOUNTER **\n" .. name, 255, 220, 60, 360)  -- area on its own line, as Gen 1
                self:request_sfx_local(25)
            end
        elseif k == "trainer_ready" then
            -- Gen 2: no trainer_battle_start: the (class, id) pair has no agreed single-int
            -- packing (gen2_gsc.trainer_info) and rival_trainer_ids() is empty
            self.battle = { wild = false }
        elseif k == "battle_end" then
            local b = self.battle
            if b and b.wild and b.resolves and not b.captured and b.area_id ~= ""
               and not self.resolved_areas[b.area_id] then
                if b.capture_refused or ev.refused_acquisitions ~= b.refused_base then
                    log("[SLink-gen2] a capture was refused in this battle: no_catch withheld, "
                        .. b.area_id .. " stays open")
                    hud.show("CATCH NOT REPORTED - SEE LOG", 255, 160, 64, 600)
                elseif not self.has_pokeballs then
                    log("[SLink-gen2] no Poke Balls yet: no_catch withheld, " .. b.area_id .. " stays open")
                else
                    send("no_catch", { area_id = b.area_id, species_id = b.species, level = b.level })
                    self.resolved_areas[b.area_id] = true
                end
            end
            self.battle = nil
            self.pending_safe = true
        elseif k == "bag_ball_received" then
            local had = self.has_pokeballs
            self.has_pokeballs = true
            if not had then announce_nuzlocke_start() end
        elseif k == "save_completed" then
            if io.saveram then pcall(io.saveram) end
            -- the native save persisted the party: deferred backing removals may run (gen2-box-durability)
            for _, s in ipairs(self.settle) do s.armed = true end
            if self.box_save_pending then log("[SLink-gen2] box edits persisted by the native save") end
            self.box_save_pending = false
        elseif k == "soft_reset" or k == "new_game" then
            self:boundary("reset", "save_reset")
        elseif k == "continue_confirmed" then
            self:boundary("reload", "save_reload")
        end
    end

    function self:on_event(ev)
        local k = ev.kind
        local m = ev.mon
        if m and m.is_egg and k ~= "capture" then
            -- PC ops may move an egg (allow_egg); an egg never goes on the wire (O-15)
            self.pending_rescan = true
            return
        end
        if k == "capture" then publish_capture(ev)
        elseif k == "whiteout" then announce_whiteout()
        elseif k == "faint" then
            self.faint_latches[#self.faint_latches + 1] = { key = m.key, cause = ev.cause, frame = self.frame,
                                                            area_id = (area_of()) }
        elseif k == "party_to_box" then
            send("party_to_box", { key = mon_key(m), stats = { level = m.level } })
            self.pending_rescan = true
        elseif k == "box_to_party" then
            send("box_to_party", { key = mon_key(m), area_id = (area_of()) })
            self.pending_rescan = true
        elseif k == "pc_release" then
            if ev.collection == "party" then send("party_to_box", { key = mon_key(m) }) -- release
            else log(string.format("[SLink-gen2] RELEASE_SEEN key=%s box=%s", mon_key(m), tostring(ev.box_index))) end
            self.pending_rescan = true
        elseif k == "key_change" then
            local new_key = mon_key(m)
            self.key_alias = { old_key = ev.old_key, new_key = new_key }
            send("key_change", { old_key = ev.old_key, new_key = new_key, new_species = m.species_id,
                                 reason = ev.reason, new_nickname = m.nickname })
            self.pending_rescan = true
        elseif k == "box_change" then
            self.pending_rescan = true
        elseif k == "observation" then
            self:on_observation(ev)
        end
    end

    -- A faint latch settles once the one record carrying its key reads HP 0 (the copy-back or
    -- the poison store has landed); a latch older than MAX_PENDING_FRAMES is dropped, logged.
    function self:settle_faints()
        if #self.faint_latches == 0 then return end
        local keep = {}
        for _, f in ipairs(self.faint_latches) do
            local _, mon = find_party_slot(f.key)
            if mon and mon.hp == 0 then
                send("faint", { key = f.key, area_id = f.area_id })
            elseif self.frame - f.frame > Client.MAX_PENDING_FRAMES then
                log("[SLink-gen2] " .. tostring(f.cause) .. " faint latch expired unsettled " .. tostring(f.key))
            else
                keep[#keep + 1] = f
            end
        end
        self.faint_latches = keep
    end

    -- ── hello / tick ─────────────────────────────────────────────────────────────────
    function self:send_hello(expected_identity)
        if expected_identity == nil then
            local sent, why = self.hello_session:send_now(io.framecount())
            if sent then self.hello_sent = true end
            return sent, why
        end
        if hello_identity() ~= expected_identity then return false, "hello identity changed or unavailable" end
        local party, battle = snapshot_party()
        if not party then return false, "hello party snapshot unavailable" end
        local area_id, loc = area_of()
        local had_balls = self.has_pokeballs
        self.has_pokeballs = self.has_pokeballs or ball_count() > 0
        if not had_balls and self.has_pokeballs then
            self.nuzlocke_announced = true
            log("[SLink-gen2] nuzlocke ACTIVE (pokeballs already in bag at startup)")
        end
        self:rescan_boxes()
        local player = reads.read_player()
        local badges = reads.read_badges()
        local payload = {
            rom_type = self.rom_type, foundation = self.foundation, artifact_kind = self.artifact_kind,
            party = party, ot_id = player.ot_id, trainer_name = player.player_name,
            has_pokeballs = self.has_pokeballs, ball_count = ball_count(),
            -- Gen 2: two badge bytes; Kanto rides the protocol's second-region field
            badges = badges and badges.johto, kanto_badges = badges and badges.kanto,
            area_id = area_id, loc_name = loc, pc_boxes = pc_boxes_wire(),
            writes_enabled = self.writes_enabled, rom_sha1 = self.rom_sha1,
            in_battle = battle.mode ~= 0,
            -- Gen 2: no rom_content (gen2_gsc.rom_content_fingerprint refuses: not qualified)
            -- P4.1f panel: per CARTRIDGE, only a live SLink build with CAP_PANEL has it. Native
            -- sound stays off until P4.2b binds the SE table and request_sfx_local posts to it.
            panel = panel and panel:present() or false, panel_abi = panel and panel:abi() or 0,
            sfx = false,
        }
        if hello_identity() ~= expected_identity then return false, "hello identity changed during snapshot" end
        return send("hello", payload)
    end

    self.hello_session = HelloSession.new({
        connected = function() return net.connected() end,
        identity = hello_identity,
        ready = function(identity)
            local live, why = game_is_live()
            if not live then return false, why end
            local battle = reads.read_battle()
            if not battle then return false, "battle state unavailable" end
            -- PLAN §5.4: the first hello waits for the OWPlayerInput checkpoint or a running battle
            if battle.mode == 0 and not (self.checkpoint_held or safety.check(PARTY_HP)) then
                return false, "waiting for Gen 2 checkpoint or battle"
            end
            return hello_identity() == identity, "identity changed while checking readiness"
        end,
        send = function(identity) return self:send_hello(identity) end,
        retry_delay = function() return 1 end, -- Gen 1's next-frame retry policy
        clock_rewind = "keep", callback_error = "raise", -- Gen 1 parity
        on_invalidate = function(reason)
            self.hello_sent = false
            -- Gen 2: another save's identity; what was held belongs to the previous one. A transient
            -- identity_unavailable keeps the queue (the same identity returning is not a change).
            if reason == "identity_changed" then
                self.key_alias, self.retired_alias = nil, {}
                drop_held("identity change")
            end
        end,
        on_error = function(stage, why) log("[SLink-gen2] hello " .. stage .. ": " .. tostring(why)) end,
    })

    self.replies = ReplyDispatch.new({
        budget = math.huge, -- Gen 1 parity: drain every queued line each frame
        receive = function() return net.receive() end,
        decode = function(line) return json.decode(line) end,
        validate = function(reply)
            if type(reply) == "table" and type(reply.commands) == "table" then return reply.commands end
            return nil, "unreadable reply line"
        end,
        handle = function(cmd) return self:handle_command(cmd) end,
        on_error = function(stage, why, subject)
            if stage == "handle" then
                log("[SLink-gen2] command " .. tostring(type(subject) == "table" and subject.cmd or nil) .. ": " .. why)
            else
                log("[SLink-gen2] unreadable reply line")
            end
        end,
    })

    function self:send_tick(event)
        local party, battle = snapshot_party()
        if not party then return end
        local area_id, loc = area_of()
        local in_battle = battle.mode ~= 0
        -- Gen 2: no area-entry NEW ENCOUNTER banner: it needs rom_content's wild map set,
        -- which Gen 2 does not send (see send_hello); the battle-start banner stays
        if self.last_area ~= nil and self.last_area ~= area_id then
            send("area_enter", { area_id = area_id, loc_name = loc })
        end
        self.last_area = area_id
        local had_balls = self.has_pokeballs
        self.has_pokeballs = self.has_pokeballs or ball_count() > 0
        if not had_balls and self.has_pokeballs then announce_nuzlocke_start() end
        local player = reads.read_player()
        local badges = reads.read_badges()
        send(event or "tick", {
            party = party, has_pokeballs = self.has_pokeballs, ball_count = ball_count(),
            area_id = area_id, loc_name = loc, in_battle = in_battle,
            -- Gen 2: no trainer_id (see trainer_ready)
            is_trainer_battle = battle.mode == c.TRAINER_BATTLE,
            enemy_party = enemy_party(battle),
            badges = badges and badges.johto, kanto_badges = badges and badges.kanto,
            trainer_name = player and player.player_name, pc_boxes = pc_boxes_wire(),
        })
    end

    -- ── per-frame driver ─────────────────────────────────────────────────────────────
    -- Gen 2: the binder is built with the client's epoch authority and has no synchronous
    -- in-hook handlers (no qualified in-battle write site): every signal is consumed here.
    local authority = {
        kind = "MODEL_PROBE", allow_model_registration = true,
        capture = function() return { generation = self.epoch, operation = "epoch-" .. self.epoch } end,
        valid = function(stamp) return type(stamp) == "table" and stamp.generation == self.epoch end,
    }

    function self:start()
        if self.signals then
            assert(self.signals:close(), "previous engine signals could not be released")
            self.signals = nil
        end
        local binder, why = signals_factory(authority)
        if not binder then error("Gen 2 engine signals refused: " .. tostring(why), 0) end
        self.signals = binder
        self.signal_failure_logged = nil
        if p.checkpoint_pc and not self.checkpoint_hook then
            self.checkpoint_hook = io.on_bus_exec(function()
                local ok, err = pcall(self.at_checkpoint, self)
                if not ok then log("[SLink-gen2] checkpoint hold: " .. tostring(err)) end
            end, p.checkpoint_pc,
                                                  "SLink-gen2-checkpoint", "System Bus")
        end
    end

    -- Production: the CPU sits at the checkpoint PC (OWPlayerInput, before `call CheckAPressOW`),
    -- the only place check(kind) can accept. An accepted hold arms this frame's hello readiness
    -- and runs one deferred write inside the hold, exactly where the U2 gate wrote.
    function self:at_checkpoint()
        if not safety.check(PARTY_HP) then return end
        self.checkpoint_held = true
        self:run_deferred()
    end

    function self:frame_end()
        local now = io.framecount()
        -- Gen 2: onframeend runs once per emulated frame (lua/gen2/run.lua), so any other step of
        -- the frame counter is a savestate load or rewind: everything queued describes another timeline.
        if self.last_frame ~= nil and now ~= self.last_frame + 1 then self:abandon_timeline("savestate load") end
        self.last_frame, self.frame = now, now
        net.pump()
        -- Gen 2 (gen2-hello-flap): frame end can land mid-routine with WRAMX switched away (battle
        -- animations select SVBK = BANK(wBGPals1) = 5: C engine/battle_anims/anim_commands.asm:1413,
        -- bg_effects.asm:2562,2589). Every frame-end read below would find its bank unmapped; the old
        -- nil identity made HelloSession invalidate (identity_unavailable) and re-hello every few frames
        -- in battle. Such a frame is skipped whole, as if it never ran: no hello step, no invalidation,
        -- nothing published from a half-read; the next mapped frame catches up (signals stay latched).
        if io.bank_valid(profile.ram_bank.wPlayerID, profile.ram.wPlayerID, 1) ~= true then return end
        -- P4.1f panel: every mapped frame, before the hello step (the player may sit in START).
        if panel then
            local pok, perr = panel:service()
            if not pok then log("[SLink-gen2] panel: " .. tostring(perr)) end
        end
        local connected = self.hello_session:step(self.frame)
        self.checkpoint_held = false -- one frame's hold arms one frame's readiness
        self.hello_sent = connected == true
        if self.frame % Client.VALIDATE_EVERY == 0 then self:validate() end
        connected = connected and self.hello_session:status().ready
        if connected and #self.held > 0 then
            local held = self.held
            self.held, self.held_full = {}, false
            for _, m in ipairs(held) do send(m.event, m.fields) end
        end
        for _, batch in ipairs(self.signals and self.signals:drain() or {}) do
            for _, ev in ipairs(batch.events or {}) do
                local ok, err = pcall(self.on_event, self, ev)
                if not ok then log("[SLink-gen2] signal " .. tostring(ev.site_id) .. ": " .. tostring(err)) end
            end
        end
        -- A binder fault latches the shared registry (no later signal is captured): say so
        -- once, loudly, rather than run on as if events were still being observed.
        local st = self.signals and self.signals:status()
        -- A refusal is the binder declining one observation (no event); each distinct
        -- site/reason is logged once, never per frame.
        for site, why in pairs(st and st.refusals or {}) do
            local seen = site .. ": " .. tostring(why)
            if not self.refusals_logged[seen] then
                self.refusals_logged[seen] = true
                log("[SLink-gen2] engine signal refused " .. seen)
            end
        end
        if st and st.failed and st.failed ~= self.signal_failure_logged then
            self.signal_failure_logged = st.failed
            log("[SLink-gen2] engine signals STOPPED: " .. tostring(st.failed))
            hud.show("SLINK SIGNALS STOPPED - SEE LOG", 255, 64, 64, 600)
        end
        self:settle_faints()
        if self.pending_rescan then self.pending_rescan = false; self:rescan_boxes() end
        if connected and self.frame % Client.TICK_INTERVAL == 0 then self:send_tick("tick") end
        if self.pending_safe and connected then
            local battle = reads.read_battle()
            if battle and battle.mode == 0 then self.pending_safe = false; send("safe", {}) end
        end
        self.replies:step()
        self:run_deferred()
    end

    function self:stop()
        if self.checkpoint_hook then io.unregister(self.checkpoint_hook); self.checkpoint_hook = nil end
        if self.signals then self.signals:close() end
    end

    return self
end

return Client
