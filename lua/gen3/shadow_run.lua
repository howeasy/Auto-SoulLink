--[[
  lua/gen3/shadow_run.lua — P3 shadow observer bootstrap (PLAN §5.7, §4).

  Loaded by the duo stub (lua/tests/duo/duo_main.lua) AFTER
  lua/clients/gen3_frlge_client.lua, only when SLINK_SHADOW is set. It builds a SECOND,
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

local WRITE_SINKS = { "write_u8", "write_u16_le", "write_u32_le", "write_bytes" }

-- M.build_io(mem): a read-only wrapper over a BizHawk-shaped memory table (real `memory` in
-- production, a fake table in tests). Reads (incl. ROM reads, which just pass a domain arg
-- through like any other read) forward unchanged; every write_* throws.
function M.build_io(mem)
    local io_ro = {
        read_u8      = function(...) return mem.read_u8(...) end,
        read_u16_le  = function(...) return mem.read_u16_le(...) end,
        read_u32_le  = function(...) return mem.read_u32_le(...) end,
        read_bytes   = function(...) return mem.read_bytes(...) end,
        framecount   = function(...) return mem.framecount(...) end,
        domains      = function(...) return mem.domains(...) end,
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
    wrapped.on_bus_exec = function(fn, addr, name, domain)
        local id = ev.on_bus_exec(fn, addr, prefix .. tostring(name), domain)
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

-- M.make_signal_reader(signals): the ONE adapter over C3-1's parts.signals surface (contract,
-- per the card: `on_fire(kind, fn)` handlers, OR a `drain()` queue of {kind, key, frame,
-- callback_addr, raw_r15}). Prefers drain() (a catch-all needing no kind list up front); falls
-- back to on_fire("*", fn) queued into an equivalent drain. Returns poll(), called once per
-- frame, which returns the fires queued since the last call. If C3-1's real surface differs
-- when it lands, this is the only function that needs to change.
function M.make_signal_reader(signals)
    if type(signals.drain) == "function" then
        return function() return signals.drain() end
    end
    if type(signals.on_fire) == "function" then
        local queued = {}
        signals.on_fire("*", function(fire) queued[#queued + 1] = fire end)
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
-- costs nothing when shadow mode is off. `opts` lets a caller (or a test, via real BizHawk
-- globals already set on _G) override any field without touching the globals.
--
-- ponytail: title/pack/kind default to "firered"/"gen3_frlg"/"clean" when SLINK_SHADOW ships no
-- table — there is no title auto-probe here yet. Wire one in once lua/gen3/entry.lua exposes
-- its own detection (mirrors Entry.detect_title in lua/gen1/entry.lua); until then, drive
-- shadow runs with an explicit SLINK_SHADOW table on non-FR ROMs.
function M.start(opts)
    opts = opts or {}
    -- SLINK_SHADOW is either a Lua global (bool/1, or a table of overrides — future e2e_duo
    -- wiring) or a process env var (run_gate.py --shadow, os.getenv per the self-location
    -- reference: a dofile'd chunk sees an inherited env var same as a --lua= top-level script).
    local shadow_cfg = opts.shadow
    if shadow_cfg == nil then shadow_cfg = _G.SLINK_SHADOW end
    if shadow_cfg == nil then shadow_cfg = os.getenv("SLINK_SHADOW") end
    if not shadow_cfg or shadow_cfg == "" then return nil end
    local cfg = type(shadow_cfg) == "table" and shadow_cfg or {}
    local duo = opts.duo or _G.SLINK_DUO

    local src = debug.getinfo(1, "S").source:match("@(.+[/\\])") or ""
    local lua_root = src:match("(.+[/\\])gen3[/\\]") or src
    local proj_root = lua_root:match("(.+[/\\])lua[/\\]") or (lua_root .. "../")
    package.path = lua_root .. "?.lua;" .. package.path

    local pack   = opts.pack   or cfg.pack   or "gen3_frlg"
    local title  = opts.title  or cfg.title  or "firered"
    local kind   = opts.kind   or cfg.kind   or "clean"
    local player = opts.player or cfg.player or (duo and duo.player) or "a"

    local logf
    if duo and duo.result then
        local base = duo.result:match("(.*)%.[^./\\]*$") or duo.result
        logf = io.open(base .. ".shadow.log", "w")
    end

    local ev_wrap = M.build_ev(event, "SLink-gen3-shadow-")
    local io_ro = M.build_io(memory)
    local t = 0
    local function shadow_log(kind_, key_, extra)
        t = t + 1
        local frame = emu and emu.framecount and emu.framecount() or 0
        local line = M.format_shadow_line(t, frame, kind_, key_, extra)
        if console and console.log then console.log(line) end
        if logf then logf:write(line .. "\n"); logf:flush() end
        return line
    end

    local Entry = require("gen3.entry")
    local deps = {
        root = proj_root, pack = pack, title = title, kind = kind, player = player,
        mode = "observer",
        io = io_ro,
        ev = { on_bus_exec = ev_wrap.on_bus_exec, unregister = ev_wrap.unregister },
        net = nil, hud = nil,
        log = function(s) if console and console.log then console.log("[shadow] " .. tostring(s)) end end,
    }
    local _client_obs, parts = Entry.build(deps)
    local read_fires = M.make_signal_reader(assert(parts and parts.signals,
        "gen3 shadow observer: Entry.build(observer) returned no parts.signals"))

    local state = { ev = ev_wrap, deps = deps, parts = parts, stubs = M.mutation_stubs() }
    function state.poll()
        for _, fire in ipairs(read_fires()) do
            -- Forward EVERY scalar field of the fire (action for pc_move, species, etc.):
            -- tools/gen3_shadow_diff.py needs them and the vocabulary belongs to signals.lua.
            local fields, names = {}, {}
            for k, v in pairs(fire) do
                if k ~= "kind" and k ~= "key" and type(v) ~= "table" and type(v) ~= "function" then
                    names[#names + 1] = k
                end
            end
            table.sort(names)
            for _, k in ipairs(names) do fields[#fields + 1] = { k, fire[k] } end
            shadow_log(fire.kind, fire.key or fire.slot or fire.box or "", fields)
        end
    end
    function state.teardown()
        ev_wrap.teardown()
        if logf then logf:close(); logf = nil end
    end
    return state
end

return M
