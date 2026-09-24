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
-- paint patterns. A CLIENT op under test goes through t.native.
--
-- TEST-ONLY RAW POSTER (card C5-4b). Companion ops the client never uses (PING, CREATE_MON, box
-- moves, FORCE_*, the EvRing, malformed stages for the patch guards) test the PATCH, not the client,
-- so native.lua's op surface does not grow for them. t.raw(op, args, stages) posts them with
-- native.lua's own ABI: writes:arm("native") over the real safety clauses, an allow window of exactly
-- the mailbox command bytes + the stages (each stage must sit inside one profile.native span from
-- write_checkpoint.json, never the mailbox header span), staging first, then args, ack = seq - 1, seq,
-- and the opcode LAST. It never shares a gate with a native.lua instance: t.raw refuses unless the gate
-- booted with native = false, so no native job can be queued, posted or polled around it. One raw job
-- in flight at a time; its receipt has the native.lua shape, with `reason` as the patch's raw FAIL
-- word (a number). A receipt needs ack == this job's seq AND a final status (OK/FAIL): ST_BUSY is an
-- armed async op, never a receipt. Like native.lua, a job that outlives its deadline (or a wait that
-- gives up on it) is finished with a "raw timeout" receipt naming the last status, and a timed-out or
-- partially written post POISONS the poster: every later t.raw fails the gate until t.boot (a
-- savestate load / reset is the recovery boundary, as for native.lua).
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
        if t.raw_job then
            t.raw_service()
        elseif t.native then
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
        if job and not job.receipt and job == t.raw_job then
            t.raw_expire(job, "no ack within " .. frames .. " frames")
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
        if not ok and job and job == t.raw_job then t.raw_expire(job, "never posted") end
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

    -- A fresh Safety + Writes (+ native instance unless with_native is false) over the entry.lua
    -- wiring (io surface, Safety, Writes, panel_closed).
    local function build_parts(kind, with_native)
        local L = function(rel) return dofile(ROOT .. "/" .. rel) end
        local title = full.titles.radical_red
        local wc = load_json(json, ROOT .. "/data/games/gen3_rr/write_checkpoint.json").radical_red
        t.spans = wc.native.spans
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
        t.writes, t.reads = writes, reads
        if with_native == false then return nil end
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
    -- opts.native  false = build no native.lua instance (required by t.raw)
    function t.boot(opts)
        opts = opts or {}
        pcall(function() client.speedmode(opts.speed or 6399)  -- max, as lua/tests/gatelib.lua; gates count frames, not wall time end)
        pcall(memory.usememorydomain, "System Bus")
        t.native, t.raw_job, t.raw_poisoned = nil, nil, nil
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
        t.native = build_parts(a.kind, opts.native)
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

    -- ── test-only raw poster (see the header) ───────────────────────────────────────────────
    -- Mailbox ABI v1 offsets: the same table as lua/gen3/native.lua (patch/src/ADDRESSES.md).
    local O = { opcode = 6, seq = 8, status = 10, ack = 12, reason = 14, args = 16, result = 48 }
    local ST_OK, ST_FAIL = 2, 3
    local RAW_DEADLINE = 1800          -- frames; longer than any patch-side async timeout (FMS 600)
    local function r16(a) return memory.read_u16_le(a, "System Bus") end
    -- A stage must sit inside one profile.native span and never touch the mailbox header span
    -- (BASE: signature, ABI, command bytes, result) -- native.lua never stages there either.
    local function span_of(addr, n)
        local B = t.P.BASE
        if addr < B + 64 and addr + n > B then return nil end
        for _, sp in ipairs(t.spans or {}) do
            if addr >= sp.start and addr + n <= sp.start + sp.size then return sp.key end
        end
    end
    local function last_status()
        local B = t.P.BASE
        return fmt("last status=%d ack=%d seq=%d opcode=%d", r16(B + O.status), r16(B + O.ack),
                   r16(B + O.seq), r16(B + O.opcode))
    end
    -- Finish a raw job that will never get a receipt. A posted op may still be owned by the patch,
    -- so, as in native.lua, the slot is never reused: the poster is poisoned until t.boot.
    function t.raw_expire(job, why)
        job.receipt = { why = "raw timeout: " .. why .. " (" .. last_status() .. ")", frame = t.frame }
        t.log("  " .. job.receipt.why)
        if t.raw_job == job then t.raw_job = nil end
        if job.posted and job.op then t.raw_poisoned = job.receipt.why end
    end
    local function try_post(job)
        local B = t.P.BASE
        local ranges = { { B + O.opcode, B + O.result } }
        for _, st in ipairs(job.stages) do ranges[#ranges + 1] = { st[1], st[1] + #st[2] } end
        local allow = function(addr, n)
            for _, r in ipairs(ranges) do
                if addr >= r[1] and addr + n <= r[2] then return true end
            end
            return false
        end
        local armed, why = pcall(function() t.writes:arm("native", allow) end)
        if not armed then t.last_service = "raw arm refused: " .. tostring(why); return false end
        local ok, err = pcall(function()
            assert(r16(B + O.opcode) == 0, "mailbox opcode pending")
            for _, st in ipairs(job.stages) do t.writes:write_bytes(st[1], st[2]) end
            if job.op then
                job.seq = (r16(B + O.seq) + 1) % 65536
                if #job.args > 0 then t.writes:write_bytes(B + O.args, job.args) end
                t.writes:write_u16(B + O.ack, (job.seq + 65535) % 65536)
                t.writes:write_u16(B + O.seq, job.seq)
                t.writes:write_u16(B + O.opcode, job.op)   -- publish last
            end
            job.posted = true
        end)
        t.writes:disarm()
        if not ok then
            job.receipt = { why = "raw post interrupted: " .. tostring(err), frame = t.frame }
            t.raw_job = nil
            t.raw_poisoned = job.receipt.why     -- a partial post: never post over it (native.lua)
        elseif not job.op then
            job.receipt = { why = nil, frame = t.frame }   -- stage-only: done when the bytes land
            t.raw_job = nil
        end
        return ok
    end
    function t.raw_service()
        local job = t.raw_job
        if t.frame > job.deadline then t.raw_expire(job, "deadline " .. RAW_DEADLINE .. " frames"); return end
        if not job.posted then try_post(job); return end
        local B = t.P.BASE
        local status = r16(B + O.status)
        if r16(B + O.ack) == job.seq and (status == ST_OK or status == ST_FAIL) then
            job.receipt = { why = status == ST_FAIL and "native refused" or nil,
                            result = memory.read_u8(B + O.result), reason = r16(B + O.reason),
                            frame = t.frame }
            t.raw_job = nil
        end
    end
    -- op: a profile.native key ("OP_PING"), a raw number (an unknown opcode), or nil (stage only).
    -- args: byte list. stages: {{addr, {bytes}}, ...}. Posts now if the window arms, else retries
    -- each step; returns the job (t.wait_posted / t.wait work on it).
    function t.raw(op, args, stages)
        assert(t.native == nil, "t.raw needs t.boot({native = false}): never beside a native.lua job")
        if t.raw_poisoned then t.fail("raw poster usable (not poisoned)", t.raw_poisoned) end
        if t.raw_job then t.fail("one raw op in flight at a time", "a previous raw job is still pending") end
        local code = type(op) == "string" and assert(t.P[op], "no " .. op .. " in profile.native") or op
        local job = { op = code, args = args or {}, stages = stages or {}, deadline = t.frame + RAW_DEADLINE }
        for _, st in ipairs(job.stages) do
            assert(span_of(st[1], #st[2]), fmt("stage 0x%08X+%d is outside every profile.native span "
                                              .. "(or touches the mailbox header)", st[1], #st[2]))
        end
        t.raw_job = job
        try_post(job)
        return job
    end
    -- Post, wait for the publish, then for the ack: returns receipt (nil = never posted / no ack), job.
    function t.raw_wait(op, args, stages, frames, drive)
        local job = t.raw(op, args, stages)
        if not t.wait_posted(job) then return nil, job end
        return t.wait(job, frames or 120, drive), job
    end
    function t.acked_ok(r) return r ~= nil and r.why == nil end
    -- Stage-only raw write into a native arena; true once the bytes landed.
    function t.raw_stage(stages)
        return t.wait_posted(t.raw(nil, nil, stages), 600)
    end

    -- FR-encode with the read facade's charmap, as native.lua's encode does ("\n" -> 0xFE,
    -- unknown -> 0, terminator appended, `limit` bytes max including it).
    function t.encode(text, limit)
        local out, codes = {}, t.reads.charmap.codes
        for _, cp in utf8.codes(tostring(text or "")) do
            if limit and #out >= limit - 1 then break end
            local g = utf8.char(cp)
            out[#out + 1] = g == "\n" and 0xFE or codes[g] or 0
        end
        out[#out + 1] = t.reads.charmap.terminator
        return out
    end

    -- ── DEFERRED-feature helpers (C5-4c): peer ghost (post-RC) and native text (off for the RC) ──
    -- Only the opt-in deferred gates use these; they are patch ABI, not client surface.
    local function le(v, n)
        local out = {}
        for i = 1, n do out[i] = v % 256; v = v // 256 end
        return out
    end
    -- GhostState (profile native.GH; handlers.c struct GhostState): +1 oeId, +6 s16 wx, +8 s16 wy,
    -- +10 face, +11 mv, +14 snap, +15 an, +16 run, +17 avatarDirty, +20 u32 imgs, +24 u32 anims.
    function t.player_oe()
        local id = memory.read_u8(t.P.GPLAYER_AVATAR + 0x05)
        if id >= 16 then id = 0 end
        return t.P.OBJECT_EVENTS_BASE + id * 0x24
    end
    -- GH->oeId, but only when that object event is really ours (active, localId == LOCALID): zeroed or
    -- stale EWRAM reads oeId 0, which must never count as a spawned ghost. 0xFF otherwise.
    function t.ghost_oe()
        local oe = memory.read_u8(t.P.GH + 1)
        if oe >= 16 then return 0xFF end
        local base = t.P.OBJECT_EVENTS_BASE + oe * 0x24
        if memory.read_u8(base) & 1 ~= 1 or memory.read_u8(base + 0x08) ~= t.P.LOCALID then return 0xFF end
        return oe
    end
    function t.ghost_set_pos(wx, wy, face, mv, an, run)
        local GH = t.P.GH
        return t.raw_stage({ { GH + 6, le(wx & 0xFFFF, 2) }, { GH + 8, le(wy & 0xFFFF, 2) },
            { GH + 10, { (face and face >= 1 and face <= 4) and face or 1, mv and mv ~= 0 and 1 or 0 } },
            { GH + 15, { an and (an & 0xFF) or 0, run and 1 or 0 } } })
    end
    function t.ghost_snap() return t.raw_stage({ { t.P.GH + 14, { 1 } } }) end
    -- imgs/anims: the partner's live sprite ROM ptrs; pcol_hex: 16 BGR555 u16 as "%04X" each.
    -- avatarDirty goes last so the patch applies a complete avatar.
    function t.ghost_set_avatar(imgs, anims, pcol_hex)
        local stages = { { t.P.GH + 20, le(imgs or 0, 4) }, { t.P.GH + 24, le(anims or 0, 4) } }
        if pcol_hex and #pcol_hex >= 64 then
            local pal = {}
            for i = 0, 15 do
                for _, b in ipairs(le((tonumber(pcol_hex:sub(i * 4 + 1, i * 4 + 4), 16) or 0) & 0xFFFF, 2)) do
                    pal[#pal + 1] = b
                end
            end
            stages[#stages + 1] = { t.P.GHOST_PAL_BUF, pal }
        end
        stages[#stages + 1] = { t.P.GH + 17, { 1 } }
        return t.raw_stage(stages)
    end
    function t.ghost_spawn(gfx) return t.raw_wait("OP_GHOST_SPAWN", { gfx or 0, t.P.LOCALID }, nil, 30) end
    function t.ghost_clear() return t.raw_wait("OP_GHOST_CLEAR", {}, nil, 30) end
    function t.peer_interact_count() return memory.read_u8(t.P.PI_COUNT) end

    -- TEXT_BUF stage for the message opcodes: FR text, optional colour prefix 0xFC 0x01 <id>,
    -- truncated to the 256-byte buffer (old client MB.write_message layout).
    function t.message_stage(text, color)
        local bytes = color and { 0xFC, 0x01, color } or {}
        for _, b in ipairs(t.encode(text, 256 - #bytes)) do bytes[#bytes + 1] = b end
        return { t.P.TEXT_BUF, bytes }
    end

    -- EvRing (profile native.EVR): wr @+0, rd @+1, overflow @+2, prim @+6, u32[8] ring @+8.
    -- init/drain write the read index / overflow through the raw poster's window.
    function t.events_init()
        local E = t.P.EVR
        return t.raw_stage({ { E + 1, { memory.read_u8(E) } }, { E + 2, { 0 } } })
    end
    function t.events_drain()
        local E, out = t.P.EVR, {}
        local wr, rd = memory.read_u8(E), memory.read_u8(E + 1)
        while rd ~= wr and #out < 8 do
            local v = memory.read_u32_le(E + 8 + (rd % 8) * 4)
            out[#out + 1] = { type = v & 0xFF, a = (v >> 8) & 0xFF, b = (v >> 16) & 0xFFFF }
            rd = (rd + 1) % 256
        end
        local ovf = memory.read_u8(E + 2) ~= 0
        local stages = { { E + 1, { rd } } }
        if ovf then stages[2] = { E + 2, { 0 } } end
        assert(t.raw_stage(stages), "EvRing drain write refused: " .. tostring(t.last_service))
        return out, ovf
    end

    return t
end

return Lib
