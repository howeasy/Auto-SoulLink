# Gen4 G1 run scenarios

`<title>.json` pins the native OUTDOOR baseline by lane-relative path and SHA256.
`<title>_row_i.json` pins its separate PC-deposit/native-SAVE boxed descendant,
including its SYNTH ancestry sidecar hash. Only row i uses that descendant.
Routes, persistence recipes and all four phase cases remain the pack's defaults;
scenario runtime overrides are forbidden. Missing inputs are named OPENs;
present wrong inputs fail. No scenario contains an absolute lane path.

Every raw and combined a-n receipt carries `scenario_path`, `scenario_sha256`,
`row_i_scenario_path` and `row_i_scenario_sha256`. Consumption re-reads both files;
changes are STALE. Launch requires committed bytes and the original harness
functions/code. Older receipts without this binding cannot qualify.

## Offline checks

```powershell
$env:SLINK_WORK_ROOT='F:/slink-work'
$env:PYTEST_DEBUG_TEMPROOT='F:/slink-work/tmp'
python -m pytest tests/unit tests/live -k gen4 -m 'not live' -q
python -m pytest @(rg --files tests/unit -g 'test_nds_*.py') -q
python -m ruff check tests/live/test_gen4_probe_gates.py tests/live/test_gen4_catch.py
python tools/lua_syntax_check.py
```

## Planned live commands (after coordinator FROZEN/lane grant)

Run sequentially in this worktree; never use pytest-xdist. Retained states below
are inputs, not reused qualification receipts. Producers stage private copies,
create fresh timestamp/UUID lanes and clean up their owned processes only.

```powershell
$env:SLINK_WORK_ROOT='F:/slink-work'
$env:PYTEST_DEBUG_TEMPROOT='F:/slink-work/tmp'
$env:SLINK_LIVE='1'
foreach ($key in @('SLINK_GEN4_PROBE_QUALIFY','SLINK_GEN4_PERF_RECEIPT','SLINK_GEN4_PERF_PHASE',
    'SLINK_GEN4_PERF_JIT_ONLY','SLINK_GEN4_PERF_SKIP_JIT','SLINK_GEN4_PERF_SUSTAINED_ONLY',
    'SLINK_GEN4_PERF_ONLY','SLINK_GEN4_PERF_COLD_BOOT')) {
    Remove-Item -LiteralPath "Env:$key" -ErrorAction SilentlyContinue
}
$tag=(git rev-parse --short HEAD).Trim()+'-'+(Get-Date -Format 'yyyyMMdd-HHmmss')
$root='F:/slink-work/lanes/g4'

# 1. Row o: HG one/two, then hge one/two. Real producer; no function overrides.
@'
import json, re, shutil
from tests.live import test_gen4_battle_faint as f
from tools.gen4_fixtures import lane_root
from tools import gen4_pins
root=lane_root()
for title, short, native, one, two in [
    ('heartgold','hg','saves/hg_base_26310.SaveRAM',
     'route/route_leg2_battle_settled.State', 'g1hg-p2-route-1016/p2hg_leg2_battle_settled.State'),
    ('heartgold_hge','hge','saves/hge_a_OOO_630.SaveRAM',
     'route_hge/route_hge_leg5_battle_settled.State', 'g1hge-p2-route-1022/p2hge_leg5_battle_settled.State')]:
    for p2, relative in [(False,one),(True,two)]:
        state=f.need(root/relative, 'retained settled battle input')
        log=state.with_name(state.name.replace('_battle_settled.State','.log'))
        text=f.need(log, 'settled input log').read_text()
        assert re.search(r'RESULT BATTLE\b',text) and re.search(r'settled after \d+ frames',text)
        save=root/(f'g1inputs-c935-1015/{short}_p2.SaveRAM' if p2 else native)
        synth=f.check_synth(save,title) if p2 else None
        scenario='seam_ufce_bit_p2' if p2 else 'seam_ufce_bit'
        before={p:f.digest(p) for p in (state,save)}
        status,payload,lane,out=f.launch(title,scenario,state,gen4_pins.default_locations().roms[title],save,synth=synth)
        verdict,why=f.receipt_verdict(out,title=title,rom_sha1=payload['rom_sha1'])
        print(json.dumps({'receipt':str(out),'verdict':verdict,'reason':why}))
        assert all(f.digest(p)==h for p,h in before.items()), 'original input changed'
        assert verdict==status=='PASS', out
        shutil.copyfile(out, f.LANES[title]/f'row_o_{title}_{scenario}.txt')
'@ | python -

# 2. Full a-n, HG / hge / SS. Read each combined.txt, including named OPENs.
$env:SLINK_GEN4_PROBE_RUNS="$root/g1-scenarios-$tag"
$env:SLINK_GEN4_PROBE_SKIP_PERF_REASON='PERF deferred to quiet-machine final step'
foreach ($title in @('heartgold','heartgold_hge','soulsilver')) {
    $env:SLINK_GEN4_PROBE_SCENARIO="data/gen4/scenarios/$title.json"
    $env:SLINK_GEN4_ROW_O=if ($title -eq 'soulsilver') {$null} else {"$root/faint2/row_o_${title}_seam_ufce_bit_p2.txt"}
    python -m pytest "tests/live/test_gen4_probe_gates.py::test_gen4_hook_probe[$title]" -m live -q -rs
    $batch=Get-ChildItem $env:SLINK_GEN4_PROBE_RUNS -Directory -Filter "$title-*" | Sort-Object LastWriteTime | Select-Object -Last 1
    Get-Content -LiteralPath (Join-Path $batch.FullName 'combined.txt')
}

# 3. First PC withdraw trial; require this target at consumption.
python tools/gen4_routes.py run --game HG --target pc_withdraw --save "$root/g1inputs-c935-1015/hg_boxed.SaveRAM" --lane "wd-hg-$tag"
python -c "from tools.gen4_routes import verify_receipt; print(verify_receipt('$root/wd-hg-$tag/wd-hg-${tag}_receipt.json','route',want='PC_WITHDRAW'))"

# 4. PERF LAST. Any remaining EmuHawk is foreign: record the PIDs and stop.
$env:SLINK_GEN4_HEARTGOLD_SAVE="$root/saves/hg_base_26310.SaveRAM"
$env:SLINK_GEN4_HEARTGOLD_HGE_SAVE="$root/saves/hge_a_OOO_630.SaveRAM"
$env:SLINK_GEN4_HEARTGOLD_BATTLE_STATE="$root/route/route_leg2_battle_settled.State"
$env:SLINK_GEN4_HEARTGOLD_OVERWORLD_STATE="$root/perf/heartgold-19ef720fc3e6/overworld_floor_1x/input.State"
$env:SLINK_GEN4_HEARTGOLD_HGE_BATTLE_STATE="$root/perf/heartgold_hge-69a401df3d4b/battle_floor_1x/input.State"
$env:SLINK_GEN4_HEARTGOLD_HGE_OVERWORLD_STATE="$root/perf/heartgold_hge-69a401df3d4b/overworld_floor_1x/input.State"
$env:SLINK_GEN4_PERF_RUNS="$root/g1-perf-$tag"
foreach ($title in @('heartgold','heartgold_hge')) {
    $foreign=@(Get-CimInstance Win32_Process -Filter "Name='EmuHawk.exe'" | Select-Object -ExpandProperty ProcessId)
    if ($foreign.Count) { Write-Output "OPEN f: foreign EmuHawk PIDs $foreign"; break }
    python -m pytest "tests/live/test_gen4_perf.py::test_live_perf[$title]" -m live -q -rs
}
```

Report PERF independently; earlier combined f OPENs remain unchanged. Missing SS
row o remains OPEN. hge/SS have no title-specific measured phase settle policy;
retain the measured verdicts/reasons rather than inheriting HG's allowance.
Read back every combined receipt before reporting. Preserve failed lanes and
all historical cuts. Audit owned PID exit and original hashes before release.
