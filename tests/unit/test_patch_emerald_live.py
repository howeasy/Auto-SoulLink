"""Opt-in Emerald native candidates. No emulator is launched by pytest import.

Each script uses only ABI staging and ordinary joypad input for game changes.
Address translations are symbol-backed; semantic differences are explicit.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CALL_REFUSAL_LUA = r'''
  local G=dofile(os.getenv("SLINK_ROOT").."/lua/tests/gen3_boot_check.lua")
  local cp=G.checkpoint()
  assert(G.boot_to_field(cp,9000),"boot failed");G.idle(120)
  local base=0x0201B000
  local function b(a) return memory.read_u8(a,"System Bus") end
  local function h(a) return memory.read_u16_le(a,"System Bus") end
  local function wb(a,v) memory.write_u8(a,v,"System Bus") end
  local function wh(a,v) memory.write_u16_le(a,v,"System Bus") end
  local function wd(a,v) memory.write_u32_le(a,v,"System Bus") end
  local function hex(a,n) local t={} for i=0,n-1 do t[#t+1]=string.format("%02X",b(a+i)) end return table.concat(t) end
  assert(rd(base)==0x4B4E4C53 and rd(base+0x40)==87,"wrong native candidate")
  local sb1=rd(0x03005D8C)
  assert((b(sb1+0x1270+(0x862>>3))&(1<<(0x862&7)))==0,"refusal fixture has PokeNav")
  assert((b(sb1+0x1270+(0x12F>>3))&(1<<(0x12F&7)))==0,"refusal fixture has Match Call")
  local shows=0
  assert(event.on_bus_exec(function() shows=shows+1 end,0x08098238,"T2-call-show"),"show hook absent")
  wd(base+0x44,7)
  for i=0,31 do wb(base+16+i,0) end
  for i=0,35 do wb(base+0x360+i,0xff) end
  wb(base+0x360,1);wb(base+0x361,0);wh(base+0x362,0);wh(base+0x364,0)
  wb(base+16,1);wh(base+8,1);wh(base+10,1);wh(base+6,32)
  for _=1,120 do if h(base+12)==1 and h(base+6)==0 then break end;G.advance() end
  assert(h(base+10)==3 and h(base+14)==17,"locked device did not refuse")
  local w=base+0xE00
  assert(rd(w)==7 and h(w+4)==1 and h(w+6)>0 and h(w+6)%2==0 and b(w+8)==3 and b(w+9)==1 and h(w+10)==17 and rd(w+16)==0,"bad refused witness")
  G.idle(180)
  assert(shows==0 and b(0x03000F2C)==0,"refused call opened UI or locked controls")
  log("CALL_REFUSED locked_device shows=0 field_lock=0 witness="..hex(w,32))
'''


def symbols(title):
    return [(int(p[0],16),int(p[2],16),p[3])
            for line in (ROOT/f"data/gen3/pret/{title}.sym").read_text().splitlines()
            if len(p := line.split()) == 4 and not p[3].startswith(".")]


def translate(text):
    fr, em = symbols("pokefirered"), symbols("pokeemerald")
    aliases = {"sNumStartMenuItems":"sNumStartMenuActions", "sStartMenuOrder":"sCurrentStartMenuActions",
               "sFanfareCounter":"sFanfareCounter", "Task_Fanfare":"Task_Fanfare"}
    audit = {}
    def address(match):
        value = int(match[0],16)
        if not 0x02000000 <= value < 0x0A000000 or 0x0201B000 <= value < 0x0201C000:
            return match[0]
        if 0x05000000 <= value < 0x05000400 or 0x06000000 <= value < 0x06018000:
            return match[0]
        matches = [(a,n,name,value-a) for a,n,name in fr if a==value or (value&1 and a==value-1)]
        if not matches:
            matches = [(a,n,name,value-a) for a,n,name in fr if n and a<=value<a+n]
        choices = set()
        for _,_,name,off in matches:
            found = [(a,n) for a,n,key in em if key==aliases.get(name,name)]
            if len(found)>1 and name=="HandleInputChooseAction":
                # pokeemerald battle_controller_player object range, from source census.
                found = [(a,n) for a,n in found if 0x08057458<=a<0x0805D116]
            if len(found)==1:
                choices.add((found[0][0]+off,name,off))
        assert choices and len({p[0] for p in choices})==1,(match[0],choices)
        new,name,off = sorted(choices)[0]
        audit[match[0]]={"address":new,"symbol":aliases.get(name,name),"offset":off}
        return f"0x{new:08X}"
    return re.sub(r"0x[0-9A-Fa-f]+",address,text),audit


def body(mode):
    from tests.unit.test_patch_panel_live import PANEL_LUA
    from tests.unit.test_patch_sound_live import SOUND_LUA
    from tests.unit.test_patch_trade_live import TRADE_LUA
    from tests.unit.test_patch_rival_live import RIVAL_LUA
    from tests.unit.test_patch_carrier_live import CARRIER_LUA
    if mode=="call-refusal":return CALL_REFUSAL_LUA,{}
    text = {"panel":PANEL_LUA,"sound":SOUND_LUA,"trade":TRADE_LUA,
            "rival":RIVAL_LUA,"carrier":CARRIER_LUA}[mode]
    if mode=="panel":
        text=text.replace("count<=8","count<=9").replace("order[#order]==9","order[#order]==13")
        text=text.replace("order[count]==6 and order[count-1]==9","order[count]==7 and order[count-1]==13")
    elif mode=="sound":
        text=text.replace("active(9,257)","active(9,367)").replace("{19,347,7,2", "{19,610,7,2")
    elif mode=="trade":
        text=text.replace("rd(base)==0x32505254", "rd(base)==0x4B4E4C53").replace("rd(base+0x40)==0", "rd(base+0x40)==87")
        text=text.replace('  client.saveram() -- host flush', '''  local witness={}
  for i=0,79 do witness[#witness+1]=string.format("%02X",memory.read_u8(w+i,"System Bus")) end
  log("TRADE_WITNESS "..table.concat(witness))
  client.saveram() -- host flush''')
    elif mode=="rival":
        text=text.replace("x==41 and y==45","x==32 and y==16").replace("==102","==318").replace("wh(base+17,102)","wh(base+17,318)")
        text=text.replace("/.cache/r/","/.cache/e-rival/").replace("Rick102","Calvin318").replace("Rick approach","Calvin approach")
    elif mode=="carrier":
        begin=text.index('  SP.play.follow(cp,"route1_edge')
        end=text.index('  local facing=',begin)
        text=text[:begin]+r'''
  G.tap("Up",12,60)
  assert(wait(300,function() local g,n=G.map(cp);return g==2 and n==2 and safe() end),"Oldale Center warp failed")
  local function step(dir,tx,ty)
    for _=1,30 do
      local x,y=G.pos(cp);if x==tx and y==ty then return end
      G.tap(dir,8,20)
    end
    error("normal step failed "..dir.." to "..tx..","..ty)
  end
  local x,y=G.pos(cp)
  log(string.format("CENTER_ENTRY x=%d y=%d",x,y))
  -- ROM/layout source: walk the open southern aisle, then north at x10.
  if x==6 then step("Right",7,y) end
  for xx=8,9 do step("Right",xx,y) end
  for yy=y-1,5,-1 do step("Up",9,yy) end
  step("Right",10,5)
  assert(wait(180,function() return npc() and safe() end),"native NPC absent")
''' + text[end:]
        text=text.replace('px==3 and py==4','px==10 and py==5')
        text=text.replace('assert(h(0x020370C0)==expected,"chooser game var differs")',
                          'assert(h(0x020370C0)==(expected==7 and 255 or expected),"chooser game var differs")')
    text,audit=translate(text)
    return text.replace("native FR","native Emerald").replace("FR native","Emerald native"),audit


def problems(mode, text, base):
    from server.adapters import gen3_codec as codec
    from tests.unit.test_patch_panel_live import panel_problems
    from tests.unit.test_patch_sound_live import sound_problems
    from tests.unit.test_patch_carrier_live import carrier_problems
    from tests.unit.test_patch_rival_live import rival_problems
    syms={name:a for a,_,name in symbols("pokeemerald")}
    if mode=="call-refusal":
        match=re.search(r"CALL_REFUSED locked_device shows=0 field_lock=0 witness=([0-9A-F]{64})",text)
        if not match:return ["native locked-device refusal absent"]
        w=bytes.fromhex(match[1])
        if (int.from_bytes(w[:4],"little")!=7 or int.from_bytes(w[4:6],"little")!=1
                or not int.from_bytes(w[6:8],"little") or w[6]&1 or w[8:12]!=bytes([3,1,17,0])
                or any(w[12:20]) or "RESULT: PASS" not in text):return ["locked-device witness differs"]
        return []
    if mode=="panel":return panel_problems(text,soul_action=13,exit_action=7)
    if mode=="sound":
        return sound_problems(text,(base/"probe.gba").read_bytes(),song_table=syms["gSongTable"],
                              mplay_table=syms["gMPlayTable"],fanfare_id=367)
    if mode=="rival":
        return rival_problems(text,(base/"rival.bin").read_bytes(),start_callback=syms["CB2_HandleStartBattle"]|1,
                              dummy_callback=syms["BeginBattleIntroDummy"]|1,trainer=318)
    save=base/"frontend/GBA/Save RAM/probe.SaveRAM"
    seed=(base/"seed.sav").read_bytes()
    if mode=="carrier":
        if not save.exists():return ["native SaveRAM absent"]
        return carrier_problems(text,seed,save.read_bytes(),title="emerald",center="2,2",field_callback=syms["CB2_Overworld"]|1)
    errors=[]
    if "RESULT: PASS" not in text:errors.append("native script failed")
    if not save.exists() or not (base/"reload_party.bin").exists():return errors+["save/reload readback missing"]
    saved=save.read_bytes()
    valid,why=codec.qualify_flash(saved,title="emerald")
    if not valid:return errors+[f"invalid native SaveRAM: {why}"]
    before=codec.parse_flash(seed,title="emerald");after=codec.parse_flash(saved,title="emerald")
    if after["counter"]!=before["counter"]+2:errors.append("native counter must advance twice")
    if after["storage"]!=before["storage"]:errors.append("native trade changed boxed storage")
    original=codec.party_from_save(seed,title="emerald")
    final=codec.party_from_save(saved,title="emerald")
    raw=(base/"reload_party.bin").read_bytes()
    reload=[codec.decode_party_mon(raw[i*100:i*100+100]) for i in range(len(original))]
    def identity(mon):return mon["species"],mon["personality"],mon["ot_id"]
    for roster in (final,reload):
        if len(roster)!=len(original) or identity(roster[0])!=(68,0x13572468,0x78563412):
            errors.append("received evolution/identity absent from save or reloaded party")
        if any(not m["checksum_ok"] for m in roster):errors.append("bad party checksum")
        if [identity(m) for m in roster[1:]]!=[identity(m) for m in original[1:]]:
            errors.append("untraded party identity changed")
    match=re.search(r"TRADE_WITNESS ([0-9A-F]{160})",text)
    if not match:errors.append("immutable trade witness missing")
    else:
        w=bytes.fromhex(match[1]);word=lambda off,n=4:int.from_bytes(w[off:off+n],"little")
        if (word(0)!=0x12345678 or word(4)!=0xABCDEF01 or w[8:24]!=bytes(range(1,17))
                or not word(24,2) or word(24,2)&1 or word(26,2)!=3 or word(28)!=31
                or [word(32+2*i,2) for i in range(5)]!=[1,2,2,2,2] or w[42:44]!=b"\x01\x01"
                or word(72)!=0x13572468 or word(76)!=0x78563412):
            errors.append("trade witness identity/milestones/durability differs")
    return errors


def run(mode, prepare=False):
    sys.path.insert(0,str(ROOT))
    from tools.gen1_playthrough import disable_rewind
    from server.adapters import gen3_codec as codec
    base=ROOT/f".cache/e-{mode}"
    base.mkdir(parents=True,exist_ok=True)
    candidate=ROOT/"patch/build/candidate-emerald-trade"
    for name in ("probe.gba","receipt.json"):
        shutil.copyfile(candidate/name,base/name)
    kind="trainer" if mode=="rival" else "pc" if mode=="trade" else "town"
    seed=(ROOT/f"tests/fixtures/gen3/emerald_{kind}.sav").read_bytes()
    (base/"seed.sav").write_bytes(seed)
    incoming=codec.party_from_save(seed,title="emerald")[0]
    incoming.update(species=67,personality=0x13572468,ot_id=0x78563412,
                    nickname_raw=codec.encode_name("AAAAAAAAAA",10),ot_name_raw=codec.encode_name("PEER",7),held_item=0)
    (base/"incoming.bin").write_bytes(codec.encode_party_mon(incoming))
    if mode=="rival":
        peer=codec.party_from_save((ROOT/"tests/fixtures/gen3/emerald_pc_b.sav").read_bytes(),title="emerald")
        (base/"late.bin").write_bytes(codec.encode_party_mon(peer[0]))
        peer[0]["hp"]=0
        (base/"rival.bin").write_bytes(b"".join(codec.encode_party_mon(m) for m in peer))
    state_dir=(base/"states").resolve();state_dir.mkdir(exist_ok=True)
    assert state_dir.is_relative_to(ROOT.resolve())
    original=Path(os.environ.get("SLINK_BIZHAWK_CONFIG","E:/Howard/Bizhawk/config.ini"))
    config=json.loads(original.read_text(encoding="utf-8-sig"))
    frontend=base/"frontend"
    for entry in config["PathEntries"]["Paths"]:
        if entry["Type"]=="Firmware":entry["Path"]=str(original.parent/"Firmware")
        else:
            entry["Path"]=str(frontend/entry["System"]/entry["Type"].replace("/","_"))
            if entry["System"]=="GBA" and entry["Type"]=="Save RAM":
                Path(entry["Path"]).mkdir(parents=True,exist_ok=True)
                (Path(entry["Path"])/"probe.SaveRAM").write_bytes(seed)
    disable_rewind(config)
    config["AutoLoadLastSaveSlot"]=False;config["AutoSaveLastSaveSlot"]=False
    (base/"config.ini").write_text(json.dumps(config,indent=2))
    script,audit=body(mode)
    script='''local out=assert(io.open("'''+(base/"result.txt").as_posix()+'''","w"))
local function log(s) out:write(s.."\\n");out:flush() end
local function rd(a) return memory.read_u32_le(a,"System Bus") end
local original_save=savestate.save
savestate.save=function(path)
 local prefix=assert(os.getenv("SLINK_STATE_DIR")):gsub("\\\\","/"):lower().."/"
 local normalized=path:gsub("\\\\","/"):lower()
 assert(normalized:sub(1,#prefix)==prefix and not normalized:find("..",1,true),"unowned state path")
 return original_save(path)
end
print=log;console.log=log
client.speedmode(1000)
local ok,why=pcall(function()
'''+script+'''
end)
log("RESULT: "..(ok and "PASS" or "FAIL").." "..tostring(why or ""))
out:close();client.exit()
'''
    (base/"probe.lua").write_text(script)
    (base/"address_bindings.json").write_text(json.dumps(audit,indent=2))
    if prepare:return 0
    result=base/"result.txt";result.unlink(missing_ok=True)
    env={**os.environ,"SLINK_ROOT":ROOT.as_posix(),"SLINK_GEN3_TITLE":"emerald",
         "SLINK_GEN3_CHECKPOINT":str(ROOT/"data/games/gen3_emerald/write_checkpoint.json"),
         "SLINK_STATE_DIR":state_dir.as_posix(),"SLINK_GEN3_PLAY_STATES_DIR":state_dir.as_posix(),
         "T2_INCOMING":str(base/"incoming.bin"),"T2_RELOAD_PARTY":str(base/"reload_party.bin")}
    if mode=="rival":
        nm=Path(os.environ["SLINK_ARMGCC"])/"arm-none-eabi-nm.exe"
        lines=subprocess.check_output([str(nm),str(candidate/"probe.elf")],text=True).splitlines()
        env["T2_RIVAL_DISPATCH"]=hex(int(next(l.split()[0] for l in lines if l.split()[-1:]==["slink_native_rival_service"]),16))
    emulator=os.environ.get("SLINK_EMUHAWK","E:/Howard/Bizhawk/EmuHawk.exe")
    cmd=[emulator,f"--config={base.relative_to(ROOT).as_posix()}/config.ini",
         f"--lua={base.relative_to(ROOT).as_posix()}/probe.lua",f"{base.relative_to(ROOT).as_posix()}/probe.gba"]
    proc=subprocess.Popen(cmd,cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    print(f"owned EmuHawk PID={proc.pid}, mode={mode}, state_dir={state_dir}",flush=True)
    receipt={"title":"emerald","mode":mode,"pid":proc.pid,"state_dir":str(state_dir),
             "config":str(base/"config.ini"),"script_sha256":hashlib.sha256(script.encode()).hexdigest(),
             "rom_sha256":hashlib.sha256((base/"probe.gba").read_bytes()).hexdigest(),
             "seed_sha256":hashlib.sha256(seed).hexdigest()}
    (base/"run_receipt.json").write_text(json.dumps(receipt,indent=2))
    started=time.monotonic()
    try:
        while proc.poll() is None and time.monotonic()-started<180:
            if result.exists() and "RESULT:" in result.read_text():break
            time.sleep(1)
    finally:
        if proc.poll() is None:
            subprocess.run(["taskkill","/PID",str(proc.pid),"/T","/F"],capture_output=True,timeout=15)
            proc.wait(timeout=15)
    text=result.read_text() if result.exists() else "FAIL: no output"
    print(text)
    errors=problems(mode,text,base)
    rejected=bool(problems(mode,text.replace("RESULT: PASS","RESULT: FAIL"),base))
    receipt.update(result="PASS" if not errors and rejected else "FAIL",problems=errors,
                   missing_success_rejected=rejected,address_bindings=audit,
                   scope="Emerald private single-cart native producer; replayed payloads and existing SYNTH fixture; no server/duo/admission")
    (base/"emerald_receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    archive=ROOT/f"patch/build/em-{mode}-live-20260927"
    archive.mkdir(exist_ok=True)
    for name in ("emerald_receipt.json","result.txt","run_receipt.json","receipt.json","probe.lua","config.ini",
                 "seed.sav","rival.bin","late.bin","incoming.bin","reload_party.bin","address_bindings.json"):
        if (base/name).exists():shutil.copyfile(base/name,archive/name)
    saved=base/"frontend/GBA/Save RAM/probe.SaveRAM"
    if saved.exists():shutil.copyfile(saved,archive/"native.SaveRAM")
    print(json.dumps({"mode":mode,"result":receipt["result"],"problems":errors,"receipt":str(archive/"emerald_receipt.json")},indent=2))
    return 0 if receipt["result"]=="PASS" else 1


if __name__=="__main__":
    sys.path.insert(0,str(ROOT))
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",choices=("panel","sound","carrier","rival","trade","call-refusal"))
    parser.add_argument("--prepare",action="store_true")
    args=parser.parse_args()
    raise SystemExit(run(args.mode,args.prepare))
