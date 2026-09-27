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
separate process. Two jars are accepted: the stock 4.6.1 release (vanilla Red/Blue/Yellow
only) and SLink's fork of it, ``4.6.1-slink3`` (built by tools/build_upr_fork.py from
.cache/slink-upr, docs/purergb/PLAN.md §6 M5), which is the only jar that may randomize the
pureRGB family: its entries are lossless and field-scoped, the stock jar has no entry for
those cartridges at all. The fork is recognised by the entries it carries, not by its name.

WHICH JAR MAY RUN AT ALL. ``java -jar`` runs whatever code the jar holds, and the jar path
can come from a browser, so a jar runs only when its SHA-256 is in data/upr_jars.json (the
SLink builds, labelled; tools/build_upr_fork.py --pin adds a new build). jar_is_trusted is
checked by randomize() before Java starts and reported by preflight(); jar_is_fork is a
separate capability check and says nothing about trust -- its INI marker is forgeable.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess

from server.adapters import variant_label
from server.adapters.gen1_rom_scan import (
    GEN1_ROM_SIZE,
    RomScanError,
    evolution_graph,
    identify,
    scan,
    scan_base_stats,
)
from server.upr_settings import (
    FAMILY_PURE,
    FAMILY_VANILLA,
    UprSettingsError,
    categories_enabled,
    forbidden_enabled,
    load,
    parse_settings_string,
    spec_from_parsed,
    summarize,
    unexpected_settings,
)

RANDOMIZE_TIMEOUT = 600

# pureRGB (game_id gen1_purergb) randomizes only on the fork jar: the stock jar has no
# entry for the cartridge and a hand-added one would repack base stats, evolutions and
# trainer AI on every save (docs/purergb/research/d1/FORK_BRIEF.md). With the stock jar the
# family stays greyed with this message.
# identify()'s `kind`, in the picker's words. The vanilla family has one pinned artifact
# per title, the clean dump; the pure family has two, the pinned v2.7.6 build and the SLink
# companion overlay (the native trade + START-menu panel linked in at source: README,
# "Companion overlay"), and the fork randomizes either as itself (A5). Anything else is a
# cartridge that was already changed -- the randomizer starts only from a pinned one.
KIND_WORDS = {
    "clean": "clean dump",
    "rand": "already modified, not a clean dump",
}
KIND_WORDS_PURE = {
    "clean": "pinned pureRGB v2.7.6 build",
    "overlay": "SLink companion overlay (native trade, START-menu panel, native sounds)",
    "rand": "already randomized",
    "rand_overlay": "already randomized (companion overlay)",
}

PUREGB_RANDOMIZER_REFUSAL = (
    "pureRGB randomization needs SLink's UPR fork jar (4.6.1-slink3, fork revision 3; build it with "
    "tools/build_upr_fork.py) — this jar is the stock 4.6.1 and has no pureRGB entry."
)
FORK_JAR_MARKER = b"[PureRed (U)]"
_SEED_RE = re.compile(r"^Random Seed:\s*(\d+)\s*$")
_SETTINGS_RE = re.compile(r"^Settings String:\s*(\S+)\s*$")
_VERSION_RE = re.compile(r"^Randomizer Version:\s*(\S+)\s*$")

SUPPORTED_UPR_VERSION = "4.6.1-slink3"        # the fork: every family
# The fork revision the pure sections must declare (SlinkForkRevision=, emitted by
# tools/gen_upr_gen1_ini.py). A pre-fix build of the fork carries the same clean CRCs and, until
# slink2, the same version string; it hangs on the similar-strength modes and crashes on global
# (review cx-25b25db1), so the cartridge CRC alone must never admit it. Revision 3 (slink3)
# is the first whose lossless entries honour the lower-case-names tweak; a slink2 jar would
# silently drop it in tweakForRom, so it is refused the same way slink1 was.
FORK_REVISION_REQUIRED = 3
STOCK_UPR_VERSION = "4.6.1"                   # the release jar: the vanilla family only
ACCEPTED_UPR_VERSIONS = (STOCK_UPR_VERSION, SUPPORTED_UPR_VERSION)


def jar_fork_revision(jar: str) -> int:
    """The SlinkForkRevision the jar's pure sections declare (0 for a stock jar or a fork
    older than the stamp)."""
    import re
    import zipfile
    try:
        with zipfile.ZipFile(jar) as zf:
            text = zf.read("com/dabomstew/pkrandom/config/gen1_offsets.ini").decode("utf-8", "replace")
    except (OSError, KeyError, zipfile.BadZipFile):
        return 0
    revs = [int(m) for m in re.findall(r"^SlinkForkRevision=(\d+)", text, flags=re.MULTILINE)]
    return min(revs) if revs else 0


_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
UPR_JAR_ALLOWLIST = os.path.join(_REPO, "data", "upr_jars.json")


def trusted_jars() -> dict[str, str]:
    """sha256 -> label of every jar allowed to run (data/upr_jars.json holds label ->
    sha256). Read on every call: a `build_upr_fork.py --pin` build is admitted without a
    Manager restart, and the file is a few hundred bytes."""
    try:
        with open(UPR_JAR_ALLOWLIST, encoding="utf-8") as f:
            return {str(h).lower(): label for label, h in json.load(f).items()}
    except (OSError, ValueError, AttributeError):
        return {}


def _is_remote(path: str) -> bool:
    """A UNC path (double-backslash host share, //host, the long-path UNC form) or a drive
    letter mapped to a network share. Either can serve one file to the hash and another
    to Java."""
    p = path.replace("/", "\\")
    if p.startswith("\\\\"):
        return True
    drive = os.path.splitdrive(p)[0]
    if os.name == "nt" and len(drive) == 2 and drive[1] == ":":
        import ctypes
        DRIVE_REMOTE = 4
        return ctypes.windll.kernel32.GetDriveTypeW(drive + "\\") == DRIVE_REMOTE
    return False


def jar_sha256(jar: str) -> str | None:
    """SHA-256 of the file the path really names (symlinks resolved), or None when it is
    not a readable regular file. A UNC path is refused before any I/O: a share the
    requester controls could serve one file to the hash and another to Java.
    ponytail: no (path, mtime, size) cache -- hashing the 1.1 MB jar takes ~1 ms."""
    if not jar or _is_remote(str(jar)):
        return None
    real = os.path.realpath(jar)
    if _is_remote(real) or not os.path.isfile(real):
        return None
    h = hashlib.sha256()
    try:
        with open(real, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def jar_is_trusted(jar: str) -> bool:
    """True only for a jar whose SHA-256 is in data/upr_jars.json."""
    digest = jar_sha256(jar)
    return digest is not None and digest in trusted_jars()


def untrusted_jar_message(jar: str) -> str:
    digest = jar_sha256(jar)
    what = f"sha256 {digest}" if digest else "not a readable local file"
    return (f"unknown randomizer build: {jar} ({what}) is not one of the SLink UPR jars in "
            f"data/upr_jars.json, so Java was not started. Build the fork with "
            f"`python tools/build_upr_fork.py --pin`, or add the hash to data/upr_jars.json "
            f"if you trust this jar.")


def jar_is_fork(jar: str) -> bool:
    """True when this PokeRandoZX.jar is the REVIEWED SLink fork: it carries the pureRGB
    entries and every pure section declares at least FORK_REVISION_REQUIRED."""
    import zipfile
    try:
        with zipfile.ZipFile(jar) as zf:
            if FORK_JAR_MARKER not in zf.read("com/dabomstew/pkrandom/config/gen1_offsets.ini"):
                return False
    except (OSError, KeyError, zipfile.BadZipFile):
        return False
    return jar_fork_revision(jar) >= FORK_REVISION_REQUIRED


def jar_entry_crcs(jar: str) -> dict[str, int | None]:
    """Section name -> its CRCInHeader (None when the section has none) from the jar's Gen 1
    INI. UPR selects an entry by exact header CRC first, so a section whose CRC no longer
    matches the build it names (the overlay was rebuilt: patch 0006) is as good as absent."""
    import re
    import zipfile
    try:
        with zipfile.ZipFile(jar) as zf:
            text = zf.read("com/dabomstew/pkrandom/config/gen1_offsets.ini").decode("utf-8", "replace")
    except (OSError, KeyError, zipfile.BadZipFile):
        return {}
    out: dict[str, int | None] = {}
    name = None
    for line in text.splitlines():
        if m := re.match(r"^\[([^\]]+)\]", line):
            name = m[1]
            out[name] = None
        elif name and (m := re.match(r"^CRCInHeader=(0x[0-9A-Fa-f]+|\d+)", line.strip())):
            out[name] = int(m[1], 0)
    return out


# Gen 2 (Gold/Silver/Crystal): not a Gen 1 cartridge at all, and gen1_rom_scan.identify()
# assumes the Gen 1 layout, so it is never called on one -- recognised by sha1 instead,
# against its own per-title admission tables (the same SELECTED clean rows server/
# manager.py's OPTION_SUPPORT and server/cartridges.py's companion apply trust). Its own
# family: it never pairs with a Gen 1 cartridge, and (no randomizer support yet) never
# randomizes -- server/cartridges.py refuses that before any jar runs.
FAMILY_GEN2 = "gen2_gsc"
_GEN2_TITLES = ("crystal", "gold", "silver")


def _gen2_clean_sha1s() -> dict[str, str]:
    """sha1 -> title, for every SELECTED clean row across the three Gen 2 admission tables
    (data/games/gen2_<title>/admission.json). Read fresh each call: three small files, and
    an admission change (a new revision selected) must be picked up without a restart."""
    out = {}
    for title in _GEN2_TITLES:
        path = os.path.join(_REPO, "data", "games", f"gen2_{title}", "admission.json")
        with open(path, encoding="utf-8") as fh:
            for row in json.load(fh)["artifacts"]:
                if row["kind"] == "clean" and row["selection"] == "SELECTED":
                    out[row["sha1"]] = title
    return out


def jar_entries(jar: str) -> set[str]:
    """The Gen 1 INI section names a jar carries -- what it can randomize. The stock jar has
    the vanilla four; the SLink fork adds the three clean pure titles and, since patch 0003,
    the three companion-overlay builds (their header CRCs differ, so without their own entry
    UPR finds nothing and dies reading base stats)."""
    return set(jar_entry_crcs(jar))


def jar_entry_for(ident: dict) -> str | None:
    """The INI section a scanned pure artifact needs (None for a non-pure identity)."""
    if ident.get("foundation") != "gen1_purergb":
        return None
    from tools.upr_write_domain_diff import SECTION, entry_key
    return SECTION.get(entry_key(ident))


def jar_supports(jar: str, ident: dict) -> bool:
    """True when the jar carries the entry this artifact randomizes under, with the CRC of
    THIS build: a pure title needs its clean or overlay section and that section's
    CRCInHeader must equal the cartridge's header checksum (a stale section would let UPR
    fall through to the generic header match); anything else is the stock handler's business."""
    entry = jar_entry_for(ident)
    if entry is None:
        return True
    crcs = jar_entry_crcs(jar)
    if entry not in crcs:
        return False
    want = ident.get("header_checksum")
    return want is None or crcs[entry] == want


def family_of(sources: dict[str, str]) -> str:
    """The randomizer family the pair belongs to (upr_settings.FAMILY_* or FAMILY_GEN2); a
    pure/vanilla/Gen2 mix is refused because the two would need different contracts and
    could not link."""
    gen2 = _gen2_clean_sha1s()
    families = {}
    for pid, path in sources.items():
        with open(path, "rb") as f:
            rom = f.read()
        if hashlib.sha1(rom).hexdigest() in gen2:
            families[pid] = FAMILY_GEN2
            continue
        ident = identify(rom)
        families[pid] = FAMILY_PURE if ident.get("foundation") == "gen1_purergb" else FAMILY_VANILLA
    if len(set(families.values())) != 1:
        raise UprPipelineError(
            f"the two ROMs are different families ({families}); a cartridge only pairs with "
            f"another of its own family (vanilla Gen 1, pureRGB, Gen 2)")
    return next(iter(families.values()))


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


def find_upr_jar() -> str | None:
    """Absolute path to PokeRandoZX.jar, or None. Searches, in order: $SLINK_UPR_JAR,
    <repo>/PokeRandoZX.jar, <repo>/tools/, then .cache/slink-upr/ (the fork, preferred:
    it serves every family) and .cache/upr/ (the stock jar) walking upward -- a git
    worktree has no .cache of its own; it lives under the main repo's .claude/worktrees/."""
    env = os.environ.get("SLINK_UPR_JAR")
    if env and os.path.exists(env):
        return env
    repo = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    for cand in (os.path.join(repo, "PokeRandoZX.jar"),
                 os.path.join(repo, "tools", "PokeRandoZX.jar")):
        if os.path.exists(cand):
            return cand
    d = repo
    for _ in range(6):
        for sub in ("slink-upr", "upr"):
            cand = os.path.join(d, ".cache", sub, "PokeRandoZX.jar")
            if os.path.exists(cand):
                return cand
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def describe_rom(path: str, jar_fork: bool) -> dict:
    """What one ROM file is, for a picker or a preflight: present, and a PINNED artifact
    of a title the scanner knows -- a clean dump, or (pure family, A5) the byte-exact
    SLink companion overlay, which is randomized as an overlay. `clean` is that pinned
    verdict; the pure family needs the fork jar, and says so in `title` otherwise."""
    info = {"path": path, "exists": bool(path) and os.path.isfile(path), "clean": None, "title": ""}
    if not info["exists"]:
        return info
    try:
        with open(path, "rb") as f:
            rom = f.read()
        # the Manager's ROM scan dedups on this, so it reads each file once, not twice
        info["sha1"] = hashlib.sha1(rom).hexdigest()
        gen2_title = _gen2_clean_sha1s().get(info["sha1"])
        if gen2_title:
            info["family"], info["kind"], info["clean"] = FAMILY_GEN2, "clean", True
            info["variant"] = variant_label(gen2_title)
            info["title"] = f"{info['variant']} · {KIND_WORDS['clean']}"
            return info
        if len(rom) != GEN1_ROM_SIZE:
            info["clean"], info["title"] = False, "not a recognised cartridge (need a clean Red/Blue/Yellow or US Gold/Silver/Crystal 1.0 dump)"
            return info
        ident = identify(rom)
        # Which contract the cartridge belongs to: a pure pair and a vanilla pair are
        # different runs, and a run named up front admits one family only.
        pure = ident.get("foundation") == "gen1_purergb"
        info["family"] = FAMILY_PURE if pure else FAMILY_VANILLA
        info["kind"] = ident.get("kind", "clean")
        info["clean"] = bool(ident.get("pinned", ident.get("clean")))
        # `title` is what a person reads in the picker: the game, and which of the
        # cartridges of that game this is, in plain words (KIND_WORDS).
        words = KIND_WORDS_PURE if pure else KIND_WORDS
        info["variant"] = variant_label(ident["variant"])
        info["title"] = f"{info['variant']} · {words.get(info['kind'], info['kind'])}"
        if pure and not jar_fork:
            info["clean"], info["title"] = False, PUREGB_RANDOMIZER_REFUSAL
    except Exception as exc:                                         # noqa: BLE001
        info["clean"], info["title"] = False, f"unreadable: {exc}"
    return info


def preflight(jar: str, sources: dict[str, str], java: str = "java") -> dict:
    """Everything that can be checked in milliseconds before anything is spent: is the
    jar there, is Java on PATH, is each ROM present and pinned (describe_rom).
    randomize() checks the same things, but 600 s deep inside a worker."""
    out = {"jar": jar, "jar_found": bool(jar) and os.path.exists(jar),
           "java_found": bool(shutil.which(java)), "roms": {}, "ok": True}
    # trust (the jar's hash is pinned) is not the fork capability below: an unknown jar is
    # refused whatever it claims to be, and the page can say so before the button
    out["jar_trusted"] = out["jar_found"] and jar_is_trusted(jar)
    if out["jar_found"] and not out["jar_trusted"]:
        out["jar_error"] = untrusted_jar_message(jar)
    out["jar_fork"] = out["jar_found"] and jar_is_fork(jar)
    # the sections the jar can randomize under -- the Cartridges form checks a pure pick's
    # "<Variant> overlay (U)" entry here, before the button, instead of after a Java failure
    out["jar_entries"] = sorted(jar_entries(jar)) if out["jar_found"] else []
    for pid, path in sources.items():
        info = describe_rom(path, out["jar_fork"])
        out["roms"][pid] = info
        out["ok"] = out["ok"] and info["exists"] and bool(info["clean"])
    out["ok"] = out["ok"] and out["jar_trusted"] and out["java_found"]
    return out


def _run_bounded(argv: list, timeout: int) -> subprocess.CompletedProcess:
    """Run the jar with a hard bound. A randomizer that never terminates (review cx-795d1423
    #1: the similar-strength search on a zero-stat sentinel) must not hang the Manager's
    worker: on expiry the whole process tree is killed (java may have children; on Windows
    Popen.kill() reaches only the direct child) and the run is refused as a timeout."""
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # the cleanup is bounded too (review cx-758c671d #7): a kill that stalls or a
        # descendant that keeps the pipes open must not turn a refusal into a hang
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               capture_output=True, timeout=15)
            else:
                proc.kill()
            proc.communicate(timeout=15)
        except (subprocess.TimeoutExpired, OSError):
            pass
        raise UprPipelineError(
            f"UPR did not finish within {timeout} s and was killed -- these settings hang "
            f"the randomizer on this cartridge; the run is refused") from None
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


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
    with open(source_rom, "rb") as f:
        src_ident = identify(f.read())
    if src_ident.get("foundation") == "gen1_purergb" and not jar_is_fork(jar):
        raise UprPipelineError(PUREGB_RANDOMIZER_REFUSAL)
    if not jar_supports(jar, src_ident):
        raise UprPipelineError(
            f"this jar has no entry for the {src_ident.get('kind')} build of "
            f"{src_ident.get('variant')} ({jar_entry_for(src_ident)}, header CRC "
            f"{src_ident.get('header_checksum', 0):04X}); rebuild the SLink fork "
            f"(tools/build_upr_fork.py, patch/upr) -- UPR would otherwise fail reading "
            f"base stats, or fall back to the vanilla entry")

    # the one gate in front of every `java -jar`, last so nothing else can come between the
    # hash and the launch; Java is handed the real path that was hashed
    jar = os.path.realpath(jar)
    if not jar_is_trusted(jar):
        raise UprPipelineError(untrusted_jar_message(jar))
    before = set(os.listdir(os.path.dirname(os.path.abspath(output_rom)) or "."))
    proc = _run_bounded(
        [java, "-jar", jar, "cli", "-s", settings_path, "-i", source_rom,
         "-o", output_rom, "-l"], timeout)
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
    if info["version"] and info["version"] not in ACCEPTED_UPR_VERSIONS:
        raise UprPipelineError(
            f"log reports UPR {info['version']}, this pipeline is pinned to "
            f"{' / '.join(ACCEPTED_UPR_VERSIONS)}")
    info.update({
        "output": output_rom,
        "log": log_path,
        "sha1": _sha1(output_rom),
        "source_sha1": _sha1(source_rom),
        # provenance (A5): the admitted kind the source was, clean or overlay; the client
        # admits the output by that kind's anchors (rand / rand_overlay)
        "base_kind": src_ident.get("kind", "clean"),
    })
    return info


# identify()'s output kind -> the pinned kind it must have been randomized from.
BASE_KIND_OF = {"clean": "clean", "rand": "clean", "overlay": "overlay", "rand_overlay": "overlay"}


def _rule_bearing(base_stats: dict[int, dict]) -> dict[int, dict]:
    return {dex: {k: v for k, v in rec.items() if k != "catch_rate"}
            for dex, rec in base_stats.items()}


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
        if not src_ident.get("pinned", src_ident["clean"]):
            raise UprPipelineError(
                f"source ROM is not a clean dump ({src_ident['sha1']}); randomize from a "
                f"clean cartridge so the result is reproducible")
        if src_ident.get("kind", "clean") != BASE_KIND_OF.get(out_ident.get("kind", "clean")):
            raise UprPipelineError(
                f"output is a {out_ident.get('kind')} artifact but the source was "
                f"{src_ident.get('kind')} -- the randomizer changed a code byte")
        profile = scan(out)
        # Gen 1 keeps the catch rate inside the base-stats record, and the minimum-catch-
        # rate option legitimately raises it; no rule reads it, so it is not compared.
        if _rule_bearing(scan_base_stats(out)) != _rule_bearing(scan_base_stats(src)):
            raise UprPipelineError(
                "base stats or types differ from the source — a setting that changes data "
                "the Soul Link rules read was enabled")
        # EVOLUTIONS, COMPARED AS A GRAPH RATHER THAN AS BYTES.
        # UPR repacks and REPOINTS this whole region on every save (savingRom() ->
        # savePokemonStats() -> writeEvosAndMovesLearnt), so the bytes and the offsets
        # differ even on a wild-only run that changed nothing. Walking the pointer table
        # and comparing the logical edges is the only way to tell repacked from altered.
        #
        # This matters because `evo_family` -- which the species clause is built on -- reads
        # a table generated from the vanilla decomp. If a cartridge's evolutions were
        # randomized, SLink would enforce families that cartridge no longer has: blocking a
        # legal pair and permitting an illegal one, both silently.
        if evolution_graph(out) != evolution_graph(src):
            raise UprPipelineError(
                "evolution targets differ from the source — evolution randomization was "
                "enabled, and the species clause reads a vanilla family table, so the "
                "rules would be enforced against a game nobody is playing")
    except RomScanError as exc:
        raise UprPipelineError(f"the randomized ROM could not be scanned: {exc}") from exc
    return profile


def _audit_write_domain(source_rom: str, output_rom: str, spec: dict) -> dict:
    """T6 on the produced cartridge (docs/purergb/PLAN.md §6 M5): every byte the fork changed
    must lie inside the write domain of the categories that were enabled. _check_content only
    compares the rule-bearing tables; this is what proves the fork wrote NOTHING else -- a
    handler that touched a code byte or an unlisted table would pass the content check."""
    from tools.upr_write_domain_diff import audit, domains_for_spec, entry_key
    with open(source_rom, "rb") as f:
        clean = f.read()
    with open(output_rom, "rb") as f:
        out = f.read()
    cats = domains_for_spec(spec)         # every option, not just the six mode choices
    r = audit(entry_key(identify(clean)), clean, out, cats)
    if r["stray"]:
        shown = ", ".join(f"0x{i:06X}" for i in r["stray"][:8])
        raise UprPipelineError(
            f"the randomizer wrote {len(r['stray'])} byte(s) outside the write domain of "
            f"{sorted(cats) or 'nothing'} (first: {shown}); the output is refused")
    return {"changed": r["changed"], "categories": sorted(cats)}


def admit_settings(settings, family: str = FAMILY_VANILLA) -> dict:
    """Read a .rnqs (a path or its bytes) and admit it, or say exactly why not. The same
    three gates whether the file comes from a run about to randomize or from a player
    importing what they built in UPR's GUI: its version, the named dangers, and the
    allowlist. Returns the parse (load())."""
    try:
        declared = load(settings)
    except UprSettingsError as exc:
        raise UprPipelineError(f"settings file unreadable: {exc}") from exc
    if not declared["version_matches"]:
        raise UprPipelineError(
            f"settings file is version {declared['version']}, not {SUPPORTED_UPR_VERSION}'s. "
            f"UPR would silently update it, and an updated file is not the file the other "
            f"player used")
    if bad := forbidden_enabled(declared, family):
        raise UprPipelineError(
            f"these settings change data the Soul Link rules read: {', '.join(bad)}")
    # ALLOWLIST, not just the named dangers. forbidden_enabled can only reject what someone
    # thought to list, and UPR has well over a hundred options; this requires the file to be
    # one this project would itself produce. "Same settings, different seeds" is only
    # meaningful if both files come from the same known set, so an option we have never
    # reasoned about is outside it whether or not it turns out to matter.
    if odd := unexpected_settings(declared):
        raise UprPipelineError(
            "these settings are outside the supported set — SLink only runs configurations "
            "it can itself produce: " + "; ".join(odd))
    return declared


def prepare_pair(jar: str, settings_path: str, sources: dict[str, str], out_dir: str,
                 java: str = "java") -> dict:
    """Randomize one ROM per player and prove the pair is usable.

    ``sources`` maps player id -> clean ROM path; the two may be different titles (a Red/Blue
    pairing is normal) but must use the SAME settings file.
    """
    if set(sources) != {"a", "b"}:
        raise UprPipelineError(f"expected sources for players a and b, got {sorted(sources)}")

    for path in sources.values():
        if not os.path.isfile(path):
            raise UprPipelineError(f"source ROM not found: {path}")
    try:
        family = family_of(sources)
    except RomScanError as exc:
        raise UprPipelineError(f"source ROM could not be identified: {exc}") from exc
    admit_settings(settings_path, family)

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
        if bad := forbidden_enabled(effective, family):
            raise UprPipelineError(
                f"player {player}: after tweakForRom the run would randomize {', '.join(bad)}")
        info["categories"] = sorted(categories_enabled(effective))
        info["spec"] = spec_from_parsed(effective)
        info["content_profile"] = _check_content(sources[player], info["output"])
        if family == "gen1_purergb":              # upr_settings.FAMILY_PURE
            info["write_domain"] = _audit_write_domain(sources[player], info["output"], info["spec"])
        results[player] = info

    if results["a"]["seed"] == results["b"]["seed"]:
        raise UprPipelineError(
            f"both players got seed {results['a']['seed']} — the point of the pairing is "
            f"that their tables differ")
    if results["a"]["spec"] != results["b"]["spec"]:
        raise UprPipelineError(
            f"the two ROMs ended up with different settings applied: "
            f"{summarize(results['a']['spec'])} vs {summarize(results['b']['spec'])}")

    from server.adapters.gen1_rom_scan import fingerprint_rom, profile_hash
    for player in ("a", "b"):
        results[player]["content_hash"] = profile_hash(results[player]["content_profile"])
        # The fingerprint is the CLIENT-reproducible one: it covers only the tables a
        # running client can read out of its own cartridge, which is what makes it usable
        # as the admission check. content_hash is broader and no client could match it.
        with open(results[player]["output"], "rb") as f:
            results[player]["fingerprint"] = fingerprint_rom(f.read())
        del results[player]["content_profile"]        # large; the hash is what is kept
    # The produced BYTES must differ: content_hash covers only wild/fishing/base stats, so a
    # pair randomized in starters or trainers alone hashes identically (review cx-795d1423 #9).
    if results["a"]["sha1"] == results["b"]["sha1"]:
        raise UprPipelineError(
            "both ROMs came out byte-identical despite different seeds — the randomization "
            "did not take effect")

    if results["a"]["version"] != results["b"]["version"]:
        raise UprPipelineError(
            f"the two ROMs were made by different randomizer versions: "
            f"{results['a']['version']} vs {results['b']['version']}")

    return {
        "upr_version": results["a"]["version"] or SUPPORTED_UPR_VERSION,
        "family": family,
        "settings_sha256": hashlib.sha256(
            open(settings_path, "rb").read()).hexdigest(),
        "categories": results["a"]["categories"],
        "spec": results["a"]["spec"],
        "summary": summarize(results["a"]["spec"]),
        "players": results,
    }
