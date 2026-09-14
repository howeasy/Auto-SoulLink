"""Manager creates a NEW Gen 1 run resumed from a closed predecessor (owner policy P2a): refused
with the audit's reasons, or created with the rules imported and the resume contract published."""
import json
from pathlib import Path

import pytest

from server import gen1_admission, manager
from server.gen1_engine_signals import SAVE_PROJECTION
from server.gen1_run_config import open_runtime
from server.gen1_run_resume import COMPONENT
from tests.unit.test_gen1_run_resume import entry, predecessor
from tests.unit.test_gen1_sessions import contract


class Request:
    def __init__(self, body, **match):
        self.body = body
        self.match_info = match

    async def json(self):
        return self.body


@pytest.fixture
def registry(tmp_path, monkeypatch):
    runs = []
    monkeypatch.setattr(manager, "MANAGER_DIR", str(tmp_path))
    monkeypatch.setattr(manager, "_load_registry", lambda: runs.copy())
    monkeypatch.setattr(manager, "_save_registry", lambda value: runs.__setitem__(slice(None), value))
    monkeypatch.setattr(gen1_admission, "clean_contract", lambda paths: contract("red", "blue"))

    async def spawn(run, *args, **kwargs):
        return 12345
    monkeypatch.setattr(manager, "_spawn_run", spawn)
    return runs


def body(**more):
    return {"name": "Resumed pair", "rom_a": "a.gb", "rom_b": "b.gb", "start": False, **more}


@pytest.mark.asyncio
async def test_unknown_or_running_predecessor_is_refused_with_reasons(registry, tmp_path):
    handler = manager.RunManager("127.0.0.1")
    response = await handler.handle_create_gen1(Request(body(resume_from="run_nope")))
    assert response.status == 404 and not json.loads(response.text)["ok"]
    predecessor(tmp_path / "run_pred")
    registry.append(entry("run_pred", status="running", pid=4242))
    response = await handler.handle_create_gen1(Request(body(resume_from="run_pred")))
    result = json.loads(response.text)
    assert response.status == 409 and not result["ok"]
    assert any("running" in reason for reason in result["reasons"]) and len(registry) == 1


@pytest.mark.asyncio
async def test_unwitnessed_predecessor_is_refused_and_nothing_is_created(registry, tmp_path):
    predecessor(tmp_path / "run_pred", witnesses=("a",))
    registry.append(entry("run_pred"))
    response = await manager.RunManager("127.0.0.1").handle_create_gen1(Request(body(resume_from="run_pred")))
    result = json.loads(response.text)
    assert response.status == 409 and any("witness" in reason for reason in result["reasons"])
    assert len(registry) == 1 and not [p.name for p in tmp_path.iterdir() if p.name.startswith("run_") and p.name != "run_pred"]


@pytest.mark.asyncio
async def test_clean_predecessor_creates_a_resumed_run_with_the_contract_published(registry, tmp_path):
    predecessor(tmp_path / "run_pred")
    registry.append(entry("run_pred"))
    handler = manager.RunManager("127.0.0.1")
    response = await handler.handle_create_gen1(Request(body(resume_from="run_pred", rules={"type_lock": True})))
    result = json.loads(response.text)
    assert response.status == 200, result
    run = result["run"]
    assert run["resume"]["from_run"] == "run_pred" and set(run["resume"]["required"]) == {"a", "b"}
    assert set(run["resume"]["required"]["a"]) == {"digest", "projection", "witness_index", "operation_id"}
    assert run["resume"]["required"]["a"]["projection"] == SAVE_PROJECTION
    # The client worker's launch contract narrows this per player (runtime_launcher.player_resume).
    from server.runtime_launcher import player_resume
    assert player_resume(run["resume"], "b") == {"from_run": "run_pred", "required_digest": run["resume"]["required"]["b"]["digest"],
                                                 "projection": SAVE_PROJECTION}
    assert "rules" not in run["resume"]  # the registry publishes the contract, not the imported state
    assert registry[-1]["run_id"] == run["run_id"] and registry[-1]["resume"] == run["resume"]
    assert run["type_lock"] is True and run["species_lock"] is False
    shown = await handler.handle_run(Request({}, run_id=run["run_id"]))
    assert shown.status == 200 and json.loads(shown.text)["run"]["resume"] == run["resume"]
    missing = await handler.handle_run(Request({}, run_id="run_nope"))
    assert missing.status == 404
    runtime = open_runtime(Path(tmp_path) / run["run_id"])
    try:
        document = runtime.state().document()
        assert document["components"][COMPONENT]["from_run"] == "run_pred"
        assert document["components"][COMPONENT]["pending"] == {"a": True, "b": True}
        assert document["rules"]["core"]["links"][0]["area_id"] == "oaks_lab"
        assert runtime.state().rules.type_lock and runtime.state().rules.pokeballs_obtained == {"a": True, "b": True}
    finally:
        runtime.close()


@pytest.mark.asyncio
async def test_resume_keys_are_rejected_when_absent_or_malformed(registry):
    response = await manager.RunManager("127.0.0.1").handle_create_gen1(Request(body(resume_from=7)))
    assert response.status == 400
