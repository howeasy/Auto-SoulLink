"""HTTP/DOM contracts for the reviewed pair board and its shared drawer."""

import json
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
    server = hydrate_capture(capture, tmp_path / request.param)
    server.battle_state["b"]["enemy_party"][0]["stat_stages"] = [7, 6, 6, 8, 9, 6, 6]
    return server


@pytest_asyncio.fixture
async def rendered(populated):
    async with TestClient(TestServer(build_app(populated))) as client:
        response = await client.get("/")
        assert response.status == 200
        text = await response.text()
        yield populated, text, Document(text), client


def owner(node):
    while node is not None:
        if "data-player" in node.attrs:
            return node.attrs["data-player"]
        node = node.parent
    return None


@pytest.mark.asyncio
async def test_pair_rows_have_explicit_ownership_and_keep_every_party_member(rendered):
    server, _, dom, _ = rendered
    rows = [node for node in dom.root.descendants("article") if node.has_class("board-pair")]
    assert len(rows) >= 8
    for row in rows:
        cells = [child for child in row.children if child.tag == "div"]
        assert cells[0].attrs["data-player"] == "a" and cells[1].has_class("board-bond") and cells[2].attrs["data-player"] == "b"
    members = [(owner(node), node.attrs["data-mon-key"]) for node in dom.root.descendants("div") if "data-mon-key" in node.attrs]
    assert len(members) == len(set(members))
    for pid in ("a", "b"):
        assert all((pid, key) in members for key in server.state.party_keys[pid])
    assert not list(dom.root.descendants("iframe"))


@pytest.mark.asyncio
async def test_disclosure_ids_and_table_structure_survive_the_port(rendered):
    _, _, dom, _ = rendered
    details = [node for node in dom.root.descendants("details") if "data-details-key" in node.attrs]
    assert len(details) >= 10
    for node in details:
        assert node.attrs.get("id") == "d-" + node.attrs["data-details-key"]
        assert len([child for child in node.children if child.tag == "summary"]) == 1
    ids = Counter(node.attrs["id"] for node in dom.root.descendants() if node.attrs.get("id"))
    assert not {key: count for key, count in ids.items() if count > 1}
    for header in dom.by_id("content").descendants("th"):
        assert header.closest("thead") is not None


@pytest.mark.asyncio
async def test_sprites_polling_and_generation_specific_stages_survive(rendered):
    server, text, dom, _ = rendered
    sprites = [node for node in dom.root.descendants("img") if node.has_class("mon-sprite")]
    assert len(sprites) >= 12 and all(node.attrs.get("data-species") for node in sprites)
    assert server._get_sprite_html(25) in text
    content = dom.by_id("content")
    assert content.attrs["hx-get"] == "/" and content.attrs["hx-trigger"] == "every 2s"
    assert content.attrs["hx-request"] == '{"timeout":10000}'
    assert "morph" in content.attrs["hx-swap"]
    for index, amount in ((0, 1), (3, 2), (4, 3)):
        label = server.adapter.stat_stage_labels()[index]
        if label:
            assert f">+{amount} {label}</span>" in text
        else:
            assert f">+{amount} " not in text


@pytest.mark.asyncio
async def test_foes_stay_with_fighting_player_and_calc_opens_separately(rendered):
    _, _, dom, _ = rendered
    foes = [node for node in dom.root.descendants("div") if "data-foe-owner" in node.attrs]
    assert foes and all(node.attrs["data-foe-owner"] == "b" and owner(node) == "b" for node in foes)
    stakes = [node for node in dom.root.descendants("span") if node.has_class("board-stake")]
    assert stakes and all(owner(node) == "a" for node in stakes)
    calc = [node for node in dom.root.descendants("a") if "data-calc-link" in node.attrs]
    assert len(calc) == 1 and calc[0].attrs["target"] == "_blank" and "noopener" in calc[0].attrs["rel"]


@pytest.mark.asyncio
async def test_setup_uses_friendly_names_and_current_states(rendered):
    _, _, _, client = rendered
    response = await client.get("/?view=setup")
    assert response.status == 200
    text = await response.text()
    dom = Document(text)
    assert "Game family" in text and "Load each player's save first" in text
    current = [node for node in dom.root.descendants("a") if node.attrs.get("aria-current") == "page"]
    assert any(node.attrs.get("href") == "/?view=setup" for node in current)
    assert any(node.has_class("board-opt-why") for node in dom.root.descendants("span"))


@pytest.mark.asyncio
async def test_debug_dialog_is_outside_the_refresh_target(rendered):
    _, _, dom, _ = rendered
    dialog = dom.by_id("debug-dialog")
    assert dialog.tag == "dialog" and dialog.attrs["aria-modal"] == "true"
    dom.by_id(dialog.attrs["aria-labelledby"])
    assert dom.by_id("debug-close").closest("dialog") is dialog
    assert not list(dom.by_id("content").descendants("dialog"))


@pytest.mark.asyncio
async def test_macro_smoke_route_renders_real_examples(rendered):
    _, _, _, client = rendered
    response = await client.get("/memorial?_smoke=1")
    assert response.status == 200
    text = await response.text()
    for expected in ("ZUBAT-A", "PIDGEY-B", "BIRBY-A", "RAT-B", "BIG", "FOX", "RIP"):
        assert expected in text
