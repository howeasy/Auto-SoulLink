"""POST /api/runs/{id}/randomize — the Manager's side of the randomizer pipeline.

The route is thin on purpose; server/upr_pipeline.py owns the decisions and is tested
directly. What is worth testing HERE is the part only the Manager can get wrong: that a
refusal reaches the caller as a 400 with the reason intact rather than a 500 or a silent
success, and that everything needed to trust the pair is persisted onto the run.

Persisting it is not bookkeeping. UPR's CLI has no seed flag and writes the seed only to
its log, so if this step does not record the seeds and hashes, nothing can reconstruct them
afterwards.
"""
from __future__ import annotations

import json
import os

import pytest

pytest.importorskip("aiohttp", reason="the manager is an aiohttp app")

from server import manager as mgr  # noqa: E402
from server.upr_settings import build, build_categories  # noqa: E402

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_RED = os.path.join(_REPO, "patch", "build", "gen1_red.gb")
_BLUE = os.path.join(_REPO, "patch", "build", "gen1_blue.gb")
ALL_CATEGORIES = {"wild", "starters", "statics", "trainers", "tms", "field_items"}


def _jar() -> str:
    from tests.conftest import find_upr_jar
    jar = find_upr_jar()
    if not jar:
        pytest.skip("PokeRandoZX.jar not found — put it in .cache/upr/ or set SLINK_UPR_JAR")
    return jar


def _roms():
    for path in (_RED, _BLUE):
        if not os.path.exists(path):
            pytest.skip(f"{path} not present")


class _Request:
    """The three things handle_randomize touches. The repo tests manager handlers by
    calling them directly rather than over HTTP (see test_manager_launcher.py), which keeps
    this independent of whether pytest-aiohttp happens to be installed."""

    def __init__(self, run_id: str, body):
        self.match_info = {"run_id": run_id}
        self._body = body

    async def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


@pytest.fixture
def manager_dir(tmp_path, monkeypatch):
    """Point the manager's registry at a temp dir so no real run is touched."""
    d = tmp_path / "runs"
    d.mkdir()
    monkeypatch.setattr(mgr, "MANAGER_DIR", str(d))
    monkeypatch.setattr(mgr, "REGISTRY_PATH", str(d / "registry.json"))
    os.makedirs(d / "run_test", exist_ok=True)
    mgr._save_registry([{"run_id": "run_test", "name": "test", "tcp_port": 1,
                         "http_port": 2, "status": "stopped", "pid": None}])
    return d


async def _post(body, run_id="run_test"):
    m = mgr.RunManager.__new__(mgr.RunManager)
    m.bind_host, m.manager_port = "127.0.0.1", 0
    resp = await m.handle_randomize(_Request(run_id, body))
    return resp.status, json.loads(resp.text)


# ── refusals reach the caller ────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_an_unknown_run_is_404(manager_dir):
    status, body = await _post({}, run_id="nope")
    assert status == 404 and body["ok"] is False


@pytest.mark.asyncio
async def test_missing_arguments_are_named(manager_dir):
    status, body = await _post({"jar": "x"})
    assert status == 400
    assert "settings" in body["error"] and "rom_a" in body["error"]


@pytest.mark.asyncio
async def test_a_pipeline_refusal_is_a_400_with_its_reason(manager_dir, tmp_path):
    """A refusal is the feature. It must not surface as a 500 or, worse, as ok:true.

    Types decide the type clause, so settings that randomize them cannot be used -- and the
    caller has to be told which setting was the problem to be able to fix it.
    """
    _roms()
    bad = tmp_path / "bad.rnqs"
    bad.write_bytes(build({"types_UNCHANGED": False}))
    status, body = await _post({
        "jar": __file__, "settings": str(bad), "rom_a": _RED, "rom_b": _BLUE})
    assert status == 400, body
    assert body["ok"] is False
    assert "types" in body["error"]


@pytest.mark.asyncio
async def test_a_pure_run_refuses_a_vanilla_pair_before_spending_anything(manager_dir, monkeypatch):
    """The run's game names the family its players will connect with; a pair from the
    other family would be refused at the first hello, after the randomizer ran. Refuse it
    here, by name, whatever the settings source."""
    _roms()
    mgr._update_run("run_test", game="gen1_purergb")
    calls = []
    monkeypatch.setattr(mgr, "_spawn_run", None, raising=False)
    import server.upr_pipeline as pipeline
    monkeypatch.setattr(pipeline, "prepare_pair", lambda *a, **k: calls.append(a))
    for body in ({"jar": __file__, "settings": __file__, "rom_a": _RED, "rom_b": _BLUE},
                 {"jar": __file__, "categories": ["wild"], "rom_a": _RED, "rom_b": _BLUE}):
        status, out = await _post(body)
        assert status == 400 and "PureRed" in out["error"] and "vanilla" in out["error"], out
    assert not calls, "nothing was randomized"
    assert not (manager_dir / "run_test" / "settings.rnqs").exists()


@pytest.mark.asyncio
async def test_a_spec_body_writes_the_settings_file_the_form_asked_for(manager_dir, monkeypatch):
    """The form posts its options, not a file; the manager writes settings.rnqs from them
    through the same builder the allowlist is computed from, then runs the pipeline on it."""
    from server import upr_pipeline
    from server.upr_settings import load, spec_from_parsed

    _roms()
    seen = {}

    def fake_prepare_pair(jar, settings, sources, out_dir, **kw):
        seen["spec"] = spec_from_parsed(load(settings))
        raise upr_pipeline.UprPipelineError("stop here")

    monkeypatch.setattr(upr_pipeline, "prepare_pair", fake_prepare_pair)
    status, body = await _post({"jar": "x", "rom_a": _RED, "rom_b": _BLUE,
                                "spec": {"trainers_levels": 30, "trainers_force_evolved": 36,
                                         "wild": "area", "starters": "unchanged"}})
    assert status == 400 and body["error"] == "stop here"
    assert seen["spec"]["trainers_levels"] == 30
    assert seen["spec"]["trainers_force_evolved"] == 36
    assert seen["spec"]["wild"] == "area" and seen["spec"]["starters"] == "unchanged"
    assert seen["spec"]["fastest_text"] is True         # a default the body did not mention
    assert os.path.exists(os.path.join(mgr.MANAGER_DIR, "run_test", "settings.rnqs"))


@pytest.mark.asyncio
async def test_a_bad_spec_is_a_400_naming_the_option(manager_dir):
    status, body = await _post({"jar": "x", "rom_a": _RED, "rom_b": _BLUE,
                                "spec": {"trainers_levels": 999}})
    assert status == 400 and "trainers_levels" in body["error"]
    status, body = await _post({"jar": "x", "rom_a": _RED, "rom_b": _BLUE, "spec": [1]})
    assert status == 400 and "spec" in body["error"]


@pytest.mark.asyncio
async def test_nothing_is_recorded_on_the_run_when_it_refuses(tmp_path, manager_dir):
    bad = tmp_path / "bad.rnqs"
    bad.write_bytes(build({"evolutions_UNCHANGED": False}))
    await _post({"jar": __file__, "settings": str(bad),
                 "rom_a": _RED, "rom_b": _BLUE})
    run = mgr._find_run(mgr._load_registry(), "run_test")
    assert "randomizer" not in run, "a refused pair was recorded as if it had worked"


# ── the real pipeline through the route ──────────────────────────────────────────────────
class TestAgainstTheRealJar:
    @pytest.mark.asyncio
    async def test_a_successful_pair_is_recorded_on_the_run(self, tmp_path, manager_dir):
        _roms()
        settings = tmp_path / "s.rnqs"
        settings.write_bytes(build_categories(ALL_CATEGORIES))
        status, body = await _post({
            "jar": _jar(), "settings": str(settings), "rom_a": _RED, "rom_b": _BLUE})
        assert status == 200, body
        rnd = body["randomizer"]
        from server.upr_pipeline import ACCEPTED_UPR_VERSIONS
        assert rnd["upr_version"] in ACCEPTED_UPR_VERSIONS
        assert set(rnd["categories"]) == ALL_CATEGORIES
        assert rnd["spec"]["trainers"] == "random" and rnd["summary"].startswith("wild encounters random")
        a, b = rnd["players"]["a"], rnd["players"]["b"]
        assert a["seed"] != b["seed"]
        assert a["content_hash"] != b["content_hash"]
        for side in (a, b):
            assert os.path.exists(side["output"])
            # A 48-bit seed exceeds JS's exact integer range only above 2^53, but it is
            # carried as a STRING regardless so no consumer can round it.
            assert isinstance(side["seed"], str) and side["seed"].isdigit()

        # And it survives to the registry, which is the only place it can be recovered from.
        run = mgr._find_run(mgr._load_registry(), "run_test")
        assert run["randomizer"]["players"]["a"]["seed"] == a["seed"]
        assert run["randomizer"]["settings_sha256"] == rnd["settings_sha256"]

    @pytest.mark.asyncio
    async def test_the_outputs_land_inside_the_run_directory(self, tmp_path, manager_dir):
        _roms()
        settings = tmp_path / "s.rnqs"
        settings.write_bytes(build_categories({"wild"}))
        status, body = await _post({
            "jar": _jar(), "settings": str(settings), "rom_a": _RED, "rom_b": _BLUE})
        assert status == 200, body
        for side in body["randomizer"]["players"].values():
            assert os.path.abspath(side["output"]).startswith(
                os.path.abspath(str(manager_dir / "run_test"))), side["output"]

    @pytest.mark.asyncio
    async def test_the_recorded_hashes_describe_the_files_on_disk(self, tmp_path, manager_dir):
        """The whole point of recording them is that they can be checked later."""
        _roms()
        import hashlib
        settings = tmp_path / "s.rnqs"
        settings.write_bytes(build_categories({"wild"}))
        _status, body = await _post({
            "jar": _jar(), "settings": str(settings), "rom_a": _RED, "rom_b": _BLUE})
        for side in body["randomizer"]["players"].values():
            with open(side["output"], "rb") as f:
                assert hashlib.sha1(f.read()).hexdigest() == side["rom_sha1"]
        with open(settings, "rb") as f:
            assert hashlib.sha256(f.read()).hexdigest() == \
                body["randomizer"]["settings_sha256"]
