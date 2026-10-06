"""Polished pokedb ALLOCATION boundaries of the box executor's deposit (box_mon) and its module-level insert.

The allocator (lua/gen2/polished_boxes.lua plan()) takes the first pokedb entry, bank 1 then bank 2, that is
unreferenced by ANY of the 40 box records (gameplay AND backup copy) and whose WRAM allocation flag is clear.
The engine never frees an entry on withdraw, so flags can exhaust while boxes are empty; SLink must refuse then,
never clear a flag. The places an off-by-one hides are the section edges (entry -> SRAM address) and the flag
byte edges (entry -> WRAM byte/bit), so every landing is checked as an EXACT whole-image diff against an
independently built expected image (CartRAM + WRAM), not as "the key shows up somewhere".

Boundaries are DERIVED, not assumed (test_the_boundaries_are_derived_from_the_geometry): section A holds
floor(0x2000 / 49) = 167 entries (one SRAM bank), section C holds (sBoxMons2C - sBoxMons1C) / 49 = 12, B is the
rest of 207 = 28. So A = 1..167, B = 168..195, C = 196..207; flag byte edges fall every 8 entries.

Red controls: each allocator mutation (backup copy ignored, gameplay copy ignored, flag ignored, scan starts at 2,
scan stops at 206, bank 2 without the Banks bit, bank 2 never scanned, section / flag-byte arithmetic off by one)
must make its matching scenario land somewhere else.
"""
from __future__ import annotations

import pytest

from server.adapters import polished_codec as pc
from tests.unit.test_polished_boxes import FLAG_FLAT, SECTION_FLAT, Env, Image, _pair, env
from tests.unit.test_polished_write_path import (
    BOXES,
    MEMORIAL_BOX,
    PER_BOX,
    SECTION_SIZE,
    SYM,
    Rig,
    _deposit,
    _mutant,
    box_flat,
    entry_flat,
    entry_for,
    fill,
    key_of,
    party,
    seal_save,
)

PER_BANK = 207
# the flag-byte edges (entry 8 = byte 0 bit 7, 9 = byte 1 bit 0, ...) and the three section edges, both sides
EDGES = [1, 2, 8, 9, 16, 17, 166, 167, 168, 169, 194, 195, 196, 197, 206, 207]
BANK2_EDGES = [1, 8, 9, 167, 168, 195, 196, 207]
SLOT = 1                      # deposits land in box 1 slot 1 (the first free slot of the first non-full box)


# ── derived geometry ─────────────────────────────────────────────────────────

def test_the_boundaries_are_derived_from_the_geometry():
    sram_bank = 0x2000
    a_end = sram_bank // SECTION_SIZE                                   # the biggest run that fits one SRAM bank
    c_count = (SECTION_FLAT[2, "C"] - SECTION_FLAT[1, "C"]) // SECTION_SIZE
    assert (SECTION_FLAT[2, "C"] - SECTION_FLAT[1, "C"]) % SECTION_SIZE == 0
    b_count = PER_BANK - a_end - c_count
    assert (a_end, a_end + 1, a_end + b_count, a_end + b_count + 1) == (167, 168, 195, 196) and c_count == 12
    # the sym agrees with the hand geometry (section starts as flat CartRAM offsets)
    for (d, letter), flat in SECTION_FLAT.items():
        bank, addr = SYM[f"sBoxMons{d}{letter}"]
        assert bank * 0x2000 + addr - 0xA000 == flat
    # section A of each pokedb bank really fits its SRAM bank, one more entry would not
    assert SECTION_FLAT[1, "A"] % sram_bank + a_end * SECTION_SIZE <= sram_bank
    assert SECTION_FLAT[1, "A"] % sram_bank + (a_end + 1) * SECTION_SIZE > sram_bank
    # entry_flat() (the independent address function) is continuous inside a section and jumps between them
    assert entry_flat(1, 168) == SECTION_FLAT[1, "B"] and entry_flat(1, 196) == SECTION_FLAT[1, "C"]
    assert entry_flat(1, 167) == SECTION_FLAT[1, "A"] + 166 * SECTION_SIZE
    # the allocation flag window: bit (e-1) of 26 WRAM bytes (208 bits for 207 entries)
    assert (PER_BANK - 1) // 8 == 25 and all(e in range(1, PER_BANK + 1) for e in EDGES)


# ── image + expected-image helpers ───────────────────────────────────────────

def flag_all(img, d):
    img.mem["WRAM"][FLAG_FLAT[d]:FLAG_FLAT[d] + 26] = b"\xff" * 26


def flag_below(img, d, n):
    """Allocation flags 1..n-1 of bank d set, nothing pointing at them: withdrawn mons' orphans."""
    for e in range(1, n):
        img.flag(d, e)


def fresh(setup):
    """A sealed save image + the three party mons, `setup(img)` applied, junk bit set in box 1 slot 1."""
    img = seal_save(Image())
    img.mem["CartRAM"][box_flat(1) + 0x14] = 0x01       # an empty slot's old bank bit is junk (§1.1): must be CLEARED
    setup(img)
    return img


def expected_after(before, d, n, entry, box=1, slot=SLOT):
    cart, wram = bytearray(before["CartRAM"]), bytearray(before["WRAM"])
    cart[entry_flat(d, n):entry_flat(d, n) + SECTION_SIZE] = entry
    wram[FLAG_FLAT[d] + (n - 1) // 8] |= 1 << ((n - 1) % 8)
    rec = box_flat(box)
    cart[rec + slot - 1] = n
    at, bit = rec + 0x14 + (slot - 1) // 8, 1 << ((slot - 1) % 8)
    cart[at] = (cart[at] | bit) if d == 2 else (cart[at] & ~bit & 0xFF)
    return {"CartRAM": bytes(cart), "WRAM": bytes(wram)}


def deposit(setup, boxes_source=None, via_client=False):
    """Deposit party slot 1 over the image `setup` builds. -> (img, before, mons, ok, reason).
    via_client: the composed client's box_mon command; otherwise the (possibly mutated) boxes module through
    the real overworld deposit()."""
    mons = party()
    img = fresh(setup)
    before = img.snap()
    rig = Rig(mons, img=img)
    key = key_of(mons[1])
    if via_client and boxes_source is None:
        rig.send_command({"cmd": "box_mon", "key": key})
        reasons = [m["reason"] for m in rig.sent("box_mon_failed")]
        return rig, img, before, mons, rig.count() == 2 and not reasons, "; ".join(reasons)
    path = _mutant(rig, None, boxes_source)
    rig.lua.globals().SLINK_PARTS = rig.parts
    done, why = _pair(_deposit(rig.lua, path.boxes, 1))
    return rig, img, before, mons, done is True, why


def lands_exactly(setup, d, n, boxes_source=None, via_client=False):
    """True when the deposit succeeded AND the whole image equals the independently built expected image."""
    rig, img, before, mons, ok, why = deposit(setup, boxes_source, via_client)
    if not ok:
        return False, f"refused: {why}"
    entry = bytes(img.mem["CartRAM"][entry_flat(d, n):entry_flat(d, n) + SECTION_SIZE])
    if entry != entry_for(mons[1]) or not pc.verify(entry):
        return False, "entry bytes are not the sealed deposit entry"
    if img.snap() != expected_after(before, d, n, entry):
        diff = [(dom, i) for dom in before for i, (a, b) in enumerate(zip(before[dom], img.snap()[dom], strict=True)) if a != b]
        return False, f"image differs from the expected one ({len(diff)} bytes changed: {diff[:4]}...)"
    return True, "ok"


# ── scenarios (setup, expected (bank, entry)) ────────────────────────────────

def first_free(d, n):
    def setup(img):
        if d == 2:
            flag_all(img, 1)
        flag_below(img, d, n)
    return setup


def referenced_only(copy, r):
    """Entry r is UNFLAGGED but a record of `copy` points at it (box 3 slot 1); 1..r-1 are flagged orphans."""
    def setup(img):
        flag_below(img, 1, r)
        img.point(3, 1, 1, r, backup=(copy == "backup"))
    return setup


def orphan(r):
    """Entry r is flagged, unreferenced, and still holds a withdrawn mon's valid bytes; 1..r-1 flagged too."""
    def setup(img):
        flag_below(img, 1, r)
        img.put(1, r, entry_for(party()[0]))
        img.flag(1, r)
    return setup


def bank_after(n):
    return (1, n) if n <= PER_BANK else (2, n - PER_BANK)


# ── (a) the next deposit lands exactly at N ──────────────────────────────────

@pytest.mark.parametrize("n", EDGES)
def test_bank1_the_next_deposit_lands_exactly_at_the_first_free_entry(n):
    ok, why = lands_exactly(first_free(1, n), 1, n, via_client=True)
    assert ok, (n, why)


@pytest.mark.parametrize("n", BANK2_EDGES)
def test_bank2_edges_land_exactly_with_the_banks_bit_set(n):
    """(b) with n == 1: bank 1 completely flagged -> bank 2 entry 1, Banks bit SET, read back through the census."""
    ok, why = lands_exactly(first_free(2, n), 2, n, via_client=True)
    assert ok, (n, why)


def test_the_rollover_reads_back_through_the_census_as_bank_2():
    rig, img, before, mons, ok, why = deposit(first_free(2, 1), via_client=True)
    assert ok, why
    boxes, cwhy = rig.census_keys()
    assert boxes is not None and key_of(mons[1]) in boxes[1], cwhy
    mon = next(m for m in rig.overworld().census.read_storage_box(0)["mons"].values() if m["key"] == key_of(mons[1]))
    assert (mon["bank"], mon["entry"]) == (2, 1)
    assert img.mem["CartRAM"][box_flat(1) + 0x14] & 1 == 1 and img.mem["CartRAM"][box_flat(1)] == 1


# ── (c) both banks exhausted: refuse, zero writes ────────────────────────────

def test_both_banks_fully_flagged_refuse_with_zero_writes():
    def setup(img):
        flag_all(img, 1)
        flag_all(img, 2)
    rig, img, before, mons, ok, why = deposit(setup, via_client=True)
    assert not ok and "no free pokedb entry" in why and "native save required" in why, why
    assert img.snap() == before and rig.writes() == [] and rig.count() == 3


def test_one_entry_left_in_the_last_slot_of_bank_2_is_still_used_then_nothing():
    """bank 1 full + bank 2 flagged 1..206: the deposit lands at bank 2 entry 207; repeat -> refuse."""
    ok, why = lands_exactly(first_free(2, PER_BANK), 2, PER_BANK, via_client=True)
    assert ok, why


# ── (d) referenced but unflagged: skipped, whichever copy refers ─────────────

@pytest.mark.parametrize("r", [1, 167, 196, 207])
def test_an_unflagged_entry_referenced_only_by_the_backup_copy_is_skipped(r):
    d, n = bank_after(r + 1)
    ok, why = lands_exactly(referenced_only("backup", r), d, n, via_client=True)
    assert ok, (r, why)


def module_lands(setup, d, n, boxes_source=None):
    """The boxes module's own insert_mon (no census in front of it) over the same scenario + exact-image check."""
    img = fresh(setup)
    before, entry = img.snap(), entry_for(party()[1])
    e = Env(boxes_source)
    result, why = _pair(e.boxes(img).insert_mon(e.permit(img), 1, e.table(entry)))
    if result is None:
        return False, f"refused: {why}"
    if img.snap() != expected_after(before, d, n, entry):
        return False, "image differs from the expected one"
    return True, "ok"


@pytest.mark.parametrize("r", [1, 167, 196, 207])
def test_an_unflagged_entry_referenced_only_by_the_gameplay_copy_is_skipped_by_the_allocator(r):
    d, n = bank_after(r + 1)
    ok, why = module_lands(referenced_only("gameplay", r), d, n)
    assert ok, (r, why)


def test_the_executor_refuses_a_gameplay_pointer_with_a_clear_flag_before_allocating():
    """PIN: through box_mon the census is complete only when every gameplay pointer is flagged, so a gameplay-only
    unflagged reference never reaches the allocator - the deposit refuses and writes nothing."""
    rig, img, before, mons, ok, why = deposit(referenced_only("gameplay", 1), via_client=True)
    assert not ok and "box census incomplete" in why and "clear WRAM flag" in why, why
    assert img.snap() == before and rig.writes() == [] and rig.count() == 3


# ── (e) flagged orphan: skipped, bytes never reused ──────────────────────────

@pytest.mark.parametrize("r", [1, 168, 207])
def test_a_flagged_unreferenced_orphan_is_never_reused(r):
    d, n = bank_after(r + 1)
    ok, why = lands_exactly(orphan(r), d, n, via_client=True)
    assert ok, (r, why)


# ── (f) full box / memorial box ──────────────────────────────────────────────

def test_a_full_target_box_refuses_box_full_with_zero_writes_at_module_level():
    img = Image()
    fill(img, 1, 1)                                         # box 1: 20 valid mons (bank 1, entries 1..20)
    e = env()
    boxes = e.boxes(img)
    entry = e.table(entry_for(party()[1]))
    before = img.snap()
    for name in ("insert_mon", "stage_entry"):
        result, why = _pair(getattr(boxes, name)(e.permit(img), 1, entry))
        assert result is None and "box full" in why, (name, why)
    assert img.snap() == before


def test_the_memorial_box_is_excluded_by_the_executor_not_the_module():
    """PIN of the current code. polished_boxes.lua plan() accepts box 1..20 (B.NUM_BOXES), so insert_mon into
    box 20 works at module level; the deposit executor (polished_overworld.lua deposit(), `index ~= MEMORIAL`)
    is what keeps ordinary deposits out of it."""
    img = Image()
    e = env()
    boxes = e.boxes(img)
    entry = entry_for(party()[1])
    result, why = _pair(boxes.insert_mon(e.permit(img), MEMORIAL_BOX, e.table(entry)))
    assert result is not None, why
    assert (result.box, result.slot, result.bank, result.entry) == (MEMORIAL_BOX, 1, 1, 1)
    assert img.mem["CartRAM"][box_flat(MEMORIAL_BOX)] == 1 and img.entry(1, 1) == entry


def test_the_deposit_never_uses_the_memorial_box_when_1_to_19_are_full():
    img = seal_save(Image())
    nxt = 1
    for box in range(1, MEMORIAL_BOX):
        nxt = fill(img, box, nxt)
    before = img.snap()
    mons = party()
    rig = Rig(mons, img=img)
    rig.send_command({"cmd": "box_mon", "key": key_of(mons[0])})
    assert [m["reason"] for m in rig.sent("box_mon_failed")] == ["no free box slot"]
    assert img.snap() == before and rig.writes() == [] and rig.count() == 3
    assert not any(before["CartRAM"][box_flat(MEMORIAL_BOX):box_flat(MEMORIAL_BOX) + 0x21])
    assert PER_BOX == 20


# ── (g) red controls: allocator mutations ────────────────────────────────────

SOURCE = BOXES
BOTH_COPIES = 'for _, copy in ipairs({"gameplay", "backup"}) do'
FLAG_TEST = "if not referenced[bank][i] and not flagged(bank, i) then"
SCAN_FROM_1 = "for i = 1, B.ENTRIES_PER_BANK do\n                if not referenced"
BANK_LOOP = "for bank = 1, 2 do"
BANKS_BIT = "bytes = {d == 2 and (old | bit) or (old & ~bit & 0xFF)}"
SECTION_AB = '{{"A", 1, 167}, {"B", 168, 195}, {"C", 196, 207}}'
FLAG_BYTE = "return wflat[\"wPokeDB\" .. d .. \"UsedEntries\"] + ((e - 1) >> 3) end"

MUTANTS = {
    "ignore the backup copy": (BOTH_COPIES, 'for _, copy in ipairs({"gameplay"}) do', referenced_only("backup", 1), (1, 2)),
    "ignore the flag": (FLAG_TEST, "if not referenced[bank][i] then", orphan(1), (1, 2)),
    "ignore the flag at a section edge": (FLAG_TEST, "if not referenced[bank][i] then", first_free(1, 168), (1, 168)),
    "scan starts at entry 2": (SCAN_FROM_1, SCAN_FROM_1.replace("i = 1,", "i = 2,"), first_free(1, 1), (1, 1)),
    "scan only 206 entries per bank": (SCAN_FROM_1, SCAN_FROM_1.replace("B.ENTRIES_PER_BANK", "B.ENTRIES_PER_BANK - 1"),
                                       first_free(1, PER_BANK), (1, PER_BANK)),
    "bank 2 without the Banks bit": (BANKS_BIT, "bytes = {old & ~bit & 0xFF}", first_free(2, 1), (2, 1)),
    "skip the bank-2 scan": (BANK_LOOP, "for bank = 1, 1 do", first_free(2, 1), (2, 1)),
    "section A ends one early (entry 167 -> B)": (SECTION_AB, '{{"A", 1, 166}, {"B", 167, 195}, {"C", 196, 207}}',
                                                   first_free(1, 167), (1, 167)),
    "section B ends one late (entry 196 -> B)": (SECTION_AB, '{{"A", 1, 167}, {"B", 168, 196}, {"C", 197, 207}}',
                                                  first_free(1, 196), (1, 196)),
    "flag byte off by one (e >> 3)": (FLAG_BYTE, FLAG_BYTE.replace("((e - 1) >> 3)", "(e >> 3)"), first_free(1, 8), (1, 8)),
}


@pytest.mark.parametrize("name", list(MUTANTS))
def test_red_control_allocator_mutation(name):
    original, mutant, setup, (d, n) = MUTANTS[name]
    assert SOURCE.count(original) == 1, name
    assert mutant != original
    ok, why = lands_exactly(setup, d, n)                       # the real module over the same scenario: lands
    assert ok, (name, "unmutated", why)
    ok, why = lands_exactly(setup, d, n, SOURCE.replace(original, mutant))
    assert not ok, f"{name}: the scenario does not catch this mutation"


def test_red_control_allocator_ignores_the_gameplay_copy():
    original, mutant = BOTH_COPIES, 'for _, copy in ipairs({"backup"}) do'
    assert SOURCE.count(original) == 1
    setup = referenced_only("gameplay", 1)
    assert module_lands(setup, 1, 2)[0]
    assert not module_lands(setup, 1, 2, SOURCE.replace(original, mutant))[0]


def test_red_control_exhaustion_must_refuse_not_clear_a_flag():
    """A mutant that 'frees' a flagged entry when none is left would land; the real module refuses (c)."""
    original = 'if not d then refuse("no free pokedb entry: native save required") end'
    assert SOURCE.count(original) == 1
    mutant = SOURCE.replace(original, "if not d then d, entry = 1, 1 end")

    def setup(img):
        flag_all(img, 1)
        flag_all(img, 2)
    rig, img, before, mons, ok, why = deposit(setup, mutant)
    # the control: this scenario can fail. publish_entry's own "no longer free" check refuses the publish, but the
    # mutant's stage_entry has already overwritten the flagged entry's bytes: that is the damage the refusal prevents
    assert not ok and "no longer free" in why and img.snap() != before
    rig, img, before, mons, ok, why = deposit(setup)
    assert not ok and "no free pokedb entry" in why and img.snap() == before


def test_the_module_level_helpers_agree_with_the_composed_deposit():
    """plan() is shared by insert_mon / stage_entry+publish_entry: the same edge lands at the same entry."""
    e = Env()
    for n in (167, 168, 196):
        img = fresh(first_free(1, n))
        boxes = e.boxes(img)
        entry = entry_for(party()[1])
        staged, why = _pair(boxes.stage_entry(e.permit(img), 1, e.table(entry)))
        assert staged is not None and (staged.bank, staged.entry) == (1, n), why
        assert img.entry(1, n) == entry
        placed, why = _pair(boxes.publish_entry(e.permit(img), staged))
        assert placed is not None and (placed.bank, placed.entry) == (1, n), why
