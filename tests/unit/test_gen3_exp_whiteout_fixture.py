"""MODEL-only low-HP setup; native qualification must independently witness HP 1/20."""
import json
from pathlib import Path

import pytest

from tools import gen3_fixtures as f

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/gen3"
TITLE = f.codec.TITLE_EXPANSION
KIND = "whiteout_synth"


def test_new_whiteout_builder_and_qualified_pair_exist():
    assert hasattr(f, "build_exp_whiteout_seed"), "whiteout builder absent"
    assert (FIXTURES / "exp_whiteout_synth.sav").is_file(), "native-qualified A fixture absent"
    assert (FIXTURES / "exp_whiteout_synth_b.sav").is_file(), "native-qualified B fixture absent"


@pytest.mark.parametrize("side", ("a", "b"))
def test_only_two_lead_bytes_and_disclosed_continue_flag_change(side):
    c = f.codec
    seed = (FIXTURES / f"exp_pc{'_b' if side == 'b' else ''}.sav").read_bytes()
    before = c.parse_flash(seed, title=TITLE)
    raw = f.build_exp_whiteout_seed(seed)
    after = c.parse_flash(raw, title=TITLE)
    count, start = c._TITLE_PARTY_OFFSETS[TITLE]
    changed = [i for i, (old, new) in enumerate(zip(before["sb1"], after["sb1"], strict=True)) if old != new]
    assert changed == [start + 0x1E, start + 0x56]
    assert before["sb1"][start + 0x1E] == 0 and after["sb1"][start + 0x1E] == 19
    assert before["sb1"][start + 0x56] == 20 and after["sb1"][start + 0x56] == 1
    assert before["sb1"][start + 0x1C:start + 0x1E] == after["sb1"][start + 0x1C:start + 0x1E]
    assert before["sb1"][start + 0x20:start + 0x50] == after["sb1"][start + 0x20:start + 0x50]
    assert before["sb1"][start + 100:start + 600] == after["sb1"][start + 100:start + 600]
    assert before["storage"] == after["storage"]
    expected_sb2 = bytearray(before["sb2"])
    expected_sb2[9] |= 1
    assert after["sb2"] == bytes(expected_sb2)
    party = c.party_from_save(raw, title=TITLE, layout=f._record_layout(TITLE))
    assert len(party) == before["sb1"][count] == 2
    assert (party[0]["hp"], party[0]["max_hp"], party[0]["unknown"] & 0x3FFF) == (1, 20, 19)
    assert party[0]["moves"] == [33, 45, 0, 0] and all(mon["checksum_ok"] for mon in party)
    assert f.build_exp_seed(KIND, [], side=side) == raw
    assert any("CONTINUE_GAME_WARP" in p for p in f.exp_fixture_problems(raw, KIND))


def test_offsets_are_the_own_compiler_fields():
    structs = json.loads((ROOT / "data/games/gen3_exp/28877d73/facts.json").read_text())["structs"]
    field = structs["BoxPokemon"]["bitfields"]["hpLost"]
    assert (field["offset"], field["width"], field["shift"], field["mask"]) == (0x1E, 2, 0, "0x3fff")
    assert structs["Pokemon"]["fields"]["hp"] == {"offset": 0x56, "size": 2}
    assert structs["Pokemon"]["fields"]["maxHP"] == {"offset": 0x58, "size": 2}
