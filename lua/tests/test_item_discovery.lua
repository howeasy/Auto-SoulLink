--[[
  lua/test_item_discovery.lua — gItems Table Scanner (RR / CFRU)
  ===============================================================
  Finds the CFRU/RR gItems ROM table by searching for known item names
  encoded in Gen III character format, then dumps all item ID → display name
  mappings.  Designed for Radical Red; also works on vanilla FRLG as fallback.

  CFRU/RR ROMs contain TWO gItems tables: the original vanilla one (still
  present but unreferenced) and the new CFRU table with extended items.
  The script scores candidates and prefers the CFRU table when present,
  using probe IDs (55=Life Orb, 56=Toxic Orb, etc.) that are empty
  placeholders in vanilla but have real names in CFRU.

  The struct Item layout (vanilla FRLG, 44 bytes):
    +0x00  u8  name[14]          ← Gen III encoded, 0xFF terminated
    +0x0E  u16 itemId
    +0x10  u16 price
    +0x12  u8  holdEffect
    +0x13  u8  holdEffectParam
    +0x14  u32 *description      ← ROM pointer
    +0x18  u8  importance
    +0x19  u8  unk19
    +0x1A  u8  pocket
    +0x1B  u8  type
    +0x1C  u32 fieldUseFunc      ← ROM pointer
    +0x20  u8  battleUsage
    +0x21  u8  pad[3]
    +0x24  u32 battleUseFunc     ← ROM pointer
    +0x28  u8  secondaryId
    +0x29  u8  pad[3]

  CFRU/RR extends name[] to 20 chars and adds a flingPower field,
  giving an entry size of ~56 bytes.  The script auto-detects entry size.

  HOW TO USE:
    1. Load FireRed/LeafGreen (vanilla or RR) in BizHawk, load a save.
    2. Load this script in the Lua Console.
    3. Results are saved to data/rr_items.json (JSON) and
       data/rr_items_pydict.txt (Python ITEM_NAMES snippet).
       Also printed to the BizHawk console.

  OUTPUT FORMAT (JSON):
    { "base": "0x08XXXXXX", "entry_size": 44, "name_cap": 14, "count": N,
      "items": { "1": "Master Ball", "4": "Poké Ball", ... } }
--]]

local ROM_BASE = 0x08000000

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
DECODE[0xAE] = "-"
DECODE[0xB0] = "\226\128\166"  -- ellipsis (…)
DECODE[0xB1] = "\226\128\156"  -- left double quote (")
DECODE[0xB2] = "\226\128\157"  -- right double quote (")
DECODE[0xB3] = "\226\128\152"  -- left single quote (')
DECODE[0xB4] = "\226\128\153"  -- apostrophe / right single quote (')
DECODE[0xB5] = "\226\153\130"  -- male sign (♂)
DECODE[0xB6] = "\226\153\128"  -- female sign (♀)
DECODE[0xB8] = ","
DECODE[0xBA] = "/"
-- Accented characters (0x01-0x29)
DECODE[0x01]="A\204\128" DECODE[0x02]="A\204\129" DECODE[0x03]="A\204\130"
DECODE[0x04]="C\204\167" DECODE[0x05]="E\204\128" DECODE[0x06]="E\204\129"
DECODE[0x07]="E\204\130" DECODE[0x08]="E\204\136" DECODE[0x09]="I\204\128"
DECODE[0x0A]="I\204\130" DECODE[0x0B]="I\204\136" DECODE[0x0C]="O\204\128"
DECODE[0x0D]="O\204\129" DECODE[0x0E]="O\204\130" DECODE[0x0F]="O\204\136"
DECODE[0x10]="U\204\128" DECODE[0x11]="U\204\129" DECODE[0x12]="U\204\130"
DECODE[0x13]="U\204\136" DECODE[0x15]="a\204\128" DECODE[0x16]="a\204\129"
DECODE[0x17]="a\204\130" DECODE[0x18]="c\204\167" DECODE[0x19]="e\204\128"
DECODE[0x1A]="\195\169"   -- é  (UTF-8: C3 A9)  — the one that matters (Poké Ball)
DECODE[0x1B]="e\204\130" DECODE[0x1C]="e\204\136"
DECODE[0x28]="\195\145"   -- Ñ
DECODE[0x29]="\195\177"   -- ñ

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

local function decodeStr(addr, maxLen)
    local chars = {}
    for i = 0, maxLen - 1 do
        local b = memory.read_u8(addr + i, "System Bus")
        if b == 0xFF then break end
        local c = DECODE[b]
        if c then
            chars[#chars + 1] = c
        else
            chars[#chars + 1] = string.format("{%02X}", b)
        end
    end
    local s = table.concat(chars)
    -- Normalize: e+combining circumflex (U+0302) → é (common CFRU encoding)
    s = s:gsub("e\204\130", "\195\169")   -- e + U+0302 → é
    s = s:gsub("E\204\130", "\195\137")   -- E + U+0302 → É
    return s
end

-- ── Helpers ─────────────────────────────────────────────────────────────────

local function hex(n) return string.format("0x%08X", n) end
local function printDiv() print(string.rep("=", 70)) end
local function printLine() print(string.rep("-", 70)) end

local function detectRomEnd()
    local addr32 = ROM_BASE + 0x02000000 - 4
    local ok32, val32 = pcall(function()
        return memory.read_u32_le(addr32, "System Bus")
    end)
    if ok32 and val32 ~= 0 then return ROM_BASE + 0x02000000 end
    return ROM_BASE + 0x01000000
end

--- Scan ROM for a byte pattern on 4-byte alignment.  Returns list of addrs.
local function scanForBytes(pattern, romEnd, label)
    local results = {}
    local pLen = #pattern
    local total = romEnd - ROM_BASE
    local lastProgress = -1

    for addr = ROM_BASE + 0x200000, romEnd - pLen, 4 do
        -- Progress every 4 MB
        local mb4 = math.floor((addr - ROM_BASE) / (4 * 1024 * 1024))
        if mb4 ~= lastProgress then
            lastProgress = mb4
            if mb4 > 0 then
                print(string.format("  Scanning %s: %dMB / %dMB...",
                    label, mb4 * 4, total / (1024 * 1024)))
                emu.yield()
            end
        end
        -- Quick-reject on first byte
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

local function resolveOutputPath(filename)
    -- Strategy 1: debug.getinfo → ../data/<filename>
    local ok, info = pcall(debug.getinfo, 1, "S")
    if ok and info and info.source then
        local dir = info.source:match("^@?(.*[\\/])")
        if dir then
            for _, sep in ipairs({"\\", "/"}) do
                local p = dir .. ".." .. sep .. "data" .. sep .. filename
                local f = io.open(p, "w")
                if f then f:close(); return p end
            end
            local p = dir .. filename
            local f = io.open(p, "w")
            if f then f:close(); return p end
        end
    end
    -- Strategy 2: common relative paths
    for _, p in ipairs({"data/" .. filename, "data\\" .. filename, filename}) do
        local f = io.open(p, "w")
        if f then f:close(); return p end
    end
    return nil
end

-- ── Main discovery ──────────────────────────────────────────────────────────

printDiv()
print("  SLINK ITEM DISCOVERY — gItems Table Scanner")
print("  Supports vanilla FRLG and Radical Red / CFRU")
printDiv()

local romEnd = detectRomEnd()
local romSizeMB = (romEnd - ROM_BASE) / (1024 * 1024)
local gc = ""
for i = 0, 3 do gc = gc .. string.char(memory.read_u8(0x080000AC + i, "System Bus")) end
print(string.format("[STEP 0] ROM: %s, %dMB (end = %s)", gc, romSizeMB, hex(romEnd)))

-- ── Step 1: Search for known item names ─────────────────────────────────────
printLine()
print("[STEP 1] Searching for known item names in ROM...")

-- Items whose name and position are stable across vanilla, CFRU, and RR.
-- We search for the encoded name + 0xFF terminator.
local KNOWN_ITEMS = {
    { name = "Master Ball", id = 1 },
    { name = "Ultra Ball",  id = 2 },
    { name = "Great Ball",  id = 3 },
    { name = "Potion",      id = 13 },
    { name = "Oran Berry",  id = 139 },
}

local allHits = {}   -- { {addr, name, id}, ... }

for _, ki in ipairs(KNOWN_ITEMS) do
    local pattern = encodeStr(ki.name)  -- includes 0xFF terminator
    local hits = scanForBytes(pattern, romEnd, ki.name)
    for _, addr in ipairs(hits) do
        allHits[#allHits + 1] = { addr = addr, name = ki.name, id = ki.id }
    end
    print(string.format("  %-14s  %d hit(s)", ki.name, #hits))
end

if #allHits == 0 then
    print("\n  ERROR: No item name strings found in ROM!")
    printDiv()
    return
end

-- ── Step 2: Determine gItems base and entry size ────────────────────────────
printLine()
print("[STEP 2] Determining gItems base and entry size...")

-- Strategy: For each "Master Ball" hit (expected at index 1), look for an
-- "Ultra Ball" hit (expected at index 2) nearby.  The distance = entry_size.
-- Then validate by checking that "Potion" (index 13) falls at the predicted
-- address.
--
-- CFRU / RR builds contain TWO gItems tables in ROM — the original vanilla
-- one (unreferenced but still present in the binary) and the new CFRU table
-- with extended items.  To prefer the CFRU table we score each candidate:
--   +1 for each vanilla check that passes  (Master Ball, Potion, Oran Berry)
--   +5 if CFRU-repurposed slots have real names  (ID 55 = Life Orb, etc.)

local base, entry_size, nameCap

-- Collect per-name hit lists for quick lookup
local hitsByName = {}
for _, h in ipairs(allHits) do
    hitsByName[h.name] = hitsByName[h.name] or {}
    hitsByName[h.name][#hitsByName[h.name] + 1] = h.addr
end

local mbHits = hitsByName["Master Ball"] or {}
local ubHits = hitsByName["Ultra Ball"]  or {}

-- CFRU repurposes vanilla placeholder IDs for new items.  In vanilla these
-- slots are empty; in CFRU/RR they have real names.  We check several:
--   55 (0x37) = Life Orb      56 (0x38) = Toxic Orb
--   57 (0x39) = Flame Orb     58 (0x3A) = Black Sludge
--   90 (0x5A) = Light Clay
local CFRU_PROBE_IDS = {55, 56, 57, 58, 90}

local bestBase, bestES, bestNC, bestScore = nil, nil, nil, -1

for _, mbAddr in ipairs(mbHits) do
    for _, ubAddr in ipairs(ubHits) do
        local es = ubAddr - mbAddr
        if es >= 28 and es <= 80 then                -- sane struct size
            local cb = mbAddr - es                    -- item 0 sits before item 1
            local nc = es >= 48 and 20 or 14
            local score = 0

            -- Vanilla checks
            if decodeStr(cb + 13 * es, nc)  == "Potion"     then score = score + 1 end
            if decodeStr(cb + 139 * es, nc) == "Oran Berry"  then score = score + 1 end
            if decodeStr(cb + 3 * es, nc)   == "Great Ball"  then score = score + 1 end

            if score >= 2 then   -- at least Potion + Oran Berry
                -- CFRU probe: count how many repurposed slots have a valid name
                local cfruHits = 0
                for _, pid in ipairs(CFRU_PROBE_IDS) do
                    local pname = decodeStr(cb + pid * es, nc)
                    if pname ~= "" and pname:sub(1,1) ~= "?" and pname:sub(1,1) ~= "{" then
                        cfruHits = cfruHits + 1
                    end
                end
                if cfruHits > 0 then score = score + 5 + cfruHits end

                print(string.format("    candidate %s  es=%d  score=%d  (cfru probes=%d/%d)",
                    hex(cb), es, score, cfruHits, #CFRU_PROBE_IDS))

                if score > bestScore then
                    bestBase  = cb
                    bestES    = es
                    bestNC    = nc
                    bestScore = score
                end
            end
        end
    end
end

base       = bestBase
entry_size = bestES
nameCap    = bestNC

if not base then
    print("  ERROR: Could not determine gItems layout!")
    print("  Make sure a FRLG / Radical Red ROM is loaded.")
    printDiv()
    return
end

local isCFRU = bestScore >= 7   -- vanilla checks(3) + cfru bonus(5+) = 8+
print(string.format("  gItems base  : %s  (score %d, %s)",
    hex(base), bestScore, isCFRU and "CFRU / RR" or "vanilla"))
print(string.format("  Entry size   : %d bytes", entry_size))
print(string.format("  Name capacity: %d chars", nameCap))

-- ── Step 3: Sanity checks ───────────────────────────────────────────────────
printLine()
print("[STEP 3] Sanity checks...")

local function check(id, expected)
    local name = decodeStr(base + id * entry_size, nameCap)
    local ok = (name == expected)
    print(string.format("  %s Item %3d = %-20s %s",
        ok and "\226\156\147" or "\226\156\151",   -- ✓ / ✗
        id, name, ok and "" or "(expected " .. expected .. ")"))
    return ok
end

check(1,   "Master Ball")
check(2,   "Ultra Ball")
check(3,   "Great Ball")
check(13,  "Potion")
check(139, "Oran Berry")
-- Show Poké Ball (item 4) — contains é (0x1A/0x1B) which is a good encoding test
local item4 = decodeStr(base + 4 * entry_size, nameCap)
print(string.format("  \194\183 Item   4 = %s  (Pok\195\169 Ball)", item4))

if isCFRU then
    print("  CFRU/RR probe items:")
    check(55,  "Dream Patch")   -- vanilla placeholder, CFRU repurposes
    check(457, "Charti Berry")  -- the item that triggered this investigation
end

-- ── Step 4: Scan all items ──────────────────────────────────────────────────
printLine()
print("[STEP 4] Scanning item table...")

local MAX_ID   = 1200       -- CFRU/RR can have ~700+; generous limit
local STOP_GAP = 20         -- stop after this many consecutive bad entries

-- A name is "good" if it contains only decoded characters (no {XX} escapes)
-- and is not empty.
local function isGoodName(name)
    if name == "" then return false end
    if name:find("{%x%x}") then return false end  -- contains unknown bytes
    return true
end

local items    = {}          -- id → name
local maxId    = 0
local badRun   = 0           -- consecutive empty OR garbage entries
local emptyCount = 0

for id = 0, MAX_ID do
    local addr = base + id * entry_size
    local name = decodeStr(addr, nameCap)

    -- Validate via the itemId field at struct offset +0x0E.
    -- In a well-formed gItems table, gItems[N].itemId == N.
    -- Once itemId stops matching, we've gone past the real table.
    local itemId = memory.read_u16_le(addr + 0x0E, "System Bus")
    local idMatch = (itemId == id)

    if not idMatch and id > 10 then
        -- itemId mismatch past the first few entries = end of table
        badRun = badRun + 1
        emptyCount = emptyCount + 1
        if badRun >= STOP_GAP then
            print(string.format("  (stopped at ID %d — itemId mismatch for %d consecutive entries)",
                id, STOP_GAP))
            break
        end
    elseif not isGoodName(name) then
        badRun = badRun + 1
        emptyCount = emptyCount + 1
        if badRun >= STOP_GAP then
            print(string.format("  (stopped at ID %d — %d consecutive empty/garbage entries)",
                id, STOP_GAP))
            break
        end
    else
        badRun = 0
        items[id] = name
        if id > maxId then maxId = id end
    end

    -- Progress every 200 items
    if id > 0 and id % 200 == 0 then
        print(string.format("  Scanned %d / %d IDs...", id, MAX_ID))
        emu.yield()
    end
end

-- Sort IDs
local ids = {}
for id in pairs(items) do ids[#ids + 1] = id end
table.sort(ids)

local namedCount = #ids
print(string.format("  %d named items, %d empty/placeholder  (highest ID: %d)",
    namedCount, emptyCount, maxId))

-- Show a small sample in the console (first 10 + last 10)
print("\n  Sample (first 10):")
for i = 1, math.min(10, #ids) do
    print(string.format("    %4d  %s", ids[i], items[ids[i]]))
end
if #ids > 20 then
    print(string.format("    ... (%d more — see data/rr_items.json for full list)", #ids - 20))
    print("\n  Sample (last 10):")
    for i = #ids - 9, #ids do
        print(string.format("    %4d  %s", ids[i], items[ids[i]]))
    end
elseif #ids > 10 then
    print(string.format("    ... and %d more", #ids - 10))
end

-- ── Step 5: Save results ────────────────────────────────────────────────────
printLine()
print("[STEP 5] Saving results...")

-- 5a. JSON output (machine-readable, matches trainer discovery format)
local parts = {}
parts[#parts + 1] = "{"
parts[#parts + 1] = string.format('  "game_code": "%s",', gc)
parts[#parts + 1] = string.format('  "base": "%s",', hex(base))
parts[#parts + 1] = string.format('  "entry_size": %d,', entry_size)
parts[#parts + 1] = string.format('  "name_cap": %d,', nameCap)
parts[#parts + 1] = string.format('  "count": %d,', namedCount)
parts[#parts + 1] = string.format('  "highest_id": %d,', maxId)
parts[#parts + 1] = '  "items": {'

local first = true
for _, id in ipairs(ids) do
    if not first then parts[#parts + 1] = "," end
    first = false
    local safeName = items[id]:gsub('"', '\\"')
    parts[#parts + 1] = string.format('    "%d": "%s"', id, safeName)
end

parts[#parts + 1] = "  }"
parts[#parts + 1] = "}"

local json = table.concat(parts, "\n")

local jsonPath = resolveOutputPath("rr_items.json")
local jsonSaved = false
if jsonPath then
    local f = io.open(jsonPath, "w")
    if f then
        f:write(json)
        f:close()
        print("  JSON  → " .. jsonPath)
        jsonSaved = true
    end
end

-- 5b. Python dict output (paste-ready for server.py ITEM_NAMES)
local pyParts = {}
pyParts[#pyParts + 1] = "# Auto-generated by test_item_discovery.lua"
pyParts[#pyParts + 1] = string.format("# ROM: %s, gItems: %s, entry: %d bytes, names: %d chars",
    gc, hex(base), entry_size, nameCap)
pyParts[#pyParts + 1] = string.format("# %d named items, highest ID: %d\n", namedCount, maxId)
pyParts[#pyParts + 1] = "ITEM_NAMES: dict[int, str] = {"

for _, id in ipairs(ids) do
    local safeName = items[id]:gsub('"', '\\"')
    pyParts[#pyParts + 1] = string.format('    %d:"%s",', id, safeName)
end

pyParts[#pyParts + 1] = "}"

local pyText = table.concat(pyParts, "\n")

local pyPath = resolveOutputPath("rr_items_pydict.txt")
local pySaved = false
if pyPath then
    local f = io.open(pyPath, "w")
    if f then
        f:write(pyText)
        f:close()
        print("  Python → " .. pyPath)
        pySaved = true
    end
end

if not jsonSaved and not pySaved then
    print("  Could not write files.  Copy from console above.")
end

-- ── Summary ─────────────────────────────────────────────────────────────────
printDiv()
print(string.format("  gItems = %s  (%d entries, %d-byte stride, %s)",
    hex(base), namedCount, entry_size, isCFRU and "CFRU/RR" or "vanilla"))
print(string.format("  Name field: %d chars", nameCap))
if isCFRU then
    print("  NOTE: This is the CFRU/RR item table (not vanilla).")
    print("  Use data/rr_items.json to update server ITEM_NAMES for RR runs.")
else
    print("  WARNING: Only the vanilla table was found.")
    print("  If running Radical Red, the CFRU table may not have been located.")
end
printDiv()
