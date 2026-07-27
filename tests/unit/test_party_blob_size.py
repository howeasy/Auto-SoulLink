"""Cached party blobs must be validated per game, not against Gen 3's size.

`_ingest_party_blobs` feeds `partner_blobs`, which is the only source the Rival Team Swap
draws from. It used to require exactly 200 hex chars / 100 bytes — Gen 3's boxmon size —
so any other generation's blobs were dropped on the floor. `partner_blobs` stayed empty
and `queue_rival_team_swap` could only ever answer "partner has no cached party blobs".

The size is genuinely per-game and is NOT just the party-struct size: Gen 1 keeps OT names
and nicknames in arrays parallel to the struct, so a faithful copy is 44 + 11 + 11 = 66.

Gen 3 returns 100 — the value that was hardcoded — so its behaviour is unchanged by
construction, which is what makes this safe to put in shared code.
"""
import pytest

from server.adapters import get_adapter
from server.state import SoulLinkState


def _party(blob_len: int, n: int = 2):
    return [{"slot": i, "key": f"KEY{i}", "species_id": 25, "level": 10,
             "blob_hex": "AB" * blob_len} for i in range(n)]


@pytest.mark.parametrize("game_id,rom_type,expected", [
    ("gen1_rby", "Red", 66),
    ("gen3_frlge", "firered", 100),
])
def test_adapter_declares_its_blob_size(game_id, rom_type, expected):
    assert get_adapter(game_id, rom_type=rom_type).party_blob_size() == expected


def test_default_is_zero_so_unopted_games_store_nothing():
    """A game that hasn't opted in must store nothing rather than unvalidated bytes."""
    from server.adapters.base import GameRulesAdapter
    assert GameRulesAdapter.party_blob_size(object()) == 0


@pytest.mark.parametrize("game_id,rom_type,size", [
    ("gen1_rby", "Red", 66),
    ("gen3_frlge", "firered", 100),
])
def test_correctly_sized_blobs_are_cached(game_id, rom_type, size):
    st = SoulLinkState(adapter=get_adapter(game_id, rom_type=rom_type))
    st._ingest_party_blobs("a", _party(size))
    assert len(st.partner_blobs["a"]) == 2, (
        f"{game_id} blobs of its own declared size were rejected"
    )
    assert all(len(e["blob"]) == size for e in st.partner_blobs["a"])


def test_gen1_blobs_were_dropped_under_the_old_hardcoded_size():
    """The actual regression: Gen 1's 66-byte blobs are not 100 bytes."""
    st = SoulLinkState(adapter=get_adapter("gen1_rby", rom_type="Red"))
    st._ingest_party_blobs("a", _party(100))   # a Gen 3-sized blob
    assert st.partner_blobs["a"] == [], "Gen 1 accepted a 100-byte blob it cannot use"


def test_wrong_size_is_rejected_not_truncated():
    st = SoulLinkState(adapter=get_adapter("gen3_frlge", rom_type="firered"))
    st._ingest_party_blobs("a", _party(99) + _party(101))
    assert st.partner_blobs["a"] == []


def test_empty_party_clears_the_cache():
    """Downstream gates read an empty cache as 'partner went offline'."""
    st = SoulLinkState(adapter=get_adapter("gen1_rby", rom_type="Red"))
    st._ingest_party_blobs("a", _party(66))
    assert st.partner_blobs["a"]
    st._ingest_party_blobs("a", [])
    assert st.partner_blobs["a"] == []
