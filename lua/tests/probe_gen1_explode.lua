--[[
  lua/tests/probe_gen1_explode.lua — WHEN does a written move selection actually take?

  Explode Mode coerces the active battler into Explosion (move 153) by writing:
    wBattleMonMoves[0]      (move slot 0)      + wBattleMonPP[0]
    wPlayerMoveListIndex    (selected slot)
    wPlayerSelectedMove     (the move the engine acts on)

  pret shows the engine writing wPlayerSelectedMove from the move menu
  (engine/battle/core.asm:321/366) and reading it back at :370/:381 and :3018. What the
  source does NOT settle is which FRAME our write survives to — write too early and the
  menu overwrites us, too late and the turn has already resolved.

  This probe answers that empirically. Press F1 during a battle to arm the write, then let
  the turn play out; it logs whether wPlayerSelectedMove still held EXPLOSION when the turn
  executed, and whether the battler's HP hit 0 (Explosion's self-KO), which is the actual
  success condition Explode Mode depends on.

  Read-only except the deliberate F1 write. Findings belong in the Gen 1 README; delete
  this probe once they are recorded.
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
console.log(fmt("[probe-explode] variant=%s — enter a battle, press F1 to arm Explosion", variant))

local armed_at, frames = nil, 0
local prev_keys = {}

local function pressed(k)
    local keys = input.get()
    local was = prev_keys[k]
    prev_keys[k] = keys[k]
    return keys[k] and not was
end

while true do
    frames = frames + 1
    local in_batt = M.isInBattle()

    if pressed("F1") then
        if not in_batt then
            console.log("[probe-explode] not in battle — nothing to arm")
        else
            local slot = M.getActivePartySlot and M.getActivePartySlot() or 0
            local before_move = M.read_u8(M.BATTLE_MON_MOVES_ADDR)
            local ok, err = M.forceExplode(slot)
            armed_at = frames
            console.log(fmt("[probe-explode] armed=%s (%s) activeSlot=%d moveSlot0 %d -> %d",
                            tostring(ok), tostring(err), slot, before_move,
                            M.read_u8(M.BATTLE_MON_MOVES_ADDR)))
        end
    end

    if armed_at then
        local since = frames - armed_at
        local sel = M.read_u8(M.PLAYER_SELECTED_MOVE_ADDR)
        -- Did anything overwrite our selection before the turn ran?
        if since <= 120 and sel ~= M.MOVE_EXPLOSION then
            console.log(fmt("  !! wPlayerSelectedMove overwritten at +%d frames (now %d)", since, sel))
            armed_at = nil
        elseif since > 0 and since % 30 == 0 then
            local hp = M.read_u16_be(M.PARTY_BASE_ADDR
                        + (M.getActivePartySlot and M.getActivePartySlot() or 0) * M.PARTY_STRUCT_SIZE
                        + M.HP_OFFSET)
            console.log(fmt("  +%3d frames: selected=%d activeHP=%d inBattle=%s",
                            since, sel, hp, tostring(in_batt)))
            if hp == 0 then
                console.log(fmt("  >>> SELF-KO CONFIRMED at +%d frames — Explosion resolved", since))
                armed_at = nil
            end
        end
        if since > 600 then
            console.log("  ... gave up after 600 frames; Explosion did not resolve")
            armed_at = nil
        end
    end

    emu.frameadvance()
end
