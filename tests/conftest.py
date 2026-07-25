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
