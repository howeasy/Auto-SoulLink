-- peer_ghost_npc.lua — engine-NPC peer ghost (Gen 3 Radical Red, companion-patch path).
--
-- Renders the partner as a REAL engine object-event spawned by the SLink companion patch
-- (SPAWN_PEER_NPC), then drives only its sprite POSITION/facing each frame. The engine owns
-- the sprite's graphics/palette/VRAM/callback, so the player-sprite corruption that plagued
-- the hand-cloned ghost cannot occur. Requires the patch (mailbox); no-ops gracefully without.
--
-- Receiver only: feed it the partner's position via on_ghost_pos{mg,mn,x,y,f,gfx} (world-pixel
-- x,y in the player's object-event coordinate space, i.e. tile*16). The sender/server relay is
-- unchanged. Positioning: an OE sprite is coordOffset-enabled like the player's, so
--   ghost.pos1 = playerSprite.pos1 + (ghost_worldPx - playerTile*16)
-- which places the ghost offset from the (always-centered) player by the world delta.

-- The companion-patch mailbox (loaded the same way the client loads its modules).
local ok_mb, MB = pcall(require, "mailbox")
if not ok_mb then MB = nil end

local PG = {}

local LOCALID = 0xF0          -- unique localId for the ghost object-event
local DEFAULT_GFX = nil       -- set from the player's gfx at spawn if the target omits one
local SNAP_PX = 48            -- jump (don't lerp) if the target is farther than this
local LERP = 0.35

-- cfg supplies the RR addresses (object events / sprites / camera offset)
local C = {
  OE = 0x02036E38, OE_STRIDE = 0x24,
  GS = 0x0202063C, GS_STRIDE = 0x44,
}

local S  -- live state

local DBG = true            -- log spawn lifecycle + throttled state (set false to silence)
local fcount = 0
local function dbg(s) if DBG then console.log("[peer-ghost] " .. s) end end

function PG.init(cfg)
  if cfg then for k, v in pairs(cfg) do C[k] = v end end
  S = { oeId = nil, sprId = nil, pending = nil, ghost = nil, dx = nil, dy = nil, pmap = nil }
end

function PG.present() return MB ~= nil and MB.present() end

-- ---- object-event / sprite field helpers ----
local function oe(i, off) return C.OE + i * C.OE_STRIDE + off end
local function p_spriteId() return memory.read_u8(oe(0, 0x04)) end
local function p_tile_x()   return memory.read_u16_le(oe(0, 0x10)) end
local function p_tile_y()   return memory.read_u16_le(oe(0, 0x12)) end
local function p_map()      return memory.read_u8(oe(0, 0x09)), memory.read_u8(oe(0, 0x0A)) end
local function p_gfx()      return memory.read_u8(oe(0, 0x05)) end
local function spr(i, off)  return C.GS + i * C.GS_STRIDE + off end
local function spr_inuse(i) return memory.read_u8(spr(i, 0x3E)) & 1 end
local function spr_pos_x(i) return memory.read_u16_le(spr(i, 0x20)) end
local function spr_pos_y(i) return memory.read_u16_le(spr(i, 0x22)) end

local function despawn()
  if S.oeId then dbg("despawn oeId=" .. tostring(S.oeId)); MB.send(MB.OP_DESPAWN_PEER_NPC, { S.oeId }) end
  S.oeId, S.sprId, S.pending, S.dx, S.dy = nil, nil, nil, nil, nil
end

-- partner position update (world-pixel x,y in OE-coordinate space)
function PG.on_ghost_pos(t)
  S.ghost = t           -- { mg, mn, x, y, f, gfx }
end

function PG.on_ghost_clear() S.ghost = nil; despawn() end
function PG.reset() despawn(); S.ghost = nil end

-- to be called every overworld frame
function PG.on_frame()
  if not PG.present() then return end          -- no patch -> no-op (graceful)
  fcount = fcount + 1
  local pmg, pmn = p_map()

  -- map change -> drop the ghost (indices/world differ on the new map)
  if S.pmap and (S.pmap[1] ~= pmg or S.pmap[2] ~= pmn) then despawn() end
  S.pmap = { pmg, pmn }

  local g = S.ghost
  local same_map = g and g.mg == pmg and g.mn == pmn

  -- throttled state line so the engine-NPC path isn't a black box during testing
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
      local gfx = g.gfx or DEFAULT_GFX or p_gfx()
      -- spawn one tile from the player so it's on-map; we drive the real position after
      local seq = MB.send(MB.OP_SPAWN_PEER_NPC,
        MB.spawn_npc_args(gfx, LOCALID, p_tile_x() + 1, p_tile_y(), 0))
      S.pending = seq
      dbg(string.format("spawn requested seq=%s gfx=%d at tile(%d,%d)", tostring(seq), gfx,
        p_tile_x() + 1, p_tile_y()))
    else
      local stp = MB.poll(S.pending)
      if stp then
        local id = MB.read_result_u8(0)
        S.pending = nil
        if id < 16 then S.oeId = id; S.sprId = memory.read_u8(oe(id, 0x04))
          dbg(string.format("spawned oeId=%d sprId=%d", S.oeId, S.sprId))
        else dbg("spawn FAILED (result id=" .. tostring(id) .. ") — retrying"); return end
      end
    end
    if not S.oeId then return end
  end

  -- the engine may recycle the slot (battle, warp); bail if our sprite went away
  if spr_inuse(S.sprId) == 0 then dbg("sprite recycled — re-spawning"); S.oeId, S.sprId = nil, nil; return end

  -- interpolate display world-pixel toward the target for smoothness
  if not S.dx or math.abs(g.x - S.dx) > SNAP_PX or math.abs(g.y - S.dy) > SNAP_PX then
    S.dx, S.dy = g.x, g.y
  else
    S.dx = S.dx + (g.x - S.dx) * LERP
    S.dy = S.dy + (g.y - S.dy) * LERP
  end

  -- ghost.pos1 = playerSprite.pos1 + (ghost_worldPx - playerTile*16)
  local psx = spr_pos_x(p_spriteId())
  local psy = spr_pos_y(p_spriteId())
  local gx = math.floor(psx + (S.dx - p_tile_x() * 16) + 0.5)
  local gy = math.floor(psy + (S.dy - p_tile_y() * 16) + 0.5)
  memory.write_u16_le(spr(S.sprId, 0x20), gx & 0xFFFF)
  memory.write_u16_le(spr(S.sprId, 0x22), gy & 0xFFFF)
  -- facing: idle anim = facing-1 (S/N/W/E -> 0/1/2/3)
  if g.f and g.f >= 1 and g.f <= 4 then memory.write_u8(spr(S.sprId, 0x2A), g.f - 1) end
end

-- diagnostics
function PG.debug() return S and { oeId = S.oeId, sprId = S.sprId, pending = S.pending } or {} end

return PG
