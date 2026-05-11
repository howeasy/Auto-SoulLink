--[[
  lua/test_sound_discovery.lua — Automatic SE SongHeader Address Discovery
  ========================================================================
  Finds gSongTable by two complementary strategies:
    A) Read an active player's songHeader (ROM ptr) and scan ROM for it
    B) Scan ROM for a long run of valid song entries ({ROM_ptr, u16, u16} x 100+)
  Then reads the SongHeader for each target SE directly by index.

  Supports vanilla (16MB), AP, and Radical Red / CFRU hacks (up to 32MB).
  Scans the full ROM address range — may take a few minutes on 32MB ROMs.

  HOW TO USE:
    1. Load FireRed/LeafGreen (vanilla, AP, or RR) in BizHawk, load a save
       (BGM must be playing).
    2. Load this script in the Lua Console.
    3. Results print automatically. Copy the SE_SONG_HEADERS block into memory.lua.
--]]

local SOUND_INFO_PTR_ADDR = 0x3007FF0
local O_SNDINFO_HEAD = 0x24
local O_MPL_SONG_HDR = 0x00
local O_MPL_STATUS   = 0x04
local O_MPL_IDENT    = 0x34
local O_MPL_NEXT     = 0x3C
local ID_NUMBER      = 0x68736D53

local SONG_ENTRY_SIZE = 8  -- {u32 header, u16 ms, u16 me}

local TARGET_SES = {
    { id = 16, name = "SE_FAINT",   desc = "mon faints" },
    { id = 17, name = "SE_FLEE",    desc = "wild flees" },
    { id = 22, name = "SE_BOO",     desc = "ball breaks open" },
    { id = 25, name = "SE_SUCCESS", desc = "ball catches" },
    { id = 26, name = "SE_FAILURE", desc = "action fails" },
    { id = 95, name = "SE_SHINY",   desc = "shiny sparkle" },
}

local function hex(n) return string.format("0x%08X", n) end
local function printDiv() print("==================================================================") end
local function printLine() print("------------------------------------------------------------------") end

-- Detect actual ROM size by probing for 0xFF padding from the end.
-- GBA ROM space is 0x08000000–0x0A000000 (32MB max).
local function detectRomEnd()
    local MAX_ROM = 0x0A000000
    -- Check common ROM sizes: 32MB, 16MB, 8MB
    local sizes = { 0x02000000, 0x01000000, 0x00800000 }
    for _, sz in ipairs(sizes) do
        local probe = 0x08000000 + sz - 4
        if probe < MAX_ROM then
            local v = memory.read_u32_le(probe)
            if v ~= 0x00000000 and v ~= 0xFFFFFFFF then
                -- Data present at this offset — ROM is at least this big.
                -- For 32MB, return MAX_ROM; otherwise check the next tier up.
                if sz == 0x02000000 then return MAX_ROM end
                -- Check halfway between this size and the next
                local next_sz = sz * 2
                local mid = 0x08000000 + sz + (next_sz - sz) / 2
                local mv = memory.read_u32_le(mid)
                if mv ~= 0x00000000 and mv ~= 0xFFFFFFFF then
                    return 0x08000000 + next_sz
                end
                return 0x08000000 + sz
            end
        end
    end
    -- Fallback: assume 16MB (vanilla)
    return 0x09000000
end

-- Walk MusicPlayerInfo linked list
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

-- Strategy A: Read active songHeaders from players, scan ROM for the pointer,
-- then walk backwards to find the table start.
local function findSongTableViaActiveHeaders(players, ROM_END)
    local known_hdrs = {}
    for _, addr in ipairs(players) do
        local hdr = memory.read_u32_le(addr + O_MPL_SONG_HDR)
        local st  = memory.read_u32_le(addr + O_MPL_STATUS)
        if hdr >= 0x08000000 and hdr < 0x0A000000 and (st & 0xFFFF) ~= 0 then
            known_hdrs[#known_hdrs + 1] = hdr
        end
    end
    if #known_hdrs == 0 then return nil end

    local ROM_START = 0x08000000
    local rom_mb = (ROM_END - ROM_START) / (1024*1024)
    print(string.format("  Strategy A: %d active songHeader(s), scanning %.0fMB ROM...",
        #known_hdrs, rom_mb))

    for _, target in ipairs(known_hdrs) do
        print(string.format("  Scanning for %s...", hex(target)))
        local last_mb = -1
        for addr = ROM_START, ROM_END - 4, 4 do
            -- Progress reporting + yield every 1MB
            local cur_mb = math.floor((addr - ROM_START) / (1024*1024))
            if cur_mb > last_mb then
                last_mb = cur_mb
                if cur_mb % 4 == 0 then
                    console.log(string.format("  Strategy A: %dMB / %.0fMB scanned...", cur_mb, rom_mb))
                end
                emu.yield()
            end

            if memory.read_u32_le(addr) == target then
                local ms = memory.read_u16_le(addr + 4)
                if ms < 16 then
                    -- Walk backwards to find table start
                    local start = addr
                    while start > ROM_START do
                        local ph = memory.read_u32_le(start - SONG_ENTRY_SIZE)
                        local pm = memory.read_u16_le(start - SONG_ENTRY_SIZE + 4)
                        if ph >= 0x08000000 and ph < 0x0A000000 and pm < 16 then
                            start = start - SONG_ENTRY_SIZE
                        else
                            break
                        end
                    end
                    -- Count forward
                    local count, check = 0, start
                    while check < ROM_END do
                        local h = memory.read_u32_le(check)
                        local m = memory.read_u16_le(check + 4)
                        if h >= 0x08000000 and h < 0x0A000000 and m < 16 then
                            count = count + 1
                            check = check + SONG_ENTRY_SIZE
                        else
                            break
                        end
                    end
                    if count >= 50 then
                        local idx = (addr - start) / SONG_ENTRY_SIZE
                        print(string.format("  FOUND: table at %s, %d entries (target was index %d)",
                            hex(start), count, idx))
                        return start, count
                    end
                end
            end
        end
        print("  (no valid table hit for this header)")
    end
    return nil
end

-- Strategy B: Find longest run of {ROM_ptr, small_u16, small_u16} at 8-byte intervals.
local function findSongTableViaStructure(ROM_END)
    local ROM_START = 0x08000000
    local rom_mb = (ROM_END - ROM_START) / (1024*1024)
    print(string.format("  Strategy B: Scanning %.0fMB ROM for song entry runs...", rom_mb))
    local best_addr, best_run = nil, 0

    local addr = ROM_START
    local last_mb = -1
    while addr < ROM_END - 400 do
        -- Progress + yield
        local cur_mb = math.floor((addr - ROM_START) / (1024*1024))
        if cur_mb > last_mb then
            last_mb = cur_mb
            if cur_mb % 4 == 0 then
                console.log(string.format("  Strategy B: %dMB / %.0fMB scanned (best=%d)...",
                    cur_mb, rom_mb, best_run))
            end
            emu.yield()
        end

        local hdr = memory.read_u32_le(addr)
        if hdr >= 0x08000000 and hdr < 0x0A000000 then
            local ms = memory.read_u16_le(addr + 4)
            if ms < 16 then
                local run, check = 0, addr
                while check < ROM_END do
                    local h = memory.read_u32_le(check)
                    local m = memory.read_u16_le(check + 4)
                    if h >= 0x08000000 and h < 0x0A000000 and m < 16 then
                        run = run + 1
                        check = check + SONG_ENTRY_SIZE
                    else
                        break
                    end
                end
                if run > best_run then
                    best_run = run
                    best_addr = addr
                    if run >= 100 then
                        print(string.format("  FOUND: %d consecutive entries at %s (early exit)",
                            run, hex(addr)))
                        return best_addr, best_run
                    end
                end
                addr = check + 8
            else
                addr = addr + 4
            end
        else
            addr = addr + 4
        end
    end
    if best_run >= 50 then
        print(string.format("  FOUND: %d consecutive entries at %s", best_run, hex(best_addr)))
        return best_addr, best_run
    end
    return nil
end

-- ── Main ──────────────────────────────────────────────────────────────────────
printDiv()
print("  SLINK SOUND DISCOVERY — Automatic gSongTable Scanner")
print("  Supports vanilla (16MB), AP, and Radical Red / CFRU (32MB)")
printDiv()

local ROM_END = detectRomEnd()
local rom_mb = (ROM_END - 0x08000000) / (1024*1024)
print(string.format("[STEP 0] ROM size detected: %.0fMB (end = %s)", rom_mb, hex(ROM_END)))

local players = walkPlayers()
if not players then
    print("  ERROR: Could not walk player list. Load a save first.")
    return
end
print(string.format("[STEP 1] %d music players found", #players))

-- Reverse to gMPlayTable order
local mplay = {}
for i = #players, 1, -1 do mplay[#mplay + 1] = players[i] end
local names = {"BGM","SE1","SE2","SE3"}
for i, a in ipairs(mplay) do
    print(string.format("  [%d] %s  (%s)", i-1, hex(a), names[i] or ("P"..(i-1))))
end

printLine()
print("[STEP 2] Finding gSongTable...")
local song_table, entry_count = findSongTableViaActiveHeaders(players, ROM_END)
if not song_table then
    print("  Strategy A failed, trying B...")
    song_table, entry_count = findSongTableViaStructure(ROM_END)
end
if not song_table then
    print("  ERROR: Could not find gSongTable!")
    return
end
print(string.format("  gSongTable = %s  (%d entries)", hex(song_table), entry_count))

printLine()
print("[STEP 3] Target SE SongHeaders:")
local results = {}
for _, se in ipairs(TARGET_SES) do
    if se.id < entry_count then
        local entry = song_table + se.id * SONG_ENTRY_SIZE
        local hdr = memory.read_u32_le(entry)
        local ms  = memory.read_u16_le(entry + 4)
        local tc  = memory.read_u8(hdr)
        local pri = memory.read_u8(hdr + 2)
        print(string.format("  [%3d] %-12s hdr=%s  ms=%d  tracks=%d  pri=%d",
            se.id, se.name, hex(hdr), ms, tc, pri))
        results[#results + 1] = { id = se.id, name = se.name, hdr = hdr }
    else
        print(string.format("  [%3d] %-12s OUT OF RANGE", se.id, se.name))
    end
end

printDiv()
print("")
print("  -- Copy into lua/memory_gba.lua PROFILES.radical_red (or appropriate profile):")
print(string.format("  -- gSongTable = %s  (%d entries)", hex(song_table), entry_count))
print("  SE_SONG_HEADERS = {")
for _, r in ipairs(results) do
    print(string.format("      [%3d] = %s,  -- %s", r.id, hex(r.hdr), r.name))
end
print("  }")
print("")
if mplay[2] then
    print(string.format("  SE1 player IWRAM addr = %s", hex(mplay[2])))
end
printDiv()
print("  Done!")
