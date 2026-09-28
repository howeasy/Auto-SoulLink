"""Expansion-only checks for the XG3 active-faint duo's independent witnesses."""

from __future__ import annotations

import json
import re
from pathlib import Path

FACTS = Path(__file__).resolve().parents[1] / "data/games/gen3_exp/28877d73/facts.json"


def hp_lost_mask(facts_path: Path = FACTS) -> int:
    """The BoxPokemon.hpLost lane from this build's compiler probe, fail closed on drift."""
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    field = facts["structs"]["BoxPokemon"]["bitfields"]["hpLost"]
    if (field["offset"], field["width"], field["shift"], field["bits"]) != (30, 2, 0, 14):
        raise ValueError("expansion BoxPokemon.hpLost compiler lane changed")
    mask = int(field["mask"], 16)
    if mask != (1 << field["bits"]) - 1:
        raise ValueError("expansion BoxPokemon.hpLost compiler mask changed")
    return mask


def memorial_source(text: str, key: str) -> tuple[tuple[int, int] | None, list[str]]:
    """Read the single keyed pre-write party snapshot tied to a successful memorial write."""
    k = re.escape(key)
    pattern = (rf"(?m)^XG3_MEMORIAL_SOURCE {k} frame=\d+ slot=\d+ hp=(\d+) "
               rf"max_hp=(\d+) attempted=([1-9]\d*)$")
    hits = list(re.finditer(pattern, text))
    if len(hits) != 1:
        return None, [f"expansion memorial source for {key} has {len(hits)} successful writes, want one"]
    rx = re.search(rf"(?m)^RX memorialize key={k}$", text)
    ack = re.search(rf"(?m)^TX memorialize_done {k}(?=\s|$)", text)
    if not rx or not ack or not rx.start() < hits[0].start() < ack.start():
        return None, [f"expansion memorial source for {key} is not between RX and acknowledgement"]
    return (int(hits[0].group(1)), int(hits[0].group(2))), []


def memorial_hp_lost_problems(before: dict, after: dict, *, source_hp: int,
                              source_max_hp: int, require_zero: bool = False) -> list[str]:
    """A boxed faint records the raw pre-write maxHP-currentHP; other bits stay fixed."""
    mask = hp_lost_mask()
    old, new = before.get("unknown"), after.get("unknown")
    if not all(isinstance(x, int) for x in (old, new, source_hp, source_max_hp)):
        return ["expansion hpLost witness is incomplete"]
    if not 0 < source_max_hp <= 65535 or not 0 <= source_hp <= source_max_hp:
        return ["expansion memorial source HP/maxHP is invalid"]
    if require_zero and source_hp != 0:
        return [f"expansion B memorial source HP is {source_hp}, not the proved KO 0"]
    loss = source_max_hp - source_hp
    if loss > mask:
        return [f"expansion hpLost {loss} is outside the compiler lane"]
    problems = []
    if new & mask != loss:
        problems.append(f"expansion hpLost is {new & mask}, expected {loss} from raw maxHP {source_max_hp} and HP {source_hp}")
    if new & ~mask != old & ~mask:
        problems.append("expansion BoxPokemon flags outside hpLost changed")
    return problems


def natural_faint_receipt_problems(text: str, key: str) -> list[str]:
    """A's normal battle: raw in-battle party HP0 precedes its client faint event."""
    k = re.escape(key)
    markers = [
        ("normal battle choice", rf"(?m)^LOSE {k} status_move_slot=\d+$"),
        ("raw in-battle HP0", rf"(?m)^FORCED_HP0 {k} frame=\d+ in_battle=1 battler=1$"),
        ("natural faint completion", rf"(?m)^LINKED_FAINTED {k}$"),
        ("faint event", rf"(?m)^TX faint {k}(?=\s|$)"),
    ]
    found = [(name, re.search(pattern, text)) for name, pattern in markers]
    missing = [f"a: missing {name} for {key}" for name, hit in found if hit is None]
    if missing:
        return missing
    positions = [hit.start() for _, hit in found]
    problems = []
    if positions != sorted(positions) or len(set(positions)) != len(positions):
        problems.append(f"a: natural faint witnesses for {key} are out of order")
    prefix = text[:positions[-1]]
    if re.search(r"(?m)^RX force_(?:faint|explode)\b", prefix):
        problems.append(f"a: {key} received a force command before its natural faint")
    if re.search(r"(?m)^\[client\].*\bwrite\b", prefix):
        problems.append(f"a: {key} has an SLink write before its natural faint")
    return problems
