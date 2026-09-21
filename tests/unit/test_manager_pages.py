"""The Manager's pages: the rail, the New-run form, and a run's board on the Manager's
own origin -- live from the run's server, or persisted for a stopped one."""
from __future__ import annotations

import json
import os

import aiohttp
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
async def test_roms_are_found_in_the_project_folder_with_a_verdict(manager_client, tmp_path, monkeypatch):
    """The run creator offers what is in the SLink folder (and roms/) rather than asking
    for paths; a file that is not a Gen 1 cartridge is listed, named, and not usable."""
    from server import manager
    (tmp_path / "roms").mkdir()
    (tmp_path / "roms" / "crystal.gbc").write_bytes(b"x" * (2 << 20))
    (tmp_path / "notes.txt").write_bytes(b"x")
    monkeypatch.setattr(manager, "ROM_DIRS", (str(tmp_path), str(tmp_path / "roms")))
    j = await (await manager_client.get("/api/roms")).json()
    assert [r["name"] for r in j["roms"]] == ["crystal.gbc"]
    assert j["roms"][0]["clean"] is False and j["roms"][0]["title"] == "not a Gen 1 cartridge"


@pytest.mark.asyncio
async def test_presets_are_named_specs_the_randomizer_would_accept(manager_client, manager_dir):
    """A preset is saved through the same builder the randomizer uses, so loading one can
    never produce a spec the pipeline refuses; names are case-insensitive and replace."""
    ok = await (await manager_client.post("/api/presets", json={"name": "Chaos", "spec": {"wild": "random"}})).json()
    assert ok["ok"] and ok["preset"]["name"] == "Chaos"
    bad = await manager_client.post("/api/presets", json={"name": "Bad", "spec": {"types": "random"}})
    assert bad.status == 400 and "types" in (await bad.json())["error"]
    assert (await manager_client.post("/api/presets", json={"name": "", "spec": {}})).status == 400
    await manager_client.post("/api/presets", json={"name": "chaos", "spec": {"wild": "area"}})
    j = await (await manager_client.get("/api/presets")).json()
    assert [(p["name"], p["spec"]["wild"]) for p in j["presets"]] == [("chaos", "area")]
    assert (manager_dir / "presets.json").exists()
    assert (await manager_client.post("/api/presets/delete", json={"name": "CHAOS"})).status == 200
    assert (await manager_client.post("/api/presets/delete", json={"name": "CHAOS"})).status == 404
    assert (await (await manager_client.get("/api/presets")).json())["presets"] == []


@pytest.mark.asyncio
async def test_settings_export_and_import_are_upr_files_through_the_pipeline_gates(manager_client):
    """Export writes the .rnqs the randomizer would write for the spec (UPR's GUI opens it);
    import reads one back through admit_settings, so a GUI-built file that randomizes
    types is refused by name instead of being silently read as 'unchanged'."""
    from server.upr_settings import build_spec
    spec = {"wild": "area", "wild_levels": 25, "trainers": "unchanged"}
    resp = await manager_client.post("/api/randomizer/settings/export", json={"spec": spec, "name": "Hard mode!"})
    assert resp.status == 200 and resp.headers["Content-Disposition"].endswith('"Hard_mode.rnqs"')
    blob = await resp.read()
    assert blob == build_spec(spec), "the same bytes handle_randomize writes"

    async def imp(name, data):
        form = aiohttp.FormData()
        form.add_field("file", data, filename=name, content_type="application/octet-stream")
        return await (await manager_client.post("/api/randomizer/settings/import", data=form)).json()

    back = await imp("Hard_mode.rnqs", blob)
    assert back["ok"] and back["spec"]["wild"] == "area" and back["spec"]["wild_levels"] == 25
    assert "wild level curve +25%" in back["summary"]
    forbidden = await imp("types.rnqs", _rnqs_with_types_randomized())
    assert forbidden["ok"] is False and "types" in forbidden["error"]
    garbage = await imp("x.rnqs", b"not a settings file")
    assert garbage["ok"] is False and "unreadable" in garbage["error"]
    assert (await manager_client.post("/api/randomizer/settings/export", json={"spec": {"bogus": 1}})).status == 400


def _rnqs_with_types_randomized() -> bytes:
    """A file UPR's GUI could produce that SLink must refuse: build the default file and
    clear the types_UNCHANGED bit the way Settings.toString() lays it out."""
    from server.upr_settings import FLAGS, build_spec, load
    raw = bytearray(build_spec({}))
    parsed = load(bytes(raw))
    data = bytearray(parsed["data"])
    i, bit = FLAGS["types_UNCHANGED"]
    data[i] &= ~(1 << bit) & 0xFF
    data[FLAGS["types_COMPLETELY_RANDOM"][0]] |= 1 << FLAGS["types_COMPLETELY_RANDOM"][1]
    from server.upr_settings import _encode
    return _encode(data, parsed["rom_name"])


def test_a_cartridge_says_which_family_it_belongs_to():
    """The picker greys a pure dump on a vanilla run and the reverse; that needs the family
    on every described cartridge, not only on a pair (family_of)."""
    from server.upr_pipeline import describe_rom
    red = os.path.join(os.path.dirname(__file__), "..", "..", "patch", "build", "gen1_red.gb")
    if not os.path.exists(red):
        pytest.skip("patch/build/gen1_red.gb not present")
    assert describe_rom(red, False)["family"] == "gen1_rby"


@pytest.mark.asyncio
async def test_uploaded_rom_lands_in_roms_and_a_same_named_different_file_is_kept(manager_client, tmp_path, monkeypatch):
    from server import manager
    monkeypatch.setattr(manager, "ROM_UPLOAD_DIR", str(tmp_path / "roms"))
    monkeypatch.setattr(manager, "ROM_DIRS", (str(tmp_path / "roms"),))

    async def upload(name, data):
        form = aiohttp.FormData()
        form.add_field("file", data, filename=name, content_type="application/octet-stream")
        return await (await manager_client.post("/api/roms", data=form)).json()

    j = await upload("red.gb", b"a" * 16)
    assert j["ok"] and j["kind"] == "rom" and j["path"] == str(tmp_path / "roms" / "red.gb")
    assert (await upload("red.gb", b"a" * 16))["path"] == j["path"], "the same bytes again is the same file"
    assert (await upload("red.gb", b"b" * 16))["path"] == str(tmp_path / "roms" / "red (2).gb"), "never overwrite a different file"
    sneaky = (await upload("../red.gb", b"c" * 16))["path"]
    assert os.path.dirname(sneaky) == str(tmp_path / "roms") and os.sep not in os.path.basename(sneaky), "stays in roms/"
    assert (await upload("x.exe", b"MZ")) == {"ok": False, "error": "send a .gb, .gbc or .jar as `file`"}
    assert (await manager_client.post("/api/roms", data=b"file=x")).status == 400, "not multipart"
    assert sorted(os.listdir(tmp_path / "roms")) == sorted(["red (2).gb", "red.gb", os.path.basename(sneaky)]), "no .part left behind"


@pytest.mark.asyncio
async def test_rom_download_is_404_until_a_pair_exists(manager_client, manager_dir):
    run = _stopped_run(manager_dir)
    assert (await manager_client.get(f"/api/runs/{run['run_id']}/rom/a")).status == 404
    assert (await manager_client.get(f"/api/runs/{run['run_id']}/settings.rnqs")).status == 404
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
