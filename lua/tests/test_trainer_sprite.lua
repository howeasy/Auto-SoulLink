--[[
  lua/tests/test_trainer_sprite.lua  —  Peer-ghost: render the PARTNER's chosen
  trainer sprite (RR lets the player pick from several trainer avatars).
  =========================================================================
  The ghost currently CLONES the local player's sprite, so it always looks like
  YOUR trainer.  To show the partner's chosen trainer we must render an arbitrary
  graphicsId with its OWN graphics + palette.  Graphics we can already do (via
  gObjectEventGraphicsInfoPointers); the missing piece is the PALETTE.  This
  script finds the palette table and proves a foreign trainer renders correctly.

  CONFIRMED constants (RR 4.1):
    gObjectEvents 0x02036E38 /0x24 ·  gSprites 0x0202063C /0x44 ·
    gObjectEventGraphicsInfoPointers 0x0934FCB8 (images +0x1C) ·
    gSpriteTileAllocBitmap 0x02017D9C ·  gSaveBlock1Ptr 0x03005008.

  HOW TO RUN (in the OVERWORLD)
    1. Load RR, Lua Console → load this script (auto-validates the GI table).
    2. F1 — dump the LOCAL player's trainer: gfx id, GI fields (paletteTag/slot,
            dims).  Note the gfx id — that's your chosen trainer.
    3. F2 — find sObjectEventSpritePalettes (the tag→palette-data table) by
            matching the player's loaded OBJ palette.  Needed for colors.
    4. F5/F6 — TARGET_GFX − / +  (set it to the OTHER player's trainer gfx id).
    5. F3 — render TARGET_GFX one tile below you WITH its correct palette.
            Walk: it should look like that trainer, right colors.  F3 = clear.

  OUTPUT → <dir>/trainer_sprite_results.txt
--]]

local fmt = string.format
local r8, r16, r32 = memory.read_u8, memory.read_u16_le, memory.read_u32_le
local rs16 = memory.read_s16_le
local w8, w16, w32 = memory.write_u8, memory.write_u16_le, memory.write_u32_le
local ws16 = memory.write_s16_le
local function hex(n) return fmt("0x%08X", n) end

-- ── output ──────────────────────────────────────────────────────────────────────
local _lines, OUT_PATH = {}, nil
local function _try(p) local ok,f=pcall(io.open,p,"w"); if ok and f then f:write("");f:close();return true end return false end
do
    local ok, info = pcall(debug.getinfo, 1, "S")
    local dir = ok and info and info.source and info.source:match("^@?(.*[\\/])")
    if dir and _try(dir.."trainer_sprite_results.txt") then OUT_PATH = dir.."trainer_sprite_results.txt"
    elseif _try("trainer_sprite_results.txt") then OUT_PATH = "trainer_sprite_results.txt" end
end
local function log(s) _lines[#_lines+1] = s end
local function con(s) console.log(s) end
local function flush() if OUT_PATH then local ok,f=pcall(io.open,OUT_PATH,"w"); if ok and f then f:write(table.concat(_lines,"\n").."\n");f:close() end end end

-- ── constants ─────────────────────────────────────────────────────────────────────
local OBJ_BASE, OBJ_STRIDE, OBJ_COUNT = 0x02036E38, 0x24, 16
local OFF_FLAGS, OFF_SPR_ID, OFF_GFX_ID, OFF_MOV_TYPE = 0x00, 0x04, 0x05, 0x06
local OFF_LOCAL_ID, OFF_MAP_N, OFF_MAP_G = 0x08, 0x09, 0x0A
local OFF_CURX, OFF_CURY, OFF_PREVX, OFF_PREVY = 0x10, 0x12, 0x14, 0x16
local GSPR_BASE, GSPR_STRIDE = 0x0202063C, 0x44
local SPR_OAM0, SPR_OAM1, SPR_OAM2 = 0x00, 0x02, 0x04
local SPR_ANIMS, SPR_IMAGES = 0x08, 0x0C
local SPR_X, SPR_Y, SPR_ANIMNUM = 0x20, 0x22, 0x2A
local SPR_BYTE2C, SPR_DATA0, SPR_BYTE3E, SPR_BYTE3F = 0x2C, 0x2E, 0x3E, 0x3F
local GFX_TABLE, GI_IMG_OFF = 0x0934FCB8, 0x1C
local GI_PALTAG, GI_WIDTH, GI_HEIGHT, GI_PALSLOT, GI_OAM, GI_ANIMS = 0x02, 0x08, 0x0A, 0x0C, 0x10, 0x18
local TILE_BITMAP = 0x02017D9C
local OBJ_VRAM0, OBJ_PLTT, TILE_4BPP = 0x06010000, 0x05000200, 32
local TOTAL_OBJ_TILES = 1024

local function in_rom(p) return p >= 0x08000000 and p < 0x0A000000 end
local function gi_ptr(gfx) local p = r32(GFX_TABLE + gfx*4); return in_rom(p) and p or nil end
local function round(n) return math.floor(n + 0.5) end

-- discovered palette table
local PAL_BASE, PAL_COUNT = nil, nil

-- ── F1: dump the local player's trainer GI ─────────────────────────────────────────
local function dumpPlayer()
    local sid = r8(OBJ_BASE + OFF_SPR_ID)
    local gfx = r8(OBJ_BASE + OFF_GFX_ID)
    local gi = gi_ptr(gfx)
    log(""); log(fmt("[F1] player gfx=%d sprite=%d", gfx, sid))
    if not gi then con("[F1] no GI for player gfx — GI table may have shifted."); flush(); return end
    local spr_images = (sid < 64) and r32(GSPR_BASE + sid*GSPR_STRIDE + SPR_IMAGES) or 0
    log(fmt("  GI=%s  palTag=0x%04X palSlot=%d  w=%d h=%d  oam=%s anims=%s images=%s (sprite images=%s %s)",
        hex(gi), r16(gi+GI_PALTAG), r8(gi+GI_PALSLOT)&0x0F, r8(gi+GI_WIDTH), r8(gi+GI_HEIGHT),
        hex(r32(gi+GI_OAM)), hex(r32(gi+GI_ANIMS)), hex(r32(gi+GI_IMG_OFF)),
        hex(spr_images), (spr_images == r32(gi+GI_IMG_OFF)) and "MATCH" or "mismatch"))
    con(fmt("[F1] player trainer gfx=%d palTag=0x%04X palSlot=%d. (Your chosen trainer.)",
        gfx, r16(gi+GI_PALTAG), r8(gi+GI_PALSLOT)&0x0F))
    -- DECISIVE: is the player's REAL graphics source in ROM (broadcast a ptr, cheap)
    -- or RAM (must ship the tile bytes)?  sprite.images → SpriteFrameImage[0] = {data, size}.
    local function cls(p)
        if p >= 0x08000000 and p < 0x0A000000 then return "ROM"
        elseif p >= 0x02000000 and p < 0x02040000 then return "EWRAM"
        elseif p >= 0x03000000 and p < 0x03008000 then return "IWRAM"
        elseif p >= 0x06000000 and p < 0x06018000 then return "VRAM" else return "?" end
    end
    if sid < 64 then
        local img = spr_images
        local f0 = (img ~= 0) and r32(img) or 0
        local sz = (img ~= 0) and r16(img + 4) or 0
        log(fmt("  sprite.images=%s (%s)  frame0.data=%s (%s)  size=0x%X", hex(img), cls(img), hex(f0), cls(f0), sz))
        con(fmt("[F1] sprite.images=%s(%s)  frame0.data=%s(%s) size=0x%X  ← ROM=cheap, RAM=heavy",
            hex(img), cls(img), hex(f0), cls(f0), sz))
    end
    flush()
end

-- ── F2: find sObjectEventSpritePalettes (tag → palette data) ────────────────────────
-- struct SpritePalette { const u16 *data; u16 tag; } = 8 bytes.  Find it by matching
-- the player's loaded OBJ palette: the entry whose tag == player GI paletteTag and
-- whose 16-colour data equals the palette loaded at the player's OBJ palette slot.
local function palettes_equal(romptr, pltt_addr)
    for i = 0, 15 do
        if r16(romptr + i*2) ~= r16(pltt_addr + i*2) then return false end
    end
    return true
end
-- GBA colours are 15-bit (BGR555), so bit15 of every entry is 0; a real palette's
-- 16 colours all satisfy that.  Cheap validator to reject coincidental tag matches.
local function looks_like_palette(romptr)
    for i = 0, 15 do if (r16(romptr + i*2) & 0x8000) ~= 0 then return false end end
    return true
end
local function findPaletteTable()
    local gfx = r8(OBJ_BASE + OFF_GFX_ID)
    local gi = gi_ptr(gfx)
    if not gi then con("[F2] no player GI."); return end
    local palTag = r16(gi + GI_PALTAG)
    local palSlot = r8(gi + GI_PALSLOT) & 0x0F
    local loaded = OBJ_PLTT + palSlot * 0x20
    log(""); log(fmt("[F2] palette-table search: player palTag=0x%04X slot=%d (loaded @ %s)", palTag, palSlot, hex(loaded)))
    con(fmt("[F2] Scanning ROM for sObjectEventSpritePalettes (palTag=0x%04X)... please wait.", palTag))
    -- Match on TAG (the loaded palette is usually day/night TINTED, so requiring a
    -- byte-exact match to ROM wrongly rejects the real entry).  Prefer an entry whose
    -- data also byte-matches the loaded palette (untinted), else accept the first
    -- tag-only hit with a ROM data ptr.
    local hit, hit_exact = nil, nil
    for T = 0x08000000, 0x0A000000 - 8, 4 do
        if r16(T + 4) == palTag then
            local data = r32(T)
            if in_rom(data) and looks_like_palette(data) then
                if palettes_equal(data, loaded) then hit_exact = T; break end
                if not hit then hit = T end
            end
        end
    end
    hit = hit_exact or hit
    if not hit then
        log("  ✗ no ROM {data,tag} entry with tag 0x"..fmt("%04X",palTag).." — struct layout differs, or palette is dynamic (DPE).")
        con("[F2] ✗ not found — see log.")
        flush(); return
    end
    log(fmt("  tag hit @ %s (%s)", hex(hit), hit_exact and "palette byte-matches loaded" or "tag-only; loaded palette differs = tint (fine)"))
    -- walk back/forward to find the table extent (valid entry = data is a ROM ptr to
    -- something that looks like a 16-colour palette — without the palette check the
    -- walk runs off the end into junk and inflates the count → wrong lookups → black).
    local function valid_entry(a) return in_rom(r32(a)) and looks_like_palette(r32(a)) end
    local base = hit
    while base - 8 >= 0x08000000 and valid_entry(base - 8) do base = base - 8 end
    local last = hit
    while valid_entry(last + 8) do last = last + 8 end
    PAL_BASE = base
    PAL_COUNT = (last - base) / 8 + 1
    log(fmt("  ✓ sObjectEventSpritePalettes = %s  (player tag entry @ %s, ~%d entries)", hex(base), hex(hit), PAL_COUNT))
    con(fmt("[F2] ✓ palette table = %s (~%d entries). F5/F6 pick a trainer, F3 to render with colour.", hex(base), PAL_COUNT))
    flush()
end
local function palette_data_for_tag(tag)
    if not PAL_BASE then return nil end
    for i = 0, PAL_COUNT - 1 do
        if r16(PAL_BASE + i*8 + 4) == tag then
            local d = r32(PAL_BASE + i*8)
            if in_rom(d) and looks_like_palette(d) then return d end
        end
    end
    return nil
end

-- ── tile + palette slot allocation ──────────────────────────────────────────────────
local function claim_tiles(n)
    local used = {}
    for s = 0, 63 do
        local sa = GSPR_BASE + s*GSPR_STRIDE
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
    for t=tile,tile+n-1 do local a=TILE_BITMAP+(t>>3); local m=1<<(t&7)
        if set then w8(a,r8(a)|m) else w8(a,r8(a)&((~m)&0xFF)) end end
end
-- find an OBJ palette slot not referenced by any active sprite (high-first)
local function claim_palette_slot()
    local used = {}
    for s = 0, 63 do
        local sa = GSPR_BASE + s*GSPR_STRIDE
        if (r8(sa+SPR_BYTE3E) & 0x01) ~= 0 then used[(r16(sa+SPR_OAM2) >> 12) & 0x0F] = true end
    end
    for slot = 15, 0, -1 do if not used[slot] then return slot end end
    return 15
end

-- ── F3: render TARGET_GFX below the player WITH its palette ─────────────────────────
local TARGET_GFX = 0
local _act, _spr, _obj, _tile, _tn = false, nil, nil, nil, 16

local function spawnTrainer()
    if _act then
        if _obj then w8(OBJ_BASE+_obj*OBJ_STRIDE+OFF_FLAGS,0x00) end
        if _spr then local b=GSPR_BASE+_spr*GSPR_STRIDE+SPR_BYTE3E; w8(b,r8(b)&0xFE) end
        if _tile then bitmap_set(_tile,_tn,false) end
        _act=false; con("[F3] trainer sprite cleared."); return
    end
    local gi = gi_ptr(TARGET_GFX)
    if not gi then con(fmt("[F3] gfx %d has no GI.", TARGET_GFX)); return end
    local p_sid = r8(OBJ_BASE+OFF_SPR_ID)
    if p_sid >= 64 then con("[F3] player sprite invalid."); return end
    local fs; for s=63,1,-1 do if s~=p_sid and (r8(GSPR_BASE+s*GSPR_STRIDE+SPR_BYTE3E)&0x01)==0 then fs=s break end end
    local fo; for o=1,OBJ_COUNT-1 do if (r8(OBJ_BASE+o*OBJ_STRIDE+OFF_FLAGS)&0x01)==0 then fo=o break end end
    if not fs or not fo then con("[F3] no free slot."); return end
    _spr, _obj = fs, fo

    local paddr, naddr = GSPR_BASE+p_sid*GSPR_STRIDE, GSPR_BASE+fs*GSPR_STRIDE
    for i=0,GSPR_STRIDE-1 do w8(naddr+i, r8(paddr+i)) end
    -- repoint graphics at TARGET_GFX
    local images, anims, oam = r32(gi+GI_IMG_OFF), r32(gi+GI_ANIMS), r32(gi+GI_OAM)
    if in_rom(images) then w32(naddr+SPR_IMAGES, images) end
    if in_rom(anims)  then w32(naddr+SPR_ANIMS,  anims)  end
    if in_rom(oam) then
        w16(naddr+SPR_OAM0, (r16(naddr+SPR_OAM0)&0x3FFF)|(r16(oam+0)&0xC000))
        w16(naddr+SPR_OAM1, (r16(naddr+SPR_OAM1)&0x3FFF)|(r16(oam+2)&0xC000))
    end
    -- own reserved tiles, sized from GI dims
    local gw, gh = r8(gi+GI_WIDTH), r8(gi+GI_HEIGHT)
    _tn = math.max(1, math.min(64, (gw//8)*(gh//8)))
    _tile = claim_tiles(_tn); bitmap_set(_tile,_tn,true)
    local a2 = r16(naddr+SPR_OAM2)
    -- PALETTE: load this trainer's palette into a free OBJ slot + point oam at it
    local palSlot = (r16(naddr+SPR_OAM2) >> 12) & 0x0F   -- default: keep player's
    local tag = r16(gi+GI_PALTAG)
    local pdata = palette_data_for_tag(tag)
    if pdata then
        palSlot = claim_palette_slot()
        for i=0,15 do w16(OBJ_PLTT + palSlot*0x20 + i*2, r16(pdata + i*2)) end
        log(fmt("[F3] loaded palette tag=0x%04X from %s into OBJ slot %d", tag, hex(pdata), palSlot))
    else
        log(fmt("[F3] palette tag=0x%04X NOT found (run F2) — using player's slot (colours may be off)", tag))
    end
    w16(naddr+SPR_OAM2, (a2 & 0x03FF) | (_tile & 0x03FF) | ((palSlot & 0x0F) << 12))
    w8(naddr+SPR_BYTE3E, (r8(naddr+SPR_BYTE3E)|0x01)&0xFB)
    ws16(naddr+SPR_DATA0, fo)
    w8(naddr+SPR_BYTE3F, r8(naddr+SPR_BYTE3F)|0x04)
    w8(naddr+SPR_BYTE2C, r8(naddr+SPR_BYTE2C)&0xBF)
    w8(naddr+SPR_ANIMNUM, 0)

    local nobj = OBJ_BASE+fo*OBJ_STRIDE
    local px,py = rs16(OBJ_BASE+OFF_CURX), rs16(OBJ_BASE+OFF_CURY)
    for i=0,OBJ_STRIDE-1 do w8(nobj+i,0) end
    w8(nobj+OFF_FLAGS,0x01); w8(nobj+OFF_SPR_ID,fs)
    w8(nobj+OFF_GFX_ID,TARGET_GFX); w8(nobj+OFF_MOV_TYPE,0x00); w8(nobj+OFF_LOCAL_ID,0xFD)
    w8(nobj+OFF_MAP_N,r8(OBJ_BASE+OFF_MAP_N)); w8(nobj+OFF_MAP_G,r8(OBJ_BASE+OFF_MAP_G))
    ws16(nobj+OFF_CURX,px); ws16(nobj+OFF_CURY,py); ws16(nobj+OFF_PREVX,px); ws16(nobj+OFF_PREVY,py)
    _act = true
    log(""); log(fmt("[F3] spawned trainer gfx=%d spr=%d tile=%d tiles=%d", TARGET_GFX, fs, _tile, _tn))
    con(fmt("[F3] trainer gfx=%d rendered below you. Walk — right trainer + colours? F3=clear.", TARGET_GFX))
    flush()
end

-- ── F8: find the palette SHADOW BUFFERS (gPlttBufferUnfaded / Faded) ────────────────
-- Writing directly to OBJ palette RAM (0x05000200) is overwritten every frame: the
-- engine DMAs gPlttBufferFaded → palette RAM (for day/night tint).  So a loaded
-- palette only sticks if written into the EWRAM shadow buffers.  Find gPlttBufferFaded
-- by matching its OBJ region to live palette RAM; Unfaded is the 0x400-byte buffer
-- immediately before it (pret declares them adjacent, PLTT_BUFFER_SIZE=0x200 u16).
local PLTT_FADED_OBJ, PLTT_UNFADED_OBJ = nil, nil
local function findPlttBuffers()
    -- Use the player SPRITE's ACTUAL oam.paletteNum (not the GI's preferred slot) and
    -- match just those 16 stable colours (animated palettes break a full-256 match).
    local p_sid = r8(OBJ_BASE+OFF_SPR_ID)
    if p_sid >= 64 then con("[F8] player sprite invalid."); return end
    local slot = (r16(GSPR_BASE+p_sid*GSPR_STRIDE+SPR_OAM2) >> 12) & 0x0F
    local plt = OBJ_PLTT + slot*0x20
    local ref = {}; for i=0,15 do ref[i] = r16(plt + i*2) end
    log(""); log(fmt("[F8] palette-buffer search: player sprite slot=%d palette @ %s", slot, hex(plt)))
    con(fmt("[F8] Scanning EWRAM for the palette shadow buffer (player slot %d, 16 colours)... please wait.", slot))
    local matches = {}
    for A = 0x02000000, 0x0203FFE0, 4 do
        if r16(A) == ref[0] and r16(A+2) == ref[1] and r16(A+0x1E) == ref[15] then
            local ok = true
            for i=2,14 do if r16(A+i*2) ~= ref[i] then ok=false break end end
            if ok then matches[#matches+1] = A end
        end
    end
    log(fmt("  %d EWRAM match(es) for the player's 16-colour palette:", #matches))
    for _, A in ipairs(matches) do
        local pair = ""
        for _, B in ipairs(matches) do
            if B == A - 0x400 then pair = pair.." (has match 0x400 below = this is Faded)" end
            if B == A + 0x400 then pair = pair.." (has match 0x400 above = this is Unfaded)" end
        end
        log(fmt("    %s  (slot-%d region base = %s)%s", hex(A), slot, hex(A - slot*0x20), pair))
    end
    if #matches == 0 then
        log("  ✗ none — shadow buffer layout differs or palette is animated. See log.")
        con("[F8] ✗ not found — see log (paste it)."); flush(); return
    end
    -- Prefer a match that has another match 0x400 below it (= Faded, Unfaded precedes).
    local faded = matches[#matches]
    for _, A in ipairs(matches) do for _, B in ipairs(matches) do if B == A - 0x400 then faded = A end end end
    PLTT_FADED_OBJ   = faded - slot*0x20          -- OBJ slot-0 base in the Faded buffer
    PLTT_UNFADED_OBJ = PLTT_FADED_OBJ - 0x400
    log(fmt("  → FadedOBJ(slot0)=%s  UnfadedOBJ(slot0)=%s", hex(PLTT_FADED_OBJ), hex(PLTT_UNFADED_OBJ)))
    con(fmt("[F8] ✓ FadedOBJ=%s UnfadedOBJ=%s (%d matches). Re-run F7.", hex(PLTT_FADED_OBJ), hex(PLTT_UNFADED_OBJ), #matches))
    flush()
end

-- ── F7: validate the REAL feature mechanism on the local trainer ───────────────────
-- Clone the player (keeps the player's REAL ROM images → renders YOUR trainer), but
-- load the palette via palTag→table into a FRESH OBJ slot and point oam there.  If
-- your trainer renders with CORRECT colours through a fresh slot, the palette path
-- works and the cross-machine feature is just: broadcast sprite.images + palTag.
local function spawnRealMechanism()
    if _act then  -- reuse the F3 teardown
        if _obj then w8(OBJ_BASE+_obj*OBJ_STRIDE+OFF_FLAGS,0x00) end
        if _spr then local b=GSPR_BASE+_spr*GSPR_STRIDE+SPR_BYTE3E; w8(b,r8(b)&0xFE) end
        if _tile then bitmap_set(_tile,_tn,false) end
        _act=false; con("[F7] cleared."); return
    end
    local p_sid = r8(OBJ_BASE+OFF_SPR_ID)
    if p_sid >= 64 then con("[F7] player sprite invalid."); return end
    local pgfx = r8(OBJ_BASE+OFF_GFX_ID)
    local gi = gi_ptr(pgfx)
    local fs; for s=63,1,-1 do if s~=p_sid and (r8(GSPR_BASE+s*GSPR_STRIDE+SPR_BYTE3E)&0x01)==0 then fs=s break end end
    local fo; for o=1,OBJ_COUNT-1 do if (r8(OBJ_BASE+o*OBJ_STRIDE+OFF_FLAGS)&0x01)==0 then fo=o break end end
    if not fs or not fo then con("[F7] no free slot."); return end
    _spr, _obj = fs, fo
    local paddr, naddr = GSPR_BASE+p_sid*GSPR_STRIDE, GSPR_BASE+fs*GSPR_STRIDE
    for i=0,GSPR_STRIDE-1 do w8(naddr+i, r8(paddr+i)) end   -- clone keeps the player's REAL images/anims
    _tn = 8
    _tile = claim_tiles(_tn); bitmap_set(_tile,_tn,true)
    -- PALETTE into a FRESH slot (the cross-machine path): tag → table → ROM data → DMA
    local tag = gi and r16(gi+GI_PALTAG) or 0
    local pdata = palette_data_for_tag(tag)
    local a2 = r16(naddr+SPR_OAM2)
    local palSlot = (a2 >> 12) & 0x0F
    if pdata and PLTT_FADED_OBJ then
        palSlot = claim_palette_slot()
        for i=0,15 do
            local c = r16(pdata + i*2)
            w16(PLTT_UNFADED_OBJ + palSlot*0x20 + i*2, c)  -- source (survives day/night recompute)
            w16(PLTT_FADED_OBJ   + palSlot*0x20 + i*2, c)  -- transferred to palette RAM
            w16(OBJ_PLTT         + palSlot*0x20 + i*2, c)  -- immediate (this frame)
        end
        log(fmt("[F7] palette tag=0x%04X from %s → fresh OBJ slot %d (shadow buffers)", tag, hex(pdata), palSlot))
        con(fmt("[F7] loaded palette tag=0x%04X into FRESH slot %d (Unfaded+Faded+PLTT)", tag, palSlot))
    elseif pdata then
        con("[F7] run F8 first (need the palette shadow buffers, else colours get overwritten → black)")
        palSlot = claim_palette_slot()
        for i=0,15 do w16(OBJ_PLTT + palSlot*0x20 + i*2, r16(pdata + i*2)) end
    else
        con(fmt("[F7] palette tag=0x%04X NOT found (run F2 first) — using player slot", tag))
    end
    w16(naddr+SPR_OAM2, (_tile & 0x03FF) | (a2 & 0x0C00) | ((palSlot & 0x0F) << 12))
    w8(naddr+SPR_BYTE3E, (r8(naddr+SPR_BYTE3E)|0x01)&0xFB)
    ws16(naddr+SPR_DATA0, fo)
    w8(naddr+SPR_BYTE3F, r8(naddr+SPR_BYTE3F)|0x04)
    w8(naddr+SPR_BYTE2C, r8(naddr+SPR_BYTE2C)&0xBF)
    local nobj = OBJ_BASE+fo*OBJ_STRIDE
    local px,py = rs16(OBJ_BASE+OFF_CURX), rs16(OBJ_BASE+OFF_CURY)
    for i=0,OBJ_STRIDE-1 do w8(nobj+i,0) end
    w8(nobj+OFF_FLAGS,0x01); w8(nobj+OFF_SPR_ID,fs); w8(nobj+OFF_LOCAL_ID,0xFD); w8(nobj+OFF_MOV_TYPE,0x00)
    w8(nobj+OFF_MAP_N,r8(OBJ_BASE+OFF_MAP_N)); w8(nobj+OFF_MAP_G,r8(OBJ_BASE+OFF_MAP_G))
    ws16(nobj+OFF_CURX,px); ws16(nobj+OFF_CURY,py); ws16(nobj+OFF_PREVX,px); ws16(nobj+OFF_PREVY,py)
    _act = true
    con("[F7] rendered YOUR trainer via a FRESH palette slot. Right shape + colours? F7=clear.")
    flush()
end

local function onFrame()
    if _act and _spr then
        local p_sid = r8(OBJ_BASE+OFF_SPR_ID)
        if p_sid < 64 and (r8(GSPR_BASE+_spr*GSPR_STRIDE+SPR_BYTE3E)&0x01) ~= 0 then
            local psa, nsa = GSPR_BASE+p_sid*GSPR_STRIDE, GSPR_BASE+_spr*GSPR_STRIDE
            ws16(nsa+SPR_X, rs16(psa+SPR_X))
            ws16(nsa+SPR_Y, rs16(psa+SPR_Y) + 16)
            w8(nsa+SPR_BYTE3E, r8(nsa+SPR_BYTE3E) | (r8(psa+SPR_BYTE3E) & 0x02))
            w16(nsa+SPR_OAM2, (r16(nsa+SPR_OAM2) & 0xFC00) | (_tile & 0x03FF))
        end
    end
end

-- ── F9: find sSpritePaletteTags (the OBJ palette SLOT manager) ──────────────────────
-- 16 u16, one per OBJ palette slot, holding the TAG occupying each slot (free = 0xFFFF
-- or 0).  The engine reuses a slot whose tag is free.  Our injected ghost shares the
-- player's slot and desyncs the ref-count → the engine reuses slot 0 → player+ghost
-- corrupt.  With this address we can RESERVE a dedicated slot (set its tag) so the
-- ghost gets its own protected palette and never touches the player's.
-- Find it: sSpritePaletteTags[playerSlot] == the player's GI paletteTag.
local function findPaletteTags()
    local sid = r8(OBJ_BASE + OFF_SPR_ID)
    if sid >= 64 then con("[F9] player sprite invalid."); return end
    local gi = gi_ptr(r8(OBJ_BASE + OFF_GFX_ID))
    if not gi then con("[F9] no player GI."); return end
    local palTag = r16(gi + GI_PALTAG)
    local pslot  = (r16(GSPR_BASE + sid*GSPR_STRIDE + SPR_OAM2) >> 12) & 0x0F
    log(""); log(fmt("[F9] sSpritePaletteTags search: player palTag=0x%04X slot=%d", palTag, pslot))
    con(fmt("[F9] Scanning EWRAM for sSpritePaletteTags (palTag=0x%04X @ slot %d)... please wait.", palTag, pslot))
    local function score_tags(A)  -- how many of the 16 entries look like real tags?
        local ok = 0
        for i = 0, 15 do
            local t = r16(A + i*2)
            if t == 0xFFFF or t == 0x0000 or (t >= 0x1000 and t <= 0x1FFF) then ok = ok + 1 end
        end
        return ok
    end
    local best, best_score = nil, -1
    for A = 0x02000000, 0x0203FFE0, 2 do
        if r16(A + pslot*2) == palTag then
            local s = score_tags(A)
            if s > best_score then best, best_score = A, s end
        end
    end
    if best and best_score >= 13 then
        log(fmt("  ✓ sSpritePaletteTags = %s  (slot-0 base; %d/16 tag-like)", hex(best - pslot*2), best_score))
        local line = "    tags:"; for i = 0, 15 do line = line .. fmt(" %04X", r16(best - pslot*2 + i*2)) end
        log(line)
        con(fmt("[F9] ✓ sSpritePaletteTags = %s (%d/16 tag-like). See log for the 16 tags.", hex(best - pslot*2), best_score))
    else
        log(fmt("  ✗ no strong match (best %s score %d).", best and hex(best) or "nil", best_score))
        con("[F9] ✗ not found — see log.")
    end
    flush()
end

-- ── keys ──────────────────────────────────────────────────────────────────────────
local _prev = {}
event.unregisterbyname("trainer_sprite_keys")
event.onframeend(function()
    local k = input.get()
    if k["F1"] and not _prev["F1"] then dumpPlayer() end
    if k["F2"] and not _prev["F2"] then findPaletteTable() end
    if k["F3"] and not _prev["F3"] then spawnTrainer() end
    if k["F4"] and not _prev["F4"] then TARGET_GFX = r8(OBJ_BASE+OFF_GFX_ID); con(fmt("[F4] TARGET_GFX = your own trainer gfx = %d (now press F3)", TARGET_GFX)) end
    if k["F5"] and not _prev["F5"] then TARGET_GFX = math.max(0, TARGET_GFX-1); con(fmt("[F5] TARGET_GFX=%d", TARGET_GFX)) end
    if k["F6"] and not _prev["F6"] then TARGET_GFX = TARGET_GFX+1; con(fmt("[F6] TARGET_GFX=%d", TARGET_GFX)) end
    if k["F7"] and not _prev["F7"] then spawnRealMechanism() end
    if k["F8"] and not _prev["F8"] then findPlttBuffers() end
    if k["F9"] and not _prev["F9"] then findPaletteTags() end
    onFrame()
    _prev = k
end, "trainer_sprite_keys")

-- validate the GI table on load
do
    local gfx = r8(OBJ_BASE+OFF_GFX_ID)
    local gi = gi_ptr(gfx)
    local sid = r8(OBJ_BASE+OFF_SPR_ID)
    local ok = gi and sid < 64 and r32(gi+GI_IMG_OFF) == r32(GSPR_BASE+sid*GSPR_STRIDE+SPR_IMAGES)
    con("")
    con("════════════════════════════════════════════════════════════════")
    con("  SLINK PEER-GHOST — TRAINER SPRITE test")
    con(fmt("    GI table %s %s", hex(GFX_TABLE), ok and "(validated)" or "(!! validation FAILED — table shifted?)"))
    con("    F1: dump your trainer   F2: find palette table   F3: render TARGET_GFX")
    con("    F4: TARGET_GFX=your trainer   F5/F6: TARGET_GFX -/+")
    con("    F8: find palette shadow buffers (run BEFORE F7)")
    con("    F7: VALIDATE — render YOUR trainer via a fresh palette slot (the real path)")
    con(fmt("  Output: %s", OUT_PATH or "(file write failed)"))
    con("════════════════════════════════════════════════════════════════")
    con("")
end
flush()
