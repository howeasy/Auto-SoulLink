; O-27 D1/D5/D6 main-thread service. Panel authority requires its complete overlay.
; Included by the source-overlay builder, after its title-specific WRAM reservation.
INCLUDE "engine/slink/slink_abi.inc"

; Both source trees: home/header.asm's joypad JP ends at $0062.
; Empty banks in the pinned maps: Crystal $75; Gold/Silver $13.
ASSERT !(DEF(_GOLD) && DEF(_SILVER))
ASSERT !DEF(_CRYSTAL11), "Crystal 1.1 is not a selected companion target"
IF DEF(_GOLD) || DEF(_SILVER)
DEF SLINK_SERVICE_BANK EQU $13
ASSERT wSlinkMailbox == $c1d9
ASSERT hVBlankCounter == $ff9d
DEF SLINK_MAILBOX_SIZE EQU 39
ELSE
DEF SLINK_SERVICE_BANK EQU $75
ASSERT wSlinkMailbox == $cfd8
ASSERT hVBlankCounter == $ff9b
DEF SLINK_MAILBOX_SIZE EQU 40
ENDC

; Private sampled-clock state, outside the 14-byte core and 16-byte trade lease.
DEF SLINK_LAST_SAMPLE EQU wSlinkMailbox + SLINK_PUBLIC_SIZE
DEF SLINK_SAMPLE_VALID EQU SLINK_LAST_SAMPLE + 1
DEF SLINK_SAMPLE_COOKIE EQU $a5
ASSERT SLINK_PUBLIC_SIZE + 2 <= SLINK_MAILBOX_SIZE
ASSERT wSlinkMailbox + SLINK_MAILBOX_SIZE <= $d000

SECTION "SLink DelayFrame Bridge", ROM0[$0063]
SlinkDelayFrameBridge::
	; Arm the native wait BEFORE servicing: a VBlank during the service must
	; satisfy this DelayFrame, not be discarded by rearming the flag afterward.
	ld a, 1
	ld [wVBlankOccurred], a
	push af
	push bc
	push hl
	ldh a, [hROMBank]
	push af
	ld a, BANK(SlinkService)
	rst Bankswitch
	call SlinkService
	pop af
	rst Bankswitch
	pop hl
	pop bc
	pop af
	ret
SlinkDelayFrameBridgeEnd::
ASSERT SlinkDelayFrameBridgeEnd <= $0100
; Eight local stack bytes (AF, BC, HL, bank); the service preserves DE.
; Nested calls/IRQs (including native audio) add more. Worst-case live minimum
; SP during battle/link remains unmeasured; MODEL is not stack qualification.

SECTION "SLink Service", ROMX[$4000], BANK[SLINK_SERVICE_BANK]
SlinkService::
	; Header repair never clears host requests, panel state, holds or lease bytes.
	ld hl, wSlinkMailbox
	ld a, SLINK_BEACON_0
	ld [hli], a
	ld a, SLINK_BEACON_1
	ld [hli], a
	ld a, SLINK_BEACON_2
	ld [hli], a
	ld a, SLINK_BEACON_3
	ld [hli], a
	ld a, SLINK_ABI_VERSION
	ld [hl], a
IF DEF(SLINK_SFX_ENABLED)
IF DEF(SLINK_PANEL_ENABLED)
	ld a, SLINK_CAP_PANEL | SLINK_CAP_SFX | SLINK_CAP_SFX_NOTIFY
ELSE
	ld a, SLINK_CAP_SFX | SLINK_CAP_SFX_NOTIFY
ENDC
ELSE
IF DEF(SLINK_PANEL_ENABLED)
	ld a, SLINK_CAP_PANEL
ELSE
	xor a
ENDC
ENDC
	ld [wSlinkMailbox + SLINK_OFS_CAPS], a

	; Sample the engine's own clock. Only selected VBlank handlers advance it;
	; this is not a count of every physical frame. Unsigned deltas lose whole
	; multiples of 256 if the service is not visited between source increments.
	ldh a, [hVBlankCounter]
	ld b, a
	ld a, [SLINK_SAMPLE_VALID]
	cp SLINK_SAMPLE_COOKIE
	jr z, .sample
	ld a, SLINK_SAMPLE_COOKIE
	ld [SLINK_SAMPLE_VALID], a
	xor a
	ld [wSlinkMailbox + SLINK_OFS_FRAME_COUNTER], a
	ld [wSlinkMailbox + SLINK_OFS_FRAME_COUNTER + 1], a
	jr .remember
.sample
	ld a, [SLINK_LAST_SAMPLE]
	ld c, a
	ld a, b
	sub c
	ld c, a
	ld a, [wSlinkMailbox + SLINK_OFS_FRAME_COUNTER]
	add c
	ld [wSlinkMailbox + SLINK_OFS_FRAME_COUNTER], a
	ld a, [wSlinkMailbox + SLINK_OFS_FRAME_COUNTER + 1]
	adc 0
	ld [wSlinkMailbox + SLINK_OFS_FRAME_COUNTER + 1], a
.remember
	ld a, b
	ld [SLINK_LAST_SAMPLE], a
IF DEF(SLINK_SFX_ENABLED)
	jp SlinkSfxService
ELSE
	ret
ENDC
SlinkServiceEnd::

; Native Init clears the whole WRAM0 mailbox on boot/reset (Crystal init.asm:66-75,
; G/S :59-68). Reset first runs 32 DelayFrames before that clear. NewGame's narrower
; ResetWRAM excludes the mailbox. Future request/lease services need their own
; new-run lifecycle. The optional sound service has its own reset-entry latch;
; trade requests are never consumed here.
