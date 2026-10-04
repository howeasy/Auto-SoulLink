"""The run's story (/timeline, /runs/{id}/timeline): server.board.timeline over the status
payload, rendered on the run server from the full mock cast and on the Manager from what
a stopped run persisted."""
from __future__ import annotations

import re

import pytest

from server import board
from tests.unit.test_dashboard_contract import parse

pytest_plugins = ["tests.unit.populated_server", "tests.unit.manager_harness"]


def _link(area, a="AA", b="BB", status="alive", **kw):
    return {"area_id": area, "area_display": area.title(), "status": status,
            "a_key": a, "a_nickname": f"{a}mon", "a_species_name": "Pidgey", "a_level": 5,
            "b_key": b, "b_nickname": f"{b}mon", "b_species_name": "Rattata", "b_level": 5, **kw}


def test_story_is_chronological_and_says_when_a_time_was_never_recorded():
    status = {
        "links": [_link("route1", status="memorial"), _link("route2", "CC", "DD"),
                  {"area_id": "route3", "area_display": "Route 3", "status": "dead"}],
        "killfeed": [
            {"area_id": "route1", "killed_at": "2026-10-01T10:00:00+00:00", "cause": "battle",
             "killer": {"trainer_name": "Brock"}, "initiating_player": "a",
             **{k: v for k, v in _link("route1").items() if k[1:2] == "_"}},
            {"area_id": "route3", "killed_at": "2026-10-01T09:00:00+00:00", "cause": "dead_zone",
             "a_enc_species_name": "Spearow", "a_enc_level": 4},
        ],
        # route2's link is in the log; route1's fell out of it (the log keeps 200)
        "recent_events": [{"type": "linked", "area_id": "route2", "ts": "2026-10-01T11:00:00"}],
        "area_states": {"route1": "linked", "route2": "linked", "route3": "dead_zone",
                        "route4": "pending_a"},
        "pending_captures": {"route4": {"a": {"nickname": "Zippy"}}},
    }
    story = board.timeline(status)
    kinds = [(e["kind"], e["area"]) for e in story["entries"]]
    assert kinds == [("linked", "Route1"), ("dead_zone", "Route 3"), ("death", "Route1"),
                     ("memorial", "Route1"), ("linked", "Route2")]
    first, dz, death, memorial, _ = story["entries"]
    assert first["ts"] is None and first["when"] == "" and memorial["ts"] is None
    assert story["untimed"] == 2
    assert death["cause"] == "fainted in battle" and death["killer"] == "Brock" and death["by"] == "A"
    assert dz["met"] == {"a": ("Spearow", 4)} and dz["a"] is None
    assert story["open_areas"] == [{"area": "Route 4", "caught": {"a": "Zippy"}}]


@pytest.mark.asyncio
async def test_run_server_timeline_renders_the_mock_cast(populated):
    srv, client = populated
    resp = await client.get("/timeline")
    assert resp.status == 200
    html = await resp.text()
    root = parse(html)
    rows = [li for li in root.find_all("li") if "tl-ev" in (li.get("class") or "")]
    kinds = [li.get("class").split()[1] for li in rows]
    status = srv._build_status_dict()
    formed = [lk for lk in status["links"] if lk.get("a_key") and lk.get("b_key")]
    assert kinds.count("linked") == len(formed)
    assert kinds.count("dead_zone") == sum(1 for k in status["killfeed"] if k["cause"] == "dead_zone")
    assert "death" in kinds or "dead_zone" in kinds
    # the timed entries read oldest first
    times = re.findall(r'<time datetime="([^"]+)"', html)
    assert times == sorted(times)
    # the rail links the page and marks it current; the run header has it as a tab
    current = re.findall(r'<a [^>]*aria-current="page"[^>]*>', html)
    assert any('href="/timeline"' in a for a in current)
    assert "Still open" in html


@pytest.mark.asyncio
async def test_board_and_rail_link_the_timeline(populated):
    _, client = populated
    html = await (await client.get("/")).text()
    assert html.count('href="/timeline"') >= 2      # rail + run header tab


@pytest.mark.asyncio
async def test_manager_timeline_of_a_stopped_run(manager_client, manager_dir):
    from tests.unit.test_manager_pages import _stopped_run
    _stopped_run(manager_dir)
    resp = await manager_client.get("/runs/run_1/timeline")
    assert resp.status == 200
    body = await resp.text()
    assert "mk-rail" in body and "Kanto Duo" in body
    assert 'href="/runs/run_1/timeline" aria-current="page"' in body
    assert "Pair formed on" in body and "SPARKY" in body and "EMBO" in body
    assert "time not recorded" in body          # the persisted link carries no time
