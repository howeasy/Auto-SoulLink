-- duo_gen3_main.lua — two-instance live harness for the NEW Gen 3 client (lua/gen3/*) on FRLG.
--
-- tools/e2e_duo.py (game "gen3_frlg") generates patch/build/duo_<lane>_{a,b}.lua, which sets
-- SLINK_HOST/PORT/PLAYER plus SLINK_DUO and dofiles this file. The production client is built
-- by RUNNING lua/gen3/run.lua itself -- the same admission, Entry.build, connector, HUD and
-- event.onframeend loop a player gets -- so nothing here can drift from the bootstrap. The
-- driver only tees three seams before run.lua binds them:
--   * event.on_bus_exec: the `save` site's hook also dumps the whole SRAM (flash) domain,
--     INSIDE the callback, once the signal validated and the capture contract holds (R0 == 1,
--     R5 == SAVE_NORMAL); the `faint` site's hook logs ENGINE_FAINT_SITE when it validates;
--   * connector.send: every non-tick event as "TX <event> <key|-> <json>";
--   * the session's handle_command: every command as "RX <cmd> key=<key> ...".
-- The battery boots through CONTINUE (lua/tests/gen3_boot_check.lua), then the scenario runs
-- as straight-line code: every frame it advances, run.lua's onframeend runs client:frame_end()
-- exactly as in production.
--
-- Scenarios are per-file modules, lua/tests/duo/scenario_<prefix><name>.lua (prefix from the
-- GAMES row, "gen3_"; name = the scenario key without its "_gen3" suffix), each returning
-- function(ctx) -> pass, msg. Inputs are ordinary buttons only; game facts come from the pack
-- (write_checkpoint.json, profile.json), pret's symbol file for the title
-- (data/gen3/pret/poke<title>.sym) and the BFS-verified paths of gen3_scripted_play.lua.
-- Receipt protocol (what e2e_duo.py parses): "MYKEY <slot> <key>", TX/RX lines as above,
-- SAVE_WITNESS/SAVE_WITNESS_DUMP lines, scenario markers, and a final "RESULT: PASS|FAIL (why)".
local D = SLINK_DUO
assert(D and D.wt and D.player and D.scenario and D.result, "SLINK_DUO not configured (run via tools/e2e_duo.py)")
-- P5 (card C5-5): "gen3_rr" is the battery-boot RR row (tools/e2e_duo.py GAMES), sharing
-- this driver with "gen3_frlg" -- everything below that reads a per-title pack/checkpoint path
-- or symbol table branches on D.title ("radical_red" vs firered/leafgreen), not on D.game.
assert(D.game == "gen3_frlg" or D.game == "gen3_rr",
       "duo_gen3_main only serves game gen3_frlg/gen3_rr, got " .. tostring(D.game))
assert(D.title, "SLINK_DUO.title missing (the GAMES row's sides)")

local ROOT = D.wt
SLINK_ROOT = ROOT          -- gen3_boot_check.lua / gen3_scripted_play.lua locate the tree by it
package.path = ROOT .. "/lua/?.lua;" .. package.path
local fmt = string.format
local phase = D.phase or "initial"

-- ── receipt, finish, console tee ─────────────────────────────────────────────────────────
local logf = io.open(D.result, "w")
local _console_log = console.log
local finished = false
local function log(s)
    _console_log("[duo" .. D.player:upper() .. "] " .. tostring(s))
    if logf then logf:write(tostring(s) .. "\n"); logf:flush() end
end
local FINISHED = "slink-duo-finished"
local function finish(pass, msg)
    if finished then error(FINISHED, 0) end
    finished = true
    joypad.set({})
    log("RESULT: " .. (pass and "PASS" or "FAIL") .. (msg and (" (" .. msg .. ")") or ""))
    if logf then logf:close(); logf = nil end
    client.exit()             -- async: the error below stops this script from driving further
    error(FINISHED, 0)
end
local writes, refused = 0, nil
-- one-shot hooks on a client write line, by reason (ctx.on_write): they run INSIDE the client's
-- frame end, i.e. in the very frame the write landed, so what they read is the state it saw
local write_hooks, write_hook_errors, write_lines = {}, {}, {}
console.log = function(s)
    local text = tostring(s)
    _console_log(text)
    if text:find("[SLink-gen3] write ", 1, true) then
        writes = writes + 1
        local reason, addr, len, wframe = text:match("%[SLink%-gen3%] write (%S+) 0x(%x+) %+(%d+) frame (%d+)")
        if reason then
            write_lines[#write_lines + 1] = { reason = reason, address = tonumber(addr, 16),
                                              len = tonumber(len), frame = tonumber(wframe) }
        end
        reason = reason or text:match("%[SLink%-gen3%] write (%S+) ")
        local hook = reason and write_hooks[reason]
        if hook then
            write_hooks[reason] = nil
            local hok, herr = pcall(hook, text)
            if not hok then write_hook_errors[#write_hook_errors + 1] = tostring(herr) end
        end
    end
    if text:find("[SLink-gen3] refused", 1, true) then refused = text end
    if logf then logf:write("[client] " .. text .. "\n"); logf:flush() end
    -- The shared helpers (gen3_boot_check / gen3_scripted_play) end a run with
    -- G.finish(false, why) -> "[gen3] RESULT: FAIL why": that is this run's verdict too.
    local helper = text:match("^%[gen3%] RESULT: FAIL ?(.*)$")
    if helper and not finished then finish(false, "helper: " .. helper) end
end

-- Every harness press, counted (ctx.inputs): the P+H carrier's "no input between the commit and
-- the KO" is checked on this AND on the engine's own gMain.heldKeysRaw. Wrapped before any helper
-- loads, so a helper that captures joypad.set captures this one.
local presses, raw_joypad_set = 0, joypad.set
joypad.set = function(buttons, ...)
    if type(buttons) == "table" then
        for _, v in pairs(buttons) do if v == true then presses = presses + 1; break end end
    end
    return raw_joypad_set(buttons, ...)
end
log(fmt("duo instance %s scenario=%s phase=%s title=%s attempt=%d", D.player, D.scenario, phase,
        D.title, D.attempt or 1))
pcall(memory.usememorydomain, "System Bus")
pcall(function() client.speedmode(D.speed or 1600) end)
-- Rendering off (W23 EMU-SPEED): oracles read RAM, and client.screenshot still captures the core's
-- frame under invisibleemulation (checked on 2.11.1/mGBA). SLINK_EMU_VISIBLE=1 keeps the window live.
pcall(function() client.invisibleemulation(not D.visible and os.getenv("SLINK_EMU_VISIBLE") ~= "1") end)

-- pcall every load-time dofile (card C4-LG2): an unprotected dofile that errors (e.g.
-- gen3_scripted_play.lua raising for a title Syms/the profile pack does not recognize) died
-- after this file's first log line and never wrote a RESULT, so e2e_duo.py's harness had nothing
-- to read but a 120s MYKEY timeout -- the real reason was on stderr, not in the receipt. finish()
-- (defined above) already writes RESULT and exits cleanly, so route every one of these through it.
local function load_or_die(rel, label)
    local ok, mod = pcall(dofile, ROOT .. rel)
    if not ok then finish(false, "load: " .. label .. ": " .. tostring(mod)) end
    return mod
end

-- Any OTHER load-time step -- a JSON read, the .sym scan, the symbol asserts, the boot call --
-- goes through the same discipline (card C4-GUARD): a failure there raised out of the main chunk,
-- so the driver stopped after its first log line and wrote no RESULT, and the harness could only
-- report a missing MYKEY. Live witness: the save_then_write_gen3 red receipt (C4-STW-DIAG), both
-- instances silent after "TCP connected" with one EmuHawk left holding a .NET exception dialog.
local function guard(label, fn)
    local ok, value = pcall(fn)
    if not ok then finish(false, "load: " .. label .. ": " .. tostring(value)) end
    return value
end

local JSON = load_or_die("/lua/json_codec.lua", "json_codec.lua")
local G = load_or_die("/lua/tests/gen3_boot_check.lua", "gen3_boot_check.lua")
SLINK_GEN3_TITLE = D.title   -- the scripted helpers read their per-title addresses from this (C4-LG)
local SP = load_or_die("/lua/tests/gen3_scripted_play.lua", "gen3_scripted_play.lua")   -- helpers only; never run()
local Reads = load_or_die("/lua/gen3/reads.lua", "reads.lua")
local play = SP.play

local function read_json(rel)
    local f = assert(io.open(ROOT .. "/" .. rel, "rb"), "cannot read " .. rel)
    local raw = f:read("a"); f:close()
    return assert(JSON.decode(raw), "malformed " .. rel)
end
local title = D.title
-- P5: radical_red's pack lives under data/games/gen3_rr, not gen3_frlg's (different checkpoint
-- predicate and RAM/derived offsets -- RR's 25-box layout in particular, gen3_codec commit
-- 62887460). Every OTHER read in this file goes through `cp`/`profile`, so this one branch is
-- the whole of the pack selection.
local pack = title == "radical_red" and "gen3_rr" or "gen3_frlg"
local cp_rel = "data/games/" .. pack .. "/write_checkpoint.json"
local cp = guard("checkpoint for title '" .. title .. "' in " .. cp_rel, function()
    local doc = read_json(cp_rel)
    return assert(doc[title], cp_rel .. " has no entry for title '" .. title .. "'")
end)
local profile_rel = "data/games/" .. pack .. "/profile.json"
local profile = guard("profile for title '" .. title .. "' in " .. profile_rel, function()
    local doc = read_json(profile_rel)
    return assert(doc.titles and doc.titles[title], profile_rel .. " has no titles." .. title)
end)
G.title, G.budget = title, 5000000
local function bus_bytes(addr, n)
    local out = {}
    for i = 1, n do out[i] = memory.read_u8(addr + i - 1, "System Bus") end
    return out
end
local reader = guard("reader (reads.lua) for title '" .. title .. "'", function()
    return Reads.new(profile, {
        read_u8 = function(a) return memory.read_u8(a, "System Bus") end,
        read_u16 = function(a) return memory.read_u16_le(a, "System Bus") end,
        read_u32 = function(a) return memory.read_u32_le(a, "System Bus") end,
        read_bytes = bus_bytes,
    }, cp.pointers)
end)

-- pret's symbols for THIS title (the first definition of a name: HandleInputChooseAction is also
-- a static in the Oak/old-man and Pokedude controllers, which sort after the player's).
local SYMS = { "gBattlerControllerFuncs", "HandleInputChooseAction", "HandleInputChooseMove",
               "gBattlescriptCurrInstr", "gBattleScripting", "gBattleCommunication",
               "gBattleControllerExecFlags", "gMoveToLearn", "BattleScript_AskToLearnMove",
               "BattleScript_ForgotAndLearnedNewMove",
               "gActionSelectionCursor", "gMoveSelectionCursor", "gBattleMons", "gBattlerPartyIndexes",
               "gBattleOutcome", "gMain", "gTasks", "gPartyMenu", "CB2_UpdatePartyMenu",
               "Task_HandleChooseMonInput", "Task_HandleSelectionMenuInput",
               "Task_ReturnToChooseMonAfterText", "Task_DepositMenu", "Task_WithdrawMon",
               "CB2_BagMenuRun", "Task_BagMenu_HandleInput", "Task_AnimateWin0v", "gPaletteFade",
               "Task_LinkupAwaitConnection", "sGlobalScriptContext",
               "CableClub_EventScript_WelcomeToCableClub", "CableClub_EventScript_UnusedWelcomeToCableClub",
               "CableClub_EventScript_UnionRoomAdapterNotConnected",
               "CableClub_EventScript_WirelessClubAttendant", "gSpecialVar_Result", "gObjectEvents",
               "gLinkCallback", "sLinkOpen", "LinkCB_RequestPlayerDataExchange", "sSaveDialogCB", "gSaveBlock1Ptr",
               "SaveDialogCB_ReturnSuccess", "task50_save_game", "Task_StartMenuHandleInput",
               -- C4-SAVE-ROWS (ctx.peek): the START menu/save dialog statics (start_menu.c:63-72,
               -- new_game.c:37)
               "sSaveDialogDelay", "gDifferentSaveFile", "SaveDialogCB_AskSaveHandleInput",
               "SaveDialogCB_AskOverwriteOrReplacePreviousFileHandleInput", "sStartMenuCursorPos",
               "sNumStartMenuItems", "sStartMenuOrder",
               -- P+H carrier (scenario_gen3_linked_faint_active.lua): the engine oracles O1-O7 and
               -- the hand-off (rr_active_faint_parity_scope §3.2; RR reuses FR's, byte-proven there)
               "gActiveBattler", "gBattleResults", "gStatuses3", "PlayerBufferExecCompleted",
               "PlayerBufferRunCommand" }
--- radical_red's symbol table (G5-RR-ORACLES-3 F4): ONLY proven sources -- gen3_title_syms'
--- radical_red values (ROM byte anchors / cited notes), the RR profile's ram block, and the RR
--- pack's own words (predicates / witnesses: symbol + base address; save pointers; hand-off). No pokefirered.sym fallback: RR is a hack of FR, not a
--- pret tree, and an FR address that CFRU moved would be read silently. A symbol no source proves
--- is ABSENT, and reading it raises by name (fail closed at the point of use, not at load, so a
--- row that never touches, say, the Cable Club words still runs). Self-contained (no upvalues)
--- so tests run this exact body over the committed RR files.
local function rr_symbols(want, proven, entries, ram, pack)
    local out = {}
    for name, e in pairs(entries) do
        local v = proven[name]
        if v and want[e.symbol] then out[e.symbol] = v - (e.offset or 0) - (e.thumb and 1 or 0) end
    end
    local RAM = { gBattleMons = "BATTLE_MONS_ADDR", gBattlerPartyIndexes = "BATTLER_PARTY_INDEXES_ADDR",
                  gBattleControllerExecFlags = "BATTLE_CONTROLLER_EXEC_FLAGS_ADDR",
                  gBattleCommunication = "BATTLE_COMM_ADDR", gStatuses3 = "STATUS3_ADDR",
                  gBattleOutcome = "BATTLE_OUTCOME_ADDR", gBattleResults = "BATTLE_RESULTS_ADDR",
                  gTasks = "TASKS_BASE_ADDR" }
    for sym, field in pairs(RAM) do
        if want[sym] and out[sym] == nil and type(ram[field]) == "number" then out[sym] = ram[field] end
    end
    for _, group in ipairs({ pack.predicates or {}, pack.witnesses or {} }) do
        for _, p in pairs(group) do
            if type(p) == "table" and want[p.symbol] and out[p.symbol] == nil and type(p.address) == "number" then
                out[p.symbol] = p.address
            end
        end
    end
    for sym, p in pairs(pack.pointers or {}) do
        if want[sym] and out[sym] == nil and type(p.address) == "number" then out[sym] = p.address end
    end
    local handoff = pack.battle and pack.battle.handoff
    if handoff and handoff.value_symbol and want[handoff.value_symbol] and out[handoff.value_symbol] == nil then
        out[handoff.value_symbol] = handoff.value - 1
    end
    return setmetatable(out, { __index = function(_, k)
        error("symbol " .. tostring(k) .. " is unproven for radical_red (no gen3_title_syms entry, RR "
              .. "profile field or RR pack word; no pokefirered.sym fallback)", 2)
    end })
end
local S = {}
if title == "radical_red" then
    local want = {}
    for _, n in ipairs(SYMS) do want[n] = true end
    S = guard("radical_red symbols (gen3_title_syms + RR profile + RR pack)", function()
        local Titles = dofile(ROOT .. "/lua/tests/gen3_title_syms.lua")
        return rr_symbols(want, Titles.for_title(title), Titles.entries, profile.ram, cp)
    end)
else
    local want = {}
    for _, n in ipairs(SYMS) do want[n] = true end
    local path = ROOT .. "/data/gen3/pret/poke" .. title .. ".sym"
    guard("pret symbols in " .. path, function()
        local fh = assert(io.open(path, "r"), "cannot read " .. path)
        for line in fh:lines() do
            local addr, name = line:match("^(%x+) %a %x+ (%S+)")
            if name and want[name] and not S[name] then S[name] = tonumber(addr, 16) end
        end
        fh:close()
        -- One source of truth with the scripted-play helpers (G5-RR-ORACLES-2, OMP review of
        -- 410d9578): every symbol lua/tests/gen3_title_syms.lua proves for this title replaces the
        -- .sym read -- on radical_red that is the ROM-proven value, not pokefirered.sym's. Its
        -- values are FINAL (offset added, Thumb bit set when `thumb`), S holds the bare symbol.
        local Titles = dofile(ROOT .. "/lua/tests/gen3_title_syms.lua")
        local proven = Titles.for_title(title)
        for name, e in pairs(Titles.entries) do
            local v = proven[name]
            if v and want[e.symbol] then
                S[e.symbol] = v - (e.offset or 0) - (e.thumb and 1 or 0)
            end
        end
        local missing = {}
        for _, n in ipairs(SYMS) do if not S[n] then missing[#missing + 1] = n end end
        assert(#missing == 0,
               "pret symbol(s) missing from " .. path .. ": " .. table.concat(missing, ", "))
    end)
end

-- ── seams teed before run.lua binds them ─────────────────────────────────────────────────
local seen_tx, seen_rx, tx, rx = {}, {}, {}, {}
local witness_saves, wrong_save_hud = 0, false
--- The receipt lines one save's witness produces, IN EMISSION ORDER: the DUMP first, then (RR)
--- the EXT copy bound to the same ordinal -- tools/e2e_duo.py _gen3_final_ext requires the final
--- EXT to follow the final DUMP. Self-contained (no upvalues) so tests/unit/test_e2e_duo_gen3.py
--- runs this exact body under lupa and feeds its output to the Python consumer.
local function witness_receipt_lines(rel, bytes, saves, frame, counter, erel, ext_size)
    local lines = { string.format("SAVE_WITNESS_DUMP path=%s bytes=%d saves=%d frame=%d counter=%d",
                                  rel, bytes, saves, frame, counter) }
    if erel then
        lines[#lines + 1] = string.format("SAVE_WITNESS_EXT path=%s bytes=%d saves=%d",
                                          erel, ext_size, saves)
    end
    return lines
end
local function dump_witness()
    witness_saves = witness_saves + 1
    -- repo-relative: ROOT contains a space, and a `path=` value with one cannot be parsed back
    local rel = fmt("patch/build/e2e_%s_%s_%d_witness.bin", D.scenario, D.player, D.attempt or 1)
    local dom = assert(G.flash_domain(), "no flash memory domain")
    local parts = {}
    for off = 0, 0x20000 - 4, 4 do parts[#parts + 1] = string.pack("<I4", memory.read_u32_le(off, dom)) end
    local blob = table.concat(parts)
    local wf = assert(io.open(ROOT .. "/" .. rel, "wb"), "cannot open " .. rel)
    wf:write(blob)          -- overwritten on every save: the file is this attempt's FINAL save
    wf:close()
    -- RR: the live EWRAM range the extension writer copies verbatim into sectors 30-31
    -- (D.ext_addr/D.ext_size from gen3_codec via the stub), read at the same save boundary, so
    -- the harness can prove the saved extension is THIS state (Codex C4-6b finding 4).
    local erel
    if D.ext_addr and D.ext_size then
        local ext = {}
        for off = 0, D.ext_size - 4, 4 do
            ext[#ext + 1] = string.pack("<I4", memory.read_u32_le(D.ext_addr + off, "System Bus"))
        end
        erel = rel:gsub("%.bin$", "_ext.bin")
        local ef = assert(io.open(ROOT .. "/" .. erel, "wb"), "cannot open " .. erel)
        ef:write(table.concat(ext))
        ef:close()
    end
    -- both files are on disk before either line is logged: a failed copy leaves no DUMP line
    -- for this ordinal (SAVE_WITNESS_DUMP_FAIL instead), never a DUMP without its EXT
    for _, line in ipairs(witness_receipt_lines(rel, #blob, witness_saves, emu.framecount(),
                                                G.save_counter(dom), erel, D.ext_size)) do
        log(line)
    end
end
-- "Validated" is observable only as the signal queue growing by one entry of the site's kind
-- (lua/gen3/signals.lua fire(): every rejection returns before the append).
local function validated(before, kind)
    local sigs = SLINK_GEN3_CLIENT and SLINK_GEN3_CLIENT.signals
    if not sigs then return nil, "no-signals-instance" end
    if #sigs.pending ~= before + 1 then return nil, fmt("pending-%d-to-%d", before, #sigs.pending) end
    local sig = sigs.pending[#sigs.pending]
    if sig.kind ~= kind then return nil, "kind-" .. tostring(sig.kind) end
    return sig
end
local function pending_count()
    local sigs = SLINK_GEN3_CLIENT and SLINK_GEN3_CLIENT.signals
    return sigs and #sigs.pending or 0
end
local faint_sites = {}
local function faint_site_now()
    local slot = memory.read_u16_le(S.gBattlerPartyIndexes, "System Bus")
    local base = reader.party_base()
    return { frame = emu.framecount(), active = memory.read_u8(S.gActiveBattler, "System Bus"),
             battler0_slot = slot, battle_hp = memory.read_u16_le(S.gBattleMons + 0x28, "System Bus"),
             party_hp = base and memory.read_u16_le(base + slot * 100 + 0x56, "System Bus") or -1,
             counter = memory.read_u8(S.gBattleResults, "System Bus") }
end
local raw_on_bus_exec = event.on_bus_exec
event.on_bus_exec = function(fn, addr, name, ...)
    local tag, fire = tostring(name or ""), fn
    if tag:find("SLink%-gen3%-save$") then
        fn = function(...)
            local before = pending_count()
            fire(...)
            local sig, why = validated(before, "save")
            -- the site's capture contract (engine_signals.json): a full save returned OK
            if sig and not (sig.point and sig.point.R0 == 1 and sig.point.R5 == 0) then
                sig, why = nil, fmt("r0-%s-r5-%s", tostring(sig.point and sig.point.R0),
                                    tostring(sig.point and sig.point.R5))
            end
            if not sig then log("SAVE_WITNESS_DUMP_SKIPPED why=" .. why) return end
            local ok, err = pcall(dump_witness)
            if not ok then log("SAVE_WITNESS_DUMP_FAIL " .. tostring(err)) end
        end
    elseif tag:find("SLink%-gen3%-faint$") then
        fn = function(...)
            local before = pending_count()
            fire(...)
            if validated(before, "faint") then
                -- read INSIDE the callback: at Cmd_tryfaintmon +0x11C the counter store is done and
                -- datahpupdate's party write has completed (scripts wait on the exec flags)
                local f = faint_site_now()
                faint_sites[#faint_sites + 1] = f
                log(fmt("ENGINE_FAINT_SITE frame=%d active=%d battler0_slot=%d battle_hp=%d party_hp=%d counter=%d",
                        f.frame, f.active, f.battler0_slot, f.battle_hp, f.party_hp, f.counter))
            end
        end
    end
    return raw_on_bus_exec(fn, addr, name, ...)
end

local C = require("connector")
local raw_send = C.send
C.send = function(line)
    local ok, msg = pcall(JSON.decode, line)
    local name = ok and type(msg) == "table" and type(msg.event) == "string" and msg.event or "?"
    seen_tx[name] = (seen_tx[name] or 0) + 1
    if name ~= "tick" then
        local key = ok and type(msg) == "table" and type(msg.key) == "string" and msg.key or "-"
        tx[#tx + 1] = { event = name, key = key, msg = ok and msg or nil }
        log(fmt("TX %s %s %s", name, key, name == "hello" and line:sub(1, 200) or line))
    end
    return raw_send(line)
end

-- ── the production client: lua/gen3/run.lua, unmodified ──────────────────────────────────
SLINK_GEN3_CLIENT = nil
-- Capture the REAL built policy through the harness composition seam; run.lua normally drops
-- Entry.build's second return. Restore dofile even if startup fails. No production code changed.
-- Always captured: ctx.center_state asks the client's own safety instance for its CPU verdict.
local battle_parts
local original_dofile = dofile
local wants_routes = D.battle_window_case or D.active_faint_case == "trainer"
do
    dofile = function(path)
        local value = original_dofile(path)
        if path == ROOT .. "/lua/gen3/entry.lua" then
            local build = value.build
            value.build = function(...)
                local client, parts = build(...)
                battle_parts = parts
                return client, parts
            end
        end
        return value
    end
end
local okrun, errrun = pcall(dofile, ROOT .. "/lua/gen3/run.lua")
dofile = original_dofile
if not okrun then finish(false, "lua/gen3/run.lua raised: " .. tostring(errrun)) end
local session = SLINK_GEN3_CLIENT
if not session then finish(false, "run.lua built no client: " .. tostring(refused or "no reason logged")) end
local raw_handle = session.handle_command
session.handle_command = function(self, cmd)
    local c = type(cmd) == "table" and type(cmd.cmd) == "string" and cmd.cmd or "?"
    local key = type(cmd) == "table" and type(cmd.key) == "string" and cmd.key or nil
    local text = type(cmd) == "table" and type(cmd.text) == "string" and cmd.text or nil
    seen_rx[c] = (seen_rx[c] or 0) + 1
    if c ~= "noop" then
        rx[#rx + 1] = { cmd = c, key = key }
        log("RX " .. c .. (key and (" key=" .. key) or "") .. (text and (" text=" .. text) or ""))
    end
    if c == "hud_show" and text and text:find("WRONG SAVE", 1, true) then
        wrong_save_hud = true
        log("WRONG_SAVE_HUD " .. text)
    end
    return raw_handle(self, cmd)
end
log(fmt("client built by lua/gen3/run.lua: title=%s player=%s -> %s:%s", title, D.player,
        tostring(SLINK_HOST), tostring(SLINK_PORT)))

-- ── context ──────────────────────────────────────────────────────────────────────────────
local ctx = { D = D, player = D.player, phase = phase, log = log, fmt = fmt, G = G, SP = SP,
              play = play, cp = cp, reader = reader, sym = S, title = title, session = session,
              finished = FINISHED, emulator = emu }

function ctx.frames(n) for _ = 1, n do emu.frameadvance() end end
--- pred() each frame until truthy (its value) or `secs` of wall clock pass (nil, logged).
function ctx.wait_until(pred, secs, what)
    local deadline = os.time() + (secs or 60)
    while os.time() <= deadline do
        local v = pred()
        if v then return v end
        emu.frameadvance()
    end
    -- which tasks held the game (card C4-6h: the Union Room tasks in a Center 1F kept the
    -- checkpoint shut and nothing said so); covers wait_sent/wait_received/mash_until too
    local dumped, dump = pcall(SP.PC.dump)
    log("TIMEOUT waiting for " .. tostring(what) .. " [" .. (dumped and tostring(dump)
                                                            or "dump failed: " .. tostring(dump)) .. "]")
    return nil
end
local function go_lines()
    local f = io.open(D.go_file, "r")
    if not f then return nil end
    local out = {}
    for l in f:lines() do out[#out + 1] = l end
    f:close()
    return out
end
function ctx.go_has(marker)
    for _, l in ipairs(go_lines() or {}) do if l == marker then return true end end
    return false
end
-- --idle-jitter, the Gen 1 standard's retry lever: BizHawk is deterministic, and FRLG's VBlank
-- advances the RNG once per frame (pret src/main.c:412 Random() in VBlankIntr), so idle frames
-- are what make a retried attempt a different roll. They go AFTER the scenario's GO, before its
-- first input: idled before the scenario, a GO that arrives later absorbs them and the retry
-- replays the same roll (Codex review of ad9669b1). The harness writes the count (+37 per
-- attempt) and checks the echo (e2e_duo.py jitter_problems); a scenario phase that never waits
-- for GO echoes applied=0 at its end.
local jitter_logged = false
local function idle_jitter(apply)
    if jitter_logged then return end
    jitter_logged = true
    local requested, applied = D.idle_jitter or 0, 0
    if apply then for _ = 1, requested do emu.frameadvance(); applied = applied + 1 end end
    log(fmt("JITTER requested=%d applied=%d attempt=%d", requested, applied, D.attempt or 1))
end
function ctx.wait_go(marker, secs)
    marker = marker or "GO"
    local ok = ctx.wait_until(function() return ctx.go_has(marker) end, secs or 1800, "go-file " .. marker)
    if ok and marker == "GO" then idle_jitter(true) end
    return ok
end
function ctx.linked()
    for _, l in ipairs(go_lines() or {}) do
        local k = l:match("^LINKED (%S+)$")
        if k then return k end
    end
end
--- The partner's whole result file once it holds a RESULT line, else nil.
function ctx.partner_result()
    local f = io.open(D.partner_result, "r")
    if not f then return nil end
    local text = f:read("a"); f:close()
    return text:find("RESULT:", 1, true) and text or nil
end
function ctx.partner_done() return ctx.partner_result() ~= nil end

function ctx.party()
    local mons = reader.read_party()
    if not mons then return nil end
    local out = {}
    for _, m in ipairs(mons) do
        out[#out + 1] = { slot = m.slot, key = reader.key(m), hp = m.hp, max_hp = m.max_hp,
                          species = m.species, level = m.level, experience = m.experience, status = m.status,
                          moves = m.moves, pp = m.pp }
    end
    return out
end
--- The party entry for `key`, or nil when it is not SEEN -- absent OR unreadable. Use it only to
--- confirm presence; absence claims go through ctx.locate / ctx.observe_*.
function ctx.find(key)
    for _, m in ipairs(ctx.party() or {}) do if m.key == key then return m end end
end
function ctx.balls()
    local b = reader.read_balls()
    return b and b.ball_count or -1
end
function ctx.sent(event, key)
    local n = 0
    for _, e in ipairs(tx) do if e.event == event and (key == nil or e.key == key) then n = n + 1 end end
    return n
end
function ctx.received(cmd, key)
    local n = 0
    for _, c in ipairs(rx) do if c.cmd == cmd and (key == nil or c.key == key) then n = n + 1 end end
    return n
end
--- The last event of this name the client sent, decoded (nil if none).
function ctx.last_sent(event)
    for i = #tx, 1, -1 do if tx[i].event == event then return tx[i].msg end end
end
--- pred() each frame, pressing `button` on a 16-frame cadence while it is false.
function ctx.mash_until(pred, secs, button)
    local n = 0
    return ctx.wait_until(function()
        local v = pred()
        if v then return v end
        n = n + 1
        if n % 16 == 0 then joypad.set({ [button or "A"] = true }) end
    end, secs, "mashing " .. tostring(button or "A"))
end
function ctx.wait_sent(event, key, secs)
    return ctx.wait_until(function() return ctx.sent(event, key) > 0 end, secs or 300,
                          "TX " .. event .. " " .. tostring(key))
end
function ctx.wait_received(cmd, key, secs)
    return ctx.wait_until(function() return ctx.received(cmd, key) > 0 end, secs or 300,
                          "RX " .. cmd .. " " .. tostring(key))
end
function ctx.writes() return writes end
--- Run fn(line) once, in the frame of the client's next `write <reason>` line.
function ctx.on_write(reason, fn) write_hooks[reason] = fn end
function ctx.write_hook_errors() return write_hook_errors end
--- Every client write line so far, parsed: { reason, address, len, frame } (entry.lua's format).
function ctx.write_lines() return write_lines end
--- The deferred queue's entry for exactly (cmd, key), and the gate's hold reason (lua/core/
--- deferred.lua Deferred:pending, e.g. "forbidden state: script_context_status"); nil when that
--- entry is not queued. The head/why alone is not enough: an unrelated queued command would
--- carry the same reason (Codex review of d199da32, the wrong-head case).
--- Self-contained (no upvalues) so tests/unit/test_e2e_duo_gen3.py runs this exact body.
local function queued_entry(items, why, cmd, key)
    for i, q in ipairs(items) do
        if q.cmd == cmd and q.key == key then return { index = i, why = why } end
    end
end
function ctx.queued(cmd, key)
    local _, why = session.deferred:pending(emu.framecount())
    return queued_entry(session.deferred.items, why, cmd, key)
end
--- Bytes the client's write sink has ATTEMPTED (lua/gen3/writes.lua `attempted`, counted before
--- each external write, via the deferred executor's write_count): independent of log lines.
function ctx.attempted() return session.deferred.exec.write_count() end
--- The party region (count byte + six records) and the PC storage (current box + every box's
--- records), as byte strings: a before/after compare needs no write log at all.
--- The PC storage bytes a before/after compare covers, as {address, length} spans. Vanilla: pret
--- include/pokemon_storage_system.h struct PokemonStorage -- currentBox, the boxes (from
--- BOX_DATA_OFFSET), boxNames[n][9], boxWallpapers[n] -- one span, 0x83D0 on FR/LG. RR (CFRU,
--- G5-RR-BATTERY-2: reconnect_gen3 died on the vanilla formula, the RR pack has no
--- MONS_PER_BOX/BOX_DATA_OFFSET): the pack's CFRU_BOX_BASES, each 30 * COMPRESSED_MON_SIZE (58),
--- the exact regions lua/gen3/reads.lua read_box decodes. Self-contained (no upvalues).
local function storage_spans(d, store, mons_per_box_default)
    local per_box = d.MONS_PER_BOX or mons_per_box_default
    if d.CFRU_COMPRESSED_BOX then
        local out = {}
        for _, base in ipairs(d.CFRU_BOX_BASES) do out[#out + 1] = { base, per_box * d.COMPRESSED_MON_SIZE } end
        return out
    end
    local n = d.BOXES_PER_STORE
    return { { store, d.BOX_DATA_OFFSET + n * per_box * 80 + n * 9 + n } }
end
function ctx.mutable_bytes()
    local function bytes(addr, n)
        local out = {}
        for i = 1, n do out[i] = string.char(memory.read_u8(addr + i - 1, "System Bus")) end
        return table.concat(out)
    end
    local party = bytes(profile.ram.PARTY_COUNT_ADDR, 1) .. bytes(profile.ram.PARTY_BASE, 6 * Reads.PARTY_MON_SIZE)
    local store = memory.read_u32_le(cp.pointers.gPokemonStoragePtr.address, "System Bus")
    local parts = {}
    for _, span in ipairs(storage_spans(profile.derived, store, Reads.MONS_PER_BOX)) do
        parts[#parts + 1] = bytes(span[1], span[2])
    end
    return party, table.concat(parts)
end
function ctx.party_base() return reader.party_base() end
--- A script variable (0x4000..), read through gSaveBlock1Ptr + SB1_VARS_OFFSET (pret
--- include/global.h SaveBlock1 vars; the pack's derived offset). nil while the pointer is insane.
function ctx.game_var(id)
    local sb1 = memory.read_u32_le(cp.pointers.gSaveBlock1Ptr.address, "System Bus")
    if sb1 < 0x02000000 or sb1 >= 0x02040000 then return nil end
    return memory.read_u16_le(sb1 + profile.derived.SB1_VARS_OFFSET + (id - 0x4000) * 2, "System Bus")
end
function ctx.wrong_save_hud() return wrong_save_hud end
--- The session's held in-battle write for `key` (lua/core/session.lua battle_pending), if any.
function ctx.battle_hold(key)
    for _, e in ipairs(session.battle_pending or {}) do if e.key == key then return e end end
end
function ctx.in_battle() return play.in_battle(cp) end
function ctx.on_field() return play.on_field(cp) end
--- pcall that lets a finished run keep finishing (a helper's FAIL is already the verdict).
function ctx.try(fn, ...)
    local ok, err = pcall(fn, ...)
    if not ok and err == FINISHED then error(FINISHED, 0) end
    return ok, err
end

-- HP-0 watcher: runs after run.lua's frame_end on every frame, whatever the driver is doing, so
-- a write the driver was not polling for (a deferred force_faint landing mid-settle, one frame
-- before its memorialize moves the record out) is still witnessed. One line per key, the first
-- time it is seen alive and then at HP 0.
ctx.hp0_tag = "FORCED_HP0"
local alive, hp0 = {}, {}
-- ctx.watch(fn): fn() runs at the end of EVERY frame, after run.lua's frame end (so after any
-- client write of that frame), whatever the driver is doing -- including inside a helper that
-- advances frames itself (playlib's incidental battle, which can settle a whole whiteout and its
-- heal script before it returns: live gen3_lgfr whiteout_gen3 r6). A truthy return removes it.
local watchers, watcher_names = {}, {}
--- `name` labels the watcher in a WATCHER_ERROR line (default: its defining source:line).
function ctx.watch(fn, name)
    if not name then
        local info = debug and debug.getinfo and debug.getinfo(fn, "S")
        name = info and (tostring(info.short_src) .. ":" .. tostring(info.linedefined)) or "?"
    end
    watchers[#watchers + 1] = fn
    watcher_names[#watchers] = name
end
-- Plaintext fields only (PID/OTID at +0/+4, hp at +0x56 of struct Pokemon, pret
-- include/pokemon.h): no per-frame decryption.
--- One pass over the watchers: a truthy return removes one; so does an error, but never silently
--- (R1 L4): report(name, err) runs first, so the FAIL it causes downstream ("no ... witnessed") is
--- diagnosable from the receipt. Self-contained (no upvalues) so tests run this exact body.
local function run_watchers(list, names, report)
    for i = #list, 1, -1 do
        local ok, done = pcall(list[i])
        if not ok then report(tostring(names[i]), tostring(done)) end
        if not ok or done then table.remove(list, i); table.remove(names, i) end
    end
end
local PARTY_COUNT_ADDR, MON_SIZE, HP_OFF = profile.ram.PARTY_COUNT_ADDR, Reads.PARTY_MON_SIZE, 0x56
event.onframeend(function()
    run_watchers(watchers, watcher_names, function(name, err)
        log(fmt("WATCHER_ERROR scenario=%s watcher=%s frame=%d err=%s", D.scenario, name, emu.framecount(), err))
    end)
    local count, base = memory.read_u8(PARTY_COUNT_ADDR, "System Bus"), reader.party_base()
    if not base or count > 6 then return end
    for slot = 0, count - 1 do
        local at = base + slot * MON_SIZE
        local k = fmt("%08X:%08X", memory.read_u32_le(at, "System Bus"), memory.read_u32_le(at + 4, "System Bus"))
        if memory.read_u16_le(at + HP_OFF, "System Bus") > 0 then
            alive[k] = true
        elseif alive[k] and not hp0[k] then
            local battling = play.in_battle(cp)
            local battler = battling and memory.read_u16_le(S.gBattlerPartyIndexes) == slot
            hp0[k] = { frame = emu.framecount(), in_battle = battling, battler = battler }
            log(fmt("%s %s frame=%d in_battle=%d battler=%d", ctx.hp0_tag, k, emu.framecount(),
                    battling and 1 or 0, battler and 1 or 0))
        end
    end
end, "SLink-duo-gen3-hp0")
function ctx.hp0(key) return hp0[key] end

--- Where `key` is, with each read's SUCCESS kept apart from its answer (Codex C4-6c finding 2).
--- Self-contained (no upvalues) so tests/unit/test_e2e_duo_gen3.py runs this exact body under
--- lupa. Returns { party = slot|false, box = "box:slot"|false } only when the party read AND every
--- one of the `box_count` box reads succeeded; otherwise nil, why -- UNKNOWN, never "absent". A
--- key in two party slots or two box slots is ambiguous, also nil.
local function locate_key(key, read_party, read_box, box_count, key_of)
    local party, pwhy = read_party()
    if not party then return nil, "party unreadable: " .. tostring(pwhy) end
    if type(box_count) ~= "number" or box_count < 1 then return nil, "no box count in the pack" end
    local at = { party = false, box = false }
    for _, m in ipairs(party) do
        if key_of(m) == key then
            if at.party then return nil, "key in two party slots" end
            at.party = m.slot
        end
    end
    for box = 0, box_count - 1 do
        local mons, bwhy = read_box(box)
        if not mons then return nil, "box " .. box .. " unreadable: " .. tostring(bwhy) end
        for _, m in ipairs(mons) do
            if m.has_species == 1 and key_of(m) == key then
                if at.box then return nil, "key in two box slots" end
                at.box = box .. ":" .. m.slot
            end
        end
    end
    return at
end
--- The two physical read-backs, decided from a COMPLETE location only: BOXED = absent from the
--- party AND in exactly one box slot; RETURNED = in the party AND in no box. Also self-contained.
local function observed(at, want)
    if not at then return nil end
    if want == "boxed" then return (at.party == false and at.box) or nil end
    return (at.party ~= false and at.box == false) and at or nil
end
function ctx.locate(key)
    return locate_key(key, reader.read_party, reader.read_box, profile.derived.BOXES_PER_STORE, reader.key)
end
--- The physical half of a deposit/withdraw ACK: an ACK on the wire is the client's word; these
--- read the cartridge, and an unreadable party or box is waited out, never taken as absence.
local function observe(key, want, marker, secs)
    local last_why
    local hit = ctx.wait_until(function()
        local at, why = ctx.locate(key)
        last_why = why or last_why
        return observed(at, want)
    end, secs or 60, marker .. " " .. key)
    if not hit and last_why then log(fmt("OBSERVE_UNKNOWN %s %s (%s)", marker, key, last_why)) end
    return hit
end
function ctx.observe_boxed(key, secs)
    local at = observe(key, "boxed", "BOXED_OBSERVED", secs)
    if at then log(fmt("BOXED_OBSERVED %s box=%s", key, at)) end
    return at
end
function ctx.observe_returned(key, secs)
    local at = observe(key, "returned", "RETURNED_OBSERVED", secs)
    if at then log(fmt("RETURNED_OBSERVED %s slot=%d", key, at.party)) end
    return at
end
--- gBattleResults.lastUsedMovePlayer (pret include/battle.h: +0x22), which HandleAction_UseMove
--- stamps with gCurrentMove as the engine starts EXECUTING a player move (pret src/battle_main.c
--- :4021-4022) and battle start resets to MOVE_NONE (:2316). Base address from the pack
--- (ram.BATTLE_RESULTS_ADDR, pinned for both packs); on RR the +0x22 layout is FR's, unverified.
function ctx.last_used_move_player()
    return memory.read_u16_le(profile.ram.BATTLE_RESULTS_ADDR + 0x22, "System Bus")
end
function ctx.battle_outcome() return memory.read_u8(S.gBattleOutcome) end

-- ── P+H engine oracles (scenario_gen3_linked_faint_active.lua) ─────────────────────────────
ctx.rr = title == "radical_red"
function ctx.inputs() return presses end
function ctx.press(buttons) joypad.set(buttons) end
function ctx.faint_sites() return faint_sites end
function ctx.peek_u8(addr) return memory.read_u8(addr, "System Bus") end
--- The hand-off words, from the carrier's symbol table S (FR/LG: pret's .sym; radical_red:
--- gen3_title_syms' ROM-proven values, docs/gen3/research/rr_harness_syms_2026-09-24.md -- never
--- the client's pack block this checks): the slot, the value the plan writes, and the
--- successor(s) PlayerBufferExecCompleted installs -- RR's CFRU hook may store its bit-24
--- alternative 0x090ACD8D instead (rr_active_faint_parity_scope §3.2 step 2).
ctx.handoff = { slot_addr = S.gBattlerControllerFuncs, from = S.PlayerBufferExecCompleted | 1,
                to = { S.PlayerBufferRunCommand | 1, ctx.rr and 0x090ACD8D or nil } }
--- The two HP words of party `slot` as battler 0 (pret pokemon.h: party hp +0x56, BattlePokemon
--- hp +0x28), as a set: no SLink write may touch either.
function ctx.hp_addrs(slot)
    local base = reader.party_base() or profile.ram.PARTY_BASE
    return { [base + slot * 100 + 0x56] = true, [S.gBattleMons + 0x28] = true }
end
--- One frame's engine reads for the carrier. gMain.heldKeysRaw +0x28 (pret include/main.h);
--- gBattleResults playerFaintCounter +0 / lastUsedMovePlayer +0x22 (include/battle.h); battler 0's
--- PP +0x24..+0x27 of BattlePokemon.
function ctx.engine_sample(slot)
    local function u8(a) return memory.read_u8(a, "System Bus") end
    local function u16(a) return memory.read_u16_le(a, "System Bus") end
    local function u32(a) return memory.read_u32_le(a, "System Bus") end
    local bm, base = S.gBattleMons, reader.party_base()
    return { frame = emu.framecount(), in_battle = play.in_battle(cp) and true or false,
             ctrl0 = u32(S.gBattlerControllerFuncs), exec = u32(S.gBattleControllerExecFlags),
             keys = u16(S.gMain + 0x28), battler0_slot = u16(S.gBattlerPartyIndexes),
             battle_hp = u16(bm + 0x28), pp = { u8(bm + 0x24), u8(bm + 0x25), u8(bm + 0x26), u8(bm + 0x27) },
             status3 = u32(S.gStatuses3), counter = u8(S.gBattleResults), last_move = u16(S.gBattleResults + 0x22),
             outcome = u8(S.gBattleOutcome), party_hp = base and u16(base + slot * 100 + 0x56) or -1 }
end
--- The client's own trade FSM phase (lua/gen3/client.lua st.trade_apply.phase), nil when idle.
function ctx.trade_phase()
    local t = session.state and session.state.trade_apply
    return t and t.phase or nil
end

-- ── battle input (pret battle_controller_player.c / party_menu.c, symbols above) ─────────
local B_OUTCOME_CAUGHT = 7        -- pret include/constants/battle.h
local ACTION_FIGHT, ACTION_BAG, ACTION_SWITCH, ACTION_RUN = 0, 1, 2, 3
local function ctrl0() return memory.read_u32_le(S.gBattlerControllerFuncs) end
local function action_menu_up() return ctrl0() == (S.HandleInputChooseAction | 1) end
local function move_menu_up() return ctrl0() == (S.HandleInputChooseMove | 1) end
local function party_menu_up() return memory.read_u32_le(S.gMain + 4) == (S.CB2_UpdatePartyMenu | 1) end
local function party_task(fn)
    for i = 0, 15 do
        local base = S.gTasks + i * 40                   -- sizeof(struct Task), include/task.h
        if memory.read_u8(base + 4) ~= 0 and memory.read_u32_le(base) == (fn | 1) then return true end
    end
    return false
end
function ctx.battler_slot() return memory.read_u16_le(S.gBattlerPartyIndexes) end
--- Where the global script context sits inside the script range [lo, hi): "scriptPtr" when its
--- next command is there, "stack[i]" when a CALLER there is waiting (a `callstd` msgbox runs in
--- the std script with the caller's return address stacked), else nil. pret include/script.h
--- struct ScriptContext: stackDepth +0, scriptPtr +8, stack[20] +12 (sGlobalScriptContext 0x74).
--- Self-contained (no upvalues) so tests/unit/test_e2e_duo_gen3.py runs this exact body.
local function script_at(read_u8, read_u32, base, lo, hi)
    local p = read_u32(base + 8)
    if p >= lo and p < hi then return "scriptPtr" end
    for i = 0, math.min(read_u8(base), 20) - 1 do
        local r = read_u32(base + 12 + 4 * i)
        if r >= lo and r < hi then return "stack[" .. i .. "]" end
    end
end
--- gSpecialVar_Result (VAR_RESULT) now. After `specialvar VAR_RESULT, IsWirelessAdapterConnected`
--- nothing in the no-adapter branches writes it until a multichoice/yesno does, so read while
--- parked in that branch's message it IS the special's return value.
function ctx.special_result() return memory.read_u16_le(S.gSpecialVar_Result, "System Bus") end
--- PRODUCT FINDING probe (live center_controls r9, fb255a05 -> f926a8b4): two overworld
--- checkpoint predicates test pointers pret never clears on a player's ordinary path.
---   link_callback: OpenLink sets gLinkCallback = LinkCB_RequestPlayerDataExchange (link.c:394);
---     only LinkMain2 with a connection ESTABLISHED runs (and so clears) it (:520-523, :1129-1133);
---     CloseLink (:419-426) leaves it. A cancelled no-partner Cable Club link leaves it set with
---     the link CLOSED (sLinkOpen FALSE, :424).
---   save_dialog_cb: sSaveDialogCB (start_menu.c:71) is assigned by every save-dialog step and
---     never reset to NULL; after ANY in-game save it rests on SaveDialogCB_ReturnSuccess.
--- Each is reported only when it is set while its real state is over: the link closed / no
--- save dialog task running. Self-contained (no upvalues) so tests run this exact body.
local function stale_predicates(read_u8, read_u32, s, task_live)
    local out = {}
    local cb = read_u32(s.gLinkCallback)
    if cb ~= 0 and read_u8(s.sLinkOpen) == 0 then
        out[#out + 1] = string.format("link_callback=0x%08X%s(sLinkOpen=0)", cb,
            cb == (s.LinkCB_RequestPlayerDataExchange | 1) and ":LinkCB_RequestPlayerDataExchange" or "")
    end
    local sd = read_u32(s.sSaveDialogCB)
    if sd ~= 0 and not task_live(s.task50_save_game) and not task_live(s.Task_StartMenuHandleInput) then
        out[#out + 1] = string.format("save_dialog_cb=0x%08X%s(no save dialog task)", sd,
            sd == (s.SaveDialogCB_ReturnSuccess | 1) and ":SaveDialogCB_ReturnSuccess" or "")
    end
    return out
end
function ctx.stale_predicates()
    return stale_predicates(function(a) return memory.read_u8(a, "System Bus") end,
                            function(a) return memory.read_u32_le(a, "System Bus") end, S,
                            function(fn) return party_task(fn) end)
end
--- script_at over the named script labels (SYMS), read now.
function ctx.script_at(label, next_label)
    return script_at(function(a) return memory.read_u8(a, "System Bus") end,
                     function(a) return memory.read_u32_le(a, "System Bus") end,
                     S.sGlobalScriptContext, S[label], S[next_label])
end
--- The player's object event (gObjectEvents slot 0). pret include/global.fieldmap.h struct
--- ObjectEvent: flags +0x00 (bit6 heldMovementActive, bit7 heldMovementFinished), +0x18
--- `u8 facingDirection:4; u8 movementDirection:4` -- GCC packs ARM bitfields LSB-first, so the
--- facing is the LOW nibble (1 down, 2 up, 3 left, 4 right; the RR object-event notes agree).
local FACING = { Down = 1, Up = 2, Left = 3, Right = 4 }
function ctx.facing() return memory.read_u8(S.gObjectEvents + 0x18, "System Bus") & 0x0F end
function ctx.player_idle()
    local f = memory.read_u8(S.gObjectEvents, "System Bus")
    return (f & 0x40) == 0 or (f & 0x80) ~= 0
end
--- Turn the player to `dir` and PROVE it: wait out any step still in flight (a follow returns
--- when the coordinates move, which is the START of the last step's walk), then tap `dir` until
--- the facing nibble reads it. Only for a blocked tile ahead (a counter): there a tap turns,
--- it cannot step. Live center_controls_gen3 r7 (fb255a05, FR and LG): the old single Up tap
--- landed inside the last Right step, was dropped, and A met the empty tile to the east.
function ctx.face(dir)
    local want = assert(FACING[dir], "no direction " .. tostring(dir))
    for _ = 1, 6 do
        for _ = 1, 60 do
            if ctx.player_idle() then break end
            ctx.frames(1)
        end
        if ctx.facing() == want then return true end
        G.tap(dir, 3, 20)
    end
    return ctx.facing() == want
end
--- Is the pret function `name` (one of SYMS) an active task right now?
function ctx.task_live(name) return party_task(assert(S[name], "no SYMS entry " .. name)) end
--- A pret static (one of SYMS) read now: `width` bytes (1/2/4) at S[name] + `offset`. Read-only;
--- a callback compares against S[fn] | 1 (Thumb).
function ctx.peek(name, width, offset)
    local a = assert(S[name], "no SYMS entry " .. name) + (offset or 0)
    if width == 4 then return memory.read_u32_le(a, "System Bus") end
    if width == 2 then return memory.read_u16_le(a, "System Bus") end
    return memory.read_u8(a, "System Bus")
end

--- Can the bag take a press? pret item_menu.c:1044-1049: Task_BagMenu_HandleInput returns
--- without reading input while gPaletteFade.active (bit 7 of byte +7, the checkpoint pack's
--- palette_fade_active predicate) or while Task_AnimateWin0v runs, and CB2_BagMenuRun is
--- installed (:501-502) BEFORE the open fade ends -- so "the bag is up" is not "the bag reads A".
--- Self-contained (no upvalues) so tests/unit/test_e2e_duo_gen3.py runs this exact body.
local function bag_input_ready(read_u32, read_u8, s)
    if read_u32(s.gMain + 4) ~= (s.CB2_BagMenuRun | 1) then return false end
    if (read_u8(s.gPaletteFade + 7) & 0x80) ~= 0 then return false end
    local input, animating = false, false
    for i = 0, 15 do
        local base = s.gTasks + i * 40                   -- sizeof(struct Task), include/task.h
        if read_u8(base + 4) ~= 0 then
            local fn = read_u32(base)
            if fn == (s.Task_BagMenu_HandleInput | 1) then input = true end
            if fn == (s.Task_AnimateWin0v | 1) then animating = true end
        end
    end
    return input and not animating
end
function ctx.bag_input_ready()
    return bag_input_ready(function(a) return memory.read_u32_le(a, "System Bus") end,
                           function(a) return memory.read_u8(a, "System Bus") end, S)
end
ctx.action_menu_up, ctx.party_menu_up = action_menu_up, party_menu_up

--- G4 item 2a (docs/gen3/G4_request_draft.md): the checkpoint state a write inside a Pokemon
--- Center is judged against -- every pack predicate's value (callback1/2, script/fade/lock,
--- gReceivedRemoteLinkPlayers as link_players_received, ...; "!" marks one off its expected
--- value) -- and the Union Room background tasks (C4-UR, 5ecfae3b: every Center 1F runs
--- CableClub_OnResume -> InitUnionRoom) that are NOT active. Self-contained (no upvalues) so
--- tests/unit/test_e2e_duo_gen3.py runs this exact body. read(address, width) -> integer.
local function center_predicates(cp, read, regs, parked_verdict)
    local t, active = cp.tasks, {}
    for i = 0, (t.count | 0) - 1 do
        local base = (t.address | 0) + i * (t.struct_size | 0)
        if read(base + (t.is_active_offset | 0), 1) ~= 0 then active[read(base + (t.func_offset | 0), 4)] = true end
    end
    local missing = {}
    for _, name in ipairs({ "Task_InitUnionRoom", "Task_SearchForChildOrParent", "Task_UnionRoomListen" }) do
        local fn = t.allowed_overworld_tasks[name]
        if not (fn and active[(fn | 0) | 1]) then missing[#missing + 1] = name end
    end
    local names, parts, bad = {}, {}, {}
    for name in pairs(cp.predicates) do names[#names + 1] = name end
    table.sort(names)
    for _, name in ipairs(names) do
        local p = cp.predicates[name]
        local v = read((p.address | 0) + ((p.offset or 0) | 0), (p.width or 1) | 0)
        if p.mask then v = v & (p.mask | 0) end
        parts[#parts + 1] = string.format("%s=0x%X%s", name, v, v == (p.expect | 0) and "" or "!")
        if v ~= (p.expect | 0) then bad[#bad + 1] = name end
    end
    -- the CPU clause is the product's own (lua/gen3/safety.lua "cpu", over the pack's cpu block
    -- incl. RR's irq_entry, owner ruling 23): the caller passes its verdict (cpu_parked), never a
    -- second copy of the shape. nil (the verdict could not be taken) is reported as bad.
    local pc, cpsr, lr = (regs.R15 or -1) | 0, (regs.CPSR or -1) | 0, (regs.R14 or -1) | 0
    local parked = parked_verdict == true
    if not parked then bad[#bad + 1] = "cpu" end
    -- the pointer snapshot the write is judged against: each a sane, aligned EWRAM address
    local pnames, ptrs, pparts = {}, {}, {}
    for name in pairs(cp.pointers) do pnames[#pnames + 1] = name end
    table.sort(pnames)
    for _, name in ipairs(pnames) do
        local v = read(cp.pointers[name].address | 0, 4)
        ptrs[name] = v
        pparts[#pparts + 1] = string.format("%s=0x%08X", name, v)
        if v < 0x02000000 or v >= 0x02040000 or v % 4 ~= 0 then bad[#bad + 1] = "pointer:" .. name end
    end
    return string.format("cpu=[R15=0x%08X,CPSR=0x%08X,R14=0x%08X%s] ptrs=[%s] preds=[%s]", pc, cpsr, lr,
                         parked and "" or "!", table.concat(pparts, ","), table.concat(parts, ",")),
           missing, bad, ptrs
end
--- The overworld CPU verdict of a lua/gen3/safety.lua instance, now: true (parked), false (its
--- "cpu" clause refuses), nil (the pack preamble failed, so no clause ran). Self-contained (no
--- upvalues) so tests run this exact body over the real safety.lua and each title's pack.
local function cpu_parked(safety)
    if not safety then return nil end
    safety:check(nil, "overworld")
    for _, k in ipairs(safety.last_clauses or {}) do
        if k == "pack" then return nil end
        if k == "cpu" then return false end
    end
    return true
end
--- (line, missing Union Room tasks, {group, num, x, y, frame, bad, ptrs}): map, tile, frame, the
--- FULL active task list (SP.PC.dump), R15/CPSR, the save/storage pointers and every predicate,
--- read now; `bad` names each predicate off its expected value, "cpu" off the parked range, and
--- "pointer:<name>" for an insane pointer.
function ctx.center_state()
    local g, n = G.map(cp)
    local x, y = G.pos(cp)
    local state, missing, bad, ptrs = center_predicates(cp, function(a, width)
        if width == 4 then return memory.read_u32_le(a, "System Bus") end
        if width == 2 then return memory.read_u16_le(a, "System Bus") end
        return memory.read_u8(a, "System Bus")
    end, { R15 = emu.getregister("R15"), CPSR = emu.getregister("CPSR"), R14 = emu.getregister("R14") },
    cpu_parked(battle_parts and battle_parts.safety))
    local dumped, dump = pcall(SP.PC.dump)
    local frame = emu.framecount()
    return fmt("map=%d.%d at=(%d,%d) frame=%d %s %s", g, n, x, y, frame,
               dumped and tostring(dump) or "dump failed: " .. tostring(dump), state),
           missing, { group = g, num = n, x = x, y = y, frame = frame, bad = bad, ptrs = ptrs }
end

--- G4 item 2a (4)'s negative control, shared by every refusing state (the nurse, the 2F
--- attendants, the cable link wait): `live()` holds (the state is still up); the runner queues
--- `cmd` for `key` once it reads CONTROL_LIVE <name>. The probe must arrive FRESH (a keyed RX
--- after the marker), its EXACT deferred entry must stay queued for `frames` frames, the sink
--- must attempt nothing (write_count) and the party + PC bytes must not change; the refusing
--- clause must name a check failing right now. Returns clause, why (or nil, reason).
-- ponytail: one probe per control; a queue-wide token is not needed while the key is unique
function ctx.hold_probe(name, cmd, key, live, frames, already_queued)
    frames = frames or 600
    -- the baseline comes BEFORE the probe is even queued: zero attempts throughout delivery
    -- (Codex REV-center-receipt-2), not only from the RX on
    local attempted0, writes0 = ctx.attempted(), ctx.writes()
    local party0, box0 = ctx.mutable_bytes()
    local rx0 = ctx.received(cmd, key)
    local state = ctx.center_state()
    ctx.log(fmt("CONTROL_LIVE %s %s %s", name, key, state))
    if not already_queued then
        if not ctx.wait_until(function() return ctx.received(cmd, key) > rx0 end, 600,
                              "RX " .. cmd .. " " .. key .. " after CONTROL_LIVE " .. name) then
            return nil, name .. ": the runner never queued " .. cmd .. " " .. key
        end
    end
    -- one sample per advanced frame, the final one included: every invariant is checked AFTER
    -- the advance, and the named refusal is read from that same last sample (Codex executed a
    -- change on frame 600 that the old before-advance checks never saw)
    local function sample(i)
        if not live() then return nil, fmt("%s: the refusing state ended by frame %d", name, i) end
        local q = ctx.queued(cmd, key)
        if not q then return nil, fmt("%s: %s %s is not queued (frame %d)", name, cmd, key, i) end
        if ctx.attempted() ~= attempted0 or ctx.writes() ~= writes0 then
            return nil, fmt("%s: the sink attempted a write while the state was live (frame %d)", name, i)
        end
        return q
    end
    local q, why = sample(0)
    if not q then return nil, why end
    for i = 1, frames do
        ctx.frames(1)
        q, why = sample(i)
        if not q then return nil, why end
    end
    why = q.why
    local clause = why and why:match("forbidden state: (%S+)$")
    if clause and G.pred_ok(cp, clause) then clause = nil end
    if not clause and why and why:find("unknown active task", 1, true) then clause = "task" end
    if not clause and why and why:find("CPU outside parked checkpoint", 1, true) then clause = "cpu" end
    if not clause then return nil, name .. ": the hold names no failing clause (" .. tostring(why) .. ")" end
    local party1, box1 = ctx.mutable_bytes()
    if party1 ~= party0 then return nil, name .. ": the party bytes changed while held" end
    if box1 ~= box0 then return nil, name .. ": the PC storage bytes changed while held" end
    ctx.log(fmt("CONTROL_REFUSED %s %s %s clause=%s held_frames=%d attempted=0 writes=0 bytes=unchanged %s",
                name, cmd, key, clause, frames, (ctx.center_state())))
    return clause, why
end

--- One press the GAME read: wait until gMain.heldKeys (+0x2C) reads `btn` released, hold until it
--- reads it pressed (that read IS the JOY_NEW edge a menu acts on), wait until it reads it
--- released again, then idle `gap`; each phase bounded. The P.press rule of
--- lua/tests/probe_gen3_checkpoint.lua (N7 live): a main-loop pass that overruns frames reads keys
--- on fewer frames than the emulator runs, so a blind 3-frame tap can fall between two reads.
--- RR (G5-RR-CARRIER-FIX, receipt c12211c1): CFRU's action menu (0x090A9EA0) acts only on
--- gMain.newKeys (+0x2E) & A; the carrier's blind tap on FIGHT was never taken. Self-contained
--- (no upvalues) so tests run this exact body. -> true, frames | false, why
local function game_press(btn, set, advance, held, gap, bound)
    local bits = { A = 0x1, B = 0x2, Select = 0x4, Start = 0x8, Right = 0x10, Left = 0x20, Up = 0x40,
                   Down = 0x80, R = 0x100, L = 0x200 }
    local bit, n = assert(bits[btn], "unknown button " .. tostring(btn)), 0
    local function phase(keys, want, what)
        for _ = 1, bound or 30 do
            set(keys); advance(); n = n + 1
            if ((held() & bit) ~= 0) == want then return true end
        end
        return false, string.format("%s: the game never read %s %s in %d frames", btn, btn, what, bound or 30)
    end
    local ok, why = phase({}, false, "released")
    if ok then ok, why = phase({ [btn] = true }, true, "pressed") end
    if ok then ok, why = phase({}, false, "released after the press") end
    if not ok then set({}); return false, why end
    for _ = 1, gap or 0 do set({}); advance(); n = n + 1 end
    return true, n
end
-- gMain from the PACK (its callback2 predicate is gMain +4, both packs): RR's CFRU menu reads
-- 0x030030F0 +0x2E (rr_active_faint_parity_scope §3.1), the same base as pret FR/LG's gMain
local GMAIN = assert(cp.predicates.callback2.offset == 4 and cp.predicates.callback2.address,
                     "the pack's callback2 predicate is not gMain+4")
local function press(btn, gap)
    return game_press(btn, joypad.set, G.advance,
                      function() return memory.read_u16_le(GMAIN + 0x2C, "System Bus") end, gap, 30)
end
ctx.press_confirmed = press

--- HandleInputChooseAction / HandleInputChooseMove: Left/Right toggle bit 0 of the cursor,
--- Up/Down bit 1 (each only in its own direction). Bounded, then read back.
local function steer(read, target)
    for _ = 1, 6 do
        local c = read()
        if c == target then return true end
        if (c & 1) ~= (target & 1) then G.tap((c & 1) == 1 and "Left" or "Right", 3, 20)
        else G.tap((c & 2) == 2 and "Up" or "Down", 3, 20) end
    end
    return read() == target
end

--- Wait for the player's next decision point: "action", "party", "over" (the battle ended) or
--- nil (timeout). `button` is pressed on a 16-frame cadence, never on a frame the action menu
--- is up: B for text, the nickname prompt (B = NO, Cmd_trygivecaughtmonnick) and the dex page.
function ctx.await_turn(secs, button, prompt_policy)
    local n = 0
    return ctx.wait_until(function()
        -- T2's move-learning policy witnesses the actual script command BEFORE deciding
        -- whether this frame accepts B or the stop-learning confirmation. Other rows retain
        -- the existing text policy. Sampling also continues after the lead reaches Lv13.
        local handled, prompt_button = false, nil
        if prompt_policy then handled,prompt_button=prompt_policy() end
        if not handled and not play.in_battle(cp) then return "over" end
        if party_menu_up() then return "party" end
        if not handled and action_menu_up() then return "action" end
        n = n + 1
        local press=button
        if handled then press=prompt_button end
        if prompt_policy then joypad.set({}) end -- guarantee released edges between decisions
        if press and n % 16 == 0 then joypad.set({ [press] = true }) end
        return nil
    end, secs or 120, "the next battle decision")
end

--- At the action menu (SP.verify_fight_cursor has put the cursor on FIGHT): pick `action`.
function ctx.choose_action(action)
    if not action_menu_up() then return false, "action menu not up" end
    if not steer(function() return memory.read_u8(S.gActionSelectionCursor) end, action) then
        return false, "action cursor stuck at " .. memory.read_u8(S.gActionSelectionCursor)
    end
    -- SP.verify_fight_cursor mashes A every other frame and returns on the frame the menu comes
    -- up, so half the time A was held on the frame before this one. HandleInputChooseAction
    -- reads JOY_NEW(A_BUTTON) (pret battle_controller_player.c:225), an edge of heldKeysRaw
    -- (main.c:299): a tap that continues that hold is no press at all. Live linked_faint_active
    -- FR 324aea87: FIGHT already under the cursor (no steer tap to break the hold), A dropped,
    -- "TIMEOUT waiting for the move menu". Release one frame first.
    -- A game-confirmed press, then the menu must actually close; bounded re-press while it is
    -- still up on the same cursor (a repeat A on the same choice is the same choice)
    for attempt = 1, 3 do
        local ok, why = press("A", 13)
        if not ok then return false, "action A: " .. why end
        if not action_menu_up() or ctx.wait_until(function() return not action_menu_up() end, 2,
                                                  "the action menu to take A") then
            return true
        end
        log(fmt("ACTION_PRESS_UNTAKEN attempt=%d ctrl0=0x%08X cursor=%d held=0x%X new=0x%X", attempt, ctrl0(),
                memory.read_u8(S.gActionSelectionCursor), memory.read_u16_le(GMAIN + 0x2C, "System Bus"),
                memory.read_u16_le(GMAIN + 0x2E, "System Bus")))
    end
    return false, "the action menu never took a game-read A press"
end

--- The first move of battler 0 with base power 0 and PP left, else nil. The move table is the
--- PACK's (rom.BATTLE_MOVES_ADDR, derived.BATTLE_MOVE_ENTRY_SIZE: RR's CFRU table sits elsewhere,
--- 0x091521D0, and RR move ids run past FR's table; G5-RR-MOVEPICK), never pret FR's gBattleMoves
--- on RR. Power is byte 1 of the entry (pret include/pokemon.h struct BattleMove; CFRU keeps it:
--- RR's own Pound reads 40 and Leer 0 there, the entries the rr_battle Treecko carries).
function ctx.status_move_slot()
    local base = S.gBattleMons                            -- battler 0
    local table_at, size = profile.rom.BATTLE_MOVES_ADDR, profile.derived.BATTLE_MOVE_ENTRY_SIZE
    for slot = 0, 3 do
        local move = memory.read_u16_le(base + 0x0C + slot * 2)
        local pp = memory.read_u8(base + 0x24 + slot)
        if move ~= 0 and pp > 0 and memory.read_u8(table_at + move * size + 1) == 0 then return slot end
    end
end

--- FIGHT, then move `slot`.
function ctx.use_move(slot)
    local ok, why = ctx.choose_action(ACTION_FIGHT)
    if not ok then return false, why end
    if not ctx.wait_until(move_menu_up, 10, "the move menu") then
        return false, "move menu never opened (action menu still up: " .. tostring(action_menu_up()) .. ")"
    end
    if not steer(function() return memory.read_u8(S.gMoveSelectionCursor) end, slot) then
        return false, "move cursor stuck"
    end
    local pok, pwhy = press("A", 13)
    if not pok then return false, "move A: " .. pwhy end
    return true
end

--- The in-battle party menu is taking input: move to `slot`, A, popup row 0 (SHIFT on a voluntary
--- switch, SEND OUT on the forced one after a faint -- pret src/data/party_menu.h), then wait for
--- battler 0 to become `slot`.
local function party_pick(slot)
    if not ctx.wait_until(function() return party_menu_up() and party_task(S.Task_HandleChooseMonInput) end,
                          20, "the in-battle party menu") then
        return false, "the party menu never took input"
    end
    for _ = 1, 8 do
        local at = memory.read_u8(S.gPartyMenu + 9)       -- gPartyMenu.slotId, include/party_menu.h
        if at == slot then break end
        G.tap(at < slot and "Down" or "Up", 3, 20)
    end
    if memory.read_u8(S.gPartyMenu + 9) ~= slot then return false, "party cursor never reached slot " .. slot end
    local pok, pwhy = press("A", 20)
    if not pok then return false, "party A: " .. pwhy end
    if not ctx.wait_until(function() return party_task(S.Task_HandleSelectionMenuInput) end, 10, "SHIFT popup") then
        return false, "the SHIFT/SUMMARY/CANCEL popup never opened"
    end
    pok, pwhy = press("A", 20)                            -- SHIFT / SEND OUT
    if not pok then return false, "popup A: " .. pwhy end
    if not ctx.wait_until(function() return ctx.battler_slot() == slot end, 60, "the switch") then
        return false, "battler 0 never became party slot " .. slot
    end
    return true
end
--- POKeMON -> party `slot` -> SHIFT, then wait for the switch to land.
function ctx.switch_to(slot)
    local ok, why = ctx.choose_action(ACTION_SWITCH)
    if not ok then return false, why end
    return party_pick(slot)
end
--- The FORCED party screen after a faint (the caller saw it come up): SEND OUT `slot`.
function ctx.send_out(slot)
    if not party_menu_up() then return false, "no forced party screen" end
    local ok, why = party_pick(slot)
    if ok then log(fmt("SENT_OUT slot=%d battler_slot=%d", slot, ctx.battler_slot())) end
    return ok, why
end

--- RUN until the battle ends (a failed escape costs a turn and returns to the action menu).
function ctx.run_away(label)
    for _ = 1, 10 do
        local turn = SP.verify_fight_cursor(cp, "incidental_battle")
        if turn == nil then return true end
        if turn == "party" then return false, "a forced party menu came up" end
        local ok, why = ctx.choose_action(ACTION_RUN)
        if not ok then return false, why end
        local r = ctx.await_turn(120, "B")
        if r == "over" then play.wait_scene_settled(cp, 1800) return true end
        if r ~= "action" then return false, "no decision point after RUN (" .. tostring(r) .. ")" end
    end
    return false, label .. ": could not escape in 10 turns"
end

--- Grass hunt from the pinned Route 1 square (gen3_scripted_play hunt_encounter).
function ctx.hunt(label) return SP.hunt_encounter(cp, label, 40) end

local boot_keys = {}
--- Hunt, throw Poke Balls until the catch lands; returns the new party key or nil, why.
function ctx.catch(label)
    if not ctx.hunt(label) then return nil, "no wild encounter" end
    local throws = 0
    while throws < 8 do
        local turn = SP.verify_fight_cursor(cp, "incidental_battle")
        if turn == nil then break end
        if turn == "party" then return nil, "a forced party menu came up while catching" end
        -- Only an exhaustion OBSERVED after real throws is the ball RNG (and earns the retry); an
        -- unreadable count or a fixture that starts empty is a harness defect (Codex review of
        -- ad9669b1: read_balls() nil before any throw read as "out-of-balls", retryable).
        local balls = ctx.balls()
        if balls < 0 then return nil, "the Poke Ball count is unreadable" end
        if balls == 0 then
            if throws == 0 then return nil, "the fixture starts with no Poke Balls" end
            local ran, rwhy = ctx.run_away(label)
            if not ran then return nil, "out of balls, then the escape failed: " .. tostring(rwhy) end
            -- bare reason: every caller prefixes "hunt ended ", giving the Gen 1 standard's exact
            -- CAUSE_RNG phrase (tools/e2e_duo.py GEN1_RNG_REASON_CLASS "hunt ended out-of-balls")
            return nil, "out-of-balls"
        end
        local ok, why = ctx.choose_action(ACTION_BAG)
        if not ok then return nil, why end
        -- Live link_gen3 FR, throw 2: the bag REMEMBERS the POKEBALLS pocket (gBagMenuState is
        -- EWRAM, OPEN_BAG_LAST), so the helper's pocket steer -- whose Right + 40-frame idle hid
        -- the open fade on throw 1 -- was skipped, its selecting A landed during the fade and was
        -- dropped, and gSpecialVar_ItemId kept GoToBagMenu's ITEM_NONE (item_menu.c:340).
        if not ctx.wait_until(ctx.bag_input_ready, 20, "the battle bag to take input") then
            return nil, "the battle bag never took input"
        end
        SP.throw_pokeball_from_bag(cp, label)
        throws = throws + 1
        log("THREW " .. throws)
        local r = ctx.await_turn(180, "B")
        if r == "over" then break end
        if r ~= "action" then return nil, "no decision point after the throw (" .. tostring(r) .. ")" end
    end
    play.wait_scene_settled(cp, 1800)
    local outcome = memory.read_u8(S.gBattleOutcome)
    if outcome ~= B_OUTCOME_CAUGHT then return nil, "the battle ended with outcome " .. outcome end
    -- The client's own capture event names the key: by the time the field settles the server may
    -- already have quarantined (box_mon) or retired (dead zone) the record out of the party.
    local cap = ctx.last_sent("capture")
    if cap and type(cap.key) == "string" and not boot_keys[cap.key] then return cap.key end
    for _, m in ipairs(ctx.party() or {}) do
        if not boot_keys[m.key] then return m.key, m end
    end
    return nil, "caught, but no new key in the party"
end

--- Keep choosing a no-damage move until the ACTIVE `key` faints (a natural engine faint).
function ctx.lose_active(key, label)
    -- The watcher's record, not a fresh read: a whiteout heals the party at the warp, so by the
    -- time the battle is gone the fainted mon can read full HP again.
    local function fainted()
        local m = ctx.find(key)
        return ctx.hp0(key) ~= nil or (m ~= nil and m.hp == 0)
    end
    -- A foe that does not hurt us (status moves, misses) burns our no-damage PP for nothing: live
    -- RR R4 at 97672e6d spent all 30 of Leer's PP on one foe and failed "no no-damage move with
    -- PP". After STALL_TURNS turns with no HP lost, RUN and hunt a fresh foe (G5-RR-MOVEPICK).
    local STALL_TURNS = 6
    local function lead_hp() return memory.read_u16_le(S.gBattleMons + 0x28) end
    local last_hp, stalled, hunts = nil, 0, 1
    for turn_no = 1, 120 do
        if fainted() then return true end
        local turn = SP.verify_fight_cursor(cp, "incidental_battle")
        if turn ~= "fight" then
            return fainted(), "battle left the action menu (" .. tostring(turn) .. ")"
        end
        -- Only now: gBattleMons is copied in at BattleIntroDrawTrainersOrMonsSprites (pret
        -- battle_main.c:2576-2578), long after the encounter step the hunt returns on -- live FR
        -- 324aea87 read it there and got nil. No damaging fallback: it can KO the foe first.
        local hp = lead_hp()
        stalled = (last_hp and hp >= last_hp) and stalled + 1 or 0
        last_hp = hp
        if stalled >= STALL_TURNS and hunts < 6 then
            log(fmt("LOSE_REHUNT %s turn=%d hp=%d foe_hp=%d", key, turn_no, hp,
                    memory.read_u16_le(S.gBattleMons + 0x58 + 0x28)))
            local ran, rwhy = ctx.run_away(label .. " rehunt")
            if not ran then return false, label .. ": re-hunt escape: " .. tostring(rwhy) end
            if not ctx.hunt(label .. " rehunt") then return false, label .. ": re-hunt found no encounter" end
            hunts, stalled, last_hp = hunts + 1, 0, nil
        else
            local slot = ctx.status_move_slot()
            if turn_no == 1 then log(fmt("LOSE %s status_move_slot=%s", key, tostring(slot))) end
            if not slot then
                return false, fmt("%s: battler 0 has no no-damage move with PP (turn %d, hp %d, hunts %d)",
                                  label, turn_no, hp, hunts)
            end
            local ok, why = ctx.use_move(slot)
            if not ok then return false, label .. ": " .. why end
        end
    end
    return false, label .. ": still standing after 120 turns"
end

-- ── walking: the BFS-verified PATHS of gen3_scripted_play.lua, plus exact reversals ──────
local INVERT = { Up = "Down", Down = "Up", Left = "Right", Right = "Left" }
local function reversed(name, as)
    local p = assert(SP.PATHS[name], "no PATHS entry " .. name)
    local dirs = {}
    for i = #p.dirs, 1, -1 do dirs[#dirs + 1] = INVERT[p.dirs[i]] end
    SP.PATHS[as] = { map = p.map, from = { p.to[1], p.to[2] }, to = { p.from[1], p.from[2] }, dirs = dirs }
end
reversed("pokecenter_entrance_to_pc", "pc_to_pokecenter_entrance")   -- the same tiles, walked back

--- Route 1 grass origin -> facing the Viridian Pokemon Center PC (the viridian_pc leg's walk).
function ctx.walk_to_pc(label)
    SP.return_to_grass_origin(cp, label)
    play.follow(cp, "route1_grass_to_north_edge", label)
    SP.warp_to(cp, "Up", 30, SP.DEST.viridian_south, label .. " Route1->Viridian")
    play.follow(cp, "route1_edge_to_pokecenter_door", label)
    SP.warp_to(cp, "Up", 30, SP.DEST.center, label .. " Center door")
    play.follow(cp, "pokecenter_entrance_to_pc", label)
    G.tap("Up", 2, 13)
end

--- The PC -> the Route 1 grass origin (Center door, Viridian, Route 1 north to south).
function ctx.walk_pc_to_grass(label)
    play.follow(cp, "pc_to_pokecenter_entrance", label)
    SP.warp_to(cp, "Down", 30, SP.DEST.center_exit, label .. " Center exit")
    play.follow(cp, "pokecenter_door_to_route1_edge", label)
    SP.warp_to(cp, "Down", 30, SP.DEST.route1_north, label .. " Viridian->Route1")
    play.follow(cp, "route1_north_to_south_edge", label)
    play.follow(cp, "route1_south_to_grass_spot", label)
end

--- DEPOSIT party slot 1 into box 0 (the leg's pinned sequence); returns the key that left.
function ctx.pc_deposit(label)
    local before = ctx.party() or {}
    local PC = SP.PC
    PC.open(cp, label); PC.mode(label, 1); PC.popup(label, 1, 1, 0)
    PC.select(label, S.Task_DepositMenu | 1); PC.box(label); PC.leave(cp, label)
    local after = ctx.party() or {}
    if #after ~= #before - 1 then return nil, fmt("party %d -> %d after the deposit", #before, #after) end
    local left = {}
    for _, m in ipairs(after) do left[m.key] = true end
    for _, m in ipairs(before) do if not left[m.key] then return m.key end end
    return nil, "no key left the party"
end

--- WITHDRAW box 0 slot 0 (the leg's pinned sequence); returns the key that joined.
function ctx.pc_withdraw(label)
    local before = ctx.party() or {}
    local PC = SP.PC
    G.tap("Up", 2, 13)
    PC.open(cp, label); PC.mode(label, 0); PC.popup(label, 0, 0, 0)
    PC.select(label, S.Task_WithdrawMon | 1); PC.withdraw(label); PC.leave(cp, label)
    local after = ctx.party() or {}
    local had = {}
    for _, m in ipairs(before) do had[m.key] = true end
    for _, m in ipairs(after) do if not had[m.key] then return m.key end end
    return nil, fmt("party %d -> %d and no new key after the withdraw", #before, #after)
end

--- In-game SAVE (row search + flash-counter proof, gen3_boot_check save_via_menu), then settle
--- so the client's save-site flush has run.
function ctx.save(tag)
    if not ctx.wait_until(function() return play.on_field(cp) end, 60, "the field before SAVE") then
        return false, "not on the field to SAVE"
    end
    local dom = G.flash_domain()
    if not dom then return false, "no flash memory domain" end
    local ok, before, after, why = G.save_via_menu(cp, dom)
    if not ok then return false, "SAVE failed: " .. tostring(why) end
    log(fmt("SAVE_WITNESS %s counter=%d->%d", tag, before, after))
    ctx.frames(30)
    return true
end

-- ── boot: battery -> CONTINUE -> field, then the production hello ───────────────────────
-- Guarded too (card C4-GUARD): a raise inside the boot is the same silent hang as a load-time
-- one -- the driver never reaches MYKEY, so a bare raise here writes no RESULT either.
local reached_field = guard("boot to field from the battery save",
                            function() return G.boot_to_field(cp, 9000) end)
if not reached_field then
    G.shot(D.scenario .. "_" .. D.player .. "_bootfail")
    finish(false, "never reached the field from the battery save")
end
local booted = guard("party read after boot", function() return ctx.party() end)
if not booted then finish(false, "party unreadable after boot") end
for _, m in ipairs(booted) do
    boot_keys[m.key] = true
    log(fmt("MYKEY %d %s", m.slot, m.key))
    log(fmt("PARTY slot=%d key=%s species=%d level=%d hp=%d/%d", m.slot, m.key, m.species, m.level, m.hp, m.max_hp))
end
ctx.boot_keys = boot_keys
log(fmt("booted frame=%d map=%s balls=%d", emu.framecount(), play.where(cp), ctx.balls()))
if not ctx.wait_until(function() return seen_tx.hello end, 120, "the client's hello") then
    finish(false, "the client never sent hello from the field")
end

-- ── the scenario ─────────────────────────────────────────────────────────────────────────
if wants_routes then
    local Routes = load_or_die("/lua/tests/gen3_routes.lua", "battle-window routes")
    local Tutorial = load_or_die("/lua/tests/mkstates_gen3_tutorials.lua", "tutorial helpers")
    assert(battle_parts and battle_parts.policy, "no actual battle-window policy captured")
    ctx.battle_window_snapshot = Routes.snapshotter(ctx, {
        u8=function(a) return memory.read_u8(a,"System Bus") end,
        u16=function(a) return memory.read_u16_le(a,"System Bus") end,
        u32=function(a) return memory.read_u32_le(a,"System Bus") end,
    }, battle_parts.policy, profile.ram, emu.framecount, function()
        return {R15=emu.getregister("R15"),CPSR=emu.getregister("CPSR")}
    end)
    ctx.enter_trainer = function(label, expected, prep)
        return Routes.enter_trainer(ctx,Tutorial,emu.framecount,label,expected,prep)
    end
    ctx.preparation_budget = Routes.preparation_budget
    ctx.move_prompt = Routes.move_prompt({
        u8=function(a) return memory.read_u8(a,"System Bus") end,
        u16=function(a) return memory.read_u16_le(a,"System Bus") end,
        u32=function(a) return memory.read_u32_le(a,"System Bus") end,
    },S,log)
end
if D.active_faint_case == "whiteout" then
    --- fn() with every incidental battle FLED instead of fought (T2's proven escape policy,
    --- gen3_routes.lua with_incidental_escape); the lone-lead walks of linked_faint_active's
    --- whiteout case (W3, live FR-as-A at b0483efe: the walk back fought a Route 1 encounter,
    --- lost and whited out before READY_ACTIVE). -> ok, result
    local Routes = load_or_die("/lua/tests/gen3_routes.lua", "escape routes")
    ctx.flee_incidentals = function(label, fn) return Routes.with_incidental_escape(ctx, label, fn) end
end
local base = D.scenario_module or D.scenario:gsub("_gen3$", "")
local file = fmt("%s/lua/tests/duo/scenario_%s%s.lua", ROOT, D.scenario_prefix or "gen3_", base)
local okload, scenario = pcall(dofile, file)
if not okload or type(scenario) ~= "function" then
    finish(false, "no scenario module " .. file .. ": " .. tostring(scenario))
end
local ok, pass, msg = pcall(scenario, ctx)
idle_jitter(false)              -- the echo, for a phase that never waited for GO (see wait_go)
if not ok then
    if pass == FINISHED then return end
    -- a raised table (playlib's {whiteout=true, map=...}) names its fields, not its address
    local why = pass
    if type(why) == "table" then
        local parts = {}
        for k, v in pairs(why) do parts[#parts + 1] = tostring(k) .. "=" .. tostring(v) end
        table.sort(parts)
        why = "{" .. table.concat(parts, ",") .. "}"
    end
    finish(false, "scenario error: " .. tostring(why))
end
log(fmt("WRITES %d", writes))
finish(pass and true or false, msg)
