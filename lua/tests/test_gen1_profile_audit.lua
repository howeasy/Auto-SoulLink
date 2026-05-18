--[[
  lua/tests/test_gen1_profile_audit.lua — Phase 0 raw-byte address audit (Gen 1)

  PURPOSE
    Read every address in the Gen 1 profile (Red/Blue OR Yellow, auto-detected
    from ROM title) and print its live value with plausibility commentary.
    Bypasses M.readPartySlot etc. — reads raw bytes via memory.read_u8 so an
    address error in the profile reveals itself rather than getting hidden by
    higher-level helpers.

    Run this in BizHawk while the ROM is loaded and progress through:
      (1) boot screen (before save loaded)
      (2) overworld (idle, e.g. Pallet Town starting point)
      (3) wild battle (e.g. Route 1 grass)
      (4) trainer battle (e.g. Brock)

    Press F1 at each state to dump a full snapshot, and F2 to dump just the
    candidate battle_flag bytes for the discrepancy investigation.

  Controls:
    F1 → full profile dump (every address + value + plausibility note)
    F2 → focused battle-flag dump (both 0xD057 and 0xD05A + surrounding bytes)
    F3 → dump party slot 0 raw 44 bytes (cross-check party_struct offsets)
    F4 → dump enemy battle struct raw 60 bytes (cross-check enemy struct)
--]]

local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
local _lua_root = _src:match("(.+[/\\])tests[/\\]") or _src
local _proj_root = _lua_root:match("(.+[/\\])lua[/\\]") or (_lua_root .. "../")
package.path = _src .. "?.lua;"
           .. _lua_root .. "?.lua;"
           .. _lua_root .. "games/?.lua;"
           .. _proj_root .. "data/games/gen1_rby/?.lua;"
           .. package.path

package.loaded["memory_gb"] = nil
package.loaded["games.gen1_rby"] = nil

local M = require("memory_gb")
local G = require("games.gen1_rby")

local variant = G.detect_variant()
if not variant then
    error("[T0-G1] Gen 1 ROM not detected — check ROM title")
end
local p = G.profiles[variant]
if not p then
    error("[T0-G1] No profile for variant: " .. tostring(variant))
end
M.initProfile(G, variant)

local fmt = string.format
local TAG = "[T0-G1]"

console.clear()
console.log(fmt("%s Phase 0 profile audit — variant=%s", TAG, variant))
console.log(fmt("%s Press F1=full dump  F2=battle_flag focus  F3=party slot 0 raw  F4=enemy struct raw", TAG))
console.log(fmt("%s Run F1 at each state: boot, overworld idle, wild battle, trainer battle", TAG))

-- ── Plausibility checks ───────────────────────────────────────────────────────
local function check_party_count(v) return v >= 0 and v <= 6, "expect 0..6" end
local function check_species(v) return v == 0xFF or (v >= 0 and v <= 190), "expect 0xFF terminator or species index ≤190" end
local function check_battle_flag(v) return v >= 0 and v <= 2, "expect 0=overworld, 1=wild, 2=trainer (-1 also valid)" end
local function check_map(v) return v >= 0 and v <= 0xF8, "expect map ID 0..0xF8" end
local function check_byte(v) return v >= 0 and v <= 0xFF, "any byte" end

-- ── Address table for the variant ─────────────────────────────────────────────
local addrs = {
    -- Party
    {"party_count_addr",       p.party_count_addr,       check_party_count, "wPartyCount"},
    {"party_species_addr[0]",  p.party_species_addr,     check_species,     "wPartySpecies first byte"},
    {"party_species_addr[1]",  p.party_species_addr + 1, check_species,     "second species"},
    {"party_species_addr[2]",  p.party_species_addr + 2, check_species,     "third"},
    {"party_species_addr[3]",  p.party_species_addr + 3, check_species,     "fourth"},
    {"party_species_addr[4]",  p.party_species_addr + 4, check_species,     "fifth"},
    {"party_species_addr[5]",  p.party_species_addr + 5, check_species,     "sixth"},
    {"party_species_addr[6]",  p.party_species_addr + 6, check_species,     "terminator (0xFF)"},
    {"party_base_addr[+0]",    p.party_base_addr,        check_species,     "slot0 species byte"},

    -- Enemy party
    {"enemy_count_addr",       p.enemy_count_addr,       check_party_count, "wEnemyPartyCount"},
    {"enemy_species_list_addr",p.enemy_species_list_addr,check_species,     "wEnemyPartySpecies first"},
    {"enemy_base_addr[+0]",    p.enemy_base_addr,        check_species,     "enemy slot0 species"},

    -- Box
    {"box_count_addr",         p.box_count_addr,         check_party_count, "wBoxCount (0..20)"},
    {"box_species_addr[0]",    p.box_species_addr,       check_species,     "wBoxSpecies first"},
    {"box_base_addr[+0]",      p.box_base_addr,          check_species,     "box slot0 species"},

    -- Bag
    {"bag_count_addr",         p.bag_count_addr,         check_byte,        "wNumBagItems (0..20)"},
    {"bag_items_addr[+0]",     p.bag_items_addr,         check_byte,        "first item ID"},

    -- Battle
    {"battle_flag_addr",       p.battle_flag_addr,       check_battle_flag, "current profile choice"},
    {"battle_flag_alt_D05A",   0xD05A,                   check_battle_flag, "DataCrystal alternative — diagnostic only"},

    -- Active enemy battle struct
    {"enemy_mon_species_addr", p.enemy_mon_species_addr, check_species,     "wEnemyMon species"},
    {"enemy_mon_hp_addr (hi)", p.enemy_mon_hp_addr,      check_byte,        "current HP high byte"},
    {"enemy_mon_hp_addr (lo)", p.enemy_mon_hp_addr + 1,  check_byte,        "current HP low byte"},
    {"enemy_mon_level_addr",   p.enemy_mon_level_addr,   check_byte,        "actual level (1..100)"},
    {"enemy_mon_maxhp_addr (hi)", p.enemy_mon_maxhp_addr,    check_byte,    "max HP high byte"},
    {"enemy_mon_maxhp_addr (lo)", p.enemy_mon_maxhp_addr + 1, check_byte,   "max HP low byte"},

    -- Map / player
    {"map_id_addr",            p.map_id_addr,            check_map,         "wCurMap"},
    {"player_id_addr (hi)",    p.player_id_addr,         check_byte,        "OT ID big-endian high"},
    {"player_id_addr (lo)",    p.player_id_addr + 1,     check_byte,        "OT ID low"},
    {"badges_addr",            p.badges_addr,            check_byte,        "wObtainedBadges (bitfield)"},
}

-- ── Helpers ───────────────────────────────────────────────────────────────────
local function dump_full()
    console.log(fmt("%s ───── FULL PROFILE DUMP (variant=%s) ─────", TAG, variant))
    for _, row in ipairs(addrs) do
        local name, addr, check, note = row[1], row[2], row[3], row[4]
        local val = M.read_u8(addr)
        local ok, hint = check(val)
        local mark = ok and "  " or "⚠ "
        console.log(fmt("  %s%-30s @ 0x%04X = 0x%02X (%3d)  %s  [%s]",
            mark, name, addr, val, val, note, hint))
    end
    -- Decoded high-level state
    local count = M.read_u8(p.party_count_addr)
    local map = M.read_u8(p.map_id_addr)
    local in_battle = M.read_u8(p.battle_flag_addr)
    console.log(fmt("%s decoded: party_count=%d  map=0x%02X  battle_flag=%d",
        TAG, count, map, in_battle))
end

local function dump_battle_flag_focus()
    console.log(fmt("%s ───── BATTLE FLAG FOCUS ─────", TAG))
    -- Profile is 0xD057. DC suggests 0xD05A. Both could exist (different semantics).
    -- Dump 8 bytes from D055 to D05C so user can see neighborhood.
    for addr = 0xD050, 0xD060 do
        local v = M.read_u8(addr)
        local mark = "  "
        if addr == p.battle_flag_addr then mark = "P>" end  -- profile's address
        if addr == 0xD05A then mark = "D>" end              -- DataCrystal's address
        console.log(fmt("  %s 0x%04X = 0x%02X (%3d)", mark, addr, v, v))
    end
    console.log("  legend: P> = profile's battle_flag_addr, D> = DataCrystal alternative")
    console.log("  EXPECT: in overworld both should be 0; in wild battle the correct one becomes 1; in trainer battle, 2.")
end

local function dump_party_slot0_raw()
    console.log(fmt("%s ───── PARTY SLOT 0 RAW (44 bytes from 0x%04X) ─────", TAG, p.party_base_addr))
    for row = 0, 43, 8 do
        local parts = {}
        for i = 0, math.min(7, 43 - row) do
            parts[#parts + 1] = fmt("%02X", M.read_u8(p.party_base_addr + row + i))
        end
        console.log(fmt("  +0x%02X  %s", row, table.concat(parts, " ")))
    end
    console.log(fmt("  species @+0x00 = 0x%02X", M.read_u8(p.party_base_addr + 0)))
    console.log(fmt("  hp_hi   @+0x01 = 0x%02X", M.read_u8(p.party_base_addr + 1)))
    console.log(fmt("  hp_lo   @+0x02 = 0x%02X", M.read_u8(p.party_base_addr + 2)))
    console.log(fmt("  status  @+0x04 = 0x%02X", M.read_u8(p.party_base_addr + 4)))
    console.log(fmt("  otid_hi @+0x0C = 0x%02X", M.read_u8(p.party_base_addr + 0x0C)))
    console.log(fmt("  otid_lo @+0x0D = 0x%02X", M.read_u8(p.party_base_addr + 0x0D)))
    console.log(fmt("  moves   @+0x08..0x0B = %02X %02X %02X %02X",
        M.read_u8(p.party_base_addr + 0x08), M.read_u8(p.party_base_addr + 0x09),
        M.read_u8(p.party_base_addr + 0x0A), M.read_u8(p.party_base_addr + 0x0B)))
    console.log(fmt("  pp      @+0x1D..0x20 = %02X %02X %02X %02X",
        M.read_u8(p.party_base_addr + 0x1D), M.read_u8(p.party_base_addr + 0x1E),
        M.read_u8(p.party_base_addr + 0x1F), M.read_u8(p.party_base_addr + 0x20)))
    console.log(fmt("  dv1/dv2 @+0x1B/0x1C = 0x%02X 0x%02X",
        M.read_u8(p.party_base_addr + 0x1B), M.read_u8(p.party_base_addr + 0x1C)))
    console.log(fmt("  level   @+0x21 = %d", M.read_u8(p.party_base_addr + 0x21)))
    console.log(fmt("  maxHPhi @+0x22 = 0x%02X", M.read_u8(p.party_base_addr + 0x22)))
    console.log(fmt("  maxHPlo @+0x23 = 0x%02X", M.read_u8(p.party_base_addr + 0x23)))
end

local function dump_enemy_struct_raw()
    -- wEnemyMon at p.enemy_mon_species_addr (typically 0xCFE5)
    local base = p.enemy_mon_species_addr
    console.log(fmt("%s ───── ENEMY BATTLE STRUCT RAW (60 bytes from 0x%04X) ─────", TAG, base))
    for row = 0, 59, 8 do
        local parts = {}
        for i = 0, math.min(7, 59 - row) do
            parts[#parts + 1] = fmt("%02X", M.read_u8(base + row + i))
        end
        console.log(fmt("  +0x%02X  %s", row, table.concat(parts, " ")))
    end
    -- Phase 4 will read enemy moves at +0x08 and PP at +0x19 — preview them
    console.log(fmt("  enemy moves   @+0x08..0x0B = %02X %02X %02X %02X (Phase 4 target)",
        M.read_u8(base + 0x08), M.read_u8(base + 0x09),
        M.read_u8(base + 0x0A), M.read_u8(base + 0x0B)))
    console.log(fmt("  enemy PP      @+0x19..0x1C = %02X %02X %02X %02X (Phase 4 target)",
        M.read_u8(base + 0x19), M.read_u8(base + 0x1A),
        M.read_u8(base + 0x1B), M.read_u8(base + 0x1C)))
end

-- ── Frame loop ────────────────────────────────────────────────────────────────
local prev_keys = {}
local prev_battle = nil

local function on_frame()
    local k = input.get()
    if k["F1"] and not prev_keys["F1"] then dump_full() end
    if k["F2"] and not prev_keys["F2"] then dump_battle_flag_focus() end
    if k["F3"] and not prev_keys["F3"] then dump_party_slot0_raw() end
    if k["F4"] and not prev_keys["F4"] then dump_enemy_struct_raw() end
    prev_keys = k

    -- Auto-log battle transitions for both candidates
    local profile_flag = M.read_u8(p.battle_flag_addr)
    local dc_flag = M.read_u8(0xD05A)
    local in_battle = profile_flag ~= 0 or dc_flag ~= 0
    if prev_battle ~= nil and in_battle ~= prev_battle then
        console.log(fmt("%s battle transition: profile@0x%04X=%d  DC@0xD05A=%d  (player should report which transitioned with the visible battle)",
            TAG, p.battle_flag_addr, profile_flag, dc_flag))
    end
    prev_battle = in_battle
end

local function safe()
    local ok, err = pcall(on_frame)
    if not ok then console.log(TAG .. " ERROR: " .. tostring(err)) end
end

event.onframeend(safe, "phase0_g1_audit")
console.log(TAG .. " running — press F1 to dump")
