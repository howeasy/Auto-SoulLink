"""Explicit inputs for required RR evidence and production-client regression cases.

These are selected separately from ordinary unit tests. Missing requested inputs
fail the selected lane rather than silently changing its coverage.
"""
from pathlib import Path

import pytest


def pytest_addoption(parser):
    group = parser.getgroup("rr-evidence")
    group.addoption("--rr-repo", type=Path, help="Exact source worktree to exercise")
    group.addoption("--rr-rom", type=Path, help="Pinned RR4.1 base ROM for binary evidence")


@pytest.fixture(scope="session")
def rr_repo(pytestconfig):
    value = pytestconfig.getoption("--rr-repo")
    if value is None:
        pytest.fail("This RR lane requires explicit --rr-repo; no source-root fallback", pytrace=False)
    try:
        path = value.resolve(strict=True)
    except OSError as exc:
        pytest.fail(f"RR source worktree unavailable: {exc}", pytrace=False)
    if not path.is_dir() or not (path / "lua" / "clients" / "gen3_frlge_client.lua").is_file():
        pytest.fail("--rr-repo is not a complete SLink source worktree", pytrace=False)
    return path


@pytest.fixture(scope="session")
def rr_rom_path(pytestconfig):
    value = pytestconfig.getoption("--rr-rom")
    if value is None:
        pytest.fail("This RR lane requires explicit --rr-rom; missing ROMs never skip", pytrace=False)
    try:
        path = value.resolve(strict=True)
    except OSError as exc:
        pytest.fail(f"RR ROM unavailable: {exc}", pytrace=False)
    if not path.is_file():
        pytest.fail("--rr-rom must identify a readable cartridge file", pytrace=False)
    return path
