"""The Manager test harness: an isolated data directory (autouse) and a client on the app
`manager.main` builds, captured before it binds a socket. Shared by every test_manager_*
file through `pytest_plugins`."""
from __future__ import annotations

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from server import manager


@pytest.fixture(autouse=True)
def manager_dir(tmp_path, monkeypatch):
    directory = tmp_path / "runs"
    directory.mkdir()
    monkeypatch.setattr(manager, "MANAGER_DIR", str(directory))
    monkeypatch.setattr(manager, "REGISTRY_PATH", str(directory / "registry.json"))
    return directory


@pytest_asyncio.fixture
async def manager_client(monkeypatch):
    """Capture the app built by main, then serve it with an isolated test client."""
    captured = {}

    class AppCaptured(Exception):
        pass

    class Runner:
        def __init__(self, app):
            captured["app"] = app

        async def setup(self):
            pass

    class Site:
        def __init__(self, runner, host, port):
            pass

        async def start(self):
            raise AppCaptured

    with monkeypatch.context() as lifecycle:
        lifecycle.setattr(manager.web, "AppRunner", Runner)
        lifecycle.setattr(manager.web, "TCPSite", Site)
        with pytest.raises(AppCaptured):
            await manager.main("127.0.0.1", 0)

    async with TestClient(TestServer(captured["app"])) as client:
        yield client
