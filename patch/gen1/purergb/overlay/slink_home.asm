; ROM0 pieces of the SLink overlay. Placed by layout.link right after "Home" (the 1382 free
; bytes at $3A9A). Kept to the minimum: the START-menu dispatcher `jp hl`s with the start
; sub-menu bank mapped, so the jump-table row must point at home code; the panel itself
; lives in bank $3F.

SECTION "SLink Home", ROM0

SlinkStartMenuEntry::
	farcall SlinkPanel
	jp RedisplayStartMenu

; The two main-thread SFX sites (slink.asm SlinkSfxService). Each is a `jp`/`call` from one
; hook edit (tools/apply_purergb_overlay.py), gates on the request byte so the common case
; costs a load and a branch, and farcalls the service with bc/de/hl saved. The gate reads
; the WRAMX mailbox with whatever WRAM bank is selected: a misread while bank 2 is up
; (pureRGB's palette buffer windows, which contain no call) costs one spurious or one
; missed service call, never a wrong sound -- the service forces bank 1 itself.
;
; DelayFrame's tail: `jr nz, .halt / ret` becomes `jr nz, .halt / jp SlinkDelayFrameTail`,
; so this returns to DelayFrame's caller. Flags are DelayFrame's own `and a` (clobbered
; anyway). The LCD-off path `jp`s into VBlank and never comes here.
SlinkDelayFrameTail::
	ld a, [wSlinkSfxRequest]
	and a
	ret z
	push bc
	push de
	push hl
	farcall SlinkSfxService
	pop hl
	pop de
	pop bc
	ret

; Joypad: `homecall _Joypad / ret` becomes `homecall _Joypad / call SlinkJoypadSite / ret`,
; after Joypad's own `pop af`; callers read HRAM, never a register, so a and the flags are
; free here and _Joypad clobbers b/d/e itself.
SlinkJoypadSite::
	ld a, [wSlinkSfxRequest]
	and a
	ret z
	push bc
	push de
	push hl
	farcall SlinkSfxService
	pop hl
	pop de
	pop bc
	ret
