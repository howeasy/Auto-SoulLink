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

import functools
import hashlib
import json
import os
import re
import shutil
import subprocess

from server import upr_gen3_write_domain, upr_polished_write_domain
from server.adapters import variant_label
from server.adapters.gen1_rom_scan import (
    GEN1_ROM_SIZE,
    RomScanError,
    evolution_graph,
    identify,
    profile_hash,
    scan,
    scan_base_stats,
)
from server.adapters.gen3_rom_tables import (
    gen3_content_fingerprint,
    normalised_species_rules,
)
from server.adapters.polished_rom_scan import (
    Rom as PolishedRom,
    RomScanError as PolishedRomScanError,
    identify as polished_identify,
)
from server.upr_settings import (
    FAMILY_EMERALD,
    FAMILY_FRLG,
    FAMILY_POLISHED,
    FAMILY_PURE,
    FAMILY_VANILLA,
    GEN3_FAMILIES,
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
# FireRed / LeafGreen needs the fork jar too (docs/gen3/research/randomized_gen3_design.md §6
# R3): ACCEPTED_UPR_VERSIONS admits the stock 4.6.1 release, but only the fork's Gen 3 handler
# is reviewed for this pipeline's write-domain assumptions -- the stock jar is refused by name
# rather than merely by an absent entry (it does have Gen 3 entries; it is untested here).
FRLG_RANDOMIZER_REFUSAL = (
    "FireRed / LeafGreen randomization needs SLink's UPR fork jar (4.6.1-slink3, fork revision 3; "
    "build it with tools/build_upr_fork.py) — the stock 4.6.1 jar is not accepted for this family."
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

# Polished Crystal v3.2.3: its own Gen 2 family (upr_settings.FAMILY_POLISHED, server/adapters/gen2_polished.py),
# recognised by the exact sha1s polished_rom_scan pins: the release (data/polished_sources.lock.json) and the SLink
# companion overlay (data/polished/overlay_provenance.json). It randomizes the OVERLAY (cartridges.py applies the
# UPS first) on a fork jar whose polished_offsets.ini has an entry for the source's header checksum. The pipeline
# below is complete; POLISHED_RANDOMIZER_ENABLED keeps every Manager path refusing it until the Polished client
# exists (flip it with that card; manager.py's NON_RANDOMIZABLE_GAMES row goes with it).
POLISHED_VARIANT = "Polished Crystal"
POLISHED_RANDOMIZER_ENABLED = False
POLISHED_RANDOMIZER_REFUSAL = "Polished Crystal randomizer support is coming via the UPR fork; turn Randomize off"
POLISHED_JAR_REFUSAL = (
    "Polished Crystal randomization needs SLink's UPR fork jar with a Polished Crystal entry for this "
    "cartridge's header checksum (tools/build_upr_fork.py, patch/upr)")

# The Emerald Expansion (pokeemerald-expansion, gen3_exp pack) is a 32 MiB BUILD, not a dump: it
# is recognised by the exact sha1 its pack pins, never by header, so the 16 MiB Gen 3 gates
# below (and every other 32 MiB BPEE) stay refused. It has no randomizer and no companion.
FAMILY_GEN3_EXP = "gen3_exp"
EXPANSION_VARIANT = "Emerald Expansion"
EXPANSION_REFUSAL = ("The Emerald Expansion has no randomizer and no companion patch (it is a prebuilt "
                     "reference ROM); turn Randomize and Companion off")


def _is_slink_polished_overlay(rom: bytes) -> bool:
    """The structure patch 0019's PolishedCrystalRomHandler.isSlinkOverlay tests: the moved DelayFrame lead-in at
    $0070, the `call $0070` rewrite at $0DA8, and a non-empty bank $7E (the release has it all $FF)."""
    return (len(rom) == 0x200000 and rom[0x70:0x77] == bytes.fromhex("f044e0d7afe08f")
            and rom[0xDA8:0xDAF] == bytes.fromhex("cd700000000000") and any(b != 0xFF for b in rom[0x1F8000:0x1FC000]))


def jar_supports_polished(jar: str, rom: bytes) -> bool:
    """The fork's PolishedCrystalRomHandler matches the release by an EXACT header checksum, and (patch 0019) the
    SLink overlay by structure with an ini section whose CRCInHeader is -1 (an overlay rebuild changes its own header
    checksum, so it cannot be pinned). A jar without a matching entry would fail inside Java ("unsupported ROM");
    say so first."""
    import zipfile
    try:
        with zipfile.ZipFile(jar) as zf:
            text = zf.read("com/dabomstew/pkrandom/config/polished_offsets.ini").decode("utf-8", "replace")
    except (OSError, KeyError, zipfile.BadZipFile):
        return False
    pinned = {int(m, 0) for m in re.findall(r"^CRCInHeader=(0x[0-9A-Fa-f]+|\d+)", text, flags=re.MULTILINE)}
    if _is_slink_polished_overlay(rom):
        return re.search(r"^CRCInHeader=-1\s*$", text, flags=re.MULTILINE) is not None
    return (rom[0x14E] << 8 | rom[0x14F]) in pinned     # read big-endian, as the handler does


@functools.cache
def _expansion_sha1() -> str:
    with open(os.path.join(_REPO, "data", "games", "gen3_exp", "28877d73", "profile.json"), encoding="utf-8") as fh:
        return json.load(fh)["source"]["rom_sha1"].lower()


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
    """The randomizer family the pair belongs to (upr_settings.FAMILY_* incl. FR/LG and Emerald,
    or FAMILY_GEN2); any cross-family mix is refused because the two would need different
    contracts and could not link."""
    gen2 = _gen2_clean_sha1s()
    families = {}
    for pid, path in sources.items():
        with open(path, "rb") as f:
            rom = f.read()
        if hashlib.sha1(rom).hexdigest() == _expansion_sha1():
            families[pid] = FAMILY_GEN3_EXP
            continue
        if title := gen3_title(rom):
            families[pid] = FAMILY_EMERALD if title == "emerald" else FAMILY_FRLG
            continue
        if hashlib.sha1(rom).hexdigest() in gen2:
            families[pid] = FAMILY_GEN2
            continue
        if polished_identify(rom):                       # release or companion overlay
            families[pid] = FAMILY_POLISHED
            continue
        ident = identify(rom)
        families[pid] = FAMILY_PURE if ident.get("foundation") == "gen1_purergb" else FAMILY_VANILLA
    if len(set(families.values())) != 1:
        raise UprPipelineError(
            f"the two ROMs are different families ({families}); a cartridge only pairs with "
            f"another of its own family (vanilla Gen 1, pureRGB, Gen 2, Polished Crystal, FireRed / LeafGreen, Emerald, "
            f"Emerald Expansion)")
    return next(iter(families.values()))


class UprPipelineError(Exception):
    """The pair could not be produced, or could not be trusted once produced."""


# ── Gen 3: FireRed / LeafGreen (docs/gen3/research/randomized_gen3_design.md §4, §6 R3) ──
# The clean pins, engine sites and write-checkpoint anchors are the gen3_frlg pack's own
# data, so a re-pinned site is re-asserted here with no edit. A GBA dump is 16 MiB; the
# header game code at 0xAC names the title and 0xBC is the revision (the pins are rev 0).
GEN3_ROM_SIZE = 16 << 20
GEN3_CODES = {b"BPRE": "firered", b"BPGE": "leafgreen", b"BPEE": "emerald"}
EMERALD_RANDOMIZER_REFUSAL = "Emerald randomization needs the current SLink fork jar (tools/build_upr_fork.py)"
GEN3_TITLE_WORDS = {"firered": "FireRed", "leafgreen": "LeafGreen", "emerald": "Emerald"}
_GEN3_PACK = os.path.join(_REPO, "data", "games", "gen3_frlg")
# gSpeciesInfo row (pret include/pokemon.h SpeciesInfo, 28 bytes): the fields a Soul Link
# rule or the calc reads -- base stats 0-5, types 6-7, growth rate 19, abilities 22-23. The
# catch rate (8) and the held items (12-15) are NOT here: the minimum-catch-rate and the
# (open, ruling 31) wild-held-item options legitimately rewrite them.


def _gen3_pack(name: str) -> dict:
    with open(os.path.join(_GEN3_PACK, name), encoding="utf-8") as f:
        return json.load(f)


def _gen3_pack_for_title(title: str, name: str) -> dict:
    if title != "emerald":
        return _gen3_pack(name)
    with open(os.path.join(_REPO, "data/games/gen3_emerald", name), encoding="utf-8") as f:
        return json.load(f)


def gen3_title(rom: bytes) -> str | None:
    """A supported 16 MiB English rev-0 FR/LG/Emerald header, else None."""
    if len(rom) != GEN3_ROM_SIZE or rom[0xBC] != 0:
        return None
    return GEN3_CODES.get(bytes(rom[0xAC:0xB0]))


def gen3_identify(rom: bytes) -> dict | None:
    """{title, kind, pinned} for an FR/LG cartridge (kind clean = the pinned dump), else None."""
    title = gen3_title(rom)
    if title is None:
        return None
    pin = _gen3_pack_for_title(title, "engine_signals.json")["titles"][title]["artifacts"]["clean"]["rom_sha1"]
    pinned = hashlib.sha1(rom).hexdigest() == pin.lower()
    return {"title": title, "kind": "clean" if pinned else "rand", "pinned": pinned}


def gen3_site_mismatches(rom: bytes, title: str) -> list[str]:
    """Every engine site (and its context window) and every write-checkpoint anchor of the
    clean artifact whose bytes differ in ``rom``. The client admits a randomized cartridge by
    these very anchors and hooks these very sites (lua/gen3/entry.lua), so a UPR setting that
    touched one would break the write safety the whole Gen 3 lane rests on; empty = intact."""
    bad = []
    sites = _gen3_pack_for_title(title, "engine_signals.json")["titles"][title]["artifacts"]["clean"]["sites"]
    for kind, site in sites.items():
        # ("context", None) is legitimate -- most sites have none, so it is skipped; a "site"
        # record missing its own expected_hex is a malformed pack and must refuse, not skip.
        for label, rec, optional in (("site", site, False), ("context", site.get("context"), True)):
            if rec is None:
                if optional:
                    continue
                raise UprPipelineError(f"engine_signals.json: {kind} site for {title} is missing")
            if not rec.get("expected_hex"):   # absent OR empty: "" would compare b"" == b"" (fail-open)
                raise UprPipelineError(
                    f"engine_signals.json: {kind} {label} for {title} has no expected_hex")
            if "rom_offset" not in rec:
                raise UprPipelineError(
                    f"engine_signals.json: {kind} {label} for {title} has no rom_offset")
            want = bytes.fromhex(rec["expected_hex"])
            off = rec["rom_offset"]
            if rom[off:off + len(want)] != want:
                bad.append(f"{kind} {label} @0x{off:06X}")
    anchors = _gen3_pack_for_title(title, "write_checkpoint.json")[title]["anchors"]
    for name, a in anchors.items():
        clean = a.get("expected_hex", {}).get("clean") if isinstance(a.get("expected_hex"), dict) else None
        if clean is None:
            raise UprPipelineError(
                f"write_checkpoint.json: anchor {name!r} for {title} has no expected_hex.clean")
        if "rom_offset" not in a:
            raise UprPipelineError(
                f"write_checkpoint.json: anchor {name!r} for {title} has no rom_offset")
        want = bytes.fromhex(clean)
        off = a["rom_offset"]
        if rom[off:off + len(want)] != want:
            bad.append(f"checkpoint anchor {name} @0x{off:06X}")
    return bad


def _gen3_species_rules(rom: bytes, title: str) -> bytes:
    from server.adapters import gen3_rom_tables

    try:
        head = gen3_rom_tables.table_symbols(title, symbol_dir=gen3_rom_tables.SYMBOL_DIR)["gSpeciesInfo"]
        raw = gen3_rom_tables._Rom(rom).read(head["address"], head["size"], "gSpeciesInfo")
        return normalised_species_rules(raw, title)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise UprPipelineError(f"gSpeciesInfo could not be read: {exc}") from exc


def gen3_fingerprint_rom(rom: bytes) -> str:
    from server.adapters.gen3_rom_tables import decode_rom_tables
    title = gen3_title(rom)
    if title is None:
        raise UprPipelineError("not an English rev-0 FireRed / LeafGreen cartridge")
    return gen3_content_fingerprint(decode_rom_tables(rom, title))


def fingerprint_any(rom: bytes) -> str:
    """The contract fingerprint for either generation's cartridge."""
    if gen3_title(rom):
        return gen3_fingerprint_rom(rom)
    from server.adapters.gen1_rom_scan import fingerprint_rom
    return fingerprint_rom(rom)


def _check_content_gen3(source_rom: str, output_rom: str) -> dict:
    """The Gen 3 _check_content: same title, a pinned source, every engine site and checkpoint
    anchor byte-identical on the OUTPUT (the analogue of T6), and the rule tables -- species
    info rule fields and the evolution graph -- equal to the source's. Returns the decode."""
    from server.adapters.gen3_rom_tables import decode_rom_tables
    with open(source_rom, "rb") as f:
        src = f.read()
    with open(output_rom, "rb") as f:
        out = f.read()
    si, oi = gen3_identify(src), gen3_identify(out)
    if si is None or not si["pinned"]:
        raise UprPipelineError("source ROM is not a pinned FireRed / LeafGreen / Emerald dump; randomize "
                               "from a clean cartridge so the result is reproducible")
    if oi is None or oi["title"] != si["title"]:
        raise UprPipelineError(f"output is not {GEN3_TITLE_WORDS[si['title']]} any more")
    if bad := gen3_site_mismatches(out, si["title"]):
        raise UprPipelineError(
            f"the randomizer changed {len(bad)} engine site / checkpoint byte range(s) "
            f"({', '.join(bad[:6])}); SLink hooks and admits by these, so the output is refused")
    if _gen3_species_rules(out, si["title"]) != _gen3_species_rules(src, si["title"]):
        raise UprPipelineError(
            "base stats, types, growth rates, gender ratios or abilities differ from the source — a setting "
            "that changes data the Soul Link rules read was enabled")
    try:
        tables = decode_rom_tables(out, si["title"])
        evolutions = decode_rom_tables(src, si["title"])["evolutions"]
    except ValueError as exc:
        raise UprPipelineError(f"the randomized ROM could not be decoded: {exc}") from exc
    if tables["evolutions"] != evolutions:
        raise UprPipelineError(
            "evolution targets differ from the source — evolution randomization was enabled, "
            "and the species clause reads a vanilla family table")
    return tables


def _polished_rules(tables: dict) -> tuple[list, list, list]:
    """(base data without the catch rate, evolutions, learnsets) per record 1..337. The catch rate is
    the one base-data byte an allowed option (minimum catch rate) rewrites; no Soul Link rule reads it."""
    stats = [{k: v for k, v in rec.items() if k != "catch_rate"} for rec in tables["base_stats"]]
    return stats, [e["evolutions"] for e in tables["evos_attacks"]], [e["learnset"] for e in tables["evos_attacks"]]


def _check_content_polished(source_rom: str, output_rom: str) -> dict:
    """The Polished _check_content: a pinned source (release or companion overlay), the same cartridge
    (size and header unchanged), and base data, types, the evolution graph and the level-up learnsets
    equal to the source's, compared as decoded records (server/adapters/polished_rom_scan.py). Returns
    the output's table scan for the content hash."""
    with open(source_rom, "rb") as f:
        src = f.read()
    with open(output_rom, "rb") as f:
        out = f.read()
    if polished_identify(src) is None:
        raise UprPipelineError("source ROM is not the pinned Polished Crystal 3.2.3 release or its companion "
                               "overlay; randomize from a pinned cartridge so the result is reproducible")
    if len(out) != len(src) or out[0x134:0x150] != src[0x134:0x150]:
        raise UprPipelineError("output is not Polished Crystal any more (size or header changed)")
    try:
        scan = PolishedRom(out, pinned=False).scan_all()
        (s_stats, s_evos, s_moves), (o_stats, o_evos, o_moves) = (
            _polished_rules(PolishedRom(src).rule_tables()), _polished_rules(scan))
    except PolishedRomScanError as exc:
        raise UprPipelineError(f"the randomized ROM could not be decoded: {exc}") from exc
    if o_stats != s_stats:
        raise UprPipelineError(
            "base stats or types differ from the source — a setting that changes data the Soul Link "
            "rules read was enabled")
    if o_evos != s_evos:
        raise UprPipelineError(
            "evolution targets differ from the source — evolution randomization was enabled, and the "
            "species clause reads a vanilla family table")
    if o_moves != s_moves:
        raise UprPipelineError("level-up movesets differ from the source — moveset randomization was enabled")
    return scan


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
        if info["sha1"] == _expansion_sha1():
            info.update(family=FAMILY_GEN3_EXP, kind="clean", clean=True, variant=EXPANSION_VARIANT,
                        title=f"{EXPANSION_VARIANT} · {KIND_WORDS['clean']}")
            return info
        if rom[0xAC:0xB0] == b"BPEE" and gen3_title(rom) is None:
            info.update(clean=False, title="Emerald header is not a supported 16 MiB revision-0 cartridge")
            return info
        if g3 := gen3_identify(rom):
            info.update(family=FAMILY_EMERALD if g3["title"] == "emerald" else FAMILY_FRLG,
                        kind=g3["kind"], clean=g3["pinned"],
                        variant=GEN3_TITLE_WORDS[g3["title"]])
            info["title"] = f"{info['variant']} · {KIND_WORDS.get(g3['kind'], g3['kind'])}"
            return info
        if pol := polished_identify(rom):
            # Recognised, but not offered: there is no Polished client to run it yet (lua/gen2/entry.lua stops at
            # admission), so every provisioning path refuses it. Flip clean back on with the client card.
            info.update(family=FAMILY_POLISHED, kind=pol["kind"], clean=False, variant=POLISHED_VARIANT,
                        title=f"{POLISHED_VARIANT} 3.2.3 (the SLink client for it is not ready yet)")
            return info
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
    with open(source_rom, "rb") as f:
        src_bytes = f.read()
    g3 = gen3_title(src_bytes)
    ext = ".gba" if g3 else ".gbc"
    if not output_rom.lower().endswith(ext):
        # Not a style preference: UPR APPENDS its handler's extension to anything else, so
        # the artifact would not be where the caller thinks it is.
        raise UprPipelineError(f"output must end in {ext}, got {output_rom!r}")
    pol = None if g3 else polished_identify(src_bytes)   # never the Gen 1 identify() on Polished
    src_ident = {"kind": "clean"} if g3 else pol or identify(src_bytes)
    if pol and not (jar_is_fork(jar) and jar_supports_polished(jar, src_bytes)):
        raise UprPipelineError(POLISHED_JAR_REFUSAL)
    if src_ident.get("foundation") == "gen1_purergb" and not jar_is_fork(jar):
        raise UprPipelineError(PUREGB_RANDOMIZER_REFUSAL)
    if g3 and not jar_is_fork(jar):
        raise UprPipelineError(EMERALD_RANDOMIZER_REFUSAL if g3 == "emerald" else FRLG_RANDOMIZER_REFUSAL)
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
    if odd := unexpected_settings(declared, family):
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
    ext = ".gba" if family in GEN3_FAMILIES else ".gbc"
    for player in ("a", "b"):
        out = os.path.join(out_dir, f"{player}_randomized{ext}")
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
        fam = (family,) if family in (*GEN3_FAMILIES, FAMILY_POLISHED) else ()    # Gen 1 keeps its call shape
        info["categories"] = sorted(categories_enabled(effective, *fam))
        info["spec"] = spec_from_parsed(effective, *fam)
        if family == FAMILY_POLISHED:
            scan = _check_content_polished(sources[player], info["output"])
            info["write_domain"] = upr_polished_write_domain.check_output(sources[player], info["output"])
            # no client-reproducible fingerprint yet (the Polished client card); the content hash covers
            # the decoded tables, as Gen 1's does
            info["content_hash"], info["fingerprint"] = profile_hash(scan), ""
            results[player] = info
            continue
        if family in GEN3_FAMILIES:
            tables = _check_content_gen3(sources[player], info["output"])
            info["sites_intact"] = True        # _check_content_gen3 refuses otherwise
            info["write_domain"] = upr_gen3_write_domain.check_output(
                sources[player], info["output"], info["spec"], jar=jar)
            info["content_hash"] = info["fingerprint"] = gen3_content_fingerprint(tables)
            results[player] = info
            continue
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

    from server.adapters.gen1_rom_scan import fingerprint_rom
    for player in ("a", "b") if family not in (*GEN3_FAMILIES, FAMILY_POLISHED) else ():
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
