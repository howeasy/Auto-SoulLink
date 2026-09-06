"""Run the reviewed portable CI inventory without private/local cartridge inputs."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=ROOT / ".cache/portable-ci/report.json")
    args = parser.parse_args(argv)
    report = args.report.resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    # A failed startup must not leave an earlier green report looking current.
    report.write_text('{"schema":1,"portable_passed":false,"release_approved":false,"problems":["run incomplete"]}\n',
                      encoding="utf-8")
    run = Path(tempfile.mkdtemp(prefix="run-", dir=report.parent))
    temporary = run / "tmp"
    temporary.mkdir()
    env = dict(os.environ, TMP=str(temporary), TEMP=str(temporary), TMPDIR=str(temporary))
    for key in ("PYTEST_ADDOPTS", "SLINK_UPR_JAR", "SLINK_ROOT", "SLINK_LIVE", "SLINK_E2E"):
        env.pop(key, None)
    command = [sys.executable, "-m", "pytest", "tests/unit", "tests/integration", "-q",
               "-p", "tools.portable_ci", "--portable-ci-inventory", "tests/portable_ci_inventory.json",
               "--portable-ci-report", str(report), "--basetemp", str(run / "pytest")]
    return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
