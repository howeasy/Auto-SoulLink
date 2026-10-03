# Gen4 G1 run scenarios

`<title>.json` pins the native OUTDOOR baseline by lane-relative path and SHA256.
`<title>_row_i.json` pins its separate PC-deposit/native-SAVE boxed descendant,
including its SYNTH ancestry sidecar hash. Only row i uses that descendant.
Schema `gen4-probe-scenario-v3` also requires `<title>_pc_case.json`: its dedicated
party2 input and SYNTH sidecar are hash-bound. The PC phase never falls back to
the native one-mon baseline or boxed row-i descendant. Existing hge/SS party2
inputs need the PC bridge Pokégear errand before Cherrygrove; no save is staged
or story flag modified by this schema.
Routes, persistence recipes and all six phase cases remain the pack's defaults;
scenario runtime overrides are forbidden. Missing inputs are named OPENs;
present wrong inputs fail. No scenario contains an absolute lane path.

Every raw and combined a-n receipt carries `scenario_path`, `scenario_sha256`,
`row_i_scenario_path`, `row_i_scenario_sha256`, `pc_case_scenario_path` and
`pc_case_scenario_sha256`. Consumption re-reads all three files;
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

## One-slot diagnostic runbook (after coordinator FROZEN + slot grant)

HOLD means no emulator. Sequential execution only, no xdist; preserve failures.
The committed tools/gen4_diag.py stays OUTSIDE qualification surface. Every
JSON says qualified:false and records driver/generated-Lua/config hashes, the
frozen surface manifest, ROM/scenario/save/state hashes, original-input check
and owned Popen PID/exit audit. Reuse the frozen recipe, BridgePlanner/native
executor and composite/phase_monitor; never override harness functions.
All manual lane names below fit the 24-character cap. Existing automatic
producer subdirectory naming stays unchanged. Foreign PIDs remain untouched.

```powershell
$env:SLINK_WORK_ROOT='F:/slink-work'
$env:PYTEST_DEBUG_TEMPROOT='F:/slink-work/tmp'
$env:SLINK_LIVE='1'
$root='F:/slink-work/lanes/g4'
$stamp=Get-Date -Format 'MMddHHmmss'
$cut='<coordinator FROZEN full SHA>'
$env:G4_FROZEN=$cut
function Assert-Cut {
    if ((git rev-parse HEAD).Trim() -ne $cut) { throw 'STOP wrong HEAD' }
    if (@(git status --porcelain).Count) { throw 'STOP dirty source' }
}
function Census {
    Get-CimInstance Win32_Process -Filter "Name='EmuHawk.exe'" |
        Select-Object ProcessId,CreationDate,CommandLine
}
Assert-Cut
Census

# D1: current 6000-frame recipe, now requiring a freshly reviewed L12 state.
# FIRST obtain the HG state from a fresh diagnostic cold-boot/native wild route
# on the committed heartgold_lead12 scenario (one owned slot, separate lane):
# python tools/gen4_diag.py settle --title heartgold --scenario data/gen4/scenarios/heartgold_lead12.json --cold-boot --errand pokegear --target battle_settled --images ov12 --lane <fresh-hg-prep> --timeout 600
# Coordinator reviews diagnostic outputs/state SHA. The old 108c state is Lv5;
# do not pair it with a new L12 save or call it the strengthened fixture.
$hg12state=$env:G4_HG_LEAD12_STATE
$hg12sha=$env:G4_HG_LEAD12_STATE_SHA256
if (-not $hg12state -or -not $hg12sha) { throw 'OPEN reviewed HG lead12 battle state absent' }
$d1="d1-hg-$stamp"
python tools/gen4_diag.py fight --title heartgold --scenario data/gen4/scenarios/heartgold_lead12.json --state $hg12state --state-sha256 $hg12sha --recipe fight_until_enemy_faints --lane $d1 --timeout 300
Get-Content "$root/$d1/diagnostic.json"
Census

# D2: cold boot, native Pokegear errand, natural wild launch, uncensored pins.
Assert-Cut
$d2h="d2-hge-$stamp"
python tools/gen4_diag.py settle --title heartgold_hge --scenario data/gen4/scenarios/heartgold_hge_lead12.json --cold-boot --errand pokegear --target battle_settled --images ov12 ov130 ov129 --lane $d2h --timeout 600
Get-Content "$root/$d2h/diagnostic.json"
Census
Assert-Cut
$d2s="d2-ss-$stamp"
python tools/gen4_diag.py settle --title soulsilver --scenario data/gen4/scenarios/soulsilver_lead12.json --cold-boot --errand pokegear --target battle_settled --images ov12 --lane $d2s --timeout 600
Get-Content "$root/$d2s/diagnostic.json"
Census

# D3: native RUN + Battle_Exit callback/fall/close counters AND advance tokens.
Assert-Cut
$d3="d3-hg-$stamp"
python tools/gen4_diag.py boundary --title heartgold --scenario data/gen4/scenarios/heartgold.json --state "$root/live108-1002220018/probes/heartgold-7a5a0a43970f/baseline/bridge-2_battle_settled.State" --state-sha256 b16302579d3ea1a7c9eef501a9fd972338841e180a46dbc91c49eaf240c165e6 --phase-case battle_close --lane $d3 --timeout 300
Get-Content "$root/$d3/diagnostic.json"
Census

# D4: first withdraw DIAGNOSTIC; per-press trace, unchanged script_a/recover_a.
Assert-Cut
$wd='wd-hg-'+(Get-Date -Format 'MMddHHmmss')
python tools/gen4_routes.py run --game HG --target pc_withdraw --save "$root/g1inputs-c935-1015/hg_boxed.SaveRAM" --lane $wd
Get-ChildItem "$root/$wd" -Filter '*leg*.log' | Sort-Object Name |
    ForEach-Object { Get-Content -LiteralPath $_.FullName }
python -c "from tools.gen4_routes import verify_receipt; print(verify_receipt('$root/$wd/'+'$wd'+'_receipt.json','route',want='PC_WITHDRAW'))"
Census
```

Before EVERY cell: assert cut, fresh directory absent, prior own PID exited,
and verify committed scenario/save hashes (plus SYNTH sidecars where used).
Diagnostic host cleanup uses its Popen handle and fresh lane command matches,
never an image-name kill. Timeout/error still publishes identity/cleanup audit.
The mutable bizhawk.ini has before/after hashes and semantic checks for NDS
sync and the whole CoreSettings[NDS] entry (including TraceArm9 toggles), all
NDS path entries plus Firmware, applied SpeedPercent, Unthrottled, FrameSkip,
AutoMinimizeSkipping, ClockThrottle, VSyncThrottle, SuperHawkThrottle, audio
flags/volume and Rewind; UI/history writes
are allowed. Lua, diagnostic input config, copied state, staged ROM and surface
remain byte-strict. Later audit errors append to the first/raw failure reason.
If the emulator exits abnormally without rewriting bizhawk.ini (identical
before/after hash), it is UNFLUSHED: settings_valid=null and settings_status=UNVERIFIED.
The Lua applied_rate field records a call argument, not a settings getter or
runtime witness. Immutable input checks still run; successful raw observations
remain available but the host grades an unverified settings audit OPEN.
Rewritten critical settings still compare exactly. Empty/malformed results
after process exit fail immediately rather than waiting the host bound.

D1 reports PP-use ordinals (frame/battler/slot/move/before/after), species/level
and both HP traces. Ordinals are NOT measured turns. No pinned miss/critical/
damage-cause witness exists in the pack; RNG attribution stays INCONCLUSIVE.
The initial sample is recorded before validation. Empty-input readiness waits
use the native battle_settled producer's existing 900-frame bound for the pack
battle phase plus the unchanged positive-HP guard; no unpinned menu-ready
criterion is invented. Both initial/last samples and refusal values are kept.
Wrong slot/nonselection is input drift evidence. Estimate 1-3 minutes; first
falsifier is wrong input/battle, unexpected PP, loss or recipe bound.

D2 samples at the first Lua-observable frame, full registration pin and region-0
residency every frame, with no 16-frame cutoff. An observed inactive-to-resident
transition after an initially inactive/unmatched observation is uncensored.
Resident in ANY of the three overlay-table regions OR pin-matched at attach
is LEFT_CENSORED:
it is reported as OBSERVED_CENSORED with left_censored=true and no measured
delta, never an invented zero. The first observable counter was PHYSICALLY 1
on both b809 title runs; it does not globally censor inactive sites. The 24000-frame
post-route observation ceiling/host timeout is not a policy/max measurement.
The driver retains every sampled state as per-site run-length spans: first/last
frame and count, active flag, full-pin match decision, all active region/slot
locations and epoch ID. Each policy-input change splits the span; active edges create epochs
with pin-land frames and censoring. Steady decisions are not discarded. Raw
mismatched bytes can vary in reused BSS: spans retain first/last byte examples
and pin_bytes_varied, rather than implying those unneeded bytes were constant
or dumping them each frame. Every frame still receives a FULL pin read. Instrument
bounds (256 spans / 128 epochs PER SITE) fail explicitly on excessive churn, never truncate
into a policy. Encoding precedes output opening; a named encoding FAIL is
published via a closed temporary file and atomic rename. A fresh lane
(mkdir exist_ok=False) guarantees an absent target, asserted before publication.
Write/rename failures use observation.json.error so the host retains their
named reason. The 24-entry table is scanned once per frame for all sites;
locations need no redundant string key. Churn limits allow >10 changes and
>5 load epochs per each of 12 bridge attempts; they are instrument capacity,
not a measured loading policy, and a trip names the site.
Keep every span/epoch, errand/re-arm trace and bridge-N_battle_settled.State/log/hash
(the diagnostic outputs manifest). Estimate 2-6 minutes/title. First falsifier:
censored load, pin never lands, wrong image, 12-attempt errand bound or no wild
launch. SS has ov12; hge additionally has ov130/ov129. Resident-from-boot ov129
is reported with its censoring class. The driver already attaches with --lua
and samples before its first frameadvance, accepting the observed frame-1 origin. That
does not establish observation before ROM/core initialization: an earlier
attachment point is not implemented or PHYSICALLY verified here. These
diagnostics do not author settle-policy values.

D3 is HG-only and uses the harness's committed HG settle policy/image pins and
M.phase_sites_ready before arming. It compares callback/fall/close frames and same advance token, pending>=1,
exactly-once delivery, retained0 and second-drain0. No assumed equal counters.
Estimate 1-3 minutes; first falsifier is missing boundary/lost event or cleanup.
D4 uses boxed row-i hash/sidecar inventory and target-specific receipt consumer.
Source gives three ACCEPTED As after interact: msg33 carriage wait, choose the
storage PC at Which-PC row0, msg35 carriage wait, THEN Right on the storage menu.
{YESNO 0} is a focus indicator, not another YesNo prompt. The executor waits the existing
900-frame bound before each semantic A; counts remain
script_a=3/recover_a=0 (return via NonNPCMsg directly to the storage menu). See
pinned pret scr_seq_0003.s:754-885, msg_0040.gmm:142-152, scrcmd_message.c:142-151
and render_text.c:95-105,158-168,270-273,302-310. This input schedule still needs
PHYSICAL validation; the observed screenshot confirms menu state only.
Right now uses the original three-frame hold and 30-frame release window.
The old single-column interpretation followed the WRONG opcode. Opcode752
MenuExec (script_cmd_table.h:1606-1609; scrcmd_c.c:5025-5032) goes through
ov01_021F6ABC(fs,3,7,p_ret) to overlay27's touchscreen grid. MoveTutorMenu_SetListItem_Internal
appends entry values in order (overlay_01_021EDAFC.s:989-1082); ov27_0225C618
builds windows from count-indexed templates in ov27_0225D4B8, and ov27_0225CA68
uses neighbors in ov27_0225D480 indexed by count-2. For five/six entries,
ov27_0225D174/D1B4 map index0 Up/Down/Left/Right to 0/2/0/1: Down reaches
MOVE, Right reaches WITHDRAW. This geometry comes from source, not pixels.
The legacy ov01_021EDC84/Handle2dMenuInput path is not used by these opcodes.
Each press, launch and terminal logs PC_WITNESS: VAR_SPECIAL_RESULT (u16 from
the magic-checked ScriptEnvironment) and the app argument (u32 man+0x18 -> args+8).
After the app/args are freed, the terminal names the gap and preserves the
launch snapshot instead of reading a cached pointer. Native script_a/recover_a,
recipe, criteria and all run budgets remain unchanged.
Estimate 2-5 minutes. First falsifier: named press blocks/wrong app, missing mon
transition, SAVE or independent reload. Remains disclosed DIAGNOSTIC even if its
consumer reports PASS.

If D1-D3 demand source repair: STOP, report, new freeze; no mid-run fix/retry.
**D2 policy consumption always requires coordinator review/commit/new FROZEN
before Q**: the current wrapper has no measured hge/SS policy. No env override.
Re-pin $cut/G4_FROZEN for Q; all old cuts stay historical. SS is FILE-verified in
the real faint producer without changing HG/hge or the Lua defaults. Generate
SS two-mon battle from its dedicated committed party2 fixture after the freeze:

```powershell
Assert-Cut
$os2="o2-ss-$stamp"
python tools/gen4_routes.py run --game SS --target grass --errand pokegear --save "$root/g1inputs-c935-1015/ss_p2.SaveRAM" --lane $os2 --tag p2ss
```

Select the actual new BATTLE+settled states, not a guessed leg number. Pin their
hashes from reviewed manifests before row o. Diagnostic.json identifies every
state by producer, qualified:false, setup class and sha256 (including resync
states and retained-input copies); it is NOT a receipt. Diagnostic-produced
states are disclosed setup inputs, not qualification evidence. Set G4_SS_ONE and G4_SS_TWO to
lane-relative paths: native SS one-state may be the reviewed D2 output; two-state
is the new party2 route output. Q's native/PC/boxed saves remain the committed
scenario inventory, including sidecar hashes. Verify every retained state hash
before reuse. Fill the expected hashes from independently reviewed manifests,
not by hashing a possibly changed file at launch. Q is approximately 50-90
minutes, not a timeout extension.

```powershell
$env:G4_SS_ONE='<lane-relative D2 bridge-N_battle_settled.State>'
$env:G4_SS_ONE_MANIFEST="$root/$d2s/diagnostic.json"
$env:G4_SS_ONE_SHA256='<reviewed SHA256 from the D2 outputs entry>'
$env:G4_SS_TWO='<lane-relative new party2 route state>'
$env:G4_SS_TWO_SHA256='<independently reviewed SHA256 of the native route state>'
```

## Q: qualification ONLY after diagnostic review and the NEW FROZEN

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
$tag=Get-Date -Format 'MMddHHmmss'
$root='F:/slink-work/lanes/g4'

# 1. Row o: HG one/two, hge one/two, then SS one/two. Real producer; no function overrides.
@'
import json, os, re, shutil
from tests.live import test_gen4_battle_faint as f
from tools.gen4_fixtures import lane_root
from tools import gen4_pins
from tools.gen4_diag import check_state_manifest, sha256
root=lane_root()
for title, short, native, one, two, one_sha, two_sha in [
    ('heartgold','hg','saves/hg_base_26310.SaveRAM',
     'route/route_leg2_battle_settled.State', 'g1hg-p2-route-1016/p2hg_leg2_battle_settled.State',
     'eca826afb5df8b73f3057219b41647028c60216aee0767302c489bd341d60da2',
     '0aafe8182ef6943366daba6338bac0c7b8da3fefe97a218843f9b2f0091579aa'),
    ('heartgold_hge','hge','saves/hge_a_OOO_630.SaveRAM',
     'route_hge/route_hge_leg5_battle_settled.State', 'g1hge-p2-route-1022/p2hge_leg5_battle_settled.State',
     '2b363fade4dcef46bde004379e6499cac53da8de0d5984c33782f49eca6f2b7f',
     'e8c96480a25609cdd1ef1d431a1cda9ec0cc69ac9b85e0dca331887ac5fc0941'),
    ('soulsilver','ss','saves/ss_DDDD_25944.SaveRAM',
     os.environ['G4_SS_ONE'], os.environ['G4_SS_TWO'],
     os.environ['G4_SS_ONE_SHA256'], os.environ['G4_SS_TWO_SHA256'])]:
    for p2, relative in [(False,one),(True,two)]:
        import subprocess
        assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()==os.environ['G4_FROZEN']
        assert not subprocess.check_output(['git','status','--porcelain'],text=True).strip()
        state=f.need(root/relative, 'retained settled battle input')
        expected=two_sha if p2 else one_sha
        assert sha256(state)==expected, 'reviewed state hash mismatch'
        setup={'producer':'tools/gen4_routes.py','qualified':False,'setup':'RETAINED_ROUTE_STATE','sha256':expected}
        if title=='soulsilver' and not p2:
            setup=check_state_manifest(state, os.environ['G4_SS_ONE_MANIFEST'], expected)
        print(json.dumps({'state':str(state),'state_setup':setup}))
        log=state.with_name(state.name.replace('_battle_settled.State','.log'))
        text=f.need(log, 'settled input log').read_text()
        assert re.search(r'RESULT BATTLE\b',text) and re.search(r'settled after \d+ frames',text)
        save=root/(f'g1inputs-c935-1015/{short}_p2.SaveRAM' if p2 else native)
        synth=f.check_synth(save,title) if p2 else None
        scenario='seam_ufce_bit_p2' if p2 else 'seam_ufce_bit'
        before={p:f.digest(p) for p in (state,save)}
        status,payload,lane,out=f.launch(title,scenario,state,gen4_pins.default_locations().roms[title],save,synth=synth)
        verdict,why=f.receipt_verdict(out,title=title,rom_sha1=payload['rom_sha1'])
        print(json.dumps({'receipt':str(out),'verdict':verdict,'reason':why,'state_setup':setup}))
        assert all(f.digest(p)==h for p,h in before.items()), 'original input changed'
        assert verdict==status=='PASS', out
        shutil.copyfile(out, f.LANES[title]/f'row_o_{title}_{scenario}.txt')
'@ | python -

# 2. Full a-n, HG / hge / SS. Read each combined.txt, including named OPENs.
$env:SLINK_GEN4_PROBE_RUNS="$root/q-$tag/probes"
$env:SLINK_GEN4_PROBE_SKIP_PERF_REASON='PERF deferred to quiet-machine final step'
foreach ($title in @('heartgold','heartgold_hge','soulsilver')) {
    Assert-Cut
    $env:SLINK_GEN4_PROBE_SCENARIO="data/gen4/scenarios/${title}_lead12.json"
    $env:SLINK_GEN4_ROW_O="$root/faint2/row_o_${title}_seam_ufce_bit_p2.txt"
    python -m pytest "tests/live/test_gen4_probe_gates.py::test_gen4_hook_probe[$title]" -m live -q -rs
    $batch=Get-ChildItem $env:SLINK_GEN4_PROBE_RUNS -Directory -Filter "$title-*" | Sort-Object LastWriteTime | Select-Object -Last 1
    Get-Content -LiteralPath (Join-Path $batch.FullName 'combined.txt')
}

```

Read every combined.txt/control-reds.json before reporting. Remaining declared
caller gaps, named OPENs and f OPEN stay explicit. No threshold, budget or
recipe change. Never repeat unchanged failure. Own-PID audit and original
save/state/sidecar hashes precede lane release. PERF is separate and quiet-only:
foreign EmuHawk means f OPEN, never a noisy receipt.

## Disclosed lead12 baselines and current authoring cut

`<title>_lead12.json` is a NEW baseline, preserving the existing native scenarios
and their separate row-i / PC-case linkage. Each binds its own SYNTH save and
sidecar by SHA256. The loader refuses an undeclared sidecar, missing/mismatched
sidecar, or sidecar naming a different output hash. The probe and diagnostic
receipts disclose setup=SYNTH and sidecar_sha256. Hooks and route behavior run
natively; a live win is OPEN. No moves, identity, IV/EV or story flags changed.

Reproduce (new output only; originals never overwritten):
`python tools/gen4_synth_save.py lead_level --profile hgss|hge --title <title> --rom <pinned ROM> --src <native save> --out <new output> --level 12`.
The personal stats come from ROM a/0/0/2; growth EXP from a/0/0/3; IV/EV/nature
come from the decoded lead. The encrypted lead and newest general-footer CRC
are the only edited spans. Unknown hg-engine nature/IV override fields refuse.

Route producers now explicitly request 300%, clock-throttled, independent of
the owner's 800% defaults. Nested native diagnostic routes use the same rate.
PC mode1 target reads GridInputHandler.nextInput (grid+0x0D), not selection
cache data+0x21. One A activates button mode only when inactive; a separate A
still grabs and the 0x57/party/box/SAVE/reload criteria remain.

Owner-accepted uncensored settle provenance: hge observation
`d2-hge-10031339/observation.json` (max1 + margin5 = 6), SS observation
`d2-ss-10031344/observation.json` (max11 + margin5 = 16). Exact SHA256 and epoch
frames live in phase_settle_policy. Their historical overall FAIL was the
ClockThrottle audit; it is never relabelled PASS. These frame differences use
emulated counters and are independent of host throttling. A policy alone does
not qualify row n.
