"""Opt-in production UPS -> boot, panel, trade/save/evolution/reload smoke."""
import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def run(title):
    from tools.gen3_companions import published
    from tests.unit import test_patch_trade_live as trade
    from tests.unit.test_patch_arena_probe import run_probe
    from tests.unit.test_patch_panel_live import PANEL_LUA,panel_problems
    from tests.unit.test_patch_leafgreen_live import lg_transform
    if title=="emerald":
        from tests.unit.test_patch_emerald_live import run as em_run
        return em_run("trade",production=True)
    base=ROOT/f".cache/pub-{title}"
    base.mkdir(parents=True,exist_ok=True)
    filename={"firered":"FireRed","leafgreen":"LeafGreen"}[title]
    clean=(Path(os.environ["SLINK_GEN3_ROMS"])/f"Pokemon - {filename} Version (USA).gba").read_bytes()
    rom,row=published(title,clean)
    (base/"probe.gba").write_bytes(rom)
    shutil.copyfile(ROOT/f"patch/build/production-{title}/receipt.json",base/"receipt.json")
    original=trade.TRADE_LUA
    trade.TRADE_LUA=PANEL_LUA+original.replace("rd(base)==0x32505254","rd(base)==0x4B4E4C53").replace("rd(base+0x40)==0","rd(base+0x40)==23")
    try:
        result=run_probe("trade",title=title,base_dir=base,
                         lua_transform=(lambda s:lg_transform(s,"trade")[0]) if title=="leafgreen" else None)
    finally:trade.TRADE_LUA=original
    errors=panel_problems((base/"result.txt").read_text())
    receipt={"title":title,"result":"PASS" if not result and not errors else "FAIL","problems":errors,
             "production":True,"rom_sha256":hashlib.sha256(rom).hexdigest(),"ups_sha256":row["ups_sha256"],
             "scope":"Published UPS applied to pinned clean ROM: boot/panel/trade/save/evolution/reload; SYNTH full-party/full-box fixture",
             "run":json.loads((base/"run_receipt.json").read_text()),
             "save_reload":json.loads((base/"census_receipt.json").read_text())}
    (base/"production_receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    archive=ROOT/f"patch/build/production-{title}-live-20260927"
    archive.mkdir(exist_ok=True)
    for name in ("production_receipt.json","run_receipt.json","census_receipt.json","result.txt","probe.lua","receipt.json","config.ini","seed.sav","incoming.bin","reload_party.bin"):
        shutil.copyfile(base/name,archive/name)
    shutil.copyfile(base/"frontend/GBA/Save RAM/probe.SaveRAM",archive/"native.SaveRAM")
    print(json.dumps({"result":receipt["result"],"problems":errors,"receipt":str(archive/"production_receipt.json")},indent=2))
    return int(receipt["result"]!="PASS")


if __name__=="__main__":
    import sys
    sys.path.insert(0,str(ROOT))
    parser=argparse.ArgumentParser()
    parser.add_argument("title",choices=("firered","leafgreen","emerald"))
    raise SystemExit(run(parser.parse_args().title))
