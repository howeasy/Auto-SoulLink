-- lua/gen4/reads.lua -- table-of-offsets RAM accessor for the Gen 4 client (HGSS / hge / Platinum).
--
-- No BizHawk globals and no literal game addresses or struct offsets: every one is a field of the
-- pack's profile.json title profile (the `profile` section of a title; a title object that nests
-- it as `.profile` is accepted too). The only constants here are NDS platform facts (main RAM
-- 0x02000000-0x023FFFFF) and the party capacity (pret include/party.h PARTY_SIZE).
--
-- `mem` is a read-only adapter with dot-called `mem.u8(addr)`, `mem.u16(addr)`, `mem.u32(addr)`,
-- little-endian, that may return nil for an unmapped address. A raising adapter is treated as
-- unmapped. Every read validates the COMPLETE range (start and end) inside main RAM before the
-- adapter is touched, and every function returns `(value)` or `(nil, reason)`; none ever errors.
--
-- Reason tokens: "pack_gap:<field>" (the pack does not carry what this read needs), "out_of_ram",
-- "unmapped", "null_ptr", "signature", "bad_array_id", "bad_array", "party_count",
-- "party_mon<N>:<pk4 reason>", "no_pk4".
--
-- Pointer chain (HGSS/hge; the Platinum table-of-offsets differs only in the profile's numbers):
--   [sSaveDataPtr] -> SaveData; array(id) = SaveData + dynamic_region_off + u32[header(id).offset]
--   (pret/pokeheartgold@ad7a3afa include/save.h:65-85; FILE+RAM confirmed on the owner HG save:
--   probe run hg_p2 savedata.bin, tests/unit/test_gen4_reads_lua.py).
local R = {}

R.RAM_LO, R.RAM_HI = 0x02000000, 0x023FFFFF
R.PARTY_CAPACITY = 6
R.NAME_EOS = 0xFFFF            -- charmap.txt EOS; the pack's trainer.name_terminator agrees
-- The PK4 codec. The client wires it in once (`Reads.pk4 = require("gen4.pk4")` or dofile);
-- party() takes no codec argument.
R.pk4 = nil

local WIDTH = { [1] = "u8", [2] = "u16", [4] = "u32" }

function R.in_ram(addr, len)
    return math.type(addr) == "integer" and len >= 1 and addr >= R.RAM_LO and addr + len - 1 <= R.RAM_HI
end

-- One scalar read of `size` (1|2|4) bytes: value, or nil + reason.
local function read(mem, addr, size)
    if not R.in_ram(addr, size) then return nil, "out_of_ram" end
    local ok, v = pcall(mem[WIDTH[size]], addr)
    if not ok or v == nil then return nil, "unmapped" end
    return v
end
R.read = read

-- `len` bytes as a fresh 1-based array (u32 reads where aligned, else u8).
local function bytes(mem, addr, len)
    if not R.in_ram(addr, len) then return nil, "out_of_ram" end
    local out, i = {}, 0
    while i < len do
        local size = (addr + i) % 4 == 0 and len - i >= 4 and 4 or 1
        local v, why = read(mem, addr + i, size)
        if not v then return nil, why end
        for k = 0, size - 1 do out[i + k + 1] = (v >> (8 * k)) & 0xFF end
        i = i + size
    end
    return out
end
R.bytes = bytes

local function words(mem, addr, n)
    local b, why = bytes(mem, addr, n * 2)
    if not b then return nil, why end
    local out = {}
    for i = 1, n do out[i] = b[2 * i - 1] | (b[2 * i] << 8) end
    return out
end

local function s32(v) return v >= 0x80000000 and v - 0x100000000 or v end

local function prof(profile)
    if type(profile) == "table" and type(profile.profile) == "table" then return profile.profile end
    return profile
end

-- p[a][b]... or nil + "pack_gap:a.b".
local function need(p, ...)
    local v, path = p, ""
    for _, k in ipairs({ ... }) do
        path = path .. (path == "" and "" or ".") .. k
        if type(v) ~= "table" or v[k] == nil then return nil, "pack_gap:" .. path end
        v = v[k]
    end
    return v
end

-- The two pack shapes of the same table of offsets: HGSS arrayHeaders {id,size,offset,crc,slot}
-- under the dynamic region, Platinum pageInfo entries {page,size,location,...} under the body.
local function layout(sv)
    if sv.array_headers_off then
        return { table_off = sv.array_headers_off, count = sv.array_header_count, entry = sv.array_header_size,
                 base_off = sv.dynamic_region_off, base_size = sv.dynamic_region_size,
                 off_f = sv.array_header_fields.offset, size_f = sv.array_header_fields.size,
                 id_f = sv.array_header_fields.id,
                 extent = math.max(sv.dynamic_region_off + sv.dynamic_region_size,
                                   sv.array_headers_off + sv.array_header_count * sv.array_header_size,
                                   sv.slot_specs_off + sv.slot_spec_count * sv.slot_spec_size) }
    elseif sv.table_off then
        return { table_off = sv.table_off, count = sv.entry_count, entry = sv.entry_size,
                 base_off = sv.body_off, base_size = sv.body_size,
                 off_f = sv.entry_fields.location, size_f = sv.entry_fields.size,
                 extent = math.max(sv.body_off + sv.body_size, sv.table_off + sv.entry_count * sv.entry_size) }
    end
end

-- HGSS: the general chunk's footer (magic, size == the slot spec's size, slot == its index).
-- Platinum has no RAM footer address in the pack, so its signature is a structural check of the
-- whole page table (every entry inside the body, at least one non-empty).
-- ponytail: Platinum is bind-only; a real signature needs a pack footer address (pack gap).
local function signature(mem, sv, sd, L)
    local cf = sv.chunk_footer
    if cf then
        local f, slot = sv.slot_spec_fields, sv.slots.general
        local spec = sd + sv.slot_specs_off + slot * sv.slot_spec_size
        local off, size = read(mem, spec + f.offset, 4), read(mem, spec + f.size, 4)
        if not off or not size then return false end
        if size < cf.size or off + size > sv.dynamic_region_size then return false end
        local foot = sd + sv.dynamic_region_off + off + size - cf.size
        local magic, fsize, fslot = read(mem, foot + cf.fields.magic, 4), read(mem, foot + cf.fields.size, 4),
            read(mem, foot + cf.fields.slot, 2)
        return magic == cf.magic and fsize == size and fslot == slot
    end
    local nonempty = false
    for id = 0, L.count - 1 do
        local e = sd + L.table_off + id * L.entry
        local loc, size = read(mem, e + L.off_f, 4), read(mem, e + L.size_f, 4)
        if not loc or not size or loc + size > L.base_size then return false end
        nonempty = nonempty or size > 0
    end
    return nonempty
end

-- SaveData address, validated: pointer cell readable, non-null, whole struct extent inside main
-- RAM, signature good.
function R.save_data(mem, profile)
    local p = prof(profile)
    local ptr, why = need(p, "save_ptr", "address")
    if not ptr then return nil, why end
    local sv
    sv, why = need(p, "save")
    if not sv then return nil, why end
    local L = layout(sv)
    if not L then return nil, "pack_gap:save.array_headers_off|table_off" end
    local sd
    sd, why = read(mem, ptr, 4)
    if not sd then return nil, why end
    if sd == 0 then return nil, "null_ptr" end
    if not R.in_ram(sd, L.extent) then return nil, "out_of_ram" end
    if not signature(mem, sv, sd, L) then return nil, "signature" end
    return sd
end

-- Address (and size) of save array `id` (number, or a name from profile.save.array_ids).
function R.array(mem, profile, sd, id)
    local p = prof(profile)
    local sv, why = need(p, "save")
    if not sv then return nil, why end
    local L = layout(sv)
    if not L then return nil, "pack_gap:save.array_headers_off|table_off" end
    if type(id) == "string" then id = sv.array_ids and sv.array_ids[id] end
    if math.type(id) ~= "integer" or id < 0 or id >= L.count then return nil, "bad_array_id" end
    local h = sd + L.table_off + id * L.entry
    local off, size = read(mem, h + L.off_f, 4), read(mem, h + L.size_f, 4)
    if not off or not size then return nil, "unmapped" end
    if L.id_f then
        local hid = read(mem, h + L.id_f, 4)
        if hid ~= id then return nil, "bad_array" end
    end
    if size == 0 or off + size > L.base_size then return nil, "bad_array" end
    return sd + L.base_off + off, size
end

-- array address with the SaveData resolved on demand, and a minimum length check.
local function area(mem, p, sd, id, need_len)
    if not sd then
        local why
        sd, why = R.save_data(mem, p)
        if not sd then return nil, why end
    end
    local addr, size = R.array(mem, p, sd, id)
    if not addr then return nil, size end
    if need_len > size then return nil, "bad_array" end
    return addr
end

local function pk4_profile(p)
    local m, why = need(p, "pkm", "exp_bits")
    if not m then return nil, why end
    -- hge's hidden-ability bit: the pack carries its location ({byte_off 0x19, bit 6}) as a table.
    return { exp_bits = p.pkm.exp_bits, ability_msb = type(p.pkm.ability_msb) == "table",
             hidden_ability = type(p.pkm.hidden_ability) == "table" }
end

-- Party as core mon records (pk4.to_core_mon) plus `slot` (0-based) and `decoded` (the full pk4
-- record). Refuses on a bad max/count header, a short array, or any record that fails pk4's
-- checksum/locked checks.
function R.party(mem, profile, sd)
    local p = prof(profile)
    local pk4 = R.pk4
    if not pk4 then return nil, "no_pk4" end
    local po, why = need(p, "party_off", "array_id")
    if not po then return nil, why end
    po = p.party_off
    local size = need(p, "pkm", "party_size")
    if not size then return nil, "pack_gap:pkm.party_size" end
    local pp
    pp, why = pk4_profile(p)
    if not pp then return nil, why end
    if not sd then
        sd, why = R.save_data(mem, p)
        if not sd then return nil, why end
    end
    local base
    base, why = area(mem, p, sd, po.array_id, po.mons_off)
    if not base then return nil, why end
    local max, cur = read(mem, base + po.max_off, 4), read(mem, base + po.count_off, 4)
    if not max or not cur then return nil, "unmapped" end
    if max ~= R.PARTY_CAPACITY or cur > max then return nil, "party_count" end
    if not area(mem, p, sd, po.array_id, po.mons_off + cur * size) then return nil, "bad_array" end
    local out = {}
    for i = 0, cur - 1 do
        local raw
        raw, why = bytes(mem, base + po.mons_off + i * size, size)
        if not raw then return nil, why end
        local mon
        mon, why = pk4.decode_party_mon(raw, pp)
        if not mon then return nil, "party_mon" .. i .. ":" .. why end
        local core = pk4.to_core_mon(mon)
        core.slot, core.decoded = i, mon
        out[#out + 1] = core
    end
    return out
end

local function player_base(mem, p, sd, min_len)
    local t, why = need(p, "trainer", "array_id")
    if not t then return nil, why end
    t = p.trainer
    local a
    a, why = area(mem, p, sd, t.array_id, t.profile_off_in_array + min_len)
    if not a then return nil, why end
    return a + t.profile_off_in_array, t
end

-- { name_raw (u16 array incl. terminator), tid, sid, otid (full u32), gender, language, version }
function R.trainer(mem, profile, sd)
    local p = prof(profile)
    local last = need(p, "trainer", "version_off")
    if not last then return nil, "pack_gap:trainer.version_off" end
    local base, t = player_base(mem, p, sd, math.max(p.trainer.id_off + 4, p.trainer.version_off + 1,
        p.trainer.name_off + p.trainer.name_chars * 2))
    if not base then return nil, t end
    local name, why = words(mem, base + t.name_off, t.name_chars)
    if not name then return nil, why end
    local otid, gender, lang, version
    otid, why = read(mem, base + t.id_off, 4)
    if not otid then return nil, why end
    gender, lang, version = read(mem, base + t.gender_off, 1), read(mem, base + t.language_off, 1),
        read(mem, base + t.version_off, 1)
    if not (gender and lang and version) then return nil, "unmapped" end
    return { name_raw = name, otid = otid, tid = otid & 0xFFFF, sid = otid >> 16,
             gender = gender, language = lang, version = version }
end

function R.money(mem, profile, sd)
    local p = prof(profile)
    local ok, why = need(p, "trainer", "money_off")
    if not ok then return nil, why end
    local base, t = player_base(mem, p, sd, p.trainer.money_off + 4)
    if not base then return nil, t end
    return read(mem, base + t.money_off, 4)
end

-- 16 badges in two regions: { johto = u8, kanto = u8, mask = johto | kanto << 8, count }.
-- The kanto byte is PlayerProfile+0x1F (a dummy byte precedes it): the pack's value, not 0x1E.
function R.badges(mem, profile, sd)
    local p = prof(profile)
    local ok, why = need(p, "trainer", "kanto_badges_off")
    if not ok then return nil, why end
    ok, why = need(p, "trainer", "johto_badges_off")
    if not ok then return nil, why end
    local base, t = player_base(mem, p, sd, math.max(p.trainer.johto_badges_off, p.trainer.kanto_badges_off) + 1)
    if not base then return nil, t end
    local johto, kanto = read(mem, base + t.johto_badges_off, 1), read(mem, base + t.kanto_badges_off, 1)
    if not johto or not kanto then return nil, "unmapped" end
    local mask, n = johto | (kanto << 8), 0
    for i = 0, 15 do n = n + ((mask >> i) & 1) end
    return { johto = johto, kanto = kanto, mask = mask, count = n }
end

-- Player Location { map_id, warp_id, x, y, dir } (signed 32-bit each).
-- PACK GAP: the HGSS pack names the local-field-data array (id 5) but carries no Location
-- offsets, so this reads a pack-supplied `profile.location = { array_id, map_off, warp_off,
-- x_off, y_off, dir_off }` (arrays are base-relative) and refuses with pack_gap:location without it.
function R.location(mem, profile, sd)
    local p = prof(profile)
    local l, why = need(p, "location", "array_id")
    if not l then return nil, why end
    l = p.location
    local a
    a, why = area(mem, p, sd, l.array_id, 0)
    if not a then return nil, why end
    local out = {}
    for name, key in pairs({ map_id = "map_off", warp_id = "warp_off", x = "x_off", y = "y_off", dir = "dir_off" }) do
        if l[key] == nil then return nil, "pack_gap:location." .. key end
        local v
        v, why = read(mem, a + l[key], 4)
        if not v then return nil, why end
        out[name] = s32(v)
    end
    return out
end

-- Gen 4 u16 text -> string through the CALLER's charmap {[code] = string}; the 0xFFFF terminator
-- ends the name; an unknown code becomes <$XXXX> (the Python oracle's rendering).
function R.decode_name(u16s, charmap)
    local out = {}
    for _, w in ipairs(u16s) do
        if w == R.NAME_EOS then break end
        out[#out + 1] = charmap[w] or string.format("<$%04X>", w)
    end
    return table.concat(out)
end

-- TODO(C1-8 / battle card): the battle chain (BattleSystem pointer -> battlers/party, validated
-- against local party ownership and PID:OTID) is NOT part of this card.
function R.battle() return nil, "todo:battle_chain" end

return R
