-- peer_ghost_npc.lua — engine-NPC peer ghost (Gen 3 Radical Red, companion-patch path).
--
-- Renders the partner as a REAL engine object-event spawned by the SLink companion patch
-- (SPAWN_PEER_NPC). The engine allocates the sprite / VRAM tiles / palette slot and applies
-- day/night tint (so tint is correct for free — the clone's hardest-won fix). We then drive
-- the sprite as a PUPPET: neutralize its movement callback so the engine stops fighting us,
-- and each frame set its sub-pixel position, walk/idle animation, and backing-OE tile.
--
-- Techniques ported from the proven clone (zealous-mccarthy-84307d/lua/peer_ghost.lua):
--  • sub-pixel smoothness: sender broadcasts coordOffset-derived WORLD PIXELS; we position via
--    a baseline C = playerSprite.pos1 - playerTile*16 CACHED WHILE THE PLAYER IS IDLE, so the
--    ghost never lurches when the player's tile snaps mid-step. ghost.pos1 = round(disp + C).
--  • animation: want = moving and walk_anim(f) or idle_anim(f) (idle=f-1, walk=f+3), with the
--    partner's live animNum preferred while moving. Set animNum + animBeginning each change.
--  • collision + interaction: keep the backing OE solid (matched elevation) and its currentCoords
--    UNDER the ghost, so you bump into your partner where you see them (no phantom/"invisible"
--    collision), and pressing A toward it fires the patch's ARM_PEER_INTERACT detection.
--
-- Receiver only: feed partner state via on_ghost_pos{mg,mn,x,y,f,mv,an,gfx}. Requires the patch.

local ok_mb, MB = pcall(require, "mailbox")
if not ok_mb then MB = nil end

local PG = {}

local LOCALID = 0xF0          -- unique localId for the ghost object-event
local SNAP_PX = 48            -- jump (don't lerp) if the target is farther than this (3 tiles)
local LERP    = 0.35

-- RR addresses (patch is RR-only, md5 8529f3a4). cfg may override.
local C = {
  OE = 0x02036E38, OE_STRIDE = 0x24,   -- gObjectEvents (slot 0 = player)
  GS = 0x0202063C, GS_STRIDE = 0x44,   -- gSprites
  COFF_X = 0x02021BC8, COFF_Y = 0x02021BCA,  -- gSpriteCoordOffsetX/Y (s16)
}

-- OE field offsets
local OE_FLAGS, OE_SPRID, OE_GFX = 0x00, 0x04, 0x05
local OE_MAPNUM, OE_MAPGRP, OE_ELEV = 0x09, 0x0A, 0x0B
local OE_CX, OE_CY, OE_PX, OE_PY, OE_FACE = 0x10, 0x12, 0x14, 0x16, 0x18
-- sprite field offsets
local SP_ANIMS, SP_IMAGES = 0x08, 0x0C   -- ROM ptrs: anim-cmd table + frame images
local SP_CALLBACK, SP_X, SP_Y, SP_ANIM = 0x1C, 0x20, 0x22, 0x2A
local SP_B2C, SP_B3E, SP_B3F = 0x2C, 0x3E, 0x3F
local function in_rom(a) return a and a >= 0x08000000 and a < 0x0A000000 end

-- pret ANIM_STD: face S/N/W/E = 0/1/2/3 ; go (walk) = 4/5/6/7. facing 1=down 2=up 3=left 4=right.
local function idle_anim(f) return f - 1 end
local function walk_anim(f) return f + 3 end

local S         -- live state
local noop_cb   -- inert `bx lr` ROM addr (found lazily), thumb bit set
local interact_text = "Your partner is here!"   -- native box on A-press (set via PG.set_interact_text)

local DBG = true
local fcount = 0
local function dbg(s) if DBG then console.log("[peer-ghost] " .. s) end end

function PG.init(cfg)
  if cfg then for k, v in pairs(cfg) do C[k] = v end end
  S = { oeId = nil, sprId = nil, pending = nil, ghost = nil, dx = nil, dy = nil, pmap = nil,
        base_cx = nil, base_cy = nil, last_anim = nil, neutralized = false, armed = false, pi_last = 0,
        interact_pending = false, cur_gfx = nil, applied_imgs = nil }
end

function PG.present() return MB ~= nil and MB.present() end
function PG.set_interact_text(s) if s and s ~= "" then interact_text = s end end

-- ---- helpers ----
local function oe(i, off) return C.OE + i * C.OE_STRIDE + off end
local function spr(i, off) return C.GS + i * C.GS_STRIDE + off end
local function p_spriteId() return memory.read_u8(oe(0, OE_SPRID)) end
local function p_tile_x()   return memory.read_u16_le(oe(0, OE_CX)) end
local function p_tile_y()   return memory.read_u16_le(oe(0, OE_CY)) end
local function p_map()      return memory.read_u8(oe(0, OE_MAPNUM)), memory.read_u8(oe(0, OE_MAPGRP)) end
local function p_gfx()      return memory.read_u8(oe(0, OE_GFX)) end
local function p_idle()     return (memory.read_u8(oe(0, OE_FLAGS)) & 0x80) ~= 0 end  -- heldMovementFinished
local function p_elev()     return memory.read_u8(oe(0, OE_ELEV)) end
local function spr_inuse(i) return memory.read_u8(spr(i, SP_B3E)) & 1 end
local function spr_pos_x(i) return memory.read_u16_le(spr(i, SP_X)) end
local function spr_pos_y(i) return memory.read_u16_le(spr(i, SP_Y)) end
local function round(n)     return math.floor(n + 0.5) end

-- Find an inert `bx lr` (Thumb 0x4770) in low ROM to use as a no-op sprite callback.
local function find_noop_cb()
  if noop_cb ~= nil then return noop_cb end
  for off = 0, 0xFFFF, 2 do
    if memory.read_u16_le(0x08000000 + off) == 0x4770 then noop_cb = (0x08000000 + off) | 1; return noop_cb end
  end
  noop_cb = false   -- not found; skip neutralize rather than write a bad pointer
  return noop_cb
end

local function disarm()
  if S.armed and MB then MB.send(MB.OP_ARM_PEER_INTERACT, { 0, 0 }) end
  S.armed = false
end

local function despawn()
  disarm()
  if S.oeId then dbg("despawn oeId=" .. tostring(S.oeId)); MB.send(MB.OP_DESPAWN_PEER_NPC, { S.oeId }) end
  S.oeId, S.sprId, S.pending, S.dx, S.dy = nil, nil, nil, nil, nil
  S.base_cx, S.base_cy, S.last_anim, S.neutralized, S.applied_imgs = nil, nil, nil, false, nil
end

-- partner state update { mg, mn, x, y, f, mv, an, gfx } (x,y are WORLD PIXELS)
function PG.on_ghost_pos(t) S.ghost = t end
function PG.on_ghost_clear() S.ghost = nil; despawn() end
function PG.reset() despawn(); S.ghost = nil end

-- True once per detected talk-to-ghost (the client emits a peer_interact event).
function PG.consume_interact()
  if S and S.interact_pending then S.interact_pending = false; return true end
  return false
end

function PG.on_frame()
  if not PG.present() then return end          -- no patch -> no-op (graceful)
  fcount = fcount + 1
  local pmg, pmn = p_map()

  -- map change -> drop the ghost (indices/world differ on the new map)
  if S.pmap and (S.pmap[1] ~= pmg or S.pmap[2] ~= pmn) then despawn() end
  S.pmap = { pmg, pmn }

  local g = S.ghost
  local same_map = g and g.mg == pmg and g.mn == pmn

  if DBG and fcount % 120 == 0 then
    dbg(string.format("state oeId=%s pending=%s same_map=%s g=%s my_map=(%d,%d)%s",
      tostring(S.oeId), tostring(S.pending), tostring(same_map),
      g and string.format("(%d,%d)", g.mg, g.mn) or "nil", pmg, pmn,
      g and "" or "  [no partner pos yet]"))
  end

  if not same_map then if S.oeId then despawn() end; return end

  -- spawn (async): request once, then adopt the returned object-event id
  if not S.oeId then
    if not S.pending then
      local gfx = g.gfx or p_gfx()
      local seq = MB.send(MB.OP_SPAWN_PEER_NPC,
        MB.spawn_npc_args(gfx, LOCALID, p_tile_x() + 1, p_tile_y(), 0))
      S.pending, S.cur_gfx = seq, gfx
      dbg(string.format("spawn requested seq=%s gfx=%d at tile(%d,%d)", tostring(seq), gfx,
        p_tile_x() + 1, p_tile_y()))
    else
      local stp = MB.poll(S.pending)
      if stp then
        local id = MB.read_result_u8(0)
        S.pending = nil
        if id < 16 then S.oeId = id; S.sprId = memory.read_u8(oe(id, OE_SPRID))
          dbg(string.format("spawned oeId=%d sprId=%d gfx=%d", S.oeId, S.sprId, S.cur_gfx or -1))
        else dbg("spawn FAILED (result id=" .. tostring(id) .. ") — retrying"); return end
      end
    end
    if not S.oeId then return end
  end

  -- the engine may recycle the slot (battle, warp); bail if our sprite went away
  if spr_inuse(S.sprId) == 0 then dbg("sprite recycled — re-spawning"); S.oeId, S.sprId = nil, nil; return end

  -- The partner changed graphics (walk<->run share a gfx, but bike/surf/fish are DIFFERENT
  -- graphicsIds with their own sprites + anim tables). Re-spawn so the engine loads the right
  -- sprite/anims/palette for the new mode — the ghost then bikes/surfs/fishes natively.
  if g.gfx and g.gfx ~= S.cur_gfx then
    dbg(string.format("partner gfx %d -> %d; re-spawning", S.cur_gfx or -1, g.gfx))
    despawn(); return
  end

  -- One-time per spawn: neutralize the OE sprite callback so the engine stops re-asserting
  -- idle facing / palette over our puppet drive (sprite still animates via AnimateSprite).
  -- Then ARM the patch's talk-to-ghost detection on this object-event.
  if not S.neutralized then
    local cb = find_noop_cb()
    if cb then memory.write_u32_le(spr(S.sprId, SP_CALLBACK), cb & 0xFFFFFFFF) end
    -- ensure coordOffset on, animPaused off, visible
    memory.write_u8(spr(S.sprId, SP_B3E), (memory.read_u8(spr(S.sprId, SP_B3E)) | 0x01 | 0x02) & 0xFB)
    memory.write_u8(spr(S.sprId, SP_B2C), memory.read_u8(spr(S.sprId, SP_B2C)) & 0xBF)
    MB.write_message(interact_text)
    MB.send(MB.OP_ARM_PEER_INTERACT, { S.oeId, 1 })
    S.armed, S.pi_last, S.neutralized = true, MB.peer_interact_count(), true
    dbg(string.format("neutralized cb=%s + armed interact on oeId=%d", cb and "yes" or "NO", S.oeId))
  end

  -- Show the PARTNER's exact sprite (RR avatars are dynamic — the spawn gfx renders the LOCAL
  -- player, not them). images/anims are ROM ptrs identical on both copies of this RR build, so
  -- adopting the partner's live ones gives their exact look + exact anim table (so run/bike/surf/
  -- fish animNums map correctly). Same gfx => same frame size => fits the engine-allocated VRAM.
  -- Callback is neutralized, so the override isn't re-derived away.
  if g.imgs and in_rom(g.imgs) and g.imgs ~= S.applied_imgs then
    memory.write_u32_le(spr(S.sprId, SP_IMAGES), g.imgs & 0xFFFFFFFF)
    if in_rom(g.anm) then memory.write_u32_le(spr(S.sprId, SP_ANIMS), g.anm & 0xFFFFFFFF) end
    memory.write_u8(spr(S.sprId, SP_B3F), memory.read_u8(spr(S.sprId, SP_B3F)) | 0x04)  -- animBeginning
    S.applied_imgs, S.last_anim = g.imgs, nil
    dbg(string.format("applied partner sprite images=%08X anims=%08X", g.imgs, g.anm or 0))
  end

  -- interpolate display world-pixel toward the target for smoothness
  if not S.dx or math.abs(g.x - S.dx) > SNAP_PX or math.abs(g.y - S.dy) > SNAP_PX then
    S.dx, S.dy = g.x, g.y
  else
    S.dx = S.dx + (g.x - S.dx) * LERP
    S.dy = S.dy + (g.y - S.dy) * LERP
  end

  -- Sub-pixel position: baseline C = playerSprite.pos1 - playerTile*16, cached WHILE THE
  -- PLAYER IS IDLE (then playerTile*16 is exact); ghost.pos1 = round(disp + C). Avoids the
  -- lurch from reading the player's tile mid-step (it snaps to the destination tile).
  local psid = p_spriteId()
  local psx, psy = spr_pos_x(psid), spr_pos_y(psid)
  if p_idle() or S.base_cx == nil then
    S.base_cx = psx - p_tile_x() * 16
    S.base_cy = psy - p_tile_y() * 16
  end
  local gx, gy = round(S.dx + S.base_cx), round(S.dy + S.base_cy)
  memory.write_u16_le(spr(S.sprId, SP_X), gx & 0xFFFF)
  memory.write_u16_le(spr(S.sprId, SP_Y), gy & 0xFFFF)

  -- Visibility (invisible bit 0x04 of byte3e; engine callback is neutralized so this sticks):
  --  • CULL off-screen — a sprite far outside the viewport has its OAM coord WRAP (9-bit X /
  --    8-bit Y) and draws as garbage at a random on-screen spot. Screen pos = pos1 + coordOffset.
  --  • HIDE until the partner's real sprite is applied — avoids the 1-frame spawn-gfx (= the LOCAL
  --    player) flash at spawn / door-transition re-spawn. (No gate if the partner sends no imgs.)
  local ssx = gx + memory.read_s16_le(C.COFF_X)
  local ssy = gy + memory.read_s16_le(C.COFF_Y)
  local onscreen = ssx > -16 and ssx < 256 and ssy > -16 and ssy < 176
  local sprite_ready = (not (g.imgs and in_rom(g.imgs))) or (S.applied_imgs ~= nil)
  local b3e = memory.read_u8(spr(S.sprId, SP_B3E))
  if onscreen and sprite_ready then b3e = b3e & 0xFB else b3e = b3e | 0x04 end
  memory.write_u8(spr(S.sprId, SP_B3E), b3e)

  -- Backing OE tile = the partner's ACTUAL tile (not the lerped display) so collision +
  -- interaction land under the ghost. Solid: match the player's elevation.
  local gtx, gty = round(g.x / 16), round(g.y / 16)
  memory.write_u16_le(oe(S.oeId, OE_CX), gtx & 0xFFFF); memory.write_u16_le(oe(S.oeId, OE_CY), gty & 0xFFFF)
  memory.write_u16_le(oe(S.oeId, OE_PX), gtx & 0xFFFF); memory.write_u16_le(oe(S.oeId, OE_PY), gty & 0xFFFF)
  memory.write_u8(oe(S.oeId, OE_ELEV), p_elev())

  -- Animation: while moving, mirror the partner's LIVE animNum (walk/run/bike/surf/fish — the
  -- ghost shares the partner's gfx after the re-spawn above, so any animNum is valid here); fall
  -- back to a directional walk if none sent. Idle -> a single-frame face anim. Re-assert
  -- animBeginning so frame 0 re-DMAs.
  local f = (g.f and g.f >= 1 and g.f <= 4) and g.f or 1
  local want
  if g.mv == 1 then want = (g.an and g.an > 0) and g.an or walk_anim(f)
  else want = idle_anim(f) end
  if want ~= S.last_anim then
    memory.write_u8(spr(S.sprId, SP_ANIM), want & 0xFF)
    memory.write_u8(spr(S.sprId, SP_B3F), memory.read_u8(spr(S.sprId, SP_B3F)) | 0x04)  -- animBeginning
    memory.write_u8(spr(S.sprId, SP_B2C), memory.read_u8(spr(S.sprId, SP_B2C)) & 0xBF)  -- animPaused = 0
    S.last_anim = want
  end

  -- Poll the patch's talk-to-ghost counter; surface each new interaction to the client.
  if S.armed then
    local cnt = MB.peer_interact_count()
    if cnt ~= S.pi_last then
      S.interact_pending = true
      dbg(string.format("interact detected (count %d -> %d)", S.pi_last, cnt))
      S.pi_last = cnt
    end
  end
end

function PG.debug() return S and { oeId = S.oeId, sprId = S.sprId, pending = S.pending, armed = S.armed } or {} end

return PG
