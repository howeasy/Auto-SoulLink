; P4.1e: native main-thread panel, shared gb_panel.lua mailbox handshake.
; No direct SRAM, party or bag writes. Native StartMenu return 6 restores
; the window, tileset, palettes and sprite updates after this function returns.
SECTION "SLink Panel", ROMX, BANK[SLINK_SERVICE_BANK]

SlinkPanel::
	ldh a, [hInMenu]
	push af
	ld a, TRUE
	ldh [hInMenu], a
	xor a
	ld [wSlinkMailbox + SLINK_OFS_PANEL_STATE], a
	ld [wSlinkMailbox + SLINK_OFS_PANEL_PAGE], a
	ld [wSlinkMailbox + SLINK_OFS_PANEL_PAGES], a

	; FadeToMenu has hidden the map. Establish the standard text palette's
	; original colors and zero attributes; reveal only after tile+attr transfer.
	ld b, SCGB_DIPLOMA
	call GetSGBLayout

.page
	; ClearBGPalettes waits four frames: CLOSED is observed before first AWAIT,
	; and STAGED is observed before a later page. All painting remains hidden.
	call ClearBGPalettes
	call ClearTilemap
	ld hl, wAttrmap
	ld bc, SCREEN_AREA
	xor a
	call ByteFill
	hlcoord 2, 2
	ld de, .title
	call PlaceString
	hlcoord 2, 4
	ld de, .fallback
	call PlaceString
	xor a
	ldh [hBGMapMode], a
	ld a, SLINK_PANEL_AWAIT
	ld [wSlinkMailbox + SLINK_OFS_PANEL_STATE], a
	call .WaitForStage
	; Timeout closes the write lease BEFORE revealing the fallback. A late
	; client cannot paint after this screen has become visible.
	cp SLINK_PANEL_STAGED
	jr z, .ready
	xor a
	ld [wSlinkMailbox + SLINK_OFS_PANEL_STATE], a
.ready
	call WaitBGMap2 ; native transfer: CGB attributes first, then the tilemap
	call SetDefaultBGPAndOBP
	call .WaitForButton
	ld c, a ; capture AFTER JoyTextDelay; it may change working registers
	and PAD_B | PAD_START
	jr nz, .close
	ld a, [wSlinkMailbox + SLINK_OFS_PANEL_STATE]
	cp SLINK_PANEL_STAGED
	jr nz, .close ; no client: A also closes; no paging into fallback
	ld a, c
	and PAD_A
	jr z, .close
	ld a, [wSlinkMailbox + SLINK_OFS_PANEL_PAGE]
	inc a
	ld b, a
	ld a, [wSlinkMailbox + SLINK_OFS_PANEL_PAGES]
	cp b
	jr c, .close ; zero page count is one page, as in the shared Gen 1 ABI
	jr z, .close ; A on last page closes; there is no wrap to the first page
	ld a, b
	ld [wSlinkMailbox + SLINK_OFS_PANEL_PAGE], a
	jr .page

.close
	xor a
	ld [wSlinkMailbox + SLINK_OFS_PANEL_STATE], a
	ld [wSlinkMailbox + SLINK_OFS_PANEL_PAGE], a
	ld [wSlinkMailbox + SLINK_OFS_PANEL_PAGES], a
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

.WaitForButton:
	; Consume the opening A/held key before accepting a new edge. GetJoypad
	; updates hJoyDown, and JoyTextDelay exposes the new edge in hJoyPressed.
.release
	call DelayFrame
	call JoyTextDelay
	ldh a, [hJoyDown]
	and PAD_A | PAD_B | PAD_START
	jr nz, .release
.press
	call DelayFrame
	call JoyTextDelay
	ldh a, [hJoyPressed]
	and PAD_A | PAD_B | PAD_START
	jr z, .press
	ret

.title:
	db "SOUL LINK@"
.fallback:
	db "NO CLIENT@"
SlinkPanelEnd::
