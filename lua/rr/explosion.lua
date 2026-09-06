-- RR-only volatile Explosion obligations. The existing Variant-3 memory helper
-- remains the sole arming mechanism. No network, HUD, journal or native opcode.
local Explosion = {}
local Snapshot = require("rr.battle_snapshot")

function Explosion.new(M,io,context)
    local self={}
    local generation,continuity,last=0,0,nil
    local current
    function self.begin_frame(sample,host_frame)
        local swap=sample.swap or {}
        local borrowed=sample.owner=="borrowed_party" or (sample.in_battle and M.isBorrowedBattle and M.isBorrowedBattle()) or false
        if not last or sample.save_fingerprint~=last.save or sample.patch_present~=last.patch
            or host_frame<last.frame then continuity=continuity+1 end
        if not last or sample.in_battle~=last.battle or borrowed~=last.borrowed or swap.active~=last.active or swap.seq~=last.seq
            or continuity~=last.continuity then generation=generation+1 end
        last={save=sample.save_fingerprint,patch=sample.patch_present,battle=sample.in_battle,
            active=swap.active,seq=swap.seq,borrowed=borrowed,frame=host_frame,continuity=continuity}
        current=sample
    end
    function self.request(key)
        return {key=key,save=current and current.save_fingerprint,continuity=continuity,
            generation=generation,in_battle=current and current.owner=="battle",phase="waiting"}
    end
    local function view(key,request,busy)
        if busy then return nil,"party mutation pending" end
        if request.key~=key or request.continuity~=continuity or not request.save then
            return nil,"Explosion continuity needs reconciliation"
        end
        local sample=context.sample()
        if sample.save_fingerprint~=request.save or not sample.party_observable then
            return nil,"real party identity unavailable"
        end
        if not sample.swap or not current.swap or sample.in_battle~=current.in_battle or sample.owner~=current.owner
            or sample.swap.active~=current.swap.active or sample.swap.seq~=current.swap.seq then
            return nil,"context changed within frame"
        end
        local slot,n=nil,0
        for i=0,sample.count-1 do
            if M.monKey(M.PARTY_BASE+i*M.MON_SIZE)==key then slot=i;n=n+1 end
        end
        if n~=1 then return nil,"target absent or ambiguous" end
        local result={slot=slot,base=M.PARTY_BASE+slot*M.MON_SIZE,in_battle=sample.in_battle}
        if not sample.in_battle then
            local ready,why=context.storage_readback_prerequisite(sample)
            if not ready or not M.isPostBattleSettled() then return nil,why or "post-battle party writer unsettled" end
            return result
        end
        if sample.owner~="battle" or (M.isBorrowedBattle and M.isBorrowedBattle()) then
            return nil,"borrowed battle ownership"
        end
        local count=io.read_u8(M.BATTLERS_COUNT_ADDR)
        if count~=2 and count~=4 then return nil,"battler count unavailable" end
        local seen={}
        for battler=0,count-1,2 do
            local mon,why=Snapshot.read(M,io,battler)
            if not mon then return nil,why end
            if io.read_u16_le(M.BATTLER_PARTY_INDEXES_ADDR+battler*2)~=mon.slot or seen[mon.key] then
                return nil,"battler index/identity transition"
            end
            seen[mon.key]=true
            if mon.key==key then result.battler=battler;result.hp=mon.hp end
        end
        if result.battler then
            local bs=io.read_u32_le(M.BATTLE_STRUCT_PTR_ADDR)
            local last_offset=math.max(M.BATTLE_STRUCT_CHOSEN_MOVE_POS_OFF,M.BATTLE_STRUCT_MOVE_TARGET_OFF)+3
            if bs%4~=0 or bs<0x02000000 or bs+last_offset>=0x02040000 then
                return nil,"battle allocation unavailable"
            end
            result.bs=bs
        end
        return result
    end
    local function reinforce(target)
        -- Exact existing Variant-3 reinforcement: never move a progressed
        -- controller back to STANDBY. Only the ownership prerequisite is new.
        local battler=target.battler
        if io.read_u8(M.BATTLE_COMM_ADDR+battler)<3 then
            io.write_u8(M.CHOSEN_ACTION_ADDR+battler,0)
            io.write_u16_le(M.CHOSEN_MOVE_ADDR+battler*2,M.MOVE_EXPLOSION)
            io.write_u8(M.BATTLE_COMM_ADDR+battler,3)
            io.write_u8(target.bs+M.BATTLE_STRUCT_CHOSEN_MOVE_POS_OFF+battler,0)
            io.write_u8(target.bs+M.BATTLE_STRUCT_MOVE_TARGET_OFF+battler,1)
        end
    end
    local function selection_ready(target)
        -- Exact RR binary08014040 dispatches comm0..6. Only0/1/2 select
        -- actions;3/4 are standby/confirmed and5/6 are selection-script paths.
        -- A stale low comm byte during a different battle main is not readiness.
        if io.read_u32_le(M.BATTLE_MAIN_FUNC_ADDR)~=0x08014041 then return false end
        local state=io.read_u8(M.BATTLE_COMM_ADDR+target.battler)
        return state<3 and (state~=2 or io.read_u8(M.CHOSEN_ACTION_ADDR+target.battler)==0)
    end
    function self.advance(key,request,frame,busy)
        local target,why=view(key,request,busy)
        if not target then request.blocked=why;return nil end
        request.blocked=nil
        local own_battler=request.phase=="armed" and request.generation==generation
            and request.battler==target.battler and request.bs==target.bs
        -- A settled field or a coherently benched identity can satisfy the
        -- partner's death obligation. A vanished key is never success.
        local settle=not target.in_battle or target.battler==nil or target.hp==0
        local timeout=own_battler and frame-request.start_frame>=600 and selection_ready(target)
        if settle or timeout then
            if own_battler and M.LOCKED_MOVES_ADDR then
                io.write_u16_le(M.LOCKED_MOVES_ADDR+target.battler*2,0)
            end
            M.forceFaint(target.slot) -- every current player index was identity-checked above
            return {effect="settled",slot=target.slot,base=target.base,
                cause=own_battler and target.hp==0 and "engine" or (target.in_battle and "external_override" or "external"),
                timeout=timeout}
        end
        if request.phase=="waiting" then
            if not request.in_battle or request.generation~=generation then
                request.blocked="original battle ended; death remains pending";return nil
            end
            if not selection_ready(target) then request.blocked="waiting for action selection";return nil end
            if not M.forceExplodeBattler(target.battler) then request.blocked="Explosion helper refused";return nil end
            request.phase="armed";request.battler=target.battler;request.bs=target.bs;request.start_frame=frame
            return {effect="armed",slot=target.slot,battler=target.battler}
        end
        if not own_battler then
            request.blocked="armed battler/context changed; death remains pending";return nil
        end
        local base=M.BATTLE_MONS_ADDR+target.battler*M.BATTLE_MON_SIZE
        if io.read_u8(base+M.BATTLE_MON_PP_OFF)>=5 and selection_ready(target) then reinforce(target) end
        return nil
    end
    return self
end
return Explosion
