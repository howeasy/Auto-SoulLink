-- Gen 4 (HGSS) scripted route walk: CONTINUE (A/Start only) -> walk tools/gen4_routes.py's route
-- with normal button input, position verified from RAM per tile -> pace in grass -> wild battle ->
-- savestates. NO writes to game memory; reads only. One buffered log, no per-frame console.log.
--
-- env: G4_REPO (repo root), G4_ROUTE (route.json), G4_OUT (log path), G4_LANE (state dir),
--      G4_TAG (state name prefix), optional G4_LOAD_STATE (resume a resync state instead of booting),
--      G4_PACE_MAX (max pace steps, default route's), G4_SETTLE (frames to wait after battle start).
-- exit status is the LAST log line `RESULT <status> ...` (BATTLE | RESYNC | FAIL <why>).
local BUS = "ARM9 System Bus"
local FS, SAVEPTR = 0x021D4158, 0x021D2228
local OVY_BATTLE = 12
local REPO, OUT, LANE = os.getenv("G4_REPO"), os.getenv("G4_OUT"), os.getenv("G4_LANE")
local TAG = os.getenv("G4_TAG") or "route"
local lines = {}
local function say(...)
  local t = {}
  for i = 1, select("#", ...) do t[#t + 1] = tostring(select(i, ...)) end
  lines[#lines + 1] = string.format("[f%d] %s", emu.framecount(), table.concat(t, " "))
end
local function flush()
  local f = io.open(OUT, "w")
  if f then f:write(table.concat(lines, "\n"), "\n"); f:close() end
end
local shot -- defined below; a FAIL leaves a screenshot of the runtime state
local function finish(status, ...)
  if status == "FAIL" and shot then shot("fail") end
  say("RESULT", status, ...)
  flush()
  pcall(function() client.exit() end)
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
local fh = assert(io.open(os.getenv("G4_ROUTE"), "rb"))
local route, jerr = J.decode(fh:read("*a"), {bytes = 8 * 1024 * 1024}); fh:close()
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
  local p = LANE .. "/" .. TAG .. "_" .. name .. ".State"
  local ok, e = pcall(function() savestate.save(p) end)
  say("savestate", name, ok and "ok" or ("ERR " .. tostring(e)), p)
  return p
end
local function pos_s(l) return l and string.format("m%d (%d,%d) d%d", l.map, l.x, l.y, l.dir) or "nil" end

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
local lst = os.getenv("G4_LOAD_STATE")
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
if not (lst and lst ~= "") and (not start or start.map ~= route.start.map or start.x ~= route.start.x
    or start.y ~= route.start.y) then
  finish("FAIL", "start_mismatch", pos_s(start))
end
for _ = 1, 30 do emu.frameadvance() end

-- ----- interruption (a script/cutscene on a coord event): advance with A until idle ----------
local function interrupted(where)
  say("INTERRUPT field task running at", where, "pos", pos_s(loc()), "taskman", hex(taskman() or 0))
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
  finish("RESYNC", string.format("map=%d x=%d y=%d dir=%d state=%s", l.map, l.x, l.y, l.dir, p))
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

-- hold `dir` until the location reads (tx,ty); returns frames used or nil+reason
local function step(dir, tx, ty, tmap)
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

local total, edge_done = 0, false
local steps = route.steps
local edge_after = route.grass_edge_after_step
if edge_after == J.null then edge_after = nil end
for i = 1, #steps do
  local s = steps[i]
  local d = DELTA[s.dir]
  for k = 1, s.n do
    local tx, ty = cur.x + d[1], cur.y + d[2]
    local fr, why, before = step(s.dir, tx, ty, s.to.map)
    if not fr then
      if why == "task" then interrupted(string.format("seg%d step%d toward (%d,%d)", i, k, tx, ty)) end
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
if edge_after == nil and not edge_done then
  wait_stable(30); say("grass edge = start", pos_s(loc())); save_state("grass_edge"); shot("grass_edge")
end
local sum = 0
for _, v in ipairs(steptimes) do sum = sum + v end
say(string.format("route walked: %d tiles, avg %.1f frames/tile, frames since overworld %d", total,
  #steptimes > 0 and sum / #steptimes or 0, emu.framecount() - f0))

-- ----- pace in the grass until a wild battle ------------------------------------------------
local pace = route.grass.pace
local A, B = pace.a, pace.b
if not wait_stable(20) then finish("FAIL", "grass_not_stable", pos_s(loc())) end
local l = loc()
if l.x ~= A[1] or l.y ~= A[2] then finish("FAIL", "not_on_pace_tile", pos_s(l)) end
say("pacing", pos_s(l), "between", A[1] .. "," .. A[2], "and", B[1] .. "," .. B[2])
local pace_max = tonumber(os.getenv("G4_PACE_MAX") or "") or pace.max_steps
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
      for _ = 1, 900 do
        found = battle()
        if found then break end
        emu.frameadvance()
      end
      if not found then finish("FAIL", "task_without_battle", pos_s(loc()), "taskman", hex(taskman() or 0)) end
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
local b = found
local lb = loc()
local grass_frames = emu.framecount() - grass_f0
say("BATTLE chain at frame", emu.framecount(), "pace steps", n, "frames in grass", grass_frames)
say("chain", describe(b))
say("player pos at battle", pos_s(lb))
save_state("battle_start"); shot("battle_start")
-- let the intro text / send-out settle (heuristic fixed wait; the screenshot confirms the menu)
local settle = tonumber(os.getenv("G4_SETTLE") or "") or 900
for _ = 1, settle do emu.frameadvance() end
local b2 = battle()
say("settled after", settle, "frames; chain", b2 and describe(b2) or "GONE")
save_state("battle_settled"); shot("battle_settled")
finish("BATTLE", string.format("species=%d level=%d map=%d x=%d y=%d paceSteps=%d framesInGrass=%d",
  b.species, b.level, lb and lb.map or -1, lb and lb.x or -1, lb and lb.y or -1, n, grass_frames))
