import copy
import hashlib
import secrets
from itertools import product

import pytest

from server.gen1_full_save import SYMBOLS, image
from server.gen1_memorial import SCHEMA
from server.gen1_memorial_runtime import (
    COMPONENT,
    EVIDENCE,
    OBSERVE,
    expand_entry,
    verify_operation,
)
from server.gen1_run_config import create_runtime, open_runtime
from server.protocol import digest
from server.protocol_journal import JournalError
from server.state import LinkStatus
from tests.unit.test_gen1_engine_signal_runtime import deliver
from tests.unit.test_gen1_faint_runtime import ack, acknowledgement, paired, signal_batch
from tests.unit.test_gen1_held_faint import checkpoint
from tests.unit.test_gen1_hud_feedback import acknowledge_hud
from tests.unit.test_gen1_memorial import fixture
from tests.unit.test_gen1_sessions import contract


def start(runtime):
    owners = paired(runtime)
    deliver(runtime, "a", owners["a"], signal_batch(runtime, "a"))
    command = runtime.journal.command("b", runtime.journal.pending_ids("b")[0])
    ack(runtime, "b", owners["b"], acknowledgement(runtime, "b", command))
    acknowledge_hud(runtime)  # the transient death/whiteout HUD precedes the memorial reads
    return owners


def observe(runtime, player):
    command = runtime.journal.command(player, runtime.journal.pending_ids(player)[0])
    initial = runtime.state().document()["components"]["gen1-initial-observations"][player]
    variant = runtime.contract["players"][player]["variant"]
    point, _, _ = fixture(variant, count=2, slot=0, initialized=False)
    entries=runtime.state().document()['components'][COMPONENT]['entries'][player]
    fresh_party=point['fields']['party']
    if len(entries)>1:
        point=copy.deepcopy(expand_entry(runtime.journal,entries[-2])['payload']['after'])
        point['fields']['party']=fresh_party
    symbols = SYMBOLS["pokeyellow" if variant == "yellow" else "pokered"]
    main = bytearray.fromhex(point["fields"]["main"])
    index = symbols["wPlayerID"] - symbols["wMainDataStart"]
    main[index : index + 2] = b"\0\0"
    point["fields"]["main"] = main.hex().upper()
    point["fields"]["name"] = initial["observation"]["source"]["fields"]["name"]
    mon = bytearray(runtime.state().rules.partner_blobs[player][0]["blob"])
    mon[1:3] = b"\0\0"
    party = bytearray.fromhex(point["fields"]["party"])
    party[1] = mon[0]
    party[8:52] = mon[:44]
    party[272:283] = mon[44:55]
    party[338:349] = mon[55:]
    point["fields"]["party"] = party.hex().upper()
    if len(entries)==1:point["cart_hex"] = initial["observation"]["source"]["cart_hex"]
    point["cart_hex"] = image(point).hex().upper()
    receipt = {
        "schema": OBSERVE,
        "command_id": command["command_id"],
        "command_sequence": command["command_sequence"],
        "context_generation": initial["binding"]["context_generation"],
        "final_sha1": initial["observation"]["final_sha1"],
        "host": {**initial["observation"]["host"], "frame": initial["observation"]["frame"]},
        "checkpoint": checkpoint(variant),
        "point": point,
    }
    return command, {
        "event": "command_ack",
        "command_id": command["command_id"],
        "command_sequence": command["command_sequence"],
        "outcome": "ACK",
        "receipt": receipt,
    }


def completion(runtime, player):
    command = runtime.journal.command(player, runtime.journal.pending_ids(player)[0])
    payload = runtime.state().document()["components"][COMPONENT]["entries"][player][-1]["payload"]
    raw = bytes.fromhex(payload["after"]["cart_hex"])
    receipt = {
        "schema": SCHEMA,
        "command_id": command["command_id"],
        "command_sequence": command["command_sequence"],
        "body_digest": digest(command["body"]),
        "context_generation": payload["context_generation"],
        "final_sha1": payload["final_sha1"],
        "before_digest": digest(payload["before"]),
        "after": copy.deepcopy(payload["after"]),
        "file": {
            "schema": "slink-saveram-file-v1",
            "path": player + ".sav",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "byte_length": len(raw),
            "host_profile": "bizhawk-2.11.1-gambatte-exclusive-hold-v1",
            "frame": payload["frame"],
            "flushed": True,
            "readback": True,
        },
    }
    return command, {
        "event": "command_ack",
        "command_id": command["command_id"],
        "command_sequence": command["command_sequence"],
        "outcome": "ACK",
        "receipt": receipt,
    }


@pytest.mark.parametrize("variants", list(product(("red", "blue", "yellow"), repeat=2)))
@pytest.mark.parametrize("order", [("a", "b"), ("b", "a")])
def test_both_exact_saved_receipts_close_only_the_death_obligation(tmp_path, variants, order):
    runtime = create_runtime(tmp_path, contract(*variants))
    try:
        owners = start(runtime)
        death_id = next(
            iter(runtime.state().document()["components"]["gen1-faint-settlement"]["deaths"])
        )
        for i, player in enumerate(order):
            _, message = observe(runtime, player)
            ack(runtime, player, owners[player], message)
            command, message = completion(runtime, player)
            initial = runtime.state().document()["components"]["gen1-initial-observations"][player]
            payload = runtime.state().document()["components"][COMPONENT]["entries"][player][-1][
                "payload"
            ]
            evidence = {
                "schema": EVIDENCE,
                "phase": "memorialize",
                "command_id": command["command_id"],
                "command_sequence": command["command_sequence"],
                "context_generation": payload["context_generation"],
                "final_sha1": payload["final_sha1"],
                "host": {**initial["observation"]["host"], "frame": payload["frame"]},
                "checkpoint": checkpoint(variants["ab".index(player)]),
                "intent": {
                    "schema": "rby-memorial-intent-v1",
                    "body_digest": digest(command["body"]),
                },
                "current": payload["before"],
            }
            assert (
                verify_operation(
                    player, command, evidence, runtime.state().document(), initial["binding"]
                ).ttl_ms
                == 1000
            )
            op = secrets.token_hex(16)
            ack(runtime, player, owners[player], message, op)
            state = runtime.journal.snapshot()
            ack(runtime, player, owners[player], message, op)
            assert runtime.journal.snapshot() == state
            stage = runtime.state()
            assert not stage.rules.pending_memorials[player]
            assert (
                stage.rules.party_size[player] == 1 and len(stage.rules.partner_blobs[player]) == 1
            )
            assert (death_id in stage.barrier.document()["blockers"]) == (i == 0)
            assert stage.rules.links[0].status == (
                LinkStatus.DEAD if i == 0 else LinkStatus.MEMORIAL
            )
        assert (
            runtime.state().barrier.ticket() is None
        )  # Other initial/gameplay obligations remain.
    finally:
        runtime.close()
    runtime = open_runtime(tmp_path)
    try:
        assert runtime.state().rules.links[0].status == LinkStatus.MEMORIAL
        assert all(
            expand_entry(runtime.journal,runtime.state().document()["components"][COMPONENT]["entries"][p][-1])["receipt_event"]
            for p in ("a", "b")
        )
    finally:
        runtime.close()


@pytest.mark.parametrize(
    "fault", ["frame", "checkpoint", "alive", "identity", "variant", "unrelated_sram"]
)
def test_bad_observation_preserves_pending_read_and_all_state(tmp_path, fault):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        owners = start(runtime)
        _, message = observe(runtime, "a")
        r = message["receipt"]
        if fault == "frame":
            r["host"]["frame"] += 1
        elif fault == "checkpoint":
            r["checkpoint"]["pc"] += 1
        elif fault == "variant":
            r["point"]["variant"] = "red"
        elif fault == "identity":
            r["point"]["fields"]["name"] = "8050000000000000000000"
        elif fault == "unrelated_sram":
            r["point"]["cart_hex"] = "00" + r["point"]["cart_hex"][2:]
        else:
            raw = bytearray.fromhex(r["point"]["fields"]["party"])
            raw[10] = 10
            r["point"]["fields"]["party"] = raw.hex().upper()
        state = runtime.journal.snapshot()
        with pytest.raises(JournalError):
            ack(runtime, "a", owners["a"], message)
        assert runtime.journal.snapshot() == state
    finally:
        runtime.close()


@pytest.mark.parametrize(
    "fault", ["file", "after", "before", "context", "command", "sequence", "nack"]
)
def test_bad_write_receipt_retains_death_and_prepared_command(tmp_path, fault):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        owners = start(runtime)
        _, msg = observe(runtime, "b")
        ack(runtime, "b", owners["b"], msg)
        _, msg = completion(runtime, "b")
        if fault == "file":
            msg["receipt"]["file"]["readback"] = False
        elif fault == "after":
            msg["receipt"]["after"]["fields"]["tiles"] = "FF"
        elif fault == "before":
            msg["receipt"]["before_digest"] = "0" * 64
        elif fault == "context":
            msg["receipt"]["context_generation"] = "0" * 32
        elif fault == "command":
            msg["receipt"]["command_id"] = "0" * 32
        elif fault == "sequence":
            msg["command_sequence"] += 1
        else:
            msg["outcome"] = "NACK"
        state = runtime.journal.snapshot()
        with pytest.raises(JournalError):
            ack(runtime, "b", owners["b"], msg)
        assert runtime.journal.snapshot() == state
    finally:
        runtime.close()


def test_read_is_renewed_after_an_intervening_queued_physical_command(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        owners = start(runtime)
        old_command, old_read = observe(runtime, "a")
        snapshot = runtime.journal.snapshot()
        runtime.journal.commit(
            "a",
            secrets.token_hex(16),
            {"event": "explicit-intervening-command-fixture"},
            expected_revision=snapshot.revision,
            state=snapshot.state,
            commands={"a": [{"cmd": "force_faint", "key": "fixture-other"}], "b": []},
            result={"ack": "ACK"},
        )
        ack(runtime, "a", owners["a"], old_read)
        assert [c["cmd"] for c in runtime.journal.pending("a")] == [
            "force_faint",
            "memorial_observe",
        ]
        entry = runtime.state().document()["components"][COMPONENT]["entries"]["a"][0]
        assert len(entry["observations"]) == 1 and entry["payload"] is None
        # The intervening kernel itself has separate force-faint coverage. This
        # fixture settles it to exercise the scheduler's subsequent fresh read.
        command = runtime.journal.command("a", runtime.journal.pending_ids("a")[0])
        snapshot = runtime.journal.snapshot()
        runtime.journal.commit(
            "a",
            secrets.token_hex(16),
            {"event": "explicit-intervening-ack-fixture"},
            expected_revision=snapshot.revision,
            state=snapshot.state,
            commands={"a": [], "b": []},
            result={"ack": "ACK"},
            acknowledgements=[
                {
                    "player": "a",
                    "command_id": command["command_id"],
                    "outcome": "ACK",
                    "receipt": {"fixture": True},
                }
            ],
        )
        new_command, new_read = observe(runtime, "a")
        raw = bytearray.fromhex(new_read["receipt"]["point"]["fields"]["party"])
        raw[53:55] = b"\0\0"
        new_read["receipt"]["point"]["fields"]["party"] = raw.hex().upper()
        ack(runtime, "a", owners["a"], new_read)
        entry = runtime.state().document()["components"][COMPONENT]["entries"]["a"][0]
        assert entry["payload"]["before"] == new_read["receipt"]["point"]
        assert entry["payload"]["before"] != old_read["receipt"]["point"]
        assert new_command["command_id"] != old_command["command_id"]
        assert [c["cmd"] for c in runtime.journal.pending("a")] == ["memorialize"]
    finally:
        runtime.close()
    runtime = open_runtime(tmp_path)
    try:
        assert (
            len(
                runtime.state().document()["components"][COMPONENT]["entries"]["a"][0][
                    "observations"
                ]
            )
            == 1
        )
    finally:
        runtime.close()


@pytest.mark.parametrize("phase", ["observation", "apply"])
def test_sql_failure_rolls_back_memorial_state_and_receipt_together(tmp_path, phase):
    import sqlite3

    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        owners = start(runtime)
        _, message = observe(runtime, "a")
        if phase == "apply":
            ack(runtime, "a", owners["a"], message)
            _, message = completion(runtime, "a")
        before = runtime.journal.snapshot()
        operation = secrets.token_hex(16)
        runtime.journal._db.execute(
            "CREATE TRIGGER fail_memorial BEFORE UPDATE OF outcome ON commands BEGIN SELECT RAISE(ABORT,'fixture'); END"
        )
        with pytest.raises(sqlite3.DatabaseError):
            ack(runtime, "a", owners["a"], message, operation)
        assert runtime.journal.snapshot() == before
        assert runtime.journal.command("a", message["command_id"])["outcome"] is None
        runtime.journal._db.execute("DROP TRIGGER fail_memorial")
        assert runtime._failed and not runtime.gate.sessions
        runtime.close()
        runtime=open_runtime(tmp_path)
        instant=runtime.clock();runtime.clock=lambda:instant
        from tests.unit.test_gen1_initial_observation import admit
        owners={p:admit(runtime,p) for p in ('a','b')}
        ack(runtime, "a", owners["a"], message, operation)
        assert runtime.journal.command("a", message["command_id"])["outcome"] == "ACK"
    finally:
        runtime.close()


def test_ten_paired_deaths_keep_active_state_bounded_and_audit_archived_evidence(tmp_path):
    import json

    from server.gen1_memorial_runtime import COMPLETED
    from server.gen1_party_codec import PartyCodec
    from server.gen1_starter_settlement import cache_party, context, mon_info
    from server.identity_registry import IdentityWitness
    from tests.unit.rules_fixture import seed_link_half
    from tests.unit.test_gen1_party_codec import make_blob
    runtime=create_runtime(tmp_path,contract('yellow','yellow'))
    try:
        owners=start(runtime)
        baseline=len(json.dumps(runtime.state().document()))
        for index in range(10):
            if index:
                stage=runtime.state();document=stage.document();initials=document['components']['gen1-initial-observations']
                members=[]
                for player in ('a','b'):
                    mon=PartyCodec('yellow').validate_blob(make_blob(PartyCodec('yellow'),dv=0x2000+index,otid=0))
                    identifier=secrets.token_hex(16)
                    members.append(stage.identities.acquire(identifier,identifier,IdentityWitness(context(initials[player],player),mon.key,mon.sha256,1))['member_id'])
                    seed_link_half(stage.rules,player,'fixture_memorial_'+str(index),mon_info(mon))
                    cache_party(stage.rules,player,mon)
                stage.identities.create_link('b',secrets.token_hex(16),members)
                stage.barrier.set_history(stage.history_digest())
                runtime.journal.commit('a',secrets.token_hex(16),{'event':'explicit-next-pair-growth-fixture','index':index},
                    expected_revision=stage.journal_revision,state=stage.document(),commands={'a':[],'b':[]},result={'ack':'ACK'})
                deliver(runtime,'a',owners['a'],signal_batch(runtime,'a',sequence=index+2,activate=False))
                command=runtime.journal.command('b',runtime.journal.pending_ids('b')[0])
                ack(runtime,'b',owners['b'],acknowledgement(runtime,'b',command))
                acknowledge_hud(runtime)
            for player in ('a','b'):
                _,message=observe(runtime,player);ack(runtime,player,owners[player],message)
                _,message=completion(runtime,player);ack(runtime,player,owners[player],message)
            document=runtime.state().document();component=document['components'][COMPONENT]
            assert all(entry['schema']==COMPLETED for entries in component['entries'].values() for entry in entries)
            assert len(json.dumps(component)) < 12000
            assert len(json.dumps(document)) < baseline+150000
        assert len(document['rules']['memorial']['retired_pairs'])==10
        assert runtime.journal._db.execute('SELECT COUNT(*) FROM records WHERE namespace=?',(COMPONENT,)).fetchone()[0]==20
        reference=document['components'][COMPONENT]['entries']['a'][0]
        record=runtime.journal.record(COMPONENT,reference['record_key'])
        assert record.value['payload']['after']['cart_hex']
        runtime.state()  # Warm the immutable-transform cache before tampering.
        runtime.journal._db.execute('UPDATE records SET digest=? WHERE namespace=? AND record_key=?',('0'*64,COMPONENT,reference['record_key']))
        with pytest.raises(JournalError):runtime.state()
    finally:runtime.close()
