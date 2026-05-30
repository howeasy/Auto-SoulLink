"""
Unit tests for the Upcoming Trainers feature — adapter methods + JSON loading.

Validates:
- Gen3Adapter.trainers_for_area returns the expected runtime IDs for known areas.
- Gen3Adapter.trainer_party returns the curated party for known trainer IDs
  (Falkner, Bugsy, Misty) sourced from rr_priority_trainers.json.
- Gen3Adapter.trainer_brief combines name+class+party in one call.
- Non-RR adapters (vanilla FRLG/Emerald) return [] / None for all calls.
- Unknown area / trainer IDs return [] / None cleanly without raising.
- The base GameRulesAdapter defaults still return [] / None for adapters
  that haven't overridden these methods.

Run:
    pytest tests/unit/test_trainer_panel.py -v
"""

from server.adapters.gen3_frlge import Gen3Adapter


def _rr() -> Gen3Adapter:
    return Gen3Adapter(is_rr=True)


def _vanilla() -> Gen3Adapter:
    return Gen3Adapter(is_rr=False)


# ── trainers_for_area ──────────────────────────────────────────────────


def test_trainers_for_area_returns_known_pewter_city():
    """Pewter City Gym (RR) hosts Brock. RR separates Pewter Museum
    (Falkner) from the city's gym (Brock) so they show up at different
    area_ids — the matchup here is just that pewter_city has Brock."""
    ids = _rr().trainers_for_area("pewter_city")
    assert isinstance(ids, list)
    assert ids, "pewter_city should have at least one trainer"
    # Brock should be present (one of his rr_trainers.json ids: 56 or 414).
    assert 56 in ids or 414 in ids


def test_trainers_for_area_pewter_museum_has_falkner():
    """Falkner specifically fights at Pewter Museum in RR."""
    ids = _rr().trainers_for_area("pewter_museum")
    assert ids, "pewter_museum should host Falkner"
    # His rr_trainers.json id should be in the list (43 or 45).
    assert 43 in ids or 45 in ids


def test_trainers_for_area_route_25_has_bugsy():
    """Route 25 in RR has Bugsy fights (id 47 is one of them)."""
    ids = _rr().trainers_for_area("route_25")
    assert 47 in ids


def test_trainers_for_area_unknown_returns_empty():
    """Unmapped area_ids return [] (widget hides cleanly)."""
    assert _rr().trainers_for_area("definitely_not_a_real_area") == []


def test_trainers_for_area_empty_string_returns_empty():
    """Empty area_id (no current area yet) returns [] without raising."""
    assert _rr().trainers_for_area("") == []


def test_trainers_for_area_non_rr_returns_empty():
    """Vanilla / AP / Emerald variants have no priority trainer data."""
    assert _vanilla().trainers_for_area("pewter_city") == []
    assert _vanilla().trainers_for_area("route_25") == []


# ── trainer_party ──────────────────────────────────────────────────────


def test_trainer_party_falkner_has_known_species():
    """Falkner (id 45) leads with a Flying-type pre-evo per RR's gym 1."""
    party = _rr().trainer_party(45)
    assert len(party) >= 1
    species = {m.get("species") for m in party}
    # Spot-check: Rufflet or Pidgey-style flying mon should be present.
    assert any("Rufflet" in s or "Flittle" in s or "Wattrel" in s
               for s in species if s), f"Unexpected Falkner species: {species}"


def test_trainer_party_unknown_id_returns_empty():
    """Trainer IDs not in rr_priority_trainers.json return []."""
    assert _rr().trainer_party(99999) == []


def test_trainer_party_party_entries_have_required_fields():
    """Every party entry must have species (str) and level (int)."""
    party = _rr().trainer_party(45)
    assert party, "expected Falkner to have a party"
    for mon in party:
        assert "species" in mon
        assert isinstance(mon.get("species"), str)
        assert "level" in mon
        # level may be 0 or a positive int — both are valid sentinels
        assert isinstance(mon.get("level"), int)


def test_trainer_party_non_rr_returns_empty():
    """Vanilla adapter exposes no party data even for known IDs."""
    assert _vanilla().trainer_party(45) == []


# ── trainer_brief ──────────────────────────────────────────────────────


def test_trainer_brief_falkner_includes_name_class_and_party():
    """The brief dict combines display + roster info for the dashboard."""
    brief = _rr().trainer_brief(45)
    assert brief is not None
    assert brief["name"]  # non-empty
    assert brief["class"]
    assert isinstance(brief["party"], list) and brief["party"]
    # "area" is informational; may be empty string when source had no
    # 3-line header location — just confirm the key exists.
    assert "area" in brief


def test_trainer_brief_unknown_returns_none():
    assert _rr().trainer_brief(99999) is None


def test_trainer_brief_non_rr_returns_none():
    assert _vanilla().trainer_brief(45) is None


# ── Default adapter behaviour (other gens) ─────────────────────────────


def test_base_adapter_defaults_empty():
    """Adapters that don't override these methods should fall through cleanly."""
    from server.adapters.gen1_rby import Gen1Adapter
    a = Gen1Adapter()
    assert a.trainers_for_area("pewter_city") == []
    assert a.trainer_party(45) == []
    # trainer_brief default synthesizes from trainer_party — should be None
    # when the party is empty.
    assert a.trainer_brief(45) is None
