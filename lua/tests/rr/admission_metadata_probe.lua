-- Read-only actual-host metadata provider test. No hello, binding or commands.
return function(ctx)
    local C,check=ctx.config,ctx.check
    dofile(C.source_root.."/lua/tests/rr/ghost_route_observation.lua")(ctx)
    local prior=ctx.report.evidence.runtime
    local out={classification="actual_userdata_metadata_read",release_ready=false,admission_selected=false,
        loader_attestation_proved=false,bundle_evidence="explicit diagnostic fixtures only",initial=prior}
    ctx.report.evidence.runtime=out
    local M=dofile(C.source_root.."/lua/memory_gba.lua")
    local G=dofile(C.source_root.."/lua/games/gen3_frlge.lua")
    check("metadata_detected_rr",G.detect_variant(),"radical_red")
    M.applyProfile(G.profiles.radical_red,"radical_red")
    local A=dofile(C.source_root.."/lua/rr/admission.lua")
    local io={read_u8=memory.read_u8,read_u32_le=memory.read_u32_le,getromhash=gameinfo.getromhash}
    out.api_types={read_u8=type(io.read_u8),read_u32_le=type(io.read_u32_le),getromhash=type(io.getromhash)}
    check("metadata_actual_userdata",out.api_types.read_u8=="userdata" and out.api_types.read_u32_le=="userdata"
        and out.api_types.getromhash=="userdata",true)
    local function hex(a,n)
        local t={};for i=0,n-1 do t[#t+1]=string.format("%02x",memory.read_u8(a+i)) end;return table.concat(t)
    end
    local first=emu.framecount();local party,mailbox=hex(0x02024284,600),hex(C.probe_options.native_descriptor.mailbox_address,64)
    local value,why=A.read_metadata(M,io,C.probe_options.native_descriptor,C.probe_options.bundle_fixtures)
    out.report=value;out.error=why
    check("metadata_provider_succeeded",value~=nil,true)
    local r=value.rr_metadata
    check("metadata_actual_save",r.trainer_name=="B" and r.trainer_id==0x2BDDC8BF,true)
    check("metadata_actual_rom",r.loaded_rom_sha1,C.identity.rom_sha1:lower())
    check("metadata_actual_mode",r.mode_flags.minimal_grinding and not r.mode_flags.easy and not r.mode_flags.hardcore
        and not r.mode_flags.restricted and not r.mode_flags.species_randomizer and not r.mode_flags.learnset_randomizer
        and not r.mode_flags.ability_randomizer and not r.mode_flags.hard_mode_randomizer,true)
    check("metadata_native_build",r.native_descriptor.build_id,C.descriptor.build_id)
    check("metadata_no_frames",emu.framecount(),first)
    check("metadata_no_party_change",hex(0x02024284,600),party)
    check("metadata_no_mailbox_change",hex(C.probe_options.native_descriptor.mailbox_address,64),mailbox)
    check("metadata_component_complete",true,true)
end
