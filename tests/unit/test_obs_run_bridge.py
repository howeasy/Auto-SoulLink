import json

import pytest

from server.obs_controller import OBSController
from server.obs_run_bridge import OBSRunBridge


def test_managed_controller_never_loads_or_overwrites_legacy_global_rules(tmp_path):
    path = tmp_path / "obs.json"
    content = json.dumps({"enabled": True, "triggers": [{"event": "capture", "scene": "Old"}]}).encode()
    path.write_bytes(content)
    controller = OBSController(str(path), managed=True)
    assert not controller._config["enabled"] and not controller._config["triggers"]
    controller.save_config()
    assert path.read_bytes() == content
    batches = []
    controller.event_sink = batches.append
    controller.submit_fired([["capture", "a", {}]])
    assert batches == [[["capture", "a", {}]]]


class Controller:
    def __init__(self):
        self.calls = []
        self.result = {"ok": True}

    async def apply_new_config(self, config):
        self._config = config
        self.calls.append(("config", config))

    def get_status(self):
        return {"available": True, "connections": {pid: {"status": "connected"} for pid in ("a", "b")}}

    async def test_scene(self, player, scene):
        self.calls.append((player, scene))
        return self.result


@pytest.mark.asyncio
async def test_execution_requires_applied_revision_and_is_idempotent():
    controller = Controller()
    bridge = OBSRunBridge(controller, "run_one", 8090)
    config = {"enabled": True, "connections": {pid: {"host": "localhost", "port": 4455} for pid in ("a", "b")}}
    await bridge.apply(3, config)
    await bridge.apply(3, config)
    assert len(controller.calls) == 1
    assert not (await bridge.execute(2, "wrong-revision", "a", "Scene"))["ok"]
    assert (await bridge.execute(3, "accepted", "a", "Scene"))["ok"]
    assert (await bridge.execute(3, "accepted", "a", "Scene"))["ok"]
    assert controller.calls[-1] == ("a", "Scene") and len(controller.calls) == 2
    with pytest.raises(ValueError, match="newer"):
        await bridge.apply(2, config)
    with pytest.raises(ValueError, match="different settings"):
        await bridge.apply(3, {**config, "enabled": False})
    assert controller._config["triggers"] == []


@pytest.mark.asyncio
async def test_uncertain_websocket_result_stays_unconfirmed():
    controller = Controller()
    bridge = OBSRunBridge(controller, "run_one", 8090)
    bridge.revision = 1
    controller.result = {"ok": False, "confirmed": False, "error": "Connection lost"}
    result = await bridge.execute(1, "uncertain", "b", "Scene")
    assert not result["confirmed"] and result["error"] == "Connection lost"
