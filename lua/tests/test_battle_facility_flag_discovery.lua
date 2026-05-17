--[[
  lua/tests/test_battle_facility_flag_discovery.lua
  =================================================
  Discovers what signal authoritatively marks a "borrowed-party" battle in
  RR / CFRU — battles where the overworld script swaps gPlayerParty for a
  preset team BEFORE gBattleTypeFlags is set, so the engine's
  BATTLE_TYPE_BATTLE_TOWER / _SANDS / etc. bits don't fire on the actual
  battles that need to be detected.

  Watches three things at once:
    1. SaveBlock1.flags[]  — looking for FLAG_BATTLE_FACILITY or similar
    2. SaveBlock1.vars[]   — looking for VAR_BATTLE_FACILITY_* set in overworld
    3. gPlayerParty PIDs   — direct detection of the actual swap
       (slot count + first-4-bytes-of-each-slot, 24 bytes total)

  And on every BATTLE START logs:
    - gBattleTypeFlags     (full 32-bit value)
    - gTrainerBattleOpponent_A  (RR uses 1-based trainer IDs)
    - whether the party PIDs changed since baseline (the swap signal)

  HOTKEYS (polled via input.get; F-keys must be pressed in the BizHawk
  emulator window, not the Lua Console):
    F1 = summary (intersection of 0→1 flags across runs)
    F2 = re-baseline NOW (do this in overworld with your real party)
    F3 = dump all observed VAR writes per run

  HOW TO USE
  ----------
  1. Load RR (or any CFRU hack) in BizHawk and open the Lua Console.
  2. Stand in the OVERWORLD with your REAL party.  Load this script.
     A baseline is captured automatically on the first frame.
  3. Walk up to a borrowed-party trainer / NPC / facility and accept.
  4. The script logs every flag transition, var write, and party-PID
     mass-swap.  When the battle starts, it logs the trainer ID and
     battle-type flags.  After the battle, F2 in overworld to re-baseline
     for the next run.
  5. F1 for the summary — flags that fired in EVERY post-baseline run are
     the FLAG_BATTLE_FACILITY candidate.  If none fire, the swap signal
     (mass party-PID change) is the only authoritative signal.

  Results also written to lua/tests/battle_facility_flag_results.txt.
--]]

local fmt = string.format
local r8  = memory.read_u8
local r16 = memory.read_u16_le
local r32 = memory.read_u32_le

local _dir = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
package.path = _dir .. "..\\?.lua;" .. _dir .. "../?.lua;" .. package.path
local M = require("memory_gba")
local game_detect = require("game_detect")
local detected = game_detect.detect()
M.applyProfile(detected.profile, detected.variant)

if not M.SB1_PTR_ADDR or not M.SB1_FLAGS_OFFSET or not M.SB1_VARS_OFFSET then
    console.log("[FAC-DISC] Profile '" .. tostring(detected.variant)
        .. "' is missing SB1_PTR_ADDR / SB1_FLAGS_OFFSET / SB1_VARS_OFFSET. "
        .. "Cannot read SaveBlock1 — exiting.")
    return
end

local FLAGS_BYTES = 128
local VARS_BYTES  = 512   -- 256 vars × 2 bytes

-- ── Output file ──────────────────────────────────────────────────────────────
local _lines = {}
local OUT_PATH
local function _try_path(p)
    local ok, f = pcall(io.open, p, "w")
    if ok and f then f:write("") f:close() return true end
    return false
end
do
    local p1 = _dir .. "battle_facility_flag_results.txt"
    if _try_path(p1) then OUT_PATH = p1
    elseif _try_path("battle_facility_flag_results.txt") then
        OUT_PATH = "battle_facility_flag_results.txt"
    end
end

local function log(line)
    console.log(line)
    _lines[#_lines + 1] = line
    if OUT_PATH then
        local f = io.open(OUT_PATH, "w")
        if f then
            for _, l in ipairs(_lines) do f:write(l .. "\n") end
            f:close()
        end
    end
end

-- ── SB1 / party read helpers ─────────────────────────────────────────────────
local function sb1_base()
    local ok, sb1 = pcall(r32, M.SB1_PTR_ADDR)
    if not ok or not sb1 or sb1 < 0x02000000 or sb1 >= 0x02040000 then return nil end
    return sb1
end

local function read_flags_block(sb1)
    if not sb1 then return nil end
    local bytes = {}
    for i = 0, FLAGS_BYTES - 1 do
        bytes[i + 1] = r8(sb1 + M.SB1_FLAGS_OFFSET + i)
    end
    return bytes
end

local function read_vars_block(sb1)
    if not sb1 then return nil end
    local vars = {}
    for i = 0, (VARS_BYTES // 2) - 1 do
        vars[i + 1] = r16(sb1 + M.SB1_VARS_OFFSET + i * 2)
    end
    return vars
end

-- Read party PIDs (first 4 bytes of each Pokemon struct).  Returns table
-- [slot] = pid (u32) for slots 0..5.  Slots beyond party_count return 0.
local function read_party_pids()
    local pids = {}
    if not M.PARTY_BASE or not M.PARTY_COUNT_ADDR then return pids end
    for slot = 0, 5 do
        local base = M.PARTY_BASE + slot * M.MON_SIZE
        local ok, pid = pcall(r32, base)
        pids[slot] = ok and pid or 0
    end
    return pids
end

local function pids_equal(a, b)
    for i = 0, 5 do
        if (a[i] or 0) ~= (b[i] or 0) then return false end
    end
    return true
end

local function pids_diff_count(a, b)
    local n = 0
    for i = 0, 5 do
        if (a[i] or 0) ~= (b[i] or 0) then n = n + 1 end
    end
    return n
end

-- ── State ────────────────────────────────────────────────────────────────────
local baseline_flags  = nil
local baseline_vars   = nil
local baseline_pids   = nil  -- party PIDs at baseline (real party)
local prev_flags      = nil
local prev_vars       = nil
local prev_pids       = nil
local current_frame   = 0
local prev_in_battle  = false

local runs            = {}
local current_run     = nil

local function start_run(label)
    current_run = {
        start_frame = current_frame,
        flag_set    = {},
        var_writes  = {},
        mode_label  = label or ("run#" .. (#runs + 1)),
    }
    runs[#runs + 1] = current_run
    log(fmt("[FAC-DISC] >>> new run started: %s (frame=%d)",
            current_run.mode_label, current_frame))
end

local function baseline()
    local sb1 = sb1_base()
    if not sb1 then
        log("[FAC-DISC] SB1 pointer is invalid — cannot baseline.")
        return
    end
    baseline_flags = read_flags_block(sb1)
    baseline_vars  = read_vars_block(sb1)
    baseline_pids  = read_party_pids()
    prev_flags     = {}
    prev_vars      = {}
    prev_pids      = {}
    for i, v in ipairs(baseline_flags) do prev_flags[i] = v end
    for i, v in ipairs(baseline_vars)  do prev_vars[i]  = v end
    for i = 0, 5 do prev_pids[i] = baseline_pids[i] end
    log(fmt("[FAC-DISC] BASELINE captured (sb1=0x%08X, %d flag bytes, %d vars)",
            sb1, FLAGS_BYTES, VARS_BYTES // 2))
    log(fmt("[FAC-DISC]   baseline party PIDs: %08X %08X %08X %08X %08X %08X",
            baseline_pids[0], baseline_pids[1], baseline_pids[2],
            baseline_pids[3], baseline_pids[4], baseline_pids[5]))
    start_run("baseline")
end

local function summary()
    log("---- [FAC-DISC] SUMMARY ----")
    log(fmt("[FAC-DISC] runs recorded: %d", #runs))
    if #runs < 2 then
        log("[FAC-DISC] At least 2 runs needed to find a common flag.")
        log("[FAC-DISC] Press F2 in overworld between facility entries to re-baseline.")
        return
    end
    local intersection = nil
    for i = 2, #runs do
        local s = runs[i].flag_set
        if not intersection then
            intersection = {}
            for k in pairs(s) do intersection[k] = true end
        else
            for k in pairs(intersection) do
                if not s[k] then intersection[k] = nil end
            end
        end
    end
    log("[FAC-DISC] flags set 0→1 in EVERY post-baseline run:")
    local common = {}
    for k in pairs(intersection or {}) do common[#common + 1] = k end
    table.sort(common)
    if #common == 0 then
        log("[FAC-DISC]   (none — no SB1 flag is set consistently across runs)")
        log("[FAC-DISC]   This means the borrowed-party trigger is NOT a save-flag.")
        log("[FAC-DISC]   The authoritative signal is the gPlayerParty PID swap itself.")
    else
        for _, fid in ipairs(common) do
            log(fmt("[FAC-DISC]   FLAG_CANDIDATE = 0x%04X (%d)", fid, fid))
        end
    end
end

local function dump_vars()
    log("---- [FAC-DISC] VAR DUMP ----")
    for idx, run in ipairs(runs) do
        log(fmt("[FAC-DISC] run %d (%s) frame=%d", idx, run.mode_label, run.start_frame))
        local ids = {}
        for vid in pairs(run.var_writes) do ids[#ids + 1] = vid end
        table.sort(ids)
        for _, vid in ipairs(ids) do
            log(fmt("[FAC-DISC]   VAR 0x%04X = %d", vid, run.var_writes[vid]))
        end
    end
end

-- ── EWRAM scanner: find the real-party backup buffer (Path B) ────────────────
-- During a borrowed-party swap, the engine still has the real party stored
-- somewhere (it gets restored post-battle).  If we can find that address,
-- the bridge could read the real party directly while frozen, skipping the
-- snapshot/revert dance.  This scanner looks for the baseline slot-0 PID
-- (matched against slot-1 PID at +0x64 for additional discrimination when
-- the party has 2+ mons) across all of EWRAM, in chunks per frame.

local EWRAM_START   = 0x02000000
local EWRAM_LEN     = 0x40000          -- 256 KB
local SCAN_CHUNK    = 1024             -- u32s scanned per frame (~64 frames = ~1 s total)

local scan_state = {
    active        = false,  -- scan in progress
    addr          = 0,      -- next address to read
    target_pid_0  = nil,    -- baseline slot-0 PID
    target_pid_1  = nil,    -- baseline slot-1 PID (0 if 1-mon party)
    target_has_p1 = false,  -- whether slot-1 is meaningfully non-zero
    matches       = {},     -- addresses where slot-0 PID was found
    matches_strict = {},    -- subset where slot-1 also matched at +0x64
    started_frame = 0,
    label         = "",
    fired_this_swap = false, -- one-shot guard for auto-trigger per swap cycle
}
local last_scan_matches = nil  -- frozen copy of strict matches from last scan
                               -- used by F5 (rescan_and_intersect)

local function _addr_in_live_party(addr)
    if not M.PARTY_BASE then return false end
    return addr >= M.PARTY_BASE and addr < M.PARTY_BASE + 6 * (M.MON_SIZE or 100)
end

local function start_scan(label)
    if not baseline_pids then
        log("[SCAN] No baseline yet — cannot scan.")
        return
    end
    if not M.PARTY_BASE then
        log("[SCAN] No M.PARTY_BASE — cannot scan.")
        return
    end
    scan_state.active        = true
    scan_state.addr          = EWRAM_START
    scan_state.target_pid_0  = baseline_pids[0]
    scan_state.target_pid_1  = baseline_pids[1] or 0
    scan_state.target_has_p1 = (baseline_pids[1] or 0) ~= 0
    scan_state.matches       = {}
    scan_state.matches_strict = {}
    scan_state.started_frame = current_frame
    scan_state.label         = label or "manual"
    log(fmt("[SCAN] starting EWRAM scan (%s) frame=%d  target slot-0 PID=%08X (slot-1 verify=%s)",
            label, current_frame, scan_state.target_pid_0,
            scan_state.target_has_p1 and fmt("%08X", scan_state.target_pid_1) or "off"))
end

local function tick_scan()
    if not scan_state.active then return end
    local end_addr = math.min(scan_state.addr + SCAN_CHUNK * 4, EWRAM_START + EWRAM_LEN)
    local target0  = scan_state.target_pid_0
    local target1  = scan_state.target_pid_1
    local check1   = scan_state.target_has_p1
    local mon_size = M.MON_SIZE or 100
    for addr = scan_state.addr, end_addr - 4, 4 do
        if not _addr_in_live_party(addr) then
            local ok, v = pcall(r32, addr)
            if ok and v == target0 then
                scan_state.matches[#scan_state.matches + 1] = addr
                if check1 then
                    local ok2, v2 = pcall(r32, addr + mon_size)
                    if ok2 and v2 == target1 then
                        scan_state.matches_strict[#scan_state.matches_strict + 1] = addr
                    end
                end
            end
        end
    end
    scan_state.addr = end_addr
    if scan_state.addr >= EWRAM_START + EWRAM_LEN then
        scan_state.active = false
        local list = scan_state.target_has_p1 and scan_state.matches_strict or scan_state.matches
        log(fmt("[SCAN] DONE (%s) frame=%d  %d matches%s",
                scan_state.label, current_frame, #list,
                scan_state.target_has_p1 and " (strict: slot-0 + slot-1 verified)" or ""))
        local mon_size = M.MON_SIZE or 100
        for _, a in ipairs(list) do
            log(fmt("[SCAN]   candidate @ 0x%08X", a))
            -- Dump first u32 of each of the 6 putative slots so the user can
            -- eyeball-verify the candidate has the real party's layout.
            -- For a 1-mon party: should be REAL_PID, 0, 0, 0, 0, 0.
            -- For a 3-mon party: should be PID0, PID1, PID2, 0, 0, 0.
            local slots = {}
            for s = 0, 5 do
                local ok, v = pcall(r32, a + s * mon_size)
                slots[#slots + 1] = ok and fmt("%08X", v) or "????????"
            end
            log(fmt("[SCAN]     struct PIDs @ +0,+%d,+%d,...: %s",
                    mon_size, mon_size * 2, table.concat(slots, " ")))
            -- Also dump u16 at offset OFF_LEVEL/OFF_HP/OFF_MAX_HP of slot 0 if
            -- the memory module exposes those, so we can cross-check vs the
            -- user's real party.
            if M.OFF_LEVEL and M.OFF_HP and M.OFF_MAX_HP then
                local ok_lv, lv  = pcall(r8,  a + M.OFF_LEVEL)
                local ok_hp, hp  = pcall(r16, a + M.OFF_HP)
                local ok_mh, mh  = pcall(r16, a + M.OFF_MAX_HP)
                log(fmt("[SCAN]     slot 0: level=%s hp=%s/%s",
                        ok_lv and tostring(lv) or "?",
                        ok_hp and tostring(hp) or "?",
                        ok_mh and tostring(mh) or "?"))
            end
        end
        if scan_state.target_has_p1 then
            log(fmt("[SCAN]   (raw slot-0-only match count: %d — strict filter dropped %d)",
                    #scan_state.matches,
                    #scan_state.matches - #scan_state.matches_strict))
        end
        -- Freeze for later F5 intersection.
        last_scan_matches = {}
        for _, a in ipairs(list) do last_scan_matches[#last_scan_matches + 1] = a end
    end
end

-- ── Per-frame ────────────────────────────────────────────────────────────────
local function on_frame()
    current_frame = current_frame + 1
    if not baseline_flags then baseline() return end

    local sb1 = sb1_base()
    if not sb1 then return end
    local flags = read_flags_block(sb1)
    local vars  = read_vars_block(sb1)
    local pids  = read_party_pids()

    -- Flag transitions
    for byte_idx = 1, FLAGS_BYTES do
        local b_curr = flags[byte_idx]
        local b_prev = prev_flags[byte_idx]
        if b_curr ~= b_prev then
            for bit = 0, 7 do
                local mask = 2 ^ bit
                local was_set = (b_prev // mask) % 2 == 1
                local is_set  = (b_curr // mask) % 2 == 1
                if is_set and not was_set then
                    local flag_id = (byte_idx - 1) * 8 + bit
                    log(fmt("[FAC-DISC]   FLAG %04X (id=%d) 0→1  frame=%d",
                            flag_id, flag_id, current_frame))
                    if current_run then current_run.flag_set[flag_id] = true end
                elseif was_set and not is_set then
                    local flag_id = (byte_idx - 1) * 8 + bit
                    log(fmt("[FAC-DISC]   FLAG %04X (id=%d) 1→0  frame=%d",
                            flag_id, flag_id, current_frame))
                end
            end
            prev_flags[byte_idx] = b_curr
        end
    end

    -- Var writes
    for i = 1, #vars do
        if vars[i] ~= prev_vars[i] then
            local var_id = 0x4000 + (i - 1)
            log(fmt("[FAC-DISC]   VAR  %04X (id=%d) %d → %d  frame=%d",
                    var_id, var_id, prev_vars[i], vars[i], current_frame))
            if current_run then current_run.var_writes[var_id] = vars[i] end
            prev_vars[i] = vars[i]
        end
    end

    -- Party-PID swap detection (the actual borrowed-party signal)
    local diff = pids_diff_count(prev_pids, pids)
    if diff > 0 then
        local same_as_baseline = pids_equal(pids, baseline_pids)
        log(fmt("[FAC-DISC]   PARTY swap (%d/6 slots changed)  frame=%d  baseline_match=%s",
                diff, current_frame, tostring(same_as_baseline)))
        log(fmt("[FAC-DISC]     now: %08X %08X %08X %08X %08X %08X",
                pids[0], pids[1], pids[2], pids[3], pids[4], pids[5]))
        for i = 0, 5 do prev_pids[i] = pids[i] end
    end

    -- Path B: auto-fire EWRAM scan once per swap (when diff vs baseline ≥ 3).
    -- Re-arms after a full revert.
    if baseline_pids and not scan_state.active and not scan_state.fired_this_swap then
        local d = pids_diff_count(pids, baseline_pids)
        if d >= 3 then
            scan_state.fired_this_swap = true
            start_scan("auto-on-swap")
        end
    elseif baseline_pids and scan_state.fired_this_swap and pids_equal(pids, baseline_pids) then
        -- Party reverted; arm for the next swap
        scan_state.fired_this_swap = false
    end

    tick_scan()

    -- Battle transition logging
    local in_battle = M.isInBattle and M.isInBattle() or false
    if in_battle and not prev_in_battle then
        local btf = M.BATTLE_TYPE_ADDR and r32(M.BATTLE_TYPE_ADDR) or 0
        local tid = M.TRAINER_OPPONENT_ADDR and r16(M.TRAINER_OPPONENT_ADDR) or 0
        local restored_match = pids_equal(pids, baseline_pids)
        log(fmt("[FAC-DISC]   *** BATTLE START frame=%d", current_frame))
        log(fmt("[FAC-DISC]       gBattleTypeFlags     = 0x%08X", btf))
        log(fmt("[FAC-DISC]       gTrainerBattleOpponent_A = %d (0x%04X)", tid, tid))
        log(fmt("[FAC-DISC]       party matches baseline   = %s (diff vs baseline = %d slots)",
                tostring(restored_match), pids_diff_count(pids, baseline_pids)))
    elseif not in_battle and prev_in_battle then
        log(fmt("[FAC-DISC]   *** BATTLE END   frame=%d", current_frame))
    end
    prev_in_battle = in_battle
end

-- F5: re-scan and intersect against the most recent scan's results.
-- Used after a swap-revert-swap cycle: addresses that hold the baseline
-- slot-0 PID across multiple scans (especially during freeze) are the
-- backup-buffer candidate.
local function rescan_and_intersect()
    if not last_scan_matches then
        log("[SCAN] No prior scan to intersect with. Trigger one first (F4).")
        return
    end
    -- Snapshot current matches synchronously (small enough; <10K cells typically)
    local target = baseline_pids and baseline_pids[0]
    if not target then log("[SCAN] No baseline.") return end
    local now = {}
    for addr = EWRAM_START, EWRAM_START + EWRAM_LEN - 4, 4 do
        if not _addr_in_live_party(addr) then
            local ok, v = pcall(r32, addr)
            if ok and v == target then now[addr] = true end
        end
    end
    local persistent = {}
    for _, addr in ipairs(last_scan_matches) do
        if now[addr] then persistent[#persistent + 1] = addr end
    end
    log(fmt("[SCAN] INTERSECT frame=%d  prior=%d  now=%d  persistent=%d",
            current_frame, #last_scan_matches,
            (function() local n=0; for _ in pairs(now) do n=n+1 end; return n end)(),
            #persistent))
    for _, a in ipairs(persistent) do
        log(fmt("[SCAN]   persistent @ 0x%08X", a))
    end
end

-- ── Hotkey polling (input.get with edge detection) ───────────────────────────
local prev_keys = {}
local function poll_hotkeys()
    local ok, keys = pcall(input.get)
    if not ok or not keys then return end
    if keys.F1 and not prev_keys.F1 then summary() end
    if keys.F2 and not prev_keys.F2 then baseline() end
    if keys.F3 and not prev_keys.F3 then dump_vars() end
    if keys.F4 and not prev_keys.F4 then start_scan("manual") end
    if keys.F5 and not prev_keys.F5 then rescan_and_intersect() end
    prev_keys = keys
end

event.onframeend(function()
    on_frame()
    poll_hotkeys()
end)

console.log("========================================================================")
console.log("[FAC-DISC] SB1 facility flag/var discovery loaded (v2)")
console.log(fmt("  profile          = %s", detected.variant or "?"))
console.log(fmt("  SB1_PTR_ADDR     = 0x%08X", M.SB1_PTR_ADDR))
console.log(fmt("  SB1_FLAGS_OFFSET = 0x%04X", M.SB1_FLAGS_OFFSET))
console.log(fmt("  SB1_VARS_OFFSET  = 0x%04X", M.SB1_VARS_OFFSET))
console.log(fmt("  TRAINER_OPPONENT_ADDR = %s", M.TRAINER_OPPONENT_ADDR
    and fmt("0x%08X", M.TRAINER_OPPONENT_ADDR) or "(nil)"))
console.log("")
console.log("  Press these F-keys in the BIZHAWK EMULATOR WINDOW (not the Lua Console):")
console.log("    F1 = print summary (intersection of 0→1 flags across runs)")
console.log("    F2 = re-baseline (do this in overworld before each facility entry)")
console.log("    F3 = dump all observed VAR writes per run")
console.log("    F4 = trigger manual EWRAM scan for the real-party backup buffer")
console.log("    F5 = re-scan and intersect — addresses still holding the baseline PID")
console.log("         are the persistent backup-buffer candidate (Path B)")
console.log("========================================================================")
