; Held foreground transaction. Only the ten-byte context lives on the stack:
; token[4], own slot, local role, generation, result, party count, release gate.
; Snapshot storage is injected by SlinkTradeSnapshot/ValidateSnapshot.
DEF SLINK_TRADE_CONTEXT_SIZE EQU 10
DEF SLINK_TRADE_APPLY_FRAMES EQU 1800 ; 30 seconds at nominal 60 Hz for peer UI

SECTION "SLink Trade Service", ROMX, BANK[SLINK_SERVICE_BANK]

SlinkTradeInit::
	ld hl, SLINK_TRADE_FRAME
	ld b, SLINK_TRADE_LEASE_SIZE
	xor a
.clear
	ld [hli], a
	dec b
	jr nz, .clear
	ret

SlinkTradeEntry::
	add sp, -SLINK_TRADE_CONTEXT_SIZE
	call SlinkTradeZeroContext
	call SlinkTradeWriteHeader
	ld a, SLINK_TRADE_CMD_QUERY
	ld [SLINK_TRADE_FRAME + 5], a
	xor a
	ld [SLINK_TRADE_FRAME + 10], a
	ld [SLINK_TRADE_FRAME + 11], a
	call SlinkTradeNextGeneration
	ld bc, 30
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
	ld a, [SLINK_TRADE_FRAME + 11]
	and $c0
	jp nz, SlinkTradeExit
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
	farcall SelectTradeOrDayCareMon
	jp c, SlinkTradeExit
	ld a, [wCurPartyMon]
	ld hl, sp + 4
	ld [hl], a
	call SlinkTradeCheckOwnSlot
	jp c, SlinkTradeExit
	; Query eligibility is a six-bit mask. Require the selected bit.
	ld a, [wCurPartyMon]
	ld c, a
	ld a, [SLINK_TRADE_FRAME + 11]
.mask
	ld b, a
	ld a, c
	and a
	ld a, b
	jr z, .maskDone
	dec c
	srl a
	jr .mask
.maskDone
	and 1
	jp z, SlinkTradeExit
	ld hl, SlinkTradeConfirmText
	call PrintText
	call YesNoBox
	jp c, SlinkTradeExit
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
	call SlinkTradeSnapshot
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
	ld bc, 180
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
	jp nz, SlinkTradeExit
	jp SlinkTradeWaitApply

SlinkTradePromptEntry::
	; Dispatcher has already checked safe overworld context; repeat publication.
	call SlinkTradeCheckHeader
	ret c
	ld a, [SLINK_TRADE_FRAME + 5]
	cp SLINK_TRADE_CMD_PROMPT
	ret nz
	ld a, [SLINK_TRADE_FRAME + 6]
	ld b, a
	ld a, [SLINK_TRADE_FRAME + 7]
	cp b
	ret z ; an acknowledged generation cannot re-enter native UI
	add sp, -SLINK_TRADE_CONTEXT_SIZE
	call SlinkTradeCaptureContext
	ld hl, sp + 0
	call SlinkTradeCheckToken
	jp c, SlinkTradeExit
	ld a, b
	ld [SLINK_TRADE_FRAME + 7], a ; pickup before any native work
	ld hl, sp + 5
	ld [hl], 1 ; responder role is local
	ld hl, sp + 9
	ld [hl], 1 ; require PROMPT's matching RELEASE before accepting APPLY
	ld hl, sp + 4
	ld a, [hl]
	call SlinkTradeCheckOwnSlot
	jp c, SlinkTradeExit
	call OpenText
	ld hl, SlinkTradeConfirmText
	call PrintText
	call YesNoBox
	push af
	call CloseText
	pop af
	jr c, .decline
	ld hl, sp + 0
	call SlinkTradeCheckHeldFrame
	jp c, SlinkTradeExit
	ld a, [SLINK_TRADE_FRAME + 5]
	cp SLINK_TRADE_CMD_PROMPT
	jp nz, SlinkTradeExit
	ld hl, sp + 4
	ld a, [hl]
	call SlinkTradeCheckOwnSlot
	jp c, SlinkTradeExit
	ld hl, sp + 4
	ld a, [hl]
	call SlinkTradeSnapshot
	jp c, SlinkTradeExit
	xor a
	call SlinkTradePublishDone
	; PROMPT completion is not a commit. Hold the same visit through RELEASE.
	jp SlinkTradeWaitApply
.decline
	ld a, 1
	call SlinkTradePublishDone
	jp SlinkTradeWaitRelease

SlinkTradeWaitApply::
	ld bc, SLINK_TRADE_APPLY_FRAMES
.wait
	call SlinkTradeWaitFrame
	jp c, SlinkTradeExit ; timeout/B before APPLY never mutates party/save
	dec bc
	ld a, b
	or c
	jp z, SlinkTradeExit
	call SlinkTradeCheckHeader
	jp c, SlinkTradeExit
	ld hl, sp + 0
	call SlinkTradeCheckToken
	jp c, SlinkTradeExit
	ld a, [SLINK_TRADE_FRAME + 5]
	ld d, a
	ld hl, sp + 9
	ld a, [hl]
	and a
	jr z, .applyCommand
	ld a, d
	cp SLINK_TRADE_CMD_RELEASE
	jr nz, .wait
	ld hl, sp + 6
	ld a, [SLINK_TRADE_FRAME + 6]
	cp [hl]
	jp nz, SlinkTradeExit
	ld a, [SLINK_TRADE_FRAME + 7]
	cp [hl]
	jp nz, SlinkTradeExit
	ld hl, sp + 9
	ld [hl], 0
	jr .wait
.applyCommand
	ld a, d
	cp SLINK_TRADE_CMD_APPLY
	jr nz, .wait
	ld a, [SLINK_TRADE_FRAME + 6]
	ld d, a
	ld a, [SLINK_TRADE_FRAME + 7]
	cp d
	jr z, .wait
	ld hl, sp + 6
	ld a, [SLINK_TRADE_FRAME + 7]
	cp [hl]
	jp nz, SlinkTradeExit ; shared arm retains the previous generation as ACK
	ld a, [hl]
	inc a ; shared arm publishes exactly previous+1, including $ff->$00
	cp d
	jp nz, SlinkTradeExit
	ld [hl], d
	ld hl, sp + 4
	ld a, [SLINK_TRADE_FRAME + 9]
	cp [hl]
	jp nz, SlinkTradeExit ; private selected slot cannot be redirected
SlinkTradeApplyPickup::
	; Host picked_up hook sees the original armed frame before ACK changes.
	ld a, d
	ld [SLINK_TRADE_FRAME + 7], a ; pickup before validation/native mutation
	call SlinkTradeCheckIncoming
	jp c, SlinkTradeExit
	ld hl, sp + 8
	ld a, [wPartyCount]
	cp [hl]
	jp nz, SlinkTradeExit
	ld hl, sp + 4
	ld a, [hl]
	call SlinkTradeCheckOwnSlot
	jp c, SlinkTradeExit
	ld hl, sp + 4
	ld a, [hl]
	call SlinkTradeValidateSnapshot
	jp c, SlinkTradeExit
	; No cancellation boundary after the preimage comparison and commit call.
	ld hl, sp + 5
	ld b, [hl]
	dec hl
	ld a, [hl]
	call SlinkTradeCommit
	ld c, a
	ld hl, sp + 5
	ld a, [hl]
	and a
	jr z, .result
	ld hl, sp + 9
	set 7, [hl] ; responder has no script closetext after native map restoration
.result
	ld a, c
	and a
	jr z, .commitResult
	ld a, 2 ; no unexpected helper result may claim a safe refusal after mutation
.commitResult
	call SlinkTradePublishDone
	jp SlinkTradeWaitRelease

SlinkTradeWaitRelease::
	ld bc, 90 ; declining made no mutation, so it may safely close without a host
.wait
	; A committed result has no timeout/B escape. An uncertain append (2)
	; remains held for recovery; neither delay nor disconnect invents success.
	ld hl, sp + 7
	ld a, [hl]
	cp 1
	jr nz, .committed
	call SlinkTradeWaitFrame
	jp c, SlinkTradeExit
	dec bc
	ld a, b
	or c
	jp z, SlinkTradeExit
	jr .check
.committed
	call DelayFrame
.check
	ld hl, sp + 7
	ld a, [hl]
	cp 2
	jr z, .wait
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
SlinkTradeExit::
	call SlinkTradeReleaseSnapshot
	call SlinkTradeClose
	ld hl, sp + 9
	bit 7, [hl]
	jr z, .closed
	call CloseText
.closed
	add sp, SLINK_TRADE_CONTEXT_SIZE
	ret

SlinkTradeZeroContext::
	; QUERY may fail before CaptureContext; never inspect uninitialized cleanup flags.
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
	ld hl, sp + 9
	ld [hl], a ; retain result locally across final RELEASE wait
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
	ld [SLINK_TRADE_FRAME + 7], a ; DONE only after native work
	ret

SlinkTradeWaitAck::
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
	; Precommit waits admit only the normal ISR. This is not a stack bound
	; for native commit/animation or the uncancellable postcommit release wait.
	ldh a, [hVBlank]
	cp VBLANK_NORMAL
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

SlinkTradeCheckOwnSlot::
	cp PARTY_LENGTH
	jr nc, .refuse
	ld c, a
	ld a, [wPartyCount]
	cp PARTY_LENGTH + 1
	jr nc, .refuse
	cp c
	jr z, .refuse
	jr c, .refuse
	ld a, c
	ld hl, wPartyMon1
	ld bc, PARTYMON_STRUCT_LENGTH
	call AddNTimes
	ld a, [hli]
	and a
	jr z, .refuse
	cp NUM_POKEMON + 1
	jr nc, .refuse
	ld a, [hl]
	jp SlinkTradeItemAllowed
.refuse
	scf
	ret

SlinkTradeCheckHeldFrame::
	; HL points to the private context captured before native UI. UI return
	; must not accept a replacement visit with the same opaque token.
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

SlinkTradeCheckIncoming::
	; Local shape/item/render guards, not a complete semantic record validator.
	; Host payload validation and the independent native-save oracle remain required.
	ld a, [wOTPartyCount]
	cp 1
	jr nz, .refuse
	ld a, [wOTPartySpecies + 1]
	cp $ff
	jr nz, .refuse
	ld a, [wOTPartyMon1Species]
	and a
	jr z, .refuse
	cp NUM_POKEMON + 1
	jr nc, .refuse
	ld b, a
	ld a, [wOTPartySpecies]
	cp EGG
	jr z, .item
	cp b
	jr nz, .refuse
.item
	ld a, [wOTPartyMon1Item]
	call SlinkTradeItemAllowed
	ret c
	ld hl, wOTPartyMonOTs
	call SlinkTradeCheckName
	ret c
	ld hl, wOTPartyMonNicknames
	call SlinkTradeCheckName
	ret c
	ld hl, wOTPlayerName ; copied to animation's trainer-name buffer by Commit
	jp SlinkTradeCheckName
.refuse
	scf
	ret

SlinkTradeCheckName::
	; constants/charmap.asm: <$60 are text controls/substitutions; $50 ends.
	; $60-$7e are native glyphs too (quotes/ellipsis), not formatting commands.
	ld b, NAME_LENGTH
.byte
	ld a, [hli]
	cp $50
	jr z, .valid
	cp $60
	jr c, .refuse
	dec b
	jr nz, .byte
.refuse
	scf
	ret
.valid
	and a
	ret

SlinkTradeConfirmText:
	text "SLINK TRADE?"
	done
