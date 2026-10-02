"""U1 retry clocks and poison-hunt diagnostics; MODEL only, no emulator."""
import json
from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime

from tests.live import test_gen2_frame_align as gate
from tools import gen2_source_data

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def crystal_boot():
    path = ROOT / "tests/fixtures/gen2/crystal_battle.SaveRAM"
    if not path.is_file():
        pytest.skip("played Crystal fixture absent")
    return path.read_bytes()


@pytest.mark.parametrize("attempt,minute", [(None, 0), ("1", 0), ("2", 23), ("3", 46)])
@pytest.mark.parametrize("kind", ["clean", "overlay"])
def test_retry_clock_is_prespecified_daytime_and_disclosed(crystal_boot, monkeypatch, attempt, minute, kind):
    monkeypatch.setenv("SLINK_GEN2_ARTIFACT", kind)
    if attempt is None:
        monkeypatch.delenv("SLINK_GEN2_U1_ATTEMPT", raising=False)
    else:
        monkeypatch.setenv("SLINK_GEN2_U1_ATTEMPT", attempt)
    with gen2_source_data.shared_contexts():
        boot, disclosure = gate.u1_clock_setup(crystal_boot, "crystal", now=1790952666)
    assert boot[:32768] == crystal_boot[:32768]
    assert disclosure["game_hour"] == 11
    assert disclosure.get("game_minute") == minute
    assert disclosure.get("game_second", 0) == 0
    assert boot[-22:].hex() == disclosure["new_hex"]
    metadata = gate.u1_receipt_metadata(disclosure)
    assert metadata["u1_attempt"] == int(attempt or "1")
    assert metadata["clock_setup"] == disclosure
    from tools.verify_gen2_release import _clock_setup_errors
    assert _clock_setup_errors(ROOT, "crystal", {"fixture": "crystal_battle", **metadata}) == []
    # Independently decode the staged clock using the recorded save start time.
    dh, dl, hour, minute_rtc, second = boot[-14:-9]
    start_h, start_m, start_s = disclosure["start_time"]
    total = ((dh & 1) * 256 + dl) * 86400 + hour * 3600 + minute_rtc * 60 + second
    total += start_h * 3600 + start_m * 60 + start_s
    assert total % 86400 == 11 * 3600 + minute * 60


@pytest.mark.parametrize("value", ["0", "4", "-1", "1.5", "", "tomorrow"])
def test_unknown_retry_attempt_refuses_before_clock_rewrite(monkeypatch, value):
    monkeypatch.setenv("SLINK_GEN2_U1_ATTEMPT", value)
    with pytest.raises(ValueError, match="SLINK_GEN2_U1_ATTEMPT"):
        gate.u1_clock_setup(b"not a save", "crystal", now=1790952666)


def _budget_run(finish):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().SLINK_GEN2_GATE_LIBRARY = True
    align = lua.execute((ROOT / "lua/tests/gen2_frame_align.lua").read_text())
    host = lua.execute((ROOT / "lua/scripted_inputs.lua").read_text())
    return lua.execute("""
        return function(Host, budget, finish)
            local frame = 0
            local host = Host.new({frame=function() return frame end,
                step=function() frame=frame+1 end, idle={A=false}})
            local ok, result = pcall(host.run, {name='MODEL-hunt', terminal='done',
                max_frames=budget.max_frames, max_phase_frames=budget.max_phase_frames,
                terminal_idle=true}, function()
                    -- Observed ~3000 frames/encounter: allow59, plus travel/ticking.
                    if frame < 15000 then return {}, 'travel' end
                    if not finish or frame < 192000 then return {}, 'hunt' end
                    if frame < 193000 then return {}, 'tick' end
                    return {}, 'done'
                end)
            return ok, result, frame
        end
    """)(host, align.POISON_BUDGET, finish)


def test_hunt_can_cover_59_encounters_without_the_old_phase_cutoff():
    ok, outcome, frames = _budget_run(True)
    assert ok, outcome
    assert frames == 193001


def test_nonterminating_hunt_still_stops_at_the_total_budget():
    ok, reason, frames = _budget_run(False)
    assert not ok and "route made no bounded progress" in reason
    assert frames == 210000


def test_stable_menu_diagnostics_emit_once_and_expose_detection_mismatch():
    lua = LuaRuntime(unpack_returned_tuples=True)
    poison = lua.execute((ROOT / "lua/tests/gen2_poison_inputs.lua").read_text())
    codec = lua.execute((ROOT / "lua/json_codec.lua").read_text())
    lines = []
    def emit(row):
        row.moves = codec.array(row.moves)
        lines.append("POISON_ENCOUNTER " + codec.encode(row))
    diagnostic = poison.hunt_diagnostics(40, emit)
    def point(mode=1, ready=True, kind="battle_menu", sting=False):
        return lua.table_from({"battle_mode": mode, "input_ready": ready, "ui": {"kind": kind},
                               "foe_sting": sting, "map_group": 26, "map_number": 1}, recursive=True)
    weedle = lua.table_from({"species_id": 13, "level": 3, "moves": [40, 81, 0, 0]}, recursive=True)
    pidgey = lua.table_from({"species_id": 16, "level": 3, "moves": [33, 0, 0, 0]}, recursive=True)
    diagnostic.observe(point(ready=False), None, "hunt", 1)
    assert lines == []  # battle entry before enemy data/menu is ready is not an encounter sample
    diagnostic.observe(point(), weedle, "hunt", 2)
    for frame in range(3, 100):
        diagnostic.observe(point(sting=True), weedle, "hunt", frame)
    diagnostic.observe(point(kind="move_menu"), weedle, "hunt", 100)
    diagnostic.observe(point(mode=0), None, "hunt", 101)
    diagnostic.observe(point(), pidgey, "hunt", 102)
    lines.append("POISON_HUNT " + codec.encode(diagnostic.summary()))
    assert len(lines) == 3
    first = json.loads(lines[0].partition(" ")[2])
    assert (first["species_id"], first["level"], first["moves"]) == (13, 3, [40, 81, 0, 0])
    assert first["candidate"] is True and first["foe_sting"] is False
    summary = gate.parse_poison_hunt("\n".join(lines))
    assert summary["encounters"] == 2 and summary["candidates"] == 1
    assert summary["foe_sting_mismatches"] == 1


def test_real_poison_observer_emits_stable_foe_and_counts_unreadable_encounter():
    lua = LuaRuntime(unpack_returned_tuples=True)
    poison = lua.execute((ROOT / "lua/tests/gen2_poison_inputs.lua").read_text())
    codec = lua.execute((ROOT / "lua/json_codec.lua").read_text())
    text = lua.execute("""
        return function(PI, json)
            local lines, frame, point, foe = {}, 0, {}, nil
            local ctx = {json=json, u1={poison={maps={H={}}, hunt_map='H',
                start_phase='hunt', moves={POISON_STING=40}, psn_mask=8}},
                api={framecount=function() return frame end},
                log=function(line) lines[#lines+1]=line end}
            ctx.reads = {
                read_battle=function() return {mode=point.battle_mode, active_slot=0} end,
                read_battle_mon=function(side)
                    if side=='enemy' then return foe, 'MODEL unreadable foe' end
                    return {status=0, hp=21, max_hp=21, stats={speed=20}}
                end,
                read_party=function() return {mons={}} end}
            local SG={qualify_observer=function() return function() return point end end}
            local driver, observe = PI.new(ctx, SG, {BUDGET={settle_frames=1}},
                {PASSIVE_MOVES={}}, {fainted=function() return false end, max_frames=20, max_phase_frames=20})
            local function sample(mode, ready)
                frame=frame+1
                point={battle_mode=mode, map_group=26, map_number=1, x=8, y=49,
                       input_ready=ready, ui={kind='battle_menu'}}
                return observe()
            end
            sample(1, false)
            foe={species_id=13,level=3,moves={40,81,0,0},stats={speed=10}}
            assert(sample(1,true).foe_sting == true)
            sample(1,true)
            sample(0,false)
            foe=nil
            sample(1,true)
            lines[#lines+1]='POISON_HUNT '..json.encode(driver.hunt_summary())
            return table.concat(lines,'\\n')
        end
    """)(poison, codec)
    summary = gate.parse_poison_hunt(text)
    assert summary == {"schema": "gen2-poison-hunt-summary-v1", "encounters": 2,
                       "candidates": 1, "unreadable": 1, "foe_sting_mismatches": 0}
    assert text.count("POISON_ENCOUNTER ") == 2
    assert "MODEL unreadable foe" in text


@pytest.mark.parametrize("fault", ["duplicate_summary", "missing_summary", "wrong_count", "wrong_candidate",
                                  "out_of_order", "boolean_count"])
def test_diagnostic_parser_refuses_inconsistent_records(fault):
    row = {"schema": "gen2-poison-hunt-encounter-v1", "encounter": 1, "frame": 12,
           "map_group": 26, "map_number": 1, "species_id": 13, "level": 3,
           "moves": [40, 81, 0, 0], "readable": True, "candidate": True, "foe_sting": True}
    summary = {"schema": "gen2-poison-hunt-summary-v1", "encounters": 1, "candidates": 1,
               "unreadable": 0, "foe_sting_mismatches": 0}
    if fault == "wrong_count":
        summary["encounters"] = 2
    elif fault == "wrong_candidate":
        row["candidate"] = False
    elif fault == "out_of_order":
        row["encounter"] = 2
    elif fault == "boolean_count":
        summary["encounters"] = True
    lines = ["POISON_ENCOUNTER " + json.dumps(row)]
    if fault != "missing_summary":
        lines += ["POISON_HUNT " + json.dumps(summary)] * (2 if fault == "duplicate_summary" else 1)
    with pytest.raises(ValueError, match="poison hunt"):
        gate.parse_poison_hunt("\n".join(lines))


def test_historical_output_has_no_invented_hunt_counts():
    assert gate.parse_poison_hunt("RESULT: PASS\n") is None
