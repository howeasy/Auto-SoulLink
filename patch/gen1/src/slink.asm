; slink.asm — SLink companion patch for Pokemon Red/Blue: the SPIKE.
;
; Proves the injection approach and NOTHING else: it writes a 'SLNK' beacon plus an ABI
; version and a per-frame counter into WRAM, then runs the code it displaced. If this is
; solid — beacon visible, counter advancing in the overworld AND in battle AND in menus,
; game otherwise indistinguishable over a long session — the approach is sound and features
; can follow. If it is not, the whole idea dies for ~1% of the cost of finding out later.
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

; Mailbox layout (30 bytes available, $DEE2-$DEFF):
;   +0..3  'SLNK' beacon, rewritten every frame
;   +4     ABI version
;   +5..6  16-bit frame counter
;   +7     SFX request: Lua writes a sound id, we play it and zero the byte
DEF SLINK_SFX_REQUEST  EQU SLINK_MAILBOX + 7
;   +8     capability bits, so a client asks WHAT this build can do rather than inferring
;          it from the ABI number -- which stops being true the moment one feature ships
;          without another
;   +9     panel state, the handshake between this code and the client
;   +10    page number, ours to the client: which page it should paint
;   +11    page COUNT, the client's to us: how many there are. We need it to know when A
;          should close instead of advancing, and only the client knows how much text the
;          server sent. 0 (never written) reads as one page.
DEF SLINK_CAPS         EQU SLINK_MAILBOX + 8
DEF SLINK_PANEL_STATE  EQU SLINK_MAILBOX + 9
DEF SLINK_PANEL_PAGE   EQU SLINK_MAILBOX + 10
DEF SLINK_PANEL_PAGES  EQU SLINK_MAILBOX + 11

DEF SLINK_CAP_SFX      EQU 1 << 0
DEF SLINK_CAP_PANEL    EQU 1 << 1

; Panel handshake. The client may paint only in AWAIT, and must stop at CLOSED.
DEF SLINK_PANEL_CLOSED EQU 0
DEF SLINK_PANEL_AWAIT  EQU 1
DEF SLINK_PANEL_STAGED EQU 2

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
; The request byte is still CONSUMED (cleared) so a client that writes one does not leave
; stale state in the mailbox; it simply never becomes a sound.

SECTION "SLink Hook", ROMX[$4000], BANK[$3F]

SlinkHook::
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
	ld a, SLINK_CAP_PANEL
	ld [SLINK_CAPS], a

	; 16-bit little-endian frame counter at +5. `inc [hl]` sets Z on wrap, so carry into
	; the high byte only when the low byte rolled over to zero.
	ld hl, SLINK_MAILBOX + 5
	inc [hl]
	jr nz, .noCarry
	inc hl
	inc [hl]
.noCarry

	; ── SFX request: drained, never played ────────────────────────────────────────────
	; Clearing it keeps the mailbox honest for a client that still writes one. There is
	; deliberately NO call here — see the note at the top of this file.
	xor a
	ld [SLINK_SFX_REQUEST], a

	; Run the code the hook displaced, then hand control back to VBlank.
	ld b, TrackPlayTimeBank
	ld hl, TrackPlayTime
	call Bankswitch
	ret


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
DEF wUpdateSpritesEnabled        EQU $CFCB
DEF wTileMap                     EQU $C3A0
DEF SCREEN_WIDTH                 EQU 20

; How long to wait for the client to paint a screen before giving up and showing the
; fallback. ~1.5s at 60fps: long enough for a client that is running, short enough that a
; player with no client attached is not left staring at a blank box.
DEF SLINK_STAGE_TIMEOUT EQU 90

SECTION "SLink Panel", ROMX[$4100], BANK[$3F]

SlinkPanel::
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
	; Draw the fallback FIRST, so a timeout shows something that explains itself rather
	; than an empty screen. A client that is attached simply paints over it -- panelStage
	; writes all eighteen rows, padded, so nothing of the previous page survives either.
	call SlinkDrawFallback

	; Hand the screen to the client and wait for it to say it has finished painting. The
	; screen is already white at this point, so a client painting mid-wait cannot be seen
	; doing it -- which is what makes a torn page impossible rather than unlikely.
	ld a, SLINK_PANEL_AWAIT
	ld [SLINK_PANEL_STATE], a
	call SlinkWaitForStage      ; returns a = the state we gave up on
	push af                     ; remember whether a client actually answered

	call Delay3                 ; let the auto-BG transfers carry wTileMap into VRAM
	call GBPalNormal            ; reveal, once and whole
	call SlinkWaitForButton     ; returns a = the buttons that were pressed
	ld c, a
	pop af

	; No client answered, so there are no pages to turn -- any button closes.
	cp SLINK_PANEL_STAGED
	jr nz, .close

	; A advances, B and START close. This is the whole reason the panel does not use
	; WaitForTextScrollButtonPress: that returns on A or B without saying which.
	ld a, c
	and SLINK_PAD_A
	jr z, .close

	; ...but only while there IS a next page. The client publishes the count, because only
	; it knows how much text the server sent; a count of 0 means it never said, which we
	; read as one page. Without this, A on a one-page panel would white out and repaint the
	; same rows -- a flicker that looks like a fault.
	ld a, [SLINK_PANEL_PAGE]
	inc a
	ld b, a
	ld a, [SLINK_PANEL_PAGES]
	cp b
	jr c, .close                ; pages < page+1  -> that was the last one
	jr z, .close                ; pages == page+1 -> ditto
	ld a, b
	ld [SLINK_PANEL_PAGE], a
	call GBPalWhiteOut          ; hide the repaint, exactly as on the way in
	jr .page

.close
	xor a
	ld [SLINK_PANEL_STATE], a   ; closed: the client must stop painting
	ld [SLINK_PANEL_PAGE], a

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
	call DelayFrame
	dec b
	jr nz, .settle
.wait
	call DelayFrame
	call Joypad
	ldh a, [hJoyPressed]
	and SLINK_PAD_ANY
	ret nz                      ; caller reads WHICH buttons out of a
	jr .wait

; Poll the mailbox for up to SLINK_STAGE_TIMEOUT frames. Returns either way: a player
; without a client still gets a panel, it just says so.
; bc is pushed around DelayFrame because nothing documents it as preserved, and a counter
; that silently stops counting would turn the timeout into a hang.
SlinkWaitForStage:
	ld b, SLINK_STAGE_TIMEOUT
.loop
	ld a, [SLINK_PANEL_STATE]
	cp SLINK_PANEL_STAGED
	ret z                       ; a = STAGED: a client answered
	push bc
	call DelayFrame
	pop bc
	dec b
	jr nz, .loop
	ld a, [SLINK_PANEL_STATE]   ; a = whatever it still is: nobody answered
	ret

SlinkDrawFallback:
	ld hl, wTileMap + SCREEN_WIDTH * 2 + 2
	ld de, .title
	call PlaceString
	ld hl, wTileMap + SCREEN_WIDTH * 5 + 2
	ld de, .noData
	call PlaceString
	ret
; ── Gen 1's text encoding, scoped to the strings that need it ────────────────────────────
; rgbasm does not know it, so without a charmap `db "SLINK@"` emits ASCII -- and '@' is $40
; in ASCII while the terminator PlaceString looks for is $50, so it walks off the end of the
; string and paints memory until it finds one. Measured: the first panel build assembled
; 53 4F 55 4C 20 4C 49 4E 4B 40 and hung the game.
;
; PUSHC/POPC rather than a file-wide charmap, because a charmap rewrites CHARACTER LITERALS
; too. A global one turned `ld a, 'S'` in the beacon above into $92 and the mailbox stopped
; reading as "SLNK" -- caught by the companion-patch gate, which is exactly what it is for.
;
; Letters are $80 + (c - 'A'), cross-checked against the ROM's own "POK<e>DEX@", which reads
; 8F 8E 8A BA 83 84 97 50.
	PUSHC
	NEWCHARMAP slinktext
	CHARMAP "@", $50
	CHARMAP " ", $7F
FOR I, 26
	CHARMAP STRSUB("ABCDEFGHIJKLMNOPQRSTUVWXYZ", I + 1, 1), $80 + I
ENDR
.title
	db "SOUL LINK@"
.noData
	db "NO CLIENT@"
	POPC
