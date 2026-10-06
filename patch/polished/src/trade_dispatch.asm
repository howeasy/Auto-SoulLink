; SLink companion overlay -- Polished Crystal trade card D1/D2: the RESPONDER DISPATCHER (port of
; patch/gen2/src/trade_dispatch.asm; docs/polished/TRADE.md sections 10, 12 and 18). INERT: the call from
; SlinkService is in the overlay, but `SlinkTradePromptEntry` below is a bare `ret` stub that never
; touches the lease, so even an accepted frame changes nothing. Production trade stays OFF until the
; responder service replaces that stub and a binder publishes a PROMPT.
;
; WHAT IT IS. SlinkService runs on EVERY patched DelayFrame (the bridge, patch/polished/src/slink.asm).
; This routine decides whether THIS DelayFrame is the idle overworld's own frame wait, the only place
; the responder may open a native prompt. It refuses (returns with NO mutation, DE and the stack
; untouched) unless every guard holds, in this order:
;
;  1. the stack fingerprint -- NINE pinned bytes, everything else on the stack is masked, never compared
;     (Stage B / s10.9 measured the register slots varying run to run). At entry:
;       +0..1  return into SlinkService         +2..3  return into the bridge
;       +4..5  the bridge's saved-bank AF       (SAVED A at +5 = hROMBank at bridge entry)
;       +6..7  saved HL   +8..9 saved BC   +10..11 saved AF
;       +12..  the chain the bridge was called from
;     pinned:  +5      == BANK(NextOverworldFrame)                 saved bank, not the current bank $7E
;              +12/+13 == DelayFrame + 3                           the patched lead-in's own return
;              +14/+15 == NextOverworldFrame.gfx_done + 6          `call z, DelayFrame` return (no DelayFrames link)
;              +24/+25 == HandleMap + $15                          return into HandleMap
;              +26/+27 == OverworldLoop.loop + 9                   return into OverworldLoop
;  2. the engine state: rSVBK & 7 < 2, wScriptMode == 0, wBattleMode == 0, wLinkMode == 0,
;     wGameLogicPaused == 0, hInMenu == 0, hVBlank == 0 (a 0..8 MODE selector in Polished: no
;     VBLANK_NORMAL), wMapStatus == MAPSTATUS_HANDLE, PLAYERSTEP_CONTINUE clear (this frame adds no
;     step vector: no mid-step BG reanchor), wMapEventStatus == MAPEVENTS_ON.
;  3. the lease: SlinkTradeCheckHeader ok, command == PROMPT, generation != ACK (not yet picked up).
;
; Only then: push de / call SlinkTradePromptEntry / pop de / ret. The DelayFrame bridge promises to
; preserve DE; HL, BC and AF are the bridge's own saved registers and the service may clobber them.
;
; STACK. The caller (SlinkService) adds exactly its own 2-byte `call`: no push precedes this routine.
; Refuse path: the sentinel/return plus nothing (`ld hl, sp+n` only reads). Accept path adds `push de`
; and the call into the entry. The depth is measured by tests/unit/test_polished_trade_dispatch.py.
;
; The stack offsets are DEPTH-DEPENDENT: they hold only for a `call SlinkTradeDispatch` made directly
; from SlinkService, with nothing pushed in between (the service must keep the call at its own depth).

ASSERT SLINK_SERVICE_BANK == $7E ; fixed, like the other trade sections
; The assumed engine constants. A renamed or renumbered one is a LINK failure, not a wrong guard.
ASSERT MAPSTATUS_HANDLE == 2
ASSERT MAPEVENTS_ON == 0
ASSERT PLAYERSTEP_CONTINUE_F == 5
; The pinned chain lives in ONE bank: the saved-bank byte at +5 is that bank.
ASSERT BANK(NextOverworldFrame) == BANK(HandleMap) && BANK(HandleMap) == BANK(OverworldLoop.loop)
ASSERT BANK(NextOverworldFrame.gfx_done) == BANK(NextOverworldFrame)

; Fixed, in the verified free interval above the validators (ends 7e:4696): the linker rejects any
; overlap with the other fixed sections, and the builder's span end covers this section.
SECTION "SLink Trade Dispatch", ROMX[$4700], BANK[SLINK_SERVICE_BANK]

SlinkTradeDispatch::
	ld hl, sp + 5
	ld a, [hl]
	cp BANK(NextOverworldFrame)
	ret nz
	ld hl, sp + 12
	ld a, [hli]
	cp LOW(DelayFrame + 3)
	ret nz
	ld a, [hl]
	cp HIGH(DelayFrame + 3)
	ret nz
	ld hl, sp + 14
	ld a, [hli]
	cp LOW(NextOverworldFrame.gfx_done + 6)
	ret nz
	ld a, [hl]
	cp HIGH(NextOverworldFrame.gfx_done + 6)
	ret nz
	ld hl, sp + 24
	ld a, [hli]
	cp LOW(HandleMap + $15)
	ret nz
	ld a, [hli]
	cp HIGH(HandleMap + $15)
	ret nz
	ld a, [hli]
	cp LOW(OverworldLoop.loop + 9)
	ret nz
	ld a, [hl]
	cp HIGH(OverworldLoop.loop + 9)
	ret nz
	ldh a, [rSVBK]
	and 7
	cp 2 ; banks 0 and 1 both map physical bank 1
	ret nc
	ld a, [wScriptMode]
	and a
	ret nz
	ld a, [wBattleMode]
	and a
	ret nz
	ld a, [wLinkMode]
	and a
	ret nz
	ld a, [wGameLogicPaused]
	and a
	ret nz
	ldh a, [hInMenu]
	and a
	ret nz
	ldh a, [hVBlank]
	and a ; Polished's hVBlank is a mode selector 0..8: only mode 0 is the normal frame
	ret nz
	ld a, [wMapStatus]
	cp MAPSTATUS_HANDLE
	ret nz
	; Vanilla opens text only when CheckPlayerState enabled events. Here, after this frame's
	; HandleMapObjects and before its ScrollScreen, CONTINUE clear also means this frame adds no
	; step vector: no mid-step BG reanchor.
	ld a, [wPlayerStepFlags]
	bit PLAYERSTEP_CONTINUE_F, a
	ret nz
	ld a, [wMapEventStatus]
	cp MAPEVENTS_ON
	ret nz
	call SlinkTradeCheckHeader
	ret c
	ld a, [wSlinkMailbox + SLINK_OFS_TRADE_LEASE + SLINK_TRADE_OFS_COMMAND]
	cp SLINK_TRADE_CMD_PROMPT
	ret nz
	ld a, [wSlinkMailbox + SLINK_OFS_TRADE_LEASE + SLINK_TRADE_OFS_GENERATION]
	ld b, a
	ld a, [wSlinkMailbox + SLINK_OFS_TRADE_LEASE + SLINK_TRADE_OFS_ACK]
	cp b
	ret z ; already picked up; never redispatch native menus/evolution
	push de ; the DelayFrame bridge promises to preserve DE
	call SlinkTradePromptEntry
	pop de
	ret
SlinkTradeDispatchCodeEnd::

ASSERT @ <= $4780, "the dispatcher overran its $4700-$477F slot"

; STUB: the responder service (vanilla patch/gen2/src/trade_service.asm :135-209) REPLACES this section's
; body. Until then an accepted PROMPT frame returns at once and, deliberately, does NOT touch the lease
; (no ACK, no DONE, no close): the dispatcher is simply not exercised until a binder publishes a PROMPT,
; and production trade stays off. Do not "complete" this by writing the lease here.
SECTION "SLink Trade Prompt Entry", ROMX[$4780], BANK[SLINK_SERVICE_BANK]
SlinkTradePromptEntry::
	ret
SlinkTradeDispatchEnd::
