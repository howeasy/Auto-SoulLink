"""Strict inactive RR data reader. No default catalog or existing-run selection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType

SCHEMA = "slink-rr41-catalog-v1"
POLICY_ID = "rr41-cosmetic-shared-regional-separate-v1"
BASE_ROM_SHA256 = "679d112cdfe699c2793d82c7e7999ac9dfca9e222ad5a85d4f8f1e457cd0283f"
PERMANENT_SHA256 = "adb582338fa2af0a1d3b6e5683e71c0672b22a8dfea3061b4f76c2c37c56fb0c"
TRANSFORM_SHA256 = "f157db79818ad0e9523e0fae48fd7caf57a3b54f9cc9d514e9f03ec57b417795"
REGIONS = {"standard", "alola", "galar", "hisui", "paldea", "sevii"}
TYPE_IDS = set(range(9)) | set(range(10, 19))
PLACEHOLDERS = set(range(252, 277)) | {920}
FIELDS = {
    "schema",
    "policy_id",
    "readiness",
    "activation",
    "base_rom_sha256",
    "domain",
    "review_sha256",
    "source_provenance",
    "records",
    "families",
    "physical_evolutions",
    "form_aliases",
    "native_transformations",
    "unknowns",
    "legacy_changes",
    "migration_rule",
    "catalog_id",
}


class CatalogError(ValueError):
    pass


def _integer(value, low, high):
    return type(value) is int and low <= value <= high


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CatalogError(f"duplicate catalog key: {key}")
        result[key] = value
    return result


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _invalid_constant(value):
    raise CatalogError(f"invalid JSON constant: {value}")


@dataclass(frozen=True)
class Species:
    species_id: int
    name: str
    family_id: int
    region: str
    gender_ratio: int
    types: tuple[int, int]
    base_stats: tuple[int, ...]


class RRCatalog:
    """A caller must supply an explicitly selected payload and its expected hash."""

    def __init__(self, payload: bytes, *, expected_sha256: str, expected_policy_id: str):
        if (
            not isinstance(payload, bytes)
            or not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
        ):
            raise CatalogError("catalog bytes and explicit expected SHA-256 are required")
        if hashlib.sha256(payload).hexdigest() != expected_sha256:
            raise CatalogError("catalog payload hash differs from the selected revision")
        try:
            data = json.loads(payload, object_pairs_hook=_unique, parse_constant=_invalid_constant)
        except (ValueError, UnicodeError) as exc:
            raise CatalogError(f"invalid catalog JSON: {exc}") from exc
        if not isinstance(data, dict) or data.get("schema") != SCHEMA:
            raise CatalogError("unsupported catalog schema")
        if set(data) != FIELDS:
            raise CatalogError("missing or unknown catalog fields")
        if expected_policy_id != POLICY_ID or data.get("policy_id") != expected_policy_id:
            raise CatalogError("catalog policy revision differs from selection")
        if data.get("readiness") != "inactive_catalog" or data.get("unknowns") != []:
            raise CatalogError("incomplete review catalog cannot be selected")
        if (
            data.get("base_rom_sha256") != BASE_ROM_SHA256
            or data.get("domain") != [0, 1375]
            or any(type(value) is not int for value in data["domain"])
        ):
            raise CatalogError("catalog is not bound to the supported RR domain")
        claimed = data.get("catalog_id")
        body = {key: value for key, value in data.items() if key != "catalog_id"}
        if not isinstance(claimed, str) or hashlib.sha256(_canonical(body)).hexdigest() != claimed:
            raise CatalogError("catalog content identity mismatch")
        records = data.get("records")
        if not isinstance(records, list) or len(records) != 1376:
            raise CatalogError("catalog does not cover the complete ROM record domain")
        species = {}
        for sid, row in enumerate(records):
            if (
                not isinstance(row, dict)
                or type(row.get("species_id")) is not int
                or row["species_id"] != sid
            ):
                raise CatalogError("duplicate, unordered or missing species record")
            kind = row.get("kind")
            expected_kind = (
                "none"
                if sid == 0
                else "egg"
                if sid == 412
                else "placeholder"
                if sid in PLACEHOLDERS
                else "species"
            )
            if kind != expected_kind:
                raise CatalogError("record kind differs from the pinned RR domain")
            if kind in {"none", "egg", "placeholder"}:
                if row.get("family_id") is not None or row.get("region") is not None:
                    raise CatalogError("non-species record declares a family")
                if kind == "none" and sid != 0 or kind == "egg" and sid != 412:
                    raise CatalogError("sentinel identity mismatch")
                if kind == "placeholder" and (sid in {0, 412} or row.get("base_stats") != [0] * 6):
                    raise CatalogError("invalid placeholder record")
                continue
            if kind != "species" or sid in {0, 412}:
                raise CatalogError("invalid species kind")
            if not isinstance(row.get("name"), str) or not row["name"].strip():
                raise CatalogError("species name is missing")
            if row.get("region") not in REGIONS or not _integer(row.get("family_id"), 1, 1375):
                raise CatalogError("species family/region is missing")
            if not _integer(row.get("gender_ratio"), 0, 255):
                raise CatalogError("invalid gender ratio")
            types = row.get("types")
            raw_types = row.get("types_rom")
            if (
                not isinstance(types, list)
                or len(types) != 2
                or any(type(t) is not int or t not in TYPE_IDS for t in types)
            ):
                raise CatalogError("invalid canonical species types")
            if (
                not isinstance(raw_types, list)
                or len(raw_types) != 2
                or any(type(t) is not int or t not in (TYPE_IDS - {18}) | {23} for t in raw_types)
                or [18 if t == 23 else t for t in raw_types] != types
            ):
                raise CatalogError("type translation is not the reviewed RR Fairy mapping")
            stats = row.get("base_stats")
            if (
                not isinstance(stats, list)
                or len(stats) != 6
                or any(not _integer(value, 0, 255) for value in stats)
                or not stats[0]
            ):
                raise CatalogError("invalid species base stats")
            species[sid] = Species(
                sid,
                row["name"],
                row["family_id"],
                row["region"],
                row["gender_ratio"],
                tuple(types),
                tuple(stats),
            )
        listed_families, membership = set(), set()
        if not isinstance(data.get("families"), list):
            raise CatalogError("families are missing")
        for family in data["families"]:
            if not isinstance(family, dict):
                raise CatalogError("invalid family record")
            root = family.get("family_id")
            members = family.get("members")
            if (
                not _integer(root, 1, 1375)
                or root in listed_families
                or type(family.get("root_species_id")) is not int
                or family["root_species_id"] != root
            ):
                raise CatalogError("invalid or duplicate family root")
            if (
                not isinstance(members, list)
                or not members
                or any(not _integer(sid, 1, 1375) for sid in members)
                or members != sorted(set(members))
                or root not in members
            ):
                raise CatalogError("family members are invalid")
            listed_families.add(root)
            for sid in members:
                if (
                    sid in membership
                    or sid not in species
                    or species[sid].family_id != root
                    or species[sid].region != family.get("region")
                ):
                    raise CatalogError("family membership or regional boundary mismatch")
                membership.add(sid)
        if membership != set(species):
            raise CatalogError("families do not cover all species")
        physical = data.get("physical_evolutions")
        transforms = data.get("native_transformations")
        if not isinstance(physical, list) or not isinstance(transforms, list):
            raise CatalogError("physical evolution evidence is missing")
        facts = []
        for edge in physical:
            if not isinstance(edge, dict) or "family_disposition" not in edge:
                raise CatalogError("physical evolution disposition is missing")
            facts.append({key: value for key, value in edge.items() if key != "family_disposition"})
        if (
            hashlib.sha256(_canonical(facts)).hexdigest() != PERMANENT_SHA256
            or hashlib.sha256(_canonical(transforms)).hexdigest() != TRANSFORM_SHA256
        ):
            raise CatalogError("physical evolution facts differ from the pinned ROM")
        for edge in physical + transforms:
            left, right = species[edge["source_species"]], species[edge["target_species"]]
            disposition = edge.get("family_disposition", "family_edge")
            if disposition == "family_edge":
                if left.family_id != right.family_id or left.region != right.region:
                    raise CatalogError("retained evolution/form edge crosses a family boundary")
            elif disposition == "regional_cut":
                if left.region == right.region or left.family_id == right.family_id:
                    raise CatalogError("regional evolution cut is not separated")
            else:
                raise CatalogError("unresolved evolution disposition in final catalog")
        if not isinstance(data.get("form_aliases"), list):
            raise CatalogError("form alias evidence is missing")
        for alias in data["form_aliases"]:
            if (
                not isinstance(alias, dict)
                or not _integer(alias.get("base"), 1, 1375)
                or not _integer(alias.get("member"), 1, 1375)
                or alias["base"] not in species
                or alias["member"] not in species
            ):
                raise CatalogError("invalid form alias")
            left, right = species[alias["base"]], species[alias["member"]]
            if left.region != right.region or left.family_id != right.family_id:
                raise CatalogError("form alias crosses a regional family boundary")
            if (
                alias.get("kind") not in {"cosmetic_or_battle", "native_method254"}
                or not isinstance(alias.get("evidence"), str)
                or not alias["evidence"]
            ):
                raise CatalogError("unreviewed form alias")
        self.catalog_id = claimed
        self.policy_id = expected_policy_id
        self._species = MappingProxyType(species)

    def species(self, species_id: int) -> Species:
        if not _integer(species_id, 1, 1375) or species_id not in self._species:
            raise CatalogError("unknown, sentinel or placeholder RR species")
        return self._species[species_id]

    def family_id(self, species_id: int) -> int:
        return self.species(species_id).family_id

    def gender(self, species_id: int, personality: int) -> str:
        if not _integer(personality, 0, 0xFFFFFFFF):
            raise CatalogError("personality must be an unsigned32-bit integer")
        ratio = self.species(species_id).gender_ratio
        if ratio == 255:
            return "genderless"
        if ratio == 254:
            return "female"
        return "female" if (personality & 255) < ratio else "male"
