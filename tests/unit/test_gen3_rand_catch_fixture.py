"""R4-LINK: a disclosed ball-stock edit leaves all other seeded state intact."""
from pathlib import Path

import pytest

from server.adapters import gen3_codec as codec
from tools import e2e_duo as duo, gen3_fixtures as fixtures

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("title,before_count", (("firered", 4), ("leafgreen", 2)))
def test_catch_fixture_changes_only_poke_ball_quantity_and_its_section_checksum(title, before_count):
    seed = (ROOT / f"tests/fixtures/gen3/{title}_party_battle.sav").read_bytes()
    assert duo.gen3_ball_count(seed, title) == before_count  # the failed 39da30fd run's inputs
    built, manifest = fixtures.build_frlg_synth(seed, "catch")
    assert duo.gen3_ball_count(built, title) == 20
    assert any(f"{before_count}->20" in line and "R4-LINK" in line for line in manifest)
    assert codec.qualify_flash(built)[0]
    old, new = codec.parse_flash(seed), codec.parse_flash(built)
    assert (new["slot"], new["counter"]) == (old["slot"], old["counter"])
    assert new["sb2"] == old["sb2"] and new["storage"] == old["storage"]
    assert duo.gen3_decode(built) == duo.gen3_decode(seed)
    # pret global.h: bagPocket_PokeBalls at 0x430, ItemSlot.quantity +2. Both pinned
    # seeds put ITEM_POKE_BALL (4) first; quantities use the low u16 encryption key.
    assert int.from_bytes(old["sb1"][0x430:0x432], "little") == 4
    expected = bytearray(old["sb1"])
    key = int.from_bytes(old["sb2"][0xF20:0xF22], "little")
    expected[0x432:0x434] = (20 ^ key).to_bytes(2, "little")
    assert new["sb1"] == bytes(expected)
    sectors = old["sectors"][old["slot"] * 14:(old["slot"] + 1) * 14]
    physical = next(s["index"] for s in sectors if s["id"] == 1) * 0x1000
    changes = {i for i, (a, b) in enumerate(zip(seed, built, strict=True)) if a != b}
    assert changes and changes <= {physical + i for i in (0x432, 0x433, 0xFF6, 0xFF7)}
    assert (ROOT / f"tests/fixtures/gen3/{title}_party_catch_synth.sav").read_bytes() == built


def test_only_randomized_link_selects_the_amended_stock():
    assert duo.SCENARIOS["link_gen3_rand"]["target"] == "catch_synth"
    assert duo.SCENARIOS["link_gen3"]["target"] == "battle"
    assert duo.SCENARIOS["admit_randomized_frlg"]["target"] == "town"
    assert duo.SCENARIOS["trainer_panel_gen3_rand"]["target"] == "trainer"
    # the Gen 1 standard ball_hunt retry: out-of-balls or a lost catch battle ("hunt ended whiteout")
    assert duo.scenario_attempt_limit("link_gen3_rand", "gen3_frlg") == 6
