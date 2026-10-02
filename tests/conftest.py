"""Repo-wide pytest fixtures.

Lives at the tests/ root (not tests/unit/) so tests/integration, tests/live and tests/e2e
see the same fixtures.

The autouse `isolate_data_dir` fixture is the important one: `server/state.py` resolves
DATA_DIR / LINKS_PATH / MEMORIAL_PATH at import time to the REAL `data/` directory, so any
test that builds a SoulLinkState without monkeypatching all three writes over live run
state.  Three tests did exactly that (they patched LINKS_PATH but not MEMORIAL_PATH, so a
plain `pytest tests/unit/` rewrote data/memorial.json).  Repointing them for every test
makes that class of leak impossible instead of relying on each test to remember.
"""
import os
import socket
import subprocess
import sys
import tempfile
import time

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Modules that bind these names at import time.  server/server.py does
# `from .state import ... LINKS_PATH, DATA_DIR`, which copies the value, so patching
# server.state alone would not cover it.
_PATH_NAMES = ("DATA_DIR", "LINKS_PATH", "MEMORIAL_PATH")


@pytest.fixture(autouse=True)
def isolate_data_dir(tmp_path, monkeypatch):
    """Point every module-level data path at a per-test tmp dir."""
    d = tmp_path / "data"
    d.mkdir(exist_ok=True)
    values = {
        "DATA_DIR": str(d),
        "LINKS_PATH": str(d / "links.json"),
        "MEMORIAL_PATH": str(d / "memorial.json"),
    }
    for mod_name in ("server.state", "server.server"):
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        for name in _PATH_NAMES:
            if hasattr(mod, name):
                monkeypatch.setattr(mod, name, values[name], raising=False)
    return d


def _find_free_port() -> int:
    """Return a free TCP port on loopback by briefly binding to port 0."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server_port() -> int:
    """The TCP port the test server is bound to (shared with live_server)."""
    return _find_free_port()


@pytest.fixture(scope="session")
def live_server(server_port):
    """Spin up a server.py subprocess for TCP integration tests."""
    tcp_port = server_port
    http_port = _find_free_port()
    tmpdir = tempfile.mkdtemp(prefix="slink_test_")
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "server.server",
            "--host", "127.0.0.1",
            "--port", str(tcp_port),
            "--http-port", str(http_port),
            "--data-dir", tmpdir,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=REPO,
    )
    # Wait up to 10 s for the TCP port to accept connections.
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", tcp_port), timeout=0.5).close()
            break
        except OSError:
            time.sleep(0.1)
    else:
        proc.terminate()
        pytest.fail(f"live_server: server did not start within 10 seconds on port {tcp_port}")

    yield proc

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


# ── the UPR jar ──────────────────────────────────────────────────────────────────────
# Three test files had three slightly different copies of this search, none of which
# looked in .cache/. The result was fifteen tests -- every proof that the ROM scanner,
# the settings codec and the Manager pipeline work on a GENUINELY randomized ROM --
# quietly skipping on any machine where the jar was not in one of two hardcoded spots.
# A skip reads exactly like a pass, and this is the set of skips that matters most.
#
# The jar is user-supplied and never redistributed (it is GPLv3 and not ours to ship),
# so .cache/upr/ is the right home: gitignored, and shared by every worktree.
def find_upr_jar() -> str | None:
    """Kept for the tests that import it from here; the server owns the search now."""
    from server.upr_pipeline import find_upr_jar as _find
    return _find()


# ── An unprovisioned Gen 2 decomp clone is a named skip, not a collection abort ─────────────────
# Gen 2 tests load the pinned pokecrystal/pokegold clone through tools.gen2_source_data, some at
# module import. On a checkout without .cache/gen2-build/<repo> that aborted collection for the
# whole suite (0 tests run; Gen1-Collab2 on master 062977a9). Only SourceUnavailable -- the clone is
# ABSENT -- becomes pytest.skip("pokecrystal not cloned: ..."), which works at import, fixture and
# test time; a present-but-dirty/other-commit/hash-mismatched source still raises and fails.
def _skip_unprovisioned_gen2_sources():
    # Tools that put tools/ on sys.path import the loader as plain `gen2_source_data` (e.g.
    # tools/gen_gen2_evos.py); alias that name to the same module so there is ONE loader, one
    # SourceUnavailable class and one wrapper.
    try:
        import tools.gen2_source_data as source_data
    except Exception:  # noqa: BLE001 - tools not importable here: nothing to wrap
        return
    sys.modules.setdefault("gen2_source_data", source_data)
    real = source_data._load_context

    def _load_context(*args, **kwargs):
        try:   # looked up per call so a test can stand in a raw loader (test_verify_gen2_release_lanes)
            return _load_context.__wrapped__(*args, **kwargs)
        except source_data.SourceUnavailable as exc:
            pytest.skip(str(exc), allow_module_level=True)

    _load_context.__wrapped__ = real   # test_gen2_source_unavailable.py reaches the unwrapped loader
    source_data._load_context = _load_context


_skip_unprovisioned_gen2_sources()



# The same absent input reached without the loader: a test that reads a built ROM or a decomp file
# under .cache/gen2-build/<repo>/ directly. Skipped ONLY when <repo> itself is absent (not cloned);
# a present clone missing a file (not built, wrong layout) still fails.
_GEN2_BUILD = os.path.join(REPO, ".cache", "gen2-build")


def _absent_gen2_clone(exc):
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        name = getattr(exc, "filename", None) if isinstance(exc, FileNotFoundError) else None
        if name:
            try:
                rel = os.path.relpath(os.path.abspath(str(name)), _GEN2_BUILD)
            except ValueError:   # another drive on Windows: outside the tree, report the failure
                rel = ".."
            repo = rel.replace("\\", "/").split("/")[0]
            if not rel.startswith("..") and repo and not os.path.isdir(os.path.join(_GEN2_BUILD, repo)):
                return f"{repo} not cloned: {os.path.join(_GEN2_BUILD, repo)}"
        exc = exc.__cause__ or exc.__context__
    return None


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    if report.failed and call.excinfo is not None:
        reason = _absent_gen2_clone(call.excinfo.value)
        if reason:
            report.outcome = "skipped"
            report.longrepr = (str(item.path), (item.location[1] or 0) + 1, f"Skipped: {reason}")
    return report
