-- test_live_infoscreen.lua — the SOULLINK info screen (ROADMAP §6, step 2, opcode 27).
--
-- Stages lines into SlinkInfo, opens the panel, and proves it renders and closes. The screen is
-- separate from the START-menu row on purpose (test_live_soullinkmenu covers that), so this gate
-- drives it straight from the opcode.
--
-- What would silently ship broken without each check:
--   * a panel that never opens still ACKs, because the ack comes from the script lock, not from
--     pixels — so assert the window really got drawn (VRAM changed) rather than trusting status.
--   * A and B must BOTH close it. If only A does, a player who reflexively presses B is stuck in a
--     locked field script with no way out.
--   * result[0] must distinguish them, because that is the whole pagination signal for step 4.
--   * the guards must actually reject: no lines staged, or a line with no terminator, must fail
--     the opcode rather than draw garbage from the next slot.
--
--   python tools/run_gate.py lua/tests/test_live_infoscreen.lua --timeout 300
local SDIR = "E:/Howard/Bizhawk/GBA/State"
local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT = WT .. "/patch/build/infoscreen_result.txt"
local MB = dofile(WT .. "/lua/mailbox.lua")

local lines = {}
local function log(s) lines[#lines + 1] = s; console.log(s) end
local function finish(ok)
    log(ok and "RESULT: PASS" or "RESULT: FAIL")
    local f = io.open(OUT, "w")
    if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
    client.exit()
end

pcall(memory.usememorydomain, "System Bus")
pcall(function() client.speedmode(400) end)

-- No "SOUL LINK" row: the title is a ROM const drawn in the header now, and no "Page 1/2" row
-- either -- write_info stages that into the header's slot 7.
--
-- All three row kinds are represented, because the patch picks the kind from the field count and a
-- fixture of only one kind would never exercise that dispatch. One mon is deliberately fainted
-- (barpx 0) and one is deliberately in the red band, so the colour thresholds are covered too.
local PANEL = {}
MB.info_pair(PANEL, "RT03", { name = "Bulbasaur",  level = 12, hp = "19/23", bar = MB.info_bar(19, 23) },
                            { name = "Squirtle",   level = 11, hp = "FNT",   bar = 0 })
-- One statused and one boxed mon, so the 7th (status) and 6th (state) fields are both exercised.
-- A boxed mon must NOT render like a dead one: red means dead on this screen.
MB.info_pair(PANEL, "VIRI", { name = "Butterfree", level = 14, hp = " 4/38", bar = MB.info_bar(4, 38),
                              status = "PSN" },
                            { name = "Nidoran",    level = 13, hp = "BOX", bar = 0, state = "B" })
PANEL[#PANEL + 1] = MB.info_stat("Dead zones", "2")
PANEL[#PANEL + 1] = "Waiting on partner..."

local function boot()
    assert(pcall(savestate.load, SDIR .. "/slink_overworld.State"), "no overworld savestate")
    emu.frameadvance()
    for _ = 1, 240 do emu.frameadvance(); if MB.present() then break end end
    if not MB.present() then log("FAIL: no 'SLNK' beacon — unpatched ROM?"); finish(false) end
    memory.write_u8(MB.INFO_LINES, 0)
end

-- The panel is drawn into a field window, so its tiles land in BG VRAM. Hashing a slice of VRAM is
-- a cheap, engine-agnostic way to assert "something was actually drawn" without asserting on exact
-- glyphs (which would break the moment the font or window style changed).
local function vram_hash()
    local h = 0
    -- Sweep the whole BG tile/char area, not just the first 4 KB: FR allocates window tiles
    -- dynamically and the panel's land well past 0x06001000 (a narrower range read as "never drew"
    -- while the screenshot plainly showed the panel).
    for a = 0x06000000, 0x0600FFFF, 4 do
        h = (h * 31 + memory.read_u32_le(a)) % 0x7FFFFFFF
    end
    return h
end

local function poll(seq, frames)
    for _ = 1, (frames or 600) do
        emu.frameadvance()
        local st, reason = MB.poll(seq)
        if st then return st, reason end
    end
    return nil
end

local function press(btn, frames)
    for f = 1, (frames or 30) do
        joypad.set(f <= 3 and { [btn] = true } or {})
        emu.frameadvance()
    end
end

-- 1. guards: nothing staged must be refused, not drawn empty.
boot()
local st, reason = poll(MB.show_info(0), 120)
log("no lines staged -> status=" .. tostring(st) .. " reason=" .. tostring(reason))
if st ~= MB.ST_FAIL then
    log("FAIL: the opcode accepted an empty panel")
    finish(false); return
end

-- 2. an unterminated line must be refused too (the printer would read into the next slot).
boot()
MB.write_info({ "ok" }, 1, 1)
for i = 0, 31 do memory.write_u8(MB.INFO_LINE + i, 0xBB) end   -- fill slot 0, no 0xFF anywhere
local seq = MB.show_info(0)
st, reason = poll(seq, 180)
-- Must be rejected at the OPCODE, before lockall. Rejecting inside the callnative instead would
-- leave a locked overworld with no window and no way out — the first run of this gate caught
-- exactly that (status came back nil because the script never resolved).
log("unterminated line -> status=" .. tostring(st) .. " reason=" .. tostring(reason))
if st ~= MB.ST_FAIL then
    log("FAIL: an unterminated line must be a clean ST_FAIL, not " .. tostring(st))
    finish(false); return
end
if memory.read_u8(0x03000F9C) ~= 0 then
    log("FAIL: the field was left locked by a rejected panel")
    finish(false); return
end

-- 3. the real thing: stage, open, and confirm it DREW.
boot()
local n = MB.write_info(PANEL, 1, 2)
log("staged " .. n .. " lines")
if n ~= #PANEL then log("FAIL: write_info staged " .. n); finish(false); return end
if memory.read_u8(MB.INFO_LINES) ~= #PANEL then
    log("FAIL: INFO_LINES not published"); finish(false); return
end

local before = vram_hash()
seq = MB.show_info(1)
-- Let the script lock and the window draw before sampling.
for _ = 1, 120 do emu.frameadvance() end
local after = vram_hash()
log(string.format("vram %d -> %d (drawn=%s)", before, after, tostring(before ~= after)))
pcall(function() client.screenshot(WT .. "/patch/build/soullink_info.png") end)
if before == after then
    log("FAIL: opening the panel changed nothing in BG VRAM — it never drew")
    finish(false); return
end

-- 3b. it must draw in COLOUR. The whole point of this redesign is that a real FRLG screen is
-- two-tone -- a blue header over dark-gray body text with a light-gray rule -- and a screen that
-- drew but drew flat black would pass every check above. Read the panel's own tiles and count
-- which 4bpp palette indices actually appear.
-- Panel tiles are row-major, 27 wide, 32 bytes each (4bpp), from baseBlock 0x38. Banding by tile
-- lets an assertion say "blue appears HERE", which is the only way to prove a specific element
-- drew rather than just that the palette is in use somewhere on the panel.
local function panel_palette_tiles(tx0, tx1, ty0, ty1)
    local cbb = ((memory.read_u16_le(0x04000008) >> 2) & 3) * 0x4000
    local base = 0x06000000 + cbb + 0x38 * 32
    local seen = {}
    for ty = ty0, ty1 do
        for tx = tx0, tx1 do
            local t = ty * 27 + tx
            if t >= 0 and t <= 350 then
                for b = 0, 31 do
                    local v = memory.read_u8(base + t * 32 + b)
                    seen[v & 0xF] = true; seen[v >> 4] = true
                end
            end
        end
    end
    return seen
end
local function panel_palette() return panel_palette_tiles(0, 26, 0, 12) end
local pal = panel_palette()
local have = {}
for i = 0, 15 do if pal[i] then have[#have + 1] = i end end
log("palette indices present in the panel: " .. table.concat(have, " "))
if not (pal[8] or pal[9]) then
    log("FAIL: no blue in the panel — the colour triple never took (AddTextPrinterParameterized4)")
    finish(false); return
end
if not pal[3] then
    log("FAIL: no light-gray — the hairline rule under the header did not draw")
    finish(false); return
end
if not pal[2] then
    log("FAIL: no dark-gray body text")
    finish(false); return
end

-- 3c. PAIR GROUPING. Two rows sharing an area tag conveyed pairing only by implication; the tie
-- bracket is what makes it explicit, so assert it landed in the gutter between the label and the
-- name (px x 24..27 -> tile col 3; the pair's two rows span px y 24..37 -> tile rows 3..4).
-- Nothing else blue is drawn there: the area tag ends before x=24 and the name is body-coloured.
local gutter = panel_palette_tiles(3, 3, 3, 4)
if not gutter[8] then
    log("FAIL: no tie bracket between the pair's rows — grouping did not draw")
    finish(false); return
end
-- and a lone row must NOT get one: row 5 (Dead zones) is a label/value, not a pair member.
local solo = panel_palette_tiles(3, 3, 8, 9)
if solo[8] then
    log("FAIL: a bracket was drawn beside a non-pair row")
    finish(false); return
end
log("pair bracket present between paired rows, absent beside unpaired ones")

-- 3d. STATUS COLUMN. A poisoned linked mon is invisible from the HP bar alone, so the token is
-- drawn in the gap between the bar and the right-aligned HP text (content px 152+, tile cols 19-20).
-- Restricted to that band so the FAINTED row's red name/HP text cannot satisfy it by accident.
local band = panel_palette_tiles(19, 20, 6, 7)
if not (band[4] or band[5]) then
    log("FAIL: no status token drawn in the status column")
    finish(false); return
end
log("status token present in its own column")

-- 4. A closes it, and reports 0.
press("A", 60)
st = poll(seq, 300)
local res_a = MB.info_result()
log("A -> status=" .. tostring(st) .. " result[0]=" .. tostring(res_a))
if st ~= MB.ST_OK then
    log("FAIL: A did not resolve the panel")
    finish(false); return
end
if res_a ~= MB.INFO_ADVANCE then
    log("FAIL: expected result[0]=0 for A, got " .. res_a)
    finish(false); return
end
if memory.read_u8(0x03000F9C) ~= 0 then      -- sScriptContext2Enabled: the field must be released
    log("FAIL: the field script is still locked after closing with A")
    finish(false); return
end

-- 5. B closes it too, and reports 0x7F — that difference IS the pagination signal.
boot()
MB.write_info(PANEL, 2, 2)
seq = MB.show_info(2)
for _ = 1, 120 do emu.frameadvance() end
press("B", 60)
st = poll(seq, 300)
local res_b = MB.info_result()
log("B -> status=" .. tostring(st) .. " result[0]=" .. tostring(res_b))
if st ~= MB.ST_OK then
    log("FAIL: B did not resolve the panel — a player pressing B would be stuck")
    finish(false); return
end
if res_b ~= MB.INFO_CLOSE then
    log("FAIL: expected result[0]=0x7F for B, got " .. res_b)
    finish(false); return
end
if memory.read_u8(0x03000F9C) ~= 0 then
    log("FAIL: the field script is still locked after closing with B")
    finish(false); return
end

-- 6. and the screen must be re-openable (a leaked window or task would break the second open).
boot()
MB.write_info(PANEL, 1, 2)
for _ = 1, 2 do
    seq = MB.show_info(1)
    for _ = 1, 120 do emu.frameadvance() end
    press("A", 60)
    if poll(seq, 300) ~= MB.ST_OK then
        log("FAIL: the panel did not survive being reopened")
        finish(false); return
    end
end
log("reopened twice cleanly")

log("info screen: draws, A=0 and B=0x7F both close and release the field, reopens cleanly")
finish(true)
