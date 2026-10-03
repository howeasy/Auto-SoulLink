-- Gen 4 (HGSS) scripted route walk: CONTINUE (A/Start only) -> walk tools/gen4_routes.py's route
-- with normal button input, position verified from RAM per tile -> pace in grass -> wild battle ->
-- savestates. NO writes to game memory; reads only. One buffered log, no per-frame console.log.
--
-- env: G4_REPO (repo root), G4_ROUTE (route.json), G4_OUT (log path), G4_LANE (state dir),
--      G4_TAG (state name prefix), optional G4_LOAD_STATE (resume a resync state instead of booting),
--      G4_PACE_MAX (max pace steps, default route's), G4_SETTLE (frames to wait after battle start).
-- exit status is the LAST log line `RESULT <status> ...` (BATTLE | PC_DEPOSIT | PC_WITHDRAW | RESYNC | FAIL <why>).
--
-- Route kinds (route.kind): absent = walk to wild grass and fight; "errand" = enter/talk/exit a house
-- (a door step ends the leg with RESYNC done=1); "pc" = the Cherrygrove Pokemon Center PC: walk to the tile
-- south of the PC, face it, deposit party slot 1 (a SYNTH party-2 save) through the PC UI by BUTTONS ONLY,
-- native SAVE, verify by RAM (tools/gen4_routes.py plan_pc; docs in that file and tests/TESTING.md);
-- route.phase == "withdraw" = the sibling leg: WITHDRAW POKEMON, grab the box 0 slot 0 mon into a party with room;
-- "hatch" = pace on plain floor until the SYNTH egg1 hatches (plan_hatch), decode the party before/after/after
-- SAVE; "reload" = a fresh boot from the saved battery, confirmed by RAM.
-- RESYNC detail: `map= x= y= dir= done=<0|1> state=<path>`; done=0 = interrupted mid-walk (re-plan the
-- same phase), done=1 = the phase finished (the next phase starts from the state).
local Driver={}
Driver.BATTLE_SETTLE_FRAMES=900 -- existing native battle_settled wait, reused by diagnostics
function Driver.position(title)
  local fs=memory.read_u32_le(title.symbols.sFieldSysPtr.address,"ARM9 System Bus")
  assert(fs~=0,"bridge FieldSystem absent")
  local loc=memory.read_u32_le(fs+0x20,"ARM9 System Bus")
  local spec=title.profile.location
  local result={}
  for _,key in ipairs({"map","warp","x","y","dir"}) do
    local v=memory.read_u32_le(loc+spec[key.."_off"],"ARM9 System Bus")
    result[key]=v>=0x80000000 and v-0x100000000 or v
  end
  return result
end
function Driver.run(bridge)
local native_emu,native_joypad=emu,joypad
local emu=bridge and setmetatable({frameadvance=function()
  local buttons=bridge.buttons or {}; bridge.buttons={}; bridge.step(buttons)
end},{__index=native_emu}) or native_emu
local joypad=bridge and {set=function(buttons) bridge.buttons=buttons; native_joypad.set(buttons) end} or native_joypad
local function getenv(key) return bridge and (bridge.env or {})[key] or os.getenv(key) end
local BUS = "ARM9 System Bus"
local FS, SAVEPTR = 0x021D4158, 0x021D2228
if bridge then FS=assert(bridge.title.symbols.sFieldSysPtr.address); SAVEPTR=assert(bridge.title.symbols.sSaveDataPtr.address) end
local OVY_BATTLE = 12
local REPO, OUT, LANE = getenv("G4_REPO"), getenv("G4_OUT"), getenv("G4_LANE")
local TAG = getenv("G4_TAG") or "route"
local lines = {}
local function say(...)
  local t = {}
  for i = 1, select("#", ...) do t[#t + 1] = tostring(select(i, ...)) end
  lines[#lines + 1] = string.format("[f%d] %s", emu.framecount(), table.concat(t, " "))
end
local function flush()
  if bridge then bridge.lines=lines; return end
  local f = io.open(OUT, "w")
  if f then f:write(table.concat(lines, "\n"), "\n"); f:close() end
end
local shot -- defined below; a FAIL leaves a screenshot of the runtime state
local terminal_witness -- withdraw-only, read-only; invoked before any terminal cleanup
local function finish(status, ...)
  if terminal_witness then
    local ok,why=pcall(terminal_witness,status)
    if not ok then say("PC_WITNESS_GAP", "terminal_read_failed", tostring(why)) end
  end
  joypad.set({}) -- never leave a button held in the result state or in a savestate
  if status == "FAIL" and shot then shot("fail") end
  say("RESULT", status, ...)
  flush()
  if bridge then error({route_result={status=status,detail=table.concat({...}," "),lines=lines}},0) end
  local ok, err = pcall(function() client.exit() end)
  if not ok then
    say("client.exit failed:", tostring(err))
    flush()
    pcall(function() os.exit(0) end) -- best effort: the spin below is the last resort
  end
  while true do emu.frameadvance() end -- never return into the caller after exit
end
local function r32(a) return memory.read_u32_le(a, BUS) end
local function r16(a) return memory.read_u16_le(a, BUS) end
local function r8(a) return memory.read_u8(a, BUS) end
local function s32(a) local v = r32(a); if v >= 0x80000000 then v = v - 0x100000000 end return v end
local function hex(v) return v and string.format("0x%08X", v) or "nil" end
local function inram(p) return p >= 0x02000000 and p < 0x02400000 end
pcall(function() emu.limitframerate(false) end)

local J = dofile(REPO .. "/lua/json_codec.lua")
local route,jerr
if bridge then route=bridge.route else
  local fh = assert(io.open(getenv("G4_ROUTE"), "rb"))
  route,jerr=J.decode(fh:read("*a"), {bytes = 8 * 1024 * 1024}); fh:close()
end
if not route then finish("FAIL", "route_json", jerr) end

-- ----- RAM probes --------------------------------------------------------------------------
local function fsys() local f = r32(FS); return inram(f) and f or nil end
local function taskman() local f = fsys(); return f and r32(f + 0x10) or nil end
-- FieldSystem.location (fs+0x20) -> Location {mapId, warpId, x, y, direction}
local function loc()
  local f = fsys(); if not f then return nil end
  local p = r32(f + 0x20); if not inram(p) then return nil end
  return {map = s32(p), x = s32(p + 8), y = s32(p + 12), dir = s32(p + 16)}
end
-- live facing of the player (see pc_deposit): 0 north, 1 south, 2 west, 3 east.
-- fs+0x40 IS FieldSystem.playerAvatar (include/field_system.h:128; mapObjectManager is at +0x3C, line 127,
-- and unk_44 at +0x44), asm GetInteractedMetatileScript loads it the same way (overlay_01_021E6880.s:1470,
-- `ldr r0, [r5, #0x40]` before PlayerAvatar_GetFacingDirection). PlayerAvatar.mapObject is at +0x30
-- (include/player_avatar.h:39) and LocalMapObject.currentFacing at +0x28 (include/map_object.h:59).
local function facing()
  local f = fsys(); if not f then return nil end
  local av = r32(f + 0x40); if not inram(av) then return nil end
  local mo = r32(av + 0x30); if not inram(mo) then return nil end
  return r32(mo + 0x28)
end
local function idle_now()
  local f = fsys(); if not f then return false end
  return r32(f + 0x10) == 0 and r32(f + 0x6C) ~= 0
end
-- zero-hook battle chain (docs/gen4/research/battle_pointer.md)
local function battle()
  local f = fsys(); if not f then return nil end
  local sub0 = r32(f); if not inram(sub0) then return nil end
  local man = r32(sub0 + 4); if not inram(man) then return nil end
  if r32(man + 0x0C) ~= OVY_BATTLE then return nil end
  local bs = r32(man + 0x1C); if not inram(bs) then return nil end
  local ctx = r32(bs + 0x30); if not inram(ctx) then return nil end
  local mon = ctx + 0x2D40 + 0xC0
  local sp = r16(mon)
  if sp == 0 then return nil end
  return {fs = f, sub0 = sub0, man = man, bs = bs, ctx = ctx, species = sp, level = r8(mon + 0x34),
          hp = s32(mon + 0x4C), maxhp = s32(mon + 0x50), btype = r32(bs + 0x2C),
          pspecies = r16(ctx + 0x2D40), ovy = r32(man + 0x0C)}
end
local function describe(b)
  return string.format("fs=%s sub0=%s man=%s ovy=%d bs=%s ctx=%s battleType=0x%X enemy=%d L%d hp=%d/%d player=%d",
    hex(b.fs), hex(b.sub0), hex(b.man), b.ovy, hex(b.bs), hex(b.ctx), b.btype, b.species, b.level,
    b.hp, b.maxhp, b.pspecies)
end
shot = function(name)
  pcall(function() client.screenshot(LANE .. "/" .. TAG .. "_" .. name .. ".png") end)
end
local function save_state(name)
  joypad.set({}) -- release first: a held button would keep being held inside the state
  local p = LANE .. "/" .. TAG .. "_" .. name .. ".State"
  local ok, e = pcall(function() savestate.save(p) end)
  say("savestate", name, ok and "ok" or ("ERR " .. tostring(e)), p)
  return p
end
local function pos_s(l) return l and string.format("m%d (%d,%d) d%d", l.map, l.x, l.y, l.dir) or "nil" end
-- the coord events the route crossed, for naming a stuck leg (gen4_routes.py records them)
local function near_soft_events(x, y, r)
  local out = {}
  for _, e in ipairs(route.soft_events or {}) do
    if math.abs(e.x - x) <= r and math.abs(e.y - y) <= r then
      out[#out + 1] = string.format("(%d,%d)=%s", e.x, e.y, table.concat(e.scriptIds or {}, "/"))
    end
  end
  return table.concat(out, " ")
end

-- ----- boot: A/Start only -----------------------------------------------------------------
local function boot_to_overworld(maxf)
  local stable = 0
  for f = 1, maxf do
    local fs = fsys()
    if fs and r32(fs + 0x10) == 0 and r32(fs + 0x6C) ~= 0 then stable = stable + 1 else stable = 0 end
    if stable >= 60 then return emu.framecount() end
    if not fs then
      local ph = f % 40
      if ph < 3 then joypad.set({A = true}) elseif ph >= 20 and ph < 23 then joypad.set({Start = true}) end
    end
    emu.frameadvance()
  end
  return nil
end

local boot_frame
local lst = getenv("G4_LOAD_STATE")
if lst and lst ~= "" then
  savestate.load(lst)
  for _ = 1, 120 do emu.frameadvance() end
  if not idle_now() then finish("FAIL", "loaded_state_not_idle", pos_s(loc())) end
  boot_frame = emu.framecount()
  say("loaded state", lst)
else
  boot_frame = boot_to_overworld(4000)
  if not boot_frame then finish("FAIL", "boot_timeout", "fs=" .. hex(r32(FS)), "tm=" .. tostring(taskman())) end
end
local f0 = emu.framecount()
local start = loc()
say("overworld frame", f0, "pos", pos_s(start), "route start m" .. route.start.map ..
  " (" .. route.start.x .. "," .. route.start.y .. ")")
if not (lst and lst ~= "") and route.kind ~= "reload" and (not start or start.map ~= route.start.map or start.x ~= route.start.x
    or start.y ~= route.start.y) then
  finish("FAIL", "start_mismatch", pos_s(start))
end
for _ = 1, 30 do emu.frameadvance() end

-- ----- interruption (a script/cutscene on a coord event): advance with A until idle ----------
local function interrupted(where, done)
  local li = loc()
  say("INTERRUPT field task running at", where, "pos", pos_s(li), "taskman", hex(taskman() or 0),
    "crossed coord events near here:", li and near_soft_events(li.x, li.y, 2) or "")
  local quiet = 0
  for f = 1, 6000 do
    if idle_now() then quiet = quiet + 1 else quiet = 0 end
    if quiet >= 90 then break end
    -- A only while a field task runs: an idle A talks to whatever the player faces (the follower)
    if not idle_now() and f % 24 < 3 then joypad.set({A = true}) end
    if f % 300 == 0 and f <= 2400 then
      say("interrupt f+" .. f, "pos", pos_s(loc()), "taskman", hex(taskman() or 0))
      shot("int" .. f)
    end
    emu.frameadvance()
  end
  for _ = 1, 30 do emu.frameadvance() end
  local l = loc()
  say("resynced", pos_s(l), "idle", tostring(idle_now()))
  if not idle_now() then finish("FAIL", "interrupt_not_cleared", pos_s(l)) end
  local p = save_state("resync")
  finish("RESYNC", string.format("map=%d x=%d y=%d dir=%d done=%d state=%s", l.map, l.x, l.y, l.dir,
    done and 1 or 0, p))
end

-- ----- walking ----------------------------------------------------------------------------
local STEP_TIMEOUT = 150
local DELTA = {Up = {0, -1}, Down = {0, 1}, Left = {-1, 0}, Right = {1, 0}}
local steptimes, cur = {}, loc()
local function wait_stable(n)
  local last, same = nil, 0
  for _ = 1, 600 do
    local l = loc()
    local key = l and (l.x .. "," .. l.y) or "?"
    if key == last and idle_now() then same = same + 1 else same = 0 end
    last = key
    if same >= n then return true end
    emu.frameadvance()
  end
  return false
end

-- errand legs (route.kind == "errand"): a quiet stop that the next leg re-plans from
local function errand_stop(name)
  if not wait_stable(60) then finish("FAIL", "errand_not_stable", name, pos_s(loc())) end
  local l = loc()
  say("errand", name, "stopped at", pos_s(l))
  local p = save_state(name)
  shot(name)
  finish("RESYNC", string.format("map=%d x=%d y=%d dir=%d done=1 state=%s", l.map, l.x, l.y, l.dir, p))
end

-- hold `dir` until the location reads (tx,ty); returns frames used or nil+reason
local function step(dir, tx, ty)
  local before = loc()
  local t0, busy = emu.framecount(), 0
  for _ = 1, STEP_TIMEOUT do
    local l = loc()
    if l and l.x == tx and l.y == ty then
      return emu.framecount() - t0
    end
    local tm = taskman()
    if emu.framecount() - t0 == 40 or emu.framecount() - t0 == 100 then
      local l2 = loc()
      say("slow step", dir, "to", tx, ty, "at", pos_s(l2), "taskman", hex(tm or 0), "f+6C", hex(r32(fsys() + 0x6C)))
      shot("slow" .. (emu.framecount() - t0))
    end
    if tm and tm ~= 0 then
      busy = busy + 1
      if busy >= 20 then return nil, "task" end
    else
      busy = 0
      joypad.set({[dir] = true})
    end
    emu.frameadvance()
  end
  return nil, "timeout", before
end

-- a wild encounter arrives as a field task too: wait for the battle chain, never call it a script
local TASK_POLL = 900
local SETTLE_FRAMES = tonumber(getenv("G4_SETTLE") or "") or Driver.BATTLE_SETTLE_FRAMES
local SPECIES = {[16] = "PIDGEY", [19] = "RATTATA", [161] = "SENTRET"}
local function species_name(id) return SPECIES[id] or ("#" .. tostring(id)) end
local function poll_battle(frames)
  for _ = 1, frames do
    local b = battle()
    if b then return b end
    emu.frameadvance()
  end
  return nil
end
-- savestate + log + RESULT for a wild battle, whichever phase entered it
local function report_battle(b, phase, extra)
  local lb = loc()
  say("BATTLE chain (" .. phase .. ") at frame", emu.framecount(), extra)
  say("chain", describe(b))
  say("player pos at battle", pos_s(lb))
  save_state("battle_start"); shot("battle_start")
  -- let the intro text / send-out settle (heuristic fixed wait; the screenshot confirms the menu)
  for _ = 1, SETTLE_FRAMES do emu.frameadvance() end
  local b2 = battle()
  say("settled after", SETTLE_FRAMES, "frames; chain", b2 and describe(b2) or "GONE")
  save_state("battle_settled"); shot("battle_settled")
  -- report the SETTLED chain: hge fills the enemy level a few frames after the chain appears
  local r = b2 or b
  finish("BATTLE", string.format("phase=%s species=%s(%d) level=%d player=%d map=%d x=%d y=%d %s",
    phase, species_name(r.species), r.species, r.level, r.pspecies,
    lb and lb.map or -1, lb and lb.x or -1, lb and lb.y or -1, extra))
end


-- ----- pack recipes + RAM readers (route.run_from_wild / route.persistence / route.ram) ---------------
-- Same semantics as lua/tests/probe_gen4_hooks.lua M.predicate / M.play_recipe: a leg presses `press`
-- for `hold_frames`, waits `then_wait_frames`, and repeats while `until` is false, at most `max_frames`.
local function rs(a) local ok, v = pcall(r32, a); return ok and v or 0 end
local function until_ok(u)
  local base = rs(u.address)
  local deref = u.deref or {}
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
local function play_leg(leg, name)
  local used, u = 0, leg["until"]
  local function adv(b)
    if used >= leg.max_frames then return false end
    joypad.set(b); emu.frameadvance(); used = used + 1
    return until_ok(u)
  end
  if until_ok(u) then return 0 end
  while used < leg.max_frames do
    local before = used
    for _, st in ipairs(leg.steps) do
      local b = {}
      for _, n in ipairs(st.press) do b[n] = true end
      for _ = 1, st.hold_frames do if adv(b) then joypad.set({}); return used end end
      for _ = 1, st.then_wait_frames do if adv({}) then return used end end
    end
    if used == before and adv({}) then return used end -- wait-only recipe
  end
  joypad.set({})
  say("leg", name, "NOT reached within", used, "frames")
  return nil
end
local function wait_idle(n, maxf)
  local same = 0
  for _ = 1, maxf do
    if idle_now() then same = same + 1 else same = 0 end
    if same >= n then return true end
    emu.frameadvance()
  end
  return false
end

-- a wild encounter on a long walk (route.run_from_wild, the pack recipe): wait for the battle menu
-- like report_battle does, run, wait for the field to come back; the caller re-issues its step
local function run_from_battle(b, where)
  say("ENCOUNTER", where, describe(b), "-> run_from_wild")
  for _ = 1, SETTLE_FRAMES do emu.frameadvance() end
  shot("encounter")
  local used = play_leg(route.run_from_wild, "run_from_wild")
  if not used then finish("FAIL", "run_failed", where, pos_s(loc())) end
  if not wait_idle(90, 1800) then finish("FAIL", "no_idle_after_run", where, pos_s(loc())) end
  say("ran from", species_name(b.species), "in", used, "frames; pos", pos_s(loc()))
end

local RAM = route.ram
-- NOTE: returns TWO values, (array address, array size from its runtime header); a caller that only
-- needs the address may ignore the size, one that snapshots the whole array (pc_snapshot) uses both.
local function array_addr(id)
  local save = r32(RAM.save_ptr)
  if not inram(save) then return nil end
  local h = save + RAM.hdr_off + id * RAM.hdr_size
  if r32(h) ~= id then return nil end
  return save + RAM.dyn_off + r32(h + RAM.hdr_offset_field), r32(h + RAM.hdr_size_field)
end
local function party_state()
  local base = array_addr(RAM.id_party)
  if not base then return nil end
  local n = r32(base + RAM.party.count_off)
  if n > 6 then return nil end
  local pids = {}
  for i = 0, n - 1 do pids[#pids + 1] = r32(base + RAM.party.mons_off + i * RAM.party.size) end
  return {n = n, pids = pids}
end
-- every non-empty box slot (PID word != 0; an empty slot is zeroed by ZeroBoxMonData) + the PCStorage
-- curBox / boxModifiedFlag words when the pack records them (HG does, hge does not: null)
local function box_census()
  local base = array_addr(RAM.id_pc)
  if not base then return nil end
  local c, total, where, dups = RAM.pc, 0, {}, 0
  for b = 0, c.boxes - 1 do
    for sl = 0, c.per_box - 1 do
      local pid = r32(base + c.box_base + b * c.box_stride + sl * c.mon_stride)
      if pid ~= 0 then
        total = total + 1
        if where[pid] then dups = dups + 1 end -- `where` is keyed by PID: a repeated PID would hide a slot
        where[pid] = {b, sl}
      end
    end
  end
  return {total = total, where = where, dups = dups,
    cur = c.cur_box_off ~= J.null and r32(base + c.cur_box_off) or nil,
    mod = c.mod_off ~= J.null and r32(base + c.mod_off) or nil}
end
-- whole SaveArray snapshot (the PC array: size from its runtime header) + word diff that skips the
-- deposited box slot: locates a dirty flag the pack does not record (hge, PCStorage+0x1E004 by source)
local function pc_snapshot()
  local base, size = array_addr(RAM.id_pc)
  if not base or size == 0 or size > 0x40000 then return nil end
  local w = {}
  for i = 0, size // 4 - 1 do w[i + 1] = r32(base + i * 4) end
  return w
end
local function pc_diff(a, b, label, slot_lo, slot_hi)
  if not a or not b then say("PCDIFF", label, "snapshot unreadable"); return end
  local out, total, inside = {}, 0, 0
  for i = 1, math.min(#a, #b) do
    if a[i] ~= b[i] then
      local off = (i - 1) * 4
      if off + 4 > slot_lo and off < slot_hi then inside = inside + 1
      else
        total = total + 1
        if #out < 80 then out[#out + 1] = string.format("%#x:%08x->%08x", off, a[i], b[i]) end
      end
    end
  end
  say("PCDIFF", label, "words", #a, "changed outside the deposited slot:", total, "inside:", inside, table.concat(out, " "))
end
local function save_driver_idle()
  local f = fsys(); if not f then return false end
  local F = RAM.field
  local sub = r32(f + F.sub); if not inram(sub) then return false end
  if r32(f + F.task) ~= 0 or r32(sub + F.launched_app) ~= 0 then return false end
  local drv = r32(f + F.save_driver); if not inram(drv) then return false end
  local data = r32(drv + F.save_driver_data_off); if not inram(data) then return false end
  return r8(data + F.save_state) == 1
end

-- ----- the PC deposit (route.kind == "pc") ---------------------------------------------------------
-- Every step is source-derived (tools/gen4_routes.py PC_BEHAVIOR; pokeheartgold@ad7a3afa):
--   A facing the PC: GetInteractedMetatileScript -> std_pokecenter_pc (scr_seq_0003_010): "booted up
--   the PC" (A) -> "Which PC?" cursor on the first item, SOMEONE or BILL PC (A) -> "Storage System
--   accessed" (A) -> sub-menu cursor on DEPOSIT POKEMON (A) -> ScrCmd_158 0 -> PCBox_LaunchApp
--   (OVY_14, mode 0).
--   OVY_14 (asm/overlay_14.s; overlay manager data = man+0x1C, state int = man->proc_state at man+0x14 (data+0x30 is only the NEXT state), selected cell byte
--   at +0x21): mode 0 starts at state 0x5B (party list, cursor on slot 0: dpad table ov14_021F8A40,
--   Right from node 0 = node 1). A on a party slot selects it (ov14_021F0794 -> [data+0x21] = 0x1E +
--   slot) and parks the cursor on the toolbar's first button (STORE); A there -> state 0xA9 -> 0x5C
--   (last-mon / mail / egg checks) -> ... -> 0x61 (choose box, cursor on the ACTIVE box); A ->
--   0x66..0x6B commits (ov14_021E6318: PCStorage_PlaceMonInBoxFirstEmptySlot + Party_RemoveMon) ->
--   back to 0x5B. Exit: B at 0x5B -> "Continue Box operations?" (state 0x94, YesNo: B = No) -> No ->
--   exit state 0xB3. The script then returns to its menus: B backs out of the sub-menu, B again is
--   SWITCH OFF.
local APP_OVY, ST_LIST, ST_BOX_CHOOSE = 14, 0x5B, 0x61
local trans, last_state = {}, "none"
local function app_info()
  local f = fsys(); if not f then return nil end
  local sub0 = r32(f); if not inram(sub0) then return nil end
  local man = r32(sub0 + 4); if not inram(man) then return nil end
  local data = r32(man + 0x1C)
  local a = {ovy = r32(man + 0x0C)}
  if a.ovy == APP_OVY then a.state = r32(man + 0x14) end -- PCBox_Main dispatches on *state (man->proc_state)
  if a.ovy == APP_OVY and inram(data) then a.sel = r8(data + 0x21) end
  return a
end
local function watch()
  local a = app_info()
  local st = a and a.ovy == APP_OVY and a.state or nil
  if st ~= last_state then
    last_state = st
    if #trans < 120 then trans[#trans + 1] = string.format("f%d:%s", emu.framecount(), st and string.format("%#x", st) or "-") end
  end
  return a
end
local function trace() return table.concat(trans, " ") end
local function pc_witness(spec)
  local w={frame=emu.framecount(),gaps={}}
  local function gap(name) w.gaps[#w.gaps+1]=name end
  local function valid(p,n) return p and inram(p) and (p&3)==0 and p+n<=0x02400000 end
  if not spec then gap("pc_witness_plan_absent"); return w end
  w.schema=spec.schema; w.special_var_id=spec.special_var_id
  local f=r32(RAM.fieldsys)
  if not valid(f,0x20) then gap("fieldsys_absent"); return w end
  w.fieldsys=f
  local task=r32(f+spec.fs_task_off); local seen={}; local env
  -- FieldSysGetAttrAddr takes the script task's environment. A nested task
  -- may be current: follow TaskManager.prev, but require its magic every time.
  for depth=0,7 do
    if not valid(task,0x10) or seen[task] then break end
    seen[task]=true
    local candidate=r32(task+spec.task_env_off)
    if valid(candidate,spec.env_app_args_off+4) and r32(candidate)==spec.env_magic then
      env=candidate; w.script_task=task; w.task_depth=depth; break
    end
    task=r32(task+spec.task_prev_off)
  end
  if env then
    w.environment=env; w.menu_result_address=env+spec.env_result_off
    w.menu_result=r16(w.menu_result_address)
    w.script_args=r32(env+spec.env_app_args_off)
  else gap("script_environment_absent_or_bad_magic") end
  local sub=r32(f+spec.fs_sub_off)
  local man=valid(sub,spec.sub_manager_off+4) and r32(sub+spec.sub_manager_off) or nil
  if not valid(man,0x20) or r32(man+spec.manager_overlay_off)~=APP_OVY then
    gap("storage_app_not_live"); return w
  end
  w.manager=man
  local args=r32(man+spec.manager_args_off)
  if not valid(args,spec.args_mode_off+4) then gap("storage_args_absent"); return w end
  w.args=args; w.launch_mode_address=args+spec.args_mode_off
  w.launch_mode=r32(w.launch_mode_address)
  if env then
    w.script_args_match=w.script_args==args
    if not w.script_args_match then gap("script_and_manager_args_differ") end
  end
  return w
end
local function frames(n, pred)
  for _ = 1, n do
    local a = watch()
    if pred and pred(a) then return true end
    emu.frameadvance()
  end
  return false
end
local function tap(btn, hold, wait, pred)
  for _ = 1, hold do joypad.set({[btn] = true}); watch(); emu.frameadvance() end
  joypad.set({})
  return frames(wait, pred)
end
local function in_state(want) return function(a) return a ~= nil and a.ovy == APP_OVY and a.state == want end end
local function app_gone(a) return not (a and a.ovy == APP_OVY) end
local function hx(v) return v and string.format("%#x", v) or "nil" end

local function face_pc() -- the shared preamble of the deposit and withdraw legs
  local pcr = route.pc
  local l = loc()
  if not l or l.x ~= pcr.stand[1] or l.y ~= pcr.stand[2] then finish("FAIL", "not_at_pc_stand", pos_s(l)) end
  -- turn north in place: the PC tile is a collision tile, so Up only turns. The LIVE facing is the
  -- player's map object (fs+0x40 PlayerAvatar -> +0x30 LocalMapObject -> +0x28 currentFacing, 0 =
  -- north); Location.direction (fs->location) is the last warp/save direction and does NOT follow
  -- movement (the first live run showed d0 after walking Right, so the turn was skipped).
  for _ = 1, 90 do
    if facing() == 0 then break end
    joypad.set({Up = true}); emu.frameadvance()
  end
  joypad.set({})
  if not wait_stable(30) then finish("FAIL", "pc_stand_not_stable", pos_s(loc())) end
  l = loc()
  if facing() ~= 0 then finish("FAIL", "not_facing_pc", pos_s(l), "facing", tostring(facing())) end
end

local function pc_deposit()
  face_pc()
  local p0, b0 = party_state(), box_census()
  if not p0 or not b0 then finish("FAIL", "ram_unreadable", "party", tostring(p0), "boxes", tostring(b0)) end
  local pid = route.synth.new_pid
  say("before: party", p0.n, "pids", table.concat(p0.pids, ","), "boxed", b0.total, "curBox", tostring(b0.cur),
    "modified", hx(b0.mod), "synth pid", pid)
  if p0.n ~= 2 then finish("FAIL", "setup_not_party2", "party", p0.n) end
  if p0.pids[2] ~= pid then finish("FAIL", "setup_not_synth", "slot1 pid", hx(p0.pids[2]), "want", hx(pid)) end
  if b0.where[pid] then finish("FAIL", "clone_already_boxed") end
  shot("pc_facing")
  local snap0 = pc_snapshot()
  say("PC array words", snap0 and #snap0 or "unreadable")

  -- 1. A-mash through the PC script until the OVY_14 manager is up (every A lands on a menu whose
  --    cursor starts on the item we want, see above)
  local launched = false
  for f = 1, 3600 do
    local a = watch()
    if a and a.ovy == APP_OVY then launched = true; break end
    if f % 30 < 3 then joypad.set({A = true}) else joypad.set({}) end
    emu.frameadvance()
    if f % 600 == 0 then say("pc script f+" .. f, "taskman", hex(taskman() or 0)); shot("pcscript" .. f) end
  end
  joypad.set({})
  if not launched then finish("FAIL", "pc_not_launched", "taskman", hex(taskman() or 0), pos_s(loc())) end
  say("PC app up at frame", emu.framecount())
  if not frames(1200, in_state(ST_LIST)) then finish("FAIL", "pc_list_not_reached", trace()) end
  frames(30)
  if not in_state(ST_LIST)(watch()) then finish("FAIL", "pc_list_lost", trace()) end
  shot("pc_list")

  -- 2. select party slot 1 (cursor starts on slot 0; the selected cell lands in [data+0x21])
  local want, picked = 0x1E + 1, false
  for try = 1, 3 do
    tap("Right", 2, 24)
    tap("A", 2, 100)
    local a = watch()
    say("select try", try, "sel", hx(a and a.sel), "state", hx(a and a.state))
    if a and a.sel == want then picked = true; break end
    if a and a.sel == 0x1E then tap("B", 2, 80) end -- slot 0 got selected: cancel it, move again
  end
  if not picked then finish("FAIL", "party_slot_not_selected", trace()) end
  shot("pc_selected")

  -- 3. STORE (toolbar button 0) -> choose-box screen on the active box -> A deposits there
  tap("A", 2, 12)
  if not frames(900, in_state(ST_BOX_CHOOSE)) then finish("FAIL", "store_menu_not_reached", trace()) end
  frames(30)
  shot("pc_choose_box")
  tap("A", 2, 10)
  local committed = false
  for f = 1, 1500 do
    watch()
    if f % 10 == 0 then local p = party_state(); if p and p.n == 1 then committed = true; break end end
    emu.frameadvance()
  end
  if not committed then finish("FAIL", "deposit_not_committed", trace()) end
  frames(600, in_state(ST_LIST))
  frames(30)

  -- 4. verify the deposit by RAM
  local p1, b1 = party_state(), box_census()
  local at = b1 and b1.where[pid]
  say("after: party", p1 and p1.n, "boxed", b1 and b1.total, "clone at", at and (at[1] .. "/" .. at[2]) or "none",
    "curBox", tostring(b1 and b1.cur), "modified", hx(b1 and b1.mod))
  if not (p1 and p1.n == 1 and p1.pids[1] == p0.pids[1] and b1 and b1.total == b0.total + 1 and at) then
    finish("FAIL", "deposit_state_wrong", trace())
  end
  if b1.mod ~= nil and (b1.mod & (1 << at[1])) == 0 then finish("FAIL", "box_modified_flag_not_set", hx(b1.mod), "box", at[1]) end
  local mod_after_deposit = b1.mod
  local slot_lo = RAM.pc.box_base + at[1] * RAM.pc.box_stride + at[2] * RAM.pc.mon_stride
  local snap1 = pc_snapshot()
  pc_diff(snap0, snap1, "before->in_app_after_deposit", slot_lo, slot_lo + RAM.pc.mon_stride)
  save_state("deposited"); shot("deposited")

  -- 5. leave the PC: B (Continue Box operations?) then B (= No) closes the app
  local gone = false
  for _ = 1, 12 do
    if tap("B", 2, 45, app_gone) then gone = true; break end
  end
  if not gone then finish("FAIL", "pc_not_closed", trace()) end
  say("PC app closed at frame", emu.framecount(), "trace", trace())
  -- the script returns to its menus: B backs out of the sub-menu and the PC list (SWITCH OFF)
  local idle = false
  for _ = 1, 60 do
    if wait_idle(90, 90) then idle = true; break end
    tap("B", 2, 30)
  end
  if not idle then finish("FAIL", "pc_script_not_closed", "taskman", hex(taskman() or 0)) end
  shot("pc_off")
  local snap2 = pc_snapshot()
  pc_diff(snap1, snap2, "in_app->after_pc_closed_before_save", slot_lo, slot_lo + RAM.pc.mon_stride)

  -- 6. native SAVE through the pack's persistence legs, then the save driver must be idle again
  for _, name in ipairs({"open_start_menu", "start_menu_cursor_to_save", "start_menu_select_save",
      "save_confirm_until_saved", "close_start_menu"}) do
    local used = play_leg(route.persistence[name], name)
    if not used then finish("FAIL", "save_leg_not_reached", name, pos_s(loc())) end
    say("save leg", name, used, "frames")
  end
  if not wait_idle(60, 900) then finish("FAIL", "save_not_idle", "taskman", hex(taskman() or 0)) end
  if not save_driver_idle() then finish("FAIL", "save_driver_not_idle") end
  local p2, b2 = party_state(), box_census()
  if not (p2 and p2.n == 1 and b2 and b2.total == b0.total + 1 and b2.where[pid]) then finish("FAIL", "state_after_save_wrong") end
  if b2.mod ~= nil and b2.mod ~= 0 then finish("FAIL", "box_modified_flag_not_cleared", hx(b2.mod)) end
  local snap3 = pc_snapshot()
  pc_diff(snap2, snap3, "before_save->after_save", slot_lo, slot_lo + RAM.pc.mon_stride)
  pc_diff(snap0, snap3, "before_deposit->after_save", slot_lo, slot_lo + RAM.pc.mon_stride)
  save_state("saved"); shot("saved")
  finish("PC_DEPOSIT", string.format("party=2->1 box=%d/%d pid=%s modified=%s->%s save_driver=idle %s",
    at[1], at[2], hx(pid), hx(mod_after_deposit), hx(b2.mod), pos_s(loc())))
end

-- ----- the PC withdraw (route.kind == "pc", route.phase == "withdraw") -----------------------------------
-- Sibling of pc_deposit; every input is cited in route.pc.withdraw.steps (tools/gen4_routes.py WITHDRAW_STEPS,
-- pokeheartgold@ad7a3afa, docs/gen4/G2_PRODUCER_PLAN.md "6b CORRECTION 2"). Top menu: Right x1 then A = WITHDRAW
-- POKEMON -> ScrCmd_158 1 (scr_seq_0003.s:821-856, OVY_14 mode 1). Mode 1 starts at state 0x51 with the cursor on
-- box cell 0 (asm/overlay_14.s:11822-11831; mode 0 = the deposit leg starts at 0x5B). A on a box mon = grab + ONE
-- msg_0025 prompt (ov14_021F0418), then state 0x57 commits with NO input (ov14_021EDF28 -> ov14_021E6184 ->
-- Party_AddMon) and returns to 0x51. STATE WORD: man+0x14, exactly as pc_deposit reads it (that read is PHYSICAL on
-- the deposit receipts); the asm calls it sysdata+0 (:11368-11385) -- the live trace in the log settles it.
-- INFERRED, so polled/logged and never blind: the script-menu settle windows (no RAM signal for a script menu), the
-- 0x57 -> 0x51 edge, and B at 0x51 reaching the exit YesNo. Precondition: a party with room (the 6/6 path is unverified).
local ST_GRID = 0x51
local function box_slot_pid(box, slot)
  local base = array_addr(RAM.id_pc)
  local c = RAM.pc
  return base and r32(base + c.box_base + box * c.box_stride + slot * c.mon_stride) or nil
end
local function app_input_state(a)
  return a ~= nil and a.ovy == APP_OVY and (a.state == ST_GRID or a.state == ST_LIST)
end
local function withdrawn_ok(p0, b0, pid, home, label)
  local p1, b1 = party_state(), box_census()
  local ok = p1 ~= nil and b1 ~= nil and p1.n == p0.n + 1 and p1.pids[p1.n] == pid and b1.total == b0.total - 1
    and not b1.where[pid] and b1.dups == 0 and box_slot_pid(home[1], home[2]) == 0
  for i = 1, p0.n do if not (p1 and p1.pids[i] == p0.pids[i]) then ok = false end end
  say(label, "party", p1 and p1.n, "pids", p1 and table.concat(p1.pids, ","), "boxed", b1 and b1.total,
    "slot pid", hx(box_slot_pid(home[1], home[2])), "curBox", tostring(b1 and b1.cur), "modified", hx(b1 and b1.mod))
  return ok, p1, b1
end
local function pc_withdraw()
  local wd = route.pc.withdraw
  local last_launch
  local function witness(when,status,attempt)
    local w=pc_witness(wd.witness); w.when=when; w.status=status; w.attempt=attempt
    if when=="terminal" then w.last_launch=last_launch end
    say("PC_WITNESS",assert(J.encode(w)))
    if when=="launch" then last_launch=w end
  end
  terminal_witness=function(status) witness("terminal",status) end
  -- one diagnostic line per script press (never per frame): the live trace that settles the press count
  local npress = 0
  local function pressed(label)
    npress = npress + 1
    local ai = app_info()
    witness("press",label)
    say("press", npress, label, "taskman", hex(taskman() or 0), "ovy", ai and ai.ovy or "-", "state",
      ai and ai.state and hx(ai.state) or "-")
  end
  -- never press into an app that came up late: a direction would move the box cursor, an A would grab
  local function no_app(where)
    if not app_gone(watch()) then finish("FAIL", "pc_late_launch", where, trace()) end
  end
  face_pc()
  local p0, b0 = party_state(), box_census()
  if not p0 or not b0 then finish("FAIL", "ram_unreadable", "party", tostring(p0), "boxes", tostring(b0)) end
  local pid = route.synth.new_pid
  local home = b0.where[pid]
  say("before: party", p0.n, "pids", table.concat(p0.pids, ","), "boxed", b0.total, "curBox", tostring(b0.cur),
    "modified", hx(b0.mod), "synth pid", pid)
  if b0.dups > 0 then finish("FAIL", "setup_duplicate_pid", "boxed twice:", b0.dups) end -- `where` is keyed by PID
  if p0.n > wd.party_max then finish("FAIL", "withdraw_party_full", "party", p0.n) end
  if not home or home[1] ~= (b0.cur or 0) or home[2] ~= wd.box_cell then
    finish("FAIL", "setup_not_in_cell", "clone at", home and (home[1] .. "/" .. home[2]) or "none", "curBox", tostring(b0.cur))
  end
  for _, v in ipairs(p0.pids) do
    if v == pid then finish("FAIL", "setup_clone_in_party") end
    if b0.where[v] then finish("FAIL", "setup_duplicate_pid", "party pid also boxed", hx(v)) end
  end
  -- the dirty mask is judged as a CLEAR -> SET edge on the source box's bit (a bit already set proves nothing)
  if b0.mod ~= nil and (b0.mod & (1 << home[1])) ~= 0 then finish("FAIL", "setup_dirty_bit_already_set", hx(b0.mod), "box", home[1]) end
  shot("pc_facing")

  -- 1. interact (A on the PC tile), then the two script menus by BUTTONS ONLY
  local started = false
  for try = 1, 4 do
    tap("A", 3, 60)
    pressed("A interact")
    if (taskman() or 0) ~= 0 then started = true; break end
  end
  if not started then finish("FAIL", "pc_script_not_started", pos_s(loc())) end
  -- Three semantic A: msg33 \r -> storage-PC row0 -> msg35 \r. A during
  -- printing is NOT also a menu press (render_text.c:95-105). Waits the existing
  -- 900-frame bound before each semantic A; do not add A-mash that could
  -- launch DEPOSIT before the menu direction. Count/recovery remain plan parameters.
  for i = 1, wd.script_a do
    frames(wd.script_wait)
    tap("A", 3, wd.a_period); pressed("A script " .. i)
  end
  -- 2. the sub-menu: Right x menu_steps (DEPOSIT -> WITHDRAW POKEMON, scr_seq_0003.s:821-846) then A (-> ScrCmd_158 1,
  --    :851-856). The launch MODE is the RAM signal that it landed: state 0x51 = withdraw, 0x5B = the DEPOSIT row;
  --    nothing launched = the script was one press behind. Either way retry Right+A from the sub-menu (INFERRED
  --    that the script re-offers its sub-menu after the app closes, as the deposit leg's exit relies on).
  local a
  local why = "pc_menu_not_attempted" -- never nil in finish(): set before the loop, overwritten per failure
  for attempt = 1, wd.menu_attempts do
    if attempt > 1 then
      say("withdraw menu attempt", attempt, "after", why, trace())
      frames(wd.a_period) -- a late launch from the last attempt shows up here, before any press
    end
    no_app("before the menu direction")
    -- Opcode752's ov27 grid: index0 Right=1 WITHDRAW; Down=2 MOVE.
    -- overlay_27.s ov27_0225CA68 and ov27_0225D174/D1B4 neighbor tables.
    for _ = 1, wd.menu_steps do tap(wd.menu_key, wd.menu_hold, 30); pressed(wd.menu_key) end
    shot("pc_menu_withdraw" .. attempt)
    no_app("before the sub-menu A")
    tap("A", 3, 10)
    pressed("A submenu")
    local launched = false
    for f = 1, wd.launch_wait do
      local x = watch()
      if x and x.ovy == APP_OVY then launched = true; break end
      emu.frameadvance()
    end
    if not launched then
      why = "pc_not_launched"
    else
      say("PC app up at frame", emu.framecount(), "attempt", attempt)
      witness("launch",nil,attempt)
      -- 3. the box grid: mode 1 = state 0x51, cursor on cell 0
      if not frames(1200, app_input_state) then finish("FAIL", "pc_input_state_not_reached", trace()) end
      frames(30)
      a = watch()
      if a and a.state == ST_GRID then break end
      why = "pc_wrong_mode"
      say("launched in the wrong mode: state", hx(a and a.state))
      a = nil
      if attempt < wd.menu_attempts then -- leave the app exactly as the deposit leg does, then the sub-menu is back
        local gone = false
        for _ = 1, 12 do if tap("B", 2, 45, app_gone) then gone = true; break end end
        if not gone then finish("FAIL", "pc_not_closed", trace()) end
        frames(wd.a_period)
        for i = 1, wd.recover_a do tap("A", 3, wd.a_period); pressed("A recover " .. i) end
      end
    end
  end
  if not a then finish("FAIL", why, "taskman", hex(taskman() or 0), pos_s(loc()), trace()) end
  if a.sel ~= wd.box_cell then finish("FAIL", "cursor_not_on_cell", "sel", hx(a.sel), "want", wd.box_cell, trace()) end
  shot("pc_grid")

  -- 4. A = grab + one prompt; state 0x57 commits with no further input: poll the party count
  tap("A", 2, 6)
  local committed = false
  for f = 1, 1500 do
    watch()
    if f % 10 == 0 then local p = party_state(); if p and p.n == p0.n + 1 then committed = true; break end end
    emu.frameadvance()
  end
  say("grab trace", trace())
  if not committed then finish("FAIL", "withdraw_not_committed", trace()) end
  say("state 0x57 sampled:", tostring(trace():find(":0x57", 1, true) ~= nil))
  if not frames(600, in_state(ST_GRID)) then say("INFERRED edge 0x57 -> 0x51 not seen in 600 frames", trace()) end
  frames(30)

  -- 5. verify by RAM: +1 party (appended, the rest unmoved), box slot empty, dirty MASK has the source box's bit
  local ok, p1, b1 = withdrawn_ok(p0, b0, pid, home, "after:")
  if not ok then finish("FAIL", "withdraw_state_wrong", trace()) end
  local mod_after = b1.mod
  if mod_after ~= nil and (mod_after & (1 << home[1])) == 0 then
    finish("FAIL", "box_modified_flag_not_set", hx(mod_after), "box", home[1])
  end
  save_state("withdrawn"); shot("withdrawn")

  -- 6. leave the PC exactly as the deposit leg does (B until the overlay is gone; B backs out of the script menus)
  local gone = false
  for _ = 1, 12 do
    if tap("B", 2, 45, app_gone) then gone = true; break end
  end
  if not gone then finish("FAIL", "pc_not_closed", trace()) end
  say("PC app closed at frame", emu.framecount(), "trace", trace())
  local idle = false
  for _ = 1, 60 do
    if wait_idle(90, 90) then idle = true; break end
    tap("B", 2, 30)
  end
  if not idle then finish("FAIL", "pc_script_not_closed", "taskman", hex(taskman() or 0)) end
  shot("pc_off")

  -- 7. native SAVE through the pack's persistence legs, then the save driver must be idle again
  for _, name in ipairs({"open_start_menu", "start_menu_cursor_to_save", "start_menu_select_save",
      "save_confirm_until_saved", "close_start_menu"}) do
    local used = play_leg(route.persistence[name], name)
    if not used then finish("FAIL", "save_leg_not_reached", name, pos_s(loc())) end
    say("save leg", name, used, "frames")
  end
  if not wait_idle(60, 900) then finish("FAIL", "save_not_idle", "taskman", hex(taskman() or 0)) end
  if not save_driver_idle() then finish("FAIL", "save_driver_not_idle") end
  local ok2, _, b2 = withdrawn_ok(p0, b0, pid, home, "after save:")
  if not ok2 then finish("FAIL", "state_after_save_wrong") end
  if b2.mod ~= nil and b2.mod ~= 0 then finish("FAIL", "box_modified_flag_not_cleared", hx(b2.mod)) end
  save_state("saved"); shot("saved")
  finish("PC_WITHDRAW", string.format("party_before=%d party_after=%d box=%d/%d slot_after=empty pid=%s " ..
    "mod_before=%s mod_after=%s mod_saved=%s save_driver=idle %s", p0.n, p1.n, home[1], home[2], hx(pid),
    hx(b0.mod), hx(mod_after), hx(b2.mod), pos_s(loc())))
end

-- ----- egg hatch (route.kind == "hatch": SYNTH egg1 in party slot 1) -------------------------------
-- The game does everything: tools/gen4_routes.py plan_hatch picks a plain-floor neighbour (no grass, no
-- coord event, no warp); this leg paces between the two tiles with the D-pad. Every 255 steps
-- HandleDaycareStep (src/get_egg.c:763-809) subtracts egg cycles; an egg at 0 cycles hatches at the next
-- boundary: a field task runs HatchEggInParty -> sub_0206D328 (hge: replaced) -> the OVY_95 hatch app ->
-- (nickname Yes/No, B = No) -> overworld. Oracle: the party decoded by lua/gen4/reads.lua + pk4.lua.
local function denull(t)
  if type(t) ~= "table" then return t end
  local out = {}
  for k, v in pairs(t) do if v ~= J.null then out[k] = denull(v) end end
  return out
end
local Reads
local function party_mons()
  if not Reads then
    Reads = dofile(REPO .. "/lua/gen4/reads.lua")
    Reads.pk4 = dofile(REPO .. "/lua/gen4/pk4.lua")
    Reads.pk4.crypto = dofile(REPO .. "/lua/nds/pkm45_crypto.lua")
    route.profile = denull(route.profile) -- JSON null decodes to a table: pk4_profile would read it as present
  end
  return Reads.party({u8 = r8, u16 = r16, u32 = r32}, route.profile)
end
local function mon_s(m)
  local d = m.decoded
  return string.format("slot%d key=%s species=%d egg=%s level=%s friendship=%d has_nick=%s ability=%s hidden=%s " ..
    "met_level=%d met_loc=%d egg_loc=%d origin=%s ball=%s ivs=%s", m.slot, m.key, d.species, tostring(d.is_egg),
    tostring(d.level), d.friendship, tostring(d.has_nickname), tostring(d.ability), tostring(d.hidden_ability),
    d.met_level, d.met_location, d.egg_location, tostring(d.origin_game), tostring(d.ball), table.concat(d.ivs, "/"))
end
local function egg_key() return string.format("%08X:%08X", route.synth.new_pid, route.synth.otid) end
local function hatch_oracle(label, want_egg)
  local mons, why = party_mons()
  if not mons then finish("FAIL", "party_unreadable", label, tostring(why)) end
  local m = mons[2]
  say("ORACLE", label, "party", #mons, m and mon_s(m) or "no slot 1")
  if #mons ~= 2 or not m or m.key ~= egg_key() then finish("FAIL", "hatch_party_wrong", label, #mons) end
  if m.decoded.is_egg ~= want_egg then finish("FAIL", "hatch_egg_flag_wrong", label, tostring(m.decoded.is_egg)) end
  if m.decoded.species ~= route.synth.species then finish("FAIL", "hatch_species_changed", label, m.decoded.species) end
  return m
end

local function hatch_leg()
  local pc = route.pace
  local egg = hatch_oracle("before", true)
  if egg.decoded.friendship ~= 0 then finish("FAIL", "egg_cycles_not_zero", egg.decoded.friendship) end
  local l = loc()
  if not l or l.x ~= pc.a[1] or l.y ~= pc.a[2] then finish("FAIL", "not_on_pace_tile", pos_s(l)) end
  shot("hatch_start")
  local n, at_a, scene, f0 = 0, true, false, emu.framecount()
  while n < pc.max_steps do
    local tgt = at_a and pc.b or pc.a
    local fr, why = step(at_a and pc.dir_ab or pc.dir_ba, tgt[1], tgt[2])
    if not fr then
      if why == "task" then scene = true; break end
      finish("FAIL", "pace_step_failed", tostring(why), pos_s(loc()))
    end
    n = n + 1; at_a = not at_a
  end
  if not scene then finish("FAIL", "no_hatch", n, "steps", pos_s(loc())) end
  say("HATCH scene started after", n, "completed steps, frames", emu.framecount() - f0, "pos", pos_s(loc()),
    "taskman", hex(taskman() or 0))
  shot("hatch_scene")
  -- advance the dialogue with normal input: B first (it also answers the nickname prompt No); if the
  -- scene is still up after 1800 frames, A-mash
  local mode, idle_run, ovy_trace, last_ovy = "B", 0, {}, "x"
  for f = 1, 9000 do
    local a = app_info()
    local ov = a and a.ovy or -1
    if ov ~= last_ovy then
      last_ovy = ov
      if #ovy_trace < 60 then ovy_trace[#ovy_trace + 1] = string.format("f%d:ovy%d", f, ov) end
    end
    if f % 24 < 3 then joypad.set({[mode] = true}) else joypad.set({}) end
    emu.frameadvance()
    if idle_now() then idle_run = idle_run + 1 else idle_run = 0 end
    if idle_run >= 120 then break end
    if f == 1800 then mode = "A"; say("B did not finish the scene; A-mash from frame", emu.framecount()) end
    if f % 600 == 0 then shot("hatch_f" .. f); say("hatch scene f+" .. f, "ovy", ov, "taskman", hex(taskman() or 0)) end
  end
  joypad.set({})
  say("hatch scene ended; overlays:", table.concat(ovy_trace, " "), "mode", mode)
  if not idle_now() then finish("FAIL", "hatch_scene_not_finished", table.concat(ovy_trace, " ")) end
  wait_stable(30)
  local m = hatch_oracle("after_hatch", false)
  save_state("hatched"); shot("hatched")
  -- native SAVE, then the oracle again
  for _, name in ipairs({"open_start_menu", "start_menu_cursor_to_save", "start_menu_select_save",
      "save_confirm_until_saved", "close_start_menu"}) do
    local used = play_leg(route.persistence[name], name)
    if not used then finish("FAIL", "save_leg_not_reached", name, pos_s(loc())) end
    say("save leg", name, used, "frames")
  end
  if not wait_idle(60, 900) then finish("FAIL", "save_not_idle", "taskman", hex(taskman() or 0)) end
  if not save_driver_idle() then finish("FAIL", "save_driver_not_idle") end
  hatch_oracle("after_save", false)
  save_state("saved"); shot("saved")
  finish("HATCH_OK", string.format("steps=%d key=%s species=%d level=%s met_level=%d met_loc=%d hidden=%s ability=%s save_driver=idle %s",
    n, m.key, m.decoded.species, tostring(m.decoded.level), m.decoded.met_level, m.decoded.met_location,
    tostring(m.decoded.hidden_ability), tostring(m.decoded.ability), pos_s(loc())))
end

-- ----- cold reload (route.kind == "reload"): a FRESH boot from the battery the PC leg saved ------------
-- No savestate: CONTINUE through the title as in leg 1, then confirm by RAM that the deposit persisted.
local function reload_check()
  if route.synth.kind == "egg1" then -- the hatched mon must have persisted through SAVE + a fresh boot
    local m = hatch_oracle("cold_reload", false)
    finish("RELOAD_OK", string.format("party=2 key=%s species=%d level=%s hidden=%s", m.key, m.decoded.species,
      tostring(m.decoded.level), tostring(m.decoded.hidden_ability)))
  end
  local p, b = party_state(), box_census()
  if not p or not b then finish("FAIL", "reload_ram_unreadable") end
  local pid = route.synth.new_pid
  local at = b.where[pid]
  say("reloaded: party", p.n, "pids", table.concat(p.pids, ","), "boxed", b.total, "clone at",
    at and (at[1] .. "/" .. at[2]) or "none", "curBox", tostring(b.cur), "modified", b.mod and string.format("%#x", b.mod) or "nil")
  if route.op == "withdraw" then -- the withdrawn mon must have persisted in the PARTY (appended) and left the box
    if p.n < 2 then finish("FAIL", "reload_party_count", p.n) end
    if p.pids[p.n] ~= pid then finish("FAIL", "reload_clone_not_in_party", hx(p.pids[p.n])) end
    if at then finish("FAIL", "reload_clone_still_boxed", at[1] .. "/" .. at[2]) end
    if b.mod ~= nil and b.mod ~= 0 then finish("FAIL", "reload_modified_flag_set", b.mod) end
    finish("RELOAD_OK", string.format("party=%d clone_slot=%d boxed=%d pid=%#x", p.n, p.n, b.total, pid))
  end
  if p.n ~= 1 then finish("FAIL", "reload_party_count", p.n) end
  if not at then finish("FAIL", "reload_clone_not_boxed") end
  if p.pids[1] == pid then finish("FAIL", "reload_clone_in_party") end
  if b.mod ~= nil and b.mod ~= 0 then finish("FAIL", "reload_modified_flag_set", b.mod) end
  finish("RELOAD_OK", string.format("party=1 box=%d/%d pid=%#x boxed=%d", at[1], at[2], pid, b.total))
end

local total, edge_done = 0, false
local steps = route.steps
local edge_after = route.grass_edge_after_step
if edge_after == J.null then edge_after = nil end
for i = 1, #steps do
  local s = steps[i]
  local d = DELTA[s.dir]
  for k = 1, s.n do
    local tx, ty = cur.x + d[1], cur.y + d[2]
    if s.warp then
      -- a door: hold the direction until the warp task starts, release, wait for the new map
      local m0, ok = cur.map, false
      for _ = 1, 600 do
        local l, tm = loc(), taskman()
        if l and l.map == s.to.map and idle_now() then ok = true; break end
        if (tm and tm ~= 0) or (l and l.map ~= m0) then joypad.set({}) else joypad.set({[s.dir] = true}) end
        emu.frameadvance()
      end
      joypad.set({})
      if not ok then finish("FAIL", "warp_timeout", string.format("seg%d toward map %d", i, s.to.map), pos_s(loc())) end
      say("warped", pos_s(loc()))
      errand_stop(route.phase)
    end
    local fr, why, before = step(s.dir, tx, ty)
    local polled = false
    -- a long walk that must not fight (route.run_from_wild): an encounter is escaped with the pack
    -- recipe and the same step is re-issued (it returns at once when the tile was already reached)
    for _ = 1, 8 do
      if fr or why ~= "task" or not route.run_from_wild then break end
      local bb = poll_battle(TASK_POLL)
      if not bb then polled = true; break end
      run_from_battle(bb, string.format("seg%d step%d", i, k))
      fr, why, before = step(s.dir, tx, ty)
    end
    if not fr then
      if why == "task" then
        -- the approach can cross grass (route.approach_grass): a field task here may be an
        -- encounter, so poll the battle chain before treating it as a script
        local bb = not polled and poll_battle(TASK_POLL) or nil
        if bb then report_battle(bb, "approach", string.format("approachTiles=%d", total)) end
        interrupted(string.format("seg%d step%d toward (%d,%d)", i, k, tx, ty))
      end
      finish("FAIL", "diverged", string.format("seg%d step%d dir=%s wanted (%d,%d) m%s; at %s; was %s",
        i, k, s.dir, tx, ty, tostring(s.to.map), pos_s(loc()), pos_s(before)))
    end
    cur = loc()
    total = total + 1
    steptimes[#steptimes + 1] = fr
    if #steptimes <= 6 then say("step", total, s.dir, "->", pos_s(cur), "frames", fr) end
  end
  local l = loc()
  say(string.format("checkpoint seg%d/%d %s x%d at %s (want m%s (%d,%d))", i, #steps, s.dir, s.n,
    pos_s(l), tostring(s.to.map), s.to.x, s.to.y))
  if l.x ~= s.to.x or l.y ~= s.to.y or l.map ~= s.to.map then
    -- tile reached but map id differs (id flips at the cell boundary): tolerate one settle window
    for _ = 1, 20 do emu.frameadvance() end
    l = loc()
    if l.x ~= s.to.x or l.y ~= s.to.y or l.map ~= s.to.map then
      finish("FAIL", "checkpoint_mismatch", string.format("seg%d at %s want m%d (%d,%d)", i, pos_s(l),
        s.to.map, s.to.x, s.to.y))
    end
  end
  if edge_after == i - 1 then -- Lua index = JSON index + 1
    if not wait_stable(30) then finish("FAIL", "edge_not_stable", pos_s(loc())) end
    say("GRASS EDGE", pos_s(loc()))
    save_state("grass_edge"); shot("grass_edge")
    edge_done = true
  end
  cur = loc()
end
if route.kind == "reload" then reload_check() end
if route.kind == "hatch" then hatch_leg() end
if route.kind == "pc" then -- ends in finish(): PC_DEPOSIT / PC_WITHDRAW or FAIL
  if route.phase == "withdraw" then pc_withdraw() else pc_deposit() end
end
if route.kind == "errand" then -- only `talk` reaches here: face the NPC, A through the dialogue
  local want = {Up = 0, Down = 1, Left = 2, Right = 3}
  local face = route.talk.face
  for _ = 1, 60 do
    local l = loc()
    if l and l.dir == want[face] then break end
    joypad.set({[face] = true})
    emu.frameadvance()
  end
  joypad.set({})
  for _ = 1, 20 do emu.frameadvance() end
  shot("talk_pre")
  -- A until the dialogue task starts (a press in the turn frames is swallowed)
  for try = 1, 6 do
    for _ = 1, 4 do joypad.set({A = true}); emu.frameadvance() end -- set per frame: it lasts one
    joypad.set({})
    for _ = 1, 30 do emu.frameadvance() end
    local tm = taskman()
    say("talk A try", try, "taskman", hex(tm or 0), "pos", pos_s(loc()))
    if tm and tm ~= 0 then break end
  end
  shot("talk_post")
  interrupted("talk to NPC " .. face, true)
end
if edge_after == nil and not edge_done then
  wait_stable(30); say("grass edge = start", pos_s(loc())); save_state("grass_edge"); shot("grass_edge")
end
local sum = 0
for _, v in ipairs(steptimes) do sum = sum + v end
say(string.format("route walked: %d tiles, avg %.1f frames/tile, frames since overworld %d", total,
  #steptimes > 0 and sum / #steptimes or 0, emu.framecount() - f0))
if #(route.approach_grass or {}) > 0 then
  local ag = {}
  for _, t in ipairs(route.approach_grass) do ag[#ag + 1] = t[1] .. "," .. t[2] end
  say("approach crossed grass at", table.concat(ag, " "), "-- an encounter there ends this leg as BATTLE")
end

-- ----- pace in the grass until a wild battle ------------------------------------------------
local pace = route.grass.pace
local A, B = pace.a, pace.b
if not wait_stable(20) then finish("FAIL", "grass_not_stable", pos_s(loc())) end
local l = loc()
if l.x ~= A[1] or l.y ~= A[2] then finish("FAIL", "not_on_pace_tile", pos_s(l)) end
say("pacing", pos_s(l), "between", A[1] .. "," .. A[2], "and", B[1] .. "," .. B[2])
local pace_max = tonumber(getenv("G4_PACE_MAX") or "") or pace.max_steps
local grass_f0 = emu.framecount()
local found
local n = 0
local at_a = true
while n < pace_max and not found do
  local dir = at_a and pace.dir_ab or pace.dir_ba
  local tgt = at_a and B or A
  local d = DELTA[dir]
  -- hold the direction until the tile changes, a battle appears, or a task starts (encounter)
  local t0 = emu.framecount()
  local moved = false
  for _ = 1, STEP_TIMEOUT do
    found = battle()
    if found then break end
    local li = loc()
    if li and li.x == tgt[1] and li.y == tgt[2] then moved = true; break end
    local tm = taskman()
    if tm and tm ~= 0 then
      -- an encounter transition is a field task: wait for the battle chain, not a script
      found = poll_battle(TASK_POLL)
      if not found then
        finish("FAIL", "task_without_battle", pos_s(loc()), "taskman", hex(taskman() or 0))
      end
      break
    end
    joypad.set({[dir] = true})
    emu.frameadvance()
  end
  if found then break end
  if not moved then finish("FAIL", "pace_step_timeout", pos_s(loc())) end
  n = n + 1
  at_a = not at_a
end
if not found then
  finish("FAIL", "no_encounter", string.format("%d pace steps, frames %d", n, emu.framecount() - grass_f0))
end
report_battle(found, "pace", string.format("paceSteps=%d framesInGrass=%d", n, emu.framecount() - grass_f0))
end
if SLINK_GEN4_ROUTE_LIBRARY then return Driver end
return Driver.run(nil)
