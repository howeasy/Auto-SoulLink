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
DEF SLINK_ABI_VERSION  EQU 2

; Mailbox layout (30 bytes available, $DEE2-$DEFF):
;   +0..3  'SLNK' beacon, rewritten every frame
;   +4     ABI version
;   +5..6  16-bit frame counter
;   +7     SFX request: Lua writes a sound id, we play it and zero the byte
DEF SLINK_SFX_REQUEST  EQU SLINK_MAILBOX + 7

; Displaced call, from data/pret_rom_syms.json.
DEF TrackPlayTime      EQU $4DEE
DEF TrackPlayTimeBank  EQU $06
DEF Bankswitch         EQU $35D6

; WHY THE SFX HOOK LIVES HERE. Gen 1 has NO RAM-writable sound trigger. `wNewSoundID`
; ($C0EE) looks like one and is not: PlaySound takes the id in register `a` and only uses
; that address as internal scratch (home/audio.asm:140-165), and nothing in the main loop
; polls it. So a Lua-only SFX is impossible on Gen 1 — the id has to reach a `call`.
;
; VBlank is the ideal place for that call and costs us nothing extra, because by the time it
; reaches our hook it has ALREADY switched to wAudioROMBank and run Audio1_UpdateMusic
; (home/vblank.asm:53-71). We are in audio-bank context, immediately after the engine's own
; per-frame audio work and before VBlank restores wVBlankSavedROMBank.
DEF PlaySound          EQU $23B1   ; home bank, so directly callable
DEF hSavedROMBank      EQU $FFB9   ; measured from the ROM, not from hram.asm ordering

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

	; 16-bit little-endian frame counter at +5. `inc [hl]` sets Z on wrap, so carry into
	; the high byte only when the low byte rolled over to zero.
	ld hl, SLINK_MAILBOX + 5
	inc [hl]
	jr nz, .noCarry
	inc hl
	inc [hl]
.noCarry

	; ── SFX request ───────────────────────────────────────────────────────────────────
	; Lua writes a sound id here; we consume it and play it. One-shot: the byte is cleared
	; BEFORE the call, so a request can never be played twice even if PlaySound re-enters.
	ld hl, SLINK_SFX_REQUEST
	ld a, [hl]
	and a
	jr z, .noSfx
	ld [hl], 0
	ld b, a                     ; stash the id — PlaySound clobbers a

	; PlaySound parks the caller's bank in hSavedROMBank. The main thread may itself be
	; mid-PlaySound at the moment this interrupt fired, so save and restore that byte or we
	; would corrupt its bank restore. PlaySound preserves hl/de/bc, so b survives the call.
	ldh a, [hSavedROMBank]
	push af
	ld a, b
	call PlaySound
	pop af
	ldh [hSavedROMBank], a
.noSfx

	; Run the code the hook displaced, then hand control back to VBlank.
	ld b, TrackPlayTimeBank
	ld hl, TrackPlayTime
	call Bankswitch
	ret
