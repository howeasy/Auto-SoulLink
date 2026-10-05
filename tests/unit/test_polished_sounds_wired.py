"""POL-SOUNDS wiring: a sound request from the client reaches the overlay mailbox byte (+7) through the
SAME mailbox-narrowed permit the panel uses (lua/gen2/entry.lua compose_polished), and nowhere else.

Same in-process rig as test_polished_hardening.py (the overlay ROM, a WRAM image laid out from the overlay
.sym). The harness io.write_u8 logs every write with address and value.
"""
from __future__ import annotations

import pytest

from tests.unit.test_polished_hardening import (  # noqa: F401
    MAILBOX,
    MAILBOX_END,
    OFF_CAPS,
    OFF_COUNTER,
    SYM,
    TILEMAP,
    _build,
    _run,
    roms,
)

lupa = pytest.importorskip("lupa")

OFF_SFX = 7
CAPS_REAL = 0x07            # SLINK_CAP_PANEL | SLINK_CAP_SFX | SLINK_CAP_SFX_NOTIFY, what the overlay stores
SE_FAILURE, SFX_FAILURE = 26, 2   # a server play_sound id and the semantic code panel.lua maps it to
COOKIE = {MAILBOX: 0x53, MAILBOX + 1: 0x4C, MAILBOX + 2: 0x4E, MAILBOX + 3: 0x4B, MAILBOX + 4: 3, MAILBOX + 31: 0xA5}


def _fresh(roms, caps=CAPS_REAL):  # noqa: F811
    """A composed client whose binder reads FRESH, with native sounds switched on by a server config."""
    lua, parts, io, log, mem = _build(roms, {**COOKIE, MAILBOX + OFF_CAPS: caps})
    client = parts.client
    client.start(client)
    for frame in range(3):
        mem[MAILBOX + OFF_COUNTER] = frame + 1
        _run(io, client, 1)
    client.handle_command(client, lua.table_from({"cmd": "config", "native_sounds": True}))
    return lua, parts, client, io, log, mem


def _writes(log):
    return [(int(log.writes[i]["addr"]), int(log.writes[i]["value"])) for i in range(1, len(log.writes) + 1)]


def test_a_client_sound_event_writes_exactly_one_mailbox_byte(roms):  # noqa: F811
    """play_sound 26 from the server -> one write, MAILBOX+7 = the FAILURE code, and nothing else.

    Red control (applied): revert compose_polished to Panel.new + a refuse-all writer and the write never
    lands; widen the narrow region and the address assertion still holds, so the containment test below is
    the second anchor."""
    lua, parts, client, io, log, mem = _fresh(roms)
    base = len(log.writes)
    client.handle_command(client, lua.table_from({"cmd": "play_sound", "sound": SE_FAILURE}))
    _run(io, client, 1)            # the panel's service() posts the queued code in this frame
    new = _writes(log)[base:]
    assert new == [(MAILBOX + OFF_SFX, SFX_FAILURE)], new
    assert mem[MAILBOX + OFF_SFX] == SFX_FAILURE
    assert parts.panel.sfx_native_ids.failure == 0x19, "the composed binder carries the profile's native-id table"


def test_no_sound_without_the_cartridge_bit_or_the_run_switch(roms):  # noqa: F811
    """A cartridge whose caps byte lacks SLINK_CAP_SFX posts nothing, and neither does a client whose
    native_sounds switch is off.

    Red control (applied): drop `panel:sfx_present()` from request_sfx_local and the first half writes."""
    lua, parts, client, io, log, mem = _fresh(roms, caps=0x02)
    base = len(log.writes)
    client.handle_command(client, lua.table_from({"cmd": "play_sound", "sound": SE_FAILURE}))
    _run(io, client, 2)
    assert _writes(log)[base:] == []
    lua, parts, client, io, log, mem = _fresh(roms)
    client.handle_command(client, lua.table_from({"cmd": "config", "native_sounds": False}))
    base = len(log.writes)
    client.handle_command(client, lua.table_from({"cmd": "play_sound", "sound": SE_FAILURE}))
    _run(io, client, 2)
    assert _writes(log)[base:] == []


def test_a_sound_write_outside_the_mailbox_is_refused(roms):  # noqa: F811
    """The permit the sound path rides is the panel's mailbox-narrowed one: a write aimed past the span or
    at the tilemap raises even when armed under the sound path's own reason, and the sound path has no
    reason of its own (no new write kind).

    Red control (applied): make Panel.writes' narrow bounds accept any WRAM0 address and this stops raising."""
    lua, parts, client, io, log, mem = _fresh(roms)
    w = parts.panel_writes
    base = len(log.writes)
    for reason in ("panel", "sfx"):
        w.arm(w, reason, lambda addr, n: True)
        for addr in (TILEMAP, MAILBOX_END, MAILBOX - 1):
            with pytest.raises(Exception, match="refused"):
                w.write_bytes(w, addr, lua.table_from([SFX_FAILURE]))
        w.disarm()
    assert _writes(log)[base:] == []
    assert SYM["wSlinkMailboxEnd"][1] == MAILBOX_END
