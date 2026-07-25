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
local OE = 0x02036E38          -- gObjectEvents[0] = the local player
-- engine's elevation->base subpriority table (event_object_movement.c sElevationToSubpriority)
local ELEV2SUB = {[0]=115,[1]=115,[2]=83,[3]=115,[4]=83,[5]=115,[6]=83,[7]=115,
                  [8]=83,[9]=115,[10]=83,[11]=115,[12]=83,[13]=0,[14]=0,[15]=115}
local interact_text = "Your partner is here!"   -- shown when YOU press A on the ghost
local SNAP_PX = 48             -- world-px jump beyond this in one update -> snap, don't slide
local S

function PG.init() S = { ghost = nil, spawned = false, pi_last = 0, interact_pending = false,
                         last_w = nil, av_imgs = nil, av_anims = nil, last_gsid = nil,
                         spawn_gfx = nil } end
function PG.present() return MB ~= nil and MB.present() end
function PG.set_interact_text(s) if s and s ~= "" then interact_text = s end end

-- partner state update; x,y are TILE coords (object-event currentCoords space)
function PG.on_ghost_pos(t) if S then S.ghost = t end end

function PG.on_ghost_clear()
  if not S then return end
  S.ghost = nil
  if S.spawned and MB then MB.ghost_clear() end
  S.spawned = false; S.last_w = nil; S.av_imgs = nil; S.av_anims = nil; S.last_gsid = nil
  S.spawn_gfx = nil
end

-- True once per detected talk-to-ghost (the client emits a peer_interact event to the server).
function PG.consume_interact()
  if S and S.interact_pending then S.interact_pending = false; return true end
  return false
end

function PG.on_frame()
  if not PG.present() then return end
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
  local want_gfx = (type(g.gfx) == "number" and g.gfx >= 0 and g.gfx <= 255) and g.gfx or 0
  if not S.spawned then
    MB.write_message(interact_text)     -- pre-set the talk-to-ghost message (patch shows it)
    MB.ghost_spawn(want_gfx)            -- patch spawns it + drives from here
    S.spawned, S.pi_last = true, MB.peer_interact_count()
    S.spawn_gfx = want_gfx
    S.last_w = nil; S.av_imgs = nil
  elseif want_gfx ~= S.spawn_gfx then
    -- Partner mounted the bike / started surfing / cast a rod: re-post the gfxId. drive_ghost sees
    -- gfxId ~= curGfx and does a clean remove + respawn at the new size, then re-applies the avatar.
    MB.ghost_spawn(want_gfx)
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

  -- Forward the partner's avatar (live sprite images/anims ROM ptrs + true 16-colour palette) to the
  -- patch, and cache the decoded values for the per-frame re-assert below. Only on change.
  if g.imgs and g.imgs ~= 0 and g.imgs ~= S.av_imgs then
    MB.ghost_set_avatar(g.imgs, g.anim or 0, g.pcol)
    S.av_imgs = g.imgs
    S.av_anims = g.anim or 0
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
        -- Read-compare-write: the re-assert must still WIN whenever the engine reverted the sprite,
        -- but on the (vast majority of) frames where nothing reverted, skip the redundant writes.
        if memory.read_u32_le(sa + 0x0C) ~= S.av_imgs then
          memory.write_u32_le(sa + 0x0C, S.av_imgs)                     -- sprite.images
        end
        if S.av_anims and S.av_anims ~= 0 and memory.read_u32_le(sa + 0x08) ~= S.av_anims then
          memory.write_u32_le(sa + 0x08, S.av_anims)                    -- sprite.anims
        end
        local attr2 = memory.read_u16_le(sa + 0x04)
        if (attr2 & 0xF000) ~= (15 << 12) then
          memory.write_u16_le(sa + 0x04, (attr2 & 0x0FFF) | (15 << 12)) -- OBJ palette slot 15
        end
        -- LAYERING: replicate the engine's per-frame OE subpriority (sElevationToSubpriority[elev] +
        -- screen-Y term + 1) so the ghost sorts in front/behind the player by depth, not always on top.
        local pelev = memory.read_u8(poe + 0x0B) & 0x0F
        local ccy = memory.read_s8(sa + 0x29)                       -- centerToCornerVecY
        local yy = (memory.read_s16_le(sa + 0x22) - ccy + memory.read_s16_le(0x02021BCA) + 8) & 0xFF
        yy = (16 - (yy >> 4)) << 1
        memory.write_u8(sa + 0x43, ((ELEV2SUB[pelev] or 115) + yy + 1) & 0xFF)
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
