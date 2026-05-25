"""
Unit tests for Gen3Adapter.rival_trainer_ids — the Rival Team Swap feature's
trainer-ID gate.

Validates that:
- RR mode returns the expected Terry set (27 entries, spot-check known IDs).
- Vanilla/AP/Emerald mode returns an empty set (feature is RR-only for MVP).
- Other adapters inherit the empty-set default from GameRulesAdapter.

Run:
    pytest tests/unit/test_gen3_adapter_rival_ids.py -v
"""

from server.adapters.gen3_frlge import Gen3Adapter, _RR_RIVAL_TRAINER_IDS


def test_rr_rival_set_has_expected_size():
    """Pin the precomputed Terry set at the size confirmed against rr_trainers.json."""
    assert len(_RR_RIVAL_TRAINER_IDS) == 27


def test_rr_rival_set_contains_known_anchors():
    """Spot-check IDs from early/mid/late Terry encounters (verified via grep)."""
    # Early Terry (class 81): Oak's Lab → Cerulean → SS Anne area.
    assert 325 in _RR_RIVAL_TRAINER_IDS
    assert 326 in _RR_RIVAL_TRAINER_IDS
    # Mid/late Terry (class 89/90): Silph → Indigo Plateau.
    assert 437 in _RR_RIVAL_TRAINER_IDS
    # Post-game Terry (class 90): 738/739/740 cluster.
    assert 740 in _RR_RIVAL_TRAINER_IDS


def test_rr_rival_set_excludes_obvious_non_rivals():
    """Trainer ID 0 (placeholder) and class-13 non-rivals must not slip in."""
    assert 0 not in _RR_RIVAL_TRAINER_IDS
    # ID 1 ("Andrew") and ID 2 ("Red", class 13) are non-rivals.
    assert 1 not in _RR_RIVAL_TRAINER_IDS
    assert 2 not in _RR_RIVAL_TRAINER_IDS


def test_rr_mode_returns_populated_set():
    adapter = Gen3Adapter(is_rr=True)
    ids = adapter.rival_trainer_ids()
    assert isinstance(ids, set)
    assert len(ids) == 27
    assert 325 in ids


def test_vanilla_mode_returns_empty_set():
    adapter = Gen3Adapter(is_rr=False)
    assert adapter.rival_trainer_ids() == set()


def test_rival_set_is_disjoint_from_zero():
    """Defensive: no spurious 0 entries — gTrainerBattleOpponent_A == 0 means 'no battle'."""
    adapter = Gen3Adapter(is_rr=True)
    assert 0 not in adapter.rival_trainer_ids()


def test_returned_set_is_mutation_safe():
    """Callers shouldn't be able to corrupt the cached frozenset via the public API."""
    adapter = Gen3Adapter(is_rr=True)
    ids = adapter.rival_trainer_ids()
    ids.add(99999)  # caller mutates their copy
    # Next call should still return the canonical set without 99999.
    assert 99999 not in adapter.rival_trainer_ids()


def test_other_adapters_inherit_empty_default():
    """Verify the base-class default applies to a fresh subclass.

    Defining a stub subclass in-test isolates the inheritance check from
    the live Gen1/2/4/5 adapters (which would force importing their full
    data files into this test).
    """
    from server.adapters.base import GameRulesAdapter

    class _StubAdapter(GameRulesAdapter):
        def game_id(self): return "stub"
        def is_gift_area(self, area_id): return False
        def is_daycare_area(self, area_id): return False
        def is_fixed_species_gift(self, area_id): return False
        def evo_family(self, species_id): return species_id
        def gender_from_key(self, key, species_id): return ""
        def species_types(self, species_id): return None
        def is_shiny(self, key): return False
        def parse_ot_id(self, key): return ""
        def is_valid_mon_key(self, key): return True
        def species_name(self, species_id): return ""
        def type_name(self, type_id): return ""

    stub = _StubAdapter()
    assert stub.rival_trainer_ids() == set()
