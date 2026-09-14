-- lua/gen1/client.lua — the Gen 1 Soul Link client, as a state machine over injected parts.
--
-- Contract: docs/protocol.md (the Gen 3 client + server/state.py are the authority).
-- Parts (all injected, so lupa can drive the whole client against a fake server):
--   reads   lua/gen1/reads.lua      pure WRAM/SRAM decoders (differential vs the Python codec)
--   signals lua/gen1/signals.lua    engine execution sites -> typed signals
--   writes  lua/gen1/writes.lua     faint/explode/rival writes behind the armed window
--   boxes   lua/gen1/boxes.lua      PC/memorial box moves (same armed window)
--   safety  lua/gen1_write_safety   the verified overworld checkpoint
--   net     lua/connector.lua       newline-JSON TCP (init/send/receive/pump/connected)
--   json    lua/json_codec.lua      decode/encode
--   hud     lua/hud.lua             show/prompt/set_game_over/set_rebuilding/clear_rebuilding
--
-- Events are derived from engine signals, never from polling heuristics: a party change is
-- only read after a site that legitimately changes the party fired (AddPartyMon,
-- SendNewMonToBox, MoveMon, RemovePokemon, TryEvolvingMon, InGameTrade_DoTrade).
-- Every write happens at the overworld checkpoint or inside the MainInBattleLoop hook.
local Client = { TICK_INTERVAL = 30, VALIDATE_EVERY = 60, MAX_INVALID = 5, MAX_PENDING_FRAMES = 600 }

local BALL_ITEMS = { [1] = true, [2] = true, [3] = true, [4] = true } -- MASTER..POKE (item_constants.asm:10-13)
-- Pokemon Tower 1F-7F ($8E-$94, map_constants.asm:228-234). A wild battle on these maps
-- without the Silph Scope (item_constants.asm:84) in the bag is a "ghost": the engine
-- refuses both the fight and the throw, so the battle ending says nothing about whether the
-- player failed to catch anything -- it is NOT a failed encounter and must not dead-zone
-- the area (docs/gen1_requirements.md F-4/S-2).
local TOWER_MAPS = { [0x8E] = true, [0x8F] = true, [0x90] = true, [0x91] = true,
                     [0x92] = true, [0x93] = true, [0x94] = true }
local SILPH_SCOPE = 0x48
local MOVE_BOX_TO_PARTY, MOVE_PARTY_TO_BOX, MOVE_DAYCARE_TO_PARTY, MOVE_PARTY_TO_DAYCARE = 0, 1, 2, 3
local TRANSFORMED_BIT = 8 -- bit 3 of wPlayerBattleStatus3 (battle_constants.asm:106)

local function hex_of(bytes)
    local out = {}
    for i = 1, #bytes do out[i] = string.format("%02X", bytes[i]) end
    return table.concat(out)
end

-- Gen 1 raw stage 7 == neutral; the wire wants seven slots, 6 == neutral, SDEF blank.
local function wire_stages(raw)
    if not raw then return nil end
    local function s(v) return (v or 7) - 1 end
    return { s(raw.attack), s(raw.defense), s(raw.speed), s(raw.special), 6, s(raw.accuracy), s(raw.evasion) }
end

function Client.new(p)
    local reads, signals_mod, writes, safety = p.reads, p.signals, p.writes, p.safety
    local net, json, hud, io = p.net, p.json, p.hud, p.io
    local profile, sites, ws_profile, area_map = p.profile, p.sites, p.write_checkpoint, p.area_map
    local log = p.log or function(...) end
    local d = profile.derived
    local arr = json.array -- tag lists so an empty one encodes as [] not {}

    local self = {
        player = p.player, rom_type = p.rom_type, rom_sha1 = p.rom_sha1,
        seq = 0, frame = 0, connected_last = false, hello_sent = false,
        writes_enabled = false, invalid_streak = 0, gate_revoked = false,
        known_keys = {}, box_cache = {}, resolved_areas = {}, config = {},
        deferred = {}, pending_battle_writes = {}, sync_written = {},
        pending_change = nil, battle = nil, has_pokeballs = false,
        signals = nil, boxes = p.boxes, rom = p.rom,
    }

    -- ── outbound ─────────────────────────────────────────────────────────────────────
    local function send(event, fields)
        if not net.connected() then
            log("[SLink-gen1] drop " .. event .. ": not connected")
            return false
        end
        self.seq = self.seq + 1
        local msg = fields or {}
        msg.event, msg.player, msg.seq = event, self.player, self.seq
        net.send(json.encode(msg))
        return true
    end
    self.send = send

    -- ── reads → wire shapes ──────────────────────────────────────────────────────────
    local function mon_key(m) return reads.key(m) end

    local function party_entry(m, active_slot, stages)
        -- 66-byte blob: struct(44) + OT(11) + nick(11), what the adapter's party_blob_size says
        local blob = io.read_range(profile.ram.wPartyMons + m.slot * d.party_struct_size, d.party_struct_size, "System Bus")
        for i = 1, #m.ot_name_bytes do blob[#blob + 1] = m.ot_name_bytes[i] end
        for i = 1, #m.nickname_bytes do blob[#blob + 1] = m.nickname_bytes[i] end
        local e = {
            key = mon_key(m), slot = m.slot, species_id = m.species, nickname = m.nickname,
            level = m.level, hp = m.hp, maxHP = m.max_hp, status_cond = m.status,
            moves = arr(m.moves), pp = arr(m.pp), pp_ups = arr(m.pp_ups), blob_hex = hex_of(blob),
            active = (active_slot ~= nil and m.slot == active_slot) or false,
        }
        if e.active and stages then e.stat_stages = arr(wire_stages(stages)) end
        return e
    end

    local function area_of(map)
        local a = area_map[tostring(map)]
        if a then return a.area_id, a.name end
        return "", "map_" .. tostring(map)
    end

    local function current_party()
        local party, why = reads.read_party()
        if not party then return nil, why end
        return party
    end

    local function snapshot_party()
        local party = current_party()
        if not party then return nil end
        local battle = reads.read_battle()
        local active = battle.in_battle ~= 0 and battle.player_mon_number or nil
        local stages = active and reads.read_stat_stages("player") or nil
        local out = arr({})
        for i, m in ipairs(party) do out[i] = party_entry(m, active, stages) end
        return out, battle
    end

    local function enemy_party(battle)
        if battle.in_battle == 0 then return arr({}) end
        local foe = { species_id = battle.enemy_species, level = battle.enemy_level,
                      hp = battle.enemy_hp, active = true }
        local stages = reads.read_stat_stages("enemy")
        if stages then foe.stat_stages = arr(wire_stages(stages)) end
        return arr({ foe })
    end

    local function ball_count()
        local bag = reads.read_bag()
        local n = 0
        if bag then for _, it in ipairs(bag.items) do if BALL_ITEMS[it.id] then n = n + it.qty end end end
        return n
    end

    local function pc_boxes_wire()
        local out = arr({})
        for _, e in ipairs(self.box_cache) do
            out[#out + 1] = { box = e.box, slot = e.slot, key = e.key, species_id = e.species_id,
                              nickname = e.nickname, level = e.level, moves = arr(e.moves) }
        end
        return out
    end

    -- Rescan the twelve boxes (SRAM) and the active box (WRAM mirror) into box_cache.
    function self:rescan_boxes()
        local cache = {}
        local cur = reads.read_current_box_num()
        local active = reads.read_active_box()
        -- SRAM boxes are garbage until the game's first ChangeBox initialises them (bit 7 of
        -- wCurrentBoxNum; save.asm EmptyAllSRAMBoxes) — only the WRAM mirror is real before that
        local sram = (cur and cur.initialized) and io.read_range(0, 0x8000, "CartRAM") or nil
        for box = 0, 11 do
            local mons
            if cur and box == cur.index then mons = active
            elseif sram then mons = reads.read_sram_box(sram, box) end
            if mons then
                for _, m in ipairs(mons) do
                    cache[#cache + 1] = { box = box, slot = m.slot, key = mon_key(m), species_id = m.species,
                                          nickname = m.nickname, level = m.level, moves = m.moves }
                end
            end
        end
        self.box_cache = cache
        return cache
    end

    -- ── the writes gate (R-4, W-6) ───────────────────────────────────────────────────
    local function game_is_live()
        local party = current_party()
        if not party then return false, "party unreadable" end
        if reads.read_player_id() == 0 and #party == 0 then return false, "pre-game (title/new game)" end
        return true
    end

    function self:validate()
        local ok, why = game_is_live()
        if ok then
            self.invalid_streak = 0
            if not self.writes_enabled and not self.gate_revoked then
                self.writes_enabled = true
                log("[SLink-gen1] writes ENABLED")
            end
            if self.gate_revoked and self.invalid_streak == 0 then
                -- a live game after a revoke: re-enable, but the deferred queue was cleared
                self.gate_revoked, self.writes_enabled = false, true
                log("[SLink-gen1] writes re-enabled after a live validation")
            end
        else
            self.invalid_streak = self.invalid_streak + 1
            if self.invalid_streak >= Client.MAX_INVALID and self.writes_enabled then
                self.writes_enabled, self.gate_revoked = false, true
                self.deferred, self.pending_battle_writes = {}, {}
                log("[SLink-gen1] writes REVOKED: " .. tostring(why))
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

    local function find_party_slot(key)
        local party = current_party()
        if not party then return nil end
        for _, m in ipairs(party) do if mon_key(m) == key then return m.slot, m, party end end
        return nil, nil, party
    end

    local function hud_color(cmd)
        if type(cmd.color) == "table" then return cmd.color[1], cmd.color[2], cmd.color[3], cmd.duration end
        return cmd.r, cmd.g, cmd.b, cmd.frames
    end

    function self:handle_command(cmd)
        local c = cmd.cmd
        if c == "noop" then return end
        if c == "force_faint" or c == "force_explode" then
            local slot, mon = find_party_slot(cmd.key)
            if not slot then log("[SLink-gen1] " .. c .. ": key not in party " .. tostring(cmd.key)) return end
            local battle = reads.read_battle()
            if battle.in_battle ~= 0 and battle.player_mon_number == slot then
                -- active battler: only the loop head may write (W-2); queue for the hook
                self.pending_battle_writes[#self.pending_battle_writes + 1] = { cmd = c, key = cmd.key }
            else
                self.deferred[#self.deferred + 1] = { cmd = c, key = cmd.key }
            end
            self.known_keys[cmd.key] = true
            return
        end
        if c == "box_mon" or c == "party_mon" or c == "memorialize" then
            self.deferred[#self.deferred + 1] = cmd
            return
        end
        if c == "replace_rival_team" then self:replace_rival_team(cmd) return end
        if c == "msgbox" or c == "gui_prompt" then
            local r, g, b, f = hud_color(cmd)
            hud.prompt(cmd.text, r, g, b, f)
        elseif c == "hud_show" then
            local r, g, b, f = hud_color(cmd)
            hud.show(cmd.text, r, g, b, f)
        elseif c == "play_sound" then
            -- Gen 3 SE ids; the Gen 1 companion patch ships no sound path
        elseif c == "resolved_areas" then
            self.resolved_areas = {}
            for _, a in ipairs(cmd.areas or {}) do self.resolved_areas[a] = true end
            self.seeded = true
        elseif c == "unresolve_area" then
            self.resolved_areas[cmd.area_id] = nil
        elseif c == "config" then
            self.config = cmd
        elseif c == "game_over" then
            hud.set_game_over()
            self.game_over = true
        elseif c == "rebuild_start" then
            hud.set_rebuilding(cmd.text)
        elseif c == "rebuild_done" then
            hud.clear_rebuilding()
        elseif c == "show_choices" or c == "show_menu" or c == "choose_mon" then
            ack_cancel(cmd) -- native prompts arrive with the trade port (Phase 7)
        elseif c == "apply_trade" then
            -- no trade path yet: report "nothing changed" with the pre-trade key (protocol §5)
            local slot, mon = find_party_slot(cmd.old_key)
            send("trade_done", { token = cmd.token, slot = slot or cmd.slot, new_key = cmd.old_key,
                                 new_species = mon and mon.species or 0 })
        elseif c == "link_panel" or c == "ghost_pos" then
            -- presentation the Gen 1 client does not render yet
        else
            log("[SLink-gen1] unknown command " .. tostring(c))
        end
    end

    function self:replace_rival_team(cmd)
        local battle = reads.read_battle()
        if battle.in_battle == 0 or battle.cur_opponent ~= cmd.trainer_id then
            send("rival_team_replaced", { trainer_id = cmd.trainer_id, species_ids = arr({}), error = "not_in_battle" })
            return
        end
        local mons, ids = {}, arr({})
        for i, hex in ipairs(cmd.blobs_hex or {}) do
            if #hex ~= 66 * 2 then
                send("rival_team_replaced", { trainer_id = cmd.trainer_id, species_ids = arr({}), error = "bad_blob_length" })
                return
            end
            local bytes = {}
            for j = 1, #hex, 2 do bytes[#bytes + 1] = tonumber(hex:sub(j, j + 1), 16) end
            local blob, ot, nick = {}, {}, {}
            for j = 1, 44 do blob[j] = bytes[j] end
            for j = 1, 11 do ot[j] = bytes[44 + j]; nick[j] = bytes[55 + j] end
            mons[i] = { species = blob[1], blob = blob, ot = ot, nick = nick }
            ids[i] = blob[1]
        end
        local ok, why = pcall(function()
            writes:arm("battle_intro")
            writes:write_enemy_party(mons)
            writes:disarm()
        end)
        writes:disarm()
        if ok then send("rival_team_replaced", { trainer_id = cmd.trainer_id, species_ids = ids })
        else send("rival_team_replaced", { trainer_id = cmd.trainer_id, species_ids = arr({}), error = tostring(why) }) end
    end

    -- Deferred queue: one command per frame, only at the verified overworld checkpoint.
    function self:run_deferred()
        if #self.deferred == 0 or not self.writes_enabled or not net.connected() then return end
        local safe, why = safety.check(ws_profile, io)
        if not safe then return end
        local cmd = table.remove(self.deferred, 1)
        local ok, err = pcall(function()
            writes:arm("overworld")
            if cmd.cmd == "force_faint" or cmd.cmd == "force_explode" then
                local slot = find_party_slot(cmd.key)
                if slot then writes:faint_party_slot(slot) end
                self.sync_written[cmd.key] = true
            elseif cmd.cmd == "box_mon" then
                local slot, mon = find_party_slot(cmd.key)
                if slot then send("stats_cache", { key = cmd.key, stats = { level = mon.level, maxHP = mon.max_hp } }) end
                local done, reason = self.boxes and self.boxes:deposit(cmd.key)
                if not done then send("box_mon_failed", { key = cmd.key, reason = reason or "no box module" })
                else self.sync_written[cmd.key] = true; self:rescan_boxes() end
            elseif cmd.cmd == "party_mon" then
                -- the withdrawn mon's stats are rebuilt from the cartridge's own base stats
                local species
                for _, e in ipairs(self.box_cache) do if e.key == cmd.key then species = e.species_id end end
                local base = species and self.rom and self.rom.base_stats_for(species) or nil
                local done, reason = self.boxes and self.boxes:withdraw(cmd.key, cmd.stats, base, cmd.nickname)
                if done then send("sync_retrieve_done", { key = cmd.key }); self.sync_written[cmd.key] = true; self:rescan_boxes()
                else send("sync_retrieve_failed", { key = cmd.key, reason = reason or "no box module" }) end
            elseif cmd.cmd == "memorialize" then
                local done, reason = self.boxes and self.boxes:memorialize(cmd.key)
                if done then send("memorialize_done", { key = cmd.key, box = 11 }); self.sync_written[cmd.key] = true; self:rescan_boxes()
                elseif reason == "last party mon" and self.game_over then
                    log("[SLink-gen1] memorialize dropped: last mon after game over")
                elseif reason == "last party mon" then
                    table.insert(self.deferred, 1, cmd) -- block until a party_mon lands
                else send("memorialize_failed", { key = cmd.key, reason = reason or "no box module" }) end
            end
            writes:disarm()
        end)
        writes:disarm()
        if not ok then log("[SLink-gen1] deferred " .. tostring(cmd.cmd) .. " failed: " .. tostring(err)) end
    end

    -- ── signals → events ─────────────────────────────────────────────────────────────
    local function key_at(party, slot)
        for _, m in ipairs(party) do if m.slot == slot then return mon_key(m), m end end
    end

    local function party_from_snapshot(bytes)
        -- decode the 404-byte snapshot a battle hook captured (party is stale for the active
        -- mon's HP at RemoveFaintedPlayerMon; the hook's battle_hp is authoritative for it)
        -- bytes[k + 1] is offset k from wPartyCount: count @0, species list @1..7, structs @8,
        -- OT names @8 + 6*44, nicknames after those (ram/wram.asm party block)
        local count = bytes[1]
        if count > d.party_capacity then return nil end
        local out = {}
        local structs = 1 + (d.party_capacity + 1)
        for slot = 0, count - 1 do
            local base = structs + slot * d.party_struct_size
            local raw = {}
            for i = 1, d.party_struct_size do raw[i] = bytes[base + i] end
            local mon = reads.decode_party_mon(raw, false)
            if not mon then return nil end
            mon.slot = slot
            local otb = structs + d.party_capacity * d.party_struct_size + slot * d.name_length
            mon.ot_name_bytes, mon.nickname_bytes = {}, {}
            for i = 1, d.name_length do
                mon.ot_name_bytes[i] = bytes[otb + i]
                mon.nickname_bytes[i] = bytes[otb + d.party_capacity * d.name_length + i]
            end
            out[#out + 1] = mon
        end
        return out
    end

    local function emit_faint(party, slot, area_id, hook_hp_zero_slot)
        local key = key_at(party, slot)
        if not key then return end
        send("faint", { key = key, area_id = area_id })
        -- whiteout: nothing alive once this faint is applied (HealParty runs before the
        -- blackout site, so the party bytes after the battle never show it)
        local alive = 0
        for _, m in ipairs(party) do
            if m.slot ~= slot and m.slot ~= hook_hp_zero_slot and m.hp > 0 then alive = alive + 1 end
        end
        if alive == 0 and not self.whiteout_sent then
            self.whiteout_sent = true
            send("whiteout", {})
        end
    end

    function self:on_signal(sig)
        local k, pt = sig.kind, sig.point or {}
        local map_id = pt.map or reads.read_map().map
        local area_id = select(1, area_of(map_id))
        if k == "battle_begin" or k == "wild_begin" then
            if not self.battle or self.battle.frame ~= sig.frame then
                self.battle = { frame = sig.frame, wild = pt.cur_opponent < 200, species = pt.species,
                                level = pt.level, area_id = area_id, map = map_id,
                                cur_opponent = pt.cur_opponent, captured = false }
                self.whiteout_sent = false
                if not self.battle.wild then send("trainer_battle_start", { trainer_id = pt.cur_opponent }) end
            end
        elseif k == "battle_end" then
            local b = self.battle
            if b and b.wild and not b.captured and not self.resolved_areas[b.area_id] and b.area_id ~= "" then
                -- A Tower ghost without the Scope: the battle cannot be won or caught, so it
                -- is not evidence of a failed encounter. `has_item` returns nil when the bag
                -- cannot be read (reads.lua:200-207), and the safe reading of "cannot tell" is
                -- to leave the area unresolved rather than to dead-zone it on a guess.
                if TOWER_MAPS[b.map] and reads.has_item(SILPH_SCOPE) ~= true then
                    log("[SLink-gen1] tower ghost battle without the Silph Scope: no_catch suppressed")
                else
                    send("no_catch", { area_id = b.area_id, species_id = b.species, level = b.level })
                    self.resolved_areas[b.area_id] = true
                end
            end
            self.battle = nil
            self.pending_safe = true
        elseif k == "battle_faint" then
            local party = party_from_snapshot(pt.party or {})
            if party then emit_faint(party, pt.active_slot, area_id, pt.battle_hp == 0 and pt.active_slot or nil) end
        elseif k == "poison_faint" then
            local party = party_from_snapshot(pt.party or {})
            if party then emit_faint(party, pt.which, area_id, pt.which) end
        elseif k == "blackout" then
            if not self.whiteout_sent then self.whiteout_sent = true; send("whiteout", {}) end
        elseif k == "bag_received" then
            self.has_pokeballs = true
        elseif k == "add_party_mon" or k == "capture_box" then
            local loc = pt.mon_location or 0
            if k == "add_party_mon" and loc % 16 ~= 0 then
                -- ReadTrainer building the ENEMY party through the same routine: not ours
            elseif k == "add_party_mon" and loc == 0x80 then
                -- NPC in-game trade appending the incoming mon: the npc_trade signal owns it
            elseif self.pending_change and self.pending_change.kind == "npc_trade" then
                -- already tracking the trade; the key_change settles it
            else
                self.pending_change = { kind = "acquire", frame = sig.frame, in_battle = pt.in_battle ~= 0,
                                        to_box = (k == "capture_box"), area_id = area_id, map = pt.map }
            end
        elseif k == "move_mon" then
            local party = current_party()
            if pt.move_type == MOVE_PARTY_TO_BOX or pt.move_type == MOVE_PARTY_TO_DAYCARE then
                local key, mon
                if party then key, mon = key_at(party, pt.which) end
                if key and not self.sync_written[key] then
                    send("party_to_box", { key = key, stats = { level = mon.level, maxHP = mon.max_hp } })
                end
                self.sync_written[key or ""] = nil
            elseif pt.move_type == MOVE_BOX_TO_PARTY or pt.move_type == MOVE_DAYCARE_TO_PARTY then
                local box = reads.read_active_box()
                local key = box and key_at(box, pt.which)
                if key and not self.sync_written[key] then send("box_to_party", { key = key, area_id = area_id }) end
                self.sync_written[key or ""] = nil
            end
            self.pending_change = { kind = "rescan", frame = sig.frame }
        elseif k == "remove_pokemon" then
            if not pt.from_box and not self.moved_this_frame then
                local party = current_party()
                local key = party and key_at(party, pt.which)
                if key and not self.sync_written[key] then send("party_to_box", { key = key }) end -- release
            end
            self.pending_change = { kind = "rescan", frame = sig.frame }
        elseif k == "evolve" then
            local party = party_from_snapshot(pt.party or {})
            local key, mon
                if party then key, mon = key_at(party, pt.which) end
            if key then self.pending_change = { kind = "evolution", frame = sig.frame, slot = pt.which, old_key = key, old_species = mon.species } end
        elseif k == "npc_trade" then
            local party = party_from_snapshot(pt.party or {})
            local key = party and key_at(party, pt.which)
            if key then self.pending_change = { kind = "npc_trade", frame = sig.frame, slot = pt.which, old_key = key } end
        elseif k == "save_witness" then
            if io.saveram then pcall(io.saveram) end
        elseif k == "starter_begin" or k == "starter_end" or k == "battle_loop_head" then
            -- consumed inside the hook (battle_loop_head) or informational (starter)
        end
        if k == "move_mon" then self.moved_this_frame = sig.frame end
    end

    -- A signal said the party/boxes changed; read the outcome once, when the engine is done.
    function self:settle_pending_change()
        local pc = self.pending_change
        if not pc or self.frame <= pc.frame then return end
        if self.frame - pc.frame > Client.MAX_PENDING_FRAMES then self.pending_change = nil return end
        local party = current_party()
        if not party then return end
        if pc.kind == "acquire" then
            local found = nil
            if pc.to_box then
                local box = reads.read_active_box()
                if box then for _, m in ipairs(box) do if not self.known_keys[mon_key(m)] then found = m end end end
            else
                for _, m in ipairs(party) do if not self.known_keys[mon_key(m)] then found = m end end
            end
            if not found then return end -- not written yet; try next frame
            local key = mon_key(found)
            self.known_keys[key] = true
            local gift = not pc.in_battle
            local area_id = pc.area_id
            if gift then area_id = "gift_map_" .. tostring(pc.map) end
            send("capture", { key = key, area_id = area_id, species_id = found.species, level = found.level,
                              hp = found.hp, maxHP = found.max_hp ~= reads.NULL and found.max_hp or nil,
                              nickname = found.nickname, gift = gift, in_box = pc.to_box,
                              stats = { level = found.level, maxHP = found.max_hp ~= reads.NULL and found.max_hp or nil } })
            if self.battle and not gift then self.battle.captured = true end
            self.resolved_areas[area_id] = true
            self.pending_change = { kind = "rescan", frame = self.frame }
        elseif pc.kind == "evolution" or pc.kind == "npc_trade" then
            local key, mon = key_at(party, pc.slot)
            if not key then self.pending_change = nil return end
            if key ~= pc.old_key then
                self.known_keys[pc.old_key] = nil
                self.known_keys[key] = true
                send("key_change", { old_key = pc.old_key, new_key = key, new_species = mon.species,
                                     reason = pc.kind == "evolution" and "evolution" or "npc_trade",
                                     new_nickname = mon.nickname })
                self.pending_change = nil
            elseif self.frame - pc.frame > 300 then
                self.pending_change = nil -- trade declined / evolution cancelled
            end
        elseif pc.kind == "rescan" then
            self:rescan_boxes()
            for _, m in ipairs(party) do self.known_keys[mon_key(m)] = true end
            for _, e in ipairs(self.box_cache) do self.known_keys[e.key] = true end
            self.pending_change = nil
        end
    end

    -- Inside the MainInBattleLoop hook: apply the queued in-battle faints/explodes now (W-2).
    function self:on_battle_loop_head(sig)
        if #self.pending_battle_writes == 0 or not self.writes_enabled then return end
        local pt = sig.point
        local party = current_party()
        if not party then return end
        local keep = {}
        for _, w in ipairs(self.pending_battle_writes) do
            local slot, mon = nil, nil
            for _, m in ipairs(party) do if mon_key(m) == w.key then slot, mon = m.slot, m end end
            if slot and slot == pt.active_slot then
                local battle = { in_battle = pt.in_battle, type = pt.battle_type, link_state = pt.link_state,
                                 player_mon_number = pt.active_slot, battle_species = pt.battle_species,
                                 transformed = math.floor(pt.status3 / TRANSFORMED_BIT) % 2 == 1 }
                local ok = writes.active_faint_guard(battle, slot, mon)
                if ok then
                    writes:arm("battle_loop_head")
                    if w.cmd == "force_explode" then writes:explode_active_battler(slot) else writes:faint_active_battler(slot) end
                    writes:disarm()
                    self.sync_written[w.key] = true
                else
                    keep[#keep + 1] = w
                end
            elseif slot then
                -- switched out meanwhile: a bench write at the next checkpoint is enough
                self.deferred[#self.deferred + 1] = { cmd = "force_faint", key = w.key }
            end
        end
        self.pending_battle_writes = keep
    end

    -- ── hello / tick ─────────────────────────────────────────────────────────────────
    function self:send_hello()
        local party, battle = snapshot_party()
        local map = reads.read_map()
        local area_id, loc = area_of(map.map)
        self.has_pokeballs = self.has_pokeballs or ball_count() > 0
        self:rescan_boxes()
        for _, e in ipairs(party or {}) do self.known_keys[e.key] = true end
        for _, e in ipairs(self.box_cache) do self.known_keys[e.key] = true end
        send("hello", {
            rom_type = self.rom_type, party = party or arr({}), ot_id = reads.read_player_id(),
            trainer_name = reads.read_player_name(), has_pokeballs = self.has_pokeballs,
            ball_count = ball_count(), badges = reads.read_badges(), area_id = area_id, loc_name = loc,
            pc_boxes = pc_boxes_wire(), writes_enabled = self.writes_enabled, rom_sha1 = self.rom_sha1,
            in_battle = battle and battle.in_battle ~= 0 or false,
        })
        self.hello_sent = true
    end

    function self:send_tick(event)
        local party, battle = snapshot_party()
        if not party then return end
        local map = reads.read_map()
        local area_id, loc = area_of(map.map)
        if self.last_area ~= nil and self.last_area ~= area_id then
            send("area_enter", { area_id = area_id, loc_name = loc })
        end
        self.last_area = area_id
        self.has_pokeballs = self.has_pokeballs or ball_count() > 0
        local in_battle = battle.in_battle ~= 0
        send(event or "tick", {
            party = party, has_pokeballs = self.has_pokeballs, ball_count = ball_count(),
            area_id = area_id, loc_name = loc, in_battle = in_battle,
            is_trainer_battle = in_battle and battle.is_trainer or false,
            trainer_id = in_battle and battle.is_trainer and battle.cur_opponent or nil,
            enemy_party = enemy_party(battle), badges = reads.read_badges(),
            trainer_name = reads.read_player_name(), pc_boxes = pc_boxes_wire(),
        })
    end

    -- ── per-frame driver ─────────────────────────────────────────────────────────────
    function self:start()
        self.signals = signals_mod.new(profile, sites, io, {
            battle_loop_head = function(sig) self:on_battle_loop_head(sig) end,
        })
    end

    function self:frame_end()
        self.frame = io.framecount()
        net.pump()
        local connected = net.connected()
        if connected and not self.connected_last then self:send_hello() end
        self.connected_last = connected
        if self.frame % Client.VALIDATE_EVERY == 0 then self:validate() end
        for _, sig in ipairs(self.signals and self.signals:drain() or {}) do
            local ok, err = pcall(self.on_signal, self, sig)
            if not ok then log("[SLink-gen1] signal " .. tostring(sig.kind) .. ": " .. tostring(err)) end
        end
        self.moved_this_frame = nil
        self:settle_pending_change()
        if connected and self.frame % Client.TICK_INTERVAL == 0 then self:send_tick("tick") end
        if self.pending_safe and connected then
            local battle = reads.read_battle()
            if battle.in_battle == 0 then self.pending_safe = false; send("safe", {}) end
        end
        while true do
            local line = net.receive()
            if not line then break end
            local ok, reply = pcall(json.decode, line)
            if ok and type(reply) == "table" and type(reply.commands) == "table" then
                for _, cmd in ipairs(reply.commands) do
                    local hok, herr = pcall(self.handle_command, self, cmd)
                    if not hok then log("[SLink-gen1] command " .. tostring(cmd and cmd.cmd) .. ": " .. tostring(herr)) end
                end
            else
                log("[SLink-gen1] unreadable reply line")
            end
        end
        self:run_deferred()
    end

    function self:stop()
        if self.signals then self.signals:close() end
    end

    return self
end

return Client
