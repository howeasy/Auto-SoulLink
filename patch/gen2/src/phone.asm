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
	ld a, [wSlinkMailbox + SLINK_OFS_PHONE_REQUEST]
	and a
	jr z, .withdraw
	ld b, a
	xor a
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
	slink_special_phone_row SpecialCallWhereverYouAre, PHONE_00, SlinkPhoneCallScript
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
	readmem wSlinkMailbox + SLINK_OFS_PHONE_ARMED
	loadmem wSlinkMailbox + SLINK_OFS_PHONE_ARMED, 0
	ifequal SLINK_CALL_FALLEN, .fallen
	ifequal SLINK_CALL_DEAD_ZONE, .dead_zone
	ifequal SLINK_CALL_FIRST_LINK, .first_link
	writetext SlinkPhoneStaticText
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
