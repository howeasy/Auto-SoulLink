-- tools/polished_live/trade_port_probe.lua -- card 1 of docs/polished/TRADE.md s12: the repointed-special entry/return
-- probe, ONE EmuHawk, NO cable partner, NO SLink client. Launched by trade_port_probe.py (which stages the ROM, the
-- fixture and the symbols). The driver only RECORDS and presses native input; the verdict is the Python oracle.
-- POL_CASE: special-entry (trade receptionist, positive) | decline (B at the must-save prompt) | battle (room 2 control)
--           | clean (release ROM, same driver; the positive oracle must reject it).
-- SYNTH (disclosed, as explore.lua WHICH=B): wEventFlags+4 |= $02 (EVENT_GAVE_MYSTERY_EGG_TO_ELM) and the engine warp
-- (Script_warp bytes + MAPSETUP_WARP) to POKECENTER_2F (20:1) step (5,3) for trade, (9,3) for battle. Everything else is
-- native input. Milestones are driven by observed hits, never absolute frames. No console.log per frame.
local L = dofile(os.getenv("SLINK_ROOT") .. "/tools/polished_live/pol_lib.lua")
local fmt = string.format
local CASE = os.getenv("POL_CASE") or "special-entry"
local BATTLE = CASE == "battle"
client.speedmode(400)
L.log(fmt("[probe] case %s boot frame %d rom %s", CASE, emu.framecount(), gameinfo.getromhash()))

local trace = {}
local function dump()
    local f = assert(io.open(L.RUN .. "/trace.json", "w"))
    f:write(L.json.encode(trace))
    f:close()
end
local function finish(tag) dump() L.log(fmt("[probe] %d trace events", #trace)) L.finish(tag) end
local function die(why)
    L.check(why, false)
    L.log(fmt("[probe] DIE state: PC %04X SP %04X bank %02X scriptmode %d running %d", emu.getregister("PC"),
              emu.getregister("SP"), L.rombank(), L.rw("wScriptMode"), L.rw("wScriptRunning")))
    pcall(client.screenshot, L.RUN .. "/die.png")
    dump()
    L.finish("aborted")
end
local FRAME_CAP = tonumber(os.getenv("POL_FRAME_CAP")) or 12000
event.onframeend(function()
    if emu.framecount() > FRAME_CAP then
        L.check("driver reached its hard frame cap", false, "frame " .. emu.framecount())
        dump()
        L.finish("probe hard-cap")
    end
end)

-- ── one recorder for every event: the register/WRAM/HRAM state the oracle needs ────────────────────────────────
local S = L.SYM
local function hram(name) return L.bus(S[name][2]) end
local last_event_frame = 0
local function snap(kind, extra)
    local sp = emu.getregister("SP")
    local stk = {}
    for i = 0, 11 do stk[#stk + 1] = L.bus((sp + i) & 0xFFFF) end
    local e = {
        ord = #trace + 1, frame = emu.framecount(), kind = kind, pc = emu.getregister("PC"), sp = sp,
        bank = L.rombank(), room = L.rw("wChosenCableClubRoom"), var = hram("hScriptVar"),
        sbank = hram("hScriptBank"), spos = hram("hScriptPos") | (L.bus(S.hScriptPos[2] + 1) << 8),
        vblank = hram("hVBlank"), link = L.rw("wLinkMode"), running = L.rw("wScriptRunning"),
        stack = L.rw("wScriptStackSize"), grp = L.rw("wMapGroup"), num = L.rw("wMapNumber"),
        x = L.rw("wXCoord"), y = L.rw("wYCoord"), cursor = L.rw("wMenuCursorY"), stk = L.hex(stk),
    }
    if extra then for k, v in pairs(extra) do e[k] = v end end
    trace[#trace + 1] = e
    last_event_frame = e.frame
    return e
end
local function rec(kind) return function(matched) if matched then snap(kind) end end end

local gsb_n, reached_7616, reached_7689 = 0, false, false
local function install()
    L.hook("SlinkTradeWaitGate", rec("wait_gate"))
    L.hook("SlinkTradeTimeoutGate", rec("timeout_gate"))
    L.hook("SlinkTradeEntry", rec("stub"))
    L.hook("Special_WaitForLinkedFriend", rec("orig_wait"))
    L.hook("Special_WaitForLinkedFriend.done", rec("orig_wait_done"))
    L.hook("Special_CheckLinkTimeout", rec("orig_timeout"))
    L.hook("PerformLinkChecks", rec("perform_link_checks"))
    L.hook("Special_TryQuickSave", rec("try_quicksave"))
    L.hook("WaitForOtherPlayerToExit", rec("wait_exit"))
    L.hook("YesNoBox", rec("yesno"))
    L.hook("NoYesBox", rec("noyes"))
    L.hook("Script_endtext", rec("endtext"))
    -- the `ret` instructions (ROM bytes C9, checked by the runner): the gate/quick-save RETURN, var and room as left
    L.hook_at("wait_ret", 0x7E, 0x440B, rec("wait_ret"))
    L.hook_at("timeout_ret", 0x7E, 0x4426, rec("timeout_ret"))
    L.hook_at("quicksave_ret", 0x0A, 0x4E59, rec("quicksave_ret"))
    -- the interpreter: GetScriptByte entry = the cursor about to be read (the redirect target is script DATA)
    L.hook("GetScriptByte", function(matched)
        if not matched then return end
        if gsb_n >= 400 then return end
        gsb_n = gsb_n + 1
        local e = snap("gsb")
        if e.sbank == 0x24 and e.spos == 0x7616 then reached_7616 = true end
        if e.sbank == 0x24 and e.spos == 0x7689 then reached_7689 = true end   -- .DidNotSave
    end)
end

-- ── boot, SYNTH, warp ──────────────────────────────────────────────────────────────────────────────────────────
for _, name in ipairs({"OWPlayerInput", "SetInitialOptions.joypad_loop"}) do L.hook(name) end   -- BEFORE to_overworld
if not L.to_overworld(24, 3, 60, 8000, "continue") then die("CONTINUE did not reach ROUTE_29") end

local function warp(group, number, x, y)
    L.ww("wMapGroup", 0, group) L.ww("wMapNumber", 0, number) L.ww("wXCoord", 0, x) L.ww("wYCoord", 0, y)
    L.ww("wDefaultSpawnpoint", 0, 0xFF)
    memory.write_u8(S.hMapEntryMethod[2], 0xF1, "System Bus")  -- MAPSETUP_WARP
    L.ww("wMapStatus", 0, 1)
end
local ev = L.rw("wEventFlags", 4)
L.ww("wEventFlags", 4, ev | 0x02)
L.log(fmt("[probe] SYNTH wEventFlags+4 %02X -> %02X (EVENT_GAVE_MYSTERY_EGG_TO_ELM)", ev, L.rw("wEventFlags", 4)))
local px = BATTLE and 9 or 5
warp(20, 1, px, 3)
L.log(fmt("[probe] SYNTH engine warp -> POKECENTER_2F (20:1) step (%d,3)", px))
if not L.to_overworld(20, 1, 60, 3000, "warp-pc2f") then die("MAPSETUP_WARP to POKECENTER_2F did not land") end
L.check("POKECENTER_2F header loaded (8x4)", L.rw("wMapWidth") == 8 and L.rw("wMapHeight") == 4)
L.check(fmt("standing at (%d,3)", px), L.rw("wXCoord") == px and L.rw("wYCoord") == 3,
        fmt("(%d,%d)", L.rw("wXCoord"), L.rw("wYCoord")))
L.idle(60)
install()
for _ = 1, 6 do L.frame({Up = true}) end   -- face the receptionist (blocked: the NPC is at (px,2))
L.idle(10)

-- ── phase 1: talk until the first YES/NO box, then A until the script reaches DoTradeOrBattle (24:7616) ────────────
local t0 = emu.framecount()
while (L.hits.YesNoBox or 0) < 1 do
    if emu.framecount() - t0 > 900 then die("the receptionist script never opened its first YES/NO box") end
    L.pulse("A")
end
local f1 = emu.framecount()
while not reached_7616 do
    if emu.framecount() - f1 > 400 then die("the first prompt was not answered YES (24:7616 never read)") end
    L.pulse("A")
end
snap("answer", {btn = "A", which = 1})
L.log(fmt("[probe] first prompt answered YES at frame %d; DoTradeOrBattle reached", emu.framecount()))

-- ── phase 2 ───────────────────────────────────────────────────────────────────────────────────────────────────
local function script_idle() return L.rw("wScriptRunning") == 0 and L.ow_idle() end
-- wait for cond(); `nudge` allows ONE A pulse per 480 event-free frames (disclosed as a trace event)
local function wait_for(cond, bound, why, nudge)
    local f0 = emu.framecount()
    while not cond() do
        if emu.framecount() - f0 > bound then die(why) end
        if nudge and emu.framecount() - math.max(last_event_frame, f0) > 480 and not script_idle() then
            snap("nudge")
            for _ = 1, 3 do L.frame({A = true}) end
            last_event_frame = emu.framecount()
        end
        L.frame()
    end
end
local function hit_since(name, f) return L.after(name, f) end

if CASE == "special-entry" or CASE == "decline" then
    -- "Before opening the link, you must save your game." scrolls (cont/para): A advances it. A stops the moment the
    -- 2nd YES/NO box opens, so no stray A can answer it (the decline case needs B there).
    local fq = emu.framecount()
    while (L.hits.YesNoBox or 0) < 2 do
        if emu.framecount() - fq > 1500 then die("the must-save YES/NO box (2nd) never opened") end
        L.pulse("A")
    end
    L.idle(24)                                     -- the menu is up and reads input
    local f2 = emu.framecount()
    if CASE == "decline" then
        snap("answer", {btn = "B", which = 2})
        while not reached_7689 do
            if emu.framecount() - f2 > 600 then die("B on the must-save prompt never reached .DidNotSave (24:7689)") end
            L.pulse("B")
        end
        wait_for(script_idle, 2400, "the decline path never ended the script", true)
    else
        snap("answer", {btn = "A", which = 2})
        while (L.hits.Special_TryQuickSave or 0) < 1 do
            if emu.framecount() - f2 > 600 then die("YES on the must-save prompt never entered Special_TryQuickSave") end
            L.pulse("A")
        end
        -- Link_SaveGame may ask NoYesBox ("another save file", cursor starts on NO): read it, never assume A = YES
        local f3 = emu.framecount()
        local answered = false
        while (L.hits.SlinkTradeTimeoutGate or 0) < 1 do
            if emu.framecount() - f3 > 1500 then die("the quick-save never reached the Timeout gate") end
            if not answered and (L.hits.NoYesBox or 0) >= 1 then
                answered = true
                L.idle(24)
                for _ = 1, 3 do L.frame({Down = true}) end
                L.idle(8)
                snap("answer", {btn = "Down+A", which = "noyes"})
                for _ = 1, 3 do L.frame({A = true}) end
            end
            L.frame()
        end
        wait_for(script_idle, 2400, "the script did not end after the Timeout gate (no endtext?)", false)
    end
else
    -- battle / clean: the original wait runs; budget from ITS entry = 900 frames (measured ~513), then the script ends
    wait_for(function() return L.hits.Special_WaitForLinkedFriend and L.hits.Special_WaitForLinkedFriend >= 1 end,
             600, "the original Special_WaitForLinkedFriend never ran", true)
    local fw = L.hit.Special_WaitForLinkedFriend
    wait_for(function() return (L.hits["Special_WaitForLinkedFriend.done"] or 0) >= 1 end, 900 + 60,
             "the original wait did not finish within its 900-frame budget (TIMEOUT)", false)
    snap("orig_wait_span", {frames = L.hit["Special_WaitForLinkedFriend.done"] - fw})
    wait_for(script_idle, 1500, "the script did not end after the original wait", true)
end

-- ── end state, then the bounded Down ────────────────────────────────────────────────────────────────────────────
L.idle(40)
snap("final")
snap("move_start")
local y0 = L.rw("wYCoord")
for i = 1, 48 do
    L.frame({Down = true})
    if i >= 8 and L.rw("wYCoord") ~= y0 then break end
end
L.idle(24)
snap("move_end")
finish("trade-port-probe " .. CASE)
