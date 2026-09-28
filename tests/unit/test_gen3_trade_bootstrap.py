"""Host-boundary controls using the installed NLua/.NET runtime, without an emulator."""
import json
import os
import shutil
import subprocess
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
local held=assert(fs.lock(path..'.contention-probe'))
local second, _, why=fs.lock(path..'.contention-probe')
assert(second == nil and why == 'busy', 'sharing violation must be a typed transient result')
assert(fs.close(held))
local denied=pcall(function() fs.lock(path..'.missing/guard') end)
assert(not denied, 'a missing parent directory must remain a permanent lock error')
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
