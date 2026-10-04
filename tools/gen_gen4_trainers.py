#!/usr/bin/env python3
"""gen_gen4_trainers.py -- HGSS trainer roster from pinned pret/pokeheartgold.

Writes data/games/gen4_hgss/trainers.json. Keys are trainer indexes (= the id the battle reads).

Sources (pokeheartgold @ the pinned commit):
  files/poketool/trainer/trainers.json  738 trainers: name ("{TRNAME}Falkner"), class const, party, items, AI flags
  include/constants/trainers.h          TRAINER_* const per index
  include/constants/trainer_class.h     TRAINERCLASS_* const per class id
  files/msgdata/msg/msg_0730.gmm        class display names (msg 0729 trainer names are the same strings the JSON holds)
  files/msgdata/msg/msg_0237/0750/0222  species / move / item names
  include/constants/{species,moves,items}.h

Trainer JSON has no HEARTGOLD/SOULSILVER split (checked); messages and sprite data are not carried.
`role` marks the story-critical classes (leader, elite_four, champion, rival, red) from the class constant.

Usage:
  python tools/gen_gen4_trainers.py [--pret PATH] [--check]
Exit: 0 ok, 1 drift / wrong pret commit, 2 pret clone absent.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_gen4_area_map as base  # noqa: E402

INPUTS = [
    "files/poketool/trainer/trainers.json",
    "include/constants/trainers.h",
    "include/constants/trainer_class.h",
    "include/constants/species.h",
    "include/constants/moves.h",
    "include/constants/items.h",
    "files/msgdata/msg/msg_0730.gmm",
    "files/msgdata/msg/msg_0237.gmm",
    "files/msgdata/msg/msg_0750.gmm",
    "files/msgdata/msg/msg_0222.gmm",
]
ROLE_PREFIXES = (("TRAINERCLASS_LEADER_", "leader"), ("TRAINERCLASS_ELITE_FOUR", "elite_four"), ("TRAINERCLASS_CHAMPION", "champion"), ("TRAINERCLASS_RIVAL", "rival"), ("TRAINERCLASS_PKMN_TRAINER_RED", "red"))


def role_of(class_const: str) -> str | None:
    return next((role for prefix, role in ROLE_PREFIXES if class_const.startswith(prefix)), None)


def clean_name(raw: str) -> str:
    """Most names carry the {TRNAME} text tag; a few (Cheryl, ...) are plain. Any other tag is unexpected."""
    name = raw.removeprefix("{TRNAME}").strip()
    assert "{" not in name, f"unexpected tag in trainer name {raw!r}"
    return name


def build(clone: Path) -> dict[str, str]:
    raw = json.loads(base.read(clone, "files/poketool/trainer/trainers.json"))["trainers"]
    assert len(raw) == 738, f"trainers.json has {len(raw)} trainers, pinned source has 738"
    assert "HEARTGOLD" not in base.read(clone, "files/poketool/trainer/trainers.json"), "trainers.json grew an HG/SS split; this generator would merge it"

    species = base.defines(clone, "include/constants/species.h", "SPECIES_")
    moves = base.defines(clone, "include/constants/moves.h", "MOVE_")
    items = base.defines(clone, "include/constants/items.h", "ITEM_")
    class_ids = base.defines(clone, "include/constants/trainer_class.h", "TRAINERCLASS_")
    trainer_consts = {v: k for k, v in base.defines(clone, "include/constants/trainers.h", "TRAINER_").items() if k != "FIRST_TRAINER_INDEX"}
    species_msg, move_msg, item_msg, class_msg = (base.gmm(clone, b) for b in (237, 750, 222, 730))

    def sname(c):
        return "" if species[c] == 0 else base.titled(species_msg[species[c]])

    def class_name(c):
        return class_msg[class_ids[c]].replace("₧₦", "PKMN")

    used_classes = sorted({t["class"] for t in raw}, key=lambda c: class_ids[c])
    classes = {str(class_ids[c]): {"const": c, "name": class_name(c), "role": role_of(c)} for c in used_classes}

    trainers = {}
    for idx, t in enumerate(raw):
        party = []
        for m in t["party"]:
            mon = {"species_id": species[m["species"]], "name": sname(m["species"]), "level": m["level"], "difficulty": m["difficulty"]}
            if m.get("item", "ITEM_NONE") != "ITEM_NONE":
                mon["item"] = {"id": items[m["item"]], "name": item_msg[items[m["item"]]]}
            if m.get("moves"):
                mon["moves"] = [{"id": moves[x], "name": move_msg[moves[x]]} for x in m["moves"]]
            if m["genderOverride"] != "TRPOKE_GENDER_OVERRIDE_OFF":
                mon["gender_override"] = m["genderOverride"]
            if m["abilityOverride"] != "TRPOKE_ABILITY_OVERRIDE_OFF":
                mon["ability_override"] = m["abilityOverride"]
            if m["capsule"]:
                mon["capsule"] = m["capsule"]
            party.append(mon)
        trainers[str(idx)] = {
            "const": trainer_consts[idx],
            "name": clean_name(t["name"]),
            "class_id": class_ids[t["class"]],
            "class": class_name(t["class"]),
            "role": role_of(t["class"]),
            "type": t["type"],
            "double": bool(t["double"]),
            "ai_flags": t["ai_flags"],
            "items": [{"id": items[i], "name": item_msg[items[i]]} for i in t["items"]],
            "party": party,
        }
    doc = {
        "_note": "GENERATED by tools/gen_gen4_trainers.py from pinned pret/pokeheartgold -- do not edit. Keys are trainer indexes (the wire trainer_id). No HG/SS split exists in the source.",
        "_schema": "gen4-hgss-trainers-v1",
        "source": base.provenance(clone, "tools/gen_gen4_trainers.py", INPUTS),
        "trainer_count": len(trainers),
        "version_split": False,
        "classes": classes,
        "trainers": trainers,
    }
    return {"trainers.json": base.dumps(doc, 3)}


def main() -> int:
    return base.cli(build, __doc__.splitlines()[0])


if __name__ == "__main__":
    sys.exit(main())
