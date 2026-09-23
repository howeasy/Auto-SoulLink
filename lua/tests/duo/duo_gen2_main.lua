--[[
  lua/tests/duo/duo_gen2_main.lua -- per-instance driver for a `gen2_new` duo scenario (card gen2-H1).

  tools/e2e_duo.py writes patch/build/duo_<lane>_<inst>.lua (SLINK_HOST, SLINK_PORT, SLINK_PLAYER, the
  SLINK_DUO table) and dofiles this file inside EmuHawk. It boots the qualified battle fixture WARM,
  arrives through the same source-qualified CONTINUE path the gates use (lua/tests/gen2_qualify.lua
  stage "boot" over the shared scripted gate), starts the PRODUCTION Gen 2 client, and plays the
  scenario (lua/tests/duo/scenario_gen2_<name>.lua) with normal buttons only. No harness write.

  LAUNCH CONTRACT (for the gen2_new rows of tools/e2e_duo.py)
    TITLE          per instance, crystal|gold|silver (O-16: any C/G/S pair, e.g. C<->C crystal_battle +
                   crystal_battle_ot2, G<->S gold_battle + silver_battle, C<->G crystal_battle + gold_battle).
                   The driver takes it from SLINK_GEN2_TITLE only; every per-title input below must be built
                   for THAT instance's title, and the fixture case must be <title>_battle[_ot2].
    ROM / config   run_gb_gate._gen2_plan(<title>, <per-instance SaveRAM dir under BUILD>, <fixture>,
                   100|300)["rom"]; config from run_gb_gate._gen2_config(plan, cfg); seed
                   tests/fixtures/gen2/<case>.SaveRAM into <SAVERAM_DIR>/<SAVERAM_NAME> before launch.
    SLINK_DUO      wt, player "a"|"b", scenario <name>|gen2_<name> (lua/tests/duo/scenario_gen2_<name>.lua: link,
                   faint, reconnect, soft_reset, admit_wrong_rom), game "gen2_new", attempt,
                   result (this instance's result file), partner_result, go_file,
                   timeout_frames (default 150000), idle_jitter (optional); per scenario (its header):
                   phase + expected_key (reconnect), expect_admission "refused" (admit_wrong_rom's
                   unadmitted-ROM half: no gate context, S.run_refused instead of S.run)
    process env    (Popen env=, per instance, as run_gb_gate passes it) SLINK_ROOT;
                   _gen2_plan(...)["env"]: SLINK_GEN2_TITLE/_ROM_SHA1/_CORE_MODE/_COLD=0/_SAVERAM_DIR/
                   _SAVERAM_NAME; tests/live/test_gen2_new_gates.inspect_env(spec, fixture_bytes):
                   SLINK_GEN2_FIXTURE_CASE (attempt_id overridden per instance, ^[%w_-]{1,80}$),
                   SLINK_GEN2_ROUTE_FACTS, SLINK_GEN2_QUALIFY (stage boot, sha256 of the staged fixture);
                   SLINK_GEN2_U1_FACTS = tests/live/test_gen2_frame_align.u1_facts(load_context(<title>),
                   route_facts(<title>), <the fixture's qualification attempt_id>) (pack UI + catch prompt;
                   the pack-UI sites are title-specific ROM addresses: never share one instance's facts)
    go-file        after HELLO the driver waits (frame-bound) for D.go_file to exist; the runner writes
                   it once the server holds both hellos

  MARKERS -- one per line in D.result, JSON after the tag (json_codec), in this order (HELLO may come
  earlier: the client says hello whenever its checkpoint allows):
    DUO_GEN2 {player, scenario, attempt, case, title, rom_sha1, fixture_sha256}         at start
    CLIENT {qualification, production_admitted, pack, title, rom_sha1}                 client started
                   (FAIL unless the production client detected the same title as SLINK_GEN2_TITLE)
    BOOTED {frame, map_group, map_number, x, y, party_count}                           after CONTINUE
    MYKEY <slot> <key>                                  each party mon, after boot and after the route
    HELLO {frame, ot_id}                                               the client's hello went out
    TX <json, <= 220 chars> / RX <cmd>[ key=<k>]                  wire traffic (no tick / noop)
    ENGINE_CAPTURE {frame, site_id, acquisition, area_id, destination, slot, key, species_id, level}
                   the production binder's capture event reached the client; site_id is
                   capture_party_finalized (its latch requires the capture_party site hit)
    CAPTURE_SENT {frame, key, seq}                          the client sent `capture` for that key
    CAUGHT <key>                       printed ONLY once ENGINE_CAPTURE and CAPTURE_SENT share the key
    SAVE_WITNESS {frame, save_completed_frame, gate_saves, client_saves, cartram_sha256,
                  cartram_bytes=32768, saveram_path, saveram_bytes, flushed_matches=true}
                   after the native save: gate_saves = the scripted gate's save_completed site hits,
                   client_saves/save_completed_frame = the production client's save_completed
                   observation; cartram_sha256 = sha256(CartRAM[0:0x8000]) == the first 0x8000 bytes of
                   the flushed file saveram_path (<SAVERAM_DIR>/<SAVERAM_NAME>, 32768 + 22 RTC bytes)
    RECEIPT {schema "gen2-duo-link-v1", ...header, key, booted, hello, capture, save, client,
             input_mode "normal_buttons", harness_write_scopes []}                     PASS only
    RESULT: PASS (caught <key>) | RESULT: FAIL (<reason>)                                   last line
  Every scenario may also see: HELLO_AGAIN {frame, ot_id, n} (each later hello; HELLO stays the first),
  RX_TEXT {frame, cmd, text} (hud_show/gui_prompt/msgbox text, after its RX line), MEMORIAL_ACK {frame,
  event memorialize_done|memorialize_failed, key, box, reason} (the client's reply to a memorialize). An RX
  line is `RX <cmd>[ key=<k>][ sound=<n>][ area_id=<a>]`. Each scenario's header lists the markers it adds.
  CLIENT also carries registered_sites (the production binder's status().registered_sites after start).
  The faint scenario adds LINK_SAVE, ENGINE_FAINT, FAINT_SENT, PARTY_HP_WRITE and BENCH_HP_STATUS;
  scenario_gen2_faint.lua's header is their contract.
  The PASS is scenario_gen2_<name>.lua S.verdict over these very lines: CAUGHT/PASS without an engine
  capture, a sent capture and a native save observed by both the gate site and the client is a FAIL.

  U3 BINDING (one place, start_production below): dofile lua/gen2/run.lua -- the entry lua/slink.lua
  launches -- then SLINK_GEN2_CLIENT / SLINK_GEN2_PARTS; the client ticks on run.lua's own
  event.onframeend. Until U3 lands, SLINK_GEN2_PARTS.production_admitted is false and this FAILs.
--]]
local D = SLINK_DUO
assert(D and D.wt and D.player and D.scenario and D.result, "SLINK_DUO not configured (run via tools/e2e_duo.py)")
assert(D.game == "gen2_new", "duo_gen2_main only serves game gen2_new, got " .. tostring(D.game))
local ROOT = D.wt
package.path = ROOT .. "/lua/?.lua;" .. package.path
local fmt = string.format
local json = dofile(ROOT .. "/lua/json_codec.lua")

local lines = {}
local logf = io.open(D.result, "w")
local _console_log = console.log
local function log(s)
    s = tostring(s)
    lines[#lines + 1] = s
    _console_log("[duo" .. D.player:upper() .. "] " .. s)
    if logf then logf:write(s .. "\n"); logf:flush() end
end
local function jlog(tag, value) log(tag .. " " .. assert(json.encode(value))) end
local function finish(pass, msg)
    log("RESULT: " .. (pass and "PASS" or "FAIL") .. (msg and (" (" .. msg .. ")") or ""))
    if logf then logf:close(); logf = nil end
    client.exit()
    error("slink-duo-finished", 0) -- client.exit() is asynchronous
end

-- The U1 gate and the shared scripted gate, as libraries (no main flow, no BizHawk exit).
local previous = SLINK_GEN2_GATE_LIBRARY
SLINK_GEN2_GATE_LIBRARY = true
local F = dofile(ROOT .. "/lua/tests/gen2_frame_align.lua")
SLINK_GEN2_GATE_LIBRARY = previous
local SG = F.scripted_gate(ROOT)
local R = dofile(ROOT .. "/lua/tests/duo/gen2_route29_inputs.lua")
local name = D.scenario:gsub("^gen2_", "")
local okS, S = pcall(dofile, ROOT .. "/lua/tests/duo/scenario_gen2_" .. name .. ".lua")
if not okS then finish(false, "no gen2_new scenario " .. tostring(D.scenario)) end
local wire = dofile(ROOT .. "/lua/gen2/wire.lua")

local api = SG.bizhawk()
local timeout = D.timeout_frames or 150000
-- ── receipts the harness keeps (never an oracle of their own; S.verdict re-reads the lines) ──
local rec = {captures=0, capture=nil, sent_keys={}, caught=nil, client_saves=0, save_completed_frame=nil,
             faint=nil, faint_sent=nil, rx={}, hp_write=nil,
             hellos={}, tx=0, memorial={}}
local sent = {}
local function maybe_caught()
    local key = rec.capture and rec.capture.key
    if rec.caught == nil and key and rec.sent_keys[key] then
        rec.caught = key
        log("CAUGHT " .. key)
    end
end

local C = require("connector")
local _send = C.send
C.send = function(line)
    local okd, msg = pcall(json.decode, line)
    local event = okd and type(msg) == "table" and msg.event or "?"
    if event ~= "tick" then log("TX " .. tostring(line):sub(1, 220)) end
    rec.tx = rec.tx + 1
    if event == "hello" then
        local hello = {frame=emu.framecount(), ot_id=msg.ot_id}
        rec.hellos[#rec.hellos + 1] = hello
        if sent.hello == nil then
            sent.hello = hello
            jlog("HELLO", hello)
        else
            jlog("HELLO_AGAIN", {frame=hello.frame, ot_id=hello.ot_id, n=#rec.hellos})
        end
    elseif event == "capture" and type(msg.key) == "string" then
        rec.sent_keys[msg.key] = true
        jlog("CAPTURE_SENT", {frame=emu.framecount(), key=msg.key, seq=msg.seq})
        maybe_caught()
    elseif (event == "memorialize_done" or event == "memorialize_failed") and type(msg.key) == "string" then
        local ack = {frame=emu.framecount(), event=event, key=msg.key, box=msg.box, reason=msg.reason}
        rec.memorial[msg.key] = rec.memorial[msg.key] or ack
        jlog("MEMORIAL_ACK", ack)
    elseif event == "faint" and type(msg.key) == "string" then
        rec.faint_sent = {frame=emu.framecount(), key=msg.key, seq=msg.seq}
        jlog("FAINT_SENT", rec.faint_sent)
    end
    return _send(line)
end

-- U3 binding point: the production entry, exactly as lua/slink.lua launches it.
local function start_production()
    dofile(ROOT .. "/lua/gen2/run.lua")
    return SLINK_GEN2_CLIENT, SLINK_GEN2_PARTS
end
local function go_ready()
    local f = D.go_file and io.open(D.go_file, "r")
    if f then f:close() end
    return f ~= nil
end
-- True once `path` exists and holds `text` (the runner's phase markers in the go-file).
local function file_has(path, text)
    local f = path and io.open(path, "r")
    if not f then return false end
    local body = f:read("a")
    f:close()
    return body:find(text, 1, true) ~= nil
end

-- ── the REFUSED half (SLINK_DUO.expect_admission == "refused", scenario admit_wrong_rom) ─────────
-- An unadmitted ROM has no route/qualification facts by construction, so this half builds no gate
-- context: it only loads the production entry, which must refuse, and then idles with no input.
if D.expect_admission == "refused" then
    if type(S.run_refused) ~= "function" then finish(false, "scenario " .. D.scenario .. " has no refused half") end
    local idle_buttons = {}
    for _, button in ipairs(SG.BUTTONS) do idle_buttons[button] = false end
    local r = {log=log, jlog=jlog, json=json, lines=lines, player=D.player, api=api, SG=SG, rec=rec, go=go_ready}
    jlog("DUO_GEN2", {player=D.player, scenario=D.scenario, attempt=D.attempt or 1,
                      title=tostring(os.getenv("SLINK_GEN2_TITLE")), rom_sha1=tostring(api.romhash()):lower(),
                      expect_admission="refused"})
    function r.start()   -- run.lua's own console lines are its refusal reason
        local captured = {}
        console.log = function(line) captured[#captured + 1] = tostring(line); _console_log(line) end
        local okp, client_or_err = pcall(start_production)
        console.log = _console_log
        return okp, client_or_err, captured
    end
    function r.frames(n)
        for _ = 1, n do
            if api.framecount() > timeout then error("scenario timeout after " .. timeout .. " frames", 0) end
            api.set_buttons(idle_buttons)
            api.advance()
        end
    end
    function r.wait(pred, frames)
        for _ = 1, frames do
            if pred() then return true end
            r.frames(1)
        end
        return pred() and true or false
    end
    local ran, pass, msg = pcall(S.run_refused, r)
    if not ran then finish(false, "scenario error: " .. tostring(pass)) end
    finish(pass, msg)
end

local ok, ctx = pcall(function()
    local c = SG.context(api, os.getenv)
    assert(c.qualify ~= nil and c.qualify.stage == "boot", "SLINK_GEN2_QUALIFY stage \"boot\" required")
    assert(c.case.target == "battle", "the link scenario runs on a battle fixture")
    c.u1 = assert(json.decode(assert(os.getenv("SLINK_GEN2_U1_FACTS"), "SLINK_GEN2_U1_FACTS missing")))
    return c
end)
if not ok then finish(false, "bad environment: " .. tostring(ctx)) end
ctx.log = log
jlog("DUO_GEN2", {player=D.player, scenario=D.scenario, attempt=D.attempt or 1, case=ctx.case.name,
                  title=ctx.env.title, rom_sha1=ctx.env.rom_sha1, fixture_sha256=ctx.qualify.stage_fingerprint})

local started, gen2, parts = pcall(start_production)
if not started or type(gen2) ~= "table" or type(parts) ~= "table" then
    finish(false, "production client did not start: " .. tostring(started and "run.lua exposed no client" or gen2))
end
-- The sites the production binder actually registered (only receipt-proven ones, lua/gen2/signals.lua).
local registered = {}
do
    local okr, st = pcall(function() return gen2.signals:status() end)
    for _, id in ipairs(okr and type(st) == "table" and st.registered_sites or {}) do registered[#registered + 1] = tostring(id) end
    table.sort(registered)
end
jlog("CLIENT", {qualification=tostring(parts.qualification), production_admitted=parts.production_admitted == true,
                pack=tostring(parts.pack), title=tostring(parts.title),
                rom_sha1=tostring(parts.profile and parts.profile.rom_sha1), registered_sites=json.array(registered)})
if parts.production_admitted ~= true then finish(false, "client is not the production graph") end
-- The client detects its title from the ROM header (run.lua Entry.detect_title); the gate booted the
-- fixture for SLINK_GEN2_TITLE. A cross-title lane mix-up must fail here, not deep in the route.
if parts.title ~= ctx.env.title then
    finish(false, fmt("client title %s differs from SLINK_GEN2_TITLE %s", tostring(parts.title), ctx.env.title))
end

local _on_event = gen2.on_event
gen2.on_event = function(self, ev)
    if type(ev) == "table" and ev.kind == "capture" and type(ev.mon) == "table" then
        local m = ev.mon
        jlog("ENGINE_CAPTURE", {frame=emu.framecount(), site_id=tostring(ev.site_id), acquisition=tostring(ev.acquisition),
            area_id=tostring(ev.area_id), destination=tostring(ev.destination), slot=ev.slot, key=tostring(m.key),
            species_id=m.species_id, level=m.level})
        if ev.site_id == "capture_party_finalized" and ev.acquisition == "wild" then
            rec.captures = rec.captures + 1
            rec.capture = rec.capture or {key=m.key, species_id=m.species_id, area_id=ev.area_id}
            maybe_caught()
        end
    elseif type(ev) == "table" and ev.kind == "faint" and type(ev.mon) == "table" then
        local f = {frame=emu.framecount(), site_id=tostring(ev.site_id), cause=tostring(ev.cause), key=tostring(ev.mon.key),
                   slot=ev.slot}
        jlog("ENGINE_FAINT", f)
        rec.faint = rec.faint or f
    elseif type(ev) == "table" and ev.kind == "observation" and ev.site_id == "save_completed" then
        rec.client_saves = rec.client_saves + 1
        rec.save_completed_frame = emu.framecount()
    end
    return _on_event(self, ev)
end
local _handle = gen2.handle_command
gen2.handle_command = function(self, cmd)
    local c = type(cmd) == "table" and cmd.cmd or "?"
    if c ~= "noop" then
        local t = type(cmd) == "table" and cmd or {}
        log("RX " .. tostring(c) .. (t.key and (" key=" .. tostring(t.key)) or "")
            .. (t.sound and (" sound=" .. tostring(t.sound)) or "") .. (t.area_id and (" area_id=" .. tostring(t.area_id)) or ""))
        rec.rx[#rec.rx + 1] = {cmd=c, key=t.key, sound=t.sound, area_id=t.area_id, text=t.text}
        if (c == "hud_show" or c == "gui_prompt" or c == "msgbox") and type(cmd.text) == "string" then
            jlog("RX_TEXT", {frame=emu.framecount(), cmd=c, text=cmd.text})
        end
    end
    return _handle(self, cmd)
end

-- PARTY_HP_WRITE: the PRODUCTION writer's bench faint, observed around the very call the client makes
-- (parts.writes IS the client's writes object; run_deferred calls it inside the checkpoint hook). Every
-- field is read synchronously in the call: raw wPartyMons before/after, the permit log rows it added, and
-- the CPU/bank/stack/state evidence the per-title checkpoint pack names. No byte is written here.
local function bus_hex(addr, n, domain)
    local bytes = api.read_range(addr, n, domain or "System Bus")
    local out = {}
    for i = 1, n do out[i] = fmt("%02x", bytes[i]) end
    return table.concat(out)
end
local function checkpoint_evidence()
    local primary = parts.data.checkpoint.titles[ctx.env.title].primary
    local anchor = primary.anchors.ow_player_input
    local sp = api.register("SP")
    local values = {}
    for _, p in ipairs(primary.state_predicates) do
        local value = 0   -- the RAW bytes, big-endian joined; the oracle applies mask/operator
        for _, b in ipairs(api.read_range(p.address, p.width, "System Bus")) do value = value * 256 + b end
        values[p.symbol] = value
    end
    -- Both anchors the production safety rechecks (gen2_write_safety.lua), each in the ROM domain at its
    -- rom_offset and mapped on the System Bus at its address, expected_hex/2 bytes.
    local anchors = {}
    for name, row in pairs(primary.anchors) do
        local n = #row.expected_hex // 2
        anchors[name] = {rom_hex=bus_hex(row.rom_offset, n, "ROM"), mapped_hex=bus_hex(row.address, n)}
    end
    -- BizHawk exposes no MBC bank register: hrom_bank is the hROMBank shadow, anchor_hex the mapped bytes.
    return {pc=api.register("PC"), sp=sp, hrom_bank=api.read_u8(ctx.profile.hram.hROMBank, "System Bus"),
            svbk=api.read_u8(0xFF70, "System Bus") % 8, sc=api.read_u8(0xFF02, "System Bus"),
            stack_hex=bus_hex(sp, primary.caller_stack.required_read_bytes),
            anchor_hex=bus_hex(anchor.address, #anchor.expected_hex // 2), anchors=json.object(anchors),
            state=json.object(values)}
end
local W = parts.writes or {}   -- production always composes it; a stand-in client may not
local _faint_party_slot = W.faint_party_slot
if _faint_party_slot then W.faint_party_slot = function(self, slot, snapshot)
    local base, n = parts.profile.ram.wPartyMons, 6 * parts.profile.constants.PARTYMON_STRUCT_LENGTH
    local mark = #(self.log or {})
    local row = {frame=emu.framecount(), slot=slot, kind="party_hp"}
    local party = ctx.reads.read_party()
    for _, m in ipairs(party and party.mons or {}) do if m.slot == slot then row.key = wire.mon_key(m) end end
    local eok, evidence = pcall(checkpoint_evidence)
    row.checkpoint = eok and evidence or {error=tostring(evidence)}
    row.before_party_hex = bus_hex(base, n)
    local ok, result = pcall(_faint_party_slot, self, slot, snapshot)
    row.after_party_hex = bus_hex(base, n)
    row.ok, row.error = ok, not ok and tostring(result) or nil
    local added = {}
    for i = mark + 1, #(self.log or {}) do added[#added + 1] = self.log[i] end
    row.log = json.array(added)
    jlog("PARTY_HP_WRITE", row)
    if ok and rec.hp_write == nil then rec.hp_write = row end
    if not ok then error(result, 0) end
    return result
end end

-- ── the gate hooks, the input host and the scenario harness ─────────────────────────────
R.prepare(ctx, SG, ctx.u1)
local FI
if S.FAINT_INPUTS then   -- the faint route's UI origins are watched from the first hook on
    FI = dofile(ROOT .. "/lua/tests/duo/gen2_faint_inputs.lua")
    local fok, fwhy = pcall(FI.prepare, ctx, SG, ctx.u1)
    if not fok then finish(false, "faint inputs: " .. tostring(fwhy)) end
end
local state = SG.hooks(ctx)
local idle = {}
for _, button in ipairs(SG.BUTTONS) do idle[button] = false end
local step = SG.button_step(ctx)
local host = ctx.Host.new({step=step, frame=api.framecount, idle=idle})

local h = {lines=lines, json=json, sent=sent, log=log, jlog=jlog, player=D.player, rec=rec, registered=registered,
           root=ROOT, client=gen2, parts=parts, phase=D.phase, expected_key=D.expected_key, go_file=D.go_file,
           file_has=file_has, frame=api.framecount}
function h.frames(n)
    for _ = 1, n do
        if api.framecount() > timeout then error("scenario timeout after " .. timeout .. " frames", 0) end
        host.idle(1)
    end
end
function h.wait(pred, frames)
    for _ = 1, frames do
        if pred() then return true end
        h.frames(1)
    end
    return pred() and true or false
end
h.go = go_ready
-- Normal buttons held for n frames (the soft-reset chord); every other button released.
function h.hold(buttons, n)
    for _ = 1, n do
        if api.framecount() > timeout then error("scenario timeout after " .. timeout .. " frames", 0) end
        local b = {}
        for k, v in pairs(idle) do b[k] = v end
        for k, v in pairs(buttons) do b[k] = v end
        step(b)
    end
end
-- Raw wPlayerID (big-endian) and wPartyCount, read by symbol in their named WRAM bank (never production's
-- reads, and never a name decode: a zero-filled WRAM has no valid name or party list to decode).
function h.identity()
    local okp, id = pcall(ctx.sym, "wPlayerID", 0, 2)
    local okq, count = pcall(ctx.sym, "wPartyCount", 0, 1)
    if not okp or not okq then return nil end
    return {ot_id=id[1] * 256 + id[2], party_count=count[1]}
end
-- The production writer's permit log length (0 for a stand-in client that composes none).
function h.write_count() return #((parts.writes or {}).log or {}) end
function h.jitter()
    local requested = D.idle_jitter or 0
    h.frames(requested)
    log(fmt("JITTER requested=%d applied=%d attempt=%d", requested, requested, D.attempt or 1))
end
function h.arrive(tag)
    local case, q = ctx.case, ctx.qualify
    local arrived, why = pcall(ctx.Qualify.run, host, SG.qualify_observer(ctx), ctx.facts, q.facts,
        {name=case.name, title=case.title, attempt_id=case.attempt_id, stage="boot",
         stage_fingerprint=q.stage_fingerprint, max_frames=case.max_frames,
         max_phase_frames=case.max_phase_frames, settle_frames=case.settle_frames},
        function(_, phase, frame) log(fmt("  phase %s @%d", phase, frame)) end)
    if not arrived then return false, why end
    local map, party = ctx.reads.read_map(), ctx.reads.read_party()
    if not map or not party then return false, "arrival map/party unreadable" end
    jlog(tag or "BOOTED", {frame=api.framecount(), map_group=map.group, map_number=map.number, x=map.x, y=map.y,
                    party_count=party.count})
    return true
end
function h.party()
    local party = ctx.reads.read_party()
    for i, m in ipairs(party and party.mons or {}) do
        local key = wire.mon_key(m)
        if key then log(fmt("MYKEY %d %s", i - 1, key)) end
    end
end
function h.play()
    local driver, observe, spec = R.new(ctx, SG, F, {captures=function() return rec.captures end,
        reported=function() return rec.caught ~= nil end,
        max_frames=math.max(1, timeout - api.framecount()), max_phase_frames=D.max_phase_frames})
    return F.play(host, spec, driver, observe, {log=log, frame=api.framecount,
        screen=function() return SG.screen(ctx) end, where=function() return "-" end,
        trace=os.getenv("SLINK_GEN2_TRACE") == "1"})
end
-- The flushed native save: CartRAM digest == the first 0x8000 bytes of the flushed SaveRAM file.
local function flushed()
    if state.saves < 1 then return nil, "the native save_completed site never fired" end
    if rec.client_saves < 1 then return nil, "the production client never observed save_completed" end
    local wok, digest = pcall(SG.cart_digest, api)
    if not wok then return nil, digest end
    local fok, saved = pcall(SG.flush, ctx, digest)   -- asserts file == CartRAM + the 22-byte RTC trailer
    if not fok then return nil, saved end
    return {frame=api.framecount(), save_completed_frame=rec.save_completed_frame, gate_saves=state.saves,
            client_saves=rec.client_saves, cartram_sha256=digest, cartram_bytes=SG.CART_RAM_BYTES,
            saveram_path=(ctx.env.dir .. "/" .. ctx.env.saveram):gsub("\\", "/"), saveram_bytes=#saved,
            flushed_matches=true}, saved
end
function h.witness()
    local w, saved = flushed()
    if not w then return false, saved end
    jlog("SAVE_WITNESS", w)
    return true
end
-- LINK_SAVE: the linked save, copied once next to the result file (the runner's e2e_<scenario>_* sweep
-- clears it between attempts; an existing copy is refused, never overwritten).
function h.link_save(key)
    local w, saved = flushed()
    if not w then return false, saved end
    local result = D.result:gsub("\\", "/")
    local path = result:gsub("_result%.txt$", "") .. "_link_save.SaveRAM"
    if path == result .. "_link_save.SaveRAM" then return false, "result path does not end in _result.txt" end
    local existing = io.open(path, "rb")
    if existing then existing:close(); return false, "link save copy already exists: " .. path end
    local f = io.open(path, "wb")
    if not f then return false, "cannot write " .. path end
    f:write(saved)
    f:close()
    jlog("LINK_SAVE", {frame=w.frame, saveram_path=path, saveram_bytes=#saved, cartram_sha256=w.cartram_sha256,
                       cartram_bytes=w.cartram_bytes, gate_saves=w.gate_saves, client_saves=w.client_saves,
                       save_completed_frame=w.save_completed_frame, key=key})
    return true
end
-- True once the partner's result file carries a `<tag> ...` line.
function h.partner_has(tag)
    local f = D.partner_result and io.open(D.partner_result, "r")
    if not f then return false end
    local text = "\n" .. f:read("a")
    f:close()
    return text:find("\n" .. tag .. " ", 1, true) ~= nil
end
-- The party slot (0-based) and record holding `key`, through the gate's own decoder (never production's).
function h.slot_of(key)
    local party = ctx.reads.read_party()
    for _, m in ipairs(party and party.mons or {}) do
        if wire.mon_key(m) == key then return m.slot, m end
    end
end
local function play(spec, driver, observe)
    return F.play(host, spec, driver, observe, {log=log, frame=api.framecount,
        screen=function() return SG.screen(ctx) end, where=function() return "-" end,
        trace=os.getenv("SLINK_GEN2_TRACE") == "1"})
end
-- START -> SAVE -> YES (-> overwrite) from the overworld: the link route's own save phase, alone.
function h.save()
    local driver = F.driver(ctx.facts.maps.Route29)
    driver.phase = "save"
    local left = math.max(1, timeout - api.framecount())
    return play({name="duo-gen2-save", terminal=driver.terminal, terminal_idle=true, max_frames=left,
                 max_phase_frames=math.min(D.max_phase_frames or F.BUDGET.max_phase_frames, left),
                 settle_frames=F.BUDGET.settle_frames}, driver, SG.qualify_observer(ctx))
end
-- The species clause's reroll (gen2_route29_inputs.lua): walk to the next wild battle's menu -> its foe species
-- (the battle stays up for h.play or h.flee), or RUN from the battle that is up back to the overworld.
function h.encounter()
    local driver, observe, spec = R.encounter(ctx, SG, F, {max_frames=math.max(1, timeout - api.framecount()),
        max_phase_frames=D.max_phase_frames})
    local ok, why = play(spec, driver, observe)
    if not ok then return false, why end
    return true, driver.foe
end
function h.flee()
    local driver, observe, spec = R.flee(ctx, SG, F, {max_frames=math.max(1, timeout - api.framecount()),
        max_phase_frames=D.max_phase_frames})
    return play(spec, driver, observe)
end
-- The faint route (gen2_faint_inputs.lua): the opts.target party slot fights until opts.fainted().
function h.sacrifice(opts)
    local driver, observe, spec = FI.new(ctx, SG, F, {target=opts.target, fainted=opts.fainted,
        max_frames=math.max(1, timeout - api.framecount()), max_phase_frames=D.max_phase_frames})
    return play(spec, driver, observe)
end

local ran, pass, msg = pcall(S.run, h)
state.release()
if not ran then finish(false, "scenario error: " .. tostring(pass)) end
finish(pass, msg)
