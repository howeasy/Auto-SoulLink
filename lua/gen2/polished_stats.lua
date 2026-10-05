-- lua/gen2/polished_stats.lua -- Polished Crystal v3.2.3 withdraw reconstruction: a 49-byte savemon -> the 48-byte
-- party_struct the engine builds (engine/pc/bills_pc.asm DecodeTempMon + SetTempPartyMonData). Byte for byte the
-- Lua twin of server/adapters/polished_codec.py savemon_to_party (tests/unit/test_polished_stats_lua.py cross-checks
-- it over seeded random mons). PURE: no file IO, no memory access, no emulator globals.
--
-- INJECTED (every one required, none defaulted; a missing one is a refusal, never a silent assumption):
--   opts.apply_evs    wInitialOptions2 & EV_OPTMASK(%11) ~= 0   (EVs enter CalcPkmnStatC only then)
--   opts.natures_on   wInitialOptions bit 0 NATURES_OPT         (off: every stat neutral)
--   opts.perfect_ivs  wInitialOptions bit 3 PERFECT_IVS_OPT     (DV 15 on every stat)
--   opts.base_stats   record index -> {hp, atk, def, spe, spa, spd}; records 292..337 (variant forms) included
--   opts.variant_record[species_id * 32 + form] -> record index for a variant form (absent = the plain species)
--   opts.move_pp      move id -> base PP
-- Hyper training is not an option: it is the OT extra byte (savemon[30] & 0xFC), always applied.
-- The savemon is a 1-based table of 49 ints; its checksum is the caller's job (polished_boxes.lua verifies it).
-- Returns party (1-based table of 48 ints), view {species, form, level, is_egg, hp, max_hp, stats = {hp,atk,def,spe,spa,spd}};
-- or nil, why.
local S = {}

local STAT_MIN_NORMAL, STAT_MIN_HP, MAX_STAT = 5, 10, 999
local PP_MASK, PP_UP_CAP, HYPER_TRAINING_MASK = 0x3F, 7, 0xFC

-- GetNatureStatMultiplier (mon_stats.asm:878-912): raised = nature//5+2, lowered = nature%5+2, equal = neutral, HP neutral.
function S.nature_multiplier(nature, stat)
    if stat == 1 then return 10 end
    local raised, lowered = nature // 5 + 2, nature % 5 + 2
    if raised == lowered then return 10 end
    if stat == lowered then return 9 end
    return stat == raised and 11 or 10
end

-- GetMaxPPOfMove + ComputeMaxPP: base 40 with 3 ups is 61, not 64.
function S.max_pp(base_pp, ups)
    return (base_pp + ups * math.min(base_pp // 5, PP_UP_CAP)) & PP_MASK
end

local function byte_table(t, n)
    if type(t) ~= "table" then return false end
    for i = 1, n do
        local v = t[i]
        if math.type(v) ~= "integer" or v < 0 or v > 255 then return false end
    end
    return true
end

function S.party_from_savemon(savemon, opts)
    if type(opts) ~= "table" or type(opts.base_stats) ~= "table" or type(opts.variant_record) ~= "table"
        or type(opts.move_pp) ~= "table" or type(opts.apply_evs) ~= "boolean"
        or type(opts.natures_on) ~= "boolean" or type(opts.perfect_ivs) ~= "boolean" then
        return nil, "options: base_stats, variant_record, move_pp and the booleans apply_evs/natures_on/perfect_ivs are required"
    end
    if not byte_table(savemon, 49) then return nil, "savemon: expected 49 bytes" end
    local sv = savemon
    local form_byte = sv[22]
    local species = sv[1] | (form_byte & 0x20) << 3
    local form = form_byte & 0x1F
    local level = sv[29]
    if species < 1 or level < 1 or level > 100 then return nil, "savemon: species/level out of range" end
    local record = opts.variant_record[species * 32 + form] or species
    local base = opts.base_stats[record]
    if type(base) ~= "table" then return nil, "base stats not supplied for record " .. record end
    for i = 1, 6 do
        if math.type(base[i]) ~= "integer" or base[i] < 1 or base[i] > 255 then
            return nil, "base stats for record " .. record .. " are not six bytes of 1..255"
        end
    end
    local nature = sv[21] & 0x1F
    local is_egg = form_byte & 0x40 ~= 0
    local trained = sv[30] & HYPER_TRAINING_MASK
    -- DV nibbles in CalcPkmnStatC order: HP, Atk | Def, Spe | SpA, SpD
    local dvs = {sv[18] >> 4, sv[18] & 15, sv[19] >> 4, sv[19] & 15, sv[20] >> 4, sv[20] & 15}
    local stats = {}
    for i = 1, 6 do
        local dv = (opts.perfect_ivs or trained & (0x80 >> (i - 1)) ~= 0) and 15 or dvs[i]
        local ev = opts.apply_evs and sv[11 + i] >> 2 or 0
        local value = ((base[i] + dv) * 2 + 1 + ev) * level // 100
        value = value + (i == 1 and STAT_MIN_HP + level or STAT_MIN_NORMAL)
        value = math.min(value, MAX_STAT)
        stats[i] = value * (opts.natures_on and S.nature_multiplier(nature, i) or 10) // 10
    end
    local p = {}
    for i = 1, 48 do p[i] = 0 end
    for i = 1, 22 do p[i] = sv[i] end               -- SPECIES..FORM: identical in both structs
    for i = 1, 4 do
        local move, ups = sv[2 + i], (sv[23] >> 2 * (i - 1)) & 3
        local pp = 0
        if move ~= 0 then
            local base_pp = opts.move_pp[move]
            if math.type(base_pp) ~= "integer" then return nil, "move " .. move .. " is not in the move table" end
            pp = S.max_pp(base_pp, ups)
        end
        p[22 + i] = (ups << 6) | pp
    end
    p[27], p[28] = sv[24], sv[25]                   -- happiness, pokerus
    p[29], p[30], p[31] = sv[26], sv[27], sv[28]    -- CaughtTime/Ball/Level/Location
    p[32] = level
    -- status (33) and the unused byte (34) stay 0; HP = MaxHP, 0 for an egg
    local hp = is_egg and 0 or stats[1]
    p[35], p[36] = hp >> 8, hp & 255     -- big-endian: high byte first
    for i = 1, 6 do p[35 + 2 * i], p[36 + 2 * i] = stats[i] >> 8, stats[i] & 255 end
    return p, {species = species, form = form, level = level, is_egg = is_egg, hp = hp, max_hp = stats[1],
               stats = {hp = stats[1], atk = stats[2], def = stats[3], spe = stats[4], spa = stats[5], spd = stats[6]}}
end

return S
