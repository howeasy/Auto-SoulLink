; slink.asm - mailbox, VBlank hook, overworld foreground hook and the SLINK panel.
; Ported from patch/gen1/src/slink.asm (vanilla Red/Blue); see that file for the design notes
; on the hook site, the silent SFX request and the panel's screen-ownership sequence.

DEF SLINK_ABI_VERSION  EQU 3
DEF SLINK_CAP_SFX      EQU 1 << 0
DEF SLINK_CAP_PANEL    EQU 1 << 1

; Panel handshake. The client may paint only in AWAIT, and must stop at CLOSED.
DEF SLINK_PANEL_CLOSED EQU 0
DEF SLINK_PANEL_AWAIT  EQU 1
DEF SLINK_PANEL_STAGED EQU 2

; How long to wait for the client to paint a screen before showing the fallback (~1.5 s).
DEF SLINK_STAGE_TIMEOUT EQU 90

; The 12-byte ABI-3 mailbox, linker-placed in the WRAMX bank-1 tail after "Current Box Data"
; ($DEEA; 22 bytes are free before the stack at $DF00). WRAM0 and HRAM have zero free bytes.
SECTION "SLink Mailbox", WRAMX

wSlinkMailbox::
wSlinkBeacon::       ds 4 ; +0..3  'SLNK', rewritten every VBlank
wSlinkAbi::          db   ; +4     ABI version
wSlinkFrameCounter:: dw   ; +5..6  16-bit frame counter
wSlinkSfxRequest::   db   ; +7     SFX request: drained to 0, never played (see the vanilla notes)
wSlinkCaps::         db   ; +8     capability bits
wSlinkPanelState::   db   ; +9     panel state: CLOSED / AWAIT / STAGED
wSlinkPanelPage::    db   ; +10    page wanted, ours to the client
wSlinkPanelPages::   db   ; +11    page count, the client's to us (0 reads as one)
wSlinkMailboxEnd::


SECTION "SLink Hook", ROMX

; Runs from VBlank in place of `farcall TrackPlayTime` (home/vblank.asm) and calls it once.
; pureRGB is GBC-aware: engine/gfx/palettes.asm's buffer loop selects WRAM bank 2 with
; interrupts enabled, so a VBlank landing inside it would otherwise write the mailbox into
; bank 2. Save, force bank 1, write, restore. On DMG rWBK is unmapped and this is a no-op.
SlinkHook::
	ldh a, [rWBK]
	push af
	ld a, 1
	ldh [rWBK], a

	ld a, $53 ; "SLNK" as bytes: the preincluded charmap would turn 'S' into $92
	ld [wSlinkBeacon + 0], a
	ld a, $4C
	ld [wSlinkBeacon + 1], a
	ld a, $4E
	ld [wSlinkBeacon + 2], a
	ld a, $4B
	ld [wSlinkBeacon + 3], a
	ld a, SLINK_ABI_VERSION
	ld [wSlinkAbi], a
	; Panel only: the VBlank PlaySound path is not safe (vanilla slink.asm), so SFX is not claimed.
	ld a, SLINK_CAP_PANEL
	ld [wSlinkCaps], a

	; 16-bit little-endian frame counter; `inc [hl]` sets Z on wrap.
	ld hl, wSlinkFrameCounter
	inc [hl]
	jr nz, .noCarry
	inc hl
	inc [hl]
.noCarry

	; SFX request: consumed so a client never sees stale state, deliberately never played.
	xor a
	ld [wSlinkSfxRequest], a

	pop af
	ldh [rWBK], a

	; Run the code the hook displaced, then hand control back to VBlank. Bankswitch is
	; re-entrant (it keeps the caller's bank on the stack), so the nested farcall is safe.
	farcall TrackPlayTime
	ret

; Runs once per overworld frame, right after `rst _DelayFrame` at OverworldLoop
; (home/overworld.asm). Replaces the vanilla patch's DelayFrame RST bridge, which cannot exist
; here (pureRGB's RST $00/$18 slots are live code). Same predicate: the foreground trade
; service runs only while the lease's availability byte (+10) reads 1.
SlinkForeground::
	ld a, [wSerialPartyMonsPatchList + 10]
	dec a
	ret nz
	jp SlinkTradeService


; The SLINK panel. Opened from the START-menu row through SlinkStartMenuEntry (ROM0). The
; screen-ownership sequence is StartMenu_TrainerInfo's (engine/menus/start_sub_menus.asm)
; with our draw substituted, so tearing, tile animations, sprites and palettes are handled
; the way the engine already handles them. Every routine it calls lives in the home bank.
SECTION "SLink Panel", ROMX

SlinkPanel::
	call GBPalWhiteOut
	call ClearScreen
	call UpdateSprites
	ldh a, [hTileAnimations]
	push af
	xor a
	ldh [hTileAnimations], a

	; Hide the overworld sprites: UpdateSprites never clears OAM; a 0 here makes
	; PrepareOAMData hide them once (engine/gfx/sprite_oam.asm). Saved and restored rather
	; than assumed to be 1, as the item menu does.
	ld a, [wUpdateSpritesEnabled]
	push af
	xor a
	ld [wUpdateSpritesEnabled], a

	; Start at page 0, and clear a stale count from a previous open.
	xor a
	ld [wSlinkPanelPage], a
	ld [wSlinkPanelPages], a

.page
	; Fallback first, so a timeout shows something that explains itself. A client that is
	; attached paints over it (all eighteen rows, padded).
	call SlinkDrawFallback

	; Hand the screen to the client while it is still white: a torn page is impossible.
	ld a, SLINK_PANEL_AWAIT
	ld [wSlinkPanelState], a
	call SlinkWaitForStage      ; returns a = the state we gave up on
	push af                     ; remember whether a client actually answered

	call Delay3                 ; let the auto-BG transfers carry wTileMap into VRAM
	call GBPalNormal            ; reveal, once and whole
	call SlinkWaitForButton     ; returns a = the buttons that were pressed
	ld c, a
	pop af

	; No client answered, so there are no pages to turn: any button closes.
	cp SLINK_PANEL_STAGED
	jr nz, .close

	; A advances, B and START close.
	ld a, c
	and PAD_A
	jr z, .close

	; ...but only while there IS a next page: the client publishes the count, 0 = one page.
	ld a, [wSlinkPanelPage]
	inc a
	ld b, a
	ld a, [wSlinkPanelPages]
	cp b
	jr c, .close                ; pages < page+1  -> that was the last one
	jr z, .close                ; pages == page+1 -> ditto
	ld a, b
	ld [wSlinkPanelPage], a
	call GBPalWhiteOut          ; hide the repaint, exactly as on the way in
	jr .page

.close
	xor a
	ld [wSlinkPanelState], a    ; closed: the client must stop painting
	ld [wSlinkPanelPage], a

	call GBPalWhiteOut
	call LoadFontTilePatterns
	call LoadScreenTilesFromBuffer2
	call RunDefaultPaletteCommand
	call ReloadMapData
	pop af
	ld [wUpdateSpritesEnabled], a   ; sprites come back with the map
	call LoadGBPal
	pop af
	ldh [hTileAnimations], a
	ret

; Wait for the player to dismiss the panel. Not WaitForTextScrollButtonPress: that runs the
; Cable Club predef and cannot tell A from B. hJoyPressed is edge-triggered; the settle loop
; covers a client that stages instantly while the opening A press is still down.
SlinkWaitForButton:
	ld b, 20
.settle
	call DelayFrame
	dec b
	jr nz, .settle
.wait
	call DelayFrame
	call Joypad
	ldh a, [hJoyPressed]
	and PAD_A | PAD_B | PAD_START
	ret nz                      ; caller reads WHICH buttons out of a
	jr .wait

; Poll the mailbox for up to SLINK_STAGE_TIMEOUT frames. Returns either way.
SlinkWaitForStage:
	ld b, SLINK_STAGE_TIMEOUT
.loop
	ld a, [wSlinkPanelState]
	cp SLINK_PANEL_STAGED
	ret z                       ; a = STAGED: a client answered
	push bc
	call DelayFrame
	pop bc
	dec b
	jr nz, .loop
	ld a, [wSlinkPanelState]    ; a = whatever it still is: nobody answered
	ret

SlinkDrawFallback:
	hlcoord 2, 2
	ld de, .title
	call PlaceString
	hlcoord 2, 5
	ld de, .noData
	call PlaceString
	ret
; pureRGB's charmap is preincluded, so these are ordinary strings (the vanilla patch had to
; scope a private charmap here).
.title
	db "SOUL LINK@"
.noData
	db "NO CLIENT@"
