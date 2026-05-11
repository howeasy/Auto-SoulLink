"""Generate data/rr_sprites.json — RR internal ID to funnotbun sprite filename.

Parses Front_Pic_Table.c and species.h from funnotbun/funnotbun.github.io
(the Radical Red dex site) to build a mapping of every RR species ID to its
correct front sprite filename.

Usage:
    python tools/gen_rr_sprites.py

The output file is loaded by server.py at startup for the status page sprites.
"""

import json
import os
import re
import urllib.request

FRONT_PIC_URL = (
    "https://raw.githubusercontent.com/funnotbun/funnotbun.github.io"
    "/main/data/species/Front_Pic_Table.c"
)
SPECIES_H_URL = (
    "https://raw.githubusercontent.com/funnotbun/funnotbun.github.io"
    "/main/data/species/species.h"
)
OUTPUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "data", "rr_sprites.json")


def main():
    print("Fetching Front_Pic_Table.c ...")
    data1 = urllib.request.urlopen(FRONT_PIC_URL).read().decode()
    sprite_map: dict[str, str] = {}
    for line in data1.split("\n"):
        m = re.search(r"\[(SPECIES_\w+)\].*?(gFrontSprite\w+)Tiles", line)
        if m and m.group(2) != "gFrontSprite000None":
            sprite_map[m.group(1)] = m.group(2)
    print(f"  Parsed {len(sprite_map)} sprite entries from Front_Pic_Table.c")

    print("Fetching species.h ...")
    data2 = urllib.request.urlopen(SPECIES_H_URL).read().decode()
    id_to_name: dict[int, str] = {}
    for m in re.finditer(r"#define\s+(SPECIES_\w+)\s+0x([0-9A-Fa-f]+)", data2):
        name, num = m.group(1), int(m.group(2), 16)
        if name not in ("SPECIES_NONE", "SPECIES_EGG") and num > 0:
            id_to_name[num] = name
    print(f"  Parsed {len(id_to_name)} species IDs from species.h")

    rr_sprites: dict[str, str] = {}
    for sid in sorted(id_to_name.keys()):
        sname = id_to_name[sid]
        if sname in sprite_map:
            rr_sprites[str(sid)] = sprite_map[sname]

    with open(OUTPUT, "w") as f:
        json.dump(rr_sprites, f, separators=(",", ":"))

    print(f"Wrote {len(rr_sprites)} entries to {OUTPUT} "
          f"({os.path.getsize(OUTPUT)} bytes)")
    # Sprite URL pattern:
    # https://raw.githubusercontent.com/funnotbun/funnotbun.github.io
    #   /main/data/species/frontspr/{filename}.png


if __name__ == "__main__":
    main()
