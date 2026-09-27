-- probe_gen3_reads_dump.lua — P3 "reads == PYDEC" dump (card gen3-P3-C3-14, PLAN §5.7).
--
-- Proves lua/gen3/reads.lua decodes exactly what server/adapters/gen3_codec.py decodes from
-- the SAME bytes, on REAL HARDWARE BYTES, never from a disk save. This probe only produces
-- the raw+decoded evidence; the comparison itself is tools/gen3_reads_pydec.py (a separate
-- process, so neither side can borrow the other's arithmetic).
--
-- Builds the REAL observer parts the same way lua/gen3/shadow_run.lua does (reused, not
-- reimplemented: M.build_io / M.build_ev, and the SAME pack/title/kind ADMISSION flow
-- M.start uses -- Entry.admit off gameinfo.getromhash()/anchors, kind included, rather than a
-- guessed default. A guessed "clean" kind against the RR COMPANION binary is exactly the RR
-- lane's silent-death bug (2026-09-21): Signals.new() registers on_bus_exec hooks at the
-- "clean" artifact's site addresses, which are wrong for the companion build, and BizHawk's
-- own hook registration can hard-error out from under an unprotected Entry.build call --
-- which is why EVERY step below is pcall'd with its own phase line, so a real failure becomes
-- a RESULT: FAIL line instead of a launcher timeout.
--
-- On the field, at frame end:
--   (a) dumps the raw party bytes and (when the title has box geometry) the raw box 0 bytes
--       as hex lines: "DUMP name=<party|box0> addr=0x... len=N frame=F hex=..."
--   (b) decodes them through parts.reads (:read_party() / :read_box(0)) and writes one line
--       per mon: "LUA name=<party|box0> slot=i key=PID:OTID species=N level=N hp=N nickname=..."
-- into patch/build/gen3_reads_dump.txt (tools/gen3_reads_pydec.py's only input).
--
-- Environment: SLINK_ROOT, SLINK_GEN3_CHECKPOINT/TITLE (gen3_boot_check.lua helpers),
-- SLINK_STATE (a savestate to load; when unset, boots to the field via G.boot_to_field),
-- SLINK_GEN3_KIND (optional override; when unset the kind is ADMITTED from the loaded ROM,
-- same as shadow_run.lua -- never guessed).
--
-- An empty party (e.g. the FR pre-starter fixture) is reported HONESTLY: a DUMP line with
-- len=0 hex="" and zero LUA lines, never a failure. Box geometry absent from the title's
-- profile (derived has neither CFRU_BOX_BASES nor BOX_DATA_OFFSET/BOXES_PER_STORE) is a NOTE
-- line, also not a failure. Any OTHER error after the field phase is caught, phase-logged, and
-- ends the run with G.finish(false, err) -- this probe never hangs the lane waiting on a
-- launcher timeout again.

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(WT, "SLINK_ROOT unset")
local G = dofile(WT .. "/lua/tests/gen3_boot_check.lua")
local SR = dofile(WT .. "/lua/gen3/shadow_run.lua")

G.open("gen3_reads_dump")                 -- patch/build/gen3_reads_dump_result.txt
pcall(client.speedmode, 6399)
local cp, title = G.checkpoint()
G.phase("start", "title=" .. tostring(title))

local STATE = os.getenv("SLINK_STATE")
if STATE and STATE ~= "" then
    local ok = pcall(savestate.load, STATE)
    G.phase("state", (ok and "loaded " or "FAILED ") .. STATE)
    G.idle(30)
else
    if not G.boot_to_field(cp, 9000) then
        G.shot("stuck")
        G.finish(false, "never reached the field")
    end
end
G.phase("field", string.format("map=%d,%d", G.map(cp)))

-- ── every step from here on is pcall'd with its own phase line; a failure ends the run via
-- G.finish(false, ...) immediately instead of falling through to an uncaught error that kills
-- the script with no RESULT line (the RR lane's exact symptom). ─────────────────────────────
local function step(name, fn)
    local ok, a, b = pcall(fn)
    if not ok then
        G.shot("stuck")
        G.finish(false, string.format("%s: %s", name, tostring(a)))
    end
    G.phase(name, "ok")
    return a, b
end

-- ── build the real observer parts (shadow_run.lua's shape AND its admission flow, reused not
-- reimplemented: M.build_io / M.build_ev / the pack-title-kind resolution M.start performs) ──
local io_ro, ev_wrap = step("build-io-ev", function()
    local io_ro_ = SR.build_io(memory, function(name) return emu.getregister(name) end,
                               function() return emu.framecount() end)
    local ev_wrap_ = SR.build_ev(event, "SLink-gen3-reads-probe-")
    return io_ro_, ev_wrap_
end)

local Entry, json = step("require-entry", function()
    package.path = WT .. "/lua/?.lua;" .. package.path
    local json_ = dofile(WT .. "/lua/json_codec.lua")
    return require("gen3.entry"), json_
end)

-- title -> pack fallback, only used when admission cannot decide (Entry.PACKS keys).
local TITLE_TO_PACK = { firered = "gen3_frlg", leafgreen = "gen3_frlg", radical_red = "gen3_rr" }

local parts = step("build-parts", function()
    -- Admission (shadow_run.lua M.start's own flow): the pack/kind actually pinned to THIS
    -- loaded ROM, via gameinfo.getromhash() + the anchor scan Entry.admit runs when the hash
    -- is not itself in the admission table. `title` is already known from the checkpoint
    -- (SLINK_GEN3_TITLE), so it is passed through unconditionally; only pack/kind come from
    -- admission -- a guessed kind (e.g. always "clean") is the bug this replaces.
    local rom_hash = ""
    if gameinfo and gameinfo.getromhash then
        local ok_h, h = pcall(gameinfo.getromhash)
        if ok_h and h then rom_hash = h end
    end
    local ok_hc, header_code = pcall(Entry.header_code, io_ro.rom_read)
    local admitted, admit_err = Entry.admit({
        root = WT, json = json, rom_hash = rom_hash, rom_read = io_ro.rom_read,
        header_code = ok_hc and header_code or "",
    })
    local kind_override = os.getenv("SLINK_GEN3_KIND")
    local pack, kind, admitted_by
    if admitted then
        pack = admitted.pack
        kind = (kind_override and kind_override ~= "") and kind_override or admitted.kind
        admitted_by = admitted.admitted_by
    else
        pack = assert(TITLE_TO_PACK[title], "no pack mapping for gen3 title " .. tostring(title))
        kind = (kind_override and kind_override ~= "") and kind_override or "clean"
        admitted_by = "default(" .. tostring(admit_err) .. ")"
    end
    G.phase("admit", string.format("pack=%s kind=%s by=%s", pack, kind, admitted_by))

    local deps = {
        root = WT, mode = "observer", pack = pack, title = title, kind = kind,
        io = io_ro,
        ev = { on_bus_exec = ev_wrap.on_bus_exec, unregister = ev_wrap.unregister },
        net = nil, hud = nil,
        log = function(s) console.log("[reads-probe] " .. tostring(s)) end,
        -- the observer-only seam shadow_run.lua honours (EG2): an unadmitted title builds OBSERVER
        -- parts only when the run names exactly "<pack>/<title>" (X3: the expansion reference build)
        allow_unadmitted = os.getenv("SLINK_SHADOW_UNADMITTED"),
    }
    local _client, parts_ = Entry.build(deps)
    return parts_
end)
G.phase("entry", string.format("pack=%s title=%s kind=%s artifact_kind=%s",
                               parts.pack, parts.title, parts.kind, parts.artifact_kind))

local reads, profile = parts.reads, parts.profile
local d = profile.derived

local dump = assert(io.open(WT .. "/patch/build/gen3_reads_dump.txt", "w"))

local function hex_of(bytes)
    local out = {}
    for i = 1, #bytes do out[i] = string.format("%02x", bytes[i]) end
    return table.concat(out)
end

local function dump_line(name, addr, bytes)
    dump:write(string.format("DUMP name=%s addr=0x%X len=%d frame=%d hex=%s\n",
                             name, addr, #bytes, emu.framecount(), hex_of(bytes)))
    dump:flush()
end

local function lua_mon_line(name, slot, mon)
    dump:write(string.format("LUA name=%s slot=%d key=%s species=%s level=%s hp=%s nickname=%s\n",
        name, slot, reads.key(mon), tostring(mon.species), tostring(mon.level or ""),
        tostring(mon.hp or ""), mon.nickname))
    dump:flush()
end

local written = { dump = 0, lua = 0 }

-- ── party: dump, then decode, as TWO separate steps so a failure names which one ───────────
local party_base_addr, party_raw = step("dump-party", function()
    local a = profile.ram
    if not a.PARTY_COUNT_ADDR then
        G.phase("note", "profile has no ram.PARTY_COUNT_ADDR; party dump skipped")
        return nil, nil
    end
    local count = io_ro.read_u8(a.PARTY_COUNT_ADDR)
    local base, why = reads.party_base()
    if not base then
        G.phase("note", "party base unavailable: " .. tostring(why))
        return nil, nil
    end
    local n = (count <= reads.party_capacity) and count or 0
    local raw = io_ro.read_bytes(base, n * 100)
    dump_line("party", base, raw)
    written.dump = written.dump + 1
    return base, raw
end)

if party_base_addr then
    step("decode-party", function()
        local mons, bad = reads.read_party()
        if not mons then
            G.phase("note", "read_party(): " .. tostring(bad))
            return
        end
        for _, mon in ipairs(mons) do
            lua_mon_line("party", mon.slot, mon)
            written.lua = written.lua + 1
        end
    end)
end

-- ── box 0 (when the title's profile carries box geometry): dump, then decode ───────────────
local box_base, box_len = step("dump-box", function()
    local base, len
    if d.CFRU_COMPRESSED_BOX and type(d.CFRU_BOX_BASES) == "table" and d.CFRU_BOX_BASES[1] then
        base = d.CFRU_BOX_BASES[1]
        len = reads.mons_per_box * (d.COMPRESSED_MON_SIZE or 0x3A)
    elseif d.BOX_DATA_OFFSET and d.BOXES_PER_STORE then
        local storage, why = reads.read_storage()
        if not storage then
            G.phase("note", "box geometry present but storage pointer unavailable: " .. tostring(why))
            return nil, nil
        end
        base = storage + d.BOX_DATA_OFFSET
        len = reads.mons_per_box * 80
    else
        G.phase("note", "profile carries no box geometry (neither CFRU_BOX_BASES nor "
                     .. "BOX_DATA_OFFSET/BOXES_PER_STORE); box dump skipped")
        return nil, nil
    end
    local raw = io_ro.read_bytes(base, len)
    dump_line("box0", base, raw)
    written.dump = written.dump + 1
    return base, len
end)

if box_base then
    step("decode-box", function()
        local mons, bad = reads.read_box(0)
        if not mons then
            G.phase("note", "read_box(0): " .. tostring(bad))
            return
        end
        for _, mon in ipairs(mons) do
            lua_mon_line("box0", mon.slot, mon)
            written.lua = written.lua + 1
        end
    end)
end

dump:close()
G.phase("wrote", string.format("%d DUMP line(s), %d LUA line(s) -> gen3_reads_dump.txt",
                               written.dump, written.lua))
G.finish(written.dump > 0, string.format("%d dumps, %d decoded mon lines", written.dump, written.lua))
