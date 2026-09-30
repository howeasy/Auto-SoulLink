"""Owner feedback: completed native trades journal display names, not identity keys.

Replay the real server dispatch/state outcome callback and render its website log.
The fixture keeps the pre-trade caches stale, as they are at trade_done before tick.
"""

import json
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from server.adapters.gen1_purergb import Gen1PureRGBAdapter
from server.adapters.gen2_gsc import Gen2GSCAdapter
from server.adapters.gen3_frlge import Gen3Adapter
from server.server import SLinkServer, build_app
from server.state import LinkEntry, LinkStatus, MonInfo


@pytest.fixture(params=("gen3", "pureRGB", "gen2"))
def trade_server(request, tmp_path):
    if request.param == "pureRGB":
        adapter = Gen1PureRGBAdapter(artifact_kind="overlay")
        species, evolved, other = 0x26, 0x95, 0xA5
        a_key, b_key, evolved_key = "ABCD:1234:26", "1234:5678:A5", "ABCD:1234:95"
    elif request.param == "gen2":
        adapter = Gen2GSCAdapter(rom_type="crystal")
        species, evolved, other = 64, 65, 19
        a_key, b_key, evolved_key = "ABCD:1234:40", "1234:5678:13", "ABCD:1234:41"
    else:
        adapter = Gen3Adapter()
        species, evolved, other = 64, 65, 19
        a_key, b_key, evolved_key = "A:1", "B:2", "A:1"
    srv = SLinkServer(data_dir=str(tmp_path))
    srv.adapter = srv.state.adapter = adapter
    entry = LinkEntry(area_id="route_1", a=MonInfo(key=a_key, species=species, level=30),
                      b=MonInfo(key=b_key, species=other, level=30), status=LinkStatus.ALIVE)
    srv.state.links.append(entry)
    srv.state._index_entry(entry)
    for pid, mon, slot in (("a", entry.a, 2), ("b", entry.b, 4)):
        srv.state.party_keys[pid].add(mon.key)
        srv.state.party_size[pid] = 2
        srv.state.pokeballs_obtained[pid] = True
        srv.state.partner_blobs[pid] = [{"slot": slot, "key": mon.key,
                                         "blob": bytes(100), "species_id": mon.species}]
        srv.party_details[pid][mon.key] = {"species_id": mon.species, "nickname": ""}
        srv._cache_mon_info(mon.key, srv.party_details[pid][mon.key], pid)
    return srv, entry, a_key, b_key, evolved_key, evolved, other


def _applying(srv):
    if srv.adapter.native_trade_ui():
        srv._dispatch("a", {"event": "trade_offer", "slot": 2})
    else:
        srv._dispatch("a", {"event": "trade_request"})
        token = srv.state.pending_trade["token"]
        srv._dispatch("a", {"event": "menu_result", "token": token, "choice": 0})
        srv._dispatch("a", {"event": "mon_chosen", "token": token, "slot": 2})
    token = srv.state.pending_trade["token"]
    srv._dispatch("b", {"event": "menu_result", "token": token, "choice": 1})
    assert srv.state.pending_trade["phase"] == "applying"
    return token


def _complete(case):
    srv, entry, a_key, b_key, evolved_key, evolved, other = case
    token = _applying(srv)
    srv._dispatch("a", {"event": "trade_done", "token": token,
                         "new_key": b_key, "new_species": other})
    assert srv.state.pending_trade is not None
    assert not any(e["type"] == "trade_committed" for e in srv._recent_events)
    srv._dispatch("b", {"event": "trade_done", "token": token,
                         "new_key": evolved_key, "new_species": evolved})
    assert srv.state.pending_trade is None
    assert (entry.a.key, entry.b.key) == (b_key, evolved_key)
    event = next(e for e in srv._recent_events if e["type"] == "trade_committed")
    assert event["key"] == token
    assert srv.state.trade_last["a_key"] == a_key
    assert srv.state.trade_last["b_key"] == b_key
    return event


@pytest.mark.parametrize("empty_caches", (False, True))
def test_completed_trade_uses_names_after_swap_and_evolution(trade_server, empty_caches):
    srv = trade_server[0]
    if empty_caches:
        srv.party_details = {"a": {}, "b": {}}
        srv._mon_cache.clear()
    event = _complete(trade_server)
    assert "Rattata" in event["text"]
    assert "Alakazam" in event["text"], "post-trade species must beat stale Kadabra cache"
    assert "Kadabra" not in event["text"]
    assert trade_server[2] not in event["text"] and trade_server[3] not in event["text"]
    persisted = json.loads(Path(srv._events_path).read_text(encoding="utf-8"))
    assert persisted[0] == event


@pytest.mark.asyncio
async def test_website_trade_log_escapes_nicknames(trade_server):
    srv, entry, *_ = trade_server
    entry.a.nickname = "<script>trade()</script>"
    entry.b.nickname = "Rat & pal"
    event = _complete(trade_server)
    assert entry.a.nickname in event["text"] and entry.b.nickname in event["text"]
    async with TestClient(TestServer(build_app(srv))) as client:
        resp = await client.get("/")
        assert resp.status == 200
        html = await resp.text()
    html = html.split('<aside class="mk-logcol">', 1)[1].split("</aside>", 1)[0]
    assert "&lt;script&gt;trade()&lt;/script&gt;" in html
    assert "Rat &amp; pal" in html
    assert "<script>trade()</script>" not in html


def test_uncertain_and_rolled_back_trade_logs_keep_original_names(trade_server):
    srv, entry, a_key, b_key, *_ = trade_server
    token = _applying(srv)
    srv._dispatch("a", {"event": "trade_done", "token": token, "uncertain": True})
    uncertain = srv._recent_events[0]
    assert uncertain["type"] == "trade_uncertain"
    assert "Kadabra" in uncertain["text"] and "Rattata" in uncertain["text"]
    srv._dispatch("a", {"event": "tick", "party": [{"key": a_key, "species_id": entry.a.species}]})
    srv._dispatch("b", {"event": "trade_done", "token": token, "new_key": b_key, "new_species": 0})
    assert srv.state.pending_trade is None
    assert srv._recent_events[0]["type"] == "trade_rolled_back"
    assert "Kadabra" in srv._recent_events[0]["text"] and "Rattata" in srv._recent_events[0]["text"]


def test_missing_trade_identity_uses_bounded_fallback(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    srv._journal_trade({"outcome": "committed", "token": "t-missing",
                        "a_key": "unknown-old-a", "b_key": "unknown-old-b",
                        "a_new": "unknown-new-a", "b_new": "", "verdict": {}, "problem": ""})
    assert "unknown-" in srv._recent_events[0]["text"]
    assert "unknown-new-a" not in srv._recent_events[0]["text"]
