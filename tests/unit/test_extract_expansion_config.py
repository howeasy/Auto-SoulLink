"""XC0 falsifiers: the pinned pokeemerald-expansion battle-config VALUES.

All offline (no network, no cross-compiler) except where explicitly noted; the
live "--host hgbox" regeneration/staleness check is a manual Run step, not a
pytest dependency (mirrors tools/build_expansion.py: never invoked from tests).
"""

import copy
import json
import re
import subprocess
import sys

import pytest

from tools import build_expansion as be, extract_expansion_config as c

CONFIG = json.loads(c.OUTPUT.read_text(encoding="utf-8"))

# Fixed, read-only local checkout named by the XC0 card (a different worktree than
# this one); the neighbouring expansion tests instead use `ex.ROOT/".cache/expansion-src"`
# -- this repo has no such local clone, so the falsifier below is gated on this path.
LOCAL_CHECKOUT = c.ROOT.parent / "em-x1/.cache/expansion-src"


def test_committed_config_header_hashes_match_lock_and_facts_provenance():
    lock = be.load_lock()
    facts = json.loads(c.FACTS_PATH.read_text(encoding="utf-8"))
    provenance = CONFIG["provenance"]
    assert set(provenance["config_sha256"]) == set(c.CONFIG_HEADERS)
    for header, digest in provenance["config_sha256"].items():
        assert lock["config_headers"][header] == digest
        assert facts["provenance"]["config_sha256"][header] == digest
    assert provenance["source_commit"] == c.PIN == facts["provenance"]["source_commit"]
    assert provenance["rom_sha1"] == facts["provenance"]["rom_sha1"]


def local_checkout():
    if not LOCAL_CHECKOUT.exists():
        pytest.skip(f"expansion source not cloned: {LOCAL_CHECKOUT}")
    commit = subprocess.check_output(["git", "-C", str(LOCAL_CHECKOUT), "rev-parse", "HEAD"], text=True).strip()
    assert commit == c.PIN
    dirty = subprocess.check_output(["git", "-C", str(LOCAL_CHECKOUT), "status", "--porcelain", "--untracked-files=no"], text=True)
    assert not dirty
    return LOCAL_CHECKOUT


def hand_read(source, header, name):
    """Independent of extract_expansion_config.py's own regex/eval: a fresh read."""
    text = (source / header).read_text(encoding="utf-8")
    match = re.search(rf"^#define[ \t]+{name}\b[ \t]+([^\r\n]+)", text, re.M)
    assert match, f"{name} not found in {header}"
    raw = re.sub(r"//.*$", "", match.group(1)).strip()
    if raw == "GEN_LATEST":
        general = (source / "include/config/general.h").read_text(encoding="utf-8")
        assert re.search(r"^#define\s+GEN_LATEST\s+GEN_9\s*$", general, re.M), "GEN_LATEST no longer aliases GEN_9"
        assert re.search(r"^#define\s+GEN_9\s+8\s*$", general, re.M), "GEN_9 is no longer 8"
        return 8
    return int(raw)


@pytest.mark.parametrize("name,header", [
    ("B_CRIT_MULTIPLIER", "include/config/battle.h"),
    ("B_EXP_CATCH", "include/config/battle.h"),
    ("B_CONFUSION_TURNS", "include/config/battle.h"),
])
def test_falsifier_hand_read_header_matches_config_json(name, header):
    source = local_checkout()
    assert CONFIG["macros"][name]["value"] == hand_read(source, header, name)
    assert CONFIG["macros"][name]["header"] == header


def test_species_enabled_header_is_pinned_but_not_extracted_from():
    assert "include/config/species_enabled.h" in CONFIG["provenance"]["config_sha256"]
    assert not any(entry["header"] == "include/config/species_enabled.h" for entry in CONFIG["macros"].values())
    assert "P_SCATTERBUG_LINE_FORM_BREED" not in CONFIG["macros"]  # enum-valued, not a macro; see `excluded`.
    assert "P_SCATTERBUG_LINE_FORM_BREED" in CONFIG["provenance"]["excluded"]["enum_valued"]


def test_config_is_deterministic_sorted_json():
    raw = c.OUTPUT.read_text(encoding="utf-8")
    assert raw == json.dumps(json.loads(raw), indent=2, sort_keys=True) + "\n"


def test_every_macro_value_matches_its_own_recorded_expansion():
    for name, entry in CONFIG["macros"].items():
        assert c.eval_int(entry["expanded"]) == entry["value"], name


def test_build_probe_emits_one_sentinel_line_per_candidate():
    candidates = {"B_FAKE": {"header": "include/config/battle.h", "raw": "5"}}
    probe = c.build_probe(candidates)
    assert '#include "global.h"' in probe
    assert "SLINK_CFG_BEGIN_B_FAKE B_FAKE SLINK_CFG_END_B_FAKE" in probe


def test_parse_expanded_reads_the_sentinel_pair():
    text = "junk\nSLINK_CFG_BEGIN_B_X 8 + 1 SLINK_CFG_END_B_X\nmore junk\n"
    assert c.parse_expanded(text, ["B_X"]) == {"B_X": "8 + 1"}


def test_parse_expanded_requires_every_name():
    with pytest.raises(ValueError, match="did not emit"):
        c.parse_expanded("nothing here", ["B_MISSING"])


@pytest.mark.parametrize("expr,value", [("8", 8), ("8 + 1", 9), ("(1 << 5) | 3", 35), ("(((255 >> 3) & 31))", 31)])
def test_eval_int_arithmetic(expr, value):
    assert c.eval_int(expr) == value


@pytest.mark.parametrize("expr", ["GEN_LATEST", "RGB2GBA(1, 2, 3)", "1;import os"])
def test_eval_int_rejects_unresolved_or_unsafe_expressions(expr):
    with pytest.raises((ValueError, SyntaxError)):
        c.eval_int(expr)


def test_read_macro_candidates_excludes_species_enabled_and_enum_valued():
    source = local_checkout()
    candidates = c.read_macro_candidates(source)
    assert "P_SCATTERBUG_LINE_FORM_BREED" not in candidates
    assert not any(info["header"] == "include/config/species_enabled.h" for info in candidates.values())
    assert len(candidates) == len(CONFIG["macros"])
    assert set(candidates) == set(CONFIG["macros"])


def test_offline_check_passes_on_the_committed_file():
    assert c.offline_check(c.OUTPUT)["macros"] == CONFIG["macros"]


@pytest.mark.parametrize("mutation", ["value", "config_sha256", "commit"])
def test_check_exits_nonzero_when_config_json_is_stale(tmp_path, mutation):
    """The XC0 falsifier: --check must fail closed on a hand-corrupted copy."""
    mutated = copy.deepcopy(CONFIG)
    if mutation == "value":
        mutated["macros"]["B_CRIT_MULTIPLIER"]["value"] += 1
    elif mutation == "config_sha256":
        mutated["provenance"]["config_sha256"]["include/config/battle.h"] = "0" * 64
    else:
        mutated["provenance"]["source_commit"] = "0" * 40
    stale = tmp_path / "config.json"
    stale.write_text(json.dumps(mutated, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        c.offline_check(stale)
    result = subprocess.run(
        [sys.executable, str(c.ROOT / "tools/extract_expansion_config.py"), "--check", "--output", str(stale)],
        cwd=c.ROOT, capture_output=True, text=True,
    )
    assert result.returncode != 0, result.stderr


def test_check_passes_on_an_unmutated_temp_copy(tmp_path):
    """Same CLI path as the staleness test, proving it isn't failing for an unrelated reason."""
    copy_path = tmp_path / "config.json"
    copy_path.write_text(c.OUTPUT.read_text(encoding="utf-8"), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(c.ROOT / "tools/extract_expansion_config.py"), "--check", "--output", str(copy_path)],
        cwd=c.ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
