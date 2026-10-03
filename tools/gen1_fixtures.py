#!/usr/bin/env python3
"""Build tests/fixtures/gen1/<rom>_<target>.SaveRAM from REAL scripted play (F-6).

The previous fixtures were written byte-by-byte by a tool (level 5 with exp 0, OT "RST"):
not game states. This one cold-boots the cartridge in EmuHawk, plays NEW GAME -> starter ->
rival battle -> (chain) -> START/SAVE with ordinary buttons (lua/tests/test_gen1_scripted_gate.lua),
flushes SaveRAM, copies it into the fixture slot and qualifies it with the Python codec: the
game's main checksum, one decodable party mon whose exp matches its level on its growth curve.

    python tools/gen1_fixtures.py red town          # lab -> save (Oak's Lab, encounter-free)
    python tools/gen1_fixtures.py blue town --player b
    python tools/gen1_fixtures.py red battle        # lab -> parcel -> Route 1 (10,35) -> save, a ball in the bag

Each title resolves its own lab driver (lua/tests/gen1_scripted_play.lua): Red/Blue and Yellow
each walk their own route to Oak's Lab. One emulator lane; nothing else running.

    python tools/gen1_fixtures.py --qualify      # re-check the committed fixtures, no emulator

--qualify never touches EmuHawk: it reads tests/fixtures/gen1/*.SaveRAM, decodes each party
against the matching dump and classifies the result, so the fixture lane can be verified (and
a stale fixture detected) without a 15-minute emulator run. Exit 1 if any fixture is REFUSED.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

from server.adapters import gen1_codec as codec, gen1_rom_scan as scan  # noqa: E402

if __package__:
    from . import fixture_qualification as fixture_runner
else:
    import fixture_qualification as fixture_runner

GATE = "lua/tests/test_gen1_scripted_gate.lua"
CHAINS = {"town": "lab,save", "battle": "lab,parcel,route1,save", "town_ot2": "lab,save"}
# What scripted play's default title timing produces: the committed red_town/red_battle pair
# both carry it, and the A1 wrong-save leg needs a Red save that does NOT (tools/e2e_duo.py
# refuses a second-OT save whose id equals the original's).
DEFAULT_OT = 0x4190
# The run_gb_gate cold key each title's fixture is built on. The companion is REQUIRED for
# Red/Blue/pureRGB (owner 2026-10-02) and the harness refuses a clean one, so those titles boot
# their companion cartridge; Yellow has none and boots clean. The key's PATCHED row names the
# ROM and the SaveRAM file the emulator writes; the fixture keeps its title name.
COLD_KEY = {"red": "red_patched_cold", "blue": "blue_patched_cold", "yellow": "yellow_cold",
            "purered": "purered_overlay_cold", "pureblue": "pureblue_overlay_cold",
            "puregreen": "puregreen_overlay_cold"}
DUMP = {"red": "patch/build/gen1_red.gb", "blue": "patch/build/gen1_blue.gb",
        "yellow": "patch/build/gen1_yellow.gbc",
        "purered": "patch/build/gen1_purered.gbc", "pureblue": "patch/build/gen1_pureblue.gbc",
        "puregreen": "patch/build/gen1_puregreen.gbc"}
FIXTURES = os.path.join(REPO, "tests", "fixtures", "gen1")

# Fixtures still holding the OLD harness' bytes: written directly into SaveRAM, so the party
# mon has a level byte and exp 0, which no game state produces (AddPartyMon derives exp from
# the level, engine/pokemon/add_mon.asm:202-207). Named individually so a regenerated fixture
# cannot hide behind a blanket tolerance -- anything not listed here must qualify clean.
# Empty: all seven committed fixtures came out of scripted play. Kept as the mechanism for
# any future fixture that lands byte-written ahead of a real rebuild.
LEGACY = set()
_LEGACY_PROBLEM = re.compile(r"^slot \d+: exp 0 is not level \d+ on curve \d+$")


def is_legacy_artefact(problems: list[str]) -> bool:
    """True when EVERY problem is the old harness' exp-0 artefact, and nothing else."""
    return bool(problems) and all(_LEGACY_PROBLEM.match(p) for p in problems)


def saved_ot(sram: bytes, title: str) -> int:
    """The trainer ID in a saved image, big-endian, by the rule tools/e2e_duo.py:1097 uses.

    wPlayerID is a 2-byte big-endian word (data/games/gen1_rby/profile.json; pret
    ram/wram.asm), reached at sMainData + (wPlayerID - wMainDataStart) because the save copies
    wMainDataStart..End to sMainData (engine/menus/save.asm:63-68).
    """
    pack = "gen1_purergb" if title.startswith("pure") else "gen1_rby"
    profile = json.loads((Path(REPO) / "data/games" / pack / "profile.json").read_text(
        encoding="utf-8"))
    ram = profile["titles"][title]["ram"]
    offset = codec.SRAM_LAYOUT["sMainData"] + ram["wPlayerID"] - ram["wMainDataStart"]
    return int.from_bytes(sram[offset:offset + 2], "big")


def qualify(sram: bytes, rom: bytes, notes: list[str] | None = None) -> list[str]:
    """Problems with a candidate fixture (empty = a real, consistent save).

    `notes`, when given, collects the tolerated-but-not-exact observations (a stored stat
    that lags its stat exp, see the band below) so a caller can name them in its own log.
    """
    problems = []
    if len(sram) != 0x8000:
        return [f"SaveRAM is {len(sram)} bytes, not 32768"]
    if not codec.verify_bank1(sram):
        problems.append("main data checksum does not validate (sPlayerName..sTileAnimations, "
                        "which includes the current box at sCurBoxData; the game would not offer "
                        "CONTINUE)")
    # The active box has no checksum byte of its own -- the main-data checksum above is what
    # covers it (SaveCurrentBoxData recomputes sGameData..sGameDataEnd, :255-258; LoadCurrentBox
    # Data refuses the save before reading the box, :96-105). The 12 boxes in SRAM banks 2/3 do
    # have checksums, and the game writes them only from CopyBoxToOrFromSRAM (:400-431), which
    # runs on a box change and sets the has-changed-boxes bit. Until that bit is set the banks
    # are untouched SRAM ($FF) and the game never reads them, so they cannot be checked.
    boxes = codec.verify_boxes(sram)
    if boxes["initialized"]:
        for bank, info in sorted(boxes["banks"].items()):
            if not info["valid"]:
                problems.append(f"box bank {bank} checksum does not match (stored "
                                f"{info['stored']:02X}, calculated {info['calculated']:02X})")
        for number, info in sorted(boxes["boxes"].items()):
            if not info["valid"]:
                problems.append(f"box {number} checksum does not match (stored "
                                f"{info['stored']:02X}, calculated {info['calculated']:02X})")
    try:
        party = codec.decode_party(sram[codec.SRAM_LAYOUT["sPartyData"]:codec.SRAM_LAYOUT["sPartyData"] + codec.PARTY_LAYOUT["size"]])
    except ValueError as exc:
        # A blank or torn save makes the decoder refuse rather than return an empty party
        # (gen1_codec._decode_collection checks the species terminator), and a qualifier's
        # job is to NAME that state, not to raise on it.
        problems.append(f"no party mon in the save: the party block is undecodable ({exc})")
        party = []
    if not party and not any("no party mon" in p for p in problems):
        problems.append("no party mon in the save")
    stats = scan.scan_base_stats(rom)
    for slot, mon in enumerate(party):
        entry = stats[codec.internal_to_natdex(mon["species"])]
        if codec.level_from_exp(entry["growth_rate"], mon["exp"]) != mon["level"]:
            problems.append(f"slot {slot}: exp {mon['exp']} is not level {mon['level']} on curve {entry['growth_rate']}")
        # Stat exp accrues after EVERY defeated foe (GainExperience .gainStatExpLoop,
        # engine/battle/experience.asm:25-51) but the stored stats are only rebuilt where the
        # engine calls CalcStats: the level-CHANGED branch of that same routine (:159-161 ->
        # :187), AddPartyMon and the box withdrawal (engine/pokemon/add_mon.asm:243,514),
        # evolution (engine/pokemon/evos_moves.asm:177) and the vitamin/rare-candy path
        # (engine/items/item_effects.asm:1331). A party mon's status screen deliberately does
        # NOT (engine/pokemon/status_screen.asm:64-76, `.DontRecalculate`; the recompute there
        # is for box/daycare mons and lands in wLoadedMon, not the party record). So a mon that
        # fought on after its last recalculation legitimately stores a stat BELOW a recompute
        # from its CURRENT stat exp. That last recalculation ran at some stat exp between 0 and
        # now, and calc_stat is monotonic in stat exp, so the sound check is the band
        # [recompute(0), recompute(now)] -- exact equality is an instrument error, not a
        # defect. HP is in the band too: CalcStats writes all five stats from one loop
        # (home/move_mon.asm:34-47), so max_hp lags exactly like the others.
        hi = codec.recompute_stats(mon, entry)
        lo = codec.recompute_stats({**mon, "stat_exp": dict.fromkeys(mon["stat_exp"], 0)}, entry)
        for k, top in hi.items():
            if not lo[k] <= mon[k] <= top:
                problems.append(f"slot {slot}: stored {k}={mon[k]} outside [{lo[k]}, {top}] "
                                f"(recompute at stat exp 0..current)")
            elif mon[k] != top and notes is not None:
                notes.append(f"slot {slot}: {k} stored {mon[k]} within [{lo[k]}, {top}] "
                             f"(stat exp accrued since the last recalculation)")
    return problems


def _qualification_case(path: Path) -> fixture_runner.FixtureCase:
    title = path.stem.split("_")[0]
    rom = DUMP.get(title)
    artifacts = {"fixture": path, "rom": Path(REPO) / rom if rom else None,
                 "qualification_source": Path(__file__), "codec_source": Path(codec.__file__),
                 "rom_reader_source": Path(scan.__file__), "orchestration_source": Path(fixture_runner.__file__),
                 "rom_symbols": Path(scan._SYMS_PATH)}
    # identify() consults pureRGB identity/anchor facts before the vanilla path,
    # even for R/B/Y. Bind the actual scanner dependencies, not just its .py file.
    for name in ("admission", "profile", "engine_signals", "write_checkpoint"):
        for suffix in ("", "_overlay"):
            key = name + suffix
            artifacts["purergb_" + key] = Path(scan._PUREGB_DATA) / f"{key}.json"
    return fixture_runner.FixtureCase(path.stem, artifacts,
        {"family": "gen1", "title": title, "oracle": "independent Python codec and ROM scanner"})


@contextmanager
def _oracle_source_snapshot(artifacts):
    """Bind the independent scanner to the source bytes captured for this attempt.

    Its normal lazy caches can predate an audit. Replace them only for the callback
    and restore them even on failure; never consult mutable files behind a receipt.
    """
    previous = scan._SYMS_CACHE, scan._PUREGB_ADMISSION_CACHE, scan._PUREGB_PACK_CACHE
    try:
        scan._SYMS_CACHE = json.loads(artifacts["rom_symbols"])
        admission = json.loads(artifacts["purergb_admission"])
        admission.update(json.loads(artifacts["purergb_admission_overlay"]))
        scan._PUREGB_ADMISSION_CACHE = admission
        scan._PUREGB_PACK_CACHE = {
            name + suffix + ".json": json.loads(artifacts["purergb_" + name + suffix])
            for name in ("profile", "engine_signals", "write_checkpoint") for suffix in ("", "_overlay")
        }
        yield
    finally:
        scan._SYMS_CACHE, scan._PUREGB_ADMISSION_CACHE, scan._PUREGB_PACK_CACHE = previous


def _qualification_stage(context: fixture_runner.StageContext) -> fixture_runner.StageReceipt:
    sram, rom = context.artifacts["fixture"], context.artifacts["rom"]
    notes: list[str] = []
    with _oracle_source_snapshot(context.artifacts):
        problems = qualify(sram, rom, notes)
    evidence = {"oracle": "gen1_fixtures.qualify"}
    if problems:
        if context.fixture in LEGACY and is_legacy_artefact(problems):
            evidence["disposition"] = "LEGACY"
        return fixture_runner.StageReceipt(context.stage, context.fingerprint, "FAIL",
                                            tuple(problems), tuple(notes), evidence)
    party = codec.decode_party(sram[codec.SRAM_LAYOUT["sPartyData"]:
                                   codec.SRAM_LAYOUT["sPartyData"] + codec.PARTY_LAYOUT["size"]])
    evidence["summary"] = f"party={[(m['species'], m['level'], m['exp']) for m in party]}"
    return fixture_runner.StageReceipt(context.stage, context.fingerprint, "PASS",
                                        notes=tuple(notes), evidence=evidence)


def qualification_report(*, scope: str = "static", stage_callbacks=None) -> dict:
    """Bind Gen 1's unchanged oracle to shared enumeration/provenance/orchestration.

    Static success does not establish a boot or re-save witness. Full qualification
    requires injected boot/resave/post_oracle callbacks; there are no emulator
    defaults and the independent Python oracle cannot be overridden by this seam.
    """
    callbacks = {"qualify": _qualification_stage}
    if stage_callbacks:
        if set(stage_callbacks) - {"boot", "resave", "post_oracle"}:
            raise ValueError("only game boot/resave/post_oracle callbacks may be injected")
        callbacks.update(stage_callbacks)
    try:
        paths = fixture_runner.enumerate_fixtures(Path(FIXTURES), suffix=".SaveRAM", max_fixtures=64)
    except ValueError as exc:
        report = fixture_runner.qualify_fixtures([], callbacks, scope=scope)
        report["errors"] = [str(exc)]
        return report
    return fixture_runner.qualify_fixtures((_qualification_case(path) for path in paths), callbacks, scope=scope)


def qualify_all() -> int:
    """Print the static audit; missing inputs/empty inventories/legacy bytes refuse.

    The report binds actual fixture, cartridge and oracle-source bytes. Its OK
    means only the existing static oracle passed, never full boot qualification.
    """
    report = qualification_report()
    for row in report["fixtures"]:
        name = row["name"]
        if row.get("missing_artifact") == "rom":
            print(f"{name}: NO-ROM")
        elif row["passed"]:
            print(f"{name}: OK {row['stages'][0]['evidence']['summary']}")
        else:
            legacy = any(stage.get("evidence", {}).get("disposition") == "LEGACY" for stage in row["stages"])
            print(f"{name}: {'LEGACY' if legacy else 'REFUSED'} {'; '.join(row['problems'])}")
    for problem in report["errors"]:
        print(f"fixtures: REFUSED {problem}")
    return 0 if report["passed"] else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("rom", nargs="?", choices=sorted(COLD_KEY))
    ap.add_argument("target", nargs="?", choices=sorted(CHAINS))
    ap.add_argument("--qualify", action="store_true",
                    help="check tests/fixtures/gen1/*.SaveRAM against the dumps and exit "
                         "(no emulator, no writes)")
    ap.add_argument("--player", choices=("a", "b"), default=None, help="a = Bulbasaur, b = Charmander (default: red a, blue b)")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--title-idle", type=int, default=0,
                    help="idle frames on the title screen before New Game; the count moves the "
                         "trainer ID (0 is what the committed fixtures were built with)")
    args = ap.parse_args()

    if args.qualify:
        return qualify_all()
    if args.rom is None or args.target is None:
        ap.error("rom and target are required unless --qualify")
    # Red and PureRed lead with Bulbasaur (the A-side starter); everything else with Charmander.
    player = args.player or ("a" if args.rom in ("red", "purered") else "b")

    import gen1_playthrough as play
    from run_gb_gate import PATCHED, run_gate
    env = dict(os.environ, SLINK_SCRIPT_CHAIN=CHAINS[args.target], SLINK_SCRIPT_PLAYER=player,
               SLINK_SCRIPT_FLUSH="1", SLINK_SCRIPT_TITLE_IDLE=str(args.title_idle))
    os.environ.update(env)
    cold_key = COLD_KEY[args.rom]
    passed, path, text = run_gate(GATE, rom_key=cold_key, target="town", timeout=args.timeout)
    print(text[-2500:])
    if not passed:
        print("scripted play did not reach its terminals; no fixture written", file=sys.stderr)
        return 1
    _, rom_rel, save_name = PATCHED[cold_key]
    src = os.path.join(play.SAVERAM_DIR, save_name)
    if not os.path.exists(src):
        print(f"EmuHawk left no SaveRAM at {src}", file=sys.stderr)
        return 1
    with open(src, "rb") as f:
        sram = f.read()
    # Qualified against the cartridge that wrote it (run_gb_gate resolves a None ROM the same way).
    rom_rel = rom_rel or play.staged_rom(cold_key.removesuffix("_cold"))
    with open(os.path.join(REPO, rom_rel), "rb") as f:
        rom = f.read()
    problems = qualify(sram, rom)
    if problems:
        print("candidate fixture refused:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    dest = os.path.join(REPO, "tests", "fixtures", "gen1", f"{args.rom}_{args.target}.SaveRAM")
    ot = saved_ot(sram, args.rom)
    if args.target == "town_ot2" and ot == DEFAULT_OT:
        # A1's wrong-save leg is only a leg if the two saves disagree on the trainer ID; a
        # fixture carrying the default one would make the leg pass for the wrong reason.
        if os.path.exists(dest):
            os.remove(dest)  # a stale fixture must not outlive the build that was refused
        print(f"refused {os.path.relpath(dest, REPO)}: the saved trainer ID is still 0x{ot:04X}, "
              f"the same OT the default fixtures carry — the idle count did not move it. "
              f"Try --title-idle 240 or 360.", file=sys.stderr)
        return 1
    shutil.copyfile(src, dest)
    party = codec.decode_party(sram[codec.SRAM_LAYOUT["sPartyData"]:codec.SRAM_LAYOUT["sPartyData"] + 404])
    print(f"wrote {os.path.relpath(dest, REPO)}: OT 0x{ot:04X} "
          f"party={[(m['species'], m['level'], m['exp']) for m in party]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
