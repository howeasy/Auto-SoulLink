"""Original-handle/create-time race checks with no real process or filesystem IO."""
from types import SimpleNamespace

import pytest

from tools.emulator_sandbox import ProcessIdentity, SandboxError, capture_spawn


class MissingProcess(Exception):
    pass


def test_alive_original_captures_immutable_identity_between_two_handle_polls():
    calls = []

    def poll():
        calls.append("poll")
        return None

    def lookup(pid):
        calls.append(("lookup", pid))
        return SimpleNamespace(create_time=lambda: calls.append("create_time") or 123.25)

    original = SimpleNamespace(pid=42, poll=poll)
    api = SimpleNamespace(Process=lookup, NoSuchProcess=MissingProcess)
    assert capture_spawn(original, api) == ProcessIdentity(42, 123.25)
    assert calls == ["poll", ("lookup", 42), "create_time", "poll"]


@pytest.mark.parametrize("returncode", [0, -9])
def test_exited_before_lookup_returns_none_without_process_api_access(returncode):
    original = SimpleNamespace(pid=42, poll=lambda: returncode)
    api = SimpleNamespace(Process=lambda _: pytest.fail("exited spawn triggered PID lookup"), NoSuchProcess=MissingProcess)
    assert capture_spawn(original, api) is None


def test_exit_during_create_time_cannot_capture_the_replacement_pid():
    calls, exited = [], False

    def poll():
        calls.append("poll")
        return 0 if exited else None

    def create_time():
        nonlocal exited
        calls.append("replacement_create_time")
        exited = True  # Original Popen handle knows it exited; the PID now belongs to another process.
        return 999.0

    def lookup(pid):
        calls.append(("lookup", pid))
        return SimpleNamespace(create_time=create_time)

    api = SimpleNamespace(Process=lookup, NoSuchProcess=MissingProcess)
    assert capture_spawn(SimpleNamespace(pid=42, poll=poll), api) is None
    assert calls == ["poll", ("lookup", 42), "replacement_create_time", "poll"]


@pytest.mark.parametrize("missing_at", ["lookup", "create_time"])
@pytest.mark.parametrize("still_alive", [False, True])
def test_missing_identity_rechecks_original_handle_and_only_refuses_live_original(missing_at, still_alive):
    calls = []
    missing = MissingProcess("PID disappeared during lookup")
    statuses = iter((None, None if still_alive else 0))

    def poll():
        calls.append("poll")
        return next(statuses)

    def create_time():
        calls.append("create_time")
        raise missing

    def lookup(pid):
        calls.append(("lookup", pid))
        if missing_at == "lookup":
            raise missing
        return SimpleNamespace(create_time=create_time)

    original = SimpleNamespace(pid=42, poll=poll)
    api = SimpleNamespace(Process=lookup, NoSuchProcess=MissingProcess)
    if still_alive:
        with pytest.raises(SandboxError, match="Cannot establish spawned process identity") as error:
            capture_spawn(original, api)
        assert error.value.__cause__ is missing
    else:
        assert capture_spawn(original, api) is None
    assert calls[0] == calls[-1] == "poll" and calls.count("poll") == 2
    assert ("create_time" in calls) is (missing_at == "create_time")


def test_default_process_api_uses_same_checks_without_launching(monkeypatch):
    import psutil

    statuses = iter((None, None))
    monkeypatch.setattr(psutil, "Process", lambda pid: SimpleNamespace(create_time=lambda: 321.5))
    original = SimpleNamespace(pid=77, poll=lambda: next(statuses))
    assert capture_spawn(original) == ProcessIdentity(77, 321.5)
