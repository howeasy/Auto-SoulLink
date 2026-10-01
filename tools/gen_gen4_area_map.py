#!/usr/bin/env python3
"""gen_gen4_area_map.py -- HGSS area map + location table from pinned pret/pokeheartgold.

Writes (both from the same parse, one provenance block each):
  data/games/gen4_hgss/area_map.json   area_id -> display/maps, plus map_id -> area_id
  data/games/gen4_hgss/locations.json  map_id -> const/token/mapsec/region/type/area

Source (pokeheartgold @ the commit pinned in data/gen4_sources.lock.json, never a ROM text dump):
  include/constants/maps.h          MAP_* id and the MAP_<token> comment
  src/data/map_headers.h            .mapsec .regionNo .mapType .wildEncounterBank per map
  include/constants/map_sections.h  MAPSEC_* ids
  files/msgdata/msg/msg_0279.gmm    area names, indexed by mapsec (src/field/draw_map_name.c)
  include/constants/safari.h        the 12 Safari areas (D10: Safari counts per area)

Area rule: an area is a map section (mapsec) -- every map sharing a mapsec shares a Soul Link area
(Union Cave 1F/B1F/B2F, Elm's Lab inside New Bark Town, ...). The area_id is the slug of the English
name in msg 0279. D10 overrides: the Bug-Catching Contest map is its own area, and the Safari Zone
gets one sub-area per Safari area (the area a position falls in is chosen at runtime from the
player's coordinates and area set, so those sub-areas own no static map).

This module is also the shared helper layer for gen_gen4_{encounters,trainers,acquisition}.py.

Usage:
  python tools/gen_gen4_area_map.py            # write
  python tools/gen_gen4_area_map.py --check    # regenerate in memory, diff vs committed (exit 1 on drift)
Exit: 0 ok, 1 drift / wrong pret commit, 2 pret clone absent (OPEN, nothing written).
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen4_pins  # noqa: E402

PIN = gen4_pins.SOURCE_COMMITS["pokeheartgold_citation"]
OUT_DIR = REPO / "data" / "games" / "gen4_hgss"
ENV_CLONE = "SLINK_PRET_HGSS"


class PretAbsent(Exception):
    """The pinned pokeheartgold clone is not on this machine (exit 2 / test skip)."""


class PretMismatch(Exception):
    """The clone exists but is not the pinned, clean checkout (exit 1 / test FAIL)."""


# --------------------------------------------------------------------------- clone + provenance


def locate_clone(arg: str | None = None) -> Path:
    path = Path(arg or os.environ.get(ENV_CLONE) or gen4_pins.default_locations().sources["pokeheartgold_citation"])
    if not (path / "include" / "constants" / "maps.h").is_file():
        raise PretAbsent(f"pret/pokeheartgold clone not found at {path} (set {ENV_CLONE} or pass --pret)")
    return path


def _git(clone: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(clone), *args], capture_output=True, text=True, check=True).stdout.strip()


def verify_clone(clone: Path) -> None:
    try:
        head = _git(clone, "rev-parse", "HEAD")
        dirty = _git(clone, "status", "--porcelain", "--untracked-files=no")
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PretMismatch(f"cannot read git state of {clone}: {exc}") from exc
    if head != PIN:
        raise PretMismatch(f"pokeheartgold clone {clone} is at {head}, pinned {PIN}")
    if dirty:
        raise PretMismatch(f"pokeheartgold clone {clone} has tracked modifications; pin {PIN} requires a clean tree")


def provenance(clone: Path, generator: str, inputs: list[str]) -> dict:
    """Source identity for a generated file: pinned commit + sha256 of every input actually read."""
    return {
        "repo": "pret/pokeheartgold",
        "commit": PIN,
        "generator": generator,
        "inputs": {rel: hashlib.sha256((clone / rel).read_bytes()).hexdigest() for rel in sorted(inputs)},
    }


def dumps(obj, depth: int, level: int = 0) -> str:
    """Pretty-print the top `depth` container levels, compact below (keeps diffs and size sane)."""
    if depth <= 0 or not isinstance(obj, (dict, list)) or not obj or (isinstance(obj, list) and not any(isinstance(v, (dict, list)) for v in obj)):
        return json.dumps(obj, ensure_ascii=False)
    pad, end = "  " * (level + 1), "  " * level
    if isinstance(obj, dict):
        body = ",\n".join(f"{pad}{json.dumps(k, ensure_ascii=False)}: {dumps(v, depth - 1, level + 1)}" for k, v in obj.items())
        return "{\n" + body + "\n" + end + "}"
    return "[\n" + ",\n".join(pad + dumps(v, depth - 1, level + 1) for v in obj) + "\n" + end + "]"


def _shown(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:  # --out-dir outside the repo
        return str(path)


def finish(out: Path, text: str, check: bool) -> bool:
    """Write `text` (or, with check, diff it against the committed file). True when in sync."""
    text += "\n"
    if check:
        have = out.read_bytes().replace(b"\r\n", b"\n").decode("utf-8") if out.is_file() else None
        if have != text:
            print(f"DRIFT: {_shown(out)} differs from a fresh regeneration", file=sys.stderr)
            return False
        print(f"ok: {_shown(out)}")
        return True
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print(f"wrote {_shown(out)}")
    return True


def cli(build, description: str) -> int:
    """Shared entry point: build(clone) -> {Path: text}; handles --pret/--check/--out-dir/exit codes."""
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--pret", help=f"pokeheartgold clone (default ${ENV_CLONE} or the gen4_pins location)")
    ap.add_argument("--check", action="store_true", help="regenerate in memory and diff vs the committed JSON")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    args = ap.parse_args()
    try:
        clone = locate_clone(args.pret)
        verify_clone(clone)
        files = build(clone)
    except PretAbsent as exc:
        print(f"OPEN: {exc}", file=sys.stderr)
        return 2
    except PretMismatch as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    out_dir = Path(args.out_dir)
    if not files:  # an empty file set would make all([]) pass vacuously
        print("FAIL: the generator produced no files", file=sys.stderr)
        return 1
    results = [finish(out_dir / name, text, args.check) for name, text in files.items()]  # no short-circuit: report every file
    return 0 if all(results) else 1


# --------------------------------------------------------------------------- pret readers


def read(clone: Path, rel: str) -> str:
    return (clone / rel).read_text(encoding="utf-8")


def gmm(clone: Path, bank: int) -> dict[int, str]:
    """English rows of files/msgdata/msg/msg_<bank>.gmm as {index: text}."""
    text = read(clone, f"files/msgdata/msg/msg_{bank:04d}.gmm")
    rows = re.findall(r'<row id="[^"]*" index="(\d+)">.*?<language name="English">(.*?)</language>', text, re.S)
    return {int(i): html.unescape(s) for i, s in rows}


def defines(clone: Path, rel: str, prefix: str) -> dict[str, int]:
    return {n: int(v) for n, v in re.findall(rf"^#define ({prefix}\w+)\s+(\d+)\b", read(clone, rel), re.M)}


def slug(text: str) -> str:
    s = text.replace("’", "").replace("'", "")
    s = s.replace("é", "e")
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def titled(name: str) -> str:
    """msg names are upper-case (BULBASAUR, MR. MIME, HO-OH, FARFETCH'D): Capitalise each word/hyphen part;
    a letter after an apostrophe stays lower-case (Farfetch'd)."""
    return re.sub(r"[A-Za-z]+(?:['’][A-Za-z]+)*", lambda m: m.group(0)[0].upper() + m.group(0)[1:].lower(), name)


def _field(body: str, name: str) -> str:
    return re.search(r"\." + name + r"\s*=\s*(\w+)", body)[1]


class Maps:
    """Everything keyed by map: id, const, header token, mapsec, region, type, encounter bank."""

    def __init__(self, clone: Path):
        self.rows: dict[int, dict] = {}
        for const, mid, token in re.findall(r"^#define (MAP_\w+)\s+(\d+)\s*//\s*MAP_(\w+)", read(clone, "include/constants/maps.h"), re.M):
            self.rows[int(mid)] = {"const": const, "token": token}
        hdr = read(clone, "src/data/map_headers.h")
        blocks = re.split(r"\n    \[(MAP_\w+)\] = \{", hdr)
        by_const = {r["const"]: mid for mid, r in self.rows.items()}
        for i in range(1, len(blocks), 2):
            body = blocks[i + 1]
            row = self.rows[by_const[blocks[i]]]
            row["mapsec"] = _field(body, "mapsec")
            row["region"] = _field(body, "regionNo").removeprefix("MAP_REGION_")
            row["map_type"] = _field(body, "mapType").removeprefix("MAP_TYPE_")
            bank = _field(body, "wildEncounterBank").removeprefix("ENCDATA_")
            row["enc_bank"] = None if bank == "NA" else bank
        assert len(self.rows) == 540 and all("mapsec" in r for r in self.rows.values()), "map header parse drifted"
        assert len({r["token"] for r in self.rows.values()}) == 540, "map tokens are no longer unique"
        self.by_token = {r["token"]: mid for mid, r in self.rows.items()}


SAFARI_AREAS = ("PLAINS", "MEADOW", "SAVANNAH", "PEAK", "ROCKY_BEACH", "WETLAND", "FOREST", "SWAMP", "MARSHLAND", "WASTELAND", "MOUNTAIN", "DESERT")
BUG_CONTEST_MAP = "MAP_NATIONAL_PARK_BUG_CATCHING_CONTEST"
SAFARI_MAPSEC = "MAPSEC_SAFARI_ZONE"
SAFARI_RESOLUTION = "runtime: src/field/encounter_check.c FieldSystem_GenerateSafariEncounter picks the area from the player coordinates (ov02_0224E340) through the save's SafariZoneAreaSet; no static map owns it"


def build_model(clone: Path) -> dict:
    maps = Maps(clone)
    sec_ids = defines(clone, "include/constants/map_sections.h", "MAPSEC_")
    sec_name = gmm(clone, 279)
    safari_ids = defines(clone, "include/constants/safari.h", "SAFARI_ZONE_AREA_")
    assert [f"SAFARI_ZONE_AREA_{n}" for n in SAFARI_AREAS] == [k for k in safari_ids if k.startswith("SAFARI_ZONE_AREA_") and k[17:] in SAFARI_AREAS], "Safari area list drifted"

    areas: dict[str, dict] = {}
    map_area: dict[int, str | None] = {}
    unmapped: dict[int, str] = {}
    slug_owner: dict[str, str] = {}
    for mid, row in sorted(maps.rows.items()):
        sec = row["mapsec"]
        if sec == "MAPSEC_MYSTERY_ZONE":
            unmapped[mid] = "system map (mapsec 0)"
            continue
        if row["const"] == BUG_CONTEST_MAP:
            aid, disp, special = "bug_catching_contest", "Bug-Catching Contest", "bug_contest"
            sec_for_area = sec  # shares the National Park mapsec; the area split is ours (D10)
        else:
            disp = sec_name[sec_ids[sec]]
            aid = slug(disp)
            if slug_owner.setdefault(aid, sec) != sec:
                aid = f"{aid}_{sec_ids[sec]}"
            special = "safari" if sec == SAFARI_MAPSEC else None
            sec_for_area = sec
        area = areas.setdefault(aid, {"display": disp, "mapsec": sec_for_area, "region": row["region"], "special": special, "parent": None, "maps": []})
        area["maps"].append(mid)
        map_area[mid] = aid

    # An area whose maps are all *_UNUSED_* dummies is not a place the player can be.
    for aid in [a for a, v in areas.items() if all("UNUSED" in maps.rows[m]["const"] for m in v["maps"])]:
        for mid in areas.pop(aid)["maps"]:
            unmapped[mid] = f"unused-only map section ({aid})"
            map_area[mid] = None

    # `_UNUSED_` dummy maps stay in the maps->area table (map_area) but are not listed as a place in the area:
    # they live in the separate `unused_maps` field.
    for v in areas.values():
        v["unused_maps"] = [m for m in v["maps"] if "UNUSED" in maps.rows[m]["const"]]
        v["maps"] = [m for m in v["maps"] if m not in v["unused_maps"]]

    # D10: Safari sub-areas. They own no static map; the parent owns the 15 Safari maps.
    areas["safari_zone"]["safari_area_resolution"] = SAFARI_RESOLUTION
    for name in SAFARI_AREAS:
        areas[f"safari_{name.lower()}"] = {
            "display": f"Safari Zone ({titled(name.replace('_', ' '))})",
            "mapsec": None,
            "region": areas["safari_zone"]["region"],
            "special": "safari",
            "parent": "safari_zone",
            "safari_area_const": f"SAFARI_ZONE_AREA_{name}",
            "safari_area_id": safari_ids[f"SAFARI_ZONE_AREA_{name}"],
            "maps": [],
            "unused_maps": [],
        }
    return {"maps": maps, "areas": areas, "map_area": map_area, "unmapped": unmapped, "sec_ids": sec_ids, "sec_name": sec_name}


INPUTS = [
    "include/constants/maps.h",
    "src/data/map_headers.h",
    "include/constants/map_sections.h",
    "include/constants/safari.h",
    "files/msgdata/msg/msg_0279.gmm",
]


def build(clone: Path) -> dict[str, str]:
    m = build_model(clone)
    maps, areas = m["maps"], m["areas"]
    prov = provenance(clone, "tools/gen_gen4_area_map.py", INPUTS)
    note = "GENERATED by tools/gen_gen4_area_map.py from pinned pret/pokeheartgold -- do not edit."

    area_doc = {
        "_note": note + " areas: area_id -> display/maps (map ids). maps: map_id -> area_id (null = not a Soul Link place, see unmapped_maps).",
        "_schema": "gen4-hgss-area-map-v1",
        "source": prov,
        "rules": {
            "area": "one area per map section (mapsec); display = msg 0279[mapsec]",
            "bug_contest": f"{BUG_CONTEST_MAP} is its own area (D10); a kept bug is the catch, awarded at the result",
            "safari": "Safari Zone is one sub-area per Safari area (D10); area resolved at runtime, sub-areas own no static map",
        },
        "areas": {aid: areas[aid] for aid in sorted(areas)},
        "maps": {str(mid): m["map_area"].get(mid) for mid in sorted(maps.rows)},
        "unmapped_maps": {str(mid): why for mid, why in sorted(m["unmapped"].items())},
    }
    loc_doc = {
        "_note": note + " Per-map location facts (HUD/status page): the name shown in game is the mapsec name.",
        "_schema": "gen4-hgss-locations-v1",
        "source": prov,
        "locations": {
            str(mid): {
                "const": row["const"],
                "token": row["token"],
                "mapsec": row["mapsec"],
                "name": m["sec_name"][m["sec_ids"][row["mapsec"]]],
                "region": row["region"],
                "map_type": row["map_type"],
                "enc_bank": row["enc_bank"],
                "area": m["map_area"].get(mid),
            }
            for mid, row in sorted(maps.rows.items())
        },
    }
    return {"area_map.json": dumps(area_doc, 2), "locations.json": dumps(loc_doc, 2)}


def main() -> int:
    return cli(build, __doc__.splitlines()[0])


if __name__ == "__main__":
    sys.exit(main())
