"""Re-pin the review hashes in tests/gen1_release_requirements.json after source edits.

The release gate compares every proof ``source_sha256`` and every ``supporting_sources`` digest
with ``verify_gen1_release.proof_sha256`` (UTF-8 text with line endings normalized for source
suffixes, raw bytes otherwise). This helper recomputes them with that same function and either
prints the drift (default) or rewrites the manifest in place (``--write``) by replacing each stale
hash string textually, so the hand-ordered manifest keeps its formatting.

It refuses to write when one stale hash would have to become two different new hashes (two
paths that used to be identical and diverged), and it never invents a hash for a file that no
longer exists: such rows must be re-registered onto a new proof source by a reviewer.

Usage:
    python tools/repin_gen1_release_hashes.py            # report drift, change nothing
    python tools/repin_gen1_release_hashes.py --write    # rewrite the stale hashes
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_gen1_release import MANIFEST, local_path, proof_sha256, read_json  # noqa: E402


def drift(manifest: dict) -> tuple[list[tuple[str, str, str, str]], list[tuple[str, str]]]:
    """Return (stale rows as (requirement, path, old, new), missing rows as (requirement, path))."""
    stale, missing = [], []
    for requirement in manifest["requirements"]:
        for proof in requirement.get("proofs", []):
            entries = [(proof.get("source"), proof.get("source_sha256"))]
            entries += list(proof.get("supporting_sources", {}).items())
            for name, old in entries:
                if not name or not old:
                    continue
                try:
                    new = proof_sha256(local_path(name))
                except (OSError, ValueError):
                    missing.append((requirement["id"], name))
                    continue
                if new != old:
                    stale.append((requirement["id"], name, old, new))
    return stale, missing


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="rewrite the stale hashes in the manifest")
    args = parser.parse_args(argv)
    manifest = read_json(MANIFEST)
    stale, missing = drift(manifest)
    for requirement_id, name in missing:
        print(f"MISSING  {requirement_id} | {name}")
    for requirement_id, name, old, new in stale:
        print(f"STALE    {requirement_id} | {name} | {old[:12]} -> {new[:12]}")
    files = sorted({name for _, name, _, _ in stale})
    rows = sorted({requirement_id for requirement_id, _, _, _ in stale})
    print(f"{len(stale)} stale hash entries over {len(rows)} requirement rows and {len(files)} files; "
          f"{len(missing)} entries point at files that no longer exist")
    if not args.write:
        return 0
    replacements = {}
    for _, _, old, new in stale:
        if replacements.setdefault(old, new) != new:
            print(f"REFUSED: hash {old[:12]} would map to two different new hashes; re-register by hand")
            return 1
    text = MANIFEST.read_bytes().decode("utf-8")
    for old, new in replacements.items():
        if text.count(old) == 0:
            print(f"REFUSED: hash {old[:12]} not found textually in the manifest")
            return 1
        text = text.replace(old, new)
    MANIFEST.write_bytes(text.encode("utf-8"))
    print(f"rewrote {len(replacements)} distinct hashes in {MANIFEST.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
