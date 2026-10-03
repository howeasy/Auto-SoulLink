"""tools/gen2_ship_overlay_receipts.py in a tmp root (D6 step 3)."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import gen2_ship_overlay_receipts as ship  # noqa: E402

RAW = b'{ "raw":  1 }\r\n'  # non-canonical on purpose: copies must survive byte for byte


def _engine(title):
    return {"artifact_kind": "overlay", "schema": "gen2-engine-site-receipt-v2", "code_digest": "d1",
            "runs": [{"proven": ["a"], "code_digest": "keep"}], "t": title}


def _window(title):
    return {"artifact_kind": "overlay", "code_digest": "d1", "runs": {"x": {"proven": []}}, "t": title}


@pytest.fixture
def root(tmp_path):
    """A tmp root holding every captured source for the real 22 destinations."""
    for rel in ship.destinations():
        src = ship.source_of(tmp_path, rel)
        src.parent.mkdir(parents=True, exist_ok=True)
        title = rel.split("/")[2]
        if rel.endswith(".engine_sites.json"):
            src.write_text(json.dumps(_engine(title)))
        elif rel.endswith(".write_window.json"):
            src.write_text(json.dumps(_window(title)))
        else:
            src.write_bytes(RAW)
    return tmp_path


def test_destination_set_is_the_overlay_namespace():
    dsts = ship.destinations()
    assert len(dsts) == len(set(dsts)) == 22
    assert all("/receipts/overlay/" in d for d in dsts)
    assert sum(d.endswith(".write_window.json") for d in dsts) == 3


def test_write_strips_only_top_level_code_digest_and_copies_the_rest_byte_for_byte(root):
    assert ship.main(["--write"], root) == 0
    for rel in ship.destinations():
        raw = (root / rel).read_bytes()
        if rel.endswith(ship.DIGEST_STRIPPED):
            d = json.loads(raw)
            make = _engine if rel.endswith(".engine_sites.json") else _window
            want = make(d["t"])
            want.pop("code_digest")
            assert d == want  # nested run digest and everything else preserved
            assert raw == (json.dumps(d, indent=1, sort_keys=True) + "\n").encode()
        else:
            assert raw == RAW
    assert ship.main(["--check"], root) == 0


def test_missing_source_refuses_write_and_ships_nothing(root, capsys):
    victim = ship.destinations()[0]
    ship.source_of(root, victim).unlink()
    assert ship.main(["--write"], root) == 1
    assert Path(victim).name in capsys.readouterr().err
    assert not any((root / rel).exists() for rel in ship.destinations())


def test_wrong_kind_source_refuses(root):
    rel = next(d for d in ship.destinations() if d.endswith(".write_window.json"))
    ship.source_of(root, rel).write_text(json.dumps({"artifact_kind": "clean"}))
    assert ship.main(["--write"], root) == 1
    assert not any((root / rel).exists() for rel in ship.destinations())


def test_check_flags_drift_and_missing(root, capsys):
    assert ship.main(["--write"], root) == 0
    rels = ship.destinations()
    (root / rels[0]).write_bytes(b"tampered")
    (root / rels[1]).unlink()
    capsys.readouterr()
    assert ship.main(["--check"], root) == 1
    out = capsys.readouterr().out
    assert f"DRIFT {rels[0]}" in out and f"MISSING {rels[1]}" in out


def test_check_reports_missing_source_as_error(root, capsys):
    ship.source_of(root, ship.destinations()[0]).unlink()
    assert ship.main(["--check"], root) == 1
    assert "ERROR" in capsys.readouterr().out


def test_clean_receipts_are_never_touched(root):
    clean = root / "data/games/gen2_crystal/receipts/crystal.engine_sites.json"
    clean.parent.mkdir(parents=True)
    clean.write_text("clean")
    assert ship.main(["--write"], root) == 0
    assert clean.read_text() == "clean"
