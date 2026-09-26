; P4.3a bounded lease-frame primitives. Framing matches lua/gb_trade_lease.lua.
; No publication, native UI, payload staging, or party mutation occurs here.
INCLUDE "engine/slink/slink_abi.inc"

DEF SLINK_TRADE_OFS_MAGIC EQU 0
DEF SLINK_TRADE_OFS_VERSION EQU 4
DEF SLINK_TRADE_OFS_COMMAND EQU 5
DEF SLINK_TRADE_OFS_GENERATION EQU 6
DEF SLINK_TRADE_OFS_ACK EQU 7
DEF SLINK_TRADE_OFS_RESULT EQU 8
DEF SLINK_TRADE_OFS_SLOT EQU 9
DEF SLINK_TRADE_OFS_AVAILABLE EQU 10
DEF SLINK_TRADE_OFS_MASK EQU 11
DEF SLINK_TRADE_OFS_TOKEN EQU 12
DEF SLINK_TRADE_FRAME EQU wSlinkMailbox + SLINK_OFS_TRADE_LEASE
ASSERT SLINK_TRADE_OFS_TOKEN + 4 == SLINK_TRADE_LEASE_SIZE

SECTION "SLink Trade Frame", ROMX, BANK[SLINK_SERVICE_BANK]

; Carry on refusal; BC/DE/HL preserved. Command/generation are caller policy.
SlinkTradeCheckHeader::
	ld a, [SLINK_TRADE_FRAME + 0]
	cp SLINK_TRADE_MAGIC_0
	jr nz, .refuse
	ld a, [SLINK_TRADE_FRAME + 1]
	cp SLINK_TRADE_MAGIC_1
	jr nz, .refuse
	ld a, [SLINK_TRADE_FRAME + 2]
	cp SLINK_TRADE_MAGIC_2
	jr nz, .refuse
	ld a, [SLINK_TRADE_FRAME + 3]
	cp SLINK_TRADE_MAGIC_3
	jr nz, .refuse
	ld a, [SLINK_TRADE_FRAME + SLINK_TRADE_OFS_VERSION]
	cp SLINK_TRADE_VERSION
	jr nz, .refuse
	and a
	ret
.refuse
	scf
	ret

; HL points to this visit's private four-byte token. Carry on zero or mismatch.
; All BC/DE/HL preserved, including HL's original pointer on early refusal.
SlinkTradeCheckToken::
	push bc
	push de
	push hl
	ld de, SLINK_TRADE_FRAME + SLINK_TRADE_OFS_TOKEN
	ld b, 0
	ld c, 4
.byte
	ld a, [de]
	cp [hl]
	jr nz, .refuse
	or b
	ld b, a
	inc de
	inc hl
	dec c
	jr nz, .byte
	ld a, b
	and a
	jr z, .refuse
	pop hl
	pop de
	pop bc
	ret
.refuse
	scf
	pop hl
	pop de
	pop bc
	ret

; End publication without erasing generation/ack/result/slot/token evidence.
SlinkTradeClose::
	xor a
	ld [SLINK_TRADE_FRAME + SLINK_TRADE_OFS_COMMAND], a
	ld [SLINK_TRADE_FRAME + SLINK_TRADE_OFS_AVAILABLE], a
	ld [SLINK_TRADE_FRAME + SLINK_TRADE_OFS_MASK], a
	ret
