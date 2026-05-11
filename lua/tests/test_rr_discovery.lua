--[[
  lua/test_rr_discovery.lua — Radical Red / CFRU Memory Address Discovery
  ========================================================================
  Comprehensive BizHawk Lua script that discovers ALL critical RAM addresses
  for a CFRU-based ROM hack (Pokemon Radical Red 4.1 or similar).

  Run this script ONCE with a save loaded that has:
    • At least 1–3 Pokemon in the party
    • Some Pokeballs in the bag
    • At least 1 badge (for flag detection)
    • BGM playing (for SE discovery)

  HOW TO USE:
    1. Load Radical Red 4.1 in BizHawk, load a save (overworld).
    2. Open the Lua Console and load this script.
    3. Overworld discoveries run automatically on load.
    4. Press F1 DURING a wild battle for battle-phase discoveries.
    5. Press F2 after battle ends (back in overworld) for outcome verification.

  OUTPUT:
    All results are written to  lua/rr_discovery_results.txt  so the
    BizHawk Lua Console line limit cannot truncate them.  Open that
    file after each phase to see the full output, including the
    copy-paste-ready PROFILES block for memory.lua.
--]]

-- ── Helpers ─────────────────────────────────────────────────────────────────
local fmt = string.format
local r8  = memory.read_u8
local r16 = memory.read_u16_le
local r32 = memory.read_u32_le

local function hex(n) return fmt("0x%08X", n) end
local function hex4(n) return fmt("0x%04X", n) end

-- ── OUTPUT FILE SETUP ────────────────────────────────────────────────────────
-- BizHawk's Lua Console truncates after ~200 lines, so we write everything
-- to a text file.  We try several path strategies in order:
--   1. MANUAL override (set below if auto-detection fails)
--   2. Script directory via debug.getinfo  (works in some BizHawk versions)
--   3. Alongside the loaded ROM file       (always known to the user)
--   4. BizHawk install directory            (fallback)
--
-- If none work, only console output is produced — but the user will see
-- a clear error message explaining what happened.

-- ┌──────────────────────────────────────────────────────────────────┐
-- │  MANUAL OVERRIDE: If auto-detection fails, uncomment ONE line   │
-- │  below and set a path that works on your system:                │
-- │                                                                 │
-- │  local MANUAL_OUT_PATH = "C:\\rr_discovery_results.txt"         │
-- │  local MANUAL_OUT_PATH = "D:\\rr_discovery_results.txt"         │
-- └──────────────────────────────────────────────────────────────────┘
local MANUAL_OUT_PATH = nil   -- set to a string to force a specific path

local _out_lines = {}      -- buffered; flushed on each phase completion
local OUT_PATH   = nil     -- resolved below
local _file_ok   = false   -- set true after first successful write

-- F1/F2 battle results go to a SEPARATE file so reruns don't wipe them.
local _battle_lines  = {}
local BATTLE_OUT_PATH = nil   -- derived from OUT_PATH once resolved
local _battle_file_ok = false

-- Try to write a test string to a path; returns true if it works.
local function _try_path(path)
    local ok, f = pcall(io.open, path, "w")
    if ok and f then
        f:write("")  -- just test that we can write; _flush() writes real content
        f:close()
        return true
    end
    return false
end

-- Strategy 1: debug.getinfo script directory
local function _path_from_debug()
    local ok, info = pcall(debug.getinfo, 1, "S")
    if ok and info and info.source then
        local dir = info.source:match("^@?(.*[\\/])")
        if dir then return dir .. "rr_discovery_results.txt" end
    end
    return nil
end

-- Strategy 2: next to the ROM file (via gameinfo or emu)
local function _path_from_rom()
    -- BizHawk 2.9+ exposes gameinfo.getromname() and client APIs
    local ok, rompath
    ok, rompath = pcall(function()
        if gameinfo and gameinfo.getromfilename then
            return gameinfo.getromfilename()
        end
        return nil
    end)
    if ok and rompath and rompath ~= "" then
        local dir = rompath:match("^(.*[\\/])")
        if dir then return dir .. "rr_discovery_results.txt" end
    end
    return nil
end

-- Strategy 3: BizHawk working directory
local function _path_from_cwd()
    return "rr_discovery_results.txt"
end

-- Resolve output path — try each strategy (manual override first)
if MANUAL_OUT_PATH and _try_path(MANUAL_OUT_PATH) then
    OUT_PATH = MANUAL_OUT_PATH
    _file_ok = true
else
    for _, getter in ipairs({ _path_from_debug, _path_from_rom, _path_from_cwd }) do
        local p = getter()
        if p and _try_path(p) then
            OUT_PATH = p
            _file_ok = true
            break
        end
    end
end

-- Derive battle output path from main path (same directory, different filename)
if OUT_PATH then
    BATTLE_OUT_PATH = OUT_PATH:gsub("rr_discovery_results", "rr_discovery_battle")
    if BATTLE_OUT_PATH == OUT_PATH then
        -- gsub didn't match; just append _battle before extension
        BATTLE_OUT_PATH = OUT_PATH:gsub("%.txt$", "_battle.txt")
    end
end

local function _flush()
    if not OUT_PATH then return end
    local ok, f = pcall(io.open, OUT_PATH, "w")
    if ok and f then
        f:write(table.concat(_out_lines, "\n") .. "\n")
        f:close()
        _file_ok = true
    else
        -- File write failed — tell the user via console
        console.log("!! FILE WRITE FAILED: " .. tostring(OUT_PATH))
        console.log("!! Copy the console output manually, or set OUT_PATH at top of script.")
        _file_ok = false
    end
end

-- Battle results flush — separate file that survives main-script reruns.
local function _flush_battle()
    if not BATTLE_OUT_PATH then return end
    local ok, f = pcall(io.open, BATTLE_OUT_PATH, "w")
    if ok and f then
        f:write(table.concat(_battle_lines, "\n") .. "\n")
        f:close()
        _battle_file_ok = true
    else
        console.log("!! BATTLE FILE WRITE FAILED: " .. tostring(BATTLE_OUT_PATH))
        _battle_file_ok = false
    end
end

-- log() writes to the output FILE ONLY (not console — avoids flooding).
-- con() writes to console only (brief progress messages the user should see).
local function log(s)
    _out_lines[#_out_lines + 1] = s
end
local function con(s) console.log(s) end
-- blog() writes to the BATTLE output file (separate from main log)
local function blog(s)
    _battle_lines[#_battle_lines + 1] = s
end
local function div() log("══════════════════════════════════════════════════════════════════") end
local function sep() log("──────────────────────────────────────────────────────────────────") end

-- FRLG character decoding (same encoding in all FRLG-based ROMs including CFRU/RR)
local CHARSET = {
    [0xBB]="A",[0xBC]="B",[0xBD]="C",[0xBE]="D",[0xBF]="E",
    [0xC0]="F",[0xC1]="G",[0xC2]="H",[0xC3]="I",[0xC4]="J",
    [0xC5]="K",[0xC6]="L",[0xC7]="M",[0xC8]="N",[0xC9]="O",
    [0xCA]="P",[0xCB]="Q",[0xCC]="R",[0xCD]="S",[0xCE]="T",
    [0xCF]="U",[0xD0]="V",[0xD1]="W",[0xD2]="X",[0xD3]="Y",[0xD4]="Z",
    [0xD5]="a",[0xD6]="b",[0xD7]="c",[0xD8]="d",[0xD9]="e",
    [0xDA]="f",[0xDB]="g",[0xDC]="h",[0xDD]="i",[0xDE]="j",
    [0xDF]="k",[0xE0]="l",[0xE1]="m",[0xE2]="n",[0xE3]="o",
    [0xE4]="p",[0xE5]="q",[0xE6]="r",[0xE7]="s",[0xE8]="t",
    [0xE9]="u",[0xEA]="v",[0xEB]="w",[0xEC]="x",[0xED]="y",[0xEE]="z",
    [0xA1]="0",[0xA2]="1",[0xA3]="2",[0xA4]="3",[0xA5]="4",
    [0xA6]="5",[0xA7]="6",[0xA8]="7",[0xA9]="8",[0xAA]="9",
    [0xAB]="!",[0xAC]="?",[0xAD]=".",[0xAE]="-",
    [0x00]=" ",
}

local function decodeStr(addr, max_len)
    local chars = {}
    for i = 0, max_len - 1 do
        local b = r8(addr + i)
        if b == 0xFF then break end
        chars[#chars + 1] = CHARSET[b] or "?"
    end
    return table.concat(chars):gsub("%s+$", "")
end

local function isValidFRLGName(addr, min_len)
    local len = 0
    for i = 0, 7 do
        local b = r8(addr + i)
        if b == 0xFF then break end
        if (b >= 0xBB and b <= 0xEE) or (b >= 0xA1 and b <= 0xAA) or b == 0x00 or b == 0xAB or b == 0xAC or b == 0xAD or b == 0xAE then
            len = len + 1
        else
            return false
        end
    end
    return len >= (min_len or 1)
end

-- Check if an EWRAM address is in valid range
local function isEWRAM(addr)
    return addr >= 0x02000000 and addr < 0x02040000
end

-- Collect results
local RESULTS = {}

-- Error-safe phase runner: runs a function, catches errors, flushes + reports
local function safe_run(phase_name, fn)
    con(fmt("[DISCOVERY] %s", phase_name))
    local ok, err = pcall(fn)
    if not ok then
        log(fmt("\n!! ERROR in %s: %s\n", phase_name, tostring(err)))
        con(fmt("!! ERROR in %s: %s", phase_name, tostring(err)))
    end
    _flush()
    if ok then
        con(fmt("[DISCOVERY] %s — done.", phase_name))
    end
end

-- ══════════════════════════════════════════════════════════════════════════════
-- PHASE 0: ROM IDENTIFICATION
-- ══════════════════════════════════════════════════════════════════════════════

div()
log("  SLINK RADICAL RED DISCOVERY — Comprehensive Address Scanner")
div()
log("")
if _file_ok then
    log(fmt("[OUTPUT] Writing results to: %s", OUT_PATH))
    if BATTLE_OUT_PATH then
        log(fmt("[OUTPUT] Battle results (F1/F2) go to: %s", BATTLE_OUT_PATH))
    end
else
    log("[OUTPUT] !! File output FAILED — results only in console (may be truncated).")
    log("[OUTPUT]    To fix: edit OUT_PATH at the top of this script to an absolute path.")
end
log("")
con("[DISCOVERY] Phase 0: ROM identification...")

-- Read game code (should be BPRE for any FireRed-based ROM)
local game_code = ""
for i = 0, 3 do
    game_code = game_code .. string.char(r8(0x080000AC + i, "System Bus"))
end
log(fmt("[ROM] Game code: %s", game_code))

-- Read ROM title (0x080000A0, 12 bytes)
local rom_title = ""
for i = 0, 11 do
    local b = r8(0x080000A0 + i, "System Bus")
    if b == 0 then break end
    rom_title = rom_title .. string.char(b)
end
log(fmt("[ROM] Title: %s", rom_title))

-- Scan ROM header region for CFRU/RR signatures
log("")
log("[ROM] Scanning for CFRU/RR signatures...")

-- Check offset 0x108 (AP detection region) — RR/CFRU will NOT have "pokemon red/green version"
local rom_108_bytes = {}
for i = 0, 63 do
    local b = r8(0x08000108 + i, "System Bus")
    if b == 0 then break end
    rom_108_bytes[#rom_108_bytes + 1] = string.char(b)
end
local rom_108_str = table.concat(rom_108_bytes):lower()
log(fmt("  ROM+0x108: \"%s\"", table.concat(rom_108_bytes)))

local is_ap = rom_108_str:find("pokemon red version") or rom_108_str:find("pokemon green version")
if is_ap then
    log("  WARNING: This looks like an AP ROM, not Radical Red!")
end

-- Scan for known CFRU markers in ROM
-- CFRU often has version strings or identifiable code patterns
local cfru_markers = {}

-- Optimized ROM string scanner: reads in 256-byte chunks to avoid per-byte overhead
local function scanROMForASCII(target, start_addr, end_addr)
    local target_lower = target:lower()
    local tlen = #target
    local CHUNK = 256
    for chunk_start = start_addr, end_addr - tlen, CHUNK do
        -- Read a chunk into a Lua string
        local bytes = {}
        local chunk_end = math.min(chunk_start + CHUNK - 1 + tlen, end_addr)
        for i = chunk_start, chunk_end do
            bytes[#bytes + 1] = string.char(r8(i, "System Bus"))
        end
        local chunk_str = table.concat(bytes):lower()
        local pos = chunk_str:find(target_lower, 1, true)
        if pos then
            return chunk_start + pos - 1
        end
    end
    return nil
end

-- Scan first 512KB for key markers (chunked reads make this ~2000x faster)
con("[DISCOVERY]   Scanning ROM for CFRU/RR signatures...")
local scan_targets = {"Radical Red", "CFRU", "Complete Fire Red"}
for _, target in ipairs(scan_targets) do
    local addr = scanROMForASCII(target, 0x08000000, 0x08080000)
    if addr then
        local context = ""
        for i = 0, math.min(31, #target + 15) do
            local b = r8(addr + i, "System Bus")
            if b >= 32 and b < 127 then context = context .. string.char(b) end
        end
        log(fmt("  FOUND \"%s\" at %s: \"%s\"", target, hex(addr), context))
        cfru_markers[#cfru_markers + 1] = {target=target, addr=addr, context=context}
    end
end

-- Wider scan (2MB) only for "Radical Red" if nothing found yet
if #cfru_markers == 0 then
    log("  No markers in first 512KB, scanning wider (2MB)...")
    con("[DISCOVERY]   Extended ROM scan (2MB)...")
    local rr_addr = scanROMForASCII("Radical Red", 0x08080000, 0x08200000)
    if rr_addr then
        log(fmt("  FOUND \"Radical Red\" at %s", hex(rr_addr)))
        cfru_markers[#cfru_markers + 1] = {target="Radical Red", addr=rr_addr}
    end
end

if #cfru_markers == 0 then
    log("  No CFRU/RR string markers found. Will try structural detection.")
end

-- Store unique ROM bytes for fingerprinting (first 256 bytes after header)
local rom_fingerprint = {}
for i = 0, 15 do
    rom_fingerprint[#rom_fingerprint + 1] = fmt("%02X", r8(0x080000C0 + i, "System Bus"))
end
RESULTS.rom_fingerprint = table.concat(rom_fingerprint, " ")
log(fmt("  ROM fingerprint (0xC0-0xCF): %s", RESULTS.rom_fingerprint))

_flush()  -- save Phase 0 results
con("[DISCOVERY] Phase 0 complete.")

-- ══════════════════════════════════════════════════════════════════════════════
-- PHASE 1: IWRAM POINTER DISCOVERY
-- ══════════════════════════════════════════════════════════════════════════════
con("[DISCOVERY] Phase 1: IWRAM pointer scan...")

sep()
log("")
log("[PHASE 1] Scanning IWRAM for SaveBlock pointers...")
log("")

-- Strategy: Scan all of IWRAM (0x03000000-0x03007FFF) for 4-byte-aligned values
-- that point into EWRAM (0x02000000-0x0203FFFF). For each, validate the target.

local iwram_candidates = {}  -- {addr, target, type}

for addr = 0x03000000, 0x03007FFC, 4 do
    local val = r32(addr)
    if isEWRAM(val) then
        iwram_candidates[#iwram_candidates + 1] = {addr=addr, target=val}
    end
end
log(fmt("  Found %d IWRAM→EWRAM pointers to test", #iwram_candidates))

-- ── Find gSaveBlock1Ptr ─────────────────────────────────────────────────────
-- SB1: offset +0x0004 has WarpData (mapGroup u8, mapNum u8)
-- CFRU SB1 also has playerPartyCount at +0x0034 (u8, 0–6)
-- and flags at +0x0EE0

log("")
log("  --- Searching for gSaveBlock1Ptr ---")
local sb1_candidates = {}

for _, c in ipairs(iwram_candidates) do
    local target = c.target
    -- Check location data at +0x0004
    local mapGroup = r8(target + 0x0004)
    local mapNum   = r8(target + 0x0005)
    -- Check party count at +0x0034 (CFRU layout)
    local partyCount = r8(target + 0x0034)
    -- Basic plausibility
    if mapGroup <= 42 and mapNum <= 200 and partyCount >= 1 and partyCount <= 6 then
        -- Additional check: flags region at +0x0EE0 should have some set bits
        local flagByte = r8(target + 0x0EE0)
        local flagByte2 = r8(target + 0x0EE0 + 1)
        -- Check that +0x0034 party count makes sense with actual Pokemon at +0x0038
        local firstMonPersonality = r32(target + 0x0038)
        local firstMonMaxHP = r16(target + 0x0038 + 0x58)
        local hasValidMon = firstMonPersonality ~= 0 and firstMonMaxHP > 0 and firstMonMaxHP < 1000
        
        if hasValidMon then
            local score = 0
            if flagByte ~= 0 or flagByte2 ~= 0 then score = score + 2 end
            if mapGroup > 0 or mapNum > 0 then score = score + 1 end
            score = score + 3  -- has valid mon
            sb1_candidates[#sb1_candidates + 1] = {
                iwram_addr = c.addr, target = target,
                mapGroup = mapGroup, mapNum = mapNum,
                partyCount = partyCount, score = score
            }
        end
    end
end

table.sort(sb1_candidates, function(a, b) return a.score > b.score end)

if #sb1_candidates > 0 then
    local best = sb1_candidates[1]
    log(fmt("  ✓ gSaveBlock1Ptr = %s → %s", hex(best.iwram_addr), hex(best.target)))
    log(fmt("    map=%d:%d  partyCount=%d  score=%d", best.mapGroup, best.mapNum, best.partyCount, best.score))
    RESULTS.SB1_PTR_ADDR = best.iwram_addr
    RESULTS.sb1_value = best.target
    
    -- Read trainer name from party mon OT (party is at SB1+0x0038, otName at mon+0x14)
    local partyBase = best.target + 0x0038
    log(fmt("    Party mon 0 personality: %s", hex(r32(partyBase))))
    log(fmt("    Party mon 0 maxHP: %d", r16(partyBase + 0x58)))
    log(fmt("    Party mon 0 level: %d", r8(partyBase + 0x54)))
    
    if #sb1_candidates > 1 then
        log(fmt("    (%d other candidates with lower scores)", #sb1_candidates - 1))
    end
else
    log("  ✗ gSaveBlock1Ptr NOT FOUND")
end

-- ── Find gSaveBlock2Ptr ─────────────────────────────────────────────────────
-- SB2: offset +0x0000 has playerName (FRLG-encoded, 7 chars + 0xFF)
-- SB2: offset +0x0008 has playerGender (0=male, 1=female)
-- SB2: offset +0x000A has specialSaveWarpFlags or regionMapZoom
-- SB2: offset +0x0F20 has encryptionKey (u32, non-zero when save loaded)
-- SB2: offset +0x0AF8 has securityKey (u32, mirrors encryptionKey in FRLG)
-- In vanilla, gSaveBlock2Ptr is near gSaveBlock1Ptr in IWRAM.

log("")
log("  --- Searching for gSaveBlock2Ptr ---")
log("    (showing ALL candidates with scores for reliability)")
local sb2_candidates = {}

for _, c in ipairs(iwram_candidates) do
    local target = c.target
    if RESULTS.SB1_PTR_ADDR and c.addr == RESULTS.SB1_PTR_ADDR then goto continue_sb2 end

    -- Check for valid trainer name at +0x0000 (at least 2 chars)
    if isValidFRLGName(target, 2) then
        -- Check encryptionKey at +0x0F20 (should be non-zero)
        local encKey = r32(target + 0x0F20)
        if encKey ~= 0 then
            local name = decodeStr(target, 7)
            local gender = r8(target + 0x0008)
            if gender <= 1 then
                local score = 0
                -- Base: valid name + encKey + gender
                score = score + 5

                -- Penalty: encKey = 0xFFFFFFFF looks like uninitialized memory
                if encKey == 0xFFFFFFFF or encKey == 0x00000001 then
                    score = score - 8
                end

                -- Bonus: proximity to SB1 in IWRAM (within 32 bytes)
                if RESULTS.SB1_PTR_ADDR then
                    local dist = math.abs(c.addr - RESULTS.SB1_PTR_ADDR)
                    if dist <= 8 then score = score + 10  -- likely consecutive
                    elseif dist <= 32 then score = score + 5
                    elseif dist <= 128 then score = score + 2
                    end
                end

                -- Bonus: securityKey at +0x0AF8 matches encryptionKey
                local secKey = r32(target + 0x0AF8)
                if secKey == encKey then score = score + 5 end

                -- Bonus: playTimeHours at +0x000E is plausible (0–999)
                local playHours = r16(target + 0x000E)
                if playHours < 1000 then score = score + 2 end

                -- Bonus: trainer name matches party mon OT name
                if RESULTS.sb1_value then
                    local partyBase = RESULTS.sb1_value + 0x0038
                    local otName = decodeStr(partyBase + 0x14, 7)
                    if otName == name and #name >= 2 then score = score + 8 end
                end

                sb2_candidates[#sb2_candidates + 1] = {
                    iwram_addr = c.addr, target = target,
                    name = name, encKey = encKey, gender = gender,
                    secKey = secKey, playHours = playHours,
                    score = score
                }
            end
        end
    end
    ::continue_sb2::
end

table.sort(sb2_candidates, function(a, b) return a.score > b.score end)

log(fmt("  Found %d SB2 candidate(s):", #sb2_candidates))
for i, c in ipairs(sb2_candidates) do
    local dist_str = ""
    if RESULTS.SB1_PTR_ADDR then
        dist_str = fmt("  dist_from_SB1=%d", math.abs(c.iwram_addr - RESULTS.SB1_PTR_ADDR))
    end
    log(fmt("    [%d] IWRAM=%s → %s  name=\"%s\"  gender=%d  encKey=%s  secKey=%s  hours=%d  score=%d%s",
        i, hex(c.iwram_addr), hex(c.target), c.name, c.gender,
        hex(c.encKey), hex(c.secKey), c.playHours, c.score, dist_str))
end

if #sb2_candidates > 0 then
    local best = sb2_candidates[1]
    log(fmt("  ✓ gSaveBlock2Ptr = %s → %s (score=%d)", hex(best.iwram_addr), hex(best.target), best.score))
    if #sb2_candidates > 1 then
        local second = sb2_candidates[2]
        if second.score == best.score then
            log(fmt("  ⚠ TIED with [2] %s (score=%d) — run discovery again to confirm",
                hex(second.iwram_addr), second.score))
        end
    end
    RESULTS.SB2_PTR_ADDR = best.iwram_addr
    RESULTS.sb2_value = best.target
    RESULTS.encKey = best.encKey
else
    log("  ✗ gSaveBlock2Ptr NOT FOUND")
end

-- ── Find gPokemonStoragePtr ─────────────────────────────────────────────────
-- PSP: offset +0x0000 = currentBox (u8, 0–24 for CFRU)
-- PSP: boxes start at +0x0004 (vanilla) or +0x0001 — try both
-- Each box = 30 × BoxPokemon (80 bytes) = 2400 bytes
-- CFRU can have up to 25 boxes = 25 × 30 × 80 = 60000 bytes
-- Box names follow box data: decodable FRLG text (8 chars + 0xFF terminator each)
-- Proximity to SB1/SB2 in IWRAM is a strong positive signal.

log("")
log("  --- Searching for gPokemonStoragePtr ---")
log("    (showing ALL candidates with scores for reliability)")
local psp_candidates = {}

for _, c in ipairs(iwram_candidates) do
    local target = c.target
    if RESULTS.SB1_PTR_ADDR and c.addr == RESULTS.SB1_PTR_ADDR then goto continue_psp end
    if RESULTS.SB2_PTR_ADDR and c.addr == RESULTS.SB2_PTR_ADDR then goto continue_psp end

    local currentBox = r8(target)
    if currentBox <= 24 then
        -- Try both box-data start offsets
        for _, boxStart in ipairs({0x0004, 0x0001}) do
            local score = 0
            local validSlots = 0
            local emptySlots = 0
            local firstBoxAddr = target + boxStart

            -- Validate slots across multiple boxes (check 3 boxes × 5 slots)
            for box = 0, 2 do
                for slot = 0, 4 do
                    local slotAddr = firstBoxAddr + (box * 30 + slot) * 80
                    local sf = r8(slotAddr + 0x13)
                    local pers = r32(slotAddr)
                    if pers == 0 and r32(slotAddr + 4) == 0 then
                        emptySlots = emptySlots + 1  -- empty slot
                    elseif (sf & 0x02) ~= 0 and pers ~= 0 then
                        validSlots = validSlots + 1  -- occupied + hasSpecies flag
                    end
                end
            end

            -- Need at least some valid or empty structure
            local totalChecked = validSlots + emptySlots
            if totalChecked < 8 then goto continue_box_start end

            score = validSlots * 2 + emptySlots

            -- Bonus: box names are readable FRLG text
            -- Try both 14-box (vanilla) and 25-box (CFRU) layouts for name offset
            local readableNames = 0
            local bestNameLayout = nil
            for _, numBoxes in ipairs({24, 14}) do
                local namesOff = boxStart + numBoxes * 30 * 80
                local names = 0
                for bi = 0, math.min(numBoxes - 1, 5) do
                    local nameAddr = target + namesOff + bi * 9
                    if isValidFRLGName(nameAddr, 2) then
                        names = names + 1
                    end
                end
                if names > readableNames then
                    readableNames = names
                    bestNameLayout = {numBoxes = numBoxes, offset = namesOff}
                end
            end
            if readableNames >= 3 then
                score = score + readableNames * 3  -- strong signal
            end

            -- Bonus: proximity to SB1 in IWRAM
            if RESULTS.SB1_PTR_ADDR then
                local dist = math.abs(c.addr - RESULTS.SB1_PTR_ADDR)
                if dist <= 16 then score = score + 10
                elseif dist <= 64 then score = score + 5
                elseif dist <= 256 then score = score + 2
                end
            end

            -- Bonus: proximity to SB2 in IWRAM
            if RESULTS.SB2_PTR_ADDR then
                local dist = math.abs(c.addr - RESULTS.SB2_PTR_ADDR)
                if dist <= 16 then score = score + 5
                elseif dist <= 64 then score = score + 3
                end
            end

            -- Bonus: OT name of first occupied box mon matches trainer name
            if RESULTS.sb2_value then
                local trainerName = decodeStr(RESULTS.sb2_value, 7)
                for slot = 0, 29 do
                    local slotAddr = firstBoxAddr + slot * 80
                    if r32(slotAddr) ~= 0 and (r8(slotAddr + 0x13) & 0x02) ~= 0 then
                        local otName = decodeStr(slotAddr + 0x14, 7)
                        if otName == trainerName and #trainerName >= 2 then
                            score = score + 6
                        end
                        break  -- only check first occupied
                    end
                end
            end

            if score >= 5 then
                psp_candidates[#psp_candidates + 1] = {
                    iwram_addr = c.addr, target = target,
                    currentBox = currentBox, boxStart = boxStart,
                    validSlots = validSlots, emptySlots = emptySlots,
                    readableNames = readableNames,
                    nameLayout = bestNameLayout,
                    score = score
                }
            end

            ::continue_box_start::
        end
    end
    ::continue_psp::
end

-- Sort by score DESC, then prefer boxStart=0x0001 (CFRU source: pokemon_storage_system.h), then addr
table.sort(psp_candidates, function(a, b)
    if a.score ~= b.score then return a.score > b.score end
    -- Tiebreak: prefer boxStart +0x0001 (CFRU convention per pokemon_storage_system.h)
    if a.iwram_addr == b.iwram_addr and a.boxStart ~= b.boxStart then
        return a.boxStart == 0x0001
    end
    return a.iwram_addr < b.iwram_addr
end)

-- Deduplicate: when same IWRAM addr appears with both boxStart values, keep best
local psp_deduped = {}
local psp_seen_iwram = {}
for _, c in ipairs(psp_candidates) do
    if not psp_seen_iwram[c.iwram_addr] then
        psp_deduped[#psp_deduped + 1] = c
        psp_seen_iwram[c.iwram_addr] = true
    end
end
psp_candidates = psp_deduped

log(fmt("  Found %d PSP candidate(s):", #psp_candidates))
for i, c in ipairs(psp_candidates) do
    local dist_str = ""
    if RESULTS.SB1_PTR_ADDR then
        dist_str = fmt("  dist_from_SB1=%d", math.abs(c.iwram_addr - RESULTS.SB1_PTR_ADDR))
    end
    local layout_str = ""
    if c.nameLayout then
        layout_str = fmt("  nameLayout=%d_boxes", c.nameLayout.numBoxes)
    end
    log(fmt("    [%d] IWRAM=%s → %s  curBox=%d  boxStart=+0x%04X  valid=%d  empty=%d  names=%d  score=%d%s%s",
        i, hex(c.iwram_addr), hex(c.target), c.currentBox, c.boxStart,
        c.validSlots, c.emptySlots, c.readableNames, c.score, dist_str, layout_str))
end

if #psp_candidates > 0 then
    local best = psp_candidates[1]
    log(fmt("  ✓ gPokemonStoragePtr = %s → %s (score=%d)", hex(best.iwram_addr), hex(best.target), best.score))

    if #psp_candidates > 1 then
        local second = psp_candidates[2]
        if second.score == best.score then
            log(fmt("  ⚠ TIED with [2] %s (score=%d) — run discovery again to confirm",
                hex(second.iwram_addr), second.score))
        end
    end

    RESULTS.PSP_PTR_ADDR = best.iwram_addr
    RESULTS.psp_value = best.target
    RESULTS.psp_box_start = best.boxStart

    -- Dump box names for verification
    if best.nameLayout then
        local namesOff = best.nameLayout.offset
        log(fmt("    Box names (layout=%d boxes, offset=+0x%04X):", best.nameLayout.numBoxes, namesOff))
        for bi = 0, math.min(best.nameLayout.numBoxes - 1, 9) do
            local nameAddr = best.target + namesOff + bi * 9
            local bn = decodeStr(nameAddr, 8)
            log(fmt("      Box %2d: \"%s\"", bi, bn))
        end
        RESULTS.BOXES_PER_STORE = best.nameLayout.numBoxes
        RESULTS.BOX_NAMES_OFFSET = namesOff
    else
        -- Fallback: try reading names at vanilla offset
        local namesOff = best.boxStart + 14 * 30 * 80
        local bn = decodeStr(best.target + namesOff, 8)
        log(fmt("    Box 0 name (vanilla offset +%s): \"%s\"", hex4(namesOff), bn))
    end
else
    log("  ✗ gPokemonStoragePtr NOT FOUND")
end

-- ── Find gMain ──────────────────────────────────────────────────────────────
-- gMain is in IWRAM, large struct (~0x43A bytes)
-- At offset +0x438 = state (u8), +0x439 = bitfield with inBattle at bit 1
-- In overworld: bit 1 of +0x439 should be 0

log("")
log("  --- Searching for gMain ---")
local gmain_candidates = {}

-- gMain is typically near the start of IWRAM. Scan for plausible locations.
-- Key insight: gMain is ~1082 bytes. It's directly in IWRAM (not a pointer to EWRAM).
-- We look for a location where +0x439 bit 1 = 0 (we're in overworld now).
-- Additional checks: +0x438 should be a small value (state enum).

for addr = 0x03000000, 0x03007000, 4 do
    local state_byte = r8(addr + 0x438)
    local flags_byte = r8(addr + 0x439)
    local inBattle = (flags_byte & 0x02) ~= 0
    
    -- In overworld: inBattle should be false, state should be reasonable
    if not inBattle and state_byte < 20 then
        -- Additional validation: the struct shouldn't be all zeros
        local nonzero = 0
        for i = 0, 15 do
            if r8(addr + i) ~= 0 then nonzero = nonzero + 1 end
        end
        if nonzero >= 3 then
            -- Check that nearby memory looks struct-like (not random data)
            local score = nonzero
            gmain_candidates[#gmain_candidates + 1] = {
                addr = addr, state = state_byte,
                flags = flags_byte, score = score
            }
        end
    end
end

-- Among candidates, prefer those near known FRLG gMain locations
-- Vanilla: 0x030030F0, AP: 0x03003040
-- CFRU/RR will be somewhere in IWRAM, likely 0x03002000–0x03005000
local preferred_candidates = {}
for _, c in ipairs(gmain_candidates) do
    if c.addr >= 0x03002000 and c.addr <= 0x03005000 then
        c.score = c.score + 5
        preferred_candidates[#preferred_candidates + 1] = c
    end
end

table.sort(preferred_candidates, function(a, b) return a.score > b.score end)

if #preferred_candidates > 0 then
    -- Show top candidates (there may be false positives)
    log(fmt("  Found %d candidates in preferred range (showing top 5):", #preferred_candidates))
    for i = 1, math.min(5, #preferred_candidates) do
        local c = preferred_candidates[i]
        log(fmt("    [%d] %s  state=%d flags=0x%02X score=%d",
            i, hex(c.addr), c.state, c.flags, c.score))
    end
    RESULTS.GMAIN_ADDR = preferred_candidates[1].addr
    log(fmt("  ✓ gMain (best guess) = %s", hex(RESULTS.GMAIN_ADDR)))
    log("    NOTE: Verify by pressing F1 during battle — bit 1 of +0x439 should flip to 1")
else
    log("  ✗ gMain NOT FOUND in preferred range")
    if #gmain_candidates > 0 then
        log(fmt("  Found %d candidates outside preferred range:", #gmain_candidates))
        for i = 1, math.min(3, #gmain_candidates) do
            local c = gmain_candidates[i]
            log(fmt("    %s  state=%d flags=0x%02X", hex(c.addr), c.state, c.flags))
        end
        RESULTS.GMAIN_ADDR = gmain_candidates[1].addr
    end
end

_flush()  -- save Phase 1 results
con("[DISCOVERY] Phase 1 complete.")

-- ══════════════════════════════════════════════════════════════════════════════
-- PHASE 2: EWRAM GLOBAL DISCOVERY
-- ══════════════════════════════════════════════════════════════════════════════
con("[DISCOVERY] Phase 2: EWRAM globals (party, bag)...")

sep()
log("")
log("[PHASE 2] Searching EWRAM for party and bag globals...")
log("")

-- ── Find gPlayerPartyCount + gPlayerParty ───────────────────────────────────
-- Strategy A: If we found SB1, party is at SB1+0x0034 (count) and SB1+0x0038 (data)
-- Strategy B: Scan EWRAM independently for party pattern

local PARTY_SIZE = 0x64  -- 100 bytes per Pokemon

log("  --- gPlayerPartyCount / gPlayerParty ---")

-- Strategy A: Derive from SaveBlock1
local partyCount_A, partyBase_A
if RESULTS.sb1_value then
    partyCount_A = r8(RESULTS.sb1_value + 0x0034)
    partyBase_A = RESULTS.sb1_value + 0x0038
    log(fmt("  Strategy A (SB1+0x34/0x38): count=%d, base=%s", partyCount_A, hex(partyBase_A)))
    
    -- Validate: check first mon
    local p0 = r32(partyBase_A)
    local hp0 = r16(partyBase_A + 0x56)
    local mhp0 = r16(partyBase_A + 0x58)
    log(fmt("    Mon 0: personality=%s  HP=%d/%d", hex(p0), hp0, mhp0))
end

-- Strategy B: Scan EWRAM for standalone gPlayerPartyCount/gPlayerParty
-- In CFRU, there's both the SB1 embedded copy AND separate EWRAM globals
-- The EWRAM globals are the "live" copies the game actually reads during gameplay
log("")
log("  Strategy B (EWRAM scan): Looking for standalone party globals...")

local party_ewram_candidates = {}

-- We know the party count from SB1. Scan EWRAM for matching count byte
-- followed by valid party data at a predictable offset.
local known_count = partyCount_A or 0

if known_count > 0 then
    -- Also get the first mon's personality from SB1 for cross-reference
    local known_personality = partyBase_A and r32(partyBase_A) or 0
    
    for addr = 0x02020000, 0x0203F000, 1 do
        local count = r8(addr)
        if count == known_count then
            -- Check if there's valid party data nearby
            -- Common patterns: party starts immediately after count (vanilla: count at -1 relative)
            -- or party starts at a fixed offset from count
            -- Vanilla: gPlayerPartyCount=0x02024029, gPlayerParty=0x02024284 (offset 0x25B)
            -- But in CFRU with SB1-embedded party, the EWRAM global might mirror SB1+0x0038
            
            -- Check: does addr+1 through addr+600 have the same data as SB1 party?
            if known_personality ~= 0 then
                -- Look for the personality value near this count byte
                for offset = 1, 0x300, 4 do
                    if addr + offset + PARTY_SIZE <= 0x02040000 then
                        local p = r32(addr + offset)
                        if p == known_personality then
                            -- Validate more of the party
                            local matchCount = 0
                            for slot = 0, known_count - 1 do
                                local slotAddr = addr + offset + slot * PARTY_SIZE
                                local sp = r32(slotAddr)
                                local smhp = r16(slotAddr + 0x58)
                                if sp ~= 0 and smhp > 0 and smhp < 1000 then
                                    matchCount = matchCount + 1
                                end
                            end
                            if matchCount == known_count then
                                -- Check if this is different from the SB1 address
                                local isDifferentFromSB1 = (addr + offset) ~= partyBase_A
                                party_ewram_candidates[#party_ewram_candidates + 1] = {
                                    countAddr = addr,
                                    partyAddr = addr + offset,
                                    offset = offset,
                                    isSB1 = not isDifferentFromSB1,
                                    matchCount = matchCount
                                }
                            end
                        end
                    end
                end
            end
        end
    end
    
    log(fmt("  Found %d party candidates", #party_ewram_candidates))
    for i, c in ipairs(party_ewram_candidates) do
        local label = c.isSB1 and " (=SB1 embedded)" or " (EWRAM global)"
        log(fmt("    [%d] count@%s  party@%s  offset=%d%s",
            i, hex(c.countAddr), hex(c.partyAddr), c.offset, label))
    end
    
    -- Determine which is the live EWRAM global (not the SB1 copy)
    local ewram_party = nil
    for _, c in ipairs(party_ewram_candidates) do
        if not c.isSB1 then
            ewram_party = c
            break
        end
    end
    
    if ewram_party then
        RESULTS.PARTY_COUNT_ADDR = ewram_party.countAddr
        RESULTS.PARTY_BASE = ewram_party.partyAddr
        log(fmt("  ✓ gPlayerPartyCount = %s (EWRAM global)", hex(RESULTS.PARTY_COUNT_ADDR)))
        log(fmt("  ✓ gPlayerParty = %s (EWRAM global)", hex(RESULTS.PARTY_BASE)))
    elseif partyBase_A then
        -- Fallback: use SB1 addresses (CFRU might only use the SB1 copy)
        RESULTS.PARTY_COUNT_ADDR = RESULTS.sb1_value + 0x0034
        RESULTS.PARTY_BASE = partyBase_A
        log(fmt("  ⚠ No separate EWRAM party found; using SB1 embedded party"))
        log(fmt("  ✓ gPlayerPartyCount = %s (SB1+0x0034)", hex(RESULTS.PARTY_COUNT_ADDR)))
        log(fmt("  ✓ gPlayerParty = %s (SB1+0x0038)", hex(RESULTS.PARTY_BASE)))
    end
else
    log("  ✗ Cannot scan — party count unknown (SB1 not found)")
end

-- ── Find gBagPockets (EWRAM ball pocket) ────────────────────────────────────
-- CFRU stores bag in EWRAM at gBagPockets, NOT in SaveBlock1.
-- CFRU source (ram_locs.h): gBagPokeBalls[50] at 0x203C354
-- Ball pocket has 50 ItemSlot entries (4 bytes each = 200 bytes).
-- Ball item IDs: 1–12 (standard), 52–53, 60–62, 622–631
-- RR may shift this address, so we check CFRU known addr first, then scan.

log("")
log("  --- gBagPockets / Ball Pocket (EWRAM) ---")

-- CFRU known ball pocket address (from ram_locs.h)
local CFRU_BALL_POCKET = 0x0203C354

local BALL_IDS = {
    [1]=true, [2]=true, [3]=true, [4]=true, [5]=true, [6]=true,
    [7]=true, [8]=true, [9]=true, [10]=true, [11]=true, [12]=true,
    [52]=true, [53]=true, [60]=true, [61]=true, [62]=true,
    [622]=true, [623]=true, [624]=true, [625]=true, [626]=true,
    [627]=true, [628]=true, [629]=true, [630]=true, [631]=true,
}
local BALL_NAMES = {
    [1]="Master", [2]="Ultra", [3]="Great", [4]="Poke", [5]="Safari",
    [6]="Net", [7]="Dive", [8]="Nest", [9]="Repeat", [10]="Timer",
    [11]="Luxury", [12]="Premier", [52]="Park", [53]="Cherish",
    [60]="Dusk", [61]="Heal", [62]="Quick",
    [622]="Fast", [623]="Level", [624]="Lure", [625]="Heavy",
    [626]="Love", [627]="Friend", [628]="Moon", [629]="Sport",
    [630]="Beast", [631]="Dream",
}

-- Check CFRU known address first (0x203C354)
log("  Checking CFRU known address (0x203C354)...")
local cfru_valid = false
do
    local cfru_balls = 0
    local cfru_total_qty = 0
    local cfru_empty = 0
    for i = 0, 49 do
        local id = r16(CFRU_BALL_POCKET + i * 4)
        local qty = r16(CFRU_BALL_POCKET + i * 4 + 2)
        if BALL_IDS[id] then
            cfru_balls = cfru_balls + 1
            cfru_total_qty = cfru_total_qty + qty
        elseif id == 0 then
            cfru_empty = cfru_empty + 1
        end
    end
    log(fmt("    CFRU addr: balls=%d totalQty=%d empty=%d", cfru_balls, cfru_total_qty, cfru_empty))
    if cfru_empty >= 40 then
        -- Mostly empty is valid (0 balls = all 50 slots empty, or a few ball types)
        cfru_valid = true
        log("    ✓ CFRU address looks valid (mostly empty slots = clean pocket structure)")
    end
    if cfru_balls >= 1 then
        cfru_valid = true
        log("    ✓ CFRU address has ball items")
    end
    -- Dump non-empty slots
    for i = 0, math.min(9, 49) do
        local id = r16(CFRU_BALL_POCKET + i * 4)
        local qty = r16(CFRU_BALL_POCKET + i * 4 + 2)
        if id ~= 0 then
            local name = BALL_NAMES[id] or fmt("item_%d", id)
            log(fmt("      [%2d] id=%3d %-8s  rawQty=%d (0x%04X)", i, id, name, qty, qty))
        end
    end
end

-- Scan EWRAM for clusters of ball item IDs on 4-byte boundaries
log("  Scanning EWRAM for ball pocket candidates...")
local bag_candidates = {}

for addr = 0x02020000, 0x0203F000, 4 do
    local id = r16(addr)
    if BALL_IDS[id] then
        -- Found a ball item. Check if this is part of a pocket (multiple balls nearby)
        local ballCount = 0
        local totalQty = 0
        local maxOffset = 0
        for i = 0, 49 do  -- up to 50 slots
            local slot_id = r16(addr + i * 4)
            if BALL_IDS[slot_id] then
                ballCount = ballCount + 1
                totalQty = totalQty + r16(addr + i * 4 + 2)
                maxOffset = i
            elseif slot_id == 0 then
                -- empty slot, still valid
            else
                break  -- non-ball, non-empty → end of pocket
            end
        end
        if ballCount >= 2 then
            bag_candidates[#bag_candidates + 1] = {
                addr = addr, ballCount = ballCount, totalQty = totalQty, maxSlot = maxOffset
            }
        end
    end
end

-- Deduplicate (keep only the start of each cluster)
local bag_unique = {}
local last_addr = 0
for _, c in ipairs(bag_candidates) do
    if c.addr - last_addr > 200 then
        bag_unique[#bag_unique + 1] = c
        last_addr = c.addr
    end
end

-- Score and sort: prefer more ball types + reasonable quantities
table.sort(bag_unique, function(a, b)
    local sa = a.ballCount * 10 + (a.maxSlot < 49 and 5 or 0)
    local sb = b.ballCount * 10 + (b.maxSlot < 49 and 5 or 0)
    return sa > sb
end)

if #bag_unique > 0 then
    log(fmt("  Found %d ball pocket candidate(s):", #bag_unique))
    for i, c in ipairs(bag_unique) do
        log(fmt("    [%d] %s  balls=%d  totalQty=%d  maxSlot=%d", i, hex(c.addr), c.ballCount, c.totalQty, c.maxSlot))
        -- Dump first few entries
        for slot = 0, math.min(9, c.maxSlot + 2) do
            local id = r16(c.addr + slot * 4)
            local qty = r16(c.addr + slot * 4 + 2)
            if id ~= 0 then
                local name = BALL_NAMES[id] or fmt("item_%d", id)
                log(fmt("      [%2d] id=%3d %-8s  rawQty=%d (0x%04X)", slot, id, name, qty, qty))
            end
        end
    end
    -- Prefer CFRU known address if it was valid
    if cfru_valid then
        RESULTS.BALL_POCKET_ADDR = CFRU_BALL_POCKET
        RESULTS.BALL_POCKET_COUNT = 50
        log(fmt("  ✓ Ball pocket @ %s (CFRU known address)", hex(CFRU_BALL_POCKET)))
        -- Check if any scan candidate matched the CFRU address
        local scan_matched = false
        for _, c in ipairs(bag_unique) do
            if c.addr == CFRU_BALL_POCKET then
                scan_matched = true
                log(fmt("    ✓ Scan also found this address (balls=%d totalQty=%d)", c.ballCount, c.totalQty))
            end
        end
        if not scan_matched then
            log("    Note: Scan did NOT find this address (pocket may be empty — that's OK)")
        end
    else
        RESULTS.BALL_POCKET_ADDR = bag_unique[1].addr
        RESULTS.BALL_POCKET_COUNT = 50
        log(fmt("  ✓ Ball pocket @ %s (scan result, totalQty=%d)", hex(RESULTS.BALL_POCKET_ADDR), bag_unique[1].totalQty))
        log("    ⚠ CFRU known address (0x203C354) was invalid — RR may have shifted it")
        log("    ⚠ Compare totalQty with your actual in-game ball count!")
    end
else
    if cfru_valid then
        RESULTS.BALL_POCKET_ADDR = CFRU_BALL_POCKET
        RESULTS.BALL_POCKET_COUNT = 50
        log(fmt("  ✓ Ball pocket @ %s (CFRU known address, no scan matches)", hex(CFRU_BALL_POCKET)))
        log("    Pocket may be empty (0 balls) — that's normal early game")
    else
        log("  ✗ No ball pocket found in EWRAM — try SB1 fallback")
        -- Fallback: scan SB1 for balls (like vanilla)
        if RESULTS.sb1_value then
            log("  Scanning SB1 for balls (vanilla/fallback)...")
            for offset = 0x0000, 0x3FFC, 4 do
                local id = r16(RESULTS.sb1_value + offset)
                if id >= 1 and id <= 12 then
                    local qty = r16(RESULTS.sb1_value + offset + 2)
                    if qty < 1000 then
                        log(fmt("    SB1+%s: id=%d qty=%d", hex4(offset), id, qty))
                    end
                end
            end
        end
    end  -- cfru_valid / SB1 fallback
end  -- #bag_unique > 0

-- Also try to determine if quantities are encrypted
if RESULTS.BALL_POCKET_ADDR and RESULTS.encKey then
    log("")
    log("  Testing item quantity encryption:")
    local first_qty_raw = r16(RESULTS.BALL_POCKET_ADDR + 2)
    local qty_xor_lo16 = first_qty_raw ~ (RESULTS.encKey & 0xFFFF)
    local qty_xor_full = first_qty_raw ~ r16(RESULTS.sb2_value + 0x0F20)
    log(fmt("    Raw qty: %d (0x%04X)", first_qty_raw, first_qty_raw))
    log(fmt("    XOR with encKey lo16: %d", qty_xor_lo16))
    log(fmt("    If encrypted → actual qty = %d", qty_xor_lo16))
    log(fmt("    If NOT encrypted → actual qty = %d", first_qty_raw))
    log("    (Check which matches your in-game ball count)")
end

_flush()  -- save Phase 2 results
con("[DISCOVERY] Phase 2 complete.")

-- ══════════════════════════════════════════════════════════════════════════════
-- PHASE 3: SOUND ENGINE DISCOVERY (reuses test_sound_discovery logic)
-- ══════════════════════════════════════════════════════════════════════════════
con("[DISCOVERY] Phase 3: Sound engine...")

sep()
log("")
log("[PHASE 3] Sound engine — finding gSongTable and SE headers...")
log("")

local SOUND_INFO_PTR_ADDR = 0x3007FF0
local O_SNDINFO_HEAD = 0x24
local O_MPL_SONG_HDR = 0x00
local O_MPL_STATUS   = 0x04
local O_MPL_IDENT    = 0x34
local O_MPL_NEXT     = 0x3C
local SONG_ENTRY_SIZE = 8

local TARGET_SES = {
    { id = 16, name = "SE_FAINT" },
    { id = 17, name = "SE_FLEE" },
    { id = 22, name = "SE_BOO" },
    { id = 25, name = "SE_SUCCESS" },
    { id = 26, name = "SE_FAILURE" },
    { id = 95, name = "SE_SHINY" },
}

-- Walk MusicPlayerInfo linked list
local function walkPlayers()
    local gs = r32(SOUND_INFO_PTR_ADDR)
    if gs < 0x03000000 or gs >= 0x03008000 then return nil end
    local list, cur = {}, r32(gs + O_SNDINFO_HEAD)
    while cur ~= 0 and #list < 16 do
        if cur < 0x03000000 or cur >= 0x03008000 then break end
        list[#list + 1] = cur
        cur = r32(cur + O_MPL_NEXT)
    end
    return list
end

-- Detect actual ROM size (CFRU/RR ROMs are 32MB; vanilla is 16MB).
local function detectRomEnd()
    local MAX_ROM = 0x0A000000  -- 32MB
    -- Probe at 16MB boundary: if data present, ROM is 32MB
    local probe_16 = 0x09000000 - 4
    local v = r32(probe_16)
    if v ~= 0x00000000 and v ~= 0xFFFFFFFF then
        -- Check 32MB boundary
        local probe_32 = MAX_ROM - 4
        local v2 = r32(probe_32)
        if v2 ~= 0x00000000 and v2 ~= 0xFFFFFFFF then
            return MAX_ROM
        end
        return 0x09000000
    end
    return 0x09000000
end

local function findSongTable(players)
    local ROM_START = 0x08000000
    local ROM_END   = detectRomEnd()
    local rom_mb    = (ROM_END - ROM_START) / (1024*1024)
    log(fmt("  ROM size for song scan: %.0fMB (end=%s)", rom_mb, hex(ROM_END)))

    -- Strategy A: from active song headers — search for the pointer value in ROM
    local known_hdrs = {}
    for _, addr in ipairs(players) do
        local hdr = r32(addr + O_MPL_SONG_HDR)
        if hdr >= 0x08000000 and hdr < 0x0A000000 then
            known_hdrs[#known_hdrs + 1] = hdr
        end
    end

    con(fmt("[DISCOVERY]   Scanning %.0fMB ROM for gSongTable (%d active headers)...",
            rom_mb, #known_hdrs))
    for _, target in ipairs(known_hdrs) do
        log(fmt("  Scanning for header pointer %s...", hex(target)))
        local last_mb = -1
        for addr = ROM_START, ROM_END - 4, 4 do
            local cur_mb = math.floor((addr - ROM_START) / (1024*1024))
            if cur_mb > last_mb then
                last_mb = cur_mb
                if cur_mb % 4 == 0 then
                    con(fmt("[DISCOVERY]   Song scan: %dMB / %.0fMB...", cur_mb, rom_mb))
                end
                emu.yield()
            end
            if r32(addr) == target then
                local ms = r16(addr + 4)
                if ms < 16 then
                    local start = addr
                    while start > ROM_START do
                        local ph = r32(start - SONG_ENTRY_SIZE)
                        local pm = r16(start - SONG_ENTRY_SIZE + 4)
                        if ph >= 0x08000000 and ph < 0x0A000000 and pm < 16 then
                            start = start - SONG_ENTRY_SIZE
                        else break end
                    end
                    local count, check = 0, start
                    while check < ROM_END do
                        local h = r32(check)
                        local m = r16(check + 4)
                        if h >= 0x08000000 and h < 0x0A000000 and m < 16 then
                            count = count + 1
                            check = check + SONG_ENTRY_SIZE
                        else break end
                    end
                    if count >= 50 then
                        return start, count
                    end
                end
            end
        end
    end

    -- Strategy B: structural scan — find longest run of valid song entries
    con("[DISCOVERY]   Strategy A failed, trying structural scan (Strategy B)...")
    log("  Strategy B: scanning for long run of valid song entries...")
    local best_addr, best_run = nil, 0
    local scan_addr = ROM_START
    local last_mb = -1
    while scan_addr < ROM_END - 400 do
        local cur_mb = math.floor((scan_addr - ROM_START) / (1024*1024))
        if cur_mb > last_mb then
            last_mb = cur_mb
            if cur_mb % 4 == 0 then
                con(fmt("[DISCOVERY]   Strategy B: %dMB / %.0fMB (best=%d)...",
                        cur_mb, rom_mb, best_run))
            end
            emu.yield()
        end
        local hdr = r32(scan_addr)
        if hdr >= 0x08000000 and hdr < 0x0A000000 then
            local ms = r16(scan_addr + 4)
            if ms < 16 then
                local run, check = 0, scan_addr
                while check < ROM_END do
                    local h = r32(check)
                    local m = r16(check + 4)
                    if h >= 0x08000000 and h < 0x0A000000 and m < 16 then
                        run = run + 1
                        check = check + SONG_ENTRY_SIZE
                    else break end
                end
                if run > best_run then
                    best_run = run
                    best_addr = scan_addr
                    if run >= 100 then break end  -- early exit
                end
                scan_addr = check + 8
            else
                scan_addr = scan_addr + 4
            end
        else
            scan_addr = scan_addr + 4
        end
    end
    if best_run >= 50 then
        log(fmt("  Strategy B: %d consecutive entries at %s", best_run, hex(best_addr)))
        return best_addr, best_run
    end

    return nil, 0
end

local players = walkPlayers()
if players and #players > 0 then
    log(fmt("  %d music players found", #players))
    local song_table, entry_count = findSongTable(players)
    if song_table then
        log(fmt("  ✓ gSongTable = %s  (%d entries)", hex(song_table), entry_count))
        RESULTS.song_table = song_table
        RESULTS.SE_SONG_HEADERS = {}
        for _, se in ipairs(TARGET_SES) do
            if se.id < entry_count then
                local entry = song_table + se.id * SONG_ENTRY_SIZE
                local hdr = r32(entry)
                log(fmt("    [%3d] %-12s hdr=%s", se.id, se.name, hex(hdr)))
                RESULTS.SE_SONG_HEADERS[se.id] = hdr
            end
        end
    else
        log("  ✗ gSongTable not found")
    end
else
    log("  ✗ No music players — BGM not playing?")
end

_flush()  -- save Phase 3 results
con("[DISCOVERY] Phase 3 complete.")

-- ══════════════════════════════════════════════════════════════════════════════
-- PHASE 4: SPECIES TABLE DISCOVERY
-- ══════════════════════════════════════════════════════════════════════════════
con("[DISCOVERY] Phase 4: Species table...")
con("[DISCOVERY]   Checking CFRU ROM pointer at 0x8000144...")

sep()
log("")
log("[PHASE 4] Species name table discovery...")
log("")

local species_table_addr = nil

-- gSpeciesNames is an array of FRLG-encoded strings in ROM.
-- CFRU accesses it via a pointer at ROM offset 0x144:
--   #define gSpeciesNames ((SpeciesNames_t*) *((u32*) 0x8000144))
-- This pointer indirection works for CFRU and RR (the pointer is set by the engine).

local SPECIES_NAME_SIZE = 11  -- POKEMON_NAME_LENGTH + 1 (CFRU default)

-- Strategy 1: Read the pointer at ROM+0x144 (CFRU method)
log("  Strategy A: ROM pointer at 0x08000144...")
local species_ptr = r32(0x08000144, "System Bus")
if species_ptr >= 0x08000000 and species_ptr < 0x0A000000 then
    log(fmt("    Pointer value: %s", hex(species_ptr)))
    local test_name = decodeStr(species_ptr + 1 * SPECIES_NAME_SIZE, 10)
    if test_name == "Bulbasaur" then
        species_table_addr = species_ptr
        log(fmt("  ✓ gSpeciesNames found via ROM pointer! stride=%d", SPECIES_NAME_SIZE))
        log(fmt("    Species 0 (NONE) @ %s", hex(species_ptr)))
        log(fmt("    Species 1 (Bulbasaur) @ %s", hex(species_ptr + SPECIES_NAME_SIZE)))
    else
        log(fmt("    Species 1 = \"%s\" — not Bulbasaur, trying stride detection...", test_name))
        -- Try different strides in case POKEMON_NAME_LENGTH changed
        for _, stride in ipairs({12, 13, 14, 16}) do
            local test2 = decodeStr(species_ptr + 1 * stride, 10)
            if test2 == "Bulbasaur" then
                SPECIES_NAME_SIZE = stride
                species_table_addr = species_ptr
                log(fmt("  ✓ gSpeciesNames found! stride=%d (non-standard)", stride))
                break
            end
        end
    end
else
    log(fmt("    Invalid pointer: %s — falling back to ROM scan", hex(species_ptr)))
end

-- Strategy 2: Brute-force ROM scan for "Bulbasaur" (fallback)
if not species_table_addr then
    log("  Strategy B: Scanning ROM for \"Bulbasaur\" in FRLG encoding...")
    con("[DISCOVERY]   Scanning ROM for species table (chunked)...")

    local BULBA_STR = string.char(0xBC, 0xE9, 0xE0, 0xD6, 0xD5, 0xE7, 0xD5, 0xE9, 0xE6, 0xFF)
    local SCAN_CHUNK = 4096
    for chunk_start = 0x08000000, 0x08400000 - 11, SCAN_CHUNK do
        local bytes = {}
        local chunk_end = math.min(chunk_start + SCAN_CHUNK - 1 + 10, 0x08400000 - 1)
        for i = chunk_start, chunk_end do
            bytes[#bytes + 1] = string.char(r8(i, "System Bus"))
        end
        local chunk_str = table.concat(bytes)
        local pos = chunk_str:find(BULBA_STR, 1, true)
        if pos then
            local addr = chunk_start + pos - 1
            local ivysaur_encoded = {0xC3, 0xEA, 0xED, 0xE7, 0xD5, 0xE9, 0xE6}
            local next_addr = addr + SPECIES_NAME_SIZE
            local next_match = true
            for i, expected in ipairs(ivysaur_encoded) do
                if r8(next_addr + i - 1, "System Bus") ~= expected then
                    next_match = false
                    break
                end
            end
            if next_match then
                local table_start = addr - SPECIES_NAME_SIZE
                species_table_addr = table_start
                log(fmt("  ✓ gSpeciesNames found via ROM scan! stride=%d", SPECIES_NAME_SIZE))
                log(fmt("    Species 0 (NONE) @ %s", hex(table_start)))
                log(fmt("    Species 1 (Bulbasaur) @ %s", hex(addr)))
                break
            end
        end
    end
end  -- if not species_table_addr

if species_table_addr then
    RESULTS.species_table_addr = species_table_addr
    RESULTS.species_name_stride = SPECIES_NAME_SIZE
    
    -- Count total species by walking until we hit invalid data
    local count = 0
    local max_scan = 2000  -- safety limit
    for i = 0, max_scan do
        local entry_addr = species_table_addr + i * SPECIES_NAME_SIZE
        local first_byte = r8(entry_addr, "System Bus")
        -- Valid FRLG character or 0xFF terminator at start means valid entry
        -- (species NONE might start with 0xAC "?" or similar)
        if first_byte == 0x00 and r8(entry_addr + 1, "System Bus") == 0x00 then
            -- All zeros = end of table
            count = i
            break
        end
        count = i + 1
    end
    
    log(fmt("  Total species entries: %d (IDs 0 to %d)", count, count - 1))
    RESULTS.species_count = count
    
    -- Validate CFRU extended species: check if species 1025 (Alolan Vulpix) is readable
    local is_extended = false
    if count > 500 then
        is_extended = true
        log("  ✓ Extended species table detected (CFRU)")
    else
        log(fmt("  ⚠ Only %d species found — this may be the vanilla FRLG table", count))
        log("    Checking for CFRU extended species beyond vanilla table...")
        -- Try reading species 1025 at the expected offset even if the count stopped early
        -- (CFRU tables may have gaps filled with 0x00 bytes between gen 3 and gen 4+)
        local test_ids = {440, 500, 808, 1000, 1025, 1200}
        for _, test_id in ipairs(test_ids) do
            local test_addr = species_table_addr + test_id * SPECIES_NAME_SIZE
            local test_name = decodeStr(test_addr, 10)
            if #test_name >= 3 and test_name:match("^%u%l") then
                log(fmt("    Species %d @ %s = \"%s\" — FOUND!", test_id, hex(test_addr), test_name))
                is_extended = true
            end
        end
        if is_extended then
            log("  ✓ CFRU extended table confirmed! Table continues beyond vanilla end.")
            log("    The count above is conservative (stops at first gap); actual table is larger.")
            -- Re-count more aggressively: walk to max 2000, only stop on 5+ consecutive zeros
            local real_count = count
            local consec_zeros = 0
            for i = count, max_scan do
                local entry_addr = species_table_addr + i * SPECIES_NAME_SIZE
                local first_byte = r8(entry_addr, "System Bus")
                if first_byte == 0x00 and r8(entry_addr + 1, "System Bus") == 0x00 then
                    consec_zeros = consec_zeros + 1
                    if consec_zeros >= 5 then
                        real_count = i - consec_zeros + 1
                        break
                    end
                else
                    consec_zeros = 0
                    real_count = i + 1
                end
            end
            if real_count > count then
                log(fmt("    Extended count: %d (IDs 0 to %d)", real_count, real_count - 1))
                RESULTS.species_count = real_count
                count = real_count
            end
        else
            log("    No extended species found — this is the vanilla table only.")
            log("    CFRU species names may be at a different ROM address or stride.")
        end
    end
    
    -- Dump sample entries
    log("")
    log("  Sample species names:")
    local samples = {0, 1, 2, 3, 4, 25, 150, 252, 277, 386, 387}
    -- Add CFRU-range samples only if extended
    if is_extended or count > 500 then
        for _, id in ipairs({440, 519, 808, 898, 1000, 1025, 1100, 1200, 1293}) do
            samples[#samples + 1] = id
        end
    end
    for _, id in ipairs(samples) do
        if id < count or is_extended then
            local name = decodeStr(species_table_addr + id * SPECIES_NAME_SIZE, 10)
            log(fmt("    [%4d] %s", id, name))
        end
    end
else
    log("  ✗ Species name table not found")
end

_flush()  -- save Phase 4 results
con("[DISCOVERY] Phase 4 complete.")

-- ══════════════════════════════════════════════════════════════════════════════
-- PHASE 5: BATTLE ADDRESSES (F1 hotkey — run during wild battle)
-- ══════════════════════════════════════════════════════════════════════════════
con("[DISCOVERY] Phase 5: Battle addresses — press F1 during a wild battle, F2 after.")
if BATTLE_OUT_PATH then
    con(fmt("[DISCOVERY] Battle results will go to: %s", BATTLE_OUT_PATH))
end

sep()
log("")
log("[PHASE 5] Battle-phase discovery — press F1 during a WILD battle")
log("          Press F2 after battle ends (back in overworld) to verify gBattleOutcome")
log("")

local battle_done = false

local function doBattleDiscovery()
    con("")
    con("══════ [F1] BATTLE PHASE DISCOVERY ══════")
    con("")
    
    -- Verify gMain inBattle state
    if RESULTS.GMAIN_ADDR then
        local flags = r8(RESULTS.GMAIN_ADDR + 0x439)
        local inBattle = (flags & 0x02) ~= 0
        con(fmt("  gMain+0x439 = 0x%02X → inBattle=%s", flags, tostring(inBattle)))
        if not inBattle then
            con("  WARNING: gMain says NOT in battle!")
        end
    end
    
    -- ── gBattleTypeFlags ────────────────────────────────────────────────────
    con("")
    con("  --- gBattleTypeFlags ---")
    local btf_candidates = {}
    
    for addr = 0x02020000, 0x0203F000, 4 do
        local val = r32(addr)
        if val ~= 0 and (val & 0x08) == 0 and val < 0x10000 then
            btf_candidates[#btf_candidates + 1] = {addr = addr, val = val}
        end
    end
    
    local btf_filtered = {}
    for _, c in ipairs(btf_candidates) do
        if c.addr >= 0x02020000 and c.addr <= 0x02030000 then
            btf_filtered[#btf_filtered + 1] = c
        end
    end
    
    con(fmt("  Found %d candidates (top 5):", #btf_filtered))
    for i = 1, math.min(5, #btf_filtered) do
        local c = btf_filtered[i]
        con(fmt("    %s = 0x%08X", hex(c.addr), c.val))
    end
    
    -- Check CFRU known address (vanilla: 0x02022B4C)
    local CFRU_BTF_ADDR = 0x02022B4C
    local cfru_btf_val = r32(CFRU_BTF_ADDR)
    con(fmt("  CFRU known addr (0x02022B4C) = 0x%08X", cfru_btf_val))
    if cfru_btf_val ~= 0 and cfru_btf_val < 0x10000 then
        local is_trainer = (cfru_btf_val & 0x08) ~= 0
        con(fmt("    trainer bit (0x08): %s → %s battle", tostring(is_trainer),
            is_trainer and "TRAINER" or "WILD"))
        RESULTS.BATTLE_TYPE_ADDR = CFRU_BTF_ADDR
    else
        con("    ⚠ Value looks invalid for gBattleTypeFlags")
    end
    
    -- ── gBattleOutcome snapshot ──────────────────────────────────────────────
    con("")
    con("  --- gBattleOutcome ---")
    con("  Snapshotting zeros for F2 comparison...")
    
    -- ── gBattleMons ─────────────────────────────────────────────────────────
    con("")
    con("  --- gBattleMons ---")
    
    local playerHP = 0
    if RESULTS.PARTY_BASE then
        playerHP = r16(RESULTS.PARTY_BASE + 0x56)
        con(fmt("  Player party slot 0 HP = %d", playerHP))
    end
    
    if playerHP > 0 then
        local bmon_candidates = {}
        for addr = 0x02020000, 0x0203F000, 4 do
            local hp_at_28 = r16(addr + 0x28)
            if hp_at_28 == playerHP then
                local species = r16(addr)
                if species > 0 and species < 2000 then
                    bmon_candidates[#bmon_candidates + 1] = {
                        addr = addr, species = species, hp = hp_at_28
                    }
                end
            end
        end
        
        con(fmt("  Found %d gBattleMons candidates (HP=%d at +0x28):", #bmon_candidates, playerHP))
        for i, c in ipairs(bmon_candidates) do
            con(fmt("    [%d] %s  species=%d  hp=%d", i, hex(c.addr), c.species, c.hp))
            local enemy_species = r16(c.addr + 0x58)
            local enemy_hp = r16(c.addr + 0x58 + 0x28)
            if enemy_species > 0 and enemy_species < 2000 and enemy_hp > 0 then
                con(fmt("      → Enemy at +0x58: species=%d hp=%d ← LIKELY gBattleMons!", enemy_species, enemy_hp))
                RESULTS.BATTLE_MONS_ADDR = c.addr
            end
        end
    end
    
    -- ── gEnemyParty ─────────────────────────────────────────────────────────
    con("")
    con("  --- gEnemyParty (wild: 1 mon) ---")
    
    local enemy_candidates = {}
    for addr = 0x02020000, 0x0203F000, 1 do
        local count = r8(addr)
        if count == 1 then
            for _, off in ipairs({1, 2, 4}) do
                local mon_addr = addr + off
                if mon_addr + PARTY_SIZE <= 0x02040000 then
                    local p = r32(mon_addr)
                    local mhp = r16(mon_addr + 0x58)
                    if p ~= 0 and mhp > 0 and mhp < 1000 then
                        local p2 = r32(mon_addr + PARTY_SIZE)
                        if p2 == 0 then
                            enemy_candidates[#enemy_candidates + 1] = {
                                countAddr = addr, partyAddr = mon_addr,
                                offset = off, personality = p, maxHP = mhp
                            }
                        end
                    end
                end
            end
        end
    end
    
    local seen = {}
    local enemy_unique = {}
    for _, c in ipairs(enemy_candidates) do
        if not seen[c.partyAddr] then
            seen[c.partyAddr] = true
            enemy_unique[#enemy_unique + 1] = c
        end
    end
    
    con(fmt("  Found %d enemy party candidates:", #enemy_unique))
    for i, c in ipairs(enemy_unique) do
        if i <= 5 then
            con(fmt("    [%d] count@%s  party@%s  pers=%s  maxHP=%d",
                i, hex(c.countAddr), hex(c.partyAddr), hex(c.personality), c.maxHP))
        end
    end
    
    if #enemy_unique > 0 then
        local best = enemy_unique[1]
        RESULTS.ENEMY_COUNT_ADDR = best.countAddr
        RESULTS.ENEMY_BASE = best.partyAddr
        con(fmt("  ✓ gEnemyPartyCount = %s", hex(best.countAddr)))
        con(fmt("  ✓ gEnemyParty = %s", hex(best.partyAddr)))
    end
    
    -- Snapshot ALL bytes for F2 comparison (not just zeros!)
    -- gBattleOutcome may have a stale non-zero value from a previous battle.
    -- By capturing every byte, F2 can detect any change (0→new OR stale→new).
    RESULTS._battle_snapshot = {}
    for addr = 0x02022000, 0x02026000, 1 do
        RESULTS._battle_snapshot[addr] = r8(addr)
    end
    
    battle_done = true
    con("")
    con("  ✓ Battle discovery complete! Now end the battle and press F2.")
end

-- F2: Post-battle outcome verification
local function doPostBattleVerify()
    con("")
    con("══════ [F2] POST-BATTLE VERIFICATION ══════")
    con("")
    
    if not RESULTS._battle_snapshot then
        con("  ERROR: Run F1 during battle first!")
        return
    end
    
    -- gMain should now show NOT in battle
    if RESULTS.GMAIN_ADDR then
        local flags = r8(RESULTS.GMAIN_ADDR + 0x439)
        local inBattle = (flags & 0x02) ~= 0
        con(fmt("  gMain+0x439 = 0x%02X → inBattle=%s", flags, tostring(inBattle)))
    end
    
    -- Find bytes that CHANGED to a valid battle outcome value (1–7).
    -- We snapshot ALL bytes in F1, so this catches both:
    --   • 0 → outcome  (properly zeroed at battle start)
    --   • stale → outcome  (gBattleOutcome kept old value from previous battle)
    local OUTCOME_NAMES = {[1]="WON", [2]="LOST", [3]="DREW", [4]="RAN",
                           [5]="TELEPORTED", [6]="MON_FLED", [7]="CAUGHT"}
    local outcome_candidates = {}
    for addr, old_val in pairs(RESULTS._battle_snapshot) do
        local new_val = r8(addr)
        if new_val ~= old_val and new_val >= 1 and new_val <= 7 then
            local score = 0
            -- Proximity to gBattleMons is a signal, BUT addresses INSIDE the
            -- gBattleMons array are almost certainly struct fields, not gBattleOutcome.
            -- gBattleMons is 4 battlers × 0x58 bytes = 0x160 bytes total.
            if RESULTS.BATTLE_MONS_ADDR then
                local dist = math.abs(addr - RESULTS.BATTLE_MONS_ADDR)
                local bmons_size = 4 * 0x58  -- 0x160
                if addr >= RESULTS.BATTLE_MONS_ADDR and addr < RESULTS.BATTLE_MONS_ADDR + bmons_size then
                    -- INSIDE gBattleMons struct — very unlikely to be gBattleOutcome
                    score = score - 10
                elseif dist <= 16 then
                    -- Just before gBattleMons — also suspicious (struct padding)
                    score = score - 5
                elseif dist > bmons_size and dist <= bmons_size + 256 then
                    -- Just after gBattleMons array — good candidate range
                    score = score + 15
                elseif dist > bmons_size and dist <= bmons_size + 1024 then
                    score = score + 10
                elseif dist <= 2048 then
                    score = score + 5
                end
            end
            -- Bonus: was zero during battle (properly initialized)
            if old_val == 0 then score = score + 3 end
            -- Bonus: WON/RAN/CAUGHT are the most common real outcomes
            if new_val == 1 or new_val == 4 or new_val == 7 then score = score + 2 end
            outcome_candidates[#outcome_candidates + 1] = {
                addr = addr, old = old_val, new = new_val, score = score
            }
        end
    end

    -- Sort by score DESC, then by address ASC (deterministic tiebreak)
    table.sort(outcome_candidates, function(a, b)
        if a.score ~= b.score then return a.score > b.score end
        return a.addr < b.addr
    end)

    con(fmt("  Found %d outcome candidates:", #outcome_candidates))
    for i, c in ipairs(outcome_candidates) do
        if i <= 12 then
            local outcome_name = OUTCOME_NAMES[c.new] or "?"
            local dist_str = ""
            if RESULTS.BATTLE_MONS_ADDR then
                dist_str = fmt("  dist=%d", math.abs(c.addr - RESULTS.BATTLE_MONS_ADDR))
            end
            local old_str = c.old == 0 and "0" or fmt("%d(stale)", c.old)
            con(fmt("    %s: %s → %d (%s) score=%d%s", hex(c.addr), old_str, c.new, outcome_name, c.score, dist_str))
        end
    end
    
    if #outcome_candidates > 0 then
        RESULTS.BATTLE_OUTCOME_ADDR = outcome_candidates[1].addr
        con(fmt("  ✓ gBattleOutcome = %s (score=%d)", hex(outcome_candidates[1].addr), outcome_candidates[1].score))
        if #outcome_candidates > 1 and outcome_candidates[2].score == outcome_candidates[1].score then
            con(fmt("  ⚠ TIED with %s — run another battle to confirm", hex(outcome_candidates[2].addr)))
        end
    end
    con("")
    con("══════ F2 DONE ══════")
end

-- Register F-key handlers via frame callback (BizHawk doesn't have event.onkeysup)
local _prev_keys = {}
event.unregisterbyname("rr_discovery_keys")
event.onframeend(function()
    local keys = input.get()
    -- Detect key press (rising edge, same as client.lua)
    if keys["F1"] and not _prev_keys["F1"] then
        con("[DISCOVERY] F1 pressed — running battle discovery...")
        doBattleDiscovery()
    end
    if keys["F2"] and not _prev_keys["F2"] then
        con("[DISCOVERY] F2 pressed — running post-battle verify...")
        doPostBattleVerify()
    end
    _prev_keys = keys
end, "rr_discovery_keys")

-- ══════════════════════════════════════════════════════════════════════════════
-- FINAL OUTPUT: PROFILES BLOCK
-- ══════════════════════════════════════════════════════════════════════════════

sep()
log("")
log("[OUTPUT] Copy-paste PROFILES block for memory.lua:")
log("")
log("  radical_red = {")
log("      PARTY_IN_SB1               = true,")
log("      SB1_PARTY_COUNT_OFFSET     = 0x0034,")
log("      SB1_PARTY_BASE_OFFSET      = 0x0038,")
log("      PARTY_COUNT_ADDR           = 0,        -- set by refreshPartyAddrs()")
log("      PARTY_BASE                 = 0,        -- set by refreshPartyAddrs()")
if RESULTS.ENEMY_COUNT_ADDR then
    log(fmt("      ENEMY_COUNT_ADDR           = %s,", hex(RESULTS.ENEMY_COUNT_ADDR)))
end
if RESULTS.ENEMY_BASE then
    log(fmt("      ENEMY_BASE                 = %s,", hex(RESULTS.ENEMY_BASE)))
end
if RESULTS.BATTLE_TYPE_ADDR then
    log(fmt("      BATTLE_TYPE_ADDR           = %s,  -- CFRU vanilla addr confirmed", hex(RESULTS.BATTLE_TYPE_ADDR)))
else
    log("      BATTLE_TYPE_ADDR           = nil,       -- not yet discovered for RR")
end
if RESULTS.BATTLE_OUTCOME_ADDR then
    log(fmt("      BATTLE_OUTCOME_ADDR        = %s,", hex(RESULTS.BATTLE_OUTCOME_ADDR)))
end
if RESULTS.BATTLE_MONS_ADDR then
    log(fmt("      BATTLE_MONS_ADDR           = %s,", hex(RESULTS.BATTLE_MONS_ADDR)))
end
log("      BATTLER_PARTY_INDEXES_ADDR = nil,")
log("      BATTLERS_COUNT_ADDR        = nil,")
log("      BATTLE_MAIN_FUNC_ADDR      = nil,")
log("      RETURN_FROM_BATTLE_ADDR    = nil,")
log("      GMAIN_ADDR                 = nil,       -- unreliable for RR (inBattle bit never flips)")
if RESULTS.SB1_PTR_ADDR then
    log(fmt("      SB1_PTR_ADDR               = %s,", hex(RESULTS.SB1_PTR_ADDR)))
end
if RESULTS.SB2_PTR_ADDR then
    log(fmt("      SB2_PTR_ADDR               = %s,", hex(RESULTS.SB2_PTR_ADDR)))
else
    log("      SB2_PTR_ADDR               = nil,       -- not confirmed; re-run discovery")
end
if RESULTS.PSP_PTR_ADDR then
    log(fmt("      PSP_PTR_ADDR               = %s,", hex(RESULTS.PSP_PTR_ADDR)))
else
    log("      PSP_PTR_ADDR               = nil,       -- not confirmed; re-run discovery")
end
log(fmt("      SB2_ENC_KEY_OFFSET         = 0x0F20,"))
log(fmt("      SB1_FLAGS_OFFSET           = 0x0EE0,"))
if RESULTS.BALL_POCKET_ADDR then
    log(fmt("      -- Ball pocket in EWRAM (not SB1):"))
    log(fmt("      BAG_IN_EWRAM               = true,"))
    log(fmt("      BALL_POCKET_ADDR           = %s,", hex(RESULTS.BALL_POCKET_ADDR)))
    log(fmt("      BALL_POCKET_ENC            = false,"))
    log(fmt("      SB1_BALL_POCKET_COUNT      = 50,"))
end
if RESULTS.BOXES_PER_STORE then
    log(fmt("      BOXES_PER_STORE            = %d,", RESULTS.BOXES_PER_STORE))
end
if RESULTS.BOX_NAMES_OFFSET then
    log(fmt("      BOX_NAMES_OFFSET           = 0x%04X,", RESULTS.BOX_NAMES_OFFSET))
end
log(fmt("      OVERWORLD_MODE             = \"battle_outcome\",  -- gMain unreliable for RR"))
log(fmt("      OUTCOME_CAUGHT             = 7,  -- CFRU: B_OUTCOME_CAUGHT = 7 (vanilla = 6)"))
if RESULTS.SE_SONG_HEADERS then
    log("      SE_SONG_HEADERS = {")
    for _, se in ipairs(TARGET_SES) do
        if RESULTS.SE_SONG_HEADERS[se.id] then
            log(fmt("          [%3d] = %s,  -- %s", se.id, hex(RESULTS.SE_SONG_HEADERS[se.id]), se.name))
        end
    end
    log("      },")
end
log("  }")

log("")
sep()
log("")
log("  ADDITIONAL INFO:")
if RESULTS.species_count then
    log(fmt("  Species count: %d (max ID = %d)", RESULTS.species_count, RESULTS.species_count - 1))
    log(fmt("  Species table ROM addr: %s (stride=%d bytes)",
        hex(RESULTS.species_table_addr), RESULTS.species_name_stride))
end
log("")
log("  INSTRUCTIONS:")
log("  1. Enter a wild battle and press F1 for battle-phase discovery")
log("  2. End the battle (win/catch/run) and press F2 to verify gBattleOutcome")
log("  3. F1/F2 results go to a SEPARATE file: rr_discovery_battle.txt")
log("     (this file won't be overwritten if you rerun the main script)")
log("  4. Copy the PROFILES block into lua/memory_gba.lua")
log("  5. Fill in any missing addresses marked with ??? or from F1/F2 results")
log("")
div()
log("  Discovery complete! (overworld phase)")
div()

-- Flush everything to the output file
_flush()
con("")
if _file_ok then
    con(fmt("[DISCOVERY] Results written to: %s", OUT_PATH))
    con("  → Open this file to see the full output (not truncated).")
else
    con("[DISCOVERY] !! FILE OUTPUT FAILED — results are only in this console.")
    con("  → To fix: edit test_rr_discovery.lua and set OUT_PATH manually, e.g.:")
    con('    OUT_PATH = "C:\\\\Users\\\\YourName\\\\Desktop\\\\rr_discovery_results.txt"')
    con("  → Or copy/paste from this console (some lines may be truncated).")
end
con("  → Press F1 during a wild battle, then F2 after, for battle addresses.")
if BATTLE_OUT_PATH then
    con(fmt("  → Battle results will go to: %s", BATTLE_OUT_PATH))
end
con("")
con("════════════════════════════════════════════════")
con("  DISCOVERY COMPLETE — check the output file!  ")
con("════════════════════════════════════════════════")
