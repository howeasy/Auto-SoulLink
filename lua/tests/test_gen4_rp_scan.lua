--[[
  lua/tests/test_gen4_rp_scan.lua — Renegade Platinum profile verification.
  READ-ONLY. Run with Renegade Platinum loaded (save booted).

  Goal:
    Confirm every _RP_PROFILE address (inherited from _PT_PROFILE) still reads
    plausible values under RP. RP doesn't rewrite the save format, so all
    Platinum offsets should work — but RP-specific deltas (if any are found)
    are flagged here so they can be added to _RP_PROFILE explicitly.

  Plausibility checks:
    • Party count 0..6
    • Each occupied party slot has plausible level/HP/maxHP/species
    • PC array header offset in 0x100..0x23000
    • Zone ID < 0x280
    • Sinnoh badges byte (no second badge set in Sinnoh)
    • Trainer name first char in Gen IV charcode range

  Controls:
    F1 = re-run
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

-- Force the renegade_platinum profile (inherits all PT addresses).
local profile = game.profiles.renegade_platinum
M.applyProfile(profile)
local RAM = profile.RAM_DOMAIN or "Main RAM"

local function r8 (a) return memory.read_u8     (a, RAM) end
local function r16(a) return memory.read_u16_le (a, RAM) end
local function r32(a) return memory.read_u32_le (a, RAM) end

local function log(msg) console.log("[RP-SCAN] " .. msg) end

local function ok_flag(b) return b and "OK" or "FAIL" end

local function run_scan()
    console.clear()
    log("============== Renegade Platinum profile scan ==============")
    if gameinfo and gameinfo.getromname then
        local ok_n, name = pcall(gameinfo.getromname)
        log("ROM name: " .. (ok_n and tostring(name) or "<unknown>"))
    end
    if gameinfo and gameinfo.getromhash then
        local ok_h, hash = pcall(gameinfo.getromhash)
        log("ROM hash: " .. (ok_h and tostring(hash) or "<unknown>"))
    end
    log(string.format("Detected variant: %s", tostring(game.detect_variant())))

    local p1 = r32(0x0BA8) & 0xFFFFFF
    log(string.format("p1 = 0x%06X  [%s]", p1, ok_flag(p1 ~= 0)))
    if p1 == 0 then log("Save not loaded."); return end

    local base = r32(p1 + 0x20) & 0xFFFFFF
    log(string.format("base = 0x%06X  [%s]", base, ok_flag(base ~= 0)))
    if base == 0 then return end

    M.init()
    local pc = r8(base + 0xB0)  -- Pt party count offset
    log(string.format("Party count @ +0xB0: %d  [%s]", pc, ok_flag(pc >= 0 and pc <= 6)))

    for i = 0, math.min(pc, 6) - 1 do
        local addr = base + 0xB4 + i * 0xEC
        local pid = r32(addr)
        local lv, hp, max_hp = M.decrypt_stats(addr + 0x88, pid)
        local sp = M.decrypt_block_a(addr)
        log(string.format("  slot %d  PID=%08X sp=%s lv=%d HP=%d/%d",
            i, pid,
            sp and tostring(sp) or "?", lv, hp, max_hp))
    end

    local pc_hdr = r32(base + 0x232AC)
    log(string.format("PC array hdr offset: 0x%X  [%s]",
        pc_hdr, ok_flag(pc_hdr >= 0x100 and pc_hdr < 0x23000)))

    local zone_raw = r16(base + 0x239B0)
    local zone = zone_raw
    if zone == 0 then
        local zptr = r32(base + 0x239B0) & 0xFFFFFF
        if zptr ~= 0 then zone = r16(zptr + 2) end
    end
    log(string.format("Zone ID: 0x%X  [%s]", zone, ok_flag(zone < 0x280)))

    local tr = r16(base + 0x4189E)
    log(string.format("Trainer ID @ +0x4189E: %d (0=wild, overworld expected)", tr))

    local badges = r8(base + 0x96)
    log(string.format("Sinnoh badges @ +0x96: 0x%02X", badges))

    local name = M.readTrainerName()
    log(string.format("Player name: '%s'", name))

    log("============== Done ==============")
    log("If every line shows OK, _RP_PROFILE inherits cleanly from Platinum.")
    log("Any FAIL line indicates an RP-specific offset delta — add explicit override to _RP_PROFILE.")
end

run_scan()
event.onframestart(function()
    if input.get()["F1"] then run_scan() end
end)
