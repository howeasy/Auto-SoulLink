; P4.3a native commit tail. Caller owns the authenticated, non-reentrant lease,
; has validated its frozen outgoing preimage and incoming OT slot 0, rejects
; mail/illegal items, and has freed its large snapshot before calling here.
; A = outgoing zero-based party slot; B = role (0 proposer, 1 responder).
; Returns A=0 after the native chain returns, A=2 on refusal/uncertain mutation.
; A=0 is NOT a durable host receipt: the host still independently verifies saves.
; No rollback exists after removal. No serial registers or exchanges are used.
;
; Entry requires normal overworld WRAM bank 1, game logic unpaused, a current
; save already established, and an open map speech textbox owned by the caller.
; BC/DE/HL and the listed native control bytes are restored. AF, temporary mon,
; string/animation scratch and evolution scratch are native caller-clobbered.
SECTION "SLink Trade Commit", ROMX, BANK[SLINK_SERVICE_BANK]

SlinkTradeCommit::
	push bc
	push de
	push hl
	ld c, a
	ld a, b
	cp 2
	jr nc, .bad_entry
	ld a, [wPartyCount]
	and a
	jr z, .bad_entry
	cp PARTY_LENGTH + 1
	jr nc, .bad_entry
	cp c
	jr z, .bad_entry
	jr c, .bad_entry
	ld a, [wOTPartyCount]
	cp 1
	jr nz, .bad_entry
	jr .entry
.bad_entry
	pop hl
	pop de
	pop bc
	ld a, 2
	ret

.entry
	; Save pairs without reserving any mailbox/phone or gameplay scratch bytes.
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
	ld a, [wTradeDialog] ; aliases a frame counter used by the native animation
	ld e, a
	push de
	ld a, [wStateFlags]
	ld d, a
	ld a, [wSpriteUpdatesEnabled]
	ld e, a
	push de
	ld a, c
	ld [wCurTradePartyMon], a
	ld [wCurPartyMon], a
	xor a
	ld [wCurOTTradePartyMon], a
	ld a, [wPartyCount]
	ld c, a
	push bc ; original count + lease role, protected across native calls

	call .PrepareAnimation
	call DisableSpriteUpdates
	; The cable path would skip normal mail compaction. We are outside a
	; cable session and the selected mon carries no mail, so use native normal
	; party removal to keep any OTHER party members' mail correctly aligned.
	xor a
	ld [wLinkMode], a
	ld [wPokemonWithdrawDepositParameter], a
	ld a, [wCurTradePartyMon]
	ld [wCurPartyMon], a
	farcall RemoveMonFromPartyOrBox
	pop bc
	push bc
	ld a, [wPartyCount]
	inc a
	cp c
	jp nz, .uncertain

	ld a, LINK_TRADECENTER
	ld [wLinkMode], a
	call ClearTilemap
	call LoadFontsBattleExtra
	ld b, SCGB_DIPLOMA
	call GetSGBLayout
	pop bc
	push bc
	ld a, b
	and a
	jr nz, .responder
	predef TradeAnimation
	jr .append
.responder
	predef TradeAnimationPlayer2

.append
	; AddTempmonToParty uses wCurPartyMon to select the OT and nickname from
	; the incoming staging party, not the outgoing player's former slot.
	xor a
	ld [wCurPartyMon], a
	ld a, [wOTPartySpecies]
	ld [wCurPartySpecies], a
	ld hl, wOTPartyMon1Species
	ld de, wTempMonSpecies
	ld bc, PARTYMON_STRUCT_LENGTH
	call CopyBytes
	predef AddTempmonToParty
	jp c, .uncertain
	pop bc
	push bc
	ld a, [wPartyCount]
	cp c
	jp nz, .uncertain
	dec a
	ld [wCurPartyMon], a
	ld hl, wPartySpecies
	ld b, 0
	ld c, a
	add hl, bc
	ld a, [wOTPartySpecies]
	cp [hl]
	jp nz, .uncertain
	ld a, [wCurPartyMon]
	ld hl, wPartyMon1Species
	call GetPartyLocation
	; Egg list entries are EGG while the struct species is the eventual hatch
	; species. Validate each against its own staged source, never conflate them.
	ld a, [wOTPartyMon1Species]
	cp [hl]
	jp nz, .uncertain
	; Native append intentionally changes happiness / dex flags. Native trade
	; evolution may also consume an evolution item and change species/nickname.
	ld a, TRUE
	ld [wForceEvolution], a
	farcall EvolvePokemon
	pop bc
	push bc
	ld a, [wPartyCount]
	cp c
	jp nz, .uncertain
	farcall SaveAfterLinkTrade
	ld b, 0
	jr .cleanup

.uncertain
	ld b, 2
.cleanup
	; Do not fall through native LinkTrade's serial check-byte loop. Match
	; NPCTrade's map restoration, then return to the caller's script end.
	pop de ; discard protected role/count, leaving the saved caller controls
	push bc ; preserve return status through native redraw/music calls
	call RestartMapMusic
	call ReturnToMapWithSpeechTextbox
	pop bc
	ld a, b
	and a ; retain Z across the following loads/pops for the return status
	pop de
	ld a, d
	ld [wStateFlags], a
	ld a, e
	ld [wSpriteUpdatesEnabled], a
	pop de
	ld a, d
	ld [wJumptableIndex], a
	ld a, e
	ld [wTradeDialog], a
	pop de
	ld a, d
	ld [wCurTradePartyMon], a
	ld a, e
	ld [wCurOTTradePartyMon], a
	pop de
	ld a, d
	ld [wCurPartyMon], a
	ld a, e
	ld [wPokemonWithdrawDepositParameter], a
	pop de
	ld a, d
	ld [wLinkMode], a
	ld a, e
	ld [wForceEvolution], a
	pop hl
	pop de
	pop bc
	ld a, 0
	ret z
	ld a, 2
	ret

.PrepareAnimation:
	; Native LinkTrade buffer preparation: C link.asm:1844-1935,
	; G/S link.asm:1694-1767. These routines consume buffers, not party indexes.
	ld hl, wPlayerName
	ld de, wPlayerTrademonSenderName
	ld bc, NAME_LENGTH
	call CopyBytes
	ld a, [wCurTradePartyMon]
	ld hl, wPartySpecies
	ld b, 0
	ld c, a
	add hl, bc
	ld a, [hl]
	ld [wPlayerTrademonSpecies], a
	ld a, [wCurTradePartyMon]
	ld hl, wPartyMonOTs
	call SkipNames
	ld de, wPlayerTrademonOTName
	ld bc, NAME_LENGTH
	call CopyBytes
	ld hl, wPartyMon1ID
	ld a, [wCurTradePartyMon]
	call GetPartyLocation
	ld de, wPlayerTrademonID
	ld bc, 2
	call CopyBytes
	ld hl, wPartyMon1DVs
	ld a, [wCurTradePartyMon]
	call GetPartyLocation
	ld de, wPlayerTrademonDVs
	ld bc, 2
	call CopyBytes
IF !DEF(_GOLD) && !DEF(_SILVER)
	ld a, [wCurTradePartyMon]
	ld hl, wPartyMon1Species
	call GetPartyLocation
	ld b, h
	ld c, l
	farcall GetCaughtGender
	ld a, c
	ld [wPlayerTrademonCaughtData], a
ENDC
	ld hl, wOTPlayerName
	ld de, wOTTrademonSenderName
	ld bc, NAME_LENGTH
	call CopyBytes
	ld a, [wOTPartySpecies]
	ld [wOTTrademonSpecies], a
	ld hl, wOTPartyMonOTs
	ld de, wOTTrademonOTName
	ld bc, NAME_LENGTH
	call CopyBytes
	ld hl, wOTPartyMon1ID
	ld de, wOTTrademonID
	ld bc, 2
	call CopyBytes
	ld hl, wOTPartyMon1DVs
	ld de, wOTTrademonDVs
	ld bc, 2
	call CopyBytes
IF !DEF(_GOLD) && !DEF(_SILVER)
	ld bc, wOTPartyMon1Species
	farcall GetCaughtGender
	ld a, c
	ld [wOTTrademonCaughtData], a
ENDC
	ret
SlinkTradeCommitEnd::
