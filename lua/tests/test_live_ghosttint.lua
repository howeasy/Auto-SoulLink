-- test_live_ghosttint.lua — the ghost's palette must follow the world's day/night tint (ROADMAP §5).
--
-- RR tints OBJ palettes by writing palette RAM and knows nothing about our hijacked slot 15, so
-- the patch derives the tint the engine is applying from the PLAYER's own slot —
-- (live palette RAM) / (unfaded true colours), summed per channel — and applies that ratio to the
-- partner's true colours (apply_tint in handlers.c).
--
-- HOW TO FORCE A TINT (learned the hard way): writing the player's palette RAM directly does
-- NOT work. The engine DMAs its FADED shadow buffer over palette RAM every frame, so a direct
-- RAM write is gone before the next frame's hook reads it — the forced ratio silently never
-- applies and the test measures the engine's own ~0.95 instead. Write the player's FADED row
-- and let the engine publish it. We then assert the ghost matches the ratio ACTUALLY OBSERVED
-- on the player's rows, so rounding in the forcing can't skew the expectation.
--   EmuHawk.exe --lua=lua/tests/test_live_ghosttint.lua patch/build/slink_RR.gba

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT = WT .. "/patch/build/ghosttint_result.txt"
local MB = dofile(WT .. "/lua/mailbox.lua")

local OE, OST, GS, GST = 0x02036E38, 0x24, 0x0202063C, 0x44
local UNFADED, FADED, PLTT_RAM = 0x020373F8, 0x020377F8, 0x05000200
local GHOST_SLOT = 15

local function spr_imgs(s)   return memory.read_u32_le(GS + s*GST + 0x0C) end
local function spr_anims(s)  return memory.read_u32_le(GS + s*GST + 0x08) end
local function spr_palnum(s) return (memory.read_u16_le(GS + s*GST + 0x04) >> 12) & 0x0F end
local function chan(c) return c & 0x1F, (c >> 5) & 0x1F, (c >> 10) & 0x1F end
local function frames(n) for _ = 1, n do emu.frameadvance() end end

local lines, fails = {}, 0
local function log(s) lines[#lines+1] = s; console.log(s) end
local function check(n, c, e) if not c then fails = fails + 1 end
    log(string.format("  [%s] %s%s", c and "PASS" or "FAIL", n, e and "  " .. e or "")) end
local function finish() log(fails == 0 and "RESULT: PASS" or ("RESULT: FAIL (" .. fails .. ")"))
    local f = io.open(OUT, "w"); if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
    client.exit() end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, "E:/Howard/Bizhawk/GBA/State/slink_overworld.State")
emu.frameadvance(); pcall(memory.usememorydomain, "System Bus")
check("patch present", MB.present()); if not MB.present() then finish(); return end

local poe = MB.player_oe()
local psid = memory.read_u8(poe + 0x04)

-- A bright, strictly-increasing synthetic palette: dim colours all round to the same value at
-- any ratio, which would make the assertions vacuous.
local pcol_t = {}
for i = 0, 15 do local v = 8 + i; pcol_t[#pcol_t+1] = string.format("%04X", v | (v << 5) | (v << 10)) end
local pcol = table.concat(pcol_t)

MB.ghost_set_pos((memory.read_s16_le(poe + 0x10) + 1) * 16, memory.read_s16_le(poe + 0x12) * 16, 4, 0, 0)
MB.ghost_spawn(memory.read_u8(poe + 0x05))
local oe = 16
for _ = 1, 120 do emu.frameadvance(); oe = MB.ghost_oe(); if oe < 16 then break end end
check("ghost spawned", oe < 16, "oeId=" .. oe); if oe >= 16 then finish(); return end
local gsid = memory.read_u8(OE + oe*OST + 0x04)

MB.ghost_set_avatar(spr_imgs(psid), spr_anims(psid), pcol)
frames(20)
check("ghost is on the dedicated palette slot", spr_palnum(gsid) == GHOST_SLOT,
      "slot=" .. spr_palnum(gsid))

local ps = spr_palnum(psid)

-- Force the player's row through FADED (the buffer the engine publishes), then let the DMA land
-- and the hook read it. Returns the ratio actually observed on the player's rows, per channel.
local function force_and_measure(num, den)
    for i = 0, 15 do
        local r, g, b = chan(memory.read_u16_le(UNFADED + ps*0x20 + i*2))
        memory.write_u16_le(FADED + ps*0x20 + i*2,
            ((r*num)//den) | (((g*num)//den) << 5) | (((b*num)//den) << 10))
    end
    frames(4)                                     -- DMA publishes, then the hook reads it
    local rn, gn, bn, rd, gd, bd = 0, 0, 0, 0, 0, 0
    for i = 0, 15 do
        local tr, tg, tb = chan(memory.read_u16_le(UNFADED + ps*0x20 + i*2))
        local lr, lg, lb = chan(memory.read_u16_le(PLTT_RAM + ps*0x20 + i*2))
        rd = rd + tr; gd = gd + tg; bd = bd + tb
        rn = rn + lr; gn = gn + lg; bn = bn + lb
    end
    return rn, rd, gn, gd, bn, bd
end

local baseline = nil
for _, case in ipairs({ {2, 2, "full brightness"}, {1, 2, "half brightness"} }) do
    local num, den, label = case[1], case[2], case[3]
    local rn, rd = force_and_measure(num, den)
    local ratio = (rd > 0) and (rn / rd) or 1
    log(string.format("%s: player row ratio measured at %.3f (forced %d/%d)", label, ratio, num, den))
    -- Guard against the trap this test used to fall into: if the forcing did not survive the
    -- frame, the ratio never moves and every assertion below is vacuous. Compared RELATIVE to
    -- the full-brightness baseline, not to num/den: the engine layers its own ambient tint on
    -- top, so the absolute ratio depends on where and when the savestate was captured (0.417
    -- rather than 0.500 in a shaded route, for instance). What must hold is that halving the
    -- player's row visibly halves what the patch measures.
    if baseline == nil then
        baseline = ratio
        check(label .. ": baseline ratio is sane", ratio > 0.2,
              string.format("measured %.3f", ratio))
    else
        check(label .. ": halving the player's row halves what the patch sees",
              ratio < baseline * 0.75,
              string.format("measured %.3f, baseline %.3f", ratio, baseline))
    end

    local uf_ok, fd_ok, rm_ok, worst = true, true, true, ""
    for i = 0, 15 do
        local want = tonumber(pcol:sub(i*4+1, i*4+4), 16)
        if memory.read_u16_le(UNFADED + GHOST_SLOT*0x20 + i*2) ~= want then uf_ok = false end
        local tr = chan(want)
        local want_r = math.min(31, math.floor(tr * ratio + 0.5))
        local fr = chan(memory.read_u16_le(FADED + GHOST_SLOT*0x20 + i*2))
        local rr = chan(memory.read_u16_le(PLTT_RAM + GHOST_SLOT*0x20 + i*2))
        if math.abs(fr - want_r) > 1 then fd_ok = false
            worst = string.format("i=%d faded r=%d want=%d", i, fr, want_r) end
        if math.abs(rr - want_r) > 1 then rm_ok = false
            worst = string.format("i=%d ram r=%d want=%d", i, rr, want_r) end
    end
    check(label .. ": unfaded slot 15 still holds the partner's TRUE colours", uf_ok)
    check(label .. ": faded slot 15 is tinted by the world's ratio", fd_ok, worst)
    check(label .. ": live palette RAM slot 15 matches", rm_ok, worst)
end

finish()
