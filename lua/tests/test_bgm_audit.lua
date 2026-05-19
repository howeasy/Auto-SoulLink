--[[
  lua/tests/test_bgm_audit.lua — Audition BGM tracks on RR (or vanilla FRLG).
  ==========================================================================
  Sibling of test_se_audit.lua. Same gSongTable discovery, but plays through
  the BGM music player (first node in gMPlayTable, last node in the walked
  linked list) so full-length tracks come out correctly instead of being
  truncated by the SE1 channel.

  Modes (all live simultaneously):

    1. CAPTURE          — passive. Logs whenever BGM's song-header pointer
                          changes (i.e. the game starts a new track).

    2. STEP-THROUGH     — manual cursor.
                            J = prev slot      L = next slot
                            I = jump -10       O = jump +10
                            U = jump -50       P = jump +50
                            K = play current   X = stop / silence

    3. AUTO-WALK        — auto-plays slots in sequence; default 5 s per slot
                          (long enough to recognize a song intro). Skips
                          empty slots and BANKs out after one full lap.
                            W = toggle   [ = faster   ] = slower

    4. JUMP-TO          — type a slot id, then press G. Useful when you know
                          a rough range (e.g. BGM tends to live ≥ 350 in
                          pokefirered, but RR/CFRU shifts it; auto-walk a
                          little first to spot the boundary).
                            0..9 = build pending id
                            G    = goto pending id
                            ESC* = clear pending id  (use Backspace in BizHawk)

  HOW TO USE:
    1. Load the ROM in BizHawk; let the save load with BGM playing.
    2. Open this script in the Lua Console.
    3. CAPTURE the slot the game's currently playing — that's a known anchor.
       From there, J/L explore neighbours; W auto-walks for a wider scan.
    4. When you hear what you want, note the slot id from the most recent
       [WALK]/[STEP]/[CAPTURE] log line. Tell SLink and we can add the
       address to a new BGM_SONG_HEADERS table or pin a constant.
--]]

local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
package.path = _src .. "../?.lua;" .. package.path
package.loaded["memory_gba"] = nil
local M = require("memory_gba")
M.initProfile()

-- ── gSongTable discovery (copied from test_se_audit, MUS_DUMMY-aware). ──────
local SOUND_INFO_PTR_ADDR = 0x3007FF0
local O_SNDINFO_HEAD = 0x24
local O_MPL_SONG_HDR   = 0x00
local O_MPL_STATUS     = 0x04
local O_MPL_TRACKCOUNT = 0x08
local O_MPL_PRIORITY   = 0x09
local O_MPL_CLOCK      = 0x0C
local O_MPL_TRACKS_PTR = 0x2C
local O_MPL_IDENT      = 0x34
local O_MPL_NEXT       = 0x3C
local O_TRK_FLAGS      = 0x00
local O_TRK_BEND       = 0x0F
local O_TRK_VOLX       = 0x13
local O_TRK_LFO        = 0x19
local O_TRK_CHAN       = 0x20
local O_TRK_CMDPTR     = 0x40
local TRK_START        = 0xC0
local ID_NUMBER        = 0x68736D53
local SONG_ENTRY       = 8

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

-- ── Player playback (mirrors M.playSE but for an arbitrary player addr). ────
-- The m4a engine treats all players the same way; only the SongHeader's
-- track_count and the player's capacity differ. BGM player has more tracks
-- so it can drive full music. We hand-write the same sequence M.playSE does.
local function play_on(player_addr, hdr)
    if not player_addr or not hdr or hdr == 0 then return false end
    local ok, err = pcall(function()
        if memory.read_u32_le(player_addr + O_MPL_IDENT) ~= ID_NUMBER then return end
        local track0 = memory.read_u32_le(player_addr + O_MPL_TRACKS_PTR)
        if track0 < 0x03000000 or track0 >= 0x03008000 then return end

        local track_count = memory.read_u8(hdr + 0x00)
        local priority    = memory.read_u8(hdr + 0x02)

        memory.write_u32_le(player_addr + O_MPL_IDENT, ID_NUMBER + 1)
        memory.write_u32_le(player_addr + O_MPL_SONG_HDR,   hdr)
        memory.write_u32_le(player_addr + O_MPL_STATUS,     (1 << track_count) - 1)
        memory.write_u8    (player_addr + O_MPL_TRACKCOUNT, track_count)
        memory.write_u8    (player_addr + O_MPL_PRIORITY,   priority)
        memory.write_u32_le(player_addr + O_MPL_CLOCK,      0)

        -- Initialize each track from the SongHeader's part[i] command pointer.
        -- BGM SongHeaders carry one cmd_ptr per track, packed after the 8-byte
        -- header (hdr+0x08 = part[0], hdr+0x0C = part[1], ...).
        for i = 0, track_count - 1 do
            local trk = track0 + i * 0x50
            local cmd_ptr = memory.read_u32_le(hdr + 0x08 + i * 4)
            memory.write_u32_le(trk + 0x00, 0)
            memory.write_u8    (trk + O_TRK_FLAGS, TRK_START)
            memory.write_u8    (trk + O_TRK_BEND,  2)
            memory.write_u8    (trk + O_TRK_VOLX,  64)
            memory.write_u8    (trk + O_TRK_LFO,   22)
            memory.write_u32_le(trk + O_TRK_CHAN,   0)
            memory.write_u32_le(trk + O_TRK_CMDPTR, cmd_ptr)
        end

        memory.write_u32_le(player_addr + O_MPL_IDENT, ID_NUMBER)
    end)
    if not ok then console.log("[BGM] play error: "..tostring(err)) end
    return ok
end

local function stop_player(player_addr)
    if not player_addr then return end
    -- Zero out track flags; engine will deselect all tracks.
    local track0 = memory.read_u32_le(player_addr + O_MPL_TRACKS_PTR)
    if track0 < 0x03000000 or track0 >= 0x03008000 then return end
    memory.write_u32_le(player_addr + O_MPL_IDENT, ID_NUMBER + 1)
    memory.write_u32_le(player_addr + O_MPL_STATUS, 0)
    for i = 0, 15 do
        memory.write_u8(track0 + i * 0x50 + O_TRK_FLAGS, 0)
    end
    memory.write_u32_le(player_addr + O_MPL_IDENT, ID_NUMBER)
end

-- ── Discovery + setup. ──────────────────────────────────────────────────────
console.clear()
console.log("=== SLink BGM Audition / Capture ===")
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

local SLOTS, REV = {}, {}
for i = 0, entries - 1 do
    local hdr = memory.read_u32_le(table_addr + i * SONG_ENTRY)
    SLOTS[i] = hdr
    if hdr ~= 0 and not REV[hdr] then REV[hdr] = i end
end

-- BGM player = first in gMPlayTable = last in the walked linked list (tail).
local BGM_PLAYER = players[#players]
console.log(("  BGM player @ %s"):format(hex(BGM_PLAYER)))

-- ── Cursor (start where the BGM is currently parked, so the user has an
--    anchor and J/L explore neighbours). ────────────────────────────────────
local cur_bgm_hdr = memory.read_u32_le(BGM_PLAYER + O_MPL_SONG_HDR)
local cursor = REV[cur_bgm_hdr] or 0
console.log(("  cursor → slot %d (current BGM)"):format(cursor))

local function move(delta)
    cursor = ((cursor + delta) % entries + entries) % entries
    console.log(("[STEP] cursor → slot %3d  hdr=%s"):format(cursor, hex(SLOTS[cursor] or 0)))
end
local function play_cursor()
    local hdr = SLOTS[cursor]
    if not hdr or hdr == 0 then
        console.log(("[STEP] ✗ slot %d has no header"):format(cursor))
        return
    end
    local ok = play_on(BGM_PLAYER, hdr)
    console.log(("[STEP] ▶ slot %3d  hdr=%s  (%s)"):format(
        cursor, hex(hdr), ok and "OK" or "FAIL"))
end

-- ── Auto-walk. ──────────────────────────────────────────────────────────────
local walk_on        = false
local walk_interval  = 300   -- 5s @ 60fps (BGM intros need room to breathe)
local walk_min       = 60    -- 1s
local walk_max       = 1200  -- 20s
local walk_step_delta = 60
local walk_timer     = 0
local walk_started_at = nil

local function walk_tick()
    if not walk_on then return end
    walk_timer = walk_timer - 1
    if walk_timer > 0 then return end
    walk_timer = walk_interval

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
    local ok = play_on(BGM_PLAYER, SLOTS[cursor])
    console.log(("[WALK] ▶ slot %3d  hdr=%s  (%s)"):format(
        cursor, hex(SLOTS[cursor]), ok and "OK" or "FAIL"))
end

-- ── Jump-to (numeric input + G). ────────────────────────────────────────────
local pending_id = nil
local function digit(d)
    pending_id = (pending_id or 0) * 10 + d
    if pending_id > entries * 10 then pending_id = d end
    console.log(("[JUMP] pending: %d"):format(pending_id))
end

console.log("")
console.log("Step keys: J/L = ±1   I/O = ±10   U/P = ±50   K = play   X = stop")
console.log("Auto-walk: W = toggle   [ = faster   ] = slower")
console.log("Jump-to:   0..9 build id   G = goto   Backspace = clear")
console.log("")
console.log("--- LIVE. CAPTURE will log when the game itself changes BGM. ---")

-- ── Main loop. ──────────────────────────────────────────────────────────────
local prev_key = {}
local prev_bgm_hdr = cur_bgm_hdr

event.onframeend(function()
    local inp = input.get()

    -- Step controls.
    if inp.J and not prev_key.J then move(-1)   end
    if inp.L and not prev_key.L then move( 1)   end
    if inp.I and not prev_key.I then move(-10)  end
    if inp.O and not prev_key.O then move( 10)  end
    if inp.U and not prev_key.U then move(-50)  end
    if inp.P and not prev_key.P then move( 50)  end
    if inp.K and not prev_key.K then play_cursor() end
    if inp.X and not prev_key.X then
        stop_player(BGM_PLAYER)
        console.log("[STEP] BGM silenced")
    end

    -- Auto-walk controls.
    if inp.W and not prev_key.W then
        walk_on = not walk_on
        if walk_on then
            walk_started_at = cursor
            walk_timer = 0
            console.log(("[WALK] ON  (start=%d  interval=%df ~%.1fs)"):format(
                cursor, walk_interval, walk_interval/60))
        else
            walk_started_at = nil
            console.log("[WALK] OFF")
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

    -- Jump-to controls.
    for d = 0, 9 do
        local k = "D"..d  -- BizHawk uses D0..D9 for top-row digits
        if inp[k] and not prev_key[k] then digit(d) end
    end
    if inp.Backspace and not prev_key.Backspace then
        pending_id = nil
        console.log("[JUMP] cleared")
    end
    if inp.G and not prev_key.G then
        if pending_id and pending_id < entries then
            cursor = pending_id
            console.log(("[JUMP] → slot %d  hdr=%s"):format(cursor, hex(SLOTS[cursor] or 0)))
            pending_id = nil
        else
            console.log(("[JUMP] invalid (need 0..%d)"):format(entries - 1))
        end
    end

    prev_key = inp

    -- Passive capture: log if BGM's song-header pointer changes.
    local cur_hdr = memory.read_u32_le(BGM_PLAYER + O_MPL_SONG_HDR)
    if cur_hdr ~= prev_bgm_hdr and cur_hdr ~= 0 then
        local slot = REV[cur_hdr]
        console.log(("[CAPTURE] BGM → slot %s  hdr=%s"):format(
            slot and tostring(slot) or "?", hex(cur_hdr)))
        prev_bgm_hdr = cur_hdr
    end

    walk_tick()
end, "bgm_audit")
