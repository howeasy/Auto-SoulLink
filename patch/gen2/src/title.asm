; SoulLink on the Gen 2 title screen: a logo in each game's own logo colours and the patch version.
; tools/gen_gen1_title.py draws the art (title_logo.2bpp, title_rows.inc: the same wordmark, 9x2 tiles for Crystal and 8x2
; for Gold/Silver, whose free tile ids are fewer); tools/build_gen2_companion.py renders the version (title_version.2bpp)
; from --version.
;
; The hook is the single `call EnableLCD` that ends each title's setup (pokecrystal _TitleScreen, pokegold TitleScreen):
; same-size operand rewrite to the ROM0 bridge below, which far-calls the routine and then jumps to EnableLCD, so the
; LCD-on ordering is the vanilla one. The LCD is off there, so VRAM is written directly. No vanilla symbol moves.
;
; CRYSTAL. The vanilla "CRYSTAL VERSION" banner stays on row 9. Rows 10-11 are written by nothing. The title scrolls
; the BG up 8 pixels, so the logo's entrance (an interlaced slide, TitleScreenEntrance) runs over map rows 1-11 once
; the overlay widens it from 80 to 88 lines (tools/build_gen2_companion.py, _title_shear_edits): the band slides in
; with the logo instead of sitting half-sheared under it. The logo (rows 10-11, tiles 3-11) and the version (row 11,
; tiles 12-19) use palette 6, the Pokemon logo's own gold/blue/white, and BG tile ids $60-$7E, which the title never
; draws (tests/fixtures/gen2/). The tilemap goes to wTilemap, which the first BG map update copies; the attributes go
; to VRAM bank 1.
;
; GOLD / SILVER. The same band, under the "GOLD/SILVER VERSION" subtitle (row 6): the logo on rows 7-8 (tiles 3-10),
; the version beside its second row (tiles 11-15). Nothing on this title scrolls or shears, so there is no entrance to
; join. Ho-Oh / Lugia flies through this sky and is drawn in front of the band, like any sprite over the BG (the
; BG-over-sprites attribute does not help: only non-zero colours take it, and the band's sky is one, so it would cut
; rectangular holes in the bird). Palette 1 (the logo's orange / grey / sky / navy) on CGB, and BG tile ids $70-$7F, $60-$63 and
; $51, which the title never draws. LoadTitleScreenTilemap already wrote the BG map in VRAM; so do we.
ASSERT DEF(SLINK_BUILD_VERSION), "the builder's --version defines SLINK_BUILD_VERSION"

SECTION "SLink Title Bridge", ROM0
SlinkTitleBridge::
	ld a, BANK(SlinkTitleBand)
	ld hl, SlinkTitleBand
	rst FarCall
	jp EnableLCD

SECTION "SLink Title Band", ROMX, BANK[SLINK_SERVICE_BANK]

INCLUDE "engine/slink/title_rows.inc" ; SLINK_TITLE_LOGO_TILES, SLINK_TITLE_FIRST_TILE and the logo rows

IF !DEF(_GOLD) && !DEF(_SILVER) ; Crystal: pokecrystal's Makefile defines no _CRYSTAL

DEF SLINK_TITLE_VERSION_TILES EQU 8

SlinkTitleBand:
	ld hl, SlinkTitleTiles
	ld de, vTiles2 tile SLINK_TITLE_FIRST_TILE
	ld bc, (SLINK_TITLE_LOGO_TILES + SLINK_TITLE_VERSION_TILES) tiles
	call CopyBytes
	ld hl, SlinkTitleLogoRow0
	decoord 3, 10
	ld bc, 9
	call CopyBytes
	ld hl, SlinkTitleLogoRow1
	decoord 3, 11
	ld bc, 9
	call CopyBytes
	ld hl, SlinkTitleVersionRow
	decoord 12, 11
	ld bc, SLINK_TITLE_VERSION_TILES
	call CopyBytes
	ld a, 1
	ldh [rVBK], a
	hlbgcoord 0, 10
	ld bc, 2 * TILEMAP_WIDTH
	ld a, 6 ; the Pokemon logo's gold
	call ByteFill
	xor a
	ldh [rVBK], a
	ret

SlinkTitleVersionRow:
FOR i, SLINK_TITLE_VERSION_TILES
	db SLINK_TITLE_FIRST_TILE + SLINK_TITLE_LOGO_TILES + i
ENDR

ELSE

DEF SLINK_TITLE_VERSION_TILES EQU 5

SlinkTitleBand:
	ld hl, SlinkTitleTiles
	ld de, vTiles2 tile SLINK_TITLE_FIRST_TILE
	ld bc, SLINK_TITLE_LOGO_TILES tiles
	call CopyBytes
	ld de, vTiles2 tile $60 ; the version's first four tiles, then its fifth, in the free ids
	ld bc, 4 tiles
	call CopyBytes
	ld de, vTiles2 tile $51
	ld bc, 1 tiles
	call CopyBytes
	ld hl, SlinkTitleLogoRow0
	debgcoord 3, 7
	ld bc, 8
	call CopyBytes
	ld hl, SlinkTitleLogoRow1
	debgcoord 3, 8
	ld bc, 8
	call CopyBytes
	ld hl, SlinkTitleVersionRow
	debgcoord 11, 8
	ld bc, SLINK_TITLE_VERSION_TILES
	call CopyBytes
	ldh a, [hCGB]
	and a
	ret z
	ld a, 1
	ldh [rVBK], a
	hlbgcoord 3, 7
	ld bc, 8
	ld a, 1 ; the Pokemon logo's orange / grey / sky / navy
	call ByteFill
	hlbgcoord 3, 8
	ld bc, 8 + SLINK_TITLE_VERSION_TILES
	ld a, 1
	call ByteFill
	xor a
	ldh [rVBK], a
	ret

SlinkTitleVersionRow:
	db $60, $61, $62, $63, $51

ENDC

SlinkTitleTiles:
	INCBIN "engine/slink/title_logo.2bpp"
	INCBIN "engine/slink/title_version.2bpp"
