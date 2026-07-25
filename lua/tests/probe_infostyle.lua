-- probe_infostyle.lua — RESEARCH probe: do FR text control codes (colour, shift-right, font) work
-- inside the SOULLINK info window as it is drawn TODAY (FONT_NORMAL into a palette-15 field window)?
--
-- If they do, most of "make it look designed" — colour, right-aligned columns, a second font — costs
-- string bytes and no new engine calls at all. Screenshot is the verdict; this probe only stages.
--   python tools/run_gate.py lua/tests/probe_infostyle.lua --timeout 240
local SDIR = "E:/Howard/Bizhawk/GBA/State"
local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT = WT .. "/patch/build/infostyle_result.txt"
local MB = dofile(WT .. "/lua/mailbox.lua")

local lines = {}
local function log(s) lines[#lines + 1] = s; console.log(s) end
local function flush()
    local f = io.open(OUT, "w"); if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
end
pcall(memory.usememorydomain, "System Bus")
pcall(function() client.speedmode(400) end)

-- raw FR byte строки: fr_encode for the text, explicit bytes for the control codes
-- fr_encode returns a byte TABLE with a trailing 0xFF; drop it so segments can be concatenated.
local function enc(s)
    local t = MB.fr_encode(s)
    t[#t] = nil
    return t
end
local function cat(...)
    local out = {}
    for _, t in ipairs({ ... }) do for _, b in ipairs(t) do out[#out + 1] = b end end
    return out
end

-- 0xFC = EXT_CTRL_CODE. 1=<colour fg>, 4=<fg,bg,shadow>, 6=<font>, 13(0x0D)=<shift right px>,
-- 18(0x12)=<skip px>, 19(0x13)=<clear-to x px>
local PANEL = {
    cat(enc("PLAIN "), { 0xFC, 0x01, 0x04 }, enc("RED "), { 0xFC, 0x01, 0x06 }, enc("GREEN "),
        { 0xFC, 0x01, 0x08 }, enc("BLUE"), { 0xFF }),
    cat({ 0xFC, 0x04, 0x04, 0x01, 0x05 }, enc("RED+SHADOW5"), { 0xFF }),
    cat(enc("LEFT"), { 0xFC, 0x13, 0x60 }, enc("COL96"), { 0xFC, 0x13, 0xA0 }, enc("COL160"), { 0xFF }),
    cat({ 0xFC, 0x06, 0x00 }, enc("FONT0 small"), { 0xFC, 0x06, 0x02 }, enc(" FONT2"), { 0xFF }),
    cat({ 0xFC, 0x12, 0x30 }, enc("SKIP48"), { 0xFF }),
}

assert(pcall(savestate.load, SDIR .. "/slink_overworld.State"), "no overworld savestate")
emu.frameadvance()
for _ = 1, 240 do emu.frameadvance(); if MB.present() then break end end
if not MB.present() then log("FAIL: no SLNK beacon"); flush(); client.exit(); return end

for i, bytes in ipairs(PANEL) do
    local off = MB.INFO_LINE + (i - 1) * MB.INFO_LINEW
    for k = 0, MB.INFO_LINEW - 1 do memory.write_u8(off + k, bytes[k + 1] or 0xFF) end
    log(string.format("line %d: %d bytes", i, #bytes))
end
memory.write_u8(MB.INFO_LINES, #PANEL)
local seq = MB.show_info(1)
for _ = 1, 180 do emu.frameadvance() end
pcall(function() client.screenshot(WT .. "/patch/build/infostyle.png") end)
log("seq=" .. tostring(seq) .. "  screenshot: patch/build/infostyle.png")
log("RESULT: PASS")
flush()
client.exit()
