-- Read-only identity of this running host, for isolated test probes only.
local M={}
function M.capture(requested_core)
    local main_form=nil
    local ok,host=pcall(function()
        luanet.load_assembly("System")
        luanet.load_assembly("System.Windows.Forms")
        local Application=luanet.import_type("System.Windows.Forms.Application")
        local File=luanet.import_type("System.IO.File")
        local SHA256=luanet.import_type("System.Security.Cryptography.SHA256")
        local BitConverter=luanet.import_type("System.BitConverter")
        local Process=luanet.import_type("System.Diagnostics.Process")
        local function fingerprint(path)
            local algorithm=SHA256.Create()
            local value=BitConverter.ToString(algorithm:ComputeHash(File.ReadAllBytes(path)))
            algorithm:Dispose()
            return {path=tostring(path),sha256=tostring(value):gsub("-",""):lower()}
        end
        local iterator=Application.OpenForms:GetEnumerator()
        while iterator:MoveNext() do
            local form=iterator.Current
            if tostring(form:GetType().FullName)=="BizHawk.Client.EmuHawk.MainForm" then main_form=form;break end
        end
        if not main_form then error("Private process MainForm was not found") end
        local core_type=main_form.Emulator:GetType()
        local assembly=core_type.Assembly
        local result={available=true,core_type=tostring(core_type.FullName),
            core_assembly=tostring(assembly.FullName),native_modules={}}
        local hash_ok,assembly_file=pcall(fingerprint,assembly.Location)
        result.core_assembly_file=hash_ok and assembly_file or {path=tostring(assembly.Location),error=tostring(assembly_file)}
        result.requested_core=requested_core
        result.matches_requested_core=requested_core=="mGBA"
            and result.core_type=="BizHawk.Emulation.Cores.Nintendo.GBA.MGBAHawk"
        local modules_ok,modules_error=pcall(function()
            local process=Process.GetCurrentProcess()
            result.process_id=process.Id
            local modules=process.Modules:GetEnumerator()
            while modules:MoveNext() do
                local module=modules.Current
                if tostring(module.ModuleName):lower():find("mgba",1,true) then
                    result.native_modules[#result.native_modules+1]=fingerprint(module.FileName)
                end
            end
        end)
        result.module_query_available=modules_ok
        if not modules_ok then result.module_query_error=tostring(modules_error) end
        return result
    end)
    return ok and host or {available=false,error=tostring(host)},main_form
end
return M
