"""The trainer fixtures (card G4-SYNTH-TRAINER): what they must be, and the producer's stop hook."""
import sys
from pathlib import Path

import pytest
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import gen3_trainer_fixture as tf  # noqa: E402

FIX = ROOT / "tests/fixtures/gen3"


@pytest.mark.parametrize("title", ["firered", "leafgreen"])
def test_committed_trainer_fixtures(title):
    path = FIX / f"{title}_party_trainer.sav"
    if not path.exists():
        pytest.skip(f"{path.name} not built yet (python tools/gen3_trainer_fixture.py --title {title})")
    a = path.read_bytes()
    assert tf.fixture_problems(a) == []
    b = (FIX / f"{title}_party_trainer_b.sav").read_bytes()
    assert b == tf.gen3_fixtures.derive_b(a)[0]
    assert tf.fixture_problems(b) == []


def test_import_registers_nothing():
    assert tf.SCENARIO not in tf.e2e_duo.SCENARIOS


@pytest.mark.parametrize("stem", ["leafgreen_party_town", "firered_party_battle"])
def test_other_fixtures_are_refused(stem):
    problems = tf.fixture_problems((FIX / f"{stem}.sav").read_bytes())
    assert any("not (1, 0, 41, 45)" in p for p in problems)
    assert any("< 13" in p for p in problems)


def _run_scenario(route_logs, at=(1, 0, 41, 45)):
    lua = LuaRuntime(unpack_returned_tuples=True)
    scenario = lua.execute((ROOT / "lua/tests/duo/scenario_gen3_trainer_fixture.lua").read_text(encoding="utf-8"))
    lua.execute("""
        saved = 0; lines = {}
        party = {{key='L', slot=0, level=13, hp=30, max_hp=30, status=0},
                 {key='B', slot=1, level=4, hp=17, max_hp=17, status=0}}
        ctx = {player='b', D={}, cp={},
          G={map=function() return AT[1], AT[2] end, pos=function() return AT[3], AT[4] end},
          log=function(s) lines[#lines+1]=s end,
          wait_go=function() return true end, party=function() return party end,
          find=function(k) for _,m in ipairs(party) do if m.key==k then return m end end end,
          in_battle=function() return false end, preparation_budget=function() return 30000 end,
          save=function() saved = saved + 1; return true end}
        -- the real enter_trainer: its body runs under pcall and calls c.log (= ctx.log) itself
        ctx.enter_trainer=function()
          local ok, err = pcall(function()
            for _, s in ipairs(ROUTE) do ctx.log(s) end
            error('walked past the stop tile')
          end)
          return false, tostring(err)
        end
    """)
    lua.globals().AT = lua.table(*at)
    lua.globals().ROUTE = lua.table(*route_logs)
    ok, why = scenario(lua.globals().ctx)
    return ok, why, lua.globals().saved, list(lua.globals().lines.values())


def test_stop_hook_saves_at_the_marker():
    stop = "PREP_ROUTE map=1.0 at=(41,45)"
    ok, why, saved, lines = _run_scenario(["PREP_ROUTE map=3.20 at=(5,52)", stop, "PREP_PAST_THE_STOP"])
    assert ok and saved == 1, why
    assert stop in lines and "PREP_PAST_THE_STOP" not in lines and lines[-1].startswith("TRAINER_FIXTURE ")


def test_no_marker_no_save():
    ok, why, saved, _ = _run_scenario(["PREP_ROUTE map=3.20 at=(5,52)"])
    assert not ok and saved == 0 and "walked past" in why


def test_wrong_tile_no_save():
    ok, why, saved, _ = _run_scenario(["PREP_ROUTE map=1.0 at=(41,45)"], at=(1, 0, 42, 45))
    assert not ok and saved == 0 and "(42,45)" in why
