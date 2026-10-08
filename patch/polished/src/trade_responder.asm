; SLink companion overlay -- Polished Crystal trade card C6: the held RESPONDER service, COMMIT DISABLED
; (docs/polished/TRADE_COMMIT_RESPONDER.md section 4; docs/polished/TRADE.md sections 14-18). Port of the
; responder branch of patch/gen2/src/trade_service.asm (:135-209, :210-352) onto the Polished lease/validators.
;
; Entered through SlinkTradePromptEntry (trade_dispatch.asm: `jp SlinkTradeResponderService`) from the
; responder DISPATCHER, i.e. from the DelayFrame bridge -> SlinkService -> SlinkTradeDispatch -> `push de /
; call SlinkTradePromptEntry`. The dispatcher has ALREADY checked the nine pinned stack bytes, the engine
; guards, the lease header, command == PROMPT and generation != ACK; this body re-checks the header, command
; and generation anyway (a direct entry never trusts its caller). It returns with `ret` to the dispatcher,
; which pops DE and returns to the bridge.
;
; Held foreground transaction. The same ten-byte context as the proposer lives on the CPU stack (never in the
; mailbox): token[4], own slot, local role (1 = responder), generation, result, party count, flags. The
; responder's flags: bit 0 = the RELEASE of the PROMPT generation is still owed before an APPLY is accepted,
; bit 7 = this visit owns an open text box that the exit closes exactly once (there is no receptionist
; script to run `endtext`). Every exit goes through SlinkTradeResponderExit, which releases the snapshot,
; closes the lease, closes the text and pops the context, so the stack is balanced on EVERY path.
;
; Flow (lease byte offsets as lua/gb_trade_lease.lua):
;   header, command PROMPT, generation != ACK, nonzero token, own slot (party 1..6, outside the contest,
;   Polished predicates, no mail), staged incoming mon (SlinkTradeValidateIncomingStaged) -> pickup ACK (the
;   PROMPT generation, last of the entry checks and BEFORE any native UI) -> OpenText, offer text, YesNoBox ->
;     NO / B: DONE result 1 (decline), bounded 90-frame RELEASE wait, close.
;     YES:    wait text -> re-check held frame / own slot / party count -> SlinkTradeSnapshot (ONLY after every native menu
;             has returned) -> DONE result 0 = CONSENT ONLY, never a completed trade (the commit does not
;             exist in this build) -> one 3600-frame wait shared by (1) the host's RELEASE of the PROMPT
;             generation and (2) its fresh APPLY (generation previous+1, ACK = previous, same token, same slot;
;             the APPLY is inspected BEFORE the counter expires, like the v8 proposer) -> pickup ACK ->
;             staged incoming re-validated, party count and own slot re-checked, own preimage compared with
;             the snapshot -> DONE result 1 ("not performed: commit disabled", NEVER 0 for an APPLY) ->
;             bounded 90-frame RELEASE wait -> close.
; B or a timeout in any wait closes the lease with no further publication. Nothing here writes a party, a
; box, the save, SRAM or OT slot 0: the only CPU writes are the lease bytes, the stack, OT slot 1 (the
; snapshot) and what the native UI routines (OpenText/PrintText/YesNoBox/CloseText/GetNickname) touch.
;
; NOT in this build (deliberately; they touch party/save and belong to the commit-enabled card): the
; consent-time FixPlayerEVsAndStats normalization and the user-confirmed Link_SaveGame of
; TRADE_COMMIT_RESPONDER.md 4(2)-(3), the commit call and the result-0/2 no-escape holds. Because this build
; has no commit, the consent snapshot is NOT post-normalization and must be re-taken by the commit card.

ASSERT SLINK_SERVICE_BANK == $7E ; fixed, like the other trade sections
ASSERT SLINK_TRADE_CONTEXT_SIZE == 10 ; the proposer's context layout (token, slot, role, gen, result, count, flags)

; PROMPT-phase DONE results (docs/polished/TRADE_COMMIT_RESPONDER.md section 4(3)): 0 = consent only, 1 = decline.
; An APPLY-phase DONE is always SLINK_TRADE_RESULT_NOT_PERFORMED (1) in this build.
DEF SLINK_TRADE_RESULT_CONSENT EQU 0
DEF SLINK_TRADE_RESULT_DECLINE EQU 1
DEF SLINK_RESP_FLAG_RELEASE_OWED EQU 0
DEF SLINK_RESP_FLAG_TEXT_OPEN EQU 7

; Fixed in the verified free bank-$7E interval above the proposer service (which ends at 7e:4cf0): the linker
; rejects any overlap with the other fixed sections, and the builder's span end covers this section.
SECTION "SLink Trade Responder", ROMX[$5000], BANK[SLINK_SERVICE_BANK]

SlinkTradeResponderService::
	add sp, -SLINK_TRADE_CONTEXT_SIZE
	call SlinkTradeZeroContext
	call SlinkTradeCheckHeader
	jp c, SlinkTradeResponderExit
	ld a, [SLINK_TRADE_FRAME + 5]
	cp SLINK_TRADE_CMD_PROMPT
	jp nz, SlinkTradeResponderExit
	ld a, [SLINK_TRADE_FRAME + 6]
	ld b, a
	ld a, [SLINK_TRADE_FRAME + 7]
	cp b
	jp z, SlinkTradeResponderExit ; an acknowledged generation never re-enters native UI
	call SlinkTradeCaptureContext
	ld hl, sp + 0
	call SlinkTradeCheckToken
	jp c, SlinkTradeResponderExit
	ld hl, sp + 5
	ld [hl], 1 ; responder role is local, never host-supplied
	ld hl, sp + 4
	ld a, [hl]
	call SlinkTradeCheckOwnSlot
	jp c, SlinkTradeResponderExit ; party 1..6, contest, slot, mail policy, own record predicates
	call SlinkTradeValidateIncomingStaged
	jp c, SlinkTradeResponderExit ; the staged incoming name is rendered below: validated first
	ld hl, sp + 6
	ld a, [hl]
	ld [SLINK_TRADE_FRAME + 7], a ; pickup ACK, last of the entry checks and before any native UI
	ld hl, sp + 4
	ld a, [hl]
	ld hl, wPartyMonNicknames
	call GetNickname ; own nickname into wStringBuffer1 for the offer text
	call OpenText
	ld hl, sp + 9
	set SLINK_RESP_FLAG_TEXT_OPEN, [hl] ; the exit closes this text box exactly once
	ld hl, SlinkTradeResponderOfferText
	call PrintText
	call YesNoBox
	jr c, .decline ; carry = NO or B
IF SLINK_TRADE_COMMIT_ENABLE
	ld hl, SlinkTradeCommitSaveText
	call PrintText
	call YesNoBox
	jp c, .decline
	farcall FixPlayerEVsAndStats
	farcall Link_SaveGame
	jp c, .decline
ENDC
	ld hl, SlinkTradeWaitText
	call PrintText
	ld hl, sp + 0
	call SlinkTradeCheckHeldFrame ; header, token, generation == ACK == this visit's PROMPT generation
	jp c, SlinkTradeResponderExit
	ld a, [SLINK_TRADE_FRAME + 5]
	cp SLINK_TRADE_CMD_PROMPT
	jp nz, SlinkTradeResponderExit
	ld hl, sp + 4
	ld a, [hl]
	call SlinkTradeCheckOwnSlot
	jp c, SlinkTradeResponderExit
	ld hl, sp + 8
	ld a, [wPartyCount]
	cp [hl]
	jp nz, SlinkTradeResponderExit ; the party changed under the native menus: refuse BEFORE snapshot and consent DONE
	ld hl, sp + 4
	ld a, [hl]
	call SlinkTradeSnapshot ; only after every native menu has returned
	jp c, SlinkTradeResponderExit
	ld hl, sp + 9
	set SLINK_RESP_FLAG_RELEASE_OWED, [hl]
	ld a, SLINK_TRADE_RESULT_CONSENT
	call SlinkTradePublishDone ; consent only: NEVER a completed-trade claim
	jr SlinkTradeResponderWait
.decline
	ld a, SLINK_TRADE_RESULT_DECLINE
	call SlinkTradePublishDone
	jp SlinkTradeResponderRelease

SlinkTradeResponderWait::
	; ONE budget of SLINK_TRADE_APPLY_FRAMES frames for the host's RELEASE of the PROMPT generation and then its
	; fresh APPLY. Every frame is INSPECTED before the counter expires (the v8 order), so a request published
	; in the final frame is still seen; B and timeouts take SlinkTradeResponderExit (no mutation exists here).
	ld bc, SLINK_TRADE_APPLY_FRAMES
	jr .wait
.next
	dec bc
	ld a, b
	or c
	jp z, SlinkTradeResponderExit
.wait
	call SlinkTradeWaitFrame
	jp c, SlinkTradeResponderExit ; timeout/B never mutates anything
	call SlinkTradeCheckHeader
	jp c, SlinkTradeResponderExit
	ld hl, sp + 0
	call SlinkTradeCheckToken
	jp c, SlinkTradeResponderExit
	ld a, [SLINK_TRADE_FRAME + 5]
	ld hl, sp + 9
	bit SLINK_RESP_FLAG_RELEASE_OWED, [hl]
	jr z, .applyPhase
	; (1) the RELEASE of the PROMPT generation is owed: an APPLY seen now is NOT accepted (RELEASE must be an
	; observed boundary of its own; the host must not overwrite it with an APPLY in the same unobserved frame).
	cp SLINK_TRADE_CMD_RELEASE
	jr nz, .next
	ld hl, sp + 6
	ld a, [SLINK_TRADE_FRAME + 6]
	cp [hl]
	jp nz, SlinkTradeResponderExit ; a RELEASE of another generation
	ld a, [SLINK_TRADE_FRAME + 7]
	cp [hl]
	jp nz, SlinkTradeResponderExit
	ld hl, sp + 9
	res SLINK_RESP_FLAG_RELEASE_OWED, [hl]
	jr .next
.applyPhase
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
	jp nz, SlinkTradeResponderExit ; the arm retains the previous generation as ACK
	ld a, [hl]
	inc a ; exactly previous+1, including $ff -> $00
	cp d
	jp nz, SlinkTradeResponderExit
	ld [hl], d
	ld hl, sp + 4
	ld a, [SLINK_TRADE_FRAME + 9]
	cp [hl]
	jp nz, SlinkTradeResponderExit ; private selected slot cannot be redirected
	ld a, d
	ld [SLINK_TRADE_FRAME + 7], a ; APPLY pickup ACK before any validation
	call SlinkTradeValidateIncomingStaged
	jp c, SlinkTradeResponderExit
	ld hl, sp + 8
	ld a, [wPartyCount]
	cp [hl]
	jp nz, SlinkTradeResponderExit ; the party changed under the held transaction
	ld hl, sp + 4
	ld a, [hl]
	call SlinkTradeCheckOwnSlot
	jp c, SlinkTradeResponderExit
	ld hl, sp + 4
	ld a, [hl]
	call SlinkTradeValidateSnapshot ; the own preimage must still be the consent snapshot
	jp c, SlinkTradeResponderExit
IF SLINK_TRADE_COMMIT_ENABLE
	jp SlinkTradeApplyCommit
ENDC
	; COMMIT DISABLED: nothing is applied, so the honest result is 1 ("not performed"), never 0.
	ld a, SLINK_TRADE_RESULT_NOT_PERFORMED
	call SlinkTradePublishDone
	; fallthrough

SlinkTradeResponderRelease::
	; Nothing was mutated, so this wait may close without a host: RELEASE and expiry take the same exit.
	ld bc, SLINK_TRADE_RELEASE_FRAMES
.wait
	call SlinkTradeWaitFrame
	jp c, SlinkTradeResponderExit
	dec bc
	ld a, b
	or c
	jp z, SlinkTradeResponderExit
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

SlinkTradeResponderExit::
	; Reached with SP at the context base from every path (jp/fallthrough, never an extra call frame).
	call SlinkTradeReleaseSnapshot
	call SlinkTradeClose
	ld hl, sp + 9
	bit SLINK_RESP_FLAG_TEXT_OPEN, [hl]
	jr z, .closed
	call CloseText ; the responder owns its text box: no script runs `endtext`
.closed
	add sp, SLINK_TRADE_CONTEXT_SIZE
	ret

SlinkTradeResponderOfferText:
	text "Trade "
	text_ram wStringBuffer1
	text_start
	line "for "
	text_ram wOTPartyMonNicknames
	text "?"
	done
SlinkTradeResponderServiceEnd::

ASSERT @ <= $5300, "the responder service overran its $5000-$52ff slot"
