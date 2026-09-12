#!/usr/bin/env python3
"""Gen 1 trainer classes: pin data/games/gen1_rby/trainers.json to pret.

Reads (per title: pokered for Red/Blue, pokeyellow for Yellow):
    constants/trainer_constants.asm   OPP_ID_OFFSET + the class const run ($00-$2F)
    data/trainers/names.asm           TrainerNames, `li "NAME"` in class order from $01
    data/trainers/parties.asm         one XxxData: block per class, one `db` line per party

Writes (default mode):
    data/games/gen1_rby/trainers.json  `classes` regenerated; `named_trainers` preserved

`--check` compares instead of writing and exits 1 with every difference printed:
  * class ids are OPP_ID_OFFSET (200) + const, contiguous, count == NUM_TRAINERS + 1
  * each display name is the names.asm text through `display_name` (see there)
  * every `named_trainers` party index <= that class's party count in EVERY title
  * per-class party counts == `TrainerDataClassCounts` in upr_layout.json for the title,
    so the pret source, the UPR pin and the shipped file are tied together.

The two decomps' constants and names are identical; only parties.asm differs by title.
"""
from __future__ import annotations

import json
import os
import re
import sys

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
_OUT = os.path.join(_REPO, "data", "games", "gen1_rby", "trainers.json")
_LAYOUT = os.path.join(_REPO, "data", "games", "gen1_rby", "upr_layout.json")
# UPR profile name -> pret decomp; Red and Blue share pokered (no _RED/_BLUE conditionals
# in any of the three files read here).
TITLES = {"red": "pokered", "blue": "pokered", "yellow": "pokeyellow"}

_LI_RE = re.compile(r'^\s*li\s+"([^"]*)"')
_CONST_RE = re.compile(r"^\s*trainer_const\s+(\w+)")
_OFFSET_RE = re.compile(r"^\s*DEF\s+OPP_ID_OFFSET\s+EQU\s+(\d+)")
_LABEL_RE = re.compile(r"^(\w+):")
_DB_RE = re.compile(r"^\s*db\s")

# Cartridge text -> the display spelling the Lua/JSON tables already use. Everything
# else is mechanical: strip the RIVAL1/2/3 digit, title-case, a space after "." and
# before a gender glyph. These two are wording choices, not casing: the cartridge says
# "FISHERMAN" and "ROCKET".
_DISPLAY_OVERRIDES = {"FISHERMAN": "Fisher", "ROCKET": "Rocket Grunt"}


def find_pret(name: str) -> str:
    """`.cache/pret/<name>`, searching upward: a worktree has no .cache of its own."""
    d = _REPO
    for _ in range(6):
        cand = os.path.join(d, ".cache", "pret", name)
        if os.path.isdir(cand):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.join(_REPO, ".cache", "pret", name)


def display_name(cart: str) -> str:
    """'JR.TRAINER♂' -> 'Jr. Trainer ♂', 'PROF.OAK' -> 'Prof. Oak', 'RIVAL2' -> 'Rival'."""
    if cart in _DISPLAY_OVERRIDES:
        return _DISPLAY_OVERRIDES[cart]
    s = re.sub(r"\d+$", "", cart).title()
    s = re.sub(r"\.(?=\S)", ". ", s)
    return re.sub(r"(?<=\S)([♂♀])", r" \1", s)


def parse_constants(path: str) -> tuple[int, list[str]]:
    """(OPP_ID_OFFSET, [const names in id order starting at $00])."""
    offset, consts = None, []
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = _OFFSET_RE.match(line)
            if m:
                offset = int(m.group(1))
            m = _CONST_RE.match(line)
            if m:
                consts.append(m.group(1))
    if offset is None or not consts:
        raise SystemExit(f"{path}: no OPP_ID_OFFSET / trainer_const lines")
    return offset, consts


def parse_names(path: str) -> list[str]:
    """TrainerNames text in class order; index 0 is class $01 (NOBODY has no entry)."""
    with open(path, encoding="utf-8") as f:
        return [m.group(1) for m in map(_LI_RE.match, f) if m]


def parse_party_counts(path: str) -> list[int]:
    """Parties per class, index = class const (0 for NOBODY). The TrainerDataPointers
    `dw` order IS the class order; each XxxData: block holds one `db` line per party."""
    order, blocks, label = [], {}, None
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.split(";", 1)[0]
            m = _LABEL_RE.match(line)
            if m:
                label = m.group(1)
                blocks[label] = 0
                continue
            if label == "TrainerDataPointers":
                m = re.match(r"^\s*dw\s+(\w+)", line)
                if m:
                    order.append(m.group(1))
            elif label and _DB_RE.match(line):
                blocks[label] += 1
    missing = [x for x in order if x not in blocks]
    if not order or missing:
        raise SystemExit(f"{path}: pointer table names blocks that do not exist: {missing}")
    return [0] + [blocks[x] for x in order]


def build_classes(pret_dir: str) -> dict[str, str]:
    offset, consts = parse_constants(os.path.join(pret_dir, "constants", "trainer_constants.asm"))
    names = parse_names(os.path.join(pret_dir, "data", "trainers", "names.asm"))
    if len(names) != len(consts) - 1:
        raise SystemExit(f"{pret_dir}: {len(consts)} consts but {len(names)} names")
    classes = {str(offset): "Nobody"}
    for i, cart in enumerate(names, start=1):
        classes[str(offset + i)] = display_name(cart)
    return classes


def check(shipped: dict, layout: dict, pret_dirs: dict[str, str] | None = None) -> list[str]:
    """Differences between the shipped trainers.json and pret (+ the UPR pin); [] when clean."""
    pret_dirs = pret_dirs or {t: find_pret(n) for t, n in TITLES.items()}
    diffs = []
    for title, pret_dir in pret_dirs.items():
        want = build_classes(pret_dir)
        got = shipped.get("classes", {})
        if len(got) != len(want):
            diffs.append(f"{title}: class count shipped={len(got)} pret={len(want)}")
        for cid in sorted(set(want) | set(got), key=int):
            if got.get(cid) != want.get(cid):
                diffs.append(f"{title}: class {cid}: shipped={got.get(cid)!r} pret={want.get(cid)!r}")
        offset = int(next(iter(want)))
        counts = parse_party_counts(os.path.join(pret_dir, "data", "trainers", "parties.asm"))
        pinned = layout["profiles"][title]["settings"]["TrainerDataClassCounts"]
        if counts != pinned:
            bad = [(i, c, p) for i, (c, p) in enumerate(zip(counts, pinned, strict=False)) if c != p]
            diffs.append(f"{title}: party counts pret != upr_layout TrainerDataClassCounts "
                         f"(len {len(counts)} vs {len(pinned)}); (class, pret, upr) = {bad}")
        for cid, names in shipped.get("named_trainers", {}).items():
            k = int(cid) - offset
            n = counts[k] if 0 <= k < len(counts) else 0
            for idx in names:
                if not 1 <= int(idx) <= n:
                    diffs.append(f"{title}: named_trainers[{cid}][{idx}] but class {cid} "
                                 f"({want.get(cid)}) has {n} parties in parties.asm")
    return diffs


def main() -> None:
    with open(_OUT, encoding="utf-8") as f:
        shipped = json.load(f)
    if "--check" in sys.argv:
        with open(_LAYOUT, encoding="utf-8") as f:
            layout = json.load(f)
        diffs = check(shipped, layout)
        for d in diffs:
            print(d)
        print(f"gen1 trainers.json vs pret+upr_layout: {len(diffs)} differences")
        sys.exit(1 if diffs else 0)
    shipped["classes"] = build_classes(find_pret("pokered"))
    with open(_OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(shipped, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"wrote {_OUT}")


if __name__ == "__main__":
    main()
