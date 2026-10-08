; SoulLink on the Polished Crystal 3.2.3 title screen (docs/polished/TITLE.md): the Crystal wordmark of
; patch/gen2/src/title.asm, in the Pokemon logo's own gold / blue / white, under the "CRYSTAL VERSION" banner.
; The patch version is not drawn here; version.asm prints it on the main menu.
;
; Art: tools/gen_gen1_title.py draws patch/gen2/src/title_logo_crystal.2bpp + title_rows_crystal.inc (9x2 tiles);
; tools/build_polished_companion.py copies them here as title_logo.2bpp / title_rows.inc (TITLE_ART). No new art.
;
; HOOK. _TitleScreen (engine/movie/title.asm:1, 35:4000) ends its setup with `call ChannelsOff / call EnableLCD`
; (:178-179); the `call EnableLCD` at 35:40eb (flat 0xD40EB, bytes cd da 24) is the only one in the routine. It is a
; same-size operand rewrite to the ROM0 bridge below, which far-calls the band and then jumps to EnableLCD, so the
; LCD-on ordering is the native one. The LCD has been off since :19 (DisableLCD) and rVBK is 0 again (:89-90), so
; VRAM is written directly. No native symbol moves.
;
; PLACEMENT. The title draws its text rows 0 (BG map 1), 3-9 and 12-17 (:40-86, :108-112, LoadSuicuneFrame :241);
; map rows 10-11 are written by nothing but ClearTileMap (:5) and the ' ' fill (:103-106). hSCY is 8 (:187-188), so
; they show on screen rows 9-10, directly under the banner on map row 9 (:77-80, cols 5-15). The band sits on map rows
; 10-11, tiles 6-14, in palette 6 (:71-74, the logo's lines 8-9: black, white, gold 26/21/0, blue 2/3/30 in
; gfx/title/title.pal -- the same order CRYSTAL_ROLES in gen_gen1_title.py paints), attribute bit 3 clear (VRAM bank 0).
;
; TILES. BG tile data is the $8800 mode: the logo is drawn from id $80 (:111) and TitleLogoGFX (logo_version.2bpp,
; 154 tiles) decompresses from vTiles1 (:93-95) through vTiles2 ids $00-$19 (logo $80-$0B, copyright $0C-$18 :115-118,
; FAITHFUL $19 :121-124). TitleSuicuneGFX (256 tiles, :22-28) fills VRAM BANK 1 only; TitleCrystalGFX is OBJ tiles in
; vTiles0 (:98-100). So bank-0 vTiles2 ids $1A-$7E are drawn by nothing on this screen ($7F is ' ', the clear tile),
; and the band's run [SLINK_TITLE_FIRST_TILE, +SLINK_TITLE_LOGO_TILES) is ASSERTed inside it.
;
; ENTRANCE. TitleScreenEntrance (engine/menus/intro_menu.asm, 01:6698) slides the logo in with an interlaced SCX
; shear over the first 80 lines (`ld bc, 8 * 10` / `ld b, 8 * 10 / 2`), i.e. map rows 1-10. The band's top row
; (map row 10, lines 72-79) would shear and its bottom row (lines 80-87) would not, so the builder widens both
; immediates to 88 lines (POLISHED_EDITS, same size), and the wordmark slides in with the logo. wLYOverrides holds
; 144 lines (05:de00-05:de90), so 88 fits.
;
; The tilemap goes to wTilemap, which UpdateBGMap mode 1 (set at :194-198 and by SuicuneFrameIterator) copies to BG
; map 0 (tiles only, home/video.asm:148-158); the attributes go straight to VRAM bank 1, as the title's own do.

DEF SLINK_TITLE_BAND_X EQU 6
DEF SLINK_TITLE_BAND_Y EQU 10
DEF SLINK_TITLE_BAND_W EQU 9
DEF SLINK_TITLE_BAND_PAL EQU 6 ; the logo's lines 8-9 (engine/movie/title.asm:71-74)

SECTION "SLink Title Bridge", ROM0[$3FA1]
; After the main-menu bridge (version.asm, ROM0[$3F92]..$3FA0) in the last free ROM0 gap; rgblink fails closed on any
; overlap, and the builder proves the bytes are $FF in the clean ROM.
SlinkTitleBridge::
	farcall SlinkTitleBand
	jp EnableLCD
SlinkTitleBridgeEnd::
ASSERT SlinkTitleBridgeEnd <= $4000

SECTION "SLink Title Band", ROMX[$5800], BANK[SLINK_SERVICE_BANK]
; Fixed above the trade commit ($5300-$5763), so no floating bank-$7E section moves.

INCLUDE "engine/slink/title_rows.inc" ; SLINK_TITLE_LOGO_TILES, SLINK_TITLE_FIRST_TILE and the logo rows

ASSERT SLINK_TITLE_FIRST_TILE >= $1A, "the band would overwrite the logo / copyright tiles in vTiles2"
ASSERT SLINK_TITLE_FIRST_TILE + SLINK_TITLE_LOGO_TILES <= $7F, "the band would overwrite the ' ' clear tile ($7F)"

SlinkTitleBand::
	ld hl, SlinkTitleTiles
	ld de, vTiles2 tile SLINK_TITLE_FIRST_TILE
	ld bc, SLINK_TITLE_LOGO_TILES tiles
	rst CopyBytes
	ld hl, SlinkTitleLogoRow0
	decoord SLINK_TITLE_BAND_X, SLINK_TITLE_BAND_Y
	ld bc, SLINK_TITLE_BAND_W
	rst CopyBytes
	ld hl, SlinkTitleLogoRow1
	decoord SLINK_TITLE_BAND_X, SLINK_TITLE_BAND_Y + 1
	ld bc, SLINK_TITLE_BAND_W
	rst CopyBytes
	ld a, 1
	ldh [rVBK], a
	hlbgcoord SLINK_TITLE_BAND_X, SLINK_TITLE_BAND_Y
	ld bc, SLINK_TITLE_BAND_W
	ld a, SLINK_TITLE_BAND_PAL
	rst ByteFill
	hlbgcoord SLINK_TITLE_BAND_X, SLINK_TITLE_BAND_Y + 1
	ld bc, SLINK_TITLE_BAND_W
	ld a, SLINK_TITLE_BAND_PAL
	rst ByteFill
	xor a
	ldh [rVBK], a
	ret

SlinkTitleTiles::
	INCBIN "engine/slink/title_logo.2bpp"
SlinkTitleTilesEnd::
ASSERT SlinkTitleTilesEnd - SlinkTitleTiles == SLINK_TITLE_LOGO_TILES tiles
SlinkTitleBandEnd::
