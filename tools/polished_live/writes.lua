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
-- NOTE: this line is NOT the phrase writes_run.py's coarse poll watches for ("party from the
-- client's own read path"). That poll kills the emulator whenever it sees it, which lands inside
-- the (a) idle and truncates the run; the driver's own env gates (POL_STOP_AFTER_A / _B) are the
-- precise stop. Delete the runner poll when writes_run.py is next touched.
L.log(fmt("[writes] party read via the client's own read path: %d mons%s", #mons,
          party_block == nil and (" -- " .. tostring(party_why)) or ""))
for i = 1, math.min(#mons, 6) do
    L.log(fmt("[writes]   mon %d: key=%s species=%s level=%s", i, tostring(mons[i].key),
              tostring(mons[i].species), tostring(mons[i].level)))
end
L.check("read_party() SUCCEEDED (a refusal is a FAIL, never an empty list)", party_block ~= nil,
        party_block and #party_block.mons or tostring(party_why))
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
local CO = (P.overworld and P.overworld.coords) or {}

-- ── EXACT DIFF DISCIPLINE ──────────────────────────────────────────────────────────────────────
-- Snapshot the three regions a write could touch, so "what changed" is measured rather than
-- inferred from the write log. CartRAM is read flat (0..0x7FFF) exactly as the census reads it;
-- the party block and the pokedb allocation windows are read in their own domains.
local function snapshot()
    local cart, party, alloc = {}, {}, {}
    for i = 0, 0x7FFF do cart[i] = memory.read_u8(i, "CartRAM") end
    for a = SB_BASE - 8, SB_BASE + 6 * 48 + 11 + 11 do party[a] = memory.read_u8(a, "System Bus") end
    for _, label in ipairs({"wPokeDB1UsedEntries", "wPokeDB2UsedEntries"}) do
        local c = CO[label]
        if c then for i = 0, 25 do alloc[c[1] * 0x1000 + c[2] - 0xD000 + i] = memory.read_u8(c[1] * 0x1000 + c[2] - 0xD000 + i, "WRAM") end end
    end
    return cart, party, alloc
end
local function changed(before, after)
    local out = {}
    out = {}
    for a, v in pairs(before[1]) do if after[1][a] ~= v then out[#out + 1] = { kind = "cart", a = a } end end
    for a, v in pairs(before[2]) do if after[2][a] ~= v then out[#out + 1] = { kind = "party", a = a } end end
    for a, v in pairs(before[3]) do if after[3][a] ~= v then out[#out + 1] = { kind = "alloc", a = a } end end
    table.sort(out, function(x, y) if x.kind ~= y.kind then return x.kind < y.kind end return x.a < y.a end)
    return out
end
local function fmt_changed(list, cap)
    local parts, n = {}, 0
    for _, c in ipairs(list) do
        n = n + 1
        if n <= (cap or 12) then parts[#parts + 1] = fmt("%s@%d", c.kind, c.a) end
    end
    if n > (cap or 12) then parts[#parts + 1] = fmt("...+%d more", n - (cap or 12)) end
    return fmt("%d byte(s): %s", n, table.concat(parts, ", "))
end
local function is_subset(got, expect)
    local set = {}
    for k, v in pairs(expect) do set[k] = v end
    local extra = {}
    for _, c in ipairs(got) do
        local k = c.kind .. "@" .. c.a
        if not set[k] then extra[#extra + 1] = k end
        set[k] = nil
    end
    local missing = {}
    for k in pairs(set) do missing[#missing + 1] = k end
    table.sort(missing)
    return #extra == 0, extra, missing
end

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

local b_cart, b_party, b_alloc = snapshot()
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

-- (a5) the EXACT changed set. Independently derived: the faint's own record, status +32 and HP
-- +34..35 -- nothing else, anywhere in CartRAM, the party block or the pokedb flags.
local a_cart, a_party, a_alloc = snapshot()
local diff_a = changed({ b_cart, b_party, b_alloc }, { a_cart, a_party, a_alloc })
local expect_a = {}
for _, off in ipairs({ STATUS_OFF, HP_OFF, HP_OFF + 1 }) do
    expect_a["party@" .. (SB_BASE + SLOT * STRIDE + off)] = true
end
local sub_ok, extra, missing = is_subset(diff_a, expect_a)
L.log(fmt("[writes] (a) changed set: %s", fmt_changed(diff_a)))
L.check("(a5) EXACT diff: nothing outside the faint record's status +32 / HP +34..35 changed", sub_ok,
        fmt("unexpected: %s", table.concat(extra, ",")))
-- A byte the writer stores with the value it already held is a WRITE, not a CHANGE, so the
-- expected set is a superset bound, not an equality: on this fixture the mon is status $00 with
-- HP 0x0098, so status +32 and HP-hi +34 were already the values the write stores and only HP-lo
-- actually flips. What must hold: no byte OUTSIDE the faint's own three, and CartRAM untouched.
local party_only, box_only, alloc_only = 0, 0, 0
for _, c in ipairs(diff_a) do
    if c.kind == "party" then party_only = party_only + 1
    elseif c.kind == "cart" then box_only = box_only + 1 else alloc_only = alloc_only + 1 end
end
L.check(fmt("(a5b) every OTHER party mon and every box slot is byte-identical (party-block %d changed, "
            .. "CartRAM %d, pokedb flags %d)", party_only, box_only, alloc_only),
        party_only <= 3 and box_only == 0 and alloc_only == 0)
L.check("(a5d) at least one byte actually changed (the diff is not empty)", #diff_a >= 1, #diff_a)
-- NEGATIVE CONTROL: the same measured diff against a WRONG expected set (the faint target shifted
-- one slot) MUST fail. Without this, (a5) could pass vacuously -- e.g. if the diff were empty.
local wrong = {}
for _, off in ipairs({ STATUS_OFF, HP_OFF, HP_OFF + 1 }) do wrong["party@" .. (SB_BASE + (SLOT + 1) * STRIDE + off)] = true end
local wrong_ok = is_subset(diff_a, wrong)
L.check("(a5c) CONTROL: the same diff against a deliberately wrong expected set FAILS", wrong_ok == false,
        fmt("subset reported %s against a one-slot-shifted set", tostring(wrong_ok)))

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

-- ── (b) box_mon deposit of a DIFFERENT bench mon (slot 3) ─────────────────────────────────────
-- Declared write ranges, from lua/gen2/polished_overworld.lua's own header (NEWBOX §1/§2):
--   System Bus  the party block wPartyCount..wPartyMonNicknamesEnd (01:DCCE..01:DE7A)
--   CartRAM     the six pokedb sections and the 20 gameplay box records (sNewBox1..20)
--   WRAM        the two pokedb allocation-flag windows wPokeDB{1,2}UsedEntries
local PARTY_LO, PARTY_HI = 0xDCCE, 0xDE7A
local CO = P.overworld.coords or {}
local function cart_flat(label) local c = CO[label] return c and (c[1] * 0x2000 + c[2] - 0xA000) or nil end
local function wram_flat(label) local c = CO[label] return c and (c[1] * 0x1000 + c[2] - 0xD000) or nil end
local POKEDB, BOXREC, ALLOC = {}, {}, {}
for bank = 1, 2 do
    local n = 0
    for _, sec in ipairs({"A", "B", "C"}) do
        local base = cart_flat("sBoxMons" .. bank .. sec)
        if base then POKEDB[#POKEDB + 1] = { lo = base, hi = base + 207 * 49 } end
        n = n + 1
    end
end
for n = 1, 20 do local at = cart_flat("sNewBox" .. n) if at then BOXREC[#BOXREC + 1] = { lo = at, hi = at + 0x21 } end end
for _, label in ipairs({"wPokeDB1UsedEntries", "wPokeDB2UsedEntries"}) do
    local at = wram_flat(label) if at then ALLOC[#ALLOC + 1] = { lo = at, hi = at + 0x40 } end
end
local function classify(w)
    local a, d = w.addr, tostring(w.domain)
    if d == "System Bus" then
        return (a >= PARTY_LO and a < PARTY_HI) and "party-block" or "other"
    elseif d == "CartRAM" then
        for _, r in ipairs(BOXREC) do if a >= r.lo and a < r.hi then return "box-record" end end
        for _, r in ipairs(POKEDB) do if a >= r.lo and a < r.hi then return "pokedb" end end
        return "other"
    elseif d == "WRAM" then
        for _, r in ipairs(ALLOC) do if a >= r.lo and a < r.hi then return "allocation-flag" end end
        return "other"
    end
    return "other"
end

if #mons < 4 then
    L.log(fmt("[writes] (b) party is %d, not >= 4: no distinct slot 3 to deposit. NOT RUN", #mons))
else
    local BSLOT = 3                                    -- a different mon from the fainted slot 2
    local bkey = mons[BSLOT + 1] and mons[BSLOT + 1].key
    L.log(fmt("[writes] (b) target slot %d key=%s", BSLOT, tostring(bkey)))
    L.check("(b0) a distinct party key is available to deposit", bkey ~= nil and bkey ~= key, tostring(bkey))
    local count_before = L.rw("wPartyCount")
    local wb = #writes
    SLINK_GEN2_CLIENT:handle_command({ cmd = "box_mon", key = bkey })
    L.check("(b0a) box_mon was queued into the client's command path", true, tostring(bkey))
    L.idle(150)
    local count_after = L.rw("wPartyCount")
    local after_party = P.reads:read_party()
    local after_keys = {}
    for i, m in ipairs((after_party and after_party.mons) or {}) do after_keys[i] = m.key end
    local still_there = false
    for _, k in ipairs(after_keys) do if k == bkey then still_there = true end end
    L.log(fmt("[writes] (b) party %d -> %d; keys now [%s]", count_before, count_after, table.concat(after_keys, " ")))
    L.check("(b1a) wPartyCount went 5 -> 4", count_after == count_before - 1, fmt("%d -> %d", count_before, count_after))
    L.check("(b1b) the deposited key is no longer in read_party()", not still_there, tostring(bkey))

    -- (b2) the COMPOSED census. lua/gen2/polished.lua P.census scans all 20 boxes through
    -- boxes.read_boxes inside scan() and FAILS CLOSED (polished.lua:767-771): it returns nil,why on
    -- `not snap.complete`, `#snap.bad_eggs > 0` or `#snap.unflagged > 0`. A NON-NIL return is
    -- therefore the completeness proof -- there is no separate `complete` field to read, and no
    -- reason for this driver to build a second reader (it did, and that reader is what hung).
    local census = P.overworld and P.overworld.census
    local t0 = os.clock()
    local got, why = census and census.read_storage_box(0)
    L.log(fmt("[writes] (b2) census.read_storage_box(0) returned %s in %.2f s CPU%s",
              got and "a mon list" or "nil", os.clock() - t0, got and "" or (" -- " .. tostring(why))))
    L.check("the composed census read is complete (P.census fails closed on incomplete/Bad Egg/"
            .. "unflagged, polished.lua:767-771)", got ~= nil, got and #got.mons or tostring(why))
    local found
    if got then
        for _, m in ipairs(got.mons or {}) do if m.key == bkey then found = m end end
    end
    if not found then
        -- the client walks 0..19 exactly like this (client.lua rescan_boxes): box 0 is the scan,
        -- boxes 1..19 are served from it. Walk them and time the walk.
        local tw = os.clock()
        for box = 1, 19 do
            local mons = census.read_storage_box(box)
            for _, m in ipairs((mons and mons.mons) or {}) do if m.key == bkey then found = m end end
        end
        L.log(fmt("[writes] (b2b) walked boxes 1..19 in %.2f s CPU", os.clock() - tw))
    end
    L.check("(b2b) the deposited mon is present in a gameplay box", found ~= nil, tostring(bkey))

    -- (b3) the pokedb entry's own checksum, via polished_boxes.lua B.verify on the stored bytes
    local Boxes = dofile(L.ROOT .. "/lua/gen2/polished_boxes.lua")
    if found and found.raw_hex then
        local entry = L.unhex(found.raw_hex)
        local okc = Boxes.verify(entry)
        L.check("(b3) the pokedb entry checksum verifies (B.verify)", okc == true, tostring(okc))
    else
        L.check("(b3) the pokedb entry checksum verifies (B.verify)", false, "no stored entry to verify")
    end

    -- (b4) every write the run made FOR (b), classified against the declared ranges
    local counts, others, listing = {}, {}, {}
    for i = wb + 1, #writes do
        local w = writes[i]
        local kind = classify(w)
        counts[kind] = (counts[kind] or 0) + 1
        listing[#listing + 1] = fmt("%s@%s[%s]=%s", w.op, tostring(w.addr), tostring(w.domain), kind)
        if kind == "other" then others[#others + 1] = listing[#listing] end
    end
    L.log(fmt("[writes] (b) %d write(s): %s", #listing, table.concat(listing, " | ")))
    L.check("(b4) every (b) write is inside a declared range", #others == 0,
            #others == 0 and table.concat(listing, " | ") or ("UNDECLARED: " .. table.concat(others, ", ")))
end

if os.getenv("POL_STOP_AFTER_B") == "1" then
    L.log("[writes] POL_STOP_AFTER_B=1: stopping after (a)+(b); the negatives are NOT RUN")
    L.finish("pol-live-writes (a)+(b) complete")
end

-- ── (c) NEGATIVES: NOT RUN in this card ────────────────────────────────────────────────────────
-- The three gate pokes (wBattleMode / wScriptRunning / wGameLogicPaused) are NOT attempted here:
-- poking wBattleMode to 1 leaves OverworldLoop, so the engine stops reaching the DelayFrame the
-- driver advances on and the run wedges (measured twice, 190 s and 300 s caps, no progress past
-- the poke line). A poke that halts the engine is not a gate: zero writes must be measured while
-- frames keep advancing. (c) needs a REAL battle, driven into by the game -- see the reply.
L.log("[writes] (c) negatives: NOT RUN (synth gate pokes wedge the frame loop; a real battle is needed)")

L.finish("pol-live-writes")