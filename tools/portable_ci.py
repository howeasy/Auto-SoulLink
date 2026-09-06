"""An explicit unit/integration CI selection; never a release verdict.

The checked inventory accounts for every collected node. Resource requirements
are reviewed policy, not a runtime probe that changes coverage on each machine.
This plugin is inactive in ordinary pytest and in the strict release runner.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pytest

PLATFORMS = {"linux", "win32"}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate inventory key: {key}")
        result[key] = value
    return result


def _strings(value, label, *, empty=False):
    if (not isinstance(value, list) or (not value and not empty)
            or any(not isinstance(item, str) or not item.strip() for item in value)
            or len(value) != len(set(value))):
        raise ValueError(f"{label} must be a list of unique nonempty strings")
    return value


def load_inventory(path):
    raw = Path(path).read_bytes()
    data = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(data, dict) or set(data) != {"schema", "roots", "resources", "groups"}:
        raise ValueError("invalid portable CI inventory fields")
    if type(data["schema"]) is not int or data["schema"] != 1:
        raise ValueError("unsupported portable CI inventory schema")
    roots = _strings(data["roots"], "roots")
    if any("\\" in root or root.startswith("/") or ".." in root.split("/") for root in roots):
        raise ValueError("inventory roots must be repository-relative paths")
    resources = data["resources"]
    if not isinstance(resources, dict) or any(
        not isinstance(key, str) or not key or not isinstance(value, dict)
        or set(value) != {"description", "provisioning"}
        or any(not isinstance(text, str) or not text.strip() for text in value.values())
        for key, value in resources.items()
    ):
        raise ValueError("resources require descriptions and provisioning instructions")
    if not isinstance(data["groups"], list) or not data["groups"]:
        raise ValueError("inventory requires nonempty groups")
    policies, group_ids, used_resources = {}, set(), set()
    for group in data["groups"]:
        if not isinstance(group, dict) or set(group) != {"id", "reason", "requires", "platforms", "nodes"}:
            raise ValueError("invalid inventory group fields")
        group_id = group["id"]
        if not isinstance(group_id, str) or not group_id or group_id in group_ids:
            raise ValueError("inventory group IDs must be unique nonempty strings")
        group_ids.add(group_id)
        if not isinstance(group["reason"], str) or not group["reason"].strip():
            raise ValueError(f"group {group_id} requires a reason")
        required = _strings(group["requires"], "requires", empty=True)
        if not set(required) <= resources.keys():
            raise ValueError(f"unknown resource in {group_id}")
        used_resources.update(required)
        platforms = _strings(group["platforms"], "platforms")
        if not set(platforms) <= PLATFORMS:
            raise ValueError(f"unsupported platform in {group_id}")
        for node in _strings(group["nodes"], "nodes"):
            file = node.split("::", 1)[0]
            if ("::" not in node or "\\" in file or ".." in file.split("/")
                    or not any(file.startswith(root + "/") for root in roots)):
                raise ValueError(f"invalid exact node ID: {node}")
            if node in policies:
                raise ValueError(f"node occurs in multiple groups: {node}")
            policies[node] = {key: group[key] for key in ("id", "reason", "requires", "platforms")}
    if used_resources != resources.keys():
        raise ValueError("inventory contains unused resource declarations")
    return data, policies, hashlib.sha256(raw).hexdigest()


def select_nodes(policies, collected, platform):
    if platform not in PLATFORMS:
        raise ValueError(f"portable CI is not qualified for platform {platform!r}")
    if len(collected) != len(set(collected)):
        raise ValueError("duplicate collected node IDs")
    unclassified = sorted(set(collected) - policies.keys())
    missing = sorted(policies.keys() - set(collected))
    if unclassified or missing:
        raise ValueError("portable CI inventory drift; review exact node classifications\n"
                         + "unclassified: " + json.dumps(unclassified) + "\n"
                         + "missing: " + json.dumps(missing))
    selected, deferred = [], []
    for node in collected:
        policy = policies[node]
        if policy["requires"] or platform not in policy["platforms"]:
            deferred.append({"nodeid": node, **policy})
        else:
            selected.append(node)
    if not selected:
        raise ValueError("portable CI selected no tests")
    return selected, deferred


def pytest_addoption(parser):
    group = parser.getgroup("portable-ci")
    group.addoption("--portable-ci-inventory", default=None)
    group.addoption("--portable-ci-report", default=None)


def pytest_configure(config):
    inventory = config.getoption("--portable-ci-inventory")
    report = config.getoption("--portable-ci-report")
    if not inventory and not report:
        return
    if not inventory or not report:
        raise pytest.UsageError("portable CI requires both inventory and report paths")
    plugin = PortableCI(config, inventory, report)
    config.pluginmanager.register(plugin, "portable-ci-policy")


class PortableCI:
    def __init__(self, config, inventory, report):
        self.config = config
        self.path = Path(report)
        self.policies = {}
        self.data = {
            "schema": 1, "lane": "portable-unit-integration", "platform": sys.platform,
            "release_approved": False, "portable_passed": False,
            "inventory_sha256": None, "resources": {}, "collected": [],
            "selected": [], "deferred": [], "deselected": [], "reports": [], "problems": [],
        }
        try:
            inventory_data, self.policies, digest = load_inventory(inventory)
            self.data.update(inventory_sha256=digest, resources=inventory_data["resources"])
        except (OSError, ValueError, TypeError) as exc:
            self.data["problems"].append(str(exc))

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_collection_modifyitems(self, session, config, items):
        self.data["collected"] = [item.nodeid for item in items]
        try:
            if self.data["problems"]:
                raise ValueError("invalid portable CI inventory")
            selected, deferred = select_nodes(self.policies, self.data["collected"], sys.platform)
            self.data.update(selected=selected, deferred=deferred)
            keep = set(selected)
            excluded = [item for item in items if item.nodeid not in keep]
            items[:] = [item for item in items if item.nodeid in keep]
            config.hook.pytest_deselected(items=excluded)
        except ValueError as exc:
            self.data["problems"].append(str(exc))
            items[:] = []
        result = yield
        if [item.nodeid for item in items] != self.data["selected"]:
            self.data["problems"].append("another selector changed the reviewed portable selection")
        if self.data["problems"]:
            items[:] = []
            raise pytest.UsageError("\n".join(self.data["problems"]))
        return result

    def pytest_deselected(self, items):
        self.data["deselected"].extend(item.nodeid for item in items)

    def pytest_collectreport(self, report):
        if report.outcome != "passed":
            self.data["problems"].append(f"collection {report.outcome}: {report.nodeid}: {report.longrepr}")

    def pytest_runtest_logreport(self, report):
        self.data["reports"].append({
            "nodeid": report.nodeid, "when": report.when,
            "outcome": report.outcome, "wasxfail": hasattr(report, "wasxfail"),
        })

    def pytest_internalerror(self, excrepr, excinfo):
        self.data["problems"].append(str(excrepr))

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session, exitstatus):
        expected = {node: Counter({("setup", "passed", False): 1,
                                  ("call", "passed", False): 1,
                                  ("teardown", "passed", False): 1})
                    for node in self.data["selected"]}
        actual = defaultdict(Counter)
        for row in self.data["reports"]:
            actual[row["nodeid"]][(row["when"], row["outcome"], row["wasxfail"])] += 1
        if not expected or actual != expected:
            self.data["problems"].append("selected tests did not each pass setup, call and teardown exactly once")
        intended = Counter(row["nodeid"] for row in self.data["deferred"])
        if Counter(self.data["deselected"]) != intended:
            self.data["problems"].append("deselection differs from named policy deferrals")
        if [item.nodeid for item in session.items] != self.data["selected"]:
            self.data["problems"].append("final collection differs from reviewed selection")
        if int(exitstatus) != 0:
            self.data["problems"].append(f"pytest exited with status {int(exitstatus)}")
        self.data["portable_passed"] = not self.data["problems"]
        if not self.data["portable_passed"]:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
        self.data["exitstatus"] = int(session.exitstatus)
        self.data["counts"] = {key: len(self.data[key]) for key in ("collected", "selected", "deferred")}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(self.data, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)

    def pytest_terminal_summary(self, terminalreporter):
        terminalreporter.section("Portable CI policy (not release validation)")
        for group, count in sorted(Counter(row["id"] for row in self.data["deferred"]).items()):
            terminalreporter.write_line(f"Deferred {count}: {group}")
        for problem in self.data["problems"]:
            terminalreporter.write_line(problem)
        verdict = "PASS" if self.data["portable_passed"] else "FAIL"
        terminalreporter.write_line(f"Portable CI: {verdict}; release approval: NO; exact node report: {self.path}")
