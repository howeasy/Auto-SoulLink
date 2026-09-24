"""P4.2c: the pure halves of lua/tests/gen2_sfx_gate.lua under lupa (channel read, grass-free BFS, verdict)."""
from __future__ import annotations

import pathlib

import lupa

REPO = pathlib.Path(__file__).resolve().parents[2]
GATE = (REPO / "lua" / "tests" / "gen2_sfx_gate.lua").as_posix()


def gate():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.globals().SLINK_GEN2_GATE_LIBRARY = True
    return lua, lua.eval(f'dofile("{GATE}")')


def test_playing_needs_channel_on_and_the_exact_16bit_id():
    lua, P = gate()
    mem = bytearray(0x10000)
    bases = lua.table(0xC1C9, 0xC1FB, 0xC22D, 0xC25F)

    def read(a):
        return mem[int(a)]
    mem[0xC22D] = 0x19                        # ch7 MusicID $19, channel off
    assert P.playing(read, bases, 0x19) is None
    mem[0xC22D + 3] = 0x09                    # SOUND_CHANNEL_ON | SOUND_SFX
    assert P.playing(read, bases, 0x19) == 7
    assert P.playing(read, bases, 0x24) is None
    mem[0xC22D + 1] = 0x01                    # high byte: id $119, not $19
    assert P.playing(read, bases, 0x19) is None


def test_first_step_avoids_grass_unless_it_is_the_goal():
    lua, P = gate()
    # 5x3: floor row 0, grass row 1 except x=4, floor row 2
    grid = [1, 1, 1, 1, 1,
            2, 2, 2, 2, 1,
            1, 1, 1, 1, 1]
    m = lua.table_from({"width": 5, "height": 3, "grid": lua.table_from(grid)})
    d, n = P.first_step(m, 0, 0, lua.eval("function(x, y) return x == 0 and y == 2 end"))
    assert (d, n) == ("Right", 10)            # around the grass through x=4
    d, n = P.first_step(m, 0, 0, lua.eval("function(x, y) return y == 1 and x < 4 end"), True)
    assert (d, n) == ("Down", 1)              # grass allowed as the goal only
    assert P.first_step(m, 0, 0, lua.eval("function(x, y) return x == 9 end")) is None


def test_problem_verdicts():
    lua, P = gate()
    ok = {"accepted": True, "posted": 10, "consumed": 12, "played": 12, "id": 0x19, "fade_frames": 0}
    assert P.problem(lua.table_from(ok), 300) is None
    assert "latency" in P.problem(lua.table_from(dict(ok, consumed=400, played=400)), 300)
    assert "never on ch5-8" in P.problem(lua.table_from({k: v for k, v in ok.items() if k != "played"}), 300)
    assert "attribution" in P.problem(lua.table_from(dict(ok, pre_playing=True)), 300)
    fade = dict(ok, watch_fade=True, fade_at_post=8, fade_frames=70, fade_end=80, consumed=81, played=81)
    assert P.problem(lua.table_from(fade), 300) is None
    assert "held" in P.problem(lua.table_from(dict(fade, dropped_in_fade=True)), 300)
    assert "during the fade" in P.problem(lua.table_from(dict(fade, consumed=40, played=40)), 300)
    assert "inside the music fade" in P.problem(lua.table_from(dict(fade, fade_at_post=0)), 300)
