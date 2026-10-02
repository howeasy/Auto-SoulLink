"""Provision a run's cartridges, preserving each family's patch/randomizer order.

Game identity and patch facts belong to the scanner, patch registry and overlay
admission tooling. This module owns only their ordering and the final-file contract.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from patch.gen1.tools import inject
from patch.tools.make_ups import ups_apply
from server import patcher, upr_pipeline
from server.adapters.gen1_rom_scan import RomScanError, identify
from server.upr_settings import FAMILY_EMERALD, FAMILY_PURE, FAMILY_VANILLA, GEN3_FAMILIES
from tools.gen1_playthrough import REPO, _overlay_admission_row


class CartridgeError(Exception):
    """The selected cartridges could not be provisioned; the message is the refusal."""


def _vanilla_target(data: bytes) -> dict:
    md5 = hashlib.md5(data).hexdigest()
    target = next((t for t in patcher.TARGETS.values() if t["base_md5"] == md5), None)
    if target is None:
        # patcher.TARGETS deliberately excludes Yellow: it has zero free WRAM.
        raise CartridgeError(
            "no companion patch for this cartridge (Red, Blue and Gold/Silver/Crystal have one; "
            "Yellow has zero free WRAM); "
            "turn Companion off or choose a supported cartridge")
    return target


def _companion(data: bytes, family: str, info: dict) -> bytes:
    if family == FAMILY_PURE:
        if info["kind"] == "overlay":
            return data
        # Reuse the playthrough tool's admission lookup and its clean + UPS proof,
        # but apply to the user's picked bytes without requiring a separate ROM cache.
        want, entry = _overlay_admission_row(identify(data)["variant"])
        out = ups_apply(data, (Path(REPO) / entry["ups"]).read_bytes())
        if hashlib.sha1(out).hexdigest() != want:
            raise CartridgeError("companion UPS did not produce the admitted pureRGB overlay; "
                                 "restore the patch matching admission_overlay.json")
        return out
    target = _vanilla_target(data)
    out = ups_apply(data, Path(patcher.patch_path(target["slug"])).read_bytes())
    if hashlib.md5(out).hexdigest() != target["patched_md5"]:
        raise CartridgeError("companion UPS does not match the patch registry; restore the "
                             "published companion patch")
    return out


def provision(run_dir: str, sources: dict[str, str], *, companion: bool,
              randomize: dict | None, jar: str = "") -> dict:
    """Write a.<ext>/b.<ext> under run_dir/roms from two pinned, same-family sources.

    The extension is the SOURCE's: BizHawk picks the system by database hit first and by
    extension second (PLAN A15), and a randomized or overlay ROM is never in the database,
    so a pure cartridge named .gb would run on the DMG core in mono. Red/Blue dumps are .gb
    (the DMG core, where the client is proven), Yellow and pureRGB are .gbc.

    Vanilla randomizes clean bytes before structural injection; pureRGB randomizes
    the admitted overlay after UPS application. Only randomized runs get a contract,
    and that contract fingerprints and hashes the final handed-out cartridges.
    ``randomize`` is None or {"settings_path": <Manager-written .rnqs path>}.
    """
    try:
        return _provision(run_dir, sources, companion=companion, randomize=randomize, jar=jar)
    except (upr_pipeline.UprPipelineError, RomScanError, inject.InjectError,
            OSError, ValueError) as exc:
        raise CartridgeError(str(exc)) from exc


def _provision(run_dir, sources, *, companion, randomize, jar):
    if set(sources) != {"a", "b"}:
        raise CartridgeError("choose a cartridge for each of players a and b")
    # Pinning is independent of the jar: pureRGB needs no randomizer for a copy/UPS.
    infos = {pid: upr_pipeline.describe_rom(path, jar_fork=True)
             for pid, path in sources.items()}
    for pid, info in infos.items():
        if not info["clean"]:
            raise CartridgeError(f"player {pid}: choose a pinned cartridge; "
                                 f"{info['title'] or 'source ROM not found'}")
    family = upr_pipeline.family_of(sources)
    data = {pid: Path(path).read_bytes() for pid, path in sources.items()}
    if family == upr_pipeline.FAMILY_GEN3_EXP and (companion or randomize is not None):
        raise CartridgeError(upr_pipeline.EXPANSION_REFUSAL)
    if companion and family == FAMILY_VANILLA:
        for rom in data.values():
            _vanilla_target(rom)  # Yellow must refuse before either randomizer starts.
    if randomize is not None and family == upr_pipeline.FAMILY_GEN2:
        raise CartridgeError(
            "Gen 2 has no randomizer support; turn Randomize off to prepare companion "
            "cartridges only")
    if randomize is not None:
        if not isinstance(randomize, dict) or not randomize.get("settings_path"):
            raise CartridgeError("randomize needs settings_path pointing to a .rnqs file")
        jar = jar or upr_pipeline.find_upr_jar()
        if not jar:
            raise CartridgeError("UPR jar not found; choose PokeRandoZX.jar or set SLINK_UPR_JAR")
        if not upr_pipeline.jar_is_trusted(jar):   # before any patching or Java
            raise CartridgeError(upr_pipeline.untrusted_jar_message(jar))
        if family == FAMILY_PURE and not upr_pipeline.jar_is_fork(jar):
            raise CartridgeError(upr_pipeline.PUREGB_RANDOMIZER_REFUSAL)
        if family in GEN3_FAMILIES and not upr_pipeline.jar_is_fork(jar):
            raise CartridgeError(upr_pipeline.EMERALD_RANDOMIZER_REFUSAL if family == FAMILY_EMERALD
                                 else upr_pipeline.FRLG_RANDOMIZER_REFUSAL)
    if companion and (family == FAMILY_PURE or randomize is None):
        data = {pid: _companion(rom, family, infos[pid]) for pid, rom in data.items()}

    directory = Path(run_dir).resolve()
    roms = directory / "roms"
    outputs = {pid: roms / f"{pid}{Path(path).suffix.lower() or '.gb'}" for pid, path in sources.items()}
    # Never replace the picked original, including through a symlink or hard link.
    destinations = list(outputs.values())
    if randomize is not None:
        ext = ".gba" if family in GEN3_FAMILIES else ".gbc"
        destinations.extend(roms / f"{pid}_randomized{ext}" for pid in sources)
        if companion and family == FAMILY_PURE:
            destinations.extend(roms / f"{pid}_companion.gbc" for pid in sources)
    for output in destinations:
        for source in sources.values():
            if output.resolve() == Path(source).resolve() or (
                    output.exists() and output.samefile(source)):
                raise CartridgeError("source is a run output; choose the original cartridge elsewhere")
    roms.mkdir(parents=True, exist_ok=True)
    randomized = None
    if randomize is not None:
        inputs = sources
        if companion and family == FAMILY_PURE:
            inputs = {}
            for pid, rom in data.items():
                staged = roms / f"{pid}_companion.gbc"
                staged.write_bytes(rom)
                inputs[pid] = str(staged)
        randomized = upr_pipeline.prepare_pair(jar, randomize["settings_path"], inputs, str(roms))
        data = {pid: Path(row["output"]).read_bytes()
                for pid, row in randomized["players"].items()}
        if companion and family == FAMILY_VANILLA:
            data = {pid: inject.inject(rom) for pid, rom in data.items()}
        if companion and family in GEN3_FAMILIES:
            from tools.gen3_companions import overlay_randomized
            data = {pid: overlay_randomized(upr_pipeline.gen3_title(rom),Path(sources[pid]).read_bytes(),rom)
                    for pid,rom in data.items()}

    players = {}
    for pid, rom in data.items():
        has_companion = companion or infos[pid].get("kind") == "overlay"
        kind = "rand_companion" if has_companion else "rand"
        if randomize is None:
            kind = "companion" if has_companion else "clean"
        # fingerprint_any: Gen 3 cartridges use the Gen 3 fingerprint, Gen 1 the wild/fishing
        # scanner; Gen 2 and the Emerald Expansion never randomize, so there is no content_fingerprint to cross-check it
        # against at hello either.
        fingerprint = "" if family in (upr_pipeline.FAMILY_GEN2, upr_pipeline.FAMILY_GEN3_EXP) else upr_pipeline.fingerprint_any(rom)
        players[pid] = {"source": sources[pid], "source_title": infos[pid]["title"],
                        "output": str(outputs[pid]), "rom_sha1": hashlib.sha1(rom).hexdigest(),
                        "fingerprint": fingerprint, "kind": kind}
    # Finish both transforms and scans before publishing either final cartridge.
    for pid, rom in data.items():
        outputs[pid].write_bytes(rom)
    contract_path = directory / "rom_contract.json"
    if randomized is not None:
        contract = {k: randomized[k] for k in ("upr_version", "settings_sha256", "categories")}
        contract["players"] = {
            pid: {"fingerprint": player["fingerprint"], "rom_sha1": player["rom_sha1"],
                  "seed": str(randomized["players"][pid]["seed"])}
            for pid, player in players.items()}
        temporary = directory / "rom_contract.json.tmp"
        temporary.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
        temporary.replace(contract_path)
        randomized = {**randomized, "players": {
            pid: {k: v for k, v in row.items() if k != "output"}
            for pid, row in randomized["players"].items()}}
    else:
        # Re-provisioning without randomization must not retain an earlier admission pin.
        contract_path.unlink(missing_ok=True)
    return {"family": family, "companion": companion, "randomizer": randomized, "players": players}
