"""EXP-RELEASE-ROW: release_gen3 is selectable on gen3_exp and boots the exp PC fixtures.
Model-only; the live receipt is the only proof the native PC path works on the expansion."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import e2e_duo as duo  # noqa: E402

EXP = "emerald_expansion_28877d73"


def test_release_gen3_applies_to_exp_with_the_pc_target():
    assert duo.scenario_applies("release_gen3", "gen3_exp")
    row = duo.SCENARIOS["release_gen3"]
    assert row["target_by_game"]["gen3_exp"] == "pc"
    assert not row.get("explicit_only") and "release_gen3" in duo.scenarios_for("gen3_exp")
    # the other titles' selection and targets are unchanged
    assert row["games"][:3] == ("gen3_frlg", "gen3_rr", "gen3_emerald")
    assert row["target_by_game"]["gen3_emerald"] == "pc" and row["target_by_game"]["gen3_rr"] == "battle2"
    assert row["target"] == {"a": "battle", "b": "town"}


def test_exp_pc_fixtures_hold_a_boxed_mon_and_survive_one_release():
    for name in ("exp_pc", "exp_pc_b"):
        party, boxes = duo.gen3_decode((ROOT / f"tests/fixtures/gen3/{name}.sav").read_bytes(), title=EXP)
        assert len(party) == 2 and len(boxes) == 2 and all(box == 0 for box, _ in boxes)


def test_exp_release_menu_constants_match_the_scripted_leg():
    """PC.popup(.., row 3) is RELEASE in the box popup (SUMMARY, MARK before it, CANCEL after);
    OPTION_WITHDRAW comes from the build's own compiler facts, not the Emerald 0."""
    k = json.loads((ROOT / "data/games/gen3_exp/28877d73/harness_facts.json").read_text())["constants"]
    assert (k["OPTION_WITHDRAW"], k["OPTION_DEPOSIT"], k["OPTION_MOVE_MONS"]) == (2, 1, 0)
    src = (ROOT / "lua/tests/gen3_scripted_play.lua").read_text()
    assert "TITLE == Syms.EXP_TITLE" in src and "k.OPTION_WITHDRAW" in src
