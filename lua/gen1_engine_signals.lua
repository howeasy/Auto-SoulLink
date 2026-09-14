-- Read-only source-qualified engine hooks. The owner must flush at each held
-- frame boundary before authorizing another frame; this module grants none.
local JSON=require("json_codec")
local Data=require("gen1_engine_signal_data")
local Full=require("gen1_full_save")
local M={SCHEMA="rby-engine-signals-v1",MAX_PENDING=32,PROJECTION="cartram-0498-8000-v1"}
local function copy(value)return assert(JSON.decode(assert(JSON.encode(value))))end
local function equal(a,b)return JSON.encode(a)==JSON.encode(b)end
local function hex(address,count,domain)
    local out={};for i=0,count-1 do out[#out+1]=string.format("%02X",memory.read_u8(address+i,domain or "System Bus"))end
    return table.concat(out)
end
function M.new(options)
    assert(type(options.owned)=="function" and type(options.held)=="function" and options.journal,
        "owned engine observation service required")
    local profile=assert(Data.titles[options.variant]);local addresses=profile.addresses
    local owner=copy(options.owned());local final=assert(options.final_sha1)
    local hooks,pending={},JSON.array();local failure,closed=nil,false
    local self={}
    local function check()
        assert(not closed and not failure,failure or "engine observation is closed")
        assert(gameinfo.getromhash():lower()==final and equal(owner,options.owned()),"engine observation context changed")
    end
    local function point(kind)
        if kind=="save_witness"then
            -- The persistent save is CartRAM[0x0498,0x8000): everything after the three sprite work
            -- buffers (ram/sram.asm). Digest that hex projection with the journal's own sha256.
            local image=Full.capture(nil,options.variant)
            return {digest=options.journal.store.backend.sha256(image.cart_hex:sub(0x498*2+1)),projection=M.PROJECTION,
                save_file_status=image.save_status}
        end
        if kind=="bag_received"then
            return {bag_hex=hex(addresses.wNumBagItems,42),trainer_hex=hex(addresses.wPlayerName,11),
                player_id_hex=hex(addresses.wPlayerID,2),destination=emu.getregister("H")*256+emu.getregister("L"),flags=emu.getregister("F"),
                item=memory.read_u8(addresses.wCurItem,"System Bus"),quantity=memory.read_u8(addresses.wItemQuantity,"System Bus")}
        end
        return {party_hex=hex(addresses.wPartyDataStart,404),trainer_hex=hex(addresses.wPlayerName,11),
            player_id_hex=hex(addresses.wPlayerID,2),map_id=memory.read_u8(addresses.wCurMap,"System Bus"),
            battle_flag=memory.read_u8(addresses.wIsInBattle,"System Bus"),
            active_slot=memory.read_u8(addresses.wPlayerMonNumber,"System Bus"),
            battle_hp=memory.read_u16_be(addresses.wBattleMonHP,"System Bus"),
            battle_species=memory.read_u8(addresses.wBattleMonSpecies,"System Bus"),
            which=memory.read_u8(addresses.wWhichPokemon,"System Bus"),
            mon_location=memory.read_u8(addresses.wMonDataLocation,"System Bus"),
            cur_species=memory.read_u8(addresses.wCurPartySpecies,"System Bus"),
            cur_level=memory.read_u8(addresses.wCurEnemyLevel,"System Bus")}
    end
    local function close_hooks()
        for _,id in ipairs(hooks)do event.unregisterbyid(id)end
        hooks={}
    end
    local ok,why=pcall(function()
        check()
        for _,site in pairs(profile.sites)do
            assert(hex(site.rom_offset,#site.expected_hex/2,"ROM")==site.expected_hex,"engine observation ROM anchor differs")
        end
        for kind,site in pairs(profile.sites)do
            local id=event.on_bus_exec(function()
                if closed or failure then return end
                if memory.read_u8(addresses.hLoadedROMBank,"System Bus")~=site.bank then return end
                if kind=="bag_received"then
                    local item=memory.read_u8(addresses.wCurItem,"System Bus")
                    if emu.getregister("H")*256+emu.getregister("L")~=addresses.wNumBagItems or math.floor(emu.getregister("F")/16)%2~=1
                        or item<1 or item>4 then return end
                end
                local observed,reason=pcall(function()
                    check();assert(#pending<M.MAX_PENDING,"engine signal buffer is full; recovery required")
                    assert(emu.getregister("PC")==site.address+(site.capture_offset or 0),"engine callback PC differs")
                    assert(hex(site.address,#site.expected_hex/2)==site.expected_hex,"engine signal bank/bytes differ")
                    local frame=emu.framecount()
                    local signal={kind=kind,frame=frame,pc=site.address+(site.capture_offset or 0),bank=site.bank,sp=emu.getregister("SP"),point=point(kind)}
                    check();assert(frame==emu.framecount(),"engine signal frame changed")
                    pending[#pending+1]=signal
                    -- Flush the witnessed save to .SaveRAM now (BizHawk 2.11.1 client.saveram), so an abrupt close
                    -- after the ack cannot leave the acknowledged checkpoint only in emulator memory.
                    if kind=="save_witness" and type(client)=="table" and client.saveram then pcall(client.saveram) end
                end)
                if not observed then failure=tostring(reason)end
            end,site.address+(site.capture_offset or 0),"SLink-engine-"..kind,"System Bus")
            assert(id,"engine signal callback registration failed");hooks[#hooks+1]=id
        end
    end)
    if not ok then close_hooks();error(why,0)end
    function self:peek()
        assert(not closed and not failure,failure or "engine observation is closed")
        assert(options.held()==true,"engine signals must be read under a held frame boundary")
        if options.fast_path and #pending==0 then return JSON.array()end
        check();assert(options.held()==true,"engine signals must be read under a held frame boundary")
        return copy(pending)
    end
    function self:drain(expected)
        check();assert(options.held()==true and equal(expected,pending),"engine signal drain differs from persisted observations")
        pending=JSON.array();return true
    end
    -- Polled battle state for the free loop (read-only, between frames): wIsInBattle and wCurOpponent
    -- (trainer class + 200 while a trainer battle is being set up; the wild species otherwise).
    function self:probe()
        assert(not closed and not failure,failure or "engine observation is closed")
        assert(options.held()==true,"engine probe must be read under a held frame boundary")
        if not options.fast_path then check()end
        return {battle=memory.read_u8(addresses.wIsInBattle,"System Bus"),opponent=memory.read_u8(addresses.wCurOpponent,"System Bus")}
    end
    function self:batch(signals,sequence)
        check();assert(options.held()==true and type(sequence)=="number" and sequence%1==0 and sequence>=1,
            "held engine batch sequence required")
        assert(JSON.kind(signals)=="array" and #signals>0 and #signals<=M.MAX_PENDING,"bounded engine batch required")
        return {schema=M.SCHEMA,source_sha256=Data.sha256,variant=options.variant,
            context_generation=owner.context_generation,final_sha1=final,sequence=sequence,signals=copy(signals)}
    end
    function self:flush()
        check();assert(options.held()==true,"engine signals must publish under a held frame boundary")
        if #pending==0 then return false end
        local frame=emu.framecount();local state=assert(options.journal.store:read());local baseline=state.observation
        local cursor=baseline.engine_signals
        if cursor then assert(equal(cursor.context,owner),"engine signal journal context changed")end
        local sequence=cursor and cursor.sequence or 0
        assert(type(sequence)=="number" and sequence%1==0 and sequence>=0 and sequence<9007199254740991,
            "engine signal sequence exhausted")
        local payload={event="engine_signals",payload={schema=M.SCHEMA,source_sha256=Data.sha256,
            variant=options.variant,context_generation=owner.context_generation,final_sha1=final,
            sequence=sequence+1,signals=copy(pending)}}
        baseline.engine_signals={context=copy(owner),sequence=sequence+1}
        local published,reason=pcall(function()
            assert(options.journal:append(payload,baseline))
            check();assert(options.held()==true and frame==emu.framecount(),"engine signal owner changed during publication")
        end)
        if not published then failure=tostring(reason);error(failure,0)end
        pending=JSON.array();return true
    end
    function self:status()return {failed=failure,pending=#pending,closed=closed}end
    function self:close()closed=true;close_hooks()end
    return self
end
return M
