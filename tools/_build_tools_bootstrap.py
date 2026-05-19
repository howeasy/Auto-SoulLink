"""
tools/_build_tools_bootstrap.py — Phase 10 build-tool auto-installer

Locates or downloads RGBDS v1.0.1 (pinned), returns the directory containing
rgbasm/rgblink/rgbfix binaries. Called by tools/build_pret_syms.py before
any compilation step.

On Windows: auto-downloads the official rgbds-win64.zip to
  .cache/build-tools/rgbds-v1.0.1/
inside the current worktree, verifies SHA-256 against the release page, and
extracts.

On macOS / Linux: refuses to auto-install (system-level installs require
sudo). Prints the brew / apt one-liner and exits.

Driving RGBDS directly avoids the GNU-make + w64devkit dependency entirely —
we never call `make`, only rgbasm.exe and rgblink.exe.

Usage:
    from tools._build_tools_bootstrap import ensure_rgbds
    rgbds_bin = ensure_rgbds()  # pathlib.Path to dir with rgbasm.exe etc.
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from typing import Optional

# Pinned RGBDS release — change here if upgrading.
RGBDS_VERSION = "v1.0.1"

# Mirror of the official release. Verified against the GitHub release page on
# initial vendor — SHA-256 below must match or the bootstrap aborts.
RGBDS_WIN64_URL = "https://github.com/gbdev/rgbds/releases/download/v1.0.1/rgbds-win64.zip"
RGBDS_WIN64_SHA256 = "554187d717cca78136a81d167107ea15742e7f622797d0b339c0bfb7ab749097"
RGBDS_WIN64_SIZE = 559_001

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / ".cache" / "build-tools" / f"rgbds-{RGBDS_VERSION}"
DOWNLOAD_CACHE = REPO_ROOT / ".cache" / "downloads"

REQUIRED_BINARIES = ("rgbasm", "rgblink", "rgbfix")


def _binary_name(name: str) -> str:
    return f"{name}.exe" if platform.system() == "Windows" else name


def _which_in_dir(dir_path: pathlib.Path, name: str) -> Optional[pathlib.Path]:
    candidate = dir_path / _binary_name(name)
    return candidate if candidate.exists() else None


def _check_existing_path(binary: str) -> Optional[pathlib.Path]:
    """Return path to `binary` on PATH if found and executable, else None."""
    found = shutil.which(binary)
    return pathlib.Path(found) if found else None


def _verify_rgbds_version(rgbasm: pathlib.Path) -> bool:
    """Return True if `rgbasm --version` reports v1.0.1 (the pinned version).
    The expected output is 'rgbasm v1.0.1\\n' or similar."""
    try:
        result = subprocess.run(
            [str(rgbasm), "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    output = (result.stdout or "") + (result.stderr or "")
    return RGBDS_VERSION in output


def _download_and_verify(url: str, expected_sha256: str, expected_size: int) -> pathlib.Path:
    """Download `url` into DOWNLOAD_CACHE, verify SHA-256, return path to file.
    If already present and hash matches, skip the download."""
    DOWNLOAD_CACHE.mkdir(parents=True, exist_ok=True)
    filename = url.rsplit("/", 1)[-1]
    target = DOWNLOAD_CACHE / filename

    if target.exists() and target.stat().st_size == expected_size:
        if _sha256(target) == expected_sha256:
            return target
        target.unlink()  # corrupt cache, re-download

    print(f"[bootstrap] Downloading {url} ({expected_size} bytes)...", file=sys.stderr)
    with urllib.request.urlopen(url) as resp, open(target, "wb") as out:
        shutil.copyfileobj(resp, out)

    actual_size = target.stat().st_size
    if actual_size != expected_size:
        target.unlink()
        raise RuntimeError(
            f"Download size mismatch: got {actual_size} bytes, expected {expected_size}. "
            f"URL: {url}"
        )

    actual_hash = _sha256(target)
    if actual_hash != expected_sha256:
        target.unlink()
        raise RuntimeError(
            f"SHA-256 mismatch on {filename}: "
            f"got {actual_hash}, expected {expected_sha256}. "
            f"Either the release was retagged or the download is corrupt."
        )
    print(f"[bootstrap] Verified SHA-256 of {filename}", file=sys.stderr)
    return target


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _install_rgbds_windows() -> pathlib.Path:
    """Download + extract RGBDS v1.0.1 win64 into CACHE_DIR. Return CACHE_DIR."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Skip if already extracted and binaries exist
    if all((CACHE_DIR / _binary_name(b)).exists() for b in REQUIRED_BINARIES):
        return CACHE_DIR

    zip_path = _download_and_verify(
        RGBDS_WIN64_URL, RGBDS_WIN64_SHA256, RGBDS_WIN64_SIZE
    )

    print(f"[bootstrap] Extracting RGBDS {RGBDS_VERSION} to {CACHE_DIR}", file=sys.stderr)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(CACHE_DIR)

    # Verify the extraction produced our binaries
    missing = [b for b in REQUIRED_BINARIES if not (CACHE_DIR / _binary_name(b)).exists()]
    if missing:
        raise RuntimeError(
            f"RGBDS extraction did not produce expected binaries: {missing}. "
            f"Contents of {CACHE_DIR}: {[p.name for p in CACHE_DIR.iterdir()]}"
        )

    return CACHE_DIR


def _install_instructions_unix() -> str:
    system = platform.system()
    if system == "Darwin":
        return f"  brew install rgbds   # installs RGBDS (current Homebrew version may differ from {RGBDS_VERSION})"
    return (
        "  # Debian/Ubuntu:\n"
        "  sudo apt install rgbds\n"
        "  # Arch:\n"
        "  sudo pacman -S rgbds\n"
        "  # Or build from source: https://github.com/gbdev/rgbds/releases/tag/" + RGBDS_VERSION
    )


def ensure_rgbds() -> pathlib.Path:
    """Locate or install RGBDS. Return the directory containing the binaries.

    Resolution order:
      1. .cache/build-tools/rgbds-v1.0.1/ inside the worktree (auto-installed).
      2. RGBDS binaries on system PATH (if version is v1.0.1, accepted).
      3. On Windows only: auto-download + install to .cache/build-tools/.
      4. On macOS / Linux: print install instructions and exit.

    Raises RuntimeError if RGBDS cannot be located after attempting install.
    """
    # 1. Already-installed local cache
    if all((CACHE_DIR / _binary_name(b)).exists() for b in REQUIRED_BINARIES):
        rgbasm = CACHE_DIR / _binary_name("rgbasm")
        if _verify_rgbds_version(rgbasm):
            return CACHE_DIR
        # Cache exists but wrong version — refresh
        shutil.rmtree(CACHE_DIR)

    # 2. System PATH
    rgbasm_on_path = _check_existing_path("rgbasm")
    if rgbasm_on_path and _verify_rgbds_version(rgbasm_on_path):
        print(
            f"[bootstrap] Using system RGBDS at {rgbasm_on_path.parent}",
            file=sys.stderr,
        )
        return rgbasm_on_path.parent

    # 3. Auto-install (Windows)
    if platform.system() == "Windows":
        return _install_rgbds_windows()

    # 4. Manual install on Unix-likes
    if rgbasm_on_path:
        actual_version = subprocess.run(
            [str(rgbasm_on_path), "--version"],
            capture_output=True, text=True,
        ).stdout.strip()
        raise RuntimeError(
            f"Found RGBDS at {rgbasm_on_path} but version mismatch.\n"
            f"  Expected: {RGBDS_VERSION}\n"
            f"  Got:      {actual_version}\n"
            f"Install the pinned version:\n{_install_instructions_unix()}"
        )

    raise RuntimeError(
        f"RGBDS {RGBDS_VERSION} not found on PATH. Install manually:\n"
        f"{_install_instructions_unix()}\n"
        f"After install, re-run."
    )


def main() -> int:
    """CLI entry point: print the binary directory and exit code."""
    try:
        binary_dir = ensure_rgbds()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(binary_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
