"""Real rules, SQLite and Lua executor composed over controlled RBY memory.

This is component integration across all nine ordered cartridge pairs, not the
production TCP binding, live battle checkpoint or a two-emulator crash test.
"""
import copy
import json
import sqlite3

import pytest

from server.adapters import get_adapter
from server.durable_dispatch import DurableDispatcher
from server.gen1_command_receipts import Gen1ReceiptPolicy
from server.gen1_party_codec import PartyCodec
from server.gen1_staged_state import StagedGen1State
from server.protocol_journal import JournalError, ProtocolJournal
from server.state import AreaStatus, LinkEntry, LinkStatus, MonInfo, SoulLinkState
from tests.unit.test_client_journal import accepted, start
from tests.unit.test_client_state_store import runtime  # noqa: F401
from tests.unit.test_gen1_command_receipts import IDENTITY, bind_memory, command_for
from tests.unit.test_gen1_party_codec import make_blob


def state_for(tmp_path, variants, before):
    state = SoulLinkState(data_dir=str(tmp_path), adapter=get_adapter("gen1_rby", rom_type=variants["a"]))
    state.rom_type = variants["a"]
    own = PartyCodec(variants["a"]).validate_blob(make_blob(PartyCodec(variants["a"]), otid=0x1111, dv=0x2222))
    partner = PartyCodec(variants["b"]).validate_blob(bytes.fromhex(before["party"][0]))
    pair = LinkEntry("route_1", MonInfo(own.key, own.level, own.species_id, "LEFT"),
                     MonInfo(partner.key, partner.level, partner.species_id, "RIGHT"), LinkStatus.ALIVE)
    state.links.append(pair)
    state._index_entry(pair)
    state.area_states["route_1"] = AreaStatus.LINKED
    state.party_keys = {"a": {own.key}, "b": {command_for(before, i)["key"] for i in range(3)}}
    state.party_size = {"a": 1, "b": 3}
    state.player_identity = {"a": {"ot_id": "1111", "trainer_name": "LEFT"}, "b": dict(IDENTITY)}
    state.pokeballs_obtained = {"a": True, "b": True}
    state._has_helld = {"a", "b"}
    state._ingest_party_blobs("a", [{"slot": 0, "key": own.key, "blob_hex": own.raw.hex()}])
    state._ingest_party_blobs("b", [{"slot": i, "key": command_for(before, i)["key"], "blob_hex": blob}
                                  for i, blob in enumerate(before["party"])])
    return state, own.key, partner.key


def command_batch(journal):
    return [{"command_id": c["command_id"], "command_sequence": c["command_sequence"],
             "body": {key: value for key, value in c.items() if key not in ("command_id", "command_sequence")}}
            for c in journal.pending("b")]


@pytest.mark.parametrize("left", ["red", "blue", "yellow"])
@pytest.mark.parametrize("right", ["red", "blue", "yellow"])
@pytest.mark.parametrize("failure", ["before", "after"])
def test_receiver_variant_physical_recovery_and_atomic_receipt_across_server_restart(
        runtime, tmp_path, left, right, failure):  # noqa: F811
    lua = runtime
    start(lua)
    before = bind_memory(lua, right)
    variants = {"a": left, "b": right}
    state, a_key, b_key = state_for(tmp_path, variants, before)
    journal_path = tmp_path / "journal.sqlite3"
    def open_server():
        journal = ProtocolJournal(journal_path, contract_hash="c" * 64)
        journal.bootstrap(StagedGen1State.from_live(state, {"retired_pairs": []}).document())
        def event_policy(player, event, staged):
            if player not in variants or event.get("event") not in ("tick", "faint"):
                raise JournalError("component event policy refused")
            if event["event"] == "faint" and (player != "a" or event.get("key") != a_key):
                raise JournalError("unexpected originating faint")
        dispatcher = DurableDispatcher(journal, data_dir=tmp_path, staged_type=StagedGen1State,
                                       validate_event=event_policy, validate_receipt=Gen1ReceiptPolicy(variants))
        return journal, dispatcher
    journal, dispatcher = open_server()
    try:
        originating = {"event": "faint", "key": a_key}
        dispatcher.dispatch("a", "f" * 32, originating)
        assert dispatcher.state().links[0].status == LinkStatus.DEAD
        poll = lua.globals().append('{"event":"tick"}')
        dispatcher.dispatch("b", poll, {"event": "tick"})
        assert accepted(lua.globals().accept(poll, json.dumps(command_batch(journal))))
        physical = next(c for c in journal.pending("b") if c["cmd"] == "force_faint")
        assert physical["key"] == b_key
        lua.globals().command_id = physical["command_id"]
        lua.globals().fail_at = failure
        lua.execute("""
            local native=M.forceFaint
            M.forceFaint=function(slot)
                if fail_at=='before' then error('before native write') end
                local result=native(slot)
                if fail_at=='after' then error('after native write') end
                return result
            end
            adapter=require('gen1_force_faint_executor').new(M,variant,{ot_id='F00D',trainer_name='ASH'},
                function()return true end) -- controlled memory; no live checkpoint assertion
            Executor=require('command_executor');executor=Executor.new(journal,adapter)
            function run()return executor:step(command_id)end
        """)
        assert lua.globals().run()[0] is False
        run_id = journal.run_id
        journal.close()
        lua.globals().reopen()
        lua.globals().fail_at = None
        lua.execute("executor=Executor.new(journal,adapter)")
        journal, dispatcher = open_server()
        assert journal.run_id == run_id and dispatcher.dispatch("a", "f" * 32, originating).replayed
        assert journal.command("b", physical["command_id"])["outcome"] is None
        assert lua.globals().run()[0] is True
        assert lua.globals().physical_writes == 4
        client_state = json.loads(lua.globals().disk)["document"]["payload"]
        ack = client_state["outbox"][0]
        revision = journal.snapshot().revision
        corrupted = copy.deepcopy(ack["payload"])
        corrupted["receipt"]["after"]["battle_hp"] = 10
        with pytest.raises(JournalError):
            dispatcher.dispatch("b", ack["operation_id"], corrupted)
        assert journal.snapshot().revision == revision
        assert journal.command("b", physical["command_id"])["outcome"] is None
        journal._db.execute("CREATE TEMP TRIGGER fail_ack BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'injected');END")
        with pytest.raises(sqlite3.IntegrityError):
            dispatcher.dispatch("b", ack["operation_id"], ack["payload"])
        assert journal.snapshot().revision == revision
        assert journal.command("b", physical["command_id"])["outcome"] is None
        journal._db.execute("DROP TRIGGER fail_ack")
        dispatcher.dispatch("b", ack["operation_id"], ack["payload"])
        remaining = journal.pending("b")
        journal.close()
        journal, dispatcher = open_server()
        assert journal.command("b", physical["command_id"])["outcome"] == "ACK"
        assert dispatcher.dispatch("b", ack["operation_id"], ack["payload"]).replayed
        assert journal.pending("b") == remaining
        assert accepted(lua.globals().accept(ack["operation_id"], json.dumps(command_batch(journal))))
        assert all(entry.command_id != physical["command_id"]
                   for entry in lua.globals().journal.pending_commands(lua.globals().journal).values())
        assert lua.globals().physical_writes == 4
        assert not (tmp_path / "links.json").exists()
    finally:
        journal.close()
