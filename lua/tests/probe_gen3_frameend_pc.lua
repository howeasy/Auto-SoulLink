--[[
  lua/tests/probe_gen3_frameend_pc.lua — P1 frame-end CPU census (docs/gen3/PLAN.md §5.3, §6 P1).

  Read-only observer, driven by tools/run_gate.py. On every event.onframeend, samples R15, CPSR
  (mode bits 0-4, T bit 5, I bit 7), SP (R13), gMain.callback1/callback2, sScriptContext2Enabled,
  gPaletteFade.active, gMain.inBattle and the active gTasks[] function set; buckets the frame into
  a coarse state label; aggregates over ~1800 frames (interim line at 600); prints per-label
  frame counts, top-10 distinct R15 values, distinct CPSR mode/T combinations, top-10 distinct
  task-function sets, and whether R15 ever parks in the BIOS range. This is PHYSICAL evidence for
  the checkpoint predicate's SOURCE decision on a parked-PC clause (PLAN §5.3, §6 P1 note).

  No walking/menu automation here — the coordinator drives natural play (walk, START menu, grass)
  while this script samples passively.
--]]

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT")
    or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT = WT .. "/patch/build/probe_gen3_frameend_pc_result.txt"

-- Mirror lua/clients/gen3_frlge_client.lua's package.path setup so require("memory_gba") /
-- require("game_detect") resolve from lua/tests/.
package.path = WT .. "/lua/?.lua;" .. WT .. "/lua/games/?.lua;" .. package.path

local lines = {}
local function log(s) lines[#lines + 1] = s; console.log(s) end
local function finish(ok, why)
    log(ok and "RESULT: PASS" or ("RESULT: FAIL " .. tostring(why)))
    local f = io.open(OUT, "w")
    if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
    client.exit()
end

local M = require("memory_gba")
local game_detect = require("game_detect")
local detected = game_detect.detect()
M.applyProfile(detected.profile, detected.variant)
-- Optional overworld savestate (the live gates load theirs the same way, e.g.
-- test_live_partyevents.lua:17,45); without it the census samples the title screen only.
local STATE = os.getenv("SLINK_STATE")
if STATE and STATE ~= "" then
    local ok_ss = pcall(savestate.load, STATE)
    console.log("[census] savestate " .. STATE .. " -> " .. tostring(ok_ss))
    emu.frameadvance()
end
local P = detected.profile
log(string.format("[probe] variant=%s game_id=%s", tostring(detected.variant), tostring(detected.game_id)))

-- gMain.callback2: profile GMAIN_ADDR + GMAIN_CB2_OFFSET on vanilla (games/gen3_frlge.lua
-- GMAIN_ADDR/GMAIN_CB2_OFFSET). RR's GMAIN_ADDR is nil (games/gen3_frlge.lua:254); CFRU preserves
-- gMain at the vanilla address, so the peer-ghost receiver reads callback2 straight off the fixed
-- literal 0x030030F4 (lua/peer_ghost_npc.lua:62) — reused verbatim here, †UNVERIFIED-source only
-- in the sense that no profile field names it for RR.
local CB2_ADDR = (P.GMAIN_ADDR and (P.GMAIN_ADDR + (P.GMAIN_CB2_OFFSET or 0x04))) or 0x030030F4
if not P.GMAIN_ADDR then log("[probe] †UNVERIFIED-source: RR gMain.callback2 @ 0x030030F4 per lua/peer_ghost_npc.lua:62 (no profile field)") end
-- callback1: struct Main convention is callback1 immediately before callback2 (+0x00 vs +0x04).
-- No GMAIN_CB1_OFFSET field exists in any profile and pokefirered is not in the local pret cache
-- (.cache/pret has no pokefirered checkout) — this offset is †UNVERIFIED-source.
local CB1_ADDR = CB2_ADDR - 0x04
log("[probe] †UNVERIFIED-source: gMain.callback1 offset assumed +0x00 (CB1_ADDR = CB2_ADDR-4); not pinned locally")

-- gPaletteFade.active: 0x02037AB8 (BPRE.ld), active flag byte +7 bit 0x80 — located live, not
-- derived from the struct's bitfield packing. Source: patch/src/handlers.c:244-247,
-- patch/src/ADDRESSES.md:220. Same address on vanilla and RR (CFRU preserves this BPRE.ld global).
local PALETTE_FADE_ACTIVE_ADDR = 0x02037ABF
local PALETTE_FADE_ACTIVE_BIT  = 0x80

-- sScriptContext2Enabled — given by the card, matches lua/clients/gen3_frlge_client.lua:134.
local SCRIPT_CTX2_ADDR = 0x03000F9C

-- gTasks[] census: struct Task (pret/pokefirered include/task.h, cited verbatim at
-- lua/tests/test_post_eob_settle_discovery.lua:49-55): +0x00 TaskFunc func (u32, thumb-bit set),
-- +0x04 bool8 isActive, +0x05 prev, +0x06 next, +0x07 priority. 16 slots (same range as
-- lua/memory_gba.lua isPostBattleSettled's gTasks scan).
local TASKS_BASE = P.TASKS_BASE_ADDR
local TASK_SIZE  = P.TASK_STRUCT_SIZE or 40
local NUM_TASKS  = 16
if not TASKS_BASE then log("[probe] finding: profile has no TASKS_BASE_ADDR — task census skipped") end

local mem_u8, mem_u16, mem_u32 = memory.read_u8, memory.read_u16_le, memory.read_u32_le

local function task_set()
    if not TASKS_BASE then return "" end
    local active = {}
    for i = 0, NUM_TASKS - 1 do
        local base = TASKS_BASE + i * TASK_SIZE
        local ok, fn, act = pcall(function()
            return mem_u32(base), mem_u8(base + 0x04)
        end)
        if ok and act ~= 0 and fn ~= 0 then active[#active + 1] = string.format("%08X", fn) end
    end
    table.sort(active)
    return table.concat(active, ",")
end

-- ── aggregation state ─────────────────────────────────────────────────────────
local frame, bios_seen = 0, false
local labels = {}  -- [label] = {count=n, r15={}, cpsr={}, tasks={}}
local function bucket(label)
    labels[label] = labels[label] or {count = 0, r15 = {}, cpsr = {}, tasks = {}}
    return labels[label]
end

local function topN(counts, n)
    local arr = {}
    for k, c in pairs(counts) do arr[#arr + 1] = {k = k, c = c} end
    table.sort(arr, function(a, b) return a.c > b.c end)
    local out = {}
    for i = 1, math.min(n, #arr) do out[i] = arr[i] end
    return out, #arr
end

local function print_summary(tag)
    log(string.format("---- [probe] %s at frame %d (bios_seen=%s) ----", tag, frame, tostring(bios_seen)))
    for label, agg in pairs(labels) do
        log(string.format("  %s: %d frames", label, agg.count))
        local r15top = topN(agg.r15, 10)
        for _, e in ipairs(r15top) do log(string.format("    R15=0x%08X x%d", tonumber(e.k, 16) or 0, e.c)) end
        local cpsrtop = topN(agg.cpsr, 10)
        for _, e in ipairs(cpsrtop) do log(string.format("    CPSR mode/T=%s x%d", e.k, e.c)) end
        local tasktop, ntasksets = topN(agg.tasks, 10)
        for _, e in ipairs(tasktop) do
            log(string.format("    tasks={%s} x%d", e.k == "" and "none" or e.k, e.c))
        end
        log(string.format("    (%d distinct task-function sets total)", ntasksets))
    end
end

-- ── frame-end sample ──────────────────────────────────────────────────────────
event.onframeend(function()
    frame = frame + 1
    local ok, regs = pcall(emu.getregisters)
    if not ok or not regs then return end
    local pc   = regs.R15 or regs.PC or regs.pc
    local cpsr = regs.CPSR or regs.cpsr
    local sp   = regs.R13 or regs.SP or regs.sp
    if pc == nil then return end
    if frame == 1 then
        local names = {}
        for k in pairs(regs) do names[#names + 1] = k end
        table.sort(names)
        log("[probe] emu.getregisters() keys: " .. table.concat(names, ","))
    end
    if pc >= 0x00000000 and pc <= 0x00003FFF then bios_seen = true end

    local mode = cpsr and (cpsr & 0x1F) or -1
    local tbit = cpsr and ((cpsr >> 5) & 1) or -1

    local ok2, inBattle, paletteActive, scriptRunning = pcall(function()
        return M.isInBattle and M.isInBattle() or false,
               (mem_u8(PALETTE_FADE_ACTIVE_ADDR) & PALETTE_FADE_ACTIVE_BIT) ~= 0,
               mem_u8(SCRIPT_CTX2_ADDR) ~= 0
    end)
    local label
    if not ok2 then
        label = "unknown"
    elseif inBattle then
        label = "in-battle"
    elseif paletteActive then
        label = "fade"
    elseif scriptRunning then
        label = "script-running"
    else
        label = "overworld-idle"
    end

    local agg = bucket(label)
    agg.count = agg.count + 1
    local r15k = string.format("%08X", pc)
    agg.r15[r15k] = (agg.r15[r15k] or 0) + 1
    local cpsrk = mode .. "/" .. tbit
    agg.cpsr[cpsrk] = (agg.cpsr[cpsrk] or 0) + 1
    local tk = task_set()
    agg.tasks[tk] = (agg.tasks[tk] or 0) + 1
    -- sp read/kept for parity with the card's ask; not aggregated separately (SP alone doesn't
    -- add a bucketing dimension beyond R15/CPSR for this census).
    local _ = sp

    if frame == 600 then print_summary("interim") end
    if frame >= 1800 then
        print_summary("final")
        local total = 0
        for _, agg2 in pairs(labels) do total = total + agg2.count end
        if total >= 600 and labels["overworld-idle"] and labels["overworld-idle"].count > 0 then
            finish(true)
        else
            finish(false, string.format("total=%d overworld-idle=%s", total,
                tostring(labels["overworld-idle"] and labels["overworld-idle"].count or 0)))
        end
    end
end)

log("[probe] armed — sampling frame-end CPU/state census for 1800 frames")
