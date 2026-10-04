"""tests/unit/test_polished_forms_adapter.py — effective species ids for variant forms.

Owner rulings 2026-10-04:
  * cosmetic forms are ONE mon (Unown letters, Magikarp patterns) -> the key normalises their
    form bits to 0;
  * regional/variant forms are DIFFERENT mons -> the codec hands the shared state an EFFECTIVE
    species id (the variant's BaseData record index, 292..337), so server/state.py is untouched.

RED CONTROL comments name the mutation that breaks each test.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from server.adapters import polished_codec as codec  # noqa: E402
from server.adapters.gen2_polished import Gen2PolishedAdapter  # noqa: E402

# Rattata 19 form 2 = Alolan; Unown 201 forms are cosmetic; Magikarp 129 patterns cosmetic.
ALOLAN_RATTATA = (19, 2)
ALOLAN_RECORD = 295
UNOWN = 201


@pytest.fixture(scope="module")
def adapter() -> Gen2PolishedAdapter:
    return Gen2PolishedAdapter()


def _mon(species: int, form: int = 0, **over) -> dict:
    mon = {"species_id": species, "item": 0, "held_item": 0, "moves": [0, 0, 0, 0], "ot_id": 0x1234,
           "exp": 0, "evs": {k: 0 for k in codec.STAT_NAMES}, "dvs": {k: 0 for k in codec.STAT_NAMES},
           "form": form, "gender": "male", "is_egg": False, "shiny": False,
           "ability_slot": 0, "nature": 0, "dv_bytes": 0}
    mon.update(over)
    return mon


# ------------------------------------------------------------------ effective id


def test_variant_form_gets_its_record_index_as_effective_species() -> None:
    """A variant form's effective species IS its BaseData record index (FORMS-H2).

    RED CONTROL: return `int(species_id)` unconditionally from `effective_species`.
    """
    assert codec.is_variant_form(*ALOLAN_RATTATA)
    assert codec.effective_species(*ALOLAN_RATTATA) == ALOLAN_RECORD
    assert codec.effective_species(19, 0) == 19


def test_plain_and_cosmetic_forms_keep_their_species_id() -> None:
    """Cosmetic forms are ONE mon, so they must NOT become their own effective species.

    RED CONTROL: treat every non-zero form as a variant.
    """
    for form in (1, 2, 3):
        assert not codec.is_variant_form(UNOWN, form)
        assert codec.effective_species(UNOWN, form) == UNOWN


def test_decoded_blob_exposes_the_effective_species(adapter: Gen2PolishedAdapter) -> None:
    """`decode_party_blob` publishes it so the shared state never sees the raw pair.

    RED CONTROL: drop the `effective_species_id` assignment in decode_party_blob.
    """
    blob = codec.encode_party_blob({**_mon(*ALOLAN_RATTATA),
                                    "pp": [0, 0, 0, 0], "pp_ups": [0, 0, 0, 0], "happiness": 0,
                                    "pokerus": 0, "caught_data": 0, "caught_level": 0,
                                    "caught_location": 0, "status": 0, "unused": 0, "hp": 1,
                                    "max_hp": 1, "level": 5,
                                    "stats": {"attack": 1, "defense": 1, "speed": 1,
                                              "special_attack": 1, "special_defense": 1},
                                    "ot_raw_hex": "00" * 11, "nickname_raw_hex": "00" * 11})
    assert adapter.decode_party_blob(blob)["effective_species_id"] == ALOLAN_RECORD


# ------------------------------------------------------------------ type clause


def test_type_clause_judges_a_variant_on_its_own_types(adapter: Gen2PolishedAdapter) -> None:
    """Alolan Rattata is Dark/Normal; Kantonian Rattata is Normal. They must differ.

    This is the hole FORMS.md F4 described: the old code answered None for a
    variant-bearing species, so the clause skipped the pair entirely.

    RED CONTROL: restore `if form == 0 and any(...): return None` in species_types.
    """
    assert [adapter.type_name(t) for t in adapter.species_types(ALOLAN_RECORD)] == ["Dark", "Normal"]
    assert [adapter.type_name(t) for t in adapter.species_types(19)] == ["Normal", "Normal"]
    assert adapter.species_types(ALOLAN_RECORD) is not None


def test_unknown_id_still_returns_none(adapter: Gen2PolishedAdapter) -> None:
    """None is now reserved for genuinely unknown ids.

    RED CONTROL: `return None` unconditionally from species_types.
    """
    assert adapter.species_types(9999) is None


# ------------------------------------------------------------------ evo family


def test_variant_form_is_its_own_evo_family(adapter: Gen2PolishedAdapter) -> None:
    """UNVERIFIED upstream: evolutions.json has no rows for variant forms, so a variant is a
    singleton family rather than a guess at the standard one.

    RED CONTROL: delete the `_variant_by_record` branch from evo_family.
    """
    assert adapter.evo_family(ALOLAN_RECORD) == ALOLAN_RECORD
    assert adapter.evo_family(19) != ALOLAN_RECORD


# ------------------------------------------------------------------ identity key


def test_two_unown_letters_share_one_key() -> None:
    """Owner ruling: cosmetic forms are ONE mon, so the letters must not split the identity.

    RED CONTROL: `return int(form)` unconditionally from `key_form`.
    """
    assert codec.key(_mon(UNOWN, 1)) == codec.key(_mon(UNOWN, 2))


def test_variant_forms_keep_distinct_keys() -> None:
    """...but a regional form IS a different mon and must keep its form bits.

    RED CONTROL: return 0 from key_form for every form.
    """
    plain = codec.key(_mon(19, 0))
    alolan = codec.key(_mon(*ALOLAN_RATTATA))
    assert plain != alolan
    assert int(alolan[-2:], 16) & 0x1F == 2
    assert int(plain[-2:], 16) & 0x1F == 0


def test_shiny_and_gender_traits_are_unchanged() -> None:
    """Only the cosmetic form bits normalise; shiny bit 7 and gender bit 6 are untouched.

    RED CONTROL: drop the shiny/gender terms from the traits expression.
    """
    shiny_f = codec.key(_mon(UNOWN, 1, shiny=True, gender="female"))
    assert int(shiny_f[-2:], 16) & 0x80
    assert int(shiny_f[-2:], 16) & 0x40
    assert int(shiny_f[-2:], 16) & 0x1F == 0


def test_plain_mon_round_trips_unchanged() -> None:
    """20 plain mons must survive encode -> decode -> encode byte-for-byte.

    RED CONTROL: change PARTY["Form"] to 20.
    """
    for species in (1, 19, 25, 94, 129, 150, 201, 208, 250, 291,
                    4, 7, 10, 13, 16, 22, 28, 31, 34, 37):
        full = {**_mon(species), "pp": [0, 0, 0, 0], "pp_ups": [0, 0, 0, 0], "happiness": 0,
                "pokerus": 0, "caught_data": 0, "caught_level": 0, "caught_location": 0,
                "status": 0, "unused": 0, "hp": 1, "max_hp": 1, "level": 5,
                "stats": {"attack": 1, "defense": 1, "speed": 1,
                          "special_attack": 1, "special_defense": 1}}
        raw = codec.encode_party_mon(full)
        mon = codec._head(raw)
        assert mon["species_id"] == species
        assert codec.encode_party_mon(_rehydrate(mon)) == raw


def _rehydrate(head: dict) -> dict:
    """The full field set encode_party_mon needs, filled from a decoded head."""
    base = _mon(head["species_id"], head["form"])
    base.update({k: v for k, v in head.items() if k in base})
    base.update({"pp": [0, 0, 0, 0], "pp_ups": [0, 0, 0, 0], "level": 5,
                 "happiness": 0, "pokerus": 0,
                 "caught_data": 0, "caught_level": 0, "caught_location": 0, "status": 0,
                 "unused": 0, "hp": 1, "max_hp": 1,
                 "stats": {"attack": 1, "defense": 1, "speed": 1,
                           "special_attack": 1, "special_defense": 1}})
    return base


# ------------------------------------------------------------------ names


def test_variant_display_name(adapter: Gen2PolishedAdapter) -> None:
    """A variant record names as '<Form label> <Species>'.

    RED CONTROL: delete the `_variant_by_record` branch at the top of species_name.
    """
    name = adapter.species_name(ALOLAN_RECORD)
    assert "Rattata" in name and "Alolan" in name


def test_unknown_id_name_falls_back(adapter: Gen2PolishedAdapter) -> None:
    """RED CONTROL: return None instead of the `#id` fallback."""
    assert adapter.species_name(9999) == "#9999"


# ------------------------------------------------------------------ evolution families


def test_alolan_rattata_and_alolan_raticate_share_a_family(adapter: Gen2PolishedAdapter) -> None:
    """An evolution is the SAME mon as its pre-evolution, so the variant chain shares a family.

    RED CONTROL: return the record index unchanged from `evo_family` (the pre-card singleton).
    """
    assert adapter.evo_family(295) == adapter.evo_family(296)


def test_rattata_and_alolan_rattata_do_not_share_a_family(adapter: Gen2PolishedAdapter) -> None:
    """Owner ruling: a regional form is a DIFFERENT mon from its standard counterpart.

    RED CONTROL: seed the union-find with (species_id, record) for every variant.
    """
    assert adapter.evo_family(295) != adapter.evo_family(19)


def test_hisuian_sneasel_joins_the_plain_sneasler_family(adapter: Gen2PolishedAdapter) -> None:
    """Hisuian Sneasel -> Sneasler is an edge into a PLAIN species, so they unify.

    RED CONTROL: ignore evolves_to targets that are not variant records.
    """
    assert adapter.evo_family(332) == adapter.evo_family(286)


def test_paldean_wooper_joins_clodsires_family(adapter: Gen2PolishedAdapter) -> None:
    """Paldean Wooper -> Clodsire; the graph says so, so they unify (derived, not assumed).

    RED CONTROL: hardcode `return species_id` for any variant record.
    """
    assert adapter.evo_family(333) == adapter.evo_family(290)


def test_every_variant_family_is_deterministic(adapter: Gen2PolishedAdapter) -> None:
    """46 variants, each answering the same id twice, and never a string.

    RED CONTROL: make `_variant_families` return a fresh random ordering per call.
    """
    for record in adapter._variant_by_record:
        assert isinstance(adapter.evo_family(record), int)
        assert adapter.evo_family(record) == adapter.evo_family(record)


def test_plain_families_are_unchanged(adapter: Gen2PolishedAdapter) -> None:
    """Adding variant edges must not move any 1..291 family: evolutions.json is still the source.

    RED CONTROL: seed the union-find with a non-minimum representative.
    """
    for species, family in adapter._families.items():
        assert adapter.evo_family(species) == family
