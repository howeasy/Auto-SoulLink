import asyncio
import copy
import json

import pytest

from server.obs_arbitration import OBSArbiter, OBSConfigError, default_config, match_rules


def configured():
    config = default_config()
    config.update(enabled=True, revision=1)
    config["connections"] = {pid: {"host": "localhost", "port": 4455, "password": "private"} for pid in ("a", "b")}
    config["rules"] = [{"id": "high", "run_id": "run_one", "enabled": True, "event": "capture", "player_filter": "any",
                        "target": "both", "scene": "Caught", "area_id_filter": ""},
                       {"id": "low", "run_id": "run_one", "enabled": True, "event": "battle_start", "player_filter": "any",
                        "target": "own", "scene": "Battle", "area_id_filter": ""}]
    return config


def lookup(run_id):
    return {"run_id": run_id, "status": "running"} if run_id in ("run_one", "run_two") else None


def test_rule_priority_resolves_a_batch_once_per_shared_endpoint():
    config = configured()
    winners = match_rules(config, "run_one", [["battle_start", "b", {}], ["capture", "a", {}]])
    assert len(winners) == 1 and winners[0]["scene"] == "Caught"
    assert winners[0]["rule_id"] == "high"
    assert not match_rules(config, "run_two", [["capture", "a", {}]])


def test_independent_endpoints_preserve_target_and_area_filters():
    config = configured()
    config["connections"]["b"]["port"] = 4456
    config["rules"][0].update(area_id_filter="group:route", player_filter="a")
    assert not match_rules(config, "run_one", [["capture", "b", {"area_id": "route_1"}]])
    assert not match_rules(config, "run_one", [["capture", "a", {"area_id": "pallet_town"}]])
    winners = match_rules(config, "run_one", [["capture", "a", {"area_id": "route_1"}]])
    assert [winner["player"] for winner in winners] == ["a", "b"]


@pytest.mark.asyncio
async def test_accepted_batches_run_in_arrival_order_without_coalescing(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()
    executing, peak, calls = 0, 0, []
    async def execute(decision):
        nonlocal executing, peak
        executing += 1
        peak = max(peak, executing)
        calls.append((decision["run_id"], decision["sequence"], decision["scene"]))
        entered.set()
        await release.wait()
        executing -= 1
        return {"ok": True}
    arbiter = OBSArbiter(tmp_path / "obs.json", lookup, execute)
    arbiter.config = configured()
    arbiter.config["rules"].append({**arbiter.config["rules"][0], "id": "second-run", "run_id": "run_two", "scene": "Other"})
    await arbiter.submit("run_one", "batch-a", [["capture", "a", {}]])
    await asyncio.wait_for(entered.wait(), 2)
    await arbiter.submit("run_two", "batch-b", [["capture", "b", {}]])
    await arbiter.submit("run_one", "batch-c", [["battle_start", "a", {}]])
    release.set()
    await asyncio.wait_for(asyncio.gather(*(q.join() for q in arbiter.queues.values())), 2)
    assert calls == [("run_one", 1, "Caught"), ("run_two", 2, "Other"), ("run_one", 3, "Battle")]
    assert peak == 1
    assert all(record["state"] == "applied" for record in arbiter.records)
    await arbiter.close()


@pytest.mark.asyncio
async def test_duplicate_batch_does_not_restore_an_earlier_scene(tmp_path):
    calls = []
    async def execute(decision):
        calls.append(decision["batch_id"])
        return {"ok": True}
    arbiter = OBSArbiter(tmp_path / "obs.json", lookup, execute)
    arbiter.config = configured()
    first = await arbiter.submit("run_one", "same", [["capture", "a", {}]])
    duplicate = await arbiter.submit("run_one", "same", [["capture", "a", {}]])
    assert first["sequence"] == duplicate["sequence"] and duplicate["duplicate"]
    await asyncio.gather(*(q.join() for q in arbiter.queues.values()))
    assert calls == ["same"]
    await arbiter.close()


@pytest.mark.asyncio
async def test_application_failure_and_config_revision_remain_visible(tmp_path):
    async def execute(decision):
        return {"ok": False, "error": "OBS refused the scene"}
    arbiter = OBSArbiter(tmp_path / "obs.json", lookup, execute)
    arbiter.config = configured()
    await arbiter.submit("run_one", "failed", [["capture", "a", {}]])
    await asyncio.gather(*(q.join() for q in arbiter.queues.values()))
    status = arbiter.status()
    assert status["records"][0]["revision"] == 1
    assert status["records"][0]["state"] == "failed"
    assert status["records"][0]["error"] == "OBS refused the scene"
    assert "private" not in json.dumps(status)
    await arbiter.close()


@pytest.mark.asyncio
async def test_legacy_rules_are_unassigned_disabled_and_original_file_is_unchanged(tmp_path):
    legacy = tmp_path / "legacy.json"
    original = json.dumps({"enabled": True, "connections": configured()["connections"],
                           "triggers": [{"event": "capture", "scene": "Caught", "target": "both"}]}).encode()
    legacy.write_bytes(original)
    arbiter = OBSArbiter(tmp_path / "manager.json", lookup, None)
    await arbiter.import_legacy([legacy])
    rule = arbiter.config["rules"][0]
    assert rule["run_id"] is None and not rule["enabled"]
    assert legacy.read_bytes() == original
    assert arbiter.config["legacy_imported"]
    # Import is idempotent; no guessed assignment even if exactly one run exists.
    await arbiter.import_legacy([legacy])
    assert len(arbiter.config["rules"]) == 1
    edit = copy.deepcopy(arbiter.config)
    edit["rules"][0]["enabled"] = True
    with pytest.raises(OBSConfigError, match="source run"):
        await arbiter.update(edit)
    edit["rules"][0]["run_id"] = "run_one"
    await arbiter.update(edit)
    assert arbiter.config["rules"][0]["enabled"]


@pytest.mark.asyncio
async def test_new_rules_require_explicit_existing_source_runs(tmp_path):
    arbiter = OBSArbiter(tmp_path / "obs.json", lookup, None)
    document = configured()
    document["revision"] = 0
    for bad in (None, "missing"):
        document["rules"][0]["run_id"] = bad
        with pytest.raises(OBSConfigError, match="source run"):
            await arbiter.update(document)
    assert not arbiter.path.exists()


@pytest.mark.asyncio
async def test_corrupt_config_is_preserved_and_stale_revisions_cannot_save(tmp_path):
    path = tmp_path / "obs.json"
    path.write_bytes(b"{unfinished")
    arbiter = OBSArbiter(path, lookup, None)
    assert arbiter.status()["error"]
    with pytest.raises(OBSConfigError, match="preserved"):
        await arbiter.update(default_config())
    assert path.read_bytes() == b"{unfinished"
    other = OBSArbiter(tmp_path / "valid.json", lookup, None)
    await other.update(default_config())
    with pytest.raises(OBSConfigError, match="changed"):
        await other.update(default_config())
