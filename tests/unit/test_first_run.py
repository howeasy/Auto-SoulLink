"""First-run blockers: the ways a new user ends up stuck with no idea why.

Each of these was real. They are pinned here because they are all *silent* failures — nothing
crashes, nothing logs, the user just sees an emulator that never connects or a document telling
them to go find a file that is already in the repo.
"""
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return f.read()


def test_every_client_defaults_to_the_documented_tcp_port():
    """gen3_frlge_client.lua defaulted to 54322 while its own usage comment — and 13 other
    references — said 54321. Loading it the documented way produced a client that connected
    nowhere, with no error, forever."""
    ports = set()
    lua_dir = os.path.join(REPO, "lua")
    for root, _d, files in os.walk(lua_dir):
        if "tests" in root:
            continue
        for fn in files:
            if not fn.endswith(".lua"):
                continue
            for m in re.finditer(r"SERVER_PORT\s*=\s*\w*\s*or\s*(\d+)", _read(
                    os.path.relpath(os.path.join(root, fn), REPO).replace("\\", "/"))):
                ports.add(int(m.group(1)))
    assert ports <= {54321}, f"client default ports disagree with the docs: {sorted(ports)}"


def test_the_luasocket_dll_is_actually_present():
    """Three documents told the user to copy this out of an Archipelago install. It is committed,
    and not gitignored — so anyone without Archipelago concluded they were blocked."""
    assert os.path.exists(os.path.join(REPO, "lua", "x64", "socket-windows-5-4.dll"))


def test_no_doc_still_claims_the_dll_must_be_fetched():
    for rel in ("lua/x64/README.md", "docs/REFERENCE.md", "tests/TESTING.md"):
        body = _read(rel)
        # The file may legitimately mention Archipelago as a RESTORE path; what it must not do is
        # present fetching it as a required setup step.
        assert "Copy `socket-windows-5-4.dll` from" not in body, rel


def test_a_failed_connect_is_reported():
    """The connector retried silently. 'Nothing happens' is the worst first-run experience
    because there is no thread to pull on."""
    src = _read("lua/connector.lua")
    assert "Cannot reach the server" in src
    assert "_fail_logged" in src, "the message must be rate-limited, not printed every backoff tick"


def test_bind_failures_explain_themselves():
    """A bare OSError traceback on a taken port reads as 'SLink is broken'."""
    src = _read("server/server.py")
    assert "Cannot listen on TCP" in src
    assert "Cannot listen on HTTP" in src
    assert src.count("raise SystemExit(") >= 2


def test_the_manager_keeps_its_children_stderr():
    """Runs that died at startup vanished without trace: stderr went to DEVNULL and the Manager
    just showed them as stopped."""
    src = _read("server/manager.py")
    assert "spawn.log" in src
    assert "stderr=asyncio.subprocess.DEVNULL" not in src


def test_readme_explains_which_port_is_which():
    """8080 vs 8090 vs 8081 is the most common first-run confusion."""
    body = _read("README.md")
    for token in ("8080", "8090", "8081"):
        assert token in body, f"README never mentions port {token}"
