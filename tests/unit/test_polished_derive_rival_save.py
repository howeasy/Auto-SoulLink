"""tools/polished_live/derive_rival_save.py: the Cherrygrove-scene SYNTH derivative of the Polished duo fixture (card B1).

The input is a disclosed SYNTH setup fixture (O-33, docs/gen2/REVIEW_RECORD.md:44) and the output is a SYNTH
derivative of it: byte-level facts are proven here, NOT that the native CONTINUE accepts it and NOT that the walk
reaches the rival (both live, separate). Plan: docs/polished/RIVAL_STAGING.md section 2.

Rule of the file: the fixture ABSENT skips with a named reason; PRESENT-but-wrong (hash) FAILS.

Every expected number below is written out by hand or re-derived from data/polished/polished_slink.sym and the pinned
source; none of it is imported from the module under test.

RED CONTROLS (each is shown red by the test named):
  size / marker / version / phase / party count     -> test_a_wrong_layout_is_refused
  checksum bad in either copy                        -> test_a_bad_checksum_is_refused
  scene already set / not 00 in either copy          -> test_a_scene_that_is_not_zero_is_refused
  starter flag set, rival bit clear, wrong map/pos   -> test_a_wrong_story_precondition_is_refused
  main and backup disagree                           -> test_copies_that_disagree_are_refused
  any other hash than the pin                        -> test_only_the_pinned_source_hash_is_accepted
  verifier: each departure from the 4-byte allowlist -> test_verifier_reports_each_departure
  builder skips a copy / a checksum / touches the footer / writes a wrong value / an extra byte
                                                     -> test_mutated_builders_are_refused
  CLI: out==src, out exists, out in tests/fixtures   -> test_cli_refuses_*
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import random
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FIXTURE_CANDIDATES = (Path("F:/slink-work/lanes/pol-live/fixture/polished_overlay_warp.SaveRAM"),
                      Path("F:/slink-work/lanes/g2int-live/pol/fixture/polished_overlay_warp.SaveRAM"))
FIXTURE_SHA256 = "75c7a5dc30126f746567202cfb39fe583dfa04eb226063560541f6cbd29f36b8"
EXPECTED_SHA256 = "030c62ff898050d81d80dea19677e8520e2f707dae0c35f873d87e79cf7ac1ae"
SRC_ROOT = Path("F:/slink-work/cache/polished/src")

_spec = importlib.util.spec_from_file_location("derive_rival_save", REPO / "tools/polished_live/derive_rival_save.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

# flat SaveRAM facts, written out by hand (NOT read from the module under test). Plan section 2.
SIZE = 32790
SCENE_MAIN, SCENE_BACKUP = 0x2582, 0x1782
SUM_MAIN, SUM_BACKUP = 0x2D0D, 0x1F0D
REGION_MAIN, REGION_BACKUP = (0x2008, 0x2B83), (0x1208, 0x1D83)
FOOTER = 32768
PINNED_DIFF = [0x1782, 0x1F0D, 0x2582, 0x2D0D]
MAP_MAIN, MAP_BACKUP = 0x283C, 0x1A3C          # group 24, map 3, Y 12, X 48
STARTER_MAIN, STARTER_BACKUP = 0x25ED, 0x17ED  # bits 28/29/30 -> mask 0x70
RIVAL_MAIN, RIVAL_BACKUP = 0x26BA, 0x18BA      # EVENT_RIVAL_CHERRYGROVE_CITY = 0x687 -> byte 0xD0, mask 0x80
COUNT_MAIN, COUNT_BACKUP = 0x285E, 0x1A5E
VERSION_AT, PHASE_AT = 0x0BE2, 0x0BE5
MARKERS = ((0x2007, 0x61), (0x1207, 0x61), (0x2D0F, 0x7F), (0x1F0F, 0x7F))


def seal(buf) -> None:
    for (a, b), at in ((REGION_MAIN, SUM_MAIN), (REGION_BACKUP, SUM_BACKUP)):
        buf[at:at + 2] = (sum(buf[a:b]) & 0xFFFF).to_bytes(2, "little")


def synthetic(low_carry=False, seed=7) -> bytearray:
    """A structurally valid 32790-byte image: identical regions, the Route 29 preconditions, scene 0, valid sums."""
    rng = random.Random(seed)
    buf = bytearray(rng.randrange(256) for _ in range(SIZE))
    main = bytearray(rng.randrange(256) for _ in range(REGION_MAIN[1] - REGION_MAIN[0]))
    buf[REGION_MAIN[0]:REGION_MAIN[1]] = main
    buf[REGION_BACKUP[0]:REGION_BACKUP[1]] = main
    for a, v in MARKERS:
        buf[a] = v
    buf[VERSION_AT:VERSION_AT + 2] = b"\x00\x0a"
    buf[PHASE_AT] = 0
    for count_at in (COUNT_MAIN, COUNT_BACKUP):
        buf[count_at] = 5
    for at in (MAP_MAIN, MAP_BACKUP):
        buf[at:at + 4] = bytes((0x18, 0x03, 0x0C, 0x30))
    for at in (STARTER_MAIN, STARTER_BACKUP):
        buf[at] &= 0x8F
    for at in (RIVAL_MAIN, RIVAL_BACKUP):
        buf[at] |= 0x80
    for at in (SCENE_MAIN, SCENE_BACKUP):
        buf[at] = 0
    if low_carry:   # make the (identical) region sums end in 0xFF so +1 carries into the high checksum byte
        pad = REGION_MAIN[0] + 0x700   # a byte nobody above constrains
        buf[REGION_BACKUP[0] + 0x700] = buf[pad] = 0
        buf[pad] = (0xFF - (sum(buf[REGION_MAIN[0]:REGION_MAIN[1]]) & 0xFF)) & 0xFF
        buf[REGION_BACKUP[0] + 0x700] = buf[pad]
    seal(buf)
    return buf


def derive_syn(buf, **kw):
    return M.derive_rival_scene(bytes(buf), pinned=False, **kw)


@pytest.fixture(scope="module")
def fixture_bytes() -> bytes:
    for path in FIXTURE_CANDIDATES:
        if path.exists():
            data = path.read_bytes()
            assert hashlib.sha256(data).hexdigest() == FIXTURE_SHA256, f"{path} is present but is NOT the pinned fixture"
            return data
    pytest.skip(f"Polished warp fixture absent: {[str(p) for p in FIXTURE_CANDIDATES]}")


# ── synthetic images: the happy path and the allowlist ─────────────────────────────────────────

def test_synthetic_image_is_valid_to_begin_with():
    buf = synthetic()
    assert len(buf) == SIZE
    out, _ = derive_syn(buf)
    assert out != bytes(buf)
    assert M.verify_rival_scene(bytes(buf), out) == []


def test_derivation_changes_the_scene_and_the_checksums_only():
    buf = synthetic()
    out, disc = derive_syn(buf)
    diff = [i for i in range(SIZE) if buf[i] != out[i]]
    assert set(diff) >= {SCENE_MAIN, SCENE_BACKUP, SUM_MAIN, SUM_BACKUP}
    assert set(diff) <= {SCENE_MAIN, SCENE_BACKUP, SUM_MAIN, SUM_MAIN + 1, SUM_BACKUP, SUM_BACKUP + 1}
    assert out[SCENE_MAIN] == out[SCENE_BACKUP] == 1
    assert out[FOOTER:] == bytes(buf[FOOTER:])
    for (a, b), at in ((REGION_MAIN, SUM_MAIN), (REGION_BACKUP, SUM_BACKUP)):
        assert int.from_bytes(out[at:at + 2], "little") == sum(out[a:b]) & 0xFFFF
    assert disc["differing_bytes"] == len(diff)


def test_a_carry_into_the_high_checksum_byte_is_resealed_and_allowed():
    buf = synthetic(low_carry=True)
    assert buf[SUM_MAIN] == 0xFF
    out, _ = derive_syn(buf)
    assert out[SUM_MAIN:SUM_MAIN + 2] != buf[SUM_MAIN:SUM_MAIN + 2]
    assert out[SUM_MAIN + 1] == buf[SUM_MAIN + 1] + 1
    assert out[SUM_BACKUP + 1] == buf[SUM_BACKUP + 1] + 1
    assert M.verify_rival_scene(bytes(buf), out) == []


def test_input_is_never_mutated_and_output_is_deterministic():
    buf = synthetic()
    before = bytes(buf)
    first = M.derive_rival_scene(buf, pinned=False)
    second = M.derive_rival_scene(buf, pinned=False)
    assert bytes(buf) == before
    assert first[0] == second[0]
    assert json.dumps(first[1], sort_keys=True) == json.dumps(second[1], sort_keys=True)
    assert isinstance(first[0], bytes)


def test_disclosure_declares_synth_and_every_change():
    buf = synthetic()
    out, disc = derive_syn(buf)
    assert disc["synth"] is True and "SYNTH" in disc["statement"]
    assert disc["input_sha256"] == hashlib.sha256(bytes(buf)).hexdigest()
    assert disc["output_sha256"] == hashlib.sha256(out).hexdigest()
    assert disc["pinned_input"] is False
    scenes = [f for f in disc["changed_fields"] if f["field"] == "cherrygrove_scene"]
    assert sorted((f["copy"], f["offset"], f["old_hex"], f["new_hex"]) for f in scenes) == [
        ("backup", SCENE_BACKUP, "00", "01"), ("main", SCENE_MAIN, "00", "01")]
    sums = {f["copy"]: f for f in disc["changed_fields"] if f["field"] == "checksum"}
    assert sums["main"]["offset"] == SUM_MAIN and sums["backup"]["offset"] == SUM_BACKUP
    assert sums["main"]["new_hex"] == out[SUM_MAIN:SUM_MAIN + 2].hex()
    assert disc["footer"] == {"offset": FOOTER, "length": 22, "preserved": True,
                              "sha256": hashlib.sha256(bytes(buf[FOOTER:])).hexdigest()}
    assert disc["native_acceptance"] == "UNVERIFIED"
    assert disc["differing_offsets"] == sorted(disc["differing_offsets"])
    json.dumps(disc)


# ── refusals, all raised before any change ─────────────────────────────────────────────────────

@pytest.mark.parametrize("mutate", [
    lambda b: bytes(b)[:32768], lambda b: bytes(b)[:-1], lambda b: bytes(b) + b"\x00", lambda b: b"",
    lambda b: b.__setitem__(0x2007, 0x00) or b, lambda b: b.__setitem__(0x1207, 0x00) or b,
    lambda b: b.__setitem__(0x2D0F, 0x00) or b, lambda b: b.__setitem__(0x1F0F, 0x00) or b,
    lambda b: b.__setitem__(VERSION_AT, 0x01) or b, lambda b: b.__setitem__(PHASE_AT, 0x01) or b,
    lambda b: b.__setitem__(COUNT_MAIN, 0) or b, lambda b: b.__setitem__(COUNT_BACKUP, 7) or b,
], ids=["size-32768", "size-32789", "size-32791", "empty", "marker-main-low", "marker-backup-low",
        "marker-main-high", "marker-backup-high", "version", "phase", "count-main-0", "count-backup-7"])
def test_a_wrong_layout_is_refused(mutate):
    buf = synthetic()
    bad = mutate(buf)
    if not isinstance(bad, (bytes, bytearray)) or len(bad) == SIZE:
        seal(bad)   # keep the sums valid so only the layout can be the reason
    with pytest.raises(M.RivalSourceError):
        M.derive_rival_scene(bytes(bad), pinned=False)


def test_non_bytes_input_is_refused():
    with pytest.raises(M.RivalSourceError):
        M.derive_rival_scene("not bytes", pinned=False)


@pytest.mark.parametrize("at", [SUM_MAIN, SUM_BACKUP], ids=["main", "backup"])
def test_a_bad_checksum_is_refused(at):
    buf = synthetic()
    buf[at] ^= 0x01
    with pytest.raises(M.RivalSourceError, match="checksum"):
        derive_syn(buf)


@pytest.mark.parametrize("main,backup", [(1, 0), (0, 1), (1, 1), (2, 2), (0xFF, 0)],
                         ids=["main-only", "backup-only", "both-1", "both-2", "main-ff"])
def test_a_scene_that_is_not_zero_is_refused(main, backup):
    buf = synthetic()
    buf[SCENE_MAIN], buf[SCENE_BACKUP] = main, backup
    seal(buf)
    with pytest.raises(M.RivalPreconditionError, match="scene"):
        derive_syn(buf)


@pytest.mark.parametrize("edit", [
    lambda b: b.__setitem__(STARTER_MAIN, b[STARTER_MAIN] | 0x10),
    lambda b: b.__setitem__(STARTER_MAIN, b[STARTER_MAIN] | 0x20),
    lambda b: b.__setitem__(STARTER_BACKUP, b[STARTER_BACKUP] | 0x40),
    lambda b: b.__setitem__(RIVAL_MAIN, b[RIVAL_MAIN] & 0x7F),
    lambda b: b.__setitem__(RIVAL_BACKUP, b[RIVAL_BACKUP] & 0x7F),
    lambda b: b.__setitem__(MAP_MAIN, 0x19),
    lambda b: b.__setitem__(MAP_BACKUP + 2, 0x0D),
    lambda b: b.__setitem__(MAP_MAIN + 3, 0x31),
], ids=["cyndaquil", "totodile", "chikorita-backup", "rival-bit-main-clear", "rival-bit-backup-clear",
        "map-group", "backup-y", "main-x"])
def test_a_wrong_story_precondition_is_refused(edit):
    buf = synthetic()
    edit(buf)
    seal(buf)
    with pytest.raises(M.RivalPreconditionError):
        derive_syn(buf)


def test_copies_that_disagree_are_refused():
    buf = synthetic()
    buf[REGION_BACKUP[0] + 0x100] ^= 0xFF
    seal(buf)
    with pytest.raises(M.RivalPreconditionError, match="disagree"):
        derive_syn(buf)


def test_only_the_pinned_source_hash_is_accepted():
    with pytest.raises(M.RivalSourceError, match="pinned"):
        M.derive_rival_scene(bytes(synthetic()))                 # default is pinned=True
    with pytest.raises(M.RivalSourceError, match="pinned"):
        M.derive_rival_scene(bytes(synthetic()), pinned=True)


def test_the_module_pins_are_the_documented_digests():
    assert M.PINNED_SRC_SHA256 == FIXTURE_SHA256
    assert M.EXPECTED_OUT_SHA256 == EXPECTED_SHA256
    assert M.SAVE_SIZE == SIZE


# ── the independent verifier: every departure from the allowlist is reported ───────────────────

def _tamper_cases():
    def region_byte(o, d):            # a mon byte changed and both sums honestly resealed: still undeclared
        d[0x2866 + 1] ^= 0x10
        seal(d)

    def footer(o, d):
        d[FOOTER + 3] ^= 0xFF

    def only_main(o, d):
        d[SCENE_BACKUP] = 0
        seal(d)

    def wrong_value(o, d):
        d[SCENE_MAIN] = d[SCENE_BACKUP] = 2
        seal(d)

    def no_reseal(o, d):
        d[SUM_MAIN:SUM_MAIN + 2] = o[SUM_MAIN:SUM_MAIN + 2]

    def one_sum_off(o, d):
        d[SUM_BACKUP] ^= 0x01

    def unchanged(o, d):
        d[:] = o

    def other_scene(o, d):
        d[SCENE_MAIN - 1] = 1    # the neighbouring scene byte, not Cherrygrove's
        seal(d)

    def marker(o, d):
        d[0x2007] = 0x62

    def event_bit(o, d):
        d[RIVAL_MAIN] &= 0x7F
        seal(d)

    def position(o, d):
        d[MAP_MAIN + 3] = 0x2F
        seal(d)

    def backup_only_byte(o, d):
        d[REGION_BACKUP[0] + 9] ^= 1
        seal(d)

    def truncate(o, d):
        del d[FOOTER:]

    return [region_byte, footer, only_main, wrong_value, no_reseal, one_sum_off, unchanged, other_scene,
            marker, event_bit, position, backup_only_byte, truncate]


@pytest.mark.parametrize("case", _tamper_cases(), ids=[
    "region-byte-resealed", "footer", "only-main-scene", "scene-2", "no-reseal", "one-sum-off", "unchanged",
    "neighbouring-scene-byte", "marker", "rival-bit", "position", "backup-only-byte", "truncated"])
def test_verifier_reports_each_departure(case):
    buf = synthetic()
    good, _ = derive_syn(buf)
    assert M.verify_rival_scene(bytes(buf), good) == []
    bad = bytearray(good)
    case(bytes(buf), bad)
    assert bytes(bad) != good or case.__name__ == "unchanged"
    problems = M.verify_rival_scene(bytes(buf), bytes(bad))
    assert problems, f"{case.__name__} slipped through the verifier"


def test_verifier_rejects_a_non_derivative_original_too():
    buf = synthetic()
    bad = bytearray(buf)
    bad[0x2007] = 0
    assert M.verify_rival_scene(bytes(bad), bytes(buf))


# ── builder mutants: the builder checks its own work before returning it ───────────────────────

def _mutants():
    def skip_backup(buf):
        buf[SCENE_MAIN] = 1

    def wrong_value(buf):
        buf[SCENE_MAIN] = buf[SCENE_BACKUP] = 2

    def touch_footer(buf):
        buf[SCENE_MAIN] = buf[SCENE_BACKUP] = 1
        buf[FOOTER] ^= 0xFF

    def extra_byte(buf):
        buf[SCENE_MAIN] = buf[SCENE_BACKUP] = 1
        buf[REGION_MAIN[0] + 0x200] ^= 0x01
        buf[REGION_BACKUP[0] + 0x200] ^= 0x01

    def neighbour(buf):
        buf[SCENE_MAIN - 1] = buf[SCENE_BACKUP - 1] = 1

    return [skip_backup, wrong_value, touch_footer, extra_byte, neighbour]


@pytest.mark.parametrize("mutant", _mutants(), ids=["skip-backup", "wrong-value", "touch-footer", "extra-byte",
                                                   "neighbour-scene"])
def test_mutated_builders_are_refused(monkeypatch, mutant):
    monkeypatch.setattr(M, "_apply_edit", mutant)
    with pytest.raises(M.RivalVerifyError):
        derive_syn(synthetic())


def test_a_builder_that_skips_a_checksum_is_refused(monkeypatch):
    real = M._reseal
    monkeypatch.setattr(M, "_reseal", lambda buf: real(buf) or buf.__setitem__(slice(SUM_BACKUP, SUM_BACKUP + 2), b"\x00\x00"))
    with pytest.raises(M.RivalVerifyError):
        derive_syn(synthetic())


def test_a_builder_that_does_not_reseal_at_all_is_refused(monkeypatch):
    monkeypatch.setattr(M, "_reseal", lambda buf: None)
    with pytest.raises(M.RivalVerifyError):
        derive_syn(synthetic())


# ── the numbers, re-derived from the pinned symbols and source (plan section 2 section checks) ─

def _sym():
    out = {}
    for line in (REPO / "data/polished/polished_slink.sym").read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2 and ":" in parts[0]:
            bank, addr = parts[0].split(":")
            out.setdefault(parts[1], (int(bank, 16), int(addr, 16)))
    return out


def _flat(bank_addr):
    bank, addr = bank_addr
    return bank * 0x2000 + addr - 0xA000


def test_offsets_agree_with_the_pinned_symbol_file():
    s = _sym()
    scene_in_player = s["wCherrygroveCitySceneID"][1] - s["wPlayerData"][1]
    assert scene_in_player == 0x57A
    assert s["wCherrygroveCitySceneID"][1] < s["wPlayerDataEnd"][1]      # inside the saved player block
    assert s["sGameData"] == (1, 0xA008) and s["sBackupGameData"] == (0, 0xB208)
    assert _flat(s["sGameData"]) + scene_in_player == SCENE_MAIN
    assert _flat(s["sBackupGameData"]) + scene_in_player == SCENE_BACKUP
    assert _flat(s["sChecksum"]) == SUM_MAIN and _flat(s["sBackupChecksum"]) == SUM_BACKUP
    assert _flat(s["sGameDataEnd"]) == REGION_MAIN[1] and _flat(s["sBackupGameDataEnd"]) == REGION_BACKUP[1]
    assert _flat(s["sGameData"]) == REGION_MAIN[0] and _flat(s["sBackupGameData"]) == REGION_BACKUP[0]
    map_in_game = s["wMapGroup"][1] - s["wPlayerData"][1]
    assert _flat(s["sGameData"]) + map_in_game == MAP_MAIN and map_in_game == 0x834
    assert _flat(s["sBackupGameData"]) + map_in_game == MAP_BACKUP
    ev = s["wEventFlags"][1] - s["wPlayerData"][1]
    assert _flat(s["sGameData"]) + ev + 3 == STARTER_MAIN and _flat(s["sBackupGameData"]) + ev + 3 == STARTER_BACKUP
    assert _flat(s["sGameData"]) + ev + 0xD0 == RIVAL_MAIN and _flat(s["sBackupGameData"]) + ev + 0xD0 == RIVAL_BACKUP
    cnt = s["wPartyCount"][1] - s["wPlayerData"][1]
    assert _flat(s["sGameData"]) + cnt == COUNT_MAIN and _flat(s["sBackupGameData"]) + cnt == COUNT_BACKUP
    assert scene_in_player == M.SCENE_IN_GAME_DATA
    assert M.SCENE_OFFSETS == (SCENE_BACKUP, SCENE_MAIN) or M.SCENE_OFFSETS == (SCENE_MAIN, SCENE_BACKUP)


def test_backup_displacement_is_0xe00_not_0x1000():
    assert SCENE_MAIN - SCENE_BACKUP == 0xE00 == SUM_MAIN - SUM_BACKUP


@pytest.mark.skipif(not SRC_ROOT.exists(), reason=f"pinned Polished source absent: {SRC_ROOT}")
def test_event_bits_and_scene_trigger_agree_with_the_pinned_source():
    idx, names = 0, {}
    for line in (SRC_ROOT / "constants/event_flags.asm").read_text(encoding="utf-8").splitlines():
        s = line.split(";")[0].strip()
        if s.startswith("const_def"):
            idx = 0
        elif s.startswith("const_next"):
            tok = s.split()[1]
            idx = int(tok[1:], 16) if tok.startswith("$") else int(tok, 0)
        elif s.startswith("const "):
            names[s.split()[1]] = idx
            idx += 1
    for name, mask_bit in (("EVENT_GOT_CYNDAQUIL_FROM_ELM", 4), ("EVENT_GOT_TOTODILE_FROM_ELM", 5),
                           ("EVENT_GOT_CHIKORITA_FROM_ELM", 6)):
        assert (names[name] // 8, names[name] % 8) == (3, mask_bit)
    assert (names["EVENT_RIVAL_CHERRYGROVE_CITY"] // 8, names["EVENT_RIVAL_CHERRYGROVE_CITY"] % 8) == (0xD0, 7)
    city = (SRC_ROOT / "maps/CherrygroveCity.asm").read_text(encoding="utf-8")
    assert re.search(r"coord_event\s+33,\s*7,\s*1,\s*CherrygroveRivalTriggerSouth", city)
    assert re.search(r"coord_event\s+33,\s*7,\s*0,\s*CherrygroveGuideGentTrigger", city)
    assert "loadtrainer RIVAL0, 3" in city
    assert re.search(r"scene_var CHERRYGROVE_CITY,\s+wCherrygroveCitySceneID",
                     (SRC_ROOT / "data/maps/scenes.asm").read_text(encoding="utf-8"))
    assert re.search(r"flag_array|and \[hl\]", (SRC_ROOT / "home/flag.asm").read_text(encoding="utf-8"))


# ── the real pinned fixture ────────────────────────────────────────────────────────────────────

def test_real_fixture_derivation_is_exactly_the_documented_four_bytes(fixture_bytes):
    out, disc = M.derive_rival_scene(fixture_bytes)
    assert len(out) == SIZE
    diff = [i for i in range(SIZE) if fixture_bytes[i] != out[i]]
    assert diff == PINNED_DIFF
    assert [(fixture_bytes[i], out[i]) for i in diff] == [(0x00, 0x01), (0xE4, 0xE5), (0x00, 0x01), (0xE4, 0xE5)]
    assert fixture_bytes[SUM_MAIN:SUM_MAIN + 2] == b"\xe4\x13" and out[SUM_MAIN:SUM_MAIN + 2] == b"\xe5\x13"
    assert out[FOOTER:] == fixture_bytes[FOOTER:]
    assert hashlib.sha256(out).hexdigest() == EXPECTED_SHA256 == disc["output_sha256"]
    assert disc["input_sha256"] == FIXTURE_SHA256 and disc["pinned_input"] is True
    assert disc["differing_offsets"] == PINNED_DIFF and disc["differing_bytes"] == 4
    assert M.verify_rival_scene(fixture_bytes, out) == []
    assert M.derive_rival_scene(fixture_bytes)[0] == out


def test_real_fixture_preconditions_are_the_documented_values(fixture_bytes):
    f = fixture_bytes
    assert f[SCENE_MAIN] == f[SCENE_BACKUP] == 0
    assert f[MAP_MAIN:MAP_MAIN + 4] == f[MAP_BACKUP:MAP_BACKUP + 4] == bytes.fromhex("18030c30")
    assert f[STARTER_MAIN] == f[STARTER_BACKUP] == 0
    assert f[RIVAL_MAIN] == f[RIVAL_BACKUP] == 0x95
    assert f[COUNT_MAIN] == f[COUNT_BACKUP] == 5
    assert f[REGION_MAIN[0]:REGION_MAIN[1]] == f[REGION_BACKUP[0]:REGION_BACKUP[1]]


def test_real_fixture_with_one_changed_byte_is_not_the_pinned_source(fixture_bytes):
    other = bytearray(fixture_bytes)
    other[FOOTER] ^= 0x01     # footer only: layout and sums stay valid, only the hash can refuse it
    with pytest.raises(M.RivalSourceError, match="pinned"):
        M.derive_rival_scene(bytes(other))


# ── source location + CLI ──────────────────────────────────────────────────────────────────────

def test_locate_source_prefers_an_existing_candidate_that_matches_the_pin(tmp_path, monkeypatch):
    good = tmp_path / "good.SaveRAM"
    other = tmp_path / "other.SaveRAM"
    other.write_bytes(b"x")
    good.write_bytes(bytes(synthetic()))
    monkeypatch.setattr(M, "PINNED_SRC_SHA256", hashlib.sha256(good.read_bytes()).hexdigest())
    monkeypatch.setattr(M, "SOURCE_CANDIDATES", (tmp_path / "missing", other, good))
    assert M.locate_source() == good
    assert M.locate_source(explicit=other) == other
    monkeypatch.setattr(M, "SOURCE_CANDIDATES", (tmp_path / "missing", other))
    assert M.locate_source() == other                  # present but wrong: returned so derive can name the refusal
    monkeypatch.setattr(M, "SOURCE_CANDIDATES", (tmp_path / "missing",))
    assert M.locate_source() is None


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    src = tmp_path / "src.SaveRAM"
    buf = synthetic()
    src.write_bytes(bytes(buf))
    out_bytes, _ = M.derive_rival_scene(bytes(buf), pinned=False)
    monkeypatch.setattr(M, "PINNED_SRC_SHA256", hashlib.sha256(bytes(buf)).hexdigest())
    monkeypatch.setattr(M, "EXPECTED_OUT_SHA256", hashlib.sha256(out_bytes).hexdigest())
    return src, out_bytes, tmp_path


def test_cli_writes_the_derivative_prints_the_disclosure_and_leaves_the_source(cli_env, capsys):
    src, expected, tmp = cli_env
    before = src.read_bytes()
    out = tmp / "sub" / "rival_scene.SaveRAM"
    assert M.main(["--src", str(src), "--out", str(out)]) == 0
    assert out.read_bytes() == expected
    assert src.read_bytes() == before
    disc = json.loads(capsys.readouterr().out)
    assert disc["output_sha256"] == hashlib.sha256(expected).hexdigest() and disc["synth"] is True
    assert disc["pinned_input"] is True


def test_cli_is_deterministic(cli_env):
    src, expected, tmp = cli_env
    assert M.main(["--src", str(src), "--out", str(tmp / "a")]) == 0
    assert M.main(["--src", str(src), "--out", str(tmp / "b")]) == 0
    assert (tmp / "a").read_bytes() == (tmp / "b").read_bytes() == expected


def test_cli_refuses_out_equal_to_source(cli_env, capsys):
    src, _, _ = cli_env
    before = src.read_bytes()
    assert M.main(["--src", str(src), "--out", str(src), "--force"]) == 2
    assert src.read_bytes() == before


def test_cli_refuses_an_existing_out_without_force(cli_env):
    src, expected, tmp = cli_env
    out = tmp / "exists"
    out.write_bytes(b"keep")
    assert M.main(["--src", str(src), "--out", str(out)]) == 2
    assert out.read_bytes() == b"keep"
    assert M.main(["--src", str(src), "--out", str(out), "--force"]) == 0
    assert out.read_bytes() == expected


def test_cli_refuses_to_write_into_the_committed_fixtures(cli_env):
    src, _, _ = cli_env
    target = REPO / "tests" / "fixtures" / "polished" / "should_never_exist.SaveRAM"
    assert M.main(["--src", str(src), "--out", str(target), "--force"]) == 2
    assert not target.exists()


def test_cli_refuses_a_source_that_is_not_the_pin(cli_env, tmp_path, capsys):
    _, _, tmp = cli_env
    bad = tmp / "other.SaveRAM"
    bad.write_bytes(bytes(synthetic(seed=99)))
    assert M.main(["--src", str(bad), "--out", str(tmp / "o")]) == 3
    assert not (tmp / "o").exists()
    assert "pinned" in capsys.readouterr().err


def test_cli_refuses_when_the_output_digest_is_not_the_expected_one(cli_env, monkeypatch, capsys):
    src, _, tmp = cli_env
    monkeypatch.setattr(M, "EXPECTED_OUT_SHA256", "0" * 64)
    assert M.main(["--src", str(src), "--out", str(tmp / "o")]) == 4
    assert not (tmp / "o").exists()


def test_cli_without_src_and_without_a_located_fixture_is_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(M, "SOURCE_CANDIDATES", (tmp_path / "missing",))
    assert M.main(["--out", str(tmp_path / "o")]) == 2


def test_cli_on_the_real_fixture_matches_the_expected_hash(fixture_bytes, tmp_path, capsys):
    src = next(p for p in FIXTURE_CANDIDATES if p.exists())
    out = tmp_path / "rival_scene.SaveRAM"
    before = src.read_bytes()
    assert M.main(["--src", str(src), "--out", str(out)]) == 0
    assert hashlib.sha256(out.read_bytes()).hexdigest() == EXPECTED_SHA256
    assert src.read_bytes() == before
    assert json.loads(capsys.readouterr().out)["output_sha256"] == EXPECTED_SHA256
