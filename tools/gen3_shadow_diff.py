"""Semantic wire/SHADOW falsifier (PLAN 5.7), not a physical qualification oracle.

Wire t is local capture order, NEVER a frame. Counts and semantic ordering have
zero tolerance for every kind. Optional --frame-bound KIND=N applies only when
both records contain a frame; unavailable timing is reported, not fabricated.
All 14 kinds require SHADOW coverage, even when a ledger explains missing wire
evidence. A ledger entry explains one delta only; it cannot waive coverage.

Ledger: JSON list (or {"differences": [...]}) of kind/key/reason/owner objects.
Simple YAML lists with these four scalar fields are also accepted, without a
YAML dependency. Advanced YAML constructs are deliberately rejected.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path

KINDS = (
    "battle_begin", "battle_end", "faint", "capture_wild", "mon_given", "pc_move",
    "whiteout", "map_load", "evolve_species_store", "trade_done", "save",
    "poison_faint", "borrowed_party", "nature_change",
)
ALIASES = {
    "area_enter": "map_load", "map": "map_load", "evolve": "evolve_species_store",
    "party_to_box": "pc_move", "box_to_party": "pc_move", "release": "pc_move",
    "pc_deposit": "pc_move", "pc_withdraw": "pc_move", "pc_release": "pc_move",
}
ACTIONS = {
    "party_to_box": "deposit", "pc_deposit": "deposit",
    "box_to_party": "withdraw", "pc_withdraw": "withdraw",
    "release": "release", "pc_release": "release",
}
# Exact P1 injected-HP fixture, independent of filename/compression. Provenance:
# lua/tests/duo/scenario_faint.lua:5-7,21. A's faint has no preceding server command.
# Do NOT generalize this classification to an arbitrary overworld faint.
INJECTED_HP_SHA256 = {
    "8e063ec5f6cb89b4ef4c4a116d922abbffb6dd24575fa27af809445ce3e2995c",
}


@dataclass(frozen=True)
class Event:
    kind: str
    key: str
    sink: str = "a"
    t: int = 0
    frame: int | None = None
    action: str = ""

    def identity(self):
        return self.kind, self.key, self.action


@dataclass
class Reduction:
    events: list[Event]
    commanded: list[Event]


def read_text(path: Path) -> str:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        return handle.read()


def file_sink(path: Path) -> str:
    match = re.search(r"(?:^|_)([ab])(?:_|\.)", path.name)
    return match[1] if match else "a"


def semantic(kind: str, msg: dict, sink: str, t: int) -> Event:
    key = msg.get("key", msg.get("new_key"))
    if key is None and kind == "map_load":
        key = msg.get("map_id", msg.get("area_id"))
    if key is None and "slot" in msg:
        key = f"box:{msg['box']}/slot:{msg['slot']}" if "box" in msg else f"slot:{msg['slot']}"
    frame = int(msg["frame"]) if "frame" in msg else None
    return Event(kind, str(key) if key is not None else "-", sink, t, frame,
                 str(msg.get("action", "")) if kind == "pc_move" else "")


def reduce_wire(path: Path) -> Reduction:
    raw = read_text(path)
    injected = hashlib.sha256(raw.encode()).hexdigest() in INJECTED_HP_SHA256
    events, commanded = [], []
    previous = 0
    pending: Counter = Counter()
    acquisitions: dict = {}
    for line in raw.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        t = row["t"]
        if not isinstance(t, int) or isinstance(t, bool) or t <= previous:
            raise ValueError(f"{path}: non-monotonic capture t={t}")
        previous = t
        msg = row.get("msg")
        if not isinstance(msg, dict) or row.get("dir") == "meta":
            continue
        sink = row.get("sink", msg.get("player", file_sink(path)))
        if sink not in ("a", "b"):
            raise ValueError(f"{path}: invalid sink {sink!r}")
        conn = row.get("conn", 0)
        if row.get("dir") == "s2c":
            for command in msg.get("commands", []):
                if command.get("cmd") in ("force_faint", "force_explode"):
                    event = semantic("commanded_write", command, sink, t)
                    commanded.append(event)
                    pending[sink, conn, event.key] += 1
            continue
        if row.get("dir") != "c2s":
            continue
        name = msg.get("event")
        kind = ALIASES.get(name, name)
        if name == "capture":
            kind = "mon_given" if msg.get("gift") in (True, 1, "true") else "capture_wild"
        if kind not in KINDS:
            continue
        payload = dict(msg)
        if name in ACTIONS:
            payload["action"] = ACTIONS[name]
        event = semantic(kind, payload, sink, t)
        if kind == "pc_move" and event.action not in ("deposit", "withdraw", "release"):
            raise ValueError(f"{path}:{t}: pc_move needs deposit/withdraw/release action")
        command_key = sink, conn, event.key
        if kind == "faint" and (injected or pending[command_key]):
            if pending[command_key]:
                pending[command_key] -= 1
            else:
                commanded.append(semantic("commanded_write", payload, sink, t))
            continue
        # Fold complementary capture + mon_given notifications only. Identical
        # repeats remain visible as duplicates. Never collapse SHADOW records.
        if kind in ("capture_wild", "mon_given"):
            token = sink, conn, event.key
            prior = acquisitions.get(token)
            if prior and {prior[0], name} == {"capture", "mon_given"}:
                index = prior[1]
                if name == "capture":
                    events[index] = semantic(kind, payload, sink, events[index].t)
                del acquisitions[token]
                continue
            acquisitions[token] = name, len(events)
        elif kind in ("pc_move", "trade_done"):
            acquisitions.pop((sink, conn, event.key), None)
        events.append(event)
    return Reduction(events, commanded)


def reduce_shadow(path: Path) -> list[Event]:
    events = []
    previous: dict[str, int] = {}
    for number, line in enumerate(read_text(path).splitlines(), 1):
        if "SHADOW " not in line:
            continue
        fields = dict(re.findall(r"(\w+)=([^\s]+)", line.split("SHADOW ", 1)[1]))
        if not {"t", "frame", "kind", "key"} <= fields.keys():
            raise ValueError(f"{path}:{number}: incomplete SHADOW record")
        kind = fields["kind"]
        if kind not in KINDS:
            raise ValueError(f"{path}:{number}: unknown SHADOW kind {kind}")
        sink = fields.get("sink", fields.get("player", file_sink(path)))
        t = int(fields["t"])
        if sink not in ("a", "b") or t <= previous.get(sink, -1):
            raise ValueError(f"{path}:{number}: invalid sink or non-monotonic SHADOW t")
        previous[sink] = t
        event = semantic(kind, fields, sink, t)
        if kind == "pc_move" and event.action not in ("deposit", "withdraw", "release"):
            raise ValueError(f"{path}:{number}: pc_move needs deposit/withdraw/release action")
        events.append(event)
    return events


def load_ledger(path: Path | None) -> list[dict]:
    if path is None:
        return []
    raw = read_text(path)
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError:
        entries = []
        for line in raw.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            match = re.fullmatch(r"(\s*-\s+|\s+)(kind|key|reason|owner):\s*(.+)", line)
            if not match:
                raise ValueError("ledger supports only a YAML list of four scalar fields") from None
            if "-" in match[1]:
                entries.append({})
            if not entries or match[2] in entries[-1]:
                raise ValueError("invalid or duplicate YAML ledger field") from None
            value = match[3].strip()
            if value.startswith('"'):
                value = json.loads(value)
            elif value.startswith("'") and value.endswith("'"):
                value = value[1:-1].replace("''", "'")
            elif value[0] in "|>&*!{[":
                raise ValueError("unsupported YAML scalar") from None
            entries[-1][match[2]] = value
    if isinstance(entries, dict):
        entries = entries.get("differences")
    if not isinstance(entries, list):
        raise ValueError("ledger must be a list")
    for entry in entries:
        if (not isinstance(entry, dict)
                or any(not isinstance(entry.get(k), str) or not entry[k].strip()
                       for k in ("kind", "key", "reason", "owner"))
                or entry["kind"] not in KINDS):
            raise ValueError("ledger entries require valid kind, key, reason and owner")
    return entries


def compare(wire: list[Event], shadow: list[Event], ledger=(), frame_bounds=None) -> dict:
    bounds = dict.fromkeys(KINDS, 0)
    bounds.update(frame_bounds or {})
    if any(k not in KINDS or not isinstance(v, int) or v < 0 for k, v in bounds.items()):
        raise ValueError("frame bounds must be nonnegative integers for known kinds")
    wc, sc = Counter(e.kind for e in wire), Counter(e.kind for e in shadow)
    coverage = {kind: {"wire": wc[kind], "shadow": sc[kind],
                       "status": "COVERED" if sc[kind] else "UNCOVERED",
                       "count_bound": 0, "order_bound": 0, "frame_bound": bounds[kind]}
                for kind in KINDS}
    deltas, timing_unavailable = [], 0
    for sink in sorted({e.sink for e in wire + shadow}):
        left = [e for e in wire if e.sink == sink]
        right = [e for e in shadow if e.sink == sink]
        matcher = SequenceMatcher(None, [e.identity() for e in left],
                                  [e.identity() for e in right], autojunk=False)
        for tag, i, j, a, b in matcher.get_opcodes():
            if tag == "equal":
                for old, new in zip(left[i:j], right[a:b], strict=True):
                    if old.frame is None or new.frame is None:
                        timing_unavailable += 1
                    elif abs(old.frame - new.frame) > bounds[old.kind]:
                        deltas.append({**asdict(new), "delta": "frame_bound_exceeded"})
            else:
                deltas.extend({**asdict(e), "delta": "missing_shadow"} for e in left[i:j])
                deltas.extend({**asdict(e), "delta": "extra_shadow"} for e in right[a:b])
    unused = list(ledger)
    for delta in deltas:
        for index, entry in enumerate(unused):
            if (entry["kind"], entry["key"]) == (delta["kind"], delta["key"]):
                delta["explanation"] = unused.pop(index)
                break
    return {"passed": all(sc[k] for k in KINDS)
            and all("explanation" in d for d in deltas),
            "coverage": coverage, "deltas": deltas, "unused_ledger": unused,
            "timing_unavailable": timing_unavailable}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="*", type=Path)
    parser.add_argument("--wire", nargs="+", type=Path)
    parser.add_argument("--shadow", nargs="+", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--frame-bound", action="append", default=[], metavar="KIND=N")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        files = sorted({p for root in args.inputs
                        for p in (root.rglob("*") if root.is_dir() else [root]) if p.is_file()})
        wire_paths = args.wire or [p for p in files if ".jsonl" in p.name]
        shadow_paths = args.shadow or [p for p in files if p.suffix in (".log", ".txt")]
        if not wire_paths or not shadow_paths:
            raise ValueError("both wire transcripts and SHADOW logs are required")
        reductions = [reduce_wire(p) for p in wire_paths]
        wire = [e for r in reductions for e in r.events]
        shadow = [e for p in shadow_paths for e in reduce_shadow(p)]
        bounds = {k: int(v) for k, v in (s.split("=", 1) for s in args.frame_bound)}
        report = compare(wire, shadow, load_ledger(args.ledger), bounds)
        report["commanded_writes"] = [asdict(e) for r in reductions for e in r.commanded]
    except (OSError, ValueError, KeyError, TypeError) as error:
        report = {"passed": False, "error": str(error)}
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("PASS" if report["passed"] else "FAIL")
        for kind, counts in report.get("coverage", {}).items():
            print(f"{kind}: wire={counts['wire']} shadow={counts['shadow']} {counts['status']}")
        print(json.dumps({k: v for k, v in report.items() if k != "coverage"}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
