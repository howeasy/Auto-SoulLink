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

-- pret c75f3523: species_info.h Squirtle GROWTH_MEDIUM_SLOW; experience_tables.h
-- EXP_MEDIUM_SLOW; wild_encounters.json Route1/2 minimum yield is Pidgey2: 55*2/7=15
-- (battle_script_commands.c:3166). Lv6=179, Lv9=419, Lv13=1261: <=73 / <=57 wins.
-- Engineering allowance, NOT a pret timing fact: 2 encounters/win *6000 frames plus
-- 12000 for a nurse round trip, and 30000 for tutorial/final route. LG <=1,782,000.
function R.preparation_budget(mon, floor)
    assert(floor==13,"preparation budget is sized for level13")
    local function exp(n) return (6*n*n*n)//5 - 15*n*n + 100*n - 140 end
    assert(mon.level>=6,"preparation needs the committed level6+ Squirtle fixture")
    local current = mon.experience or exp(mon.level)
    local wins = math.ceil(math.max(0,exp(floor)-current)/15)
    return 30000 + wins*24000
end

-- The SAME playlib object is closed over by SP's follow/hunt/nurse helpers. Scope its
-- incidental policy to preparation, restoring on success AND errors before the Rick fight.
-- LG's captured trace (seq371/384/410) entered the second transit battle at8/25 then5/25;
-- the inherited FIGHT policy had no health gate. Transit now always RUNs, even at full HP.
function R.with_incidental_escape(c, label, fn)
    local old = c.play.fight_through
    c.play.fight_through = function()
        c.log("PREP_ESCAPE incidental")
        local ok, why = c.run_away(label.." incidental")
        assert(ok,"incidental flee: "..tostring(why))
        return true
    end
    local ok, result = pcall(fn)
    c.play.fight_through = old
    return ok, result
end

local function rest_needed(m)
    -- In battle, RUN at half HP (minimum12). LG's observed normal hits were3 and crit8;
    -- starting another fight at8 was unsafe. A 75% IN-BATTLE cutoff would also prevent a
    -- healthy Lv6 from finishing an ordinary four-hit Pidgey3 battle (23->20->17->14).
    -- This reserve is not an RNG guarantee; the per-frame lead/bench guards stay mandatory.
    return m.hp<=math.max(12,math.ceil(m.max_hp/2)) or m.status~=0
end

local function heal_before_hunt(m)
    -- Heal earlier between encounters, BEFORE entering another battle near the RUN floor.
    return m.hp*4<=m.max_hp*3 or rest_needed(m)
end

local function tackle(m)
    for i,id in ipairs(m.moves) do if id==33 and m.pp[i]>0 then return i-1 end end
end

-- pret c75f3523 battle_scripts_1.s:3122-3135: Ask+17 is opcode5A (forget?),
-- Ask+32 is opcode5B (stop?). battle_script_commands.c:5142-5325: state1 accepts
-- JOY_NEW; B at5A declines, but B at5B RESTARTS the question. At5B choose YES(0), A.
-- battle_script_commands.h:24,32 pins learnMoveState +0x1F and cursor +1.
-- Offsets/opcodes/branch target independently pinned against BOTH title ROMs in unit tests.
function R.move_prompt(io, s, log)
    local last
    return function()
        local pc=io.u32(s.gBattlescriptCurrInstr)
        local ask=s.BattleScript_AskToLearnMove
        if pc<ask or pc>=s.BattleScript_ForgotAndLearnedNewMove then
            last=nil;return false
        end
        local state=io.u8(s.gBattleScripting+0x1F)
        local cursor=io.u8(s.gBattleCommunication+1)
        local which = pc==ask+17 and "forget" or pc==ask+32 and "stop" or nil
        if not which then return true,"B" end -- ordinary text within this exact script
        assert(io.u8(pc)==(which=="forget" and 0x5A or 0x5B),"PREP move prompt opcode mismatch")
        if state~=1 or io.u32(s.gBattleControllerExecFlags)~=0 then return true,nil end
        assert(cursor==0 or cursor==1,"PREP move prompt invalid cursor")
        local button=which=="forget" and "B" or cursor==0 and "A" or "Up"
        local marker=string.format("PREP_MOVE_PROMPT phase=%s move=%d pc=0x%X state=%d cursor=%d input=%s",
                                  which,io.u16(s.gMoveToLearn),pc,state,cursor,button)
        if marker~=last then log(marker);last=marker end
        return true,button
    end
end

function R.train(c, label, floor, heal, guard)
    local function lead() return c.party()[1] end
    while lead().level < floor do
        guard()
        local m=lead();local move=tackle(m)
        while heal_before_hunt(m) or not move or m.pp[move+1]<5 do
            heal();guard()
            m=lead();move=tackle(m) -- a failed escape on the return walk can cost HP
        end
        assert(c.hunt(label),"training encounter not reached")
        local rest=false
        for _=1,80 do
            guard()
            local turn=c.await_turn(60,"B",c.move_prompt)
            if turn=="over" then break end
            assert(turn=="action","training forced party menu or stalled")
            m=lead();move=tackle(m)
            if not move or rest_needed(m) then
                c.log(string.format("PREP_ESCAPE training hp=%d/%d",m.hp,m.max_hp))
                local ok,why=c.run_away(label.." training rest")
                assert(ok,"training rest escape: "..tostring(why))
                rest=true;break
            end
            local ok,why=c.use_move(move);assert(ok,why)
        end
        assert(not c.in_battle(),"training battle budget exhausted")
        assert(c.play.wait_scene_settled(c.cp,1800),"training did not settle");guard()
        if rest or heal_before_hunt(lead()) then heal() end
    end
end

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
    local next_progress = start
    local function guard()
        assert(frame()-start < prep.max_frames, "PREPARATION frame budget exhausted")
        local p = c.party()
        assert(p and p[1] and p[1].hp>0, "PREPARATION lead fainted")
        if frame() >= next_progress then
            local m=p[1]
            c.log(string.format("PREP_PROGRESS level=%d exp=%d hp=%d/%d frames=%d budget=%d",
                  m.level,m.experience or -1,m.hp,m.max_hp,frame()-start,prep.max_frames))
            next_progress=frame()+6000
        end
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
    local function field_diagnostic(tag, dir)
        local function predicate(name)
            local value,want=c.G.pred(c.cp,name)
            return string.format("%s=%s/%s",name,tostring(value),tostring(want))
        end
        local g,n=c.G.map(c.cp);local x,y=c.G.pos(c.cp)
        c.log(string.format("%s dir=%s map=%d.%d at=(%d,%d) frames=%d field=%s battle=%s %s %s",
              tag,dir or "none",g,n,x,y,frame()-start,tostring(c.on_field()),tostring(c.in_battle()),
              predicate("field_controls_locked"),predicate("script_context_status")))
    end
    local function step(dir, flee)
        local x,y=c.G.pos(c.cp); local d=delta[dir]
        local from_g,from_n=c.G.map(c.cp)
        local function changed_map()
            local g,n=c.G.map(c.cp)
            return g>=0 and g<255 and n>=0 and n<255 and (g~=from_g or n~=from_n)
        end
        local moved=false
        for _=1,60 do
            tick(dir)
            local u,v=c.G.pos(c.cp)
            if changed_map() or u~=x or v~=y then moved=true;break end
        end
        if not moved then
            field_diagnostic("PREP_BLOCKED",dir)
            error("route blocked going "..dir)
        end
        for _=1,24 do if c.in_battle() then break end;tick() end
        if flee and c.in_battle() then
            local ok,why=c.run_away(label.." incidental")
            assert(ok,"incidental flee: "..tostring(why));guard()
        end
        local u,v=c.G.pos(c.cp)
        -- Warp movement need not change x/y. Callers still enforce their exact segment
        -- map/end tile; recognizing a transition does not admit an unexpected destination.
        assert(changed_map() or (u==x+d[1] and v==y+d[2]),"unexpected route step destination")
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
        -- SP verifies coordinates, not control unlock. The LG receipt had already entered
        -- Forest before the next Up failed at(29,62). Do not spend a step budget during fade
        -- cleanup: admit the destination only after field/script controls are stably free.
        local stable=0
        local ready=await(function()
            stable=quiet() and stable+1 or 0
            return stable>=60
        end,1800)
        if not ready then
            field_diagnostic("PREP_BLOCKED_WARP",dir)
            error("PREPARATION warp controls never settled")
        end
        assert(at(dest.group,dest.num,dest.x,dest.y),"wrong warp destination")
    end
    local function lead() return (c.party() or {})[1] end
    local function healthy()
        local m=lead()
        return m and m.hp==m.max_hp and m.status==0
    end
    local function heal()
        c.log("PREP_HEAL begin")
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
        c.log("PREP_HEAL returned")
    end
    local function run()
        assert(expected==102,"unsupported preparation trainer")
        assert(at(3,1,T.START[1],T.START[2]),"T2 needs the town fixture")
        -- boot_to_field only holds callback2/fade for60 frames, not field/script control.
        -- Its save helper documents a CONTINUE control lock lasting100+ frames. Do not spend
        -- the first step's60-tick movement budget on that independent settle interval.
        -- No battle await/prompt reader runs here: those cannot clear this walk's inputs.
        local stable=0
        local ready=await(function()
            stable=quiet() and stable+1 or 0
            return stable>=60
        end,1800)
        if not ready then
            field_diagnostic("PREP_BLOCKED_READY")
            error("PREPARATION field/script controls never settled")
        end
        c.log(string.format("PREP_READY frames=%d stable=60",frame()-start))
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
        R.train(c,label,prep.level_floor,heal,guard)
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
        -- Gate(7,1): collision0, MB_CAVE_DOOR0x60 (IsNonAnimDoor) on BOTH ROMs; Up from(7,2)
        -- steps onto it, then TryStartStepBasedScript -> TryStartWarpEventScript -> DoWarp
        -- (field_control_avatar.c:618-623,856-898). NOT TryDoorWarp's forward0x69 check,
        -- and NOT TryArrowWarp (current tile + matching direction, :249-251,825-838).
        -- Forest(29,62) is SOUTH arrow0x65: north leaves it normally after unlock.
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
    local function bounded()
        if c.emulator then
            local passed,value=R.with_budget(c.emulator,frame,prep.max_frames,run,guard)
            if not passed then error(value,0) end
            return value
        end
        return run() -- read-only unit fakes also exercise guard() directly
    end
    ok,result=R.with_incidental_escape(c,label,bounded)
    if not ok then return false,tostring(result) end
    return result
end
return R
