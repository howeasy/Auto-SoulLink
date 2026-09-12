"""Installed canonical clean/companion identities for durable RBY admission only."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from server.gen1_admission import (
    CONTRACT_SCHEMA,
    VARIANTS,
    AdmissionError,
    cartridge_metadata,
    clean_profiles,
)
from server.protocol import canonical_json, digest

CATALOG = Path(__file__).resolve().parents[1] / "data/games/gen1_rby/companion_profiles.json"


def companion_profiles():
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    if (
        set(catalog) != {"schema", "profiles"}
        or catalog["schema"] != "gen1-rby-canonical-companion-catalog-v1"
        or set(catalog["profiles"]) != VARIANTS
    ):
        raise AdmissionError("invalid installed canonical companion catalog")
    clean = clean_profiles()
    for variant, profile in catalog["profiles"].items():
        if not isinstance(profile, dict):
            raise AdmissionError("invalid installed companion profile")
        manifest = profile.get("manifest")
        capabilities = {"panel": variant != "yellow", "sfx": False, "pc_trade": True}
        if (
            profile.get("schema") != "gen1-rby-canonical-companion-content-v1"
            or profile.get("variant") != variant
            or digest({k: v for k, v in profile.items() if k != "content_profile_hash"})
            != profile.get("content_profile_hash")
            or not isinstance(manifest, dict)
            or digest(manifest) != profile.get("manifest_sha256")
            or manifest.get("schema") != "gen1-native-trade-build-v1"
            or manifest.get("runtime_ready") is not False
            or manifest.get("test_probe") is not None
            or manifest.get("variant") != variant
            or manifest.get("final_sha1") != profile.get("final_rom_sha1")
            or profile.get("base_sha1") != clean[variant]["final_rom_sha1"]
            or profile.get("source_commit") != clean[variant]["source_commit"]
            or profile.get("party_codec") != clean[variant]["party_codec"]
            or profile.get("codec_data_sha256") != clean[variant]["codec_data_sha256"]
            or type(profile.get("patch_version")) is not int
            or profile["patch_version"] != 3
            or canonical_json(profile.get("capabilities")) != canonical_json(capabilities)
            or profile.get("provenance") != "canonical-whole-rom-plus-checked-companion"
        ):
            raise AdmissionError("installed companion identity, layout or provenance differs")
        companion = manifest.get("companion", {})
        if (
            companion.get("schema") != "gen1-canonical-companion-v1"
            or companion.get("runtime_ready") is not False
            or companion.get("final_sha256") != profile.get("rom_sha256")
            or companion.get("base_sha256") != clean[variant]["rom_sha256"]
            or companion.get("kind")
            != ("yellow-trade-only" if variant == "yellow" else "rb-panel-trade")
            or (companion.get("panel") is None) != (variant == "yellow")
        ):
            raise AdmissionError("installed companion composition differs")
    return catalog["profiles"]


def validate_runtime_contract(contract):
    if (
        not isinstance(contract, dict)
        or set(contract) != {"schema", "players"}
        or contract["schema"] != CONTRACT_SCHEMA
        or not isinstance(contract["players"], dict)
        or set(contract["players"]) != {"a", "b"}
    ):
        raise AdmissionError("complete canonical RBY runtime contract required")
    clean, companions = clean_profiles(), companion_profiles()
    for player, expected in contract["players"].items():
        if not isinstance(expected, dict) or expected.get("variant") not in VARIANTS:
            raise AdmissionError("invalid runtime cartridge for player " + player)
        variant = expected["variant"]
        choices = (cartridge_metadata(clean[variant]), cartridge_metadata(companions[variant]))
        if not any(canonical_json(expected) == canonical_json(value) for value in choices):
            raise AdmissionError("unsupported or unverified runtime cartridge provenance")
    return copy.deepcopy(contract["players"])


def contract_from_files(paths):
    """Explicit prepared runtime input; never a fallback for legacy/UPR admission."""
    if not isinstance(paths, dict) or set(paths) != {"a", "b"}:
        raise AdmissionError("both owned local cartridge files required")
    profiles = [*clean_profiles().values(), *companion_profiles().values()]
    players = {}
    for player, path in paths.items():
        with Path(path).open("rb") as stream:
            data = stream.read(0x100001)
        identity = hashlib.sha1(data).hexdigest(), hashlib.sha256(data).hexdigest()
        profile = next(
            (p for p in profiles if (p["final_rom_sha1"], p["rom_sha256"]) == identity), None
        )
        if len(data) != 0x100000 or profile is None:
            raise AdmissionError("runtime cartridge is not an exact installed canonical artifact")
        players[player] = cartridge_metadata(profile)
    return {"schema": CONTRACT_SCHEMA, "players": players}
