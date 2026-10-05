; SLink companion overlay -- Polished Crystal v3.2.3 native notification sounds (POL-SOUNDS).
;
; The port of patch/gen2/src/sfx.asm, reached ONLY through the DelayFrame bridge's main-thread
; service (patch/polished/src/slink.asm SlinkService tail-jumps here), exactly like vanilla's
; `jp SlinkSfxService`. No IRQ handler, no VBlank hook, no second entry: one foreground visit
; per frame the engine itself waits in DelayFrame.
;
; The semantic codes are the shared mailbox ABI's (patch/gb/slink_abi.inc), NOT native ids: the
; host posts SUCCESS/FAILURE/BOO/NOTIFY and this table resolves the code to the cartridge's own
; SFX id, so lua/gb_panel.lua never has to know a Polished sound number.
;
; Every native fact below is read out of the pinned Polished source, not from vanilla:
;   constants/sfx_constants.asm:4  SFX_ITEM       ; 01   SUCCESS
;   constants/sfx_constants.asm:11 SFX_READ_TEXT_2; 08   NOTIFY
;   constants/sfx_constants.asm:28 SFX_WRONG      ; 19   FAILURE
;   constants/sfx_constants.asm:39 SFX_BUMP       ; 24   BOO
;   home/audio.asm:240 PlaySFX::   (sound id in E; preserves every register, restores the bank)
;   home/audio.asm:443 CheckSFX::  (nz = an SFX channel is active; audio.asm:454 `bit` sets Z)
;   home/audio.asm:127 wMusicFade  (nonzero = a fade owns the channels)
; The four ASSERTs make a renamed constant or a moved routine a LINK failure, not a wrong cue.
; (Vanilla's overlay branches on CARRY after CheckSFX; Polished's CheckSFX ends in `bit`, which
; clears carry, so the busy-channel hold below must test Z -- see .hold.)
ASSERT SFX_ITEM == $01 && SFX_READ_TEXT_2 == $08 && SFX_WRONG == $19 && SFX_BUMP == $24
ASSERT BANK(PlaySFX) == 0 && BANK(CheckSFX) == 0 && BANK(DelayFrames) == 0 && BANK(_PlaySFX) != 0

; +12/+13 are ROM-private, exactly as in vanilla: normal hold = 1, elapsed BLOCKED SERVICE VISITS.
; This is a 240-visit ceiling, not a frame guarantee: hVBlankCounter freezes in several VBlank
; modes and rDIV is reset by native serial code, so neither is a sound deadline.
DEF SLINK_SFX_MAX_HOLD EQU 240
; Released by native _Init clearing WRAM0, which covers the mailbox (slink_mailbox.asm).
DEF SLINK_SFX_RESET_BLOCKED EQU $ff

; SoftReset (home/init.asm) calls InitSound, ClearPalettes and THEN `ld c, 3 / call DelayFrames`
; before _Init zeroes WRAM0. Those frames run the bridge, so a request left in the mailbox from
; before the reset would be played against a half-initialized audio engine. Same-size rewrite of
; that one `call DelayFrames` (3 bytes either way, C preserved), placed in the free ROM0 gap that
; follows SlinkDelayFrameBridgeEnd ($0089; "Header" starts at $0100).
SECTION "Slink Sound Reset", ROM0[$0089]
SlinkResetSoundBridge::
	push af
	ld a, SLINK_SFX_RESET_BLOCKED
	ld [wSlinkMailbox + SLINK_OFS_SFX_HOLD], a
	xor a
	ld [wSlinkMailbox + SLINK_OFS_SFX_REQUEST], a
	ld [wSlinkMailbox + SLINK_OFS_SFX_HOLD_AT], a
	pop af
	jp DelayFrames
SlinkResetSoundBridgeEnd::
ASSERT SlinkResetSoundBridgeEnd <= $0100
; _InitSound clears wChannels..wChannelsEnd (wChannelsEnd 00:ccc0), never the mailbox, so the latch
; above is what releases a hold; the sound RAM and the mailbox do not overlap.
ASSERT wSlinkMailbox + SLINK_MAILBOX_SIZE <= wChannels

SECTION "Slink Sound Service", ROMX, BANK[SLINK_SERVICE_BANK]
SlinkSfxService::
	; Check the latch BEFORE the empty/invalid-request path: a host post during Reset has to be
	; discarded too, not merely held.
	ld a, [wSlinkMailbox + SLINK_OFS_SFX_HOLD]
	cp SLINK_SFX_RESET_BLOCKED
	jr z, .reset_blocked
	ld a, [wSlinkMailbox + SLINK_OFS_SFX_REQUEST]
	and a
	jr z, .clear
	cp SLINK_SFX_NOTIFY + 1
	jr nc, .clear          ; not one of the four semantic codes: consumed unplayed
	ld b, a
	; A music fade owns the channels; PlaySFX would land inside the fade (audio.asm:127 wMusicFade).
	ld a, [wMusicFade]
	and a
	jr nz, .hold
	; nz = an SFX channel is still active. Waiting keeps a SLink cue from cutting a native one
	; off; PlaySFX's own priority check (audio.asm:250-256, wCurSFX) is the last word.
	call CheckSFX
	jr nz, .hold

.play
	; PlaySFX preserves every register and the bank but takes DE; preserve the caller's DE
	; locally. Never call the blocking WaitSFX (audio.asm:278) from here: it spins on DelayFrame,
	; which would re-enter this bridge.
	push de
	ld a, b
	dec a
	ld e, a
	ld d, 0
	ld hl, .sounds
	add hl, de
	ld e, [hl]
	; Acknowledge BEFORE the play: the byte is the whole handshake, and a sound that PlaySFX's
	; native priority then refuses must not strand the host's queue.
	xor a
	ld [wSlinkMailbox + SLINK_OFS_SFX_REQUEST], a
	ld [wSlinkMailbox + SLINK_OFS_SFX_HOLD], a
	ld [wSlinkMailbox + SLINK_OFS_SFX_HOLD_AT], a
	call PlaySFX
	pop de
	ret

.hold
	; First blocked visit arms the hold and zeroes its age; later ones only count.
	ld a, [wSlinkMailbox + SLINK_OFS_SFX_HOLD]
	cp 1
	jr z, .count
	ld a, 1
	ld [wSlinkMailbox + SLINK_OFS_SFX_HOLD], a
	xor a
	ld [wSlinkMailbox + SLINK_OFS_SFX_HOLD_AT], a
.count
	ld a, [wSlinkMailbox + SLINK_OFS_SFX_HOLD_AT]
	cp SLINK_SFX_MAX_HOLD - 1
	; Gen 1 ceiling semantics: consume once and let PlaySFX's native priority decide. A native
	; call is not proof that a cue was audible. Saturation: a corrupted age cannot wrap into a
	; fresh hold.
	jr nc, .play
	inc a
	ld [wSlinkMailbox + SLINK_OFS_SFX_HOLD_AT], a
	ret

.clear
	xor a
	ld [wSlinkMailbox + SLINK_OFS_SFX_HOLD], a
.reset_blocked
	xor a
	ld [wSlinkMailbox + SLINK_OFS_SFX_REQUEST], a
	ld [wSlinkMailbox + SLINK_OFS_SFX_HOLD_AT], a
	ret

.sounds
	db SFX_ITEM, SFX_WRONG, SFX_BUMP, SFX_READ_TEXT_2
SlinkSfxServiceEnd::