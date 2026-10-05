-- lua/gen2/polished_trade.lua -- the Polished Crystal half of SLink's in-game trade (card POL-TRADE).
--
-- WHY THIS FILE IS SEPARATE FROM compose_polished
--   lua/gen2/entry.lua `compose_polished` owns the writes/safety composition another card is
--   building. This module never edits it. The coordinator hooks it in at ONE seam:
--
--       -- in lua/gen2/entry.lua, inside compose_polished, next to the `client` construction:
--       local PT = load("lua/gen2/polished_trade.lua")
--       local trade = PT.compose({reads = reads, io = io_, profile = profile,
--                                 charmap = charmap, admission = Admission})
--       -- then pass `trade = trade` into client.new{...} (client.lua's trade hooks read `self.trade`)
--
--   compose() is fail-closed: if the profile does not yet carry the Polished overlay trade block, it
--   returns nil, why -- the client keeps its hello and ticks and logs the reason once. Nothing here
--   can half-arm.
--
-- WHAT IS ACTUALLY IMPLEMENTED
--   The 53-byte `trademon` codec, which is the piece the vanilla Gen 2 path has no analogue for and
--   which the overlay's staging needs on both sides. Vanilla Crystal's trademon is 50 bytes;
--   Polished's is 53 (wPlayerTrademon 00:c51c .. wPlayerTrademonEnd 00:c551, and wOTTrademon
--   00:c551 .. wOTTrademonEnd 00:c586 -- three more, and the extra bytes are the third DV byte plus
--   the two attribute bytes that carry shiny/ability/nature and ext-species/form/gender/is-egg).
--   See docs/polished/TRADE.md §8.2 and server/adapters/polished_codec.py, which is the byte-for-byte
--   twin of this module and whose tests/unit/test_polished_trade_codec.py pins both against the sym.
--
--   NOT implemented here, and deliberately not faked: the ROM service, the receptionist anchor, the
--   party-replace commit and the lease binder. Those are M1/M2b and they need the overlay.
local PT = {}

-- ── the 53-byte struct ─────────────────────────────────────────────────────────
-- Offsets are macros/ram.asm:252-276 `MACRO trademon`, cross-checked against the built sym; every
-- one is asserted against that sym by the Python test named above.
PT.TRADEMON_SIZE = 53
PT.NAME_SIZE = 11          -- NAME_LENGTH / MON_NAME_LENGTH: the field stride, not the glyph count
PT.OFF = {
    Species = 0, SpeciesName = 1, Nickname = 12, SenderName = 23, OTName = 34,
    HPAtkDV = 45, DefSpeDV = 46, SatSdfDV = 47, Personality = 48, Form = 49,
    ID = 50, CaughtData = 52,
}
-- pokemon_data_constants.asm:235-245, as the codec already reads them.
PT.GENDER_MASK, PT.IS_EGG_MASK, PT.EXTSPECIES_MASK, PT.FORM_MASK = 0x80, 0x40, 0x20, 0x1F
PT.SHINY_MASK, PT.ABILITY_MASK, PT.NATURE_MASK = 0x80, 0x60, 0x1F

PT.BLOB_SIZE = 70          -- 48 party_struct + 11 OT + 11 nickname, the wire party blob
local OFF, NAME_SIZE, BLOB_SIZE = PT.OFF, PT.NAME_SIZE, PT.BLOB_SIZE
local function valid_bytes(bytes, n, label)
    if type(bytes) ~= "table" or #bytes ~= n then
        return nil, string.format("%s: expected %d bytes, got %s", label, n, tostring(bytes and #bytes))
    end
    for i = 1, n do
        local v = bytes[i]
        if type(v) ~= "number" or v < 0 or v > 255 or v ~= math.floor(v) then
            return nil, string.format("%s: byte %d is %s, not 0..255", label, i, tostring(v))
        end
    end
    return true
end

--- The 9-bit species: the low byte plus bit 5 of the form byte
--- (ConvertFormToExtendedSpecies, home/pokemon.asm:408). A species above 0xFF must never be
--- truncated -- that is precisely the check vanilla's one-byte species compare could not make.

--- Bitwise AND that does not assume the mask is 2^k-1. Every %/floor shortcut here was wrong for
--- at least one of the four masks: GENDER_MASK $80 is not 2^k-1, and FORM_MASK $1F is not a divisor
--- of $FF, so `form_byte % 31` reads 7 for a form of 3.
local function band(v, m)
    local out, bit = 0, 1
    while bit <= 128 do
        if (v % (bit * 2)) >= bit and (m % (bit * 2)) >= bit then out = out + bit end
        bit = bit * 2
    end
    return out
end
PT.band = band

local function species_of(low, form_byte)
    return low + band(form_byte, PT.EXTSPECIES_MASK) * 8
end
PT.species_of = species_of

--- 70-byte wire party blob -> 53-byte staged trademon.
--- species_name_raw / sender_name_raw are the two names the blob does not carry: the species name is
--- engine-owned, the sender name is the partner's trainer name. Both default to the engine's own
--- blank (all terminators), never to a guess.
function PT.encode(blob, species_name_raw, sender_name_raw)
    local ok, why = valid_bytes(blob, BLOB_SIZE, "party blob")
    if not ok then return nil, why end
    local out = {}
    for i = 1, PT.TRADEMON_SIZE do out[i] = 0 end

    out[OFF.Species + 1] = blob[1]                                   -- party_struct +0
    local form_byte = blob[22]                                      -- party_struct +21
    local personality = blob[21]                                    -- party_struct +20
    out[OFF.Personality + 1] = personality
    out[OFF.Form + 1] = form_byte
    out[OFF.HPAtkDV + 1], out[OFF.DefSpeDV + 1], out[OFF.SatSdfDV + 1] = blob[18], blob[19], blob[20]
    out[OFF.ID + 1], out[OFF.ID + 2] = blob[7], blob[8]              -- big-endian OT id
    out[OFF.CaughtData + 1] = blob[29]                              -- party_struct +28

    local function put(offset, raw)
        if raw == nil then return end
        local good, problem = valid_bytes(raw, NAME_SIZE, "name field")
        if not good then error(problem, 0) end
        for i = 1, NAME_SIZE do out[offset + i] = raw[i] end
    end
    put(OFF.SpeciesName, species_name_raw)
    put(OFF.SenderName, sender_name_raw)
    -- OT and nickname come out of the blob itself, at their own strides.
    for i = 1, NAME_SIZE do
        out[OFF.OTName + i] = blob[BLOB_SIZE - 2 * NAME_SIZE + i] or 0
        out[OFF.Nickname + i] = blob[BLOB_SIZE - NAME_SIZE + i] or 0
    end
    return out
end

--- 53-byte staged trademon -> the fields a consumer needs. Deliberately NOT the same dict shape as
--- a decoded party mon: a trademon has no level, item, moves, exp, EVs or stats, and pretending
--- otherwise is how a received mon would silently arrive at level 0.
function PT.decode(raw)
    local ok, why = valid_bytes(raw, PT.TRADEMON_SIZE, "trademon")
    if not ok then return nil, why end
    local form_byte, personality = raw[OFF.Form + 1], raw[OFF.Personality + 1]
    local function field(offset)
        local t = {}
        for i = 1, NAME_SIZE do t[i] = raw[offset + i] end
        return t
    end
    return {
        size = PT.TRADEMON_SIZE,
        species_id = species_of(raw[OFF.Species + 1], form_byte),
        form = band(form_byte, PT.FORM_MASK),
        gender = band(form_byte, PT.GENDER_MASK) > 0 and "female" or "male",
        is_egg = band(form_byte, PT.IS_EGG_MASK) > 0,
        shiny = band(personality, PT.SHINY_MASK) > 0,
        ability_slot = band(personality, PT.ABILITY_MASK) / 32,
        nature = band(personality, PT.NATURE_MASK),
        ot_id = raw[OFF.ID + 1] * 256 + raw[OFF.ID + 2],
        caught_data = raw[OFF.CaughtData + 1],
        dvs = {hp_atk = raw[OFF.HPAtkDV + 1], def_spe = raw[OFF.DefSpeDV + 1], sat_sdf = raw[OFF.SatSdfDV + 1]},
        species_name = field(OFF.SpeciesName), sender_name = field(OFF.SenderName),
        ot_name = field(OFF.OTName), nickname = field(OFF.Nickname),
    }
end

-- ── the composition seam ───────────────────────────────────────────────────────

--- spec = {profile, io, charmap}. Returns the trade part, or nil, why.
--- The addresses come from the profile's overlay trade block; without it there is no trade, and
--- this returns nil rather than a half-built object (the same shape compose_polished uses for
--- panel and census).
function PT.compose(spec)
    local ok, result = pcall(function()
        assert(type(spec) == "table", "trade spec required")
        local profile = assert(spec.profile, "profile required")
        local ov = profile.overlay
        assert(ov and ov.trade and ov.ram, "profile.overlay.trade block required (Polished)")
        local T = {encode = PT.encode, decode = PT.decode, species_of = PT.species_of,
                   TRADEMON_SIZE = PT.TRADEMON_SIZE, OFF = OFF, NAME_SIZE = NAME_SIZE}
        -- The lease and the OT-party staging spans. Polished has NO wOTPartySpecies, so the vanilla
        -- six-span staging window (which includes species0 + $FF) has no counterpart here: the
        -- species reaches the trade inside wOTPartyMon1Species, i.e. inside the party-struct span.
        local ram = ov.ram
        T.spans = {
            lease = {bank = 0, addr = ram.wSlinkMailbox.addr + ov.trade.lease_offset, n = ov.trade.lease_size},
            player = {bank = ram.wOTPlayerName.bank, addr = ram.wOTPlayerName.addr, n = NAME_SIZE},
            count = {bank = ram.wOTPartyCount.bank, addr = ram.wOTPartyCount.addr, n = 1},
            mon = {bank = ram.wOTPartyMons.bank, addr = ram.wOTPartyMons.addr, n = profile.derived.party_struct_size},
            ot = {bank = ram.wOTPartyMonOTs.bank, addr = ram.wOTPartyMonOTs.addr, n = NAME_SIZE},
            nick = {bank = ram.wOTPartyMonNicknames.bank, addr = ram.wOTPartyMonNicknames.addr, n = NAME_SIZE},
        }
        assert(T.spans.lease.n == 16, "trade lease is 16 bytes (patch/gb/slink_abi.inc)")
        return T
    end)
    if not ok then return nil, tostring(result) end
    return result
end

return PT
