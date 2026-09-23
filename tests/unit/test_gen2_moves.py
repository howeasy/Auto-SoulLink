"""Move count/record-format controls independent of the existing legacy pack."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.gen_gen2_charmap import integer
from tools.gen_gen2_moves import move_rows


def test_all_251_moves_are_required_and_extra_animation_slots_refuse():
    row = "move POUND, EFFECT_NORMAL_HIT, 40, NORMAL, 100, 35, 0"
    assert len(move_rows("\n".join([row] * 251))) == 251
    for count in (250, 252):
        with pytest.raises(ValueError, match="rows != 251"):
            move_rows("\n".join([row] * count))


def test_bad_record_and_unsupported_macro_refuse():
    with pytest.raises(ValueError, match="seven"):
        move_rows("move POUND, EFFECT_NORMAL_HIT")
    with pytest.raises(ValueError, match="unsupported"):
        move_rows("INCLUDE \"another_table.asm\"")


def test_percent_byte_uses_native_truncation_not_rounded_100_scale():
    assert integer("95 * $ff / 100") == 242
    assert integer("30 * $ff / 100") == 76
    assert integer("100 * $ff / 100") == 255


def test_generated_source_verified_move_bounds_and_known_records():
    root = Path(__file__).resolve().parents[2] / "data/games"
    for title in ("crystal", "gold", "silver"):
        pack = json.loads((root / f"gen2_{title}/moves.json").read_bytes())
        assert isinstance(pack["moves"], list)
        moves = {row["id"]: row for row in pack["moves"]}
        assert set(moves) == set(range(1, 252))
        assert moves[1]["power"] == 40
        assert moves[1]["pp"] == 35
        assert moves[33]["native_name"] == "TACKLE"
        assert moves[33]["accuracy_byte"] == 242
        assert moves[251]["constant"] == "BEAT_UP"
        assert moves[2]["type"] == "Fighting" and moves[2]["type_id"] == 1
        assert moves[12]["split"] == "Physical"  # native power0 but OHKO effect
        assert moves[117]["split"] == "Physical"  # native power0 but Bide effect
        assert moves[14]["split"] == "Status"
        assert moves[53]["split"] == "Special"
        assert pack["sentinels"] == {"0": "NO_MOVE", "255": "CANNOT_MOVE"}


def test_shared_adapter_package_import_and_existing_move_reader_compatibility():
    root = Path(__file__).resolve().parents[2]
    code = "from server.adapters.gen2_gsc import Gen2GSCAdapter; a=Gen2GSCAdapter(rom_type='Crystal'); assert a.move_data(2)['type_name']=='Fighting'; assert a.move_data(12)['split']==0; assert a.move_data(14)['split']==2; assert a.move_data(53)['split']==1; assert a.move_data(33)['accuracy']==95"
    result = subprocess.run([sys.executable, "-B", "-c", code], cwd=root, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
