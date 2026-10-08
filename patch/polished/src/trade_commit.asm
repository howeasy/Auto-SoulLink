; C5: native staged-record exchange. Built, NOT production-authorized.
; A = outgoing zero-based slot, B = local role (0/1). The caller's ten-byte
; authenticated APPLY context starts immediately above our return address.
; Return 1 = verified not-performed, 0 = native save/readback completed, 2 = hold.
; Bounded rollback: only a last/sole-slot removal failure BEFORE native UI.
; That path changes only wPartyCount: SetStorageBoxPointer.party, Polished
; engine/pc/bills_pc.asm:585-597; ShiftPartySlotToEnd returns without swaps
; when selected == count (615-623). The outgoing record/OT/nick snapshot
; is untouched and is rechecked after the original count is restored.
; POINT OF NO RETURN = first DURABLE store, not the first live party store:
; non-last slot: DoMailSwap -> DoPartySwap's SRAM CopyBytes store, bank 0
; sPartyMon1Mail ($A600), bills_pc.asm:289-296,299-329 (first swap).
; last/sole slot: no mail swap; ForceGameSave -> SaveGameData -> ValidateSave,
; first SRAM sCheckValue1 store (engine/menus/save.asm:55-59,148-169,275-281).
; CopyBytes's RAM record store and the last-slot dec [wPartyCount] precede
; durability. Non-last partial rotations CANNOT be recovered from the one
; outgoing snapshot; they stay result 2 even before their first durable byte.
; Full pre-durable rollback after native UI is deliberately NOT claimed:
; snapshot lifetime through animation/evolution is not proven. No new
; scratch buffer, serial exchange, box allocation or mail shift is used.
; Native UI/save depth and cold-load durability still require enabled live proof.
SECTION "SLink Trade Commit", ROMX[$5300], BANK[SLINK_SERVICE_BANK]

ASSERT EVOLVE_TRADE == 3
ASSERT PARTYMON_STRUCT_LENGTH == 48
ASSERT wPlayerTrademonEnd - wPlayerTrademonSpecies == 53
; 22 explicit local bytes; native call/return frames are additional.
DEF SLINK_TRADE_COMMIT_LOCALS EQU 22
ASSERT SLINK_TRADE_COMMIT_LOCALS <= 24

SlinkTradeCommit::
	push bc
	push de
	push hl
	ld c, a
	ld a, [wLinkMode]
	ld d, a
	ld a, [wForceEvolution]
	ld e, a
	push de
	ld a, [wCurPartyMon]
	ld d, a
	ld a, [wPokemonWithdrawDepositParameter]
	ld e, a
	push de
	ld a, [wCurTradePartyMon]
	ld d, a
	ld a, [wCurOTTradePartyMon]
	ld e, a
	push de
	ld a, [wJumptableIndex]
	ld d, a
	ld a, [wTradeDialog]
	ld e, a
	push de
	ld a, [wStateFlags]
	ld d, a
	ld a, [wSpriteUpdatesEnabled]
	ld e, a
	push de
	ld a, c
	ld d, a ; original slot, never overwritten with a species
	ld a, [wPartyCount]
	ld c, a
	push bc ; role/count
	ldh a, [hVBlank]
	ld e, a
	push de ; slot/VBlank
	ldh a, [rSVBK]
	ld d, a
	ld e, 0
	push de ; SVBK/reserved
	call .Preflight
	ld a, 1
	jp c, .Restore
	call .PrepareDisplay
	; Final checks: no native menu, delay or staging window before removal.
	call SlinkTradeValidateIncomingStaged
	jp c, .Refused
	ld hl, sp + 3
	ld a, [hl]
	call SlinkTradeCheckOwnSlot
	jp c, .Refused
	ld hl, sp + 3
	ld a, [hl]
	call SlinkTradeValidateSnapshot
	jp c, .Refused
	ld hl, sp + 3
	ld a, [hl]
	ld [wCurPartyMon], a
	ld [wCurTradePartyMon], a
	xor a
	ld [wCurOTTradePartyMon], a
	ld [wPokemonWithdrawDepositParameter], a
	ld a, LINK_TRADECENTER
	ld [wLinkMode], a
.Mutation
	farcall RemoveMonFromParty ; Polished rotates party/OT/nick/SRAM mail itself
	ld hl, sp + 4
	ld a, [wPartyCount]
	inc a
	cp [hl]
	jp nz, SlinkTradeCommitRollback
	call DisableSpriteUpdates
	call ClearTileMap
	call LoadFontsBattleExtra
	ld a, CGB_PLAIN
	call GetCGBLayout
	ld hl, sp + 5
	ld a, [hl]
	and a
	jr nz, .Player2
	farcall TradeAnimation
	jr .Append
.Player2
	farcall TradeAnimationPlayer2
.Append
	; Do not trust native UI to preserve scattered staging.
	call SlinkTradeValidateIncomingStaged
	jp c, .Uncertain
	ld b, $81
	ld c, 1
	ld hl, wOTPartyMon1Species
	farcall CopyBetweenPartyAndTemp
	farcall AddTempMonToParty
	jp c, .Uncertain
	ld hl, sp + 4
	ld a, [wPartyCount]
	cp [hl]
	jp nz, .Uncertain
	dec a
	ld [wCurPartyMon], a
	xor a
	ld [wForceEvolution], a ; append nickname comparison is exact
	call .CheckAppend
	jp c, .Uncertain
	ld a, [wOTPartyMon1Form]
	bit MON_IS_EGG_F, a
	jr nz, .Evolved ; retain underlying egg record; never force egg evolution
	ld a, EVOLVE_TRADE
	ld [wForceEvolution], a
	farcall EvolvePokemon
.Evolved
	ld hl, sp + 4
	ld a, [wPartyCount]
	cp [hl]
	jp nz, .Uncertain
	dec a
	ld [wCurPartyMon], a
	call .CheckIdentity
	jp c, .Uncertain
	; Animation/evolution do not restore overworld music in trade link mode.
	call RestartMapMusic
	call ReturnToMapWithSpeechTextbox
	farcall ForceGameSave
	jp c, .Uncertain
	call .CheckSave
	jp c, .Uncertain
	xor a
	jr .Restore
.Refused
	ld a, 1
	jr .Restore
.Uncertain
	; Durable/unsupported partial path: never save it or report a safe refusal.
	call RestartMapMusic
	call ReturnToMapWithSpeechTextbox
	ld a, 2
.Restore
	push af ; maximum explicit locals 24
	call CloseSRAM
	pop af
	pop de
	push af
	ld a, d
	ldh [rSVBK], a
	pop af
	pop de
	push af
	ld a, e
	ldh [hVBlank], a
	pop af
	pop de ; role/count
	pop de
	push af
	ld a, d
	ld [wStateFlags], a
	ld a, e
	ld [wSpriteUpdatesEnabled], a
	pop af
	pop de
	push af
	ld a, d
	ld [wJumptableIndex], a
	ld a, e
	ld [wTradeDialog], a
	pop af
	pop de
	push af
	ld a, d
	ld [wCurTradePartyMon], a
	ld a, e
	ld [wCurOTTradePartyMon], a
	pop af
	pop de
	push af
	ld a, d
	ld [wCurPartyMon], a
	ld a, e
	ld [wPokemonWithdrawDepositParameter], a
	pop af
	pop de
	push af
	ld a, d
	ld [wLinkMode], a
	ld a, e
	ld [wForceEvolution], a
	pop af
	pop hl
	pop de
	pop bc
	ret

.Preflight
	; Our extra CALL adds two bytes: caller context = SP+26.
	ld hl, sp + 7
	ld a, [hl] ; role
	cp 2
	jp nc, .Bad
	ld hl, sp + 31
	cp [hl] ; private role
	jp nz, .Bad
	ldh a, [rSVBK]
	and 7
	cp 2
	jp nc, .Bad
	ldh a, [hVBlank]
	and a
	jp nz, .Bad
	ld a, [wBattleMode]
	and a
	jp nz, .Bad
	ld a, [wLinkMode]
	and a
	jp nz, .Bad
	ld a, [wGameLogicPaused]
	and a
	jp nz, .Bad
	call SlinkTradeCheckSaved
	jp c, .Bad
	call SlinkTradeCheckParty
	jp c, .Bad
	ld hl, sp + 6
	ld a, [wPartyCount]
	cp [hl]
	jp nz, .Bad
	ld hl, sp + 34
	cp [hl] ; private count
	jp nz, .Bad
	ld hl, sp + 26
	call SlinkTradeCheckHeldFrame
	jp c, .Bad
	ld a, [SLINK_TRADE_FRAME + 5]
	cp SLINK_TRADE_CMD_APPLY
	jp nz, .Bad
	ld hl, sp + 5
	ld a, [hl]
	ld hl, sp + 30
	cp [hl] ; private selected slot
	jp nz, .Bad
	ld a, [SLINK_TRADE_FRAME + 9]
	cp [hl]
	jp nz, .Bad
	call SlinkTradeCheckOwnSlot
	jp c, .Bad
	call SlinkTradeValidateIncomingStaged
	jp c, .Bad
	; Refuse mail anywhere in the local party, not merely the outgoing slot.
	ld a, [wPartyCount]
	ld b, a
	ld hl, wPartyMon1Item
.Mail
	ld a, [hl]
	push bc
	call SlinkTradeItemAllowed
	pop bc
	jp c, .Bad
	ld de, PARTYMON_STRUCT_LENGTH
	add hl, de
	dec b
	jr nz, .Mail
	; Validate outgoing display names before the animation sees either one.
	ld hl, sp + 5
	ld a, [hl]
	ld hl, wPartyMonOTs
	call SkipNames
	ld b, SLINK_TRADE_OT_TEXT_LENGTH
	call SlinkTradeValidateText
	jp c, .Bad
	ld hl, sp + 5
	ld a, [hl]
	ld hl, wPartyMonNicknames
	call SkipNames
	ld b, MON_NAME_LENGTH
	call SlinkTradeValidateText
	jp c, .Bad
	ld hl, wPlayerName
	ld b, NAME_LENGTH
	call SlinkTradeValidateText
	jp c, .Bad
	farcall CompareLoadedAndSavedPlayerID
	jp nz, .Bad
	; Native last-alive rule is HP-only (NOT certification of egg/stats policy).
	ld a, [wPartyCount]
	ld b, a
	ld c, 0
.Alive
	ld hl, sp + 5
	ld a, c
	cp [hl]
	jr z, .NextAlive
	ld hl, wPartyMon1HP
	push bc
	call GetPartyLocation
	pop bc
	ld a, [hli]
	or [hl]
	jr nz, .Good
.NextAlive
	inc c
	dec b
	jr nz, .Alive
	ld hl, wOTPartyMon1HP
	ld a, [hli]
	or [hl]
	jr z, .Bad
.Good
	and a
	ret
.Bad
	scf
	ret

.PrepareDisplay
	ld hl, sp + 5
	ld a, [hl]
	ld hl, wPartyMon1
	call GetPartyLocation
	ld de, wPlayerTrademonSpecies
	call .DisplayRecord
	ld hl, wOTPartyMon1
	ld de, wOTTrademonSpecies
	call .DisplayRecord
	ld hl, wPlayerName
	ld de, wPlayerTrademonSenderName
	ld bc, NAME_LENGTH
	rst CopyBytes
	ld hl, wOTPlayerName
	ld de, wOTTrademonSenderName
	ld bc, NAME_LENGTH
	rst CopyBytes
	ld hl, sp + 5
	ld a, [hl]
	ld hl, wPartyMonOTs
	call SkipNames
	ld de, wPlayerTrademonOTName
	ld bc, NAME_LENGTH
	rst CopyBytes
	ld hl, sp + 5
	ld a, [hl]
	ld hl, wPartyMonNicknames
	call SkipNames
	ld de, wPlayerTrademonNickname
	ld bc, MON_NAME_LENGTH
	rst CopyBytes
	ld hl, wOTPartyMonOTs
	ld de, wOTTrademonOTName
	ld bc, NAME_LENGTH
	rst CopyBytes
	ld hl, wOTPartyMonNicknames
	ld de, wOTTrademonNickname
	ld bc, MON_NAME_LENGTH
	rst CopyBytes
	ret
.DisplayRecord
	; HL record, DE native 53-byte buffer. Fill all consumed identity fields.
	push hl
	push de
	ld a, [hl]
	ld [de], a
	ld bc, MON_DVS
	add hl, bc
	ld a, e
	add wPlayerTrademonDVs - wPlayerTrademonSpecies
	ld e, a
	jr nc, .DVs
	inc d
.DVs
	ld bc, 5 ; three DVs plus personality and full form
	rst CopyBytes
	pop de
	pop hl
	push hl
	push de
	ld bc, MON_ID
	add hl, bc
	ld a, e
	add wPlayerTrademonID - wPlayerTrademonSpecies
	ld e, a
	jr nc, .ID
	inc d
.ID
	ld bc, 2
	rst CopyBytes
	xor a
	ld [de], a ; display caught data only; do not modify actual party caught fields
	pop de
	pop hl
	ld bc, MON_FORM
	add hl, bc
	bit MON_IS_EGG_F, [hl]
	ret z
	ld a, EGG
	ld [de], a
	ld a, e
	add wPlayerTrademonForm - wPlayerTrademonSpecies
	ld e, a
	jr nc, .Egg
	inc d
.Egg
	ld a, [de]
	and ~EXTSPECIES_MASK
	ld [de], a
	ret

.CheckAppend
	ld a, [wCurPartyMon]
	ld hl, wPartyMon1
	call GetPartyLocation
	ld de, wOTPartyMon1
	ld b, PARTYMON_STRUCT_LENGTH
	ld c, 0
.Record
	ld a, c
	cp MON_HAPPINESS
	jr nz, .Exact
	ld a, [wOTPartyMon1Form]
	bit MON_IS_EGG_F, a
	jr nz, .Exact
	ld a, [hl]
	cp BASE_HAPPINESS
	jr nz, .BadAppend
	jr .NextByte
.Exact
	ld a, [de]
	cp [hl]
	jr nz, .BadAppend
.NextByte
	inc hl
	inc de
	inc c
	dec b
	jr nz, .Record
	jr .Names
.CheckIdentity
	ld a, [wCurPartyMon]
	call SlinkTradeCheckOwnSlot
	ret c
	ld a, [wCurPartyMon]
	ld hl, wPartyMon1ID
	call GetPartyLocation
	ld de, wOTPartyMon1ID
	ld b, 2
	call .Compare
	ret c
	ld a, [wCurPartyMon]
	ld hl, wPartyMon1DVs
	call GetPartyLocation
	ld de, wOTPartyMon1DVs
	ld b, 4 ; three DVs and immutable personality
	call .Compare
	ret c
.Names
	ld a, [wCurPartyMon]
	ld hl, wPartyMonOTs
	call SkipNames
	ld de, wOTPartyMonOTs
	ld b, NAME_LENGTH
	call .Compare
	ret c
	; Evolution may rename a non-custom nickname; only append compares it exactly.
	ld a, [wForceEvolution]
	cp EVOLVE_TRADE
	jr z, .GoodAppend
	ld a, [wCurPartyMon]
	ld hl, wPartyMonNicknames
	call SkipNames
	ld de, wOTPartyMonNicknames
	ld b, MON_NAME_LENGTH
	jp .Compare
.GoodAppend
	and a
	ret
.BadAppend
	scf
	ret
.Compare
	ld a, [de]
	cp [hl]
	jr nz, .BadAppend
	inc hl
	inc de
	dec b
	jr nz, .Compare
	and a
	ret

.CheckSave
	farcall VerifyChecksum
	jr nz, .BadSave
	farcall VerifyBackupChecksum
	jr nz, .BadSave
	ld a, BANK(sWritingBackup)
	call GetSRAMBank
	ld a, [sWritingBackup]
	and a
	jr nz, .BadSave
	ld a, BANK(sPokemonData)
	call GetSRAMBank
	ld hl, sPokemonData
	ld de, wPokemonData
	ld bc, wPokemonDataEnd - wPokemonData
	call .SavedSpan
	jr c, .BadSave
	ld a, BANK(sBackupPokemonData)
	call GetSRAMBank
	ld hl, sBackupPokemonData
	ld de, wPokemonData
	ld bc, wPokemonDataEnd - wPokemonData
	call .SavedSpan
	jr c, .BadSave
	call CloseSRAM
	and a
	ret
.BadSave
	call CloseSRAM
	scf
	ret
.SavedSpan
	ld a, [de]
	cp [hl]
	jp nz, .BadAppend
	inc hl
	inc de
	dec bc
	ld a, b
	or c
	jr nz, .SavedSpan
	and a
	ret

; Tail-entered with the original service context at SP. No post-commit escape.
SlinkTradeApplyCommit::
	ld hl, sp + 5
	ld b, [hl]
	dec hl
	ld a, [hl]
	call SlinkTradeCommit
	cp 2
	jr c, .Publish
	ld a, 2 ; unknown native return also means uncertain
.Publish
	call SlinkTradePublishDone
	ld hl, sp + 7
	ld a, [hl]
	cp 1
	jr nz, .Hold
	ld hl, sp + 5
	ld a, [hl]
	and a
	jp z, SlinkTradeWaitRelease
	jp SlinkTradeResponderRelease
.Hold
	; No JoyTextDelay, no B gate, no counter. Result 2 ignores RELEASE forever.
	call DelayFrame
	ld hl, sp + 7
	ld a, [hl]
	and a
	jr nz, .Hold
	call SlinkTradeCheckHeader
	jr c, .Hold
	ld hl, sp + 0
	call SlinkTradeCheckHeldFrame
	jr c, .Hold
	ld a, [SLINK_TRADE_FRAME + 5]
	cp SLINK_TRADE_CMD_RELEASE
	jr nz, .Hold
	ld hl, sp + 4
	ld a, [SLINK_TRADE_FRAME + 9]
	cp [hl]
	jr nz, .Hold
	ld hl, sp + 5
	ld a, [hl]
	and a
	jp z, SlinkTradeExit
	jp SlinkTradeResponderExit

SlinkTradeCommitSaveText:
	text "Save before"
	line "this trade?"
	done
; Auditable ROM witness of the compile-time call-site authorization.
SlinkTradeCommitEnabled::
	db SLINK_TRADE_COMMIT_ENABLE
ASSERT SlinkTradeCommitEnabled == $573b, "compile gate witness moved"

SECTION "SLink Trade Commit Rollback", ROMX[$573c], BANK[SLINK_SERVICE_BANK]
SlinkTradeCommitRollback::
	; Enter only immediately after removal, at the original 22-local-byte SP.
	; The native last-slot path has no rotation, OT/nickname or SRAM writes.
	; A non-last abort could already have performed a mail swap: always hold.
	ld hl, sp + 3
	ld a, [hl]
	inc a
	ld hl, sp + 4
	cp [hl]
	jp nz, SlinkTradeCommit.Uncertain
	ld a, [hl]
	ld [wPartyCount], a
	; Re-run the identical preflight in its original no-link context.
	ld hl, sp + 15
	ld a, [hl]
	ld [wLinkMode], a
SlinkTradeCommitRollbackVerify::
	call SlinkTradeCommit.Preflight
	jp c, SlinkTradeCommit.Uncertain
	ld hl, sp + 3
	ld a, [hl]
	call SlinkTradeValidateSnapshot
	jp c, SlinkTradeCommit.Uncertain
SlinkTradeCommitRollbackVerified::
	ld a, 1
	jp SlinkTradeCommit.Restore
SlinkTradeCommitEnd::
ASSERT @ <= $7000, "C5 commit exceeded its fixed bank-$7E reservation"
