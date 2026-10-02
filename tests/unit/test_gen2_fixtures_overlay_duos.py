"""Overlay qualification CLI covers every declared played duo fixture, never borrowing clean reports."""
import pytest

from tools import gen2_fixtures as fixtures

DUO_ADDITIONS = ("crystal_battle_errand", "crystal_battle_ot2", "crystal_battle_ot2_errand",
                 "crystal_town_ot2", "gold_battle_ot2", "silver_battle_errand")


@pytest.mark.parametrize("name", DUO_ADDITIONS)
def test_overlay_qualification_cli_accepts_each_duo_base_and_asks_for_fresh_capture(name, monkeypatch, tmp_path):
    calls = []
    def capture(selected, path, attempt, *, root, kind):
        calls.append((selected, path, attempt, root, kind))
        return {"passed": False, "errors": ["MODEL runner; no physical capture"]}
    monkeypatch.setattr(fixtures, "qualify", capture)
    assert fixtures.main(["--root", str(tmp_path), "--qualify-overlay", name, "--attempt", "MODEL-a1"]) == 1
    assert calls == [(name, tmp_path / f"tests/fixtures/gen2/{name}.SaveRAM", "MODEL-a1", tmp_path, "overlay")]
    assert not (tmp_path / f"tests/fixtures/gen2/receipts/overlay/{name}.qualification.json").exists()


def test_duo_capture_choices_do_not_expand_the_production_inspect_set():
    assert set(DUO_ADDITIONS) <= set(fixtures.OVERLAY_QUALIFIABLE)
    assert set(fixtures.OVERLAY_QUALIFIED) == {
        "crystal_battle", "crystal_town", "gold_battle", "gold_battle_errand", "gold_town",
        "silver_battle", "silver_town"}
    assert set(fixtures.OVERLAY_QUALIFIABLE) == set(fixtures.OVERLAY_QUALIFIED) | set(DUO_ADDITIONS)
