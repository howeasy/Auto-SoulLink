--[[
  lua/memory_nds.lua — Gen 4 NDS memory map constants and read/write helpers.
  Shared by all Gen 4 games: HeartGold, SoulSilver, Platinum.

  Named "memory_nds" (not "memory") to avoid collision with BizHawk's built-in
  global `memory` object, which NLua can return instead of the file module when
  the module name matches a registered global.
  Source references:
    pret/pokeheartgold include/pokemon_types_def.h  — PartyPokemon struct layout
    BluRosie/hg-engine include/constants/maps.h     — map / zone constants
    HGSS disassembly research

  Pointer chain (call M.init() every frame):
    p1   = memory.read_u32_le(P1_ADDR, "Main RAM") & 0xFFFFFF
    base = memory.read_u32_le(p1 + BASE_OFFSET, "Main RAM") & 0xFFFFFF
  If either is 0 the save is not loaded; M.init() returns nil.

  Identity key: PID:OTID — Block A is decrypted for party mons (partyDecrypted
  flag set) so OT ID is available. Falls back to PID-only if decryption fails.
--]]

local M = {}

-- ── BizHawk NDS domain ────────────────────────────────────────────────────────
local RAM = "Main RAM"

-- Localise hot-path BizHawk memory functions to reduce dispatch overhead.
local function r8 (a)    return memory.read_u8   (a, RAM) end
local function r16(a)    return memory.read_u16_le(a, RAM) end
local function r32(a)    return memory.read_u32_le(a, RAM) end
local function w16(a, v) memory.write_u16_le(a, v, RAM) end

local fmt = string.format

-- ── Gen IV LCRNG — party/battle stat decryption ───────────────────────────────
-- In HGSS, the battle-stat block (PKM+0x88: level, curHP, maxHP, …) is encrypted
-- in live RAM using a PID-seeded linear-congruential RNG (confirmed against live
-- scan data: encrypted level=70 / curHP=48378 / maxHP=15155 → decrypted 5/19/19).
-- Reference: NDS-Ironmon-Tracker PokemonDataReader.lua / BattleHandlerGen4.lua.
--
-- LCRNG: seed = (seed × 0x41C64E6D + 0x6073) mod 2³²
-- Each encrypted u16 word is XOR'd with the upper 2 bytes of the current seed.
-- Advance schedule for the battle-stat block (offsets from block start):
--   1 advance  →  read+XOR offset 0  (status u16 lo)
--   2 advances →  read+XOR offset 4  (level u8 | unused u8)
--   1 advance  →  read+XOR offset 6  (curHP u16)
--   1 advance  →  read+XOR offset 8  (maxHP u16)
--
-- Lua 5.3 integer arithmetic: all products fit in int64 (max ≈ 4.74×10¹⁸ < 2⁶³).
-- & 0xFFFFFFFF truncates to 32 bits, matching the intended mod 2³².

local function lcrng(s)
    return (s * 0x41C64E6D + 0x6073) & 0xFFFFFFFF
end

local function xor16(enc, seed)
    local b0 = (enc & 0xFF)        ~ ((seed >> 16) & 0xFF)
    local b1 = ((enc >> 8) & 0xFF) ~ ((seed >> 24) & 0xFF)
    return b0 | (b1 << 8)
end

local function _block_order(pid)
    return ((pid & 0x3E000) >> 13) % 24
end

-- Decrypt battle-stat block at bs_addr (= PKM struct + 0x088).
-- Returns level (u8), curHP (u16), maxHP (u16) as plain integers.
-- Advance schedule (each u16 word at offset N uses the Nth LCRNG step):
--   s1 → offset 0  (status lo-word, discarded)
--   s2 → offset 2  (status hi-word)
--   s3 → offset 4  (level in low byte)
--   s4 → offset 6  (curHP)
--   s5 → offset 8  (maxHP)
local function decrypt_stats(bs_addr, pid)
    local s = lcrng(pid)                               -- s1 → offset 0 (status lo)
    local status_lo = xor16(r16(bs_addr), s)
    s = lcrng(s)                                       -- s2 → offset 2 (status hi)
    local status_hi = xor16(r16(bs_addr + 2), s)
    local status = status_lo | (status_hi << 16)
    s = lcrng(s)                                       -- s3 → offset 4
    local level = xor16(r16(bs_addr + 4), s) & 0xFF   -- low byte = level
    s = lcrng(s)                                       -- s4 → offset 6
    local curHP = xor16(r16(bs_addr + 6), s)
    s = lcrng(s)                                       -- s5 → offset 8
    local maxHP = xor16(r16(bs_addr + 8), s)
    return level, curHP, maxHP, status
end

-- Export so test scripts can use it for verified scan output.
M.decrypt_stats = decrypt_stats

-- Encrypt and write battle-stat block at bs_addr (= PKM struct + 0x088).
-- Takes plaintext values; XORs each u16 with PID-seeded LCRNG (same as decrypt — XOR is self-inverse).
-- Writes: status(u32), level+pad(u16), curHP(u16), maxHP(u16), then atk/def/speed/spatk/spdef.
-- If stats beyond HP are unknown, pass 0 — the game recalculates on summary screen access.
local function encrypt_stats(bs_addr, pid, status, level, curHP, maxHP, atk, def, speed, spatk, spdef)
    status = status or 0
    level  = level or 1
    curHP  = curHP or maxHP or 1
    maxHP  = maxHP or curHP or 1
    atk    = atk or 0
    def    = def or 0
    speed  = speed or 0
    spatk  = spatk or 0
    spdef  = spdef or 0
    -- Encrypt each u16 word with LCRNG stream seeded by PID
    local s = lcrng(pid)                                       -- s1 → offset 0
    local status_lo = status & 0xFFFF
    w16(bs_addr + 0, xor16(status_lo, s))
    s = lcrng(s)                                               -- s2 → offset 2
    local status_hi = (status >> 16) & 0xFFFF
    w16(bs_addr + 2, xor16(status_hi, s))
    s = lcrng(s)                                               -- s3 → offset 4
    local lv_word = level & 0xFF                               -- level in low byte, pad=0
    w16(bs_addr + 4, xor16(lv_word, s))
    s = lcrng(s)                                               -- s4 → offset 6
    w16(bs_addr + 6, xor16(curHP & 0xFFFF, s))
    s = lcrng(s)                                               -- s5 → offset 8
    w16(bs_addr + 8, xor16(maxHP & 0xFFFF, s))
    s = lcrng(s)                                               -- s6 → offset 0x0A (atk)
    w16(bs_addr + 0x0A, xor16(atk & 0xFFFF, s))
    s = lcrng(s)                                               -- s7 → offset 0x0C (def)
    w16(bs_addr + 0x0C, xor16(def & 0xFFFF, s))
    s = lcrng(s)                                               -- s8 → offset 0x0E (speed)
    w16(bs_addr + 0x0E, xor16(speed & 0xFFFF, s))
    s = lcrng(s)                                               -- s9 → offset 0x10 (spatk)
    w16(bs_addr + 0x10, xor16(spatk & 0xFFFF, s))
    s = lcrng(s)                                               -- s10 → offset 0x12 (spdef)
    w16(bs_addr + 0x12, xor16(spdef & 0xFFFF, s))
end
M.encrypt_stats = encrypt_stats

-- ── Gen IV Block A decryption ─────────────────────────────────────────────────
-- The 128-byte data section (PKM+0x008..+0x087) is divided into four 32-byte
-- sub-structures (blocks A–D). Their order is determined by ((PID & 0x3E000) >> 13) % 24.
-- Block A holds species (u16), heldItem (u16), otID (u32: TID=lo16, SID=hi16).
--
-- Decryption: seed = PKM+0x006 (checksum); for each u16 word at index i
--   (i = 0..63): xor with (lcrng^(i+1)(chk) >> 16).
--
-- Reference: pret/pokeheartgold include/pokemon_types_def.h,
--            Project Pokemon Gen 4 PKM structure docs (block order formula).

-- Block A byte offset within the 128-byte data region for each of the 24 block orders.
-- order_val = ((PID & 0x3E000) >> 13) % 24  (Project Pokemon spec; NOT pid%24)
-- ABCD=0..5 → A@0, BACD=6 → A@32, BCAD=8 → A@64, BCDA=9 → A@96, …
local BLOCK_A_OFF = {
    [0]=0,  [1]=0,  [2]=0,  [3]=0,  [4]=0,  [5]=0,
    [6]=32, [7]=32, [8]=64, [9]=96, [10]=64,[11]=96,
    [12]=32,[13]=32,[14]=64,[15]=96,[16]=64,[17]=96,
    [18]=32,[19]=32,[20]=64,[21]=96,[22]=64,[23]=96,
}

-- Block B byte offset within the 128-byte data region for each of the 24 block orders.
-- Block B holds: moves (4×u16), PP (4×u8), PP Ups (4×u8), IV32 (with IsEgg/IsNicknamed bits),
-- Hoenn ribbons, and (Gen 5 only) Form/Gender packed byte.
local BLOCK_B_OFF = {
    [0]=32, [1]=32, [2]=64, [3]=96, [4]=64, [5]=96,
    [6]=0,  [7]=0,  [8]=0,  [9]=0,  [10]=0, [11]=0,
    [12]=64,[13]=96,[14]=32,[15]=32,[16]=96,[17]=64,
    [18]=64,[19]=96,[20]=32,[21]=32,[22]=96,[23]=64,
}

-- Block C byte offset within the 128-byte data region for each of the 24 block orders.
-- Block C holds: nickname (11 × u16).
local BLOCK_C_OFF = {
    [0]=64, [1]=96, [2]=32, [3]=32, [4]=96, [5]=64,
    [6]=64, [7]=96, [8]=32, [9]=32, [10]=96,[11]=64,
    [12]=0,  [13]=0, [14]=0, [15]=0, [16]=0, [17]=0,
    [18]=96,[19]=64,[20]=96,[21]=64,[22]=32,[23]=32,
}

-- Decrypt Block A and return (species_id u16, ot_id u32).
-- ot_id: TID = ot_id & 0xFFFF, SID = (ot_id >> 16) & 0xFFFF.
-- Returns nil if the slot is empty or the decrypted species is out of range.
--
-- IMPORTANT: In live RAM (party, battle copies), data blocks are already decrypted
-- by the game engine (partyDecrypted flag, FLAGS bit 0, is set). When this flag is
-- set, blocks at PKM+0x008 are plaintext — no LCRNG XOR needed; read directly.
-- The LCRNG path only applies to save-file / PC-box format (flag = 0).
local function decrypt_block_a(pkm_addr)
    local pid = r32(pkm_addr)
    if pid == 0 then return nil end
    local chk       = r16(pkm_addr + 0x006)
    local order_val = _block_order(pid)
    local blk_off   = BLOCK_A_OFF[order_val] or 0
    local data_base = pkm_addr + 0x008 + blk_off
    local word_base = blk_off >> 1   -- u16 words before Block A in the 64-word stream
    local s = chk
    for _ = 1, word_base do s = lcrng(s) end
    s = lcrng(s); local species = xor16(r16(data_base),     s)  -- word 0: species
    s = lcrng(s)                                                 -- word 1: heldItem (skip)
    s = lcrng(s); local ot_lo   = xor16(r16(data_base + 4), s)  -- word 2: otID lo (TID)
    s = lcrng(s); local ot_hi   = xor16(r16(data_base + 6), s)  -- word 3: otID hi (SID)
    if species == 0 or species > SPECIES_MAX then return nil end
    return species, ot_lo | (ot_hi << 16)
end

M.decrypt_block_a = decrypt_block_a

-- Decrypt Block A extended: returns (species, ot_id, held_item, ability).
-- Block A layout: species(u16), heldItem(u16), otID(u32), exp(u32), friendship(u8), ability(u8).
function M.decrypt_block_a_ext(pkm_addr)
    local pid = r32(pkm_addr)
    if pid == 0 then return nil end
    local chk       = r16(pkm_addr + 0x006)
    local order_val = _block_order(pid)
    local blk_off   = BLOCK_A_OFF[order_val] or 0
    local data_base = pkm_addr + 0x008 + blk_off
    local word_base = blk_off >> 1
    local s = chk
    for _ = 1, word_base do s = lcrng(s) end
    s = lcrng(s); local species   = xor16(r16(data_base),     s)
    s = lcrng(s); local held_item = xor16(r16(data_base + 2), s)
    s = lcrng(s); local ot_lo     = xor16(r16(data_base + 4), s)
    s = lcrng(s); local ot_hi     = xor16(r16(data_base + 6), s)
    s = lcrng(s)  -- exp lo
    s = lcrng(s)  -- exp hi
    s = lcrng(s)  -- friendship(u8) | ability(u8) packed as u16
    local packed = xor16(r16(data_base + 12), s)
    local ability = (packed >> 8) & 0xFF
    if species == 0 or species > SPECIES_MAX then return nil end
    return species, ot_lo | (ot_hi << 16), held_item, ability
end

-- Decrypt Block B and return a table with moves, PP, PP Ups, form, and isEgg.
-- Block B layout (offsets within the 32-byte block; struct offsets in [brackets] for Gen 5):
--   +0x00 [0x28] Move 1 (u16)
--   +0x02 [0x2A] Move 2 (u16)
--   +0x04 [0x2C] Move 3 (u16)
--   +0x06 [0x2E] Move 4 (u16)
--   +0x08 [0x30] Move 1-2 PP (u16 packed: lo=PP1, hi=PP2)
--   +0x0A [0x32] Move 3-4 PP (u16 packed: lo=PP3, hi=PP4)
--   +0x0C [0x34] Move 1-2 PP Ups (u16 packed)
--   +0x0E [0x36] Move 3-4 PP Ups (u16 packed)
--   +0x10 [0x38] IV32 lo word (HP/Atk/Def/Spd IVs)
--   +0x12 [0x3A] IV32 hi word (SpA/SpD IVs + bit 30=IsEgg, bit 31=IsNicknamed)
--   +0x14 [0x3C] Hoenn ribbon set 1 (skip)
--   +0x16 [0x3E] Hoenn ribbon set 1 (skip)
--   +0x18 [0x40] Misc1: lo byte = (Form << 3 | Gender << 1 | Fateful). Form = bits 3-7.
-- Sources: kwsch/PKHeX PK5.cs (struct offsets); Bulbapedia Gen IV/V data structure
-- (shuffle formula and block layout); reused for Gen 4 (PK4.cs offsets identical for
-- moves/PP/IV32; AltForm location matches per PKHeX).
--
-- Returns: { moves={u16×4}, pp={u8×4}, pp_ups={u8×4}, form=u8, isEgg=bool } or nil.
function M.decrypt_block_b(pkm_addr)
    local pid = r32(pkm_addr)
    if pid == 0 then return nil end
    local chk       = r16(pkm_addr + 0x006)
    local order_val = _block_order(pid)
    local blk_off   = BLOCK_B_OFF[order_val] or 0
    local data_base = pkm_addr + 0x008 + blk_off
    local word_base = blk_off >> 1
    local s = chk
    for _ = 1, word_base do s = lcrng(s) end
    -- Words 0-3: moves
    s = lcrng(s); local m1 = xor16(r16(data_base + 0),  s)
    s = lcrng(s); local m2 = xor16(r16(data_base + 2),  s)
    s = lcrng(s); local m3 = xor16(r16(data_base + 4),  s)
    s = lcrng(s); local m4 = xor16(r16(data_base + 6),  s)
    -- Words 4-5: PP (4 bytes packed across 2 u16)
    s = lcrng(s); local pp12 = xor16(r16(data_base + 8),  s)
    s = lcrng(s); local pp34 = xor16(r16(data_base + 10), s)
    -- Words 6-7: PP Ups (4 bytes packed across 2 u16)
    s = lcrng(s); local up12 = xor16(r16(data_base + 12), s)
    s = lcrng(s); local up34 = xor16(r16(data_base + 14), s)
    -- Words 8-9: IV32 (split across two u16)
    s = lcrng(s); local _iv_lo = xor16(r16(data_base + 16), s)
    s = lcrng(s); local iv_hi  = xor16(r16(data_base + 18), s)
    -- IsEgg = bit 30 of IV32 = bit 14 of iv_hi (since iv_hi = bits 16-31 of IV32)
    local isEgg = ((iv_hi >> 14) & 1) == 1
    -- Words 10-11: Hoenn ribbon set 1 (skip)
    s = lcrng(s)
    s = lcrng(s)
    -- Word 12: Misc1 (form bits 3-7 of low byte; gender bits 1-2)
    s = lcrng(s); local misc1 = xor16(r16(data_base + 24), s)
    local form = (misc1 >> 3) & 0x1F
    return {
        moves  = {m1, m2, m3, m4},
        pp     = {pp12 & 0xFF, (pp12 >> 8) & 0xFF, pp34 & 0xFF, (pp34 >> 8) & 0xFF},
        pp_ups = {up12 & 0xFF, (up12 >> 8) & 0xFF, up34 & 0xFF, (up34 >> 8) & 0xFF},
        form   = form,
        isEgg  = isEgg,
    }
end

-- Decrypt Block C (nickname): returns a Lua string (ASCII, up to 10 chars).
-- Block C layout: nickname is 11 × u16 (Gen IV charcode, 0xFFFF terminated).
-- Gen 5: same shuffle + LCRNG, but characters are UTF-16LE (printable ASCII passes through).
function M.readNickname(pkm_addr)
    local pid = r32(pkm_addr)
    if pid == 0 then return nil end
    local order_val = _block_order(pid)
    local blk_off   = BLOCK_C_OFF[order_val] or 0
    local data_base = pkm_addr + 0x008 + blk_off
    local chars = {}
    -- Both Gen 4 and Gen 5: always LCRNG-encrypted in live RAM (no plaintext shortcut)
    local chk       = r16(pkm_addr + 0x006)
    local word_base = blk_off >> 1
    local s = chk
    for _ = 1, word_base do s = lcrng(s) end
    if TRAINER_NAME_ENCODING == "gen5" then
        -- Gen 5: UTF-16LE-compatible. Printable ASCII 0x0020-0x007E passes through.
        -- Non-ASCII chars (Japanese, accented) are silently skipped.
        for i = 0, 10 do
            s = lcrng(s)
            local c = xor16(r16(data_base + i * 2), s)
            if c == 0xFFFF or c == 0x0000 then break end
            if c >= 0x0020 and c <= 0x007E then
                chars[#chars+1] = string.char(c)
            end
        end
    else
        -- Gen 4: custom charcode table (289-350 = digits/upper/lower)
        for i = 0, 10 do
            s = lcrng(s)
            local c = xor16(r16(data_base + i * 2), s)
            if c == 0xFFFF or c == 0x0000 then break end
            if     c >= 289 and c <= 298 then chars[#chars+1] = string.char(c - 241)
            elseif c >= 299 and c <= 324 then chars[#chars+1] = string.char(c - 234)
            elseif c >= 325 and c <= 350 then chars[#chars+1] = string.char(c - 228)
            elseif c == 478 then chars[#chars+1] = " "
            elseif c == 446 then chars[#chars+1] = "-"
            elseif c == 435 then chars[#chars+1] = "'"
            elseif c == 430 then chars[#chars+1] = "."
            else chars[#chars+1] = "?"
            end
        end
    end
    return #chars > 0 and table.concat(chars) or nil
end

-- ── PartyPokemon struct field offsets ─────────────────────────────────────────
-- Source: pret/pokeheartgold include/pokemon_types_def.h
-- dataBlocks[4] at +0x008–+0x087 are PRNG-encrypted.
-- NEVER write those bytes without re-encrypting.
M.PKM = {
    PID    = 0x000,  -- u32  personality (unencrypted, stable identity)
    FLAGS  = 0x004,  -- u16  partyDecrypted:1, boxDecrypted:1, checksumFailed:1
    CHKSUM = 0x006,  -- u16  CRC-16-CCITT of dataBlocks
    -- dataBlocks: 0x008–0x087 (encrypted)
    STATUS = 0x088,  -- u32  status condition (party only)
    LEVEL  = 0x08C,  -- u8   level (party only)
    -- ballCapsuleID at 0x08D
    CUR_HP = 0x08E,  -- u16  current HP (party only)  ← force_faint target
    MAX_HP = 0x090,  -- u16  max HP (party only)
    -- atk=0x092, def=0x094, speed=0x096, spatk=0x098, spdef=0x09A
}

M.MON_SIZE = 0xEC   -- sizeof(PartyPokemon) = 236 bytes

-- ── Bag pocket constants ───────────────────────────────────────────────────────
M.BAG = {
    BALLS_COUNT = 24,   -- balls pocket holds 24 × 4-byte ItemSlots {u16 id, u16 qty}
}

-- ── Ball item ID ranges ────────────────────────────────────────────────────────
-- 0x0001–0x0010: Master Ball → Cherish Ball (standard)
-- 0x01EC–0x01F4: Kurt / Apricorn balls (HGSS-exclusive)
M.BALL_ID_MIN  = 0x0001
M.BALL_ID_MAX  = 0x0010
M.BALL_APRICORN_MIN = 0x01EC
M.BALL_APRICORN_MAX = 0x01F4

-- ── Active profile values (upvalues) ─────────────────────────────────────────
-- All address constants are stored as module-level locals so that M.applyProfile()
-- can reassign them and every function that captures them as upvalues immediately
-- sees the new values. Default values are the confirmed HGSS US 1.0 addresses.
--
-- HGSS pointer chain (source: pret/pokeheartgold include/save.h, src/save.c):
--   p1   = r32(P1_PTR_ADDR) & 0xFFFFFF
--   base = r32(p1 + BASE_PTR_OFF) & 0xFFFFFF  →  SaveData*
--   base+PARTY_COUNT_OFF = PartyCore.curCount
--   base+PARTY_OFF       = PartyCore.mons[0]
local P1_PTR_ADDR        = 0x0BA8    -- u32_le ptr to p1; & 0xFFFFFF = p1
local BASE_PTR_OFF       = 0x20      -- offset within p1 to save-data base pointer

-- PC storage (source: pret/pokeheartgold include/pokemon_storage_system.h, src/save.c):
--   arrayHeaders[41] (SAVE_PCSTORAGE) at base+0x232A4
--   arrayHeaders[41].offset field (3rd u32 in 0x10-byte header) at base+0x232AC
--   PC storage base = base + 0x10 + r32(base + PC_ARRAY_HDR_OFF)
local PC_ARRAY_HDR_OFF   = 0x232AC   -- arrayHeaders[SAVE_PCSTORAGE].offset field
local PC_BOX_STRIDE      = 0x1000    -- bytes per PC_BOX (30 slots + padding)
local PC_SLOT_STRIDE     = 0x88      -- bytes per BoxPokemon slot

-- Party / battle copy offsets (relative to resolved base pointer)
local PARTY_COUNT_OFF    = 0xA4      -- u8, party count (0-6)
local PARTY_OFF          = 0xA8      -- PartyPokemon[0]; stride = MON_SIZE
local PLAYER_BATTLE_OFF  = 0x4EA98   -- player battle copy slot 0; stride = MON_SIZE
local ENEMY_BATTLE_OFF   = 0x4F068   -- enemy battle party slot 0; stride = MON_SIZE

-- Bag (relative to base pointer)
local BALLS_POCKET_OFF   = 0xD14     -- ball pocket base; 24 × {u16 id, u16 qty}
local BALLS_POCKET_COUNT = 24        -- number of item slots in ball pocket

-- Zone ID pointer: base+ZONE_ID_OFF is a pointer; the u16 two bytes in = zone.
-- Falls back to ptr+2 if direct read returns 0. Confirmed in live T3 tests.
local ZONE_ID_OFF        = 0x25FE4
local ZONE_ID_MAX        = 0x220     -- plausibility upper bound (HGSS: 540 zones, max ID 0x21B)

-- Enemy trainer ID: u16 at base+TRAINER_ID_OFF (0 = wild battle).
-- Confirmed against live wild/trainer battles (NDS-Ironmon-Tracker MemoryAddresses.lua).
local TRAINER_ID_OFF     = 0x440AA

-- Gym badge bitmasks (HGSS):
--   BADGES_1 = Johto  (bit 0=Zephyr … bit 7=Rising)
--   BADGES_2 = Kanto  (bit 0=Boulder … bit 7=Earth)
-- For Platinum: BADGES_1 = Sinnoh (bit 0=Coal … bit 7=Beacon); BADGES_2_OFF = nil.
local BADGES_1_OFF       = 0x8E
local BADGES_2_OFF       = 0x93      -- nil for Platinum

-- Player trainer name: u16[8] at base+PLAYER_NAME_OFF (PlayerProfile.name).
-- Source: pret/pokeheartgold include/player_data.h (johtoBadges at profile+0x1A).
-- Chars are standard Unicode; Latin letters match ASCII. EOS = 0xFFFF or 0x0000.
local PLAYER_NAME_OFF    = 0x74

-- Battle status: absolute RAM address (not base-relative); non-zero in any battle.
-- Source: HGSS disassembly — stable in US 1.0.
local BATTLE_STATUS_ADDR = 0x246F48

-- Battle mode (Gen 5 only): absolute RAM address, u8.
-- Values per NDS-Ironmon-Tracker BattleHandlerGen5.lua:
--   0 = single, 1 = double, 2 = triple, 3 = rotation
-- Gen 4 leaves this nil; isDoubleBattle() returns false in that case.
local BATTLE_MODE_ADDR   = nil

-- Memorial box index (0-based). Box 17 = UI "Box 18" = "THE DEAD".
-- Both HGSS and Platinum use 18-box storage; memorial is the last box.
local MEMORIAL_BOX       = 17

-- Max National Pokédex species ID accepted by Block A decryption.
-- Gen 4 = 493 (Arceus); Gen 5 = 649 (Genesect). Set via profile.
local SPECIES_MAX        = 493

-- ── Gen 5 direct-addressing mode ─────────────────────────────────────────────
-- Gen 5 (Black/White/Black2/White2) uses fixed absolute RAM addresses instead of
-- the Gen 4 two-level pointer chain. When DIRECT_ADDR = true:
--   • M.init() sets M._base = 0 (truthy in Lua) and skips pointer resolution.
--   • All M._base + OFF expressions evaluate to the absolute address directly.
--   • ZONE_ID_DIRECT disables the Gen 4 zone ID pointer-fallback branch.
--   • PC_STORAGE_BASE replaces the Gen 4 PC array-header dereference.
--   • TRAINER_NAME_ENCODING switches readTrainerName() to UTF-16 passthrough.
local DIRECT_ADDR          = false   -- true for Gen 5
local ZONE_ID_DIRECT       = false   -- true for Gen 5 (no pointer fallback on zone==0)
local PC_STORAGE_BASE      = nil     -- Gen 5 direct PC box[0] base addr (nil = Gen 4 method)
local PC_STORAGE_BASE_ALT  = nil     -- Gen 5 fallback candidate (probed if primary reads zero)
local TRAINER_NAME_ENCODING = "gen4" -- "gen4" or "gen5" (UTF-16 passthrough)
local BOXES_COUNT          = 18      -- 18 (Gen 4) or 24 (Gen 5)
local PC_CURRENT_BOX_OFF   = 0x12000 -- offset from pcStorageBase to currentBox u8

-- ── M.applyProfile ────────────────────────────────────────────────────────────
-- Call once at startup (after variant detection) to apply a game-specific address
-- profile. Only fields present in the table are updated; nil fields keep defaults.
-- See gen4_hgsspt.lua for profile definitions.
function M.applyProfile(p)
    if not p then return end
    if p.P1_PTR_ADDR        ~= nil then P1_PTR_ADDR        = p.P1_PTR_ADDR        end
    if p.BASE_PTR_OFF        ~= nil then BASE_PTR_OFF       = p.BASE_PTR_OFF       end
    if p.PC_ARRAY_HDR_OFF    ~= nil then PC_ARRAY_HDR_OFF   = p.PC_ARRAY_HDR_OFF   end
    if p.PARTY_COUNT_OFF     ~= nil then PARTY_COUNT_OFF    = p.PARTY_COUNT_OFF    end
    if p.PARTY_OFF           ~= nil then PARTY_OFF          = p.PARTY_OFF          end
    if p.PLAYER_BATTLE_OFF   ~= nil then PLAYER_BATTLE_OFF  = p.PLAYER_BATTLE_OFF  end
    if p.ENEMY_BATTLE_OFF    ~= nil then ENEMY_BATTLE_OFF   = p.ENEMY_BATTLE_OFF   end
    if p.BALLS_POCKET_OFF    ~= nil then BALLS_POCKET_OFF   = p.BALLS_POCKET_OFF   end
    if p.BALLS_POCKET_COUNT  ~= nil then
        BALLS_POCKET_COUNT = p.BALLS_POCKET_COUNT
        M.BAG.BALLS_COUNT  = p.BALLS_POCKET_COUNT  -- keep export in sync
    end
    if p.ZONE_ID_OFF         ~= nil then ZONE_ID_OFF        = p.ZONE_ID_OFF        end
    if p.ZONE_ID_MAX         ~= nil then ZONE_ID_MAX        = p.ZONE_ID_MAX        end
    if p.TRAINER_ID_OFF      ~= nil then TRAINER_ID_OFF     = p.TRAINER_ID_OFF     end
    if p.BADGES_1_OFF        ~= nil then BADGES_1_OFF       = p.BADGES_1_OFF       end
    -- BADGES_2_OFF may be explicitly set to false/nil to disable the second badge set.
    if p.BADGES_2_OFF ~= nil then BADGES_2_OFF = p.BADGES_2_OFF end
    if rawget(p, "BADGES_2_OFF") == false then BADGES_2_OFF = nil end
    if p.PLAYER_NAME_OFF     ~= nil then PLAYER_NAME_OFF    = p.PLAYER_NAME_OFF    end
    if p.BATTLE_STATUS_ADDR  ~= nil then BATTLE_STATUS_ADDR = p.BATTLE_STATUS_ADDR end
    if p.MEMORIAL_BOX        ~= nil then
        MEMORIAL_BOX   = p.MEMORIAL_BOX
        M.MEMORIAL_BOX = p.MEMORIAL_BOX
    end
    -- Gen 5 direct-addressing mode fields
    if p.DIRECT_ADDR           ~= nil then DIRECT_ADDR           = p.DIRECT_ADDR           end
    if p.ZONE_ID_DIRECT        ~= nil then ZONE_ID_DIRECT        = p.ZONE_ID_DIRECT        end
    if p.PC_STORAGE_BASE       ~= nil then PC_STORAGE_BASE       = p.PC_STORAGE_BASE       end
    if p.PC_STORAGE_BASE_ALT   ~= nil then PC_STORAGE_BASE_ALT   = p.PC_STORAGE_BASE_ALT   end
    if p.TRAINER_NAME_ENCODING ~= nil then TRAINER_NAME_ENCODING = p.TRAINER_NAME_ENCODING end
    if p.MON_SIZE              ~= nil then M.MON_SIZE            = p.MON_SIZE              end
    if p.PC_BOX_STRIDE         ~= nil then PC_BOX_STRIDE         = p.PC_BOX_STRIDE         end
    if p.BOXES_COUNT           ~= nil then BOXES_COUNT           = p.BOXES_COUNT           end
    if p.PC_CURRENT_BOX_OFF    ~= nil then PC_CURRENT_BOX_OFF    = p.PC_CURRENT_BOX_OFF    end
    if p.SPECIES_MAX           ~= nil then SPECIES_MAX           = p.SPECIES_MAX           end
    if p.BATTLE_MODE_ADDR      ~= nil then BATTLE_MODE_ADDR      = p.BATTLE_MODE_ADDR      end
end

-- Export read-only profile values for callers that need them.
M.MEMORIAL_BOX = MEMORIAL_BOX

-- ── Cached base pointer ───────────────────────────────────────────────────────
M._base = nil

-- ── Live HP debounce cache ────────────────────────────────────────────────────
-- Updated by M.init() every frame. Filters the 1-2 frame garbage that appears
-- when the game decrypts/re-encrypts the battle-stat block between turns.
-- Entry layout: {cand, frames, conf}
--   cand   = last raw slot read
--   frames = consecutive frames cand has been stable
--   conf   = last value confirmed stable for ≥2 frames (nil until confirmed)
-- Callers use M.partyHP / M.battleHP / M.enemyHP for debounced access.
-- M.readPartySlot / M.readBattleSlot / M.readEnemySlot remain instant raw reads.
local _db_party  = {}   -- [slot 0-5]
local _db_battle = {}   -- [slot 0-5]
local _db_enemy  = {}   -- [slot 0-5]

local function _slot_eq(a, b)
    if a == nil and b == nil then return true end
    if a == nil or b == nil  then return false end
    return a.key == b.key and a.hp == b.hp and a.maxHP == b.maxHP and a.level == b.level
end

local function _db_update(cache, slot, raw)
    local s = cache[slot]
    if not s then
        cache[slot] = {cand = raw, frames = 1, conf = nil}
        return
    end
    if _slot_eq(raw, s.cand) then
        s.frames = s.frames + 1
        if s.frames >= 2 then s.conf = raw end
    else
        s.cand   = raw
        s.frames = 1
    end
end

-- Clear all debounce caches (call on battle start and battle end so the new
-- copy — battle or party — settles from scratch without stale confirmed values).
function M.clearDebounce()
    _db_party  = {}
    _db_battle = {}
    _db_enemy  = {}
end

-- ── M.init() ─────────────────────────────────────────────────────────────────
-- Resolve the base pointer (Gen 4: two-level chain; Gen 5: set base = 0 directly)
-- and update the per-slot debounce caches.
-- Must be called every frame before any address helper.
-- Returns base (integer, 0 for Gen 5) or nil when save is not loaded.
function M.init()
    if DIRECT_ADDR then
        -- Gen 5: all addresses are absolute; no pointer chain.
        -- Use party count as a plausibility check (must be 0-6).
        -- Note: PARTY_COUNT_OFF is the absolute address (M._base will be 0).
        local n = r8(PARTY_COUNT_OFF)
        if n > 6 then
            if M._base then M.clearDebounce() end
            M._base = nil; return nil
        end
        M._base = 0   -- 0 is truthy in Lua; signals direct-addressing mode active
    else
        local p1 = r32(P1_PTR_ADDR) & 0xFFFFFF
        if p1 == 0 then
            if M._base then M.clearDebounce() end
            M._base = nil; return nil
        end
        local base = r32(p1 + BASE_PTR_OFF) & 0xFFFFFF
        if base == 0 then
            if M._base then M.clearDebounce() end
            M._base = nil; return nil
        end
        M._base = base
    end
    for i = 0, 5 do
        _db_update(_db_party,  i, M.readPartySlot(i))
        _db_update(_db_battle, i, M.readBattleSlot(i))
        _db_update(_db_enemy,  i, M.readEnemySlot(i))
    end
    return M._base
end

-- ── Pre-write validation ────────────────────────────────────────────────────
-- Performs a multi-point sanity check on live save RAM to confirm the save is
-- loaded and not corrupted. Returns (true, nil) on success or (false, reason)
-- on failure. Use to gate writes_enabled — prevent force_faint / memorialize /
-- box_mon / party_mon from firing when the game state is garbage (title screen,
-- mid-save, reset).
--
-- Gen 4 checks:
--   1. Base pointer chain resolves (M._base non-nil and non-zero)
--   2. Party count u8 is 0–6
--   3. PC storage arrayHeaders[41].offset is in valid range
--   4. Zone ID pointer dereferences to a plausible value (< ZONE_ID_MAX)
--   5. Player name starts with a valid Gen IV char code (not 0x0000)
-- Gen 5 checks (DIRECT_ADDR mode): skip #1 (no pointer chain) and #3 (no PC array header).
function M.validateSave()
    if not DIRECT_ADDR then
        -- 1. Base pointer (Gen 4 only)
        if not M._base then return false, "base pointer not resolved" end
    else
        if M._base == nil then return false, "base not initialized" end
    end

    -- 2. Party count
    local raw_count = r8(M._base + PARTY_COUNT_OFF)
    if raw_count > 6 then
        return false, fmt("party count=%d (expected 0-6)", raw_count)
    end

    -- 3. PC storage header offset (Gen 4 only; Gen 5 uses PC_STORAGE_BASE)
    if not DIRECT_ADDR and PC_ARRAY_HDR_OFF then
        local pc_off = r32(M._base + PC_ARRAY_HDR_OFF)
        if pc_off < 0x100 or pc_off >= 0x23000 then
            return false, fmt("PC header offset=0x%X (expected 0x100-0x22FFF)", pc_off)
        end
    end

    -- 4. Zone ID plausibility
    local zone
    if ZONE_ID_DIRECT then
        zone = r16(M._base + ZONE_ID_OFF)
    else
        zone = r16(M._base + ZONE_ID_OFF)
        if zone == 0 then
            local ptr = r32(M._base + ZONE_ID_OFF) & 0xFFFFFF
            if ptr ~= 0 then zone = r16(ptr + 2) end
        end
    end
    if zone > ZONE_ID_MAX then
        return false, fmt("zone ID=0x%X (expected < 0x%X)", zone, ZONE_ID_MAX)
    end

    -- 5. Player name first char
    if PLAYER_NAME_OFF then
        local first_char = r16(M._base + PLAYER_NAME_OFF)
        if TRAINER_NAME_ENCODING == "gen5" then
            -- Gen 5: 0xFFFF = EOS (save not loaded or no name); 0x0000 also invalid
            if first_char == 0x0000 or first_char == 0xFFFF then
                return false, "player name is empty (save not loaded)"
            end
        else
            -- Gen 4: valid charcodes start at 0x0121 (289); 0x0000 = not loaded
            if first_char == 0x0000 then
                return false, "player name starts with 0x0000 (save not loaded)"
            end
        end
    end

    return true, nil
end

-- ── Address helpers ───────────────────────────────────────────────────────────

-- Absolute address (Main RAM domain offset) of party slot i (0-based).
-- Returns nil when M._base is not set.
function M.partyAddr(slot)
    if not M._base then return nil end
    return M._base + PARTY_OFF + slot * M.MON_SIZE
end

-- Absolute address of player battle copy slot i.
-- Returns nil when M._base is not set.
function M.playerBattleAddr(slot)
    if not M._base then return nil end
    return M._base + PLAYER_BATTLE_OFF + slot * M.MON_SIZE
end

-- Absolute address of enemy battle party slot i.
-- Returns nil when M._base is not set.
function M.enemyBattleAddr(slot)
    if not M._base then return nil end
    return M._base + ENEMY_BATTLE_OFF + slot * M.MON_SIZE
end

-- ── Party count ───────────────────────────────────────────────────────────────

-- Returns party count (0-6). Returns 0 when base is not set or count > 6.
function M.readPartyCount()
    if not M._base then return 0 end
    local n = r8(M._base + PARTY_COUNT_OFF)
    return (n > 6) and 0 or n
end

-- Write party count (used by exec_party_mon after adding a slot).
function M.writePartyCount(n)
    if not M._base then return end
    memory.write_u8(M._base + PARTY_COUNT_OFF, n, RAM)
end

-- ── Zone ID ───────────────────────────────────────────────────────────────────

-- Returns the current zone ID (u16).
-- Gen 4: tries a direct u16 read; falls back to dereferencing as a u32 pointer
-- and reading u16 at ptr+2 if direct read returns 0 (zone ID stored via pointer).
-- Gen 5: reads absolute ZONE_ID_OFF directly; zone 0 is valid (Black City/Marine Tube),
-- so the Gen 4 pointer fallback is skipped when ZONE_ID_DIRECT = true.
function M.readZoneID()
    if M._base == nil then return 0 end
    local zone = r16(M._base + ZONE_ID_OFF)
    -- Gen 5: zone 0 is a valid map; skip the pointer-fallback branch.
    -- Gen 4: zone 0 means use the parent header pointer (fallback to ZONE_ID_OFF+2).
    if zone == 0 and not ZONE_ID_DIRECT then
        local ptr = r32(M._base + ZONE_ID_OFF) & 0xFFFFFF
        if ptr ~= 0 then
            zone = r16(ptr + 2)
        end
    end
    return zone
end

-- ── Gym badges ────────────────────────────────────────────────────────────────

-- Returns the primary badge bitmask (u8): Johto in HGSS, Sinnoh in Platinum.
-- Bit 0 = first badge, bit 7 = eighth badge.
function M.readBadges1()
    if not M._base or not BADGES_1_OFF then return 0 end
    return r8(M._base + BADGES_1_OFF) or 0
end

-- Returns the secondary badge bitmask (u8): Kanto in HGSS, nil/0 in Platinum.
-- Returns 0 when the profile has no secondary badge set (BADGES_2_OFF = nil).
function M.readBadges2()
    if not M._base or not BADGES_2_OFF then return 0 end
    return r8(M._base + BADGES_2_OFF) or 0
end

-- Backward-compat aliases (HGSS-named variants still work).
M.readJohtoBadges = M.readBadges1
M.readKantoBadges = M.readBadges2

-- Returns the player's trainer name as an ASCII string (up to 7 chars).
-- Gen IV uses a custom 16-bit character encoding (pret/pokeheartgold charcode.h),
-- NOT standard Unicode. Key mappings (decimal values from charcode.h):
--   CHAR_0..CHAR_9   = 289..298   CHAR_A..CHAR_Z = 299..324
--   CHAR_a..CHAR_z   = 325..350   CHAR_SPACE = 478
--   CHAR_HYPHEN=446  CHAR_RAPOST=435  CHAR_PERIOD=430
--   EOS = 0xFFFF (end-of-string)
-- Unknown chars are silently skipped. Returns "" when base is not set.
function M.readTrainerName()
    if M._base == nil then return "" end
    if not PLAYER_NAME_OFF then return "" end
    local chars = {}
    if TRAINER_NAME_ENCODING == "gen5" then
        -- Gen 5: UTF-16LE-compatible encoding. Printable ASCII range 0x0020–0x007E
        -- passes through directly. EOS = 0xFFFF. Up to 7 visible chars + terminator.
        for i = 0, 7 do
            local c = r16(M._base + PLAYER_NAME_OFF + i * 2)
            if c == 0xFFFF or c == 0x0000 then break end
            if c >= 0x0020 and c <= 0x007E then
                chars[#chars+1] = string.char(c)
            end
            -- Non-ASCII chars (Japanese, accented) are silently skipped.
        end
    else
        -- Gen 4: custom charcode table (289–350 = digits+uppercase+lowercase, etc.)
        for i = 0, 7 do
            local c = r16(M._base + PLAYER_NAME_OFF + i * 2)
            if c == 0xFFFF or c == 0x0000 then break end
            if     c >= 289 and c <= 298 then chars[#chars+1] = string.char(c - 241)  -- '0'=48; 289-48=241
            elseif c >= 299 and c <= 324 then chars[#chars+1] = string.char(c - 234)  -- 'A'=65; 299-65=234
            elseif c >= 325 and c <= 350 then chars[#chars+1] = string.char(c - 228)  -- 'a'=97; 325-97=228
            elseif c == 478 then chars[#chars+1] = " "
            elseif c == 446 then chars[#chars+1] = "-"
            elseif c == 435 then chars[#chars+1] = "'"
            elseif c == 430 then chars[#chars+1] = "."
            -- other control/symbol chars: silently skip
            end
        end
    end
    return table.concat(chars)
end

-- ── Bag ──────────────────────────────────────────────────────────────────────

-- Absolute address of the balls pocket. Returns nil when base is not set.
function M.bagBallsAddr()
    if not M._base then return nil end
    return M._base + BALLS_POCKET_OFF
end

-- Returns {id=..., qty=...} for item slot i within the pocket at addr.
function M.readItemSlot(addr, i)
    local off = addr + i * 4
    return { id = r16(off), qty = r16(off + 2) }
end

-- ── Battle state ──────────────────────────────────────────────────────────────

-- Returns true when in any battle (wild or trainer).
-- Method: the player-battle copy slot 0 (at base+PLAYER_BATTLE_OFF) holds the
-- active party mon's PID when in battle, and 0 when in the overworld.  We also
-- confirm it matches party slot 0 PID to rule out stale data.
-- Reference: NDS-Ironmon-Tracker BattleHandlerGen4._tryToFetchBattleData.
function M.isInBattle()
    if not M._base then return false end
    local battle_pid = r32(M._base + PLAYER_BATTLE_OFF)
    if battle_pid == 0 then return false end
    local party_pid  = r32(M._base + PARTY_OFF)
    return battle_pid == party_pid
end

-- Returns true when likely in a wild battle (heuristic: enemy trainer ID == 0).
-- Confirmed working against both wild battles and trainer battles (live T3 tests).
function M.isWildBattle()
    if not M.isInBattle() then return false end
    if not M._base then return false end
    return r16(M._base + TRAINER_ID_OFF) == 0
end

-- Returns the enemy trainer ID (u16). 0 = wild battle.
function M.readEnemyTrainerId()
    if not M._base then return 0 end
    return r16(M._base + TRAINER_ID_OFF)
end

-- Returns the enemy trainer name as a string (u16 chars at base+0x440AC, up to 8 chars).
-- In HGSS, trainer name follows trainer ID in the battle work struct.
function M.readEnemyTrainerName()
    if not M._base then return "" end
    local name_off = TRAINER_ID_OFF + 2  -- name immediately after trainer ID (u16[8])
    local chars = {}
    for i = 0, 7 do
        local c = r16(M._base + name_off + i * 2)
        if c == 0xFFFF or c == 0x0000 then break end
        if c >= 0x20 and c < 0x7F then
            chars[#chars + 1] = string.char(c)
        end
    end
    return table.concat(chars)
end

-- Returns true when not in battle (inverse of isInBattle).
function M.isInOverworld()
    return not M.isInBattle()
end

-- Returns true when the current battle is a double / triple / rotation battle.
-- Reads u8 at BATTLE_MODE_ADDR (Gen 5 only). Returns false for Gen 4 (addr nil)
-- or when not in battle. Values: 0=single, 1=double, 2=triple, 3=rotation.
function M.isDoubleBattle()
    if not BATTLE_MODE_ADDR then return false end
    if not M.isInBattle() then return false end
    local mode = r8(BATTLE_MODE_ADDR)
    return mode == 1 or mode == 2 or mode == 3
end

-- ── Party state ───────────────────────────────────────────────────────────────

-- Returns true when every occupied party slot has curHP == 0.
-- Returns false when the party is empty.
function M.allPartyFainted()
    local n = M.readPartyCount()
    if n == 0 then return false end
    local any = false
    for i = 0, n - 1 do
        local a = M.partyAddr(i)
        if a then
            local pid = r32(a)
            if pid ~= 0 and r16(a + M.PKM.CHKSUM) ~= 0 then
                any = true
                local _, curHP, _ = decrypt_stats(a + M.PKM.STATUS, pid)
                if curHP > 0 then return false end
            end
        end
    end
    return any
end

-- Write curHP = maxHP to the party slot (and battle copy if in battle).
-- Used to undo a force-faint in testing. Reads decrypted maxHP then re-encrypts
-- it with s4's keystream before writing back to the curHP field.
function M.restoreHP(slot)
    local function write_enc(a, plain_val)
        local pid = r32(a)
        if pid == 0 then return false end
        local s = lcrng(lcrng(lcrng(lcrng(pid))))  -- 4 advances → s4 (keys curHP)
        w16(a + M.PKM.CUR_HP, xor16(plain_val, s))
        return true
    end
    local p = M.partyAddr(slot)
    if not p then return end
    local pid = r32(p)
    if pid == 0 then return end
    local _, _, maxHP = decrypt_stats(p + M.PKM.STATUS, pid)
    if maxHP == 0 then return end
    write_enc(p, maxHP)
    local b = M.playerBattleAddr(slot)
    if b then
        local bpid = r32(b)
        if bpid ~= 0 then
            local _, _, bmaxHP = decrypt_stats(b + M.PKM.STATUS, bpid)
            if bmaxHP > 0 then write_enc(b, bmaxHP) end
        end
    end
end

-- Write curHP = 0 to the party slot AND to the player battle copy.
-- The field is encrypted, so we write the XOR-keystream value that decrypts to 0.
function M.forceFaint(slot)
    local function enc_zero(a)
        local pid = r32(a)
        if pid == 0 then return nil end
        -- 4 LCRNG steps from PID reach s4, which keys the curHP word (offset 6).
        local s = lcrng(lcrng(lcrng(lcrng(pid))))
        return (s >> 16) & 0xFFFF   -- XOR with 0 = key itself = encrypted zero
    end
    local p = M.partyAddr(slot)
    if p then
        local enc = enc_zero(p)
        if enc then w16(p + M.PKM.CUR_HP, enc) end
    end
    local b = M.playerBattleAddr(slot)
    if b then
        local enc = enc_zero(b)
        if enc then w16(b + M.PKM.CUR_HP, enc) end
    end
end

-- ── PC Storage helpers ────────────────────────────────────────────────────────

-- Returns the base address of PCStorage.boxes[0] (Box 1, Slot 0) in RAM,
-- or nil if the save is not loaded / base pointer not resolved.
-- Reads arrayHeaders[SAVE_PCSTORAGE=41].offset live from RAM each call.
-- Formula: saveData + 0x10 + arrayHeaders[41].offset
--   saveData      = M._base   (confirmed: base = SaveData*)
--   PC_ARRAY_HDR_OFF = 0x232AC  (saveData + 0x23014 + 41*0x10 + 8)
-- Gen 5: PC storage is at an absolute address (PC_STORAGE_BASE); no array header needed.
-- Probe a Gen 5 PC base candidate by checking the first 4 slots of Box 0.
-- A valid PC base will have at least one slot whose PID is non-zero on most
-- saves; an empty save returns 0 for all slots. We accept the address if the
-- first 4 PIDs are all 0 OR at least one is non-zero (i.e., we reject only
-- when we read clearly invalid garbage — but in practice empty saves are
-- rare enough that this probe primarily distinguishes between candidates).
local function _gen5_pc_base_looks_valid(base)
    if not base or base == 0 then return false end
    -- Sample 4 slots of box 0; reject if all read as 0xFFFFFFFF (uninit memory).
    local stride = 0x88   -- PC_SLOT_STRIDE for Gen 5
    local all_ff = true
    for slot = 0, 3 do
        local pid = r32(base + slot * stride)
        if pid ~= 0xFFFFFFFF then all_ff = false; break end
    end
    return not all_ff
end

function M.pcStorageBase()
    if DIRECT_ADDR then
        -- Gen 5: PC_STORAGE_BASE is a direct absolute address set in the profile.
        -- If a fallback candidate is configured and the primary looks invalid
        -- (all-0xFFFFFFFF reads), swap to the alt. Once swapped, the choice
        -- persists for the session.
        if PC_STORAGE_BASE and not _gen5_pc_base_looks_valid(PC_STORAGE_BASE)
           and PC_STORAGE_BASE_ALT and _gen5_pc_base_looks_valid(PC_STORAGE_BASE_ALT) then
            PC_STORAGE_BASE = PC_STORAGE_BASE_ALT
            PC_STORAGE_BASE_ALT = nil
        end
        return PC_STORAGE_BASE
    end
    if not M._base then return nil end
    local chunk_off = r32(M._base + PC_ARRAY_HDR_OFF)
    -- Valid PC chunk offset must be non-zero and within dynamic_region (0x23000 bytes).
    -- In practice it will be well above 0x100 (all 40 prior chunks precede it).
    if chunk_off < 0x100 or chunk_off >= 0x23000 then return nil end
    return M._base + 0x10 + chunk_off
end

-- Returns the RAM address of BoxPokemon at PC box `box` (0-based, 0=Box 1)
-- and slot `slot` (0-based, 0=first slot), or nil if PC storage is inaccessible.
function M.pcBoxAddr(box, slot)
    local base_pc = M.pcStorageBase()
    if not base_pc then return nil end
    return base_pc + box * PC_BOX_STRIDE + slot * PC_SLOT_STRIDE
end

-- Returns the index (0-based) of the first empty slot in PC box `box`, or nil
-- if all 30 slots are occupied or PC storage is inaccessible.
-- An empty slot has PID == 0 at its base address.
function M.pcBoxFirstEmpty(box)
    for slot = 0, 29 do
        local addr = M.pcBoxAddr(box, slot)
        if not addr then return nil end
        if r32(addr) == 0 then return slot end
    end
    return nil   -- box is full
end

-- Read the "current box" index (0-based) from PCStorage.
-- PCStorage struct: boxes[BOXES_COUNT] (each 0x1000) followed by currentBox (u8) at PC_CURRENT_BOX_OFF.
-- Box names: u16[9] × BOXES_COUNT at pcStorageBase + 0x12004 (Gen 4) or similar (Gen 5: VERIFY_ME).
-- pret/pokeheartgold PCStorage: boxNames[NUM_BOXES][BOX_NAME_LENGTH+1] (each entry = 9 u16 = 18 bytes).
local PC_BOX_NAMES_OFF   = 0x12004  -- confirmed via NDS-Ironmon-Tracker MemoryAddresses
local PC_BOX_NAME_STRIDE = 0x12     -- 18 bytes (9 u16 chars) per box name

function M.readCurrentBox()
    local base_pc = M.pcStorageBase()
    if not base_pc then return 0 end
    local idx = r8(base_pc + PC_CURRENT_BOX_OFF)
    return (idx < BOXES_COUNT) and idx or 0
end

-- Rename a PC box. Converts ASCII name to Gen IV charcodes (u16).
-- box is 0-based (0 = Box 1). Max 8 chars (terminator at position 8).
-- Gen IV charcode: A-Z=299-324, a-z=325-350, 0-9=289-298, space=478, EOS=0xFFFF.
function M.renameBox(box, name)
    local base_pc = M.pcStorageBase()
    if not base_pc then return false end
    local addr = base_pc + PC_BOX_NAMES_OFF + box * PC_BOX_NAME_STRIDE
    for i = 1, 9 do
        if i > #name then
            w16(addr + (i - 1) * 2, 0xFFFF)
        else
            local byte = name:byte(i)
            local charcode
            if byte >= 65 and byte <= 90 then       -- A-Z
                charcode = 299 + (byte - 65)
            elseif byte >= 97 and byte <= 122 then  -- a-z
                charcode = 325 + (byte - 97)
            elseif byte >= 48 and byte <= 57 then   -- 0-9
                charcode = 289 + (byte - 48)
            elseif byte == 32 then                  -- space
                charcode = 478
            elseif byte == 45 then                  -- hyphen
                charcode = 446
            else
                charcode = 478  -- fallback to space
            end
            w16(addr + (i - 1) * 2, charcode)
        end
    end
    return true
end

-- Returns a set of PID hex strings for all occupied slots in a given box.
-- Used for battle_box_snapshot to detect party-full captures to PC.
function M.readBoxPIDs(box)
    local pids = {}
    for slot = 0, 29 do
        local addr = M.pcBoxAddr(box, slot)
        if addr then
            local pid = r32(addr)
            if pid ~= 0 then
                pids[fmt("%08X", pid)] = true
            end
        end
    end
    return pids
end

-- Copy the BoxPokemon (bytes 0x00..0x87) from party_addr to pc_addr.
-- Clears partyDecrypted (bit 0) and boxDecrypted (bit 1) in the flags u16 at +0x004
-- so the PC copy is treated as encrypted storage (matching normal PC box state).
-- The encrypted data can be copied verbatim: HGSS uses the same LCRNG cipher for
-- both party and PC storage; only the status flags differ.
function M.writeBoxMonFromParty(party_addr, pc_addr)
    for i = 0, PC_SLOT_STRIDE - 1 do
        memory.write_u8(pc_addr + i, memory.read_u8(party_addr + i, RAM), RAM)
    end
    local flags = memory.read_u16_le(pc_addr + 0x004, RAM)
    memory.write_u16_le(pc_addr + 0x004, flags & 0xFFFC, RAM)
end

-- Returns {key, level, hp, maxHP} for the slot, or nil if empty.
-- Battle-stat fields (level, curHP, maxHP) are PID-encrypted in live RAM
-- and must be decrypted before use.
function M.readPartySlot(slot)
    local a = M.partyAddr(slot)
    if not a then return nil end
    local pid = r32(a)
    if pid == 0 then return nil end
    local chk = r16(a + M.PKM.CHKSUM)
    if chk == 0 then return nil end
    local level, curHP, maxHP, status = decrypt_stats(a + M.PKM.STATUS, pid)
    if maxHP == 0 then return nil end
    return {
        key         = fmt("%08X", pid),
        level       = level,
        hp          = curHP,
        maxHP       = maxHP,
        status_cond = status,
    }
end

-- Returns {key, level, hp, maxHP, status_cond} from the player's battle copy for the slot,
-- or nil if the slot is empty / base not resolved.
-- Use during battle for live HP — the party copy only syncs at battle end.
function M.readBattleSlot(slot)
    local a = M.playerBattleAddr(slot)
    if not a then return nil end
    local pid = r32(a)
    if pid == 0 then return nil end
    local chk = r16(a + M.PKM.CHKSUM)
    if chk == 0 then return nil end
    local level, curHP, maxHP, status = decrypt_stats(a + M.PKM.STATUS, pid)
    if maxHP == 0 then return nil end
    return {
        key         = fmt("%08X", pid),
        level       = level,
        hp          = curHP,
        maxHP       = maxHP,
        status_cond = status,
    }
end

-- Returns {key, level, hp, maxHP, status_cond} from the enemy battle party for the slot,
-- or nil if the slot is empty / base not resolved.
function M.readEnemySlot(slot)
    local a = M.enemyBattleAddr(slot)
    if not a then return nil end
    local pid = r32(a)
    if pid == 0 then return nil end
    local chk = r16(a + M.PKM.CHKSUM)
    if chk == 0 then return nil end
    local level, curHP, maxHP, status = decrypt_stats(a + M.PKM.STATUS, pid)
    if maxHP == 0 then return nil end
    return {
        key         = fmt("%08X", pid),
        level       = level,
        hp          = curHP,
        maxHP       = maxHP,
        status_cond = status,
    }
end

function M.monKey(slotAddr)
    return fmt("%08X", r32(slotAddr))
end

-- ── Debounced HP accessors (updated by M.init each frame) ────────────────────
-- Falls back to a raw read if the cache has not yet confirmed a value
-- (e.g. the first frame after clearDebounce or initial load).
function M.partyHP(slot)
    local s = _db_party[slot]
    return (s and s.conf) or M.readPartySlot(slot)
end

function M.battleHP(slot)
    local s = _db_battle[slot]
    return (s and s.conf) or M.readBattleSlot(slot)
end

function M.enemyHP(slot)
    local s = _db_enemy[slot]
    return (s and s.conf) or M.readEnemySlot(slot)
end

return M
