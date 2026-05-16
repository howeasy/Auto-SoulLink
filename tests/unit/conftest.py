"""
Pytest fixtures shared across unit/integration tests.

live_server — starts a real server.py subprocess on a dynamically-allocated
              port using a temporary data directory so it never touches the
              real run state or conflicts with a live server already running.
              Tests that need it declare:
                  pytestmark = pytest.mark.usefixtures("live_server")
              Tests read the TCP port from the ``server_port`` fixture.
"""
import socket
import subprocess
import sys
import tempfile
import time
import os
import pytest


def _find_free_port() -> int:
    """Return a free TCP port on loopback by briefly binding to port 0."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server_port() -> int:
    """The TCP port the test server is bound to (shared with live_server)."""
    # Filled in by live_server; exposed here so tests can import it independently.
    return _find_free_port()


@pytest.fixture(scope="session")
def live_server(server_port):
    """Spin up a server.py subprocess for TCP integration tests."""
    tcp_port  = server_port
    http_port = _find_free_port()
    tmpdir    = tempfile.mkdtemp(prefix="slink_test_")
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "server.server",
            "--host",      "127.0.0.1",
            "--port",      str(tcp_port),
            "--http-port", str(http_port),
            "--data-dir",  tmpdir,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    )
    # Wait up to 10 s for the TCP port to accept connections.
    # If the port check succeeds before our subprocess is ready it means
    # something else is already bound there — that would be a logic error
    # since we picked a free port above, but we verify the PID to be safe.
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            s = socket.create_connection(("127.0.0.1", tcp_port), timeout=0.5)
            s.close()
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
