"""Polished Crystal adapter (server/adapters/gen2_polished.py): pack load, routing, 9-bit species + forms,
rival ids (all five rival classes), trainer_info, keys, blobs and the companion gate."""
import random

import pytest

from server.adapters import (
    foundation_for_rom_type,
    game_id_for_rom_type,
    get_adapter,
    polished_codec as pc,
)
from server.adapters.gen2_polished import Gen2PolishedAdapter


@pytest.fixture(scope="module")
def adapter():
    return get_adapter("gen2_polished", is_rr=False, rom_type="polished_crystal")


def test_routing_is_its_own_family():
    assert game_id_for_rom_type("polished_crystal") == "gen2_polished"
    assert foundation_for_rom_type("polished_crystal") == "gen2_polished" != foundation_for_rom_type("crystal")
    with pytest.raises(ValueError):
        Gen2PolishedAdapter(rom_type="crystal")


def test_pack_loads(adapter):
    assert adapter.game_id == "gen2_polished" and adapter.title == "polished_crystal"
    assert adapter.mons_per_box == 20 and adapter.memorial_box_index == 19
    assert adapter.party_blob_size() == pc.BLOB_SIZE == 70
    assert adapter.move_name(1) == "Acrobatics" and adapter.move_data(255)["type_name"] == "???"
    assert adapter.item_name(1) == "Poké Ball" and adapter.is_valid_held_item(1)
    assert not adapter.is_valid_held_item(245)                     # mail never travels
    assert adapter.area_display_name("olivine_city") == "Olivine City"
    assert {"Morn", "Day", "Nite"} <= set(adapter.encounter_table("route_29"))
    assert adapter.encounter_table("national_park_contest")["Contest"]


def test_nine_bit_species_and_forms(adapter):
    assert adapter.species_name(1) == "Bulbasaur"
    assert adapter.species_name(291) == "Annihilape"                # ext species: low byte 0x23 + bit 8
    assert adapter.species_name(255) == "#255" and adapter.species_name(256) == "#256"   # EGG / invalid
    assert adapter.evo_family(291) == 56 and adapter.evo_family(288) == 206
    assert adapter.to_national_dex(25) == 25 and adapter.to_national_dex(291) == 0
    # variant form: Alolan Rattata is its own name and types; a cosmetic form (Unown B) is the base species
    assert adapter.species_name(19, 2) == "Rattata (Alolan)"
    assert [adapter.type_name(t) for t in adapter.species_types(19, 2)] == ["Dark", "Normal"]
    # forms are in the pool (owner 2026-10-04): Rattata is plain Normal; the Alolan form is its own effective species
    assert [adapter.type_name(t) for t in adapter.species_types(19)] == ["Normal", "Normal"]
    assert len(adapter.species_types(1)) == 2                      # Bulbasaur has no variant forms
    assert adapter.species_name(201, 2) == "Unown"


def test_rival_ids_cover_all_five_classes(adapter):
    rivals = adapter.rival_trainer_ids()
    assert {tid >> 8 for tid in rivals} == {27, 28, 29, 30, 31}     # RIVAL0/1/2, LYRA1/2
    assert 28 * 256 + 1 in rivals and 30 * 256 + 1 in rivals
    # Pin the SIZE as well as the class set: a class-only assertion passes unchanged if a whole
    # rival's instances are dropped from the pack, which is the failure this guards.
    assert len(rivals) == 36


def test_trainer_info(adapter):
    assert adapter.trainer_info(28 * 256 + 1) == ("", "Rival")     # <RIVAL> placeholder hidden
    assert adapter.trainer_info(30 * 256 + 1) == ("Lyra", "Pokémon Trainer")
    assert adapter.trainer_info(0) == ("", "") and adapter.trainer_info(28 * 256 + 255) == ("", "")


def test_keys(adapter):
    assert adapter.is_valid_mon_key("ABCDEF:1234:123:C2")           # 0x123 = 291
    assert not adapter.is_valid_mon_key("ABCDEF:1234:100:00")       # 256 is no species
    assert not adapter.is_valid_mon_key("ABCD:1234:12")             # a vanilla Gen 2 key
    assert adapter.parse_ot_id("ABCDEF:1234:123:C2") == "1234"
    assert adapter.is_shiny("ABCDEF:1234:123:C2") and not adapter.is_shiny("ABCDEF:1234:123:42")
    assert adapter.gender_from_key("ABCDEF:1234:123:42", 291) == "female"
    assert adapter.gender_from_key("ABCDEF:1234:123:02", 291) == "male"
    assert adapter.gender_from_key("ABCDEF:1234:051:40", 0x51) == "genderless"   # Magnemite
    assert adapter.gender_from_key("ABCDEF:1234:123:42", 1) == ""


def test_party_blob_validation(adapter):
    raw = bytearray(pc.PARTY_SIZE)
    raw[0], raw[21], raw[31], raw[2] = 291 & 0xFF, 0x20, 30, 1
    blob = bytes(raw) + pc.encode_text("Kris", 11) + pc.encode_text("Ape", 11)
    mon = adapter.decode_party_blob(blob.hex())
    assert mon["species_id"] == 291 and mon["key"] == "000000:0000:123:00"
    assert adapter.validate_party_blob(blob, key="000000:0000:123:00")
    bad = bytearray(blob)
    bad[0] = 0                                                     # species 256: not in the pack
    assert not adapter.validate_party_blob(bytes(bad))
    assert not adapter.validate_party_blob(bytes(random.Random(0).randrange(256) for _ in range(69)))


def test_companion_is_required():
    reason = Gen2PolishedAdapter.companion_refusal({"rom_type": "polished_crystal", "artifact_kind": "clean"})
    assert reason and "Polished Crystal" in reason
    assert Gen2PolishedAdapter.companion_refusal({"rom_type": "crystal"}) is None
    from server.adapters.gen2_polished import _companion_abi
    if _companion_abi() is None:
        pytest.skip("companion overlay provenance absent")
    hello = {"rom_type": "polished_crystal", "artifact_kind": "overlay", "companion_abi": _companion_abi()}
    assert Gen2PolishedAdapter.companion_refusal(hello) is None
    assert Gen2PolishedAdapter.companion_refusal(dict(hello, companion_abi=_companion_abi() + 1))


def test_kanto_badge_bits_swap_marsh_and_soul(adapter):
    assert [name for _, name in adapter.gym_badge_slugs("polished_crystal")[12:14]] == ["Marsh Badge", "Soul Badge"]


# ── P8: randomized companion cartridges (rand_overlay) ─────────────────────────────────────
def test_rand_overlay_is_a_companion_kind_and_nothing_else_is_added():
    assert Gen2PolishedAdapter.supports_randomized("polished_crystal")
    assert not Gen2PolishedAdapter.supports_randomized("crystal") and not Gen2PolishedAdapter.supports_randomized(None)
    assert Gen2PolishedAdapter.rom_contract_by_sha1 is True
    for kind in ("rand", "named", "companion"):
        with pytest.raises(ValueError):
            Gen2PolishedAdapter(artifact_kind=kind)
    clean, overlay, rand = (Gen2PolishedAdapter(artifact_kind=k) for k in ("clean", "overlay", "rand_overlay"))
    assert (clean.randomized, overlay.randomized, rand.randomized) == (False, False, True)
    assert [a.supports_info_panel() for a in (clean, overlay, rand)] == [False, True, True]
    assert [a.native_trade_ui() for a in (clean, overlay, rand)] == [False, True, True]
    # clean and overlay keep the shipped tables; a randomized adapter shows nothing until it adopts its own
    assert clean.encounter_table("route_29") == overlay.encounter_table("route_29") is not None
    assert rand.encounter_table("route_29") is None


def test_companion_gate_admits_a_randomized_overlay_with_the_pinned_abi():
    from server.adapters.gen2_polished import _companion_abi
    if _companion_abi() is None:
        pytest.skip("companion overlay provenance absent")
    hello = {"rom_type": "polished_crystal", "artifact_kind": "rand_overlay", "companion_abi": _companion_abi()}
    assert Gen2PolishedAdapter.companion_refusal(hello) is None
    assert Gen2PolishedAdapter.companion_refusal(dict(hello, companion_abi=_companion_abi() + 1))
    assert Gen2PolishedAdapter.companion_refusal(dict(hello, artifact_kind="rand"))     # a randomized RELEASE


@pytest.mark.parametrize("fault", ["client_json", "client_list", "sha1", "no_pin", "rom_type", "not_a_dict"])
def test_ingest_takes_only_the_servers_contract_checked_bytes(fault):
    import hashlib
    rom = b"\x00" * 0x200
    payload = {"rom": rom, "rom_type": "polished_crystal", "rom_sha1": hashlib.sha1(rom).hexdigest()}
    if fault == "client_json":
        payload["rom"] = rom.hex()              # a JSON hello can carry text, never bytes
    elif fault == "client_list":
        payload["rom"] = list(rom)
    elif fault == "sha1":
        payload["rom_sha1"] = "0" * 40
    elif fault == "no_pin":
        del payload["rom_sha1"]
    elif fault == "rom_type":
        payload["rom_type"] = "crystal"
    else:
        payload = [rom]
    with pytest.raises(ValueError):
        Gen2PolishedAdapter(artifact_kind="rand_overlay").ingest_rom_content(payload)


def test_a_client_reported_rom_content_leaves_the_player_with_no_tables():
    """server.py _ingest_rom_content: a hello's JSON rom_content reaches the adapter, which refuses it; the player's
    adapter then shows NO encounters (the 'unavailable' state), never the shipped tables."""
    from types import SimpleNamespace

    from server.server import SLinkServer
    server = SLinkServer.__new__(SLinkServer)
    server.adapter = Gen2PolishedAdapter(artifact_kind="rand_overlay")
    server.connected_players = {"a": {"rom_type": "polished_crystal"}}
    server.state = SimpleNamespace(is_rr=False, artifact_kind="rand_overlay")
    server._player_adapters = {}
    server._ingest_rom_content("a", {"wild": {}, "rom_sha1": "ab" * 20})
    adopted = server._player_adapters["a"]
    assert adopted.randomized and adopted.encounter_table("route_29") is None
