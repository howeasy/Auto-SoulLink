--[[
  lua/tests/test_gen1_moves.lua — Phase 3 moves+PP live verification (Gen 1)

  Reads the 4 move IDs at party_base+0x08 and 4 PP bytes at party_base+0x1D
  for the slot 0 mon, prints them, and reports if the values are plausible.

  EXPECT: a fresh starter has 1-2 moves, the rest are 0. PP values typically
  in 5..40 range. F1 dumps the bytes.

  Controls:
    F1 → dump slot 0 moves + PP
    F2 → dump all 6 slots (for multi-mon party verification)
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
M.initProfile(G, G.detect_variant() or "red")
local p = G.profiles[G.detect_variant() or "red"]

local fmt = string.format
local TAG = "[T3-G1]"

console.clear()
console.log(fmt("%s Phase 3 moves+PP audit", TAG))
console.log(fmt("%s moves_offset=0x%02X  pp_offset=0x%02X  pp_encoding=%s",
    TAG, p.moves_offset, p.pp_offset, p.pp_encoding))
console.log(fmt("%s F1=slot 0 dump  F2=all party slots", TAG))

local function dump_slot(slot)
    local base = M.PARTY_BASE_ADDR + slot * M.PARTY_STRUCT_SIZE
    local species = M.read_u8(base)
    if species == 0 or species == 0xFF then
        console.log(fmt("  slot %d: empty", slot))
        return
    end
    console.log(fmt("  slot %d  species_idx=0x%02X", slot, species))
    local mp = M.readMovesAndPP(base, nil)
    if mp then
        for i = 1, 4 do
            local move_id = mp.moves[i]
            local pp = mp.pp[i]
            local mark = (move_id >= 0 and move_id <= 165) and "  " or "??"
            console.log(fmt("    %s move[%d] id=%-3d  pp=%-3d", mark, i - 1, move_id, pp))
        end
    end
end

local function dump_all_slots()
    console.log(fmt("%s ── all party slots ──", TAG))
    local count = M.getPartyCount()
    for slot = 0, math.min(count, 6) - 1 do
        dump_slot(slot)
    end
end

local prev_keys = {}
event.onframeend(function()
    local k = input.get()
    if k["F1"] and not prev_keys["F1"] then dump_slot(0) end
    if k["F2"] and not prev_keys["F2"] then dump_all_slots() end
    prev_keys = k
end, "phase3_g1_moves")
