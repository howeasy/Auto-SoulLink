"""Pin the FRLG build contract; validate receipts only when actually published."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = ROOT / "data/gen3_sources.lock.json"
OUT = ROOT / "data/gen3/pret"


def test_gen3_source_lock():
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert lock["schema_version"] == 1
    assert lock["source"] == {
        "url": "https://github.com/pret/pokefirered",
        "commit": "c75f352304d529f6ba92d4f74b9cf8b5c3810788",
    }
    assert lock["agbcc"] == {
        "url": "https://github.com/pret/agbcc",
        "commit": "da598c1d918402c42c0c0d7128ba14567f3175e9",
    }
    assert lock["w64devkit_version"] == "2.10.0"
    assert lock["outputs"] == {
        "pokefirered": {
            "filename": "pokefirered.gba", "game_version": "FIRERED",
            "sha1": "41cb23d8dccc8ebd7c649cd8fbb58eeace6e2fdc",
        },
        "pokeleafgreen": {
            "filename": "pokeleafgreen.gba", "game_version": "LEAFGREEN",
            "sha1": "574fa542ffebb14be69902d1d36f1ec0a4afd71e",
        },
    }
    assert lock["make_variables"] == {"GAME_REVISION": "0", "MODERN": "0"}


def test_gen3_published_provenance():
    receipt = OUT / "provenance.json"
    expected = {f"{name}.{ext}" for name in ("pokefirered", "pokeleafgreen")
                for ext in ("sym", "map")}
    if not receipt.exists():
        # An absent build is permitted; orphaned artifacts are not evidence.
        assert not any((OUT / name).exists() for name in expected)
        return
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    provenance = json.loads(receipt.read_text(encoding="utf-8"))
    assert provenance["schema"] == "gen3-pret-build-provenance-v1"
    assert provenance["source"] == lock["source"]
    assert provenance["agbcc"] == lock["agbcc"]
    assert provenance["host"] and provenance["generated"] and provenance["toolchain"]
    assert set(provenance["files"]) == expected
    assert provenance["roms"] == {
        spec["filename"]: spec["sha1"] for spec in lock["outputs"].values()
    }
    for name, digest in provenance["files"].items():
        data = (OUT / name).read_bytes()
        assert data
        assert hashlib.sha256(data).hexdigest() == digest, name
