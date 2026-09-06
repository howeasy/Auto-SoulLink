"""Build an inactive RR catalog, refusing unresolved taxonomy in final output."""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
from typing import Any

from tools.rr import reference

SCHEMA = "slink-rr41-catalog-v1"
POLICY = "rr41-cosmetic-shared-regional-separate-v1"
REVIEW_PATH = "data/games/gen3_frlge/rr_catalog_review.json"
TRANSFORM_SHA256 = "f157db79818ad0e9523e0fae48fd7caf57a3b54f9cc9d514e9f03ec57b417795"
REGIONS = {"standard", "alola", "galar", "hisui", "paldea", "sevii"}


class CatalogError(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CatalogError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def integer(value, low=0, high=1375):
    return type(value) is int and low <= value <= high


class Components:
    def __init__(self, nodes):
        self.parent = {node: node for node in nodes}

    def find(self, node):
        if node not in self.parent:
            raise CatalogError(f"taxonomy references non-species ID {node}")
        while node != self.parent[node]:
            self.parent[node] = self.parent[self.parent[node]]
            node = self.parent[node]
        return node

    def union(self, left, right):
        a, b = self.find(left), self.find(right)
        self.parent[max(a, b)] = min(a, b)  # Internal graph key only, never a family ID.


def partition(records, permanent, transforms, review):
    """Separate the physical graph, form equivalence and regional family policy."""
    nodes = {row["species_id"] for row in records if row["kind"] == "species"}
    regions = dict.fromkeys(nodes, "standard")
    unknowns = []
    unknown_nodes = set()
    for item in review["unresolved"]:
        sid = item["species_id"]
        if not integer(sid, 1) or sid not in nodes or sid in unknown_nodes or not item["reason"]:
            raise CatalogError("invalid or duplicate unresolved taxonomy record")
        unknown_nodes.add(sid)
        regions[sid] = None
        unknowns.append({"kind": "taxonomy", **item})
    assigned = set()
    for region, members in review["regional_groups"].items():
        if region not in REGIONS - {"standard"}:
            raise CatalogError(f"unknown region: {region}")
        for sid in members:
            if not integer(sid, 1) or sid not in nodes or sid in assigned or sid in unknown_nodes:
                raise CatalogError("duplicate, unknown or unresolved regional member")
            assigned.add(sid)
            regions[sid] = region
    aliases = Components(nodes)
    alias_rows, preferred = [], []
    explicit_member = set()
    for group in review["cosmetic_groups"]:
        base = group["base"]
        if not integer(base, 1) or base not in nodes or not group["evidence"]:
            raise CatalogError("invalid cosmetic base/evidence")
        preferred.append(base)
        for member in group["members"]:
            if not integer(member, 1) or member == base or member in explicit_member:
                raise CatalogError("duplicate or invalid cosmetic member")
            explicit_member.add(member)
            if member not in nodes or regions[base] is None or regions.get(member) != regions[base]:
                raise CatalogError("cosmetic alias crosses a regional or unresolved boundary")
            aliases.union(base, member)
            alias_rows.append(
                {
                    "base": base,
                    "member": member,
                    "kind": "cosmetic_or_battle",
                    "evidence": group["evidence"],
                }
            )
    # The full143 exact rows were reviewed independently and pinned as a set.
    # A changed reference table cannot silently add a transformation-family union.
    if reference.sha256(canonical(transforms)) != TRANSFORM_SHA256:
        raise CatalogError("native transformation rows differ from the reviewed set")
    for edge in transforms:
        a, b = edge["source_species"], edge["target_species"]
        if edge["method_id"] != 254 or regions.get(a) is None or regions.get(a) != regions.get(b):
            raise CatalogError("native transformation crosses an unreviewed regional boundary")
        aliases.union(a, b)
        if edge["parameter"]:
            preferred.append(a)
            alias_rows.append(
                {
                    "base": a,
                    "member": b,
                    "kind": "native_method254",
                    "evidence": edge["record_address"],
                }
            )

    cuts = set()
    for pair in review["shared_precursor_cuts"]:
        if len(pair) != 2 or not all(integer(value, 1) for value in pair) or tuple(pair) in cuts:
            raise CatalogError("invalid or duplicate shared-precursor cut")
        cuts.add(tuple(pair))
    seen_cuts = set()
    physical, incoming = [], set()
    families = Components(nodes)
    for row in alias_rows:
        families.union(row["base"], row["member"])
    for edge in permanent:
        a, b = edge["source_species"], edge["target_species"]
        if a not in nodes or b not in nodes:
            raise CatalogError("physical evolution references an invalid species")
        if regions[a] is None or regions[b] is None:
            disposition = "unresolved"
            unknowns.append(
                {"kind": "edge", "source": a, "target": b, "reason": "unresolved taxonomy endpoint"}
            )
        elif regions[a] != regions[b]:
            disposition = "regional_cut"
            if (a, b) not in cuts:
                raise CatalogError(f"unreviewed regional evolution cut {a}->{b}")
            seen_cuts.add((a, b))
        else:
            if (a, b) in cuts:
                raise CatalogError("reviewed regional cut now has equal regions")
            disposition = "family_edge"
            families.union(a, b)
            if aliases.find(a) != aliases.find(b):
                incoming.add(aliases.find(b))
        physical.append({**edge, "family_disposition": disposition})
    if cuts != seen_cuts:
        raise CatalogError("review includes shared-precursor cuts absent from the ROM")

    # Equal custom dex numbers are an AUDIT surface, not a family union rule.
    # The special collision0 contains unrelated records and is not a form group.
    collisions = {tuple(sorted(pair)) for pair in review["independent_dex_collisions"]}
    dex_groups = {}
    for row in records:
        if row["species_id"] in nodes and row["rom_dex_group"]:
            dex_groups.setdefault(row["rom_dex_group"], []).append(row["species_id"])
    for group in dex_groups.values():
        for a, b in itertools.combinations(group, 2):
            if regions[a] is None or regions[b] is None or regions[a] != regions[b]:
                continue
            if aliases.find(a) != aliases.find(b) and (a, b) not in collisions:
                unknowns.append(
                    {
                        "kind": "form_group",
                        "species_ids": [a, b],
                        "reason": "shared ROM dex group lacks an explicit form alias or independent-species exception",
                    }
                )

    groups = {}
    for sid in sorted(nodes):
        groups.setdefault(families.find(sid), []).append(sid)
    overrides = {}
    for row in review["family_root_overrides"]:
        members = tuple(sorted(row["members"]))
        if members in overrides or row["root"] not in members or not row["evidence"]:
            raise CatalogError("invalid family root override")
        overrides[members] = row["root"]
    output, by_species = [], {}
    used_overrides = set()
    for members in groups.values():
        if any(sid in unknown_nodes for sid in members):
            continue
        roots = {aliases.find(sid) for sid in members} - incoming
        candidates = [sid for sid in members if aliases.find(sid) in roots]
        chosen = None
        if len(roots) == 1:
            preferences = [sid for sid in preferred if sid in candidates]
            # An explicit cosmetic base supersedes its own alternate native form.
            # Multiple unrelated preferences require review rather than min(ID).
            if preferences:
                choices = {sid for sid in preferences if sid not in explicit_member}
                if len(choices) == 1:
                    chosen = next(iter(choices))
            elif len(candidates) == 1:
                chosen = candidates[0]
        key = tuple(members)
        if key in overrides:
            chosen = overrides[key]
            used_overrides.add(key)
        if chosen is None:
            unknowns.append(
                {
                    "kind": "family_root",
                    "species_ids": members,
                    "root_candidates": candidates,
                    "reason": "no unique reviewed lineage root",
                }
            )
            continue
        for sid in members:
            by_species[sid] = chosen
        output.append(
            {
                "family_id": chosen,
                "root_species_id": chosen,
                "region": regions[chosen],
                "members": members,
            }
        )
    if used_overrides != set(overrides):
        raise CatalogError("unused family root override")
    return (
        regions,
        by_species,
        sorted(output, key=lambda row: row["family_id"]),
        physical,
        alias_rows,
        unknowns,
    )


def build_catalog(rom, sources, review, *, final=True):
    reference.validate_rom(rom)
    if review.get("schema") != "slink-rr41-taxonomy-review-v1" or review.get("policy_id") != POLICY:
        raise CatalogError("unsupported taxonomy review or policy")
    if review["evidence"]["base_rom_sha256"] != reference.BASE_SHA256:
        raise CatalogError("taxonomy review is not bound to the pinned ROM")
    names = dict(sources["names"])
    for key, value in review["name_overrides"].items():
        if (
            not key.isdecimal()
            or str(int(key)) != key
            or not integer(int(key), 1)
            or not isinstance(value, str)
            or not value.strip()
        ):
            raise CatalogError("invalid reviewed name override")
        names[int(key)] = value
    species = reference.extract_species(rom, names)
    evolution = reference.extract_evolutions(rom, species)
    if evolution["coverage_gaps"] or species["catalog_coverage_gaps"]:
        raise CatalogError("ROM species/evolution evidence has coverage gaps")
    # Verify the actual custom-dex function before using its table as an audit.
    expected = bytes.fromhex("00b50004010c002908d00348013949000918088803e00000f0188209")
    if reference.read_region(rom, 0x08043298, len(expected)) != expected:
        raise CatalogError("custom dex lookup anchor differs")
    records = []
    kinds = {
        "none_sentinel": "none",
        "egg_sentinel": "egg",
        "zero_record_placeholder": "placeholder",
    }
    for row in species["records"]:
        sid = row["species_id"]
        records.append(
            {
                "species_id": sid,
                "name": row["catalog_name"],
                "rom_name": row["rom_display_name"],
                "kind": kinds.get(row["classification"], "species"),
                "gender_ratio": row["gender_ratio"],
                "types_rom": row["types_rom"],
                "types": row["types_canonical"],
                "base_stats": row["base_stats"],
                "rom_dex_group": int.from_bytes(
                    reference.read_region(rom, 0x098218F0 + (sid - 1) * 2, 2), "little"
                )
                if sid
                else None,
                "note": review["form_notes"].get(str(sid)),
            }
        )
    regions, family_ids, families, physical, aliases, unknowns = partition(
        records, evolution["permanent_edges"], evolution["excluded_methods_0xfd_and_above"], review
    )
    changes = []
    for row in records:
        sid = row["species_id"]
        row["region"], row["family_id"] = regions.get(sid), family_ids.get(sid)
        if row["kind"] != "species":
            continue
        before = {
            "name": sources["names"].get(sid),
            "family_id": sources["families"].get(sid, sid),
            "gender_ratio": sources["gender"].get(sid, 127),
            "types": sources["types"].get(sid),
        }
        after = {key: row[key] for key in before}
        changed = [key for key in before if before[key] != after[key]]
        if changed:
            changes.append(
                {"species_id": sid, "changed_fields": changed, "before": before, "after": after}
            )
    unknowns = sorted(unknowns, key=lambda row: canonical(row))
    if final and unknowns:
        raise CatalogError(
            f"final catalog refused: {len(unknowns)} unresolved taxonomy/root records"
        )
    result = {
        "schema": SCHEMA,
        "policy_id": POLICY,
        "readiness": "inactive_catalog"
        if final
        else "review_blocked"
        if unknowns
        else "review_only",
        "activation": "explicit version migration required; never selected automatically",
        "base_rom_sha256": reference.BASE_SHA256,
        "domain": [0, 1375],
        "review_sha256": reference.sha256(canonical(review)),
        "records": records,
        "families": families,
        "source_provenance": sources["provenance"],
        "physical_evolutions": physical,
        "form_aliases": aliases,
        "native_transformations": evolution["excluded_methods_0xfd_and_above"],
        "unknowns": unknowns,
        "legacy_changes": changes,
        "migration_rule": "Do not reinterpret existing link/capture/death history. Re-evaluate current eligibility under explicit versioned migration.",
    }
    result["catalog_id"] = reference.sha256(canonical(result))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--rom", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--review-only",
        action="store_true",
        help="Write blocked review evidence; never a loadable final catalog",
    )
    args = parser.parse_args(argv)
    try:
        review = json.loads(
            (args.repo / REVIEW_PATH).read_text(encoding="utf-8"), object_pairs_hook=unique_object
        )
        result = build_catalog(
            args.rom.read_bytes(),
            reference.load_sources(args.repo),
            review,
            final=not args.review_only,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n"
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"RR catalog refused: {exc}\n")
    print(
        json.dumps(
            {
                "status": result["readiness"],
                "unknowns": len(result["unknowns"]),
                "catalog_id": result["catalog_id"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
