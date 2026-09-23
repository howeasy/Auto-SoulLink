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
    SLINK_DUO      wt, player "a"|"b", scenario "link"|"gen2_link", game "gen2_new", attempt,
                   result (this instance's result file), partner_result, go_file,
                   timeout_frames (default 150000), idle_jitter (optional)
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
  The PASS is scenario_gen2_link.lua S.verdict over these very lines: CAUGHT/PASS without an engine
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

-- ── receipts the harness keeps (never an oracle of their own; S.verdict re-reads the lines) ──
local rec = {captures=0, capture=nil, sent_keys={}, caught=nil, client_saves=0, save_completed_frame=nil}
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
    if event == "hello" and sent.hello == nil then
        sent.hello = {frame=emu.framecount(), ot_id=msg.ot_id}
        jlog("HELLO", sent.hello)
    elseif event == "capture" and type(msg.key) == "string" then
        rec.sent_keys[msg.key] = true
        jlog("CAPTURE_SENT", {frame=emu.framecount(), key=msg.key, seq=msg.seq})
        maybe_caught()
    end
    return _send(line)
end

-- U3 binding point: the production entry, exactly as lua/slink.lua launches it.
local function start_production()
    dofile(ROOT .. "/lua/gen2/run.lua")
    return SLINK_GEN2_CLIENT, SLINK_GEN2_PARTS
end
local started, gen2, parts = pcall(start_production)
if not started or type(gen2) ~= "table" or type(parts) ~= "table" then
    finish(false, "production client did not start: " .. tostring(started and "run.lua exposed no client" or gen2))
end
jlog("CLIENT", {qualification=tostring(parts.qualification), production_admitted=parts.production_admitted == true,
                pack=tostring(parts.pack), title=tostring(parts.title),
                rom_sha1=tostring(parts.profile and parts.profile.rom_sha1)})
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
            rec.capture = rec.capture or {key=m.key}
            maybe_caught()
        end
    elseif type(ev) == "table" and ev.kind == "observation" and ev.site_id == "save_completed" then
        rec.client_saves = rec.client_saves + 1
        rec.save_completed_frame = emu.framecount()
    end
    return _on_event(self, ev)
end
local _handle = gen2.handle_command
gen2.handle_command = function(self, cmd)
    local c = type(cmd) == "table" and cmd.cmd or "?"
    if c ~= "noop" then log("RX " .. tostring(c) .. (type(cmd) == "table" and cmd.key and (" key=" .. tostring(cmd.key)) or "")) end
    return _handle(self, cmd)
end

-- ── the gate hooks, the input host and the scenario harness ─────────────────────────────
R.prepare(ctx, SG, ctx.u1)
local state = SG.hooks(ctx)
local idle = {}
for _, button in ipairs(SG.BUTTONS) do idle[button] = false end
local host = ctx.Host.new({step=SG.button_step(ctx), frame=api.framecount, idle=idle})
local timeout = D.timeout_frames or 150000

local h = {lines=lines, json=json, sent=sent, log=log, jlog=jlog}
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
function h.go()
    local f = D.go_file and io.open(D.go_file, "r")
    if f then f:close() end
    return f ~= nil
end
function h.jitter()
    local requested = D.idle_jitter or 0
    h.frames(requested)
    log(fmt("JITTER requested=%d applied=%d attempt=%d", requested, requested, D.attempt or 1))
end
function h.arrive()
    local case, q = ctx.case, ctx.qualify
    local arrived, why = pcall(ctx.Qualify.run, host, SG.qualify_observer(ctx), ctx.facts, q.facts,
        {name=case.name, title=case.title, attempt_id=case.attempt_id, stage="boot",
         stage_fingerprint=q.stage_fingerprint, max_frames=case.max_frames,
         max_phase_frames=case.max_phase_frames, settle_frames=case.settle_frames},
        function(_, phase, frame) log(fmt("  phase %s @%d", phase, frame)) end)
    if not arrived then return false, why end
    local map, party = ctx.reads.read_map(), ctx.reads.read_party()
    if not map or not party then return false, "arrival map/party unreadable" end
    jlog("BOOTED", {frame=api.framecount(), map_group=map.group, map_number=map.number, x=map.x, y=map.y,
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
function h.witness()
    if state.saves < 1 then return false, "the native save_completed site never fired" end
    if rec.client_saves < 1 then return false, "the production client never observed save_completed" end
    local wok, digest = pcall(SG.cart_digest, api)
    if not wok then return false, digest end
    local fok, saved = pcall(SG.flush, ctx, digest)   -- asserts file == CartRAM + the 22-byte RTC trailer
    if not fok then return false, saved end
    jlog("SAVE_WITNESS", {frame=api.framecount(), save_completed_frame=rec.save_completed_frame,
        gate_saves=state.saves, client_saves=rec.client_saves, cartram_sha256=digest, cartram_bytes=SG.CART_RAM_BYTES,
        saveram_path=(ctx.env.dir .. "/" .. ctx.env.saveram):gsub("\\", "/"), saveram_bytes=#saved,
        flushed_matches=true})
    return true
end

local ran, pass, msg = pcall(S.run, h)
state.release()
if not ran then finish(false, "scenario error: " .. tostring(pass)) end
finish(pass, msg)
