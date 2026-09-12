"""Ordinary physical changes refresh trade planning without minting identities."""

import copy
import secrets
from types import SimpleNamespace

import pytest

from server.gen1_frame_journal import returned
from server.gen1_party_codec import PartyCodec
from server.gen1_run_config import create_runtime
from server.party_observation_cache import refresh
from tests.unit.test_gen1_atomic_frame_settlement import frame, starters, window
from tests.unit.test_gen1_sessions import contract


@pytest.mark.parametrize("variant,change", [("yellow", "hp"), ("red", "level"), ("blue", "pp")])
def test_ordinary_party_changes_replace_stale_trade_cache(tmp_path, variant, change):
    runtime = create_runtime(tmp_path, contract(variant, variant))
    try:
        starters(runtime)
        before = runtime.state()
        identities = before.identities.document()
        keys = set(before.rules.party_keys["a"])
        old = before.rules.partner_blobs["a"][0]["blob"]
        updated = bytearray(old)
        if change == "hp":
            updated[1:3] = (int.from_bytes(old[1:3], "big") - 1).to_bytes(2, "big")
        elif change == "level":
            codec = PartyCodec(variant)
            updated[33] += 1
            growth = codec.profile["species"][str(updated[0])]["growth_rate"]
            updated[14:17] = codec.experience_for_level(growth, updated[33]).to_bytes(3, "big")
        else:
            updated[29] -= 1
        PartyCodec(variant).validate_blob(bytes(updated))
        observation = copy.deepcopy(
            before.document()["components"]["gen1-inventory-observations"]["a"]["observation"]
        )
        party = bytearray.fromhex(observation["source"]["fields"]["party"])
        party[8:52] = updated[:44]
        observation["source"]["fields"]["party"] = party.hex().upper()
        observation["frame"] += 1
        window(runtime, "a")
        returned(
            runtime,
            "a",
            secrets.token_hex(16),
            frame(runtime, "a", observation, None),
            settle_observations=True,
        )
        after = runtime.state()
        assert after.rules.partner_blobs["a"][0]["blob"] == bytes(updated) != old
        assert after.rules.party_keys["a"] == keys
        assert after.identities.document() == identities
        assert not any(after.rules.pokeballs_obtained.values())
    finally:
        runtime.close()


def test_shared_cache_never_enables_unknown_or_missing_party_members():
    stats = {}
    rules = SimpleNamespace(
        party_size={"a": 2},
        party_keys={"a": {"known", "gone"}},
        partner_blobs={},
        cache_stats=lambda player, key, values: stats.update({key: values}),
    )
    rows = [
        {
            "slot": slot,
            "key": key,
            "species_id": 1,
            "level": 5,
            "blob": b"qualified fixture",
            "stats": {"level": 5},
        }
        for slot, key in enumerate(("known", "unqualified"))
    ]
    refresh(rules, "a", rows)
    assert rules.party_keys["a"] == {"known", "gone"} and rules.party_size["a"] == 2
    rows[0]["key"] = "mutated caller"
    assert rules.partner_blobs["a"][0]["key"] == "known"
