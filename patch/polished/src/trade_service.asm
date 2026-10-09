; SLink companion overlay -- Polished Crystal trade card C1a: the PROPOSER-ONLY held trade service,
; COMMIT DISABLED (docs/polished/TRADE.md sections 11, 12, 14, 15, 16, 17). Port of patch/gen2/src/trade_service.asm.
;
; Entered through SlinkTradeEntry (trade_gate.asm: `jp SlinkTradeProposerService`) from the timeout gate,
; i.e. from a native special inside the Pokecenter 2F receptionist script, after the script's own forced
; save. It returns with `ret` to the gate, which then redirects the script at a bare `endtext`.
;
; Held foreground transaction. Only the ten-byte caller-frame context lives on the CPU stack (never in the
; mailbox: its 69 bytes are fully reserved): token[4], own slot, local role, generation, result, party count,
; flags (unused by the proposer; kept so the layout is the vanilla one). Every exit goes through
; SlinkTradeExit, which closes the lease and pops the context, so the stack is balanced on EVERY path.
;
; Flow (lease byte offsets as lua/gb_trade_lease.lua):
;   entry guards -> QUERY (publish, wait <= 600 frames) -> reject mask 0 / bits above the party count ->
;   native party menu (SelectTradeOrDayCareMon) -> Polished predicates on the picked mon -> native
;   confirm (YesNoBox) -> SlinkTradeSnapshot -> OFFER (wait <= 600, result must be 0) -> wait <= 3600 for
;   the host's APPLY (the incoming mon staged at OT slot 0) -> validate -> DONE result 1 ("not performed:
;   commit disabled", NEVER 0) -> bounded RELEASE wait (90 frames or B) -> close the lease.
; Nothing here writes a party, a box, the save or SRAM: the only writes are the lease bytes, the stack, OT
; slot 1 (the snapshot) and what the native UI routines themselves touch. A QUERY/OFFER timeout, B,
; an OFFER reject, a token/slot/generation drift or any invalid APPLY closes the lease with no DONE.
;
; Differences from vanilla: no wPartySpecies list (the species-list/EGG logic is gone), the party menu is
; Polished's SelectTradeOrDayCareMon, a held item and the record must pass SlinkTradeItemAllowed and
; SlinkTradeValidateRecord, hVBlank must be exactly 0 (it is a 0..8 mode selector in Polished, there is no
; VBLANK_NORMAL), the incoming OT slot 0 is the SCATTERED staging checked by SlinkTradeValidateIncomingStaged,
; and the whole responder branch, the animation, the commit and the result-0/2 holds are dropped.

ASSERT SLINK_SERVICE_BANK == $7E ; fixed, like the other trade sections
ASSERT PARTYMON_STRUCT_LENGTH == 48
ASSERT PARTY_LENGTH == 6

DEF SLINK_TRADE_CONTEXT_SIZE EQU 10
; Host waits, in frames (60 Hz). B cancels every one of them (SlinkTradeWaitFrame).
; QUERY/OFFER: the host answers in the reply to our own event, so the need is one network round trip.
DEF SLINK_TRADE_QUERY_FRAMES EQU 600
DEF SLINK_TRADE_OFFER_FRAMES EQU 600
; APPLY: the partner's prompt, a human's YES/NO and our apply_trade delivered on the next host tick.
DEF SLINK_TRADE_APPLY_FRAMES EQU 3600
; Declining/refusing made no mutation, so the RELEASE wait may safely close without a host.
DEF SLINK_TRADE_RELEASE_FRAMES EQU 90
DEF SLINK_TRADE_RESULT_NOT_PERFORMED EQU 1
; Deliberate build-time authorization gate. Symbol presence is NOT enablement.
IF !DEF(SLINK_TRADE_COMMIT_ENABLE)
DEF SLINK_TRADE_COMMIT_ENABLE EQU 1
ENDC
ASSERT SLINK_TRADE_COMMIT_ENABLE == 0 || SLINK_TRADE_COMMIT_ENABLE == 1

SECTION "SLink Trade Service", ROMX[$4a00], BANK[SLINK_SERVICE_BANK]

SlinkTradeProposerService::
	; The receptionist script (maps/PokeCenter2F.asm) has already forced the native full save.
	add sp, -SLINK_TRADE_CONTEXT_SIZE
	call SlinkTradeZeroContext
	call SlinkTradeCheckSaved
	jp c, SlinkTradeExit
	call SlinkTradeCheckParty
	jp c, SlinkTradeExit ; refused before any QUERY is published
	call SlinkTradeWriteHeader
	ld a, SLINK_TRADE_CMD_QUERY
	ld [SLINK_TRADE_FRAME + 5], a
	xor a
	ld [SLINK_TRADE_FRAME + 10], a
	ld [SLINK_TRADE_FRAME + 11], a
	call SlinkTradeNextGeneration
	ld bc, SLINK_TRADE_QUERY_FRAMES
	call SlinkTradeWaitAck
	jp c, SlinkTradeExit
	call SlinkTradeCheckHeader
	jp c, SlinkTradeExit
	ld a, [SLINK_TRADE_FRAME + 5]
	cp SLINK_TRADE_CMD_QUERY
	jp nz, SlinkTradeExit
	ld a, [SLINK_TRADE_FRAME + 10]
	cp 1
	jp nz, SlinkTradeExit
	call SlinkTradeCheckMask
	jp c, SlinkTradeExit ; mask 0 or a bit above the party count: no menu is shown
	call SlinkTradeCaptureContext
	ld hl, sp + 0
	call SlinkTradeCheckToken
	jp c, SlinkTradeExit
	ld hl, sp + 5
	ld [hl], 0 ; proposer role is local, never host-supplied
	ld a, [wPartyCount]
	and a
	jp z, SlinkTradeExit
	cp PARTY_LENGTH + 1
	jp nc, SlinkTradeExit ; reject malformed parties before native menu indexing
	ld b, PARTYMENUACTION_GIVE_MON
	farcall SelectTradeOrDayCareMon ; carry = cancelled; the pick is in wCurPartyMon
	jp c, SlinkTradeExit
	ld a, [wCurPartyMon]
	ld hl, sp + 4
	ld [hl], a
	call SlinkTradeCheckOwnSlot
	jp c, SlinkTradeExit
	ld hl, sp + 4
	ld a, [hl]
	call SlinkTradeSlotInMask
	jp c, SlinkTradeExit ; the host must have offered this very slot
	ld hl, SlinkTradeConfirmText
	call PrintText
	call YesNoBox
	jp c, SlinkTradeExit ; carry = NO
	ld hl, SlinkTradeWaitText
	call PrintText
	call SlinkTradeCheckHeader
	jp c, SlinkTradeExit
	ld a, [SLINK_TRADE_FRAME + 5]
	cp SLINK_TRADE_CMD_QUERY
	jp nz, SlinkTradeExit
	ld hl, sp + 0
	call SlinkTradeCheckHeldFrame
	jp c, SlinkTradeExit
	ld hl, sp + 4
	ld a, [hl]
	call SlinkTradeCheckOwnSlot
	jp c, SlinkTradeExit
	ld hl, sp + 4
	ld a, [hl]
	call SlinkTradeSnapshot ; only after every native menu has returned
	jp c, SlinkTradeExit
	ld hl, sp + 4
	ld a, [hl]
	ld [SLINK_TRADE_FRAME + 9], a
	ld a, $ff
	ld [SLINK_TRADE_FRAME + 8], a
	ld a, SLINK_TRADE_CMD_OFFER
	ld [SLINK_TRADE_FRAME + 5], a
	call SlinkTradeNextGeneration
	ld hl, sp + 6
	ld [hl], a
	ld bc, SLINK_TRADE_OFFER_FRAMES
	call SlinkTradeWaitAck
	jp c, SlinkTradeExit
	call SlinkTradeCheckHeader
	jp c, SlinkTradeExit
	ld hl, sp + 0
	call SlinkTradeCheckToken
	jp c, SlinkTradeExit
	ld a, [SLINK_TRADE_FRAME + 5]
	cp SLINK_TRADE_CMD_OFFER
	jp nz, SlinkTradeExit
	ld a, [SLINK_TRADE_FRAME + 8]
	and a
	jp nz, SlinkTradeExit ; the host rejected (or never answered: $ff)
	; fallthrough

SlinkTradeWaitApply::
	ld bc, SLINK_TRADE_APPLY_FRAMES
	jr .wait
.next
	; The frame just returned has been INSPECTED and was not an APPLY: only now does the counter expire, so
	; all SLINK_TRADE_APPLY_FRAMES frames (the last one included) can carry the request.
	dec bc
	ld a, b
	or c
	jp z, SlinkTradeExit
.wait
	call SlinkTradeWaitFrame
	jp c, SlinkTradeExit ; timeout/B before APPLY never mutates anything
	call SlinkTradeCheckHeader
	jp c, SlinkTradeExit
	ld hl, sp + 0
	call SlinkTradeCheckToken
	jp c, SlinkTradeExit
	ld a, [SLINK_TRADE_FRAME + 5]
	cp SLINK_TRADE_CMD_APPLY
	jr nz, .next
	ld a, [SLINK_TRADE_FRAME + 6]
	ld d, a
	ld a, [SLINK_TRADE_FRAME + 7]
	cp d
	jr z, .next ; an acknowledged generation is not a fresh request
	ld hl, sp + 6
	ld a, [SLINK_TRADE_FRAME + 7]
	cp [hl]
	jp nz, SlinkTradeExit ; the arm retains the previous generation as ACK
	ld a, [hl]
	inc a ; exactly previous+1, including $ff -> $00
	cp d
	jp nz, SlinkTradeExit
	ld [hl], d
	ld hl, sp + 4
	ld a, [SLINK_TRADE_FRAME + 9]
	cp [hl]
	jp nz, SlinkTradeExit ; private selected slot cannot be redirected
	; Host picked_up hook sees the original armed frame before ACK changes.
	ld a, d
	ld [SLINK_TRADE_FRAME + 7], a ; pickup before any validation
	call SlinkTradeValidateIncomingStaged
	jp c, SlinkTradeExit
	ld hl, sp + 8
	ld a, [wPartyCount]
	cp [hl]
	jp nz, SlinkTradeExit ; the party changed under the held transaction
	ld hl, sp + 4
	ld a, [hl]
	call SlinkTradeCheckOwnSlot
	jp c, SlinkTradeExit
	ld hl, sp + 4
	ld a, [hl]
	call SlinkTradeValidateSnapshot
	jp c, SlinkTradeExit
IF SLINK_TRADE_COMMIT_ENABLE
	jp SlinkTradeApplyCommit ; tail jump: shared waits require context-base SP
ENDC
	; COMMIT DISABLED: nothing is applied, so the honest result is 1 ("not performed"), never 0.
	ld a, SLINK_TRADE_RESULT_NOT_PERFORMED
	call SlinkTradePublishDone
	; fallthrough

SlinkTradeWaitRelease::
	; Counter-before-inspection is harmless here: RELEASE and expiry take the same exit (SlinkTradeExit), so
	; a RELEASE seen on the final frame changes nothing observable (unlike the APPLY wait above).
	ld bc, SLINK_TRADE_RELEASE_FRAMES
.wait
	call SlinkTradeWaitFrame
	jp c, SlinkTradeExit
	dec bc
	ld a, b
	or c
	jp z, SlinkTradeExit
	call SlinkTradeCheckHeader
	jr c, .wait
	ld hl, sp + 0
	call SlinkTradeCheckToken
	jr c, .wait
	ld a, [SLINK_TRADE_FRAME + 5]
	cp SLINK_TRADE_CMD_RELEASE
	jr nz, .wait
	ld hl, sp + 6
	ld a, [SLINK_TRADE_FRAME + 6]
	cp [hl]
	jr nz, .wait
	ld a, [SLINK_TRADE_FRAME + 7]
	cp [hl]
	jr nz, .wait
	; fallthrough

SlinkTradeExit::
	call SlinkTradeReleaseSnapshot
	call SlinkTradeClose
	add sp, SLINK_TRADE_CONTEXT_SIZE
	ret

SlinkTradeZeroContext::
	; QUERY may fail before CaptureContext; never inspect uninitialised context bytes.
	ld hl, sp + 2
	ld b, SLINK_TRADE_CONTEXT_SIZE
	xor a
.clear
	ld [hli], a
	dec b
	jr nz, .clear
	ret

SlinkTradeWriteHeader::
	ld hl, SLINK_TRADE_FRAME
	ld a, SLINK_TRADE_MAGIC_0
	ld [hli], a
	ld a, SLINK_TRADE_MAGIC_1
	ld [hli], a
	ld a, SLINK_TRADE_MAGIC_2
	ld [hli], a
	ld a, SLINK_TRADE_MAGIC_3
	ld [hli], a
	ld a, SLINK_TRADE_VERSION
	ld [hl], a
	ret

SlinkTradeNextGeneration::
	; ACK = the old generation, then the new generation LAST (it is what publishes the frame).
	ld a, [SLINK_TRADE_FRAME + 6]
	ld [SLINK_TRADE_FRAME + 7], a
	inc a
	ld [SLINK_TRADE_FRAME + 6], a ; publish last
	ret

SlinkTradeCaptureContext::
	ld hl, sp + 2
	ld de, SLINK_TRADE_FRAME + 12
	ld c, 4
.copy
	ld a, [de]
	inc de
	ld [hli], a
	dec c
	jr nz, .copy
	ld a, [SLINK_TRADE_FRAME + 9]
	ld [hli], a
	xor a
	ld [hli], a
	ld a, [SLINK_TRADE_FRAME + 6]
	ld [hli], a
	xor a
	ld [hli], a
	ld a, [wPartyCount]
	ld [hli], a
	xor a
	ld [hl], a
	ret

SlinkTradePublishDone::
	; A = result. Header, token, slot and command first; generation, then ACK = the same generation, LAST.
	ld hl, sp + 9
	ld [hl], a ; retain the result locally
	ld [SLINK_TRADE_FRAME + 8], a
	call SlinkTradeWriteHeader
	ld hl, sp + 2
	ld de, SLINK_TRADE_FRAME + 12
	ld c, 4
.token
	ld a, [hli]
	ld [de], a
	inc de
	dec c
	jr nz, .token
	ld hl, sp + 6
	ld a, [hl]
	ld [SLINK_TRADE_FRAME + 9], a
	ld a, SLINK_TRADE_CMD_DONE
	ld [SLINK_TRADE_FRAME + 5], a
	ld hl, sp + 8
	ld a, [hl]
	ld [SLINK_TRADE_FRAME + 6], a
	ld [SLINK_TRADE_FRAME + 7], a ; DONE only after every check
	ret

SlinkTradeWaitAck::
	; BC = frames, A = the generation that must be published AND acknowledged. Carry = refused.
	ld d, a ; generation must match, not merely gen==ack in a replacement frame
.wait
	call SlinkTradeWaitFrame
	ret c
	ld a, [SLINK_TRADE_FRAME + 6]
	cp d
	jr nz, .refuse
	ld a, [SLINK_TRADE_FRAME + 7]
	cp d
	ret z
	dec bc
	ld a, b
	or c
	jr nz, .wait
.refuse
	scf
	ret

SlinkTradeWaitFrame::
	; Precommit waits admit only the normal ISR: hVBlank is a 0..8 mode selector in Polished and 0 is the
	; idle one. Carry = refused (hVBlank != 0) or B pressed. Not a stack bound for native UI.
	ldh a, [hVBlank]
	and a
	jr nz, .refuse
	push bc
	push de
	call DelayFrame
	call JoyTextDelay
	ldh a, [hJoyPressed]
	and PAD_B
	pop de
	pop bc
	ret z
.refuse
	scf
	ret

SlinkTradeCheckSaved::
	; Carry unless a full native save exists (set by the native save path).
	ld a, [wSavedAtLeastOnce]
	and a
	ret nz
	scf
	ret

SlinkTradeCheckParty::
	; Carry refuses a Bug-Catching Contest party (the contest hides slots 2-6 until it ends) and a party
	; count outside 1..PARTY_LENGTH. Clobbers AF.
	ld a, [wStatusFlags2]
	bit STATUSFLAGS2_BUG_CONTEST_TIMER_F, a
	jr nz, .refuse
	ld a, [wPartyCount]
	and a
	jr z, .refuse
	cp PARTY_LENGTH + 1
	jr nc, .refuse
	and a ; accepted: clear carry
	ret
.refuse
	scf
	ret

SlinkTradeCheckMask::
	; Carry unless 0 < host mask < 1 << wPartyCount. Clobbers AF, BC.
	ld a, [SLINK_TRADE_FRAME + 11]
	and a
	jr z, .refuse
	ld b, a
	ld a, [wPartyCount]
	and a
	jr z, .refuse
	cp PARTY_LENGTH + 1
	jr nc, .refuse
	ld c, a
	ld a, b
.shift
	srl a
	dec c
	jr nz, .shift
	and a ; bits left above the party count?
	ret z
.refuse
	scf
	ret

SlinkTradeSlotInMask::
	; A = slot. Carry unless bit A of the host's eligibility mask is set. Clobbers AF, B.
	ld b, a
	ld a, [SLINK_TRADE_FRAME + 11]
	inc b
.shift
	dec b
	jr z, .test
	srl a
	jr .shift
.test
	srl a ; bit 0 -> carry
	ccf   ; carry = the bit was clear
	ret

SlinkTradeCheckOwnSlot::
	; A = zero-based own party slot. Carry unless the party is 1..6 outside the contest, the slot exists, and
	; its held item and its record pass the Polished predicates (mail policy). Clobbers AF, BC, HL.
	push af
	call SlinkTradeCheckParty
	jr c, .refuseParty
	pop af
	cp PARTY_LENGTH
	jr nc, .refuse
	ld c, a
	ld a, [wPartyCount]
	cp c
	jr z, .refuse ; slot == count
	jr c, .refuse ; slot > count
	ld a, c
	ld hl, wPartyMon1
	ld bc, PARTYMON_STRUCT_LENGTH
	rst AddNTimes
	push hl
	inc hl
	ld a, [hl] ; held item
	call SlinkTradeItemAllowed
	pop hl
	ret c
	jp SlinkTradeValidateRecord
.refuseParty
	pop af
.refuse
	scf
	ret

SlinkTradeCheckHeldFrame::
	; HL points to the private context captured before native UI. UI return must not accept a replacement
	; visit with the same opaque token.
	call SlinkTradeCheckHeader
	ret c
	call SlinkTradeCheckToken
	ret c
	ld de, 6
	add hl, de
	ld a, [SLINK_TRADE_FRAME + 6]
	cp [hl]
	jr nz, .refuse
	ld a, [SLINK_TRADE_FRAME + 7]
	cp [hl]
	ret z
.refuse
	scf
	ret

SlinkTradeConfirmText:
	text "SLINK TRADE?"
	done

SlinkTradeWaitText:
	text "Waiting for"
	line "partner. B: cancel"
	done
SlinkTradeProposerServiceEnd::

ASSERT @ <= $5000, "the proposer service overran its $4a00-$4fff slot"
