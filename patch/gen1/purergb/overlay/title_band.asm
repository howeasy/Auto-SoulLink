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
