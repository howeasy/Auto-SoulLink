-- test_live_partyevents.lua — LIVE validation of the EvRing PARTY producers (ROADMAP §4).
-- The patch's frame hook polls gPlayerPartyCount and the per-slot species (CFRU NO_ENCRYPT: raw
-- u16 at mon+0x20) and pushes EV_PARTY_ADD (count grew — catch / gift / withdraw / trade-in) and
-- EV_EVOLVE (a slot's species changed in place) into the EvRing @0x0203FD10.
--
-- We drive both by writing party RAM directly — the producer keys off DELTAS, not on who wrote
-- them, exactly like the faint-counter producers. Also covers the two safety properties the
-- boot-default invariant depends on:
--   * priming: with prim=0 the next frame LATCHES ONLY (no burst of spurious events for a party
--     that was already there) — this is what makes all-zero EWRAM reproduce the old behaviour;
--   * an empty->filled or filled->empty slot is NOT an evolution (0 on either side).
--   EmuHawk.exe --lua=lua/tests/test_live_partyevents.lua patch/build/slink_RR.gba

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT = WT .. "/patch/build/partyevents_result.txt"
local STATE = "E:/Howard/Bizhawk/GBA/State/slink_overworld.State"
local MB  = dofile(WT .. "/lua/mailbox.lua")

local PARTY_BASE  = 0x02024284
local PARTY_COUNT = 0x02024029
local MON_SIZE    = 100
local SPECIES_OFF = 0x20

local lines, fails = {}, 0
local function log(s) lines[#lines + 1] = s; console.log(s) end
local function check(n, c, e) if not c then fails = fails + 1 end
    log(string.format("  [%s] %s%s", c and "PASS" or "FAIL", n, e and "  " .. e or "")) end
local function finish() log(fails == 0 and "RESULT: PASS" or ("RESULT: FAIL (" .. fails .. ")"))
    local f = io.open(OUT, "w"); if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
    client.exit() end
local function abort(why) fails = fails + 1; log("ABORT: " .. why); finish() end

local function species(slot)      return memory.read_u16_le(PARTY_BASE + slot * MON_SIZE + SPECIES_OFF) end
local function set_species(slot, s) memory.write_u16_le(PARTY_BASE + slot * MON_SIZE + SPECIES_OFF, s) end
local function frames(n) for _ = 1, n do emu.frameadvance() end end
local function of_type(evs, t)
    local out = {}
    for _, e in ipairs(evs) do if e.type == t then out[#out + 1] = e end end
    return out
end

pcall(function() client.speedmode(400) end)
pcall(memory.usememorydomain, "System Bus")
local ok_ss = pcall(savestate.load, STATE)
frames(30)
if not MB.present() then abort("beacon never appeared (unpatched ROM?)  ss_loaded=" .. tostring(ok_ss)); return end

local count0 = memory.read_u8(PARTY_COUNT)
if count0 < 1 or count0 > 6 then abort("savestate has no usable party (count=" .. count0 .. ")"); return end
log(string.format("party count=%d slot0 species=%d", count0, species(0)))

MB.events_init()
frames(5)
check("ring quiet after init", #MB.events_drain() == 0)

-- ── priming: clearing prim must LATCH, not replay the existing party as events ───────────────
memory.write_u8(MB.EVR_PRIM, 0)
frames(5)
local evs = MB.events_drain()
check("re-prime emits nothing for the party already present", #evs == 0, "#evs=" .. #evs)

-- ── EV_EVOLVE: species changes in place ─────────────────────────────────────────────────────
local orig0 = species(0)
local evolved = (orig0 == 3) and 6 or 3          -- any other real species
set_species(0, evolved)
frames(5)
evs = of_type(MB.events_drain(), MB.EV_EVOLVE)
check("in-place species change -> one EV_EVOLVE", #evs == 1, "#evs=" .. #evs)
check("EV_EVOLVE carries slot + NEW species",
      evs[1] and evs[1].a == 0 and evs[1].b == evolved,
      string.format("a=%s b=%s want a=0 b=%d", tostring(evs[1] and evs[1].a),
                    tostring(evs[1] and evs[1].b), evolved))
set_species(0, orig0)                            -- restore (fires one more evolve; drained below)
frames(5); MB.events_drain()

-- ── an empty slot filling is NOT an evolution ───────────────────────────────────────────────
local free = count0                               -- first slot past the party is empty
if free <= 5 then
    local prev = species(free)
    set_species(free, 25)
    frames(5)
    evs = of_type(MB.events_drain(), MB.EV_EVOLVE)
    check("0 -> species is not an evolution", #evs == 0, "#evs=" .. #evs)
    set_species(free, prev)
    frames(5); MB.events_drain()
else
    log("  [SKIP] full party — no empty slot to test")
end

-- ── the case the client's stats cache used to miss ──────────────────────────────────────────
-- The client only re-read a party mon's combat stats when its KEY or LEVEL changed. An evolution
-- keeps the key (personality/OT are untouched in Gen 3), and a STONE or TRADE evolution keeps the
-- level too — so those stats stayed at their pre-evolution values indefinitely. Prove the ring
-- fires in exactly that situation: species changes while key and level do not.
do
    local OFF_PID, OFF_OTID, OFF_LEVEL = 0x00, 0x04, 0x54
    local base = PARTY_BASE
    local pid0  = memory.read_u32_le(base + OFF_PID)
    local otid0 = memory.read_u32_le(base + OFF_OTID)
    local lv0   = memory.read_u8(base + OFF_LEVEL)
    local sp0   = species(0)
    local evolved = (sp0 == 26) and 25 or 26          -- Raichu <-> Pikachu, no level change
    set_species(0, evolved)
    frames(5)
    local evs = of_type(MB.events_drain(), MB.EV_EVOLVE)
    check("stone/trade evolution (species changes, key + level do NOT) still fires EV_EVOLVE",
          #evs == 1 and evs[1].b == evolved,
          string.format("#evs=%d b=%s want=%d", #evs, tostring(evs[1] and evs[1].b), evolved))
    check("the key really did not change (that is why the old cache gate missed this)",
          memory.read_u32_le(base + OFF_PID) == pid0
          and memory.read_u32_le(base + OFF_OTID) == otid0)
    check("the level really did not change", memory.read_u8(base + OFF_LEVEL) == lv0)
    set_species(0, sp0)
    frames(5); MB.events_drain()
end

-- ── EV_PARTY_ADD: count grows ───────────────────────────────────────────────────────────────
if count0 <= 5 then
    set_species(count0, 25)                       -- Pikachu in the slot that is about to appear
    memory.write_u8(PARTY_COUNT, count0 + 1)
    frames(5)
    evs = of_type(MB.events_drain(), MB.EV_PARTY_ADD)
    check("count grew -> one EV_PARTY_ADD", #evs == 1, "#evs=" .. #evs)
    check("EV_PARTY_ADD carries the new count + species",
          evs[1] and evs[1].a == count0 + 1 and evs[1].b == 25,
          string.format("a=%s b=%s want a=%d b=25", tostring(evs[1] and evs[1].a),
                        tostring(evs[1] and evs[1].b), count0 + 1))

    -- shrinking back must NOT push EV_PARTY_ADD (only growth is an event)
    memory.write_u8(PARTY_COUNT, count0)
    frames(5)
    check("count shrink emits no EV_PARTY_ADD",
          #of_type(MB.events_drain(), MB.EV_PARTY_ADD) == 0)
else
    log("  [SKIP] party already full — cannot grow the count")
end

finish()
