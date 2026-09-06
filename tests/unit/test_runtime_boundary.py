"""The UI can read real facts without creating authority or mutating a run."""
import copy
import itertools
import json

import pytest

from server import runtime_boundary as boundary
from server.adapters import get_adapter
from server.server import SLinkServer
from server.state import LinkEntry, LinkStatus, MonInfo, SoulLinkState
from tests.unit.test_gen1_sessions import contract, hello, server


def forbid(*args, **kwargs):
    pytest.fail("a read-only call attempted a mutation")


@pytest.mark.parametrize("titles", itertools.product(("red", "blue", "yellow"), repeat=2))
def test_per_player_facts_are_detached_and_follow_the_actual_admission(titles, tmp_path, monkeypatch):
    spec = contract(*titles)
    srv = server(tmp_path, spec)
    before_hello = srv.read_runtime_facts(now=100)
    assert before_hello["players"]["a"]["verified_cartridge"] is None
    assert before_hello["players"]["b"]["adapter"] is None
    for player in ("a", "b"):
        assert srv._gen1_wire_response(player, hello(spec, player), object())["ack"] == "ACK"
    srv.connected_players["a"]["last_seen_ts"] = 90
    srv.state.pc_trade_npc = True
    srv.state.queued_commands["a"].append({"cmd": "force_faint", "key": "1234:0000:99"})
    queues = copy.deepcopy(srv.state.queued_commands)
    identities = copy.deepcopy(srv.state.player_identity)
    monkeypatch.setattr(srv.state, "_save", forbid)
    monkeypatch.setattr(srv.state, "handle_event", forbid)
    monkeypatch.setattr(srv, "_refresh_rom_contract", forbid)
    facts = srv.read_runtime_facts(now=100)
    for player, title in zip(("a", "b"), titles, strict=True):
        row = facts["players"][player]
        assert row["verified_cartridge"]["variant"] == title
        assert row["expected_cartridge"] == spec["players"][player]
        assert row["adapter"]["mons_per_box"] == 20
        assert row["feature_gates"]["pc_trade_npc"] is False
        assert row["feature_readiness"] is None
    assert facts["requested_rules"]["pc_trade_npc"] is True
    assert facts["players"]["a"]["observation"]["age_seconds"] == 10
    assert srv.read_runtime_facts(now=105)["players"]["a"]["observation"]["age_seconds"] == 15
    assert facts["operations"]["pending_operations"] is None and facts["operations"]["receipts"] is None
    assert facts["operations"]["durable_commands"] is False
    assert facts["recovery"] is None and facts["liveness"] is None
    facts["players"]["a"]["verified_cartridge"]["variant"] = "changed"
    facts["players"]["b"]["expected_cartridge"]["capabilities"]["pc_trade"] = True
    assert srv._rom_contract == spec
    assert srv._gen1_sessions.sessions["a"].metadata["variant"] == titles[0]
    assert srv.state.player_identity == identities and srv.state.queued_commands == queues


def test_live_rule_snapshot_never_becomes_a_persistence_receipt(tmp_path, monkeypatch):
    srv = SLinkServer(data_dir=str(tmp_path))
    pair = LinkEntry("route_1", MonInfo("a:1", nickname="A"), MonInfo("b:2", nickname="B"), LinkStatus.DEAD)
    srv.state.links.append(pair)
    monkeypatch.setattr(srv.state, "_save", forbid)
    snapshot = srv.read_rule_state()
    assert snapshot["source"] == "live_memory" and snapshot["committed_revision"] is None
    snapshot["document"]["links"][0]["a"]["nickname"] = "changed"
    assert srv.state.links[0].a.nickname == "A"


HANDLERS = ("handle_reset_api", "handle_debug_rollback", "handle_inject_link_api",
            "handle_inject_link_by_slot_api", "handle_api_attempts", "handle_debug_inject_event",
            "handle_debug_queue_command", "handle_debug_set_pokeballs", "handle_debug_set_area_state",
            "handle_debug_clear_pending", "handle_debug_unlink", "handle_debug_revive")


@pytest.mark.asyncio
@pytest.mark.parametrize("handler", HANDLERS)
async def test_restricted_rby_handlers_refuse_before_reading_or_mutating(handler, tmp_path, monkeypatch):
    srv = server(tmp_path, contract("yellow", "yellow"))
    before = srv.state.to_document()
    monkeypatch.setattr(srv.state, "_save", forbid)
    monkeypatch.setattr(srv.state, "handle_event", forbid)
    response = await getattr(srv, handler)(object())
    assert response.status == 409
    body = json.loads(response.text)
    assert body["available"] is False and body["reason_code"] == "rby_operation_interface_unavailable"
    assert srv.state.to_document() == before


@pytest.mark.asyncio
async def test_gen3_mutation_path_keeps_its_existing_behavior(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    class Request:
        async def json(self):
            return {"count": 4}
    assert boundary.operation_decision(srv, "attempts_edit")["available"] is True
    response = await srv.handle_api_attempts(Request())
    assert response.status == 200 and srv.state.attempts_count == 4
    assert json.loads((tmp_path / "links.json").read_text())["attempts_count"] == 4


def test_existing_ap_binding_does_not_inherit_rby_restrictions(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    srv.state.adapter = get_adapter("gen1_rby", rom_type="red_ap")
    srv.state.rom_type = "red_ap"
    assert boundary.operation_decision(srv, "reset")["available"] is True


@pytest.mark.parametrize("change", ["missing", "malformed", "incomplete", "journal"])
def test_stopped_state_missing_or_unverified_is_unavailable_not_empty(change, tmp_path, monkeypatch):
    if change == "malformed":
        (tmp_path / "links.json").write_text('{"links":[],"links":[]}')
    elif change == "incomplete":
        (tmp_path / "links.json").write_text('{}')
    elif change == "journal":
        (tmp_path / "runtime.sqlite3").write_bytes(b"pending authoritative journal")
    before = {p.relative_to(tmp_path).as_posix(): p.read_bytes() if p.is_file() else None for p in tmp_path.rglob("*")}
    monkeypatch.setattr(SoulLinkState, "_save", forbid)
    result = boundary.read_saved_run(tmp_path)
    assert result["available"] is False and result["document"] is None and result["reason_code"]
    assert {p.relative_to(tmp_path).as_posix(): p.read_bytes() if p.is_file() else None for p in tmp_path.rglob("*")} == before


def test_stopped_read_returns_exact_saved_document_without_restore_or_repair(tmp_path, monkeypatch):
    state = SoulLinkState(data_dir=str(tmp_path))
    state.rom_type = "firered"
    state.links.append(LinkEntry("route_1", MonInfo("a:1"), MonInfo("b:2"), LinkStatus.DEAD))
    document = state.to_document()
    path = tmp_path / "links.json"
    path.write_text(json.dumps(document))
    before = path.read_bytes()
    monkeypatch.setattr(SoulLinkState, "load", forbid)
    monkeypatch.setattr(SoulLinkState, "_save", forbid)
    result = boundary.read_saved_run(tmp_path)
    assert result["available"] and result["document"] == document
    result["document"]["links"].clear()
    assert path.read_bytes() == before
