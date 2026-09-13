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
    local Mode=luanet.import_type("System.IO.FileMode")
    local Access=luanet.import_type("System.IO.FileAccess")
    local Share=luanet.import_type("System.IO.FileShare")
    local encoding=Encoding(false,true)
    local clock=assert(Clock.new())
    local canonical=input.canonical_document
    assert(type(canonical)=="string" and #canonical==input.source_bytes,
        "source text byte count differs: actual="..tostring(type(canonical)=="string" and #canonical)
            .." expected="..tostring(input.source_bytes))
    assert(JSON.encode(assert(JSON.decode(canonical)))==canonical,"representative document is not canonical")
    local large=encoding:GetBytes(canonical)
    local small=Convert.FromBase64String(input.compressed_base64)
    assert(type(input.source_bytes)=="number" and input.source_bytes==74352
        and type(input.compressed_bytes)=="number" and input.compressed_bytes>=1500
        and input.compressed_bytes<=2200,"invalid trusted record counts: source="..tostring(input.source_bytes)
            .." compressed="..tostring(input.compressed_bytes))
    local large_b64=tostring(Convert.ToBase64String(large))
    local small_b64=tostring(Convert.ToBase64String(small))
    assert(small_b64==input.compressed_base64,
        "compressed byte[] roundtrip differs: host_type="..type(small).." actual_b64="..#small_b64
            .." expected_b64="..tostring(type(input.compressed_base64)=="string" and #input.compressed_base64))
    local backend=assert(Storage.new(input.atomic_path))
    local wal_small,wal_large
    local ok,result=pcall(function()
        assert(backend.sha256(canonical)==input.source_sha256,"source digest changed")
        assert(backend.sha256(large_b64)==input.source_base64_sha256,
            "source byte[] base64 digest differs: host_type="..type(large).." b64_bytes="..#large_b64)
        assert(backend.replace(canonical)) -- warm target so all 200 timed calls use File.Replace
        assert(backend.read()==canonical)
        wal_small=Stream(input.small_path,Mode.CreateNew,Access.ReadWrite,Share.None)
        wal_large=Stream(input.large_path,Mode.CreateNew,Access.ReadWrite,Share.None)
        local samples={atomic=JSON.array(),wal_small=JSON.array(),wal_large=JSON.array()}
        local function append_and_readback(stream,data,count,expected,times)
            local offset=tonumber(stream.Position)
            local start=clock()
            stream:Write(data,0,count)
            stream:Flush(true)
            stream.Position=offset
            -- Use the same byte[] and integer count accepted by FileStream.Write.
            -- The earlier one-argument readback call failed NLua conversion on
            -- this pinned host; FileStream.Read matches Write's three-arg API.
            local read_ok,bytes_read=pcall(function()return stream:Read(data,0,count)end)
            assert(read_ok,"FileStream.Read(byte[],int,int) failed: buffer_type="..type(data)
                .." count="..tostring(count).." error="..tostring(bytes_read))
            assert(tonumber(bytes_read)==count,
                "FileStream.Read byte count differs: buffer_type="..type(data)
                    .." count="..tostring(count).." returned_type="..type(bytes_read)
                    .." returned="..tostring(bytes_read))
            assert(tostring(Convert.ToBase64String(data))==expected,"append readback differs")
            stream.Position=stream.Length
            times[#times+1]=(clock()-start)*1000
        end
        for _=1,input.samples do
            local start=clock()
            local saved,error=backend.replace(canonical)
            assert(saved,error)
            assert(backend.read()==canonical,"atomic replacement readback differs")
            samples.atomic[#samples.atomic+1]=(clock()-start)*1000
            append_and_readback(wal_small,small,input.compressed_bytes,small_b64,samples.wal_small)
            append_and_readback(wal_large,large,input.source_bytes,large_b64,samples.wal_large)
        end
        local receipt={schema="rby-bizhawk-local-storage-benchmark-v1",variant=t.variant,
            rom_sha1=gameinfo.getromhash():lower(),preferred_core=input.preferred_core,
            directory=path,atomic_path=input.atomic_path,small_path=input.small_path,
            large_path=input.large_path,source_bytes=input.source_bytes,compressed_bytes=input.compressed_bytes,
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
