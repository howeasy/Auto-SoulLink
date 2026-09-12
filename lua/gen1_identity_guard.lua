-- Read-only identity witness for original tutorial name borrowing. No write or
-- execution authority. External-clock trade name swaps are deliberately outside
-- this scope; the production internal-clock animation does not perform them.
local Data=require('gen1_identity_sites')
local M={}
local function byte(a)return memory.read_u8(a,'System Bus')end
local function bytes(a,n,domain)
    local out={};for i=0,n-1 do out[#out+1]=string.format('%02X',memory.read_u8(a+i,domain or 'System Bus'))end
    return table.concat(out)
end
local function pair(a,b)return emu.getregister(a)*256+emu.getregister(b)end
local function word(a)return byte(a)+256*byte(a+1)end
local function prefix(value,before,after)
    for n=0,22,2 do if value==after:sub(1,n)..before:sub(n+1)then return true end end
    return false
end
function M.new(options)
    local p=assert(Data.titles[options.variant]);local r=p.ram
    local context=assert(options.context());local generation,instance=context.context_generation,context.physical_instance
    local original=bytes(r.wPlayerName,11);local id=bytes(r.wPlayerID,2)
    local hooks={};local scope,failure;local closed=false
    local function base()
        assert(not closed and not failure,failure or 'identity witness closed')
        local current=options.context()
        assert(current.context_generation==generation and current.physical_instance==instance
            and gameinfo.getromhash():lower()==options.final_sha1 and bytes(r.wPlayerID,2)==id,'identity physical context changed')
    end
    local function tutorial()
        local name=assert(p.names[tostring(byte(r.wBattleType))],'unqualified tutorial name borrow')
        assert(byte(r.wIsInBattle)==1 and byte(r.wCurMap)==name.map,'tutorial identity context changed')
        if name.pallet_script then
            assert(byte(r.wPartyCount)==0 and byte(r.wPalletTownCurScript)==name.pallet_script,'Oak tutorial source context changed')
        end
        return name
    end
    local function copy_interval(c)
        local pc,sp=emu.getregister('PC'),emu.getregister('SP')
        if sp==c.sp and (pc==c.call or pc==c.done)then return true end
        local function copying(at)return at>=p.copy.address and at<p.copy.address+#p.copy.expected_hex/2 end
        if copying(pc)and sp==c.sp-2 and word(sp)==c.done then return true end
        -- Frame boundaries and engine VBlank hooks observe the interrupt entry,
        -- before its handler changes the stack. Its saved PC must remain in this
        -- exact CopyData invocation (or its immediate return).
        if pc==0x40 then
            if sp==c.sp-4 and copying(word(sp))and word(sp+2)==c.done then return true end
            if sp==c.sp-2 and word(sp)==c.done then return true end
        end
        return false
    end
    local function check()
        base();local current=bytes(r.wPlayerName,11)
        if not scope then assert(current==original,'trainer name changed outside source-qualified tutorial');return true end
        assert(tutorial().hex==scope.name.hex,'tutorial name source changed')
        if scope.phase=='backup' then assert(current==original,'name changed during tutorial backup');return true end
        assert(bytes(r.wLinkEnemyTrainerName,11)==original,'tutorial original-name backup changed')
        if scope.copy then
            assert(copy_interval(scope.copy)and prefix(current,scope.copy.before,scope.copy.after),'tutorial name copy left its qualified interval')
        else
            assert(current==(scope.phase=='armed'and original or scope.name.hex),'tutorial borrowed name changed')
        end
        return true
    end
    local function begin_copy(site,done,source,before,after)
        assert(pair('H','L')==source and pair('D','E')==r.wPlayerName and pair('B','C')==11,'tutorial name copy operands changed')
        scope.copy={call=site.address,done=done.address,sp=emu.getregister('SP'),before=before,after=after}
    end
    local function close_hooks()for _,hook in ipairs(hooks)do event.unregisterbyid(hook)end;hooks={}end
    local ok,why=pcall(function()
        base()
        assert(bytes(p.copy.rom_offset,#p.copy.expected_hex/2,'ROM')==p.copy.expected_hex,'identity CopyData anchor differs')
        for _,name in pairs(p.names)do
            local offset=p.sites.borrow_begin.bank*0x4000+name.address-0x4000
            assert(bytes(offset,11,'ROM')==name.hex,'identity tutorial literal differs')
        end
        for _,kind in ipairs({'backup_begin','backup_done','borrow_begin','borrow_done','restore_begin','restore_done'})do
            local site=p.sites[kind]
            assert(bytes(site.rom_offset,#site.expected_hex/2,'ROM')==site.expected_hex,'identity tutorial ROM anchor differs')
            hooks[#hooks+1]=assert(event.on_bus_exec(function()
                if closed or failure or byte(r.hLoadedROMBank)~=site.bank then return end
                local success,reason=pcall(function()
                    base();assert(emu.getregister('PC')==site.address and bytes(site.address,#site.expected_hex/2)==site.expected_hex,'identity tutorial instruction changed')
                    if kind=='backup_begin'then
                        assert(not scope and bytes(r.wPlayerName,11)==original,'overlapping tutorial name borrow')
                        assert(pair('H','L')==r.wPlayerName and pair('D','E')==r.wLinkEnemyTrainerName and pair('B','C')==11,'tutorial backup operands changed')
                        scope={phase='backup',name=tutorial(),sp=emu.getregister('SP')}
                    elseif kind=='backup_done'then
                        assert(scope and scope.phase=='backup'and emu.getregister('SP')==scope.sp,'tutorial backup return lacks entry')
                        assert(bytes(r.wLinkEnemyTrainerName,11)==original,'tutorial backup is not original');scope.phase='armed'
                    elseif kind=='borrow_begin'then
                        assert(scope and scope.phase=='armed','tutorial borrow lacks verified backup');check()
                        begin_copy(site,p.sites.borrow_done,scope.name.address,original,scope.name.hex)
                    elseif kind=='borrow_done'then
                        assert(scope and scope.phase=='armed'and scope.copy and emu.getregister('SP')==scope.copy.sp
                            and bytes(r.wPlayerName,11)==scope.name.hex,'tutorial borrow return differs')
                        scope.copy=nil;scope.phase='borrowed'
                    elseif kind=='restore_begin'then
                        assert(scope and scope.phase=='borrowed','tutorial restore lacks borrow');check()
                        begin_copy(site,p.sites.restore_done,r.wLinkEnemyTrainerName,scope.name.hex,original)
                    else
                        assert(scope and scope.copy and scope.phase=='borrowed'and emu.getregister('SP')==scope.copy.sp
                            and bytes(r.wPlayerName,11)==original,'tutorial restore return differs')
                        scope=nil
                    end
                    check()
                end)
                if not success then scope=nil;failure=tostring(reason)end
            end,site.address,'slink-identity-'..kind,'System Bus'))
        end
        local function invalidate(reason)scope=nil;failure=reason end
        hooks[#hooks+1]=assert(event.onloadstate(function()invalidate('savestate load invalidated identity witness')end,'slink-identity-load'))
        hooks[#hooks+1]=assert(event.onexit(function()invalidate('Lua exit invalidated identity witness')end,'slink-identity-exit'))
    end)
    if not ok then close_hooks();error(why,0)end
    return {check=function()
        local valid,result=pcall(check)
        if not valid then scope=nil;failure=tostring(result);error(failure,0)end
        return result
    end,status=function()return {failed=failure,closed=closed,phase=scope and scope.phase or nil}end,
        close=function()closed=true;scope=nil;close_hooks()end}
end
return M
