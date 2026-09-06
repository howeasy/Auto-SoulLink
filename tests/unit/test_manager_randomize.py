"""The restricted RBY publisher refuses without altering existing run evidence.

Legacy UPR subprocess/scanner component tests remain in test_upr_pipeline.py.
Those components cannot authorize Manager publication before the full catalog,
semantic scan and final-output contract are implemented.
"""
import copy
import json

import pytest

from server import manager as mgr


class Request:
    def __init__(self, run_id, body):
        self.match_info = {"run_id": run_id}
        self.body = body
        self.remote = "127.0.0.1"
        self.host = "localhost"

    async def json(self):
        if self.body is None:
            raise ValueError("invalid JSON")
        return self.body


_Request = Request  # Existing cartridge-binding tests reuse this request fixture.


@pytest.fixture
def manager_dir(tmp_path, monkeypatch):
    directory = tmp_path / "runs"
    directory.mkdir()
    monkeypatch.setattr(mgr, "MANAGER_DIR", str(directory))
    monkeypatch.setattr(mgr, "REGISTRY_PATH", str(directory / "registry.json"))
    (directory / "run_test").mkdir()
    mgr._save_registry([{"run_id": "run_test", "name": "test", "tcp_port": 1,
                         "http_port": 2, "status": "stopped", "pid": None,
                         "rules": {"explode_mode": True}}])
    return directory


async def post(body, run_id="run_test"):
    manager = mgr.RunManager("127.0.0.1")
    response = await manager.handle_randomize(Request(run_id, body))
    return response.status, json.loads(response.text)


@pytest.mark.asyncio
async def test_unknown_run_keeps_404(manager_dir):
    status, body = await post({}, "missing")
    assert status == 404 and body["ok"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [None, [], "not an object"])
async def test_invalid_request_keeps_400(manager_dir, payload):
    status, body = await post(payload)
    assert status == 400 and body["ok"] is False


@pytest.mark.asyncio
async def test_missing_arguments_are_named(manager_dir):
    status, body = await post({"jar": "provided"})
    assert status == 400 and "settings" in body["error"] and "rom_a" in body["error"]


@pytest.mark.asyncio
async def test_restricted_publisher_never_invokes_legacy_pipeline_or_records_success(manager_dir, monkeypatch):
    from server import upr_pipeline

    def forbidden(*args, **kwargs):
        pytest.fail("restricted publisher invoked Java or legacy scanner")
    monkeypatch.setattr(upr_pipeline, "prepare_pair", forbidden)
    before = (manager_dir / "registry.json").read_bytes()
    status, body = await post({"jar": "user.jar", "settings": "settings.rnqs", "rom_a": "red.gb", "rom_b": "yellow.gb"})
    assert status == 409 and body["available"] is False
    assert body["reason_code"] == "rby_provenance_publisher_unavailable"
    assert mgr.RunManager.randomization_availability()["reason"] == body["error"]
    assert (manager_dir / "registry.json").read_bytes() == before
    assert not (manager_dir / "run_test" / "roms").exists()
    assert not (manager_dir / "run_test" / "rom_contract.json").exists()


@pytest.mark.asyncio
async def test_restriction_preserves_old_requested_settings_and_unverified_evidence(manager_dir):
    runs = mgr._load_registry()
    runs[0]["randomizer"] = {"settings_sha256": "old", "categories": ["wild"], "players": {"a": {"seed": "1"}}}
    mgr._save_registry(runs)
    before = copy.deepcopy(runs)
    status, body = await post({"jar": "user.jar", "settings": "settings.rnqs", "rom_a": "red.gb", "rom_b": "blue.gb"})
    assert status == 409 and body["ok"] is False
    assert mgr._load_registry() == before


@pytest.mark.asyncio
async def test_bound_cartridge_run_still_requires_a_new_run(manager_dir):
    runs = mgr._load_registry()
    runs[0]["cartridges"] = {"a": {"variant": "red"}}
    mgr._save_registry(runs)
    status, body = await post({})
    assert status == 400 and "new run" in body["error"]
