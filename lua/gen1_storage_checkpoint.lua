-- Read-only refusal evidence. These bytes never authorize a write.
local M={}
function M.capture(profile)
  local JSON=require('json_codec');local p=assert(profile.write_safe)
  local pc,sp=emu.getregister('PC'),emu.getregister('SP')
  assert(type(pc)=='number' and pc%1==0 and pc>=0 and pc<=65535,'bounded PC required')
  assert(type(sp)=='number' and sp%1==0 and sp>=0 and sp<=65532,'bounded stack read required')
  local point={pc=pc,sp=sp,rom=JSON.object(),system=JSON.object()}
  local function read(address,domain,target)
    local value=memory.read_u8(address,domain)
    assert(type(value)=='number' and value%1==0 and value>=0 and value<=255,'complete checkpoint byte required')
    target[tostring(address)]=value
  end
  for _,address in ipairs({p.irq_vector,p.overworld_loop,p.overworld_loop_less_delay})do
    for i=0,2 do read(address+i,'ROM',point.rom)end
  end
  for i=0,7 do read(p.delay_frame+i,'ROM',point.rom)end
  for _,address in ipairs({profile.BATTLE_FLAG_ADDR,profile.JOY_IGNORE_ADDR,profile.FONT_LOADED_ADDR,
      p.link_state,p.serial_status,p.entering_cable_club,p.vblank_flag})do read(address,'System Bus',point.system)end
  if p.printer_open then read(p.printer_open,'System Bus',point.system)end
  for i=0,3 do read(sp+i,'System Bus',point.system)end
  return point
end
return M
