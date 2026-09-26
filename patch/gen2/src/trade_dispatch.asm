; Only pick up a partner prompt at the idle overworld's own frame wait.
; Called directly by SlinkService, before its optional SFX tail call.
SECTION "SLink Trade Dispatch", ROMX, BANK[SLINK_SERVICE_BANK]
SlinkTradeDispatch::
	; At this entry: service return, bridge return, saved bank AF, HL, BC,
	; AF, patched DelayFrame return, DelayFrames return, NextOverworldFrame return.
	ld hl, sp + 5
	ld a, [hl]
	cp BANK(NextOverworldFrame)
	ret nz
	ld hl, sp + 12
	ld a, [hli]
	cp LOW(DelayFrame + 3)
	ret nz
	ld a, [hli]
	cp HIGH(DelayFrame + 3)
	ret nz
	ld a, [hli]
	cp LOW(DelayFrames + 3)
	ret nz
	ld a, [hli]
	cp HIGH(DelayFrames + 3)
	ret nz
	ld a, [hli]
	cp LOW(NextOverworldFrame + 9)
	ret nz
	ld a, [hl]
	cp HIGH(NextOverworldFrame + 9)
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
	cp VBLANK_NORMAL
	ret nz
	ld a, [wMapStatus]
	cp MAPSTATUS_HANDLE
	ret nz
	; Vanilla opens text only when CheckPlayerState enabled events. Here, after
	; this frame's HandleMapObjects and before its ScrollScreen, CONTINUE clear
	; also means this frame adds no step vector: no mid-step BG reanchor.
	ld a, [wPlayerStepFlags]
	bit PLAYERSTEP_CONTINUE_F, a
	ret nz
	ld a, [wMapEventStatus]
	cp MAPEVENTS_ON
	ret nz
	call SlinkTradeCheckHeader
	ret c
	ld a, [wSlinkMailbox + SLINK_OFS_TRADE_LEASE + 5]
	cp SLINK_TRADE_CMD_PROMPT
	ret nz
	ld a, [wSlinkMailbox + SLINK_OFS_TRADE_LEASE + 6]
	ld b, a
	ld a, [wSlinkMailbox + SLINK_OFS_TRADE_LEASE + 7]
	cp b
	ret z ; already picked up; never redispatch native menus/evolution
	push de ; the DelayFrame bridge promises to preserve DE
	call SlinkTradePromptEntry
	pop de
	ret
