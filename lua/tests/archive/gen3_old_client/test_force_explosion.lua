--[[
  lua/tests/test_force_explosion.lua — FORCE-EXPLOSION COERCION TEST (Gen 3 / RR)

  Tests M.forceExplodeBattler — overwrites all 4 move slots of a player-side
  battler with Explosion (move 153, 5 PP each) so the FIGHT menu shows Explosion
  in every slot. Picking any slot self-faints the user.

  Lets you exercise the coercion by hand in a SINGLE BizHawk instance — no
  Soul Link server, no partner instance, no risk of losing a real mon.

  ⚠  WRITES TO RAM — save a BizHawk state before testing so you can restore.

  Controls:
    F1 → coerce battler 0 (player primary) to Explosion
    F2 → coerce battler 2 (player secondary, doubles only)
    F3 → restore original moves+PP for battler 0/2 from party data
    F4 → dump current gBattleMons moves+PP for all battlers
    F5 → instant fallback: faint slot 0 immediately (simulates the 600-frame
         timeout firing after a Damp / type-immunity stall)

  ┌─ TESTING CRITERIA ─────────────────────────────────────────────────────────
  │  A. Golden path
  │     → Enter any wild/trainer battle. Press F4 → confirm legitimate moves.
  │     → Press F1 → HUD line "moves=[153,153,153,153] pp=[5,5,5,5]".
  │     → Open FIGHT — all 4 slots read "Explosion".
  │     → Pick any slot → mon Explodes → self-faints → battle resolves.
  │     → PASS: visible Explosion animation, user mon at HP=0, no crash.
  │
  │  B. Abort / restore
  │     → After F1, press F3 instead of selecting a move.
  │     → HUD line returns to the original move IDs and PP values.
  │     → PASS: FIGHT menu shows original moves again.
  │
  │  C. Damp / no-effect
  │     → Battle a Poliwag/Wooper (Damp) in RR. Press F1 → pick Explosion.
  │     → Game prints "But it failed!" — mon stays alive.
  │     → Press F5 → simulates the in-client 600-frame fallback. Slot 0 HP→0.
  │     → PASS: fallback path zeros HP without crash.
  │
  │  D. Doubles
  │     → Enter any double battle. Press F2 → coerce battler 2 (P2 secondary).
  │     → HUD shows battler 2's move row updated to Explosion ×4.
  │     → PASS: only battler 2 changed; battler 0 untouched.
  │
  │  E. Out of battle
  │     → Press F1 in the overworld. Console logs "(not in battle — refused)".
  │     → PASS: no writes occur, no crash.
  │  FAIL: writes succeed but FIGHT menu still shows old moves
  │        → menu may be cached; close + reopen, or check BATTLE_MON_MOVES_OFF.
  │  FAIL: M.forceExplodeBattler returns false in battle
  │        → check M.BATTLE_MONS_ADDR for the active profile.
  └─────────────────────────────────────────────────────────────────────────────
--]]

-- ── path setup ────────────────────────────────────────────────────────────────
local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
local _lua_root = _src:match("(.+[/\\])tests[/\\]") or _src
package.path = _src .. "?.lua;" .. _lua_root .. "?.lua;" .. package.path

package.loaded["memory_gba"] = nil
local M = require("memory_gba")

-- ── startup ───────────────────────────────────────────────────────────────────
M.initProfile()
local ok, err = M.validateROM()
console.clear()
console.log(string.format("[TE] ROM validation: %s", ok and "OK" or ("FAIL – " .. tostring(err))))

-- Diagnostic: report which memory_gba.lua was actually loaded.  BizHawk's
-- package.path can resolve to an old snapshot in its own lua/ dir if CWD or
-- search-order isn't pointing at the worktree.
do
    local info = debug.getinfo(M.initProfile, "S")
    console.log(string.format("[TE] memory_gba source: %s", tostring(info and info.source or "<unknown>")))
end

-- Compatibility shim: define the new constants + helper on M if the loaded
-- memory_gba.lua is older than Phase 1 of the force-Explosion change.  Lets
-- the test exercise the memory writes even when a stale module was loaded.
if not M.BATTLE_MON_MOVES_OFF then
    console.log("[TE] WARN: loaded memory_gba.lua is STALE — missing BATTLE_MON_MOVES_OFF")
    console.log("[TE] WARN:   defining constants + forceExplodeBattler inline so the test still runs")
    console.log("[TE] WARN:   FIX UPSTREAM: ensure BizHawk loads memory_gba.lua from the worktree")
    M.BATTLE_MON_MOVES_OFF   = 0x0C
    M.BATTLE_MON_PP_OFF      = 0x24
    M.BATTLE_MON_STATUS2_OFF = 0x50
    M.MOVE_EXPLOSION         = 153
    M.STATUS2_MULTIPLETURNS  = 0x00000400
    M.STATUS2_LOCK_CONFUSE   = 0x0000C000
end
if not M.STATUS2_LOCK_CONFUSE then  -- shim: older module had MULTIPLETURNS but not LOCK_CONFUSE
    M.STATUS2_LOCK_CONFUSE   = 0x0000C000
end
-- Variant 3 active: full action-state pre-fill, no rampage.  Variants 1
-- (RECHARGE) and 2 (MULTIPLETURNS bit 12) both went through the rampage code
-- path which caused phantom-turn-2 softlocks.  Variant 3 writes directly to
-- the engine's chosen-action state at the canonical CFRU addresses, so the
-- engine sees "action already committed" and skips the menu without ever
-- entering rampage state.  No status2 modification, no gLockedMoves write.
-- Shim fallbacks if profile didn't load:
if not M.CHOSEN_ACTION_ADDR        then M.CHOSEN_ACTION_ADDR        = 0x02023D7C end
if not M.CHOSEN_MOVE_ADDR          then M.CHOSEN_MOVE_ADDR          = 0x02023DC4 end
if not M.BATTLE_COMM_ADDR          then M.BATTLE_COMM_ADDR          = 0x02023E82 end
if not M.BATTLE_STRUCT_PTR_ADDR    then M.BATTLE_STRUCT_PTR_ADDR    = 0x02023FE8 end
if not M.BATTLE_STRUCT_MOVE_TARGET_OFF      then M.BATTLE_STRUCT_MOVE_TARGET_OFF      = 0x0C end
if not M.BATTLE_STRUCT_CHOSEN_MOVE_POS_OFF  then M.BATTLE_STRUCT_CHOSEN_MOVE_POS_OFF  = 0x80 end

-- Always re-define forceExplodeBattler in the test so Variant-3 path is
-- exercised even if a stale memory_gba.lua was loaded.
function M.forceExplodeBattler(battler_idx)
    if not M.isInBattle() then return false end
    if not M.BATTLE_MONS_ADDR or M.BATTLE_MONS_ADDR == 0 then return false end
    if battler_idx < 0 then return false end
    local base = M.BATTLE_MONS_ADDR + battler_idx * M.BATTLE_MON_SIZE
    for i = 0, 3 do
        memory.write_u16_le(base + M.BATTLE_MON_MOVES_OFF + i * 2, M.MOVE_EXPLOSION)
        memory.write_u8   (base + M.BATTLE_MON_PP_OFF    + i,     5)
    end
    -- Legacy rampage path (kept for fallback compatibility).
    if M.LOCKED_MOVES_ADDR and M.LOCK_STATUS2_VALUE then
        memory.write_u16_le(M.LOCKED_MOVES_ADDR + battler_idx * 2, M.MOVE_EXPLOSION)
        local status2 = memory.read_u32_le(base + M.BATTLE_MON_STATUS2_OFF)
        memory.write_u32_le(base + M.BATTLE_MON_STATUS2_OFF, status2 | M.LOCK_STATUS2_VALUE)
    end
    -- Variant 3: pre-fill action-commit state at canonical CFRU addresses.
    if M.CHOSEN_ACTION_ADDR and M.CHOSEN_MOVE_ADDR and M.BATTLE_COMM_ADDR then
        memory.write_u8 (M.CHOSEN_ACTION_ADDR + battler_idx,     0)  -- USE_MOVE
        memory.write_u16_le(M.CHOSEN_MOVE_ADDR + battler_idx * 2, M.MOVE_EXPLOSION)
        memory.write_u8 (M.BATTLE_COMM_ADDR + battler_idx,        3)  -- STANDBY
        if M.BATTLE_STRUCT_PTR_ADDR then
            local bs = memory.read_u32_le(M.BATTLE_STRUCT_PTR_ADDR)
            if bs ~= 0 then
                if M.BATTLE_STRUCT_CHOSEN_MOVE_POS_OFF then
                    memory.write_u8(bs + M.BATTLE_STRUCT_CHOSEN_MOVE_POS_OFF + battler_idx, 0)
                end
                if M.BATTLE_STRUCT_MOVE_TARGET_OFF then
                    memory.write_u8(bs + M.BATTLE_STRUCT_MOVE_TARGET_OFF + battler_idx, 1)
                end
            end
        end
    end
    return true
end

console.log(string.format("[TE] LOCKED_MOVES_ADDR = %s",
    M.LOCKED_MOVES_ADDR and string.format("0x%08X", M.LOCKED_MOVES_ADDR) or "<nil — engine lock skipped>"))
console.log(string.format("[TE] LOCK_STATUS2_VALUE = %s",
    M.LOCK_STATUS2_VALUE and string.format("0x%08X", M.LOCK_STATUS2_VALUE) or "<nil — engine lock skipped>"))

console.log("[TE] Controls:")
console.log("[TE]   F1 = coerce battler 0 to Explosion (move slots + engine lock)")
console.log("[TE]   F2 = coerce battler 2 (doubles)")
console.log("[TE]   F3 = restore original moves; clear STATUS2_MULTIPLETURNS")
console.log("[TE]   F4 = dump gBattleMons moves+PP+status2 + gLockedMoves window")
console.log("[TE]   F5 = instant fallback (faint slot 0)")
console.log("[TE]   F6 = SCAN: find candidate gLockedMoves addrs (after using Outrage)")
console.log("[TE]   F7 = give battler 0 Outrage in slot 0 (for F6 discovery)")
console.log("[TE]   F8 = decode gBattleMons[0].status2 bits (compare to Outrage's writes)")
console.log("[TE]   F9 = toggle continuous monitor of gChosenMoveByBattler candidates")
console.log("[TE]   F10 = toggle byte-level monitor for gBattleCommunication discovery")
console.log("[TE] --- monitoring started ---")

-- ── per-frame state ───────────────────────────────────────────────────────────
local prev_keys      = {}
local prev_in_battle = nil
local prev_moves     = {[0]={}, [2]={}}  -- track moves per player-side battler
local prev_hp        = {}                -- party slot → last HP
-- When F1 coerces a battler, we track it here.  The cleanup that prevents the
-- "phantom turn 2 / double-faint" softlock fires when we detect the engine
-- has *committed* to using Explosion — signalled by PP[slot 0] decrementing
-- from the 5 we set during the coerce.  At that point the move's script has
-- already started; clearing the rampage state out from under it leaves no
-- stale lock for the engine to act on once the mon faints.
-- Fallback: also clear at HP=0 in case PP detection misses (e.g., if the
-- engine pre-deducts PP before our scan, we'd never see the transition).
local test_pending_explosions = {}  -- [battler] → {start_pp = N}
local INITIAL_LOCKED_PP        = 5
local test_frame_counter       = 0

-- ── helpers ───────────────────────────────────────────────────────────────────
local function log(msg) console.log("[TE] " .. msg) end

local function read_battle_hp(battler)
    return memory.read_u16_le(M.BATTLE_MONS_ADDR + battler * M.BATTLE_MON_SIZE + M.BATTLE_MON_HP_OFF)
end

local function read_battle_moves(battler)
    if not M.BATTLE_MONS_ADDR or M.BATTLE_MONS_ADDR == 0 then return {0,0,0,0}, {0,0,0,0} end
    local base = M.BATTLE_MONS_ADDR + battler * M.BATTLE_MON_SIZE
    local moves, pp = {}, {}
    for i = 0, 3 do
        moves[i+1] = memory.read_u16_le(base + M.BATTLE_MON_MOVES_OFF + i * 2)
        pp[i+1]    = memory.read_u8   (base + M.BATTLE_MON_PP_OFF    + i)
    end
    return moves, pp
end

-- Returns the party slot index for a player-side battler (0 or 2), or -1.
local function slot_for_battler(battler)
    if not M.BATTLER_PARTY_INDEXES_ADDR then return -1 end
    if battler == 0 then return memory.read_u16_le(M.BATTLER_PARTY_INDEXES_ADDR) end
    if battler == 2 and M.BATTLERS_COUNT_ADDR and memory.read_u8(M.BATTLERS_COUNT_ADDR) >= 4 then
        return memory.read_u16_le(M.BATTLER_PARTY_INDEXES_ADDR + 4)
    end
    return -1
end

local function coerce(battler)
    if not M.isInBattle() then
        log(string.format("F%d: not in battle — refused", battler == 0 and 1 or 2))
        return
    end
    local slot = slot_for_battler(battler)
    if slot < 0 then
        log(string.format("ACTION: coerce battler %d — no active slot (singles? wrong battler?)", battler))
        return
    end
    local before_moves, before_pp = read_battle_moves(battler)
    local okc = M.forceExplodeBattler(battler)
    local after_moves, after_pp = read_battle_moves(battler)
    if okc then
        test_pending_explosions[battler] = {start_pp = INITIAL_LOCKED_PP}
    end
    log(string.format("ACTION: coerce battler %d slot=%d  result=%s", battler, slot, tostring(okc)))
    log(string.format("  before moves=[%d,%d,%d,%d] pp=[%d,%d,%d,%d]",
        before_moves[1], before_moves[2], before_moves[3], before_moves[4],
        before_pp[1],    before_pp[2],    before_pp[3],    before_pp[4]))
    log(string.format("  after  moves=[%d,%d,%d,%d] pp=[%d,%d,%d,%d]",
        after_moves[1], after_moves[2], after_moves[3], after_moves[4],
        after_pp[1],    after_pp[2],    after_pp[3],    after_pp[4]))
end

local function restore_battler(battler)
    if not M.isInBattle() then
        log("F3: not in battle — refused")
        return
    end
    local slot = slot_for_battler(battler)
    if slot < 0 then return end  -- silent for absent battler 2 in singles
    local base = M.PARTY_BASE + slot * M.MON_SIZE
    local pmoves, ppp = M.decryptMoves(base)
    local bbase = M.BATTLE_MONS_ADDR + battler * M.BATTLE_MON_SIZE
    for i = 0, 3 do
        memory.write_u16_le(bbase + M.BATTLE_MON_MOVES_OFF + i * 2, pmoves[i+1])
        memory.write_u8   (bbase + M.BATTLE_MON_PP_OFF    + i,     ppp[i+1])
    end
    -- Clear our multi-turn lock bits (profile-specific) + zero gLockedMoves
    -- so the engine doesn't try to keep applying the lock after restore.
    local clear_mask = M.LOCK_STATUS2_VALUE or M.STATUS2_MULTIPLETURNS
    local status2    = memory.read_u32_le(bbase + M.BATTLE_MON_STATUS2_OFF)
    local cleared    = status2 & (~clear_mask)
    memory.write_u32_le(bbase + M.BATTLE_MON_STATUS2_OFF, cleared)
    if M.LOCKED_MOVES_ADDR then
        memory.write_u16_le(M.LOCKED_MOVES_ADDR + battler * 2, 0)
    end
    log(string.format("ACTION: restore battler %d slot=%d moves=[%d,%d,%d,%d] pp=[%d,%d,%d,%d] status2 0x%08X→0x%08X",
        battler, slot,
        pmoves[1], pmoves[2], pmoves[3], pmoves[4],
        ppp[1],    ppp[2],    ppp[3],    ppp[4],
        status2, cleared))
end

local function restore_all()
    restore_battler(0)
    restore_battler(2)
end

local function dump_battle_moves()
    if not M.isInBattle() then
        log("F4: not in battle")
        return
    end
    local bcount = (M.BATTLERS_COUNT_ADDR and memory.read_u8(M.BATTLERS_COUNT_ADDR)) or 2
    log(string.format("--- gBattleMons dump (battlers=%d) ---", bcount))
    if M.LOCKED_MOVES_ADDR then
        local lm = {}
        for b = 0, 3 do
            lm[b+1] = memory.read_u16_le(M.LOCKED_MOVES_ADDR + b * 2)
        end
        log(string.format("  gLockedMoves @ 0x%08X = [%d,%d,%d,%d]",
            M.LOCKED_MOVES_ADDR, lm[1], lm[2], lm[3], lm[4]))
    else
        log("  gLockedMoves: <LOCKED_MOVES_ADDR not set in profile>")
    end
    for b = 0, math.min(bcount - 1, 3) do
        local moves, pp = read_battle_moves(b)
        local bbase = M.BATTLE_MONS_ADDR + b * M.BATTLE_MON_SIZE
        local s2    = memory.read_u32_le(bbase + M.BATTLE_MON_STATUS2_OFF)
        local locked = (s2 & M.STATUS2_MULTIPLETURNS) ~= 0
        log(string.format("  B%d  status2=0x%08X%s",
            b, s2, locked and " (MULTIPLETURNS SET)" or ""))
        log(string.format("  B%d  moves=[%d,%d,%d,%d]  pp=[%d,%d,%d,%d]  hp=%d",
            b, moves[1], moves[2], moves[3], moves[4],
            pp[1], pp[2], pp[3], pp[4],
            read_battle_hp(b)))
    end
end

local function fallback_faint()
    log("ACTION: fallback faint slot 0 (simulates 600-frame timer firing)")
    M.forceFaint(0)
end

-- F6: scan EWRAM for a candidate gLockedMoves array.  Pre-condition: in battle,
-- the player has just used Outrage / Petal Dance / Thrash so the engine has
-- written that move id into gLockedMoves[0].  We scan the small EWRAM window
-- right after gBattleMons (where the address must live) for u16 matches.
-- F6 dual-purpose: scan EWRAM for known move IDs at strict-alignment
-- ([seed, 0, 0, 0] = looks like a per-battler u16[4] array with only battler 0
-- non-zero).  The seeds:
--   • Outrage / Petal Dance / Thrash  → find gLockedMoves (was the original
--                                       Phase 1 discovery, already complete)
--   • Explosion (153)                  → find gChosenMoveByBattler — used by
--                                       the engine to track "which move did
--                                       the player commit to this turn".
--                                       Write here to pre-fill the action.
local DISCOVERY_MOVES = {
    [200] = "Outrage / gLockedMoves seed",
    [80]  = "Petal Dance / gLockedMoves seed",
    [37]  = "Thrash / gLockedMoves seed",
    [153] = "Explosion / gChosenMoveByBattler seed",
}

-- F8: decode gBattleMons[0].status2 into named bits.  Compare what we set (via
-- F1) against what the engine sets (when Outrage is actually used) — if they
-- differ, the lock won't take effect.
local STATUS2_BITS = {
    {mask=0x00000007, name="CONFUSION (3-bit counter)"},
    {mask=0x00000008, name="FLINCHED"},
    {mask=0x00000070, name="UPROAR (3-bit counter)"},
    {mask=0x00000100, name="BIDE_lo"}, {mask=0x00000200, name="BIDE_hi"},
    {mask=0x00000400, name="MULTIPLETURNS  ← engine skips action-select"},
    {mask=0x0000C000, name="LOCK_CONFUSE (2-bit counter) ← required ≠ 0"},
    {mask=0x00003800, name="WRAPPED (3-bit counter)"},
    {mask=0x000F0000, name="INFATUATION (4 battlers)"},
    {mask=0x00100000, name="FOCUS_ENERGY"},
    {mask=0x00200000, name="TRANSFORMED"},
    {mask=0x00400000, name="RECHARGE"},
    {mask=0x00800000, name="RAGE"},
    {mask=0x01000000, name="SUBSTITUTE"},
    {mask=0x02000000, name="DESTINY_BOND"},
    {mask=0x04000000, name="ESCAPE_PREVENTION"},
    {mask=0x08000000, name="NIGHTMARE"},
    {mask=0x10000000, name="CURSED"},
    {mask=0x20000000, name="FORESIGHT"},
    {mask=0x40000000, name="DEFENSE_CURL"},
    {mask=0x80000000, name="TORMENT"},
}
local function decode_status2()
    if not M.isInBattle() then log("F8: not in battle") return end
    local base = M.BATTLE_MONS_ADDR + 0 * M.BATTLE_MON_SIZE
    local s2   = memory.read_u32_le(base + M.BATTLE_MON_STATUS2_OFF)
    log(string.format("--- gBattleMons[0].status2 @ 0x%08X = 0x%08X ---",
        base + M.BATTLE_MON_STATUS2_OFF, s2))
    if s2 == 0 then
        log("  (no flags set)")
        return
    end
    for _, b in ipairs(STATUS2_BITS) do
        local v = s2 & b.mask
        if v ~= 0 then
            log(string.format("  bit 0x%08X (%-50s) = 0x%X", b.mask, b.name, v))
        end
    end
end

-- F9: toggle continuous monitoring of the three [seed,0,0,0] candidates from
-- the F6 Explosion scan.  Once enabled, the test logs any time one of the
-- candidates' values changes — so you can see *which* address records the
-- move ID at the moment you pick a move.
--
-- Workflow:
--   1. F3 to restore original moves (don't use F1 for this discovery).
--   2. F9 to enable monitoring.  Initial values printed.
--   3. Open FIGHT in-game, hover slot N, press A to commit the move.
--   4. As soon as the engine writes the chosen move ID anywhere, the test
--      logs which address changed and to what value.
--   5. The address whose element [0] becomes the move you just picked is
--      gChosenMoveByBattler.
--   6. F9 again to disable monitoring.
-- F10: byte-level monitor to find gBattleCommunication (the action-select
-- state machine).  Records the FULL sequence of values each changing byte
-- took, then on F10-OFF filters to bytes that look like state machines:
-- max value < 16 (state IDs are tiny) and ≥ 2 transitions.
local BYTE_MONITOR_LO          = 0x02023C00   -- wider range — covers pre- and post-gBattleMons gaps
local BYTE_MONITOR_HI          = 0x02024020
local BYTE_HISTORY_CAP         = 16            -- record up to N transitions per byte
local byte_monitor_active      = false
local byte_monitor_snapshot    = {}
local byte_monitor_history     = {}  -- addr → {values = {v0, v1, ...}, max = N}

local function toggle_byte_monitor()
    byte_monitor_active = not byte_monitor_active
    if byte_monitor_active then
        log(string.format("F10: byte monitor ON — snapshotting 0x%08X..0x%08X (%d bytes)",
            BYTE_MONITOR_LO, BYTE_MONITOR_HI, BYTE_MONITOR_HI - BYTE_MONITOR_LO))
        byte_monitor_snapshot = {}
        byte_monitor_history  = {}
        for addr = BYTE_MONITOR_LO, BYTE_MONITOR_HI - 1 do
            byte_monitor_snapshot[addr] = memory.read_u8(addr)
        end
        log("F10: snapshot complete — open FIGHT, pick a move, then F10 again")
        log("F10: ⚠ keep window tight (just the action-select cycle) for cleanest data")
    else
        log("F10: byte monitor OFF — candidate state-machine bytes (max≤15, ≥2 transitions):")
        local sorted = {}
        for addr, h in pairs(byte_monitor_history) do
            if h.max <= 15 and #h.values >= 2 then
                table.insert(sorted, {addr=addr, h=h})
            end
        end
        table.sort(sorted, function(a, b)
            if #a.h.values ~= #b.h.values then return #a.h.values > #b.h.values end
            return a.addr < b.addr
        end)
        if #sorted == 0 then
            log("  (no state-machine-like bytes found — try a tighter capture window)")
        else
            for i = 1, math.min(#sorted, 20) do
                local e = sorted[i]
                local seq = table.concat(e.h.values, "→")
                log(string.format("  0x%08X  transitions=%d  values=[%s]",
                    e.addr, #e.h.values, seq))
            end
        end
    end
end

local function watch_bytes()
    if not byte_monitor_active then return end
    for addr = BYTE_MONITOR_LO, BYTE_MONITOR_HI - 1 do
        local cur  = memory.read_u8(addr)
        local snap = byte_monitor_snapshot[addr]
        if cur ~= snap then
            local h = byte_monitor_history[addr]
            if not h then
                h = {values = {snap, cur}, max = math.max(snap, cur)}
                byte_monitor_history[addr] = h
            else
                if #h.values < BYTE_HISTORY_CAP then
                    table.insert(h.values, cur)
                end
                if cur > h.max then h.max = cur end
            end
            byte_monitor_snapshot[addr] = cur
        end
    end
end

local CHOSEN_MOVE_CANDIDATES   = {0x02023D90, 0x02023D98, 0x02023DB0}
local chosen_move_monitoring   = false
local chosen_move_prev         = {}  -- [addr] → [v0,v1,v2,v3]

local function probe_chosen_move_snapshot()
    log("--- gChosenMoveByBattler candidate snapshot ---")
    for _, addr in ipairs(CHOSEN_MOVE_CANDIDATES) do
        local v0 = memory.read_u16_le(addr + 0)
        local v1 = memory.read_u16_le(addr + 2)
        local v2 = memory.read_u16_le(addr + 4)
        local v3 = memory.read_u16_le(addr + 6)
        log(string.format("  0x%08X = [%d, %d, %d, %d]", addr, v0, v1, v2, v3))
        chosen_move_prev[addr] = {v0, v1, v2, v3}
    end
    if M.LOCKED_MOVES_ADDR then
        local v = {}
        for i = 0, 3 do v[i+1] = memory.read_u16_le(M.LOCKED_MOVES_ADDR + i*2) end
        log(string.format("  gLockedMoves @ 0x%08X = [%d, %d, %d, %d]  (reference)",
            M.LOCKED_MOVES_ADDR, v[1], v[2], v[3], v[4]))
    end
end

local function toggle_chosen_move_monitoring()
    chosen_move_monitoring = not chosen_move_monitoring
    if chosen_move_monitoring then
        log("F9: MONITORING ON — pick a move now and watch for change logs")
        probe_chosen_move_snapshot()
    else
        log("F9: monitoring OFF")
        chosen_move_prev = {}
    end
end

local function watch_chosen_move_candidates()
    if not chosen_move_monitoring then return end
    for _, addr in ipairs(CHOSEN_MOVE_CANDIDATES) do
        local cur  = {
            memory.read_u16_le(addr + 0),
            memory.read_u16_le(addr + 2),
            memory.read_u16_le(addr + 4),
            memory.read_u16_le(addr + 6),
        }
        local prev = chosen_move_prev[addr]
        if prev and (cur[1] ~= prev[1] or cur[2] ~= prev[2]
                  or cur[3] ~= prev[3] or cur[4] ~= prev[4]) then
            log(string.format("CHOSEN-MOVE WATCH 0x%08X  [%d,%d,%d,%d] → [%d,%d,%d,%d]",
                addr, prev[1], prev[2], prev[3], prev[4],
                       cur[1],  cur[2],  cur[3],  cur[4]))
            chosen_move_prev[addr] = cur
        end
    end
end

-- F7: drop Outrage into battler 0 slot 0 so you have a multi-turn move to fire
-- for the F6 discovery flow.  Reversible via F3.
local MOVE_OUTRAGE = 200
local function grant_outrage()
    if not M.isInBattle() then
        log("F7: not in battle — refused")
        return
    end
    if not M.BATTLE_MONS_ADDR or M.BATTLE_MONS_ADDR == 0 then
        log("F7: BATTLE_MONS_ADDR not set")
        return
    end
    local base = M.BATTLE_MONS_ADDR + 0 * M.BATTLE_MON_SIZE  -- battler 0
    memory.write_u16_le(base + M.BATTLE_MON_MOVES_OFF + 0 * 2, MOVE_OUTRAGE)
    memory.write_u8   (base + M.BATTLE_MON_PP_OFF    + 0,     10)
    log("ACTION: granted battler 0 Outrage (move 200, 10 PP) in slot 0")
    log("        → open FIGHT, pick slot 0 (top-left). After the move lands,")
    log("          press F6 to scan for gLockedMoves.")
end

local function discover_locked_moves()
    if not M.BATTLE_MONS_ADDR then
        log("F6: BATTLE_MONS_ADDR not set; cannot scan")
        return
    end
    -- gLockedMoves is a 4×u16 EWRAM array; only battler 0 (the one using
    -- Outrage) should be non-zero.  Strict match pattern: [seed, 0, 0, 0].
    -- Aligned scan (every 2 bytes; u16 alignment).  Window extends from end of
    -- gBattleMons through ~0x300 bytes — well past where gLockedMoves can sit.
    local scan_lo = M.BATTLE_MONS_ADDR + 4 * M.BATTLE_MON_SIZE
    local scan_hi = scan_lo + 0x300
    log(string.format("F6: scanning EWRAM 0x%08X..0x%08X for [seed, 0, 0, 0] pattern",
        scan_lo, scan_hi))
    local strict, loose = {}, {}
    for addr = scan_lo, scan_hi - 8, 2 do
        local v0 = memory.read_u16_le(addr)
        local name = DISCOVERY_MOVES[v0]
        if name then
            local v1 = memory.read_u16_le(addr + 2)
            local v2 = memory.read_u16_le(addr + 4)
            local v3 = memory.read_u16_le(addr + 6)
            if v1 == 0 and v2 == 0 and v3 == 0 then
                table.insert(strict, {addr=addr, name=name})
            else
                table.insert(loose,  {addr=addr, name=name, v1=v1, v2=v2, v3=v3})
            end
        end
    end
    if #strict > 0 then
        log(string.format("F6: STRICT matches (look like gLockedMoves[0..3] = [seed, 0, 0, 0]):"))
        for _, c in ipairs(strict) do
            log(string.format("  ★ 0x%08X  (seed=%s, [+2..+6] all zero)", c.addr, c.name))
        end
    end
    if #loose > 0 and #loose <= 12 then
        log(string.format("F6: loose matches (seed found but adjacent words non-zero):"))
        for _, c in ipairs(loose) do
            log(string.format("  · 0x%08X  (seed=%s, next u16s = %d, %d, %d)",
                c.addr, c.name, c.v1, c.v2, c.v3))
        end
    end
    if #strict == 0 and #loose == 0 then
        log("F6: no candidates found — did you actually use Outrage this turn?")
        return
    end
    if #strict == 1 then
        log(string.format("F6: ✓ single STRICT match → use LOCKED_MOVES_ADDR = 0x%08X", strict[1].addr))
    else
        log("F6: pick the STRICT (★) address; update LOCKED_MOVES_ADDR in gen3_frlge.lua.")
    end
end

-- ── per-frame monitoring ──────────────────────────────────────────────────────
local function check_battle_state()
    local in_battle = M.isInBattle()
    if prev_in_battle ~= nil and in_battle ~= prev_in_battle then
        log(string.format("Battle state: %s → %s",
            prev_in_battle and "IN BATTLE" or "overworld",
            in_battle      and "IN BATTLE" or "overworld"))
    end
    prev_in_battle = in_battle
end

local function check_move_changes()
    if not M.isInBattle() or not M.BATTLE_MONS_ADDR or M.BATTLE_MONS_ADDR == 0 then return end
    for _, b in ipairs({0, 2}) do
        local slot = slot_for_battler(b)
        if slot >= 0 then
            local moves = read_battle_moves(b)
            local prev = prev_moves[b]
            local changed = false
            for i = 1, 4 do
                if prev[i] ~= nil and prev[i] ~= moves[i] then changed = true break end
            end
            if changed then
                local all_explosion = moves[1] == M.MOVE_EXPLOSION and moves[2] == M.MOVE_EXPLOSION
                                  and moves[3] == M.MOVE_EXPLOSION and moves[4] == M.MOVE_EXPLOSION
                log(string.format("MOVE CHANGE  B%d  [%d,%d,%d,%d → %d,%d,%d,%d] %s",
                    b, prev[1] or 0, prev[2] or 0, prev[3] or 0, prev[4] or 0,
                    moves[1], moves[2], moves[3], moves[4],
                    all_explosion and "(ALL EXPLOSION)" or ""))
            end
            prev_moves[b] = moves
        end
    end
end

-- Per-frame: reinforce the menu-skip writes while a coercion is pending.
-- The engine resets gBattleCommunication[battler] to a lower state at the
-- start of each action-select cycle, so a one-shot write at F1 gets
-- overwritten before the engine reads it.  We re-write every frame and
-- settle the moment Explosion's PP drops (engine committed) or HP hits 0.
local function settle_test_pending()
    if not next(test_pending_explosions) then return end
    local in_battle = M.isInBattle()
    for battler, st in pairs(test_pending_explosions) do
        local bhp, bpp0 = 0, st.start_pp
        if in_battle and M.BATTLE_MONS_ADDR and M.BATTLE_MONS_ADDR ~= 0 then
            local bmon = M.BATTLE_MONS_ADDR + battler * M.BATTLE_MON_SIZE
            bhp  = memory.read_u16_le(bmon + M.BATTLE_MON_HP_OFF)
            bpp0 = memory.read_u8   (bmon + M.BATTLE_MON_PP_OFF)
        end
        local pp_dropped = (bpp0 < st.start_pp)
        local hp_zero    = (in_battle and bhp == 0)
        if pp_dropped or hp_zero or not in_battle then
            -- Settle: clear lock state, stop reinforcing.
            if M.BATTLE_MONS_ADDR and M.LOCK_STATUS2_VALUE then
                local bmon = M.BATTLE_MONS_ADDR + battler * M.BATTLE_MON_SIZE
                local s2   = memory.read_u32_le(bmon + M.BATTLE_MON_STATUS2_OFF)
                memory.write_u32_le(bmon + M.BATTLE_MON_STATUS2_OFF, s2 & (~M.LOCK_STATUS2_VALUE))
            end
            if M.LOCKED_MOVES_ADDR then
                memory.write_u16_le(M.LOCKED_MOVES_ADDR + battler * 2, 0)
            end
            test_pending_explosions[battler] = nil
            local reason = pp_dropped and "PP-dropped" or (hp_zero and "HP=0") or "off-battle"
            log(string.format("[TE] EXPLOSION cleanup (%s) battler=%d  bhp=%d  pp0=%d",
                reason, battler, bhp, bpp0))
        elseif in_battle then
            -- Variant-3 reinforce: re-write gActionForBanks + gChosenMovesByBanks
            -- + gBattleCommunication + gBattleStruct sub-fields only when the
            -- engine hasn't already progressed past STANDBY (state 3).  Stale
            -- overwrites of advanced states would lock the engine in STANDBY
            -- and softlock the game.
            if M.BATTLE_COMM_ADDR and M.CHOSEN_ACTION_ADDR and M.CHOSEN_MOVE_ADDR then
                local cur_state = memory.read_u8(M.BATTLE_COMM_ADDR + battler)
                if cur_state < 3 then
                    memory.write_u8 (M.CHOSEN_ACTION_ADDR + battler,     0)
                    memory.write_u16_le(M.CHOSEN_MOVE_ADDR + battler * 2, M.MOVE_EXPLOSION)
                    memory.write_u8 (M.BATTLE_COMM_ADDR + battler,        3)
                    if M.BATTLE_STRUCT_PTR_ADDR then
                        local bs = memory.read_u32_le(M.BATTLE_STRUCT_PTR_ADDR)
                        if bs ~= 0 then
                            if M.BATTLE_STRUCT_CHOSEN_MOVE_POS_OFF then
                                memory.write_u8(bs + M.BATTLE_STRUCT_CHOSEN_MOVE_POS_OFF + battler, 0)
                            end
                            if M.BATTLE_STRUCT_MOVE_TARGET_OFF then
                                memory.write_u8(bs + M.BATTLE_STRUCT_MOVE_TARGET_OFF + battler, 1)
                            end
                        end
                    end
                    if st.last_logged_state ~= cur_state then
                        log(string.format(
                            "[TE] override battler %d: gBattleComm %d → 3 (action+move pre-filled)",
                            battler, cur_state))
                        st.last_logged_state = cur_state
                    end
                else
                    -- Engine progressed past 3 — reset the dedupe so we log
                    -- again if the engine cycles back into action-select.
                    st.last_logged_state = nil
                end
            end
        end
    end
end

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

-- ── diagnostic HUD (top-left corner) ──────────────────────────────────────────
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

    -- Battle mon rows (player-side only: battlers 0 and 2)
    if M.isInBattle() and M.BATTLE_MONS_ADDR and M.BATTLE_MONS_ADDR ~= 0 then
        for _, b in ipairs({0, 2}) do
            local slot = slot_for_battler(b)
            if slot >= 0 then
                local moves, pp = read_battle_moves(b)
                table.insert(lines, string.format(
                    "B%d(P%d):%d  moves=[%d,%d,%d,%d]  pp=[%d,%d,%d,%d]",
                    b, slot, read_battle_hp(b),
                    moves[1], moves[2], moves[3], moves[4],
                    pp[1], pp[2], pp[3], pp[4]))
            end
        end
    end

    for i, line in ipairs(lines) do
        gui.text(2, 2 + (i - 1) * 10, line, "white", "black")
    end
end

-- ── main frame handler ────────────────────────────────────────────────────────
local function on_frame()
    local keys = input.get()
    local function pressed(k) return keys[k] and not prev_keys[k] end

    if pressed("F1") then coerce(0) end
    if pressed("F2") then coerce(2) end
    if pressed("F3") then restore_all() end
    if pressed("F4") then dump_battle_moves() end
    if pressed("F5") then fallback_faint() end
    if pressed("F6") then discover_locked_moves() end
    if pressed("F7") then grant_outrage() end
    if pressed("F8") then decode_status2() end
    if pressed("F9")  then toggle_chosen_move_monitoring() end
    if pressed("F10") then toggle_byte_monitor() end

    prev_keys = keys

    test_frame_counter = test_frame_counter + 1
    check_battle_state()
    check_move_changes()
    check_party_hp()
    settle_test_pending()
    watch_chosen_move_candidates()
    watch_bytes()
    draw_hud()
end

local function on_frame_safe()
    local okf, errf = pcall(on_frame)
    if not okf then log("ERROR (handler kept alive): " .. tostring(errf)) end
end

event.onframeend(on_frame_safe, "t_explosion")
console.log("[TE] Force-explosion test running.")
