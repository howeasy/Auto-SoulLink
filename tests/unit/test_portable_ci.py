"""The public lane must account for every test without weakening local release."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.portable_ci import load_inventory, select_nodes

ROOT = Path(__file__).resolve().parents[2]
PORTABLE = "cases/test_case.py::test_portable"
LOCAL = "cases/test_case.py::test_local"


def inventory():
    return {
        "schema": 1, "roots": ["cases"],
        "resources": {"cartridge": {"description": "User-provided cartridge", "provisioning": "Local release only"}},
        "groups": [
            {"id": "portable", "reason": "Synthetic test", "requires": [],
             "platforms": ["linux", "win32"], "nodes": [PORTABLE]},
            {"id": "local", "reason": "Reads real cartridge", "requires": ["cartridge"],
             "platforms": ["linux", "win32"], "nodes": [LOCAL]},
        ],
    }


def load(tmp_path, data):
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return load_inventory(path)[1]


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_local_inputs_are_always_named_deferrals_even_if_present(tmp_path, platform):
    (tmp_path / "cartridge.gb").write_bytes(b"present")
    policies = load(tmp_path, inventory())
    selected, deferred = select_nodes(policies, [PORTABLE, LOCAL], platform)
    assert selected == [PORTABLE]
    assert deferred == [{"nodeid": LOCAL, **policies[LOCAL]}]


def test_each_platform_executes_its_own_filesystem_coverage(tmp_path):
    data = inventory()
    data["groups"][0]["platforms"] = ["linux"]
    data["groups"][1].update(requires=[], platforms=["win32"])
    data["resources"] = {}
    policies = load(tmp_path, data)
    for platform, expected in (("linux", PORTABLE), ("win32", LOCAL)):
        selected, deferred = select_nodes(policies, [PORTABLE, LOCAL], platform)
        assert selected == [expected]
        assert len(deferred) == 1 and deferred[0]["nodeid"] != expected


@pytest.mark.parametrize("change", ["new", "missing", "duplicate", "platform"])
def test_collection_drift_and_unqualified_platforms_cannot_pass(tmp_path, change):
    policies = load(tmp_path, inventory())
    nodes, platform = [PORTABLE, LOCAL], "linux"
    if change == "new":
        nodes.append("cases/test_case.py::test_new")
    elif change == "missing":
        nodes.remove(LOCAL)
    elif change == "duplicate":
        nodes.append(PORTABLE)
    else:
        platform = "unqualified"
    with pytest.raises(ValueError):
        select_nodes(policies, nodes, platform)


@pytest.mark.parametrize("change", ["duplicate-node", "unknown-resource", "unknown-field", "empty-nodes", "outside-root"])
def test_malformed_classifications_are_rejected(tmp_path, change):
    data = copy.deepcopy(inventory())
    if change == "duplicate-node":
        data["groups"][1]["nodes"].append(PORTABLE)
    elif change == "unknown-resource":
        data["groups"][1]["requires"] = ["typo"]
    elif change == "unknown-field":
        data["groups"][0]["require"] = ["cartridge"]
    elif change == "empty-nodes":
        data["groups"][0]["nodes"] = []
    else:
        data["groups"][0]["nodes"] = ["../cases/test_case.py::test_escape"]
    with pytest.raises(ValueError):
        load(tmp_path, data)


def test_duplicate_json_keys_cannot_replace_reviewed_policy(tmp_path):
    path = tmp_path / "inventory.json"
    path.write_text('{"schema":1,"schema":2}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate inventory key"):
        load_inventory(path)


@pytest.mark.parametrize("case", [
    "pass", "skip", "xfail", "xpass", "call-fail", "setup-fail", "teardown-fail",
    "collection-skip", "collection-fail", "unclassified", "missing", "deselect", "collect-only",
])
def test_real_pytest_requires_complete_execution_and_reports_every_deferral(tmp_path, case):
    cases = tmp_path / "cases"
    cases.mkdir()
    body = "def test_portable():\n    pass\n"
    if case == "skip":
        body = "def test_portable():\n    pytest.skip('unavailable')\n"
    elif case in {"xfail", "xpass"}:
        body = "@pytest.mark.xfail(reason='known failure', strict=False)\ndef test_portable():\n    "
        body += "assert False\n" if case == "xfail" else "pass\n"
    elif case == "call-fail":
        body = "def test_portable():\n    assert False\n"
    elif case in {"setup-fail", "teardown-fail"}:
        body = "@pytest.fixture\ndef fixture():\n"
        body += "    yield\n" if case == "teardown-fail" else ""
        body += "    assert False\ndef test_portable(fixture):\n    pass\n"
    elif case == "collection-skip":
        body = "pytest.skip('unavailable module', allow_module_level=True)\n" + body
    elif case == "collection-fail":
        body = "raise RuntimeError('broken collection')\n" + body
    elif case == "unclassified":
        body += "def test_unclassified():\n    pass\n"
    elif case == "missing":
        body = ""
    # Any accidental execution of a deferred fixture is visible even if its test
    # then skips, xfails, or is caught by another test's exception handler.
    body += ("@pytest.fixture\ndef local_input():\n"
             "    Path('private-fixture-executed').write_text('ERROR')\n"
             "    raise RuntimeError('local fixture executed')\n"
             "def test_local(local_input):\n    assert False\n")
    (cases / "test_case.py").write_text("import pytest\nfrom pathlib import Path\n" + body, encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(inventory()), encoding="utf-8")
    report = tmp_path / "report.json"
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    env.pop("PYTEST_ADDOPTS", None)
    extra = ["-k", "not portable"] if case == "deselect" else []
    if case == "collect-only":
        extra = ["--collect-only"]
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "cases", "-q", "-p", "tools.portable_ci",
         "--portable-ci-inventory", str(path), "--portable-ci-report", str(report),
         "--basetemp", str(tmp_path / "pytest-tmp"), *extra],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30, check=False,
    )
    data = json.loads(report.read_text())
    assert (result.returncode == 0) == (case == "pass"), result.stdout + result.stderr
    assert data["portable_passed"] == (case == "pass")
    assert data["release_approved"] is False
    assert not (tmp_path / "private-fixture-executed").exists()
    if case == "pass":
        assert data["selected"] == [PORTABLE]
        assert [row["nodeid"] for row in data["deferred"]] == [LOCAL]
        assert data["deselected"] == [LOCAL]
        assert data["counts"] == {"collected": 2, "selected": 1, "deferred": 1}
    else:
        assert data["problems"]
