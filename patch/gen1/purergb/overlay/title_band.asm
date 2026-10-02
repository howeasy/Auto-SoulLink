; SoulLink on pureRGB's title screen: a logo in the Pokemon logo's style in the 16 pixel band (tile rows 8-9)
; that holds the game's own "Red Version" line. tools/gen_gen1_title.py draws the logo (title_logo.2bpp,
; title_band_rows.inc). The Red Version / Blue Version / Green Version line itself is the game's own, moved right
; and down onto the wordmark's baseline by the hook in engine/movie/title.asm. The patch version is not drawn here;
; it is on the main menu (main_menu_version.asm).
;
; Only the vanilla-style title gets the band. The opt-in Pure title (BIT_NEW_TITLE_SCREEN, which is
; only ever set after a save has been loaded: Init zero-fills WRAM) animates the version cells in rows
; 7-8 itself and would corrupt or overwrite ours, so the hook falls through to the original printer
; there and this routine never runs.
;
; Tile ids $60-$71 are free on the vanilla-style title (nothing in engine/movie/title.asm loads or
; places them; the blinking mon starts at $7A) and all of them are >= $60, so PlaceString prints
; them as plain tiles.
;
; The mon swap in engine/movie/title2.asm raster-scrolls from scanline $48 (tile row 9), where the
; logo's second row sits; the overlay moves that start line to $50 (tile row 10, where the mon
; starts) so the band stays still.

SECTION "SLink title band", ROMX

INCLUDE "engine/slink/title_band_rows.inc" ; the tile-id constants and the two logo rows

DEF SLINK_TITLE_LOGO_X EQU 1

SlinkTitleBand::
	ld de, SlinkTitleTiles
	ld hl, vChars2 tile SLINK_TITLE_FIRST_TILE
	lb bc, BANK(SlinkTitleTiles), SLINK_TITLE_LOGO_TILES
	call CopyVideoData
	hlcoord SLINK_TITLE_LOGO_X, 8
	ld de, SlinkTitleLogoRow0
	call PlaceString
	hlcoord SLINK_TITLE_LOGO_X, 9
	ld de, SlinkTitleLogoRow1
	jp PlaceString

SlinkTitleTiles:
	INCBIN "engine/slink/title_logo.2bpp"

; ---- the opt-in Pure title ---------------------------------------------------------------------
; It has no room for the logo: of the BG tile ids only $62 $67 $6C and $71-$79 are never drawn between the banner
; animation and the idle loop (tests/fixtures/gen1/title_refs_pure*.json). So it gets one line, "SoulLink", on tile row 9
; under the PureRed banner, set in the banner's own bold dark-red lettering (tools/gen_gen1_title.py: title_line.2bpp,
; 6 tiles). The patch version is not drawn here; it is on the main menu. The player-pointing pose
; (PureTitlePlayerSpritePointing, vChars2 tile $4F-$78) overwrites those ids when the player presses a button, so the
; hook clears the row first.

DEF SLINK_PURE_LINE_CELLS EQU 6
DEF SLINK_PURE_LINE_X EQU 7

SlinkTitleLinePure::
	ld de, SlinkTitleLineTiles
	ld hl, vChars2 tile $72
	lb bc, BANK(SlinkTitleLineTiles), SLINK_PURE_LINE_CELLS
	call CopyVideoData
	; The PureRed banner above reveals itself letter by letter, so the line types in one cell at a time too
	; (wTileMap goes to VRAM every vblank on this screen). The row's own bytes stay plain tile ids, no PlaceString.
	hlcoord SLINK_PURE_LINE_X, 9
	ld de, SlinkTitleLineRow
	ld b, SLINK_PURE_LINE_CELLS
.reveal
	ld a, [de]
	inc de
	ld [hli], a
	push hl
	push de
	push bc
	ld c, 3
	call DelayFrames
	pop bc
	pop de
	pop hl
	dec b
	jr nz, .reveal
	ret

SlinkTitleLinePureClear::
	hlcoord SLINK_PURE_LINE_X, 9
	ld a, $7F
	ld b, SLINK_PURE_LINE_CELLS
.loop
	ld [hli], a
	dec b
	jr nz, .loop
	ret

SlinkTitleLineRow:
	db $72, $73, $74, $75, $76, $77, $50

SlinkTitleLineTiles:
	INCBIN "engine/slink/title_line.2bpp"
