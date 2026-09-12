"""P14: starters are under the clauses in every generation; Yellow/Yellow is the one exemption.

Owner decision 2026-09-11. Gen 3 already applies the clauses to starters ("intro" is not in its
fixed-species set). Gen 1 applies them at the shared engine through the adapter's fixed-species
policy: the lab is a fixed-species gift only when both cartridges are Yellow, because both scripts
hand out Pikachu with no choice. The pair is declared at run creation and re-declared on restore.
"""
from itertools import product

import pytest

from server.adapters import get_adapter
from server.adapters.gen1_rby import Gen1Adapter
from server.gen1_engine_bridge import starter_grant
from server.gen1_run_config import create_runtime, open_runtime
from server.state import AreaStatus, LinkStatus, MonInfo, SoulLinkState
from tests.unit.test_gen1_sessions import contract

LAB = "oaks_lab"
KEY_A = "AAAA:0001:99"   # DVs:OTID:species byte (Bulbasaur 0x99 internal)
KEY_B = "BBBB:0002:99"
KEY_B_CHARMANDER = "BBBB:0002:B0"
BULBASAUR, CHARMANDER, PIKACHU = 1, 4, 25   # National Dex ids the engine reasons about


@pytest.mark.parametrize("a,b", list(product(("red", "blue", "yellow"), repeat=2)))
def test_lab_is_a_fixed_species_gift_only_for_yellow_yellow(a, b):
    adapter = Gen1Adapter(rom_type=a, peer_rom_type=b)
    assert adapter.is_fixed_species_gift(LAB) is ((a, b) == ("yellow", "yellow"))


def test_pair_declaration_is_case_insensitive_and_maps_ap_titles():
    assert Gen1Adapter(rom_type="Yellow", peer_rom_type="Yellow").is_fixed_species_gift(LAB) is True
    assert Gen1Adapter(rom_type="red_ap", peer_rom_type="Yellow").is_fixed_species_gift(LAB) is False
    assert Gen1Adapter(rom_type="Yellow", peer_rom_type="Blue (AP)").is_fixed_species_gift(LAB) is False


def test_unknown_partner_applies_the_clauses_until_bound():
    adapter = Gen1Adapter(rom_type="yellow")
    assert adapter.is_fixed_species_gift(LAB) is False
    adapter.bind_peer("yellow")
    assert adapter.is_fixed_species_gift(LAB) is True
    adapter.bind_peer("red")
    assert adapter.is_fixed_species_gift(LAB) is False


def test_other_fixed_species_gifts_do_not_depend_on_the_pair():
    for a, b in product(("red", "blue", "yellow"), repeat=2):
        adapter = Gen1Adapter(rom_type=a, peer_rom_type=b)
        assert adapter.is_fixed_species_gift("celadon_mansion_roof") is True   # Eevee
        assert adapter.is_fixed_species_gift("route_1") is False


@pytest.mark.parametrize("variants,fixed", [(("yellow", "yellow"), True), (("yellow", "red"), False), (("red", "blue"), False)])
def test_run_creation_and_restore_declare_the_pair_to_the_rule_adapter(tmp_path, variants, fixed):
    runtime = create_runtime(tmp_path, contract(*variants))
    try:
        assert runtime.state().rules.adapter.is_fixed_species_gift(LAB) is fixed
    finally:
        runtime.close()
    runtime = open_runtime(tmp_path)   # from_document rebuilds the adapter; the contract re-declares the pair
    try:
        assert runtime.state().rules.adapter.is_fixed_species_gift(LAB) is fixed
    finally:
        runtime.close()


def rules_for(tmp_path, a, b):
    rules = SoulLinkState(data_dir=str(tmp_path), adapter=get_adapter("gen1_rby", rom_type=a, peer_rom_type=b))
    rules.species_lock = rules.type_lock = True
    return rules


def test_bridge_pairs_distinct_starters_under_the_clauses(tmp_path):
    rules = rules_for(tmp_path, "red", "blue")
    assert starter_grant(rules, "a", LAB, MonInfo(key=KEY_A, level=5, species=BULBASAUR)) == (None, None)
    assert rules.area_states[LAB] == AreaStatus.PENDING_B
    link, rejection = starter_grant(rules, "b", LAB, MonInfo(key=KEY_B_CHARMANDER, level=5, species=CHARMANDER))
    assert rejection is None and link is not None and link.status == LinkStatus.ALIVE and link.area_id == LAB
    assert rules.area_states[LAB] == AreaStatus.LINKED and not rules.pending_captures
    assert rules.queued_commands == {"a": [], "b": []} and not any(rules.pokeballs_obtained.values())


def test_bridge_surfaces_the_engine_rejection_of_identical_starters(tmp_path):
    rules = rules_for(tmp_path, "red", "red")
    assert starter_grant(rules, "a", LAB, MonInfo(key=KEY_A, level=5, species=BULBASAUR)) == (None, None)
    link, rejection = starter_grant(rules, "b", LAB, MonInfo(key=KEY_B, level=5, species=BULBASAUR))
    assert link is None
    assert rejection == {"player": "b", "key": KEY_B, "reason": "Species clause: both are Bulbasaur"}
    # The rejected starter stays pending for the other player, exactly as Gen 3 leaves it.
    assert rules.area_states[LAB] == AreaStatus.PENDING_B and set(rules.pending_captures[LAB]) == {"a"}   # the lab waits on b
    assert LAB in rules.retry_areas["b"] and KEY_B not in rules.party_keys["b"] and not rules.links
    # Physical consequences run from the rules state through the held executors; nothing dangles here.
    assert rules.queued_commands == {"a": [], "b": []} and not rules.pending_memorials["b"]
    assert not any(rules.pokeballs_obtained.values())


def test_bridge_keeps_yellow_yellow_starters_exempt(tmp_path):
    rules = rules_for(tmp_path, "yellow", "yellow")
    assert starter_grant(rules, "a", LAB, MonInfo(key="AAAA:0001:54", level=5, species=PIKACHU)) == (None, None)
    link, rejection = starter_grant(rules, "b", LAB, MonInfo(key="BBBB:0002:54", level=5, species=PIKACHU))
    assert rejection is None and link is not None and link.status == LinkStatus.ALIVE
    assert link.a.species == link.b.species == PIKACHU


def test_mixed_pair_applies_the_clauses_and_pikachu_never_collides_with_a_kanto_starter(tmp_path):
    for species, key in ((BULBASAUR, KEY_B), (CHARMANDER, KEY_B_CHARMANDER), (7, "BBBB:0002:B1")):
        rules = rules_for(tmp_path / str(species), "yellow", "red")
        assert rules.adapter.is_fixed_species_gift(LAB) is False
        starter_grant(rules, "a", LAB, MonInfo(key="AAAA:0001:54", level=5, species=PIKACHU))
        link, rejection = starter_grant(rules, "b", LAB, MonInfo(key=key, level=5, species=species))
        assert rejection is None and link is not None and link.status == LinkStatus.ALIVE
