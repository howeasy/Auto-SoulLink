"""Tripwire for the Gen 3 unit-test harness: which World kinds arm the native ABI-2 path.

The vanilla FR/LG/Emerald COMPANION artifact (production: true) builds with lua/gen3/entry.lua
`fr_native` armed (native.lua constructed, the client binds the session epoch into the native
nonce); the CLEAN artifact never does. Migrating the unit worlds from clean to companion
therefore changes more than the engine sites (frame_control / trade_begin): a test that asserts
native_present False, or hello/write ordering, can go red for reasons unrelated to the sites.
RR is the control: its companion already arms native and always did.
"""
import pytest

from tests.unit.gen3_world import World

ARMED = [("gen3_frlg", "firered"), ("gen3_frlg", "leafgreen"), ("gen3_emerald", "emerald"),
         ("gen3_rr", "radical_red")]


@pytest.mark.parametrize("pack,title", ARMED)
def test_companion_world_arms_native_clean_world_does_not(pack, title):
    assert World(pack, title, "companion").parts.native_present is True
    if pack != "gen3_rr":                      # clean RR is not a vanilla title: assert FR/LG/E only
        assert World(pack, title, "clean").parts.native_present is False
