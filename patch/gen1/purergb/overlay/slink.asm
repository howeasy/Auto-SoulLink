; slink.asm - mailbox, VBlank hook, overworld foreground hook, the SFX service and the SLINK
; panel. Ported from patch/gen1/src/slink.asm (vanilla Red/Blue); see that file for the design
; notes on the hook site, the main-thread SFX dispatch and the panel's screen-ownership sequence.

DEF SLINK_ABI_VERSION  EQU 3
DEF SLINK_CAP_SFX      EQU 1 << 0
DEF SLINK_CAP_PANEL    EQU 1 << 1
DEF SLINK_CAP_SFX_NOTIFY EQU 1 << 2   ; knows SFX code 4 (an older build drops it unplayed)
DEF SLINK_CAP_TRADE  EQU 1 << 4   ; patch/gb/slink_abi.inc; set when slink_overlay.asm links trade

; Panel handshake. The client may paint only in AWAIT, and must stop at CLOSED.
DEF SLINK_PANEL_CLOSED EQU 0
DEF SLINK_PANEL_AWAIT  EQU 1
DEF SLINK_PANEL_STAGED EQU 2

; How long to wait for the client to paint a screen before showing the fallback (~1.5 s).
DEF SLINK_STAGE_TIMEOUT EQU 90

; The 14-byte ABI-3 mailbox, linker-placed in the WRAMX bank-1 tail after "Current Box Data"
; ($DEEA; 22 bytes are free before the stack at $DF00). WRAM0 and HRAM have zero free bytes.
SECTION "SLink Mailbox", WRAMX

wSlinkMailbox::
wSlinkBeacon::       ds 4 ; +0..3  'SLNK', rewritten every VBlank
wSlinkAbi::          db   ; +4     ABI version
wSlinkFrameCounter:: dw   ; +5..6  16-bit frame counter
wSlinkSfxRequest::   db   ; +7     SFX request: a semantic code (1 success, 2 failure, 3 boo, 4 notify),
                          ;        played by SlinkSfxService on the main thread and zeroed
wSlinkCaps::         db   ; +8     capability bits
wSlinkPanelState::   db   ; +9     panel state: CLOSED / AWAIT / STAGED
wSlinkPanelPage::    db   ; +10    page wanted, ours to the client
wSlinkPanelPages::   db   ; +11    page count, the client's to us (0 reads as one)
wSlinkSfxHold::      db   ; +12    ROM-private: nonzero while a request is being held
wSlinkSfxHoldAt::    db   ; +13    ROM-private: frame counter low byte when the hold began
wSlinkMailboxEnd::

; Bounded hold, in FRAMES of the mailbox's own counter (the vanilla note explains why not
; in service calls): GET_ITEM_2 owns CHAN5 for ~180 frames and a request behind it must wait.
DEF SLINK_SFX_HOLD_MAX EQU 240
DEF SLINK_SFX_CODES    EQU 4


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
	; Panel and SFX (the SFX request is served on the main thread, SlinkSfxService, never
	; here), plus trade when slink_overlay.asm links it (the patch/gen2/src/slink.asm pattern).
DEF SLINK_BUILD_CAPS EQU SLINK_CAP_PANEL | SLINK_CAP_SFX | SLINK_CAP_SFX_NOTIFY
IF DEF(SLINK_TRADE_ENABLED)
REDEF SLINK_BUILD_CAPS EQU SLINK_BUILD_CAPS | SLINK_CAP_TRADE
ENDC
	ld a, SLINK_BUILD_CAPS
	ld [wSlinkCaps], a

	; 16-bit little-endian frame counter; `inc [hl]` sets Z on wrap.
	ld hl, wSlinkFrameCounter
	inc [hl]
	jr nz, .noCarry
	inc hl
	inc [hl]
.noCarry

	; The SFX request is NOT touched here: clearing it from VBlank would eat it before the
	; main thread looked (the ABI-2 lesson in the vanilla notes: VBlank must never PlaySound).

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
	; Only on a frame where vanilla could open the START menu and SAVE (OverworldLoop):
	; no step, ledge hop, scripted movement, START ignore, pending battle, Safari end or
	; warp. The prompt opens text and both roles save, so mid-step pickup would misdraw
	; the map and save a half step.
	ld a, [wWalkCounter]
	ld hl, wCurOpponent
	or [hl]
	ld hl, wSafariZoneGameOver
	or [hl]
	ret nz
	ld a, [wJoyIgnore]
	and PAD_START
	ret nz
	ld a, [wMovementFlags]
	and 1 << BIT_LEDGE_OR_FISHING
	ret nz
	ld a, [wStatusFlags5]
	and 1 << BIT_SCRIPTED_MOVEMENT_STATE
	ret nz
	ld a, [wStatusFlags3]
	and 1 << BIT_WARP_FROM_CUR_SCRIPT
	ret nz
	ld a, [wStatusFlags6]
	and (1 << BIT_FLY_WARP) | (1 << BIT_DUNGEON_WARP)
	ret nz
	jp SlinkTradeService


; ── Main-thread SFX dispatch ─────────────────────────────────────────────────────────────
; Reached from two ROM0 sites in slink_home.asm, both idempotent (the first consumes it):
; SlinkDelayFrameTail after every VBlank wait, and SlinkJoypadSite from Joypad, because a menu
; waiting for input spins in HandleMenuInput_ on JoypadLowSensitivity and never reaches
; DelayFrame. The vanilla slink.asm carries the full design note; the pureRGB deltas are:
;   * every symbol is the linker's (no address literals), including the sound ids and the
;     audio banks (BANK(Audio1_PlaySound) / BANK(Audio2_PlaySound));
;   * the low-health alarm's "tones playing" flag is bit 7 of wLowHealthTonePairs (WRAM0),
;     the byte pureRGB's own WaitForSoundToFinish tests (home/delay.asm), not wLowHealthAlarm
;     (WRAMX);
;   * the mailbox is WRAMX bank 1, so rWBK is saved, forced to 1 and restored around the
;     whole service, exactly as SlinkHook does;
;   * PlaySound is safe to call from bank $3F: DetermineAudioFunction keeps the caller's bank
;     on the stack (home/audio.asm).
; Clobbers a, bc, hl; the callers save them.
SlinkSfxService::
	ldh a, [rWBK]
	push af
	ld a, 1
	ldh [rWBK], a
	call .service
	pop af
	ldh [rWBK], a
	ret

.service
	ld a, [wSlinkSfxRequest]
	and a
	ret z
	cp SLINK_SFX_CODES + 1
	jr nc, .drop                ; unknown code: consumed, never played

	; Hold while a music fade runs: PlaySound would return without playing.
	ld a, [wAudioFadeOutControl]
	and a
	jr nz, .hold

	; Hold while an SFX still owns CHAN5/6/8 (the engine drops a higher id on a busy
	; channel), unless the low-health alarm has CHAN5 for the rest of the battle.
	ld a, [wLowHealthTonePairs]
	bit 7, a
	jr nz, .play
	ld hl, wChannelSoundIDs + CHAN5
	xor a
	or [hl]
	inc hl
	or [hl]
	inc hl
	inc hl
	or [hl]
	jr nz, .hold

.play
	xor a
	ld [wSlinkSfxHold], a       ; whatever was held ends here
	; Resolve the code for the audio bank loaded NOW, with PlaySound's own bank choice.
	ld hl, .bankAudio1
	ld a, [wAudioROMBank]
	cp BANK(Audio1_PlaySound)
	jr z, .row
	ld hl, .bankAudio2
	cp BANK(Audio2_PlaySound)
	jr z, .row
	ld hl, .bankAudio3
.row
	ld a, [wSlinkSfxRequest]
	dec a                       ; codes are 1-based
	ld c, a
	ld b, 0
	add hl, bc
	ld b, [hl]
	; While the low-health alarm owns CHAN5 it re-marks it with CRY_SFX_END and the engine
	; rejects any higher id there, so TINK/DENIED would be consumed into silence; the one id
	; that channel accepts is CRY_SFX_END itself = SFX_LEVEL_UP in the battle bank (the way
	; the vanilla level-up jingle plays through the alarm). Battle end zeroes the flag.
	; START_MENU is CHAN8-only, which the alarm never marks, so the notify blip plays as is.
	ld a, b
	cp SFX_START_MENU
	jr z, .resolved
	ld a, [wAudioROMBank]
	cp BANK(Audio2_PlaySound)
	jr nz, .resolved
	ld a, [wLowHealthTonePairs]
	bit 7, a
	jr z, .resolved
	ld b, SFX_LEVEL_UP
.resolved
	; Consumed before the call, so a request PlaySound still drops (hold ceiling reached
	; mid-fade) does not replay every frame until something else clears it.
	xor a
	ld [wSlinkSfxRequest], a
	ld a, b
	jp PlaySound

.hold
	; ponytail: bounded hold -- after SLINK_SFX_HOLD_MAX frames play regardless and let the
	; engine's priority rule decide, rather than carrying a request forever.
	ld hl, wSlinkSfxHold
	ld a, [hl]
	and a
	jr nz, .holding
	inc [hl]                    ; a hold begins: stamp the frame
	ld a, [wSlinkFrameCounter]
	ld [wSlinkSfxHoldAt], a
	ret
.holding
	ld a, [wSlinkFrameCounter]
	ld hl, wSlinkSfxHoldAt
	sub [hl]                    ; frames held, modulo 256
	cp SLINK_SFX_HOLD_MAX
	jr nc, .play
	ret

.drop
	xor a
	ld [wSlinkSfxRequest], a
	ld [wSlinkSfxHold], a
	ret

;                   1 success       2 failure    3 boo      4 notify
.bankAudio1: db SFX_GET_ITEM_2, SFX_DENIED,  SFX_TINK,  SFX_START_MENU
.bankAudio2: db SFX_LEVEL_UP,   SFX_TINK,    SFX_TINK,  SFX_START_MENU ; no buzzer in the battle bank
.bankAudio3: db SFX_GET_ITEM_2, SFX_DENIED,  SFX_TINK,  SFX_START_MENU


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
