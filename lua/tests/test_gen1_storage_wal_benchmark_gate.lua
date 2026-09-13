-- TEMPORARY test-only BizHawk/.NET storage I/O measurement; no game RAM/server.
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
local G=dofile(ROOT.."/lua/tests/gatelib.lua")
local t=G.start("test_gen1_storage_wal_benchmark_gate",{no_boot=true})
package.path=ROOT.."/lua/?.lua;"..package.path
local JSON=require("json_codec")
local Clock=require("platform_clock")
local Storage=require("platform_storage")

local function read(path)
    local file=assert(io.open(path,"rb"))
    local value=file:read("*a");file:close();return value
end
local input=assert(JSON.decode(read(assert(os.getenv("SLINK_STORAGE_BENCH_INPUT")))))
assert(input.schema=="rby-bizhawk-local-storage-benchmark-input-v1" and input.samples==200)
assert(t.variant=="yellow" and input.preferred_core=="Gambatte")
local path=input.directory
assert(type(path)=="string" and #path>0 and input.atomic_path==path.."/atomic-current.bin"
    and input.small_path==path.."/wal-small.bin" and input.large_path==path.."/wal-large.bin")
assert(input.output and type(input.output)=="string")

local success,why=pcall(function()
    luanet.load_assembly("System")
    local Convert=luanet.import_type("System.Convert")
    local Encoding=luanet.import_type("System.Text.UTF8Encoding")
    local Stream=luanet.import_type("System.IO.FileStream")
    local Reader=luanet.import_type("System.IO.BinaryReader")
    local Mode=luanet.import_type("System.IO.FileMode")
    local Access=luanet.import_type("System.IO.FileAccess")
    local Share=luanet.import_type("System.IO.FileShare")
    local encoding=Encoding(false,true)
    local clock=assert(Clock.new())
    local canonical=input.canonical_document
    assert(type(canonical)=="string" and #canonical==input.source_bytes)
    assert(JSON.encode(assert(JSON.decode(canonical)))==canonical,"representative document is not canonical")
    local large=encoding:GetBytes(canonical)
    local small=Convert.FromBase64String(input.compressed_base64)
    assert(large.Length==input.source_bytes and small.Length>=1500 and small.Length<=2200)
    local large_b64=Convert.ToBase64String(large)
    local small_b64=Convert.ToBase64String(small)
    local backend=assert(Storage.new(input.atomic_path))
    local wal_small,wal_large
    local ok,result=pcall(function()
        assert(backend.sha256(canonical)==input.source_sha256,"source digest changed")
        assert(backend.replace(canonical)) -- warm target so all 200 timed calls use File.Replace
        assert(backend.read()==canonical)
        wal_small=Stream(input.small_path,Mode.CreateNew,Access.ReadWrite,Share.None)
        wal_large=Stream(input.large_path,Mode.CreateNew,Access.ReadWrite,Share.None)
        local small_reader,large_reader=Reader(wal_small),Reader(wal_large)
        local samples={atomic=JSON.array(),wal_small=JSON.array(),wal_large=JSON.array()}
        local function append_and_readback(stream,reader,data,expected,times)
            local offset=tonumber(stream.Position)
            local start=clock()
            stream:Write(data,0,data.Length)
            stream:Flush(true)
            stream.Position=offset
            local actual=reader:ReadBytes(data.Length)
            assert(actual.Length==data.Length and Convert.ToBase64String(actual)==expected,
                "append readback differs")
            stream.Position=stream.Length
            times[#times+1]=(clock()-start)*1000
        end
        for _=1,input.samples do
            local start=clock()
            local saved,error=backend.replace(canonical)
            assert(saved,error)
            assert(backend.read()==canonical,"atomic replacement readback differs")
            samples.atomic[#samples.atomic+1]=(clock()-start)*1000
            append_and_readback(wal_small,small_reader,small,small_b64,samples.wal_small)
            append_and_readback(wal_large,large_reader,large,large_b64,samples.wal_large)
        end
        local receipt={schema="rby-bizhawk-local-storage-benchmark-v1",variant=t.variant,
            rom_sha1=gameinfo.getromhash():lower(),preferred_core=input.preferred_core,
            directory=path,atomic_path=input.atomic_path,small_path=input.small_path,
            large_path=input.large_path,source_bytes=large.Length,compressed_bytes=small.Length,
            source_sha256=input.source_sha256,samples=samples}
        local wire=assert(JSON.encode(receipt))
        local file=assert(io.open(input.output..".tmp","wb"))
        file:write(wire);file:close();assert(os.rename(input.output..".tmp",input.output))
    end)
    if wal_small then pcall(function()wal_small:Dispose()end)end
    if wal_large then pcall(function()wal_large:Dispose()end)end
    backend.close()
    if not ok then error(result,0)end
end)
t.check("pinned Yellow host completed exact local storage readback benchmark",success,tostring(why))
t.finish()
