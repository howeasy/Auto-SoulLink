; SLink companion overlay -- Polished Crystal v3.2.3 core (P5a) + phone (Stage 1) + panel
; (Stage 2) + native notification sounds: beacon, ABI version, sampled frame counter, the
; Pokegear Phone card's virtual SLink contact, the in-game text panel and the sound service.
; Port of patch/gen2/src/slink.asm; same ABI (patch/gb/slink_abi.inc), caps
; SLINK_CAP_PANEL | SLINK_CAP_SFX | SLINK_CAP_SFX_NOTIFY.
INCLUDE "engine/slink/slink_abi.inc"

; Bank $7E: wholly unused in the clean 3.2.3 ROM (data/polished/free_space.txt) and not named
; in layout.link, so this fixed BANK[] section is placed there by rgblink and nothing else moves.
DEF SLINK_SERVICE_BANK EQU $7E
DEF SLINK_MAILBOX_SIZE EQU 69
ASSERT wSlinkMailbox == $c60b
ASSERT wSlinkMailboxEnd - wSlinkMailbox == SLINK_MAILBOX_SIZE
ASSERT hVBlankCounter == $ff8e
; The audio clear (_InitSound: wChannels..wChannelsEnd) cannot reach the mailbox.
ASSERT wSlinkMailbox + SLINK_MAILBOX_SIZE <= wChannels

; Private sampled-clock state, outside the 14-byte core and 16-byte trade lease.
; EQUS, not EQU: wSlinkMailbox lives in ram.o, so it is only known at link time.
DEF SLINK_LAST_SAMPLE EQUS "wSlinkMailbox + SLINK_PUBLIC_SIZE"
DEF SLINK_SAMPLE_VALID EQUS "wSlinkMailbox + SLINK_PUBLIC_SIZE + 1"
DEF SLINK_SAMPLE_COOKIE EQU $a5
ASSERT SLINK_PUBLIC_SIZE + 2 <= SLINK_MAILBOX_SIZE

; The panel's staged page starts right after the shared core, the shared trade lease and the
; service's two private bytes (patch/polished/src/slink_mailbox.asm lays the span out and names
; it wSlinkPanelText). 34 + 2 lines * (16 glyphs + terminator) = 68 <= 69.
DEF SLINK_OFS_PANEL_TEXT EQU 34

; Save path: Polished assembles every object with -E (export all labels), so the native save
; entry the vanilla trade overlay EXPORTs by edit is already linkable; no source edit needed.
ASSERT BANK(Link_SaveGame) != 0 && BANK(NextOverworldFrame) != 0

; ROM0 $0070-$00FF is free: "High Home" (home/header.asm, layout.link org $005b) ends with
; _hl_ at $006f, and the next scripted section is "Header" at $0100.
SECTION "SLink DelayFrame Bridge", ROM0[$0070]
SlinkDelayFrameBridge::
	; DelayFrame's native 7-byte lead-in, moved here verbatim. It arms the native wait
	; BEFORE servicing, so a VBlank during the service is not erased by rearming the flag
	; afterward. Cost (review cx-4c455434): that VBlank is already serviced when the wait's
	; halt starts, so this DelayFrame sleeps to the NEXT one -- the window between the flag
	; clear and the halt grows from ~10 to ~200 T-cycles (about 0.3% of calls take a frame
	; longer). Order kept on purpose; a live gate is still owed. hDelayFrameLY keeps the entry LY.
	ldh a, [rLY]
	ldh [hDelayFrameLY], a
	xor a ; ld a, FALSE
	ldh [hVBlankOccurred], a
	push af
	push bc
	push hl
	ldh a, [hROMBank]
	push af
	ld a, BANK(SlinkService)
	rst Bankswitch
	call SlinkService
	pop af
	rst Bankswitch
	pop hl
	pop bc
	pop af
	ret
SlinkDelayFrameBridgeEnd::
ASSERT SlinkDelayFrameBridgeEnd <= $0100
; Eight local stack bytes (four two-byte pushes: af, bc, hl and the saved bank in af) plus the two-byte
; return of `call SlinkService`; the service preserves DE.

SECTION "SLink Service", ROMX[$4000], BANK[SLINK_SERVICE_BANK]
SlinkService::
	; Header repair never clears host requests, panel state, holds or lease bytes.
	ld hl, wSlinkMailbox
	ld a, SLINK_BEACON_0
	ld [hli], a
	ld a, SLINK_BEACON_1
	ld [hli], a
	ld a, SLINK_BEACON_2
	ld [hli], a
	ld a, SLINK_BEACON_3
	ld [hli], a
	ld a, SLINK_ABI_VERSION
	ld [hl], a
	; SLINK_CAP_PANEL | SLINK_CAP_SFX | SLINK_CAP_SFX_NOTIFY: the panel (patch/polished/src/panel.asm)
	; paints the Phone-card text page; the sound service below plays the shared semantic codes
	; through the cartridge's own PlaySFX (patch/polished/src/slink_sfx.asm). SLINK_CAP_PHONE stays clear:
	; the Phone card's virtual SLink contact opens the panel, it does not serve the host-driven phone-call
	; extension (SLINK_OFS_PHONE_*). SLINK_CAP_TRADE stays clear although the trade lease services below
	; are built (proposer + responder, commit compile-disabled: SlinkTradeCommitEnabled = 0); production
	; trade is off and nothing here advertises it.
	ld a, SLINK_CAP_PANEL | SLINK_CAP_SFX | SLINK_CAP_SFX_NOTIFY
	ld [wSlinkMailbox + SLINK_OFS_CAPS], a

	; Sample the engine's own clock (VBlank's hVBlankCounter). Unsigned deltas lose whole
	; multiples of 256 if the service is not visited between source increments.
	ldh a, [hVBlankCounter]
	ld b, a
	ld a, [SLINK_SAMPLE_VALID]
	cp SLINK_SAMPLE_COOKIE
	jr z, .sample
	ld a, SLINK_SAMPLE_COOKIE
	ld [SLINK_SAMPLE_VALID], a
	xor a
	ld [wSlinkMailbox + SLINK_OFS_FRAME_COUNTER], a
	ld [wSlinkMailbox + SLINK_OFS_FRAME_COUNTER + 1], a
	jr .remember
.sample
	ld a, [SLINK_LAST_SAMPLE]
	ld c, a
	ld a, b
	sub c
	ld c, a
	ld a, [wSlinkMailbox + SLINK_OFS_FRAME_COUNTER]
	add c
	ld [wSlinkMailbox + SLINK_OFS_FRAME_COUNTER], a
	ld a, [wSlinkMailbox + SLINK_OFS_FRAME_COUNTER + 1]
	adc 0
	ld [wSlinkMailbox + SLINK_OFS_FRAME_COUNTER + 1], a
.remember
	ld a, b
	ld [SLINK_LAST_SAMPLE], a
	; The responder dispatcher (patch/polished/src/trade_dispatch.asm): a plain `call` made at the
	; service's own depth with NOTHING pushed before it -- its stack fingerprint is offsets from this
	; exact depth. It refuses by itself (no mutation, DE preserved) unless this DelayFrame is the idle
	; overworld's frame wait with a PROMPT in the lease, so it is not gated here. B/A are free here.
	call SlinkTradeDispatch
	; One foreground service per DelayFrame, in the same order vanilla uses: the sound service
	; preserves DE, so the bridge's contract is unchanged. `jp`, never `call`, to keep the depth
	; bounded by the bridge.
	jp SlinkSfxService
SlinkServiceEnd::

; ---- The panel (docs/polished/PANEL.md, Stage 2) ----
; Bank $7E, after the service and before the phone bridge: the phone's ROM0 gate switches to this
; bank, runs SlinkPanel and switches back, so the panel's script and strings are readable where
; they link. It calls only ROM0 natives (PrintText 00:0e58, DelayFrame 00:0da8).
INCLUDE "engine/slink/panel.asm"

; ---- Pokegear Phone card: one virtual SLink contact (docs/polished/PHONE_SLOT.md, Stage 1) ----
; The contact is VIRTUAL: no wPhoneList bit, no PhoneContacts row, nothing in the save. The Phone
; card's own list walk (PokegearPhone_GetCellNumberFromE) is told there is one more contact, id
; NUM_PHONE_CONTACTS + 1, which sorts after every native id. Five same-size `call` operand rewrites
; in bank $24 (tools/build_polished_companion.py PHONE_HOOKS) route here; every other id falls
; through to the native routine. Bank $24 calls these with $24 mapped and they jump back into it,
; so they live in ROM0 (the last free ROM0 gap, $3F34-$3FFF; the bridge gap above holds the service).
DEF SLINK_PHONE_CONTACT EQU NUM_PHONE_CONTACTS + 1
ASSERT SLINK_PHONE_CONTACT <= 40 ; a wPhoneList bit no native script can set (flag_array is 5 bytes)
ASSERT BANK(PokegearPhone_GetCellNumberFromE) == BANK(CheckCellNum)
ASSERT BANK(PokegearPhone_GetCellNumberFromE) == BANK(PokegearPhone_CountSetBits)
ASSERT BANK(PokegearPhone_GetCellNumberFromE) == BANK(GetCallerClassAndName)
ASSERT BANK(PokegearPhone_GetCellNumberFromE) == BANK(CheckCanDeletePhoneNumber)
ASSERT BANK(PokegearPhone_GetCellNumberFromE) == BANK(PokegearText_WhomToCall)
ASSERT BANK(PokegearPhone_GetCellNumberFromE) == BANK(PokegearPhone_MakePhoneCall)

SECTION "SLink Phone Bridge", ROM0[$3F34]
SlinkPhone_CountSetBits::
; for `call PokegearPhone_CountSetBits` in PokegearPhone_GetCellNumberFromE: native count + 1
	call PokegearPhone_CountSetBits
	inc a
	ld [wNumSetBits], a
	ret

SlinkPhone_CheckCellNum::
; for `call CheckCellNum` in the same walk: the virtual contact reads as present (nz + carry)
	ld a, c
	cp SLINK_PHONE_CONTACT
	jp nz, CheckCellNum
	or a
	scf
	ret

SlinkPhone_CallerName::
; for `call GetCallerClassAndName` in PokegearPhone_UpdateDisplayList (b = contact, de = tile)
	ld a, b
	cp SLINK_PHONE_CONTACT
	jp nz, GetCallerClassAndName
	ld h, d
	ld l, e
	ld de, SlinkPhoneCallerName
	rst PlaceString
	ret

SlinkPhone_CanDelete::
; for `call CheckCanDeletePhoneNumber` in PokegearPhoneContactSubmenu: c = 0 -> Call/Cancel (Mom style)
	ld a, c
	cp SLINK_PHONE_CONTACT
	jp nz, CheckCanDeletePhoneNumber
	ld c, 0
	ret

SlinkPhone_CallGate::
; for `call GetMapPhoneService` at the top of PokegearPhone_MakePhoneCall: "Call" on SLink opens
; the SLink PANEL (Stage 2: the paged, host-fed text box in bank $7E) and never rings, then
; returns to the list like the native out-of-service path does. wPokegearPhoneCursorPosition and
; wPokegearPhoneScrollPosition are never touched, so the cursor is exactly where the player left
; it; the list is redrawn by the native PokegearText_WhomToCall below.
	ld a, [wPokegearPhoneSelectedPerson]
	cp SLINK_PHONE_CONTACT
	jp nz, GetMapPhoneService
	pop af ; drop the return into PokegearPhone_MakePhoneCall: nothing of the call runs
	ld a, BANK(SlinkPanel)
	rst Bankswitch
	call SlinkPanel
	ld a, BANK(PokegearPhone_MakePhoneCall)
	rst Bankswitch
	ld a, POKEGEARSTATE_PHONEJOYPAD
	ld [wJumptableIndex], a
	ld hl, PokegearText_WhomToCall
	jp PrintText

SlinkPhoneCallerName:
; same shape as data/phone/non_trainer_names.asm (.bill / .elm)
	text  "SLink:"
	next1 "   Soul Link"
	done
SlinkPhoneBridgeEnd::

; ---- native notification sounds: the reset-entry latch + the one foreground service ----------
; Same ABI, same semantic codes, same private hold bytes as patch/gen2/src/sfx.asm; the native
; facts (SFX ids, PlaySFX/CheckSFX, wMusicFade) are Polished's own and each is ASSERTed there.
INCLUDE "engine/slink/slink_sfx.asm"

; TITLE-VERSION: the main-menu version bridge and its 20-byte stamped field.
INCLUDE "engine/slink/version.asm"

; TITLE: the SoulLink wordmark on the title screen (docs/polished/TITLE.md): the ROM0 bridge after the
; main-menu bridge and the band, fixed at 7e:5800.
INCLUDE "engine/slink/title.asm"

; TRADE slice 1 (docs/polished/TRADE.md): the lease-frame primitives and the item policy, called by the
; dispatcher and the proposer/responder services below.
INCLUDE "engine/slink/trade_frame.asm"
INCLUDE "engine/slink/trade_items.asm"

; TRADE slice 2a: the two special gates that re-point SpecialsPointers entries 2 and 3 (builder edit),
; plus SlinkTradeEntry, the 3-byte `jp SlinkTradeProposerService` trampoline the wait gate calls. Trade
; requests skip the cable wait, run the held proposer service and end the script; battle is native.
INCLUDE "engine/slink/trade_gate.asm"

; TRADE card 2a: the outgoing 70-byte snapshot and the incoming-mon validity predicates, called by the
; held proposer and responder services (and the snapshot check by the disabled commit).
INCLUDE "engine/slink/trade_snapshot.asm"
INCLUDE "engine/slink/trade_validate.asm"

; TRADE card D1/D2: the responder dispatcher (called from SlinkService each frame) and
; SlinkTradePromptEntry, the 3-byte `jp SlinkTradeResponderService` trampoline it calls once every guard
; holds. The dispatcher refuses by itself; the responder service owns every lease write.
INCLUDE "engine/slink/trade_dispatch.asm"

; TRADE card C1a: the held PROPOSER-ONLY service (commit disabled), behind the SlinkTradeEntry trampoline.
INCLUDE "engine/slink/trade_service.asm"

; TRADE card C6: the held RESPONDER service (commit disabled) behind the SlinkTradePromptEntry trampoline.
; After the proposer service: it reuses its helpers and the SLINK_TRADE_* constants it defines.
INCLUDE "engine/slink/trade_responder.asm"

; C5 native commit helper is present but default-disabled at both APPLY callers.
INCLUDE "engine/slink/trade_commit.asm"
