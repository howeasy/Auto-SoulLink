"""Overlays, the memorial wall and the shared macros must say what is actually true.

Each test here pins one defect a validator confirmed at source: an overlay showing event types
the catalog says are off, a wild battle rendered as "TRAINER / Loading...", a dropped client's
last state passed off as live, a reset that swapped a Gen 1 run onto the Gen 3 adapter, dead
zones counted as fallen pairs, layouts advertised that do nothing, a dead list clipped with no
word of it, and status carried by colour alone.
"""
import asyncio
import time
from datetime import UTC, datetime, timedelta

import jinja2
import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from server.overlay_catalog import OVERLAYS
from server.server import SLinkServer, build_app
from server.state import LinkEntry, LinkStatus, MonInfo
from server.templating import TEMPLATES_DIR


@pytest.fixture
def srv(tmp_path):
    return SLinkServer(data_dir=str(tmp_path))


@pytest_asyncio.fixture
async def get(srv):
    c = TestClient(TestServer(build_app(srv)))
    await c.start_server()
    try:
        async def _get(path):
            r = await c.get(path, allow_redirects=False)
            assert r.status == 200, path
            return await r.text()
        yield _get
    finally:
        await c.close()


def _connect(srv, pid, connected=True):
    srv.connected_players[pid] = {"connected": connected, "rom_type": "firered",
                                  "last_event": "tick", "last_seen": "12:00:00",
                                  "last_seen_ts": time.time()}


# ── 1. event feed default filter ─────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("slug", ["events", "ticker"])
async def test_a_bare_event_feed_hides_the_default_off_types(srv, get, slug):
    srv._recent_events.appendleft({"type": "party_to_box", "player": "a", "text": "BOXED-MARKER"})
    srv._recent_events.appendleft({"type": "capture", "player": "a", "text": "CAUGHT-MARKER"})
    bare = await get(f"/stream/{slug}/fragment")
    assert "CAUGHT-MARKER" in bare
    assert "BOXED-MARKER" not in bare, "party_to_box is default-off in the catalog"
    everything = await get(f"/stream/{slug}/fragment?filter=all")
    assert "BOXED-MARKER" in everything and "CAUGHT-MARKER" in everything
    explicit = await get(f"/stream/{slug}/fragment?filter=party_to_box")
    assert "BOXED-MARKER" in explicit and "CAUGHT-MARKER" not in explicit


# ── 2. enemy trainer overlay during a wild battle ────────────────────────────

@pytest.mark.asyncio
async def test_the_enemy_trainer_overlay_is_blank_in_a_wild_battle(srv, get):
    _connect(srv, "a")
    srv.battle_state["a"] = {"in_battle": True, "is_trainer_battle": False, "is_doubles": False,
                             "enemy_party": [{"species_id": 16, "level": 3, "hp": 10, "maxHP": 10}]}
    html = await get("/stream/enemy-trainer-a/fragment")
    assert "TRAINER" not in html and "Loading" not in html


# ── 3. a dropped client is tagged, and its battle panels hidden ──────────────

def _seed_player_a(srv):
    srv.party_details["a"] = {"K1": {"species_id": 25, "nickname": "SPARKY", "level": 9,
                                     "hp": 20, "maxHP": 25, "slot": 0, "active": True}}
    srv.battle_state["a"] = {"in_battle": True, "is_trainer_battle": True, "is_doubles": False,
                             "opponent_class": "Youngster", "opponent_name": "JOEY",
                             "enemy_party": [{"species_id": 19, "level": 4, "hp": 12,
                                              "maxHP": 12, "active": True}]}


@pytest.mark.asyncio
async def test_a_disconnected_players_overlays_say_so(srv, get):
    _seed_player_a(srv)
    _connect(srv, "a", connected=False)
    party = await get("/stream/party-a/fragment")
    assert "SPARKY" in party, "the last state stays on screen"
    assert "DISCONNECTED" in party
    assert "DISCONNECTED" in await get("/stream/badges-a/fragment")
    for slug in ("enemy-focus-a", "enemy-trainer-a"):
        html = await get(f"/stream/{slug}/fragment")
        assert "JOEY" not in html and "Youngster" not in html, f"{slug} still shows the battle"
    focus = await get("/stream/focus-a/fragment")
    assert "SPARKY" not in focus and "DISCONNECTED" in focus


@pytest.mark.asyncio
async def test_a_connected_players_overlays_are_untagged(srv, get):
    """The control: the tag and the hiding must key on the connection, not fire always."""
    _seed_player_a(srv)
    _connect(srv, "a")
    assert "DISCONNECTED" not in await get("/stream/party-a/fragment")
    assert "JOEY" in await get("/stream/enemy-trainer-a/fragment")
    assert "SPARKY" in await get("/stream/focus-a/fragment")


# ── 4. /api/reset keeps the run's adapter ────────────────────────────────────

def test_a_reset_keeps_a_gen1_run_on_the_gen1_adapter(srv):
    from server.adapters import get_adapter
    # What the TCP reader leaves behind after both Gen 1 helloes (it, not _dispatch, owns
    # connected_players and the adapter switch).
    srv.state.adapter = srv.adapter = get_adapter("gen1_rby", rom_type="red")
    for pid, rom in (("a", "red"), ("b", "blue")):
        srv.connected_players[pid] = {"connected": True, "rom_type": rom}
    assert srv.adapter.game_id == "gen1_rby"
    sprite_before = srv._get_sprite_html(25)

    asyncio.run(srv.handle_reset_api(None))
    srv._dispatch("a", {"event": "tick", "party": []})

    assert srv.adapter.game_id == "gen1_rby"
    assert srv.state.adapter is srv.adapter
    assert srv.adapter_for("a").game_id == "gen1_rby"
    assert srv.connected_players["a"]["rom_type"] == "red", "the client will not re-hello"
    assert srv._get_sprite_html(25) == sprite_before


def test_a_reset_keeps_the_committed_rom_type(srv):
    """A blank rom_type after reset would disarm the Mixed-games check on the next hello."""
    srv.connected_players["a"] = {"connected": True, "rom_type": "red"}
    srv.state.rom_type, srv.state.artifact_kind = "red", "clean"
    asyncio.run(srv.handle_reset_api(None))
    assert srv.state.rom_type == "red"
    assert srv.state.artifact_kind == "clean"


# ── 5. the memorial wall ─────────────────────────────────────────────────────

def _ts(minutes):
    return (datetime(2026, 9, 1, tzinfo=UTC) + timedelta(minutes=minutes)).isoformat()


def _seed_deaths(srv):
    s = srv.state
    # oldest: a real fallen pair, buried
    s.links.append(LinkEntry(area_id="route_1", status=LinkStatus.MEMORIAL, killed_at=_ts(1),
                             cause="battle",
                             a=MonInfo(key="A1", species=16, level=5, nickname=""),
                             b=MonInfo(key="B1", species=19, level=5, nickname="RATTY")))
    # a dead zone where nobody caught anything: not a fallen pair
    s.links.append(LinkEntry(area_id="route_2", status=LinkStatus.DEAD, killed_at=_ts(2),
                             cause="dead_zone", a=None, b=None,
                             encounter_a=MonInfo(key="", species=10, level=3)))
    # one-sided dead zone: A missed a Caterpie, B's catch dies with it; not buried yet
    s.links.append(LinkEntry(area_id="route_22", status=LinkStatus.DEAD, killed_at=_ts(3),
                             cause="dead_zone", a=None,
                             encounter_a=MonInfo(key="", species=10, level=4),
                             b=MonInfo(key="B3", species=21, level=6, nickname="SPIKE")))


@pytest.mark.asyncio
async def test_the_memorial_wall_counts_only_fallen_pairs(srv, get):
    _seed_deaths(srv)
    html = await get("/memorial")
    assert "2 fallen pairs" in html
    num = '<div class="tomb-num">#'
    assert num + "3" not in html
    # numbering stays oldest first
    assert html.index(num + "1") < html.index("RATTY") < html.index(num + "2") < html.index("SPIKE")


@pytest.mark.asyncio
async def test_a_one_sided_dead_zone_shows_what_got_away(srv, get):
    _seed_deaths(srv)
    caterpie = srv.adapter.species_name(10)
    html = await get("/memorial")
    assert f"missed: {caterpie} Lv 4" in html
    assert "???" not in html, "an empty nickname falls back to the species name"
    assert html.count("burial pending") == 1, "only the DEAD row, not the MEMORIAL one"


def test_the_killfeed_itself_still_carries_every_death(srv):
    """Only the WALL drops empty dead zones; the board and other consumers keep them."""
    _seed_deaths(srv)
    assert len(srv._build_status_dict()["killfeed"]) == 3


# ── 6. catalog layouts ───────────────────────────────────────────────────────

@pytest.mark.parametrize("slug", ["links", "linked-party", "areas"])
def test_non_party_overlays_offer_no_layouts_that_do_nothing(slug):
    entry = next(o for o in OVERLAYS if o["slug"] == slug)
    assert entry["layouts"] == [""], "the layout CSS only restyles .p-list (party overlays)"


# ── 7. the links overlay's dead list ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_links_overlay_caps_the_dead_list_and_says_how_many_more(srv, get):
    for i in range(8):
        srv.state.links.append(LinkEntry(
            area_id=f"route_{i}", status=LinkStatus.DEAD, killed_at=_ts(i), cause="battle",
            a=MonInfo(key=f"A{i}", species=16, level=5, nickname=f"DEADA{i}"),
            b=MonInfo(key=f"B{i}", species=19, level=5, nickname=f"DEADB{i}")))
    html = await get("/stream/links/fragment")
    assert "8 DEAD" in html
    shown = [i for i in range(8) if f"DEADA{i}<" in html]
    assert shown == [3, 4, 5, 6, 7], "the newest five"
    assert "+3 more" in html


# ── 8. accessibility in the shared macros ────────────────────────────────────

def _render(src, **kw):
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    env.filters["bitand"] = lambda v, m: (int(v) & int(m)) if isinstance(v, int) else 0
    return env.from_string(src).render(**kw)


def test_hp_bar_is_a_labelled_progressbar():
    html = _render('{% from "_macros.html" import hp_bar %}{{ hp_bar(34, 100) }}')
    for attr in ('role="progressbar"', 'aria-label="HP"', 'aria-valuemin="0"',
                 'aria-valuemax="100"', 'aria-valuenow="34"', 'aria-valuetext="34 of 100 HP"'):
        assert attr in html, attr


def test_hp_bar_without_a_max_says_so():
    html = _render('{% from "_macros.html" import hp_bar %}{{ hp_bar(0, 0) }}')
    assert "HP unavailable" in html and "progressbar" not in html


@pytest.mark.parametrize("status,word", [("alive", "Alive"), ("dead", "Dead"), ("memorial", "Memorial")])
def test_link_row_status_is_not_colour_only(status, word):
    mon = {"nickname": "X", "species_name": "", "sprite_html": "", "level": 1}
    html = _render('{% from "_macros.html" import link_row %}{{ link_row(link) }}',
                   link={"a": mon, "b": mon, "status": status})
    assert f'<span class="sr-only">{word}</span>' in html


def test_a_reset_with_nobody_connected_frees_the_game(srv):
    """With no cartridge connected a reset is how a run switches games: nothing to keep."""
    srv.connected_players["a"] = {"connected": False, "rom_type": "red"}
    srv.state.rom_type, srv.state.artifact_kind = "red", "clean"
    asyncio.run(srv.handle_reset_api(None))
    assert srv.state.rom_type == ""
    assert srv.state.artifact_kind == ""
