-- Gen 4 (HGSS / hge) C1-8 row o probe: the ACTIVE in-battle faint mechanism (plan D7/D12).
-- AUTHORED OFFLINE, NOT YET RUN. Seam derivation: docs/gen4/research/battle_faint_seam.md.
-- Instrumentation, not a production binding. No console.log in callbacks or frame loops; one
-- terminal receipt via io.open. Offline consumers set SLINK_GEN4_FAINT_TEST=true and get the
-- pure API (identity crypto, guarded resolve, two-copy write, readback verify, controls, judge).
--
-- Live env: SLINK_ROOT (repo), SLINK_GEN4_FAINT_CONFIG (json), SLINK_GEN4_FAINT_OUT (receipt).
-- The run loads cfg.state_path (the C1-9 FIGHT-menu state), resolves + validates the battle chain,
-- runs the instrument controls on a copy-on-write shadow, then runs ONE scenario with normal inputs.
-- Receipt: `PROBE o <PASS|FAIL|OPEN> <json>` + `RESULT: <same>` (tests/live/test_gen4_probe_gates.py
-- row_o() grammar). PASS needs the independent oracle AND the red negative controls.
local M = {}
local BUS = "ARM9 System Bus"

M.L = {
  FS = 0x021D4158, SAVEPTR = 0x021D2228, OVY = 12,
  -- SaveData: dynamic_region @+0x10, arrayHeaders @+0x23014 (16 B each, offset field +8); party = array 2
  SAVE_DYN = 0x10, SAVE_HDR = 0x23014, HDR_SIZE = 16, HDR_OFFSET = 8, PARTY_ID = 2,
  -- BattleSystem
  bs_type = 0x2C, bs_ctx = 0x30, bs_party = 0x68, bs_outcome = 0x2420,
  -- BattleContext
  ctx_cmd = 0x08, ctx_status = 0x213C, ctx_sel = 0x219C, ctx_mons = 0x2D40,
  -- BattleMon (0xC0): hp is s32
  mon_size = 0xC0, mon_hp = 0x4C, mon_maxhp = 0x50, mon_pid = 0x68, mon_otid = 0x74,
  -- Party {int max; int count; Pokemon mons[6]}; Pokemon = 0xEC; PartyPokemon tail @0x88
  party_count = 0x04, party_mons = 0x08, rec_size = 0xEC, rec_hp = 0x8E, rec_maxhp = 0x90,
  FAINT_SHIFT = 24, CMD_SELECT = 5, CMD_UFCE = 11, CMD_TURN_END = 12,
}
local L = M.L
-- Per-title offsets come from the pack profile (cfg.pack, from data/games/<pack>/profile.json); the defaults above
-- are HG. hge differs in the SaveData header table (0x2F014 vs 0x23014).
function M.configure(pack)
  local sv, b = pack.save, pack.battle
  L.SAVE_HDR, L.SAVE_DYN, L.HDR_SIZE = sv.array_headers_off, sv.dynamic_region_off, sv.array_header_size
  L.HDR_OFFSET, L.PARTY_ID = sv.array_header_fields.offset, sv.array_ids.party
  L.bs_ctx, L.ctx_mons, L.ctx_sel, L.mon_hp, L.mon_size = b.ctx_off, b.mons_off, b.selected_off, b.hp_off, b.mon_size
end
local BT_DOUBLES, BT_UNSUPPORTED = 0x02, 0x1C -- link | multi | tag: refuse (OPEN, no live case)

-- Exec seams. Addresses are pret xMAP (HG) and the pinned hge build (BYTE-IDENTICAL ov12 extents,
-- FILE, docs/gen4/research/battle_faint_seam.md section 5); pins = LE u32 of the first 4 bytes.
M.SEAMS = {
  turnend = {addr = 0x0224A958, pin = 0x1C0CB538, cmd = 12, name = "BattleControllerPlayer_TurnEnd"},
  ufce = {addr = 0x0224A70C, pin = 0xB082B5F8, cmd = 11, name = "BattleControllerPlayer_UpdateFieldConditionExtra"},
}
M.OBS = {
  heal = {addr = 0x02090C1C, pin = 0xB083B5F0, name = "HealParty"},
  blackout = {addr = 0x02052858, pin = 0xB086B5F8, name = "Task_Blackout"},
}
M.SCENARIOS = {
  seam_turnend = {kind = "primary", seam = "turnend", apply = {battle = true, party = true}},
  seam_ufce_bit = {kind = "primary", seam = "ufce", apply = {battle = true, party = true}, faint_bit = true},
  poll_fightmenu = {kind = "exploratory", seam = "poll", apply = {battle = true, party = true}},
  battle_only = {kind = "control", seam = "turnend", apply = {battle = true}},
  party_only = {kind = "control", seam = "turnend", apply = {party = true}},
}
local BOTH = {battle = true, party = true}
M.EFFECT_WINDOW = 900 -- frames after the write within which the game result byte must appear

local function u32(v) return v & 0xFFFFFFFF end
local function s32(v) v = u32(v); if v >= 0x80000000 then return v - 0x100000000 end return v end
local function inram(p) return type(p) == "number" and p >= 0x02000000 and p < 0x02400000 and p % 4 == 0 end
local function clone(t)
  if type(t) ~= "table" then return t end
  local r = {}; for k, v in pairs(t) do r[k] = clone(v) end; return r
end
local function copy_set(t) local r = {}; for k, v in pairs(t or {}) do r[k] = v end; return r end

-- ----- memory: BizHawk bus and a copy-on-write shadow (controls never touch the game) -----
function M.bus_mem()
  return {
    r8 = function(a) return memory.read_u8(a, BUS) end,
    r16 = function(a) return memory.read_u16_le(a, BUS) end,
    r32 = function(a) return u32(memory.read_u32_le(a, BUS)) end,
    w8 = function(a, v) memory.write_u8(a, v & 0xFF, BUS) end,
    w16 = function(a, v) memory.write_u16_le(a, v & 0xFFFF, BUS) end,
    w32 = function(a, v) memory.write_u32_le(a, u32(v), BUS) end,
  }
end
function M.shadow(mem)
  local o, s = {}, {}
  function s.r8(a) local v = o[a]; if v ~= nil then return v end return mem.r8(a) end
  function s.r16(a) return s.r8(a) | (s.r8(a + 1) << 8) end
  function s.r32(a) return s.r16(a) | (s.r16(a + 2) << 16) end
  function s.w8(a, v) o[a] = v & 0xFF end
  function s.w16(a, v) s.w8(a, v); s.w8(a + 1, v >> 8) end
  function s.w32(a, v) s.w16(a, v); s.w16(a + 2, v >> 16) end
  return s
end

-- ----- PK4 crypto (re-proved against server/adapters/gen4_codec.py by the model test) -----
local function lcg(seed) return (seed * 0x41C64E6D + 0x6073) & 0xFFFFFFFF end
local BLOCK_A = {[0] = 0, 0, 0, 0, 0, 0, 0x20, 0x20, 0x40, 0x60, 0x40, 0x60, 0x20, 0x20, 0x40, 0x60,
  0x40, 0x60, 0x20, 0x20, 0x40, 0x60, 0x40, 0x60, 0, 0, 0, 0, 0, 0, 0x20, 0x20}
function M.block_a_offset(pid) return BLOCK_A[(pid & 0x3E000) >> 13] end
-- PartyPokemon tail is PID-stream encrypted: HP = keystream word 3 (tail starts at 0x88), maxHP = word 4
function M.tail_words(pid)
  local seed, w = pid, {}
  for i = 0, 4 do seed = lcg(seed); w[i] = seed >> 16 end
  return w
end
-- identity from the (unlocked, encrypted) record: {pid, otid, species, flags, csum} | nil, reason, detail
function M.read_identity(mem, rec, opts)
  opts = opts or {}
  local pid, flags, csum = mem.r32(rec), mem.r16(rec + 4), mem.r16(rec + 6)
  if (flags & 3) ~= 0 and opts.fault ~= "locked" then
    return nil, "locked", {flags = flags} -- partyDecrypted/boxDecrypted: plaintext representation, never XOR it
  end
  local seed, sum, words = csum, 0, {}
  for i = 0, 63 do
    seed = lcg(seed)
    local w = mem.r16(rec + 8 + 2 * i) ~ (seed >> 16)
    words[i] = w; sum = sum + w
  end
  if (sum & 0xFFFF) ~= csum then return nil, "checksum", {stored = csum, computed = sum & 0xFFFF} end
  local a = M.block_a_offset(pid) // 2
  return {pid = pid, otid = words[a + 2] | (words[a + 3] << 16), species = words[a], flags = flags, csum = csum}
end
function M.rec_hp(mem, rec)
  local w = M.tail_words(mem.r32(rec))
  return mem.r16(rec + L.rec_hp) ~ w[3], mem.r16(rec + L.rec_maxhp) ~ w[4], w[3]
end

-- ----- chain, save party, targets -----
function M.chain(mem)
  local fs = mem.r32(L.FS); if not inram(fs) then return nil, "fs" end
  local sub0 = mem.r32(fs); if not inram(sub0) then return nil, "sub0" end
  local man = mem.r32(sub0 + 4); if not inram(man) then return nil, "man" end
  if mem.r32(man + 0x0C) ~= L.OVY then return nil, "overlay" end
  local bs = mem.r32(man + 0x1C); if not inram(bs) then return nil, "bs" end
  local ctx = mem.r32(bs + L.bs_ctx); if not inram(ctx) then return nil, "ctx" end
  return {fs = fs, sub0 = sub0, man = man, bs = bs, ctx = ctx, btype = mem.r32(bs + L.bs_type)}
end
function M.save_party(mem) -- base of the live save-array party, or nil
  local save = mem.r32(L.SAVEPTR); if not inram(save) then return nil end
  local off = mem.r32(save + L.SAVE_HDR + L.PARTY_ID * L.HDR_SIZE + L.HDR_OFFSET)
  local base = save + L.SAVE_DYN + off
  if not inram(base) then return nil end
  local count = mem.r32(base + L.party_count)
  if count < 1 or count > 6 then return nil end
  return base, count
end
function M.saved_hp(mem, slot)
  local base = M.save_party(mem); if not base then return nil end
  local hp, max = M.rec_hp(mem, base + L.party_mons + L.rec_size * slot)
  return hp, max
end
function M.want_from_save(mem, slot) -- the expected key, derived from the SAVE array (independent of the battle copy)
  local base = M.save_party(mem); if not base then return nil, "save_party" end
  local id, why = M.read_identity(mem, base + L.party_mons + L.rec_size * slot)
  if not id then return nil, why end
  return {pid = id.pid, otid = id.otid, slot = slot}
end

-- Guarded resolve. opts.fault in {identity, slot, locked} disables ONE check (revert-test hook).
-- Returns plan | nil, reason, detail. Both spans are prevalidated here, nothing is written.
function M.resolve(mem, want, opts)
  opts = opts or {}
  local c, why = M.chain(mem)
  if not c then return nil, "chain_" .. why end
  if (c.btype & BT_UNSUPPORTED) ~= 0 then return nil, "battle_type_unsupported", {btype = c.btype} end
  local doubles = (c.btype & BT_DOUBLES) ~= 0
  local cands = {}
  for b = 0, (doubles and 4 or 2) - 1 do
    local own = doubles and (b & 1) or b -- BattleSystem_GetPartyMon: doubles b&1, singles b
    if own == 0 then
      local idx = mem.r8(c.ctx + L.ctx_sel + b)
      local mon = c.ctx + L.ctx_mons + L.mon_size * b
      if idx ~= 6 and mem.r16(mon) ~= 0 and (opts.fault == "slot" or idx == want.slot) then
        cands[#cands + 1] = {b = b, idx = idx, mon = mon, own = own}
      end
    end
  end
  if #cands == 0 then return nil, "slot_not_active" end
  local plans, reason = {}, nil
  for _, cd in ipairs(cands) do
    local party = mem.r32(c.bs + L.bs_party + 4 * cd.own)
    local count = inram(party) and mem.r32(party + L.party_count) or 0
    if count < 1 or count > 6 or cd.idx >= count then
      reason = reason or "party_range"
    else
      local rec = party + L.party_mons + L.rec_size * cd.idx
      local id, why2, det = M.read_identity(mem, rec, opts)
      if not id then
        reason = reason or why2
      elseif opts.fault ~= "identity" and (id.pid ~= want.pid or id.otid ~= want.otid) then
        reason = reason or "identity"
      elseif opts.fault ~= "identity" and (mem.r32(cd.mon + L.mon_pid) ~= id.pid or mem.r32(cd.mon + L.mon_otid) ~= id.otid) then
        reason = reason or "battlemon_identity"
      else
        local bhp, bmax = s32(mem.r32(cd.mon + L.mon_hp)), mem.r32(cd.mon + L.mon_maxhp)
        local php, pmax, w3 = M.rec_hp(mem, rec)
        if bmax < 1 or bmax > 999 or bhp < 0 or bhp > bmax or pmax < 1 or pmax > 999 or php > pmax then
          reason = reason or "hp_range"
        elseif (bhp == 0) ~= (php == 0) then
          reason = reason or "copies_incoherent"
        else
          plans[#plans + 1] = {chain = c, b = cd.b, idx = cd.idx, own = cd.own, mon = cd.mon, rec = rec, party = party,
            id = id, w3 = w3, noop = (bhp == 0),
            before = {battle_hp = bhp, battle_max = bmax, party_hp = php, party_max = pmax, flags = id.flags},
            spans = {{name = "battle", addr = cd.mon + L.mon_hp, width = 4, value = 0},
                     {name = "party", addr = rec + L.rec_hp, width = 2, value = 0 ~ w3}}}
        end
      end
    end
  end
  if #plans > 1 then return nil, "ambiguous", {n = #plans} end
  if #plans == 0 then return nil, reason or "no_match" end
  return plans[1]
end

function M.apply(mem, plan, which)
  for _, sp in ipairs(plan.spans) do
    if which[sp.name] then
      if sp.width == 4 then mem.w32(sp.addr, sp.value) else mem.w16(sp.addr, sp.value) end
    end
  end
end
-- Readback of ALL four battle-HP bytes and both party-HP bytes. `expect` = spans that must read zero.
-- opts.fault in {verify_party, verify_high} blinds one half (revert-test hook).
function M.verify(mem, plan, expect, opts)
  opts = opts or {}
  local a = plan.mon + L.mon_hp
  local out = {ok = true, reasons = {}, battle_bytes = {mem.r8(a), mem.r8(a + 1), mem.r8(a + 2), mem.r8(a + 3)}}
  local raw = mem.r16(plan.rec + L.rec_hp)
  out.party_bytes = {raw & 0xFF, raw >> 8}
  out.party_plain = raw ~ plan.w3
  local function fail(r) out.ok = false; out.reasons[#out.reasons + 1] = r end
  if expect.battle then
    local b = out.battle_bytes
    local low = b[1] == 0 and b[2] == 0
    local high = (b[3] == 0 and b[4] == 0) or opts.fault == "verify_high"
    if not low then fail("battle_hp_nonzero") elseif not high then fail("battle_hp_high_stale") end
  end
  if expect.party and opts.fault ~= "verify_party" and out.party_plain ~= 0 then fail("party_hp_nonzero") end
  if mem.r32(plan.rec) ~= plan.id.pid or (mem.r16(plan.rec + 4) & 3) ~= 0 then fail("record_disturbed") end
  return out
end

-- ----- instrument controls: run on a shadow of the REAL live memory; each must be able to go red -----
function M.controls(mem, want, opts)
  opts = opts or {}
  local c = {}
  local plan, why = M.resolve(M.shadow(mem), want, opts)
  c.positive = {resolved = plan ~= nil, reason = why}
  if not plan then return c end
  local function refused(mutate_want, mutate_mem)
    local sh = M.shadow(mem)
    if mutate_mem then mutate_mem(sh, plan) end
    local w = clone(want); if mutate_want then mutate_want(w) end
    local p, r = M.resolve(sh, w, opts)
    return {refused = p == nil, reason = r}
  end
  c.wrong_pid = refused(function(w) w.pid = u32(w.pid ~ 1) end)
  c.wrong_otid = refused(function(w) w.otid = u32(w.otid ~ 0x10000) end)
  c.wrong_slot = refused(function(w) w.slot = (w.slot + 1) % 6 end)
  c.sentinel = refused(function(w) w.slot = 6 end, function(sh, p) sh.w8(p.chain.ctx + L.ctx_sel + p.b, 6) end)
  c.locked = refused(nil, function(sh, p) sh.w16(p.rec + 4, 1) end)
  local function readback(apply, prep)
    local sh = M.shadow(mem)
    if prep then prep(sh, plan) end
    M.apply(sh, plan, apply)
    local v = M.verify(sh, plan, BOTH, opts)
    return {detected = not v.ok, ok = v.ok, reasons = v.reasons}
  end
  local full = readback(BOTH)
  c.full = {verified = full.ok, reasons = full.reasons}
  c.battle_only = readback({battle = true})
  c.party_only = readback({party = true})
  -- a 2-byte battle-HP write over a stale high half: only a four-byte readback can catch it
  c.two_byte = readback({party = true}, function(sh, p)
    sh.w16(p.mon + L.mon_hp + 2, 1)
    sh.w16(p.mon + L.mon_hp, 0)
  end)
  return c
end
function M.judge_controls(c)
  local function chk(ok, why) if not ok then return false, why end return true end
  local steps = {
    {c.positive and c.positive.resolved, "positive_control_unresolved"},
    {c.wrong_pid and c.wrong_pid.refused, "wrong_pid_accepted"},
    {c.wrong_otid and c.wrong_otid.refused, "wrong_otid_accepted"},
    {c.wrong_slot and c.wrong_slot.refused, "wrong_slot_accepted"},
    {c.sentinel and c.sentinel.refused, "sentinel_accepted"},
    {c.locked and c.locked.refused, "locked_accepted"},
    {c.full and c.full.verified, "full_write_not_verified"},
    {c.battle_only and c.battle_only.detected, "battle_only_not_detected"},
    {c.party_only and c.party_only.detected, "party_only_not_detected"},
    {c.two_byte and c.two_byte.detected, "two_byte_stale_high_not_detected"},
  }
  for _, s in ipairs(steps) do local ok, why = chk(s[1], s[2]); if not ok then return false, why end end
  return true, ""
end

-- ----- scenario judge (pure; examples in the model test are hypothetical, never physical) -----
function M.judge(scn, o)
  if o.fatal then return "FAIL", "fatal: " .. tostring(o.fatal) end
  if not o.controls_ok then return "FAIL", "instrument controls red: " .. tostring(o.controls_why) end
  local w = o.write
  if not w then return "OPEN", "no write performed: " .. tostring(o.no_write_reason) end
  local heal = o.heal and o.heal[1]
  -- the game result must FOLLOW the write closely: a later natural faint (live run 163725, party_only) is not evidence
  local lat = o.latency and o.latency.write_to_effect
  local ended = o.effect and o.effect.outcome_frame ~= nil and lat ~= nil and lat <= M.EFFECT_WINDOW
  local copyback_zero = heal ~= nil and heal.saved_hp_at_entry == 0
  if scn.kind == "control" then
    if w.verify.ok then return "FAIL", "single-copy write passed the full readback (control cannot go red)" end
    if ended and copyback_zero then return "FAIL", "single-copy write passed the full-write oracle (control cannot go red)" end
    return "PASS", "single-copy write detected by readback and red against the copy-back oracle"
  end
  if not w.verify.ok then return "FAIL", "readback: " .. table.concat(w.verify.reasons, ",") end
  if scn.kind ~= "primary" then return "OPEN", "exploratory observation recorded (not a gate)" end
  if not ended then return "OPEN", "no game result byte observed after the write within budget" end
  if o.effect.outcome_value ~= 2 then return "FAIL", "unexpected game result byte " .. tostring(o.effect.outcome_value) end
  if not heal then return "OPEN", "no HealParty observed: pre-heal witness absent" end
  if not copyback_zero then return "FAIL", "copy-back lost the zero: saved HP at heal entry " .. tostring(heal.saved_hp_at_entry) end
  if o.post_heal_saved_hp == nil or o.post_heal_saved_hp ~= o.saved_max_hp then
    return "OPEN", "post-heal saved HP not observed at max"
  end
  return "PASS", "both copies zero; game LOSE byte; zero reached the save party before heal; native heal restored it"
end

-- ----- live run -------------------------------------------------------------------------
local function run()
  local root = assert(SLINK_ROOT or os.getenv("SLINK_ROOT"), "SLINK_ROOT required")
  local json = dofile(root .. "/lua/json_codec.lua")
  local f = assert(io.open(assert(os.getenv("SLINK_GEN4_FAINT_CONFIG"), "SLINK_GEN4_FAINT_CONFIG required"), "rb"))
  local cfg = assert(json.decode(f:read("a"))); f:close()
  local out = assert(os.getenv("SLINK_GEN4_FAINT_OUT"), "SLINK_GEN4_FAINT_OUT required")
  if cfg.pack then M.configure(cfg.pack) end
  -- per-build seam override (hge folds commands 9-11 into command 9: the wrapper derives addr/pin from the ROM table)
  for k, v in pairs(cfg.seams or {}) do M.SEAMS[k] = v end
  local scn = assert(M.SCENARIOS[cfg.scenario], "unknown scenario " .. tostring(cfg.scenario))
  local fault = (cfg.fault ~= json.null) and cfg.fault or nil
  local opts = {fault = fault}
  local mem = M.bus_mem()
  local obs = {scenario = cfg.scenario, kind = scn.kind, fault = fault, shots = json.array({}), trace = json.array({})}
  local callback_errors, callback_error = 0, nil
  local handles = {}
  local frame0

  local function shot(name)
    local p = cfg.shot_dir .. "/" .. cfg.scenario .. "_" .. name .. ".png"
    if pcall(function() client.screenshot(p) end) then obs.shots[#obs.shots + 1] = p end
  end
  local function hook(spec, cb)
    local h = event.on_bus_exec(function(a, v, fl)
      local ok, e = pcall(cb, a, v, fl)
      if not ok then callback_errors = callback_errors + 1; callback_error = tostring(e) end
    end, spec.addr, "g4faint." .. spec.name, BUS)
    assert(h ~= nil and tostring(h):gsub("[%-%{%}0]", "") ~= "", "exec registration failed: " .. spec.name)
    handles[#handles + 1] = h
  end

  local function body()
    pcall(function() emu.limitframerate(false) end)
    pcall(function() client.speedmode(cfg.requested_rate or 300) end)
    assert(savestate.load(cfg.state_path) ~= false, "savestate load failed")
    for _ = 1, 30 do emu.frameadvance() end
    frame0 = emu.framecount()

    -- identity + chain baseline (independent key from the SAVE array)
    local want, why = M.want_from_save(mem, cfg.want_slot or 0)
    assert(want, "save-array key unreadable: " .. tostring(why))
    local c0 = M.chain(mem)
    assert(c0, "state is not inside a battle (chain absent)")
    obs.want = {pid = want.pid, otid = want.otid, slot = want.slot}
    obs.chain = {fs = c0.fs, man = c0.man, bs = c0.bs, ctx = c0.ctx, battle_type = c0.btype}
    obs.cmd_at_start = mem.r32(c0.ctx + L.ctx_cmd)
    local locp = mem.r32(c0.fs + 0x20)
    if inram(locp) then obs.map_before = s32(mem.r32(locp)) end
    shot("pre")

    -- instrument controls (shadow only; the game memory is untouched)
    obs.controls = M.controls(mem, want, opts)
    obs.controls_ok, obs.controls_why = M.judge_controls(obs.controls)
    if not obs.controls_ok then return end

    local plan0, pwhy = M.resolve(mem, want, opts)
    assert(plan0, "target unresolved at baseline: " .. tostring(pwhy))
    obs.target = {battler = plan0.b, slot = plan0.idx, owner = plan0.own, before = plan0.before,
                  party_ptr = plan0.party, record = plan0.rec, battle_mon = plan0.mon}
    obs.saved_before = (M.saved_hp(mem, want.slot))
    obs.saved_max_hp = select(2, M.saved_hp(mem, want.slot))

    -- state
    local S = {hits = 0, wrong_image = 0, stale = 0, bad_state = 0, hit_frames = json.array({}),
               refusals = json.array({}), done = false}
    local O = {turnend_hits = 0}
    local armed, write_frame, input_done_frame = false, nil, nil
    local seen12 = {}
    local heal_hits, blackout_hits = json.array({}), json.array({})
    local had_chain, chain_gone_frame = true, nil
    local left5 = false
    local last_key

    local function do_write(fr, where, ctx_cmd)
      local plan, rwhy = M.resolve(mem, want, opts)
      if not plan then
        S.refusals[#S.refusals + 1] = {frame = fr, reason = rwhy}
        if #S.refusals >= 8 then S.done = true; obs.no_write_reason = "refused x8: " .. tostring(rwhy) end
        return
      end
      if plan.noop then S.done = true; obs.no_write_reason = "target already at zero (game faint)"; return end
      local st_before
      if scn.faint_bit then st_before = mem.r32(plan.chain.ctx + L.ctx_status) end
      M.apply(mem, plan, scn.apply)
      if scn.faint_bit then
        mem.w32(plan.chain.ctx + L.ctx_status, st_before | ((1 << plan.b) << L.FAINT_SHIFT))
      end
      local v = M.verify(mem, plan, BOTH, opts)
      obs.write = {frame = fr, where = where, cmd = ctx_cmd, applied = copy_set(scn.apply), before = plan.before,
                   verify = v, battler = plan.b, slot = plan.idx}
      if scn.faint_bit then
        obs.write.status_before = st_before
        obs.write.status_after = mem.r32(plan.chain.ctx + L.ctx_status)
      end
      write_frame = fr
      S.done = true
    end

    local function seam_cb(spec)
      return function(a, val)
        local fr = emu.framecount()
        if mem.r32(spec.addr) ~= spec.pin then S.wrong_image = S.wrong_image + 1; return end -- wrong overlay: drop first
        local r0 = u32(emu.getregister("ARM9 r0")); local r1 = u32(emu.getregister("ARM9 r1"))
        local ch = M.chain(mem)
        if not ch or ch.bs ~= r0 or ch.ctx ~= r1 then S.stale = S.stale + 1; return end
        local cmd = mem.r32(ch.ctx + L.ctx_cmd)
        if cmd ~= spec.cmd then S.bad_state = S.bad_state + 1; return end
        S.hits = S.hits + 1
        if #S.hit_frames < 64 then S.hit_frames[#S.hit_frames + 1] = fr end
        if armed and not S.done then do_write(fr, spec.name, cmd) end
      end
    end

    local seam = M.SEAMS[scn.seam == "poll" and "turnend" or scn.seam]
    obs.seam = {addr = seam.addr, pin = seam.pin, name = seam.name, armed_mode = scn.seam}
    hook(seam, seam_cb(seam))
    if scn.seam == "ufce" then -- plus TurnEnd as an observer for hit-vs-poll coverage
      hook(M.SEAMS.turnend, function()
        if mem.r32(M.SEAMS.turnend.addr) ~= M.SEAMS.turnend.pin then return end
        O.turnend_hits = O.turnend_hits + 1
      end)
    end
    local function observer(spec, list)
      hook(spec, function()
        if mem.r32(spec.addr) ~= spec.pin then return end
        if #list < 8 then
          list[#list + 1] = {frame = emu.framecount(), saved_hp_at_entry = (M.saved_hp(mem, want.slot))}
        end
      end)
    end
    observer(M.OBS.heal, heal_hits)
    observer(M.OBS.blackout, blackout_hits)

    -- per-frame poll: change log + the observables the effect judge needs
    local first_out, outv, script_frame, bit_set_seen, bit_clear_frame
    local function sample()
      local fr = emu.framecount()
      local ch = M.chain(mem)
      local key
      if ch then
        local cmd = mem.r32(ch.ctx + L.ctx_cmd)
        local out_b = mem.r8(ch.bs + L.bs_outcome)
        local mon0 = ch.ctx + L.ctx_mons
        local bhp = s32(mem.r32(mon0 + L.mon_hp))
        local sel = mem.r8(ch.ctx + L.ctx_sel)
        local party = mem.r32(ch.bs + L.bs_party)
        local php = (inram(party) and sel < 6) and (M.rec_hp(mem, party + L.party_mons + L.rec_size * sel)) or -1
        if cmd == L.CMD_TURN_END or cmd == seam.cmd then seen12[fr] = true end -- seam.cmd: 11 on HG, 9 on hge
        if cmd ~= L.CMD_SELECT then left5 = true end
        if write_frame and out_b ~= 0 and not first_out then first_out, outv = fr, out_b end
        if write_frame and cmd == 22 and not script_frame then script_frame = fr end -- RUN_SCRIPT after the write
        local fb = (mem.r32(ch.ctx + L.ctx_status) >> L.FAINT_SHIFT) & 1
        if write_frame and scn.faint_bit then
          if fb == 1 then bit_set_seen = true elseif bit_set_seen and not bit_clear_frame then bit_clear_frame = fr end
        end
        key = cmd .. "," .. out_b .. "," .. bhp .. "," .. php .. "," .. sel
        if key ~= last_key and #obs.trace < 120 then
          obs.trace[#obs.trace + 1] = {f = fr, cmd = cmd, out = out_b, bhp = bhp, php = php, sel = sel}
        end
        had_chain = true
      else
        if had_chain and not chain_gone_frame then chain_gone_frame = fr end
        key = "nochain," .. tostring((M.saved_hp(mem, want.slot)))
        if key ~= last_key and #obs.trace < 120 then
          obs.trace[#obs.trace + 1] = {f = fr, nochain = true, saved_hp = (M.saved_hp(mem, want.slot))}
        end
      end
      last_key = key
    end
    local function step(n) for _ = 1, n do emu.frameadvance(); sample() end end
    local function tap(btn, hold, wait)
      for _ = 1, hold do joypad.set({[btn] = true}); emu.frameadvance(); sample() end
      step(wait or 0)
    end
    local function field_idle()
      local fs = mem.r32(L.FS)
      return inram(fs) and mem.r32(fs + 0x10) == 0 and mem.r32(fs + 0x6C) ~= 0 and not M.chain(mem)
    end

    sample()
    armed = scn.seam ~= "poll"
    if scn.seam == "poll" then -- worst-case arrival: the command lands while the selection screen idles (command 5)
      do_write(emu.framecount(), "poll@selection", obs.cmd_at_start)
      step(90)
      obs.idle_effect = {cmd = mem.r32(M.chain(mem).ctx + L.ctx_cmd), out = mem.r8(M.chain(mem).bs + L.bs_outcome)}
      shot("poll_idle")
    end
    -- normal inputs: FIGHT, (Right for the 2nd move = a non-damaging turn), confirm
    -- live finding (run 163238): the FIRST A only wakes the button cursor; the second opens FIGHT
    if cfg.wake ~= false then tap("A", 3, 40) end
    tap("A", 3, 50); shot("moves")
    if cfg.move_right ~= false then tap("Right", 3, 20) end
    tap("A", 3, 30)
    input_done_frame = emu.framecount()
    local budget = cfg.max_frames or 5400
    local waited = 0
    -- seam scenarios: wait for the hook to write; A taps only advance text, never re-select (abort at the next menu)
    while armed and not S.done and waited < budget do
      step(44); tap("A", 2, 0); waited = waited + 46
      local ch = M.chain(mem)
      if left5 and ch and not S.done and mem.r32(ch.ctx + L.ctx_cmd) == L.CMD_SELECT then
        obs.no_write_reason = "turn ended at the next selection screen without a seam hit"
        break
      end
      if not ch and had_chain then obs.no_write_reason = obs.no_write_reason or "battle ended before a seam hit"; break end
    end
    if armed and not S.done and not obs.no_write_reason then obs.no_write_reason = "budget exhausted without a seam hit" end
    if not write_frame and #S.refusals > 0 then
      obs.no_write_reason = tostring(obs.no_write_reason) .. "; last refusal: " .. tostring(S.refusals[#S.refusals].reason)
    end
    local nshots, last_shot = 0, 0
    if write_frame then shot("after_write") end
    -- after the write: advance text and observe until the field is idle again
    local quiet, spent = 0, 0
    if scn.kind == "control" then budget = 1500 end -- controls only need the window after the write
    while spent < budget and (write_frame or not armed) do
      step(40); spent = spent + 40
      if write_frame and nshots < 14 and emu.framecount() - last_shot >= 70 then
        nshots = nshots + 1; last_shot = emu.framecount(); shot("w" .. (emu.framecount() - write_frame))
      end
      -- advance text only while something is running: an idle A would talk to the nurse (a second HealParty)
      if not field_idle() then tap("A", 2, 0); spent = spent + 2 end
      if chain_gone_frame and field_idle() then quiet = quiet + 42 else quiet = 0 end
      if quiet >= 240 then break end
    end
    step(60)
    shot("final")

    -- assemble
    local lat = {}
    if write_frame then
      lat.cmd_to_write = write_frame - frame0
      lat.input_frames = input_done_frame and (input_done_frame - frame0) or nil
      lat.write_to_effect = first_out and (first_out - write_frame) or nil
    end
    obs.latency = lat
    obs.effect = {outcome_frame = first_out, outcome_value = outv, chain_gone_frame = chain_gone_frame,
                  script_after_write_frame = script_frame, faint_bit_consumed_frame = bit_clear_frame}
    obs.heal = heal_hits
    obs.blackout = blackout_hits
    obs.seam.hits, obs.seam.wrong_image, obs.seam.stale, obs.seam.bad_state = S.hits, S.wrong_image, S.stale, S.bad_state
    obs.seam.hit_frames = S.hit_frames; obs.seam.refusals = S.refusals
    local nosight = 0
    for _, hf in ipairs(S.hit_frames) do
      if not (seen12[hf] or seen12[hf - 1] or seen12[hf + 1]) then nosight = nosight + 1 end
    end
    obs.seam.hits_without_poll_sight = nosight -- frame-boundary poll never saw the command at that hit (+-1 frame)
    obs.turnend_observer_hits = (scn.seam == "ufce") and O.turnend_hits or nil
    obs.saved_final = (M.saved_hp(mem, want.slot))
    obs.post_heal_saved_hp = heal_hits[1] and obs.saved_final or nil
    local fs2 = mem.r32(L.FS)
    local lp2 = inram(fs2) and mem.r32(fs2 + 0x20) or 0
    if inram(lp2) then obs.map_after = s32(mem.r32(lp2)) end
    obs.written_in_game = write_frame ~= nil
  end

  local ok, err = pcall(body)
  if not ok then obs.fatal = tostring(err) end
  for _, h in ipairs(handles) do pcall(event.unregisterbyid, h) end
  local scn_status, reason = M.judge(scn, obs)
  if obs.fatal then scn_status, reason = "FAIL", "fatal: " .. obs.fatal end
  local payload = {
    schema = "gen4-probe-row-v1", run_id = cfg.run_id, title = cfg.title, rom_sha1 = cfg.rom_sha1, level = "PHYSICAL",
    mode = cfg.scenario, reason = reason, observation = obs, requested_rate = cfg.requested_rate,
    script_sha256 = cfg.script_sha256, profile_sha256 = cfg.profile_sha256, callback_errors = callback_errors,
    source_head = cfg.source_head, producer = "C1-8",
    oracle = "game result byte BattleSystem+0x2420; save-array party HP read at HealParty entry (independent of both written spans)",
    negative_control = obs.controls, callback_error = callback_error,
  }
  if callback_errors > 0 and scn_status ~= "FAIL" then payload.reason = "callback fault"; scn_status = "FAIL" end
  local enc, e2 = json.encode(payload)
  local line = enc and ("PROBE o " .. scn_status .. " " .. enc) or ("PROBE o FAIL " .. json.encode({
    schema = "gen4-probe-row-v1", run_id = cfg.run_id, title = cfg.title, rom_sha1 = cfg.rom_sha1, level = "PHYSICAL",
    reason = "receipt encode failed: " .. tostring(e2), callback_errors = callback_errors}))
  if not enc then scn_status = "FAIL" end
  local fh = assert(io.open(out, "w"), "cannot publish receipt: " .. out)
  fh:write(line, "\n", "RESULT: ", scn_status, "\n"); fh:close()
  pcall(client.exit)
end

if SLINK_GEN4_FAINT_TEST then return M end
run()
return M
