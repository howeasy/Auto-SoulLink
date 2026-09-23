-- Normal-input T2 preparation; no writes, savestate loads or game-data staging.
-- pret c75f3523 map.json/layouts/attributes: Route2 gate -> Forest Rick102 (47,45), west sight5.
-- All segments below are independently checked tile-by-tile on BOTH ROMs by test_gen3_routes.
local R = {}
R.paths = {
    tutorial_to_town = {3,1,22,8,24,39,"D23 R2 D8"},
    town_to_north = {3,1,24,39,20,0,"U8 L2 U31 L2"}, -- scene2, tutorial triggers inactive
    route2 = {3,20,8,79,5,52,"U8 R1 U4 L4 U11 R6 U3 L4 U1 L2"},
    gate_arrival = {15,0,7,10,7,9,"U1"},
    gate = {15,0,7,9,7,2,"U7"},
    forest_arrival = {1,0,29,62,29,61,"U1"},
    forest = {1,0,29,61,41,45,"U2 R1 U1 R1 U3 R8 U10 R2"},
}
local dirs = {U="Up",D="Down",L="Left",R="Right"}
local delta = {Up={0,-1},Down={0,1},Left={-1,0},Right={1,0}}

-- Bound even frames advanced inside shared helpers; restore the emulator API on EVERY exit.
function R.with_budget(emulator, frame, max_frames, fn, check)
    local old, start = emulator.frameadvance, frame()
    emulator.frameadvance = function(...)
        assert(frame()-start < max_frames,"PREPARATION frame budget exhausted")
        if check then check() end
        old(...)
        if check then check() end
    end
    local ok, result = pcall(fn)
    emulator.frameadvance = old
    return ok, result
end

-- Frame samples are coalesced, so two reads inside one write frame do not invent observations.
function R.snapshotter(c, io, policy, ram, frame, regs)
    local last, samples = nil, 0
    return function(key)
        local f = frame()
        if f ~= last then samples, last = samples+1, f end
        local party = c.party()
        if not party then return nil, "party unreadable" end
        local target, count = nil, 0
        for _, m in ipairs(party) do if m.key == key then target, count = m, count+1 end end
        local n, active = io.u8(ram.BATTLERS_COUNT_ADDR), {}
        if n < 2 or n > 4 then
            if c.in_battle() then return nil, "invalid battler count" end
        else
            active[1] = io.u16(ram.BATTLER_PARTY_INDEXES_ADDR)
            if n == 4 then active[2] = io.u16(ram.BATTLER_PARTY_INDEXES_ADDR+4) end
        end
        local snap, err = policy:snapshot()
        if not snap then return nil, err end
        local bp = policy:check(snap, "battle_faint")
        local op = policy:check(snap, "overworld")
        local flags, cpu = io.u32(ram.BATTLE_TYPE_ADDR), regs()
        local b = ram.BATTLE_MONS_ADDR
        local bytes = {}
        for i=0,0x57 do bytes[#bytes+1]=string.char(io.u8(b+i)) end
        local clauses = {}
        for _, p in ipairs(c.cp.battle.clauses) do
            local a = p.address+(p.offset or 0)
            local v = p.width==4 and io.u32(a) or p.width==2 and io.u16(a) or io.u8(a)
            clauses[#clauses+1]=string.format("%s=0x%X",p.name,v)
        end
        return {frame=f,samples=samples,in_battle=c.in_battle(),outcome=io.u8(ram.BATTLE_OUTCOME_ADDR),
            is_trainer=(flags & 8)~=0,trainer_id=io.u16(ram.TRAINER_OPPONENT_ADDR),
            battlers_count=n,active_slots=active,party_base=c.party_base(),target_count=count,target=target,
            active_bytes=table.concat(bytes),battle_permit=bp==true,overworld_permit=op==true,
            tuple=string.format("type=0x%X R15=0x%X CPSR=0x%X permits=%s/%s %s",flags,cpu.R15,cpu.CPSR,
                                tostring(bp),tostring(op),table.concat(clauses," "))}
    end
end

function R.enter_trainer(c, T, frame, label, expected, prep)
    local start = frame()
    local function guard()
        assert(frame()-start < prep.max_frames, "PREPARATION frame budget exhausted")
        local p = c.party()
        assert(p and p[1] and p[1].hp>0, "PREPARATION lead fainted")
        local target = c.find(prep.target_key)
        assert(target and target.slot==prep.target_slot and target.hp==prep.target_hp,
               "PREPARATION bench target changed")
        if c.in_battle() then assert(c.battler_slot()==0,"PREPARATION forced bench switch") end
    end
    local function tick(button)
        guard()
        if button then c.G.tap(button,1,0) else c.frames(1) end
    end
    local function await(pred, limit, button)
        for i=1,limit do
            guard()
            if pred() then return true end
            tick(button and i%16==0 and button or nil)
        end
        return false
    end
    local function at(g,n,x,y)
        local a,b=c.G.map(c.cp);local u,v=c.G.pos(c.cp)
        return a==g and b==n and u==x and v==y
    end
    local function quiet()
        return not c.in_battle() and c.on_field() and c.G.pred_ok(c.cp,"field_controls_locked")
            and c.G.pred_ok(c.cp,"script_context_status")
    end
    local function step(dir, flee)
        local x,y=c.G.pos(c.cp); local d=delta[dir]
        local moved=false
        for _=1,60 do
            tick(dir)
            local u,v=c.G.pos(c.cp)
            if u~=x or v~=y then moved=true;break end
        end
        assert(moved,"route blocked going "..dir)
        for _=1,24 do if c.in_battle() then break end;tick() end
        if flee and c.in_battle() then
            local ok,why=c.run_away(label.." incidental")
            assert(ok,"incidental flee: "..tostring(why));guard()
        end
        local u,v=c.G.pos(c.cp)
        assert(u==x+d[1] and v==y+d[2],"unexpected route step destination")
    end
    local function walk(p)
        assert(at(p[1],p[2],p[3],p[4]),"route segment starts on wrong map/tile")
        for d,n in p[7]:gmatch("([UDLR])(%d+)") do
            for _=1,tonumber(n) do step(dirs[d],true) end
        end
        assert(at(p[1],p[2],p[5],p[6]),"route segment ends on wrong map/tile")
        c.log(string.format("PREP_ROUTE map=%d.%d at=(%d,%d)",p[1],p[2],p[5],p[6]))
    end
    local function warp(dir,dest)
        c.SP.warp_to(c.cp,dir,30,dest,label);guard()
        assert(at(dest.group,dest.num,dest.x,dest.y),"wrong warp destination")
    end
    local function lead() return (c.party() or {})[1] end
    local function healthy()
        local m=lead()
        return m and m.hp==m.max_hp and m.status==0
    end
    local function heal()
        c.walk_to_pc(label)
        c.play.follow(c.cp,"pc_to_pokecenter_entrance",label)
        c.play.follow(c.cp,"pokecenter_entrance_to_nurse",label)
        assert(c.face("Up"),"nurse facing failed")
        c.G.tap("A",3,13)
        assert(await(function() return not c.G.pred_ok(c.cp,"field_controls_locked") end,180,"A"),
               "nurse script did not start")
        assert(await(function() return healthy() and quiet() end,2400,"A"),"nurse did not heal/settle")
        c.play.follow(c.cp,"center_heal_spot_to_pc",label)
        c.walk_pc_to_grass(label);guard()
    end
    local function run()
        assert(expected==102,"unsupported preparation trainer")
        assert(at(3,1,T.START[1],T.START[2]),"T2 needs the town fixture")
        local sb1=c.peek("gSaveBlock1Ptr",4)
        local pocket={c.SP.SB1_KEYITEMS_POCKET_OFFSET,c.SP.BAG_KEYITEMS_COUNT}
        local already=T.after_scene(sb1,pocket)
        if not already then assert(T.before_scene(sb1,pocket),"tutorial precondition failed") end
        for _,s in ipairs(T.SEGMENTS) do
            for _=1,s[2] do step(s[1],false) end
            assert(at(3,1,s[3][1],s[3][2]),"tutorial segment mismatch")
        end
        step("Up",false)
        assert(await(function() return quiet() and T.after_scene(c.peek("gSaveBlock1Ptr",4),pocket) end,
                     12000,"A"),"tutorial did not finish with scene2 and TeachyTV")
        assert(at(3,1,T.TRIGGER[1],T.TRIGGER[2]),"tutorial end tile mismatch")
        c.log("PREP_TUTORIAL scene=2 item=366 field=quiet")
        walk(R.paths.tutorial_to_town)
        warp("Down",c.SP.DEST.route1_north)
        c.play.follow(c.cp,"route1_north_to_south_edge",label)
        c.play.follow(c.cp,"route1_south_to_grass_spot",label)
        while lead().level < prep.level_floor do
            guard()
            local m=lead();local move
            for i,id in ipairs(m.moves) do if id==33 and m.pp[i]>0 then move=i-1 end end
            if m.hp*2<m.max_hp or m.status~=0 or not move or m.pp[move+1]<5 then heal() end
            assert(c.hunt(label),"training encounter not reached")
            local rest = false
            for _=1,80 do
                guard()
                local turn=c.await_turn(60,"B")
                if turn=="over" then break end
                assert(turn=="action","training forced party menu or stalled")
                m=lead();move=nil
                for i,id in ipairs(m.moves) do if id==33 and m.pp[i]>0 then move=i-1 end end
                if not move or m.hp*2<m.max_hp or m.status~=0 then
                    local ok,why=c.run_away(label.." training rest")
                    assert(ok,"training rest escape: "..tostring(why))
                    rest=true;break
                end
                local ok,why=c.use_move(move);assert(ok,why)
            end
            assert(not c.in_battle(),"training battle budget exhausted")
            c.play.wait_scene_settled(c.cp,1800);guard()
            if rest then heal() end
        end
        heal() -- always: full HP/status0 before leaving for Rick
        c.SP.return_to_grass_origin(c.cp,label)
        c.play.follow(c.cp,"route1_grass_to_north_edge",label)
        warp("Up",c.SP.DEST.viridian_south)
        walk(R.paths.town_to_north)
        warp("Up",{group=3,num=20,x=8,y=79})
        walk(R.paths.route2)
        -- Both destinations are MB_SOUTH_ARROW_WARP0x65, NOT a non-animated door.
        -- pret field_fadetransition.c:242-276,441-458 only unlocks; step north explicitly.
        warp("Up",{group=15,num=0,x=7,y=10})
        walk(R.paths.gate_arrival)
        walk(R.paths.gate)
        warp("Up",{group=1,num=0,x=29,y=62})
        walk(R.paths.forest_arrival)
        walk(R.paths.forest)
        step("Right",false)
        assert(await(c.in_battle,1800,"A"),"Rick encounter did not start")
        assert(await(function()
            local s=c.battle_window_snapshot(prep.target_key)
            return s and s.battle_permit
        end,1800,"A"),
               "Rick action menu not parked")
        local s=c.battle_window_snapshot(prep.target_key)
        assert(s.is_trainer and s.trainer_id==expected and s.outcome==0 and healthy(),
               "Rick postcondition/full-HP entry failed")
        return true
    end
    local ok, result
    if c.emulator then ok,result=R.with_budget(c.emulator,frame,prep.max_frames,run,guard)
    else ok,result=pcall(run) end -- read-only unit fakes also exercise guard() directly
    if not ok then return false,tostring(result) end
    return result
end
return R
