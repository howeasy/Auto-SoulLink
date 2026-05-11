--[[
  lua/test_map_names.lua — ROM Map Name Extractor
  =================================================
  One-time BizHawk discovery script. Reads in-game map names directly from
  ROM data tables for ANY FRLG-based ROM (vanilla, Archipelago, Radical Red).

  HOW TO USE:
    1. Load any FRLG/RR ROM in BizHawk (a save must be loaded — title screen
       is NOT enough, because SaveBlock pointers are needed for validation).
    2. Open the Lua Console and load this script.
    3. Wait for it to complete (may take 1–3 minutes for full ROM scan).
    4. Results are written to  lua/map_names_results.txt
    5. Run companion script:  python tools/parse_map_names.py

  APPROACH:
    Phase 1: Find anchor strings ("PALLET TOWN", "VIRIDIAN CITY", "ROUTE 1")
             in ROM by scanning for their GBA-encoded byte sequences.
    Phase 2: Find sRegionMapSectionNameTable by locating ROM pointers to those
             strings and validating they index into the same pointer array.
    Phase 3: Dump ALL mapsec names from the table (complete reference).
    Phase 4: Find gMapGroups by locating MapHeader structs (via mapsec cross-
             reference) and tracing the pointer chain backwards.
    Phase 5: Walk every known mapGroup:mapNum, read MapHeader+0x14 to get
             regionMapSectionId, decode the in-game name from the string table.

  OUTPUT FORMAT (in results file):
    Human-readable report followed by a JSON block delimited by
    ===JSON_START=== / ===JSON_END=== markers for machine parsing.
--]]

-- ── ROM read helpers (always "System Bus" domain) ──────────────────────────
local function rom_r8(addr)   return memory.read_u8(addr, "System Bus")       end
local function rom_r16(addr)  return memory.read_u16_le(addr, "System Bus")   end
local function rom_r32(addr)  return memory.read_u32_le(addr, "System Bus")   end

local fmt = string.format

-- ── Constants ──────────────────────────────────────────────────────────────
local ROM_BASE = 0x08000000
local ROM_MAX  = 0x02000000   -- scan up to 32MB

-- MapHeader struct layout (28 = 0x1C bytes):
--   +0x00  mapLayout*       (ROM pointer)
--   +0x04  events*          (ROM pointer)
--   +0x08  mapScripts*      (ROM pointer)
--   +0x0C  connections*     (ROM pointer or NULL)
--   +0x10  music            (u16)
--   +0x12  mapLayoutId      (u16)
--   +0x14  regionMapSectionId (u8)  ← THIS IS WHAT WE NEED
--   +0x15  cave             (u8, 0 or 1 or 2)
--   +0x16  weather          (u8)
--   +0x17  mapType          (u8)
--   +0x18  ...padding / flags
local MAP_HEADER_SIZE        = 0x1C
local MAPSEC_OFFSET          = 0x14

-- Vanilla FRLG map group sizes (from pret/pokefirered data/maps/map_groups.json).
-- Used for REFERENCE/COMPARISON only — iteration is fully dynamic.
local VANILLA_GROUP_SIZES = {
    [0]=5, [1]=123, [2]=60, [3]=66, [4]=4, [5]=6, [6]=8, [7]=10,
    [8]=6, [9]=8, [10]=20, [11]=10, [12]=8, [13]=2, [14]=10, [15]=4,
    [16]=2, [17]=2, [18]=2, [19]=1, [20]=1, [21]=2, [22]=2, [23]=3,
    [24]=2, [25]=3, [26]=2, [27]=1, [28]=1, [29]=1, [30]=1, [31]=7,
    [32]=5, [33]=5, [34]=8, [35]=8, [36]=5, [37]=5, [38]=1, [39]=1,
    [40]=1, [41]=2, [42]=1,
}
local VANILLA_NUM_GROUPS = 43   -- vanilla has groups 0–42

-- ── GBA text encoding ──────────────────────────────────────────────────────
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
    [0x34]="'",  -- apostrophe (used in some FRLG strings like "DIGLETT'S CAVE")
    [0xB4]="'",  -- alternative apostrophe encoding
    [0x1B]=",",  -- comma
    [0xB0]="+",  -- plus sign
    [0xB1]="=",  -- equals sign
    [0x35]="♂",  -- male symbol (FRLG encoding)
    [0x36]="♀",  -- female symbol (FRLG encoding)
}

local CHARSET_REV = {}
for byte, char in pairs(CHARSET) do CHARSET_REV[char] = byte end

local function decodeRomString(addr, max_len)
    max_len = max_len or 32
    local chars = {}
    for i = 0, max_len - 1 do
        local b = rom_r8(addr + i)
        if b == 0xFF then break end
        chars[#chars + 1] = CHARSET[b] or fmt("{%02X}", b)
    end
    return (table.concat(chars):gsub("%s+$", ""))
end

-- Encode ASCII string → GBA byte array (WITH 0xFF terminator)
local function encodeString(str)
    local bytes = {}
    for i = 1, #str do
        local c = str:sub(i, i)
        bytes[#bytes + 1] = CHARSET_REV[c] or 0xAC
    end
    bytes[#bytes + 1] = 0xFF
    return bytes
end

-- ── Pointer validation ─────────────────────────────────────────────────────
local function isRomPtr(val)
    return val >= 0x08000000 and val < 0x0A000000
end

-- ── OUTPUT FILE SETUP ──────────────────────────────────────────────────────
local _out_lines = {}
local OUT_PATH = nil

local function _try_path(path)
    local ok, f = pcall(io.open, path, "w")
    if ok and f then f:write(""); f:close(); return true end
    return false
end

-- Resolve output path (same strategy as test_rr_discovery.lua)
do
    local candidates = {}
    local ok, info = pcall(debug.getinfo, 1, "S")
    if ok and info and info.source then
        local dir = info.source:match("^@?(.*[\\/])")
        if dir then
            candidates[#candidates + 1] = dir .. "map_names_results.txt"
        end
    end
    local rom_path = gameinfo and gameinfo.getromname and gameinfo.getromname() or nil
    if rom_path then
        local dir = rom_path:match("^(.*[\\/])") or ""
        if dir ~= "" then
            candidates[#candidates + 1] = dir .. "map_names_results.txt"
        end
    end
    candidates[#candidates + 1] = "lua/map_names_results.txt"
    candidates[#candidates + 1] = "map_names_results.txt"

    for _, p in ipairs(candidates) do
        if _try_path(p) then OUT_PATH = p; break end
    end
end

local function log(s) _out_lines[#_out_lines + 1] = s end
local function con(s) console.log(s) end

local function flush()
    if not OUT_PATH then
        con("!! No writable output path found. Results in console only.")
        for _, line in ipairs(_out_lines) do con(line) end
        return
    end
    local ok, f = pcall(io.open, OUT_PATH, "w")
    if ok and f then
        f:write(table.concat(_out_lines, "\n") .. "\n")
        f:close()
    end
end

local function div() log("══════════════════════════════════════════════════════════════════") end
local function sep() log("──────────────────────────────────────────────────────────────────") end

-- ── ROM size detection ─────────────────────────────────────────────────────
-- Read u32 at candidate boundary; if all-zero for several consecutive reads,
-- we've gone past the actual ROM.
local ROM_SIZE = ROM_MAX
do
    -- Test at 16MB boundary (typical FRLG size)
    local function check_zeroes(base, count)
        for i = 0, count - 1 do
            local ok, val = pcall(rom_r32, base + i * 4)
            if not ok or val ~= 0 then return false end
        end
        return true
    end
    -- Try progressively: 16MB, 24MB, 32MB
    for _, sz in ipairs({0x01000000, 0x01800000, 0x02000000}) do
        if check_zeroes(ROM_BASE + sz, 64) then
            ROM_SIZE = sz
            break
        end
    end
end

con(fmt("ROM size detected: %dMB (%d bytes)", ROM_SIZE / 0x100000, ROM_SIZE))

-- ══════════════════════════════════════════════════════════════════════════
-- PHASE 0: Diagnostics — verify ROM is readable
-- ══════════════════════════════════════════════════════════════════════════
div()
log("PHASE 0: ROM Read Diagnostics")
sep()

-- 0a. Read game code from ROM header (0x080000AC, 4 bytes)
local game_code = ""
for i = 0, 3 do
    local ok, b = pcall(rom_r8, 0x080000AC + i)
    if ok then game_code = game_code .. string.char(b) end
end
log(fmt("  Game code: \"%s\"", game_code))
con(fmt("  Game code: %s", game_code))

-- 0b. Log ROM size to file too
log(fmt("  ROM size: %dMB (0x%X bytes)", ROM_SIZE / 0x100000, ROM_SIZE))

-- 0c. Read ROM title from header (0x080000A0, 12 bytes)
local rom_title = ""
for i = 0, 11 do
    local ok, b = pcall(rom_r8, 0x080000A0 + i)
    if ok and b > 0 then rom_title = rom_title .. string.char(b) end
end
log(fmt("  ROM title: \"%s\"", rom_title))

-- 0d. Sample raw bytes at 1MB intervals to verify ROM is populated
log("  ROM samples (first byte at each MB):")
local zero_mbs = 0
for mb = 0, math.min(31, ROM_SIZE / 0x100000 - 1) do
    local addr = ROM_BASE + mb * 0x100000
    local ok, b = pcall(rom_r8, addr)
    if ok then
        log(fmt("    ROM[%2dMB] (0x%08X) = 0x%02X", mb, addr, b))
        if b == 0 then zero_mbs = zero_mbs + 1 end
    else
        log(fmt("    ROM[%2dMB] (0x%08X) = READ ERROR", mb, addr))
    end
end
if zero_mbs > ROM_SIZE / 0x100000 / 2 then
    log("  ⚠ WARNING: Most ROM MB boundaries read as 0x00 — ROM may not be loaded!")
end

-- 0e. Hex dump first 32 bytes of ROM
local hex_row = {}
for i = 0, 31 do
    local ok, b = pcall(rom_r8, ROM_BASE + i)
    hex_row[#hex_row + 1] = ok and fmt("%02X", b) or "??"
end
log(fmt("  ROM[0x08000000..+31]: %s", table.concat(hex_row, " ")))

-- 0f. Test encoding: show what "PALLET TOWN" encodes to
local test_enc = encodeString("PALLET TOWN")
local enc_hex = {}
for _, b in ipairs(test_enc) do enc_hex[#enc_hex + 1] = fmt("%02X", b) end
log(fmt("  \"PALLET TOWN\" encodes to: {%s}", table.concat(enc_hex, ", ")))

-- 0g. Spot-check: manually search for byte 0xCA ('P') in first 64KB
local p_count = 0
for addr = ROM_BASE, ROM_BASE + 0x10000 - 1 do
    local ok, b = pcall(rom_r8, addr)
    if ok and b == 0xCA then p_count = p_count + 1 end
end
log(fmt("  Byte 0xCA ('P' in GBA) found %d times in first 64KB", p_count))

-- 0h. Also check for ASCII 'P' (0x50) — in case CFRU uses ASCII strings
local ascii_p_count = 0
for addr = ROM_BASE, ROM_BASE + 0x10000 - 1 do
    local ok, b = pcall(rom_r8, addr)
    if ok and b == 0x50 then ascii_p_count = ascii_p_count + 1 end
end
log(fmt("  Byte 0x50 ('P' in ASCII) found %d times in first 64KB", ascii_p_count))

-- 0i. Test reading with NO domain specified (default) vs "System Bus"
local test_addr = ROM_BASE + 0x100
local sb_val = memory.read_u8(test_addr, "System Bus")
local def_val = memory.read_u8(test_addr)
log(fmt("  ROM[0x%08X]: System Bus=0x%02X, default=0x%02X, match=%s",
        test_addr, sb_val, def_val, sb_val == def_val and "yes" or "NO"))

-- 0j. Try reading with "ROM" domain (0-based addresses)
local rom_domain_ok = false
do
    local ok, val = pcall(memory.read_u8, 0x100, "ROM")
    if ok then
        log(fmt("  ROM domain read(0x100) = 0x%02X (SystemBus equivalent=0x%02X, match=%s)",
                val, sb_val, val == sb_val and "yes" or "NO"))
        rom_domain_ok = true
    else
        log("  ROM domain: not available")
    end
end

-- 0k. List available memory domains
local domains_str = "unknown"
do
    local ok, domains = pcall(memory.getmemorydomainlist or function() return nil end)
    if ok and domains then
        domains_str = table.concat(domains, ", ")
    end
end
log(fmt("  Memory domains: %s", domains_str))

con("Phase 0 diagnostics complete.")
flush()  -- write diagnostics immediately in case Phase 1 hangs

-- ══════════════════════════════════════════════════════════════════════════
-- PHASE 1: Find anchor strings in ROM
-- ══════════════════════════════════════════════════════════════════════════
div()
log("PHASE 1: Finding anchor strings in ROM")
sep()

-- ── Phase 1a: Quick probe — search for SHORT patterns in all casings ────
-- We test 4 encodings × casings to determine what format the ROM uses.
-- This scans for 5-6 byte patterns, much faster than full-string search.

local PROBES = {}  -- { name, bytes }

-- Helper: encode a short string in GBA encoding
local function gba_encode_short(str)
    local b = {}
    for i = 1, #str do
        local c = str:sub(i, i)
        b[#b + 1] = CHARSET_REV[c]
        if not CHARSET_REV[c] then return nil end  -- char not in charset
    end
    return b
end

-- Helper: encode a short string in ASCII
local function ascii_encode_short(str)
    local b = {}
    for i = 1, #str do b[#b + 1] = str:byte(i) end
    return b
end

-- Add probe patterns for both casings and both encodings
local probe_words = {
    {"ROUTE", "Route", "route"},
    {"PALLET", "Pallet", "pallet"},
    {"VIRIDIAN", "Viridian", "viridian"},
    {"CERULEAN", "Cerulean", "cerulean"},
}

for _, variants in ipairs(probe_words) do
    for _, word in ipairs(variants) do
        local gba = gba_encode_short(word)
        if gba then
            PROBES[#PROBES + 1] = { name = fmt("GBA \"%s\"", word), bytes = gba }
        end
        local asc = ascii_encode_short(word)
        PROBES[#PROBES + 1] = { name = fmt("ASCII \"%s\"", word), bytes = asc }
    end
end

-- Initialize hit counts
for _, p in ipairs(PROBES) do p.hits = 0; p.first_addr = nil end

log(fmt("  Probing %d patterns (GBA+ASCII × upper+title+lower)...", #PROBES))
local enc_hex = {}
for _, p in ipairs(PROBES) do
    enc_hex = {}
    for _, b in ipairs(p.bytes) do enc_hex[#enc_hex + 1] = fmt("%02X", b) end
    log(fmt("    %s = {%s}", p.name, table.concat(enc_hex, " ")))
end
con("Phase 1a: Probing for short patterns across ROM...")

for addr = ROM_BASE, ROM_BASE + ROM_SIZE - 20 do
    local b = rom_r8(addr)
    for _, p in ipairs(PROBES) do
        if b == p.bytes[1] then
            local match = true
            for j = 2, #p.bytes do
                if rom_r8(addr + j - 1) ~= p.bytes[j] then
                    match = false
                    break
                end
            end
            if match then
                p.hits = p.hits + 1
                if not p.first_addr then p.first_addr = addr end
            end
        end
    end

    if (addr - ROM_BASE) % 0x100000 == 0 then
        local mb = (addr - ROM_BASE) / 0x100000
        con(fmt("  Phase 1a: %dMB / %dMB scanned...", mb, ROM_SIZE / 0x100000))
        emu.yield()
    end
end

-- Report probe results
log("")
log("  Probe results:")
local any_found = false
local best_encoding = nil  -- "gba" or "ascii"
local best_casing = nil    -- "upper", "title", or "lower"

for _, p in ipairs(PROBES) do
    if p.hits > 0 then
        log(fmt("  ✓ %-25s — %d hits (first at 0x%08X)", p.name, p.hits, p.first_addr))
        any_found = true
        -- Determine encoding and casing from the pattern name
        if p.name:find("^GBA") then
            best_encoding = best_encoding or "gba"
        elseif p.name:find("^ASCII") then
            best_encoding = best_encoding or "ascii"
        end
    else
        log(fmt("  ✗ %-25s — not found", p.name))
    end
end

flush()

if not any_found then
    -- ── Phase 1b: Emergency diagnostics — dump raw bytes at key offsets ────
    log("")
    log("  ⚠ NO patterns found in any encoding. Running emergency diagnostics...")
    log("")

    -- Dump 64 raw bytes at several offsets to see what's actually in the ROM
    local sample_offsets = {
        0x00000000,  -- ROM start
        0x003F0000,  -- typical vanilla data region (~4MB)
        0x003FC000,  -- vanilla sMapNames vicinity
        0x00400000,  -- 4MB boundary
        0x00500000,  -- 5MB
        0x00600000,  -- 6MB
        0x00700000,  -- 7MB
        0x01000000,  -- 16MB (CFRU extended region start)
        0x01100000,  -- 17MB
    }

    for _, off in ipairs(sample_offsets) do
        local hex_row = {}
        local char_row = {}
        local addr = ROM_BASE + off
        for i = 0, 31 do
            local ok, byte = pcall(rom_r8, addr + i)
            if ok then
                hex_row[#hex_row + 1] = fmt("%02X", byte)
                -- Show as GBA char if printable, else as ASCII char if printable, else dot
                if CHARSET[byte] and CHARSET[byte] ~= " " then
                    char_row[#char_row + 1] = CHARSET[byte]
                elseif byte >= 32 and byte <= 126 then
                    char_row[#char_row + 1] = string.char(byte)
                else
                    char_row[#char_row + 1] = "."
                end
            else
                hex_row[#hex_row + 1] = "??"
                char_row[#char_row + 1] = "?"
            end
        end
        log(fmt("  ROM[+0x%07X]: %s  |%s|", off, table.concat(hex_row, " "), table.concat(char_row)))
    end

    -- Also try scanning for ANY GBA-terminated string (0xFF) preceded by valid chars
    -- Look for sequences of 5+ valid GBA chars followed by 0xFF
    log("")
    log("  Searching for GBA-terminated strings (5+ valid chars then 0xFF)...")
    local valid_string_count = 0
    local sample_strings = {}
    for addr = ROM_BASE, ROM_BASE + math.min(ROM_SIZE, 0x00800000) - 1 do  -- first 8MB only
        if rom_r8(addr) == 0xFF then  -- potential string terminator
            -- Look backwards for valid GBA chars
            local len = 0
            for k = 1, 30 do
                local prev = rom_r8(addr - k)
                if CHARSET[prev] then
                    len = len + 1
                else
                    break
                end
            end
            if len >= 5 then
                valid_string_count = valid_string_count + 1
                if #sample_strings < 20 then
                    local str_addr = addr - len
                    sample_strings[#sample_strings + 1] = {
                        addr = str_addr,
                        text = decodeRomString(str_addr, len + 1)
                    }
                end
            end
        end
        if (addr - ROM_BASE) % 0x100000 == 0 then emu.yield() end
    end

    log(fmt("  Found %d GBA-terminated strings (5+ chars) in first 8MB", valid_string_count))
    for _, s in ipairs(sample_strings) do
        log(fmt("    0x%08X: \"%s\"", s.addr, s.text))
    end

    log("")
    log("FATAL: Cannot determine string encoding. See diagnostics above.")
    flush()
    con("FATAL: No known string patterns found. Check results file.")
    return
end

-- ── Phase 1c: Full anchor search using detected encoding/casing ────
log("")
log(fmt("  Detected encoding: %s", best_encoding or "unknown"))

-- Which encoding to decode strings with
local STRING_MODE = best_encoding or "gba"

local function decodeByMode(addr, max_len)
    max_len = max_len or 32
    if STRING_MODE == "ascii" then
        local chars = {}
        for i = 0, max_len - 1 do
            local b = rom_r8(addr + i)
            if b == 0 then break end
            if b >= 32 and b <= 126 then
                chars[#chars + 1] = string.char(b)
            else
                chars[#chars + 1] = fmt("{%02X}", b)
            end
        end
        return table.concat(chars):gsub("%s+$", "")
    else
        return decodeRomString(addr, max_len)
    end
end

-- If probes found hits, dump the strings at those addresses for confirmation
log("  Sample strings at probe hit addresses:")
for _, p in ipairs(PROBES) do
    if p.first_addr then
        -- Read 30 chars from that address
        local str = decodeByMode(p.first_addr, 30)
        log(fmt("    0x%08X: \"%s\" (matched %s)", p.first_addr, str, p.name))
    end
end

-- Now find the full anchor strings using the working encoding
-- Build anchor patterns using detected casing
local ANCHORS_UPPER = {
    "PALLET TOWN", "VIRIDIAN CITY", "ROUTE 1", "MT. MOON", "CERULEAN CITY"
}
local ANCHORS_TITLE = {
    "Pallet Town", "Viridian City", "Route 1", "Mt. Moon", "Cerulean City"
}
local ANCHORS_LOWER = {
    "pallet town", "viridian city", "route 1", "mt. moon", "cerulean city"
}

-- Determine casing from probe hits
local best_casing_set = nil
for _, p in ipairs(PROBES) do
    if p.hits > 0 then
        local pname = p.name
        -- Check if the matched word was upper, title, or lower case
        local word = pname:match('"(%u%u+)"')  -- all uppercase
        if word then
            best_casing_set = best_casing_set or ANCHORS_UPPER
        else
            word = pname:match('"(%u%l+)"')  -- title case
            if word then
                best_casing_set = best_casing_set or ANCHORS_TITLE
            else
                word = pname:match('"(%l+)"')  -- lowercase
                if word then
                    best_casing_set = best_casing_set or ANCHORS_LOWER
                end
            end
        end
        if best_casing_set then break end
    end
end

-- Try detected casing first, then fall back to others
local casing_order = {ANCHORS_UPPER, ANCHORS_TITLE, ANCHORS_LOWER}
if best_casing_set then
    -- Put the detected casing first
    casing_order = {best_casing_set}
    for _, set in ipairs({ANCHORS_UPPER, ANCHORS_TITLE, ANCHORS_LOWER}) do
        if set ~= best_casing_set then
            casing_order[#casing_order + 1] = set
        end
    end
end

-- Try all casings to find which works
local ANCHORS = {}
local anchor_ok = false

for _, anchor_set in ipairs(casing_order) do
    ANCHORS = {}
    for _, name in ipairs(anchor_set) do
        local entry = { name = name, rom_addrs = {} }
        if STRING_MODE == "gba" then
            entry.encoded = encodeString(name)
        else
            local bytes = {}
            for i = 1, #name do bytes[#bytes + 1] = name:byte(i) end
            bytes[#bytes + 1] = 0x00  -- null terminator for ASCII
            entry.encoded = bytes
        end
        ANCHORS[#ANCHORS + 1] = entry
    end

    -- Search for each anchor at the probe hit addresses' vicinity first,
    -- then fall back to full scan if needed
    log(fmt("  Trying casing: \"%s\" ...", anchor_set[1]))

    -- Full scan for these anchors
    for addr = ROM_BASE, ROM_BASE + ROM_SIZE - 20 do
        local b = rom_r8(addr)
        for _, a in ipairs(ANCHORS) do
            if b == a.encoded[1] then
                local match = true
                for j = 2, #a.encoded do
                    if rom_r8(addr + j - 1) ~= a.encoded[j] then
                        match = false
                        break
                    end
                end
                if match then
                    a.rom_addrs[#a.rom_addrs + 1] = addr
                end
            end
        end
        if (addr - ROM_BASE) % 0x100000 == 0 then
            local mb = (addr - ROM_BASE) / 0x100000
            con(fmt("  Phase 1c: %dMB / %dMB scanned...", mb, ROM_SIZE / 0x100000))
            emu.yield()
        end
    end

    -- Check if we found all anchors
    anchor_ok = true
    for _, a in ipairs(ANCHORS) do
        if #a.rom_addrs == 0 then
            anchor_ok = false
            break
        end
    end

    if anchor_ok then
        log(fmt("  ✓ All anchors found with casing: \"%s\"", anchor_set[1]))
        break
    else
        log(fmt("  ✗ Casing \"%s\" — not all anchors found", anchor_set[1]))
    end
end

-- Report findings
for _, a in ipairs(ANCHORS) do
    local count = #a.rom_addrs
    if count == 0 then
        log(fmt("  ✗ \"%s\" — NOT FOUND", a.name))
    elseif count == 1 then
        log(fmt("  ✓ \"%s\" — found at 0x%08X", a.name, a.rom_addrs[1]))
    else
        log(fmt("  ⚠ \"%s\" — %d occurrences:", a.name, count))
        for _, addr in ipairs(a.rom_addrs) do
            log(fmt("      0x%08X", addr))
        end
    end
end

if not anchor_ok then
    log("")
    log("FATAL: Could not find all anchor strings in any encoding/casing combo.")
    flush()
    con("FATAL: Anchor string search failed. Check results file.")
    return
end

log(fmt("  String decoding mode: %s", STRING_MODE))

con("Phase 1 complete.")

-- ══════════════════════════════════════════════════════════════════════════
-- PHASE 2: Find sRegionMapSectionNameTable
-- ══════════════════════════════════════════════════════════════════════════
div()
log("PHASE 2: Finding sRegionMapSectionNameTable")
sep()
con("Phase 2: Locating name table via string clustering + pointer scan...")

-- Strategy: The name table strings are packed consecutively in ROM.
-- Multiple anchors found in a small ROM region = the name table.
-- Dialogue occurrences are scattered far apart.

-- Collect ALL occurrences of ALL anchors
local all_addrs = {}
for _, a in ipairs(ANCHORS) do
    for _, addr in ipairs(a.rom_addrs) do
        all_addrs[#all_addrs + 1] = { addr = addr, name = a.name }
    end
end

-- Sort by address
table.sort(all_addrs, function(a, b) return a.addr < b.addr end)

log("  All anchor string locations (sorted):")
for _, e in ipairs(all_addrs) do
    log(fmt("    0x%08X: \"%s\"", e.addr, e.name))
end

-- Find the cluster: look for a region where 3+ different anchors appear
-- within a 4KB window (name table is compact — packed strings)
local best_cluster = nil
local best_cluster_count = 0

for i = 1, #all_addrs do
    local base_addr = all_addrs[i].addr
    local unique_names = {}
    local cluster_entries = {}
    for j = i, #all_addrs do
        if all_addrs[j].addr - base_addr > 0x1000 then break end  -- 4KB window
        unique_names[all_addrs[j].name] = true
        cluster_entries[#cluster_entries + 1] = all_addrs[j]
    end
    local count = 0
    for _ in pairs(unique_names) do count = count + 1 end
    if count > best_cluster_count then
        best_cluster_count = count
        best_cluster = cluster_entries
    end
end

if not best_cluster or best_cluster_count < 3 then
    log("")
    log("FATAL: Could not find a cluster of 3+ anchor strings within 4KB.")
    flush()
    con("FATAL: Name table cluster not found.")
    return
end

log(fmt("\n  Best cluster: %d unique anchors in region 0x%08X–0x%08X",
        best_cluster_count, best_cluster[1].addr,
        best_cluster[#best_cluster].addr))
for _, e in ipairs(best_cluster) do
    log(fmt("    0x%08X: \"%s\"", e.addr, e.name))
end

-- Scan ROM for 4-byte aligned pointers to a target address
local function findPointersTo(target_addr)
    local results = {}
    for addr = ROM_BASE, ROM_BASE + ROM_SIZE - 4, 4 do
        if rom_r32(addr) == target_addr then
            results[#results + 1] = addr
        end
        if (addr - ROM_BASE) % 0x400000 == 0 then emu.yield() end
    end
    return results
end

-- Find pointers to two cluster entries
local pallet_entry = nil
local second_entry = nil
for _, e in ipairs(best_cluster) do
    if e.name:lower():find("pallet") then
        pallet_entry = e
    elseif not second_entry then
        second_entry = e
    end
end
if not pallet_entry then
    pallet_entry = best_cluster[1]
    second_entry = best_cluster[2]
end

con(fmt("  Scanning for pointers to \"%s\" (0x%08X)...", pallet_entry.name, pallet_entry.addr))
local pallet_ptrs = findPointersTo(pallet_entry.addr)
log(fmt("  Pointers to \"%s\" (0x%08X): %d found", pallet_entry.name, pallet_entry.addr, #pallet_ptrs))
for _, p in ipairs(pallet_ptrs) do log(fmt("    0x%08X", p)) end

con(fmt("  Scanning for pointers to \"%s\" (0x%08X)...", second_entry.name, second_entry.addr))
local second_ptrs = findPointersTo(second_entry.addr)
log(fmt("  Pointers to \"%s\" (0x%08X): %d found", second_entry.name, second_entry.addr, #second_ptrs))
for _, p in ipairs(second_ptrs) do log(fmt("    0x%08X", p)) end

-- Find pointer pairs in the same pointer table.
-- Both should be in a contiguous region of ROM string pointers.
local NAME_TABLE_BASE = nil
local MAPSEC_PALLET   = nil

for _, pp in ipairs(pallet_ptrs) do
    for _, sp in ipairs(second_ptrs) do
        local diff = math.abs(sp - pp)
        if diff >= 4 and diff <= 0x400 and (sp - pp) % 4 == 0 then
            -- Validate neighborhood: check that surrounding entries are valid string pointers
            local test_base = math.min(pp, sp) - 32
            local valid_count = 0
            for off = 0, 80, 4 do
                local candidate_ptr = rom_r32(test_base + off)
                if isRomPtr(candidate_ptr) then
                    local first_byte = rom_r8(candidate_ptr)
                    if (first_byte >= 0xA1 and first_byte <= 0xEE) or first_byte == 0x00 then
                        valid_count = valid_count + 1
                    end
                end
            end

            if valid_count >= 12 then
                log(fmt("  ✓ Pointer pair: 0x%08X → \"%s\", 0x%08X → \"%s\" (valid=%d)",
                        pp, pallet_entry.name, sp, second_entry.name, valid_count))
                -- Scan backwards to find table start
                local base = math.min(pp, sp)
                while true do
                    local prev = rom_r32(base - 4)
                    if isRomPtr(prev) then
                        local fb = rom_r8(prev)
                        if (fb >= 0xA1 and fb <= 0xEE) or fb == 0x00 then
                            base = base - 4
                        else
                            break
                        end
                    else
                        break
                    end
                    if (pp - base) > 4096 then break end
                end
                NAME_TABLE_BASE = base
                MAPSEC_PALLET = (pp - base) / 4
                log(fmt("  Table base: 0x%08X  (Pallet Town table index = %d)",
                        NAME_TABLE_BASE, MAPSEC_PALLET))
                break
            end
        end
    end
    if NAME_TABLE_BASE then break end
end

if not NAME_TABLE_BASE then
    log("")
    log("FATAL: Could not find sRegionMapSectionNameTable.")
    log("The pointer-pair heuristic failed.")
    flush()
    con("FATAL: Name table not found. Check results file.")
    return
end

-- Determine table size: scan forward until entries stop being valid string pointers.
local NAME_TABLE_SIZE = 0
do
    local addr = NAME_TABLE_BASE
    while true do
        local ptr = rom_r32(addr)
        if not isRomPtr(ptr) then break end
        local fb = rom_r8(ptr)
        if not ((fb >= 0xA1 and fb <= 0xEE) or fb == 0x00 or fb == 0xFF) then break end
        NAME_TABLE_SIZE = NAME_TABLE_SIZE + 1
        addr = addr + 4
        if NAME_TABLE_SIZE > 500 then break end  -- safety limit
    end
end
log(fmt("  Table size: %d entries (mapsec 0 through %d)", NAME_TABLE_SIZE, NAME_TABLE_SIZE - 1))

-- In FRLG/CFRU, MapHeaders store raw regionMapSectionId values (e.g., 0x58 for
-- Pallet Town). The name table is indexed starting from 0. The offset between
-- raw mapsec IDs and table indices is MAPSEC_PALLET_TOWN (0x58) from CFRU constants.
-- Formula: table_index = raw_mapsec - MAPSEC_RAW_BASE
--          raw_mapsec  = table_index + MAPSEC_RAW_BASE
local MAPSEC_RAW_BASE = 0x58  -- MAPSEC_PALLET_TOWN from FRLG/CFRU region_map_sections.h
log(fmt("  MAPSEC_RAW_BASE = 0x%02X (raw mapsec offset for name table index 0)", MAPSEC_RAW_BASE))
log(fmt("  Raw mapsec range: 0x%02X–0x%02X (table indices 0–%d)",
        MAPSEC_RAW_BASE, MAPSEC_RAW_BASE + NAME_TABLE_SIZE - 1, NAME_TABLE_SIZE - 1))

-- Cross-validate with other anchors
sep()
log("  Cross-validation with other anchors:")
for i = 3, #ANCHORS do
    local a = ANCHORS[i]
    local found = false
    for mapsec = 0, NAME_TABLE_SIZE - 1 do
        local str_ptr = rom_r32(NAME_TABLE_BASE + mapsec * 4)
        if isRomPtr(str_ptr) then
            local name = decodeByMode(str_ptr, 30)
            if name == a.name then
                log(fmt("    ✓ \"%s\" → table[%d] raw=0x%02X", a.name, mapsec, mapsec + MAPSEC_RAW_BASE))
                found = true
                break
            end
        end
    end
    if not found then
        log(fmt("    ✗ \"%s\" — not found in table!", a.name))
    end
end

con("Phase 2 complete.")

-- ══════════════════════════════════════════════════════════════════════════
-- PHASE 3: Dump ALL mapsec names
-- ══════════════════════════════════════════════════════════════════════════
div()
log("PHASE 3: All region map section names")
sep()

local mapsec_names = {}  -- table_index → name string (0-based)
for idx = 0, NAME_TABLE_SIZE - 1 do
    local str_ptr = rom_r32(NAME_TABLE_BASE + idx * 4)
    if isRomPtr(str_ptr) then
        local name = decodeByMode(str_ptr, 30)
        mapsec_names[idx] = name
        log(fmt("  [%3d] raw=0x%02X: \"%s\"", idx, idx + MAPSEC_RAW_BASE, name))
    else
        log(fmt("  [%3d] raw=0x%02X: <invalid pointer 0x%08X>", idx, idx + MAPSEC_RAW_BASE, str_ptr))
    end
end

con(fmt("Phase 3 complete: %d mapsec names dumped.", NAME_TABLE_SIZE))

-- ══════════════════════════════════════════════════════════════════════════
-- PHASE 4: Find gMapGroups
-- ══════════════════════════════════════════════════════════════════════════
div()
log("PHASE 4: Finding gMapGroups")
sep()
con("Phase 4: Searching for gMapGroups pointer table...")

-- Strategy:
-- 1. MapHeaders store RAW mapsec IDs (e.g., 0x58 for Pallet Town).
--    Scan ROM for MapHeader structs where +0x14 == MAPSEC_RAW_BASE (0x58).
-- 2. For each candidate PalletTown MapHeader, search ROM for a pointer to it.
--    That pointer is gMapGroup_TownsAndRoutes[0].
-- 3. From gMapGroup_TownsAndRoutes base, search ROM for a pointer to it.
--    That pointer is gMapGroups[3].
-- 4. gMapGroups base = found_addr - 3*4.

local PALLET_RAW_MAPSEC = MAPSEC_RAW_BASE + MAPSEC_PALLET  -- 0x58 + 0 = 0x58

-- Step 1: Find PalletTown's MapHeader
local pallet_mh_candidates = {}
con(fmt("  Step 1: Scanning for PalletTown MapHeader (raw mapsec=0x%02X)...", PALLET_RAW_MAPSEC))

for addr = ROM_BASE, ROM_BASE + ROM_SIZE - MAP_HEADER_SIZE, 4 do
    local mapsec_byte = rom_r8(addr + MAPSEC_OFFSET)
    if mapsec_byte == PALLET_RAW_MAPSEC then
        local layout_ptr = rom_r32(addr + 0x00)
        local events_ptr = rom_r32(addr + 0x04)
        local scripts_ptr = rom_r32(addr + 0x08)
        -- Validate: first three fields should be ROM pointers
        if isRomPtr(layout_ptr) and isRomPtr(events_ptr) and isRomPtr(scripts_ptr) then
            local cave = rom_r8(addr + 0x15)
            local weather = rom_r8(addr + 0x16)
            local map_type = rom_r8(addr + 0x17)
            -- Pallet Town: no cave, normal weather/type
            if cave <= 2 and weather <= 15 and map_type <= 15 then
                pallet_mh_candidates[#pallet_mh_candidates + 1] = addr
            end
        end
    end

    if (addr - ROM_BASE) % 0x400000 == 0 then emu.yield() end
end

log(fmt("  PalletTown MapHeader candidates: %d", #pallet_mh_candidates))
for _, addr in ipairs(pallet_mh_candidates) do
    log(fmt("    0x%08X  layout=0x%08X  music=%d  cave=%d  weather=%d  type=%d",
            addr, rom_r32(addr), rom_r16(addr + 0x10),
            rom_r8(addr + 0x15), rom_r8(addr + 0x16), rom_r8(addr + 0x17)))
end

if #pallet_mh_candidates == 0 then
    log("FATAL: No PalletTown MapHeader candidates found.")
    flush()
    con("FATAL: MapHeader search failed.")
    return
end

flush()  -- write candidates before long pointer scan

-- Step 2: Single-pass scan — find ROM pointers to ALL candidates at once.
local G_MAP_GROUPS = nil
local TOWNS_BASE   = nil

con("  Step 2: Single-pass pointer scan for all candidates...")
flush()

-- Build lookup set of all candidate addresses
local candidate_set = {}
for _, addr in ipairs(pallet_mh_candidates) do
    candidate_set[addr] = true
end

-- ONE scan of entire ROM: find every u32 that matches any candidate
local ptr_to_candidate = {}  -- target_addr → list of pointer addresses
for addr = ROM_BASE, ROM_BASE + ROM_SIZE - 4, 4 do
    local val = rom_r32(addr)
    if candidate_set[val] then
        if not ptr_to_candidate[val] then ptr_to_candidate[val] = {} end
        local t = ptr_to_candidate[val]
        t[#t + 1] = addr
    end
    if (addr - ROM_BASE) % 0x400000 == 0 then
        con(fmt("  Step 2: %dMB / %dMB scanned...",
                (addr - ROM_BASE) / 0x100000, ROM_SIZE / 0x100000))
        emu.yield()
    end
end

-- Count how many candidates had pointers
local candidates_with_ptrs = 0
for _ in pairs(ptr_to_candidate) do candidates_with_ptrs = candidates_with_ptrs + 1 end
log(fmt("  %d of %d candidates have ROM pointers to them", candidates_with_ptrs, #pallet_mh_candidates))

-- For each candidate that has pointers, check if it forms a valid group array
for mh_addr, ptr_list in pairs(ptr_to_candidate) do
    for _, scan in ipairs(ptr_list) do
        -- scan points to mh_addr. If this is gMapGroup_TownsAndRoutes[0],
        -- then scan+4 should point to ViridianCity MapHeader
        local next_mh_ptr = rom_r32(scan + 4)
        if isRomPtr(next_mh_ptr) then
            local next_mapsec = rom_r8(next_mh_ptr + MAPSEC_OFFSET)
            if next_mapsec == PALLET_RAW_MAPSEC + 1 then
                -- Convert raw mapsec to table index for name lookup
                local pallet_idx = PALLET_RAW_MAPSEC - MAPSEC_RAW_BASE
                local next_idx   = next_mapsec - MAPSEC_RAW_BASE
                log(fmt("  ✓ gMapGroup_TownsAndRoutes candidate at 0x%08X", scan))
                log(fmt("    [0] → 0x%08X (raw=0x%02X=%s)",
                        mh_addr, PALLET_RAW_MAPSEC, mapsec_names[pallet_idx] or "?"))
                log(fmt("    [1] → 0x%08X (raw=0x%02X=%s)",
                        next_mh_ptr, next_mapsec, mapsec_names[next_idx] or "?"))

                -- Step 3: Find gMapGroups — search for pointer to this group array base.
                TOWNS_BASE = scan
                con("  Step 3: Finding gMapGroups outer pointer...")
                local outer_ptrs = findPointersTo(scan)
                log(fmt("    Pointers to TownsAndRoutes base: %d found", #outer_ptrs))

                for _, outer in ipairs(outer_ptrs) do
                    local g0_ptr = rom_r32(outer - 12)
                    local g1_ptr = rom_r32(outer - 8)
                    local g2_ptr = rom_r32(outer - 4)
                    if isRomPtr(g0_ptr) and isRomPtr(g1_ptr) and isRomPtr(g2_ptr) then
                        local g0_first = rom_r32(g0_ptr)
                        if isRomPtr(g0_first) then
                            G_MAP_GROUPS = outer - 12
                            log(fmt("  ✓ gMapGroups found at 0x%08X", G_MAP_GROUPS))
                            log(fmt("    [0]=0x%08X  [1]=0x%08X  [2]=0x%08X  [3]=0x%08X",
                                    g0_ptr, g1_ptr, g2_ptr, scan))
                            break
                        end
                    end
                end
                if G_MAP_GROUPS then break end
            end
        end
    end
    if G_MAP_GROUPS then break end
end

if not G_MAP_GROUPS then
    log("")
    log("FATAL: Could not find gMapGroups pointer table.")
    flush()
    con("FATAL: gMapGroups not found. Check results file.")
    return
end

-- Validate: count the groups by scanning forward
local detected_groups = 0
do
    local addr = G_MAP_GROUPS
    while true do
        local gptr = rom_r32(addr)
        if not isRomPtr(gptr) then break end
        -- The group pointer should itself point to ROM pointers (MapHeader*)
        local first_entry = rom_r32(gptr)
        if not isRomPtr(first_entry) then break end
        detected_groups = detected_groups + 1
        addr = addr + 4
        if detected_groups > 100 then break end
    end
end
log(fmt("  Detected %d map groups (vanilla has %d)", detected_groups, VANILLA_NUM_GROUPS))
if detected_groups > VANILLA_NUM_GROUPS then
    log(fmt("  ★ ROM has %d NEW map groups beyond vanilla!", detected_groups - VANILLA_NUM_GROUPS))
end

con("Phase 4 complete.")

-- ══════════════════════════════════════════════════════════════════════════
-- PHASE 5: Walk all maps — FULLY DYNAMIC discovery
-- ══════════════════════════════════════════════════════════════════════════
div()
log("PHASE 5: Walking all mapGroup:mapNum → in-game name (dynamic)")
sep()
con("Phase 5: Reading map names (dynamic probe per group)...")

-- For each group, we dynamically determine the number of maps by probing
-- the pointer array until the chain fails validation.  A valid map entry
-- must satisfy ALL of these checks (prevents overrun into adjacent data):
--   1. gMapGroup[num] is a ROM pointer           → candidate MapHeader address
--   2. MapHeader+0x00 (mapLayout*) is a ROM pointer
--   3. MapHeader+0x04 (events*) is a ROM pointer
--   4. MapHeader+0x08 (mapScripts*) is a ROM pointer
--   5. MapHeader+0x14 (regionMapSectionId) in range [MAPSEC_RAW_BASE, MAPSEC_RAW_BASE + NAME_TABLE_SIZE)
--   6. MapHeader+0x15 (cave) <= 2
--   7. MapHeader+0x16 (weather) <= 15
--   8. MapHeader+0x17 (mapType) <= 15
-- If ANY check fails, we stop probing that group.

local function isValidMapHeader(mh_addr)
    local layout_ptr  = rom_r32(mh_addr + 0x00)
    local events_ptr  = rom_r32(mh_addr + 0x04)
    local scripts_ptr = rom_r32(mh_addr + 0x08)
    if not isRomPtr(layout_ptr)  then return false end
    if not isRomPtr(events_ptr)  then return false end
    if not isRomPtr(scripts_ptr) then return false end
    local mapsec   = rom_r8(mh_addr + MAPSEC_OFFSET)
    local cave     = rom_r8(mh_addr + 0x15)
    local weather  = rom_r8(mh_addr + 0x16)
    local map_type = rom_r8(mh_addr + 0x17)
    -- Raw mapsec must be in the valid range: MAPSEC_RAW_BASE to MAPSEC_RAW_BASE + NAME_TABLE_SIZE - 1
    if mapsec < MAPSEC_RAW_BASE or mapsec >= MAPSEC_RAW_BASE + NAME_TABLE_SIZE then return false end
    if cave > 2    then return false end
    if weather > 15 then return false end
    if map_type > 15 then return false end
    return true
end

-- Results table: list of {group, num, mapsec, name, cave, weather, map_type, music}
local results = {}
local errors = {}
local total_maps = 0
local new_maps = 0          -- maps beyond vanilla group boundaries
local new_group_maps = 0    -- maps in entirely new groups

for group = 0, detected_groups - 1 do
    local group_ptr = rom_r32(G_MAP_GROUPS + group * 4)
    if not isRomPtr(group_ptr) then
        log(fmt("  Group %d: SKIPPED (invalid group pointer 0x%08X)", group, group_ptr))
        goto next_group
    end

    -- Determine group size: use pointer boundary as upper limit, validate each entry.
    -- Group arrays are USUALLY contiguous, but not always (Group 0 may be distant).
    local max_entries = 300  -- safety limit
    if group < detected_groups - 1 then
        local next_group_ptr = rom_r32(G_MAP_GROUPS + (group + 1) * 4)
        if isRomPtr(next_group_ptr) and next_group_ptr > group_ptr then
            local ptr_diff = (next_group_ptr - group_ptr) / 4
            if ptr_diff < max_entries then
                max_entries = ptr_diff
            end
        end
    end
    local group_count = 0
    for probe = 0, max_entries - 1 do
        local mh_ptr = rom_r32(group_ptr + probe * 4)
        if not isRomPtr(mh_ptr) then break end
        if not isValidMapHeader(mh_ptr) then break end
        group_count = group_count + 1
    end

    -- Compare with vanilla
    local vanilla_count = VANILLA_GROUP_SIZES[group]
    local is_new_group = (group >= VANILLA_NUM_GROUPS)
    local group_label
    if is_new_group then
        group_label = fmt("Group %d [NEW — %d maps]", group, group_count)
    elseif vanilla_count and group_count ~= vanilla_count then
        group_label = fmt("Group %d [CHANGED: vanilla=%d, actual=%d]", group, vanilla_count, group_count)
    else
        group_label = fmt("Group %d [%d maps]", group, group_count)
    end
    log(fmt("\n  ── %s ──", group_label))

    for num = 0, group_count - 1 do
        local mh_ptr = rom_r32(group_ptr + num * 4)
        -- We already validated in the probe loop, but double-check
        if not isRomPtr(mh_ptr) then
            errors[#errors + 1] = fmt("%d:%d — invalid MapHeader pointer", group, num)
            goto next_map
        end

        local mapsec = rom_r8(mh_ptr + MAPSEC_OFFSET)
        local table_idx = mapsec - MAPSEC_RAW_BASE
        local name = mapsec_names[table_idx]
        if not name then
            if table_idx >= 0 and table_idx < NAME_TABLE_SIZE then
                local str_ptr = rom_r32(NAME_TABLE_BASE + table_idx * 4)
                if isRomPtr(str_ptr) then
                    name = decodeByMode(str_ptr, 30)
                end
            end
        end
        name = name or fmt("<unknown mapsec 0x%02X>", mapsec)

        local cave     = rom_r8(mh_ptr + 0x15)
        local weather  = rom_r8(mh_ptr + 0x16)
        local map_type = rom_r8(mh_ptr + 0x17)
        local music    = rom_r16(mh_ptr + 0x10)

        -- Track new vs vanilla maps
        local is_new_map = is_new_group or (vanilla_count and num >= vanilla_count)
        if is_new_map and is_new_group then
            new_group_maps = new_group_maps + 1
        elseif is_new_map then
            new_maps = new_maps + 1
        end

        results[#results + 1] = {
            group    = group,
            num      = num,
            mapsec   = mapsec,
            name     = name,
            cave     = cave,
            weather  = weather,
            map_type = map_type,
            music    = music,
            is_new   = is_new_map,
        }
        total_maps = total_maps + 1

        local new_tag = is_new_map and " ★NEW" or ""
        log(fmt("    %d:%d  mapsec=0x%02X  name=%-25s  cave=%d  weather=%d  type=%d%s",
                group, num, mapsec, '"' .. name .. '"', cave, weather, map_type, new_tag))

        ::next_map::
    end

    -- Yield between groups to keep BizHawk responsive
    if group % 5 == 0 then emu.yield() end

    ::next_group::
end

-- Summary
sep()
log(fmt("  Total maps: %d  (vanilla=%d, new in existing groups=%d, new groups=%d)",
        total_maps, total_maps - new_maps - new_group_maps, new_maps, new_group_maps))
if #errors > 0 then
    log(fmt("  Errors: %d", #errors))
    for _, e in ipairs(errors) do log("    " .. e) end
end

con("Phase 5 complete.")

-- ══════════════════════════════════════════════════════════════════════════
-- PHASE 6: JSON output for machine parsing
-- ══════════════════════════════════════════════════════════════════════════
div()
log("JSON OUTPUT")
sep()

-- Escape a string for JSON embedding
local function json_escape(s)
    return s:gsub("\\", "\\\\"):gsub('"', '\\"'):gsub("\n", "\\n")
end

log("===JSON_START===")
log("{")

-- Section 1: mapsec name table (keyed by raw mapsec ID)
log('  "mapsec_names": {')
local mapsec_lines = {}
for idx = 0, NAME_TABLE_SIZE - 1 do
    local n = mapsec_names[idx]
    if n then
        local raw = idx + MAPSEC_RAW_BASE
        mapsec_lines[#mapsec_lines + 1] = fmt('    "%d": "%s"', raw, json_escape(n))
    end
end
log(table.concat(mapsec_lines, ",\n"))
log("  },")

-- Section 2: map results
log('  "maps": [')
local map_lines = {}
for _, r in ipairs(results) do
    map_lines[#map_lines + 1] = fmt(
        '    {"group":%d,"num":%d,"mapsec":%d,"name":"%s","cave":%d,"weather":%d,"map_type":%d,"music":%d,"is_new":%s}',
        r.group, r.num, r.mapsec, json_escape(r.name), r.cave, r.weather, r.map_type, r.music,
        r.is_new and "true" or "false")
end
log(table.concat(map_lines, ",\n"))
log("  ],")

-- Section 3: metadata
log('  "metadata": {')
log(fmt('    "rom_name": "%s",', json_escape(gameinfo and gameinfo.getromname and gameinfo.getromname() or "unknown")))
log(fmt('    "name_table_base": "0x%08X",', NAME_TABLE_BASE))
log(fmt('    "name_table_size": %d,', NAME_TABLE_SIZE))
log(fmt('    "gMapGroups": "0x%08X",', G_MAP_GROUPS))
log(fmt('    "detected_groups": %d,', detected_groups))
log(fmt('    "vanilla_groups": %d,', VANILLA_NUM_GROUPS))
log(fmt('    "total_maps": %d,', total_maps))
log(fmt('    "new_maps_in_existing_groups": %d,', new_maps))
log(fmt('    "new_group_maps": %d,', new_group_maps))
log(fmt('    "mapsec_pallet_town": %d,', MAPSEC_PALLET))
log(fmt('    "mapsec_raw_base": %d', MAPSEC_RAW_BASE))
log("  }")

log("}")
log("===JSON_END===")

-- ── Flush output ───────────────────────────────────────────────────────────
flush()

div()
con("")
con("════════════════════════════════════════════════════════")
con(fmt("  DONE — %d maps extracted, %d mapsec names", total_maps, NAME_TABLE_SIZE))
if new_maps + new_group_maps > 0 then
    con(fmt("  ★ %d NEW maps discovered beyond vanilla FRLG!", new_maps + new_group_maps))
    if new_group_maps > 0 then
        con(fmt("    (%d in %d new groups, %d in expanded existing groups)",
                new_group_maps, detected_groups - VANILLA_NUM_GROUPS, new_maps))
    end
end
if OUT_PATH then
    con(fmt("  Results: %s", OUT_PATH))
    con("  Run: python tools/parse_map_names.py")
else
    con("  (no file written — check console output)")
end
con("════════════════════════════════════════════════════════")
