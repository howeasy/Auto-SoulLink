-- Test-only R/B START-menu save from the lab overworld. Read-only point and ordinary
-- buttons; the caller owns emu.frameadvance and the paired handshake. Geometry (pret pokered):
--   START menu  engine/menus/draw_start_menu.asm:17-38: wTopMenuItemY=2, wTopMenuItemX=11,
--               wMaxMenuItem=6 without the Pokedex (7 with). Rows POKeMON/ITEM/<name>/SAVE/OPTION/EXIT
--               two rows apart from (12,2) (:83-89), so the SAVE glyphs sit at tilemap (12,8) and
--               SAVE is cursor index 3 (home/start_menu.asm:60-74 offsets no-Pokedex indices by one).
--   Save prompt engine/menus/save.asm:150-153,186-194: TWO_OPTION_MENU ($14) at wTopMenuItemY=8,
--               wTopMenuItemX=1, wMaxMenuItem=1, index 0 = YES; the "older file" prompt has the same shape.
--   Witness     SaveGameData (save.asm:290-292) writes wSaveFileStatus=2 before SRAM; the client's
--               save_witness site is SaveMenu.save+3. Any text/menu sets wFontLoaded bit 0 and
--               CloseTextDisplay (home/text_script.asm:105-131) clears it and redraws the map.
local M={}
local function idle()return {A=false,B=false,Start=false,Select=false,Up=false,Down=false,Left=false,Right=false}end
local function tap(button,frame)local b=idle();b[button]=frame%16<2;return b end
function M.new(expected)
    assert(expected and (expected.player=="a" or expected.player=="b")
        and expected.run_id and expected.rom_sha1 and expected.context_generation and expected.physical_instance,
        "complete R/B save identity required")
    local self={last_frame=-1,confirmed=false}
    function self.step(handshake,status,point,frame)
        if not handshake then return idle(),"await-pair-handshake" end
        assert(handshake.ready==true and handshake.run_id==expected.run_id
            and handshake.player==expected.player and handshake.rom_sha1==expected.rom_sha1
            and handshake.context_generation==expected.context_generation
            and handshake.physical_instance==expected.physical_instance,
            "stale or foreign save handshake")
        assert(status and status.observation_loop and status.context
            and status.context.context_generation==expected.context_generation
            and status.context.physical_instance==expected.physical_instance,"save context changed")
        assert(status.host and status.host.owner_id==expected.physical_instance
            and status.host.held==false and status.runtime and status.runtime.connected
            and status.runtime.session_state=="admitted" and not status.runtime.failed,
            "save service not free and owned")
        assert(type(frame)=="number" and frame>self.last_frame,"save frame did not advance")
        self.last_frame=frame
        assert(point and type(point.map)=="number" and type(point.battle)=="number"
            and type(point.joy_ignore)=="number" and type(point.font_loaded)=="boolean"
            and type(point.save_file_status)=="number" and type(point.start_menu_save)=="boolean"
            and type(point.text_box)=="number" and type(point.menu_y)=="number" and type(point.menu_x)=="number"
            and type(point.menu_max)=="number" and type(point.menu_index)=="number",
            "complete read-only save point required")
        assert(point.map==0x28 and point.battle==0,"save route left the lab overworld")
        if point.save_file_status==2 then
            assert(self.confirmed,"save file status changed without a scripted confirmation")
            if point.font_loaded or point.start_menu_save then return idle(),"save-await-close" end
            return idle(),"save-witnessed"
        end
        assert(point.save_file_status==1,"save file status is not the fresh-cartridge 1")
        if not point.font_loaded then
            if point.joy_ignore~=0 then return idle(),"save-overworld-wait" end
            return tap("Start",frame),"save-open-start-menu"
        end
        if point.start_menu_save and point.menu_y==2 and point.menu_x==11 and point.menu_max==6 then
            if point.menu_index<3 then return tap("Down",frame),"save-select-save" end
            if point.menu_index>3 then return tap("Up",frame),"save-select-save" end
            return tap("A",frame),"save-choose-save"
        end
        if point.text_box==0x14 and point.menu_y==8 and point.menu_x==1 and point.menu_max==1 then
            if point.menu_index~=0 then return tap("Up",frame),"save-select-yes" end
            self.confirmed=true
            return tap("A",frame),"save-confirm"
        end
        return idle(),"save-menu-wait"
    end
    return self
end
return M
