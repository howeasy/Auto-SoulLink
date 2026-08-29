"""Produce a matched pair of randomized ROMs, or refuse to.

A Soul Link run on randomized cartridges is only fair if both players got the SAME
settings and DIFFERENT seeds. Neither half is checkable after the fact from the ROMs alone,
so this drives the randomizer itself and keeps the evidence.

WHY THE SEED HAS TO BE READ BACK RATHER THAN CHOSEN. UPR ZX v4.6.1's CLI has no seed flag:
``Randomizer.randomize(filename, log)`` calls ``RandomSource.pickSeed()`` unconditionally and
the 3-argument overload that takes a seed is never reached from ``CliRandomizer``. The seed
is written only to the log, and only when ``-l`` is passed. So the pipeline always passes
``-l``, parses ``Random Seed:`` back out, and requires the two to differ -- it cannot demand
particular seeds, only verify it got two.

WHY THE SETTINGS HAVE TO BE READ BACK TOO. ``Settings.tweakForRom()`` mutates settings in
place before randomizing and the CLI computes ``isRemovedCodeTweaks`` and then discards it,
so a silently dropped option produces no output at all. The settings a player HANDS us are
therefore not necessarily the settings that were APPLIED, and only the ``Settings String:``
line in the log says what actually ran. Measured on Gen 1: it clears allowWonderGuard and
trainersBlockEarlyWonderGuard and replaces custom-starter sentinels with the ROM's own,
none of which touch the allowlist -- but that is a fact to verify per run, not to assume.

WHY THE OUTPUT FILENAME IS DISCOVERED RATHER THAN TRUSTED. ``FileFunctions.fixFilename``
APPENDS ``.gbc`` to anything not already ending in it, so ``-o out.gb`` silently produces
``out.gb.gbc``. Asking for ``.gbc`` avoids it; checking what appeared catches it anyway.

THE JAR IS NOT BUNDLED. UPR ZX is GPLv3 and redistributable, but the project policy is that
players supply their own from the official releases, and SLink shells out to it as a
separate process.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess

from server.adapters.gen1_rom_scan import RomScanError, identify, scan, scan_base_stats
from server.upr_settings import (
    UprSettingsError, categories_enabled, forbidden_enabled, load, parse_settings_string,
)

RANDOMIZE_TIMEOUT = 600
_SEED_RE = re.compile(r"^Random Seed:\s*(\d+)\s*$")
_SETTINGS_RE = re.compile(r"^Settings String:\s*(\S+)\s*$")
_VERSION_RE = re.compile(r"^Randomizer Version:\s*(\S+)\s*$")

SUPPORTED_UPR_VERSION = "4.6.1"


class UprPipelineError(Exception):
    """The pair could not be produced, or could not be trusted once produced."""


def _sha1(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_log(path: str) -> dict:
    """Pull the seed and the EFFECTIVE settings out of a UPR log.

    The log is UTF-8 with a BOM, and the settings line is the version integer immediately
    followed by Base64 with no separator (Randomizer.java writes VERSION + toString()).
    """
    with open(path, "rb") as f:
        text = f.read().decode("utf-8-sig", "replace")
    seed = settings = version = None
    for line in text.splitlines():
        if m := _SEED_RE.match(line):
            seed = int(m.group(1))
        elif m := _SETTINGS_RE.match(line):
            settings = m.group(1)
        elif m := _VERSION_RE.match(line):
            version = m.group(1)
        if seed is not None and settings and version:
            break
    if seed is None or not settings:
        raise UprPipelineError(f"{os.path.basename(path)} has no seed or settings line")
    if not 0 <= seed < (1 << 48):
        raise UprPipelineError(f"seed {seed} is outside the 48-bit range UPR produces")
    return {"seed": seed, "settings_string": settings, "version": version}


def randomize(jar: str, settings_path: str, source_rom: str, output_rom: str,
              java: str = "java", timeout: int = RANDOMIZE_TIMEOUT) -> dict:
    """Run UPR once. Returns the seed, effective settings and the artifact's identity."""
    for label, path in (("jar", jar), ("settings", settings_path), ("source ROM", source_rom)):
        if not os.path.exists(path):
            raise UprPipelineError(f"{label} not found: {path}")
    if not shutil.which(java):
        raise UprPipelineError(f"{java} is not on PATH — UPR ZX needs a Java runtime")
    if os.path.abspath(source_rom) == os.path.abspath(output_rom):
        raise UprPipelineError("source and output are the same file — refusing to randomize "
                               "a ROM over itself, which would destroy the clean copy")
    if not output_rom.lower().endswith(".gbc"):
        # Not a style preference: UPR APPENDS .gbc to anything else, so the artifact would
        # not be where the caller thinks it is.
        raise UprPipelineError(f"output must end in .gbc, got {output_rom!r}")

    before = set(os.listdir(os.path.dirname(os.path.abspath(output_rom)) or "."))
    proc = subprocess.run(
        [java, "-jar", jar, "cli", "-s", settings_path, "-i", source_rom,
         "-o", output_rom, "-l"],
        capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise UprPipelineError(
            f"UPR exited {proc.returncode}: {(proc.stderr or proc.stdout).strip()[:400]}")

    if not os.path.exists(output_rom):
        # Report what DID appear; a silently renamed artifact is the likeliest cause.
        appeared = sorted(set(os.listdir(
            os.path.dirname(os.path.abspath(output_rom)) or ".")) - before)
        raise UprPipelineError(
            f"UPR reported success but {os.path.basename(output_rom)} does not exist; "
            f"new files: {appeared}")
    log_path = output_rom + ".log"
    if not os.path.exists(log_path):
        raise UprPipelineError(
            f"no log at {os.path.basename(log_path)} — the seed is unrecoverable without it")

    info = _parse_log(log_path)
    if info["version"] and info["version"] != SUPPORTED_UPR_VERSION:
        raise UprPipelineError(
            f"log reports UPR {info['version']}, this pipeline is pinned to "
            f"{SUPPORTED_UPR_VERSION}")
    info.update({
        "output": output_rom,
        "log": log_path,
        "sha1": _sha1(output_rom),
        "source_sha1": _sha1(source_rom),
    })
    return info


def _check_content(source_rom: str, output_rom: str) -> dict:
    """Scan the output and refuse anything that moved data the rules depend on.

    The SOURCE ROM is the canon here, not a table shipped with SLink: it is by definition
    what this output was made from, so a difference is attributable to the randomizer
    rather than to a stale reference. Base stats and types must be untouched -- UPR rewrites
    every base-stat record on every save, but value-identically when base-stat
    randomization is off, so any real difference means a forbidden setting was enabled.
    """
    with open(source_rom, "rb") as f:
        src = f.read()
    with open(output_rom, "rb") as f:
        out = f.read()
    try:
        src_ident, out_ident = identify(src), identify(out)
        if src_ident["variant"] != out_ident["variant"]:
            raise UprPipelineError(
                f"output is {out_ident['variant']} but the source was {src_ident['variant']}")
        if not src_ident["clean"]:
            raise UprPipelineError(
                f"source ROM is not a clean dump ({src_ident['sha1']}); randomize from a "
                f"clean cartridge so the result is reproducible")
        profile = scan(out)
        if scan_base_stats(out) != scan_base_stats(src):
            raise UprPipelineError(
                "base stats or types differ from the source — a setting that changes data "
                "the Soul Link rules read was enabled")
    except RomScanError as exc:
        raise UprPipelineError(f"the randomized ROM could not be scanned: {exc}") from exc
    return profile


def prepare_pair(jar: str, settings_path: str, sources: dict[str, str], out_dir: str,
                 java: str = "java") -> dict:
    """Randomize one ROM per player and prove the pair is usable.

    ``sources`` maps player id -> clean ROM path; the two may be different titles (a Red/Blue
    pairing is normal) but must use the SAME settings file.
    """
    if set(sources) != {"a", "b"}:
        raise UprPipelineError(f"expected sources for players a and b, got {sorted(sources)}")

    try:
        declared = load(settings_path)
    except UprSettingsError as exc:
        raise UprPipelineError(f"settings file unreadable: {exc}") from exc
    if not declared["version_matches"]:
        raise UprPipelineError(
            f"settings file is version {declared['version']}, not {SUPPORTED_UPR_VERSION}'s. "
            f"UPR would silently update it, and an updated file is not the file the other "
            f"player used")
    if bad := forbidden_enabled(declared):
        raise UprPipelineError(
            f"these settings change data the Soul Link rules read: {', '.join(bad)}")

    os.makedirs(out_dir, exist_ok=True)
    results: dict[str, dict] = {}
    for player in ("a", "b"):
        out = os.path.join(out_dir, f"{player}_randomized.gbc")
        info = randomize(jar, settings_path, sources[player], out, java=java)
        try:
            effective = parse_settings_string(info["settings_string"])
        except UprSettingsError as exc:
            raise UprPipelineError(
                f"player {player}: the log's settings string is unreadable: {exc}") from exc
        # tweakForRom may have changed things; what matters is that it did not touch the
        # allowlist and did not enable anything forbidden.
        if bad := forbidden_enabled(effective):
            raise UprPipelineError(
                f"player {player}: after tweakForRom the run would randomize {', '.join(bad)}")
        info["categories"] = sorted(categories_enabled(effective))
        info["content_profile"] = _check_content(sources[player], info["output"])
        results[player] = info

    if results["a"]["seed"] == results["b"]["seed"]:
        raise UprPipelineError(
            f"both players got seed {results['a']['seed']} — the point of the pairing is "
            f"that their tables differ")
    if results["a"]["categories"] != results["b"]["categories"]:
        raise UprPipelineError(
            f"the two ROMs ended up with different categories randomized: "
            f"{results['a']['categories']} vs {results['b']['categories']}")

    from server.adapters.gen1_rom_scan import fingerprint_rom, profile_hash
    for player in ("a", "b"):
        results[player]["content_hash"] = profile_hash(results[player]["content_profile"])
        # The fingerprint is the CLIENT-reproducible one: it covers only the tables a
        # running client can read out of its own cartridge, which is what makes it usable
        # as the admission check. content_hash is broader and no client could match it.
        with open(results[player]["output"], "rb") as f:
            results[player]["fingerprint"] = fingerprint_rom(f.read())
        del results[player]["content_profile"]        # large; the hash is what is kept
    if results["a"]["content_hash"] == results["b"]["content_hash"]:
        raise UprPipelineError(
            "both ROMs scanned to identical content despite different seeds — the "
            "randomization did not take effect")

    return {
        "upr_version": SUPPORTED_UPR_VERSION,
        "settings_sha256": hashlib.sha256(
            open(settings_path, "rb").read()).hexdigest(),
        "categories": results["a"]["categories"],
        "players": results,
    }
