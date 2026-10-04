; SLink companion overlay -- Polished Crystal v3.2.3 mailbox reservation (P5a).
;
; tools/build_polished_companion.py INCLUDEs this file in place of the one line
; `ds 69 ; it's free real estate` inside Polished's own SECTION "Unused", WRAM0
; (ram/wram0.asm; layout.link places it between "Footprint Queue" and "Misc 1326",
; $C60B-$C64F, docs/polished/HOOKS.md section 5.1). The section keeps its exact size,
; so no other WRAM symbol moves, and it emits zero ROM bytes.
;
; Lifecycle: _Init clears all of WRAM0 on power-on/soft reset (engine/init.asm), and
; unlike vanilla, NewGame's ResetWRAM (wShadowOAM..wMusic, $C100-$CB7D) ALSO clears it.
; Only SLink code (plus the Lua host through the armed write gate) may write this span.

wSlinkMailbox::
	ds 40 ; same 40-byte shape as the vanilla Crystal span (slink_mailbox_crystal.asm)
wSlinkMailboxEnd::
	ds 69 - 40 ; the rest of the published free span, still unused
