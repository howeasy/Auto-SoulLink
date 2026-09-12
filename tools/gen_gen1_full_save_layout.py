"""Generate the Lua SaveGameData copy layout from pinned pret symbol metadata."""
import argparse
import json
from pathlib import Path

from server.gen1_full_save import layout

ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT/'data/games/gen1_rby/gen1_full_save_layout.lua'


def lua(value):
    if isinstance(value,dict):return '{'+','.join('['+json.dumps(k)+']='+lua(v) for k,v in sorted(value.items()))+'}'
    if type(value) is int:return str(value)
    raise TypeError(value)


def generated():
    return '-- Generated from pinned pret symbols by tools/gen_gen1_full_save_layout.py.\nreturn '+lua({v:layout(v) for v in ('red','blue','yellow')})+'\n'


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    text=generated()
    if args.check:assert TARGET.read_text()==text,'full-save layout is stale'
    else:TARGET.write_text(text,encoding='utf-8',newline='\n')
