"""tools/gen2_final_sweep.py: the cell list and the receipt naming, no emulator."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import gen2_final_sweep as sweep  # noqa: E402


def test_every_release_cell_is_listed_once():
    ids = [c["id"] for c in sweep.cells()]
    assert len(ids) == len(set(ids))
    assert sum("/gen2_trade_" in i for i in ids) == 21
    assert sum(i.startswith("gate/") for i in ids) == 3 + 2 + 12
    assert {"gen2_new/gen2_faint_active_trainer", "gen2_gold_silver/gen2_faint_active_trainer"} <= set(ids)
    assert "gen2_crystal_gold/gen2_faint_active_trainer" not in ids


def test_duo_outputs_take_the_committed_receipt_names(tmp_path):
    build = tmp_path / "lane/patch/build"
    build.mkdir(parents=True)
    for suffix in ("a_result.txt", "pydec_result.txt", "a_witness.SaveRAM", "a_attempt1_result.txt", "a_link_save.SaveRAM"):
        (build / f"e2e_gen2_faint_s31_{suffix}").write_bytes(b"x\r\n")
    cell = {"scenario": "gen2_faint", "pair": "gs"}
    got = sweep.collect_duo(cell, "s31", tmp_path / "lane", tmp_path / "out")
    root = "tests/fixtures/gen2/receipts/duo_faint_gs_"
    assert sorted(got) == [root + "a_result.txt", root + "a_witness.SaveRAM", root + "pydec_result.txt"]
    assert got[root + "a_result.txt"] != got[root + "a_witness.SaveRAM"]   # LF-normalized text only
