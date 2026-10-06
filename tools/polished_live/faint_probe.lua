-- Natural-faint observation only. Coordinates/ROM bytes come from the Python contract.
-- No SLink client, memory writes, register changes, forced battles or synthetic setup.
local L = dofile(assert(os.getenv("SLINK_ROOT")) .. "/tools/polished_live/pol_lib.lua")
local config = L.json.decode(L.slurp(assert(os.getenv("POL_PROBE_CONFIG"))))
local C = assert(config.contract)
local trace, counts, ids = {}, {}, {}
local hits, stored, overflows, guest_writes, cpu_changes, driver_errors = 0, 0, 0, 0, 0, 0
local function append(kind, fields)
    local row = {kind=kind, ord=#trace + 1, frame=emu.framecount()}
    for key, value in pairs(fields or {}) do row[key] = value end
    trace[#trace + 1] = row
end

-- Guard probe-originated mutation attempts; the native game necessarily writes RAM.
local raw_memory, raw_emu = memory, emu
memory = setmetatable({}, {__index=function(_, name)
    if name:match("^write") then
        return function()
            guest_writes = guest_writes + 1
            if guest_writes == 1 then append("guest_write", {api="memory." .. name}) end
            error("read-only faint probe denied memory." .. name, 0)
        end
    end
    return raw_memory[name]
end})
emu = setmetatable({}, {__index=function(_, name)
    if name == "setregister" then
        return function()
            cpu_changes = cpu_changes + 1
            if cpu_changes == 1 then append("cpu_change", {api="emu.setregister"}) end
            error("read-only faint probe denied emu.setregister", 0)
        end
    end
    return raw_emu[name]
end})

local function byte(field, delta)
    local row = assert(C.ram[field], "missing contract RAM field")
    local value = memory.read_u8(row.offset + (delta or 0), row.domain)
    assert(type(value) == "number" and value >= 0 and value <= 255 and value % 1 == 0, "unreadable " .. field)
    return value
end
local function hp(field, delta)
    local hi, lo = byte(field, delta), byte(field, (delta or 0) + 1)
    return {hi, lo}, hi * 256 + lo
end
local function record(kind, site)
    hits, counts[kind] = hits + 1, counts[kind] + 1
    if stored >= config.trace_cap then return end
    stored = stored + 1
    local bank, pc, sp = byte("rombank"), emu.getregister("PC"), emu.getregister("SP")
    local slot, count = byte("slot"), byte("count")
    local valid = count >= 1 and count <= C.party_capacity and slot < count
    local battle_raw, battle_hp = hp("battle_hp")
    local party_raw, party_hp, party_status = false, false, false
    if valid then
        party_raw, party_hp = hp("party_hp", slot * C.party_stride)
        party_status = byte("party_status", slot * C.party_stride)
    end
    local bytes = {}
    for i = 0, #site.bytes / 2 - 1 do
        bytes[#bytes + 1] = memory.read_u8(site.rom_offset + i, "ROM")
    end
    append(kind, {hook_addr=site.addr, hook_bytes=L.hex(bytes), pc=pc, sp=sp, bank=bank,
        matched=bank == site.bank, qualified=bank == site.bank and pc == site.addr,
        slot=slot, count=count, party_slot_valid=valid, battle_hp_bytes=battle_raw, battle_hp=battle_hp,
        party_hp_bytes=party_raw, party_hp=party_hp, party_status=party_status,
        battle_status=byte("battle_status"), order=byte("order"), substatus2=byte("substatus2"),
        turn=byte("turn"), mode=byte("mode")})
    -- Capacity reached is already censored: never silently pass even without a later hook.
    if stored == config.trace_cap then
        overflows = overflows + 1
        append("overflow", {cap=config.trace_cap})
    end
end
local function api_text(fn)
    if type(fn) ~= "function" then return "UNAVAILABLE" end
    local ok, value = pcall(fn)
    return ok and tostring(value) or "UNAVAILABLE"
end
append("begin", {run_id=config.run_id, provenance=config.provenance,
    emulator_version=api_text(client.getversion), system=api_text(emu.getsystemid)})

local elapsed = 0
local ok, err = pcall(function()
    assert(C.schema == "polished-faint-probe-v1", "wrong probe contract")
    for kind, site in pairs(C.sites) do
        counts[kind] = 0
        ids[#ids + 1] = event.on_bus_exec(function()
            -- Callback exceptions may be swallowed by the emulator. Latch explicitly.
            local recorded, why = pcall(record, kind, site)
            if not recorded then
                driver_errors = driver_errors + 1
                if driver_errors == 1 then append("driver_error", {error=tostring(why), site=kind}) end
            end
        end, site.addr, "pol_faint_" .. kind, "System Bus")
    end
    client.speedmode(300)
    for _, step in ipairs(config.steps) do
        local buttons = {}
        for _, button in ipairs(step.buttons) do buttons[button] = true end
        for _ = 1, step.frames do L.frame(buttons); elapsed = elapsed + 1 end
    end
    while elapsed < config.frames do L.frame(); elapsed = elapsed + 1 end
end)
if not ok then
    driver_errors = driver_errors + 1
    append("driver_error", {error=tostring(err)})
end
for _, id in ipairs(ids) do event.unregisterbyid(id) end
append("final", {completed=ok and elapsed == config.frames, elapsed=elapsed,
    hook_hits=hits, counts=counts, guest_writes=guest_writes, cpu_changes=cpu_changes,
    overflows=overflows, driver_errors=driver_errors})
local f = assert(io.open(L.RUN .. "/trace.json", "w"))
f:write(L.json.encode(trace)); f:close()
L.check("complete read-only faint recording", ok and guest_writes == 0 and cpu_changes == 0
        and overflows == 0 and driver_errors == 0, "hook rows " .. stored .. "/" .. hits)
L.finish("faint-probe recording")
