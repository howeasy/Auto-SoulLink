"""The PERF producer's bundle must satisfy the row f consumer's evidence surface (12a05f6e; OMP cx-ea9abdbc).

Offline: committed=False is the documented MODEL seam of gen4_evidence.snapshot. A producer-built bundle is
accepted, and a 1-byte edit to (or the removal of) any bound module makes it STALE.
"""

import copy
import json

import pytest

from tests.live import test_gen4_probe_gates as gates
from tools import gen4_evidence as evidence

TITLE = "heartgold"


@pytest.fixture
def perf_cut():
    return evidence.snapshot("perf", TITLE, repo=gates.REPO, committed=False)


def _sample(cut):
    sample = {
        "producer": "gen4-PERF", "result": "PASS", "level": "PHYSICAL",
        "title": TITLE, "rom_sha1": "a" * 40, "source_head": "MODEL",
        "concurrent_load": False, "ending_registered": 0, "frames_requested": 3000,
    }
    sample.update(cut)
    return sample


def _bundle(sample):
    observation = copy.deepcopy(gates.examples()["f"])
    for record in observation["sustained"].values():
        record.update(copy.deepcopy(sample))
        record["floor"].update(copy.deepcopy(sample))
    return {"schema": "gen4-perf-bundle-v1", "producer": "gen4-PERF", "level": "PHYSICAL",
            "title": TITLE, "rom_sha1": "a" * 40, "source_head": "MODEL", "observation": observation}


def _write(tmp_path, cut):
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(_bundle(_sample(cut))), encoding="utf-8")
    return path


def test_a_perf_bundle_over_the_full_surface_is_accepted(tmp_path, perf_cut):
    observation, why = gates.perf_f(_write(tmp_path, perf_cut), TITLE, "a" * 40, "MODEL", expected_cut=perf_cut)
    assert why is None and observation is not None


@pytest.mark.parametrize("module", [
    "lua/gen4/reads.lua", "lua/json_codec.lua", "lua/hook_registry.lua", "tools/gen4_evidence.py",
    "lua/nds/hook_binding.lua",
])
def test_a_one_byte_edit_to_any_bound_module_is_stale(tmp_path, perf_cut, module):
    assert module in perf_cut["module_sha256"], module
    cut = copy.deepcopy(perf_cut)
    cut["module_sha256"][module] = "0" * 64
    cut["surface_sha256"] = evidence.surface_hash("perf", cut["module_sha256"])
    with pytest.raises(evidence.StaleEvidenceError, match="STALE module_sha256"):
        gates.perf_f(_write(tmp_path, cut), TITLE, "a" * 40, "MODEL", expected_cut=perf_cut)


def test_a_trimmed_surface_is_stale(tmp_path, perf_cut):
    cut = copy.deepcopy(perf_cut)
    cut["module_sha256"].pop("lua/gen4/safety.lua")
    cut["surface_sha256"] = evidence.surface_hash("perf", cut["module_sha256"])
    with pytest.raises(evidence.StaleEvidenceError, match="STALE module_sha256"):
        gates.perf_f(_write(tmp_path, cut), TITLE, "a" * 40, "MODEL", expected_cut=perf_cut)
