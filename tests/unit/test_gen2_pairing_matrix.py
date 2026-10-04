"""Gen 2 pairing matrix (docs/gen2/PLAN.md §5.9 + P3a.1, owner O-16 and O-8).

Gold, Silver and Crystal share ONE pairing foundation, `gen2_gsc`, for every rom_type
spelling, so every Gen 2 pairing is admitted by the generic derived-foundation comparison
(no title relation in shared code). A Gen 2 half beside a Gen 1 or Gen 3 half is refused
and the refusal changes nothing.

Patch-first (owner 2026-10-02): the SLink companion overlay is REQUIRED for Crystal, Gold and
Silver, so every Gen 2 half that reaches this matrix as an ADMITTED cartridge is an overlay
(`Gen2GSCAdapter.companion_refusal`; the rule itself is tests/unit/test_companion_required_gen2.py).
`_cart` therefore sends the overlay, and the artifact-kind matrix at the bottom keeps only the
overlay column: the clean column no longer admits a run, it is refused, and the tests that used
to pair clean with overlay now assert that refusal.

The runtime adapter was NOT part of this card: `_ROM_TYPE_TO_GAME_ID` kept every Gen 2
spelling on the legacy `gen2_crystal` adapter until U5, which re-pointed Crystal, Gold and
Silver to `gen2_gsc`. Archipelago Crystal (`crystal_ap` / "Crystal (AP)") is REFUSED by
owner ruling O-25: it routes to no game_id and no foundation, so its hello is refused on its
own, beside any Gen 2 half, and whatever it declares. A run persisted under the retired
legacy adapter is refused at load (tests/unit/test_gen2_persisted_cutover.py).
"""
from __future__ import annotations

import copy
import itertools
import re
from pathlib import Path

import pytest

from server.adapters import (
    _REGISTRY,
    _ROM_TYPE_TO_FOUNDATION,
    _ROM_TYPE_TO_GAME_ID,
    foundation_for_rom_type,
    game_id_for_rom_type,
)
from server.server import SLinkServer
from server.state import LinkEntry, LinkStatus, MonInfo
from tests.unit.companion_evidence import companion
from tests.unit.test_mixed_foundations import _hello, _refused, _session, _snapshot

REPO = Path(__file__).resolve().parents[2]
GEN2 = ("Crystal", "crystal", "Gold", "gold", "Silver", "silver")
AP = ("Crystal (AP)", "crystal_ap")
OTHER_GENS = ("red", "Red", "PureRed", "firered", "firered_rr", "emerald")
KEY_A, KEY_B = "AABB:30B8:10", "CCDD:7B0B:13"
REASON = "needs the SLink companion patch"


def _cart(rom_type: str, declare: bool = False) -> dict:
    """A cartridge that MAY connect, carrying its own companion evidence: the required overlay
    for Gen 2, and for every other family what tests/unit/companion_evidence.companion says a
    patched cartridge sends (`{}` for the unrouted spellings, refused before any of this)."""
    cart = {"rom_type": rom_type, **companion(rom_type)}
    if declare:  # the new client (lua/gen2/client.lua) declares it; the legacy one omits it
        cart["foundation"] = "gen2_gsc"
    return cart


def _needs_companion(reply) -> bool:
    return any(c.get("cmd") == "hud_show" and "COMPANION" in c.get("text", "")
               for c in reply["commands"])


def _seed(srv) -> None:
    """Real nonempty run data + sentinels in every cache a refused hello must not touch."""
    entry = LinkEntry(area_id="route_29", a=MonInfo(key=KEY_A, level=5, species=16),
                      b=MonInfo(key=KEY_B, level=5, species=19), status=LinkStatus.ALIVE)
    srv.state.links.append(entry)
    srv.state._index_entry(entry)
    for pid, key in (("a", KEY_A), ("b", KEY_B)):
        srv.party_details[pid][key] = {"species": 16, "level": 5, "hp": 20,
                                       "nickname": f"SENTINEL_{pid}"}
        srv._mon_cache[key] = {"nickname": f"SENTINEL_{pid}", "held_item": 1}
        srv._last_panel_sig[pid] = f"sentinel-{pid}"
    srv.state._save()


def _deep(srv) -> dict:
    links = Path(srv.state._links_path)
    assert links.exists() and KEY_B.encode() in links.read_bytes(), "seed not persisted"
    return {
        "links_json": links.read_bytes(),
        "links": copy.deepcopy(srv.state.links),
        "rom_type": srv.state.rom_type,
        "artifact_kind": srv.state.artifact_kind,
        "adapter": id(srv.adapter),
        "is_rr": srv.state.is_rr,
        "identity": copy.deepcopy(srv.state.player_identity),
        "mon_cache": copy.deepcopy(srv._mon_cache),
        "party_details": copy.deepcopy(srv.party_details),
        "panel_sig": dict(srv._last_panel_sig),
    }


def _gate_snapshot(srv) -> dict:
    _seed(srv)
    return _deep(srv)


# ── the derivation ───────────────────────────────────────────────────────────────────────

def test_every_gen2_spelling_has_its_own_foundation_row_not_the_game_id_fallback():
    """Falsifier: a title-cased alias falling back to the game_id foundation is red.

    Every routed Gen 2 spelling is on `gen2_gsc` (U5); Archipelago Crystal routes nowhere
    (O-25), so the totality check is exactly the six admitted spellings.
    """
    routed = {rt for rt, gid in _ROM_TYPE_TO_GAME_ID.items() if gid == "gen2_gsc"}  # Polished is its own family
    assert routed == set(GEN2), "a Gen 2 spelling was added without a pairing row"
    for rom_type in GEN2:
        assert _ROM_TYPE_TO_FOUNDATION.get(rom_type) == "gen2_gsc", rom_type
        assert foundation_for_rom_type(rom_type) == "gen2_gsc", rom_type


def test_the_rom_types_the_new_client_sends_derive_the_foundation_it_declares():
    """lua/gen2/entry.lua sends Crystal/Gold/Silver with foundation="gen2_gsc"; its dev Polished title sends
    polished_crystal, whose foundation lua/gen2/polished.lua declares (P.FOUNDATION = "gen2_polished")."""
    src = (REPO / "lua/gen2/entry.lua").read_text("utf-8")
    sent = set(re.findall(r'rom_type="([^"]+)"', src))
    assert sent == {"Crystal", "Gold", "Silver", "polished_crystal"}, sent
    assert 'foundation="gen2_gsc"' in src
    assert {foundation_for_rom_type(rt) for rt in sent - {"polished_crystal"}} == {"gen2_gsc"}
    assert 'P.FOUNDATION = "gen2_polished"' in (REPO / "lua/gen2/polished.lua").read_text("utf-8")
    assert foundation_for_rom_type("polished_crystal") == "gen2_polished"


def test_crystal_ap_routes_to_no_game_and_no_foundation():
    """O-25: refused, so it has no row anywhere -- not even a legacy one."""
    for rom_type in AP:
        assert rom_type not in _ROM_TYPE_TO_FOUNDATION and rom_type not in _ROM_TYPE_TO_GAME_ID
        assert foundation_for_rom_type(rom_type) is None, rom_type
        assert game_id_for_rom_type(rom_type) is None, rom_type


# ── the full symmetric Gen 2 matrix: 6 spellings x 6, both arrival orders ────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("declare", [False, True], ids=["omitted", "declared"])
@pytest.mark.parametrize("first,second", list(itertools.product(GEN2, GEN2)))
async def test_every_gen2_pairing_is_admitted(tmp_path, first, second, declare):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", _cart(first, declare))))
        assert srv.state.rom_type == first
        assert not _refused(await send(_hello("b", _cart(second, declare))))
        assert not srv.state.identity_error, srv.state.identity_error
    finally:
        await close()


@pytest.mark.asyncio
@pytest.mark.parametrize("a_declares", [True, False], ids=["a_declares", "b_declares"])
async def test_a_legacy_half_and_a_declaring_half_pair_in_both_orders(tmp_path, a_declares):
    """One half omits `foundation` (legacy client), the other declares gen2_gsc (new)."""
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", _cart("Crystal", a_declares))))
        assert not _refused(await send(_hello("b", _cart("Gold", not a_declares))))
        assert not srv.state.identity_error, srv.state.identity_error
    finally:
        await close()


# ── Gen 2 beside another generation: refused, both orders, nothing changes ──────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("other", OTHER_GENS)
@pytest.mark.parametrize("gen2", ["Crystal", "gold", "Silver"])
@pytest.mark.parametrize("gen2_first", [True, False], ids=["gen2_first", "other_first"])
async def test_a_gen2_half_beside_a_gen1_or_gen3_half_is_refused(tmp_path, other, gen2,
                                                                 gen2_first):
    committed, joining = ((_cart(gen2), _cart(other)) if gen2_first
                          else (_cart(other), _cart(gen2, declare=True)))
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", committed)))
        before = _gate_snapshot(srv)
        reply = await send(_hello("b", joining, panel=True, sfx=True))
        assert _refused(reply), reply
        assert "Mixed games" in srv.state.identity_error["b"]
        assert _deep(srv) == before, "a refused hello changed the run, links.json or a cache"
        assert not srv.connected_players["b"].get("panel")
        assert "b" not in srv.state.player_identity
    finally:
        await close()


@pytest.mark.asyncio
@pytest.mark.parametrize("committed,joining", [
    (_cart("Crystal"), _cart("red")),
    (_cart("red"), _cart("Crystal", declare=True)),
    (_cart("Gold"), _cart("firered_rr")),
    (_cart("firered"), _cart("Gold", declare=True)),
], ids=["gen2_then_gen1", "gen1_then_gen2", "gen2_then_gen3", "gen3_then_gen2"])
async def test_a_refusal_preserves_seeded_run_data_and_every_cache(tmp_path, committed,
                                                                   joining):
    """R5-2: non-vacuous preservation. Resetting slot b's panel sig or clearing the mon
    cache before the pairing gate (server.py handle_client) must turn this red."""
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", committed)))
        before = _gate_snapshot(srv)
        assert before["panel_sig"]["b"] == "sentinel-b" and before["mon_cache"][KEY_B]
        assert before["links"] and before["party_details"]["b"]
        assert _refused(await send(_hello("b", joining, panel=True, sfx=True)))
        after = _deep(srv)
        assert after["links_json"] == before["links_json"], "links.json bytes changed"
        assert after == before
    finally:
        await close()


# ── crystal_ap (O-25: refused) ───────────────────────────────────────────────────────────

def _unsupported(reply) -> bool:
    return any(c.get("cmd") == "hud_show" and "UNKNOWN ROM" in c.get("text", "")
               for c in reply["commands"])


@pytest.mark.asyncio
@pytest.mark.parametrize("declare", [False, True], ids=["omitted", "declared"])
@pytest.mark.parametrize("ap", AP)
async def test_crystal_ap_is_refused_on_its_own_by_name(tmp_path, ap, declare):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        before = _snapshot(srv)
        assert _unsupported(await send(_hello("a", _cart(ap, declare=declare))))
        err = srv.state.identity_error["a"]
        assert "this Crystal build is not supported" in err, err
        assert "a" in srv._rom_type_rejected
        assert _snapshot(srv) == before and not srv.state.rom_type
    finally:
        await close()


@pytest.mark.asyncio
@pytest.mark.parametrize("gsc", ["Crystal", "Gold", "Silver"])
@pytest.mark.parametrize("ap", AP)
async def test_crystal_ap_is_refused_beside_every_gen2_gsc_half(tmp_path, ap, gsc):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", _cart(gsc))))
        before = _gate_snapshot(srv)
        assert _unsupported(await send(_hello("b", _cart(ap))))
        assert "this Crystal build is not supported" in srv.state.identity_error["b"]
        assert _deep(srv) == before
    finally:
        await close()


def test_the_mixed_games_check_refuses_crystal_ap_as_unsupported_too(tmp_path):
    """The lock's own derivation (the other refusal site) names O-25 as well."""
    srv = SLinkServer(data_dir=str(tmp_path))
    for ap in AP:
        err = srv._mixed_games_error("b", ap, "clean")
        assert "this Crystal build is not supported" in err, err


# ── unknown and contradictory hellos ─────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("claim", ["gen2_crystal", "gen1_rby", "gen3_frlg", "", None])
async def test_a_gen2_hello_declaring_another_foundation_is_refused(tmp_path, claim):
    """`gen2_crystal` was the derived value before P3a; it is a contradiction now."""
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        before = _snapshot(srv)
        assert _refused(await send(_hello("a", {"rom_type": "Gold", "foundation": claim},
                                          panel=True)))
        assert "Foundation mismatch" in srv.state.identity_error["a"]
        assert _snapshot(srv) == before and not srv.state.rom_type
        assert not srv.connected_players["a"].get("panel")
    finally:
        await close()


@pytest.mark.asyncio
@pytest.mark.parametrize("unknown", ["GOLD", "Gold (AP)", "pokegold", "gen2_gsc"])
async def test_an_unknown_gen2_like_rom_type_is_refused_and_keeps_the_standing_rejection(
        tmp_path, unknown):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", _cart("Crystal"))))
        assert _refused(await send(_hello("b", _cart("red"))))
        before = _gate_snapshot(srv)
        reply = await send(_hello("b", {"rom_type": unknown}))
        assert any("UNKNOWN ROM" in c.get("text", "") for c in reply["commands"]), reply
        assert srv.state.identity_error.get("b"), "an invalid retry cleared the refusal"
        assert "b" in srv._rom_type_rejected
        assert _deep(srv) == before
    finally:
        await close()


# ── reconnect ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reconnect_keeps_gen2_pairing_and_a_refusal_clears_on_a_gen2_retry(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", _cart("Crystal"))))
        assert not _refused(await send(_hello("b", _cart("Gold"))))
    finally:
        await close()
    send, close = await _session(srv)  # both halves come back on a fresh connection
    try:
        assert not _refused(await send(_hello("b", _cart("gold", declare=True))))
        assert not _refused(await send(_hello("a", _cart("Crystal", declare=True))))
        before = _gate_snapshot(srv)
        assert _refused(await send(_hello("b", _cart("firered"))))  # swapped cartridge
        assert _deep(srv) == before
        assert not _refused(await send(_hello("b", _cart("Silver", declare=True))))
        assert not srv.state.identity_error, "a routable Gen 2 retry must clear the refusal"
        assert srv.state.rom_type == "Crystal", "the committed rom_type is set-once"
    finally:
        await close()


# ── persisted run ────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("persisted", GEN2)
async def test_a_restart_re_derives_gen2_gsc_from_every_persisted_spelling(tmp_path, persisted):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", _cart(persisted))))
        srv.state._save()
    finally:
        await close()
    restarted = SLinkServer(data_dir=str(tmp_path))
    assert restarted.state.rom_type == persisted
    # The persisted run is an OVERLAY run (patch-first: only the overlay half connects), so a
    # Gen 2 probe carries that kind -- and a clean Gen 2 half is refused on the run-wide
    # artifact-kind lock whatever its spelling.
    for rom_type in GEN2:
        assert restarted._mixed_games_error("b", rom_type, "overlay") == "", rom_type
        assert "Mixed artifact kinds" in restarted._mixed_games_error("b", rom_type, "clean"), rom_type
    for rom_type in OTHER_GENS:  # the foundation gate fires before the kind lock, so "clean" is inert here
        assert "Mixed games" in restarted._mixed_games_error("b", rom_type, "clean"), rom_type
    for rom_type in AP:
        assert "this Crystal build is not supported" in restarted._mixed_games_error("b", rom_type, "clean"), rom_type
    send, close = await _session(restarted)
    try:
        assert not _refused(await send(_hello("b", _cart("Silver", declare=True))))
        assert not restarted.state.identity_error
    finally:
        await close()


# ── the cutover boundary: every admitted Gen 2 title moved; AP is refused ───────────────

def test_the_u5_cutover_moved_every_admitted_gen2_title_and_ap_routes_nowhere():
    """U5 (docs/gen2/reviews/OMP_U5_CUTOVER_FACTS_2026-09-23.md, widened by owner ruling
    O-23) flipped Crystal, Gold and Silver together -- per-title admission is Entry.admit's
    job at runtime, not this row. `crystal_ap` is refused (O-25), and P3b.8 removed the
    legacy `gen2_crystal` adapter, so no row may point at it."""
    for rom_type in GEN2:
        assert game_id_for_rom_type(rom_type) == "gen2_gsc", rom_type
    for rom_type in AP:
        assert game_id_for_rom_type(rom_type) is None, rom_type
    assert "gen2_gsc" in _REGISTRY
    assert "gen2_crystal" not in set(_ROM_TYPE_TO_GAME_ID.values())


# ── artifact-kind pairing (P4.3d, ruling O-27 D4) ─────────────────────────────────────────
# Before this card: `Gen2GSCAdapter.set_artifact_kind` required exactly "clean", so a hello
# declaring "overlay" raised ValueError out of `_dispatch` instead of being admitted or
# cleanly refused (an unhandled exception, not a graceful "Mixed artifact kinds" reply).
# `pairing_kind` already returned its argument unchanged, so it needed no change here --
# the fix is adapter DATA only (`set_artifact_kind`, `supports_info_panel`, `native_trade_ui`).
#
# Patch-first (owner 2026-10-02) then retired the "clean" COLUMN of that matrix: the companion
# overlay is required, so a clean Gen 2 hello is refused at its own hello (never reaching
# `_dispatch`, so it commits no run kind and installs no Gen 2 adapter). The mixed-kind lock
# itself is untouched and still fires when a run IS committed -- an overlay run with a clean
# half behind it, or a run persisted under the earlier ruling. Both orders are still refused;
# each order now asserts the refusal that is actually reachable for it.

def _cart_kind(rom_type: str, kind: str, declare: bool = False) -> dict:
    cart = _cart(rom_type, declare)
    cart["artifact_kind"] = kind
    return cart


def test_gen2_gsc_adapter_flips_native_capabilities_on_the_companion_kinds_only():
    """Direct adapter check, no server session: the companion kinds (overlay, and R3's randomized
    rand_overlay) are the only ones that opt in."""
    from server.adapters.gen2_gsc import Gen2GSCAdapter

    adapter = Gen2GSCAdapter("crystal")
    assert not adapter.supports_info_panel() and not adapter.native_trade_ui()
    adapter.set_artifact_kind("clean")
    assert not adapter.supports_info_panel() and not adapter.native_trade_ui()
    adapter.set_artifact_kind("rand_overlay")
    assert adapter.supports_info_panel() and adapter.native_trade_ui()
    adapter.set_artifact_kind("overlay")
    assert adapter.supports_info_panel() and adapter.native_trade_ui()
    for bad in ("named", "rand", "companion", "ghost", ""):
        with pytest.raises(ValueError):
            adapter.set_artifact_kind(bad)
    # A rejected kind must not have partially clobbered the committed one.
    assert adapter.supports_info_panel() and adapter.native_trade_ui()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["overlay"])
async def test_matching_artifact_kinds_pair_and_commit_the_run_wide_capability(tmp_path, kind):
    """Falsifier: overlay<->overlay refused (or raising out of the hello) -> red."""
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", _cart_kind("Crystal", kind))))
        assert not _refused(await send(_hello("b", _cart_kind("Gold", kind, declare=True))))
        assert not srv.state.identity_error, srv.state.identity_error
        assert srv.state.artifact_kind == kind
        assert srv.adapter.supports_info_panel() == (kind == "overlay")
        assert srv.adapter.native_trade_ui() == (kind == "overlay")
    finally:
        await close()


@pytest.mark.asyncio
@pytest.mark.parametrize("declare", [False, True], ids=["omitted", "declared"])
async def test_a_clean_gen2_half_is_refused_and_commits_no_run_wide_capability(tmp_path,
                                                                               declare):
    """The "clean" column of the matrix above, as it survives the ruling: the clean pret build
    is refused for lacking the companion, and the run's kind -- the run-wide native
    capabilities that follow it -- stays uncommitted.

    Falsifier: the clean half admitted, or its refusal committing `artifact_kind` / installing
    the Gen 2 adapter -> red. (The adapter's own clean-vs-overlay capability flip, with no
    session, is `test_gen2_gsc_adapter_flips_native_capabilities_on_overlay_only` above.)
    """
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        reply = await send(_hello("a", _cart_kind("Crystal", "clean", declare)))
        assert _needs_companion(reply), reply
        assert REASON in srv.state.identity_error["a"]
        assert srv.state.artifact_kind == "" and not srv.state.rom_type
        assert srv.adapter.game_id != "gen2_gsc", "a refused hello installed the Gen 2 adapter"
    finally:
        await close()


@pytest.mark.asyncio
@pytest.mark.parametrize("first_kind,second_kind", [("clean", "overlay"), ("overlay", "clean")])
async def test_mixed_artifact_kinds_are_refused_not_admitted(tmp_path, first_kind, second_kind):
    """The card's own falsifier: clean<->overlay admitted -> red.

    Both orders are refused, each on the gate that is reachable for it: a clean FIRST half never
    commits a run (the companion gate), so the overlay half that follows starts an overlay run
    of its own; a clean SECOND half is refused on the run-wide kind lock, which is the whole
    point of this card.
    """
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        first = await send(_hello("a", _cart_kind("Crystal", first_kind)))
        if first_kind == "clean":
            assert _needs_companion(first), first
            assert REASON in srv.state.identity_error["a"]
            assert srv.state.rom_type == "" and srv.state.artifact_kind == ""
            _gate_snapshot(srv)  # a run already carrying real data: the overlay half still joins
            assert not _refused(await send(_hello("b", _cart_kind("Gold", second_kind,
                                                                  declare=True)))), \
                "the clean first half committed a run the overlay half could not join"
            assert srv.state.artifact_kind == "overlay" and srv.state.rom_type == "Gold"
            assert not srv.state.identity_error.get("b")
            return
        assert not _refused(first)
        before = _gate_snapshot(srv)
        reply = await send(_hello("b", _cart_kind("Gold", second_kind, declare=True)))
        assert _refused(reply), reply
        assert "Mixed artifact kinds" in srv.state.identity_error["b"]
        assert _deep(srv) == before, "a refused hello changed the run, links.json or a cache"
    finally:
        await close()
