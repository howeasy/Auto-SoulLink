; SLink companion overlay -- Polished Crystal v3.2.3 mailbox reservation (P5a).
;
; tools/build_polished_companion.py INCLUDEs this file in place of the one line
; `ds 69 ; it's free real estate` inside Polished's own SECTION "Unused", WRAM0
; (ram/wram0.asm; layout.link places it between "Footprint Queue" and "Misc 1326",
; $C60B-$C64F, docs/polished/HOOKS.md section 5.1). The section keeps its exact size,
; so no other WRAM symbol moves, and it emits zero ROM bytes.
;
; Lifecycle: _Init clears all of WRAM0 on power-on/soft reset (engine/init.asm), and
; unlike vanilla, NewGame's ResetWRAM ALSO clears it: its first ByteFill span is
; [wShadowOAM $C100, wMusic $CB7E), which contains $C60B-$C632 (ResetWRAM is five spans in
; engine/menus/intro_menu.asm; the other four do not touch this region).
; Only SLink code (plus the Lua host through the armed write gate) may write this span.

wSlinkMailbox::
	ds 34 ; patch/gb/slink_abi.inc's 14-byte core (+0..13), the 16-byte trade lease (+14..29)
	       ; and the service's two private sample bytes (+30,+31). Nothing on Polished writes
	       ; the lease or the phone extension, but both offsets are shared ABI, so they stay.
wSlinkPanelText::
	ds 35 ; the panel's staged page (card POL-PANEL): two fixed-stride lines of 16 glyphs,
	       ; each closed by the game's own string terminator, plus one spare byte.
wSlinkMailboxEnd::
