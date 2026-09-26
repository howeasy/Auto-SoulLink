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
-- The client opens this screen only from the START-menu row (native.lua stages SlinkInfo and re-opens
-- it as a page turn), never with a direct OP_SHOW_INFO, and never with a malformed stage. So the
-- staging and the opcode go through lua/tests/gen3_gatelib.lua's test-only raw poster (card C5-4b),
-- with the row builders and write_info below mirroring the old client's layout vocabulary.
--
--   python tools/run_gate.py lua/tests/test_live_infoscreen.lua --timeout 300
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("infoscreen")
local SC2 = 0x03000F9C       -- sScriptContext2Enabled
local P = t.P
local INFO_LINE = P.INFO + 8 -- u8[8][32]: FR-encoded, 0xFF-terminated
local INFO_LINES = P.INFO + 3
local INFO_ADVANCE, INFO_CLOSE = 0, 0x7F

-- Row builders (the patch picks a row's KIND from its "\n"-field count: 5+ = mon row, 2 = label/
-- value, 1 = full-width text). Lua does the HP->pixels division; barpx 0 renders red (fainted).
local function info_bar(cur, max)
    if not cur or not max or max <= 0 or cur <= 0 then return 0 end
    local px = math.floor(cur * P.INFO_BAR_W / max + 0.5)
    if px < 1 then px = 1 end
    return math.min(P.INFO_BAR_W, px)
end
local function info_mon(label, name, level, hptext, barpx, state, status)
    return table.concat({ tostring(label):sub(1, 4), tostring(name):sub(1, 10), tostring(level),
                          tostring(hptext),
                          tostring(math.max(0, math.min(P.INFO_BAR_W, math.floor(barpx or 0)))),
                          state or "", (status or ""):sub(1, 3) }, "\n")
end
local function info_stat(label, value) return tostring(label) .. "\n" .. tostring(value) end
local function info_pair(rows, label, mine, theirs)
    rows[#rows + 1] = info_mon(label, mine.name, mine.level, mine.hp, mine.bar, mine.state, mine.status)
    rows[#rows + 1] = info_mon("", theirs.name, theirs.level, theirs.hp, theirs.bar, theirs.state, theirs.status)
    return rows
end
-- Stage the panel: lines, page/pages, the header page indicator (slot 7), THEN the line count (the
-- patch's "ready" gate), then gen++. One raw stage through the native write window.
local function write_info(lines, page, pages)
    local n = math.min(#lines, P.INFO_MAXLINES)
    local stages = {}
    for i = 1, n do
        stages[#stages + 1] = { INFO_LINE + (i - 1) * P.INFO_LINEW,
                                t.encode(tostring(lines[i]):sub(1, P.INFO_LINEW - 1), P.INFO_LINEW) }
    end
    stages[#stages + 1] = { P.INFO + 4, { page or 0, pages or 1 } }
    stages[#stages + 1] = { INFO_LINE + P.INFO_PAGESLOT * P.INFO_LINEW,
                            t.encode(string.format("PAGE %d/%d", (page or 0) + 1, pages or 1), P.INFO_LINEW) }
    stages[#stages + 1] = { INFO_LINES, { n } }
    stages[#stages + 1] = { P.INFO + 6, { (memory.read_u8(P.INFO + 6) + 1) % 256 } }
    if not t.raw_stage(stages) then t.fail("SlinkInfo staged", t.last_service) end
    return n
end
local function show_info(page)
    local job = t.raw("OP_SHOW_INFO", { page or 0 })
    if not t.wait_posted(job) then t.fail("OP_SHOW_INFO posted", t.last_service) end
    return job
end

-- No "SOUL LINK" row: the title is a ROM const drawn in the header now, and no "Page 1/2" row
-- either -- write_info stages that into the header's slot 7.
--
-- All three row kinds are represented, because the patch picks the kind from the field count and a
-- fixture of only one kind would never exercise that dispatch. One mon is deliberately fainted
-- (barpx 0) and one is deliberately in the red band, so the colour thresholds are covered too.
local PANEL = {}
info_pair(PANEL, "RT03", { name = "Bulbasaur",  level = 12, hp = "19/23", bar = info_bar(19, 23) },
                            { name = "Squirtle",   level = 11, hp = "FNT",   bar = 0 })
-- One statused and one boxed mon, so the 7th (status) and 6th (state) fields are both exercised.
-- A boxed mon must NOT render like a dead one: red means dead on this screen.
info_pair(PANEL, "VIRI", { name = "Butterfree", level = 14, hp = " 4/38", bar = info_bar(4, 38),
                              status = "PSN" },
                            { name = "Nidoran",    level = 13, hp = "BOX", bar = 0, state = "B" })
PANEL[#PANEL + 1] = info_stat("Dead zones", "2")
PANEL[#PANEL + 1] = "Waiting on partner..."

local function boot()
    t.boot({ state = "slink_overworld.State", native = false, beacon = 240 })
    if not t.raw_stage({ { INFO_LINES, { 0 } } }) then t.fail("SlinkInfo lines cleared", t.last_service) end
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

-- A raw job's receipt as status "OK" / "FAIL" (patch refusal) / nil (no ack yet), raw reason, result.
local function poll(job, frames)
    local r = t.wait(job, frames or 600)
    if not r then return nil end
    return r.why == nil and "OK" or (r.why == "native refused" and "FAIL" or r.why), r.reason, r.result
end
local function press(btn, frames) t.tap(btn, frames or 30) end

-- 1. guards: nothing staged must be refused, not drawn empty.
boot()
local st, reason = poll(show_info(0), 120)
t.log("no lines staged -> status=" .. tostring(st) .. " reason=" .. tostring(reason))
if st ~= "FAIL" then
    t.fail("the opcode accepted an empty panel")
end

-- 2. an unterminated line must be refused too (the printer would read into the next slot).
boot()
write_info({ "ok" }, 1, 1)
local fill = {}
for i = 1, 32 do fill[i] = 0xBB end                            -- fill slot 0, no 0xFF anywhere
if not t.raw_stage({ { INFO_LINE, fill } }) then t.fail("slot 0 unterminated", t.last_service) end
local seq = show_info(0)
st, reason = poll(seq, 180)
-- Must be rejected at the OPCODE, before lockall. Rejecting inside the callnative instead would
-- leave a locked overworld with no window and no way out — the first run of this gate caught
-- exactly that (status came back nil because the script never resolved).
t.log("unterminated line -> status=" .. tostring(st) .. " reason=" .. tostring(reason))
if st ~= "FAIL" then
    t.fail("an unterminated line must be a clean ST_FAIL, not ", tostring(st))
end
if memory.read_u8(SC2) ~= 0 then
    t.fail("the field was left locked by a rejected panel")
end

-- 3. the real thing: stage, open, and confirm it DREW.
boot()
local n = write_info(PANEL, 1, 2)
t.log("staged " .. n .. " lines")
if n ~= #PANEL then t.fail("write_info staged every row", "staged " .. n) end
if memory.read_u8(INFO_LINES) ~= #PANEL then t.fail("INFO_LINES published") end

local before = vram_hash()
seq = show_info(1)
-- Let the script lock and the window draw before sampling.
t.idle(120)
local after = vram_hash()
t.log(string.format("vram %d -> %d (drawn=%s)", before, after, tostring(before ~= after)))
pcall(function() client.screenshot(t.ROOT .. "/patch/build/soullink_info.png") end)
if before == after then
    t.fail("opening the panel changed nothing in BG VRAM — it never drew")
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
t.log("palette indices present in the panel: " .. table.concat(have, " "))
if not (pal[8] or pal[9]) then
    t.fail("no blue in the panel — the colour triple never took (AddTextPrinterParameterized4)")
end
if not pal[3] then
    t.fail("no light-gray — the hairline rule under the header did not draw")
end
if not pal[2] then
    t.fail("no dark-gray body text")
end

-- 3c. PAIR GROUPING. Two rows sharing an area tag conveyed pairing only by implication; the tie
-- bracket is what makes it explicit, so assert it landed in the gutter between the label and the
-- name (px x 24..27 -> tile col 3; the pair's two rows span px y 24..37 -> tile rows 3..4).
-- Nothing else blue is drawn there: the area tag ends before x=24 and the name is body-coloured.
local gutter = panel_palette_tiles(3, 3, 3, 4)
if not gutter[8] then
    t.fail("no tie bracket between the pair's rows — grouping did not draw")
end
-- and a lone row must NOT get one: row 5 (Dead zones) is a label/value, not a pair member.
local solo = panel_palette_tiles(3, 3, 8, 9)
if solo[8] then
    t.fail("a bracket was drawn beside a non-pair row")
end
t.log("pair bracket present between paired rows, absent beside unpaired ones")

-- 3d. STATUS COLUMN. A poisoned linked mon is invisible from the HP bar alone, so the token is
-- drawn in the gap between the bar and the right-aligned HP text (content px 152+, tile cols 19-20).
-- Restricted to that band so the FAINTED row's red name/HP text cannot satisfy it by accident.
local band = panel_palette_tiles(19, 20, 6, 7)
if not (band[4] or band[5]) then
    t.fail("no status token drawn in the status column")
end
t.log("status token present in its own column")

-- 4. A closes it, and reports 0.
press("A", 60)
local res_a
st, _, res_a = poll(seq, 300)
t.log("A -> status=" .. tostring(st) .. " result[0]=" .. tostring(res_a))
if st ~= "OK" then
    t.fail("A did not resolve the panel")
end
if res_a ~= INFO_ADVANCE then
    t.fail("expected result[0]=0 for A, got ", res_a)
end
if memory.read_u8(SC2) ~= 0 then      -- sScriptContext2Enabled: the field must be released
    t.fail("the field script is still locked after closing with A")
end

-- 5. B closes it too, and reports 0x7F — that difference IS the pagination signal.
boot()
write_info(PANEL, 2, 2)
seq = show_info(2)
t.idle(120)
press("B", 60)
local res_b
st, _, res_b = poll(seq, 300)
t.log("B -> status=" .. tostring(st) .. " result[0]=" .. tostring(res_b))
if st ~= "OK" then
    t.fail("B did not resolve the panel — a player pressing B would be stuck")
end
if res_b ~= INFO_CLOSE then
    t.fail("expected result[0]=0x7F for B, got ", res_b)
end
if memory.read_u8(SC2) ~= 0 then
    t.fail("the field script is still locked after closing with B")
end

-- 6. and the screen must be re-openable (a leaked window or task would break the second open).
boot()
write_info(PANEL, 1, 2)
for _ = 1, 2 do
    seq = show_info(1)
    t.idle(120)
    press("A", 60)
    if poll(seq, 300) ~= "OK" then
        t.fail("the panel did not survive being reopened")
    end
end
t.log("reopened twice cleanly")

t.log("info screen: draws, A=0 and B=0x7F both close and release the field, reopens cleanly")
t.finish()
