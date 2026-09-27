"""Opt-in LG versions of the bounded single-cart probes, with audited address translation."""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def symbols(title):
    rows=[]
    for line in (ROOT/f"data/gen3/pret/{title}.sym").read_text().splitlines():
        words=line.split()
        if len(words)==4 and not words[3].startswith("."):
            rows.append((int(words[0],16),int(words[2],16),words[3]))
    return rows


def lg_transform(text,mode):
    fr,lg=symbols("pokefirered"),symbols("pokeleafgreen")
    audit={}
    def address(match):
        value=int(match[0],16)
        if not 0x02000000<=value<0x0A000000 or 0x0201B000<=value<0x0201C000:
            return match[0]
        # GBA hardware palette/VRAM regions are title-independent, not ROM symbols.
        if 0x05000000<=value<0x05000400 or 0x06000000<=value<0x06018000:
            audit[match[0]]={"address":value,"symbol":"GBA hardware memory","offset":0}
            return match[0]
        matches=[(row,0) for row in fr if row[0]==value]
        if not matches and value>=0x08000000 and value&1:
            matches=[(row,1) for row in fr if row[0]==value-1]
        if not matches:
            matches=[(row,value-row[0]) for row in fr if row[1] and row[0]<=value<row[0]+row[1]]
        choices=[]
        for (old,size,name),offset in matches:
            targets=[row for row in lg if row[2]==name]
            if len(targets)>1:
                # e.g. player HandleInputChooseAction: same named/sized entry at
                # the explicitly shared address (also pinned by gen3_title_syms).
                targets=[row for row in targets if row[0]==old and row[1]==size]
            if len(targets)==1:
                choices.append((targets[0][0]+offset,name,offset))
        assert choices and len({row[0] for row in choices})==1,(match[0],choices)
        new,name,offset=choices[0]
        audit[match[0]]={"address":new,"symbol":name,"offset":offset}
        return f"0x{new:08X}"
    text=re.sub(r"0x[0-9A-Fa-f]+",address,text)
    text=text.replace("/.cache/r/",f"/.cache/lg-{mode}/").replace("FR native","LG native").replace("SCOPE: FR ","SCOPE: LG ").replace("native FR", "native LG").replace("FR client", "LG client")
    if mode=="trade":
        text=text.replace("SCOPE: allocator boundary; census when requested covers only named scenes; title lifecycle unqualified",
                          "SCOPE: LG native trade/save/reload; SYNTH full party/boxes, no duo/admission")
        text=text.replace("rd(base)==0x32505254 and r16(base+4)==2 and rd(base+0x40)==0",
                          "rd(base)==0x4B4E4C53 and r16(base+4)==2 and rd(base+0x40)==23")
    return text,audit


def main(mode):
    sys.path.insert(0,str(ROOT))
    from server.adapters import gen3_codec as codec
    from tests.unit.test_patch_arena_probe import run_probe
    from tests.unit.test_patch_carrier_live import carrier_problems
    from tests.unit.test_patch_panel_live import panel_problems
    from tests.unit.test_patch_rival_live import rival_problems
    from tests.unit.test_patch_sound_live import sound_problems

    if os.environ.get("T2_FAIL_POST_SAVE"):
        raise ValueError("LG candidate has no private post-save fault-injection switch")
    target=ROOT/f".cache/lg-{mode}"
    target.mkdir(exist_ok=True)
    candidate=ROOT/"patch/build/candidate-leafgreen-trade"
    for name in ("probe.gba","receipt.json"):
        shutil.copyfile(candidate/name,target/name)
    expected=None
    if mode=="rival":
        peer=codec.party_from_save((ROOT/"tests/fixtures/gen3/leafgreen_party_trainer_b.sav").read_bytes())
        (target/"late.bin").write_bytes(codec.encode_party_mon(peer[0]))
        peer[0]["hp"]=0
        expected=b"".join(codec.encode_party_mon(mon) for mon in peer)
        (target/"rival.bin").write_bytes(expected)
        nm=Path(os.environ["SLINK_ARMGCC"])/"arm-none-eabi-nm.exe"
        output=subprocess.check_output([str(nm),str(candidate/"probe.elf")],text=True)
        dispatch=int(next(line.split()[0] for line in output.splitlines() if line.split()[-1:]==["slink_native_rival_service"]),16)
        os.environ["T2_RIVAL_DISPATCH"]=hex(dispatch)
    audit={}
    def transform(text):
        translated,records=lg_transform(text,mode)
        audit.update(records)
        return translated
    result=run_probe(mode,title="leafgreen",base_dir=target,lua_transform=transform)
    text=(target/"result.txt").read_text()
    rom=(target/"probe.gba").read_bytes()
    syms={name:address for address,_,name in symbols("pokeleafgreen")}
    if mode=="carrier":
        problems=carrier_problems(text,(target/"seed.sav").read_bytes(),
                                  (target/"frontend/GBA/Save RAM/probe.SaveRAM").read_bytes())
    elif mode=="panel":
        problems=panel_problems(text)
    elif mode=="sound":
        problems=sound_problems(text,rom,song_table=syms["gSongTable"],mplay_table=syms["gMPlayTable"])
    elif mode=="rival":
        problems=rival_problems(text,expected)
    else:
        proof=json.loads((target/"census_receipt.json").read_text()) if (target/"census_receipt.json").exists() else {}
        problems=[] if proof.get("pydec_pass") is True else ["native save/reload decode did not pass"]
    receipt={"title":"leafgreen","mode":mode,
             "scope":"LG single-cart native producer; replayed payloads/SYNTH setup where applicable; no server/duo/admission",
             "result":"PASS" if not result and not problems else "FAIL","problems":problems,
             "rom_sha256":hashlib.sha256(rom).hexdigest(),"address_bindings":audit,
             "run":json.loads((target/"run_receipt.json").read_text())}
    (target/"leafgreen_receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    archive=ROOT/f"patch/build/lg-{mode}-live-20260927"
    archive.mkdir(exist_ok=True)
    for name in ("leafgreen_receipt.json","result.txt","run_receipt.json","receipt.json","probe.lua","config.ini","seed.sav",
                 "rival.bin","late.bin","incoming.bin","reload_party.bin","census_receipt.json"):
        if (target/name).exists():
            shutil.copyfile(target/name,archive/name)
    save=target/"frontend/GBA/Save RAM/probe.SaveRAM"
    if save.exists():
        shutil.copyfile(save,archive/"native.SaveRAM")
    print(json.dumps({"mode":mode,"result":receipt["result"],"problems":problems,"receipt":str(archive/"leafgreen_receipt.json")},indent=2))
    return receipt["result"]!="PASS"


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",choices=("carrier","panel","sound","rival","trade"))
    raise SystemExit(main(parser.parse_args().mode))
