"""lua/gen2/polished_boxes.lua (Polished newbox PC storage, docs/polished/NEWBOX.md) over a synthetic CartRAM +
WRAM image built with server/adapters/polished_codec.py. No emulator: the Lua runs under lupa, `coords` come from
data/polished/polishedcrystal.sym, and the image geometry is NEWBOX.md's own tables (an independent derivation)."""
from __future__ import annotations

import random
import re
from functools import cache
from pathlib import Path

import pytest

from server.adapters import polished_codec as pc

lupa = pytest.importorskip("lupa")

REPO = Path(__file__).resolve().parents[2]
ROOT = str(REPO).replace("\\", "/")
MODULE = REPO / "lua/gen2/polished_boxes.lua"
SYM = REPO / "data/polished/polishedcrystal.sym"
SIZE = 49

# NEWBOX.md §1.1/§1.2/§2 flat geometry, written out by hand (NOT derived from the sym)
SECTION_FLAT = {(1, "A"): 0x4000, (1, "B"): 0x0000, (1, "C"): 0x360C,
                (2, "A"): 0x6000, (2, "B"): 0x0BF1, (2, "C"): 0x3858}
FLAG_FLAT = {1: 0x28B7, 2: 0x28D1}          # WRAM 02:D8B7 / 02:D8D1 -> 0x2000 + (addr - 0xD000)
PAUSED_FLAT, WRITING_BACKUP_FLAT = 0x0EB9, 0x0BE5   # wGameLogicPaused 00:CEB9, sWritingBackup 00:ABE5


def box_flat(n, backup=False):
    return (0x3378 if backup else 0x30E4) + 0x21 * (n - 1)


def entry_flat(d, e):
    if e <= 167:
        return SECTION_FLAT[d, "A"] + SIZE * (e - 1)
    if e <= 195:
        return SECTION_FLAT[d, "B"] + SIZE * (e - 168)
    return SECTION_FLAT[d, "C"] + SIZE * (e - 196)


def _pair(result):
    return result if isinstance(result, tuple) else (result, None)


# ── Lua environment ──────────────────────────────────────────────────────────

class Env:
    """One lupa runtime with the boxes module (optionally a mutated source), polished.lua and the permit."""

    def __init__(self, source=None):
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.B = self.lua.execute(source if source is not None else MODULE.read_text(encoding="utf-8"))
        self.polished = self.lua.eval(f'dofile("{ROOT}/lua/gen2/polished.lua")')
        self.Permit = self.lua.eval(f'dofile("{ROOT}/lua/write_permit.lua")')
        # Python callables reach Lua as userdata; the module and the permit want Lua functions
        self.fn = self.lua.eval("function(f) return function(...) return f(...) end end")
        self._permit = self.lua.eval("""function(Permit, write)
            local open = {bounds=function() return true end, mapped=function() return true end,
                          pointer_stable=function() return true end}
            return Permit.new({write_u8=write, domains={CartRAM=open, WRAM=open},
                lifetime={capture=function() return 1 end, valid=function() return true end},
                provenance=function() return {site="test"} end})
        end""")

    def table(self, values):
        return self.lua.table_from(list(values))

    def boxes(self, image):
        coords = self.lua.table_from({k: self.table(v) for k, v in _coords().items()})
        io = self.lua.table_from({"read_u8": self.fn(image.read)})
        result, why = _pair(self.B.new(coords, io, self.polished.mon_key))
        assert result is not None, why
        return result

    def permit(self, image, armed=True):
        permit = self._permit(self.Permit, self.fn(image.write))
        if armed:
            permit.arm(permit, "test")
        return permit

    def lbytes(self, table, n=SIZE):
        return bytes(table[i] for i in range(1, n + 1))


@cache
def env():
    return Env()


@cache
def _coords():
    rows = re.findall(r"^([0-9a-f]{2}):([0-9a-f]{4}) (\S+)$", SYM.read_text(encoding="utf-8"), re.M)
    sym = {name: (int(bank, 16), int(addr, 16)) for bank, addr, name in rows}
    labels = list(env().B.COORD_LABELS.values())
    return {label: sym[label] for label in labels}


# ── synthetic image ──────────────────────────────────────────────────────────

class Image:
    def __init__(self):
        self.mem = {"CartRAM": bytearray(0x8000), "WRAM": bytearray(0x8000)}

    def read(self, offset, domain):
        return self.mem[domain][offset]

    def write(self, offset, value, domain):
        self.mem[domain][offset] = value

    def snap(self):
        return {d: bytes(m) for d, m in self.mem.items()}

    def flag(self, d, e, on=True):
        at, bit = FLAG_FLAT[d] + (e - 1) // 8, 1 << ((e - 1) % 8)
        self.mem["WRAM"][at] = self.mem["WRAM"][at] | bit if on else self.mem["WRAM"][at] & ~bit

    def point(self, box, slot, d, e, backup=False):
        rec, cart = box_flat(box, backup), self.mem["CartRAM"]
        cart[rec + slot - 1] = e
        at, bit = rec + 0x14 + (slot - 1) // 8, 1 << ((slot - 1) % 8)
        cart[at] = cart[at] | bit if d == 2 else cart[at] & ~bit

    def put(self, d, e, entry):
        self.mem["CartRAM"][entry_flat(d, e):entry_flat(d, e) + SIZE] = entry

    def entry(self, d, e):
        return bytes(self.mem["CartRAM"][entry_flat(d, e):entry_flat(d, e) + SIZE])

    def plant(self, box, slot, d, e, entry, flag=True, gameplay=True, backup=True):
        self.put(d, e, entry)
        if gameplay:
            self.point(box, slot, d, e)
        if backup:
            self.point(box, slot, d, e, backup=True)
        if flag:
            self.flag(d, e)


def random_entry(rng):
    raw = bytearray(rng.randrange(256) for _ in range(SIZE))
    species = rng.randint(1, 0x1FF)
    raw[0], raw[21] = species & 0xFF, (raw[21] & 0xDF) | ((species >> 8) & 1) << 5
    raw[28] = rng.randint(1, 100)
    for i in range(32, SIZE):
        raw[i] &= 0x7F
    return pc.seal(bytes(raw))


def random_party_blob(rng):
    blob = bytearray(rng.randrange(256) for _ in range(pc.BLOB_SIZE))
    species = rng.randint(1, 0x1FF)
    blob[0], blob[21] = species & 0xFF, (blob[21] & 0xDF) | ((species >> 8) & 1) << 5
    blob[31] = rng.randint(1, 100)
    return bytes(blob)


def codec_key(entry):
    return pc.key(pc.decode_savemon(entry, name_decoder=None))


def scenario(seed=7, full_memorial=True):
    """box 1: (1,1) | hole | (2,1) | (1,170) B | (2,200) C ; box 2: (1,5) unflagged | (1,2) BAD EGG |
    (1,196) C | (2,168) B ; backup-only box 3: (1,3) flagged, (1,6) unflagged ; (1,4) flagged, unreferenced ;
    box 20: bank 2 entries 10..29 (slot 7 left empty unless full_memorial)."""
    rng, img, planted = random.Random(seed), Image(), {}

    def mon(box, slot, d, e, **kw):
        entry = random_entry(rng)
        img.plant(box, slot, d, e, entry, **kw)
        if kw.get("gameplay", True) and kw.get("flag", True):
            planted[box, slot] = entry
        return entry

    for slot, (d, e) in {1: (1, 1), 3: (2, 1), 4: (1, 170), 5: (2, 200)}.items():
        mon(1, slot, d, e)
    mon(2, 1, 1, 5, flag=False)
    bad = bytearray(mon(2, 2, 1, 2))
    bad[5] ^= 0x01                                   # one data bit: the game shows a Bad Egg
    img.put(1, 2, bytes(bad))
    del planted[2, 2]
    mon(2, 3, 1, 196)
    mon(2, 4, 2, 168)
    mon(3, 1, 1, 3, gameplay=False)
    mon(3, 2, 1, 6, gameplay=False, flag=False)
    img.put(1, 4, random_entry(rng))
    img.flag(1, 4)
    for slot in range(1, 21):
        if full_memorial or slot != 7:
            mon(20, slot, 2, 9 + slot)
    return img, planted


def diff(before, after):
    return {(d, i) for d in before for i, (a, b) in enumerate(zip(before[d], after[d], strict=True)) if a != b}


# ── checksum / entry building ────────────────────────────────────────────────

def check_seal(e):
    rng = random.Random(1)
    vector = bytearray(SIZE)
    vector[0], vector[28] = 1, 5
    vector[32:] = pc.encode_name_bytes(bytes([0x80] + [0x53] * 9 + [0x81] + [0x53] * 6))
    assert e.B.checksum(e.table(vector)) == 0x32D1
    assert e.lbytes(e.B.seal(e.table(vector)))[32:].hex(" ").upper() == "00 7B FB FB 7B 7B FB 7B FB FB 01 FB 7B 7B 7B FB 7B"
    for _ in range(250):
        raw = bytes(rng.randrange(256) for _ in range(SIZE))
        t = e.table(raw)
        assert e.B.checksum(t) == pc.checksum(raw)
        sealed = e.lbytes(e.B.seal(t))
        assert sealed == pc.seal(raw)
        assert e.B.verify(e.table(sealed)) is True and pc.verify(sealed)
        assert e.B.verify(t) == pc.verify(raw)


def test_lua_seal_matches_python_seal():
    check_seal(env())


def test_entry_from_party_matches_codec():
    e, rng = env(), random.Random(2)
    for _ in range(200):
        blob = random_party_blob(rng)
        want = pc.party_to_savemon(pc.decode_party_blob(blob, name_decoder=None))
        assert e.lbytes(e.B.entry_from_party(e.table(blob))) == want


def test_coords_from_the_sym_are_newbox_geometry():
    c = _coords()
    flat = {k: b * 0x2000 + a - 0xA000 for k, (b, a) in c.items() if 0xA000 <= a < 0xC000}
    for n in range(1, 21):
        assert flat[f"sNewBox{n}"] == box_flat(n) and flat[f"sBackupNewBox{n}"] == box_flat(n, True)
    for (d, s), want in SECTION_FLAT.items():
        assert flat[f"sBoxMons{d}{s}"] == want
    assert c["wPokeDB1UsedEntries"] == (2, 0xD8B7) and c["wPokeDB2UsedEntries"] == (2, 0xD8D1)
    assert c["wGameLogicPaused"] == (0, 0xCEB9) and flat["sWritingBackup"] == WRITING_BACKUP_FLAT


def test_bad_coords_refused():
    e = env()
    for label, row in (("sNewBox7", (1, 0xB0E5)), ("sBoxMons1A", (2, 0xB000)), ("wPokeDB2UsedEntries", (0, 0xD8D1))):
        coords = dict(_coords(), **{label: row})
        lc = e.lua.table_from({k: e.table(v) for k, v in coords.items()})
        result, why = _pair(e.B.new(lc, e.lua.table_from({"read_u8": e.fn(Image().read)}), e.polished.mon_key))
        assert result is None and label in why, (label, why)


# ── reads ────────────────────────────────────────────────────────────────────

def test_enumeration_returns_exactly_the_planted_mons():
    img, planted = scenario()
    boxes = env().boxes(img)
    snap, why = _pair(boxes.read_boxes())
    assert snap is not None, why
    got = {(m.box, m.slot): m for m in snap.mons.values()}
    assert set(got) == set(planted) and len(planted) == 26
    for where, entry in planted.items():
        m, want = got[where], pc.decode_savemon(entry, name_decoder=None)
        assert m.key == codec_key(entry)
        for field in ("species_id", "form", "ot_id", "level", "dv_bytes", "nickname_raw_hex", "ot_raw_hex", "raw_hex"):
            assert m[field] == want[field], field
    assert [(b.box, b.slot) for b in snap.bad_eggs.values()] == [(2, 2)]
    assert snap.bad_eggs[1].bad_egg and snap.bad_eggs[1].key is None
    assert [(u.box, u.slot) for u in snap.unflagged.values()] == [(2, 1)]
    assert [m.slot for m in snap.boxes[1].mons.values()] == [1, 3, 4, 5]          # the hole stays a hole
    assert snap.complete and snap.generation == 1 and boxes.read_boxes().generation == 2
    backup = boxes.read_boxes("backup")
    assert {(m.box, m.slot) for m in backup.mons.values()} == set(planted) | {(3, 1)} and backup.generation is None


def test_corrupt_pointer_makes_the_census_incomplete():
    img, _ = scenario()
    img.mem["CartRAM"][box_flat(4)] = 208
    boxes = env().boxes(img)
    snap = boxes.read_boxes()
    assert not snap.complete and snap.generation is None and snap.invalid[1].reason == "corrupt pointer"


# ── writes ───────────────────────────────────────────────────────────────────

def test_move_to_memorial_changes_only_the_two_pointer_records():
    e = env()
    img, planted = scenario(full_memorial=False)
    boxes, before = e.boxes(img), img.snap()
    result, why = _pair(boxes.move_to_memorial(e.permit(img), 1, 3))         # (2,1): bank 2
    assert result is not None, why
    assert (result.box, result.slot, result.bank, result.entry) == (20, 7, 2, 1)
    assert diff(before, img.snap()) == {("CartRAM", box_flat(20) + 6), ("CartRAM", box_flat(20) + 0x14),
                                        ("CartRAM", box_flat(1) + 2)}
    snap = boxes.read_boxes()
    got = {(m.box, m.slot): m.key for m in snap.mons.values()}
    assert got[20, 7] == codec_key(planted[1, 3]) and (1, 3) not in got and len(got) == len(planted)


def test_memorial_full_and_bad_paths_refuse_without_writing():
    e = env()
    img, _ = scenario()
    boxes, before = e.boxes(img), img.snap()
    for args, reason in (((1, 1), "memorial box full"), ((1, 2), "empty slot"), ((2, 1), "unflagged"),
                         ((20, 1), "source box"), ((1, 21), "slot outside")):
        result, why = _pair(boxes.move_to_memorial(e.permit(img), *args))
        assert result is None and reason in why, (args, why)
    assert img.snap() == before


def check_insert(e):
    img, _ = scenario(seed=11)
    boxes, rng = e.boxes(img), random.Random(3)
    entry = random_entry(rng)
    before = img.snap()
    result, why = _pair(boxes.insert_mon(e.permit(img), 1, e.table(entry)))
    assert result is not None, why
    # (1,5) is referenced by gameplay, (1,6) only by backup: both skipped although their flags are clear
    assert (result.box, result.slot, result.bank, result.entry) == (1, 2, 1, 7)
    allowed = {("CartRAM", entry_flat(1, 7) + i) for i in range(SIZE)}
    allowed |= {("WRAM", FLAG_FLAT[1]), ("CartRAM", box_flat(1) + 1), ("CartRAM", box_flat(1) + 0x14)}
    changed = diff(before, img.snap())
    assert changed <= allowed and {("WRAM", FLAG_FLAT[1]), ("CartRAM", box_flat(1) + 1)} <= changed
    assert img.entry(1, 7) == entry and pc.verify(img.entry(1, 7))
    assert img.mem["WRAM"][FLAG_FLAT[1]] >> 6 & 1 == 1
    assert result.key == codec_key(entry)
    # a party transfer blob: built + sealed in Lua, then verified by the PYTHON verify()
    blob = random_party_blob(rng)
    before = img.snap()
    result, why = _pair(boxes.insert_mon(e.permit(img), 1, e.table(blob)))
    assert result is not None, why
    assert (result.slot, result.bank, result.entry) == (6, 1, 8)
    want = pc.party_to_savemon(pc.decode_party_blob(blob, name_decoder=None))
    assert img.entry(1, 8) == want and pc.verify(img.entry(1, 8))
    changed = diff(before, img.snap())
    assert changed <= {("CartRAM", entry_flat(1, 8) + i) for i in range(SIZE)} | {
        ("WRAM", FLAG_FLAT[1]), ("CartRAM", box_flat(1) + 5), ("CartRAM", box_flat(1) + 0x14)}
    assert img.mem["WRAM"][FLAG_FLAT[1]] >> 7 & 1 == 1
    got = {(m.box, m.slot): m.key for m in boxes.read_boxes().mons.values()}
    assert got[1, 2] == codec_key(entry) and got[1, 6] == codec_key(want)


def test_insert_mon_changes_only_entry_flag_and_pointer():
    check_insert(env())


def test_insert_refusals_write_nothing():
    e = env()
    img, planted = scenario()
    boxes = e.boxes(img)
    sealed = random_entry(random.Random(4))
    unsealed = bytearray(sealed)
    unsealed[40] ^= 0x80
    before = img.snap()
    for box, payload, reason in ((20, sealed, "box full"), (1, bytes(unsealed), "checksum mismatch"),
                                 (1, sealed[:48], "49-byte entry"), (21, sealed, "box outside")):
        result, why = _pair(boxes.insert_mon(e.permit(img), box, e.table(payload)))
        assert result is None and reason in why, (box, why)
    assert img.snap() == before
    for d in (1, 2):                                  # every flag set: no free entry until a native save
        img.mem["WRAM"][FLAG_FLAT[d]:FLAG_FLAT[d] + 26] = b"\xff" * 26
    before = img.snap()
    result, why = _pair(boxes.insert_mon(e.permit(img), 1, e.table(sealed)))
    assert result is None and "native save required" in why and img.snap() == before


def test_bad_egg_is_untouched_by_every_write_path():
    e = env()
    img, _ = scenario(full_memorial=False)
    boxes = e.boxes(img)
    bad, rec = img.entry(1, 2), box_flat(2)
    pointer = (img.mem["CartRAM"][rec + 1], img.mem["CartRAM"][rec + 0x14])
    result, why = _pair(boxes.move_to_memorial(e.permit(img), 2, 2))
    assert result is None and "bad egg" in why
    result, why = _pair(boxes.insert_mon(e.permit(img), 4, e.table(bad)))
    assert result is None and "checksum mismatch" in why
    rng = random.Random(5)
    for _ in range(3):
        assert _pair(boxes.insert_mon(e.permit(img), 2, e.table(random_entry(rng))))[0] is not None
    assert _pair(boxes.move_to_memorial(e.permit(img), 2, 3))[0] is not None
    assert img.entry(1, 2) == bad and (img.mem["CartRAM"][rec + 1], img.mem["CartRAM"][rec + 0x14] & 2) == (
        pointer[0], pointer[1] & 2)
    assert [(b.box, b.slot) for b in boxes.read_boxes().bad_eggs.values()] == [(2, 2)]


def test_writes_refuse_without_an_armed_gate():
    e = env()
    img, _ = scenario(full_memorial=False)
    boxes, entry, before = e.boxes(img), e.table(random_entry(random.Random(6))), img.snap()
    for permit in (None, e.permit(img, armed=False), e.lua.table_from({"armed": "x"})):
        for result, why in (_pair(boxes.insert_mon(permit, 1, entry)), _pair(boxes.move_to_memorial(permit, 1, 1))):
            assert result is None and "no armed write window" in why
    img.mem["WRAM"][PAUSED_FLAT] = 1
    assert "game logic paused" in _pair(boxes.insert_mon(e.permit(img), 1, entry))[1]
    img.mem["WRAM"][PAUSED_FLAT], img.mem["CartRAM"][WRITING_BACKUP_FLAT] = 0, 1
    assert "backup save in progress" in _pair(boxes.move_to_memorial(e.permit(img), 1, 1))[1]
    img.mem["CartRAM"][WRITING_BACKUP_FLAT] = 0
    assert img.snap() == before


# ── red controls: each mutant must fail the check that guards it ─────────────

FLAG_SPAN = "{domain = WRAM, addr = fb, bytes = {rd(WRAM, fb) | (1 << ((entry - 1) & 7))}},"
SEED = "local sum = 127"


@pytest.mark.parametrize(("original", "mutant", "check"), [
    (FLAG_SPAN, "", check_insert),             # skip the flag set
    (SEED, "local sum = 128", check_seal),      # wrong checksum seed
])
def test_red_control_mutants(original, mutant, check):
    source = MODULE.read_text(encoding="utf-8")
    assert source.count(original) == 1
    with pytest.raises(AssertionError):
        check(Env(source.replace(original, mutant)))
