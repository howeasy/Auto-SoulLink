"""gen2_trade_evolve's A seed (post-RC card TRADE-EVOLVE-CATCH, O-33): the errand base with Master Balls, so the
link catch of the disclosed O-31 HAUNTER plant is certain. MODEL only, no emulator."""
from __future__ import annotations

import json
from pathlib import Path

from lupa import LuaRuntime

from server.adapters import gen2_codec as codec
from tools import e2e_duo, gen2_synth_fixtures as synth

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests/fixtures/gen2"
SEEDS = {"crystal_synth_trade_evolve": "crystal_battle_errand", "gold_synth_trade_evolve": "gold_battle_errand"}
MASTER_BALL = 0x01   # constants/item_constants.asm
BALL_FIELDS = {"wNumBalls", "wBalls", "sChecksum", "sBackupChecksum"}


def test_each_seed_is_its_errand_base_with_only_master_balls():
    for name, base in SEEDS.items():
        raw, disclosure = synth.build_named(name)
        base_raw = (FIX / f"{base}.SaveRAM").read_bytes()
        assert disclosure["base_fixture"] == base and disclosure["edits"] == {"balls": [["MASTER_BALL", 5]]}
        assert {field["symbol"] for field in disclosure["fields"]} <= BALL_FIELDS
        balls = next(field for field in disclosure["fields"] if field["symbol"] == "wBalls")
        assert balls["new_hex"].startswith(f"{MASTER_BALL:02x}05ff")
        layout = codec.for_foundation(name.split("_")[0])
        seed_party, base_party = (codec.decode_saved_party(data[:synth.CART], layout, copy_name="primary")["mons"]
                                  for data in (raw, base_raw))
        assert seed_party == base_party   # the lead, the plant target and the trade stay native
        assert raw[synth.CART:] == base_raw[synth.CART:]   # the RTC trailer untouched


def test_committed_seeds_are_the_builders_output():
    assert set(synth.TRADE_FIXTURES) == set(SEEDS)
    for name in SEEDS:
        raw, disclosure = synth.build_named(name)
        assert (FIX / f"{name}.SaveRAM").read_bytes() == raw
        assert json.loads((FIX / f"{name}.synth.json").read_text(encoding="utf-8")) == disclosure


def test_the_runner_stages_the_seed_for_trade_evolve_a_only():
    assert e2e_duo.GEN2_TRADE_EVOLVE_FIXTURES == {
        "gen2_new": {"a": "crystal_synth_trade_evolve", "b": "crystal_battle_ot2_errand"},
        "gen2_gold_silver": {"a": "gold_synth_trade_evolve", "b": "silver_battle_errand"},
        "gen2_crystal_gold": {"a": "crystal_synth_trade_evolve", "b": "gold_battle_errand"}}
    assert set(e2e_duo.GEN2_TRADE_EVOLVE_FIXTURES) == set(e2e_duo.GEN2_TRADE_FIXTURES)
    for game, fixtures in e2e_duo.GEN2_TRADE_EVOLVE_FIXTURES.items():
        rows = e2e_duo.gen2_preflight(game=game, scenario="gen2_trade_evolve")
        assert rows["a"]["synth"] == fixtures["a"] and rows["a"]["name"] == e2e_duo.GEN2_TRADE_FIXTURES[game]["a"]
        assert rows["a"]["fixture"] == FIX / f"{fixtures['a']}.SaveRAM"   # boots through the PLAYED errand base
        assert "synth" not in rows["b"] and rows["b"]["name"] == e2e_duo.GEN2_TRADE_FIXTURES[game]["b"]
        assert any(line.startswith(f"gen2_trade_evolve  attempts=1  targets=a:{fixtures['a']}, b:{fixtures['b']}")
                   for line in e2e_duo.list_lines(game))
    rows = e2e_duo.gen2_preflight(game="gen2_new", scenario="gen2_trade_new")   # every other case: errand seeds
    assert "synth" not in rows["a"] and rows["a"]["name"] == "crystal_battle_errand"


def _gate():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute("SLINK_GEN2_GATE_LIBRARY = true")
    return lua, lua.eval("dofile")((ROOT / "lua/tests/gen2_frame_align.lua").as_posix())


def test_the_ball_cursor_steers_to_a_master_ball_on_screen():
    lua, gate = _gate()

    def rows(*texts):
        return lua.table_from([list(text) for text in texts], recursive=True)

    assert gate.ball_cursor(rows("▶POKé BALL  ×3", " MASTER BALL ×5", " CANCEL")) == ("ball", "Down")
    assert gate.ball_cursor(rows(" MASTER BALL ×5", "▶POKé BALL  ×3", " CANCEL")) == ("ball", "Up")
    assert gate.ball_cursor(rows("▶MASTER BALL ×5", " POKé BALL  ×3")) == "ball"   # on it: throw
    assert gate.ball_cursor(rows("▶POKé BALL  ×3", " CANCEL")) == "ball"   # no Master Ball: the old choice
    assert gate.ball_cursor(rows(" MASTER BALL ×5", "▶CANCEL")) == "cancel"


def test_the_driver_throws_the_master_ball_not_the_poke_ball():
    lua, gate = _gate()

    def t(value):
        return lua.table_from(value, recursive=True)

    driver = gate.driver(t({"width": 3, "height": 3, "grid": [2] * 9}))
    base = {"battle_mode": 1, "input_ready": True, "save_success_counter": 0, "probe_hits": {"capture_party": 0},
            "hits": {"same_save_file": 0, "erase_save": 0}, "ui": {"kind": "pack_balls"}}

    def step(**extra):
        buttons, _phase = driver.step(t({**base, **extra}))
        for _ in range(12):   # the 12-frame hold, then one release frame
            driver.step(t(base))
        return dict(buttons)

    assert step(ball_cursor="ball", ball_toward="Down") == {"Down": True}
    assert step(ball_cursor="ball") == {"A": True}
