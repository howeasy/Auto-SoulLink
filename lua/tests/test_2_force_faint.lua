--[[
  lua/test_2_force_faint.lua — FORCE FAINT + WHITEOUT VALIDATION TEST

  Tests that HP=0 writes trigger correct in-game faint behaviour, including
  the whiteout sequence when the last party mon faints during a battle.

  This test writes HP=0 to BOTH gPlayerParty[slot].hp AND gBattleMons[battler].hp
  when called during a battle, so the battle engine's own faint detection fires.

  ⚠  WRITES TO RAM — save a BizHawk state before testing so you can restore.

  Controls:
    F1 → force-faint party slot 0
    F2 → force-faint party slot 1
    F3 → force-faint party slot 2
    F4 → restore all party mons to full HP (undo / reset)
    F5 → faint the last remaining LIVING party mon  (whiteout trigger)
    F6 → faint ALL party mons simultaneously        (full-party wipe)
    F7 → IMMEDIATE whiteout (skips animation, battle only)

  ┌─ TESTING CRITERIA ─────────────────────────────────────────────────────────
  │  A. In-battle faint (single mon)
  │     → Press F1 while in a battle. Console: "FAINT DETECTED slot 0 HP N→0"
  │     → ACTION log shows "party HP 0 / battle HP 0 OK" confirming both writes.
  │     → If pressed during move selection, faint animation plays after the
  │       player selects an action and the turn resolves (normal Gen III behaviour
  │       — HandleFaintedMonActions fires after move resolution, not every frame).
  │     → PASS: ACTION log shows both writes succeeded AND faint animation plays.
  │
  │  B. In-battle whiteout (last mon)
  │     → With only 1 mon alive in battle, press F5.
  │     → Console: "FAINT DETECTED", then "ALL PARTY FAINTED",
  │                then "WHITEOUT DETECTED (gBattleOutcome=2)" once the
  │                battle engine processes the HP=0 write.
  │     → If triggered during move selection, select any action to advance
  │       the battle engine; whiteout fires after the turn resolves.
  │       OR: press F7 to force immediate whiteout (skips faint animation).
  │     → PASS: all three log lines appear, player is teleported to PokeCenter.
  │
  │  C. Overworld full-party wipe
  │     → In the overworld (not in a battle), press F6.
  │     → Console: "ALL PARTY FAINTED (overworld — no automatic whiteout)"
  │     → The GAME does NOT auto-whiteout; the Soul Link server detects this.
  │     → Enter grass — the game will refuse the encounter or display an error
  │       about having no usable Pokémon.
  │     → PASS: console shows the overworld-wipe message, game does not crash.
  │
  │  D. HP restore
  │     → Press F4. Console lists every slot restored to full HP.
  │     → PASS: maxHP values match what the party menu shows.
  │        Note: F4 restores gPlayerParty HP only. In-battle HUD won't update
  │        until after the current turn (gBattleMons not touched by restore).
  │
  │  E. Immediate whiteout (in battle only)
  │     → Press F7 during any battle state.
  │     → Faint animation is skipped; game jumps straight to "blacked out"
  │       screen and teleports to PokeCenter on the very next frame.
  │     → PASS: whiteout screen appears within 1-2 frames, no crash.
  │     → FAIL/FREEZE: if it glitches, reload the savestate and retry
  │       from a quieter battle state (not mid-animation).
  │
  │  FAIL: party HP write fails     → address bug; report slot + address.
  │  FAIL: battle HP write fails    → check BATTLE_MONS_ADDR or battler lookup.
  │  FAIL: Wrong slot zeroed        → M.PARTY_BASE or MON_SIZE offset is wrong.
  │  FAIL: gBattleOutcome never = 2 → check BATTLE_OUTCOME_ADDR = 0x02023E8A
  └─────────────────────────────────────────────────────────────────────────────
--]]

-- ── path setup ────────────────────────────────────────────────────────────────
local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
package.path = _src .. "?.lua;" .. package.path

package.loaded["memory_gba"] = nil  -- always reload memory_gba.lua fresh on script restart
local M = require("memory_gba")

-- ── startup ───────────────────────────────────────────────────────────────────
M.initProfile()
local ok, err = M.validateROM()
console.clear()
console.log(string.format("[T2] ROM validation: %s", ok and "OK" or ("FAIL – " .. tostring(err))))
console.log("[T2] Controls:")
console.log("[T2]   F1/F2/F3 = faint slot 0/1/2")
console.log("[T2]   F4 = restore all HP")
console.log("[T2]   F5 = faint last living mon (whiteout trigger)")
console.log("[T2]   F6 = faint ALL party mons (full wipe)")
console.log("[T2] --- monitoring started ---")

-- ── per-frame state ───────────────────────────────────────────────────────────
local prev_keys        = {}
local prev_hp          = {}   -- slot → last seen HP value
local prev_in_battle   = nil  -- last isInBattle() result
local prev_outcome     = nil  -- last gBattleOutcome value
local prev_all_fainted = false

-- ── helpers ───────────────────────────────────────────────────────────────────
local function log(msg) console.log("[T2] " .. msg) end

-- Reads gBattleMons[battler].hp directly for diagnostic logging.
local function read_battle_hp(battler)
    return memory.read_u16_le(M.BATTLE_MONS_ADDR + battler * M.BATTLE_MON_SIZE + M.BATTLE_MON_HP_OFF)
end

local function faint_slot(slot)
    local base      = M.PARTY_BASE + slot * M.MON_SIZE
    local hp_before = memory.read_u16_le(base + M.OFF_HP)
    local maxHP     = memory.read_u16_le(base + M.OFF_MAX_HP)
    if maxHP == 0 then
        log(string.format("Slot %d is empty — skipped", slot))
        return
    end
    if hp_before == 0 then
        log(string.format("Slot %d already at 0 HP — skipped", slot))
        return
    end

    M.forceFaint(slot)

    local party_hp_after = memory.read_u16_le(base + M.OFF_HP)
    local battler = M.isInBattle() and M.getBattlerForPartySlot(slot) or -1

    if battler >= 0 then
        local battle_hp_after = read_battle_hp(battler)
        log(string.format(
            "ACTION: faint slot %d  party HP %d→%d / battle B%d HP→%d  key=%s  %s",
            slot, hp_before, party_hp_after,
            battler, battle_hp_after,
            M.monKey(base),
            (party_hp_after == 0 and battle_hp_after == 0) and "OK" or "PARTIAL WRITE"))
    else
        log(string.format(
            "ACTION: faint slot %d  party HP %d→%d  key=%s  %s%s",
            slot, hp_before, party_hp_after,
            M.monKey(base),
            party_hp_after == 0 and "OK" or "WRITE FAILED",
            M.isInBattle() and " (benched — no battle HP write)" or ""))
    end
end

local function restore_all_hp()
    local count = memory.read_u8(M.PARTY_COUNT_ADDR)
    for i = 0, count - 1 do
        local base  = M.PARTY_BASE + i * M.MON_SIZE
        local maxHP = memory.read_u16_le(base + M.OFF_MAX_HP)
        if maxHP > 0 then
            memory.write_u16_le(base + M.OFF_HP, maxHP)
            log(string.format("  restored slot %d: party HP→%d", i, maxHP))
        end
    end
    log(string.format("ACTION: restore all HP  (%d slots) — gPlayerParty only", count))
end

local function faint_last_living()
    local count  = memory.read_u8(M.PARTY_COUNT_ADDR)
    local target = -1
    for i = count - 1, 0, -1 do
        local base = M.PARTY_BASE + i * M.MON_SIZE
        if memory.read_u16_le(base + M.OFF_HP) > 0 then
            target = i
            break
        end
    end
    if target >= 0 then
        log("ACTION: faint last living mon (whiteout trigger)")
        faint_slot(target)
    else
        log("ACTION: faint last living — no living mons found")
    end
end

local function faint_all()
    log("ACTION: faint ALL party mons")
    local count = memory.read_u8(M.PARTY_COUNT_ADDR)
    for i = 0, count - 1 do
        faint_slot(i)
    end
end

local function force_immediate_whiteout()
    local in_battle = M.isInBattle()
    if in_battle then
        log("ACTION: immediate whiteout (battle) — zeroing HP, outcome=LOST, redirecting gBattleMainFunc")
    else
        log("ACTION: immediate whiteout (overworld) — zeroing all party HP for server detection")
    end
    local battle_path = M.forceImmediateWhiteout()
    if battle_path then
        log("  gBattleOutcome=2  gBattleMainFunc→ReturnFromBattleToOverworld")
        log("  Whiteout screen should appear within 1-2 frames (no faint animation)")
    else
        log("  All party HP set to 0 — Soul Link server will detect the wipeout")
    end
end

-- ── per-frame monitoring ──────────────────────────────────────────────────────
local function check_party_hp()
    local count = memory.read_u8(M.PARTY_COUNT_ADDR)
    for i = 0, count - 1 do
        local base = M.PARTY_BASE + i * M.MON_SIZE
        local hp   = memory.read_u16_le(base + M.OFF_HP)
        local prev = prev_hp[i]
        if prev ~= nil and prev > 0 and hp == 0 then
            log(string.format("FAINT DETECTED  slot %d  HP %d→0  key=%s",
                i, prev, M.monKey(base)))
        end
        prev_hp[i] = hp
    end
end

local function check_all_fainted()
    local all = M.allPartyFainted()
    if all and not prev_all_fainted then
        if M.isInBattle() then
            log("ALL PARTY FAINTED (in battle — expecting gBattleOutcome=2 soon)")
        else
            log("ALL PARTY FAINTED (overworld — no automatic whiteout; Soul Link server must detect)")
        end
    end
    prev_all_fainted = all
end

local function check_battle_outcome()
    local outcome = M.getBattleOutcome()
    if prev_outcome ~= nil and outcome ~= prev_outcome then
        local label = ({[1]="WON",[2]="LOST/WHITEOUT",[3]="RAN",[6]="CAUGHT"})[outcome]
            or tostring(outcome)
        log(string.format("gBattleOutcome CHANGED: %d→%d (%s)",
            prev_outcome, outcome, label))
        if outcome == M.OUTCOME_LOST then
            log("WHITEOUT DETECTED (gBattleOutcome=2)")
        end
    end
    prev_outcome = outcome
end

local function check_battle_state()
    local in_battle = M.isInBattle()
    if prev_in_battle ~= nil and in_battle ~= prev_in_battle then
        log(string.format("Battle state: %s → %s",
            prev_in_battle and "IN BATTLE" or "overworld",
            in_battle      and "IN BATTLE" or "overworld"))
    end
    prev_in_battle = in_battle
end

-- ── diagnostic HUD (top-left corner) ─────────────────────────────────────────
local function draw_hud()
    local count = memory.read_u8(M.PARTY_COUNT_ADDR)
    local lines = {}

    -- Party HP row
    local party_parts = {}
    for i = 0, count - 1 do
        local base = M.PARTY_BASE + i * M.MON_SIZE
        local hp   = memory.read_u16_le(base + M.OFF_HP)
        local max  = memory.read_u16_le(base + M.OFF_MAX_HP)
        table.insert(party_parts, string.format("P%d:%d/%d", i, hp, max))
    end
    table.insert(lines, "Party: " .. table.concat(party_parts, "  "))

    -- Battle HP row (only when in battle)
    if M.isInBattle() then
        local bcount = memory.read_u8(M.BATTLERS_COUNT_ADDR)
        local b_parts = {}
        for i = 0, bcount - 1 do
            local bhp = read_battle_hp(i)
            local pidx = memory.read_u16_le(M.BATTLER_PARTY_INDEXES_ADDR + i * 2)
            table.insert(b_parts, string.format("B%d(P%d):%d", i, pidx, bhp))
        end
        table.insert(lines, "Battle: " .. table.concat(b_parts, "  "))
    end

    for i, line in ipairs(lines) do
        gui.text(2, 2 + (i - 1) * 10, line, "white", "black")
    end
end

-- ── main frame handler ────────────────────────────────────────────────────────
local function on_frame()
    local keys = input.get()
    local function pressed(k) return keys[k] and not prev_keys[k] end

    if pressed("F1") then faint_slot(0) end
    if pressed("F2") then faint_slot(1) end
    if pressed("F3") then faint_slot(2) end
    if pressed("F4") then restore_all_hp() end
    if pressed("F5") then faint_last_living() end
    if pressed("F6") then faint_all() end
    if pressed("F7") then force_immediate_whiteout() end

    prev_keys = keys

    check_battle_state()
    check_battle_outcome()
    check_party_hp()
    check_all_fainted()
    draw_hud()
end

local function on_frame_safe()
    local ok2, err2 = pcall(on_frame)
    if not ok2 then log("ERROR (handler kept alive): " .. tostring(err2)) end
end

event.onframeend(on_frame_safe, "t2_force_faint")
console.log("[T2] Force faint test running.")