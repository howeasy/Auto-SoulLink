"""Contracts consumed by dashboard.js survive changes to the HTML generator."""

import copy
import json
import re
from collections import Counter
from pathlib import Path

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from server.server import build_app
from tests.html_contract import Document
from tests.ui_support import hydrate_capture

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(params=["gen3", "gen1"])
def populated(request, tmp_path):
    capture = json.loads((ROOT / f"tests/fixtures/ui/source/{request.param}.json").read_text(encoding="utf-8"))
    srv = hydrate_capture(capture, tmp_path / request.param)
    srv.battle_state["b"]["enemy_party"][0]["stat_stages"] = [7, 6, 6, 8, 9, 6, 6]
    return srv


@pytest_asyncio.fixture
async def rendered(populated):
    async with TestClient(TestServer(build_app(populated))) as client:
        response = await client.get("/")
        assert response.status == 200
        text = await response.text()
        yield populated, text, Document(text), client


def filter_values():
    source = (ROOT / "server/static/dashboard.js").read_text(encoding="utf-8")
    groups = re.search(r"var FILTER_GROUPS = \{(.*?)\};", source, re.S)
    assert groups, "the filter contract moved; update its explicit consumer guard"
    arrays = re.findall(r"\[([^]]+)\]", groups[1])
    return set(re.findall(r"'([^']+)'", " ".join(arrays)))


@pytest.mark.asyncio
async def test_encounter_table_sort_filter_and_search_contract(rendered):
    _, _, dom, _ = rendered
    table = dom.by_id("enc-table")
    dom.by_id("enc-filters")
    assert dom.by_id("dash-search-input").tag == "input"
    headers = list(table.descendants("th"))
    assert len(headers) == 4
    for column, header in enumerate(headers):
        assert header.has_class("sortable")
        assert int(header.attrs["data-col"]) == column
        assert header.closest("thead") is not None
    rows = [row for row in table.descendants("tr") if "data-status" in row.attrs]
    assert len(rows) >= 8
    assert {row.attrs["data-status"] for row in rows} <= filter_values()
    for row in rows:
        cells = [cell for cell in row.children if cell.tag == "td"]
        assert len(cells) == 4
        assert "data-sort" in cells[0].attrs and "data-sort" in cells[3].attrs
    events = [table for table in dom.root.descendants("table") if "data-no-search" in table.attrs]
    assert len(events) == 1 and events[0].has_class("events-table")


@pytest.mark.asyncio
async def test_disclosure_ids_and_source_header_structure(rendered):
    _, _, dom, _ = rendered
    details = [node for node in dom.root.descendants("details") if "data-details-key" in node.attrs]
    assert len(details) >= 10
    for node in details:
        assert node.attrs.get("id") == "d-" + node.attrs["data-details-key"]
        assert len([child for child in node.children if child.tag == "summary"]) == 1
    ids = Counter(node.attrs["id"] for node in dom.root.descendants() if node.attrs.get("id"))
    assert not {key: count for key, count in ids.items() if count > 1}
    for header in dom.root.descendants("th"):
        head = header.closest("thead")
        assert head is not None and head.closest("table") is header.closest("table")


@pytest.mark.asyncio
async def test_sprite_html_is_not_escaped_and_poll_contract_survives(rendered):
    srv, text, dom, _ = rendered
    sprites = [img for img in dom.root.descendants("img") if img.has_class("mon-sprite")]
    assert len(sprites) >= 12
    assert all(img.attrs.get("data-species") for img in sprites)
    assert srv._get_sprite_html(25) in text
    content = dom.by_id("content")
    assert content.attrs["hx-get"] == "/"
    assert "every 2s" in content.attrs["hx-trigger"]
    assert "morph" in content.attrs["hx-swap"]
    # Exercise real generation-specific stat labels through the page, so a
    # later macro reuse cannot silently split Gen1 Special into two stats.
    labels = srv.adapter.stat_stage_labels()
    for index, amount in ((0, 1), (3, 2), (4, 3)):
        if labels[index]:
            assert f">+{amount} {labels[index]}</span>" in text
        else:
            assert f">+{amount} " not in text


@pytest.mark.asyncio
async def test_calc_preview_is_unique_per_battling_rr_player(rendered):
    srv, _, dom, client = rendered
    if not srv.state.is_rr:
        assert not [node for node in dom.root.descendants() if node.attrs.get("id", "").startswith("calc-preview-")]
        return
    assert dom.by_id("calc-preview-b").attrs["data-in-battle"] == "1"
    srv.battle_state["a"] = copy.deepcopy(srv.battle_state["b"])
    both = Document(await (await client.get("/")).text())
    for pid in ("a", "b"):
        assert both.by_id("calc-preview-" + pid).attrs["data-in-battle"] == "1"


@pytest.mark.asyncio
async def test_macro_smoke_route_renders_real_examples(rendered):
    _, _, _, client = rendered
    response = await client.get("/memorial?_smoke=1")
    assert response.status == 200
    text = await response.text()
    for expected in ("ZUBAT-A", "PIDGEY-B", "BIRBY-A", "RAT-B", "BIG", "FOX", "RIP"):
        assert expected in text
