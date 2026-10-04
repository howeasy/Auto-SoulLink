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

Library: ``audit(title, overlay_bytes, output_bytes)`` (server/upr_gen2_write_domain.py).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from patch.tools.make_ups import ups_apply  # noqa: E402

# the geometry and the audit are the server's (the pipeline re-runs them on every output)
from server.upr_gen2_write_domain import (  # noqa: E402,F401  (re-exported: the library API)
    HEADER,
    TITLES,
    Geometry,
    audit,
    bank_addr,
    regions,
)
from server.upr_settings import MISC_TWEAKS, build  # noqa: E402

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
