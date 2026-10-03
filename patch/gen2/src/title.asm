; SoulLink on the Gen 2 title screen: a wordmark in each game's own logo colours, centred under the game's subtitle.
; The patch version is not drawn here; it is on the main menu (version.asm).
; tools/gen_gen1_title.py draws the art (title_logo.2bpp, title_rows.inc: the same wordmark, 9x2 tiles for Crystal and 8x2
; for Gold/Silver, whose free tile ids are fewer).
;
; The hook is the single `call EnableLCD` that ends each title's setup (pokecrystal _TitleScreen, pokegold TitleScreen):
; same-size operand rewrite to the ROM0 bridge below, which far-calls the routine and then jumps to EnableLCD, so the
; LCD-on ordering is the vanilla one. The LCD is off there, so VRAM is written directly. No vanilla symbol moves.
;
; CRYSTAL. The vanilla "CRYSTAL VERSION" banner stays on row 9 (its pill is centred on x=83). Rows 10-11 are written by
; nothing. The title scrolls the BG up 8 pixels, so the logo's entrance (an interlaced slide, TitleScreenEntrance) runs
; over map rows 1-11 once the overlay widens it from 80 to 88 lines (tools/build_gen2_companion.py, TITLE_SHEAR_EDITS):
; the wordmark slides in with the logo instead of sitting half-sheared under it. It sits on rows 10-11, tiles 6-14, in
; palette 6, the Pokemon logo's own gold/blue/white, and BG tile ids $60-$7E, which the title never draws
; (tests/fixtures/gen2/). The tilemap goes to wTilemap, which the first BG map update copies; the attributes go to
; VRAM bank 1.
;
; GOLD / SILVER. The same wordmark, 8 tiles wide, on rows 7-8 (tiles 6-13) directly under the subtitle on row 6.
; Nothing on this title scrolls or shears, so there is no entrance to join. Ho-Oh / Lugia flies through this sky and is
; drawn in front of the wordmark, like any sprite over the BG (the BG-over-sprites attribute does not help: only non-zero
; colours take it, and the band's sky is one, so it would cut rectangular holes in the bird). Palette 1 (the logo's
; orange / grey / sky / navy) on CGB, and BG tile ids $70-$7F, which the title never draws. LoadTitleScreenTilemap
; already wrote the BG map in VRAM; so do we.

SECTION "SLink Title Bridge", ROM0
SlinkTitleBridge::
	ld a, BANK(SlinkTitleBand)
	ld hl, SlinkTitleBand
	rst FarCall
	jp EnableLCD

SECTION "SLink Title Band", ROMX, BANK[SLINK_SERVICE_BANK]

INCLUDE "engine/slink/title_rows.inc" ; SLINK_TITLE_LOGO_TILES, SLINK_TITLE_FIRST_TILE and the logo rows

IF !DEF(_GOLD) && !DEF(_SILVER) ; Crystal: pokecrystal's Makefile defines no _CRYSTAL

SlinkTitleBand:
	ld hl, SlinkTitleTiles
	ld de, vTiles2 tile SLINK_TITLE_FIRST_TILE
	ld bc, SLINK_TITLE_LOGO_TILES tiles
	call CopyBytes
	ld hl, SlinkTitleLogoRow0
	decoord 6, 10
	ld bc, 9
	call CopyBytes
	ld hl, SlinkTitleLogoRow1
	decoord 6, 11
	ld bc, 9
	call CopyBytes
	ld a, 1
	ldh [rVBK], a
	hlbgcoord 6, 10
	ld bc, 9
	ld a, 6 ; the Pokemon logo's gold
	call ByteFill
	hlbgcoord 6, 11
	ld bc, 9
	ld a, 6
	call ByteFill
	xor a
	ldh [rVBK], a
	ret

ELSE

SlinkTitleBand:
	ld hl, SlinkTitleTiles
	ld de, vTiles2 tile SLINK_TITLE_FIRST_TILE
	ld bc, SLINK_TITLE_LOGO_TILES tiles
	call CopyBytes
	ld hl, SlinkTitleLogoRow0
	debgcoord 6, 7
	ld bc, 8
	call CopyBytes
	ld hl, SlinkTitleLogoRow1
	debgcoord 6, 8
	ld bc, 8
	call CopyBytes
	ldh a, [hCGB]
	and a
	ret z
	ld a, 1
	ldh [rVBK], a
	hlbgcoord 6, 7
	ld bc, 8
	ld a, 1 ; the Pokemon logo's orange / grey / sky / navy
	call ByteFill
	hlbgcoord 6, 8
	ld bc, 8
	ld a, 1
	call ByteFill
	xor a
	ldh [rVBK], a
	ret

ENDC

SlinkTitleTiles:
	INCBIN "engine/slink/title_logo.2bpp"
