-- lua/gen4/pk4.lua -- the Gen 4 (HGSS / hg-engine / Platinum) in-game Pokemon record codec.
--
-- Pure: byte strings or 1-based byte arrays in, 1-based byte arrays / tables out; no BizHawk
-- API, no globals. Mirrors the PK4 half of server/adapters/gen4_codec.py (the independent
-- oracle; the save-file half is not ported). Offsets are 0-based struct offsets, arrays 1-based,
-- as in lua/gen3/reads.lua. Errors are (nil, reason) with the oracle's reason tokens
-- "size" | "locked" | "checksum".
--
-- Sources (pret/pokeheartgold ad7a3afa): record layout include/pokemon_types_def.h:50-217,
-- checksum src/pokemon.c:3941-3950, shuffle :3951-3986, PRNG src/math_util.c:150-157.
local Pk4 = {}

Pk4.BOX_MON_SIZE = 0x88
Pk4.PARTY_MON_SIZE = 0xEC
local BLOCK, HEADER, TAIL = 0x20, 8, 0x88

-- Variants as data (mirrors gen4_codec.PROFILES): exp field width, hge 9-bit ability (abilityMSB
-- = bit 31 of the block A exp word) and hge hidden-ability bit (block B +0x19 bit 6; bit 0 is
-- HGSS_shinyLeaves, bit 7 the crit flag: pret pokemon_types_def.h:96-98, fork pokemon.h:21-23).
-- max_species / max_item / max_move bound the box_plausible guard (highest valid id, from the committed
-- data/games/gen4_*/names.json tables: hgss 493 / 536 / 467; hge counts forms: 1475 / 2684 / 922). Pt has no
-- names.json here: its species/move bounds are the HGSS ones and its item bound is the HGSS table size (a
-- safe upper bound, a too-small one would flag real mons).
Pk4.PROFILES = {
    hgss = { exp_bits = 32, ability_msb = false, hidden_ability = false, max_species = 493,  max_item = 536,  max_move = 467 },
    hge  = { exp_bits = 21, ability_msb = true,  hidden_ability = true,  max_species = 1475, max_item = 2684, max_move = 922 },
    pt   = { exp_bits = 32, ability_msb = false, hidden_ability = false, max_species = 493,  max_item = 536,  max_move = 467 },
}
local MAX_EXP = 1640000 -- exp at level 100 on the largest curve (Fluctuating)

-- Row = (pid >> 13) & 31 (== (pid & 0x3E000) >> 13); rows 24-31 repeat rows 0-7 (% 24).
-- Column = logical block A..D, value = stored byte offset of that block.
local SHUFFLE = {
    { 0x00, 0x20, 0x40, 0x60 }, { 0x00, 0x20, 0x60, 0x40 }, { 0x00, 0x40, 0x20, 0x60 },
    { 0x00, 0x60, 0x20, 0x40 }, { 0x00, 0x40, 0x60, 0x20 }, { 0x00, 0x60, 0x40, 0x20 },
    { 0x20, 0x00, 0x40, 0x60 }, { 0x20, 0x00, 0x60, 0x40 }, { 0x40, 0x00, 0x20, 0x60 },
    { 0x60, 0x00, 0x20, 0x40 }, { 0x40, 0x00, 0x60, 0x20 }, { 0x60, 0x00, 0x40, 0x20 },
    { 0x20, 0x40, 0x00, 0x60 }, { 0x20, 0x60, 0x00, 0x40 }, { 0x40, 0x20, 0x00, 0x60 },
    { 0x60, 0x20, 0x00, 0x40 }, { 0x40, 0x60, 0x00, 0x20 }, { 0x60, 0x40, 0x00, 0x20 },
    { 0x20, 0x40, 0x60, 0x00 }, { 0x20, 0x60, 0x40, 0x00 }, { 0x40, 0x20, 0x60, 0x00 },
    { 0x60, 0x20, 0x40, 0x00 }, { 0x40, 0x60, 0x20, 0x00 }, { 0x60, 0x40, 0x20, 0x00 },
}

-- Accept a string or an array; always hand back a fresh 1-based array (callers never alias).
local function arr(b)
    if type(b) == "string" then
        local out = {}
        for i = 1, #b do out[i] = b:byte(i) end
        return out
    end
    local out = {}
    for i = 1, #b do out[i] = b[i] end
    return out
end

local function u(b, off, size)
    local value = 0
    for i = size - 1, 0, -1 do value = (value << 8) | b[off + i + 1] end
    return value
end

local function words(b, off, n)
    local out = {}
    for i = 1, n do out[i] = u(b, off + (i - 1) * 2, 2) end
    return out
end

local function slice(b, off, len)
    local out = {}
    for i = 1, len do out[i] = b[off + i] end
    return out
end

-- XOR each u16 from `off` to the end with the next LCG output; symmetric.
local function lcg_xor(b, off, seed)
    for i = off + 1, #b, 2 do
        seed = (seed * 0x41C64E6D + 0x6073) & 0xFFFFFFFF
        local x = (b[i] | (b[i + 1] << 8)) ~ (seed >> 16)
        b[i], b[i + 1] = x & 0xFF, x >> 8
    end
end

-- u16 sum of the 64 words of the four blocks (`b` holds them from 0-based `off`).
function Pk4.checksum(b, off)
    local total = 0
    for i = off + 1, off + 4 * BLOCK, 2 do total = total + (b[i] | (b[i + 1] << 8)) end
    return total & 0xFFFF
end

-- Move block `src` (0-based offset table row, `to_stored` picks direction) of 0x80 body bytes.
local function reorder(b, pid, to_stored)
    local row = SHUFFLE[((pid >> 13) & 31) % 24 + 1]
    local out = {}
    for which = 0, 3 do
        local logical, stored = HEADER + which * BLOCK, HEADER + row[which + 1]
        local from, to = logical, stored
        if not to_stored then from, to = stored, logical end
        for i = 1, BLOCK do out[to + i] = b[from + i] end
    end
    for i = 1, HEADER do out[i] = b[i] end
    return out
end

function Pk4.decrypt_box(raw)
    local b = arr(raw)
    if #b ~= Pk4.BOX_MON_SIZE then return nil, "size" end
    local pid, flags, stored_sum = u(b, 0, 4), u(b, 4, 2), u(b, 6, 2)
    if flags & 0x3 ~= 0 then return nil, "locked" end
    lcg_xor(b, HEADER, stored_sum)
    if Pk4.checksum(b, HEADER) ~= stored_sum then return nil, "checksum" end
    return reorder(b, pid, false)
end

function Pk4.encrypt_box(plain)
    local p = arr(plain)
    if #p ~= Pk4.BOX_MON_SIZE then return nil, "size" end
    local b = reorder(p, u(p, 0, 4), true)
    local csum = Pk4.checksum(b, HEADER)
    b[7], b[8] = csum & 0xFF, csum >> 8
    lcg_xor(b, HEADER, csum)
    return b
end

-- The party tail has no checksum and is keyed by the PID.
function Pk4.decrypt_party(raw)
    local b = arr(raw)
    if #b ~= Pk4.PARTY_MON_SIZE then return nil, "size" end
    local head, why = Pk4.decrypt_box(slice(b, 0, Pk4.BOX_MON_SIZE))
    if not head then return nil, why end
    local tail = slice(b, TAIL, Pk4.PARTY_MON_SIZE - TAIL)
    lcg_xor(tail, 0, u(b, 0, 4))
    for i = 1, #tail do head[TAIL + i] = tail[i] end
    return head
end

function Pk4.encrypt_party(plain)
    local p = arr(plain)
    if #p ~= Pk4.PARTY_MON_SIZE then return nil, "size" end
    local head = Pk4.encrypt_box(slice(p, 0, Pk4.BOX_MON_SIZE))
    local tail = slice(p, TAIL, Pk4.PARTY_MON_SIZE - TAIL)
    lcg_xor(tail, 0, u(p, 0, 4))
    for i = 1, #tail do head[TAIL + i] = tail[i] end
    return head
end

function Pk4.mon_key(pid, otid) return string.format("%08X:%08X", pid, otid) end

-- Plaintext record (0x88 or 0xEC, from decrypt_*) -> fields named as in the oracle's decode_plain
-- (raw values, no text conversion: nickname_raw / ot_name_raw are u16 arrays incl. terminator).
-- Extra over the oracle: hidden_ability (hge only; the oracle leaves it undecoded).
function Pk4.decode_plain(plain, profile)
    local p = type(plain) == "string" and arr(plain) or plain
    if #p ~= Pk4.BOX_MON_SIZE and #p ~= Pk4.PARTY_MON_SIZE then return nil, "size" end
    local a, b, c, d = HEADER, HEADER + BLOCK, HEADER + 2 * BLOCK, HEADER + 3 * BLOCK
    local pid, flags, csum = u(p, 0, 4), u(p, 4, 2), u(p, 6, 2)
    local otid, expword = u(p, a + 4, 4), u(p, a + 8, 4)
    local ability = p[a + 0x0D + 1]
    if profile.ability_msb then ability = ability | ((expword >> 31) << 8) end
    local ivword = u(p, b + 0x10, 4)
    local fgf = p[b + 0x18 + 1]
    local origin = p[c + 0x17 + 1]
    local ball = p[d + 0x1B + 1]
    if (origin == 7 or origin == 8) and p[d + 0x1E + 1] ~= 0 then ball = p[d + 0x1E + 1] end
    local egg_dp, met_dp = u(p, d + 0x16, 2), u(p, d + 0x18, 2)
    local egg_ph, met_ph = u(p, b + 0x1C, 2), u(p, b + 0x1E, 2)
    local ivs = {}
    for i = 0, 5 do ivs[i + 1] = (ivword >> (5 * i)) & 31 end
    local tid, sid = otid & 0xFFFF, otid >> 16
    local mon = {
        pid = pid, flags = flags, checksum = csum, otid = otid, tid = tid, sid = sid,
        key = Pk4.mon_key(pid, otid),
        species = u(p, a, 2), held_item = u(p, a + 2, 2),
        exp = expword & ((1 << profile.exp_bits) - 1), ability = ability,
        friendship = p[a + 0x0C + 1], markings = p[a + 0x0E + 1], language = p[a + 0x0F + 1],
        evs = slice(p, a + 0x10, 6),
        moves = words(p, b, 4), pp = slice(p, b + 8, 4), pp_ups = slice(p, b + 12, 4),
        ivs = ivs, is_egg = ((ivword >> 30) & 1) == 1, has_nickname = ((ivword >> 31) & 1) == 1,
        fateful = fgf & 1, gender = (fgf >> 1) & 3, form = fgf >> 3,
        nickname_raw = words(p, c, 11), origin_game = origin, ot_name_raw = words(p, d, 8),
        ball = ball, met_level = p[d + 0x1C + 1] & 0x7F, ot_gender = p[d + 0x1C + 1] >> 7,
        -- src/pokemon.c:818-830: the DP location wins unless it is "faraway place" (3002)
        egg_location = (egg_dp ~= 3002 or egg_ph == 0) and egg_dp or egg_ph,
        met_location = (met_dp ~= 3002 or met_ph == 0) and met_dp or met_ph,
        nature = pid % 25,
        shiny = (sid ~ tid ~ (pid >> 16) ~ (pid & 0xFFFF)) < 8,
    }
    -- The box checksum is order-invariant, so a wrong PID decrypts to scrambled blocks without a refusal;
    -- this range check on the decoded head is the guard (the party tail has its own, tail_plausible).
    local ok = mon.species >= 1 and mon.species <= (profile.max_species or math.huge)
        and mon.held_item <= (profile.max_item or math.huge) and mon.exp <= MAX_EXP and mon.met_level <= 100
    for _, mv in ipairs(mon.moves) do ok = ok and mv <= (profile.max_move or math.huge) end
    mon.box_plausible = ok
    if profile.hidden_ability then mon.hidden_ability = (p[b + 0x19 + 1] >> 6) & 1 end
    if #p == Pk4.PARTY_MON_SIZE then
        mon.status, mon.level, mon.capsule = u(p, TAIL, 4), p[TAIL + 4 + 1], p[TAIL + 5 + 1]
        mon.hp, mon.max_hp = u(p, TAIL + 6, 2), u(p, TAIL + 8, 2)
        mon.stats = { u(p, TAIL + 10, 2), u(p, TAIL + 12, 2), u(p, TAIL + 14, 2),
                      u(p, TAIL + 16, 2), u(p, TAIL + 18, 2) }
        mon.tail_plausible = mon.level >= 1 and mon.level <= 100 and mon.max_hp > 0
            and mon.max_hp < 1000 and mon.hp <= mon.max_hp
    end
    return mon
end

function Pk4.decode_box_mon(raw, profile)
    local plain, why = Pk4.decrypt_box(raw)
    if not plain then return nil, why end
    return Pk4.decode_plain(plain, profile)
end

function Pk4.decode_party_mon(raw, profile)
    local plain, why = Pk4.decrypt_party(raw)
    if not plain then return nil, why end
    return Pk4.decode_plain(plain, profile)
end

-- A never-used box slot is all zero; a cleared one decrypts to species 0.
function Pk4.is_empty_slot(raw)
    local b = arr(raw)
    local any = false
    for i = 1, math.min(#b, Pk4.BOX_MON_SIZE) do if b[i] ~= 0 then any = true; break end end
    if not any then return true end
    local plain = Pk4.decrypt_box(slice(b, 0, Pk4.BOX_MON_SIZE))
    return plain ~= nil and u(plain, HEADER, 2) == 0
end

-- The shared core's mon record (lua/core/identity.lua key/slot/nickname_bytes/moves,
-- lua/core/deferred.lua level/max_hp). `slot` is filled by the caller; box mons carry no
-- level/hp. Gen 4 text is u16 codes: nickname_bytes is the raw u16 array, `nickname` (string)
-- is left nil until the text card lands.
function Pk4.to_core_mon(m)
    return { key = m.key, species = m.species, level = m.level, hp = m.hp, max_hp = m.max_hp,
             moves = m.moves, nickname = nil, nickname_bytes = m.nickname_raw }
end

return Pk4
