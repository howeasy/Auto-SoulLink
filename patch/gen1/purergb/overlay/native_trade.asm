; Foreground physical trade engine. Ported from patch/gen1/src/native_trade.asm. Caller owns a
; durably committed trade, revalidates both complete parties/identities and stages enemy
; slot 0 before entry. No permanent WRAM: presentation state lives on the caller's stack.
; D returns 0=completed, 1=refused before mutation, 2=uncertain append failure.
; A mirrors D on direct return; Bankswitch preserves D/flags but replaces A and BC.
;
; Home-bank routines are plain `call`s; the four routines that live in other banks
; (InternalClockTradeAnim, TryEvolvingMon, InGameTrade_RestoreScreen, RedrawMapView,
; SaveGameData) go through `farcall`, with the bank resolved by the linker
; (TryEvolvingMon is bank $2C in pureRGB, not vanilla's $0E: the linker, not a constant).

; 191 entries: internal ids $00-$BE (pureRGB has 190 real records; index 0 is never a species).
DEF SLINK_SPECIES_TABLE_LENGTH EQU 191

SECTION "SLink Native Trade", ROMX

SlinkTradeApply::
	; Cheap last-moment geometry/ownership refusal. Full semantic checks, save/ROM
	; admission, exact prepared digest and key collision checks are the caller's
	; prerequisites; this entry alone must never grant admission.
	ld a, [wIsInBattle]
	and a
	jp nz, .refused
	ld a, [wLinkState]
	and a
	jp nz, .refused
	ldh a, [hSerialConnectionStatus]
	cp $ff
	jp nz, .refused
	ld a, [wEnteringCableClub]
	and a
	jp nz, .refused
	ld a, [wPartyCount]
	and a
	jp z, .refused
	cp PARTY_LENGTH + 1
	jp nc, .refused
	ld b, a
	ld a, [wTradingWhichPlayerMon]
	cp b
	jp nc, .refused
	ld e, b
	ld d, 0
	ld hl, wPartySpecies
	add hl, de
	ld a, [hl]
	cp $ff
	jp nz, .refused
	ld a, [wTradingWhichPlayerMon]
	ld e, a
	ld hl, wPartySpecies
	add hl, de
	ld a, [hl]
	push af
	ld a, [wTradingWhichPlayerMon]
	ld hl, wPartyMons
	ld bc, PARTYMON_STRUCT_LENGTH
	call AddNTimes
	pop de
	ld a, [hli]
	cp d
	jp nz, .refused
	push hl
	call .validSpecies
	pop hl
	jp c, .refused
	ld a, [hli]
	or [hl]
	jp z, .refused
	ld a, [wEnemyPartyCount]
	cp 1
	jp nz, .refused
	ld a, [wEnemyPartySpecies + 1]
	cp $ff
	jp nz, .refused
	ld a, [wEnemyPartySpecies]
	ld b, a
	ld a, [wEnemyMons]
	cp b
	jp nz, .refused
	call .validSpecies
	jp c, .refused
	ld a, [wEnemyMons + MON_HP]
	ld b, a
	ld a, [wEnemyMons + MON_HP + 1]
	or b
	jp z, .refused

	; The selection bytes are aliases of wTraded*MonSpecies. Preserve the
	; outgoing slot BEFORE publishing animation metadata to that same storage.
	ld a, [wTradingWhichPlayerMon]
	ld [wWhichPokemon], a

	ld a, [wOptions]
	push af
	ld a, [wStatusFlags5]
	push af
	ld a, [wFontLoaded]
	push af
	ld a, [wForceEvolution]
	push af
	ld a, [wUpdateSpritesEnabled]
	push af
	ldh a, [hAutoBGTransferEnabled]
	push af
	ldh a, [hTileAnimations]
	push af
	ldh a, [hWY]
	push af
	xor a
	ldh [hTileAnimations], a
	call SaveScreenTilesToBuffer2

	; Native cable trade metadata uses each Pokemon's actual OT, not save ID.
	ld a, [wWhichPokemon]
	ld hl, wPartyMonOT
	call SkipFixedLengthTextEntries
	ld de, wTradedPlayerMonOT
	ld bc, NAME_LENGTH
	call CopyData
	ld a, [wWhichPokemon]
	ld hl, wPartyMons
	ld bc, PARTYMON_STRUCT_LENGTH
	call AddNTimes
	ld a, [hl]
	ld [wTradedPlayerMonSpecies], a
	ld bc, MON_OTID
	add hl, bc
	ld a, [hli]
	ld [wTradedPlayerMonOTID], a
	ld a, [hl]
	ld [wTradedPlayerMonOTID + 1], a
	ld hl, wEnemyMonOT
	ld de, wTradedEnemyMonOT
	ld bc, NAME_LENGTH
	call CopyData
	ld a, [wEnemyMons + MON_OTID]
	ld [wTradedEnemyMonOTID], a
	ld a, [wEnemyMons + MON_OTID + 1]
	ld [wTradedEnemyMonOTID + 1], a
	ld a, [wEnemyMons]
	ld [wTradedEnemyMonSpecies], a

	xor a
	ld [wRemoveMonFromBox], a
	call RemovePokemon
	xor a
	ld [wWhichPokemon], a
	ld a, [wEnemyMons]
	ld [wCurPartySpecies], a
	ld hl, wEnemyMons
	ld de, wLoadedMon
	ld bc, PARTYMON_STRUCT_LENGTH
	call CopyData
	call AddEnemyMonToPlayerParty
	; Removal made one free slot. Failure here is uncertain, never normal NACK.
	jp c, .unreachableAppendFailure

	; The same fade/music setup used by native Cable Club trades (engine/link/cable_club.asm).
	ld a, 10
	ld [wAudioFadeOutControl], a
	ld a, BANK(Music_Evolution)
	ld [wAudioSavedROMBank], a
	ld a, MUSIC_EVOLUTION
	ld [wNewSoundID], a
	call PlaySound
	ld c, 100
	call DelayFrames
	call ClearScreen
	call LoadFontTilePatterns
	call LoadHpBarAndStatusTilePatterns
	farcall InternalClockTradeAnim
	ld a, [wPartyCount]
	dec a
	ld [wWhichPokemon], a
	ld a, 1
	ld [wForceEvolution], a
	ld a, LINK_STATE_TRADING
	ld [wLinkState], a
	farcall TryEvolvingMon
	xor a
	ld [wLinkState], a

	; Use the original NPC-trade restoration, preserving current map/object
	; state instead of entering/reinitializing the map after the movie.
	call ClearScreen
	farcall InGameTrade_RestoreScreen
	farcall RedrawMapView
	call UpdateSprites
	call Delay3
	call PlayDefaultMusic
	ld d, 0
	jr .restore
.unreachableAppendFailure
	ld d, 2
.restore
	pop af
	ldh [hWY], a
	pop af
	ldh [hTileAnimations], a
	pop af
	ldh [hAutoBGTransferEnabled], a
	pop af
	ld [wUpdateSpritesEnabled], a
	pop af
	ld [wForceEvolution], a
	pop af
	ld [wFontLoaded], a
	pop af
	ld [wStatusFlags5], a
	pop af
	ld [wOptions], a
	ld a, d
	and a
	ret nz
	; Vanilla saves only party+dex after a Cable Club trade (engine/link/cable_club.asm,
	; "this allows reset into Pokecenter") because its entry save left nothing else to
	; change. This player roamed since consenting, so save everything, after the
	; restores above (SaveMainData records wOptions and hTileAnimations).
	farcall SaveGameData
	xor a
	ld d, a
	ret
.refused
	ld d, 1
	ld a, d
	scf
	ret
.validSpecies
	cp SLINK_SPECIES_TABLE_LENGTH
	jr nc, .invalidSpecies
	ld l, a
	ld h, 0
	ld de, SlinkTradeSpeciesTable
	add hl, de
	ld a, [hl]
	and a
	ret nz
.invalidSpecies
	scf
	ret
SlinkTradeSpeciesTable:
	INCLUDE "engine/slink/species_table.inc"
