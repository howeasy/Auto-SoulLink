"""GIFT-EGG-ROWS-G3: SOURCE/MODEL controls; no emulator launches."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.unit import gen3_world as gw
from tests.unit.gen3_world import World, key_of, mon_record

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
TITLES = [("gen3_frlg", "firered", "clean"), ("gen3_frlg", "leafgreen", "clean"),
          ("gen3_emerald", "emerald", "clean"), ("gen3_rr", "radical_red", "clean"),
          ("gen3_rr", "radical_red", "companion")]
OT = 0xABCD
LEAD = mon_record(0x11111111, OT)
EGG = mon_record(0x22222222, OT, is_egg=1)


def world(monkeypatch, pack, title, kind, *, boot_egg=False):
    w = World(pack, title, kind)
    w.set_party([LEAD, EGG] if boot_egg else [LEAD])
    w.step_to(60)
    assert w.client.writes_enabled
    return w


@pytest.mark.parametrize("pack,title,kind", TITLES)
def test_native_giveegg_does_not_publish_a_capture(monkeypatch, pack, title, kind):
    w = world(monkeypatch, pack, title, kind)
    w.set_party([LEAD, EGG])
    w.fire("mon_given")
    w.step(60)
    assert w.events("capture") == []
    assert w.events("faint") == []


@pytest.mark.parametrize("pack,title,kind", TITLES)
@pytest.mark.parametrize("boot_egg", [False, True])
def test_hatch_signal_publishes_exactly_one_daycare_capture(monkeypatch, pack, title, kind, boot_egg):
    w = world(monkeypatch, pack, title, kind, boot_egg=boot_egg)
    if not boot_egg:
        w.set_party([LEAD, EGG])
        w.fire("mon_given")
        w.step(60)
    assert w.events("capture") == []
    # Native AddHatchedMonToParty has finished CalculateMonStats. R5 is its mon.
    w.set_party([LEAD, dict(EGG, is_egg=0, is_egg_flag=0, friendship=120)])
    w.regs["R5"] = w.party_base() + 100
    w.fire("hatch")
    w.step()
    (cap,) = w.events("capture")
    assert (cap["key"], cap["area_id"], cap["gift"], cap["is_egg"]) == (
        key_of(EGG["personality"], OT), "gift_daycare", True, False)
    w.fire("hatch")
    w.fire("mon_given")
    w.step(60)
    assert len(w.events("capture")) == 1


@pytest.mark.parametrize("pack,title,kind", TITLES)
def test_boxed_egg_withdrawal_does_not_absorb_its_future_hatch(monkeypatch, pack, title, kind):
    w = world(monkeypatch, pack, title, kind)
    w.set_box(0, 0, EGG)
    w.fire("mon_given")
    w.step(5)
    assert w.events("capture") == []
    w.set_box(0, 0, None)
    w.set_party([LEAD, EGG])
    w.fire("pc_withdraw")
    w.step(60)
    w.set_party([LEAD, dict(EGG, is_egg=0, is_egg_flag=0)])
    w.regs["R5"] = w.party_base() + 100
    w.fire("hatch")
    w.step()
    assert [e["area_id"] for e in w.events("capture")] == ["gift_daycare"]


def test_a_different_gift_signal_cannot_acquire_a_pending_hatch(monkeypatch):
    w = world(monkeypatch, "gen3_frlg", "firered", "clean", boot_egg=True)
    w.set_party([LEAD, dict(EGG, is_egg=0, is_egg_flag=0)])
    w.fire("mon_given")
    w.step()
    assert w.events("capture") == []
    w.regs["R5"] = w.party_base() + 100
    w.fire("hatch")
    w.step()
    assert [e["area_id"] for e in w.events("capture")] == ["gift_daycare"]


@pytest.mark.parametrize("fault", ["bad_pointer", "still_egg", "bad_egg", "reset"])
def test_invalid_hatch_observation_never_publishes(monkeypatch, fault):
    w = world(monkeypatch, "gen3_frlg", "firered", "clean", boot_egg=True)
    mon = dict(EGG, is_egg=0, is_egg_flag=0)
    if fault == "still_egg":
        mon = EGG
    if fault == "bad_egg":
        mon["is_bad_egg"] = 1
    w.set_party([LEAD, mon])
    w.regs["R5"] = w.party_base() + (101 if fault == "bad_pointer" else 100)
    w.fire("hatch")
    if fault == "reset":
        w.client.driver.on_reset()
    w.step(5)
    assert w.events("capture") == []


@pytest.mark.parametrize("game", ["gen3_frlg", "gen3_lgfr", "gen3_emerald", "gen3_rr"])
@pytest.mark.parametrize("name", ["gift_gen3", "egg_hatch_gen3"])
def test_gift_and_hatch_rows_have_native_carriers_and_saved_oracles(game, name):
    import e2e_duo as duo
    assert duo.scenario_applies(name, game)
    row = duo.SCENARIOS[name]
    assert callable(getattr(duo.DuoRun, row["oracle"], None))
    assert callable(getattr(duo.DuoRun, "orchestrate_" + name, None))
    assert (ROOT / f"lua/tests/duo/scenario_gen3_{row['scenario_module']}.lua").is_file()


def rom_for(title):
    from tools.pin_gen3_site import EMERALD_SPECS, ROM_SPECS
    return next(row[3] for row in (ROM_SPECS | EMERALD_SPECS).values() if row[1:3] == (title, "clean"))


@pytest.mark.parametrize("title", ["firered", "leafgreen", "emerald", "radical_red"])
@pytest.mark.parametrize("kind", ["gift", "hatch"])
def test_disclosed_seed_uses_own_title_flags_and_preserves_native_egg_state(title, kind):
    from server.adapters import gen3_codec as c
    from tools.gen3_gift_egg_rows import build_seed, title_facts
    stem = {"firered": "firered_party_town", "leafgreen": "leafgreen_party_town",
            "emerald": "emerald_town", "radical_red": "rr_town"}[title]
    seed = (ROOT / f"tests/fixtures/gen3/{stem}.sav").read_bytes()
    rom = rom_for(title).read_bytes()
    result, manifest = build_seed(seed, title, kind, rom)
    rr = title == "radical_red"
    layout = "emerald" if title == "emerald" else "frlg"
    before = c.rr_party_from_save(seed) if rr else c.party_from_save(seed, title=layout)
    after = c.rr_party_from_save(result) if rr else c.party_from_save(result, title=layout)
    assert after[0] == before[0]
    assert all(line.startswith("SYNTH ") for line in manifest)
    assert result[28 * c.SECTOR_SIZE:] == seed[28 * c.SECTOR_SIZE:]
    facts = title_facts(rom, title)
    assert facts["species"] == (398 if title == "emerald" else 129)
    assert facts["flag"] == {"firered": 0x249, "leafgreen": 0x249, "emerald": 0x12A, "radical_red": 0x98E}[title]
    if kind == "hatch":
        assert len(after) == 2 and after[1]["is_egg"] == after[1]["is_egg_flag"] == 1
        assert after[1]["friendship"] == 0 and after[1]["species"] == before[0]["species"]
        assert facts["hatch_level"] == (1 if rr else 5)
    else:
        assert after == before  # native receipt has not happened yet


@pytest.mark.parametrize("title", ["firered", "leafgreen", "emerald", "radical_red"])
def test_wrong_gift_script_and_hatch_callback_are_not_borrowed(title):
    from tools.gen3_gift_egg_rows import GIFTS, HATCH_CALLBACKS, title_facts
    for address in (GIFTS[title]["script"], HATCH_CALLBACKS[title]):
        rom = bytearray(rom_for(title).read_bytes())
        rom[address - 0x08000000] ^= 1
        with pytest.raises(ValueError, match="unproven|not the reviewed"):
            title_facts(bytes(rom), title)


def test_rr_gift_flag_uses_its_native_extended_bank_not_sb1_vars():
    from server.adapters import gen3_codec as c
    from tools.gen3_gift_egg_rows import build_seed, saved_gift_flag, title_facts
    seed = bytearray((ROOT / "tests/fixtures/gen3/rr_town.sav").read_bytes())
    p = c.parse_flash(seed, cfru=True)
    sector = next(s for s in p["sectors"][14*p["slot"]:14*(p["slot"]+1)] if s["id"] == 0)
    # RR GetFlagAddr: [0203B174 + (098E-0900)/8], mask 40. Native
    # serializer puts parasite[11] at section0+F24+11 = section0+F35.
    offset = sector["index"] * 0x1000 + 0xF35
    seed[offset] = 0xFF  # parasite is outside the section's checksum
    assert c.qualify_flash(bytes(seed), cfru=True)[0]
    rom = rom_for("radical_red").read_bytes()
    result, _ = build_seed(bytes(seed), "radical_red", "gift", rom)
    assert result[offset] == 0xBF
    assert c.parse_flash(result, cfru=True)["sb1"][0x1011] == p["sb1"][0x1011]
    assert title_facts(rom, "radical_red")["flag_address"] == 0x0203B185
    facts = title_facts(rom, "radical_red")
    assert saved_gift_flag(bytes(seed), "radical_red", facts) is True
    assert saved_gift_flag(result, "radical_red", facts) is False


def test_all_committed_synth_fixtures_regenerate_with_the_disclosed_manifest():
    import hashlib

    from tools.gen3_gift_egg_rows import build_seed
    directory = ROOT / "tests/fixtures/gen3"
    manifest = json.loads((directory / "gift_egg_synth_manifest.json").read_text())
    assert manifest["evidence"] == "SYNTH_SETUP_ONLY" and len(manifest["fixtures"]) == 12
    for entry in manifest["fixtures"]:
        seed = (directory / entry["seed"]).read_bytes()
        assert hashlib.sha256(seed).hexdigest() == entry["seed_sha256"]
        actual, edits = build_seed(seed, entry["title"], entry["kind"], rom_for(entry["title"]).read_bytes())
        assert actual == (directory / entry["file"]).read_bytes()
        assert hashlib.sha256(actual).hexdigest() == entry["sha256"] and edits == entry["manifest"]


@pytest.mark.parametrize("game", ["gen3_frlg", "gen3_lgfr", "gen3_emerald", "gen3_rr"])
@pytest.mark.parametrize("scenario", ["gift_gen3", "egg_hatch_gen3"])
def test_real_generated_lua_stub_loads_in_lupa(monkeypatch, tmp_path, game, scenario):
    import e2e_duo as duo
    import gen3_fixtures
    from lupa import LuaRuntime

    from tests.unit.test_e2e_duo_lane_isolation import _args
    monkeypatch.setattr(duo, "BUILD", str(tmp_path))
    monkeypatch.setattr(duo, "REPO", str(tmp_path))
    monkeypatch.setattr(gen3_fixtures, "write_gba_run_config", lambda *a: None)
    launched = []
    monkeypatch.setattr(duo.subprocess, "Popen", lambda *a, **kw: launched.append(a) or SimpleNamespace())
    run = duo.DuoRun(scenario, _args(game=game, scenario=scenario, lane="gift-egg"))
    run._gen3_rom = lambda i: str(rom_for(run._gen3_title(i)))
    run._rom_for = run._gen3_rom
    for side in ("a", "b"):
        run.launch_instance(side, seed=False)
        lua = LuaRuntime()
        lua.execute("dofile=function(path) loaded_main=path end")
        lua.execute(Path(run.stub_path(side)).read_text())
        d = lua.globals().SLINK_DUO
        assert d.title == run._gen3_title(side) and d.acquisition_kind == run.cfg["acquisition_kind"]
        assert d.acquisition_facts.flag == (0x98E if game == "gen3_rr" else 0x12A if game == "gen3_emerald" else 0x249)
        assert lua.globals().loaded_main.endswith("lua/tests/duo/duo_gen3_main.lua")
    assert len(launched) == 2  # recorded Popen, never a real emulator


def oracle_case(monkeypatch, tmp_path, kind):
    from server.adapters import gen3_codec as c
    from tests.unit.test_e2e_duo_gen3 import STARTER, _fixture, _key, _mon, _oracle_stub, _saved
    from tools import gen3_gift_egg_rows as row
    subject = _mon(0xAABBCCDD, species=129 if kind == "gift" else 7)
    pre = dict(subject, is_egg=1, is_egg_flag=1, friendship=0) if kind == "hatch" else None
    fixture = _fixture([STARTER, pre] if pre else [STARTER])
    saved = _saved(fixture, 3, [STARTER, subject])
    facts = row.title_facts(rom_for("firered").read_bytes(), "firered")
    if kind == "gift":
        # Independent engine-result flash, including seller's money and flag.
        p = c.parse_flash(saved)
        sb1 = bytearray(p["sb1"])
        sb1[0xEE0 + 0x249 // 8] |= 1 << (0x249 % 8)
        xor = int.from_bytes(p["sb2"][0xF20:0xF24], "little")
        sb1[0x290:0x294] = (500 ^ xor).to_bytes(4, "little")
        body, layout = bytearray(saved), c.slot_layout()
        for entry in layout:
            if entry["object"] != "sb1":
                continue
            sector = next(s for s in p["sectors"][14 * p["slot"]:14 * (p["slot"] + 1)] if s["id"] == entry["id"])
            offset = sector["index"] * c.SECTOR_SIZE
            body[offset:offset + c.SECTOR_SIZE] = c.write_sector(
                sb1[entry["offset"]:entry["offset"] + entry["size"]], entry["id"], p["counter"], layout)
        saved = bytes(body)
    area = "gift_daycare" if kind == "hatch" else "route_4_pokecenter"
    key = _key(subject)
    links = [{"a": {"key": key}, "b": {"key": key}, "status": "alive", "area_id": area}]
    raw = {"a": saved, "b": saved}
    run, notes = _oracle_stub(monkeypatch, tmp_path, "egg_hatch_gen3" if kind == "hatch" else "gift_gen3", raw, fixture, links)
    run._acquisition_facts = {"a": facts, "b": facts}
    cap = {"event": "capture", "key": key, "species_id": subject["species"], "area_id": area,
               "level": 5, "gift": True, "is_egg": False, "held_item_id": 0, "nickname": "MON"}
    def mark(tag, value):
        return tag + " " + json.dumps(value) + "\n"
    text = (mark("ACQUISITION_BEFORE", {"captures": 0, "balls": 4, "egg": int(kind == "hatch")})
            + mark("ACQUISITION_SIGNAL", {"kind": "hatch" if kind == "hatch" else "mon_given"})
            + mark("TX capture " + key, cap)
            + mark("ACQUISITION_AFTER", {"balls": 4, "egg": 0, "scene": kind == "hatch", "steps": 256, "flag": True})
            + mark("ACQUISITION_READY", cap))
    return row, run, {"a": text, "b": text}, raw, notes


@pytest.mark.parametrize("kind", ["gift", "hatch"])
def test_acquisition_oracle_requires_native_signal_wire_link_and_flash(monkeypatch, tmp_path, kind):
    row, run, results, _, notes = oracle_case(monkeypatch, tmp_path, kind)
    row.saved_oracle(run, results)
    assert notes and "independent saved" in notes[-1]


@pytest.mark.parametrize("old,new", [('"captures": 0', '"captures": 1'),
                                   ('"scene": true', '"scene": false'),
                                   ('"steps": 256', '"steps": 0'),
                                   ('"gift": true', '"gift": false'),
                                   ('"gift_daycare"', '"route_1"'),
                                   ('"kind": "hatch"', '"kind": "mon_given"')])
def test_hatch_oracle_refuses_missing_acquisition_evidence(monkeypatch, tmp_path, old, new):
    row, run, results, _, _ = oracle_case(monkeypatch, tmp_path, "hatch")
    results["a"] = results["a"].replace(old, new)
    with pytest.raises(RuntimeError):
        row.saved_oracle(run, results)


def test_hatch_oracle_refuses_a_saved_egg_despite_green_markers(monkeypatch, tmp_path):
    row, run, results, raw, _ = oracle_case(monkeypatch, tmp_path, "hatch")
    raw["a"] = run._gen3_fixture_bytes("a")
    with pytest.raises(RuntimeError, match="still an egg"):
        row.saved_oracle(run, results)


def test_saved_gift_link_cannot_cross_player_ownership(monkeypatch, tmp_path):
    from tests.unit.test_e2e_duo_gen3 import STARTER, _fixture, _key, _mon, _saved
    row, run, results, raw, _ = oracle_case(monkeypatch, tmp_path, "hatch")
    original_fixture = run._gen3_fixture_bytes("a")
    old_key = json.loads(results["a"].split("ACQUISITION_READY ")[1])["key"]
    second = _mon(0xDEADBEEF, species=7)
    second_egg = dict(second, is_egg=1, is_egg_flag=1, friendship=0)
    second_fixture = _fixture([STARTER, second_egg])
    run._gen3_fixture_bytes = lambda side: original_fixture if side == "a" else second_fixture
    raw["b"] = _saved(second_fixture, 3, [STARTER, second])
    new_key = _key(second)
    results["b"] = results["b"].replace(old_key, new_key)
    (tmp_path / "links.json").write_text(json.dumps({"links": [{"a": {"key": new_key}, "b": {"key": old_key},
        "area_id": "gift_daycare", "status": "alive"}]}))
    with pytest.raises(RuntimeError, match="player ownership"):
        row.saved_oracle(run, results)


@pytest.mark.parametrize("title", ["firered", "leafgreen", "emerald", "radical_red"])
def test_fixed_gift_bypasses_clauses_but_pending_shiny_bonus_does_not(tmp_path, title):
    from server.adapters.gen3_frlge import Gen3Adapter
    from server.state import SoulLinkState
    from tools.gen3_gift_egg_rows import title_facts
    facts = title_facts(rom_for(title).read_bytes(), title)
    adapter = Gen3Adapter(is_rr=title == "radical_red", rom_type=title)
    def state(name):
        return SoulLinkState(data_dir=str(tmp_path / name), adapter=adapter,
                             species_lock=True, gender_lock=True, type_lock=True)
    def cap(key):
        return {"event": "capture", "key": key, "species_id": facts["species"], "area_id": facts["area"],
                    "level": 5, "gift": True, "is_egg": False}
    normal = state("normal")
    normal.handle_event("a", cap("11223344:0000ABCD"))
    normal.handle_event("b", cap("22334455:0000ABCD"))
    assert len(normal.links) == 1 and normal.links[0].area_id == facts["area"]
    shiny = state("shiny")
    shiny.handle_event("a", cap("0000ABCD:0000ABCD"))
    assert len(shiny.links) == 0 and shiny.pending_bonus["b"]
    commands = shiny.handle_event("b", cap("22334455:0000ABCD"))
    assert any(c["cmd"] == "force_faint" for c in commands)
    assert len(shiny.links) == 0 and shiny.pending_bonus["b"]


@pytest.mark.parametrize("title", ["firered", "leafgreen", "emerald", "radical_red"])
@pytest.mark.parametrize("kind", ["gift", "hatch"])
def test_native_carrier_executes_under_lupa_with_own_title_facts(title, kind):
    from lupa import LuaRuntime

    from tools.e2e_duo import lua_literal
    from tools.gen3_gift_egg_rows import title_facts
    lua = LuaRuntime(unpack_returned_tuples=True)
    facts = title_facts(rom_for(title).read_bytes(), title)
    lua.execute("facts=" + lua_literal(facts) + "; kind=" + lua_literal(kind))
    scenario = lua.execute((ROOT / "lua/tests/duo/scenario_gen3_gift_egg.lua").read_text())
    ctx = lua.execute('''
        local f=facts
        local party={{key="lead",slot=0,species=7,hp=20,is_egg=0}}
        if kind=="hatch" then party[2]={key="egg",slot=1,species=7,hp=20,is_egg=1,friendship=0} end
        local cap, scene, field, flag, steps = nil,false,true,false,0
        local x,y = kind=="hatch" and f.hatch_x or f.x, kind=="hatch" and f.hatch_y or f.y
        local c={D={acquisition_facts=f,acquisition_kind=kind}, cp={predicates={callback2={address=1,offset=4}}},
                 reader={},G={},session={signals={drain=function() return {{kind=kind=="hatch" and "hatch" or "mon_given",address=123,frame=1}} end}}, marks={}}
        memory={read_u32_le=function() return scene and f.hatch_callback or 0 end,
                read_u8=function(address) assert(address==f.flag_address);return flag and f.flag_mask or 0 end}
        c.party=function() local out={};for i,m in ipairs(party) do out[i]=m end;return out end
        c.find=function(key) for _,m in ipairs(party) do if m.key==key then return m end end end
        c.sent=function(event,key) return event=="capture" and cap and (not key or key==cap.key) and 1 or 0 end
        c.last_sent=function() return cap end
        c.balls=function() return 5 end
        c.game_flag=function() return flag end
        c.wait_go=function() return true end
        c.face=function(dir) assert(dir==f.face);return true end
        c.on_field=function() return field end
        c.player_idle=function() return true end
        c.in_battle=function() return false end
        c.fail=function(why) error(why) end
        c.reader.read_location=function() return {map_group=f.group,map_num=f.num} end
        c.G.pos=function() return x,y end
        c.G.pred_ok=function() return field end
        c.jlog=function(tag,value) c.marks[tag]=value end
        c.G.tap=function(button)
            if not cap then
                assert(button==(kind=="gift" and "A" or "Right"))
                if kind=="hatch" then
                    x=x+1; steps=steps+1; scene=true; field=false
                    party[2].is_egg=0;party[2].level=f.hatch_level
                else party[2]={key="gift",slot=1,species=f.species,is_egg=0,level=f.level} end
                c.session.signals:drain()
                cap={event="capture",key=party[2].key,species_id=party[2].species,level=party[2].level,
                     area_id=kind=="hatch" and "gift_daycare" or f.area,gift=true,is_egg=false}
            else assert(button=="B");flag=true;field=true end
        end
        c.wait_until=function(pred) for i=1,20 do local r=pred();if r then return r end end end
        c.mash_until=function(pred,_,button)
            for i=1,20 do local r=pred();if r then return r end;c.G.tap(button) end
        end
        c.save=function(label) c.saved=label;return true,"saved" end
        return c
    ''')
    assert scenario(ctx) == (True, "saved")
    assert ctx.saved == kind and ctx.marks.ACQUISITION_BEFORE.captures == 0
    assert ctx.marks.ACQUISITION_READY.is_egg is False
    if kind == "hatch":
        assert ctx.marks.ACQUISITION_AFTER.scene is True and ctx.marks.ACQUISITION_AFTER.steps == 1
