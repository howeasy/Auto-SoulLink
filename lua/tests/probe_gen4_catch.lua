-- Gen 4 G2 catch probe (HG/hge): a native wild CAPTURE with normal inputs from the FIGHT menu of a settled wild battle.
-- Instrumentation, not a production binding. Reads only (NO game-memory writes). One terminal receipt via io.open.
-- Env: SLINK_ROOT, SLINK_GEN4_CATCH_CONFIG (json), SLINK_GEN4_CATCH_OUT (receipt).
-- cfg: state_path, shot_dir, pack{save,battle,system}, keys (list of {k, hold, wait, shot}) = the menu path to the throw,
--      mode "explore" (run keys + screenshots only) | "catch" (throw loop + oracle + native SAVE legs), max_throws.
local M = {}
local BUS = "ARM9 System Bus"
local FS, SAVEPTR = 0x021D4158, 0x021D2228
local function u32(v) return v & 0xFFFFFFFF end
local function s32(v) v = u32(v); if v >= 0x80000000 then return v - 0x100000000 end return v end
local function inram(p) return type(p) == "number" and p >= 0x02000000 and p < 0x02400000 and p % 4 == 0 end
local mem = {
  r8 = function(a) return memory.read_u8(a, BUS) end,
  r16 = function(a) return memory.read_u16_le(a, BUS) end,
  r32 = function(a) return u32(memory.read_u32_le(a, BUS)) end,
}
local L = {bs_ctx = 0x30, bs_outcome = 0x2420, bs_party = 0x68, ctx_cmd = 0x08, ctx_mons = 0x2D40, mon_size = 0xC0,
  mon_pid = 0x68, mon_otid = 0x74, mon_hp = 0x4C, mon_species = 0x00, SAVE_HDR = 0x23014, SAVE_DYN = 0x10, HDR_SIZE = 16,
  HDR_OFFSET = 8, PARTY_ID = 2}
function M.configure(pack)
  local sv, b = pack.save, pack.battle
  L.SAVE_HDR, L.SAVE_DYN, L.HDR_SIZE = sv.array_headers_off, sv.dynamic_region_off, sv.array_header_size
  L.HDR_OFFSET, L.PARTY_ID = sv.array_header_fields.offset, sv.array_ids.party
  L.bs_ctx, L.ctx_mons, L.mon_size, L.mon_hp = b.ctx_off, b.mons_off, b.mon_size, b.hp_off
end

-- zero-hook battle chain (docs/gen4/research/battle_pointer.md)
function M.chain()
  local fs = mem.r32(FS); if not inram(fs) then return nil end
  local sub0 = mem.r32(fs); if not inram(sub0) then return nil end
  local man = mem.r32(sub0 + 4); if not inram(man) then return nil end
  if mem.r32(man + 0x0C) ~= 12 then return nil end
  local bs = mem.r32(man + 0x1C); if not inram(bs) then return nil end
  local ctx = mem.r32(bs + L.bs_ctx); if not inram(ctx) then return nil end
  return {fs = fs, bs = bs, ctx = ctx}
end
-- live save-array party: base + count (SaveArray_Get(party))
function M.save_party()
  local save = mem.r32(SAVEPTR); if not inram(save) then return nil end
  local off = mem.r32(save + L.SAVE_HDR + L.PARTY_ID * L.HDR_SIZE + L.HDR_OFFSET)
  local base = save + L.SAVE_DYN + off
  if not inram(base) then return nil end
  return base, mem.r32(base + 4)
end
function M.rec_pid(base, slot) return mem.r32(base + 8 + 0xEC * slot) end

local function run()
  local root = assert(SLINK_ROOT or os.getenv("SLINK_ROOT"), "SLINK_ROOT required")
  local json = dofile(root .. "/lua/json_codec.lua")
  local f = assert(io.open(assert(os.getenv("SLINK_GEN4_CATCH_CONFIG")), "rb"))
  local cfg = assert(json.decode(f:read("a"))); f:close()
  local out = assert(os.getenv("SLINK_GEN4_CATCH_OUT"))
  if cfg.pack then M.configure(cfg.pack) end
  local obs = {shots = json.array({}), keylog = json.array({}), throws = json.array({}), trace = json.array({})}
  local status, reason = "OPEN", "not finished"
  local function shot(name)
    local p = cfg.shot_dir .. "/" .. name .. ".png"
    if pcall(function() client.screenshot(p) end) then obs.shots[#obs.shots + 1] = p end
  end
  local last_key
  local function sample() -- change log of the observables (no per-frame console traffic)
    local ch = M.chain()
    local base, count = M.save_party()
    local key
    if ch then
      key = table.concat({mem.r32(ch.ctx + L.ctx_cmd), mem.r8(ch.bs + L.bs_outcome), count or -1}, ",")
      if key ~= last_key and #obs.trace < 200 then
        obs.trace[#obs.trace + 1] = {f = emu.framecount(), cmd = mem.r32(ch.ctx + L.ctx_cmd),
                                     out = mem.r8(ch.bs + L.bs_outcome), party = count}
      end
      if mem.r8(ch.bs + L.bs_outcome) ~= 0 and not obs.outcome_frame then
        obs.outcome_frame, obs.outcome_value = emu.framecount(), mem.r8(ch.bs + L.bs_outcome)
      end
    else
      key = "nochain," .. tostring(count)
      if not obs.chain_gone_frame and obs.had_chain then obs.chain_gone_frame = emu.framecount() end
      if key ~= last_key and #obs.trace < 200 then
        obs.trace[#obs.trace + 1] = {f = emu.framecount(), nochain = true, party = count}
      end
    end
    last_key = key
  end
  local function step(n) for _ = 1, n do emu.frameadvance(); sample() end end
  local function tap(k, hold, wait)
    for _ = 1, hold or 2 do joypad.set({[k] = true}); emu.frameadvance(); sample() end
    step(wait or 20)
  end
  local function run_keys(keys, tag)
    for i, e in ipairs(keys) do
      tap(e.k, e.hold, e.wait)
      obs.keylog[#obs.keylog + 1] = {tag = tag, i = i, k = e.k, f = emu.framecount()}
      if e.shot then shot(tag .. "_" .. i .. "_" .. e.k) end
    end
  end

  local ok, err = pcall(function()
    pcall(function() emu.limitframerate(false) end)
    pcall(function() client.speedmode(cfg.requested_rate or 300) end)
    assert(savestate.load(cfg.state_path) ~= false, "savestate load failed")
    for _ = 1, 30 do emu.frameadvance() end
    local ch = assert(M.chain(), "state is not in a battle")
    obs.had_chain = true
    local mon1 = ch.ctx + L.ctx_mons + L.mon_size
    obs.foe = {pid = mem.r32(mon1 + L.mon_pid), otid = mem.r32(mon1 + L.mon_otid), species = mem.r16(mon1),
               hp = s32(mem.r32(mon1 + L.mon_hp))}
    local base, count = M.save_party()
    obs.party_before = count
    obs.pids_before = {}
    for i = 0, (count or 0) - 1 do obs.pids_before[#obs.pids_before + 1] = M.rec_pid(base, i) end
    shot("pre")
    step(1)
    if cfg.mode == "explore" then
      run_keys(cfg.keys, "x")
      shot("end")
      status, reason = "OPEN", "exploration only"
      return
    end
    -- catch: reach the bag and the ball, throw; retry (each throw returns to the menu or ends the battle)
    local throws = 0
    local maxt = cfg.max_throws or 10
    local ball_keys = cfg.throw_keys or cfg.keys
    local wake = cfg.wake_keys or {}
    local function at_menu()
      local c = M.chain()
      return c and mem.r32(c.ctx + L.ctx_cmd) == 5
    end
    run_keys(wake, "wake")
    while throws < maxt and not obs.outcome_frame do
      throws = throws + 1
      local rec = {n = throws, f0 = emu.framecount(), party = (select(2, M.save_party()))}
      run_keys(ball_keys, "t" .. throws)
      -- wait for the throw to resolve: back at the menu (command 5), or the result byte appears
      local waited = 0
      while waited < 1500 and not obs.outcome_frame and not (at_menu() and waited > 120) do
        step(30); waited = waited + 30
        -- advance text (a held A would also re-open the bag at the menu; only while not at the menu)
        if not at_menu() then tap("A", 2, 0) end
      end
      rec.f1, rec.outcome = emu.framecount(), obs.outcome_value
      obs.throws[#obs.throws + 1] = rec
      shot("throw" .. throws)
    end
    obs.throw_count = throws
    -- after the result: dismiss the nickname prompt (B = No), advance until the field is idle again
    local quiet, nshot = 0, 0
    for i = 1, 400 do
      step(30)
      if i % 6 == 1 and nshot < 10 then nshot = nshot + 1; shot("dismiss" .. i) end
      local fs = mem.r32(FS)
      local idle = inram(fs) and mem.r32(fs + 0x10) == 0 and mem.r32(fs + 0x6C) ~= 0 and not M.chain()
      if idle then quiet = quiet + 30 else quiet = 0; tap(cfg.dismiss_key or "B", 2, 0) end
      if quiet >= 240 then break end
    end
    shot("after_battle")
    local base2, count2 = M.save_party()
    obs.party_after = count2
    obs.pids_after = {}
    for i = 0, (count2 or 0) - 1 do obs.pids_after[#obs.pids_after + 1] = M.rec_pid(base2, i) end
    -- native SAVE: replay the pack legs
    if cfg.save_legs then
      -- same semantics as gen4_route_play.lua play_leg: press/hold/wait, repeat while `until` is false, bounded by max_frames
      local function rs(a) return mem.r32(a) end
      local function until_ok(u)
        local base = rs(u.address)
        local deref = u["deref"] or {}
        if u.zero and #deref == 0 and u.offset == 0 then return base == 0 end
        for _, off in ipairs(deref) do
          if base == 0 then return false end
          base = rs(base + off)
        end
        if base == 0 then return false end
        local v = rs(base + u.offset)
        if u.nonzero then return v ~= 0 end
        if u.zero then return v == 0 end
        return v == u.value
      end
      local function leg(name)
        local l = cfg.save_legs[name]
        local u, used = l["until"], 0
        local function adv(b)
          if used >= l.max_frames then return false end
          joypad.set(b); emu.frameadvance(); sample(); used = used + 1
          return until_ok(u)
        end
        if until_ok(u) then return 0 end
        while used < l.max_frames do
          local before = used
          for _, st in ipairs(l.steps) do
            local b = {}
            for _, n in ipairs(st.press) do b[n] = true end
            for _ = 1, st.hold_frames do if adv(b) then return used end end
            for _ = 1, st.then_wait_frames do if adv({}) then return used end end
          end
          if used == before and adv({}) then return used end
        end
        return nil
      end
      obs.save = {}
      for _, name in ipairs({"open_start_menu", "start_menu_cursor_to_save", "start_menu_select_save",
                              "save_confirm_until_saved", "close_start_menu"}) do
        local used = leg(name)
        obs.save[#obs.save + 1] = {leg = name, f = emu.framecount(), frames = used}
        if used == nil then obs.save_failed = name; shot("save_failed_" .. name); break end
        shot("save_" .. name)
      end
      step(120)
    end
    obs.final_frame = emu.framecount()
    status, reason = "OPEN", "recorded; the wrapper judges against the lane battery"
  end)
  if not ok then obs.fatal = tostring(err); status, reason = "FAIL", obs.fatal end
  local payload = {schema = "gen4-catch-v1", level = "PHYSICAL", producer = "G2-catch", run_id = cfg.run_id, title = cfg.title,
                   rom_sha1 = cfg.rom_sha1, setup = cfg.setup, synth = cfg.synth, observation = obs,
                   source_head = cfg.source_head, script_sha256 = cfg.script_sha256, reason = reason}
  local enc, e2 = json.encode(payload)
  local fh = assert(io.open(out, "w"))
  fh:write(enc and ("CATCH " .. status .. " " .. enc) or ("CATCH FAIL " .. tostring(e2)), "\n", "RESULT: ", status, "\n")
  fh:close()
  pcall(client.exit)
end

if SLINK_GEN4_CATCH_TEST then return M end
run()
return M
