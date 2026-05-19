--[[
  lua/tests/test_se_audit.lua — Find the "shiny sparkle" slot on a modded ROM.
  ===========================================================================
  Built for Radical Red, but works on any FRLG variant. Four modes are
  always live so you can mix them:

    1. CAPTURE          — passive. Every frame we poll SE1/SE2/SE3 and BGM.
                          When a song-header pointer changes, we log the slot
                          id and the header address. Trigger a real shiny
                          encounter in-game and read the slot off the console.

    2. FORCE-SHINY      — toggled. Rewrites enemy[].PID = OT_ID at the moment
                          an encounter is generated, which makes the game's
                          shiny check (PID_hi ^ PID_lo ^ OT_hi ^ OT_lo == 0)
                          pass. Walk into grass → encounter → sparkle plays
                          naturally → CAPTURE logs the slot.
                            Y = toggle force-shiny mode

                          WARNING: this mutates the wild mon's PID in RAM.
                          Don't catch the mon and save — soft-reset after
                          you've captured the slot id.

    3. STEP-THROUGH     — manual. Walk all slots and audition them.
                            J = prev slot         L = next slot
                            I = jump -10          O = jump +10
                            U = jump -50          P = jump +50
                            K = play current slot

    4. AUTO-WALK        — plays slots in sequence from the current cursor,
                          one every ~2 s, logging each. Skips empty (MUS_DUMMY)
                          slots. Stops after a full lap or on toggle.
                            W = toggle auto-walk
                            [ = walk faster   ] = walk slower

    5. CANDIDATES       — F1..F12 jump straight to specific high-likelihood
                          slots and play them.

  HOW TO USE (recommended fast path):
    1. Load RR in BizHawk; let the save load with BGM audible.
    2. Stand in tall grass (or a fishing spot).
    3. Load this script in the Lua Console.
    4. Press Y to arm force-shiny.
    5. Take one step → wild encounter → sparkle. Watch the console for the
       [CAPTURE] line. That slot id is your SE_SHINY for RR.
    6. Soft-reset (don't save with the modified mon).
--]]

local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
package.path = _src .. "../?.lua;" .. package.path
package.loaded["memory_gba"] = nil
local M = require("memory_gba")
M.initProfile()

-- ── F-key candidates (still useful for quick reference). ────────────────────
local CANDIDATES = {
    { key = "F1",  id = 21,  name = "SE_PIN"          },
    { key = "F2",  id = 25,  name = "SE_SUCCESS"      },
    { key = "F3",  id = 27,  name = "SE_EXP"          },
    { key = "F4",  id = 66,  name = "SE_DING_DONG"    },
    { key = "F5",  id = 84,  name = "SE_EXP_MAX"      },
    { key = "F6",  id = 95,  name = "SE_SHINY"        },
    { key = "F7",  id = 96,  name = "SE_INTRO_BLAST"  },
    { key = "F8",  id = 97,  name = "SE_MUGSHOT"      },
    { key = "F9",  id = 98,  name = "SE_APPLAUSE"     },
    { key = "F10", id = 100, name = "SE_ORB"          },
    { key = "F11", id = 106, name = "SE_EGG_HATCH"    },
    { key = "F12", id = 110, name = "SE_GLASS_FLUTE"  },
}

-- ── gSongTable discovery (MUS_DUMMY-aware). ──────────────────────────────────
local SOUND_INFO_PTR_ADDR = 0x3007FF0
local O_SNDINFO_HEAD = 0x24
local O_MPL_SONG_HDR = 0x00
local O_MPL_NEXT     = 0x3C
local SONG_ENTRY     = 8

local function hex(n) return string.format("0x%08X", n) end

local function walkPlayers()
    local gs = memory.read_u32_le(SOUND_INFO_PTR_ADDR)
    if gs < 0x03000000 or gs >= 0x03008000 then return nil end
    local list, cur = {}, memory.read_u32_le(gs + O_SNDINFO_HEAD)
    while cur ~= 0 and #list < 16 do
        if cur < 0x03000000 or cur >= 0x03008000 then break end
        list[#list + 1] = cur
        cur = memory.read_u32_le(cur + O_MPL_NEXT)
    end
    return list
end

local function detectRomEnd()
    local probe16 = memory.read_u32_le(0x09000000 - 4)
    if probe16 ~= 0 and probe16 ~= 0xFFFFFFFF then
        local probe32 = memory.read_u32_le(0x0A000000 - 4)
        if probe32 ~= 0 and probe32 ~= 0xFFFFFFFF then return 0x0A000000 end
        return 0x09000000
    end
    return 0x09000000
end

local function headerLooksValid(hdr)
    if hdr < 0x08000000 or hdr >= 0x0A000000 then return false end
    local tc = memory.read_u8(hdr)
    local voice = memory.read_u32_le(hdr + 8)
    return tc >= 1 and tc <= 16
        and voice >= 0x08000000 and voice < 0x0A000000
end

local function findTableViaActiveBGM(players, ROM_END)
    local known = {}
    for _, addr in ipairs(players) do
        local hdr = memory.read_u32_le(addr + O_MPL_SONG_HDR)
        if hdr >= 0x08000000 and hdr < 0x0A000000 then
            known[#known + 1] = hdr
        end
    end
    if #known == 0 then return nil end
    console.log(("  Strategy A: anchoring on %d active songHeader(s)"):format(#known))
    for _, target in ipairs(known) do
        local last_mb = -1
        for addr = 0x08000000, ROM_END - 4, 4 do
            local cur_mb = math.floor((addr - 0x08000000) / (1024*1024))
            if cur_mb > last_mb then
                last_mb = cur_mb
                if cur_mb % 4 == 0 then emu.yield() end
            end
            if memory.read_u32_le(addr) == target then
                local ms = memory.read_u16_le(addr + 4)
                if ms <= 4 and headerLooksValid(target) then
                    local start = addr
                    while start > 0x08000000 do
                        local p = memory.read_u32_le(start - SONG_ENTRY)
                        local m = memory.read_u16_le(start - SONG_ENTRY + 4)
                        local e = memory.read_u16_le(start - SONG_ENTRY + 6)
                        if (p == 0 and m == 0 and e == 0)
                            or (m <= 4 and headerLooksValid(p)) then
                            start = start - SONG_ENTRY
                        else
                            break
                        end
                    end
                    local count, check = 0, start
                    while check < ROM_END do
                        local p = memory.read_u32_le(check)
                        local m = memory.read_u16_le(check + 4)
                        local e = memory.read_u16_le(check + 6)
                        if (p == 0 and m == 0 and e == 0)
                            or (m <= 4 and p >= 0x08000000 and p < 0x0A000000) then
                            count = count + 1
                            check = check + SONG_ENTRY
                        else
                            break
                        end
                    end
                    if count >= 100 then return start, count end
                end
            end
        end
    end
    return nil
end

console.clear()
console.log("=== SLink SE Audition / Capture ===")
local players = walkPlayers()
if not players then
    console.log("ERROR: couldn't read music player list. Load a save first.")
    return
end
local ROM_END = detectRomEnd()
console.log(("  %d music players found; scanning %.0fMB..."):format(
    #players, (ROM_END - 0x08000000) / (1024*1024)))
local table_addr, entries = findTableViaActiveBGM(players, ROM_END)
if not table_addr then
    console.log("ERROR: gSongTable not located. Make sure BGM is playing.")
    return
end
console.log(("  gSongTable @ %s  (%d entries)"):format(hex(table_addr), entries))

-- ── Pre-cache every slot's header addr; build hdr→slot reverse map. ──────────
local SLOTS  = {}                -- slot id → hdr addr (or 0 for MUS_DUMMY)
local REV    = {}                -- hdr addr → slot id
for i = 0, entries - 1 do
    local hdr = memory.read_u32_le(table_addr + i * SONG_ENTRY)
    SLOTS[i] = hdr
    if hdr ~= 0 and not REV[hdr] then
        REV[hdr] = i
    end
end

-- Wire the F-key candidates into M.SE_SONG_HEADERS so playSE() can dispatch.
console.log("")
console.log("Quick-play candidates (jump to slot + play):")
for _, c in ipairs(CANDIDATES) do
    local hdr = SLOTS[c.id]
    if hdr then
        M.SE_SONG_HEADERS[c.id] = hdr
        console.log(("  %-3s →  slot %3d  hdr=%s  %s"):format(
            c.key, c.id, hex(hdr), c.name))
    end
end

-- ── Locate SE players for passive capture. ──────────────────────────────────
-- The MPlay linked list orders nodes as: head ... SE3 SE2 SE1 BGM (tail).
local function se_nodes()
    local list = walkPlayers()
    if not list or #list < 2 then return nil end
    local out = {}                            -- name → addr
    out.BGM = list[#list]
    if #list >= 2 then out.SE1 = list[#list - 1] end
    if #list >= 3 then out.SE2 = list[#list - 2] end
    if #list >= 4 then out.SE3 = list[#list - 3] end
    return out
end
local SE = se_nodes() or {}
console.log("")
console.log("Capture channels:")
for _, name in ipairs({"BGM", "SE1", "SE2", "SE3"}) do
    if SE[name] then
        console.log(("  %s player @ %s"):format(name, hex(SE[name])))
    end
end

-- ── Step-through cursor. ────────────────────────────────────────────────────
local cursor = 0
local function move(delta)
    cursor = ((cursor + delta) % entries + entries) % entries
    local hdr = SLOTS[cursor]
    console.log(("[STEP]   cursor → slot %3d  hdr=%s"):format(cursor, hex(hdr or 0)))
end
local function play_cursor()
    local hdr = SLOTS[cursor]
    if not hdr or hdr == 0 then
        console.log(("[STEP] ✗ slot %d has no header (MUS_DUMMY?)"):format(cursor))
        return
    end
    M.SE_SONG_HEADERS[cursor] = hdr
    local ok = M.playSE(cursor)
    console.log(("[STEP] ▶ slot %3d  hdr=%s  (%s)"):format(
        cursor, hex(hdr), ok and "OK" or "FAIL"))
end

console.log("")
console.log("Step keys: J/L = ±1   I/O = ±10   U/P = ±50   K = play current")
console.log("Auto-walk: W = toggle   [ = faster   ] = slower")
console.log("Force-shiny toggle: Y   (writes PID=OT_ID to enemy mons; soft-reset after)")
console.log("")
console.log("--- LIVE. Trigger a shiny in-game and watch the [CAPTURE] line. ---")

-- ── Auto-walk: step the cursor through every slot and play each. ────────────
local walk_on        = false
local walk_interval  = 120   -- frames between plays (~2s @ 60fps)
local walk_min       = 30    -- 0.5s lower bound
local walk_max       = 360   -- 6s upper bound
local walk_step_delta = 30   -- ± per [ / ] press
local walk_timer     = 0
local walk_started_at = nil  -- cursor where walk started; used to detect full lap

local function walk_tick()
    if not walk_on then return end
    walk_timer = walk_timer - 1
    if walk_timer > 0 then return end
    walk_timer = walk_interval

    -- Advance past MUS_DUMMY / empty slots without burning a play interval.
    local hops = 0
    repeat
        cursor = (cursor + 1) % entries
        hops = hops + 1
        if walk_started_at and cursor == walk_started_at then
            walk_on = false
            console.log("[WALK] full lap complete — stopped")
            return
        end
    until SLOTS[cursor] ~= 0 or hops > entries

    if SLOTS[cursor] == 0 then return end
    M.SE_SONG_HEADERS[cursor] = SLOTS[cursor]
    local ok = M.playSE(cursor)
    console.log(("[WALK] ▶ slot %3d  hdr=%s  (%s)"):format(
        cursor, hex(SLOTS[cursor]), ok and "OK" or "FAIL"))
end

-- ── Force-shiny rewriter. ───────────────────────────────────────────────────
-- Gen 3 shiny check: shiny if (PID_hi ^ PID_lo ^ OT_hi ^ OT_lo) < SHINY_ODDS
-- (CFRU's default SHINY_ODDS = 16). Setting PID := OT_ID gives XOR = 0 →
-- guaranteed shiny.
--
-- We rewrite in BOTH locations:
--   • gEnemyParty[slot]  — persistent struct (this is what catch logic reads)
--   • gBattleMons[1/3]   — in-battle copy that the intro animation script's
--                          `shinytarget` opcode actually reads. Without this,
--                          the rewrite is too late: gEnemyParty → gBattleMons
--                          copy already happened during battle init.
-- RR/CFRU stores substructs unencrypted in fixed order (CFRU_NO_ENCRYPT),
-- so rewriting the PID is safe for the duration of the test.
local force_shiny_on = false
local logged_pids = {}  -- "loc:slot" → last PID we wrote (suppress log spam)

local function force_shiny_pass()
    if not force_shiny_on then return end

    -- Pass 1: gEnemyParty.
    if M.ENEMY_COUNT_ADDR and M.ENEMY_BASE then
        local count = memory.read_u8(M.ENEMY_COUNT_ADDR)
        if count > 0 and count <= 6 then
            for slot = 0, count - 1 do
                local base = M.ENEMY_BASE + slot * M.MON_SIZE
                local pid = memory.read_u32_le(base + M.OFF_PERSONALITY)
                if pid ~= 0 then
                    local otid = memory.read_u32_le(base + M.OFF_OTID)
                    if pid ~= otid then
                        memory.write_u32_le(base + M.OFF_PERSONALITY, otid)
                        local k = "eparty:"..slot
                        if logged_pids[k] ~= otid then
                            console.log(("[SHINY] gEnemyParty[%d]  OT=%s  PID %s → %s"):format(
                                slot, hex(otid), hex(pid), hex(otid)))
                            logged_pids[k] = otid
                        end
                    end
                end
            end
        end
    end

    -- Pass 2: gBattleMons (foe battlers 1 and 3 in singles/doubles).
    if M.BATTLE_MONS_ADDR and M.BATTLE_MONS_ADDR ~= 0
        and M.BATTLE_MON_PERS_OFF and M.BATTLE_MON_OTID_OFF then
        for _, battler in ipairs({1, 3}) do
            local base = M.BATTLE_MONS_ADDR + battler * M.BATTLE_MON_SIZE
            local pid = memory.read_u32_le(base + M.BATTLE_MON_PERS_OFF)
            if pid ~= 0 then
                local otid = memory.read_u32_le(base + M.BATTLE_MON_OTID_OFF)
                if pid ~= otid then
                    memory.write_u32_le(base + M.BATTLE_MON_PERS_OFF, otid)
                    local k = "bmon:"..battler
                    if logged_pids[k] ~= otid then
                        console.log(("[SHINY] gBattleMons[%d] OT=%s  PID %s → %s"):format(
                            battler, hex(otid), hex(pid), hex(otid)))
                        logged_pids[k] = otid
                    end
                end
            end
        end
    end
end

-- ── Main frame loop: F-keys, step keys, and passive capture. ────────────────
local prev_key = {}
local prev_hdr = { BGM = nil, SE1 = nil, SE2 = nil, SE3 = nil }

event.onframeend(function()
    local inp = input.get()

    -- F-key candidates: play (and set the cursor to that slot for context).
    for _, c in ipairs(CANDIDATES) do
        if inp[c.key] and not prev_key[c.key] then
            cursor = c.id
            local ok = M.playSE(c.id)
            console.log(("[CAND] ▶ %-3s slot %3d  hdr=%s  %s  (%s)"):format(
                c.key, c.id, hex(SLOTS[c.id] or 0), c.name,
                ok and "OK" or "FAIL"))
        end
    end

    -- Step controls.
    if inp.J and not prev_key.J then move(-1)   end
    if inp.L and not prev_key.L then move( 1)   end
    if inp.I and not prev_key.I then move(-10)  end
    if inp.O and not prev_key.O then move( 10)  end
    if inp.U and not prev_key.U then move(-50)  end
    if inp.P and not prev_key.P then move( 50)  end
    if inp.K and not prev_key.K then play_cursor() end

    -- Force-shiny toggle.
    if inp.Y and not prev_key.Y then
        force_shiny_on = not force_shiny_on
        logged_pids = {}
        console.log(("[SHINY] force-shiny mode: %s"):format(
            force_shiny_on and "ON (walk into grass to capture)" or "OFF"))
    end

    -- Auto-walk controls.
    if inp.W and not prev_key.W then
        walk_on = not walk_on
        if walk_on then
            walk_started_at = cursor
            walk_timer = 0   -- play immediately on toggle
            console.log(("[WALK] auto-walk ON  (start=%d  interval=%df  %d slots to lap)"):format(
                cursor, walk_interval, entries))
        else
            walk_started_at = nil
            console.log("[WALK] auto-walk OFF")
        end
    end
    if inp["["] and not prev_key["["] then
        walk_interval = math.max(walk_min, walk_interval - walk_step_delta)
        console.log(("[WALK] interval = %df (%.1fs)"):format(walk_interval, walk_interval/60))
    end
    if inp["]"] and not prev_key["]"] then
        walk_interval = math.min(walk_max, walk_interval + walk_step_delta)
        console.log(("[WALK] interval = %df (%.1fs)"):format(walk_interval, walk_interval/60))
    end

    prev_key = inp

    -- Auto-walk tick.
    walk_tick()

    -- Force-shiny rewriter (no-op when off; cheap when on).
    force_shiny_pass()

    -- Passive capture: any time a tracked channel's song-header changes,
    -- log the slot. This is the path that catches a real shiny encounter.
    for _, name in ipairs({"SE1", "SE2", "SE3", "BGM"}) do
        local addr = SE[name]
        if addr then
            local hdr = memory.read_u32_le(addr + O_MPL_SONG_HDR)
            if hdr ~= prev_hdr[name] and hdr ~= 0 then
                local slot = REV[hdr]
                console.log(("[CAPTURE] %s → slot %s  hdr=%s"):format(
                    name, slot and tostring(slot) or "?", hex(hdr)))
                prev_hdr[name] = hdr
            end
        end
    end
end, "se_audit")
