"""Client-sent battle payloads reach the page: nothing a client sends is trusted as HTML,
and odd shapes (null, a scalar where a list belongs) render instead of raising."""
from __future__ import annotations

import json
from pathlib import Path

import jinja2
import pytest

from server.server import SLinkServer

XSS = "<img src=x onerror=alert(1)>"
TEMPLATES = Path(__file__).resolve().parents[2] / "server" / "templates"


def _status(tmp_path, enemy_party):
    srv = SLinkServer(data_dir=str(tmp_path))
    srv.battle_state["a"] = {"in_battle": False, "enemy_party": enemy_party}
    return srv._build_status_dict()


def test_a_client_sent_sprite_html_never_reaches_the_page(tmp_path):
    st = _status(tmp_path, [{"species_id": 25, "sprite_html": XSS},
                            {"species_id": 0, "sprite_html": XSS}])
    assert "onerror=alert" not in json.dumps(st)
    foes = st["players"]["a"]["battle_state"]["enemy_party"]
    assert "sprite_html" not in foes[1], "no species, no sprite: the client's value is dropped"


def test_a_null_enemy_party_is_an_empty_one(tmp_path):
    assert _status(tmp_path, None)["players"]["a"]["battle_state"]["enemy_party"] == []


@pytest.mark.parametrize("stages", [7, {}, {"atk": 1}, "6666666", None])
def test_stat_stages_row_ignores_a_non_list(stages):
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(TEMPLATES), autoescape=True)
    assert str(env.get_template("_macros.html").module.stat_stages_row(stages)).strip() == ""


def test_stat_stages_row_still_draws_a_list():
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(TEMPLATES), autoescape=True)
    assert "ATK" in str(env.get_template("_macros.html").module.stat_stages_row([8, 6, 6, 6, 6, 6, 6]))


@pytest.mark.parametrize("party", [[5, "x", None], {"0": {}}, 7])
def test_an_enemy_party_that_is_not_a_list_of_objects_is_dropped(tmp_path, party):
    srv = SLinkServer(data_dir=str(tmp_path))
    srv._dispatch("a", {"event": "tick", "in_battle": True, "enemy_party": party})
    assert srv.battle_state["a"]["enemy_party"] == []
    srv._build_status_dict()
