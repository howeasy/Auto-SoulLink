-- Source-pinned BizHawk SaveRAM file flush/readback, independent of cartridge.
-- Caller supplies private current control authority and its isolated save path.
-- No frames, core reset/load, savestate, or gameplay permission is granted here.
local M={SCHEMA="slink-saveram-file-v1"}
function M.new(options)
    assert(type(options.authorize)=="function","private save-file authority required")
    assert(options.path==nil or type(options.path)=="string" and #options.path>0 and #options.path<=4096,
        "explicit SaveRAM path must be a bounded string")
    local profile=assert(require("platform_execution").supported_profile(options.profile))
    luanet.load_assembly("System")
    luanet.load_assembly("System.Windows.Forms")
    luanet.load_assembly("BizHawk.Client.Common")
    local Application=luanet.import_type("System.Windows.Forms.Application")
    local Object=luanet.import_type("System.Object")
    local Enum=luanet.import_type("System.Enum")
    local Flags=luanet.import_type("System.Reflection.BindingFlags")
    local Process=luanet.import_type("System.Diagnostics.Process")
    local File=luanet.import_type("System.IO.File")
    local Path=luanet.import_type("System.IO.Path")
    local Stream=luanet.import_type("System.IO.FileStream")
    local Mode=luanet.import_type("System.IO.FileMode")
    local Access=luanet.import_type("System.IO.FileAccess")
    local Share=luanet.import_type("System.IO.FileShare")
    local Hash=luanet.import_type("System.Security.Cryptography.SHA256")
    local Bits=luanet.import_type("System.BitConverter")
    local Paths=luanet.import_type("BizHawk.Client.Common.PathEntryExtensions")
    local flags=Enum.Parse(luanet.ctype(Flags),"Instance, NonPublic")
    local main
    local forms=Application.OpenForms:GetEnumerator()
    while forms:MoveNext()do
        local form=forms.Current
        if tostring(form:GetType().FullName)=="BizHawk.Client.EmuHawk.MainForm"then
            assert(not main,"multiple emulator main forms");main=form
        end
    end
    assert(main and not main.InvokeRequired,"between-frame emulator UI thread required")
    local core=main.Emulator
    local function hash(raw)
        local algorithm=Hash.Create()
        local ok,result=pcall(function()return tostring(Bits.ToString(algorithm:ComputeHash(raw))):gsub("-",""):lower()end)
        algorithm:Dispose();assert(ok,result);return result
    end
    local process=Process.GetCurrentProcess()
    assert(client.getversion()==profile.emulator_version
        and hash(File.ReadAllBytes(process.MainModule.FileName))==profile.emulator_sha256
        and tostring(core:GetType().FullName)==profile.core_type
        and hash(File.ReadAllBytes(core:GetType().Assembly.Location))==profile.core_assembly_sha256,
        "save-file host profile differs")
    local get_property=luanet.get_method_bysig(main:GetType(),"GetProperty","System.String","System.Reflection.BindingFlags")
    local property=assert(get_property("Config",flags))
    local get_config=luanet.get_method_bysig(property,"GetValue","System.Object")
    local initial_config=get_config(main)
    -- An owner may bind the current configured path instead of supplying it.
    -- Both modes freeze it once and recheck it before and after every flush.
    local target=tostring(Path.GetFullPath(options.path or Paths.SaveRamAbsolutePath(
        initial_config.PathEntries,main.Game,main.MovieSession.Movie)))
    if options.directory~=nil then
        assert(type(options.directory)=="string" and #options.directory>0 and #options.directory<=4096,
            "explicit SaveRAM directory must be a bounded string")
        local expected=tostring(Path.GetFullPath(options.directory)):gsub("[/\\]+$",""):lower()
        local actual=tostring(Path.GetDirectoryName(target)):gsub("[/\\]+$",""):lower()
        assert(actual==expected,"host SaveRAM directory differs from the isolated launch directory")
    end
    local flush=luanet.get_method_bysig(main,"FlushSaveRAM","System.Boolean")
    local self={path=target}
    local function guard()
        assert(options.authorize()==true and Object.ReferenceEquals(core,main.Emulator)
            and not main.IsDisposed and not main.InvokeRequired,"save-file physical authority changed")
        local config=get_config(main)
        local actual=tostring(Path.GetFullPath(Paths.SaveRamAbsolutePath(config.PathEntries,main.Game,main.MovieSession.Movie)))
        assert(actual:lower()==target:lower(),"host SaveRAM destination differs from the admitted isolated path")
    end
    guard()
    function self:flush(expected_hex)
        assert(type(expected_hex)=="string" and #expected_hex>0 and #expected_hex<=2*1024*1024
            and #expected_hex%2==0 and expected_hex:match("^[0-9A-F]+$"),"complete expected save-file bytes required")
        guard()
        local frame=emu.framecount()
        local result=flush(false)
        assert(result and not result.IsError and result.Exception==nil,"host SaveRAM write failed")
        -- A default FileWriteResult is also Success when the core supplies no
        -- SaveRAM. Require the actual source-selected final path, not that enum.
        local get_field=luanet.get_method_bysig(result:GetType(),"GetField","System.String","System.Reflection.BindingFlags")
        local field=assert(get_field("Paths",flags))
        local field_value=luanet.get_method_bysig(field,"GetValue","System.Object")
        local writer_paths=field_value(result)
        assert(writer_paths and tostring(Path.GetFullPath(writer_paths.Final)):lower()==target:lower(),
            "host did not publish the expected SaveRAM file")
        local stream
        local ok,receipt=pcall(function()
            stream=Stream(target,Mode.Open,Access.ReadWrite,Share.None)
            assert(tonumber(stream.Length)*2==#expected_hex,"SaveRAM file length differs")
            stream:Flush(true);stream:Dispose();stream=nil
            local raw=File.ReadAllBytes(target)
            local actual=tostring(Bits.ToString(raw)):gsub("-","")
            assert(actual==expected_hex,"SaveRAM file bytes differ from the canonical cartridge readback")
            guard();assert(emu.framecount()==frame,"emulation advanced during save-file persistence")
            return {schema=M.SCHEMA,path=target,sha256=hash(raw),byte_length=#expected_hex/2,
                host_profile=profile.capability_id,frame=frame,flushed=true,readback=true}
        end)
        if stream then pcall(function()stream:Dispose()end)end
        assert(ok,receipt);return receipt
    end
    return self
end
return M
