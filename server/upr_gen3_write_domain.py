"""The write-domain audit for Manager-randomized FireRed / LeafGreen and Emerald -- the Gen 3
counterpart of pureRGB's T6 (server/upr_pipeline.py `_audit_write_domain`,
tools/upr_write_domain_diff.py, docs/purergb/PLAN.md A5 / G5).

The standard: disabled settings write nothing; enabled settings write only inside their
allow-listed domains; 0 stray bytes. `_check_content_gen3` re-proves the engine sites, their
context windows, the checkpoint anchors and the species rules -- not what ELSE a setting wrote.
This module diffs the clean pinned ROM against the fork's output and requires every changed byte
to lie inside a domain of an ENABLED setting (or the fork's unconditional `baseline`).

The domains are FACTS, recorded separately in data/games/gen3_{frlg,emerald}/upr_write_domains.json
with a source per component. `build_model` regenerates those files from:
  * the pinned fork jar's own gen3_offsets.ini section and IPS code tweaks (read from the jar),
  * the clean ROM, walked exactly the way Gen3RomHandler walks it (the same locators, map-event
    scan, wild headers, trainer table, text-pointer search radius), and
  * the pret .sym (data/gen3/pret) for the free-space gap and the naming-only forbidden tables.
A ROM-backed test regenerates it and requires it to equal the committed file.

    python -m server.upr_gen3_write_domain --write      # regenerate the JSON (clean ROMs + jar)
"""
from __future__ import annotations

import bisect
import hashlib
import json
import re
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MODEL_PATH = REPO / "data" / "games" / "gen3_frlg" / "upr_write_domains.json"
EMERALD_MODEL_PATH = REPO / "data/games/gen3_emerald/upr_write_domains.json"
SYM_DIR = REPO / "data" / "gen3" / "pret"
DEFAULT_JAR = REPO / ".cache" / "slink-upr" / "PokeRandoZX.jar"
STAGED = {"firered": "patch/build/gen3_Pokemon_-_FireRed_Version_(USA).gba",
          "leafgreen": "patch/build/gen3_Pokemon_-_LeafGreen_Version_(USA).gba",
          "emerald": "patch/build/gen3_Pokemon_-_Emerald_Version_(USA,_Europe).gba"}
INI_SECTION = {"firered": "Fire Red (U) 1.0", "leafgreen": "Leaf Green (U) 1.0", "emerald": "Emerald (U)"}
SYM_FILE = {"firered": "pokefirered.sym", "leafgreen": "pokeleafgreen.sym", "emerald": "pokeemerald.sym"}
SCHEMA = "slink-upr-gen3-write-domains-v1"

# ── which domains a settings SPEC enables (upr_settings.options_for(FAMILY_FRLG) keys) ──────
# Options that only steer a pool or a sub-choice of another option write nothing of their own;
# every other allowed option enables at least one domain (test_upr_gen3_write_domain checks the
# partition is exhaustive, so a new option cannot slip in unmodelled).
NO_WRITE_OPTIONS = (
    "wild_restriction", "wild_block_legendaries", "wild_held_items_ban_bad",
    "trainers_similar_strength", "trainers_block_legendaries", "trainers_match_typing",
    "trainer_items_consumable", "trainer_items_sensible", "trainer_items_highest_only",
    "tm_keep_field", "tutor_keep_field", "field_items_ban_bad",
    "trades_items", "trades_ivs", "trades_nicknames", "trades_ots",
    "shops_ban_bad", "shops_ban_regular", "shops_ban_op", "shops_evolution_items",
    "pickup_ban_bad", "ban_lucky_egg")
# The rule-bearing tables the FR/LG family forbids (upr_settings.forbidden_enabled). Never
# enabled by a spec: they exist so a stray byte is NAMED ("types", "evolutions", ...).
FORBIDDEN_DOMAINS = ("base_stats", "types", "abilities", "exp_curves", "evolutions", "movesets",
                     "egg_moves", "move_data", "type_chart")
EMERALD_FACILITIES = {
    "frontier": ("Frontier", "BattleTower", "BattleFactory", "BattleArena", "BattleDome", "BattlePalace", "BattlePike"),
    "pyramid": ("Pyramid",), "trainer_hill": ("TrainerHill",),
    "contests": ("Contest",), "secret_bases": ("SecretBase",),
}


def domains_for_spec(spec: dict) -> set[str]:
    """The write domains an FR/LG spec enables (Randomizer.randomize's own conditions)."""
    g = spec.get
    on = {"baseline"}

    def changed(k):
        return g(k, "unchanged") != "unchanged"
    if changed("wild") or g("wild_levels", 0):
        on |= {"wild", "obedience_evo_code"}        # setEncounters -> attemptObedienceEvolutionPatches
    if g("wild_held_items"):
        on.add("wild_held_items")
    if g("wild_min_catch_rate", 0):                  # randomizeCatchRates: tier 5 ONLY patches the
        on.add("guaranteed_catch" if g("wild_min_catch_rate") == 5 else "catch_rate")   # ball odds
    if changed("starters"):
        on |= {"starters", "obedience_evo_code"}
    if changed("statics") or g("static_levels", 0):
        on |= {"statics", "obedience_evo_code"}
    if (changed("trainers") or g("trainers_levels", 0) or g("trainers_force_evolved", 0)
            or (g("trainers_rival_starter") and (changed("trainers") or changed("starters")))
            or g("trainer_items_boss") or g("trainer_items_important") or g("trainer_items_regular")):
        on.add("trainer_parties")
    if g("trainer_names"):
        on.add("trainer_names")
    if g("trainer_class_names"):
        on.add("trainer_class_names")
    if changed("tms"):
        on |= {"tms", "free_space"}
    if changed("tm_compat") or g("tm_sanity"):
        on.add("tm_compat")
    if changed("tutors"):
        on.add("tutors")
        if changed("tms"):
            # setMoveTutorMoves writes its texts only for sites preprocessMaps located, and the
            # maps are first walked by setTMMoves (Randomizer: TMs, then tutors, then the rest)
            on.add("tutor_text")
    if changed("tutor_compat") or g("tutor_sanity"):
        on.add("tutor_compat")
    if changed("trades"):
        on.add("trades")
    if changed("field_items"):
        on.add("field_items")
    if changed("shops"):
        on.add("shops")
        if g("shops") == "random" and g("shops_balance_prices"):
            on.add("item_prices")                    # randomizeShopItems -> setShopPrices
    if g("pickup") == "random":
        on.add("pickup")
    for key in ("fastest_text", "pc_potion", "running_shoes_indoors", "run_without_shoes",
                "catching_tutorial", "national_dex"):
        if g(key):
            on.add(key)
    if g("national_dex"):
        on.add("free_space")
    if g("lowercase_names"):
        on.add("species_names")
    if g("balance_static_levels"):
        on.add("fossil_levels")
    return on


# ── the audit (runtime: needs only the JSON) ─────────────────────────────────────────────
def _ranges(components: list[dict]) -> list[tuple[int, int]]:
    out = []
    for comp in components:
        for r in comp["ranges"].split():
            start, length = r.split("+")
            s = int(start, 16)
            out.append((s, s + int(length)))
    return out


def _merge(spans) -> tuple[list[int], list[int]]:
    starts, ends = [], []
    for s, e in sorted(spans):
        if ends and s <= ends[-1]:
            ends[-1] = max(ends[-1], e)
        else:
            starts.append(s)
            ends.append(e)
    return starts, ends


def _inside(merged, off: int) -> bool:
    starts, ends = merged
    i = bisect.bisect_right(starts, off) - 1
    return i >= 0 and off < ends[i]


def load_model(path: Path | None = None, *, title: str | None = None) -> dict:
    default = EMERALD_MODEL_PATH if title == "emerald" else MODEL_PATH
    return json.loads(Path(path or default).read_text(encoding="utf-8"))


def changed_offsets(clean: bytes, out: bytes, chunk: int = 4096) -> list[int]:
    if len(clean) != len(out):
        raise ValueError(f"length differs: {len(clean)} vs {len(out)}")
    changed = []
    for base in range(0, len(clean), chunk):
        a, b = clean[base:base + chunk], out[base:base + chunk]
        if a != b:
            changed.extend(base + i for i, (x, y) in enumerate(zip(a, b, strict=True)) if x != y)
    return changed


# RomFunctions.freeSpaceFinder returns (first run of amount+5 0xFF at/after FreeSpace + 5) & ~3,
# and every text the fork allocates ends in its 0xFF terminator, so each allocation starts 2..5
# bytes past the previous one's terminator (the first one at FreeSpace + 4). Between two changed
# bytes of the packed region there are therefore at most 5 unchanged bytes.
PACKED_MAX_GAP = 5


def _packed_end(changed: list[int], start: int, end: int) -> int:
    """End of the run of `changed` bytes packed from `start` (gaps of <= PACKED_MAX_GAP)."""
    pos = start
    for c in changed[bisect.bisect_left(changed, start):bisect.bisect_left(changed, end)]:
        if c - pos > PACKED_MAX_GAP:
            break
        pos = c + 1
    return pos


def audit(title: str, clean: bytes, out: bytes, enabled: set[str], model: dict | None = None) -> dict:
    """Every changed byte must lie in a domain of `enabled`. A `packed` component (free space)
    admits only the changes packed from its start the way freeSpaceFinder allocates. A stray
    byte is NAMED by every domain of the model that holds it (a disabled allowed setting, a
    forbidden table, or '<domain> (not packed ...)'), or 'unattributed'."""
    model = model or load_model(title=title)
    entry = model["titles"][title]
    if hashlib.sha1(clean).hexdigest() != entry["clean_sha1"]:
        raise ValueError(f"the clean {title} ROM is not the pinned dump ({entry['clean_sha1']})")
    domains = entry["domains"]
    unknown = set(enabled) - set(domains)
    if unknown:
        raise ValueError(f"unknown write domain(s): {sorted(unknown)}")
    forbidden = set(enabled) & set(model.get("forbidden_domains", ()))
    if forbidden:
        raise ValueError(f"forbidden write domain(s) cannot be enabled: {sorted(forbidden)}")
    changed = changed_offsets(clean, out)
    comps = [(d, c) for d in enabled for c in domains[d]]
    fixed = _merge(s for _d, c in comps if not c.get("packed") for s in _ranges([c]))
    loose = [i for i in changed if not _inside(fixed, i)]    # what the packed regions must explain
    spans, unpacked = list(zip(*fixed, strict=True)), {}
    for d, c in comps:
        if c.get("packed"):
            for s, e in _ranges([c]):
                p = _packed_end(loose, s, e)
                spans.append((s, p))
                unpacked[f"{d} (not packed from 0x{s:06X})"] = [(p, e)]
    allowed = _merge(spans)
    stray = [i for i in loose if not _inside(allowed, i)]
    named: dict[str, int] = {}
    if stray:
        each = {d: _merge(_ranges(c)) for d, c in domains.items() if d not in enabled}
        each.update((k, _merge(v)) for k, v in unpacked.items())
        for i in stray:
            hit = [d for d, m in each.items() if _inside(m, i)] or ["unattributed"]
            for d in hit:
                named[d] = named.get(d, 0) + 1
    return {"changed": len(changed), "stray": stray, "named": named,
            "enabled": sorted(enabled)}


def check_output(source_rom: str, output_rom: str, spec: dict, jar: str | None = None) -> dict:
    """The pipeline's one call (Gen 3 branch of prepare_pair): refuse the output if the fork
    wrote a byte outside the domains its spec enables, or if `jar` (the jar that made it;
    default: find_upr_jar()) is not the jar the model was built from."""
    from server.upr_pipeline import UprPipelineError, find_upr_jar, gen3_title, jar_sha256
    try:
        clean, out = Path(source_rom).read_bytes(), Path(output_rom).read_bytes()
        title = gen3_title(clean)
        model = load_model(title=title)
        if title not in model["titles"]:
            raise ValueError(f"it covers only {sorted(model['titles'])} (1.0, USA), and {source_rom} "
                             f"is not one of them")
        jar = jar or find_upr_jar()
        digest = jar_sha256(jar) if jar else None
        if digest != model["jar_sha256"]:
            command = "python -m server.upr_gen3_write_domain --write" + (" --title emerald" if title == "emerald" else "")
            raise ValueError(f"the randomizer jar {jar} (sha256 {digest}) is not the jar the write "
                             f"domains were modelled from ({model['jar_sha256']}); regenerate "
                             f"with `{command}`")
        r = audit(title, clean, out, domains_for_spec(spec), model)
    except (OSError, ValueError, KeyError) as exc:
        raise UprPipelineError(f"write-domain audit could not run: {exc}") from exc
    if r["stray"]:
        shown = ", ".join(f"0x{i:06X}" for i in r["stray"][:8])
        names = ", ".join(f"{d} ({n})" for d, n in sorted(r["named"].items()))
        raise UprPipelineError(
            f"the randomizer wrote {len(r['stray'])} byte(s) outside the write domain of "
            f"{r['enabled']} -- they fall in: {names} (first: {shown}); the output is refused")
    return {"changed": r["changed"], "domains": r["enabled"]}


# ── the model builder (facts: fork INI + IPS, clean ROM walked like Gen3RomHandler, .sym) ──
ROM_BASE = 0x08000000
H = "Gen3RomHandler"                                   # provenance shorthand
# Gen3Constants (fork src/com/dabomstew/pkrandom/constants/Gen3Constants.java)
WILD_PTR_PREFIX = "0348048009E00000FFFF0000"
MAP_BANKS_PTR_PREFIX = "80180068890B091808687047"
POKEDEX_ORDER_PREFIX = "0448814208D0481C0004000C05E00000"
DEOXYS_OBEY = "CD21490088420FD0"
MEW_OBEY_FROM_DEOXYS = 0x16
LEVEL_EVO_KANTO_CHECK = "972814DD"
STONE_EVO_KANTO_CHECK = "972808D9"
PERFECT_ODDS = "FE2E2FD90020"
RUNNING_SHOES_PREFIX_FRLG = "02200540002D29D0"
NATDEX_SCRIPT_ID = "292908258101"
NATDEX_FLAG_CHECKER = "260D809301210D800100"
OAKS_LAB_CHECK = "257D011604800000260D80D400"
OAK_HOUSE_CHECK = "1604800000260D80D4001908800580190980068083000880830109802109803C"
OAK_AIDE_PREFIX = "00B5064800880028"
PTR_SEARCH_RADIUS = 500
TM_ITEM_OFFSET = 289                                   # Gen3Items.tm01
ITEM_DESC_FIELD = 0x14
BASE_STATS_SIZE = 28
SLOTS = (12, 5, 5, 10)                                 # grass, surf, rock smash, fishing
SPECIES_DEOXYS_DEX = 386
STARTER_SITE_OFFSETS = (0, 5, 515, 520, 461, 466)      # frlgStarter{2,3}Offset + RepeatOffset
# Gen3Constants.setupAllowedItems: ItemList(Gen3Items.oldSeaMap = 376) minus machBike+30,
# oaksParcel+28, the unknown ranges/singles and hm01+8; tm01+50 are the TMs (isTM). setFieldTMs
# rewrites a site whose CURRENT item isTM, setRegularFieldItems one that isAllowed && !isTM;
# any other site (a key item, an HM) is never written (the Gen 1 audit's field_items rule).
FIELD_TMS = frozenset(range(TM_ITEM_OFFSET, TM_ITEM_OFFSET + 50))
FIELD_REGULAR = frozenset(range(1, 377)) - FIELD_TMS - (
    set(range(259, 289)) | set(range(349, 377)) | set(range(52, 63)) | set(range(87, 93))
    | set(range(99, 103)) | set(range(112, 121)) | set(range(176, 179)) | set(range(226, 254))
    | {347, 348, 72, 82, 105, 267} | set(range(339, 347)))


def _int(v: str) -> int:
    v = v.strip()
    return int(v, 16) if v.lower().startswith("0x") else int(v)


def parse_ini(text: str) -> dict[str, dict]:
    """gen3_offsets.ini the way Gen3RomHandler.loadROMInfo reads it (the subset FR/LG uses)."""
    roms: dict[str, dict] = {}
    cur = None
    for raw in text.splitlines():
        q = raw.split("//", 1)[0].strip()
        if not q:
            continue
        if q.startswith("[") and q.endswith("]"):
            cur = roms[q[1:-1]] = {"values": {}, "arrays": {}, "strings": {}, "tweaks": {},
                                   "statics": [], "roamers": [], "tmmt": []}
            continue
        k, v = (s.strip() for s in q.split("=", 1))
        if k in ("StaticPokemon{}", "RoamingPokemon{}"):
            sp = re.search(r"Species=\[([^\]]*)\]", v).group(1)
            lv = re.search(r"Level=\[([^\]]*)\]", v)
            rec = ([_int(x) for x in sp.split(",")],
                   [_int(x) for x in lv.group(1).split(",")] if lv and lv.group(1).strip() else [])
            cur["statics" if k.startswith("Static") else "roamers"].append(rec)
        elif k in ("TMText[]", "MoveTutorText[]"):
            p = v[1:-1].split(",", 5)
            cur["tmmt"].append({"number": _int(p[0]), "bank": _int(p[1]), "map": _int(p[2]),
                                "person": _int(p[3]), "offset": _int(p[4]),
                                "tutor": k == "MoveTutorText[]"})
        elif k == "CopyFrom":
            other = roms[v]
            for part in ("arrays", "values", "strings"):
                cur[part].update(other[part])
            if cur["values"].get("CopyTMText") == 1:
                cur["tmmt"].extend(other["tmmt"])
        elif k.endswith("Tweak"):
            cur["tweaks"][k] = v
        elif k.endswith("Locator") or k.endswith("Prefix"):
            cur["strings"][k] = v
        elif k in ("Game", "Type", "TableFile", "CRC32"):
            cur["values"][k] = v
        elif v.startswith("[") and v.endswith("]"):
            body = v[1:-1].strip()
            cur["arrays"][k] = [_int(x) for x in body.split(",")] if body else []
        else:
            cur["values"][k] = _int(v)
    return roms


def ips_ranges(patch: bytes) -> list[tuple[int, int]]:
    """The byte ranges an IPS patch writes (FileFunctions.applyPatch's record walk)."""
    assert patch[:5] == b"PATCH", "not an IPS file"
    out, o = [], 5
    while o + 2 < len(patch):
        off = int.from_bytes(patch[o:o + 3], "big")
        if off == 0x454F46:
            return out
        size = int.from_bytes(patch[o + 3:o + 5], "big")
        o += 5
        if size == 0:
            size = int.from_bytes(patch[o:o + 2], "big")
            o += 3
        else:
            o += size
        out.append((off, off + size))
    return out


class _Rom:
    def __init__(self, data: bytes):
        self.b = data

    def u16(self, o): return self.b[o] | self.b[o + 1] << 8
    def u32(self, o): return int.from_bytes(self.b[o:o + 4], "little")
    def ptr(self, o): return self.u32(o) - ROM_BASE

    def ok(self, p): return 0 <= p < len(self.b)

    def find_all(self, hexstr: str, lo: int = 0, hi: int | None = None) -> list[int]:
        """RomFunctions.search: non-overlapping hits whose needle ends before `hi`."""
        needle, hi = bytes.fromhex(hexstr), len(self.b) if hi is None else hi
        hits, i = [], self.b.find(needle, lo, hi)
        while i >= 0:
            hits.append(i)
            i = self.b.find(needle, i + len(needle), hi)
        return hits

    def find(self, hexstr: str) -> int:
        """Gen3RomHandler.find: the unique hit, -1 absent, -2 ambiguous."""
        hits = self.find_all(hexstr)
        return hits[0] if len(hits) == 1 else (-1 if not hits else -2)

    def strlen(self, o):                                 # lengthOfStringAt
        return self.b.index(0xFF, o) - o


def _map_scan(rom: _Rom, entry: dict) -> tuple[list[int], list[dict]]:
    """preprocessMaps: item-ball script item words, hidden-item words, and the TM / tutor text
    pointer sites (each tmmt record gains `actual`)."""
    headers = rom.ptr(rom.find_all(MAP_BANKS_PTR_PREFIX)[0] + 12)
    banks = []                                          # determineMapBankSizes
    off = headers
    while True:
        if any(headers < mb <= off for mb in banks):
            break
        p = rom.ptr(off)
        if not rom.ok(p):
            break
        banks.append(p)
        off += 4
    counts = []
    for base in banks:
        n, off = 0, base
        while True:
            if any(base < mb <= off for mb in banks) or (base < headers <= off):
                break
            if not rom.ok(rom.ptr(off)):
                break
            n, off = n + 1, off + 4
        counts.append(n)
    items, tmmt = [], [dict(t) for t in entry["tmmt"]]
    ball = entry["values"]["ItemBallPic"]
    for bank, count in enumerate(counts):
        bank_off = rom.ptr(headers + bank * 4)
        for m in range(count):
            mh = rom.ptr(bank_off + m * 4)
            ev = rom.ptr(mh + 4)
            if not rom.ok(ev):
                continue
            pcount, spcount = rom.b[ev], rom.b[ev + 3]
            if pcount:
                people = rom.ptr(ev + 4)
                for p in range(pcount):
                    rec = people + p * 24
                    if rom.b[rec + 1] == ball and rom.ptr(rec + 16) >= 0:
                        s = rom.ptr(rec + 16)
                        b = rom.b
                        if (b[s] == 0x1A and b[s + 1] == 0 and b[s + 2] == 0x80 and b[s + 5] == 0x1A
                                and b[s + 6] == 1 and b[s + 7] == 0x80 and b[s + 10] == 9
                                and b[s + 11] in (0, 1)):
                            items.append(s + 3)
                for t in tmmt:
                    if (t["bank"], t["map"]) != (bank, m):
                        continue
                    s = rom.ptr(people + (t["person"] - 1) * 24 + 16)
                    if s < 0:
                        continue
                    if entry["values"]["Type"] == "FRLG" and t["tutor"] and (t["number"] == 5 or 8 <= t["number"] <= 11):
                        s = rom.ptr(s + 1)
                    elif entry["values"]["Type"] == "FRLG" and t["tutor"] and t["number"] == 7:
                        s = rom.ptr(s + 0x1F)
                    look = s + t["offset"]
                    if 0 <= look < len(rom.b) - 2 and rom.b[look + 3] in (8, 9):
                        t["actual"] = look
            if spcount:
                signs = rom.ptr(ev + 16)
                for sp in range(spcount):
                    rec = signs + sp * 12
                    if 5 <= rom.b[rec + 5] <= 7 and rom.u16(rec + 8) != 0:
                        items.append(rec + 8)
    return items, tmmt


def _text_sites(rom: _Rom, tmmt: list[dict], tutor: bool) -> list[tuple[int, int]]:
    """The pointer copies setTMMoves / setMoveTutorMoves repoint: every hit of the site's 4-byte
    pointer within Gen3Constants.pointerSearchRadius of it."""
    out = []
    for t in tmmt:
        if t["tutor"] != tutor or "actual" not in t:
            continue
        a = t["actual"]
        needle = rom.b[a:a + 4].hex()
        for hit in rom.find_all(needle, max(0, a - PTR_SEARCH_RADIUS), min(len(rom.b), a + PTR_SEARCH_RADIUS)):
            out.append((hit, hit + 4))
    return out


def _syms(title: str) -> list[tuple[int, int, str]]:
    out = []
    for line in (SYM_DIR / SYM_FILE[title]).read_text(encoding="utf-8").splitlines():
        a, _k, size, name = line.split()[:4]
        a = int(a, 16)
        if ROM_BASE <= a < ROM_BASE + 0x2000000:
            out.append((a - ROM_BASE, int(size, 16), name))
    return sorted(out)


def _comp(what: str, source: str, spans, **extra) -> dict:
    starts, ends = _merge(spans)
    return {"what": what, "source": source,
            "ranges": " ".join(f"0x{s:06X}+{e - s}" for s, e in zip(starts, ends, strict=True)), **extra}


def build_title(title: str, clean: bytes, ini: dict, ips: dict[str, bytes]) -> dict:
    rom = _Rom(clean)
    emerald = title == "emerald"
    e = ini[INI_SECTION[title]]
    V, A = e["values"], e["arrays"]
    ini_src = f"gen3_offsets.ini [{INI_SECTION[title]}]"
    count = V["PokemonCount"]
    stats = rom.ptr(0x1BC)                               # efrlgPokemonStatsPointer
    names = rom.ptr(0x144)                               # efrlgPokemonNamesPointer
    item_data = rom.ptr(0x1C8)                           # efrlgItemDataPointer
    move_data = rom.ptr(0x1CC)                           # efrlgMoveDataPointer
    records = [stats + i * BASE_STATS_SIZE for i in range(1, count + 1)]

    def field(lo, hi):
        return [(r + lo, r + hi) for r in records]
    pd = rom.ptr(rom.find_all(POKEDEX_ORDER_PREFIX)[1] + 16)
    deoxys = next(i for i in range(1, count + 1) if rom.u16(pd + (i - 1) * 2) == SPECIES_DEOXYS_DEX)

    def tweak(name):
        return ips_ranges(ips[e["tweaks"][name]])
    items, tmmt = _map_scan(rom, e)
    D: dict[str, list[dict]] = {}

    def site(off, n):
        return [(off, off + n)]

    def found(hexstr, n, delta=0, multiple=False):
        hits = rom.find_all(hexstr) if multiple else [rom.find(hexstr)]
        return [(h + delta, h + delta + n) for h in hits if h > 0]

    D["baseline"] = ([
        _comp("intro Pokemon species words (randomizeIntroPokemon, unconditional)",
              f"{ini_src} IntroCryOffset/IntroSpriteOffset; {H}.randomizeIntroPokemon (Emerald)",
              site(V["IntroCryOffset"], 2) + site(V["IntroSpriteOffset"], 2)),
        _comp("first-battle IPS (getStaticPokemon applies it on every clean run)",
              f"jar {e['tweaks']['StaticFirstBattleTweak']}.ips; {H}.getStaticPokemon", tweak("StaticFirstBattleTweak")),
        _comp("roamer code/constant rewrite (getRoamers applies it on every clean run)",
              f"{ini_src} CreateInitialRoamerMonFunctionStartOffset; {H}.applyEmeraldRoamerPatch:2559-2586",
              [(V["CreateInitialRoamerMonFunctionStartOffset"] + lo, V["CreateInitialRoamerMonFunctionStartOffset"] + hi)
               for lo, hi in ((8, 12), (14, 15), (28, 32), (48, 52))]),
    ] if emerald else [
        _comp("intro Pokemon cry/sprite operands (randomizeIntroPokemon, unconditional)",
              f"{ini_src} IntroCryOffset/IntroOtherOffset/IntroSpriteOffset; {H}.randomizeIntroPokemon",
              site(V["IntroCryOffset"], 1) + site(V["IntroOtherOffset"], 1) + site(V["IntroSpriteOffset"], 8)),
        _comp("Ghost Marowak IPS (getStaticPokemon applies it on every run)",
              f"jar {e['tweaks']['GhostMarowakTweak']}.ips; {H}.getStaticPokemon", tweak("GhostMarowakTweak")),
        _comp("roamer IPS (getRoamers applies it on every run)",
              f"jar {e['tweaks']['RoamingPokemonTweak']}.ips; {H}.getRoamers", tweak("RoamingPokemonTweak")),
    ]) + [
        _comp("ability 2 := ability 1 where ability 2 is 0 (saveBasicPokeStats, every record)",
              f"{H}.saveBasicPokeStats bsAbility2Offset=23",
              [(r + 23, r + 24) for r in records if clean[r + 23] == 0], id="ability2_normalisation"),
        _comp("Deoxys record stats := the hardcoded forme stats (load/savePokemonStats)",
              f"{ini_src} DeoxysStatPrefix; {H}.loadPokemonStats/savePokemonStats", site(stats + deoxys * BASE_STATS_SIZE, 6),
              id="deoxys_stats"),
    ]
    wild = []
    start = rom.ptr(rom.find_all(WILD_PTR_PREFIX)[0] + 12)
    o = start
    while not (clean[o] == 0xFF and clean[o + 1] == 0xFF):
        for k, n in enumerate(SLOTS):
            p = rom.ptr(o + 4 + 4 * k)
            if rom.ok(p) and clean[p] != 0:
                d = rom.ptr(p + 4)
                # an allowlist builder fails closed: a slot pointer off the ROM means the walk left the table
                assert rom.ok(d) and d + 4 * n <= len(clean), f"wild header {o:#x} slot {k} points off the ROM"
                wild.append((d, d + 4 * n))
        o += 20
    D["wild"] = [_comp("encounter slots (level, level, species) of every wild table",
                       f"{H}.setEncounters/writeWildArea via Gen3Constants.wildPokemonPointerPrefix", wild)]
    evo = [] if emerald else found(LEVEL_EVO_KANTO_CHECK, 4) + found(STONE_EVO_KANTO_CHECK, 4)
    obey = rom.find(DEOXYS_OBEY)
    if obey > 0:
        evo += site(obey, 4)
        if rom.u16(obey + MEW_OBEY_FROM_DEOXYS) == (0x28 << 8) | 151:
            evo += site(obey + MEW_OBEY_FROM_DEOXYS, 2)
    D["obedience_evo_code"] = [_comp(
        "Deoxys/Mew obedience (CODE)" if emerald else "Deoxys/Mew obedience + Kanto-dex level/stone evolution checks (CODE)",
        f"{H}.attemptObedienceEvolutionPatches (called by setStarters/setEncounters/setStaticPokemon)", evo)]
    D["wild_held_items"] = [_comp("common/rare held item words of every base-stats record",
                                  f"{H}.saveBasicPokeStats bsCommonHeldItemOffset=12/bsRareHeldItemOffset=14",
                                  field(12, 16))]
    D["catch_rate"] = [_comp("catch rate of every base-stats record", f"{H}.saveBasicPokeStats bsCatchRateOffset=8",
                             field(8, 9))]
    D["guaranteed_catch"] = [_comp("Cmd_handleballthrow odds branch nop (CODE)",
                                   f"{H}.enableGuaranteedPokemonCatching perfectOddsBranchLocator",
                                   found(PERFECT_ODDS, 4))]
    sp = V["StarterPokemon"]
    starter_text = []
    for dex in (() if emerald else (1, 4, 7)):           # frlgBaseStarter1..3
        name = clean[names + dex * 11: clean.index(0xFF, names + dex * 11)]
        hit = clean.find(name)
        if hit >= 0:
            starter_text.append((hit, hit + rom.strlen(hit) + 1))
    D["starters"] = ([_comp("three contiguous starter species words", f"{ini_src} StarterPokemon; {H}.setStarters (RSE)",
                            site(sp, 6))] if emerald else [
        _comp("the six starter species words", f"{ini_src} StarterPokemon; {H}.setStarters",
              [(sp + d, sp + d + 2) for d in STARTER_SITE_OFFSETS]),
        _comp("Oak's three starter descriptions (rewritten in place)", f"{H}.writeFRLGStarterText", starter_text)])
    statics = [(s, s + 2) for rec in e["statics"] for s in rec[0]] + [(lv, lv + 1) for rec in e["statics"] for lv in rec[1]]
    roam = [(s, s + 2) for rec in e["roamers"] for s in rec[0]] + [(lv, lv + 1) for rec in e["roamers"] for lv in rec[1]]
    hardcoded = (_comp("first-battle species word and level byte", f"{ini_src} StaticFirstBattleSpeciesOffset/LevelOffset; {H}.setStaticPokemon",
                      site(V["StaticFirstBattleSpeciesOffset"], 2) + site(V["StaticFirstBattleLevelOffset"], 1)) if emerald else
                 _comp("Ghost Marowak species/level/gender", f"{ini_src} GhostMarowak*; {H}.setStaticPokemon",
                       [(s, s + 2) for s in A["GhostMarowakSpeciesOffsets"]]
                       + [(lv, lv + 1) for lv in A["GhostMarowakLevelOffsets"]] + site(V["GhostMarowakGenderOffset"], 1)))
    D["statics"] = [
        _comp("StaticPokemon{} species words and level bytes", f"{ini_src} StaticPokemon{{}}; {H}.setStaticPokemon", statics),
        _comp("roamer species words and level bytes", f"{ini_src} RoamingPokemon{{}}; {H}.setRoamers", roam),
        hardcoded,
        _comp("special-music fix IPS + its species pool", f"jar {e['tweaks']['NewIndexToMusicTweak']}.ips; {H}.applyCorrectStaticMusic",
              tweak("NewIndexToMusicTweak"))]
    if not emerald:
        D["fossil_levels"] = [_comp("fossil level words", f"{ini_src} FossilLevelOffsets; {H}.applyMiscTweak BALANCE_STATIC_LEVELS",
                                    [(f, f + 2) for f in A["FossilLevelOffsets"]])]
    td, tlen, tcount = V["TrainerData"], V["TrainerEntrySize"], V["TrainerCount"]
    party = []
    for i in range(1, tcount):
        t = td + i * tlen
        party += [(t, t + 1), (t + tlen - 8, t + tlen - 7)]
        p, n = rom.ptr(t + tlen - 4), clean[t + tlen - 8]
        party.append((p, p + n * (16 if clean[t] & 1 else 8)))
    D["trainer_parties"] = [_comp("trainer party-type byte, party count and every party record",
                                  f"{ini_src} TrainerData/TrainerEntrySize/TrainerCount; {H}.setTrainers (no repoint: counts never grow)",
                                  party)]
    if emerald:
        steven = V["MossdeepStevenTeamOffset"]
        D["trainer_parties"].append(_comp("Steven's three partner records: species, IVs, level and moves only",
            f"{ini_src} MossdeepStevenTeamOffset; {H}.setTrainers Emerald branch",
            [(steven + i * 20 + lo, steven + i * 20 + hi) for i in range(3) for lo, hi in ((0, 4), (12, 20))]))
    D["trainer_names"] = [_comp("trainer names", f"{H}.setTrainerNames TrainerNameLength",
                                [(td + i * tlen + 4, td + i * tlen + 4 + V["TrainerNameLength"]) for i in range(1, tcount)])]
    D["trainer_class_names"] = [_comp("trainer class names", f"{ini_src} TrainerClassNames; {H}.setTrainerClassNames",
                                      site(V["TrainerClassNames"], V["TrainerClassCount"] * V["TrainerClassNameLength"]))]
    D["tms"] = [
        _comp("TM move tables (both copies)", f"{ini_src} TmMoves/TmMovesDuplicate; {H}.setTMMoves",
              site(V["TmMoves"], 100) + site(V["TmMovesDuplicate"], 100)),
        _comp("TM item icon palette pointers", f"{ini_src} ItemImages; {H}.setTMMoves",
              [(V["ItemImages"] + (TM_ITEM_OFFSET + i) * 8 + 4, V["ItemImages"] + (TM_ITEM_OFFSET + i) * 8 + 8)
               for i in range(50)]),
        _comp("TM item description pointers", f"{H}.setTMMoves itemDataDescriptionOffset",
              [(item_data + (TM_ITEM_OFFSET + i) * V["ItemEntrySize"] + ITEM_DESC_FIELD,
                item_data + (TM_ITEM_OFFSET + i) * V["ItemEntrySize"] + ITEM_DESC_FIELD + 4) for i in range(50)]),
        _comp("TM text pointer sites (+copies within the search radius)", f"{ini_src} TMText[]; {H}.preprocessMaps/setTMMoves",
              _text_sites(rom, tmmt, tutor=False))]
    D["tm_compat"] = [_comp("TM/HM compatibility table", f"{ini_src} PokemonTMHMCompat; {H}.setTMHMCompatibility",
                            site(V["PokemonTMHMCompat"], 8 * (count + 1)))]
    mtd, mtn = V["MoveTutorData"], V["MoveTutorMoves"]
    D["tutors"] = [_comp("tutor move words", f"{ini_src} MoveTutorData; {H}.setMoveTutorMoves", site(mtd, 2 * mtn))]
    D["tutor_text"] = [_comp("tutor text pointer sites (+copies within the search radius), written only once setTMMoves "
                             "has walked the maps", f"{ini_src} MoveTutorText[]; {H}.preprocessMaps/setMoveTutorMoves",
                             _text_sites(rom, tmmt, tutor=True))]
    # MoveTutorCompatibility is no INI key for FR/LG: loadROMInfo derives it as MoveTutorData +
    # 2*MoveTutorMoves. Cross-check it against the table the game itself reads: the literal pool
    # of pret's CanLearnTutorMove (the pointer the fork's BPRE hack path reads at 0x120C30).
    tc = mtd + 2 * mtn
    syms = _syms(title)
    lit, size = next((a, n) for a, n, name in syms if name == "CanLearnTutorMove")
    assert any(rom.ptr(lit + i) == tc for i in range(0, size, 4)), "CanLearnTutorMove does not read the derived table"
    D["tutor_compat"] = [_comp("tutor compatibility table (sTutorLearnsets)",
                               f"{H}.loadROMInfo MoveTutorCompatibility = MoveTutorData + 2*MoveTutorMoves (no INI key), "
                               f"= the table pret CanLearnTutorMove reads; {H}.setMoveTutorCompatibility",
                               site(tc, ((mtn + 7) // 8) * (count + 1)))]
    D["trades"] = [_comp("in-game trade table", f"{ini_src} TradeTableOffset/TradeTableSize; {H}.setIngameTrades",
                         site(V["TradeTableOffset"], 60 * V["TradeTableSize"]))]
    D["field_items"] = [
        _comp("item-ball script and hidden-item words holding a TM", f"{H}.preprocessMaps/setFieldTMs (isTM)",
              [(i, i + 2) for i in items if rom.u16(i) in FIELD_TMS], id="field_tms"),
        _comp("item-ball script and hidden-item words holding an allowed non-TM item",
              f"{H}.preprocessMaps/setRegularFieldItems (isAllowed && !isTM)",
              [(i, i + 2) for i in items if rom.u16(i) in FIELD_REGULAR], id="field_regular")]
    shops = []
    for i, off in enumerate(A["ShopItemOffsets"]):
        if i in A["SkipShops"]:
            continue
        end = off
        while rom.u16(end):
            end += 2
        shops.append((off, end))
    D["shops"] = [_comp("item lists of the randomizable shops", f"{ini_src} ShopItemOffsets/SkipShops; {H}.setShopItems", shops)]
    D["item_prices"] = [_comp("item price words", f"{H}.setShopPrices",
                              [(item_data + i * V["ItemEntrySize"] + 16, item_data + i * V["ItemEntrySize"] + 18)
                               for i in range(1, V["ItemCount"])])]
    pk = rom.find(e["strings"]["PickupTableStartLocator"])
    pickup_stride = 2 if emerald else 4
    D["pickup"] = [_comp("pickup item words", f"{ini_src} PickupTableStartLocator; {H}.setPickupItems",
                         [(pk + pickup_stride * i, pk + pickup_stride * i + 2) for i in range(V["PickupItemCount"])] if pk > 0 else [])]
    D["fastest_text"] = [_comp("instant-text IPS (CODE + sTextSpeedFrameDelays)", f"jar {e['tweaks']['InstantTextTweak']}.ips",
                               tweak("InstantTextTweak"))]
    D["pc_potion"] = [_comp("new-game PC item", f"{ini_src} PCPotionOffset; {H}.randomizePCPotion", site(V["PCPotionOffset"], 2))]
    D["running_shoes_indoors"] = [_comp("run-indoors check (CODE)", f"{ini_src} RunIndoorsTweakOffset",
                                        site(V["RunIndoorsTweakOffset"], 1))]
    rs = rom.find("0640002E1BD08C20" if emerald else RUNNING_SHOES_PREFIX_FRLG)
    D["run_without_shoes"] = [_comp("FLAG_SYS_B_DASH branch nop (CODE)", f"{H}.applyRunWithoutRunningShoesPatch",
                                    site(rs + 0x12, 2) if rs > 0 else [])]
    D["catching_tutorial"] = [_comp("catching-tutorial opponent operand (CODE)", f"{ini_src} CatchingTutorialOpponentMonOffset",
                                    site(V["CatchingTutorialOpponentMonOffset"], 4 if emerald else 2))]
    if emerald:
        D["catching_tutorial"].append(_comp("catching-tutorial player operand (CODE)",
            f"{ini_src} CatchingTutorialPlayerMonOffset; {H}.randomizeCatchingTutorial",
            site(V["CatchingTutorialPlayerMonOffset"], 4)))
    aide = rom.find(OAK_AIDE_PREFIX)
    D["national_dex"] = [_comp("Pokedex script hook, national-dex flag checks, Oak/aide fixes (script + CODE)",
                               f"{H}.patchForNationalDex (FRLG)",
                               found(NATDEX_SCRIPT_ID, 6) + found(NATDEX_FLAG_CHECKER, 10, multiple=True)
                               + found(OAKS_LAB_CHECK, 8) + found(OAK_HOUSE_CHECK, 5)
                               + (site(aide + len(OAK_AIDE_PREFIX) // 2 + 1, 1) if aide > 0 else []))]
    if emerald:
        dex = rom.find("3229610825F00129E40816CD40010003")
        assert dex >= 8, "Emerald Pokedex script signature missing or ambiguous"
        dex_pointer = rom.find((ROM_BASE + dex - 8).to_bytes(4, "little").hex())
        assert dex_pointer > 0, "Emerald Pokedex script pointer missing or ambiguous"
        D["national_dex"] = [_comp("Pokedex acquisition script pointer (new script uses packed free space)",
            f"{H}.patchForNationalDex (Emerald); Gen3Constants.ePokedexScriptIdentifier", site(dex_pointer, 4))]
    D["species_names"] = [_comp("species name table", f"{H}.savePokemonStats writeFixedLengthString (applyCamelCaseNames)",
                                site(names + 11, 11 * count))]
    fs = V["FreeSpace"]
    later_symbols = [a for a, _s, _n in syms if a >= fs]
    gap_end = min(later_symbols, default=len(clean))
    assert clean[fs:gap_end] == b"\xff" * (gap_end - fs), "free space is not 0xFF in the clean ROM"
    limit = "up to the first pret symbol" if later_symbols else "to ROM end (no later pret symbol)"
    D["free_space"] = [_comp("0xFF free space the fork repoints text/scripts into, packed from FreeSpace",
                             f"{ini_src} FreeSpace {limit}; every RomFunctions.freeSpaceFinder call "
                             f"scans forward from FreeSpace (audit: packed, PACKED_MAX_GAP)", [(fs, gap_end)], packed=True)]
    # naming only: the rule-bearing tables the family forbids
    learn = V["PokemonMovesets"]
    lsets = [(learn, learn + 4 * (count + 1))]
    for i in range(1, count + 1):
        p = rom.ptr(learn + 4 * i)
        end = p
        while rom.u16(end) != 0xFFFF:
            end += 2
        lsets.append((p, end + 4))
    egg = V["EggMoves"]
    egg_end = egg
    while rom.u16(egg_end) != 0xFFFF:
        egg_end += 2
    te = V["TypeEffectivenessOffset"]
    te_end = te
    while clean[te_end] != 0xFF:
        te_end += 3
    ds = rom.find(e["strings"]["DeoxysStatPrefix"])
    D["base_stats"] = [_comp("base stats of every record + the hardcoded Deoxys forme stats", f"{H}.saveBasicPokeStats/savePokemonStats",
                             field(0, 6) + (site(ds + len(e["strings"]["DeoxysStatPrefix"]) // 2, 12) if ds > 0 else []))]
    D["types"] = [_comp("types of every record", f"{H}.saveBasicPokeStats bsPrimaryTypeOffset=6", field(6, 8))]
    D["abilities"] = [_comp("abilities of every record", f"{H}.saveBasicPokeStats bsAbility1Offset=22", field(22, 24))]
    D["exp_curves"] = [_comp("growth rate of every record", f"{H}.saveBasicPokeStats bsGrowthCurveOffset=19", field(19, 20))]
    D["evolutions"] = [_comp("evolution table", f"{ini_src} PokemonEvolutions; {H}.writeEvolutions",
                             site(V["PokemonEvolutions"], 0x28 * (count + 1)))]
    D["movesets"] = [_comp("level-up learnset pointers and learnsets", f"{ini_src} PokemonMovesets; {H}.setMovesLearnt", lsets)]
    D["egg_moves"] = [_comp("egg move list", f"{ini_src} EggMoves; {H}.setEggMoves", [(egg, egg_end + 2)])]
    D["move_data"] = [_comp("battle move data", f"{H}.saveMoves (efrlgMoveDataPointer)", site(move_data, 12 * (V["MoveCount"] + 1)))]
    D["type_chart"] = [_comp("type effectiveness table", f"{ini_src} TypeEffectivenessOffset; {H}.writeTypeEffectivenessTable",
                             [(te, te_end + 1)])]
    if emerald:
        for domain, markers in EMERALD_FACILITIES.items():
            named = [(a, size, name) for a, size, name in syms if size and any(mark in name for mark in markers)]
            assert named, f"no pinned Emerald {domain} symbols"
            D[domain] = [_comp("protected facility symbols (data and code)",
                f"pokeemerald.sym; Emerald RC excludes {domain}; naming only, never enabled",
                [(a, a + size) for a, size, _ in named], symbols=[name for _, _, name in named])]
    result = {"ini_section": INI_SECTION[title], "clean_sha1": hashlib.sha1(clean).hexdigest(), "domains": D}
    if emerald:
        result["symbol_sha256"] = hashlib.sha256((SYM_DIR / SYM_FILE[title]).read_bytes()).hexdigest()
    return result


def build_model(jar: Path = DEFAULT_JAR, roms: dict[str, bytes] | None = None) -> dict:
    with zipfile.ZipFile(jar) as zf:
        ini = parse_ini(zf.read("com/dabomstew/pkrandom/config/gen3_offsets.ini").decode("utf-8"))
        ips = {n[len("com/dabomstew/pkrandom/patches/"):-4]: zf.read(n) for n in zf.namelist()
               if n.startswith("com/dabomstew/pkrandom/patches/") and n.endswith(".ips")}
    roms = roms or {t: (REPO / STAGED[t]).read_bytes() for t in ("firered", "leafgreen")}
    return {"schema": SCHEMA,
            "generated_by": "python -m server.upr_gen3_write_domain --write" + (" --title emerald" if set(roms) == {"emerald"} else ""),
            "jar_sha256": hashlib.sha256(Path(jar).read_bytes()).hexdigest(),
            "forbidden_domains": list(FORBIDDEN_DOMAINS) + (list(EMERALD_FACILITIES) if "emerald" in roms else []),
            "titles": {t: build_title(t, roms[t], ini, ips) for t in sorted(roms)}}


def dumps(model: dict) -> str:
    return json.dumps(model, indent=1) + "\n"


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate pinned Gen 3 UPR write-domain models")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--title", choices=("frlg", "emerald"), default="frlg")
    args = parser.parse_args()
    if args.write:
        emerald = args.title == "emerald"
        target = EMERALD_MODEL_PATH if emerald else MODEL_PATH
        inputs = {"emerald": (REPO / STAGED["emerald"]).read_bytes()} if emerald else None
        from server.upr_pipeline import find_upr_jar
        target.write_text(dumps(build_model(Path(find_upr_jar() or DEFAULT_JAR), inputs)), encoding="utf-8", newline="\n")
        print(f"wrote {target}")
