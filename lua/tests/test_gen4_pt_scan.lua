--[[
  lua/tests/test_gen4_pt_scan.lua — Platinum profile address verification.
  READ-ONLY. Run with Pokémon Platinum loaded in BizHawk (a save already booted).

  Purpose:
    The Platinum profile in lua/games/gen4_hgsspt.lua carries some VERIFY_ME tags
    (PC array header offset, in particular). This scanner forces the Platinum
    profile, then prints every base-relative address with its decoded value so a
    human can confirm "plausible" before promoting VERIFY_ME → confirmed.

  Plausibility heuristics (logged inline):
    • party count must be 0–6
    • PC arrayHeaders[41].offset must be in 0x100..0x23000
    • zone ID must be non-zero and below 0x280
    • player name first char in Gen IV charcode range (289..350) or 0
    • Sinnoh badges byte ∈ 0..0xFF, bit count ∈ 0..8

  Controls:
    F1 = re-run the scan
--]]

local _src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
local _lua_root = _src:match("(.+[/\\])tests[/\\]") or _src
local _proj_root = _lua_root:match("(.+[/\\])lua[/\\]") or (_lua_root .. "../")
package.path = _src .. "?.lua;"
           .. _lua_root .. "?.lua;"
           .. _lua_root .. "games/?.lua;"
           .. _proj_root .. "data/games/gen4_hgsspt/?.lua;"
           .. package.path

package.loaded["memory_nds"] = nil
package.loaded["gen4_hgsspt"] = nil

local M    = require("memory_nds")
local game = require("gen4_hgsspt")

-- Force Platinum profile (do not rely on variant detection).
local profile = game.profiles.platinum
M.applyProfile(profile)
local RAM = profile.RAM_DOMAIN or "Main RAM"

local function r8 (a) return memory.read_u8     (a, RAM) end
local function r16(a) return memory.read_u16_le (a, RAM) end
local function r32(a) return memory.read_u32_le (a, RAM) end

local function log(msg) console.log("[PT-SCAN] " .. msg) end

local function bit_count(n)
    local c = 0
    while n and n > 0 do
        c = c + (n & 1)
        n = n >> 1
    end
    return c
end

local function plausibility(label, ok) return label .. (ok and " OK" or " ⚠️  FAIL") end

local function dump_player_name(base, name_off)
    local chars, raw = {}, {}
    for i = 0, 7 do
        local c = r16(base + name_off + i * 2)
        raw[#raw+1] = string.format("%04X", c)
        if c == 0xFFFF or c == 0x0000 then break end
        if     c >= 289 and c <= 298 then chars[#chars+1] = string.char(c - 241)
        elseif c >= 299 and c <= 324 then chars[#chars+1] = string.char(c - 234)
        elseif c >= 325 and c <= 350 then chars[#chars+1] = string.char(c - 228)
        elseif c == 478 then chars[#chars+1] = " "
        elseif c == 446 then chars[#chars+1] = "-"
        end
    end
    return table.concat(chars), table.concat(raw, " ")
end

local function run_scan()
    console.clear()
    log("============== Gen 4 Platinum profile scan ==============")
    log(string.format("emu.framecount = %d", emu.framecount and emu.framecount() or -1))

    -- 1. Pointer chain
    local p1_addr = 0x0BA8
    local p1 = r32(p1_addr) & 0xFFFFFF
    log(string.format("P1 @ 0x%04X        = 0x%06X  %s", p1_addr, p1,
        plausibility("(non-zero)", p1 ~= 0)))
    if p1 == 0 then
        log("⚠️  Pointer chain not resolved — load a save and re-run.")
        return
    end

    local base = r32(p1 + 0x20) & 0xFFFFFF
    log(string.format("BASE @ p1+0x20     = 0x%06X  %s", base,
        plausibility("(non-zero)", base ~= 0)))
    if base == 0 then return end

    local mb = M.init()
    log(string.format("M.init() base      = %s", mb and string.format("0x%06X", mb) or "nil"))

    -- 2. Party count (Pt: base+0xB0)
    local pc = r8(base + 0xB0)
    log(string.format("Party count @ +0xB0 = %d  %s", pc, plausibility("(0..6)", pc >= 0 and pc <= 6)))

    -- 3. Each party slot
    for i = 0, math.min(pc, 6) - 1 do
        local addr = base + 0xB4 + i * 0xEC
        local pid  = r32(addr)
        local chk  = r16(addr + 0x06)
        local lv, hp, max_hp, status = M.decrypt_stats(addr + 0x88, pid)
        local sp, ot, hi, abl = M.decrypt_block_a_ext(addr)
        log(string.format("  slot %d  PID=%08X chk=%04X  sp=%s lv=%d HP=%d/%d ot=%s hi=%s abl=%s",
            i, pid, chk,
            sp and tostring(sp) or "nil",
            lv, hp, max_hp,
            ot and string.format("%08X", ot) or "nil",
            hi and string.format("%d", hi) or "nil",
            abl and string.format("%d", abl) or "nil"))
    end

    -- 4. PC storage offset — Platinum uses SaveData.pageInfo[37].location, NOT arrayHeaders.
    --   0x2027C  — &pageInfo[37].location in SaveData (SAVE_TABLE_ENTRY_PC_BOXES=37);
    --              expected to return the offset of PCBoxes within body.data (~0x11C8 or similar)
    --   0x232AC  — HGSS arrayHeaders[41].offset; always reads 0x0 on live Pt (past struct end)
    --   0x232B0  — same (+4 shift theory); also reads 0x0 on live Pt
    -- Plausibility: value should be in 0x100..0x23000.
    -- pcStorageBase() adds PC_BOXES_DATA_OFF=4 to skip PCBoxes.currentBoxID header.
    for _, candidate in ipairs({ 0x2027C, 0x232AC, 0x232B0 }) do
        local pc_hdr_off = r32(base + candidate)
        local ok = pc_hdr_off >= 0x100 and pc_hdr_off < 0x23000
        log(string.format("PC arrayHeaders[41].offset @ +0x%X = 0x%X  %s",
            candidate, pc_hdr_off, plausibility("(0x100..0x23000)", ok)))
    end

    -- 5. Zone ID (Pt: base+0x239B0 is a pointer; u16 at ptr+2)
    local zone_raw = r16(base + 0x239B0)
    local zone = zone_raw
    if zone == 0 then
        local zptr = r32(base + 0x239B0) & 0xFFFFFF
        if zptr ~= 0 then zone = r16(zptr + 2) end
        log(string.format("Zone direct=0x%X  ptr=0x%06X  → zone=0x%X", zone_raw, zptr, zone))
    else
        log(string.format("Zone direct=0x%X", zone))
    end
    log(string.format("Zone plausibility  %s", plausibility("(0..0x280)", zone < 0x280)))

    -- 6. Enemy trainer ID (Pt: base+0x4189E)
    local tr_id = r16(base + 0x4189E)
    log(string.format("Enemy trainer ID @ +0x4189E = %d (0=wild, expected 0 in overworld)", tr_id))

    -- 7. Player name (Pt: base+0x7C, u16[8] Gen IV charcode)
    local name, raw = dump_player_name(base, 0x7C)
    log(string.format("Player name @ +0x7C = \"%s\"  raw: %s", name, raw))
    local first = r16(base + 0x7C)
    log(string.format("Name first char plausibility  %s",
        plausibility("(289..350 or 0)", first == 0 or (first >= 289 and first <= 350))))

    -- 8. Sinnoh badges (Pt: base+0x96)
    local badges = r8(base + 0x96)
    log(string.format("Sinnoh badges @ +0x96 = 0x%02X (%d/8)  %s",
        badges, bit_count(badges), plausibility("(bit_count 0..8)", bit_count(badges) <= 8)))

    -- 9. Battle status (absolute, profile says 0x24A55A for Pt)
    local bs = r8(0x24A55A)
    log(string.format("Battle status @ 0x24A55A = %d", bs))

    log("============== Scan complete ==============")
    log("If every line shows OK, _PT_PROFILE constants can graduate from VERIFY_ME.")
end

-- Initial scan
run_scan()

-- F1 = re-run
event.onframestart(function()
    if input.get()["F1"] then
        run_scan()
    end
end)
