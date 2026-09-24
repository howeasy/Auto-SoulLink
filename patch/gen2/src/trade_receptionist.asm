; The builder changes only the Trade receptionist's object-script pointer.
; Original story gate and Crystal Mobile branch remain reachable in their bank.
IF DEF(_GOLD) || DEF(_SILVER)
DEF SLINK_TRADE_MAP_BANK EQU $5c
ELSE
DEF SLINK_TRADE_MAP_BANK EQU $64
ENDC
; The original map is in another object file; its BANK is only known at link.
ASSERT BANK(LinkReceptionistScript_Trade) == SLINK_TRADE_MAP_BANK
SECTION "SLink Trade Receptionist", ROMX, BANK[SLINK_TRADE_MAP_BANK]
SlinkTradeReceptionistScript::
	checkevent EVENT_GAVE_MYSTERY_EGG_TO_ELM
	iffalse Script_TradeCenterClosed
	opentext
	writetext Text_TradeReceptionistIntro
	yesorno
	iffalse .cancel
IF !DEF(_GOLD) && !DEF(_SILVER)
	special CheckMobileAdapterStatusSpecial
	iffalse .cable
	writetext Text_TradeReceptionistMobile
	special AskMobileOrCable
	iffalse .cancel
	ifequal $1, .mobile
ENDC
.cable
	callasm SlinkTradeEntry
.cancel
	closetext
	end
IF !DEF(_GOLD) && !DEF(_SILVER)
.mobile
	sjump LinkReceptionistScript_Trade.Mobile
ENDC
