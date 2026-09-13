-- Test-only Red/Blue first lab checkpoint. Read-only WRAM point and ordinary
-- buttons; the caller owns emu.frameadvance and the paired admission handshake.
local M={}
local function idle()return {A=false,B=false,Start=false,Select=false,Up=false,Down=false,Left=false,Right=false}end
local function press(button,frame)
    local buttons=idle();buttons[button]=frame%16<2;return buttons
end
local function walk(point,x,y)
    local buttons=idle()
    if point.x<x then buttons.Right=true
    elseif point.x>x then buttons.Left=true
    elseif point.y<y then buttons.Down=true
    elseif point.y>y then buttons.Up=true end
    return buttons
end
function M.new(expected)
    assert(expected and (expected.player=="a" or expected.player=="b")
        and expected.run_id and expected.rom_sha1 and expected.context_generation and expected.physical_instance,
        "complete owned R/B route identity required")
    local self={last_frame=-1,starter_seen=false,battle_seen=false,loss_seen=false,nickname_declined=false}
    function self.step(handshake,status,point,frame)
        if not handshake then return idle(),"await-pair-handshake" end
        assert(handshake.ready==true and handshake.run_id==expected.run_id
            and handshake.player==expected.player and handshake.rom_sha1==expected.rom_sha1
            and handshake.context_generation==expected.context_generation
            and handshake.physical_instance==expected.physical_instance,
            "stale or foreign paired route handshake")
        assert(status and status.observation_loop and status.context
            and status.context.context_generation==expected.context_generation
            and status.context.physical_instance==expected.physical_instance,
            "R/B route changed admitted context")
        assert(status.host and status.host.owner_id==expected.physical_instance
            and status.host.held==false and status.runtime and status.runtime.connected
            and status.runtime.session_state=="admitted" and not status.runtime.failed,
            "R/B route lost owned free service")
        assert(type(frame)=="number" and frame>self.last_frame,"R/B route frame did not advance")
        self.last_frame=frame
        assert(point and type(point.map)=="number" and type(point.x)=="number" and type(point.y)=="number"
            and type(point.party_count)=="number" and type(point.battle)=="number",
            "complete read-only R/B route point required")
        if point.map==0x26 then
            if point.x<4 and point.y>1 then return walk(point,4,6),"bedroom-row" end
            if point.y>1 then return walk(point,4,1),"bedroom-column" end
            return walk(point,7,1),"bedroom-to-stairs"
        end
        if point.map==0x25 then
            if point.x==7 and point.y<2 then return walk(point,7,2),"house-clear-stairs" end
            if point.x>2 and point.y<=2 then return walk(point,2,2),"house-row" end
            return walk(point,2,7),"house-to-pallet"
        end
        if point.map==0 then
            if point.pallet_script==2 or point.pallet_script==4 or point.npc_moving then
                return idle(),"pallet-script-wait"
            end
            if point.pallet_script==1 or point.pallet_script==3 then
                if point.joy_ignore==0xFC then return press("A",frame),"pallet-oak-dialogue" end
                return idle(),"pallet-script-wait" -- 0xFF masks all buttons during NPC movement.
            end
            assert(point.pallet_script==0,"unexpected Pallet script before lab")
            if point.x<10 and point.y<6 then return walk(point,5,6),"pallet-clear-house" end
            if point.x<10 then return walk(point,10,6),"pallet-row" end
            return walk(point,10,1),"pallet-to-oak"
        end
        assert(point.map==0x28,"R/B first checkpoint left Oak's Lab unexpectedly")
        if point.party_count==0 then
            if point.lab_script==5 then
                if point.joy_ignore==0xFC then
                    return press("A",frame),"lab-oak-choose-mon-speech"
                end
                return idle(),"lab-oak-speech-wait"
            end
            if point.lab_script==6 and point.x==5 and point.y==3 and point.joy_ignore==0 then
                self.lab_text_exit_started=self.lab_text_exit_started or frame
                assert(frame-self.lab_text_exit_started<600,"lab script6 text exit made no bounded progress")
                if frame%16<2 then return press("B",frame),"lab-text-exit" end
                return walk(point,5,4),"lab-text-exit"
            end
            self.lab_text_exit_started=nil
            local target=expected.player=="a"and 8 or 6 -- Bulbasaur A, Charmander B; distinct species.
            if point.y<4 then return walk(point,5,4),"lab-clear-entry" end
            if point.x==target and point.y==4 then
                local buttons=press("A",frame);buttons.Up=true;return buttons,"choose-growl-starter"
            end
            local buttons=walk(point,target,4)
            if frame%16<2 then buttons.A=true end -- advance Oak's dialogue when scripted movement is held.
            return buttons,"lab-to-starter"
        end
        self.starter_seen=true
        if point.battle==0 and not self.nickname_declined then
            if type(point.lab_script)~="number" or point.lab_script<8 then
                return press("B",frame),"decline-nickname"
            end
            self.nickname_declined=true -- script 8 follows AddPartyMon/AskName completion.
        end
        if point.battle~=0 then
            assert(point.opponent==225,"first battle was not lab Rival1")
            self.battle_seen=true
            if point.menu_y==12 and point.menu_x==5 and point.menu_max>=2 then
                assert(point.move2==0x2d and point.move2_pp>0,"Growl unavailable; refuse Struggle/damage")
                if point.menu_index<2 then return press("Down",frame),"select-growl" end
                if point.menu_index==2 then return press("A",frame),"use-growl" end
                return press("Up",frame),"correct-growl-cursor"
            end
            if point.menu_y==14 and point.menu_max==1 then
                if point.menu_x~=9 then return press("Left",frame),"select-fight" end
                return press("A",frame),"open-fight"
            end
            assert(point.menu_y~=12 and point.menu_y~=14,"unknown battle menu; refuse blind A")
            return press("A",frame),"rival-dialogue"
        end
        if point.lab_rival_done then
            assert(self.battle_seen and point.battle_result==1 and point.party_hp>0,
                "lab loss/heal checkpoint differs")
            self.loss_seen=true
            return idle(),"lab-loss-complete"
        end
        if point.x~=5 or point.y<5 then
            if point.y<5 then return walk(point,point.x,5),"lab-clear-ball-row" end
            return walk(point,5,5),"lab-center-row"
        end
        local buttons=idle();buttons.Down=true
        if frame%16<2 then buttons.A=true end
        return buttons,"start-lab-rival"
    end
    return self
end
return M
