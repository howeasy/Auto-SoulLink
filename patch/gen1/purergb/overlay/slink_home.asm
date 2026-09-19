; ROM0 pieces of the SLink overlay. Placed by layout.link right after "Home" (the 1382 free
; bytes at $3A9A). Kept to the minimum: the START-menu dispatcher `jp hl`s with the start
; sub-menu bank mapped, so the jump-table row must point at home code; the panel itself
; lives in bank $3F.

SECTION "SLink Home", ROM0

SlinkStartMenuEntry::
	farcall SlinkPanel
	jp RedisplayStartMenu
