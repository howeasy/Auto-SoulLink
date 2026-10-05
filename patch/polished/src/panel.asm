; SLink companion overlay -- Polished Crystal v3.2.3 in-game panel (card POL-PANEL, Stage 2).
;
; The handshake is the shared GB one, unchanged: PANEL_STATE / PANEL_PAGE / PANEL_PAGES at
; wSlinkMailbox +9/+10/+11 (patch/gb/slink_abi.inc), AWAIT then STAGED, and A advances while B
; closes. Only the PAYLOAD differs from the vanilla Crystal overlay's panel, and it is the whole
; reason this file exists:
;
; Vanilla's panel is a lease on a graphics buffer. The host paints wTileMap/wAttrmap while the
; screen is hidden and the cartridge reveals it with WaitBGMap2. Polished has no WaitBGMap2
; (docs/polished/PANEL.md E7: "the port's central unknown"), so that port is blocked on a
; transfer primitive nobody has measured. This panel sidesteps it entirely by moving TEXT and not
; pixels: the host writes the page into the mailbox in the game's own charmap and the ROM hands
; it to PrintText. The text engine owns the tilemap (SetUpTextbox -> ClearSpeechBox ->
; ApplyTilemap), so there is no tile transfer, no new graphics tile, no hBGMapMode handshake and
; no attribute map -- and the page is a native text box, with the game's border, palettes, blink
; arrow and per-frame print, which is what "feel vanilla" actually means here.
;
; Wire: wSlinkPanelText (mailbox +34) is SLINK_PANEL_LINES fixed-stride lines of
; SLINK_PANEL_LINE_MAX glyphs, each closed by the game's string terminator (charmap `@`, $53).
; Both lines are space-padded by the host, so a page always fully overwrites the fallback below.
DEF SLINK_PANEL_LINES EQU 2
DEF SLINK_PANEL_LINE_MAX EQU 16
DEF SLINK_PANEL_STRIDE EQU SLINK_PANEL_LINE_MAX + 1
ASSERT SLINK_OFS_PANEL_TEXT + SLINK_PANEL_LINES * SLINK_PANEL_STRIDE <= SLINK_MAILBOX_SIZE
ASSERT wSlinkPanelText == wSlinkMailbox + SLINK_OFS_PANEL_TEXT

SECTION "SLink Panel", ROMX, BANK[SLINK_SERVICE_BANK]

SlinkPanel::
	ldh a, [hInMenu]
	push af
	ld a, TRUE
	ldh [hInMenu], a
	xor a
	ld [wSlinkMailbox + SLINK_OFS_PANEL_STATE], a
	ld [wSlinkMailbox + SLINK_OFS_PANEL_PAGE], a

.page
	; The fallback is printed FIRST and stays up until the host answers, so the screen is never
	; blank, a host that never stages a page leaves a native page behind, and a late host cannot
	; retype text the player has already read. Same lease discipline as the vanilla panel.
	ld hl, SlinkPanelFallback
	call PrintText
	ld a, SLINK_PANEL_AWAIT
	ld [wSlinkMailbox + SLINK_OFS_PANEL_STATE], a
	call .WaitForStage
	; A timeout closes the lease before the fallback is handed over.
	cp SLINK_PANEL_STAGED
	jr nz, .ready
	ld hl, SlinkPanelScript
	call PrintText
.ready
	; PrintText's prompt is the game's own <PROMPT> -> ButtonSound -> CheckIfAOrBPressed, which
	; leaves the accepted edge in hJoyDown. Consuming the opening A is that routine's job; no
	; release loop is needed and none is written.
	ldh a, [hJoyDown]
	and PAD_B | PAD_START
	jr nz, .close
	ld a, [wSlinkMailbox + SLINK_OFS_PANEL_STATE]
	cp SLINK_PANEL_STAGED
	jr nz, .close ; no client: A closes too; there is no paging into a fallback
	ldh a, [hJoyDown]
	and PAD_A
	jr z, .close
	ld a, [wSlinkMailbox + SLINK_OFS_PANEL_PAGE]
	inc a
	ld b, a
	ld a, [wSlinkMailbox + SLINK_OFS_PANEL_PAGES]
	cp b
	jr c, .close ; a zero page count is one page, as in the shared GB ABI
	jr z, .close ; A on the last page closes; there is no wrap to the first page
	ld a, b
	ld [wSlinkMailbox + SLINK_OFS_PANEL_PAGE], a
	jp .page

.close
	xor a
	ld [wSlinkMailbox + SLINK_OFS_PANEL_STATE], a
	ld [wSlinkMailbox + SLINK_OFS_PANEL_PAGE], a
	pop af
	ldh [hInMenu], a
	ret

.WaitForStage:
	ld b, 90
.poll
	call DelayFrame
	ld a, [wSlinkMailbox + SLINK_OFS_PANEL_STATE]
	cp SLINK_PANEL_STAGED
	ret z
	dec b
	jr nz, .poll
	ret

; Both strings are exactly SLINK_PANEL_LINE_MAX glyphs, space-padded, so printing the staged
SlinkPanelFallback:
	text "SOUL LINK       "
	next1 "NO CLIENT       "
	prompt

; <RAM> prints from WRAM until the terminator; <LNBRK> is one text row down. The two addresses
; are link-time constants because wSlinkPanelText lives in ram.o, and bank $7E is mapped while
; this runs (the ROM0 phone bridge switched to it), so the script is readable where it links.
SlinkPanelScript:
	db "<RAM>"
	dw wSlinkPanelText
	db "<LNBRK>"
	db "<RAM>"
	dw wSlinkPanelText + SLINK_PANEL_STRIDE
	db "@"
SlinkPanelEnd::
