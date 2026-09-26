-- lua/gen3/client.lua -- the Gen 3 driver over the shared core (P4 C4-2b).
--
-- Client.new(p) builds the game driver (docs/gen3/research/p4_gen1_contract_map.md §3.2) and
-- returns lua/core/session.lua's Session over it: the Gen 1 constructor shape. It is
-- pack-neutral: gen3_frlg (firered/leafgreen) and gen3_rr (radical_red, clean and companion)
-- differ only in profile data and capability flags (which addresses the pack pins), never in
-- a title branch. No BizHawk global is named here; every byte arrives through p.io and every
-- write goes through p.writes (the armed sink) or p.boxes (which arms the same sink).
--
-- Parts (all injected by lua/gen3/entry.lua production mode):
--   reads (instance) + R (the reads module, for record geometry), profile, sites, Signals,
--   writes, boxes (optional), policy (snapshot/check(snap, reason): "overworld" is the
--   G3-signed checkpoint; "battle_faint"/"battle_commit" are the C4-B battle predicate seam),
--   net, hud, json, io, ev, area_map, locations, player, rom_type, rom_sha1, foundation,
--   artifact_kind, log, core = { Session, Identity, Deferred }, native (optional; P5).
--
-- The optional native part (lua/gen3/native.lua, the RR companion mailbox) arrives as p.native:
-- Entry builds ONE instance and hands it to the client, Safety's native_idle and (through it)
-- the write policy, so all three see the same mailbox. Every seam below calls it when present
-- and otherwise does what the old client did without the patch. Native POSTING is gated on the
-- session (S:eligible(): writes enabled, hello'd, connected): the client wraps the injected
-- write policy so that every arm of reason "native" or "sound" is also refused while the
-- session is ineligible. native:service() still runs every frame, so ACK polling never stops;
-- a refused arm leaves the job queued (native.lua dispatch returns nil), it is not dropped.
--   native:service()               each frame before the net pump
--   native:idle() -> bool          the safety checkpoint's "native" clause
--   native:hello_fields() -> table merged into hello (panel/sfx capabilities)
--   native:replace_rival_team(cmd) / show_menu(cmd) / show_choices(cmd) / choose_mon(cmd) /
--   link_panel(cmd) / config(cmd) / play_sound(id) / transfer(step, args, done) (the trade FSM
--   trade.lua owns prepare/apply/withdraw, milestones, readback and owed completion)
--
-- Reducer model (the Gen 1 rule, lua/gen1/client.lua:14-17): events are derived from engine
-- signals, never from polling. A signal marks WHAT kind of change the engine made this frame;
-- the settle pass after the drain reads the party (and the boxes when storage moved) once and
-- diffs it against the last snapshot. The site register points are not interpreted, because
-- their meanings differ per artifact and the packs do not carry register roles yet
-- (docs/gen3/research/site_capture_points.md): a register-free diff is identical on both packs.
-- Vocabulary: tools/gen3_shadow_diff.py KINDS; folding: capture_wild + mon_given in one
-- settle -> one capture; SendMonToPC (pc_move) is acquisition to storage, not a user deposit.
local Client = {}

-- Record geometry and game constants the packs do not ship yet (requested from C4-2a), the same
-- on every admitted title: pret/pokefirered@c75f352 include/pokemon.h struct Pokemon / struct
-- BattlePokemon and the old client's production values (archive/gen3-old-client:lua/memory_gba.lua:395-416);
-- CFRU keeps the same layout, and so does pret/pokeemerald@c65e93f2 (include/pokemon.h:219-231 hp
-- at 0x56, :268 moves, :281 pp; include/constants/moves.h:157; include/battle.h:27).
local PARTY_HP_OFF = 0x56            -- struct Pokemon.hp (u16)
local BATTLE_MON_MOVES_OFF = 0x0C    -- BattlePokemon.moves[4] (u16 each)
local BATTLE_MON_PP_OFF = 0x24       -- BattlePokemon.pp[4] (u8 each)
local MOVE_EXPLOSION = 153           -- include/constants/moves.h
local EXPLODE_PP = 5                 -- Explosion's PP, so a PP drop proves the move executed
-- CFRU action-commit values (archive/gen3-old-client:lua/memory_gba.lua:1318-1345, production-tested on RR):
local B_ACTION_USE_MOVE = 0
local TARGET_FOE_PRIMARY = 1
-- (the committed state, STATE_WAIT_ACTION_CONFIRMED_STANDBY, is per title: p.commit_guard.value)
-- The m4a SE1 poke (the old client's M.playSE, archive/gen3-old-client:lua/memory_gba.lua:2021-2066, production-tested
-- on FR/LG and RR). Every address, field offset and title SE id (se_ids) comes from the checkpoint pack's sound block
-- (p.sound: player_se1 / sound_info_ptr, player_head_off / player_next_off / tracks_off, and
-- `fields`, the exact m4a fields a sound write may touch); only the VALUES the old client
-- stores are here.
local TRK_START = 0xC0                        -- MusicPlayerTrack.flags: EXIST | START
local TRK_BEND, TRK_VOLX, TRK_LFO = 2, 64, 22 -- the old client's per-track defaults
local PC_KINDS = { pc_deposit = true, pc_withdraw = true, pc_box_place = true,
                   pc_release_begin = true, pc_release = true }
local MENU_CMDS = { "show_menu", "show_choices", "choose_mon" }

local function hex_of(bytes)
    local out = {}
    for i = 1, #bytes do out[i] = string.format("%02X", bytes[i]) end
    return table.concat(out)
end
-- json null decodes to a table sentinel: only a number is an address
local function num(v) return type(v) == "number" and v or nil end

function Client.new(p)
    local reads, R, profile = assert(p.reads, "reads"), assert(p.R, "R"), assert(p.profile, "profile")
    local writes, policy, boxes = assert(p.writes, "writes"), assert(p.policy, "policy"), p.boxes
    local json, hud, io, native = assert(p.json, "json"), assert(p.hud, "hud"), assert(p.io, "io"), p.native
    local core = assert(p.core, "core")
    local trade
    local owed = p.owed_reports and p.owed_reports.new() or nil
    local a, d = profile.ram, profile.derived
    local arr = json.array
    local area_map, locations = p.area_map or {}, p.locations or {}
    local sink = p.log or function() end
    local TAG = "[SLink-gen3]"
    local function log(msg) sink(TAG .. " " .. msg) end
    -- E3-CLIENT: title facts come from the pack, never FR literals, and a missing one fails
    -- closed (logged once, here). STANDBY is this title's STATE_WAIT_ACTION_CONFIRMED_STANDBY
    -- (battle.commit_guard.value: FR/LG/RR 3, Emerald 4); without it no battle commit is written.
    local STANDBY = type(p.commit_guard) == "table" and num(p.commit_guard.value) or nil
    if not STANDBY then log("pack has no battle.commit_guard.value: battle commits refused") end
    -- Gift areas (the pack's gift_areas.ids): no NEW ENCOUNTER banner and never a no_catch there.
    -- Without the list EVERY area counts as one: an area is never dead-zoned on a guess.
    local gift_area
    do
        local ids = type(p.gift_areas) == "table" and p.gift_areas.ids
        local set = ids and json.kind(ids) == "array" and {} or nil
        for _, id in ipairs(set and ids or {}) do
            -- a non-string or empty id would build a set nothing matches (fail OPEN): the whole
            -- list is untrusted then, and takes the missing-list fallback
            if type(id) ~= "string" or id == "" then set = nil; break end
            set[id] = true
        end
        if set then
            gift_area = function(id) return set[id] == true end
        else
            log("pack has no valid gift_areas.ids: every area treated as a gift area (no banner, no no_catch)")
            gift_area = function() return true end
        end
    end
    local key = reads.key
    local session
    local function send(event, fields) return session.send(event, fields) end
    local function eligible() return session ~= nil and session:eligible() end
    -- The BLOCKER gate (C4-2d): native and sound arms need an eligible session. Wrapping the
    -- injected policy covers every arm made through the one sink, including a job native.lua
    -- queued while eligible and tries to post after a pause.
    local base_check = policy.check
    function policy:check(snapshot, reason, args)
        if (reason == "native" or reason == "sound") and not eligible() then
            return false, "session not eligible for " .. reason .. " writes (paused, not hello'd or disconnected)"
        end
        return base_check(self, snapshot, reason, args)       -- args reach the clause sets
    end

    -- battle request identity (docs/protocol.md, card C5-10): a client-SESSION NONCE minted once
    -- per client process, plus a per-battle counter bumped on every battle-begin signal. Both
    -- ride on trainer_battle_start; the server stores and echoes both on replace_rival_team, and
    -- the command seam below refuses anything that is not this session's current battle.
    --
    -- The nonce is what makes a restart safe: a bare counter would collide across sessions
    -- (session A's battle 1 and a restarted session B's battle 1 are both 1, so a command the
    -- server queued for A and delivered late would pass in B). A reconnect inside one process
    -- keeps both; only a real restart re-mints the nonce.
    --
    -- The seed arrives from the bootstrap (lua/gen3/run.lua, which owns the BizHawk-facing
    -- entropy) through Entry, or from $SLINK_GEN3_BATTLE_NONCE for a harness that needs
    -- determinism. Anything else -- absent, non-hex, longer than the wire's 16 chars -- means NO
    -- identity: there is no local draw (C5-11c MAJOR 5), because a guessable session is exactly
    -- what the per-install counter exists to prevent.
    local session_nonce
    do
        local seed = p.battle_nonce_seed
        -- NO fallback (Codex C5-10 review, restated C5-11c): without a usable seed this client
        -- mints NO identity, declares no capability, and refuses every rival command -- fail
        -- closed, never a guessable session.
        if type(seed) == "string" and seed:match("^%x+$") and #seed <= 16 then
            session_nonce = seed
        else
            session_nonce = nil
        end
    end
    local battle_seq = 0
    -- RIVAL AUTHORITY (C5-11c BLOCKER 2). The battle that may accept a rival swap, as the immutable
    -- {session, battle_id, trainer_id} triple. It is opened when this client ANNOUNCES a battle
    -- (note_battle) and closed SYNCHRONOUSLY when a lifecycle boundary signal is CAPTURED -- the
    -- signals layer runs the on_fire handlers at the fire (lua/gen3/signals.lua:121-122), i.e.
    -- before the frame's drain and before pre_pump services native. That is deliberately separate
    -- from st.battle: a same-frame battle_end + battle_begin (same trainer) never touches the
    -- reducer's lifecycle, so a job queued behind a menu cannot ride it into the next battle, and
    -- the boundary sweep that used to clear st.battle (and made finish_battle skip the encounter
    -- result) is gone.
    --
    -- It is only as good as the signals that close it (C5-11d): a reset (drv.on_reset) revokes it,
    -- and so does a signal source that stopped delivering -- see live_authority below.
    local rival_authority = nil
    local sig_src = nil          -- the signal source drv.start armed; its health gates the authority
    local st = {
        known = {},        -- every key this save has shown us (party + boxes): acquisitions are NEW keys
        alive = {},        -- keys last seen with hp > 0: a faint is alive -> hp 0 at a faint site
        commanded = {},    -- keys WE zeroed: their faint is not reported (old client force_fainted_keys)
        party_prev = {},   -- key -> { slot, level, max_hp } at the last settle (PC diff baseline)
        carried = {},      -- keys that left the party into the PC cursor, not yet placed
        box_cache = {}, boxes_ok = false, box_generation = 0,
        battle = nil,      -- battle_begin .. battle_end lifecycle
        frozen = false,    -- a borrowed party is in RAM
        flags = {},        -- what the signals of this frame said changed
        has_pokeballs = false, last_area = nil, trade = nil, sound_frame = nil, sound_logged = {},
        baselined = false, seen_count = nil, observe_at = nil,
        trade_apply = nil, trade_settle_until = 0,
        trade_unresolved = {},   -- token-bound uncertainty journal; never upgraded from RAM alone
        trade_limits = { settle = 30 },
        bframe = nil, bcache = nil,
    }

    -- ── reads (tolerant: a read the pack cannot make yet degrades the field, not the client)
    local function call(name, ...)
        local f = reads[name]
        if not f then return nil, "reads." .. name .. " is not built" end
        return f(...)
    end
    local function party_read(occupied) return call("read_party", occupied) end
    local function trainer() local t = call("read_trainer") return type(t) == "table" and t or nil end
    local function area_now()
        local l = call("read_location")
        if type(l) ~= "table" then return "", "" end
        local k = tostring(l.map_group) .. ":" .. tostring(l.map_num)
        return area_map[k] or "", locations[k] or ""
    end
    local function badges()
        local b = call("read_badges")
        if type(b) == "table" then b = b.mask or b.badges end
        return num(b)
    end
    local function ball_count()
        local b = call("read_balls")
        if type(b) ~= "table" then return nil end
        return num(b.ball_count or b.count)
    end
    -- read_battle decodes the enemy party: once per frame
    local function battle_now()
        local f = io.framecount()
        if st.bframe ~= f then
            st.bframe = f
            local b = call("read_battle")
            st.bcache = type(b) == "table" and b or false
        end
        return st.bcache or nil
    end
    local function in_battle()
        local b = battle_now()
        if b and b.in_battle ~= nil then return b.in_battle == true end
        return st.battle ~= nil
    end
    local function party_hp_addr(slot)
        local base = reads.party_base and reads.party_base()
        return base and base + slot * R.PARTY_MON_SIZE + PARTY_HP_OFF or nil
    end
    -- player-side battlers are positions 0 and (doubles) 2 (reads.lua read_battle)
    local function battler_of(b, slot)
        local idx = b and b.battler_party_indexes or {}
        if idx[1] == slot then return 0 end
        if (b and b.battlers_count or 0) >= 4 and idx[3] == slot then return 2 end
        return nil
    end

    -- ── wire shapes ────────────────────────────────────────────────────────────────
    -- `active` and stat_stages ride a battler's entry (docs/protocol.md §4.1, old client parity)
    -- only while gBattleMons[battler] holds that very mon (reads.battler_holds: in a switch the
    -- party index moves before the mon is copied in, so the index alone would pin the outgoing
    -- mon's stages on the incoming one). No stages at all in a link battle, nor while the pack
    -- cannot say it is not one: there battler ids are not positions (pret
    -- battle_controllers.c:151-168). Returns active, stages.
    local function stages_of(b, battler, m)
        if not battler or call("battler_holds", battler, m) ~= true then return false, nil end
        local s = b and b.is_link == false and call("read_stat_stages", battler)
        return true, type(s) == "table" and arr(s) or nil
    end
    local function party_entry(m, active, b)
        local base = reads.party_base and reads.party_base()
        local raw = base and io.read_bytes(base + m.slot * R.PARTY_MON_SIZE, R.PARTY_MON_SIZE)
        local held, stages = stages_of(b, active[m.slot], m)
        return { key = key(m), slot = m.slot, species_id = m.species, nickname = m.nickname,
                 level = m.level, hp = m.hp, maxHP = m.max_hp, status_cond = m.status,
                 moves = arr(m.moves), pp = arr(m.pp), pp_bonuses = m.pp_bonuses,
                 held_item_id = m.held_item, active = held,
                 stat_stages = stages, blob_hex = raw and hex_of(raw) or nil }
    end
    local function party_wire(party)
        local active, b = {}, nil
        if in_battle() then
            b = battle_now()
            for i, s in ipairs(b and b.active_player_battler_slots or {}) do active[s] = 2 * (i - 1) end
        end
        local out = arr({})
        for i, m in ipairs(party) do out[i] = party_entry(m, active, b) end
        return out
    end
    local function enemy_wire(b)
        local out = arr({})
        if not b then return out end
        local idx, active = b.battler_party_indexes or {}, {}
        if idx[2] then active[idx[2]] = 1 end
        if (b.battlers_count or 0) >= 4 and idx[4] then active[idx[4]] = 3 end
        for _, m in ipairs(b.enemy_party or {}) do
            if m.species and m.species ~= 0 then
                local held, stages = stages_of(b, active[m.slot], m)
                out[#out + 1] = { species_id = m.species, level = m.level, hp = m.hp, maxHP = m.max_hp,
                                  active = held, held_item_id = m.held_item,
                                  stat_stages = stages,
                                  status_cond = m.status, moves = arr(m.moves), pp = arr(m.pp),
                                  pp_bonuses = m.pp_bonuses }
            end
        end
        return out
    end
    local function rescan_boxes()
        local cache, ok = {}, true
        for box = 0, (num(d.BOXES_PER_STORE) or 0) - 1 do
            local mons, why = call("read_box", box)
            if not mons then ok = false; log("box scan stopped at box " .. box .. ": " .. tostring(why)); break end
            for _, m in ipairs(mons) do
                if m.has_species == 1 then
                    cache[#cache + 1] = { box = box, slot = m.slot, key = key(m), species_id = m.species,
                                          nickname = m.nickname, held_item_id = m.held_item,
                                          moves = m.moves, is_egg = m.is_egg }
                end
            end
        end
        st.box_cache, st.boxes_ok = cache, ok
        if ok then st.box_generation = st.box_generation + 1 end
        return cache
    end
    local function box_generation() return st.boxes_ok and st.box_generation or nil end
    local function pc_boxes_wire()
        if not st.boxes_ok then return nil end
        local out = arr({})
        for _, e in ipairs(st.box_cache) do
            out[#out + 1] = { box = e.box, slot = e.slot, key = e.key, species_id = e.species_id,
                              nickname = e.nickname, held_item_id = e.held_item_id, moves = arr(e.moves) }
        end
        return out
    end

    -- ── baselines ──────────────────────────────────────────────────────────────────
    local function observe_hp(party)
        for _, m in ipairs(party) do
            local k = key(m)
            if m.hp == 0 then st.commanded[k] = nil          -- our zero has landed
            elseif not st.commanded[k] then st.alive[k] = true end
        end
    end
    -- The stats shape server/state.py caches (stats_cache, party_to_box, boxed capture) and
    -- boxes.lua needs to rebuild a CFRU record on withdraw (level, maxHP, five stats, PP):
    -- the old client's snapshot, archive/gen3-old-client:lua/clients/gen3_frlge_client.lua:1625-1639.
    local function stats_of(m)
        local s = { level = m.level, maxHP = m.max_hp, attack = m.attack, defense = m.defense,
                    speed = m.speed, spAtk = m.sp_attack, spDef = m.sp_defense }
        for i = 1, 4 do s["pp" .. i] = m.pp and m.pp[i] or 0 end
        return s
    end
    local function rebaseline(party)
        st.party_prev = {}
        for _, m in ipairs(party) do st.party_prev[key(m)] = { slot = m.slot, stats = stats_of(m) } end
        observe_hp(party)
    end
    local function seed_known(party)
        for _, m in ipairs(party) do st.known[key(m)] = true end
        for _, e in ipairs(st.box_cache) do st.known[e.key] = true end
    end
    local function mark_commanded(k)
        st.commanded[k], st.alive[k] = true, nil
    end
    local function latch_balls(announce)
        local n = ball_count()
        if n and n > 0 and not st.has_pokeballs then
            st.has_pokeballs = true
            if announce then hud.nuzlocke_start("Nuzlocke Start!") end
        end
        return n
    end

    -- A borrowed party (RR multi/tag battles swap a partner's party in) shares no key with the
    -- pre-battle party. While it is in RAM nothing is diffed and tick omits `party`
    -- (docs/protocol.md §3.2 tick row). Held battle writes are KEPT, not dropped (the old client
    -- dropped them on restore, :2976): a server force_faint is never resent, so dropping one
    -- loses a required write; the core holds them until the real party returns or the battle
    -- ends, then the checkpoint queue lands them.
    local function update_frozen(party)
        local was = st.frozen
        local base = st.battle and st.battle.base_keys
        if base and next(base) and #party > 0 then
            local overlap = false
            for _, m in ipairs(party) do if base[key(m)] then overlap = true; break end end
            st.frozen = not overlap
        else
            st.frozen = false
        end
        if st.frozen ~= was then log(st.frozen and "borrowed party in RAM: party frozen" or "own party restored") end
    end

    -- ── settles (one party read per frame that had signals) ────────────────────────
    local function settle_faints(party, area_id)
        for _, m in ipairs(party) do
            local k = key(m)
            if m.hp == 0 and st.alive[k] then
                st.alive[k] = nil
                send("faint", { key = k, area_id = area_id })
            end
        end
    end

    local function settle_acquisitions(party, area_id, caught)
        local gift = not caught
        local function resolve_area()
            if area_id ~= "" and not gift_area(area_id) and not gift then session.resolved_areas[area_id] = true end
        end
        local found = false
        for _, m in ipairs(party) do
            local k = key(m)
            if not st.known[k] then
                st.known[k], found = true, true
                resolve_area()
                send("capture", { key = k, area_id = area_id, species_id = m.species, level = m.level,
                                  hp = m.hp, maxHP = m.max_hp, nickname = m.nickname,
                                  held_item_id = m.held_item, is_egg = m.is_egg == 1, gift = gift or nil })
            end
        end
        if found then return end
        -- party full: the mon went to the PC (SendMonToPC)
        rescan_boxes()
        local fresh = {}
        for _, e in ipairs(st.box_cache) do if not st.known[e.key] then fresh[#fresh + 1] = e end end
        for _, e in ipairs(fresh) do st.known[e.key] = true end
        if #fresh == 1 then
            local e = fresh[1]
            resolve_area()
            -- a boxed record has no party tail: the caught mon's stats and PP are still in the
            -- enemy party record it was copied from (old client :3950-3985 read the same foe)
            local src
            local b = battle_now()
            for _, m in ipairs(b and b.enemy_party or {}) do if key(m) == e.key then src = m end end
            local stats = src and stats_of(src) or nil
            send("capture", { key = e.key, area_id = area_id, in_box = true, species_id = e.species_id,
                              nickname = e.nickname, held_item_id = e.held_item_id,
                              level = stats and stats.level or nil, maxHP = stats and stats.maxHP or nil,
                              stats = stats, is_egg = e.is_egg == 1, gift = gift or nil })
        elseif #fresh > 1 then
            -- more than one unknown boxed key cannot be attributed to this acquisition
            log("acquisition: " .. #fresh .. " new boxed keys, none reported (ambiguous)")
        end
    end

    local function settle_pc(party, area_id, released)
        local now = {}
        for _, m in ipairs(party) do now[key(m)] = m end
        rescan_boxes()
        local boxed = {}
        for _, e in ipairs(st.box_cache) do boxed[e.key] = true end
        for k, prev in pairs(st.party_prev) do
            if not now[k] and not st.carried[k] then
                session.identity:departure(k)
                st.carried[k] = prev
            end
        end
        for k, prev in pairs(st.carried) do
            if boxed[k] then
                st.carried[k] = nil
                send("party_to_box", { key = k, stats = prev.stats })
            elseif now[k] then
                st.carried[k] = nil                            -- a party shuffle, not a move
            elseif released then
                st.carried[k] = nil
                log("released " .. k)
            end
        end
        for k in pairs(now) do
            if not st.party_prev[k] then
                if st.known[k] then send("box_to_party", { key = k, area_id = area_id })
                else st.known[k] = true end                    -- the PC cannot create a mon
            end
        end
    end

    -- OPEN kind (not PHYSICAL; G3_request_draft.md:72-74): an in-game NPC trade replaces the
    -- record at the traded slot. Reported as key_change reason npc_trade (the Gen 1 contract);
    -- never for a link trade (docs/protocol.md §3.2), so skipped while a native trade runs.
    local function settle_trade(party)
        local before = st.trade
        st.trade = nil
        if not before or (native and native.trade_active and native:trade_active()) then return end
        for _, m in ipairs(party) do
            local old = before[m.slot]
            local k = key(m)
            if old and old ~= k then
                st.known[k] = true
                if m.hp and m.hp > 0 then st.alive[k] = true end
                session.identity:begin_alias(old, k, m, party, io.framecount())
                send("key_change", { old_key = old, new_key = k, reason = "npc_trade",
                                     new_species = m.species, new_nickname = m.nickname })
            end
        end
    end

    local function check_area()
        local area_id, loc = area_now()
        local here = area_id .. "|" .. loc
        if st.last_area ~= nil and st.last_area ~= here then
            send("area_enter", { area_id = area_id, loc_name = loc })
            if st.has_pokeballs and session.seeded and area_id ~= "" and not gift_area(area_id)
               and not session.resolved_areas[area_id] and not in_battle() then
                hud.show("** NEW ENCOUNTER **  " .. loc, 255, 220, 60, 240)
            end
        end
        st.last_area = here
        return area_id, loc
    end

    -- per-battle facts the end of the battle needs: the foe and whether it was a trainer
    local function note_battle(b)
        local bt = st.battle
        if not (bt and b) then return end
        if b.is_trainer ~= nil then bt.is_trainer = b.is_trainer end
        if num(a.BATTLE_TYPE_ADDR) then bt.type_flags = io.read_u32(a.BATTLE_TYPE_ADDR) end
        if not bt.foe then
            for _, m in ipairs(b.enemy_party or {}) do
                if m.species and m.species ~= 0 then bt.foe = { species = m.species, level = m.level }; break end
            end
        end
        -- one announcement per battle id (OMP F5): a battle a pre-battle announcement already named
        -- is never announced again, even when its battle_begin refused the carry
        if bt.battle_id and bt.battle_id == st.pre_announced_id then bt.trainer_sent = true end
        if b.is_trainer and num(b.trainer_id) and b.trainer_id ~= 0 and not bt.trainer_sent then
            bt.trainer_sent = true
            bt.trainer_id = b.trainer_id
            -- battle_id rides with the announcement: it is what this battle's
            -- replace_rival_team must echo back (docs/protocol.md).
            if session_nonce then
                send("trainer_battle_start", { trainer_id = b.trainer_id,
                                               battle_id = bt.battle_id, session = session_nonce })
                rival_authority = {session = session_nonce, battle_id = bt.battle_id,
                                   trainer_id = b.trainer_id,
                                   rejected = sig_src and sig_src.rejected}
            else
                -- no identity to announce: the server will treat this client as legacy
                send("trainer_battle_start", { trainer_id = b.trainer_id })
            end
        end
    end

    local function finish_battle(area_id)
        local bt = st.battle
        st.battle = nil
        session.pending_safe = true
        if not bt then return end
        local b = battle_now()
        local caught = bt.caught or (b and num(d.OUTCOME_CAUGHT) and b.outcome == d.OUTCOME_CAUGHT)
        -- is_trainer must be KNOWN false: a pack without the trainer mask never dead-zones an
        -- area on a guess (an unknown battle type is not evidence of a failed encounter).
        -- †Limit: FRLG ghost/old-man-tutorial battles need a pack BATTLE_TYPE_NO_CATCH_MASK.
        local exempt = num(d.BATTLE_TYPE_NO_CATCH_MASK) and bt.type_flags
                       and (bt.type_flags & d.BATTLE_TYPE_NO_CATCH_MASK) ~= 0
        if not caught and bt.is_trainer == false and not exempt and bt.foe and st.has_pokeballs
           and area_id ~= "" and not gift_area(area_id) and not session.resolved_areas[area_id] then
            session.resolved_areas[area_id] = true
            send("no_catch", { area_id = area_id, species_id = bt.foe.species, level = bt.foe.level })
        end
    end

    local function settle()
        local f = st.flags
        if not next(f) then return end
        st.flags = {}
        if f.save and io.saveram then pcall(io.saveram) end
        local party = party_read(f.pc)                          -- a PC settle reads occupancy
        if not party then
            f.save = nil
            st.flags = f                                        -- try again next frame
            return
        end
        update_frozen(party)
        local area_id = area_now()
        if st.battle and in_battle() then note_battle(battle_now()) end
        if f.acquire and not st.baselined then
            -- nothing tells a pre-existing key from a new one yet: report none, learn them all
            log("acquisition signal before a party baseline exists: not reported")
            f.acquire = nil
            if not st.frozen then rescan_boxes(); seed_known(party); st.baselined = true end
        end
        -- a PC trade in flight (and its settle window) swaps a party slot: nothing about it is a
        -- capture, a deposit or a key_change (docs/protocol.md §6.2 item 5, §6.5); the TradeMons
        -- site fires during the native scene and is ignored here
        -- from the FIRST ACTUAL POST (an owned op's own dispatch receipt published its opcode),
        -- not from the queued phase: a post that is refused or held writes nothing, and until
        -- something is written the party can only change the ordinary way, so ordinary reduction
        -- keeps going
        local trading = (st.trade_apply ~= nil and (st.trade_apply.posted == true or st.trade_apply.possibly_posted == true))
                        or io.framecount() < st.trade_settle_until
        if trading then st.trade = nil end
        if not st.frozen and not trading then
            if f.faint or f.battle_end or f.whiteout then settle_faints(party, area_id) end
            if f.acquire then settle_acquisitions(party, area_id, f.caught or (st.battle and st.battle.caught)) end
            if f.pc then settle_pc(party, area_id, f.release) end
            if f.trade then settle_trade(party) end
        end
        if f.whiteout then
            send("whiteout", {})
            hud.show("WHITED OUT", 255, 60, 60, 300)
        end
        if f.battle_end then finish_battle(area_id) end
        if f.map then check_area() end
        if not st.frozen then rebaseline(party) end
    end

    -- ── in-battle writes (owner ruling 2026-09-23: parity with RR on vanilla) ──────
    local explode_capable = num(a.BATTLE_MONS_ADDR) and num(a.CHOSEN_ACTION_ADDR)
                            and num(a.CHOSEN_MOVE_ADDR) and num(a.BATTLE_COMM_ADDR) and true or false
    -- mechanism P (C4-ACTIVE-FAINT-P): its own flag, so the P fields never flip explode_capable
    -- (vanilla ships CHOSEN_ACTION/BATTLE_COMM but no CHOSEN_MOVE). RR ships no STATUS3 /
    -- DISABLE_STRUCTS (CFRU layout OPEN, G5), so it keeps the hold by data, not by title.
    local active_faint_capable = num(a.BATTLE_MONS_ADDR) and num(a.STATUS3_ADDR)
                                 and num(a.DISABLE_STRUCTS_ADDR) and num(a.CHOSEN_ACTION_ADDR)
                                 and num(a.BATTLE_COMM_ADDR) and num(d.STATUS3_PERISH_SONG)
                                 and num(d.DISABLE_STRUCT_SIZE) and num(d.DISABLE_STRUCT_PERISH_TIMER_OFF)
                                 and num(d.B_ACTION_NOTHING_FAINTED) and true or false

    -- one armed window, one reason, one allow set; returns true or nil, why
    -- args: what the reason's clause set needs (battle_commit: {battler}; sound: {player, track})
    --
    -- C5-11d addendum (the LeafGreen sound stall): a plan is applied WHOLE or not at all. Every
    -- entry's address, width and value is checked against writes.lua's own uint rules BEFORE the
    -- window is armed, so a bad entry anywhere (LG's garbage SE header made the sound plan's LAST
    -- value, status, overflow after 11 of 12 entries had landed) is refused with zero bytes
    -- written. What can still stop a plan mid-way is a live safety refusal between entries;
    -- writes.attempted makes that one loud.
    local UINT_MAX = { [1] = 255, [2] = 65535, [4] = 4294967295 }
    local function uint_ok(v, max)
        return type(v) == "number" and v % 1 == 0 and v >= 0 and v <= max
    end
    local function armed_write(reason, plan, args)
        if args then args.plan = plan end                     -- G4-PH: the policy judges the plan itself
        for i, w in ipairs(plan) do
            local max = UINT_MAX[w[2]]
            if not (max and uint_ok(w[1], 4294967296 - w[2]) and uint_ok(w[3], max)) then
                return nil, string.format("%s plan entry %d/%d is not writable (addr=%s width=%s "
                                          .. "value=%s); nothing written", reason, i, #plan,
                                          tostring(w[1]), tostring(w[2]), tostring(w[3]))
            end
        end
        local snap, why = policy:snapshot()
        if not snap then return nil, why end
        local ok, cwhy = policy:check(snap, reason, args)
        if not ok then return nil, cwhy end
        local allow = {}
        for _, w in ipairs(plan) do allow[w[1] .. ":" .. w[2]] = true end
        local before = writes.attempted
        local wok, err = pcall(function()
            writes:arm(reason, function(x, n) return allow[x .. ":" .. n] == true end, args)
            -- G4-PH §3.3: a plan ending in the controller hand-off carries two self-invalidating
            -- writes (comm, then the slot); it is validated once and written whole
            if plan.handoff then return writes:write_plan(plan) end
            for _, w in ipairs(plan) do
                if w[2] == 4 then writes:write_u32(w[1], w[3])
                elseif w[2] == 2 then writes:write_u16(w[1], w[3])
                else writes:write_bytes(w[1], { w[3] }) end
            end
        end)
        writes:disarm()
        if not wok then
            local attempted = (writes.attempted or 0) - (before or 0)
            if attempted > 0 then
                err = string.format("PARTIAL %s write: %d byte(s) attempted, partial mutation possible: %s",
                                    reason, attempted, tostring(err))
                log(err)
            end
            return nil, tostring(err)
        end
        return true
    end

    local function faint_plan(slot, battler)
        local hp = party_hp_addr(slot)
        if not hp then return nil end
        local plan = { { hp, 2, 0 } }
        if battler and num(a.BATTLE_MONS_ADDR) then
            plan[2] = { a.BATTLE_MONS_ADDR + battler * R.BATTLE_MON_SIZE + R.BATTLE_MON_HP_OFF, 2, 0 }
        end
        return plan
    end

    -- The Variant-3 menu skip (archive/gen3-old-client:lua/memory_gba.lua:1303-1345): every move slot of the battler
    -- reads Explosion, and the action-commit state says "already chosen", so the action menu is
    -- skipped. Addresses come from the pack (RR pins CHOSEN_*/BATTLE_COMM/BATTLE_STRUCT_PTR);
    -- a pack without them (vanilla FRLG) is not explode_capable and force_explode is a faint.
    local function commit_plan(battler, with_moves)
        local plan = {}
        if with_moves then
            local base = a.BATTLE_MONS_ADDR + battler * R.BATTLE_MON_SIZE
            for i = 0, 3 do
                plan[#plan + 1] = { base + BATTLE_MON_MOVES_OFF + i * 2, 2, MOVE_EXPLOSION }
                plan[#plan + 1] = { base + BATTLE_MON_PP_OFF + i, 1, EXPLODE_PP }
            end
        end
        plan[#plan + 1] = { a.CHOSEN_ACTION_ADDR + battler, 1, B_ACTION_USE_MOVE }
        plan[#plan + 1] = { a.CHOSEN_MOVE_ADDR + battler * 2, 2, MOVE_EXPLOSION }
        local bs = num(a.BATTLE_STRUCT_PTR_ADDR) and io.read_u32(a.BATTLE_STRUCT_PTR_ADDR) or 0
        if bs ~= 0 then
            if num(d.BATTLE_STRUCT_CHOSEN_MOVE_POS_OFF) then
                plan[#plan + 1] = { bs + d.BATTLE_STRUCT_CHOSEN_MOVE_POS_OFF + battler, 1, 0 }
            end
            if num(d.BATTLE_STRUCT_MOVE_TARGET_OFF) then
                plan[#plan + 1] = { bs + d.BATTLE_STRUCT_MOVE_TARGET_OFF + battler, 1, TARGET_FOE_PRIMARY }
            end
        end
        -- the committing state is itself the battle_commit guard (gBattleCommunication[battler]
        -- < STANDBY, the pack's commit_guard.value) and writes.lua re-validates before every write, so only the hand-off may follow it
        plan[#plan + 1] = { a.BATTLE_COMM_ADDR + battler, 1, STANDBY }
        -- G5-EXPLODE-HANDOFF (owner ruling 19): where the pack proves the Explode+H shape (RR,
        -- whose parked CFRU menu outlives the commit), the same hand-off as P ends the menu, so
        -- Explosion fires with no press. FR/LG packs carry no such shape: plan unchanged there.
        local h = policy.handoff_entry and policy:handoff_entry(battler, "explode")
        if h then plan[#plan + 1] = { h[1], h[2], h[3] }; plan.handoff = true end
        return plan
    end

    -- force_explode on the active battler. The old client settled on HP 0 / switch-out /
    -- battle end, and otherwise after a 600-frame wall-clock timer wrote HP 0 into the ACTIVE
    -- battler (the write the force_faint path deliberately avoids, :2555-2596). Here the
    -- timer is replaced by an engine witness: Explosion's PP dropped (the move executed) and a
    -- new action selection began (gBattleCommunication < standby) with HP still > 0, i.e. the
    -- user survived (Damp). The entry then degrades to the force_faint rule for an active
    -- battler: held until switch-out or battle end. UNVERIFIED on hardware (no emulator lane).
    local function explode_step(e, slot, mon, battler)
        local base = a.BATTLE_MONS_ADDR + battler * R.BATTLE_MON_SIZE
        local bhp = io.read_u16(base + R.BATTLE_MON_HP_OFF)
        local pp0 = io.read_u8(base + BATTLE_MON_PP_OFF)
        local comm = io.read_u8(a.BATTLE_COMM_ADDR + battler)
        local ex = e.explode
        if ex and ex.failed then return "hold", ex.why end
        if not STANDBY then return "hold", "pack has no battle.commit_guard.value" end
        -- A pre-existing multi-turn lock (Thrash/Outrage/Rollout: gLockedMoves[battler] ~= 0)
        -- owns the next action; committing Explosion over it would fight the engine. Held as
        -- the active battler instead, and nothing is written. Sleep and flinch need no case:
        -- the move never executes, PP never drops, and the commit is re-armed each turn until
        -- it does or the battler leaves. Liveness of every branch here is NOT PHYSICAL.
        if not ex and num(a.LOCKED_MOVES_ADDR) and io.read_u16(a.LOCKED_MOVES_ADDR + battler * 2) ~= 0 then
            e.explode = { battler = battler, failed = true, why = "move locked; held as the active battler" }
            log("force_explode: battler " .. battler .. " is move-locked; held as active " .. e.key)
            return "hold", "move locked; held as the active battler"
        end
        if ex and bhp == 0 then
            e.explode = nil
            hud.show("!! " .. (mon.nickname or key(mon)) .. " BOOM!", 255, 80, 80, 360)
            return "done"
        end
        if ex and pp0 < EXPLODE_PP then
            if comm < STANDBY then
                ex.failed, ex.why = true, "explosion failed; held as the active battler"
                log("force_explode: Explosion executed and the battler survived; held as active " .. e.key)
                return "hold", "explosion failed; held as the active battler"
            end
            return "hold", "explosion executing"
        end
        if ex and comm >= STANDBY then return "hold", "explosion committed" end
        -- first commit, or the engine reset the commit state at turn start: (re)write it
        local plan = commit_plan(battler, not ex)
        local ok, why = armed_write("battle_commit", plan, { battler = battler })
        if not ok then return "hold", why end
        if not ex then
            e.explode = { battler = battler }
            mark_commanded(key(mon))
            log("force_explode: menu skip committed slot=" .. slot .. " battler=" .. battler
                .. " handoff=" .. (plan.handoff and 1 or 0))
        end
        return "hold", "explosion committed"
    end

    -- Mechanism P (docs/gen3/research/active_faint_in_battle_scope_2026-09-23.md §2d; owner
    -- ruling PLAN §0 "In-battle faint"): at the parked action menu, the battler gets the Perish
    -- flag with its counter at 0 and a committed no-op action. The turn runs, and the end-of-turn
    -- Perish check (FR/LG HandleWishPerishSongOnTurnEnd, RR CFRU end-turn state 34) runs the
    -- engine's own BattleScript_PerishSongTakesLife: HP drain, datahpupdate (gBattleMons AND the
    -- party), tryfaintmon ("X fainted!"), then the vanilla send-out / whiteout. No HP byte is
    -- written here. The no-op commit is what stops the mon acting (or Baton Passing the Perish
    -- flag on). gStatuses3 and the timer byte are read on the same parked frame.
    -- G4-PH (P+H, owner rulings 15-18; rr_active_faint_parity_scope_2026-09-23.md §3.2): when the
    -- pack proves battle.handoff, the plan ends by handing the controller slot to
    -- PlayerBufferExecCompleted, AFTER comm = 3 (with comm 1 the stale buffer-B action replays).
    -- The engine then ends the menu itself: no A press on any title, and CFRU's parked menu (the
    -- RR L-throw) is gone. Without the block the plan is P alone and the player presses A once.
    local function perish_plan(battler)
        local s3 = a.STATUS3_ADDR + battler * 4
        local timer = a.DISABLE_STRUCTS_ADDR + battler * d.DISABLE_STRUCT_SIZE + d.DISABLE_STRUCT_PERISH_TIMER_OFF
        local plan = {
            { s3, 4, io.read_u32(s3) | d.STATUS3_PERISH_SONG },
            -- timer 0 (low nibble); the high nibble is kept, as the engine's own decrement does
            { timer, 1, io.read_u8(timer) & 0xF0 },
            { a.CHOSEN_ACTION_ADDR + battler, 1, d.B_ACTION_NOTHING_FAINTED },
            -- comm is the battle_commit guard: only the hand-off may follow it
            { a.BATTLE_COMM_ADDR + battler, 1, STANDBY },
        }
        local h = policy.handoff_entry and policy:handoff_entry(battler)
        if h then plan[#plan + 1] = { h[1], h[2], h[3] }; plan.handoff = true end
        return plan
    end

    -- commit -> held until gBattleMons[b].hp == 0 (done: the engine's faint, or a foe KO first).
    -- The battler leaving (Roar) takes battle_write's bench path; the battle ending first (flee,
    -- catch) takes its overworld path. A reset commit (comm < STANDBY) with the mon alive is re-armed;
    -- mid-turn the permit refuses that, so it can only land at a parked menu.
    -- Review follow-up 2: the commit's comm[b] = STANDBY fails every later battle_faint (battle_comm_0)
    -- until the next parked menu, which comes AFTER the Perish KO's party screen, where a bench
    -- mon still alive could be sent in. So the commit waits while another pending entry resolves
    -- to a bench slot: that entry lands later in this same flush (same permit, minus the guard)
    -- and the commit follows next frame. Only this step is delayed; the core's arrival order of
    -- battle_pending and each entry's arrival stamp (684bbb7a) are untouched.
    local function bench_write_pending(e, b)
        local party = party_read()
        if not party then return false end
        for _, o in ipairs(session.battle_pending) do
            if o ~= e then
                local slot = session.identity:find_party_slot(o.key, party)
                if slot and not battler_of(b, slot) then return true end
            end
        end
        return false
    end

    local function active_faint_step(e, mon, battler, b)
        if not STANDBY then return "hold", "pack has no battle.commit_guard.value" end
        local bhp = io.read_u16(a.BATTLE_MONS_ADDR + battler * R.BATTLE_MON_SIZE + R.BATTLE_MON_HP_OFF)
        if e.perish and bhp == 0 then
            hud.show("!! " .. (e.nickname or mon.nickname or key(mon)) .. " fainted", 255, 80, 80, 360)
            return "done"
        end
        -- the carrier's contract (W2, G4-PH): e.why is exactly "active faint committed" after a
        -- hand-off; a pack without battle.handoff keeps the press hint
        if e.perish and io.read_u8(a.BATTLE_COMM_ADDR + battler) >= STANDBY then
            return "hold", e.handoff and "active faint committed" or "active faint committed (press A)"
        end
        if bench_write_pending(e, b) then return "hold", "bench write first" end
        local plan = perish_plan(battler)
        local ok, why = armed_write("battle_commit", plan, { battler = battler })
        if not ok then return "hold", why end
        e.handoff = plan.handoff == true
        if not e.perish then
            e.perish = true
            mark_commanded(key(mon))                          -- the engine's faint is not an echo
            log("force_faint: Perish commit battler=" .. battler .. " handoff=" .. (e.handoff and 1 or 0)
                .. " " .. e.key)
        end
        return "hold", e.handoff and "active faint committed" or "active faint committed (press A)"
    end

    local function battle_write(e, slot, mon, ending)
        local k = key(mon)
        if ending then
            -- the battle is over: the overworld checkpoint rarely holds on the exit frame, so this
            -- normally declines and the core hands the entry to the checkpoint queue
            local plan = faint_plan(slot, nil)
            if plan and armed_write("overworld", plan) then mark_commanded(k); return "done" end
            return nil
        end
        local b = battle_now()
        local battler = battler_of(b, slot)
        if battler then
            if e.cmd == "force_explode" and explode_capable then return explode_step(e, slot, mon, battler) end
            -- P is the linked-faint path ONLY (owner 2026-09-23: Explode Mode is untouched, so a
            -- non-capable force_explode keeps its hold below). Singles only: in doubles a partner
            -- B-cancel resets battler 0's commit while the Perish flag stays (scope doc §2.1), and
            -- D1-D5 are signed limits.
            if e.cmd == "force_faint" and active_faint_capable and battler == 0
               and b.battlers_count == 2 and b.is_doubles ~= true then
                return active_faint_step(e, mon, battler, b)
            end
            -- Held until it switches out or the battle ends: a party-only HP write is undone by the
            -- next datahpupdate, and a both-words write is a silent faint (scope doc §1.4, §2a).
            return "hold", "active battler"
        end
        local plan = faint_plan(slot, nil)
        if not plan then return "hold", "party base unreadable" end
        local ok, why = armed_write("battle_faint", plan)
        if not ok then return "hold", why end                  -- C4-B: refusal = hold, not defer
        mark_commanded(k)
        hud.show("!! " .. (e.nickname or mon.nickname or k) .. " KO'd", 255, 80, 80, 360)
        return "done"
    end

    -- ── the checkpoint executors (the deferred queue) ──────────────────────────────
    local exec = {
        arm = function() end,                                  -- each executor arms its own window
        disarm = function() writes:disarm() end,
        faint_slot = function(slot)
            local plan = assert(faint_plan(slot, nil), "party base unreadable")
            local ok, why = armed_write("overworld", plan)
            assert(ok, why)
            local party = party_read() or {}
            for _, m in ipairs(party) do if m.slot == slot then mark_commanded(key(m)) end end
        end,
        deposit = function(k, hint)
            if not boxes then return nil, "no box module" end
            return boxes:deposit(k, hint)
        end,
        withdraw = function(k, stats, nickname)
            if not boxes then return nil, "no box module" end
            return boxes:withdraw(k, stats, nickname)
        end,
        memorialize = function(k, hint)
            if not boxes then return nil, "no box module" end
            return boxes:memorialize(k, hint)
        end,
        stats_of = stats_of,
        -- every byte moves through the one sink; its ATTEMPT counter moves before each external
        -- write, so an error after the first attempted byte reads as a (possible) mutation
        write_count = function() return writes.attempted end,
        -- our own moves must not read as the player's: re-baseline after every one
        rescan = function()
            rescan_boxes()
            local party = party_read()
            if party then seed_known(party); rebaseline(party) end
        end,
    }
    local memorial_box = boxes and boxes.memorial_box or ((num(d.BOXES_PER_STORE) or 1) - 1)

    -- ── the driver ─────────────────────────────────────────────────────────────────
    local drv = { commands = {} }
    drv.frame = function() return io.framecount() end
    drv.read_party = party_read
    drv.in_battle = in_battle
    drv.battle_write = battle_write
    function drv.party_borrowed()
        local party = party_read()
        if party then update_frozen(party) end
        return st.frozen
    end

    function drv.game_is_live()
        local party, why = party_read()
        if not party then return false, why or "party unreadable" end
        if reads.read_sb2 and not reads.read_sb2() then return false, "save blocks not set" end
        local t = trainer()
        if t and t.ot_id == 0 and #party == 0 then return false, "pre-game (title/new game)" end
        return true
    end
    function drv.save_cleared()
        if reads.read_sb2 and not reads.read_sb2() then return true end
        local t = trainer()
        return t ~= nil and t.ot_id == 0
    end
    local function overworld_ok()
        local snap, why = policy:snapshot()
        if not snap then return false, why end
        return policy:check(snap, "overworld")
    end
    -- the deferred queue's gate: box moves wait while a PC trade swaps a party slot
    -- (docs/protocol.md §6.2 item 6)
    function drv.checkpoint_ok()
        if st.trade_apply then return false, "PC trade in flight" end
        return overworld_ok()
    end
    function drv.hello_ready()
        local live, why = drv.game_is_live()
        if not live then return false, why end
        if in_battle() then return true end
        return overworld_ok()
    end
    function drv.on_reset()
        if trade then trade:reset() end
        st.known, st.alive, st.commanded, st.party_prev, st.carried = {}, {}, {}, {}, {}
        st.box_cache, st.boxes_ok, st.battle, st.frozen, st.flags = {}, false, nil, false, {}
        st.last_area, st.trade = nil, nil
        st.opp_seen, st.pre_announced_id = nil, nil
        st.baselined, st.seen_count, st.observe_at = false, nil, nil
        st.trade_apply, st.trade_settle_until = nil, 0
        -- Native reset ends a hardware lease, never the token-bound report owed to the server.
        st.trade_unresolved = trade and trade:uncertainties() or st.trade_unresolved
        -- C5-11d MAJOR 3: the battle the authority named is gone with the save, whatever the
        -- battle RAM still says; a queued job must not ride it (reducer lifecycle or not)
        rival_authority = nil
    end

    -- One read-only cartridge snapshot per session, including cached failure. The Gen 3
    -- reader owns bounds/pointer walking; this hook only binds table metadata and transport.
    local content_cache = {attempted=false}
    local function rom_content()
        if p.artifact_kind ~= "rand" then return nil end
        if not content_cache.attempted then
            content_cache.attempted = true
            local ok, payload, why = pcall(function()
                local source = assert(profile.rom_tables, "profile has no rom_tables")
                local tables = {rom_size=p.rom_size} -- reader's documented 32 MiB window default if absent
                for _, name in ipairs({"gTrainers", "gWildMonHeaders", "gEvolutionTable", "gSpeciesInfo", "gTrainerClassNames"}) do
                    local row = assert(source[name], "missing ROM table " .. name)
                    tables[name] = {address=tonumber(row.address), count=tonumber(row.count), size=tonumber(row.size)}
                end
                local reader = assert(p.rom_content_new, "ROM content reader unavailable")(tables, {read_u8=io.read_u8})
                return reader:payload()
            end)
            if ok and type(payload) == "table" and type(payload.tables) == "table" and type(payload.fingerprint) == "string" then
                content_cache.payload = payload
            else
                log("rom_content unavailable: " .. tostring(ok and (why or "invalid reader result") or payload))
            end
        end
        return content_cache.payload
    end
    -- No wire side effect here (no area_enter, no banner): hello is the connection's first line.
    function drv.hello_fields()
        local party = party_read() or {}
        update_frozen(party)
        rescan_boxes()
        -- a borrowed party is never published nor learned as ours (docs/protocol.md §9 item 11):
        -- hello.party stays present and empty, exactly like tick_fields' guard
        local own = (st.frozen or (trade and trade:hide_party())) and {} or party
        -- Once a baseline exists hello REPORTS and never learns: the session builds hello before
        -- this frame's signals drain, so a mon added since the last quiet frame (its acquisition
        -- hook firing this frame or the next) must stay unknown for settle to report it as a
        -- capture right after the hello. Only the very first baseline is taken here.
        if not st.baselined and not st.frozen then
            seed_known(own)                                    -- box-key seeding at connect
            rebaseline(party)
            st.baselined = true
            -- the quiet interval starts from THIS count: a mon added after hello is a change
            st.seen_count = num(a.PARTY_COUNT_ADDR) and io.read_u8(a.PARTY_COUNT_ADDR) or -1
        end
        latch_balls(false)                                     -- a resume, not an acquisition
        local area_id, loc = area_now()
        st.last_area = area_id .. "|" .. loc
        local f = { rom_type = p.rom_type, foundation = p.foundation, artifact_kind = p.artifact_kind,
                    rom_sha1 = p.rom_sha1, party = party_wire(own), pc_boxes = pc_boxes_wire(),
                    pc_boxes_generation = box_generation(),
                    area_id = area_id, loc_name = loc, has_pokeballs = st.has_pokeballs,
                    in_battle = in_battle(), badges = badges(), ball_count = ball_count() }
        if session_nonce then
            -- capability declaration (card C5-10b): this client mints and enforces the battle
            -- request identity, so the server may refuse an identity-less manual rival inject for
            -- it. Declared ONLY when the identity really exists (fail closed).
            f.battle_identity = true
        end
        local t = trainer()
        if t then f.ot_id, f.trainer_name = t.ot_id, t.name end
        if native and native.hello_fields then
            for k, v in pairs(native:hello_fields() or {}) do f[k] = v end
        end
        if trade and trade:hide_party() then f.pc_boxes, f.pc_boxes_generation = nil, nil end
        f.trade_prepare = trade ~= nil and trade:capable() == true
        f.rom_content = rom_content()
        return f
    end

    function drv.tick_fields()
        local party = party_read()
        if not party then return nil end
        update_frozen(party)
        if not st.frozen then observe_hp(party) end
        local area_id, loc = check_area()
        local b = in_battle() and battle_now() or nil
        if b then note_battle(b) end
        local n = latch_balls(true)
        local f = { area_id = area_id, loc_name = loc, in_battle = b ~= nil, has_pokeballs = st.has_pokeballs,
                    is_trainer_battle = b and b.is_trainer or false, is_doubles = b and b.is_doubles or false,
                    trainer_id = b and b.is_trainer and num(b.trainer_id) or nil,
                    enemy_party = enemy_wire(b), ball_count = n, badges = badges() }
        if not st.frozen and not (trade and trade:hide_party()) then f.party = party_wire(party) end
        if st.boxes_ok and not (trade and trade:hide_party()) then
            f.pc_boxes, f.pc_boxes_generation = pc_boxes_wire(), st.box_generation
        end
        local t = trainer()
        if t then f.trainer_name = t.name end
        return f
    end

    function drv.start()
        -- on_fire runs AT the fire, before the queue is drained: the only place a same-frame
        -- end+begin can be seen before native is serviced (see rival_authority above).
        local function close_authority(sig)
            local had = rival_authority
            rival_authority = nil                 -- first: a throwing log must not keep it open
            -- G5-RR-RIVAL: a PRE-battle announcement names the battle about to begin (battle_seq
            -- + 1). Its own battle_begin -- the first one, for the same trainer -- CARRIES it
            -- into that battle instead of closing it; any later boundary closes it as before.
            -- a WILD battle never carries it (review F2): the trainer type bit is set by
            -- BattleSetup_StartTrainerBattle before CB2_InitBattle, i.e. at this fire
            if had and had.pre and not had.begun and sig and sig.kind == "battle_begin"
               and had.battle_id == battle_seq + 1
               and io.read_u16(a.TRAINER_OPPONENT_ADDR) == had.trainer_id
               and num(d.BATTLE_TYPE_TRAINER_MASK)
               and (io.read_u32(a.BATTLE_TYPE_ADDR) & d.BATTLE_TYPE_TRAINER_MASK) ~= 0 then
                rival_authority = {session = had.session, battle_id = had.battle_id,
                                   trainer_id = had.trainer_id, rejected = had.rejected,
                                   pre = true, opened = had.opened, begun = io.framecount()}
                log("rival authority carried into battle " .. tostring(had.battle_id))
                return
            end
            if had then log("rival authority closed by " .. tostring(sig and sig.kind)) end
        end
        sig_src = p.Signals.new(profile, p.sites, io, p.ev,
                                {battle_begin = close_authority, battle_end = close_authority,
                                 whiteout = close_authority})
        return sig_src
    end

    function drv.on_signal(sig)
        local k, f = sig.kind, st.flags
        if k == "battle_begin" then
            -- the pre-battle party is the borrowed-party reference
            local base = {}
            for pk in pairs(st.party_prev) do base[pk] = true end
            battle_seq = battle_seq + 1
            -- both halves of the request identity live on the epoch record: the guard below and
            -- the harness read them from here, never from a second copy
            st.battle = { caught = false, base_keys = base, battle_id = battle_seq,
                          session = session_nonce }
            -- the battle a pre-battle announcement already named: never announce it twice (the
            -- server queues one swap per trainer_battle_start)
            local ra = rival_authority
            if ra and ra.pre and ra.begun and ra.battle_id == battle_seq then
                st.battle.trainer_sent, st.battle.trainer_id = true, ra.trainer_id
            end
        elseif k == "battle_end" then f.battle_end = true
        elseif k == "faint" then f.faint = true
        elseif k == "poison_faint" then f.faint = true          -- OPEN kind (FR only), not PHYSICAL
        elseif k == "whiteout" then f.whiteout = true          -- a flag: one whiteout per settle
        elseif k == "capture_wild" then
            f.acquire, f.caught = true, true
            if st.battle then st.battle.caught = true end
        elseif k == "mon_given" or k == "pc_move" then f.acquire = true
        elseif PC_KINDS[k] then
            f.pc = true
            if k == "pc_release" then f.release = true end
        elseif k == "map_load" then f.map = true
        elseif k == "save" then f.save = true
        elseif k == "trade_begin" then                          -- OPEN kind, not PHYSICAL
            st.trade = {}
            for pk, prev in pairs(st.party_prev) do st.trade[prev.slot] = pk end
        elseif k == "trade_done" then f.trade = true            -- OPEN kind, not PHYSICAL
        end
        -- evolve_species_store / trade_evolve_species_store (OPEN, not PHYSICAL): a Gen 3
        -- evolution keeps PID:OTID, so the key is unchanged and the next tick carries the
        -- species. poison_hp_before / pc_release_begin bookkeeping and frame_control: nothing.
    end
    -- The pre-existing baseline (R4), independent of hello: what is in the party/boxes on a
    -- QUIET frame (no engine change signalled) is not an acquisition. The first live quiet
    -- frame baselines at once (a loaded save, or the script starting mid-game). After that a
    -- party-count change is learned only after it has stayed quiet across one frame boundary,
    -- so a gift whose GiveMonToPlayer straddles a frame end (party written this frame, return
    -- hook next frame) is still settled as an acquisition, not absorbed. A signalled frame
    -- belongs to settle, which runs after this hook.
    local function observe_known()
        if next(st.flags) then st.observe_at = nil; return end
        local f = io.framecount()
        local count = num(a.PARTY_COUNT_ADDR) and io.read_u8(a.PARTY_COUNT_ADDR) or -1
        -- the quiet interval belongs to one candidate count: a change inside it restarts it
        if st.baselined and st.observe_at == nil then
            if count ~= st.seen_count then st.observe_at, st.observe_count = f + 1, count end
            return
        end
        if st.baselined and count ~= st.observe_count then
            st.observe_at, st.observe_count = f + 1, count
            return
        end
        if st.baselined and f < st.observe_at then return end
        st.observe_at = nil
        if not drv.game_is_live() then return end
        local party = party_read()
        if not party then return end
        update_frozen(party)
        if st.frozen then return end                           -- a borrowed party is never ours
        if not st.baselined then rescan_boxes(); st.baselined = true end
        seed_known(party)
        st.seen_count = count
    end
    -- G5-RR-RIVAL: the PRE-BATTLE announcement. The patch's rival-swap window (W1,
    -- gBattleMainFunc == BeginBattleIntroDummy) is ~5 frames long and opens in the battle_begin
    -- frame itself, while the in_battle read (gBattleMons[0].maxHP) first holds ~30 frames AFTER
    -- it closes (live receipt rr_rival_swap_real_gen3_gen3_rr_as_a_4202b5d8: window 1012-1016,
    -- announcement 1043). The trainerbattle script sets gTrainerBattleOpponent_A ~120 frames
    -- before the battle (891 there), so a trainer battle is announced on that value's EDGE on the
    -- field, with the id of the battle about to begin (battle_seq + 1); its battle_begin carries
    -- the authority in (drv.start) and the staged swap posts in the window (native.lua).
    -- RR companion only (native.rival_window_open); every other artifact keeps note_battle's
    -- in-battle announcement. The value stays set after a battle, so only a CHANGE counts: a
    -- rematch against the SAME id is not pre-announced and falls back to note_battle (the value
    -- is tracked every frame, so a stale post-battle id is never an edge).
    local function pre_announce()
        if not (native and native.rival_window_open and session_nonce and num(a.TRAINER_OPPONENT_ADDR)) then
            return
        end
        local opp = io.read_u16(a.TRAINER_OPPONENT_ADDR)
        local seen = st.opp_seen
        st.opp_seen = opp
        if opp == 0 or seen == nil or opp == seen then return end   -- the first read only latches
        if st.battle or in_battle() then return end
        -- a NOT-YET-BEGUN pre-authority is replaced, never a wall (review F1): the opponent id is
        -- loaded before the script's defeated-trainer check (pret FR ScrCmd_trainerbattle ->
        -- TrainerBattleLoadArgs, then the flag test), so talking to a beaten trainer announces a
        -- battle that never begins; the next trainer's edge must still be announced. A job staged
        -- for the replaced authority fails its guard (trainer mismatch) and is refused.
        local old = rival_authority
        if old and not (old.pre and not old.begun) then return end
        local id = battle_seq + 1
        -- only an announcement that left (or is held for hello) opens the authority (review F4):
        -- a dropped one would stage nothing the server ever answers
        if not send("trainer_battle_start", { trainer_id = opp, battle_id = id, session = session_nonce }) then
            log("trainer " .. opp .. " pre-battle announcement dropped (not connected)")
            return
        end
        rival_authority = {session = session_nonce, battle_id = id, trainer_id = opp,
                           rejected = sig_src and sig_src.rejected, pre = true,
                           opened = io.framecount()}
        st.pre_announced_id = id
        log("trainer " .. opp .. " announced before battle " .. id
            .. (old and (" (replaces trainer " .. tostring(old.trainer_id) .. ")") or ""))
    end
    drv.frame_hooks = { observe_known, settle, pre_announce }

    -- ── command seams ──────────────────────────────────────────────────────────────
    local C = drv.commands
    -- §4.3 selectable-team pre-filter (C5-11a). The engine's own rule, getter semantics:
    -- GetMonData(MON_DATA_SPECIES_OR_EGG) collapses an empty slot, an egg and a BAD EGG to
    -- SPECIES_EGG (pret src/pokemon.c:3245-3249), plus HP != 0, so the predicate is
    -- hp != 0 and species != 0 and not is_egg_flag and not is_bad_egg. Doubles needs two
    -- distinct such mons. Decode-only, from the blobs the command carries. The patch remains
    -- the authority for the WINDOW; this is a pre-filter that keeps an unselectable team from
    -- ever being staged.
    local function selectable_team(cmd)
        -- doubles from the battle's own type flags (C5-11c MAJOR 6): gBattlersCount is not
        -- initialised yet in W1, so the count was the wrong witness.
        local double_mask = d.BATTLE_TYPE_DOUBLE_MASK
        local need = (num(a.BATTLE_TYPE_ADDR) and num(double_mask)
                      and (io.read_u32(a.BATTLE_TYPE_ADDR) & double_mask) ~= 0) and 2 or 1
        local viable = 0
        for _, hex in ipairs(cmd.blobs_hex or {}) do
            local raw = {}
            for i = 1, 200, 2 do raw[#raw + 1] = tonumber(hex:sub(i, i + 1), 16) end
            local mon = reads.decode_party_mon(raw)
            -- getter semantics (pret src/pokemon.c:3182-3183, 3245-3249): MON_DATA_SPECIES_OR_EGG
            -- returns SPECIES_EGG when species != 0 && (SECURE Misc.isEgg || boxMon.isBadEgg) --
            -- the decoded `is_egg` is that secure bit; the header `is_egg_flag` is not enough.
            if mon and mon.hp ~= 0 and mon.species ~= 0 and mon.is_egg == 0
               and mon.is_bad_egg == 0 then
                viable = viable + 1
            end
        end
        if viable >= need then return true end
        return false, "slots_unviable"
    end

    -- The dispatch-time revalidation (C5-11a BLOCKER). The job carries an IMMUTABLE epoch snapshot
    -- and this runs immediately before the post, so a job queued behind a menu cannot act after
    -- the battle it was minted for has ended -- the case Codex reproduced (battle1/sessionS/id1,
    -- battle2 same trainer/id2, the old request posting into battle2). `st.battle` alone is not
    -- enough: lua/core/session.lua services native BEFORE this frame's signal drain, which is why
    -- pre_pump sweeps the boundary first (below) and why the live reads are checked here too.
    -- C5-11d MAJOR 4: the authority is closed BY signals, so it cannot outlive their delivery. A
    -- source that failed (signals.lua:126 -- a fire can fail before on_fire runs), was closed
    -- (hooks uninstalled), was never armed, or has rejected a callback since the authority opened
    -- (a boundary fire counted and dropped, signals.lua:97-100) may have missed the boundary that
    -- should have closed it. Read here, at the ONE consumer, from the source's own fields, so no
    -- path that stops delivery -- however its flag got set -- leaves the authority usable.
    local function live_authority()
        local s, a = sig_src, rival_authority
        if a and not (s and not s.failure and not s.closed and s.rejected == a.rejected) then
            rival_authority = nil
            log("rival authority revoked: engine signals are not being delivered")
        end
        return rival_authority
    end
    local function rival_epoch_guard(epoch)
        -- the AUTHORITY, not the reducer's st.battle: it is closed at signal capture, so a job
        -- minted for an earlier battle can never post after a same-frame boundary (BLOCKER 2).
        local now = live_authority()
        if now == nil then return false, "stale_battle_id" end
        if now.session ~= epoch.session or now.battle_id ~= epoch.battle_id
           or now.trainer_id ~= epoch.trainer_id then
            return false, "stale_battle_id"
        end
        -- a pre-announced battle (G5-RR-RIVAL) posts in the W1 window, before the in_battle read
        -- holds: its own battle_begin must have carried the authority (`begun`); the patch's
        -- five-part check stays the authority for the window itself
        if not in_battle() and not (now.pre and now.begun) then return false, "not_in_battle" end
        local live = battle_now()
        if not (live and live.is_trainer and num(live.trainer_id)
                and live.trainer_id == epoch.trainer_id) then
            return false, "stale_battle_id"
        end
        return true
    end
    -- G5-RR-RIVAL: how long a pre-announced swap may wait in native.lua's queue for the W1 window
    -- (native job `ready`): true = keep holding. Only a pre-battle authority holds; the battle must
    -- begin within RIVAL_HOLD frames of the announcement and the window open within RIVAL_WINDOW
    -- frames of battle_begin. When the hold ends the job is dispatched anyway and its guard (or the
    -- patch's REASON_WINDOW_CLOSED) refuses it cleanly -- a hold never becomes a silent drop.
    local RIVAL_HOLD, RIVAL_WINDOW = 3600, 30
    local function rival_hold(epoch)
        local now = live_authority()
        if not (now and now.pre and now.session == epoch.session and now.battle_id == epoch.battle_id
                and now.trainer_id == epoch.trainer_id) then
            return false
        end
        if not now.begun then return io.framecount() - now.opened < RIVAL_HOLD end
        return io.framecount() - now.begun < RIVAL_WINDOW
    end

    -- rival swap is a companion-mailbox feature (OP_RIVAL_SWAP 28, C5-11a; 16 stays the trade's).
    -- Without the patch: the old client's refusal (archive/gen3-old-client:lua/clients/gen3_frlge_client.lua:824-837).
    C.replace_rival_team = function(cmd)
        local function refuse(why)
            send("rival_team_replaced", { trainer_id = cmd.trainer_id or 0, species_ids = arr({}),
                                          error = why })
        end
        local trainer = cmd.trainer_id
        local current = st.battle
        local ra = live_authority()
        if ra and ra.pre and session_nonce ~= nil and type(cmd.session) == "string"
           and cmd.session == ra.session and cmd.battle_id == ra.battle_id
           and type(trainer) == "number" and trainer == ra.trainer_id then
            -- G5-RR-RIVAL: the swap for a PRE-announced battle (usually still on the field). It is
            -- STAGED in native.lua and posted in the W1 window. Selectability is checked ONLY at
            -- dispatch (OMP F6): on the field gBattleTypeFlags still holds the LAST battle's bits,
            -- so a stale doubles bit would refuse a singles swap here.
            if not eligible() then
                log("replace_rival_team: session not eligible (writes paused); nothing staged")
            elseif native and native.replace_rival_team then
                log("replace_rival_team staged for the window (battle " .. tostring(ra.battle_id) .. ")")
                native:replace_rival_team(cmd, function(epoch)
                    local gok, gwhy = rival_epoch_guard(epoch)
                    if not gok then return gok, gwhy end
                    return selectable_team(cmd)
                end, rival_hold)
            else
                refuse("patch_required")
            end
        elseif not in_battle() then
            refuse("not_in_battle")
        -- MAJOR 1 (Codex C5-10 review): the no-epoch case FIRST -- a client attached mid-battle
        -- has no identity to compare against and must refuse by name, never index a nil record.
        elseif session_nonce == nil then
            -- fail closed: no identity was minted, so nothing can be validated
            log("replace_rival_team refused: stale_battle_id (no session nonce)")
            refuse("stale_battle_id")
        elseif current == nil then
            log("replace_rival_team refused: stale_battle_id (no epoch)")
            refuse("stale_battle_id")
        elseif type(cmd.battle_id) ~= "number" or cmd.battle_id % 1 ~= 0
            or type(cmd.session) ~= "string" or cmd.session ~= current.session
            or cmd.battle_id ~= current.battle_id then
            log("replace_rival_team refused: stale_battle_id (counter=" .. tostring(cmd.battle_id)
                .. " session=" .. tostring(cmd.session) .. " current="
                .. tostring(current.battle_id) .. "/" .. tostring(current.session) .. ")")
            refuse("stale_battle_id")
        -- trainer matching is mandatory and has no shortcuts: a missing, non-numeric, zero,
        -- out-of-range or non-matching id is refused, and so is an epoch whose trainer is unknown.
        elseif type(trainer) ~= "number" or trainer % 1 ~= 0 or trainer <= 0 or trainer > 65535
            or type(current.trainer_id) ~= "number" or current.trainer_id ~= trainer then
            log("replace_rival_team refused: stale_battle_id (trainer=" .. tostring(trainer)
                .. " current=" .. tostring(current.trainer_id) .. ")")
            refuse("stale_battle_id")
        else
            local ok, why = selectable_team(cmd)
            if not ok then
                log("replace_rival_team refused: " .. why)
                refuse(why)
            elseif not eligible() then
                log("replace_rival_team: session not eligible (writes paused); nothing staged")
            elseif native and native.replace_rival_team then
                native:replace_rival_team(cmd, rival_epoch_guard)
            else
                refuse("patch_required")
            end
        end
        return true
    end

    -- Durable trade is a separate protocol owner. It never writes; native owns every stage.
    -- V1 companions have no save witness and therefore cannot implement this capability.
    local function sync_trade()
        if not trade then return end
        local active, prepared = trade:state()
        st.trade_apply = active or prepared
        st.trade_unresolved = trade:uncertainties()
    end
    if native and p.Trade and owed and p.artifact_kind == "companion" then
        trade = p.Trade.new({native=native, frame=io.framecount, eligible=eligible,
            ready_to_send=function() return session and session.hello_sent and p.net.connected() end,
            clear=function() return not in_battle() and overworld_ok() end,
            party=party_read, key=key, capacity=d.PARTY_CAPACITY or 6, mon_size=R.PARTY_MON_SIZE,
            send=function(event, fields)
                if event == "trade_done" then
                    owed.list[#owed.list+1] = {event=event, fields=fields}
                    return true
                end
                return send(event, fields)
            end,
            completed=function(t, changed, party, mon)
                if changed then
                    local new_key = key(mon)
                    st.known[t.old_key], st.alive[t.old_key], st.commanded[t.old_key] = nil, nil, nil
                    st.known[new_key] = true
                    local items = session.deferred.items
                    for i=#items,1,-1 do
                        local q=items[i]
                        if (q.key == t.old_key or q.key == new_key)
                           and (q.cmd == "box_mon" or q.cmd == "party_mon" or q.cmd == "memorialize") then
                            table.remove(items,i)
                        end
                    end
                    seed_known(party); rebaseline(party)
                    st.trade_settle_until = io.framecount() + st.trade_limits.settle
                end
            end})
    end
    C.apply_prepare = function(cmd)
        if trade then trade:prepare(cmd); sync_trade()
        else send("apply_ready", {token=cmd.token, ok=false}) end
        return true
    end
    C.apply_trade = function(cmd)
        if trade and trade:capable() then trade:apply(cmd); sync_trade()
        else log("apply_trade refused: durable native trade unavailable") end
        return true
    end
    C.withdraw_trade = function(cmd)
        if trade then trade:withdraw(cmd); sync_trade() end
        return true
    end
    drv.after_receive = function()
        if trade then trade:tick(); sync_trade() end
        if owed then
            local refresh=false
            owed:step(p.net.connected(), session.hello_sent == true, function(event, fields)
                local sent=send(event,fields)
                if sent and event == "trade_done" and fields.uncertain and fields.after_reset
                   and trade and trade:reloaded(fields.token) then refresh=true end
                return sent
            end)
            -- Server only consumes a hello AFTER the uncertainty declaration. This second
            -- hello is allowed only after the real reset boundary, never from unsaved RAM.
            if refresh then session.hello_sent=false end
        end
    end
    -- native pickers/menus (RR PC trade NPC); otherwise the core answers with the cancel sentinels
    -- Once native takes a prompt it owns the answer (its done callback replies, including the
    -- cancel sentinel on refusal), so the command is CONSUMED: no second, core-made ACK.
    for _, name in ipairs(MENU_CMDS) do
        C[name] = function(cmd)
            if native and native[name] and eligible() then
                native[name](native, cmd)
                return true
            end
            return false
        end
    end
    C.link_panel = function(cmd)                               -- the RR info panel (native)
        if native and native.link_panel then native:link_panel(cmd) end
        return true
    end
    C.config = function(cmd)                                   -- the session stores it too
        if native and native.config then native:config(cmd) end
        return false
    end
    C.ghost_pos = function() return true end                   -- peer ghost: post-RC (PLAN §0)
    -- Sound: the native SE when the companion is present, else the old client's m4a SE1 poke
    -- (archive/gen3-old-client:lua/memory_gba.lua M.playSE) as a GATED write, writes:arm("sound", allow, {player, track})
    -- over exactly the pack block's fields. WHETHER it may land (driver initialised, addresses in
    -- IWRAM) is safety's sound clause set, re-checked before every byte; the client only
    -- resolves addresses. Any refusal means no sound, logged once per reason.
    local function sound_refused(why)
        if not st.sound_logged[why] then
            st.sound_logged[why] = true
            log("sound refused: " .. why)
        end
    end
    -- SE1: the pack's static gMPlayInfo_SE1 (FR/LG), else resolved at runtime from the pack's
    -- gSoundInfo pointer (MPlayOpen prepends, so the list is gMPlayTable reversed and SE1 is its
    -- second-to-last node). A pack naming neither (RR today) is refused by name.
    local function se1_player(snd)
        if type(snd.player_se1) == "table" and num(snd.player_se1.address) then
            return snd.player_se1.address
        end
        local ptr = type(snd.sound_info_ptr) == "table" and num(snd.sound_info_ptr.address) or nil
        if not ptr then return nil, "the pack's sound block names no SE1 player and no gSoundInfo pointer" end
        local lo, hi = snd.iwram_min, snd.iwram_max
        local function iw(v) return v >= lo and v < hi end
        local info = io.read_u32(ptr)
        if not iw(info) then return nil, "gSoundInfo not initialised" end
        local nodes, cur = {}, io.read_u32(info + snd.player_head_off)
        while iw(cur) and #nodes < 16 do nodes[#nodes + 1] = cur; cur = io.read_u32(cur + snd.player_next_off) end
        if #nodes < 2 then return nil, "m4a player list not initialised" end
        return nodes[#nodes - 1]
    end
    -- id: the TITLE's song id (drv.play_sound translates the wire id once, for both paths)
    local function m4a_plan(id)
        local snd = p.sound
        if type(snd) ~= "table" or type(snd.fields) ~= "table" then
            return nil, "no sound block in the checkpoint pack"
        end
        local headers = profile.rom and profile.rom.SE_SONG_HEADERS
        local hdr = type(headers) == "table" and num(headers[tostring(id)]) or nil
        if not hdr then return nil, "pack has no song header for SE " .. tostring(id) end
        local player, why = se1_player(snd)
        if not player then return nil, why end
        local track = io.read_u32(player + snd.tracks_off) + (snd.track0_off or 0)
        local F = {}
        for _, f in ipairs(snd.fields) do F[f.on .. "." .. f.name] = f end
        local function at(on, name)
            local f = assert(F[on .. "." .. name], "sound block has no field " .. on .. "." .. name)
            return (on == "player" and player or track) + f.offset, f.size
        end
        -- the header and the track-0 script it points at must be in ROM, and the track count a
        -- real m4a one (pret include/gba/m4a_internal.h MAX_MUSICPLAYER_TRACKS = 16): a garbage
        -- header (LG shipped FR's SE addresses) must be refused here, before any plan exists
        local function in_rom(v, len) return v >= 0x08000000 and v + (len or 1) <= 0x0A000000 end
        local se = "SE " .. tostring(id) .. " song header " .. string.format("0x%X", hdr)
        if not in_rom(hdr, 12) then return nil, se .. " is not in ROM" end
        local h = io.rom_read(hdr - 0x08000000, 12)
        local count, priority = h[1], h[3]
        local cmd_ptr = h[9] + h[10] * 256 + h[11] * 65536 + h[12] * 16777216
        -- ponytail: 16 is m4a's hard cap; SE1's own allocated tracks (gMPlayTable) are tighter,
        -- use them if a pack ever names them
        if not (count >= 1 and count <= 16) then
            return nil, se .. " has trackCount " .. count .. " (m4a allows 1..16)"
        end
        if not in_rom(cmd_ptr) then
            return nil, se .. string.format(" has a track pointer 0x%X outside ROM", cmd_ptr)
        end
        local plan = {}
        local function put(on, name, value, width)
            local addr, size = at(on, name)
            plan[#plan + 1] = { addr, width or size, value }
        end
        -- No ident lock/unlock: the frame-end callback runs between emulated instructions, so the
        -- ISR cannot see a half-set player, and the sound clause set (re-checked before every
        -- byte) requires ident == magic -- a lock value would refuse the rest of the plan.
        -- status goes LAST: it is what makes the next VBlank start the song.
        put("player", "songHeader", hdr)
        put("player", "trackCount", count)
        put("player", "priority", priority)
        put("player", "clock", 0)
        put("track", "flags", 0)
        put("track", "flags", TRK_START, 1)
        put("track", "bendRange", TRK_BEND)
        put("track", "volX", TRK_VOLX)
        put("track", "lfoSpeed", TRK_LFO)
        put("track", "chan", 0)
        put("track", "cmdPtr", cmd_ptr)
        put("player", "status", (1 << count) - 1)
        return plan, { player = player, track = track }
    end
    drv.play_sound = function(id)
        if not eligible() then return sound_refused("session not eligible") end
        local f = io.framecount()
        if st.sound_frame == f then return end              -- one cue per frame
        st.sound_frame = f
        -- the wire id keeps FR numbering (docs/protocol.md "play_sound ids"); the pack's se_ids
        -- maps it to this title's song id, and an id it does not map is refused. Translated ONCE,
        -- before either path: the companion's OP_PLAY_SE plays a song number of the running ROM
        -- (native.lua play_sound), exactly what the m4a poke needs, so both take the title id.
        -- (RR's map is identity today; asserting identity would only refuse a future native title.)
        local snd = type(p.sound) == "table" and p.sound or {}
        local sid = type(snd.se_ids) == "table" and num(snd.se_ids[tostring(id)]) or nil
        if not sid then return sound_refused("pack maps no title SE for wire id " .. tostring(id)) end
        if native and native.play_sound and native:play_sound(sid) then return end
        local plan, args = m4a_plan(sid)
        if not plan then return sound_refused(args) end
        local ok, awhy = armed_write("sound", plan, args)
        if not ok then sound_refused(tostring(awhy)) end
    end
    local trade_frame
    drv.pre_pump = function()
        if owed then owed:step(p.net.connected(), false, send) end
        if trade_frame and io.framecount() < trade_frame then
            if trade then trade:reset(false); sync_trade() end
            session.hello_sent = false
        end
        trade_frame = io.framecount()
        if not (native and native.service) then return end
        -- C5-11c MAJOR 3: this used to clear st.battle on a live boundary, which made
        -- finish_battle skip the encounter result (RR companion then sent no no_catch where RR
        -- clean did). The rival authority above replaces it and never touches the lifecycle.
        native:service()
        sync_trade() -- each native job's own publication receipt, never inferred from sink bytes
    end

    local Id = core.Identity.new({ key = key })
    local Q = core.Deferred.new({ exec = exec, memorial_box = memorial_box })
    local transport = p.net
    if owed then
        transport = setmetatable({
            send=function(line) local result=p.net.send(line); owed:line_sent(); return result end,
            receive=function()
                local line=p.net.receive()
                if line ~= nil then
                    owed:line_received()
                    local ok, reply=pcall(json.decode,line)
                    if ok and type(reply)=="table" and type(reply.commands)=="table" then owed:answer(reply.commands) end
                end
                return line
            end}, {__index=p.net})
    end
    session = core.Session.new({ net = transport, json = json, hud = hud, log = sink, tag = TAG,
                                 player = p.player, game = drv, identity = Id, deferred = Q })
    session.driver, session.state = drv, st
    local base_send = session.send
    session.send = function(a, b, c)
        local event = (a == session) and b or a
        if event == "trade_request" and st.trade_apply then
            log("trade_request dropped: a trade is in flight")
            return false
        end
        return base_send(a, b, c)
    end
    return session
end

return Client
