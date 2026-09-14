"""The Manager's pages: the rail, the New-run form, and a run's board on the Manager's
own origin -- live from the run's server, or persisted for a stopped one."""
from __future__ import annotations

import json

import pytest

from server import manager
from server.server import SLinkServer
from server.state import AreaStatus, LinkEntry, LinkStatus, MonInfo

pytest_plugins = ["tests.unit.manager_harness"]


def _stopped_run(run_root, run_id="run_1", name="Kanto Duo", game="gen1"):
    run = {"run_id": run_id, "name": name, "created_at": "2026-09-14T12:00:00", "tcp_port": 54321,
           "http_port": 8081, "status": "stopped", "pid": None, "game": game}
    manager._save_registry([run])
    run_dir = run_root / run_id
    run_dir.mkdir()
    # What the run persisted while it was alive: one linked pair, written by its own state.
    srv = SLinkServer(data_dir=str(run_dir))
    st = srv.state
    e = LinkEntry(area_id="route_1",
                  a=MonInfo(key="AABB:30B8:99", level=6, species=25, nickname="SPARKY"),
                  b=MonInfo(key="CCDD:7B0B:B0", level=6, species=4, nickname="EMBO"),
                  status=LinkStatus.ALIVE)
    st.links.append(e)
    st._index_entry(e)
    st.area_states["route_1"] = AreaStatus.LINKED
    st._save()
    return run


@pytest.mark.asyncio
async def test_no_runs_lands_on_the_new_run_form(manager_client):
    resp = await manager_client.get("/")
    assert resp.status == 200
    body = await resp.text()
    assert "window.SLINK_FORM" in body and "Create run" in body
    start = body.index("window.SLINK_FORM = ") + len("window.SLINK_FORM = ")
    form = json.loads(body[start:body.index(";", start)])
    assert "Red · Blue · Yellow" in [g["label"] for g in form["games"]], "the game families are the form's first question"


@pytest.mark.asyncio
async def test_the_form_carries_the_option_table_the_server_computed(manager_client):
    body = await (await manager_client.get("/new")).text()
    start = body.index("window.SLINK_FORM = ") + len("window.SLINK_FORM = ")
    form = json.loads(body[start:body.index(";", start)])
    assert form["support"]["gen1"]["gender_lock"]["ok"] is False
    assert form["support"][""]["battle_calc"]["ok"] is True
    assert "gen1" in form["gen1_games"] and "gen3_rr" not in form["gen1_games"]


@pytest.mark.asyncio
async def test_a_stopped_run_renders_its_persisted_board(manager_client, manager_dir):
    """The Manager has no live server to ask, so it rebuilds the payload from the run's
    own files -- the board is the board it had, with nobody connected."""
    run = _stopped_run(manager_dir)
    resp = await manager_client.get(f"/runs/{run['run_id']}")
    assert resp.status == 200
    body = await resp.text()
    assert "SPARKY" in body and "EMBO" in body
    assert "zone-linked" in body, "nothing is located on a stopped run, so the pair is Linked"
    assert "run not running" in body and "waiting for hello" not in body
    assert 'hx-get="/runs/run_1/board"' in body, "the fragment must poll the Manager, not /"
    assert "Kanto Duo" in body and "Red · Blue · Yellow" in body


@pytest.mark.asyncio
async def test_the_board_fragment_stands_alone(manager_client, manager_dir):
    run = _stopped_run(manager_dir)
    resp = await manager_client.get(f"/runs/{run['run_id']}/board")
    assert resp.status == 200
    body = await resp.text()
    assert body.lstrip().startswith("<div id=\"content\"")
    assert "SPARKY" in body


@pytest.mark.asyncio
async def test_unknown_run_is_a_404_not_a_500(manager_client):
    assert (await manager_client.get("/runs/nope")).status == 404
    assert (await manager_client.get("/runs/nope/board")).status == 404


@pytest.mark.asyncio
async def test_new_run_records_the_game_family(manager_client, monkeypatch):
    async def no_spawn(*a, **k):
        raise RuntimeError("no server in tests")
    monkeypatch.setattr(manager, "_spawn_run", no_spawn)
    resp = await manager_client.post("/api/runs/new", json={"name": "Duo", "game": "gen1", "species_lock": True})
    j = await resp.json()
    assert j["ok"] and j["run"]["game"] == "gen1"
    resp = await manager_client.post("/api/runs/new", json={"name": "Duo 2", "game": "not-a-family"})
    assert (await resp.json())["run"]["game"] == "", "an unknown family is detect-on-connect, not stored"


@pytest.mark.asyncio
async def test_the_events_ping_stream_is_gone(manager_client):
    """It contacted no run and emitted an unconditional ping every 1.5 s; nothing read it."""
    assert (await manager_client.get("/api/events")).status == 404
