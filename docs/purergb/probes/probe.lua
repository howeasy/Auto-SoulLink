-- pureRGB live probe (BizHawk 2.11.1). Measures, does not decide.
-- Answers: domain sizes / CGB mode, hGBC, KEY1 double speed by scene, VBlank stack shape
-- ([SP],[SP+2]) at the vector, WRAM bank at VBlank entry, hook frame offset, romhash API.
local OUT = os.getenv("SLINK_PROBE_OUT") or "probe_out.txt"
local MAX_FRAMES = tonumber(os.getenv("SLINK_PROBE_FRAMES") or "9000")
local f = assert(io.open(OUT, "w"))
local function log(s) f:write(s .. "\n"); f:flush() end

-- symbols from the canonical build (pokered.sym, identical in Blue/Green for these)
local SYM = {
    VBlank_vector = 0x0040,
    DelayFrame = 0x1E76, DelayFrame_halt = 0x1E8D,
    OverworldLoop = 0x03D6, OverworldLoopLessDelay = 0x03D7,
    wCurMap = 0xD366, wIsInBattle = 0xD057, wLinkState = 0xD133,
    wDelayFrameBank = 0xD12B, hGBC = 0xFFFE, hLoadedROMBank = 0xFFB8,
    wPlayerName = 0xD2FF, wPartyCount = 0xD16B,
    wXCoord = 0xD36A, wYCoord = 0xD369, wOptions2 = 0xDA45,
}
local walk_mode, fade_set, warps = false, false, 0
local last_map = nil
local offset_hist = {}

log("version=" .. tostring(client.getversion()))
log("systemid=" .. tostring(emu.getsystemid()))
log("romname=" .. tostring(gameinfo.getromname()))
log("romhash=" .. tostring(gameinfo.getromhash()))
log("indatabase=" .. tostring(gameinfo.indatabase()))
log("client.step=" .. type(client.step))
local doms = memory.getmemorydomainlist()
for k, d in pairs(doms) do
    log(string.format("domain[%s]=%s size=0x%X", tostring(k), tostring(d), memory.getmemorydomainsize(d)))
end
log("currentdomain=" .. tostring(memory.getcurrentmemorydomain()))

local bus = "System Bus"
local function u8(a) return memory.read_u8(a, bus) end
local function u16(a) return memory.read_u16_le(a, bus) end

-- tallies
local pairs_tally = {}       -- "[SP],[SP+2],wb,rb" -> count (only when map is a real map)
local vb_bank = {}           -- wram bank at vblank entry -> count
local key1_tally = {}        -- key1 bit7 at vblank -> count, per scene (map:inbattle)
local ow_cb_frames = {}      -- hook frame vs frame-end frame agreement
local last_ow_cb_frame, last_ow_cb_pc = nil, nil
local halt_cb = 0

event.on_bus_exec(function()
    local sp = emu.getregister("SP")
    local wb = emu.getregister("WRAM BANK")
    local rb = emu.getregister("ROMX BANK")
    local r0, r2 = u16(sp), u16(sp + 2)
    local map, inb = u8(SYM.wCurMap), u8(SYM.wIsInBattle)
    local key = string.format("%04X,%04X,wb%d,rb%02X,map%02X,inb%d", r0, r2, wb, rb, map, inb)
    pairs_tally[key] = (pairs_tally[key] or 0) + 1
    vb_bank[wb] = (vb_bank[wb] or 0) + 1
    local k1 = u8(0xFF4D)
    local scene = string.format("map%02X:inb%d:spd%d", map, inb, (k1 >= 0x80) and 2 or 1)
    key1_tally[scene] = (key1_tally[scene] or 0) + 1
end, SYM.VBlank_vector, "probe_vblank")

event.on_bus_exec(function()
    last_ow_cb_frame = emu.framecount()
    last_ow_cb_pc = emu.getregister("PC")
end, SYM.OverworldLoop, "probe_owloop")

event.on_bus_exec(function() halt_cb = halt_cb + 1 end, SYM.DelayFrame_halt, "probe_halt")

local function idle()
    return {A = false, B = false, Start = false, Select = false,
            Up = false, Down = false, Left = false, Right = false}
end

local frame = 0
local started = emu.framecount()
client.speedmode(800)
local first_ow_frame, first_spd2_frame = nil, nil

local function summary(tag)
    log("== summary " .. tag .. " frame=" .. frame)
    log(string.format("hGBC=%d hLoadedROMBank=%02X wCurMap=%02X wIsInBattle=%d wLinkState=%d wDelayFrameBank=%d KEY1=%02X WRAMBANK=%d",
        u8(SYM.hGBC), u8(SYM.hLoadedROMBank), u8(SYM.wCurMap), u8(SYM.wIsInBattle), u8(SYM.wLinkState),
        u8(SYM.wDelayFrameBank), u8(0xFF4D), emu.getregister("WRAM BANK")))
    log("halt_cb=" .. halt_cb .. " first_ow_frame=" .. tostring(first_ow_frame) .. " first_spd2_frame=" .. tostring(first_spd2_frame))
    local keys = {}
    for k in pairs(pairs_tally) do keys[#keys + 1] = k end
    table.sort(keys, function(a, b) return pairs_tally[a] > pairs_tally[b] end)
    for i = 1, math.min(#keys, 40) do log("stack " .. keys[i] .. " x" .. pairs_tally[keys[i]]) end
    for b, n in pairs(vb_bank) do log("vblank_wram_bank " .. b .. " x" .. n) end
    local sk = {}
    for k in pairs(key1_tally) do sk[#sk + 1] = k end
    table.sort(sk)
    for _, k in ipairs(sk) do log("scene " .. k .. " x" .. key1_tally[k]) end
    local ok, mis = 0, 0
    for _, v in ipairs(ow_cb_frames) do if v then ok = ok + 1 else mis = mis + 1 end end
    for d, n in pairs(offset_hist) do log("hook_frame_offset " .. d .. " x" .. n) end
    log("warps=" .. warps .. " walk_mode=" .. tostring(walk_mode))
end

event.onframeend(function()
    frame = frame + 1
    if last_ow_cb_frame then
        local d = last_ow_cb_frame - emu.framecount()
        offset_hist[d] = (offset_hist[d] or 0) + 1
        if not first_ow_frame then first_ow_frame = frame end
        last_ow_cb_frame = nil
        walk_mode = true
    end
    if not first_spd2_frame and u8(0xFF4D) >= 0x80 then first_spd2_frame = frame end
    -- mash through the intro: A every 8 frames, Start every 40, Down once in a while for menus
    local b = idle()
    if not walk_mode then
        if frame % 8 < 2 then b.A = true end
        if frame % 40 < 2 then b.Start = true end
    else
        local map, x, y = u8(SYM.wCurMap), u8(SYM.wXCoord), u8(SYM.wYCoord)
        if not fade_set and emu.getregister("WRAM BANK") == 1 then
            memory.write_u8(SYM.wOptions2, u8(SYM.wOptions2) | 0x20, bus) -- GBC FADE on (probe only)
            fade_set = true
            log("fade_set at frame " .. frame .. " wOptions2=" .. string.format("%02X", u8(SYM.wOptions2)))
        end
        if last_map ~= nil and map ~= last_map then warps = warps + 1; log("warp " .. warps .. " map " .. string.format("%02X->%02X", last_map, map) .. " frame " .. frame) end
        last_map = map
        local tgt
        if map == 0x26 then tgt = (x ~= 4 and y ~= 1) and {4, 1} or ((y ~= 1) and {4, 1} or {7, 1})
        elseif map == 0x25 then tgt = {7, 1}
        else tgt = nil end
        if tgt and frame % 4 < 3 then
            if x < tgt[1] then b.Right = true elseif x > tgt[1] then b.Left = true
            elseif y < tgt[2] then b.Down = true elseif y > tgt[2] then b.Up = true end
        end
        if frame % 300 == 0 then b.B = true end
    end
    joypad.set(b)
    if frame % 600 == 0 then summary("periodic") end
    if frame >= MAX_FRAMES then
        summary("final")
        log("RESULT: DONE")
        f:close()
        client.exit()
    end
end)
