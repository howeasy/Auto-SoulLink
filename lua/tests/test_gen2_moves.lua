--[[
  lua/tests/test_gen2_moves.lua — Phase 3 moves+PP live verification (Gen 2)

  Reads 4 move IDs at party_base+0x02 and 4 packed PP bytes at +0x17.
  Decodes packed PP: current_pp = byte & 0x3F, pp_ups = (byte >> 6) & 0x03.

  EXPECT: starter has 1-2 moves, valid move IDs are 1..251, PP in 0..63.
  pp_ups should be 0 unless the user has used PP-Up items.

  Controls:
    F1 → slot 0 dump
    F2 → all 6 party slots
    F3 → also dump the raw 4 PP bytes (for PP-Up bit unpacking sanity)
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
M.initProfile(G, "crystal")
local p = G.profiles.crystal

local fmt = string.format
local TAG = "[T3-G2]"

console.clear()
console.log(fmt("%s Phase 3 moves+PP audit (Crystal)", TAG))
console.log(fmt("%s moves_offset=0x%02X  pp_offset=0x%02X  pp_encoding=%s",
    TAG, p.moves_offset, p.pp_offset, p.pp_encoding))

local function dump_slot(slot)
    local base = M.PARTY_BASE_ADDR + slot * M.PARTY_STRUCT_SIZE
    local species = M.read_u8(base)
    if species == 0 or species == 0xFF then
        console.log(fmt("  slot %d: empty", slot))
        return
    end
    local is_egg = (species == 0xFD) and " (EGG)" or ""
    console.log(fmt("  slot %d  species=%03d%s", slot, species, is_egg))
    local mp = M.readMovesAndPP(base, nil)
    if mp then
        for i = 1, 4 do
            local mark = (mp.moves[i] >= 0 and mp.moves[i] <= 251) and "  " or "??"
            console.log(fmt("    %s move[%d] id=%-3d  pp=%-2d  pp_ups=%d",
                mark, i - 1, mp.moves[i], mp.pp[i], mp.pp_ups[i]))
        end
    end
end

local function dump_raw_pp(slot)
    local base = M.PARTY_BASE_ADDR + slot * M.PARTY_STRUCT_SIZE
    console.log(fmt("  slot %d raw PP bytes @0x%04X..0x%04X:",
        slot, base + p.pp_offset, base + p.pp_offset + 3))
    for i = 0, 3 do
        local b = M.read_u8(base + p.pp_offset + i)
        local cur = b % 64
        local ups = math.floor(b / 64)
        console.log(fmt("    +0x%02X = 0x%02X  (current=%d, pp_ups=%d)",
            p.pp_offset + i, b, cur, ups))
    end
end

local prev_keys = {}
event.onframeend(function()
    local k = input.get()
    if k["F1"] and not prev_keys["F1"] then dump_slot(0) end
    if k["F2"] and not prev_keys["F2"] then
        for s = 0, math.min(M.getPartyCount(), 6) - 1 do dump_slot(s) end
    end
    if k["F3"] and not prev_keys["F3"] then dump_raw_pp(0) end
    prev_keys = k
end, "phase3_g2_moves")
