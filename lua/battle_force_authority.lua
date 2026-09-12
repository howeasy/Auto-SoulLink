-- R/B/Y binding for lua/instruction_executor.lua: battle force-faint (PROTOTYPE, not wired in).
-- Sites, addresses and the member come from the server-issued authority; this file only knows
-- how to snapshot the Gen 1 battle state at the instruction and which bytes a death may write:
--   active linked mon  -> wBattleMonHP=0000 (+ wPlayerSelectedMove=$FF at ExecutePlayerMove+0)
--   benched linked mon -> its party slot HP=0000 and status=00 (the only copy during a battle)
-- decide() must stay byte-for-byte equivalent to server/battle_force_authority.decide.
local Executor=require("instruction_executor")
local M={NAME="rby-battle-force-faint",PARTY_STRIDE=44,TRANSFORMED=8}
local function u8(a)return memory.read_u8(a,"System Bus")end
function M.snapshot(a,member)
    local slot=u8(a.wPlayerMonNumber);local mine=member.slot
    return {is_in_battle=u8(a.wIsInBattle),battle_type=u8(a.wBattleType),link_state=u8(a.wLinkState),player_mon_number=slot,
        status3=u8(a.wPlayerBattleStatus3),battle_species=u8(a.wBattleMonSpecies),battle_dvs_hex=Executor.hex(a.wBattleMonDVs,2),
        party_species=u8(a.wPartyMon1+M.PARTY_STRIDE*mine),party_dvs_hex=Executor.hex(a.wPartyMon1DVs+M.PARTY_STRIDE*mine,2),
        party_ot_id_hex=Executor.hex(a.wPartyMon1OTID+M.PARTY_STRIDE*mine,2),
        party_hp_hex=Executor.hex(a.wPartyMon1HP+M.PARTY_STRIDE*mine,2),party_status=u8(a.wPartyMon1Status+M.PARTY_STRIDE*mine),
        hp_hex=Executor.hex(a.wBattleMonHP,2),enemy_hp_hex=Executor.hex(a.wEnemyMonHP,2),
        action_result=u8(a.wActionResultOrTookBattleTurn),selected_move=u8(a.wPlayerSelectedMove)}
end
function M.decide(state,member,site,authority)
    local function refuse(reason)return {writes={},refusal=reason}end
    if state.is_in_battle~=1 and state.is_in_battle~=2 then return refuse("not in a wild or trainer battle")end
    if state.battle_type~=0 then return refuse("no player mon in play for this battle type")end
    if state.link_state==4 then return refuse("link battle would desync")end
    if state.party_species~=member.species or state.party_dvs_hex~=member.dvs_hex or state.party_ot_id_hex~=member.ot_id_hex then
        return refuse("party slot is not the linked mon")
    end
    local a=authority.addresses
    if state.player_mon_number~=member.slot then
        if state.party_hp_hex=="0000" then return refuse("already fainted")end
        local hp=a.wPartyMon1HP+M.PARTY_STRIDE*member.slot
        return {writes={{address=hp,value=0},{address=hp+1,value=0},{address=a.wPartyMon1Status+M.PARTY_STRIDE*member.slot,value=0}},outcome="benched"}
    end
    local transformed=math.floor(state.status3/M.TRANSFORMED)%2==1
    if not transformed and (state.battle_species~=member.species or state.battle_dvs_hex~=member.dvs_hex) then
        return refuse("active battle struct is not the linked mon")
    end
    if state.hp_hex=="0000" then return refuse("already fainted")end
    if state.enemy_hp_hex=="0000" then return refuse("enemy faint path owns this turn")end
    return {writes=authority.sites[site].writes,outcome="fainted"}
end
function M.new(options)
    return Executor.new({owner_id=options.owner_id,held=options.held,binding={name=M.NAME,snapshot=M.snapshot,decide=M.decide}})
end
return M
