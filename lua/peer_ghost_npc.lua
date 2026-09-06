-- peer_ghost_npc.lua — engine-driven peer ghost (Gen 3 Radical Red, companion-patch path).
--
-- The partner is ANOTHER real player playing their own game; we show THEM in our overworld — their
-- own trainer avatar + colours, moving and animating exactly as they move. The companion patch's
-- frame hook (drive_ghost in handlers.c) spawns a real engine object-event for the sprite slot /
-- collision / palette, neutralizes its callback, and follows the partner's broadcast sub-pixel
-- WORLD-PIXEL position at constant engine velocity (1 px/frame walk, 2 run), extrapolating up to
-- GHOST_LEAD_CAP_PX past a stale sample while the partner is still moving — continuous motion, no
-- "chase the sampled tile -> stop at every tile" stutter. We no longer puppet sprite memory from
-- Lua. (The older step-stream design was rejected: it belongs to the abandoned held-movement
-- driver — see patch/ROADMAP.md §1.)
--
-- This receiver's whole job, when the partner is on the SAME map: request the ghost once; keep the
-- partner's world-px position + facing/moving/anim posted into GhostState; forward their avatar
-- (live sprite images/anims ptrs + palette). When not same map, clear it. The patch owns the
-- spawn/despawn/map-change/gfx-change lifecycle.
--
-- Feed via on_ghost_pos{mg,mn,x,y,f,mv,run,gfx,imgs,anim,pcol}; x,y are WORLD PIXELS (sub-pixel).
-- Requires the patch (mailbox); no-ops gracefully without.

local ok_mb, MB = pcall(require, "mailbox")
if not ok_mb then MB = nil end

local PG = {}
local interact_text = "Your partner is here!"   -- shown when YOU press A on the ghost
local SNAP_PX = 48             -- world-px jump beyond this in one update -> snap, don't slide
local S

function PG.init() S = { ghost = nil, enabled = true, spawned = false, pi_last = 0, interact_pending = false,
                         last_w = nil, av_imgs = nil, av_anims = nil, av_pcol = nil,
                         spawn_gfx = nil } end
function PG.present() return MB ~= nil and MB.present() end
function PG.set_interact_text(s) if s and s ~= "" then interact_text = s end end

-- partner state update; x,y are world-pixel coordinates
function PG.on_ghost_pos(t)
  if not S or not S.enabled or type(t) ~= "table" then return false end
  local bounds = {mg={0,255}, mn={0,255}, x={-32768,32767}, y={-32768,32767},
                  f={1,4}, gfx={0,65535}}
  for field, range in pairs(bounds) do
    local v = t[field]
    if type(v) ~= "number" or v % 1 ~= 0 or v < range[1] or v > range[2] then return false end
  end
  for _, field in ipairs({"mv", "run", "an"}) do
    local v = t[field]
    local max = field == "an" and 255 or 1
    if v ~= nil and (type(v) ~= "number" or v % 1 ~= 0 or v < 0 or v > max) then return false end
  end
  if t.pcol ~= nil and (type(t.pcol) ~= "string" or #t.pcol ~= 64 or not t.pcol:match("^[0-9a-fA-F]+$")) then return false end
  for _, field in ipairs({"imgs", "anim"}) do
    local v = t[field]
    if v ~= nil and v ~= 0 and (type(v) ~= "number" or v % 4 ~= 0 or v < 0x08000000 or v >= 0x0A000000) then return false end
  end
  S.ghost = t
  return true
end

function PG.on_ghost_clear()
  if not S then return end
  S.ghost = nil
  if S.spawned and MB then MB.ghost_clear() end
  S.spawned = false; S.last_w = nil; S.av_imgs = nil; S.av_anims = nil; S.av_pcol = nil
  S.spawn_gfx = nil
end

function PG.set_enabled(value)
  if not S then PG.init() end
  S.enabled = value == true
  if not S.enabled then PG.on_ghost_clear() end
end

-- True once per detected talk-to-ghost (the client emits a peer_interact event to the server).
function PG.consume_interact()
  if S and S.interact_pending then S.interact_pending = false; return true end
  return false
end

function PG.on_frame()
  if not S or not S.enabled or not PG.present() then return end
  -- Only touch the ghost in the WALKABLE FIELD. Menus (party/bag/start), the trade scene, etc. reuse
  -- gSprites for their own UI; the avatar re-assert below writes gSprites[ghost_sid], which corrupts
  -- those screens (the party-menu "square"/sprite errors). is_overworld is TRUE in menus (only battle
  -- flips it false), so gate on gMain.callback2 == CB2_Overworld (the field, incl. field dialogues).
  if memory.read_u32_le(0x030030F4) ~= 0x080565B5 then return end
  local poe = MB.player_oe()                                              -- player's actual slot
  local pmg, pmn = memory.read_u8(poe + 0x0A), memory.read_u8(poe + 0x09) -- local player map
  local g = S.ghost
  local same_map = g and g.mg == pmg and g.mn == pmn

  -- one-shot: confirm the partner's position is reaching us + whether we're on the same map
  if g and not S.first_logged then
    S.first_logged = true
    console.log(string.format("[peer-ghost] partner pos received: theirs=map(%s,%s)@tile(%s,%s) "
      .. "mine=map(%d,%d) same_map=%s", tostring(g.mg), tostring(g.mn), tostring(g.x), tostring(g.y),
      pmg, pmn, tostring(same_map)))
  end

  if not same_map then
    if S.spawned then MB.ghost_clear(); S.spawned = false end
    S.last_w = nil; S.av_imgs = nil
    return
  end

  -- Spawn with the PARTNER's own graphicsId, so the engine allocates the OAM shape/size and tile
  -- count that their sprite actually needs. This is what makes bike / surf / fishing work: those
  -- frames are 32x32 / 16 tiles, and the old fixed 16x32 stand-in rendered them as a corrupted blob
  -- because the avatar repoint only swaps the image POINTER, not the OAM geometry.
  --
  -- Never the LOCAL player's gfx: a custom local character can resolve to a different OAM size than
  -- the partner's, which is the bug the stand-in was working around. Both players run the same RR
  -- build, so the partner's graphicsId indexes the same graphics-info table here. Fall back to 0 (the
  -- default 16x32 player base) until their gfx has actually arrived.
  local want_gfx = (type(g.gfx) == "number" and g.gfx >= 0 and g.gfx <= 65535 and g.gfx % 1 == 0) and g.gfx or 0
  if not S.spawned then
    MB.write_message(interact_text)     -- pre-set the talk-to-ghost message (patch shows it)
    local request = MB.ghost_spawn(want_gfx)
    if not request then return end
    S.spawned, S.pi_last = true, MB.peer_interact_count()
    S.spawn_gfx = want_gfx
    S.last_w = nil; S.av_imgs = nil
  elseif want_gfx ~= S.spawn_gfx then
    -- Partner mounted the bike / started surfing / cast a rod: re-post the gfxId. drive_ghost sees
    -- gfxId ~= curGfx and does a clean remove + respawn at the new size, then re-applies the avatar.
    local request = MB.ghost_spawn(want_gfx)
    if not request then return end
    S.spawn_gfx = want_gfx
    S.av_imgs = nil                     -- force the avatar re-forward onto the new sprite slot
    console.log("[peer-ghost] partner avatar size changed -> respawn gfx=" .. want_gfx)
  end

  -- One-shot diagnostic: is the partner's avatar data actually DIFFERENT from ours? (If you both
  -- picked the same character, the ghost legitimately looks like you.) Compares the partner's
  -- broadcast imgs/anim/palette to the LOCAL player's, and flags a nil parse (no avatar received).
  if not S.av_logged then
    S.av_logged = true
    local lsid = memory.read_u8(poe + 0x04)
    local limgs = (lsid < 64) and memory.read_u32_le(0x0202063C + lsid*0x44 + 0x0C) or 0
    local lslot = (lsid < 64) and ((memory.read_u16_le(0x0202063C + lsid*0x44 + 0x04) >> 12) & 0x0F) or 0
    local lpc = ""
    for i = 0, 3 do lpc = lpc .. string.format("%04X", memory.read_u16_le(0x020373F8 + lslot*0x20 + i*2)) end
    console.log(string.format("[peer-ghost] AVATAR partner imgs=%s anim=%s pcol=%s | LOCAL imgs=0x%08X pcol=%s | same_imgs=%s",
      g.imgs and string.format("0x%08X", g.imgs) or "NIL(parse?)",
      g.anim and string.format("0x%08X", g.anim) or "nil",
      (g.pcol or "nil"):sub(1, 16), limgs, lpc, tostring(g.imgs == limgs)))
  end

  -- Stage complete desired avatar state; the native owner handles all sprite,
  -- palette, allocation, animation and depth writes. Re-forward palette-only and
  -- animation-table changes even if the images pointer stayed unchanged.
  if g.imgs and g.imgs ~= 0 and (g.imgs ~= S.av_imgs or g.anim ~= S.av_anims or g.pcol ~= S.av_pcol) then
    MB.ghost_set_avatar(g.imgs, g.anim or 0, g.pcol)
    S.av_imgs, S.av_anims, S.av_pcol = g.imgs, g.anim, g.pcol
  end

  -- Mirror the partner's exact motion: post their WORLD-PIXEL position + facing + moving + live
  -- animNum; the patch LERPs the ghost there sub-pixel (continuous, speed-agnostic) and plays their
  -- animation. Snap on the first frame on this map or a large jump (warp/lag); else slide smoothly.
  local wx, wy = g.x or 0, g.y or 0
  MB.ghost_set_pos(wx, wy, g.f, g.mv == 1, g.an, g.run == 1)
  if S.last_w == nil then
    MB.ghost_snap()                              -- first frame on this map: place, don't slide in
    S.last_w = { x = wx, y = wy }
  else
    local jump = math.abs(wx - S.last_w.x) + math.abs(wy - S.last_w.y)
    if jump > SNAP_PX then MB.ghost_snap() end   -- warp / big lag gap -> snap instead of a long slide
    S.last_w.x, S.last_w.y = wx, wy
  end

  -- one-shot: confirm the patch actually spawned the engine ghost
  if not S.spawn_logged and MB.ghost_oe() < 16 then
    S.spawn_logged = true
    console.log("[peer-ghost] ghost spawned (engine oeId=" .. MB.ghost_oe() .. ")")
  end

  -- surface talk-to-ghost interactions (patch bumps pi_count + shows a dismissable box).
  -- A BACKWARDS counter means a savestate load / soft reset rewound EWRAM: re-latch
  -- silently instead of firing a phantom interact.
  local cnt = MB.peer_interact_count()
  if cnt < S.pi_last then S.pi_last = cnt
  elseif cnt ~= S.pi_last then S.interact_pending = true; S.pi_last = cnt end
end

function PG.debug()
  return S and { oeId = (MB and S.spawned) and MB.ghost_oe() or nil, spawned = S.spawned } or {}
end

return PG
