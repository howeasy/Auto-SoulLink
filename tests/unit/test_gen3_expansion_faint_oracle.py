"""The expansion's BoxPokemon.hpLost and A-side natural-faint receipts stay strict."""

from __future__ import annotations

import json

import pytest

from tools import gen3_expansion_faint_oracle as oracle


def test_hp_lost_mask_is_the_compiler_bitfield_and_refuses_drift(tmp_path):
    facts = json.loads(oracle.FACTS.read_text(encoding="utf-8"))
    field = facts["structs"]["BoxPokemon"]["bitfields"]["hpLost"]
    assert oracle.hp_lost_mask() == int(field["mask"], 16) == 0x3FFF
    field["bits"] = 13
    changed = tmp_path / "facts.json"
    changed.write_text(json.dumps(facts), encoding="utf-8")
    with pytest.raises(ValueError, match="compiler lane changed"):
        oracle.hp_lost_mask(changed)
    field["bits"], field["mask"] = 14, "0x1fff"
    changed.write_text(json.dumps(facts), encoding="utf-8")
    with pytest.raises(ValueError, match="compiler mask changed"):
        oracle.hp_lost_mask(changed)


@pytest.mark.parametrize("after,problems", [
    ({"unknown": 20}, []),
    ({"unknown": 19}, ["hpLost is 19"]),
    ({"unknown": 0x4014}, ["flags outside hpLost changed"]),
    ({"unknown": 0x8014}, ["flags outside hpLost changed"]),
    ({"unknown": None}, ["incomplete"]),
])
def test_memorial_only_accepts_exact_engine_hp_loss(after, problems):
    found = oracle.memorial_hp_lost_problems({"unknown": 0}, after, source_hp=0, source_max_hp=20)
    assert len(found) == len(problems)
    assert all(expected in actual for expected, actual in zip(problems, found, strict=True))


def test_raw_prewrite_hp_distinguishes_a_healed_from_a_still_fainted():
    before = {"unknown": 0}
    assert oracle.memorial_hp_lost_problems(before, {"unknown": 0}, source_hp=20, source_max_hp=20) == []
    assert oracle.memorial_hp_lost_problems(before, {"unknown": 20}, source_hp=0, source_max_hp=20) == []
    assert oracle.memorial_hp_lost_problems(before, {"unknown": 20}, source_hp=20, source_max_hp=20)
    assert oracle.memorial_hp_lost_problems(before, {"unknown": 0}, source_hp=0, source_max_hp=20)
    assert oracle.memorial_hp_lost_problems(before, {"unknown": 0}, source_hp=20, source_max_hp=20,
                                            require_zero=True)
    assert oracle.memorial_hp_lost_problems(before, {"unknown": 0}, source_hp=0, source_max_hp=0)


KEY = "4D55444B:20250925"
SOURCE = (f"RX memorialize key={KEY}\n"
          f"XG3_MEMORIAL_SOURCE {KEY} frame=24496 slot=0 hp=0 max_hp=20 attempted=281\n"
          f"TX memorialize_done {KEY} {{}}\n")


@pytest.mark.parametrize("text,valid", [
    (SOURCE, True),
    (SOURCE.replace("attempted=281", "attempted=0"), False),
    (SOURCE.replace("TX memorialize_done", "TX other"), False),
    (SOURCE.replace("RX memorialize", "RX other"), False),
    (SOURCE + SOURCE, False),
    (SOURCE.replace("hp=0 max_hp=20", "hp=20 max_hp=20"), True),
])
def test_memorial_source_must_be_one_successful_write_between_rx_and_ack(text, valid):
    source, problems = oracle.memorial_source(text, KEY)
    assert (source is not None) is valid
    assert (not problems) is valid


NATURAL = (f"LOSE {KEY} status_move_slot=1\n"
           f"FORCED_HP0 {KEY} frame=24495 in_battle=1 battler=1\n"
           f"LINKED_FAINTED {KEY}\n"
           f"TX faint {KEY} {{\"event\":\"faint\"}}\n")


@pytest.mark.parametrize("text,why", [
    (NATURAL, None),
    (NATURAL.replace("in_battle=1", "in_battle=0"), "missing raw in-battle HP0"),
    (NATURAL.replace("battler=1", "battler=0"), "missing raw in-battle HP0"),
    (NATURAL.replace(f"LINKED_FAINTED {KEY}\n", ""), "missing natural faint completion"),
    (NATURAL.replace(f"LOSE {KEY} status_move_slot=1\n", ""), "missing normal battle choice"),
    (NATURAL.replace(f"TX faint {KEY}", f"RX force_faint key={KEY}\nTX faint {KEY}"), "force command"),
    (NATURAL.replace(f"TX faint {KEY}", "[client] [SLink-gen3] write battle_faint 0x02031BBA +2 frame 24495\n"
                     f"TX faint {KEY}"), "SLink write"),
    ("[client] [SLink-gen3] write battle_faint 0x02031BBA +2 frame 1\n" + NATURAL, "SLink write"),
])
def test_natural_faint_requires_raw_hp0_without_force_or_client_write(text, why):
    found = oracle.natural_faint_receipt_problems(text, KEY)
    if why is None:
        assert found == []
    else:
        assert any(why in problem for problem in found)
