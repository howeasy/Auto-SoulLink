; ---- the main menu ---------------------------------------------------------------------------
; engine/menus/main_menu.asm draws its box at (0,0), rows 0-7 with a save file and 0-5 without (TextBoxBorder takes b+2
; rows), and pureRGB prints its own version at (0, 17). Row 16 is the last full-width row both layouts leave alone and it
; sits directly above pureRGB's line, so the two read as one footer. The save-file and no-save-file branches both fall
; into .next2, so a single hook covers both layouts; it runs inside the DisableTextDelay window the menu opens before its
; boxes, so PlaceString has no per-letter delay, and the menu's own clears are all followed by .mainMenuLoop, which draws
; this again.
;
; Choosing CONTINUE draws DisplayContinueGameInfo's box over rows 7-16 from column 4, and its bottom border cuts this line,
; so .choseContinue (apply_purergb_overlay.py) blanks the four cells left of the box first.
;
; Identical for Red, Blue and Green: nothing on this screen is title-conditional. A farcall, not a call: MainMenu is in
; ROMX bank $01 and this file is in $3F.

SECTION "SLink main menu version", ROMX

INCLUDE "engine/slink/main_menu_version.inc" ; tools/build_purergb_overlay.py writes it from --version

SlinkMainMenuVersion::
	hlcoord SLINK_MENU_VERSION_X, SLINK_MENU_VERSION_Y
	ld de, SlinkMenuVersionText
	jp PlaceString
