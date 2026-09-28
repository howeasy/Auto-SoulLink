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


def memorial_hp_lost_problems(before: dict, after: dict, *, expected_hp: int = 0) -> list[str]:
    """A boxed faint records maxHP-currentHP; its other `unknown` bits must stay fixed."""
    mask = hp_lost_mask()
    old, new = before.get("unknown"), after.get("unknown")
    max_hp = before.get("max_hp")
    if not all(isinstance(x, int) for x in (old, new, max_hp, expected_hp)):
        return ["expansion hpLost witness is incomplete"]
    loss = max_hp - expected_hp
    if not 0 <= loss <= mask:
        return [f"expansion hpLost {loss} is outside the compiler lane"]
    problems = []
    if new & mask != loss:
        problems.append(f"expansion hpLost is {new & mask}, expected {loss} from maxHP {max_hp} and HP {expected_hp}")
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
