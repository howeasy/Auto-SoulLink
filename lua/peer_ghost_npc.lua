-- peer_ghost_npc.lua — engine-driven peer ghost (Gen 3 Radical Red, companion-patch path).
--
-- The partner is ANOTHER real player playing their own game; we show THEM in our overworld — their
-- own trainer avatar + colours, moving and animating exactly as they move. The companion patch's
-- frame hook (drive_ghost in handlers.c) spawns a real engine object-event and consumes the
-- partner's committed STEP STREAM (one tile per step the partner actually walked), so the engine
-- owns sub-pixel motion / animation / day-night tint / culling / collision and the ghost mirrors
-- the partner's exact path one step behind — no "chase the sampled tile -> stop at every tile"
-- stutter. We no longer puppet sprite memory from Lua.
--
-- This receiver's whole job, when the partner is on the SAME map: request the ghost once; each tile
-- the partner advances, push one step into the shared ring; keep the absolute tile posted (snap
-- target); forward the partner's avatar (live sprite images/anims ptrs + palette). When not same
-- map, clear it. The patch owns the spawn/despawn/map-change/gfx-change lifecycle.
--
-- Feed via on_ghost_pos{mg,mn,x,y,f,mv,run,gfx,imgs,anim,pcol}; x,y are TILE coords (object-event
-- currentCoords space). Requires the patch (mailbox); no-ops gracefully without.

local ok_mb, MB = pcall(require, "mailbox")
if not ok_mb then MB = nil end

local PG = {}
local OE = 0x02036E38          -- gObjectEvents[0] = the local player
local interact_text = "Your partner is here!"   -- shown when YOU press A on the ghost
local SNAP_PX = 48             -- world-px jump beyond this in one update -> snap, don't slide
local S

function PG.init() S = { ghost = nil, spawned = false, pi_last = 0, interact_pending = false,
                         last_w = nil, av_imgs = nil, av_anims = nil, pcols = nil, last_gsid = nil } end
function PG.present() return MB ~= nil and MB.present() end
function PG.set_interact_text(s) if s and s ~= "" then interact_text = s end end

-- partner state update; x,y are TILE coords (object-event currentCoords space)
function PG.on_ghost_pos(t) if S then S.ghost = t end end

function PG.on_ghost_clear()
  if not S then return end
  S.ghost = nil
  if S.spawned and MB then MB.ghost_clear() end
  S.spawned = false; S.last_w = nil; S.av_imgs = nil; S.av_anims = nil; S.pcols = nil; S.last_gsid = nil
end

-- True once per detected talk-to-ghost (the client emits a peer_interact event to the server).
function PG.consume_interact()
  if S and S.interact_pending then S.interact_pending = false; return true end
  return false
end

function PG.on_frame()
  if not PG.present() then return end
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

  -- Spawn the stand-in with a FIXED 16x32 / 8-tile base gfx (0 = the default player base), NOT the
  -- local player's gfx. The local player's graphicsId can resolve to a DIFFERENT OAM size than the
  -- actual on-foot character (e.g. a custom character whose graphicsId's static graphics-info is
  -- 32x32 / 16 tiles), which would leave the ghost a 32x32 OAM and render the 8-tile partner frame as
  -- a corrupted blob. A fixed 16x32 base guarantees the OAM matches every 8-tile on-foot partner; the
  -- patch then repaints it to the PARTNER's avatar (their live sprite ptrs + colours into slot 15).
  local STANDIN_GFX = 0
  if not S.spawned then
    MB.write_message(interact_text)     -- pre-set the talk-to-ghost message (patch shows it)
    MB.ghost_spawn(STANDIN_GFX)         -- patch spawns the 16x32 stand-in + drives from here
    S.spawned, S.pi_last = true, MB.peer_interact_count()
    S.last_w = nil; S.av_imgs = nil
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

  -- Forward the partner's avatar (live sprite images/anims ROM ptrs + true 16-colour palette) to the
  -- patch, and cache the decoded values for the per-frame re-assert below. Only on change.
  if g.imgs and g.imgs ~= 0 and g.imgs ~= S.av_imgs then
    MB.ghost_set_avatar(g.imgs, g.anim or 0, g.pcol)
    S.av_imgs = g.imgs
    S.av_anims = g.anim or 0
    S.pcols = nil
    if g.pcol and #g.pcol >= 64 then
      S.pcols = {}
      for i = 0, 15 do S.pcols[i] = tonumber(g.pcol:sub(i*4+1, i*4+4), 16) or 0 end
    end
  end

  -- Re-assert the partner's avatar onto the ghost sprite EVERY FRAME, here in Lua. The client runs
  -- this at end-of-frame (after the engine's field update), so a post-warp / door-transition sprite
  -- reload can't leave the ghost showing the local stand-in — our write always wins. (The patch also
  -- stamps it at frame-top; this is the belt-and-braces that fixes the "ghost looks like me" revert.)
  if S.av_imgs and S.spawned then
    local goe = MB.ghost_oe()
    -- ONLY write if the slot is still ACTIVE and OURS (localId 0xF0). After a warp the engine rebuilds
    -- the object-event array and may reassign our old slot to a real map NPC; without this guard the
    -- re-assert would scribble the partner's sprite/palette onto that NPC (or the player) = corruption.
    local owned = goe < 16 and (memory.read_u8(OE + goe*0x24) & 1) == 1
                            and memory.read_u8(OE + goe*0x24 + 0x08) == 0xF0
    if owned then
      local gsid = memory.read_u8(OE + goe*0x24 + 0x04)
      if gsid < 64 then
        local sa = 0x0202063C + gsid*0x44
        memory.write_u32_le(sa + 0x0C, S.av_imgs)                       -- sprite.images
        if S.av_anims and S.av_anims ~= 0 then memory.write_u32_le(sa + 0x08, S.av_anims) end
        local attr2 = memory.read_u16_le(sa + 0x04)
        memory.write_u16_le(sa + 0x04, (attr2 & 0x0FFF) | (15 << 12))   -- OBJ palette slot 15
        if S.pcols then
          for i = 0, 15 do
            local c = S.pcols[i] or 0
            memory.write_u16_le(0x020373F8 + 15*0x20 + i*2, c)          -- unfaded slot 15
            memory.write_u16_le(0x020377F8 + 15*0x20 + i*2, c)          -- faded slot 15
          end
        end
        if gsid ~= S.last_gsid then                                     -- respawn -> re-DMA new tiles now
          memory.write_u8(sa + 0x3F, memory.read_u8(sa + 0x3F) | 0x04)  -- animBeginning
          memory.write_u8(sa + 0x2C, memory.read_u8(sa + 0x2C) & 0xBF)  -- animPaused = 0
          S.last_gsid = gsid
        end
      end
    end
  end

  -- Mirror the partner's exact motion: post their WORLD-PIXEL position + facing + moving + live
  -- animNum; the patch LERPs the ghost there sub-pixel (continuous, speed-agnostic) and plays their
  -- animation. Snap on the first frame on this map or a large jump (warp/lag); else slide smoothly.
  local wx, wy = g.x or 0, g.y or 0
  MB.ghost_set_pos(wx, wy, g.f, g.mv == 1, g.an)
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

  -- surface talk-to-ghost interactions (patch bumps pi_count + shows a dismissable box)
  local cnt = MB.peer_interact_count()
  if cnt ~= S.pi_last then S.interact_pending = true; S.pi_last = cnt end
end

function PG.debug()
  return S and { oeId = (MB and S.spawned) and MB.ghost_oe() or nil, spawned = S.spawned } or {}
end

return PG
