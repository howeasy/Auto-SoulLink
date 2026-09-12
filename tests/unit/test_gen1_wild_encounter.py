"""Source-shaped encounter facts plus real staged rules and atomic journal handlers."""

import copy
import json
import secrets
import subprocess
import sys
from itertools import product
from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime

from server import gen1_wild_encounter_runtime as wild
from server.gen1_capture_receipt import DATA as CAPTURE_DATA, SCHEMA as CAPTURE_SCHEMA
from server.gen1_run_config import create_runtime, open_runtime
from server.gen1_runtime_state import Gen1RuntimeState
from server.gen1_wild_encounter_receipt import DATA, SCHEMA, validate
from server.protocol_journal import JournalError
from tests.unit.test_gen1_acquisition_runtime import checkpoint, observe as acquire
from tests.unit.test_gen1_capture_receipt import receipt as capture_fixture
from tests.unit.test_gen1_engine_signal_runtime import deliver as engine, payload as engine_payload
from tests.unit.test_gen1_faint_runtime import bag
from tests.unit.test_gen1_initial_observation import admit, observation, send
from tests.unit.test_gen1_sessions import contract

ROOT = Path(__file__).resolve().parents[2]


def receipt(variant="yellow", kind="begin", frame=130, **changes):
    profile = DATA["titles"][variant]
    site = profile["sites"][kind]
    point = {
        "map_id": 33,
        "cur_opponent": 0,
        "species_index": 84,
        "level": 7,
        "battle_flag": 1,
        "battle_type": 0,
        "battle_result": 2,
        "link_state": 0,
        "bag_hex": (bytes((1, 4, 5, 255)) + bytes(38)).hex().upper(),
        "trainer_hex": "92808C8450000000000000",
        "player_id_hex": "0000",
    }
    point.update(changes)
    return {
        "schema": SCHEMA,
        "source_sha256": DATA["sha256"],
        "variant": variant,
        "context_generation": "a" * 32,
        "physical_instance": "1" * 32,
        "final_sha1": "f" * 40,
        "kind": kind,
        "witness": {
            "frame": frame,
            "pc": site["address"],
            "bank": site["bank"],
            "sp": 0xDFF0,
            "point": point,
        },
    }


def decoded(value):
    return validate(
        value,
        variant=value["variant"],
        identity={"ot_id": "0000", "trainer_name": "SAME"},
        context_generation="a" * 32,
        physical_instance="1" * 32,
        final_sha1="f" * 40,
    )


@pytest.mark.parametrize(
    "variant,kind,battle_type", product(("red", "blue", "yellow"), ("begin", "end"), (0, 2))
)
def test_normal_and_safari_boundaries_use_the_actual_source_species_and_level(
    variant, kind, battle_type
):
    fact = decoded(receipt(variant, kind, battle_type=battle_type))
    assert fact["kind"] == "wild_" + kind and fact["exclusion"] is None
    assert (fact["species_id"], fact["level"], fact["frame"]) == (25, 7, 130)


@pytest.mark.parametrize("variant", ("red", "blue", "yellow"))
@pytest.mark.parametrize(
    "point,reason",
    [
        ({"battle_type": 1}, "tutorial_or_scripted_battle_type"),
        ({"battle_type": 4}, "tutorial_or_scripted_battle_type"),
        ({"map_id": 0x90}, "unidentified_ghost"),
        ({"map_id": 0x93, "cur_opponent": 33, "bag_hex": "014801FF" + "00" * 38}, "ghost_marowak"),
    ],
)
def test_uncatchable_tutorial_oak_and_ghost_encounters_are_excluded(variant, point, reason):
    assert decoded(receipt(variant, **point))["exclusion"] == reason


def test_identified_random_tower_encounter_is_allowed():
    assert (
        decoded(receipt(map_id=0x93, cur_opponent=0, bag_hex="014801FF" + "00" * 38))["exclusion"]
        is None
    )


@pytest.mark.parametrize("field,value", [("pc", 0), ("bank", 255), ("frame", True), ("sp", 0)])
def test_foreign_or_malformed_boundary_refuses(field, value):
    raw = receipt()
    raw["witness"][field] = value
    with pytest.raises(JournalError):
        decoded(raw)


@pytest.fixture
def runtime(tmp_path):
    value = create_runtime(tmp_path, contract("yellow", "yellow"))
    now = value.clock()
    value.clock = lambda: now
    value.test_owners = {}
    value.test_initials = {}
    value.test_operations = {}
    for player in ("a", "b"):
        owner = admit(value, player)
        initial = observation(value, player)
        op = secrets.token_hex(16)
        send(value, player, owner, initial, op)
        value.test_owners[player] = owner
        value.test_initials[player] = initial
        value.test_operations[player] = op
    yield value
    value.close()


def activate(runtime, player="a"):
    payload = engine_payload(runtime, player, [], 1)
    payload["signals"] = [bag("yellow")]
    engine(runtime, player, runtime.test_owners[player], payload)


def row(runtime, player, kind, frame, **point):
    raw = receipt(runtime.contract["players"][player]["variant"], kind, frame, **point)
    raw.update(
        context_generation=player * 32,
        physical_instance=("1" if player == "a" else "2") * 32,
        final_sha1=runtime.contract["players"][player]["final_rom_sha1"],
    )
    return {"kind": "wild_" + kind, "receipt": raw}


def capture(runtime, player, where="party"):
    variant = runtime.contract["players"][player]["variant"]
    raw = capture_fixture(variant, destination=where, party_count=0)
    for position, frame in (("begin", 140), ("end", 150)):
        raw[position]["frame"] = frame
        raw[position]["point"]["player_id_hex"] = "0000"
    field = "party_hex" if where == "party" else "box_hex"
    raw_mon = bytearray.fromhex(raw["end"]["point"][field])
    offset = 20 if where == "party" else 34
    raw_mon[offset : offset + 2] = bytes(2)
    raw["end"]["point"][field] = raw_mon.hex().upper()
    return {
        "kind": "capture",
        "receipt": {
            "schema": CAPTURE_SCHEMA,
            "source_sha256": CAPTURE_DATA["sha256"],
            "variant": variant,
            "context_generation": player * 32,
            "final_sha1": runtime.contract["players"][player]["final_rom_sha1"],
            "receipt": raw,
        },
    }


def record(runtime, player, rows, sequence=1, operation=None):
    message = {
        "event": wild.EVENT,
        "payload": {"schema": wild.SCHEMA, "sequence": sequence, "receipts": rows},
    }
    op = operation or secrets.token_hex(16)
    result = wild.record(runtime, player, op, message)
    wild.verify_journal(runtime.journal, runtime.state())
    return result, op, message


def encounters(runtime, player="a"):
    return runtime.state().document()["components"][wild.COMPONENT]["players"][player]["encounters"]


def test_successful_capture_suppresses_no_catch_before_inventory_and_identity_settle(runtime):
    activate(runtime)
    record(runtime, "a", [row(runtime, "a", "begin", 130)])
    caught = capture(runtime, "a")
    acquire(runtime, "a", [caught], 1)
    record(runtime, "a", [caught], 2)
    result, op, message = record(runtime, "a", [row(runtime, "a", "end", 160)], 3)
    state = runtime.state().document()
    assert len(state["components"][wild.ACQUISITIONS]["a"]["pending"]) == 1
    assert not state["identities"]["acquisitions"]
    assert next(iter(encounters(runtime).values()))["phase"] == "captured"
    before = runtime.journal.snapshot()
    assert wild.record(runtime, "a", op, message) == result and runtime.journal.snapshot() == before
    directory = runtime.data_dir if hasattr(runtime, "data_dir") else None
    assert directory is not None


@pytest.mark.parametrize("activated,outcome", [(False, "ball_gate"), (True, "dead_zone")])
def test_flee_or_ko_closes_exact_encounter_with_ball_gate_and_no_legacy_writes(
    runtime, activated, outcome
):
    if activated:
        activate(runtime)
    record(runtime, "a", [row(runtime, "a", "begin", 130), row(runtime, "a", "end", 160)])
    resolved = next(iter(encounters(runtime).values()))
    assert resolved["decision"]["outcome"] == outcome
    assert not runtime.journal.pending_ids("a") and not runtime.journal.pending_ids("b")
    assert not runtime.state().document()["components"][wild.COMPONENT]["obligations"]


def test_end_without_begin_and_second_begin_roll_back_atomically(runtime):
    before = runtime.journal.snapshot()
    with pytest.raises(JournalError, match="observed begin"):
        record(runtime, "a", [row(runtime, "a", "end", 160)])
    assert runtime.journal.snapshot() == before
    record(runtime, "a", [row(runtime, "a", "begin", 130)])
    before = runtime.journal.snapshot()
    with pytest.raises(JournalError, match="prior end"):
        record(runtime, "a", [row(runtime, "a", "begin", 150)], 2)
    assert runtime.journal.snapshot() == before


def test_same_frame_capture_wins_even_when_bundle_lists_end_first(runtime):
    activate(runtime)
    caught = capture(runtime, "a")
    caught["receipt"]["receipt"]["end"]["frame"] = 160
    record(runtime, "a", [row(runtime, "a", "begin", 130), row(runtime, "a", "end", 160), caught])
    assert next(iter(encounters(runtime).values()))["phase"] == "captured"


def test_peer_capture_pending_identity_defers_until_real_stable_settlement_then_schedules_retirement(
    runtime,
):
    activate(runtime)
    caught = capture(runtime, "b")
    acquire(runtime, "b", [caught], 1)
    record(runtime, "a", [row(runtime, "a", "begin", 130), row(runtime, "a", "end", 160)])
    assert next(iter(encounters(runtime).values()))["phase"] == "awaiting_peer"
    assert not runtime.journal.pending_ids("b")
    checkpoint(
        runtime,
        "b",
        runtime.test_owners["b"],
        runtime.test_initials["b"],
        runtime.test_operations["b"],
        caught["receipt"]["receipt"]["end"]["point"]["party_hex"],
        frame=170,
    )
    acquire(runtime, "b", [], 2)
    record(runtime, "b", [])
    resolved = next(iter(encounters(runtime).values()))
    assert resolved["decision"]["outcome"] == "dead_zone" and resolved["retirement_id"]
    document = runtime.state().document()
    obligation = document["components"][wild.COMPONENT]["obligations"][resolved["retirement_id"]]
    source = wild.retirement_source(document, "b", resolved["retirement_id"])
    assert source["reason"] == "paired_no_catch" and obligation["phase"] == "pending"
    commands = [runtime.journal.command("b", key) for key in runtime.journal.pending_ids("b")]
    assert len(commands) == 1 and commands[0]["body"]["cmd"] == "retirement_observe"
    assert commands[0]["body"]["key"] == source["key"]
    assert runtime.state().barrier.document()["blockers"][source["hold_id"]] == wild.REASON
    assert not runtime.state().rules.pending_captures


def test_dead_zone_retirement_reports_memorialize_done_and_the_pair_reaches_memorial(runtime):
    from server.gen1_engine_bridge import memorial_completion
    from server.gen1_full_save import image
    from server.gen1_party_codec import PartyCodec
    from server.gen1_retirement_runtime import acknowledge
    from server.state import LinkStatus
    from tests.unit.test_gen1_inventory_observation import party_point
    from tests.unit.test_gen1_party_codec import make_blob
    from tests.unit.test_gen1_retirement_runtime import observed, written

    activate(runtime)
    caught = capture(runtime, "b")
    acquire(runtime, "b", [caught], 1)
    record(runtime, "a", [row(runtime, "a", "begin", 130), row(runtime, "a", "end", 160)])
    checkpoint(
        runtime,
        "b",
        runtime.test_owners["b"],
        runtime.test_initials["b"],
        runtime.test_operations["b"],
        caught["receipt"]["receipt"]["end"]["point"]["party_hex"],
        frame=170,
    )
    acquire(runtime, "b", [], 2)
    record(runtime, "b", [])
    obligation_id = next(iter(encounters(runtime).values()))["retirement_id"]
    state = runtime.state()
    key = state.document()["components"][wild.COMPONENT]["obligations"][obligation_id]["key"]
    link = state.rules.find_link("b", key)
    # The engine booked the burial of the retired catch (Gen 3 buries it); it stays booked until
    # the retirement job's verified archive reports it.
    assert link.status == LinkStatus.DEAD and link.a is None and state.rules.pending_memorials["b"] == {key}
    # The read finds the catch beside a second party member, so the archive kernel applies.
    _, read = observed(runtime, "b")
    point = read["receipt"]["point"]
    party = bytes.fromhex(point["fields"]["party"])
    filler = make_blob(PartyCodec("yellow"), dv=0x7654, otid=0)
    blobs = [party[8:52] + party[272:283] + party[338:349], filler]
    point["fields"]["party"] = party_point("yellow", blobs)["fields"]["party"]
    point["cart_hex"] = image(point).hex().upper()
    acknowledge(runtime, "b", secrets.token_hex(16), read)
    _, write = written(runtime, "b")
    acknowledge(runtime, "b", secrets.token_hex(16), write)
    state = runtime.state()
    document = state.document()
    obligation = document["components"][wild.COMPONENT]["obligations"][obligation_id]
    assert obligation["phase"] == "complete" and obligation_id not in state.barrier.document()["blockers"]
    link = state.rules.find_link("b", key)
    assert link.status == LinkStatus.MEMORIAL and link.cause == "dead_zone" and link.a is None
    assert not state.rules.pending_memorials["b"] and key not in state.rules.party_keys["b"]
    assert document["rules"]["memorial"]["retired_pairs"][-1]["area_id"] == link.area_id
    assert not runtime.journal.pending_ids("b") and not runtime.journal.pending_ids("a")
    with pytest.raises(JournalError, match="pending memorial obligation"):
        memorial_completion(state.rules, "b", key)  # exactly one completion per retired key
    wild.verify_state(state)
    wild.verify_journal(runtime.journal, state)
    directory = runtime.data_dir
    runtime.close()
    reopened = open_runtime(directory)
    try:
        assert reopened.state().rules.find_link("b", key).status == LinkStatus.MEMORIAL
    finally:
        reopened.close()


def test_own_pending_source_from_prior_encounter_prevents_false_no_catch(runtime):
    activate(runtime)
    acquire(runtime, "a", [capture(runtime, "a")], 1)
    record(runtime, "a", [row(runtime, "a", "begin", 170), row(runtime, "a", "end", 180)])
    assert (
        next(iter(encounters(runtime).values()))["decision"]["outcome"] == "already_captured_source"
    )


@pytest.mark.parametrize("species_lock,outcome", [(False, "dead_zone"), (True, "species_clause")])
def test_settled_boxed_counterpart_participates_in_the_same_clause_and_retirement_policy(
    runtime, species_lock, outcome
):
    from server.gen1_faint_runtime import synchronize
    from server.gen1_full_save import SYMBOLS
    from tests.unit.test_gen1_inventory_observation import deliver as inventory_event

    activate(runtime)
    state = runtime.state()
    document = state.document()
    state.rules.species_lock = species_lock
    synchronize(state, document)
    runtime.journal.commit(
        "a",
        secrets.token_hex(16),
        {"event": "explicit-species-policy-fixture"},
        expected_revision=state.journal_revision,
        state=document,
        commands={"a": [], "b": []},
        result={"ack": "ACK"},
    )
    caught = capture(runtime, "b", "box")
    acquire(runtime, "b", [caught], 1)
    point = copy.deepcopy(runtime.test_initials["b"])
    point["frame"] = 170
    for field, name in [("party_hex", "party"), ("box_hex", "box")]:
        point["source"]["fields"][name] = caught["receipt"]["receipt"]["end"]["point"][field]
    syms = SYMBOLS["pokeyellow"]
    main = bytearray.fromhex(point["source"]["fields"]["main"])
    main[syms["wCurrentBoxNum"] - syms["wMainDataStart"]] = 3
    point["source"]["fields"]["main"] = main.hex().upper()
    inventory_event(
        runtime,
        "b",
        runtime.test_owners["b"],
        {
            "sequence": 1,
            "previous_operation_id": runtime.test_operations["b"],
            "observation": point,
        },
    )
    acquire(runtime, "b", [], 2)
    assert (
        runtime.state().document()["components"][wild.ACQUISITIONS]["b"]["settled"][0]["rule"]
        == "clause_checked"
    )
    # The production boxed acquisition policy now retains the actual counterpart
    # under its original area; usability still belongs to storage disposition.
    from server.adapters.gen1_rby import _MAP_ID_TO_AREA
    assert runtime.state().rules.pending_captures[_MAP_ID_TO_AREA[33]]['b'].key
    record(runtime, "a", [row(runtime, "a", "begin", 180), row(runtime, "a", "end", 200)])
    resolved = next(iter(encounters(runtime).values()))
    assert resolved["decision"]["outcome"] == outcome
    assert bool(resolved["retirement_id"]) == (outcome == "dead_zone")
    if outcome == "dead_zone":
        command = runtime.journal.command("b", runtime.journal.pending_ids("b")[0])
        assert command["body"]["cmd"] == "retirement_observe"


def test_checked_wild_history_survives_reopen_with_no_new_rule_or_command(runtime):
    activate(runtime)
    record(runtime, "a", [row(runtime, "a", "begin", 130), row(runtime, "a", "end", 160)])
    before = runtime.journal.snapshot()
    directory = runtime.data_dir
    runtime.close()
    reopened = open_runtime(directory)
    try:
        wild.verify_journal(reopened.journal, reopened.state())
        assert (
            reopened.journal.snapshot().state["components"][wild.COMPONENT]
            == before.state["components"][wild.COMPONENT]
        )
        assert not reopened.journal.pending_ids("a") and not reopened.journal.pending_ids("b")
    finally:
        reopened.close()


@pytest.mark.parametrize(
    "fault", ["players", "row", "begin", "capture_list", "source_index", "kind"]
)
def test_malformed_retained_lifecycle_refuses_with_journal_error(runtime, fault):
    record(runtime, "a", [row(runtime, "a", "begin", 130)])
    document = copy.deepcopy(runtime.journal.snapshot().state)
    component = document["components"][wild.COMPONENT]
    values = component["players"]["a"]["encounters"]
    key = next(iter(values))
    current = values[key]
    if fault == "players":
        component["players"] = None
    elif fault == "row":
        values[key] = None
    elif fault == "begin":
        current["begin"] = None
    elif fault == "capture_list":
        current["captures"] = None
    elif fault == "source_index":
        current["begin"]["source_ref"]["index"] = True
    else:
        current["begin"]["kind"] = "foreign"
    with pytest.raises(JournalError):
        staged = Gen1RuntimeState(document, data_dir=runtime.data_dir)
        wild.verify_state(staged)


def test_deleted_raw_source_event_cannot_leave_a_valid_rehashed_component(runtime):
    _, op, _ = record(runtime, "a", [row(runtime, "a", "begin", 130)])
    runtime.journal._db.execute("DELETE FROM events WHERE player=? AND operation_id=?", ("a", op))
    with pytest.raises(JournalError, match="missing"):
        wild.verify_journal(runtime.journal, runtime.state())


def test_generated_sites_reproduce_pinned_original_sources():
    result = subprocess.run(
        [sys.executable, "tools/gen_gen1_wild_encounter_sites.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_real_observer_is_readonly_and_keeps_receipts_until_durable_ack():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().root = ROOT.as_posix()
    lua.globals().raw_json = json.dumps(receipt())
    lua.execute("""
        package.path=root..'/lua/?.lua;'..root..'/data/games/gen1_rby/?.lua;'..package.path
        JSON=require('json_codec');Data=require('gen1_wild_encounter_sites');p=Data.titles.yellow
        bus={};rom={};hooks={};removed=0;frame=130;pc=p.sites.begin.address
        function put(a,hex,domain)for i=1,#hex,2 do (domain=='ROM'and rom or bus)[a+(i-1)/2]=tonumber(hex:sub(i,i+1),16)end end
        memory={read_u8=function(a,d)return (d=='ROM'and rom or bus)[a]or 0 end,write_u8=function()error('observer wrote')end}
        gameinfo={getromhash=function()return string.rep('f',40)end}
        emu={framecount=function()return frame end,getregister=function(n)return n=='PC'and pc or 0xDFF0 end}
        event={on_bus_exec=function(fn,a,name)hooks[name]=fn;return name end,unregisterbyid=function(id)hooks[id]=nil;removed=removed+1 end}
        for _,site in pairs(p.sites)do put(site.rom_offset,site.expected_hex,'ROM');put(site.address,site.expected_hex)end
        local raw=JSON.decode(raw_json);local q=raw.witness.point
        for field,name in pairs({map_id='wCurMap',cur_opponent='wCurOpponent',species_index='wEnemyMonSpecies2',level='wCurEnemyLevel',
            battle_flag='wIsInBattle',battle_type='wBattleType',battle_result='wBattleResult',link_state='wLinkState'})do bus[p.addresses[name]]=q[field]end
        put(p.addresses.wPlayerName,q.trainer_hex);put(p.addresses.wPlayerID,q.player_id_hex);put(p.addresses.wNumBagItems,q.bag_hex)
        observer=require('gen1_wild_encounter_observer').new({variant='yellow',final_sha1=string.rep('f',40),held=function()return true end,
            owned=function()return {context_generation=string.rep('a',32),physical_instance=string.rep('1',32)}end})
        bus[p.addresses.hLoadedROMBank]=p.sites.begin.bank;hooks['slink-wild-encounter-begin']()
        assert(observer.status().pending==1);assert(#observer.peek()==1 and observer.status().pending==1)
        assert(observer.acknowledge(observer.peek()));assert(observer.status().pending==0)
        bus[p.addresses.wBattleType]=4;hooks['slink-wild-encounter-begin']();assert(observer.status().pending==0)
        observer.close();assert(removed==2 and next(hooks)==nil)
    """)
