; P4.5b/O-29. Native facts: C 7a7881d, G/S 656583c, phone.asm and scripting.asm.
; +32 request is host-owned until ACK; +33 armed is ROM-owned until delivery.
; This service uses no calls/pushes and preserves DE. All paths reach one tail.
ASSERT SLINK_OFS_PHONE_REQUEST == 32 && SLINK_OFS_PHONE_ARMED == 33
DEF SLINK_CALL_FALLEN EQU 1
DEF SLINK_CALL_DEAD_ZONE EQU 2
DEF SLINK_CALL_FIRST_LINK EQU 3
DEF SPECIALCALL_SLINK EQU 9
ASSERT NUM_SPECIALCALLS == 8 && SPECIALCALL_SIZE == 6
ASSERT SLINK_OFS_PHONE_ARMED < SLINK_MAILBOX_SIZE

; PHONE-NAMES (docs/gen2/POST_RC_CARDS.md): lua/gen2/phone.lua stages one 24-byte record in the
; native, never-read wUnusedMapBuffer BEFORE posting the request, cookie last. HandleNewMap clears
; it (home/map.asm ClearUnusedMapBuffer); the host re-stages once while ARMED. Every reader
; validates the whole record first and otherwise keeps the fixed text.
DEF SLINK_PHONE_STAGE EQUS "wUnusedMapBuffer"
DEF SLINK_STAGE_EVENT EQU 0
DEF SLINK_STAGE_CALLER EQU 1   ; caller species
DEF SLINK_STAGE_RECEIVER EQU 2 ; receiver species
DEF SLINK_STAGE_TRAINER EQU 3  ; 7 glyphs + "@"
DEF SLINK_STAGE_NICK EQU 11    ; caller nickname, 10 glyphs + "@"; empty = the species name
DEF SLINK_STAGE_NONCE EQU 22   ; the request's nonce (1..255), == ARMED_NONCE
DEF SLINK_STAGE_COOKIE EQU 23
DEF SLINK_PHONE_COOKIE EQU $a6 ; layout v1
DEF SLINK_CALL_NAMED EQU 3     ; wScriptVar = ARMED + 3 selects the named text
ASSERT wUnusedMapBufferEnd - wUnusedMapBuffer == SLINK_STAGE_COOKIE + 1
; Gen 2 phone-private mailbox tail (free: public 30 + sample 2 + phone 2 = 34 of 39/40 bytes).
DEF SLINK_OFS_PHONE_HEADER EQU 34      ; ROM: ARMED of the SLink call that is ringing, else 0
DEF SLINK_OFS_PHONE_NONCE EQU 35       ; host: the next request's nonce, written before +32
DEF SLINK_OFS_PHONE_ARMED_NONCE EQU 36 ; ROM: that nonce, moved at the ack (0 = a bare post)
ASSERT SLINK_OFS_PHONE_ARMED_NONCE < SLINK_MAILBOX_SIZE

SECTION "SLink Phone Service", ROMX, BANK[SLINK_SERVICE_BANK]
SlinkPhoneService::
	; Physical WRAM bank 1 only, including G/S running on CGB. Select 0 maps 1.
	ldh a, [rWBK]
	and 7
	cp 2
	jp nc, .tail
	; Boot/CONTINUE may load a contaminated saved ID. Native clean tables stop
	; at 8 and have no bounds check. Only a live, valid owned 9 may remain.
	ld a, [wSpecialPhoneCallID]
	cp SPECIALCALL_SLINK
	jr c, .mailbox
	jr nz, .scrub_reserved
	ld a, [wSlinkMailbox + SLINK_OFS_PHONE_ARMED]
	and a
	jr z, .scrub_reserved
	cp SLINK_CALL_FIRST_LINK + 1
	jr nc, .scrub_reserved
	ld a, [wSpecialPhoneCallID + 1]
	and a
	jr z, .mailbox
.scrub_reserved
	xor a
	ld [wSpecialPhoneCallID], a
	ld [wSpecialPhoneCallID + 1], a
.mailbox
	ld a, [wSlinkMailbox + SLINK_OFS_PHONE_ARMED]
	cp SLINK_CALL_FIRST_LINK + 1
	jr c, .armed_valid
	xor a
	ld [wSlinkMailbox + SLINK_OFS_PHONE_ARMED], a
.armed_valid
	and a
	jr nz, .pending
	ld [wSlinkMailbox + SLINK_OFS_PHONE_HEADER], a ; nothing armed: no SLink header
	ld a, [wSlinkMailbox + SLINK_OFS_PHONE_REQUEST]
	and a
	jr z, .withdraw
	ld b, a
	ld a, [wSlinkMailbox + SLINK_OFS_PHONE_NONCE] ; PHONE-NAMES: this request's record identity
	ld [wSlinkMailbox + SLINK_OFS_PHONE_ARMED_NONCE], a
	xor a
	ld [wSlinkMailbox + SLINK_OFS_PHONE_NONCE], a
	ld [wSlinkMailbox + SLINK_OFS_PHONE_REQUEST], a ; ACK invalid requests too
	ld a, b
	cp SLINK_CALL_FIRST_LINK + 1
	jr nc, .withdraw
	ld [wSlinkMailbox + SLINK_OFS_PHONE_ARMED], a
.pending
	ld a, [wScriptRunning]
	and a
	jr nz, .withdraw
	ld a, [wLinkMode]
	and a
	jr nz, .withdraw
	ld a, [wPokegearFlags]
	bit POKEGEAR_PHONE_CARD_F, a
	jr z, .withdraw
	; The script setter writes a word although dispatch reads only its low byte.
	; Preserve foreign/malformed high padding rather than treating it as empty.
	ld a, [wSpecialPhoneCallID]
	and a
	jr nz, .tail
	ld a, [wSpecialPhoneCallID + 1]
	and a
	jr nz, .tail
	ld [wSpecialPhoneCallID + 1], a
	ld a, SPECIALCALL_SLINK
	ld [wSpecialPhoneCallID], a
	jr .tail
.withdraw
	; Native story ids are never erased. ARMED survives withdrawal/overwrite.
	ld a, [wSpecialPhoneCallID]
	cp SPECIALCALL_SLINK
	jr nz, .tail
	ld a, [wSpecialPhoneCallID + 1]
	and a
	jr nz, .tail
	ld [wSpecialPhoneCallID], a
	ld [wSpecialPhoneCallID + 1], a
.tail
IF DEF(SLINK_SFX_ENABLED)
	jp SlinkSfxService
ELSE
	ret
ENDC
SlinkPhoneServiceEnd::

; Keep the native eight rows byte-identical. No native enum/table grows.
MACRO slink_special_phone_row
	dw \1
	db \2
	dba \3
ENDM

SECTION "SLink Special Calls", ROMX, BANK[$24]
SlinkSpecialPhoneCallList::
	slink_special_phone_row SpecialCallOnlyWhenOutside, PHONECONTACT_ELM, ElmPhoneCallerScript
	slink_special_phone_row SpecialCallOnlyWhenOutside, PHONECONTACT_ELM, ElmPhoneCallerScript
	slink_special_phone_row SpecialCallOnlyWhenOutside, PHONECONTACT_ELM, ElmPhoneCallerScript
	slink_special_phone_row SpecialCallOnlyWhenOutside, PHONECONTACT_ELM, ElmPhoneCallerScript
	slink_special_phone_row SpecialCallWhereverYouAre, PHONECONTACT_ELM, ElmPhoneCallerScript
	slink_special_phone_row SpecialCallWhereverYouAre, PHONECONTACT_BIKESHOP, BikeShopPhoneCallerScript
	slink_special_phone_row SpecialCallWhereverYouAre, PHONECONTACT_MOM, MomPhoneLectureScript
	slink_special_phone_row SpecialCallOnlyWhenOutside, PHONECONTACT_ELM, ElmPhoneCallerScript
	slink_special_phone_row SlinkSpecialCallCondition, PHONE_00, SlinkPhoneCallScript
SlinkSpecialPhoneCallListEnd::
ASSERT SlinkSpecialPhoneCallListEnd - SlinkSpecialPhoneCallList == 9 * SPECIALCALL_SIZE

SECTION "SLink Phone Script", ROMX, BANK[SLINK_SERVICE_BANK]
SlinkPhoneCallScript::
	; Usually withdrawn during the native pause before the call. Clear only
	; our exact word if still present; never erase a subsequent native story id.
	readmem wSpecialPhoneCallID
	ifnotequal SPECIALCALL_SLINK, .delivered
	readmem wSpecialPhoneCallID + 1
	ifnotequal 0, .delivered
	specialphonecall SPECIALCALL_NONE
.delivered
	callasm SlinkPhonePrepareCall ; wScriptVar = ARMED, or ARMED + 3 with the names staged
	loadmem wSlinkMailbox + SLINK_OFS_PHONE_ARMED, 0
	loadmem wSlinkMailbox + SLINK_OFS_PHONE_HEADER, 0
	ifequal SLINK_CALL_FALLEN, .fallen
	ifequal SLINK_CALL_DEAD_ZONE, .dead_zone
	ifequal SLINK_CALL_FIRST_LINK, .first_link
	ifequal SLINK_CALL_FALLEN + SLINK_CALL_NAMED, .named_fallen
	ifequal SLINK_CALL_FIRST_LINK + SLINK_CALL_NAMED, .named_first_link
	writetext SlinkPhoneStaticText
	end
.named_fallen
	writetext SlinkPhoneNamedFallenText
	end
.named_first_link
	writetext SlinkPhoneNamedFirstLinkText
	end
.fallen
	writetext SlinkPhoneFallenText
	end
.dead_zone
	writetext SlinkPhoneDeadZoneText
	end
.first_link
	writetext SlinkPhoneFirstLinkText
	end

; Lines fit 18 tiles with PLAYER expanded to its seven-character maximum.
SlinkPhoneFallenText::
	text "…Hello? <PLAYER>?"
	line "It's your partner."
	para "Our link snapped."
	line "Mine didn't make"
	cont "it through…"
	para "…and yours went"
	line "with it. Sorry."
	done

SlinkPhoneDeadZoneText::
	text "<PLAYER>? Can you"
	line "hear me? …kssh…"
	para "The catch here got"
	line "away. This place"
	cont "is a DEAD ZONE."
	para "Don't look back!"
	done

SlinkPhoneFirstLinkText::
	text "Hey, <PLAYER>!"
	line "It's your partner!"
	para "Our first #MON"
	line "are linked. Their"
	cont "souls are one now."
	para "Keep 'em alive,"
	line "OK? Bye-bye!"
	done

SlinkPhoneStaticText::
	text "…kssh… …kssh…"
	line "Nobody's there."
	done

; wStringBuffer5 = the caller's trainer name (7), 3 = the caller's mon (10), 4 = the receiver's
; species (10). Widths are checked with those maxima (test_gen2_companion_abi).
SlinkPhoneNamedFallenText::
	text_ram wStringBuffer5
	text "'s"
	line "@"
	text_ram wStringBuffer3
	text_start
	cont "fainted!"
	para "Your @"
	text_ram wStringBuffer4
	text_start
	line "is gone too!"
	done

SlinkPhoneNamedFirstLinkText::
	text_ram wStringBuffer5
	text "'s"
	line "@"
	text_ram wStringBuffer3
	text_start
	cont "linked with"
	para "your @"
	text_ram wStringBuffer4
	text "."
	line "They're linked!"
	done

; callasm from SlinkPhoneCallScript, before ARMED is cleared. Fallen and first-link calls with a
; valid record copy the names into wStringBuffer3/4/5 and select the named text; anything else
; leaves wScriptVar = ARMED, the fixed text. Dead-zone calls keep their body (the header names).
SlinkPhonePrepareCall:
	call .prepare
	xor a ; a record is single-use: never reused by a later call
	ld [SLINK_PHONE_STAGE + SLINK_STAGE_COOKIE], a
	ret

.prepare
	ld a, [wSlinkMailbox + SLINK_OFS_PHONE_ARMED]
	ld [wScriptVar], a
	cp SLINK_CALL_DEAD_ZONE
	ret z
	call SlinkPhoneCheckRecord
	ret c
	ld a, [SLINK_PHONE_STAGE + SLINK_STAGE_CALLER]
	call .species
	ret c
	ld a, [SLINK_PHONE_STAGE + SLINK_STAGE_RECEIVER]
	call .species
	ret c
	ld [wNamedObjectIndex], a
	call GetPokemonName ; de = wStringBuffer1
	ld hl, wStringBuffer4
	call .copy
	ld de, SLINK_PHONE_STAGE + SLINK_STAGE_NICK
	ld a, [de]
	cp '@'
	jr nz, .caller
	ld a, [SLINK_PHONE_STAGE + SLINK_STAGE_CALLER]
	ld [wNamedObjectIndex], a
	call GetPokemonName
.caller
	ld hl, wStringBuffer3
	call .copy
	ld de, SLINK_PHONE_STAGE + SLINK_STAGE_TRAINER
	ld hl, wStringBuffer5
	call .copy
	ld a, [wScriptVar]
	add SLINK_CALL_NAMED
	ld [wScriptVar], a
	ret

.species
	; carry = not a species 1..251
	and a
	scf
	ret z
	cp NUM_POKEMON + 1
	ccf
	ret

.copy
	; de -> hl through "@"; the record check bounded every source
	ld a, [de]
	inc de
	ld [hli], a
	cp '@'
	jr nz, .copy
	ret

; carry = invalid: cookie, the ARMED request's nonzero nonce, event == ARMED, a non-empty glyph-only
; trainer name and a glyph-only caller nickname, each terminated inside its field.
SlinkPhoneCheckRecord:
	ld a, [SLINK_PHONE_STAGE + SLINK_STAGE_COOKIE]
	cp SLINK_PHONE_COOKIE
	jr nz, .bad
	ld a, [wSlinkMailbox + SLINK_OFS_PHONE_ARMED_NONCE]
	and a
	jr z, .bad
	ld b, a
	ld a, [SLINK_PHONE_STAGE + SLINK_STAGE_NONCE]
	cp b
	jr nz, .bad
	ld a, [wSlinkMailbox + SLINK_OFS_PHONE_ARMED]
	and a
	jr z, .bad
	ld b, a
	ld a, [SLINK_PHONE_STAGE + SLINK_STAGE_EVENT]
	cp b
	jr nz, .bad
	ld a, [SLINK_PHONE_STAGE + SLINK_STAGE_TRAINER]
	cp '@'
	jr z, .bad
	ld hl, SLINK_PHONE_STAGE + SLINK_STAGE_TRAINER
	ld c, SLINK_STAGE_NICK - SLINK_STAGE_TRAINER
	call .name
	ret c
	ld hl, SLINK_PHONE_STAGE + SLINK_STAGE_NICK
	ld c, SLINK_STAGE_NONCE - SLINK_STAGE_NICK
.name
	ld a, [hli]
	cp '@'
	ret z ; nc
	cp $60 ; below the font: a control code or text command
	ret c
	dec c
	jr nz, .name
.bad
	scf
	ret

; The header: GetCallerName's first four bytes (ld a,c / and a / jr z) become `jp
; SlinkPhoneCallerName` + nop (tools/build_gen2_companion.py). Only the SLink special call's
; WrongNumber contact (TRAINER_NONE, PHONE_00) whose script is SlinkPhoneCallScript, while that call
; is ringing (HEADER == ARMED, set by SlinkSpecialCallCondition, cleared on delivery and whenever
; nothing is armed) and with a valid record for it, prints the partner's trainer name (no colon).
; All else is native, e.g. an empty Pokegear row (PHONE_00) under a stale wCallerContact pointer.
; The special-call id cannot gate this: the service withdraws it during the call's native pause.
SlinkPhoneCallerNameService:
	; in: de = the header coord. out: nc = printed; carry = continue natively
	ld a, [wSlinkMailbox + SLINK_OFS_PHONE_ARMED]
	ld b, a
	ld a, [wSlinkMailbox + SLINK_OFS_PHONE_HEADER]
	cp b
	jr nz, .native
	ld a, [wCallerContact + PHONE_CONTACT_SCRIPT2_BANK]
	cp BANK(SlinkPhoneCallScript)
	jr nz, .native
	ld a, [wCallerContact + PHONE_CONTACT_SCRIPT2_ADDR]
	cp LOW(SlinkPhoneCallScript)
	jr nz, .native
	ld a, [wCallerContact + PHONE_CONTACT_SCRIPT2_ADDR + 1]
	cp HIGH(SlinkPhoneCallScript)
	jr nz, .native
	push de
	call SlinkPhoneCheckRecord
	pop hl
	ret c
	ld de, SLINK_PHONE_STAGE + SLINK_STAGE_TRAINER
	call PlaceString
	and a
	ret
.native
	scf
	ret

SECTION "SLink Caller Name", ROMX, BANK[$24]
SlinkSpecialCallCondition:
	; The ninth row's condition (native SpecialCallWhereverYouAre: scf / ret). CheckSpecialPhoneCall
	; runs it right before it starts the call: the SLink header is active for this ARMED call.
	ld a, [wSlinkMailbox + SLINK_OFS_PHONE_ARMED]
	ld [wSlinkMailbox + SLINK_OFS_PHONE_HEADER], a
	scf
	ret

SlinkPhoneCallerName::
	; in: hl = coord, b = contact, c = trainer class (native GetCallerName)
	ld a, c
	or b
	jr nz, .native
	push hl
	push bc ; FarCall returns the callee's bc (home/farcall.asm ReturnFarCall)
	ld d, h
	ld e, l
	ld a, BANK(SlinkPhoneCallerNameService)
	ld hl, SlinkPhoneCallerNameService
	rst FarCall ; keeps f
	pop bc
	pop hl
	ret nc
.native
	ld a, c
	and a
	jp nz, GetCallerName.SlinkTrainer
	jp GetCallerName.NotTrainer
