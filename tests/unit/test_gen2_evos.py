"""Branch and evolution-engine controls independently fixed from pinned source."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import gen_gen2_evos as evos  # noqa: E402


@pytest.fixture(scope="module")
def packs():
    return {title: evos.build(title) for title in ("crystal", "gold", "silver")}


def test_baby_species_connect_generation_two_families(packs):
    for pack in packs.values():
        family = pack["family"]
        assert len(family) == 251
        assert family["106"] == family["107"] == family["236"] == family["237"]
        assert family["25"] == family["26"] == family["172"]
        assert family["133"] == family["134"] == family["135"] == family["136"] == family["196"] == family["197"]
        assert family["243"] != family["244"] != family["245"]
        assert "253" not in family


def test_eevee_and_tyrogue_branch_parameters(packs):
    for pack in packs.values():
        methods = pack["methods"]
        eevee = {row["target"]: row for row in methods["133"]}
        assert set(eevee) == {134, 135, 136, 196, 197}
        assert eevee[196]["time"] == "MORNING_OR_DAY"
        assert eevee[197]["time"] == "NIGHT"
        assert eevee[196]["minimum_happiness"] == 220
        tyrogue = {row["target"]: row for row in methods["236"]}
        assert tyrogue[106]["comparison"] == "ATTACK_GT_DEFENSE"
        assert tyrogue[107]["comparison"] == "ATTACK_LT_DEFENSE"
        assert tyrogue[237]["comparison"] == "ATTACK_EQ_DEFENSE"
        assert {row["minimum_level"] for row in tyrogue.values()} == {20}


def test_trade_item_and_everstone_constraints(packs):
    for pack in packs.values():
        kadabra = pack["methods"]["64"][0]
        onix = pack["methods"]["95"][0]
        assert kadabra["method"] == "TRADE"
        assert kadabra["held_item_id"] is None
        assert kadabra["consumes_held_item"] is False
        assert onix["held_item"] == "METAL_COAT"
        assert onix["consumes_held_item"] is True
        assert onix["time_capsule_refused"] is True
        assert pack["method_rules"]["ITEM"]["everstone_blocks"] is False
        assert pack["method_rules"]["TRADE"]["everstone_blocks"] is True


def test_gold_silver_evolutions_independently_equal(packs):
    assert packs["gold"]["source"] != packs["silver"]["source"]
    for key in ("family", "evolutions", "method_rules"):
        assert packs["gold"][key] == packs["silver"][key]
    def semantic(pack):
        return {sid: [{k: v for k, v in row.items() if k != "evidence"}
                      for row in rows] for sid, rows in pack["methods"].items()}
    assert semantic(packs["gold"]) == semantic(packs["silver"])


def test_rom_pointer_or_branch_corruption_refused(monkeypatch):
    from dataclasses import replace
    context = evos.load_context("crystal")
    for symbol in ("EvosAttacksPointers", "TyrogueEvosAttacks"):
        raw = bytearray(context.rom)
        raw[evos.rom_offset(*context.symbol(symbol))] ^= 1
        monkeypatch.setattr(evos, "load_context", lambda *a, raw=bytes(raw), **k: replace(context, rom=raw))
        with pytest.raises(ValueError, match="ROM/source"):
            evos.build("crystal")


def test_check_detects_missing_family_branch_without_writing(tmp_path, packs, monkeypatch):
    monkeypatch.setattr(evos, "build", lambda title, root=ROOT: copy.deepcopy(packs[title]))
    args = ["--out-dir", str(tmp_path)]
    assert evos.main(args) == 0
    path = tmp_path / "gen2_gold/evolutions.json"
    stale = json.loads(path.read_text())
    stale["evolutions"]["236"].remove(237)
    path.write_text(json.dumps(stale))
    before = path.read_bytes()
    assert evos.main([*args, "--check"]) == 1
    assert path.read_bytes() == before
