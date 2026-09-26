; TITLE-VERSION part A (docs/gen2/POST_RC_CARDS.md): "SLINK vX.Y.Z" on the main menu at tile (1,10),
; clear of the menu box, both time boxes and the G/S debug menu. tools/build_gen2_companion.py
; defines SLINK_BUILD_VERSION from its required --version and rewrites the one `call SetUpMenu`
; (MainMenuJoypadLoop) to `call SlinkMainMenuBridge`, same size.
ASSERT DEF(SLINK_BUILD_VERSION), "the builder's --version defines SLINK_BUILD_VERSION"

SECTION "SLink Main Menu Bridge", ROM0
SlinkMainMenuBridge::
	; Print first so SetUpMenu's own ApplyTilemap shows it. SetUpMenu then runs in the caller's
	; bank: its item printer is a `call _hl_` into the main menu's bank.
	ld a, BANK(SlinkPrintVersion)
	ld hl, SlinkPrintVersion
	rst FarCall
	jp SetUpMenu

SECTION "SLink Version", ROMX, BANK[SLINK_SERVICE_BANK]
SlinkPrintVersion:
	hlcoord 1, 10
	ld de, .text
	jp PlaceString
.text
	db "SLINK {SLINK_BUILD_VERSION}@"
.end
ASSERT .end - .text - 1 <= SCREEN_WIDTH - 2
