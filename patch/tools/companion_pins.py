"""patch/dist/companion_pins.json: the build manifest of the companions that ship as UPS patches.

    {"schema": "slink-companion-pins-v1", "pins": {slug: {"patched_md5", "canonical_sha1", "version",
                                                         "version_slot": {"offset", "length"}}}}

One entry per slug (rr, rb-red, rb-blue), each written by the tool that owns that build; server/patcher.py reads
`patched_md5` and the stamp tool rewrites the file for a release. `update` is a read-modify-write that touches only
the slug it is given, so the builders can run in any order (and next to each other) without clobbering one another.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

SCHEMA = "slink-companion-pins-v1"
PINS = Path(__file__).resolve().parents[1] / "dist" / "companion_pins.json"


def load(path: Path = PINS) -> dict:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("schema") != SCHEMA:
        raise ValueError(f"{path}: schema {doc.get('schema')!r}, expected {SCHEMA!r}")
    return doc


def update(slug: str, fields: dict, path: Path = PINS) -> dict:
    """Merge `fields` into pins[slug] (created if absent) and write the file back; returns the merged pin."""
    doc = load(path)
    pin = doc["pins"].setdefault(slug, {})
    pin.update(fields)
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)
    return pin
