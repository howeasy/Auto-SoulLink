--[[
  lua/tests/probe_gen1_rivalswap.lua — WHEN is it safe to overwrite the enemy party?

  The Gen 1 Rival Team Swap writes the partner's team over wEnemyMons. The implementation
  in memory_gb.lua (writeEnemyParty) was derived from pret source rather than measured:

    ReadTrainer (engine/battle/read_trainer_party.asm) zeroes wEnemyPartyCount, then fills
    the party from TrainerDataPointers using wCurOpponent + wTrainerNo.
    LoadEnemyMonData (engine/battle/core.asm:5992) builds the ACTIVE battler on send-out,
    copying HP (+0x01), status (+0x04) and moves (+0x08) out of the party struct and the
    level out of wEnemyMon1Level (+0x21) via wCurEnemyLevel. Stats and DVs are NOT copied —
    a trainer mon gets fixed DVs and recomputed stats.

  So the write window opens once wEnemyPartyCount is nonzero and closes when the first mon
  is sent out. This probe MEASURES that window instead of trusting the reading:

    * how many frames elapse between "in trainer battle" and "party count nonzero"
    * how many more before the active battler (wEnemyMon) is populated
    * whether wCurOpponent is stable across those frames (the trainer_battle_start gate
      waits TRAINER_STABLE_GATE frames for exactly this reason)

  Read-only. Load in the BizHawk Lua console with a trainer battle about to start, or from
  a savestate, then walk into the fight.

  Findings belong in data/games/gen1_rby/README.md; delete this probe once they are recorded.
--]]

local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
local _lua_root = _src:match("(.+[/\\])tests[/\\]") or _src
package.path = _lua_root .. "?.lua;" .. _lua_root .. "games/?.lua;" .. package.path

package.loaded["memory_gb"] = nil
package.loaded["games.gen1_rby"] = nil
local M = require("memory_gb")
local G = require("games.gen1_rby")

local variant = G.detect_variant()
if not variant then error("not a Gen 1 ROM") end
M.initProfile(G, variant)

local fmt = string.format
console.clear()
console.log(fmt("[probe-rivalswap] variant=%s — walk into a TRAINER battle", variant))

local prev_battle, frames, t0 = 0, 0, nil
local saw_count_at, saw_active_at = nil, nil
local opp_seen = {}

while true do
    local battle = M.read_u8(M.BATTLE_FLAG_ADDR)
    local count  = M.read_u8(M.ENEMY_COUNT_ADDR)
    local active = M.read_u8(M.ENEMY_MON_SPECIES_ADDR)
    local opp    = M.CUR_OPPONENT_ADDR and M.read_u8(M.CUR_OPPONENT_ADDR) or 0

    if battle == 2 and prev_battle ~= 2 then
        t0, frames, saw_count_at, saw_active_at, opp_seen = 0, 0, nil, nil, {}
        console.log("[probe-rivalswap] TRAINER battle started")
    end

    if t0 then
        frames = frames + 1
        opp_seen[opp] = (opp_seen[opp] or 0) + 1
        if not saw_count_at and count > 0 then
            saw_count_at = frames
            console.log(fmt("  party count %d appeared at frame +%d (opponent=%d)",
                            count, frames, opp))
        end
        if not saw_active_at and active ~= 0 then
            saw_active_at = frames
            console.log(fmt("  ACTIVE battler populated at frame +%d (species=%d)", frames, active))
            local window = saw_count_at and (frames - saw_count_at) or -1
            console.log(fmt("  >>> SAFE WRITE WINDOW = %d frames", window))
            local n = 0
            for id, c in pairs(opp_seen) do
                n = n + 1
                console.log(fmt("      wCurOpponent saw id=%d for %d frames", id, c))
            end
            console.log(fmt("      distinct wCurOpponent values during init: %d", n))
            t0 = nil
        end
    end

    prev_battle = battle
    emu.frameadvance()
end
