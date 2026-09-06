"""Structured pytest evidence for the release runner; inactive unless requested.

Text summaries and test names do not prove execution. Record collection and all three
runtest phases, including teardown and non-strict XPASS, in a nonce-bound artifact.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def pytest_addoption(parser):
    group = parser.getgroup("gen1-release")
    group.addoption("--gen1-release-report", default=None)
    group.addoption("--gen1-release-token", default=None)


def pytest_configure(config):
    if config.getoption("--gen1-release-report"):
        config.pluginmanager.register(ReleaseEvidence(config), "gen1-release-evidence")


class ReleaseEvidence:
    def __init__(self, config):
        self.path = Path(config.getoption("--gen1-release-report"))
        self.data = {
            "schema": 1,
            "token": config.getoption("--gen1-release-token"),
            "collected": [], "deselected": [], "reports": [],
            "collection_problems": [], "internal_errors": [],
        }

    def pytest_collection_finish(self, session):
        self.data["collected"] = [item.nodeid for item in session.items]

    def pytest_deselected(self, items):
        self.data["deselected"].extend(item.nodeid for item in items)

    def pytest_collectreport(self, report):
        if report.outcome != "passed":
            self.data["collection_problems"].append({
                "nodeid": report.nodeid, "outcome": report.outcome,
                "detail": str(report.longrepr),
            })

    def pytest_runtest_logreport(self, report):
        self.data["reports"].append({
            "nodeid": report.nodeid, "when": report.when,
            "outcome": report.outcome, "wasxfail": hasattr(report, "wasxfail"),
        })

    def pytest_internalerror(self, excrepr, excinfo):
        self.data["internal_errors"].append(str(excrepr))

    def pytest_sessionfinish(self, session, exitstatus):
        self.data["exitstatus"] = int(exitstatus)
        self.data["collected_count"] = session.testscollected
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(self.data, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)
