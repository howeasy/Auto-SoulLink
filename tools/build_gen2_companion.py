#!/usr/bin/env python3
"""Build the SLink companion overlay ROMs for Crystal, Gold and Silver (P4.1a).

Source overlay on the pinned pret checkout (owner ruling O-27 D6), the pureRGB pipeline shape
(tools/build_purergb_overlay.py) applied to Gen 2's two source repos:

    fresh copy of the pinned checkout (.cache/gen2-build/{pokecrystal,pokegold},
      HEAD == data/gen2_sources.lock.json)
      -> apply_overlay()                 (copies patch/gen2/src/* into engine/slink/, edits
                                          main.asm; a no-op when patch/gen2/src/ has nothing
                                          this tool recognises for a repo -- the "empty overlay")
      -> make pokecrystal.gbc / pokegold.gbc pokesilver.gbc  (pinned RGBDS v1.0.3 + w64devkit,
                                          bare tool names on the verified PATH, same as
                                          tools/build_gen2_syms.py -- no space-free relocation
                                          needed, the pinned build already succeeds from this
                                          space-bearing worktree)
      -> data/gen2/{crystal,gold,silver}_slink.{sym,map}
      -> patch/dist/SLink-{Crystal,Gold,Silver}.ups  (patch/tools/make_ups.py; CRC-bound to the
                                          clean pinned ROM, round-trip verified)
      -> data/gen2/overlay_provenance.json

Today patch/gen2/src/ holds only the mailbox reservation stubs (ticket 14, owner ruling O-27
D1): SECTION "SLink Mailbox" at a fixed WRAM0 address per title, sized to the full linker-
verified EMPTY gap, emitting zero ROM bytes. Card P4.1c (Codex) adds patch/gen2/src/slink.asm
next; this tool includes it automatically when present -- see `overlay_plan()`.

    python tools/build_gen2_companion.py --version vX.Y.Z           # build + publish
    python tools/build_gen2_companion.py --version vX.Y.Z --check   # build, compare, publish nothing
    python tools/build_gen2_companion.py --no-version --src-dir DIR  # a source without version.asm

--version is required (TITLE-VERSION): it is printed on the main menu, so it is part of the ROM
bytes and is recorded as overlay.version + overlay.version_sha256 in the provenance.
    python tools/build_gen2_companion.py --src-dir DIR    # override patch/gen2/src (falsifiers)
    python tools/build_gen2_companion.py --rgbds-bin DIR --w64devkit-bin DIR
    python tools/build_gen2_companion.py --crystal-repo PATH --gold-repo PATH
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import zlib
from datetime import UTC, datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "patch" / "tools"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from build_gen2_syms import ROOT, _load_lock, _source_check, _toolchains  # noqa: E402
from make_ups import ups_apply, ups_create  # noqa: E402

from patch.gen1.tools import title_screen  # noqa: E402

LOCK_PATH = ROOT / "data" / "gen2_sources.lock.json"
OVERLAY_CACHE = ROOT / ".cache" / "gen2-overlay"
SRC_DIR = ROOT / "patch" / "gen2" / "src"
OUT_DIR = ROOT / "data" / "gen2"
DIST = ROOT / "patch" / "dist"
PROVENANCE_PATH = OUT_DIR / "overlay_provenance.json"
PROVENANCE_SCHEMA = "gen2-overlay-provenance-v1"

# lock output key -> (SLink title, UPS artifact, source repo)
TITLES: dict[str, tuple[str, str, str]] = {
    "pokecrystal": ("crystal", "SLink-Crystal.ups", "pokecrystal"),
    "pokegold": ("gold", "SLink-Gold.ups", "pokegold"),
    "pokesilver": ("silver", "SLink-Silver.ups", "pokegold"),
}

# repo -> the mailbox stub that reserves that repo's title-specific WRAM span (O-27 D1).
REPO_MAILBOX_STUB = {
    "pokecrystal": "slink_mailbox_crystal.asm",
    "pokegold": "slink_mailbox_goldsilver.asm",
}
# Shared files a later card drops into patch/gen2/src/ that both repos include verbatim.
# Card P4.1c: Codex's beacon/ABI/DelayFrame bridge, once it exists.
OPTIONAL_SHARED_FILES = ["slink.asm"]
PANEL_FILES = ("panel_flags.asm", "panel.asm", "panel_start.asm")
SFX_FILE = "sfx.asm"
PHONE_FILES = ("phone_flags.asm", "phone.asm")
VERSION_FILE = "version.asm"
# TITLE: the SoulLink logo and the version on the real title screen. title.asm is shared; the art is per repo and is
# copied under fixed names. The version tiles are rendered here, per build (title_version.2bpp).
TITLE_FILE = "title.asm"
TITLE_ART = {"pokecrystal": ("title_logo_crystal.2bpp", "title_rows_crystal.inc"),
             "pokegold": ("title_logo_gs.2bpp", "title_rows_gs.inc")}
TITLE_ANCHOR = "\tcall EnableLCD\n"
# vX.Y.Z plus an optional lowercase pre-release suffix; "SLINK " + it must fit 18 tiles
VERSION_RE = re.compile(r"v\d+\.\d+\.\d+(?:-[a-z0-9.]+)?")
TRADE_FILES = ("trade_frame.asm", "trade_items.asm", "trade_snapshot.asm",
               "trade_commit.asm", "trade_service.asm", "trade_receptionist.asm", "trade_dispatch.asm")


def _trade_receptionist_text(checkout: pathlib.Path) -> tuple[pathlib.Path, str]:
    path = checkout / "maps/Pokecenter2F.asm"
    text = path.read_text(encoding="utf-8")
    anchor = ("\tobject_event  5,  2, SPRITE_LINK_RECEPTIONIST, SPRITEMOVEDATA_STANDING_DOWN, "
              "0, 0, -1, -1, PAL_NPC_GREEN, OBJECTTYPE_SCRIPT, 0, LinkReceptionistScript_Trade, -1")
    if text.count(anchor) != 1:
        raise RuntimeError("trade receptionist object anchor must occur exactly once")
    return path, text.replace(anchor, anchor.replace("LinkReceptionistScript_Trade",
                                                   "SlinkTradeReceptionistScript"), 1)


def trade_export_text(checkout: pathlib.Path, repo: str) -> list[tuple[pathlib.Path, str]]:
    """Expose existing labels across object files; EXPORT emits no ROM bytes."""
    names = ["LinkReceptionistScript_Trade", "Script_TradeCenterClosed", "Text_TradeReceptionistIntro",
             "Text_MustSaveGame", "Text_PleaseWait", "Text_PleaseComeAgain"]
    if repo == "pokecrystal":
        names += ["LinkReceptionistScript_Trade.Mobile", "Text_TradeReceptionistMobile"]
    files = [("maps/Pokecenter2F.asm", names), ("engine/overworld/events.asm", ["NextOverworldFrame"]),
             ("engine/menus/save.asm", ["Link_SaveGame"])]  # the responder's forced pre-trade save
    if repo == "pokecrystal":
        files.append(("mobile/mobile_41.asm", ["BackupGSBallFlag"]))  # native LinkTrade's post-save call
    edits = []
    for relative, symbols in files:
        path = checkout / relative
        text = path.read_text(encoding="utf-8")
        declaration = "EXPORT " + ", ".join(symbols)
        if declaration not in text.splitlines():
            text = text.rstrip("\n") + "\n\n" + declaration + "\n"
        edits.append((path, text))
    return edits


# PHONE-NAMES: GetCallerName's first four bytes (ld a,c / and a / jr z,.NotTrainer) become a jump
# to the bank-$24 SlinkPhoneCallerName + nop; the label adds no byte (verify_phone_hook pins it).
CALLER_NAME_ANCHOR = "GetCallerName:\n\tld a, c\n\tand a\n\tjr z, .NotTrainer\n\n\tcall Phone_GetTrainerName\n"
CALLER_NAME_REPLACEMENT = ("GetCallerName:\n\tjp SlinkPhoneCallerName ; SLink overlay: same size as "
                           "ld a,c / and a / jr z\n\tnop\n.SlinkTrainer:\n\tcall Phone_GetTrainerName\n")


def _phone_table_text(checkout: pathlib.Path) -> tuple[pathlib.Path, str]:
    path = checkout / "engine/phone/phone.asm"
    text = path.read_text(encoding="utf-8")
    anchor = "\tld hl, SpecialPhoneCallList\n"
    if text.count(anchor) != 2:
        raise RuntimeError("phone table requires exactly two native pointer loads")
    if text.count(CALLER_NAME_ANCHOR) != 1:
        raise RuntimeError("phone caller-name hook requires exactly one native GetCallerName entry")
    text = text.replace(CALLER_NAME_ANCHOR, CALLER_NAME_REPLACEMENT, 1)
    return path, text.replace(anchor, "\tld hl, SlinkSpecialPhoneCallList\n")


MAIN_MENU_ANCHOR = "MainMenuJoypadLoop:\n\tcall SetUpMenu\n"


def _main_menu_text(checkout: pathlib.Path) -> tuple[pathlib.Path, str]:
    """TITLE-VERSION: the one `call SetUpMenu` per title, same size, to the ROM0 bridge."""
    path = checkout / "engine/menus/main_menu.asm"
    text = path.read_text(encoding="utf-8")
    if text.count(MAIN_MENU_ANCHOR) != 1 or text.count("call SetUpMenu") != 1:
        raise RuntimeError("main menu requires exactly one `call SetUpMenu`, in MainMenuJoypadLoop")
    return path, text.replace(MAIN_MENU_ANCHOR, "MainMenuJoypadLoop:\n\tcall SlinkMainMenuBridge "
                              "; SLink overlay: same size as call SetUpMenu\n", 1)


def _title_text(checkout: pathlib.Path) -> tuple[pathlib.Path, str]:
    """TITLE: the one `call EnableLCD` that ends the title screen's setup, same size, to the ROM0 bridge."""
    path = checkout / "engine/movie/title.asm"
    text = path.read_text(encoding="utf-8")
    if text.count(TITLE_ANCHOR) != 1:
        raise RuntimeError("title screen requires exactly one `call EnableLCD`")
    return path, text.replace(TITLE_ANCHOR, "\tcall SlinkTitleBridge ; SLink overlay: same size as call EnableLCD\n", 1)


def title_version_tiles(repo: str, version: str) -> bytes:
    """The patch version as 2bpp tiles in the repo's palette. Crystal: white (colour 1) on black, 8 cells, from pixel 2.
    Gold/Silver: navy (3) on the sky (2), 5 cells, from pixel 2, without a pre-release suffix (it does not fit)."""
    if repo == "pokecrystal":
        return title_screen.text_tiles(version, 8, 2, fg=1, bg=0, y0=0)
    return title_screen.text_tiles(version.split("-")[0], 5, 2, fg=3, bg=2, y0=1)


def check_version(version: str | None) -> str:
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version) or len("SLINK " + version) > 18:
        raise RuntimeError(f"--version must be vX.Y.Z[-suffix] and fit 12 characters, got {version!r}")
    return version

# The mailbox/panel ABI is shared with Gen 1 (patch/gb/slink_abi.inc), not per-generation source,
# so it is copied -- never duplicated under patch/gen2 -- from its one committed location. It is
# copy-only: slink.asm (card P4.1c) INCLUDEs it itself (engine/slink/slink_abi.inc), so it never
# gets its own top-level INCLUDE from main.asm, and copying it alone (no consumer yet) changes no
# ROM byte. Absent today; card P4.1c adds it (coordinator follow-up gen2-p41a-abi-copy).
GB_DIR = ROOT / "patch" / "gb"
SHARED_ABI_NAME = "slink_abi.inc"

# (file, anchor) per repo -- the anchor is the tail of main.asm up to (not including) the rest of
# the "Stadium 2 Checksums" section line, so the fixed ROMX[$addr] suffix that differs between the
# two repos is never part of the matched text. Verify-then-replace-once, same discipline as
# tools/apply_purergb_overlay.py: a checkout that isn't the pinned source fails loudly.
MAIN_ANCHORS: dict[str, str] = {
    "pokecrystal": 'INCLUDE "engine/events/odd_egg.asm"\n\n\nSECTION "Stadium 2 Checksums"',
    "pokegold": 'INCLUDE "data/credits_strings.asm"\n\n\nSECTION "Stadium 2 Checksums"',
}
OVERLAY_DST = "engine/slink"

# Coordinator follow-up gen2-p41a-delay-hook (Codex, via P4.1c): DelayFrame is called directly by
# menus/text/overworld, not reached through slink.asm's own INCLUDE chain, so the main-thread SFX
# service needs its own hook. Same-size edit: DelayFrame's leading `ld a, 1` / `ld [wVBlankOccurred],
# a` (5 bytes) becomes `call SlinkDelayFrameBridge` + 2 nops (5 bytes). Confirmed identical text in
# both pinned repos (.cache/gen2-build/{pokecrystal,pokegold}/home/delay.asm). The ROM0 bridge (its
# body is Codex's, in slink.asm) lives in the confirmed-free $0063-$00FF padding right after the
# joypad vector ($0060-$0062) in all three titles' pinned .map -- this tool owns only the source
# replacement, applied verify-once, only when slink.asm is present.
DELAY_ANCHOR = 'DelayFrame::\n; Wait for one frame\n\tld a, 1\n\tld [wVBlankOccurred], a\n'
DELAY_REPLACEMENT = (
    'DelayFrame::\n; Wait for one frame\n'
    '\tcall SlinkDelayFrameBridge ; SLink overlay: same size as the displaced ld a,1 / ld [wVBlankOccurred],a\n'
    '\tnop\n\tnop\n'
)
DELAY_HOOK_TRIGGER = "slink.asm"  # presence of this file in the plan gates the home/delay.asm edit
RESET_ANCHORS = {
    "pokecrystal": "Reset::\n\tdi\n\tcall InitSound\n",
    "pokegold": "Reset::\n\tcall InitSound\n",
}
RESET_WAIT_ANCHOR = "\tld c, 32\n\tcall DelayFrames\n\n\tjr Init\n"


def _reset_sound_text(checkout: pathlib.Path, repo: str) -> tuple[pathlib.Path, str]:
    path = checkout / "home/init.asm"
    text = path.read_text(encoding="utf-8")
    anchor = RESET_ANCHORS[repo]
    count = text.count(anchor)
    if count != 1:
        raise RuntimeError(f"Reset: expected InitSound anchor exactly once, found {count}")
    count = text.count(RESET_WAIT_ANCHOR)
    if count != 1 or text.count("\n_Start::") != 1:
        raise RuntimeError(f"Reset: expected one 32-frame wait and _Start boundary, found {count}")
    if not text.index(anchor) < text.index(RESET_WAIT_ANCHOR) < text.index("\n_Start::"):
        raise RuntimeError("Reset: 32-frame wait is outside Reset")
    replacement = RESET_WAIT_ANCHOR.replace("call DelayFrames", "call SlinkResetSoundBridge")
    return path, text.replace(RESET_WAIT_ANCHOR, replacement, 1)

START_MENU_EDITS = (
    ("\tconst STARTMENUITEM_QUIT     ; 8\n",
     "\tconst STARTMENUITEM_QUIT     ; 8\n\tconst STARTMENUITEM_SLINK ; 9\n"),
    ("\tdw StartMenu_Quit,     .QuitString,     .QuitDesc\n",
     "\tdw StartMenu_Quit,     .QuitString,     .QuitDesc\n"
     "\tdw SlinkStartMenuEntry, SlinkMenuString, SlinkMenuDesc\n"),
    ("\tld a, STARTMENUITEM_EXIT\n", "\tld a, STARTMENUITEM_SLINK\n"),
)


def _start_menu_text(checkout: pathlib.Path) -> tuple[pathlib.Path, str]:
    path = checkout / "engine/menus/start_menu.asm"
    text = path.read_text(encoding="utf-8")
    for anchor, _replacement in START_MENU_EDITS:
        count = text.count(anchor)
        if count != 1:
            raise RuntimeError(f"start_menu.asm: expected {anchor.strip()!r} exactly once, found {count}")
    for anchor, replacement in START_MENU_EDITS:
        text = text.replace(anchor, replacement, 1)
    return path, text + '\nINCLUDE "engine/slink/panel_start.asm"\n'


def apply_start_menu_hook(checkout: pathlib.Path) -> None:
    """O-28 replaces the visible EXIT choice; B/START still close the native menu."""
    path, text = _start_menu_text(checkout)
    path.write_text(text, encoding="utf-8", newline="\n")


def apply_delay_hook(checkout: pathlib.Path) -> None:
    """Verify-then-replace-once the DelayFrame lead-in in home/delay.asm (same size, no shift)."""
    path = checkout / "home" / "delay.asm"
    text = path.read_text(encoding="utf-8")
    n = text.count(DELAY_ANCHOR)
    if n != 1:
        raise RuntimeError(f"home/delay.asm: expected the DelayFrame anchor exactly once, found {n}")
    path.write_text(text.replace(DELAY_ANCHOR, DELAY_REPLACEMENT, 1), encoding="utf-8", newline="\n")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_sha256(path: pathlib.Path) -> str:
    """F7: an overlay source's hash, independent of the checkout's line endings (CRLF == LF)."""
    return _sha256(path.read_bytes().replace(b"\r\n", b"\n"))


def rom_facts(data: bytes) -> dict:
    return {
        "sha1": hashlib.sha1(data).hexdigest(),
        "md5": hashlib.md5(data).hexdigest(),
        "header_crc": data[0x14E:0x150].hex().upper(),
        "crc32": format(zlib.crc32(data) & 0xFFFFFFFF, "08X"),
        "title": data[0x134:0x143].rstrip(b"\x00").decode("ascii", "replace"),
        "size": len(data),
    }


def overlay_plan(
    repo: str, src_dir: pathlib.Path, gb_dir: pathlib.Path = GB_DIR
) -> list[tuple[str, pathlib.Path, bool]]:
    """Return (dest name under engine/slink/, source path, needs a main.asm INCLUDE) triples.

    The repo-specific mailbox stub is normalised to a fixed destination name (slink_mailbox.asm)
    so shared files (Codex's slink.asm) can reference the wSlinkMailbox symbol without caring
    which title they were built for. The shared ABI header is copy-only (its own consumer,
    slink.asm, INCLUDEs it once that file exists) -- copying it alone never touches main.asm and
    changes no ROM byte. An empty return means "empty overlay" -- apply_overlay() then touches
    nothing in the checkout.
    """
    plan: list[tuple[str, pathlib.Path, bool]] = []
    panel = [name for name in PANEL_FILES if (src_dir / name).is_file()]
    if panel and (len(panel) != len(PANEL_FILES) or not (src_dir / "slink.asm").is_file()):
        raise RuntimeError("panel overlay requires panel_flags.asm, panel.asm, panel_start.asm and slink.asm")
    sfx = (src_dir / SFX_FILE).is_file()
    if sfx and not (src_dir / "slink.asm").is_file():
        raise RuntimeError("SFX overlay requires slink.asm")
    trade = [name for name in TRADE_FILES if (src_dir / name).is_file()]
    if trade and (len(trade) != len(TRADE_FILES) or not (src_dir / "slink.asm").is_file()):
        raise RuntimeError("trade overlay requires its complete file family and slink.asm")
    phone = [name for name in PHONE_FILES if (src_dir / name).is_file()]
    if phone and (len(phone) != len(PHONE_FILES) or not (src_dir / "slink.asm").is_file()):
        raise RuntimeError("phone overlay requires phone_flags.asm, phone.asm and slink.asm")
    version = (src_dir / VERSION_FILE).is_file()
    if version and not (src_dir / "slink.asm").is_file():
        raise RuntimeError("version overlay requires slink.asm")
    title = (src_dir / TITLE_FILE).is_file()
    if title and not (version and all((src_dir / name).is_file() for name in TITLE_ART[repo])):
        raise RuntimeError("title overlay requires version.asm and its art (title_logo_*.2bpp, title_rows_*.inc)")
    stub = src_dir / REPO_MAILBOX_STUB[repo]
    if stub.is_file():
        plan.append(("slink_mailbox.asm", stub, True))
    abi = gb_dir / SHARED_ABI_NAME
    if abi.is_file():
        plan.append((SHARED_ABI_NAME, abi, False))
    if panel:
        plan.append(("panel_flags.asm", src_dir / "panel_flags.asm", True))
    if phone:
        plan.append(("phone_flags.asm", src_dir / "phone_flags.asm", True))
    for name in OPTIONAL_SHARED_FILES:
        path = src_dir / name
        if path.is_file():
            plan.append((name, path, True))
    if panel:
        plan += [("panel.asm", src_dir / "panel.asm", True),
                 ("panel_start.asm", src_dir / "panel_start.asm", False)]
    if sfx:
        plan.append((SFX_FILE, src_dir / SFX_FILE, True))
    if trade:
        plan += [(name, src_dir / name, True) for name in TRADE_FILES]
    if phone:
        plan.append(("phone.asm", src_dir / "phone.asm", True))
    if version:
        plan.append((VERSION_FILE, src_dir / VERSION_FILE, True))
    if title:
        art, rows = TITLE_ART[repo]
        plan += [("title_logo.2bpp", src_dir / art, False), ("title_rows.inc", src_dir / rows, False),
                 (TITLE_FILE, src_dir / TITLE_FILE, True)]
    return plan


def apply_overlay(
    checkout: pathlib.Path, repo: str, src_dir: pathlib.Path, gb_dir: pathlib.Path = GB_DIR,
    version: str | None = None,
) -> list[str]:
    """Copy the overlay plan into `checkout` and hook main.asm. Returns the files applied."""
    plan = overlay_plan(repo, src_dir, gb_dir)
    if not plan:
        return []
    include_names = [name for name, _path, include in plan if include]
    if "panel.asm" in include_names:
        _start_menu_text(checkout)  # all three anchors validated before any checkout mutation
    reset_edit = _reset_sound_text(checkout, repo) if SFX_FILE in include_names else None
    trade_edit = _trade_receptionist_text(checkout) if "trade_service.asm" in include_names else None
    phone_edit = _phone_table_text(checkout) if "phone.asm" in include_names else None
    menu_edit = _main_menu_text(checkout) if VERSION_FILE in include_names else None
    title_edit = _title_text(checkout) if TITLE_FILE in include_names else None
    if menu_edit is not None:
        check_version(version)
    main_path = checkout / "main.asm"
    if include_names:
        anchor = MAIN_ANCHORS[repo]
        text = main_path.read_text(encoding="utf-8")
        n = text.count(anchor)
        if n != 1:
            raise RuntimeError(
                f"{repo}: expected the Stadium-checksums anchor exactly once in main.asm, found {n}"
            )
    dest_dir = checkout / OVERLAY_DST
    dest_dir.mkdir(parents=True, exist_ok=True)
    applied = []
    for dest_name, source_path, _include in plan:
        (dest_dir / dest_name).write_bytes(source_path.read_bytes())
        applied.append(dest_name)
    if title_edit is not None:  # the version, rendered for this repo's palette: the one per-release build input
        (dest_dir / "title_version.2bpp").write_bytes(title_version_tiles(repo, version))
    if include_names:
        block = "\n".join(
            ['; SLink companion overlay (tools/build_gen2_companion.py)']
            + (["DEF SLINK_SFX_ENABLED EQU 1"] if SFX_FILE in include_names else [])
            + (["DEF SLINK_TRADE_ENABLED EQU 1"] if trade_edit is not None else [])
            + ([f'DEF SLINK_BUILD_VERSION EQUS "{version}"'] if menu_edit is not None else [])
            + [f'INCLUDE "{OVERLAY_DST}/{name}"' for name in include_names]
        )
        new_anchor = anchor.replace('\n\n\nSECTION', f'\n\n{block}\n\n\nSECTION', 1)
        main_path.write_text(text.replace(anchor, new_anchor, 1), encoding="utf-8", newline="\n")
    if DELAY_HOOK_TRIGGER in applied:
        apply_delay_hook(checkout)
    if "panel.asm" in applied:
        apply_start_menu_hook(checkout)
    if reset_edit is not None:
        path, text = reset_edit
        path.write_text(text, encoding="utf-8", newline="\n")
    if trade_edit is not None:
        path, text = trade_edit
        path.write_text(text, encoding="utf-8", newline="\n")
        for path, text in trade_export_text(checkout, repo):
            path.write_text(text, encoding="utf-8", newline="\n")
    for edit in (phone_edit, menu_edit, title_edit):
        if edit is not None:
            path, text = edit
            path.write_text(text, encoding="utf-8", newline="\n")
    return applied


def external_source_hashes(
    repos: dict[str, pathlib.Path] | list[str], src_dir: pathlib.Path, gb_dir: pathlib.Path = GB_DIR
) -> dict[str, str]:
    """sha256, keyed by repo-relative path, for every overlay input apply_overlay() copies from
    outside `src_dir` (today just patch/gb/slink_abi.inc). Coordinator follow-up: `sources_sha256`
    previously only hashed files inside src_dir, so a shared file copied from elsewhere (the ABI
    include) was missing from the input provenance even though it was compiled into the ROM.
    """
    hashes: dict[str, str] = {}
    resolved_src = src_dir.resolve() if src_dir.is_dir() else None
    for repo in repos:
        for _dest_name, source_path, _include in overlay_plan(repo, src_dir, gb_dir):
            resolved = source_path.resolve()
            if resolved_src is not None and resolved.parent == resolved_src:
                continue  # already covered by sources_sha256's src_dir scan
            key = (resolved.relative_to(ROOT).as_posix() if resolved.is_relative_to(ROOT)
                   else resolved.as_posix())
            hashes[key] = source_sha256(resolved)
    return hashes


def fresh_copy(repo_dir: pathlib.Path, commit: str, dest: pathlib.Path) -> pathlib.Path:
    """Verified-clean, pinned-commit copy of `repo_dir` into `dest` (a fresh tree each build)."""
    _source_check(repo_dir, commit)
    if dest.exists():
        shutil.rmtree(dest, onexc=lambda fn, p, e: (os.chmod(p, 0o600), fn(p)))
    shutil.copytree(repo_dir, dest, symlinks=True)
    return dest


def make(checkout: pathlib.Path, targets: list[str], env: dict) -> list[str]:
    make_bin = env["_MAKE_BIN"]
    clean = [make_bin, "RGBDS=", "CC=gcc", "MAKE=make", "SHELL=sh", "clean"]
    command = [make_bin, "RGBDS=", "CC=gcc", "MAKE=make", "SHELL=sh", "-j4", *targets]
    run_env = {k: v for k, v in env.items() if not k.startswith("_")}
    for cmd in (clean, command):
        print(f"[gen2-companion] {' '.join(cmd)}  (cwd={checkout})", file=sys.stderr)
        result = subprocess.run(cmd, cwd=str(checkout), env=run_env, capture_output=True, text=True)
        if result.returncode != 0:
            sys.stderr.write(result.stdout)
            sys.stderr.write(result.stderr)
            raise RuntimeError(f"{' '.join(cmd)} failed with exit code {result.returncode}")
    return command


def _symbols(path: pathlib.Path) -> dict[str, tuple[int, int]]:
    symbols = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]+):([0-9a-fA-F]+)\s+(\S+)", line.strip())
        if match:
            bank, address, name = match.groups()
            if name in symbols:
                raise RuntimeError(f"{path}: duplicate symbol {name}")
            symbols[name] = (int(bank, 16), int(address, 16))
    if not symbols:
        raise RuntimeError(f"{path}: no link symbols")
    return symbols


def verify_trade_hook(base: bytes, overlay: bytes, overlay_sym: pathlib.Path, repo: str) -> None:
    """The complete 13-byte object event changes only its two-byte script pointer."""
    bank, address, original = {"pokecrystal": (0x64, 0x73b1, 0x689d),
                               "pokegold": (0x5c, 0x545b, 0x4d6f)}[repo]
    offset = bank * 0x4000 + address - 0x4000
    target_bank, target = _symbols(overlay_sym).get("SlinkTradeReceptionistScript", (-1, -1))
    if target_bank != bank or not 0x4000 <= target < 0x8000:
        raise RuntimeError("trade receptionist must remain in its original map bank")
    if len(base) != len(overlay) or base[offset:offset + 2] != original.to_bytes(2, "little"):
        raise RuntimeError("trade receptionist clean pointer/ROM size differs")
    expected = bytearray(base[offset - 9:offset + 4])
    expected[9:11] = target.to_bytes(2, "little")
    if overlay[offset - 9:offset + 4] != expected:
        raise RuntimeError("trade receptionist changed outside its two-byte script pointer")


def verify_phone_hook(base: bytes, overlay: bytes, clean_sym: pathlib.Path, overlay_sym: pathlib.Path) -> None:
    """Pin native rows and the two same-size loads; never grow the native table."""
    old, new = _symbols(clean_sym), _symbols(overlay_sym)
    required = ("SpecialPhoneCallList", "CheckSpecialPhoneCall", "CheckSpecialPhoneCall.DoSpecialPhoneCall",
                "SpecialCallOnlyWhenOutside", "SpecialCallWhereverYouAre")
    if any(name not in old for name in required) or any(name not in new for name in
            ("SlinkSpecialPhoneCallList", "SlinkSpecialPhoneCallListEnd", "SlinkPhoneCallScript",
             "SlinkSpecialCallCondition")):
        raise RuntimeError("phone link symbols missing")

    def flat(location):
        bank, address = location
        if not 0x4000 <= address < 0x8000 or bank <= 0:
            raise RuntimeError("phone symbol is not banked ROM")
        return bank * 0x4000 + address - 0x4000

    table = new["SlinkSpecialPhoneCallList"]
    if (table[0] != 0x24 or table[1] + 54 > 0x8000
            or new["SlinkSpecialPhoneCallListEnd"] != (0x24, table[1] + 54)):
        raise RuntimeError("phone table must have nine rows inside bank24")
    source, target = flat(old["SpecialPhoneCallList"]), flat(table)
    if (overlay[target:target + 48] != base[source:source + 48]
            or overlay[source:source + 48] != base[source:source + 48]):
        raise RuntimeError("phone native eight-row table changed")
    script_bank, script_address = new["SlinkPhoneCallScript"]
    flat((script_bank, script_address))
    condition_bank, condition = new["SlinkSpecialCallCondition"]
    if condition_bank != 0x24:
        raise RuntimeError("phone ninth-row condition must link in bank24")
    ninth = (condition.to_bytes(2, "little") + bytes([0, script_bank])
             + script_address.to_bytes(2, "little"))
    if overlay[target + 48:target + 54] != ninth:
        raise RuntimeError("phone ninth row has wrong condition/contact/script")
    start, end = flat(old["CheckSpecialPhoneCall"]), flat(old["SpecialCallOnlyWhenOutside"])
    expected = bytearray(base[start:end])
    native_load = b"\x21" + old["SpecialPhoneCallList"][1].to_bytes(2, "little")
    for at in (10, flat(old["CheckSpecialPhoneCall.DoSpecialPhoneCall"]) - start + 7):
        if expected[at:at + 3] != native_load:
            raise RuntimeError("phone native pointer-load instruction differs")
        expected[at + 1:at + 3] = table[1].to_bytes(2, "little")
    if overlay[start:end] != expected:
        raise RuntimeError("phone dispatch changed outside two pointer operands")
    # PHONE-NAMES: GetCallerName .. Phone_GetTrainerName changes only its 4-byte entry
    hook_bank, hook = new.get("SlinkPhoneCallerName", (-1, -1))
    if hook_bank != 0x24 or not 0x4000 <= hook < 0x8000:
        raise RuntimeError("phone caller-name hook must link in bank24")
    start, end = flat(old["GetCallerName"]), flat(old["Phone_GetTrainerName"])
    expected = bytearray(base[start:end])
    if expected[:3] != b"\x79\xa7\x28":
        raise RuntimeError("phone native GetCallerName entry differs")
    expected[:4] = b"\xc3" + hook.to_bytes(2, "little") + b"\x00"
    if overlay[start:end] != expected:
        raise RuntimeError("phone caller-name hook changed more than GetCallerName's 4-byte entry")


def verify_version_hook(base: bytes, overlay: bytes, clean_sym: pathlib.Path, overlay_sym: pathlib.Path) -> None:
    """TITLE-VERSION: MainMenuJoypadLoop's `call SetUpMenu` changes only its operand, to ROM0."""
    old, new = _symbols(clean_sym), _symbols(overlay_sym)
    bank, address = old["MainMenuJoypadLoop"]
    bridge_bank, bridge = new.get("SlinkMainMenuBridge", (-1, -1))
    if bridge_bank != 0 or not 0 <= bridge < 0x4000:
        raise RuntimeError("main menu bridge must link in ROM0")
    at = bank * 0x4000 + address - 0x4000
    end = at + old["MainMenuJoypadLoop.b_button"][1] - address
    expected = bytearray(base[at:end])
    if expected[:3] != b"\xcd" + old["SetUpMenu"][1].to_bytes(2, "little"):
        raise RuntimeError("main menu native call SetUpMenu differs")
    expected[1:3] = bridge.to_bytes(2, "little")
    if overlay[at:end] != expected:
        raise RuntimeError("main menu changed more than the call SetUpMenu operand")


def verify_title_hook(base: bytes, overlay: bytes, clean_sym: pathlib.Path, overlay_sym: pathlib.Path,
                      repo: str) -> None:
    """TITLE: the title setup's `call EnableLCD` changes only its operand, to the ROM0 bridge."""
    old, new = _symbols(clean_sym), _symbols(overlay_sym)
    bank, address = old["_TitleScreen" if repo == "pokecrystal" else "TitleScreen"]
    bridge_bank, bridge = new.get("SlinkTitleBridge", (-1, -1))
    if bridge_bank != 0 or not 0 <= bridge < 0x4000:
        raise RuntimeError("title bridge must link in ROM0")
    # the routine runs to the next global symbol in its bank (local labels are inside it)
    following = sorted(a for name, (b, a) in old.items() if b == bank and a > address and "." not in name)
    at = bank * 0x4000 + address - 0x4000
    end = at + following[0] - address
    call = b"\xcd" + old["EnableLCD"][1].to_bytes(2, "little")
    if base[at:end].count(call) != 1:
        raise RuntimeError("title screen native call EnableLCD differs")
    expected = bytearray(base[at:end])
    hook = expected.index(call)
    expected[hook + 1:hook + 3] = bridge.to_bytes(2, "little")
    if overlay[at:end] != expected:
        raise RuntimeError("title screen changed more than the call EnableLCD operand")


def verify_symbol_scope(clean_sym: pathlib.Path, overlay_sym: pathlib.Path, *, panel: bool) -> None:
    """Gate 6c: panel grows bank 4 only; other existing symbols stay fixed.

    rgblink enforces section/bank fit. ROM operands elsewhere can legitimately change when
    they reference bank-4 labels; byte-difference classification belongs to the later ROM gate.
    """
    old, new = _symbols(clean_sym), _symbols(overlay_sym)
    for name, location in old.items():
        current = new.get(name)
        movable = panel and location[0] == 4 and 0x4000 <= location[1] < 0x8000
        if current is None or (movable and (current[0] != 4 or not 0x4000 <= current[1] < 0x8000)):
            raise RuntimeError(f"{name}: original symbol missing or outside allowed bank 4")
        if not movable and current != location:
            raise RuntimeError(f"{name}: original symbol moved outside panel bank 4: {location} -> {current}")
    if panel:
        for name in ("SlinkStartMenuEntry", "SlinkMenuString", "SlinkMenuDesc"):
            bank, address = new.get(name, (-1, -1))
            if bank != 4 or not 0x4000 <= address < 0x8000:
                raise RuntimeError(f"{name}: panel START binding must link inside bank 4")


def build(*, version: str | None, crystal_repo: pathlib.Path | None = None, gold_repo: pathlib.Path | None = None,
          src_dir: pathlib.Path | None = None, rgbds_bin: pathlib.Path | None = None,
          w64devkit_bin: pathlib.Path | None = None, check: bool = False) -> int:
    src_dir = src_dir or SRC_DIR
    # F5: a normal build is always versioned; --no-version (version None) is for sources without it
    has_version = (src_dir / VERSION_FILE).is_file()
    if version is None:
        if has_version:
            raise RuntimeError(f"--no-version needs a source without {VERSION_FILE}")
    else:
        check_version(version)
        if not has_version:
            raise RuntimeError(f"{src_dir / VERSION_FILE} is missing: a versioned build needs it (or --no-version)")
    lock, _raw = _load_lock(LOCK_PATH, record=False)
    clean_repos = {
        "pokecrystal": (crystal_repo or ROOT / ".cache" / "gen2-build" / "pokecrystal").resolve(),
        "pokegold": (gold_repo or ROOT / ".cache" / "gen2-build" / "pokegold").resolve(),
    }
    from _build_tools_bootstrap import _binary_name, ensure_rgbds, ensure_w64devkit
    rgbds = (rgbds_bin or ensure_rgbds(lock["rgbds_version"])).resolve()
    devkit = (w64devkit_bin or ensure_w64devkit()).resolve()
    toolchain_record, env = _toolchains(rgbds, devkit, lock)
    env["_MAKE_BIN"] = str(devkit / _binary_name("make"))

    targets_by_repo: dict[str, list[str]] = {}
    for _key, (_title, _ups, repo) in TITLES.items():
        targets_by_repo.setdefault(repo, [])
    for key, (_title, _ups, repo) in TITLES.items():
        targets_by_repo[repo].append(f"{key}.gbc")

    outputs: dict[str, dict] = {}
    files: dict[pathlib.Path, bytes] = {}
    overlay_applied: dict[str, list[str]] = {}
    commands: dict[str, list[str]] = {}
    for repo, commit_spec in ((name, lock["sources"][name]) for name in clean_repos):
        checkout = fresh_copy(clean_repos[repo], commit_spec["commit"], OVERLAY_CACHE / repo)
        overlay_applied[repo] = apply_overlay(checkout, repo, src_dir, version=version)
        commands[repo] = make(checkout, targets_by_repo[repo], env)

    for key, (title, ups_name, repo) in TITLES.items():
        checkout = OVERLAY_CACHE / repo
        clean_dir = clean_repos[repo]
        spec = lock["outputs"][key]
        base = (clean_dir / spec["filename"]).read_bytes()
        if hashlib.sha1(base).hexdigest() != spec["sha1"]:
            raise RuntimeError(f"{key}: the clean ROM in {clean_dir} does not match the lock")
        data = (checkout / spec["filename"]).read_bytes()
        verify_symbol_scope(clean_dir / f"{key}.sym", checkout / f"{key}.sym",
                            panel="panel.asm" in overlay_applied[repo])
        if "trade_service.asm" in overlay_applied[repo]:
            verify_trade_hook(base, data, checkout / f"{key}.sym", repo)
        if "phone.asm" in overlay_applied[repo]:
            verify_phone_hook(base, data, clean_dir / f"{key}.sym", checkout / f"{key}.sym")
        if VERSION_FILE in overlay_applied[repo]:
            verify_version_hook(base, data, clean_dir / f"{key}.sym", checkout / f"{key}.sym")
        if TITLE_FILE in overlay_applied[repo]:
            verify_title_hook(base, data, clean_dir / f"{key}.sym", checkout / f"{key}.sym", repo)
        ups = ups_create(base, data)
        if ups_apply(base, ups) != data:
            raise RuntimeError(f"{key}: UPS round trip failed")
        files[DIST / ups_name] = ups
        for ext in ("sym", "map"):
            # rgbds on Windows writes CRLF; the repo pins LF (.gitattributes), matching the
            # pureRGB overlay's published bytes and provenance hashes (c411b2f3).
            files[OUT_DIR / f"{title}_slink.{ext}"] = (
                (checkout / f"{key}.{ext}").read_bytes().replace(b"\r\n", b"\n"))
        outputs[key] = {
            "filename": spec["filename"], "slink_title": title, "base_sha1": spec["sha1"],
            "identical_to_clean": data == base,
            **rom_facts(data),
            "ups": {"file": f"patch/dist/{ups_name}", "size": len(ups), "sha256": _sha256(ups)},
        }
        print(f"[gen2-companion] {key}: sha1={outputs[key]['sha1']} "
              f"identical_to_clean={outputs[key]['identical_to_clean']} ups={len(ups)} bytes",
              file=sys.stderr)

    sources_sha256 = {p.name: source_sha256(p) for p in sorted(src_dir.iterdir())
                       if p.suffix in (".asm", ".inc", ".2bpp")} if src_dir.is_dir() else {}
    sources_sha256.update(external_source_hashes(clean_repos, src_dir))

    provenance = {
        "schema": PROVENANCE_SCHEMA,
        "generated": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": lock["sources"],
        "overlay": {
            "src_dir": (src_dir.relative_to(ROOT).as_posix() if src_dir.is_relative_to(ROOT)
                        else src_dir.as_posix()),
            "applied": overlay_applied,
            "sources_sha256": sources_sha256,
            **({"version": version, "version_sha256": _sha256(version.encode("utf-8"))} if version else {}),
        },
        "toolchain": toolchain_record,
        "commands": {repo: " ".join(cmd) for repo, cmd in commands.items()},
        "outputs": outputs,
        "symbols": {dst.name: _sha256(data) for dst, data in files.items() if dst.parent == OUT_DIR},
    }

    if check:
        drift = [str(dst.relative_to(ROOT)) for dst, data in files.items()
                 if not dst.exists() or dst.read_bytes() != data]
        if PROVENANCE_PATH.exists():
            committed = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
            committed.pop("generated", None)
            mine = dict(provenance)
            mine.pop("generated")
            if committed != mine:
                drift.append(str(PROVENANCE_PATH.relative_to(ROOT)))
        else:
            drift.append(str(PROVENANCE_PATH.relative_to(ROOT)))
        if drift:
            print(f"[gen2-companion] --check: drift from the committed artifacts: {drift}", file=sys.stderr)
            return 1
        print("[gen2-companion] --check: the build reproduces every committed artifact byte-for-byte",
              file=sys.stderr)
        return 0

    for dst, data in files.items():
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
    PROVENANCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROVENANCE_PATH.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(f"[gen2-companion] published {len(files)} files + {PROVENANCE_PATH.relative_to(ROOT)}",
          file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--crystal-repo", type=pathlib.Path, default=None)
    ap.add_argument("--gold-repo", type=pathlib.Path, default=None)
    ap.add_argument("--src-dir", type=pathlib.Path, default=None,
                    help="override patch/gen2/src (used by the equality-gate falsifiers)")
    ap.add_argument("--rgbds-bin", type=pathlib.Path, default=None)
    ap.add_argument("--w64devkit-bin", type=pathlib.Path, default=None)
    ap.add_argument("--check", action="store_true", help="build and compare, publish nothing")
    versioning = ap.add_mutually_exclusive_group(required=True)
    versioning.add_argument("--version",
                            help="the release version shown on the main menu, vX.Y.Z (the exact release tag)")
    versioning.add_argument("--no-version", action="store_true",
                            help="a source without version.asm (falsifiers); no version provenance")
    args = ap.parse_args()
    try:
        return build(version=args.version, crystal_repo=args.crystal_repo, gold_repo=args.gold_repo, src_dir=args.src_dir,
                     rgbds_bin=args.rgbds_bin, w64devkit_bin=args.w64devkit_bin, check=args.check)
    except (RuntimeError, SystemExit) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
