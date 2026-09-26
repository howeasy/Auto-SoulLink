; SLink companion overlay -- Gold/Silver mailbox reservation.
; Card P4.1a (build pipeline), ticket 14, owner ruling O-27 D1
; (docs/gen2/reviews/P4_PLAN_2026-09-23.md section 1, docs/gen2/REVIEW_RECORD.md O-27).
;
; WRAM0 $C1D9-$C1FF (39 bytes) is EMPTY in the clean pokegold.map / pokesilver.map (data/gen2/
; pokegold.map, data/gen2/pokesilver.map), the linker-verified gap between "WRAM" (last symbol
; wPCItemsScrollPosition ends at $C1D8) and "GBC Palettes" ($C200). Gold and Silver share this
; layout (both build from the pokegold source tree with no _GOLD/_SILVER branch in ram/*.asm, per
; cx-3569f8d9 item 4), so one stub covers both titles. A fixed-address SECTION claims the whole
; span: rgblink refuses to link if any other section is ever placed here (the W1 proof, section
; 1.4), and this stub emits zero ROM bytes -- it is a WRAM reservation only.
;
; Lifecycle (section 1.3): zeroed by Init on power-on/soft reset, NOT cleared by New Game or
; save/continue, never touched by link code. Only SLink code (plus the Lua host through the
; armed write gate) may write this span.
;
; Card P4.1c (patch/gen2/src/slink.asm, Codex) owns the mailbox's contents (beacon/ABI/counter/
; lease bytes); it targets the wSlinkMailbox symbol declared here, so it links unmodified whether
; or not this stub's shape changes later.

SECTION "SLink Mailbox", WRAM0[$C1D9]
wSlinkMailbox::
	ds $C1FF - $C1D9 + 1 ; 39 bytes, the full reserved span
