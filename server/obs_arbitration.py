"""Manager-owned OBS rules and ordered scene decisions per OBS endpoint.

This module never opens a WebSocket. The selected source run executes decisions
through an injected private HTTP transport and reports the actual result.
"""

import asyncio
import copy
import ipaddress
import json
import uuid
from collections import OrderedDict, deque
from pathlib import Path

from server.json_files import atomic_write_json
from server.obs_controller import classify_area


class OBSConfigError(ValueError):
    pass


def default_config():
    return {"schema": 1, "revision": 0, "enabled": False, "legacy_imported": False,
            "connections": {pid: {"host": "", "port": 4455, "password": ""} for pid in ("a", "b")}, "rules": []}


def endpoint(connection):
    host = connection.get("host", "").strip().lower().rstrip(".")
    if not host:
        return None
    try:
        address = ipaddress.ip_address(host.strip("[]"))
        host = str(address.ipv4_mapped or address) if isinstance(address, ipaddress.IPv6Address) else str(address)
        if ipaddress.ip_address(host).is_loopback:
            host = "localhost"
    except ValueError:
        pass
    return host, connection["port"]


def match_rules(config, run_id, fired):
    """First matching rule wins per endpoint within one event batch."""
    winners = {}
    if not config["enabled"]:
        return []
    for rule in config["rules"]:
        if not rule["enabled"] or rule["run_id"] != run_id:
            continue
        for event, player, metadata in fired:
            if event != rule["event"] or rule["player_filter"] not in ("any", player):
                continue
            area = rule["area_id_filter"]
            if area and (classify_area(metadata.get("area_id", "")) != area[6:] if area.startswith("group:")
                         else metadata.get("area_id") != area):
                continue
            targets = ["a", "b"] if rule["target"] == "both" else [player if rule["target"] == "own" else rule["target"]]
            for target in targets:
                key = endpoint(config["connections"][target])
                if key is not None and key not in winners:
                    winners[key] = {"endpoint": key, "player": target, "scene": rule["scene"], "rule_id": rule["id"]}
            break
    return list(winners.values())


class OBSArbiter:
    def __init__(self, path, run_lookup, execute):
        self.path = Path(path)
        self.run_lookup, self.execute = run_lookup, execute
        self.config = default_config()
        self.load_error = None
        self.lock = asyncio.Lock()
        self.queues, self.workers = {}, {}
        self.records = deque(maxlen=100)
        self.blocked_endpoints = {}
        self.receipts = OrderedDict()
        self.sequence = 0
        try:
            if self.path.exists():
                self.config = self._read()
        except OBSConfigError as error:
            self.load_error = str(error)

    def _read(self):
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
            if document.get("schema") != 1 or type(document.get("revision")) is not int or document["revision"] < 0:
                raise ValueError("unsupported OBS configuration")
            return self._validate(document, old=document, check_runs=False)
        except (OSError, ValueError, TypeError, AttributeError, KeyError) as error:
            raise OBSConfigError("OBS settings could not be read. The original file has been preserved.") from error

    def _validate(self, document, *, old, check_runs=True):
        if not isinstance(document, dict) or type(document.get("enabled")) is not bool:
            raise OBSConfigError("Choose whether OBS automation is enabled.")
        connections = document.get("connections")
        if not isinstance(connections, dict) or set(connections) != {"a", "b"}:
            raise OBSConfigError("Provide both player connections.")
        result = {**default_config(), "revision": old["revision"], "enabled": document["enabled"],
                  "legacy_imported": old.get("legacy_imported", False)}
        for pid, connection in connections.items():
            if not isinstance(connection, dict):
                raise OBSConfigError("Invalid OBS connection.")
            host, port = connection.get("host", ""), connection.get("port", 4455)
            if not isinstance(host, str) or len(host) > 253 or any(char in host for char in "/\\@?#\r\n \t"):
                raise OBSConfigError("Use an OBS hostname or IP address, without a URL or path.")
            if type(port) is not int or not 1 <= port <= 65535:
                raise OBSConfigError("OBS ports must be between 1 and 65535.")
            password = connection.get("password", old["connections"][pid].get("password", ""))
            if not isinstance(password, str) or len(password) > 1024:
                raise OBSConfigError("Invalid OBS password.")
            result["connections"][pid] = {"host": host.strip(), "port": port, "password": password}
        rules = document.get("rules")
        if not isinstance(rules, list) or len(rules) > 200:
            raise OBSConfigError("Provide up to 200 OBS rules.")
        existing = {rule["id"]: rule for rule in old["rules"]}
        seen = set()
        for source in rules:
            if not isinstance(source, dict):
                raise OBSConfigError("Invalid OBS rule.")
            rule = {"id": source.get("id") or uuid.uuid4().hex, "run_id": source.get("run_id"),
                    "enabled": source.get("enabled", False), "event": source.get("event", ""),
                    "player_filter": source.get("player_filter", "any"), "target": source.get("target", "own"),
                    "scene": source.get("scene", ""), "area_id_filter": source.get("area_id_filter", "")}
            if not isinstance(rule["id"], str) or not rule["id"] or len(rule["id"]) > 128 or rule["id"] in seen:
                raise OBSConfigError("Every rule needs a unique identifier.")
            seen.add(rule["id"])
            if type(rule["enabled"]) is not bool or rule["player_filter"] not in ("any", "a", "b") or rule["target"] not in ("own", "both", "a", "b"):
                raise OBSConfigError("Choose valid rule players and an enabled state.")
            if any(not isinstance(rule[key], str) or len(rule[key]) > 300 for key in ("event", "scene", "area_id_filter")) or not rule["event"] or not rule["scene"]:
                raise OBSConfigError("Every rule needs an event and scene name.")
            previous = existing.get(rule["id"])
            if rule["run_id"] is None:
                if rule["enabled"] or check_runs and not (previous and previous.get("run_id") is None):
                    raise OBSConfigError("Choose a source run before adding or enabling this rule.")
            elif not isinstance(rule["run_id"], str):
                raise OBSConfigError("Choose a source run.")
            elif check_runs and (not previous or previous.get("run_id") != rule["run_id"]) and self.run_lookup(rule["run_id"]) is None:
                raise OBSConfigError("The chosen source run no longer exists.")
            result["rules"].append(rule)
        return result

    async def update(self, document):
        async with self.lock:
            if self.path.exists():
                current = self._read()  # never overwrite externally damaged settings
                if current["revision"] != self.config["revision"]:
                    self.config = current
            if not isinstance(document, dict) or type(document.get("revision")) is not int or document.get("revision") != self.config["revision"]:
                raise OBSConfigError("OBS settings changed. Reload before saving.")
            result = self._validate(document, old=self.config)
            result["revision"] += 1
            atomic_write_json(self.path, result)
            self.config, self.load_error = result, None
            return self.status()

    async def import_legacy(self, paths):
        async with self.lock:
            if self.load_error or self.config["legacy_imported"]:
                return
            paths = [Path(path) for path in paths if Path(path).exists()]
            if not paths:
                self.config["legacy_imported"] = True
                return  # a read-only startup needs no empty settings file
            result = copy.deepcopy(self.config)
            for path in paths:
                path = Path(path)
                if not path.exists():
                    continue
                try:
                    legacy = json.loads(path.read_text(encoding="utf-8"))
                    # Credentials are retained, but imported rules are unassigned
                    # and disabled. No run is inferred from a directory or pin.
                    result["connections"] = copy.deepcopy(legacy.get("connections", result["connections"]))
                    for rule in legacy.get("triggers", []):
                        result["rules"].append({**rule, "id": uuid.uuid4().hex, "run_id": None, "enabled": False})
                except (OSError, ValueError, AttributeError, TypeError) as error:
                    self.load_error = "Legacy OBS settings could not be imported. The original files have been preserved."
                    raise OBSConfigError(self.load_error) from error
            result["legacy_imported"] = True
            result = self._validate(result, old=result, check_runs=False)
            result["revision"] += 1
            atomic_write_json(self.path, result)
            self.config = result

    def status(self):
        config = copy.deepcopy(self.config)
        for connection in config["connections"].values():
            connection["password_set"] = bool(connection.pop("password", ""))
        return {"config": config, "error": self.load_error, "records": list(self.records),
                "pending": sum(queue.qsize() for queue in self.queues.values()),
                "blocked_endpoints": [{"host": host, "port": port, "reason": reason}
                                      for (host, port), reason in self.blocked_endpoints.items()]}

    async def submit(self, run_id, batch_id, fired):
        if not isinstance(batch_id, str) or not batch_id or len(batch_id) > 128:
            raise OBSConfigError("Invalid OBS batch identity.")
        if not isinstance(fired, list) or len(fired) > 100:
            raise OBSConfigError("Invalid OBS event batch.")
        for item in fired:
            if (not isinstance(item, (list, tuple)) or len(item) != 3 or not isinstance(item[0], str)
                    or item[1] not in ("a", "b") or not isinstance(item[2], dict)
                    or not isinstance(item[2].get("area_id", ""), str)):
                raise OBSConfigError("Invalid OBS event.")
        async with self.lock:
            run = self.run_lookup(run_id)
            if not run or run.get("status") != "running":
                raise OBSConfigError("The source run is not running.")
            key = run_id, batch_id
            if key in self.receipts:
                return dict(self.receipts[key], duplicate=True)
            if self.load_error:
                raise OBSConfigError(self.load_error)
            winners = match_rules(self.config, run_id, fired)
            return self._enqueue(run_id, batch_id, winners)

    async def submit_scene(self, run_id, player, scene):
        if player not in ("a", "b") or not isinstance(scene, str) or not scene or len(scene) > 300:
            raise OBSConfigError("Choose an OBS player and scene.")
        async with self.lock:
            run = self.run_lookup(run_id)
            if not run or run.get("status") != "running":
                raise OBSConfigError("Choose a running source run.")
            target = endpoint(self.config["connections"][player])
            if target is None:
                raise OBSConfigError("Configure this OBS connection before testing a scene.")
            return self._enqueue(run_id, "manual-" + uuid.uuid4().hex,
                [{"endpoint": target, "player": player, "scene": scene, "rule_id": None}])

    def _enqueue(self, run_id, batch_id, winners):
        if self.load_error:
            raise OBSConfigError(self.load_error)
        key = run_id, batch_id
        if any(self.queues.get(tuple(win["endpoint"])) and self.queues[tuple(win["endpoint"])].full() for win in winners):
            raise OBSConfigError("OBS scene queue is full; this batch was not accepted.")
        self.sequence += 1
        receipt = {"sequence": self.sequence, "revision": self.config["revision"], "decisions": len(winners)}
        self.receipts[key] = receipt
        while len(self.receipts) > 10000:
            self.receipts.popitem(last=False)
        for winner in winners:
            target = tuple(winner["endpoint"])
            queue = self.queues.setdefault(target, asyncio.Queue(maxsize=100))
            decision = {**winner, **receipt, "run_id": run_id, "batch_id": batch_id,
                        "config": copy.deepcopy(self.config)}
            queue.put_nowait(decision)
            if target not in self.workers or self.workers[target].done():
                self.workers[target] = asyncio.create_task(self._worker(target, queue))
        return dict(receipt)

    async def _worker(self, target, queue):
        while True:
            decision = await queue.get()
            record = {key: value for key, value in decision.items() if key != "config"}
            try:
                if target in self.blocked_endpoints:
                    result = {"ok": False, "error": self.blocked_endpoints[target]}
                elif decision["revision"] != self.config["revision"]:
                    result = {"ok": False, "error": "Configuration changed before this scene was applied."}
                else:
                    result = await self.execute(decision)
                if result.get("confirmed") is False:
                    self.blocked_endpoints[target] = "A previous scene has an unconfirmed result. Check OBS before resuming this endpoint."
                record.update(state="applied" if result.get("ok") else "failed", error=result.get("error"))
            except asyncio.CancelledError:
                record.update(state="interrupted", error="OBS execution was interrupted; application is unconfirmed.")
                raise
            except Exception as error:
                record.update(state="failed", error=str(error))
                self.blocked_endpoints[target] = "Scene execution ended without confirmation. Check OBS before resuming this endpoint."
            finally:
                self.records.appendleft(record)
                queue.task_done()

    async def close(self):
        for worker in self.workers.values():
            worker.cancel()
        await asyncio.gather(*self.workers.values(), return_exceptions=True)
        self.workers.clear()
