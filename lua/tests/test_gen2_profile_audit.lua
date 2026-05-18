--[[
  lua/tests/test_gen2_profile_audit.lua — Phase 0 raw-byte address audit (Gen 2 Crystal)

  PURPOSE
    Read every address in the Gen 2 Crystal profile and print its live value
    with plausibility commentary. Bypasses higher-level helpers so address
    errors reveal themselves.

    The 4 TODO addresses in the profile (enemy_count_addr, enemy_base_addr,
    enemy_species_list_addr, battle_flag_addr) are exercised specifically by
    F5 — run that during a wild battle and a trainer battle to see which
    candidate transitions correctly.

    Run order in BizHawk:
      (1) boot screen (before save loaded)
      (2) overworld idle (e.g. New Bark Town)
      (3) wild battle (e.g. Route 29 grass — Pidgey/Sentret)
      (4) trainer battle (e.g. Falkner)
      (5) daycare area (Route 34) — for Phase 1d egg detection prep

  Controls:
    F1 → full profile dump (every address + value + plausibility note)
    F2 → focused enemy/battle region dump (0xD200..0xD2A0)
    F3 → party slot 0 raw 48 bytes (cross-check party_struct offsets)
    F4 → enemy battle struct raw 60 bytes
    F5 → focused TODO-address dump for the 4 unverified Crystal addresses
--]]

local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
local _lua_root = _src:match("(.+[/\\])tests[/\\]") or _src
local _proj_root = _lua_root:match("(.+[/\\])lua[/\\]") or (_lua_root .. "../")
package.path = _src .. "?.lua;"
           .. _lua_root .. "?.lua;"
           .. _lua_root .. "games/?.lua;"
           .. _proj_root .. "data/games/gen2_crystal/?.lua;"
           .. package.path

package.loaded["memory_gb"] = nil
package.loaded["games.gen2_crystal"] = nil

local M = require("memory_gb")
local G = require("games.gen2_crystal")

local variant = G.detect_variant() or "crystal"
local p = G.profiles[variant]
if not p then
    error("[T0-G2] No profile for variant: " .. tostring(variant))
end
M.initProfile(G, variant)

local fmt = string.format
local TAG = "[T0-G2]"

console.clear()
console.log(fmt("%s Phase 0 profile audit — variant=%s", TAG, variant))
console.log(fmt("%s Press F1=full dump  F2=battle region  F3=party slot 0  F4=enemy struct  F5=TODO focus", TAG))
console.log(fmt("%s Run F1 at: boot, overworld idle, wild battle, trainer battle, daycare (Route 34)", TAG))

local function check_party_count(v) return v >= 0 and v <= 6, "expect 0..6" end
local function check_species(v) return v == 0xFF or (v >= 0 and v <= 251) or v == 0xFD, "expect 0..251, 0xFF terminator, or 0xFD (EGG)" end
local function check_battle_flag(v) return v >= 0 and v <= 2, "expect 0=overworld, 1=wild, 2=trainer" end
local function check_map(v) return v >= 0 and v <= 26, "expect map group 0..26 / map number 0..255" end
local function check_byte(v) return v >= 0 and v <= 0xFF, "any byte" end
local function check_level(v) return v >= 1 and v <= 100, "expect 1..100" end

local addrs = {
    -- Party
    {"party_count_addr",        p.party_count_addr,        check_party_count, "wPartyCount"},
    {"party_species_addr[0]",   p.party_species_addr,      check_species,     "wPartySpecies first"},
    {"party_species_addr[1]",   p.party_species_addr + 1,  check_species,     "second"},
    {"party_species_addr[5]",   p.party_species_addr + 5,  check_species,     "sixth"},
    {"party_species_addr[6]",   p.party_species_addr + 6,  check_species,     "terminator (0xFF)"},
    {"party_base_addr[+0]",     p.party_base_addr,         check_species,     "slot0 species"},
    {"party_base_addr[+0x01]",  p.party_base_addr + 0x01,  check_byte,        "slot0 held item"},

    -- Enemy party (TODO addresses)
    {"enemy_count_addr ★TODO",  p.enemy_count_addr,        check_party_count, "wOTPartyCount candidate"},
    {"enemy_species_list ★TODO",p.enemy_species_list_addr, check_species,     "wOTPartySpecies first"},
    {"enemy_base_addr ★TODO",   p.enemy_base_addr,         check_species,     "wOTPartyMon1 species"},

    -- Box (SRAM)
    {"box_count_addr (SRAM)",   p.box_count_addr,          check_byte,        "wBoxCount in CartRAM — uses sram_read"},

    -- Bag
    {"bag_count_addr",          p.bag_count_addr,          check_byte,        "wNumBalls (0..12)"},
    {"bag_items_addr[+0]",      p.bag_items_addr,          check_byte,        "first ball ID"},
    {"bag_items_addr[+1]",      p.bag_items_addr + 1,      check_byte,        "first ball quantity"},

    -- Battle (TODO)
    {"battle_flag_addr ★TODO",  p.battle_flag_addr,        check_battle_flag, "current profile choice — 0xD22D"},

    -- Active enemy battle struct
    {"enemy_mon_species_addr",  p.enemy_mon_species_addr,  check_species,     "wEnemyMon species"},
    {"enemy_mon_level_addr",    p.enemy_mon_level_addr,    check_level,       "level (1..100)"},
    {"enemy_mon_hp_hi",         p.enemy_mon_hp_addr,       check_byte,        "current HP high byte"},
    {"enemy_mon_hp_lo",         p.enemy_mon_hp_addr + 1,   check_byte,        "current HP low byte"},
    {"enemy_mon_maxhp_hi",      p.enemy_mon_maxhp_addr,    check_byte,        "max HP high byte"},
    {"enemy_mon_maxhp_lo",      p.enemy_mon_maxhp_addr + 1,check_byte,        "max HP low byte"},

    -- Map (Gen 2 has 2-byte map group + number)
    {"map_group_addr",          p.map_group_addr,          check_map,         "wMapGroup"},
    {"map_number_addr",         p.map_number_addr,         check_byte,        "wMapNumber"},

    -- Player
    {"player_id_addr (hi)",     p.player_id_addr,          check_byte,        "OT ID big-endian high"},
    {"player_id_addr (lo)",     p.player_id_addr + 1,      check_byte,        "OT ID low"},
    {"player_name_addr[0]",     p.player_name_addr,        check_byte,        "first char of name"},

    -- Badges
    {"badges_addr (Johto)",     p.badges_addr,             check_byte,        "wJohtoBadges bitfield"},
    {"kanto_badges_addr",       p.kanto_badges_addr,       check_byte,        "wKantoBadges bitfield"},
}

local function dump_full()
    console.log(fmt("%s ───── FULL PROFILE DUMP ─────", TAG))
    for _, row in ipairs(addrs) do
        local name, addr, check, note = row[1], row[2], row[3], row[4]
        local val = M.read_u8(addr)
        local ok, hint = check(val)
        local mark = ok and "  " or "⚠ "
        console.log(fmt("  %s%-30s @ 0x%04X = 0x%02X (%3d)  %s  [%s]",
            mark, name, addr, val, val, note, hint))
    end
    local count = M.read_u8(p.party_count_addr)
    local mg = M.read_u8(p.map_group_addr)
    local mn = M.read_u8(p.map_number_addr)
    local bf = M.read_u8(p.battle_flag_addr)
    console.log(fmt("%s decoded: party_count=%d  map=%d:%d  battle_flag=%d",
        TAG, count, mg, mn, bf))
end

local function dump_battle_region()
    console.log(fmt("%s ───── BATTLE REGION DUMP (0xD200..0xD2A0) ─────", TAG))
    for base = 0xD200, 0xD2A0, 16 do
        local parts = {}
        for i = 0, 15 do
            parts[#parts + 1] = fmt("%02X", M.read_u8(base + i))
        end
        console.log(fmt("  0x%04X  %s", base, table.concat(parts, " ")))
    end
end

local function dump_party_slot0_raw()
    console.log(fmt("%s ───── PARTY SLOT 0 RAW (48 bytes from 0x%04X) ─────", TAG, p.party_base_addr))
    for row = 0, 47, 8 do
        local parts = {}
        for i = 0, math.min(7, 47 - row) do
            parts[#parts + 1] = fmt("%02X", M.read_u8(p.party_base_addr + row + i))
        end
        console.log(fmt("  +0x%02X  %s", row, table.concat(parts, " ")))
    end
    console.log(fmt("  species @+0x00 = 0x%02X  %s",
        M.read_u8(p.party_base_addr + 0x00),
        M.read_u8(p.party_base_addr + 0x00) == 0xFD and "(EGG marker)" or ""))
    console.log(fmt("  held_item @+0x01 = 0x%02X", M.read_u8(p.party_base_addr + 0x01)))
    console.log(fmt("  moves   @+0x02..0x05 = %02X %02X %02X %02X",
        M.read_u8(p.party_base_addr + 0x02), M.read_u8(p.party_base_addr + 0x03),
        M.read_u8(p.party_base_addr + 0x04), M.read_u8(p.party_base_addr + 0x05)))
    console.log(fmt("  otid    @+0x06..0x07 = %02X %02X",
        M.read_u8(p.party_base_addr + 0x06), M.read_u8(p.party_base_addr + 0x07)))
    console.log(fmt("  DVs     @+0x15..0x16 = %02X %02X",
        M.read_u8(p.party_base_addr + 0x15), M.read_u8(p.party_base_addr + 0x16)))
    console.log(fmt("  pp      @+0x17..0x1A = %02X %02X %02X %02X (top 2 bits = PP-Up count)",
        M.read_u8(p.party_base_addr + 0x17), M.read_u8(p.party_base_addr + 0x18),
        M.read_u8(p.party_base_addr + 0x19), M.read_u8(p.party_base_addr + 0x1A)))
    console.log(fmt("  level   @+0x1F = %d", M.read_u8(p.party_base_addr + 0x1F)))
    console.log(fmt("  status  @+0x20 = 0x%02X", M.read_u8(p.party_base_addr + 0x20)))
    console.log(fmt("  hp      @+0x22..0x23 = %02X %02X", M.read_u8(p.party_base_addr + 0x22), M.read_u8(p.party_base_addr + 0x23)))
    console.log(fmt("  maxhp   @+0x24..0x25 = %02X %02X", M.read_u8(p.party_base_addr + 0x24), M.read_u8(p.party_base_addr + 0x25)))
end

local function dump_enemy_struct_raw()
    local base = p.enemy_mon_species_addr
    console.log(fmt("%s ───── ENEMY BATTLE STRUCT RAW (60 bytes from 0x%04X) ─────", TAG, base))
    for row = 0, 59, 8 do
        local parts = {}
        for i = 0, math.min(7, 59 - row) do
            parts[#parts + 1] = fmt("%02X", M.read_u8(base + row + i))
        end
        console.log(fmt("  +0x%02X  %s", row, table.concat(parts, " ")))
    end
    console.log(fmt("  enemy moves @+0x02..0x05 = %02X %02X %02X %02X (Phase 4 target)",
        M.read_u8(base + 0x02), M.read_u8(base + 0x03),
        M.read_u8(base + 0x04), M.read_u8(base + 0x05)))
    console.log(fmt("  enemy PP    @+0x08..0x0B = %02X %02X %02X %02X (DC offset; verify against pret)",
        M.read_u8(base + 0x08), M.read_u8(base + 0x09),
        M.read_u8(base + 0x0A), M.read_u8(base + 0x0B)))
end

local function dump_todo_focus()
    console.log(fmt("%s ───── TODO-ADDRESS FOCUS ─────", TAG))
    -- enemy_count_addr (0xD280): in overworld should be 0; in trainer battle, opponent's party count (1..6); in wild battle, typically 1
    local ec_profile = p.enemy_count_addr  -- 0xD280
    console.log(fmt("  enemy_count_addr @0x%04X = %d  (expect 0 in overworld, 1..6 in battle)",
        ec_profile, M.read_u8(ec_profile)))

    -- Surrounding bytes — sometimes the right address is ±1 or ±2 from the profile
    for offset = -4, 4 do
        local addr = ec_profile + offset
        local v = M.read_u8(addr)
        local mark = (offset == 0) and "P>" or "  "
        console.log(fmt("    %s 0x%04X = 0x%02X (%d)", mark, addr, v, v))
    end

    -- battle_flag_addr (0xD22D): 0=overworld, 1=wild, 2=trainer
    local bf_profile = p.battle_flag_addr  -- 0xD22D
    console.log(fmt("  battle_flag_addr @0x%04X = %d  (expect 0/1/2)",
        bf_profile, M.read_u8(bf_profile)))
    for offset = -4, 4 do
        local addr = bf_profile + offset
        local v = M.read_u8(addr)
        local mark = (offset == 0) and "P>" or "  "
        console.log(fmt("    %s 0x%04X = 0x%02X (%d)", mark, addr, v, v))
    end

    console.log("  Action: in OVERWORLD, all should show plausible values for that state.")
    console.log("          In WILD BATTLE, enemy_count should be 1, battle_flag should be 1.")
    console.log("          In TRAINER BATTLE, enemy_count should be 1..6, battle_flag should be 2.")
end

local prev_keys = {}
local prev_battle = nil
local prev_enemy_count = nil

local function on_frame()
    local k = input.get()
    if k["F1"] and not prev_keys["F1"] then dump_full() end
    if k["F2"] and not prev_keys["F2"] then dump_battle_region() end
    if k["F3"] and not prev_keys["F3"] then dump_party_slot0_raw() end
    if k["F4"] and not prev_keys["F4"] then dump_enemy_struct_raw() end
    if k["F5"] and not prev_keys["F5"] then dump_todo_focus() end
    prev_keys = k

    local bf = M.read_u8(p.battle_flag_addr)
    local ec = M.read_u8(p.enemy_count_addr)
    if prev_battle and bf ~= prev_battle then
        console.log(fmt("%s battle_flag transition: %d → %d  (enemy_count=%d)",
            TAG, prev_battle, bf, ec))
    end
    prev_battle = bf
    if prev_enemy_count and ec ~= prev_enemy_count then
        console.log(fmt("%s enemy_count transition: %d → %d", TAG, prev_enemy_count, ec))
    end
    prev_enemy_count = ec
end

local function safe()
    local ok, err = pcall(on_frame)
    if not ok then console.log(TAG .. " ERROR: " .. tostring(err)) end
end

event.onframeend(safe, "phase0_g2_audit")
console.log(TAG .. " running — press F1 to dump")
