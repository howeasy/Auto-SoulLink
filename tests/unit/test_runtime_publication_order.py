"""Committed responses must reach the transport before potentially slow presentation."""

import asyncio
from types import SimpleNamespace

import pytest

from server.durable_runtime import DurableRuntime
from server.protocol import canonical_json


@pytest.mark.parametrize("fail_presentation", [False, True])
def test_transport_precedes_presentation_and_each_publication_reads_one_view(fail_presentation):
    async def run():
        calls = []
        runtime = object.__new__(DurableRuntime)
        runtime._lock = asyncio.Lock()
        runtime._writers = {}
        runtime._failed = None
        runtime._wall_seen = {}
        runtime.protocol = "fixture"
        runtime.gate = SimpleNamespace(sessions={})
        stage = SimpleNamespace(
            rules=object(), barrier=SimpleNamespace(status=lambda: {"fixture": True})
        )

        def state():
            calls.append("state")
            return stage

        def process(message, owner):
            calls.append("committed")
            return {"ack": "ACK"}

        runtime.state = state
        runtime.process = process
        runtime.disconnect = lambda *args: calls.append("disconnect")

        class Reader:
            async def readuntil(self, separator):
                raise asyncio.IncompleteReadError(b"", 1)

        class Writer:
            def write(self, value):
                assert value == b'{"ack":"ACK"}\n'
                calls.append("write")

            async def drain(self):
                calls.append("drain")

            def close(self):
                calls.append("close")

            async def wait_closed(self):
                pass

        def publish(rules, status):
            assert rules is stage.rules and status["recovery"] == {"fixture": True}
            calls.append("publish")
            if fail_presentation:
                raise RuntimeError("presentation failed")

        await runtime.handle_client(
            Reader(),
            Writer(),
            first_frame=canonical_json({"event": "hello", "player": "a"}).encode(),
            on_change=publish,
        )
        assert calls[:5] == ["committed", "write", "state", "publish", "drain"]
        assert calls.count("write") == 1 and calls.count("state") == 2

    asyncio.run(run())
