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
--   p.d7        PACK GAP block, used only when profile.battle.d7 is absent (the pack carries none of
--               it yet; the values are the live-proven ones, docs/gen4/research/battle_faint_seam.md):
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
-- returns "hold"; the callback does the write. The armed hook is a ONE-FRAME LEASE:
--   * every battle_write call for the entry renews it (lease.renewed_frame = this frame);
--   * the callback writes ONLY IF lease.renewed_frame == framecount - 1, i.e. the immediately
--     preceding frame_end's flush renewed it. If the core skipped battle_write (writes paused,
--     party unreadable, key not in the party, entry retired) the hook is still armed through the
--     next frameadvance, and only this check stops it (pre_pump's disarm is one frame late);
--   * the phase declares NO `active` predicate, otherwise signals:poll() would re-arm it forever;
--   * single shot: every fire returns an event, and the drain removes the one-shot hook; the
--     NEXT battle_write call reports "done" for a landed write (the completion latch).
-- The callback also validates the overlay (binding:context), r0 == battle system, r1 == ctx,
-- ctx.command == the seam's command, and the key pin (battler key + party slot + both copies).
-- Missed seam on the ending frame: battle_write(..., true) returns nil, so the core defers the
-- faint to the checkpoint queue; its executor is step 4, so today that is a loud logged refusal.
--
-- Step 3: after a write the game must show its OWN effect within EFFECT_WINDOW (900) frames: the
-- replacement flag (u32[ctx + repl_flag_off + 4*b] & 1, 2+ party mons) or the LOSE result byte
-- (one-mon party). Later is a different, unrelated event and does not satisfy it.
--
-- Idle (checkpoint_ok, the deferred-write gate and the reducer's `idle`): lua/gen4/safety.lua's
-- checkpoint, polled ONCE per frame in pre_pump and cached for the frame (it is stateful). It is the
-- settled predicate runningFieldMap (fs+0x6C) != 0 AND taskman (fs+0x10) == 0 AND processManager
-- parent != NULL (field_app) AND child == NULL (launched_app), plus paused / save driver idle /
-- no encounter. encounter_active here = "the battle chain is up"; the encounter task's copy-back
-- is the taskman clause. `pc_active` for the reducer = another app than the battle one is
-- launched (the pack carries no PC-resident predicate: an approximation, absorbed by the
-- reducer's pc_frames window).
--
-- Left as seams (OUT of this card): deferred box/party writes (exec.* below refuse loudly, step 4),
-- key_change (step 5), full hello/tick fields (step 6; hello_fields/tick_fields here are the
-- minimum the protocol needs).
local Client = {}

Client.PHASE = "d7"
Client.EFFECT_WINDOW = 900
Client.BOX_RETRY_FRAMES = 60
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
        d7 = nil,                 -- the armed lease { key, slot, renewed_frame }
        d7_done = {},             -- physical key -> landed write (consumed once by battle_write)
        revoked = nil,            -- reason: a partial D7 write revokes every further D7 write
        watch = nil,              -- step 3: the effect window of the last landed write
        last_notes = "",
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

    local function party_read()
        local frame = now()
        if st.party_frame == frame then return st.party, st.party_why end
        local sd, why = R.save_data(mem, prof)
        local party
        if sd then party, why = R.party(mem, prof, sd) end
        st.party, st.party_why, st.party_frame = party, why, frame
        st.sd = sd
        return party, why
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
                local pid, csum = R.read(mem, a, 4), R.read(mem, a + 6, 2)
                if not pid or not csum then B.ok = false; return false, "box slot unreadable" end
                sigt[#sigt + 1] = (pid | (csum << 32))
            end
        end
        local sig = table.concat(sigt, ",")
        if B.ok and not force and sig == B.sig then B.dirty = false; return true, "unchanged" end
        local mons, complete = {}, true
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
                            mons[m.key] = { species_id = m.species, held_item_id = m.held_item, is_egg = m.is_egg,
                                            moves = m.moves, box = box, slot = slot }
                        end
                    end
                end
            end
        end
        B.ok = complete
        if not complete then return false, "incomplete box scan" end
        B.gen, B.mons, B.sig, B.dirty = B.gen + 1, mons, sig, false
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

    -- ── wire shapes (step 6 owns the full set) ─────────────────────────────────────
    local function party_wire(party)
        local out = {}
        for i, m in ipairs(party) do
            out[i] = { key = m.key, slot = m.slot, species_id = m.species, level = m.level, hp = m.hp,
                       maxHP = m.max_hp, held_item_id = m.decoded and m.decoded.held_item, moves = arr(m.moves) }
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

    -- ── D7: the seam site, resolved lazily (the pack carries none of it yet) ────────
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
    local function resolve_seam()
        if st.seam then return st.seam end
        local s, gap = d7_need("seam")
        if not s then return nil, gap end
        for _, k in ipairs({ "ctx_cmd_off", "bs_party_off", "party_hp_off", "repl_flag_off" }) do
            local v, vgap = d7_need(k)
            if not v then return nil, vgap end
        end
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

    -- Everything the callback needs, resolved from the LIVE chain (nothing cached across hits).
    -- Returns plan | nil, reason. Both spans are prevalidated here; nothing is written.
    local function d7_plan(lease, r0, r1)
        local b, bwhy = R.battle(mem, prof)
        if not b then return nil, "chain: " .. tostring(bwhy) end
        local c = chain_of(b.fingerprint)
        if r0 ~= c.bs then return nil, "r0 is not the battle system" end
        if r1 ~= c.ctx then return nil, "r1 is not the battle context" end
        local cmd = R.read(mem, c.ctx + d7cfg.ctx_cmd_off, 4)
        if cmd ~= st.seam.cmd then return nil, "command " .. tostring(cmd) .. " is not the seam command" end
        local be = prof.battle_enums
        if be.exempt_mask and (b.btype & be.exempt_mask) ~= 0 then return nil, "battle type is exempt" end
        local pick
        for _, m in ipairs(b.mons) do
            if m.b % 2 == 0 and m.key == lease.key then
                if pick then return nil, "ambiguous: two local battlers carry the key" end
                pick = m
            end
        end
        if not pick then return nil, "key is not a local battler" end
        if pick.slot ~= lease.slot then return nil, "party slot pin differs" end
        local bt, po = prof.battle, prof.party_off
        local party = R.read(mem, c.bs + d7cfg.bs_party_off, 4)         -- owner 0: every local battler
        local count = party and R.read(mem, party + po.count_off, 4)
        if not count or count < 1 or count > R.PARTY_CAPACITY or pick.slot >= count then return nil, "party range" end
        local rec = party + po.mons_off + prof.pkm.party_size * pick.slot
        local raw, rwhy = R.record(mem, rec, prof.pkm.party_size)
        if not raw then return nil, "record: " .. tostring(rwhy) end
        local mon, dwhy = pk4.decode_party_mon(raw, pkp)
        if not mon then return nil, "record: " .. tostring(dwhy) end      -- includes "locked": never XOR plaintext
        if mon.key ~= lease.key then return nil, "record identity differs" end
        if pick.max_hp < 1 or pick.max_hp > 999 or mon.max_hp < 1 or mon.max_hp > 999 or mon.hp > mon.max_hp then
            return nil, "hp range"
        end
        if (pick.hp == 0) ~= (mon.hp == 0) then return nil, "hp copies incoherent" end
        local bit = ((1 << pick.b) << bt.fainted_flag_shift)
        if bit & bt.fainted_flag_mask == 0 then return nil, "faint bit outside the mask" end
        local ks = stream(mon.pid, (d7cfg.party_hp_off - pk4.BOX_MON_SIZE) // 2 + 1)
        return { b = pick.b, slot = pick.slot, key = lease.key, noop = pick.hp == 0, rec = rec, pid = mon.pid, ks = ks,
                 bhp = c.ctx + bt.mons_off + bt.mon_size * pick.b + bt.hp_off, php = rec + d7cfg.party_hp_off,
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
        if lease.renewed_frame ~= frame - 1 then return ev("refused", "lease not renewed by the previous frame") end
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
            st.watch = { key = pl.key, b = pl.b, frame = frame, fp = pl.fp, ctx = pl.ctx, bs = pl.bs, bt = bt }
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
    function drv.checkpoint_ok() return st.ck, st.ck_why end
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
                    has_pokeballs = p.has_pokeballs and p.has_pokeballs() or false }
        if #admitted.rom_hash == 40 then f.rom_sha1 = admitted.rom_hash end
        local t = R.trainer(mem, prof, st.sd)
        if t then f.ot_id = t.otid end
        f.area_id, f.loc_name = area_now()
        local gen, ok = box_generation()
        if ok then f.pc_boxes, f.pc_boxes_generation = pc_boxes_wire(), gen end
        return f
    end
    function drv.tick_fields()
        local party = party_read()
        if not party then return nil end
        local f = { party = party_wire(party), in_battle = drv.in_battle(),
                    has_pokeballs = p.has_pokeballs and p.has_pokeballs() or false }
        f.area_id, f.loc_name = area_now()
        local gen, ok = box_generation()
        if ok then f.pc_boxes, f.pc_boxes_generation = pc_boxes_wire(), gen end
        return f
    end
    function drv.on_reset()
        pe:reset()
        st.d7, st.d7_done, st.watch = nil, {}, nil
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
            st.d7_done[sig.key] = { frame = sig.frame }
            log("D7 faint written " .. tostring(sig.key) .. " at frame " .. sig.frame)
        elseif sig.result == "noop" then
            st.d7_done[sig.key] = { frame = sig.frame, noop = true }
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
        local landed = st.d7_done[k]
        if landed then st.d7_done[k] = nil; return "done" end
        if ending then
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
        if st.d7 and st.d7.key ~= k then return "hold", "D7 seam busy with another faint" end
        local seam, swhy = resolve_seam()
        if not seam then return "hold", swhy end
        local ok, rwhy = signals:request(Client.PHASE)
        if ok then
            st.d7 = { key = k, slot = slot, renewed_frame = now() }
        elseif type(rwhy) == "string" and rwhy:find("already armed", 1, true) then
            if not st.d7 then signals:disarm(Client.PHASE); return "hold", "stale arm cleared" end
            st.d7.renewed_frame = now()                                  -- BUSY = armed = held: renew the lease
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
        -- 1. the lease: an unrenewed frame disarms (cleanup only; the callback guard is the real one)
        if st.d7 and st.d7.renewed_frame ~= frame - 1 then
            if signals then signals:disarm(Client.PHASE) end
            st.d7 = nil
        end
        -- 2. predicates (the D7 phase has none; poll() here and nowhere else)
        if signals then signals:poll() end
        -- 3. the world
        local party = party_read()
        local battle, bwhy = R.battle(mem, prof)
        st.battle, st.battle_why = battle, bwhy
        local app = bwhy == "not_battle"            -- another launched app: bag / party / PC / summary
        st.ck, st.ck_why = safety:checkpoint()
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
        local t = party and R.trainer(mem, prof, st.sd)
        snap.player_otid = t and t.otid
        -- 4. the reducer
        local events, notes = pe:step(snap)
        for _, e in ipairs(events) do session.send(e.name, e.data) end
        local joined = table.concat(notes, ",")
        if joined ~= st.last_notes then
            st.last_notes = joined
            if joined ~= "" then log("reducer: " .. joined) end
        end
        -- 5. the effect window
        watch_step(frame, battle)
    end
    -- the core does not pcall pre_pump: a fault here must not stop the frame loop
    function drv.pre_pump()
        local ok, err = pcall(pre_pump_body)
        if not ok and tostring(err) ~= st.pre_err then
            st.pre_err = tostring(err)
            log("pre_pump error: " .. st.pre_err)
        end
    end

    -- ── the deferred queue: step 4 owns the executors, until then they refuse LOUDLY ──
    local function not_yet(what)
        return function() return nil, "gen4 deferred " .. what .. " is not implemented (step 4)" end
    end
    local exec = {
        arm = function() end, disarm = function() end,
        faint_slot = function() error("gen4 overworld faint is not implemented (step 4)", 0) end,
        deposit = not_yet("deposit"), withdraw = not_yet("withdraw"), memorialize = not_yet("memorialize"),
        write_count = function() return st.attempted end,
        rescan = function() rescan_boxes() end,
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
