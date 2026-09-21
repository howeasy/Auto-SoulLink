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
    assert all(c["shadow"] == c["wire"] >= 1 for c in result["coverage"].values())
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
    missing = next(e for e in new if e.kind == "save")
    new.remove(missing)
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


def shadow_lines(tmp_path, rows, window=0):
    path = tmp_path / "shadow_a.log"
    path.write_text("\n".join(
        f"SHADOW t={i} frame={row.get('frame', 10)} "
        + " ".join(f"{k}={v}" for k, v in row.items() if k != "frame")
        for i, row in enumerate(rows, 1)), encoding="utf-8")
    return reduce_shadow(path, window)


def test_missing_and_empty_keys_are_preserved_and_liveness_dropped(tmp_path):
    events = shadow_lines(tmp_path, [{"kind": "frame_control", "key": ""},
                                     {"kind": "battle_begin", "key": ""},
                                     {"kind": "map_load"}])
    assert [(e.kind, e.key) for e in events] == [("battle_begin", "-"), ("map_load", "-")]
    result = compare([], events)
    assert result["coverage"]["battle_begin"]["status"] == "COVERED"
    assert "frame_control" not in result["coverage"]


def test_release_uses_pre_removal_key_and_reports_unmatched_begin(tmp_path):
    events = shadow_lines(tmp_path, [{"kind": "pc_release_begin", "key": "old"},
                                     {"kind": "pc_release"},
                                     {"kind": "pc_release_begin", "key": "pending"}])
    assert [e.identity() for e in events] == [("pc_move", "old", "release")]
    assert events.diagnostics[0]["key"] == "pending"
    assert events.diagnostics[0]["delta"] == "unmatched_begin"
    assert any(d["delta"] == "unmatched_begin" for d in compare([], events)["deltas"])


@pytest.mark.parametrize("raw,action", [("pc_deposit", "deposit"), ("pc_withdraw", "withdraw"),
                                       ("pc_box_place", "place")])
@pytest.mark.parametrize("reverse", [False, True])
def test_pc_alias_fold_is_one_to_one(tmp_path, raw, action, reverse):
    rows = [{"kind": raw, "key": "k"}, {"kind": "pc_move", "key": "k", "action": action}]
    if reverse:
        rows.reverse()
    events = shadow_lines(tmp_path, rows)
    assert [e.identity() for e in events] == [("pc_move", "k", action)]
    events = shadow_lines(tmp_path, rows + [rows[-1]])
    assert len(events) == 2  # repeating the same site remains a duplicate


def test_trade_pairs_changed_key_by_slot(tmp_path):
    events = shadow_lines(tmp_path, [{"kind": "trade_begin", "key": "old", "slot": 2},
                                     {"kind": "trade_done", "key": "new", "slot": 2}])
    assert [e.identity() for e in events] == [("trade_done", "new", "")]
    assert events.diagnostics == []


def test_pairing_does_not_guess_ambiguous_release_or_cross_frames(tmp_path):
    events = shadow_lines(tmp_path, [{"kind": "pc_release_begin", "key": "one"},
                                     {"kind": "pc_release_begin", "key": "two"},
                                     {"kind": "pc_release"}])
    assert [(e.key, e.action) for e in events] == [("-", "release")]
    assert len(events.diagnostics) == 3
    events = shadow_lines(tmp_path, [{"kind": "trade_begin", "key": "old", "slot": 0},
                                     {"kind": "trade_done", "key": "new", "slot": 0, "frame": 11}])
    assert events.diagnostics[0]["delta"] == "unmatched_begin"


def test_unknown_completion_still_counts_presence(tmp_path):
    events = shadow_lines(tmp_path, [{"kind": "pc_release"}, {"kind": "poison_faint"}])
    assert [(e.kind, e.key) for e in events] == [("pc_move", "-"), ("faint", "-")]
    assert events[1].cause == "poison"
    assert compare([], events)["coverage"]["pc_move"]["status"] == "COVERED"


def test_poison_pair_becomes_faint_with_cause(tmp_path):
    events = shadow_lines(tmp_path, [{"kind": "poison_hp_before", "key": "k", "hp": 1},
                                     {"kind": "poison_faint", "key": "k", "hp": 0}])
    assert [(e.kind, e.key, e.cause) for e in events] == [("faint", "k", "poison")]
    assert compare([], events)["coverage"]["poison_faint"]["status"] == "COVERED"
    assert not shadow_lines(tmp_path, [{"kind": "poison_hp_before", "key": "k", "hp": 0},
                                       {"kind": "poison_faint", "key": "k", "hp": 0}])


@pytest.mark.parametrize("first,second,result", [
    ("mon_given", "capture_wild", "capture_wild"),
    ("capture_wild", "mon_given", "capture_wild"),
    ("trade_evolve_species_store", "evolve_species_store", "evolve_species_store"),
    ("evolve_species_store", "trade_evolve_species_store", "evolve_species_store"),
])
def test_complementary_sites_fold_but_duplicates_do_not(tmp_path, first, second, result):
    events = shadow_lines(tmp_path, [{"kind": first, "key": "k"}, {"kind": second, "key": "k"}])
    assert [e.kind for e in events] == [result]
    assert len(shadow_lines(tmp_path, [{"kind": first, "key": "k"},
                                      {"kind": first, "key": "k"}])) == 2


def test_folds_are_key_sink_and_window_bounded(tmp_path):
    rows = [{"kind": "mon_given", "key": "k", "frame": 10},
            {"kind": "capture_wild", "key": "k", "frame": 11}]
    assert len(shadow_lines(tmp_path, rows)) == 2
    assert len(shadow_lines(tmp_path, rows, window=1)) == 1
    rows[1]["sink"] = "b"
    assert len(shadow_lines(tmp_path, rows, window=1)) == 2
    assert len(shadow_lines(tmp_path, [{"kind": "mon_given"}, {"kind": "capture_wild"}])) == 2


def test_supplemental_and_shadow_only_cli(tmp_path, capsys):
    path = tmp_path / "a.log"
    path.write_text("SHADOW t=1 frame=1 kind=save key=\n"
                    "SHADOW t=2 frame=2 kind=borrowed_party key=x\n"
                    "SHADOW t=3 frame=3 kind=nature_change key=y\n", encoding="utf-8")
    assert main(["--shadow", str(path), "--json"]) == 1  # partial coverage, not parse error
    result = json.loads(capsys.readouterr().out)
    assert "error" not in result and not result["wire_present"]
    assert "borrowed_party" not in result["coverage"]
    assert result["supplemental"]["borrowed_party"]["shadow"] == 1
    assert result["supplemental"]["nature_change"]["shadow"] == 1
    assert result["coverage"]["save"]["status"] == "COVERED"


def test_current_physical_logs_parse_and_count_presence():
    root = Path(__file__).resolve().parents[2] / "patch/build/shadow_wire"
    paths = list(root.glob("*.shadow.log"))
    if not paths:
        pytest.skip("shadow captures not present in patch/build/shadow_wire")
    for path in paths:
        events = reduce_shadow(path)
        result = compare([], events)
        raw_kinds = {part.split("=", 1)[1] for line in path.read_text(encoding="utf-8").splitlines()
                     if "SHADOW " in line for part in line.split() if part.startswith("kind=")}
        for kind in raw_kinds & {"battle_begin", "battle_end", "whiteout", "map_load", "save", "mon_given"}:
            # An acquired mon may be folded into capture_wild rather than mon_given.
            if kind == "mon_given" and "capture_wild" in raw_kinds:
                continue
            assert result["coverage"][kind]["status"] == "COVERED", path
