; SLink companion overlay -- Polished Crystal v3.2.3 core (P5a): beacon, ABI version,
; sampled frame counter. Port of patch/gen2/src/slink.asm; same ABI (patch/gb/slink_abi.inc),
; caps 0 (no SFX/panel/phone/trade yet).
INCLUDE "engine/slink/slink_abi.inc"

; Bank $7E: wholly unused in the clean 3.2.3 ROM (data/polished/free_space.txt) and not named
; in layout.link, so this fixed BANK[] section is placed there by rgblink and nothing else moves.
DEF SLINK_SERVICE_BANK EQU $7E
DEF SLINK_MAILBOX_SIZE EQU 40
ASSERT wSlinkMailbox == $c60b
ASSERT wSlinkMailboxEnd - wSlinkMailbox == SLINK_MAILBOX_SIZE
ASSERT hVBlankCounter == $ff8e
; The audio clear (_InitSound: wChannels..wChannelsEnd) cannot reach the mailbox.
ASSERT wSlinkMailbox + SLINK_MAILBOX_SIZE <= wChannels

; Private sampled-clock state, outside the 14-byte core and 16-byte trade lease.
; EQUS, not EQU: wSlinkMailbox lives in ram.o, so it is only known at link time.
DEF SLINK_LAST_SAMPLE EQUS "wSlinkMailbox + SLINK_PUBLIC_SIZE"
DEF SLINK_SAMPLE_VALID EQUS "wSlinkMailbox + SLINK_PUBLIC_SIZE + 1"
DEF SLINK_SAMPLE_COOKIE EQU $a5
ASSERT SLINK_PUBLIC_SIZE + 2 <= SLINK_MAILBOX_SIZE

; Save path: Polished assembles every object with -E (export all labels), so the native save
; entry the vanilla trade overlay EXPORTs by edit is already linkable; no source edit needed.
ASSERT BANK(Link_SaveGame) != 0 && BANK(NextOverworldFrame) != 0

; ROM0 $0070-$00FF is free: "High Home" (home/header.asm, layout.link org $005b) ends with
; _hl_ at $006f, and the next scripted section is "Header" at $0100.
SECTION "SLink DelayFrame Bridge", ROM0[$0070]
SlinkDelayFrameBridge::
	; DelayFrame's native 7-byte lead-in, moved here verbatim. It arms the native wait
	; BEFORE servicing: a VBlank during the service must satisfy this DelayFrame, not be
	; discarded by rearming the flag afterward. hDelayFrameLY keeps the entry LY.
	ldh a, [rLY]
	ldh [hDelayFrameLY], a
	xor a ; ld a, FALSE
	ldh [hVBlankOccurred], a
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
	xor a ; core build: no capabilities
	ld [wSlinkMailbox + SLINK_OFS_CAPS], a

	; Sample the engine's own clock (VBlank's hVBlankCounter). Unsigned deltas lose whole
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
	ret
SlinkServiceEnd::
