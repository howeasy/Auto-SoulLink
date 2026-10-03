"""Gen 2 server title binder (card gen2-U4; docs/gen2/reviews/P3B7_PLAN_CODEX_2026-09-23.md).

`Gen2GSCAdapter` needs a title, but the generic factory forwards `is_rr`/`rom_type`
(server.py hello, state.py persisted reload, server.py rom_content). The binder lives in
the adapter (`_TITLE_FOR_ROM_TYPE`), so shared code keeps no `game_id` branch.

All six Gen 2 rom_type rows now select `gen2_gsc` (U5, O-22/O-23;
docs/gen2/reviews/OMP_U5_CUTOVER_FACTS_2026-09-23.md), which the live-row test below pins against the
real registry; the `cutover` fixture re-points them anyway, so a regressed row is repaired here rather
than turning every hello test into a row test.

Patch-first (owner 2026-10-02): the SLink companion overlay is REQUIRED for every Gen 2 title, so a
clean Gen 2 hello is REFUSED (server/adapters/gen2_gsc.companion_refusal) and a run commits "overlay".
Nothing here is about patching -- the title binder is -- so every cartridge below connects as the
artifact its title requires. The refusals themselves belong to test_companion_required_gen2.py.
"""
from __future__ import annotations

import itertools

import pytest

from server import adapters
from server.adapters import (
    _ROM_TYPE_TO_FOUNDATION,
    adapter_class_for_rom_type,
    game_id_for_rom_type,
    get_adapter,
)
from server.adapters.gen2_gsc import _TITLE_FOR_ROM_TYPE, Gen2GSCAdapter
from server.server import SLinkServer
from tests.unit.companion_evidence import companion
from tests.unit.test_mixed_foundations import _hello, _refused, _session

TITLE = {"Crystal": "crystal", "crystal": "crystal", "Gold": "gold", "gold": "gold",
         "Silver": "silver", "silver": "silver"}
GEN2 = tuple(TITLE)
AP = ("Crystal (AP)", "crystal_ap")


def _cart(rom_type):
    """A cartridge of `rom_type` that CONNECTS: the companion evidence its title requires.

    Gen 2 needs `overlay`, Gen 3 `companion`, Gen 1 Red/Blue `named` + `panel`. These tests are
    about the TITLE binder, so each half connects as the prepared cartridge a player would run.
    """
    return {"rom_type": rom_type, **companion(rom_type)}


@pytest.fixture
def cutover(monkeypatch):
    """The G3 cutover's row flip, test-local: every Gen 2 spelling -> gen2_gsc."""
    for rom_type in GEN2:
        monkeypatch.setitem(adapters._ROM_TYPE_TO_GAME_ID, rom_type, "gen2_gsc")


# ── the binder via the generic factory ───────────────────────────────────────────────────

@pytest.mark.parametrize("rom_type", GEN2)
def test_every_gen2_spelling_binds_its_title_through_the_generic_factory(rom_type):
    # the exact kwarg shapes of server.py hello, state.py reload and rom_content ingest
    for kwargs in ({"is_rr": False, "rom_type": rom_type},
                   {"is_rr": False, "rom_type": rom_type, "artifact_kind": "clean"}):
        adapter = get_adapter("gen2_gsc", **kwargs)
        assert isinstance(adapter, Gen2GSCAdapter)
        assert adapter.title == TITLE[rom_type] and adapter.game_id == "gen2_gsc"


def test_the_binder_covers_exactly_the_gen2_gsc_foundation_rows():
    """A spelling added to the pairing rows without a title binding -> red (and vice versa)."""
    rows = {rt for rt, foundation in _ROM_TYPE_TO_FOUNDATION.items() if foundation == "gen2_gsc"}
    assert rows == set(_TITLE_FOR_ROM_TYPE) == set(GEN2)


@pytest.mark.parametrize("kwargs", [
    {"rom_type": "crystal_ap"}, {"rom_type": "Crystal (AP)"}, {"rom_type": ""},
    {"rom_type": "CRYSTAL"}, {"rom_type": "red"}, {"rom_type": "firered_rr", "is_rr": True},
    {"rom_type": "Gold", "is_rr": True}, {"rom_type": "Gold", "title": "crystal"},
    {"rom_type": "Gold", "artifact_kind": "built"}, {},
], ids=lambda k: repr(k))
def test_the_binder_refuses_what_is_not_an_admitted_gen2_title(kwargs):
    with pytest.raises(ValueError):
        get_adapter("gen2_gsc", **kwargs)


def test_overlay_with_the_cartridges_own_evidence_is_the_only_admitted_gen2_kind():
    """P4.3d (d5697cfb): the adapter binds the overlay kind (native trade UI / info panel on).

    The claim's second half used to be "admission keeps it future", written while the overlay
    was deliberately not admitted. Owner 2026-10-02 made the overlay the ONLY admitted kind,
    so the name is historical and the rule is now asserted: overlay admitted, clean refused.
    The refusal is exercised end to end in tests/unit/test_companion_required_gen2.py.
    """
    adapter = get_adapter("gen2_gsc", rom_type="Gold", artifact_kind="overlay")
    assert adapter.native_trade_ui() and adapter.supports_info_panel()
    assert Gen2GSCAdapter.companion_refusal({"rom_type": "Gold", "artifact_kind": "overlay", "companion_abi": 3}) is None
    # the kind alone is a claim, not evidence: the cartridge's own live mailbox ABI must come with it
    assert "needs the SLink companion patch" in Gen2GSCAdapter.companion_refusal(
        {"rom_type": "Gold", "artifact_kind": "overlay"})
    assert "needs the SLink companion patch" in Gen2GSCAdapter.companion_refusal(
        {"rom_type": "Gold", "artifact_kind": "clean"})


def test_the_live_rows_reflect_the_u5_cutover():
    """Row-flip verdict: Crystal, Gold and Silver all flip at U5 (O-22/O-23; the launcher now
    runs lua/gen2/run.lua for any of them); `crystal_ap` is refused and routes nowhere (O-25)."""
    for rom_type in GEN2:
        assert game_id_for_rom_type(rom_type) == "gen2_gsc", rom_type
    for rom_type in AP:
        assert game_id_for_rom_type(rom_type) is None, rom_type


def test_after_the_flip_the_class_lookup_answers_pairing_without_a_title(cutover):
    for rom_type in GEN2:
        assert adapter_class_for_rom_type(rom_type) is Gen2GSCAdapter
        assert Gen2GSCAdapter.pairing_kind("clean") == "clean"
    for rom_type in AP:  # O-25: AP is refused, so it has no class either
        assert adapter_class_for_rom_type(rom_type) is None


# ── hello: first hello binds, the run's title is then locked ────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("first,second", list(itertools.product(GEN2, GEN2)))
async def test_first_hello_binds_the_title_and_every_mixed_pairing_keeps_it(
        tmp_path, cutover, first, second):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", _cart(first))))
        adapter = srv.state.adapter
        assert isinstance(adapter, Gen2GSCAdapter) and adapter.title == TITLE[first]
        assert srv.adapter is adapter
        assert not _refused(await send(_hello("b", _cart(second))))  # O-16
        assert not srv.state.identity_error, srv.state.identity_error
        assert srv.state.adapter is adapter and adapter.title == TITLE[first]
    finally:
        await close()


@pytest.mark.asyncio
@pytest.mark.parametrize("other", ["red", "Red", "PureRed", "firered", "firered_rr",
                                   "emerald"])
@pytest.mark.parametrize("gen2_first", [True, False], ids=["gen2_first", "other_first"])
async def test_after_the_flip_gen2_still_never_pairs_with_another_foundation(
        tmp_path, cutover, other, gen2_first):
    committed, joining = ("Gold", other) if gen2_first else (other, "Gold")
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", _cart(committed))))
        adapter = srv.state.adapter
        assert _refused(await send(_hello("b", _cart(joining))))
        # The refusal must be the FOUNDATION lock, not the patch gate: both halves now connect
        # patched, so without this a clean-cartridge refusal would satisfy _refused() too.
        assert "Mixed games" in srv.state.identity_error["b"], srv.state.identity_error
        assert srv.state.adapter is adapter and srv.state.rom_type == committed
    finally:
        await close()


# ── reconnect and persisted reload ───────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("first", ["Crystal", "gold", "Silver"])
async def test_persisted_reload_restores_the_title_and_a_mixed_reconnect_keeps_it(
        tmp_path, cutover, first):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", _cart(first))))
        others = [rt for rt in ("Crystal", "Gold", "Silver") if TITLE[rt] != TITLE[first]]
        assert not _refused(await send(_hello("b", _cart(others[0]))))
    finally:
        await close()
    srv.state._save()

    # state.py reload (SoulLinkState.load via the server constructor) starts from the
    # default Gen 3 adapter and must re-bind the title from the persisted rom_type.
    reloaded = SLinkServer(data_dir=str(tmp_path))
    adapter = reloaded.state.adapter
    assert isinstance(adapter, Gen2GSCAdapter), type(adapter)
    assert adapter.title == TITLE[first] and reloaded.state.rom_type == first
    assert reloaded.adapter is adapter

    send, close = await _session(reloaded)
    try:
        for player, rom_type in (("b", others[1]), ("a", others[0])):  # mixed-title reconnects
            assert not _refused(await send(_hello(player, _cart(rom_type))))
            assert reloaded.state.adapter is adapter and adapter.title == TITLE[first]
            assert reloaded.state.rom_type == first
    finally:
        await close()
