"""Neutral coverage-contract controls; a second binder can run these unchanged."""
from __future__ import annotations

import copy
import hashlib
import json
import pathlib

import pytest

from tools import coverage_map as coverage


def encoded(value):
    return json.dumps(value, sort_keys=True).encode()


@pytest.fixture(params=["portable.event", "another-binder/obligation"])
def contract(request):
    row_id = request.param
    obligations = {row_id: coverage.Obligation(("SOURCE", "PHYSICAL"))}
    artifacts = {"cartridge": "a" * 40}
    inputs = {"contract": "b" * 64}
    mapping = {
        "status": "MAPPED",
        "stimulus": {"kind": "NATURAL", "description": "Play through the event."},
        "artifacts": artifacts.copy(),
        "positive_control": "Observe the event after its preconditions hold.",
        "refusal_control": "Observe no event when the preconditions do not hold.",
        "oracle": "Independent saved-state decoder",
        "receipt_marker": "event-observed",
        "lane": "natural-event",
    }
    row = {
        "id": row_id, "required_layers": ["SOURCE", "PHYSICAL"], "mapping": mapping,
        "evidence": {layer: {"status": "OPEN", "reason": "Not run."}
                     for layer in ("SOURCE", "PHYSICAL")},
    }
    document = {"schema_version": 1, "input_sha256": inputs.copy(), "rows": [row]}
    return document, obligations, artifacts, inputs, {}


def check(contract, mode="mapping"):
    document, obligations, artifacts, inputs, receipts = contract

    def read(path):
        if path not in receipts:
            raise FileNotFoundError(path)
        return receipts[path]

    return coverage.validate_coverage(document, obligations=obligations, artifacts=artifacts,
                                      inputs=inputs, read_receipt=read, mode=mode)


def close(contract, layer):
    document, _, _, inputs, receipts = contract
    row = document["rows"][0]
    path = f"receipts/{layer.lower()}.json"
    receipt = {
        "schema_version": 1, "obligation_id": row["id"], "layer": layer, "verdict": "PASS",
        "input_sha256": inputs.copy(), "mapping_sha256": coverage.mapping_sha256(row["mapping"]),
        "artifacts": row["mapping"]["artifacts"].copy(), "lane": row["mapping"]["lane"],
        "marker": row["mapping"]["receipt_marker"],
        "controls": {"positive": "PASS", "refusal": "PASS"},
    }
    raw = encoded(receipt)
    receipts[path] = raw
    row["evidence"][layer] = {"status": "CLOSED", "receipt": {
        "path": path, "sha256": hashlib.sha256(raw).hexdigest(),
    }}
    return path


def mutate_receipt(contract, layer, mutation):
    path = close(contract, layer)
    data = json.loads(contract[4][path])
    mutation(data)
    raw = encoded(data)
    contract[4][path] = raw
    contract[0]["rows"][0]["evidence"][layer]["receipt"]["sha256"] = hashlib.sha256(raw).hexdigest()


def test_mapping_completeness_never_closes_unrun_physical(contract):
    report = check(contract)
    assert report["ok"] and report["mapping_complete"]
    assert not report["evidence_complete"]
    assert report["open"]["PHYSICAL"] == [contract[0]["rows"][0]["id"]]
    assert not check(contract, "closure")["ok"]


def test_unmapped_inventory_is_honest_but_blocks_mapping_gate(contract):
    row = contract[0]["rows"][0]
    row["mapping"] = {"status": "UNMAPPED", "reason": "Owning lane has not supplied an oracle."}
    assert check(contract, "inventory")["ok"]
    report = check(contract)
    assert not report["ok"] and report["unmapped"] == [row["id"]]


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate", "exemption", "input", "empty_oracle", "artifact"])
def test_mapping_falsifiers(contract, mutation):
    doc = contract[0]
    if mutation == "missing":
        doc["rows"].clear()
    elif mutation == "extra":
        row = copy.deepcopy(doc["rows"][0])
        row["id"] = "invented"
        doc["rows"].append(row)
    elif mutation == "duplicate":
        doc["rows"].append(copy.deepcopy(doc["rows"][0]))
    elif mutation == "exemption":
        doc["rows"][0]["required_layers"] = ["MODEL"]
    elif mutation == "input":
        doc["input_sha256"]["contract"] = "c" * 64
    elif mutation == "empty_oracle":
        doc["rows"][0]["mapping"]["oracle"] = " "
    else:
        doc["rows"][0]["mapping"]["artifacts"]["cartridge"] = "c" * 40
    assert not check(contract, "inventory")["ok"]


def test_current_receipts_close_only_declared_layers(contract):
    close(contract, "SOURCE")
    close(contract, "PHYSICAL")
    report = check(contract, "closure")
    assert report["ok"] and report["evidence_complete"]


@pytest.mark.parametrize("mutation", ["missing", "bytes", "layer", "artifact", "mapping", "controls", "verdict", "identity", "input"])
def test_closed_evidence_requires_current_matching_receipt(contract, mutation):
    path = close(contract, "PHYSICAL")
    if mutation == "missing":
        del contract[4][path]
    elif mutation == "bytes":
        contract[4][path] += b" "
    else:
        changes = {
            "layer": lambda r: r.update(layer="MODEL"),
            "artifact": lambda r: r["artifacts"].update(cartridge="c" * 40),
            "mapping": lambda r: r.update(mapping_sha256="c" * 64),
            "controls": lambda r: r["controls"].update(refusal="NOT_RUN"),
            "verdict": lambda r: r.update(verdict="SKIPPED"),
            "identity": lambda r: r.update(obligation_id="other"),
            "input": lambda r: r["input_sha256"].update(contract="c" * 64),
        }
        mutate_receipt(contract, "PHYSICAL", changes[mutation])
    assert not check(contract, "inventory")["ok"]


def test_model_execution_cannot_be_labeled_physical(contract):
    contract[0]["rows"][0]["mapping"]["stimulus"]["kind"] = "MODEL"
    close(contract, "PHYSICAL")
    assert not check(contract, "inventory")["ok"]


def test_command_receipt_cannot_close_natural_stimulus(contract):
    close(contract, "PHYSICAL")
    contract[0]["rows"][0]["mapping"]["stimulus"]["kind"] = "COMMAND"
    assert not check(contract, "inventory")["ok"]


@pytest.mark.parametrize("layers", [("SOURCE",), ("MODEL",)])
def test_only_injected_policy_can_declare_nonphysical_obligation(contract, layers):
    row = contract[0]["rows"][0]
    contract[1][row["id"]] = coverage.Obligation(layers)
    row["required_layers"] = list(layers)
    row["evidence"] = {layers[0]: {"status": "OPEN", "reason": "Not run."}}
    row["mapping"]["stimulus"]["kind"] = layers[0]
    close(contract, layers[0])
    report = check(contract, "closure")
    assert report["ok"] and report["open"]["PHYSICAL"] == []


def test_empty_injected_inventory_is_not_vacuous_success(contract):
    contract[1].clear()
    with pytest.raises(ValueError, match="obligations"):
        check(contract)


def planned_target(contract):
    row = contract[0]["rows"][0]
    target = {"state": "PLANNED", "digest": None, "base_artifact": "cartridge",
              "base_digest": contract[2]["cartridge"]}
    contract[2]["future-build"] = copy.deepcopy(target)
    contract[1][row["id"]] = coverage.Obligation(("SOURCE", "PHYSICAL"), ("future-build",))
    row["mapping"]["artifacts"] = {"future-build": copy.deepcopy(target)}
    return target


def test_planned_target_maps_without_requiring_its_future_build(contract):
    planned_target(contract)
    for mode in ("inventory", "mapping"):
        report = check(contract, mode)
        assert report["ok"] and report["mapping_complete"]
        assert not report["evidence_complete"]
        assert report["unbuilt_artifacts"] == ["future-build"]
    report = check(contract, "closure")
    assert not report["ok"]
    assert any("unbuilt" in error for error in report["errors"])


@pytest.mark.parametrize("layer", ["SOURCE", "MODEL", "PHYSICAL"])
def test_planned_target_cannot_support_any_closed_evidence(contract, layer):
    planned_target(contract)
    close(contract, layer)
    for mode in ("inventory", "mapping", "closure"):
        report = check(contract, mode)
        assert not report["ok"]
        assert any("unbuilt" in error for error in report["errors"])


@pytest.mark.parametrize("mutation", ["invent_digest", "replace_with_base", "omit_target"])
def test_map_cannot_promote_or_omit_injected_planned_target(contract, mutation):
    planned_target(contract)
    artifacts = contract[0]["rows"][0]["mapping"]["artifacts"]
    if mutation == "invent_digest":
        artifacts["future-build"].update(state="BUILT", digest="d" * 64)
    elif mutation == "replace_with_base":
        artifacts.clear()
        artifacts["cartridge"] = contract[2]["cartridge"]
    else:
        artifacts.clear()
    assert not check(contract, "inventory")["ok"]


@pytest.mark.parametrize("mutation", ["planned_hash", "missing_built_hash", "wrong_base", "stale_base", "bad_state_type"])
def test_inconsistent_target_policy_is_refused(contract, mutation):
    planned_target(contract)
    target = contract[2]["future-build"]
    if mutation == "planned_hash":
        target["digest"] = "d" * 64
    elif mutation == "missing_built_hash":
        target["state"] = "BUILT"
    elif mutation == "wrong_base":
        target["base_artifact"] = "unknown"
    elif mutation == "bad_state_type":
        target["state"] = ["PLANNED"]
    else:
        target["base_digest"] = "d" * 40
    with pytest.raises(ValueError):
        check(contract)


def test_built_target_requires_current_digest_and_new_matching_receipts(contract):
    planned_target(contract)
    close(contract, "SOURCE")
    close(contract, "PHYSICAL")
    target = contract[2]["future-build"]
    target.update(state="BUILT", digest="d" * 64)
    contract[0]["rows"][0]["mapping"]["artifacts"] = {"future-build": copy.deepcopy(target)}
    assert not check(contract, "closure")["ok"]  # Old planned-target receipts cannot transfer.
    close(contract, "SOURCE")
    close(contract, "PHYSICAL")
    assert check(contract, "closure")["ok"]


REQUIREMENTS = """# Contract
| id | Requirement | Oracle | S | M | P |
|---|---|---|---|---|---|
| first | A fact | — (SOURCE-only, P = —) | · | · | — |
| second | A schema | — (MODEL-only by design) | · | · | — |
| third | A runtime result | GAME | · | · | · |
"""
PROTOCOL = """## 9. Checklist
1. A wire assertion.
2. Another assertion.
2a. An added assertion.
## 10. Outside
1. Not in the checklist.
"""


def test_markdown_inputs_preserve_explicit_policy_and_protocol_suffixes():
    obligations = coverage.requirements_from_markdown(REQUIREMENTS)
    assert obligations["requirement:first"].required_layers == ("SOURCE",)
    assert obligations["requirement:second"].required_layers == ("MODEL",)
    assert obligations["requirement:third"].required_layers == ("SOURCE", "PHYSICAL")
    assert set(coverage.protocol_from_markdown(PROTOCOL, section="9", layers=("MODEL",))) == {
        "protocol:9.1", "protocol:9.2", "protocol:9.2a",
    }


def test_undeclared_physical_exemption_is_refused():
    with pytest.raises(ValueError, match="declaration"):
        coverage.requirements_from_markdown(REQUIREMENTS.replace("— (SOURCE-only, P = —)", "—"))


def test_duplicate_or_empty_normative_inventory_refused():
    with pytest.raises(ValueError, match="duplicate"):
        coverage.protocol_from_markdown(PROTOCOL.replace("2a.", "2."), section="9", layers=("MODEL",))
    with pytest.raises(ValueError):
        coverage.requirements_from_markdown("No requirement table")


def test_protocol_subheading_does_not_replace_selected_section():
    text = PROTOCOL.replace("2. Another", "### 9.1 More detail\n2. Another")
    assert set(coverage.protocol_from_markdown(text, section="9", layers=("MODEL",))) == {
        "protocol:9.1", "protocol:9.2", "protocol:9.2a",
    }


def test_mapping_cannot_omit_a_current_artifact(contract):
    contract[2]["second-cartridge"] = "d" * 40
    assert not check(contract, "inventory")["ok"]


def test_embedded_document_requires_one_unambiguous_block(tmp_path):
    payload = {"schema_version": 1, "input_sha256": {}, "rows": []}
    block = "<!-- COVERAGE_MAP_START -->\n```json\n" + json.dumps(payload) + "\n```\n<!-- COVERAGE_MAP_END -->"
    path = tmp_path / "coverage.md"
    path.write_text(block)
    assert coverage.load_document(path) == payload
    path.write_text(block + "\n" + block)
    with pytest.raises(ValueError):
        coverage.load_document(path)


def test_cli_missing_inputs_never_silently_skip(tmp_path, capsys):
    missing = str(tmp_path / "absent")
    assert coverage.main([
        "--map", missing, "--requirements", missing, "--protocol", missing,
        "--protocol-section", "9", "--protocol-layers", "MODEL",
        "--artifact-policy", missing, "--artifact-collection", "outputs",
        "--artifact-digest-field", "sha1", "--artifact-id", "candidate",
        "--mode", "mapping",
    ]) == 1
    assert "refused" in capsys.readouterr().err.lower()


def test_cli_distinguishes_inventory_mapping_and_closure(tmp_path, capsys):
    requirement_path = tmp_path / "requirements.md"
    protocol_path = tmp_path / "protocol.md"
    artifacts_path = tmp_path / "artifacts.json"
    map_path = tmp_path / "map.md"
    requirement_path.write_text(REQUIREMENTS, encoding="utf-8", newline="\n")
    protocol_path.write_text(PROTOCOL, encoding="utf-8", newline="\n")
    artifacts_path.write_bytes(encoded({"candidates": {"sample": {"digest": "a" * 64}}}))
    obligations = coverage.requirements_from_markdown(REQUIREMENTS)
    obligations.update(coverage.protocol_from_markdown(PROTOCOL, section="9", layers=("MODEL",)))
    document = {
        "schema_version": 1,
        "input_sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in (
            ("requirements", requirement_path), ("protocol", protocol_path), ("artifact_policy", artifacts_path))},
        "rows": [{
            "id": identifier, "required_layers": list(policy.required_layers),
            "mapping": {"status": "UNMAPPED", "reason": "No binding yet."},
            "evidence": {layer: {"status": "OPEN", "reason": "Not run."} for layer in policy.required_layers},
        } for identifier, policy in obligations.items()],
    }

    def publish():
        map_path.write_text("<!-- COVERAGE_MAP_START -->\n```json\n" + json.dumps(document)
                            + "\n```\n<!-- COVERAGE_MAP_END -->", encoding="utf-8")

    publish()
    args = ["--map", str(map_path), "--requirements", str(requirement_path), "--protocol", str(protocol_path),
            "--protocol-section", "9", "--protocol-layers", "MODEL", "--artifact-policy", str(artifacts_path),
            "--artifact-collection", "candidates", "--artifact-digest-field", "digest", "--artifact-id", "sample"]
    assert coverage.main([*args, "--mode", "inventory"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert not report["mapping_complete"] and not report["evidence_complete"]
    assert coverage.main([*args, "--mode", "mapping"]) == 1
    capsys.readouterr()
    for row in document["rows"]:
        row["mapping"] = {
            "status": "MAPPED", "stimulus": {"kind": "NATURAL" if "PHYSICAL" in row["required_layers"] else row["required_layers"][0],
                                               "description": "Exercise the declared obligation."},
            "artifacts": {"sample": "a" * 64}, "positive_control": "Known-valid input", "refusal_control": "Known-invalid input",
            "oracle": "Independent oracle", "receipt_marker": row["id"], "lane": "selected-lane",
        }
    publish()
    assert coverage.main([*args, "--mode", "mapping"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["mapping_complete"] and not report["evidence_complete"]
    assert coverage.main([*args, "--mode", "closure"]) == 1
    capsys.readouterr()
    document["rows"][0]["mapping"]["artifacts"] = {"future": {
        "state": "PLANNED", "digest": None, "base_artifact": "sample", "base_digest": "a" * 64,
    }}
    publish()
    target_args = [*args, "--planned-target", "future=sample", "--target-binding", "requirement:first=future"]
    assert coverage.main([*target_args, "--mode", "mapping"]) == 0
    assert json.loads(capsys.readouterr().out)["unbuilt_artifacts"] == ["future"]
    assert coverage.main([*args, "--mode", "mapping"]) == 1  # Map cannot authorize its own target.
    capsys.readouterr()
    assert coverage.main([*target_args, "--mode", "closure"]) == 1
    capsys.readouterr()
    assert coverage.main([*args, "--planned-target", "unused=sample", "--mode", "mapping"]) == 1
    assert "not bound" in capsys.readouterr().err
    artifacts_path.write_bytes(encoded({"candidates": {"sample": {"state": "UNBUILT", "digest": "a" * 64}}}))
    document["input_sha256"]["artifact_policy"] = hashlib.sha256(artifacts_path.read_bytes()).hexdigest()
    publish()
    assert coverage.main([*target_args, "--mode", "mapping"]) == 1
    assert "unbuilt artifact" in capsys.readouterr().err
    artifacts_path.write_bytes(encoded({"candidates": {"sample": {"digest": "a" * 64}}}))
    document["input_sha256"]["artifact_policy"] = hashlib.sha256(artifacts_path.read_bytes()).hexdigest()
    publish()
    protocol_path.write_text(PROTOCOL + "\nChanged contract context.\n", encoding="utf-8")
    assert coverage.main([*target_args, "--mode", "inventory"]) == 1
    assert "stale" in capsys.readouterr().out


# --- F-3 per-family table/JSON binding: the two require explicit sync. ---
# GEN2_MAP_PATH is the real coverage map, not a synthetic fixture: these two
# tests catch a hand-edit to only the table or only the JSON F-3 cell.

GEN2_MAP_PATH = pathlib.Path(__file__).resolve().parents[2] / "docs" / "gen2" / "gen2_coverage_map.md"

F3_FAMILIES = [
    "battle_start_wild", "battle_start_trainer", "battle_end_result", "capture_party",
    "capture_box", "player_faint", "poison_faint", "whiteout", "evolution_publish",
    "npc_trade", "link_trade", "pc_deposit", "pc_withdraw", "pc_release", "pc_changebox",
    "map_load", "ball_received", "save_success", "continue", "new_game", "soft_reset",
    "egg_hatch",
]


def _f3_table_rows():
    """Parse the F-3 Markdown table's four columns, keyed by family."""
    doc_lines = GEN2_MAP_PATH.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(doc_lines) if line.startswith("## F-3"))
    end = next((i for i in range(start + 1, len(doc_lines)) if doc_lines[i].startswith("## ")), len(doc_lines))
    section = doc_lines[start:end]
    rows = {}
    for line in section:
        if not line.startswith("| "):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4 or cells[0] in ("Family", "") or set(cells[0]) == {"-"}:
            continue
        if cells[0] not in F3_FAMILIES:
            continue
        rows[cells[0]] = {"positive": cells[1], "refusal": cells[2], "witness": cells[3]}
    assert set(rows) == set(F3_FAMILIES), f"table family rows do not match the known 22: {sorted(rows)}"
    return rows


def _split_family_field(text, families, delim):
    """Split one JSON F-3 field ("fam1<delim>text1; fam2<delim>text2; ...") by family."""
    positions = []
    search_from = 0
    for family in families:
        needle = family + delim
        idx = text.index(needle, search_from)
        positions.append((family, idx + len(needle)))
        search_from = idx + len(needle)
    result = {}
    for i, (family, content_start) in enumerate(positions):
        end = (text.index(families[i + 1] + delim, content_start) if i + 1 < len(families) else len(text))
        segment = text[content_start:end]
        if segment.endswith("; "):
            segment = segment[:-2]
        result[family] = segment
    return result


def _f3_json_mapping():
    document = coverage.load_document(GEN2_MAP_PATH)
    rows = {row["id"]: row for row in document["rows"]}
    return rows["requirement:F-3"]["mapping"]


def test_f3_table_and_json_agree_for_all_22_families():
    table = _f3_table_rows()
    mapping = _f3_json_mapping()
    stimulus_by_family = _split_family_field(mapping["stimulus"]["description"], F3_FAMILIES, ": ")
    positive_by_family = _split_family_field(mapping["positive_control"], F3_FAMILIES, ": ")
    refusal_by_family = _split_family_field(mapping["refusal_control"], F3_FAMILIES, ": ")
    witness_by_family = _split_family_field(mapping["oracle"], F3_FAMILIES, " => ")
    for family in F3_FAMILIES:
        reconstructed_positive = stimulus_by_family[family] + " " + positive_by_family[family]
        assert reconstructed_positive == table[family]["positive"], f"{family}: stimulus/positive_control drifted from the table"
        assert refusal_by_family[family] == table[family]["refusal"], f"{family}: refusal_control drifted from the table"
        assert witness_by_family[family] == table[family]["witness"], f"{family}: oracle witness drifted from the table"


def test_f3_player_faint_and_soft_reset_keep_their_discriminator_wording():
    table = _f3_table_rows()
    mapping = _f3_json_mapping()
    refusal_by_family = _split_family_field(mapping["refusal_control"], F3_FAMILIES, ": ")
    witness_by_family = _split_family_field(mapping["oracle"], F3_FAMILIES, " => ")

    player_faint_refusal_markers = ("write-permit receipt", "W-1", "wBattleMonHP", "writes.lua")
    for marker in player_faint_refusal_markers:
        assert marker in table["player_faint"]["refusal"], f"table player_faint refusal lost {marker!r}"
        assert marker in refusal_by_family["player_faint"], f"JSON player_faint refusal_control lost {marker!r}"

    soft_reset_witness_markers = ("transition", "in-game", "into the reset/title flow")
    for marker in soft_reset_witness_markers:
        assert marker in table["soft_reset"]["witness"], f"table soft_reset witness lost {marker!r}"
        assert marker in witness_by_family["soft_reset"], f"JSON soft_reset oracle lost {marker!r}"
