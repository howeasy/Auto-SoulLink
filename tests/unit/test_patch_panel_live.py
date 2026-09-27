"""Opt-in FR START panel run. Normal menu inputs; Python decodes native RAM.

Replays the row payload from the accepted RR receipt as a disclosed input fixture.
This tests FR producer/UI, not a server or T3 panel adapter. No screenshots oracle.
"""
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROWS = ["DUO0|Treecko|6|22/22|38||", "|Treecko|6|22/22|38||",
        "Pairs alive|1/1", "Dead zones|0", "Badges|0/8"]
PANEL_LUA = r'''
  local G=dofile(os.getenv("SLINK_ROOT").."/lua/tests/gen3_boot_check.lua")
  local cp=G.checkpoint()
  assert(G.boot_to_field(cp,9000),"no field after cold boot")
  G.idle(120)
  assert(G.mash(1200,function() return G.pred_ok(cp,"field_controls_locked") and G.pred_ok(cp,"script_context_status") end),"field unsafe")
  local base,info,snapshot=0x0201B000,0x0201B6E0,0x0201BA00
  local function b(a) return memory.read_u8(a,"System Bus") end
  local function h(a) return memory.read_u16_le(a,"System Bus") end
  local function wb(a,v) memory.write_u8(a,v,"System Bus") end
  local function wh(a,v) memory.write_u16_le(a,v,"System Bus") end
  local function wd(a,v) memory.write_u32_le(a,v,"System Bus") end
  local function wait(n,p) for _=1,n do if p() then return true end;G.advance() end;return p() end
  local function hex(a,n) local t={} for i=0,n-1 do t[#t+1]=string.format("%02X",b(a+i)) end return table.concat(t) end
  local function vram() local v=0 for a=0x06000000,0x0600FFFF,4 do v=(v*31+rd(a))%0x7FFFFFFF end return string.format("%08X",v) end
  assert(rd(base)==0x4B4E4C53 and h(base+4)==2 and (rd(base+0x40)&3)==3,"wrong candidate")
  local rows={"DUO0|Treecko|6|22/22|38||","|Treecko|6|22/22|38||","Pairs alive|1/1","Dead zones|0","Badges|0/8","","","PAGE 1/1"}
  -- Host-owned ABI staging only. All game navigation uses joypad inputs below.
  wd(base+0x44,7);wd(info,7)
  for row=0,7 do
    assert(#rows[row+1]<32,"fixture row too wide")
    for i=0,31 do wb(info+32+row*32+i,0xff) end
    for i=1,#rows[row+1] do
      local c=rows[row+1]:byte(i)
      local v=c==124 and 0xfe or c==32 and 0 or c==47 and 0xba
        or c>=48 and c<=57 and c-48+0xa1 or c>=97 and c<=122 and c-97+0xd5 or c-65+0xbb
      wb(info+32+row*32+i-1,v)
    end
  end
  wb(info+8,5);wb(info+9,0);wb(info+10,1);wb(info+11,1)
  for run,button in ipairs({"A","B"}) do
    assert(wait(180,function() return b(0x03000F9C)==0 and b(0x03000EA8)==2 end),"field not free")
    G.idle(30);wh(info+4,run)
    local before=vram()
    G.tap("Start",2,60)
    local count=b(0x020370F5);local target=nil;local order={}
    assert(count>0 and count<=8,"bad menu count")
    for i=0,count-1 do order[#order+1]=b(0x020370F6+i);if order[#order]==9 then target=i end end
    log(string.format("START_MENU %d count=%d order=%s cursor=%d",run,count,table.concat(order,","),b(0x020370F4)))
    assert(target and order[count]==6 and order[count-1]==9,"SOULLINK/EXIT shape missing")
    for _=1,count do
      local cursor=b(0x020370F4);if cursor==target then break end
      G.tap("Down",2,14)
      assert(b(0x020370F4)==(cursor+1)%count,"cursor did not advance one row")
    end
    assert(b(0x020370F4)==target,"cursor missed SOULLINK")
    G.tap("A",2,10)
    local drawn=wait(240,function() return b(info+14)==2 and h(info+6)==run and b(0x03000F9C)~=0 end)
    if not drawn then log(string.format("DEBUG state=%d drawn=%d lock=%d script=%d runtime=%d,%d,%d active=%d",b(info+14),h(info+6),b(0x03000F9C),b(0x03000EA8),rd(base+0x940),rd(base+0x944),rd(base+0x948),b(base+0xB20))) end
    assert(drawn,"panel never drawn")
    G.idle(120)
    local colors=0 for a=0x05000000,0x050001FF do colors=colors+b(a) end
    local after=vram()
    assert(before~=after and colors>0,"VRAM unchanged or palette black")
    assert(rd(snapshot)==7 and h(snapshot+4)==run,"snapshot identity mismatch")
    log(string.format("PANEL_OPEN %d epoch=%d request=%d drawn=%d state=%d sc2=%d lines=%d page=%d pages=%d vram=%s->%s palette=%d",run,rd(snapshot),h(snapshot+4),h(info+6),b(info+14),b(0x03000F9C),b(snapshot+8),b(snapshot+9),b(snapshot+10),before,after,colors))
    for i=0,b(snapshot+8)-1 do log(string.format("PANEL_LINE %d %d %s",run,i,hex(snapshot+32+i*32,32))) end
    log(string.format("PANEL_SLOT7 %d %s",run,hex(snapshot+32+7*32,32)))
    G.tap(button,2,10)
    assert(wait(180,function() return b(info+14)==0 and h(info+12)==run and b(0x03000F9C)==0 end),"panel did not close/release")
    assert(b(info+15)==(button=="A" and 0 or 0x7f),"wrong A/B result")
    log(string.format("PANEL_CLOSED %d button=%s closed=%d result=%d sc2=%d",run,button,h(info+12),b(info+15),b(0x03000F9C)))
  end
  assert(h(base+6)==0,"menu opening unexpectedly posted an opcode")
  log("PANEL_SCOPE: native FR producer UI; replayed row fixture, no server/T3 adapter, no save claim")
'''


def panel_problems(text):
    from tools.e2e_duo import gen3_panel_text

    problems = []
    for n, button, result in ((1, "A", 0), (2, "B", 127)):
        menu = re.search(rf"START_MENU {n} count=(\d+) order=([\d,]+) cursor=(\d+)", text)
        if not menu or not menu[2].endswith(",9,6"):
            problems.append(f"open {n}: missing normal START/SOULLINK/EXIT")
        opened = re.search(rf"PANEL_OPEN {n} epoch=7 request={n} drawn={n} state=2 sc2=1 lines=5 page=0 pages=1 vram=(\w+)->(\w+) palette=(\d+)", text)
        if not opened or opened[1] == opened[2] or int(opened[3]) == 0:
            problems.append(f"open {n}: missing bound drawing/lock/VRAM/palette witness")
        for row, expected in enumerate(ROWS):
            raw = re.search(rf"PANEL_LINE {n} {row} ([0-9A-F]{{64}})$", text, re.M)
            if not raw or gen3_panel_text(bytes.fromhex(raw[1])) != expected.replace("|", "\n"):
                problems.append(f"open {n} row {row}: independent decode differs")
        raw = re.search(rf"PANEL_SLOT7 {n} ([0-9A-F]{{64}})$", text, re.M)
        if not raw or gen3_panel_text(bytes.fromhex(raw[1])) != "PAGE 1/1":
            problems.append(f"open {n}: bad page header")
        if f"PANEL_CLOSED {n} button={button} closed={n} result={result} sc2=0" not in text:
            problems.append(f"open {n}: missing {button} closure/release")
    if "RESULT: PASS" not in text:
        problems.append("native script did not pass")
    return problems


def main():
    sys.path.insert(0, str(ROOT))
    from tests.unit.test_patch_arena_probe import run_probe

    target = ROOT / ".cache/p"
    target.mkdir(exist_ok=True)
    for name in ("probe.gba", "receipt.json"):
        shutil.copyfile(ROOT / "patch/build/candidate-firered-trade" / name, target / name)
    (target / "input_rows.json").write_text(json.dumps(ROWS), encoding="utf-8")
    result = run_probe("panel")
    text = (target / "result.txt").read_text()
    problems = panel_problems(text)
    corrupted = re.sub(r"(PANEL_LINE 1 0 )[0-9A-F]{2}", r"\g<1>AA", text)
    falsifier = bool(panel_problems(corrupted))
    receipt = {"scope": "FR native panel only, replayed RR row payload; no server/client qualification",
               "result": "PASS" if not result and not problems and falsifier else "FAIL",
               "problems": problems, "corrupt_readback_rejected": falsifier,
               "rom_sha256": hashlib.sha256((target / "probe.gba").read_bytes()).hexdigest(),
               "input_rows": ROWS, "run": json.loads((target / "run_receipt.json").read_text())}
    (target / "panel_receipt.json").write_text(json.dumps(receipt, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["result"] == "PASS" else 1


def test_panel_readback_oracle_rejects_missing_corrupt_and_unbound_evidence():
    # Literal RAM rows captured from the 2026-09-27 native run, not re-encoded
    # with the decoder under test. Both native opens displayed these bytes.
    raw_rows = [
        "BECFC9A1FECEE6D9D9D7DFE3FEA7FEA3A3BAA3A3FEA4A9FEFEFFFFFFFFFFFFFF",
        "FECEE6D9D9D7DFE3FEA7FEA3A3BAA3A3FEA4A9FEFEFFFFFFFFFFFFFFFFFFFFFF",
        "CAD5DDE6E700D5E0DDEAD9FEA2BAA2FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF",
        "BED9D5D800EEE3E2D9E7FEA1FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF",
        "BCD5D8DBD9E7FEA1BAA9FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF",
    ]
    lines = []
    for n, button, result in ((1, "A", 0), (2, "B", 127)):
        lines += [f"START_MENU {n} count=8 order=0,1,2,3,4,5,9,6 cursor=0",
                  f"PANEL_OPEN {n} epoch=7 request={n} drawn={n} state=2 sc2=1 lines=5 page=0 pages=1 vram=1->2 palette=47461"]
        lines += [f"PANEL_LINE {n} {i} {raw}" for i, raw in enumerate(raw_rows)]
        lines += [f"PANEL_SLOT7 {n} CABBC1BF00A2BAA2FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF",
                  f"PANEL_CLOSED {n} button={button} closed={n} result={result} sc2=0"]
    text = "\n".join(lines + ["RESULT: PASS"])
    assert not panel_problems(text)
    for before, after in (("BECFC9A1", "AACFC9A1"), ("epoch=7", "epoch=8"),
                          ("vram=1->2", "vram=1->1"), ("result=127", "result=0"),
                          ("PANEL_LINE 1 0", "MISSING_LINE 1 0")):
        assert panel_problems(text.replace(before, after))


if __name__ == "__main__":
    raise SystemExit(main())
