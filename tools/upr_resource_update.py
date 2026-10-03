#!/usr/bin/env python3
"""Keep the SLink UPR fork jar's pureRGB overlay entries current with data/purergb/upr_pure_entries.ini.

The randomizer jar identifies a cartridge by its header CRC / CRC32, so every rebuilt pureRGB overlay (and every stamped
release: the version text is part of the ROM) needs its entry in the jar's gen1_offsets.ini. That is a RESOURCE-ONLY
update: every zip entry except com/dabomstew/pkrandom/config/gen1_offsets.ini stays byte-identical, no Java class changes.

    python tools/upr_resource_update.py --check      # exit 1 if the installed jar's entries differ from the generated ones
    python tools/upr_resource_update.py --install    # build the updated jar, keep the old one, pin it, write the patch file

--install, in order:
  1. splice the current entries into a copy of the installed jar's own ini (tools/gen_upr_gen1_ini.splice_into_fork);
  2. write the new jar next to the old one (zip entries copied one by one, only the ini replaced; asserted);
  3. copy the installed jar to PokeRandoZX-pre<NNNN>-<date>.jar, then install the new one as PokeRandoZX.jar;
  4. pin its sha256 in data/upr_jars.json (the Manager runs only pinned jars);
  5. write patch/upr/<NNNN>-slink-pure-overlay-entries-regenerated.patch (the series is the durable record of the fork);
  6. re-pin the Gen 3 write-domain models to the new jar: `python -m server.upr_gen3_write_domain --write --title frlg|emerald`
     (printed, not run: they need the clean Gen 3 ROMs staged; tools/stamp_release.py runs them).
"""
from __future__ import annotations

import argparse
import datetime
import difflib
import hashlib
import json
import pathlib
import re
import shutil
import sys
import tempfile
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
INI_NAME = "com/dabomstew/pkrandom/config/gen1_offsets.ini"
ENTRIES = ROOT / "data" / "purergb" / "upr_pure_entries.ini"
ALLOWLIST = ROOT / "data" / "upr_jars.json"
PATCHES = ROOT / "patch" / "upr"
DEFAULT_JAR = ROOT / ".cache" / "slink-upr" / "PokeRandoZX.jar"
FORK_REL = "src/" + INI_NAME


def spliced_ini(jar: pathlib.Path) -> tuple[str, str]:
    """(the jar's current ini, the same ini with data/purergb/upr_pure_entries.ini spliced in)."""
    import gen_upr_gen1_ini as gen

    with zipfile.ZipFile(jar) as zf:
        old = zf.read(INI_NAME).decode("utf-8")
    with tempfile.TemporaryDirectory(prefix="upr-ini-") as tmp:
        fork = pathlib.Path(tmp)
        target = fork / gen.FORK_INI
        target.parent.mkdir(parents=True)
        target.write_text(old, encoding="utf-8", newline="\n")
        gen.splice_into_fork(fork, ENTRIES.read_text(encoding="utf-8"))
        return old, target.read_text(encoding="utf-8")


def rewrite_jar(src: pathlib.Path, dst: pathlib.Path, new_ini: str) -> None:
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for info in zin.infolist():
            data = new_ini.encode("utf-8") if info.filename == INI_NAME else zin.read(info.filename)
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type, zi.external_attr, zi.create_system = info.compress_type, info.external_attr, info.create_system
            zout.writestr(zi, data)
    with zipfile.ZipFile(src) as a, zipfile.ZipFile(dst) as b:
        assert [i.filename for i in a.infolist()] == [i.filename for i in b.infolist()]
        changed = [i.filename for i in a.infolist() if a.read(i.filename) != b.read(i.filename)]
    if changed != [INI_NAME]:
        raise RuntimeError(f"resource-only update touched {changed}")


def next_patch_number() -> int:
    nums = [int(m[1]) for p in PATCHES.glob("*.patch") if (m := re.match(r"(\d{4})-", p.name))]
    return max(nums, default=0) + 1


def patch_text(old: str, new: str, number: int, subject: str) -> str:
    diff = list(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                     fromfile=f"a/{FORK_REL}", tofile=f"b/{FORK_REL}", n=3))
    stat = sum(1 for line in diff if line[:1] == "+" and line[:3] != "+++")
    minus = sum(1 for line in diff if line[:1] == "-" and line[:3] != "---")
    return (f"From: slink <slink@local>\nDate: {datetime.datetime.now(datetime.UTC):%a, %d %b %Y %H:%M:%S +0000}\n"
            f"Subject: [PATCH] {subject}\n\n---\n {FORK_REL} | {stat + minus} {'+' * stat}{'-' * minus}\n"
            f" 1 file changed, {stat} insertions(+), {minus} deletions(-)\n\n"
            f"diff --git a/{FORK_REL} b/{FORK_REL}\n" + "".join(diff))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jar", type=pathlib.Path, default=DEFAULT_JAR)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--install", action="store_true")
    ap.add_argument("--label", default="resource update", help="note appended to the allowlist label")
    args = ap.parse_args()
    if not args.jar.is_file():
        print(f"ERROR: the fork jar is not at {args.jar}", file=sys.stderr)
        return 1
    old, new = spliced_ini(args.jar)
    if old == new:
        print("the installed jar already carries every generated pureRGB entry")
        return 0
    if args.check:
        print("the installed jar's pureRGB entries differ from data/purergb/upr_pure_entries.ini: run --install", file=sys.stderr)
        return 1
    number = next_patch_number()
    today = datetime.date.today().isoformat()
    candidate = args.jar.with_name(f"PokeRandoZX-{number:04d}-candidate.jar")
    rewrite_jar(args.jar, candidate, new)
    sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
    backup = args.jar.with_name(f"PokeRandoZX-pre{number:04d}-{today}.jar")
    shutil.copyfile(args.jar, backup)
    shutil.copyfile(candidate, args.jar)
    candidate.unlink()
    pins = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    pins[f"SLink fork 4.6.1-slink3, {args.label} {today} (patches 0001-{number:04d}; PokeRandoZX.jar)"] = sha
    ALLOWLIST.write_text(json.dumps(pins, indent=2) + "\n", encoding="utf-8", newline="\n")
    subject = f"slink: pure overlay entries regenerated ({args.label}, {today})"
    out = PATCHES / f"{number:04d}-slink-pure-overlay-entries-regenerated.patch"
    out.write_text(patch_text(old, new, number, subject), encoding="utf-8", newline="\n")
    print(f"installed {args.jar.name} sha256 {sha}\n  previous jar kept as {backup.name}\n  pinned in {ALLOWLIST.relative_to(ROOT)}"
          f"\n  patch {out.relative_to(ROOT)}")
    print("next: python -m server.upr_gen3_write_domain --write --title frlg ; ... --title emerald (jar_sha256 changes only)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
