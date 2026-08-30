#!/usr/bin/env python3
"""Build a randomized Red and inject the companion patch into it.

The artifact this produces is the only way to answer the question the structural injector
exists for: does a cartridge that UPR rewrote, and that we then patched WITHOUT a hash to
lean on, still boot and still run the panel? Comparing bytes against the clean build
cannot tell you that -- the whole point is that the bytes differ.

Deterministic enough to be useful: UPR ZX has no seed flag, so the wild tables differ from
run to run. What must NOT differ is that all twelve manifest spans still match, the hook
site is untouched, bank $3F is empty, and the injected result boots. Those are properties
of the region UPR does not touch, and they hold for every seed.

    python tools/make_randomized_patched.py            # -> patch/gen1/build/slink_red_randomized.gbc

Needs the UPR jar (see tests/conftest.py find_upr_jar) and a clean Red dump. Skips
loudly rather than failing when either is absent, because neither is committed.
"""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "patch", "gen1", "tools"))

CLEAN_RED = os.path.join(_REPO, "patch", "build", "gen1_red.gb")
# .gb, not .gbc: UPR insists on .gbc for its OWN output (it appends the extension
# otherwise), but BizHawk picks its core mode from the extension, and a Gen 1 ROM
# opened as a Game Boy COLOR title does not load the DMG battery save the gates seed.
OUT = os.path.join(_REPO, "patch", "gen1", "build", "slink_red_randomized.gb")

# The categories this project permits. Deliberately all of them: the injector's spans have
# to survive the busiest allowed run, not the quietest.
CATEGORIES = {"wild", "starters", "statics", "trainers", "tms", "field_items"}


def build(jar: str | None = None, quiet: bool = False) -> str | None:
    """Returns the output path, or None when the inputs are not available."""
    from server.upr_pipeline import UprPipelineError, randomize
    from server.upr_settings import build_categories
    from tests.conftest import find_upr_jar

    import inject as injector

    jar = jar or find_upr_jar()
    if not jar:
        if not quiet:
            print("[rand-patch] no PokeRandoZX.jar — put one in .cache/upr/ or set "
                  "SLINK_UPR_JAR", file=sys.stderr)
        return None
    if not os.path.exists(CLEAN_RED):
        if not quiet:
            print(f"[rand-patch] {CLEAN_RED} not present (ROMs are gitignored)",
                  file=sys.stderr)
        return None

    with tempfile.TemporaryDirectory() as tmp:
        settings = os.path.join(tmp, "slink.rnqs")
        with open(settings, "wb") as f:
            f.write(build_categories(CATEGORIES))
        randomized = os.path.join(tmp, "randomized.gbc")
        try:
            result = randomize(jar, settings, CLEAN_RED, randomized)
        except UprPipelineError as exc:
            print(f"[rand-patch] randomization failed: {exc}", file=sys.stderr)
            return None
        with open(randomized, "rb") as f:
            data = f.read()

        try:
            patched = injector.inject(data)
        except injector.InjectError as exc:
            print(f"[rand-patch] injection refused: {exc}", file=sys.stderr)
            return None

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "wb") as f:
        f.write(patched)
    if not quiet:
        print(f"[rand-patch] seed={result['seed']}  -> {os.path.relpath(OUT, _REPO)}  "
              f"sha1={hashlib.sha1(patched).hexdigest()}", file=sys.stderr)
    return OUT


if __name__ == "__main__":
    sys.exit(0 if build() else 1)
