"""Ordinary RR school borrowed-party DuoRun rows. SOURCE/MODEL; PHYSICAL unrun."""
from pathlib import Path
import hashlib,json,re
from tools.research.rr_special_lifecycle import census,school_fixture_flags,COMPANION_SHA1
from tools.gba_map import Rom
from tools.gen3_clause_rows import one,rows
from tools.gen3_gift_egg_rows import tx_messages

ROOT = Path(__file__).resolve().parents[1]

ROWS={name:dict(flags=[],timeout=2400,frames=3000000,games=("gen3_rr",),target="battle2",
               explicit_only=True,scenario_module="borrowed",no_save=("b",),
               oracle="assert_borrowed_party_gen3_saved")
      for name in ("borrowed_party_menu_gen3","borrowed_party_battle_gen3")}


def own_facts(run):
    rom=(ROOT / run._gen3_rom("a")).read_bytes()
    facts=census(rom)
    if facts["rom_sha1"]!=COMPANION_SHA1:raise RuntimeError("borrow requires actual admitted RR companion")
    flags=school_fixture_flags(rom,run._gen3_fixture_bytes("a"))
    if flags["flags"]!={"1047":0,"1096":0}:raise RuntimeError("school fixture progress route differs")
    maps=Rom(rom,0x083526A8);city=maps.map(3,1);school=maps.map(5,2)
    doors=[w for w in city.warps if (w.map_group,w.map_num)==(5,2)]
    if len(doors)!=1 or (doors[0].x,doors[0].y)!=(25,18):raise RuntimeError("school door changed")
    door=doors[0];dest=school.warps[door.warp_id]
    arrival=[dest.x,dest.y+1] # same door step/arrival semantics as verified Center door
    paths=dict(city=city.bfs((26,27),(door.x,door.y+1)),school=school.bfs(tuple(arrival),(6,4)))
    if any(p is None or len(p)>=100 for p in paths.values()):raise RuntimeError("school BFS route absent")
    labels=[(0x091153D2,"View Your Team"),(0x091153F0,"Start Battle")]
    from tools.rr_ingame_trades import decode_text
    if any(decode_text(rom[a-0x08000000:a-0x08000000+50])!=text for a,text in labels):
        raise RuntimeError("school ordinary menu labels changed")
    if rom[0x1051BA0:0x1051BAE].hex()!="5c0907000000725111098a561109":
        raise RuntimeError("school trainerbattle9 command changed")
    if rom[0xA03B0:0xA03B4].hex()!="50c70302":raise RuntimeError("selection order binding changed")
    return dict(case="menu" if run.scenario=="borrowed_party_menu_gen3" else "battle",
                rom_sha1=facts["rom_sha1"],arrival=arrival,paths=paths,school_flags=flags,
                menu_option=0 if run.scenario=="borrowed_party_menu_gen3" else 3,
                selected_order_address=0x0203C750,confirm_slot=6,borrow=facts["borrowed_party"])


def orchestrate(run):
    facts=own_facts(run);mode=facts["case"]
    ka,kb=run._gen3_prelude(link_slot=1 if mode=="battle" else None)
    if mode=="menu":run._link_keys={"a":ka[1],"b":kb[1]}
    run._gen3_area_control()
    lines={inst:["TARGET "+json.dumps(run._link_keys[inst]),"BORROW "+json.dumps(facts)] for inst in ("a","b")}
    run.go(lines)
    if mode=="menu":
        run._gen3_mark("a",r"^BORROW_MENU_READY ","native borrowed ViewYourTeam")
        run.queue_command("a",{"cmd":"force_faint","key":run._link_keys["a"]})
        run._gen3_mark("a",r"^BORROW_HELD ","command held 120 frames without loan write")
        run._append_reconnect_marker("a","RESTORE")
    run._gen3_mark("a",r"^BORROW_RESTORED ","own-party registered restore")
    run._append_reconnect_marker("a","SAVE")


def saved_oracle(run,results):
    """DuoRun's witness gate runs first; independently decode its actual flushed batteries."""
    import e2e_duo as h
    from server.adapters import gen3_codec as c
    facts=own_facts(run);mode=facts["case"];text=results["a"]
    run._gen3_flush_boundary()
    baseline=one(text,"BORROW_BASELINE");held=one(text,"BORROW_HELD") if mode=="menu" else None
    restored=one(text,"BORROW_RESTORED")
    raw=[bytes.fromhex(x) for x in baseline["raw_party_hex"]]
    if baseline.get("rom_sha1")!=facts["rom_sha1"] or len(raw)<2 or any(len(x)!=100 for x in raw):
        raise RuntimeError("borrow baseline ROM/party raw invalid")
    before=[c.decode_party_mon(x,rr=True) for x in raw]
    target=run._link_keys["a"]
    if h.gen3_key(before[1])!=target:raise RuntimeError("borrow target differs from actual ownslot1")
    party,boxes=run._gen3_saved("a")
    if len(party)!=len(before) or boxes!=run._gen3_fixture_saved("a")[1]:
        raise RuntimeError("borrow changed own membership or boxes")
    for i,(old,new) in enumerate(zip(before,party)):
        mutable={"hp"} if mode=="menu" and i==1 else set()
        changed=h.gen3_record_diff(old,new,rr=True,mutable=mutable)
        if changed:raise RuntimeError(f"borrow changed own record{i}: {changed}")
    if mode=="menu":
        if party[1]["hp"]!=0 or held.get("frames",0)<120 or held.get("party_write_count")!=0 or held.get("hidden_ticks",0)<1:
            raise RuntimeError("borrow menu lacks held-write/hidden-window/ownHP0 proof")
        window=(held.get("start_frame"),held.get("end_frame"))
        if any(type(v) is not int for v in window) or window[1]-window[0]<120:
            raise RuntimeError("borrow menu lacks actual 120-frame bound")
        for address,length,frame in re.findall(r"write \S+ 0x([0-9A-Fa-f]+) \+(\d+) frame (\d+)",text):
            address,length,frame=int(address,16),int(length),int(frame)
            base=facts["borrow"]["party_base"]
            if window[0]<=frame<=window[1] and address<base+600 and address+length>base:
                raise RuntimeError("logged client write touched loan during held window")
        if run._links_json():raise RuntimeError("menu command control must not create a link")
    else:
        if party!=before:raise RuntimeError("native borrowed fight changed own party")
        links=run._links_json()
        if len(links)!=1 or links[0].get("status")!="alive" or any(
                (links[0].get(pid) or {}).get("key")!=run._link_keys[pid] for pid in ("a","b")):
            raise RuntimeError("borrowed fight changed the single alive linked pair")
        if one(text,"BORROW_BATTLE").get("outcome") not in (1,2):raise RuntimeError("no actual win/loss")
    if run._gen3_saved("b")!=run._gen3_fixture_saved("b"):raise RuntimeError("idle B changed saved party/boxes")
    operation=text[text.index("BORROW_BASELINE "):]
    for event in ("capture","no_catch","whiteout","party_to_box","box_to_party","key_change"):
        if tx_messages(operation,event):raise RuntimeError("borrow emitted "+event)
    if mode=="battle" and tx_messages(operation,"faint"):raise RuntimeError("borrowed KO emitted own faint")
    signals=rows(text,"BORROW_SIGNAL")
    if not signals or signals[0].get("kind")!="borrowed_party_begin" or not any(s.get("kind")=="borrowed_party_end" for s in signals):
        raise RuntimeError("registered begin/end borrow evidence missing")
    if restored.get("key")!=target or restored.get("borrowed") is not False:raise RuntimeError("restore names wrong ownparty")
    problems=h.gen3_receipt_problems("a",text,required=["BORROW_BASELINE ","BORROW_RESTORED ","SAVE_WITNESS "],
             ordered=[("BORROW_BASELINE ","BORROW_RESTORED "),("BORROW_RESTORED ","SAVE_WITNESS ")])
    if "SAVE_WITNESS " in results["b"]:problems.append("idle B unexpectedly saved")
    if problems:raise RuntimeError("; ".join(problems))
    run._pydec_note("borrowed "+mode+": real registered lifecycle, independent saved own records, idle peer")
