; SLink companion overlay -- Polished Crystal trade slice 2a: the two bank-$7E special gates.
;
; The Pokecenter 2F receptionists (maps/PokeCenter2F.asm) share ONE flow, DoTradeOrBattle, for the
; trade and the battle receptionist, and run `special Special_WaitForLinkedFriend` and
; `special Special_CheckLinkTimeout` in it. The builder (tools/build_polished_companion.py) re-points
; those two SpecialsPointers entries at the gates below, so no script byte changes (bank $24 has no
; free bytes). The discriminator is wChosenCableClubRoom: Special_SetBitsForLinkTradeRequest stores
; LINK_TRADECENTER - 1 (= 1), Special_SetBitsForBattleRequest stores LINK_COLOSSEUM - 1 (= 2), and it
; survives Special_TryQuickSave. A battle request tail-calls the ORIGINAL special untouched.
;
; The script tests hScriptVar after each special (iffalsefwd), not carry. FarCall_hl runs a special
; from any bank, and Script_special does `farjp Special`, so no register is live across the gate.

ASSERT SLINK_SERVICE_BANK == $7E ; fixed, like the frame and item sections (see trade_frame.asm)
ASSERT LINK_TRADECENTER - 1 == 1
ASSERT LINK_COLOSSEUM - 1 == 2

; The script label that is a bare `endtext` (maps/Route26DayofWeekSiblingsHouse.asm,
; DayOfWeekSiblingsHousePokedexScript.End). Pointing hScriptBank/hScriptPos at it makes the script
; engine close the text box and end the script as soon as the special returns. The builder also
; checks the clean sym + ROM byte $C0 (endtext) at it.
ASSERT BANK(DayOfWeekSiblingsHousePokedexScript.End) == $2D
ASSERT DayOfWeekSiblingsHousePokedexScript.End == $7595

SECTION "SLink Trade Gates", ROMX[$4400], BANK[SLINK_SERVICE_BANK]

; Replaces Special_WaitForLinkedFriend: a trade request skips the cable wait.
SlinkTradeWaitGate::
	ld a, [wChosenCableClubRoom]
	cp LINK_TRADECENTER - 1
	jr nz, .native
	ld a, TRUE
	ldh [hScriptVar], a
	ret
.native
	farjp Special_WaitForLinkedFriend

; Replaces Special_CheckLinkTimeout: a trade request enters the SLink trade service, then ends the script.
SlinkTradeTimeoutGate::
	ld a, [wChosenCableClubRoom]
	cp LINK_TRADECENTER - 1
	jr nz, .native
	call SlinkTradeEntry
	ld a, BANK(DayOfWeekSiblingsHousePokedexScript.End)
	ldh [hScriptBank], a
	ld a, LOW(DayOfWeekSiblingsHousePokedexScript.End)
	ldh [hScriptPos], a
	ld a, HIGH(DayOfWeekSiblingsHousePokedexScript.End)
	ldh [hScriptPos + 1], a
	ret
.native
	farjp Special_CheckLinkTimeout
SlinkTradeGatesCodeEnd::

ASSERT @ <= $4480, "the gates overran their $4400-$447F slot"

; The entry is a 4-byte trampoline (3-byte jp + nop, the old stub's footprint) to the held PROPOSER-ONLY
; service in trade_service.asm (commit disabled). The gate still `call`s it, and the service returns with
; `ret` after balancing its own stack frame.
SECTION "SLink Trade Entry", ROMX[$4480], BANK[SLINK_SERVICE_BANK]
SlinkTradeEntry::
	jp SlinkTradeProposerService
	nop
SlinkTradeGatesEnd::
