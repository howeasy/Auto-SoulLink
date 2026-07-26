"""The overlay catalogue must describe overlays that actually exist.

`server/overlay_catalog.py` is the registry the stream launcher renders from: a slug with no
route is a dead link the user only finds mid-stream, and a route with no catalogue entry is an
overlay nobody can discover. Nothing checked either direction before.
"""
import pytest

from server.overlay_catalog import EVENT_FILTERS_DEFAULT_OFF, EVENT_FILTERS_DEFAULT_ON, OVERLAYS

aiohttp = pytest.importorskip("aiohttp")

from server.server import SLinkServer, build_app  # noqa: E402

# "all" is a synthetic entry: the launcher renders it as a grid of iframes pointing at the other
# overlays' real slugs, so there is deliberately no /stream/all route.
SYNTHETIC = {"all"}


@pytest.fixture(scope="module")
def stream_paths():
    import types
    stub = types.SimpleNamespace()
    for name in dir(SLinkServer):
        if name.startswith("handle_") or name == "_build_sidebar_html":
            setattr(stub, name, getattr(SLinkServer, name))
    app = build_app(stub)
    return {getattr(r.resource, "canonical", "") for r in app.router.routes() if r.method == "GET"}


def test_catalog_is_not_empty():
    assert len(OVERLAYS) > 5


@pytest.mark.parametrize("entry", OVERLAYS, ids=lambda e: e["slug"])
def test_entry_has_the_fields_the_launcher_renders(entry):
    for field in ("slug", "family", "title", "desc", "sizes", "layouts"):
        assert field in entry, f"{entry.get('slug')} is missing {field!r}"
    assert entry["title"] and entry["desc"]
    assert isinstance(entry["sizes"], list) and entry["sizes"]
    assert isinstance(entry["layouts"], list) and entry["layouts"]


def test_slugs_are_unique():
    slugs = [e["slug"] for e in OVERLAYS]
    assert len(slugs) == len(set(slugs)), f"duplicate slugs: {sorted(set(s for s in slugs if slugs.count(s) > 1))}"


@pytest.mark.parametrize("entry", [e for e in OVERLAYS if e["slug"] not in SYNTHETIC],
                         ids=lambda e: e["slug"])
def test_every_slug_has_a_real_route(entry, stream_paths):
    assert f"/stream/{entry['slug']}" in stream_paths, \
        f"catalogue advertises /stream/{entry['slug']} but no such route is registered"


@pytest.mark.parametrize("entry", [e for e in OVERLAYS if e["slug"] not in SYNTHETIC],
                         ids=lambda e: e["slug"])
def test_every_slug_has_an_htmx_fragment_route(entry, stream_paths):
    """The overlays refresh by polling <slug>/fragment; a missing one means a frozen overlay."""
    assert f"/stream/{entry['slug']}/fragment" in stream_paths


def test_event_filter_pills_do_not_overlap():
    assert not set(EVENT_FILTERS_DEFAULT_ON) & set(EVENT_FILTERS_DEFAULT_OFF)


def test_event_filters_cover_every_dashboard_event_type():
    """A type the dashboard styles but the overlays never list is invisible on stream."""
    known = set(EVENT_FILTERS_DEFAULT_ON) | set(EVENT_FILTERS_DEFAULT_OFF)
    styled = set(SLinkServer._EVENT_TYPE_CLASSES)
    missing = styled - known
    assert not missing, f"event types with no overlay filter pill: {sorted(missing)}"


def test_every_default_on_filter_has_a_pill():
    """stream_index.html used to hardcode its own copy of the filter roster, and it had drifted:
    force_explode was missing, so with Explode Mode on there was no pill for it AND the
    "are all filters enabled" comparison — which counts against that list — could never be
    satisfied. The roster is now single-sourced through the context."""
    import json

    from server.overlay_catalog import (EVENT_FILTERS_DEFAULT_OFF, EVENT_FILTERS_DEFAULT_ON,
                                        build_index_context)

    class _Req:
        rel_url = type("U", (), {"query": {}})()
        query, headers, cookies = {}, {}, {}

    roster = json.loads(build_index_context(_Req())["all_filters_json"])
    assert "force_explode" in roster
    assert set(EVENT_FILTERS_DEFAULT_ON) <= set(roster)
    assert set(EVENT_FILTERS_DEFAULT_OFF) <= set(roster)


def test_the_template_no_longer_carries_its_own_filter_list():
    import os
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "server", "templates", "stream_index.html")
    with open(tpl, encoding="utf-8") as f:
        src = f.read()
    assert "'force_faint', 'whiteout'" not in src, "the hardcoded roster is back — it will drift again"
