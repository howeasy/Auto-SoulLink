"""EXP-ADAPTER-POLICY: gift areas + fixed-species exemption for the expansion adapter, derived
from the real census (expansion_gifts.json) -- Beldum/Castform fixed; starters/fossils choices."""
import json
from pathlib import Path

import pytest

from server.adapters import get_adapter

PACK = Path(__file__).resolve().parents[2] / "data/games/gen3_exp/28877d73"
GIFT_AREAS = {"lavaridge_town", "littleroot_town_professor_birchs_lab",
              "mossdeep_city_stevens_house", "route119_weather_institute_2f",
              "rustboro_city_devon_corp_2f"}


@pytest.fixture(scope="module")
def a():
    return get_adapter("gen3_exp")


def test_gift_areas_match_pack_and_census(a):
    ckpt = json.loads((PACK / "write_checkpoint.json").read_text())["emerald_expansion_28877d73"]
    assert set(ckpt["gift_areas"]["ids"]) == GIFT_AREAS
    census = json.loads((PACK / "expansion_gifts.json").read_text())["declarations"]
    assert {r["gift_area"] for r in census if r["status"] == "active" and r["gift_area"]} == GIFT_AREAS
    assert all(a.is_gift_area(x) for x in GIFT_AREAS)
    assert a.is_gift_area("gift_route_101")  # the existing gift_ prefix stays
    assert not any(a.is_gift_area(x) for x in ("route_101", "route_104", "littleroot_town", ""))


def test_fixed_species_only_beldum_and_castform(a):
    fixed = {x for x in GIFT_AREAS if a.is_fixed_species_gift(x)}
    assert fixed == {"mossdeep_city_stevens_house", "route119_weather_institute_2f"}
    # choices (starters, fossils) and the Wynaut egg are not fixed
    for x in ("littleroot_town_professor_birchs_lab", "rustboro_city_devon_corp_2f", "lavaridge_town"):
        assert not a.is_fixed_species_gift(x)
    # gift_link_area may have prefixed a gift received elsewhere: stripped like Emerald
    assert a.is_fixed_species_gift("gift_mossdeep_city_stevens_house")


def test_no_static_is_fixed(a):
    census = json.loads((PACK / "expansion_gifts.json").read_text())["declarations"]
    statics = {r["area_id"] for r in census if r["kind"] == "static" and r["area_id"]}
    assert statics and not any(a.is_fixed_species_gift(x) for x in statics)
    assert not a.is_fixed_species_gift("route_101")


def test_a_pin_mismatch_fails_closed_without_rereading_the_pack_per_event(a, monkeypatch, tmp_path):
    """A stale census must refuse (ValueError) on every event call, but the hot path (area_enter,
    capture, no_catch) must not re-read and re-parse the pack each time: the failure is cached."""
    from server.adapters import gen3_expansion as mod
    bad = json.loads((PACK / "expansion_gifts.json").read_text())
    bad["source_commit"] = "0" * 40
    stale = tmp_path / "expansion_gifts.json"
    stale.write_text(json.dumps(bad))
    reads = []
    real = Path.read_text

    def counting(self, *args, **kwargs):
        if self == stale:
            reads.append(1)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(mod, "GIFTS_PACK", stale)
    monkeypatch.setattr(Path, "read_text", counting)
    mod._gift_policy_result.cache_clear()
    try:
        for _ in range(3):
            with pytest.raises(ValueError, match="source_commit does not match"):
                a.is_gift_area("lavaridge_town")
        assert len(reads) == 1
    finally:
        monkeypatch.undo()
        mod._gift_policy_result.cache_clear()
    assert a.is_gift_area("lavaridge_town")  # the real pack is healthy again


def test_gift_predicates_tolerate_non_string_areas(a):
    for junk in (None, 0, 7, [], {}):
        assert a.is_gift_area(junk) is False
        assert a.is_fixed_species_gift(junk) is False


def test_link_ids_follow_emerald_convention(a):
    assert a.gift_link_area("mossdeep_city_stevens_house") == "mossdeep_city_stevens_house"  # bare
    assert a.gift_link_area("route_101") == "gift_route_101"
    assert a.gift_link_area("gift_route_101") == "gift_route_101"
    assert not a.is_daycare_area("gift_daycare")  # no daycare id, as Emerald
