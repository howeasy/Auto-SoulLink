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
--   below owns apply_trade: identity, preflight, lifecycle, readback, fallback, trade_done)
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

-- Record geometry and game constants the packs do not ship yet (requested from C4-2a).
-- pret/pokefirered@c75f352 include/pokemon.h struct Pokemon / struct BattlePokemon, and the
-- old client's production values (lua/memory_gba.lua:395-416); CFRU keeps the same layout.
local PARTY_HP_OFF = 0x56            -- struct Pokemon.hp (u16)
local BATTLE_MON_MOVES_OFF = 0x0C    -- BattlePokemon.moves[4] (u16 each)
local BATTLE_MON_PP_OFF = 0x24       -- BattlePokemon.pp[4] (u8 each)
local MOVE_EXPLOSION = 153           -- include/constants/moves.h
local EXPLODE_PP = 5                 -- Explosion's PP, so a PP drop proves the move executed
-- CFRU action-commit values (lua/memory_gba.lua:1318-1345, production-tested on RR):
local B_ACTION_USE_MOVE = 0
local STATE_ACTION_CONFIRMED_STANDBY = 3
local TARGET_FOE_PRIMARY = 1
-- The m4a SE1 poke (the old client's M.playSE, lua/memory_gba.lua:2021-2066, production-tested
-- on FR/LG and RR). Every address and field offset comes from the checkpoint pack's sound block
-- (p.sound: player_se1 / sound_info_ptr, player_head_off / player_next_off / tracks_off, and
-- `fields`, the exact m4a fields a sound write may touch); only the VALUES the old client
-- stores are here.
local TRK_START = 0xC0                        -- MusicPlayerTrack.flags: EXIST | START
local TRK_BEND, TRK_VOLX, TRK_LFO = 2, 64, 22 -- the old client's per-track defaults
-- Gift/static areas (server/adapters/gen3_frlge.py via lua/games/gen3_frlge.lua:27-37): no
-- NEW ENCOUNTER banner and never a no_catch there.
local GIFT_AREAS = { oaks_lab = true, intro = true, gift = true, cinnabar_lab = true,
                     celadon_condominiums = true, silph_co_7f = true, saffron_dojo = true,
                     route_4_pokecenter = true }
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
    local a, d = profile.ram, profile.derived
    local arr = json.array
    local area_map, locations = p.area_map or {}, p.locations or {}
    local sink = p.log or function() end
    local TAG = "[SLink-gen3]"
    local function log(msg) sink(TAG .. " " .. msg) end
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

    local st = {
        known = {},        -- every key this save has shown us (party + boxes): acquisitions are NEW keys
        alive = {},        -- keys last seen with hp > 0: a faint is alive -> hp 0 at a faint site
        commanded = {},    -- keys WE zeroed: their faint is not reported (old client force_fainted_keys)
        party_prev = {},   -- key -> { slot, level, max_hp } at the last settle (PC diff baseline)
        carried = {},      -- keys that left the party into the PC cursor, not yet placed
        box_cache = {}, boxes_ok = false,
        battle = nil,      -- battle_begin .. battle_end lifecycle
        frozen = false,    -- a borrowed party is in RAM
        flags = {},        -- what the signals of this frame said changed
        has_pokeballs = false, last_area = nil, trade = nil, sound_frame = nil, sound_logged = {},
        baselined = false, seen_count = nil, observe_at = nil,
        trade_apply = nil, trade_settle_until = 0,
        trade_unresolved = {},   -- token -> the unresolved transaction, each watched for its own late fact
        -- field_wait: frames an apply waits for a clear field before the silent swap (old client
        -- :2250); backstop: frames after the scene post before a lost ACK is reconciled from the
        -- slot, LONGER than the patch's own ~5400-frame scene timeout (old client :563-566)
        trade_limits = { field_wait = 1800, backstop = 6000, settle = 30 },
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
    local function party_entry(m, active)
        local base = reads.party_base and reads.party_base()
        local raw = base and io.read_bytes(base + m.slot * R.PARTY_MON_SIZE, R.PARTY_MON_SIZE)
        return { key = key(m), slot = m.slot, species_id = m.species, nickname = m.nickname,
                 level = m.level, hp = m.hp, maxHP = m.max_hp, status_cond = m.status,
                 moves = arr(m.moves), pp = arr(m.pp), pp_bonuses = m.pp_bonuses,
                 held_item_id = m.held_item, active = active[m.slot] or false,
                 blob_hex = raw and hex_of(raw) or nil }
    end
    local function party_wire(party)
        local active = {}
        if in_battle() then
            local b = battle_now()
            for _, s in ipairs(b and b.active_player_battler_slots or {}) do active[s] = true end
        end
        local out = arr({})
        for i, m in ipairs(party) do out[i] = party_entry(m, active) end
        return out
    end
    local function enemy_wire(b)
        local out = arr({})
        if not b then return out end
        local idx, active = b.battler_party_indexes or {}, {}
        if idx[2] then active[idx[2]] = true end
        if (b.battlers_count or 0) >= 4 and idx[4] then active[idx[4]] = true end
        for _, m in ipairs(b.enemy_party or {}) do
            if m.species and m.species ~= 0 then
                out[#out + 1] = { species_id = m.species, level = m.level, hp = m.hp, maxHP = m.max_hp,
                                  active = active[m.slot] or false, held_item_id = m.held_item,
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
        return cache
    end
    local function pc_boxes_wire()
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
    -- the old client's snapshot, gen3_frlge_client.lua:1625-1639.
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
            if area_id ~= "" and not GIFT_AREAS[area_id] and not gift then session.resolved_areas[area_id] = true end
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
            if st.has_pokeballs and session.seeded and area_id ~= "" and not GIFT_AREAS[area_id]
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
        if b.is_trainer and num(b.trainer_id) and b.trainer_id ~= 0 and not bt.trainer_sent then
            bt.trainer_sent = true
            send("trainer_battle_start", { trainer_id = b.trainer_id })
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
           and area_id ~= "" and not GIFT_AREAS[area_id] and not session.resolved_areas[area_id] then
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
        local trading = (st.trade_apply ~= nil and st.trade_apply.posted == true)
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

    -- one armed window, one reason, one allow set; returns true or nil, why
    -- args: what the reason's clause set needs (battle_commit: {battler}; sound: {player, track})
    local function armed_write(reason, plan, args)
        local snap, why = policy:snapshot()
        if not snap then return nil, why end
        local ok, cwhy = policy:check(snap, reason, args)
        if not ok then return nil, cwhy end
        local allow = {}
        for _, w in ipairs(plan) do allow[w[1] .. ":" .. w[2]] = true end
        local wok, err = pcall(function()
            writes:arm(reason, function(x, n) return allow[x .. ":" .. n] == true end, args)
            for _, w in ipairs(plan) do
                if w[2] == 4 then writes:write_u32(w[1], w[3])
                elseif w[2] == 2 then writes:write_u16(w[1], w[3])
                else writes:write_bytes(w[1], { w[3] }) end
            end
        end)
        writes:disarm()
        if not wok then return nil, tostring(err) end
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

    -- The Variant-3 menu skip (lua/memory_gba.lua:1303-1345): every move slot of the battler
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
        -- LAST: the committing state is itself the battle_commit guard (gBattleCommunication
        -- [battler] < 3) and writes.lua re-validates before every write, so any write after it
        -- would be refused mid-plan and leave a half-committed action
        plan[#plan + 1] = { a.BATTLE_COMM_ADDR + battler, 1, STATE_ACTION_CONFIRMED_STANDBY }
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
            if comm < STATE_ACTION_CONFIRMED_STANDBY then
                ex.failed, ex.why = true, "explosion failed; held as the active battler"
                log("force_explode: Explosion executed and the battler survived; held as active " .. e.key)
                return "hold", "explosion failed; held as the active battler"
            end
            return "hold", "explosion executing"
        end
        if ex and comm >= STATE_ACTION_CONFIRMED_STANDBY then return "hold", "explosion committed" end
        -- first commit, or the engine reset the commit state at turn start: (re)write it
        local ok, why = armed_write("battle_commit", commit_plan(battler, not ex), { battler = battler })
        if not ok then return "hold", why end
        if not ex then
            e.explode = { battler = battler }
            mark_commanded(key(mon))
            log("force_explode: menu skip committed slot=" .. slot .. " battler=" .. battler)
        end
        return "hold", "explosion committed"
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
            -- the engine refreshes an active battler's gBattleMons: a direct write races it
            -- (old client :2555-2596). Held until it switches out or the battle ends.
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
        st.known, st.alive, st.commanded, st.party_prev, st.carried = {}, {}, {}, {}, {}
        st.box_cache, st.boxes_ok, st.battle, st.frozen, st.flags = {}, false, nil, false, {}
        st.last_area, st.trade = nil, nil
        st.baselined, st.seen_count, st.observe_at = false, nil, nil
        st.trade_apply, st.trade_settle_until, st.trade_unresolved = nil, 0, {}   -- the save is gone
    end

    -- No wire side effect here (no area_enter, no banner): hello is the connection's first line.
    function drv.hello_fields()
        local party = party_read() or {}
        update_frozen(party)
        rescan_boxes()
        -- a borrowed party is never published nor learned as ours (docs/protocol.md §9 item 11):
        -- hello.party stays present and empty, exactly like tick_fields' guard
        local own = st.frozen and {} or party
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
                    area_id = area_id, loc_name = loc, has_pokeballs = st.has_pokeballs,
                    in_battle = in_battle(), badges = badges(), ball_count = ball_count() }
        local t = trainer()
        if t then f.ot_id, f.trainer_name = t.ot_id, t.name end
        if native and native.hello_fields then
            for k, v in pairs(native:hello_fields() or {}) do f[k] = v end
        end
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
        if not st.frozen then f.party = party_wire(party) end
        if st.boxes_ok then f.pc_boxes = pc_boxes_wire() end
        local t = trainer()
        if t then f.trainer_name = t.name end
        return f
    end

    function drv.start()
        return p.Signals.new(profile, p.sites, io, p.ev, nil)
    end

    function drv.on_signal(sig)
        local k, f = sig.kind, st.flags
        if k == "battle_begin" then
            -- the pre-battle party is the borrowed-party reference
            local base = {}
            for pk in pairs(st.party_prev) do base[pk] = true end
            st.battle = { caught = false, base_keys = base }
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
    drv.frame_hooks = { observe_known, settle }

    -- ── command seams ──────────────────────────────────────────────────────────────
    local C = drv.commands
    -- rival swap is a companion-mailbox feature (OP_SET_ENEMY_PARTY, P5 native.lua). Without
    -- the patch: the old client's refusal (gen3_frlge_client.lua:824-837).
    C.replace_rival_team = function(cmd)
        if not in_battle() then
            send("rival_team_replaced", { trainer_id = cmd.trainer_id or 0, species_ids = arr({}), error = "not_in_battle" })
        elseif not eligible() then
            log("replace_rival_team: session not eligible (writes paused); nothing staged")
        elseif native and native.replace_rival_team then
            native:replace_rival_team(cmd)
        else
            send("rival_team_replaced", { trainer_id = cmd.trainer_id or 0, species_ids = arr({}), error = "patch_required" })
        end
        return true
    end
    -- the disabled-foundation write guard (PLAN §10): no trade path -> nothing written, no reply
    -- ── the RR PC trade (apply_trade), PLAN §5.6, docs/protocol.md §6.2 ───────────
    -- The Gen 1 standard's shape (lua/gen1/client.lua:1594-1765) over the old RR client's native
    -- sequence (gen3_frlge_client.lua:2211-2293): every byte is a native.lua transfer, i.e.
    -- writes:arm("native") over the mailbox and BLOB_BUF; this FSM writes nothing itself.
    --   wait      buffered until a clear field (the overworld checkpoint) with an eligible
    --             session; the offered mon is re-located by old_key (the slot is a snapshot).
    --             Nothing is owned yet: unrelated signals keep reducing normally.
    --   stage     transfer("enemy", {blob}) = OP_SET_ENEMY_PARTY: the partner mon into
    --             gEnemyParty[0] (no slot involved)
    --   scene     transfer("scene", {slot}) = OP_TRADE_SCENE
    --   fallback  transfer("party", {slot, blob}) = OP_SET_PARTY_MON, the silent faithful swap
    --   scene_lost the scene's ACK was lost: nothing is written, wait the backstop
    --   readback  the op reported done (or its ACK was lost): read the party back by KEY
    -- Every slot op carries a DISPATCH-TIME guard (native.lua runs it just before posting, in
    -- the same frame-end callback): the offered key is re-located at that instant; moved means
    -- re-post at its new slot, unreadable means try again, gone means nothing is posted.
    -- Completions report only FACTS read back: the partner's key present = the swap landed; the
    -- offered key still present after a done/lost op = unchanged. When the trade failed or the
    -- result cannot be read (stage poisoned, silent swap failed, no conclusive read-back) NO
    -- trade_done is sent and nothing is purged: the trade is "unresolved", the server watchdog's
    -- inferred-key commit settles it (PLAN §5.6/§10, the recorded limit), and a later read-back
    -- that finds the partner's mon still reports that fact. The one unchanged-key trade_done
    -- without a read-back fact stays the Gen 1 standard's: the offered mon cannot be located
    -- unambiguously, so no bystander slot is ever written (old client :692 ponytail).
    local function partner_key_of(hex)
        local function u32(off)
            local v = 0
            for i = 3, 0, -1 do v = v * 256 + tonumber(hex:sub(2 * (off + i) + 1, 2 * (off + i) + 2), 16) end
            return v
        end
        return string.format("%08X:%08X", u32(0), u32(4))
    end
    -- where are the partner's mon and the offered mon now (by key, so a reorder cannot fool it)
    local function trade_evidence(t)
        local party = party_read()
        if not party then return nil end
        local got, old
        for _, m in ipairs(party) do
            local k = key(m)
            if k == t.partner_key then got = m end
            if k == t.old_key then old = m end
        end
        return party, got, old
    end
    local function trade_report(t, party, mon, changed, how)
        local new_key = changed and key(mon) or t.old_key
        local slot = mon and mon.slot or t.slot
        local species = changed and mon.species or 0
        if st.trade_apply == t then st.trade_apply = nil end
        if st.trade_unresolved[t.token] == t then st.trade_unresolved[t.token] = nil end
        st.trade_settle_until = io.framecount() + st.trade_limits.settle
        if changed then
            -- a local key migration only (protocol §6.5): the server re-keys from trade_done
            st.known[t.old_key], st.alive[t.old_key], st.commanded[t.old_key] = nil, nil, nil
            st.known[new_key] = true
            -- box moves queued for either key are stale now the mon changed players (old :3423-3429)
            local items = session.deferred.items
            for i = #items, 1, -1 do
                local q = items[i]
                if (q.key == t.old_key or q.key == new_key)
                   and (q.cmd == "box_mon" or q.cmd == "party_mon" or q.cmd == "memorialize") then
                    log("trade: purged the queued " .. q.cmd .. " " .. tostring(q.key))
                    table.remove(items, i)
                end
            end
        end
        if party then seed_known(party); rebaseline(party) end
        log("trade: " .. how .. "; trade_done " .. t.old_key .. " -> " .. new_key)
        send("trade_done", { token = t.token, slot = slot, new_key = new_key, new_species = species })
    end
    local function trade_unresolved(t, why)
        if st.trade_apply ~= t then return end
        st.trade_apply = nil
        st.trade_unresolved[t.token] = t
        t.phase = "unresolved"
        log("TRADE UNRESOLVED: " .. why .. "; no trade_done, nothing purged (the server watchdog settles it)")
        hud.show("TRADE UNRESOLVED: " .. why, 255, 120, 60, 600)
    end
    local function trade_abort(t, why)
        if st.trade_apply ~= t then return end
        st.trade_apply = nil
        log("trade ABORTED: " .. why .. "; no swap performed, no completion")
    end
    -- the owned op said done (or went silent): report what the party shows, else keep reading
    local function trade_readback(t, how)
        if st.trade_apply ~= t then return end
        local party, got, old = trade_evidence(t)
        if party and got then return trade_report(t, party, got, true, how) end
        if party and old then return trade_report(t, party, old, false, how .. " (unchanged)") end
        if t.phase ~= "readback" then
            t.phase, t.readback_why, t.readback_since = "readback", how, io.framecount()
            log("trade: " .. how .. "; no conclusive read-back yet, no trade_done")
        end
    end
    -- one native transfer; done(why, result) fires exactly once (native.lua calls it on refusal
    -- at enqueue too; an argument refusal returns without calling it). The returned job handle is
    -- this post's own dispatch receipt: `handle.posted` is set when native.lua publishes that
    -- job's opcode -- and never for a refused, guarded-off or still-queued job.
    local function transfer(t, step, args, on_done, valid)
        local fired = false
        local handle, why = native:transfer(step, args, function(w, r) fired = true; on_done(w, r) end, valid)
        if not handle and not fired then on_done(why or "transfer refused") end
        if handle then
            t.posts = t.posts or {}
            t.posts[#t.posts + 1] = handle
        end
        return handle
    end
    -- the dispatch-time guard for a slot op: the offered key must be exactly at t.slot NOW
    local function slot_guard(t)
        return function()
            if st.trade_apply ~= t then return false, "guard:stale" end
            local party = party_read()
            if not party then return false, "guard:unreadable" end
            local slot = session.identity:find_party_slot(t.old_key, party)
            if slot == nil then return false, "guard:lost" end
            if slot ~= t.slot then t.moved_to = slot; return false, "guard:moved" end
            return true
        end
    end
    local post_fallback
    local function post_scene(t)
        t.phase, t.scene_frame = "scene", t.scene_frame or io.framecount()
        transfer(t, "scene", { slot = t.slot }, function(swhy)
            if st.trade_apply ~= t or swhy == "guard:stale" then return end
            if not swhy then return trade_readback(t, "native scene complete") end
            if swhy == "guard:moved" then t.slot = t.moved_to; return post_scene(t) end
            if swhy == "guard:unreadable" then return post_scene(t) end
            if swhy == "guard:lost" then
                -- nothing was posted for the slot and the offered mon cannot be located: the
                -- Gen 1 standard's "nothing changed"
                return trade_report(t, party_read(), nil, false, "the offered mon left the party before the scene")
            end
            if swhy == "native refused" or swhy == "native absent" then
                return post_fallback(t, "scene " .. swhy)
            end
            -- the ACK was lost (timeout, overwritten sequence): the scene may still be running
            -- natively, so nothing is written; the backstop reads the party back
            t.phase = "scene_lost"
            log("trade: scene ACK lost (" .. swhy .. "); waiting the backstop, no overwrite")
        end, slot_guard(t))
    end
    post_fallback = function(t, why)
        t.phase = "fallback"
        transfer(t, "party", { slot = t.slot, blob_hex = t.blob_hex }, function(fwhy)
            if st.trade_apply ~= t or fwhy == "guard:stale" then return end
            if not fwhy then return trade_readback(t, "silent swap after " .. why) end
            if fwhy == "guard:moved" then t.slot = t.moved_to; return post_fallback(t, why) end
            if fwhy == "guard:unreadable" then return post_fallback(t, why) end
            if fwhy == "guard:lost" then
                -- the pre-trade mon is not in the party: never swap on top of a scene that may
                -- have swapped (the old "pairs break" double write); read back what is there
                return trade_readback(t, why .. "; the offered mon is gone before the silent swap")
            end
            trade_unresolved(t, "silent swap failed (" .. fwhy .. ") after " .. why)
        end, slot_guard(t))
    end
    local function post_stage(t)
        t.phase = "stage"
        st.known[t.partner_key] = true                             -- never a capture if it lands
        transfer(t, "enemy", { blobs_hex = { t.blob_hex } }, function(why)
            if st.trade_apply ~= t or why == "guard:stale" then return end
            if why == "native absent" then return trade_abort(t, "companion absent") end
            if why then return post_fallback(t, "stage " .. why) end
            post_scene(t)
        end, function()
            if st.trade_apply ~= t then return false, "guard:stale" end
            return true
        end)
    end
    local function trade_tick()
        local f = io.framecount()
        for _, u in pairs(st.trade_unresolved) do
            -- a later read-back that finds a transaction's partner mon is a fact worth reporting
            local party, got = trade_evidence(u)
            if party and got then trade_report(u, party, got, true, "late read-back: the swap landed") end
        end
        local t = st.trade_apply
        if not t then return end
        if t.phase == "scene_lost" then
            if f - t.scene_frame >= st.trade_limits.backstop then trade_readback(t, "scene ACK lost") end
            return
        end
        if t.phase == "readback" then
            if f - t.readback_since >= st.trade_limits.backstop then
                return trade_unresolved(t, "no conclusive read-back (" .. t.readback_why .. ")")
            end
            return trade_readback(t, t.readback_why)
        end
        if t.phase ~= "wait" or not eligible() or in_battle() then return end
        local party = party_read()
        if not party then return end
        local clear = overworld_ok()
        if not clear and f - t.since < st.trade_limits.field_wait then return end
        -- re-locate by key: the slot index is a snapshot from mon_chosen (protocol §6.2 item 2)
        local slot, _, _, why = session.identity:find_party_slot(t.old_key, party)
        if not slot then
            return trade_report(t, party, nil, false, "the offered mon is " .. (why or "not in the party"))
        end
        t.slot = slot
        if clear then return post_stage(t) end
        post_fallback(t, "the field never cleared")                -- the old client's :2250 rule
    end
    drv.after_receive = trade_tick
    C.apply_trade = function(cmd)
        -- the disabled-foundation guard (PLAN §10): no native part (vanilla FRLG, RR clean) means no
        -- trade path -- nothing written, no reply (the old client's no-patch abort, :2233-2242)
        if not (native and native.transfer) then
            log("apply_trade refused: no trade path on this cartridge (nothing written) " .. tostring(cmd.old_key))
            return true
        end
        if st.trade_apply then
            log("apply_trade ignored: a trade is already in flight " .. tostring(cmd.old_key))
            return true
        end
        local hex = cmd.blob_hex
        if type(hex) ~= "string" or #hex ~= 2 * R.PARTY_MON_SIZE or hex:find("[^%x]")
           or type(cmd.old_key) ~= "string" or cmd.old_key == "" then
            log("apply_trade: bad blob_hex or old_key, skipped")      -- the old client's :983
            return true
        end
        st.trade_apply = { token = cmd.token or "", slot = cmd.slot, old_key = cmd.old_key,
                           blob_hex = hex, partner_key = partner_key_of(hex), phase = "wait",
                           since = io.framecount() }
        log("apply_trade received for " .. cmd.old_key .. ": queued for the native trade")
        return true
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
    -- (lua/memory_gba.lua M.playSE) as a GATED write, writes:arm("sound", allow, {player, track})
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
        local h = io.rom_read(hdr - 0x08000000, 12)
        local count, priority = h[1], h[3]
        local cmd_ptr = h[9] + h[10] * 256 + h[11] * 65536 + h[12] * 16777216
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
        if native and native.play_sound and native:play_sound(id) then return end
        local plan, args = m4a_plan(id)
        if not plan then return sound_refused(args) end
        local ok, awhy = armed_write("sound", plan, args)
        if not ok then sound_refused(tostring(awhy)) end
    end
    drv.pre_pump = function()
        if not (native and native.service) then return end
        native:service()
        -- the trade's first actual post is the posting job's OWN dispatch receipt (native.lua sets
        -- `posted` when it publishes that job's opcode). Never infer it from sink bytes: a
        -- completion callback (the rival swap's refresh_enemy) or a panel/NPC callback can write
        -- through the same sink in this very call while our job is refused at its guard.
        local t = st.trade_apply
        if t and t.posts then
            for _, handle in ipairs(t.posts) do
                if handle.posted == true then t.posted = true break end
            end
        end
    end

    local Id = core.Identity.new({ key = key })
    local Q = core.Deferred.new({ exec = exec, memorial_box = memorial_box })
    session = core.Session.new({ net = p.net, json = json, hud = hud, log = sink, tag = TAG,
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
