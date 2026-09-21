"""tools/build_upr_fork.py — build a UPR ZX source tree into PokeRandoZX.jar.

UPR ZX 4.6.1 ships no pom/gradle/ant file: upstream builds it as an IntelliJ
artifact (plain sources + resources under ``src/``, main class
``com.dabomstew.pkrandom.newgui.NewRandomizerGUI``; the three ``.form`` files
are inert — the GUI classes build their components in Java). So the build is
``javac --release 8`` over every ``.java`` under ``src/`` plus a copy of every
non-Java resource, jarred with that Main-Class. ``--release 8`` keeps the jar
runnable on the Java 8 JRE SLink shells out to.

Usage:
    python tools/build_upr_fork.py [--src .cache/slink-upr] [--out .cache/slink-upr/PokeRandoZX.jar]
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from tools._build_tools_bootstrap import ensure_jdk  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MAIN_CLASS = "com.dabomstew.pkrandom.newgui.NewRandomizerGUI"


def build(src_root: pathlib.Path, out_jar: pathlib.Path) -> pathlib.Path:
    jdk = ensure_jdk()
    src = src_root / "src"
    if not src.is_dir():
        raise RuntimeError(f"no src/ under {src_root}")
    with tempfile.TemporaryDirectory(prefix="upr-build-") as tmp:
        tmp = pathlib.Path(tmp)
        classes = tmp / "classes"
        classes.mkdir()
        sources = sorted(src.rglob("*.java"))
        argfile = tmp / "sources.txt"
        argfile.write_text("\n".join(f'"{p.as_posix()}"' for p in sources), encoding="utf-8")
        subprocess.run(
            [str(jdk / "javac"), "--release", "8", "-encoding", "UTF-8", "-nowarn",
             "-d", str(classes), f"@{argfile}"],
            check=True)
        for res in src.rglob("*"):
            if res.is_file() and res.suffix not in (".java", ".form"):
                dst = classes / res.relative_to(src)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(res, dst)
        manifest = tmp / "MANIFEST.MF"
        manifest.write_text(f"Manifest-Version: 1.0\nMain-Class: {MAIN_CLASS}\n\n", encoding="utf-8")
        out_jar.parent.mkdir(parents=True, exist_ok=True)
        if out_jar.exists():
            out_jar.unlink()
        subprocess.run(
            [str(jdk / "jar"), "--create", "--file", str(out_jar), "--manifest", str(manifest),
             "-C", str(classes), "."],
            check=True)
    return out_jar


UPR_ZX_URL = "https://github.com/Ajarmar/universal-pokemon-randomizer-zx"
UPR_ZX_COMMIT = "7f00eb866ed35c8fe3963f078b6a2e0979dc2b8c"  # v4.6.1
PATCHES = REPO_ROOT / "patch" / "upr"  # the fork as a durable patch series over v4.6.1


def bootstrap(src_root: pathlib.Path) -> None:
    """Clone UPR ZX at the pinned v4.6.1 commit and apply patch/upr/*.patch (git am)."""
    import subprocess
    if (src_root / "src").is_dir():
        return
    src_root.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "-q", UPR_ZX_URL, str(src_root)], check=True)
    subprocess.run(["git", "-C", str(src_root), "checkout", "-q", UPR_ZX_COMMIT], check=True)
    subprocess.run(["git", "-C", str(src_root), "checkout", "-q", "-b", "slink/4.6.1-slink1"], check=True)
    patches = sorted(str(p) for p in PATCHES.glob("*.patch"))
    if not patches:
        raise RuntimeError(f"no fork patches under {PATCHES}")
    subprocess.run(["git", "-C", str(src_root), "-c", "user.name=slink", "-c", "user.email=slink@local",
                    "am", "--keep-cr", *patches], check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(REPO_ROOT / ".cache" / "slink-upr"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--bootstrap", action="store_true",
                    help="clone UPR ZX v4.6.1 and apply patch/upr/*.patch when --src has no sources")
    args = ap.parse_args()
    src_root = pathlib.Path(args.src)
    if args.bootstrap:
        bootstrap(src_root)
    out = pathlib.Path(args.out) if args.out else src_root / "PokeRandoZX.jar"
    jar = build(src_root, out)
    print(f"{jar} sha256={hashlib.sha256(jar.read_bytes()).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
