; SLink companion overlay -- Polished Crystal trade slice 1: bounded lease-frame primitives (port of
; patch/gen2/src/trade_frame.asm, behaviour byte-for-byte). Framing matches lua/gb_trade_lease.lua.
; No publication, native UI, payload staging, or party mutation occurs here. Callers: the responder
; dispatcher, the held proposer and responder services and the (disabled) commit.
; The shared ABI is already INCLUDEd by slink.asm.

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
; EQUS, not EQU: wSlinkMailbox lives in ram.o, so it is only known at link time (see slink.asm).
DEF SLINK_TRADE_FRAME EQUS "wSlinkMailbox + SLINK_OFS_TRADE_LEASE"
ASSERT SLINK_TRADE_OFS_TOKEN + 4 == SLINK_TRADE_LEASE_SIZE

; Fixed above the version field ($4000-$41FF is the core/panel/sound/version run): rgblink packs
; floating sections largest-first, so a floating section here would shove the version field (and every
; pinned symbol after it) up. The linker rejects an overlap, so growth of either side is loud.
ASSERT SLINK_SERVICE_BANK == $7E

SECTION "SLink Trade Frame", ROMX[$4200], BANK[SLINK_SERVICE_BANK]

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
SlinkTradeFrameEnd::
