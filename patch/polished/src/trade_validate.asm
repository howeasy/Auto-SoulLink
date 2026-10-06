; SLink companion overlay -- Polished Crystal trade card 2a: the INCOMING-MON validity predicates
; (docs/polished/TRADE.md section 14). INERT: nothing calls them until the held service lands.
;
; Native OT staging is SCATTERED, not contiguous: OT slot 0 is the 48-byte record at wOTPartyMon1, the
; 11-byte OT field (8 text + 3 metadata bytes) at wOTPartyMonOTs, the 11-byte nickname at
; wOTPartyMonNicknames and the sender's trainer name (11) at wOTPlayerName. So the predicate is split:
;   SlinkTradeValidateRecord   HL = a 48-byte party record: species, level, item, nature
;   SlinkTradeValidateText     HL = a name buffer, B = its max text length (8 or 11)
;   SlinkTradeValidateIncomingStaged   no arguments: all four pieces at their native staged addresses
;   SlinkTradeValidateIncoming         HL = a contiguous 70-byte blob P(48)||O(11)||N(11) (the model form;
;                                      the staged wrapper does NOT use it)
; All return carry = REFUSED, clear = acceptable; BC/DE/HL preserved; AF clobbered; READ-ONLY (only the
; stack is written). The caller selects bank $7E.
;
; Rules (zero-based offsets into the record P):
;   species s = P[0] + ((P[21] & $20) << 3): accept 1..$FE or $101..$123 ($FF and $100 are holes)
;   level   P[31] in 1..100 (eggs too)          item  P[1] must pass SlinkTradeItemAllowed (mail refused)
;   nature  (P[20] & $1F) < NUM_NATURES (25)
;   text    the first "@" ($53) within B bytes, none = refuse, every byte before it >= $5F
;   O[8:11] (the OT metadata) is never checked. An egg (P[21] & $40) is valid iff its species is.
; Moves, HP, status, stats and form policy are NOT checked here (host side): the native getters are
; unbounded, so this runs BEFORE any of them.

ASSERT SLINK_SERVICE_BANK == $7E ; fixed, like the other trade sections
ASSERT MON_ITEM == 1 && MON_PERSONALITY == 20 && MON_EXTSPECIES == 21 && MON_LEVEL == 31
ASSERT MON_EXTSPECIES_F == 5 && NATURE_MASK == $1f && NUM_NATURES == 25
ASSERT NUM_SPECIES == $123 && PARTYMON_STRUCT_LENGTH == 48 && NAME_LENGTH == 11 && MON_NAME_LENGTH == 11
ASSERT wOTPartyMonOTs == wOTPartyMon1OT && wOTPartyMonNicknames == wOTPartyMon1Nickname
ASSERT wOTPartyMon1 == wOTPartyMon1Species
DEF SLINK_TRADE_NAME_TERMINATOR EQU $53 ; "@" (constants/charmap.asm ctxtmap)
DEF SLINK_TRADE_NAME_FLOOR EQU $5f       ; "<MALE>", the lowest glyph byte a name may hold before the terminator
DEF SLINK_TRADE_OT_TEXT_LENGTH EQU 8

SECTION "SLink Trade Validate", ROMX[$4600], BANK[SLINK_SERVICE_BANK]

; HL = a 48-byte party record.
SlinkTradeValidateRecord::
	push bc
	push de
	push hl
	ld a, [hli]                       ; P[0] species low byte
	ld c, a
	ld a, [hl]                        ; P[1] held item
	call SlinkTradeItemAllowed
	jr c, .refuse
	ld de, MON_PERSONALITY - MON_ITEM ; &P[1] -> &P[20]
	add hl, de
	ld a, [hli]
	and NATURE_MASK
	cp NUM_NATURES
	jr nc, .refuse
	ld a, [hl]                        ; P[21]
	ld d, $fe                         ; no extension bit: species 1..$FE, i.e. C - 1 < $FE
	bit MON_EXTSPECIES_F, a
	jr z, .limit
	ld d, NUM_SPECIES - $100          ; extension bit: species $101..$123, i.e. C - 1 < $23
.limit
	ld a, c
	dec a
	cp d
	jr nc, .refuse
	ld de, MON_LEVEL - MON_EXTSPECIES ; &P[21] -> &P[31]
	add hl, de
	ld a, [hl]
	dec a
	cp 100
	jr nc, .refuse
	and a                             ; accepted: clear carry
	jr .done
.refuse
	scf
.done
	pop hl
	pop de
	pop bc
	ret

; HL = text start, B = field length. Carry = refused: no terminator in B bytes, or a byte before it is
; below SLINK_TRADE_NAME_FLOOR.
SlinkTradeValidateText::
	push bc
	push hl
.next
	ld a, [hli]
	cp SLINK_TRADE_NAME_TERMINATOR
	jr z, .ok
	cp SLINK_TRADE_NAME_FLOOR
	jr c, .refuse
	dec b
	jr nz, .next
.refuse
	scf
	jr .done
.ok
	and a
.done
	pop hl
	pop bc
	ret

; The staged incoming data of OT slot 0, where the native trade code leaves it. No arguments.
SlinkTradeValidateIncomingStaged::
	push bc
	push de
	push hl
	ld hl, wOTPartyMon1
	call SlinkTradeValidateRecord
	jr c, .done
	ld hl, wOTPartyMonOTs
	ld b, SLINK_TRADE_OT_TEXT_LENGTH
	call SlinkTradeValidateText
	jr c, .done
	ld hl, wOTPartyMonNicknames
	ld b, MON_NAME_LENGTH
	call SlinkTradeValidateText
	jr c, .done
	ld hl, wOTPlayerName
	ld b, NAME_LENGTH
	call SlinkTradeValidateText
.done
	pop hl
	pop de
	pop bc
	ret

; HL = a contiguous 70-byte blob P(48) || O(11) || N(11).
SlinkTradeValidateIncoming::
	push bc
	push de
	push hl
	call SlinkTradeValidateRecord
	jr c, .done
	ld de, PARTYMON_STRUCT_LENGTH     ; &P[0] -> &O[0]
	add hl, de
	ld b, SLINK_TRADE_OT_TEXT_LENGTH
	call SlinkTradeValidateText
	jr c, .done
	ld de, NAME_LENGTH                ; &O[0] -> &N[0]
	add hl, de
	ld b, MON_NAME_LENGTH
	call SlinkTradeValidateText
.done
	pop hl
	pop de
	pop bc
	ret
SlinkTradeValidateEnd::

ASSERT @ <= $4700, "the incoming predicates overran their $4600-$46FF slot"
