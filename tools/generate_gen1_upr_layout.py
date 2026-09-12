"""Pin Gen1 UPR config facts; canonical-ROM walking remains in the scanner."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import re
import sys
from bisect import bisect_right
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
PIN="6c36a57ec538f8d69f032ddc8113f0914edc0e312d560ddb9274d3d02ddad587"
PINS={"gameboy_jpn.tbl":"6f52530485d61c84a5b32cf815e0226caf907fcd635ad1ead83348313a9bf3e4",
      "rby_english.tbl":"c82be8cdf0aa85d762e90e98699784a9551ff8cdce2015e84d528d4a0e446c01",
      "Gen1Constants.java":"c55eddf85caac4fb762b2200599a32d302a0a55e4f15638974c993efa67d96f4",
      "Gen1Items.java":"16f4b079c13604d085db911bb3e35750d98f28e7a082682c3189529b58637303"}


def extract(directory):
    directory=Path(directory)
    raw=(directory/"gen1_offsets.ini").read_bytes().replace(b"\r\n",b"\n")
    if hashlib.sha256(raw).hexdigest()!=PIN:
        raise ValueError("Gen1 UPR config source differs")
    profiles={};current=None
    for line in raw.decode().splitlines():
        line=line.split("//",1)[0].strip()
        if not line:continue
        if line.startswith("["):
            name=line[1:-1]
            if name not in ("Red (U)","Blue (U)","Yellow (U)"):break
            current={"settings":{},"statics":[],"tm_text":[]}
            profiles[name]=current
            continue
        key,value=[part.strip() for part in line.split("=",1)]
        fields=current["settings"]
        if key=="CopyFrom":
            previous=profiles[value]
            copy_static=fields.get("CopyStaticPokemon")==1
            copy_text=fields.get("CopyTMText")==1
            # Java copies only entries/arrayEntries, not RomEntry metadata.
            metadata={"Game","Version","NonJapanese","Type","CRCInHeader","CRC32"}
            fields.update(copy.deepcopy({key:value for key,value in previous["settings"].items()
                                         if isinstance(value,(int,list)) and key not in metadata}))
            fields["ExtraTableFile"]=previous["settings"]["ExtraTableFile"]
            if copy_static:current["statics"].extend(copy.deepcopy(previous["statics"]))
            if copy_text:current["tm_text"].extend(copy.deepcopy(previous["tm_text"]))
        elif key in ("StaticPokemon{}","StaticPokemonGhostMarowak{}"):
            groups={name:[int(n.strip(),0) for n in numbers.split(",") if n.strip()]
                    for name,numbers in re.findall(r"(Species|Level)=\[([^\]]*)\]",value)}
            if set(groups)!={"Species","Level"}:raise ValueError("static config differs")
            current["statics"].append(groups|{"ghost":key=="StaticPokemonGhostMarowak{}"})
        elif key=="TMText[]":
            number,offset,template=value[1:-1].split(",",2)
            current["tm_text"].append({"number":int(number,0),"offset":int(offset,0),"template":template})
        elif value.startswith("["):
            fields[key]=[int(n.strip(),0) for n in value[1:-1].split(",") if n.strip()]
        else:
            try:fields[key]=int(value,0)
            except ValueError:fields[key]=value
    table={};sources={"gen1_offsets.ini":PIN}
    for name in ("gameboy_jpn.tbl","rby_english.tbl"):
        raw=(directory/name).read_bytes().replace(b"\r\n",b"\n")
        sources[name]=hashlib.sha256(raw).hexdigest()
        for line in raw.decode("utf-8-sig").splitlines():
            if re.match(r"^[0-9A-Fa-f]{2}=",line):
                number,text=line.split("=",1)
                table[int(number,16)]=text
    # UPR replaces any earlier token at a reused byte before building its encoder.
    encoded={text:number for number,text in table.items()}
    constants=directory.parent/"constants"
    items_text=(constants/"Gen1Items.java").read_text()
    items={name:int(number) for name,number in re.findall(r"public static final int (\w+) = (\d+);",items_text)}
    source=(constants/"Gen1Constants.java").read_text()
    setup=source.split("private static ItemList setupAllowedItems() {",1)[1].split("return allowedItems;",1)[0]
    allowed=set(range(1,items["tm50"]+1))
    singles=re.search(r"banSingles\((.*?)\);",setup,re.S)[1]
    allowed.difference_update(items[name] for name in re.findall(r"Gen1Items\.(\w+)",singles))
    for name,length in re.findall(r"banRange\(Gen1Items\.(\w+), (\d+)\)",setup):
        allowed.difference_update(range(items[name],items[name]+int(length)))
    allowed.difference_update(range(items["hm01"],items["hm01"]+5))
    for name in ("Gen1Constants.java","Gen1Items.java"):
        sources[name]=hashlib.sha256((constants/name).read_bytes().replace(b"\r\n",b"\n")).hexdigest()
    if any(sources[name]!=pin for name,pin in PINS.items()):raise ValueError("Gen1 UPR supporting source differs")
    from tools.verify_canonical_sources import verify
    from tools.build_gen1_native_trade import read_symbols
    verification=verify()
    if verification['failures']:raise ValueError('canonical text-boundary evidence differs: '+repr(verification['failures']))
    for name,profile in profiles.items():
        variant=name.split()[0].lower()
        source='pokeyellow' if variant=='yellow' else 'pokered'
        target='pokeblue' if variant=='blue' else source
        path=ROOT/'.cache/pret'/source/(target+'.sym')
        symbols=read_symbols(path)
        entries=sorted((bank*0x4000+address%0x4000,label) for label,(bank,address) in symbols.items()
            if (bank==0 and address<0x4000) or (bank>0 and 0x4000<=address<0x8000))
        positions=[offset for offset,_ in entries]
        profile['text_symbol_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        for record in profile['tm_text']:
            end,label=entries[bisect_right(positions,record['offset'])]
            record.update(limit=end,next_symbol=label)
        profile['starter_text_bounds']=[]
        if variant!='yellow':
            for offset in profile['settings']['StarterTextOffsets']:
                end,label=entries[bisect_right(positions,offset)]
                profile['starter_text_bounds'].append({'offset':offset,'limit':end,'next_symbol':label})
    return {"schema":"gen1-upr-layout-v1","source_commit":"7f00eb866ed35c8fe3963f078b6a2e0979dc2b8c",
        "source_sha256":sources,"text_encoding":encoded,"allowed_items":sorted(allowed),"tm_items":list(range(items["tm01"],items["tm50"]+1)),
        "profiles":{name.split()[0].lower():profile for name,profile in profiles.items()}}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("config",type=Path)
    options=parser.parse_args()
    output=ROOT/"data/games/gen1_rby/upr_layout.json"
    output.write_text(json.dumps(extract(options.config),indent=2,ensure_ascii=True)+"\n")
    print(output)
