"""data/games/gen1_rby/map_names.json: every Gen 1 map id -> its name, from pret's
constants/map_constants.asm (the order of `map_const` lines IS the id). The board names the
maps area_map.json does not (a town without wild encounters, a gym, a house) with this
instead of "Map 5".

    python tools/gen_gen1_map_names.py [path/to/pokered]
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / ".cache" / "pret" / "pokered"
OUT = ROOT / "data" / "games" / "gen1_rby" / "map_names.json"


def name(const: str) -> str:
    w = const.replace("_", " ").title()
    w = re.sub(r"\b(Bill|Oak|Diglett|Blue|Red|Lorelei|Agatha|Bruno|Lance|Champion|Copycat|Fuji|"
               r"Psychic|Rater|Warden|Grandpa)s\b", r"\1's", w)
    for a, b in (("Mt ", "Mt. "), ("Mr ", "Mr. "), ("Ss ", "S.S. "), ("Silph Co", "Silph Co."),
                 ("Pokecenter", "Pokémon Center"), ("Pokemon", "Pokémon"), ("Fuchsia Bill's", "Bill's")):
        w = w.replace(a, b)
    return w


src = (SRC / "constants" / "map_constants.asm").read_text(encoding="utf-8")
consts = re.findall(r"^\s*map_const\s+(\w+)", src, re.M)
names = {i: name(c) for i, c in enumerate(consts) if not c.startswith("UNUSED_")}
OUT.write_text(json.dumps(names, indent=0, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"{len(names)} maps -> {OUT.relative_to(ROOT)}")
