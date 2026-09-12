"""replace_rival_team: the Lua sub-executor over the real memory_gb/gen1_rby profile on a fake bus
halted in DelayFrame at trainer-battle init, the server verifier over its evidence, and the
composition through gen1_held_faint.lua under the one-use permit."""
import copy
import json
import secrets
from pathlib import Path

import pytest
from lupa.lua54 import LuaError, LuaRuntime

from server import gen1_held_rival_team as rival
from server.gen1_party_codec import PartyCodec
from server.gen1_run_config import create_runtime
from server.held_write_permit import VerifiedHeldWrite
from server.protocol_journal import JournalError
from tests.unit.test_client_journal import start
from tests.unit.test_client_state_store import runtime  # noqa: F401
from tests.unit.test_gen1_faint_runtime import paired
from tests.unit.test_gen1_party_codec import make_blob
from tests.unit.test_gen1_sessions import contract

ROOT = Path(__file__).resolve().parents[2]
RIVAL = 225
SP = 0xDFF0
BUS = """
    bus={};rom={};regs={PC=64,SP=0xDFF0}
    memory={getmemorydomainlist=function()return {"System Bus","ROM"}end,
        read_u8=function(a,d) if d=="ROM" then return rom[a] or 0 end return bus[a] or 0 end,
        write_u8=function(a,v,d) bus[a]=v%256 end,
        read_u16_le=function(a,d) return (bus[a] or 0)+(bus[a+1] or 0)*256 end,
        write_u16_le=function(a,v,d) bus[a]=v%256;bus[a+1]=math.floor(v/256)%256 end}
    print=function()end;console={log=function()end}
    JSON=require("json_codec")
    function decode(text)return JSON.decode(text)end
    function encode(value)return JSON.encode(value)end
"""


def blobs(variant, n=2, hp=10):
    codec = PartyCodec(variant)
    out = []
    for i in range(n):
        raw = bytearray(make_blob(codec, dv=0x3000 + i))
        raw[1:3] = hp.to_bytes(2, "big")
        out.append(bytes(raw))
    return out


def body(variant, n=2, hp=10, trainer=RIVAL):
    rows = blobs(variant, n, hp)
    command = {"cmd": "replace_rival_team", "trainer_id": trainer, "source_frame": 100, "n": n,
               "blobs_hex": [b.hex().upper() for b in rows], "source": "auto"}
    return command, rows


def arm(g, mem, variant, trainer=RIVAL):
    """ROM anchors, the DelayFrame return word and the battle-init bytes; a canned trainer party of three."""
    p = rival.PROFILES[variant]
    for i, val in enumerate((0xC3, p["vblank_entry"] & 255, p["vblank_entry"] >> 8)):
        g.rom[p["irq_vector"] + i] = val
    for i, val in enumerate((0x3E, 1, 0xE0, p["vblank_flag"] & 255, 0x76, 0xF0, p["vblank_flag"] & 255, 0xA7)):
        g.rom[p["delay_frame"] + i] = val
    resume = p["delay_frame"] + 5
    for addr, val in ((p["is_in_battle"], 2), (p["enemy_mon_party_pos"], 0xFF), (p["enemy_party_count"], 3),
                      (p["cur_opponent"], trainer), (p["link_state"], 0), (p["battle_type"], 0),
                      (p["vblank_flag"], 1), (SP, resume & 255), (SP + 1, resume >> 8)):
        g.bus[addr] = val
    for i in range(3):
        g.bus[mem.ENEMY_SPECIES_LIST_ADDR + i] = i + 1
        for j in range(44):
            g.bus[mem.ENEMY_BASE_ADDR + 44 * i + j] = (i * 44 + j) % 256
    g.bus[mem.ENEMY_SPECIES_LIST_ADDR + 3] = 0xFF


def lua_runtime(variant, trainer=RIVAL):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().root = ROOT.as_posix()
    lua.execute("package.path=root..\"/lua/?.lua;\"..root..\"/data/games/gen1_rby/?.lua;\"..package.path")
    lua.execute(BUS)
    lua.execute("emu={getregister=function(name)return regs[name]end,framecount=function()return 100 end}")
    lua.execute("Mem=dofile(root..\"/lua/memory_gb.lua\");Game=dofile(root..\"/lua/games/gen1_rby.lua\")")
    lua.execute("Mem.initProfile(Game,\"" + variant + "\")")
    lua.execute("Rival=require(\"gen1_held_rival_team\");executor=Rival.new({memory=Mem,variant=\"" + variant + "\"})")
    g = lua.globals()
    arm(g, g.Mem, variant, trainer)
    return lua, g, g.executor


def wire(g, value):
    return g.decode(json.dumps(value))


def plain(g, value):
    return json.loads(g.encode(value))


def bus_snapshot(g):
    return dict(g.bus.items())


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_valid_swap_writes_the_party_and_its_readback_receipt_verifies_on_the_server(variant):
    lua, g, executor = lua_runtime(variant)
    command, rows = body(variant)
    request = wire(g, command)
    assert executor.safe(request)[0] is True
    intent = executor.prepare(request)
    before = plain(g, intent)
    assert before["schema"] == rival.INTENT and before["n"] == 2 and before["trainer_id"] == RIVAL
    assert before["before"]["count"] == 3 and before["before"]["species_list"] == [1, 2, 3, 255]
    state, observed = executor.classify(request, intent)
    assert state == "before" and plain(g, observed) == before["before"]
    executor.apply(request, intent)
    state, observed = executor.classify(request, intent)
    assert state == "after"
    receipt = plain(g, executor.receipt(request, intent, observed))
    assert receipt["schema"] == rival.RECEIPT and receipt["after"]["image_hex"] == rival.expected_image(rows)
    assert receipt["after"]["species_list"] == [rows[0][0], rows[1][0], 255] and receipt["after"]["count"] == 2
    assert rival.verify_rival_team_receipt(command, receipt, variant=variant) == {
        "trainer_id": RIVAL, "n": 2, "species_list": [rows[0][0], rows[1][0]]}
    mem = g.Mem
    for i, raw in enumerate(rows):
        assert bytes(g.bus[mem.ENEMY_BASE_ADDR + 44 * i + j] for j in range(44)) == raw[:44]
        assert bytes(g.bus[mem.ENEMY_OT_NAMES_ADDR + 11 * i + j] for j in range(11)) == raw[44:55]
        assert bytes(g.bus[mem.ENEMY_NICKS_ADDR + 11 * i + j] for j in range(11)) == raw[55:]
    assert g.bus[mem.ENEMY_COUNT_ADDR] == 2 and g.bus[mem.ENEMY_SPECIES_LIST_ADDR + 2] == 0xFF


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_missed_battle_init_window_closes_without_writing(variant):
    lua, g, executor = lua_runtime(variant)
    command, _ = body(variant)
    request = wire(g, command)
    before = bus_snapshot(g)
    g.bus[rival.PROFILES[variant]["enemy_mon_party_pos"]] = 0
    missed = plain(g, executor.prepare(request))
    assert missed["schema"] == "rby-rival-team-missed-intent-v1"
    state, observed = executor.classify(request, wire(g, missed))
    assert state == "after" and plain(g, observed) == missed["observed"]
    receipt = plain(g, executor.receipt(request, wire(g, missed), observed))
    assert receipt["schema"] == rival.MISSED_RECEIPT
    result = rival.verify_rival_team_receipt(command, receipt, variant=variant)
    assert result["missed"] is True and result["trainer_id"] == RIVAL
    assert bus_snapshot(g) == {**before, rival.PROFILES[variant]["enemy_mon_party_pos"]: 0}


@pytest.mark.parametrize("fault", ["short_hex", "non_hex", "bad_species", "no_hp", "seven"])
def test_invalid_payloads_are_refused_before_any_write(fault):
    lua, g, executor = lua_runtime("red")
    command, rows = body("red")
    if fault == "short_hex":
        command["blobs_hex"][1] = command["blobs_hex"][1][:130]
    elif fault == "non_hex":
        command["blobs_hex"][0] = "ZZ" + command["blobs_hex"][0][2:]
    elif fault == "bad_species":
        raw = bytearray(rows[0])
        raw[0] = 0
        command["blobs_hex"][0] = raw.hex().upper()
    elif fault == "no_hp":
        command, rows = body("red", hp=0)
    else:
        command["blobs_hex"] = [b.hex().upper() for b in blobs("red", 7)]
        command["n"] = 7
    before = bus_snapshot(g)
    result = executor.prepare(wire(g, command))
    assert result[0] is None and result[1]
    assert bus_snapshot(g) == before
    with pytest.raises(JournalError):
        rival.validate_party(command, "red")


@pytest.mark.parametrize("fault", [("is_in_battle", 1), ("enemy_mon_party_pos", 0), ("enemy_party_count", 0),
                                   ("enemy_party_count", 7), ("cur_opponent", 242), ("link_state", 4), ("battle_type", 1),
                                   ("vblank_flag", 0), ("PC", 65), ("SP", 0xDEFF), ("resume", 1), ("rom", 1), ("trainer", 200)])
def test_wrong_checkpoint_refuses_the_hold_and_the_capture(fault):
    lua, g, executor = lua_runtime("yellow")
    command, _ = body("yellow")
    request = wire(g, command)
    assert executor.safe(request)[0] is True and executor.checkpoint(request)
    name, value = fault
    p = rival.PROFILES["yellow"]
    if name in ("PC", "SP"):
        g.regs[name] = value
    elif name == "resume":
        g.bus[SP] = (g.bus[SP] + 1) % 256
    elif name == "rom":
        g.rom[p["delay_frame"]] = g.rom[p["delay_frame"]] ^ 1
    elif name == "trainer":
        command["trainer_id"] = value
        request = wire(g, command)
    else:
        g.bus[p[name]] = value
    safe, reason = executor.safe(request)
    assert safe is False and reason
    with pytest.raises(LuaError):
        executor.checkpoint(request)


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_captured_checkpoint_verifies_on_the_server_and_every_byte_is_required(variant):
    lua, g, executor = lua_runtime(variant)
    command, _ = body(variant)
    point = plain(g, executor.checkpoint(wire(g, command)))
    rival.verify_battle_init_checkpoint(point, variant, RIVAL)
    p = rival.PROFILES[variant]
    assert set(point["system"]) == {str(a) for a in (p["is_in_battle"], p["enemy_mon_party_pos"], p["enemy_party_count"],
                                                     p["cur_opponent"], p["link_state"], p["battle_type"], p["vblank_flag"], SP, SP + 1)}
    for domain in ("rom", "system"):
        for key, value in point[domain].items():
            missing = copy.deepcopy(point)
            del missing[domain][key]
            with pytest.raises(JournalError):
                rival.verify_battle_init_checkpoint(missing, variant, RIVAL)
            changed = copy.deepcopy(point)
            changed[domain][key] = 0 if key == str(p["enemy_party_count"]) else (value + 1) % 256
            with pytest.raises(JournalError):
                rival.verify_battle_init_checkpoint(changed, variant, RIVAL)
    with pytest.raises(JournalError):
        rival.verify_battle_init_checkpoint(point, variant, 242)


def test_receipt_with_a_tampered_species_byte_is_refused():
    command, rows = body("red")
    image = rival.expected_image(rows)
    after = {"count": 2, "species_list": [rows[0][0], rows[1][0], 255], "image_hex": image}
    receipt = {"schema": rival.RECEIPT, "trainer_id": RIVAL, "after": after,
               "before": {"count": 3, "species_list": [1, 2, 3, 255], "image_hex": "00" * (67 * 2 + 2)}}
    assert rival.verify_rival_team_receipt(command, receipt, variant="red")["n"] == 2
    for tamper in ("list", "image", "count", "n"):
        bad = copy.deepcopy(receipt)
        cmd = copy.deepcopy(command)
        if tamper == "list":
            bad["after"]["species_list"][1] ^= 1
        elif tamper == "image":
            bad["after"]["image_hex"] = image[:132] + "00" + image[134:]
        elif tamper == "count":
            bad["after"]["count"] = 3
        else:
            cmd["n"] = 3
        with pytest.raises(JournalError):
            rival.verify_rival_team_receipt(cmd, bad, variant="red")


def test_missed_receipt_requires_a_complete_ineligible_window():
    command, _ = body("red")
    p = rival.PROFILES["red"]
    receipt = {"schema": rival.MISSED_RECEIPT, "trainer_id": RIVAL,
               "observed": {"battle": 2, "opponent": RIVAL, "enemy_position": 0, "frame": 123}}
    assert rival.verify_rival_team_receipt(command, receipt, variant="red")["missed"] is True
    for fault in ("missing", "trainer", "frame", "eligible"):
        bad = copy.deepcopy(receipt)
        if fault == "missing":
            del bad["observed"]["opponent"]
        elif fault == "trainer":
            bad["trainer_id"] = 242
        elif fault == "frame":
            bad["observed"]["frame"] = -1
        else:
            bad["observed"] = {"battle": p["trainer_battle"], "opponent": RIVAL,
                               "enemy_position": 0xFF, "frame": 123}
        with pytest.raises(JournalError):
            rival.verify_rival_team_receipt(command, bad, variant="red")


def test_exact_rival_swap_gets_a_held_write_and_faults_are_refused(tmp_path):
    server = create_runtime(tmp_path, contract("red", "red"))
    try:
        paired(server)
        partner = [row["blob"] for row in server.state().rules.partner_blobs["b"]]
        queued = {"cmd": "replace_rival_team", "trainer_id": RIVAL, "n": len(partner),
                  "blobs_hex": [b.hex() for b in partner], "source": "auto"}  # state.queue_rival_team_swap shape
        snapshot = server.journal.snapshot()
        server.journal.commit("a", secrets.token_hex(16), {"event": "rival-swap-fixture"}, expected_revision=snapshot.revision,
                              state=snapshot.state, commands={"a": [queued], "b": []}, result={"ack": "ACK"})
        command = server.journal.command("a", server.journal.pending_ids("a")[0])
        initial = server.state().document()["components"]["gen1-initial-observations"]["a"]
        lua, g, executor = lua_runtime("red")
        request = wire(g, command["body"])
        intent = plain(g, executor.prepare(request))
        point = plain(g, executor.checkpoint(request))
        evidence = {"schema": rival.SCHEMA, "command_id": command["command_id"], "command_sequence": command["command_sequence"],
                    "context_generation": initial["binding"]["context_generation"],
                    "final_sha1": server.contract["players"]["a"]["final_rom_sha1"],
                    "host": {**initial["observation"]["host"], "frame": initial["observation"]["frame"]},
                    "checkpoint": point, "intent": intent, "current": intent["before"]}
        binding = server.gate.sessions["a"].metadata["control_binding"]
        document = server.state().document()
        proof = rival.verify("a", command, evidence, document, binding)
        assert isinstance(proof, VerifiedHeldWrite) and proof.scope["phase"] == "replace_rival_team"
        # The held-write entry point (gen1_run_config verify_operation_execution) dispatches the swap here.
        from server.gen1_held_faint import verify as held_verify
        dispatched = held_verify("a", command, evidence, document, binding)
        assert isinstance(dispatched, VerifiedHeldWrite) and dict(dispatched.scope) == dict(proof.scope)
        executor.apply(request, wire(g, intent))
        after = plain(g, executor.image(request))
        assert after["image_hex"] == rival.expected_image(partner)
        assert isinstance(rival.verify("a", command, {**evidence, "current": after}, document, binding), VerifiedHeldWrite)
        assert rival.verify("a", {**command, "body": {"cmd": "force_faint"}}, evidence, document, binding) is None
        for fault in ("trainer", "checkpoint", "current", "intent", "host", "schema"):
            bad = copy.deepcopy(evidence)
            cmd = copy.deepcopy(command)
            if fault == "trainer":
                cmd["body"]["trainer_id"] = 201
            elif fault == "checkpoint":
                bad["checkpoint"]["system"][str(rival.PROFILES["red"]["enemy_mon_party_pos"])] = 0
            elif fault == "current":
                bad["current"] = {**after, "image_hex": "00" * (67 * len(partner) + 2)}
            elif fault == "intent":
                bad["intent"]["n"] = 6
            elif fault == "host":
                bad["host"]["held"] = False
            else:
                bad["schema"] = "rby-held-faint-evidence-v1"
            with pytest.raises(JournalError):
                rival.verify("a", cmd, bad, document, binding)
            with pytest.raises(JournalError):
                held_verify("a", cmd, bad, document, binding)
    finally:
        server.close()


def test_receipt_policy_settles_the_rival_swap_ack_by_its_readback():
    """The durable dispatcher's receipt callback (gen1_command_receipts.Gen1ReceiptPolicy) verifies the
    swap ACK with verify_rival_team_receipt and raises no rule follow-up: the swap is informational."""
    from types import SimpleNamespace

    from server.gen1_command_receipts import Gen1ReceiptPolicy

    policy = Gen1ReceiptPolicy({"a": "red", "b": "red"})
    command, rows = body("red")
    receipt = {"schema": rival.RECEIPT, "trainer_id": RIVAL,
               "before": {"count": 3, "species_list": [1, 2, 3, 255], "image_hex": "00" * (67 * 2 + 2)},
               "after": {"count": 2, "species_list": [rows[0][0], rows[1][0], 255], "image_hex": rival.expected_image(rows)}}
    journal_command = {"command_id": "a" * 32, "command_sequence": 1, "body": command}

    def ack(value):
        event = {"event": "command_ack", "command_id": "a" * 32, "command_sequence": 1, "outcome": "ACK", "receipt": value}
        return policy("a", journal_command, event, SimpleNamespace(player_identity={}))

    assert ack(receipt) == []
    missed = {"schema": rival.MISSED_RECEIPT, "trainer_id": RIVAL,
              "observed": {"battle": 2, "opponent": RIVAL, "enemy_position": 0, "frame": 123}}
    assert ack(missed) == []
    tampered = copy.deepcopy(receipt)
    tampered["after"]["species_list"][0] ^= 1
    with pytest.raises(JournalError):
        ack(tampered)
    with pytest.raises(JournalError):
        ack({"schema": "gen1-force-faint-receipt-v1", "before": receipt["before"], "after": receipt["after"]})


def test_composed_held_faint_dispatches_the_swap_under_the_one_use_permit(runtime):  # noqa: F811
    """The tests/unit/test_gen1_held_faint_client.py fixture with the real memory module and the
    real sub-executor: armed until the permit, one write, receipt, no second write."""
    lua = runtime
    start(lua)
    command, rows = body("yellow")
    lua.globals().wire_body = json.dumps(command)
    lua.execute("package.path=root..\"/data/games/gen1_rby/?.lua;\"..package.path")
    lua.execute("package.loaded.platform_identity={new_nonce=new_id};now=1;frame=100;held=true")
    lua.execute(BUS)
    lua.execute("emu={framecount=function()return frame end,getregister=function(name)return regs[name]end}")
    lua.execute("gameinfo={getromhash=function()return string.rep(\"e\",40)end}")
    lua.execute("Mem=dofile(root..\"/lua/memory_gb.lua\");Game=dofile(root..\"/lua/games/gen1_rby.lua\");Mem.initProfile(Game,\"yellow\")")
    lua.execute("""
        context={context_generation=string.rep("c",32),save_identity={ot_id="0000",trainer_name="SAME"}}
        body=JSON.decode(wire_body);id=string.rep("a",32)
        local event=assert(journal:append({event="fixture"}))
        assert(journal:accept_response(event,JSON.array({{command_id=id,command_sequence=1,body={cmd=body.cmd,body=body}}})))
        service=require("gen1_held_faint").new({journal=journal,memory=Mem,player="b",variant="yellow",clock=function()return now end,
            owned=function()return context end,
            host={status=function()return {owner_id=string.rep("b",32),capability_id="fixture",process_id=1,physical_stop_verified=held}end}})
        local adapter={}
        for _,name in ipairs({"prepare","classify","receipt"})do adapter[name]=function(wrapped,...)return service.adapter[name](wrapped.body,...)end end
        adapter.apply=function(wrapped,intent,identity)
            assert(service.operations.authorize_apply(wrapped.body,intent,identity,{admitted=true,held=true}))
            return service.adapter.apply(wrapped.body,intent,identity)
        end
        executor=require("command_executor").new(journal,adapter)
        function step()return executor:step(id)end
        function request()
            return JSON.encode(service.operations.request({binding_digest=string.rep("f",64)},{admitted=true,held=true}))
        end
        function grant()
            local value=JSON.decode(request());local proof=journal.store.backend.sha256(assert(require("journal_document").encode(value.evidence)))
            return service.operations.accept(JSON.object({schema="slink-held-write-permit-v1",scope=value.window.scope,
                challenge=value.window.challenge,uses=1,ttl_ms=1000,proof_digest=proof}))
        end
        function ready_unheld()return service.ready(body,nil,{admitted=true,held=false})end
        function next_command()
            local pending=assert(journal:pending_events())[1]
            assert(pending and journal:accept_response(pending.operation_id,JSON.array()))
            id=string.rep("b",32)
            local event=assert(journal:append({event="fixture-next"}))
            assert(journal:accept_response(event,JSON.array({{command_id=id,command_sequence=2,body={cmd=body.cmd,body=body}}})))
            executor=require("command_executor").new(journal,adapter)
        end
    """)
    g = lua.globals()
    arm(g, g.Mem, "yellow")
    # Rival Swap owns a battle-init checkpoint, not the generic overworld party
    # checkpoint used by death/storage writers. The composed free-loop router
    # must request its hold even while that generic predicate is false.
    lua.execute("Mem.isPartyWriteSafe=function()return false end")
    assert lua.execute("return service.pending()") is True
    # Persist a normal in-window intent, but do not grant its permit yet.
    done, result = g.step()
    assert done is False and result["pending"] is True
    g.enemy_pos = rival.PROFILES["yellow"]["enemy_mon_party_pos"]
    lua.execute("bus[enemy_pos]=0")
    assert lua.execute("return service.pending()") is False
    assert g.ready_unheld() is True
    done, result = g.step()
    assert done is True and result["outcome"] == "ACK"
    missed = plain(g, result["receipt"])
    assert rival.verify_rival_team_receipt(command, missed, variant="yellow")["missed"] is True
    g.next_command()
    lua.execute("bus[enemy_pos]=0xFF")
    assert lua.execute("return service.pending()") is True
    done, result = g.step()
    assert done is False and result["pending"] is True and result["evidence"]["schema"] == "rby-held-faint-awaiting-permit-v1"
    assert g.bus[g.Mem.ENEMY_COUNT_ADDR] == 3
    requested = json.loads(g.request())
    assert requested["evidence"]["schema"] == rival.SCHEMA and requested["window"]["scope"]["phase"] == "replace_rival_team"
    rival.verify_battle_init_checkpoint(requested["evidence"]["checkpoint"], "yellow", RIVAL)
    assert requested["evidence"]["current"] == requested["evidence"]["intent"]["before"]
    assert g.grant()[0] is True
    done, result = g.step()
    assert done is True and result["outcome"] == "ACK"
    receipt = plain(g, result["receipt"])
    assert rival.verify_rival_team_receipt(command, receipt, variant="yellow")["n"] == 2
    assert g.bus[g.Mem.ENEMY_COUNT_ADDR] == 2 and g.frame == 100
    assert g.step()[0] is True and g.bus[g.Mem.ENEMY_COUNT_ADDR] == 2


def test_checkpoint_data_artifacts_match_their_generator():
    from tools.gen_gen1_rival_team_checkpoint import LUA, OUTPUT, generate
    encoded, text = generate()
    assert OUTPUT.read_text(encoding="utf-8") == encoded and LUA.read_text(encoding="utf-8") == text
    assert rival.PROFILES["red"] == rival.PROFILES["blue"] and rival.PROFILES["yellow"]["is_in_battle"] == rival.PROFILES["red"]["is_in_battle"] - 1
