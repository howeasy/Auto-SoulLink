; APEX CHIP refusal (docs/purergb/PLAN.md §5.2 A1 / decision U6). An APEX CHIP sets a mon's DVs
; to $FFFF, so its Soul Link key (DVs:OTID:species) would collide with any mon of the same OT
; and species that already sits at $FFFF. The rules-only build can only undo the write after the
; chip is consumed; this guard runs BEFORE the DV store, from `ItemUseMedicine.setDVs`
; (engine/items/item_effects.asm, retargeted by tools/apply_purergb_overlay.py), and on a hit
; the item routine branches to its own .alreadyUsedApex refusal text with the chip still in
; the bag. Every other use proceeds untouched.
;
; in:  de = the target party mon's DV pointer (wPartyMonNDVs). It rides in de because a farcall
;      loads hl with the callee (macros/farcall.asm); the hook copies hl there and back.
; out: carry set = a colliding mon exists; de preserved; a/bc/hl clobbered (Bankswitch already
;      clobbers a and bc; the hook restores hl from de and reloads a).
; Scanned: the party, the box in WRAM, and (only once BIT_HAS_CHANGED_BOXES is set, i.e. the
; SRAM boxes have been initialised) the other eleven boxes in SRAM. The current box's SRAM copy
; is skipped: it is stale next to its WRAM image.

SECTION "SLink APEX guard", ROMX

SlinkApexGuard::
	push de
	ld h, d
	ld l, e
	ld bc, -MON_DVS
	add hl, bc
	ld d, h
	ld e, l ; de = the target's struct; it is never its own collision
	push de

	ld a, [wPartyCount]
	ld hl, wPartyMons
	ld bc, PARTYMON_STRUCT_LENGTH
	call .scanList
	jr c, .hit

	pop de
	push de
	ld hl, wBoxDataStart
	call .scanBox
	jr c, .hit

	ld a, [wCurrentBoxNum]
	bit BIT_HAS_CHANGED_BOXES, a
	jr z, .miss
	ld a, RAMG_SRAM_ENABLE
	ld [rRAMG], a
	ld a, BMODE_ADVANCED
	ld [rBMODE], a
	ld c, 0 ; box index 0..NUM_BOXES-1
.sramLoop
	ld a, [wCurrentBoxNum]
	and BOX_NUM_MASK
	cp c
	jr z, .nextBox ; the current box was scanned from WRAM
	ld a, c
	ld b, BANK(sBox1)
	ld hl, sBox1
	cp NUM_BOXES / 2
	jr c, .bankKnown
	sub NUM_BOXES / 2
	ld b, BANK(sBox7)
	ld hl, sBox7
.bankKnown
	push bc
	ld bc, wBoxDataEnd - wBoxDataStart
	call AddNTimes ; hl += a * box size
	pop bc
	ld a, b
	ld [rRAMB], a
	pop de
	push de
	push bc
	call .scanBox
	pop bc
	jr c, .sramHit
.nextBox
	inc c
	ld a, c
	cp NUM_BOXES
	jr c, .sramLoop
	call .closeSram
.miss
	pop hl ; the target struct
	pop de ; the DV pointer, handed back
	and a
	ret
.sramHit
	call .closeSram
.hit
	pop hl
	pop de
	scf
	ret

.closeSram
	xor a
	ld [rBMODE], a
	ld [rRAMG], a
	ret

; hl = a box (count, species list, structs); de = target. Carry = hit.
.scanBox
	ld a, [hli]
	cp MONS_PER_BOX + 1
	jr c, .countOk
	ld a, MONS_PER_BOX ; a corrupt count never walks past the box
.countOk
	ld bc, MONS_PER_BOX + 1 ; skip the species list
	add hl, bc
	ld bc, BOXMON_STRUCT_LENGTH
	; fall through

; hl = first struct, a = count, bc = stride, de = target. Carry = hit.
.scanList
	and a
	ret z
.scanLoop
	push af
	push bc
	push de
	push hl
	call .match
	pop hl
	pop de
	pop bc
	jr c, .found
	add hl, bc
	pop af
	dec a
	jr nz, .scanLoop
	and a
	ret
.found
	pop af
	scf
	ret

; hl = candidate struct, de = target struct. Carry = same species, same OT id, DVs $FFFF.
.match
	ld a, h
	cp d
	jr nz, .compare
	ld a, l
	cp e
	jr z, .noMatch ; the target itself
.compare
	ld a, [de]
	cp [hl]
	jr nz, .noMatch
	push hl
	push de
	ld bc, MON_OTID
	add hl, bc
	ld a, e
	add MON_OTID
	ld e, a
	jr nc, .otid
	inc d
.otid
	ld a, [de]
	cp [hl]
	jr nz, .noMatchPop
	inc hl
	inc de
	ld a, [de]
	cp [hl]
	jr nz, .noMatchPop
	ld bc, MON_DVS - MON_OTID - 1
	add hl, bc
	ld a, [hli]
	cp $FF
	jr nz, .noMatchPop
	ld a, [hl]
	cp $FF
	jr nz, .noMatchPop
	pop de
	pop hl
	scf
	ret
.noMatchPop
	pop de
	pop hl
.noMatch
	and a
	ret
