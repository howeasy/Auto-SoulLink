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
local Client = { TICK_INTERVAL = 30, VALIDATE_EVERY = 60, MAX_INVALID = 5, MAX_PENDING_FRAMES = 600,
                 -- A13: the two halves of the `replace_rival_team` window. ONE window measured
                 -- from `battle_begin` cannot work, because the transition alone outlasts any
                 -- figure small enough to be a write window (this was RIVAL_SWAP_FRAMES = 120,
                 -- unsatisfiable behind either spiral). Both numbers below are LOWER BOUNDS built
                 -- from the engine's EXPLICIT delays plus margin -- they deliberately leave out
                 -- the CopyVideoData waits, which cost "c/8 frames" each (home/copy2.asm:62-65,
                 -- :96): LoadBattleTransitionTile (battle_transitions.asm:161-164, c=1) and
                 -- _LoadTrainerPic (core.asm:6681 -> home/pics.asm:193-196, c=PIC_SIZE=49, ~7
                 -- frames). The real deltas are measured per battle and logged as
                 -- `RIVAL_WINDOW init_frames=N staged_frames=M`.
                 --
                 -- (a) battle_begin (InitBattleCommon offset 0, engine_signals.json:43-49) -> the
                 -- staging at engine/battle/core.asm:6689-6690. In between sits
                 -- DoBattleTransitionAndInitBattleVariables (:6680):
                 --   outward spiral  120 DelayFrames        battle_transitions.asm:194-205
                 --   inward spiral   51 x TransferDelay3    :213-260 with :616-622 (Delay3)
                 --                   = 153 frames
                 --   prefix          Delay3 + DelayFrame + Delay3 (:4,:9,:49) + core.asm:6164
                 --                   = 8 frames
                 -- so >= 128 and >= 161; 240 is the worse of the two with ~50% margin.
                 RIVAL_INIT_FRAMES = 240,
                 -- (b) staging -> the FIRST consumer of the enemy party. This is NOT a lower
                 -- bound like (a): it is the maximum AGE of a $FF observation that may still be
                 -- written through, and it is what makes the byte sufficient rather than merely
                 -- necessary.
                 --
                 -- Why the byte alone is not enough. wEnemyMonPartyPos is not cleared on entry to
                 -- EnemySendOutFirstMon: :1326 reads it to pick the slot, :1337-1341 reads that
                 -- mon's HP, :1343-1348 its level and :1349-1357 its species, and only
                 -- LoadEnemyMonData stores the new position at :6055 -- after CalcStats (:6027)
                 -- and the HP copy (:6046-6053). That span contains NO engine-initiated wait (its
                 -- only calls are AddNTimes, GetMonHeader and CalcStats; BattleRandom is the
                 -- wild-only branch), but a BizHawk frame boundary is a PPU event, not a code
                 -- event, so a frame-end callback CAN land inside it and still read $FF.
                 --
                 -- And the send-out is not even the first party read. In order from the staging:
                 --   1. DrawAllPokeballs   common_text.asm:21-29 (`ld c,20 / DelayFrames`, THEN
                 --      `callfar DrawAllPokeballs`) -> draw_hud_pokeball_gfx.asm:1-7 ->
                 --      SetupEnemyPartyPokeballs :33-45 reads wEnemyMons + wEnemyPartyCount, and
                 --      PickPokeball :69-95 reads each mon's HP and status.  <-- FIRST CONSUMER
                 --   2. StartBattle core.asm:139-148 scans wEnemyMon1HP for the first alive mon
                 --      before it calls EnemySendOutFirstMon (:154).
                 --   3. EnemySendOutFirstMon :1326+ as above.
                 -- Explicit floor from the staging to (1), all inside _InitBattleCommon (:6735)
                 -- -> SlidePlayerAndEnemySilhouettesOnScreen (:9-100, which `jpfar`s into
                 -- PrintBeginningBattleText at :100):
                 --   Delay3 / DelayFrame / Delay3   :58, :65, :96          =  7 frames
                 --   silhouette slide  :70-84, 72 ITERATIONS (c = $90, dec c twice), each
                 --     blocking on rLY at $40 then $60 within one frame, so >= 71 guaranteed
                 --     inter-iteration frame crossings plus a partial first and last
                 --                                                        >= 71 frames
                 --   TrainerWantsToFight DelayFrames  common_text.asm:22-23 = 20 frames
                 --                                                        -------------
                 --                                                        >= 98 frames
                 -- 60 is that with a wide margin. A $FF seen by the client can itself be one
                 -- frame stale (the store happens inside a frame; the callback for that frame may
                 -- already have run), so the last permitted write lands at most 61 frames after
                 -- the store -- still far under 98.
                 --
                 -- The `RIVAL_WINDOW staged_frames=M` line below measures staging -> the
                 -- POSITION BYTE CHANGING, which is (3), downstream of (1) and (2). It must NEVER
                 -- be used to raise this cutoff; only a measured staging -> DrawAllPokeballs
                 -- interval could. COST of the cutoff: a reply arriving more than 60 frames after
                 -- the staging is refused `late_reply` even though the byte still reads $FF. In
                 -- the live flow the reply is parked through the transition and applied ON the
                 -- staging frame, so this only refuses a server answering about a second late.
                 RIVAL_STAGED_FRAMES = 60 }

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
-- Y-0: the two DEMONSTRATION battle types (constants/battle_constants.asm:43-46) —
-- BATTLE_TYPE_OLD_MAN (1, the Viridian catching tutorial) and BATTLE_TYPE_PIKACHU (4, Oak
-- catching the Pikachu in Yellow). Neither is the player's own encounter, so neither resolves
-- the area and neither reports a capture. BATTLE_TYPE_SAFARI (2) is NOT here: item_effects.asm
-- spends the player's Safari Balls (:130-137) and adds a Safari catch to the party/box
-- (:549-560), so it keeps both semantics.
local DEMO_BATTLE_TYPES = { [1] = true, [4] = true }
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
        seq = 0, frame = 0, hello_sent = false,
        writes_enabled = false, invalid_streak = 0, gate_revoked = false,
        known_keys = {}, box_cache = {}, resolved_areas = {}, config = {},
        deferred = {}, pending_battle_writes = {},
        pending_change = nil, pending_rival = nil, battle = nil, has_pokeballs = false,
        signals = nil, boxes = p.boxes, rom = p.rom, statics = p.statics, panel = p.panel,
        trade = p.trade, trade_enabled = false, trade_state = nil,
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
                self.gate_revoked, self.writes_enabled = false, true
                log("[SLink-gen1] writes re-enabled after a live validation")
            end
        else
            self.invalid_streak = self.invalid_streak + 1
            -- WRAM cleared (home/init.asm after a reset): whatever the player picks next is a
            -- new session for the server — CONTINUE re-hellos the same save (a reconnect),
            -- NEW GAME hellos a fresh wPlayerID and is refused (C-1)
            if reads.read_player_id() == 0 then
                self.hello_sent = false
                -- WRAM clear: the held panel belongs to the session that just ended
                if self.panel then self.panel:clear() end
            end
            if self.invalid_streak >= Client.MAX_INVALID and self.writes_enabled then
                -- pause, never drop: the queues survive (an unreadable party is a transient the
                -- engine creates itself, e.g. AddPartyMon's AskName prompt before the struct
                -- lands; a soft reset clears WRAM until the main menu reloads the save). Every
                -- command still needs its key to match at the checkpoint before a byte moves.
                self.writes_enabled, self.gate_revoked = false, true
                log("[SLink-gen1] writes PAUSED: " .. tostring(why))
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

    -- D-13 (MODEL): two party slots can answer to one identity key (same DVs, OT and species).
    -- Inbound commands then have no way to tell which mon the server meant, so the resolver
    -- refuses rather than guesses -- the same fail-closed rule boxes.lua:121-130 already applies.
    -- Returns slot, mon, party, why; `why` is "ambiguous key" when more than one slot matches.
    local function find_party_slot(key)
        local party = current_party()
        if not party then return nil end
        local slot, mon
        for _, m in ipairs(party) do
            if mon_key(m) == key then
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

    function self:handle_command(cmd)
        local c = cmd.cmd
        if c == "noop" then return end
        if c == "force_faint" or c == "force_explode" then
            local slot, mon, party, why = find_party_slot(cmd.key)
            if why then log("[SLink-gen1] " .. c .. ": " .. why .. " " .. tostring(cmd.key)) return end
            if not party then
                -- unreadable right now (AddPartyMon's AskName window): keep it; the checkpoint
                -- re-finds the key (a server command is never resent)
                self.deferred[#self.deferred + 1] = { cmd = c, key = cmd.key }
                self.known_keys[cmd.key] = true
                return
            end
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
        elseif c == "trade_mask" then
            self:trade_answer_query(cmd.mask or 0)
        elseif c == "trade_offer_ack" then
            self:trade_answer_offer(cmd.ok == true)
        elseif c == "show_menu" and self.trade_enabled and cmd.blob_hex and cmd.slot ~= nil then
            self:trade_prompt(cmd)
        elseif c == "show_choices" or c == "show_menu" or c == "choose_mon" then
            ack_cancel(cmd) -- no native picker outside the receptionist flow
        elseif c == "apply_trade" then
            if self.trade_enabled then self:trade_apply(cmd)
            else
                -- no trade path on this cartridge: "nothing changed" with the pre-trade key (§5)
                local slot, mon = find_party_slot(cmd.old_key)
                send("trade_done", { token = cmd.token, slot = slot or cmd.slot, new_key = cmd.old_key,
                                     new_species = mon and mon.species or 0 })
            end
        elseif c == "link_panel" then
            -- Held, not painted: the cartridge asks for the screen when the player opens the
            -- menu, and only the panel module knows whether that ask is still fresh.
            if self.panel then
                local pok, perr = self.panel:hold(cmd.rows)
                if not pok then log("[SLink-gen1] link_panel: " .. tostring(perr)) end
            end
        elseif c == "ghost_pos" then
            -- presentation the Gen 1 client does not render yet
        else
            log("[SLink-gen1] unknown command " .. tostring(c))
        end
    end

    -- A13: is `b` the battle `cmd` names, and is it still inside the window? Before the party is
    -- staged that is RIVAL_INIT_FRAMES from `battle_begin`; after it, RIVAL_STAGED_FRAMES from
    -- the staging. Measuring the whole thing from `battle_begin` is what made the window
    -- unsatisfiable: the staging itself can be 161 frames in.
    local function rival_window_live(b, trainer_id)
        if not b or b.cur_opponent ~= trainer_id then return false end
        if b.pos_staged then return (self.frame - b.pos_staged) <= Client.RIVAL_STAGED_FRAMES end
        return (self.frame - b.frame) <= Client.RIVAL_INIT_FRAMES
    end

    function self:replace_rival_team(cmd)
        local battle = reads.read_battle()
        local b = self.battle
        local live = rival_window_live(b, cmd.trainer_id)
        -- wIsInBattle is NOT the gate. `battle_begin` is hooked at InitBattleCommon offset 0
        -- (engine_signals.json:43-49) and `trainer_battle_start` goes out from that hook, so the
        -- server answers in the same round trip -- while pret is still inside
        -- DoBattleTransitionAndInitBattleVariables (core.asm:6680). `ld a, $2 / ld [wIsInBattle]`
        -- is at :6691-6692, one instruction AFTER the staging at :6689-6690, so an early reply
        -- legitimately reads 0. Refuse `not_in_battle` only when no initializing battle for this
        -- trainer is live either.
        if not live and (battle.in_battle == 0 or battle.cur_opponent ~= cmd.trainer_id) then
            send("rival_team_replaced", { trainer_id = cmd.trainer_id, species_ids = arr({}), error = "not_in_battle" })
            return
        end
        if not live then -- the right battle, but past its window
            send("rival_team_replaced", { trainer_id = cmd.trainer_id, species_ids = arr({}), error = "late_reply" })
            return
        end
        -- One replacement per battle. A duplicate reply (a server retry, or the same command
        -- delivered twice) would otherwise write the party a second time, and the second write
        -- races the engine for no gain: ack it and move no byte.
        if b.rival_applied then
            send("rival_team_replaced", { trainer_id = cmd.trainer_id, species_ids = arr({}), error = "already_applied" })
            return
        end
        -- The enemy party may only be rewritten between InitBattleCommon staging it
        -- (core.asm:6689-6690 sets wEnemyMonPartyPos = $FF) and EnemySendOutFirstMon clearing it
        -- before LoadEnemyMonData (:1292,:1326). $FF means nobody has been sent out: write now.
        -- Not $FF and never staged means the transition is still running: park the reply and let
        -- rival_window_tick apply it at the frame the byte flips. Not $FF after it HAS been $FF
        -- means the engine already read the bytes we would replace.
        if io.read_u8(profile.ram.wEnemyMonPartyPos, "System Bus") ~= 0xFF then
            if b.pos_staged then
                send("rival_team_replaced", { trainer_id = cmd.trainer_id, species_ids = arr({}), error = "late_reply" })
                return
            end
            if self.pending_rival then -- one hold at a time; the displaced reply gets its answer
                send("rival_team_replaced", { trainer_id = self.pending_rival.trainer_id,
                                              species_ids = arr({}), error = "late_reply" })
            end
            self.pending_rival = cmd
            return
        end
        b.pos_staged = b.pos_staged or self.frame
        local mons, ids = {}, arr({})
        for i, hex in ipairs(cmd.blobs_hex or {}) do
            -- `#hex` on a server-supplied non-string raises outside the pcall below, and an
            -- error thrown here leaves the server with no answer at all: check the type first.
            if type(hex) ~= "string" or #hex ~= 66 * 2 then
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
        if ok then
            b.rival_applied = true
            send("rival_team_replaced", { trainer_id = cmd.trainer_id, species_ids = ids })
        else send("rival_team_replaced", { trainer_id = cmd.trainer_id, species_ids = arr({}), error = tostring(why) }) end
    end

    -- A13: watch wEnemyMonPartyPos for the frame InitBattleCommon stages the party ($FF), both to
    -- remember that this battle's window HAS opened (so a reply after EnemySendOutFirstMon cleared
    -- the byte again is late, not early) and to release a reply that beat the staging. A parked
    -- reply is answered `late_reply` the frame the window closes -- by the send-out, or by the
    -- belt -- rather than sitting unanswered.
    local function answer_pending_late()
        local cmd = self.pending_rival
        if not cmd then return end
        self.pending_rival = nil
        send("rival_team_replaced", { trainer_id = cmd.trainer_id, species_ids = arr({}), error = "late_reply" })
    end

    function self:rival_window_tick()
        local b = self.battle
        if not b then return answer_pending_late() end
        local pos = io.read_u8(profile.ram.wEnemyMonPartyPos, "System Bus")
        if pos == 0xFF and not b.pos_staged and (self.frame - b.frame) <= Client.RIVAL_INIT_FRAMES then
            b.pos_staged = self.frame
            log("[SLink-gen1] RIVAL_WINDOW init_frames=" .. (b.pos_staged - b.frame))
            local cmd = self.pending_rival
            if cmd then self.pending_rival = nil; self:replace_rival_team(cmd) end
        elseif b.pos_staged and pos ~= 0xFF and not b.sendout_frame then
            -- The measurement the constants above are only lower bounds for. Logged once per
            -- battle, whatever the swap did, so the lane run records the real numbers.
            b.sendout_frame = self.frame
            log("[SLink-gen1] RIVAL_WINDOW init_frames=" .. (b.pos_staged - b.frame)
                .. " staged_frames=" .. (b.sendout_frame - b.pos_staged))
        end
        -- a parked reply is answered the frame the window shuts: by the send-out, or by the belt
        if self.pending_rival and (not rival_window_live(b, b.cur_opponent)
                                   or (b.pos_staged and pos ~= 0xFF)) then
            answer_pending_late()
        end
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
                local slot, _, _, why = find_party_slot(cmd.key)
                if slot then
                    writes:faint_party_slot(slot)
                else
                    -- the mon left the party before the checkpoint (PC deposit), or a duplicate
                    -- arrived and the key no longer names one mon: no byte moves. The protocol
                    -- has no force_faint NACK.
                    log("[SLink-gen1] " .. cmd.cmd .. " dropped at the checkpoint: "
                        .. (why or "key not in party") .. " " .. tostring(cmd.key))
                end
            elseif cmd.cmd == "box_mon" then
                local slot, mon = find_party_slot(cmd.key)
                if slot then send("stats_cache", { key = cmd.key, stats = { level = mon.level, maxHP = mon.max_hp } }) end
                -- `x and f()` keeps only f's first value: bind both explicitly
                local done, reason = nil, "no box module"
                if self.boxes then done, reason = self.boxes:deposit(cmd.key) end
                if not done then send("box_mon_failed", { key = cmd.key, reason = reason or "deposit refused" })
                else self:rescan_boxes() end
            elseif cmd.cmd == "party_mon" then
                -- the withdrawn mon's stats are rebuilt from the cartridge's own base stats
                local species
                for _, e in ipairs(self.box_cache) do if e.key == cmd.key then species = e.species_id end end
                local base = species and self.rom and self.rom.base_stats_for(species) or nil
                local done, reason = nil, "no box module"
                if self.boxes then done, reason = self.boxes:withdraw(cmd.key, cmd.stats, base, cmd.nickname) end
                if done then send("sync_retrieve_done", { key = cmd.key }); self:rescan_boxes()
                else send("sync_retrieve_failed", { key = cmd.key, reason = reason or "withdraw refused" }) end
            elseif cmd.cmd == "memorialize" then
                local done, reason = nil, "no box module"
                if self.boxes then done, reason = self.boxes:memorialize(cmd.key) end
                if done then send("memorialize_done", { key = cmd.key, box = 11 }); self:rescan_boxes()
                elseif reason == "last party mon" and self.game_over then
                    log("[SLink-gen1] memorialize dropped: last mon after game over")
                elseif reason == "last party mon" then
                    -- block until a party_mon lands -- at the TAIL, because the rebuild that
                    -- makes the memorial legal is itself queued behind this command; re-inserting
                    -- at the head starves it and the pair never recovers (A5)
                    self.deferred[#self.deferred + 1] = cmd
                else send("memorialize_failed", { key = cmd.key, reason = reason or "memorial refused" }) end
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
    local function holds_key(list, key)
        if not list or not key then return false end
        for _, m in ipairs(list) do if mon_key(m) == key then return true end end
        return false
    end

    local function party_from_snapshot(bytes)
        -- decode the 404-byte snapshot a battle hook captured (party is stale for the active
        -- mon's HP at RemoveFaintedPlayerMon; the hook's battle_hp is authoritative for it)
        -- bytes[k + 1] is offset k from wPartyCount: count @0, species list @1..7, structs @8,
        -- OT names @8 + 6*44, nicknames after those (ram/wram.asm party block)
        local count = bytes[1]
        -- nil/garbage must come back as "undecoded", not as an error: the pcall around on_signal
        -- (frame_end) would swallow the whole signal and nothing would classify it at all
        if type(count) ~= "number" or count > d.party_capacity then return nil end
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
                                cur_opponent = pt.cur_opponent, captured = false,
                                demo = DEMO_BATTLE_TYPES[pt.battle_type] and pt.battle_type or false }
                self.whiteout_sent = false
                if not self.battle.wild then send("trainer_battle_start", { trainer_id = pt.cur_opponent }) end
                if self.battle.wild then
                    -- A scripted, fixed-species encounter owns its own slot and must not consume
                    -- the map's wild area: data/games/gen1_rby/static_encounters.json lists the
                    -- species per map, and the server recognises static_<map>_<dex>.
                    local ids = self.statics and self.statics[tostring(map_id)]
                    for _, s in ipairs(ids or {}) do
                        if s == pt.species then
                            local dex = self.rom.natdex(pt.species)
                            if dex then
                                self.battle.static = true
                                self.battle.area_id = "static_" .. tostring(map_id) .. "_" .. tostring(dex)
                            end
                            break
                        end
                    end
                end
            end
        elseif k == "battle_end" then
            local b = self.battle
            if b and b.demo then
                log("[SLink-gen1] demonstration battle (type " .. tostring(b.demo) .. "): nothing resolved")
            elseif b and b.wild and not b.captured and not self.resolved_areas[b.area_id] and b.area_id ~= "" then
                -- A Tower ghost without the Scope: the battle cannot be won or caught, so it
                -- is not evidence of a failed encounter. `has_item` returns nil when the bag
                -- cannot be read (reads.lua:200-207), and the safe reading of "cannot tell" is
                -- to leave the area unresolved rather than to dead-zone it on a guess.
                if TOWER_MAPS[b.map] and reads.has_item(SILPH_SCOPE) ~= true then
                    log("[SLink-gen1] tower ghost battle without the Silph Scope: no_catch suppressed")
                elseif not self.has_pokeballs then
                    -- D-2: nothing resolves before the first Poke Ball. The server has no ball
                    -- gate by design (test_state.py: the client is responsible), and the parcel
                    -- walk crosses Route 1 grass with an empty bag (ball_gate_new, 2026-09-17).
                    log("[SLink-gen1] no Poke Balls yet: no_catch withheld, " .. b.area_id .. " stays open")
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
                                        to_box = (k == "capture_box"), area_id = area_id, map = pt.map,
                                        -- stamped now: the demo battle can end before this settles
                                        demo = (self.battle and self.battle.demo) or false }
            end
        elseif k == "move_mon" then
            -- Every MoveMon is the PLAYER's: boxes.lua moves the client's own box bytes with
            -- io.write_bytes (:345-346,:455-456) and never calls _MoveMon, so a server-ordered
            -- box_mon/party_mon produces no signal to echo and needs no per-key suppression.
            -- A per-key mark that outlived its write instead swallowed the player's own Bill's
            -- PC deposit of a quarantined key (PC-1, whiteout_new receipt 2026-09-17).
            -- both sides come from the point's snapshot: _MoveMon has already copied the mon and
            -- _RemovePokemon shifts the rest down, so a live read here names the wrong slot (or
            -- none at all, when the last slot moved)
            if pt.move_type == MOVE_PARTY_TO_BOX or pt.move_type == MOVE_PARTY_TO_DAYCARE then
                local party = party_from_snapshot(pt.party or {})
                local key, mon
                if party then key, mon = key_at(party, pt.which) end
                if key then
                    send("party_to_box", { key = key, stats = { level = mon.level, maxHP = mon.max_hp } })
                end
            elseif pt.move_type == MOVE_BOX_TO_PARTY or pt.move_type == MOVE_DAYCARE_TO_PARTY then
                local box = reads.box_from_snapshot(pt.box or {})
                local key = box and key_at(box, pt.which)
                if key then send("box_to_party", { key = key, area_id = area_id }) end
            end
            self.pending_change = { kind = "rescan", frame = sig.frame }
        elseif k == "remove_pokemon" then
            -- the native SLINK apply removes the offered mon through _RemovePokemon and appends
            -- the received one; trade_done accounts for both (receipt: a spurious party_to_box
            -- for the INCOMING key went out mid-apply and the server ordered a box_mon back)
            -- The removal happens EARLY in the apply (patch/gen1/src/native_trade.asm:157-158,
            -- vanilla cable_club.asm:799-800) and the DONE that ends the trade is published a
            -- hundred-odd frames later (:179-180 DelayFrames 100, :204 save, then
            -- trade_service.asm:106-113): only the APPLY state spans that gap, which is why this
            -- is a state test and not an age window.
            local trading = self.trade_state and self.trade_state.kind == "apply"
            -- What separates a removal that finishes a MoveMon from a standalone one is WHERE
            -- THE MON IS, not how many frames ago the MoveMon fired: _MoveMon runs to completion
            -- before RemovePokemon is called, and both collections are in this point's snapshot.
            -- The frame distance is not usable — pc_ops_new (2026-09-17) drained the withdraw's
            -- two hooks in different frame_end batches and the 2-frame age window called Bill's
            -- WITHDRAW a release.
            local party = party_from_snapshot(pt.party or {})
            local box = reads.box_from_snapshot(pt.box or {})
            local moved = self.moved_this_frame and (self.frame - self.moved_this_frame) <= 2
            local key
            if pt.from_box then key = box and key_at(box, pt.which)
            else key = party and key_at(party, pt.which) end
            if not party or not box then
                -- Both collections must DECODE before an absence can mean anything: a nil party
                -- would make Bill's WITHDRAW look like a release, a nil box would make a deposit
                -- look standalone. The signal is consumed here either way -- a later snapshot is
                -- a different instant and must never be used to re-classify this removal.
                log(string.format("[SLink-gen1] STORAGE_CLASSIFICATION_UNAVAILABLE key=%s why=%s",
                                  key or "?", (not party) and "party-undecoded" or "box-undecoded"))
            elseif pt.from_box then
                -- Bill's WITHDRAW ends in RemovePokemon(from_box) too, right after its
                -- BOX_TO_PARTY MoveMon (bills_pc.asm:282-287), so `from_box` alone is not the
                -- discriminator. At this hook (site offset 0, home/move_mon.asm:20-21 jpfar
                -- _RemovePokemon -- nothing has been shifted yet) the key is still in the BOX
                -- either way; what tells them apart is that the WITHDRAW's MoveMon has already
                -- installed it in the PARTY and a RELEASE (bills_pc.asm:310-312) has not. The
                -- shared protocol has no release event and a party_to_box for a mon that was
                -- never in the party would be a lie, so this is a marker for the receipts.
                if key and not holds_key(party, key) and not trading then
                    log(string.format("[SLink-gen1] RELEASE_SEEN key=%s box=%d", key, (pt.box_num or 0) % 128))
                end
            else
                -- from the SNAPSHOT, like the sibling branches: _RemovePokemon has already shifted
                -- the rest of the party down by drain time, so a live read names the mon that
                -- moved INTO the slot (engine/events/in_game_trades.asm:145,
                -- engine/link/cable_club.asm:799 are the two standalone callers).
                -- A DEPOSIT's MoveMon (bills_pc.asm:230-235) has already appended the mon to the
                -- box, so its key is in the box snapshot and `move_mon` has reported it already.
                -- PARTY_TO_DAYCARE (scripts/Daycare.asm:51-56) leaves it in neither collection,
                -- which is what the MoveMon pairing still covers.
                if key and not holds_key(box, key) and not moved and not trading then
                    send("party_to_box", { key = key }) -- release
                end
            end
            -- ponytail: key membership, not a handshake. The key is DVs:OT:species only
            -- (reads.lua:185-188 -- nickname and level are not in it), so a 1/65536 identity
            -- collision misreads BOTH directions: releasing a boxed mon whose key also names a
            -- party mon logs nothing, and a standalone party removal (in_game_trades.asm:143-148,
            -- cable_club.asm:799-800) of a key that an unrelated boxed mon shares is swallowed as
            -- a completed deposit. Pair the two signals by wWhichPokemon if a receipt shows one.
            -- a live npc_trade/evolution still owes a key_change; RemovePokemon runs INSIDE the
            -- NPC trade (in_game_trades.asm:145), so a rescan here would swallow it
            local pk = self.pending_change and self.pending_change.kind
            if pk ~= "npc_trade" and pk ~= "evolution" then
                self.pending_change = { kind = "rescan", frame = sig.frame }
            end
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
            -- add_mon.asm:58-243 writes the struct AFTER the AskName prompt (:45-52), in the
            -- order species, DVs, moves, OT, exp, EVs, PP, level, stats, and a frame boundary
            -- can fall inside that run (ball_gate_new receipts 2026-09-17: OT 0000, level 0).
            -- Level and stats are the last writes: require them, and the same key on two
            -- consecutive frames, before the mon is reported.
            local key = mon_key(found)
            if found.level == 0 or (not pc.to_box and found.max_hp == 0) or pc.candidate ~= key then
                pc.candidate = key
                return
            end
            self.known_keys[key] = true
            if pc.demo then
                -- Y-0: the mon Oak (or the old man) catches during a demonstration is not the
                -- player's capture and its map is not resolved by it. Known, but not reported.
                log("[SLink-gen1] demonstration battle: capture of " .. key .. " not reported")
                self.pending_change = { kind = "rescan", frame = self.frame }
                return
            end
            local gift = not pc.in_battle
            local area_id = pc.area_id
            if gift then area_id = "gift_map_" .. tostring(pc.map)
            elseif self.battle and self.battle.static then area_id = self.battle.area_id end
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
        -- an unreadable party keeps the queue: find_party_slot could not tell "gone" from
        -- "not readable yet", and a dropped in-battle write never comes back
        if not current_party() then return end
        local keep = {}
        for _, w in ipairs(self.pending_battle_writes) do
            -- the same ambiguity-aware resolver the checkpoint uses: this one used to take the
            -- LAST match where find_party_slot took the first, so one duplicate made the two
            -- paths faint different mons (D-13)
            local slot, mon, _, why = find_party_slot(w.key)
            if why then
                log("[SLink-gen1] battle write dropped: " .. why .. " " .. tostring(w.key))
            elseif slot and slot == pt.active_slot then
                local battle = { in_battle = pt.in_battle, type = pt.battle_type, link_state = pt.link_state,
                                 player_mon_number = pt.active_slot, battle_species = pt.battle_species,
                                 transformed = math.floor(pt.status3 / TRANSFORMED_BIT) % 2 == 1 }
                local ok = writes.active_faint_guard(battle, slot, mon)
                if ok then
                    writes:arm("battle_loop_head")
                    if w.cmd == "force_explode" then writes:explode_active_battler(slot) else writes:faint_active_battler(slot) end
                    writes:disarm()
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
        local rom_content
        if self.rom and self.rom.rom_content then
            local ok, result = pcall(self.rom.rom_content)
            if ok then rom_content = result
            elseif not self.rom_content_error_logged then
                log("[SLink-gen1] rom_content unavailable: " .. tostring(result))
                self.rom_content_error_logged = true
            end
        end
        send("hello", {
            rom_type = self.rom_type, party = party or arr({}), ot_id = reads.read_player_id(),
            trainer_name = reads.read_player_name(), has_pokeballs = self.has_pokeballs,
            ball_count = ball_count(), badges = reads.read_badges(), area_id = area_id, loc_name = loc,
            pc_boxes = pc_boxes_wire(), writes_enabled = self.writes_enabled, rom_sha1 = self.rom_sha1,
            in_battle = battle and battle.in_battle ~= 0 or false, rom_content = rom_content,
            -- per CARTRIDGE, not per generation: only a patched one has the panel mailbox
            panel = self.panel and self.panel:present() or false,
            panel_abi = self.panel and self.panel:abi() or 0,
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

    -- ── in-game SLINK TRADE (companion patch receptionist; T-rows) ───────────────────
    -- The overlay is a 16-byte lease the patched game hands the host at wSerialPartyMonsPatchList;
    -- writes to it (and the staged enemy party) happen inside that lease, not at the overworld
    -- checkpoint: the receptionist waits <=30/180 frames in its own loop for our bytes.
    local TRADE_DISPATCH = { 0x21, 0x00, 0x4C, 0x06, 0x3F } -- receptionist hook at 0x29C3 once patched
    local PROMPT, APPLY = 3, 5

    -- pret charmap subset for the partner name shown by the prompt/animation
    local function encode_name11(text)
        local out = {}
        for ch in tostring(text or ""):upper():gmatch(".") do
            local b = ch:byte()
            local code
            if b >= 65 and b <= 90 then code = 0x80 + (b - 65)
            elseif b >= 48 and b <= 57 then code = 0xF6 + (b - 48)
            elseif ch == " " then code = 0x7F end
            if code and #out < 10 then out[#out + 1] = code end
        end
        out[#out + 1] = 0x50
        while #out < 11 do out[#out + 1] = 0x50 end
        return out
    end
    local function hex_bytes(hex)
        local out = {}
        for i = 1, #hex, 2 do out[#out + 1] = tonumber(hex:sub(i, i + 1), 16) end
        return out
    end
    local function ot_of(blob)
        local name = {}
        for i = 45, 55 do name[#name + 1] = blob[i] end -- the incoming mon carries its OT name
        return name
    end
    local function new_token()
        local t = {}
        for i = 1, 4 do t[i] = math.random(1, 255) end
        return t
    end

    function self:trade_patch_present()
        for i, b in ipairs(TRADE_DISPATCH) do
            if io.read_u8(0x29C3 + i - 1, "ROM") ~= b then return false end
        end
        return true
    end

    local function trade_arm(fn)
        writes:arm("trade_overlay")
        local ok, a, b = pcall(fn)
        writes:disarm()
        if not ok then error(a, 0) end
        return a, b
    end

    function self:trade_answer_query(mask)
        local st = self.trade_state
        if not st or st.kind ~= "query" then return end
        local token = new_token()
        local ok, why = trade_arm(function() return self.trade:answer_query(st.gen, mask, token) end)
        if not ok then log("[SLink-gen1] trade query answer refused: " .. tostring(why)) end
        self.trade_state = { kind = "visit", token = token }
    end

    function self:trade_answer_offer(ok)
        local st = self.trade_state
        if not st or st.kind ~= "offer" then return end
        local done, why = trade_arm(function() return self.trade:answer_offer(st.gen, ok) end)
        if not done then log("[SLink-gen1] trade offer answer refused: " .. tostring(why)) end
        self.trade_state = { kind = "visit", token = st.token }
    end

    -- Partner side: the initiator mon is staged and the game asks YES/NO natively.
    function self:trade_prompt(cmd)
        local blob = hex_bytes(cmd.blob_hex)
        local name = ot_of(blob)
        local gen, why = trade_arm(function()
            return self.trade:arm(PROMPT, cmd.slot, blob, name, new_token())
        end)
        if not gen then
            log("[SLink-gen1] trade prompt arm refused: " .. tostring(why))
            send("menu_result", { token = cmd.token, choice = 0 })
            return
        end
        self.trade_state = { kind = "prompt", gen = gen, token = cmd.token, arm = { PROMPT, cmd.slot, blob, name } }
    end

    -- Both sides: apply_trade stages the OTHER mon; the game swaps, animates, evolves, saves.
    function self:trade_apply(cmd)
        local slot = find_party_slot(cmd.old_key)
        if slot == nil then
            log("[SLink-gen1] apply_trade: old_key not in party; nothing changed")
            send("trade_done", { token = cmd.token, slot = cmd.slot, new_key = cmd.old_key, new_species = 0 })
            return
        end
        local blob = hex_bytes(cmd.blob_hex)
        local name = cmd.partner_name and encode_name11(cmd.partner_name) or ot_of(blob)
        local gen, why = trade_arm(function()
            return self.trade:arm(APPLY, slot, blob, name, new_token())
        end)
        if not gen then
            log("[SLink-gen1] apply_trade arm refused: " .. tostring(why))
            send("trade_done", { token = cmd.token, slot = slot, new_key = cmd.old_key, new_species = 0 })
            return
        end
        self.trade_state = { kind = "apply", gen = gen, token = cmd.token, old_key = cmd.old_key, slot = slot,
                             arm = { APPLY, slot, blob, name } }
    end

    -- Per-frame: watch the lease for the receptionist questions and the native completions.
    function self:trade_tick()
        if not self.trade_enabled or not self.trade then return end
        local st = self.trade_state
        if st and (st.kind == "prompt" or st.kind == "apply") then
            if self.trade:clobbered() then
                -- the borrowed tile bytes were overwritten before pickup: stage again
                local gen = trade_arm(function() return self.trade:arm(st.arm[1], st.arm[2], st.arm[3], st.arm[4], new_token()) end)
                if gen then st.gen = gen end
                return
            end
            local done = self.trade:poll_done()
            if not done then return end
            if st.kind == "prompt" then
                local released = trade_arm(function() return self.trade:release(st.gen) end)
                send("menu_result", { token = st.token, choice = (done.result == 0 and released) and 1 or 0 })
                self.trade_state = nil
            else
                if done.result == 2 then
                    -- native append uncertain (T-5 limit): the cartridge keeps the lease; no release, no claim
                    if not st.warned then
                        st.warned = true
                        hud.show("TRADE UNCERTAIN - CHECK PARTY", 255, 64, 64, 600)
                        log("[SLink-gen1] apply_trade: native result 2 (uncertain); holding, no release")
                    end
                    return
                end
                trade_arm(function() return self.trade:release(st.gen) end)
                if done.result == 0 then
                    local party = current_party()
                    local received = party and party[#party]
                    if received then
                        local key = mon_key(received)
                        self.known_keys[st.old_key] = nil
                        self.known_keys[key] = true
                        send("trade_done", { token = st.token, slot = received.slot, new_key = key, new_species = received.species })
                    else
                        send("trade_done", { token = st.token, slot = st.slot, new_key = st.old_key, new_species = 0 })
                    end
                else
                    log("[SLink-gen1] apply_trade refused natively (result " .. tostring(done.result) .. "); nothing changed")
                    send("trade_done", { token = st.token, slot = st.slot, new_key = st.old_key, new_species = 0 })
                end
                self.trade_state = nil
                self.pending_change = { kind = "rescan", frame = self.frame }
            end
            return
        end
        local q = self.trade:poll_query()
        if q and not (st and st.kind == "query" and st.gen == q.gen) then
            self.trade_state = { kind = "query", gen = q.gen }
            if not send("trade_query", {}) then
                trade_arm(function() return self.trade:answer_query(q.gen, 0, new_token()) end) -- offline: nothing eligible
                self.trade_state = nil
            end
            return
        end
        local o = self.trade:poll_offer()
        if o and not (st and st.kind == "offer" and st.gen == o.gen) then
            self.trade_state = { kind = "offer", gen = o.gen, slot = o.slot, token = st and st.token }
            if not send("trade_offer", { slot = o.slot }) then
                trade_arm(function() return self.trade:answer_offer(o.gen, false) end)
                self.trade_state = nil
            end
        end
    end

    -- ── per-frame driver ─────────────────────────────────────────────────────────────
    function self:start()
        local handlers = { battle_loop_head = function(sig) self:on_battle_loop_head(sig) end }
        local all_sites = sites
        if self.trade and self:trade_patch_present() then
            -- the receptionist service entry (bank $3F:$4500) exists only in a patched cartridge,
            -- so it is pinned against the running ROM here rather than in engine_signals.json
            local svc = self.trade.service_address and self.trade.service_address() or { bank = 0x3F, addr = 0x4500 }
            local flat = svc.bank * 0x4000 + (svc.addr - 0x4000)
            local bytes = io.read_range(flat, 6, "ROM")
            all_sites = {}
            for k, v in pairs(sites) do all_sites[k] = v end
            all_sites.trade_service = { bank = svc.bank, address = svc.addr, rom_offset = flat,
                                        capture_offset = 0, expected_hex = hex_of(bytes), symbol = "SlinkTradeService" }
            handlers.trade_service = function() self.trade:picked_up() end
            self.trade_enabled = true
        end
        self.signals = signals_mod.new(profile, all_sites, io, handlers)
    end

    function self:frame_end()
        self.frame = io.framecount()
        -- FIRST: the patch whites the screen and polls for us, and the player doing that is
        -- sitting in the START menu with the overworld write checkpoint long behind them.
        if self.panel then
            local pok, perr = self.panel:service()
            if not pok then log("[SLink-gen1] panel: " .. tostring(perr)) end
        end
        net.pump()
        local connected = net.connected()
        -- hello only once the player is IN the game: the main menu already holds the save
        -- (MainMenu -> TryLoadSaveFile before the CONTINUE/NEW GAME choice) and a cleared WRAM
        -- holds nothing, so "party readable" is not enough — require the overworld checkpoint
        -- or a running battle (a reconnect mid-battle must not wait for it to end)
        if not connected then
            self.hello_sent = false
            if self.panel then self.panel:clear() end  -- rows outlive neither the link nor the save
        end
        if connected and not self.hello_sent and game_is_live()
           and (reads.read_battle().in_battle ~= 0 or safety.check(ws_profile, io)) then
            self:send_hello()
        end
        connected = connected and self.hello_sent
        if self.frame % Client.VALIDATE_EVERY == 0 then self:validate() end
        for _, sig in ipairs(self.signals and self.signals:drain() or {}) do
            local ok, err = pcall(self.on_signal, self, sig)
            if not ok then log("[SLink-gen1] signal " .. tostring(sig.kind) .. ": " .. tostring(err)) end
        end
        self:rival_window_tick()
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
        local tok, terr = pcall(self.trade_tick, self)
        if not tok then log("[SLink-gen1] trade: " .. tostring(terr)) end
        self:run_deferred()
    end

    function self:stop()
        if self.signals then self.signals:close() end
    end

    return self
end

return Client
