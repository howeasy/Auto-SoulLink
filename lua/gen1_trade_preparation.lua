-- Read-only preparation for a paired native trade. No frames or RAM writes.
-- Ownership/hold callbacks are supplied by the runtime; a snapshot is not authority.
local JSON=require("json_codec")
local Canonical=require("journal_document")
local Receipts=require("gen1_command_receipts")
local Codec=require("gen1_party_codec")
local M={SCHEMA="rby-trade-checkpoint-v1",INTENT="rby-trade-preparation-intent-v1"}
local function copy(v)return assert(JSON.decode(assert(JSON.encode(v))))end
local function same(a,b)return assert(Canonical.encode(a))==assert(Canonical.encode(b))end

function M.capture(mem,manifest,read_only_query)
    assert(manifest.schema=="gen1-native-trade-build-v1" and manifest.test_probe==JSON.null,
        "qualified native artifact required")
    assert(gameinfo.getromhash():lower()==manifest.final_sha1 and (mem.isPartyWriteSafe()
        or read_only_query==true and require("gen1_receptionist_client").query(mem,manifest)),
        "trade preparation requires the admitted overworld checkpoint")
    local layout=assert(mem.profile.sram_box_layout)
    assert(layout.box_len==1122 and mem.GENERATION==1,"RBY box layout required")
    local function read(p,n,domain)
        local out={};for i=0,n-1 do out[#out+1]=memory.read_u8(p+i,domain or "System Bus")end
        return mem.bytesToHex(out)
    end
    -- Retain physical storage, not a caller-supplied list that could omit a key.
    assert(mem.storedBoxKeys())
    return {schema=M.SCHEMA,final_sha1=manifest.final_sha1,
        party=assert(Receipts.party_snapshot(mem,manifest.variant)),
        party_storage_hex=read(manifest.readback.party.address,404),
        name_hex=read(manifest.ram.wPlayerName,11),map=memory.read_u8(manifest.ram.wCurMap,"System Bus"),
        current_box=memory.read_u8(mem.CURRENT_BOX_NUM_ADDR,"System Bus"),
        active_box_hex=read(mem.BOX_COUNT_ADDR,1122),cart_hex=read(0,0x8000,"CartRAM")}
end

function M.new(options)
    local mem,manifest=options.memory,copy(options.manifest)
    assert(type(options.authorize)=="function" and type(options.context_generation)=="function"
        and type(options.sha256)=="function","owned preparation/context/hash callbacks required")
    assert(options.player=="a" or options.player=="b","preparation player required")
    local function sha(v)return options.sha256(assert(Canonical.encode(v)))end
    local function guard(body,identity,intent)
        assert(options.authorize("prepare",copy(body),copy(identity),intent and copy(intent))==true,
            "current trade preparation authority unavailable")
        assert(body.cmd=="native_trade_prepare" and body.player==options.player
            and body.payload.schema=="rby-native-prepare-v1"
            and sha(body.payload.proposal)==body.proposal_digest,"paired preparation command required")
        local own=body.payload.proposal.participants[options.player]
        assert(own.context.context_generation==options.context_generation(),"preparation context changed")
        if intent then
            assert(intent.schema==M.INTENT and intent.command_id==identity.command_id
                and intent.command_sequence==identity.command_sequence and intent.body_digest==sha(body)
                and intent.context_generation==options.context_generation(),"prepared command/context changed")
        end
        local observed=M.capture(mem,manifest)
        assert(same(observed.party.party,own.snapshot.party)
            and observed.party.save_id==own.context.save_identity.ot_id
            and observed.party.save_name==own.context.save_identity.trainer_name
            and observed.name_hex==body.payload.own_name_hex,"prepared party/save differs from proposal")
        local peer=body.payload.proposal.participants[options.player=="a" and "b" or "a"]
        local party={};for _,blob in ipairs(observed.party.party)do party[#party+1]=assert(mem.hexToBytes(blob))end
        assert(Codec.prepareExchange(party,manifest.variant,own.slot,
            assert(mem.hexToBytes(peer.snapshot.party[peer.slot+1])),own.key,peer.key,
            body.payload.evolved_species,assert(mem.storedBoxKeys())))
        if intent then assert(same(observed,intent.checkpoint),"trade checkpoint changed after preparation")end
        return observed
    end
    local self={}
    function self.prepare(body,identity)
        local checkpoint=guard(body,identity)
        return {schema=M.INTENT,command_id=identity.command_id,command_sequence=identity.command_sequence,
            body_digest=sha(body),context_generation=options.context_generation(),checkpoint=checkpoint}
    end
    function self.classify(body,intent,identity)return "after",guard(body,identity,intent)end
    function self.apply()error("read-only preparation has no physical apply",0)end
    function self.receipt(body,intent,observed,identity)
        assert(same(guard(body,identity,intent),observed),"preparation receipt checkpoint changed")
        return {schema="rby-native-ready-v1",command_id=identity.command_id,
            command_sequence=identity.command_sequence,transaction_id=body.transaction_id,
            proposal_digest=body.proposal_digest,context_generation=intent.context_generation,
            checkpoint=copy(observed)}
    end
    return self
end
return M
