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


# ── the randomizer page and its endpoints ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_randomizer_page_is_a_gen1_run_page(manager_client, manager_dir):
    run = _stopped_run(manager_dir)
    resp = await manager_client.get(f"/runs/{run['run_id']}/randomizer")
    assert resp.status == 200
    body = await resp.text()
    start = body.index("window.SLINK_RANDOMIZER = ") + len("window.SLINK_RANDOMIZER = ")
    form = json.loads(body[start:body.index(";</script>", start)])   # labels carry ';'
    keys = [o["key"] for o in form["options"]]
    assert {"wild", "starters", "statics", "trainers", "tms", "field_items", "trainers_levels"} <= set(keys)
    assert form["current"] is None
    assert "/static/randomizer.js" in body and "randomizerPage(" in body


@pytest.mark.asyncio
async def test_the_randomizer_page_refuses_a_non_gen1_run(manager_client, manager_dir):
    run = _stopped_run(manager_dir, game="gen3_rr")
    assert (await manager_client.get(f"/runs/{run['run_id']}/randomizer")).status == 404


@pytest.mark.asyncio
async def test_preflight_names_what_is_missing_without_spending_anything(manager_client, tmp_path):
    resp = await manager_client.get("/api/randomizer/status", params={"jar": str(tmp_path / "nope.jar"),
                                                                     "rom_a": str(tmp_path / "a.gb"), "rom_b": ""})
    j = await resp.json()
    assert j["ok"] is False and j["jar_found"] is False
    assert j["roms"]["a"]["exists"] is False and j["roms"]["b"]["exists"] is False


@pytest.mark.asyncio
async def test_browse_lists_only_inside_the_roots(manager_client, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / "roms").mkdir()
    (tmp_path / "roms" / "red.gb").write_bytes(b"x")
    (tmp_path / "roms" / "notes.txt").write_bytes(b"x")
    j = await (await manager_client.get("/api/browse", params={"dir": str(tmp_path / "roms"), "ext": ".gb,.gbc"})).json()
    assert j["ok"] and [e["name"] for e in j["entries"]] == ["red.gb"], "only the asked-for extensions, plus directories"
    outside = await manager_client.get("/api/browse", params={"dir": str(tmp_path.parent.parent)})
    assert outside.status == 403


@pytest.mark.asyncio
async def test_rom_download_is_404_until_a_pair_exists(manager_client, manager_dir):
    run = _stopped_run(manager_dir)
    assert (await manager_client.get(f"/api/runs/{run['run_id']}/rom/a")).status == 404
    assert (await manager_client.get(f"/api/runs/{run['run_id']}/rom/c")).status == 400


# ── the flag table ────────────────────────────────────────────────────────────────────

def test_run_flags_follow_one_table():
    """Four sites wrote the option list out by hand and drifted: an adopted orphan run
    dropped `verbose`, so it could never be started verbose. One table now."""
    from server.manager import RUN_FLAGS, run_flags, run_options
    defaults = run_options({})
    assert defaults["battle_calc"] is True and defaults["pc_trade_npc"] is True
    assert run_flags(defaults) == [], "defaults pass no flags"
    everything_on = run_options({k: True for k, _, _ in RUN_FLAGS})
    assert "--verbose" in run_flags(everything_on) and "--no-battle-calc" not in run_flags(everything_on)
    assert run_flags(run_options({"battle_calc": False})) == ["--no-battle-calc"]


# ── a run's secondary pages, in the Manager's chrome ────────────────────────────────────
@pytest.mark.asyncio
@pytest.mark.parametrize("path,panel", [("/runs/run_1/debug", "debug"), ("/runs/run_1/calc/normal.html", "calc")])
async def test_debug_and_calc_are_manager_pages(manager_client, manager_dir, path, panel):
    """Both wear the rail and the run header; a stopped run gets the empty state instead of
    a panel whose JS would fail against a dead server."""
    _stopped_run(manager_dir)
    resp = await manager_client.get(path)
    assert resp.status == 200
    body = await resp.text()
    assert "mk-rail" in body and "Kanto Duo" in body
    assert f"/runs/run_1/{'calc/normal.html' if panel == 'calc' else 'debug'}" in body
    assert "window.SLINK_API_BASE = \"/runs/run_1\"" in body
    assert "not running" in body


@pytest.mark.asyncio
async def test_the_calc_files_are_served_from_both_paths(manager_client, manager_dir):
    _stopped_run(manager_dir)
    for path in ("/calc/css/main.css", "/runs/run_1/calc/css/main.css"):
        resp = await manager_client.get(path)
        assert resp.status == 200 and "text/css" in resp.headers["Content-Type"], path
    assert (await manager_client.get("/calc/../server/manager.py")).status in (403, 404)


@pytest.mark.asyncio
async def test_the_per_run_relay_refuses_a_run_that_is_not_running(manager_client, manager_dir):
    _stopped_run(manager_dir)
    resp = await manager_client.get("/runs/run_1/api/status")
    assert resp.status == 404
    assert (await manager_client.get("/runs/nope/api/status")).status == 404
