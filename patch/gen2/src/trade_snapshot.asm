; P4.3a held-foreground preimage. OT slot 1 (the second slot) is borrowed only
; while battle/START/SAVE are excluded; incoming native trade data owns OT slot 0.
; Layout: pinned pret ram/wram.asm party_struct and OT/name arrays for C/G/S.
ASSERT PARTYMON_STRUCT_LENGTH == 48
ASSERT NAME_LENGTH == 11 && MON_NAME_LENGTH == 11
ASSERT PARTY_LENGTH == 6

SECTION "SLink Trade Snapshot", ROMX, BANK[SLINK_SERVICE_BANK]

; A = zero-based own slot. Carry refuses invalid live bounds/species-list state.
; BC/DE/HL preserved. Only the second OT record, OT name and nickname are written.
SlinkTradeSnapshot::
	push bc
	push de
	push hl
	call SlinkTradeSnapshotPartyPointer
	jr c, .done
	ld de, wOTPartyMon2
	ld c, PARTYMON_STRUCT_LENGTH
	call SlinkTradeSnapshotCopy
	ld hl, wPartyMonOTs
	ld de, NAME_LENGTH
	call SlinkTradeSnapshotOffset
	ld de, wOTPartyMonOTs + NAME_LENGTH
	ld c, NAME_LENGTH
	call SlinkTradeSnapshotCopy
	ld hl, wPartyMonNicknames
	ld de, MON_NAME_LENGTH
	call SlinkTradeSnapshotOffset
	ld de, wOTPartyMonNicknames + MON_NAME_LENGTH
	ld c, MON_NAME_LENGTH
	call SlinkTradeSnapshotCopy
	and a
.done
	pop hl
	pop de
	pop bc
	ret

; A = private own slot retained by the FSM; it also retains/checks original count.
; Carry refuses any of the 70 bytes changing, invalid live bounds, or list drift.
SlinkTradeValidateSnapshot::
	push bc
	push de
	push hl
	call SlinkTradeSnapshotPartyPointer
	jr c, .done
	ld de, wOTPartyMon2
	ld c, PARTYMON_STRUCT_LENGTH
	call SlinkTradeSnapshotCompare
	jr c, .done
	ld hl, wPartyMonOTs
	ld de, NAME_LENGTH
	call SlinkTradeSnapshotOffset
	ld de, wOTPartyMonOTs + NAME_LENGTH
	ld c, NAME_LENGTH
	call SlinkTradeSnapshotCompare
	jr c, .done
	ld hl, wPartyMonNicknames
	ld de, MON_NAME_LENGTH
	call SlinkTradeSnapshotOffset
	ld de, wOTPartyMonNicknames + MON_NAME_LENGTH
	ld c, MON_NAME_LENGTH
	call SlinkTradeSnapshotCompare
.done
	pop hl
	pop de
	pop bc
	ret

SlinkTradeReleaseSnapshot::
	; Native-parity policy: unused OT slots remain garbage; G/S can save them,
	; Crystal excludes this scratch from saves. Do not erase or restore OT data.
	; Caller must end the held-foreground lease before enabling other consumers.
	ret

; A slot -> B slot and HL selected live record, carry refusal, no WRAM writes.
SlinkTradeSnapshotPartyPointer:
	ld b, a
	ld a, [wPartyCount]
	and a
	jr z, .refuse
	cp PARTY_LENGTH + 1
	jr nc, .refuse
	cp b
	jr c, .refuse
	jr z, .refuse
	ld hl, wPartyMon1
	ld de, PARTYMON_STRUCT_LENGTH
	call SlinkTradeSnapshotOffset
	ld a, [hl]
	ld c, a
	push hl
	ld hl, wPartySpecies
	ld d, 0
	ld e, b
	add hl, de
	ld a, [hl]
	pop hl
	cp EGG
	jr z, .valid
	cp c
	jr nz, .refuse
.valid
	and a
	ret
.refuse
	scf
	ret

; HL base, DE stride, B slot -> HL selected slot. B is retained across spans.
SlinkTradeSnapshotOffset:
	ld a, b
	and a
	ret z
.next
	add hl, de
	dec a
	jr nz, .next
	ret

SlinkTradeSnapshotCopy:
	ld a, [hli]
	ld [de], a
	inc de
	dec c
	jr nz, SlinkTradeSnapshotCopy
	ret

SlinkTradeSnapshotCompare:
	ld a, [de]
	cp [hl]
	jr nz, .refuse
	inc hl
	inc de
	dec c
	jr nz, SlinkTradeSnapshotCompare
	and a
	ret
.refuse
	scf
	ret
