"""Configured durable RBY runtime on real SQLite/rules/TCP; host proof is modeled."""

import asyncio
import copy
from itertools import product

import pytest

from server.adapters import get_adapter
from server.gen1_command_receipts import Gen1ReceiptPolicy
from server.gen1_party_codec import PartyCodec
from server.gen1_runtime import Gen1Runtime
from server.gen1_runtime_admission import METADATA_SCHEMA, PROTOCOL
from server.gen1_runtime_state import Gen1RuntimeState
from server.gen1_staged_state import StagedGen1State
from server.identity_registry import IdentityRegistry
from server.paired_recovery import VerifiedReconciliation
from server.protocol import ProtocolError, canonical_json, decode_frame
from server.protocol_journal import JournalError
from server.server import SLinkServer, build_app
from server.state import AreaStatus, LinkEntry, LinkStatus, MonInfo, SoulLinkState
from tests.unit.test_gen1_party_codec import make_blob
from tests.unit.test_gen1_sessions import contract

RUN_ID = "7" * 32


class RuntimeCase:
    def __init__(self, path, variants=("yellow", "yellow")):
        self.path, self.variants = path, dict(zip(("a", "b"), variants, strict=True))
        self.contract = contract(*variants)
        self.time, self.counter, self.owners, self.admissions = 10.0, 100, {}, {}
        self.events, self.blobs, self.keys = [], {}, {}
        rules = SoulLinkState(
            data_dir=str(path), adapter=get_adapter("gen1_rby", rom_type=variants[0])
        )
        rules.rom_type = variants[0]
        rules.player_identity = {p: {"ot_id": "0000", "trainer_name": "SAME"} for p in ("a", "b")}
        halves = {}
        for p in ("a", "b"):
            codec = PartyCodec(self.variants[p])
            raw = make_blob(
                codec, dv=0x1000 if variants == ("yellow", "yellow") or p == "a" else 0x2000, otid=0
            )
            mon = codec.validate_blob(raw)
            self.blobs[p], self.keys[p] = raw, mon.key
            halves[p] = MonInfo(mon.key, mon.level, mon.species_id, "NICK")
            rules.party_keys[p] = {mon.key}
            rules.party_size[p] = 1
            rules.pokeballs_obtained[p] = True
            rules._has_helld.add(p)
            rules._ingest_party_blobs(
                p,
                [
                    {
                        "key": mon.key,
                        "level": mon.level,
                        "slot": 0,
                        "species_id": mon.species_id,
                        "blob_hex": raw.hex(),
                    }
                ],
            )
        link = LinkEntry("oaks_lab", halves["a"], halves["b"], LinkStatus.ALIVE)
        rules.links.append(link)
        rules._index_entry(link)
        rules.area_states["oaks_lab"] = AreaStatus.LINKED
        self.rules = StagedGen1State.from_live(rules, {"retired_pairs": []}).document()
        self.initial = Gen1RuntimeState.initial(
            self.rules, IdentityRegistry(RUN_ID).document(), self.contract, data_dir=path
        )
        self.open(initial=True)

    def token(self):
        self.counter += 1
        return f"{self.counter:032x}"

    def validate_event(self, player, event, state):
        self.events.append((player, copy.deepcopy(event)))
        if event != {"event": "faint", "key": self.keys[player]}:
            raise JournalError("test event policy only permits this observed faint")

    def verify_reconciliation(self, player, evidence, stage, binding):
        if evidence != {"schema": "explicit-test-host-proof-v1"}:
            return None
        recovery = stage.barrier.document()
        return VerifiedReconciliation(
            player,
            recovery["epoch"],
            binding["binding_digest"],
            binding["context_generation"],
            recovery["history_digest"],
            player * 64,
        )

    def open(self, initial=False):
        self.runtime = Gen1Runtime(
            self.path / "gen1.sqlite3",
            contract=self.contract,
            data_dir=self.path,
            validate_event=self.validate_event,
            validate_receipt=Gen1ReceiptPolicy(self.variants),
            verify_reconciliation=self.verify_reconciliation,
            initial_state=self.initial if initial else None,
            run_id=RUN_ID,
            clock=lambda: self.time,
        )

    def close(self):
        self.runtime.close()

    def hello(self, player, **changes):
        nonce = self.token()
        return {
            "protocol": PROTOCOL,
            "run_id": RUN_ID,
            "player": player,
            "event": "hello",
            "seq": 0,
            "client_nonce": nonce,
            "operation_id": nonce,
            "context_generation": player * 32,
            "gen1_metadata": {
                "schema": METADATA_SCHEMA,
                "cartridge": self.contract["players"][player],
                "save_identity": {"ot_id": "0000", "trainer_name": "SAME"},
                "physical_instance": ("1" if player == "a" else "2") * 32,
            },
            **changes,
        }

    def admit(self, player):
        owner = object()
        self.owners[player] = owner
        self.admissions[player] = self.runtime.process(self.hello(player), owner)
        return self.admissions[player]

    def envelope(self, player, payload, operation=None):
        session = self.runtime.gate.sessions[player]
        return {
            **copy.deepcopy(payload),
            "protocol": PROTOCOL,
            "player": player,
            "admission_epoch": self.runtime.gate.epoch,
            "session_id": session.session_id,
            "seq": session.last_seq + 1,
            "operation_id": operation or self.token(),
        }

    def send(self, player, payload, operation=None):
        message = self.envelope(player, payload, operation)
        return message, self.runtime.process(message, self.owners[player])

    def control(self, player, evidence=None):
        binding = self.admissions[player]["admission"]["control_binding"]
        nonce = self.token()
        return self.send(
            player,
            {
                "event": "control",
                "control": {**binding, "challenge": nonce},
                "reconciliation": evidence,
            },
            nonce,
        )


@pytest.fixture
def case(tmp_path):
    value = RuntimeCase(tmp_path)
    yield value
    value.close()


@pytest.mark.parametrize("variants", list(product(("red", "blue", "yellow"), repeat=2)))
@pytest.mark.parametrize("order", [("a", "b"), ("b", "a")])
def test_metadata_only_admission_preserves_all_gameplay_state_and_emits_no_commands(
    tmp_path, variants, order
):
    case = RuntimeCase(tmp_path, variants)
    try:
        before = case.runtime.journal.snapshot().state
        for p in order:
            response = case.admit(p)
            assert response["commands"] == []
            assert response["admission"]["rom_type"] == case.variants[p]
        after = case.runtime.journal.snapshot().state
        assert after["rules"] == before["rules"] and after["identities"] == before["identities"]
        assert case.runtime.state().barrier.ticket() is None
        assert case.runtime.journal.pending("a") == case.runtime.journal.pending("b") == []
        assert not case.events and not (tmp_path / "links.json").exists()
    finally:
        case.close()


@pytest.mark.parametrize("field", ["party", "pc_boxes", "has_pokeballs", "rom_type", "commands"])
def test_legacy_gameplay_fields_in_durable_hello_are_refused_before_state_adoption(case, field):
    before = case.runtime.journal.snapshot()
    with pytest.raises(ProtocolError, match="metadata only"):
        case.runtime.process(case.hello("a", **{field: []}), object())
    assert case.runtime.journal.snapshot() == before and not case.runtime.gate.sessions


def test_bootstrap_refuses_unpublished_legacy_queues_instead_of_draining_them_on_hello(case):
    document = copy.deepcopy(case.rules)
    document["runtime"]["queued_commands"]["a"] = [{"cmd": "force_faint", "key": case.keys["a"]}]
    with pytest.raises(JournalError, match="already published"):
        Gen1RuntimeState.initial(
            document, IdentityRegistry(RUN_ID).document(), case.contract, data_dir=case.path
        )


def test_semantic_replay_survives_reconnect_without_hello_readopting_party(case):
    case.admit("a")
    case.admit("b")
    request, response = case.send("a", {"event": "faint", "key": case.keys["a"]})
    assert case.runtime.rule_state().links[0].status == LinkStatus.DEAD
    commands = {p: case.runtime.journal.pending(p) for p in ("a", "b")}
    assert any(row["cmd"] == "force_faint" for row in commands["b"])
    count = len(case.events)
    assert case.runtime.process(request, case.owners["a"]) == response
    assert len(case.events) == count
    rules = case.runtime.journal.snapshot().state["rules"]
    case.close()
    case.open()
    case.admit("b")
    case.admit("a")
    assert case.runtime.journal.snapshot().state["rules"] == rules
    case.send("a", {"event": "faint", "key": case.keys["a"]}, request["operation_id"])
    assert len(case.events) == count
    assert {p: case.runtime.journal.pending(p) for p in ("a", "b")} == commands


def test_control_requires_explicit_verified_evidence_and_does_not_retire_semantic_events(case):
    case.admit("a")
    case.admit("b")
    assert case.control("a", {"success": True})[1]["control"]["authority"] == "hold"
    proof = {"schema": "explicit-test-host-proof-v1"}
    assert case.control("a", proof)[1]["control"]["authority"] == "hold"
    packet, response = case.control("b", proof)
    assert response["control"]["authority"] == "run" and response["commands"] == []
    with pytest.raises(ProtocolError, match="replay"):
        case.runtime.process(packet, case.owners["b"])


def test_wrong_or_duplicate_connection_cannot_evict_owner(case):
    case.admit("a")
    owner = case.owners["a"]
    before = case.runtime.journal.snapshot()
    with pytest.raises(ProtocolError, match="owning connection"):
        case.runtime.process(case.hello("a"), object())
    assert case.runtime.gate.owns("a", owner) and case.runtime.journal.snapshot() == before
    wrong = case.hello("b")
    wrong["gen1_metadata"]["physical_instance"] = "1" * 32
    with pytest.raises(ProtocolError, match="distinct physical"):
        case.runtime.process(wrong, object())
    assert case.runtime.gate.owns("a", owner) and "b" not in case.runtime.gate.sessions


def test_nested_delivery_retains_every_stored_body_field(case):
    body = {
        "cmd": "fixture_nested_body",
        "player": "b",
        "seq": 42,
        "protocol": "body",
        "operation_id": "inside",
    }
    snap = case.runtime.journal.snapshot()
    case.runtime.journal.commit(
        "a",
        case.token(),
        {"event": "fixture_command"},
        expected_revision=snap.revision,
        state=snap.state,
        commands={"a": [], "b": [body]},
        result={"ack": "ACK"},
    )
    assert case.runtime.delivery_commands("b")[0]["body"] == body


def test_read_only_runtime_facts_report_the_committed_journal_without_mutation(case):
    srv = SLinkServer(data_dir=str(case.path), gen1_runtime=case.runtime)
    case.admit("a")
    case.admit("b")
    before = case.runtime.journal.snapshot()
    facts = srv.read_runtime_facts(now=100)
    rules = srv.read_rule_state()
    assert facts["persistence"]["mode"] == "protocol_journal"
    assert facts["operations"]["durable_events"] and facts["operations"]["durable_commands"]
    assert facts["recovery"]["paired_reconciled"] is False
    assert facts["players"]["b"]["verified_cartridge"]["variant"] == "yellow"
    assert facts["players"]["b"]["feature_gates"]["pc_trade_npc"] is False
    assert rules["source"] == "protocol_journal" and rules["committed_revision"] == before.revision
    rules["document"]["links"].clear()
    assert case.runtime.journal.snapshot() == before


def test_unconfigured_durable_protocol_cannot_fall_through_legacy_tcp(tmp_path):
    async def scenario():
        srv = SLinkServer(data_dir=str(tmp_path))
        before = srv.state.to_document()
        listener = await asyncio.start_server(srv.handle_client, "127.0.0.1", 0)
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", listener.sockets[0].getsockname()[1]
        )
        try:
            writer.write(
                canonical_json(
                    {
                        "protocol": PROTOCOL,
                        "event": "hello",
                        "player": "a",
                        "seq": 0,
                        "operation_id": "1" * 32,
                        "client_nonce": "1" * 32,
                    }
                ).encode()
                + b"\n"
            )
            await writer.drain()
            response = decode_frame(await reader.readline())
            assert (
                response["ack"] == "NACK"
                and response["reason_code"] == "gen1_durable_runtime_unconfigured"
            )
            assert (
                not srv._connection_owners and not srv._last_seq and not srv._gen1_sessions.sessions
            )
            assert srv.state.to_document() == before
        finally:
            writer.close()
            await writer.wait_closed()
            listener.close()
            await listener.wait_closed()

    asyncio.run(scenario())


def test_idle_owned_tcp_connection_expires_without_another_request(case):
    async def scenario():
        listener = await asyncio.start_server(case.runtime.handle_client, "127.0.0.1", 0)
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", listener.sockets[0].getsockname()[1]
        )
        try:
            writer.write(canonical_json(case.hello("a")).encode() + b"\n")
            await writer.drain()
            assert decode_frame(await reader.readline())["ack"] == "ACK"
            notice = await asyncio.wait_for(reader.read(), 3)
            assert not notice or decode_frame(notice)["event"] == "gen1_hold"
            assert not case.runtime.gate.sessions and case.runtime.state().barrier.ticket() is None
        finally:
            writer.close()
            await writer.wait_closed()
            listener.close()
            await listener.wait_closed()

    asyncio.run(scenario())


def test_configured_main_server_tcp_uses_journal_route_and_closes_both_on_disconnect(case):
    async def scenario():
        srv = SLinkServer(data_dir=str(case.path), gen1_runtime=case.runtime, tcp_port=9000)
        srv._dispatch = lambda *args, **kwargs: pytest.fail(
            "durable traffic reached legacy dispatcher"
        )
        listener = await asyncio.start_server(srv.handle_client, "127.0.0.1", 0)
        sockets = {}
        try:
            for p in ("a", "b"):
                reader, writer = await asyncio.open_connection(
                    "127.0.0.1", listener.sockets[0].getsockname()[1]
                )
                sockets[p] = reader, writer
                writer.write(canonical_json(case.hello(p)).encode() + b"\n")
                await writer.drain()
                assert decode_frame(await reader.readline())["commands"] == []
            packet = case.envelope("a", {"event": "faint", "key": case.keys["a"]})
            sockets["a"][1].write(canonical_json(packet).encode() + b"\n")
            await sockets["a"][1].drain()
            response = decode_frame(await sockets["a"][0].readline())
            assert response["ack"] == "ACK" and srv.state.links[0].status == LinkStatus.DEAD
            sockets["a"][1].close()
            await sockets["a"][1].wait_closed()
            notice = decode_frame(await asyncio.wait_for(sockets["b"][0].readline(), 3))
            assert notice["event"] == "gen1_hold" and notice["commands"] == []
            assert not case.runtime.gate.sessions
        finally:
            for _, writer in sockets.values():
                writer.close()
                await writer.wait_closed()
            listener.close()
            await listener.wait_closed()
            for _ in range(40):
                if not case.runtime._writers:
                    break
                await asyncio.sleep(0.01)

    asyncio.run(scenario())


def test_unexpected_domain_exception_nacks_and_revokes_without_partial_rules(case):
    async def scenario():
        listener = await asyncio.start_server(case.runtime.handle_client, "127.0.0.1", 0)
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", listener.sockets[0].getsockname()[1]
        )
        try:
            writer.write(canonical_json(case.hello("a")).encode() + b"\n")
            await writer.drain()
            assert decode_frame(await reader.readline())["ack"] == "ACK"
            before = case.runtime.journal.snapshot().state["rules"]

            def broken(*args):
                raise RuntimeError("injected domain callback failure")

            case.runtime.validate_event = broken
            packet = case.envelope("a", {"event": "faint", "key": case.keys["a"]})
            writer.write(canonical_json(packet).encode() + b"\n")
            await writer.drain()
            assert decode_frame(await reader.readline())["ack"] == "NACK"
            await reader.read()
            assert not case.runtime.gate.sessions
            assert case.runtime.journal.snapshot().state["rules"] == before
        finally:
            writer.close()
            await writer.wait_closed()
            listener.close()
            await listener.wait_closed()

    asyncio.run(scenario())


def test_configured_http_reads_work_and_unbound_launch_writes_refuse(case):
    from aiohttp.test_utils import TestClient, TestServer

    async def scenario():
        srv = SLinkServer(data_dir=str(case.path), gen1_runtime=case.runtime)
        client = TestClient(TestServer(build_app(srv)))
        await client.start_server()
        try:
            before = case.runtime.journal.snapshot()
            assert (await client.get("/api/status")).status == 200
            assert (await client.post("/api/reset", json={})).status == 409
            assert (await client.get("/launcher/a.lua")).status == 400
            assert case.runtime.journal.snapshot() == before
        finally:
            await client.close()

    asyncio.run(scenario())
