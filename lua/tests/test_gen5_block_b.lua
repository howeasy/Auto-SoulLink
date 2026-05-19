--[[
  lua/tests/test_gen5_block_b.lua — Gen 5 Block B decryption verifier

  Validates moves, PP, PP Ups, form byte, and isEgg flag for the player's
  active party. Use this against a BW/BW2 ROM with a Pokemon that has a
  known move set, form (e.g. Deerling in a specific season), or egg state.

  Press F1 to dump Block B for every occupied party slot. Output goes to
  the BizHawk Lua console.

  Expected output for a known Deerling Summer:
    [T2-G5] slot 0  species=585 form=1 (Deerling Summer)
    [T2-G5]   moves: { 33, 73, 113, 234 }
    [T2-G5]   pp:    { 35, 25, 30, 10 }
    [T2-G5]   pp_ups:{ 0, 0, 0, 0 }
    [T2-G5]   isEgg: false

  Use this to confirm:
    1. Block B byte offsets (PKHeX PK5.cs) are correct in memory_nds.lua
    2. The form byte for Unova alt-forms reads back the expected value
    3. The PID-seeded LCRNG advance schedule for Block B matches Gen 4 logic
--]]

local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
local _lua_root = _src:match("(.+[/\\])tests[/\\]") or _src
local _proj_root = _lua_root:match("(.+[/\\])lua[/\\]") or (_lua_root .. "../")
package.path = _src .. "?.lua;"
           .. _lua_root .. "?.lua;"
           .. _lua_root .. "games/?.lua;"
           .. _proj_root .. "data/games/gen5_bw/?.lua;"
           .. package.path
package.loaded["memory_nds"] = nil
package.loaded["gen5_bw"] = nil

local M = require("memory_nds")
local game = require("gen5_bw")

local fmt = string.format
local function log(msg) console.log("[T2-G5] " .. msg) end

-- Apply game profile
local variant = game.detect_variant()
local profile = game.profiles[variant]
if profile then
    M.applyProfile(profile)
    log("variant=" .. variant)
else
    log("WARNING: no profile for " .. tostring(variant))
end

local function dump_party()
    if not M.init() then
        log("save not loaded")
        return
    end
    local count = M.readPartyCount()
    log(fmt("party_count=%d", count))
    for i = 0, count - 1 do
        local base = M.partyAddr(i)
        if not base then break end
        local pid = memory.read_u32_le(base, "Main RAM")
        if pid ~= 0 then
            local species, _ot, _hi, _ab = M.decrypt_block_a_ext(base)
            local blk_b = M.decrypt_block_b(base)
            if blk_b then
                local display = game.form_display_id(species or 0, blk_b.form)
                log(fmt("slot %d  pid=0x%08X  species=%d form=%d (display=%d)",
                    i, pid, species or 0, blk_b.form, display))
                log(fmt("  moves : { %d, %d, %d, %d }",
                    blk_b.moves[1], blk_b.moves[2], blk_b.moves[3], blk_b.moves[4]))
                log(fmt("  pp    : { %d, %d, %d, %d }",
                    blk_b.pp[1], blk_b.pp[2], blk_b.pp[3], blk_b.pp[4]))
                log(fmt("  pp_ups: { %d, %d, %d, %d }",
                    blk_b.pp_ups[1], blk_b.pp_ups[2], blk_b.pp_ups[3], blk_b.pp_ups[4]))
                log(fmt("  is_egg: %s", tostring(blk_b.is_egg)))
            else
                log(fmt("slot %d: decrypt_block_b returned nil", i))
            end
        end
    end
end

console.clear()
log("test_gen5_block_b loaded — press F1 to dump Block B for party")

local prev = {}
event.onframeend(function()
    local k = input.get()
    if k.F1 and not prev.F1 then
        log("=== F1 — Block B dump ===")
        dump_party()
    end
    prev = k
end, "test_gen5_block_b")
