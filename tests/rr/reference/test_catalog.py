"""Exact-ROM review generation and inactive reader contracts, never activation."""

import copy
import hashlib
import json

import pytest

from server.rr_catalog import POLICY_ID, CatalogError as ReaderError, RRCatalog
from tools.rr import catalog, reference


@pytest.fixture(scope="module")
def catalog_inputs(rr_repo, rr_rom_path):
    review = json.loads((rr_repo / catalog.REVIEW_PATH).read_text())
    return rr_rom_path.read_bytes(), reference.load_sources(rr_repo), review


@pytest.fixture(scope="module")
def candidate(catalog_inputs):
    return catalog.build_catalog(*catalog_inputs, final=False)


def serialize(data):
    data = copy.deepcopy(data)
    data.pop("catalog_id", None)
    data["catalog_id"] = hashlib.sha256(catalog.canonical(data)).hexdigest()
    return catalog.canonical(data)


def read(payload):
    return RRCatalog(
        payload, expected_sha256=hashlib.sha256(payload).hexdigest(), expected_policy_id=POLICY_ID
    )


@pytest.fixture
def completed_reader_shape(candidate):
    """SCHEMA FIXTURE ONLY: invented singleton dispositions for3 unknown records.

    This never passes through final generation, never writes an artifact, and
    must not be interpreted as evidence resolving those records. It only allows
    positive and corruption tests of a reader awaiting a future completed input.
    """
    data = copy.deepcopy(candidate)
    assert {row["species_id"] for row in data["unknowns"]} == {1038, 1214, 1224}
    for sid in [1038, 1214, 1224]:
        data["records"][sid]["region"] = "standard"
        data["records"][sid]["family_id"] = sid
        data["families"].append(
            {"family_id": sid, "root_species_id": sid, "region": "standard", "members": [sid]}
        )
    data["families"].sort(key=lambda row: row["family_id"])
    data["unknowns"] = []
    data["readiness"] = "inactive_catalog"
    return data


def test_deterministic_review_and_no_final_with_unresolved_taxonomy(catalog_inputs, candidate):
    assert candidate == catalog.build_catalog(*catalog_inputs, final=False)
    assert candidate["readiness"] == "review_blocked"
    assert {item["species_id"] for item in candidate["unknowns"]} == {1038, 1214, 1224}
    with pytest.raises(catalog.CatalogError, match="final catalog refused: 3"):
        catalog.build_catalog(*catalog_inputs)
    with pytest.raises(ReaderError, match="incomplete review"):
        read(serialize(candidate))


def test_final_cli_refusal_does_not_replace_existing_output(rr_repo, rr_rom_path, tmp_path):
    output = tmp_path / "catalog.json"
    output.write_bytes(b"existing artifact must survive refusal")
    with pytest.raises(SystemExit) as error:
        catalog.main(["--repo", str(rr_repo), "--rom", str(rr_rom_path), "--output", str(output)])
    assert error.value.code == 2
    assert output.read_bytes() == b"existing artifact must survive refusal"


def test_exact_rom_gender_types_names_and_domain(candidate):
    rows = candidate["records"]
    assert len(rows) == 1376
    assert [rows[sid]["kind"] for sid in [0, 252, 276, 412]] == [
        "none",
        "placeholder",
        "placeholder",
        "egg",
    ]
    assert rows[35]["types_rom"] == [23, 23] and rows[35]["types"] == [18, 18]
    assert rows[468]["gender_ratio"] == 31 and rows[303]["gender_ratio"] == 255
    assert rows[1356]["name"] == "Ursaluna-Bloodmoon"
    assert rows[1375]["name"] == "Chillet"
    assert all(rows[sid]["name"] for sid in range(1356, 1376))
    assert rows[418]["name"] == "Unown G" and rows[418]["region"] == "standard"
    assert rows[1044]["name"] == "Oricorio (Pa'u)" and rows[1044]["region"] == "standard"
    assert rows[1047]["family_id"] == 963 and rows[1293]["family_id"] == 1292


@pytest.mark.parametrize(
    "species,root",
    [
        (25, 172),
        (106, 236),
        (183, 350),
        (1186, 1200),
        (1037, 1036),
        (1356, 216),
        (1359, 1357),
        (1371, 1132),
    ],
)
def test_families_use_supported_roots_not_minimum_ids(candidate, species, root):
    assert candidate["records"][species]["family_id"] == root


@pytest.mark.parametrize(
    "evolved,regional_root,old_root",
    [(1154, 1222, 288), (1155, 1208, 52), (1156, 1221, 222), (1159, 1228, 615)],
)
def test_legacy_cross_region_unions_have_explicit_migration_rows(
    candidate, evolved, regional_root, old_root
):
    row = next(row for row in candidate["legacy_changes"] if row["species_id"] == evolved)
    assert row["before"]["family_id"] == old_root
    assert row["after"]["family_id"] == regional_root
    assert (
        candidate["records"][regional_root]["family_id"]
        != candidate["records"][old_root]["family_id"]
    )


def test_shared_precursor_edges_are_retained_but_partitioned(candidate, catalog_inputs):
    cuts = {tuple(pair) for pair in catalog_inputs[2]["shared_precursor_cuts"]}
    observed = set()
    assert len(candidate["physical_evolutions"]) == 592
    assert len(candidate["native_transformations"]) == 143
    for edge in candidate["physical_evolutions"]:
        a, b = edge["source_species"], edge["target_species"]
        if edge["family_disposition"] == "regional_cut":
            observed.add((a, b))
            assert candidate["records"][a]["family_id"] != candidate["records"][b]["family_id"]
    assert observed == cuts and len(cuts) == 12
    assert any(
        edge["source_species"] == 1036
        and edge["target_species"] == 1037
        and edge["family_disposition"] == "family_edge"
        for edge in candidate["physical_evolutions"]
    )


def test_chillet_reused_dex_never_unions_with_furret(candidate):
    assert (
        candidate["records"][1375]["rom_dex_group"]
        == candidate["records"][162]["rom_dex_group"]
        == 162
    )
    assert candidate["records"][1375]["family_id"] == 1375
    assert candidate["records"][162]["family_id"] == 161


@pytest.mark.parametrize("alteration", ["regional_alias", "missing_cut", "changed_transform"])
def test_unreviewed_topology_cannot_generate(catalog_inputs, alteration):
    rom, sources, review = catalog_inputs
    review = copy.deepcopy(review)
    if alteration == "regional_alias":
        review["cosmetic_groups"].append(
            {"base": 19, "members": [1020], "evidence": "wrong alias fixture"}
        )
    elif alteration == "missing_cut":
        review["shared_precursor_cuts"].pop()
    else:
        records = reference.extract_species(rom, sources["names"])
        evolution = reference.extract_evolutions(rom, records)
        transforms = copy.deepcopy(evolution["excluded_methods_0xfd_and_above"])
        transforms[0]["parameter"] += 1
        rows = catalog.build_catalog(rom, sources, review, final=False)["records"]
        with pytest.raises(catalog.CatalogError, match="transformation rows"):
            catalog.partition(rows, evolution["permanent_edges"], transforms, review)
        return
    with pytest.raises(catalog.CatalogError, match="regional"):
        catalog.build_catalog(rom, sources, review, final=False)


def test_erasing_unknown_labels_does_not_bypass_form_coverage_audit(catalog_inputs):
    rom, sources, review = catalog_inputs
    review = copy.deepcopy(review)
    review["unresolved"] = []
    result = catalog.build_catalog(rom, sources, review, final=False)
    assert result["readiness"] == "review_blocked"
    assert any(row["kind"] == "form_group" for row in result["unknowns"])
    with pytest.raises(catalog.CatalogError, match="final catalog refused"):
        catalog.build_catalog(rom, sources, review)


def test_inactive_reader_queries_and_immutable_records(completed_reader_shape):
    reader = read(serialize(completed_reader_shape))
    assert reader.family_id(25) == 172 and reader.family_id(1022) == 1022
    assert reader.species(35).types == (18, 18)
    assert reader.gender(468, 30) == "female" and reader.gender(468, 31) == "male"
    assert reader.gender(303, 0) == "genderless"
    with pytest.raises(AttributeError):
        reader.species(25).family_id = 25
    for sid in [0, 252, 412, 920, 1376, True, "25"]:
        with pytest.raises(ReaderError):
            reader.species(sid)
    for pid in [-1, 2**32, True, "1"]:
        with pytest.raises(ReaderError):
            reader.gender(25, pid)


@pytest.mark.parametrize(
    "corrupt",
    [
        "domain_bool",
        "missing_record",
        "kind",
        "ratio_bool",
        "types",
        "family",
        "physical",
        "alias",
        "root_bool",
        "unknown_field",
    ],
)
def test_strict_reader_refuses_corrupt_self_consistent_hashes(completed_reader_shape, corrupt):
    data = completed_reader_shape
    if corrupt == "domain_bool":
        data["domain"][0] = False
    elif corrupt == "missing_record":
        data["records"].pop()
    elif corrupt == "kind":
        data["records"][25]["kind"] = "placeholder"
    elif corrupt == "ratio_bool":
        data["records"][25]["gender_ratio"] = True
    elif corrupt == "types":
        data["records"][35]["types_rom"] = [18, 18]
    elif corrupt == "family":
        data["records"][1020]["family_id"] = 19
    elif corrupt == "physical":
        data["physical_evolutions"][0]["target_species"] = 3
    elif corrupt == "alias":
        data["form_aliases"][0]["member"] = 1020
    elif corrupt == "root_bool":
        data["families"][0]["root_species_id"] = True
    else:
        data["surprise"] = True
    with pytest.raises(ReaderError):
        read(serialize(data))


def test_reader_requires_selected_hash_policy_and_strict_json(completed_reader_shape):
    payload = serialize(completed_reader_shape)
    with pytest.raises(ReaderError, match="payload hash"):
        RRCatalog(payload, expected_sha256="0" * 64, expected_policy_id=POLICY_ID)
    with pytest.raises(ReaderError, match="policy"):
        RRCatalog(
            payload, expected_sha256=hashlib.sha256(payload).hexdigest(), expected_policy_id="old"
        )
    with pytest.raises(ReaderError, match="duplicate"):
        read(b'{"schema":1,"schema":2}')
    with pytest.raises(ReaderError, match="constant"):
        read(b'{"unused":NaN}')
