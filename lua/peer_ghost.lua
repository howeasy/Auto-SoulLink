--[[
  lua/peer_ghost.lua — render the partner player as a live overworld "ghost"
  ===========================================================================
  Renders the SoulLink partner as an in-engine NPC sprite that mirrors their
  live overworld position 1:1, as if both players shared one world.

  MECHANISM (proven in Phase 0 — see lua/tests/test_overworld_discovery.lua):
    • Clone the LOCAL player's trainer sprite (always present, fully animated)
      into a FREE gSprites slot, giving it its OWN OBJ-VRAM tiles (oam.tileNum
      → a free region) so it never fights the player's tiles.
    • Back it with a FREE object-event slot whose coords we pin to the partner's
      tile (collision is acceptable; pinning prevents the off-screen cull).
    • Each frame: position the ghost sprite at the partner's world tile RELATIVE
      to the local player (camera-safe: ghost.pos1 = player.pos1 + 16·tileDelta),
      and drive its walk/idle animation from the partner's facing + moving bit.
    • Interpolate the partner's tile-to-tile motion for smooth movement at the
      ~10 Hz ghost_pos update rate.
    • On a local map change the engine rebuilds both arrays, so we FORGET our
      slot refs WITHOUT writing memory (deactivating reused indices would
      corrupt new-map NPCs) and respawn after a short cooldown.

  GEN-AGNOSTIC: every address/offset comes from the cfg table passed to init();
  the gen-3 client supplies them.  A future generation can reuse this module by
  supplying its own cfg.

  API:
    PG.init(cfg)              -- one-time setup with addresses/offsets
    PG.on_ghost_pos(cmd)      -- server "ghost_pos" command {mg,mn,x,y,f,mv,...}
    PG.on_ghost_clear()       -- server "ghost_clear" command (partner gone)
    PG.on_frame()             -- call every frame, late (after engine update)
    PG.reset()                -- drop everything (e.g. on disconnect)
--]]

local PG = {}

-- BizHawk memory shorthands
local r8   = memory.read_u8
local r16  = memory.read_u16_le
local r32  = memory.read_u32_le
local rs16 = memory.read_s16_le
local w8   = memory.write_u8
local w16  = memory.write_u16_le
local w32  = memory.write_u32_le
local ws16 = memory.write_s16_le

-- ── config + state ────────────────────────────────────────────────────────────
local cfg = nil

-- Partner state from the latest ghost_pos (nil = no ghost to show).
local ghost = nil          -- { mg, mn, x, y, f, mv }

-- Our claimed slots + render state.
local objslot, sprslot = nil, nil
local disp_x, disp_y   = nil, nil   -- interpolated display tile (fractional)
local last_map_g, last_map_n = -1, -1
local cooldown   = 0
local last_anim  = nil
local ghost_tile = nil              -- dynamically-claimed free OBJ-VRAM tile base
local reserved_tile = nil           -- tile base currently RESERVED in the alloc bitmap (nil = none)
local applied_imgs  = nil           -- partner-trainer images ptr currently applied (nil = cloned local look)
local dbg_frames = 0   -- throttle for the [PG-DBG] diagnostic log
local spin_tick  = 0   -- drives the "partner in battle" spin-in-place indicator
-- A sprite slot left behind by suspend() (menu/battle): we can't clear its inUse
-- while the engine has gSprites repurposed, so we remember it and clear it on the
-- next field frame (safe) — otherwise it lingers as an orphan ghost after a menu.
local stale_sprslot = nil
-- Map baseline C = playerSprite.pos1 - playerTile*16 (cached while idle); the
-- ghost's coordOffset-enabled pos1 = partnerTile*16 + C renders map-fixed.
local base_cx, base_cy = nil, nil

local GHOST_TILE_COUNT = 8          -- 16x32 overworld sprite = 8 tiles
local TOTAL_OBJ_TILES  = 1024
local GHOST_PAL_SLOT   = 15         -- the ghost's OWN OBJ palette slot (high → rarely
                                    -- contested; never the player's slot, so the engine's
                                    -- palette ref-count for the player stays balanced)

-- Tunables.  Positions over the wire are now WORLD PIXELS (sub-pixel precise),
-- so interpolation works in pixels.
local VIEW_X, VIEW_Y = 9, 7    -- half-viewport in TILES; cull the ghost beyond
local GHOST_LERP     = 0.35    -- ease toward the (smooth, sub-pixel) target; the
                               -- target is already smooth so a light ease tracks
                               -- it with ~2px lag and no stutter
local SNAP_PX        = 48      -- pixel delta (3 tiles) beyond which we snap (warp)
local RESPAWN_COOLDOWN = 10    -- small debounce after a map change before respawn.
                               -- The client's gMain.callback2 field-active gate is
                               -- the real guard against writing mid-load, so this
                               -- only needs to be short — a long wait was the bulk
                               -- of the "ghost flicks out" gap when crossing maps
                               -- together (re-appears faster now).

-- Animation numbers (pret ANIM_STD_*): face S/N/W/E = 0/1/2/3 ; GO = 4/5/6/7.
-- facing convention 1=down 2=up 3=left 4=right.
local function idle_anim(f) return f - 1 end
local function walk_anim(f) return f + 3 end
local SPIN_FRAMES = 6   -- frames per facing while spinning the in-battle ghost (~0.4s/rotation)

-- ── small helpers ───────────────────────────────────────────────────────────
local function round(n) return math.floor(n + 0.5) end

local function player_tile()
    local b = cfg.obj_base
    return rs16(b + cfg.off_curr_x), rs16(b + cfg.off_curr_y)
end

-- Returns the local player's sprite slot + its on-screen pos1, or nil if the
-- player sprite isn't valid right now (e.g. mid-transition / non-overworld).
local function player_sprite()
    local sid = r8(cfg.obj_base + cfg.off_sprite_id)
    if sid >= 64 then return nil end
    local s = cfg.gsprites + sid * cfg.spr_stride
    return sid, rs16(s + cfg.spr_x), rs16(s + cfg.spr_y)
end

local function find_free_sprite()
    -- Scan HIGH→LOW and never return slot 0 (or the player's own sprite slot).
    -- The engine allocates the player + real map NPCs from the LOW indices, and
    -- during the battle⇄overworld teardown those low slots read transiently
    -- "free" (inUse cleared for a few frames).  Grabbing one — slot 0 was observed
    -- live — clones our ghost into the player's sprite, corrupting the player and
    -- leaving a phantom NPC.  Taking the highest free slot keeps us clear of the
    -- engine's allocation pool.
    local p_sid = r8(cfg.obj_base + cfg.off_sprite_id)
    for s = 63, 1, -1 do
        if s ~= p_sid
           and (r8(cfg.gsprites + s * cfg.spr_stride + cfg.spr_byte3e) & 0x01) == 0 then
            return s
        end
    end
    return nil
end

local function find_free_obj()
    for slot = 1, cfg.obj_count - 1 do
        if (r8(cfg.obj_base + slot * cfg.obj_stride + cfg.off_flags) & 0x01) == 0 then
            return slot
        end
    end
    return nil
end

-- Claim a FREE OBJ-VRAM tile block the engine won't hand to a real sprite.
-- The engine's AllocSpriteTiles fills from LOW indices, so we take the highest
-- free GHOST_TILE_COUNT-block not currently used by any active sprite.  This
-- avoids the fixed-tile collision (both player + ghost garbling after the
-- engine reallocated our old hardcoded region on a map change).
local function claim_free_tile()
    local used = {}
    for s = 0, 63 do
        local sa = cfg.gsprites + s * cfg.spr_stride
        if (r8(sa + cfg.spr_byte3e) & 0x01) ~= 0 then        -- inUse
            local t = r16(sa + 0x04) & 0x03FF                -- oam.tileNum
            for k = 0, GHOST_TILE_COUNT - 1 do used[t + k] = true end
        end
    end
    for base = TOTAL_OBJ_TILES - GHOST_TILE_COUNT, 0, -GHOST_TILE_COUNT do
        local ok = true
        for k = 0, GHOST_TILE_COUNT - 1 do
            if used[base + k] then ok = false; break end
        end
        if ok then return base end
    end
    return cfg.ghost_tile   -- fallback to the configured region
end

-- ── OBJ-VRAM tile reservation (gSpriteTileAllocBitmap) ────────────────────────
-- bit b == 1 ⟺ tile b is allocated; AllocSpriteTiles scans LOW→high for a free
-- run.  When cfg.tile_alloc_bitmap is known (RR 4.1 = 0x02017D9C) we RESERVE our
-- ghost's tiles by setting their bits, so the engine never hands them to a real
-- sprite → corruption fixed at the source.  ghost_tiles_collide() (below) stays
-- as a cheap backstop for profiles where the bitmap address is unknown.
--
-- SAFETY: the address could be wrong on an unverified profile, and writing bits
-- into unrelated EWRAM would corrupt the game.  bitmap_trusted() validates the
-- address every time before any write: the player's own tiles MUST read
-- allocated and a top tile MUST read free.  If either fails we disable
-- reservation (fall back to the self-heal) rather than risk a bad write.
local function bitmap_trusted()
    local bm = cfg.tile_alloc_bitmap
    if not bm then return false end
    local p_sid = r8(cfg.obj_base + cfg.off_sprite_id)
    if p_sid >= 64 then return false end
    local ptile = r16(cfg.gsprites + p_sid * cfg.spr_stride + 0x04) & 0x03FF
    local function bit(t) return (r8(bm + (t >> 3)) >> (t & 7)) & 1 end
    return bit(ptile) == 1 and bit(TOTAL_OBJ_TILES - 1) == 0
end

local function bitmap_set_range(tile, count, set)
    local bm = cfg.tile_alloc_bitmap
    for t = tile, tile + count - 1 do
        local a = bm + (t >> 3)
        local mask = 1 << (t & 7)
        if set then w8(a, r8(a) | mask) else w8(a, r8(a) & ((~mask) & 0xFF)) end
    end
end

-- Re-enabled: the corruption was PALETTE, not tiles (disabling reservation didn't
-- help), so the reservation stays on for proactive tile protection.  The leak it had
-- on connection crossings is fixed (free_reserved on map change, below).
local TILE_RESERVE_ENABLED = true

-- Reserve `newtile`'s block (freeing any previously-reserved block first).  No-op
-- if reservation is disabled or the bitmap address isn't trustworthy this frame.
local function reserve_tiles(newtile)
    if not TILE_RESERVE_ENABLED then return end
    if not bitmap_trusted() then reserved_tile = nil; return end
    if reserved_tile and reserved_tile ~= newtile then
        bitmap_set_range(reserved_tile, GHOST_TILE_COUNT, false)
    end
    bitmap_set_range(newtile, GHOST_TILE_COUNT, true)
    reserved_tile = newtile
end

-- Clear our reserved bits (same-map teardown / menu).  Clears exactly the bits we
-- set earlier, which is always safe.  NOT to be called on a map change — the
-- engine resets the whole bitmap on map load and the indices get reused by new
-- NPCs, so we must only drop the ref there (see the map-change handler).
local function free_reserved()
    if reserved_tile and cfg.tile_alloc_bitmap then
        bitmap_set_range(reserved_tile, GHOST_TILE_COUNT, false)
    end
    reserved_tile = nil
end

-- Does any OTHER active sprite's tile range overlap our claimed ghost tiles?
-- Backstop for when the alloc bitmap is unknown (reservation disabled): the
-- engine can still hand our tiles to a newly-spawned sprite (NPC entering view,
-- field effect, …) which fights our frame-DMA → garble.  Detecting overlap lets
-- us re-claim a fresh block on the fly.
local function ghost_tiles_collide()
    if not ghost_tile then return false end
    for s = 0, 63 do
        if s ~= sprslot then
            local sa = cfg.gsprites + s * cfg.spr_stride
            if (r8(sa + cfg.spr_byte3e) & 0x01) ~= 0 then
                local t = r16(sa + 0x04) & 0x03FF
                if t < ghost_tile + GHOST_TILE_COUNT and t + GHOST_TILE_COUNT > ghost_tile then
                    return true
                end
            end
        end
    end
    return false
end

-- ── partner's chosen trainer (override the cloned local-player look) ──────────────
-- RR custom trainers load dynamically, so we can't rebuild one from a graphicsId —
-- but the partner broadcasts its live sprite.images/anims ROM ptrs (identical on
-- both ROMs) + the palette ROM ptr.  We override the cloned ghost sprite with those:
-- images/anims directly, and the palette into a fresh OBJ slot via the EWRAM shadow
-- buffers (a direct palette-RAM write is overwritten each frame by the engine's
-- day/night transfer).  No-op when the partner sent no trainer info → keeps cloning
-- the local player (graceful fallback).

-- The shadow-buffer Faded OBJ slot-0 mirrors live OBJ palette RAM; validate that
-- before trusting the baked address (a wrong addr self-disables, no EWRAM scribbling).
local function pltt_trusted()
    if not (cfg.pltt_faded_obj and cfg.obj_pltt) then return false end
    return r16(cfg.pltt_faded_obj) == r16(cfg.obj_pltt)
end

-- Re-enabled: the palette corruption is fixed by giving the ghost its OWN palette
-- slot (GHOST_PAL_SLOT, see render) instead of a "free" slot that clobbered engine
-- palettes.  The partner-trainer palette loads into that SAME slot, per-frame, in
-- render — so it self-heals and never touches an engine-owned slot.
local TRAINER_RENDER_ENABLED = true

-- Override the cloned ghost sprite with the partner's chosen-trainer GRAPHICS only:
-- images/anims are ROM ptrs identical on both ROMs.  The PALETTE is loaded per-frame
-- in render into GHOST_PAL_SLOT (the ghost's own slot).  No-op when the partner sent
-- no trainer info → keeps cloning the local player (graceful fallback).
local function apply_trainer(naddr)
    if not TRAINER_RENDER_ENABLED then return end
    if not (ghost and ghost.imgs and ghost.imgs ~= 0 and cfg.spr_images) then return end
    -- One-shot diagnostic on each NEW foreign trainer: log the partner's ROM ptrs,
    -- the frame-0 byte SIZE the engine will DMA into our reserved tiles vs the local
    -- player's frame size + our reservation, and the palette source — to pinpoint
    -- whether the asymmetric "one player's ghost corrupts" is a tile-DMA OVERFLOW
    -- (foreign frame bigger than our 8-tile block) or a bad resolved palette.
    if ghost.imgs ~= applied_imgs then
        local function cls(a)
            if     a >= 0x08000000 and a < 0x0A000000 then return "ROM"
            elseif a >= 0x02000000 and a < 0x02040000 then return "EWRAM"
            elseif a >= 0x03000000 and a < 0x03008000 then return "IWRAM"
            elseif a >= 0x06000000 and a < 0x06018000 then return "VRAM"
            elseif a == 0 then return "0" else return "?" end
        end
        local p_sid = r8(cfg.obj_base + cfg.off_sprite_id)
        local p_imgs = (p_sid < 64) and r32(cfg.gsprites + p_sid * cfg.spr_stride + cfg.spr_images) or 0
        local g_sz = r16(ghost.imgs + 4)                       -- SpriteFrameImage.size (bytes)
        local p_sz = (p_imgs ~= 0) and r16(p_imgs + 4) or 0
        local gpal = ghost.pal or 0
        console.log(string.format(
            "[PG-TRAIN] foreign trainer: imgs=%08X(%s) anim=%08X(%s) | frame0 size ghost=0x%X local=0x%X (reserved=%d tiles) | pcol=%s | pcol[0..2]=%04X,%04X,%04X | pal(legacy)=%08X(%s)",
            ghost.imgs, cls(ghost.imgs), ghost.anim or 0, cls(ghost.anim or 0),
            g_sz, p_sz, GHOST_TILE_COUNT,
            ghost.pcols and "yes(live)" or "no(clone fallback)",
            ghost.pcols and ghost.pcols[0] or 0, ghost.pcols and ghost.pcols[1] or 0,
            ghost.pcols and ghost.pcols[2] or 0, gpal, cls(gpal)))
    end
    w32(naddr + cfg.spr_images, ghost.imgs)
    if ghost.anim and ghost.anim ~= 0 and cfg.spr_anims then w32(naddr + cfg.spr_anims, ghost.anim) end
    w8(naddr + cfg.spr_byte3f, r8(naddr + cfg.spr_byte3f) | 0x04)   -- animBeginning → re-DMA frame0
    last_anim = nil
    applied_imgs = ghost.imgs
end

-- ── spawn / despawn ───────────────────────────────────────────────────────────

-- Clone the player's trainer sprite into free slots; pin near the partner tile.
-- Returns true on success.  Does NOT touch any previously-held slots — callers
-- must despawn first when appropriate.
local function acquire()
    local p_sid = r8(cfg.obj_base + cfg.off_sprite_id)
    if p_sid >= 64 then return false end
    -- Only clone once the player's OWN sprite is fully set up (inUse).  During the
    -- battle→overworld teardown the player sprite is briefly torn down and low
    -- slots read "free"; cloning in that window is what produced the slot-0
    -- corruption.  Waiting for the player sprite guarantees the engine has rebuilt
    -- the overworld before we touch it.
    if (r8(cfg.gsprites + p_sid * cfg.spr_stride + cfg.spr_byte3e) & 0x01) == 0 then
        return false
    end
    local fs = find_free_sprite()
    local fo = find_free_obj()
    if not fs or not fo then return false end
    sprslot, objslot = fs, fo

    -- clone the player's gSprites entry → our free slot
    local paddr = cfg.gsprites + p_sid * cfg.spr_stride
    local naddr = cfg.gsprites + fs * cfg.spr_stride
    for i = 0, cfg.spr_stride - 1 do w8(naddr + i, r8(paddr + i)) end
    -- own VRAM tiles: claim a free high block so the engine never hands our
    -- tiles to a real sprite (the after-area-change corruption). oam.tileNum =
    -- low 10 bits of OAM attr2 (u16 @ sprite+0x04).
    ghost_tile = claim_free_tile()
    reserve_tiles(ghost_tile)   -- mark them allocated so AllocSpriteTiles skips them
    local attr2 = r16(naddr + 0x04)
    w16(naddr + 0x04, (attr2 & 0xFC00) | (ghost_tile & 0x03FF))
    w8(naddr + cfg.spr_byte3e, r8(naddr + cfg.spr_byte3e) | 0x01)   -- inUse
    w8(naddr + cfg.spr_byte3e, r8(naddr + cfg.spr_byte3e) & 0xFB)   -- invisible = 0
    ws16(naddr + cfg.spr_data0, fo)                                 -- data[0] = our objevent
    w8(naddr + cfg.spr_byte3f, r8(naddr + cfg.spr_byte3f) | 0x04)   -- animBeginning
    w8(naddr + cfg.spr_byte2c, r8(naddr + cfg.spr_byte2c) & 0xBF)   -- animPaused = 0
    applied_imgs = nil
    apply_trainer(naddr)   -- show the PARTNER's chosen trainer (no-op if not sent)

    -- backing object-event: pinned later each frame; init at the partner tile.
    local nobj = cfg.obj_base + fo * cfg.obj_stride
    local gx, gy = ghost.x, ghost.y
    for i = 0, cfg.obj_stride - 1 do w8(nobj + i, 0) end
    w8(nobj + cfg.off_flags, 0x01)
    w8(nobj + cfg.off_sprite_id, fs)
    w8(nobj + cfg.off_graphics_id, r8(cfg.obj_base + cfg.off_graphics_id))
    w8(nobj + cfg.off_mov_type, 0x00)                               -- NONE
    w8(nobj + cfg.off_local_id, 0xFD)
    w8(nobj + cfg.off_map_num, ghost.mn)
    w8(nobj + cfg.off_map_group, ghost.mg)
    ws16(nobj + cfg.off_curr_x, gx)
    ws16(nobj + cfg.off_curr_y, gy)
    ws16(nobj + cfg.off_prev_x, gx)
    ws16(nobj + cfg.off_prev_y, gy)

    last_anim = nil
    return true
end

-- safe=true  → deactivate our slots (only valid on the SAME map we acquired on)
-- safe=false → just forget refs WITHOUT writing (map changed; indices reused)
local function despawn(safe)
    if safe then
        if objslot then w8(cfg.obj_base + objslot * cfg.obj_stride + cfg.off_flags, 0x00) end
        if sprslot then
            local b = cfg.gsprites + sprslot * cfg.spr_stride + cfg.spr_byte3e
            w8(b, r8(b) & 0xFE)   -- clear inUse
        end
        free_reserved()           -- give our OBJ-VRAM tiles back to the allocator
        applied_imgs = nil
    else
        -- Map change.  FREE our reserved bits rather than abandoning them: a WARP
        -- already cleared them (suspend() ran during the fade → reserved_tile nil →
        -- no-op here), but a SEAMLESS CONNECTION CROSSING does NOT reset the alloc
        -- bitmap, so abandoning the ref LEAKS one 8-tile reservation per crossing.
        -- Those leaks accumulate until AllocSpriteTiles can't find a free run and a
        -- real sprite lands on garbage tiles (the "corrupts after several area
        -- transitions").  Our tiles are HIGH and new-map sprites allocate LOW, so
        -- clearing high bits never un-reserves a freshly-spawned sprite.
        free_reserved()
        applied_imgs = nil
    end
    objslot, sprslot = nil, nil
    last_anim = nil
end

local function spawned() return objslot ~= nil and sprslot ~= nil end

local function slot_valid()
    if not spawned() then return false end
    local nsa  = cfg.gsprites + sprslot * cfg.spr_stride
    local nobj = cfg.obj_base + objslot * cfg.obj_stride
    return (r8(nsa + cfg.spr_byte3e) & 0x01) ~= 0
       and (r8(nobj + cfg.off_flags) & 0x01) ~= 0
end

-- ── public API ────────────────────────────────────────────────────────────────

function PG.init(c)
    cfg = c
    ghost = nil
    objslot, sprslot = nil, nil
    disp_x, disp_y = nil, nil
    last_map_g, last_map_n = -1, -1
    cooldown, last_anim = 0, nil
    ghost_tile, reserved_tile = nil, nil
    applied_imgs = nil
    spin_tick = 0
end

function PG.on_ghost_pos(cmd)
    if not cfg then return end
    local g = {
        mg = cmd.mg, mn = cmd.mn,
        x  = cmd.x,  y  = cmd.y,
        f  = (cmd.f and cmd.f >= 1 and cmd.f <= 4) and cmd.f or 1,
        mv = cmd.mv == 1 and 1 or 0,
        -- partner's live animNum (walk/run) for 1:1 motion; only trusted while
        -- moving and within the on-foot anim range (else fall back to walk).
        an = (cmd.an and cmd.an >= 0 and cmd.an <= 23) and cmd.an or nil,
        bt = cmd.bt == 1 and 1 or 0,   -- partner is in a battle → freeze + spin
        -- partner's chosen-trainer graphics (ROM ptrs + palette ROM ptr); nil/0 =
        -- unknown → clone the local player (graceful fallback).
        imgs = cmd.imgs, anim = cmd.anim, pal = cmd.pal,
    }
    -- Decode the partner's AUTHORITATIVE live trainer palette (64 hex chars → 16
    -- BGR555 colours) ONCE per update.  This is the correct fix for RR's dynamically
    -- loaded custom-trainer skins, where the tag-resolved `pal` ROM ptr is wrong.
    -- nil = no palette sent → render keeps the local-player palette (clone).
    if cmd.pcol and #cmd.pcol >= 64 then
        local cols = {}
        for i = 0, 15 do
            cols[i] = tonumber(cmd.pcol:sub(i * 4 + 1, i * 4 + 4), 16) or 0
        end
        g.pcols = cols
    end
    -- Snap the interpolation target on first sight or a big jump (warp/fly).
    if not ghost or ghost.mg ~= g.mg or ghost.mn ~= g.mn
       or not disp_x
       or math.abs(g.x - disp_x) > SNAP_PX or math.abs(g.y - disp_y) > SNAP_PX then
        disp_x, disp_y = g.x, g.y
    end
    ghost = g
end

function PG.on_ghost_clear()
    ghost = nil
    -- actual slot teardown happens in on_frame (knows if same-map safe).
end

function PG.reset()
    if cfg and spawned() then despawn(true) end
    ghost = nil
    disp_x, disp_y = nil, nil
    last_anim = nil
end

-- Call when NOT in the overworld (battle/menu/transition).  Clears our injected
-- slot once and stops all writes, so we never touch gObjectEvents/gSprites while
-- the engine is using them for battle sprites (which crashed the game) or while
-- tile allocation is churning (which corrupted sprites).  Keeps `ghost` data so
-- we re-render on return to the overworld.
function PG.suspend()
    if not cfg then return end
    -- Leaving the overworld (battle / menu / transition).  The engine repurposes
    -- gSprites for battle sprites, so writing into our sprite slot here corrupts
    -- battle state and CRASHED the game (observed on both entering and running
    -- from a battle).  So we must NOT touch gSprites in suspend.
    --
    -- But our backing object-event lives in gObjectEvents — overworld-only logical
    -- state the battle engine never touches.  If we leave it active, the engine
    -- spawns a real sprite for it on the way back to the overworld → a phantom
    -- "bad NPC" stuck on the map (observed after running from a battle).  So clear
    -- ONLY the object-event's active flag (a safe EWRAM byte write), forget both
    -- slot refs, and re-acquire cleanly once we're back in a settled overworld
    -- (the client also gates re-entry on post_battle_frames == 0).
    if objslot then
        w8(cfg.obj_base + objslot * cfg.obj_stride + cfg.off_flags, 0x00)
    end
    -- Remember our sprite slot so we can clear its inUse once the field is active
    -- again (clearing it now is unsafe — gSprites is repurposed for the menu/
    -- battle).  Without this it lingers as an orphan ghost after closing a menu.
    if sprslot then stale_sprslot = sprslot end
    free_reserved()               -- release our OBJ-VRAM tiles (safe: clears only our bits)
    objslot, sprslot = nil, nil
    last_anim = nil
    base_cx, base_cy = nil, nil   -- re-calibrate the camera baseline on return
end

-- Called at FRAME START (before the engine processes this frame's input).  With
-- the backing object-event sitting on the partner's tile for collision, pressing A
-- while facing it triggers the engine's interaction → a localId-0xFD lookup hits a
-- null map template → garbage script → SOFTLOCK.  Until we give it a real script
-- (the conversation dialogue), suppress it: if the player is facing the ghost's
-- tile AND A is pressed this frame, deactivate our object-event so the engine finds
-- nothing to interact with.  on_frame re-activates it at frame end, so collision is
-- intact every frame except the one where A is pressed (A doesn't move you → no
-- clip).  a_pressed is the emulated A-button state for the upcoming frame.
function PG.guard_interaction(a_pressed)
    if not cfg or not a_pressed or not ghost then return end
    if not spawned() or not slot_valid() then return end
    local px, py = player_tile()
    local f = r8(cfg.obj_base + cfg.off_facing) & 0x0F   -- 1=down 2=up 3=left 4=right
    local fx, fy = px, py
    if     f == 1 then fy = py + 1
    elseif f == 2 then fy = py - 1
    elseif f == 3 then fx = px - 1
    elseif f == 4 then fx = px + 1 end
    if fx == round(ghost.x / cfg.tile_px) and fy == round(ghost.y / cfg.tile_px) then
        local oa = cfg.obj_base + objslot * cfg.obj_stride
        w8(oa + cfg.off_flags, r8(oa + cfg.off_flags) & 0xFE)   -- deactivate for this frame
    end
end

function PG.on_frame()
    if not cfg then return end

    -- on_frame only runs when the field is active+settled (the client gates it),
    -- so gSprites is safe to write now.  Clear any sprite slot a prior suspend
    -- (menu/battle) left behind — it couldn't be cleared then (gSprites was
    -- repurposed) and would otherwise linger as an orphan ghost after a menu.
    -- Our slots are HIGH (top-down alloc) so this never clobbers a low field NPC.
    if stale_sprslot then
        local b = cfg.gsprites + stale_sprslot * cfg.spr_stride + cfg.spr_byte3e
        w8(b, r8(b) & 0xFE)   -- clear inUse → engine stops drawing the orphan
        stale_sprslot = nil
    end

    local mg, mn = cfg.get_map()

    -- Map change: the engine may have rebuilt gObjectEvents/gSprites, and even a
    -- seamless connection crossing clobbers the VRAM tiles our kept sprite points
    -- at.  ALWAYS tear down + re-acquire on the new map (keeping the slot across a
    -- crossing rendered the player AND ghost as garbage — reverted).  Forget refs
    -- WITHOUT writing the object-event into a reused low slot (guard by 0xFD).
    if mg ~= last_map_g or mn ~= last_map_n then
        last_map_g, last_map_n = mg, mn
        if sprslot then
            local b = cfg.gsprites + sprslot * cfg.spr_stride + cfg.spr_byte3e
            w8(b, r8(b) & 0xFE)
        end
        if objslot then
            local oa = cfg.obj_base + objslot * cfg.obj_stride
            if r8(oa + cfg.off_local_id) == 0xFD then
                w8(oa + cfg.off_flags, 0x00)
            end
        end
        objslot, sprslot = nil, nil
        -- FREE our reserved tile bits (don't abandon them): a warp already cleared
        -- them (suspend ran → no-op), but a seamless connection crossing does NOT
        -- reset the alloc bitmap, so abandoning leaks one reservation per crossing →
        -- the bitmap fills → AllocSpriteTiles fails → real sprites get garbage tiles
        -- (the corruption after several area transitions).  High bits, new sprites
        -- are low → safe to clear.
        free_reserved()
        applied_imgs = nil
        last_anim = nil
        base_cx, base_cy = nil, nil
        cooldown = RESPAWN_COOLDOWN
        return
    end
    if cooldown > 0 then cooldown = cooldown - 1; return end

    -- Nothing to show?  (cleared, stale-dropped by server, or never set.)
    if not ghost then
        if spawned() then despawn(true) end
        return
    end

    -- Partner on a different map → no ghost here.
    if ghost.mg ~= mg or ghost.mn ~= mn then
        if spawned() then despawn(true) end
        return
    end

    local px, py = player_tile()
    -- Off-screen test (same map, outside the viewport).  We no longer despawn when
    -- off-screen: tearing the slot down and re-acquiring on every screen exit/entry
    -- churned slots and risked grabbing a reserved low slot during a fragile frame
    -- (the corruption-when-partner-walks-off-screen report).  Instead we keep the
    -- slot, hide the sprite via its invisible bit (below), and pin the backing
    -- object-event to the LOCAL PLAYER's tile so the engine's off-screen cull never
    -- fires.  ghost.x/y are WORLD PIXELS → /16 to compare tiles.
    local off_screen = math.abs(ghost.x / 16 - px) > VIEW_X
                    or math.abs(ghost.y / 16 - py) > VIEW_Y

    -- Ensure we have valid slots (acquire / re-acquire after an engine reclaim).
    if not slot_valid() then
        if spawned() then despawn(true) end
        if not acquire() then cooldown = RESPAWN_COOLDOWN; return end
    end

    -- Interpolate the display position (WORLD PIXELS) toward the partner's
    -- smooth sub-pixel position.  The target is already smooth (sender derives
    -- it from coordOffset), so a light ease tracks it closely with no stutter;
    -- snap on a big gap (warp/fly/resync).
    local function approach(cur, tgt)
        if math.abs(tgt - cur) >= SNAP_PX then return tgt end
        return cur + (tgt - cur) * GHOST_LERP
    end
    disp_x = approach(disp_x, ghost.x)
    disp_y = approach(disp_y, ghost.y)

    local p_sid, psx, psy = player_sprite()
    if not p_sid then return end   -- player sprite not valid this frame; skip draw

    local nsa  = cfg.gsprites + sprslot * cfg.spr_stride
    local nobj = cfg.obj_base + objslot * cfg.obj_stride

    -- Re-apply the partner's trainer graphics if it changed since we last applied
    -- (they picked a different avatar mid-session) — acquire() applies on first spawn.
    if ghost.imgs ~= applied_imgs then apply_trainer(nsa) end

    -- Backing object-event placement = COLLISION tile.
    --   • On-screen: put it on the PARTNER's actual tile so you physically BUMP into
    --     each other (the ghost IS the other player).  Match the player's elevation
    --     so the engine registers the collision (mismatched elevations pass through).
    --   • Off-screen: pin to the LOCAL PLAYER's tile so RemoveObjectEventIfOutsideView
    --     never culls our slot (nothing to collide with off-screen anyway, and the
    --     sprite is hidden below).
    -- The sprite renders at the partner's position via pos1 below regardless.
    -- NOTE: with the object-event on the partner's faced tile, pressing A toward the
    -- ghost now triggers the engine's interaction (localId 0xFD, zeroed script).  We
    -- are TESTING whether that's a safe no-op; if it warps/crashes we neutralize it.
    local gtx = round(ghost.x / cfg.tile_px)
    local gty = round(ghost.y / cfg.tile_px)
    local ctx, cty = px, py
    if not off_screen then ctx, cty = gtx, gty end
    w8(nobj + cfg.off_flags, r8(nobj + cfg.off_flags) | 0x01)
    w8(nobj + cfg.off_elevation, r8(cfg.obj_base + cfg.off_elevation))  -- match player elevation
    ws16(nobj + cfg.off_curr_x, ctx); ws16(nobj + cfg.off_curr_y, cty)
    ws16(nobj + cfg.off_prev_x, ctx); ws16(nobj + cfg.off_prev_y, cty)

    -- inUse + coordOffset on; hide the sprite when off-screen.  Rendering a sprite
    -- far outside the viewport risks OAM coordinate wrap-around (9-bit X / 8-bit Y)
    -- drawing the ghost as garbage at the opposite screen edge — toggling the
    -- invisible bit keeps the slot stable (no churn) while hiding it cleanly.
    -- Partner-in-battle: keep the ghost FROZEN in place, simply VISIBLE.  (A blink
    -- "wink" indicator was tried but wasn't legible in-game, so it's disabled for
    -- now — just not vanishing is the win.  A clearer in-world indicator, e.g. a
    -- mon sprite walking in front, is a separate exploration.)  ghost.bt is still
    -- carried end-to-end and freezes the ghost; only the blink is gone.
    local in_battle = (ghost.bt == 1)                              -- freeze (idle anim) below
    local b3e = r8(nsa + cfg.spr_byte3e) | 0x01 | 0x02             -- inUse + coordOffset
    local hide = off_screen
    if hide then b3e = b3e | 0x04 else b3e = b3e & 0xFB end         -- 0x04 = invisible
    w8(nsa + cfg.spr_byte3e, b3e)

    -- Self-heal VRAM-tile collisions: if the engine put another sprite on our
    -- tiles, re-claim a fresh free block and force a frame re-DMA into it.  Fixes
    -- the "random corruption until area change" without needing the alloc bitmap.
    if ghost_tiles_collide() then
        ghost_tile = claim_free_tile()
        reserve_tiles(ghost_tile)   -- reserve the fresh block (frees the old one)
        w8(nsa + cfg.spr_byte3f, r8(nsa + cfg.spr_byte3f) | 0x04)   -- animBeginning → re-DMA
        last_anim = nil
    end
    -- Keep our claimed tiles, AND re-sync the OBJ palette slot every frame.  The
    -- ghost cloned the player's oam.paletteNum once, but the engine reassigns OBJ
    -- palette slots as NPCs come and go and doesn't know our injected ghost is using
    -- one — so the cloned slot goes stale and the ghost renders an NPC's colours
    -- ("correct sprite, wrong colours").  The PLAYER's slot is engine-protected
    -- (always active), so following it each frame keeps the ghost's colours correct.
    -- (Only while we're NOT painting a partner-trainer palette — applied_imgs nil.)
    -- Give the ghost its OWN OBJ palette slot (a per-frame copy of the player's
    -- palette) instead of SHARING the player's slot.  Sharing slot 0 desynced the
    -- engine's palette ref-counting → it freed/reused slot 0 → BOTH player and ghost
    -- corrupted ("NPC colours", confirmed: gPal==pPal==slot0 with changing data).  On
    -- our own high slot the engine never frees the player's slot because of us → the
    -- player stays correct, and we keep the ghost correct by copying the player's
    -- palette (all three buffers, so no double day/night tint) into our slot each
    -- frame.  (A RESERVED slot via the engine's palette-tag table would also stop an
    -- NPC ever reusing slot 15, but that table isn't located; a high slot is rarely
    -- contested.)  When a partner-trainer palette is loaded (applied_imgs ~= nil) we
    -- keep that instead of copying the player's.
    -- Load the ghost's palette into its OWN slot (GHOST_PAL_SLOT) every frame so it
    -- never shares/desyncs the player's engine-managed slot AND self-heals if an NPC
    -- briefly reuses our high slot.  Source, in priority order:
    --   1. the partner's AUTHORITATIVE live trainer palette (ghost.pcols — the 16
    --      colours actually loaded for their chosen skin; correct for ALL skins incl.
    --      RR's dynamic custom trainers, where the old tag-resolved ROM ptr was wrong);
    --   2. else a copy of the LOCAL player's live palette (clone fallback — no trainer
    --      info sent, or older sender).
    -- All three buffers (Unfaded + Faded + live PLTT) so the day/night tint isn't doubled.
    local pal_bits
    if pltt_trusted() then
        if applied_imgs ~= nil and ghost.pcols then
            -- The partner sent UNTINTED colours (the unfaded master).  Writing them
            -- raw into the FADED/PLTT buffers left the ghost untinted → too-bright /
            -- wrong colours at dusk/night/in caves (the clone path below tints because
            -- it copies the player's already-tinted FADED buffer).  Derive the engine's
            -- current per-channel day/night tint from the PLAYER's own slot (the tint
            -- is a uniform multiplier across the whole OBJ palette this frame: faded =
            -- tint·unfaded) and apply it to pcol so the ghost tints like every other
            -- sprite.  At neutral tint (daytime) the ratio is ~1 → colours unchanged.
            local psrc = (r16(cfg.gsprites + p_sid * cfg.spr_stride + 0x04) >> 12) & 0x0F
            local rn, gn, bn, rd, gd, bd = 0, 0, 0, 0, 0, 0
            for i = 0, 15 do
                local uf = r16(cfg.pltt_unfaded_obj + psrc*0x20 + i*2)
                local fd = r16(cfg.pltt_faded_obj   + psrc*0x20 + i*2)
                rd = rd + (uf & 0x1F);          rn = rn + (fd & 0x1F)
                gd = gd + ((uf >> 5) & 0x1F);   gn = gn + ((fd >> 5) & 0x1F)
                bd = bd + ((uf >> 10) & 0x1F);  bn = bn + ((fd >> 10) & 0x1F)
            end
            for i = 0, 15 do
                local off = i * 2
                local c = ghost.pcols[i]
                local r, g, b = (c & 0x1F), ((c >> 5) & 0x1F), ((c >> 10) & 0x1F)
                if rd > 0 then r = math.floor(r * rn / rd + 0.5); if r > 31 then r = 31 end end
                if gd > 0 then g = math.floor(g * gn / gd + 0.5); if g > 31 then g = 31 end end
                if bd > 0 then b = math.floor(b * bn / bd + 0.5); if b > 31 then b = 31 end end
                local tc = r | (g << 5) | (b << 10)
                w16(cfg.pltt_unfaded_obj + GHOST_PAL_SLOT*0x20 + off, c)    -- untinted master
                w16(cfg.pltt_faded_obj   + GHOST_PAL_SLOT*0x20 + off, tc)   -- engine-matched tint (shown)
                w16(cfg.obj_pltt         + GHOST_PAL_SLOT*0x20 + off, tc)
            end
        else
            local psrc = (r16(cfg.gsprites + p_sid * cfg.spr_stride + 0x04) >> 12) & 0x0F
            for i = 0, 15 do
                local off = i * 2
                w16(cfg.pltt_unfaded_obj + GHOST_PAL_SLOT*0x20 + off, r16(cfg.pltt_unfaded_obj + psrc*0x20 + off))
                w16(cfg.pltt_faded_obj   + GHOST_PAL_SLOT*0x20 + off, r16(cfg.pltt_faded_obj   + psrc*0x20 + off))
                w16(cfg.obj_pltt         + GHOST_PAL_SLOT*0x20 + off, r16(cfg.obj_pltt         + psrc*0x20 + off))
            end
        end
        pal_bits = GHOST_PAL_SLOT << 12
    else
        pal_bits = r16(nsa + 0x04) & 0xF000   -- untrusted palette addr → keep current
    end
    local attr2 = r16(nsa + 0x04)
    w16(nsa + 0x04, pal_bits | (attr2 & 0x0C00) | ((ghost_tile or cfg.ghost_tile) & 0x03FF))

    -- Position: MAP-FIXED, exactly like the engine renders a real NPC.
    -- DATA-CONFIRMED relationship: playerSprite.pos1 + gSpriteCoordOffset =
    -- screen centre (120,72) — i.e. sprites are coordOffset-enabled and pos1 is
    -- map-relative.  So a sprite at world tile T has pos1 = T*16 + C, where
    -- C = playerSprite.pos1 - playerTile*16 (a per-map constant).  We cache C
    -- while the player is IDLE (then psx is exact for px; mid-step psx carries a
    -- sub-tile offset), set ghost.pos1 = partnerTile*16 + C, and let the engine's
    -- coordOffset scroll it smoothly.  Result: in-sync AND smooth, no local-tile
    -- lurch, no drift, no separate NPC needed.
    -- base C = playerSprite.pos1 - playerWorldPx (= map pixel origin offset),
    -- calibrated while the LOCAL player is idle (then px*16 is the player's exact
    -- world pixel).  A sprite at world pixel W has pos1 = W + C, so
    -- ghost.pos1 = partnerWorldPx (disp) + C.  coordOffset (enabled above) scrolls
    -- it smoothly.  disp_x/y are WORLD PIXELS now.
    local p_idle = (r8(cfg.obj_base + cfg.off_flags) & 0x80) ~= 0
    if p_idle or base_cx == nil then
        base_cx = psx - px * cfg.tile_px
        base_cy = psy - py * cfg.tile_px
    end
    local gx_pos1 = round(disp_x + base_cx)
    local gy_pos1 = round(disp_y + base_cy)
    ws16(nsa + cfg.spr_x, gx_pos1)
    ws16(nsa + cfg.spr_y, gy_pos1)

    -- Throttled diagnostic so we debug with real numbers, not guesses.
    dbg_frames = dbg_frames + 1
    if dbg_frames % 120 == 0 then
        local p_sid_dbg = r8(cfg.obj_base + cfg.off_sprite_id)
        local p_tile = (p_sid_dbg < 64)
            and (r16(cfg.gsprites + p_sid_dbg * cfg.spr_stride + 0x04) & 0x03FF) or -1
        local coffx = cfg.coff_x and rs16(cfg.coff_x) or 0
        local coffy = cfg.coff_y and rs16(cfg.coff_y) or 0
        -- Read back our ghost's ACTUAL oam.tileNum: if it differs from what we
        -- claimed (ghost_tile), the engine reallocated our tiles → corruption.
        local actual_gtile = (r16(nsa + 0x04) & 0x03FF)
        -- Palette: ghost vs player slot + each slot's colour 1 (colour 0 is usually
        -- transparent).  If gPal slot == pPal slot but colours differ, something is
        -- wrong with the read; if the colours are an NPC's, the slot data was clobbered.
        local g_palslot = (r16(nsa + 0x04) >> 12) & 0x0F
        local p_palslot = (p_sid_dbg < 64) and ((r16(cfg.gsprites + p_sid_dbg * cfg.spr_stride + 0x04) >> 12) & 0x0F) or -1
        local pltt = cfg.obj_pltt or 0x05000200
        local g_c1 = r16(pltt + g_palslot * 0x20 + 2)
        local p_c1 = (p_palslot >= 0) and r16(pltt + p_palslot * 0x20 + 2) or 0
        console.log(string.format(
            "[PG-DBG] playerTile=(%d,%d) spr=(%d,%d) pTileNum=%d | partnerPx=(%d,%d) disp=(%.0f,%.0f) | ghost pos1=(%d,%d) screen=(%d,%d) C=(%d,%d) slot=%d claimedTile=%d actualTile=%d coff=(%d,%d) | gPal=%d:%04X pPal=%d:%04X",
            px, py, psx, psy, p_tile,
            ghost.x, ghost.y, disp_x, disp_y,
            gx_pos1, gy_pos1, gx_pos1 + coffx, gy_pos1 + coffy,
            base_cx or 0, base_cy or 0, sprslot or -1, ghost_tile or -1, actual_gtile,
            coffx, coffy, g_palslot, g_c1, p_palslot, p_c1))
    end

    -- Animation: while moving, mirror the partner's live animNum (walk/run 1:1);
    -- fall back to a directional walk if no valid animNum was sent.  When idle,
    -- a single-frame face anim so the ghost stands.
    local want
    if in_battle then
        -- IN-BATTLE INDICATOR: spin the trainer in place — cycle the facing every
        -- SPIN_FRAMES frames through the four face anims (0..3 = S/N/W/E).  A
        -- stationary trainer rotating in place is an unmistakable, in-engine
        -- "they're busy / in a battle" cue — no overlay, no second sprite, and it
        -- reuses the same animNum writes we already do safely.
        spin_tick = spin_tick + 1
        want = (spin_tick // SPIN_FRAMES) % 4
        -- DIAGNOSTIC (issue 2): capture the ghost's palette state DURING the spin so
        -- we can see if the engine is overriding our slot-15 colours / paletteNum as
        -- the frequent animBeginning re-asserts the backing object-event's graphics
        -- palette.  Only meaningful with DIFFERENT trainers on each side.
        if dbg_frames % 30 == 0 then
            local pltt = cfg.obj_pltt or 0x05000200
            local gslot = (r16(nsa + 0x04) >> 12) & 0x0F
            console.log(string.format(
                "[PG-BATPAL] spin: ghost palSlot=%d slot15 c0,1,2=%04X,%04X,%04X | applied=%s pcols=%s c0,1,2=%04X,%04X,%04X",
                gslot,
                r16(pltt + GHOST_PAL_SLOT*0x20), r16(pltt + GHOST_PAL_SLOT*0x20 + 2), r16(pltt + GHOST_PAL_SLOT*0x20 + 4),
                applied_imgs and "trainer" or "clone", ghost.pcols and "yes" or "no",
                ghost.pcols and ghost.pcols[0] or 0, ghost.pcols and ghost.pcols[1] or 0,
                ghost.pcols and ghost.pcols[2] or 0))
        end
    elseif ghost.mv == 1 then
        want = ghost.an or walk_anim(ghost.f)
    else
        want = idle_anim(ghost.f)
    end
    if want ~= last_anim then
        w8(nsa + cfg.spr_anim, want)
        w8(nsa + cfg.spr_byte3f, r8(nsa + cfg.spr_byte3f) | 0x04)    -- animBeginning
        w8(nsa + cfg.spr_byte2c, r8(nsa + cfg.spr_byte2c) & 0xBF)    -- animPaused = 0
        last_anim = want
    end
end

return PG
