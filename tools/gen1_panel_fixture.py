"""Canonical pre-run map/Pokedex/Safari inputs for native panel qualification."""
from __future__ import annotations

import hashlib
import json
import re

from tools.build_gen1_native_trade import ROOT, TARGETS, read_symbols
from tools.gen1_receptionist_fixture import RAM_FIELDS, ROM_FIELDS, receptionist_maps, write_fixture


def make_panel_fixture(variant, map_name, pokedex, directory):
    if map_name != "SafariZoneCenter":
        info = receptionist_maps(variant)[map_name]
        return write_fixture(info,directory,pokedex=pokedex)
    repo = "pokered" if variant != "yellow" else "pokeyellow"
    source = ROOT/".cache/pret"/repo
    symbols = read_symbols(source/(TARGETS[variant]+".sym"))
    lock = json.loads((ROOT/"data/pret_sources.lock.json").read_text())
    pin = lock["clean_roms"][TARGETS[variant]]
    rom = (ROOT/pin["filename"]).read_bytes()
    if hashlib.sha1(rom).hexdigest()!=pin["sha1"]:
        raise ValueError("canonical map fixture input differs")
    def flat(name):
        bank,address=symbols[name]
        return bank*0x4000+address%0x4000
    constants=(source/"constants/map_constants.asm").read_text()
    match=re.search(r"map_const SAFARI_ZONE_CENTER,\s*(\d+),\s*(\d+)\s*;\s*\$([0-9A-F]+)",constants)
    if match is None:
        raise ValueError("Safari map constants changed")
    width,height,map_id=int(match[1]),int(match[2]),int(match[3],16)
    header=rom[flat(map_name+"_h"):flat(map_name+"_h")+12]
    if header[1:3]!=bytes((height,width)) or header[9]!=0:
        raise ValueError("Safari header geometry/connections differ")
    blocks=rom[flat(map_name+"_Blocks"):flat(map_name+"_Blocks")+width*height]
    if blocks!=(source/f"maps/{map_name}.blk").read_bytes():
        raise ValueError("Safari block map differs")
    objects=(source/f"data/maps/objects/{map_name}.asm").read_text()
    info={"variant":variant,"map_name":map_name,"map_id":map_id,"x":14,"y":23,
          "width":width,"height":height,"base_sha1":pin["sha1"],"source_commit":lock["sources"][repo]["commit"],
          "header_hex":header[:10].hex(),"blocks_hex":blocks.hex(),
          "object_count":len(re.findall(r"^\s*object_event\s+",objects,re.M)),
          "ram":{name:symbols[name][1] for name in RAM_FIELDS},
          "rom":{name:{"bank":symbols[name][0],"address":symbols[name][1]} for name in ROM_FIELDS}}
    return write_fixture(info,directory,pokedex=pokedex,safari=True)
