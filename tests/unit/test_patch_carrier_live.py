"""Opt-in single-cart native carrier run; replayed server payload, normal inputs."""
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CARRIER_LUA = r'''
  local G=dofile(os.getenv("SLINK_ROOT").."/lua/tests/gen3_boot_check.lua")
  local SP=dofile(os.getenv("SLINK_ROOT").."/lua/tests/gen3_scripted_play.lua")
  local cp=G.checkpoint()
  local base,ctrl,carrier=0x0201B000,0x0201B800,0x0201BB40
  local function b(a) return memory.read_u8(a,"System Bus") end
  local function h(a) return memory.read_u16_le(a,"System Bus") end
  local function wb(a,v) memory.write_u8(a,v,"System Bus") end
  local function wh(a,v) memory.write_u16_le(a,v,"System Bus") end
  local function wd(a,v) memory.write_u32_le(a,v,"System Bus") end
  local function wait(n,p) for _=1,n do if p() then return true end;G.advance() end;return p() end
  local function safe() return rd(0x030030F4)==0x080565B5 and b(0x03000F9C)==0 and b(0x03000EA8)==2 end
  local function hex(a,n) local t={} for i=0,n-1 do t[#t+1]=string.format("%02X",b(a+i)) end return table.concat(t) end
  local function oe(i) return 0x02036E38+i*0x24 end
  local function player() return b(0x0203707D) end
  local function npc() for i=0,15 do if (b(oe(i))&1)~=0 and b(oe(i)+8)==0xF1 then return i end end end
  local function xy(i) return h(oe(i)+0x10)-7,h(oe(i)+0x12)-7 end
  local function idle() return (b(oe(player()))&0x80)~=0 end
  local function trace(tag) log(string.format("TRACE %s cb=%08X lock=%d script=%d active=%d phase=%d npc=%s counter=%d",tag,rd(0x030030F4),b(0x03000F9C),b(0x03000EA8),b(carrier+8),rd(base+0x48),tostring(npc()),rd(ctrl+4))) end
  assert(G.boot_to_field(cp,9000),"boot failed");G.idle(120)
  assert(G.mash(1200,safe),"field unsafe")
  assert(rd(base)==0x4B4E4C53 and h(base+4)==2,"wrong candidate")
  local oldpid,oldot=rd(0x02024284),rd(0x02024288)
  local party_before=hex(0x02024284,b(0x02024029)*100)
  local flash=assert(G.flash_domain());local before_save=G.save_counter(flash);local saves=0
  assert(event.on_bus_exec(function() saves=saves+1 end,0x080DA364,"T2-carrier-native-save"),"save hook absent")
  wd(base+0x44,7);wd(ctrl,7);wb(ctrl+8,1)
  SP.play.follow(cp,"route1_edge_to_pokecenter_door","carrier")
  SP.warp_to(cp,"Up",30,SP.DEST.center,"carrier Center door")
  SP.play.follow(cp,"pokecenter_entrance_to_nurse","carrier")
  assert(wait(180,function() return npc() and safe() end),"native NPC absent")
  local deadline=emu.framecount()+3000
  while emu.framecount()<deadline do
    local x,y=G.pos(cp);if x==3 and y==4 then break end
    assert(y==4 and x>=3,"left row4 route")
    for _=1,12 do joypad.set({Left=true});G.advance() end;G.idle(20)
  end
  local x,y=G.pos(cp);assert(x==3 and y==4,"could not reach NPC approach")
  local facing={Up=2,Down=1,Left=3,Right=4}
  local adj={["0,-1"]="Up",["0,1"]="Down",["-1,0"]="Left",["1,0"]="Right"}
  local function talk(run)
    assert(wait(180,safe),"field unsafe before talk")
    local before=rd(ctrl+4)
    for _=1,500 do
      local slot=npc();assert(slot,"NPC disappeared")
      local nx,ny=xy(slot);local px,py=G.pos(cp)
      local dir=adj[(nx-px)..","..(ny-py)]
      if dir then
        if (b(oe(player())+0x18)&15)~=facing[dir] then G.tap(dir,3,20) end
        local mx,my=xy(slot);px,py=G.pos(cp)
        if adj[(mx-px)..","..(my-py)]==dir and idle() and safe() and (b(oe(player())+0x18)&15)==facing[dir] then
          G.tap("A",1,20)
          if rd(ctrl+4)~=before then
            assert(rd(ctrl+4)==before+1,"counter did not advance exactly once")
            log(string.format("NPC_EDGE %d counter=%d->%d slot=%d local=%d map=%d,%d field=%d owned=%d",run,before,rd(ctrl+4),slot,b(oe(slot)+8),b(oe(slot)+10),b(oe(slot)+9),safe() and 1 or 0,b(carrier+8)))
            return
          end
        end
      elseif px==3 and py==4 then G.tap("Up",12,20) end
      if not safe() then G.tap("B",2,20) end
      G.idle(8)
    end
    trace("talk-failure");error("NPC A did not produce counter")
  end
  local function encoded(s)
    local out={};local punctuation={[46]=0xad,[58]=0xf0,[63]=0xac,[33]=0xab,[45]=0xae}
    for i=1,#s do local c=s:byte(i)
      local v=c==10 and 0xfe or c==32 and 0 or punctuation[c]
        or c>=48 and c<=57 and c-48+0xa1 or c>=97 and c<=122 and c-97+0xd5
        or c>=65 and c<=90 and c-65+0xbb
      assert(v,"unsupported fixture character");out[#out+1]=v
    end
    out[#out+1]=0xff;return out
  end
  local function stage_text(s)
    local bytes=encoded(s);assert(#bytes<=256)
    for i=0,255 do wb(base+0x360+i,0xff) end
    for i,v in ipairs(bytes) do wb(base+0x360+i-1,v) end
  end
  local function stage_choices()
    local bytes={2}
    for _,s in ipairs({"Trade","Say hey"}) do for _,v in ipairs(encoded(s)) do bytes[#bytes+1]=v end end
    for i=0,111 do wb(base+0x560+i,0xff) end
    for i,v in ipairs(bytes) do wb(base+0x560+i-1,v) end
    stage_text("OAK: Took you long enough.\nPEER is waiting. Make it quick.")
  end
  local seq=0
  local function post(op,args)
    assert(safe() and h(base+6)==0 and b(carrier+8)==0,"posting over owned UI")
    seq=seq+1
    for i=0,31 do wb(base+16+i,0) end
    if args then args() end
    wh(base+8,seq);wh(base+10,1);wh(base+6,op)
    return seq
  end
  local function ui(op,button,expected)
    local job=post(op,function() if op==22 then wb(base+16,1) end end)
    assert(wait(180,function() return b(carrier+8)==1 end),"UI not owned")
    assert(h(base+10)==1 and h(base+12)~=job,"premature UI ACK")
    assert(rd(carrier)==7 and h(carrier+4)==job and h(carrier+6)==op,"unbound UI owner")
    if op==20 then assert(wait(240,function() return rd(0x030030F4)~=0x080565B5 end),"chooser CB never entered") end
    log(string.format("UI_ENTER op=%d seq=%d epoch=%d owned=%d cb=%08X",op,job,rd(carrier),b(carrier+8),rd(0x030030F4)))
    if op==22 then log("CHOICES_COPY "..hex(carrier+266,112)) end
    if op==17 or op==22 then log("TEXT_COPY "..hex(carrier+10,256)) end
    for _=1,240 do
      if h(base+12)==job and h(base+10)~=1 then break end
      G.tap(button,2,14)
    end
    trace("after-ui-"..op)
    assert(h(base+12)==job and h(base+10)==2 and b(base+0x30)==expected,"UI result mismatch op="..op)
    assert(safe() and b(carrier+8)==0,"UI returned before field/owner release")
    if op==20 then assert(h(0x020370C0)==expected,"chooser game var differs") end
    log(string.format("UI_DONE op=%d seq=%d result=%d owned=%d field=1",op,job,b(base+0x30),b(carrier+8)))
  end
  talk(1);stage_choices();ui(22,"A",0);ui(20,"A",0)
  stage_text("Trade your Squirtle for Pidgey?");ui(17,"A",1)
  -- Same native consent/pre-save as the durable protocol; withdraw before SCENE.
  local function identity()
    wb(base+16,0);wb(base+17,0);wd(base+20,oldpid);wd(base+24,oldot);wd(base+28,0x12345678)
    for i=0,15 do wb(base+32+i,i+1) end
  end
  local prep=post(29,identity)
  for _=1,360 do if h(base+12)==prep and h(base+10)~=1 then break end;G.tap("A",2,14) end
  assert(h(base+12)==prep and h(base+10)==2 and rd(base+0x48)==2,"native PREPARE failed")
  assert(rd(base+0x50+0x1c)==1 and h(base+0x50+0x1a)==3 and saves==1,"native pre-save evidence missing")
  assert(G.save_counter(flash)==before_save+1,"native save counter did not advance once")
  log("PREPARE_WITNESS "..hex(base+0x50,80))
  log(string.format("PREPARE_DONE seq=%d phase=%d saves=%d counter=%d->%d",prep,rd(base+0x48),saves,before_save,G.save_counter(flash)))
  local withdraw=post(30,identity);assert(wait(60,function() return h(base+12)==withdraw end),"withdraw ACK missing")
  assert(b(base+0x50+0x2a)==2 and rd(base+0x48)==4,"withdraw not unchanged")
  log(string.format("WITHDRAW_DONE seq=%d result=%d phase=%d",withdraw,b(base+0x50+0x2a),rd(base+0x48)))
  talk(2);stage_choices();ui(22,"B",127);ui(20,"B",7)
  stage_text("Trade your Squirtle for Pidgey?");ui(17,"B",0)
  assert(party_before==hex(0x02024284,b(0x02024029)*100),"carrier mutated party")
  log("PARTY_UNCHANGED "..party_before)
  wb(ctrl+8,0);assert(wait(120,function() return not npc() end),"NPC not removed on disable")
  assert(safe() and b(carrier+8)==0,"final field/ownership failure")
  log("NPC_DISABLED field=1 owned=0")
  client.saveram()
  log("CARRIER_SCOPE: replayed server payload; native UI+PREPARE/WITHDRAW; no server/duo/SCENE claim")
'''


def carrier_problems(text, seed=None, saved=None):
    from server.adapters import gen3_codec as codec
    from tools.e2e_duo import gen3_panel_text

    problems = []
    edges = re.findall(r"NPC_EDGE (\d+) counter=(\d+)->(\d+) slot=(\d+) local=241 map=5,4 field=1 owned=0", text)
    if len(edges)!=2 or any(int(end)!=int(start)+1 or int(slot)>=16 for _,start,end,slot in edges):
        problems.append("missing native NPC counter edges")
    expected=[("22","1","0"),("20","2","0"),("17","3","1"),
              ("22","6","127"),("20","7","7"),("17","8","0")]
    done=re.findall(r"UI_DONE op=(\d+) seq=(\d+) result=(\d+) owned=0 field=1",text)
    if done!=expected:
        problems.append(f"native menu/chooser/offer results differ: {done}")
    for op,seq,_ in expected:
        if not re.search(rf"UI_ENTER op={op} seq={seq} epoch=7 owned=1 cb=[0-9A-F]+",text):
            problems.append(f"unbound UI entry {op}/{seq}")
    for seq in (2,7):
        entry=re.search(rf"UI_ENTER op=20 seq={seq} epoch=7 owned=1 cb=([0-9A-F]+)",text)
        if not entry or int(entry[1],16)==0x080565B5:
            problems.append("party chooser never left field callback")
    expected_texts=["OAK: Took you long enough.\nPEER is waiting. Make it quick.",
                    "Trade your Squirtle for Pidgey?"]*2
    decoded=[gen3_panel_text(bytes.fromhex(raw)) for raw in re.findall(r"TEXT_COPY ([0-9A-F]{512})$",text,re.M)]
    if decoded!=expected_texts:
        problems.append("owned text differs from replayed server payload")
    choices=re.findall(r"CHOICES_COPY ([0-9A-F]{224})$",text,re.M)
    if len(choices)!=2:
        problems.append("missing owned options")
    for raw in choices:
        data=bytes.fromhex(raw)
        options=[codec.decode_name(part) for part in data[1:].split(b"\xff")[:2]]
        if data[0]!=2 or options!=["Trade","Say hey"]:
            problems.append("owned options differ")
    raw=re.search(r"PREPARE_WITNESS ([0-9A-F]{160})",text)
    if not raw:
        problems.append("missing PREPARE witness")
    else:
        w=bytes.fromhex(raw[1])
        if (int.from_bytes(w[:4],"little")!=7 or int.from_bytes(w[4:8],"little")!=0x12345678
                or w[8:24]!=bytes(range(1,17)) or not int.from_bytes(w[24:26],"little")
                or w[24]&1 or int.from_bytes(w[26:28],"little")!=3
                or int.from_bytes(w[28:32],"little")!=1 or int.from_bytes(w[32:34],"little")!=4):
            problems.append("wrong PREPARE identity/consent/save/seq")
    save_match=re.search(r"PREPARE_DONE seq=4 phase=2 saves=1 counter=(\d+)->(\d+)",text)
    if not save_match or int(save_match[2])!=int(save_match[1])+1:
        problems.append("native pre-save count missing")
    if "WITHDRAW_DONE seq=5 result=2 phase=4" not in text:
        problems.append("withdrawal not unchanged")
    if "PARTY_UNCHANGED " not in text or "NPC_DISABLED field=1 owned=0" not in text:
        problems.append("missing party/cleanup evidence")
    if seed is not None:
        original=codec.party_from_save(seed)
        def roster(party):
            return [(m["species"],m["personality"],m["ot_id"]) for m in party]
        dump=re.search(r"PARTY_UNCHANGED ([0-9A-F]+)$",text,re.M)
        raw=bytes.fromhex(dump[1]) if dump else b""
        if len(raw)!=len(original)*100:
            problems.append("party RAM length differs from seed")
        else:
            party=[codec.decode_party_mon(raw[i:i+100]) for i in range(0,len(raw),100)]
            if roster(party)!=roster(original) or any(m["checksum_ok"] is not True for m in party):
                problems.append("independent party RAM decode differs")
        if saved is not None:
            valid,why=codec.qualify_flash(saved)
            if not valid:
                problems.append(f"native SaveRAM invalid: {why}")
            elif (roster(codec.party_from_save(saved))!=roster(original)
                  or codec.parse_flash(saved)["counter"]!=codec.parse_flash(seed)["counter"]+1):
                problems.append("native SaveRAM party/counter differs")
    if "RESULT: PASS" not in text:
        problems.append("script did not pass")
    return problems


def main():
    sys.path.insert(0,str(ROOT))
    from tests.unit.test_patch_arena_probe import run_probe

    target=ROOT / ".cache/c"
    target.mkdir(exist_ok=True)
    for name in ("probe.gba","receipt.json"):
        shutil.copyfile(ROOT / "patch/build/candidate-firered-trade" / name,target/name)
    result=run_probe("carrier")
    text=(target/"result.txt").read_text()
    problems=carrier_problems(text,(target/"seed.sav").read_bytes(),
                              (target/"frontend/GBA/Save RAM/probe.SaveRAM").read_bytes())
    receipt={"scope":"single FR native carrier with replayed server payload; no server/duo/SCENE",
             "result":"PASS" if not result and not problems else "FAIL","problems":problems,
             "rom_sha256":hashlib.sha256((target/"probe.gba").read_bytes()).hexdigest(),
             "run":json.loads((target/"run_receipt.json").read_text())}
    (target/"carrier_receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    print(json.dumps(receipt,indent=2))
    return receipt["result"]!="PASS"


if __name__=="__main__":
    raise SystemExit(main())
