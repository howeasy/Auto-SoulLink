-- Storage delegates delta preimage, deterministic writes, repair and flush proof.
local M={}
function M.new(options)
  local core=require('gen1_held_save_image').new(options,{
    command='storage_apply',intent='rby-storage-intent-v1',delta='rby-storage-delta-v1',
    receipt='rby-storage-receipt-v1',save_phase='storage_save',repair_phase='storage_repair',observe='storage_observe'})
  local prepare,classify,receipt=core.prepare,core.classify,core.receipt
  local function capture()
    options.owned()
    assert(options.host.status().physical_stop_verified,'owned held storage read required')
    return require('gen1_full_save').capture(options.memory,options.variant)
  end
  core.prepare=function(body,...)
    if body.cmd~='storage_observe' then return prepare(body,...) end
    return {schema='rby-storage-observe-intent-v1',body_digest=options.sha(body),point=capture()}
  end
  core.classify=function(body,intent,...)
    if body.cmd~='storage_observe' then return classify(body,intent,...) end
    assert(intent.schema=='rby-storage-observe-intent-v1' and intent.body_digest==options.sha(body),'storage read intent differs')
    local current=capture();assert(options.sha(current)==options.sha(intent.point),'storage read point changed')
    return 'after',current
  end
  core.receipt=function(body,...)
    if body.cmd=='storage_observe' then
      local intent,observed,identity=...
      assert(intent.body_digest==options.sha(body) and options.sha(capture())==options.sha(observed),'storage read changed')
      local host=options.host.status();local owner=options.owned()
      return {schema='rby-storage-observation-v1',command_id=identity.command_id,command_sequence=identity.command_sequence,
        context_generation=owner.context_generation,final_sha1=gameinfo.getromhash():lower(),point=observed,
        checkpoint=require('gen1_storage_checkpoint').capture(options.memory.profile),
        host={owner_id=host.owner_id,capability_id=host.capability_id,process_id=host.process_id,
              frame=emu.framecount(),held=true}}
    end
    local result=receipt(body,...)
    return result
  end
  return core
end
return M
