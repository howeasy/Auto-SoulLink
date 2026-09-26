; P4.3a / D3: refuse mail, key items, non-tossable items and placeholder IDs.
; Pinned C 7a7881d0 / G+S 656583c9: data/items/{attributes,mail_items,names}.asm
; and constants/item_constants.asm. Native give checks: mon_menu.asm:240-257;
; ItemIsMail: C mail_2.asm:941-945, G/S:922-926; CANT_TOSS: items.asm:494-501.
; Placeholder attributes are permissive, so an attributes-only check is unsafe.
; Tests regenerate/ROM-check all three items packs and compare every input byte.

ASSERT !(DEF(_GOLD) && DEF(_SILVER))
IF DEF(_GOLD) || DEF(_SILVER)
	ASSERT SLINK_SERVICE_BANK == $13
ELSE
	ASSERT SLINK_SERVICE_BANK == $75
ENDC

SECTION "SLink Trade Item Predicate", ROMX, BANK[SLINK_SERVICE_BANK]
SlinkTradeItemAllowed::
	; A = item ID. Carry set = refused; clear = allowed. NONE ($00) is allowed.
	; BC/DE/HL preserved; AF clobbered. No mutation or item stripping.
	; Caller must select SLINK_SERVICE_BANK. Four stack bytes, plus return address.
	push hl
	push de
	ld e, a
	ld d, 0
	ld hl, SlinkTradeAllowedItems
	add hl, de
	ld a, [hl]
	cp 1
	pop de
	pop hl
	ret
SlinkTradeItemAllowedEnd::

; Identical membership at all three pins: 184 allowed IDs including NONE.
; Indexed by the complete byte (not item-1); $ff is always refused.
SlinkTradeAllowedItems::
	db 1,1,1,1,1,1,0,0,1,1,1,1,1,1,1,1 ; $00
	db 1,1,1,1,1,1,1,1,1,0,1,1,1,1,1,1 ; $10
	db 1,1,1,1,1,1,1,1,1,1,1,1,1,0,1,1 ; $20
	db 1,1,0,1,1,1,0,0,0,1,0,0,1,0,1,1 ; $30
	db 1,1,0,0,0,0,0,0,1,1,1,1,1,1,1,1 ; $40
	db 1,1,1,1,1,1,1,1,1,1,0,1,1,1,1,1 ; $50
	db 1,1,1,1,0,1,1,1,1,1,1,1,1,1,1,1 ; $60
	db 1,1,1,0,0,1,1,1,0,1,1,1,1,1,1,0 ; $70
	db 0,0,0,1,1,0,0,0,0,0,1,1,1,0,0,1 ; $80
	db 1,0,1,0,0,0,1,1,1,0,0,0,1,1,0,1 ; $90
	db 1,1,0,1,1,1,1,1,1,1,1,0,1,1,1,0 ; $a0
	db 0,1,0,0,1,0,0,0,0,0,0,0,0,0,0,1 ; $b0
	db 1,1,1,0,1,1,1,1,1,1,1,1,1,1,1,1 ; $c0
	db 1,1,1,1,1,1,1,1,1,1,1,1,0,1,1,1 ; $d0
	db 1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1 ; $e0
	db 1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0 ; $f0
SlinkTradeAllowedItemsEnd::
ASSERT SlinkTradeAllowedItemsEnd - SlinkTradeAllowedItems == 256
