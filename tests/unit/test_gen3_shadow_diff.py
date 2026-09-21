"""Semantic differential falsification, including committed P1 characterization."""
from __future__ import annotations

import gzip
import json
from collections import Counter
from pathlib import Path

import pytest

from tools.gen3_shadow_diff import (
    KINDS,
    Event,
    compare,
    load_ledger,
    main,
    reduce_shadow,
    reduce_wire,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "gen3" / "wire"


def write_wire(path, messages):
    rows = [{"dir": "c2s", "t": i, "msg": msg}
            for i, msg in enumerate(messages, 1)]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path


@pytest.fixture
def pair(tmp_path):
    messages = [{"event": kind, "key": str(i), "frame": i,
                 **({"action": "deposit"} if kind == "pc_move" else {})}
                for i, kind in enumerate(KINDS, 1)]
    wire = write_wire(tmp_path / "wire_a.jsonl", messages)
    shadow = tmp_path / "shadow_a.log"
    shadow.write_text("\n".join(
        f"SHADOW t={i} frame={i} kind={msg['event']} key={i} "
        + ("action=deposit " if msg['event'] == "pc_move" else "") + "future_field=ignored"
        for i, msg in enumerate(messages, 1)), encoding="utf-8")
    return wire, shadow


def test_synthetic_pair_and_cli_pass(pair, capsys):
    wire, shadow = pair
    result = compare(reduce_wire(wire).events, reduce_shadow(shadow))
    assert result["passed"]
    assert all(c["shadow"] == c["wire"] == 1 for c in result["coverage"].values())
    assert main(["--wire", str(wire), "--shadow", str(shadow), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["passed"]


@pytest.mark.parametrize("mutation", ["DROP", "DUPLICATE", "MISORDER"])
def test_shadow_mutations_fail(pair, mutation):
    wire, shadow = pair
    lines = shadow.read_text(encoding="utf-8").splitlines()
    if mutation == "DROP":
        del lines[2]
    elif mutation == "DUPLICATE":
        lines.insert(2, lines[2])
    else:
        lines[2], lines[3] = lines[3], lines[2]
    # Renumber capture t: mutations must fail semantically, not just syntactically.
    lines = [f"SHADOW t={i} " + line.split(" ", 2)[2]
             for i, line in enumerate(lines, 1)]
    shadow.write_text("\n".join(lines), encoding="utf-8")
    assert not compare(reduce_wire(wire).events, reduce_shadow(shadow))["passed"]


def test_uncovered_cannot_be_waived(pair):
    wire, shadow = pair
    old, new = reduce_wire(wire).events, reduce_shadow(shadow)
    missing = new.pop()
    ledger = [{"kind": missing.kind, "key": missing.key,
               "reason": "missing hook", "owner": "P3"}]
    result = compare(old, new, ledger)
    assert not result["passed"]
    assert result["coverage"][missing.kind]["status"] == "UNCOVERED"


def test_ledger_explains_exactly_one_delta(pair, tmp_path):
    wire, shadow = pair
    old, new = reduce_wire(wire).events, reduce_shadow(shadow)
    new.append(Event("save", "extra"))
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(json.dumps([{
        "kind": "save", "key": "extra", "reason": "wire omits save", "owner": "C3-4",
    }]), encoding="utf-8")
    ledger = load_ledger(ledger_path)
    assert compare(old, new, ledger)["passed"]
    new.append(Event("save", "extra"))
    assert not compare(old, new, ledger)["passed"]


def test_yaml_ledger(tmp_path):
    path = tmp_path / "ledger.yaml"
    path.write_text('- kind: save\n  key: "-"\n  reason: absent on wire\n  owner: P3\n',
                    encoding="utf-8")
    assert load_ledger(path) == [{"kind": "save", "key": "-", "reason": "absent on wire", "owner": "P3"}]


def test_real_injected_hp_is_commanded_write(tmp_path):
    a = reduce_wire(FIXTURES / "faint_a_old_client.jsonl")
    b = reduce_wire(FIXTURES / "faint_b_old_client.jsonl")
    assert Counter(e.kind for e in a.events + b.events) == {}
    assert [(e.kind, e.key) for e in a.commanded] == [
        ("commanded_write", "EBEF11DA:2BDDC8BF")]
    assert [(e.kind, e.key) for e in b.commanded] == [
        ("commanded_write", "EBEF11DA:2BD6C8BF")]
    compressed = tmp_path / "renamed.jsonl.gz"
    with gzip.open(compressed, "wb") as handle:
        handle.write((FIXTURES / "faint_a_old_client.jsonl").read_bytes())
    assert reduce_wire(compressed) == a


def test_real_boxsync_has_no_engine_moves():
    # stats_cache is an acknowledgement/snapshot, not evidence of an engine deposit.
    result = reduce_wire(FIXTURES / "boxsync_a_old_client.jsonl")
    assert Counter(e.kind for e in result.events) == {}
    assert result.commanded == []


def test_acquisition_folding_and_pc_actions(tmp_path):
    path = write_wire(tmp_path / "wire_a.jsonl", [
        {"event": "hello"}, {"event": "capture", "key": "gift", "gift": True},
        {"event": "tick"}, {"event": "mon_given", "key": "gift"},
        {"event": "capture", "key": "wild"},
        {"event": "party_to_box", "key": "wild"},
        {"event": "box_to_party", "key": "wild"},
        {"event": "release", "key": "wild"},
        {"event": "area_enter", "area_id": "town"},
    ])
    assert [e.identity() for e in reduce_wire(path).events] == [
        ("mon_given", "gift", ""), ("capture_wild", "wild", ""),
        ("pc_move", "wild", "deposit"), ("pc_move", "wild", "withdraw"),
        ("pc_move", "wild", "release"), ("map_load", "town", ""),
    ]


def test_unmarked_faint_is_not_inferred_commanded(tmp_path):
    path = write_wire(tmp_path / "faint_a_old_client.jsonl", [
        {"event": "faint", "key": "natural"}])
    result = reduce_wire(path)
    assert [e.kind for e in result.events] == ["faint"]
    assert result.commanded == []


def test_capture_order_is_not_frame_time(pair):
    wire, shadow = pair
    old = [Event(e.kind, e.key, e.sink, e.t * 100, action=e.action)
           for e in reduce_wire(wire).events]
    result = compare(old, reduce_shadow(shadow))
    assert result["passed"]
    assert result["timing_unavailable"] == len(KINDS)


def test_frame_bound_and_cross_sink_order(pair):
    wire, shadow = pair
    old, new = reduce_wire(wire).events, reduce_shadow(shadow)
    event = new[-1]
    new[-1] = Event(event.kind, event.key, event.sink, event.t, event.frame + 2)
    assert not compare(old, new)["passed"]
    assert compare(old, new, frame_bounds={event.kind: 2})["passed"]
    assert not compare(old, [Event(e.kind, e.key, "b", e.t, e.frame, e.action)
                             for e in new])["passed"]


def test_invalid_shadow_fails_cli(pair, capsys):
    wire, shadow = pair
    shadow.write_text("SHADOW kind=faint key=x", encoding="utf-8")
    assert main(["--wire", str(wire), "--shadow", str(shadow), "--json"]) == 1
    assert "incomplete" in json.loads(capsys.readouterr().out)["error"]
