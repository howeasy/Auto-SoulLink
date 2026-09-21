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
;   +7     SFX request: Lua writes a SEMANTIC code (1 success, 2 failure, 3 boo); the
;          main thread plays the matching sound for the current audio bank and zeroes it
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
;   +12    SFX hold flag, ROM-private (see SlinkSfxService)
;   +13    SFX hold start: the frame counter's low byte when the hold began

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

; ── HOW SOUND IS PLAYED (and why not from here) ─────────────────────────────────────────
; Gen 1 has NO RAM-writable sound trigger: PlaySound ($23B1) takes the id in `a`, and
; `wNewSoundID` is only its own scratch (home/audio.asm:140-200). So the id has to reach a
; `call`, and the ABI-2 build made that call from THIS hook — the VBlank handler. Two
; failures were measured in the shipped ROM and are the reason the call is not here:
;
;   * SWALLOWED DURING FADES. PlaySound's `.next` arm returns without playing whenever
;     `wAudioFadeOutControl` is nonzero and `wNewSoundID` is zero — i.e. during every map
;     change and battle start/end fade, exactly when capture, faint and whiteout fire.
;   * RE-ENTRANCY. PlaySound is a main-thread routine. A VBlank landing inside it re-enters
;     the non-reentrant audio engine and corrupts wChannelSoundIDs; our hook IS that VBlank.
;
; The dispatch therefore lives on the MAIN THREAD, at two sites that both call
; SlinkSfxService below and are idempotent (the first to run consumes the request):
;   * the trade work's DelayFrame bridge (trade_service.asm, ROM0 $0001), after every
;     VBlank wait — the overworld, battles, animations, text;
;   * a stub on Joypad (SlinkJoypadStub, ROM0 $3FBE), because a menu waiting for input
;     never reaches DelayFrame: HandleMenuInput_ (home/window.asm .loop2) spins on
;     JoypadLowSensitivity and hFrameCounter, and the START menu, the PC, the bag and the
;     battle menu all sit in that loop. MEASURED: a request written with the START menu
;     open was still pending 300 frames later on the bridge alone.
; SlinkSfxService owns the queue-drain
; timing PlaySound lacks: it HOLDS the request while a fade is running (PlaySound would drop
; it), holds while the SFX channels are busy (engine_1.asm .sfxChannelLoop drops a higher id
; on a busy channel; the same CHAN5/6/8 test home/delay.asm WaitForSoundToFinish uses,
; with the same low-health-alarm bypass), and after SLINK_SFX_HOLD_MAX frames plays anyway
; and lets the engine's priority rule decide.
;
; The request byte carries a SEMANTIC CODE, not a sound id. Sound ids are indices into each
; audio bank's own header table (constants/music_constants.asm), so the same number names a
; different sound in bank $02, $08 and $1F — and a request held across a battle fade spans a
; bank change. SlinkSfxService resolves the code against wAudioROMBank at the moment it
; plays, with the row PlaySound itself would pick (anything not $02/$08 is Audio3).
;
; This hook only STOPS clearing the byte (the ABI-3 panel-only build drained it every frame
; so a client could never leave stale state; now the main thread clears it when it plays).
; Init zero-fills WRAM0 at power-on and soft reset (home/init.asm:30-40), so a fresh
; cartridge never sees a stray request.

; Mailbox +12: how many frames the current request has been held. ROM-private; a client
; never writes it. Reserved in the layout so a later byte cannot collide with it.
DEF SLINK_SFX_HOLD     EQU SLINK_MAILBOX + 12   ; nonzero while a hold is in progress
DEF SLINK_SFX_HOLD_AT  EQU SLINK_MAILBOX + 13   ; frame counter low byte when it began
; Measured in FRAMES against the mailbox's own VBlank counter (+5), not in service calls:
; the overworld runs both dispatch sites every frame and a menu runs one, so a call count
; would mean different things in different places. GET_ITEM_2, the longest sound used,
; owns CHAN5 for ~180 frames; a second request behind it must outlast that.
DEF SLINK_SFX_HOLD_MAX EQU 240          ; ~4 s: then play anyway, the engine decides
DEF SLINK_SFX_CODES    EQU 3            ; 1 success, 2 failure, 3 boo; others are dropped

; Audio engine facts, from data/pret/pokered.sym (Red and Blue identical).
DEF PlaySound            EQU $23B1     ; home/audio.asm:140; saves/restores the ROM bank itself
DEF wAudioFadeOutControl EQU $CFC7     ; nonzero while a music fade runs (home/fade_audio.asm)
DEF wChannelSoundIDs     EQU $C026     ; 8 bytes; CHAN5..CHAN8 are the SFX channels
DEF CHAN5                EQU 4
DEF wLowHealthAlarm      EQU $D083     ; bit 7 set = alarm owns CHAN5 (audio/low_health_alarm.asm)
DEF wAudioROMBank        EQU $C0EF     ; $02 / $08 / $1F: which header table the ids index

; Sound ids = (header address - SFX_Headers_N) / 3, from the .sym. The first three are the
; same number in ALL THREE banks; DENIED exists in $02/$1F only (in $08 that index is a
; battle sound), LEVEL_UP in $08 only — and equals CRY_SFX_END, so it still plays while
; the low-health alarm marks CHAN5 (the alarm writes CRY_SFX_END there).
DEF SFX_GET_ITEM_2 EQU $89
DEF SFX_TINK       EQU $8C
DEF SFX_DENIED     EQU $A5
DEF SFX_LEVEL_UP   EQU $86

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
	; Panel and SFX. A client reads this byte rather than inferring features from the ABI
	; number, which is why adding SFX back (ABI 3 shipped panel-only) needs no ABI bump.
	ld a, SLINK_CAP_PANEL | SLINK_CAP_SFX
	ld [SLINK_CAPS], a

	; 16-bit little-endian frame counter at +5. `inc [hl]` sets Z on wrap, so carry into
	; the high byte only when the low byte rolled over to zero.
	ld hl, SLINK_MAILBOX + 5
	inc [hl]
	jr nz, .noCarry
	inc hl
	inc [hl]
.noCarry

	; The SFX request is NOT touched here: it is the main thread's (SlinkSfxService) to
	; consume, and clearing it from VBlank would eat it before that thread ever looked.

	; Run the code the hook displaced, then hand control back to VBlank.
	ld b, TrackPlayTimeBank
	ld hl, TrackPlayTime
	call Bankswitch
	ret


; ── Main-thread SFX dispatch ─────────────────────────────────────────────────────────────
; Called by SlinkForeground (trade_service.asm) from the DelayFrame bridge, i.e. on the main
; thread right after a VBlank wait, in every context. Clobbers a, bc, hl (the bridge saved
; them). PlaySound preserves the rest and restores the ROM bank itself.
SlinkSfxService::
	ld a, [SLINK_SFX_REQUEST]
	and a
	ret z
	cp SLINK_SFX_CODES + 1
	jr nc, .drop                ; unknown code: consumed, never played

	; Hold while a music fade runs: PlaySound would return without playing.
	ld a, [wAudioFadeOutControl]
	and a
	jr nz, .hold

		; Hold while an SFX still owns CHAN5/6/8 — the engine drops a higher id on a busy
	; channel — unless the low-health alarm has CHAN5 for the rest of the battle, in
	; which case waiting would be forever (home/delay.asm WaitForSoundToFinish); .play
	; then substitutes the one id that channel accepts.
	ld a, [wLowHealthAlarm]
	and $80
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
	ld [SLINK_SFX_HOLD], a      ; whatever was held ends here
	; Resolve the code for the audio bank loaded NOW, with PlaySound's own bank choice.
	ld hl, .bank02
	ld a, [wAudioROMBank]
	cp $02
	jr z, .row
	ld hl, .bank08
	cp $08
	jr z, .row
	ld hl, .bank1F
.row
	ld a, [SLINK_SFX_REQUEST]
	dec a                       ; codes are 1-based
	ld c, a
	ld b, 0
	add hl, bc
	ld b, [hl]
	; While the low-health alarm owns CHAN5 it re-marks it with CRY_SFX_END ($86) and the
	; engine rejects any higher id there (.sfxChannelLoop: play only if new <= current), so
	; TINK and DENIED would be consumed into silence for the rest of the battle. The one id
	; the marked channel accepts is $86 itself -- LEVEL_UP in the battle bank, which is how
	; the vanilla level-up jingle plays through the alarm. Every code plays that then.
	; Only meaningful in bank $08: the alarm is ticked from the Audio2 branch alone and
	; battle end zeroes the flag (engine/battle/end_of_battle.asm .resetVariables).
	ld a, [wAudioROMBank]
	cp $08
	jr nz, .resolved
	ld a, [wLowHealthAlarm]
	and $80
	jr z, .resolved
	ld b, SFX_LEVEL_UP
.resolved
	; Consumed before the call, so a request that PlaySound still drops (hold ceiling
	; reached mid-fade) does not replay every frame until something else clears it.
	xor a
	ld [SLINK_SFX_REQUEST], a
	ld a, b
	jp PlaySound

.hold
	; ponytail: bounded hold — after SLINK_SFX_HOLD_MAX frames play regardless and let the
	; engine's priority rule decide, rather than carrying a request forever.
	ld hl, SLINK_SFX_HOLD
	ld a, [hl]
	and a
	jr nz, .holding
	inc [hl]                    ; a hold begins: stamp the frame
	ld a, [SLINK_MAILBOX + 5]
	ld [SLINK_SFX_HOLD_AT], a
	ret
.holding
	ld a, [SLINK_MAILBOX + 5]
	ld hl, SLINK_SFX_HOLD_AT
	sub [hl]                    ; frames held, modulo 256
	cp SLINK_SFX_HOLD_MAX
	jr nc, .play
	ret

.drop
	xor a
	ld [SLINK_SFX_REQUEST], a
	ld [SLINK_SFX_HOLD], a
	ret

;               1 success       2 failure    3 boo
.bank02: db SFX_GET_ITEM_2, SFX_DENIED,  SFX_TINK
.bank08: db SFX_LEVEL_UP,   SFX_TINK,    SFX_TINK     ; no buzzer in the battle bank
.bank1F: db SFX_GET_ITEM_2, SFX_DENIED,  SFX_TINK
SlinkSfxServiceEnd::
; The panel section is pinned at $4100; this one must stay below it.
ASSERT SlinkSfxServiceEnd <= $4100


; ── The Joypad site ──────────────────────────────────────────────────────────────────────
; Joypad (home, $019A) is `homecall _Joypad`: bank 3 is mapped, `call _Joypad` ($01A4), then
; the caller's bank comes back off the stack. The manifest redirects that one `call` here,
; where _Joypad runs first and the SFX request is serviced after it, on the main thread, in
; the menu loops the DelayFrame bridge never sees. Joypad's own `pop af` restores a and the
; flags; _Joypad clobbers b/d/e itself, so callers rely on none of them, but bc/de/hl are
; saved around our call anyway. Bankswitch restores bank 3 for the epilogue.
; $3FBE..$3FD4: the free tail of ROM0 past the START-menu trampoline (manifest.py), zeros
; in both pinned dumps; 66 bytes free, 23 used.
DEF _Joypad EQU $4000               ; data/pret/pokered.sym 03:4000, mapped by Joypad's prologue

SECTION "SLink Joypad stub", ROM0[$3FBE]
SlinkJoypadStub::
	call _Joypad
	ld a, [SLINK_SFX_REQUEST]
	and a
	ret z
	push bc
	push de
	push hl
	ld b, $3F
	ld hl, SlinkSfxService
	call Bankswitch
	pop hl
	pop de
	pop bc
	ret
SlinkJoypadStubEnd::
ASSERT SlinkJoypadStubEnd <= $4000


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
