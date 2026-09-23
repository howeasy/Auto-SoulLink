; P4.2a, O-27 D5: one foreground service, reached only through DelayFrame.
; +12/+13 are ROM-private: normal hold=1 and elapsed BLOCKED SERVICE VISITS.
; This is a 240-visit bound, not a wall-clock/frame guarantee. hVBlankCounter
; freezes in several VBlank modes; rDIV is reset by native serial code. Neither
; is a sound deadline. A loop without DelayFrame still needs physical coverage.
DEF SLINK_SFX_MAX_HOLD EQU 240
DEF SLINK_SFX_RESET_BLOCKED EQU $ff
ASSERT SFX_ITEM == $01 && SFX_WRONG == $19 && SFX_BUMP == $24 && SFX_READ_TEXT_2 == $08
ASSERT BANK(CheckSFX) == 0 && BANK(PlaySFX) == 0 && BANK(InitSound) == 0
; InitSound clears wAudio..wAudioEnd, not the mailbox/reset latch.
ASSERT wAudioEnd <= wSlinkMailbox

SECTION "SLink Sound Reset", ROM0[$0080]
SlinkResetSoundBridge::
	; Same-size Reset call replacement, not another polling site. Latch before
	; InitSound makes the channels idle, and retain it through all 32 waits.
	push af
	ld a, SLINK_SFX_RESET_BLOCKED
	ld [wSlinkMailbox + SLINK_OFS_SFX_HOLD], a
	xor a
	ld [wSlinkMailbox + SLINK_OFS_SFX_REQUEST], a
	ld [wSlinkMailbox + SLINK_OFS_SFX_HOLD_AT], a
	pop af
	jp InitSound
SlinkResetSoundBridgeEnd::
ASSERT SlinkDelayFrameBridgeEnd <= SlinkResetSoundBridge
ASSERT SlinkResetSoundBridgeEnd <= $0100

SECTION "SLink Sound Service", ROMX, BANK[SLINK_SERVICE_BANK]
SlinkSfxService::
	; Check the latch BEFORE the empty/invalid-request path: a new host post
	; during Reset must be discarded too. Native Init clears WRAM to release it.
	ld a, [wSlinkMailbox + SLINK_OFS_SFX_HOLD]
	cp SLINK_SFX_RESET_BLOCKED
	jr z, .reset_blocked
	ld a, [wSlinkMailbox + SLINK_OFS_SFX_REQUEST]
	and a
	jr z, .clear
	cp SLINK_SFX_NOTIFY + 1
	jr nc, .clear
	ld b, a
	ld a, [wMusicFade]
	and a
	jr nz, .hold
	call CheckSFX ; carry = active native channel 5-8; AF only is clobbered
	jr c, .hold

.play
	; PlaySFX itself preserves all registers/bank but takes DE. Preserve the
	; bridge caller's DE locally; never call the blocking WaitSFX helper here.
	push de
	ld a, b
	dec a
	ld e, a
	ld d, 0
	ld hl, .sounds
	add hl, de
	ld e, [hl]
	xor a
	ld [wSlinkMailbox + SLINK_OFS_SFX_REQUEST], a
	ld [wSlinkMailbox + SLINK_OFS_SFX_HOLD], a
	ld [wSlinkMailbox + SLINK_OFS_SFX_HOLD_AT], a
	call PlaySFX
	pop de
	ret

.hold
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
	; Gen 1 ceiling semantics: consume once and let PlaySFX's native priority
	; decide. It can refuse; a native call is not proof that a cue was audible.
	jr nc, .play ; saturate: corrupted ages cannot wrap into a fresh hold
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
