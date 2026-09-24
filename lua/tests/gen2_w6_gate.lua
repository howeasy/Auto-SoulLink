--[[
  lua/tests/gen2_w6_gate.lua -- card gen2-p4-w6: the live write-watch TRIPWIRE over the SLink mailbox on the
  patched overlays (O-27 D1: writer exclusion is proven by tools/gen2_mailbox_census.py; this is the live
  tripwire only, docs/gen2/REVIEW_RECORD.md O-27).

  A wrapper, not a new corpus: it arms a bus-write callback on every byte of the mailbox span (the same
  event.onmemorywrite technique as the P4.1g minimum-SP witness in lua/tests/gen2_panel_gate.lua), then runs an
  EXISTING scripted gate unchanged (SLINK_GEN2_W6.gate: the panel gate, the sfx gate or the U1 frame-align gate)
  and classifies every CPU write into the span by its writer PC + hROMBank shadow:
    allowed   PC inside a SLink code range of the pinned overlay .sym (the whole service bank, the ROM0
              bridges, the bank-4 START entry; tests/live/test_gen2_w6_gate.w6_facts)
    boot      PC inside Init's inline WRAM0 clear loop, and only within W.INIT_WINDOW frames of an executed
              Init entry (a reset) or of the arming frame (the power-on boot, which precedes the script);
              outside that window it is a violation
    anything else is a VIOLATION, recorded with its PC/bank/address/frame.
  Lua writes into the span are tagged in the harness (every memory.write* is wrapped): a write whose call
  stack passes through the shipped client (lua/gen2/*.lua) or lua/write_permit.lua is the client's permitted
  write; any other Lua caller is a violation. A bus callback that fires INSIDE a Lua write is attributed to
  that Lua tag, never to whatever PC the CPU happens to be parked at.
  Known-positive controls (never part of the verdict above, reported under CONTROL):
    native    the identical callback + classifier armed on wVBlankOccurred, which native DelayFrame/VBlank
              code writes every frame: it MUST produce non-allowlisted writer PCs (the tripwire fires on a
              real native CPU writer).
    lua       after the inner gate, the harness itself rewrites one span byte with its current value (a
              no-op store) under a non-client tag: it MUST be caught as a Lua violation.
  Regions (facts.regions): SLink-owned NATIVE spans (main 2026-09-23: the P4.5b phone service writes the two-byte
  wSpecialPhoneCallID word). Native writers there are the game's own and only counted; a SLink code range
  may write one only if the region's slink_allow names it (empty until the phone service lands: until then
  any SLink write is a violation); any Lua store into a region is a violation. A region in WRAMX names its
  wram_bank and only writes with SVBK selecting that bank count.
  Environment: whatever the inner gate needs, plus SLINK_GEN2_W6 (json, tests/live/test_gen2_w6_gate.py).
  Result file: patch/build/gen2_w6_gate_result.txt. Printed: INNER (the inner gate's own RESULT line),
  W6 (json), then RESULT: PASS|FAIL last. The inner gate's full output stays in its own result file.
--]]
local W = {}
W.RESULT = "patch/build/gen2_w6_gate_result.txt"
W.SCHEMA = "gen2-w6-leg-v1"
W.INIT_WINDOW = 30      -- frames: Init's WRAM0 clear (8 KiB, one store per ~7 cycles) is ~1 frame after its entry
W.MAX_EVENTS = 50       -- violations kept verbatim (the count is exact beyond it)
W.CLIENT_SOURCES = {"lua/gen2/", "lua/write_permit.lua"}

local fmt = string.format

-- Pure: the allowed range name for a writer, or nil. `at` is the writing instruction's last byte:
-- Gambatte reports PC AFTER the store (live: Init's 2-byte `ld [hl], 0` at $01B1 reports $01B3; the
-- bridge's `ld [wVBlankOccurred], a` at $0065 reports $0068), so at = PC - 1. ROM0 ignores the shadow.
function W.allowed(ranges, at, bank)
    if at < 0x4000 then bank = 0 end
    for _, r in ipairs(ranges) do
        if r.bank == bank and at >= r.lo and at < r.hi then return r.name end
    end
end

-- Pure: classify one CPU write by its reported PC. Returns kind ("allowed"|"boot"|"violation"), label.
function W.classify(facts, pc, bank, frame, last_init)
    local at = pc - 1
    local name = W.allowed(facts.allow, at, bank)
    if name then return "allowed", name end
    local init = facts.init
    if at >= init.lo and at < init.hi then
        if last_init ~= nil and frame - last_init <= W.INIT_WINDOW then return "boot", init.name end
        return "violation", init.name .. " outside boot/reset"
    end
    return "violation", nil
end

-- Pure: the Lua tag for a call stack's sources (outermost last). A client source anywhere = client.
function W.lua_tag(sources)
    for _, src in ipairs(sources) do
        local s = src:gsub("\\", "/")
        for _, want in ipairs(W.CLIENT_SOURCES) do
            local at = s:find(want, 1, true)
            if at then return "client", s:sub(at) end
        end
    end
    return "harness", sources[1] or "?"
end

-- Pure: one CPU write into a SLink-owned native region. Returns kind ("slink"|"native"|"violation"), label.
function W.classify_region(facts, region, pc, bank)
    local name = W.allowed(facts.allow, pc - 1, bank)
    if name == nil then return "native", nil end
    for _, ok in ipairs(region.slink_allow) do if ok == name then return "slink", name end end
    return "violation", name .. " is not allowed to write " .. region.name
end

-- Pure: is a (domain, address) Lua write inside the span? System Bus uses bus addresses; "WRAM" is the
-- flat bank-0-first domain (C000 -> 0).
function W.in_span(span, addr, domain)
    if domain == nil or domain == "System Bus" then return addr >= span.lo and addr < span.hi end
    if domain == "WRAM" then return addr + 0xC000 >= span.lo and addr + 0xC000 < span.hi end
    return false
end

function W.new(facts)
    return {facts=facts, writers={}, boot={}, violations={}, n_violations=0, n_allowed=0, n_boot=0,
            lua={client={}, harness={}}, lua_fired=0, control={native={}, native_allowed=0, native_flagged=0},
            inits={}, lua_depth=0, regions={}}
end

local function bump(t, key) t[key] = (t[key] or 0) + 1 end

-- One CPU write into the span (or the control byte when control is true).
function W.observe(st, addr, pc, bank, frame, control)
    if st.lua_depth > 0 then   -- a Lua store, attributed to its tag (counted in the write wrapper)
        st.lua_fired = st.lua_fired + 1
        return
    end
    local kind, label = W.classify(st.facts, pc, bank, frame, st.inits[#st.inits])
    local key = fmt("%02X:%04X", pc < 0x4000 and 0 or bank, pc)
    if control then
        bump(st.control.native, key)
        if kind == "allowed" then st.control.native_allowed = st.control.native_allowed + 1
        else st.control.native_flagged = st.control.native_flagged + 1 end
        return
    end
    if kind == "allowed" then
        bump(st.writers, key)
        st.n_allowed = st.n_allowed + 1
    elseif kind == "boot" then
        bump(st.boot, key)
        st.n_boot = st.n_boot + 1
    else
        st.n_violations = st.n_violations + 1
        if #st.violations < W.MAX_EVENTS then
            st.violations[#st.violations + 1] = {pc=pc, bank=bank, addr=addr, frame=frame, why=label or "non-SLink writer"}
        end
    end
end

-- One CPU write into region r (its SVBK filter already applied).
function W.observe_region(st, r, addr, pc, bank, frame)
    local rec = st.regions[r.name]
    if st.lua_depth > 0 then rec.lua_fired = rec.lua_fired + 1 return end
    local kind, label = W.classify_region(st.facts, r, pc, bank)
    local key = fmt("%02X:%04X", pc < 0x4000 and 0 or bank, pc)
    bump(kind == "native" and rec.native or rec.slink, key)
    if kind == "violation" then
        st.n_violations = st.n_violations + 1
        if #st.violations < W.MAX_EVENTS then
            st.violations[#st.violations + 1] = {pc=pc, bank=bank, addr=addr, frame=frame, why=label}
        end
    end
end

-- One Lua store into the span. The control store is kept apart: its tag is the verdict under test.
function W.lua_write(st, kind, source, addr, frame, control)
    if control then st.control.lua_kind, st.control.lua_source = kind, source return end
    bump(st.lua[kind], source)
    if kind ~= "client" then
        st.n_violations = st.n_violations + 1
        if #st.violations < W.MAX_EVENTS then
            st.violations[#st.violations + 1] = {lua=source, addr=addr, frame=frame, why="non-client Lua write"}
        end
    end
end

function W.main(root, getenv)
    local json = dofile(root .. "/lua/json_codec.lua")
    local lines = {}
    local function log(s)
        lines[#lines + 1] = s
        local f = io.open(root .. "/" .. W.RESULT, "w")
        if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
    end
    local cfg = assert(json.decode(assert(getenv("SLINK_GEN2_W6"), "SLINK_GEN2_W6 missing")))
    local facts = cfg.facts
    local span = {lo=facts.span[1], hi=facts.span[2]}
    local st = W.new(facts)
    os.remove(root .. "/" .. cfg.inner_result)   -- a leftover inner verdict must never be read as this run's
    local running = assert(gameinfo.getromhash()):lower()
    assert(running == cfg.overlay_sha1, "running ROM is not the staged overlay")

    -- The watch: one callback per span byte + the native control byte, plus Init's entry.
    local handles = {}
    local function cpu_write(addr, control)
        return function()
            W.observe(st, addr, emu.getregister("PC"), memory.read_u8(facts.hrombank, "System Bus"),
                      emu.framecount(), control)
        end
    end
    for a = span.lo, span.hi - 1 do
        handles[#handles + 1] = event.onmemorywrite(cpu_write(a, false), a, "SLink-w6-" .. a, "System Bus")
    end
    for _, r in ipairs(facts.regions or {}) do
        st.regions[r.name] = {lo=r.lo, hi=r.hi, wram_bank=r.wram_bank, native={}, slink={}, lua={},
                              lua_fired=0, other_bank=0}
        for a = r.lo, r.hi - 1 do
            handles[#handles + 1] = event.onmemorywrite(function()
                if r.wram_bank then   -- CGB SVBK: 0 selects bank 1
                    local svbk = memory.read_u8(0xFF70, "System Bus") % 8
                    if (svbk == 0 and 1 or svbk) ~= r.wram_bank then
                        st.regions[r.name].other_bank = st.regions[r.name].other_bank + 1
                        return
                    end
                end
                W.observe_region(st, r, a, emu.getregister("PC"), memory.read_u8(facts.hrombank, "System Bus"),
                                 emu.framecount())
            end, a, "SLink-w6-" .. r.name .. "-" .. a, "System Bus")
        end
    end
    handles[#handles + 1] = event.onmemorywrite(cpu_write(facts.control, true), facts.control, "SLink-w6-control", "System Bus")
    handles[#handles + 1] = event.onmemoryexecute(function() st.inits[#st.inits + 1] = emu.framecount() end,
                                                  facts.init.entry, "SLink-w6-init", "System Bus")
    local armed_at = emu.framecount()
    -- The power-on Init runs before a --lua script is armed (live: armed at frame 1, the clear at frame 3,
    -- its entry unseen): the cold boot counts as the first Init entry. A later Init needs a real entry hit.
    st.inits[1] = armed_at

    -- Tag every Lua store. memory.* are userdata callables in a plain table: wrap in place.
    local control_lua = false
    local wrapped = {}
    for name, fn in pairs(memory) do
        if type(name) == "string" and name:find("^write") then wrapped[name] = fn end
    end
    for name, fn in pairs(wrapped) do
        memory[name] = function(addr, value, domain, ...)
            local hit = type(addr) == "number" and W.in_span(span, addr, domain)
            for _, r in ipairs(type(addr) == "number" and facts.regions or {}) do
                -- ponytail: bus address only; a region is never poked through a flat WRAMX domain offset here.
                if (domain == nil or domain == "System Bus") and addr >= r.lo and addr < r.hi then
                    bump(st.regions[r.name].lua, "any")
                    st.n_violations = st.n_violations + 1
                    st.violations[#st.violations + 1] = {lua="?", addr=addr, frame=emu.framecount(),
                                                         why="Lua store into " .. r.name}
                end
            end
            if hit then
                local sources = {}
                for level = 2, 40 do
                    local info = debug ~= nil and debug.getinfo(level, "S")
                    if not info then break end
                    sources[#sources + 1] = info.source
                end
                local kind, source = W.lua_tag(sources)
                W.lua_write(st, kind, source, addr, emu.framecount(), control_lua)
            end
            st.lua_depth = st.lua_depth + 1
            local ok, r = pcall(fn, addr, value, domain, ...)
            st.lua_depth = st.lua_depth - 1
            if not ok then error(r, 0) end
            return r
        end
    end

    -- The inner gate, run as its own top-level script. It ends in client.exit() + error("slink-gate-finished"):
    -- hold the exit until the watch has been read.
    local real_exit = client.exit
    client.exit = function() end
    local real_hash = gameinfo.getromhash
    if cfg.clean_view then   -- the U1 gate binds the CLEAN facts; the overlay moves no RAM symbol and
        -- every hooked site's bytes are re-validated against the running ROM (lua/gb_hook_binding.lua)
        gameinfo.getromhash = function() return cfg.base_sha1 end
    end
    local ok, why = pcall(dofile, root .. "/" .. cfg.gate)
    gameinfo.getromhash = real_hash
    local inner_done = ok or tostring(why):find("slink-gate-finished", 1, true) ~= nil
    local frames = emu.framecount() - armed_at

    -- Lua control: a no-op store (the byte's own value) under a non-client tag.
    local probe = span.lo + cfg.lua_control_offset
    control_lua = true
    memory.write_u8(probe, memory.read_u8(probe, "System Bus"), "System Bus")
    control_lua = false
    local lua_caught = st.control.lua_kind == "harness"

    for _, h in ipairs(handles) do pcall(event.unregisterbyid, h) end
    for name, fn in pairs(wrapped) do memory[name] = fn end

    local inner = ""
    local f = io.open(root .. "/" .. cfg.inner_result, "r")
    if f then
        for line in f:lines() do if line:find("^RESULT:") then inner = line end end
        f:close()
    end
    local native_ok = st.control.native_flagged > 0
    local pass = inner_done and inner:find("^RESULT: PASS") ~= nil and st.n_violations == 0 and st.n_allowed > 0
                 and native_ok and lua_caught
    log("INNER " .. (inner ~= "" and inner or ("no RESULT line; " .. tostring(why))))
    log("W6 " .. json.encode({schema=W.SCHEMA, leg=cfg.leg, gate=cfg.gate, overlay_sha1=running,
        evidence_level="PHYSICAL", armed_frame=armed_at, corpus_frames=frames, inner_completed=inner_done,
        span=json.array({span.lo, span.hi}), writers=st.writers, allowed_writes=st.n_allowed,
        boot_clear=st.boot, boot_writes=st.n_boot, init_entries=json.array(st.inits),
        lua_writes={client=st.lua.client, harness=st.lua.harness}, lua_callbacks_fired=st.lua_fired,
        violations=json.array(st.violations), violation_count=st.n_violations,
        regions=st.regions,
        control={native_addr=facts.control, native_writers=st.control.native,
                 native_allowed=st.control.native_allowed, native_flagged=st.control.native_flagged,
                 native_caught=native_ok, lua_addr=probe, lua_caught=lua_caught,
                 lua_kind=st.control.lua_kind or json.null, lua_source=st.control.lua_source or json.null}}))
    log(fmt("RESULT: %s w6 %s (%d violations, %d allowed writes, native control %s, lua control %s)",
            pass and "PASS" or "FAIL", cfg.leg, st.n_violations, st.n_allowed,
            native_ok and "caught" or "MISSED", lua_caught and "caught" or "MISSED"))
    client.exit = real_exit
    client.exit()
end

if SLINK_GEN2_GATE_LIBRARY then return W end

local ROOT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(ROOT, "SLINK_ROOT unset -- launch via tools/run_gb_gate.py")
W.main(ROOT, os.getenv)
error("slink-gate-finished", 0)   -- client.exit() is asynchronous; stop here for real
