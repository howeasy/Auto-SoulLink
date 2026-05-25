"""
Unit tests for the Rival Team Swap blob cache.

Phase 4 cleanup: blobs are now piggybacked on the existing tick/hello
party snapshot (one `blob_hex` field per slot in `build_party_snapshot`).
The standalone `party_blob_sync` event was removed; these tests drive
the cache via `tick` / `hello` events instead.

Run:
    pytest tests/unit/test_state_party_blob_cache.py -v
"""

from server.state import SoulLinkState


def _slot(slot=0, species_id=25, level=10, key="AAAA:BBBB", fill_byte=0xAB,
          maxHP=100, hp=100):
    """Build a single party snapshot entry mirroring build_party_snapshot."""
    blob_hex = ("%02x" % fill_byte) * 100
    return {
        "slot": slot, "species_id": species_id, "level": level, "key": key,
        "hp": hp, "maxHP": maxHP, "blob_hex": blob_hex,
    }


def _tick(party):
    """Build a tick event payload carrying a party snapshot."""
    return {"event": "tick", "party": party}


def _hello(party):
    """Build a hello event payload carrying a party snapshot."""
    return {"event": "hello", "party": party,
            "rom_type": "firered_rr", "trainer_name": "TEST"}


def test_blob_cache_starts_empty():
    state = SoulLinkState()
    assert state.partner_blobs["a"] == []
    assert state.partner_blobs["b"] == []


def test_tick_populates_blob_cache():
    state = SoulLinkState()
    state.handle_event("a", _tick([
        _slot(slot=0, species_id=25, level=10, fill_byte=0x01),
        _slot(slot=1, species_id=143, level=42, fill_byte=0x02),
    ]))
    cached = state.partner_blobs["a"]
    assert len(cached) == 2
    assert cached[0]["species_id"] == 25
    assert cached[0]["level"] == 10
    assert cached[0]["blob"] == bytes([0x01] * 100)
    assert cached[1]["species_id"] == 143
    assert cached[1]["blob"] == bytes([0x02] * 100)
    # Partner's cache stays untouched.
    assert state.partner_blobs["b"] == []


def test_hello_populates_blob_cache():
    state = SoulLinkState()
    state.handle_event("a", _hello([
        _slot(slot=0, species_id=6, level=50, fill_byte=0x55),
    ]))
    cached = state.partner_blobs["a"]
    assert len(cached) == 1
    assert cached[0]["species_id"] == 6
    assert cached[0]["blob"] == bytes([0x55] * 100)


def test_tick_replaces_cache_on_resync():
    """Whole-party snapshot semantics: a fresh tick replaces the prior list."""
    state = SoulLinkState()
    state.handle_event("a", _tick([
        _slot(slot=0, species_id=25, fill_byte=0x01),
        _slot(slot=1, species_id=143, fill_byte=0x02),
        _slot(slot=2, species_id=6, fill_byte=0x03),
    ]))
    assert len(state.partner_blobs["a"]) == 3
    state.handle_event("a", _tick([
        _slot(slot=0, species_id=9, fill_byte=0xFF),
    ]))
    cached = state.partner_blobs["a"]
    assert len(cached) == 1
    assert cached[0]["species_id"] == 9
    assert cached[0]["blob"] == bytes([0xFF] * 100)


def test_tick_drops_short_hex_silently():
    """Phase 4: malformed blobs are dropped, other handlers still get the snapshot."""
    state = SoulLinkState()
    bad_slot = {"slot": 0, "species_id": 25, "level": 10, "key": "K",
                "hp": 1, "maxHP": 1, "blob_hex": "ab" * 50}  # 100 hex = 50 bytes
    state.handle_event("a", _tick([bad_slot]))
    assert state.partner_blobs["a"] == []


def test_tick_drops_non_hex_silently():
    state = SoulLinkState()
    bad_slot = {"slot": 0, "species_id": 25, "level": 10, "key": "K",
                "hp": 1, "maxHP": 1, "blob_hex": "z" * 200}
    state.handle_event("a", _tick([bad_slot]))
    assert state.partner_blobs["a"] == []


def test_tick_filters_bad_slots_keeps_good():
    """A mixed party keeps valid slots, drops the invalid ones."""
    state = SoulLinkState()
    state.handle_event("a", _tick([
        _slot(slot=0, species_id=25, fill_byte=0x01),
        {"slot": 1, "species_id": 99, "level": 5, "key": "X",
         "hp": 1, "maxHP": 1, "blob_hex": "short"},
        _slot(slot=2, species_id=143, fill_byte=0x03),
    ]))
    cached = state.partner_blobs["a"]
    assert [c["species_id"] for c in cached] == [25, 143]


def test_tick_empty_party_clears_cache():
    state = SoulLinkState()
    state.handle_event("a", _tick([
        _slot(slot=0, species_id=25, fill_byte=0x01),
    ]))
    assert len(state.partner_blobs["a"]) == 1
    state.handle_event("a", _tick([]))
    assert state.partner_blobs["a"] == []


def test_tick_without_party_field_is_safe():
    """A tick that omits `party` (no save loaded) must not touch the cache."""
    state = SoulLinkState()
    state.handle_event("a", _tick([_slot(slot=0, species_id=25, fill_byte=0x01)]))
    assert len(state.partner_blobs["a"]) == 1
    # No party field at all — must leave the existing cache intact.
    state.handle_event("a", {"event": "tick"})
    assert len(state.partner_blobs["a"]) == 1


def test_per_player_isolation():
    state = SoulLinkState()
    state.handle_event("a", _tick([
        _slot(slot=0, species_id=25, fill_byte=0x01),
    ]))
    state.handle_event("b", _tick([
        _slot(slot=0, species_id=6, fill_byte=0x02),
        _slot(slot=1, species_id=9, fill_byte=0x03),
    ]))
    assert len(state.partner_blobs["a"]) == 1
    assert state.partner_blobs["a"][0]["species_id"] == 25
    assert len(state.partner_blobs["b"]) == 2
    assert state.partner_blobs["b"][0]["species_id"] == 6
