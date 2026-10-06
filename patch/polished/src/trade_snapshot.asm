; SLink companion overlay -- Polished Crystal trade card 2a: the outgoing SNAPSHOT (port of
; patch/gen2/src/trade_snapshot.asm). INERT: nothing calls it until the held service lands.
;
; The preimage is 70 bytes: the 48-byte party record, the 11-byte OT field (8 name bytes + the 3 extra
; metadata bytes, e.g. the Hyper Training mask) and the 11-byte nickname of ONE own party slot, copied
; into OT slot 1 (wOTPartyMon2 / wOTPartyMonOTs+11 / wOTPartyMonNicknames+11) while battle/START/SAVE
; are excluded. Incoming native trade data owns OT slot 0. There is NO mutation mask: Validate is exact
; equality of all 70 bytes, because no Polished trade-time effect rewrites the own record before commit.
; Differences from the vanilla port: Polished has no wPartySpecies list, so the species-list/EGG
; cross-check is dropped (the byte compare is the integrity check).
;
; ASSERTs pin every layout fact against the pinned source constants so growth/drift is loud.

ASSERT SLINK_SERVICE_BANK == $7E ; fixed, like the frame, item and gate sections
ASSERT PARTYMON_STRUCT_LENGTH == 48
ASSERT NAME_LENGTH == 11 && MON_NAME_LENGTH == 11
ASSERT PARTY_LENGTH == 6
ASSERT wOTPartyMon2 == wOTPartyMon1 + PARTYMON_STRUCT_LENGTH
ASSERT wOTPartyMonOTs + NAME_LENGTH == wOTPartyMon2OT
ASSERT wOTPartyMon2OT + 8 == wOTPartyMon2Extra
ASSERT wOTPartyMonNicknames + MON_NAME_LENGTH == wOTPartyMon2Nickname

SECTION "SLink Trade Snapshot", ROMX[$4500], BANK[SLINK_SERVICE_BANK]

; A = zero-based own party slot. Carry = refused (wPartyCount not 1..6, or slot >= count); clear = captured.
; BC/DE/HL preserved; AF clobbered. Writes only OT slot 1's record, OT field and nickname.
; Caller must have selected SLINK_SERVICE_BANK. Six stack bytes plus the call frames.
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

; A = the same slot. Carry = refused: invalid live bounds, or ANY of the 70 bytes differs from the capture.
; BC/DE/HL preserved; AF clobbered; no WRAM writes.
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

; Native-parity policy: the unused OT slots stay whatever they hold; nothing is erased or restored.
; The caller ends the held-foreground lease before enabling other consumers.
SlinkTradeReleaseSnapshot::
	ret

; A = slot -> B = slot, HL = wPartyMon1 + slot * 48. Carry = refused. No WRAM writes.
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
	and a
	ret
.refuse
	scf
	ret

; HL = base, DE = stride, B = slot -> HL = base + slot * stride. B is retained across spans.
SlinkTradeSnapshotOffset:
	ld a, b
	and a
	ret z
.next
	add hl, de
	dec a
	jr nz, .next
	ret

; HL source, DE destination, C bytes.
SlinkTradeSnapshotCopy:
	ld a, [hli]
	ld [de], a
	inc de
	dec c
	jr nz, SlinkTradeSnapshotCopy
	ret

; HL live, DE snapshot, C bytes. Carry = a byte differs.
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
SlinkTradeSnapshotEnd::

ASSERT @ <= $4600, "the snapshot overran its $4500-$45FF slot"
