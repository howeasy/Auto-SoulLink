"""Falsifiers for tools/gen3_fixtures.py.

Synthetic flash images built the same way tests/unit/test_gen3_flash_layout.py
builds them: no ROM, no real save, no emulator. Committed-fixture assertions
read tests/fixtures/gen3/*.sav directly.
"""

import glob
import os
import sys

import pytest

from server.adapters import gen3_codec as codec

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tools"))

import gen3_fixtures as fx  # noqa: E402  (tools/ is not a package; the tool is a script)

FIXTURES_DIR = os.path.join(REPO, "tests", "fixtures", "gen3")


def _blocks(seed: int) -> dict:
    return {
        "sb2": bytearray((seed + i) & 0xFF for i in range(codec.SAVEBLOCK2_SIZE)),
        "sb1": bytearray(codec.SAVEBLOCK1_SIZE),
        "storage": bytearray(codec.STORAGE_SIZE),
    }


def _mon(personality: int, ot_id: int, ot_name: str, *, party: bool) -> dict:
    mon = {
        "personality": personality, "ot_id": ot_id,
        "nickname": "MON", "language": 2,
        "is_bad_egg": 0, "has_species": 1, "is_egg_flag": 0,
        "block_box_rs": 0, "flags_unused": 0,
        "ot_name": ot_name, "markings": 0, "unknown": 0,
        "species": 1, "held_item": 0, "experience": 100,
        "pp_bonuses": 0, "friendship": 0, "growth_filler": 0,
        "moves": [1, 2, 3, 4], "pp": [10, 10, 10, 10],
        "evs": {"hp": 0, "attack": 0, "defense": 0, "speed": 0,
                "sp_attack": 0, "sp_defense": 0},
        "contest": [0, 0, 0, 0, 0, 0],
        "pokerus": 0, "met_location": 0, "met_level": 5,
        "met_game": 1, "pokeball": 1, "ot_gender": 0,
        "ivs": {"hp": 1, "attack": 1, "defense": 1,
                "speed": 1, "sp_attack": 1, "sp_defense": 1},
        "is_egg": 0, "ability_num": 0, "ribbons": 0,
    }
    if party:
        mon.update({"status": 0, "level": 5, "mail": 0xFF, "hp": 20,
                    "max_hp": 20, "attack": 10, "defense": 10, "speed": 10,
                    "sp_attack": 10, "sp_defense": 10})
    return mon


def _build_image(trainer_name="RED", trainer_id=0x1234, *, party_mons=None,
                  box_mons=None, counter=1, rotation=0) -> bytes:
    """One qualifying single-slot vanilla flash image (counter 1, so it lands
    in slot 1 i.e. physical sectors 14-27; matches HandleWriteSector's
    ``counter % 2`` slot rule)."""
    blocks = _blocks(0)
    blocks["sb2"][0:7] = codec.encode_name(trainer_name, 7)
    blocks["sb2"][0xA:0xE] = trainer_id.to_bytes(4, "little")
    blocks["sb1"][codec.SB1_PARTY_COUNT_OFFSET] = len(party_mons or [])
    for i, mon in enumerate(party_mons or []):
        start = codec.SB1_PARTY_OFFSET + i * codec.PARTY_MON_SIZE
        blocks["sb1"][start:start + codec.PARTY_MON_SIZE] = codec.encode_party_mon(mon)
    for (box, slot), mon in (box_mons or {}).items():
        idx = box * codec.MONS_PER_BOX + slot
        start = codec.BOX_DATA_OFFSET + idx * codec.BOX_MON_SIZE
        blocks["storage"][start:start + codec.BOX_MON_SIZE] = codec.encode_box_mon(mon)

    layout = codec.slot_layout()
    image = bytearray(codec.FLASH_SIZE)
    half = codec.NUM_SECTORS_PER_SLOT * (counter % codec.NUM_SAVE_SLOTS)
    for entry in layout:
        sid = entry["id"]
        chunk = bytes(blocks[entry["object"]])[entry["offset"]:entry["offset"] + entry["size"]]
        physical = half + (rotation + sid) % codec.NUM_SECTORS_PER_SLOT
        image[physical * codec.SECTOR_SIZE:(physical + 1) * codec.SECTOR_SIZE] = \
            codec.write_sector(chunk, sid, counter, layout)
    return bytes(image)


# --- committed fixtures -----------------------------------------------------

def _committed_fixtures():
    return sorted(glob.glob(os.path.join(FIXTURES_DIR, "*.sav")))


@pytest.mark.parametrize("path", _committed_fixtures() or [None])
def test_committed_fixtures_qualify(path):
    if path is None:
        pytest.skip("no fixtures committed yet")
    with open(path, "rb") as f:
        data = f.read()
    assert len(data) == codec.FLASH_SIZE == 131072
    is_rr = "rr_" in os.path.basename(path)
    result = fx.qualify_one(data, rr=is_rr)
    assert result["ok"], result["message"]


# --- import: RTC-suffix strip -----------------------------------------------

def test_import_strips_optional_rtc_suffix(tmp_path):
    body = _build_image()
    rtc = bytes(range(16))
    src = tmp_path / "with_rtc.SaveRAM"
    src.write_bytes(body + rtc)
    imported = fx.import_savedata(src.read_bytes(), rr=False)
    assert imported == body
    assert len(imported) == codec.FLASH_SIZE


def test_import_refuses_blank_save(tmp_path):
    blank = b"\xFF" * codec.FLASH_SIZE
    with pytest.raises(ValueError, match="blank"):
        fx.import_savedata(blank, rr=False)


# --- torn save refusal -------------------------------------------------------

def test_import_refuses_torn_save():
    image = bytearray(_build_image(counter=1))
    # Corrupt one sector's checksum in the selected slot -> torn/incomplete.
    half = codec.NUM_SECTORS_PER_SLOT * (1 % codec.NUM_SAVE_SLOTS)
    off = half * codec.SECTOR_SIZE + codec.OFF_SECTOR_CHECKSUM
    image[off] ^= 0xFF
    with pytest.raises(ValueError, match="qualify_flash refused"):
        fx.import_savedata(bytes(image), rr=False)


# --- derive-b: exact manifest, re-qualifies ---------------------------------

def test_derive_b_changes_exactly_the_manifested_fields():
    owned = _mon(0x1111, 0x1234, "RED", party=True)
    foreign = _mon(0x2222, 0x9999, "BLU", party=False)  # traded-mon provenance
    image_a = _build_image(trainer_name="RED", trainer_id=0x1234,
                            party_mons=[owned], box_mons={(0, 0): foreign})
    ok, msg = codec.qualify_flash(image_a)
    assert ok, msg

    image_b, manifest = fx.derive_b(image_a)
    assert len(image_b) == codec.FLASH_SIZE
    ok, msg = codec.qualify_flash(image_b)
    assert ok, msg

    # Manifest names sb2 identity + the one owned party mon; the foreign
    # box mon (different OTID) must NOT be in the manifest or changed.
    joined = "\n".join(manifest)
    assert "playerTrainerId" in joined
    assert "playerName" in joined
    assert "party[0]" in joined
    assert "box[0][0]" not in joined

    parsed_a, parsed_b = codec.parse_flash(image_a), codec.parse_flash(image_b)
    assert parsed_b["storage"] == parsed_a["storage"]  # foreign box mon untouched

    old_name, old_tid = fx._trainer_identity(parsed_a["sb2"])
    new_name, new_tid = fx._trainer_identity(parsed_b["sb2"])
    assert new_tid != old_tid
    assert new_name != old_name

    mon_a = codec.decode_party_mon(
        parsed_a["sb1"][codec.SB1_PARTY_OFFSET:codec.SB1_PARTY_OFFSET + codec.PARTY_MON_SIZE])
    mon_b = codec.decode_party_mon(
        parsed_b["sb1"][codec.SB1_PARTY_OFFSET:codec.SB1_PARTY_OFFSET + codec.PARTY_MON_SIZE])
    assert mon_b["ot_id"] == new_tid
    assert mon_b["species"] == mon_a["species"]  # unrelated payload preserved
    assert mon_b["checksum_ok"] is True


def test_derive_b_rr_refuses():
    # derive_b() itself only implements vanilla; the --rr CLI refusal
    # (cmd_derive_b) never calls it and always cites the UNVERIFIED reason.
    assert "UNVERIFIED" in fx.RR_DERIVE_REFUSAL
    assert "flash_save.md" in fx.RR_DERIVE_REFUSAL
    # derive_b() applied to a vanilla-shaped image never silently claims RR.
    body = _build_image()
    _, manifest = fx.derive_b(body)
    assert isinstance(manifest, list)


# --- boot-check / make-fr (card C2-6b): argument handling + the post-run verdict ---
#
# No emulator anywhere in here. The emulator lane is the coordinator's; what is falsifiable
# without one is (a) the two subcommands' CLI surface and (b) boot_check_verdict, which is
# the whole judgement the run's PASS/FAIL rests on.

def _parse(argv):
    return fx.build_parser().parse_args(argv)


def test_boot_check_argument_handling():
    args = _parse(["boot-check", "--rom", "patch/build/slink_RR.gba",
                   "--fixture", "tests/fixtures/gen3/rr_town.sav", "--rr"])
    assert (args.rom, args.fixture, args.rr) == (
        "patch/build/slink_RR.gba", "tests/fixtures/gen3/rr_town.sav", True)
    assert args.saveram_name is None and args.timeout > 0
    assert args.func is fx.cmd_boot_check
    assert _parse(["boot-check", "--rom", "r.gba", "--fixture", "f.sav"]).rr is False
    assert _parse(["boot-check", "--rom", "r.gba", "--fixture", "f.sav",
                   "--saveram-name", "Pokemon - FireRed Version (USA).SaveRAM"
                   ]).saveram_name == "Pokemon - FireRed Version (USA).SaveRAM"
    for missing in (["boot-check", "--rom", "r.gba"], ["boot-check", "--fixture", "f.sav"]):
        with pytest.raises(SystemExit):
            _parse(missing)


def test_make_fr_argument_handling():
    args = _parse(["make-fr", "--rom", "fr.gba", "--out",
                   "tests/fixtures/gen3/firered_town.sav"])
    assert (args.rom, args.out) == ("fr.gba", "tests/fixtures/gen3/firered_town.sav")
    assert args.func is fx.cmd_make_fr
    # make-fr is vanilla by construction: no --rr to get it wrong with.
    with pytest.raises(SystemExit):
        _parse(["make-fr", "--rom", "fr.gba", "--out", "o.sav", "--rr"])
    with pytest.raises(SystemExit):
        _parse(["make-fr", "--rom", "fr.gba"])


def test_saveram_name_drops_the_extension_and_appends_nothing():
    # BizHawk writes the optional RTC suffix itself; the seeded name must not carry one.
    assert fx.saveram_name("patch/build/gen3_slink_RR.gba") == "gen3_slink_RR.SaveRAM"
    assert fx.saveram_name("a/b/firered.gba") == "firered.SaveRAM"


def _q(counter, party, ok=True, message="ok"):
    return {"ok": ok, "message": message, "counter": counter,
            "party": [{"species": s, "level": lv} for s, lv in party]}


def test_boot_check_verdict_accepts_one_save_with_an_unchanged_party():
    ok, problems = fx.boot_check_verdict(_q(4, [(1, 5), (4, 7)]), _q(5, [(1, 5), (4, 7)]))
    assert (ok, problems) == (True, [])


def test_boot_check_verdict_refuses_a_counter_that_did_not_move():
    ok, problems = fx.boot_check_verdict(_q(4, [(1, 5)]), _q(4, [(1, 5)]))
    assert not ok
    assert "save counter 4 -> 4" in problems[0]


def test_boot_check_verdict_refuses_more_than_one_save():
    # Two saves is not the scenario being signed, and it means the driver did something else.
    ok, problems = fx.boot_check_verdict(_q(4, [(1, 5)]), _q(6, [(1, 5)]))
    assert not ok and "expected exactly one in-game save" in problems[0]


def test_boot_check_verdict_refuses_a_changed_party():
    ok, problems = fx.boot_check_verdict(_q(4, [(1, 5)]), _q(5, [(1, 6)]))
    assert not ok and "party changed" in problems[0]
    ok, problems = fx.boot_check_verdict(_q(4, [(1, 5)]), _q(5, []))
    assert not ok and "party changed" in problems[0]


def test_boot_check_verdict_refuses_a_flushed_save_that_does_not_qualify():
    ok, problems = fx.boot_check_verdict(
        _q(4, [(1, 5)]), _q(5, [(1, 5)], ok=False, message="sector 3 missing"))
    assert not ok
    assert any("does not qualify" in p and "sector 3 missing" in p for p in problems)


def test_boot_check_verdict_over_real_images():
    """The synthetic pair, end to end through qualify_one rather than hand-built dicts:
    the same save re-written with the counter bumped is a PASS, the untouched one a FAIL."""
    mon = _mon(0xAABBCCDD, 0x1234, "RED", party=True)
    before = fx.qualify_one(_build_image(party_mons=[mon], counter=4), rr=False)
    after = fx.qualify_one(_build_image(party_mons=[mon], counter=5), rr=False)
    assert before["ok"] and after["ok"]
    assert fx.boot_check_verdict(before, after) == (True, [])
    ok, problems = fx.boot_check_verdict(before, before)
    assert not ok and problems
