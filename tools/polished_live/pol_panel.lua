-- pol-panel: LIVE check of the SLink PANEL behind the Phone card's virtual contact (Stage 2).
-- DEV evidence. Boots the same warp fixture as pol-phone (CONTINUE, native; the fixture sits on
-- ROUTE_29, reached by the engine's own warp -- POL_POSMODE=warp, no bare position pokes).
--
-- SYNTH writes, each logged and disclosed:
--   * wPokegearFlags = $87  (Pokegear + map/radio/phone cards obtained)  -- as in pol-phone
--   * wPhoneList     = 00 00 00 00 00 (no native contact, so the virtual SLink row is row 0)
-- Everything else is scripted native input. Probes only read.
--
-- WHO PUBLISHES THE PAGES: a scripted mailbox writer in THIS driver (L.on_frame), not a real
-- SLinkServer. It speaks the shared GB panel protocol verbatim -- watch PANEL_STATE (+9) for
-- AWAIT, write the page's charmap codes into wSlinkPanelText with SLINK_PANEL_STRIDE, publish
-- PANEL_PAGES (+11), then PANEL_STATE = STAGED (+9) last. So what this run proves is the ROM
-- half (SlinkPanel, the PrintText render, paging, the close) against a host that obeys the ABI.
local L = dofile(os.getenv("SLINK_ROOT") .. "/tools/polished_live/pol_lib.lua")
local fmt = string.format
local J = L.json
local CM = dofile(L.ROOT .. "/data/games/polished_crystal/charmap.lua").glyphs
local ENC = dofile(L.ROOT .. "/data/games/polished_crystal/charmap.lua").encoding
local ARROW = 240
L.log("[panel] step 1: libraries loaded")
client.speedmode(400)
L.log(fmt("[panel] boot frame %d rom %s", emu.framecount(), gameinfo.getromhash()))

for _, n in ipairs({"OWPlayerInput", "StartMenu", "PokeGear", "PokegearPhoneContactSubmenu",
                    "SlinkPhone_CallGate", "MakePhoneCallFromPokegear", "SlinkPanel", "YesNoBox"}) do
    L.hook(n)
end
L.log("[panel] step 2: boot logged")
local function write(path, s) local f = assert(io.open(path, "w")) f:write(s) f:close() end
local ev = {pages = {}}

-- ── the mailbox contract, read off the generated profile so nothing is hardcoded ──────────
local PROF = J.decode(L.slurp(L.ROOT .. "/data/games/polished_crystal/profile.json"))
L.log("[panel] step 3: hooks + write audit installed")
local PAN = PROF.titles.polished.overlay.panel
local OFF_STATE, OFF_PAGE, OFF_PAGES, OFF_CAPS = 9, 10, 11, 8
local AWAIT, STAGED = 1, 2
local MB_LO = L.woff("wSlinkMailbox", 0)
local MB_HI = L.woff("wSlinkMailboxEnd", 0) - 1
local TEXT = L.woff("wSlinkPanelText", 0)
L.log(fmt("[panel] step 4: geometry base=$%X span $%X..$%X lines=%d stride=%d term=$%02X",
          TEXT, MB_LO, MB_HI, PAN.lines, PAN.stride, PAN.terminator))

-- every byte this driver writes, audited against the mailbox span (the "wrap memory.write_*" check)
local AUDIT = {n = 0, lo = 0x7fffffff, hi = -1, outside = {}, seen = {}}
local raw_write = memory.write_u8
-- C5 audits the PANEL's writes only. The SYNTH setup below writes wPokegearFlags and wPhoneList
-- on purpose, outside the mailbox, so the audit is armed after it and reset. (Round 10: `wb` used
-- raw_write and therefore bypassed this wrapper entirely, so C5 would have reported "0 writes" and
-- passed VACUOUSLY -- the check was measuring nothing.)
AUDIT.on = false
memory.write_u8 = function(a, v, d)
    if AUDIT.on then
        AUDIT.n = AUDIT.n + 1
        if a < AUDIT.lo then AUDIT.lo = a end
        if a > AUDIT.hi then AUDIT.hi = a end
        if a < MB_LO or a > MB_HI then AUDIT.outside[#AUDIT.outside + 1] = fmt("%X", a) end
        -- the address list, capped: 68 panel writes, so a dump can be read in full
        if #AUDIT.seen < 80 then AUDIT.seen[#AUDIT.seen + 1] = fmt("%X", a) end
    end
    return raw_write(a, v, d)
end
--- Every panel write goes THROUGH the audited wrapper; nothing may bypass it.
--- Count and range-check HERE, not by wrapping memory.write_u8: assigning to that binding does
--- not stick in BizHawk (round 11 measured n=0 with the wrapper in place), so a wrapper-based audit
--- reports a clean run while seeing nothing. This is the only path a panel write takes.
local function wb(addr, v)
    if AUDIT.on then
        AUDIT.n = AUDIT.n + 1
        if addr < AUDIT.lo then AUDIT.lo = addr end
        if addr > AUDIT.hi then AUDIT.hi = addr end
        if addr < MB_LO or addr > MB_HI then AUDIT.outside[#AUDIT.outside + 1] = fmt("%X", addr) end
        if #AUDIT.seen < 80 then AUDIT.seen[#AUDIT.seen + 1] = fmt("%X", addr) end
    end
    return raw_write(addr, v, "WRAM")
end

-- ── the pages this host publishes ────────────────────────────────────────────────────────
L.log("[panel] step 5: writer closed over")
local PAGES = {
    {"SOUL LINK", "PARTNER: RED"},
    {"PAIRS 2/3", "BADGES 4/8"},
}
local function encode(line)
    local out = {}
    for i = 1, PAN.line_max do
        local ch = line:sub(i, i)
        out[i] = (ch ~= "" and type(ENC[ch]) == "number") and ENC[ch] or 0x7F
    end
    out[PAN.line_max + 1] = PAN.terminator
    return out
end
local staged_at, staged_page, staged_count = nil, nil, 0
-- NOTE (round 5 bisect): installing L.on_frame BEFORE to_overworld stalls the boot --
-- 8002 frames, never reaching the overworld. With it installed afterwards the same
-- driver reaches the Phone card in ~1000 frames. pol_panel.lua:writer() is therefore
-- called AFTER the boot, never at load.
local stage_frame_before_input = nil
local presses = 0
local function press(btn, settle) presses = presses + 1 for _ = 1, 2 do L.frame({[btn] = true}) end L.idle(settle or 24) end
local function writer()
    local st = L.rw("wSlinkMailbox", OFF_STATE)
    if st ~= AWAIT then staged_at = nil return end
    if staged_at then return end                    -- one stage per AWAIT edge, never per frame
    local page = L.rw("wSlinkMailbox", OFF_PAGE) or 0
    if page >= #PAGES then page = #PAGES - 1 end
    local lines = PAGES[page + 1]
    for i = 0, PAN.lines - 1 do
        local bytes = encode(lines[i + 1] or "")
        for c = 1, PAN.stride do wb(TEXT + i * PAN.stride + c - 1, bytes[c]) end
    end
    wb(L.woff("wSlinkMailbox", OFF_PAGES), #PAGES)
    wb(L.woff("wSlinkMailbox", OFF_STATE), STAGED)  -- published last, exactly like gb_panel
    staged_at, staged_page, staged_count = emu.framecount(), page + 1, staged_count + 1
    if staged_count == 1 then stage_frame_before_input = presses end
end
L.on_frame = nil

-- ── helpers (pol_phone/drv/phone.lua, same shapes) ──────────────────────────────────────
local function wait(cond, bound, what)
    local f0 = emu.framecount()
    while not cond() do
        if emu.framecount() - f0 > bound then L.die(what) return end
        L.frame()
    end
end
local function row(y)
    local s = {}
    for i, b in ipairs(L.wbytes("wTilemap", y * 20, 20)) do s[i] = CM[b] or "?" end
    return table.concat(s)
end
local function rows(a, b) local o = {} for y = a, b do o[#o + 1] = fmt("%02d|%s|", y, row(y)) end return o end
local function screen() return table.concat(rows(0, 17), "\n") end
-- The textbox's own border glyphs, so a row can be compared as TEXT rather than as a picture.
local BORDER = { ["│"] = 1, ["┃"] = 1, ["┌"] = 1, ["┐"] = 1, ["└"] = 1, ["┘"] = 1,
                 ["─"] = 1, ["━"] = 1 }
--- One tilemap row as trimmed text: border glyphs removed, edges trimmed.
local function clean_row(y)
    local t = row(y)
    for ch in pairs(BORDER) do t = t:gsub(ch, " ") end
    return (t:gsub("^%s+", ""):gsub("%s+$", ""))
end
--- The textbox rows, each on its own. A line the ROM wrapped across a row boundary is two
--- entries here, which is what made the old joined-substring matcher miss "PARTNER: RED".
local function box_rows() local o = {} for y = 12, 17 do o[#o + 1] = clean_row(y) end return o end
--- The box as one string with rows joined by a space: a phrase laid out on ONE row still matches
--- contiguously, and a phrase the ROM wrapped is still findable.
local function box() return table.concat(box_rows(), " ") end
--- Rows with a column ruler, so a dump says which column a glyph is in (round 8: "PAR" landed at
--- row 15 columns 17-19 and the dump had no way to show it).
local function ruler(a, b)
    local tens, ones = "     ", "     "
    for i = 1, 20 do
        tens = tens .. tostring(math.floor((i - 1) / 10) % 10)
        ones = ones .. tostring((i - 1) % 10)
    end
    return tens .. "   (tens)\n" .. ones .. "   (cols)\n" .. table.concat(rows(a, b), "\n")
end
local function plist() return L.hex(L.wbytes("wPhoneList", 0, 5)) end
local function state() return L.rw("wJumptableIndex") end
local function cur() return L.rw("wPokegearPhoneCursorPosition"), L.rw("wPokegearPhoneScrollPosition") end
local function shot(name) client.screenshot(fmt("%s/%s.png", L.RUN, name)) end

L.log("[panel] step 6: helpers defined, entering boot")
-- ── drive to the Phone card ──────────────────────────────────────────────────────────────
-- (the round-2 boot probe that pulsed A/B here MOVED THE MAIN MENU off CONTINUE and was
-- the real cause of the boot-gate abort; it must never press anything here)
L.log("[panel] step 7: calling to_overworld (writer NOT yet installed)")
if not L.to_overworld(24, 3, 60, 8000, "continue") then L.die("CONTINUE did not reach ROUTE_29") end
L.on_frame = writer
L.log("[panel] step 8: overworld reached; mailbox writer installed")
local flags0 = L.rw("wPokegearFlags")
raw_write(L.woff("wPokegearFlags", 0), 0x87, "WRAM")
local list0 = plist()
raw_write(L.woff("wPhoneList", 0), 0, "WRAM")
for i = 1, 4 do raw_write(L.woff("wPhoneList", i), 0, "WRAM") end
-- the SYNTH setup above wrote outside the mailbox on purpose; from here on every host-side panel write is audited
AUDIT.n, AUDIT.lo, AUDIT.hi, AUDIT.outside, AUDIT.seen = 0, 0x7fffffff, -1, {}, {}
AUDIT.on = true
L.log(fmt("[panel] SYNTH wPokegearFlags %02X -> 87, wPhoneList %s -> 0000000000 (SLink is row 0)",
          flags0, list0))

local function open_phone()
    local s0 = emu.framecount()
    while not L.after("StartMenu", s0) do
        if emu.framecount() - s0 > 600 then L.die("START menu never opened") end
        L.pulse("Start")
    end
    L.idle(30)
    local r
    for i = 1, L.rw("wMenuItemsList") do if L.rw("wMenuItemsList", i) == 7 then r = i end end
    if not r then L.die("no POKEGEAR row in the START menu") end
    local s1 = emu.framecount()
    while not L.after("PokeGear", s1) do
        if emu.framecount() - s1 > 1200 then L.die("PokeGear never ran") end
        L.pulse(L.rw("wMenuCursorY") == r and "A" or "Down")
    end
    local c0 = emu.framecount()
    while not (L.rw("wPokegearCard") == 2 and state() == 0x0a) do
        if emu.framecount() - c0 > 1200 then L.die("the Phone card never reached its joypad state") end
        L.pulse(L.rw("wPokegearCard") < 2 and "Right" or nil)
    end
    L.idle(40)
end

open_phone()
-- C1: the caps byte advertises the panel and nothing else
local caps = L.rw("wSlinkMailbox", OFF_CAPS)
ev.caps = caps
-- C1: the caps byte advertises the panel and nothing else.
-- The span is a property of the SYMBOLS' ADDRESSES, not of what is stored at them: L.rw reads the
-- memory CONTENTS of a symbol, so End - Start was a difference of two mailbox bytes.
local SPAN = L.SYM.wSlinkMailboxEnd[2] - L.SYM.wSlinkMailbox[2]
L.check("C1 PANEL cap advertised (integrated overlay: caps=07 = PANEL|SFX|SFX_NOTIFY)", caps == 0x07, fmt("%02X", caps))
L.check("C1 mailbox span is the overlay's own 69 bytes (symbol addresses, not contents)",
        SPAN == 69, fmt("$%X..$%X = %d", L.SYM.wSlinkMailbox[2], L.SYM.wSlinkMailboxEnd[2], SPAN))

-- the list has exactly the SLink row
for _ = 1, 40 do local c, s = cur() if c + s == 0 then break end press("Up", 10) end
local c0, s0 = cur()
L.check("C0 the SLink row is row 0 and is labelled by the overlay",
        row(4):find("SLink:", 1, true) ~= nil, row(4))

-- ── A on the SLink row -> Call -> the PANEL ─────────────────────────────────────────────
local calls0, gate0, panel0 = L.hits.MakePhoneCallFromPokegear, L.hits.SlinkPhone_CallGate, L.hits.SlinkPanel
local caller0, plist_before = L.rw("wCurCaller"), plist()
press("A", 30)                                     -- contact submenu
L.check("C0 A opened the contact submenu", L.hits.PokegearPhoneContactSubmenu >= 1)
local presses_before_call = presses
press("A", 10)                                     -- Call
wait(function() return L.hits.SlinkPhone_CallGate > gate0 end, 300, "Call never reached SlinkPhone_CallGate")
wait(function() return L.hits.SlinkPanel > panel0 end, 300, "the gate never entered SlinkPanel")

-- The ROM prints the fallback, publishes AWAIT and the host answers, all before it waits on a
-- KEY (the stage-2 fix: the fallback no longer ends in `prompt`). No press to dismiss.
wait(function() return staged_count >= 1 end, 400, "the host never saw an AWAIT")
L.idle(4)
L.check("C2 AWAIT was published with NO EXTRA keypress (the fallback no longer prompts)",
        -- presses_before_call is captured BEFORE the Call press, so staging on presses_before_call+1
        -- means the Call A itself and nothing after it: the lease was served without a dead press.
        stage_frame_before_input == presses_before_call + 1,
        fmt("presses when AWAIT was staged: %s; before Call: %d (Call itself = +1, expected %d)",
            tostring(stage_frame_before_input), presses_before_call, presses_before_call + 1))
-- Do NOT judge the render on the first frame after staging: the ROM prints the page through the
-- text engine and the tilemap is pushed on its own schedule. Poll, and dump the screen at the
-- AWAIT and 120 frames later so a miss says WHICH screen we were looking at.
L.log("[panel] --- textbox AT AWAIT (column ruler) ---")
L.log(ruler(12, 17))
local seen_frame, seen = nil, nil
for _ = 1, 30 do
    local b = box()
    if b:find("SOUL LINK", 1, true) then seen_frame, seen = emu.framecount(), b break end
    L.idle(10)
end
L.log(seen_frame and fmt("[panel] box text appeared at frame %d", seen_frame)
      or fmt("[panel] box text NEVER appeared within 300 frames (last read at frame %d)", emu.framecount()))
L.idle(120)
L.log("[panel] --- textbox 120 frames later (column ruler) ---")
L.log(ruler(12, 17))
shot("panel_2_page1")
local p1 = box()
ev.page1 = p1
local br1 = box_rows()
local on_row = function(s) for _, r in ipairs(br1) do if r:find(s, 1, true) then return r end end end
L.check("C2 page 1 rendered: SOUL LINK on one row", on_row("SOUL LINK") ~= nil, table.concat(br1, " / "))
L.check("C2 page 1 rendered: PARTNER: RED on ONE row (row-aware)",
        on_row("PARTNER: RED") ~= nil, table.concat(br1, " / "))
L.check("C2 both lines present (joined form)", p1:find("SOUL LINK", 1, true) ~= nil
        and p1:find("PARTNER: RED", 1, true) ~= nil, p1)
L.check("C2 the ROM's fallback second line is gone", p1:find("NO CLIENT", 1, true) == nil, p1)
L.check("C2 PANEL_PAGE/PAGES published by the host",
        L.rw("wSlinkMailbox", OFF_PAGES) == 2 and L.rw("wSlinkMailbox", OFF_PAGE) == 0,
        fmt("page %d of %d", L.rw("wSlinkMailbox", OFF_PAGE), L.rw("wSlinkMailbox", OFF_PAGES)))

-- ── A advances to page 2 ─────────────────────────────────────────────────────────────────
press("A", 10)                                     -- advance: page 2's fallback + AWAIT, no keypress needed
wait(function() return staged_count >= 2 end, 400, "the host never saw the page-2 AWAIT")
L.idle(4)
local p2 = box()
shot("panel_3_page2")
ev.page2 = p2
local br2 = box_rows()
local on_row2 = function(s) for _, r in ipairs(br2) do if r:find(s, 1, true) then return r end end end
L.check("C3 A advanced to page 2: PAIRS 2/3 on one row", on_row2("PAIRS 2/3") ~= nil, table.concat(br2, " / "))
L.check("C3 A advanced to page 2: BADGES 4/8 on one row", on_row2("BADGES 4/8") ~= nil, table.concat(br2, " / "))
L.check("C3 PANEL_PAGE advanced to 1", L.rw("wSlinkMailbox", OFF_PAGE) == 1, L.rw("wSlinkMailbox", OFF_PAGE))

-- ── B closes back to the Phone list ──────────────────────────────────────────────────────
press("B", 10)
wait(function() return state() == 0x0a end, 400, "B did not return to PHONEJOYPAD")
L.idle(40)
local back = screen()
shot("panel_4_back")
local c1, s1 = cur()
L.check("C4 back on the Phone list with the cursor/scroll intact", c1 == c0 and s1 == s0,
        fmt("%d/%d -> %d/%d", c0, s0, c1, s1))
L.check("C4 the SLink row is still row 0", row(4):find("SLink:", 1, true) ~= nil, row(4))
L.check("C4 no phone call placed (MakePhoneCallFromPokegear never entered)",
        L.hits.MakePhoneCallFromPokegear == calls0)
L.check("C4 wCurCaller untouched", L.rw("wCurCaller") == caller0, fmt("%02X", L.rw("wCurCaller")))
L.check("C4 wPhoneList untouched by the panel", plist() == plist_before, plist())
L.check("C4 the panel cleared PANEL_STATE on close", L.rw("wSlinkMailbox", OFF_STATE) == 0,
        L.rw("wSlinkMailbox", OFF_STATE))
ev.back = back

-- ── write audit ──────────────────────────────────────────────────────────────────────────
-- The whole block is wrapped so a Lua error here cannot silently swallow the run: the harness
-- records result.txt but not BizHawk's console, so an uncaught error used to look exactly like
-- "the driver stopped". Round 11: this was reached only after the flow stalled at the last C4
-- line, with no RESULT: at all. L.finish stays OUTSIDE the pcall (it ends by raising, on purpose),
-- so a RESULT: line is always written.
local okC5, errC5 = pcall(function()
    L.log("[panel] C5 BLOCK ENTER")
    local hex = function(v) return fmt("%X", v % 0x10000) end   -- safe for 0 and the sentinels
    L.log(fmt("[panel] audit n=%d lo=%s hi=%s outside=%d", AUDIT.n, tostring(AUDIT.lo), tostring(AUDIT.hi),
              #AUDIT.outside))
    ev.audit = {n = AUDIT.n, lo = hex(AUDIT.lo), hi = hex(AUDIT.hi),
                mailbox = fmt("%X..%X", MB_LO, MB_HI), outside = AUDIT.outside,
                writes = AUDIT.seen}
    L.log("[panel] C5 BLOCK ev.audit built")
    L.check("C5 every PANEL write is inside the mailbox span", #AUDIT.outside == 0,
            fmt("%d panel writes, %s..%s vs mailbox %s; outside: %s", AUDIT.n,
                AUDIT.n > 0 and ev.audit.lo or "-", AUDIT.n > 0 and ev.audit.hi or "-",
                ev.audit.mailbox, #AUDIT.outside == 0 and "none" or table.concat(AUDIT.outside, ",")))
    -- The vacuous-pass guard: an audit that SAW nothing must not read as a clean run.
    L.check("C5 the audit actually SAW writes (not a vacuous pass)", AUDIT.n > 0, AUDIT.n)
    L.log("[panel] C5 CHECKS DONE, ev.hits/panel.json next")
    ev.hits = L.hits
    write(L.RUN .. "/panel.json", J.encode(ev))
    L.log("[panel] C5 write addresses: " .. table.concat(AUDIT.seen, " "))
    L.log("[panel] C5 BLOCK OK")
end)
if not okC5 then
    L.log("[panel] C5 BLOCK ERROR: " .. tostring(errC5))
    L.check("C5 audit block ran without a Lua error", false, tostring(errC5))
end
L.finish("pol-panel")
