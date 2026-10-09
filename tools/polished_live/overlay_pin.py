"""The current shipped overlay identity. Historical receipts keep their recorded hashes."""
from __future__ import annotations

import json
import re
from pathlib import Path


def overlay_sha1(root: Path | None = None) -> str:
    root = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    value = json.loads((root / "data/polished/overlay_provenance.json").read_text(encoding="utf-8"))["output"]["sha1"]
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError("invalid shipped Polished overlay sha1")
    return value
