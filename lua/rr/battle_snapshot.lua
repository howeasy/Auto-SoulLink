-- Read-only RR player-battler projection. Party indexes can advance before the
-- outgoing BattlePokemon is replaced, so a mismatched index is not permission
-- to assign the outgoing HP to the incoming mon or discard an observed death.
local Snapshot = {}
function Snapshot.read(M,io,battler)
    local base=M.BATTLE_MONS_ADDR+battler*M.BATTLE_MON_SIZE
    local hp,maxHP=io.read_u16_le(base+M.BATTLE_MON_HP_OFF),io.read_u16_le(base+0x2C)
    local level=io.read_u8(base+0x2A)
    if maxHP==0 or level==0 then return nil,"uninitialized" end
    local key=string.format("%08X:%08X",io.read_u32_le(base+M.BATTLE_MON_PERS_OFF),
        io.read_u32_le(base+M.BATTLE_MON_OTID_OFF))
    local count=io.read_u8(M.PARTY_COUNT_ADDR)
    if count>6 then return nil,"invalid party count" end
    local function matches(slot)
        local address=M.PARTY_BASE+slot*M.MON_SIZE
        return M.slotOccupied(address) and M.monKey(address)==key
    end
    -- Even a plausible index cannot disambiguate two raw records with the same
    -- wire identity. Count matches before constructing any key-indexed view.
    local index,n=nil,0
    for slot=0,count-1 do if matches(slot) then index=slot;n=n+1 end end
    if n~=1 then return nil,hp==0 and "unattributed zero" or "unmatched identity" end
    return {key=key,slot=index,hp=hp,maxHP=maxHP,level=level,ability=io.read_u8(base+0x20)}
end
return Snapshot
