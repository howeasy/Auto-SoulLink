"""XC2 falsifier: every name Gen3ExpansionAdapter can emit for a real id resolves
against the damage calc's gen-9 name set, either directly or through
data/games/gen3_exp/28877d73/calc_names.json -- mirrors test_calc_names_multigen.py's
shape for the expansion pack. See tools/gen_expansion_calc_names.py and
docs/gen3_emerald/research/expansion_calc_design_2026-09-26.md §4 (XC2).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from server.adapters import get_adapter  # noqa: E402
from tools.gen_expansion_calc_names import (  # noqa: E402
    EXPECTED_UNRESOLVED,
    build,
)


def test_calc_names_json_is_up_to_date():
    import json

    out, _ = build()
    on_disk = json.loads((ROOT / "data/games/gen3_exp/28877d73/calc_names.json").read_text())
    assert out == on_disk


def test_every_emittable_name_resolves_or_is_documented_unresolved():
    a = get_adapter("gen3_exp")
    out, unresolved = build()
    for kind in ("species", "move", "ability", "item"):
        surprising = unresolved[kind] - EXPECTED_UNRESOLVED[kind]
        assert not surprising, f"{kind}: newly-unresolved names {sorted(surprising)}"
        stale = EXPECTED_UNRESOLVED[kind] - unresolved[kind]
        assert not stale, f"{kind}: documented-unresolved names now resolve {sorted(stale)}"

    # Spot-check the adapter's own calc_name() wiring (not just the generator's table).
    assert a.calc_name("species", "Farfetch'd") == "Farfetch’d"
    assert a.calc_name("species", "Nidoran♀") == "Nidoran-F"
    assert a.calc_name("species", "Nidoran♂") == "Nidoran-M"
    assert a.calc_name("move", "Light Of Ruin") == "Light of Ruin"
    assert a.calc_name("ability", "Power Of Alchemy") == "Power of Alchemy"
    # A name with no calc-9 equivalent at all: identity fallback, not a KeyError/crash.
    assert a.calc_name("ability", "Spicy Spray") == "Spicy Spray"


def test_calc_names_table_has_no_unnecessary_identity_entries():
    """Every mapped value must differ from its key -- an identity entry would be dead
    weight (calc_name already falls back to identity when a name isn't in the table)."""
    out, _ = build()
    for kind in ("species", "move", "ability", "item"):
        for rom_name, calc_name in out[kind].items():
            assert rom_name != calc_name
