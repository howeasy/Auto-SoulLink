"""Offline preparation must expose missing contracts instead of passing silently."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web

from tools import ui_migration_inventory as inventory
from tools.ui_migration_inventory import compare, file_record, read_catalog, read_routes, snapshot

REPO = Path(__file__).resolve().parents[2]


def test_catalog_resolves_shared_controls_without_executing_code():
    assert read_catalog("SPEEDS = ['1', '2']\nOVERLAYS = [{'slug': 'feed', 'speeds': SPEEDS}]") == [
        {"slug": "feed", "speeds": ["1", "2"]}]
    with pytest.raises(ValueError, match="nonliteral"):
        read_catalog("OVERLAYS = __import__('os').system('this-must-never-run')")
    with pytest.raises(ValueError, match="duplicate"):
        read_catalog("OVERLAYS = [{'slug':'same'}, {'slug':'same'}]")


def test_dynamic_or_ambiguous_registrations_are_reported():
    routes, mounts, failures = read_routes("""
app.router.add_get('/fixed', handler, allow_head=False)
app.router.add_post('/change', handler)
app.router.add_get('/dynamic/' + name, handler)
app.router.add_routes(routes)
app.router.add_get('/ambiguous', handler, **options)
app.router.add_static('/static/', path='assets')
""", "example.py")
    assert [(row["method"], row["path"], row["served_methods"]) for row in routes] == [
        ("GET", "/fixed", ["GET"]), ("POST", "/change", ["POST"])]
    assert len(failures) == 3
    assert all(row["source"] == "example.py" and row["line"] for row in failures)
    assert [row["path"] for row in mounts] == ["/static/"]


def test_text_hashes_are_portable_and_binary_hashes_preserve_bytes(tmp_path):
    sample = tmp_path / "sample"
    sample.write_bytes(b"first\r\nsecond\r\n")
    text_before = file_record(tmp_path, "sample")
    binary_before = file_record(tmp_path, "sample", binary=True)
    sample.write_bytes(b"first\nsecond\n")
    assert file_record(tmp_path, "sample")["sha256"] == text_before["sha256"]
    assert file_record(tmp_path, "sample", binary=True)["sha256"] != binary_before["sha256"]
    with pytest.raises(ValueError, match="escapes"):
        file_record(tmp_path, "../outside")


def test_comparison_detects_same_count_route_replacements_and_control_loss():
    before = {"routes": {"run": [{"path": "/api/status", "served_methods": ["GET", "HEAD"]}]},
              "overlays": [{"slug": "events", "event_filters": True}], "static_mounts": []}
    after = copy.deepcopy(before)
    after["routes"]["run"][0]["path"] = "/api/wrong"
    del after["overlays"][0]["event_filters"]
    delta = compare(before, after)
    assert delta["route_patterns_removed"] == ["run GET /api/status", "run HEAD /api/status"]
    assert delta["route_patterns_added"] == ["run GET /api/wrong", "run HEAD /api/wrong"]
    assert delta["overlays_changed"] == ["events"]


def expected_routes(document, service):
    # aiohttp's canonical form removes the regex part of dynamic placeholders.
    return {(method, web.DynamicResource(row["path"]).canonical)
            for row in document["routes"][service] for method in row["served_methods"]}


def actual_routes(app):
    return {(route.method, route.resource.canonical) for route in app.router.routes()
            if not isinstance(route.resource, web.StaticResource)}


def test_snapshot_matches_actual_run_router_without_a_server_instance():
    from server.server import SLinkServer, build_app

    stub = SimpleNamespace(**{name: getattr(SLinkServer, name) for name in dir(SLinkServer)
                             if name.startswith("handle_") or name == "_build_sidebar_html"})
    document = snapshot(REPO)
    assert not document["unresolved_routes"]
    assert expected_routes(document, "run") == actual_routes(build_app(stub))
    assert all(row["both_registered"] for row in document["overlay_route_pairs"])
    assert "all" not in {row["slug"] for row in document["overlay_route_pairs"]}


@pytest.mark.asyncio
async def test_snapshot_matches_actual_manager_router_without_app_startup(monkeypatch):
    from server import manager

    captured = {}

    class AppCaptured(Exception):
        pass

    def capture(app):
        captured["app"] = app
        raise AppCaptured

    monkeypatch.setattr(manager.web, "AppRunner", capture)
    # Failure happens before runner setup, any socket, or lifecycle callbacks.
    with pytest.raises(AppCaptured):
        await manager.main("127.0.0.1", 0)
    assert expected_routes(snapshot(REPO), "manager") == actual_routes(captured["app"])


def test_checked_in_baseline_has_complete_route_pairs():
    baseline = json.loads((REPO / "docs/ui_migration/baseline.json").read_text(encoding="utf-8"))
    assert not baseline["unresolved_routes"]
    assert all(row["both_registered"] for row in baseline["overlay_route_pairs"])
    assert {row["family"] for row in baseline["mockup"]["selected_fonts"]} == {"Jersey 20", "IBM Plex Sans"}


def test_cli_reports_differences_and_unresolved_routes(tmp_path, monkeypatch, capsys):
    current = {"source_commit": "test", "routes": {"run": [{"path": "/api/status", "served_methods": ["GET"]}]},
               "overlays": [{"slug": "events"}], "static_mounts": [],
               "unresolved_routes": [], "overlay_route_pairs": [{"slug": "events", "both_registered": True}]}
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(current), encoding="utf-8")
    monkeypatch.setattr(inventory, "snapshot", lambda *args: current)
    assert inventory.main(["--compare", str(baseline)]) == 0
    assert not any(json.loads(capsys.readouterr().out)["differences"].values())
    current["routes"]["run"][0]["path"] = "/api/renamed"
    assert inventory.main(["--compare", str(baseline)]) == 1
    assert json.loads(capsys.readouterr().out)["differences"]["route_patterns_removed"] == ["run GET /api/status"]
    current["unresolved_routes"] = [{"source": "example.py", "line": 1, "reason": "dynamic path"}]
    assert inventory.main([]) == 2
    assert json.loads(capsys.readouterr().out)["unresolved_routes"]


def test_cli_does_not_publish_incomplete_snapshot_on_missing_inputs(tmp_path, capsys):
    output = tmp_path / "report.json"
    assert inventory.main(["--repo", str(tmp_path), "--output", str(output)]) == 2
    assert not output.exists()
    assert "UI inventory failed" in capsys.readouterr().err
