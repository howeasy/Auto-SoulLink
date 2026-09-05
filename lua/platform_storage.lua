-- Flushed atomic file replacement through BizHawk's .NET host. No game memory access.
local Identity=require("platform_identity")
local M={}

local function exception_name(error)
    local current=error
    for _=1,5 do
        local ok,name,inner=pcall(function()
            return tostring(current:GetType().FullName),current.InnerException
        end)
        if not ok then return nil end
        if not inner then return name end
        current=inner
    end
    return nil
end

function M.new(path)
    local lock
    local ok,result=pcall(function()
        assert(type(path)=="string" and #path>0,"storage path required")
        local File=luanet.import_type("System.IO.File")
        local Path=luanet.import_type("System.IO.Path")
        local Directory=luanet.import_type("System.IO.Directory")
        local Stream=luanet.import_type("System.IO.FileStream")
        local Writer=luanet.import_type("System.IO.StreamWriter")
        local Mode=luanet.import_type("System.IO.FileMode")
        local Access=luanet.import_type("System.IO.FileAccess")
        local Share=luanet.import_type("System.IO.FileShare")
        local Encoding=luanet.import_type("System.Text.UTF8Encoding")
        local Hash=luanet.import_type("System.Security.Cryptography.SHA256")
        local Bits=luanet.import_type("System.BitConverter")
        local encoding=Encoding(false,true)
        local target=tostring(Path.GetFullPath(path))
        local directory=tostring(Path.GetDirectoryName(target))
        Directory.CreateDirectory(directory)
        lock=Stream(target..".lock",Mode.OpenOrCreate,Access.ReadWrite,Share.None)
        local backend={path=target}
        function backend.close()
            if lock then lock:Dispose();lock=nil end
        end
        function backend.read()
            if not lock then return nil,"storage is closed" end
            local probe
            local read_ok,text=pcall(function()
                probe=Stream(target,Mode.Open,Access.Read,Share.Read)
                if probe.Length>4*1024*1024 then error("state file exceeds byte bound",0) end
                probe:Dispose();probe=nil
                return tostring(File.ReadAllText(target,encoding))
            end)
            if probe then pcall(function() probe:Dispose() end) end
            if read_ok then return text end
            local name=exception_name(text)
            if name=="System.IO.FileNotFoundException" then return nil,"missing" end
            return nil,"read failed: "..tostring(text)
        end
        function backend.sha256(text)
            local hash=Hash.Create()
            local hash_ok,value=pcall(function()
                return tostring(Bits.ToString(hash:ComputeHash(encoding:GetBytes(text)))):gsub("-",""):lower()
            end)
            hash:Dispose()
            if not hash_ok then error(value,0) end
            return value
        end
        function backend.replace(text)
            if not lock then return false,"storage is closed" end
            if type(text)~="string" or #text>4*1024*1024 then return false,"invalid state file bytes" end
            local nonce,reason=Identity.new_nonce()
            if not nonce then return false,reason end
            local temporary=target..".tmp-"..nonce
            local stream,writer
            local write_ok,error=pcall(function()
                stream=Stream(temporary,Mode.CreateNew,Access.Write,Share.None)
                writer=Writer(stream,encoding)
                writer:Write(text)
                writer:Flush()
                stream:Flush(true)
                writer:Dispose(); writer=nil; stream=nil
                if File.Exists(target) then File.Replace(temporary,target,nil)
                else File.Move(temporary,target) end
            end)
            if writer then pcall(function() writer:Dispose() end) end
            if stream then pcall(function() stream:Dispose() end) end
            if not write_ok then
                pcall(function() File.Delete(temporary) end)
                return false,"atomic replacement failed: "..tostring(error)
            end
            return true
        end
        return backend
    end)
    if not ok then
        if lock then pcall(function() lock:Dispose() end) end
        return nil,"durable file API unavailable: "..tostring(result)
    end
    return result
end
return M
