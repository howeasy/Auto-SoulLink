"""Explode Mode must be gated on the adapter, and every death watcher must see both commands.

Two bugs this covers:

1. `--explode-mode` emitted `force_explode` for EVERY game, but only the Gen 3 Radical Red
   Lua client implements that command — Gen 1/2/4/5 clients fall into their unknown-command
   branch and merely log it, so the linked partner never fainted.  A silent Soul Link rule
   violation, and the opposite of how `rival_team_swap` is gated.

2. Downstream watchers compared the literal string "force_faint", so under Explode Mode the
   dashboard death event and the OBS `link_death` trigger never fired.
"""
import pytest

from server.adapters.gen1_rby import Gen1Adapter
from server.adapters.gen3_frlge import Gen3Adapter
from server.adapters.gen4_hgsspt import Gen4Adapter
from server.state import DEATH_COMMANDS, LinkStatus

from .test_state import make_state_with_link


def _explode_state(adapter):
    state = make_state_with_link()
    state.adapter = adapter
    state.explode_mode = True
    return state


def _cmds(state, player):
    return [c.get("cmd") for c in state.queued_commands[player]]


# ── the adapter capability itself ────────────────────────────────────────────

def test_rr_adapter_supports_explode_mode():
    assert Gen3Adapter(is_rr=True).supports_explode_mode() is True


@pytest.mark.parametrize("adapter", [
    Gen3Adapter(is_rr=False),   # vanilla / AP / Emerald FRLG
    Gen1Adapter(),
    Gen4Adapter(),
])
def test_non_rr_adapters_do_not_support_explode_mode(adapter):
    assert adapter.supports_explode_mode() is False


# ── the gate in _propagate_faint ─────────────────────────────────────────────

def test_explode_mode_emits_force_explode_on_rr():
    state = _explode_state(Gen3Adapter(is_rr=True))
    state.handle_event("a", {"event": "faint", "key": "A:1"})
    assert "force_explode" in _cmds(state, "b")
    assert "force_faint" not in _cmds(state, "b")


@pytest.mark.parametrize("adapter", [Gen3Adapter(is_rr=False), Gen1Adapter(), Gen4Adapter()])
def test_explode_mode_falls_back_to_force_faint_when_unsupported(adapter):
    """The partner must still die — just via the deferred faint the client understands."""
    state = _explode_state(adapter)
    state.handle_event("a", {"event": "faint", "key": "A:1"})
    assert "force_faint" in _cmds(state, "b")
    assert "force_explode" not in _cmds(state, "b")
    assert state.links[0].status == LinkStatus.DEAD


def test_explode_mode_off_uses_force_faint_even_on_rr():
    state = make_state_with_link()
    state.adapter = Gen3Adapter(is_rr=True)
    state.explode_mode = False
    state.handle_event("a", {"event": "faint", "key": "A:1"})
    assert "force_faint" in _cmds(state, "b")


# ── the shared death predicate ───────────────────────────────────────────────

def test_death_commands_covers_both_names():
    assert set(DEATH_COMMANDS) == {"force_faint", "force_explode"}


def test_queued_death_cmd_finds_force_explode():
    state = _explode_state(Gen3Adapter(is_rr=True))
    state.handle_event("a", {"event": "faint", "key": "A:1"})
    assert state.queued_death_cmd("b", "B:2") == "force_explode"


def test_queued_death_cmd_finds_force_faint():
    state = make_state_with_link()
    state.adapter = Gen3Adapter(is_rr=True)
    state.handle_event("a", {"event": "faint", "key": "A:1"})
    assert state.queued_death_cmd("b", "B:2") == "force_faint"


def test_queued_death_cmd_ignores_other_commands_and_keys():
    state = make_state_with_link()
    state.adapter = Gen3Adapter(is_rr=True)
    state.handle_event("a", {"event": "faint", "key": "A:1"})
    assert state.queued_death_cmd("b", "B:999") is None   # right player, wrong mon
    assert state.queued_death_cmd("a", "B:2") is None     # right mon, wrong player


def test_force_explode_is_a_known_event_type_and_visible_by_default():
    """A death the dashboard/overlays would otherwise drop on the floor."""
    from server.overlay_catalog import EVENT_FILTERS_DEFAULT_ON
    from server.server import SLinkServer

    for cmd in DEATH_COMMANDS:
        assert cmd in SLinkServer._EVENT_TYPE_CLASSES, f"{cmd} has no dashboard CSS class"
        assert cmd in EVENT_FILTERS_DEFAULT_ON, f"{cmd} is not shown by default in overlays"
