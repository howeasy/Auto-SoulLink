-- P1 capability only; coordinator runs this gate, never production clients.
-- BR: docs/rr_reference/BIZHAWK_MGBA_CALLBACKS.md:150-170:
-- callback addr=0800051A, raw R15=0800051C (NOT callback addr=...51C).
-- games/gen3_frlge.lua:85,211-212: return pointer; archive/gen3-old-client:lua/mailbox.lua:13,475:
-- 0203F800 is the signature/beacon, opcode is +6. No opcodes are dispatched.
-- Emerald (E2): the frame site is the pack's frame_control (CallCallbacks ENTRY 0800051C) and the
-- return site is battle_end's function entry, both read from data/games/gen3_emerald/engine_signals.json.
local WT = os.getenv("SLINK_ROOT")
assert(WT, "launch via tools/run_gate.py")
local OUT = WT .. "/patch/build/probe_gen3_hooks_result.txt"
local out = assert(io.open(OUT, "w"))
local ids, rows, samples = {}, {}, {}
local required = {a=true, ["b-base"]=true, d=true, e=true, g=true}
local armed, phase, errors, dropped = -1, "setup", 0, 0
local reset_seen = false
local function log(s) out:write(s .. "\n"); out:flush() end
local function row(name, status, detail)
    rows[name] = status
    local s = "PROBE " .. name .. " " .. status .. " " .. detail
    log(s); console.log(s)
end
local function hex(v) return type(v) == "number" and string.format("0x%08X", v) or tostring(v) end
local function step(n)
    for _ = 1, n do
        armed = emu.framecount(); emu.frameadvance()
        if phase == "reset" and emu.framecount() < armed then reset_seen = true end
    end
end
local function unregister(list)
    local ok = true
    for _, id in ipairs(list) do
        local success, result = pcall(event.unregisterbyid, id)
        ok = success and result ~= false and ok
    end
    return ok
end
local function register(kind, addr, name, fn, group)
    local ok, id = pcall(function()
        return event[kind](fn, addr, "SLink-gen3-probe-" .. name, "System Bus")
    end)
    local valid = ok and id ~= nil and id ~= false and tostring(id) ~= ""
        and tostring(id):gsub("[{}%-]", "") ~= string.rep("0", 32)
    if valid then ids[#ids+1] = id; if group then group[#group+1] = id end end
    log("REGISTER " .. name .. " addr=" .. hex(addr) .. " id=" .. tostring(id) .. " valid=" .. tostring(valid))
    return valid
end
local function observer(label, expected, exec, readaddr)
    local s = {n=0, bad=0, old_differs=0}
    local function fn(addr, val, flags)
        local ok, err = pcall(function()
            s.n = s.n + 1
            local pc, cpsr, frame = emu.getregister("R15"), emu.getregister("CPSR"), emu.framecount()
            s.r15 = s.r15 or pc
            if exec and (addr ~= expected or type(pc) ~= "number" or type(cpsr) ~= "number"
                or (cpsr & 32) == 0 or frame ~= armed) then s.bad = s.bad + 1 end
            local before = readaddr and memory.read_u8(readaddr, "System Bus") or nil
            if addr == readaddr and type(val) == "number" and before ~= (val & 255) then
                s.old_differs = s.old_differs + 1
            end
            if #samples < 16000 then
                samples[#samples+1] = string.format(
                    "HIT %s phase=%s addr=%s val=%s flags=%s r15=%s cpsr=%s T=%s mode=%s frame=%s armed=%s before=%s",
                    label, phase, hex(addr), hex(val), tostring(flags), hex(pc), hex(cpsr),
                    type(cpsr)=="number" and tostring((cpsr >> 5) & 1) or "?",
                    type(cpsr)=="number" and tostring(cpsr & 31) or "?",
                    tostring(frame), tostring(armed), tostring(before))
            else dropped = dropped + 1 end
        end)
        if not ok then errors = errors + 1; s.bad = s.bad + 1; s.error = tostring(err) end
    end
    return s, fn
end
local function main()
    local domains, sizes, scopes = {}, {}, {}
    for k, v in pairs(memory.getmemorydomainlist()) do
        local name = type(v) == "string" and v or k
        domains[name] = true; sizes[name] = memory.getmemorydomainsize(name)
        log("DOMAIN " .. tostring(name) .. " size=" .. tostring(sizes[name]))
    end
    local sok, available = pcall(function() return event.availableScopes() end)
    if sok and type(available) == "table" then
        for k,v in pairs(available) do scopes[type(v)=="string" and v or k] = true end
    end
    local pok, params = pcall(function() return event.can_use_callback_params("memory") end)
    row("g", domains["System Bus"] and domains.ROM and sizes.SRAM == 0x20000
        and scopes["System Bus"] and "PASS" or "FAIL",
        "flash=SRAM size=" .. tostring(sizes.SRAM) .. " scopes_bus=" .. tostring(scopes["System Bus"])
        .. " params_exists=" .. tostring(event.can_use_callback_params ~= nil)
        .. " params_call=" .. tostring(pok) .. " params=" .. tostring(params))
    assert(rows.g == "PASS", "required domains/scopes unavailable")
    local game = dofile(WT .. "/lua/games/gen3_frlge.lua")
    local variant = os.getenv("SLINK_PROBE_VARIANT") or game.detect_variant()
    assert(variant == "vanilla" or variant == "radical_red" or variant == "emerald", "unsupported probe profile")
    local p = assert(game.profiles[variant])
    local anchor, ret, base
    if variant == "emerald" then
        local f = assert(io.open(WT .. "/data/games/gen3_emerald/engine_signals.json", "rb"))
        local sites = dofile(WT .. "/lua/json_codec.lua").decode(f:read("a")).titles.emerald.artifacts.clean.sites
        f:close()
        -- Anchor = site.address + capture_offset, mirroring lua/gen3/signals.lua:94's own
        -- hook_address computation, not a bare site.address.
        anchor = math.floor(sites.frame_control.address + (sites.frame_control.capture_offset or 0))
        ret = math.floor(sites.battle_end.address + (sites.battle_end.capture_offset or 0))
        -- The watch base is write_checkpoint.json's own gMain.callback2 predicate (address +
        -- offset), not a literal "+4" beside a profile constant that happens to agree with it.
        local cf = assert(io.open(WT .. "/data/games/gen3_emerald/write_checkpoint.json", "rb"))
        local cp = dofile(WT .. "/lua/json_codec.lua").decode(cf:read("a")).emerald
        cf:close()
        local cb2 = assert(cp.predicates.callback2, "no callback2 predicate in write_checkpoint")
        base = math.floor(cb2.address + (cb2.offset or 0))
    else
        anchor, ret = 0x0800051A, assert(p.RETURN_FROM_BATTLE_ADDR) & ~1
        base = variant == "radical_red" and 0x0203F800 or p.GMAIN_ADDR + 4
    end
    log("BIND variant=" .. variant .. " return=" .. hex(ret) .. " watch=" .. hex(base))
    local primary = {}
    local a, af = observer("frame_control", anchor, true)
    local r, rf = observer("battle_return", ret, true)
    local ar = register("on_bus_exec", anchor, "frame", af, primary)
    local rr = register("on_bus_exec", ret, "return", rf, primary)
    local ws, wr = {}, {}
    for i, offset in ipairs({0,1,2}) do
        local fn; ws[i], fn = observer("write+" .. offset, base+offset, false, base+offset)
        wr[i] = register("on_bus_write", base+offset, "write" .. offset, fn, primary)
    end
    -- Negative candidate: ROM tail with 64 uniform filler bytes, not an ownership proof.
    local neg = sizes.ROM - 64
    local fill = memory.read_u8(neg, "ROM")
    local filler = fill == 0 or fill == 255
    for i=1,63 do filler = memory.read_u8(neg+i, "ROM") == fill and filler end
    local n, nf = observer("negative", 0x08000000+neg, true)
    local nr = filler and register("on_bus_exec", 0x08000000+neg, "negative", nf, primary)
    phase = "natural"
    -- Register BEFORE boot: vanilla callback2 need not change on an idle title screen.
    for _=1,2000 do step(1); if a.n >= 30 and ws[1].n > 0 then break end end
    row("a", ar and rr and a.n > 0 and a.bad == 0 and errors == 0 and dropped == 0 and "PASS" or "FAIL",
        "frame_hits=" .. a.n .. " bad=" .. a.bad .. " return_registration=" .. tostring(rr)
        .. " expected_addr=" .. hex(anchor) .. " first_raw_r15=" .. hex(a.r15))
    row("a-return", r.n > 0 and r.bad == 0 and "PASS" or "OPEN",
        "hits=" .. r.n .. " bad=" .. r.bad .. " battle_not_required=true")
    row("b-base", wr[1] and ws[1].n > 0 and ws[1].bad == 0 and "PASS" or "FAIL",
        "natural_hits=" .. ws[1].n .. " old_byte_differs_from_val=" .. ws[1].old_differs
        .. " pre_store_bytes_in_HIT=true width_and_origin_unavailable=true")
    row("b-interior", "OPEN", "registered=" .. tostring(wr[2] and wr[3])
        .. " plus1_hits=" .. ws[2].n .. " plus2_hits=" .. ws[3].n
        .. " overlap_counts_not_access_counts=true byte_halfword_word_origins_UNVERIFIED")
    phase = "host"
    local before, hits = memory.read_u8(base, "System Bus"), ws[1].n
    -- Same-value write, CPU frozen: do not corrupt callback2/signature or dispatch a command.
    local hostok, hosterr = pcall(memory.write_u8, base, before, "System Bus")
    row("c", hostok and memory.read_u8(base, "System Bus") == before and "PASS" or "OPEN",
        "same_value=true callback_delta=" .. (ws[1].n-hits) .. " error=" .. tostring(hosterr))
    row("e", nr and n.n == 0 and a.n > 0 and "PASS" or "FAIL",
        "addr=" .. hex(0x08000000+neg) .. " filler=" .. tostring(filler) .. " hits=" .. n.n
        .. " claim=observed_window_only")
    local removed = unregister(primary)
    local stopped = a.n + ws[1].n + ws[2].n + ws[3].n + r.n + n.n
    phase = "unregistered"; step(60)
    removed = removed and stopped == a.n+ws[1].n+ws[2].n+ws[3].n+r.n+n.n
    phase = "reset"
    local before_reset = emu.framecount()
    local resetok, reseterr = pcall(function() return client.reboot_core() end)
    reset_seen = emu.framecount() < before_reset
    local after, fn = observer("after_reset", anchor, true)
    local resetids = {}
    local regok = register("on_bus_exec", anchor, "after-reset", fn, resetids)
    for _=1,2000 do step(1); if after.n >= 30 then break end end
    local offok, count = unregister(resetids), after.n
    local live, livefn = observer("liveness", anchor, true)
    local liveids = {}
    local liveok = register("on_bus_exec", anchor, "liveness", livefn, liveids)
    step(60)
    row("d", removed and resetok and reseterr ~= false and reset_seen and regok and offok and count > 0 and after.n == count
        and after.bad == 0 and liveok and live.n > 0 and "PASS" or "FAIL",
        "removed=" .. tostring(removed) .. " reset_call=" .. tostring(resetok) .. " reset_seen=" .. tostring(reset_seen)
        .. " post_reset_hits=" .. count .. " after_unregister=" .. (after.n-count)
        .. " live_control=" .. live.n .. " reset_error=" .. tostring(reseterr))
    unregister(liveids)
    -- Conservative Thumb walk at the measured instruction start; stop at control transfer.
    -- No claim that merely aligned task/CB2 pointers outside first 64 KiB meet this budget.
    local candidates, pos = {}, anchor
    for _=1,12 do
        local h = memory.read_u16_le(pos-0x08000000, "ROM")
        if pos >= 0x08010000 or h == 0 or h == 0xFFFF then break end
        if (h & 0xF800) == 0xE000 or (h & 0xFF00) == 0xBD00 or (h & 0xFF00) == 0x4700 then break end
        candidates[#candidates+1] = pos
        log("BUDGET_SITE addr=" .. hex(pos) .. " halfword=" .. hex(h))
        if (h & 0xF800) == 0xF000 then
            local tail = memory.read_u16_le(pos-0x08000000+2, "ROM")
            if (tail & 0xF800) ~= 0xF800 then table.remove(candidates); break end
            pos = pos+4
        else pos = pos+2 end
    end
    local function measure()
        local start = os.time(); step(600); return os.difftime(os.time(), start)
    end
    phase = "budget_off"; local elapsedoff = measure()
    local budget, all = {}, true
    for i, addr in ipairs(candidates) do
        all = register("on_bus_exec", addr, "budget" .. i, function() end, budget) and all
    end
    phase = "budget_on"; local elapsedon = measure()
    unregister(budget)
    row("f", "OPEN", string.format("sites=%d registered=%s frames_off=600 frames_on=600 fps_off=%s fps_on=%s wall_clock_resolution_s=1 instruction_walk_UNVERIFIED=true",
        #candidates, tostring(all), elapsedoff>0 and tostring(600/elapsedoff) or "unresolved",
        elapsedon>0 and tostring(600/elapsedon) or "unresolved"))
end
local ok, err = pcall(main)
if not ok then row("fatal", "FAIL", tostring(err)) end
unregister(ids) -- best-effort cleanup even when a required API/observation failed
for _, s in ipairs(samples) do log(s) end -- per-hit evidence, file only; no per-frame console spam
log("COUNTERS callback_errors=" .. errors .. " dropped=" .. dropped)
local pass = ok and errors == 0 and dropped == 0
for name in pairs(required) do pass = rows[name] == "PASS" and pass end
log(pass and "RESULT: PASS" or "RESULT: FAIL"); out:close()
client.exit()
