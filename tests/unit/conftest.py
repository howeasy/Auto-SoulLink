"""
Pytest fixtures shared across unit/integration tests.

live_server — starts a real server.py subprocess on 127.0.0.1:54321 using a
              temporary data directory so it never touches the real run state.
              Tests that need it declare:
                  pytestmark = pytest.mark.usefixtures("live_server")
"""
import socket
import subprocess
import sys
import tempfile
import time
import os
import pytest


@pytest.fixture(scope="session")
def live_server():
    """Spin up a server.py subprocess for TCP integration tests."""
    tmpdir = tempfile.mkdtemp(prefix="slink_test_")
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "server.server",
            "--host",     "127.0.0.1",
            "--port",     "54321",
            "--http-port", "54380",
            "--data-dir", tmpdir,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    )
    # Wait up to 10 s for the TCP port to accept connections
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            s = socket.create_connection(("127.0.0.1", 54321), timeout=0.5)
            s.close()
            break
        except OSError:
            time.sleep(0.1)
    else:
        proc.terminate()
        pytest.fail("live_server: server did not start within 10 seconds")

    yield proc

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
