"""Verify generated Gen 2 CPU candidates against locked source, symbols, and ROMs."""

import argparse
import sys
from pathlib import Path

if __package__:
    from .gen2_source_data import ARTIFACTS, ROOT, load_context
    from .gen_gen2_engine_signals import SPEC_PATH, generate_pack, read_specs
else:
    from gen2_source_data import ARTIFACTS, ROOT, load_context
    from gen_gen2_engine_signals import SPEC_PATH, generate_pack, read_specs


def verify_pack(context, pack, specs):
    expected = generate_pack(context, specs)
    if pack != expected:
        raise ValueError(f"{context.title}: engine-site bytes, source provenance, guards, or inventory differ")
    return {"title": context.title, "sites": len(expected["titles"][context.title]["sites"]),
            "evidence_level": "SOURCE", "physical_status": "OPEN", "f3_complete": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--title", choices=tuple(ARTIFACTS))
    args = parser.parse_args(argv)
    try:
        specs = read_specs(args.root / SPEC_PATH)
        for title in [args.title] if args.title else ARTIFACTS:
            context = load_context(title, root=args.root)
            pack = read_specs(args.root / f"data/games/gen2_{title}/engine_signals.json")
            result = verify_pack(context, pack, specs)
            print(f"{title}: {result['sites']} SOURCE candidates verified; physical firing/F3 OPEN")
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"Gen 2 ROM layout refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
