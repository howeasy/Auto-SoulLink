"""Host-boundary controls using the installed NLua/.NET runtime, without an emulator."""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _powershell_hosts():
    primary = shutil.which("pwsh") or shutil.which("powershell")
    hosts = [pytest.param(primary, id="PATH")]
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        packaged = Path(os.environ["LOCALAPPDATA"]) / "Microsoft/WindowsApps/pwsh.exe"
        if packaged.is_file() and str(packaged).lower() != str(primary).lower():
            hosts.append(pytest.param(str(packaged), id="WindowsApps"))
    return hosts


@pytest.mark.parametrize("shell", _powershell_hosts())
def test_real_nlua_file_adapter_survives_a_new_process_and_uses_the_configured_battery_path(tmp_path, shell):
    runtime = Path(os.environ.get("SLINK_BIZHAWK", "E:/Howard/Bizhawk"))
    if os.name != "nt" or not shell or not (runtime / "dll/NLua.dll").is_file():
        pytest.skip("installed Windows NLua/BizHawk runtime absent")
    def quote(value):
        return "'" + str(value).replace("'", "''") + "'"
    script = tmp_path / "journal_host.ps1"
    script.write_text("$ErrorActionPreference='Stop'\n" +
        "$base=" + quote(runtime.as_posix()) + "\n" +
        "$root=" + quote(ROOT.as_posix()) + "\n" +
        "$path=" + quote((tmp_path / "journal").as_posix()) + "\n" + r'''
# EmuHawk Program.cs at bdddf4a5:125-160 configures this Win32 search directory.
# PATH alone fails in packaged WindowsApps PowerShell (NLua loads lua54.dll by name).
Add-Type -TypeDefinition @"
using System.Runtime.InteropServices;
public static class SLinkNativePath {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, ExactSpelling=true, SetLastError=true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool SetDllDirectoryW(string path);
}
"@
if (-not [SLinkNativePath]::SetDllDirectoryW("$base/dll")) { throw 'SetDllDirectoryW failed' }
foreach($dll in @('BizHawk.Common.dll','BizHawk.Emulation.Common.dll','BizHawk.Client.Common.dll','NLua.dll')) {
    Add-Type -LiteralPath "$base/dll/$dll"
}
$vm=[NLua.Lua]::new()
try {
    if ([NLua.Lua].Assembly.Location -ne [System.IO.Path]::GetFullPath("$base/dll/NLua.dll")) {
        throw 'Unexpected managed NLua runtime'
    }
    $native=[System.Diagnostics.Process]::GetCurrentProcess().Modules | Where-Object ModuleName -eq 'lua54.dll'
    if ($native.FileName -ne [System.IO.Path]::GetFullPath("$base/dll/lua54.dll")) {
        throw 'Unexpected native Lua runtime'
    }
    $source=Get-Content -Raw -LiteralPath "$root/lua/gen3/run.lua"
    $block=[regex]::Match($source,'(?s)-- >>> durable trade storage.*?>>>\s*(.*?)-- <<< durable trade storage <<<').Groups[1].Value
    if (-not $block) { throw 'adapter extraction failed' }
    $vm['root']=$root
    $vm['path']=$path
    $cfg=[BizHawk.Client.Common.Config]::new()
    $cfg.PathEntries.get_Item('GBA','Save RAM').Path=[System.IO.Path]::GetDirectoryName($path)
    $vm['cfg']=$cfg
    $code="luanet.load_assembly('BizHawk.Emulation.Common'); luanet.load_assembly('BizHawk.Client.Common');`n"+$block+"`n"+@'
local J=dofile(root..'/lua/gen3/trade_journal.lua')
local json=dofile(root..'/lua/json_codec.lua')
local fs=trade_file_adapter(luanet.import_type)
local File=luanet.import_type('System.IO.File')
local Mode=luanet.import_type('System.IO.FileMode')
local Access=luanet.import_type('System.IO.FileAccess')
local Share=luanet.import_type('System.IO.FileShare')
local birth_path=path..'.birth-probe'
local pre=File.Open(birth_path,Mode.OpenOrCreate,Access.ReadWrite,Share.None)
pre:Dispose()
local duplicate_ok, duplicate_error=pcall(function()
    return File.Open(birth_path,Mode.CreateNew,Access.ReadWrite,Share.None)
end)
assert(not duplicate_ok)
local duplicate_code=duplicate_error.InnerException.HResult
assert(duplicate_code == -2147024816 or duplicate_code == -2147024713,
       'unexpected CreateNew FILE_EXISTS HResult '..tostring(duplicate_code))
local first_exists=true
local proxy={}
proxy.Exists=function(p)
    if p==birth_path and first_exists then first_exists=false; return false end
    return File.Exists(p)
end
proxy.Open=function(...) return File.Open(...) end
local birth_fs=trade_file_adapter(function(name)
    if name=='System.IO.File' then return proxy end
    return luanet.import_type(name)
end)
local first_born, _, first_why=birth_fs.lock(birth_path)
assert(first_born == nil and first_why == 'busy' and first_exists == false,
       'CreateNew FILE_EXISTS race must defer, not permanently fail or replace the guard')
local born, was_fresh=birth_fs.lock(birth_path)
assert(born and was_fresh == false, 'the next frame must open the existing guard')
assert(birth_fs.close(born))
local held=assert(fs.lock(path..'.contention-probe'))
local second, _, why=fs.lock(path..'.contention-probe')
assert(second == nil and why == 'busy', 'sharing violation must be a typed transient result')
assert(fs.close(held))
local denied, denial=pcall(function() fs.lock(path..'.missing/guard') end)
local detail=tostring(denial)
assert(not denied and detail:find(path..'.missing/guard',1,true)
       and detail:find('DirectoryNotFoundException',1,true)
       and detail:find('hresult=',1,true) and detail:find('message=',1,true),
       'a permanent acquisition error must name its path and CLR cause: '..detail)
local store=J.file_store({json=json,fs=fs,path=path})
local obj=J.new({json=json,store=store,rom_sha1=string.rep('a',40),player='a'})
assert(not obj.failure,obj.failure)
obj:bind('host-model','12345678')
local old=obj:outstanding()
local wire=json.decode(json.encode(old))
if #old>0 then
    assert(math.type(old[1].epoch)=='integer' and math.type(wire[1].epoch)=='integer')
    assert(tostring(old[1].epoch)==tostring(wire[1].epoch))
end
local epoch=assert(obj:allocate())
if #old==0 then assert(obj:arm('host-token',epoch)) end
assert(obj:hidden())
local guard=assert(fs.lock(path..'.guard'))
assert(obj:hidden() and obj.failure == nil, 'host contention must hide without poisoning')
assert(obj:ready() == false, 'host contention must withhold trade capability')
assert(fs.close(guard))
assert(obj:ready() == true, 'the next host read must recover after guard release')
local battery=trade_battery_path(luanet.import_type,cfg,'Test Cartridge','GBA',false)
return json.encode({epoch=epoch,prior=#old,battery=battery,lua_version=_VERSION,epoch_type=math.type(epoch)})
'@
    $result=$vm.DoString($code)
    Write-Output $result[0]
} finally {$vm.Dispose()}
''', encoding="utf-8")
    results = []
    for _ in range(2):
        run = subprocess.run([shell, "-NoProfile", "-File", str(script)], capture_output=True, text=True, timeout=30)
        assert run.returncode == 0, run.stdout + run.stderr
        results.append(json.loads(run.stdout.strip().splitlines()[-1]))
    assert [(r["epoch"], r["prior"]) for r in results] == [(1, 0), (2, 1)]
    assert all(r["lua_version"] == "Lua 5.4" and r["epoch_type"] == "integer" for r in results)
    assert Path(results[1]["battery"]) == tmp_path / "Test Cartridge.SaveRAM"


def test_two_host_processes_recover_from_overlapping_guard_and_keep_epochs_monotonic(tmp_path):
    shell = shutil.which("pwsh")
    runtime = Path(os.environ.get("SLINK_BIZHAWK", "E:/Howard/Bizhawk"))
    if os.name != "nt" or not shell or not (runtime / "dll/NLua.dll").is_file():
        pytest.skip("installed Windows NLua/BizHawk runtime absent")

    def quote(value):
        return "'" + str(value).replace("'", "''") + "'"

    path, ready, release = (tmp_path / name for name in ("journal", "a-held", "b-observed"))
    script = tmp_path / "overlap.ps1"
    script.write_text("$ErrorActionPreference='Stop'\n" +
        "$base=" + quote(runtime.as_posix()) + "\n" +
        "$root=" + quote(ROOT.as_posix()) + "\n" +
        "$path=" + quote(path.as_posix()) + "\n" +
        "$ready=" + quote(ready.as_posix()) + "\n" +
        "$release=" + quote(release.as_posix()) + "\n" + r'''
Add-Type -TypeDefinition @"
using System.Runtime.InteropServices;
public static class SLinkOverlapNativePath {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, ExactSpelling=true, SetLastError=true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool SetDllDirectoryW(string path);
}
"@
if (-not [SLinkOverlapNativePath]::SetDllDirectoryW("$base/dll")) { throw 'SetDllDirectoryW failed' }
foreach($dll in @('BizHawk.Common.dll','BizHawk.Emulation.Common.dll','BizHawk.Client.Common.dll','NLua.dll')) {
    Add-Type -LiteralPath "$base/dll/$dll"
}
$vm=[NLua.Lua]::new()
try {
    $source=Get-Content -Raw -LiteralPath "$root/lua/gen3/run.lua"
    $block=[regex]::Match($source,'(?s)-- >>> durable trade storage.*?>>>\s*(.*?)-- <<< durable trade storage <<<').Groups[1].Value
    if (-not $block) { throw 'adapter extraction failed' }
    $vm['root']=$root
    $vm['path']=$path
    $vm['ready']=$ready
    $vm['release']=$release
    $vm['role']=$args[0]
    $code=$block+"`n"+@'
local J=dofile(root..'/lua/gen3/trade_journal.lua')
local json=dofile(root..'/lua/json_codec.lua')
local File=luanet.import_type('System.IO.File')
local Thread=luanet.import_type('System.Threading.Thread')
local fs=trade_file_adapter(luanet.import_type)
local store=J.file_store({json=json,fs=fs,path=path})
local obj=J.new({json=json,store=store,rom_sha1=string.rep('a',40),player=role})
assert(obj:bind('overlap-run','12345678'))
if role=='a' then
    local epoch=assert(obj:allocate())
    local guard=assert(fs.lock(path..'.guard'))
    File.WriteAllText(ready,'held')
    for _=1,5000 do
        if File.Exists(release) then break end
        Thread.Sleep(2)
    end
    assert(File.Exists(release),'B never observed the held guard')
    assert(fs.close(guard))
    return json.encode({epoch=epoch})
end
assert(obj:hidden() and obj.failure == nil,'B must hide but not poison while A holds guard')
assert(obj:ready() == false,'B cannot advertise trade during A guard hold')
File.WriteAllText(release,'observed')
local recovered=false
for _=1,5000 do
    if obj:ready() then recovered=true; break end
    Thread.Sleep(2)
end
assert(recovered,'B did not recover after A released guard')
local prior=J.decode(json,store.read()).counter
local epoch=assert(obj:allocate())
return json.encode({prior=prior,epoch=epoch})
'@
    $result=$vm.DoString($code)
    Write-Output $result[0]
} finally {$vm.Dispose() }
''', encoding="utf-8")

    a = subprocess.Popen([shell, "-NoProfile", "-File", str(script), "a"],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    b = None
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and a.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists(), a.communicate(timeout=5)
        b = subprocess.Popen([shell, "-NoProfile", "-File", str(script), "b"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        bout, berr = b.communicate(timeout=25)
        aout, aerr = a.communicate(timeout=25)
        assert a.returncode == 0, aout + aerr
        assert b.returncode == 0, bout + berr
        first, second = (json.loads(out.strip().splitlines()[-1]) for out in (aout, bout))
        assert first["epoch"] == 1 and second == {"prior": 1, "epoch": 2}
    finally:
        for process in (a, b):
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
