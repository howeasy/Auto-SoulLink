"""Tripwire for the Gen 3 unit-test harness: which World kinds arm the native ABI-2 path.

The vanilla FR/LG/Emerald COMPANION artifact (production: true) builds with lua/gen3/entry.lua
`fr_native` armed (native.lua constructed, the client binds the session epoch into the native
nonce); the CLEAN artifact never does. Migrating the unit worlds from clean to companion
therefore changes more than the engine sites (frame_control / trade_begin): a test that asserts
native_present False, or hello/write ordering, can go red for reasons unrelated to the sites.
RR is the control: its companion already arms native and always did.
"""
import pytest

from tests.unit.gen3_world import World, pack_json

ARMED = [("gen3_frlg", "firered"), ("gen3_frlg", "leafgreen"), ("gen3_emerald", "emerald"),
         ("gen3_rr", "radical_red")]


@pytest.mark.parametrize("pack,title", ARMED)
def test_companion_world_arms_native_clean_world_does_not(pack, title):
    assert World(pack, title, "companion").parts.native_present is True
    if pack != "gen3_rr":                      # clean RR is not a vanilla title: assert FR/LG/E only
        assert World(pack, title, "clean").parts.native_present is False


@pytest.mark.parametrize("pack,title", ARMED[:3])
def test_vanilla_companion_world_has_companion_evidence_only_once_the_mailbox_is_written(pack, title):
    """Companion evidence comes from cartridge RAM (the mailbox), never from the artifact kind: a bare
    companion world sends no companion_abi (the refusal thread pins that), write_companion_mailbox()
    supplies it."""
    w = World(pack, title, "companion")
    nat = pack_json(pack, "profile.json")["native"]
    assert w._read(nat["BASE"], 4) == 0
    assert w.write_companion_mailbox() is True
    assert w._read(nat["BASE"], 4) == nat["SIG"] and w._read(nat["BASE"] + 4, 2) == nat["ABI"] == 2
    # a clean (MODEL) world has no mailbox
    assert World(pack, title, "clean")._read(nat["BASE"], 4) == 0


def test_rr_companion_world_keeps_its_mailbox_free_start_but_can_write_one():
    w = World("gen3_rr", "radical_red", "companion")
    nat = pack_json("gen3_rr", "profile.json")["native"]
    assert w._read(nat["BASE"], 4) == 0
    assert w.write_companion_mailbox() is True and w._read(nat["BASE"] + 4, 2) == nat["ABI"] == 1
