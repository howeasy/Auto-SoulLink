; Included at the END of native engine/menus/start_menu.asm, still in bank 4.
; O-28 changes the visible EXIT choice to SLINK; native B/START still close.
SlinkStartMenuEntry:
	call FadeToMenu
	farcall SlinkPanel
	ld a, 6 ; StartMenu.ReturnRedraw owns the matching window/palette restoration.
	ret

SlinkMenuString:
	db "SLINK@"

SlinkMenuDesc:
	db "Partner"
	next "status@"

ASSERT BANK(SlinkStartMenuEntry) == 4
ASSERT BANK(SlinkMenuString) == 4
ASSERT BANK(SlinkMenuDesc) == 4
