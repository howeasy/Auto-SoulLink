"""O-33 synthetic setup builder (tools/gen2_synth_fixtures.py): valid copies/checksums, the decoded party is the spec,
and the disclosure names every changed byte (the checksums aside)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from server.adapters import gen2_codec as codec  # noqa: E402
from tools import gen2_synth_fixtures as synth  # noqa: E402

EDITS = {"party": [{"species": "CATERPIE", "level": 6, "exp": 342, "moves": ["TACKLE", "STRING_SHOT"]},
                   {"species": "SENTRET", "egg": True, "happiness": 1, "moves": ["TACKLE"]},
                   {"species": "PIDGEY", "level": 5, "moves": ["TACKLE"], "hp": 1, "status": synth.PSN}],
         "balls": [["MASTER_BALL", 5]], "step_count": 0x7F, "poison_step": 3, "last_spawn": "VIOLET_CITY"}


def base(title):
    path = ROOT / "tests/fixtures/gen2" / f"{title}_battle.SaveRAM"
    if not path.exists():
        pytest.skip(f"{path.name} missing")
    return path.read_bytes()


TITLES = ["crystal", "gold", "silver"]


def independent_checksums(raw, layout):
    """The source Checksum: a 16-bit byte sum over the primary copy (the contiguous saved regions) and over the
    backup copy's region spans (C/G engine/menus/save.asm SaveChecksum/SaveBackupChecksum), read little-endian."""
    primary = sum(sum(raw[r.primary:r.primary + r.length]) for r in layout.regions) & 0xFFFF
    backup = sum(sum(raw[r.backup:r.backup + r.length]) for r in layout.regions) & 0xFFFF
    stored = {name: int.from_bytes(raw[at:at + 2], "little") for name, at in layout.checksum_offsets.items()}
    return (primary, backup), (stored["primary"], stored["backup"])


@pytest.mark.parametrize("title", TITLES)
def test_the_built_save_is_valid_and_carries_the_spec(title):
    raw = base(title)
    out, disclosure = synth.build(title, raw, EDITS, base_name=f"{title}_battle")
    layout = codec.for_foundation(title)
    assert codec.strict_checksum_witness(out[:synth.CART], layout)["valid"]
    assert out[synth.CART:] == raw[synth.CART:]   # the RTC trailer is untouched
    for copy_name in ("primary", "backup"):
        party = codec.decode_saved_party(out[:synth.CART], layout, copy_name=copy_name)
        rows = [(m["species_id"], m["is_egg"], m["level"], m["exp"], m["hp"], m["status"], m["happiness"])
                for m in party["mons"]]
        assert rows == [(10, False, 6, 342, 23, 0, 70), (161, True, 5, 125, 0, 0, 1), (16, False, 5, 135, 1, 8, 70)]
    computed, stored = independent_checksums(out, layout)
    assert computed == stored
    assert disclosure["base_sha256"] != disclosure["sha256"] and disclosure["edits"] == EDITS


@pytest.mark.parametrize("title", TITLES)
def test_the_disclosure_names_every_changed_byte(title):
    raw = base(title)
    out, disclosure = synth.build(title, raw, EDITS)
    covered = set()
    for field in disclosure["fields"]:
        for at in ([field["cart"]] if field.get("cart") is not None else [field["primary"], field["backup"]]):
            covered |= set(range(at, at + field["size"]))
            assert out[at:at + field["size"]].hex() == field["new_hex"]
            assert raw[at:at + field["size"]].hex() == field["old_hex"]
    changed = {i for i in range(len(raw)) if raw[i] != out[i]}
    assert changed and changed <= covered and len(out) == len(raw) == synth.SAVERAM
    assert {f["symbol"] for f in disclosure["fields"]} >= {"wPartyCount", "wPartyMon1", "wBalls", "sChecksum",
                                                           "sBackupChecksum", "wLastSpawnMapGroup", "wStepCount",
                                                           "wPoisonStepCount"}


@pytest.mark.parametrize("edits, match", [
    ({"party": [{"species": "CATERPIE", "level": 7, "exp": 342, "moves": ["TACKLE"]}]}, "not level"),
    ({"last_spawn": "ROUTE_29"}, "not a spawn point"),
    ({"party": [{"species": "CATERPIE", "level": 6, "moves": []}]}, "moves required"),
    ({"map": {"map_const": "VIOLET_CITY", "x": 1, "y": 1}}, "unsupported edit keys"),
    ({"events": {"toggle": ["EVENT_GOT_EEVEE"]}}, "unsupported events keys"),
    ({"party": [{"species": "PIDGEY", "egg": True, "hp": 5, "moves": ["TACKLE"]}]}, "egg's HP"),
    ({"balls": [["POTION", 5]]}, "BALL-pocket"),
    ({"balls": [["POKE_BALL", 100]]}, "1..99"),
    ({"balls": [["POKE_BALL", 5], ["POKE_BALL", 5]]}, "unique"),
])
def test_contradictory_edits_are_refused(edits, match):
    with pytest.raises(ValueError, match=match):
        synth.build("crystal", base("crystal"), edits)


def test_only_an_exact_saveram_is_accepted():
    raw = base("crystal")
    for bad in (raw[:synth.CART], raw + bytes(1)):
        with pytest.raises(ValueError, match="exactly"):
            synth.build("crystal", bad, {"step_count": 1})


@pytest.mark.parametrize("title", TITLES)
def test_event_flags_use_the_source_numbering_and_are_disclosed(title):
    """constants/event_flags.asm jumps with const_next: EVENT_MET_BILL is set at new game
    (engine/events/std_scripts.asm InitializeEventsScript) and hides Bill at home until it is cleared."""
    from tools.gen2_source_data import load_context
    raw = (ROOT / "tests/fixtures/gen2" / f"{title}_town.SaveRAM").read_bytes()
    ctx = load_context(title)
    ids = synth.event_ids(ctx, title)
    layout = codec.for_foundation(title)
    before = synth._Save(raw[:synth.CART], layout)

    def flag(save, name):
        return save.read("wEventFlags", 1, ids[name] // 8)[0] >> (ids[name] % 8) & 1

    assert flag(before, "EVENT_INITIALIZED_EVENTS") == flag(before, "EVENT_MET_BILL") == 1
    out, disclosure = synth.build(title, raw, {"events": {"clear": ["EVENT_MET_BILL"]}})
    after = synth._Save(out[:synth.CART], layout)
    assert flag(after, "EVENT_MET_BILL") == 0 and flag(after, "EVENT_INITIALIZED_EVENTS") == 1
    assert [f["symbol"] for f in disclosure["fields"]][0] == "wEventFlags"
