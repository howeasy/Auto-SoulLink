"""Run-side forwarding and private OBS execution for a managed run."""

import asyncio
import copy
import uuid
from collections import OrderedDict

import aiohttp


class OBSRunBridge:
    def __init__(self, controller, run_id, manager_port):
        self.controller, self.run_id = controller, run_id
        self.manager_url = f"http://127.0.0.1:{manager_port}"
        self.revision = None
        self.forwarding_error = None
        self.queue = asyncio.Queue(maxsize=100)
        self.worker = None
        self.apply_lock = asyncio.Lock()
        self.execution_lock = asyncio.Lock()
        self.receipts = OrderedDict()

    def submit(self, fired):
        if not fired:
            return
        try:
            self.queue.put_nowait({"run_id": self.run_id, "batch_id": uuid.uuid4().hex, "fired": copy.deepcopy(fired)})
        except asyncio.QueueFull:
            self.forwarding_error = "OBS forwarding queue is full; an event batch was not submitted."
            return
        if self.worker is None or self.worker.done():
            self.worker = asyncio.create_task(self._forward())

    async def _forward(self):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            while not self.queue.empty():
                batch = self.queue.get_nowait()
                try:
                    async with session.post(self.manager_url + "/_internal/obs/events", json=batch) as response:
                        result = await response.json()
                        if response.status != 202 or result.get("ok") is not True:
                            self.forwarding_error = result.get("error", "The manager did not accept an OBS batch.")
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                    # Do not replay an ambiguously accepted batch after a network
                    # failure or manager restart. Surface the unknown outcome.
                    self.forwarding_error = "An OBS event batch could not be confirmed by the manager. It was not retried."
                finally:
                    self.queue.task_done()

    async def apply(self, revision, config):
        if type(revision) is not int or revision < 0:
            raise ValueError("Invalid OBS configuration revision")
        async with self.execution_lock:
            async with self.apply_lock:
                if self.revision is not None and revision < self.revision:
                    raise ValueError("A newer OBS configuration is already applied")
                if not isinstance(config, dict) or type(config.get("enabled")) is not bool:
                    raise ValueError("Invalid OBS execution configuration")
                connections = config.get("connections")
                if not isinstance(connections, dict) or set(connections) != {"a", "b"}:
                    raise ValueError("Both OBS connections are required")
                clean = {"enabled": config["enabled"], "connections": {}, "triggers": []}
                for pid, connection in connections.items():
                    if not isinstance(connection, dict):
                        raise ValueError("Invalid OBS connection")
                    host, port, password = connection.get("host", ""), connection.get("port"), connection.get("password", "")
                    if (not isinstance(host, str) or not isinstance(password, str) or type(port) is not int
                            or not 1 <= port <= 65535 or any(char in host for char in "/\\@?#\r\n \t")):
                        raise ValueError("Invalid OBS connection")
                    clean["connections"][pid] = {"host": host, "port": port, "password": password}
                if revision == self.revision:
                    if clean != self.controller._config:
                        raise ValueError("This OBS revision was already applied with different settings")
                    return self.status()
                await self.controller.apply_new_config(clean)
                self.revision = revision
                return self.status()

    def status(self):
        return {**self.controller.get_status(), "applied_revision": self.revision,
                "forwarding_error": self.forwarding_error, "forwarding_pending": self.queue.qsize()}

    async def execute(self, revision, identity, player, scene):
        if type(revision) is not int:
            raise ValueError("Invalid OBS configuration revision")
        if player not in ("a", "b") or not isinstance(scene, str) or not scene or len(scene) > 300:
            raise ValueError("Choose an OBS player and scene")
        if not isinstance(identity, str) or not identity or len(identity) > 200:
            raise ValueError("Invalid scene decision identity")
        async with self.execution_lock:
            if identity in self.receipts:
                return copy.deepcopy(self.receipts[identity])
            if revision != self.revision:
                return {"ok": False, "error": "OBS configuration revision is not applied", "confirmed": True}
            try:
                # Connecting workers may have just received a new configuration.
                # This bounded wait does not claim readiness before identification.
                async with asyncio.timeout(5):
                    while self.controller.get_status()["available"] and self.controller.get_status()["connections"][player]["status"] in ("connecting", "disconnected"):
                        if not self.controller._config["connections"][player]["host"]:
                            break
                        await asyncio.sleep(.05)
            except TimeoutError:
                pass
            try:
                result = await asyncio.wait_for(self.controller.test_scene(player, scene), 10)
                result = {**result, "confirmed": result.get("confirmed", True)}
            except TimeoutError:
                result = {"ok": False, "confirmed": False, "error": "OBS scene application timed out; the result is unconfirmed."}
            self.receipts[identity] = result
            while len(self.receipts) > 10000:
                self.receipts.popitem(last=False)
            return copy.deepcopy(result)

    async def close(self):
        if self.worker is not None:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
            self.worker = None
