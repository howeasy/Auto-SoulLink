"""tools/_upr_probe.py — run tools/upr_probe/SlinkProbe.java against a PokeRandoZX.jar.

The probe is compiled once per jar (into .cache/upr-probe/<jar sha1 prefix>/) with the
pinned JDK and run on the Java 8 JRE that is on PATH, exactly as SLink runs the jar.
"""
from __future__ import annotations

import hashlib
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from tools._build_tools_bootstrap import ensure_jdk  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
PROBE_SRC = REPO / "tools" / "upr_probe" / "SlinkProbe.java"
SEP = ";" if sys.platform == "win32" else ":"


def sha1(path) -> str:
    return hashlib.sha1(pathlib.Path(path).read_bytes()).hexdigest()


def compile_probe(jar: pathlib.Path) -> pathlib.Path:
    out = REPO / ".cache" / "upr-probe" / sha1(jar)[:12]
    if not (out / "SlinkProbe.class").exists():
        out.mkdir(parents=True, exist_ok=True)
        subprocess.run([str(ensure_jdk() / "javac"), "--release", "8", "-cp", str(jar), "-d", str(out),
                        str(PROBE_SRC)], check=True)
    return out


def probe(jar, *args: str, java: str = "java", check: bool = True) -> subprocess.CompletedProcess:
    jar = pathlib.Path(jar)
    cp = compile_probe(jar)
    return subprocess.run([java, "-cp", str(jar) + SEP + str(cp), "SlinkProbe", *args],
                          capture_output=True, text=True, check=check)


def cli(jar, settings, rom_in, rom_out, java: str = "java") -> subprocess.CompletedProcess:
    """The exact invocation server/upr_pipeline.randomize() uses."""
    return subprocess.run([java, "-jar", str(jar), "cli", "-s", str(settings), "-i", str(rom_in),
                           "-o", str(rom_out), "-l"], capture_output=True, text=True)
