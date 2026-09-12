"""Real source hooks use stable identity; inventory publication still requires a hold."""

import pytest

from tests.unit.test_client_state_store import runtime  # noqa: F401
from tests.unit.test_gen1_engine_signals_client import load_point, probe, saved  # noqa: F401


def composed(lua, separate=True):
    load_point(lua)
    lua.globals().separate = separate
    lua.execute("""
        probe:close()
        package.loaded.gen1_full_save={capture=function()return {fixture=true}end}
        local Observe=require('gen1_initial_observation')
        local baseline=journal.store:read().observation
        baseline.initial_inventory={phase='acknowledged',operation_id=string.rep('9',32),
            payload={event='initial_observation',payload={context_generation=context.context_generation,frame=frame}}}
        assert(journal:append({event='explicit-initial-ack-fixture'},baseline))
        local function owned()assert(held,'held reader called inside frame');return context end
        composite=Observe.new({journal=journal,variant='yellow',engine_signals=true,
            memory={isPartyWriteSafe=function()return true end},owned=owned,
            source_owned=separate and function()return context end or nil,
            host={status=function()return {physical_stop_verified=held,owner_id='fixture',process_id=1,capability_id='fixture'}end}})
        composite:step(true)
        probe=composite.signals
    """)


def test_real_engine_hook_survives_moving_frame_and_flushes_only_after_hold(probe):  # noqa: F811
    composed(probe)
    before = probe.globals().disk
    probe.execute("held=false;frame=101;fire('battle_faint')")
    assert probe.globals().probe.status(probe.globals().probe)["failed"] is None
    assert probe.globals().probe.status(probe.globals().probe)["pending"] == 1
    assert probe.globals().disk == before
    probe.execute("assert(not pcall(function()composite:step(true)end))")
    assert probe.globals().disk == before
    probe.execute("held=true;composite:step(true)")
    events = [row["payload"] for row in saved(probe)["outbox"]]
    assert [row["event"] for row in events] == [
        "explicit-initial-ack-fixture",
        "engine_signals",
        "inventory_observation",
    ]
    assert events[1]["payload"]["signals"][0]["frame"] == 101
    assert probe.globals().probe.status(probe.globals().probe)["pending"] == 0


def test_previous_held_callback_wiring_is_a_failing_negative_control(probe):  # noqa: F811
    composed(probe, separate=False)
    probe.execute("held=false;frame=101;fire('battle_faint')")
    assert "held reader" in probe.globals().probe.status(probe.globals().probe)["failed"]
    probe.execute("held=true;assert(not pcall(function()composite:step(true)end))")
    assert len(saved(probe)["outbox"]) == 1


@pytest.mark.parametrize("fault", ["identity", "rom"])
def test_source_context_change_during_frame_still_latches_without_publication(probe, fault):  # noqa: F811
    composed(probe)
    probe.execute("held=false;frame=101")
    if fault == "identity":
        probe.execute("context.context_generation=string.rep('c',32)")
    else:
        probe.execute("hash=string.rep('b',40)")
    probe.execute("fire('battle_faint')")
    assert probe.globals().probe.status(probe.globals().probe)["failed"]
    assert len(saved(probe)["outbox"]) == 1
