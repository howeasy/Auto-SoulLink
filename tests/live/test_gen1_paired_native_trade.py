"""Real paired native clients and durable coordinator; offer/control are fixtures.

This closes the COMMIT-to-file-to-migration integration slice using the complete
production rule document. Production TCP, native receptionist/partner acceptance
and host reset/rebind remain separate.
"""
import hashlib
import json
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from itertools import product
from pathlib import Path

import pytest

from server.adapters import get_adapter
from server.gen1_native_trade_receipts import verify_native_release, verify_native_trade_receipt
from server.gen1_staged_state import StagedGen1State
from server.gen1_trade_result import TradeResultRules
from server.gen1_trade_rules import Gen1TradeRules
from server.gen1_trade_ui_receipts import verify_partner_prompt, verify_receptionist_offer
from server.gen1_trade_preparation import preparation_payload, verify_preparation
from server.identity_registry import (
    IdentityContext,
    IdentityRegistry,
    IdentityWitness,
    MigrationWitness,
)
from server.protocol_journal import JournalError, ProtocolJournal
from server.save_identity import SaveIdentity
from server.state import AreaStatus, LinkEntry, LinkStatus, MonInfo, SoulLinkState
from server.trade_coordinator import PreparedTrade, TradeCoordinator, TradeVerification
from tests.live.test_gen1_foreground_trade import verify_durable_result
from tests.live.test_gen1_native_trade import trade_cases
from tests.unit.test_trade_coordinator import Policy, Run, context_from
from tools.build_gen1_native_trade import build
from tools.gen1_receptionist_fixture import make_fixture
from tools.run_gb_gate import run_gate

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.live, pytest.mark.slow,
              pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1", reason="explicit live emulator lane required")]


def read_when_ready(path, futures):
    deadline = time.monotonic()+75
    while time.monotonic() < deadline:
        if path.exists():
            return json.loads(path.read_text())
        for future in futures:
            if future.done():
                passed, result, log = future.result()
                raise AssertionError(f"paired emulator exited before {path.name}: {passed}, {result}\n{log}")
        time.sleep(0.05)
    raise AssertionError(f"paired endpoint timed out before {path.name}")


def publish(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    temporary.replace(path)


class PhysicalPolicy(Policy):
    """Real native/file validation; explicit synthetic offer/host authorization."""
    def __init__(self, variants, contexts, artifacts, observed, data_dir):
        super().__init__(variants, contexts)
        self.artifacts = artifacts
        self.rules = {p: TradeResultRules.from_rom(variants[p], (ROOT/artifact["output"]).read_bytes(),
            expected_sha1=artifact["final_sha1"]) for p, artifact in artifacts.items()}
        self.observed = observed
        self.rule_binding = Gen1TradeRules(self.rules, data_dir=data_dir)

    def offer(self, player, payload, state):
        registry = IdentityRegistry.restore(state["identities"], run_id=state["identities"]["run_id"])
        key = self.rules[player].codec.validate_blob(bytes.fromhex(self.observed[player]["snapshot"]["party"][0])).key
        proposal = self.rule_binding.proposal(state["rules"], registry, player=player, key=key,
            contexts=self.contexts, snapshots={p: item["snapshot"] for p, item in self.observed.items()})
        if payload != {"link": proposal.link_id}:
            raise JournalError("offer differs from the rule-selected pair")
        return proposal

    def ready(self, trade, player, command, receipt):
        # The actual endpoint supplied this party/context while waiting for its
        # command. Receptionist/partner/production control are outside this slice.
        super().ready(trade, player, command, receipt)
        own = trade["proposal"]["participants"][player]
        peer = trade["proposal"]["participants"]["b" if player == "a" else "a"]
        incoming = bytes.fromhex(peer["snapshot"]["party"][peer["slot"]])
        species = self.rules[player].outcomes(incoming)[0].blob[0]
        return PreparedTrade(trade["proposal_digest"], own["context"]["context_generation"], own["evidence_digest"],
            {"schema": "rby-native-prepared-v1", "evolved_species": species, "peer_name_hex": "8F84849150505050505050"})

    def applied(self, trade, player, command, receipt):
        verify_native_trade_receipt(command, receipt, rules=self.rules[player], boxed_keys=())
        return receipt

    def verified(self, trade, player, command, receipt):
        if receipt["native"] != trade["applied"][player]:
            raise JournalError("native evidence differs from the applied record")
        readback = verify_native_trade_receipt(command, receipt["native"], rules=self.rules[player], boxed_keys=())
        proof = receipt["file"]
        path = Path(proof["path"]).resolve()
        if not path.is_relative_to(ROOT/"patch/build") or proof["schema"] != "slink-saveram-file-v1":
            raise JournalError("isolated endpoint save-file proof required")
        raw = path.read_bytes()
        if (len(raw) != proof["byte_length"] or hashlib.sha256(raw).hexdigest() != proof["sha256"]
                or proof["flushed"] is not True or proof["readback"] is not True):
            raise JournalError("actual endpoint save-file bytes differ")
        region = self.artifacts[player]["readback"]["save"]
        if raw[region["address"]:region["address"]+region["length"]].hex().upper() != receipt["native"]["after"]["save_region_hex"]:
            raise JournalError("file does not contain the independently verified canonical save")
        own = trade["proposal"]["participants"][player]
        sender = trade["proposal"]["participants"]["b" if player == "a" else "a"]
        witness = MigrationWitness(sender["member_id"], context_from(sender["context"]), sender["key"], sender["evidence_digest"],
            IdentityWitness(context_from(own["context"]), readback.received_key, readback.received_digest, 1))
        return TradeVerification(witness, receipt["native"], proof)

    def finalize(self, rules, trade, migrations):
        return self.rule_binding.finalize(rules, trade, migrations)


class NativeUIPolicy(PhysicalPolicy):
    """Actual receptionist/partner/native/file evidence; host authority is a fixture."""
    def offer(self, player, payload, state):
        key = verify_receptionist_offer(payload, manifest=self.artifacts[player], context=self.contexts[player],
                                       snapshot=self.observed[player]["snapshot"])
        registry = IdentityRegistry.restore(state["identities"], run_id=state["identities"]["run_id"])
        return self.rule_binding.proposal(state["rules"], registry, player=player, key=key,
            contexts=self.contexts, snapshots={p: item["snapshot"] for p, item in self.observed.items()})

    def prompt(self, trade, player):
        return {"schema": "rby-native-prompt-v1", "proposal": trade["proposal"]}

    def decision(self, trade, player, command, receipt):
        return verify_partner_prompt(command, receipt, manifest=self.artifacts[player]), receipt

    def prepare(self, trade, player):
        return preparation_payload(trade, player, rules=self.rules,
            checkpoints={p: item["checkpoint"] for p, item in self.observed.items()})

    def ready(self, trade, player, command, receipt):
        return verify_preparation(command, receipt, rules=self.rules[player])

    def auxiliary(self, trade, player, command, receipt):
        if command["body"]["cmd"] == "native_trade_release":
            return verify_native_release(command, receipt, trade=trade)
        return super().auxiliary(trade, player, command, receipt)


@pytest.mark.parametrize("variants", list(product(("red", "blue", "yellow"), repeat=2)), ids=lambda pair: "-".join(pair))
def test_two_native_clients_commit_save_verify_and_migrate_together(variants):
    run_native_pair(variants)


@pytest.mark.parametrize("variants", list(product(("red", "blue", "yellow"), repeat=2)), ids=lambda pair: "-".join(pair))
def test_native_receptionist_and_partner_decision_feed_both_original_trade_animations(variants):
    run_native_pair(variants, native_ui=True)


@pytest.mark.parametrize("variants", [("red", "blue"), ("blue", "yellow"), ("yellow", "yellow")])
def test_native_release_receipt_failure_recovers_without_repeating_the_trade(variants):
    run_native_pair(variants, native_ui=True, release_receipt_fault=True)


def run_native_pair(variants, *, native_ui=False, companion=False, bounded_host=False,prepared_artifacts=None,party_dex=None,paced_host=False,release_receipt_fault=False):
    assert not paced_host or bounded_host
    directory = Path(tempfile.mkdtemp(prefix="paired-native-", dir=ROOT/".cache"))
    if prepared_artifacts is not None:
        assert native_ui and companion and set(prepared_artifacts)=={"a","b"}
        artifacts=prepared_artifacts
    elif companion:
        from tools.build_gen1_companion import build as companion_build
        built = {variant: companion_build(variant) for variant in set(variants)}
        artifacts = {p:built[v] for p,v in zip(("a","b"),variants,strict=True)}
    else:
        built = {variant: build(variant, foreground=not native_ui, receptionist=native_ui) for variant in set(variants)}
        artifacts = {p:built[v] for p,v in zip(("a","b"),variants,strict=True)}
    players = dict(zip(("a", "b"), variants, strict=True))
    source = (ROOT/"lua/tests/test_gen1_foreground_trade_gate.lua").read_text()
    private_config = None
    if bounded_host:
        from tools.run_gb_gate import BIZHAWK_CONFIG
        config = json.loads(Path(BIZHAWK_CONFIG).read_text(encoding="utf-8-sig"))
        config["Rewind"]["Enabled"] = False
        private_config = directory/"bounded-host.ini"
        private_config.write_text(json.dumps(config))
    jobs = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        for player, variant in players.items():
            case = next(row for row in trade_cases(variant) if row["id"] == "identical-transfer-count1-slot0")
            if party_dex is not None:
                from server.gen1_party_codec import PartyCodec
                from tests.unit.test_gen1_party_codec import make_blob
                codec=PartyCodec(variant)
                species=next(int(key) for key,value in codec.profile["species"].items() if value["dex"]==party_dex)
                blob=make_blob(codec,species=species,level=50).hex().upper()
                case.update(party=[blob],incoming=blob)
            case.update(player=player, paired_directory=directory.as_posix())
            if bounded_host: case["bounded_host"] = True
            if paced_host: case["paced_host"] = True
            if release_receipt_fault: case["release_receipt_fault"] = True
            fixture = None
            if native_ui:
                case.update(native_ui=True, manifest=artifacts[player])
                if player == "a":
                    case["fixture"] = make_fixture(variant, "ViridianPokecenter", directory)
                    fixture = case["fixture"]["fixture"]
            spec, result = directory/f"input-{player}.json", directory/f"result-{player}.json"
            publish(spec, case)
            script = directory/f"paired-{player}.lua"
            gate_name = f"paired_native_{directory.name}_{player}".replace("-", "_")
            script.write_text(source.replace('G.start("test_gen1_foreground_trade_gate")',
                f'G.start("{gate_name}")'), encoding="utf-8")
            jobs.append(pool.submit(run_gate, script.relative_to(ROOT).as_posix(),
                rom_key=variant+("_companion" if companion else "_receptionist_trade" if native_ui else "_foreground_trade"), fixture_override=fixture,
                timeout=180 if bounded_host else 110, quiet=True,
                config_base=str(private_config) if private_config else None,
                cartridge_override={"path":str(ROOT/artifacts[player]["output"]),
                    "sha256":artifacts[player]["companion"]["final_sha256"],"saveram_name":"candidate.SaveRAM"} if prepared_artifacts else None,
                extra_env={"SLINK_NATIVE_SPEC": str(spec), "SLINK_NATIVE_RESULT": str(result)}))
        observed = {p: read_when_ready(directory/f"observed-{p}.json", jobs) for p in players}
        # Reuse only the model driver's event helpers. Its fixture state is not
        # created: bootstrap this test from both actual endpoint observations.
        run = Run.__new__(Run)
        run.path, run.now, run.sequence = directory/"server.sqlite3", int(time.time()*1000), 100
        run.contexts = {p: IdentityContext(p, "gen1_rby", SaveIdentity(v["snapshot"]["save_id"], v["snapshot"]["save_name"]),
            hashlib.sha256(v["final_sha1"].encode()).hexdigest(), v["context_generation"], v["physical_instance"])
            for p, v in observed.items()}
        run_id, contract = "1"*32, "2"*64
        registry = IdentityRegistry(run_id)
        policy_type = NativeUIPolicy if native_ui else PhysicalPolicy
        run.policy = policy_type(players, run.contexts, artifacts, observed, directory)
        members, parties = {}, {}
        for p, value in observed.items():
            registry.bind_context(run.contexts[p])
            mon = run.policy.rules[p].codec.validate_blob(bytes.fromhex(value["snapshot"]["party"][0]))
            members[p] = registry.acquire(run.op(), run.op(), IdentityWitness(run.contexts[p], mon.key, mon.sha256, 1))["member_id"]
            parties[p] = value["snapshot"]["party"]
        run.link = registry.create_link("a", run.op(), list(members.values()))["link_id"]
        rules = SoulLinkState(data_dir=str(directory), adapter=get_adapter("gen1_rby", rom_type=variants[0]), rival_team_swap=True)
        rules.rom_type = variants[0]
        rules.player_identity = {p: {"ot_id": c.save_identity.ot_id, "trainer_name": c.save_identity.trainer_name}
                                 for p, c in run.contexts.items()}
        halves = {}
        for p in players:
            mons = [run.policy.rules[p].codec.validate_blob(bytes.fromhex(raw)) for raw in parties[p]]
            halves[p] = MonInfo(mons[0].key, mons[0].level, mons[0].species_id, observed[p]["nickname"])
            rules.party_keys[p] = {mon.key for mon in mons}
            rules.party_size[p] = len(mons)
            rules.pokeballs_obtained[p] = True
            rules._has_helld.add(p)
            rules._ingest_party_blobs(p, [{"slot": slot, "key": mon.key, "species_id": mon.species_id,
                "level": mon.level, "blob_hex": mon.raw.hex()} for slot, mon in enumerate(mons)])
        pair = LinkEntry("oaks_lab", halves["a"], halves["b"], LinkStatus.ALIVE)
        rules.links.append(pair)
        rules._index_entry(pair)
        rules.area_states = {"oaks_lab": AreaStatus.LINKED, "route_1": AreaStatus.DEAD_ZONE}
        rule_document = StagedGen1State.from_live(rules, {"retired_pairs": []}).document()
        run.journal = ProtocolJournal(run.path, run_id=run_id, contract_hash=contract)
        try:
            run.service = run.coordinator()
            run.journal.bootstrap(TradeCoordinator.initial_state(rule_document, registry.document()))
            original = run.journal.snapshot().state
            if native_ui:
                offer = read_when_ready(directory/"offer.json", jobs)
                response = run.service.handle("a", offer["operation_id"], offer["payload"], owner=run.policy.owners["a"])
                run.tx, run.initiator = response["transaction_id"], "a"
                publish(directory/"offer.json.ack", {"ack": "ACK", "operation_id": offer["operation_id"]})
                prompt = run.command("b", "native_trade_prompt")
                publish(directory/"prompt-b.json", run.service.authorize_delivery("b", prompt["command_id"], owner=run.policy.owners["b"]))
                decision = read_when_ready(directory/"decision.json", jobs)
                run.service.handle("b", decision["operation_id"], decision["payload"], owner=run.policy.owners["b"])
                publish(directory/"decision.json.ack", {"ack": "ACK", "operation_id": decision["operation_id"]})
                ui = {p: read_when_ready(directory/f"ui-closed-{p}.json", jobs) for p in players}
                assert all(value["server_acknowledged"] for value in ui.values())
                run.control("prepare")
                for p in players:
                    command = run.command(p, "native_trade_prepare")
                    publish(directory/f"prepare-{p}.json", run.service.authorize_delivery(
                        p, command["command_id"], owner=run.policy.owners[p]))
                for p in players:
                    path = directory/f"ready-{p}.json"
                    ready = read_when_ready(path, jobs)
                    run.service.handle(p, ready["operation_id"], ready["payload"], owner=run.policy.owners[p])
                    publish(path.with_suffix(".json.ack"), {"ack": "ACK", "operation_id": ready["operation_id"]})
                run.control("commit")
            else:
                run.committed()
            assert run.service.status(run.tx)["phase"] == "commit_persisted"
            for p in players:
                queued = run.command(p, "native_trade_commit")
                command = run.service.authorize_delivery(p, queued["command_id"], owner=run.policy.owners[p])
                publish(directory/f"commit-{p}.json", command)
            native = {p: read_when_ready(directory/f"native-{p}.json", jobs) for p in players}
            assert native["a"]["save_file_receipt"]["path"] != native["b"]["save_file_receipt"]["path"]
            for p in players:
                command = run.command(p, "native_trade_commit")
                if native_ui:
                    assert [packet["payload"]["event"] for packet in native[p]["events"]] == ["trade_applied", "trade_verified"]
                    for index, packet in enumerate(native[p]["events"], 1):
                        event_path = directory/f"native-event-{p}-{index}.json"
                        assert read_when_ready(event_path, jobs) == packet
                        run.service.handle(p, packet["operation_id"], packet["payload"], owner=run.policy.owners[p])
                        publish(event_path.with_suffix(".json.ack"), {"ack": "ACK", "operation_id": packet["operation_id"]})
                else:
                    run.event(p, "trade_applied", command, native[p]["receipt"])
                    run.event(p, "trade_verified", command, {"schema": "rby-file-backed-v1", "native": native[p]["receipt"],
                        "file": native[p]["save_file_receipt"]})
                assert run.journal.snapshot().state["identities"] == original["identities"]
            assert run.service.status(run.tx)["phase"] == "both_verified"
            run.control("finalize")
            final = run.journal.snapshot().state
            assert final["active_trade"] is None
            finished_rules = StagedGen1State.restore(final["rules"], data_dir=str(directory))
            assert finished_rules.links[0].a.nickname == halves["b"].nickname
            assert finished_rules.links[0].b.nickname == halves["a"].nickname
            assert finished_rules.area_states == rules.area_states and finished_rules.rival_team_swap
            for p in players:
                assert [row["blob"].hex().upper() for row in finished_rules.partner_blobs[p]] == native[p]["receipt"]["after"]["party"]["party"]
            for p in players:
                command = run.command(p, "native_trade_release")
                publish(directory/f"release-{p}.json", run.journal.command(p, command["command_id"]))
            if native_ui:
                for p in players:
                    path = directory/f"closure-{p}.json"
                    closure = read_when_ready(path, jobs)
                    run.service.handle(p, closure["operation_id"], closure["payload"], owner=run.policy.owners[p])
                    publish(path.with_suffix(".json.ack"), {"ack": "ACK", "operation_id": closure["operation_id"]})
                assert all(not run.journal.pending_ids(p) for p in players)
            for job in jobs:
                passed, path, log = job.result(timeout=30)
                assert passed, f"{path}\n{log[-6000:]}"
            results = {p: json.loads((directory/f"result-{p}.json").read_text()) for p in players}
            for p, result in results.items():
                verify_durable_result(result, artifacts[p], native[p]["command"] if native_ui else None)
                assert result["counts"]["InternalClockTradeAnim"] == result["counts"]["SavePartyAndDexData"] == 1
                if bounded_host:
                    assert result["bounded_host"]["steps"]>2000 and result["bounded_host"]["host"]["physical_stop_verified"]
                if paced_host:
                    playback=result["playback"]
                    assert playback["paced"] and playback["scheduled"]==result["bounded_host"]["steps"]
                    expected=playback["scheduled"]*playback["frame_rate"]["denominator"]/playback["frame_rate"]["numerator"]
                    assert expected*.95<=playback["elapsed"]<=expected*1.25+2,playback
            publish(directory/"verified.json", {"variants": players, "phase": run.service.status(run.tx)["phase"],
                "native_animations": {p: results[p]["counts"]["InternalClockTradeAnim"] for p in players},
                "save_files": {p: native[p]["save_file_receipt"] for p in players}, "identity_migrated": True,
                "production_runtime": False, "rule_document": "complete StagedGen1State",
                "offer_and_control": "actual native UI; file transport and host control fixtures" if native_ui else "explicit integration fixtures"})
        finally:
            run.journal.close()
