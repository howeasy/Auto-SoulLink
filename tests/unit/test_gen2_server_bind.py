"""Gen 2 server title binder (card gen2-U4; docs/gen2/reviews/P3B7_PLAN_CODEX_2026-09-23.md).

`Gen2GSCAdapter` needs a title, but the generic factory forwards `is_rr`/`rom_type`
(server.py hello, state.py persisted reload, server.py rom_content). The binder lives in
the adapter (`_TITLE_FOR_ROM_TYPE`), so shared code keeps no `game_id` branch.

Crystal's rom_type rows now select `gen2_gsc` (U5, docs/gen2/reviews/OMP_U5_CUTOVER_FACTS_2026-09-23.md);
Gold and Silver still select the legacy `gen2_crystal` adapter (G1 PENDING, no shipped
receipts). The hello-path tests below simulate the FULL eventual cutover by re-pointing all
six Gen 2 rows with monkeypatch, since Gold/Silver's own binder needs to be provable ahead
of their own G1 admission; the live default is asserted to reflect only the Crystal flip.
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
from tests.unit.test_mixed_foundations import _hello, _refused, _session
from tests.unit.companion_evidence import companion

TITLE = {"Crystal": "crystal", "crystal": "crystal", "Gold": "gold", "gold": "gold",
         "Silver": "silver", "silver": "silver"}
GEN2 = tuple(TITLE)
AP = ("Crystal (AP)", "crystal_ap")


def _cart(rom_type):
    cart = {"rom_type": rom_type, "artifact_kind": "clean"}
    if rom_type.lower() not in ("crystal", "gold", "silver"):
        # a Gen 1 / Gen 3 half connects PATCHED (companion required, owner 2026-10-02)
        cart.update(companion(rom_type))
    return cart


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


def test_the_binder_accepts_the_overlay_kind_but_admission_keeps_it_future():
    """P4.3d (d5697cfb): the adapter binds the overlay kind (native trade UI / info panel on);
    admitting a patched ROM is still refused by its FUTURE admission rows until P4.4."""
    adapter = get_adapter("gen2_gsc", rom_type="Gold", artifact_kind="overlay")
    assert adapter.native_trade_ui() and adapter.supports_info_panel()


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
