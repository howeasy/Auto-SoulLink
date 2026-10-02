"""lua/nds/residency_contract.lua: the shared NDS residency strategy contract and its arming rule.

Reference fakes (written in Lua, over a Python byte-addressed "RAM") implement the contract with the real
geometries: an HGSS-shaped static 3 x 8 x 8 B array, and the Gen 5 heap block behind a pointer global:
header = u8 counts at P+0/+1/+2, u32 list pointers at P+4/+8/+0xC, region-0 entries inline from P+0x10, each
entry a {u32 id; u32 active} pair; counts BW 16/4/4, B2W2 20/4/4 (docs/gen5/research/rom_overlay_loader.md).
Their epoch() is the cheap kind the Gen 4 arming path needs: a pointer plus a loader-call counter plus a
boot/save generation counter, a few reads, never a hash of the slots. The module under test knows no geometry.
"""

from __future__ import annotations

from pathlib import Path

import lupa
import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "lua/nds/residency_contract.lua"

# -- fakes (Lua) -----------------------------------------------------------------------------------------
# `read(addr, size)` returns the little-endian unsigned integer of `size` bytes (default 4).
FAKES = r"""
local fp = function(acc, w) return (acc * 1000003 + w + 1) & 0x7FFFFFFF end

local function main_resident(slots, id)
    for _, e in ipairs(slots()) do if e.id == id and e.active and e.region == 0 then return true end end
    return false
end

-- HGSS shape: static array, 3 regions x 8 entries x 8 bytes {u32 id; u32 active}.
local function hgss(read, base, ctr_load, ctr_boot)
    local s = {}
    local function slots()
        local out = {}
        for r = 0, 2 do
            for i = 0, 7 do
                local p = base + (r * 8 + i) * 8
                out[#out + 1] = { id = read(p), active = read(p + 4) ~= 0, region = r }
            end
        end
        return out
    end
    function s.entries(rd) return slots() end
    function s.resident(id) return main_resident(slots, id) end
    function s.epoch() return fp(fp(0, read(ctr_load)), read(ctr_boot)) end -- 2 reads
    function s.geometry() return { kind = "static", regions = 3, per_region = 8, entry_size = 8 } end
    return s
end

-- Gen 5 shape: pointer global -> heap block P. u8 counts at P+0/+1/+2, u32 list pointers at P+4/+8/+0xC.
local function gen5(read, ptr_global, ctr_load, ctr_boot)
    local s = {}
    local function slots()
        local out, p = {}, read(ptr_global)
        if p == 0 then return out end -- manager not created yet
        for r = 1, 3 do
            local n, list = read(p + r - 1, 1), read(p + 4 * r)
            for i = 0, n - 1 do
                local q = list + i * 8
                out[#out + 1] = { id = read(q), active = read(q + 4) ~= 0, region = r - 1 }
            end
        end
        return out
    end
    function s.entries(rd) return slots() end
    function s.resident(id) return main_resident(slots, id) end
    function s.epoch() return fp(fp(fp(0, read(ptr_global)), read(ctr_load)), read(ctr_boot)) end -- 3 reads
    function s.geometry() return { kind = "heap" } end
    return s
end

-- A strategy with ALL-region residency semantics (the wrong one): any active entry counts.
local function all_region(base)
    local s = { entries = base.entries, epoch = base.epoch }
    function s.resident(id)
        for _, e in ipairs(base.entries()) do if e.id == id and e.active then return true end end
        return false
    end
    return s
end

-- Shallow state of a table, and equality of two such states (rawequal per key).
local function shallow(t) local c = {} for k, v in pairs(t) do c[k] = v end return c end
local function same(a, b)
    for k, v in pairs(a) do if not rawequal(b[k], v) then return false end end
    for k in pairs(b) do if a[k] == nil then return false end end
    return true
end
local function globals_count() local n = 0 for _ in pairs(_G) do n = n + 1 end return n end

return { hgss = hgss, gen5 = gen5, all_region = all_region, shallow = shallow, same = same,
         globals_count = globals_count }
"""

HGSS_BASE = 0x021D_0DF0
G5_PTR, G5_HEAP = 0x0210_0000, 0x0230_0000
CTR_LOAD, CTR_BOOT = 0x0220_0000, 0x0220_0004  # loader-call counter, boot/save generation counter
SITE_OV = {"id": "ov36_site", "overlay_id": 36}
SITE_STATIC = {"id": "arm9_site"}
COUNTS = {"hgss": (8, 8, 8), "gen5_bw": (16, 4, 4), "gen5_b2w2": (20, 4, 4)}
GEOMETRIES = sorted(COUNTS)


class Ram:
    """Byte-addressed little-endian memory; counts reads so epoch() cost can be asserted."""

    def __init__(self):
        self.mem: dict[int, int] = {}
        self.reads = 0

    def read(self, addr, size=4):
        self.reads += 1
        return int.from_bytes(bytes(self.mem.get(addr + i, 0) for i in range(size)), "little")

    def put(self, addr, value, size=4):
        for i, b in enumerate(value.to_bytes(size, "little")):
            self.mem[addr + i] = b


def slot_addr(geometry, region, i, heap=G5_HEAP):
    if geometry == "hgss":
        return HGSS_BASE + (region * 8 + i) * 8
    n = COUNTS[geometry]
    base = heap + 0x10  # region-0 entries are INLINE right after the 0x10-byte header
    for r in range(region):
        base += n[r] * 8
    return base + i * 8


def build(ram, geometry, ids=(), heap=G5_HEAP):
    """Lay out a table in `ram` with the given ids active in region 0 (slot order), others never loaded."""
    n = COUNTS[geometry]
    for r in range(3):
        for i in range(n[r]):
            a = slot_addr(geometry, r, i, heap)
            ram.put(a, 0xFFFF)
            ram.put(a + 4, 0)
    if geometry != "hgss":
        ram.put(G5_PTR, heap)
        for r in range(3):
            ram.put(heap + r, n[r], 1)  # u8 counts
            ram.put(heap + 4 + 4 * r, slot_addr(geometry, r, 0, heap))  # u32 list pointers
    for i, ovy in enumerate(ids):
        ram.put(slot_addr(geometry, 0, i, heap), ovy)
        ram.put(slot_addr(geometry, 0, i, heap) + 4, 1)
    return ram


def new_ram(geometry, ids=()):
    return build(Ram(), geometry, ids)


def loader_event(ram):
    ram.put(CTR_LOAD, ram.read(CTR_LOAD) + 1)


def unload(ram, geometry, ovy):
    for i in range(COUNTS[geometry][0]):
        a = slot_addr(geometry, 0, i)
        if ram.read(a) == ovy and ram.read(a + 4):
            ram.put(a + 4, 0)  # active cleared, the id stays
    loader_event(ram)


def load(ram, geometry, ovy):
    for i in range(COUNTS[geometry][0]):
        a = slot_addr(geometry, 0, i)
        if not ram.read(a + 4):  # first free slot
            ram.put(a, ovy)
            ram.put(a + 4, 1)
            break
    loader_event(ram)


@pytest.fixture()
def rt():
    lua = lupa.LuaRuntime()
    load_chunk = lua.eval("function(s, n) return assert(load(s, n))() end")
    return lua, load_chunk(MODULE.read_text(encoding="utf-8"), "=residency_contract"), load_chunk(FAKES, "=fakes")


def make(rt, geometry, ram):
    fakes = rt[2]
    if geometry == "hgss":
        return fakes.hgss(ram.read, HGSS_BASE, CTR_LOAD, CTR_BOOT)
    return fakes.gen5(ram.read, G5_PTR, CTR_LOAD, CTR_BOOT)


def R(v):
    """A Lua multi-return as a tuple (lupa gives a bare value for a single return)."""
    return v if isinstance(v, tuple) else (v,)


def T(rt, d):
    """A Lua table from a plain dict (sites are tables, not Python objects)."""
    return rt[0].table_from(d)


def py(v):
    if lupa.lua_type(v) != "table":
        return v
    keys = sorted(v.keys(), key=lambda k: (not isinstance(k, int), k if isinstance(k, int) else 0))
    if keys and keys == list(range(1, len(keys) + 1)):
        return [py(v[k]) for k in keys]
    return {k: py(v[k]) for k in keys}


# -- the reference geometries satisfy the contract --------------------------------------------------------------------
@pytest.mark.parametrize("geometry", GEOMETRIES)
def test_reference_fakes_pass_the_contract(rt, geometry):
    _, c, _ = rt
    ram = new_ram(geometry, (10, 11, 36))
    s = make(rt, geometry, ram)
    assert rt[0].eval("rawequal")(c.assert_strategy(s, ram.read), s)
    assert R(c.validate_strategy(s, ram.read)) == (True,)
    snap = c.snapshot(s, ram.read)
    entries = py(snap.entries)
    counts = COUNTS[geometry]
    assert len(entries) == sum(counts)
    assert [sum(1 for e in entries if e["region"] == r) for r in range(3)] == list(counts)
    assert {e["id"] for e in entries if e["active"]} == {10, 11, 36}
    assert [s.resident(i) for i in (10, 11, 36, 12, 0)] == [True, True, True, False, False]
    assert isinstance(snap.epoch, int)


@pytest.mark.parametrize("geometry", ["gen5_bw", "gen5_b2w2"])
def test_gen5_heap_block_header_is_not_an_entry(rt, geometry):
    """The block starts with u8 counts and u32 list pointers; region-0 entries begin at P+0x10. A reader that
    started at P would produce phantom entries from the header words."""
    ram = new_ram(geometry, (10, 11, 36))
    s = make(rt, geometry, ram)
    entries = py(s.entries(ram.read))
    assert entries[0] == {"id": 10, "active": True, "region": 0}  # entry 0 IS the first real {id, active}
    assert entries[1]["id"] == 11 and entries[2]["id"] == 36
    n0, n1, n2 = COUNTS[geometry]
    header_words = {ram.read(G5_HEAP + 4 * k) for k in range(4)}
    assert not header_words & {e["id"] for e in entries}  # no id was read out of the counts / pointer words
    assert ram.read(G5_HEAP, 1) == n0 and ram.read(G5_HEAP + 1, 1) == n1 and ram.read(G5_HEAP + 2, 1) == n2
    assert ram.read(G5_HEAP + 4) == G5_HEAP + 0x10  # list-0 pointer -> the inline entries
    assert len(entries) == n0 + n1 + n2
    # lists are FOLLOWED, not assumed contiguous: move list 2 elsewhere and the reader still finds its entry
    moved = G5_HEAP + 0x4000
    ram.put(G5_HEAP + 0xC, moved)
    ram.put(moved, 99)
    ram.put(moved + 4, 1)
    again = py(s.entries(ram.read))
    assert {"id": 99, "active": True, "region": 2} in again


@pytest.mark.parametrize("geometry", GEOMETRIES)
def test_a_stale_id_with_active_cleared_is_not_resident(rt, geometry):
    _, c, _ = rt
    ram = new_ram(geometry, (10, 36))
    s = make(rt, geometry, ram)
    unload(ram, geometry, 36)
    assert ram.read(slot_addr(geometry, 0, 1)) == 36 and s.resident(36) is False and s.resident(10) is True
    assert R(c.validate_strategy(s, ram.read)) == (True,)


def test_the_geometries_really_differ(rt):
    """Anti-vacuity: the same words read with the other geometry give a different answer, so a lane that
    hard-codes the other's shape (the Gen 4 hook_binding assert) would be wrong, not just stricter."""
    ram = new_ram("gen5_bw")
    ram.put(slot_addr("gen5_bw", 0, 10), 50)  # slot 10: region 0 of a 16/4/4 block, region 1 of a 3 x 8 array
    ram.put(slot_addr("gen5_bw", 0, 10) + 4, 1)
    g5 = make(rt, "gen5_bw", ram)
    hg = rt[2].hgss(ram.read, slot_addr("gen5_bw", 0, 0), CTR_LOAD, CTR_BOOT)  # HGSS reader on the same words
    assert g5.resident(50) is True and hg.resident(50) is False
    assert [e["region"] for e in py(g5.entries(ram.read))].count(0) == 16
    assert [e["region"] for e in py(hg.entries(ram.read))].count(0) == 8


# -- residency is region 0 only -----------------------------------------------------------------------------------
@pytest.mark.parametrize("geometry", GEOMETRIES)
def test_an_active_entry_in_another_region_does_not_fail_a_correct_region0_strategy(rt, geometry):
    _, c, fakes = rt
    ram = new_ram(geometry, (10,))
    a = slot_addr(geometry, 1, 0)
    ram.put(a, 77)
    ram.put(a + 4, 1)  # id 77 active in region 1 only
    s = make(rt, geometry, ram)
    assert any(e["id"] == 77 and e["active"] and e["region"] == 1 for e in py(s.entries(ram.read)))
    assert s.resident(77) is False
    assert R(c.validate_strategy(s, ram.read)) == (True,)
    wrong = fakes.all_region(s)  # counts region 1 too: the contract refuses that semantics
    ok, why = c.validate_strategy(wrong, ram.read)
    assert ok is False and "disagrees" in why


# -- malformed strategies are rejected ---------------------------------------------------------------------------
def lua_strategy(rt, body: str):
    return rt[0].eval("function(read) " + body + " end")(None)


GOOD = ("local s = {entries = function() return {{id = 1, active = true, region = 0}} end,"
        " resident = function(id) return id == 1 end, epoch = function() return 7 end}")


@pytest.mark.parametrize("name,body", [
    ("not a table", "return 42"),
    ("no entries", "return {resident = function() return false end, epoch = function() return 1 end}"),
    ("no resident", "return {entries = function() return {} end, epoch = function() return 1 end}"),
    ("no epoch", "return {entries = function() return {} end, resident = function() return false end}"),
    ("resident not callable", "return {entries = function() return {} end, resident = true, epoch = function() return 1 end}"),
    ("geometry not callable", GOOD + " s.geometry = 5 return s"),
])
def test_malformed_shapes_are_rejected(rt, name, body):
    _, c, _ = rt
    s = lua_strategy(rt, body)
    ok, why = c.validate_strategy(s)
    assert ok is False and why, name
    with pytest.raises(lupa.LuaError, match="invalid residency strategy"):
        c.assert_strategy(s)


@pytest.mark.parametrize("name,body,needle", [
    ("float epoch", GOOD + " s.epoch = function() return 1.5 end return s", "epoch"),
    ("string epoch", GOOD + " s.epoch = function() return 'x' end return s", "epoch"),
    ("entries not a table", GOOD + " s.entries = function() return 3 end return s", "array"),
    ("entry without id", GOOD + " s.entries = function() return {{active = true, region = 0}} end return s", "id"),
    ("entry active not boolean", GOOD + " s.entries = function() return {{id = 1, active = 1, region = 0}} end return s", "active"),
    ("entry without region", GOOD + " s.entries = function() return {{id = 1, active = true}} end return s", "region"),
    ("resident not boolean", GOOD + " s.resident = function(id) return id == 1 and 1 or false end return s", "boolean"),
    ("resident disagrees", GOOD + " s.resident = function() return false end return s", "disagrees"),
    ("unknown id resident", GOOD + " s.resident = function() return true end return s", "unknown"),
    ("epoch moves on its own", GOOD + " local n = 0 s.epoch = function() n = n + 1 return n end return s", "changed"),
])
def test_malformed_behaviour_is_rejected_when_exercised(rt, name, body, needle):
    _, c, _ = rt
    s = lua_strategy(rt, body)
    assert R(c.validate_strategy(s)) == (True,), "shape alone passes; behaviour needs a read"
    ok, why = c.validate_strategy(s, lambda *a: 0)
    assert ok is False and needle in why, (name, why)
    with pytest.raises(lupa.LuaError, match="invalid residency strategy"):
        c.assert_strategy(s, lambda *a: 0)


def test_a_good_hand_written_strategy_passes(rt):
    _, c, _ = rt
    s = lua_strategy(rt, GOOD + " return s")
    assert R(c.validate_strategy(s, lambda *a: 0)) == (True,)


def test_snapshot_forwards_read_so_behavioural_validation_runs_on_the_arming_path(rt):
    lua, c, _ = rt
    # a well-shaped strategy whose behaviour is wrong (resident disagrees with entries): shape alone passes,
    # so only a snapshot that forwards `read` into assert_strategy can catch it
    bad = lua_strategy(rt, GOOD + " s.resident = function() return false end return s")
    assert R(c.validate_strategy(bad)) == (True,)
    with pytest.raises(lupa.LuaError, match="disagrees"):
        c.snapshot(bad, lambda *a: 0)
    # and the very `read` the caller gave is the one the strategy's entries() receives
    seen = lua.eval(
        "function(c) local seen = {} local s = {entries = function(read) seen[#seen + 1] = read return {} end,"
        " resident = function() return false end, epoch = function() return 1 end}"
        " local sentinel = {} c.snapshot(s, sentinel) return #seen > 0 and rawequal(seen[#seen], sentinel) end"
    )
    assert seen(c) is True


# -- the arming rule: a residency flag alone never arms a hook ------------------------------------------------------
class Code:
    """Stands in for the site's registration pin: bytes at the site that are only right once the load is done."""

    def __init__(self):
        self.loaded = False
        self.reads = 0

    def confirmed(self, site):
        self.reads += 1
        return self.loaded


@pytest.mark.parametrize("geometry", GEOMETRIES)
def test_a_flag_that_leads_the_load_is_refused_until_the_pin_matches(rt, geometry):
    _, c, _ = rt
    ram = new_ram(geometry, (36,))  # active flag set, the code has not been copied yet (or the load failed)
    s = make(rt, geometry, ram)
    code = Code()
    snap = c.snapshot(s, ram.read)
    assert s.resident(36) is True  # the flag says yes ...
    assert R(c.may_arm(s, T(rt, SITE_OV), code.confirmed, snap.epoch)) == (False, "pin_mismatch")  # ... the bytes say no
    assert code.reads == 1  # the pin was re-read, not skipped
    code.loaded = True  # the load finishes
    assert R(c.may_arm(s, T(rt, SITE_OV), code.confirmed, snap.epoch)) == (True,)


@pytest.mark.parametrize("geometry", GEOMETRIES)
def test_a_failed_load_leaves_the_entry_active_and_the_hook_unarmed(rt, geometry):
    _, c, _ = rt
    ram = new_ram(geometry, (36,))
    s = make(rt, geometry, ram)
    code = Code()  # never loaded
    for _ in range(3):  # re-polling the stale flag never flips the answer
        assert R(c.may_arm(s, T(rt, SITE_OV), code.confirmed, c.snapshot(s, ram.read).epoch)) == (False, "pin_mismatch")


def test_no_pin_check_or_a_non_true_answer_never_arms(rt):
    _, c, _ = rt
    ram = new_ram("gen5_bw", (36,))
    s = make(rt, "gen5_bw", ram)
    e = s.epoch()
    assert R(c.may_arm(s, T(rt, SITE_OV), None, e)) == (False, "no_pin_check")
    assert R(c.may_arm(s, T(rt, SITE_STATIC), None)) == (False, "no_pin_check")
    for answer in ("yes", 1, "true"):
        assert R(c.may_arm(s, T(rt, SITE_OV), lambda site, a=answer: a, e)) == (False, "pin_mismatch")
    assert R(c.may_arm(s, T(rt, SITE_OV), lambda site: None, e)) == (False, "pin_mismatch")

    def boom(site):
        raise RuntimeError("unreadable")

    assert R(c.may_arm(s, T(rt, SITE_OV), boom, e)) == (False, "pin_error")


def test_a_static_site_needs_the_pin_but_not_residency_or_an_epoch(rt):
    _, c, _ = rt
    s = make(rt, "hgss", new_ram("hgss"))  # nothing resident at all
    assert R(c.may_arm(s, T(rt, SITE_STATIC), lambda site: True)) == (True,)
    assert R(c.may_arm(s, T(rt, SITE_STATIC), lambda site: False)) == (False, "pin_mismatch")


@pytest.mark.parametrize("geometry", GEOMETRIES)
def test_stale_epoch_is_refused_and_a_fresh_snapshot_recovers(rt, geometry):
    _, c, _ = rt
    ram = new_ram(geometry, (36,))
    s = make(rt, geometry, ram)
    code = Code()
    code.loaded = True
    old = c.snapshot(s, ram.read).epoch
    assert R(c.may_arm(s, T(rt, SITE_OV), code.confirmed, old)) == (True,)
    unload(ram, geometry, 36)
    load(ram, geometry, 36)  # reloaded into another slot: the same residency answer, a different table
    assert s.resident(36) is True
    assert R(c.may_arm(s, T(rt, SITE_OV), code.confirmed, old)) == (False, "stale_epoch")
    assert R(c.may_arm(s, T(rt, SITE_OV), code.confirmed, c.snapshot(s, ram.read).epoch)) == (True,)


def test_a_relocated_gen5_heap_block_changes_the_epoch(rt):
    ram = new_ram("gen5_bw", (36,))
    s = make(rt, "gen5_bw", ram)
    before = s.epoch()
    build(ram, "gen5_bw", (36,), heap=G5_HEAP + 0x1000)  # same words at a new address: only the pointer differs
    assert s.resident(36) is True and s.epoch() != before


@pytest.mark.parametrize("geometry", GEOMETRIES)
def test_epoch_is_cheap_and_changes_on_boot_even_if_the_heap_reuses_the_same_addresses(rt, geometry):
    """Gen 4 cost requirement: epoch() is at most a few reads, and a soft reset / Continue / New Game changes it
    even when the table is rebuilt at identical addresses with identical words."""
    _, c, _ = rt
    ram = new_ram(geometry, (10, 36))
    s = make(rt, geometry, ram)
    code = Code()
    code.loaded = True
    before_reads = ram.reads
    old = s.epoch()
    assert ram.reads - before_reads <= 4, "epoch() must be a few reads, not a hash of the table"
    assert R(c.may_arm(s, T(rt, SITE_OV), code.confirmed, old)) == (True,)
    snapshot_words = dict(ram.mem)
    build(ram, geometry, (10, 36))  # the game re-created the table: same addresses, same-looking words
    assert ram.mem == snapshot_words and s.epoch() == old  # nothing about the words can tell: that is the trap
    ram.put(CTR_BOOT, ram.read(CTR_BOOT) + 1)  # boot/save generation counter bumps on reset / Continue / New Game
    assert s.epoch() != old
    assert R(c.may_arm(s, T(rt, SITE_OV), code.confirmed, old)) == (False, "stale_epoch")
    assert R(c.may_arm(s, T(rt, SITE_OV), code.confirmed, c.snapshot(s, ram.read).epoch)) == (True,)


def test_an_overlay_site_without_an_epoch_is_refused(rt):
    _, c, _ = rt
    s = make(rt, "hgss", new_ram("hgss", (36,)))
    assert R(c.may_arm(s, T(rt, SITE_OV), lambda site: True)) == (False, "epoch_required")


@pytest.mark.parametrize("geometry", GEOMETRIES)
def test_not_resident_is_refused_even_if_the_pin_matches(rt, geometry):
    """Another overlay may hold the same RAM, whose bytes could even coincide: residency is necessary."""
    _, c, _ = rt
    s = make(rt, geometry, new_ram(geometry, (10,)))
    assert R(c.may_arm(s, T(rt, SITE_OV), lambda site: True, s.epoch())) == (False, "not_resident")
    assert R(c.may_fire(s, T(rt, SITE_OV), lambda site: True)) == (False, "not_resident")


@pytest.mark.parametrize("geometry", GEOMETRIES)
def test_fire_rereads_the_pin_every_time(rt, geometry):
    _, c, _ = rt
    s = make(rt, geometry, new_ram(geometry, (36,)))
    code = Code()
    code.loaded = True
    assert R(c.may_fire(s, T(rt, SITE_OV), code.confirmed)) == (True,)
    code.loaded = False  # the overlay was replaced (aliasing) while the hook stayed registered
    assert R(c.may_fire(s, T(rt, SITE_OV), code.confirmed)) == (False, "pin_mismatch")
    assert code.reads == 2
    assert R(c.may_fire(s, T(rt, SITE_OV), None)) == (False, "no_pin_check")


def test_bad_strategy_and_bad_site_never_arm(rt):
    _, c, _ = rt
    ok = lambda site: True  # noqa: E731
    s = make(rt, "hgss", new_ram("hgss", (36,)))
    bad = lua_strategy(rt, "return {}")
    assert R(c.may_arm(bad, T(rt, SITE_STATIC), ok)) == (False, "bad_strategy")
    assert R(c.may_fire(bad, T(rt, SITE_STATIC), ok)) == (False, "bad_strategy")
    for site in (None, {}, {"id": ""}, {"id": "x", "overlay_id": 1.5}, {"id": 3}):
        arg = None if site is None else T(rt, site)
        assert R(c.may_arm(s, arg, ok, 1)) == (False, "bad_site"), site
        assert R(c.may_fire(s, arg, ok)) == (False, "bad_site"), site


@pytest.mark.parametrize("geometry", GEOMETRIES)
def test_arming_and_firing_are_pure_checks_with_no_state_of_their_own(rt, geometry):
    """may_arm / may_fire / snapshot never mutate the strategy, the site, the module, RAM or _G, and never
    consume anything: the same inputs give the same answer, any number of times (the caller's single-shot
    lease is the only state)."""
    lua, c, fakes = rt
    ram = new_ram(geometry, (36,))
    s = make(rt, geometry, ram)
    site = T(rt, SITE_OV)
    code = Code()
    code.loaded = True
    epoch = s.epoch()
    before = (fakes.shallow(s), fakes.shallow(site), fakes.shallow(c), dict(ram.mem), fakes.globals_count())
    answers = []
    for _ in range(4):
        answers.append((R(c.may_arm(s, site, code.confirmed, epoch)), R(c.may_fire(s, site, code.confirmed))))
        c.snapshot(s, ram.read)
    assert answers == [((True,), (True,))] * 4  # nothing was consumed
    assert fakes.same(before[0], fakes.shallow(s)) and fakes.same(before[1], fakes.shallow(site))
    assert fakes.same(before[2], fakes.shallow(c))
    assert dict(ram.mem) == before[3] and fakes.globals_count() == before[4]
    # refusals are pure too, and repeat identically
    code.loaded = False
    assert [R(c.may_arm(s, site, code.confirmed, epoch)) for _ in range(3)] == [(False, "pin_mismatch")] * 3
    assert fakes.same(before[0], fakes.shallow(s)) and dict(ram.mem) == before[3]


def test_reasons_are_the_documented_tokens(rt):
    _, c, _ = rt
    assert set(py(c.REASONS)) >= {"stale_epoch", "pin_mismatch", "not_resident", "no_pin_check", "epoch_required"}
    doc = (ROOT / "docs/shared-nds-residency.md").read_text(encoding="utf-8")
    for token in py(c.REASONS):
        assert token in doc, f"docs/shared-nds-residency.md does not document the refusal {token!r}"


# -- hygiene ---------------------------------------------------------------------------------------------------------
def test_module_has_no_game_geometry_and_leaks_no_globals():
    lines = MODULE.read_text(encoding="utf-8").splitlines()
    code = chr(10).join(ln for ln in lines if not ln.lstrip().startswith("--"))
    for banned in ("per_region", "entry_size", "0x021D", "0x0200", "region_count", "memory.", "emu.", "client."):
        assert banned not in code, banned
    lua = lupa.LuaRuntime()
    dump = lua.eval("function() local t = {} for k in pairs(_G) do t[#t + 1] = k end return t end")
    before = set(py(dump()))
    lua.eval("function(s) return assert(load(s, '=rc'))() end")(MODULE.read_text(encoding="utf-8"))
    assert set(py(dump())) == before


def test_controls_a_module_that_arms_on_the_flag_alone_fails_the_fake():
    """Revert test: drop the pin check from may_arm and the lead-flag fake must be armed (the test would go red)."""
    src = MODULE.read_text(encoding="utf-8")
    old = "    return pin_ok(site, site_confirmed)\nend\n\n-- May an armed hook FIRE"
    assert src.count(old) == 1
    lua = lupa.LuaRuntime()
    load_chunk = lua.eval("function(s, n) return assert(load(s, n))() end")
    weak = load_chunk(src.replace(old, "    return true\nend\n\n-- May an armed hook FIRE"), "=weak")
    strong = load_chunk(src, "=strong")
    fakes = load_chunk(FAKES, "=f")
    ram = new_ram("gen5_bw", (36,))
    s = fakes.gen5(ram.read, G5_PTR, CTR_LOAD, CTR_BOOT)
    code = Code()
    site = lua.table_from(SITE_OV)
    assert R(weak.may_arm(s, site, code.confirmed, s.epoch())) == (True,)  # the weakened module arms: bad
    assert R(strong.may_arm(s, site, code.confirmed, s.epoch())) == (False, "pin_mismatch")
    # and a region filter dropped from validate must let the all-region strategy through
    region_old = "if entry.active and entry.region == 0 then active[entry.id] = true end"
    assert src.count(region_old) == 1
    weak2 = load_chunk(src.replace(region_old, "if entry.active then active[entry.id] = true end"), "=weak2")
    ram2 = new_ram("gen5_bw", (10,))
    a = slot_addr("gen5_bw", 1, 0)
    ram2.put(a, 77)
    ram2.put(a + 4, 1)
    base = fakes.gen5(ram2.read, G5_PTR, CTR_LOAD, CTR_BOOT)
    assert R(strong.validate_strategy(base, ram2.read)) == (True,)
    assert R(weak2.validate_strategy(base, ram2.read))[0] is False  # the loosened module rejects the correct one
