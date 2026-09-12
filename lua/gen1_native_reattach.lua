-- Start-of-script native reattach read. Before the first frame of a reattached native client
-- may run, the physical arming state is read under the bounded owner's hold and handed to the
-- server for classification: an APPLY-armed overlay word in WRAM (byte4==1, byte5==5,
-- byte6~=byte7) would run the original trade routine on the very next free frame
-- (trade_service.asm bridge), unowned. This reads, it never writes, never advances a frame, and
-- never decides anything; the classifier (server) does.
local JSON=require("json_codec")
local M={SCHEMA="rby-native-reattach-read-v1"}
local function copy(v)return assert(JSON.decode(assert(JSON.encode(v))))end
-- options: host (bounded owner, must be held with the physical stop verified), memory (profile),
-- manifest (companion build), lease (function returning the persisted native lease document).
function M.read(options)
    assert(type(options)=="table" and type(options.host)=="table" and type(options.host.status)=="function","bounded host required")
    local status=options.host.status()
    assert(type(status)=="table" and status.held==true and status.physical_stop_verified==true,
        "native reattach read requires the held bounded owner before any frame")
    local manifest=options.manifest
    assert(type(manifest)=="table" and manifest.schema=="gen1-native-trade-build-v1" and type(manifest.foreground)=="table",
        "qualified foreground layout required")
    assert(gameinfo.getromhash():lower()==manifest.final_sha1,"native artifact changed")
    local fg=manifest.foreground
    local frame=emu.framecount()
    local word={}
    for i=0,15 do word[#word+1]=memory.read_u8(fg.overlay+i,"System Bus")end
    local published=word[1]==0x53 and word[2]==0x4c and word[3]==0x54 and word[4]==0x31 and word[5]==1
    local lease=assert(options.lease(),"persisted native lease required")
    assert(lease.schema=="gen1-native-trade-lease-v1","invalid persisted native lease")
    local result={schema=M.SCHEMA,frame=frame,pc=emu.getregister("PC"),sp=emu.getregister("SP"),
        bank=memory.read_u8(manifest.ram.hLoadedROMBank,"System Bus"),
        overlay_hex=options.memory.bytesToHex(word),published=published,
        phase=published and word[6] or JSON.null,
        armed=published and word[6]==5 and word[7]~=word[8],
        done=published and word[6]==7 and word[7]==word[8],
        token_hex=published and options.memory.bytesToHex({word[13],word[14],word[15],word[16]}) or JSON.null,
        lease={phase=lease.phase,command_id=lease.command_id or JSON.null,intent_digest=lease.intent_digest or JSON.null,
            token_hex=lease.intent and lease.intent.token_hex or JSON.null,receipt=lease.receipt~=nil}}
    assert(emu.framecount()==frame,"native reattach read advanced a frame")
    return copy(result)
end
return M
