"""Opt-in FR sound engine witnesses; no audible-output or screenshot claims."""
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SOUND_LUA=r'''
  local G=dofile(os.getenv("SLINK_ROOT").."/lua/tests/gen3_boot_check.lua")
  local cp=G.checkpoint()
  assert(G.boot_to_field(cp,9000),"boot failed");G.idle(120)
  assert(G.mash(1200,function() return G.pred_ok(cp,"field_controls_locked") and G.pred_ok(cp,"script_context_status") end),"field unsafe")
  local base=0x0201B000
  local function b(a) return memory.read_u8(a,"System Bus") end
  local function h(a) return memory.read_u16_le(a,"System Bus") end
  local function wh(a,v) memory.write_u16_le(a,v,"System Bus") end
  local function wd(a,v) memory.write_u32_le(a,v,"System Bus") end
  local function wait(n,p) for _=1,n do if p() then return true end;G.advance() end;return p() end
  assert(rd(base)==0x4B4E4C53 and h(base+4)==2 and (rd(base+0x40)&7)==7,"wrong candidate")
  wd(base+0x44,7);wd(base+0x800,7)
  local calls={se=0,fanfare=0,m4a=0}
  local function hook(kind,address)
    assert(event.on_bus_exec(function()
      calls[kind]=calls[kind]+1
      log(string.format("SOUND_CALL kind=%s seq=%d id=%d",kind,h(base+8),emu.getregister("R0")))
    end,address,"T2-sound-"..kind),"missing native hook")
  end
  hook("se",0x080722CC);hook("fanfare",0x08071C60);hook("m4a",0x081DD0F4)
  local seq=0
  local function post(op,song,epoch,status,reason)
    assert(h(base+6)==0,"owned opcode")
    seq=seq+1;wd(base+0x44,epoch);wh(base+16,song)
    wh(base+8,seq);wh(base+10,1);wh(base+6,op)
    assert(wait(120,function() return h(base+12)==seq and h(base+6)==0 end),"sound ACK absent")
    assert(h(base+10)==status and h(base+14)==reason,"wrong sound result")
  end
  local function active(op,song)
    local entry=0x084A32CC+song*8
    local expected=rd(entry);local index=h(entry+4)
    assert(index<4,"bad native player index")
    local player=rd(0x084A329C+index*12)
    post(op,song,7,2,0)
    assert(wait(120,function() return rd(player)==expected and (rd(player+4)&0xffff)~=0 and (rd(player+4)&0x80000000)==0 end),"m4a player never active")
    local status,clock=rd(player+4),rd(player+12)
    assert(wait(120,function() return rd(player+12)~=clock end),"m4a clock never advanced")
    log(string.format("SOUND_ACTIVE op=%d id=%d seq=%d player=%08X header=%08X status=%08X clock=%d->%d",op,song,seq,player,rd(player),status,clock,rd(player+12)))
  end
  active(19,25)
  assert(calls.se==1 and calls.fanfare==0 and calls.m4a==1,"wrong SE call count")
  G.idle(180)
  active(9,257)
  assert(calls.se==1 and calls.fanfare==1 and calls.m4a==2,"wrong fanfare call count")
  local counter=h(0x03000FC6)
  local paused=(rd(0x03007304)&0x80000000)~=0
  assert(counter>0 and paused,"fanfare did not own duration/BGM pause")
  local function fanfare_task()
    for i=0,15 do local a=0x03005090+i*0x28;if b(a+4)~=0 and rd(a)==0x08071CBD then return true end end
    return false
  end
  assert(fanfare_task(),"native fanfare task absent")
  assert(wait(360,function() return h(0x03000FC6)==0 and not fanfare_task() and (rd(0x03007304)&0x80000000)==0 end),"fanfare did not finish/resume BGM")
  log(string.format("FANFARE_RELEASE counter=%d->0 paused=1->0 task=1->0",counter))
  for _,case in ipairs({{19,347,7,2,"invalid_se"},{9,65535,7,2,"invalid_fanfare"},{19,25,0,13,"unarmed_epoch"},{19,25,8,12,"stale_epoch"}}) do
    post(case[1],case[2],case[3],3,case[4]);G.idle(8)
    assert(calls.se==1 and calls.fanfare==1 and calls.m4a==2,"refused request reached native sound")
    log(string.format("SOUND_REFUSED case=%s seq=%d status=3 reason=%d se=%d fanfare=%d m4a=%d configured_epoch=%d request_epoch=%d",case[5],seq,case[4],calls.se,calls.fanfare,calls.m4a,rd(base+0x800),rd(base+0x44)))
  end
  log("SOUND_SCOPE: native routine/player/task RAM evidence only; no audible-output or FR client-toggle claim")
'''


def sound_problems(text,rom,*,song_table=0x084A32CC,mplay_table=0x084A329C,fanfare_id=257):
    problems=[]
    def word(address,size=4):
        start=address-0x08000000
        return int.from_bytes(rom[start:start+size],"little")
    calls=re.findall(r"SOUND_CALL kind=(\w+) seq=(\d+) id=(\d+)",text)
    if calls!=[("se","1","25"),("m4a","1","25"),("fanfare","2",str(fanfare_id)),("m4a","2",str(fanfare_id))]:
        problems.append(f"wrong native call trace: {calls}")
    for op,song,seq in ((19,25,1),(9,fanfare_id,2)):
        match=re.search(rf"SOUND_ACTIVE op={op} id={song} seq={seq} player=([0-9A-F]+) header=([0-9A-F]+) status=([0-9A-F]+) clock=(\d+)->(\d+)",text)
        entry=song_table+song*8
        if not match:
            problems.append(f"missing active player {song}")
            continue
        player,header,status=(int(match[i],16) for i in (1,2,3))
        if (player!=word(mplay_table+12*word(entry+4,2)) or header!=word(entry)
                or not status&0xffff or status&0x80000000 or match[4]==match[5]):
            problems.append(f"player/song/clock differs from ROM table {song}")
    if not re.search(r"FANFARE_RELEASE counter=[1-9]\d*->0 paused=1->0 task=1->0",text):
        problems.append("no native fanfare release")
    for name,seq,reason,epoch in (("invalid_se",3,2,7),("invalid_fanfare",4,2,7),("unarmed_epoch",5,13,0),("stale_epoch",6,12,8)):
        if f"SOUND_REFUSED case={name} seq={seq} status=3 reason={reason} se=1 fanfare=1 m4a=2 configured_epoch=7 request_epoch={epoch}" not in text:
            problems.append(f"missing refusal {name}")
    if "RESULT: PASS" not in text:
        problems.append("script did not pass")
    return problems


def main():
    sys.path.insert(0,str(ROOT))
    from tests.unit.test_patch_arena_probe import run_probe

    target=ROOT/".cache/s"
    target.mkdir(exist_ok=True)
    for name in ("probe.gba","receipt.json"):
        shutil.copyfile(ROOT/"patch/build/candidate-firered-trade"/name,target/name)
    result=run_probe("sound")
    text=(target/"result.txt").read_text()
    rom=(target/"probe.gba").read_bytes()
    problems=sound_problems(text,rom)
    falsifier=bool(sound_problems(text.replace("id=25 seq=1 player=", "id=26 seq=1 player="),rom))
    receipt={"scope":"FR native sound calls/m4a player state; no audible-output/client-toggle qualification",
             "result":"PASS" if not result and not problems and falsifier else "FAIL",
             "problems":problems,"altered_player_receipt_rejected":falsifier,
             "rom_sha256":hashlib.sha256(rom).hexdigest(),
             "run":json.loads((target/"run_receipt.json").read_text())}
    (target/"sound_receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    print(json.dumps(receipt,indent=2))
    return receipt["result"]!="PASS"


if __name__=="__main__":
    raise SystemExit(main())
