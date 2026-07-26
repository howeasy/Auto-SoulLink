"""The `link_panel` payload that feeds the native in-game SOULLINK screen.

The screen is proven by `lua/tests/test_live_infoscreen.lua` and the whole chain by the
`infopanel` duo scenario; these tests cover the half that decides WHAT it says.

Rows are flat `field|field|...` strings because the Lua client has no JSON decoder — its
`parse_command_list` is a pattern scraper, so a nested payload never reaches it. That is not a
detail worth hiding behind a mock: the field order and the empty-label convention ARE the contract
with the ROM patch, so they are asserted literally.
"""
import pytest

from server.adapters.gen3_frlge import Gen3Adapter
from server.server import SLinkServer, _area_tag
from server.state import AreaStatus, LinkEntry, LinkStatus, MonInfo


def _mon(key, species=1, level=5, nickname=""):
    return MonInfo(key=key, level=level, species=species, nickname=nickname)


@pytest.fixture
def srv(tmp_path):
    s = SLinkServer(data_dir=str(tmp_path))
    s.state.adapter = s.adapter = Gen3Adapter(is_rr=True)
    s.state.links = [
        LinkEntry(area_id="route_3", a=_mon("aaa", species=1, level=12),
                  b=_mon("bbb", species=7, level=11), status=LinkStatus.ALIVE),
    ]
    s.party_details["a"] = {"aaa": {"level": 12, "hp": 19, "maxHP": 23, "nickname": "Bulba"}}
    s.party_details["b"] = {"bbb": {"level": 11, "hp": 21, "maxHP": 21, "nickname": "Squirt"}}
    return s


def rows(srv, pid):
    return srv._build_link_panel(pid)["rows"]


def test_pair_halves_swap_per_recipient(srv):
    """The same pair must read as MINE/THEIRS from each side — the point of the whole screen.

    Getting this backwards would show a player their partner's run as if it were their own, and
    no amount of visual polish would reveal it.
    """
    assert rows(srv, "a")[0].split("|")[1] == "Bulba"
    assert rows(srv, "a")[1].split("|")[1] == "Squirt"
    assert rows(srv, "b")[0].split("|")[1] == "Squirt"
    assert rows(srv, "b")[1].split("|")[1] == "Bulba"


def test_second_row_of_a_pair_has_an_empty_label(srv):
    """The empty label IS the pair-grouping signal: it makes the slot start with the field
    separator, which is what the patch keys the tie bracket off."""
    r = rows(srv, "a")
    assert r[0].split("|")[0] != ""      # first row carries the area tag
    assert r[1].split("|")[0] == ""      # second continues the pair


def test_live_hp_and_bar_come_from_the_party_snapshot(srv):
    """LinkEntry stores identity; current HP only exists in party_details."""
    label, name, level, hp, bar, state, status = rows(srv, "a")[0].split("|")
    assert (level, hp, state, status) == ("12", "19/23", "", "")
    # 19/23 of a 38px track ~= 31px, and it must never round to 0 for a living mon.
    assert 1 <= int(bar) <= 38


def test_a_fainted_mon_reports_no_bar_so_the_row_goes_red(srv):
    srv.party_details["b"]["bbb"]["hp"] = 0
    _, _, _, hp, bar, state, _ = rows(srv, "a")[1].split("|")
    assert (hp, bar, state) == ("FNT", "0", "")


def test_a_boxed_mon_is_not_reported_as_dead(srv):
    """A boxed mon is alive but has no live HP. Marking it 'B' keeps it out of the red 'dead'
    styling — telling a player their mon died when it is sitting in a box is the one mistake
    this screen must never make."""
    srv.party_details["b"] = {}
    _, _, _, hp, bar, state, _ = rows(srv, "a")[1].split("|")
    assert (hp, state) == ("BOX", "B")


def test_a_living_mon_never_rounds_down_to_an_empty_bar(srv):
    """1 HP of 200 is 0.19px. Rounding to 0 would render it as dead."""
    srv.party_details["a"]["aaa"].update(hp=1, maxHP=200)
    assert int(rows(srv, "a")[0].split("|")[4]) >= 1


def test_half_formed_pairs_are_omitted(srv):
    """One side having caught is not a pair yet."""
    srv.state.links.append(
        LinkEntry(area_id="route_4", a=_mon("ccc"), b=None, status=LinkStatus.ALIVE))
    assert len([r for r in rows(srv, "a") if r.count("|") == 6]) == 2   # still just the one pair


def test_summary_rows_report_the_run(srv):
    srv.state.area_states["route_9"] = AreaStatus.DEAD_ZONE
    srv.state.player_badges["a"] = 5
    stats = dict(r.split("|") for r in rows(srv, "a") if r.count("|") == 1)
    assert stats == {"Pairs alive": "1/1", "Dead zones": "1", "Badges": "5/8"}


def test_dead_zones_are_named_not_just_counted(srv):
    """A count tells the player a number; the names tell them where they can no longer catch,
    which is the part they can act on."""
    srv.state.area_states["route_9"] = AreaStatus.DEAD_ZONE
    srv.state.area_states["mt_moon"] = AreaStatus.DEAD_ZONE
    named = [r for r in rows(srv, "a") if r.startswith("- ")]
    assert len(named) == 2
    assert any("Moon" in r for r in named)


def test_status_condition_is_reported(srv):
    """A poisoned linked mon is exactly what a player opens this screen to find out, and it is
    invisible from the HP bar alone."""
    srv.party_details["a"]["aaa"]["status_cond"] = 0x08          # poisoned
    assert rows(srv, "a")[0].split("|")[6] == "PSN"
    srv.party_details["a"]["aaa"]["status_cond"] = 0x40          # paralysed
    assert rows(srv, "a")[0].split("|")[6] == "PAR"


def test_toxic_is_reported_as_tox_not_psn(srv):
    """Toxic sets the poison bit too, so order matters."""
    srv.party_details["a"]["aaa"]["status_cond"] = 0x88
    assert rows(srv, "a")[0].split("|")[6] == "TOX"


def test_status_decoding_is_adapter_owned(srv):
    """The bitfield is per-generation, so shared code must not decode it. A game that has not
    implemented it shows no status rather than a wrong one."""
    from server.adapters.base import GameRulesAdapter
    assert GameRulesAdapter.status_token(object(), 0x40) == ""
    assert Gen3Adapter(is_rr=True).status_token(0x40) == "PAR"


def test_dead_pair_is_not_counted_alive(srv):
    srv.state.links[0].status = LinkStatus.DEAD
    stats = dict(r.split("|") for r in rows(srv, "a") if r.count("|") == 1)
    assert stats["Pairs alive"] == "0/1"


def test_empty_run_says_so_rather_than_rendering_nothing(srv):
    srv.state.links = []
    assert rows(srv, "a")[0] == "No linked pairs yet"


@pytest.mark.parametrize("name,tag", [
    ("Route 3", "RT03"), ("route 12", "RT12"), ("Viridian Forest", "VIRI"),
    ("Mt. Moon", "MTMO"), ("", ""),
])
def test_area_tag_fits_the_four_character_column(name, tag):
    """A blind truncation would give "Rout" for every route; the number is the informative part."""
    assert _area_tag(name) == tag


def test_adapter_gates_the_panel():
    """A client that cannot render it must never be sent it — the command would land in its
    unknown-command branch and log a warning on every change."""
    from server.adapters.base import GameRulesAdapter
    assert GameRulesAdapter.supports_info_panel(object()) is False
    assert Gen3Adapter(is_rr=True).supports_info_panel() is True
    assert Gen3Adapter(is_rr=False).supports_info_panel() is False
