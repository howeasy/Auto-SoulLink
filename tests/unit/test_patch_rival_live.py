"""Opt-in FR real-trainer W1 replacement and late refusal, normal inputs only."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
RIVAL_LUA=r'''
  local G=dofile(os.getenv("SLINK_ROOT").."/lua/tests/gen3_boot_check.lua")
  local cp=G.checkpoint()
  local base=0x0201B000
  local function b(a) return memory.read_u8(a,"System Bus") end
  local function h(a) return memory.read_u16_le(a,"System Bus") end
  local function wb(a,v) memory.write_u8(a,v,"System Bus") end
  local function wh(a,v) memory.write_u16_le(a,v,"System Bus") end
  local function wd(a,v) memory.write_u32_le(a,v,"System Bus") end
  local function hex(a,n) local t={} for i=0,n-1 do t[#t+1]=string.format("%02X",b(a+i)) end return table.concat(t) end
  local function wait(n,p) for _=1,n do if p() then return true end;G.advance() end;return p() end
  local function window()
    return rd(0x030030F4)==0x08010509 and rd(0x03004F84)==0x080123BD and b(0x02023E82)<15
      and h(0x020386AE)==102 and (rd(0x02022B4C)&10)==8 and (b(0x03003529)&2)~=0
  end
  assert(G.boot_to_field(cp,9000),"boot failed");G.idle(120)
  assert(rd(base)==0x4B4E4C53 and h(base+4)==2 and (rd(base+0x40)&16)~=0,"no rival candidate")
  assert(G.mash(1800,function() return rd(0x030030F4)==0x080565B5 and b(0x03000F9C)==0 and b(0x03000EA8)==2 end),"fixture field never quiet")
  local x,y=G.pos(cp);assert(x==41 and y==45,"fixture not at Rick approach")
  log(string.format("TRAINER_READY x=%d y=%d lock=%d script=%d",x,y,b(0x03000F9C),b(0x03000EA8)))
  wd(base+0x44,7);wd(base+0x800,7)
  local function stage(name)
    local file=assert(io.open(os.getenv("SLINK_ROOT").."/.cache/r/"..name,"rb"))
    local data=file:read("a");file:close()
    for i=1,#data do wb(base+0x100+i-1,data:byte(i)) end
  end
  stage("rival.bin")
  local consumes,selected=0,0
  assert(event.on_bus_exec(function()
    if h(base+6)==28 then
      consumes=consumes+1
      log(string.format("RIVAL_CONSUME seq=%d callback=%08X main=%08X stage=%d flags=%X trainer=%d inbattle=%d sp=%08X",h(base+8),rd(0x030030F4),rd(0x03004F84),b(0x02023E82),rd(0x02022B4C),h(0x020386AE),(b(0x03003529)&2)~=0 and 1 or 0,emu.getregister("R13")))
    end
  end,assert(tonumber(os.getenv("T2_RIVAL_DISPATCH"))),"T2-rival-dispatch"),"no dispatch observer")
  assert(event.on_bus_exec(function()
    selected=selected+1
    log(string.format("SELECTION_ENTRY count=%d ack=%d status=%d stage=%d",b(0x0202402A),h(base+12),h(base+10),b(0x02023E82)))
    log("SELECTION_PARTY "..hex(0x0202402C,600))
  end,0x0800D768,"T2-party-selection"),"no selection observer")
  -- Existing cached-native fixture: one normal Right step reaches Rick's sight line.
  G.tap("Right",12,24)
  local sx,sy=G.pos(cp)
  log(string.format("TRAINER_STEP x=%d y=%d lock=%d script=%d trainer=%d",sx,sy,b(0x03000F9C),b(0x03000EA8),h(0x020386AE)))
  for tick=1,6000 do
    if window() then break end
    joypad.set({})
    if (b(0x03003529)&2)==0 and tick%16==0 then joypad.set({A=true}) end
    G.advance()
  end
  joypad.set({})
  log(string.format("WINDOW_POST callback=%08X main=%08X stage=%d trainer=%d flags=%X",rd(0x030030F4),rd(0x03004F84),b(0x02023E82),h(0x020386AE),rd(0x02022B4C)))
  assert(window(),"real trainer W1 never opened")
  log("ORIGINAL_ENEMY "..hex(0x0202402C,200))
  local function post(seq,count)
    assert(h(base+6)==0,"owned opcode")
    wb(base+16,count);wh(base+17,102);wh(base+8,seq);wh(base+10,1);wh(base+6,28)
  end
  post(1,2)
  assert(wait(5,function() return h(base+12)==1 and h(base+6)==0 end),"W1 ACK absent")
  assert(h(base+10)==2,"W1 refused reason="..h(base+14))
  log("RIVAL_ACK seq=1 status=2 reason=0")
  for tick=1,6000 do
    if rd(0x03004FE0)==0x0802E439 then break end
    joypad.set(tick%16==0 and {B=true} or {});G.advance()
  end
  joypad.set({})
  assert(rd(0x03004FE0)==0x0802E439,"no native battle action menu")
  assert(selected==1 and consumes==1,"unexpected native selection/dispatch count")
  local index=h(0x02023BCE+2)
  log(string.format("BATTLE_SNAPSHOT index=%d count=%d mon=%s",index,b(0x0202402A),hex(0x02023BE4+0x58,0x58)))
  assert(index==1,"engine did not skip replacement's fainted lead")
  local before=hex(0x0202402C,600);local before_count=b(0x0202402A)
  assert(not window(),"late control still in W1")
  stage("late.bin");post(2,1)
  assert(wait(5,function() return h(base+12)==2 and h(base+6)==0 end),"late ACK absent")
  assert(h(base+10)==3 and h(base+14)==8,"late request not window_closed")
  assert(before==hex(0x0202402C,600) and before_count==b(0x0202402A),"late request changed enemy party")
  log("LATE_BEFORE "..before)
  log("LATE_AFTER "..hex(0x0202402C,600))
  log(string.format("LATE_REFUSED status=%d reason=%d count=%d unchanged=1 consumes=%d",h(base+10),h(base+14),b(0x0202402A),consumes))
  log("RIVAL_SCOPE: real Rick102 battle, replayed peer team with fainted lead; no live server/duo or save claim")
'''


def rival_problems(text,expected,*,start_callback=0x08010509,dummy_callback=0x080123BD,trainer=102):
    from server.adapters import gen3_codec as codec

    problems=[]
    early=re.search(rf"RIVAL_CONSUME seq=1 callback={start_callback:08X} main={dummy_callback:08X} stage=(\d+) flags=([0-9A-F]+) trainer={trainer} inbattle=1",text)
    if not early or int(early[1])>=15 or int(early[2],16)&10!=8:
        problems.append("missing native W1 consumption")
    if "RIVAL_ACK seq=1 status=2 reason=0" not in text or "SELECTION_ENTRY count=2 ack=1 status=2 stage=15" not in text:
        problems.append("replacement not acknowledged before native selection")
    party=re.search(r"SELECTION_PARTY ([0-9A-F]{1200})",text)
    if not party:
        problems.append("missing native selection party")
    else:
        raw=bytes.fromhex(party[1])
        if raw[:200]!=expected or any(raw[200:]):
            problems.append("selection party differs from staged replacement/clear")
        mons=[codec.decode_party_mon(raw[i:i+100]) for i in (0,100)]
        if any(m["checksum_ok"] is not True for m in mons) or mons[0]["hp"]!=0 or mons[1]["hp"]==0:
            problems.append("replacement not valid fainted/live pair")
    selected=re.search(r"BATTLE_SNAPSHOT index=1 count=2 mon=([0-9A-F]{176})",text)
    if not selected:
        problems.append("engine did not select later viable slot")
    else:
        raw=bytes.fromhex(selected[1])
        mon=codec.decode_party_mon(expected[100:200])
        for off,size,key in ((0,2,"species"),(0x28,2,"hp"),(0x2A,1,"level"),(0x2C,2,"max_hp"),(0x48,4,"personality"),(0x54,4,"ot_id")):
            if int.from_bytes(raw[off:off+size],"little")!=mon[key]:
                problems.append(f"native BattlePokemon {key} differs")
    late=re.search(r"RIVAL_CONSUME seq=2 callback=([0-9A-F]+) main=([0-9A-F]+) stage=(\d+)",text)
    if not late or (late[1]==f"{start_callback:08X}" and late[2]==f"{dummy_callback:08X}" and int(late[3])<15):
        problems.append("late request not observed outside W1")
    before=re.search(r"LATE_BEFORE ([0-9A-F]{1200})",text)
    after=re.search(r"LATE_AFTER ([0-9A-F]{1200})",text)
    if not before or not after or before[1]!=after[1] or "LATE_REFUSED status=3 reason=8 count=2 unchanged=1 consumes=2" not in text:
        problems.append("late refusal changed party or lacks evidence")
    if "RESULT: PASS" not in text:
        problems.append("script did not pass")
    return problems


def main():
    sys.path.insert(0,str(ROOT))
    from server.adapters import gen3_codec as codec
    from tests.unit.test_patch_arena_probe import run_probe

    target=ROOT/".cache/r"
    target.mkdir(exist_ok=True)
    for name in ("probe.gba","receipt.json"):
        shutil.copyfile(ROOT/"patch/build/candidate-firered-trade"/name,target/name)
    peer=codec.party_from_save((ROOT/"tests/fixtures/gen3/firered_party_trainer_b.sav").read_bytes())
    late=codec.encode_party_mon(peer[0])
    peer[0]["hp"]=0
    expected=b"".join(codec.encode_party_mon(mon) for mon in peer)
    (target/"rival.bin").write_bytes(expected)
    (target/"late.bin").write_bytes(late)
    nm=Path(os.environ["SLINK_ARMGCC"])/"arm-none-eabi-nm.exe"
    symbols=subprocess.check_output([str(nm),str(ROOT/"patch/build/candidate-firered-trade/probe.elf")],text=True)
    dispatch=int(next(line.split()[0] for line in symbols.splitlines() if line.split()[-1:]==["slink_native_rival_service"]),16)
    os.environ["T2_RIVAL_DISPATCH"]=hex(dispatch)
    result=run_probe("rival")
    text=(target/"result.txt").read_text()
    problems=rival_problems(text,expected)
    falsifier=bool(rival_problems(text.replace("BATTLE_SNAPSHOT index=1","BATTLE_SNAPSHOT index=0"),expected))
    receipt={"scope":"FR W1+late refusal on real Rick102; replayed peer fixture with fainted lead; no server/duo/save",
             "result":"PASS" if not result and not problems and falsifier else "FAIL","problems":problems,
             "wrong_selection_rejected":falsifier,"dispatch_address":dispatch,
             "rom_sha256":hashlib.sha256((target/"probe.gba").read_bytes()).hexdigest(),
             "payload_sha256":hashlib.sha256(expected).hexdigest(),
             "run":json.loads((target/"run_receipt.json").read_text())}
    (target/"rival_receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    print(json.dumps(receipt,indent=2))
    return receipt["result"]!="PASS"


if __name__=="__main__":
    raise SystemExit(main())
