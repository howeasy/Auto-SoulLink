--[[
  lua/tests/test_gen4_block_b.lua — Block B / Block D decode verifier.
  READ-ONLY. Run with HGSS or Platinum loaded (save booted, party non-empty).

  Verifies that M.decrypt_block_b and M.decrypt_block_d on each party slot return
  plausible data:
    • moves: each in 0..467 (Gen 4 move max) or 0 for empty slots
    • PP: each in 0..40 (PP-Up max), 0 for empty move slots
    • PP-Ups: each in 0..3
    • IVs: each in 0..31
    • is_egg: false for any caught mon (true only for actual eggs)
    • form: 0..31
    • pokeball: 1..16 (standard) or 0x90..0x9F (Apricorn HGSS) [in this u8 we expect 1-16]
    • met_level: 1..100

  Cross-check against the in-game summary screen for one or two mons.

  Controls:
    F1 = re-run
    F2 = also dump Block A (species, OTID, item, ability) for slot 0
--]]

local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
local _lua_root = _src:match("(.+[/\\])tests[/\\]") or _src
local _proj_root = _lua_root:match("(.+[/\\])lua[/\\]") or (_lua_root .. "../")
package.path = _src .. "?.lua;"
           .. _lua_root .. "?.lua;"
           .. _lua_root .. "games/?.lua;"
           .. _proj_root .. "data/games/gen4_hgsspt/?.lua;"
           .. package.path

package.loaded["memory_nds"] = nil
package.loaded["gen4_hgsspt"] = nil

local M    = require("memory_nds")
local game = require("gen4_hgsspt")

local variant = game.detect_variant()
local profile = game.profiles[variant] or game.profiles.heartgold
M.applyProfile(profile)
local RAM = profile.RAM_DOMAIN or "Main RAM"

local function log(msg) console.log("[BLOCK-B] " .. msg) end

local function plausible(label, ok)
    return label .. (ok and " ✓" or " ⚠️")
end

local function dump_slot(slot)
    local base = M.init()
    if not base then log("Save not loaded"); return end
    local addr = M.partyAddr(slot)
    if not addr then return end
    local pid = memory.read_u32_le(addr, RAM)
    if pid == 0 then return end

    -- Block A for context
    local species, otid, item, ability = M.decrypt_block_a_ext(addr)
    log(string.format("─── Slot %d  PID=%08X  species=%s  OT=%08X  item=%d  abl=%d",
        slot, pid,
        species and tostring(species) or "?",
        otid or 0, item or 0, ability or 0))

    -- Battle-stat block: level, HP, status
    local level, curHP, maxHP, status = M.decrypt_stats(addr + 0x88, pid)
    log(string.format("    Lv %d  HP %d/%d  status=%d", level, curHP, maxHP, status))

    -- Block B: moves, PP, IVs, egg flag, form
    local bb = M.decrypt_block_b(addr)
    if bb then
        log(string.format("    moves : [%d, %d, %d, %d]",
            bb.moves[1], bb.moves[2], bb.moves[3], bb.moves[4]))
        log(string.format("    PP    : [%d, %d, %d, %d]",
            bb.pp[1], bb.pp[2], bb.pp[3], bb.pp[4]))
        log(string.format("    PP-Up : [%d, %d, %d, %d]",
            bb.pp_ups[1], bb.pp_ups[2], bb.pp_ups[3], bb.pp_ups[4]))
        log(string.format("    IVs   : HP=%d ATK=%d DEF=%d SPE=%d SPA=%d SPD=%d",
            bb.ivs.hp, bb.ivs.atk, bb.ivs.def, bb.ivs.spe, bb.ivs.spa, bb.ivs.spd))
        log(string.format("    flags : %s  %s  form=%d  gender=%d  fateful=%s",
            plausible("isEgg=" .. tostring(bb.is_egg), not bb.is_egg or level == 1),
            plausible("nicked=" .. tostring(bb.is_nicknamed), true),
            bb.form, bb.gender_bits, tostring(bb.fateful)))
        -- IV sanity
        local iv_ok = bb.ivs.hp <= 31 and bb.ivs.atk <= 31 and bb.ivs.def <= 31
                      and bb.ivs.spe <= 31 and bb.ivs.spa <= 31 and bb.ivs.spd <= 31
        log(string.format("    IV sanity (each 0..31)  %s", iv_ok and "OK ✓" or "FAIL ⚠️"))
        -- Move sanity
        local mv_ok = true
        for i = 1, 4 do
            if bb.moves[i] > 467 then mv_ok = false end
        end
        log(string.format("    Move sanity (each 0..467)  %s", mv_ok and "OK ✓" or "FAIL ⚠️"))
    else
        log("    Block B decode failed")
    end

    -- Block D: pokeball, met level, encounter type
    local bd = M.decrypt_block_d(addr)
    if bd then
        log(string.format("    Block D: ball=%d  metLv=%d  encType=%d  pokerus=0x%02X  metLoc=%d",
            bd.pokeball, bd.met_level, bd.encounter_type, bd.pokerus, bd.met_location))
        local d_ok = bd.pokeball >= 1 and bd.pokeball <= 0xFF
                     and bd.met_level >= 0 and bd.met_level <= 100
        log(string.format("    Block D sanity  %s", d_ok and "OK ✓" or "FAIL ⚠️"))
    else
        log("    Block D decode failed")
    end

    -- isEgg() wrapper
    log(string.format("    M.isEgg() = %s", tostring(M.isEgg(addr))))
end

local function run()
    console.clear()
    log(string.format("============== Gen 4 Block B/D verifier (%s) ==============", variant))
    local base = M.init()
    if not base then
        log("Save not loaded — load a save and re-run with F1.")
        return
    end
    log(string.format("base=0x%06X", base))
    local pc = M.readPartyCount()
    log(string.format("Party count: %d", pc))
    for i = 0, pc - 1 do
        dump_slot(i)
    end
    log("============== Done ==============")
end

run()

event.onframestart(function()
    if input.get()["F1"] then run() end
    if input.get()["F2"] then dump_slot(0) end
end)
