-- Real .NET UTF8/SHA256/flush/atomic-replace APIs on the pinned emulator host.
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
local G=dofile(ROOT.."/lua/tests/gatelib.lua")
local t=G.start("test_platform_storage_gate",{no_boot=true})
package.path=ROOT.."/lua/?.lua;"..package.path
local Storage=require("platform_storage")
local nonce=assert(require("platform_identity").new_nonce())
local path=ROOT.."/patch/build/storage-"..nonce.."/state.json"
local backend,reason=Storage.new(path)
t.check("platform storage available",backend~=nil,reason)
if not backend then t.finish() end
local missing,error=backend.read()
t.check("missing file distinguished from unreadable file",missing==nil and error=="missing",error)
t.check("SHA256 bytes agree with published empty vector",backend.sha256("")=="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
local first='{"text":"é😀","revision":1}'
local wrote,write_error=backend.replace(first)
t.check("first flushed publication",wrote,write_error)
t.check("UTF8 roundtrip",backend.read()==first)
local second='{"revision":2,"text":"replacement"}'
local changed,change_error=backend.replace(second)
t.check("atomic overwrite",changed,change_error)
local duplicate=Storage.new(path)
t.check("second writer cannot acquire the same file",duplicate==nil)
backend.close()
local reopened=assert(Storage.new(path))
t.check("new reader sees complete replacement",reopened.read()==second)
reopened.close()
local JSON=require("json_codec")
local Store=require("state_store")
local Journal=require("client_journal")
local binding={run_id=nonce,player="a",save_id="0000",rom_sha1=gameinfo.getromhash():lower()}
local ledger_path=ROOT.."/patch/build/storage-"..nonce.."/ledger.json"
local function open_ledger()
    local store=assert(Store.open(assert(Storage.new(ledger_path)),binding,Journal.initial()))
    return store,assert(Journal.open(store))
end
local lifecycle_ok,lifecycle_error=pcall(function()
luanet.load_assembly("System")
local watch=luanet.import_type("System.Diagnostics.Stopwatch").StartNew()
local store,journal=open_ledger()
local operation=assert(journal:append({event="capture",key="1234:5678:99"}))
store:close()
store,journal=open_ledger()
t.check("outbox identity survives a real close/reopen",journal:pending_events()[1].operation_id==operation)
local command_id=assert(require("platform_identity").new_nonce())
t.check("response durably stages command",journal:accept_response(operation,JSON.array({
    {command_id=command_id,command_sequence=1,body={cmd="box_mon",key="1234:5678:99"}}})))
store:close()
store,journal=open_ledger()
t.check("unexecuted command survives reopen",journal:pending_commands()[1].command_id==command_id)
t.check("explicit test receipt stages its ACK",journal:complete_command(command_id,"NACK",{reason="test executor did not mutate game"}))
store:close()
store,journal=open_ledger()
local receipt_event=journal:pending_events()[1]
t.check("receipt and ACK event survive together",receipt_event.payload.event=="command_ack" and #journal:pending_commands()==0)
t.check("server receipt confirmation advances durable floor",journal:accept_response(receipt_event.operation_id,JSON.array()))
local ids=assert(journal:append_many(JSON.array({{event="capture",key="1234:5678:99"},
    {event="faint",key="1234:5678:99"}}),{frame=123,detector="explicit batch fixture"}))
store:close();store,journal=open_ledger()
local batch_state=assert(store:read())
t.check("whole frame batch and detector baseline survive real reopen",#batch_state.outbox==2
    and batch_state.outbox[1].operation_id==ids[1] and batch_state.outbox[2].operation_id==ids[2]
    and ids[1]~=ids[2] and batch_state.observation.frame==123
    and batch_state.observation.detector=="explicit batch fixture")
t.check("batch operations retain individual FIFO acknowledgements",journal:accept_response(ids[1],JSON.array())
    and journal:accept_response(ids[2],JSON.array()) and #journal:pending_events()==0)
store:close()
watch:Stop()
t.log("store_lifecycle_wall_ms="..tostring(watch.ElapsedMilliseconds))
end)
t.check("complete durable lifecycle",lifecycle_ok,tostring(lifecycle_error))
t.log("storage_path="..path)
t.finish()
