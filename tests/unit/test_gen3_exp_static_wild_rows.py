"""Own-build static/wild setup and method tables; physical selection is separate."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from tools import gen3_static_wild_rows as rows

ROOT = Path(__file__).resolve().parents[2]


ARTIFACTS = SOURCE = None  # Resolved by the fixture at call time, after environment overrides.


@pytest.fixture(scope="module")
def pinned_inputs():
    from tools import gen_gen3_profile as profile

    global ARTIFACTS, SOURCE
    ARTIFACTS = Path(os.environ.get("SLINK_EXPANSION_ARTIFACTS", ROOT / ".cache/expansion-output/reference"))
    SOURCE = Path(os.environ.get("SLINK_EXPANSION_SRC", ROOT / ".cache/expansion-src"))
    for required in (SOURCE, *(ARTIFACTS / name for name in ("pokeemerald.gba", "pokeemerald.sym", "pokeemerald.map"))):
        if not required.exists():
            pytest.skip(f"local copyrighted expansion inputs absent: {required}")
    context = profile.expansion_inputs(artifacts=ARTIFACTS)  # wrong-present fails identity, never skips
    assert subprocess.check_output(["git", "-C", str(SOURCE), "rev-parse", "HEAD"], text=True).strip() == context["facts"]["provenance"]["source_commit"]
    assert not subprocess.check_output(["git", "-C", str(SOURCE), "status", "--porcelain", "--untracked-files=no"], text=True).strip()
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("SLINK_EXPANSION_SRC", str(SOURCE))
        yield


@pytest.mark.parametrize(
    "case", ["static", "static_run", "grass", "surf", "rock", "fish", "altering0", "altering1"]
)
def test_static_wild_case_binds_rom_tiles_and_pending_seed(case, pinned_inputs):
    rom = (ARTIFACTS / "pokeemerald.gba").read_bytes()
    facts = rows.facts(rom, case)
    assert facts["area"] and facts["x"] >= 0
    assert (SOURCE / "data/maps" / facts["map"] / "map.json").is_file()
    if case == "fish":
        assert facts["task_size"] == 40 and facts["task_count"] == 16
    else:
        assert "fishing_task" not in facts
    body, edits = rows.build_seed((ROOT / "tests/fixtures/gen3/exp_pc.sav").read_bytes(), case, rom)
    assert edits and not rows.seed_problems(body, facts)
    if case.startswith("altering"):
        assert facts["projection_scope"] == "set0; nonzero is selection-characterization only"


def test_static_native_trace_requires_actual_slot_method_and_ball_debit():
    f={"case":"static","method":"static","slots":[(30,30,101)],"area":"aqua_hideout"}
    cap={"key":"a:b","area_id":"aqua_hideout","species_id":101,"level":30}
    def mark(tag,doc):return tag+" "+json.dumps(doc)+"\n"
    text=(mark("STATIC_WILD_BEFORE",{"balls":20,"captures":0,"no_catch":0})
          +mark("STATIC_WILD_BATTLE",{"method":"static","species":101,"level":30,"field_probe":True})
          +"TX capture a:b "+json.dumps(cap)+"\n"
          +mark("STATIC_WILD_AFTER",{"balls":19}))
    assert rows.trace_problems(text,f)==[]
    for changed in (text.replace('"species_id": 101','"species_id": 100'),
                    text.replace('"species": 101','"species": 100'),
                    text.replace('"field_probe": true','"field_probe": false'),
                    text.replace('"balls": 19','"balls": 20'),
                    text+'TX capture bad {malformed\n'):
        assert rows.trace_problems(changed,f)


def test_static_run_trace_is_a_negative_and_must_not_publish_capture():
    f={"case":"static_run","method":"static","slots":[(30,30,101)],"area":"aqua_hideout"}
    def mark(tag,doc):return tag+" "+json.dumps(doc)+"\n"
    text=(mark("STATIC_WILD_BEFORE",{"balls":20,"captures":0,"no_catch":0})
          +mark("STATIC_WILD_BATTLE",{"method":"static","species":101,"level":30,"field_probe":True})
          +'TX no_catch - {"event":"no_catch","area_id":"aqua_hideout","species_id":101,"level":30}\n'
          +mark("STATIC_WILD_AFTER",{"balls":20}))
    assert rows.trace_problems(text,f)==[]
    assert rows.trace_problems(text.replace('TX no_catch','TX capture'),f)


def test_direct_fixture_cli_resolves_this_worktree_modules():
    import subprocess
    import sys
    result=subprocess.run([sys.executable,str(ROOT/"tools/gen3_static_wild_rows.py"),"--help"],capture_output=True,text=True)
    assert result.returncode==0, result.stderr


def test_native_pending_seed_manifest_binds_all_cases_and_private_inputs(pinned_inputs):
    import hashlib

    manifest=json.loads((ROOT/"tests/fixtures/gen3/exp_static_wild_synth_manifest.json").read_text())
    assert {(r["case"],r["side"])for r in manifest["fixtures"]}=={(c,s)for c in rows.CASES for s in ("a","b")}
    rom=(ARTIFACTS/"pokeemerald.gba").read_bytes()
    for entry in manifest["fixtures"]:
        raw=(ROOT/entry["file"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==entry["sha256"]
        assert hashlib.sha256((ROOT/entry["seed"]).read_bytes()).hexdigest()==entry["seed_sha256"]
        derived, _ = rows.build_seed((ROOT / entry["seed"]).read_bytes(), entry["case"], rom)
        assert hashlib.sha256(derived).hexdigest() == entry["generator_raw_sha256"]
        flipped = bytearray(derived)
        flipped[0] ^= 1
        assert hashlib.sha256(flipped).hexdigest() != entry["generator_raw_sha256"]
        assert not rows.seed_problems(raw,rows.facts(rom,entry["case"]))


def test_capture_reward_changes_only_lead_exact_source_ev_yield():
    import copy
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    import e2e_duo as h

    old = h.gen3_decode((ROOT / "tests/fixtures/gen3/exp_static_static_synth.sav").read_bytes(),
                       title="emerald_expansion_28877d73")[0]
    f = {"case": "static", "ev_yields": {101: {k: (2 if k == "speed" else 0) for k in old[0]["evs"]}}}
    now = copy.deepcopy(old)
    now[0]["evs"]["speed"] += 2
    assert rows.party_control_problems(old, now, f, {"species": 101}) == []
    for slot, stat, delta in ((0, "speed", 1), (0, "hp", 1), (1, "speed", 2)):
        bad = copy.deepcopy(now)
        bad[slot]["evs"][stat] += delta
        assert rows.party_control_problems(old, bad, f, {"species": 101})
    assert rows.party_control_problems(old, now, dict(f, case="static_run"), {"species": 101})
    bad = copy.deepcopy(now)
    bad[0]["moves"][0] += 1
    assert rows.party_control_problems(old, bad, f, {"species": 101})


def test_full_box_derivation_has_420_pack_offset_records_and_identities(pinned_inputs):
    import hashlib
    manifest = json.loads((ROOT / "tests/fixtures/gen3/exp_pc_full_box_synth_manifest.json").read_text())
    seed = (ROOT / manifest["seed"]).read_bytes()
    raw = rows.build_full_box_seed(seed)
    saved = (ROOT / manifest["file"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == manifest["raw_sha256"]
    assert rows.full_box_seed_problems(raw) == rows.full_box_seed_problems(saved) == []
    assert rows.full_box_seed_problems(seed)
    c = rows.fixture.codec
    before = c.parse_flash(raw, title=c.TITLE_EXPANSION)
    after = c.parse_flash(saved, title=c.TITLE_EXPANSION)
    assert before["storage"] == after["storage"]
    seed_store = c.parse_flash(seed, title=c.TITLE_EXPANSION)["storage"]
    fields = rows.profile.expansion_inputs()["facts"]["structs"]["PokemonStorage"]["fields"]["boxes"]
    off = fields["offset"]
    original = c.decode_box_mon(seed_store[off:off + 80])["personality"]
    for index in range(420):
        expected_pid = original ^ (((index + 1) * 0x01001001) & 0xFFFFFFFF)
        for image in (before, after):
            record = image["storage"][off + index * 80:off + (index + 1) * 80]
            assert c.decode_box_mon(record)["personality"] == expected_pid
    assert after["counter"] == before["counter"] + 1
    assert before["slot_status"] == (1, 0) and after["slot_status"] == (1, 1)


def test_box0_full_pending_seed_binds_empty_positive_sibling(pinned_inputs):
    import hashlib
    manifest = json.loads((ROOT / "tests/fixtures/gen3/exp_pc_box0_full_synth_manifest.json").read_text())
    raw = rows.build_box0_full_seed((ROOT / manifest["seed"]).read_bytes())
    saved = (ROOT / manifest["file"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == manifest["raw_sha256"]
    assert rows.box0_full_seed_problems(raw) == rows.box0_full_seed_problems(saved) == []
    assert rows.box0_full_seed_problems((ROOT / "tests/fixtures/gen3/exp_pc_full_box_synth.sav").read_bytes())
    assert rows.box0_full_seed_problems((ROOT / "tests/fixtures/gen3/exp_pc.sav").read_bytes())


@pytest.mark.parametrize("base_slot", [0, 1])
@pytest.mark.parametrize("residue", range(24))
def test_static_damp_packed_edit_preserves_nonability_data_in_every_shuffle(residue, base_slot):
    """Masked expansion abilityNum is authoritative. The vanilla decoder reads IV bit31
    (0 on the base seed) while the same seed's Misc/ribbons bit29 is actual abilityNum1.
    Exercise both ordinary slots without inventing a normalization in physical seeds.
    """
    c = rows.fixture.codec
    parsed = c.parse_flash((ROOT / "tests/fixtures/gen3/exp_pc.sav").read_bytes(), title=c.TITLE_EXPANSION)
    at = c._TITLE_PARTY_OFFSETS[c.TITLE_EXPANSION][1]
    mon = c.decode_party_mon(parsed["sb1"][at:at + 100])
    mon["personality"] = (mon["personality"] // 24) * 24 + residue
    # Exercise both neighbouring bits without changing the ability slot (bits29-30).
    mon["ribbons"] = (mon["ribbons"] & ~0x60000000) | (base_slot << 29) | (1 << 28) | (1 << 31)
    raw = c.encode_party_mon(mon)
    before = c.decode_party_mon_masked(raw, layout=rows.fixture._record_layout(c.TITLE_EXPANSION))
    assert before["ability_num"] == base_slot
    result = rows.static_damp_record(raw)
    after = c.decode_party_mon_masked(result, layout=rows.fixture._record_layout(c.TITLE_EXPANSION))
    assert after["ability_num"] == 2 and after["checksum_ok"]
    for field in ("moves", "evs", "ivs", "is_egg"):
        assert after[field] == before[field]
    assert c.decode_party_mon(result)["ribbons"] & 0x9FFFFFFF == mon["ribbons"] & 0x9FFFFFFF
    with pytest.raises(ValueError, match="abilityNum0/1"):
        rows.static_damp_record(result)


def test_native_run_deadzone_placeholder_passes_but_formed_or_nonempty_key_fails():
    import copy
    f={"area":"aqua_hideout"}
    battles={i:{"species":101,"level":30}for i in "ab"}
    doc={"links":[{"area_id":"aqua_hideout","a":None,"b":None,"status":"dead","cause":"dead_zone",
                   "initiating_player":"a","encounter_a":{"key":"","species":101,"level":30},"encounter_b":None}],
         "area_states":{"aqua_hideout":"dead_zone"},"pending_captures":{}}
    assert rows.negative_ledger_problems(doc,f,battles)==[]
    for edit in ("alive","key","species","area","pending"):
        bad=copy.deepcopy(doc)
        if edit=="alive":
            bad["links"][0].update(status="alive",a={"key":"a"},b={"key":"b"})
        elif edit=="key":
            bad["links"][0]["encounter_a"]["key"]="notempty"
        elif edit=="species":
            bad["links"][0]["encounter_a"]["species"]=100
        elif edit=="area":
            bad["area_states"]["aqua_hideout"]="linked"
        else:
            bad["pending_captures"]["aqua_hideout"]={"a":{"key":"a"}}
        assert rows.negative_ledger_problems(bad,f,battles)


def test_saved_master_debit_is_item_specific_and_other_balls_stay_unchanged():
    import struct
    c=rows.fixture.codec
    before=(ROOT/"tests/fixtures/gen3/exp_static_static_synth.sav").read_bytes()
    def pocket(body,item,qty):
        parsed=c.parse_flash(body,title=c.TITLE_EXPANSION)
        sb1=bytearray(parsed["sb1"])
        key=int.from_bytes(parsed["sb2"][rows.fixture.SB2_ENCRYPTION_KEY:rows.fixture.SB2_ENCRYPTION_KEY+4],"little")&65535
        at=rows.fixture._exp_derived()["SB1_BALL_POCKET_OFFSET"]
        sb1[at:at+4]=struct.pack("<HH",item,qty^key)
        return rows.fixture.exp_write_slot({"sb1":bytes(sb1),"sb2":parsed["sb2"],"storage":parsed["storage"]},counter=parsed["counter"])
    assert rows.master_bag_problems(before,pocket(before,0,0),4)==[]
    assert rows.master_bag_problems(before,before,4)
    assert rows.master_bag_problems(before,pocket(before,1,0),4)==[]  # zero non-Master occupancy is not a changed quantity
    assert rows.master_bag_problems(before,pocket(before,1,1),4)


def test_real_fishing_button_waits_for_bite_and_never_cancels_dots():
    import re

    from lupa import LuaRuntime
    source=(ROOT/"lua/tests/duo/scenario_gen3_static_wild.lua").read_text()
    body=re.search(r"(?ms)^local function fishing_button\(step\).*?^end$",source).group()
    lua=LuaRuntime(unpack_returned_tuples=True)
    choose=lua.execute(body+"\nreturn fishing_button")
    for step in range(8):
        assert choose(step) is None  # SHOW_DOTS4: A prematurely cancels the native cast.
    assert choose(8)==choose(9)=="A"
    assert choose(10) is None
    for step in range(11,18):
        assert choose(step)=="A"  # after bite: hook/failure text pauses need confirmation.


@pytest.mark.parametrize("task_starts", [True, False])
def test_real_fishing_reducer_names_cast_exhaustion_and_absent_registered_task(task_starts):
    import re

    from lupa import LuaRuntime
    source=(ROOT/"lua/tests/duo/scenario_gen3_static_wild.lua").read_text()
    button=re.search(r"(?ms)^local function fishing_button\(step\).*?^end$",source).group()
    reducer=re.search(r"(?ms)^local function fish_native\(ctx, f\).*?^end$",source).group()
    lua=LuaRuntime(unpack_returned_tuples=True)
    lua.globals().task_starts=task_starts
    lua.execute("""
        casts=0; active=false
        memory={read_u32_le=function()return 0x0814FE65 end,
                read_u8=function()return active and 1 or 0 end,
                read_s16_le=function()return 17 end}
        emu={framecount=function()return casts end}
        ctx={in_battle=function()return false end,on_field=function()return true end,
             player_idle=function()return true end,jlog=function()end,
             G={advance=function()end,tap=function(key)
                 if key=='Select'then casts=casts+1;active=task_starts else active=false end
             end}}
        f={tasks=0x03006C20,task_count=1,task_size=40,task_active_off=4,task_data_off=8,
           fishing_task=0x0814FE64}
    """)
    fn=lua.execute(button+"\n"+reducer+"\nreturn fish_native")
    ok,why=fn(lua.globals().ctx,lua.globals().f)
    assert ok is False
    if task_starts:
        assert lua.globals().casts==30 and "CAST_LIMIT=30 exhausted" in why
    else:
        assert lua.globals().casts==1 and "registered OLD_ROD did not start native Task_Fishing" in why


def test_native_rock_seeds_persist_completed_hidden_tower_through_pack_offsets(pinned_inputs):
    c=rows.fixture.codec
    f=rows.facts((ARTIFACTS/"pokeemerald.gba").read_bytes(),"rock")
    for side in ("", "_b"):
        raw=(ROOT/("tests/fixtures/gen3/exp_static_rock_synth"+side+".sav")).read_bytes()
        saved=c.parse_flash(raw,title=c.TITLE_EXPANSION)
        off=f["vars_off"]+2*(f["mirage_var"]-0x4000)
        assert int.from_bytes(saved["sb1"][off:off+2],"little")==3
        assert not saved["sb1"][f["flags_off"]+f["mirage_visible"]//8]&(1<<(f["mirage_visible"]%8))
        assert int.from_bytes(saved["sb1"][0x32:0x34],"little")==f["no_tower_layout"]==392
        assert not rows.seed_problems(raw,f)


def test_live_selector_rereads_the_moving_saveblock_pointer():
    import re

    from lupa import LuaRuntime
    src=(ROOT/"lua/tests/duo/scenario_gen3_static_wild.lua").read_text()
    body=re.search(r"(?ms)^local function live_selector\(f\).*?^end$",src).group()
    lua=LuaRuntime(unpack_returned_tuples=True)
    lua.execute("""pointer=0x02000000
        memory={read_u32_le=function()return pointer end,
                read_u16_le=function(at)return at==pointer+0x10 and 1 or 0 end}
    """)
    fn=lua.execute(body+"\nreturn live_selector")
    f=lua.table_from({"sb1_pointer":0x03000000,"vars_off":0x10,"selector_var":0x4000})
    assert fn(f)==(1,0x02000000)
    lua.globals().pointer=0x02001000
    assert fn(f)==(1,0x02001000)


def test_synth_rock_rng_writes_only_the_symbol_bound_sfc32_state():
    import re

    from lupa import LuaRuntime
    src=(ROOT/"lua/tests/duo/scenario_gen3_static_wild.lua").read_text()
    body=re.search(r"(?ms)^local function rock_rng_prep\(f\).*?^end$",src).group()
    lua=LuaRuntime(unpack_returned_tuples=True)
    writes=[]
    lua.globals().capture=lambda at,value,domain:writes.append((at,value,domain))
    lua.execute("memory={read_u8=function()return 17 end,write_u8=capture}")
    fn=lua.execute(body+"\nreturn rock_rng_prep")
    fn(lua.table_from({"rock_rng_address":0x03006B64,"rock_rng_size":16,"rock_rng_state_hex":rows.rock_rng_state().hex()}))
    assert writes==[(0x03006B64+i,value,"System Bus")for i,value in enumerate(rows.rock_rng_state())]
    # SRC random.c Random32 result=a+b+ctr; nativeSeedRng(0) after16warmups.
    import struct
    a,b,_c,counter=struct.unpack("<4I",rows.rock_rng_state())
    assert (((a+b+counter)&0xFFFFFFFF)>>16)%2880==64 < 20*16


def test_rock_runtime_synth_manifest_hash_binds_source_qualified_scope():
    import hashlib
    manifest=json.loads((ROOT/"tests/fixtures/gen3/exp_static_wild_synth_manifest.json").read_text())
    entries=[e for e in manifest["fixtures"]if e["case"]=="rock"]
    assert len(entries)==2
    for entry in entries:
        spec=dict(entry["runtime_synth_precondition"])
        digest=spec.pop("sha256")
        assert hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()==digest
        assert bytes.fromhex(spec["state_hex"])==rows.rock_rng_state()
        assert "not saved" in spec["persistence"]


def test_enemy_slot_check_waits_for_native_action_menu_and_logs_entry_record():
    import re

    from lupa import LuaRuntime
    source=(ROOT/"lua/tests/duo/scenario_gen3_static_wild.lua").read_text()
    match=re.search(r"(?ms)^local function native_enemy_ready\(ctx\).*?^end$",source)
    assert match, "native enemy readiness helper absent"
    lua=LuaRuntime(unpack_returned_tuples=True)
    lua.execute("""
        ready=false; logged=nil
        ctx={reader={read_battle=function()
            return {enemy_party={{species=ready and 74 or 261,level=ready and 15 or 3}}}
        end},jlog=function(tag,row)if tag=='STATIC_ENEMY_ENTRY'then logged={tag,row.species,row.level}end end,
        await_turn=function(seconds,button)
            assert(seconds==30 and button=='A');ready=true;return 'action'
        end}
    """)
    fn=lua.execute(match.group()+"\nreturn native_enemy_ready")
    foe=fn(lua.globals().ctx)
    assert foe['species']==74 and foe['level']==15
    logged=lua.globals().logged
    assert [logged[i]for i in range(1,4)]==['STATIC_ENEMY_ENTRY',261,3]
    lua.execute("ctx.await_turn=function()return 'over'end")
    result=fn(lua.globals().ctx)
    assert result[0] is None and 'action menu' in result[1]
