#!/usr/bin/env python3
"""Generate data/games/gen2_gsc/calc_names.json: Gen 2 (Crystal/Gold/Silver)
display name -> damage-calc GSC name, per kind (species/move/item; Gen 2 has
no abilities).

Species/moves/items are identical across the three titles (verified by this
script's own cross-title check), so Gen2GSCAdapter.calc_name() uses one
shared table regardless of which title is running.

The mismatch is mechanical: pret's raw ROM text is monocase (all-caps), and
the pack generators (tools/gen_gen2_moves.py, gen_gen2_items.py,
gen_gen2_species.py) title-case it with no knowledge of word boundaries, so
a two-word ROM name like "DYNAMICPUNCH" becomes the single word
"Dynamicpunch" while the calc (calc/calc/src/data/*.ts) spells it
"Dynamic Punch". There is no general rule to recover the lost boundary, so
each mismatch is listed explicitly below; this script's job is to find
every one that needs it (by diffing every id 1..251/1..254 against
calc_name_sets(2)) and fail loudly if a new one shows up unhandled.

Usage:
    python tools/gen_gen2_calc_names.py          # regenerate + verify
    python tools/gen_gen2_calc_names.py --check  # verify only, no write
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from server.adapters.gen2_gsc import Gen2GSCAdapter  # noqa: E402
from tools.gen_rr_priority_trainers import calc_name_sets  # noqa: E402

_OUT_PATH = _REPO_ROOT / "data" / "games" / "gen2_gsc" / "calc_names.json"

# Display name -> damage-calc GSC name. Only entries actually needed (i.e. the
# adapter's raw name isn't already a calc name) belong here; verified by the
# diff this script runs before writing.
_OVERRIDES: dict[str, dict[str, str]] = {
    "species": {
        "Farfetch'd": "Farfetch’d",
        "Mr.Mime": "Mr. Mime",
        "Nidoran♀": "Nidoran-F",
        "Nidoran♂": "Nidoran-M",
    },
    "move": {
        "Ancientpower": "Ancient Power",
        "Bubblebeam": "Bubble Beam",
        "Conversion2": "Conversion 2",
        "Doubleslap": "Double Slap",
        "Dragonbreath": "Dragon Breath",
        "Dynamicpunch": "Dynamic Punch",
        "Extremespeed": "Extreme Speed",
        "Faint Attack": "Feint Attack",
        "Hi Jump Kick": "High Jump Kick",
        "Poisonpowder": "Poison Powder",
        "Sand-Attack": "Sand Attack",
        "Selfdestruct": "Self-Destruct",
        "Softboiled": "Soft-Boiled",
        "Solarbeam": "Solar Beam",
        "Sonicboom": "Sonic Boom",
        "Thunderpunch": "Thunder Punch",
        "Thundershock": "Thunder Shock",
        "Vicegrip": "Vise Grip",
    },
    "item": {
        "Blackbelt": "Black Belt",
        "Blackglasses": "Black Glasses",
        "Brightpowder": "Bright Powder",
        "Miracleberry": "Miracle Berry",
        "Mysteryberry": "Mystery Berry",
        "Nevermeltice": "Never-Melt Ice",
        "Poké Ball": "Poke Ball",
        "Przcureberry": "PRZ Cure Berry",
        "Psncureberry": "PSN Cure Berry",
        "Silverpowder": "Silver Powder",
        "Thunderstone": "Thunder Stone",
        "Twistedspoon": "Twisted Spoon",
    },
}


def _emitted_names() -> dict[str, set[str]]:
    """Every non-empty name the adapter can emit for a real in-game id, per kind."""
    titles = [Gen2GSCAdapter(title=t) for t in ("crystal", "gold", "silver")]
    names: dict[str, set[str]] = {"species": set(), "move": set(), "item": set()}
    for adapter in titles:
        names["species"] |= {adapter.species_name(i) for i in range(1, 252)}
        names["move"] |= {adapter.move_name(i) for i in range(1, 252)} - {""}
        names["item"] |= {adapter.item_name(i) for i in range(1, 255)} - {""}
    return names


def build() -> tuple[dict, list[str]]:
    """Return (table to write, unmatched names left over after overrides)."""
    calc = calc_name_sets(2)
    emitted = _emitted_names()
    table: dict[str, dict[str, str]] = {}
    unmatched: list[str] = []
    for kind, names in emitted.items():
        mapped = {}
        for name in sorted(names):
            if name in calc[kind]:
                continue  # identity match, no table entry needed
            override = _OVERRIDES.get(kind, {}).get(name)
            if override is not None and (override == "" or override in calc[kind]):
                mapped[name] = override
            else:
                unmatched.append(f"{kind}: {name!r}")
        if mapped:
            table[kind] = mapped
    # Stale overrides (kept here but no longer needed / no longer resolve) are a bug.
    for kind, entries in _OVERRIDES.items():
        for name in entries:
            if name not in emitted[kind]:
                raise ValueError(f"stale override, no adapter id emits it: {kind} {name!r}")
    return table, unmatched


def main() -> int:
    check_only = "--check" in sys.argv
    table, unmatched = build()
    if unmatched:
        print("gen_gen2_calc_names: names with no calc match at all (expected for "
              "non-battle items -- key items, TMs/HMs, mail, apricorns, sell items):",
              file=sys.stderr)
        for line in unmatched:
            print("   ", line, file=sys.stderr)
    payload = {
        "_note": ("Gen 2 (Crystal/Gold/Silver -- Gen2GSCAdapter serves all three off one "
                  "shared table) display name -> damage-calc Gen 2 (GSC) name "
                  "(calc/calc/src/data/*.ts). Applied by Gen2GSCAdapter.calc_name(). Keys are "
                  "names the server emits (species_index.json/moves.json/items.json under "
                  "data/games/gen2_{crystal,gold,silver}). Gen 2 has no abilities, so that "
                  "kind has no entries here. Names with no entry either already match the "
                  "calc exactly, or (mostly key items/TMs/HMs/mail/apricorns/sell items) have "
                  "no calc battle-item counterpart at all. Generated by "
                  "tools/gen_gen2_calc_names.py; guarded by tests/unit/test_calc_names_multigen.py."),
        **table,
    }
    if check_only:
        current = json.loads(_OUT_PATH.read_text(encoding="utf-8")) if _OUT_PATH.exists() else None
        if current != payload:
            print("gen_gen2_calc_names: data/games/gen2_gsc/calc_names.json is stale", file=sys.stderr)
            return 1
        print("gen_gen2_calc_names: up to date")
        return 0
    _OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {_OUT_PATH} ({sum(len(v) for v in table.values())} mapped names, "
          f"{len(unmatched)} left unmapped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
