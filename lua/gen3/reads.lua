-- lua/gen3/reads.lua — profile-driven Gen 3 (FRLG + Radical Red) record reads.
--
-- No BizHawk globals and no literal addresses: every address is a field of the pack's
-- profile.json (`profile.ram` / `profile.derived`), and every byte arrives through the
-- injected read-only `io`:
--
--   io.read_u8(addr)  io.read_u16(addr)  io.read_u32(addr)   -- GBA flat bus, little-endian
--   io.read_bytes(addr, len) -> {b1, ..., blen}
--
-- The numbers below are RECORD GEOMETRY (sizeof(struct Pokemon) and friends,
-- include/pokemon.h#L8-L141 at the pinned pret commit c75f3523), not addresses; a pack may
-- override any of them through profile.derived. The pack does not ship them today — see the
-- card report's "missing pack fields".
--
-- The Python twin of this file is server/adapters/gen3_codec.py (the PYDEC oracle, PLAN
-- §5.7): the two are written from pret independently and must agree byte for byte.
local R = {}

R.PARTY_MON_SIZE = 100          -- sizeof(struct Pokemon)
R.BOX_MON_SIZE = 80             -- sizeof(struct BoxPokemon)
R.COMPRESSED_MON_SIZE = 0x3A    -- CFRU CompressedPokemon (RR boxes)
R.SECURE_OFFSET = 0x20          -- BoxPokemon.secure
R.SUBSTRUCT_SIZE = 12           -- NUM_SUBSTRUCT_BYTES
R.NICKNAME_LEN, R.OT_NAME_LEN = 10, 7
R.NAME_EOS = 0xFF               -- charmap.txt: '$' = FF
R.PARTY_CAPACITY = 6            -- PARTY_SIZE
R.MONS_PER_BOX = 30             -- IN_BOX_COUNT

-- src/pokemon.c GetSubstruct: entry [personality % 24] gives the POSITION of the
-- Growth / Attacks / EVs / Misc substruct inside the 48-byte secure block (0-based).
R.SUBSTRUCT_ORDER = {
    [0] = {0,1,2,3}, {0,1,3,2}, {0,2,1,3}, {0,3,1,2}, {0,2,3,1}, {0,3,2,1},
    {1,0,2,3}, {1,0,3,2}, {2,0,1,3}, {3,0,1,2}, {2,0,3,1}, {3,0,2,1},
    {1,2,0,3}, {1,3,0,2}, {2,1,0,3}, {3,1,0,2}, {2,3,0,1}, {3,2,0,1},
    {1,2,3,0}, {1,3,2,0}, {2,1,3,0}, {3,1,2,0}, {2,3,1,0}, {3,2,1,0},
}
-- CFRU (and therefore Radical Red) stores the four substructs in fixed order and does not
-- encrypt them: profile.derived.CFRU_NO_ENCRYPT.
R.FIXED_ORDER = {0, 1, 2, 3}

-- ── the one glyph table ──────────────────────────────────────────────────────────────
-- English FR font, pret charmap.txt at the pinned commit. Letters and digits are
-- contiguous runs ('A'=BB, 'a'=D5, '0'=A1) so they are built, not typed; everything else is
-- transcribed below. An unmapped byte decodes to a reversible <$XX> token.
local EXTRA = {
    [0x00] = " ",
    [0x01] = "À", [0x02] = "Á", [0x03] = "Â", [0x04] = "Ç", [0x05] = "È", [0x06] = "É",
    [0x07] = "Ê", [0x08] = "Ë", [0x09] = "Ì", [0x0B] = "Î", [0x0C] = "Ï", [0x0D] = "Ò",
    [0x0E] = "Ó", [0x0F] = "Ô", [0x10] = "Œ", [0x11] = "Ù", [0x12] = "Ú", [0x13] = "Û",
    [0x14] = "Ñ", [0x15] = "ß", [0x16] = "à", [0x17] = "á", [0x19] = "ç", [0x1A] = "è",
    [0x1B] = "é", [0x1C] = "ê", [0x1D] = "ë", [0x1E] = "ì", [0x20] = "î", [0x21] = "ï",
    [0x22] = "ò", [0x23] = "ó", [0x24] = "ô", [0x25] = "œ", [0x26] = "ù", [0x27] = "ú",
    [0x28] = "û", [0x29] = "ñ", [0x2A] = "º", [0x2B] = "ª",
    [0x2D] = "&", [0x2E] = "+", [0x35] = "=", [0x36] = ";", [0x51] = "¿", [0x52] = "¡",
    [0x5A] = "Í", [0x5B] = "%", [0x5C] = "(", [0x5D] = ")",
    [0x68] = "â", [0x6F] = "í", [0x85] = "<", [0x86] = ">",
    [0xAB] = "!", [0xAC] = "?", [0xAD] = ".", [0xAE] = "-", [0xAF] = "·", [0xB0] = "…",
    [0xB1] = "“", [0xB2] = "”", [0xB3] = "‘", [0xB4] = "’", [0xB5] = "♂", [0xB6] = "♀",
    [0xB7] = "¥", [0xB8] = ",", [0xB9] = "×", [0xBA] = "/",
    [0xEF] = "▶", [0xF0] = ":", [0xF1] = "Ä", [0xF2] = "Ö", [0xF3] = "Ü", [0xF4] = "ä",
    [0xF5] = "ö", [0xF6] = "ü",
}

-- {terminator, glyphs[0..255], codes[glyph] = byte}. Built once; a pack that ships its own
-- charmap.lua supplies profile.charmap and that object is used instead.
function R.charmap(profile)
    local cm = profile and profile.charmap
    if not cm then
        if not R.FR then
            local glyphs = {}
            for b = 0, 255 do
                if EXTRA[b] then glyphs[b] = EXTRA[b]
                elseif b >= 0xBB and b <= 0xD4 then glyphs[b] = string.char(65 + b - 0xBB)
                elseif b >= 0xD5 and b <= 0xEE then glyphs[b] = string.char(97 + b - 0xD5)
                elseif b >= 0xA1 and b <= 0xAA then glyphs[b] = string.char(48 + b - 0xA1)
                else glyphs[b] = string.format("<$%02X>", b) end
            end
            R.FR = { terminator = R.NAME_EOS, glyphs = glyphs }
        end
        cm = R.FR
    end
    assert(type(cm.glyphs) == "table" and type(cm.terminator) == "number",
           "charmap needs glyphs + terminator")
    if not cm.codes then
        local codes = {}
        for b = 0, 255 do
            local g = cm.glyphs[b]
            if g and codes[g] == nil then codes[g] = b end
        end
        cm.codes = codes
    end
    return cm
end

-- ── byte helpers (1-based arrays, 0-based struct offsets) ────────────────────────────
local function u(b, off, size)
    local value, mul = 0, 1
    for i = 0, size - 1 do
        local byte = b[off + i + 1]
        if type(byte) ~= "number" then return nil end
        value = value + byte * mul
        mul = mul * 256
    end
    return value
end
local function take(b, off, len)
    local out = {}
    for i = 1, len do out[i] = b[off + i] end
    return out
end
-- src/pokemon.c EncryptBoxMon/DecryptBoxMon: XOR every 32-bit word with personality ^ otId.
local function xor_words(bytes, key)
    local out = {}
    for i = 0, #bytes - 1, 4 do
        local word = u(bytes, i, 4) ~ key
        for j = 0, 3 do out[i + j + 1] = (word >> (8 * j)) & 0xFF end
    end
    return out
end
-- src/pokemon.c CalculateBoxMonChecksum: u16 sum of the 24 decrypted halfwords.
function R.secure_checksum(plain)
    local total = 0
    for i = 0, #plain - 1, 2 do total = total + u(plain, i, 2) end
    return total & 0xFFFF
end

-- CFRU CompressedPokemon (0x3A) -> BoxPokemon (0x50). Fields CFRU does not store
-- (checksum, PP, contest, ribbons) stay zero, which is why RR records carry no checksum.
function R.expand_compressed_mon(raw)
    if #raw ~= R.COMPRESSED_MON_SIZE then
        return nil, "compressed record length disagrees with profile"
    end
    local out = {}
    for i = 1, R.BOX_MON_SIZE do out[i] = 0 end
    local function copy(dst, src, len)
        for i = 1, len do out[dst + i] = raw[src + i] end
    end
    copy(0x00, 0x00, 0x1C)      -- header verbatim
    copy(0x20, 0x1C, 0x0B)      -- Growth
    local packed = u(raw, 0x27, 5)
    for i = 0, 3 do             -- four 10-bit move ids -> u16 each
        local move = (packed >> (10 * i)) & 0x3FF
        out[0x2C + i * 2 + 1] = move & 0xFF
        out[0x2C + i * 2 + 2] = (move >> 8) & 0xFF
    end
    copy(0x38, 0x2C, 6)         -- EVs
    copy(0x44, 0x32, 8)         -- Misc head
    return out
end

-- BizHawk's API members are `userdata`, not `function` (and so are lupa's Python stubs), so
-- callability is checked by type class, never by `type(f) == "function"`.
function R.callable(v)
    local t = type(v)
    return t == "function" or t == "userdata" or t == "table"
end

function R.new(profile, io)
    assert(type(profile) == "table" and type(profile.ram) == "table"
           and type(profile.derived) == "table", "Gen 3 title profile required")
    assert(type(io) == "table" and R.callable(io.read_u8) and R.callable(io.read_u32)
           and R.callable(io.read_bytes), "injected read-only byte reader required")
    local a, d = profile.ram, profile.derived
    local cm = R.charmap(profile)
    -- Radical Red / CFRU: fixed substruct order, no XOR, no BoxPokemon checksum.
    local rr = d.CFRU_NO_ENCRYPT == true
    local party_capacity = d.PARTY_CAPACITY or R.PARTY_CAPACITY
    local mons_per_box = d.MONS_PER_BOX or R.MONS_PER_BOX
    local r = { charmap = cm, rr = rr, party_capacity = party_capacity,
                mons_per_box = mons_per_box }

    function r.decode_name(bytes)
        local out = {}
        for i = 1, #bytes do
            if bytes[i] == cm.terminator then break end
            out[#out + 1] = cm.glyphs[bytes[i]] or string.format("<$%02X>", bytes[i])
        end
        return table.concat(out)
    end

    -- include/pokemon.h: the four 12-byte substructs, already put back in
    -- Growth / Attacks / EVs / Misc order.
    local function decode_secure(g, at, e, m)
        local ivs, met = u(m, 4, 4), u(m, 2, 2)
        local moves, pp, contest = {}, {}, {}
        for i = 0, 3 do moves[i + 1] = u(at, i * 2, 2) end
        for i = 0, 3 do pp[i + 1] = at[9 + i] end
        for i = 0, 5 do contest[i + 1] = e[7 + i] end
        return {
            species = u(g, 0, 2), held_item = u(g, 2, 2), experience = u(g, 4, 4),
            pp_bonuses = g[9], friendship = g[10], growth_filler = u(g, 10, 2),
            moves = moves, pp = pp,
            evs = { hp = e[1], attack = e[2], defense = e[3], speed = e[4],
                    sp_attack = e[5], sp_defense = e[6] },
            contest = contest,
            pokerus = m[1], met_location = m[2],
            met_level = met & 0x7F, met_game = (met >> 7) & 0x0F,
            pokeball = (met >> 11) & 0x0F, ot_gender = (met >> 15) & 1,
            ivs = { hp = ivs & 0x1F, attack = (ivs >> 5) & 0x1F,
                    defense = (ivs >> 10) & 0x1F, speed = (ivs >> 15) & 0x1F,
                    sp_attack = (ivs >> 20) & 0x1F, sp_defense = (ivs >> 25) & 0x1F },
            is_egg = (ivs >> 30) & 1, ability_num = (ivs >> 31) & 1,
            ribbons = u(m, 8, 4),
        }
    end

    -- include/pokemon.h: the party-only tail after the 80-byte BoxPokemon.
    local PARTY_TAIL = { { "status", 0x50, 4 }, { "level", 0x54, 1 }, { "mail", 0x55, 1 },
                         { "hp", 0x56, 2 }, { "max_hp", 0x58, 2 }, { "attack", 0x5A, 2 },
                         { "defense", 0x5C, 2 }, { "speed", 0x5E, 2 },
                         { "sp_attack", 0x60, 2 }, { "sp_defense", 0x62, 2 } }

    local function decode_mon(raw, party)
        local want = party and R.PARTY_MON_SIZE or R.BOX_MON_SIZE
        if #raw ~= want then return nil, "record length disagrees with profile" end
        local personality, ot_id = u(raw, 0x00, 4), u(raw, 0x04, 4)
        if not personality or not ot_id then return nil, "record is not a byte array" end
        local secure = take(raw, R.SECURE_OFFSET, 4 * R.SUBSTRUCT_SIZE)
        local plain = rr and secure or xor_words(secure, personality ~ ot_id)
        local order = rr and R.FIXED_ORDER or R.SUBSTRUCT_ORDER[personality % 24]
        local ordered = {}
        for kind = 1, 4 do
            ordered[kind] = take(plain, order[kind] * R.SUBSTRUCT_SIZE, R.SUBSTRUCT_SIZE)
        end
        local flags, stored = raw[0x13 + 1], u(raw, 0x1C, 2)
        local nick = take(raw, 0x08, R.NICKNAME_LEN)
        local ot = take(raw, 0x14, R.OT_NAME_LEN)
        local mon = {
            personality = personality, ot_id = ot_id,
            nickname = r.decode_name(nick), nickname_bytes = nick,
            language = raw[0x12 + 1],
            is_bad_egg = flags & 1, has_species = (flags >> 1) & 1,
            is_egg_flag = (flags >> 2) & 1, block_box_rs = (flags >> 3) & 1,
            flags_unused = (flags >> 4) & 0x0F,
            ot_name = r.decode_name(ot), ot_name_bytes = ot,
            markings = raw[0x1B + 1], checksum = stored, unknown = u(raw, 0x1E, 2),
            box = not party,
        }
        for key, value in pairs(decode_secure(ordered[1], ordered[2], ordered[3], ordered[4])) do
            mon[key] = value
        end
        -- CFRU never validates the BoxPokemon checksum and leaves the field zero, so in RR
        -- mode there is nothing to check: the key is absent, not false.
        if not rr then mon.checksum_ok = R.secure_checksum(plain) == stored end
        if party then
            for _, field in ipairs(PARTY_TAIL) do
                mon[field[1]] = u(raw, field[2], field[3])
            end
        end
        return mon
    end
    function r.decode_party_mon(raw) return decode_mon(raw, true) end
    function r.decode_box_mon(raw) return decode_mon(raw, false) end

    -- docs/protocol.md mon key, as the shipped Gen 3 client spells it
    -- (lua/memory_gba.lua:651): PERSONALITY:OTID, upper-case hex, eight digits each.
    function r.key(mon) return string.format("%08X:%08X", mon.personality, mon.ot_id) end

    -- SaveBlock pointers. gSaveBlock1Ptr/gSaveBlock2Ptr are relocated by the engine, so the
    -- pointer is dereferenced on every call and never cached across frames.
    local function deref(name)
        local addr = a[name]
        if not addr then return nil, "profile has no " .. name end
        local ptr = io.read_u32(addr)
        if not ptr or ptr == 0 then return nil, name .. " is null" end
        return ptr
    end
    function r.read_sb1() return deref("SB1_PTR_ADDR") end
    function r.read_sb2() return deref("SB2_PTR_ADDR") end

    local function party_base()
        if d.PARTY_IN_SB1 then
            local sb1, why = r.read_sb1()
            if not sb1 then return nil, why end
            local off = d.SB1_PARTY_BASE_OFFSET
            if not off then return nil, "profile has no derived.SB1_PARTY_BASE_OFFSET" end
            return sb1 + off
        end
        if not a.PARTY_BASE then return nil, "profile has no ram.PARTY_BASE" end
        return a.PARTY_BASE
    end
    r.party_base = party_base

    function r.read_party()
        if not a.PARTY_COUNT_ADDR then return nil, "profile has no ram.PARTY_COUNT_ADDR" end
        local count = io.read_u8(a.PARTY_COUNT_ADDR)
        if count > party_capacity then return nil, "party count exceeds capacity" end
        local base, why = party_base()
        if not base then return nil, why end
        local out = {}
        for slot = 0, count - 1 do
            local mon, bad = r.decode_party_mon(
                io.read_bytes(base + slot * R.PARTY_MON_SIZE, R.PARTY_MON_SIZE))
            if not mon then return nil, bad end
            mon.slot = slot
            out[#out + 1] = mon
        end
        return out
    end

    -- One PC box, by zero-based index. RR keeps 25 boxes of 30 CFRU-compressed records at
    -- the scattered EWRAM bases in derived.CFRU_BOX_BASES; vanilla FRLG keeps 14 boxes of
    -- 80-byte records inside gPokemonStorage, whose base the pack does not name yet.
    function r.read_box(index)
        if type(index) ~= "number" or index ~= math.floor(index) or index < 0 then
            return nil, "box index must be a non-negative integer"
        end
        local base, stride, compressed
        if d.CFRU_COMPRESSED_BOX then
            local bases = d.CFRU_BOX_BASES
            if type(bases) ~= "table" then
                return nil, "profile has no derived.CFRU_BOX_BASES"
            end
            base = bases[index + 1]
            if not base then return nil, "box index outside profile" end
            stride, compressed = d.COMPRESSED_MON_SIZE or R.COMPRESSED_MON_SIZE, true
        else
            if not a.POKEMON_STORAGE_BASE then
                return nil, "profile has no ram.POKEMON_STORAGE_BASE"
            end
            if not d.BOX_DATA_OFFSET then
                return nil, "profile has no derived.BOX_DATA_OFFSET"
            end
            if index >= (d.BOXES_PER_STORE or 0) then return nil, "box index outside profile" end
            base = a.POKEMON_STORAGE_BASE + d.BOX_DATA_OFFSET
                   + index * mons_per_box * R.BOX_MON_SIZE
            stride, compressed = R.BOX_MON_SIZE, false
        end
        local raw = io.read_bytes(base, mons_per_box * stride)
        local out = {}
        for slot = 0, mons_per_box - 1 do
            local record = take(raw, slot * stride, stride)
            if compressed then
                local expanded, why = R.expand_compressed_mon(record)
                if not expanded then return nil, why end
                record = expanded
            end
            local mon, bad = r.decode_box_mon(record)
            if not mon then return nil, bad end
            mon.slot, mon.box_index = slot, index
            out[#out + 1] = mon
        end
        return out
    end

    return r
end

return R
