--[[
  lua/tests/gen1_battle_driver.lua — drive the ORIGINAL Gen 1 engine's battle menus with joypad
  input, one caller-owned frame per step(buttons), and report exact state evidence.

  Everything here follows pret/pokered engine/battle/core.asm (Yellow is byte-for-byte the same
  logic for these menus; only the PCs differ):

    DisplayBattleMenu     wTopMenuItemY=$e, wTopMenuItemX=9 (FIGHT/ITEM) or 15 (PKMN/RUN),
                          wMaxMenuItem=1, wMenuWatchedKeys=RIGHT|A ($11) left / LEFT|A ($21) right,
                          wMenuWrappingEnabled=0 so Up/Down never wrap; the remembered id carries
                          +2 in the right column (".AButtonPressed ... add $2").
    MoveSelectionMenu     .regularmenu: wTopMenuItemY=$c, wTopMenuItemX=5,
                          wCurrentMenuItem = wPlayerMoveListIndex+1 (the move cursor is 1-BASED),
                          wMaxMenuItem = wNumMovesMinusOne+2 (= move count + 1, the wrap sentinel
                          SelectMenuItem_CursorDown folds back to 1), watched = everything but
                          LEFT|RIGHT|START ($c7).
    SelectMenuItem        A: cur-1 -> wPlayerMoveListIndex; PP==0 -> "No PP left" prompt then
                          jp MoveSelectionMenu; else wPlayerSelectedMove=wBattleMonMoves[cur-1],
                          ret z -> MainInBattleLoop .selectEnemyMove -> SelectEnemyMove ->
                          ExecutePlayerMove / ExecuteEnemyMove in speed order.
                          B: ret nz -> "jr nz, MainInBattleLoop" (battle menu again, no turn).
    Party menu            PartyMenuInit: y=1, x=0, max=wPartyCount-1, watched A|B, wrapping ON.
                          Then the SWITCH/STATS/CANCEL box: y=x=$c, cur=0, max=2, watched B|A.
    Bag                   DisplayListMenuID: y=4, x=5, max=2 (>=2 entries) else 1, watched
                          A|B|SELECT ($07); item index = wListScrollOffset + wCurrentMenuItem.
    Input                 hJoy7 is 0 throughout battle (only list menus set it), so
                          HandleMenuInput_/JoypadLowSensitivity see hJoyPressed ONLY: an edge
                          relative to the game's LAST Joypad poll (hJoyLast), never a held key.
                          HandleMenuInput_ runs PlaceMenuCursor + Delay3 (3 frames) before its
                          first poll, so a press must still be held at that poll to count.

  new{step=function(buttons) end, u8=function(addr) end, sites={...}, addresses={...}}
    sites:     display_battle_menu, move_selection_menu, select_enemy_move,
               execute_player_move, execute_enemy_move  (bank $0F PCs; any extra names are
               hooked and counted too)
    addresses: wTopMenuItemX wCurrentMenuItem wMaxMenuItem wMenuWatchedKeys wIsInBattle
               wPlayerSelectedMove wActionResultOrTookBattleTurn hLoadedROMBank (required)
               wTopMenuItemY wListScrollOffset wPlayerMonNumber wWhichPokemon wPartyCount
               wBattleMonMoves wBattleMonPP wBattleMonHP wEnemyMonHP wEnemySelectedMove
               wCurItem hJoyPressed hJoy5 (optional, enrich the evidence)
               wNumRunAttempts (optional for construction, but D.run's receipt that the RUN
                                press was taken; without it D.run refuses with why=no_run_counter
                                rather than repress blind)
    optional:  hook=function(pc, fn) -> id (default event.on_bus_exec, "System Bus"),
               unhook=function(id), framecount=function() (default emu.framecount),
               press={pre=2, hold=3, post=3}
  Plain Lua 5.4 (no goto, no bit32).
--]]
local M={}
local PAD={A=0x01,B=0x02,SELECT=0x04,START=0x08,RIGHT=0x10,LEFT=0x20,UP=0x40,DOWN=0x80}
M.PAD=PAD
M.BATTLE_MENU={left_x=9,right_x=15,left_watched=PAD.RIGHT+PAD.A,right_watched=PAD.LEFT+PAD.A}
M.MOVE_MENU={x=5,y=0x0c,watched=0xFF-(PAD.LEFT+PAD.RIGHT+PAD.START)}
M.PARTY_MENU={x=0,y=1}
M.SWITCH_BOX={x=0x0c,y=0x0c,max=2}
M.BAG={x=5,y=4,watched=PAD.A+PAD.B+PAD.SELECT}
M.TARGET={FIGHT={"left",0},ITEM={"left",1},PKMN={"right",0},RUN={"right",1}}
M.RUN_REPRESS=120 -- frames D.run waits for a sign the RUN press was taken before pressing again

function M.new(o)
    local step,u8,A=assert(o.step),assert(o.u8),assert(o.addresses)
    local S=assert(o.sites)
    local frame_of=o.framecount or function()return emu.framecount()end
    local hook=o.hook or function(pc,fn)return event.on_bus_exec(fn,pc,"gen1-battle-driver-"..tostring(pc),"System Bus")end
    local unhook=o.unhook or function(id)event.unregisterbyid(id)end
    local P=o.press or {};local PRE,HOLD,POST=P.pre or 2,P.hold or 3,P.post or 3
    local bank_addr=assert(A.hLoadedROMBank,"addresses.hLoadedROMBank")
    for _,k in ipairs({"wTopMenuItemX","wCurrentMenuItem","wMaxMenuItem","wMenuWatchedKeys","wIsInBattle","wPlayerSelectedMove","wActionResultOrTookBattleTurn"})do assert(A[k],"addresses."..k)end
    local D={}
    local n=0                       -- driver-local step count (frames the caller stepped for us)
    local hits={}                   -- site -> {count, first, last, last_step}
    local ids={}
    for name,pc in pairs(S)do
        hits[name]={count=0}
        ids[#ids+1]=hook(pc,function()
            if u8(bank_addr)==0x0F then
                local h=hits[name];h.count=h.count+1;h.last=frame_of();h.last_step=n;h.first=h.first or h.last
            end
        end)
    end
    local function count(name)return hits[name] and hits[name].count or 0 end
    local function fired_since(name,base)return count(name)>base and hits[name].last or nil end
    local function rd(k)return A[k] and u8(A[k]) or nil end
    local function hp(k)if not A[k] then return nil end;return u8(A[k])*256+u8(A[k]+1)end

    local function tick(buttons)n=n+1;step(buttons)end
    local function idle(frames)for _=1,frames do tick(nil)end end
    -- a press the engine cannot merge with a neighbour: released frames, held frames, released frames
    local function press(btn)idle(PRE);local at=frame_of();for _=1,HOLD do tick({[btn]=true})end;idle(POST);return at end

    function D.state()
        return {frame=frame_of(),step=n,x=u8(A.wTopMenuItemX),y=rd("wTopMenuItemY"),cur=u8(A.wCurrentMenuItem),max=u8(A.wMaxMenuItem),
            watched=u8(A.wMenuWatchedKeys),in_battle=u8(A.wIsInBattle),took_turn=u8(A.wActionResultOrTookBattleTurn),
            selected_move=u8(A.wPlayerSelectedMove),player_mon=rd("wPlayerMonNumber"),joy_pressed=rd("hJoyPressed"),joy5=rd("hJoy5")}
    end
    function D.hits()local out={};for k,v in pairs(hits)do out[k]={count=v.count,first=v.first,last=v.last,last_step=v.last_step}end;return out end

    local function battle_menu_consistent(st)
        return (st.x==M.BATTLE_MENU.left_x and st.watched==M.BATTLE_MENU.left_watched)
            or (st.x==M.BATTLE_MENU.right_x and st.watched==M.BATTLE_MENU.right_watched)
    end
    -- until(pred, max [, tap]): tick frames until pred(state) returns a truthy reason; returns
    -- reason|nil, frames used. With `tap`, that button is re-pulsed on the 16-frame cadence
    -- instead of idling, for waits that sit behind a PrintText box (see D.run).
    local function until_(pred,max,tap)
        for i=0,max do
            local st=D.state();local why=pred(st)
            if why then return why,i,st end
            if i<max then tick(tap and i%16<2 and {[tap]=true} or nil)end
        end
        return nil,max,D.state()
    end

    -- FIGHT/ITEM/PKMN/RUN menu: entered (DisplayBattleMenu executed, bank $0F) and the cursor
    -- variables already written for one of the two columns (they are stale until then).
    local menu_base=0
    function D.wait_menu(max_frames)
        local why,frames,st=until_(function(st)
            if st.in_battle==0 then return "battle_over"end
            if count("display_battle_menu")>menu_base and battle_menu_consistent(st)then return "menu"end
        end,max_frames or 600)
        return {ok=why=="menu",why=why or "timeout",frames=frames,entered_frame=hits.display_battle_menu and hits.display_battle_menu.last,
            menu_entries=count("display_battle_menu")-menu_base,state=st}
    end

    -- Two 2-item columns, no vertical wrap (wMenuWrappingEnabled=0), remembered id +2 on the right.
    function D.choose(name)
        local want=assert(M.TARGET[name],"unknown battle menu item "..tostring(name))
        local trace={name=name,presses={},ok=false}
        for _=1,8 do
            local st=D.state()
            if st.in_battle==0 then trace.why="battle_over";trace.state=st;return trace end
            local col=(st.x==M.BATTLE_MENU.left_x)and"left"or(st.x==M.BATTLE_MENU.right_x)and"right"or"?"
            local row=st.cur%2
            if col==want[1] and row==want[2] then
                trace.before=st;menu_base=count("display_battle_menu")
                trace.a_frame=press("A");trace.ok=true;trace.after=D.state();return trace
            end
            local btn
            if col~=want[1] then btn=(want[1]=="left")and"Left"or"Right"
            elseif row<want[2] then btn="Down" else btn="Up" end
            local at=press(btn)
            -- the column re-entry runs HandleMenuInput's PlaceMenuCursor+Delay3 before polling again
            until_(function(s)local c=(s.x==M.BATTLE_MENU.left_x)and"left"or"right";return (c~=col or s.cur%2~=row) and "moved" or nil end,8)
            trace.presses[#trace.presses+1]={button=btn,frame=at,from={x=st.x,cur=st.cur},to={x=u8(A.wTopMenuItemX),cur=u8(A.wCurrentMenuItem)}}
        end
        trace.why="cursor never reached "..name;trace.state=D.state();return trace
    end

    -- Move the 1-based move cursor to `slot` and commit with A; wait for the turn's stages.
    function D.commit_move(slot,max_frames)
        slot=slot or 1;max_frames=max_frames or 900
        local base={mm=count("move_selection_menu"),sem=count("select_enemy_move"),epm=count("execute_player_move"),eem=count("execute_enemy_move"),dbm=count("display_battle_menu")}
        local t={slot=slot,stages={},ok=false,hp_before={player=hp("wBattleMonHP"),enemy=hp("wEnemyMonHP")}}
        -- 1. MoveSelectionMenu entered and .regularmenu state written (x=5)
        local why,used,st=until_(function(s)
            if s.in_battle==0 then return "battle_over"end
            -- the caller may already have opened the move menu (choose("FIGHT") before this call): x=5,y=$c is unique to it
            if (count("move_selection_menu")>base.mm or (s.x==M.MOVE_MENU.x and s.y==M.MOVE_MENU.y)) and s.x==M.MOVE_MENU.x then return "move_menu"end
            if count("display_battle_menu")>base.dbm and battle_menu_consistent(s)then return "battle_menu"end -- FIGHT never opened the move menu
        end,120)
        t.stages.move_menu=fired_since("move_selection_menu",base.mm);t.menu_wait_frames=used
        if why~="move_menu" then t.why=why or "move menu not entered (asleep/frozen/trapped/turn already used skip it)";t.state=st;return t end
        t.moves=st.max-1 -- wMaxMenuItem = wNumMovesMinusOne + 2
        if slot<1 or slot>t.moves then t.why="slot "..slot.." beyond move count "..t.moves;t.state=st;return t end
        idle(4) -- HandleMenuInput_: PlaceMenuCursor + Delay3 before the first JoypadLowSensitivity poll
        -- 2. cursor (1-based); SelectMenuItem_CursorUp/Down redraw through MoveSelectionMenu again
        t.cursor_presses={}
        for _=1,8 do
            local cur=u8(A.wCurrentMenuItem)
            if cur==slot then break end
            local btn=(cur<slot)and"Down"or"Up"
            local at=press(btn)
            until_(function(s)return s.cur~=cur and "moved" or nil end,10);idle(4)
            t.cursor_presses[#t.cursor_presses+1]={button=btn,frame=at,from=cur,to=u8(A.wCurrentMenuItem)}
        end
        t.before_a=D.state()
        if t.before_a.cur~=slot then t.why="cursor stuck at "..t.before_a.cur;return t end
        if A.wBattleMonPP then t.pp_before=u8(A.wBattleMonPP+slot-1)%64 end
        if A.wBattleMonMoves then t.expected_move=u8(A.wBattleMonMoves+slot-1)end
        -- 3. the press edge. hJoyLast is the game's LAST poll, so make sure every earlier press has been
        --    seen released before this one, and re-press if the menu did not act on it (measured live: a
        --    press right after the FIGHT confirmation was not taken; the next one, later, was).
        idle(24)
        t.attempts=0
        repeat
            t.attempts=t.attempts+1
            t.stages.selected=press("A")
            t.selected_move=u8(A.wPlayerSelectedMove)
            -- 4. the turn: SelectEnemyMove, then the two Execute* in speed order
            why,used,st=until_(function(s)
                if s.in_battle==0 then return "battle_over"end
                if count("execute_player_move")>base.epm then return "player_move"end
                if count("select_enemy_move")>base.sem or count("execute_enemy_move")>base.eem then return nil end -- turn under way: keep waiting
                if count("display_battle_menu")>base.dbm and battle_menu_consistent(s)then return "battle_menu_again"end
            end,(t.attempts<3) and 240 or max_frames)
            if why==nil and (count("select_enemy_move")>base.sem or count("execute_enemy_move")>base.eem) then
                why,used,st=until_(function(s)
                    if s.in_battle==0 then return "battle_over"end
                    if count("execute_player_move")>base.epm then return "player_move"end
                    if count("display_battle_menu")>base.dbm and battle_menu_consistent(s)then return "battle_menu_again"end
                end,max_frames)
            end
        until why~=nil or t.attempts>=3
        t.stages.select_enemy_move=fired_since("select_enemy_move",base.sem)
        t.stages.execute_enemy_move=fired_since("execute_enemy_move",base.eem)
        t.stages.execute_player_move=fired_since("execute_player_move",base.epm)
        t.stages.battle_menu_again=(why=="battle_menu_again")and hits.display_battle_menu.last or nil
        t.move_menu_reentries=count("move_selection_menu")-base.mm-1 -- >0 = "No PP"/"disabled" text or a cursor redraw
        t.enemy_selected_move=rd("wEnemySelectedMove")
        t.frames_after_a=used;t.why=why or "timeout";t.ok=why=="player_move"
        t.still_in_move_menu=(why==nil) and st.x==M.MOVE_MENU.x and t.stages.select_enemy_move==nil
        t.hp_after={player=hp("wBattleMonHP"),enemy=hp("wEnemyMonHP")};t.state=st
        return t
    end

    -- PKMN -> party list -> `slot` (0-based, = wPlayerMonNumber) -> SWITCH.
    function D.switch_to(slot,max_frames)
        max_frames=max_frames or 900
        assert(A.wTopMenuItemY,"addresses.wTopMenuItemY (party/switch boxes are told apart by Y)")
        local t={slot=slot,stages={},ok=false,player_mon_before=rd("wPlayerMonNumber")}
        local base={dbm=count("display_battle_menu"),eem=count("execute_enemy_move")}
        t.choose=D.choose("PKMN");if not t.choose.ok then t.why="PKMN not chosen";return t end
        local why,used,st=until_(function(s)
            if s.in_battle==0 then return "battle_over"end
            if s.x==M.PARTY_MENU.x and s.y==M.PARTY_MENU.y and s.watched==PAD.A+PAD.B then return "party_menu"end
        end,240)
        t.stages.party_menu=why=="party_menu" and st.frame or nil
        if why~="party_menu" then t.why=why or "party menu not shown";t.state=st;return t end
        if A.wPartyCount and slot>u8(A.wPartyCount)-1 then t.why="slot beyond party";t.state=st;return t end
        idle(4)
        t.cursor_presses={}
        for _=1,8 do
            local cur=u8(A.wCurrentMenuItem)
            if cur==slot then break end
            local btn=(cur<slot)and"Down"or"Up";local at=press(btn)
            until_(function(s)return s.cur~=cur and "moved" or nil end,10)
            t.cursor_presses[#t.cursor_presses+1]={button=btn,frame=at,from=cur,to=u8(A.wCurrentMenuItem)}
        end
        t.party_cursor=D.state()
        if t.party_cursor.cur~=slot then t.why="party cursor stuck at "..t.party_cursor.cur;return t end
        t.stages.mon_selected=press("A")
        why,used,st=until_(function(s)
            if s.in_battle==0 then return "battle_over"end
            if s.x==M.SWITCH_BOX.x and s.y==M.SWITCH_BOX.y and s.max==M.SWITCH_BOX.max then return "switch_box"end
        end,120)
        t.stages.switch_box=why=="switch_box" and st.frame or nil
        if why~="switch_box" then t.why=why or "SWITCH/STATS/CANCEL box not shown";t.state=st;return t end
        t.which_pokemon=rd("wWhichPokemon")
        idle(4)
        if u8(A.wCurrentMenuItem)~=0 then t.why="switch box cursor not on SWITCH";t.state=D.state();return t end
        t.stages.switch_pressed=press("A")
        why,used,st=until_(function(s)
            if s.in_battle==0 then return "battle_over"end
            if s.player_mon==slot and s.took_turn==1 then return "switched"end
            if s.x==M.PARTY_MENU.x and s.y==M.PARTY_MENU.y then return "back_in_party_menu"end -- AlreadyOut / fainted refusal
            if count("execute_enemy_move")>base.eem then return "enemy_moved"end
        end,max_frames)
        t.stages.switched=(why=="switched" or why=="enemy_moved")and st.frame or nil
        t.frames_after_switch=used;t.why=why or "timeout";t.player_mon_after=rd("wPlayerMonNumber")
        t.ok=t.player_mon_after==slot;t.state=st
        return t
    end

    -- ITEM -> bag -> `index` (0-based bag slot; the CANCEL row is index wNumBagItems) -> A.
    function D.use_item(index,max_frames)
        max_frames=max_frames or 900
        assert(A.wTopMenuItemY and A.wListScrollOffset,"addresses.wTopMenuItemY + wListScrollOffset (bag index = scroll offset + cursor)")
        local t={index=index,stages={},ok=false}
        local base={dbm=count("display_battle_menu"),eem=count("execute_enemy_move")}
        t.choose=D.choose("ITEM");if not t.choose.ok then t.why="ITEM not chosen";return t end
        local why,used,st=until_(function(s)
            if s.in_battle==0 then return "battle_over"end
            if s.x==M.BAG.x and s.y==M.BAG.y and s.watched==M.BAG.watched then return "bag"end
            if count("display_battle_menu")>base.dbm and battle_menu_consistent(s)then return "battle_menu_again"end -- link battle: items refused
        end,240)
        t.stages.bag=why=="bag" and st.frame or nil
        if why~="bag" then t.why=why or "bag not shown";t.state=st;return t end
        local function bag_index()return (A.wListScrollOffset and u8(A.wListScrollOffset) or 0)+u8(A.wCurrentMenuItem)end
        idle(10) -- DisplayListMenuID: ld c,10 / DelayFrames before the loop starts polling
        t.cursor_presses={}
        for _=1,16 do
            local at_idx=bag_index()
            if at_idx==index then break end
            local btn=(at_idx<index)and"Down"or"Up";local at=press(btn)
            until_(function()return bag_index()~=at_idx and "moved" or nil end,12);idle(4)
            t.cursor_presses[#t.cursor_presses+1]={button=btn,frame=at,from=at_idx,to=bag_index()}
        end
        t.bag_cursor=D.state();t.bag_cursor.index=bag_index()
        if t.bag_cursor.index~=index then t.why="bag cursor stuck at "..t.bag_cursor.index;return t end
        t.stages.confirmed=press("A")
        t.cur_item=rd("wCurItem")
        why,used,st=until_(function(s)
            if s.in_battle==0 then return "battle_over"end
            if count("execute_enemy_move")>base.eem then return "turn_used"end
            if count("display_battle_menu")>base.dbm and battle_menu_consistent(s)then return "battle_menu_again"end
        end,max_frames)
        t.frames_after_a=used;t.why=why or "timeout";t.ok=why=="turn_used" or why=="battle_over";t.state=st
        return t
    end

    -- RUN: escaped (wIsInBattle 0) or the menu comes back (can't escape / trainer battle).
    -- Two measured ways a single blind A press dies here, both unrecoverable from outside: the
    -- battle menu is still on screen, so DisplayBattleMenu never executes again and a caller's
    -- B-mash fallback hits a key the menu does not watch (watched = RIGHT|A / LEFT|A).
    --   * The A is not always taken. D.choose only ever proves a press indirectly, by watching the
    --     CURSOR move; when the cursor is already on RUN it moves nothing and the lone A is never
    --     verified (commit_move re-presses through the same miss, :178-199). "Already on RUN" is
    --     exactly what a previous RUN leaves behind: .AButtonPressed saves the id in
    --     wBattleAndStartSavedMenuItem (core.asm:2131-2136) and the next menu re-seeds the cursor
    --     from it (:2056-2062). So press RUN again while the engine shows no sign of having taken
    --     it -- TryRunningFromBattle increments wNumRunAttempts before any RNG (:1508-1510), which
    --     is the receipt that it did.
    --   * "Got away safely!" (:1608-1612) and "Can't escape!" (:1573-1580) are PrintText boxes that
    --     wait for a button, so an input-free wait burns the whole budget on a run that has in fact
    --     escaped. B advances them and, being unwatched, cannot disturb the menu.
    -- wNumRunAttempts is D.run's only receipt that a RUN press was taken (see above); without it
    -- a repress cannot be told apart from a miss, and a blind repress can land on "Use next
    -- Pokémon?" after an escape-turn KO. Require it rather than falling back to a blind cadence.
    function D.run(max_frames)
        max_frames=max_frames or 600
        if not A.wNumRunAttempts then return{ok=false,why="no_run_counter",presses=0,frames=0,stages={}}end
        local t={stages={},ok=false,attempts_before=rd("wNumRunAttempts"),presses=1,frames=0}
        local base={dbm=count("display_battle_menu")}
        t.choose=D.choose("RUN");if not t.choose.ok then t.why="RUN not chosen";return t end
        local function taken()return t.attempts_before and rd("wNumRunAttempts")~=t.attempts_before end
        local why,used,st
        while t.frames<max_frames do
            local left=max_frames-t.frames
            why,used,st=until_(function(s)
                if s.in_battle==0 then return "escaped"end
                if count("display_battle_menu")>base.dbm and battle_menu_consistent(s)then return "battle_menu_again"end
            end,taken() and left or math.min(M.RUN_REPRESS,left),"B")
            t.frames=t.frames+used
            if why or t.frames>=max_frames then break end
            -- re-check right before the press: a counter that moved during the wait means the
            -- earlier A was in fact taken, so this repress would be spurious.
            if not taken()then t.presses=t.presses+1;t.stages["repress"..t.presses]=press("A");t.frames=t.frames+PRE+HOLD+POST end
        end
        t.why=why or "timeout";t.ok=why=="escaped";t.state=st;t.attempts_after=rd("wNumRunAttempts")
        return t
    end

    function D.steps()return n end
    function D.close()for _,id in ipairs(ids)do pcall(unhook,id)end;ids={}end
    return D
end

return M
