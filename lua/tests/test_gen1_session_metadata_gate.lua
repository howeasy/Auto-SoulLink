-- Read the actual emulator ROM hash and obtain independent OS-backed session nonces.
local ROOT=SLINK_ROOT or os.getenv('SLINK_ROOT')
local G=dofile(ROOT..'/lua/tests/gatelib.lua')
local t=G.start("test_gen1_session_metadata_gate",{no_boot=true})
package.path=ROOT..'/lua/?.lua;'..ROOT..'/data/games/gen1_rby/?.lua;'..package.path
local S=require('gen1_session')
local metadata,reason=S.metadata(t.variant)
t.check('complete ROM hash matches canonical profile',metadata~=nil,reason)
if metadata then
    t.log('rom_sha1='..metadata.final_rom_sha1)
    t.check('clean cartridge has no patch capabilities',not metadata.capabilities.panel and
        not metadata.capabilities.sfx and not metadata.capabilities.pc_trade)
end
local seen={}
for i=1,32 do
    local nonce,error=S.new_nonce()
    t.check('secure nonce '..i,nonce~=nil and not seen[nonce],error)
    if nonce then seen[nonce]=true end
end
t.finish()
