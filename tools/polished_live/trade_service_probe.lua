-- Serverless, single-EmuHawk proposer-only held-service probe; NO SLink client/server/cable.
-- SYNTH: event flag + engine warp to POKECENTER_2F (5,3), exactly as trade_port_probe.lua.
-- TEST HOST: QUERY/OFFER replies, and disclosed COPY-to-OT-slot-0 staging for APPLY.
-- gb_trade_lease owns framing. Host writes occur ONLY in onframeend, never in a CPU hook.
-- Oracle/runner: trade_service_probe.py. This driver does not claim a native trade commit.
-- Every exec callback is counted; only the first 16 wrong-bank samples per site are retained.
-- Bad-PC callbacks are diagnostic-only. Serialization failure uses independent minimal JSON and FAILS.
local ROOT = assert(os.getenv("SLINK_ROOT"))
local L = dofile(ROOT .. "/tools/polished_live/pol_lib.lua")
local Lease = dofile(ROOT .. "/lua/gb_trade_lease.lua")
local CASE = assert(os.getenv("POL_CASE"))
local cases = {["offer-reject"]=true, ["cancel-menu"]=true, ["no-eligible"]=true,
               ["query-timeout"]=true, ["apply-done1"]=true, ["apply-invalid"]=true}
assert(cases[CASE], "unknown POL_CASE")
local S, trace = L.SYM, {}
local TOKEN = {0x54, 0x45, 0x53, 0x54} -- opaque nonzero LOCAL test visit token, not a server token
local base = assert(S.wSlinkMailbox)[2] + Lease.OFF_LEASE
local host_active, host_tx, enabled = false, nil, false
local shadow, entered, returned, entry_frame, slot = nil, false, false, nil, nil
local query_answered, offer_answered, applied, released = false, false, false, false
local gsb_n, overflow = 0, false
local last_pump = -1
local hook_counts, hook_sites, driver_errors = {}, {}, 0
local WRONG_BANK_SAMPLE_LIMIT = 16
local finished = false
local BUDGET = CASE == "query-timeout" and 700 or 2400
client.speedmode(400)

local function copy(t) local out = {} for i, v in ipairs(t) do out[i] = v end return out end
local function lease_bytes() return L.wbytes("wSlinkMailbox", Lease.OFF_LEASE, Lease.LEASE_SIZE) end
local function checksum(bytes)
    local h = 0x811C9DC5
    for _, v in ipairs(bytes) do h = ((h ~ v) * 0x01000193) & 0xFFFFFFFF end
    return string.format("%08x", h)
end
local function append(t, bytes) for _, v in ipairs(bytes) do t[#t + 1] = v end end
local function mon_bytes(prefix, i)
    local bytes = L.wbytes(prefix .. "Mon1", i * 48, 48)
    append(bytes, L.wbytes(prefix .. "MonOTs", i * 11, 11))
    append(bytes, L.wbytes(prefix .. "MonNicknames", i * 11, 11))
    return bytes
end
local function snap(kind, extra)
    local own = L.wbytes("wPartyMon1", 0, 6 * 48)
    append(own, L.wbytes("wPartyMonOTs", 0, 6 * 11))
    append(own, L.wbytes("wPartyMonNicknames", 0, 6 * 11))
    local tail = {}
    for i = 2, 5 do append(tail, mon_bytes("wOTParty", i)) end
    local e = {ord=#trace + 1, frame=emu.framecount(), kind=kind, pc=emu.getregister("PC"),
        sp=emu.getregister("SP"), bank=L.rombank(), vblank=L.bus(S.hVBlank[2]),
        link=L.rw("wLinkMode"), running=L.rw("wScriptRunning"), stack=L.rw("wScriptStackSize"),
        count=L.rw("wPartyCount"), party_sum=checksum(own), ot_tail_sum=checksum(tail),
        ot0_sum=checksum(mon_bytes("wOTParty", 0)), ot1_sum=checksum(mon_bytes("wOTParty", 1)),
        own0_sum=checksum(mon_bytes("wParty", 0)), lease=lease_bytes(),
        sbank=L.bus(S.hScriptBank[2]), spos=L.bus(S.hScriptPos[2]) | (L.bus(S.hScriptPos[2]+1) << 8),
        x=L.rw("wXCoord"), y=L.rw("wYCoord")}
    if extra then for k, v in pairs(extra) do e[k] = v end end
    trace[#trace + 1] = e
    return e
end
-- Independent serializer for a minimal failure trace; never retries the primary encoder.
local function quote(value)
    return '"' .. tostring(value):gsub('[%z\1-\31\\"]', function(c)
        if c == '\\' then return '\\\\' end
        if c == '"' then return '\\"' end
        return string.format('\\u%04x', string.byte(c))
    end) .. '"'
end
local function tiny_json(value)
    local kind = type(value)
    if kind == "string" then return quote(value) end
    if kind == "number" or kind == "boolean" then return tostring(value) end
    if kind ~= "table" then return "null" end
    local parts = {}
    for key, item in pairs(value) do parts[#parts + 1] = quote(key) .. ":" .. tiny_json(item) end
    return "{" .. table.concat(parts, ",") .. "}"
end
local function accounting(e, completed)
    e.hook_counts, e.hook_sites = hook_counts, hook_sites
    e.wrong_bank_sample_limit, e.driver_errors = WRONG_BANK_SAMPLE_LIMIT, driver_errors
    e.completed = completed and driver_errors == 0 and not overflow
    return e
end
local function dump(completed)
    local final
    for _, e in ipairs(trace) do
        if e.kind == "final" or e.kind == "complete" then
            accounting(e, completed)
            if e.kind == "final" then final = e end
        end
    end
    if not final then
        local ok, snapshot = pcall(snap, "final")
        if ok then final = accounting(snapshot, false)
        else
            driver_errors = driver_errors + 1
            final = accounting({kind="final"}, false)
            trace[#trace + 1] = {kind="driver_error", reason="final snapshot failed: " .. tostring(snapshot)}
            trace[#trace + 1] = final
        end
    end
    local ok, encoded = pcall(L.json.encode, trace)
    if not ok or type(encoded) ~= "string" then
        driver_errors = driver_errors + 1
        local diagnostic = {kind="driver_error", reason="trace serialization failed: " .. tostring(encoded)}
        trace[#trace + 1] = diagnostic
        L.check(diagnostic.reason, false)
        accounting(final, false)
        encoded = "[" .. tiny_json(diagnostic) .. "," .. tiny_json({
            kind="final", completed=false, driver_errors=driver_errors,
            wrong_bank_sample_limit=WRONG_BANK_SAMPLE_LIMIT, hook_counts=hook_counts, hook_sites=hook_sites
        }) .. "]"
    end
    local f = assert(io.open(L.RUN .. "/trace.json", "w"))
    f:write(encoded) f:close()
end
local function die(why)
    if finished then error(why, 0) end
    finished = true driver_errors = driver_errors + 1
    local ok, snapshot_error = pcall(snap, "driver_error", {reason=tostring(why)})
    if not ok then trace[#trace + 1] = {kind="driver_error", reason=tostring(snapshot_error)} end
    L.check(tostring(why), false)
    local dumped, dump_error = pcall(dump, false)
    if not dumped then L.check("trace dump failed: " .. tostring(dump_error), false) end
    L.finish("aborted")
end
local function hook_at(name, bank, addr, fn)
    if hook_sites[name] then return end
    hook_sites[name] = {bank=bank, addr=addr}
    local counts = {total=0, qualified=0, wrong_pc=0, wrong_banks={}, wrong_bank_samples=0}
    hook_counts[name] = counts
    L.hits[name] = 0
    L.ids[name] = event.on_bus_exec(function()
        if finished then return end
        local ok, why = pcall(function()
            counts.total = counts.total + 1
            local observed_bank, pc = L.rombank(), emu.getregister("PC")
            local matched = addr < 0x4000 or observed_bank == bank
            local metadata = {hook_site=name, hook_addr=addr, matched=matched, qualified=matched and pc == addr}
            if not matched then
                local key = string.format("%d", observed_bank)
                counts.wrong_banks[key] = (counts.wrong_banks[key] or 0) + 1
                if counts.wrong_bank_samples < WRONG_BANK_SAMPLE_LIMIT then
                    counts.wrong_bank_samples = counts.wrong_bank_samples + 1
                    snap("wrong_bank", metadata)
                end
                return
            end
            if pc ~= addr then
                counts.wrong_pc = counts.wrong_pc + 1
                if name == "GetScriptByte" then
                    if gsb_n >= 4000 then
                        if not overflow then overflow = true snap("gsb_overflow") end
                        return
                    end
                    gsb_n = gsb_n + 1
                end
                snap("wrong_pc", metadata) return
            end
            counts.qualified = counts.qualified + 1
            L.hit[name], L.hits[name] = emu.framecount(), counts.qualified
            if fn then fn(metadata) else snap(name, metadata) end
        end)
        if not ok then die(why) end
    end, addr, "pol_" .. name, "System Bus")
end
local function hook(name, fn)
    if S[name] then hook_at(name, S[name][1], S[name][2], fn)
    else snap("missing_symbol", {symbol=name}) end
end
local function rec(kind)
    return function(metadata) snap(kind, metadata) end
end

-- Write observations retain the supplied bus value, not a timing-dependent read of the destination.
-- Manual host accounting suppresses any callback triggered by Lua's debugger writes.
local function install()
    shadow = lease_bytes()
    for off = 0, 15 do
        local offset = off
        event.on_bus_write(function(_, value)
            if host_active or finished then return end
            local ok, why = pcall(function()
                if type(value) ~= "number" then
                    snap("instrumentation_error", {reason="bus write callback supplied no value"}) return
                end
                local before = copy(shadow)
                shadow[offset + 1] = value & 0xFF
                snap("rom_write", {offset=offset, value=value & 0xFF, before=before, lease=copy(shadow)})
            end)
            if not ok then die(why) end
        end, base + offset, "pol_service_lease_" .. offset, "System Bus")
    end
    hook("SlinkTradeEntry", function(metadata)
        entered, entry_frame = true, emu.framecount()
        local e = snap("service_entry", metadata)
        local target = L.bus(e.sp) | (L.bus(e.sp + 1) << 8)
        e.return_addr, e.return_bank = target, e.bank
        -- Independently derive the gate's CALL continuation, never trust a
        -- stack value merely because we can install a matching return hook.
        local gate = assert(S.SlinkTradeTimeoutGate, "missing timeout gate symbol")
        local continuation = gate[2] + 10 -- ld a,[addr]; cp; jr; call (3+2+2+3)
        if target ~= continuation or e.bank ~= gate[1] then
            die("service return does not match timeout-gate CALL continuation")
        end
        -- A CALL continuation observes SP AFTER RET; retain both boundaries.
        hook_at("service_return", gate[1], continuation, function(return_metadata)
            returned = true
            return_metadata.ret_sp = emu.getregister("SP") - 2
            snap("service_return", return_metadata)
        end)
    end)
    hook("SlinkTradeClose", rec("close"))
    hook("SlinkTradeCheckHeader", rec("check_header"))
    hook("Script_endtext", rec("endtext"))
    hook("SelectTradeOrDayCareMon", rec("party_menu"))
    hook("YesNoBox", rec("yesno"))
    hook("NoYesBox", rec("noyes"))
    hook("Special_TryQuickSave", rec("try_quicksave"))
    hook("SlinkTradeTimeoutGate", rec("timeout_gate"))
    hook("GetScriptByte", function(metadata)
        if gsb_n >= 4000 then
            if not overflow then overflow = true snap("gsb_overflow") end
            return
        end
        gsb_n = gsb_n + 1 snap("gsb", metadata)
    end)
end

local function host_write(address, bytes)
    assert(host_active and host_tx, "host write outside frame-end transaction")
    for i, value in ipairs(bytes) do
        local offset = address + i - 1 - base
        assert(offset >= 0 and offset < 16, "lease-only writer escaped lease")
        local before = copy(shadow)
        L.ww("wSlinkMailbox", Lease.OFF_LEASE + offset, value)
        shadow[offset + 1] = value
        snap("host_write", {tx=host_tx, offset=offset, value=value, before=before, lease=copy(shadow)})
    end
end
local function stage(payload)
    -- Intentionally stage ONLY the incoming slot 0 and sender. OT slot 1 belongs to ROM snapshot.
    local spans = {{"wOTPartyMon1", payload.record}, {"wOTPartyMonOTs", payload.ot},
                   {"wOTPartyMonNicknames", payload.nick}, {"wOTPlayerName", payload.sender}}
    for _, span in ipairs(spans) do
        for i, value in ipairs(span[2]) do
            local old = L.rw(span[1], i - 1)
            L.ww(span[1], i - 1, value)
            snap("host_stage_write", {tx=host_tx, symbol=span[1], offset=i-1, value=value, old=old})
        end
    end
    local staged = copy(payload.record) append(staged, payload.ot) append(staged, payload.nick)
    snap("staged", {tx=host_tx, staged_sum=checksum(staged), invalid=CASE == "apply-invalid",
        record=L.hex(payload.record), ot=L.hex(payload.ot), nick=L.hex(payload.nick), sender=L.hex(payload.sender),
        source_record=L.hex(L.wbytes("wPartyMon1", 0, 48)), source_ot=L.hex(L.wbytes("wPartyMonOTs", 0, 11)),
        source_nick=L.hex(L.wbytes("wPartyMonNicknames", 0, 11))})
end
local function valid_name(bytes, limit)
    for i = 1, limit do
        if bytes[i] == 0x53 then return true end
        if not bytes[i] or bytes[i] < 0x5F then return false end
    end
    return false
end
local function valid_record(record)
    if not Lease.valid_bytes(record, 48) then return false end
    local species = record[1] + ((record[22] & 0x20) << 3)
    return ((species >= 1 and species <= 0xFE) or (species >= 0x101 and species <= 0x123)) and
        record[2] == 0 and (record[21] & 0x1F) < 25 and record[32] >= 1 and record[32] <= 100
end
local function check_payload(payload)
    if not valid_record(payload.record) or L.hex(payload.record) ~= L.hex(L.wbytes("wPartyMon1", 0, 48)) then
        return "incoming must copy the valid itemless own mon 0"
    end
    if not Lease.valid_bytes(payload.ot, 11) or not Lease.valid_bytes(payload.nick, 11) or
       not Lease.valid_bytes(payload.sender, 11) or not valid_name(payload.ot, 8) or
       not valid_name(payload.sender, 11) then return "invalid staged OT/sender" end
    if CASE == "apply-invalid" then
        if valid_name(payload.nick, 11) then return "negative case requires no nickname terminator" end
    elseif not valid_name(payload.nick, 11) then return "invalid copied nickname" end
end
local binder = Lease.new({lease=base, party_capacity=6, check=check_payload, stage=stage},
    {read_u8=function(a) return L.rw("wSlinkMailbox", a - S.wSlinkMailbox[2]) end,
     read_range=function(a, n) return L.wbytes("wSlinkMailbox", a - S.wSlinkMailbox[2], n) end},
    {write_bytes=host_write})
local function transaction(name, fn)
    assert(not host_active)
    host_tx = name snap("host_begin", {tx=name, pump="onframeend"}) host_active = true
    local ok, why = fn()
    host_active = false snap("host_end", {tx=name}) host_tx = nil
    if not ok then die("test host " .. name .. ": " .. tostring(why)) end
end
local function incoming()
    local record, ot = L.wbytes("wPartyMon1", 0, 48), L.wbytes("wPartyMonOTs", 0, 11)
    local nick = L.wbytes("wPartyMonNicknames", 0, 11)
    local first = ot[1] == 0x80 and 0x81 or 0x80 -- distinct native name, A or B; metadata is preserved
    local sender = {}
    for i = 1, 11 do sender[i] = i == 1 and first or 0x53 end
    for i = 1, 8 do ot[i] = sender[i] end
    if CASE == "apply-invalid" then for i = 1, 11 do nick[i] = 0x80 end end
    return {record=record, ot=ot, nick=nick, sender=sender}
end
-- Exactly one host pump per emulator frame, outside any instruction/bus callback.
local function pump()
    local frame = emu.framecount()
    if not enabled or frame == last_pump then return end
    last_pump = frame
    if frame > (tonumber(os.getenv("POL_FRAME_CAP")) or 12000) then die("hard frame deadline") end
    if entered and not returned and frame - entry_frame > BUDGET then die("service deadline") end
    if not entered or returned then return end
    local q = binder:poll_query()
    if q and not query_answered and CASE ~= "query-timeout" then
        local own = L.wbytes("wPartyMon1", 0, 48)
        if L.rw("wPartyCount") < 1 or not valid_record(own) or (own[22] & 0x40) ~= 0 or
           (own[35] == 0 and own[36] == 0) then die("fixture mon 0 is not a real eligible living slot") end
        slot = 0 -- proven live itemless, non-egg record; native selection validates the same single bit
        transaction("query", function()
            if CASE == "no-eligible" then
                -- Deliberate boundary: available=1 AND mask=0 (helper's ordinary mask=0 answer uses available=0).
                host_write(base + 10, {1, 0, TOKEN[1], TOKEN[2], TOKEN[3], TOKEN[4]})
                host_write(base + 7, {q.gen}) return true
            end
            return binder:answer_query(q.gen, 1 << slot, TOKEN)
        end)
        query_answered = true snap("query_answered")
        return
    end
    local offer = binder:poll_offer()
    if offer and not offer_answered then
        snap("offer_observed")
        transaction("offer", function() return binder:answer_offer(offer.gen, CASE ~= "offer-reject") end)
        offer_answered = true snap("offer_answered")
        return
    end
    if offer_answered and not applied and CASE:sub(1, 6) == "apply-" then
        transaction("apply", function() return binder:arm(Lease.APPLY, slot, TOKEN, incoming()) end)
        applied = true snap("apply_published") return
    end
    local done = binder:poll_done()
    if done and not released then
        snap("done_observed", {result=done.result})
        if CASE ~= "apply-done1" or done.result ~= 1 then die("unexpected DONE (commit must remain disabled)") end
        transaction("release", function() return binder:release(binder.expected[7]) end)
        released = true snap("release_published")
    end
end
event.onframeend(function()
    if finished then return end
    local ok, why = pcall(pump)
    if not ok then
        if finished then error(why, 0) end
        die(why)
    end
end)

-- SYNTH setup matches the existing entry/return probe, not a direct RAM teleport.
local function run()
for _, name in ipairs({"OWPlayerInput", "SetInitialOptions.joypad_loop"}) do hook(name) end
if not L.to_overworld(24, 3, 60, 8000, "continue") then die("CONTINUE did not reach ROUTE_29") end
local ev = L.rw("wEventFlags", 4)
L.ww("wEventFlags", 4, ev | 0x02)
L.ww("wMapGroup", 0, 20) L.ww("wMapNumber", 0, 1)
L.ww("wXCoord", 0, 5) L.ww("wYCoord", 0, 3) L.ww("wDefaultSpawnpoint", 0, 0xFF)
memory.write_u8(S.hMapEntryMethod[2], 0xF1, "System Bus") L.ww("wMapStatus", 0, 1)
L.log("[service-probe] SYNTH wEventFlags+4 |= $02; engine warp to POKECENTER_2F (20:1) (5,3)")
L.log("[service-probe] TEST HOST ONLY: copied incoming mon 0 / distinct OT name in OT slot 0; no commit/server/client")
if not L.to_overworld(20, 1, 60, 3000, "warp-pc2f") then die("engine warp failed") end
L.check("POKECENTER_2F 8x4 at (5,3)", L.rw("wMapWidth") == 8 and L.rw("wMapHeight") == 4 and
        L.rw("wXCoord") == 5 and L.rw("wYCoord") == 3)
L.idle(60) install() enabled = true
snap("setup", {case=CASE, synth=true, token=TOKEN})
for _ = 1, 6 do L.frame({Up=true}) end L.idle(10)
local function wait_for(cond, bound, why, button)
    local start = emu.framecount()
    while not cond() do
        if emu.framecount() - start > bound then die(why) end
        if button then L.pulse(button) else L.frame() end
    end
end
wait_for(function() return (L.hits.YesNoBox or 0) >= 1 end, 900, "first receptionist prompt missing", "A")
local reached = function()
    for _, e in ipairs(trace) do if e.kind == "gsb" and e.sbank == 0x24 and e.spos == 0x7616 then return true end end
    return false
end
wait_for(reached, 400, "first prompt did not reach DoTradeOrBattle", "A")
snap("answer", {btn="A", which="receptionist"})
wait_for(function() return (L.hits.YesNoBox or 0) >= 2 end, 1500, "must-save prompt missing", "A")
L.idle(24) snap("answer", {btn="A", which="must-save"})
wait_for(function() return (L.hits.Special_TryQuickSave or 0) >= 1 end, 600, "quick-save entry missing", "A")
local saved_start, overwrite = emu.framecount(), false
while not entered do
    if emu.framecount() - saved_start > 1500 then die("quick-save did not enter service") end
    if not overwrite and (L.hits.NoYesBox or 0) >= 1 then
        overwrite = true L.idle(24)
        for _ = 1, 3 do L.frame({Down=true}) end L.idle(8)
        snap("answer", {btn="Down+A", which="overwrite"})
        for _ = 1, 3 do L.frame({A=true}) end
    end
    L.frame()
end
if CASE == "offer-reject" or CASE:sub(1, 6) == "apply-" or CASE == "cancel-menu" then
    wait_for(function() return (L.hits.SelectTradeOrDayCareMon or 0) >= 1 or returned end,
             700, "party menu missing")
    if returned then die("service exited before party menu") end
    L.idle(24)
    if CASE == "cancel-menu" then
        snap("answer", {btn="B", which="party"})
        wait_for(function() return returned end, 700, "B did not close service", "B")
    else
        snap("answer", {btn="A", which="party", slot=0})
        wait_for(function() return (L.hits.YesNoBox or 0) >= 3 or returned end,
                 700, "trade confirm missing", "A")
        if returned then die("service exited before trade confirm") end
        L.idle(24) snap("answer", {btn="A", which="confirm"})
        wait_for(function() return offer_answered or returned end, 700, "OFFER missing", "A")
        if not offer_answered then die("service exited before OFFER") end
    end
end
wait_for(function() return returned end, BUDGET, "service did not return")
wait_for(function() return L.rw("wScriptRunning") == 0 and L.ow_idle() end, 1500,
         "endtext did not restore player input")
L.idle(40) snap("final") snap("move_start")
local y0 = L.rw("wYCoord")
for i = 1, 48 do L.frame({Down=true}) if i >= 8 and L.rw("wYCoord") ~= y0 then break end end
L.idle(24) snap("move_end") snap("complete", {case=CASE})
dump(true) finished = true L.finish("trade-service-probe " .. CASE)
end
local ok, why = pcall(run)
if not ok then
    if finished then error(why, 0) end
    die(why)
end
