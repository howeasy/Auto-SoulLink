; SLink companion overlay -- Crystal mailbox reservation.
; Card P4.1a (build pipeline), ticket 14, owner ruling O-27 D1
; (docs/gen2/reviews/P4_PLAN_2026-09-23.md section 1, docs/gen2/REVIEW_RECORD.md O-27).
;
; WRAM0 $CFD8-$CFFF (40 bytes) is EMPTY in the clean pokecrystal.map (data/gen2/pokecrystal.map),
; the linker-verified gap right after the "Video" section, whose last symbols wSecondsSince..
; wDaysSince end at $CFD7 (P4_PLAN_2026-09-23.md option A-C). A fixed-address SECTION claims the
; whole span: rgblink refuses to link if any other section is ever placed here (the W1 proof,
; section 1.4), and this stub emits zero ROM bytes -- it is a WRAM reservation only.
;
; Lifecycle (section 1.3): zeroed by Init on power-on/soft reset, NOT cleared by New Game or
; save/continue, never touched by link code. Only SLink code (plus the Lua host through the
; armed write gate) may write this span.
;
; Card P4.1c (patch/gen2/src/slink.asm, Codex) owns the mailbox's contents (beacon/ABI/counter/
; lease bytes); it targets the wSlinkMailbox symbol declared here, so it links unmodified whether
; or not this stub's shape changes later.

SECTION "SLink Mailbox", WRAM0[$CFD8]
wSlinkMailbox::
	ds $CFFF - $CFD8 + 1 ; 40 bytes, the full reserved span
