"""tools/upr_gen2_write_domain.py -- R0: does UPR randomizing a Gen 2 SLink overlay ROM ever
write inside the overlay? (docs/gen2/RANDOMIZER.md)

The order "apply the UPS overlay, then randomize" is safe only if every byte the fork changes
lies outside the overlay. For each title this:

  1. rebuilds the overlay ROM from the pinned clean dump + patch/dist/SLink-<Title>.ups and
     checks it against data/gen2/overlay_provenance.json;
  2. runs the fork's CLI exactly as server/upr_pipeline.randomize() does (same argv, trusted
     jar only) over a matrix: N "max" seeds, one run per category alone, one per misc tweak
     alone, and an all-off baseline;
  3. diffs each output against the overlay input and intersects the changed bytes with
       ups      the bytes the overlay changed (decoded UPS hunks)       -> must be empty
       slink    every ROM SECTION named "SLink ..." in <title>_slink.map -> must be empty
       touched  the vanilla map SECTIONs that hold an overlay byte      -> informational
     and groups every changed byte into map-section regions: the Gen 2 write domain.

    python tools/upr_gen2_write_domain.py --clean crystal=PATH [--clean gold=PATH ...] \\
        --work F:/slink-work/tmp/g2 --evidence F:/slink-work/evidence/g2-rand-r0 [--seeds 5]
    python tools/upr_gen2_write_domain.py --self-check --clean crystal=PATH   # known-positive control

Library: ``audit(title, overlay_bytes, output_bytes)``.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "patch" / "tools"))
from make_ups import _ups_decode, ups_apply  # noqa: E402

from server.upr_settings import MISC_TWEAKS, build  # noqa: E402

# title -> (lock / provenance key, UPR settings rom name)
TITLES = {"crystal": ("pokecrystal", "Pokemon Crystal (U)"),
          "gold": ("pokegold", "Pokemon Gold (U)"),
          "silver": ("pokesilver", "Pokemon Silver (U)")}
HEADER = range(0x134, 0x150)   # cartridge header: UPR's own checksum fix-up lands here

# every "unchanged" mode bit the matrix may clear, per category
_CATEGORY_FLAGS = {
    "wild_random": {"wild_RANDOM": True, "wild_UNCHANGED": False},
    "wild_area": {"wild_AREA_MAPPING": True, "wild_UNCHANGED": False},
    "wild_global": {"wild_GLOBAL_MAPPING": True, "wild_UNCHANGED": False},
    "trainers": {"trainers_RANDOM": True, "trainers_UNCHANGED": False},
    "starters": {"starters_COMPLETELY_RANDOM": True, "starters_UNCHANGED": False},
    "statics": {"static_COMPLETELY_RANDOM": True, "static_UNCHANGED": False},
    "trades": {"trades_RANDOMIZE_GIVEN_AND_REQUESTED": True, "trades_UNCHANGED": False,
               "randomizeInGameTradesItems": True, "randomizeInGameTradesIVs": True,
               "randomizeInGameTradesNicknames": True, "randomizeInGameTradesOTs": True},
    "tms": {"tms_RANDOM": True, "tms_UNCHANGED": False,
            "tmCompat_COMPLETELY_RANDOM": True, "tmCompat_UNCHANGED": False},
    "tutors": {"tutors_RANDOM": True, "tutors_UNCHANGED": False,
               "tutorCompat_COMPLETELY_RANDOM": True, "tutorCompat_UNCHANGED": False},
    "field_items": {"fieldItems_RANDOM": True, "fieldItems_UNCHANGED": False},
}
MAX_CATEGORIES = ("trainers", "starters", "statics", "trades", "tms", "tutors", "field_items")
WILD_MODES = ("wild_random", "wild_area", "wild_global")
TWEAKS = ("BW_EXP_PATCH", "FASTEST_TEXT", "LOWER_CASE_POKEMON_NAMES",
          "RANDOMIZE_CATCHING_TUTORIAL", "BAN_LUCKY_EGG")


def settings_bytes(title: str, categories=(), tweaks=()) -> bytes:
    flags: dict[str, bool] = {}
    for c in categories:
        flags.update(_CATEGORY_FLAGS[c])
    misc = 0
    for t in tweaks:
        misc |= MISC_TWEAKS[t]
    return build(flags, misc, rom_name=TITLES[title][1])


def matrix(seeds: int) -> list[tuple[str, tuple, tuple]]:
    """(run name, categories, tweaks). Max runs rotate the three wild modes."""
    runs = [("off", (), ())]
    runs += [(f"max{i + 1}_{WILD_MODES[i % 3]}", (WILD_MODES[i % 3], *MAX_CATEGORIES), ())
             for i in range(seeds)]
    runs += [(f"cat_{c}", (c,), ()) for c in _CATEGORY_FLAGS]
    runs += [(f"tweak_{t}", (), (t,)) for t in TWEAKS]
    return runs


# ── ROM geometry ─────────────────────────────────────────────────────────────────────────
def flat(bank: int, addr: int) -> int:
    return addr if bank == 0 else bank * 0x4000 + (addr - 0x4000)


def bank_addr(off: int) -> str:
    bank = off // 0x4000
    return f"{bank:02X}:{off if bank == 0 else 0x4000 + off % 0x4000:04X}"


def ups_spans(patch: bytes) -> list[tuple[int, int]]:
    """[start, end) runs of bytes the UPS changes (a hunk is a run of non-zero XOR bytes)."""
    pos, out, i, end = 4, [], 0, len(patch) - 12
    _, pos = _ups_decode(patch, pos)
    _, pos = _ups_decode(patch, pos)
    while pos < end:
        rel, pos = _ups_decode(patch, pos)
        i += rel
        start, x = i, None
        while pos < end:
            x = patch[pos]
            pos += 1
            i += 1
            if x == 0:
                break
        # the terminating 0 XOR is an unchanged byte; a hunk running to EOF has none
        out.append((start, i - 1 if x == 0 else i))
    return out


def map_sections(map_path: pathlib.Path) -> list[tuple[int, int, str]]:
    """[start, end) flat ROM ranges of every section in an rgblink .map (ROM0/ROMX only)."""
    out, bank = [], None
    for line in map_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if m := re.match(r"^(ROM0|ROMX) bank #(\d+):", line):
            bank = int(m.group(2))
        elif re.match(r"^\S", line):
            bank = None                                   # WRAM / SRAM / HRAM ...
        elif bank is not None and (m := re.search(r'SECTION: \$([0-9a-f]+)(?:-\$([0-9a-f]+))? .*\["(.*)"\]', line)):
            lo = int(m.group(1), 16)
            hi = int(m.group(2), 16) if m.group(2) else lo
            out.append((flat(bank, lo), flat(bank, hi) + 1, m.group(3)))
    return sorted(out)


def sym_labels(sym_path: pathlib.Path) -> tuple[list[int], list[str]]:
    offs, names = [], []
    for line in sym_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^([0-9a-f]{2}):([0-9a-f]{4}) (\S+)", line)
        if m and (int(m.group(2), 16) < 0x8000):
            offs.append(flat(int(m.group(1), 16), int(m.group(2), 16)))
            names.append(m.group(3))
    order = sorted(range(len(offs)), key=offs.__getitem__)
    return [offs[i] for i in order], [names[i] for i in order]


def _merge(offsets, gap: int = 1) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for o in sorted(offsets):
        if out and o - out[-1][1] <= gap:
            out[-1][1] = o + 1
        else:
            out.append([o, o + 1])
    return [tuple(r) for r in out]


class Geometry:
    def __init__(self, title: str):
        key = TITLES[title][0]
        stem = {"pokecrystal": "crystal", "pokegold": "gold", "pokesilver": "silver"}[key]
        prov = json.loads((REPO / "data" / "gen2" / "overlay_provenance.json").read_text())["outputs"][key]
        self.prov = prov
        self.spans = ups_spans((REPO / prov["ups"]["file"]).read_bytes())
        self.ups_bytes = {i for a, b in self.spans for i in range(a, b)}
        self.sections = map_sections(REPO / "data" / "gen2" / f"{stem}_slink.map")
        self._starts = [s[0] for s in self.sections]
        self.slink = [s for s in self.sections if s[2].lower().startswith("slink")]
        self.slink_bytes = {i for a, b, _ in self.slink for i in range(a, b)}
        self.touched = sorted({s for s in self.sections if any(i in self.ups_bytes for i in range(s[0], s[1]))})
        self.touched_bytes = {i for a, b, _ in self.touched for i in range(a, b)}
        self.label_offs, self.label_names = sym_labels(REPO / "data" / "gen2" / f"{stem}_slink.sym")

    def section_of(self, off: int) -> str:
        k = bisect.bisect_right(self._starts, off) - 1
        if k >= 0 and self.sections[k][0] <= off < self.sections[k][1]:
            return self.sections[k][2]
        return "(unmapped)"

    def label_of(self, off: int) -> str:
        k = bisect.bisect_right(self.label_offs, off) - 1
        return f"{self.label_names[k]}+{off - self.label_offs[k]:#x}" if k >= 0 else "?"


def regions(geo: Geometry, offsets) -> list[dict]:
    """Changed bytes merged into runs (gap <= 16) and attributed to their map section."""
    out = []
    for a, b in _merge(offsets, 16):
        out.append({"start": bank_addr(a), "end": bank_addr(b - 1), "flat": [a, b],
                    "section": geo.section_of(a), "label": geo.label_of(a),
                    "changed": sum(1 for o in offsets if a <= o < b) if len(offsets) < 200000 else None})
    return out


def audit(title: str, overlay: bytes, output: bytes, geo: Geometry | None = None) -> dict:
    geo = geo or Geometry(title)
    if len(overlay) != len(output):
        raise ValueError(f"size changed {len(overlay)} -> {len(output)}")
    changed = [i for i, (x, y) in enumerate(zip(overlay, output, strict=True)) if x != y]
    ch = set(changed)
    return {
        "changed": len(changed),
        "header": [bank_addr(i) for i in changed if i in HEADER],
        "ups_hits": [bank_addr(i) for i in sorted(ch & geo.ups_bytes) if i not in HEADER],
        "slink_hits": [bank_addr(i) for i in sorted(ch & geo.slink_bytes)],
        "touched_section_hits": sorted({geo.section_of(i) for i in ch & geo.touched_bytes if i not in HEADER}),
        "regions": regions(geo, changed),
        "_changed": changed,
    }


# ── running ──────────────────────────────────────────────────────────────────────────────
def load_overlay(title: str, clean_path: pathlib.Path) -> tuple[bytes, bytes]:
    key = TITLES[title][0]
    lock = json.loads((REPO / "data" / "gen2_sources.lock.json").read_text())["outputs"][key]
    clean = clean_path.read_bytes()
    if hashlib.sha1(clean).hexdigest() != lock["sha1"]:
        raise SystemExit(f"{clean_path} is not the pinned clean {key} ({lock['sha1']})")
    geo_prov = json.loads((REPO / "data" / "gen2" / "overlay_provenance.json").read_text())["outputs"][key]
    overlay = ups_apply(clean, (REPO / geo_prov["ups"]["file"]).read_bytes())
    if hashlib.sha1(overlay).hexdigest() != geo_prov["sha1"] or hashlib.md5(overlay).hexdigest() != geo_prov["md5"]:
        raise SystemExit(f"{title}: overlay does not match overlay_provenance.json")
    return clean, overlay


def run_cli(jar: str, settings: pathlib.Path, rom_in: pathlib.Path, rom_out: pathlib.Path) -> subprocess.CompletedProcess:
    """The exact argv server/upr_pipeline.randomize() uses."""
    return subprocess.run(["java", "-jar", jar, "cli", "-s", str(settings), "-i", str(rom_in),
                           "-o", str(rom_out), "-l"], capture_output=True, text=True, timeout=600)


def seed_of(log: pathlib.Path) -> int | None:
    m = re.search(r"Random Seed: (\d+)", log.read_text(encoding="utf-8-sig", errors="replace"))
    return int(m.group(1)) if m else None


def main_run(args) -> int:
    from server.upr_pipeline import find_upr_jar, jar_is_trusted, jar_sha256
    jar = os.path.realpath(args.jar or find_upr_jar() or "")
    if not jar_is_trusted(jar):
        raise SystemExit(f"untrusted or missing jar: {jar}")
    work, ev = pathlib.Path(args.work), pathlib.Path(args.evidence)
    work.mkdir(parents=True, exist_ok=True)
    ev.mkdir(parents=True, exist_ok=True)
    summary = {"jar": jar, "jar_sha256": jar_sha256(jar), "titles": {}}
    for title, path in args.clean:
        _clean, overlay = load_overlay(title, pathlib.Path(path))
        geo = Geometry(title)
        src = work / f"{title}_overlay.gbc"
        src.write_bytes(overlay)
        tsum = {"overlay_sha1": hashlib.sha1(overlay).hexdigest(), "ups_spans": len(geo.spans),
                "ups_bytes": len(geo.ups_bytes), "slink_sections": len(geo.slink),
                "slink_bytes": len(geo.slink_bytes),
                "touched_sections": [s[2] for s in geo.touched], "runs": {}}
        domain: dict[str, set] = {}
        for name, cats, tweaks in matrix(args.seeds):
            settings = work / f"{title}_{name}.rnqs"
            settings.write_bytes(settings_bytes(title, cats, tweaks))
            out = work / f"{title}_{name}.gbc"
            proc = run_cli(jar, settings, src, out)
            log = pathlib.Path(str(out) + ".log")
            row = {"categories": list(cats), "tweaks": list(tweaks), "rc": proc.returncode,
                   "stdout": proc.stdout.strip()[-600:], "stderr": proc.stderr.strip()[-600:]}
            if proc.returncode == 0 and out.exists():
                r = audit(title, overlay, out.read_bytes(), geo)
                domain[name] = set(r.pop("_changed"))
                row.update(r, seed=seed_of(log) if log.exists() else None,
                           warnings=[ln for ln in (log.read_text(encoding="utf-8-sig", errors="replace").splitlines() if log.exists() else [])
                                     if re.search(r"warn|crc|error|fail|could not|unable", ln, re.I)][:20])
                (ev / f"{title}_{name}.gbc.log").write_bytes(log.read_bytes())
                out.unlink()
            (ev / f"{title}_{name}.json").write_text(json.dumps(row, indent=1))
            tsum["runs"][name] = {k: row.get(k) for k in ("rc", "seed", "changed", "header", "ups_hits", "slink_hits",
                                                          "touched_section_hits", "warnings")}
            print(f"[{title}] {name}: rc={proc.returncode} changed={row.get('changed')} "
                  f"ups_hits={len(row.get('ups_hits') or [])} slink_hits={len(row.get('slink_hits') or [])} "
                  f"header={row.get('header')}", flush=True)
        # the write domain: every byte any run changed, by map section, with the runs that wrote it
        union = set().union(*domain.values()) if domain else set()
        tsum["write_domain"] = [dict(reg, runs=sorted(n for n, s in domain.items()
                                                      if any(reg["flat"][0] <= o < reg["flat"][1] for o in s)))
                                for reg in regions(geo, union)]
        summary["titles"][title] = tsum
    (ev / "summary.json").write_text(json.dumps(summary, indent=1))
    bad = [(t, n) for t, s in summary["titles"].items() for n, r in s["runs"].items()
           if r["rc"] != 0 or r["ups_hits"] or r["slink_hits"]]
    print("COLLISIONS / FAILURES:" if bad else "NO COLLISIONS", bad)
    return 1 if bad else 0


def self_check(args) -> int:
    """Known-positive control: a byte flipped inside an overlay hunk and one inside an SLink
    section must be reported; one flipped in a vanilla table must only land in regions."""
    title, path = args.clean[0]
    _clean, overlay = load_overlay(title, pathlib.Path(path))
    geo = Geometry(title)
    assert len(geo.spans) and sum(b - a for a, b in geo.spans) == len(geo.ups_bytes)
    assert all(x != y for x, y in ((_clean[i], overlay[i]) for i in geo.ups_bytes)), "UPS decode off"
    assert sum(1 for x, y in zip(_clean, overlay, strict=True) if x != y) == len(geo.ups_bytes), "UPS decode incomplete"
    hunk = next(a for a, b in geo.spans if a not in HEADER)
    sec = geo.slink[-1][0] + 2
    plain = next(i for i in range(0x50000, 0x60000) if i not in geo.touched_bytes)
    out = bytearray(overlay)
    for i in (hunk, sec, plain):
        out[i] ^= 0xFF
    r = audit(title, overlay, bytes(out), geo)
    assert bank_addr(hunk) in r["ups_hits"], r["ups_hits"]
    assert bank_addr(sec) in r["slink_hits"], r["slink_hits"]
    assert r["changed"] == 3 and len(r["regions"]) == 3
    assert audit(title, overlay, overlay, geo)["changed"] == 0
    print(f"self-check OK ({title}: {len(geo.spans)} spans / {len(geo.ups_bytes)} bytes, "
          f"{len(geo.slink)} SLink sections / {len(geo.slink_bytes)} bytes; flagged {bank_addr(hunk)}, "
          f"{bank_addr(sec)}; {bank_addr(plain)} only in regions)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clean", action="append", required=True, type=lambda s: tuple(s.split("=", 1)),
                    help="title=path to the pinned clean dump (crystal, gold, silver)")
    ap.add_argument("--jar")
    ap.add_argument("--work", default="F:/slink-work/tmp/g2-rand-r0/work")
    ap.add_argument("--evidence", default="F:/slink-work/evidence/g2-rand-r0")
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--self-check", action="store_true")
    args = ap.parse_args()
    for t, _ in args.clean:
        if t not in TITLES:
            ap.error(f"unknown title {t}")
    return self_check(args) if args.self_check else main_run(args)


if __name__ == "__main__":
    sys.exit(main())
