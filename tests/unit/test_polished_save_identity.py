"""tools/polished_live/derive_save.py: a SECOND trainer identity derived from the Polished Crystal duo fixture.

The fixture is a disclosed SYNTH setup fixture (O-33, docs/gen2/REVIEW_RECORD.md:44). The derivative is a SYNTH
identity derivative of it: byte-level facts are proven here, NOT that the native Continue accepts it (live, separate).

Rule of the file: the fixture ABSENT skips with a named reason; PRESENT-but-wrong (hash, layout) FAILS.

RED CONTROLS (each is shown red by the test named, which mutates the builder in-process or corrupts an input):
  main checksum bad / only backup checksum bad   -> test_a_bad_checksum_is_refused
  size / marker / version / phase wrong          -> test_a_wrong_layout_is_refused
  non-empty box (main or backup)                 -> test_a_non_empty_box_is_refused
  name empty / too long / unencodable, bad ID    -> test_a_bad_name_or_id_is_refused
  builder skips the backup copy                  -> test_mutated_builders_are_caught[skip_backup]
  builder overwrites all 11 OT bytes             -> test_mutated_builders_are_caught[overwrite_extra]
  builder forgets one party slot                 -> test_mutated_builders_are_caught[forget_slot]
  builder skips a checksum                       -> test_mutated_builders_are_caught[skip_checksum]
  verifier: undeclared byte / composition / key  -> test_verify_derived_reports_each_departure
Offline admission: the repo's own Lua census (lua/gen2/polished.lua P.census over lua/gen2/polished_boxes.lua)
checks sSaveVersion + sChecksum; test_the_derived_save_is_still_a_census runs it over the derived CartRAM.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from server.adapters import polished_codec as pc

REPO = Path(__file__).resolve().parents[2]
FIXTURE = Path("F:/slink-work/lanes/g2int-live/pol/fixture/polished_overlay_warp.SaveRAM")
FIXTURE_SHA256 = "75c7a5dc30126f746567202cfb39fe583dfa04eb226063560541f6cbd29f36b8"

_spec = importlib.util.spec_from_file_location("derive_save", REPO / "tools/polished_live/derive_save.py")
ds = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ds)

# flat CartRAM facts, written out by hand (NOT read from the module under test)
MAIN_BASE, BACKUP_BASE = 0x2008, 0x1208
MAIN_END, BACKUP_END = 0x2B83, 0x1D83
MAIN_SUM, BACKUP_SUM = 0x2D0D, 0x1F0D
MAIN_MON, BACKUP_MON = 0x2866, 0x1A66
MAIN_OT, BACKUP_OT = 0x2986, 0x1B86
MAIN_NICK, BACKUP_NICK = 0x29C8, 0x1BC8
MAIN_COUNT, BACKUP_COUNT = 0x285E, 0x1A5E
NEWBOX_MAIN, NEWBOX_BACKUP = 0x30E4, 0x3378
OLD_ID, OLD_NAME = 53698, "Aaaaaaa"
NEW_ID, NEW_NAME = 53699, "Bbbbbbb"


@pytest.fixture(scope="module")
def src() -> bytes:
    if not FIXTURE.exists():
        pytest.skip(f"Polished duo fixture absent: {FIXTURE}")
    return FIXTURE.read_bytes()


def cksum(buf, a, b) -> int:
    return sum(buf[a:b]) & 0xFFFF


def reseal(buf: bytearray) -> bytearray:
    buf[MAIN_SUM:MAIN_SUM + 2] = cksum(buf, MAIN_BASE, MAIN_END).to_bytes(2, "little")
    buf[BACKUP_SUM:BACKUP_SUM + 2] = cksum(buf, BACKUP_BASE, BACKUP_END).to_bytes(2, "little")
    return buf


def expected_default_diff() -> set[int]:
    """Hand-built from the brief's offsets: what 'Aaaaaaa'/53698 -> 'Bbbbbbb'/53699 must change, per copy."""
    out = set()
    for base, mon, ot, sums in ((MAIN_BASE, MAIN_MON, MAIN_OT, MAIN_SUM), (BACKUP_BASE, BACKUP_MON, BACKUP_OT, BACKUP_SUM)):
        out.add(base + 1)                                  # player ID low byte (D1 C2 -> D1 C3)
        out.update(range(base + 3, base + 10))             # 7 glyphs A,a.. -> B,b..; the terminator stays
        for i in range(5):
            out.add(mon + 48 * i + 7)                      # OT ID low byte
            out.update(range(ot + 11 * i, ot + 11 * i + 7))
        out.update((sums, sums + 1))                       # 13e4 -> 1414: both bytes
    return out


# ── the fixture's own facts ──────────────────────────────────────────────────

def test_golden_facts_of_the_fixture(src):
    assert hashlib.sha256(src).hexdigest() == FIXTURE_SHA256, "present-but-wrong fixture"
    assert len(src) == 32790
    assert src[0x2007] == 0x61 and src[0x2D0F] == 0x7F and src[0x1207] == 0x61 and src[0x1F0F] == 0x7F
    assert src[0x0BE2:0x0BE4] == b"\x00\x0a" and src[0x0BE5] == 0
    assert cksum(src, MAIN_BASE, MAIN_END) == cksum(src, BACKUP_BASE, BACKUP_END) == 0x13E4
    assert src[MAIN_SUM:MAIN_SUM + 2] == src[BACKUP_SUM:BACKUP_SUM + 2] == b"\xe4\x13"
    for base, count, mon, ot, nick in ((MAIN_BASE, MAIN_COUNT, MAIN_MON, MAIN_OT, MAIN_NICK),
                                       (BACKUP_BASE, BACKUP_COUNT, BACKUP_MON, BACKUP_OT, BACKUP_NICK)):
        assert int.from_bytes(src[base:base + 2], "big") == OLD_ID
        assert src[base + 2] == 1
        assert src[base + 3:base + 14] == bytes.fromhex("80a0a0a0a0a0a053000000")
        assert pc.decode_text(src[base + 3:base + 11]) == OLD_NAME
        assert src[count] == 5
        for i in range(5):
            assert int.from_bytes(src[mon + 48 * i + 6:mon + 48 * i + 8], "big") == OLD_ID
            assert src[ot + 11 * i:ot + 11 * i + 11] == bytes.fromhex("80a0a0a0a0a0a053000000")
            assert src[nick + 11 * i] != 0
        assert src[mon + 48 * 5:mon + 48 * 5 + 48] == bytes(48)           # sixth slot empty
    for base in (NEWBOX_MAIN, NEWBOX_BACKUP):
        assert all(not any(src[base + 33 * b:base + 33 * b + 20]) for b in range(20))   # Entries all empty
    assert src[32768:].hex() == "000000006ac2a3950000000100001228fe0000000100"


# ── the derivation ───────────────────────────────────────────────────────────

def test_the_derivation_changes_exactly_the_declared_offsets(src):
    before = bytes(src)
    out, disclosure = ds.derive_identity(src)
    assert src == before, "the input must not be mutated"
    assert len(out) == len(src) == 32790
    differing = {i for i in range(len(src)) if src[i] != out[i]}
    assert differing == expected_default_diff()
    assert len(differing) == disclosure["differing_bytes"] == 100
    assert out[32768:] == src[32768:]                                # RTC trailer
    assert out[0x0BE2:0x0BE6] == src[0x0BE2:0x0BE6]                  # version + phase
    # both checksums: independently recomputed, valid, and equal to what changed
    assert out[MAIN_SUM:MAIN_SUM + 2] == cksum(out, MAIN_BASE, MAIN_END).to_bytes(2, "little") == b"\x14\x14"
    assert out[BACKUP_SUM:BACKUP_SUM + 2] == cksum(out, BACKUP_BASE, BACKUP_END).to_bytes(2, "little") == b"\x14\x14"
    for at in (MAIN_BASE, BACKUP_BASE):
        assert int.from_bytes(out[at:at + 2], "big") == NEW_ID
        assert pc.decode_text(out[at + 3:at + 11]) == NEW_NAME
        assert out[at + 10:at + 14] == bytes.fromhex("53000000")      # terminator + the allocation's last 3 bytes kept
    for mon, ot, nick in ((MAIN_MON, MAIN_OT, MAIN_NICK), (BACKUP_MON, BACKUP_OT, BACKUP_NICK)):
        for i in range(5):
            assert int.from_bytes(out[mon + 48 * i + 6:mon + 48 * i + 8], "big") == NEW_ID
            assert out[ot + 11 * i:ot + 11 * i + 11] == bytes.fromhex("81a1a1a1a1a1a153000000")
            assert out[ot + 11 * i + 8:ot + 11 * i + 11] == src[ot + 11 * i + 8:ot + 11 * i + 11]    # EXTRA kept
            assert out[nick + 11 * i:nick + 11 * i + 11] == src[nick + 11 * i:nick + 11 * i + 11]
            assert out[mon + 48 * i + 1] == src[mon + 48 * i + 1]                                    # held item kept
    assert ds.verify_derived(src, out) == []


def test_keys_are_disjoint_and_composition_unchanged(src):
    out, _ = ds.derive_identity(src)
    for mon, count in ((MAIN_MON, MAIN_COUNT), (BACKUP_MON, BACKUP_COUNT)):
        old = [pc.decode_party_mon(src[mon + 48 * i:mon + 48 * i + 48]) for i in range(src[count])]
        new = [pc.decode_party_mon(out[mon + 48 * i:mon + 48 * i + 48]) for i in range(out[count])]
        assert {pc.key(m) for m in old}.isdisjoint({pc.key(m) for m in new})
        assert len({pc.key(m) for m in new}) == 5
        for o, n in zip(old, new, strict=True):
            assert (o["species_id"], o["dv_bytes"], o["level"]) == (n["species_id"], n["dv_bytes"], n["level"])
            assert o["ot_id"] == OLD_ID and n["ot_id"] == NEW_ID


def test_the_derivation_is_deterministic(src):
    a, da = ds.derive_identity(src)
    b, db = ds.derive_identity(src)
    assert a == b and da == db
    assert json.loads(json.dumps(da)) == da                          # the disclosure is plain JSON


def test_the_disclosure_lists_what_it_promises(src):
    out, d = ds.derive_identity(src)
    assert d["input_sha256"] == FIXTURE_SHA256 and d["output_sha256"] == hashlib.sha256(out).hexdigest()
    assert d["revision"] == ds.REVISION and d["arguments"] == {"name": NEW_NAME, "player_id": NEW_ID}
    assert d["statement"] == ("SYNTH identity derivative of an existing SYNTH setup fixture (O-33); not independently "
                              "played; native Continue/save/reload evaluated separately")
    assert d["checksums"] == {"main": {"offset": MAIN_SUM, "offset_hex": "0x2D0D", "old": "13e4", "new": "1414"},
                              "backup": {"offset": BACKUP_SUM, "offset_hex": "0x1F0D", "old": "13e4", "new": "1414"}}
    kinds = [f["field"] for f in d["changed_fields"]]
    assert kinds.count("player_id") == kinds.count("player_name") == 2
    assert kinds.count("party_ot_id") == kinds.count("party_ot_name") == 10
    for f in d["changed_fields"]:
        assert src[f["offset"]:f["offset"] + f["length"]].hex() == f["old_hex"]
        assert out[f["offset"]:f["offset"] + f["length"]].hex() == f["new_hex"]
    ot_fields = [f for f in d["changed_fields"] if f["field"] == "party_ot_name"]
    assert {f["preserved_extra_hex"] for f in ot_fields} == {"000000"}


# ── preconditions (each refused BEFORE any change) ───────────────────────────

def corrupt(src, edit, *, seal=True) -> bytes:
    buf = bytearray(src)
    edit(buf)
    if seal:
        reseal(buf)
    return bytes(buf)


def test_a_bad_checksum_is_refused(src):
    main_bad = corrupt(src, lambda b: b.__setitem__(MAIN_SUM, b[MAIN_SUM] ^ 1), seal=False)
    backup_bad = corrupt(src, lambda b: b.__setitem__(BACKUP_SUM + 1, b[BACKUP_SUM + 1] ^ 0x80), seal=False)
    region_bad = corrupt(src, lambda b: b.__setitem__(BACKUP_BASE + 100, b[BACKUP_BASE + 100] ^ 1), seal=False)
    for bad in (main_bad, backup_bad, region_bad):
        with pytest.raises(ds.SaveChecksumError):
            ds.derive_identity(bad)
        with pytest.raises(ds.SaveChecksumError):
            ds.held_item_variant(bad, 0, 1)
    assert "backup checksum" in str(pytest.raises(ds.SaveChecksumError, ds.derive_identity, backup_bad).value)
    ds.derive_identity(src)                                          # the control: the sound fixture passes


@pytest.mark.parametrize("label,edit", [
    ("size_short", None), ("size_long", None),
    ("main_low_marker", lambda b: b.__setitem__(0x2007, 0x60)),
    ("main_high_marker", lambda b: b.__setitem__(0x2D0F, 0x7E)),
    ("backup_low_marker", lambda b: b.__setitem__(0x1207, 0x00)),
    ("backup_high_marker", lambda b: b.__setitem__(0x1F0F, 0x00)),
    ("version", lambda b: b.__setitem__(0x0BE3, 0x0B)),
    ("phase", lambda b: b.__setitem__(0x0BE5, 1)),
    ("party_zero", lambda b: b.__setitem__(MAIN_COUNT, 0)),
    ("party_seven", lambda b: b.__setitem__(BACKUP_COUNT, 7)),
])
def test_a_wrong_layout_is_refused(src, label, edit):
    if label == "size_short":
        bad = src[:-1]
    elif label == "size_long":
        bad = src + b"\x00"
    else:
        bad = corrupt(src, edit)                                     # re-sealed: only the layout fact is wrong
    with pytest.raises(ds.SaveLayoutError):
        ds.derive_identity(bad)
    with pytest.raises(ds.SaveLayoutError):
        ds.held_item_variant(bad, 0, 1)


@pytest.mark.parametrize("at", [NEWBOX_MAIN, NEWBOX_MAIN + 33 * 19 + 19, NEWBOX_BACKUP + 33 * 7 + 3, NEWBOX_BACKUP + 33 * 19 + 19])
def test_a_non_empty_box_is_refused(src, at):
    bad = corrupt(src, lambda b: b.__setitem__(at, 5), seal=False)
    with pytest.raises(ds.SaveBoxesNotEmptyError):
        ds.derive_identity(bad)
    # control: the box NAME bytes (not Entries) are not a mon and never refuse
    ok = corrupt(src, lambda b: b.__setitem__(NEWBOX_MAIN + 0x17, 0x82), seal=False)
    ds.derive_identity(ok)


@pytest.mark.parametrize("name,player_id", [("", 5), ("Bbbbbbbb", 5), ("a" * 40, 5), ("Bb~~", 5), ("B@", 5),
                                            (None, 5), ("Bob", -1), ("Bob", 65536), ("Bob", "7"), ("Bob", True)])
def test_a_bad_name_or_id_is_refused(src, name, player_id):
    with pytest.raises(ds.SaveNameError):
        ds.derive_identity(src, name=name, player_id=player_id)
    out, _ = ds.derive_identity(src, name="Bobby", player_id=1)      # controls: a 5-letter name and ID 1 are fine
    assert pc.decode_text(out[MAIN_BASE + 3:MAIN_BASE + 11]) == "Bobby"
    ds.derive_identity(src, name="Bbbbbbb", player_id=0)             # 7 chars and ID 0 are the boundaries
    with pytest.raises(ds.SaveNameError):
        ds.derive_identity(src, name="Bbbbbbbb")


def test_precondition_errors_are_named_and_share_a_base():
    for cls in (ds.SaveLayoutError, ds.SaveChecksumError, ds.SaveBoxesNotEmptyError, ds.SaveNameError):
        assert issubclass(cls, ds.SaveIdentityError) and issubclass(cls, ValueError)


# ── mutated builders must be caught (RED CONTROLS) ───────────────────────────

def _mut_skip_backup(mp):
    mp.setattr(ds, "COPIES", (ds.MAIN,))


def _mut_overwrite_extra(mp):
    def write(buf, at, name8):
        buf[at:at + ds.NAME_ALLOC] = name8 + b"\x53\x53\x53"         # clobbers the 3 EXTRA (hyper-training) bytes
    mp.setattr(ds, "_write_ot_name", write)


def _mut_forget_slot(mp):
    mp.setattr(ds, "_party_slots", lambda count: range(count - 1))


def _mut_skip_checksum(mp):
    def reseal(buf):
        buf[ds.MAIN.checksum_at:ds.MAIN.checksum_at + 2] = ds.region_sum(buf, ds.MAIN).to_bytes(2, "little")
    mp.setattr(ds, "_reseal", reseal)


@pytest.mark.parametrize("label,mutate,needle", [
    ("skip_backup", _mut_skip_backup, "backup: player ID unchanged"),
    ("overwrite_extra", _mut_overwrite_extra, "OT EXTRA bytes changed"),
    ("forget_slot", _mut_forget_slot, "slot 4: OT id"),
    ("skip_checksum", _mut_skip_checksum, "backup checksum"),
])
def test_mutated_builders_are_caught(src, monkeypatch, label, mutate, needle):
    assert ds.verify_derived(src, ds.derive_identity(src)[0]) == []   # control: the unmutated builder is clean
    mutate(monkeypatch)
    out, _ = ds.derive_identity(src)
    problems = ds.verify_derived(src, out)
    assert problems, f"mutation {label} went undetected"
    assert any(needle in p for p in problems), problems


# ── the verifier itself, one departure at a time (RED CONTROLS) ──────────────

def test_verify_derived_reports_each_departure(src):
    good, _ = ds.derive_identity(src)

    def bad(edit, seal=True):
        return corrupt(good, edit, seal=seal)

    cases = {
        "undeclared nickname byte": (bad(lambda b: b.__setitem__(MAIN_NICK, b[MAIN_NICK] ^ 1)), "undeclared offsets"),
        "undeclared held item": (bad(lambda b: b.__setitem__(MAIN_MON + 1, 0x11)), "undeclared offsets"),
        "nickname changed": (bad(lambda b: b.__setitem__(BACKUP_NICK + 11, 0x80)), "nickname changed"),
        "species changed": (bad(lambda b: b.__setitem__(MAIN_MON, 0x10)), "species_id changed"),
        "level changed": (bad(lambda b: b.__setitem__(MAIN_MON + 31, 77)), "level changed"),
        "dv changed": (bad(lambda b: b.__setitem__(MAIN_MON + 17, b[MAIN_MON + 17] ^ 0x11)), "dv_bytes changed"),
        "bad checksum": (bad(lambda b: b.__setitem__(MAIN_BASE + 1, 0), seal=False), "derived: main checksum"),
        "marker": (bad(lambda b: b.__setitem__(0x2007, 0)), "marker"),
        "trailer": (good[:-1] + b"\x01", "RTC trailer changed"),
        "version": (bad(lambda b: b.__setitem__(0x0BE3, 0x0B)), "sSaveVersion"),
        "backup identity differs": (bad(lambda b: b.__setitem__(BACKUP_BASE + 1, 0x77)), "copies disagree"),
        "ot id differs from player": (bad(lambda b: b.__setitem__(MAIN_MON + 6 + 48 * 2 + 1, 9)), "slot 2: OT id"),
        "party count changed": (bad(lambda b: b.__setitem__(MAIN_COUNT, 4)), "party count changed"),
        "size": (good[:-1], "size"),
    }
    for label, (image, needle) in cases.items():
        problems = ds.verify_derived(src, image)
        assert any(needle in p for p in problems), (label, problems)
    # identity unchanged at all (the original verified against itself): ID, name, OT, keys all report it
    problems = ds.verify_derived(src, src)
    for needle in ("player ID unchanged", "player name not changed", "OT id not changed", "OT name not changed", "keys not disjoint"):
        assert any(needle in p for p in problems), (needle, problems)
    # an ID-only change keeps names: the verifier says the OT name no longer matches/changed
    only_id = bytearray(src)
    for at in (MAIN_BASE, BACKUP_BASE):
        only_id[at + 1] ^= 1
    for mon in (MAIN_MON, BACKUP_MON):
        for i in range(5):
            only_id[mon + 48 * i + 7] ^= 1
    assert any("name not changed" in p for p in ds.verify_derived(src, bytes(reseal(only_id))))


# ── held_item_variant ────────────────────────────────────────────────────────

def test_held_item_variant_changes_exactly_the_item_byte(src):
    base, _ = ds.derive_identity(src)
    before = bytes(base)
    out, d = ds.held_item_variant(base, 2, 0x2B)
    assert base == before
    differing = {i for i in range(len(base)) if base[i] != out[i]}
    old_item = base[MAIN_MON + 48 * 2 + 1]
    assert old_item != 0x2B, "pick an item that differs from what slot 2 holds"
    item_bytes = {MAIN_MON + 48 * 2 + 1, BACKUP_MON + 48 * 2 + 1}
    sum_bytes = {MAIN_SUM, MAIN_SUM + 1, BACKUP_SUM, BACKUP_SUM + 1}
    assert item_bytes <= differing <= item_bytes | sum_bytes
    assert differing - item_bytes == {i for i in sum_bytes if base[i] != out[i]} and len(differing - item_bytes) >= 2
    assert out[MAIN_MON + 48 * 2 + 1] == out[BACKUP_MON + 48 * 2 + 1] == 0x2B
    assert out[MAIN_SUM:MAIN_SUM + 2] == cksum(out, MAIN_BASE, MAIN_END).to_bytes(2, "little")
    assert out[BACKUP_SUM:BACKUP_SUM + 2] == cksum(out, BACKUP_BASE, BACKUP_END).to_bytes(2, "little")
    assert d["statement"] == ds.ITEM_STATEMENT and d["arguments"] == {"slot": 2, "item": 0x2B}
    assert d["differing_bytes"] == len(differing) and d["input_sha256"] == hashlib.sha256(base).hexdigest()
    assert {f["field"] for f in d["changed_fields"]} == {"party_held_item"} and len(d["changed_fields"]) == 2
    assert ds.verify_derived(src, out, item_slots=[2]) == []
    assert any("undeclared offsets" in p for p in ds.verify_derived(src, out)), "an item change must need declaring"
    # applied to the ORIGINAL fixture it works as well, and never by default
    plain, _ = ds.derive_identity(src)
    assert plain[MAIN_MON + 48 * 2 + 1] == src[MAIN_MON + 48 * 2 + 1]


def test_held_item_variant_refuses_bad_arguments(src):
    for slot in (-1, 5, 6, "0", None):
        with pytest.raises(ds.SaveLayoutError):
            ds.held_item_variant(src, slot, 1)
    for item in (-1, 256, "1", None):
        with pytest.raises(ds.SaveLayoutError):
            ds.held_item_variant(src, 0, item)


# ── offline admission by the repo's own reader ───────────────────────────────

def test_the_derived_save_is_still_a_census(src):
    """The Lua census (sSaveVersion + sChecksum + box decode) admits the derivative exactly as it admits the fixture."""
    pytest.importorskip("lupa")
    from tests.unit.test_polished_boxes import Image
    from tests.unit.test_polished_boxes_census import Rig

    def walk(save):
        img = Image()
        img.mem["CartRAM"][:] = save[:32768]
        return Rig(img).walk()

    assert walk(src) == ([], None), "control: the fixture itself is a complete empty census"
    out, _ = ds.derive_identity(src)
    assert walk(out) == ([], None)
    # red control: a derivative with one stale checksum is refused by the same reader
    stale = bytearray(out)
    stale[MAIN_SUM] ^= 1
    boxes, why = walk(bytes(stale))
    assert boxes is None and "checksum" in why


# ── CLI ──────────────────────────────────────────────────────────────────────

def test_cli_writes_refuses_and_forces(src, tmp_path, capsys):
    source = tmp_path / "A.SaveRAM"
    source.write_bytes(src)
    out = tmp_path / "B.SaveRAM"
    assert ds.main(["--src", str(source), "--out", str(out)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["differing_bytes"] == 100 and printed["output_sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert out.read_bytes() == ds.derive_identity(src)[0]
    assert source.read_bytes() == src
    assert ds.main(["--src", str(source), "--out", str(out)]) == 2             # existing --out refused
    assert ds.main(["--src", str(source), "--out", str(source), "--force"]) == 2   # the source is never overwritten
    assert source.read_bytes() == src
    out.write_bytes(b"x")
    assert ds.main(["--src", str(source), "--out", str(out), "--force"]) == 0
    capsys.readouterr()
    assert ds.main(["--src", str(source), "--out", str(tmp_path / "C.SaveRAM"), "--name", "Waytoolongname"]) == 3
    assert not (tmp_path / "C.SaveRAM").exists()
    assert ds.main(["--src", str(source), "--out", str(tmp_path / "D.SaveRAM"), "--item", "1:2B", "--name", "Cccc", "--id", "7"]) == 0
    printed = json.loads(capsys.readouterr().out)
    derived = (tmp_path / "D.SaveRAM").read_bytes()
    assert derived[MAIN_MON + 48 + 1] == derived[BACKUP_MON + 48 + 1] == 0x2B
    assert printed["final_output_sha256"] == hashlib.sha256(derived).hexdigest()
    assert printed["held_item_variants"][0]["arguments"] == {"slot": 1, "item": 0x2B}
    assert printed["final_differing_bytes"] == len({i for i in range(len(src)) if src[i] != derived[i]})
    assert ds.verify_derived(src, derived, item_slots=[1]) == []
