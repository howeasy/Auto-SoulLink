"""OBS reconnect attempts own and release their clients before replacement.

No sockets are opened. Events hold connection/cleanup boundaries and a controlled
sleep queue drives retries without waiting for production backoff intervals.
"""

import asyncio
from types import SimpleNamespace

import pytest
import pytest_asyncio

from server import obs_controller as obs


async def reached(event):
    await asyncio.wait_for(event.wait(), timeout=1)


class FakeClient:
    def __init__(self, *, failure=None, connect_gate=None, identify_gate=None,
                 close_gate=None):
        self.failure = failure
        self.connect_gate = connect_gate
        self.identify_gate = identify_gate
        self.close_gate = close_gate
        self.connecting = asyncio.Event()
        self.identifying = asyncio.Event()
        self.closing = asyncio.Event()
        self.closed = asyncio.Event()
        self.identified = False
        self.disconnect_calls = 0
        self.disconnect_cancelled = False
        self.url = None

    async def connect(self):
        self.connecting.set()
        if self.connect_gate is not None:
            await self.connect_gate.wait()
        if self.failure == "connect":
            raise OSError("connection failed")

    async def wait_until_identified(self):
        self.identifying.set()
        if self.identify_gate is not None:
            await self.identify_gate.wait()
        if self.failure == "identify":
            raise OSError("identification failed")
        self.identified = self.failure != "auth"
        return self.identified

    def is_identified(self):
        return self.identified

    async def disconnect(self):
        self.disconnect_calls += 1
        self.closing.set()
        try:
            if self.close_gate is not None:
                await self.close_gate.wait()
        except asyncio.CancelledError:
            self.disconnect_cancelled = True
            raise
        self.identified = False
        self.closed.set()
        if self.failure == "disconnect":
            raise OSError("already closed")


class ControlledSleep:
    def __init__(self):
        self.calls = asyncio.Queue()

    async def __call__(self, delay):
        release = asyncio.Event()
        self.calls.put_nowait((delay, release))
        await release.wait()

    async def next(self, expected):
        delay, release = await asyncio.wait_for(self.calls.get(), timeout=1)
        assert delay == expected
        return release


@pytest_asyncio.fixture
async def harness(tmp_path, monkeypatch):
    clock = ControlledSleep()
    planned = []
    created = []
    arrivals = asyncio.Queue()

    def make_client(**kwargs):
        client = planned.pop(0) if planned else FakeClient()
        client.url = kwargs["url"]
        created.append(client)
        arrivals.put_nowait(client)
        return client

    runtime = SimpleNamespace(**{**vars(asyncio), "sleep": clock})
    monkeypatch.setattr(obs, "asyncio", runtime)
    monkeypatch.setattr(obs, "_OBS_AVAILABLE", True)
    monkeypatch.setattr(obs, "simpleobsws", SimpleNamespace(WebSocketClient=make_client), raising=False)
    controller = obs.OBSController(str(tmp_path / "obs_config.json"))
    controller._config["connections"]["a"]["host"] = "fake-a"
    h = SimpleNamespace(controller=controller, planned=planned, created=created,
                        arrivals=arrivals, clock=clock, runtime=runtime)
    yield h
    # Release a deliberately held cleanup even when an assertion failed.
    for client in created:
        if client.close_gate is not None:
            client.close_gate.set()
    await asyncio.wait_for(controller.stop_workers(), timeout=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["connect", "identify", "auth", "timeout", "drop"])
async def test_attempt_is_closed_before_retry(harness, failure):
    h = harness
    first = FakeClient(failure=failure)
    h.planned.append(first)
    if failure == "timeout":
        async def expire_identification(awaitable, timeout):
            return await asyncio.wait_for(awaitable, timeout=0)
        h.runtime.wait_for = expire_identification
    await h.controller.connect_player("a")
    await reached(first.connecting)
    if failure == "drop":
        poll = await h.clock.next(1)
        first.identified = False
        poll.set()

    retry = await h.clock.next(5)
    assert first.closed.is_set()
    assert first.disconnect_calls == 1
    assert h.controller._clients["a"] is None
    assert h.controller._status["a"] == ("auth_failed" if failure == "auth" else "disconnected")

    # The next attempt starts only after the previous client has been closed.
    retry.set()
    await asyncio.wait_for(h.arrivals.get(), timeout=1)  # first attempt
    second = await asyncio.wait_for(h.arrivals.get(), timeout=1)
    assert second is not first
    assert first.closed.is_set()
    await h.controller.disconnect_player("a")
    assert second.closed.is_set()
    assert second.disconnect_calls == 1


@pytest.mark.asyncio
async def test_auth_failure_keeps_exponential_backoff(harness):
    h = harness
    h.planned.extend([FakeClient(failure="auth"), FakeClient(failure="auth"), FakeClient()])
    await h.controller.connect_player("a")
    (await h.clock.next(5)).set()
    (await h.clock.next(10)).set()
    connected_poll = await h.clock.next(1)
    h.created[-1].identified = False
    connected_poll.set()
    await h.clock.next(5)  # a successful identification resets the backoff
    assert all(client.closed.is_set() for client in h.created)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["connect", "identify", "connected", "backoff"])
async def test_disconnect_cancels_each_connection_phase(harness, phase):
    h = harness
    client = FakeClient(
        connect_gate=asyncio.Event() if phase == "connect" else None,
        identify_gate=asyncio.Event() if phase == "identify" else None,
        failure="auth" if phase == "backoff" else None,
    )
    h.planned.append(client)
    await h.controller.connect_player("a")
    task = h.controller._reconnect_tasks["a"]
    if phase == "connect":
        await reached(client.connecting)
    elif phase == "identify":
        await reached(client.identifying)
    else:
        await h.clock.next(5 if phase == "backoff" else 1)
    await h.controller.disconnect_player("a")
    assert task.done()
    assert client.closed.is_set()
    assert client.disconnect_calls == 1
    assert h.controller._clients["a"] is None
    assert h.controller._reconnect_tasks["a"] is None
    assert h.controller._status["a"] == "disconnected"


@pytest.mark.asyncio
async def test_reconnect_waits_for_cleanup_even_if_cancelled_during_cleanup(harness):
    h = harness
    first = FakeClient(failure="connect", close_gate=asyncio.Event())
    h.planned.append(first)
    await h.controller.connect_player("a")
    old_task = h.controller._reconnect_tasks["a"]
    await reached(first.closing)
    replacement = asyncio.create_task(h.controller.connect_player("a"))
    await asyncio.sleep(0)
    assert not replacement.done()
    assert len(h.created) == 1
    assert not first.disconnect_cancelled
    first.close_gate.set()
    await asyncio.wait_for(replacement, timeout=1)
    await h.clock.next(1)
    assert old_task.done()
    assert first.closed.is_set()
    assert first.disconnect_calls == 1
    assert not first.disconnect_cancelled
    assert len(h.created) == 2
    assert h.controller._clients["a"] is h.created[1]


@pytest.mark.asyncio
async def test_cancelled_reconnect_request_does_not_start_a_replacement(harness):
    h = harness
    first = FakeClient(close_gate=asyncio.Event())
    h.planned.append(first)
    await h.controller.connect_player("a")
    await h.clock.next(1)
    replacement = asyncio.create_task(h.controller.connect_player("a"))
    await reached(first.closing)
    replacement.cancel()
    first.close_gate.set()
    with pytest.raises(asyncio.CancelledError):
        await replacement
    assert first.closed.is_set()
    assert not first.disconnect_cancelled
    assert len(h.created) == 1
    assert h.controller._clients["a"] is None


@pytest.mark.asyncio
async def test_concurrent_disconnect_waits_for_reconnect_cleanup(harness):
    h = harness
    first = FakeClient(close_gate=asyncio.Event())
    h.planned.append(first)
    await h.controller.connect_player("a")
    await h.clock.next(1)
    reconnect = asyncio.create_task(h.controller.connect_player("a"))
    await reached(first.closing)
    disconnect = asyncio.create_task(h.controller.disconnect_player("a"))
    await asyncio.sleep(0)
    assert not reconnect.done() and not disconnect.done()
    first.close_gate.set()
    await asyncio.wait_for(asyncio.gather(reconnect, disconnect), timeout=1)
    assert h.controller._clients["a"] is None
    assert h.controller._reconnect_tasks["a"] is None
    assert all(client.closed.is_set() for client in h.created)


@pytest.mark.asyncio
async def test_old_cleanup_cannot_clear_a_newer_client_or_its_status(harness):
    h = harness
    old = FakeClient(failure="connect", close_gate=asyncio.Event())
    h.planned.append(old)
    await h.controller.connect_player("a")
    old_task = h.controller._reconnect_tasks["a"]
    await reached(old.closing)
    newer = FakeClient()
    h.controller._clients["a"] = newer
    h.controller._status["a"] = "connected"
    old_task.cancel()
    old.close_gate.set()
    with pytest.raises(asyncio.CancelledError):
        await old_task
    assert h.controller._clients["a"] is newer
    assert h.controller._status["a"] == "connected"
    assert newer.disconnect_calls == 0


@pytest.mark.asyncio
async def test_failed_disconnect_does_not_prevent_replacement(harness):
    h = harness
    first = FakeClient(failure="disconnect")
    h.planned.append(first)
    await h.controller.connect_player("a")
    await h.clock.next(1)
    await h.controller.connect_player("a")
    await h.clock.next(1)
    assert first.closed.is_set()
    assert first.disconnect_calls == 1
    assert h.controller._clients["a"] is h.created[1]


@pytest.mark.asyncio
async def test_config_reload_drains_old_workers_before_restarting(harness):
    h = harness
    first = FakeClient(close_gate=asyncio.Event())
    h.planned.append(first)
    h.controller.start_workers()
    await reached(first.identifying)
    old_workers = list(h.controller._workers.values())
    old_reconnects = list(h.controller._reconnect_tasks.values())
    old_queues = h.controller._queues
    new_config = {"enabled": True, "triggers": [], "connections": {
        "a": {"host": "replacement", "port": 4456, "password": ""},
        "b": {"host": "", "port": 4455, "password": ""},
    }}
    reload = asyncio.create_task(h.controller.apply_new_config(new_config))
    await reached(first.closing)
    assert not reload.done()
    assert len(h.created) == 1
    first.close_gate.set()
    await asyncio.wait_for(reload, timeout=1)
    await asyncio.wait_for(h.arrivals.get(), timeout=1)
    second = await asyncio.wait_for(h.arrivals.get(), timeout=1)
    await reached(second.identifying)
    assert second.url == "ws://replacement:4456"
    assert first.closed.is_set()
    assert all(task.done() for task in old_workers + old_reconnects)
    assert all(task not in old_workers and not task.done() for task in h.controller._workers.values())
    assert all(h.controller._queues[pid] is not old_queues[pid] for pid in "ab")


@pytest.mark.asyncio
async def test_cancelling_worker_also_closes_its_reconnect_client(harness):
    h = harness
    h.controller._start_worker("a")
    await h.clock.next(1)
    worker = h.controller._workers["a"]
    reconnect = h.controller._reconnect_tasks["a"]
    worker.cancel()
    await asyncio.wait_for(worker, timeout=1)
    assert reconnect.done()
    assert h.created[0].closed.is_set()
    assert h.controller._workers["a"] is None
    assert h.controller._reconnect_tasks["a"] is None


@pytest.mark.asyncio
async def test_stop_workers_waits_for_cleanup_and_is_idempotent(harness):
    h = harness
    client = FakeClient(close_gate=asyncio.Event())
    h.planned.append(client)
    h.controller.start_workers()
    await reached(client.identifying)
    workers = list(h.controller._workers.values())
    reconnects = list(h.controller._reconnect_tasks.values())
    stopping = asyncio.create_task(h.controller.stop_workers())
    await reached(client.closing)
    assert not stopping.done()
    client.close_gate.set()
    await asyncio.wait_for(stopping, timeout=1)
    await h.controller.stop_workers()
    assert all(task.done() for task in workers + reconnects)
    assert all(value is None for value in h.controller._clients.values())
    assert all(value is None for value in h.controller._workers.values())
    assert all(value is None for value in h.controller._reconnect_tasks.values())
    assert client.disconnect_calls == 1


@pytest.mark.asyncio
async def test_missing_optional_library_does_not_attempt_to_connect(harness, monkeypatch):
    monkeypatch.setattr(obs, "_OBS_AVAILABLE", False)
    await harness.controller.connect_player("a")
    await harness.controller._reconnect_tasks["a"]
    assert harness.created == []
