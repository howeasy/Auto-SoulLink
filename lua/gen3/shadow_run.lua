--[[
  lua/gen3/shadow_run.lua — P3 shadow observer bootstrap (PLAN §5.7, §4).

  Loaded by the duo stub (lua/tests/duo/duo_main.lua) AFTER
  archive/gen3-old-client:lua/clients/gen3_frlge_client.lua, only when SLINK_SHADOW is set. It builds a SECOND,
  read-only client instance over `gen3.entry` (deps.mode = "observer") that runs alongside
  the old production client and never touches game state: `deps.io` decodes memory but every
  write_* throws, `deps.net`/`deps.hud` are nil, every BizHawk hook it registers is named
  "SLink-gen3-shadow-*", and it never calls console.clear/gui.*/joypad.*/savestate.*/
  client.saveram/client.exit. Its only job is to prove the hook mechanism sees the same
  engine signals the old client's polling does (the real falsifier), by logging one line per
  semantic signal.

  ── SHADOW line format (tools/gen3_shadow_diff.py parses this — keep both in sync) ─────────
    SHADOW t=<n> frame=<n> kind=<name> key=<key> [field=value ...]
      t     1-based, strictly increasing for the lifetime of this observer instance. Proves a
            replay wasn't dropped/duplicated/misordered (PLAN §5.7 mutation test).
      frame emu.framecount() at capture.
      kind  the semantic signal name from parts.signals (e.g. "faint", "capture", "box_to_box").
      key   the mon key "PID:OTID" (hex:hex) for a mon-scoped signal, or a slot/box locator
            ("slot:<n>", "box:<box>:<idx>") when no mon key is available yet.
      remaining fields are free-form key=value tokens (no spaces, no "="), signal-specific —
            e.g. callback_addr=0x..., raw_r15=0x....
    One line per queued signal fire; this file does not filter hello/tick/safe/acks (those are
    wire-protocol concepts the old client emits, not engine signals) — semantic exclusion for
    the old-client side of the diff is tools/gen3_shadow_diff.py's job, not this file's.

  ── Isolation contract (PLAN §5.7) ──────────────────────────────────────────────────────────
    * deps.io: every read_* passes through to real BizHawk memory; every write_* throws
      (M.build_io).
    * deps.ev: wraps event.on_bus_exec/unregister so every hook name is prefixed
      "SLink-gen3-shadow-" and teardown() unregisters ONLY the ids this instance registered
      (M.build_ev).
    * deps.net = nil, deps.hud = nil.
    * M.mutation_stubs() names the BizHawk globals this file promises never to call
      (joypad.set, savestate.load/save, client.saveram/exit, console.clear, gui.text) so the
      isolation test can assert each one throws if ever reached.
--]]

local M = {}

-- ── generic "this is a mutation sink" refusal ───────────────────────────────────────────────
local function refuse(name)
    return function()
        error("gen3 shadow observer: " .. name .. " is a mutation sink; shadow_run.lua is read-only (PLAN §5.7)", 2)
    end
end

local WRITE_SINKS = { "write_u8", "write_u16", "write_u32", "write_bytes" }

-- M.build_io(mem, reg): a read-only io matching the CONTRACT lua/gen3/entry.lua documents
-- (`deps.io`: read_u8/read_u16/read_u32(addr), read_bytes(addr, len), rom_read(off, len),
-- framecount(), register(name)) -- no domain argument, unlike BizHawk's own `memory.*`. `mem`
-- is a BizHawk-shaped memory table (real `memory` in production, a fake in tests) whose reads
-- DO take a domain ("System Bus" for the bus reads, "ROM" for rom_read); `reg` is
-- function(name) -> number, i.e. `emu.getregister` in production. Every read forwards
-- unchanged; every write_* throws.
function M.build_io(mem, reg, framecount)
    -- `framecount` is emu.framecount in production (memory.* has no frame counter: PHYSICAL,
    -- RR explode duo 2026-09-21, the first fire died here); a fake mem may carry its own.
    local io_ro = {
        read_u8    = function(addr) return mem.read_u8(addr, "System Bus") end,
        read_u16   = function(addr) return mem.read_u16_le(addr, "System Bus") end,
        read_u32   = function(addr) return mem.read_u32_le(addr, "System Bus") end,
        read_bytes = function(addr, len)
            local out = {}
            for i = 1, len do out[i] = mem.read_u8(addr + i - 1, "System Bus") end
            return out
        end,
        rom_read = function(off, len)
            local out = {}
            for i = 1, len do out[i] = mem.read_u8(off + i - 1, "ROM") end
            return out
        end,
        framecount = function()
            if framecount then return framecount() end
            return mem.framecount()
        end,
        register   = function(name) return reg(name) end,
    }
    for _, name in ipairs(WRITE_SINKS) do
        io_ro[name] = refuse(name)
    end
    return io_ro
end

-- M.build_ev(ev, prefix): wraps event.on_bus_exec/unregisterbyid so every hook THIS observer
-- registers is named "<prefix><name>" and its id is tracked. teardown() unregisters exactly
-- those ids (never "all", never a caller-supplied foreign id) — unregister() on an id this
-- instance did not register is itself refused, so a bug can't silently tear down someone
-- else's hook.
function M.build_ev(ev, prefix)
    local ids = {}
    local wrapped = {}
    wrapped.on_bus_exec = function(fn, addr, name)
        local id = ev.on_bus_exec(fn, addr, prefix .. tostring(name))
        ids[#ids + 1] = id
        return id
    end
    wrapped.unregister = function(id)
        for i, known in ipairs(ids) do
            if known == id then
                table.remove(ids, i)
                return ev.unregisterbyid(id)
            end
        end
        error("gen3 shadow observer: refusing to unregister an id it did not register: " .. tostring(id), 2)
    end
    wrapped.teardown = function()
        for _, id in ipairs(ids) do ev.unregisterbyid(id) end
        ids = {}
    end
    wrapped.registered_ids = function()
        local out = {}
        for i, id in ipairs(ids) do out[i] = id end
        return out
    end
    return wrapped
end

-- M.mutation_stubs(): the exact BizHawk entry points this observer promises never to reach for
-- (over and above the write_* sinks in deps.io, which entry/writes.lua would go through). Not
-- wired into `deps` — the isolation test calls these directly to prove the promise is checkable.
function M.mutation_stubs()
    return {
        joypad    = { set = refuse("joypad.set") },
        savestate = { load = refuse("savestate.load"), save = refuse("savestate.save") },
        client    = { saveram = refuse("client.saveram"), exit = refuse("client.exit") },
        console   = { clear = refuse("console.clear") },
        gui       = { text = refuse("gui.text") },
    }
end

-- M.format_shadow_line: pure formatter for the SHADOW line documented above. `extra` is an
-- ordered array of {key, value} pairs (plain Lua tables have no order, so pairs come as a list).
function M.format_shadow_line(t, frame, kind, key, extra)
    local buf = { "SHADOW", "t=" .. tostring(t), "frame=" .. tostring(frame),
                  "kind=" .. tostring(kind), "key=" .. tostring(key) }
    if extra then
        for _, kv in ipairs(extra) do
            if kv[2] ~= nil then buf[#buf + 1] = tostring(kv[1]) .. "=" .. tostring(kv[2]) end
        end
    end
    return table.concat(buf, " ")
end

-- M.make_signal_reader(signals): the ONE adapter over lua/gen3/signals.lua's real object
-- (S.new returns `self` with COLON methods -- `function self:drain()` at signals.lua:150 --
-- so it must be called as `signals:drain()`/`signals:on_fire(...)`, never with a dot, or the
-- missing `self` argument breaks it at runtime). Prefers `drain()` (a catch-all queue, no
-- kind list needed up front; this is the only method signals.lua actually ships). Falls back
-- to an `on_fire(kind, fn)` method IF a future signals surface adds one, queued into an
-- equivalent drain. Returns poll(), called once per frame, returning the fires queued since
-- the last call. If the real surface changes again, this is the only function to fix.
function M.make_signal_reader(signals)
    if type(signals.drain) == "function" then
        return function() return signals:drain() end
    end
    if type(signals.on_fire) == "function" then
        local queued = {}
        signals:on_fire("*", function(fire) queued[#queued + 1] = fire end)
        return function()
            local out = queued
            queued = {}
            return out
        end
    end
    error("gen3 shadow observer: parts.signals exposes neither drain() nor on_fire(kind, fn)", 2)
end

-- M.start(opts): the production bootstrap. Reads config from SLINK_SHADOW (a truthy flag, or a
-- table of {pack, title, kind, player} overrides) and SLINK_DUO (for the result-log path and a
-- player fallback); no-ops (returns nil) when SLINK_SHADOW is unset, so dofile'ing this file
-- costs nothing when shadow mode is off. `opts` lets a caller (or a test) inject the BizHawk
-- globals (memory/event/emu/console/gameinfo/os.getenv) instead of reading them off _G.
--
-- pack/title/kind resolution: `Entry.admit` (PLAN §5.1), never a hard guess, UNLESS opts/
-- SLINK_SHADOW names them explicitly. `gameinfo.getromhash()` supplies the hash path for free
-- (BizHawk computes it, not Lua); the anchor path costs a few hundred `rom_read` bytes -- both
-- are cheap. entry.lua deliberately ships no pure-Lua SHA-1 over the cartridge (its own note:
-- minutes for a 32 MiB ROM), so this file doesn't add one either. If admission still can't
-- decide (no gameinfo, e.g. under a fake test harness with no ROM), fall back to FR clean so a
-- duo run never crashes for want of a title.
function M.start(opts)
    opts = opts or {}
    -- SLINK_SHADOW is either a Lua global (bool/1, or a table of overrides — future e2e_duo
    -- wiring) or a process env var (run_gate.py --shadow, os.getenv per the self-location
    -- reference: a dofile'd chunk sees an inherited env var same as a --lua= top-level script).
    local getenv = opts.getenv or os.getenv
    local shadow_cfg = opts.shadow
    if shadow_cfg == nil then shadow_cfg = _G.SLINK_SHADOW end
    if shadow_cfg == nil then shadow_cfg = getenv("SLINK_SHADOW") end
    if not shadow_cfg or shadow_cfg == "" then return nil end
    local cfg = type(shadow_cfg) == "table" and shadow_cfg or {}
    local duo = opts.duo or _G.SLINK_DUO

    local mem_g      = opts.memory   or memory
    local event_g    = opts.event    or event
    local emu_g      = opts.emu      or emu
    local console_g  = opts.console  or console
    local gameinfo_g = opts.gameinfo or gameinfo

    local src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
    local lua_root = src:match("(.+[/\\])gen3[/\\]") or src
    local proj_root = lua_root:match("(.+[/\\])lua[/\\]") or (lua_root .. "../")
    package.path = lua_root .. "?.lua;" .. package.path

    local io_ro = M.build_io(mem_g, function(name) return emu_g.getregister(name) end,
                             function() return emu_g.framecount() end)
    local json = dofile(proj_root .. "lua/json_codec.lua")
    local Entry = require("gen3.entry")

    local pack, title, kind = opts.pack or cfg.pack, opts.title or cfg.title, opts.kind or cfg.kind
    local admitted_by = "override"
    if not (pack and title and kind) then
        local rom_hash = ""
        if gameinfo_g and gameinfo_g.getromhash then
            local ok, h = pcall(gameinfo_g.getromhash)
            if ok and h then rom_hash = h end
        end
        local ok_hc, header_code = pcall(Entry.header_code, io_ro.rom_read)
        local admitted = Entry.admit({ root = proj_root, json = json, rom_hash = rom_hash,
                                       rom_read = io_ro.rom_read,
                                       header_code = ok_hc and header_code or "" })
        if admitted then
            pack, title, kind = pack or admitted.pack, title or admitted.title, kind or admitted.kind
            admitted_by = admitted.admitted_by
        else
            admitted_by = "default"
        end
    end
    pack  = pack  or "gen3_frlg"
    title = title or "firered"
    kind  = kind  or "clean"
    local player = opts.player or cfg.player or (duo and duo.player) or "a"

    local logf
    if duo and duo.result then
        local base = duo.result:match("(.*)%.[^./\\]*$") or duo.result
        logf = io.open(base .. ".shadow.log", "w")
    end

    local ev_wrap = M.build_ev(event_g, "SLink-gen3-shadow-")
    local t = 0
    local function shadow_log(kind_, key_, extra)
        t = t + 1
        local frame = emu_g and emu_g.framecount and emu_g.framecount() or 0
        local line = M.format_shadow_line(t, frame, kind_, key_, extra)
        -- FILE ONLY. Never console.log per fire: a per-frame site would push 60 lines/s into
        -- the BizHawk console and starve the emulator (reference_bizhawk_gate_drivers;
        -- observed on the RR shadow batch 2026-09-21).
        if logf then logf:write(line .. "\n"); logf:flush() end
        return line
    end
    if console_g and console_g.log then
        console_g.log(string.format("[shadow] admitted_by=%s pack=%s title=%s kind=%s",
                                     admitted_by, pack, title, kind))
    end

    local deps = {
        root = proj_root, pack = pack, title = title, kind = kind, player = player,
        mode = "observer",
        -- probe-only seam (Emerald EG2 observer runs before EG4 admission): entry.lua honours
        -- it in observer mode only; nothing in production sets it
        allow_unadmitted = getenv("SLINK_SHADOW_UNADMITTED"),   -- "<pack>/<title>", e.g. gen3_emerald/emerald
        io = io_ro,
        ev = { on_bus_exec = ev_wrap.on_bus_exec, unregister = ev_wrap.unregister },
        net = nil, hud = nil,
        log = function(s) if console_g and console_g.log then console_g.log("[shadow] " .. tostring(s)) end end,
    }
    local _client_obs, parts = Entry.build(deps)
    if deps.allow_unadmitted and parts and parts.profile and parts.profile.admitted == false and logf then
        -- a receipt of this run can never be mistaken for an admitted one
        logf:write("NOTE observer building unadmitted " .. pack .. "/" .. title .. "\n"); logf:flush()
    end
    local read_fires = M.make_signal_reader(assert(parts and parts.signals,
        "gen3 shadow observer: Entry.build(observer) returned no parts.signals"))

    local state = { ev = ev_wrap, deps = deps, parts = parts, stubs = M.mutation_stubs(),
                    admitted_by = admitted_by }
    -- A STATUS line (not a SHADOW line: the differ ignores it) at start and every 600 frames,
    -- so a run with zero fires can be told apart from a run whose hooks never registered.
    local function status_line()
        local ok, st = pcall(function() return parts.signals:status() end)
        if not ok or type(st) ~= "table" then return end
        local frame = emu_g and emu_g.framecount and emu_g.framecount() or 0
        local line = string.format(
            "STATUS frame=%d registered=%s rejected=%s dropped=%s pending=%s failed=%s handler_error=%s",
            frame, tostring(st.registered), tostring(st.rejected), tostring(st.dropped),
            tostring(st.pending), tostring(st.failed), tostring(st.handler_error))
        for k, n in pairs(state.liveness_counts or {}) do
            line = line .. " " .. tostring(k) .. "=" .. tostring(n)
        end
        if console_g and console_g.log then console_g.log("[shadow] " .. line) end
        if logf then logf:write(line .. "\n"); logf:flush() end
    end
    status_line()
    -- Liveness kinds fire EVERY frame (frame_control is the frame-end anchor): counted and
    -- reported in the STATUS line, never written per fire (60 file writes/s otherwise).
    local LIVENESS = { frame_control = true }
    state.liveness_counts = {}
    local polls = 0
    function state.poll()
        polls = polls + 1
        if polls % 600 == 0 then status_line() end
        for _, fire in ipairs(read_fires()) do
          if LIVENESS[fire.kind] then
            state.liveness_counts[fire.kind] = (state.liveness_counts[fire.kind] or 0) + 1
          else
            -- Forward EVERY OTHER scalar field of the fire (callback_address, raw_r15, cpsr,
            -- sp, thumb, mode, action for pc_move, species, ...): tools/gen3_shadow_diff.py
            -- needs them and the vocabulary belongs to signals.lua. `frame` is excluded: it is
            -- already the line's own leading `frame=` field (same value, signals.lua's
            -- io.framecount() at capture == this poll's read, since poll runs every frame).
            local fields, names = {}, {}
            for k, v in pairs(fire) do
                if k ~= "kind" and k ~= "key" and k ~= "frame"
                   and type(v) ~= "table" and type(v) ~= "function" then
                    names[#names + 1] = k
                end
            end
            table.sort(names)
            for _, k in ipairs(names) do fields[#fields + 1] = { k, fire[k] } end
            shadow_log(fire.kind, fire.key or fire.slot or fire.box or "", fields)
          end
        end
    end
    function state.teardown()
        ev_wrap.teardown()
        if logf then logf:close(); logf = nil end
    end
    return state
end

return M
