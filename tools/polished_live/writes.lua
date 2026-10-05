-- tools/polished_live/writes.lua -- card POL-LIVE-WRITES: the FIRST live proof of the merged
-- Polished write path (force_faint + box_mon) on the integrated overlay.
--
-- It composes the REAL client through the real entry path exactly as live.lua does
-- (dofile lua/slink.lua -> lua/gen2/entry.lua Entry.build -> compose_polished), boots the fixture
-- into the overworld, and then does ONE thing live.lua never does: it queues commands into the
-- client's OWN command path, `Client:handle_command` (lua/gen2/client.lua:535). Nothing here
-- re-implements a command, pokes the party, or edits the client; the driver only presses the
-- public entry and reads.
--
-- Every Lua-originated memory write is tapped (the same list live.lua uses) so "only the declared
-- bytes were written" is measured, not asserted.
local L = dofile(os.getenv("SLINK_ROOT") .. "/tools/polished_live/pol_lib.lua")
local fmt = string.format
local J = L.json

-- ── the write tap: every memory.write_* the client makes, in order ────────────────────────────
local writes = {}
for _, k in ipairs({"write_u8", "write_s8", "write_u16_le", "write_u16_be", "write_s16_le", "write_s16_be",
                    "write_u24_le", "write_u24_be", "write_u32_le", "write_u32_be", "write_s32_le",
                    "write_s32_be", "writebyte", "writebyterange", "write_bytes_as_array",
                    "write_bytes_as_dict", "writefloat"}) do
    local fn = memory[k]
    if fn ~= nil then
        memory[k] = function(...)
            local a = {...}
            writes[#writes + 1] = { op = k, addr = a[1], v = a[2], domain = a[3], frame = emu.framecount() }
            return fn(...)
        end
    end
end
local function write_report(since)
    local seen, rows, n = {}, {}, 0
    for i = (since or 0) + 1, #writes do
        local w = writes[i]
        local key = fmt("%s@%s", w.op, tostring(w.addr))
        seen[key] = (seen[key] or 0) + 1
        n = n + 1
        if #rows < 40 then rows[#rows + 1] = fmt("%s frame %d v=%s", key, w.frame, tostring(w.v)) end
    end
    return n, seen, table.concat(rows, " | ")
end

-- ── the client, through the real entry ──────────────────────────────────────────────────────────
SLINK_HOST, SLINK_PORT, SLINK_PLAYER = os.getenv("SLINK_HOST"), tonumber(os.getenv("SLINK_PORT")),
                                       os.getenv("SLINK_PLAYER") or "a"
local hello
do
    local C = package.loaded["connector"]
    if C then
        local orig = C.send
        C.send = function(line, ...)
            local ok, msg = pcall(J.decode, line)
            if ok and type(msg) == "table" and msg.event == "hello" and hello == nil then hello = msg end
            return orig(line, ...)
        end
    end
end
-- hard cap: a driver that never reaches its phases must still produce a RESULT line, not spin
local FRAME_CAP = tonumber(os.getenv("POL_FRAME_CAP")) or 14000   -- must exceed the 8000-frame boot budget
event.onframeend(function()
    if emu.framecount() > FRAME_CAP then
        L.check("driver reached its hard frame cap", false, "frame " .. emu.framecount() .. " cap " .. FRAME_CAP)
        L.finish("pol-live-writes hard-cap")
    end
end)

local t0 = emu.framecount()
dofile(L.ROOT .. "/lua/slink.lua")
L.log(fmt("[writes] slink.lua built the client in %d frames; client=%s", emu.framecount() - t0,
          tostring(SLINK_GEN2_CLIENT ~= nil)))
if not SLINK_GEN2_CLIENT then L.die("the Gen 2 route did not start a client") end
local P = SLINK_GEN2_PARTS
L.log(fmt("[writes] parts: pack %s kind %s sha1 %s; overworld writer=%s boxes=%s",
          tostring(P.pack), tostring(P.artifact_kind), tostring(P.runtime_rom_sha1),
          tostring(P.overworld ~= nil and P.overworld.writes ~= nil),
          tostring(P.overworld ~= nil and P.overworld.boxes ~= nil)))
L.check("the composition has the overworld write path", P.overworld ~= nil and P.overworld.writes ~= nil)
L.check("the composition has the box executor", P.overworld ~= nil and P.overworld.boxes ~= nil)

-- ── boot the fixture into the overworld ─────────────────────────────────────────────────────────
-- group/number nil = "any map" (pol_lib.lua:106-113 tests `group == nil or ...`): the fixture is
-- parked wherever the warp put it, and pinning ROUTE_29 (24,3) made the gate fail on a game that
-- was already running the overworld. 8000 matches live.lua:133.
-- L.to_overworld gates on L.ow_idle() -> L.recent("OWPlayerInput", 2), a HOOK hit, not a memory
-- read (pol_lib.lua:103,112). Without these registrations ow_idle() is always false and the helper
-- spins to its bound whatever the map -- the same two hooks control.lua:7 registers.
for _, name in ipairs({"OWPlayerInput", "SetInitialOptions.joypad_loop"}) do L.hook(name) end

local ok_ow, ow_why = L.to_overworld(nil, nil, 60, 8000, "continue")
L.log(fmt("[writes] overworld: map %d:%d (warp fixture's own map)", L.rw("wMapGroup"), L.rw("wMapNumber")))
if not ok_ow then
    local g = { map = L.rw("wMapStatus"), script = L.rw("wScriptRunning"), paused = L.rw("wGameLogicPaused"),
                battle = L.rw("wBattleMode"), party = L.rw("wPartyCount"),
                xsav = L.rw("wSaveFileExists"), saved = L.rw("wSavedAtLeastOnce") }
    L.log(fmt("[writes] CONTINUE did not reach the overworld after %d frames: %s", emu.framecount(), J.encode(g)))
    L.die("CONTINUE did not reach the overworld: " .. tostring(ow_why))
end
-- No server is started: the card drives the CLIENT. Keys therefore come from the client's OWN read
-- path -- polished.lua:509 `r.read_party()` takes no argument and returns {mons={{key=...}}}; this
-- is the exact call shape tests/unit/test_polished_write_path.py uses (reads.read_party().mons[n].key).
L.idle(120)
local party_block, party_why = P.reads:read_party()
local mons = (party_block and party_block.mons) or {}
L.log(fmt("[writes] party from the client's own read path: %d mons%s", #mons,
          party_block == nil and (" -- " .. tostring(party_why)) or ""))
for i = 1, math.min(#mons, 6) do
    L.log(fmt("[writes]   mon %d: key=%s species=%s level=%s", i, tostring(mons[i].key),
              tostring(mons[i].species), tostring(mons[i].level)))
end
L.check("the save has a party of >= 2 (the card's precondition)", #mons >= 2, #mons)

-- the gate bytes the write path predicates on (live.lua's own running test)
local function gate()
    return { map = L.rw("wMapStatus"), script = L.rw("wScriptRunning"), paused = L.rw("wGameLogicPaused"),
             link = L.rw("wLinkMode"), battle = L.rw("wBattleMode") }
end
local function running() local g = gate() return g.map == 2 and g.script == 0 and g.paused == 0 and g.link == 0 end

-- ── (a) force_faint on a BENCH party slot ──────────────────────────────────────────────────────
-- In the overworld nothing is the active battler, so every party slot is a bench slot: this is the
-- client's land_bench_deaths path (client.lua:1653), NOT the in-battle path. Slot 2 (the card's
-- target, NOT slot 0) is the third mon.
--
-- Record geometry, Polished's OWN (docs/polished/RAM.md; constants/pokemon_data_constants.asm):
-- 48-byte stride, Status @ +32, current HP @ +34..35, MaxHP @ +36..37, HP/stats BIG-endian.
-- wPartyMon1 and wPartyMons are the same address in the overlay .sym; wPartyMons is what
-- harness.py's SYMBOLS exports, so it is what we address by.
local SB_BASE = L.SYM.wPartyMons[2]          -- System Bus address of wPartyMon1
local WRAM_BASE = L.woff("wPartyMons")        -- the same block in the WRAM domain
local STRIDE, STATUS_OFF, HP_OFF, MAXHP_OFF = 48, 32, 34, 36
L.log(fmt("[writes] party block: SystemBus $%04X / WRAM $%04X, stride %d, status +%d, HP +%d, MaxHP +%d",
          SB_BASE, WRAM_BASE, STRIDE, STATUS_OFF, HP_OFF, MAXHP_OFF))
local function be16(slot, off) return L.bus(SB_BASE + slot * STRIDE + off) * 256
                                    + L.bus(SB_BASE + slot * STRIDE + off + 1) end
local function status(slot) return L.bus(SB_BASE + slot * STRIDE + STATUS_OFF) end

local SLOT = 2                                   -- 0-based: the third mon, a bench mon
local key = mons[SLOT + 1] and mons[SLOT + 1].key
L.log(fmt("[writes] target slot %d key=%s", SLOT, tostring(key)))
L.check("a party key is available to queue for the bench slot", key ~= nil, tostring(key))

local before_count = L.rw("wPartyCount")
local hp_before, max_before, st_before = be16(SLOT, HP_OFF), be16(SLOT, MAXHP_OFF), status(SLOT)
L.log(fmt("[writes] slot %d before: HP %d/%d status $%02X party %d", SLOT, hp_before, max_before,
          st_before, before_count))
L.check("the target slot is alive before the faint (HP > 0)", hp_before > 0,
        fmt("HP %d/%d status $%02X", hp_before, max_before, st_before))

local w_before = #writes
local g = gate()
L.check("the overworld predicate is satisfied at queue time (no battle, no script)",
        running() and g.battle == 0, fmt("gate %s", J.encode(g)))
SLINK_GEN2_CLIENT:handle_command({ cmd = "force_faint", key = key })
L.check("force_faint was queued into the client's command path", true, "handle_command accepted it")
L.idle(120)
local hp_after, max_after, st_after = be16(SLOT, HP_OFF), be16(SLOT, MAXHP_OFF), status(SLOT)
local after_count = L.rw("wPartyCount")
L.log(fmt("[writes] slot %d after: HP %d/%d status $%02X party %d", SLOT, hp_after, max_after, st_after,
          after_count))
L.check("(a1) the bench mon's HP bytes are 0/0 (big-endian pair)", hp_after == 0,
        fmt("%d/%d (before %d/%d)", hp_after, L.bus(SB_BASE + SLOT * STRIDE + HP_OFF + 1), hp_before, max_before))
L.check("(a2) the mon's status byte is 0", st_after == 0, fmt("$%02X (before $%02X)", st_after, st_before))
L.check("(a3) the party count is unchanged", after_count == before_count, fmt("%d -> %d", before_count, after_count))

-- every write this run made must lie inside the declared party-record block, in EITHER domain the
-- tap may report (the client's io.write_u8 domain is logged with each write, never assumed).
local n, outside, seen_addrs = 0, {}, {}
for i = w_before + 1, #writes do
    local w = writes[i]
    n = n + 1
    local a = w.addr
    seen_addrs[#seen_addrs + 1] = fmt("%s@%s[%s]", w.op, tostring(a), tostring(w.domain))
    local inside = (a >= SB_BASE and a < SB_BASE + 6 * STRIDE) or (a >= WRAM_BASE and a < WRAM_BASE + 6 * STRIDE)
    if not inside then outside[#outside + 1] = seen_addrs[#seen_addrs] end
end
L.log(fmt("[writes] (a) %d client write(s): %s", n, table.concat(seen_addrs, " | ")))
L.check("(a4) every write landed inside the declared party-record block", #outside == 0,
        #outside == 0 and n .. " write(s), all in the party block" or table.concat(outside, ", "))
L.check("(a4b) the client wrote something at all", n > 0, n)

if os.getenv("POL_STOP_AFTER_A") == "1" then
    L.log(fmt("[writes] POL_STOP_AFTER_A=1: stopping after (a); box_mon and the negatives are NOT RUN"))
    L.finish("pol-live-writes (a) complete")
end

-- ── (b) box_mon deposit of another party mon ───────────────────────────────────────────────────
local dep = party[2]
local dkey = dep and (dep.key or dep.mon_key)
local dep_before_count = L.rw("wPartyCount")
local w_before_b = #writes
local b_result, b_sent = "not attempted", nil
if dkey then
    SLINK_GEN2_CLIENT:handle_command({ cmd = "box_mon", key = dkey })
    L.check("(b0) box_mon was queued into the client's command path", true, tostring(dkey))
    L.idle(150)
    local c = L.rw("wPartyCount")
    b_result = fmt("party %d -> %d", dep_before_count, c)
    L.log(fmt("[writes] (b) box_mon: %s", b_result))
    L.check("(b1) the deposited slot left the party", c == dep_before_count - 1, b_result)
else
    L.log("[writes] (b) no second party key in the hello; box_mon NOT attempted")
end

-- ── (c) negative controls ──────────────────────────────────────────────────────────────────────
-- The same commands, queued while the gate is NOT satisfied, must not write. We do not fake the
-- gate: we only queue during a frame where the engine's own bytes say so, and say NOT RUN if the
-- card's condition never occurs naturally in this boot.
local negatives = 0
for _, probe in ipairs({ { name = "battle", ok = function() return L.rw("wBattleMode") ~= 0 end,
                           cmd = function(k) return { cmd = "force_faint", key = k } end },
                         { name = "script", ok = function() return L.rw("wScriptRunning") ~= 0 end,
                           cmd = function(k) return { cmd = "box_mon", key = k } end } }) do
    local seen_state = false
    local w0 = #writes
    for _ = 1, 1800 do
        L.frame()
        if probe.ok() then
            seen_state = true
            if key then
                local wq = #writes
                SLINK_GEN2_CLIENT:handle_command(probe.cmd(key))
                L.idle(6)
                local dn = #writes - wq
                if dn > 0 then
                    L.check("(c-" .. probe.name .. ") nothing was written while " .. probe.name .. " was active",
                            false, dn .. " write(s)")
                    negatives = negatives + 1
                end
            end
            break
        end
    end
    L.check("(c-" .. probe.name .. ") the " .. probe.name .. " state was observed", seen_state,
            seen_state and "queued and nothing written" or "never occurred in this boot -> NOT RUN")
end

L.log(fmt("[writes] RESULT-DATA %s", J.encode({
    rom = P.runtime_rom_sha1, party = #party, wrote = #writes,
    gate = gate(), writes_total = select(2, write_report(0)),
})))
L.finish("pol-live-writes")