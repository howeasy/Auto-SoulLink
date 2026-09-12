; R/B ABI-3 panel, heartbeat, lease and BG-transfer accounting. No VBlank audio.
; Native trade is advertised only by the combined companion build.
;
; WHY THIS HOOK SITE
;   VBlank (home, 00:2024) contains `farcall TrackPlayTime`, which the macro assembles as
;       ld b, BANK(TrackPlayTime)   ; 06 06
;       ld hl, TrackPlayTime        ; 21 EE 4D
;       call Bankswitch             ; CD D6 35
;   That exact 8-byte pattern occurs EXACTLY ONCE in the Red dump, at ROM 0x2094 (verified
;   by searching the cartridge). So the hook costs 3 rewritten immediate bytes and ZERO
;   home-bank space — which matters, because Red/Blue have only 156 free bytes in ROM0.
;
;   VBlank is also an interrupt that fires in every context, so the counter advancing
;   proves the hook runs in battles and menus too, not just the overworld.
;
; WHY IT IS SAFE TO CALL BACK OUT
;   Bankswitch (home/bankswitch.asm) saves the current bank on the STACK, switches, pushes
;   its own return address and `jp hl`. It is therefore re-entrant: this code, already
;   running in bank $3F via Bankswitch, can farcall TrackPlayTime and the nested call
;   restores $3F before returning here.
;
; WHERE IT LIVES
;   Bank $3F — one of nineteen entirely unused 16 KB banks in Red/Blue ($2D-$3F, ~311 KB of
;   solid padding). No bank-switching constraint on the hook, because the site is already a
;   farcall.
;
; MAILBOX
;   $DEE2 is the START of the only free WRAM in Red/Blue: pret's linker map reports
;   `WRAM0: TOTAL EMPTY: $001E` — thirty bytes, between wBoxDataEnd and the stack at $DF00.
;   Yellow has ZERO free WRAM, which is why the patch targets Red/Blue only.


DEF SLINK_MAILBOX      EQU $DEE2
DEF SLINK_ABI_VERSION  EQU 3

; Mailbox $DEE2-$DEFF: magic0-3, ABI4, capabilities5, heartbeat6-7,
; SFX head/tail8-9, FIFO10-13, overflow14, panel15-21, canary22-29.
; SFX is disabled and these reserved queue fields never dispatch audio.
DEF SLINK_HEARTBEAT    EQU SLINK_MAILBOX + 6
DEF SLINK_SFX_HEAD     EQU SLINK_MAILBOX + 8
DEF SLINK_SFX_TAIL     EQU SLINK_MAILBOX + 9
DEF SLINK_SFX_FIFO     EQU SLINK_MAILBOX + 10
DEF SLINK_SFX_OVERFLOW EQU SLINK_MAILBOX + 14
DEF SLINK_CAPS         EQU SLINK_MAILBOX + 5
DEF SLINK_PANEL_STATE  EQU SLINK_MAILBOX + 15
DEF SLINK_PANEL_PAGE   EQU SLINK_MAILBOX + 16
DEF SLINK_PANEL_PAGES  EQU SLINK_MAILBOX + 17
DEF SLINK_PANEL_GEN    EQU SLINK_MAILBOX + 18
DEF SLINK_PANEL_ACK    EQU SLINK_MAILBOX + 19
DEF SLINK_PANEL_TRANSFERS EQU SLINK_MAILBOX + 20
DEF SLINK_PANEL_LEASE  EQU SLINK_MAILBOX + 21
DEF SLINK_CANARY       EQU SLINK_MAILBOX + 22
DEF SLINK_CANARY_VALUE EQU $A5

DEF SLINK_CAP_SFX      EQU 1 << 0
DEF SLINK_CAP_PANEL    EQU 1 << 1
DEF SLINK_CAP_PC_TRADE EQU 1 << 2

; Panel handshake. The client may paint only in AWAIT, and must stop at CLOSED.
DEF SLINK_PANEL_CLOSED EQU 0
DEF SLINK_PANEL_AWAIT  EQU 1
DEF SLINK_PANEL_STAGED EQU 2
DEF SLINK_PANEL_DISPLAY EQU 3

; Displaced call, from data/pret_rom_syms.json.
DEF TrackPlayTime      EQU $4DEE
DEF TrackPlayTimeBank  EQU $06
DEF Bankswitch         EQU $35D6

; ── WHY THIS PATCH NO LONGER PLAYS SOUND ─────────────────────────────────────────────────
; Gen 1 has NO RAM-writable sound trigger. `wNewSoundID` ($C0EE) looks like one and is not:
; PlaySound takes the id in register `a` and uses that address only as internal scratch
; (home/audio.asm:140-165), and nothing in the main loop polls it. So the id has to reach a
; `call`, and VBlank was the obvious place — by the time VBlank reaches our hook it has
; already switched to wAudioROMBank and run Audio1_UpdateMusic (home/vblank.asm:53-71).
;
; Obvious, and wrong, for two reasons measured in the shipped ROM:
;
;   * SWALLOWED DURING FADES. PlaySound ($23B1) opens
;         ld a,[wAudioFadeOutControl] / and a / jr z,.noFadeOut
;         ld a,[wNewSoundID]          / and a / jr z,.done
;     We pass the id in `a` and never set wNewSoundID, which is 0 in steady state — so
;     during any fade the call returns without playing, and the request byte has already
;     been cleared, so the event is simply lost. Fades run ~56-70 frames on map change and
;     on battle start/end: precisely when capture, faint and whiteout fire.
;
;   * RE-ENTRANCY, in the ORDINARY case. `.noFadeOut` does `xor a / ld [wNewSoundID], a`
;     and only calls the audio engine several instructions later. A VBlank landing anywhere
;     in that window sees BOTH guard bytes clear, passes the guard, and re-enters a
;     non-reentrant audio routine — corrupting wChannelSoundIDs and stamping our SFX id
;     into wLastMusicSoundID. Our hook IS the VBlank handler, so we are the interrupt that
;     lands there. No guard we can write on our side closes this: the window is inside
;     PlaySound itself.
;
; Playing sound safely needs a main-thread dispatch point with its own displaced bytes and
; queue-drain timing. Until one exists and passes a full state matrix, this build ships
; PANEL ONLY and says so in the capability byte, rather than shipping audio that is silently
; dropped a fifth of the time and corrupts the music the rest.
;
; No legacy one-byte SFX request register is exposed by this ABI.
; The reserved queue remains inactive until a main-thread implementation is qualified.

SECTION "SLink Hook", ROMX[$4000], BANK[$3F]

SlinkHook::
	ld hl, SLINK_MAILBOX
	ld a, [hli]
	cp 'S'
	jr nz, .initialize
	ld a, [hli]
	cp 'L'
	jr nz, .initialize
	ld a, [hli]
	cp 'N'
	jr nz, .initialize
	ld a, [hli]
	cp 'K'
	jr nz, .initialize
	ld a, [hl]
	cp SLINK_ABI_VERSION
	jr z, .beacon
.initialize
	ld hl, SLINK_CAPS
	ld b, 25
	xor a
.clear
	ld [hli], a
	dec b
	jr nz, .clear
	ld hl, SLINK_CANARY
	ld b, 8
	ld a, SLINK_CANARY_VALUE
.canary
	ld [hli], a
	dec b
	jr nz, .canary
.beacon
	; Beacon, rewritten every frame. Cheap, and it self-heals if anything scribbles on it
	; — which is exactly what a presence check wants to be.
	ld a, 'S'
	ld [SLINK_MAILBOX + 0], a
	ld a, 'L'
	ld [SLINK_MAILBOX + 1], a
	ld a, 'N'
	ld [SLINK_MAILBOX + 2], a
	ld a, 'K'
	ld [SLINK_MAILBOX + 3], a
	ld a, SLINK_ABI_VERSION
	ld [SLINK_MAILBOX + 4], a
	; Panel only. See the SFX note at the top of this file: the VBlank PlaySound path is
	; not safe, so the capability it would advertise is not claimed. A client reads this
	; byte rather than inferring features from the ABI number, which is why dropping a
	; feature does not need an ABI bump.
	IF DEF(SLINK_NATIVE_TRADE)
		ld a, SLINK_CAP_PANEL | SLINK_CAP_PC_TRADE
	ELSE
		ld a, SLINK_CAP_PANEL
	ENDC
	ld [SLINK_CAPS], a

	; 16-bit little-endian frame counter at +5. `inc [hl]` sets Z on wrap, so carry into
	; the high byte only when the low byte rolled over to zero.
	ld hl, SLINK_HEARTBEAT
	inc [hl]
	jr nz, .noCarry
	inc hl
	inc [hl]
.noCarry

	; Age the panel lease and account for actual BG transfers only.
	ld a, [SLINK_PANEL_STATE]
	and a
	jr z, .displaced
	ld hl, SLINK_PANEL_LEASE
	ld a, [hl]
	and a
	jr z, .transfer
	dec [hl]
.transfer
	ld a, [SLINK_PANEL_STATE]
	cp SLINK_PANEL_STAGED
	jr nz, .displaced
	ld a, [SLINK_PANEL_GEN]
	and 1
	jr nz, .unstable
	ldh a, [hAutoBGTransferEnabled]
	and a
	jr z, .displaced
	; AutoBgMapTransfer already stored its NEXT portion: 0 means bottom was
	; copied, 1 means top, 2 means middle. Require all three distinct portions.
	ldh a, [hAutoBGTransferPortion]
	ld b, 4
	and a
	jr z, .markTransfer
	ld b, 1
	dec a
	jr z, .markTransfer
	ld b, 2
.markTransfer
	ld a, [SLINK_PANEL_TRANSFERS]
	or b
	ld [SLINK_PANEL_TRANSFERS], a
	jr .displaced
.unstable
	xor a
	ld [SLINK_PANEL_TRANSFERS], a
.displaced

	; Run the code the hook displaced, then hand control back to VBlank.
	ld b, TrackPlayTimeBank
	ld hl, TrackPlayTime
	call Bankswitch
	ret
SlinkHookEnd::
ASSERT SlinkHookEnd <= $4100


; ── The SLINK panel ──────────────────────────────────────────────────────────────────────
; Opened from the START menu row. The whole screen-ownership sequence below is
; StartMenu_TrainerInfo's (engine/menus/start_sub_menus.asm:453-475) with our draw
; substituted for DrawTrainerInfo -- deliberately, because that routine already solves
; every hazard this panel has:
;
;   * TEARING. GBPalWhiteOut before the draw and GBPalNormal after it means nothing
;     half-drawn is ever visible, without needing to reason about auto-BG transfer timing.
;   * TILE ANIMATIONS. hTileAnimations is pushed and restored, so the flower/water
;     animation the overworld was running comes back.
;   * SPRITES. ClearScreen + UpdateSprites on the way in, ReloadMapData on the way out.
;     The plan's warning that UpdateSprites does not hide sprites is real; what hides them
;     is that we are no longer on the map screen.
;   * PALETTES and TILES. LoadFontTilePatterns, LoadScreenTilesFromBuffer2,
;     RunDefaultPaletteCommand and LoadGBPal put back exactly what the menu had.
;
; Every routine it calls lives in the HOME bank, so there is no bank juggling inside the
; panel at all -- the only Bankswitch is the one that got us here.
;
; hTileAnimations was MEASURED from the ROM rather than derived from hram.asm's ordering:
; StartMenu_TrainerInfo assembles to `F0 D7 / F5 / AF / E0 D7`, so it is $FFD7.
DEF GBPalWhiteOut                EQU $3DE5
DEF ClearScreen                  EQU $190F
DEF UpdateSprites                EQU $2429
DEF GBPalNormal                  EQU $3DDC
DEF Joypad                       EQU $019A
DEF hJoyPressed                  EQU $FFB3
DEF LoadFontTilePatterns         EQU $3680
DEF LoadScreenTilesFromBuffer2   EQU $3701
DEF RunDefaultPaletteCommand     EQU $3DED
DEF ReloadMapData                EQU $3071
DEF LoadGBPal                    EQU $20BA
DEF PlaceString                  EQU $1955
DEF DelayFrame                   EQU $20AF
DEF Delay3                       EQU $3DD7
DEF hTileAnimations              EQU $FFD7
DEF hAutoBGTransferEnabled       EQU $FFBA
DEF hAutoBGTransferPortion       EQU $FFBB
DEF hAutoBGTransferDest          EQU $FFBC
DEF rBGP                        EQU $FF47
DEF rOBP0                       EQU $FF48
DEF rOBP1                       EQU $FF49
DEF wUpdateSpritesEnabled        EQU $CFCB
DEF wTileMap                     EQU $C3A0
DEF SCREEN_WIDTH                 EQU 20

; How long to wait for the client to paint a screen before giving up and showing the
; fallback. ~1.5s at 60fps: long enough for a client that is running, short enough that a
; player with no client attached is not left staring at a blank box.
DEF SLINK_STAGE_TIMEOUT EQU 180

SECTION "SLink Panel", ROMX[$4100], BANK[$3F]

SlinkPanel::
	call SlinkPanelCanary
	ret c
	ldh a, [rBGP]
	push af
	ldh a, [rOBP0]
	push af
	ldh a, [rOBP1]
	push af
	ldh a, [hAutoBGTransferEnabled]
	push af
	ldh a, [hAutoBGTransferPortion]
	push af
	ldh a, [hAutoBGTransferDest]
	push af
	ldh a, [hAutoBGTransferDest + 1]
	push af
	ld a, 1
	ldh [hAutoBGTransferEnabled], a
	call GBPalWhiteOut
	call ClearScreen
	call UpdateSprites
	ldh a, [hTileAnimations]
	push af
	xor a
	ldh [hTileAnimations], a

	; HIDE THE OVERWORLD SPRITES.
	; UpdateSprites does not do this -- home/update_sprites.asm only RETURNS when the flag
	; is not 1; it never clears OAM. So the player and every NPC stayed in the shadow OAM
	; and GBPalNormal's rOBP0 restore drew them straight over the panel text, on any
	; sprite-dense map. StartMenu_Pokemon (start_sub_menus.asm:16) shows the engine's own
	; answer: write 0. PrepareOAMData (engine/gfx/sprite_oam.asm:5-12) reads 0, calls
	; HideSprites once and latches $FF so it stops re-hiding. The Delay3 before the reveal
	; is enough for that VBlank to run.
	; Saved and restored rather than assumed to be 1, exactly as the item menu does
	; (start_sub_menus.asm:409-422) -- the panel can be opened from states where it is not.
	ld a, [wUpdateSpritesEnabled]
	push af
	xor a
	ld [wUpdateSpritesEnabled], a

	; Start at page 0, and clear the count so a stale one from a previous open cannot
	; make A page into nothing.
	xor a
	ld [SLINK_PANEL_PAGE], a
	ld [SLINK_PANEL_PAGES], a

.page
	; Start a fresh request while the palette remains blank.
	ld a, [SLINK_PANEL_ACK]
	ld [SLINK_PANEL_GEN], a
	xor a
	ld [SLINK_PANEL_TRANSFERS], a
	ld a, SLINK_STAGE_TIMEOUT
	ld [SLINK_PANEL_LEASE], a

	; Hand the screen to the client and wait for it to say it has finished painting. The
	; screen is already white at this point, so a client painting mid-wait cannot be seen
	; doing it -- which is what makes a torn page impossible rather than unlikely.
	ld a, SLINK_PANEL_AWAIT
	ld [SLINK_PANEL_STATE], a
	call SlinkWaitForStage
	jp c, .close
	push af
	; The stable generation has completed all three actual BG portions.
.reveal
	call GBPalNormal            ; reveal, once and whole
	pop af
	ld [SLINK_PANEL_ACK], a
	ld a, SLINK_PANEL_DISPLAY
	ld [SLINK_PANEL_STATE], a
	call SlinkWaitForButton     ; returns a = the buttons that were pressed
	jp c, .close

	; A advances, B and START close. This is the whole reason the panel does not use
	; WaitForTextScrollButtonPress: that returns on A or B without saying which.
	and SLINK_PAD_A
	jr z, .close

	; A advances and wraps after the last page. B/START close.
	ld a, [SLINK_PANEL_PAGE]
	inc a
	ld b, a
	ld a, [SLINK_PANEL_PAGES]
	cp b
	jr z, .wrap
	jr c, .wrap
	ld a, b
	jr .selectedPage
.wrap
	xor a
.selectedPage
	ld [SLINK_PANEL_PAGE], a
	call GBPalWhiteOut          ; hide the repaint, exactly as on the way in
	jr .page

.close
	xor a
	ld [SLINK_PANEL_STATE], a   ; closed: the client must stop painting
	ld [SLINK_PANEL_PAGE], a
	ld [SLINK_PANEL_LEASE], a

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
	pop af
	ldh [hAutoBGTransferDest + 1], a
	pop af
	ldh [hAutoBGTransferDest], a
	pop af
	ldh [hAutoBGTransferPortion], a
	pop af
	ldh [hAutoBGTransferEnabled], a
	pop af
	ldh [rOBP1], a
	pop af
	ldh [rOBP0], a
	pop af
	ldh [rBGP], a
	ret

; Wait for the player to dismiss the panel.
;
; NOT WaitForTextScrollButtonPress, which is the obvious choice and does not work here: it
; runs `predef CableClub_Run` and drives the down-arrow blink, and a panel built on it
; opened and then never returned. It also cannot tell A from B, which pagination will need.
; A local loop costs nine instructions and owns its own behaviour.
;
; hJoyPressed is EDGE-triggered, so the A press that opened the panel cannot immediately
; close it; the settle loop covers the case where a client stages instantly and the button
; is somehow still down. hJoyPressed's address was measured from CloseStartMenu's own bytes
; (`call Joypad` then `ldh a, [$FFB3]`), and the A/B/START bits from wMenuWatchedKeys
; reading 0xCB when the START menu is up.
DEF SLINK_PAD_A   EQU $01                   ; bit 0, from wMenuWatchedKeys' 0xCB
DEF SLINK_PAD_ANY EQU $01 | $02 | $08      ; A, B, START

SlinkWaitForButton:
	ld b, 20
.settle
	call SlinkPanelDisplayed
	ret c
	push bc
	call DelayFrame
	pop bc
	dec b
	jr nz, .settle
.wait
	call SlinkPanelDisplayed
	ret c
	call DelayFrame
	call Joypad
	ldh a, [hJoyPressed]
	and SLINK_PAD_ANY
	ret nz                      ; caller reads WHICH buttons out of a
	jr .wait

; Require a fresh stable even generation and all three actual BG portions.
; Carry means timeout, lease/canary failure, or a changed publication.
SlinkWaitForStage:
	ld b, SLINK_STAGE_TIMEOUT
.loop
	call SlinkPanelHealthy
	ret c
	ld a, [SLINK_PANEL_STATE]
	cp SLINK_PANEL_STAGED
	jr nz, .next
	ld a, [SLINK_PANEL_GEN]
	bit 0, a
	jr nz, .next
	ld c, a
	ld a, [SLINK_PANEL_ACK]
	cp c
	jr z, .next
	ld a, [SLINK_PANEL_PAGES]
	and a
	jr z, .next
.stable
	call SlinkPanelHealthy
	ret c
	ld a, [SLINK_PANEL_GEN]
	cp c
	jr nz, .failed
	ld a, [SLINK_PANEL_STATE]
	cp SLINK_PANEL_STAGED
	jr nz, .failed
	ld a, [SLINK_PANEL_TRANSFERS]
	cp 7
	jr nz, .nextStable
	ld a, [SLINK_PANEL_GEN]
	cp c
	jr nz, .failed
	and a
	ret
.nextStable
	push bc
	call DelayFrame
	pop bc
	dec b
	jr z, .failed
	jr .stable
.next
	push bc
	call DelayFrame
	pop bc
	dec b
	jp nz, .loop
.failed
	scf
	ret

SlinkPanelCanary:
	push bc
	push hl
	ld b, 8
	ld hl, SLINK_CANARY
.loop
	ld a, [hli]
	cp SLINK_CANARY_VALUE
	jr nz, .bad
	dec b
	jr nz, .loop
	pop hl
	pop bc
	and a
	ret
.bad
	pop hl
	pop bc
	scf
	ret

SlinkPanelHealthy:
	call SlinkPanelCanary
	ret c
	ld a, [SLINK_PANEL_LEASE]
	and a
	jr z, .bad
	ld a, [SLINK_CAPS]
	and SLINK_CAP_PANEL
	jr z, .bad
	ld a, [SLINK_PANEL_STATE]
	and a
	ret nz
.bad
	scf
	ret

SlinkPanelDisplayed:
	call SlinkPanelHealthy
	ret c
	ld a, [SLINK_PANEL_STATE]
	cp SLINK_PANEL_DISPLAY
	jr nz, .bad
	ld a, [SLINK_PANEL_ACK]
	ld hl, SLINK_PANEL_GEN
	cp [hl]
	jr nz, .bad
	and a
	ret
.bad
	scf
	ret

SlinkPanelEnd::
ASSERT SlinkPanelEnd <= $4500
