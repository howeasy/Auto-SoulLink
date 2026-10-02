#!/usr/bin/env python3
"""Apply the SLink companion overlay to a pureRGB checkout (docs/purergb/PLAN.md M3).

Copies patch/gen1/purergb/overlay/ to <checkout>/engine/slink/ and makes the hook edits the
design (docs/purergb/research/s3/overlay_design.md + PLAN §11.2 A8/S3) calls for:

    main.asm                          INCLUDE the overlay (after the last section, "newCode3"
                                      + "Silph Card Key Scripts")
    layout.link                       "SLink Home" after "Home"; the "SLink *" ROMX sections in
                                      a new ROMX $3F block; "SLink Mailbox" after "Current Box
                                      Data" in WRAMX bank 1 (the 22-byte tail before the stack)
    home/vblank.asm                   farcall TrackPlayTime -> farcall SlinkHook (calls it once)
    home/map_objects.asm              TextScript_CableClubNPC -> jpfar SlinkReceptionist
    home/start_menu.asm               dw SlinkStartMenuEntry appended after CloseTextDisplay
    engine/menus/draw_start_menu.asm  box heights 14/12 -> 16/14, max index +1, SLINK row after EXIT
    engine/menus/custom_list_menu.asm GetStartMenuPrompt rows 15/13 -> 17/15
    home/overworld.asm                farcall SlinkForeground after `rst _DelayFrame` at OverworldLoop
    engine/pokemon/evos_moves.asm     TryEvolvingMon exported (::) for the bank-$3F farcall
    engine/items/item_effects.asm     .setDVs: farcall SlinkApexGuard (DV pointer in de) / jr c,
                                      .alreadyUsedApex before the DV store (the chip is not consumed
                                      on a refusal)

Every edit is verify-then-replace: the exact original text must occur exactly once, so a
checkout that is not the pinned 7e7a4653 source fails loudly and nothing is written. Applying
twice fails the same way (the build script always starts from a fresh copy).

    python tools/apply_purergb_overlay.py <checkout>          # edit in place
    python tools/apply_purergb_overlay.py <checkout> --check  # verify the originals only
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
OVERLAY_SRC = REPO / "patch" / "gen1" / "purergb" / "overlay"
OVERLAY_DST = "engine/slink"

ROMX_SECTIONS = [
    "SLink Hook", "SLink Panel", "SLink foreground trade service", "SLink Native Trade",
    "SLink trade receptionist", "SLink trade UI helpers", "SLink partner trade prompt",
    "SLink APEX guard", "SLink title band",
]
OVERLAY_BANK = 0x3F
MAILBOX_SECTION = "SLink Mailbox"
HOME_SECTION = "SLink Home"

# (file, original, replacement) — originals are the pinned pureRGB text, byte for byte.
EDITS: list[tuple[str, str, str]] = [
    ("layout.link",
     '\torg $150\n\t"Home"\n',
     f'\torg $150\n\t"Home"\n\t"{HOME_SECTION}"\n'),
    ("layout.link",
     'ROMX $3D\n\t"newCode3"\nWRAM0\n',
     'ROMX $3D\n\t"newCode3"\n' + f"ROMX ${OVERLAY_BANK:X}\n"
     + "".join(f'\t"{s}"\n' for s in ROMX_SECTIONS) + "WRAM0\n"),
    ("layout.link",
     '\t"Current Box Data"\n\torg $df00\n',
     f'\t"Current Box Data"\n\t"{MAILBOX_SECTION}"\n\torg $df00\n'),
    ("home/vblank.asm",
     "\tfarcall TrackPlayTime ; keep track of time played\n",
     "\tfarcall SlinkHook ; SLink overlay: writes the mailbox, then calls TrackPlayTime once\n"),
    ("home/map_objects.asm",
     "TextScript_CableClubNPC::\n\tjpfar CableClubNPC\n",
     "TextScript_CableClubNPC::\n\tjpfar SlinkReceptionist ; SLink overlay: falls back to CableClubNPC\n"),
    ("home/start_menu.asm",
     "\tdw StartMenu_Option\n\tdw CloseTextDisplay\n",
     "\tdw StartMenu_Option\n\tdw CloseTextDisplay\n"
     "\tdw SlinkStartMenuEntry ; SLink overlay: appended, so ITEM/SAVE keep indices 2/4\n"),
    ("engine/menus/draw_start_menu.asm",
     "\thlcoord 10, 0\n\tlb bc, 14, 8\n\tjr nz, .drawTextBoxBorder\n"
     "; shorter menu if the player doesn't have the pokedex\n\tld b, 12\n",
     "\thlcoord 10, 0\n\tlb bc, 16, 8 ; SLink overlay: one more row\n\tjr nz, .drawTextBoxBorder\n"
     "; shorter menu if the player doesn't have the pokedex\n\tld b, 14 ; SLink overlay: one more row\n"),
    ("engine/menus/draw_start_menu.asm",
     "\tld a, 5\n\tld de, StartMenuWithoutPokedexText\n",
     "\tld a, 6 ; SLink overlay: one more row\n\tld de, StartMenuWithoutPokedexText\n"),
    ("engine/menus/draw_start_menu.asm",
     '\tnext "OPTION"\n\tnext "EXIT@"\n',
     '\tnext "OPTION"\n\tnext "EXIT"\n\tnext "SLINK@" ; SLink overlay\n'),
    ("engine/menus/custom_list_menu.asm",
     "\tdecoord 12, 15\n\tjr nz, .next1\n\tdecoord 12, 13\n",
     "\tdecoord 12, 17 ; SLink overlay: the menu is one row taller\n\tjr nz, .next1\n"
     "\tdecoord 12, 15 ; SLink overlay: the menu is one row taller\n"),
    ("home/vblank.asm",
     "\tldh a, [hVBlankOccurred]\n\tand a\n\tjr nz, .halt\n\tret\n",
     "\tldh a, [hVBlankOccurred]\n\tand a\n\tjr nz, .halt\n"
     "\tjp SlinkDelayFrameTail ; SLink overlay: main-thread SFX service, returns to the caller\n"),
    ("home/joypad.asm",
     "\thomecall _Joypad\n\tret\n",
     "\thomecall _Joypad\n\tcall SlinkJoypadSite ; SLink overlay: SFX service for the menu loops\n\tret\n"),
    ("home/overworld.asm",
     "OverworldLoop::\n\trst _DelayFrame\nOverworldLoopLessDelay::\n",
     "OverworldLoop::\n\trst _DelayFrame\n"
     "\tfarcall SlinkForeground ; SLink overlay: foreground trade service (lease byte +10 == 1)\n"
     "OverworldLoopLessDelay::\n"),
    ("engine/pokemon/evos_moves.asm",
     "; try to evolve the mon in [wWhichPokemon]\nTryEvolvingMon:\n",
     "; try to evolve the mon in [wWhichPokemon]\nTryEvolvingMon:: ; SLink overlay: exported for the native trade\n"),
    ("engine/items/item_effects.asm",
     ".setDVs\n\tld [hli], a ; set first byte of DVs to max\n",
     ".setDVs\n"
     "\tld d, h ; SLink overlay: the DV pointer rides in de (a farcall takes hl)\n"
     "\tld e, l\n"
     "\tfarcall SlinkApexGuard ; carry = a same-OT/same-species mon is already $FFFF\n"
     "\tjr c, .alreadyUsedApex ; refused before the chip is consumed\n"
     "\tld h, d\n"
     "\tld l, e\n"
     "\tld a, $FF\n"
     "\tld [hli], a ; set first byte of DVs to max\n"),
    # Title band: SoulLink logo + patch version on the vanilla-style title only (title_band.asm). The Pure
    # title animates rows 7-8 itself, so IsPureTitleScreenEnabled sends it to the original printer.
    ("engine/movie/title.asm",
     "PrintGameVersionOnTitleScreen:\n",
     "PrintGameVersionOnTitleScreen:\n"
     "\tcall IsPureTitleScreenEnabled\n"
     "\tjr nz, .slinkVanillaPrint ; SLink overlay: the Pure title is left untouched\n"
     "\tfarcall SlinkTitleBand ; SLink overlay: SoulLink logo and patch version beside the game's own line\n"
     "\tIF DEF(_GREEN) ; the game's own line moves right to make room; \"Green Version\" is a tile longer\n"
     "\t\thlcoord 10, 8\n"
     "\tELSE\n"
     "\t\thlcoord 11, 8\n"
     "\tENDC\n"
     "\tjr .slinkPrint\n"
     ".slinkVanillaPrint\n"),
    ("engine/movie/title.asm",
     "\tld de, VersionOnTitleScreenText\n\tjp PlaceString\n",
     ".slinkPrint\n\tld de, VersionOnTitleScreenText\n\tjp PlaceString\n"),
    ("engine/movie/title2.asm",
     "\tld h, d\n\tld l, $48\n",
     "\tld h, d\n\tld l, $50 ; SLink overlay: scroll from tile row 10, so the title band's second row stays still\n"),
    ("main.asm",
     'INCLUDE "engine/events/silph_card_key_scripts.asm"\n',
     'INCLUDE "engine/events/silph_card_key_scripts.asm"\n\n'
     '; SLink companion overlay (tools/apply_purergb_overlay.py)\n'
     f'INCLUDE "{OVERLAY_DST}/slink_overlay.asm"\n'),
]


def check(checkout: pathlib.Path) -> list[str]:
    """Every original present exactly once, no replacement present, no overlay dir yet."""
    problems: list[str] = []
    for rel, old, new in EDITS:
        path = checkout / rel
        if not path.is_file():
            problems.append(f"{rel}: missing")
            continue
        text = path.read_text(encoding="utf-8")
        n = text.count(old)
        if n != 1:
            problems.append(f"{rel}: expected the original text once, found {n}: {old!r}")
        elif new in text:
            problems.append(f"{rel}: already applied")
    if (checkout / OVERLAY_DST).exists():
        problems.append(f"{OVERLAY_DST}/ already exists in the checkout")
    return problems


def apply(checkout: pathlib.Path) -> None:
    problems = check(checkout)
    if problems:
        raise SystemExit("apply_purergb_overlay: refusing to edit " + str(checkout) + ":\n  "
                         + "\n  ".join(problems))
    for rel, old, new in EDITS:
        path = checkout / rel
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
    shutil.copytree(OVERLAY_SRC, checkout / OVERLAY_DST,
                    ignore=shutil.ignore_patterns("README.md", "__pycache__"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("checkout", type=pathlib.Path)
    ap.add_argument("--check", action="store_true", help="verify the hook sites, write nothing")
    args = ap.parse_args()
    if args.check:
        problems = check(args.checkout)
        print("\n".join(problems) if problems else f"{args.checkout}: all {len(EDITS)} hook sites as expected")
        return 1 if problems else 0
    apply(args.checkout)
    print(f"applied {len(EDITS)} edits + {OVERLAY_DST}/ to {args.checkout}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
