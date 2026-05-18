--[[
  lua/tests/test_gen4_doubles.lua — Verify Gen 4 doubles + stat-stage + enemy-party reads.
  READ-ONLY. Run after BATTLERS_COUNT_OFF + BATTLE_INFO_* are populated in
  lua/games/gen4_hgsspt.lua (via test_gen4_battlers_count.lua + test_gen4_stat_stages.lua).

  Checks each frame:
    • M.isInBattle() result
    • M.isDoubleBattle() result
    • Stat stages for battler 0 (player L), 1 (enemy L), 2 (player R), 3 (enemy R)
    • Active party slot for each battler (via M.getBattlerPartyIndex)
    • Full enemy party via M.readEnemyParty (species, level, HP, moves, PP, form)

  Controls:
    F1 = re-dump state
    F2 = print enemy party only
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

local function log(msg) console.log("[DOUBLES] " .. msg) end

local function dump_stages(label, battler_idx)
    local s = M.readStatStages(battler_idx)
    if not s then
        log(string.format("  %s [b=%d]  stat stages: <unavailable — BATTLE_INFO_* not set>", label, battler_idx))
        return
    end
    log(string.format("  %s [b=%d]  ATK=%d DEF=%d SPE=%d SPA=%d SPD=%d ACC=%d EVA=%d",
        label, battler_idx, s[1], s[2], s[3], s[4], s[5], s[6], s[7]))
end

local function dump_enemy_party()
    local ep = M.readEnemyParty()
    log(string.format("Enemy party: %d mon(s)", #ep))
    for i, mon in ipairs(ep) do
        log(string.format("  slot %d  sp=%d  lv=%d  HP=%d/%d  abl=%d  item=%d  form=%d  egg=%s",
            i - 1, mon.species_id, mon.level, mon.hp, mon.maxHP,
            mon.ability_id, mon.held_item_id, mon.form, tostring(mon.is_egg)))
        log(string.format("    moves=[%d,%d,%d,%d]  PP=[%d,%d,%d,%d]",
            mon.moves[1], mon.moves[2], mon.moves[3], mon.moves[4],
            mon.pp[1], mon.pp[2], mon.pp[3], mon.pp[4]))
    end
end

local function run()
    console.clear()
    log(string.format("============== Gen 4 doubles verifier (%s) ==============", variant))
    local base = M.init()
    if not base then log("Save not loaded"); return end
    log(string.format("In battle:        %s", tostring(M.isInBattle())))
    log(string.format("Wild battle:      %s", tostring(M.isWildBattle())))
    log(string.format("Double battle:    %s", tostring(M.isDoubleBattle())))
    log(string.format("Enemy trainer ID: %d", M.readEnemyTrainerId()))
    log("─── Stat stages ───")
    dump_stages("player_L", 0)
    dump_stages("enemy_L ", 1)
    dump_stages("player_R", 2)
    dump_stages("enemy_R ", 3)
    log("─── Active party indices ───")
    for b = 0, 3 do
        local idx = M.getBattlerPartyIndex(b)
        log(string.format("  battler %d  active party slot = %s", b, tostring(idx)))
    end
    log("─── Enemy party ───")
    dump_enemy_party()
    log("============== Done ==============")
end

run()

event.onframestart(function()
    local k = input.get()
    if k["F1"] then run() end
    if k["F2"] then dump_enemy_party() end
end)
