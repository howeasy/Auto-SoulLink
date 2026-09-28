# Harness-only installed NLua probe. Every invocation uses a new caller-owned install root;
# it traces the shipped Lua counter function without modifying that function or any old root.
param(
    [Parameter(Mandatory=$true)][string]$Root,
    [Parameter(Mandatory=$true)][string]$Side,
    [Parameter(Mandatory=$true)][string]$Trace,
    [Parameter(Mandatory=$true)][string]$SourceRoot,
    [Parameter(Mandatory=$true)][string]$BizHawk,
    [switch]$HoldAfterClaim,
    [string]$Held,
    [string]$Release
)
$ErrorActionPreference = 'Stop'
$base = $BizHawk
Add-Type -TypeDefinition @"
using System.Runtime.InteropServices;
public static class SLinkCounterRunNativePath {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, ExactSpelling=true, SetLastError=true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool SetDllDirectoryW(string path);
}
"@
if (-not [SLinkCounterRunNativePath]::SetDllDirectoryW("$base/dll")) { throw 'SetDllDirectoryW failed' }
foreach($dll in @('BizHawk.Common.dll','BizHawk.Emulation.Common.dll','BizHawk.Client.Common.dll','NLua.dll')) {
    Add-Type -LiteralPath "$base/dll/$dll"
}
$vm = [NLua.Lua]::new()
try {
    $source = Get-Content -Raw -LiteralPath (Join-Path $SourceRoot 'lua/gen3/run.lua')
    $block = [regex]::Match($source,'(?s)-- >>> session counter.*?>>>\s*(.*?)-- <<< session counter <<<').Groups[1].Value
    if (-not $block) { throw 'counter extraction failed' }
    $vm['root'] = [IO.Path]::GetFullPath($Root).Replace('\','/')
    $vm['trace'] = [IO.Path]::GetFullPath($Trace).Replace('\','/')
    $vm['side'] = $Side
    $vm['hold_after_claim'] = $HoldAfterClaim.IsPresent
    $vm['held_marker'] = $Held
    $vm['release_marker'] = $Release
    $start = [DateTime]::UtcNow
    $result = $vm.DoString($block + "`n" + @'
local raw_open, raw_rename, raw_remove = io.open, os.rename, os.remove
local File = luanet.import_type('System.IO.File')
local DateTime = luanet.import_type('System.DateTime')
local Thread = luanet.import_type('System.Threading.Thread')
local spins, missing_rename = 0, 0
local function log(kind, detail)
    local f=assert(raw_open(trace,'a'))
    f:write(side,' utc_ticks=',tostring(DateTime.UtcNow.Ticks),' cpu=',string.format('%.6f',os.clock()),
            ' ',kind,' ',tostring(detail),'\n')
    f:close()
end
local function open_file(path,mode)
    local f,msg,code=raw_open(path,mode)
    if path:match('%.born$') or path:find('%.born%.') or path:find('%.new%.')
       or path:find('%.baton%.') or not f then
        log('OPEN',tostring(mode)..' '..path..' ok='..tostring(f~=nil)..' exists='..tostring(File.Exists(path))..' errno='..tostring(code)..' msg='..tostring(msg))
    end
    return f,msg,code
end
local function rename_file(src,dst)
    local ok,msg,code=raw_rename(src,dst)
    if ok and hold_after_claim and src==root..'/slink_gen3_session.baton' then
        File.WriteAllText(held_marker,'claimed')
        local deadline=os.time()+15
        while not File.Exists(release_marker) and os.time()<deadline do Thread.Sleep(2) end
        assert(File.Exists(release_marker),'the adversarial holder was not released')
    end
    if ok or code~=2 then
        local content='-'
        if ok and dst:find('%.baton%.') then
            local f=raw_open(dst,'r')
            if f then content=f:read('a'); f:close() else content='MISSING_AFTER_SUCCESS' end
        end
        log('RENAME',src..' -> '..dst..' ok='..tostring(ok)..' dst_exists='..tostring(File.Exists(dst))..' src_exists='..tostring(File.Exists(src))..' content='..tostring(content)..' errno='..tostring(code)..' msg='..tostring(msg))
    else
        missing_rename=missing_rename+1
        if missing_rename==1 then log('RENAME_ENOENT_FIRST',src..' -> '..dst) end
    end
    return ok,msg,code
end
local function spin()
    spins=spins+1
    local t=os.clock()+0.005
    while os.clock()<t do end
end
log('START',root)
local function guard(path)
    local handle,why=acquire_session_guard(path)
    log('GUARD',path..' ok='..tostring(handle~=nil)..' reason='..tostring(why))
    return handle,why
end
local n,why,busy
busy=0
for _=1,600 do
    n,why=next_session_counter(root,open_file,raw_remove,spin,rename_file,true,guard)
    if n or why~='busy' then break end
    busy=busy+1
    Thread.Sleep(1) -- host-only stand-in for the production emu.frameadvance yield
end
log('END','n='..tostring(n)..' reason='..tostring(why)..' guard_busy='..busy..' spins='..spins..' missing_rename='..missing_rename)
return tostring(n),tostring(spins),tostring(missing_rename),tostring(busy)
'@)
    $elapsed = ([DateTime]::UtcNow - $start).TotalMilliseconds
    Write-Output "SIDE=$Side VALUE=$($result[0]) SPINS=$($result[1]) MISSING_RENAMES=$($result[2]) GUARD_BUSY=$($result[3]) WALL_MS=$elapsed"
} finally { $vm.Dispose() }
