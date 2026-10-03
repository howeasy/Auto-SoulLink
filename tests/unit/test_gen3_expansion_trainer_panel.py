"""EXP-TOWNS: the expansion build's trainer panel / Upcoming Key Trainers / Prep deep link
(trainer panels are RC-mandatory, owner ruling 28) for the gym towns.

Drives server.SLinkServer._trainer_panel_html with Gen3ExpansionAdapter, the way
test_gen3_rc_trainer_panel_titles.py does for the four vanilla titles. dashboard.js's
tr-calc-btn handler builds the calc ?prep= URL from the rendered data-calc-label
(server/static/dashboard.js:334-347), so a present data-calc-label is the deep-link payload.

Before the area_map.json town backfill (tools/gen_area_map.py _EMERALD_WILD_LESS_TOWNS now also
applies to the expansion) Roxanne / Wattson / Winona were filed under route_104 / route_110 /
route_119 and these three panels were empty.
"""
import pytest

from server.adapters.gen3_expansion import Gen3ExpansionAdapter
from server.server import SLinkServer


def _panel_server(player_gender=None):
    server = SLinkServer.__new__(SLinkServer)
    server.adapter = Gen3ExpansionAdapter()
    server._player_adapters = {}
    server.player_gender = player_gender or {}
    return server


@pytest.mark.parametrize("area,leader,elsewhere", [
    ("rustboro_city", "Roxanne", "route_104"),
    ("mauville_city", "Wattson", "route_110"),
    ("fortree_city", "Winona", "route_119"),
])
def test_gym_town_panel_shows_leader_with_prep_deep_link(area, leader, elsewhere):
    srv = _panel_server()
    html = srv._trainer_panel_html(area, "a")
    assert "Upcoming Key Trainers" in html
    assert leader in html and f'data-calc-label="Leader {leader}"' in html
    # and the leader has left the neighbouring route's list
    assert leader not in srv._trainer_panel_html(elsewhere, "a")


def test_petalburg_city_shows_norman_and_his_four_rematches():
    # Petalburg has its own wild header, so it was never affected; pinned as the control.
    html = _panel_server()._trainer_panel_html("petalburg_city", "a")
    assert "Norman" in html and 'data-calc-label="Leader Norman"' in html
    for n in range(1, 5):
        assert f"Rematch {n}" in html


# The rival: Gen3ExpansionAdapter.trainer_brief() copies Gen3Adapter._frlg_trainer_brief's rule
# (gen3_frlge.py:810-818) for TRAINER_MAY_* (0) / TRAINER_BRENDAN_* (1); expansion
# data/maps/Route103/scripts.inc:23-24 sends MALE (0) to May and FEMALE (1) to Brendan.
def test_rival_is_filtered_by_player_gender_on_the_expansion():
    # Emerald's May/Brendan rival: only the opposite-gender sibling is shown (route_103 is the
    # rival's first fight; the Rustboro rival fights stay on route_104 by the alphabetical-first
    # area tie-break, tests/unit/test_gen3_emerald_towns.py).
    srv = _panel_server(player_gender={"a": 0, "b": 1})
    for area in ("route_103", "route_104"):
        a, b = srv._trainer_panel_html(area, "a"), srv._trainer_panel_html(area, "b")
        assert "May" in a and "Brendan" not in a, area
        assert "Brendan" in b and "May" not in b, area
        assert 'data-calc-label="' in a and 'data-calc-label="' in b
