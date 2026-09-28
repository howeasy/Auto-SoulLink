-- FRLG-R2b: a cached, read-only snapshot of the cartridge's table closure.
--
-- local RC = dofile(root .. "/lua/gen3/rom_content.lua")
-- local content = RC.new(tbl, io)
-- local payload, why = content:payload()   -- nil + reason on ANY failure
--
-- tbl = {
--   gTrainers = {address = <GBA address>, count = <trainer rows>},
--   gWildMonHeaders = {address = ..., count = <headers INCLUDING sentinel>},
--   gEvolutionTable = {address = ..., count = <species rows, five evos each>},
--   gSpeciesInfo = {address = ..., count = <species rows>},
--   gTrainerClassNames = {address = ..., count = <13-byte names>},
--   rom_size = <optional file size; otherwise the 32 MiB GBA ROM window>,
-- }
-- A descriptor may additionally carry size; it must equal count * record stride.
-- Addresses use the same flat GBA ROM bus as gen3/reads.lua and gen3_world.py:
-- io.read_u8(address), restricted here to 0x08000000..0x09FFFFFF. The harness's
-- read_u16[_le]/read_u32[_le] are not needed: pointers come from the exact bytes
-- already captured, so the walked pointer and the shipped pointer cannot differ.
-- An IO wrapper for BizHawk's ROM domain subtracts 0x08000000 from that address.
--
-- payload = {tables = {{addr = <GBA address>, hex = <lowercase hex>}, ...},
--            fingerprint = <lowercase SHA-1 of concatenated raw blob bytes>}
-- Regions are sorted by ascending address; overlaps and adjacent ranges merge.
-- No gap bytes are shipped. The fingerprint excludes addresses and hex encoding,
-- and uses precisely that array order. Python's sparse input is simply
-- {row["addr"]: bytes.fromhex(row["hex"]) for row in payload["tables"]}.
-- A successful payload, or a failure reason, is built once and cached per object.
-- Treat the returned table as immutable; create a new object for another ROM.
--
-- SOURCE: pret/pokefirered@c75f352304d529f6ba92d4f74b9cf8b5c3810788,
-- include/battle.h:71-128; include/wild_encounter.h:6-34;
-- include/pokemon.h:208-235,266-271; include/data.h:24.
-- Strides include the matching agbcc struct padding (Python twin:
-- server/adapters/gen3_rom_tables.py). No ROM table addresses live in this file.
local RC = {}
local ROM_BASE, ROM_LIMIT = 0x08000000, 0x0A000000
-- Transport/resource bounds, not game facts. Raw 1 MiB becomes 2 MiB of hex;
-- this leaves room under the existing 4 MiB hello frame limit.
local MAX_BYTES, MAX_REQUESTS = 1024 * 1024, 16384
local HEADS = {
    {"gTrainers", 40}, {"gWildMonHeaders", 20}, {"gEvolutionTable", 40},
    {"gSpeciesInfo", 28}, {"gTrainerClassNames", 13},
}
local PARTY_STRIDES = {[0] = 8, [1] = 16, [2] = 8, [3] = 16}
local WILD_SLOTS = {12, 5, 5, 10} -- land, water, rock smash, fishing
local HEX, CHAR = {}, {}
for byte = 0, 255 do
    HEX[byte], CHAR[byte] = string.format("%02x", byte), string.char(byte)
end

local function fail(reason) error(reason, 0) end
local function integer(value)
    return type(value) == "number" and value % 1 == 0
end
local function callable(value)
    local kind = type(value)
    return kind == "function" or kind == "userdata" or kind == "table"
end

-- SHA-1 over binary bytes, using Lua 5.3+ integer operations like gen3/reads.lua.
-- All additions and rotations are explicitly reduced to unsigned 32-bit words.
local function sha1(raw)
    local mask = 0xFFFFFFFF
    local function rol(word, bits)
        return ((word << bits) | (word >> (32 - bits))) & mask
    end
    local padded = raw .. "\x80" .. string.rep("\0", (55 - #raw) % 64)
        .. string.pack(">I8", #raw * 8)
    local h0, h1, h2, h3, h4 = 0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0
    for offset = 1, #padded, 64 do
        local w = {}
        for i = 0, 15 do w[i] = string.unpack(">I4", padded, offset + i * 4) end
        for i = 16, 79 do w[i] = rol(w[i - 3] ~ w[i - 8] ~ w[i - 14] ~ w[i - 16], 1) end
        local a, b, c, d, e = h0, h1, h2, h3, h4
        for i = 0, 79 do
            local f, k
            if i < 20 then f, k = (b & c) | ((~b) & d), 0x5A827999
            elseif i < 40 then f, k = b ~ c ~ d, 0x6ED9EBA1
            elseif i < 60 then f, k = (b & c) | (b & d) | (c & d), 0x8F1BBCDC
            else f, k = b ~ c ~ d, 0xCA62C1D6 end
            local next_a = (rol(a, 5) + f + e + k + w[i]) & mask
            a, b, c, d, e = next_a, a, rol(b, 30), c, d
        end
        h0, h1, h2, h3, h4 = (h0 + a) & mask, (h1 + b) & mask, (h2 + c) & mask,
            (h3 + d) & mask, (h4 + e) & mask
    end
    return string.format("%08x%08x%08x%08x%08x", h0, h1, h2, h3, h4)
end

local function build(tbl, io)
    if type(tbl) ~= "table" then fail("table descriptors required") end
    if type(io) ~= "table" or not callable(io.read_u8) then fail("io.read_u8 required") end
    local rom_size = tbl.rom_size
    if rom_size == nil then rom_size = ROM_LIMIT - ROM_BASE end
    if not integer(rom_size) or rom_size <= 0 or rom_size > ROM_LIMIT - ROM_BASE then
        fail("invalid ROM size")
    end
    local rom_end = ROM_BASE + rom_size
    local function check_span(address, size, label)
        if not integer(address) or not integer(size) or size <= 0 then
            fail(label .. ": invalid address or size")
        end
        if address < ROM_BASE or address >= rom_end or size > rom_end - address then
            fail(string.format("%s: out-of-range ROM pointer 0x%08x + %d", label, address, size))
        end
        if size > MAX_BYTES then fail(label .. ": ROM content byte budget exceeded") end
    end

    -- Validate every descriptor before touching IO. Counts are supplied by the
    -- pack; only fixed FR/LG struct geometry and transport limits are local.
    local heads = {}
    for _, definition in ipairs(HEADS) do
        local name, stride = definition[1], definition[2]
        local row = tbl[name]
        if type(row) ~= "table" or not integer(row.count) or row.count <= 0
            or row.count > MAX_BYTES // stride then
            fail(name .. ": invalid or missing table count")
        end
        local size = row.count * stride
        if row.size ~= nil and row.size ~= size then fail(name .. ": size/count mismatch") end
        check_span(row.address, size, name)
        heads[name] = {address = row.address, count = row.count, size = size}
    end

    local bytes, intervals, seen = {}, {}, {}
    local byte_count = 0
    local function capture(address, size, label)
        check_span(address, size, label)
        local key = tostring(address) .. ":" .. tostring(size)
        if seen[key] then return end
        if #intervals >= MAX_REQUESTS then fail("ROM content region budget exceeded") end
        seen[key] = true
        intervals[#intervals + 1] = {first = address, last = address + size - 1}
        for at = address, address + size - 1 do
            if bytes[at] == nil then
                if byte_count >= MAX_BYTES then fail("ROM content byte budget exceeded") end
                local value = io.read_u8(at)
                if not integer(value) or value < 0 or value > 255 then
                    fail(string.format("%s: ROM byte unavailable at 0x%08x", label, at))
                end
                bytes[at] = value
                byte_count = byte_count + 1
            end
        end
    end
    local function u32(address)
        return bytes[address] | (bytes[address + 1] << 8)
            | (bytes[address + 2] << 16) | (bytes[address + 3] << 24)
    end
    for _, definition in ipairs(HEADS) do
        local name = definition[1]
        capture(heads[name].address, heads[name].size, name)
    end

    local trainers = heads.gTrainers
    for id = 0, trainers.count - 1 do
        local address = trainers.address + id * 40
        local flags, count = bytes[address], bytes[address + 32]
        local stride = PARTY_STRIDES[flags]
        local label = "trainer[" .. id .. "].party"
        if not stride or count > 6 then fail(label .. ": invalid flags/count") end
        local pointer = u32(address + 36)
        if count > 0 then capture(pointer, count * stride, label)
        elseif pointer ~= 0 then capture(pointer, 1, label) end
    end

    local wild, terminated = heads.gWildMonHeaders, false
    for id = 0, wild.count - 1 do
        local address = wild.address + id * 20
        if bytes[address] == 0xFF then terminated = true; break end
        for habitat, count in ipairs(WILD_SLOTS) do
            local pointer = u32(address + habitat * 4)
            if pointer ~= 0 then
                local label = "wild[" .. id .. "].habitat[" .. habitat .. "]"
                capture(pointer, 8, label .. ".info")
                capture(u32(pointer + 4), count * 4, label .. ".slots")
            end
        end
    end
    if not terminated then fail("gWildMonHeaders: missing 0xFF map-group sentinel") end

    table.sort(intervals, function(a, b) return a.first < b.first end)
    local merged = {}
    for _, interval in ipairs(intervals) do
        local previous = merged[#merged]
        if previous and interval.first <= previous.last + 1 then
            previous.last = math.max(previous.last, interval.last)
        else
            merged[#merged + 1] = {first = interval.first, last = interval.last}
        end
    end
    local tables, raw_regions = {}, {}
    for _, interval in ipairs(merged) do
        local hex, raw = {}, {}
        for address = interval.first, interval.last do
            local byte = bytes[address]
            hex[#hex + 1], raw[#raw + 1] = HEX[byte], CHAR[byte]
        end
        tables[#tables + 1] = {addr = interval.first, hex = table.concat(hex)}
        raw_regions[#raw_regions + 1] = table.concat(raw)
    end
    return {tables = tables, fingerprint = sha1(table.concat(raw_regions))}
end

function RC.new(tbl, io)
    local obj, attempted, cached, reason = {}, false, nil, nil
    function obj:payload()
        if not attempted then
            attempted = true
            local ok, result = pcall(build, tbl, io)
            if ok then cached = result
            else reason = "rom_content: " .. tostring(result) end
        end
        if cached then return cached end
        return nil, reason
    end
    return obj
end

-- Reuse the same raw-byte digest for locally bound artifact receipts.
RC.sha1 = sha1
return RC
