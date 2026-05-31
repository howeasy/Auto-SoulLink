--[[
  lua/tests/test_ghost_phase2_discovery.lua  —  Peer-ghost PHASE 2 discovery
  =========================================================================
  Two NEW discoveries the peer-ghost feature wants, building on the confirmed
  Phase-0 addresses (gObjectEvents, gSprites, gSpriteTileAllocBitmap):

    (A) MON OVERWORLD GRAPHICS — find gObjectEventGraphicsInfoPointers (the ROM
        table of per-graphicsId ObjectEventGraphicsInfo), identify the mon
        overworld-sprite graphicsId range, and PROVE we can render a mon sprite
        (clone our ghost slot but point it at a mon's images/anims/oam).  Goal:
        a partner's lead Pokémon walking in front of them as a battle indicator.

    (B) ROUTE↔ROUTE TRANSITION — when two players cross a connected-map border
        together the ghost "flicks out".  This probe spawns a tracked sprite and
        logs, every frame across a crossing, whether our gSprites slot SURVIVES
        the crossing (→ we can keep the ghost, just recalibrate) or the engine
        wipes/reuses it (→ a gap is unavoidable and we re-acquire faster).

  CONFIRMED constants reused (RR 4.1 — see reference_rr_object_events memory):
    gObjectEvents 0x02036E38 /24 ·  gSprites 0x0202063C /0x44 ·
    gSpriteTileAllocBitmap 0x02017D9C ·  coordOffset 0x02021BC8/0x02021BCA.

  HOW TO RUN
    1. Load Radical Red 4.1 in BizHawk, be in the OVERWORLD.
    2. Lua Console → load this script.  Auto-discovery (table find) runs on load.
    3. F1 — (re)find gObjectEventGraphicsInfoPointers + confirm vs the player.
    4. F2 — scan the table for MON-like entries + dump TARGET_GFX's struct.
    5. F5 / F6 — TARGET_GFX − / +  (browse graphicsIds; then F2 to dump / F3 to render).
    6. F3 — SPAWN-RENDER TARGET_GFX one tile below the player (mon-in-front PoC).
            Press again to clear.
    7. F4 — toggle the ROUTE-CROSSING tracker, then walk across a route border.

  OUTPUT → <results-dir>/ghost_phase2_results.txt
--]]

local fmt = string.format
local r8, r16, r32 = memory.read_u8, memory.read_u16_le, memory.read_u32_le
local rs16 = memory.read_s16_le
local w8, w16, w32 = memory.write_u8, memory.write_u16_le, memory.write_u32_le
local ws16 = memory.write_s16_le
local function hex(n) return fmt("0x%08X", n) end

-- ── output file ───────────────────────────────────────────────────────────────
local _lines = {}
local OUT_PATH
local function _try(p) local ok,f = pcall(io.open,p,"w"); if ok and f then f:write(""); f:close(); return true end; return false end
do
    local cands = {}
    local ok, info = pcall(debug.getinfo, 1, "S")
    if ok and info and info.source then
        local dir = info.source:match("^@?(.*[\\/])")
        if dir then cands[#cands+1] = dir .. "ghost_phase2_results.txt" end
    end
    cands[#cands+1] = "ghost_phase2_results.txt"
    for _, p in ipairs(cands) do if _try(p) then OUT_PATH = p; break end end
end
local function log(s) _lines[#_lines+1] = s end
local function con(s) console.log(s) end
local function flush()
    if not OUT_PATH then return end
    local ok, f = pcall(io.open, OUT_PATH, "w")
    if ok and f then f:write(table.concat(_lines, "\n")); f:write("\n"); f:close() end
end

-- ── confirmed constants ─────────────────────────────────────────────────────────
local OBJ_BASE   = 0x02036E38
local OBJ_STRIDE = 0x24
local OBJ_COUNT  = 16
local OFF_FLAGS, OFF_SPR_ID, OFF_GFX_ID = 0x00, 0x04, 0x05
local OFF_MOV_TYPE, OFF_LOCAL_ID, OFF_MAP_N, OFF_MAP_G = 0x06, 0x08, 0x09, 0x0A
local OFF_CURX, OFF_CURY, OFF_PREVX, OFF_PREVY = 0x10, 0x12, 0x14, 0x16
local OFF_FACING = 0x18

local GSPR_BASE   = 0x0202063C
local GSPR_STRIDE = 0x44
local SPR_OAM0, SPR_OAM1, SPR_OAM2 = 0x00, 0x02, 0x04      -- attr0/1/2 (u16)
local SPR_ANIMS, SPR_IMAGES, SPR_CALLBACK = 0x08, 0x0C, 0x1C
local SPR_X, SPR_Y, SPR_ANIMNUM = 0x20, 0x22, 0x2A
local SPR_BYTE2C, SPR_DATA0, SPR_BYTE3E, SPR_BYTE3F = 0x2C, 0x2E, 0x3E, 0x3F

local TILE_BITMAP = 0x02017D9C
local COFF_X, COFF_Y = 0x02021BC8, 0x02021BCA
local OBJ_VRAM0 = 0x06010000
local TILE_4BPP = 32
local TOTAL_OBJ_TILES = 1024

-- ObjectEventGraphicsInfo field offsets (pret vanilla; we CONFIRM images offset by
-- correlation in case CFRU/DPE shifted the struct).
local GI_TILETAG, GI_PALTAG1, GI_SIZE = 0x00, 0x02, 0x06
local GI_WIDTH, GI_HEIGHT, GI_PALSLOT = 0x08, 0x0A, 0x0C
local GI_OAM, GI_ANIMS, GI_IMAGES = 0x10, 0x18, 0x1C
local GI_IMAGES_CANDIDATES = { 0x1C, 0x20, 0x24, 0x28, 0x2C }   -- handle CFRU/DPE struct drift

local function in_rom(p)  return p >= 0x08000000 and p < 0x0A000000 end
local function in_ewram(p) return p >= 0x02000000 and p < 0x02040000 end

-- Live current map = gSaveBlock1Ptr → sb1+0x04 (group) / +0x05 (num).  (The
-- player OBJECT-EVENT's mapNum/mapGroup is the map it SPAWNED on and does NOT
-- update on a connection crossing — using it is why the F4 verdict never fired.)
local SB1_PTR = 0x03005008   -- gSaveBlock1Ptr (RR 4.1, radical_red profile)
local function get_map()
    local sb1 = r32(SB1_PTR)
    if not in_ewram(sb1) then return 0, 0 end
    return r8(sb1 + 0x04), r8(sb1 + 0x05)
end

-- ── discovered / tunable state ───────────────────────────────────────────────────
local GFX_TABLE   = nil      -- gObjectEventGraphicsInfoPointers base (ROM)
local GI_IMG_OFF  = GI_IMAGES
local TARGET_GFX  = 0        -- graphicsId to dump / render (browse with F5/F6)
local MON_RANGE_LO, MON_RANGE_HI = nil, nil

-- ── helpers ──────────────────────────────────────────────────────────────────────
local function player_sprite_id() return r8(OBJ_BASE + OFF_SPR_ID) end
local function gi_ptr(gfx)
    if not GFX_TABLE then return nil end
    local p = r32(GFX_TABLE + gfx * 4)
    return in_rom(p) and p or nil
end
-- OAM (shape,size) → tile count.
local OAM_DIMS = { [0]={{1,1},{2,2},{4,4},{8,8}}, [1]={{2,1},{4,1},{4,2},{8,4}}, [2]={{1,2},{1,4},{2,4},{4,8}} }
local function oam_tile_count(attr0, attr1)
    local shape = (attr0 >> 14) & 3
    local size  = (attr1 >> 14) & 3
    local row = OAM_DIMS[shape]; if not row then return 4 end
    local d = row[size+1]; return d[1]*d[2]
end

-- ── (A) FIND gObjectEventGraphicsInfoPointers ─────────────────────────────────────
-- Correlate against ACTIVE object-events: gObjectEventGraphicsInfoPointers[gfx]
-- points to a struct whose images ptr == that object's sprite's live images ptr.
-- We collect every active object (player + NPCs) as an anchor, scan the FULL ROM
-- (RR 4.1 = 32 MB; CFRU relocates tables high, so the old 16 MB cap missed it),
-- prune on the first anchor, and VERIFY the hit against the other anchors so the
-- player being special-cased can't produce a false table.  Auto-detects the
-- images-field offset (CFRU/DPE may have grown the struct).
local function collect_anchors()
    local anchors, seen = {}, {}
    for slot = 0, OBJ_COUNT - 1 do
        local oa = OBJ_BASE + slot * OBJ_STRIDE
        if (r8(oa + OFF_FLAGS) & 0x01) ~= 0 then
            local sid = r8(oa + OFF_SPR_ID)
            if sid < 64 then
                local gfx = r8(oa + OFF_GFX_ID)
                local images = r32(GSPR_BASE + sid * GSPR_STRIDE + SPR_IMAGES)
                if in_rom(images) and not seen[gfx] then
                    seen[gfx] = true
                    anchors[#anchors+1] = { gfx = gfx, images = images, slot = slot }
                end
            end
        end
    end
    return anchors
end

-- length of the run of consecutive valid ROM pointers starting at T (the real
-- gObjectEventGraphicsInfoPointers is a dense array of hundreds of them; a
-- coincidental image-match sits in sparse data with a short run).
local function ptr_run_len(T)
    local n = 0
    for i = 0, 1200 do if in_rom(r32(T + i*4)) then n = n + 1 else break end end
    return n
end

local function findGfxTable()
    local anchors = collect_anchors()
    log("")
    if #anchors == 0 then
        log("[F1] no active object-events with ROM images ptr — be in the overworld.")
        con("[F1] no anchors — be in the overworld."); flush(); return
    end
    -- primary anchor = the PLAYER if present (slot 0; always a clean GI), else first.
    local pa = anchors[1]
    for _, a in ipairs(anchors) do if a.slot == 0 then pa = a; break end end
    log(fmt("[F1] table search: %d anchors, primary gfx=%d images=%s; scanning FULL ROM...", #anchors, pa.gfx, hex(pa.images)))
    con(fmt("[F1] Scanning ROM for gObjectEventGraphicsInfoPointers (%d anchors)... please wait (~1 min).", #anchors))
    -- Among every table where table[primaryGfx] points to a struct holding the
    -- player's images (a highly specific filter), pick the one with the LONGEST
    -- pointer run (the real GI table) — robust even when only 1 anchor matches.
    local best = nil
    for T = 0x08000000, 0x0A000000 - 4, 4 do
        local e = r32(T + pa.gfx * 4)
        if in_rom(e) then
            for _, off in ipairs(GI_IMAGES_CANDIDATES) do
                if r32(e + off) == pa.images then
                    local votes = 0
                    for _, a in ipairs(anchors) do
                        local ea = r32(T + a.gfx * 4)
                        if in_rom(ea) and r32(ea + off) == a.images then votes = votes + 1 end
                    end
                    local run = ptr_run_len(T)
                    if (not best) or run > best.run or (run == best.run and votes > best.votes) then
                        best = { T = T, off = off, votes = votes, run = run }
                    end
                end
            end
        end
        if (T & 0x007FFFFF) == 0 then con(fmt("[F1]   ...scanned up to %s", hex(T))) end
    end
    if best and best.run >= 32 then
        GFX_TABLE, GI_IMG_OFF = best.T, best.off
        log(fmt("  ✓ gObjectEventGraphicsInfoPointers = %s (images +0x%02X, ptr-run=%d, %d/%d anchors agree)",
            hex(best.T), best.off, best.run, best.votes, #anchors))
        -- validate: dump each anchor's GI vs its LIVE sprite images (MATCH proves real)
        for _, a in ipairs(anchors) do
            local gi = gi_ptr(a.gfx)
            if gi then
                local img = r32(gi + GI_IMG_OFF)
                log(fmt("    anchor gfx=%-4d %s  GI=%s  w=%d h=%d size=0x%X  images=%s [%s]",
                    a.gfx, a.slot==0 and "(PLAYER)" or "(npc)   ", hex(gi),
                    r8(gi+GI_WIDTH), r8(gi+GI_HEIGHT), r16(gi+GI_SIZE), hex(img),
                    img == a.images and "MATCH" or "mismatch"))
            end
        end
        con(fmt("[F1] ✓ table=%s (+0x%02X, run=%d, %d/%d agree). %s Press F2 to SURVEY the table.",
            hex(best.T), best.off, best.run, best.votes, #anchors,
            best.run >= 200 and "Dense → looks real." or "Run short — verify with F2."))
    else
        log(fmt("  ✗ no dense table found (best run=%d). Struct layout may differ.", best and best.run or 0))
        con("[F1] ✗ not found — see log.")
    end
    flush()
end

-- ── (A) SURVEY the whole table (run-length of WxH) to locate the mon block ─────────
-- Walk every graphicsId and print runs of constant (w x h) — tolerating gaps (null
-- entries) so we see the WHOLE structure, including high ids.  Mon overworld sprites
-- are bigger (32x32 = size 0x200; some 64x64) than the 16x32 NPCs, so the mon block
-- shows up as a long run of large entries.  Flags candidate mon runs.
local function surveyTable()
    if not GFX_TABLE then con("[F2] Run F1 first (need the table)."); return end
    log(""); log(fmt("[F2] SURVEY of %s (images +0x%02X) — runs of WxH across all graphicsIds:", hex(GFX_TABLE), GI_IMG_OFF))
    local run_lo, run_w, run_h, run_sz = nil, nil, nil, nil
    local nulls, valid = 0, 0
    local mon_lo, mon_hi, mon_n = nil, nil, 0
    local function emit(hi)
        if run_lo then
            local px = (run_w//8) * (run_h//8)
            local mon = (run_w >= 32 and run_h >= 32)
            log(fmt("    [%4d..%4d]  %2dx%-2d  size=0x%-4X (%d tiles)%s",
                run_lo, hi, run_w, run_h, run_sz, px, mon and "   <-- mon-size" or ""))
            if mon then
                if not mon_lo then mon_lo = run_lo end
                mon_hi = hi; mon_n = mon_n + (hi - run_lo + 1)
            end
        end
    end
    local last_valid = -1
    for gfx = 0, 1023 do
        local gi = gi_ptr(gfx)
        if gi then
            valid = valid + 1; last_valid = gfx
            local w, h, sz = r8(gi+GI_WIDTH), r8(gi+GI_HEIGHT), r16(gi+GI_SIZE)
            if w ~= run_w or h ~= run_h or sz ~= run_sz then
                emit(gfx - 1); run_lo, run_w, run_h, run_sz = gfx, w, h, sz
            end
        else
            nulls = nulls + 1
            emit(gfx - 1); run_lo = nil
            -- stop only after a long tail of nulls past the last valid entry
            if gfx - last_valid > 96 and last_valid > 0 then break end
        end
    end
    emit(last_valid)
    log(fmt("  total: %d valid entries, %d nulls; last valid gfx=%d", valid, nulls, last_valid))
    if mon_lo then
        MON_RANGE_LO, MON_RANGE_HI = mon_lo, mon_hi
        TARGET_GFX = mon_lo
        log(fmt("  → mon-size (≥32x32) entries span gfx [%d..%d] (%d). TARGET_GFX set to %d.", mon_lo, mon_hi, mon_n, mon_lo))
        con(fmt("[F2] survey done. Mon-size ids ≈ [%d..%d]. TARGET_GFX=%d. F5/F6 to browse, F3 to render.", mon_lo, mon_hi, mon_lo))
    else
        con("[F2] survey done — NO ≥32x32 entries (mons may be 16x16/16x32, or table wrong). See log.")
    end
    flush()
end

-- ── (A) SPAWN-RENDER a mon graphicsId (proof of concept) ──────────────────────────
-- Clone the player's sprite into a free slot, but repoint images/anims/oam at the
-- MON's graphics-info so the engine DMAs the mon's frames into our reserved tiles.
-- Position it one tile below the player.  PALETTE is left as the player's for now
-- (colors may be wrong) — proving the SHAPE renders is the goal; palette load is a
-- follow-up (needs the paletteTag→data table).
local _mon_active, _mon_spr, _mon_obj, _mon_tile = false, nil, nil, nil
local _mon_tile_n = 16   -- tiles reserved for the current mon (sized from its GI)

local function claim_tiles(n)
    local used = {}
    for s = 0, 63 do
        local sa = GSPR_BASE + s * GSPR_STRIDE
        if (r8(sa+SPR_BYTE3E) & 0x01) ~= 0 then
            local t = r16(sa+SPR_OAM2) & 0x03FF
            for k=0,n-1 do used[t+k]=true end
        end
    end
    for base = TOTAL_OBJ_TILES - n, 0, -n do
        local ok=true; for k=0,n-1 do if used[base+k] then ok=false break end end
        if ok then return base end
    end
    return TOTAL_OBJ_TILES - n
end
local function bitmap_set(tile, n, set)
    for t=tile,tile+n-1 do
        local a=TILE_BITMAP+(t>>3); local m=1<<(t&7)
        if set then w8(a, r8(a)|m) else w8(a, r8(a)&((~m)&0xFF)) end
    end
end

local function monSpawn()
    if _mon_active then
        if _mon_obj then w8(OBJ_BASE + _mon_obj*OBJ_STRIDE + OFF_FLAGS, 0x00) end
        if _mon_spr then local b=GSPR_BASE+_mon_spr*GSPR_STRIDE+SPR_BYTE3E; w8(b, r8(b)&0xFE) end
        if _mon_tile then bitmap_set(_mon_tile, _mon_tile_n, false) end
        _mon_active=false; con("[F3] mon sprite cleared.")
        return
    end
    if not GFX_TABLE then con("[F3] Run F1/F2 first."); return end
    local gi = gi_ptr(TARGET_GFX)
    if not gi then con(fmt("[F3] graphicsId %d has no GI entry.", TARGET_GFX)); return end
    local p_sid = player_sprite_id()
    if p_sid >= 64 then con("[F3] player sprite invalid."); return end

    -- free slots
    local fs; for s=63,1,-1 do if s~=p_sid and (r8(GSPR_BASE+s*GSPR_STRIDE+SPR_BYTE3E)&0x01)==0 then fs=s break end end
    local fo; for o=1,OBJ_COUNT-1 do if (r8(OBJ_BASE+o*OBJ_STRIDE+OFF_FLAGS)&0x01)==0 then fo=o break end end
    if not fs or not fo then con("[F3] no free slot."); return end
    _mon_spr, _mon_obj = fs, fo

    local paddr = GSPR_BASE + p_sid*GSPR_STRIDE
    local naddr = GSPR_BASE + fs*GSPR_STRIDE
    for i=0,GSPR_STRIDE-1 do w8(naddr+i, r8(paddr+i)) end

    -- repoint at the mon's graphics: images (→ engine DMAs mon frames), anims, oam
    -- shape/size (so the right tile count is drawn).
    local mon_images = r32(gi+GI_IMG_OFF)
    local mon_anims  = r32(gi+GI_ANIMS)
    local mon_oam    = r32(gi+GI_OAM)
    if in_rom(mon_images) then w32(naddr+SPR_IMAGES, mon_images) end
    if in_rom(mon_anims)  then w32(naddr+SPR_ANIMS,  mon_anims)  end
    -- copy the mon OAM template's attr0/attr1 shape+size bits into our inline oam
    if in_rom(mon_oam) then
        local ma0, ma1 = r16(mon_oam+0x00), r16(mon_oam+0x02)
        local na0 = (r16(naddr+SPR_OAM0) & 0x3FFF) | (ma0 & 0xC000)
        local na1 = (r16(naddr+SPR_OAM1) & 0x3FFF) | (ma1 & 0xC000)
        w16(naddr+SPR_OAM0, na0); w16(naddr+SPR_OAM1, na1)
    end

    -- own reserved tiles, sized from the mon's GI dimensions (32x32=16, 64x64=64)
    local gw, gh = r8(gi+GI_WIDTH), r8(gi+GI_HEIGHT)
    _mon_tile_n = math.max(1, math.min(64, (gw//8) * (gh//8)))
    _mon_tile = claim_tiles(_mon_tile_n)
    bitmap_set(_mon_tile, _mon_tile_n, true)
    local a2 = r16(naddr+SPR_OAM2)
    w16(naddr+SPR_OAM2, (a2 & 0xFC00) | (_mon_tile & 0x03FF))
    w8(naddr+SPR_BYTE3E, (r8(naddr+SPR_BYTE3E) | 0x01) & 0xFB)   -- inUse, visible
    ws16(naddr+SPR_DATA0, fo)
    w8(naddr+SPR_BYTE3F, r8(naddr+SPR_BYTE3F) | 0x04)           -- animBeginning → DMA frame0
    w8(naddr+SPR_BYTE2C, r8(naddr+SPR_BYTE2C) & 0xBF)          -- animPaused=0
    w8(naddr+SPR_ANIMNUM, 0)

    -- backing object-event one tile below player (so it isn't culled)
    local nobj = OBJ_BASE + fo*OBJ_STRIDE
    local px, py = rs16(OBJ_BASE+OFF_CURX), rs16(OBJ_BASE+OFF_CURY)
    for i=0,OBJ_STRIDE-1 do w8(nobj+i,0) end
    w8(nobj+OFF_FLAGS, 0x01); w8(nobj+OFF_SPR_ID, fs)
    w8(nobj+OFF_GFX_ID, TARGET_GFX); w8(nobj+OFF_MOV_TYPE, 0x00)
    w8(nobj+OFF_LOCAL_ID, 0xFD)
    w8(nobj+OFF_MAP_N, r8(OBJ_BASE+OFF_MAP_N)); w8(nobj+OFF_MAP_G, r8(OBJ_BASE+OFF_MAP_G))
    ws16(nobj+OFF_CURX, px); ws16(nobj+OFF_CURY, py)
    ws16(nobj+OFF_PREVX, px); ws16(nobj+OFF_PREVY, py)

    _mon_active = true
    log(""); log(fmt("[F3] spawned mon gfx=%d at slot spr=%d obj=%d tile=%d images=%s",
        TARGET_GFX, fs, fo, _mon_tile, hex(mon_images)))
    con(fmt("[F3] mon gfx=%d spawned (slot %d, tile %d). Walk — does a MON shape track below you?", TARGET_GFX, fs, _mon_tile))
    con("[F3]   (palette may be wrong = colors off; SHAPE is the proof.) F3 again to clear.")
    flush()
end

-- ── (B) ROUTE↔ROUTE CROSSING tracker ─────────────────────────────────────────────
-- Spawn a tracked clone (like the real ghost), then log every frame whether our
-- slot SURVIVES a connected-map crossing.  If inUse stays set + our data intact
-- across the (mg,mn) change, we can keep the ghost (recalibrate base C) instead of
-- despawning → no flicker.  Also logs how currentCoords + coordOffset re-base.
local _xt_active, _xt_spr, _xt_obj, _xt_tile = false, nil, nil, nil
local _xt_last_mg, _xt_last_mn = -1, -1
local _xt_frames = 0

local function crossingToggle()
    if _xt_active then
        if _xt_obj then w8(OBJ_BASE+_xt_obj*OBJ_STRIDE+OFF_FLAGS,0x00) end
        if _xt_spr then local b=GSPR_BASE+_xt_spr*GSPR_STRIDE+SPR_BYTE3E; w8(b,r8(b)&0xFE) end
        if _xt_tile then bitmap_set(_xt_tile, 8, false) end
        _xt_active=false; con("[F4] crossing tracker OFF.")
        flush(); return
    end
    local p_sid = player_sprite_id()
    if p_sid >= 64 then con("[F4] player sprite invalid."); return end
    local fs; for s=63,1,-1 do if s~=p_sid and (r8(GSPR_BASE+s*GSPR_STRIDE+SPR_BYTE3E)&0x01)==0 then fs=s break end end
    local fo; for o=1,OBJ_COUNT-1 do if (r8(OBJ_BASE+o*OBJ_STRIDE+OFF_FLAGS)&0x01)==0 then fo=o break end end
    if not fs or not fo then con("[F4] no free slot."); return end
    _xt_spr, _xt_obj = fs, fo
    -- Mirror peer_ghost.acquire EXACTLY (the proven-safe path): clone the player
    -- sprite, give it OWN reserved tiles, set data[0]=our objevent (CRITICAL — a
    -- clone with the player's data[0] makes the copied callback drive the PLAYER
    -- and corrupts the game), and a NONE-movement backing objevent.
    local paddr, naddr = GSPR_BASE+p_sid*GSPR_STRIDE, GSPR_BASE+fs*GSPR_STRIDE
    for i=0,GSPR_STRIDE-1 do w8(naddr+i, r8(paddr+i)) end
    local xt_tile = claim_tiles(8)
    bitmap_set(xt_tile, 8, true)
    local a2 = r16(naddr+SPR_OAM2)
    w16(naddr+SPR_OAM2, (a2 & 0xFC00) | (xt_tile & 0x03FF))
    w8(naddr+SPR_BYTE3E, (r8(naddr+SPR_BYTE3E)|0x01)&0xFB)   -- inUse, visible
    ws16(naddr+SPR_DATA0, fo)                                -- data[0] = our objevent (CRITICAL)
    w8(naddr+SPR_BYTE3F, r8(naddr+SPR_BYTE3F) | 0x04)        -- animBeginning → DMA frame0 to our tiles
    w8(naddr+SPR_BYTE2C, r8(naddr+SPR_BYTE2C) & 0xBF)        -- animPaused=0
    local nobj = OBJ_BASE+fo*OBJ_STRIDE
    local px,py = rs16(OBJ_BASE+OFF_CURX), rs16(OBJ_BASE+OFF_CURY)
    for i=0,OBJ_STRIDE-1 do w8(nobj+i,0) end
    w8(nobj+OFF_FLAGS,0x01); w8(nobj+OFF_SPR_ID,fs)
    w8(nobj+OFF_GFX_ID, r8(OBJ_BASE+OFF_GFX_ID)); w8(nobj+OFF_MOV_TYPE,0x00)
    w8(nobj+OFF_LOCAL_ID,0xFD)
    w8(nobj+OFF_MAP_N, r8(OBJ_BASE+OFF_MAP_N)); w8(nobj+OFF_MAP_G, r8(OBJ_BASE+OFF_MAP_G))
    ws16(nobj+OFF_CURX,px); ws16(nobj+OFF_CURY,py); ws16(nobj+OFF_PREVX,px); ws16(nobj+OFF_PREVY,py)
    _xt_tile = xt_tile
    _xt_active = true
    _xt_last_mg, _xt_last_mn = get_map()
    _xt_frames = 0
    log(""); log(fmt("[F4] crossing tracker ON — spr=%d obj=%d on map %d:%d. Walk across a route border.",
        fs, fo, _xt_last_mg, _xt_last_mn))
    con(fmt("[F4] crossing tracker ON (slot %d). Walk route→route; watch the log for SURVIVED/WIPED.", fs))
    flush()
end

-- per-frame work for F3 (drive the mon below the player) + F4 (log the crossing)
local function onFramePhase2()
    if _mon_active and _mon_spr then
        local p_sid = player_sprite_id()
        if p_sid < 64 and (r8(GSPR_BASE+_mon_spr*GSPR_STRIDE+SPR_BYTE3E)&0x01) ~= 0 then
            local psa = GSPR_BASE + p_sid*GSPR_STRIDE
            local nsa = GSPR_BASE + _mon_spr*GSPR_STRIDE
            -- one tile (16px) below the player; copy coordOffset-enable bit too
            ws16(nsa+SPR_X, rs16(psa+SPR_X))
            ws16(nsa+SPR_Y, rs16(psa+SPR_Y) + 16)
            w8(nsa+SPR_BYTE3E, r8(nsa+SPR_BYTE3E) | (r8(psa+SPR_BYTE3E) & 0x02))
            -- keep our reserved tiles (engine DMAs mon frames here)
            local a2 = r16(nsa+SPR_OAM2)
            w16(nsa+SPR_OAM2, (a2 & 0xFC00) | (_mon_tile & 0x03FF))
        end
    end
    if _xt_active and _xt_spr then
        _xt_frames = _xt_frames + 1
        local mg, mn = get_map()
        local sa = GSPR_BASE + _xt_spr*GSPR_STRIDE
        local oa = OBJ_BASE + _xt_obj*OBJ_STRIDE
        local spr_inuse = (r8(sa+SPR_BYTE3E) & 0x01) ~= 0
        local obj_ours  = (r8(oa+OFF_FLAGS) & 0x01) ~= 0 and r8(oa+OFF_LOCAL_ID) == 0xFD
        local p_sid = player_sprite_id()
        local px, py = rs16(OBJ_BASE+OFF_CURX), rs16(OBJ_BASE+OFF_CURY)
        local coffx, coffy = rs16(COFF_X), rs16(COFF_Y)
        -- While the slot is still OURS, pin the objevent to the player's tile (so
        -- off-screen cull never fires → a slot clear is then attributable to the
        -- map crossing, not culling) and keep our tileNum.  Guarded by the 0xFD
        -- marker so we never write into a slot the engine has reused.
        if obj_ours and mg == _xt_last_mg and mn == _xt_last_mn then
            ws16(oa+OFF_CURX, px); ws16(oa+OFF_CURY, py)
            ws16(oa+OFF_PREVX, px); ws16(oa+OFF_PREVY, py)
            if spr_inuse and _xt_tile then
                local a2 = r16(sa+SPR_OAM2)
                w16(sa+SPR_OAM2, (a2 & 0xFC00) | (_xt_tile & 0x03FF))
            end
        end
        if mg ~= _xt_last_mg or mn ~= _xt_last_mn then
            log(fmt("[F4] >>> MAP CHANGE %d:%d → %d:%d at frame %d <<<", _xt_last_mg, _xt_last_mn, mg, mn, _xt_frames))
            log(fmt("     our spr slot inUse=%s | our obj slot ours=%s | playerSpriteId=%d",
                tostring(spr_inuse), tostring(obj_ours), p_sid))
            log(fmt("     playerCoords=(%d,%d) coordOffset=(%d,%d)  → %s",
                px, py, coffx, coffy,
                (spr_inuse and obj_ours) and "SLOT SURVIVED (can keep ghost, recalibrate C)"
                                          or "SLOT WIPED/REUSED (gap unavoidable; re-acquire fast)"))
            con(fmt("[F4] map %d:%d→%d:%d  slot %s", _xt_last_mg,_xt_last_mn,mg,mn,
                (spr_inuse and obj_ours) and "SURVIVED" or "WIPED"))
            _xt_last_mg, _xt_last_mn = mg, mn
            flush()
        end
    end
end

-- ── key handler ───────────────────────────────────────────────────────────────────
local _prev = {}
event.unregisterbyname("ghost_phase2_keys")
event.onframeend(function()
    local k = input.get()
    if k["F1"] and not _prev["F1"] then findGfxTable() end
    if k["F2"] and not _prev["F2"] then surveyTable() end
    if k["F3"] and not _prev["F3"] then monSpawn() end
    if k["F4"] and not _prev["F4"] then crossingToggle() end
    if k["F5"] and not _prev["F5"] then TARGET_GFX = math.max(0, TARGET_GFX-1); con(fmt("[F5] TARGET_GFX=%d", TARGET_GFX)) end
    if k["F6"] and not _prev["F6"] then TARGET_GFX = TARGET_GFX+1; con(fmt("[F6] TARGET_GFX=%d", TARGET_GFX)) end
    onFramePhase2()
    _prev = k
end, "ghost_phase2_keys")

-- auto-find the table on load
findGfxTable()

con("")
con("════════════════════════════════════════════════════════════════")
con("  SLINK PEER-GHOST — PHASE 2 discovery (mon graphics + route crossing)")
con("    F1: find gObjectEventGraphicsInfoPointers   F2: SURVEY table (find mon block)")
con("    F5/F6: TARGET_GFX − / +     F3: spawn-render TARGET_GFX below you")
con("    F4: route-crossing tracker (toggle, then walk across a route border)")
con(fmt("  Output: %s", OUT_PATH or "(file write failed)"))
con("════════════════════════════════════════════════════════════════")
con("")
flush()
