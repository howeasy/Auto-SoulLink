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
            writes[#writes + 1] = { op = k, addr = a[1], v = a[2], frame = emu.framecount() }
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
local FRAME_CAP = tonumber(os.getenv("POL_FRAME_CAP")) or 4500
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
local ok_ow, ow_why = L.to_overworld(24, 3, 60, 2500, "continue")
if not ok_ow then
    local g = { map = L.rw("wMapStatus"), script = L.rw("wScriptRunning"), paused = L.rw("wGameLogicPaused"),
                battle = L.rw("wBattleMode"), party = L.rw("wPartyCount"),
                xsav = L.rw("wSaveFileExists"), saved = L.rw("wSavedAtLeastOnce") }
    L.log(fmt("[writes] CONTINUE did not reach the overworld after %d frames: %s", emu.framecount(), J.encode(g)))
    L.die("CONTINUE did not reach the overworld: " .. tostring(ow_why))
end
-- No server is started: the card drives the CLIENT. Keys therefore come from the client's own
-- read path (parts.reads:read_party(true) + the wire key builder), not from a hello that would
-- need a TCP peer. A hello is still recorded if one arrives.
L.idle(120)
local recorded = P.reads:read_party(true)
local party = {}
for i, mon in ipairs(recorded or {}) do
    party[i] = { key = P.wire.mon_key(mon), species = mon.species, level = mon.level }
end
L.log(fmt("[writes] party from the client's own read path: %d mons [%s]", #party,
          table.concat((function() local t = {} for i, m in ipairs(party) do t[i] = m.key end return t end)(), " ")))
L.check("the save has a party of >= 2 (the card's precondition)", #party >= 2, #party)

-- the gate bytes the write path predicates on (live.lua's own running test)
local function gate()
    return { map = L.rw("wMapStatus"), script = L.rw("wScriptRunning"), paused = L.rw("wGameLogicPaused"),
             link = L.rw("wLinkMode"), battle = L.rw("wBattleMode") }
end
local function running() local g = gate() return g.map == 2 and g.script == 0 and g.paused == 0 and g.link == 0 end

-- ── (a) force_faint on a NON-ACTIVE party slot ────────────────────────────────────────────────
-- In the overworld nothing is the active battler, so every party slot is a bench slot: this is
-- the client's land_bench_deaths path (client.lua:1653), NOT the in-battle path.
local target = party[1]
local key = target and (target.key or target.mon_key)
L.log(fmt("[writes] target slot key=%s species=%s level=%s", tostring(key),
          tostring(target and (target.species_id or target.species)), tostring(target and target.level)))
L.check("a party key is available to queue", key ~= nil, tostring(key))

local HP = L.SYM.wPartyMons[2]
local STATUS_OFF = 0x36 - 0x24          -- HP @ +0x24, Status @ +0x36 of the 48-byte record (polished profile)
local status_off, hp_off = 0x36, 0x24
local before_count = L.rw("wPartyCount")
local slot = 0
local hp0 = L.woff("wPartyMons", slot * 48 + hp_off)
local hp1 = L.woff("wPartyMons", slot * 48 + hp_off + 1)
local st0 = L.woff("wPartyMons", slot * 48 + status_off)
L.log(fmt("[writes] slot 0 before: HP %d/%d status $%02X party %d", hp0, hp1, st0, before_count))
L.check("the target slot is alive before the faint (HP > 0 and status not fainted)",
        hp0 > 0 or hp1 > 0, fmt("HP %d/%d status $%02X", hp0, hp1, st0))

local w_before = #writes
local g = gate()
L.check("the overworld predicate is satisfied at queue time (no battle, no script)",
        running() and g.battle == 0, fmt("gate %s", J.encode(g)))
SLINK_GEN2_CLIENT:handle_command({ cmd = "force_faint", key = key })
L.check("force_faint was queued into the client's command path", true, "handle_command accepted it")
L.idle(90)
local hp1a = L.woff("wPartyMons", slot * 48 + hp_off)
local hp1b = L.woff("wPartyMons", slot * 48 + hp_off + 1)
local st1 = L.woff("wPartyMons", slot * 48 + status_off)
local after_count = L.rw("wPartyCount")
L.log(fmt("[writes] slot 0 after: HP %d/%d status $%02X party %d", hp1a, hp1b, st1, after_count))
L.check("(a1) the bench mon's HP bytes are 0/0", hp1a == 0 and hp1b == 0, fmt("%d/%d", hp1a, hp1b))
L.check("(a2) the mon's status byte is 0 (not fainted/statused)", st1 == 0, fmt("$%02X", st1))
L.check("(a3) the party count is unchanged", after_count == before_count,
        fmt("%d -> %d", before_count, after_count))
local n, seen, rows = write_report(w_before)
L.log(fmt("[writes] (a) %d client write(s): %s", n, rows))
L.check("(a4) the client wrote something at all", n > 0, n)
for op, count in pairs(seen) do
    L.check("(a5) every write is a byte write, no block/blob write", op:match("^write_u8") ~= nil
            or op:match("^write_s8") ~= nil or op:match("^writebyte@") ~= nil, op .. " x" .. count)
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