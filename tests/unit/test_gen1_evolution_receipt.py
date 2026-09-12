"""Source-qualified full party evolution results, independent of identity policy."""

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime

from server.gen1_evolution_receipt import DATA, SCHEMA, rules_for, validate
from server.protocol_journal import JournalError
from tests.unit.test_gen1_capture_receipt import box_bytes, party_bytes
from tests.unit.test_gen1_party_codec import make_blob

ROOT = Path(__file__).resolve().parents[2]
IDENTITY = {"ot_id": "0000", "trainer_name": "SAME"}
NAME = "92808C8450000000000000"


def receipt(
    variant="yellow",
    *,
    species=4,
    level=5,
    outcome="evolved",
    slot=0,
    custom=False,
    blob=None,
    party=None,
    frame=130,
):
    policy = rules_for(variant, DATA["titles"][variant]["clean_sha1"])
    old = bytearray(
        blob or make_blob(policy.codec, species=species, level=level, otid=0, dv=0x1234)
    )
    if blob is None:
        old[44:55] = bytes.fromhex(NAME)
        if not custom:
            old[55:66] = policy._names[species]
    party = list(party) if party is not None else [bytes(old), make_blob(policy.codec, dv=0x4321)]
    old = policy.codec.validate_blob(party[slot])
    species = old.species_index
    selected = next(
        row
        for row in DATA["titles"][variant]["rules"]["entries"][str(species)]
        if row["method"] in (1, 2)
    )
    p = {
        "party_hex": party_bytes(party).hex().upper(),
        "box_hex": box_bytes([]).hex().upper(),
        "trainer_hex": NAME,
        "player_id_hex": "0000",
        "dex_hex": "00" * 38,
        "map_id": 33,
        "battle_flag": 0 if selected["method"] == 2 else 2,
        "link_state": 0,
        "slot": slot,
        "table_species": species,
        "current_item": selected["parameter"] if selected["method"] == 2 else 0,
        "force": 1 if selected["method"] == 2 else 0,
        "current_box": 0,
        "mon_location": 0,
    }
    before = {
        "frame": frame,
        "sp": 0xDFF0,
        "point": p,
        "selection": {"pointer": selected["pointer"], "level": old.level},
        "pc": DATA["titles"][variant]["sites"]["begin"]["address"],
        "bank": DATA["titles"][variant]["sites"]["begin"]["bank"],
    }
    after = copy.deepcopy(before)
    after.pop("selection")
    after["frame"] = frame + 20
    after.update(
        pc=DATA["titles"][variant]["sites"][outcome]["address"],
        bank=DATA["titles"][variant]["sites"][outcome]["bank"],
    )
    if outcome == "evolved":
        candidate = policy.evolution_outcomes(old.raw, selected["target"], allow_zero_hp=True)[0]
        party[slot] = candidate.blob
        after["point"]["party_hex"] = party_bytes(party).hex().upper()
        dex = bytearray(38)
        index = policy.codec.profile["species"][str(selected["target"])]["dex"] - 1
        for offset in (0, 19):
            dex[offset + index // 8] |= 1 << (index % 8)
        after["point"]["dex_hex"] = dex.hex().upper()
    return {
        "schema": SCHEMA,
        "source_sha256": DATA["sha256"],
        "variant": variant,
        "context_generation": "a" * 32,
        "physical_instance": "1" * 32,
        "final_sha1": DATA["titles"][variant]["clean_sha1"],
        "outcome": outcome,
        "before": before,
        "after": after,
    }


def decode(value, **options):
    return validate(
        value,
        variant=value["variant"],
        identity=IDENTITY,
        context_generation="a" * 32,
        physical_instance="1" * 32,
        final_sha1=value["final_sha1"],
        **options,
    )


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
@pytest.mark.parametrize(
    "species,level,outcome", [(4, 5, "evolved"), (153, 16, "evolved"), (153, 16, "cancelled")]
)
@pytest.mark.parametrize("custom", [False, True])
def test_level_stone_and_cancel_receipts_preserve_complete_members_and_current_box(
    variant, species, level, outcome, custom
):
    value = receipt(variant, species=species, level=level, outcome=outcome, custom=custom)
    fact = decode(value)
    assert fact["kind"] == "evolution" and fact["outcome"] == outcome
    assert fact["outgoing"]["key"][:10] == fact["incoming"]["key"][:10]
    assert (fact["outgoing"]["key"] != fact["incoming"]["key"]) == (outcome == "evolved")
    if custom:
        assert (
            bytes.fromhex(fact["outgoing"]["blob_hex"])[55:]
            == bytes.fromhex(fact["incoming"]["blob_hex"])[55:]
        )


@pytest.mark.parametrize(
    "fault",
    [
        "other_mon",
        "unused_party",
        "current_box",
        "dex",
        "dv",
        "ot",
        "level",
        "selection",
        "frame",
        "stack",
        "context",
        "location",
        "trade",
        "force_cancel",
        "target",
    ],
)
def test_changed_source_or_any_unpermitted_result_refuses(fault):
    value = receipt(
        species=153, level=16, outcome="cancelled" if fault == "force_cancel" else "evolved"
    )
    if fault in ("other_mon", "unused_party", "dv", "ot", "level"):
        offsets = {"other_mon": 53, "unused_party": 240, "dv": 35, "ot": 20, "level": 41}
        raw = bytearray.fromhex(value["after"]["point"]["party_hex"])
        raw[offsets[fault]] ^= 1
        value["after"]["point"]["party_hex"] = raw.hex().upper()
    elif fault == "current_box":
        value["after"]["point"]["box_hex"] = "01" + value["after"]["point"]["box_hex"][2:]
    elif fault == "dex":
        value["after"]["point"]["dex_hex"] = "00" * 38
    elif fault == "selection":
        value["before"]["selection"]["pointer"] += 1
    elif fault == "frame":
        value["after"]["frame"] = 1
    elif fault == "stack":
        value["after"]["sp"] += 2
    elif fault == "context":
        value["context_generation"] = "b" * 32
    elif fault == "location":
        value["before"]["point"]["mon_location"] = 1
    elif fault == "trade":
        value["before"]["point"]["link_state"] = 0x32
    elif fault == "force_cancel":
        value["before"]["point"]["force"] = value["after"]["point"]["force"] = 1
    else:
        value["before"]["point"]["table_species"] = 4
    with pytest.raises(JournalError):
        decode(value)


@pytest.mark.parametrize("variant", ["red", "blue"])
def test_source_verified_red_blue_in_battle_item_evolution_bug_remains_cartridge_faithful(variant):
    value = receipt(variant)
    for key in ("before", "after"):
        value[key]["point"].update(force=0, battle_flag=1)
    assert decode(value)["method"] == 2
    yellow = receipt("yellow")
    for key in ("before", "after"):
        yellow[key]["point"].update(force=0, battle_flag=1)
    with pytest.raises(JournalError, match="cartridge condition"):
        decode(yellow)


def test_following_starter_pikachu_is_not_stone_evolved_and_local_collision_refuses():
    with pytest.raises(JournalError, match="starter refuses"):
        decode(receipt("yellow", species=84))
    value = receipt()
    candidate = bytes.fromhex(decode(value)["incoming"]["blob_hex"])
    box = box_bytes([candidate[:33] + candidate[44:]]).hex().upper()
    value["before"]["point"]["box_hex"] = value["after"]["point"]["box_hex"] = box
    with pytest.raises(JournalError, match="colliding"):
        decode(value)


def test_ordinary_fainted_evolution_can_remain_at_zero_hp_without_relaxing_trade_results():
    from server.gen1_party_codec import PartyCodecError
    from server.stat_experience import calculate_stat, split_dvs

    policy = rules_for("red", DATA["titles"]["red"]["clean_sha1"])
    species = next(int(k) for k, v in policy.codec.profile["species"].items() if v["dex"] == 10)
    raw = bytearray(make_blob(policy.codec, species=species, level=7, dv=0x0110))
    raw[1:3] = bytes(2)
    raw[17:27] = bytes(10)
    old = policy.codec.validate_blob(bytes(raw))
    values = [
        calculate_stat(base, dv, old.level, 0, hp=i == 0)
        for i, (base, dv) in enumerate(
            zip(
                policy.codec.profile["species"][str(species)]["base_stats"],
                split_dvs(old.dv_word),
                strict=True,
            )
        )
    ]
    for offset, value in zip(range(34, 44, 2), values, strict=True):
        raw[offset : offset + 2] = value.to_bytes(2, "big")
    value = receipt("red", party=[bytes(raw)], blob=bytes(raw), frame=130)
    fact = decode(value)
    assert bytes.fromhex(fact["incoming"]["blob_hex"])[1:3] == bytes(2)
    with pytest.raises(PartyCodecError):
        policy.evolution_outcomes(bytes(raw), fact["table_target"])


def test_exact_admitted_rom_table_is_used_when_upr_changes_the_evolution_threshold():
    value = receipt("red", species=153, level=15)
    with pytest.raises(JournalError, match="level"):
        decode(value)
    lock = json.loads((ROOT / "data/pret_sources.lock.json").read_text())
    rom = bytearray((ROOT / lock["clean_roms"]["pokered"]["filename"]).read_bytes())
    entry = DATA["titles"]["red"]["rules"]["entries"]["153"][0]
    offset = DATA["titles"]["red"]["table"]["bank"] * 0x4000 + entry["pointer"] - 0x4000 - 1
    rom[offset] = 15
    value["final_sha1"] = hashlib.sha1(rom).hexdigest()
    assert decode(value, rom=bytes(rom))["method"] == 1
    with pytest.raises(JournalError, match="complete admitted ROM"):
        decode(value)


def test_source_generator_reproduces_original_rom_anchors_and_complete_rules():
    result = subprocess.run(
        [sys.executable, "tools/gen_gen1_evolution_sites.py", "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_real_observer_publishes_only_complete_attempts_and_skips_native_trade_context():
    value = receipt()
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().root = ROOT.as_posix()
    lua.globals().raw_json = json.dumps(value)
    lua.execute("""
        package.path=root..'/lua/?.lua;'..root..'/data/games/gen1_rby/?.lua;'..package.path
        JSON=require('json_codec');Data=require('gen1_evolution_sites');profile=Data.titles.yellow;input=JSON.decode(raw_json)
        bus={};rom={};hooks={};registers={};current_frame=0;owner_calls=0
        function put(a,hex,d)for i=1,#hex,2 do(d=='ROM'and rom or bus)[a+(i-1)/2]=tonumber(hex:sub(i,i+1),16)end end
        memory={read_u8=function(a,d)return(d=='ROM'and rom or bus)[a]or 0 end,write_u8=function()error('observer wrote')end}
        emu={getregister=function(n)return registers[n]or 0 end,framecount=function()return current_frame end}
        gameinfo={getromhash=function()return input.final_sha1 end}
        event={on_bus_exec=function(fn,a,name)hooks[name]=fn;return name end,unregisterbyid=function(id)hooks[id]=nil end}
        for _,site in pairs(profile.sites)do put(site.rom_offset,site.expected_hex,'ROM');put(site.address,site.expected_hex)end
        function load(w)
            current_frame=w.frame;registers.PC=w.pc;registers.SP=w.sp;bus[profile.addresses.hLoadedROMBank]=w.bank
            for field,name in pairs({party_hex='wPartyDataStart',box_hex='wBoxDataStart',trainer_hex='wPlayerName',player_id_hex='wPlayerID',dex_hex='wPokedexOwned'})do put(profile.addresses[name],w.point[field])end
            for field,name in pairs({map_id='wCurMap',battle_flag='wIsInBattle',link_state='wLinkState',slot='wWhichPokemon',table_species='wEvoOldSpecies',
                current_item='wCurItem',force='wForceEvolution',current_box='wCurrentBoxNum',mon_location='wMonDataLocation'})do bus[profile.addresses[name]]=w.point[field]end
            if w.selection then registers.A=w.selection.level;registers.H=math.floor(w.selection.pointer/256);registers.L=w.selection.pointer%256 end
        end
        observer=require('gen1_evolution_observer').new({variant='yellow',final_sha1=input.final_sha1,held=function()return true end,
            owned=function()owner_calls=owner_calls+1;return{context_generation=input.context_generation,physical_instance=input.physical_instance}end})
        load(input.before);bus[profile.addresses.wLinkState]=50;local old=owner_calls;hooks['slink-evolution-begin']()
        assert(owner_calls==old and observer.status().in_flight==0)
        load(input.before);hooks['slink-evolution-begin']();assert(observer.status().in_flight==1 and #observer.peek()==0)
        load(input.after);hooks['slink-evolution-evolved']();assert(observer.status().in_flight==0 and #observer.peek()==1)
        output=JSON.encode(observer.peek()[1]);assert(observer.acknowledge(observer.peek()));assert(#observer.peek()==0)
        observer.close();assert(next(hooks)==nil)
    """)
    assert json.loads(lua.globals().output) == value
