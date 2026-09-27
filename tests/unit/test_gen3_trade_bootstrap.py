"""Host-boundary controls using the installed NLua/.NET runtime, without an emulator."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_real_nlua_file_adapter_survives_a_new_process_and_uses_the_configured_battery_path(tmp_path):
    runtime = Path(os.environ.get("SLINK_BIZHAWK", "E:/Howard/Bizhawk"))
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if os.name != "nt" or not shell or not (runtime / "dll/NLua.dll").is_file():
        pytest.skip("installed Windows NLua/BizHawk runtime absent")
    def quote(value):
        return "'" + str(value).replace("'", "''") + "'"
    script = tmp_path / "journal_host.ps1"
    script.write_text("$ErrorActionPreference='Stop'\n" +
        "$base=" + quote(runtime.as_posix()) + "\n" +
        "$root=" + quote(ROOT.as_posix()) + "\n" +
        "$path=" + quote((tmp_path / "journal").as_posix()) + "\n" + r'''
$env:PATH="$base/dll;"+$env:PATH
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
    $cfg=[BizHawk.Client.Common.Config]::new()
    $cfg.PathEntries.get_Item('GBA','Save RAM').Path=[System.IO.Path]::GetDirectoryName($path)
    $vm['cfg']=$cfg
    $code="luanet.load_assembly('BizHawk.Emulation.Common'); luanet.load_assembly('BizHawk.Client.Common');`n"+$block+"`n"+@'
local J=dofile(root..'/lua/gen3/trade_journal.lua')
local json=dofile(root..'/lua/json_codec.lua')
local store=J.file_store({json=json,fs=trade_file_adapter(luanet.import_type),path=path})
local obj=J.new({json=json,store=store,rom_sha1=string.rep('a',40),player='a'})
assert(not obj.failure,obj.failure)
obj:bind('host-model','12345678')
local old=obj:outstanding()
local epoch=assert(obj:allocate())
if #old==0 then assert(obj:arm('host-token',epoch)) end
assert(obj:hidden())
local battery=trade_battery_path(luanet.import_type,cfg,'Test Cartridge','GBA',false)
return json.encode({epoch=epoch,prior=#old,battery=battery})
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
    assert Path(results[1]["battery"]) == tmp_path / "Test Cartridge.SaveRAM"
