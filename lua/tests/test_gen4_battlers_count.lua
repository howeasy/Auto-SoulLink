--[[
  lua/tests/test_gen4_battlers_count.lua — Locate gBattlersCount in Gen 4 RAM.
  READ-ONLY. Run during an active battle.

  Goal:
    Find the base-relative offset where the battle work struct stores the
    number of active battlers — 2 in singles, 4 in doubles.

  Methodology:
    The script captures a 256 KB window around the player-battle base offset
    when you press F1 (during a 1v1 battle) and again when you press F2
    (during a 2v2). The diff highlights bytes that change from 2→4. The
    first such offset that is stable across multiple captures is the
    BATTLERS_COUNT_OFF candidate.

    Once F1 + F2 both ran, F3 prints a candidate list sorted by likelihood:
      • read 2 at F1 capture
      • read 4 at F2 capture
      • lives within +/-0x2000 of PLAYER_BATTLE_OFF

  Where to test:
    HGSS singles → wild Pidgey on Route 29 (1 mon, 1 mon vs)
    HGSS doubles → Tag Battle "Bird Keepers" on Route 36, or Lance fight pairs
    Platinum singles → wild on Route 201
    Platinum doubles → Cyrus + Mars at Lake Verity, Champion Cynthia doubles segments

  Once an offset is confirmed, set BATTLERS_COUNT_OFF in lua/games/gen4_hgsspt.lua
  in the appropriate profile.
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

local function log(msg) console.log("[BATTLER-SCAN] " .. msg) end
local function r8(a) return memory.read_u8(a, RAM) end

-- Scan window: ±0x2000 around PLAYER_BATTLE_OFF (battle work struct is local to player battle copy).
local PLAYER_BATTLE_OFF = profile.PLAYER_BATTLE_OFF
local SCAN_LO = PLAYER_BATTLE_OFF - 0x2000
local SCAN_HI = PLAYER_BATTLE_OFF + 0x2000

local capture_singles = nil  -- [off] = byte value
local capture_doubles = nil

local function capture(label)
    local base = M.init()
    if not base then log("Save not loaded"); return nil end
    local c = {}
    for off = SCAN_LO, SCAN_HI do
        c[off] = r8(base + off)
    end
    log(string.format("Captured %s @ frame %d: %d bytes scanned (base=0x%06X)",
        label, emu.framecount and emu.framecount() or -1, SCAN_HI - SCAN_LO + 1, base))
    return c
end

local function compare()
    if not capture_singles or not capture_doubles then
        log("Need both F1 (singles capture) and F2 (doubles capture) before F3 comparison.")
        return
    end
    local candidates = {}
    for off = SCAN_LO, SCAN_HI do
        local s = capture_singles[off]
        local d = capture_doubles[off]
        if s == 2 and d == 4 then
            candidates[#candidates + 1] = off
        end
    end
    log(string.format("Found %d candidates with singles=2, doubles=4:", #candidates))
    for i, off in ipairs(candidates) do
        local rel = off - PLAYER_BATTLE_OFF
        log(string.format("  [%d] base+0x%X  (PLAYER_BATTLE_OFF %s 0x%X)",
            i, off, rel >= 0 and "+" or "-", math.abs(rel)))
        if i >= 20 then log("  ... (truncated, " .. (#candidates - 20) .. " more)"); break end
    end
    if #candidates == 1 then
        log("=> Set BATTLERS_COUNT_OFF = 0x" .. string.format("%X", candidates[1])
            .. " in _" .. variant:upper() .. "_PROFILE.")
    elseif #candidates > 1 then
        log("Multiple candidates — repeat the capture in different battles to narrow it down.")
    end
end

log(string.format("Gen 4 battler-count scanner — variant=%s, scan=0x%X..0x%X", variant, SCAN_LO, SCAN_HI))
log("F1 = capture in 1v1 (singles)   F2 = capture in 2v2 (doubles)   F3 = compare")

event.onframestart(function()
    local k = input.get()
    if k["F1"] then capture_singles = capture("singles") end
    if k["F2"] then capture_doubles = capture("doubles") end
    if k["F3"] then compare() end
end)
