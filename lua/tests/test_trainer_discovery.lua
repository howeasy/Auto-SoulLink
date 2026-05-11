--[[
  lua/test_trainer_discovery.lua — gTrainers Table Scanner
  =========================================================
  Finds the gTrainers ROM table by searching for known gym leader names
  encoded in Gen III character format, then dumps all trainer names.

  Supports vanilla FRLG (16MB) and Radical Red / CFRU (32MB).

  The struct Trainer layout (identical in vanilla and CFRU) is 40 bytes:
    +0x00  u8  partyFlags
    +0x01  u8  trainerClass
    +0x02  u8  encounterMusic_gender
    +0x03  u8  trainerPic
    +0x04  u8  trainerName[12]   ← Gen III encoded, 0xFF terminated
    +0x10  u16 items[4]
    +0x18  u8  doubleBattle
    +0x19  u8  padding[3]
    +0x1C  u32 aiFlags
    +0x20  u8  partySize
    +0x21  u8  padding[3]
    +0x24  u32 partyPtr           ← ROM pointer (0x08xxxxxx)

  HOW TO USE:
    1. Load FireRed/LeafGreen (vanilla or RR) in BizHawk, load a save.
    2. Load this script in the Lua Console.
    3. Results are saved to data/rr_trainers.json (or data/trainers.json).
       Copy from the BizHawk Lua console output directory if needed.

  OUTPUT FORMAT (JSON):
    { "base": "0x08XXXXXX", "struct_size": 40, "count": N,
      "trainers": { "1": {"name": "BROCK", "class": 57}, ... } }
--]]

local TRAINER_STRUCT_SIZE = 40    -- sizeof(struct Trainer) = 0x28
local NAME_OFFSET         = 4    -- trainerName starts at +0x04
local NAME_MAX_LEN        = 12   -- trainerName[12]
local CLASS_OFFSET         = 1   -- trainerClass at +0x01
local PARTY_SIZE_OFFSET    = 0x20
local PARTY_PTR_OFFSET     = 0x24
local ROM_BASE             = 0x08000000

-- ── Gen III character encoding ──────────────────────────────────────────────

local DECODE = {}
-- Uppercase A-Z: 0xBB..0xD4
for i = 0, 25 do DECODE[0xBB + i] = string.char(65 + i) end
-- Lowercase a-z: 0xD5..0xEE
for i = 0, 25 do DECODE[0xD5 + i] = string.char(97 + i) end
-- Digits 0-9: 0xA1..0xAA
for i = 0, 9 do DECODE[0xA1 + i] = string.char(48 + i) end
-- Common special characters
DECODE[0x00] = " "
DECODE[0xAB] = "!"
DECODE[0xAC] = "?"
DECODE[0xAD] = "."
DECODE[0xAE] = "-"   -- U+2013 en-dash in some tables, but dash for our purposes
DECODE[0xB0] = "\226\128\166"  -- ellipsis (...)
DECODE[0xB1] = "\226\128\156"  -- open double quote
DECODE[0xB2] = "\226\128\157"  -- close double quote
DECODE[0xB3] = "\226\128\152"  -- open single quote
DECODE[0xB4] = "\226\128\153"  -- apostrophe / close single quote
DECODE[0xB5] = "\226\153\130"  -- male sign
DECODE[0xB6] = "\226\153\128"  -- female sign
DECODE[0xB8] = ","
DECODE[0xBA] = "/"

local ENCODE = {}
for byte, char in pairs(DECODE) do
    if #char == 1 then ENCODE[char] = byte end
end

local function encodeStr(s)
    local bytes = {}
    for i = 1, #s do
        local c = s:sub(i, i)
        local b = ENCODE[c]
        if b then bytes[#bytes + 1] = b end
    end
    bytes[#bytes + 1] = 0xFF  -- EOS
    return bytes
end

local function decodeStr(addr)
    local chars = {}
    for i = 0, NAME_MAX_LEN - 1 do
        local b = memory.read_u8(addr + i, "System Bus")
        if b == 0xFF then break end
        local c = DECODE[b]
        if c then
            chars[#chars + 1] = c
        else
            chars[#chars + 1] = string.format("{%02X}", b)
        end
    end
    return table.concat(chars)
end

-- ── Helpers ─────────────────────────────────────────────────────────────────

local function hex(n) return string.format("0x%08X", n) end
local function printDiv() print(string.rep("=", 70)) end
local function printLine() print(string.rep("-", 70)) end

local function detectRomEnd()
    -- Check 32MB boundary first, then 16MB
    local addr32 = ROM_BASE + 0x02000000 - 4  -- last 4 bytes of 32MB
    local ok32, val32 = pcall(function() return memory.read_u32_le(addr32, "System Bus") end)
    if ok32 and val32 ~= 0 then return ROM_BASE + 0x02000000 end
    return ROM_BASE + 0x01000000  -- 16MB
end

-- Scan ROM for a byte pattern. Returns list of addresses where found.
local function scanForBytes(pattern, romEnd, label)
    local results = {}
    local pLen = #pattern
    local step = 4  -- trainer structs are 4-byte aligned
    local total = romEnd - ROM_BASE
    local lastProgress = -1

    for addr = ROM_BASE, romEnd - pLen, step do
        -- Progress every 4MB
        local mb4 = math.floor((addr - ROM_BASE) / (4 * 1024 * 1024))
        if mb4 ~= lastProgress then
            lastProgress = mb4
            if mb4 > 0 then
                print(string.format("  Scanning %s: %dMB / %dMB...",
                    label, mb4 * 4, total / (1024*1024)))
                emu.yield()
            end
        end
        -- Check first byte quick-reject
        if memory.read_u8(addr, "System Bus") == pattern[1] then
            local match = true
            for j = 2, pLen do
                if memory.read_u8(addr + j - 1, "System Bus") ~= pattern[j] then
                    match = false
                    break
                end
            end
            if match then
                results[#results + 1] = addr
            end
        end
    end
    return results
end

-- Validate a candidate trainer struct entry at the given address.
local function isValidTrainer(addr, romEnd)
    -- partyFlags should be 0-3 (bitmask: custom_moves | has_item)
    local flags = memory.read_u8(addr, "System Bus")
    if flags > 3 then return false end

    -- trainerClass should be reasonable (0-255 but typically < 130)
    local cls = memory.read_u8(addr + CLASS_OFFSET, "System Bus")

    -- partySize should be 1-6
    local pSize = memory.read_u8(addr + PARTY_SIZE_OFFSET, "System Bus")
    if pSize < 1 or pSize > 6 then return false end

    -- partyPtr should be a ROM pointer (0x08xxxxxx) within ROM range
    local ptr = memory.read_u32_le(addr + PARTY_PTR_OFFSET, "System Bus")
    if ptr < ROM_BASE or ptr >= romEnd then return false end

    -- Name should start with a valid Gen III character (not 0xFF = EOS)
    local firstChar = memory.read_u8(addr + NAME_OFFSET, "System Bus")
    if firstChar == 0xFF then return false end

    return true
end

-- Read a single trainer entry at the given struct base address.
local function readTrainer(addr)
    return {
        name      = decodeStr(addr + NAME_OFFSET),
        class     = memory.read_u8(addr + CLASS_OFFSET, "System Bus"),
        partySize = memory.read_u8(addr + PARTY_SIZE_OFFSET, "System Bus"),
        pic       = memory.read_u8(addr + 3, "System Bus"),
        flags     = memory.read_u8(addr, "System Bus"),
    }
end

-- ── Main discovery ──────────────────────────────────────────────────────────

printDiv()
print("  SLINK TRAINER DISCOVERY — gTrainers Table Scanner")
print("  Supports vanilla FRLG and Radical Red / CFRU")
printDiv()

local romEnd = detectRomEnd()
local romSizeMB = (romEnd - ROM_BASE) / (1024 * 1024)
print(string.format("[STEP 0] ROM size detected: %dMB (end = %s)", romSizeMB, hex(romEnd)))

-- ── Step 1: Search for known gym leader names ───────────────────────────────
printLine()
print("[STEP 1] Searching for known trainer names in ROM...")

-- These names are stable across vanilla FRLG and Radical Red.
-- Vanilla uses ALL CAPS ("BROCK"), RR/CFRU uses Title Case ("Brock").
-- We search for both variants.
local KNOWN_NAMES = {
    { name = "BROCK",    bytes = encodeStr("BROCK"),    alt = encodeStr("Brock") },
    { name = "MISTY",    bytes = encodeStr("MISTY"),    alt = encodeStr("Misty") },
    { name = "ERIKA",    bytes = encodeStr("ERIKA"),    alt = encodeStr("Erika") },
    { name = "KOGA",     bytes = encodeStr("KOGA"),     alt = encodeStr("Koga") },
    { name = "SABRINA",  bytes = encodeStr("SABRINA"),  alt = encodeStr("Sabrina") },
    { name = "BLAINE",   bytes = encodeStr("BLAINE"),   alt = encodeStr("Blaine") },
    { name = "GIOVANNI", bytes = encodeStr("GIOVANNI"), alt = encodeStr("Giovanni") },
    { name = "LORELEI",  bytes = encodeStr("LORELEI"),  alt = encodeStr("Lorelei") },
    { name = "BRUNO",    bytes = encodeStr("BRUNO"),    alt = encodeStr("Bruno") },
    { name = "AGATHA",   bytes = encodeStr("AGATHA"),   alt = encodeStr("Agatha") },
    { name = "LANCE",    bytes = encodeStr("LANCE"),    alt = encodeStr("Lance") },
}

-- For each name, find occurrences where the name starts at offset +4
-- of a valid trainer struct (i.e., the address - 4 is a valid struct start).
local candidates = {}  -- { addr = struct_base, name = ... }

for _, kn in ipairs(KNOWN_NAMES) do
    -- Try ALL CAPS first (vanilla), then Title Case (RR/CFRU)
    local hits = scanForBytes(kn.bytes, romEnd, kn.name)
    local altHits = {}
    if kn.alt then
        altHits = scanForBytes(kn.alt, romEnd, kn.name .. "(lc)")
    end
    -- Merge hit lists
    for _, h in ipairs(altHits) do hits[#hits + 1] = h end

    local validCount = 0
    for _, nameAddr in ipairs(hits) do
        local structAddr = nameAddr - NAME_OFFSET
        if structAddr >= ROM_BASE and isValidTrainer(structAddr, romEnd) then
            candidates[#candidates + 1] = { addr = structAddr, name = kn.name }
            validCount = validCount + 1
        end
    end
    print(string.format("  %-10s  %d hit(s) in ROM, %d valid struct(s)",
        kn.name, #hits, validCount))
end

if #candidates == 0 then
    print("\n  ERROR: No trainer structs found! Cannot determine gTrainers base.")
    -- Diagnostic: dump encoded bytes for the first name so user can verify
    print("\n  Diagnostic — encoded bytes for 'BROCK':")
    local diag = {}
    for _, b in ipairs(encodeStr("BROCK")) do diag[#diag+1] = string.format("%02X", b) end
    print("    ALL CAPS: " .. table.concat(diag, " "))
    diag = {}
    for _, b in ipairs(encodeStr("Brock")) do diag[#diag+1] = string.format("%02X", b) end
    print("    Title:    " .. table.concat(diag, " "))
    -- Also sample some raw ROM bytes near where gTrainers might be
    -- (vanilla gTrainers is around 0x0823EAC8)
    print("\n  Sampling ROM at vanilla gTrainers region (0x0823EAC8 ± 256 bytes):")
    local sampleBase = 0x0823EAC8
    for off = 0, 256, 40 do
        local addr = sampleBase + off
        local raw = {}
        for i = 0, 15 do
            raw[#raw+1] = string.format("%02X", memory.read_u8(addr + i, "System Bus"))
        end
        -- Also decode bytes 4-15 as a name
        local nameStr = decodeStr(addr + 4)
        print(string.format("    %s: %s  name='%s'", hex(addr), table.concat(raw, " "), nameStr))
    end
    printDiv()
    return
end

-- ── Step 2: Determine gTrainers base address ────────────────────────────────
printLine()
print("[STEP 2] Determining gTrainers base address...")

-- All candidate struct addresses should be: base + (trainerID * STRUCT_SIZE)
-- So (addr - base) must be divisible by STRUCT_SIZE for all candidates.
-- The base is the lowest address where entry 0 would be.
-- Strategy: take the lowest candidate address and walk backward by STRUCT_SIZE
-- until we find entry 0 (an empty/placeholder trainer, or an invalid entry).

-- Sort candidates by address
table.sort(candidates, function(a, b) return a.addr < b.addr end)

-- Use the first candidate as anchor, walk backward
local anchor = candidates[1].addr
print(string.format("  Anchor: %s (%s)", candidates[1].name, hex(anchor)))

-- Walk backward by STRUCT_SIZE until we find an invalid entry
local base = anchor
while base > ROM_BASE do
    local prev = base - TRAINER_STRUCT_SIZE
    -- Check if prev looks like a valid trainer or the empty entry 0
    local firstNameByte = memory.read_u8(prev + NAME_OFFSET, "System Bus")
    local pSize = memory.read_u8(prev + PARTY_SIZE_OFFSET, "System Bus")
    local ptr = memory.read_u32_le(prev + PARTY_PTR_OFFSET, "System Bus")

    -- Entry 0 is typically empty: name starts with 0xFF, partySize=0
    -- But it might have a valid partyPtr pointing to a dummy entry.
    -- We stop when the entry is clearly not part of the table.
    if ptr < ROM_BASE or ptr >= romEnd then
        break  -- partyPtr out of ROM range = not a trainer entry
    end
    -- partySize of 0 is allowed for entry 0 (placeholder)
    if pSize > 6 then
        break
    end
    base = prev
end

-- Verify: check that all candidates are at (base + N*STRUCT_SIZE) offsets
local allAligned = true
for _, c in ipairs(candidates) do
    local offset = c.addr - base
    if offset % TRAINER_STRUCT_SIZE ~= 0 then
        allAligned = false
        print(string.format("  WARNING: %s at %s is not aligned (offset=%d)",
            c.name, hex(c.addr), offset))
    end
end

if allAligned then
    print(string.format("  All %d candidates align to base %s with stride %d",
        #candidates, hex(base), TRAINER_STRUCT_SIZE))
else
    print("  WARNING: Not all candidates align! Struct size might differ.")
    -- Try to compute actual struct size from candidate spacing
    if #candidates >= 2 then
        local diffs = {}
        for i = 2, #candidates do
            diffs[#diffs + 1] = candidates[i].addr - candidates[i-1].addr
        end
        -- GCD of all diffs
        local function gcd(a, b)
            while b ~= 0 do a, b = b, a % b end
            return a
        end
        local g = diffs[1]
        for i = 2, #diffs do g = gcd(g, diffs[i]) end
        print(string.format("  Computed struct size from GCD of spacings: %d bytes", g))
        if g ~= TRAINER_STRUCT_SIZE then
            print(string.format("  OVERRIDING struct size: %d → %d", TRAINER_STRUCT_SIZE, g))
            TRAINER_STRUCT_SIZE = g
            -- Re-walk backward with new stride
            base = anchor
            while base > ROM_BASE do
                local prev = base - TRAINER_STRUCT_SIZE
                local ptr = memory.read_u32_le(prev + PARTY_PTR_OFFSET, "System Bus")
                if ptr < ROM_BASE or ptr >= romEnd then break end
                local pSize = memory.read_u8(prev + PARTY_SIZE_OFFSET, "System Bus")
                if pSize > 6 then break end
                base = prev
            end
        end
    end
end

print(string.format("  gTrainers base = %s", hex(base)))

-- ── Step 3: Count total trainers ────────────────────────────────────────────
printLine()
print("[STEP 3] Counting trainers...")

local count = 0
local maxScan = 3000  -- RR has ~800+ trainers, cap at 3000 for safety
while count < maxScan do
    local entryAddr = base + count * TRAINER_STRUCT_SIZE
    if entryAddr + TRAINER_STRUCT_SIZE > romEnd then break end

    local ptr = memory.read_u32_le(entryAddr + PARTY_PTR_OFFSET, "System Bus")
    local pSize = memory.read_u8(entryAddr + PARTY_SIZE_OFFSET, "System Bus")

    -- Entry 0 (placeholder) is allowed: partySize=0
    -- Valid entries: partyPtr in ROM, partySize 0-6
    if ptr < ROM_BASE or ptr >= romEnd then break end
    if pSize > 6 then break end

    count = count + 1
end

print(string.format("  Found %d trainer entries", count))

-- ── Step 4: Read all trainer names ──────────────────────────────────────────
printLine()
print("[STEP 4] Reading trainer data...")

local trainers = {}
local emptyCount = 0

for i = 0, count - 1 do
    local addr = base + i * TRAINER_STRUCT_SIZE
    local t = readTrainer(addr)

    if t.name == "" or t.name:sub(1, 1) == "{" then
        emptyCount = emptyCount + 1
    else
        trainers[i] = t
    end

    -- Print gym leaders and other notable trainers
    if i <= 5 or (t.name ~= "" and t.name:sub(1,1) ~= "{") then
        if i <= 5 or i % 100 == 0 then
            -- Print occasionally
        end
    end
end

-- Print summary of known trainers found
print(string.format("  %d named trainers, %d empty/placeholder", count - emptyCount, emptyCount))

-- Print all candidates with their IDs
print("\n  Known gym leaders/E4 found at:")
for _, c in ipairs(candidates) do
    local id = (c.addr - base) / TRAINER_STRUCT_SIZE
    local t = readTrainer(c.addr)
    print(string.format("    [%4d] %-12s  class=%d  party=%d",
        id, t.name, t.class, t.partySize))
end

-- ── Step 5: Save results ────────────────────────────────────────────────────
printLine()
print("[STEP 5] Saving results...")

-- Build JSON output
local parts = {}
parts[#parts + 1] = "{"
parts[#parts + 1] = string.format('  "base": "%s",', hex(base))
parts[#parts + 1] = string.format('  "struct_size": %d,', TRAINER_STRUCT_SIZE)
parts[#parts + 1] = string.format('  "count": %d,', count)
parts[#parts + 1] = '  "trainers": {'

local first = true
for i = 0, count - 1 do
    local addr = base + i * TRAINER_STRUCT_SIZE
    local t = readTrainer(addr)
    if t.name ~= "" and t.name:sub(1,1) ~= "{" then
        if not first then parts[#parts + 1] = "," end
        first = false
        -- Escape any quotes in names
        local safeName = t.name:gsub('"', '\\"')
        parts[#parts + 1] = string.format(
            '    "%d": {"name": "%s", "class": %d, "party_size": %d}',
            i, safeName, t.class, t.partySize)
    end
end

parts[#parts + 1] = "  }"
parts[#parts + 1] = "}"

local json = table.concat(parts, "\n")

-- Try to write to the data directory (relative to script location)
local function resolveOutputPath()
    -- Strategy 1: debug.getinfo script directory → ../data/rr_trainers.json
    local ok, info = pcall(debug.getinfo, 1, "S")
    if ok and info and info.source then
        local dir = info.source:match("^@?(.*[\\/])")
        if dir then
            -- dir is lua/, go up to project root and into data/
            for _, sep in ipairs({"\\", "/"}) do
                local dataPath = dir .. ".." .. sep .. "data" .. sep .. "rr_trainers.json"
                local f = io.open(dataPath, "w")
                if f then f:close(); return dataPath end
            end
            -- Fallback: save in the script's own directory
            local dataPath = dir .. "rr_trainers.json"
            local f = io.open(dataPath, "w")
            if f then f:close(); return dataPath end
        end
    end
    -- Strategy 2: try common relative paths
    for _, path in ipairs({"data/rr_trainers.json", "data\\rr_trainers.json",
                           "rr_trainers.json"}) do
        local f = io.open(path, "w")
        if f then f:close(); return path end
    end
    return nil
end

local outPath = resolveOutputPath()
local saved = false
if outPath then
    local f = io.open(outPath, "w")
    if f then
        f:write(json)
        f:close()
        print("  Saved to: " .. outPath)
        saved = true
    end
end

if not saved then
    -- Fallback: print a truncated version to console
    print("  Could not write file. Printing first 20 trainers to console:")
    local printed = 0
    for i = 0, count - 1 do
        if printed >= 20 then break end
        local addr = base + i * TRAINER_STRUCT_SIZE
        local t = readTrainer(addr)
        if t.name ~= "" and t.name:sub(1,1) ~= "{" then
            print(string.format("    [%4d] %-12s  class=%d  party=%d",
                i, t.name, t.class, t.partySize))
            printed = printed + 1
        end
    end
    print(string.format("    ... (%d more, save file to see all)", count - emptyCount - 20))
end

printDiv()
print("  gTrainers = " .. hex(base) .. "  (" .. count .. " entries)")
print("  struct size = " .. TRAINER_STRUCT_SIZE .. " bytes")
print("  Results saved to data/rr_trainers.json")
printDiv()

-- ── Step 6: Interactive gTrainerBattleOpponent_A discovery ─────────────────────
-- Strategy: compare EWRAM outside battle (baseline) vs during battle.
-- The correct address holds 0 or stale data in overworld, a valid trainer ID in battle.
--
-- Usage:
--   1. Make sure you're on the OVERWORLD (not in battle), press F1 for baseline
--   2. Enter a trainer battle, press F1 again for battle snapshot
--   3. The script finds addresses that changed from 0/invalid → valid trainer ID
--   Press F2 to show status.  Press F3 to exit.

print("\n[STEP 6] gTrainerBattleOpponent_A discovery (interactive)...")
print("  Step A: Go to OVERWORLD (not in battle), press F1 for baseline scan.")
print("  Step B: Enter a trainer battle, press F1 again for battle scan.")
print("  Press F3 to exit.\n")

-- Build lookup: trainer_id → name
local idToName = {}
for i = 1, count - 1 do
    local tAddr = base + i * TRAINER_STRUCT_SIZE
    local tName = decodeStr(tAddr + NAME_OFFSET)
    if tName ~= "" and tName:sub(1,1) ~= "{" then
        idToName[i] = tName
    end
end

-- Also build an off-by-one lookup (game might use 1-based IDs)
local idToNameAdj = {}
for i = 1, count - 1 do
    if idToName[i] then
        idToNameAdj[i + 1] = idToName[i] .. " [idx+" .. 1 .. "]"
    end
end

local SCAN_START = 0x02022000
local SCAN_END   = 0x0203FFFE

local baseline = nil   -- {[addr] = value} snapshot from overworld
local battle   = nil   -- {[addr] = value} snapshot from battle
local scanPhase = "baseline"  -- "baseline" or "battle"

local function scanRegion()
    local snapshot = {}
    for addr = SCAN_START, SCAN_END, 2 do
        snapshot[addr] = memory.read_u16_le(addr, "System Bus")
    end
    return snapshot
end

local function analyzeResults()
    if not baseline or not battle then return end

    -- Find addresses where:
    --   baseline value is NOT a valid trainer ID (0, or not in table)
    --   battle value IS a valid trainer ID
    local candidates = {}
    for addr = SCAN_START, SCAN_END, 2 do
        local bval = baseline[addr] or 0
        local aval = battle[addr] or 0
        local baselineValid = (bval >= 1 and bval < count and idToName[bval])
        local battleValid   = (aval >= 1 and aval < count and idToName[aval])
        -- Also check off-by-one: game value might be table_index + 1
        local battleValidAdj = (aval >= 2 and aval <= count and idToName[aval - 1])

        if not baselineValid and (battleValid or battleValidAdj) then
            local name = ""
            local adjusted = false
            if battleValid then
                name = idToName[aval]
            elseif battleValidAdj then
                name = idToName[aval - 1]
                adjusted = true
            end
            candidates[#candidates + 1] = {
                addr = addr, id = aval, name = name,
                baseline_val = bval, adjusted = adjusted,
            }
        end
    end

    -- Also check: addresses where baseline WAS valid but battle has a DIFFERENT valid ID
    -- (gTrainerBattleOpponent_A might retain the previous trainer's ID on overworld)
    local changed = {}
    for addr = SCAN_START, SCAN_END, 2 do
        local bval = baseline[addr] or 0
        local aval = battle[addr] or 0
        if bval ~= aval then
            local battleValid    = (aval >= 1 and aval < count and idToName[aval])
            local battleValidAdj = (aval >= 2 and aval <= count and idToName[aval - 1])
            if battleValid or battleValidAdj then
                local name = battleValid and idToName[aval] or idToName[aval - 1]
                changed[addr] = {id = aval, name = name, adjusted = not battleValid}
            end
        end
    end

    printDiv()

    -- Check predicted addresses specifically
    print("  Predicted address check:")
    for _, paddr in ipairs({0x020386AE, 0x020386C2}) do
        local bval = baseline[paddr] or 0
        local aval = battle[paddr] or 0
        local nameExact = idToName[aval] or ""
        local nameAdj   = (aval >= 2) and idToName[aval - 1] or ""
        local label = (paddr == 0x020386AE) and "vanilla" or "AP+0x14"
        if bval ~= aval then
            local marker = ""
            if nameAdj ~= "" then marker = string.format(" (or #%d = %s with -1 adjust)", aval-1, nameAdj) end
            print(string.format("    %s (%s): %d → %d  %s%s  ◀ CHANGED",
                hex(paddr), label, bval, aval,
                nameExact ~= "" and ("= " .. nameExact) or "unknown",
                marker))
        else
            print(string.format("    %s (%s): %d → %d  (no change)", hex(paddr), label, bval, aval))
        end
    end

    -- Report candidates (baseline invalid → battle valid)
    if #candidates > 0 then
        -- Sort by address, prioritize 0x02038xxx range
        table.sort(candidates, function(a, b)
            local a_hi = (a.addr >= 0x02038000 and a.addr < 0x0203A000) and 0 or 1
            local b_hi = (b.addr >= 0x02038000 and b.addr < 0x0203A000) and 0 or 1
            if a_hi ~= b_hi then return a_hi < b_hi end
            return a.addr < b.addr
        end)
        print(string.format("\n  %d addresses changed from invalid → valid trainer ID:", #candidates))
        local show = math.min(#candidates, 20)
        for i = 1, show do
            local c = candidates[i]
            local adj = c.adjusted and " (idx-1 adjusted)" or ""
            local region = (c.addr >= 0x02038000 and c.addr < 0x0203A000) and " ◀ battle globals region" or ""
            print(string.format("    %s: was %d, now %d = %s%s%s",
                hex(c.addr), c.baseline_val, c.id, c.name, adj, region))
        end
        if #candidates > 20 then
            print(string.format("    ... and %d more", #candidates - 20))
        end
    else
        print("\n  No addresses went from invalid → valid trainer ID.")
        print("  (The variable may retain stale values on overworld.)")
    end

    -- Narrow focus: addresses in 0x02038000-0x0203A000 that changed
    local battle_region = {}
    for addr, info in pairs(changed) do
        if addr >= 0x02038000 and addr < 0x0203A000 then
            battle_region[#battle_region + 1] = {addr=addr, id=info.id, name=info.name, adjusted=info.adjusted}
        end
    end
    if #battle_region > 0 then
        table.sort(battle_region, function(a, b) return a.addr < b.addr end)
        print(string.format("\n  Battle globals region (0x02038000-0x0203A000): %d changed addresses", #battle_region))
        for _, c in ipairs(battle_region) do
            local adj = c.adjusted and " (idx-1)" or ""
            print(string.format("    %s = %d (%s)%s", hex(c.addr), c.id, c.name, adj))
        end
    end

    print("\n  ★ Which trainer were you fighting? Look for that name above.")
    print("    If a name matches with '(idx-1 adjusted)', the game uses 1-based IDs")
    print("    and the server lookup needs trainer_id - 1.")
    printDiv()
end

-- Interactive loop
local prev_keys = {}
while true do
    emu.frameadvance()
    local keys = input.get()
    local function pressed(k) return keys[k] and not prev_keys[k] end

    if pressed("F1") then
        if scanPhase == "baseline" then
            print("  [Baseline] Scanning overworld state...")
            baseline = scanRegion()
            scanPhase = "battle"
            print("  Baseline captured. Now enter a trainer battle and press F1.")
        elseif scanPhase == "battle" then
            print("  [Battle] Scanning battle state...")
            battle = scanRegion()
            scanPhase = "done"
            analyzeResults()
        else
            print("  Both scans complete. See results above. Press F3 to exit.")
        end
    end

    if pressed("F2") then
        print(string.format("\n  Status: phase=%s  baseline=%s  battle=%s",
            scanPhase, baseline and "done" or "pending", battle and "done" or "pending"))
    end

    if pressed("F3") then
        print("\n  Exiting trainer discovery.")
        break
    end

    prev_keys = keys
end

printDiv()
print("  Done!")
