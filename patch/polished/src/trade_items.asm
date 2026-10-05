; SLink companion overlay -- Polished Crystal trade slice 1: the item policy (port of
; patch/gen2/src/trade_items.asm). Nothing calls it yet.
;
; Polished's only native refusal on a held item is mail: ItemIsMail_a (home/header.asm) is
; `cp FIRST_MAIL`, with mail the tail of the item list (FIRST_MAIL = $f5, the $ff sentinel above
; it). The vanilla 184-entry table does NOT apply: its ids mean different items here. The 256-entry
; table is generated from constants/item_constants.asm (tools/gen_polished_trade_items.py).

ASSERT SLINK_SERVICE_BANK == $7E ; fixed at $4280 for the same reason as the frame section

SECTION "SLink Trade Item Predicate", ROMX[$4280], BANK[SLINK_SERVICE_BANK]
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

INCLUDE "engine/slink/trade_items_table.asm"
