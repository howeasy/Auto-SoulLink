"""Item ID gaps and complete attribute coverage must not silently shift names."""
import json
from pathlib import Path

import pytest

from tools.gen_gen2_items import attribute_rows, item_ids


def source_ids():
    lines = ["const_def", "const NO_ITEM"] + [f"const ITEM_{i}" for i in range(1, 191)]
    for number in range(1, 51):
        if number in (5, 29):
            lines.append("const ITEM_C3" if number == 5 else "const ITEM_DC")
        lines.append(f"add_tm MOVE_{number}")
    lines += [f"add_hm HM_MOVE_{i}" for i in range(1, 8)] + ["const ITEM_FA"]
    return "\n".join(lines)


def test_tm_hm_ids_keep_native_gaps_and_last_hm():
    ids, machines = item_ids(source_ids())
    assert ids[0] == "NO_ITEM"
    assert machines[0xbf] == "TM01"
    assert 0xc3 not in machines and 0xdc not in machines
    assert machines[0xdd] == "TM29"
    assert machines[0xf9] == "HM07"
    assert ids[0xfa] == "ITEM_FA"


@pytest.mark.parametrize("old,new", [("const ITEM_C3\n", ""), ("add_hm HM_MOVE_7\n", ""),
                                    ("const ITEM_FA", "IF _CRYSTAL\nconst ITEM_FA\nENDC")])
def test_missing_slot_or_unsupported_conditional_refuses(old, new):
    with pytest.raises(ValueError):
        item_ids(source_ids().replace(old, new))


def test_attribute_table_requires_all_256_slots_including_sentinels():
    row = "item_attribute 0, HELD_NONE, 0, CANT_SELECT, BALL, ITEMMENU_NOUSE, ITEMMENU_CLOSE"
    assert len(attribute_rows("\n".join([row] * 256))) == 256
    with pytest.raises(ValueError, match="255 rows"):
        attribute_rows("\n".join([row] * 255))
    with pytest.raises(ValueError, match="seven"):
        attribute_rows("\n".join([row] * 255 + ["item_attribute 0, BALL"]))


def test_generated_source_verified_packs_keep_title_specific_items_and_sentinels():
    root = Path(__file__).resolve().parents[2] / "data/games"
    for title in ("crystal", "gold", "silver"):
        pack = json.loads((root / f"gen2_{title}/items.json").read_bytes())
        assert pack["source"]["evidence_level"] == "SOURCE"
        assert pack["items"]["1"]["name"] == "MASTER BALL"
        assert pack["items"]["5"]["name"] == "POKé BALL"
        assert pack["items"]["70"]["name"] == ("CLEAR BELL" if title == "crystal" else "TERU-SAMA")
        assert pack["items"]["221"]["tm_hm"] == "TM29"
        assert pack["items"]["249"]["tm_hm"] == "HM07"
        assert "0" not in pack["items"] and "255" not in pack["items"]
        assert pack["sentinels"]["0"]["constant"] == "NO_ITEM"
