; SLink companion overlay for pureRGB (docs/purergb/PLAN.md M3, research/s3/overlay_design.md).
;
; A LINKED build, not a binary injection: tools/apply_purergb_overlay.py copies this directory
; to engine/slink/ in the pinned pureRGB checkout, INCLUDEs this file from the end of main.asm
; and pins the "SLink *" ROMX sections to bank $3F in layout.link. Every pret symbol below is
; resolved by rgblink, so nothing here carries an address literal (the vanilla patch's
; trade_defs.inc has no counterpart). The sources assemble with pureRGB's own includes.asm
; (charmap + text macros preincluded by the Makefile), which is why the SLNK/SLT1 protocol
; magics are written as numeric bytes: under the global charmap 'S' would assemble to $92.
;
; The ABI the Lua client consumes (lua/gen1/panel.lua, lua/gen1/trade_overlay.lua) is the
; vanilla patch's: mailbox 'SLNK' ABI 3 (12 bytes, now at wSlinkMailbox in the WRAMX bank-1
; tail), lease 'SLT1' v1 over the first 16 bytes of wSerialPartyMonsPatchList, the same states,
; generations, timings and result codes. Only the addresses moved, and the profile carries them.

DEF SLINK_TRADE_ENABLED EQU 1  ; the trade modules below are always linked; slink.asm advertises them
INCLUDE "engine/slink/slink.asm"
INCLUDE "engine/slink/trade_service.asm"
INCLUDE "engine/slink/native_trade.asm"
INCLUDE "engine/slink/trade_receptionist.asm"
INCLUDE "engine/slink/trade_ui.asm"
INCLUDE "engine/slink/trade_prompt.asm"
INCLUDE "engine/slink/apex_guard.asm"
INCLUDE "engine/slink/slink_home.asm"
INCLUDE "engine/slink/title_band.asm"
INCLUDE "engine/slink/main_menu_version.asm"
