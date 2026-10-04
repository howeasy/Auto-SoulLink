"""Pack-aware pairing (docs/gen3/PLAN.md §5.1, card gen3-P3a-C3a-1).

A `game_id` is too coarse to pair on: Radical Red and vanilla FireRed share `Gen3Adapter`,
so the old comparison let a clean FireRed join a run committed to RR. Pairing now compares
a DERIVED foundation (`foundation_for_rom_type`) plus a pairing kind normalized by the
foundation's adapter CLASS, and the check runs BEFORE the per-cartridge capability updates
and the adapter reselection -- a refused hello leaves the run exactly as it found it.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from server.adapters import (
    adapter_class_for_rom_type,
    foundation_for_rom_type,
    get_adapter,
)
from server.server import _KNOWN_ARTIFACT_KINDS, SLinkServer
from tests.unit.companion_evidence import companion
from tests.unit.protocol_schema import ARTIFACT_KINDS

# Patch-first (owner 2026-10-02): a clean FR/LG/Emerald/RR hello is refused for lack of the companion, so
# every cartridge that has to CONNECT here declares the companion.
RR = {"rom_type": "firered_rr", "artifact_kind": "companion"}
RR_CLEAN = {"rom_type": "firered_rr", "artifact_kind": "clean"}
FR = {"rom_type": "firered", "artifact_kind": "companion"}
LG = {"rom_type": "leafgreen", "artifact_kind": "companion"}
EM = {"rom_type": "emerald", "artifact_kind": "companion"}


async def _session(srv):
    tcp = await asyncio.start_server(srv.handle_client, "127.0.0.1", 0)
    port = tcp.sockets[0].getsockname()[1]
    r, w = await asyncio.open_connection("127.0.0.1", port)

    async def send(msg):
        w.write((json.dumps(msg) + "\n").encode())
        await w.drain()
        return json.loads(await asyncio.wait_for(r.readline(), 15))

    async def close():
        w.close()
        tcp.close()
        await tcp.wait_closed()
    return send, close


def _hello(player: str, cart: dict, *, with_companion=True, **extra) -> dict:
    # Deliberate missing-patch controls opt out; ordinary fixtures reach the
    # pairing/identity guard with their title's exact mailbox ABI.
    evidence = companion(cart.get("rom_type", "")) if with_companion else {}
    return {**evidence, "event": "hello", "player": player, "trainer_name": player.upper(),
            "ot_id": "30B8" if player == "a" else "7B0B", "has_pokeballs": True,
            "party": [], **cart, **extra}


def _refused(reply) -> bool:
    return any(c.get("cmd") == "hud_show" and "MIXED GAMES" in c.get("text", "")
               for c in reply["commands"])


def _snapshot(srv) -> dict:
    """Everything a refused hello must not touch: persisted bytes + presentation caches."""
    links = Path(srv.state._links_path)
    links = links.read_bytes() if links.exists() else b""
    return {
        "links": links,
        "rom_type": srv.state.rom_type,
        "artifact_kind": srv.state.artifact_kind,
        "adapter": id(srv.adapter),
        "is_rr": srv.state.is_rr,
        "mon_cache": dict(srv._mon_cache),
        "party_details": json.dumps(srv.party_details, sort_keys=True),
        "panel_sig": dict(srv._last_panel_sig),
    }


# ── the derivation itself ────────────────────────────────────────────────────────────────

def test_the_two_gen3_foundations_are_distinct_but_share_one_adapter():
    assert foundation_for_rom_type("firered") == "gen3_frlg"
    assert foundation_for_rom_type("leafgreen") == "gen3_frlg"
    assert foundation_for_rom_type("firered_rr") == "gen3_rr"
    assert foundation_for_rom_type("emerald") == "gen3_emerald"
    assert (adapter_class_for_rom_type("firered")
            is adapter_class_for_rom_type("firered_rr")), "same class, different foundations"


def test_every_other_pack_keeps_its_game_id_as_its_foundation():
    # `platinum` WAS in this list. It is gone because the fallback it relied on stopped
    # being true for Gen 4: every Gen 4 title shares the one game_id `gen4_hgsspt`, so
    # heartgold, soulsilver, heartgold_hge, platinum, hgss and renegade_platinum all
    # derived `gen4_hgsspt` and any two of them paired. Gen 4 now carries explicit
    # foundation rows (docs/gen4/PLAN.md §4.5); `platinum` itself is unrouted.
    # Pinned by tests/unit/test_gen4_foundation.py.
    for rom_type in ("red", "blue", "yellow", "pokemon_black"):
        assert foundation_for_rom_type(rom_type) == adapter_class_for_rom_type(rom_type)().game_id
    # Gen 2 left this list at P3a: one explicit foundation for all three titles
    # (tests/unit/test_gen2_pairing_matrix.py), not the legacy game_id.
    assert foundation_for_rom_type("crystal") == "gen2_gsc"
    # pureRGB is already a foundation of its own by game_id.
    assert foundation_for_rom_type("PureRed") == "gen1_purergb"
    assert foundation_for_rom_type("red") != foundation_for_rom_type("PureRed")


def test_an_unknown_rom_type_derives_nothing():
    assert foundation_for_rom_type("sapphire") is None
    assert adapter_class_for_rom_type("sapphire") is None


def test_pairing_kind_is_a_class_lookup_and_does_not_move_the_committed_kind():
    gen1 = adapter_class_for_rom_type("red")
    gen3 = adapter_class_for_rom_type("firered_rr")
    assert gen1.pairing_kind("named") == "clean" and gen1.pairing_kind("overlay") == "overlay"
    assert gen1.pairing_kind("companion") == "companion", "Gen 1 knows no companion kind"
    assert gen3.pairing_kind("companion") == "clean" and gen3.pairing_kind("rand") == "rand"
    # The committed kind is whatever was declared: set_artifact_kind never sees the mapping.
    adapter = get_adapter("gen3_frlge", is_rr=True, artifact_kind="companion")
    adapter.set_artifact_kind("companion")
    assert getattr(adapter, "artifact_kind", "companion") == "companion"


# ── the defect: a clean FireRed beside Radical Red ───────────────────────────────────────

@pytest.mark.asyncio
async def test_a_clean_firered_cannot_join_a_companion_rr_run(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", RR, panel=True, sfx=True)))
        assert srv.state.rom_type == "firered_rr"
        assert srv.state.artifact_kind == "companion", "the committed kind is the declared one"
        before = _snapshot(srv)
        reply = await send(_hello("b", FR, panel=True, sfx=True))
        assert _refused(reply)
        assert "Mixed games" in srv.state.identity_error["b"]
        assert "gen3_rr" in srv.state.identity_error["b"]
        assert _snapshot(srv) == before, "a refused hello changed the run (links.json included)"
        assert not srv.connected_players["b"].get("panel"), "capabilities updated before the gate"
        assert not srv.connected_players["b"].get("sfx")
    finally:
        await close()


@pytest.mark.asyncio
async def test_the_reverse_arrival_order_is_refused_too(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", FR)))
        assert srv.state.rom_type == "firered"
        reply = await send(_hello("b", RR))
        assert _refused(reply) and "gen3_frlg" in srv.state.identity_error["b"]
    finally:
        await close()


@pytest.mark.asyncio
async def test_a_clean_rr_is_refused_for_the_companion_and_firered_pairs_with_leafgreen(tmp_path):
    """Variants of ONE foundation still pair (FireRed with LeafGreen). A clean RR no longer pairs with a
    companion RR: it is refused outright for lacking the companion (patch-first, owner 2026-10-02) --
    refused for THAT reason, not as a mixed game."""
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", RR)))
        reply = await send(_hello("b", RR_CLEAN, with_companion=False))
        assert not _refused(reply) and any("COMPANION" in c.get("text", "") for c in reply["commands"])
        assert "needs the SLink companion patch" in srv.state.identity_error["b"]
    finally:
        await close()
    srv2 = SLinkServer(data_dir=str(tmp_path / "second"))
    send, close = await _session(srv2)
    try:
        assert not _refused(await send(_hello("a", FR)))
        assert not _refused(await send(_hello("b", LG)))
        assert not srv2.state.identity_error.get("b")
    finally:
        await close()



# ── Emerald is a third Gen 3 foundation (docs/gen3_emerald/PLAN.md §2 decision 5, EC-1) ───

@pytest.mark.asyncio
@pytest.mark.parametrize("first,second", [(FR, EM), (EM, FR), (RR, EM), (EM, RR)],
                         ids=["fr-then-e", "e-then-fr", "rr-then-e", "e-then-rr"])
async def test_emerald_never_pairs_with_firered_or_rr(tmp_path, first, second):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", first)))
        before = _snapshot(srv)
        reply = await send(_hello("b", second))
        assert _refused(reply), (first, second)
        assert foundation_for_rom_type(first["rom_type"]) in srv.state.identity_error["b"]
        assert _snapshot(srv) == before, "a refused hello changed the run (links.json included)"
    finally:
        await close()


@pytest.mark.asyncio
async def test_emerald_pairs_with_emerald(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", EM)))
        assert not _refused(await send(_hello("b", EM)))
        assert not srv.state.identity_error.get("b") and srv.state.rom_type == "emerald"
    finally:
        await close()

def test_a_restart_re_derives_the_lock_from_the_persisted_rom_type(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    srv.state.rom_type = "firered_rr"
    srv.state.artifact_kind = "companion"
    srv.state._save()
    restarted = SLinkServer(data_dir=str(tmp_path))
    assert restarted.state.rom_type == "firered_rr"
    assert "Mixed games" in restarted._mixed_games_error("b", "firered", "clean")
    assert restarted._mixed_games_error("b", "firered_rr", "clean") == ""


# ── unknown rom_type, declared foundation ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_unknown_rom_type_is_refused_not_absorbed_by_the_installed_adapter(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    installed = srv.adapter.game_id
    send, close = await _session(srv)
    try:
        reply = await send(_hello("a", {"rom_type": "sapphire"}))
        assert any("UNKNOWN ROM" in c.get("text", "") for c in reply["commands"])
        assert "Unknown rom_type" in srv.state.identity_error["a"]
        assert srv.adapter.game_id == installed and not srv.state.rom_type
    finally:
        await close()
    # The pairing check refuses it on its own too, so no caller can absorb it.
    assert "Unknown rom_type" in srv._mixed_games_error("a", "sapphire", "clean")


@pytest.mark.asyncio
async def test_a_hello_that_declares_a_contradictory_foundation_is_refused(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        reply = await send(_hello("a", RR, foundation="gen3_frlg"))
        assert _refused(reply)
        assert "Foundation mismatch" in srv.state.identity_error["a"]
        assert not srv.state.rom_type, "a refused hello commits nothing"
        assert not _refused(await send(_hello("a", RR, foundation="gen3_rr")))
        assert srv.state.rom_type == "firered_rr"
    finally:
        await close()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [{}, {"rom_type": ""}, {"rom_type": None},
                                 {"rom_type": 3}, {"rom_type": ["firered"]}])
async def test_a_hello_without_a_usable_rom_type_cannot_slip_past_the_foundation_lock(
        tmp_path, bad):
    """Codex cx-a66ab55a F1: the lock is DERIVED from rom_type, so no rom_type is no entry.

    The hole: a falsey rom_type skipped both the routing gate and the pairing check, so a
    hello with a valid identity reached `state.handle_event` on a run committed to another
    foundation -- and, worse, cleared a standing pairing rejection on its way through.
    """
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", RR)))
        # Slot b is refused first, so the retry below has a standing rejection to clear.
        assert _refused(await send(_hello("b", FR)))
        standing = srv.state.identity_error["b"]
        before = _snapshot(srv)

        reply = await send(_hello("b", bad, panel=True, sfx=True))
        assert any("UNKNOWN ROM" in c.get("text", "") for c in reply["commands"]), reply
        assert standing and srv.state.identity_error.get("b"), \
            "an invalid retry cleared the standing pairing rejection"
        assert "b" in srv._rom_type_rejected
        assert _snapshot(srv) == before, "a hello with no usable rom_type changed the run"
        assert not srv.connected_players["b"].get("panel")
        assert not srv.connected_players["b"].get("sfx")
        # And nothing was dispatched: slot b never got an identity or a trainer name.
        assert "b" not in srv.state.player_identity
    finally:
        await close()
    # Fail-closed for a direct caller too, not only through the socket.
    assert "Missing rom_type" in srv._mixed_games_error("b", bad.get("rom_type", ""), "clean")


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["", None, False, 0, [], {}, "gen3_frlg", "gen1_rby"])
async def test_a_present_foundation_must_be_the_derived_string(tmp_path, bad):
    """Codex cx-a66ab55a F2: absent is not empty. A key that is there is an assertion."""
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        before = _snapshot(srv)
        reply = await send(_hello("a", RR, foundation=bad, panel=True))
        assert _refused(reply), (bad, reply)
        assert "Foundation mismatch" in srv.state.identity_error["a"]
        assert _snapshot(srv) == before, "a refused foundation claim changed the run"
        assert not srv.state.rom_type and not srv.connected_players["a"].get("panel")
    finally:
        await close()


# ── declared artifact_kind: absent defaults to clean, present is an assertion ────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [None, "", False, 0, [], {}])
async def test_a_present_artifact_kind_is_never_coerced_to_clean(tmp_path, bad):
    """docs/protocol.md §2.2: only a MISSING key defaults to `clean`.

    The socket path passed `msg.get("artifact_kind") or "clean"` into
    `_mixed_games_error`, so a present falsey kind (None, "", False, 0, [], {}) became a
    clean-lane admission before the isinstance check could see it, and the commit path
    then stored "clean" for the whole run.
    """
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        reply = await send(_hello("a", {"rom_type": "firered", "artifact_kind": bad}))
        assert _refused(reply), (bad, reply)
        assert "Bad artifact_kind" in srv.state.identity_error["a"]
        assert srv.state.artifact_kind == "", "a refused hello commits no artifact kind"
        assert not srv.state.rom_type and "a" not in srv.state.player_identity
        # Fail-closed for a direct caller too, not only through the socket.
        assert "Bad artifact_kind" in srv._mixed_games_error("a", "firered", bad)
        # And the run is still open: omitting the key is what defaults to clean, which a companion
        # title now refuses for the companion (not as a bad kind); declaring the companion connects.
        reply = await send(_hello("a", {"rom_type": "firered"}, with_companion=False))
        assert not _refused(reply) and "needs the SLink companion patch" in srv.state.identity_error["a"]
        assert srv.state.artifact_kind == ""
        assert not _refused(await send(_hello("a", FR)))
        assert srv.state.artifact_kind == "companion"
    finally:
        await close()


def test_the_servers_known_artifact_kinds_match_the_wire_schema():
    """gen2-N16: one list, pinned both ways so a new kind added to either cannot drift."""
    assert set(ARTIFACT_KINDS) == _KNOWN_ARTIFACT_KINDS


@pytest.mark.asyncio
async def test_an_unknown_artifact_kind_string_is_refused(tmp_path):
    """gen2-N16 (carried from N15's ca0888b): N15 only stopped a MISSING/falsey kind from being
    coerced to "clean" -- a present, non-empty string outside the known set (a typo, or a kind
    no shipped client sends) still fell through `_kind()`/`pairing_kind()` unchanged and got
    committed as this run's artifact kind for good.
    """
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        before = _snapshot(srv)
        reply = await send(_hello("a", {"rom_type": "firered", "artifact_kind": "bogus"}))
        assert _refused(reply)
        assert "Bad artifact_kind" in srv.state.identity_error["a"]
        assert "bogus" in srv.state.identity_error["a"]
        assert _snapshot(srv) == before, "a refused hello changed the run"
        assert not srv.state.rom_type and "a" not in srv.state.player_identity
        # Fail-closed for a direct caller too, not only through the socket.
        assert "Bad artifact_kind" in srv._mixed_games_error("a", "firered", "bogus")
    finally:
        await close()


@pytest.mark.parametrize("kind", sorted(ARTIFACT_KINDS))
def test_every_known_artifact_kind_still_passes_the_guard(tmp_path, kind):
    srv = SLinkServer(data_dir=str(tmp_path))
    assert srv._mixed_games_error("a", "firered", kind) == ""


@pytest.mark.asyncio
async def test_a_declared_named_artifact_kind_still_commits_as_clean(tmp_path):
    """The commit path's `named` -> `clean` mapping is a rule, not a falsey coercion."""
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        # Yellow: a companion title's header-named cartridge is refused for the companion now, so the
        # rule is pinned on the one title that still declares `named` and connects clean.
        assert not _refused(await send(_hello("a", {"rom_type": "yellow",
                                                    "artifact_kind": "named"})))
        assert srv.state.artifact_kind == "clean"
    finally:
        await close()


@pytest.mark.asyncio
async def test_the_matching_and_the_omitted_foundation_are_both_accepted(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", RR, foundation="gen3_rr")))
        assert srv.state.rom_type == "firered_rr"
        assert not _refused(await send(_hello("b", RR)))
        assert not srv.state.identity_error
    finally:
        await close()


@pytest.mark.asyncio
async def test_an_absent_foundation_is_derived_so_an_old_client_still_connects(tmp_path):
    """P4 coexistence: today's RR client sends no `foundation`."""
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", RR)))
        assert not _refused(await send(_hello("b", RR)))
        assert not srv.state.identity_error
    finally:
        await close()


# ── the rules that must not move ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gen1_named_still_pairs_with_clean_and_a_second_game_is_still_refused(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        # Yellow (clean) beside a patched Blue (named): the one clean/named pairing that still connects
        assert not _refused(await send(_hello("a", {"rom_type": "yellow", "artifact_kind": "clean"})))
        assert not _refused(await send(_hello("b", {"rom_type": "blue", "artifact_kind": "named",
                                                    "panel": True})))
        assert srv.state.artifact_kind == "clean"
        assert _refused(await send(_hello("b", {"rom_type": "PureBlue", "artifact_kind": "clean"})))
        assert "Mixed games" in srv.state.identity_error["b"]
    finally:
        await close()


@pytest.mark.asyncio
async def test_purergb_clean_and_overlay_still_never_mix(tmp_path):
    """Owner decision U8: the overlay is a run-level capability, not a per-cartridge patch."""
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", {"rom_type": "PureRed",
                                                    "artifact_kind": "overlay"})))
        assert _refused(await send(_hello("b", {"rom_type": "PureBlue",
                                                "artifact_kind": "clean"})))
        assert "Mixed artifact kinds" in srv.state.identity_error["b"]
        assert not _refused(await send(_hello("b", {"rom_type": "PureBlue",
                                                    "artifact_kind": "overlay"})))
    finally:
        await close()
