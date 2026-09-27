"""Opt-in native producer proof, never an automatic unit/emulator test.

Build --arena-probe trade, then run this file. Uses the isolated T2 runner,
native save consent, real scene/evolution, automatic post-save and soft reset.
No manual in-game SAVE is issued after the trade.
"""
TRADE_LUA = r'''
  local G=dofile(os.getenv("SLINK_ROOT").."/lua/tests/gen3_boot_check.lua")
  local cp=G.checkpoint()
  assert(G.boot_to_field(cp,9000),"no field after cold boot")
  G.idle(120)
  assert(G.mash(1200,function() return G.pred_ok(cp,"field_controls_locked") and G.pred_ok(cp,"script_context_status") end),"field never became safe")
  local base,w=0x0201B000,0x0201B050
  local function r16(a) return memory.read_u16_le(a,"System Bus") end
  local function wr16(a,v) memory.write_u16_le(a,v,"System Bus") end
  local function wr32(a,v) memory.write_u32_le(a,v,"System Bus") end
  local function wr8(a,v) memory.write_u8(a,v,"System Bus") end
  assert(rd(base)==0x32505254 and r16(base+4)==2 and rd(base+0x40)==0,"not private v2 producer")
  local flash=assert(G.flash_domain())
  local before=G.save_counter(flash)
  local fail_save=os.getenv("T2_FAIL_POST_SAVE")=="1"
  local oldpid,oldot=rd(0x02024284),rd(0x02024288)
  wr32(base+0x44,0x12345678)
  local function post(op,seq)
    assert(r16(base+6)==0,"overwriting an owned opcode")
    wr8(base+16,0);wr8(base+17,0)
    wr32(base+20,oldpid);wr32(base+24,oldot);wr32(base+28,0xABCDEF01)
    for i=0,15 do wr8(base+32+i,i+1) end
    wr16(base+8,seq);wr16(base+10,1);wr16(base+6,op)
  end
  local save_calls,commit_seen=0,false
  assert(event.on_bus_exec(function()
    save_calls=save_calls+1
    assert(memory.read_u8(w+0x2A,"System Bus")~=1,"committed before native save returned")
    log("NATIVE_SAVE_ENTRY "..save_calls)
  end,0x080DA364,"T2-producer-save"),"save hook missing")
  assert(event.on_bus_exec(function()
    assert((rd(w+0x1C)&2)~=0 and r16(w+0x22)==2,"swap before bound commit marker")
    commit_seen=true;log("COMMIT_ENTERED before original TradeMons body")
  end,0x08050814,"T2-producer-commit"),"commit hook missing")
  post(29,1)
  assert(G.mash(6000,function() return r16(base+6)==0 and r16(base+12)==1 end),"PREPARE timeout")
  log(string.format("PREPARE_DEBUG status=%d reason=%d phase=%d milestones=%X flags=%d lock=%d script=%d",r16(base+10),r16(base+14),rd(base+0x820),rd(w+0x1C),r16(w+0x1A),memory.read_u8(0x03000F9C,"System Bus"),memory.read_u8(0x03000EA8,"System Bus")))
  assert(r16(base+10)==2 and rd(w+0x1C)==1 and r16(w+0x20)==1,"pre-save not proven")
  assert(r16(w+0x1A)==3,"accepted/consent flags missing")
  assert(G.save_counter(flash)==before+1,"PREPARE did not save exactly once")
  log("PRE_SAVE_OK native consent + save")
  local file=assert(io.open(os.getenv("T2_INCOMING"),"rb"));local blob=file:read("a");file:close()
  for i=1,100 do wr8(base+0x100+i-1,blob:byte(i)) end
  if fail_save then wr32(base+0x8A8,1) end
  post(21,2)
  assert(G.mash(12000,function() return r16(base+6)==0 and r16(base+12)==2 end),"SCENE timeout")
  log(string.format("SCENE_DEBUG status=%d reason=%d phase=%d milestones=%X result=%d",r16(base+10),r16(base+14),rd(base+0x820),rd(w+0x1C),memory.read_u8(w+0x2A,"System Bus")))
  local rev=r16(w+0x18)
  assert(rev~=0 and rev%2==0,"incoherent witness")
  assert(rd(w)==0x12345678 and rd(w+4)==0xABCDEF01,"stale witness identity")
  if fail_save then
    assert(rd(w+0x1C)==23 and memory.read_u8(w+0x2A,"System Bus")==3,"missing-save control claimed success")
    assert(save_calls==1 and r16(base+10)==3,"failure did not stay uncertain")
    assert(G.save_counter(flash)==before+1,"failure control wrote a post-save")
    log("POST_SAVE_FAILURE_UNCERTAIN: no POST_SAVE_OK, no success ACK")
  else
    assert(rd(w+0x1C)==31 and memory.read_u8(w+0x2A,"System Bus")==1,"not durable final result")
    for i=1,4 do assert(r16(w+0x20+2*i)==2,"wrong scene milestone sequence") end
    assert(commit_seen and save_calls==2,"native commit/save call count")
    assert(rd(w+0x48)==0x13572468 and rd(w+0x4C)==0x78563412,"received key mismatch")
    assert(G.save_counter(flash)==before+2,"post-save counter missing")
  end
  assert(r16(w+0x18)==rev,"witness changed during read")
  log((fail_save and "UNCERTAIN" or "DURABLE_DONE").." counter="..G.save_counter(flash).."; no later manual SAVE")
  client.saveram() -- host flush only, not an in-game save
  for i=1,4 do joypad.set({A=true,B=true,Start=true,Select=true});G.advance() end
  joypad.set({});G.idle(120)
  assert(rd(base+0x44)==0,"soft reset did not revoke epoch")
  assert(G.boot_to_field(cp,9000),"could not reload native post-trade save")
  local wantpid,wantot=fail_save and oldpid or 0x13572468,fail_save and oldot or 0x78563412
  assert(rd(0x02024284)==wantpid and rd(0x02024288)==wantot,"reload identity differs")
  assert(G.save_counter(flash)==before+(fail_save and 1 or 2),"reload required/created another save")
  local data={}
  for i=0,599 do data[#data+1]=string.char(memory.read_u8(0x02024284+i,"System Bus")) end
  local readback=assert(io.open(os.getenv("T2_RELOAD_PARTY"),"wb"));readback:write(table.concat(data));readback:close()
  log("RESET_WITHOUT_SAVE_RELOAD expected identity retained; epoch revoked")
'''


if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
    from tests.unit.test_patch_arena_probe import run_probe

    raise SystemExit(run_probe("trade"))
