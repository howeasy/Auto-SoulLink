-- lua/tests/gen3_gatelib.lua — headless harness for the RR companion opcode gates, bound to the
-- NEW Gen 3 client's native layer (lua/gen3/native.lua). PLAN §4 / §14 P5, card C5-4.
--
-- Replaces the old binding (lua/mailbox.lua over lua/memory_gba.lua). A gate drives native.lua the
-- way production does: ONE injected instance over the real lua/gen3/writes.lua sink and the real
-- lua/gen3/safety.lua "native" clause set, serviced once per frame at frame end (t.step). Only the
-- send() sink and the done() receipts belong to the harness, so every opcode reaches the patch
-- through the same queue, staging, seq/ack and write window the client uses. The wiring mirrors
-- lua/gen3/entry.lua build_production minus the client: the client's eligibility wrapper refuses
-- every native arm until a server hello, and a gate has no server.
--
--   local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
--   local t = G.open("menu")          -- patch/build/menu_result.txt (tools/run_gate.py _GOPEN_RE)
--   t.boot({ state = "slink_overworld.State" })  -- admit, build native, wait for the beacon
--   local job = t.watch(t.native:show_menu({ token = 1, text = "Trade?" }))
--   local r = t.wait(job, 300, function(i) return i % 2 == 0 and { A = true } or nil end)
--   t.check("acked OK", r ~= nil and r.why == nil); t.finish()
--
-- Receipts: a job's `receipt` is {why, result, reason, frame}, set when native.lua finishes it.
-- why == nil is the patch's ST_OK, "native refused" its ST_FAIL (reason = the named FAIL word),
-- anything else is native.lua's own refusal (absent, poisoned, timeout, arm refused).
--
-- Raw memory access in a gate is INSTRUMENTATION only: preconditions, oracles, player placement,
-- paint patterns. The op under test always goes through t.native. An op native.lua does not expose
-- is a GAP in tests/live/test_lua_gates.py, never a raw post from here.
--
-- Log/check/finish are the lua/tests/gen1_gate.lua shape; gatelib.lua keeps its copies inside
-- Lib.start (GB-only), so there is nothing exported to reuse.
local Lib = {}

Lib.STATE_DIR = (os.getenv("SLINK_BIZHAWK_HOME") or "E:/Howard/Bizhawk") .. "/GBA/State"

local function load_json(json, path)
    local f = assert(io.open(path, "rb"), "cannot open " .. path)
    local text = f:read("a")
    f:close()
    return assert(json.decode(text))
end

function Lib.open(name)
    local ROOT = assert(SLINK_ROOT or os.getenv("SLINK_ROOT"),
                        "SLINK_ROOT unset — launch via tools/run_gate.py")
    package.path = ROOT .. "/lua/?.lua;" .. package.path
    local OUT = (SLINK_GATE_OUT or (ROOT .. "/patch/build")) .. "/" .. name .. "_result.txt"
    local fmt = string.format
    local json = dofile(ROOT .. "/lua/json_codec.lua")
    local full = load_json(json, ROOT .. "/data/games/gen3_rr/profile.json")
    local t = {
        ROOT = ROOT, name = name, frame = 0, failures = 0, lines = {}, sent = {},
        P = assert(full.native, "gen3_rr profile has no native block"),
        ram = full.titles.radical_red.ram,
    }

    function t.log(s)
        console.log(s)
        t.lines[#t.lines + 1] = s
        local f = io.open(OUT, "w")
        if f then f:write(table.concat(t.lines, "\n") .. "\n"); f:close() end
    end
    function t.check(what, ok, detail)
        if not ok then t.failures = t.failures + 1 end
        t.log(fmt("  [%s] %s%s", ok and "ok" or "FAIL", what,
                  detail ~= nil and ("  — " .. tostring(detail)) or ""))
        return ok
    end
    function t.finish(extra)
        t.log(fmt("RESULT: %s %s (%d checks failed)", t.failures == 0 and "PASS" or "FAIL",
                  extra or name, t.failures))
        client.exit()
        error("slink-gate-finished", 0)     -- client.exit() is async; stop here for real
    end
    function t.fail(what, detail) t.check(what, false, detail); t.finish() end

    -- One frame, then native:service() at frame end, exactly where lua/gen3/run.lua runs it.
    function t.step(buttons)
        if buttons then joypad.set(buttons) end
        emu.frameadvance()
        t.frame = t.frame + 1
        if t.native then
            local ok, err, why = pcall(t.native.service, t.native)
            t.last_service = ok and why or nil     -- e.g. "native arm refused: ..." while queued
            if not ok and not t.service_error then
                t.service_error = tostring(err)
                t.log("native:service raised: " .. t.service_error)
            end
        end
    end
    function t.idle(frames) for _ = 1, frames do t.step(nil) end end
    function t.tap(btn, frames)
        for f = 1, (frames or 20) do t.step(f <= 3 and { [btn] = true } or nil) end
    end

    -- The raw beacon, independent of the admitted kind (native:idle() treats absence as idle, and
    -- native.lua's own present() also requires kind == companion, so neither can be the oracle).
    function t.present()
        return memory.read_u32_le(t.P.BASE) == t.P.SIG and memory.read_u16_le(t.P.BASE + 4) == t.P.ABI
    end

    function t.watch(job)
        if type(job) ~= "table" then return nil end
        local inner = job.done
        job.done = function(why, result, reason)
            job.receipt = { why = why, result = result, reason = reason, frame = t.frame }
            if inner then return inner(why, result, reason) end
        end
        return job
    end
    -- Step until the job has a receipt (or `frames` run out). drive(i) -> buttons for frame i.
    function t.wait(job, frames, drive)
        for i = 1, frames do
            if not job or job.receipt then break end
            t.step(drive and drive(i) or nil)
        end
        return job and job.receipt
    end
    -- Step until native.lua has PUBLISHED the job's opcode (job.posted) or finished it. A job whose
    -- write window is refused stays queued and is retried every frame, so a cold boot needs budget.
    function t.wait_posted(job, frames)
        for _ = 1, (frames or 600) do
            if not job or job.posted or job.receipt then break end
            t.step(nil)
        end
        local ok = job ~= nil and job.posted == true
        if not ok and t.last_service then t.log("  last native:service refusal: " .. t.last_service) end
        return ok
    end
    function t.receipt_str(r)
        if not r then return "no receipt" end
        return fmt("why=%s result=%s reason=%s", tostring(r.why), tostring(r.result), tostring(r.reason))
    end
    function t.sent_of(event)
        local out = {}
        for _, s in ipairs(t.sent) do if s.event == event then out[#out + 1] = s.fields end end
        return out
    end
    function t.read_blob(addr, n)
        local b = {}
        for j = 1, (n or 100) do b[j] = memory.read_u8(addr + j - 1) end
        return b
    end
    function t.hex(bytes)
        local out = {}
        for i, b in ipairs(bytes) do out[i] = fmt("%02X", b) end
        return table.concat(out)
    end

    local admitted
    local function admit()
        if admitted then return admitted end
        local Entry = dofile(ROOT .. "/lua/gen3/entry.lua")
        local function rom_read(off, len)
            local out = {}
            for i = 1, len do out[i] = memory.read_u8(off + i - 1, "ROM") end
            return out
        end
        local ok_hc, code = pcall(Entry.header_code, rom_read)
        local why
        admitted, why = Entry.admit({
            root = ROOT, json = json, rom_read = rom_read, header_code = ok_hc and code or "",
            rom_hash = gameinfo and gameinfo.getromhash and gameinfo.getromhash() or "",
        })
        if not admitted then t.fail("cartridge admitted by lua/gen3/entry.lua", why) end
        return admitted
    end

    -- A fresh native instance over the entry.lua wiring (io surface, Safety, Writes, panel_closed).
    local function build_native(kind)
        local L = function(rel) return dofile(ROOT .. "/" .. rel) end
        local title = full.titles.radical_red
        local wc = load_json(json, ROOT .. "/data/games/gen3_rr/write_checkpoint.json").radical_red
        local io_ = {
            read_u8    = function(a) return memory.read_u8(a, "System Bus") end,
            read_u16   = function(a) return memory.read_u16_le(a, "System Bus") end,
            read_u32   = function(a) return memory.read_u32_le(a, "System Bus") end,
            read_bytes = function(a, n)
                local out = {}
                for i = 1, n do out[i] = memory.read_u8(a + i - 1, "System Bus") end
                return out
            end,
            framecount = function() return emu.framecount() end,
            write_u8   = function(a, v) return memory.write_u8(a, v, "System Bus") end,
        }
        local reads = L("lua/gen3/reads.lua").new(title, io_, wc.pointers)
        local native
        local safety = L("lua/gen3/safety.lua").new(wc, {
            io = {
                read_u8 = function(a, domain)
                    if domain == "ROM" then return memory.read_u8(a, "ROM") end
                    return io_.read_u8(a)
                end,
                read_u16_le = function(a) return io_.read_u16(a) end,
                read_u32_le = function(a) return io_.read_u32(a) end,
            },
            regs = function() return { R15 = emu.getregister("R15"), CPSR = emu.getregister("CPSR") } end,
            native_idle = function() return native == nil or native:idle() end,
        }, kind)
        local writes = L("lua/gen3/writes.lua").new({
            safety = safety, frame = io_.framecount, io = io_,
            log = function(r) t.writes_log[#t.writes_log + 1] = r end,
        })
        local status = wc.predicates and wc.predicates.script_context_status
        native = L("lua/gen3/native.lua").new(full, {
            io = io_, writes = writes, reads = reads, array = json.array, artifact_kind = kind,
            send = function(event, fields) t.sent[#t.sent + 1] = { event = event, fields = fields } end,
            panel_closed = function()                  -- entry.lua's binding, verbatim in effect
                if not status then return true, 1 end
                local v = io_.read_u8(status.address + (status.offset or 0))
                if status.mask then v = v & status.mask end
                return v == status.expect, 1
            end,
        })
        return native
    end

    -- opts.state   savestate file in Lib.STATE_DIR (nil = cold boot)
    -- opts.kind    admitted artifact kind required ("companion" default; "clean" for absent)
    -- opts.beacon  frames to wait for the beacon (default 600); false = do not wait
    function t.boot(opts)
        opts = opts or {}
        pcall(function() client.speedmode(opts.speed or 400) end)
        pcall(memory.usememorydomain, "System Bus")
        t.native = nil
        if opts.state then
            local ok = pcall(savestate.load, Lib.STATE_DIR .. "/" .. opts.state)
            if not ok then t.fail("savestate loaded", Lib.STATE_DIR .. "/" .. opts.state) end
        end
        t.step(nil)
        local a = admit()
        local want = opts.kind or "companion"
        if a.pack ~= "gen3_rr" or a.kind ~= want then
            t.fail("cartridge is gen3_rr/" .. want, fmt("admitted %s/%s/%s by %s", a.pack,
                   a.title, a.kind, a.admitted_by))
        end
        t.kind, t.sent, t.writes_log = a.kind, {}, {}
        t.native = build_native(a.kind)
        if opts.beacon ~= false then
            local up = t.present()
            for _ = 1, (opts.beacon or 600) do
                if up then break end
                t.step(nil)
                up = t.present()
            end
            if not up then t.fail("'SLNK' beacon up (companion hook running)", "frame " .. t.frame) end
        end
        return t
    end

    return t
end

return Lib
