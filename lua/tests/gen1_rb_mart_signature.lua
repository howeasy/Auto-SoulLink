local M={}
-- Viridian Mart, per title:
--   R/B     POKE_BALL, ANTIDOTE, PARLYZ_HEAL, BURN_HEAL          (pokered  data/items/marts.asm:4-5)
--   Yellow  POKE_BALL, REPEL, ANTIDOTE, PARLYZ_HEAL, BURN_HEAL   (pokeyellow data/items/marts.asm:5)
-- The ball is index 1 in both, which is what the parcel driver's purchase step keys on.
local INVENTORY = {
    red =    {0x04,0x0B,0x0F,0x0C},
    blue =   {0x04,0x0B,0x0F,0x0C},
    yellow = {0x04,0x14,0x0B,0x0F,0x0C},
}
function M.inventory(title) return INVENTORY[title] or INVENTORY.red end
-- Returns kind, item_id, confirm_index. kind is one of
-- "none" (no Mart display can be live: not in the Mart, script~=2, or no list/text display),
-- "mart-choice" | "mart-item" | "mart-quantity" | "mart-confirm" (source signatures below), or
-- "unknown" (a display is live but the signature is ambiguous: the driver must idle, not act).
-- Signatures: pokered engine/menus/text_box.asm:151-175,213-235,307-335; home/list_menu.asm:29-56,98-99,197-245,322-327.
-- font_loaded is wFontLoaded bit 0: set by DisplayTextIDInit (engine/menus/display_text_id_init.asm:33-34)
-- and cleared by CloseTextDisplay (home/text_script.asm:130-131), so it spans the whole clerk
-- dialogue including every Mart menu (the buy loop never calls ReloadMapSpriteTilePatterns, the
-- only other writer). wListMenuID stays 2 after the Mart closes until the next DisplayTextIDInit,
-- so "none" needs both gates clear.
-- ponytail: after a completed Mart session (list_menu_id 2, font clear) this stays "unknown", so the
-- driver idles into the wrapper's 120000-frame bound instead of re-tapping A; the parcel driver never
-- leaves a session before its terminal, so no retry path is modelled.
-- wCurItem is overwritten per printed price (home/list_menu.asm:417), so item_id comes from the
-- inventory row at menu_index+list_scroll_offset. Sentinels: item_id 0 and confirm_index -1 can never
-- satisfy the parcel module's ==4 / ==0 checks.
function M.mart_menu(r, title)
    local list = M.inventory(title)
    local item,confirm=0,-1
    if r.map~=0x2A or r.mart_script~=2 then return "none",item,confirm end
    if not r.font_loaded then
        if r.list_menu_id~=2 then return "none",item,confirm end
        return "unknown",item,confirm -- retained geometry after a closed Mart is never a live menu.
    end
    local i=r.menu_index
    if type(i)~="number" or i%1~=0 then return "unknown",item,confirm end
    if r.list_menu_id==2 and r.text_box==0x0E and r.menu_y==1 and r.menu_x==1 and r.menu_max==2 and i>=0 and i<=2 then
        return "mart-choice",item,confirm
    elseif r.list_menu_id==2 and r.menu_y==4 and r.menu_x==5 and r.menu_max==2 and i>=0 and i<=2 then
        -- text_box is deliberately not consulted here: live parcel attempt 5 showed wTextBoxID==1
        -- (MESSAGE_BOX) through the item list and quantity prompt on both cartridges.
        if r.menu_watch_oob==1 then
            local s=r.list_scroll_offset
            -- The bound is the list length's: 4 items allow 0..2, Yellow's 5 allow 0..3.
            if type(s)=="number" and s%1==0 and s>=0 and s<=#list-2 then return "mart-item",list[i+s+1] or 0,confirm end
        elseif r.menu_watch_oob==0 and r.menu_exit_method==1 and type(r.quantity)=="number" and r.quantity>=1 and r.quantity<=99 then
            return "mart-quantity",item,confirm
        end
        return "unknown",item,confirm
    elseif r.list_menu_id==2 and r.menu_y==8 and r.menu_x==15 and r.menu_max==1 and (i==0 or i==1) and r.menu_exit_method==0 then
        return "mart-confirm",item,i
    end
    return "unknown",item,confirm
end
return M
