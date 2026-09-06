"""Extract a baseline RR 4.1 reference without importing SLink runtime code.

This deliberately does not approve a release, patch a ROM, infer form aliases,
or assert that the existing species-name catalog covers every ROM species.
All addresses and anchors apply only to the pinned base ROM below.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import struct
from pathlib import Path
from typing import Any

BASE_SHA256 = "679d112cdfe699c2793d82c7e7999ac9dfca9e222ad5a85d4f8f1e457cd0283f"
ROM_BASE = 0x08000000
ROM_SIZE = 32 * 1024 * 1024
BASE_STATS_POINTER = 0x080001BC
BASE_STATS_ADDRESS = 0x097B98EC
CRY_TABLE_POINTER = 0x08072114
CRY_TABLE_ADDRESS = 0x097C2F6C
SPECIES_NAMES_POINTER = 0x08000144
SPECIES_NAMES_ADDRESS = 0x094042CC
SPECIES_NAMES_END = 0x09407DEC
SPECIES_NAME_STRIDE = 11
EVOLUTION_POINTER = 0x08042F6C
EVOLUTION_ADDRESS = 0x097CD9B0
BOX_POINTER_ADDRESS = 0x09148930
BASE_STATS_STRIDE = 28
EVOLUTION_STRIDE = 128
EVOLUTION_SLOTS = 16
ROM_SPECIES_COUNT = (CRY_TABLE_ADDRESS - BASE_STATS_ADDRESS) // BASE_STATS_STRIDE
ROM_SPECIES_MAX = ROM_SPECIES_COUNT - 1
EGG_ID = 412
EXPECTED_BOX_POINTERS = (
    *(0x02029318 + 1740 * i for i in range(19)),
    *(0x0203CB44 + 1740 * i for i in range(3)),
    *(0x02027434 + 1740 * i for i in range(2)),
    0x02024638,
)
SOURCE_PATHS = {
    "species_names": "data/games/gen3_frlge/rr_species.json",
    "baseline_python": "server/pokemon_data.py",
    "baseline_types": "data/games/gen3_frlge/rr_types.json",
}

# Full instruction snippets or relevant literals, not opcode-presence searches.
ANCHORS = (
    ("species_name_stride", 0x08040FE0, "024f0b206843c319321c04e0"),
    ("species_name_table_literal", 0x08040FEC, "cc424009"),
    ("cry_table_stride_and_literal", 0x08072108, "480040188000014934e000006c2f7c09"),
    ("asset_after_species_names_header", 0x09407DEC, "10000800"),
    ("asset_after_species_names_first_reference", 0x097B6DC4, "ec7d4009"),
    ("asset_after_species_names_second_reference", 0x097B8A84, "ec7d4009"),
    ("gender_stride_and_ratio", 0x0803F794, "0c49d000801a80004018007c"),
    ("gender_table_literal", 0x0803F7C8, "ec987b09"),
    ("evolution_dispatch", 0x08042EC4, "004b184755380909"),
    ("shiny_classifier", 0x0804449C,
     "10b50024020c074b18404240080c424019404a40072a00d80124201c10bc02bc08470000"),
    ("palette_struct_detour", 0x08044180, "004b1847391c3f09"),
    ("palette_struct_xor_threshold", 0x093F1C44,
     "2a0c2d042d0c230c6a4024045a40240c6240c000024b072a00d9024b1818"),
    ("palette_pointer_detour", 0x080440F4, "004b18476d1c3f09"),
    ("palette_pointer_xor_threshold", 0x093F1C84,
     "2a0c2d042d0c230c6a4024045a40240c6240c000044b072a00d9024b"),
    ("expanded_flag_pointer", 0x090B8FB0,
     "0c4b0200c3180c481904090c814203d8d8100a4bc0187047"),
    ("expanded_flag_literals", 0x090B8FE4, "00f7ffffff0f000074b10302ff3f0000"),
    ("default_mode_menu", 0x0904EF08,
     "2b3c10060136ef04092b3310060136ef04092b3410060136ef040916068000000f00b4e6100925250005a4ee0409"),
    ("mgm_clear", 0x0904F203, "2a3210"),
    ("mgm_set", 0x0904F214, "293210"),
    ("hardcore_set_and_mgm", 0x0904F7B4, "2934102b3210070027f80409293210"),
    ("restricted_set", 0x0904F801, "293c10"),
    ("easy_set", 0x0904F816, "293310"),
    ("new_game_mgm_set", 0x0904F827, "293210"),
    ("species_randomizer_set", 0x0904F838, "294009"),
    ("hard_randomizer_set", 0x0904F849, "293a09"),
    ("ability_randomizer_set", 0x0904F85A, "294209"),
    ("learnset_randomizer_set", 0x0904F86B, "294109"),
)


class ReferenceError(ValueError):
    """A source cannot support this pinned reference extraction."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def address_text(address: int) -> str:
    return f"0x{address:08X}"


def read_region(rom: bytes, address: int, size: int) -> bytes:
    """Bounds-check before slicing; Python's truncated slices are not validation."""
    offset = address - ROM_BASE
    if size < 0 or offset < 0 or offset > len(rom) or size > len(rom) - offset:
        raise ReferenceError(f"ROM region out of bounds: {address_text(address)} + {size}")
    return rom[offset:offset + size]


def read_pointer(rom: bytes, address: int, expected: int, table_size: int) -> int:
    target = struct.unpack("<I", read_region(rom, address, 4))[0]
    if target != expected or target % 4:
        raise ReferenceError(f"Unexpected table pointer at {address_text(address)}")
    read_region(rom, target, table_size)
    return target


def validate_rom(rom: bytes) -> dict[str, Any]:
    """Require the exact base before interpreting any gameplay structure."""
    if len(rom) != ROM_SIZE:
        raise ReferenceError(f"Expected a {ROM_SIZE}-byte base RR ROM, got {len(rom)}")
    digest = sha256(rom)
    if digest != BASE_SHA256:
        raise ReferenceError(f"Base RR SHA-256 mismatch: expected {BASE_SHA256}, got {digest}")
    for name, address, expected_hex in ANCHORS:
        expected = bytes.fromhex(expected_hex)
        if read_region(rom, address, len(expected)) != expected:
            raise ReferenceError(f"Anchor mismatch: {name} at {address_text(address)}")
    count = ROM_SPECIES_COUNT
    if ((CRY_TABLE_ADDRESS - BASE_STATS_ADDRESS) % BASE_STATS_STRIDE
            or count * SPECIES_NAME_STRIDE != SPECIES_NAMES_END - SPECIES_NAMES_ADDRESS):
        raise ReferenceError("Independent species-name and BaseStats extents disagree")
    read_pointer(rom, BASE_STATS_POINTER, BASE_STATS_ADDRESS, count * BASE_STATS_STRIDE)
    read_pointer(rom, CRY_TABLE_POINTER, CRY_TABLE_ADDRESS, 12)
    read_pointer(rom, SPECIES_NAMES_POINTER, SPECIES_NAMES_ADDRESS, count * SPECIES_NAME_STRIDE)
    read_pointer(rom, EVOLUTION_POINTER, EVOLUTION_ADDRESS, count * EVOLUTION_STRIDE)
    for sid in range(count):
        raw_name = read_region(rom, SPECIES_NAMES_ADDRESS + sid * SPECIES_NAME_STRIDE,
                               SPECIES_NAME_STRIDE)
        if b"\xff" not in raw_name:
            raise ReferenceError(f"Unterminated ROM species name at ID {sid}")
    for species, expected in ((1, (4, 16, 2, 0)), (2, (4, 36, 3, 0))):
        row = struct.unpack("<4H", read_region(rom, EVOLUTION_ADDRESS + species * 128, 8))
        if row != expected:
            raise ReferenceError("Evolution stride/known-row anchor mismatch")
    return {"sha256": digest, "size_bytes": len(rom)}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReferenceError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load_sources(repo: Path) -> dict[str, Any]:
    """Read data and literal dictionaries only; never execute workspace code."""
    files = {key: (repo / relative).read_bytes() for key, relative in SOURCE_PATHS.items()}
    names = json.loads(files["species_names"].decode("utf-8-sig"), object_pairs_hook=_unique_object)
    if not isinstance(names, dict):
        raise ReferenceError("rr_species.json must contain an ID-to-name object")
    for key, value in names.items():
        if not key.isdecimal() or str(int(key)) != key or not 1 <= int(key) <= ROM_SPECIES_MAX:
            raise ReferenceError(f"Species catalog outside reviewed ID domain: {key!r}")
        if not isinstance(value, str) or not value.strip():
            raise ReferenceError(f"Missing species display name for {key}")
    if not names:
        raise ReferenceError("Species catalog is empty")
    tree = ast.parse(files["baseline_python"].decode("utf-8-sig"))
    literals = {}
    for node in tree.body:
        if (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                and node.target.id in ("GENDER_RATIO", "EVO_FAMILY")):
            literals[node.target.id] = ast.literal_eval(node.value)
    if set(literals) != {"GENDER_RATIO", "EVO_FAMILY"}:
        raise ReferenceError("Baseline GENDER_RATIO/EVO_FAMILY literals not found")
    for name, values in literals.items():
        if not isinstance(values, dict) or any(
            not isinstance(k, int) or not isinstance(v, int) for k, v in values.items()
        ):
            raise ReferenceError(f"Baseline {name} is not an integer mapping")
    types = json.loads(files["baseline_types"].decode("utf-8-sig"), object_pairs_hook=_unique_object)
    if not isinstance(types, dict) or any(
        not k.isdecimal() or not isinstance(v, list) or len(v) != 2
        or any(not isinstance(t, int) for t in v) for k, v in types.items()
    ):
        raise ReferenceError("Baseline RR types are not ID-to-two-types records")
    return {
        "names": {int(k): v for k, v in names.items()},
        "gender": literals["GENDER_RATIO"],
        "families": literals["EVO_FAMILY"],
        "types": {int(k): v for k, v in types.items()},
        "provenance": [{"path": SOURCE_PATHS[k], "sha256": sha256(files[k])}
                       for k in sorted(files)],
    }


def decode_rom_name(raw: bytes) -> tuple[str, list[int]]:
    """Decode observed name bytes; unfamiliar characters stay visible and flagged."""
    punctuation = {0x00: " ", 0x1B: "é", 0xAB: "!", 0xAC: "?", 0xAD: ".",
                   0xAE: "-", 0xB4: "'", 0xB5: "♂", 0xB6: "♀", 0xB7: "¥", 0xB8: ","}
    text, unknown = [], []
    for byte in raw:
        if byte == 0xFF:
            break
        if 0xBB <= byte <= 0xD4:
            text.append(chr(ord("A") + byte - 0xBB))
        elif 0xD5 <= byte <= 0xEE:
            text.append(chr(ord("a") + byte - 0xD5))
        elif 0xA1 <= byte <= 0xAA:
            text.append(str(byte - 0xA1))
        elif byte in punctuation:
            text.append(punctuation[byte])
        else:
            text.append(f"<{byte:02X}>")
            unknown.append(byte)
    return "".join(text), sorted(set(unknown))


def _species_record(rom: bytes, species_id: int, name: str | None) -> dict[str, Any]:
    if not 0 <= species_id <= ROM_SPECIES_MAX:
        raise ReferenceError(f"Species ID outside verified ROM table domain: {species_id}")
    address = BASE_STATS_ADDRESS + species_id * BASE_STATS_STRIDE
    raw = read_region(rom, address, BASE_STATS_STRIDE)
    name_address = SPECIES_NAMES_ADDRESS + species_id * SPECIES_NAME_STRIDE
    rom_name, unknown_chars = decode_rom_name(read_region(rom, name_address, SPECIES_NAME_STRIDE))
    if species_id == 0:
        classification = "none_sentinel"
    elif species_id == EGG_ID:
        classification = "egg_sentinel"
    elif not any(raw):
        classification = "zero_record_placeholder"
    elif name is None:
        classification = "rom_named_record_missing_catalog"
    else:
        classification = "named_record_playability_unverified"
    return {
        "species_id": species_id, "catalog_name": name, "classification": classification,
        "rom_display_name": rom_name, "rom_name_address": address_text(name_address),
        "unmapped_rom_name_bytes": unknown_chars,
        "record_address": address_text(address), "base_stats": list(raw[:6]),
        "gender_ratio": raw[16], "types_rom": list(raw[6:8]),
        "types_canonical": [18 if value == 23 else value for value in raw[6:8]],
    }


def extract_species(rom: bytes, names: dict[int, str]) -> dict[str, Any]:
    records = [_species_record(rom, sid, names.get(sid)) for sid in range(ROM_SPECIES_COUNT)]
    return {
        "reviewed_rom_domain": {"first": 0, "last": ROM_SPECIES_MAX, "count": ROM_SPECIES_COUNT},
        "source_catalog_max": max(names), "records": records,
        "catalog_coverage_gaps": [row["species_id"] for row in records
                                  if row["classification"] == "rom_named_record_missing_catalog"],
        "name_semantics": "Exact ROM display labels can be truncated or shared by forms; no canonical form aliases inferred",
        "type_translation": {"23": 18},
        "type_translation_reason": "RR Fairy byte 23 maps to the existing server Fairy ID 18",
        "gender_rule": "0 male; 254 female; 255 genderless; otherwise PID low byte < ratio is female",
    }


def extract_evolutions(rom: bytes, species: dict[str, Any]) -> dict[str, Any]:
    nodes = {row["species_id"] for row in species["records"]
             if row["classification"] not in ("none_sentinel", "egg_sentinel", "zero_record_placeholder")}
    parent = {sid: sid for sid in nodes}

    def find(sid: int) -> int:
        while parent[sid] != sid:
            parent[sid] = parent[parent[sid]]
            sid = parent[sid]
        return sid

    edges, excluded, gaps = [], [], []
    for sid in sorted(nodes):
        for slot in range(EVOLUTION_SLOTS):
            address = EVOLUTION_ADDRESS + sid * EVOLUTION_STRIDE + slot * 8
            method, parameter, target, auxiliary = struct.unpack("<4H", read_region(rom, address, 8))
            if method == 0:
                if parameter or target or auxiliary:
                    gaps.append({"source_species": sid, "slot": slot,
                                 "reason": "nonzero_fields_on_empty_evolution_method"})
                continue
            row = {"source_species": sid, "target_species": target, "method_id": method,
                   "parameter": parameter, "auxiliary": auxiliary, "slot": slot,
                   "record_address": address_text(address)}
            if method >= 0xFD:
                excluded.append(row)
                continue
            edges.append(row)
            if target not in nodes:
                gaps.append({**row, "reason": "target_outside_reviewed_nonplaceholder_domain"})
                continue
            a, b = find(sid), find(target)
            parent[max(a, b)] = min(a, b)
    components: dict[int, list[int]] = {}
    for sid in sorted(nodes):
        components.setdefault(find(sid), []).append(sid)
    return {
        "table_address": address_text(EVOLUTION_ADDRESS), "species_stride_bytes": EVOLUTION_STRIDE,
        "slots_per_species": EVOLUTION_SLOTS, "entry_stride_bytes": 8,
        "permanent_method_range": [1, 0xFC], "permanent_edges": edges,
        "excluded_methods_0xfd_and_above": excluded, "coverage_gaps": gaps,
        "families": [{"component_id": key, "members": values,
                      "closed_within_reviewed_evolution_domain": not any(
                          gap["source_species"] in values for gap in gaps)}
                     for key, values in sorted(components.items())],
        "family_semantics": "Undirected permanent-evolution components; ID is minimum member, not a biological base form",
        "form_aliases": [], "form_alias_policy": "No inferred aliases; explicit reviewed policy still required",
    }


def extract_boxes(rom: bytes) -> dict[str, Any]:
    pointers = struct.unpack("<25I", read_region(rom, BOX_POINTER_ADDRESS, 25 * 4))
    if pointers != EXPECTED_BOX_POINTERS:
        raise ReferenceError("Compressed box pointer table differs from the reviewed RR layout")
    intervals = []
    rows = []
    for index, address in enumerate(pointers):
        end = address + 30 * 58
        if not 0x02000000 <= address < end <= 0x02040000:
            raise ReferenceError(f"Compressed box {index} is outside EWRAM")
        if any(address < other_end and other_start < end for other_start, other_end in intervals):
            raise ReferenceError(f"Compressed box {index} overlaps another box")
        intervals.append((address, end))
        rows.append({"box_index_zero_based": index, "data_address": address_text(address),
                     "end_address_exclusive": address_text(end),
                     "pointer_address": address_text(BOX_POINTER_ADDRESS + index * 4)})
    return {"table_address": address_text(BOX_POINTER_ADDRESS), "box_count": 25,
            "slots_per_box": 30, "compressed_mon_bytes": 58, "boxes": rows,
            "validation_limit": "Pointer identity, bounds and pairwise box nonoverlap; not ownership safety against every other RR allocation"}


def mode_evidence() -> dict[str, Any]:
    flags = (
        ("minimal_grinding", 0x1032, 0x0904F214), ("easy", 0x1033, 0x0904F816),
        ("hardcore", 0x1034, 0x0904F7B4), ("restricted", 0x103C, 0x0904F801),
        ("species_randomizer", 0x0940, 0x0904F838),
        ("learnset_randomizer", 0x0941, 0x0904F86B),
        ("ability_randomizer", 0x0942, 0x0904F85A),
        ("hard_mode_randomizer", 0x093A, 0x0904F849),
    )
    return {
        "flags": [{"name": name, "flag_id": flag,
                   "ram_byte": address_text(0x0203B174 + ((flag - 0x900) >> 3)),
                   "bit_mask": 1 << (flag & 7), "set_script_address": address_text(address)}
                  for name, flag, address in flags],
        "flag_pointer_function": "0x090B8FB0", "expanded_flag_range": [0x900, 0x18FF],
        "formula": "byte = 0x0203B174 + ((flag - 0x0900) >> 3); mask = 1 << (flag & 7)",
        "default_mode_requires_clear": ["easy", "hardcore", "restricted"],
        "default_menu_evidence": "0x0904EF08",
        "internal_randomizer_flags_require_clear": [name for name, _, _ in flags if "randomizer" in name],
        "mgm_states_supported_by_planned_release": [False, True],
        "planned_mode_pairings": [[False, False], [True, True]],
        "mgm_prompt_address": "0x0910DD7F", "mgm_enabled_message": "0x0910E400",
        "mgm_disabled_message": "0x0910E329", "mgm_clear_script": "0x0904F203",
        "runtime_values_observed": False,
        "note": "Evidence for a future reader; this generator never reads a save, running emulator, or current mode",
    }


def comparison_report(species: dict[str, Any], evolutions: dict[str, Any], sources: dict[str, Any]) -> dict[str, Any]:
    gender, types, order, missing_types = [], [], [], []
    for row in species["records"]:
        sid = row["species_id"]
        if sid not in sources["names"]:
            continue
        identity = {"species_id": sid, "catalog_name": row["catalog_name"]}
        prior = sources["gender"].get(sid, 127)
        if prior != row["gender_ratio"]:
            gender.append({**identity, "rom_ratio": row["gender_ratio"], "baseline_ratio": prior,
                           "baseline_used_default": sid not in sources["gender"]})
        prior_types = sources["types"].get(sid)
        if prior_types is None:
            missing_types.append(identity)
        elif set(prior_types) != set(row["types_canonical"]):
            types.append({**identity, "rom_types_canonical": row["types_canonical"], "baseline_types": prior_types})
        elif prior_types != row["types_canonical"]:
            order.append({**identity, "rom_types_canonical": row["types_canonical"], "baseline_types": prior_types})
    family_edges = []
    for edge in evolutions["permanent_edges"]:
        a, b = edge["source_species"], edge["target_species"]
        fa, fb = sources["families"].get(a, a), sources["families"].get(b, b)
        if fa != fb:
            family_edges.append({**edge, "source_name": sources["names"].get(a),
                                 "target_name": sources["names"].get(b),
                                 "baseline_source_family": fa, "baseline_target_family": fb})
    return {
        "status": "baseline_comparison_only_not_release_approval",
        "counts": {"named_species_compared": len(sources["names"]), "gender_mismatches": len(gender),
                   "type_set_mismatches": len(types), "type_order_only_mismatches": len(order),
                   "missing_baseline_types": len(missing_types), "evolution_rows_split_by_baseline_family": len(family_edges)},
        "gender_mismatches": gender, "type_set_mismatches": types,
        "type_order_only_mismatches": order, "missing_baseline_types": missing_types,
        "evolution_rows_split_by_baseline_family": family_edges,
        "limitations": ["Counts compare named catalog records, excluding the unnamed Egg sentinel",
                        "Raw evolution rows can repeat the same species edge for different methods",
                        "A family comparison does not decide regional or temporary-form aliases",
                        "Names are copied from the input catalog, not independently verified against ROM text"],
    }


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def build_artifacts(rom: bytes, sources: dict[str, Any]) -> dict[str, bytes]:
    """Pure API: validated ROM and read-only source data -> deterministic JSON bytes."""
    base = validate_rom(rom)
    species = extract_species(rom, sources["names"])
    evolutions = extract_evolutions(rom, species)
    data = {
        "rr41_species.json": species,
        "rr41_evolution_families.json": evolutions,
        "rr41_compressed_boxes.json": extract_boxes(rom),
        "rr41_modes.json": mode_evidence(),
        "rr41_comparison.json": comparison_report(species, evolutions, sources),
    }
    artifacts = {name: canonical_bytes(value) for name, value in data.items()}
    manifest = {
        "schema_version": 2, "reference_id": "rr41-base-rom-tables-v2",
        "status": "baseline_only_not_release_approval", "rom": base,
        "source_files": sources["provenance"],
        "anchors": [{"name": name, "address": address_text(address), "expected_hex": expected}
                    for name, address, expected in ANCHORS],
        "tables": {"base_stats_pointer": address_text(BASE_STATS_POINTER),
                   "base_stats_address": address_text(BASE_STATS_ADDRESS),
                   "base_stats_stride_bytes": BASE_STATS_STRIDE,
                   "evolution_pointer": address_text(EVOLUTION_POINTER),
                   "evolution_address": address_text(EVOLUTION_ADDRESS),
                   "evolution_species_stride_bytes": EVOLUTION_STRIDE,
                   "reviewed_rom_domain_max": ROM_SPECIES_MAX,
                   "species_count_including_sentinels": ROM_SPECIES_COUNT,
                   "base_stats_end_exclusive": address_text(CRY_TABLE_ADDRESS),
                   "following_cry_table_pointer": address_text(CRY_TABLE_POINTER),
                   "species_names_pointer": address_text(SPECIES_NAMES_POINTER),
                   "species_names_address": address_text(SPECIES_NAMES_ADDRESS),
                   "species_names_end_exclusive": address_text(SPECIES_NAMES_END),
                   "species_name_stride_bytes": SPECIES_NAME_STRIDE},
        "species_extent_evidence_document": "docs/rr_reference/SPECIES_EXTENT.md",
        "shiny": {"xor_threshold_exclusive": 8,
                  "classifier_compare_address": "0x080444B0",
                  "active_palette_compare_addresses": ["0x093F1C5A", "0x093F1C9A"],
                  "generation_odds_are_not_classifier_threshold": True},
        "release_policy_context": {"companion_required_both_players": True,
                                   "exact_companion_build_validation": "not_performed_by_base_reference_generator",
                                   "disconnect_policy": "pause_until_paired_reconciliation"},
        "coverage_gaps": [
            "Every ROM record is bounded independently by the species-name table/next asset and BaseStats/cry-table boundaries",
            "Missing canonical catalog names remain coverage gaps even when a ROM display label is available",
            "ROM labels can be shared by forms or truncated; do not guess expanded identities from those labels",
            "Missing catalog IDs within the reviewed domain retain explicit sentinel/placeholder classification",
            "No form aliases or playability inferred from display names",
            "Permanent evolution method numbers/parameters are preserved; symbolic method semantics require reviewed RR definitions",
            "No game-state, save compatibility, companion execution, or full release validation performed",
        ],
        "files": [{"name": name, "sha256": sha256(content), "size_bytes": len(content)}
                  for name, content in sorted(artifacts.items())],
    }
    artifacts["rr41_reference_manifest.json"] = canonical_bytes(manifest)
    return artifacts


def write_artifacts(artifacts: dict[str, bytes], output_dir: Path, repo: Path, rom_path: Path) -> None:
    """Write explicit evidence outputs, never runtime data, source inputs, or a ROM."""
    output = output_dir.resolve()
    repository = repo.resolve()
    evidence_root = (repository / "docs" / "rr_reference").resolve()
    if ((output == repository or repository in output.parents)
            and output != evidence_root and evidence_root not in output.parents):
        raise ReferenceError("Output directory must be outside the repository or under docs/rr_reference")
    destinations = [output / name for name in artifacts]
    if any(path.resolve() == rom_path.resolve() for path in destinations):
        raise ReferenceError("An output would overwrite the input ROM")
    if any(path.is_symlink() for path in destinations):
        raise ReferenceError("Refusing a symlink output")
    output.mkdir(parents=True, exist_ok=True)
    for name, content in sorted(artifacts.items()):
        destination = output / name
        destination.write_bytes(content)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", required=True, type=Path)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        rom = args.rom.read_bytes()
        validate_rom(rom)  # Wrong-ROM requests fail before reading workspace sources.
        artifacts = build_artifacts(rom, load_sources(args.repo))
        write_artifacts(artifacts, args.output_dir, args.repo, args.rom)
    except (OSError, ValueError, SyntaxError) as error:
        parser.exit(2, f"RR reference generation failed: {error}\n")
    summary = json.loads(artifacts["rr41_comparison.json"])["counts"]
    print(json.dumps({"status": "baseline_only_not_release_approval", "files": len(artifacts),
                      "comparison_counts": summary}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
