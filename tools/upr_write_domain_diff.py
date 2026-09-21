"""tools/upr_write_domain_diff.py — the T6 write-domain audit (docs/purergb/PLAN.md §6 M5).

Diff a clean pure ROM against a randomized output and require every changed byte to lie
inside the allowlist derived from the INI entry for the categories that were enabled:

    wild         species+level bytes of every grass/water/rod table (never a rate byte)
    starters     the StarterOffsets1/2/3 sites
    statics      every Species/Level site of every StaticPokemon{} record
    trainers     level and species bytes inside party records (tags, moveset ids and
                 terminators are outside)
    tms          the 50 TM move bytes (+ the TM/HM compatibility bytes of each base-stat
                 record when tm_compat is enabled)
    field_items  item bytes of object_event item rows and of hidden-item rows whose give
                 routine is one of HiddenItemRoutineEntries

    python tools/upr_write_domain_diff.py --clean ROM --out ROM --title purered --enable wild [--enable ...]

Usable as a library too: ``allowlist(title, rom, categories)`` and ``audit(...)``.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
INI = REPO / "data" / "purergb" / "upr_pure_entries.ini"
SECTION = {"purered": "PureRed (U)", "pureblue": "PureBlue (U)", "puregreen": "PureGreen (U)",
           # the SLink companion-overlay builds: own header CRCs, bank 0/1/3 offsets shifted
           "purered_overlay": "PureRed overlay (U)", "pureblue_overlay": "PureBlue overlay (U)",
           "puregreen_overlay": "PureGreen overlay (U)"}


def entry_key(ident: dict) -> str:
    """The SECTION key for a scanner identity (server.adapters.gen1_rom_scan.identify): an
    overlay artifact is judged by the overlay entry -- the clean offsets would report the
    shifted starter sites and fishing tables as stray writes."""
    return ident["variant"] + ("_overlay" if ident.get("kind") == "overlay" else "")


def _int(v: str) -> int:
    v = v.strip()
    return int(v, 16) if v.lower().startswith("0x") else int(v)


def load_entry(title: str, ini: pathlib.Path = INI) -> dict:
    """The keys of one section: scalars as int, arrays as list[int], statics as a list of
    (species offsets, level offsets)."""
    text = ini.read_text(encoding="utf-8")
    m = re.search(r"^\[" + re.escape(SECTION[title]) + r"\]\n(.*?)(?=^\[|\Z)", text, re.S | re.M)
    if not m:
        raise SystemExit(f"no [{SECTION[title]}] in {ini}")
    entry: dict = {"statics": []}
    for line in m.group(1).splitlines():
        line = line.split("//", 1)[0].strip()
        if not line or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.endswith("{}"):
            sp = re.search(r"Species=\[([^\]]*)\]", v).group(1)
            lv = re.search(r"Level=\[([^\]]*)\]", v).group(1)
            entry["statics"].append(([_int(x) for x in sp.split(",")], [_int(x) for x in lv.split(",")]))
        elif v.startswith("["):
            body = v[1:-1].strip()
            entry[k] = [_int(x) for x in body.split(",")] if body and "=" not in body else body
        else:
            try:
                entry[k] = _int(v)
            except ValueError:
                entry[k] = v
    return entry


def _flat(bank: int, ptr: int) -> int:
    return ptr if bank == 0 else bank * 0x4000 + (ptr - 0x4000)


def _word(rom: bytes, o: int) -> int:
    return rom[o] | rom[o + 1] << 8


def wild_bytes(rom: bytes, e: dict) -> set[int]:
    out: set[int] = set()
    tbl = e["WildPokemonTableOffset"]
    bank = tbl // 0x4000
    seen = set()
    while _word(rom, tbl) != 0xFFFF:
        off = _flat(bank, _word(rom, tbl))
        if off not in seen:
            seen.add(off)
            for _ in range(2):
                rate = rom[off]
                off += 1
                if rate:
                    out.update(range(off, off + 20))
                    off += 20
        tbl += 2
    for o in e.get("OldRodOffsets", [e["OldRodOffset"]]):
        out.update((o + 1, o + 2))
    for t in [e["GoodRodOffset"]] + ([e["GoodRodMonsOcean"]] if "GoodRodMonsOcean" in e else []):
        out.update(range(t, t + 2 * e.get("GoodRodPairCount", 2)))
    sr = e["SuperRodTableOffset"]
    srbank = sr // 0x4000
    seen = set()
    while rom[sr] != 0xFF:
        set_off = _flat(srbank, _word(rom, sr + 1))
        sr += 3
        if set_off in seen:
            continue
        seen.add(set_off)
        n = rom[set_off]
        out.update(range(set_off + 1, set_off + 1 + 2 * n))
    return out


def trainer_bytes(rom: bytes, e: dict) -> set[int]:
    out: set[int] = set()
    tbl = e["TrainerDataTableOffset"]
    bank = tbl // 0x4000
    counts = e["TrainerDataClassCounts"]
    for cls in range(1, e.get("TrainerClassCount", 47) + 1):
        offs = _flat(bank, _word(rom, tbl + (cls - 1) * 2))
        for _ in range(counts[cls]):
            tag = rom[offs]
            offs += 1
            if tag in (0xFF, 0xFE, 0xFD):
                if tag == 0xFD:
                    offs += 1                      # custom-moveset id: outside
                while rom[offs] != 0:
                    out.update((offs, offs + 1))   # level|flags, species
                    offs += 2
            else:
                out.add(offs - 1)                  # the shared level byte
                while rom[offs] != 0:
                    out.add(offs)
                    offs += 1
            offs += 1                              # terminator: outside
    return out


def field_item_bytes(rom: bytes, e: dict) -> set[int]:
    out: set[int] = set()
    banks, ptrs = e["MapBanks"], e["MapAddresses"]
    for map_id in range(0, 0xF8):
        if map_id in (0xED, 0xFF):
            continue
        hdr = _flat(rom[banks + map_id], _word(rom, ptrs + map_id * 2))
        if hdr >= len(rom) - 16:
            continue
        ncons = bin(rom[hdr + 9] & 0xF).count("1")
        obj = _flat(rom[banks + map_id], _word(rom, hdr + 10 + ncons * 11))
        if obj >= len(rom) - 4:
            continue
        offs = obj + 2 + rom[obj + 1] * 4
        offs += 1 + rom[offs] * 3
        n = rom[offs]
        offs += 1
        for _ in range(n):
            tid = rom[offs + 5]
            if tid & 0x40:
                offs += 8
            elif tid & 0x80 and rom[offs + 6] != 0:
                out.add(offs + 6)
                offs += 7
            else:
                offs += 6
    routines = set(e.get("HiddenItemRoutineEntries", [e["HiddenItemRoutine"]]))
    lst, tbl = e["SpecialMapList"], e["SpecialMapPointerTable"]
    tbank = tbl // 0x4000
    idx = 0
    while rom[lst] != 0xFF:
        row = _flat(tbank, _word(rom, tbl + idx))
        while rom[row] != 0xFF:
            if _flat(rom[row + 3], _word(rom, row + 4)) in routines:
                out.add(row + 2)
            row += 6
        lst += 1
        idx += 2
    return out




# UPR's Gen 1 item pool, exactly as Gen1Constants.setupAllowedItems builds it (the fork keeps
# vanilla's list): ids 1..250 minus the banned singles (townMap 5, bicycle 6, ?????? 7,
# safariBall 8, pokedex 9, oldAmber 31, cardKey 48, ppUpGlitch 50, coin 59, ssTicket 63,
# goldTeeth 64), the banned ranges (badges 21+8, fossils/keys 41+5, coinCase 69+10, unused
# 84+112 = 84..195) and the HMs 196..200; TMs 201..250 are the TM pool. The writer only ever
# touches a pickup whose CURRENT item is in this pool (randomizeFieldItems/shuffleFieldItems
# test isAllowed on the existing item), so a site holding anything else -- a key item, an HM,
# but also pureRGB's own ids that vanilla banned (HYPER BALL 5, ... 8, 23, APEX CHIP 50, 59)
# -- is never a legal write target and the audit must not allow it (review cx-795d1423 #10,
# cx-758c671d #5). tests/unit/test_upr_pure_pipeline.py re-derives this from the fork source.
_UPR_BANNED = ({5, 6, 7, 8, 9, 31, 48, 50, 59, 63, 64} | set(range(21, 29)) | set(range(41, 46))
               | set(range(69, 79)) | set(range(84, 196)) | set(range(196, 201)))
UPR_GEN1_ALLOWED_ITEMS = frozenset(set(range(1, 251)) - _UPR_BANNED)


def _rewritable_items() -> set[int]:
    return set(UPR_GEN1_ALLOWED_ITEMS)


GUARANTEED_CATCH_PREFIX = bytes.fromhex("CF7EFE01")   # Gen1Constants.guaranteedCatchPrefix


def guaranteed_catch_byte(rom: bytes) -> int | None:
    """Catch-rate tier 5 also makes every ball a Master Ball: the fork turns the `jp z,
    .captured` after `cp MASTER_BALL` into `jp` (CA -> C3) at the byte after the prefix
    (Gen1RomHandler.enableGuaranteedPokemonCatching; 0xD1E9 in all six pure ROMs). That one
    code byte is part of the catch_rate write domain (review cx-758c671d #1)."""
    i = rom.find(GUARANTEED_CATCH_PREFIX)
    if i < 0 or rom.find(GUARANTEED_CATCH_PREFIX, i + 1) >= 0:
        return None                       # absent or ambiguous: nothing is allowed
    at = i + len(GUARANTEED_CATCH_PREFIX)
    return at if rom[at] == 0xCA else None


def catch_rate_bytes(e: dict) -> set[int]:
    """The catch-rate byte (+8) of the 151 dex records -- what a minimum catch-rate tier
    rewrites. pureRGB keeps Mew inline as record 150; the non-dex records are untouched."""
    size = e.get("BaseStatsEntrySize", 28)
    return {e["PokemonStatsOffset"] + i * size + 8 for i in range(151)}


DOMAINS = ("wild", "starters", "statics", "trainers", "tms", "tm_compat", "field_items", "catch_rate")


def domains_for_spec(spec: dict) -> set[str]:
    """The write domains a settings SPEC enables -- from every option, not just the six mode
    choices: a level curve with its parent mode unchanged still rewrites level bytes, a
    catch-rate tier rewrites base stats, TM sanity rewrites TM compatibility (#11)."""
    g = spec.get
    out: set[str] = set()
    if g("wild", "unchanged") != "unchanged" or g("wild_levels", 0):
        out.add("wild")
    if g("wild_min_catch_rate", 0):
        out.add("catch_rate")
    if g("starters", "unchanged") != "unchanged":
        out.add("starters")
    if g("statics", "unchanged") != "unchanged" or g("static_levels", 0):
        out.add("statics")
    if (g("trainers", "unchanged") != "unchanged" or g("trainers_levels", 0)
            or g("trainers_force_evolved", 0)):
        out.add("trainers")
    if g("tms", "unchanged") != "unchanged":
        out.add("tms")
    if g("tm_compat", "unchanged") != "unchanged" or g("tm_sanity", False):
        out.add("tm_compat")
    if g("field_items", "unchanged") != "unchanged":
        out.add("field_items")
    return out


def allowlist(title: str, rom: bytes, categories: set[str], ini: pathlib.Path = INI) -> set[int]:
    e = load_entry(title, ini)
    out: set[int] = set()
    if "catch_rate" in categories:
        out |= catch_rate_bytes(e)
        if (gc := guaranteed_catch_byte(rom)) is not None:
            out.add(gc)
    if "wild" in categories:
        out |= wild_bytes(rom, e)
    if "starters" in categories:
        for n in (1, 2, 3):
            out.update(e[f"StarterOffsets{n}"])
    if "statics" in categories:
        for sp, lv in e["statics"]:
            out.update(sp)
            out.update(lv)
    if "trainers" in categories:
        out |= trainer_bytes(rom, e)
    if "tms" in categories:
        out.update(range(e["TMMovesOffset"], e["TMMovesOffset"] + 50))
    if "tm_compat" in categories:
        size = e.get("BaseStatsEntrySize", 28)
        for i in range(151):
            base = e["PokemonStatsOffset"] + i * size
            out.update(range(base + 0x14, base + 0x14 + 7))
    if "field_items" in categories:
        legal = _rewritable_items()
        out |= {o for o in field_item_bytes(rom, e) if rom[o] in legal}
    return out


def audit(title: str, clean: bytes, out: bytes, categories: set[str], ini: pathlib.Path = INI) -> dict:
    allowed = allowlist(title, clean, categories, ini)
    changed = [i for i, (a, b) in enumerate(zip(clean, out, strict=True)) if a != b]
    stray = [i for i in changed if i not in allowed]
    return {"changed": len(changed), "allowed": len(allowed), "stray": stray}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="purered", choices=sorted(SECTION))
    ap.add_argument("--enable", action="append", default=[], choices=list(DOMAINS))
    ap.add_argument("--ini", default=str(INI))
    args = ap.parse_args()
    clean, out = pathlib.Path(args.clean).read_bytes(), pathlib.Path(args.out).read_bytes()
    if len(clean) != len(out):
        print(f"length differs: {len(clean)} vs {len(out)}")
        return 1
    r = audit(args.title, clean, out, set(args.enable), pathlib.Path(args.ini))
    print(f"enabled={sorted(args.enable)} changed={r['changed']} allowlist={r['allowed']} bytes "
          f"stray={len(r['stray'])}")
    for i in r["stray"][:40]:
        print(f"  OUTSIDE 0x{i:06X}: {clean[i]:02X} -> {out[i]:02X}")
    if len(r["stray"]) > 40:
        print(f"  ... {len(r['stray']) - 40} more")
    print("WRITE DOMAIN OK" if not r["stray"] else "WRITE DOMAIN VIOLATED")
    return 0 if not r["stray"] else 1


if __name__ == "__main__":
    sys.exit(main())
