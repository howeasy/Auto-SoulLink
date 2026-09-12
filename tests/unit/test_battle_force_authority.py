"""Battle instruction authority: source pins, generic envelope, R/B/Y decision, and the Lua executor.

No emulator runs. The Lua executor is driven against a stubbed bus/registers/hook table the same
way the grant observer is; the server verifies the evidence the executor produced. The hook-frame
convention is unknown until measured live, so these tests pass the offset explicitly where a
reached row must settle, and prove the default refuses (fail-safe).
"""
import json

import pytest

from server import battle_force_authority as auth, instruction_authority as generic
from server.protocol_journal import JournalError
from tests.unit.test_battle_force_window_analysis import census, local, pinned, rom_at  # noqa: F401
from tests.unit.test_client_state_store import runtime  # noqa: F401

VARIANTS = ("red", "blue", "yellow")
OWNER = "a" * 32
COMMAND = {"command_id": "b" * 32, "command_sequence": 7, "body": {"cmd": "force_faint", "death_id": "d" * 32, "key": "9A5F:1234:84"}}
BINDING = {"context_generation": "c" * 32, "binding_digest": "e" * 64}
DEATH = {"phase": "pending_faint", "peer": "a", "peer_key": "9A5F:1234:84"}
MEMBER = {"slot": 2, "species": 0x84, "dvs_hex": "9a5f", "ot_id_hex": "1234"}
HOST = {"owner_id": OWNER, "frame": 1200, "step": 9}
OFFSET = 0  # the convention these unit tests assume; the live gate pins the real one


# ---------------------------------------------------------------- source pins


def test_anchor_bytes_and_addresses_match_sym_and_clean_rom(pinned):  # noqa: F811
    p = pinned
    a = auth.ANCHORS[p.title]
    assert p.sym["MainInBattleLoop"] == (a["bank"], a["loop_head"]["pc"])
    assert p.sym["ExecutePlayerMove"] == (a["bank"], a["player_action"]["pc"])
    assert p.sym["ExecutePlayerMoveDone"] == (a["bank"], a["move_done"]["pc"])
    for name in ("loop_head", "player_action", "poison_tail", "move_done"):
        site = a[name]
        offset = a["bank"] * 0x4000 + site["pc"] - 0x4000
        assert p.rom[offset:offset + len(site["expected_hex"]) // 2].hex() == site["expected_hex"], name
    for name, address in a["addresses"].items():
        assert p.sym[name][1] == address, name
    assert p.sym["wBattleMonHP"][1] == p.sym["wBattleMonSpecies"][1] + 1
    assert p.sym["wPartyMon1HP"][1] == p.sym["wPartyMon1"][1] + 1
    assert p.sym["wPartyMon1Status"][1] == p.sym["wPartyMon1HP"][1] + 3
    assert p.sym["wPartyMon1DVs"][1] - p.sym["wPartyMon1"][1] == 27
    assert p.sym["wPartyMon2"][1] - p.sym["wPartyMon1"][1] == auth.PARTY_STRIDE


def test_player_action_site_is_the_engine_skip_and_its_two_callers(pinned):  # noqa: F811
    p = pinned
    a = auth.ANCHORS[p.title]
    head = rom_at(p, "ExecutePlayerMove", 10)
    lo, hi = a["addresses"]["wPlayerSelectedMove"] & 255, a["addresses"]["wPlayerSelectedMove"] >> 8
    done = a["move_done"]["pc"]
    assert head == bytes((0xAF, 0xE0, 0xF3, 0xFA, lo, hi, 0x3C, 0xCA, done & 255, done >> 8))
    assert rom_at(p, "ExecutePlayerMoveDone", 7) == bytes((0xAF, 0xEA, 0x6A, 0xCD, 0x06, 0x01, 0xC9))
    base = a["bank"] * 0x4000
    target = bytes((0xCD, a["player_action"]["pc"] & 255, a["player_action"]["pc"] >> 8))
    callers = [0x4000 + i for i in range(0x4000) if p.rom[base + i:base + i + 3] == target]
    assert [c + 3 for c in callers] == a["player_action"]["return_sites"]
    core = p.core
    assert core.count("\tcall ExecutePlayerMove\n") == 2
    for block in (".playerMovesFirst", ".AIActionUsedEnemyFirst"):
        segment = local(core, block)
        assert "call ExecutePlayerMove" in segment and "call HandlePoisonBurnLeechSeed\n\tjp z, HandlePlayerMonFainted" in segment
    assert "\tld a, [hli]\n\tor [hl]\n\tret nz          ; test if fainted" in core
    # a successful run / Poké Doll returns straight out of the loop: those paths never reach a site
    menu = core[core.index("MainInBattleLoop:"):core.index(".selectPlayerMove")]
    assert "call DisplayBattleMenu ; show battle menu\n\tret c" in menu and "ld a, [wEscapedFromBattle]\n\tand a\n\tret nz" in menu


def test_transform_copies_species_and_dvs_but_not_hp_and_benched_slot_is_the_only_copy(pinned):  # noqa: F811
    p = pinned
    transform = (p.root / "engine/battle/move_effects/transform.asm").read_text(encoding="utf-8")
    assert "set TRANSFORMED, a" in transform and "; species\n\tld a, [hl]\n\tld [de], a" in transform
    assert "; DVs\n\tld a, [hli]\n\tld [de], a" in transform and "; Skip level and max HP" in transform
    constants = (p.root / "constants/battle_constants.asm").read_text(encoding="utf-8")
    assert "\tconst TRANSFORMED         ; 3" in constants and auth.TRANSFORMED == 1 << 3
    core = p.core
    faint = core[core.index("HasMonFainted:"):core.index("HasMonFainted:") + 200]
    assert "ld hl, wPartyMon1HP\n\tld bc, PARTYMON_STRUCT_LENGTH\n\tcall AddNTimes\n\tld a, [hli]\n\tor [hl]\n\tret nz" in faint
    removed = core[core.index("RemoveFaintedPlayerMon:"):core.index("RemoveFaintedPlayerMon:") + 1200]
    assert "ld [wBattleMonStatus], a\n\tcall ReadPlayerMonCurHPAndStatus" in removed


def test_write_sets_are_exactly_the_documented_footprints():
    for variant in VARIANTS:
        a = auth.ANCHORS[variant]["addresses"]
        hp = a["wBattleMonHP"]
        assert auth.active_writes(variant, "loop_head") == [{"address": hp, "value": 0}, {"address": hp + 1, "value": 0}]
        assert auth.active_writes(variant, "player_action")[2] == {"address": a["wPlayerSelectedMove"], "value": 0xFF}
        assert auth.benched_writes(variant, 2) == [{"address": a["wPartyMon1HP"] + 88, "value": 0}, {"address": a["wPartyMon1HP"] + 89, "value": 0},
                                                   {"address": a["wPartyMon1Status"] + 88, "value": 0}]


# ---------------------------------------------------------------- server side


def authority(variant, **host):
    proof = auth.prepare("a", COMMAND, BINDING, DEATH, MEMBER, {**HOST, **host}, variant=variant)
    return auth.issue({"schema": generic.SCHEMA, "challenge": "f" * 32, "scope": dict(proof.scope)}, proof)


def state(variant, **over):
    base = {"is_in_battle": 1, "battle_type": 0, "link_state": 0, "player_mon_number": 2, "status3": 0, "battle_species": 0x84,
            "battle_dvs_hex": "9a5f", "party_species": 0x84, "party_dvs_hex": "9a5f", "party_ot_id_hex": "1234", "party_hp_hex": "0037", "party_status": 0,
            "hp_hex": "0037", "enemy_hp_hex": "0012", "action_result": 0, "selected_move": 0x21, "moves_hex": "21270000", "pp_hex": "231e0000"}
    base.update(over)
    return base


def before_bytes(variant, st):
    a = auth.ANCHORS[variant]["addresses"]
    hp = a["wPartyMon1HP"] + 88
    out = {a["wBattleMonHP"]: int(st["hp_hex"][:2], 16), a["wBattleMonHP"] + 1: int(st["hp_hex"][2:], 16), a["wPlayerSelectedMove"]: st["selected_move"],
           hp: int(st["party_hp_hex"][:2], 16), hp + 1: int(st["party_hp_hex"][2:], 16), a["wPartyMon1Status"] + 88: st["party_status"]}
    for i in range(4):
        out[a["wBattleMonMoves"] + i] = int(st["moves_hex"][2 * i:2 * i + 2], 16)
        out[a["wBattleMonPP"] + i] = int(st["pp_hex"][2 * i:2 * i + 2], 16)
    return out


def evidence(variant, site, st=None, binding=auth.BINDING, **over):
    a = auth.ANCHORS[variant]
    st = st if st is not None else state(variant)
    row = {"schema": generic.EVIDENCE, "challenge": "f" * 32, "owner_id": OWNER, "frame": 1200, "step": 9, "held": False, "site": site,
           "pc": a[site]["pc"], "bank": a["bank"], "sp": 0xDFF0,
           "stack_hex": ("64430000" if variant != "yellow" else "7a430000") if site == "player_action" else "12345678",
           "hook_frame": 1200 + OFFSET, "state": st, "writes": [], "refusal": None}
    decision = auth.decide(st, MEMBER, variant, site, binding=binding)
    if decision["refusal"] is None:
        before = before_bytes(variant, st)
        row["writes"] = [{"address": w["address"], "before_hex": f"{before[w['address']]:02x}", "after_hex": f"{w['value']:02x}"} for w in decision["writes"]]
    else:
        row["refusal"] = decision["refusal"]
    row.update(over)
    return row


def verify(a, row):
    return auth.verify_evidence(a, row, hook_frame_offset=OFFSET)


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("site", auth.SITES)
def test_active_linked_mon_settles_as_fainted_at_either_site(variant, site):
    a = authority(variant)
    assert a["uses"] == 1 and a["held"] is False and a["binding"] == auth.BINDING and a["sites"][site]["writes"] == auth.active_writes(variant, site)
    assert verify(a, evidence(variant, site)) == {"outcome": "fainted", "site": site, "reason": None}


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("site", auth.SITES)
def test_transformed_linked_mon_is_still_recognised_by_its_party_slot(variant, site):
    a = authority(variant)
    st = state(variant, status3=auth.TRANSFORMED, battle_species=0x15, battle_dvs_hex="ffff")  # battle struct now carries the enemy
    row = evidence(variant, site, st)
    assert row["refusal"] is None and verify(a, row)["outcome"] == "fainted"
    untransformed = state(variant, battle_species=0x15, battle_dvs_hex="ffff")
    assert verify(a, evidence(variant, site, untransformed)) == {"outcome": "refused", "site": site, "reason": "active battle struct is not the linked mon"}


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("site", auth.SITES)
def test_benched_linked_mon_gets_party_only_hp_and_status_zero(variant, site):
    a = authority(variant)
    addr = auth.ANCHORS[variant]["addresses"]
    st = state(variant, player_mon_number=0, battle_species=0x19, battle_dvs_hex="1111", party_status=0x08)  # PSN on the bench
    row = evidence(variant, site, st)
    assert [w["address"] for w in row["writes"]] == [w["address"] for w in auth.benched_writes(variant, 2)]
    assert row["writes"][2]["before_hex"] == "08" and all(w["after_hex"] == "00" for w in row["writes"])
    assert verify(a, row) == {"outcome": "benched", "site": site, "reason": None}
    assert all(w["address"] not in (addr["wBattleMonHP"], addr["wBattleMonHP"] + 1, addr["wPlayerSelectedMove"]) for w in row["writes"])
    assert verify(a, evidence(variant, site, state(variant, player_mon_number=0, party_hp_hex="0000")))["reason"] == "already fainted"


@pytest.mark.parametrize("variant", VARIANTS)
def test_unreached_frame_is_reported_not_settled_even_without_a_frame_convention(variant):
    a = authority(variant)
    row = {"schema": generic.EVIDENCE, "challenge": "f" * 32, "owner_id": OWNER, "frame": 1200, "step": 9, "held": False, "site": None,
           "pc": None, "bank": None, "sp": None, "stack_hex": None, "hook_frame": None, "state": None, "writes": [], "refusal": None}
    assert auth.verify_evidence(a, row)["outcome"] == "not_reached"
    with pytest.raises(JournalError, match="unreached authority"):
        auth.verify_evidence(a, {**row, "writes": [{"address": 1, "before_hex": "00", "after_hex": "00"}]})


def test_hook_frame_convention_is_the_live_measured_zero_and_none_is_fail_safe():
    a = authority("red")
    assert auth.HOOK_FRAME_OFFSET == 0 and a["hook_frame_offset"] == 0  # measured live on red/blue/yellow, frameadvance and step_one alike
    assert auth.verify_evidence(a, evidence("red", "loop_head"))["outcome"] == "fainted"
    proof = auth.prepare("a", COMMAND, BINDING, DEATH, MEMBER, HOST, variant="red")
    with pytest.raises(ValueError, match="measured hook frame convention"):
        generic.issue({"schema": generic.SCHEMA, "challenge": "f" * 32, "scope": dict(proof.scope)}, proof, auth.sites("red"),
                      auth.ANCHORS["red"]["addresses"], hook_frame_offset=None)
    with pytest.raises(JournalError, match="outside the authorized frame"):
        auth.verify_evidence({**a, "hook_frame_offset": 1}, evidence("red", "loop_head"))  # the conveyed convention is what binds
    with pytest.raises(JournalError, match="convention is unverified"):
        auth.verify_evidence({**a, "hook_frame_offset": None}, evidence("red", "loop_head"))  # an authority without the convention settles nothing
    assert auth.verify_evidence(a, evidence("red", "loop_head", hook_frame=1201), hook_frame_offset=1)["outcome"] == "fainted"
    with pytest.raises(JournalError, match="outside the authorized frame"):
        auth.verify_evidence(a, evidence("red", "loop_head", hook_frame=1201))


@pytest.mark.parametrize("over,reason", [
    ({"is_in_battle": 0}, "not in a wild or trainer battle"),
    ({"battle_type": 2}, "no player mon in play"),
    ({"battle_type": 4}, "no player mon in play"),
    ({"link_state": 4}, "link battle"),
    ({"party_species": 0x01}, "party slot is not the linked mon"),
    ({"party_dvs_hex": "0000"}, "party slot is not the linked mon"),
    ({"party_ot_id_hex": "4321"}, "party slot is not the linked mon"),
    ({"battle_species": 0x85}, "active battle struct is not the linked mon"),
    ({"hp_hex": "0000"}, "already fainted"),
    ({"enemy_hp_hex": "0000"}, "enemy faint path"),
])
def test_client_refusals_must_match_the_bytes_and_write_nothing(over, reason):
    a = authority("red")
    row = evidence("red", "player_action", state("red", **over))
    assert row["writes"] == [] and reason in row["refusal"]
    assert verify(a, row)["outcome"] == "refused"
    forged = dict(row, writes=evidence("red", "player_action")["writes"], refusal=None)
    with pytest.raises(JournalError, match="wrote or misreported"):
        verify(a, forged)
    with pytest.raises(JournalError, match="refused an admissible"):
        verify(a, dict(evidence("red", "player_action"), refusal="made up"))


@pytest.mark.parametrize("mutate,match", [
    (lambda r, v: r.update(held=True), "cannot fire in a held frame"),
    (lambda r, v: r.update(frame=1201), "not from the authorized bounded step"),
    (lambda r, v: r.update(step=10), "not from the authorized bounded step"),
    (lambda r, v: r.update(hook_frame=1199), "outside the authorized frame"),
    (lambda r, v: r.update(owner_id="1" * 32), "different instruction authority"),
    (lambda r, v: r.update(challenge="0" * 32), "different instruction authority"),
    (lambda r, v: r.update(pc=r["pc"] + 3), "not the pinned instruction"),
    (lambda r, v: r.update(bank=0x0E), "not the pinned instruction"),
    (lambda r, v: r.update(stack_hex="00000000"), "not entered from its pinned caller"),
    (lambda r, v: r.update(site="menu"), "unknown instruction site"),
    (lambda r, v: r["writes"].pop(), "exact authorized write set"),
    (lambda r, v: r["writes"].append({"address": 0xD062, "before_hex": "00", "after_hex": "08"}), "exact authorized write set"),
    (lambda r, v: r["writes"][0].update(address=auth.ANCHORS[v]["addresses"]["wBattleMonHP"] + 2), "outside the authorized byte set"),
    (lambda r, v: r["writes"][2].update(after_hex="fe"), "outside the authorized byte set"),
    (lambda r, v: r["writes"][0].update(before_hex="ff"), "outside the authorized byte set"),
    (lambda r, v: r["state"].pop("status3"), "complete instruction state"),
    (lambda r, v: r.pop("sp"), "complete instruction evidence"),
])
@pytest.mark.parametrize("variant", VARIANTS)
def test_forged_or_misaddressed_evidence_is_refused(variant, mutate, match):
    a = authority(variant)
    row = evidence(variant, "player_action")
    mutate(row, variant)
    with pytest.raises(JournalError, match=match):
        verify(a, row)


def test_loop_head_arrives_by_jump_so_only_the_action_site_pins_a_return_address():
    a = authority("blue")
    assert verify(a, evidence("blue", "loop_head", stack_hex="00000000"))["outcome"] == "fainted"
    assert verify(a, evidence("blue", "player_action", stack_hex="80430000"))["outcome"] == "fainted"


def test_prepare_binds_the_pending_owned_death_and_refuses_everything_else():
    with pytest.raises(JournalError, match="serves force_faint"):
        auth.prepare("a", {**COMMAND, "body": {"cmd": "memorialize"}}, BINDING, DEATH, MEMBER, HOST, variant="red")
    for death in ({**DEATH, "phase": "pending_memorial"}, {**DEATH, "peer": "b"}, {**DEATH, "peer_key": "K2"}, None):
        with pytest.raises(JournalError, match="pending owned death"):
            auth.prepare("a", COMMAND, BINDING, death, MEMBER, HOST, variant="red")
    with pytest.raises(JournalError, match="slot/species/DVs/OT id"):
        auth.prepare("a", COMMAND, BINDING, DEATH, {"slot": 2}, HOST, variant="red")
    for member in ({**MEMBER, "slot": 6}, {**MEMBER, "dvs_hex": "zz"}, {**MEMBER, "ot_id_hex": "4321"}, {**MEMBER, "species": 0x85}):
        with pytest.raises(JournalError, match="physical key|differs from the physical key"):
            auth.prepare("a", COMMAND, BINDING, DEATH, member, HOST, variant="red")
    with pytest.raises(JournalError, match="physical key"):
        auth.prepare("a", {**COMMAND, "body": {**COMMAND["body"], "key": "K1"}}, BINDING, {**DEATH, "peer_key": "K1"}, MEMBER, HOST, variant="red")
    assert auth.member_of("9A5F:1234:84", 2) == MEMBER
    with pytest.raises(JournalError, match="owner id, frame and step"):
        auth.prepare("a", COMMAND, BINDING, DEATH, MEMBER, {"owner_id": OWNER}, variant="red")
    with pytest.raises(ValueError, match="positive step"):
        auth.prepare("a", COMMAND, BINDING, DEATH, MEMBER, {**HOST, "step": 0}, variant="red")
    proof = auth.prepare("a", COMMAND, BINDING, DEATH, MEMBER, HOST, variant="red")
    assert proof.scope["phase"] == "battle_force_faint" and proof.frame == 1200 and proof.step == 9 and proof.member["variant"] == "red"
    with pytest.raises(ValueError, match="scope differs"):
        auth.issue({"schema": generic.SCHEMA, "challenge": "f" * 32, "scope": {**proof.scope, "phase": "force_faint"}}, proof)
    with pytest.raises(ValueError, match="verified battle instruction authority"):
        auth.issue({"schema": generic.SCHEMA, "challenge": "f" * 32, "scope": dict(proof.scope)}, object())
    other = generic.VerifiedInstructionAuthority(dict(proof.scope), proof.proof_digest, OWNER, 1200, 9, "other-binding", {})
    with pytest.raises(ValueError, match="verified battle instruction authority"):
        auth.issue({"schema": generic.SCHEMA, "challenge": "f" * 32, "scope": dict(proof.scope)}, other)
    with pytest.raises(JournalError, match="not a battle force-faint authority"):
        auth.verify_evidence({**authority("red"), "binding": "other"}, evidence("red", "loop_head"))


def test_an_authority_for_one_step_cannot_settle_another_step():
    a = authority("red")
    later = evidence("red", "loop_head", frame=1201, step=10, hook_frame=1201 + OFFSET)
    with pytest.raises(JournalError, match="not from the authorized bounded step"):
        verify(a, later)
    assert verify(authority("red", frame=1201, step=10), later)["outcome"] == "fainted"


# ---------------------------------------------------------------- lua executor


@pytest.fixture
def probe(runtime):  # noqa: F811
    lua = runtime
    lua.execute("""
        bus={};hooks={};frame=1200;pc=0;regs={SP=0xDFF0};held=true
        memory={read_u8=function(a,d)return bus[a]or 0 end,write_u8=function(a,v,d)bus[a]=v end}
        emu={framecount=function()return frame end,getregister=function(k)if k=='PC' then return pc end;return regs[k]end}
        event={on_bus_exec=function(fn,a,name)hooks[name]=fn;return name end,unregisterbyid=function(name)hooks[name]=nil end}
        function put(address,hexs)for i=1,#hexs,2 do bus[address+(i-1)/2]=tonumber(hexs:sub(i,i+1),16)end end
        X=require('battle_force_authority').new({owner_id=string.rep('a',32),held=function()return held end})
    """)
    return lua


def load(lua, variant, st, site):
    a = auth.ANCHORS[variant]
    addr = a["addresses"]
    lua.globals().payload = json.dumps({"a": addr, "st": st, "sites": auth.sites(variant), "bank": a["bank"], "site": site,
                                        "stack": ("64430000" if variant != "yellow" else "7a430000") if site == "player_action" else "12345678",
                                        "stride": auth.PARTY_STRIDE, "slot": MEMBER["slot"]})
    lua.execute("""
        local p=JSON.decode(payload);local a=p.a;local st=p.st
        for name,site in pairs(p.sites)do put(site.pc,site.expected_hex)end
        bus[a.hLoadedROMBank]=p.bank;bus[a.wIsInBattle]=st.is_in_battle;bus[a.wBattleType]=st.battle_type;bus[a.wLinkState]=st.link_state
        bus[a.wPlayerMonNumber]=st.player_mon_number;bus[a.wPlayerBattleStatus3]=st.status3
        bus[a.wBattleMonSpecies]=st.battle_species;put(a.wBattleMonDVs,st.battle_dvs_hex)
        bus[a.wPartyMon1+p.stride*p.slot]=st.party_species;put(a.wPartyMon1DVs+p.stride*p.slot,st.party_dvs_hex);put(a.wPartyMon1OTID+p.stride*p.slot,st.party_ot_id_hex)
        put(a.wPartyMon1HP+p.stride*p.slot,st.party_hp_hex);bus[a.wPartyMon1Status+p.stride*p.slot]=st.party_status
        put(a.wBattleMonHP,st.hp_hex);put(a.wEnemyMonHP,st.enemy_hp_hex);bus[a.wActionResultOrTookBattleTurn]=st.action_result
        bus[a.wPlayerSelectedMove]=st.selected_move;put(regs.SP,p.stack)
        put(a.wBattleMonMoves,st.moves_hex);put(a.wBattleMonPP,st.pp_hex)
        target=p.sites[p.site]
    """)


def arm(lua, a):
    lua.globals().authority_json = json.dumps(a)
    lua.execute("assert(X.arm(JSON.decode(authority_json)))")


def hit(lua, site, *, frame_delta=OFFSET):
    """Simulate the hook firing inside step_one's released frame at the pinned PC."""
    lua.execute(f"held=false;frame=frame+({frame_delta});pc=target.pc;hooks['slink-instruction-rby-battle-force-faint-{site}']();frame=frame-({frame_delta})")


def run_frame(lua):
    lua.execute("frame=frame+1;held=true")


def finish(lua):
    return json.loads(lua.eval("JSON.encode(X.finish())"))


def bus(lua, address):
    return lua.eval(f"bus[{address}] or 0")


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("site", auth.SITES)
def test_executor_writes_exactly_the_active_footprint_and_the_server_settles_it(probe, variant, site):
    a = authority(variant)
    addr = auth.ANCHORS[variant]["addresses"]
    load(probe, variant, state(variant), site)
    arm(probe, a)
    hit(probe, site)
    run_frame(probe)
    row = finish(probe)
    assert (bus(probe, addr["wBattleMonHP"]), bus(probe, addr["wBattleMonHP"] + 1)) == (0, 0)
    assert bus(probe, addr["wPlayerSelectedMove"]) == (0xFF if site == "player_action" else 0x21)
    assert bus(probe, addr["wPartyMon1HP"] + 89) == 0x37 and bus(probe, addr["wBattleMonSpecies"]) == 0x84  # nothing else moved
    assert row["held"] is False and row["site"] == site and row["hook_frame"] == 1200 + OFFSET
    assert verify(a, row) == {"outcome": "fainted", "site": site, "reason": None}
    assert probe.eval("X.status().armed") is False and probe.eval("X.status().last_step") == 9


@pytest.mark.parametrize("variant", VARIANTS)
def test_executor_benched_and_transformed_branches_match_the_server(probe, variant):
    a = authority(variant)
    addr = auth.ANCHORS[variant]["addresses"]
    load(probe, variant, state(variant, player_mon_number=0, battle_species=0x19, battle_dvs_hex="1111", party_status=0x08), "loop_head")
    arm(probe, a)
    hit(probe, "loop_head")
    run_frame(probe)
    row = finish(probe)
    assert bus(probe, addr["wPartyMon1HP"] + 88) == 0 and bus(probe, addr["wPartyMon1HP"] + 89) == 0 and bus(probe, addr["wPartyMon1Status"] + 88) == 0
    assert bus(probe, addr["wBattleMonHP"] + 1) == 0x37  # the active, unlinked mon is untouched
    assert verify(a, row) == {"outcome": "benched", "site": "loop_head", "reason": None}
    b = authority(variant, frame=1201, step=10)
    b["challenge"] = "0" * 32
    load(probe, variant, state(variant, status3=auth.TRANSFORMED, battle_species=0x15, battle_dvs_hex="ffff"), "player_action")
    arm(probe, b)
    hit(probe, "player_action")
    run_frame(probe)
    row = finish(probe)
    assert bus(probe, addr["wBattleMonHP"] + 1) == 0 and bus(probe, addr["wPlayerSelectedMove"]) == 0xFF
    assert verify(b, row)["outcome"] == "fainted"


def test_first_site_consumes_the_authority_and_the_other_hook_is_inert(probe):
    a = authority("red")
    addr = auth.ANCHORS["red"]["addresses"]
    load(probe, "red", state("red"), "loop_head")
    arm(probe, a)
    hit(probe, "loop_head")
    probe.execute(f"put({addr['wBattleMonHP']},'0037');bus[{addr['wPlayerSelectedMove']}]=0x21;target=JSON.decode(payload).sites.player_action")
    hit(probe, "player_action")
    assert bus(probe, addr["wPlayerSelectedMove"]) == 0x21 and bus(probe, addr["wBattleMonHP"] + 1) == 0x37
    run_frame(probe)
    assert finish(probe)["site"] == "loop_head"


def test_menu_state_reaches_no_site_and_reports_not_reached_without_writing(probe):
    a = authority("blue")
    addr = auth.ANCHORS["blue"]["addresses"]
    load(probe, "blue", state("blue"), "loop_head")
    arm(probe, a)
    run_frame(probe)  # the frame ran; the busy menu loop never executed either PC
    row = finish(probe)
    assert row["site"] is None and row["writes"] == [] and row["hook_frame"] is None and bus(probe, addr["wBattleMonHP"] + 1) == 0x37
    assert auth.verify_evidence(a, row)["outcome"] == "not_reached"


@pytest.mark.parametrize("over", [{"player_mon_number": 0, "party_species": 0x01}, {"party_ot_id_hex": "4321"}, {"battle_species": 0x19}, {"battle_type": 2}, {"link_state": 4}, {"hp_hex": "0000"}])
def test_ineligible_battle_refuses_and_writes_nothing(probe, over):
    a = authority("yellow")
    st = state("yellow", **over)
    addr = auth.ANCHORS["yellow"]["addresses"]
    load(probe, "yellow", st, "player_action")
    arm(probe, a)
    hit(probe, "player_action")
    run_frame(probe)
    row = finish(probe)
    assert row["writes"] == [] and row["refusal"] and bus(probe, addr["wPlayerSelectedMove"]) == 0x21
    assert bus(probe, addr["wBattleMonHP"] + 1) == int(st["hp_hex"][2:], 16) and bus(probe, addr["wPartyMon1HP"] + 89) == 0x37
    assert verify(a, row)["outcome"] == "refused"


def test_stale_frame_or_wrong_bank_never_fires_and_a_claimed_hold_latches(probe):
    a = authority("red")
    addr = auth.ANCHORS["red"]["addresses"]
    load(probe, "red", state("red"), "loop_head")
    arm(probe, a)
    hit(probe, "loop_head", frame_delta=2)  # a hook from a frame that is not the stepped one
    assert bus(probe, addr["wBattleMonHP"] + 1) == 0x37 and probe.eval("X.status().armed") is True
    probe.execute(f"bus[{addr['hLoadedROMBank']}]=0x0E")
    hit(probe, "loop_head")
    assert bus(probe, addr["wBattleMonHP"] + 1) == 0x37
    probe.execute(f"bus[{addr['hLoadedROMBank']}]=0x0F;held=true;pc=target.pc;hooks['slink-instruction-rby-battle-force-faint-loop_head']()")
    assert bus(probe, addr["wBattleMonHP"] + 1) == 0x37
    assert "reports a hold" in probe.eval("X.status().failed")
    with pytest.raises(Exception, match="reports a hold"):
        finish(probe)


def test_arm_and_finish_enforce_hold_one_frame_one_use_and_monotonic_steps(probe):
    a = authority("red")
    load(probe, "red", state("red"), "loop_head")
    with pytest.raises(Exception, match="for this owner and binding"):
        arm(probe, {**a, "owner_id": "1" * 32})
    with pytest.raises(Exception, match="for this owner and binding"):
        arm(probe, {**a, "held": True})
    with pytest.raises(Exception, match="for this owner and binding"):
        arm(probe, {**a, "binding": "other"})
    probe.execute("held=false")
    with pytest.raises(Exception, match="requires the verified hold"):
        arm(probe, a)
    probe.execute("held=true;frame=1201")
    with pytest.raises(Exception, match="frame other than the one about to run"):
        arm(probe, a)
    probe.execute("frame=1200")
    arm(probe, a)
    with pytest.raises(Exception, match="already armed"):
        arm(probe, a)
    probe.execute("assert(not pcall(X.finish))")  # finish without a frame having run is a latching fault
    assert "exactly one frame" in probe.eval("X.status().failed")


def test_a_finished_challenge_cannot_be_rearmed_and_steps_must_advance(probe):
    a = authority("red")
    load(probe, "red", state("red"), "loop_head")
    arm(probe, a)
    run_frame(probe)
    assert finish(probe)["site"] is None
    probe.execute("frame=1200")  # even if the host frame were rewound, the same challenge is spent
    with pytest.raises(Exception, match="already used"):
        arm(probe, a)
    probe.execute("frame=1201")
    with pytest.raises(Exception, match="already used"):
        arm(probe, {**a, "frame": 1201})
    same_step = authority("red", frame=1201, step=9)
    same_step["challenge"] = "0" * 32
    with pytest.raises(Exception, match="not after the last finished step"):
        arm(probe, same_step)
    later = authority("red", frame=1201, step=10)
    later["challenge"] = "0" * 32
    arm(probe, later)
    probe.execute("frame=1202;held=false")
    with pytest.raises(Exception, match="re-acquired hold"):
        finish(probe)


def test_wrong_caller_latches_before_any_byte_is_written(probe):
    a = authority("red")
    addr = auth.ANCHORS["red"]["addresses"]
    load(probe, "red", state("red"), "player_action")
    probe.execute("put(regs.SP,'00c00000')")  # a return address that is not one of the two battle-loop callers
    arm(probe, a)
    hit(probe, "player_action")
    assert bus(probe, addr["wBattleMonHP"] + 1) == 0x37 and bus(probe, addr["wPlayerSelectedMove"]) == 0x21
    assert "not entered from its pinned caller" in probe.eval("X.status().failed")
    with pytest.raises(Exception, match="pinned caller"):
        finish(probe)


def test_same_species_and_dvs_but_another_ot_writes_nothing(probe):
    a = authority("blue")
    addr = auth.ANCHORS["blue"]["addresses"]
    load(probe, "blue", state("blue", party_ot_id_hex="4321"), "loop_head")
    arm(probe, a)
    hit(probe, "loop_head")
    run_frame(probe)
    row = finish(probe)
    assert row["writes"] == [] and row["refusal"] == "party slot is not the linked mon" and bus(probe, addr["wBattleMonHP"] + 1) == 0x37
    assert verify(a, row)["outcome"] == "refused"


def test_a_hook_one_frame_late_writes_nothing_and_leaves_the_authority_armed(probe):
    a = authority("red")
    addr = auth.ANCHORS["red"]["addresses"]
    load(probe, "red", state("red"), "loop_head")
    arm(probe, a)
    hit(probe, "loop_head", frame_delta=1)  # the host convention is 0; a +1 hook is not this step's instruction
    assert bus(probe, addr["wBattleMonHP"] + 1) == 0x37 and probe.eval("X.status().armed") is True and probe.eval("X.status().failed") is None
    hit(probe, "loop_head", frame_delta=-1)
    assert bus(probe, addr["wBattleMonHP"] + 1) == 0x37 and probe.eval("X.status().armed") is True
    run_frame(probe)
    assert auth.verify_evidence(a, finish(probe))["outcome"] == "not_reached"
    with pytest.raises(Exception, match="measured hook frame convention"):
        arm(probe, {**authority("red", frame=1201, step=10), "challenge": "0" * 32, "hook_frame_offset": None})


# ---------------------------------------------------------------- frame window (count > 1)


def window_status(lua, challenge="f" * 32):
    return json.loads(lua.eval(f"JSON.encode(X.window_status('{challenge}') or JSON.null)"))


def step_window(lua, a, site, fire_at=None, frames=None):
    """Arm/step/finish the same authority once per frame; fire the site on 0-based frame `fire_at`. Returns the rows."""
    rows = []
    for i in range(frames if frames is not None else a["frames"]["count"]):
        arm(lua, a)
        if i == fire_at:
            hit(lua, site)
        run_frame(lua)
        rows.append(finish(lua))
    return rows


def settle_window(a, rows):
    return generic.verify_window(a, rows, verify_row=auth.verify_evidence, hook_frame_offset=OFFSET)


def test_window_authority_carries_frames_and_a_count_of_one_carries_none():
    a = authority("red", count=5)
    assert a["frames"] == {"first": 1200, "count": 5} and a["frame"] == 1200 and a["step"] == 9 and a["uses"] == 1
    assert "frames" not in authority("red") and generic.window(authority("red")) == (1200, 1)
    assert generic.window(a) == (1200, 5)
    proof = auth.prepare("a", COMMAND, BINDING, DEATH, MEMBER, {**HOST, "count": 5}, variant="red")
    assert proof.count == 5 and proof.frame == 1200
    request = {"schema": generic.SCHEMA, "challenge": "f" * 32, "scope": dict(proof.scope)}
    same = generic.issue(request, proof, auth.sites("red"), auth.ANCHORS["red"]["addresses"], hook_frame_offset=OFFSET, frames={"first": 1200, "count": 5})
    assert same == a
    for frames in ({"first": 1200, "count": 6}, {"first": 1201, "count": 5}, {"first": 1200, "count": 1}):
        with pytest.raises(ValueError, match="window differs from the proof"):
            generic.issue(request, proof, auth.sites("red"), auth.ANCHORS["red"]["addresses"], hook_frame_offset=OFFSET, frames=frames)
    for bad in ({"first": 1201, "count": 5}, {"first": 1200}, {"first": 1200, "count": 0}, {"first": 1200, "count": generic.MAX_WINDOW_FRAMES + 1}, [1200, 5]):
        with pytest.raises(JournalError, match="window is malformed"):
            generic.window({**a, "frames": bad})


@pytest.mark.parametrize("count", [0, -1, generic.MAX_WINDOW_FRAMES + 1, 5.0, "5", None])
def test_window_count_outside_one_to_max_is_refused_at_construction(count):
    with pytest.raises(ValueError, match="instruction window of 1"):
        auth.prepare("a", COMMAND, BINDING, DEATH, MEMBER, {**HOST, "count": count}, variant="red")
    proof = auth.prepare("a", COMMAND, BINDING, DEATH, MEMBER, HOST, variant="red")
    with pytest.raises(ValueError, match="instruction window of 1"):
        generic.VerifiedInstructionAuthority(dict(proof.scope), proof.proof_digest, OWNER, 1200, 9, auth.BINDING, {}, count)
    assert generic.MAX_WINDOW_FRAMES == 64
    with pytest.raises(JournalError, match="owner id, frame and step"):
        auth.prepare("a", COMMAND, BINDING, DEATH, MEMBER, {**HOST, "count": 2, "ttl_ms": 5}, variant="red")


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("site", auth.SITES)
def test_window_of_five_firing_on_the_third_frame_yields_two_unreached_rows_then_the_reached_one(probe, variant, site):
    a = authority(variant, count=5)
    addr = auth.ANCHORS[variant]["addresses"]
    load(probe, variant, state(variant), site)
    rows = step_window(probe, a, site, fire_at=2, frames=3)
    assert [r["site"] for r in rows] == [None, None, site]
    assert [(r["frame"], r["step"]) for r in rows] == [(1200, 9), (1201, 10), (1202, 11)]
    assert rows[2]["hook_frame"] == 1202 + OFFSET and rows[0]["writes"] == rows[1]["writes"] == []
    assert (bus(probe, addr["wBattleMonHP"]), bus(probe, addr["wBattleMonHP"] + 1)) == (0, 0)
    assert bus(probe, addr["wPlayerSelectedMove"]) == (0xFF if site == "player_action" else 0x21)
    for row in rows[:2]:
        assert auth.verify_evidence(a, row)["outcome"] == "not_reached"
    assert verify(a, rows[2]) == {"outcome": "fainted", "site": site, "reason": None}
    settled = settle_window(a, rows)
    assert settled == {"covered": [1200, 1202], "outcome": "fainted", "row": rows[2]}
    assert window_status(probe) == {"covered_from": 1200, "covered_to": 1202, "consumed": True}
    assert probe.eval("X.status().last_step") == 11 and probe.eval("X.status().armed") is False
    probe.execute("frame=1203")
    with pytest.raises(Exception, match="already used"):  # consumed: nothing more is stepped under this challenge
        arm(probe, a)


def test_window_firing_on_the_first_frame_is_a_single_row_and_a_count_of_one_is_the_old_behaviour(probe):
    a = authority("red", count=5)
    load(probe, "red", state("red"), "loop_head")
    rows = step_window(probe, a, "loop_head", fire_at=0, frames=1)
    assert len(rows) == 1 and rows[0]["site"] == "loop_head" and rows[0]["frame"] == 1200 and rows[0]["step"] == 9
    assert settle_window(a, rows) == {"covered": [1200, 1200], "outcome": "fainted", "row": rows[0]}
    with pytest.raises(Exception, match="already used"):
        arm(probe, a)
    one = authority("red", frame=1201, step=10)
    one["challenge"] = "0" * 32
    probe.execute(f"put({auth.ANCHORS['red']['addresses']['wBattleMonHP']},'0037')")
    rows = step_window(probe, one, "loop_head", fire_at=None, frames=1)
    assert rows[0]["site"] is None and settle_window(one, rows) == {"covered": [1201, 1201], "outcome": "not_reached", "row": None}
    assert window_status(probe, "0" * 32) == {"covered_from": 1201, "covered_to": 1201, "consumed": False}
    with pytest.raises(Exception, match="already used"):  # a count of one is exhausted after its one frame, as before
        arm(probe, one)


def test_window_that_never_fires_covers_all_five_frames_and_a_sixth_arm_is_refused(probe):
    a = authority("blue", count=5)
    addr = auth.ANCHORS["blue"]["addresses"]
    load(probe, "blue", state("blue"), "loop_head")
    rows = step_window(probe, a, "loop_head", fire_at=None)
    assert [r["site"] for r in rows] == [None] * 5 and [r["frame"] for r in rows] == [1200, 1201, 1202, 1203, 1204]
    assert [r["step"] for r in rows] == [9, 10, 11, 12, 13] and bus(probe, addr["wBattleMonHP"] + 1) == 0x37
    assert settle_window(a, rows) == {"covered": [1200, 1204], "outcome": "not_reached", "row": None}
    assert generic.verify_window(a, rows, verify_row=auth.verify_evidence)["outcome"] == "not_reached"  # no convention needed for unreached rows
    assert window_status(probe) == {"covered_from": 1200, "covered_to": 1204, "consumed": False}
    assert probe.eval("emu.framecount()") == 1205
    with pytest.raises(Exception, match="already used"):  # window exhausted
        arm(probe, a)
    hit(probe, "loop_head")  # a stray hook after the window: nothing armed, nothing written
    assert bus(probe, addr["wBattleMonHP"] + 1) == 0x37 and probe.eval("X.status().failed") is None
    with pytest.raises(JournalError, match="one to count frames"):
        settle_window(a, rows + [dict(rows[4], frame=1205, step=14)])
    with pytest.raises(JournalError, match="one to count frames"):
        settle_window(a, [])


def test_window_gap_is_refused_at_arm_and_by_verify_window(probe):
    a = authority("red", count=5)
    load(probe, "red", state("red"), "loop_head")
    rows = step_window(probe, a, "loop_head", fire_at=None, frames=2)
    probe.execute("frame=frame+1")  # the owner stepped a frame outside the authority
    with pytest.raises(Exception, match="not contiguous"):
        arm(probe, a)
    probe.execute("frame=frame-2")  # nor may it go back
    with pytest.raises(Exception, match="not contiguous"):
        arm(probe, a)
    probe.execute("frame=frame+1")
    arm(probe, a)  # back on the contiguous frame: the window continues
    run_frame(probe)
    rows.append(finish(probe))
    assert [r["frame"] for r in rows] == [1200, 1201, 1202] and window_status(probe) == {"covered_from": 1200, "covered_to": 1202, "consumed": False}
    skipped = [rows[0], rows[2]]
    with pytest.raises(JournalError, match="not contiguous"):
        settle_window(a, skipped)
    with pytest.raises(JournalError, match="not contiguous"):
        settle_window(a, [rows[1], rows[0]])
    with pytest.raises(JournalError, match="not contiguous"):
        settle_window(a, [rows[1]])  # a window's rows start at frames.first


def test_window_reached_row_must_be_last_and_only_one_may_be_reached():
    a = authority("red", count=5)
    unreached = [dict(evidence("red", "loop_head"), frame=1200 + i, step=9 + i, site=None, pc=None, bank=None, sp=None, stack_hex=None,
                      hook_frame=None, state=None, writes=[], refusal=None) for i in range(5)]
    reached = evidence("red", "loop_head", frame=1202, step=11, hook_frame=1202 + OFFSET)
    assert settle_window(a, unreached[:2] + [reached])["outcome"] == "fainted"
    with pytest.raises(JournalError, match="reached row must be the last"):
        settle_window(a, unreached[:2] + [reached, unreached[3]])
    later = evidence("red", "loop_head", frame=1203, step=12, hook_frame=1203 + OFFSET)
    with pytest.raises(JournalError, match="reached row must be the last"):
        settle_window(a, unreached[:2] + [reached, later])
    refused = evidence("red", "loop_head", state("red", hp_hex="0000"), frame=1202, step=11, hook_frame=1202 + OFFSET)
    assert refused["refusal"] == "already fainted"
    with pytest.raises(JournalError, match="reached row must be the last"):  # a refusal is a reached row too
        settle_window(a, unreached[:2] + [refused, unreached[3]])
    assert settle_window(a, unreached[:2] + [refused])["outcome"] == "refused"


def test_window_evidence_frame_step_and_hook_frame_are_checked_per_frame():
    a = authority("yellow", count=5)
    inside = evidence("yellow", "player_action", frame=1203, step=12, hook_frame=1203 + OFFSET)
    assert verify(a, inside)["outcome"] == "fainted"
    with pytest.raises(JournalError, match="not from the authorized bounded step"):
        verify(a, dict(inside, step=9))  # the step must track the frame inside the window
    with pytest.raises(JournalError, match="not from the authorized bounded step"):
        verify(a, dict(inside, step=13))
    with pytest.raises(JournalError, match="not from the authorized bounded step"):
        verify(a, dict(inside, frame=1205, step=14, hook_frame=1205 + OFFSET))  # first+count is outside
    with pytest.raises(JournalError, match="not from the authorized bounded step"):
        verify(a, dict(inside, frame=1199, step=8, hook_frame=1199 + OFFSET))
    with pytest.raises(JournalError, match="outside the authorized frame"):
        verify(a, dict(inside, hook_frame=1200 + OFFSET))  # the hook frame is exact against the row's own frame, not frames.first
    with pytest.raises(JournalError, match="outside the authorized frame"):
        verify(a, dict(inside, hook_frame=1204 + OFFSET))
    with pytest.raises(JournalError, match="not from the authorized bounded step"):
        verify(authority("yellow"), inside)  # a single-frame authority does not stretch


def test_window_hook_one_frame_off_inside_the_window_writes_nothing(probe):
    a = authority("red", count=5)
    addr = auth.ANCHORS["red"]["addresses"]
    load(probe, "red", state("red"), "loop_head")
    rows = step_window(probe, a, "loop_head", fire_at=None, frames=2)
    arm(probe, a)  # frame 1202 of the window
    hit(probe, "loop_head", frame_delta=1)
    hit(probe, "loop_head", frame_delta=-1)
    assert bus(probe, addr["wBattleMonHP"] + 1) == 0x37 and probe.eval("X.status().armed") is True and probe.eval("X.status().failed") is None
    run_frame(probe)
    rows.append(finish(probe))
    assert rows[2]["site"] is None and settle_window(a, rows) == {"covered": [1200, 1202], "outcome": "not_reached", "row": None}
    arm(probe, a)
    hit(probe, "loop_head")  # the exact frame writes
    run_frame(probe)
    rows.append(finish(probe))
    assert rows[3]["site"] == "loop_head" and bus(probe, addr["wBattleMonHP"] + 1) == 0
    assert settle_window(a, rows) == {"covered": [1200, 1203], "outcome": "fainted", "row": rows[3]}


def test_window_abandoned_for_another_challenge_is_spent_and_steps_stay_monotonic(probe):
    a = authority("red", count=5)
    load(probe, "red", state("red"), "loop_head")
    step_window(probe, a, "loop_head", fire_at=None, frames=2)  # last_step 10, frame 1202
    b = authority("red", frame=1202, step=11, count=2)
    b["challenge"] = "0" * 32
    same_step = authority("red", frame=1202, step=10, count=2)
    same_step["challenge"] = "1" * 32
    with pytest.raises(Exception, match="not after the last finished step"):
        arm(probe, same_step)
    rows = step_window(probe, b, "loop_head", fire_at=1)
    assert [(r["frame"], r["step"], r["site"]) for r in rows] == [(1202, 11, None), (1203, 12, "loop_head")]
    assert settle_window(b, rows)["outcome"] == "fainted"
    probe.execute("frame=1202")  # even rewound to where a's window would have continued, a is spent
    with pytest.raises(Exception, match="already used"):
        arm(probe, a)
    assert window_status(probe) is None and window_status(probe, "0" * 32)["consumed"] is True


def test_window_arm_requires_the_hold_and_a_latched_fault_ends_the_window(probe):
    a = authority("red", count=3)
    addr = auth.ANCHORS["red"]["addresses"]
    load(probe, "red", state("red"), "loop_head")
    step_window(probe, a, "loop_head", fire_at=None, frames=1)
    probe.execute("held=false")
    with pytest.raises(Exception, match="requires the verified hold"):
        arm(probe, a)
    probe.execute("held=true")
    arm(probe, a)
    probe.execute("held=true;pc=target.pc;hooks['slink-instruction-rby-battle-force-faint-loop_head']()")  # a hook while held latches
    assert bus(probe, addr["wBattleMonHP"] + 1) == 0x37 and "reports a hold" in probe.eval("X.status().failed")
    run_frame(probe)
    with pytest.raises(Exception, match="reports a hold"):
        finish(probe)
    with pytest.raises(Exception, match="reports a hold"):
        arm(probe, a)


# ---------------------------------------------------------------- free-loop window (handoff item 5)


def window_authority(variant="red", *, first=1200, anchor=1192):
    """A server-issued free-loop window: WINDOW_FRAMES frames from `first`, the step by the anchor rule."""
    return authority(variant, frame=first, step=first - anchor + 1, count=auth.WINDOW_FRAMES)


def unreached(a, frame):
    return {"schema": generic.EVIDENCE, "challenge": a["challenge"], "owner_id": a["owner_id"], "frame": frame, "step": a["step"] + (frame - a["frame"]),
            "held": False, "site": None, "pc": None, "bank": None, "sp": None, "stack_hex": None, "hook_frame": None, "state": None, "writes": [], "refusal": None}


def window_rows(variant, a, start, count, *, reached_at=None, site="loop_head", st=None):
    rows = [unreached(a, start + i) for i in range(count)]
    if reached_at is not None:
        f = start + reached_at
        rows[reached_at] = evidence(variant, site, st, challenge=a["challenge"], frame=f, step=a["step"] + (f - a["frame"]), hook_frame=f + OFFSET)
    return rows


def test_verify_window_accepts_a_window_entered_late_and_settles_its_last_row():
    a = window_authority("red")
    rows = window_rows("red", a, 1210, 5, reached_at=4)
    assert auth.verify_window(a, rows, hook_frame_offset=OFFSET) == {"covered": [1210, 1214], "outcome": "fainted", "row": rows[4]}
    assert auth.verify_window(a, window_rows("red", a, 1263, 1))["outcome"] == "not_reached"  # the last frame of the window alone
    assert auth.verify_window(a, window_rows("red", a, 1200, 64))["covered"] == [1200, 1263]
    benched = window_rows("red", a, 1230, 2, reached_at=1, st=state("red", player_mon_number=0))
    assert auth.verify_window(a, benched, hook_frame_offset=OFFSET)["outcome"] == "benched"
    refused = window_rows("red", a, 1230, 2, reached_at=1, st=state("red", hp_hex="0000"))
    assert auth.verify_window(a, refused, hook_frame_offset=OFFSET)["outcome"] == "refused"
    with pytest.raises(JournalError, match="not contiguous"):  # the generic verifier still demands frames.first
        generic.verify_window(a, rows, verify_row=auth.verify_evidence, hook_frame_offset=OFFSET)


@pytest.mark.parametrize("start, count, reached_at, mutate, match", [
    (1199, 2, None, None, "starts outside"),
    (1264, 1, None, None, "starts outside"),
    (1260, 5, None, None, "one to count frames"),  # runs past the end of the window
    (1210, 3, 1, None, "must be the last row"),
    (1210, 3, None, lambda rows: rows.pop(1), "not contiguous"),
    (1210, 2, None, lambda rows: rows[1].update(step=rows[1]["step"] + 1), "authorized bounded step"),
    (1210, 2, None, lambda rows: rows[0].update(challenge="0" * 32), "different instruction authority"),
    (1210, 0, None, None, "one to count frames"),
])
def test_verify_window_refuses_rows_outside_the_window_gaps_order_and_foreign_challenges(start, count, reached_at, mutate, match):
    a = window_authority("blue")
    rows = window_rows("blue", a, start, count, reached_at=reached_at)
    if mutate:
        mutate(rows)
    with pytest.raises(JournalError, match=match):
        auth.verify_window(a, rows, hook_frame_offset=OFFSET)


def test_verify_issued_reproduces_the_authority_from_its_command_and_refuses_tampering():
    a = window_authority("red", first=1200, anchor=1192)
    assert auth.verify_issued(a, COMMAND, BINDING, player="a", anchor=1192, owner_id=OWNER) == a
    with pytest.raises(JournalError, match="free-run rule"):
        auth.verify_issued(a, COMMAND, BINDING, player="a", anchor=1100, owner_id=OWNER)  # another anchor means another step
    with pytest.raises(JournalError, match="another owner"):
        auth.verify_issued(a, COMMAND, BINDING, player="a", anchor=1192, owner_id="1" * 32)
    for tamper, match in [
        (lambda t: t.update(step=t["step"] + 1), "free-run rule"),
        (lambda t: t["frames"].update(count=5), "free-run rule"),
        (lambda t: t.update(frame=1201), "malformed"),
        (lambda t: t["member"].update(species=1), "differs from the physical key"),
        (lambda t: t["sites"]["loop_head"].update(pc=t["sites"]["loop_head"]["pc"] + 1), "differs from the one its command issues"),
        (lambda t: t["addresses"].update(wBattleMonHP=0), "differs from the one its command issues"),
        (lambda t: t.update(hook_frame_offset=1), "differs from the one its command issues"),
        (lambda t: t.update(binding=auth.EXPLODE), "differs from the one its command issues"),
        (lambda t: t.update(owner_id="1" * 32), "another owner"),
    ]:
        tampered = json.loads(json.dumps(a))
        tamper(tampered)
        with pytest.raises(JournalError, match=match):
            auth.verify_issued(tampered, COMMAND, BINDING, player="a", anchor=1192, owner_id=OWNER)
    other = {**COMMAND, "body": {**COMMAND["body"], "cmd": "force_explode"}}
    with pytest.raises(JournalError):  # the command selects the binding: this one issues the EXPLODE authority
        auth.verify_issued(a, other, BINDING, player="a", anchor=1192, owner_id=OWNER)


def test_pending_instruction_issues_for_the_oldest_pending_death_command_and_nothing_else(tmp_path):
    from server.gen1_run_config import create_runtime
    from tests.unit.test_gen1_engine_signal_runtime import deliver
    from tests.unit.test_gen1_faint_runtime import paired, signal_batch
    from tests.unit.test_gen1_sessions import contract
    run = create_runtime(tmp_path, contract("red", "blue"))
    try:
        owners = paired(run)
        binding = run.gate.sessions["b"].metadata["control_binding"]
        stage = run.state()
        assert auth.pending_instruction(run, stage, stage.document(), "b", frame=130, seed="1" * 32, binding=binding) is None  # nothing pending
        deliver(run, "a", owners["a"], signal_batch(run, "a"))
        stage = run.state()
        document = stage.document()
        death_id, death = next(iter(document["components"][auth.FAINTS]["deaths"].items()))
        initial = document["components"][auth.INITIAL]["b"]
        anchor = initial["observation"]["frame"]
        issued = auth.pending_instruction(run, stage, document, "b", frame=130, seed="1" * 32, binding=binding)
        a = issued["authority"]
        assert issued["cmd"] == auth.COMMAND and issued["death_id"] == death_id and issued["key"] == death["peer_key"]
        assert a["frame"] == 130 and a["step"] == 130 - anchor + 1 and a["frames"] == {"first": 130, "count": auth.WINDOW_FRAMES}
        assert a["binding"] == auth.BINDING and a["member"]["slot"] == 0 and a["challenge"] == auth.challenge_for("1" * 32, death_id)
        assert a["owner_id"] == initial["metadata"]["gen1_metadata"]["physical_instance"] and a["member"]["variant"] == "blue"
        command = run.journal.command("b", run.journal.pending_ids("b")[0])
        assert auth.verify_issued(a, command, binding, player="b", anchor=anchor, owner_id=a["owner_id"]) == a
        assert auth.pending_instruction(run, stage, document, "b", frame=130, seed="1" * 32, binding=binding) == issued  # deterministic
        assert auth.pending_instruction(run, stage, document, "a", frame=130, seed="1" * 32, binding=binding) is None  # the killer has nothing pending
        with pytest.raises(JournalError, match="enrollment frame"):
            auth.pending_instruction(run, stage, document, "b", frame=anchor - 1, seed="1" * 32, binding=binding)
        enforced = json.loads(json.dumps(document))
        enforced["components"][auth.FAINTS]["deaths"][death_id]["enforcement"] = {}
        assert auth.pending_instruction(run, stage, enforced, "b", frame=130, seed="1" * 32, binding=binding) is None
        # one outstanding window at a time; the one being acknowledged is ignored
        snapshot = run.journal.snapshot()
        run.journal.commit("a", "2" * 32, {"event": "issued-window-fixture"}, expected_revision=snapshot.revision, state=snapshot.state,
                           commands={"a": [], "b": [issued]}, result={"ack": "ACK"})
        stage = run.state()
        document = stage.document()
        assert auth.pending_instruction(run, stage, document, "b", frame=140, seed="3" * 32, binding=binding) is None
        following = auth.pending_instruction(run, stage, document, "b", frame=140, seed="3" * 32, binding=binding,
                                             ignore=run.journal.pending_ids("b")[-1])
        assert following["authority"]["frame"] == 140 and following["authority"]["challenge"] != a["challenge"]
    finally:
        run.close()


def test_pending_instruction_waits_behind_an_older_pending_command(tmp_path):
    from server.gen1_run_config import create_runtime
    from tests.unit.test_gen1_engine_signal_runtime import deliver
    from tests.unit.test_gen1_faint_runtime import paired, signal_batch
    from tests.unit.test_gen1_sessions import contract
    run = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        owners = paired(run)
        snapshot = run.journal.snapshot()
        run.journal.commit("a", "4" * 32, {"event": "explicit-older-command-fixture"}, expected_revision=snapshot.revision,
                           state=snapshot.state, commands={"a": [], "b": [{"cmd": "fixture_older_observation"}]}, result={"ack": "ACK"})
        deliver(run, "a", owners["a"], signal_batch(run, "a"))
        stage = run.state()
        binding = run.gate.sessions["b"].metadata["control_binding"]
        assert auth.pending_instruction(run, stage, stage.document(), "b", frame=130, seed="1" * 32, binding=binding) is None
    finally:
        run.close()


def test_window_may_be_entered_late_and_its_rows_start_at_the_entry_frame(probe):
    a = authority("blue", count=8)  # frames 1200..1207
    load(probe, "blue", state("blue"), "loop_head")
    probe.execute("frame=1203")
    rows = step_window(probe, a, "loop_head", fire_at=2, frames=3)  # armed at 1203, 1204, 1205; the site fires on the third
    assert [r["frame"] for r in rows] == [1203, 1204, 1205] and [r["step"] for r in rows] == [12, 13, 14]
    assert rows[2]["site"] == "loop_head" and window_status(probe) == {"covered_from": 1203, "covered_to": 1205, "consumed": True}
    assert auth.verify_window(a, rows, hook_frame_offset=OFFSET)["outcome"] == "fainted"
    with pytest.raises(Exception, match="already used"):
        arm(probe, a)
    late = authority("blue", count=8)
    late["challenge"] = "1" * 32
    probe.execute("frame=1208")  # one frame past the window: refused
    with pytest.raises(Exception, match="frame other than the one about to run"):
        arm(probe, late)


def test_window_service_arms_each_frame_closes_on_the_reached_row_and_declines_stale_commands(probe):
    a = authority("red", count=8)  # frames 1200..1207
    load(probe, "red", state("red"), "loop_head")
    probe.globals().command_json = json.dumps({"cmd": auth.COMMAND, "death_id": "d" * 32, "key": COMMAND["body"]["key"], "authority": a})
    probe.execute("""
        addr=JSON.decode(payload).a
        inbox={{command_id=string.rep('1',32),command_sequence=1,body={cmd='force_faint',death_id=string.rep('d',32),key='9A5F:1234:84'}},
               {command_id=string.rep('2',32),command_sequence=2,body=JSON.decode(command_json)}}
        completed={}
        journal={pending_commands=function()local out={};for _,e in ipairs(inbox)do if not e.outcome then out[#out+1]=e end end;return out end,
                 complete_command=function(_,id,outcome,receipt)
                     for _,e in ipairs(inbox)do if e.command_id==id then e.outcome=outcome;e.receipt=receipt end end
                     completed[#completed+1]={id=id,outcome=outcome,receipt=receipt};return true end}
        mem={BATTLE_FLAG_ADDR=addr.wIsInBattle,read_u8=function(address)return bus[address] or 0 end}
        S=require('battle_force_authority').service({journal=journal,memory=mem,owner_id=string.rep('a',32),held=function()return held end,
            unwrap=function(e)return e.body end})
    """)
    probe.execute("frame=1203")  # the command arrived three frames into its window
    assert probe.eval("S:arm()") is True and probe.eval("S:status().armed") is True
    assert probe.eval("S:finish() == nil") is True and probe.eval("S:status().armed") is True  # no frame ran: still armed
    run_frame(probe)
    row = json.loads(probe.eval("JSON.encode(S:finish())"))
    assert row["site"] is None and row["frame"] == 1203 and probe.eval("#completed") == 0 and probe.eval("S:status().rows") == 1
    assert probe.eval("S:arm()") is True
    hit(probe, "loop_head")
    run_frame(probe)
    row = json.loads(probe.eval("JSON.encode(S:finish())"))
    assert row["site"] == "loop_head" and probe.eval("#completed") == 1 and probe.eval("S:status().open") is False
    receipt = json.loads(probe.eval("JSON.encode(completed[1].receipt)"))
    assert receipt["schema"] == auth.RECEIPT and receipt["challenge"] == a["challenge"] and receipt["battle"] == 1 and receipt["frame"] == 1205
    assert [r["frame"] for r in receipt["rows"]] == [1203, 1204] and receipt["rows"][1]["site"] == "loop_head"
    assert auth.verify_window(a, receipt["rows"], hook_frame_offset=OFFSET)["outcome"] == "fainted"
    assert probe.eval("S:arm()") is False, "nothing pending any more"
    # a command whose window has passed closes declined (no rows), so the server re-issues from the receipt
    probe.execute("inbox[2].outcome=nil;completed={};frame=1300")
    assert probe.eval("S:arm()") is False and probe.eval("#completed") == 1
    declined = json.loads(probe.eval("JSON.encode(completed[1].receipt)"))
    assert declined["rows"] == [] and declined["frame"] == 1300 and declined["challenge"] == a["challenge"]
    probe.execute("inbox[2].outcome=nil;completed={};frame=1206;bus[addr.wIsInBattle]=0")  # inside the window but the battle is over
    assert probe.eval("S:arm()") is False and probe.eval("#completed") == 1 and json.loads(probe.eval("JSON.encode(completed[1].receipt)"))["battle"] == 0
    probe.execute("inbox[1].outcome='ACK';inbox[2].outcome=nil;completed={};bus[addr.wIsInBattle]=1")  # the death command already closed
    assert probe.eval("S:arm()") is False and probe.eval("#completed") == 1
    probe.execute("S:close()")
    assert probe.eval("next(hooks) == nil") is True
