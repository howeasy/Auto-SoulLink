-- lua/gen4/client.lua -- the Gen 4 (HGSS / hg-engine) driver over the shared core (G3 card, steps 0-3).
--
-- Client.new(p) admits the cartridge (lua/gen4/entry.lua admit_routed: hash first, never a
-- fallback), builds the game driver (lua/core/session.lua's seam) and returns the core Session
-- over it, or nil + reason. No BizHawk global is named here: every byte arrives through p.io.
--
--   p.root, p.json, p.net, p.hud, p.log, p.player      the usual client shell inputs
--   p.rom_hash, p.header_code                          admission (Entry.admit_routed)
--   p.io = { read_u8/16/32(addr[, domain]), read_range(addr, n[, domain]) -> 1-based array,
--            write_u8/16/32(addr, value), framecount(), register(name), on_bus_exec(fn, addr, name,
--            domain), unregister(handle) }
--   p.packs / p.title_profile                          optional (tests): decoded pack / title object
--   p.d7        test override of the pack's profile.battle.d7 (the pack wins when it has the block):
--               { seam = { cmd, overlay_id, addr+pin_hex (HG: pinned) | table (hge: read the ROM
--                 dispatch table sPlayerBattleCommands entry `cmd`) },
--                 ctx_cmd_off, bs_party_off, party_hp_off, repl_flag_off }
--   p.area_of(map_id, location) -> area_id, loc_name   optional (step 6): area ids come from data
--   p.has_pokeballs() -> bool                          optional (the bag read is a pack gap)
--
-- Frame order (lua/core/session.lua frame_end, lua/nds/phase_signals.lua):
--   emu.frameadvance (the D7 hook fires inside it)
--   pre_pump: lease cleanup -> signals:poll() -> snapshot -> reducer (poll_events) -> effect window
--   net.pump -> signals:drain() (-> on_signal) -> frame_hooks -> ... -> flush_battle_writes (last)
-- Everything that READS game state for the reducer lives in pre_pump and ONLY there (a read in a
-- frame hook is one frame late and loses first-entry coverage).
--
-- D7, the in-battle faint (step 2). The write must happen INSIDE the bus-exec callback at the
-- battle command seam, but the core only offers frame granularity: battle_write(entry, slot, mon,
-- ending) is called from the frame's last act. So battle_write ARMS the seam hook on demand and
-- returns "hold"; the callback does the write. The armed hook is held by a BOOLEAN LEASE:
--   * every battle_write call for the entry sets lease.renewed = true (flush is the frame's last act);
--   * pre_pump clears it as its FIRST act (it runs before the flush, session.lua :409 < :472), so
--     it is true across exactly the one frameadvance after a renewal, under ANY emu.framecount
--     convention (no frame arithmetic anywhere);
--   * the arm persists while it is renewed every frame, and ONE unrenewed frame disarms it. If the
--     core skipped battle_write (writes paused, party unreadable, key not in the party, entry
--     retired) the hook is still armed through the next frameadvance, and only the callback check
--     `lease.renewed` stops it (pre_pump's disarm comes one frame later);
--   * the callback consumes the lease (lease.fired): a second fire in the same frameadvance writes
--     nothing;
--   * the phase declares NO `active` predicate, otherwise signals:poll() would re-arm it forever;
--   * single shot: every fire returns an event, and the drain removes the one-shot hook; the
--     NEXT battle_write call for THAT ENTRY reports "done" for a landed write (the completion
--     latch is keyed by the entry table, so a later command for the same mon never inherits it).
-- The callback also validates the overlay (binding:context), r0 == battle system, r1 == ctx,
-- ctx.command == the seam's command, and the key pin (battler key + party slot + both copies). The
-- chain (fs/sub/man/bs/ctx) comes from the previous pre_pump snapshot and is NOT walked again in
-- the callback; only the volatile parts are re-read there (command, battle type, the battler's
-- identity / slot / HP, the battle party record).
-- The write is the S2 seam (cmd 11 UFCE entry on HG, cmd 9 on hge) + the FAINTED bit, which is the
-- PHYSICAL-PASS scenario seam_ufce_bit (docs/gen4/research/battle_faint_seam.md :249, :295, :299):
-- only S2 together with the bit makes the game run its normal faint.
-- Missed seam on the ending frame: battle_write(..., true) returns nil, so the core defers the
-- faint to the checkpoint queue (step 4's overworld faint executor), with a logged reason (D12).
--
-- Step 3: after a write the game must show its OWN effect within EFFECT_WINDOW (900) frames: the
-- replacement flag (u32[ctx + repl_flag_off + 4*b] & 1, 2+ party mons) or the LOSE result byte
-- (one-mon party). Later is a different, unrelated event and does not satisfy it.
--
-- Idle (checkpoint_ok, the deferred-write gate and the reducer's `idle`): lua/gen4/safety.lua's
-- checkpoint, polled ONCE per frame in pre_pump and cached for the frame (it is stateful). Its
-- anchor is the engine's own gate FieldSystem_IsPlayerMovementAllowed (src/field_system.c:199-201):
-- !isPaused && unk6C (runningFieldMap, fs+0x6C) && !TaskIsRunning (taskman, fs+0x10 == NULL), plus
-- fs->unk0->unk0 != NULL (the field app) AND fs->unk0->unk4 == NULL (no launched app), save driver
-- idle and no encounter. (There is no OverlayManager.parent at the pinned tree.) encounter_active
-- here = "the battle chain is up"; the encounter task's copy-back is the taskman clause.
-- `pc_active` for the reducer = another app than the battle one is launched (the pack carries no
-- PC-resident predicate: an approximation, absorbed by the reducer's pc_frames window).
--
-- Step 4 (storage): the deferred executors below write box/party records at the checkpoint, see
-- the "storage" section. Step 5 (D11): a reducer slot_replace note becomes a key_change with the
-- alias and its exact message on identity.pending. Step 6: hello_fields/tick_fields, see "wire
-- shapes". Still open: the bag read (has_pokeballs) and p.area_of / p.charmap are injections.
local Client = {}

Client.PHASE = "d7"
Client.EFFECT_WINDOW = 900
Client.BOX_RETRY_FRAMES = 60
Client.MAX_CHANGES = 8          -- observed key changes waiting behind one unanswered alias
-- NDS platform facts for BizHawk's melonDS core (the NDS binding takes them as config, never defaults).
Client.PLATFORM = { bus_domain = "ARM9 System Bus", pc_register = "ARM9 r15", pc_offset = { thumb = 4, arm = 8 },
                    arg_registers = { "ARM9 r0", "ARM9 r1" } }
local TAG = "[SLink gen4]"

local function u32(v) return v & 0xFFFFFFFF end

-- the PID-stream keystream word `n` (1-based) of a party tail (pk4.lua lcg_xor: seed = PID)
local function stream(pid, n)
    local seed, w = pid, 0
    for _ = 1, n do
        seed = (seed * 0x41C64E6D + 0x6073) & 0xFFFFFFFF
        w = seed >> 16
    end
    return w
end

local function chain_of(fp)
    local t = {}
    for h in fp:gmatch("%x+") do t[#t + 1] = tonumber(h, 16) end
    return { fs = t[1], sub = t[2], man = t[3], bs = t[4], ctx = t[5] }
end

function Client.new(p)
    local root, json, io_ = assert(p.root, "root"), assert(p.json, "json"), assert(p.io, "io")
    local plat = p.platform or Client.PLATFORM
    local sink = p.log or function() end
    local function log(msg) sink(TAG .. " " .. msg) end
    local function L(rel) return dofile(root .. "/" .. rel) end
    local arr = json.array or function(t) return t end

    -- ── step 0: admission (hash-first; the Entry owns the rule) ─────────────────────
    local Entry = p.entry or L("lua/gen4/entry.lua")
    local admitted, why = Entry.admit_routed({
        root = root, json = json, packs = p.packs, rom_hash = p.rom_hash, header_code = p.header_code,
        read_ram = function(addr, n) return io_.read_range(addr, n, plat.bus_domain) end })
    if not admitted then return nil, why end

    local mem = { u8 = io_.read_u8, u16 = io_.read_u16, u32 = io_.read_u32 }
    local st = {
        attempted = 0,            -- write attempts (every byte this client moves counts here)
        party = nil, party_why = nil, party_frame = -1,
        battle = nil, battle_why = nil, app_active = false,
        ck = false, ck_why = "no frame yet", idle = false,
        boxes = { gen = 0, mons = {}, ok = false, sig = nil, dirty = true, next_try = 0 },
        d7 = nil,                 -- the armed lease { key, slot, entry, renewed, fired }
        d7_done = setmetatable({}, { __mode = "k" }),   -- ENTRY table -> landed write (consumed once by its battle_write)
        party_sig = nil,          -- the party signature the cached decode belongs to
        revoked = nil,            -- reason: a partial D7 write revokes every further D7 write
        watch = nil,              -- step 3: the effect window of the last landed write
        last_notes = "",
        changes = {},             -- D11: observed NPC-trade key changes waiting for a free alias slot
        fatal = nil,              -- a storage write that failed its readback: no further checkpoint writes
    }
    local session, pe, signals
    local parts = Entry.build({
        root = root, pack = admitted.pack, title = admitted.title, mem = mem, title_profile = p.title_profile,
        encounter_active = function() return st.battle ~= nil end })
    local R, pk4, safety, profile = parts.reads, parts.pk4, parts.safety, parts.profile
    local prof = profile.profile
    local PE = L("lua/gen4/poll_events.lua")
    local Registry = L("lua/hook_registry.lua")
    local binding = parts.nds.new(io_, { bus_domain = plat.bus_domain, pc_register = plat.pc_register,
        pc_offset = plat.pc_offset, overlay_table = profile.overlay_table, overlays = profile.overlays })

    local function now() return io_.framecount() end
    local function wr(width, addr, value)
        st.attempted = st.attempted + 1
        io_["write_u" .. (8 * width)](addr, value)
    end

    -- ── reads for the shapes below ─────────────────────────────────────────────────
    local pkp = { exp_bits = prof.pkm.exp_bits, ability_msb = type(prof.pkm.ability_msb) == "table",
                  hidden_ability = type(prof.pkm.hidden_ability) == "table" }

    local po = prof.party_off
    local psize = prof.pkm.party_size
    -- F6 (1x rule): the party is decoded only when it CHANGED. The signature is the ciphertext words
    -- that move whenever the record does: pid, flags + box checksum (every block), and the tail's
    -- status / level / HP / maxHP / stats (the tail is outside the checksum, and the reducer reads party
    -- HP). Torn or unreadable words only cost a full decode (R.party double-reads); a change inside a
    -- block that keeps the checksum word identical is the (2^-16) limit, as for the box signature.
    local SIG_OFFS = { 0, 4, 0x88, 0x8C, 0x90, 0x94, 0x98 }
    local function party_sig(sd)
        local base = R.array(mem, prof, sd, po.array_id)
        if not base then return nil end
        local mx, cnt = R.read(mem, base + po.max_off, 4), R.read(mem, base + po.count_off, 4)
        if not mx or not cnt or cnt > R.PARTY_CAPACITY then return nil end
        local t = { mx, cnt }
        for i = 0, cnt - 1 do
            local rec = base + po.mons_off + i * psize
            for _, off in ipairs(SIG_OFFS) do
                local v = R.read(mem, rec + off, 4)
                if not v then return nil end
                t[#t + 1] = v
            end
        end
        return table.concat(t, ",")
    end
    local function invalidate_party() st.party_frame, st.party_sig = -1, nil end
    local function party_read()
        local frame = now()
        if st.party_frame == frame then return st.party, st.party_why end
        local sd, why = R.save_data(mem, prof)
        local party
        if sd then
            local sig = party_sig(sd)
            if sig and sig == st.party_sig and st.party then
                party = st.party
            else
                party, why = R.party(mem, prof, sd)
                st.party_sig = party and sig or nil
            end
        else
            st.party_sig = nil
        end
        st.party, st.party_why, st.party_frame = party, why, frame
        st.sd = sd
        return party, why
    end
    local function player_otid()
        local sd, t = st.sd, prof.trainer
        local a = sd and R.array(mem, prof, sd, t.array_id)
        return a and R.read(mem, a + t.profile_off_in_array + t.id_off, 4)
    end

    -- ── boxes: complete scans only bump the generation ─────────────────────────────
    -- A cheap signature (pid + checksum word of every slot) decides whether the heavy decode is
    -- needed at all, so an idle edge with nothing moved costs ~1100 reads and changes nothing.
    local function scan_boxes(force)
        local B, pc = st.boxes, prof.pc
        local sd = st.sd or R.save_data(mem, prof)
        if not sd then B.ok = false; return false, "save data unreadable" end
        local base, size = R.array(mem, prof, sd, pc.array_id)
        if not base then B.ok = false; return false, tostring(size) end
        local per, sigt = prof.mons_per_box, {}
        local function slot_addr(box, slot) return base + pc.box_base + box * pc.box_stride + slot * pc.mon_stride end
        for box = 0, prof.boxes - 1 do
            for slot = 0, per - 1 do
                local a = slot_addr(box, slot)
                local pid, flags_csum = R.read(mem, a, 4), R.read(mem, a + 4, 4)   -- pid + flags + checksum
                if not pid or not flags_csum then B.ok = false; return false, "box slot unreadable" end
                sigt[#sigt + 1] = (pid | (flags_csum << 32))
            end
        end
        local sig = table.concat(sigt, ",")
        if B.ok and not force and sig == B.sig then B.dirty = false; return true, "unchanged" end
        local mons, dup, complete = {}, {}, true
        for box = 0, prof.boxes - 1 do
            for slot = 0, per - 1 do
                local a = slot_addr(box, slot)
                if R.read(mem, a, 4) ~= 0 or R.read(mem, a + 6, 2) ~= 0 then
                    local raw = R.record(mem, a, pk4.BOX_MON_SIZE)
                    if not raw then complete = false
                    elseif not pk4.is_empty_slot(raw) then
                        local m = R.box_mon(mem, prof, a)
                        if not m then complete = false
                        else
                            if mons[m.key] then dup[m.key] = true end
                            mons[m.key] = { species_id = m.species, held_item_id = m.held_item, is_egg = m.is_egg,
                                            moves = m.moves, box = box, slot = slot }
                        end
                    end
                end
            end
        end
        B.ok = complete
        if not complete then return false, "incomplete box scan" end
        B.gen, B.mons, B.dup, B.sig, B.dirty = B.gen + 1, mons, dup, sig, false
        return true
    end
    -- the ONE box-generation accessor: (generation, whether the last scan was complete) -- TWO values
    local function box_generation() return st.boxes.gen, st.boxes.ok end
    local function rescan_boxes() st.boxes.dirty = true; return scan_boxes(true) end
    local function pc_boxes_wire()
        local B = st.boxes
        if not B.ok then return nil end
        local out = {}
        for k, e in pairs(B.mons) do
            out[#out + 1] = { box = e.box, slot = e.slot, key = k, species_id = e.species_id,
                              held_item_id = e.held_item_id, moves = arr(e.moves) }
        end
        table.sort(out, function(a, b) if a.box ~= b.box then return a.box < b.box end return a.slot < b.slot end)
        return arr(out)
    end

    -- ── wire shapes (step 6) ─────────────────────────────────────────────────────────
    -- What Gen 3 sends that Gen 4 can supply from the pack and the save: party entries (key, slot,
    -- species, level, hp, maxHP, status_cond, moves, pp, held_item_id, active), enemy_party,
    -- trainer/doubles flags, ot_id, trainer_name (needs p.charmap), player_gender, badges (Johto
    -- bitmask) + kanto_badges, rom_sha1 (the pinned sha1 of the ADMITTED title), area (p.area_of),
    -- the census. Not supplied (no Gen 4 source yet): ball_count and the bag read (pack gap),
    -- trainer_id / opponent_*, stat_stages, blob_hex, pp_bonuses (an int on the wire; Gen 4 holds 4
    -- bytes), rom_content, battle_identity, trade fields; foundation/artifact_kind are not declared
    -- (the server derives the foundation from rom_type; hge is not routed there yet).
    local be = prof.battle_enums
    local doubles_bit = be.type_bits.BATTLE_TYPE_DOUBLES or be.type_bits.BATTLE_TYPE_DOUBLE
    local function party_wire(party)
        local active = {}
        for _, m in ipairs(st.battle and st.battle.mons or {}) do
            if m.b % 2 == 0 and m.slot then active[m.slot] = true end
        end
        local out = {}
        for i, m in ipairs(party) do
            local d = m.decoded
            out[i] = { key = m.key, slot = m.slot, species_id = m.species, level = m.level, hp = m.hp,
                       maxHP = m.max_hp, status_cond = d and d.status, moves = arr(m.moves),
                       pp = d and arr(d.pp), held_item_id = d and d.held_item, active = active[m.slot] == true }
        end
        return arr(out)
    end
    local function enemy_wire()
        local out = {}
        for _, m in ipairs(st.battle and st.battle.mons or {}) do
            if m.b % 2 == 1 then
                out[#out + 1] = { species_id = m.species, level = m.level, hp = m.hp, maxHP = m.max_hp, active = true }
            end
        end
        return arr(out)
    end
    local function area_now()
        if not p.area_of then return nil, nil end
        local sd = st.sd
        local loc = sd and R.location(mem, prof, sd)
        if not loc then return nil, nil end
        return p.area_of(loc.map_id, loc)
    end
    local function trainer_fields(f, hello)
        local t = R.trainer(mem, prof, st.sd)
        if t then
            f.player_gender = t.gender
            if hello then f.ot_id = t.otid end
            if p.charmap then
                local raw = table.concat(t.name_raw, ",")           -- decoded only when the name changed
                if st.name_raw ~= raw then st.name_raw, st.name = raw, R.decode_name(t.name_raw, p.charmap) end
                f.trainer_name = st.name
            end
        end
        local b = R.badges(mem, prof, st.sd)
        -- protocol_schema's hello has no kanto_badges (docs/protocol.md says Gen 2's hello sends it): tick only
        if b then f.badges = b.johto; if not hello then f.kanto_badges = b.kanto end end
    end

    -- ── D7: the seam site, resolved lazily from profile.battle.d7 ───────────────────
    local d7cfg = (prof.battle and prof.battle.d7) or p.d7
    local d7_phase = { sites = {} }          -- filled by resolve_seam; NO `active` predicate (see header)
    local function d7_need(...)
        local v = d7cfg
        for _, k in ipairs({ ... }) do
            if type(v) ~= "table" or v[k] == nil then return nil, "pack_gap:battle.d7." .. table.concat({ ... }, ".") end
            v = v[k]
        end
        return v
    end
    -- the ONE source of the party-tail HP offset (the in-battle write and the overworld faint both use it)
    local PARTY_HP_OFF = pk4.BOX_MON_SIZE + 6          -- PartyPokemon tail: status u32, level, capsule, hp u16
    local function hp_off()
        local off = (d7cfg and d7cfg.party_hp_off) or PARTY_HP_OFF
        if math.type(off) ~= "integer" or off < pk4.BOX_MON_SIZE or off % 2 ~= 0 or off + 2 > psize then
            return nil, "bad battle.d7.party_hp_off"
        end
        return off
    end
    local function resolve_seam()
        if st.seam then return st.seam end
        local s, gap = d7_need("seam")
        if not s then return nil, gap end
        for _, k in ipairs({ "ctx_cmd_off", "bs_party_off", "party_hp_off", "repl_flag_off" }) do
            local v, vgap = d7_need(k)
            if not v then return nil, vgap end
        end
        local _, hwhy = hp_off()
        if hwhy then return nil, hwhy end
        local addr, pin, mode = s.addr, s.pin_hex, s.mode or "thumb"
        if not binding:resident(s.overlay_id) then return nil, "seam overlay not resident" end
        if not addr then                      -- hge: the ROM's own dispatch table names the entry
            local entry = R.read(mem, s.table + 4 * s.cmd, 4)
            if not entry then return nil, "dispatch table unreadable" end
            mode, addr = (entry & 1) == 1 and "thumb" or "arm", entry & ~1
        end
        if not pin then
            local b = R.bytes(mem, addr, 4)
            if not b then return nil, "seam bytes unreadable" end
            pin = string.format("%02x%02x%02x%02x", b[1], b[2], b[3], b[4])
        end
        local fire = pin:sub(7, 8) .. pin:sub(5, 6) .. pin:sub(3, 4) .. pin:sub(1, 2)
        st.seam = { id = "d7_seam", phase = Client.PHASE, image = "ov" .. s.overlay_id, overlay_id = s.overlay_id,
                    address = addr, mode = mode, extent = 4, register_hex = pin, fire_hex = fire, cmd = s.cmd }
        d7_phase.sites[1] = st.seam
        return st.seam
    end

    -- Everything the callback needs. The chain comes from the previous pre_pump snapshot (st.battle) and
    -- is not walked again; only the volatile parts are read here. Returns plan | nil, reason. Both spans
    -- are prevalidated here; nothing is written.
    local function s32(v) return v >= 0x80000000 and v - 0x100000000 or v end
    local function d7_plan(lease, r0, r1)
        local b = st.battle
        if not b then return nil, "chain: no battle snapshot" end
        local c = chain_of(b.fingerprint)
        if r0 ~= c.bs then return nil, "r0 is not the battle system" end
        if r1 ~= c.ctx then return nil, "r1 is not the battle context" end
        local cmd = R.read(mem, c.ctx + d7cfg.ctx_cmd_off, 4)
        if cmd ~= st.seam.cmd then return nil, "command " .. tostring(cmd) .. " is not the seam command" end
        local bt, be = prof.battle, prof.battle_enums
        local btype = R.read(mem, c.bs + bt.type_off, 4)
        if not btype then return nil, "battle type unreadable" end
        if be.exempt_mask and (btype & be.exempt_mask) ~= 0 then return nil, "battle type is exempt" end
        local pick
        for _, m in ipairs(b.mons) do
            if m.b % 2 == 0 and m.key == lease.key then
                if pick then return nil, "ambiguous: two local battlers carry the key" end
                pick = m
            end
        end
        if not pick then return nil, "key is not a local battler" end
        -- the battler is re-read live: identity, selected slot, both HP words
        local base = c.ctx + bt.mons_off + bt.mon_size * pick.b
        local pid, otid = R.read(mem, base + bt.personality_off, 4), R.read(mem, base + bt.otid_off, 4)
        if not pid or not otid or pk4.mon_key(pid, otid) ~= lease.key then return nil, "key is not a local battler" end
        local sel = R.read(mem, c.ctx + bt.selected_off + pick.b, 1)
        if sel ~= lease.slot or pick.slot ~= lease.slot then return nil, "party slot pin differs" end
        local rawhp, bmax = R.read(mem, base + bt.hp_off, 4), R.read(mem, base + bt.max_hp_off, 2)
        if not rawhp or not bmax then return nil, "battler hp unreadable" end
        local bhp = s32(rawhp)
        local off, owhy = hp_off()
        if not off then return nil, owhy end
        local po = prof.party_off
        local party = R.read(mem, c.bs + d7cfg.bs_party_off, 4)         -- owner 0: every local battler
        local count = party and R.read(mem, party + po.count_off, 4)
        if not count or count < 1 or count > R.PARTY_CAPACITY or lease.slot >= count then return nil, "party range" end
        local rec = party + po.mons_off + psize * lease.slot
        local raw, rwhy = R.record(mem, rec, psize)
        if not raw then return nil, "record: " .. tostring(rwhy) end
        local mon, dwhy = pk4.decode_party_mon(raw, pkp)
        if not mon then return nil, "record: " .. tostring(dwhy) end      -- includes "locked": never XOR plaintext
        if mon.key ~= lease.key then return nil, "record identity differs" end
        if bmax < 1 or bmax > 999 or mon.max_hp < 1 or mon.max_hp > 999 or mon.hp > mon.max_hp
           or bhp < 0 or bhp > bmax then
            return nil, "hp range"
        end
        if (bhp == 0) ~= (mon.hp == 0) then return nil, "hp copies incoherent" end
        local bit = ((1 << pick.b) << bt.fainted_flag_shift)
        if bit & bt.fainted_flag_mask == 0 then return nil, "faint bit outside the mask" end
        local ks = stream(mon.pid, (off - pk4.BOX_MON_SIZE) // 2 + 1)
        return { b = pick.b, slot = lease.slot, key = lease.key, noop = bhp == 0, rec = rec, pid = mon.pid, ks = ks,
                 bhp = base + bt.hp_off, php = rec + off,
                 status = c.ctx + bt.fainted_flag_off, bit = bit, ctx = c.ctx, bs = c.bs, fp = b.fingerprint }
    end

    local function d7_verify(pl)
        local hp = R.bytes(mem, pl.bhp, 4)
        local raw = R.read(mem, pl.php, 2)
        local status = R.read(mem, pl.status, 4)
        if not hp or not raw or not status then return false, "readback unreadable" end
        if hp[1] ~= 0 or hp[2] ~= 0 then return false, "battle hp nonzero" end
        if hp[3] ~= 0 or hp[4] ~= 0 then return false, "battle hp high half stale" end
        if (raw ~ pl.ks) ~= 0 then return false, "party hp nonzero" end
        if status & pl.bit == 0 then return false, "faint bit not set" end
        if R.read(mem, pl.rec, 4) ~= pl.pid or ((R.read(mem, pl.rec + 4, 2) or 3) & 3) ~= 0 then
            return false, "record disturbed"
        end
        return true
    end

    -- THE CALLBACK (inside the bus-exec hook; no request/arm/disarm in here, no session.frame).
    local function d7_fire()
        local frame = now()
        local lease = st.d7
        local function ev(result, why, extra)
            local e = { kind = "d7", result = result, why = why, key = lease and lease.key, frame = frame }
            for k, v in pairs(extra or {}) do e[k] = v end
            return e
        end
        if not lease then return ev("refused", "no lease") end
        if lease.fired then return ev("refused", "lease already used by an earlier fire") end
        if not lease.renewed then return ev("refused", "lease not renewed by the previous frame") end
        lease.fired = true                                    -- single shot, even inside one frameadvance
        if st.revoked then return ev("refused", "revoked: " .. st.revoked) end
        local before = st.attempted
        local ok, res, rwhy = pcall(function()
            local r0, r1 = u32(io_.register(plat.arg_registers[1])), u32(io_.register(plat.arg_registers[2]))
            local pl, why2 = d7_plan(lease, r0, r1)
            if not pl then return "refused", why2 end
            if pl.noop then return "noop", "target already at zero (the game's own faint)" end
            local bt = prof.battle
            wr(4, pl.bhp, 0)
            wr(2, pl.php, 0 ~ pl.ks)
            wr(4, pl.status, (R.read(mem, pl.status, 4) | pl.bit))
            local vok, vwhy = d7_verify(pl)
            if not vok then return "fatal", vwhy end
            pe:commanded(pl.key)                  -- our zero is not a faint (the reducer must never echo it)
            -- frame is stamped by the next pre_pump (watch_step), so no framecount convention matters
            st.watch = { key = pl.key, b = pl.b, fp = pl.fp, ctx = pl.ctx, bs = pl.bs, bt = bt }
            return "written"
        end)
        if not ok then
            if st.attempted ~= before then return ev("fatal", "error after a write: " .. tostring(res)) end
            return ev("refused", "error: " .. tostring(res))
        end
        return ev(res, rwhy)
    end

    local function capture(site)
        if site.phase ~= Client.PHASE then return nil end
        if binding:context(site) == nil then return nil end          -- wrong overlay resident: zero writes
        return d7_fire()
    end

    -- ── the driver ─────────────────────────────────────────────────────────────────
    local drv = { commands = {} }
    drv.frame = now
    drv.read_party = party_read
    function drv.in_battle() return st.battle ~= nil end
    -- The deferred-write gate is the safety checkpoint, which reads the SAVE DRIVER state byte
    -- (save_busy). It deliberately does not look at the PC modified word: the battery keeps it at 1
    -- permanently (f426a76b), so "modified" never means "a save is in flight".
    function drv.checkpoint_ok()
        if st.fatal then return false, "write fault: " .. st.fatal end
        if st.ck_frame ~= now() then return false, "checkpoint stale (not polled this frame)" end
        return st.ck, st.ck_why
    end
    drv.box_generation = box_generation
    drv.rescan_boxes = rescan_boxes

    function drv.game_is_live()
        local party, pwhy = party_read()
        if not party then return false, pwhy or "party unreadable" end
        local t = R.trainer(mem, prof, st.sd)
        if t and t.otid == 0 and #party == 0 then return false, "pre-game (title/new game)" end
        return true
    end
    function drv.save_cleared()
        if not R.save_data(mem, prof) then return true end
        local t = R.trainer(mem, prof)
        return t ~= nil and t.otid == 0
    end
    function drv.hello_ready()
        local live, lwhy = drv.game_is_live()
        if not live then return false, lwhy end
        if drv.in_battle() then return true end
        return st.ck, st.ck_why
    end
    function drv.hello_fields()
        local party = party_read() or {}
        if not st.boxes.ok then scan_boxes(true) end
        local f = { rom_type = admitted.rom_type, party = party_wire(party),
                    has_pokeballs = p.has_pokeballs and p.has_pokeballs() or false, rom_sha1 = profile.rom.sha1 }
        trainer_fields(f, true)
        f.area_id, f.loc_name = area_now()
        local gen, ok = box_generation()
        if ok then f.pc_boxes, f.pc_boxes_generation = pc_boxes_wire(), gen end
        return f
    end
    function drv.tick_fields()
        local party = party_read()
        if not party then return nil end
        local b = st.battle
        local f = { party = party_wire(party), in_battle = b ~= nil, enemy_party = enemy_wire(),
                    has_pokeballs = p.has_pokeballs and p.has_pokeballs() or false,
                    is_trainer_battle = b ~= nil and (b.btype & be.trainer_mask) ~= 0,
                    is_doubles = b ~= nil and doubles_bit ~= nil and (b.btype & doubles_bit) ~= 0 }
        trainer_fields(f)
        f.area_id, f.loc_name = area_now()
        local gen, ok = box_generation()
        if ok then f.pc_boxes, f.pc_boxes_generation = pc_boxes_wire(), gen end
        return f
    end
    function drv.on_reset()
        pe:reset()
        st.d7, st.d7_done, st.watch, st.changes, st.fatal = nil, setmetatable({}, { __mode = "k" }), nil, {}, nil
        st.party_sig = nil
        st.boxes = { gen = st.boxes.gen, mons = {}, ok = false, sig = nil, dirty = true, next_try = 0 }
    end

    function drv.start()
        signals = parts.phase_signals.new({
            Registry = Registry, binding = binding, owner = "slink.gen4", max_pending = 8, capture = capture,
            phases = { [Client.PHASE] = d7_phase } })
        st.signals = signals
        return signals
    end
    function drv.on_signal(sig)
        if sig.kind ~= "d7" then return end
        local lease = st.d7
        st.d7 = nil                          -- the one-shot hook is gone (the drain removed it)
        if sig.result == "written" then
            if lease then st.d7_done[lease.entry] = { frame = sig.frame } end
            log("D7 faint written " .. tostring(sig.key) .. " at frame " .. sig.frame)
        elseif sig.result == "noop" then
            if lease then st.d7_done[lease.entry] = { frame = sig.frame, noop = true } end
            log("D7 faint: " .. tostring(sig.why) .. " " .. tostring(sig.key))
        elseif sig.result == "fatal" then
            st.revoked = tostring(sig.why)
            st.watch = nil
            log("D7 FATAL (partial write, further D7 writes revoked): " .. tostring(sig.why) .. " " .. tostring(sig.key))
        else
            log("D7 write refused (re-armed while the entry is held): " .. tostring(sig.why)
                .. (lease and "" or " [no lease]"))
        end
    end

    -- ── step 2: battle_write, the arm + completion latch ────────────────────────────
    local function battle_write(e, slot, mon, ending)
        local k = mon.key
        local landed = st.d7_done[e]
        if landed then st.d7_done[e] = nil; return "done" end
        if ending then
            st.d7_done[e] = nil
            if st.d7 then signals:disarm(Client.PHASE); st.d7 = nil end
            log("D7: no in-battle write landed before the battle ended; handed to the checkpoint queue: " .. tostring(e.key))
            return nil
        end
        if st.revoked then return nil end
        if not signals then return "hold", "engine signals not started" end
        local battler
        for _, m in ipairs(st.battle and st.battle.mons or {}) do
            if m.b % 2 == 0 and m.key == k then battler = m; break end
        end
        if not battler then return "hold", "not an active battler" end   -- the battle-end call defers it
        if st.d7 and st.d7.entry ~= e then return "hold", "D7 seam busy with another faint" end
        local seam, swhy = resolve_seam()
        if not seam then return "hold", swhy end
        local ok, rwhy = signals:request(Client.PHASE)
        if ok then
            st.d7 = { key = k, slot = slot, entry = e, renewed = true }
        elseif type(rwhy) == "string" and rwhy:find("already armed", 1, true) then
            if not st.d7 then signals:disarm(Client.PHASE); return "hold", "stale arm cleared" end
            st.d7.renewed = true                                         -- BUSY = armed = held: renew the lease
        else
            return "hold", rwhy or "seam refused"
        end
        return "hold", "D7 seam armed"
    end
    drv.battle_write = battle_write

    -- ── step 3: the effect window ───────────────────────────────────────────────────
    local function effect_seen(w)
        local o = prof.battle_enums.outcomes
        local flag = R.read(mem, w.ctx + d7cfg.repl_flag_off + 4 * w.b, 4)
        if flag and (flag & 1) ~= 0 then return "replacement" end
        local raw = R.read(mem, w.bs + w.bt.outcome_off, 1)
        if raw and (raw & w.bt.outcome_mask) == o.lose then return "lose" end
    end
    local function watch_step(frame, battle)
        local w = st.watch
        if not w then return end
        w.frame = w.frame or frame                       -- the write landed in the frameadvance before this pre_pump
        local same = battle ~= nil and battle.fingerprint == w.fp
        w.gone = same and 0 or (w.gone or 0) + 1            -- a one-frame chain refusal is not the battle's end
        local seen = same and effect_seen(w) or nil
        local elapsed = frame - w.frame
        if seen and elapsed <= Client.EFFECT_WINDOW then
            st.effect = { key = w.key, result = "satisfied", via = seen, frames = elapsed }
            st.watch = nil
        elseif elapsed > Client.EFFECT_WINDOW or w.gone >= 3 then
            st.effect = { key = w.key, result = seen and "late" or "expired", via = seen, frames = elapsed }
            st.watch = nil
            log("D7 effect " .. st.effect.result .. " for " .. tostring(w.key) .. " (" .. elapsed .. " frames after the write)")
        end
    end

    -- ── pre_pump: the ONLY place the reducer's world is read ─────────────────────────
    local function pre_pump_body()
        local frame = now()
        -- 1. the lease, FIRST (pre_pump runs before the flush): clear the renewal; a frame that was not
        -- renewed disarms (cleanup only; the callback check is the real guard). A fired lease waits for
        -- its drain, which records the landed write.
        local lease = st.d7
        if lease then
            local was = lease.renewed
            lease.renewed = false
            if not was and not lease.fired then
                if signals then signals:disarm(Client.PHASE) end
                st.d7 = nil
            end
        end
        -- 2. predicates (the D7 phase has none; poll() here and nowhere else)
        if signals then signals:poll() end
        -- 3. the world
        local party = party_read()
        local battle, bwhy = R.battle(mem, prof)
        st.battle, st.battle_why = battle, bwhy
        local app = bwhy == "not_battle"            -- another launched app: bag / party / PC / summary
        st.ck, st.ck_why = safety:checkpoint()
        st.ck_frame = frame
        local idle = st.ck == true
        if st.prev_battle and not battle then st.boxes.dirty = true end        -- a catch can land in a box
        if st.app_active and not app then st.boxes.dirty = true end            -- the PC closed
        if idle and not st.prev_idle then st.boxes.dirty = true end            -- a task (script/gift) ended
        if st.boxes.dirty and idle and not battle and frame >= st.boxes.next_try then
            local ok = scan_boxes(false)
            st.boxes.next_try = ok and 0 or frame + Client.BOX_RETRY_FRAMES
        end
        st.prev_battle, st.app_active, st.prev_idle = battle ~= nil, app, idle
        local snap = { frame = frame, party = party, battle = battle, idle = idle, pc_active = app,
                       boxes = st.boxes.ok and { gen = st.boxes.gen, mons = st.boxes.mons } or nil,
                       has_pokeballs = p.has_pokeballs and p.has_pokeballs() or false }
        snap.area, snap.loc = area_now()
        snap.player_otid = party and player_otid() or nil
        -- 4. the reducer
        local events, notes = pe:step(snap)
        for _, e in ipairs(events) do session.send(e.name, e.data) end
        local joined = table.concat(notes, ",")
        if joined ~= st.last_notes then
            st.last_notes = joined
            if joined ~= "" then log("reducer: " .. joined) end
        end
        -- 5. D11: a record replaced in place with its old one gone (NPC trade) is a key_change
        for _, n in ipairs(notes) do
            local old, new = n:match("^slot_replace:([^>]+)>(.+)$")
            if old then
                if #st.changes >= Client.MAX_CHANGES then
                    log("key_change queue full: dropped " .. old .. " > " .. new)
                else
                    st.changes[#st.changes + 1] = { old = old, new = new }
                end
            end
        end
        while #st.changes > 0 and not session.identity.pending do
            local c = table.remove(st.changes, 1)
            local mon
            for _, m in ipairs(party or {}) do if m.key == c.new then mon = m end end
            if mon then
                -- the exact message rides on the alias: the core resends it after a retryable refusal
                session.identity:begin_alias(c.old, c.new, mon, party, frame)
                session.identity.pending.msg = { old_key = c.old, new_key = c.new, reason = "npc_trade",
                                                 new_species = mon.species, new_nickname = mon.nickname }
                session.send("key_change", session.identity.pending.msg)
            else
                log("key_change " .. c.old .. " > " .. c.new .. " dropped: the new record left the party")
            end
        end
        -- 6. the effect window
        watch_step(frame, battle)
    end
    -- the core does not pcall pre_pump: a fault here must not stop the frame loop
    function drv.pre_pump()
        local ok, err = pcall(pre_pump_body)
        if ok then
            st.pre_err = nil                                  -- a recurring error logs again
        else
            -- fail CLOSED: no checkpoint (so no deferred write) and no battle snapshot from a broken frame
            st.ck, st.ck_why = false, "pre_pump fault: " .. tostring(err)
            st.ck_frame = now()
            st.battle, st.battle_why = nil, "pre_pump fault"
            if tostring(err) ~= st.pre_err then
                st.pre_err = tostring(err)
                log("pre_pump error: " .. st.pre_err)
            end
        end
    end

    -- ── step 4: the deferred executors (storage) ─────────────────────────────────────
    -- Every box/party mutation is ONE plan {{addr, bytes}, ...} (PLAN 4.3 storage): prevalidated as a
    -- whole (nothing is written unless the permit is open, every span is inside RAM and the storage
    -- has not moved since the plan was made), written, then READ BACK. A readback that differs is a
    -- visible FATAL write fault (st.fatal, a console line, and the gate closes): never rolled back,
    -- never reported as success. The PERMIT is the safety checkpoint of THIS frame (st.ck, polled in
    -- pre_pump; the deferred queue runs in the same frame_end): it includes the save driver state
    -- byte (save_busy) and never the battery modified word. Box edits keep the game's own
    -- representation: records are copied or re-encrypted through pk4 (box checksum recomputed), a
    -- party-tail-only HP edit is outside that checksum, and the PC's per-box dirty bit
    -- (pc.box_modified_flag_off, PCStorage_SetBoxModified: flag |= 1 << box) is set with the data.
    -- Not reproduced (no Gen 4 data source): RestoreBoxMonPP on a deposit and the held-mail refusal.
    local per = prof.mons_per_box
    local function layout()
        local sd, why = R.save_data(mem, prof)
        if not sd then return nil, why end
        local party, psz = R.array(mem, prof, sd, po.array_id)
        if not party then return nil, psz end
        local pc, cw = R.array(mem, prof, sd, prof.pc.array_id)
        if not pc then return nil, cw end
        return { sd = sd, party = party, party_size = psz, pc = pc }
    end
    -- PartyExtra (pokemon_types_def.h:322-326): Party = { PartyCore core; PartyExtra extra }, extra =
    -- aprijuiceModifiers[PARTY_SIZE] of PERFORMANCE_MAX bytes (5, include/constants/pokemon.h:132),
    -- right after mons[6] in the same save array. Party_RemoveMon (src/party.c:56-68) shifts mons[] AND
    -- extra[] and clears the last entry; Party_AddMon (:47-54) clears extra[curCount]. The pack carries no
    -- geometry for it (pinned for HGSS only): party_off.extra = { stride, off? } or p.party_extra; without
    -- it every write that changes the party's SHAPE refuses with a pack-gap reason instead of guessing.
    local function extra_geometry(L)
        local g = po.extra or p.party_extra
        if type(g) ~= "table" or math.type(g.stride) ~= "integer" or g.stride < 1 then
            return nil, "pack_gap:party_off.extra"
        end
        local off = g.off or (po.mons_off + R.PARTY_CAPACITY * psize)
        if off + R.PARTY_CAPACITY * g.stride > L.party_size then return nil, "party extra outside the party array" end
        return { off = off, stride = g.stride }
    end
    local function extra_addr(L, g, slot) return L.party + g.off + slot * g.stride end
    local function box_addr(L, box, slot)
        local pc = prof.pc
        return L.pc + pc.box_base + box * pc.box_stride + slot * pc.mon_stride
    end
    local function party_addr(L, slot) return L.party + po.mons_off + slot * psize end
    local function zeros(n) local t = {}; for i = 1, n do t[i] = 0 end; return t end
    local function word_bytes(v, n) local t = {}; for i = 1, n do t[i] = v & 0xFF; v = v >> 8 end; return t end
    local function slice(t, n) local o = {}; for i = 1, n do o[i] = t[i] end; return o end
    local function same(a, b)
        if not a or #a ~= #b then return false end
        for i = 1, #b do if a[i] ~= b[i] then return false end end
        return true
    end

    -- returns true | nil, why [, true when the fault is FATAL (bytes may have moved)]
    local function write_plan(L, plan)
        if st.fatal then return nil, "write fault: " .. st.fatal end
        if st.ck_frame ~= now() then return nil, "checkpoint closed: stale (not polled this frame)" end
        if not st.ck then return nil, "checkpoint closed: " .. tostring(st.ck_why) end
        for _, sp in ipairs(plan) do
            if not R.in_ram(sp[1], #sp[2]) then return nil, "span outside RAM" end
        end
        local cur = layout()
        if not (cur and cur.sd == L.sd and cur.party == L.party and cur.pc == L.pc) then
            return nil, "storage moved before the write"
        end
        local ok, err = pcall(function()
            for _, sp in ipairs(plan) do
                local a, bytes, i, n = sp[1], sp[2], 1, #sp[2]
                while i <= n do                                -- aligned u32 / u16 where the span allows, else u8
                    local at, w = a + i - 1, 1
                    if at % 4 == 0 and n - i + 1 >= 4 then w = 4 elseif at % 2 == 0 and n - i + 1 >= 2 then w = 2 end
                    local v = 0
                    for k = w, 1, -1 do v = (v << 8) | bytes[i + k - 1] end
                    wr(w, at, v)
                    i = i + w
                end
            end
        end)
        local bad = (not ok) and ("write error: " .. tostring(err)) or nil
        if ok then
            for _, sp in ipairs(plan) do
                if not same(R.bytes(mem, sp[1], #sp[2]), sp[2]) then
                    bad = string.format("readback differs at 0x%08X", sp[1])
                    break
                end
            end
        end
        invalidate_party()
        if bad then
            st.fatal = bad
            log("STORAGE FATAL (bytes may have moved; checkpoint writes revoked): " .. bad)
            return nil, "fatal: " .. bad, true
        end
        return true
    end

    local function dirty_span(L, boxes)
        local off = prof.pc.box_modified_flag_off
        if not off then return nil, "pack_gap:pc.box_modified_flag_off" end
        local cur = R.read(mem, L.pc + off, 4)
        if not cur then return nil, "dirty flag unreadable" end
        for _, b in ipairs(boxes) do cur = cur | (1 << b) end
        return { L.pc + off, word_bytes(cur, 4) }
    end

    local function party_match(key, hint)
        local party, why = party_read()
        if not party then return nil, nil, why end
        local found, hinted, dup
        for _, m in ipairs(party) do
            if m.key == key then
                if found then dup = true end
                found = m
                if m.slot == hint then hinted = m end
            end
        end
        if hinted then return party, hinted end              -- a validated locator tells shared keys apart
        if dup then return nil, nil, "ambiguous duplicate key" end
        return party, found
    end
    local function alive_elsewhere(party, slot)
        for _, m in ipairs(party) do
            if m.slot ~= slot and not (m.decoded and m.decoded.is_egg) and m.hp > 0 then return true end
        end
        return false
    end
    -- A complete census, reused for CENSUS_FRAMES while nothing marked the boxes dirty (a retrying
    -- command - "last party mon" requeues every frame - must not rescan every frame); older or dirty
    -- goes through scan_boxes' signature shortcut, which only decodes when something moved. Any write of
    -- ours drops it (commit).
    local CENSUS_FRAMES = 30
    local function census()
        local frame = now()
        if not (st.boxes.ok and not st.boxes.dirty and st.census_frame and frame - st.census_frame < CENSUS_FRAMES) then
            if not scan_boxes(false) then st.census_frame = nil; return nil, "box census unavailable" end
            st.census_frame = frame
        end
        local occ = {}
        for _, e in pairs(st.boxes.mons) do occ[e.box * per + e.slot] = true end
        return st.boxes, occ
    end
    local function free_slot(occ, lo, hi)
        for box = lo, hi do
            for slot = 0, per - 1 do
                if not occ[box * per + slot] then return box, slot end
            end
        end
    end
    local function box_record(L, e)
        local raw, why = R.record(mem, box_addr(L, e.box, e.slot), pk4.BOX_MON_SIZE)
        if not raw then return nil, "record: " .. tostring(why) end
        local _, dwhy = pk4.decrypt_box(raw)                   -- refuses locked / bad checksum
        if dwhy then return nil, "record: " .. tostring(dwhy) end
        return raw
    end
    local function commit(L, plan, boxes)
        local flag, fwhy = dirty_span(L, boxes)
        if not flag then return nil, fwhy end
        plan[#plan + 1] = flag
        st.census_frame = nil
        return write_plan(L, plan)
    end

    -- deposit (to a regular box) / memorialize (to the memorial box); the source is the party or a box
    local function move_to_box(key, hint, memorial)
        local L, why = layout()
        if not L then return nil, why end
        local party, mon, pwhy = party_match(key, hint)
        if not party then return nil, pwhy end
        local B, occ = census()
        if not B then return nil, occ end
        if B.dup[key] then return nil, "ambiguous duplicate boxed key" end
        local boxed, last = B.mons[key], prof.memorial_box
        if mon and boxed then return nil, "ambiguous key exists in both party and box" end
        if not mon and not boxed then return nil, "key not in party" end
        if boxed and (not memorial or boxed.box == last) then return true end      -- already where it belongs
        local tb, ts
        if memorial then tb, ts = free_slot(occ, last, last) else tb, ts = free_slot(occ, 0, last - 1) end
        if not tb then return nil, memorial and "memorial box full" or "current box full" end
        local plan, touched = {}, { tb }
        if mon then
            if not alive_elsewhere(party, mon.slot) then return nil, "last party mon" end
            local g, gwhy = extra_geometry(L)
            if not g then return nil, gwhy end
            local recs, extras = {}, {}
            for s = mon.slot, #party - 1 do
                local raw, rwhy = R.record(mem, party_addr(L, s), psize)
                if not raw then return nil, "record: " .. tostring(rwhy) end
                recs[s] = raw
                local x = R.bytes(mem, extra_addr(L, g, s), g.stride)
                if not x then return nil, "party extra unreadable" end
                extras[s] = x
            end
            local _, dwhy = pk4.decode_party_mon(recs[mon.slot], pkp)
            if dwhy then return nil, "record: " .. tostring(dwhy) end
            plan[1] = { box_addr(L, tb, ts), slice(recs[mon.slot], pk4.BOX_MON_SIZE) }
            for s = mon.slot, #party - 2 do plan[#plan + 1] = { party_addr(L, s), recs[s + 1] } end
            -- the vacated slot is ZeroMonData (src/pokemon.c:101-105): zeros, then box AND party encrypted
            plan[#plan + 1] = { party_addr(L, #party - 1), pk4.encrypt_party(zeros(psize)) }
            for s = mon.slot, #party - 2 do plan[#plan + 1] = { extra_addr(L, g, s), extras[s + 1] } end
            plan[#plan + 1] = { extra_addr(L, g, #party - 1), zeros(g.stride) }
            plan[#plan + 1] = { L.party + po.count_off, word_bytes(#party - 1, 4) }
        else
            local raw, rwhy = box_record(L, boxed)
            if not raw then return nil, rwhy end
            plan[1] = { box_addr(L, tb, ts), raw }
            plan[2] = { box_addr(L, boxed.box, boxed.slot), pk4.encrypt_box(zeros(pk4.BOX_MON_SIZE)) }
            touched[2] = boxed.box
        end
        local ok, cwhy = commit(L, plan, touched)
        if not ok then return nil, cwhy end
        if mon then pe:expect("party_to_box", key) end
        return true
    end

    local function valid_stat(v, hi) return math.type(v) == "integer" and v >= 1 and v <= hi end
    local function withdraw(key, stats)
        local L, why = layout()
        if not L then return nil, why end
        local party, mon, pwhy = party_match(key)
        if not party then return nil, pwhy end
        local B = census()
        if not B then return nil, "box census unavailable" end
        if B.dup[key] then return nil, "ambiguous duplicate boxed key" end
        local boxed = B.mons[key]
        if mon then
            if boxed then return nil, "ambiguous key exists in both party and box" end
            return true
        end
        if #party >= R.PARTY_CAPACITY then return nil, "party full" end
        if not boxed then return nil, "key not boxed" end
        if type(stats) ~= "table" or not valid_stat(stats.level, 100) or not valid_stat(stats.maxHP, 999)
           or not valid_stat(stats.attack, 999) or not valid_stat(stats.defense, 999)
           or not valid_stat(stats.speed, 999) or not valid_stat(stats.spAtk, 999)
           or not valid_stat(stats.spDef, 999) then
            return nil, "missing stats"
        end
        local g, gwhy = extra_geometry(L)
        if not g then return nil, gwhy end
        local raw, rwhy = box_record(L, boxed)
        if not raw then return nil, rwhy end
        -- The tail is the server's CACHED stats (stats_cache), not CalcMonLevelAndStats: HP = max, status cleared.
        local plain = pk4.decrypt_box(raw)
        local tail = zeros(psize - pk4.BOX_MON_SIZE)
        tail[5] = stats.level                                  -- BoxMonToMon: status cleared, HP = max
        for i, v in ipairs({ stats.maxHP, stats.maxHP, stats.attack, stats.defense, stats.speed, stats.spAtk,
                             stats.spDef }) do
            tail[7 + 2 * (i - 1)], tail[8 + 2 * (i - 1)] = v & 0xFF, v >> 8
        end
        for i = 1, #tail do plain[pk4.BOX_MON_SIZE + i] = tail[i] end
        local rec = pk4.encrypt_party(plain)
        local plan = { { party_addr(L, #party), rec }, { extra_addr(L, g, #party), zeros(g.stride) },
                       { L.party + po.count_off, word_bytes(#party + 1, 4) },
                       { box_addr(L, boxed.box, boxed.slot), pk4.encrypt_box(zeros(pk4.BOX_MON_SIZE)) } }
        local ok, cwhy = commit(L, plan, { boxed.box })
        if not ok then return nil, cwhy end
        pe:expect("box_to_party", key)
        return true
    end

    -- the overworld faint: party HP = 0 (u16, PID-stream encrypted; outside the box checksum)
    local function faint(slot)
        local L, why = layout()
        if not L then return nil, why end
        local party = party_read()
        if not party or math.type(slot) ~= "integer" or slot < 0 or slot >= #party then return nil, "slot out of range" end
        local rec = party_addr(L, slot)
        local raw, rwhy = R.record(mem, rec, psize)
        if not raw then return nil, "record: " .. tostring(rwhy) end
        local mon, dwhy = pk4.decode_party_mon(raw, pkp)       -- "locked" is refused, never XORed as plaintext
        if not mon then return nil, "record: " .. tostring(dwhy) end
        if mon.hp == 0 then return true end
        local off, owhy = hp_off()
        if not off then return nil, owhy end
        local ks = stream(mon.pid, (off - pk4.BOX_MON_SIZE) // 2 + 1)
        local ok, wwhy = write_plan(L, { { rec + off, { ks & 0xFF, ks >> 8 } } })
        if not ok then return nil, wwhy end
        pe:commanded(mon.key)                                  -- our zero is not a faint
        return true
    end

    local function stats_of(m)
        local s, d = { level = m.level, maxHP = m.max_hp }, m.decoded
        if d and d.stats then
            s.attack, s.defense, s.speed, s.spAtk, s.spDef = d.stats[1], d.stats[2], d.stats[3], d.stats[4], d.stats[5]
            for i = 1, 4 do s["pp" .. i] = d.pp and d.pp[i] or 0 end
        end
        return s
    end
    local exec = {
        arm = function() end, disarm = function() end,             -- each plan is its own permit window
        faint_slot = function(slot)
            local ok, why = faint(slot)
            if not ok then error("overworld faint refused: " .. tostring(why), 0) end
        end,
        deposit = function(key, hint) return move_to_box(key, hint, false) end,
        withdraw = withdraw,
        memorialize = function(key, hint) return move_to_box(key, hint, true) end,
        stats_of = stats_of,
        write_count = function() return st.attempted end,
        rescan = function() rescan_boxes(); invalidate_party() end,
    }
    local core = { Session = L("lua/core/session.lua"), Identity = L("lua/core/identity.lua"),
                   Deferred = L("lua/core/deferred.lua") }
    local identity = core.Identity.new({ key = function(m) return m.key end })
    local queue = core.Deferred.new({ exec = exec, memorial_box = prof.memorial_box })
    session = core.Session.new({ net = p.net, json = json, hud = p.hud, log = sink, tag = TAG, player = p.player,
                                 game = drv, identity = identity, deferred = queue })
    -- the reducer shares the session's resolved_areas (the core REPLACES that table on a command)
    local resolved = setmetatable({}, { __index = function(_, k) return session.resolved_areas[k] end,
                                        __newindex = function(_, k, v) session.resolved_areas[k] = v end })
    pe = PE.new({ battle_enums = prof.battle_enums, resolved = resolved })
    session.driver, session.state, session.parts, session.admitted = drv, st, parts, admitted
    return session
end

return Client
