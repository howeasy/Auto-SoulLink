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

import random
from collections.abc import Callable
from types import SimpleNamespace
from typing import NamedTuple

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
    live_mon,
    party,
    plant,
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


def fresh(setup, bit=1, junk_after=True, slot=SLOT):
    """A sealed save image with `setup(img)` applied. The target slot's Banks bit is then forced to `bit` (an empty
    slot's old bank bit is junk, §1.1: 1 must be CLEARED by a bank-1 landing, 0 must be SET by a bank-2 landing) and,
    with junk_after, the bits of the EMPTY slots after it in the same Banks byte are set (a landing must change
    only its own bit). Occupied slots' bits are left as `setup` made them."""
    img = seal_save(Image())
    setup(img)
    at, k = box_flat(1) + 0x14 + (slot - 1) // 8, (slot - 1) % 8
    value = (img.mem["CartRAM"][at] & ~(1 << k) & 0xFF) | (bit << k)
    if junk_after:                                       # only EMPTY slots' bits: an occupied slot's bit is its bank
        for j in range(k + 1, 8):
            if (slot - 1) // 8 * 8 + j < 20 and img.mem["CartRAM"][box_flat(1) + (slot - 1) // 8 * 8 + j] == 0:
                value |= 1 << j
    img.mem["CartRAM"][at] = value
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


def deposit(setup, boxes_source=None, via_client=False, **fresh_kw):
    """Deposit party slot 1 over the image `setup` builds. -> (rig, img, before, mons, ok, reason).
    via_client: the composed client's box_mon command; otherwise the (possibly mutated) boxes module through
    the real overworld deposit()."""
    mons = party()
    img = fresh(setup, **fresh_kw)
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


def landed(img, slot=SLOT):
    """(pokedb bank, entry) the gameplay record of box 1 `slot` points at, or None when the slot is empty."""
    cart, rec = img.mem["CartRAM"], box_flat(1)
    entry = cart[rec + slot - 1]
    return (1 + ((cart[rec + 0x14 + (slot - 1) // 8] >> ((slot - 1) % 8)) & 1), entry) if entry else None


def named_diff(actual, expected, d, n, slot):
    """Which parts of the image differ from the expected one, by name."""
    rec, names = box_flat(1), set()
    for domain in actual:
        for i, (a, b) in enumerate(zip(actual[domain], expected[domain], strict=True)):
            if a == b:
                continue
            if domain == "WRAM" and FLAG_FLAT[d] <= i < FLAG_FLAT[d] + 26:
                names.add("allocation flag")
            elif domain == "WRAM":
                names.add(f"stray WRAM[{i:#x}]")
            elif i == rec + slot - 1:
                names.add("Entries pointer")
            elif i == rec + 0x14 + (slot - 1) // 8:
                names.add("Banks byte")
            elif entry_flat(d, n) <= i < entry_flat(d, n) + SECTION_SIZE:
                names.add("entry bytes at the expected address")
            else:
                names.add(f"stray CartRAM[{i:#x}]")
    return sorted(names)


def run(setup, boxes_source=None, route="mutant", **fresh_kw):
    """One deposit. route: "client" (composed box_mon command, real module), "mutant" (real overworld deposit()
    over the given boxes source) or "module" (the boxes module's own insert_mon, no census in front of it)."""
    slot = fresh_kw.get("slot", SLOT)
    if route == "module":
        img = fresh(setup, **fresh_kw)
        before, entry = img.snap(), entry_for(party()[1])
        e = Env(boxes_source)
        result, why = _pair(e.boxes(img).insert_mon(e.permit(img), 1, e.table(entry)))
        ok, why = result is not None, why
    else:
        rig, img, before, mons, ok, why = deposit(setup, boxes_source, route == "client", **fresh_kw)
        entry = entry_for(mons[1])
    return SimpleNamespace(ok=ok, why=why, img=img, before=before, entry=entry, slot=slot)


def verdict(r, d, n):
    """(True, "ok") only when the deposit succeeded and the WHOLE image equals the independently built expected
    one; otherwise the specific property that failed."""
    if not r.ok:
        return False, f"refused: {r.why}"
    if landed(r.img, r.slot) != (d, n):
        got = landed(r.img, r.slot)
        return False, f"landed at bank {got[0]} entry {got[1]}, expected bank {d} entry {n}" if got else "landed nowhere"
    at = bytes(r.img.mem["CartRAM"][entry_flat(d, n):entry_flat(d, n) + SECTION_SIZE])
    if at != r.entry or not pc.verify(at):
        return False, "image differs: entry bytes absent at the expected address"
    after = r.img.snap()
    want = expected_after(r.before, d, n, r.entry, slot=r.slot)
    if after != want:
        return False, "image differs from the expected one at: " + ", ".join(named_diff(after, want, d, n, r.slot))
    return True, "ok"


def lands_exactly(setup, d, n, boxes_source=None, via_client=False, **fresh_kw):
    """True when the deposit succeeded AND the whole image equals the independently built expected image."""
    r = run(setup, boxes_source, "client" if via_client and boxes_source is None else "mutant", **fresh_kw)
    return verdict(r, d, n)


def module_lands(setup, d, n, boxes_source=None, **fresh_kw):
    return verdict(run(setup, boxes_source, "module", **fresh_kw), d, n)


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


@pytest.mark.parametrize("bit", [0, 1])
@pytest.mark.parametrize("n", BANK2_EDGES)
def test_bank2_edges_land_exactly_with_the_banks_bit_set(n, bit):
    """(b) with n == 1: bank 1 completely flagged -> bank 2 entry 1, Banks bit SET whether the empty slot's old bit
    was 0 or 1 (a mutant that leaves the bit as it was passes only the bit == 1 half), neighbours untouched."""
    ok, why = lands_exactly(first_free(2, n), 2, n, via_client=True, bit=bit)
    assert ok, (n, bit, why)


def test_the_rollover_reads_back_through_the_census_as_bank_2():
    rig, img, before, mons, ok, why = deposit(first_free(2, 1), via_client=True, bit=0)
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


def test_one_entry_left_in_the_last_slot_of_bank_2_is_used_then_the_next_deposit_refuses():
    """bank 1 full + bank 2 flagged 1..206: the deposit lands at bank 2 entry 207; a SECOND deposit on the same rig
    refuses 'native save required', changes nothing and issues no write."""
    rig, img, before, mons, ok, why = deposit(first_free(2, PER_BANK), via_client=True, bit=0)
    assert ok, why
    r = SimpleNamespace(ok=ok, why=why, img=img, before=before, entry=entry_for(mons[1]), slot=SLOT)
    assert verdict(r, 2, PER_BANK) == (True, "ok")
    after_first, writes_first = img.snap(), len(rig.writes())
    rig.send_command({"cmd": "box_mon", "key": key_of(mons[2])})
    reasons = [m["reason"] for m in rig.sent("box_mon_failed")]
    assert len(reasons) == 1 and "no free pokedb entry: native save required" in reasons[0], reasons
    assert img.snap() == after_first and len(rig.writes()) == writes_first and rig.count() == 2


# ── a partially occupied target box: the first free slot is not slot 1 ──────

def occupied(slots, d):
    """Box 1 slots `slots` hold valid mons at pokedb bank d entries 1..len (flagged, both copies); a bank-2 run has
    bank 1 fully flagged. The next deposit lands at entry len + 1 in the first slot NOT in `slots`."""
    def setup(img):
        if d == 2:
            flag_all(img, 1)
        for i, slot in enumerate(slots, start=1):
            plant(img, 1, slot, d, i, entry_for(live_mon(random.Random(i), 30 + i)))
    return setup


PARTIAL = [([1, 2, 3, 4, 5], 6), ([1, 2, 3, 4, 5, 6, 7, 8], 9), ([1, 2, 4, 5], 3), (list(range(1, 20)), 20)]


@pytest.mark.parametrize("bit", [0, 1])
@pytest.mark.parametrize("d", [1, 2])
@pytest.mark.parametrize(("slots", "slot"), PARTIAL)
def test_the_first_free_slot_is_used_with_its_own_banks_bit(slots, slot, d, bit):
    """Slot 9 is bit 0 of the SECOND Banks byte, slot 20 bit 3 of the third; the hole case lands in slot 3."""
    ok, why = lands_exactly(occupied(slots, d), d, len(slots) + 1, via_client=True, bit=bit, slot=slot)
    assert ok, (slots, slot, d, bit, why)


# ── (d) referenced but unflagged: skipped, whichever copy refers ─────────────

@pytest.mark.parametrize("r", [1, 167, 196, 207])
def test_an_unflagged_entry_referenced_only_by_the_backup_copy_is_skipped(r):
    d, n = bank_after(r + 1)
    ok, why = lands_exactly(referenced_only("backup", r), d, n, via_client=True)
    assert ok, (r, why)


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
FREE_SLOT = "for slot = 1, B.MONS_PER_BOX do if rd(CART, rec + slot - 1) == 0 then return slot end end"
FLAG_BYTE = "return wflat[\"wPokeDB\" .. d .. \"UsedEntries\"] + ((e - 1) >> 3) end"

class Mut(NamedTuple):
    original: str
    mutant: str
    setup: Callable
    at: tuple               # the (bank, entry) the real module lands at
    expect: str             # the SPECIFIC failure the mutation must produce (a substring of verdict()'s reason)
    kw: dict = {}
    route: str = "mutant"
    extra: Callable | None = None   # a further property of the damaged image


def _overwrote(d, e):
    return lambda r: r.img.entry(d, e) == r.entry


MUTANTS = {
    # lands at the backup-referenced entry 1 instead of skipping it
    "ignore the backup copy": Mut(BOTH_COPIES, 'for _, copy in ipairs({"gameplay"}) do', referenced_only("backup", 1),
                                  (1, 2), "landed at bank 1 entry 1"),
    # lands at the gameplay-referenced (unflagged) entry 1 (insert_mon: no census in front of it)
    "ignore the gameplay copy": Mut(BOTH_COPIES, 'for _, copy in ipairs({"backup"}) do', referenced_only("gameplay", 1),
                                    (1, 2), "landed at bank 1 entry 1", route="module"),
    # picks the flagged orphan; publish_entry refuses (no longer free), but stage_entry already overwrote the orphan
    "ignore the flag": Mut(FLAG_TEST, "if not referenced[bank][i] then", orphan(1), (1, 2),
                           "staged entry is no longer free", extra=_overwrote(1, 1)),
    "ignore the flag at a section edge": Mut(FLAG_TEST, "if not referenced[bank][i] then", first_free(1, 168), (1, 168),
                                             "staged entry is no longer free", extra=_overwrote(1, 1)),
    "scan starts at entry 2": Mut(SCAN_FROM_1, SCAN_FROM_1.replace("i = 1,", "i = 2,"), first_free(1, 1), (1, 1),
                                  "landed at bank 1 entry 2"),
    # entry 207 is never considered, so bank 1 looks exhausted and the deposit rolls to bank 2 entry 1
    "scan only 206 entries per bank": Mut(SCAN_FROM_1, SCAN_FROM_1.replace("B.ENTRIES_PER_BANK", "B.ENTRIES_PER_BANK - 1"),
                                          first_free(1, PER_BANK), (1, PER_BANK), "landed at bank 2 entry 1"),
    # initial bit 1: the span CLEARS it, so the pointer reads bank 1 (a zeroed entry) -> the deposit read-back refuses
    "bank 2 clears the Banks bit": Mut(BANKS_BIT, "bytes = {old & ~bit & 0xFF}", first_free(2, 1), (2, 1),
                                       "deposit read-back refused: entry checksum fails"),
    # initial bit 0: leaving the bit as it was is only visible when it started clear (bit 1 would pass: see below)
    "bank 2 leaves the Banks bit as it was": Mut(BANKS_BIT, "bytes = {d == 2 and old or (old & ~bit & 0xFF)}",
                                                 first_free(2, 1), (2, 1),
                                                 "deposit read-back refused: entry checksum fails", kw={"bit": 0}),
    "skip the bank-2 scan": Mut(BANK_LOOP, "for bank = 1, 1 do", first_free(2, 1), (2, 1),
                                "no free pokedb entry: native save required"),
    # entry 167 is written at B's start instead of A's end: nothing at the expected address, the census sees a Bad Egg
    "section A ends one early (entry 167 -> B)": Mut(
        SECTION_AB, '{{"A", 1, 166}, {"B", 167, 195}, {"C", 196, 207}}', first_free(1, 167), (1, 167), "Bad Egg",
        extra=lambda r: bytes(r.img.mem["CartRAM"][entry_flat(1, 167):entry_flat(1, 167) + SECTION_SIZE]) != r.entry),
    # entry 196 maps past section B's declared end: the WRITE PERMIT's span guard refuses the batch, zero bytes land
    "section B ends one late (entry 196 -> B)": Mut(
        SECTION_AB, '{{"A", 1, 167}, {"B", 168, 196}, {"C", 197, 207}}', first_free(1, 196), (1, 196),
        "interval outside domain bounds", extra=lambda r: r.img.snap() == r.before),
    # the flag of entry 8 lands in byte 1: the census finds the pointer unflagged, and bit 7 of byte 0 stays clear
    "flag byte off by one (e >> 3)": Mut(
        FLAG_BYTE, FLAG_BYTE.replace("((e - 1) >> 3)", "(e >> 3)"), first_free(1, 8), (1, 8),
        "referenced entry with a clear WRAM flag", extra=lambda r: r.img.mem["WRAM"][FLAG_FLAT[1]] >> 7 & 1 == 0),
    # free_slot finds nothing past slot 1: a box with slots 1..5 taken reads as full
    "free_slot returns 1 or nil": Mut(FREE_SLOT, "if rd(CART, rec) == 0 then return 1 end", occupied([1, 2, 3, 4, 5], 1),
                                      (1, 6), "box full", kw={"slot": 6}),
    # free_slot always answers 1: the occupied slot is detected by publish_entry before any pointer is written
    "free_slot always returns 1": Mut(FREE_SLOT, "do return 1 end", occupied([1, 2, 3, 4, 5], 1), (1, 6),
                                      "staged slot is no longer empty", kw={"slot": 6}),
}


@pytest.mark.parametrize("name", list(MUTANTS))
def test_red_control_allocator_mutation(name):
    m = MUTANTS[name]
    assert SOURCE.count(m.original) == 1, name
    assert m.mutant != m.original
    assert verdict(run(m.setup, None, "module" if m.route == "module" else "client", **m.kw), *m.at) == (True, "ok"), name
    r = run(m.setup, SOURCE.replace(m.original, m.mutant), m.route, **m.kw)
    ok, why = verdict(r, *m.at)
    assert not ok and m.expect in why, f"{name}: expected {m.expect!r}, got {why!r}"
    if m.extra:
        assert m.extra(r), f"{name}: the damaged image does not show the expected state"


def test_the_leaves_the_bit_mutant_passes_when_the_old_bit_was_already_set():
    """WHY the bank-2 landings start from both bit values: with the junk bit pre-set to 1, 'leave it as it was' lands
    exactly like the real module. Only the initial-0 run (above) can tell them apart."""
    m = MUTANTS["bank 2 leaves the Banks bit as it was"]
    source = SOURCE.replace(m.original, m.mutant)
    assert verdict(run(m.setup, source, "mutant", bit=1), *m.at) == (True, "ok")
    assert not verdict(run(m.setup, source, "mutant", bit=0), *m.at)[0]


def test_red_control_forced_reuse_of_a_flagged_entry_overwrites_it_before_publish_refuses():
    """Both banks exhausted and the refusal replaced by 'use entry 1' (a forced reuse of a flagged entry). The real
    module refuses in plan() and the image is untouched. The mutant is caught only by publish_entry's own 'staged
    entry is no longer free' (the flag is set), and by then stage_entry has ALREADY overwritten exactly the 49 bytes
    of bank 1 entry 1: no other byte changed, and those 49 now hold the deposit entry."""
    original = 'if not d then refuse("no free pokedb entry: native save required") end'
    assert SOURCE.count(original) == 1
    mutant = SOURCE.replace(original, "if not d then d, entry = 1, 1 end")

    def setup(img):
        flag_all(img, 1)
        flag_all(img, 2)
    r = run(setup, mutant)
    assert not r.ok and "staged entry is no longer free" in r.why, r.why
    region = range(entry_flat(1, 1), entry_flat(1, 1) + SECTION_SIZE)
    after = r.img.snap()
    changed = [i for i, (a, b) in enumerate(zip(r.before["CartRAM"], after["CartRAM"], strict=True)) if a != b]
    assert changed and set(changed) <= set(region), "only bank 1 entry 1 may differ"
    assert bytes(after["CartRAM"][region.start:region.stop]) == r.entry and after["WRAM"] == r.before["WRAM"]
    real = run(setup, None, "client")
    assert not real.ok and "no free pokedb entry" in real.why and real.img.snap() == real.before


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
