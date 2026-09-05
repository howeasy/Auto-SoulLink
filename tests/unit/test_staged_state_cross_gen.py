"""Shared staging must preserve each adapter's mode and data without enabling runtime features."""
import pytest

from server.adapters import get_adapter
from server.protocol_journal import JournalError
from server.staged_state import StagedSoulLinkState
from server.state import SoulLinkState


@pytest.mark.parametrize("game,title,is_rr", [
    ("gen1_rby", "Yellow", False), ("gen2_crystal", "crystal", False),
    ("gen3_frlge", "firered", False), ("gen3_frlge", "firered_rr", True),
    ("gen3_frlge", "", True), ("gen4_hgsspt", "heartgold", False), ("gen5_bw", "black", False),
])
def test_shared_state_staging_roundtrip_across_generations(tmp_path, game, title, is_rr):
    state = SoulLinkState(data_dir=str(tmp_path), adapter=get_adapter(game, rom_type=title, is_rr=is_rr), is_rr=is_rr)
    state.rom_type = title
    state.party_keys = {"a": {"adapter-specific-key"}, "b": set()}
    state.party_size = {"a": 2, "b": 1}
    state._has_helld = {"a", "b"}
    state.queued_commands["b"] = [{"cmd": "hud_show", "text": "shared transport"}]
    size = state.adapter.party_blob_size()
    if size:
        # Use the real ingestion path, including its bytes-valued cache.
        raw = bytes(i % 256 for i in range(size))
        state._ingest_party_blobs("a", [{"slot": 0, "key": "adapter-specific-key", "species_id": 1,
                                        "level": 5, "blob_hex": raw.hex()}])
        assert state.partner_blobs["a"][0]["blob"] == raw
    staged = StagedSoulLinkState.from_live(state, {"retired_pairs": []})
    restored = StagedSoulLinkState.restore(staged.document(), data_dir=str(tmp_path))
    assert restored.adapter.game_id == state.adapter.game_id
    assert restored.is_rr is is_rr
    assert restored.document() == staged.document()
    assert restored.partner_blobs == state.partner_blobs
    if size:
        assert type(restored.partner_blobs["a"][0]["blob"]) is bytes
    if hasattr(restored.adapter, "_is_rr"):
        assert restored.adapter._is_rr is is_rr
    assert not list(tmp_path.glob("*.json"))


def test_ephemeral_ghost_samples_and_relays_cannot_enter_durable_staging(tmp_path):
    state = SoulLinkState(data_dir=str(tmp_path), adapter=get_adapter("gen3_frlge", is_rr=True),
                          is_rr=True, overworld_presence=True)
    state.rom_type = "firered_rr"
    staged = StagedSoulLinkState.from_live(state, {"retired_pairs": []})
    before = staged.document()
    with pytest.raises(JournalError, match="volatile channel"):
        staged.handle_event("a", {"event": "ghost_pos", "x": 2, "y": 3})
    assert staged.document() == before
    with pytest.raises(JournalError, match="volatile channel"):
        staged.take_commands("a", [{"cmd": "ghost_pos", "x": 2, "y": 3}])
    assert staged.document() == before
    state.handle_event("a", {"event": "ghost_pos", "x": 2, "y": 3})
    with pytest.raises(JournalError, match="volatile channel"):
        StagedSoulLinkState.from_live(state, {"retired_pairs": []})
