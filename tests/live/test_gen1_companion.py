"""Combined canonical companion artifacts; native/held scopes remain distinct."""

import json
import os
import tempfile
from itertools import product
from pathlib import Path

import pytest

from tests.live.test_gen1_launcher import run_launcher_pair
from tests.live.test_gen1_paired_native_trade import run_native_pair
from tools.build_gen1_companion import build
from tools.run_gb_gate import run_gate

pytestmark = [
    pytest.mark.live,
    pytest.mark.slow,
    pytest.mark.skipif(
        os.environ.get("SLINK_LIVE") != "1", reason="explicit live emulator lane required"
    ),
]


@pytest.mark.parametrize(
    "variants", list(product(("red", "blue", "yellow"), repeat=2)), ids=lambda pair: "-".join(pair)
)
def test_combined_companions_keep_native_ui_both_animations_saves_and_logical_migration(variants):
    run_native_pair(variants, native_ui=True, companion=True)


@pytest.mark.parametrize(
    "variants", [("red", "blue"), ("yellow", "yellow")], ids=lambda pair: "-".join(pair)
)
def test_exact_companion_launcher_admits_both_cartridges_and_keeps_execution_held(variants):
    for variant in set(variants):
        build(variant)
    run_launcher_pair(variants, companion=True)


@pytest.mark.parametrize("variant", ["red", "blue"])
def test_combined_panel_keeps_paging_native_return_and_trade_separate(variant):
    run_panel(variant)


@pytest.mark.parametrize("variant", ["red", "blue"])
@pytest.mark.parametrize("map_name", ["ViridianPokecenter", "IndigoPlateauLobby", "SafariZoneCenter"])
@pytest.mark.parametrize("pokedex", [False, True])
def test_panel_protocol_across_maps_and_pokedex_states(variant,map_name,pokedex):
    run_panel(variant,map_name=map_name,pokedex=pokedex)


def run_panel(variant,*,map_name=None,pokedex=None):
    from tools.build_gen1_companion import ROOT

    manifest = build(variant)
    directory = Path(tempfile.mkdtemp(prefix="combined-panel-", dir=ROOT / ".cache"))
    fixture = None
    if map_name:
        from tools.gen1_panel_fixture import make_panel_fixture
        manifest["panel_fixture"] = make_panel_fixture(variant,map_name,pokedex,directory)
        fixture = manifest["panel_fixture"]["fixture"]
    source = directory / "manifest.json"
    source.write_text(json.dumps(manifest))
    output = directory / "observed.json"
    passed, path, log = run_gate(
        "lua/tests/test_gen1_companion_panel_gate.lua",
        rom_key=variant + "_companion",
        quiet=True,
        timeout=65,
        fixture_override=fixture,
        extra_env={
            "SLINK_COMPANION_MANIFEST": str(source),
            "SLINK_COMPANION_PANEL_RESULT": str(output),
        },
    )
    assert passed, f"{path}\n{log[-7000:]}"
    observed = json.loads(output.read_text())
    assert observed["passed"] and observed["final_sha1"] == manifest["final_sha1"]
    assert len(observed["cases"]) == 12 and observed["native_trade_calls"] == 0
    assert [row["page"] for row in observed["cases"][1]["reveals"]] == [0, 1, 0]
