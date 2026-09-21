-- probe_gen3_reads_dump.lua — P3 "reads == PYDEC" dump (card gen3-P3-C3-14, PLAN §5.7).
--
-- Proves lua/gen3/reads.lua decodes exactly what server/adapters/gen3_codec.py decodes from
-- the SAME bytes, on REAL HARDWARE BYTES, never from a disk save. This probe only produces
-- the raw+decoded evidence; the comparison itself is tools/gen3_reads_pydec.py (a separate
-- process, so neither side can borrow the other's arithmetic).
--
-- Builds the REAL observer parts the same way lua/gen3/shadow_run.lua does (reused, not
-- reimplemented: M.build_io / M.build_ev from that file), then on the field, at frame end:
--   (a) dumps the raw party bytes and (when the title has box geometry) the raw box 0 bytes
--       as hex lines: "DUMP name=<party|box0> addr=0x... len=N frame=F hex=..."
--   (b) decodes them through parts.reads (:read_party() / :read_box(0)) and writes one line
--       per mon: "LUA name=<party|box0> slot=i key=PID:OTID species=N level=N hp=N nickname=..."
-- into patch/build/gen3_reads_dump.txt (tools/gen3_reads_pydec.py's only input).
--
-- Environment: SLINK_ROOT, SLINK_GEN3_CHECKPOINT/TITLE (gen3_boot_check.lua helpers),
-- SLINK_STATE (a savestate to load; when unset, boots to the field via G.boot_to_field),
-- SLINK_GEN3_KIND (optional; "clean" default, "companion" for the RR companion build).
--
-- An empty party (e.g. the FR pre-starter fixture) is reported HONESTLY: a DUMP line with
-- len=0 hex="" and zero LUA lines, never a failure. Box geometry absent from the title's
-- profile (derived has neither CFRU_BOX_BASES nor BOX_DATA_OFFSET/BOXES_PER_STORE) is a NOTE
-- line, also not a failure — the RESULT only fails when the probe itself errors.

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

-- ── build the real observer parts (shadow_run.lua's shape, reused not reimplemented) ────────
local io_ro = SR.build_io(memory, function(name) return emu.getregister(name) end,
                          function() return emu.framecount() end)
local ev_wrap = SR.build_ev(event, "SLink-gen3-reads-probe-")

package.path = WT .. "/lua/?.lua;" .. package.path
local Entry = require("gen3.entry")

-- title -> pack: the same union entry.lua's own PACKS table names (Entry.PACKS keys), so a
-- new title only needs adding there, not here.
local TITLE_TO_PACK = { firered = "gen3_frlg", leafgreen = "gen3_frlg", radical_red = "gen3_rr" }
local pack = assert(TITLE_TO_PACK[title], "no pack mapping for gen3 title " .. tostring(title))
local kind = os.getenv("SLINK_GEN3_KIND")
if not kind or kind == "" then kind = "clean" end

local deps = {
    root = WT, mode = "observer", pack = pack, title = title, kind = kind,
    io = io_ro,
    ev = { on_bus_exec = ev_wrap.on_bus_exec, unregister = ev_wrap.unregister },
    log = function(s) console.log("[reads-probe] " .. tostring(s)) end,
}
local _client, parts = Entry.build(deps)
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

-- ── party ─────────────────────────────────────────────────────────────────────────────────
local a = profile.ram
if not a.PARTY_COUNT_ADDR then
    G.phase("note", "profile has no ram.PARTY_COUNT_ADDR; party dump skipped")
else
    local count = io_ro.read_u8(a.PARTY_COUNT_ADDR)
    local base, why = reads.party_base()
    if not base then
        G.phase("note", "party base unavailable: " .. tostring(why))
    else
        local n = (count <= reads.party_capacity) and count or 0
        local raw = io_ro.read_bytes(base, n * 100)
        dump_line("party", base, raw)
        written.dump = written.dump + 1
        local mons, bad = reads.read_party()
        if not mons then
            G.phase("note", "read_party(): " .. tostring(bad))
        else
            for _, mon in ipairs(mons) do
                lua_mon_line("party", mon.slot, mon)
                written.lua = written.lua + 1
            end
        end
    end
end

-- ── box 0 (when the title's profile carries box geometry) ──────────────────────────────────
local box_base, box_len
if d.CFRU_COMPRESSED_BOX and type(d.CFRU_BOX_BASES) == "table" and d.CFRU_BOX_BASES[1] then
    box_base = d.CFRU_BOX_BASES[1]
    box_len = reads.mons_per_box * (d.COMPRESSED_MON_SIZE or 0x3A)
elseif d.BOX_DATA_OFFSET and d.BOXES_PER_STORE then
    local storage, why = reads.read_storage()
    if not storage then
        G.phase("note", "box geometry present but storage pointer unavailable: " .. tostring(why))
    else
        box_base = storage + d.BOX_DATA_OFFSET
        box_len = reads.mons_per_box * 80
    end
else
    G.phase("note", "profile carries no box geometry (neither CFRU_BOX_BASES nor "
                 .. "BOX_DATA_OFFSET/BOXES_PER_STORE); box dump skipped")
end
if box_base then
    local raw = io_ro.read_bytes(box_base, box_len)
    dump_line("box0", box_base, raw)
    written.dump = written.dump + 1
    local mons, bad = reads.read_box(0)
    if not mons then
        G.phase("note", "read_box(0): " .. tostring(bad))
    else
        for _, mon in ipairs(mons) do
            lua_mon_line("box0", mon.slot, mon)
            written.lua = written.lua + 1
        end
    end
end

dump:close()
G.phase("wrote", string.format("%d DUMP line(s), %d LUA line(s) -> gen3_reads_dump.txt",
                               written.dump, written.lua))
G.finish(written.dump > 0, string.format("%d dumps, %d decoded mon lines", written.dump, written.lua))
