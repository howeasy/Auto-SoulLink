"""RC qualifying checks: per-title trainer panel / Upcoming Key Trainers / Prep deep link
(owner ruling 28 -- trainer names, Upcoming Key Trainers and the calc Prep tab are MANDATORY on
FR, LG, RR and Emerald, not RR-only extras).

Drives server.SLinkServer._trainer_panel_html the same way the dashboard does, for each of the
four titles, and asserts:
  - the title-specific trainer name renders for a known area (the same server code path the
    coordinator's mock browser check exercises);
  - the rival is filtered by player gender where the game has one (Emerald only -- FR/LG and RR
    are gender-independent, per test_gen3_emerald_rival.py's test_gender_does_not_change_frlg_or_rr_panels);
  - a Prep deep link is present: dashboard.js's tr-calc-btn handler builds the calc's `?prep=`
    URL straight from the rendered `data-calc-label` attribute (server/static/dashboard.js:334-347),
    so a present, correct data-calc-label IS the deep link payload at the server layer.

Also regression-covers the Mauville Gym area fix (tools/gen_area_map.py E5-CITYLINK,
tests/unit/test_gen3_trainers_emerald.py::test_wattson_is_filed_under_mauville_city_not_route_110):
Wattson must render under "mauville_city", not "route_110".
"""
from server.adapters.gen3_frlge import Gen3Adapter
from server.server import SLinkServer


def _panel_server(rom_type, is_rr=False, player_gender=None):
    server = SLinkServer.__new__(SLinkServer)
    server.adapter = Gen3Adapter(rom_type=rom_type, is_rr=is_rr)
    server._player_adapters = {}
    server.player_gender = player_gender or {}
    return server


# ── frlg (FireRed side) ──────────────────────────────────────────────────────────────────────

def test_frlg_pewter_city_shows_brock_with_prep_deep_link():
    srv = _panel_server("firered")
    html = srv._trainer_panel_html("pewter_city", "a")
    assert "Upcoming Key Trainers" in html
    assert "Brock" in html and 'data-calc-label="Leader Brock"' in html
    # FR/LG's rival is gender-independent (vanilla rival names) -- gender must not change the panel
    baseline = html
    for gender in (0, 1):
        srv.player_gender["a"] = gender
        assert srv._trainer_panel_html("pewter_city", "a") == baseline


# ── lgfr (LeafGreen side of the same vanilla pair) ───────────────────────────────────────────

def test_lgfr_pewter_city_shows_brock_with_prep_deep_link():
    srv = _panel_server("leafgreen")
    html = srv._trainer_panel_html("pewter_city", "a")
    assert "Brock" in html and 'data-calc-label="Leader Brock"' in html
    baseline = html
    for gender in (0, 1):
        srv.player_gender["a"] = gender
        assert srv._trainer_panel_html("pewter_city", "a") == baseline


# ── rr (Radical Red) ─────────────────────────────────────────────────────────────────────────

def test_rr_pewter_city_shows_falkner_with_prep_deep_link():
    srv = _panel_server("firered_rr", is_rr=True)
    html = srv._trainer_panel_html("pewter_city", "a")
    assert "Falkner" in html and 'data-calc-label="Leader Falkner"' in html
    # RR's rival preview is also gender-independent (test_gen3_emerald_rival.py)
    baseline = html
    for gender in (0, 1):
        srv.player_gender["a"] = gender
        assert srv._trainer_panel_html("pewter_city", "a") == baseline


# ── emerald ───────────────────────────────────────────────────────────────────────────────────

def test_emerald_route_103_rival_filtered_by_gender_with_prep_deep_link():
    srv = _panel_server("emerald", player_gender={"a": 0, "b": 1})
    a = srv._trainer_panel_html("route_103", "a")
    b = srv._trainer_panel_html("route_103", "b")
    assert "May" in a and "Brendan" not in a
    assert "Brendan" in b and "May" not in b
    assert 'data-calc-label="' in a and 'data-calc-label="' in b


def test_emerald_mauville_city_shows_wattson_not_route_110():
    """Regression for the RC defect: Mauville City has no trainers of its own outside Wattson's
    gym (owner ruling), so the gym's trainers must render under mauville_city, and route_110's
    Upcoming Key Trainers list must not contain Wattson at all."""
    srv = _panel_server("emerald")
    mauville = srv._trainer_panel_html("mauville_city", "a")
    assert "Wattson" in mauville and 'data-calc-label="Leader Wattson"' in mauville
    route_110 = srv._trainer_panel_html("route_110", "a")
    assert "Wattson" not in route_110
