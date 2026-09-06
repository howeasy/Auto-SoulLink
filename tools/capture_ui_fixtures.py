"""Regenerate UI presentation fixtures from archived capture inputs, offline.

No sockets, emulator, admission override or live data directory is used. These
are rendering scenarios, not evidence that an actual cartridge was admitted.
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.ui_support import hydrate_capture  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "tests/fixtures/ui/source")
    parser.add_argument("--output", type=Path, default=ROOT / "tests/fixtures/ui/status")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="slink-ui-fixtures-") as scratch:
        for game in ("gen3", "gen1"):
            capture = json.loads((args.source / f"{game}.json").read_text(encoding="utf-8"))
            srv = hydrate_capture(capture, Path(scratch) / game)
            output = srv._build_status_dict()
            (args.output / f"{game}.json").write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
            print(f"{game}: generated from isolated state; admission/freshness evidence remains unavailable")


if __name__ == "__main__":
    main()
