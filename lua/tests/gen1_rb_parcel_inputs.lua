-- Pure R/B parcel route. Caller owns frames, observation, and the paired grant.
local M = {}
local function idle() return {A=false,B=false,Start=false,Select=false,Up=false,Down=false,Left=false,Right=false} end
local function tap(key, frame)
    local b=idle(); b[key]=frame%16<2; return b
end
local function move(point, target)
    local b=idle()
    if point.x<target[1] then b.Right=true
    elseif point.x>target[1] then b.Left=true
    elseif point.y<target[2] then b.Down=true
    elseif point.y>target[2] then b.Up=true end
    return b
end
local paths={
    lab_exit={{5,11}},
    pallet_north={{12,11},{9,11},{9,2},{10,2},{10,-1}}, -- (9,1) is a tree; -1/36 drive past the edge until the engine changes map
    route_north={{10,31},{8,31},{8,24},{12,24},{12,22},{9,22},{9,14},{14,14},{14,4},{11,4},{11,-1}},
    viridian_mart={{20,35},{20,30},{19,30},{19,20},{29,20},{29,19}},
    viridian_south={{29,20},{19,20},{19,30},{20,30},{20,36}},
    route_south={{10,4},{14,4},{14,14},{9,14},{9,22},{12,22},{12,24},{8,24},{8,31},{10,31},{10,36}},
    pallet_lab={{10,2},{9,2},{9,12},{12,12},{12,11}},
    lab_oak={{5,11},{5,3}},
}
function M.new(expected)
    assert(expected and (expected.player=="a" or expected.player=="b")
        and expected.run_id and expected.rom_sha1 and expected.context_generation and expected.physical_instance,
        "complete R/B parcel identity required")
    local self={last_frame=-1, segments={}, parcel_seen=false, delivered=false,
        cancel_baseline=nil, cancelled=false, purchase_started=false,
        wild_active=false, delivery_in_progress=false}
    local function follow(name, point)
        local targets=paths[name]
        local index=self.segments[name] or 1
        while targets[index] and point.x==targets[index][1] and point.y==targets[index][2] do index=index+1 end
        self.segments[name]=index
        if not targets[index] then return idle(),name.."-arrival" end
        return move(point,targets[index]),name
    end
    function self.step(handshake,status,point,frame)
        if not handshake then return idle(),"await-pair-handshake" end
        assert(handshake.ready==true and handshake.run_id==expected.run_id
            and handshake.player==expected.player and handshake.rom_sha1==expected.rom_sha1
            and handshake.context_generation==expected.context_generation
            and handshake.physical_instance==expected.physical_instance,
            "stale or foreign parcel handshake")
        assert(status and status.observation_loop and status.context
            and status.context.context_generation==expected.context_generation
            and status.context.physical_instance==expected.physical_instance,
            "parcel context changed")
        assert(status.host and status.host.owner_id==expected.physical_instance
            and status.host.held==false and status.runtime and status.runtime.connected
            and status.runtime.session_state=="admitted" and not status.runtime.failed,
            "parcel service not free and owned")
        assert(type(frame)=="number" and frame>self.last_frame,"parcel frame did not advance")
        self.last_frame=frame
        assert(point and type(point.map)=="number" and type(point.x)=="number"
            and type(point.y)=="number" and type(point.battle)=="number"
            and type(point.ball_count)=="number" and type(point.parcel_count)=="number"
            and type(point.money)=="number" and type(point.got_parcel)=="boolean"
            and type(point.oak_got_parcel)=="boolean" and type(point.menu_kind)=="string",
            "complete read-only parcel point required")
        if point.battle~=0 then
            assert(point.map==0x0C and point.battle==1 and point.battle_type==0
                and type(point.party_hp)=="number" and point.party_hp>0,
                "unexpected trainer, special battle or whiteout")
            self.wild_active=true
            assert(type(point.run_attempts)=="number" and point.run_attempts<8,
                "wild RUN attempt bound exceeded")
            if point.text_box==0x0B then -- BATTLE_MENU_TEMPLATE, normal battle.
                if point.menu_y~=14 or point.menu_max~=1 then
                    return idle(),"unknown-wild-menu"
                end
                if point.menu_x==9 then return tap("Right",frame),"wild-select-right-column" end
                if point.menu_x~=15 then return idle(),"unknown-wild-menu" end
                if point.menu_index==0 then return tap("Down",frame),"wild-select-run" end
                if point.menu_index~=1 then return idle(),"unknown-wild-menu" end
                return tap("A",frame),"wild-attempt-run"
            end
            if point.text_box==nil or point.text_box==0 then
                return idle(),"wild-text-state-unknown"
            end
            return tap("A",frame),"wild-dialogue"
        end
        if self.wild_active then
            assert(point.map==0x0C and point.battle_result==2
                and type(point.party_hp)=="number" and point.party_hp>0,
                "wild battle ended without observed escape")
            self.wild_active=false
        end
        if self.cancel_baseline and not self.cancelled and point.menu_kind~="mart-confirm"
            and point.menu_kind~="unknown" then
            assert(point.ball_count==self.cancel_baseline.balls
                and point.money==self.cancel_baseline.money,
                "cancel changed ball count or money")
            self.cancelled=true
        end
        if self.purchase_started and point.ball_count>self.cancel_baseline.balls then
            assert(point.money<self.cancel_baseline.money,"first ball lacks purchase debit")
            return idle(),"first-ball-readback"
        end
        if point.menu_kind~="none" then
            if point.map~=0x2A or not point.oak_got_parcel then
                return idle(),"unexpected-menu"
            end
            if point.menu_kind=="unknown" then return idle(),"mart-unknown-wait" end
            if point.menu_kind=="mart-choice" and point.menu_index==0 then
                return tap("A",frame),"mart-buy"
            end
            if point.menu_kind=="mart-item" and point.menu_index==0
                and point.item_id==4 then -- POKE_BALL; source item constant.
                return tap("A",frame),"mart-poke-ball"
            end
            if point.menu_kind=="mart-quantity" and point.quantity==1 then
                return tap("A",frame),"mart-one-ball"
            end
            if point.menu_kind=="mart-confirm" and point.confirm_index==0 then
                if not self.cancelled then
                    self.cancel_baseline={balls=point.ball_count,money=point.money}
                    return tap("B",frame),"cancel-first-purchase"
                end
                self.purchase_started=true
                return tap("A",frame),"confirm-first-ball"
            end
            return idle(),"unknown-mart-menu"
        end
        if point.map==0x28 then
            if not point.oak_got_parcel then
                if point.parcel_count>0 then self.delivery_in_progress=true end
                if not self.delivery_in_progress then return follow("lab_exit",point) end
                if point.parcel_count==0 then
                    assert(point.lab_script==15 or point.lab_script==16
                        or point.lab_script==17,
                        "parcel removed outside Oak delivery script")
                    if point.joy_ignore==0xFC then
                        return tap("A",frame),"oak-delivery-dialogue"
                    end
                    return idle(),"oak-delivery-script-wait"
                end
                if point.x==5 and point.y==3 then
                    if point.lab_script==0 and point.joy_ignore==0 then
                        local b=tap("A",frame);b.Up=true;return b,"give-parcel-to-oak"
                    end
                    if point.joy_ignore==0xFC then return tap("A",frame),"oak-parcel-dialogue" end
                    return idle(),"oak-parcel-script-wait"
                end
                return follow("lab_oak",point)
            end
            if not self.delivered then
                assert(self.delivery_in_progress,"Oak parcel event without admitted delivery")
                self.delivered=true
                self.segments={} -- second outbound journey starts at the lab again.
            end
            if point.lab_script~=18 or point.joy_ignore~=0 then
                if point.joy_ignore==0xFC then
                    return tap("A",frame),"oak-post-event-dialogue"
                end
                return idle(),"oak-post-event-script-wait"
            end
            return follow("lab_exit",point)
        end
        if point.map==0 then
            if point.parcel_count>0 and not point.oak_got_parcel then return follow("pallet_lab",point) end
            return follow("pallet_north",point)
        end
        if point.map==0x0C then
            if point.parcel_count>0 and not point.oak_got_parcel then return follow("route_south",point) end
            return follow("route_north",point)
        end
        if point.map==1 then
            if point.parcel_count>0 and not point.oak_got_parcel then return follow("viridian_south",point) end
            return follow("viridian_mart",point)
        end
        if point.map==0x2A then
            if not point.oak_got_parcel then
                if point.got_parcel and point.parcel_count>0 then
                    self.parcel_seen=true
                    return move(point,{3,7}),"leave-with-parcel"
                end
                if point.mart_script==0 and point.y==7
                    and (point.x==3 or point.x==4) and point.joy_ignore==0 then
                    return tap("A",frame),"mart-initial-clerk-dialogue"
                end
                if point.mart_script==1 then
                    assert(type(point.simulated_joypad_index)=="number",
                        "Mart simulated movement index missing")
                end
                if point.mart_script==1 and point.simulated_joypad_index~=0 then
                    return idle(),"mart-auto-walk"
                end
                if point.mart_script==1 and point.simulated_joypad_index==0
                    and point.x==2 and point.y==5 and point.joy_ignore==0 then
                    return tap("A",frame),"mart-parcel-dialogue"
                end
                return idle(),"mart-parcel-wait"
            end
            assert(self.parcel_seen and self.delivered,"purchase before parcel delivery")
            if point.x~=2 or point.y~=5 then return move(point,{2,5}),"mart-clerk-position" end
            if point.facing~="left" then return tap("Left",frame),"face-mart-clerk" end
            return tap("A",frame),"open-mart"
        end
        return idle(),"unknown-map"
    end
    return self
end
return M
