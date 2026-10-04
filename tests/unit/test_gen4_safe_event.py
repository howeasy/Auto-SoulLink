"""`safe` (docs/protocol.md §9 item 19) from lua/gen4/client.lua: exactly one per battle end.

The core never sends it on its own -- it is armed by the generation driver (`session.pending_safe`,
lua/core/session.lua:451-454) and only goes out once the driver also reports itself out of battle.
Gen 3 arms it when its battle closes (lua/gen3/client.lua:644-647, `finish_battle`); the conformance
audit found `pending_safe` nowhere under lua/gen4/, so the Gen 4 client sent no `safe` at all.

Gen 4 has no battle-end signal, so the boundary it arms on is its own: the reducer's debounced end of
the battle chain (lua/gen4/poll_events.lua `step_battle` / `end_frames`), NOT the first frame the chain
reads nil -- a one-frame chain refusal is not a battle's end, and arming on it would put `safe` on the
wire mid-battle. Each scenario below has a red control below that removes the arm and must fail.

NOT PHYSICAL evidence: the battle chain, the reducer and the checkpoint are the fake world's.
"""
import pytest

from tests.unit.gen4_world import ROOT, Mon, World

CLIENT = ROOT / "lua/gen4/client.lua"
ARM = "session.pending_safe = true"
# tests/unit/gen4_world.py PC_OFF (:53) has no "soulsilver" row, so World("soulsilver") raises
# KeyError in _lay_out; every World-driven Gen 4 test on this branch uses these two titles.
TITLES = ["heartgold", "heartgold_hge"]


def two_mon():
    return [Mon(0x5A3C91E7, 155, 5, 20, 20), Mon(0x0BADF00D, 155, 5, 11, 11)]


def booted(title, **kw):
    w = World(title, party=two_mon(), **kw)
    w.boot(80)
    return w


def one_safe_per_battle_end(title, **kw):
    """None on boot, none through the battle, one after it -- and no more, ever, while idle."""
    w = booted(title, **kw)
    assert w.events("safe") == []                          # never on boot
    w.enter_battle(cmd=5)
    w.advance(40)
    assert w.events("safe") == []                          # never while in battle
    w.leave_battle()
    w.advance(6)
    assert len(w.events("safe")) == 1                      # the first overworld frame after the end
    w.advance(400)                                          # a second idle period
    assert len(w.events("safe")) == 1                      # once per battle end, not once per frame


def one_safe_per_battle_end_across_two_battles(title, **kw):
    """The arm is re-armed per battle, not consumed once per session."""
    w = booted(title, **kw)
    w.enter_battle(cmd=5)
    w.advance(40)
    w.leave_battle()
    w.advance(6)
    assert len(w.events("safe")) == 1
    w.enter_battle(cmd=5)
    w.advance(40)
    assert len(w.events("safe")) == 1                      # the second battle sends nothing yet
    w.leave_battle()
    w.advance(6)
    assert len(w.events("safe")) == 2


def a_one_frame_chain_refusal_is_not_a_battle_end(title, **kw):
    """The chain reads nil for a single frame and comes back: no `safe` mid-battle, one at the real end."""
    w = booted(title, **kw)
    w.enter_battle(cmd=5)
    w.advance(10)
    w.leave_battle()
    w.advance(1)                                            # exactly one frame without the chain
    w.enter_battle(cmd=5)
    w.advance(40)
    assert w.events("safe") == []
    w.leave_battle()
    w.advance(6)
    assert len(w.events("safe")) == 1


SCENARIOS = [one_safe_per_battle_end, one_safe_per_battle_end_across_two_battles,
             a_one_frame_chain_refusal_is_not_a_battle_end]
IDS = [s.__name__ for s in SCENARIOS]


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.parametrize("scenario", SCENARIOS, ids=IDS)
def test_safe_is_sent_exactly_once_per_battle_end(scenario, title):
    scenario(title)


def _never_arm(w):
    """Pre-hook: load a MUTATED lua/gen4/client.lua whose battle end never arms the core."""
    src = CLIENT.read_text(encoding="utf-8")
    assert src.count(ARM) == 1, "the arming line moved; the red control is no longer aimed at it"
    mutant = src.replace(ARM, "session.pending_safe = false")
    assert mutant != src
    load, real = w.lua.eval("load"), w.lua.globals().dofile

    def dofile(path):
        if str(path).replace("\\", "/").endswith("lua/gen4/client.lua"):
            return load(mutant, "@mutant-client")()   # run the chunk: dofile returns its result
        return real(path)

    w.lua.globals().dofile = dofile


@pytest.mark.parametrize("scenario", SCENARIOS, ids=IDS)
def test_every_scenario_goes_red_when_the_battle_end_stops_arming(scenario):
    """Without the arm the client never sends `safe`, so each contract above must fail."""
    with pytest.raises(AssertionError):
        scenario("heartgold", pre=_never_arm)
