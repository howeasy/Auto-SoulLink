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

-- P4 card C4-2a: engine-fixed struct geometry, shared by every title (vanilla and CFRU/RR
-- alike -- lua/memory_gba.lua's production isInBattle() uses this same HP offset on both).
-- include/pokemon.h:170-206 (pret/pokefirered@c75f3523) struct BattlePokemon.
R.BATTLE_MON_SIZE = 0x58        -- sizeof(struct BattlePokemon)
R.BATTLE_MON_HP_OFF = 0x28      -- BattlePokemon.hp (u16); .maxHP is HP_OFF + 4
-- include/global.h:400-404 struct ItemSlot { u16 itemId; u16 quantity; }.
R.ITEM_SLOT_SIZE = 4

-- Vanilla FR/LG relocate their save blocks on every load: SetSaveBlocksPointers
-- (pret/pokefirered src/load_save.c:68-78 at the pinned commit c75f3523) computes
--     offset = Random() & ((SAVEBLOCK_MOVE_RANGE - 1) & ~3)     -- :75
-- with SAVEBLOCK_MOVE_RANGE 128 (:15), i.e. a 4-byte-aligned offset in [0, 124], and adds it
-- to gSaveBlock2Ptr, gSaveBlock1Ptr AND gPokemonStoragePtr alike. The DMA pads that make the
-- slack are declared right there (:29, :32, :35). So a static base is never a live address:
-- the pointer is dereferenced on every read and the base is only a SANITY BOUND.
R.SAVEBLOCK_MOVE_RANGE = 128

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

-- `pointers` is the pack's write_checkpoint `pointers` block (Entry.build passes
-- parts.write_checkpoint.pointers), so the pointer symbols arrive as data like every other
-- address. When it is absent the equivalent profile.ram symbol is used instead.
function R.new(profile, io, pointers)
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

    -- SaveBlock / storage pointers. SetSaveBlocksPointers relocates all three on every load,
    -- so each is dereferenced on the call and never cached across frames.
    --   symbol    the write_checkpoint pointers key (gSaveBlock1Ptr, ...)
    --   ram_key   the equivalent profile.ram symbol, used when the pack ships no pointers
    --   base      optional static base for the cross-check; nil = null + alignment only
    local move_range = d.SAVEBLOCK_MOVE_RANGE or R.SAVEBLOCK_MOVE_RANGE
    local max_offset = move_range - 4        -- Random() & ((RANGE - 1) & ~3)
    local function pointer_address(symbol, ram_key)
        local entry = pointers and pointers[symbol]
        if entry and entry.address then return entry.address end
        return a[ram_key]
    end
    local function deref(symbol, ram_key, base)
        local addr = pointer_address(symbol, ram_key)
        if not addr then
            return nil, "neither write_checkpoint.pointers." .. symbol
                        .. " nor profile.ram." .. ram_key .. " names the pointer"
        end
        local ptr = io.read_u32(addr)
        if not ptr or ptr == 0 then return nil, symbol .. " is null" end
        if ptr % 4 ~= 0 then return nil, symbol .. " is not word aligned" end
        if base then
            local offset = ptr - base
            if offset < 0 or offset > max_offset then
                return nil, symbol .. " is outside the relocation window of its base"
            end
        end
        return ptr
    end
    r.deref = deref
    -- †The pack names no static base for SaveBlock1/2, so these get the null + alignment
    -- check only; add SB1_BASE/SB2_BASE to profile.ram to bound them the way storage is.
    function r.read_sb1() return deref("gSaveBlock1Ptr", "SB1_PTR_ADDR", a.SB1_BASE) end
    function r.read_sb2() return deref("gSaveBlock2Ptr", "SB2_PTR_ADDR", a.SB2_BASE) end
    function r.read_storage()
        return deref("gPokemonStoragePtr", "PSP_PTR_ADDR", a.POKEMON_STORAGE_BASE)
    end

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
    -- 80-byte records inside gPokemonStorage, which SetSaveBlocksPointers RELOCATES, so its
    -- live address is gPokemonStoragePtr and ram.POKEMON_STORAGE_BASE is only the bound.
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
            if not d.BOX_DATA_OFFSET then
                return nil, "profile has no derived.BOX_DATA_OFFSET"
            end
            if index >= (d.BOXES_PER_STORE or 0) then return nil, "box index outside profile" end
            local storage, why = r.read_storage()
            if not storage then return nil, why end
            base = storage + d.BOX_DATA_OFFSET + index * mons_per_box * R.BOX_MON_SIZE
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

    -- ── P4 card C4-2a: trainer / location / badges / bag / battle ────────────────────
    -- Every field here returns nil, reason when the pack has not pinned the address or
    -- offset it needs (so the gen3_rr pack, which does not carry most of these yet, keeps
    -- working exactly as it did before this card until its own evidence lands).

    -- SaveBlock2.playerTrainerId (u32 LE) + playerName (pret include/global.h:327-332;
    -- src/pokemon.c:1798-1801 for the little-endian assembly of the OT id).
    function r.read_trainer()
        local ot_off, name_off = d.SB2_OT_ID_OFFSET, d.SB2_NAME_OFFSET
        if not ot_off or not name_off then
            return nil, "profile has no derived.SB2_OT_ID_OFFSET/SB2_NAME_OFFSET"
        end
        local sb2, why = r.read_sb2()
        if not sb2 then return nil, why end
        local name = io.read_bytes(sb2 + name_off, R.OT_NAME_LEN)
        return { ot_id = io.read_u32(sb2 + ot_off), name = r.decode_name(name), name_bytes = name }
    end

    -- SaveBlock1.location (struct WarpData, pret include/global.h:392-398,759-762): signed
    -- mapGroup/mapNum bytes.
    function r.read_location()
        local group_off, num_off = d.SB1_LOCATION_MAP_GROUP_OFFSET, d.SB1_LOCATION_MAP_NUM_OFFSET
        if not group_off or not num_off then
            return nil, "profile has no derived.SB1_LOCATION_MAP_GROUP_OFFSET/MAP_NUM_OFFSET"
        end
        local sb1, why = r.read_sb1()
        if not sb1 then return nil, why end
        local function s8(v) return v >= 128 and v - 256 or v end
        return { map_group = s8(io.read_u8(sb1 + group_off)), map_num = s8(io.read_u8(sb1 + num_off)) }
    end

    -- SaveBlock1.flags[]: the 8 FLAG_BADGE0x_GET bits sit consecutively inside one byte
    -- (pret include/constants/flags.h:1324,1364-1371) -- bit i (0-based) is badge i+1.
    function r.read_badges()
        if not d.SB1_FLAGS_OFFSET or not d.SB1_BADGE_BYTE_OFFSET then
            return nil, "profile has no derived.SB1_FLAGS_OFFSET/SB1_BADGE_BYTE_OFFSET"
        end
        local sb1, why = r.read_sb1()
        if not sb1 then return nil, why end
        return io.read_u8(sb1 + d.SB1_FLAGS_OFFSET + d.SB1_BADGE_BYTE_OFFSET)
    end

    -- Poke Ball pocket: ItemSlot{u16 itemId, u16 quantity} (pret include/global.h:400-404).
    -- Vanilla FR/LG keep the pocket inside SaveBlock1 and XOR every quantity with the low 16
    -- bits of SaveBlock2.encryptionKey (src/item.c GetBagItemQuantity: `encryptionKey ^ *ptr`,
    -- truncated to u16 by the return type). CFRU/RR relocate the pocket to a fixed EWRAM
    -- address and leave quantities unencrypted (profile.derived.BAG_IN_EWRAM / BALL_POCKET_ENC).
    function r.read_balls()
        local count = d.SB1_BALL_POCKET_COUNT
        if not count then return nil, "profile has no derived.SB1_BALL_POCKET_COUNT" end
        local base
        if d.BAG_IN_EWRAM then
            if not a.BALL_POCKET_ADDR then return nil, "profile has no ram.BALL_POCKET_ADDR" end
            base = a.BALL_POCKET_ADDR
        else
            if not d.SB1_BALL_POCKET_OFFSET then
                return nil, "profile has no derived.SB1_BALL_POCKET_OFFSET"
            end
            local sb1, why = r.read_sb1()
            if not sb1 then return nil, why end
            base = sb1 + d.SB1_BALL_POCKET_OFFSET
        end
        local encrypted = d.BALL_POCKET_ENC ~= false
        local key = 0
        if encrypted then
            if not d.SB2_ENC_KEY_OFFSET then return nil, "profile has no derived.SB2_ENC_KEY_OFFSET" end
            local sb2, why = r.read_sb2()
            if not sb2 then return nil, why end
            key = io.read_u32(sb2 + d.SB2_ENC_KEY_OFFSET) & 0xFFFF
        end
        local total = 0
        for i = 0, count - 1 do
            local item = io.read_u16(base + i * R.ITEM_SLOT_SIZE)
            local qty = io.read_u16(base + i * R.ITEM_SLOT_SIZE + 2)
            if encrypted then qty = qty ~ key end
            if item ~= 0 then total = total + qty end
        end
        return { ball_count = total, has_pokeballs = total > 0 }
    end

    -- The enemy party, decoded exactly like r.read_party() (ram.ENEMY_BASE/ENEMY_COUNT_ADDR
    -- instead of the player's; the enemy array is never save-block-relocated).
    function r.read_enemy_party()
        if not a.ENEMY_COUNT_ADDR then return nil, "profile has no ram.ENEMY_COUNT_ADDR" end
        if not a.ENEMY_BASE then return nil, "profile has no ram.ENEMY_BASE" end
        local count = io.read_u8(a.ENEMY_COUNT_ADDR)
        if count > party_capacity then return nil, "enemy party count exceeds capacity" end
        local out = {}
        for slot = 0, count - 1 do
            local mon, bad = r.decode_party_mon(
                io.read_bytes(a.ENEMY_BASE + slot * R.PARTY_MON_SIZE, R.PARTY_MON_SIZE))
            if not mon then return nil, bad end
            mon.slot = slot
            out[#out + 1] = mon
        end
        return out
    end

    -- In-battle state, type flags, the trainer opponent id, the battler->party-slot mapping
    -- and the enemy party. Booleans whose mask/address the pack has not pinned come back
    -- absent rather than failing the whole read (gen3_rr today: is_trainer/is_doubles).
    function r.read_battle()
        if not (a.BATTLE_TYPE_ADDR and a.BATTLE_OUTCOME_ADDR and a.BATTLERS_COUNT_ADDR
                and a.BATTLER_PARTY_INDEXES_ADDR and a.ENEMY_COUNT_ADDR and a.ENEMY_BASE) then
            return nil, "profile has no ram.BATTLE_TYPE_ADDR/BATTLE_OUTCOME_ADDR/"
                       .. "BATTLERS_COUNT_ADDR/BATTLER_PARTY_INDEXES_ADDR/ENEMY_*"
        end
        local out = {}
        -- Two production-proven in-battle detectors (lua/memory_gba.lua M.isInBattle),
        -- selected by the pack: vanilla reads a gMain bit, CFRU/RR has no reliable gMain so
        -- it reads the live battler-0 BattlePokemon instead.
        -- profile.json's JSON `null` (e.g. RR's ram.GMAIN_ADDR) decodes to a truthy sentinel
        -- table, not Lua nil (lua/json_codec.lua), so "is this address present" is a type
        -- check, never a plain truthiness check.
        if d.OVERWORLD_MODE == "battle_outcome" and type(a.BATTLE_MONS_ADDR) == "number" then
            local max_hp = io.read_u16(a.BATTLE_MONS_ADDR + R.BATTLE_MON_HP_OFF + 4)
            out.in_battle = max_hp > 0 and io.read_u8(a.BATTLE_OUTCOME_ADDR) == 0
        elseif type(a.GMAIN_ADDR) == "number" and d.GMAIN_INBATTLE_OFFSET and d.GMAIN_INBATTLE_MASK then
            out.in_battle = (io.read_u8(a.GMAIN_ADDR + d.GMAIN_INBATTLE_OFFSET) & d.GMAIN_INBATTLE_MASK) ~= 0
        end
        out.outcome = io.read_u8(a.BATTLE_OUTCOME_ADDR)
        local type_flags = io.read_u32(a.BATTLE_TYPE_ADDR)
        if d.BATTLE_TYPE_TRAINER_MASK then out.is_trainer = (type_flags & d.BATTLE_TYPE_TRAINER_MASK) ~= 0 end
        if d.BATTLE_TYPE_DOUBLE_MASK then out.is_doubles = (type_flags & d.BATTLE_TYPE_DOUBLE_MASK) ~= 0 end
        if type(a.TRAINER_OPPONENT_ADDR) == "number" then
            out.trainer_id = io.read_u16(a.TRAINER_OPPONENT_ADDR)
        end
        local count = io.read_u8(a.BATTLERS_COUNT_ADDR)
        local battlers = {}
        for i = 0, count - 1 do
            battlers[i + 1] = io.read_u16(a.BATTLER_PARTY_INDEXES_ADDR + i * 2)
        end
        out.battlers_count, out.battler_party_indexes = count, battlers
        -- Player battlers are position 0 (single) and additionally 2 (doubles): outside link
        -- battles the battler id equals the position id (pret include/constants/battle.h:10-19).
        out.active_player_battler_slots = { battlers[1] }
        if count >= 4 then out.active_player_battler_slots[2] = battlers[3] end
        local enemy, why = r.read_enemy_party()
        if not enemy then return nil, why end
        out.enemy_party = enemy
        return out
    end

    return r
end

return R
