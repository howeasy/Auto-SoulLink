"""A native hatch capture carries the full party stats needed for later RR retrieval."""

import pytest

from tests.unit.gen3_world import World, key_of, mon_record

OT = 0x0000ABCD
A, B = 0x11111111, 0x22222222
FULL_STATS = {"level": 5, "maxHP": 20, "attack": 11, "defense": 12, "speed": 13,
              "spAtk": 14, "spDef": 15, "pp1": 35, "pp2": 30, "pp3": 0, "pp4": 0}


@pytest.mark.parametrize("pack,title", [("gen3_frlg", "firered"), ("gen3_rr", "radical_red")])
def test_native_hatch_capture_carries_full_stats(pack, title):
    w = World(pack, title)
    starter = mon_record(A, OT, species=4)
    egg = mon_record(B, OT, species=175, is_egg=1)
    w.set_party([starter, egg])
    w.step_to(60)  # the egg is known before its native hatch

    hatched = mon_record(B, OT, species=175)
    w.set_party([starter, hatched])
    w.regs["R5"] = w.party_base() + 100  # AddHatchedMonToParty return points at slot 1
    w.fire("hatch")
    w.step()

    (capture,) = [e for e in w.sent if e.get("event") == "capture"]
    assert capture["key"] == key_of(B, OT)
    assert capture["area_id"] == "gift_daycare"
    assert capture["gift"] is True and capture["is_egg"] is False
    assert capture["stats"] == FULL_STATS
