"""Independent native trade projection MODEL; no physical trade qualification."""

import pytest

from server.adapters import gen2_codec as codec
from tools import gen2_trade_projection as projection
from tools.gen2_source_data import ROOT, rom_offset


@pytest.fixture(scope="module")
def verified_sources():
    return {title: projection._load_projection_data(title, ROOT) for title in ("crystal", "gold", "silver")}


@pytest.fixture(autouse=True)
def cached_verified_sources(monkeypatch, verified_sources):
    # Source/ROM verification runs once per title, never once per mutation.
    monkeypatch.setattr(projection, "_load_projection_data", lambda title, root: verified_sources[title])


def offered(data, species=64, item=0, level=18, moves=(100, 0, 0, 0), nickname=None):
    layout = data["layout"]
    raw = (ROOT / f"tests/fixtures/gen2/{layout.title}_battle.SaveRAM").read_bytes()[:0x8000]
    mon = codec.decode_saved_party(raw, layout, copy_name="primary")["mons"][0]
    mon.update(species_id=species, species_marker=species, held_item=item, level=level, happiness=123,
               moves=list(moves), pp=[data["moves"][m]["pp"] if m else 0 for m in moves], pp_ups=[0] * 4)
    stats = codec.calc_stats(data["species"][str(species)]["base_stats"], mon["dvs"], mon["stat_exp"], level)
    mon.update(max_hp=stats["hp"], hp=stats["hp"] - 3, stats={key: value for key, value in stats.items() if key != "hp"})
    mon["nickname_raw_hex"] = (nickname or data["names"][species]).hex()
    return codec.encode_party_blob(mon, layout)


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_trade_evolves_and_learns_exact_level_move(verified_sources, title):
    data = verified_sources[title]
    blob = offered(data)
    out = projection.project_received_mon(blob, species_marker=64, title=title)
    mon = codec.decode_party_blob(out["blob"], data["layout"], species_marker=65)
    before = codec.decode_party_blob(blob, data["layout"], species_marker=64)
    assert out["evolved"] and out["species_marker"] == 65 and out["expected_dex_species"] == [64, 65]
    assert mon["happiness"] == 70 and mon["held_item"] == 0
    assert mon["moves"] == [100, 50, 0, 0]  # Alakazam learns DISABLE at level 18.
    assert mon["pp"][1] == 20 and mon["pp_ups"][1] == 0
    assert mon["nickname_raw_hex"] == data["names"][65].hex()
    assert mon["ot_raw_hex"] == before["ot_raw_hex"] and mon["dv_word"] == before["dv_word"]
    assert mon["hp"] == before["hp"] + mon["max_hp"] - before["max_hp"]
    assert set(before["stat_exp"].values()) == {0}
    # Independent fresh-stat arithmetic, not another invocation of the projection's calc_stats.
    bases = {"attack": 50, "defense": 45, "speed": 120, "special_attack": 135, "special_defense": 85}
    expected = {name: 2 * (base + before["dvs"]["special" if name.startswith("special") else name]) * 18 // 100 + 5
                for name, base in bases.items()}
    assert mon["stats"] == expected
    assert mon["max_hp"] == 2 * (55 + before["dvs"]["hp"]) * 18 // 100 + 28


@pytest.mark.parametrize("species,item,target", [(61, 82, 186), (79, 82, 199), (95, 143, 208),
    (117, 151, 230), (123, 143, 212), (137, 172, 233), (67, 0, 68), (75, 0, 76), (93, 0, 94)])
@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_trade_evolution_variants(verified_sources, species, item, target, title):
    data = verified_sources[title]
    blob = offered(data, species, item, level=5)
    out = projection.project_received_mon(blob, species_marker=species, title=title)
    mon = codec.decode_party_blob(out["blob"], data["layout"], species_marker=target)
    assert out["species_marker"] == target and mon["held_item"] == 0


@pytest.mark.parametrize("species,item", [(64, 112), (95, 0), (16, 0)])
def test_everstone_missing_item_or_nontrade_species_do_not_evolve(verified_sources, species, item):
    data = verified_sources["gold"]
    blob = offered(data, species, item)
    out = projection.project_received_mon(blob, species_marker=species, title="gold")
    expected = bytearray(blob)
    expected[data["layout"].constants["MON_HAPPINESS"]] = 70
    assert out["blob"] == bytes(expected) and not out["evolved"]


def test_full_move_slots_need_exact_decision_and_preserve_custom_name(verified_sources):
    data = verified_sources["crystal"]
    nick = bytes([0x80, 0x81, 0x50] + [0] * 8)
    blob = offered(data, moves=(100, 93, 94, 115), nickname=nick)
    with pytest.raises(ValueError, match="decision"):
        projection.project_received_mon(blob, species_marker=64, title="crystal")
    choices = [{"move_id": 50, "replace_slot": 2}]
    out = projection.project_received_mon(blob, species_marker=64, title="crystal", move_decisions=choices)
    mon = codec.decode_party_blob(out["blob"], data["layout"], species_marker=65)
    assert mon["moves"] == [100, 93, 50, 115] and mon["nickname_raw_hex"] == nick.hex()
    assert out["move_decisions"] == choices


@pytest.mark.parametrize("field", ["MON_HAPPINESS", "MON_ITEM", "MON_SPECIES", "MON_ATK", "MON_MOVES", "MON_PP", "nickname"])
def test_received_mutations_are_rejected(verified_sources, field):
    data = verified_sources["crystal"]
    original = offered(data)
    expected = projection.project_received_mon(original, species_marker=64, title="crystal")
    actual = bytearray(expected["blob"])
    actual[59 if field == "nickname" else data["layout"].constants[field]] ^= 1
    with pytest.raises(ValueError, match="received"):
        projection.verify_received_mon(bytes(actual), actual_species_marker=65, offered_blob=original,
                                        species_marker=64, title="crystal")


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_native_egg_noop_is_pinned_and_mon_bytes_unchanged(verified_sources, title):
    data = verified_sources[title]
    blob = offered(data, species=64)
    out = projection.project_received_mon(blob, species_marker=253, title=title)
    assert out["blob"] == blob and out["species_marker"] == 253 and not out["evolved"]
    assert out["expected_dex_species"] == []


def test_unown_saved_form_side_effect_is_explicitly_uncovered(verified_sources):
    blob = offered(verified_sources["silver"], species=201, level=5)
    out = projection.project_received_mon(blob, species_marker=201, title="silver")
    assert not out["auxiliary_supported"] and out["unsupported_auxiliary_effects"] == ["unown_form_registration"]
    assert out["expected_dex_species"] == [201]


def test_declining_full_slot_move_preserves_moves_and_pp(verified_sources):
    data = verified_sources["gold"]
    blob = offered(data, moves=(100, 93, 94, 115))
    choice = [{"move_id": 50, "decline": True}]
    out = projection.project_received_mon(blob, species_marker=64, title="gold", move_decisions=choice)
    before = codec.decode_party_blob(blob, data["layout"], species_marker=64)
    after = codec.decode_party_blob(out["blob"], data["layout"], species_marker=65)
    assert out["move_decisions"] == choice and out["learned_moves"] == []
    assert after["moves"] == before["moves"] and after["pp"] == before["pp"]


@pytest.mark.parametrize("choice", [[{"move_id": 51, "replace_slot": 0}], [{"move_id": 50, "replace_slot": True}],
    [{"move_id": 50, "replace_slot": 4}], [{"move_id": 50, "decline": False}],
    [{"move_id": 50, "decline": True, "replace_slot": 0}], [{"move_id": 50, "replace_slot": 0}, {"move_id": 50, "decline": True}]])
def test_unknown_ambiguous_or_extra_move_decisions_refused(verified_sources, choice):
    blob = offered(verified_sources["crystal"], moves=(100, 93, 94, 115))
    with pytest.raises(ValueError):
        projection.project_received_mon(blob, species_marker=64, title="crystal", move_decisions=choice)


def test_native_hm_forgetting_is_refused(verified_sources):
    blob = offered(verified_sources["crystal"], moves=(57, 93, 94, 115))
    with pytest.raises(ValueError, match="HM"):
        projection.project_received_mon(blob, species_marker=64, title="crystal", move_decisions=[{"move_id": 50, "replace_slot": 0}])


def test_learned_move_resets_pp_ups_but_other_pp_are_preserved(verified_sources):
    data = verified_sources["crystal"]
    blob = bytearray(offered(data, moves=(100, 93, 94, 115)))
    at = data["layout"].constants["MON_PP"]
    blob[at:at + 4] = bytes([0x41, 0x82, 0xC3, 4])
    out = projection.project_received_mon(bytes(blob), species_marker=64, title="crystal", move_decisions=[{"move_id": 50, "replace_slot": 2}])
    assert out["blob"][at:at + 4] == bytes([0x41, 0x82, 20, 4])


def test_already_known_exact_level_move_does_not_consume_decision(verified_sources):
    data = verified_sources["crystal"]
    blob = offered(data, moves=(100, 50, 0, 0))
    out = projection.project_received_mon(blob, species_marker=64, title="crystal")
    assert out["learned_moves"] == [] and out["move_decisions"] == []
    with pytest.raises(ValueError, match="unused"):
        projection.project_received_mon(blob, species_marker=64, title="crystal", move_decisions=[{"move_id": 50, "decline": True}])


def test_multiple_same_level_moves_follow_native_source_order(verified_sources):
    data = verified_sources["silver"]
    blob = offered(data, level=1, moves=(100, 0, 0, 0))
    out = projection.project_received_mon(blob, species_marker=64, title="silver")
    mon = codec.decode_party_blob(out["blob"], data["layout"], species_marker=65)
    assert mon["moves"] == [100, 134, 93, 0]
    assert out["learned_moves"] == [{"move_id": 134, "slot": 1}, {"move_id": 93, "slot": 2}]


@pytest.mark.parametrize("item", [6, 7, 25, 158, 243, 255])
def test_mail_key_placeholder_hm_and_sentinel_items_refused(verified_sources, item):
    blob = offered(verified_sources["crystal"], item=item)
    with pytest.raises(ValueError, match="item"):
        projection.project_received_mon(blob, species_marker=64, title="crystal")


def test_learnset_rom_mutation_is_detected(verified_sources):
    from dataclasses import replace

    data = verified_sources["crystal"]
    ctx = data["ctx"]
    rom = bytearray(ctx.rom)
    rom[rom_offset(*ctx.symbol("AlakazamEvosAttacks")) + 1] ^= 1
    with pytest.raises(ValueError, match="learnset ASM/ROM"):
        projection._learnsets(replace(ctx, rom=bytes(rom)), {"methods": data["methods"]}, data["moves"])
