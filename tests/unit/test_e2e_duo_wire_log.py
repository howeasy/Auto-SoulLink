"""`--wire-log`: the golden-transcript capture for Gen 3 (card gen3-P1-C1-3).

Two halves, and the second one is the point:

* the harness (`tools/e2e_duo.py`) only adds `--wire-log DIR` to the server's argv when the
  flag is given, and promotes the server's capture to
  `tests/fixtures/gen3/wire/<scenario>_<player>_old_client.jsonl`;
* the server (`server/server.py`) writes that capture from a `_WireTap` wrapped around the
  connection's StreamWriter, so the transcript is the bytes that actually crossed the socket.

The invariance test is the one that guards production: without the flag, `server_cmd()` must be
the literal argv the runner has always built. Drop the `if wire:` guard and it goes red.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

import pytest
import pytest_asyncio

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(_REPO, "tools"))

import e2e_duo as duo  # noqa: E402

from server.server import SLinkServer  # noqa: E402

HELLO_A = {"event": "hello", "player": "a", "rom_type": "FRLG_1_0", "trainer_name": "Alice",
           "ot_id": "30B8", "has_pokeballs": True}


def _run(tmp_path, **overrides) -> duo.DuoRun:
    """A DuoRun with only the fields the argv and collection paths read."""
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.scenario = "faint"
    run.cfg = duo.SCENARIOS["faint"]
    run.tcp_port = 54321
    run.http_port = 8080
    run.data_dir = str(tmp_path / "data")
    base = {"server_flags": [], "wire_log": False}
    base.update(overrides)
    run.args = argparse.Namespace(**base)
    return run


# ── the flag ──────────────────────────────────────────────────────────────────

def _parse(monkeypatch, argv):
    """The real parser, reached by driving `main()` down its `--list` exit."""
    captured = {}
    real = argparse.ArgumentParser.parse_args

    def spy(self, *a, **kw):
        captured["args"] = real(self, *a, **kw)
        return captured["args"]

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", spy)
    monkeypatch.setattr(duo, "list_lines", lambda game: [])
    monkeypatch.setattr(sys, "argv", ["e2e_duo.py", *argv, "--list"])
    with pytest.raises(SystemExit) as exit_info:
        duo.main()
    assert exit_info.value.code == 0
    return captured["args"]


def test_the_flag_parses_and_defaults_off(monkeypatch):
    assert _parse(monkeypatch, []).wire_log is False
    assert _parse(monkeypatch, ["--wire-log"]).wire_log is True


# ── argv invariance ──────────────────────────────────────────────────────────

def test_without_the_flag_the_server_argv_is_unchanged(tmp_path):
    run = _run(tmp_path)
    assert run.server_cmd() == [
        sys.executable, "-m", "server.server",
        "--host", "127.0.0.1",
        "--port", "54321",
        "--http-port", "8080",
        "--data-dir", run.data_dir,
    ] + run.cfg["flags"]
    assert run._wire_dir() is None
    assert run.collect_wire_logs() == []


def test_with_the_flag_the_server_argv_gains_exactly_the_wire_log_pair(tmp_path):
    plain = _run(tmp_path).server_cmd()
    run = _run(tmp_path, wire_log=True)
    assert run.server_cmd() == plain + ["--wire-log", os.path.join(run.data_dir, "wire")]


def test_extra_server_flags_still_come_before_wire_log(tmp_path):
    run = _run(tmp_path, wire_log=True, server_flags=["--verbose"])
    cmd = run.server_cmd()
    assert cmd[-2:] == ["--wire-log", run._wire_dir()]
    assert "--verbose" in cmd[:-2]


# ── output path naming ───────────────────────────────────────────────────────

def test_collection_names_files_by_scenario_and_player(tmp_path, monkeypatch):
    monkeypatch.setattr(duo, "WIRE_FIXTURES", str(tmp_path / "fixtures"))
    run = _run(tmp_path, wire_log=True)
    run.scenario = "boxsync"
    os.makedirs(run._wire_dir())
    for player in ("a", "b"):
        with open(os.path.join(run._wire_dir(), f"wire_{player}.jsonl"), "w",
                  encoding="utf-8") as handle:
            handle.write(json.dumps({"dir": "c2s", "t": 1, "msg": {"player": player}}) + "\n")
    with open(os.path.join(run._wire_dir(), "server.log"), "w", encoding="utf-8") as handle:
        handle.write("not a transcript\n")

    landed = run.collect_wire_logs()

    assert sorted(os.path.basename(p) for p in landed) == [
        "boxsync_a_old_client.jsonl", "boxsync_b_old_client.jsonl"]
    with open(landed[0], encoding="utf-8") as handle:
        assert json.loads(handle.read())["msg"]["player"] == "a"


# ── the capture itself, over a real socket ───────────────────────────────────

@pytest_asyncio.fixture
async def wired(tmp_path):
    """A server with --wire-log pointed at a tmp dir, listening on an ephemeral port."""
    srv = SLinkServer(data_dir=str(tmp_path / "data"), wire_log=str(tmp_path / "wire"))
    tcp = await asyncio.start_server(srv.handle_client, "127.0.0.1", 0)
    try:
        yield tcp.sockets[0].getsockname()[1], str(tmp_path / "wire")
    finally:
        tcp.close()
        await tcp.wait_closed()


async def _send(writer, reader, msg):
    writer.write((json.dumps(msg) + "\n").encode())
    await writer.drain()
    return json.loads(await asyncio.wait_for(reader.readline(), 3))


def _lines(wire_dir, player):
    with open(os.path.join(wire_dir, f"wire_{player}.jsonl"), encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


@pytest.mark.asyncio
async def test_every_line_lands_in_capture_order_with_req_linking_the_reply(wired):
    port, wire_dir = wired
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    await _send(writer, reader, dict(HELLO_A, seq=1))
    await _send(writer, reader, {"event": "tick", "player": "a", "seq": 2, "party": [],
                                 "area_id": "pallet_town"})
    writer.close()
    await writer.wait_closed()
    await asyncio.sleep(0.05)

    rows = _lines(wire_dir, "a")
    # t is capture order for the file, not the protocol's own seq: a _connect meta record is
    # first, then each c2s/s2c pair gets its own next number, and each reply's req points at
    # the request it answers.
    assert [(r["dir"], r["t"], r.get("req")) for r in rows] == [
        ("meta", 1, None),
        ("c2s", 2, None),
        ("s2c", 3, 2),
        ("c2s", 4, None),
        ("s2c", 5, 4),
        ("meta", 6, None),
    ]
    assert rows[0]["msg"] == {"event": "_connect"}
    assert rows[-1]["msg"] == {"event": "_disconnect"}
    assert rows[1]["msg"]["event"] == "hello"
    # Verbatim, field order included: no re-serialization beyond loads/dumps.
    assert list(rows[1]["msg"]) == list(dict(HELLO_A, seq=1))
    assert list(rows[2]["msg"]) == ["commands"]
    assert isinstance(rows[2]["msg"]["commands"], list)


@pytest.mark.asyncio
async def test_a_reconnect_shares_the_file_and_keeps_counting(wired):
    """Same player, two connections: one file, an unbroken t sequence, a _disconnect/_connect
    pair marking the boundary between them."""
    port, wire_dir = wired
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    await _send(writer, reader, dict(HELLO_A))  # no seq at all
    writer.close()
    await writer.wait_closed()
    await asyncio.sleep(0.05)

    reader2, writer2 = await asyncio.open_connection("127.0.0.1", port)
    await _send(writer2, reader2, dict(HELLO_A))
    writer2.close()
    await writer2.wait_closed()
    await asyncio.sleep(0.05)

    rows = _lines(wire_dir, "a")
    assert [(r["dir"], r["msg"].get("event") if r["dir"] == "meta" else None) for r in rows] == [
        ("meta", "_connect"), ("c2s", None), ("s2c", None), ("meta", "_disconnect"),
        ("meta", "_connect"), ("c2s", None), ("s2c", None), ("meta", "_disconnect"),
    ]
    assert [r["t"] for r in rows] == list(range(1, len(rows) + 1))  # one unbroken counter


@pytest.mark.asyncio
async def test_no_wire_log_writes_nothing(tmp_path):
    """The default server never builds a tap, so no directory appears."""
    srv = SLinkServer(data_dir=str(tmp_path / "data"))
    assert srv._wire_log is None
    tcp = await asyncio.start_server(srv.handle_client, "127.0.0.1", 0)
    try:
        port = tcp.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        assert "commands" in await _send(writer, reader, dict(HELLO_A, seq=1))
        writer.close()
        await writer.wait_closed()
    finally:
        tcp.close()
        await tcp.wait_closed()
    assert not os.path.isdir(tmp_path / "wire")


def test_a_tap_io_failure_never_reaches_the_connection(tmp_path, monkeypatch):
    """Adapter-guard finding on b0e0538: disk/permission failures inside the tap are logged and
    dropped, never raised into handle_client (which would kill that client's task)."""
    from server.server import _WireTap

    class _Writer:
        def __init__(self):
            self.sent = []

        def write(self, data):
            self.sent.append(data)

    w = _Writer()
    tap = _WireTap(w, str(tmp_path / "nope"), {})

    def _boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", _boom)
    tap.c2s('{"event":"hello","player":"a","seq":1}', {"event": "hello", "player": "a", "seq": 1})
    tap.write(b'{"commands":[]}\n')
    assert w.sent == [b'{"commands":[]}\n']  # the reply still went out


# ── review findings (card gen3-P1-C1-3b): unvalidated players, t semantics, malformed lines ──

def _tap(tmp_path, files=None):
    from server.server import _WireTap

    class _Writer:
        def write(self, data):
            pass

    return _WireTap(_Writer(), str(tmp_path / "wire"), files if files is not None else {})


def test_an_unrecognised_player_id_goes_to_the_bounded_rejected_sink(tmp_path):
    tap = _tap(tmp_path)
    tap.c2s('{"event":"hello","player":"c"}', {"event": "hello", "player": "c"})
    with open(tmp_path / "wire" / "wire_rejected.jsonl", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    assert [r["dir"] for r in rows] == ["meta", "c2s"]
    assert rows[1]["msg"] == {"event": "hello", "player": "c"}
    assert not os.path.exists(tmp_path / "wire" / "wire_c.jsonl")


def test_the_rejected_sink_is_capped_then_dropped(tmp_path):
    from server.server import _WireTap
    tap = _tap(tmp_path)
    for _ in range(_WireTap._REJECTED_CAP + 20):
        tap.c2s('{"player":"nope"}', {"player": "nope"})
    with open(tmp_path / "wire" / "wire_rejected.jsonl", encoding="utf-8") as f:
        n = sum(1 for _ in f)
    assert n == _WireTap._REJECTED_CAP


def test_a_non_dict_line_is_recorded_raw_and_does_not_raise(tmp_path):
    tap = _tap(tmp_path)
    tap.c2s("[1, 2, 3]", [1, 2, 3])  # valid JSON, not protocol -- must not raise
    with open(tmp_path / "wire" / "wire_rejected.jsonl", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    malformed = rows[1]
    assert malformed["dir"] == "c2s"
    assert malformed["raw"] == "[1, 2, 3]"
    assert malformed["msg"] is None
    # the following reply's req points at the malformed line's own t, not the previous one
    tap.write(b'{"commands":[]}\n')
    with open(tmp_path / "wire" / "wire_rejected.jsonl", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    assert rows[-1]["req"] == malformed["t"]


def test_at_most_three_handles_ever_open(tmp_path):
    tap = _tap(tmp_path)
    tap.c2s('{"player":"a"}', {"player": "a"})
    tap2 = _tap(tmp_path, files=tap._files)
    tap2.c2s('{"player":"b"}', {"player": "b"})
    tap3 = _tap(tmp_path, files=tap._files)
    tap3.c2s('{"player":"?"}', {"player": "?"})
    assert set(tap._files) == {"a", "b", "rejected"}
