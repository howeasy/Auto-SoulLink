"""Polished client hardening (card POLISHED-HARDEN): F-3 inert panel writes, F-4 hello readiness, C-AREA wiring.

Same in-process rig as test_polished_client.py (the overlay ROM, a WRAM image laid out from the overlay .sym).
The IO write log must stay empty on every path here; each guard's docstring names its red control.
"""
from __future__ import annotations

import json
import pathlib
import pytest

from tests.unit.test_polished_client import (  # noqa: F401
    HARNESS,
    ROOT,
    SYM,
    _entry,
    _memory,
    _mons,
    _pair,
    _run,
    roms,
)

lupa = pytest.importorskip("lupa")

MAILBOX = SYM["wSlinkMailbox"][1]
OFF_CAPS, OFF_STATE, OFF_COUNTER = 8, 9, 5
BATTLE_MODE = SYM["wBattleMode"][1]
PARTY_COUNT = SYM["wPartyCount"][1]
MAILBOX_END = SYM["wSlinkMailboxEnd"][1]
PANEL_TEXT = SYM["wSlinkPanelText"][1]
TILEMAP = SYM["wTilemap"][1]
OFF_PAGES = 11
_PANEL = json.loads((pathlib.Path(ROOT) / "data/games/polished_crystal/profile.json")
                    .read_text(encoding="utf-8"))["titles"]["polished"]["overlay"]["panel"]
PANEL_LINES, PANEL_STRIDE = _PANEL["lines"], _PANEL["stride"]
CAPS_PANEL_SFX = 0x03   # a LYING caps byte: panel + SFX, so every gate but the writer is open
SFX_BOO = 3


def _build(roms, extra=None):  # noqa: F811
    """A composed Polished client over a Lua-side mutable System Bus table: (lua, parts, io, log, mem)."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    memory = _memory(_mons())
    memory.update(extra or {})
    mem = lua.table_from(memory)
    deps, io, log = lua.execute(HARNESS.replace("ROOTDIR", json.dumps(ROOT)))(roms[1], mem)
    parts, why = _pair(_entry(lua).build(deps))
    assert why is None, why
    return lua, parts, io, log, mem


def _hellos(log):
    return [json.loads(line) for line in log.sent.values() if json.loads(line)["event"] == "hello"]


# ── H1 (F-3, rewritten for POL-PANEL Stage 2): the panel's write path is NARROW ─────────────

def test_a_panel_page_lands_only_inside_the_overlay_mailbox(roms):  # noqa: F811
    """F-3's blanket refuse-all is retired: the panel is live, and its permit is what holds the line.

    The caps byte CLAIMS panel + SFX, so every gate but the writer is open. A held page taken
    through a real open must then stage INSIDE the overlay's own mailbox span and nowhere else --
    in particular the tilemap must not move, because Polished's panel is a native text box and has
    no business touching the screen buffer -- and a write aimed outside that span is still refused
    rather than silently dropped.

    Red control (applied): drop the `narrow` region from the Panel.writes call in compose_polished
    and the containment assertion fails; drop the permit entirely and the refusal raises."""
    lua, parts, io, log, mem = _build(roms, {MAILBOX + OFF_CAPS: CAPS_PANEL_SFX,
                                            MAILBOX + 31: 0xA5,      # the service's init cookie
                                            MAILBOX: 0x53, MAILBOX + 1: 0x4C,
                                            MAILBOX + 2: 0x4E, MAILBOX + 3: 0x4B, MAILBOX + 4: 3})
    client, panel = parts.client, parts.panel
    client.start(client)
    for frame in range(3):  # the sampled counter moves each frame: the binder reads FRESH
        mem[MAILBOX + OFF_COUNTER] = frame + 1
        _run(io, client, 1)
    assert panel.present(panel) and panel.sfx_present(panel), "the lying caps byte must open every other gate"

    tiles = [mem[TILEMAP + i] for i in range(64)]
    assert panel.hold(panel, lua.table_from(["SOUL LINK", "PARTNER: RED"])) is True
    mem[MAILBOX + OFF_STATE] = 0  # CLOSED observed while present, then AWAIT: the only arming edge
    mem[MAILBOX + OFF_COUNTER] = 10
    _run(io, client, 1)
    mem[MAILBOX + OFF_STATE] = 1
    mem[MAILBOX + OFF_COUNTER] = 11
    _run(io, client, 1)

    addresses = [int(log.writes[i]["addr"]) for i in range(1, len(log.writes) + 1)]
    assert addresses, "a real open must stage the page"
    assert all(MAILBOX <= a < MAILBOX_END for a in addresses), sorted(addresses)
    assert PANEL_TEXT in addresses and MAILBOX + OFF_PAGES in addresses
    assert mem[MAILBOX + OFF_STATE] == 2, "STAGED is published last"
    assert [mem[TILEMAP + i] for i in range(64)] == tiles, "the panel must not paint the tilemap"
    # C-WRITE r2: the composition also hooks the overworld HOLD site (25:51BF, SLink-gen2-checkpoint);
    # the hook registers nothing on its own and writes nothing without a command.
    # C-EXPLODE: the composition also hooks the battle hold (0f:416A, SLink-gen2-battle-hold): the explode PC hold, nothing written on its own.
    assert set(log.hooks.values()) <= {'SLink-gen2-polished:capture_party', 'SLink-gen2-checkpoint', 'SLink-gen2-battle-hold'}


def test_a_panel_write_outside_the_mailbox_is_still_refused(roms):  # noqa: F811
    """The other half of H1: a write aimed outside the span is REFUSED, not silently dropped, even
    when the caller arms the permit with an allow() that says yes to everything.

    Red control (applied): make P.writes' bounds accept any WRAM0 address and this stops raising."""
    lua, parts, io, log, mem = _build(roms, {MAILBOX + OFF_CAPS: CAPS_PANEL_SFX})
    w = parts.panel_writes
    w.arm(w, "panel", lambda addr, n: True)
    for addr, n in ((TILEMAP, 4), (MAILBOX_END - 4, 8), (PANEL_TEXT + PANEL_LINES * PANEL_STRIDE, 1)):
        with pytest.raises(Exception, match="refused"):
            w.write_bytes(w, addr, lua.table_from([1] * n))
    w.disarm()


# ── H2 (F-4): hello_unheld still needs out-of-battle and a stable party ─────

def test_no_first_hello_in_a_battle_then_one_once_it_ends(roms):  # noqa: F811
    """Red control (applied): the old one-line hello_unheld return sends the first hello in the battle frame."""
    _, parts, io, log, mem = _build(roms, {BATTLE_MODE: 1})
    client = parts.client
    client.start(client)
    _run(io, client, 40)
    assert _hellos(log) == [], list(log.lines.values())
    mem[BATTLE_MODE] = 0
    _run(io, client, 3)
    assert _hellos(log) == []  # a stable party takes several polls, not one
    _run(io, client, 20)
    assert len(_hellos(log)) == 1 and _hellos(log)[0]["in_battle"] is False
    assert len(log.writes) == 0


MAP_STATUS, SCRIPT_RUNNING, LOGIC_PAUSED = (SYM[n][1] for n in ("wMapStatus", "wScriptRunning", "wGameLogicPaused"))


@pytest.mark.parametrize("label, extra", [
    ("main menu / title (wMapStatus START)", {MAP_STATUS: 0}),
    ("map load (wMapStatus ENTER)", {MAP_STATUS: 1}),
    ("script running", {SCRIPT_RUNNING: 1}),
    ("game logic paused (native save / hall of fame)", {LOGIC_PAUSED: 1}),
])
def test_no_first_hello_until_the_overworld_loop_runs(roms, label, extra):  # noqa: F811
    """Live finding: the first hello went out from the CONTINUE screen (frame 286), with a perfectly stable party,
    before the overworld took input. The gate is wMapStatus == HANDLE (2) with no script and no pause
    (docs/polished/HELLO_GATE.md). Red control (applied): drop the gate from the readiness predicate -> every case sends."""
    _, parts, io, log, mem = _build(roms, extra)
    client = parts.client
    client.start(client)
    _run(io, client, 60)
    assert _hellos(log) == [], (label, list(log.lines.values()))
    for address in extra:
        mem[address] = 2 if address == MAP_STATUS else 0
    _run(io, client, 20)
    assert len(_hellos(log)) == 1, label
    assert len(log.writes) == 0


def test_no_first_hello_while_the_party_keeps_changing(roms):  # noqa: F811
    """A party signature that changes every poll never reads stable. Red control (applied): drop the signature
    comparison (hello_sig reset) -> the hello goes out while the party still flips."""
    _, parts, io, log, mem = _build(roms)
    client = parts.client
    client.start(client)
    for frame in range(40):
        mem[PARTY_COUNT] = 2 + frame % 2
        _run(io, client, 1)
    assert _hellos(log) == [], list(log.lines.values())
    mem[PARTY_COUNT] = 3
    _run(io, client, 20)
    assert len(_hellos(log)) == 1 and len(_hellos(log)[0]["party"]) == 3


# ── H3 (C-AREA wiring): the composed client resolves areas through area_map.json ─

def test_the_composed_client_names_new_bark_town(roms):  # noqa: F811
    """group 24, number 4 -> new_bark_town in the composed pack, the tick and the hello. Red control (applied):
    area_map={} in compose_polished -> ("", "map_24_4")."""
    _, parts, io, log, _ = _build(roms)
    client = parts.client
    client.start(client)
    _run(io, client, 30)
    (hello,) = _hellos(log)
    assert (hello["area_id"], hello["loc_name"]) == ("new_bark_town", "New Bark Town")
    assert parts.data.area_map["6148"]["area_id"] == "new_bark_town"  # 24 * 256 + 4
    ticks = [json.loads(line) for line in log.sent.values() if json.loads(line)["event"] == "tick"]
    assert ticks and (ticks[-1]["area_id"], ticks[-1]["loc_name"]) == ("new_bark_town", "New Bark Town")
