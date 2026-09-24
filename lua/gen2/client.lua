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
--   battle_hold    O-30: write_checkpoint.json battle_hold facts, the in-battle death site (before
--                  `call DetermineMoveOrder`); production composes it only behind a battle_faint receipt
--   battle_bench   O-32: true lands a BENCH death on receipt, at the battle frame end (Gen 1 battle_bench);
--                  production composes it only behind a receipt covering battle_bench (and battle_faint)
--   contest_mask   write_checkpoint.json contest_mask: the Bug-Catching Contest's party mask (ruling a)
--   net      lua/connector.lua      newline-JSON TCP (send/receive/pump/connected)
--   json/hud/io                     as Gen 1
--
-- Events come from the binder's latches only (capture, whiteout, PC ops, NPC trade,
-- evolution) or from a binder observation settled against one read (faint, battle start/end,
-- save, reset); nothing is inferred by polling. A binder refusal is logged once per reason. Writes happen only inside the armed permit at the
-- checkpoint. P4 native sound and SLINK trade are not here: those commands get the protocol's
-- "nothing happened" replies (handle_command) and request_sfx_local is the sound seam. The
-- native panel (P4.1f) is the optional p.panel (lua/gen2/panel.lua); nil means no panel. The
-- native SLINK TRADE (P4.3b) is the optional p.trade (lua/gen2/trade_overlay.lua) with its own
-- trade permit; without it (or off an advertising overlay) trade commands get the same replies.
local Client = { TICK_INTERVAL = 30, VALIDATE_EVERY = 60, MAX_INVALID = 5, MAX_PENDING_FRAMES = 600,
                 MAX_HELD = 64,
                 -- P4.3b: an armed PROMPT the player never picks up is withdrawn after this many frames
                 -- (fits inside the proposer's SLINK_TRADE_APPLY_FRAMES = 3600 hold with ~29 s left for the
                 -- YES/NO, patch/gen2/src/trade_service.asm; a waiting cartridge picks up an armed APPLY
                 -- within a frame, so this never gives up before the cartridge does)
                 TRADE_PICKUP_FRAMES = 1800 }

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
-- O-30: the write kind held at the battle hold (gen2_write_safety BATTLE_KINDS).
local BATTLE_FAINT = "battle_faint"
-- O-32: the receipt-time bench write kind (gen2_write_safety BENCH_KINDS), checked at a battle frame end.
local BATTLE_BENCH = "battle_bench"

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
    local phone = p.phone -- P4.5c phone calls: lua/gen2/phone.lua, or nil (no panel)
    local trade = p.trade -- P4.3b native SLINK TRADE: lua/gen2/trade_overlay.lua, or nil (no trade build)
    local c = profile.constants
    local arr = json.array -- tag lists so an empty one encodes as [] not {}

    local self = {
        player = p.player, rom_type = p.rom_type, rom_sha1 = p.rom_sha1,
        -- Gen 2: one pairing foundation for all three packs (O-16; gen2_gsc.py game_id)
        foundation = "gen2_gsc", artifact_kind = p.artifact_kind or "clean",
        -- P4.3b: the lease the cartridge is waiting on ({kind, gen, token, frame, ...}) and this
        -- visit's role/token, kept from the first command (trade_mask/show_menu) through APPLY
        trade = trade, trade_state = nil, trade_visit = nil,
        trade_owed = {}, -- trade_uncertain / withdraw_offer messages, sent in order once the hello is ready
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
        -- O-30, Gen 1 parity (lua/gen1/client.lua pending_battle_writes / arrivals / defer_held): deaths
        -- owed in battle wait for the next battle hold; `commanded` holds keys whose native faint is the
        -- echo of a death the server commanded (dropped once, never reported as a new faint).
        pending_battle_writes = {}, arrivals = 0, commanded = {},
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

    -- Gen 1 parity (lua/gen1/client.lua defer_held): a battle-held death handed to the checkpoint keeps
    -- its ARRIVAL position, so it never falls behind a later memorialize for the same key.
    local function defer_held(entry)
        entry.arrival = entry.arrival or self.arrivals
        for i, queued in ipairs(self.deferred) do
            if queued.arrival and queued.arrival > entry.arrival then
                table.insert(self.deferred, i, entry)
                return
            end
        end
        self.deferred[#self.deferred + 1] = entry
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
        -- O-30: a reset/reload leaves the battle; the owed deaths go to the checkpoint (Gen 1 battle_end)
        for _, w in ipairs(self.pending_battle_writes) do defer_held(w) end
        self.pending_battle_writes, self.commanded = {}, {}
        -- P4.3b: Init clears the lease on reset; a reload leaves the Trade Center. The hello resyncs.
        self:trade_forget("the " .. kind .. " boundary")
        -- review m2: a trade report held for the hello is lost with the timeline; the side cannot vouch
        for _, m in ipairs(self.held) do
            if m.event == "trade_done" and m.fields and m.fields.token then
                self.trade_owed[#self.trade_owed + 1] = { event = "trade_done",
                    fields = { token = m.fields.token, uncertain = true } }
            end
        end
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
        self.pending_battle_writes, self.commanded = {}, {}
        self:trade_forget(why)
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
    --
    -- `death` (the command name: force_faint/explode and memorialize, never the other box ops):
    -- a missing exact key falls back to the evolution-stable identity. Gen 2 sends no key_change
    -- for evolution (U1 OPEN), and EvolveAfterBattle both rewrites the species and adds the
    -- max-HP gain to a fainted mon's HP, so a death owed past the battle would otherwise escape
    -- (A2). The DV word + OT id
    -- (key fields 1-2) must name exactly one party mon, and its species must descend from the
    -- key's (evolutions.json), so a DV/OT collision never kills another mon.
    local evolutions = p.evolutions or {}
    local function descends(from, to)
        for _, nxt in ipairs(evolutions[string.format("%d", from)] or {}) do
            if nxt == to or descends(nxt, to) then return true end
        end
        return false
    end
    local function find_party_slot(key, death)
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
        if slot or not death then return slot, mon, party end
        local stable, old = target:sub(1, 9), tonumber(target:sub(11), 16)
        for _, m in ipairs(party.mons) do
            if not m.is_egg and mon_key(m):sub(1, 9) == stable then
                if mon then return nil, nil, party, "ambiguous evolved match" end
                mon = m
            end
        end
        if not mon then return nil, nil, party end
        if not (old and descends(old, mon.species_id)) then
            return nil, nil, party, "DV/OT match " .. mon_key(mon) .. " is not a descendant"
        end
        log("[SLink-gen2] " .. death .. " matched evolved " .. target .. "->" .. mon_key(mon))
        return mon.slot, mon, party
    end

    -- O-30 ruling (a): the Bug-Catching Contest hides every party mon but the lead
    -- (ContestDropOffMons) until ContestReturnMons; a death for a hidden mon waits for the return.
    local contest = p.contest_mask
    local function contest_masked()
        if not contest or io.bank_valid(contest.bank, contest.address, 1) ~= true then return false end
        return math.floor(io.read_u8(contest.address, "System Bus") / 2 ^ contest.bit) % 2 == 1
    end

    local function hud_color(cmd)
        if type(cmd.color) == "table" then return cmd.color[1], cmd.color[2], cmd.color[3], cmd.duration end
        return cmd.r, cmd.g, cmd.b, cmd.frames
    end

    -- The one native-SFX gate (P4.2b, Gen 1's shape): a server `play_sound` and every LOCAL cue
    -- request through this. panel:sfx_code_for maps the Gen 3 SE id on the wire to this
    -- cartridge's semantic code; an id with no Gen 2 sound is dropped silently, never sent. The
    -- panel's arbiter keeps one cue per frame (lua/sfx_arbiter.lua), so no per-frame set here.
    function self:request_sfx_local(gen3_id)
        local code = panel and panel:sfx_code_for(gen3_id)
        if panel and not code then return end
        if code and self.config and self.config.native_sounds == true and panel:sfx_present() then
            panel:request_sfx(code)
        elseif not self.sfx_unavailable_logged then
            self.sfx_unavailable_logged = true
            log("[SLink-gen2] play_sound: native sounds off or no SFX-capable SLink cartridge")
        end
    end

    function self:handle_command(cmd)
        local c_ = cmd.cmd
        if c_ == "noop" then return end
        -- P4.5c: an optional "phone" tag rides force_faint/msgbox; phone.lua drops it off a phone build
        if phone and cmd.phone ~= nil then phone:request(cmd.phone) end
        self.arrivals = self.arrivals + 1 -- Gen 1 parity: every command's arrival order (defer_held)
        if c_ == "force_faint" or c_ == "force_explode" then
            -- Gen 2: supports_explode_mode() is False; a stray explode is the bench faint.
            local slot, mon, party, why = find_party_slot(cmd.key, c_)
            if why then log("[SLink-gen2] " .. c_ .. ": " .. why .. " " .. tostring(cmd.key)) return end
            local entry = { cmd = c_, key = cmd.key, nickname = cmd.nickname, arrival = self.arrivals }
            -- a key not in the party is deferred, never dropped on receipt: ContestDropOffMons masks the
            -- party before ENGINE_BUG_CONTEST_TIMER is set and ContestReturnMons unmasks it after the flag
            -- is cleared (O-30 review MINOR-3); the checkpoint holds it through the contest or drops it
            if not party or not slot then self.deferred[#self.deferred + 1] = entry return end
            local battle = reads.read_battle()
            if battle and battle.mode ~= 0 then
                if p.battle_hold then
                    -- O-30 (Gen 1 pending_battle_writes): the death lands at the next battle hold,
                    -- active battler and bench alike; a battle that ends first hands it to the checkpoint.
                    -- O-32: a bench death lands this frame instead (land_bench_deaths, from frame_end)
                    self.pending_battle_writes[#self.pending_battle_writes + 1] = entry
                    self.bench_owed = true
                    return
                end
                if battle.active_slot == slot then
                    -- no battle hold composed (production before the battle_faint receipt): the
                    -- command waits for the checkpoint (protocol §5: deferred to battle end)
                    log("[SLink-gen2] " .. c_ .. " held for the checkpoint: no in-battle active faint composed " .. cmd.key)
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
            self.deferred[#self.deferred + 1] = { cmd = c_, key = cmd.key, nickname = cmd.nickname,
                                                  arrival = self.arrivals }
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
            -- a cue accepted under the old setting must not post after it
            if cmd.native_sounds ~= true and panel then panel:clear_sfx() end
        elseif c_ == "game_over" then
            self:request_sfx_local(26)
            hud.set_game_over()
            self.game_over = true
        elseif c_ == "rebuild_start" then
            hud.set_rebuilding(cmd.text)
        elseif c_ == "rebuild_done" then
            hud.clear_rebuilding()
        elseif c_ == "show_menu" and self:trade_live() and cmd.blob_hex and cmd.slot ~= nil then
            self:trade_prompt(cmd)
        elseif c_ == "apply_trade" and self:trade_live() then
            self:trade_apply(cmd)
        elseif c_ == "apply_prepare" then
            self:trade_prepare_answer(cmd)
        elseif c_ == "withdraw_trade" then
            self:trade_withdraw(cmd)
        elseif c_ == "trade_mask" and self:trade_live() then
            self:trade_answer_query(cmd.mask or 0)
        elseif c_ == "trade_offer_ack" and self:trade_live() then
            self:trade_answer_offer(cmd.ok == true, type(cmd.token) == "string" and cmd.token or nil)
        elseif c_ == "show_choices" or c_ == "show_menu" or c_ == "choose_mon" then
            ack_cancel(cmd) -- Gen 2: no picker; a native trade prompt needs the trade build (above)
        elseif c_ == "apply_trade" then
            -- Gen 2: no SLINK trade path on this cartridge: "nothing changed" with the pre-trade key (§5)
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

    -- ── in-game SLINK TRADE (P4.3b; O-27 D2-D4; Gen 1's shape, lua/gen1/client.lua trade_*) ──────
    -- The cartridge (patch/gen2/src/trade_*.asm) waits in the Trade Center for our lease bytes; the
    -- binder (p.trade) owns the frame, the staging and its own permit. Gen 2 differs from Gen 1:
    --   * ONE token per visit: minted at the query answer (proposer) or the PROMPT (responder) and
    --     reused through APPLY; the asm refuses an APPLY whose token is not the accepted one.
    --   * the role is the first command of the visit (trade_mask -> proposer, show_menu -> responder);
    --     there is no role byte.
    --   * the lease is owned, so a frame that changes before pickup, or closes without DONE, is the
    --     cartridge ending the visit (B, its own timeout, a reset): nothing was committed.
    -- Live only on a trade build (p.trade), an overlay kind, and a cartridge advertising the cap.
    local PROMPT, APPLY = 3, 5 -- gb_trade_lease commands
    function self:trade_live()
        return trade ~= nil and self.artifact_kind == "overlay" and trade:advertised()
    end
    local function hex_bytes(hex)
        local out = {}
        for pair in tostring(hex or ""):gmatch("%x%x") do out[#out + 1] = tonumber(pair, 16) end
        return out
    end
    local function new_token()
        local t = {}
        for i = 1, 4 do t[i] = math.random(1, 255) end
        return t
    end
    -- the cartridge waits <= SLINK_TRADE_QUERY/OFFER_FRAMES (600) for these answers: never hold them for a later hello
    local function send_now(event, fields)
        return self.hello_session:status().ready == true and send(event, fields)
    end
    local function traded(fn, what)
        local ok, a, b = pcall(fn)
        if not ok then a, b = nil, tostring(a) end
        if not a then log("[SLink-gen2] trade " .. what .. " refused: " .. tostring(b)) end
        return a, b
    end
    local function nothing_changed(token, slot, old_key, why)
        log("[SLink-gen2] apply_trade: " .. why .. "; nothing changed")
        send("trade_done", { token = token, slot = slot, new_key = old_key, new_species = 0 })
    end

    function self:trade_answer_query(mask)
        local st = self.trade_state
        if not st or st.kind ~= "query" then return end
        local token = new_token()
        if contest_masked() then mask = 0 end -- the cartridge refuses a contest trade (9805ac1c)
        local ok = traded(function() return trade:answer_query(st.gen, mask, token) end, "query answer")
        self.trade_state = nil
        self.trade_visit = (ok and mask ~= 0) and { role = "proposer", token = token } or nil
    end

    -- The server holds an offer until the partner answers; a proposer whose cartridge has left
    -- withdraws it (menu_result choice 0 under the ack's token), or the partner's YES would apply
    -- the partner side alone. Owed like trade_done: sent once the hello is ready (frame_end).
    local function withdraw_offer(server_token, why)
        log("[SLink-gen2] trade offer withdrawn: " .. why)
        self.trade_owed[#self.trade_owed + 1] = { event = "menu_result",
                                                  fields = { token = server_token, choice = 0, withdraw = true } }
    end

    function self:trade_answer_offer(accept, server_token)
        local st, visit = self.trade_state, self.trade_visit
        if not st or st.kind ~= "offer" then return end
        local ok = traded(function() return trade:answer_offer(st.gen, accept) end, "offer answer")
        self.trade_state = nil
        if ok and accept and visit then
            visit.slot, visit.accepted, visit.server_token = st.slot, true, server_token
        else
            self.trade_visit = nil
            -- the ack came after the cartridge's offer wait (SLINK_TRADE_OFFER_FRAMES): the server accepted, the game did not
            if accept and server_token then withdraw_offer(server_token, "the offer wait expired before the ack") end
        end
    end

    -- Responder: stage the proposer's mon and let the cartridge ask its own YES/NO.
    function self:trade_prompt(cmd)
        if contest_masked() then
            -- 9805ac1c: SlinkTradeCheckParty refuses during the Bug-Catching Contest; never arm it
            self.trade_visit = nil
            send("menu_result", { token = cmd.token, choice = 0 })
            return
        end
        local token = new_token()
        local gen = traded(function()
            return trade:arm(PROMPT, cmd.slot, token, { blob = hex_bytes(cmd.blob_hex) })
        end, "prompt arm")
        if not gen then
            self.trade_visit = nil
            send("menu_result", { token = cmd.token, choice = 0 })
            return
        end
        self.trade_visit = { role = "responder", token = token, slot = cmd.slot }
        self.trade_state = { kind = "prompt", gen = gen, token = cmd.token, frame = self.frame }
    end

    -- MAJOR-1 prepare round: before either side may commit, can THIS cartridge still take its APPLY?
    -- The checks trade_apply makes, moved ahead of both commits; nothing is staged. A side that
    -- cannot answers ok = false and forgets the visit (the server cancels both).
    function self:trade_prepare_answer(cmd)
        local visit = self.trade_visit
        local ok = self:trade_live() and visit ~= nil and visit.accepted == true and self.trade_state == nil
                   and find_party_slot(cmd.old_key) == visit.slot and not trade:closed()
        if not ok then self.trade_visit = nil end
        send("apply_ready", { token = cmd.token, ok = ok })
    end

    -- Both sides: stage the OTHER mon under the accepted visit token; the cartridge commits.
    function self:trade_apply(cmd)
        local visit = self.trade_visit
        local slot = find_party_slot(cmd.old_key)
        if not visit or not visit.accepted then
            return nothing_changed(cmd.token, slot or cmd.slot, cmd.old_key, "no accepted trade visit")
        end
        if slot == nil or slot ~= visit.slot then
            self.trade_visit = nil
            return nothing_changed(cmd.token, slot or cmd.slot, cmd.old_key, "old_key is not the visit's slot")
        end
        if trade:closed() then
            self.trade_visit = nil
            return nothing_changed(cmd.token, slot, cmd.old_key, "the cartridge already left the Trade Center")
        end
        local gen = traded(function()
            return trade:arm(APPLY, slot, visit.token, { blob = hex_bytes(cmd.blob_hex),
                                                         partner_name = cmd.partner_name })
        end, "apply arm")
        if not gen then
            self.trade_visit = nil
            return nothing_changed(cmd.token, slot, cmd.old_key, "apply arm refused")
        end
        self.trade_state = { kind = "apply", gen = gen, token = cmd.token, old_key = cmd.old_key, slot = slot,
                             frame = self.frame }
    end

    -- An entered native commit that never published DONE may have mutated or saved: Gen 1's result-2
    -- handling (no release, no key claim). It is DECLARED, trade_done{token, uncertain = true}, once
    -- the hello is ready (after a reset: the post-reset hello, frame_end); the server journals it and
    -- that side's next party snapshot settles the link, instead of the applying watchdog.
    -- Mirrored by lua/gen1/client.lua trade_uncertain.
    -- after_reset (MAJOR-5): a native result 2 holds until a reset, and its RAM party was never
    -- saved; the server then takes evidence only from the reloaded save (the post-reset hello).
    local function trade_uncertain(st, why, after_reset)
        hud.show("TRADE UNCERTAIN - CHECK PARTY", 255, 64, 64, 600)
        log("[SLink-gen2] apply_trade uncertain: " .. why .. "; no release, no key claim")
        if st.declared then return end
        st.declared = true
        self.trade_owed[#self.trade_owed + 1] = { event = "trade_done",
            fields = { token = st.token, uncertain = true, after_reset = after_reset or nil } }
    end
    function self:trade_forget(why)
        local st, visit = self.trade_state, self.trade_visit
        if st and st.kind == "apply" and trade and trade.committing then trade_uncertain(st, tostring(why))
        elseif st and st.kind == "apply" then
            -- review m2: before SlinkTradeCommit nothing was mutated or saved: a certain none, owed
            log("[SLink-gen2] apply_trade forgotten before the commit entry (" .. tostring(why) .. "); nothing changed")
            self.trade_owed[#self.trade_owed + 1] = { event = "trade_done",
                fields = { token = st.token, slot = st.slot, new_key = st.old_key, new_species = 0 } }
        elseif st and st.kind == "prompt" then
            self.trade_owed[#self.trade_owed + 1] = { event = "menu_result", fields = { token = st.token, choice = 0 } }
        elseif not st and visit and visit.server_token then withdraw_offer(visit.server_token, tostring(why)) end
        self.trade_state, self.trade_visit = nil, nil
    end

    local trade_end
    -- MAJOR-4 (review e9d5e136): the server asks a silent side to withdraw its APPLY. Unpicked: pull
    -- it and report nothing changed (certain). Past the commit entry: uncertain. Picked up but not
    -- committing yet: the cartridge answers on its own (DONE or a close) within frames.
    -- Mirror of lua/gen1/client.lua trade_withdraw.
    function self:trade_withdraw(cmd)
        local st = self.trade_state
        if not (trade and st and st.kind == "apply" and st.token == cmd.token) then return end
        if trade.phase == "armed" then
            traded(function() trade:withdraw() return true end, "withdraw")
            return trade_end(st, "the server withdrew the unpicked APPLY")
        end
        if trade.committing then trade_uncertain(st, "the server asked for a withdrawal") end
    end

    function trade_end(st, why)
        if st.kind == "prompt" then
            log("[SLink-gen2] trade prompt ended: " .. why)
            send("menu_result", { token = st.token, choice = 0 })
        else
            nothing_changed(st.token, st.slot, st.old_key, why)
        end
        self.trade_state, self.trade_visit = nil, nil
    end

    -- Per-frame: watch the lease for the receptionist questions and the native completions.
    function self:trade_tick()
        if not self:trade_live() then return end
        local st = self.trade_state
        if st and (st.kind == "prompt" or st.kind == "apply") then
            local done = trade:poll_done()
            if not done then
                if trade:clobbered() or trade:closed() then
                    if st.kind == "apply" and trade.committing then
                        return self:trade_forget("the visit ended after SlinkTradeCommit was entered")
                    end
                    -- before the commit entry the asm refused (precommit checks) or timed out
                    return trade_end(st, "the cartridge ended the visit")
                end
                if trade.phase == "armed" and self.frame - st.frame > Client.TRADE_PICKUP_FRAMES then
                    traded(function() trade:withdraw() return true end, "withdraw")
                    return trade_end(st, "never picked up (timeout)")
                end
                return
            end
            if st.kind == "prompt" then
                local released = traded(function() return trade:release(st.gen) end, "prompt release")
                local yes = done.result == 0 and released == true
                send("menu_result", { token = st.token, choice = yes and 1 or 0 })
                if yes then self.trade_visit.accepted = true else self.trade_visit = nil end
                self.trade_state = nil
                return
            end
            if done.result == 2 then
                -- native append uncertain (T-5 limit): the cartridge keeps the lease; no release, no claim
                if not st.warned then
                    st.warned = true
                    trade_uncertain(st, "native result 2; holding until a reset", true)
                end
                return
            end
            traded(function() return trade:release(st.gen) end, "apply release")
            local party = done.result == 0 and current_party() or nil
            local received = party and party.mons[#party.mons]
            if received and not received.is_egg then
                -- REMOVE+compact then APPEND: the received (possibly evolved) mon is the last slot
                send("trade_done", { token = st.token, slot = received.slot, new_key = mon_key(received),
                                     new_species = received.species_id })
            else
                nothing_changed(st.token, st.slot, st.old_key, "native result " .. tostring(done.result))
            end
            self.trade_state, self.trade_visit = nil, nil
            self.pending_rescan = true
            return
        end
        local visit = self.trade_visit
        if not st and visit and visit.server_token and trade:closed() then
            -- SLINK_TRADE_APPLY_FRAMES ran out (or B) before the APPLY: the proposer left its offer
            self.trade_visit = nil
            return withdraw_offer(visit.server_token, "the cartridge left before APPLY")
        end
        local q = trade:poll_query()
        if q and not (st and st.kind == "query" and st.gen == q.gen) then
            self.trade_state, self.trade_visit = { kind = "query", gen = q.gen }, nil
            if not send_now("trade_query", {}) then
                traded(function() return trade:answer_query(q.gen, 0, new_token()) end, "offline query answer")
                self.trade_state = nil
            end
            return
        end
        local o = trade:poll_offer()
        if o and not (st and st.kind == "offer" and st.gen == o.gen) then
            self.trade_state = { kind = "offer", gen = o.gen, slot = o.slot }
            if not send_now("trade_offer", { slot = o.slot }) then
                traded(function() return trade:answer_offer(o.gen, false) end, "offline offer answer")
                self.trade_state, self.trade_visit = nil, nil
            end
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
        local slot, mon, _, why = find_party_slot(cmd.key, cmd.cmd)
        if not slot and not why and contest_masked() then
            -- ruling (a): kill on return; the hidden mon is back at the first checkpoint after
            -- ContestReturnMons (tail requeue, bounded by the contest itself)
            if not cmd.contest_logged then
                cmd.contest_logged = true
                log("[SLink-gen2] " .. cmd.cmd .. " held until the contest returns the party " .. tostring(cmd.key))
            end
            self.deferred[#self.deferred + 1] = cmd
            return
        end
        if not slot then
            -- the mon left the party before the checkpoint (PC deposit) or its key is ambiguous
            log("[SLink-gen2] " .. cmd.cmd .. " dropped at the checkpoint: " .. (why or "key not in party")
                .. " " .. tostring(cmd.key))
            return
        end
        -- the re-zero behind a landed battle write (O-30): a mon still at HP 0 needs nothing more
        if cmd.quiet and mon.hp == 0 then return end
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
        if ok and cmd.quiet then
            -- EvolveAfterBattle's max-HP gain or the Battle Tower's reload revived it: dead stays dead
            log("[SLink-gen2] re-zeroed a revived dead mon " .. cmd.key .. " -> " .. mon_key(mon))
        elseif ok then
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
        -- O-30: a memorial follows the dead mon through an evolution like its force_faint did
        local _, mon = find_party_slot(cmd.key, cmd.cmd == "memorialize" and cmd.cmd or nil)
        if mon and cmd.cmd == "memorialize" then phys = mon_key(mon) end
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
            self.bench_owed = true -- O-32: a death deferred before the battle lands at its first frame
            if self.battle.resolves and self.has_pokeballs and self.seeded and area_id ~= ""
               and not self.resolved_areas[area_id] then
                hud.show("** NEW ENCOUNTER **\n" .. name, 255, 220, 60, 360)  -- area on its own line, as Gen 1
                self:request_sfx_local(25)
            end
        elseif k == "trainer_ready" then
            -- Gen 2: no trainer_battle_start: the (class, id) pair has no agreed single-int
            -- packing (gen2_gsc.trainer_info) and rival_trainer_ids() is empty
            self.battle = { wild = false }
            self.bench_owed = true -- O-32: as wild_ready
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
            -- Gen 1 parity: a battle write that never reached a battle hold (the battle ended first,
            -- a link battle) is still owed: the checkpoint zeroes it
            for _, w in ipairs(self.pending_battle_writes) do defer_held(w) end
            -- an echo that never came (the binder refused the observation) must not eat a later faint
            self.pending_battle_writes, self.commanded = {}, {}
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
            if self.commanded[m.key] then
                -- O-30: HandlePlayerMonFaint after our own battle write; the server commanded this death
                self.commanded[m.key] = nil
                log("[SLink-gen2] faint echo of a commanded death dropped " .. m.key)
                return
            end
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
            -- P4.1f panel / P4.2b sound: per CARTRIDGE, only a live SLink build with the cap bit.
            panel = panel and panel:present() or false, panel_abi = panel and panel:abi() or 0,
            sfx = panel and panel:sfx_present() or false,
            -- MAJOR-1 (review e9d5e136): this client answers apply_prepare before any APPLY
            trade_prepare = self:trade_live(),
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
            -- the contest-masked party refuses any trade (9805ac1c): the server offers none meanwhile
            trade_blocked = contest_masked(),
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
        if p.battle_hold and not self.battle_hook then
            self.battle_hook = io.on_bus_exec(function()
                local ok, err = pcall(self.at_battle_hold, self)
                if not ok then log("[SLink-gen2] battle hold: " .. tostring(err)) end
            end, p.battle_hold.execution_before.pc, "SLink-gen2-battle-hold", "System Bus")
        end
        if trade and not self.trade_hooks then
            -- P4.3b: SlinkTradePromptEntry / SlinkTradeApplyPickup run BEFORE the cartridge writes
            -- the ACK; from pickup the frame is the cartridge's and clobber checks stop (Lease:picked_up).
            -- SlinkTradeCommit latches the native commit entry (trade_overlay commit_entered).
            self.trade_hooks = {}
            for label, site in pairs(trade.hooks) do
                self.trade_hooks[#self.trade_hooks + 1] = io.on_bus_exec(function()
                    if io.read_u8(profile.ram.hROMBank, "System Bus") ~= site.bank then return end
                    local ok, err = pcall(site.on, trade)
                    if not ok then log("[SLink-gen2] trade pickup: " .. tostring(err)) end
                end, site.addr, "SLink-gen2-trade-" .. label, "System Bus")
            end
        end
    end

    -- O-30, mirroring lua/gen1/client.lua on_battle_loop_head: inside the synchronous CPU hold before
    -- `call DetermineMoveOrder` (the player committed this turn), land every owed death. Gen 2 differs
    -- in the site (Gen 2 has no HP test at its loop head) and in W-2's action suppression (USEITEM, not
    -- CANNOT_MOVE; lua/gen2/writes.lua). Link battles never write (the other Game Boy would desync).
    local transformed_bit = p.battle_hold and p.battle_hold.transformed_bit
    -- O-30 review MAJOR-1/2 (Gen 1 on_battle_loop_head lifts the same way): a death deferred before the
    -- battle (a script window refused the checkpoint) and a quiet re-zero whose mon was revived with no
    -- checkpoint between battles (Battle Tower: HealParty/LoadPokemonData around every StartBattle,
    -- battle_tower.asm:228-235, inside one Script_BattleRoomLoop) both land at this hold, not at battle end.
    local function lift_deferred_deaths()
        local stay = {}
        for _, e in ipairs(self.deferred) do
            local slot, mon
            if e.cmd == "force_faint" or e.cmd == "force_explode" then slot, mon = find_party_slot(e.key, e.cmd) end
            if slot and not (e.quiet and mon.hp == 0) then
                self.pending_battle_writes[#self.pending_battle_writes + 1] = e
            else
                stay[#stay + 1] = e
            end
        end
        self.deferred = stay
    end
    function self:at_battle_hold()
        if (#self.pending_battle_writes == 0 and #self.deferred == 0) or not self.writes_enabled then return end
        -- a bus-exec hit at this PC in another ROM bank is not BattleTurn: cheapest refusal first
        if io.read_u8(profile.ram.hROMBank, "System Bus") ~= p.battle_hold.execution_before.bank then return end
        if not safety.check(BATTLE_FAINT) then return end
        -- an unreadable party keeps the queue (Gen 1: "gone" and "not readable yet" look alike)
        if not current_party() then return end
        local battle, link = reads.read_battle(), wram_byte("wLinkMode")
        if not battle or battle.mode == 0 or link ~= 0 then return end
        lift_deferred_deaths()
        if #self.pending_battle_writes == 0 then return end
        local targets = p.battle_hold.write.targets
        local function target(name)
            local t = targets[name]
            if io.bank_valid(t.bank, t.address, 1) ~= true then return nil end
            return io.read_u8(t.address, "System Bus")
        end
        local snapshot = { mode = battle.mode, battle_type = battle.battle_type,
                           active_slot = battle.active_slot, link_mode = link }
        local keep = {}
        for _, w in ipairs(self.pending_battle_writes) do
            local slot, mon, _, why = find_party_slot(w.key, w.cmd)
            local landed, err = false, nil
            if why then
                log("[SLink-gen2] battle write dropped: " .. why .. " " .. tostring(w.key))
            elseif not slot then
                defer_held(w) -- a contest-hidden or departed mon: the checkpoint decides
            elseif slot == battle.active_slot then
                -- Gen 1 active_faint_guard: the battle struct must be this slot's (Transform excepted)
                local species, sub5 = target("wBattleMonSpecies"), target("wPlayerSubStatus5")
                local transformed = sub5 ~= nil and math.floor(sub5 / 2 ^ transformed_bit) % 2 == 1
                if species == mon.species_id or transformed then
                    local ok, e = pcall(function()
                        writes:arm("battle_hold")
                        writes:faint_active_battler(slot, snapshot)
                    end)
                    writes:disarm()
                    landed, err = ok, e
                else
                    keep[#keep + 1] = w
                end
            elseif mon.hp == 0 then
                -- Gen 1 parity (NIT-7): a bench mon already fainted needs no write, KO line or re-zero
                log("[SLink-gen2] battle write skipped: already at HP 0 " .. tostring(w.key))
            else
                local ok, e = pcall(function()
                    writes:arm("battle_hold")
                    writes:faint_party_slot(slot, snapshot)
                end)
                writes:disarm()
                landed, err = ok, e
            end
            if landed then
                -- only the active battler runs HandlePlayerMonFaint (the echo); a bench write has none
                if slot == battle.active_slot then self.commanded[mon_key(mon)] = true end
                if w.quiet then
                    log("[SLink-gen2] re-zeroed a revived dead mon in battle " .. w.key .. " -> " .. mon_key(mon))
                else
                    hud.show("!! " .. nick_label(w.key, w.nickname or mon.nickname) .. " KO'd", 255, 80, 80, 360)
                end
                -- dead stays dead: EvolveAfterBattle and the Battle Tower reload can revive it (facts doc §2)
                defer_held({ cmd = "force_faint", key = w.key, nickname = w.nickname, arrival = w.arrival, quiet = true })
            elseif err ~= nil then
                log("[SLink-gen2] battle write refused: " .. tostring(err) .. " " .. tostring(w.key))
                keep[#keep + 1] = w
            end
        end
        self.pending_battle_writes = keep
    end

    -- O-32 (Gen 1 handle_command: a benched mon dies the frame the command arrives, owner 2026-09-22 "so it
    -- can never be switched in"): at the battle frame end after the command's receipt, never inside a CPU
    -- hold (gen2_write_safety evaluate_frame). Frame end is the game's DelayFrame boundary: every in-battle
    -- read of a bench mon's party HP is a live read (CheckIfCurPartyMonIsFitToFight, C engine/battle/
    -- core.asm:3650-3656, from TryPlayerSwitch :5176 and PickPartyMonInBattle :2852-2860; the party list
    -- only draws it), so a death landed first refuses the switch. The entry stays queued, as Gen 1 keeps it:
    -- a switch already past that check (TryPlayerSwitch :5176-5192 -> BattleMonEntrance -> InitBattleMon
    -- :5249-5271, frames apart) is the active battler at the next hold and dies there by W-2 before it acts;
    -- a revival by GiveExperiencePoints (fainted test :7004, level-up HP gain after the exp text :7121-7240;
    -- G :6764/:6881-6990) is lifted by the quiet re-zero every landing leaves. A refused frame (an
    -- animation's SVBK, the permit, the evaluation) retries the next one. Link battles never write (O-30).
    function self:land_bench_deaths()
        if not self.bench_owed or not p.battle_bench or not self.writes_enabled then return end
        local battle, link = reads.read_battle(), wram_byte("wLinkMode")
        if not battle or link == nil then return end
        if battle.mode == 0 or link ~= 0 then self.bench_owed = false return end
        if not safety.check(BATTLE_BENCH) or not current_party() then return end
        self.bench_owed = false
        lift_deferred_deaths()
        local snapshot = { mode = battle.mode, battle_type = battle.battle_type,
                           active_slot = battle.active_slot, link_mode = link }
        for _, w in ipairs(self.pending_battle_writes) do
            local slot, mon, _, why = find_party_slot(w.key, w.cmd)
            if not w.landed and slot and not why and slot ~= battle.active_slot and mon.hp > 0 then
                local ok, err = pcall(function()
                    writes:arm(BATTLE_BENCH)
                    writes:faint_party_slot(slot, snapshot)
                end)
                writes:disarm()
                if ok then
                    if w.quiet then
                        log("[SLink-gen2] re-zeroed a revived dead mon on receipt " .. w.key .. " -> " .. mon_key(mon))
                    else
                        log("[SLink-gen2] bench write landed on receipt: slot " .. slot .. " " .. tostring(w.key))
                        hud.show("!! " .. nick_label(w.key, w.nickname or mon.nickname) .. " KO'd", 255, 80, 80, 360)
                    end
                    -- still queued (landed, quiet): the hold settles a switch-in that beat the write
                    w.landed, w.quiet = true, true
                    defer_held({ cmd = "force_faint", key = w.key, nickname = w.nickname, arrival = w.arrival, quiet = true })
                else
                    self.bench_owed = true
                    if not w.bench_refused then
                        w.bench_refused = true
                        log("[SLink-gen2] bench write refused on receipt, retried: " .. tostring(err) .. " " .. tostring(w.key))
                    end
                end
            end
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
        if phone then -- P4.5c: after the panel refreshed freshness this frame
            local pok, perr = pcall(phone.service, phone)
            if not pok then log("[SLink-gen2] phone: " .. tostring(perr)) end
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
        if connected and #self.trade_owed > 0 then -- trade_uncertain / withdraw_offer, after any held messages
            local owed = self.trade_owed
            self.trade_owed = {}
            for _, m in ipairs(owed) do send(m.event, m.fields) end
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
        if trade then
            local tok, terr = pcall(self.trade_tick, self)
            if not tok then log("[SLink-gen2] trade: " .. tostring(terr)) end
        end
        self.replies:step()
        self:land_bench_deaths() -- O-32: a bench death lands the frame its command arrived (replies:step)
        self:run_deferred()
    end

    function self:stop()
        if self.checkpoint_hook then io.unregister(self.checkpoint_hook); self.checkpoint_hook = nil end
        if self.battle_hook then io.unregister(self.battle_hook); self.battle_hook = nil end
        for _, id in ipairs(self.trade_hooks or {}) do io.unregister(id) end
        self.trade_hooks = nil
        if self.signals then self.signals:close() end
    end

    return self
end

return Client
