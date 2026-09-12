"""Prepare checked R/B/Y randomized companion candidates; runtime remains separate."""
import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from server.gen1_upr_pipeline import prepare_pair  # noqa: E402


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar",required=True,type=Path)
    parser.add_argument("--settings",required=True,type=Path)
    parser.add_argument("--rom-a",required=True,type=Path);parser.add_argument("--rom-b",required=True,type=Path)
    parser.add_argument("--seed-a",required=True);parser.add_argument("--seed-b",required=True)
    parser.add_argument("--output",required=True,type=Path)
    parser.add_argument("--java",default="java");parser.add_argument("--custom-names",type=Path)
    args=parser.parse_args()
    result=prepare_pair(args.jar,args.settings.read_bytes(),{"a":args.rom_a,"b":args.rom_b},args.output,
        seeds={"a":args.seed_a,"b":args.seed_b},java=args.java,custom_names=args.custom_names)
    print(json.dumps(result,indent=2))


if __name__=="__main__":main()
