"""Profile regressions against canonical symbols and strict Gen 1 evidence.

Gen 1 checks effective values, aliases, nested structures and nil dispositions.
Missing canonical dependencies fail. The older Gen 2 hex-literal audit remains
covered separately without claiming its constant-only skips as Gen 1 evidence.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
PRET_SYMS_PATH = REPO_ROOT / "data" / "pret_syms.json"
TOOLS_DIR = REPO_ROOT / "tools"


def _load_verifier():
    """Import tools/verify_profile_addresses.py as a module so we reuse its
    PROFILE_TO_PRET mapping and Lua-profile parser without duplicating logic."""
    sys.path.insert(0, str(TOOLS_DIR))
    try:
        import verify_profile_addresses  # type: ignore
        return verify_profile_addresses
    finally:
        sys.path.pop(0)


def _verifier_results():
    if not PRET_SYMS_PATH.exists():
        pytest.fail("data/pret_syms.json missing; canonical symbols are required")
    mod = _load_verifier()
    pret_syms = json.loads(PRET_SYMS_PATH.read_text(encoding="utf-8"))
    profile_addrs = {
        **mod._extract_variant_addresses(mod.PROFILE_GEN1),
        **mod._extract_variant_addresses(mod.PROFILE_GEN2),
    }
    return mod.verify(profile_addrs, pret_syms)


@pytest.fixture(scope="module")
def results():
    return _verifier_results()


def test_no_fail_addresses(results):
    """Hard gate: zero FAIL severity rows. Every profile address that maps to
    a known pret symbol must equal that symbol's authoritative address."""
    fails = [f"{r['variant']}.{r['field']}: {r['note']}" for r in results if r["severity"] == "FAIL"]
    assert not fails, (
        "Profile addresses diverge from pret authority:\n  " + "\n  ".join(fails)
        + "\n\nRun `python tools/verify_profile_addresses.py` for details, "
        + "or rebuild pret_syms with `python tools/build_pret_syms.py --update`."
    )


def test_pret_syms_loaded_for_all_three_repos(results):
    """Sanity: pret_syms.json should have all three Gen 1/2 repos with
    symbols. A repo with zero symbols means the build_pret_syms run failed
    silently for that repo."""
    pret_syms = json.loads(PRET_SYMS_PATH.read_text(encoding="utf-8"))
    for repo in ("pokered", "pokeyellow", "pokecrystal"):
        assert repo in pret_syms, f"data/pret_syms.json missing {repo}"
        # Sanity: at least 100 WRAM symbols expected per repo. The actual
        # counts at first ship were ~2600 / ~3000 / ~5900.
        assert len(pret_syms[repo]) > 100, (
            f"{repo} has only {len(pret_syms[repo])} symbols — build likely failed"
        )


def test_no_unmapped_addresses(results):
    """Every address field in the Lua profile should be either OK (matches pret)
    or explicitly SKIPped (offset constant / sentinel / unmapped on purpose).
    WARN rows mean the verifier's PROFILE_TO_PRET mapping is stale — fix it.

    If this test fails after a pret upstream rename, update the mapping in
    tools/verify_profile_addresses.py to use the new symbol name."""
    warns = [
        f"{r['variant']}.{r['field']}: {r['note']} "
        f"(profile=0x{r['profile_addr']:04X}, expected symbol={r['pret_symbol']})"
        for r in results
        if r["severity"] == "WARN"
    ]
    assert not warns, (
        "Profile fields are mapped to pret symbols that no longer exist:\n  "
        + "\n  ".join(warns)
        + "\n\nEither rename the symbol in tools/verify_profile_addresses.py "
        + "or add a source-backed contract for the value."
    )
