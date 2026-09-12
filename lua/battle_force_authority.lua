-- R/B/Y binding for lua/instruction_executor.lua: battle force-faint and force-explode (PROTOTYPE, not wired in).
-- Sites, addresses, the member AND the write lists come from the server-issued authority; this file only knows
-- how to snapshot the Gen 1 battle state at the instruction and which of the server's write sets a death may take:
--   faint   (NAME)    active linked mon -> wBattleMonHP=0000 (+ wPlayerSelectedMove=$FF at ExecutePlayerMove+0)
--   explode (EXPLODE) active linked mon -> loop_head: wBattleMonMoves[0..3]=$99 + wBattleMonPP[0..3]=5 (not transformed)
--                                          player_action: wPlayerSelectedMove=$99 (unless the turn was already taken)
--   either            benched linked mon -> its party slot HP=0000 and status=00 (the only copy during a battle)
-- decide() must stay byte-for-byte equivalent to server/battle_force_authority.decide (same checks, order, reasons).
local Executor=require("instruction_executor")
local M={NAME="rby-battle-force-faint",EXPLODE="rby-battle-force-explode",PARTY_STRIDE=44,TRANSFORMED=8}
local function u8(a)return memory.read_u8(a,"System Bus")end
function M.snapshot(a,member)
    local slot=u8(a.wPlayerMonNumber);local mine=member.slot
    return {is_in_battle=u8(a.wIsInBattle),battle_type=u8(a.wBattleType),link_state=u8(a.wLinkState),player_mon_number=slot,
        status3=u8(a.wPlayerBattleStatus3),battle_species=u8(a.wBattleMonSpecies),battle_dvs_hex=Executor.hex(a.wBattleMonDVs,2),
        party_species=u8(a.wPartyMon1+M.PARTY_STRIDE*mine),party_dvs_hex=Executor.hex(a.wPartyMon1DVs+M.PARTY_STRIDE*mine,2),
        party_ot_id_hex=Executor.hex(a.wPartyMon1OTID+M.PARTY_STRIDE*mine,2),
        party_hp_hex=Executor.hex(a.wPartyMon1HP+M.PARTY_STRIDE*mine,2),party_status=u8(a.wPartyMon1Status+M.PARTY_STRIDE*mine),
        hp_hex=Executor.hex(a.wBattleMonHP,2),enemy_hp_hex=Executor.hex(a.wEnemyMonHP,2),
        action_result=u8(a.wActionResultOrTookBattleTurn),selected_move=u8(a.wPlayerSelectedMove),
        moves_hex=Executor.hex(a.wBattleMonMoves,4),pp_hex=Executor.hex(a.wBattleMonPP,4)}
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
    if authority.binding~=M.EXPLODE then return {writes=authority.sites[site].writes,outcome="fainted"}end
    if site=="loop_head" and transformed then return refuse("transformed battle mon keeps the copied moveset")end
    if site=="player_action" and state.action_result~=0 then return refuse("turn already taken")end
    return {writes=authority.sites[site].writes,outcome="explode_armed"}
end
-- options.name selects the binding this executor serves (default the faint binding); the authority must name the same one.
function M.new(options)
    return Executor.new({owner_id=options.owner_id,held=options.held,binding={name=options.name or M.NAME,snapshot=M.snapshot,decide=M.decide}})
end
return M
