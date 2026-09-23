"""Gen 2 per-player title binding (card gen2-U4b; docs/gen2/PLAN.md §5.9, owner O-16).

One pairing foundation, three packs. U4 binds the RUN's adapter from the forwarded
rom_type, which leaves the partner answered by the first player's cartridge -- Gold's
Bug-Catching Contest grass and Gold's item table are not Crystal's. The binding is
declared by the adapter (`per_player_key` / `per_player_bound_key`) and applied by a
getattr-gated hook in server.py's hello path, so no title, rom_type or game_id branch
exists in shared code.

What each adapter must answer is read here INDEPENDENTLY from data/games/gen2_<title>/
(a grass-encounter species set and the item names), never from the other adapter.

The production rows still select the legacy adapter until the G3 cutover (U5), so these
tests re-point the six Gen 2 rows with the same monkeypatch U4's tests use.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from server import adapters
from server.adapters import get_adapter
from server.server import SLinkServer
from tests.unit.test_mixed_foundations import _hello, _refused, _session

DATA = Path(__file__).resolve().parents[2] / "data" / "games"
TITLE = {"Crystal": "crystal", "crystal": "crystal", "Gold": "gold", "gold": "gold",
         "Silver": "silver", "silver": "silver"}
GEN2 = tuple(TITLE)
# The Bug-Catching Contest park: both titles have grass tables there and they differ.
AREA = "national_park"
# A real key item in one title's pack and a placeholder (unnamed) in the other's.
ITEM = 70


@pytest.fixture
def cutover(monkeypatch):
    """The G3 cutover's row flip, test-local: every Gen 2 spelling -> gen2_gsc."""
    for rom_type in GEN2:
        monkeypatch.setitem(adapters._ROM_TYPE_TO_GAME_ID, rom_type, "gen2_gsc")


def _cart(rom_type):
    return {"rom_type": rom_type, "artifact_kind": "clean"}


def _pack(title, name):
    return json.loads((DATA / f"gen2_{title}" / f"{name}.json").read_text("utf-8"))


def _grass_species(title, area):
    """Species this title's own grass rows can produce on `area` -- straight from the pack."""
    pack = _pack(title, "encounter_tables")
    keys = {int(key) for key, value in pack["map_areas"].items() if value == area}
    return {slot["species"] for row in pack["wild"]["grass"]
            if row["map_group"] * 256 + row["map_number"] in keys
            for slot in row["slots"]}


def _table_species(adapter, area):
    """Species ids the adapter's own presentation table for `area` can produce."""
    return {row["species_id"] for rows in (adapter.encounter_table(area) or {}).values()
            for row in rows}


def _pack_item_name(title, item_id):
    """This title's own name for an item, in the display form the adapter prints."""
    row = _pack(title, "items")["items"][str(item_id)]
    return "" if row["placeholder"] else row["name"].title().replace("'D", "'d")


def _assert_answers_from_its_own_pack(adapter, title, other_title):
    """This adapter carries ITS title's exclusive rows, and none of the other title's."""
    mine = _grass_species(title, AREA) - _grass_species(other_title, AREA)
    theirs = _grass_species(other_title, AREA) - _grass_species(title, AREA)
    assert mine and theirs, "the packs do not differ on this area -- nothing is proven"
    table = _table_species(adapter, AREA)
    assert mine <= table, f"{title}'s own rows are missing from the {title} adapter"
    assert not theirs & table, f"{other_title}'s rows leaked into the {title} adapter"
    assert adapter.item_name(ITEM) == _pack_item_name(title, ITEM)


# ── the declaration itself ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rom_type,title", TITLE.items())
def test_the_declaration_answers_the_bound_title_and_nothing_else(rom_type, title):
    adapter = get_adapter("gen2_gsc", is_rr=False, rom_type=rom_type)
    assert adapter.per_player_bound_key() == title
    assert adapter.per_player_key(rom_type) == title
    # A spelling this pack does not own binds nothing -- `crystal_ap` is O-8's case.
    for other in ("crystal_ap", "Crystal (AP)", "red", "firered_rr", "", "CRYSTAL"):
        assert adapter.per_player_key(other) is None, other


# ── (a) Crystal first, Gold second ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_crystal_then_gold_gives_gold_its_own_pack(tmp_path, cutover):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", _cart("Crystal"))))
        run = srv.state.adapter
        assert run.title == "crystal"
        assert not _refused(await send(_hello("b", _cart("Gold"))))

        # A second title is a second PACK, not a second run: the run's identity is untouched.
        assert srv.state.adapter is run and srv.state.rom_type == "Crystal"
        # The player on the committed title keeps the run adapter; the other gets its own.
        assert srv.adapter_for("a") is run
        gold = srv.adapter_for("b")
        assert gold is not run and gold.title == "gold"

        # And each answers from its own pack, not from whichever said hello first.
        _assert_answers_from_its_own_pack(run, "crystal", "gold")
        _assert_answers_from_its_own_pack(gold, "gold", "crystal")
        assert run.item_name(ITEM) != gold.item_name(ITEM)
    finally:
        await close()


# ── (b) the symmetric arrival order ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gold_then_crystal_is_symmetric(tmp_path, cutover):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", _cart("Gold"))))
        run = srv.state.adapter
        assert run.title == "gold"
        assert not _refused(await send(_hello("b", _cart("Crystal"))))

        assert srv.state.adapter is run and srv.state.rom_type == "Gold"
        assert srv.adapter_for("a") is run
        crystal = srv.adapter_for("b")
        assert crystal is not run and crystal.title == "crystal"

        _assert_answers_from_its_own_pack(run, "gold", "crystal")
        _assert_answers_from_its_own_pack(crystal, "crystal", "gold")
        assert run.item_name(ITEM) != crystal.item_name(ITEM)
    finally:
        await close()


# ── (c) one title, either spelling: no per-player adapter ────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("first,second", [("Crystal", "Crystal"), ("Crystal", "crystal"),
                                          ("gold", "Gold"), ("Silver", "silver")])
async def test_one_title_binds_no_per_player_adapter(tmp_path, cutover, first, second):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", _cart(first))))
        run = srv.state.adapter
        assert not _refused(await send(_hello("b", _cart(second))))
        # The key is the TITLE, not the spelling: two spellings of one title share one pack.
        assert srv._player_adapters == {}
        assert srv.adapter_for("a") is run and srv.adapter_for("b") is run
    finally:
        await close()


# ── (d) reconnect re-declares; a match drops the binding ─────────────────────────────────

@pytest.mark.asyncio
async def test_a_reconnect_re_declares_and_a_match_drops_the_binding(tmp_path, cutover):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", _cart("Crystal"))))
        run = srv.state.adapter
        assert not _refused(await send(_hello("b", _cart("gold"))))
        assert srv.adapter_for("b").title == "gold"

        # A reconnect is a new connection re-declaring the same cartridge: the binding holds.
        reconnect, close_reconnect = await _session(srv)
        try:
            assert not _refused(await reconnect(_hello("b", _cart("gold"))))
            assert srv.adapter_for("b") is not run and srv.adapter_for("b").title == "gold"
            # Back on the run's own title -> the per-player adapter is dropped, not kept.
            assert not _refused(await reconnect(_hello("b", _cart("crystal"))))
            assert "b" not in srv._player_adapters
            assert srv.adapter_for("b") is run
            # ...and the drop is not a latch: the other title re-binds it.
            assert not _refused(await reconnect(_hello("b", _cart("Gold"))))
            assert srv.adapter_for("b").title == "gold"
            assert srv.state.adapter is run and srv.state.rom_type == "Crystal"
        finally:
            await close_reconnect()
    finally:
        await close()


# ── (e) a generation whose adapter declares no key ───────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("first,second", [("red", "blue"), ("firered", "leafgreen")])
async def test_another_generation_binds_no_per_player_adapter(tmp_path, first, second):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", _cart(first))))
        run = srv.state.adapter
        assert not _refused(await send(_hello("b", _cart(second))))
        assert srv.state.adapter is run
        assert srv._player_adapters == {}
        assert srv.adapter_for("a") is run and srv.adapter_for("b") is run
    finally:
        await close()


# ── the persisted run: ONE stored rom_type, players re-declare theirs ────────────────────

@pytest.mark.asyncio
async def test_a_restart_keeps_the_run_title_and_re_binds_the_other_title(tmp_path, cutover):
    """The persisted run stores one rom_type, so the binding is re-derived from hellos.

    This is why state.py needed no change: `_player_adapters` is live-only state, and the
    U4 binder already restores the RUN's title from the persisted rom_type.
    """
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        assert not _refused(await send(_hello("a", _cart("Crystal"))))
        assert not _refused(await send(_hello("b", _cart("Gold"))))
        assert srv.adapter_for("b").title == "gold"
    finally:
        await close()
    srv.state._save()

    reloaded = SLinkServer(data_dir=str(tmp_path))
    assert reloaded.state.rom_type == "Crystal"
    assert reloaded.state.adapter.title == "crystal"
    assert reloaded._player_adapters == {}, "a reload starts with no per-player adapter"

    send, close = await _session(reloaded)
    try:
        assert not _refused(await send(_hello("b", _cart("Gold"))))
        assert reloaded.state.adapter.title == "crystal", "the run's title is untouched"
        assert reloaded.adapter_for("b").title == "gold", "re-derived from the hello"
        assert not _refused(await send(_hello("a", _cart("Crystal"))))
        assert reloaded.adapter_for("a") is reloaded.state.adapter
    finally:
        await close()
