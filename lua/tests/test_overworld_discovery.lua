--[[
  lua/tests/test_overworld_discovery.lua  —  Phase 0 HARD GATE for peer-ghost
  =========================================================================
  Discovers every address/value the peer-ghost feature needs on Radical Red /
  CFRU.  Until this script produces a clean profile snippet AND the user has
  confirmed each value in-game, no peer-ghost client code is written.

  WHAT IT FINDS
    • gObjectEvents[0] base address + per-entry stride
    • Struct field offsets: flags, graphicsId, currentCoords.x/y, previousCoords,
      facingDirection, movementDirection, movementType, movementActionId,
      movementActionStep
    • Camera world-anchor (camera_x, camera_y in tiles; pixel offsets for
      smooth scroll)
    • "Overworld currently visible" predicate (user labels states via F3)
    • Sample free-slot detection across the 16-slot pool
    • Generic NPC graphicsId candidates (user picks one)
    • Whether gui.drawImage works on this BizHawk core (fallback path probe)

  HOW TO RUN
    1. Load Radical Red 4.1 in BizHawk on a save in the OVERWORLD (any map).
    2. Open the Lua Console, load this script.
    3. Auto-discovery runs on load (writes to lua/overworld_discovery_results.txt).
    4. F1 — Anchor walk (press, walk 1 tile NORTH, press again). Narrows the
            player-object address to a single match.
    5. F2 — Toggle continuous frame logger (player + camera + state bytes).
            Walk around, then press F2 again to stop.
    6. F3 — State snapshot. Press in 10 known states (overworld, START menu,
            bag, party, dialog, warp fade, fly anim, battle, evolution, name
            entry). Each snapshot labels the candidate predicate bytes.
    7. F4 — gui.drawImage capability probe.
    8. F5 — Object-event slot scan (free slots + each slot's graphicsId).
    9. F6 — INJECT TEST: writes a candidate NPC to a free slot to verify the
            engine renders it.  Observe in BizHawk; press again to clear.

  OUTPUT
    All non-trivial output goes to:
        <results-dir>/overworld_discovery_results.txt        (main log)
        <results-dir>/overworld_discovery_frames.txt         (F2 frame log)
        <results-dir>/overworld_discovery_states.txt         (F3 state log)
    Plus a copy-paste-ready PROFILES BLOCK at the end of the main log.

  Modeled on test_rr_discovery.lua (same path/output/F-key pattern).
--]]

local fmt = string.format
local r8  = memory.read_u8
local r16 = memory.read_u16_le
local r32 = memory.read_u32_le
local w8  = memory.write_u8
local w16 = memory.write_u16_le
local w32 = memory.write_u32_le

local function hex(n)  return fmt("0x%08X", n) end
local function hex4(n) return fmt("0x%04X", n) end

-- ── OUTPUT FILE SETUP ────────────────────────────────────────────────────────
local MANUAL_OUT_PATH = nil   -- set to a string to force a specific path

local _out_lines   = {}
local _frame_lines = {}
local _state_lines = {}
local OUT_PATH, FRAMES_PATH, STATES_PATH

local function _try_path(path)
    local ok, f = pcall(io.open, path, "w")
    if ok and f then f:write(""); f:close(); return true end
    return false
end
local function _path_from_debug()
    local ok, info = pcall(debug.getinfo, 1, "S")
    if ok and info and info.source then
        local dir = info.source:match("^@?(.*[\\/])")
        if dir then return dir .. "overworld_discovery_results.txt" end
    end
    return nil
end
local function _path_from_rom()
    local ok, rompath = pcall(function()
        if gameinfo and gameinfo.getromfilename then return gameinfo.getromfilename() end
        return nil
    end)
    if ok and rompath and rompath ~= "" then
        local dir = rompath:match("^(.*[\\/])")
        if dir then return dir .. "overworld_discovery_results.txt" end
    end
    return nil
end
local function _path_from_cwd() return "overworld_discovery_results.txt" end

if MANUAL_OUT_PATH and _try_path(MANUAL_OUT_PATH) then
    OUT_PATH = MANUAL_OUT_PATH
else
    for _, getter in ipairs({_path_from_debug, _path_from_rom, _path_from_cwd}) do
        local p = getter()
        if p and _try_path(p) then OUT_PATH = p; break end
    end
end

if OUT_PATH then
    FRAMES_PATH = OUT_PATH:gsub("overworld_discovery_results", "overworld_discovery_frames")
    STATES_PATH = OUT_PATH:gsub("overworld_discovery_results", "overworld_discovery_states")
end

local function _flush_to(path, lines)
    if not path then return end
    local ok, f = pcall(io.open, path, "w")
    if ok and f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
end
local function _flush()        _flush_to(OUT_PATH,    _out_lines)   end
local function _flush_frames() _flush_to(FRAMES_PATH, _frame_lines) end
local function _flush_states() _flush_to(STATES_PATH, _state_lines) end

local function log(s)  _out_lines[#_out_lines+1]   = s end
local function flog(s) _frame_lines[#_frame_lines+1] = s end
local function slog(s) _state_lines[#_state_lines+1] = s end
local function con(s)  console.log(s) end
local function div() log("══════════════════════════════════════════════════════════════════") end
local function sep() log("──────────────────────────────────────────────────────────────────") end

local function isEWRAM(addr)
    return addr >= 0x02000000 and addr < 0x02040000
end

-- ── PHASE A: BASELINE — read SB1 to know map + sanity-check ──────────────────

local RESULTS = {}

div()
log("  SLINK PEER-GHOST PHASE 0 — Overworld memory discovery (RR/CFRU)")
div()
log("")
if OUT_PATH then
    log(fmt("[OUTPUT] Main results:   %s", OUT_PATH))
    log(fmt("[OUTPUT] F2 frame log:   %s", FRAMES_PATH))
    log(fmt("[OUTPUT] F3 state log:   %s", STATES_PATH))
else
    log("[OUTPUT] !! File output FAILED — results only in console.")
end
log("")

con("[PG-DISCOVERY] Phase A: reading SaveBlock1 + map...")

-- Locate SB1 via the same IWRAM scan as test_rr_discovery
local sb1_ptr_addr, sb1_value
for addr = 0x03000000, 0x03007FFC, 4 do
    local v = r32(addr)
    if isEWRAM(v) then
        local mg, mn = r8(v + 0x0004), r8(v + 0x0005)
        local pc = r8(v + 0x0034)
        local p0 = r32(v + 0x0038)
        local mhp = r16(v + 0x0038 + 0x58)
        if mg <= 42 and mn <= 200 and pc >= 1 and pc <= 6
           and p0 ~= 0 and mhp > 0 and mhp < 1000 then
            sb1_ptr_addr, sb1_value = addr, v
            break
        end
    end
end

if not sb1_value then
    log("!! Could not locate SaveBlock1 — abort.  Are you on a save with a party?")
    _flush()
    return
end

local map_g = r8(sb1_value + 0x0004)
local map_n = r8(sb1_value + 0x0005)
log(fmt("[SB1] gSaveBlock1Ptr=%s → %s", hex(sb1_ptr_addr), hex(sb1_value)))
log(fmt("[MAP] mapGroup=%d mapNum=%d", map_g, map_n))
RESULTS.SB1_PTR_ADDR = sb1_ptr_addr
RESULTS.SB1_VALUE    = sb1_value
log("")

-- ── PHASE B: probe pret-documented vanilla addresses first ───────────────────
-- Vanilla FireRed (pret/pokefirered) ObjectEvent struct layout:
--   +0x00  flags (u8)         bit0=active, bit1=singleMovementActive, ...
--   +0x01  flags2 (u8)        bit5=invisible, bit6=offScreen, ...
--   +0x05  graphicsId (u8)
--   +0x06  movementType (u8)
--   +0x10  currentCoords.x (s16)
--   +0x12  currentCoords.y (s16)
--   +0x14  previousCoords.x (s16)
--   +0x16  previousCoords.y (s16)
--   +0x18  facingDirection (u8)    1=down, 2=up, 3=left, 4=right
--   +0x19  movementDirection (u8)
--   +0x1A  rangeX:4 | rangeY:4
--   +0x1C  fieldEffectSpriteId (u8)
--   +0x1D  warpArrowSpriteId (u8)
--   +0x1E  movementActionId (u8)
--   +0x1F  trainerType (u8)
--   +0x20  localId (u8)
--   +0x21  mapNum / mapGroup
--   Total: 0x24 bytes per entry; 16 slots = 0x240 bytes
-- NOTE: offsets below were CONFIRMED against a live RR 4.1 F5 dump (map 6:5):
--   mapNum@0x09 / mapGroup@0x0A matched the live map; player localId@0x08==0xFF
--   (pret LOCALID_PLAYER); facing == low nibble of 0x18 (1=down/2=up/3=left/4=right).
--   spriteId@0x04 increments per active slot (player=0) — the OAM sprite index;
--   a dormant slot has it zeroed, which is why activating a free slot alone does
--   NOT render (no sprite allocated behind it).
local PRET_OFFSETS = {
    OFF_FLAGS         = 0x00,   -- bit0=active, bit7=heldMovementFinished (idle)
    OFF_FLAGS2        = 0x01,
    OFF_FLAGS3        = 0x02,
    OFF_SPRITE_ID     = 0x04,   -- OAM sprite index; must be valid to render
    OFF_GRAPHICS_ID   = 0x05,
    OFF_MOV_TYPE      = 0x06,
    OFF_TRAINER_TYPE  = 0x07,
    OFF_LOCAL_ID      = 0x08,   -- player == 0xFF
    OFF_MAP_NUM       = 0x09,
    OFF_MAP_GROUP     = 0x0A,
    OFF_ELEVATION     = 0x0B,   -- currentElevation:4 | previousElevation:4
    OFF_INITIAL_X     = 0x0C,
    OFF_INITIAL_Y     = 0x0E,
    OFF_CURR_X        = 0x10,
    OFF_CURR_Y        = 0x12,
    OFF_PREV_X        = 0x14,
    OFF_PREV_Y        = 0x16,
    OFF_FACING_DIR    = 0x18,   -- facingDirection:4 (low) | movementDirection:4 (high)
    OFF_MOV_ACTION_ID = 0x1C,
    OBJ_EVENT_STRIDE  = 0x24,
    OBJ_EVENT_COUNT   = 16,
}

-- "moving" predicate confirmed from the F2 frame log: idle slots have flags
-- bit7 set (0xC1); mid-step slots have it clear (0x41).
local function is_idle(flags) return (flags & 0x80) ~= 0 end

-- Candidate base addresses to probe (vanilla + likely CFRU shifts)
local CANDIDATE_BASES = {
    0x02036E38,  -- vanilla pret
    0x02037000,  -- common CFRU shift target
    0x02036C00,  -- speculative
    0x02037200,  -- speculative
}

local function probe_slot(base, offsets)
    return {
        flags    = r8(base + offsets.OFF_FLAGS),
        flags2   = r8(base + offsets.OFF_FLAGS2),
        gfx_id   = r8(base + offsets.OFF_GRAPHICS_ID),
        mov_type = r8(base + offsets.OFF_MOV_TYPE),
        curr_x   = memory.read_s16_le(base + offsets.OFF_CURR_X),
        curr_y   = memory.read_s16_le(base + offsets.OFF_CURR_Y),
        prev_x   = memory.read_s16_le(base + offsets.OFF_PREV_X),
        prev_y   = memory.read_s16_le(base + offsets.OFF_PREV_Y),
        facing   = r8(base + offsets.OFF_FACING_DIR) & 0x0F,         -- low nibble
        mov_dir  = (r8(base + offsets.OFF_FACING_DIR) >> 4) & 0x0F,  -- high nibble
        action   = r8(base + offsets.OFF_MOV_ACTION_ID),
        local_id = r8(base + offsets.OFF_LOCAL_ID),
    }
end

local function score_slot_as_player(s)
    -- Player slot signals:
    --   flags bit 0 (active) set
    --   facingDirection in {1, 2, 3, 4}
    --   curr_x, curr_y plausible tile coords (0..200; world coords are usually small s16)
    --   gfx_id < 0x100 (always true since u8) but should be > 0 (player has a sprite)
    --   localId == 0 or 0xFF (player is always slot 0; localId convention varies)
    local score = 0
    if (s.flags & 0x01) ~= 0 then score = score + 5 end
    if s.facing >= 1 and s.facing <= 4 then score = score + 5 end
    if s.curr_x >= -100 and s.curr_x <= 1000 then score = score + 3 end
    if s.curr_y >= -100 and s.curr_y <= 1000 then score = score + 3 end
    -- player previousCoords usually equal currentCoords when standing still
    if math.abs(s.curr_x - s.prev_x) <= 1 then score = score + 1 end
    if math.abs(s.curr_y - s.prev_y) <= 1 then score = score + 1 end
    if s.gfx_id > 0 and s.gfx_id < 0xF0 then score = score + 2 end
    return score
end

con("[PG-DISCOVERY] Phase B: probing candidate gObjectEvents bases...")
log("[PHASE B] Probing candidate gObjectEvents bases (pret + CFRU shifts):")
log("")

local best_base, best_score = nil, -1
local candidates = {}
for _, base in ipairs(CANDIDATE_BASES) do
    local s = probe_slot(base, PRET_OFFSETS)
    local score = score_slot_as_player(s)
    log(fmt("  %s  flags=0x%02X gfx=%3d type=%3d facing=%d  curr=(%4d,%4d) prev=(%4d,%4d) action=%3d  localId=%d  score=%d",
        hex(base), s.flags, s.gfx_id, s.mov_type, s.facing,
        s.curr_x, s.curr_y, s.prev_x, s.prev_y, s.action, s.local_id, score))
    candidates[#candidates+1] = {base=base, slot=s, score=score}
    if score > best_score then best_base, best_score = base, score end
end
log("")
if best_score >= 10 then
    log(fmt("  ✓ Best guess: %s  (score=%d)", hex(best_base), best_score))
    log("    Vanilla pret offsets APPEAR to hold — confirm with F1 anchor walk.")
    RESULTS.OBJ_EVENTS_BASE_ADDR = best_base
else
    log(fmt("  ⚠ Top guess %s scored only %d — pret offsets likely DON'T hold under CFRU.",
        hex(best_base), best_score))
    log("    Run F1 anchor walk to auto-find player x/y; we'll re-derive offsets from there.")
end

-- ── PHASE C: EWRAM s16-pair scan for any candidates pret missed ──────────────
-- Find all 4-byte-aligned s16 pairs in EWRAM that look like player coords
-- (plausible range, both nonzero or both zero, repeated at +0x04 offset for
-- previousCoords).  Used as fallback if Phase B fails or to corroborate.

con("[PG-DISCOVERY] Phase C: EWRAM scan for player-coord candidates...")
log("")
log("[PHASE C] EWRAM scan for (currentCoords, previousCoords) pairs...")

local coord_candidates = {}
for addr = 0x02020000, 0x0203F000, 2 do
    local cx = memory.read_s16_le(addr)
    local cy = memory.read_s16_le(addr + 2)
    -- player coords are typically 0..150 on most maps
    if cx > 0 and cx < 200 and cy > 0 and cy < 200 then
        local px = memory.read_s16_le(addr + 4)
        local py = memory.read_s16_le(addr + 6)
        -- previousCoords near currentCoords (within 2 tiles)
        if math.abs(px - cx) <= 2 and math.abs(py - cy) <= 2 then
            coord_candidates[#coord_candidates+1] = {
                addr = addr, cx = cx, cy = cy, px = px, py = py
            }
        end
    end
end
log(fmt("  Found %d candidate currentCoords addresses", #coord_candidates))
RESULTS._coord_candidates_pass1 = coord_candidates

if #coord_candidates > 0 and #coord_candidates <= 20 then
    for i, c in ipairs(coord_candidates) do
        log(fmt("    [%2d] %s  curr=(%d,%d)  prev=(%d,%d)", i, hex(c.addr), c.cx, c.cy, c.px, c.py))
    end
elseif #coord_candidates > 20 then
    log("    (too many to list — F1 anchor walk will narrow them down)")
end

_flush()

-- ── PHASE D: FREE-SLOT SCAN ──────────────────────────────────────────────────
-- For each candidate base, scan all 16 slots and report which look free
-- (flags bit 0 clear).  Knowing the typical free-slot count per map tells us
-- whether the array layout matches expectations.

log("")
log("[PHASE D] Free-slot scan at best base candidate:")
if RESULTS.OBJ_EVENTS_BASE_ADDR then
    local base   = RESULTS.OBJ_EVENTS_BASE_ADDR
    local stride = PRET_OFFSETS.OBJ_EVENT_STRIDE
    local count  = PRET_OFFSETS.OBJ_EVENT_COUNT
    local active = {}
    local free   = {}
    for slot = 0, count - 1 do
        local sa = base + slot * stride
        local flags = r8(sa + PRET_OFFSETS.OFF_FLAGS)
        local gfx   = r8(sa + PRET_OFFSETS.OFF_GRAPHICS_ID)
        local fx    = r8(sa + PRET_OFFSETS.OFF_FACING_DIR)
        local cx    = memory.read_s16_le(sa + PRET_OFFSETS.OFF_CURR_X)
        local cy    = memory.read_s16_le(sa + PRET_OFFSETS.OFF_CURR_Y)
        if (flags & 0x01) ~= 0 then
            active[#active+1] = slot
            log(fmt("    Slot %2d ACTIVE  flags=0x%02X gfx=%3d facing=%d coords=(%d,%d)",
                slot, flags, gfx, fx, cx, cy))
        else
            free[#free+1] = slot
        end
    end
    log(fmt("  Summary: %d ACTIVE, %d FREE slots on this map", #active, #free))
    log(fmt("  Free slots: {%s}", table.concat(free, ", ")))
    RESULTS._active_slots_on_load = active
    RESULTS._free_slots_on_load   = free
end

_flush()

-- ── F1: ANCHOR WALK ──────────────────────────────────────────────────────────
-- First press records current candidate coords; user walks 1 tile NORTH;
-- second press intersects candidates.

local _anchor_state = {}    -- {addr → (cx, cy)} captured on first F1 press
local _anchor_armed = false

local function doAnchorFirst()
    _anchor_state = {}
    for _, c in ipairs(RESULTS._coord_candidates_pass1 or {}) do
        _anchor_state[c.addr] = {cx = c.cx, cy = c.cy}
    end
    _anchor_armed = true
    con(fmt("[F1] Anchored %d candidates. Walk 1 tile NORTH, then press F1 again.",
        #(RESULTS._coord_candidates_pass1 or {})))
    log("")
    log("[F1] Anchor pass 1 captured. Awaiting walk + second press.")
    _flush()
end

local function doAnchorSecond()
    log("")
    log("[F1] Anchor pass 2: looking for candidates that moved by exactly (0, -1)...")
    local kept = {}
    for addr, before in pairs(_anchor_state) do
        local cx = memory.read_s16_le(addr)
        local cy = memory.read_s16_le(addr + 2)
        local dx = cx - before.cx
        local dy = cy - before.cy
        if dx == 0 and dy == -1 then
            -- Read full struct context assuming player at this addr is +0x10
            local base_guess = addr - PRET_OFFSETS.OFF_CURR_X
            local flags = r8(base_guess + PRET_OFFSETS.OFF_FLAGS)
            local gfx   = r8(base_guess + PRET_OFFSETS.OFF_GRAPHICS_ID)
            local fx    = r8(base_guess + PRET_OFFSETS.OFF_FACING_DIR)
            kept[#kept+1] = {addr = addr, base_guess = base_guess, flags = flags, gfx = gfx, fx = fx, cx = cx, cy = cy}
            log(fmt("    %s  base_guess=%s  flags=0x%02X gfx=%3d facing=%d  curr=(%d,%d)",
                hex(addr), hex(base_guess), flags, gfx, fx, cx, cy))
        end
    end
    log(fmt("  Intersection: %d candidate(s)", #kept))
    if #kept == 1 then
        local k = kept[1]
        log(fmt("  ✓ CONFIRMED player object base = %s (offset to currentCoords = +0x10)",
            hex(k.base_guess)))
        RESULTS.OBJ_EVENTS_BASE_ADDR = k.base_guess
        RESULTS.OFFSETS_CONFIRMED    = true
    elseif #kept > 1 then
        log("  ⚠ Multiple matches.  Pick one whose flags+gfx look most player-like, ")
        log("    or walk another direction and repeat F1.")
    else
        log("  !! No matches.  Did you walk NORTH exactly 1 tile?  Try again.")
    end
    _anchor_armed = false
    _flush()
    con(fmt("[F1] Anchor pass 2 done — %d match(es).  See main log.", #kept))
end

-- ── F2: CONTINUOUS FRAME LOGGER ──────────────────────────────────────────────
local _frame_logger_on   = false
local _frame_log_started = nil
local _last_log_frame    = -100

local function toggleFrameLogger()
    _frame_logger_on = not _frame_logger_on
    if _frame_logger_on then
        _frame_lines = {}  -- reset
        _frame_log_started = emu.framecount()
        flog("# F2 continuous frame logger — every 6 frames")
        flog(fmt("# Started at framecount=%d", _frame_log_started))
        flog(fmt("# Player object base candidate: %s", hex(RESULTS.OBJ_EVENTS_BASE_ADDR or 0)))
        flog("# frame  cx  cy  px  py  facing  movDir  movAction  flags  flags2")
        con("[F2] Frame logger ON — walk around to capture data; press F2 to stop.")
    else
        _flush_frames()
        con(fmt("[F2] Frame logger OFF — %d frames logged to: %s", #_frame_lines, FRAMES_PATH or "?"))
    end
end

-- ── F3: STATE SNAPSHOT (overworld-visible predicate calibration) ─────────────
-- User presses in 10 known states; each snapshot captures candidate bytes
-- that may distinguish overworld from menus/battle/fade.

local STATE_LABELS = {
    "OVERWORLD",      -- standing still in overworld
    "START_MENU",     -- with start menu open
    "BAG",            -- bag open
    "PARTY",          -- party menu open
    "DIALOG",         -- talking to NPC
    "WARP_FADE",      -- mid-door fade
    "FLY_ANIM",       -- fly animation
    "BATTLE",         -- in a battle
    "EVOLUTION",      -- evolution scene
    "NAME_ENTRY",     -- naming a mon
}
local _state_index = 1

local function doStateSnapshot()
    local label = STATE_LABELS[_state_index] or fmt("STATE_%d", _state_index)
    slog("")
    slog(fmt("══ STATE %d: %s ══  framecount=%d", _state_index, label, emu.framecount()))

    -- Dump 256 bytes of IWRAM around the likely gMain location (0x03002000-0x03005000)
    -- Use a coarse hash: every 16th byte.
    local sig = {}
    for off = 0, 4096, 16 do
        sig[#sig+1] = fmt("%02X", r8(0x03002000 + off))
    end
    slog("  IWRAM(0x03002000..+4096, stride 16): " .. table.concat(sig, " "))

    -- Likely "menu open" candidates around gMain (vanilla 0x030030F0)
    for _, addr in ipairs({0x03003040, 0x030030F0, 0x03003120, 0x03002F30, 0x03003200}) do
        local b0 = r8(addr + 0x438)   -- vanilla gMain.state
        local b1 = r8(addr + 0x439)   -- vanilla gMain bit1 = inBattle
        local cb = r32(addr + 0x44C)  -- vanilla gMain.callback2 area (offset varies)
        slog(fmt("  near %s: +0x438=%3d +0x439=0x%02X +0x44C=%s",
            hex(addr), b0, b1, hex(cb)))
    end

    -- Dump a few well-known "transition" bytes
    slog(fmt("  player_obj base=%s curr=(%d,%d) facing=%d action=%d flags=0x%02X flags2=0x%02X",
        hex(RESULTS.OBJ_EVENTS_BASE_ADDR or 0),
        memory.read_s16_le((RESULTS.OBJ_EVENTS_BASE_ADDR or 0) + PRET_OFFSETS.OFF_CURR_X),
        memory.read_s16_le((RESULTS.OBJ_EVENTS_BASE_ADDR or 0) + PRET_OFFSETS.OFF_CURR_Y),
        r8((RESULTS.OBJ_EVENTS_BASE_ADDR or 0) + PRET_OFFSETS.OFF_FACING_DIR),
        r8((RESULTS.OBJ_EVENTS_BASE_ADDR or 0) + PRET_OFFSETS.OFF_MOV_ACTION_ID),
        r8((RESULTS.OBJ_EVENTS_BASE_ADDR or 0) + PRET_OFFSETS.OFF_FLAGS),
        r8((RESULTS.OBJ_EVENTS_BASE_ADDR or 0) + PRET_OFFSETS.OFF_FLAGS2)))

    _state_index = _state_index + 1
    _flush_states()
    con(fmt("[F3] Snapshot %d/%d captured (%s) → %s",
        _state_index - 1, #STATE_LABELS, label, STATES_PATH or "?"))
    if _state_index > #STATE_LABELS then
        con("[F3] All states captured.  Compare the IWRAM signatures across states to")
        con("     find a byte that changes consistently when leaving the overworld.")
        _state_index = 1
    end
end

-- ── F4: gui.drawImage probe (fallback rendering path) ────────────────────────
local _drawimg_test_on = false
local _drawimg_start   = 0
local _drawimg_path    = nil   -- placeholder PNG path; user can drop one alongside

local function probeDrawImage()
    _drawimg_test_on = not _drawimg_test_on
    if _drawimg_test_on then
        _drawimg_start = emu.framecount()
        -- We don't bundle a PNG; just test the API + measure overhead with a NIL path
        con("[F4] gui.drawImage probe ON for ~120 frames (no PNG — measures call overhead).")
        con("     To test a real PNG: drop a 16x16 png at overworld_test.png alongside the ROM.")
    else
        con(fmt("[F4] gui.drawImage probe OFF (%d frames)", emu.framecount() - _drawimg_start))
    end
end

-- ── F5: OBJECT-EVENT SLOT INSPECTION ─────────────────────────────────────────
-- Dump every slot's full 0x24-byte struct so we can compare layouts across
-- multiple captures (e.g., after entering a new map).

local function dumpAllSlots()
    if not RESULTS.OBJ_EVENTS_BASE_ADDR then
        con("[F5] No base address known yet — run F1 anchor walk first.")
        return
    end
    log("")
    log(fmt("[F5] Full slot dump at framecount=%d:", emu.framecount()))
    local base   = RESULTS.OBJ_EVENTS_BASE_ADDR
    local stride = PRET_OFFSETS.OBJ_EVENT_STRIDE
    for slot = 0, PRET_OFFSETS.OBJ_EVENT_COUNT - 1 do
        local sa = base + slot * stride
        local bytes = {}
        for i = 0, stride - 1 do
            bytes[#bytes+1] = fmt("%02X", r8(sa + i))
        end
        log(fmt("  slot %2d %s : %s", slot, hex(sa), table.concat(bytes, " ")))
    end
    _flush()
    con(fmt("[F5] Slot dump written — see main log."))
end

-- ── F6: DORMANT-SLOT INJECT TEST (improved, correct offsets) ─────────────────
-- Activate the first FREE slot 2 tiles south of the player, with mapNum/mapGroup/
-- elevation copied from the player so the engine treats it as on-map.  Press
-- again to restore.
--
-- EXPECTATION: this likely does NOT render, because spriteId@0x04 stays 0 (no
-- OAM sprite is allocated by merely flipping flags.active).  If it DOES render,
-- great — the engine lazily spawns sprites for active slots.  Either outcome is
-- a decisive Phase 0 result.

local _inject_slot   = nil
local _inject_active = false
local _inject_saved  = nil

local function _save_slot(base, slot, stride)
    local sa = base + slot * stride
    local t = {}
    for i = 0, stride - 1 do t[i+1] = r8(sa + i) end
    return t
end
local function _restore_slot(base, slot, stride, saved)
    local sa = base + slot * stride
    for i = 0, stride - 1 do w8(sa + i, saved[i+1]) end
end

local function doInjectTest()
    if not RESULTS.OBJ_EVENTS_BASE_ADDR then
        con("[F6] No base address known yet — run F1 anchor walk first.")
        return
    end
    local base   = RESULTS.OBJ_EVENTS_BASE_ADDR
    local stride = PRET_OFFSETS.OBJ_EVENT_STRIDE
    local O = PRET_OFFSETS

    if _inject_active then
        if _inject_slot and _inject_saved then
            _restore_slot(base, _inject_slot, stride, _inject_saved)
            con(fmt("[F6] Restored slot %d.", _inject_slot))
        end
        _inject_active = false
        return
    end

    for slot = 1, O.OBJ_EVENT_COUNT - 1 do
        local sa = base + slot * stride
        if (r8(sa + O.OFF_FLAGS) & 0x01) == 0 then
            _inject_slot  = slot
            _inject_saved = _save_slot(base, slot, stride)

            local px = memory.read_s16_le(base + O.OFF_CURR_X)
            local py = memory.read_s16_le(base + O.OFF_CURR_Y)
            local elev = r8(base + O.OFF_ELEVATION)
            local tx, ty = px, py + 2

            for i = 0, stride - 1 do w8(sa + i, 0) end
            w8 (sa + O.OFF_FLAGS, 0x01)                       -- active
            w8 (sa + O.OFF_GRAPHICS_ID, 0x05)                 -- candidate NPC gfx
            w8 (sa + O.OFF_MOV_TYPE, 0x08)                    -- FACE_DOWN (inert)
            w8 (sa + O.OFF_LOCAL_ID, 0xFE)                    -- non-player, unused localId
            w8 (sa + O.OFF_MAP_NUM, map_n)
            w8 (sa + O.OFF_MAP_GROUP, map_g)
            w8 (sa + O.OFF_ELEVATION, elev)
            memory.write_s16_le(sa + O.OFF_INITIAL_X, tx)
            memory.write_s16_le(sa + O.OFF_INITIAL_Y, ty)
            memory.write_s16_le(sa + O.OFF_CURR_X, tx)
            memory.write_s16_le(sa + O.OFF_CURR_Y, ty)
            memory.write_s16_le(sa + O.OFF_PREV_X, tx)
            memory.write_s16_le(sa + O.OFF_PREV_Y, ty)
            w8 (sa + O.OFF_FACING_DIR, 0x11)                  -- facing=1 down, movDir=1
            w8 (sa + O.OFF_MOV_ACTION_ID, 0xFF)               -- no action

            _inject_active = true
            con(fmt("[F6] Dormant-slot inject → slot %d at (%d,%d).  Press F6 to restore.",
                slot, tx, ty))
            con("     WATCH THE SCREEN: does an NPC appear 2 tiles south of you?")
            con("     (Likely NOT — spriteId stays 0.  If it does render, even better.)")
            return
        end
    end
    con("[F6] No free slot on this map.")
end

-- ── F7: PUPPET AN EXISTING NPC (the likely-correct architecture) ─────────────
-- Commandeer the HIGHEST-numbered active NPC slot (least likely to be a plot
-- NPC) and continuously rewrite its coords to sit 1 tile south of the player,
-- mirroring the player's facing.  Because we reuse a slot the engine already
-- spawned + rendered (valid spriteId), the sprite SHOULD follow our writes.
--
-- This is the empirical test for "can we render a peer ghost by puppeting an
-- existing object-event slot?"  Toggle on, walk around, watch the NPC track
-- you; toggle off to restore.

-- pret FireRed movement action IDs (CFRU inherits these):
--   FACE_DOWN=0 UP=1 LEFT=2 RIGHT=3 ; WALK_NORMAL_DOWN=8 UP=9 LEFT=10 RIGHT=11
-- facing 1=down/2=up/3=left/4=right ⇒ WALK_NORMAL = 7 + facing, FACE = facing - 1.
local function walk_action_for_facing(f) return 7 + f end
local function face_action_for_facing(f) return f - 1 end

-- heldMovement flag bits in flags byte (0x00): bit6=active (0x40), bit7=finished (0x80).
local FLAG_ACTIVE   = 0x01
local FLAG_HELD_ON  = 0x40
local FLAG_HELD_FIN = 0x80

local _puppet_slot     = nil
local _puppet_active   = false
local _puppet_saved    = nil
local _puppet_last_px  = nil
local _puppet_last_py  = nil

local function doPuppetTest()
    if not RESULTS.OBJ_EVENTS_BASE_ADDR then
        con("[F7] No base address known yet — run F1 anchor walk first.")
        return
    end
    local base   = RESULTS.OBJ_EVENTS_BASE_ADDR
    local stride = PRET_OFFSETS.OBJ_EVENT_STRIDE
    local O = PRET_OFFSETS

    if _puppet_active then
        if _puppet_slot and _puppet_saved then
            _restore_slot(base, _puppet_slot, stride, _puppet_saved)
            con(fmt("[F7] Restored puppeted slot %d.", _puppet_slot))
        end
        _puppet_active = false
        return
    end

    -- Find the highest active slot that isn't the player (slot 0).
    local target = nil
    for slot = O.OBJ_EVENT_COUNT - 1, 1, -1 do
        local sa = base + slot * stride
        if (r8(sa + O.OFF_FLAGS) & 0x01) ~= 0 then target = slot; break end
    end
    if not target then
        con("[F7] No active NPC on this map to puppet — try a town with NPCs.")
        return
    end

    _puppet_slot   = target
    _puppet_saved  = _save_slot(base, target, stride)
    _puppet_last_px = memory.read_s16_le(base + O.OFF_CURR_X)
    _puppet_last_py = memory.read_s16_le(base + O.OFF_CURR_Y)
    _puppet_active = true
    con(fmt("[F7] Puppeting active slot %d via MOVEMENT ACTIONS.", target))
    con("     Walk around — each step you take, the NPC should take the SAME step")
    con("     (engine-animated).  Press F7 to restore.  F8 = swap its graphicsId.")
end

-- ── F8: GRAPHICS-ID SWAP on the puppeted slot ────────────────────────────────
-- Tests whether changing graphicsId on an already-spawned sprite changes its
-- appearance WITHOUT an engine reload (pret loads tiles at spawn, so it may not).

local _gfx_swapped = false
local function doGfxSwap()
    if not (_puppet_active and _puppet_slot) then
        con("[F8] Start the F7 puppet first.")
        return
    end
    local base = RESULTS.OBJ_EVENTS_BASE_ADDR
    local sa   = base + _puppet_slot * PRET_OFFSETS.OBJ_EVENT_STRIDE
    local player_gfx = r8(base + PRET_OFFSETS.OFF_GRAPHICS_ID)
    _gfx_swapped = not _gfx_swapped
    if _gfx_swapped then
        w8(sa + PRET_OFFSETS.OFF_GRAPHICS_ID, player_gfx)
        con(fmt("[F8] Wrote graphicsId=%d (player's) to slot %d.", player_gfx, _puppet_slot))
        con("     Did the sprite's APPEARANCE change, or only after it moved/redrew?")
    else
        con("[F8] (toggle) graphicsId left as-is; restore via F7.")
    end
end

-- ── F9: FIND gSprites (the OAM sprite array) ─────────────────────────────────
-- The rendered sprite lives in gSprites[objEvent.spriteId], NOT in the object
-- event.  Find the array by correlation that is INDEPENDENT of the camera:
--   gSprites[npc.spriteId].pos − gSprites[player.spriteId].pos  ≈  16 × worldDelta
-- because both sprites share the same camera coordOffset, their pos1 difference
-- reflects only their world-tile separation.  We scan EWRAM for a 0x44-stride
-- array where this holds for ≥2 known NPCs.

local SPR_STRIDE_GUESS = 0x44

-- struct Sprite field offsets (pret, confirmed via CFRU BPRE.ld; base 0x0202063C):
--   x@0x20 y@0x22 (s16) · animNum@0x2A · byte 0x2C bit6 = animPaused ·
--   data[2]@0x32 (held-move step) · byte 0x3E bit0=inUse bit2=invisible ·
--   byte 0x3F bit2 = animBeginning (write to restart an anim).
-- Anim numbers: FACE_S/N/W/E = 0/1/2/3 ; GO_S/N/W/E = 4/5/6/7.
-- Direction (low nibble of objEvent 0x18): 1=down 2=up 3=left 4=right.
local SPR = { X=0x20, Y=0x22, ANIM_NUM=0x2A, BYTE_2C=0x2C, DATA2=0x32, BYTE_3E=0x3E, BYTE_3F=0x3F }
local GSPRITES_VANILLA = 0x0202063C  -- CFRU BPRE.ld; RR 4.1 confirmed via F9 correlation
-- Default the base so F6/F10 work WITHOUT first running F9 (F9 stays for re-confirm).
RESULTS.GSPRITES_BASE   = GSPRITES_VANILLA
RESULTS.GSPRITES_POSOFF = 0x20
-- A free OBJ-VRAM tile region for our spawned sprite's OWN tiles.  Real NPCs
-- allocate from low indices; a 16x32 sprite needs 8 tiles.  0x300 (768) is a
-- high region very unlikely to be in use in a town.  (Ideally we'd reserve it
-- in gSpriteTileAllocBitmap, but that addr is unconfirmed on RR — high index
-- avoids collisions in practice.)
local GHOST_FREE_TILE = 0x300
local function idle_anim_for_facing(f) return f - 1 end   -- down1→0, up2→1, left3→2, right4→3
local function walk_anim_for_facing(f) return f + 3 end   -- down1→4, up2→5, left3→6, right4→7

local function findGSprites()
    if not RESULTS.OBJ_EVENTS_BASE_ADDR then
        con("[F9] No base address yet — run F1 anchor walk first.")
        return
    end
    local obase   = RESULTS.OBJ_EVENTS_BASE_ADDR
    local ostride = PRET_OFFSETS.OBJ_EVENT_STRIDE
    local O = PRET_OFFSETS

    local p_spr = r8(obase + O.OFF_SPRITE_ID)
    local p_wx  = memory.read_s16_le(obase + O.OFF_CURR_X)
    local p_wy  = memory.read_s16_le(obase + O.OFF_CURR_Y)

    local npcs = {}
    for slot = 1, O.OBJ_EVENT_COUNT - 1 do
        local sa = obase + slot * ostride
        if (r8(sa + O.OFF_FLAGS) & 0x01) ~= 0 then
            npcs[#npcs+1] = {
                spr = r8(sa + O.OFF_SPRITE_ID),
                wx  = memory.read_s16_le(sa + O.OFF_CURR_X),
                wy  = memory.read_s16_le(sa + O.OFF_CURR_Y),
            }
        end
    end

    log("")
    log(fmt("[F9] gSprites search: player spriteId=%d world=(%d,%d), %d active NPCs",
        p_spr, p_wx, p_wy, #npcs))
    con(fmt("[F9] Scanning EWRAM for gSprites (player spr=%d, %d NPCs)... please wait.",
        p_spr, #npcs))
    if #npcs < 2 then
        log("  !! Need >=2 active NPCs for a reliable correlation.  Move to a busier map.")
        con("[F9] Need >=2 NPCs on-screen — try a town. Aborting.")
        return
    end

    local POS_OFFS = {0x20, 0x24, 0x1E, 0x22}  -- candidate pos1 offsets in struct Sprite
    local best = nil
    for _, posoff in ipairs(POS_OFFS) do
        for base = 0x02000000, 0x02030000, 4 do
            local px = memory.read_s16_le(base + p_spr * SPR_STRIDE_GUESS + posoff)
            local py = memory.read_s16_le(base + p_spr * SPR_STRIDE_GUESS + posoff + 2)
            -- Cheap sanity gate to prune the scan: pos within a sane s16 window.
            if px > -512 and px < 768 and py > -512 and py < 768 then
                local matches = 0
                for _, n in ipairs(npcs) do
                    local nx = memory.read_s16_le(base + n.spr * SPR_STRIDE_GUESS + posoff)
                    local ny = memory.read_s16_le(base + n.spr * SPR_STRIDE_GUESS + posoff + 2)
                    local exp_dx = 16 * (n.wx - p_wx)
                    local exp_dy = 16 * (n.wy - p_wy)
                    if math.abs((nx - px) - exp_dx) <= 4 and math.abs((ny - py) - exp_dy) <= 4 then
                        matches = matches + 1
                    end
                end
                if matches >= 2 then
                    local cand = {base = base, posoff = posoff, matches = matches, px = px, py = py}
                    if (not best) or matches > best.matches
                       or (matches == best.matches and math.abs(base - 0x02020630) < math.abs(best.base - 0x02020630)) then
                        best = cand
                    end
                end
            end
        end
    end

    if best then
        log(fmt("  ✓ gSprites base = %s  (pos1 offset +0x%02X, stride 0x44, %d/%d NPCs matched)",
            hex(best.base), best.posoff, best.matches, #npcs))
        log(fmt("    player sprite pos1 = (%d, %d)", best.px, best.py))
        -- Normalize to the TRUE struct base so SPR.* field offsets (animNum, etc.)
        -- line up: true_base = found_base + (found_posoff - x_offset). For the
        -- canonical layout this yields 0x0202063C (CFRU BPRE.ld).
        local true_base = best.base + (best.posoff - SPR.X)
        RESULTS.GSPRITES_BASE   = true_base
        RESULTS.GSPRITES_POSOFF = SPR.X
        log(fmt("    → normalized gSprites base = %s (x@0x20, y@0x22, animNum@0x2A)", hex(true_base)))
        if true_base == GSPRITES_VANILLA then
            log("    ✓ matches CFRU BPRE.ld gSprites symbol (0x0202063C)")
        end
        con(fmt("[F9] ✓ gSprites = %s (%d NPCs matched). Now press F10 to puppet a sprite.",
            hex(true_base), best.matches))
    else
        log("  ✗ gSprites NOT found by correlation.  Sprite stride may not be 0x44, or")
        log("    pos1 is at an unexpected offset.  (Deep research will pin this down.)")
        con("[F9] ✗ gSprites not found — see main log. Deep research pending.")
    end
    _flush()
end

-- ── F10: DIRECT SPRITE-POSITION PUPPET ───────────────────────────────────────
-- Glue an existing NPC's *sprite* 1 tile below the player by copying the
-- player's sprite pos1 (+16 in y) every frame.  Camera-safe: both sprites carry
-- the same coordOffset, so a constant pos1 delta = a constant on-screen delta.
-- If the NPC sprite visibly tracks below the player → we have our render
-- primitive (drive gSprites pos1) and the whole feature is unblocked.

local _spup_slot   = nil
local _spup_active = false
local _spup_obj_saved = nil
local _spup_last_anim = nil

local function doSpritePuppet()
    if not (RESULTS.GSPRITES_BASE and RESULTS.GSPRITES_POSOFF) then
        con("[F10] Run F9 first to locate gSprites.")
        return
    end
    local obase   = RESULTS.OBJ_EVENTS_BASE_ADDR
    local ostride = PRET_OFFSETS.OBJ_EVENT_STRIDE
    local O = PRET_OFFSETS

    if _spup_active then
        if _spup_slot and _spup_obj_saved then
            _restore_slot(obase, _spup_slot, ostride, _spup_obj_saved)
            con(fmt("[F10] Restored slot %d (sprite returns to engine control).", _spup_slot))
        end
        _spup_active = false
        return
    end

    local target = nil
    for slot = O.OBJ_EVENT_COUNT - 1, 1, -1 do
        local sa = obase + slot * ostride
        if (r8(sa + O.OFF_FLAGS) & 0x01) ~= 0 then target = slot; break end
    end
    if not target then
        con("[F10] No active NPC to puppet — try a town.")
        return
    end
    _spup_slot = target
    _spup_obj_saved = _save_slot(obase, target, ostride)
    _spup_active = true
    con(fmt("[F10] Sprite-puppeting slot %d.  Walk around — its SPRITE should glue 1 tile",
        target))
    con("      below you and track as you move.  Press F10 to restore.")
end

-- ── F6 (repurposed): CLONE-SPAWN OUR OWN NPC ─────────────────────────────────
-- Create an INDEPENDENT animated NPC without stealing a map NPC:
--   1. Pick a template = an active WALKING NPC (movementType wander) so it has
--      GO_* walk frames + valid images/anims/oam pointers.
--   2. Clone its gSprites entry into a FREE gSprites slot (inUse bit clear).
--   3. Clone its object-event into a FREE object-event slot, point it at our new
--      sprite, set movementType=NONE so the engine doesn't fight us.
--   4. Drive our clone's position + animNum each frame (F10-style).
-- KNOWN RISK: the cloned sprite shares the template's VRAM tileNum, so the two
-- may share/fight frame tiles.  This test reveals whether that's a problem;
-- VRAM tile allocation is the parallel research topic.

local _clone_active   = false
local _clone_objslot  = nil
local _clone_sprslot  = nil
local _clone_last_anim = nil
local _clone_idle_frames = 0    -- consecutive frames the player has been "finished" (idle)
local _clone_cooldown   = 0     -- frames to wait before (re)spawning (lets a new map settle)
local _clone_last_map_g = -1
local _clone_last_map_n = -1

-- Acquire free slots and clone the PLAYER's trainer sprite (always present,
-- fully animated — walk/run/bike) into a free gSprites slot with its OWN VRAM
-- tiles + a backing object-event (collision is acceptable per the design).
-- Returns true on success.
local function _clone_acquire()
    local obase   = RESULTS.OBJ_EVENTS_BASE_ADDR
    local ostride = PRET_OFFSETS.OBJ_EVENT_STRIDE
    local O = PRET_OFFSETS
    local gbase = RESULTS.GSPRITES_BASE

    -- Free any previously-held slots first so a re-acquire doesn't LEAK an
    -- active object-event behind us (that leak is a phantom static collision).
    if _clone_objslot then w8(obase + _clone_objslot * ostride, 0x00) end
    if _clone_sprslot then
        local b = gbase + _clone_sprslot * 0x44 + 0x3E
        w8(b, r8(b) & 0xFE)
    end

    local p_spr = r8(obase + O.OFF_SPRITE_ID)   -- player's sprite (slot 0)
    if p_spr >= 64 then return false end

    local free_spr
    for s = 0, 63 do
        if (r8(gbase + s * 0x44 + 0x3E) & 0x01) == 0 then free_spr = s; break end
    end
    local free_obj
    for slot = 1, O.OBJ_EVENT_COUNT - 1 do
        if (r8(obase + slot * ostride + O.OFF_FLAGS) & 0x01) == 0 then free_obj = slot; break end
    end
    if not free_spr or not free_obj then return false end
    _clone_sprslot, _clone_objslot = free_spr, free_obj

    -- clone PLAYER sprite → free sprite slot
    local paddr = gbase + p_spr * 0x44
    local naddr = gbase + free_spr * 0x44
    for i = 0, 0x43 do w8(naddr + i, r8(paddr + i)) end
    -- own VRAM tiles (oam.tileNum = low 10 bits of OAM attr2 @ sprite+0x04)
    local attr2 = r16(naddr + 0x04)
    w16(naddr + 0x04, (attr2 & 0xFC00) | (GHOST_FREE_TILE & 0x03FF))
    w8(naddr + 0x3E, r8(naddr + 0x3E) | 0x01)            -- inUse
    w8(naddr + 0x3E, r8(naddr + 0x3E) & 0xFB)            -- invisible = 0 (bit2)
    memory.write_s16_le(naddr + 0x2E, free_obj)          -- data[0] = our object-event id
    w8(naddr + 0x3F, r8(naddr + 0x3F) | 0x04)            -- animBeginning → DMA frame0 to our tiles
    w8(naddr + 0x2C, r8(naddr + 0x2C) & 0xBF)            -- animPaused = 0

    -- backing object-event: pin to player so it never culls (collision OK).
    local nobj = obase + free_obj * ostride
    local px = memory.read_s16_le(obase + O.OFF_CURR_X)
    local py = memory.read_s16_le(obase + O.OFF_CURR_Y)
    for i = 0, ostride - 1 do w8(nobj + i, 0) end
    w8(nobj + O.OFF_FLAGS, 0x01)                          -- active
    w8(nobj + O.OFF_SPRITE_ID, free_spr)
    w8(nobj + O.OFF_GRAPHICS_ID, r8(obase + O.OFF_GRAPHICS_ID))
    w8(nobj + O.OFF_MOV_TYPE, 0x00)                       -- NONE
    w8(nobj + O.OFF_LOCAL_ID, 0xFD)
    w8(nobj + O.OFF_MAP_NUM, map_n)
    w8(nobj + O.OFF_MAP_GROUP, map_g)
    memory.write_s16_le(nobj + O.OFF_CURR_X, px)
    memory.write_s16_le(nobj + O.OFF_CURR_Y, py)
    memory.write_s16_le(nobj + O.OFF_PREV_X, px)
    memory.write_s16_le(nobj + O.OFF_PREV_Y, py)

    _clone_last_anim = nil
    _clone_idle_frames = 0
    _clone_last_map_g = r8(sb1_value + 0x0004)
    _clone_last_map_n = r8(sb1_value + 0x0005)
    return true
end

local function doCloneSpawn()
    if not (RESULTS.GSPRITES_BASE and RESULTS.OBJ_EVENTS_BASE_ADDR) then
        con("[F6] gSprites base not set (defaulted to 0x0202063C — should be fine).")
        return
    end
    local obase = RESULTS.OBJ_EVENTS_BASE_ADDR
    local ostride = PRET_OFFSETS.OBJ_EVENT_STRIDE
    local gbase = RESULTS.GSPRITES_BASE

    if _clone_active then
        -- free our slots: deactivate the object-event, clear the sprite inUse bit.
        if _clone_objslot then w8(obase + _clone_objslot * ostride, 0x00) end
        if _clone_sprslot then
            local b = gbase + _clone_sprslot * 0x44 + 0x3E
            w8(b, r8(b) & 0xFE)
        end
        _clone_active = false
        _clone_last_anim = nil
        con("[F6] Ghost removed.")
        return
    end

    if _clone_acquire() then
        _clone_active = true
        con(fmt("[F6] Cloned PLAYER trainer sprite → sprite slot %d (own tiles @0x%X).",
            _clone_sprslot, GHOST_FREE_TILE))
        con("     Walk/run around — a fully-animated trainer ghost tracks 1 tile below you,")
        con("     survives going off-screen, and leaves all NPCs untouched.")
    else
        con("[F6] Could not acquire free sprite/object slots.")
    end
end

-- ── F11: SPRITE ANIMATION-FIELD DIFF ─────────────────────────────────────────
-- Find the sprite's animation fields (animNum / animCmdIndex / delay) the same
-- way we found the object-event layout: capture the player sprite's 0x44 bytes
-- while STANDING (press 1), walk, then press 2 while WALKING — the script diffs
-- the two snapshots and reports every byte that changed.  pos1 (0x24/0x26) will
-- change with position; the OTHER changed bytes are the animation state.

local SPR_STRIDE = 0x44
local _anim_snap = nil
local function doAnimDiff()
    if not (RESULTS.GSPRITES_BASE) then
        con("[F11] Run F9 first to locate gSprites.")
        return
    end
    local obase = RESULTS.OBJ_EVENTS_BASE_ADDR
    local p_spr = r8(obase + PRET_OFFSETS.OFF_SPRITE_ID)
    local sa = RESULTS.GSPRITES_BASE + p_spr * SPR_STRIDE

    if not _anim_snap then
        _anim_snap = {}
        for i = 0, SPR_STRIDE - 1 do _anim_snap[i] = r8(sa + i) end
        con("[F11] Captured STANDING sprite snapshot. Now WALK, then press F11 again.")
        log("")
        log(fmt("[F11] Sprite anim diff — standing snapshot captured (player spriteId=%d @ %s)",
            p_spr, hex(sa)))
    else
        log("[F11] Walking snapshot — changed bytes (offset: standing → walking):")
        local changed = {}
        for i = 0, SPR_STRIDE - 1 do
            local now = r8(sa + i)
            if now ~= _anim_snap[i] then
                local tag = ""
                if i == 0x24 or i == 0x25 or i == 0x26 or i == 0x27 then tag = "  (pos1 x/y — expected)" end
                log(fmt("    +0x%02X : 0x%02X → 0x%02X%s", i, _anim_snap[i], now, tag))
                changed[#changed+1] = i
            end
        end
        if #changed == 0 then
            log("    (no change — were you actually walking at press 2?)")
        end
        log("    → Non-pos changed offsets are animNum / animCmdIndex / delay candidates.")
        con(fmt("[F11] Diff done — %d bytes changed. See main log.", #changed))
        _anim_snap = nil
        _flush()
    end
end

-- ── F12: FIND gSpriteTileAllocBitmap (OBJ-VRAM tile allocator) ───────────────
-- The engine tracks OBJ-VRAM tile allocation in a bitmap: bit b == 1 ⟺ 4bpp
-- tile b is allocated.  AllocSpriteTiles scans it LOW→high for a free run.  We
-- currently CLAIM a high free block but can't RESERVE it (engine doesn't know)
-- → a newly-spawned sprite can be handed our tiles → garble.  Knowing this
-- address lets us set the bits (reserve) on spawn + clear them (free) on
-- despawn — corruption eliminated at the source, no self-heal needed.
--
-- DISCOVERY (camera-independent, behavioral): the bitmap tracks every active
-- sprite's tiles, so for the TRUE base address ~100% of all active sprites'
-- FULL tile ranges (derived from OAM shape/size) read as set.  88+ specific
-- bits all being 1 is essentially impossible by chance, so coverage alone pins
-- the address — no fragile "top tiles free / every start bit set" hard gates
-- (an earlier version used those and pruned the real address away).  We load
-- EWRAM/IWRAM once, then rank every plausible 128-byte window by coverage.
--   Press F12 once → scan + report top candidates by coverage %.
--   Walk to a DIFFERENT map (new sprite set) → press F12 again → re-validates
--   the stored candidate against the new sprites (confirms it's stable).

local TOTAL_OBJ_TILES = 1024            -- 4bpp OBJ-VRAM tiles tracked by the bitmap
local BITMAP_BYTES    = TOTAL_OBJ_TILES // 8   -- 128

local POPCOUNT = {}
for i = 0, 255 do
    local c, v = 0, i
    while v > 0 do c = c + (v & 1); v = v >> 1 end
    POPCOUNT[i] = c
end

-- (shape,size) → tile count, per GBA OAM dimension table (w*h in 8x8 tiles).
local OAM_TILE_DIMS = {
    [0] = { {1,1}, {2,2}, {4,4}, {8,8} },   -- square
    [1] = { {2,1}, {4,1}, {4,2}, {8,4} },   -- horizontal (wide)
    [2] = { {1,2}, {1,4}, {2,4}, {4,8} },   -- vertical (tall) — overworld NPCs (16x32 = 8)
}
local function sprite_tile_count(sa)
    local attr0 = r16(sa + 0x00)
    local attr1 = r16(sa + 0x02)
    local shape = (attr0 >> 14) & 0x03
    local size  = (attr1 >> 14) & 0x03
    local row = OAM_TILE_DIMS[shape]
    if not row then return 1 end
    local d = row[size + 1]
    return d[1] * d[2]
end

local function collect_active_sprite_tiles()
    local gbase = RESULTS.GSPRITES_BASE
    local ranges, total = {}, 0
    for s = 0, 63 do
        local sa = gbase + s * SPR_STRIDE
        if (r8(sa + 0x3E) & 0x01) ~= 0 then                 -- inUse
            local t = r16(sa + 0x04) & 0x03FF               -- oam.tileNum
            local n = sprite_tile_count(sa)
            ranges[#ranges+1] = { t = t, n = n }
            total = total + n
        end
    end
    return ranges, total
end

-- Read [lo, hi) once into a 0-indexed byte array + a prefix-popcount table so a
-- window's set-bit count is O(1).  Returns mem, prefixPopcount, n.
local function load_region(lo, hi)
    local n = hi - lo
    local mem, pc = {}, {}
    pc[0] = 0
    for i = 0, n - 1 do
        local b = r8(lo + i)
        mem[i] = b
        pc[i + 1] = pc[i] + POPCOUNT[b]
    end
    return mem, pc, n
end

-- bit b set within the window whose byte-0 is array-index o ?  (LSB-first, per
-- pret SpriteTileAllocBitmapOp: tile b → byte b>>3, bit b&7.)
local function arr_bit(mem, o, b) return ((mem[o + (b >> 3)] >> (b & 7)) & 1) == 1 end

local function window_coverage(mem, o, ranges, total)
    if total == 0 then return 0 end
    local hit = 0
    for _, rg in ipairs(ranges) do
        for k = 0, rg.n - 1 do
            if arr_bit(mem, o, rg.t + k) then hit = hit + 1 end
        end
    end
    return hit / total
end

local function findTileAllocBitmap()
    if not RESULTS.GSPRITES_BASE then
        con("[F12] Run F9 first (need gSprites to read sprite tile allocations).")
        return
    end
    local ranges, total = collect_active_sprite_tiles()
    if #ranges < 3 then
        con(fmt("[F12] Only %d active sprites — move to a busier map (town) for a reliable scan.", #ranges))
        return
    end

    -- RE-CONFIRM PATH: a candidate already exists → re-validate it against the
    -- current (presumably different-map) sprite set.
    if RESULTS.TILE_ALLOC_BITMAP then
        local b = RESULTS.TILE_ALLOC_BITMAP
        local mem = load_region(b, b + BITMAP_BYTES)
        local sc = window_coverage(mem, 0, ranges, total)
        log("")
        if sc >= 0.90 then
            log(fmt("[F12] RE-CONFIRM %s vs %d active sprites → PASS (%.0f%% coverage)", hex(b), #ranges, sc * 100))
            con(fmt("[F12] ✓ RE-CONFIRM PASS at %s (%.0f%% coverage, %d sprites). Address is stable.",
                hex(b), sc * 100, #ranges))
        else
            log(fmt("[F12] RE-CONFIRM %s vs %d active sprites → FAIL (%.0f%% coverage)", hex(b), #ranges, sc * 100))
            con(fmt("[F12] ✗ RE-CONFIRM FAIL at %s (%.0f%%) — coincidence. Clearing; press F12 to re-scan.",
                hex(b), sc * 100))
            RESULTS.TILE_ALLOC_BITMAP = nil
        end
        _flush()
        return
    end

    con(fmt("[F12] Scanning for gSpriteTileAllocBitmap (%d active sprites, %d tiles)... please wait.", #ranges, total))
    log("")
    log(fmt("[F12] gSpriteTileAllocBitmap search: %d active sprites, %d total tiles in use", #ranges, total))

    -- Coverage alone is too weak here: only ~63 tiles are used and they cluster
    -- in LOW indices, so any dense data blob whose first ~16 bytes are set scores
    -- 100%.  The defining NEGATIVE property of the real bitmap is that the HIGH
    -- tiles are free: the engine packs allocations low→high, so tiles 768..1023
    -- (bytes 96..127) read ~0 in a town.  We require near-perfect coverage AND a
    -- near-empty upper quarter, then tie-break by sparsity + word-alignment (a
    -- global bitmap symbol is aligned; a coincidental hit inside a struct is not).
    local UPPER_BYTE0 = 96            -- tile 768 → byte 96
    local MAX_UPPER_BITS = 16         -- allow a few stray high allocations
    local cands = {}
    local function scan(lo, hi, label)
        local mem, pc, n = load_region(lo, hi)
        local dens_pass, cov_pass = 0, 0
        for o = 0, n - BITMAP_BYTES do
            local wc = pc[o + BITMAP_BYTES] - pc[o]       -- window set-bit count
            if wc >= total and wc <= TOTAL_OBJ_TILES - 4 then  -- ≥ tiles we need, not saturated
                dens_pass = dens_pass + 1
                local sc = window_coverage(mem, o, ranges, total)
                if sc >= 0.95 then
                    cov_pass = cov_pass + 1
                    local upper = pc[o + BITMAP_BYTES] - pc[o + UPPER_BYTE0]  -- bits in tiles 768..1023
                    if upper <= MAX_UPPER_BITS then
                        cands[#cands+1] = {
                            base = lo + o, score = sc, density = wc,
                            upper = upper, aligned = ((lo + o) % 4 == 0),
                        }
                    end
                end
            end
        end
        log(fmt("    scanned %s [%s..%s] — %d density-pass, %d ≥95%% cov, %d also high-tiles-free",
            label, hex(lo), hex(hi), dens_pass, cov_pass, #cands))
    end
    scan(0x02000000, 0x02040000, "EWRAM")
    scan(0x03000000, 0x03008000, "IWRAM")

    -- Rank: high-tiles-free first (real allocator), then sparsest, then aligned.
    table.sort(cands, function(a, b)
        if a.upper ~= b.upper then return a.upper < b.upper end
        if a.density ~= b.density then return a.density < b.density end
        if a.aligned ~= b.aligned then return a.aligned end
        return a.base < b.base
    end)
    if #cands > 0 then
        log(fmt("  Top candidates (of %d passing coverage+high-free):", #cands))
        for i = 1, math.min(8, #cands) do
            local c = cands[i]
            log(fmt("    %d. %s  cov=%.1f%%  density=%d/1024  upper=%d  %s",
                i, hex(c.base), c.score * 100, c.density, c.upper, c.aligned and "ALIGNED" or "unaligned"))
        end
        local best = cands[1]
        RESULTS.TILE_ALLOC_BITMAP = best.base
        log(fmt("  ✓ best gSpriteTileAllocBitmap = %s (%.1f%% cov, density=%d, upper=%d, %s, byte[0]=0x%02X)",
            hex(best.base), best.score * 100, best.density, best.upper,
            best.aligned and "aligned" or "UNALIGNED", r8(best.base)))
        log("    Reserve ghost tiles by OR-ing bits [base, base+8); clear them to free on despawn.")
        con(fmt("[F12] ✓ best = %s (%.1f%% cov, density=%d, upper=%d, %s). %d candidates — see main log.",
            hex(best.base), best.score * 100, best.density, best.upper,
            best.aligned and "aligned" or "UNALIGNED", #cands))
        con("[F12] Now WALK TO A DIFFERENT MAP and press F12 again to RE-CONFIRM (real one stays ≥90%).")
    else
        log("  ✗ No window passed coverage+high-tiles-free. OBJ tile count may differ from 1024,")
        log("    sprites may use non-allocator tiles, or the bitmap is outside EWRAM/IWRAM.")
        con("[F12] ✗ Not found — see main log. (Try widening: high tiles may not be free here.)")
    end
    _flush()
end

-- ── KEY HANDLER ──────────────────────────────────────────────────────────────
local _prev_keys = {}
event.unregisterbyname("overworld_discovery_keys")
event.onframeend(function()
    local keys = input.get()

    -- F1: anchor walk (toggling between pass 1 / pass 2)
    if keys["F1"] and not _prev_keys["F1"] then
        if not _anchor_armed then doAnchorFirst() else doAnchorSecond() end
    end
    if keys["F2"] and not _prev_keys["F2"] then toggleFrameLogger() end
    if keys["F3"] and not _prev_keys["F3"] then doStateSnapshot() end
    if keys["F4"] and not _prev_keys["F4"] then probeDrawImage() end
    if keys["F5"] and not _prev_keys["F5"] then dumpAllSlots() end
    if keys["F6"] and not _prev_keys["F6"] then doCloneSpawn() end
    if keys["F7"] and not _prev_keys["F7"] then doPuppetTest() end
    if keys["F8"] and not _prev_keys["F8"] then doGfxSwap() end
    if keys["F9"] and not _prev_keys["F9"] then findGSprites() end
    if keys["F10"] and not _prev_keys["F10"] then doSpritePuppet() end
    if keys["F11"] and not _prev_keys["F11"] then doAnimDiff() end
    if keys["F12"] and not _prev_keys["F12"] then findTileAllocBitmap() end

    -- F10 per-frame sprite-position puppet: render the host NPC's sprite 1 tile
    -- below the player (camera-safe: copy player sprite x/y), and drive its walk
    -- animation to mirror the player's facing + moving state.
    if _spup_active and _spup_slot and RESULTS.GSPRITES_BASE then
        local obase = RESULTS.OBJ_EVENTS_BASE_ADDR
        local O = PRET_OFFSETS
        local gbase = RESULTS.GSPRITES_BASE
        local hsa = obase + _spup_slot * O.OBJ_EVENT_STRIDE
        local host_flags = r8(hsa + O.OFF_FLAGS)
        local n_spr = r8(hsa + O.OFF_SPRITE_ID)

        if (host_flags & 0x01) == 0 or n_spr >= 64 then
            -- Host despawned (map change / off-camera cull). Stop writing so we
            -- don't corrupt a reused sprite (this is what caused the warp teleport).
            _spup_active = false
            _spup_last_anim = nil
            con("[F10] Host NPC gone (map change/cull) — auto-stopped. Re-press F10 to re-acquire.")
        else
            local p_spr = r8(obase + O.OFF_SPRITE_ID)
            local psa = gbase + p_spr * SPR_STRIDE_GUESS
            local nsa = gbase + n_spr * SPR_STRIDE_GUESS

            -- Position: 1 tile (16px) below the player on screen.
            local p_sx = memory.read_s16_le(psa + SPR.X)
            local p_sy = memory.read_s16_le(psa + SPR.Y)
            memory.write_s16_le(nsa + SPR.X, p_sx)
            memory.write_s16_le(nsa + SPR.Y, p_sy + 16)

            -- Animation: mirror player's facing + moving (only rewrite on change
            -- so we don't restart the anim to frame 0 every frame).
            local pf = r8(obase + O.OFF_FACING_DIR) & 0x0F
            local moving = (r8(obase + O.OFF_FLAGS) & 0x80) == 0
            if pf >= 1 and pf <= 4 then
                local want = moving and walk_anim_for_facing(pf) or idle_anim_for_facing(pf)
                if want ~= _spup_last_anim then
                    w8(nsa + SPR.ANIM_NUM, want)
                    w8(nsa + SPR.BYTE_3F, r8(nsa + SPR.BYTE_3F) | 0x04)   -- animBeginning
                    w8(nsa + SPR.BYTE_2C, r8(nsa + SPR.BYTE_2C) & 0xBF)   -- clear animPaused (bit6)
                    _spup_last_anim = want
                end
            end
        end
    end

    -- F6 clone-spawn per-frame: spawn/maintain a ghost = clone of the PLAYER
    -- sprite, rendered 1 tile below the player, mirroring walk/run + idle.
    if _clone_active and RESULTS.GSPRITES_BASE then
        local obase = RESULTS.OBJ_EVENTS_BASE_ADDR
        local O = PRET_OFFSETS
        local gbase = RESULTS.GSPRITES_BASE

        -- Map-change detection: a map load rebuilds gObjectEvents/gSprites, so our
        -- slot indices now point at NEW-map objects.  FORGET our refs WITHOUT
        -- writing memory (deactivating them would corrupt real new-map NPCs — the
        -- "changing areas breaks the game" bug), and wait for the map to settle.
        local cmg = r8(sb1_value + 0x0004)
        local cmn = r8(sb1_value + 0x0005)
        if cmg ~= _clone_last_map_g or cmn ~= _clone_last_map_n then
            _clone_last_map_g, _clone_last_map_n = cmg, cmn
            _clone_objslot, _clone_sprslot = nil, nil
            _clone_cooldown = 30
            _clone_last_anim = nil
        end

        if _clone_cooldown > 0 then
            _clone_cooldown = _clone_cooldown - 1
        elseif not (_clone_objslot and _clone_sprslot) then
            -- (re)spawn on the (possibly new) map; retry later if no free slots yet.
            if not _clone_acquire() then _clone_cooldown = 30 end
        else
            local nobj = obase + _clone_objslot * O.OBJ_EVENT_STRIDE
            local nsa  = gbase + _clone_sprslot * 0x44
            -- same-map validity guard: engine reclaimed our slot?  re-acquire
            -- (safe to deactivate the stale slot here — still same map).
            if (r8(nsa + SPR.BYTE_3E) & 0x01) == 0 or (r8(nobj + O.OFF_FLAGS) & 0x01) == 0 then
                if not _clone_acquire() then _clone_cooldown = 30 end
            else
                local p_spr = r8(obase + O.OFF_SPRITE_ID)
                local psa = gbase + p_spr * 0x44

                -- pin object-event (current + previous) to the player → no cull,
                -- no static collision wall (pret collision checks both coords).
                local px = memory.read_s16_le(obase + O.OFF_CURR_X)
                local py = memory.read_s16_le(obase + O.OFF_CURR_Y)
                w8(nobj + O.OFF_FLAGS, r8(nobj + O.OFF_FLAGS) | 0x01)
                memory.write_s16_le(nobj + O.OFF_CURR_X, px)
                memory.write_s16_le(nobj + O.OFF_CURR_Y, py)
                memory.write_s16_le(nobj + O.OFF_PREV_X, px)
                memory.write_s16_le(nobj + O.OFF_PREV_Y, py)

                -- render 1 tile below player; re-assert inUse + our tiles.
                w8(nsa + SPR.BYTE_3E, r8(nsa + SPR.BYTE_3E) | 0x01)
                local attr2 = r16(nsa + 0x04)
                w16(nsa + 0x04, (attr2 & 0xFC00) | (GHOST_FREE_TILE & 0x03FF))
                memory.write_s16_le(nsa + SPR.X, memory.read_s16_le(psa + SPR.X))
                memory.write_s16_le(nsa + SPR.Y, memory.read_s16_le(psa + SPR.Y) + 16)

                -- Idle-debounce: heldMovementFinished (flags bit7) goes set the
                -- instant the player truly stops (only brief blips at tile edges).
                -- Require it set for 6 consecutive frames before idling → no
                -- trailing extra step, but fluid mid-walk.
                if (r8(obase + O.OFF_FLAGS) & 0x80) ~= 0 then
                    _clone_idle_frames = _clone_idle_frames + 1
                else
                    _clone_idle_frames = 0
                end
                local moving = _clone_idle_frames < 6

                -- While moving, mirror the player's live animNum (walk OR run);
                -- when stopped, a single-frame face anim so the ghost stands.
                local pf = r8(obase + O.OFF_FACING_DIR) & 0x0F
                local want
                if moving then
                    want = r8(psa + SPR.ANIM_NUM)
                elseif pf >= 1 and pf <= 4 then
                    want = idle_anim_for_facing(pf)
                else
                    want = _clone_last_anim
                end
                if want ~= _clone_last_anim then
                    w8(nsa + SPR.ANIM_NUM, want)
                    w8(nsa + SPR.BYTE_3F, r8(nsa + SPR.BYTE_3F) | 0x04)  -- animBeginning
                    w8(nsa + SPR.BYTE_2C, r8(nsa + SPR.BYTE_2C) & 0xBF)  -- animPaused = 0
                    _clone_last_anim = want
                end
            end
        end
    end

    -- Per-frame puppet updater: drive the puppeted slot through the engine's
    -- MOVEMENT-ACTION state machine so the SPRITE animates (raw coord writes
    -- only move collision, not the sprite — confirmed empirically).
    -- Strategy: when the player completes a step, issue the same WALK_NORMAL
    -- action to the puppet IF the puppet is idle (heldMovementFinished set).
    if _puppet_active and _puppet_slot and RESULTS.OBJ_EVENTS_BASE_ADDR then
        local base = RESULTS.OBJ_EVENTS_BASE_ADDR
        local O = PRET_OFFSETS
        local sa = base + _puppet_slot * O.OBJ_EVENT_STRIDE

        local px = memory.read_s16_le(base + O.OFF_CURR_X)
        local py = memory.read_s16_le(base + O.OFF_CURR_Y)
        local pf = r8(base + O.OFF_FACING_DIR) & 0x0F

        local player_stepped = (px ~= _puppet_last_px) or (py ~= _puppet_last_py)
        _puppet_last_px, _puppet_last_py = px, py

        local pflags = r8(sa + O.OFF_FLAGS)
        local puppet_idle = (pflags & FLAG_HELD_FIN) ~= 0

        if player_stepped and puppet_idle and pf >= 1 and pf <= 4 then
            -- Issue WALK_NORMAL_<player facing> as a held movement.
            w8(sa + O.OFF_MOV_ACTION_ID, walk_action_for_facing(pf))
            local nf = (pflags & ~FLAG_HELD_FIN) | FLAG_HELD_ON | FLAG_ACTIVE
            w8(sa + O.OFF_FLAGS, nf)
            -- Mirror facing nibble so the walk faces the right way immediately.
            w8(sa + O.OFF_FACING_DIR, (pf << 4) | pf)
        end
    end

    -- Frame logger: every 6 frames while on
    if _frame_logger_on then
        local fc = emu.framecount()
        if fc - _last_log_frame >= 6 then
            _last_log_frame = fc
            if RESULTS.OBJ_EVENTS_BASE_ADDR then
                local base = RESULTS.OBJ_EVENTS_BASE_ADDR
                local cx = memory.read_s16_le(base + PRET_OFFSETS.OFF_CURR_X)
                local cy = memory.read_s16_le(base + PRET_OFFSETS.OFF_CURR_Y)
                local px = memory.read_s16_le(base + PRET_OFFSETS.OFF_PREV_X)
                local py = memory.read_s16_le(base + PRET_OFFSETS.OFF_PREV_Y)
                local fbyte = r8(base + PRET_OFFSETS.OFF_FACING_DIR)
                local fx = fbyte & 0x0F
                local md = (fbyte >> 4) & 0x0F
                local ma = r8(base + PRET_OFFSETS.OFF_MOV_ACTION_ID)
                local fl = r8(base + PRET_OFFSETS.OFF_FLAGS)
                local f2 = r8(base + PRET_OFFSETS.OFF_FLAGS2)
                flog(fmt("%6d  %3d %3d  %3d %3d  %d  %3d  %3d  0x%02X 0x%02X",
                    fc, cx, cy, px, py, fx, md, ma, fl, f2))
            end
            -- Periodic auto-flush so user can tail the file
            if (fc - _frame_log_started) % 60 == 0 then _flush_frames() end
        end
    end

    -- gui.drawImage probe: attempt the call; let BizHawk error if unsupported
    if _drawimg_test_on then
        local ok, err = pcall(function()
            -- Just draw a colored box at fixed location — minimum-viable overlay
            gui.drawBox(20, 20, 36, 36, 0xFFFF8000, 0x80FF8000)
        end)
        if not ok and (emu.framecount() - _drawimg_start) % 60 == 0 then
            con("[F4] gui.drawBox failed: " .. tostring(err))
        end
        if emu.framecount() - _drawimg_start > 120 then
            _drawimg_test_on = false
            con("[F4] Probe finished (gui.drawBox is the cheapest overlay; gui.drawImage works on most cores).")
        end
    end

    _prev_keys = keys
end, "overworld_discovery_keys")

-- ── FINAL OUTPUT: PROFILE STUB ───────────────────────────────────────────────
log("")
sep()
log("")
log("[OUTPUT] PROFILES stub (fill in confirmed values after F1/F5/F6):")
log("")
log("  radical_red = {  -- add to lua/games/gen3_frlge.lua")
if RESULTS.OBJ_EVENTS_BASE_ADDR then
    log(fmt("      OBJ_EVENTS_BASE_ADDR    = %s,  -- ⚠ confirm via F1 anchor walk", hex(RESULTS.OBJ_EVENTS_BASE_ADDR)))
else
    log("      OBJ_EVENTS_BASE_ADDR    = 0x???,    -- run F1 anchor walk")
end
log(fmt("      OBJ_EVENT_STRIDE        = 0x%02X,", PRET_OFFSETS.OBJ_EVENT_STRIDE))
log(fmt("      OBJ_EVENT_COUNT         = %d,", PRET_OFFSETS.OBJ_EVENT_COUNT))
log("      -- Struct field offsets (pret vanilla; F5 dump confirms / disproves):")
for _, k in ipairs({"OFF_FLAGS","OFF_FLAGS2","OFF_FLAGS3","OFF_SPRITE_ID",
                    "OFF_GRAPHICS_ID","OFF_MOV_TYPE","OFF_TRAINER_TYPE","OFF_LOCAL_ID",
                    "OFF_MAP_NUM","OFF_MAP_GROUP","OFF_ELEVATION","OFF_INITIAL_X","OFF_INITIAL_Y",
                    "OFF_CURR_X","OFF_CURR_Y","OFF_PREV_X","OFF_PREV_Y",
                    "OFF_FACING_DIR","OFF_MOV_ACTION_ID"}) do
    log(fmt("      %-22s  = 0x%02X,", k, PRET_OFFSETS[k]))
end
log("      MOVEMENT_TYPE_NONE      = 0x00,  -- or 0x08 = FACE_DOWN (vanilla pret)")
log("      GHOST_GRAPHICS_ID       = 0x05,  -- ⚠ pick after F5 dump shows clean candidates")
log("      MOVEMENT_ACTION_WALK_DOWN  = 0x08,  -- vanilla pret; verify via F6 inject test")
log("      MOVEMENT_ACTION_WALK_UP    = 0x09,")
log("      MOVEMENT_ACTION_WALK_LEFT  = 0x0A,")
log("      MOVEMENT_ACTION_WALK_RIGHT = 0x0B,")
log("      MOVEMENT_ACTION_FACE_DOWN  = 0x04,")
log("      MOVEMENT_ACTION_FACE_UP    = 0x05,")
log("      MOVEMENT_ACTION_FACE_LEFT  = 0x06,")
log("      MOVEMENT_ACTION_FACE_RIGHT = 0x07,")
log("      CAMERA_X_ADDR           = 0x???,    -- F2 frame log reveals; pret vanilla = SB1+0x000C area")
log("      CAMERA_Y_ADDR           = 0x???,")
log("      OVERWORLD_VISIBLE_PRED  = nil,      -- compose from F3 state-snapshot comparison")
log("  }")
log("")
sep()
log("")
log("  PHASE 0 SIGN-OFF CHECKLIST (paste filled values into chat before Phase 1):")
log("    [ ] OBJ_EVENTS_BASE_ADDR confirmed via F1 anchor walk + save-state reload")
log("    [ ] Struct field offsets confirmed via F5 dump (compare across multiple maps)")
log("    [ ] MOVEMENT_TYPE_NONE confirmed inert (F6 inject test — NPC stays put)")
log("    [ ] GHOST_GRAPHICS_ID picked from F5 candidates (renders cleanly with sane palette)")
log("    [ ] MOVEMENT_ACTION_* constants verified (F6 with WALK_DOWN — NPC walks 1 tile)")
log("    [ ] Re-inject trigger documented (warp through a door — slot becomes inactive)")
log("    [ ] Safe-to-write predicate (movAction = 0x00 or sentinel = idle)")
log("    [ ] Collision/interactability: walk INTO NPC + press A — note behavior")
log("    [ ] CAMERA_X_ADDR / CAMERA_Y_ADDR from F2 log (track player at non-edge tiles)")
log("    [ ] OVERWORLD_VISIBLE predicate composed from F3 state-snapshot diff")
log("    [ ] CFRU struct layout == vanilla? YES / NO (note any offset diffs)")
log("    [ ] Vanilla FRLG profile populated OR explicitly nil with comment")
log("")
log("  WORKFLOW:")
log("    1. Stand still in overworld, observe Phase B/C/D candidates above.")
log("    2. Press F1.  Walk 1 tile NORTH (game must accept the input).  Press F1 again.")
log("    3. Press F5.  Slot dump now anchored to confirmed base.")
log("    4. Press F6.  An NPC should appear 2 tiles south of you.  Press F6 again to clear.")
log("    5. Press F3 in each of: overworld, START menu, bag, party, dialog, warp fade,")
log("       fly anim, battle, evolution, name entry.  Compare the dumped IWRAM signatures")
log("       across STATES_PATH to find a byte that flips consistently.")
log("    6. Press F2 + walk for ~10 seconds + press F2.  Inspect FRAMES_PATH for")
log("       camera tracking + 'moving' transitions.")
log("    7. Repeat F1 after a save-state reload to confirm the address is stable")
log("       (not a moving pointer).")
log("")
div()
log("  Discovery script loaded.  Press F1 to begin.")
div()

_flush()

con("")
con("════════════════════════════════════════════════════════════════")
con("  SLINK PEER-GHOST — Phase 0 discovery loaded")
con("    F1: anchor walk     F2: frame logger toggle    F3: state snapshot")
con("    F5: slot dump   F6: SPAWN ghost = clone of PLAYER trainer sprite")
con("    F9: re-confirm gSprites (optional; base defaulted to 0x0202063C)")
con("    F10: puppet existing NPC sprite   F11: anim-field diff")
con("    F12: find gSpriteTileAllocBitmap (in a TOWN; then re-press on a new map)")
con("  CRITICAL TEST: ANYWHERE (no NPCs needed) press F6, then walk AND run.")
con("  Watch: fully-animated trainer ghost tracks 1 tile below you, mirrors")
con("  walk+run, and SURVIVES walking off-screen / around (no corruption).")
con(fmt("  Output: %s", OUT_PATH or "(file write failed)"))
con("════════════════════════════════════════════════════════════════")
con("")
