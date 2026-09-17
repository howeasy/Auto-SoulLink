-- Test-only Pokemon YELLOW first lab checkpoint: the twin of gen1_rb_ball_gate_inputs.lua.
-- Read-only WRAM point and ordinary buttons; the caller owns emu.frameadvance and the paired
-- admission handshake. Same pure step contract (gen1_scripted_play.lua:137-159): the module is
-- handed a point, never memory, so every screen is classified from the point's WRAM fields
-- (script number + wJoyIgnore + menu geometry) and no press is ever blind. The host owns the
-- only tilemap probes (gen1_scripted_play.lua:64-70, gen1_rb_mart_signature.lua).
--
-- Verified against pret/pokeyellow 0a08515 (E:/Google Drive/SLink/.cache/pret/pokeyellow):
--   Pallet intercept is wYCoord == 0, not R/B's 1        scripts/PalletTown.asm:27-28
--   Pallet scripts 0-9 (4 = PIKACHU_BATTLE, 5 = AFTER)   scripts/PalletTown.asm:11-22
--   wJoyIgnore is a mask of IGNORED buttons; 0 ignores
--     nothing, so the gate is "is PAD_A (bit 0) set?"    engine/joypad.asm:62-74;
--                                                        constants/hardware.inc:95,105
--   $FC = PAD_SELECT|PAD_START|PAD_CTRL_PAD (A/B pass),
--     $FF = PAD_BUTTONS|PAD_CTRL_PAD (all masked)        constants/hardware.inc:96-97;
--                                                        scripts/PalletTown.asm:38-39,55-56
--   the map reload after ANY battle zeroes wJoyIgnore    home/overworld.asm:40-41
--   the end of a simulated-joypad walk zeroes it too     home/overworld.asm:1623-1629
--   so Pallet script 5's two text boxes run at 0 and it
--     only writes $FF once both are done                 scripts/PalletTown.asm:155-169
--     ($FF, not $FC: PAD_BUTTONS|PAD_CTRL_PAD)           scripts/PalletTown.asm:168-169
--   demo battle: wBattleType = BATTLE_TYPE_PIKACHU (4),
--     wCurOpponent = STARTER_PIKACHU ($54), level 5      scripts/PalletTown.asm:143-148
--     BATTLE_TYPE_PIKACHU = 4                            constants/battle_constants.asm:46
--     PIKACHU = $54                                      constants/pokemon_constants.asm:93,204
--   demo battle menu input is ENGINE-SIMULATED           engine/battle/core.asm:2095-2141
--   one-item ball list, and its A is simulated too       engine/battle/core.asm:2305-2317,
--                                                        home/list_menu.asm:62-80
--   no party add / no nickname for type 4                engine/items/item_effects.asm:528-531
--   Oak's Lab is 23 scripts, 0-22 (NOOP = 22)            scripts/OaksLab.asm:12-35
--   the single Eevee ball object sits at x=7, y=3        data/maps/objects/OaksLab.asm:22
--   pressing A on it sets script 8 (no yes/no menu)      scripts/OaksLab.asm:781-806
--   script 9 (OaksLabRivalTakesPokeballScript) shows
--     FIVE text boxes back to back (Text1-5) with
--     wJoyIgnore $FC                                     scripts/OaksLab.asm:218-243,982-994
--   script 11's text shows TWO boxes (OakGivesText,
--     ReceivedText) before it calls AddPartyMon
--     (Pikachu L5), then advances to 12                  scripts/OaksLab.asm:291-297,1017-1036
--   Yellow DOES ask for a nickname here, exactly as R/B:
--     wMonDataLocation is 0                              scripts/OaksLab.asm:1029-1036
--     so _AddPartyMon reaches AskName                    engine/pokemon/add_mon.asm:43-52
--     which is a TWO_OPTION_MENU prompt                  engine/menus/naming_screen.asm:13-31
--   but the party count is written BEFORE the prompt     engine/pokemon/add_mon.asm:12-16
--     so the driver is already out of the party_count==0
--     window when the prompt appears, and the
--     `decline-nickname` B pulse below is what answers
--     it: B picks the second option (NO)                 engine/menus/text_box.asm:283-286,
--                                                        :300-303
--     and the mon keeps the species name GetMonName left
--     in wNameBuffer                                     engine/menus/naming_screen.asm:10-12,
--                                                        :21-23,:44-49
--   DO NOT remove that B branch as "Yellow has no naming
--     screen": the naming screen would open and the
--     Yellow fixture would never reach the rival battle.
--   script 12 fires at wYCoord == 6 (as R/B's 10)        scripts/OaksLab.asm:299-303
--   lab rival is OPP_RIVAL1 = 200 + $19 = 225 with a
--     lone Eevee L5 (Tackle / Tail Whip)                 constants/trainer_constants.asm:1,42;
--                                                        data/trainers/parties.asm:491-493
--   script 14 heals the party and sets wJoyIgnore $FC    scripts/OaksLab.asm:366-399
--   scripts 15/17/18 are live text boxes, 16 is movement scripts/OaksLab.asm:402-495
--   script 18 hands off to 22 (NOOP) -- the terminal     scripts/OaksLab.asm:490-495
--   EVENT_BATTLED_RIVAL_IN_OAKS_LAB = 35 as in R/B       constants/event_constants.asm:19
--   Pikachu's moves are THUNDERSHOCK, GROWL: Growl is
--     slot 2 / id $2d, exactly as R/B's starters         data/pokemon/base_stats/pikachu.asm:13;
--                                                        constants/move_constants.asm:53
-- Inherited from the R/B module (the plan records the .blk layouts of the bedroom, the house,
-- Pallet and the lab as byte-identical): the house/bedroom walk, the lab row-4 approach, and
-- the whole rival-battle block, which is copy-portable move for move.
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
-- Refusals inside the battle carry the point so a live failure receipt is diagnosable.
local DESCRIBE_KEYS={"map","x","y","battle","battle_type","opponent","menu_y","menu_x","menu_max",
    "menu_index","move2","move2_pp","text_box","joy_ignore","font_loaded","lab_script","pallet_script"}
local function describe(point)
    local parts={}
    for _,key in ipairs(DESCRIBE_KEYS) do
        if point[key]~=nil then parts[#parts+1]=key.."="..tostring(point[key]) end
    end
    return " point{"..table.concat(parts,",").."}"
end
-- Every stall guard is the same shape: the first frame in a window is latched, and the window
-- has a bound. `key` names the latch so overlapping guards never share one.
local function bounded(self,key,frame,limit,message,point)
    self[key]=self[key] or frame
    assert(frame-self[key]<limit,message..describe(point))
end
function M.new(expected)
    assert(expected and (expected.player=="a" or expected.player=="b")
        and expected.run_id and expected.rom_sha1 and expected.context_generation and expected.physical_instance,
        "complete owned Yellow route identity required")
    local self={last_frame=-1,starter_seen=false,battle_seen=false,loss_seen=false,demo_seen=false,
        ball_fired=false,nickname_declined=false,pending_growl_pp=nil,awaiting_main_menu=false}
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
            "Yellow route changed admitted context")
        assert(status.host and status.host.owner_id==expected.physical_instance
            and status.host.held==false and status.runtime and status.runtime.connected
            and status.runtime.session_state=="admitted" and not status.runtime.failed,
            "Yellow route lost owned free service")
        assert(type(frame)=="number" and frame>self.last_frame,"Yellow route frame did not advance")
        self.last_frame=frame
        assert(point and type(point.map)=="number" and type(point.x)=="number" and type(point.y)=="number"
            and type(point.party_count)=="number" and type(point.battle)=="number",
            "complete read-only Yellow route point required")
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
            -- Oak's demonstration battle. Not the player's encounter: party stays 0, nothing is
            -- caught for us (item_effects.asm:528-531). Both menus are simulated by the engine,
            -- so A only ever advances a text box here -- and B in the one-item ball list would
            -- cancel the throw, so B is never pressed on this map while a battle is live.
            if point.battle~=0 then
                assert(point.battle_type==4 and point.opponent==0x54 and point.party_count==0,
                    "Pallet battle is not Oak's Pikachu demonstration"..describe(point))
                self.demo_seen=true
                bounded(self,"demo_frame",frame,7200,"Pikachu demonstration battle made no bounded progress",point)
                return press("A",frame),"pallet-pikachu-demo"
            end
            self.demo_frame=nil
            local script=point.pallet_script
            if script==1 or script==3 or script==5 then
                -- Scripts 1/3 set $FC before their DisplayTextID, but script 5 runs on whatever the
                -- post-demonstration map reload left -- EnterMap zeroes wJoyIgnore, and script 5
                -- writes $FF (PAD_BUTTONS|PAD_CTRL_PAD, PalletTown.asm:168-169) only after both of
                -- its text boxes are done -- never $FC at all. Testing for $FC exactly
                -- therefore parked the route at script 5 with joy_ignore 0 forever, so the gate is
                -- the real question the engine asks: is PAD_A (bit 0) in the ignore mask?
                if point.joy_ignore%2==0 then return press("A",frame),"pallet-oak-dialogue" end
                return idle(),"pallet-script-wait" -- 0xFF masks all buttons during NPC movement.
            end
            if script~=0 then
                assert(script==2 or script==4 or script==6 or script==7,
                    "unexpected Pallet script before the lab"..describe(point))
                return idle(),"pallet-script-wait" -- 7 walks us into the lab; nothing to press.
            end
            if point.x<10 and point.y<6 then return walk(point,5,6),"pallet-clear-house" end
            if point.x<10 then return walk(point,10,6),"pallet-row" end
            -- Map-edge intercept guard: the trigger row IS the Route 1 connection row, so once we
            -- stand on it we stop holding Up and let the script fire (it masks the pad itself,
            -- PalletTown.asm:36-39) instead of racing a second step off the map.
            if point.y==0 then
                bounded(self,"edge_frame",frame,900,"Pallet map-edge intercept never fired at y=0",point)
                return idle(),"pallet-await-intercept"
            end
            return walk(point,10,0),"pallet-to-north-exit"
        end
        assert(point.map==0x28,"Yellow first checkpoint left Oak's Lab unexpectedly"..describe(point))
        local script=point.lab_script
        if point.party_count==0 then
            -- Eevee-ball guard: OaksLabEeveePokeBallText re-arms script 8 every time it is read
            -- (OaksLab.asm:781-806), and scripts 8 and 10 leave the player in control for a frame
            -- while still facing the ball tile. Script 9 hides the ball object the moment it runs
            -- (TOGGLE_STARTER_BALL_1 HideObject, OaksLab.asm:218-224), so from 9 onward an A can no
            -- longer reach that text at all -- what it CAN reach is a forced-movement frame, which
            -- is why npc_moving / wSimulatedJoypadStatesIndex still have to be clear.
            -- SEVEN text boxes live in this window, not two: script 9's FIVE boxes (Text1-5,
            -- OaksLab.asm:982-994) and script 11's TWO boxes (OakGivesText, ReceivedText,
            -- OaksLab.asm:1025-1028) before AddPartyMon fires (OaksLab.asm:1036) -- so
            -- party_count is still 0 while it waits. Script 11 is also where the
            -- mask reads 0 rather than $FC: script 10's RLE walk to Oak (OaksLab.asm:262-289) ends
            -- in .doneSimulating, which zeroes wJoyIgnore (home/overworld.asm:1623-1629).
            if self.ball_fired or (type(script)=="number" and script>=8) then
                self.ball_fired=true
                -- The stall window is latched on the DIALOGUE STATE, never on an attempted press.
                -- A wedged text box keeps permitting A forever, so clearing the latch whenever the
                -- driver was allowed to press meant the bound could never be reached (a live run
                -- sat on script 11 for 7201 frames and 901 A pulses without failing). Only an
                -- observed script transition counts as progress; the other exit from this window,
                -- party_count going 0 -> 1, leaves the enclosing party_count==0 branch outright.
                if script~=self.ball_script then
                    self.ball_script=script
                    self.fired_frame=nil
                end
                bounded(self,"fired_frame",frame,3600,"Eevee-ball window made no bounded progress",point)
                if (script==9 or script==11) and point.joy_ignore%2==0
                    and not point.npc_moving and point.simulated_joypad_index==0 then
                    return press("A",frame),
                        script==9 and "rival-takes-eevee-ball" or "receive-pikachu-dialogue"
                end
                return idle(),"eevee-ball-window"
            end
            if script==5 then
                if point.joy_ignore==0xFC then return press("A",frame),"lab-oak-choose-mon-speech" end
                return idle(),"lab-oak-speech-wait"
            end
            if script~=6 and script~=7 then
                assert(type(script)=="number" and script<5,
                    "unexpected Yellow lab script before the Eevee ball"..describe(point))
                return idle(),"lab-entry-wait" -- 0-4: Oak enters, then the scripted walk-in.
            end
            if point.joy_ignore==0xFF or point.npc_moving or point.simulated_joypad_index~=0 then
                return idle(),"lab-scripted-movement" -- script 7 walks us back off row 6.
            end
            if script==6 and point.x==5 and point.y==3 and point.joy_ignore==0 then
                bounded(self,"text_exit_frame",frame,600,"lab script6 text exit made no bounded progress",point)
                if frame%16<2 then return press("B",frame),"lab-text-exit" end
                return walk(point,5,4),"lab-text-exit"
            end
            self.text_exit_frame=nil
            bounded(self,"to_ball_frame",frame,3600,"lab approach to the Eevee ball stalled",point)
            if point.y<4 then return walk(point,5,4),"lab-clear-entry" end
            -- Row 4 only: wYCoord 6 arms OaksLabPlayerDontGoAwayScript and costs a forced walk back.
            if point.y>4 then return walk(point,point.x,4),"lab-return-to-row" end
            if point.x==7 then
                local buttons=press("A",frame);buttons.Up=true;return buttons,"take-eevee-ball"
            end
            return walk(point,7,4),"lab-to-eevee-ball"
        end
        self.starter_seen=true
        self.to_ball_frame=nil
        if point.battle==0 and not self.nickname_declined then
            if type(script)~="number" or script<12 then
                return press("B",frame),"decline-nickname"
            end
            -- Yellow asks for the nickname exactly as R/B does: OaksLabPlayerReceivedMonText
            -- leaves wMonDataLocation 0 (OaksLab.asm:1029-1036), so _AddPartyMon reaches AskName
            -- (add_mon.asm:43-52, naming_screen.asm:13-31) -- but it writes the party count first
            -- (add_mon.asm:12-16), which is why this branch, not the Eevee-ball window, is the one
            -- holding the pad when the prompt opens. The B pulse above therefore does two jobs:
            -- it answers the TWO_OPTION_MENU with NO (B = second option, text_box.asm:283-286,
            -- :300-303, keeping the species name GetMonName left in wNameBuffer,
            -- naming_screen.asm:21-23,:44-49) and it lets script 11's text_asm finish -- both of
            -- its boxes (OakGivesText, ReceivedText) already printed before AddPartyMon was
            -- called (OaksLab.asm:1025-1036); script 12 is the receipt that DisplayTextID
            -- returned (OaksLab.asm:285-297). Deleting it strands the fixture on the name screen.
            self.nickname_declined=true
        end
        if point.battle~=0 then
            assert(point.opponent==225,"first party battle was not lab Rival1"..describe(point))
            self.battle_seen=true
            if self.pending_growl_pp and point.move2_pp<self.pending_growl_pp then
                self.pending_growl_pp=nil
                self.awaiting_main_menu=true
            end
            if self.awaiting_main_menu then
                if point.menu_y==14 and point.menu_max==1 then
                    self.awaiting_main_menu=false
                else
                    return press("B",frame),"rival-turn-text"
                end
            end
            if self.pending_growl_pp then
                assert(frame-self.pending_growl_frame<600,"selected Growl has no accepted PP/action evidence"..describe(point))
                -- ponytail: HandleMenuInput_ runs Delay3 after each cursor placement and drops presses; keep pulsing A
                -- while the move menu still shows index 2. The index decrement (core.asm:2620-2626) precedes validation;
                -- the PP drop is the acceptance oracle. Until then pulse B: the driver never presses B inside the open
                -- move menu (index 2 -> A), and B only advances prompt-gated text (WaitForTextScrollButtonPress takes A|B,
                -- e.g. enemy-first "fell!"/"fainted!" before ExecutePlayerMove, core.asm:418-424) or backs out of nothing.
                if point.menu_y==12 and point.menu_x==5 and point.menu_max>=2 and point.menu_index==2 then
                    return press("A",frame),"use-growl"
                end
                return press("B",frame),"await-growl-acceptance"
            end
            local move_menu=point.menu_y==12 and point.menu_x==5 and point.menu_max>=2
            local main_menu=point.menu_y==14 and point.menu_max==1
            if (point.menu_y==12 or point.menu_y==14) and not move_menu and not main_menu then
                -- ponytail: retained/transient menu geometry between game routines is common (cf. the Mart
                -- signature history); wait bounded instead of crashing the run, but still never blind-A here.
                bounded(self,"unknown_menu_frame",frame,600,"unknown battle menu; refuse blind A",point)
                return idle(),"unknown-battle-menu-wait"
            end
            self.unknown_menu_frame=nil
            if move_menu then
                -- Pikachu L5 knows THUNDERSHOCK, GROWL: slot 2 is Growl ($2d), the same damage-free
                -- loss the R/B starters give, so the lab script's HealParty is what ends the battle.
                assert(point.move2==0x2d and point.move2_pp>0,"Growl unavailable; refuse Struggle/damage"..describe(point))
                if point.menu_index<2 then return press("Down",frame),"select-growl" end
                if point.menu_index==2 then
                    local buttons=press("A",frame)
                    if buttons.A then
                        self.pending_growl_pp=point.move2_pp
                        self.pending_growl_frame=frame
                    end
                    return buttons,"use-growl"
                end
                return press("Up",frame),"correct-growl-cursor"
            end
            if main_menu then
                if point.menu_x~=9 then return press("Left",frame),"select-fight" end
                return press("A",frame),"open-fight"
            end
            return press("A",frame),"rival-dialogue"
        end
        if script==12 then
            if point.y==6 then return press("B",frame),"rival-challenge-dialogue" end
            if point.y<5 then return walk(point,point.x,5),"lab-clear-ball-row" end
            if point.x~=5 then return walk(point,5,5),"lab-center-row" end
            local buttons=idle();buttons.Down=true;return buttons,"start-lab-rival"
        end
        if script==13 or script==14 then
            return idle(),"rival-battle-transition" -- 13 waits on the walk-up, 14 heals in one frame.
        end
        -- Follower guard: script 17 spawns the Pikachu overworld follower
        -- (OaksLab.asm:469-479), which can wedge the player against the lab furniture. From the
        -- rival's exit to the terminal this driver only presses B -- it never walks again.
        if script==15 or script==17 or script==18 then
            if point.npc_moving or point.joy_ignore==0xFF then return idle(),"lab-exit-movement" end
            assert(point.joy_ignore==0xFC,"lab exit dialogue lacks A/B permission"..describe(point))
            return press("B",frame),"lab-exit-dialogue"
        end
        if script==16 then return idle(),"watch-rival-exit" end
        if script==22 then
            assert(self.demo_seen and self.battle_seen and point.lab_rival_done
                and point.battle_result==1 and point.party_hp>0,
                "lab loss/heal/free checkpoint differs"..describe(point))
            self.loss_seen=true
            return idle(),"lab-loss-complete"
        end
        error("unexpected post-starter Yellow lab script before the terminal"..describe(point))
    end
    return self
end
return M
