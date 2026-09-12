"""Export the already source-verified RBY safe checkpoint profiles for server validation."""
import argparse
import json
from pathlib import Path
from lupa.lua54 import LuaRuntime

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'data/games/gen1_rby/write_checkpoint.json'


def generate():
    lua=LuaRuntime(unpack_returned_tuples=True)
    game=lua.execute((ROOT/'lua/games/gen1_rby.lua').read_text())
    result={}
    for variant in ('red','blue','yellow'):
        profile=game.PROFILES[variant]
        result[variant]={'write_safe':dict(profile.write_safe.items()),
            **{k:profile[k] for k in ('BATTLE_FLAG_ADDR','JOY_IGNORE_ADDR','FONT_LOADED_ADDR')}}
    return json.dumps(result,indent=2,sort_keys=True)+'\n'


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args();text=generate()
    if args.check:assert OUTPUT.read_text()==text,'write checkpoint data is stale'
    else:OUTPUT.write_text(text,encoding='utf-8',newline='\n')
