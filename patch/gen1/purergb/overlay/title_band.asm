; SoulLink on pureRGB's title screen: a logo in the Pokemon logo's style and the patch version, in
; the 16 pixel band (tile rows 8-9) that holds the game's own "Red Version" line. tools/gen_gen1_title.py
; draws the logo (title_logo.2bpp, title_band_rows.inc); tools/build_purergb_overlay.py renders the
; version (title_version.2bpp) from its --version. The Red Version / Blue Version / Green Version
; line itself is the game's own, moved right by the hook in engine/movie/title.asm.
;
; Only the vanilla-style title gets the band. The opt-in Pure title (BIT_NEW_TITLE_SCREEN, which is
; only ever set after a save has been loaded: Init zero-fills WRAM) animates the version cells in rows
; 7-8 itself and would corrupt or overwrite ours, so the hook falls through to the original printer
; there and this routine never runs.
;
; Tile ids $60-$79 are free on the vanilla-style title (nothing in engine/movie/title.asm loads or
; places them; the blinking mon starts at $7A) and all of them are >= $60, so PlaceString prints
; them as plain tiles. The logo takes $60-$71 and the version $72-$79, one contiguous copy.
;
; The mon swap in engine/movie/title2.asm raster-scrolls from scanline $48 (tile row 9), where the
; logo's second row sits; the overlay moves that start line to $50 (tile row 10, where the mon
; starts) so the band stays still.

SECTION "SLink title band", ROMX

INCLUDE "engine/slink/title_band_rows.inc" ; the tile-id constants and the two logo rows

DEF SLINK_TITLE_VERSION_TILES EQU 8
DEF SLINK_TITLE_LOGO_X EQU 1
IF DEF(_GREEN) ; "Green Version" is nine tiles: it starts one tile further left, and the version follows it
DEF SLINK_TITLE_VERSION_X EQU 10
ELSE
DEF SLINK_TITLE_VERSION_X EQU 11
ENDC

SlinkTitleBand::
	ld de, SlinkTitleTiles
	ld hl, vChars2 tile SLINK_TITLE_FIRST_TILE
	lb bc, BANK(SlinkTitleTiles), SLINK_TITLE_LOGO_TILES + SLINK_TITLE_VERSION_TILES
	call CopyVideoData
	hlcoord SLINK_TITLE_LOGO_X, 8
	ld de, SlinkTitleLogoRow0
	call PlaceString
	hlcoord SLINK_TITLE_LOGO_X, 9
	ld de, SlinkTitleLogoRow1
	call PlaceString
	hlcoord SLINK_TITLE_VERSION_X, 9
	ld de, SlinkTitleVersionRow
	jp PlaceString

SlinkTitleVersionRow:
FOR i, SLINK_TITLE_VERSION_TILES
	db SLINK_TITLE_FIRST_TILE + SLINK_TITLE_LOGO_TILES + i
ENDR
	db $50

SlinkTitleTiles:
	INCBIN "engine/slink/title_logo.2bpp"
IF DEF(_GREEN)
	INCBIN "engine/slink/title_version_green.2bpp"
ELSE
	INCBIN "engine/slink/title_version.2bpp"
ENDC

; ---- the opt-in Pure title ---------------------------------------------------------------------
; It has no room for the logo: of the BG tile ids, only $62 $67 $6C and $71-$79 are never drawn between the
; banner animation and the idle loop (tests/fixtures/gen1/title_refs_pure*.json), 12 in all. So it gets one line
; of text, "SoulLink vX.Y.Z", on tile row 9 under the PureRed banner, rendered by build_purergb_overlay.py
; (title_line.2bpp). The player-pointing pose (PureTitlePlayerSpritePointing, vChars2 tile $4F-$78) overwrites
; those ids when the player presses a button, so the hook clears the row first.

DEF SLINK_PURE_LINE_CELLS EQU 12
DEF SLINK_PURE_LINE_X EQU 5

SlinkTitleLinePure::
	ld de, SlinkTitleLineTiles
	ld hl, vChars2 tile $62
	lb bc, BANK(SlinkTitleLineTiles), 1
	call CopyVideoData
	ld de, SlinkTitleLineTiles + 1 * TILE_SIZE
	ld hl, vChars2 tile $67
	lb bc, BANK(SlinkTitleLineTiles), 1
	call CopyVideoData
	ld de, SlinkTitleLineTiles + 2 * TILE_SIZE
	ld hl, vChars2 tile $6C
	lb bc, BANK(SlinkTitleLineTiles), 1
	call CopyVideoData
	ld de, SlinkTitleLineTiles + 3 * TILE_SIZE
	ld hl, vChars2 tile $71
	lb bc, BANK(SlinkTitleLineTiles), 9
	call CopyVideoData
	hlcoord SLINK_PURE_LINE_X, 9
	ld de, SlinkTitleLineRow
	jp PlaceString

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
	db $62, $67, $6C, $71, $72, $73, $74, $75, $76, $77, $78, $79, $50

SlinkTitleLineTiles:
	INCBIN "engine/slink/title_line.2bpp"
