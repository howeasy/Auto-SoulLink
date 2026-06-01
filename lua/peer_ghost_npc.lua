-- peer_ghost_npc.lua — engine-driven peer ghost (Gen 3 Radical Red, companion-patch path).
--
-- The partner is shown as a REAL engine object-event. The companion patch's frame hook
-- (drive_ghost in handlers.c) spawns it once and WALKS it toward a target tile each frame using the
-- engine's native held-movement API — so the engine owns animation, sub-pixel motion, palette,
-- day/night tint, off-screen culling, and collision. We no longer puppet sprite memory from Lua.
--
-- This receiver's whole job: when the partner is on the SAME map as the local player, request the
-- ghost once and post the partner's target tile + facing + gfx into the shared GhostState each tick;
-- when they're not, clear it. The patch owns the spawn/despawn/map-change/gfx-change lifecycle.
--
-- Feed it the partner's state via on_ghost_pos{mg,mn,x,y,f,mv,run,gfx} where x,y are TILE coords
-- (object-event currentCoords space). Requires the patch (mailbox); no-ops gracefully without.

local ok_mb, MB = pcall(require, "mailbox")
if not ok_mb then MB = nil end

local PG = {}
local OE = 0x02036E38          -- gObjectEvents[0] = the local player
local interact_text = "Your partner is here!"   -- shown when YOU press A on the ghost
local S

function PG.init() S = { ghost = nil, spawned = false, pi_last = 0, interact_pending = false } end
function PG.present() return MB ~= nil and MB.present() end
function PG.set_interact_text(s) if s and s ~= "" then interact_text = s end end

-- partner state update; x,y are TILE coords (not world pixels — the engine interpolates now)
function PG.on_ghost_pos(t) if S then S.ghost = t end end

function PG.on_ghost_clear()
  if not S then return end
  S.ghost = nil
  if S.spawned and MB then MB.ghost_clear() end
  S.spawned = false
end

-- True once per detected talk-to-ghost (the client emits a peer_interact event to the server).
function PG.consume_interact()
  if S and S.interact_pending then S.interact_pending = false; return true end
  return false
end

function PG.on_frame()
  if not PG.present() then return end
  local pmg, pmn = memory.read_u8(OE + 0x0A), memory.read_u8(OE + 0x09)   -- local player map
  local g = S.ghost
  local same_map = g and g.mg == pmg and g.mn == pmn

  if not same_map then
    if S.spawned then MB.ghost_clear(); S.spawned = false end
    return
  end

  if not S.spawned then
    MB.write_message(interact_text)     -- pre-set the talk-to-ghost message (patch shows it)
    MB.ghost_spawn(g.gfx or 0)          -- patch spawns + drives from here
    S.spawned, S.pi_last = true, MB.peer_interact_count()
  end

  -- post the partner's target each tick; the patch walks the ghost there natively
  MB.ghost_set_target(g.x, g.y, g.f, g.run, g.gfx)

  -- surface talk-to-ghost interactions (patch bumps pi_count + shows a dismissable box)
  local cnt = MB.peer_interact_count()
  if cnt ~= S.pi_last then S.interact_pending = true; S.pi_last = cnt end
end

function PG.debug()
  return S and { oeId = (MB and S.spawned) and MB.ghost_oe() or nil, spawned = S.spawned } or {}
end

return PG
