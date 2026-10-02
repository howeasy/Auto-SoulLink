# Gen 2 overlay admission — next session

Snapshot: 2026-10-02, branch `claude/mandatory-rom-patch-3fcfda`; initial handoff `b7d3f2b4`, refreshed through `499a2948`. This is an execution runbook, not a release verdict. The coordinator owns the sole guide/register and emulator allocation.
- Committed: R/A/B/C and review fixes; seven overlay qualifications (`79c6ac8a`); the overlay U1 union is COMPLETE
  for all three titles (frame_align + u1g grass/kyle/bill, production registration PASS): Crystal `db2fe12c`
  (frame_align at attempt 2 / 11:23), Gold `078738e9`, Silver `205d87ed`. Receipts are under
  `tests/fixtures/gen2/receipts/overlay/`.
- `499a2948` fixed overlay identity on BOTH U1G union producers (`lua/tests/gen2_u1g_inputs.lua:430`,
  `tests/live/test_gen2_u1g.py:129`), found by the Gold u1g PHYSICAL run; all three unions were captured on it.
- Still to establish in round 1: U2 for Crystal, Gold and Silver, then inspect. The first overlay U2 run (Crystal)
  failed in 75 s on a harness defect, now FIXED: reload/reset candidates were copied into the CLEAN lane's
  non-existent `.cache/gen2-fixtures/u2-write-windows/` (all U2 scratch paths now go through `work_root()` in
  `tests/live/test_gen2_write_windows.py`). Gold U2 was interrupted at wrap-up; Silver U2 and inspect never ran.
  Expect the `crystal_hello` step to keep failing until activation (it needs production overlay admission). Rows remain FUTURE/BUILT; `server/cartridges.py:28` excludes Gen 2.

## 1. Recover ownership and finish round 1

All following shell blocks are PowerShell. Use an external desktop terminal or the already validated detached runner: the coordinator observed the agent tool's **30-minute background limit killing long jobs**; Crystal's successful capture took 32:37. This is a host-tool limit, not the gate timeout (`tests/live/test_gen2_frame_align.py:676`).
```powershell
$overlayRepo = 'E:/Google Drive/SLink/.claude/worktrees/mandatory-rom-patch-3fcfda'
$overlayR1 = 'C:/Users/howar/AppData/Local/Temp/claude/E--Google-Drive-SLink/4c3e927b-c467-4a50-9792-2232e4a1d377/scratchpad/r1'
Set-Location $overlayRepo
git status --short
Get-Content "$overlayR1/progress.log" -Tail 30
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'round1b|test_gen2_(frame_align|u1g|write_windows|new_gates)' } | Format-List ProcessId,ParentProcessId,CommandLine
```
Confirm the running process tree belongs to this lane. Do not start another capture against its shared result/SaveRAM paths. `round1b.sh` lives in that scratch directory (lines 5–24 define steps/retries); its final DONE marker alone does not imply all steps passed. Inspect each exit/result and zero skips. Preserve failed logs and archived result traces before another gate overwrites `patch/build/gen2_frame_align_result.txt`.
When the lane is idle, **merge master into this feature branch first**, resolve/review conflicts, then continue. This is not landing the feature into master. `master@735dea38` fixes README port documentation and `test_state_npc_trade_clauses.py:207`; do not re-fix them locally.
```powershell
git log -1 --oneline master
git merge master
$env:SLINK_GEN2_ARTIFACT = 'overlay'
$env:SLINK_LIVE = '1'
$env:SLINK_GEN2_U1_ATTEMPT = '1'
Remove-Item Env:SLINK_GEN2_NO_ATTEST -ErrorAction SilentlyContinue
```
Resume only unfinished steps, in order. U1G must follow its title's frame-align PASS: it preserves that run and adds grass/kyle/bill (`tests/live/test_gen2_u1g.py:113–134,137–179`). A later frame-align overwrites the union, so run U1G again afterward.
```powershell
python -m pytest tests/live/test_gen2_u1g.py -q -p no:randomly -p no:cacheprovider -k gold
python -m pytest tests/live/test_gen2_u1g.py -q -p no:randomly -p no:cacheprovider -k crystal
python -m pytest tests/live/test_gen2_frame_align.py -q -p no:randomly -p no:cacheprovider -k silver
python -m pytest tests/live/test_gen2_u1g.py -q -p no:randomly -p no:cacheprovider -k silver
foreach ($title in 'crystal','gold','silver') { python -m pytest tests/live/test_gen2_write_windows.py -q -p no:randomly -p no:cacheprovider -k $title; if ($LASTEXITCODE) { break } }
python -m pytest tests/live/test_gen2_new_gates.py -q -p no:randomly -p no:cacheprovider
```
Execute these as separate steps: inspect `$LASTEXITCODE` after each command and stop on nonzero; do not paste the entire sequence past a failure. U2's file has town/battle/reload, boxes/reset/reload, active faint and bench tests; selecting the title runs them all (`tests/live/test_gen2_write_windows.py:276,431,512,591`). Silver overlay owns its U2, never Gold's. Inspect covers seven overlay-qualified fixtures and writes `overlay/live_new_gates.inspect_run.json`; no skip/error is a PASS (`tests/live/test_gen2_new_gates.py:586–590`; `tests/live/conftest.py:52–82`).
For a documented RNG-only frame-align miss, retain the failed trace and retry the same command with `$env:SLINK_GEN2_U1_ATTEMPT='2'`, then `'3'` if needed: 11:00 / 11:23 / 11:46, no further seed hunting (`tests/live/test_gen2_frame_align.py:73–85`). Do not retry a pin/identity/guard defect unchanged. Other steps get at most one retry for the exact `RNG_STALL` classes (`tools/gen2_final_sweep.py:55–60`). Never classify every missing downstream poison site as RNG without examining the first failure.
To resume the existing script instead, edit the quoted list to omit completed steps; `frame:silver@2` begins at attempt 2. Do this in the external terminal, after verifying there is no active owner:
```powershell
$overlayJob = Start-Process 'C:/Program Files/Git/bin/bash.exe' -ArgumentList @("$overlayR1/round1b.sh", '"u1g:gold u1g:crystal frame:silver u1g:silver u2:crystal u2:gold u2:silver inspect"') -WorkingDirectory $overlayRepo -WindowStyle Hidden -PassThru
$overlayJob.Id | Set-Content "$overlayR1/resume.pid"
```
The script skips U1G if its journal already contains `STOP-TITLE <title>`; inspect/resolve that earlier failure before resuming the title (do not erase evidence). If the scratch script is absent, use the explicit commands above. If a qualification must be replaced, use a unique attempt id: `python tools/gen2_fixtures.py --qualify-overlay crystal_battle --attempt r1-resume-crystal-battle-UNIQUE` (`:1298–1318`); the seven names are `OVERLAY_QUALIFIED` (`:262`).
Verify each completed capture offline; the live tests themselves re-check hits, ROM/binding, fixture hashes and qualified origin before writing PASS. The discovered receipt test covers overlay U1/U2 (`tests/unit/test_gen2_physical_receipts.py:260–289`):
```powershell
python -m pytest tests/unit/test_gen2_physical_receipts.py -q -k 'test_a_committed_physical_receipt_still_validates and overlay'
@'
import json
from pathlib import Path
from tools import verify_gen2_release as v
from tools.gen2_fixtures import OVERLAY_QUALIFIED
r=Path.cwd(); p=r/'tests/fixtures/gen2/receipts/overlay'
for name in OVERLAY_QUALIFIED:
    f=p/(name+'.qualification.json'); report=json.loads(f.read_text())
    assert report['scope']=='full' and not v._qualification_row_errors(r,name,report,'overlay'), f
a=json.loads((p/'live_new_gates.inspect_run.json').read_text())
assert not v._inspect_run_row_errors(a,'overlay',r)
'@ | python -B -
```
Require all seven qualifications, all three full U1 unions, all three full U2 receipts and the inspect attestation; discovery alone cannot detect a missing file. `Entry.activation_proof` will require the full shipping set (`lua/gen2/entry.lua:69–169,601–612`). Commit reviewed round-1 receipts without relabelling their digest or identity; they are pre-freeze evidence.

## 2. Required code/review work BEFORE the freeze

- Accepted OMP `cx-92b99a75` A1/A3: route engine-sites `clock_setup` through re-derivation. Current `_clock_setup_errors` has only the W6 caller and omits minute (`tools/verify_gen2_release.py:1379–1401,1422–1423`). Thread disclosed minute/second through it and fix the stale sentence in `tools/gen2_synth_fixtures.py:433`.
- A2: newly captured receipts need explicit `u1_attempt` and explicit `clock_setup.game_minute`, including zero; tighten `test_retry_clock_is_prespecified_daytime_and_disclosed` to `.get('game_minute')`. Preserve existing round-1 receipts as recorded; the post-freeze sweep earns new checked-clock evidence.
- Gold detail: validate/rebuild its disclosed `poison_setup` BEFORE applying RTC re-derivation. Its clock base is `gold_synth_psn`, not raw `gold_battle_errand` (`tests/live/test_gen2_frame_align.py:664–671`; captured Gold clock base SHA equals `poison_setup.sha256`). Passing the raw fixture straight to the clock checker is wrong.
- Sweep gap: current `run()` inherits `SLINK_GEN2_U1_ATTEMPT`; `run_cell()` loops 1/2 without updating it (`tools/gen2_final_sweep.py:165–170,318–342`). Before freezing, make U1's RNG retry advance to attempt 2, preserve one automatic RNG retry, add a red test, and define/report how an explicitly authorized third attempt is recorded. Do not claim the present sweep already rotates clocks.
- Shipping-test gap: `test_gen2_entry.py:111–163` checks **clean** copies only (qualifications/synth byte equality; engine/write proven-site equivalence + Lua decode). Existing overlay admission tests validate ownership/refusals, not real shipped/captured parity. Add the analogous overlay checks; the pre-freeze copy audit below checks exact canonical equality. After sweep, compare semantic coverage rather than volatile capture timestamps; never refresh production copies merely to fix equality.

## 3. Produce D6 shipping copies, then activate

No dedicated shipping-copy CLI exists at this cut. This snippet derives the 22 destinations from `Entry.RECEIPT_FILES.*.overlay`; it copies qualifications byte-for-byte, copies O-33 disclosures from beside their SaveRAM, and removes **only top-level `code_digest`** from engine/write receipts. Preserve all identity, runs, fixture/clock/poison disclosures and validation evidence. U1 merging already removes a v1 top-level stamp from its nested run (`tools/gen2_fixtures.py:370–377`). Run only before activation/freeze:
```powershell
@'
import json
from pathlib import Path
from lupa.lua54 import LuaRuntime
r=Path.cwd(); e=LuaRuntime(unpack_returned_tuples=True).eval('dofile')((r/'lua/gen2/entry.lua').as_posix()); count=0
for pack in e.RECEIPT_FILES.values():
    o=pack.overlay
    for rel in [o.engine_sites,o.write_window,*o.qualifications.values()]:
        dst=r/rel; base=r/'tests/fixtures/gen2'
        src=(base if dst.name.endswith('.synth.json') else base/'receipts/overlay')/dst.name
        raw=src.read_bytes()
        if dst.name.endswith(('.engine_sites.json','.write_window.json')):
            d=json.loads(raw); assert d.get('artifact_kind')=='overlay',src
            if dst.name.endswith('.engine_sites.json'): assert d['schema']=='gen2-engine-site-receipt-v2',src
            d.pop('code_digest',None); raw=(json.dumps(d,indent=1,sort_keys=True)+'\n').encode()
        dst.parent.mkdir(parents=True,exist_ok=True); dst.write_bytes(raw)
        assert dst.read_bytes()==raw; count+=1
assert count==22,count
'@ | python -B -
python -m pytest tests/unit/test_gen2_entry.py tests/unit/test_gen2_overlay_admission.py tests/unit/test_gen2_admission.py -q
python tools/gen_gen2_admission.py --provenance data/gen2/build_provenance.json --overlay-provenance data/gen2/overlay_provenance.json --promote-overlays
```
STOP on any error. `activation_blockers` checks signed G4, published UPS/symbol hashes and binding identity/base/hashes; `overlay_proof_errors` runs `Entry.activation_proof` on prospective rows, including production U1/U2 qualification binding (`tools/gen_gen2_admission.py:352–398,578–597`; `lua/gen2/entry.lua:264–295,601–612`). Full release-evidence is deliberately later. G4 is already signed (`docs/gen2/PLAN.md:207`); the playtest is not a blocker.
Expected diff in each generated `admission.json`: overlay FUTURE→SELECTED, BUILT→ADMITTED, G4 runtime_gate/grant_fingerprint and binding_sha256; ROM/base/UPS identities and clean G1 rows stay the same (`tools/gen_gen2_admission.py:213–230`). Do not hand-edit generated rows. Inspect `git diff -- data/games/gen2_crystal data/games/gen2_gold data/games/gen2_silver`.

## 4. Provisioning and the one pre-freeze commit

In the SAME pre-freeze commit, add `"Crystal", "Gold", "Silver"` to `server/cartridges.py:28` `COMPANION_TITLES` and update its stale comments. Do not add another flag or change the browser's patch-first intent.
`test_cartridges.py:235–256` already branches on admission and must now prove Gold/Silver companion output SHA matches each activated row. Update `test_randomizer_js.py:72–94`: Crystal still sends companion=True, but the “does not admit it yet” expectation must become the admitted/no-exception outcome. Check Crystal provisioning explicitly too. Catalog-driven ZIP rules require all overlay files once ADMITTED (`tools/make_release.py:415,624`); losing a proof must fail, never skip.
```powershell
python -m pytest tests/unit/test_cartridges.py tests/unit/test_randomizer_js.py tests/unit/test_make_release_manifest.py tests/unit/test_player_pack.py tests/unit/test_gen2_release_bundle_boot.py -q
python tools/gen_gen2_admission.py --provenance data/gen2/build_provenance.json --overlay-provenance data/gen2/overlay_provenance.json --check
git diff --check
git status --short
```
Review/freeze the exact change with an independent non-author reviewer. Stage the reviewed paths explicitly, then `git commit -m "Gen 2: activate overlay admission and patch-first provisioning"`. Include shipping copies, activation rows, provisioning/tests and all required pre-freeze fixes; no unrelated worker changes. Do not freeze while code/proof-copy edits remain.

## 5. Freeze, sweep, review and pin

`CODE_DIGEST` includes shipped proofs/admission and all server/shared-runtime paths; do not narrow it (`tools/gen2_code_digest.py:25–34,52–77`). After the reviewed commit, require a clean tree and digest `dirty: []`. Preserve the freeze SHA and digest in the coordinator ledger.
```powershell
$overlayFreeze = (git rev-parse HEAD).Trim()
python tools/gen2_code_digest.py
Remove-Item Env:SLINK_GEN2_U1_ATTEMPT -ErrorAction SilentlyContinue
$overlayLanes = 1 # replace only with the coordinator's allocated concurrency
$overlayOut = "C:/Users/howar/AppData/Local/Temp/fsw-overlay-$($overlayFreeze.Substring(0,8))"
python tools/gen2_final_sweep.py --list
python tools/gen2_final_sweep.py --lanes $overlayLanes --sha $overlayFreeze --out $overlayOut
```
Run from the persistent external shell/detached launcher. Expect 148 cells; estimate **6–10 lane-hours**, not measured elapsed time for this new cut. Other lanes share the machine: allocate CPU/emulator slots, verify `Temp/fs1..fsN` are owned/available (the tool recreates them), and never kill global EmuHawk/python process names. The runner kills only its timed-out child tree (`tools/gen2_final_sweep.py:122–152,165–179`). Default is four lanes; set N explicitly.
One retry is permitted only for the recorded RNG classes; guard/identity failures require diagnosis. The U1 attempt-index gap in §2 must be fixed and tested before this command. Preserve failed attempts. Use `--only <exact-cell-id>` with a new output directory for diagnosed reruns at the same SHA; review/merge their summary records by cell ID before pinning, not by overwriting failed evidence.
Require all 148 unique cells PASS, zero unexplained skips, same frozen SHA/digest, and inspect the per-command logs. `--pin` copies only PASS cells and does NOT itself certify completeness (`tools/gen2_final_sweep.py:214–294,403–409`):
```powershell
python tools/gen2_final_sweep.py --pin $overlayOut
python tools/gen_gen2_admission.py --provenance data/gen2/build_provenance.json --overlay-provenance data/gen2/overlay_provenance.json --check
python tools/verify_gen2_release.py --release-evidence
python tools/gen2_code_digest.py
```
Resolve every RED and every unregistered receipt printed by pinning. Commit reviewed captured receipts + requirement pins; do NOT recopy `data/games/**/receipts/overlay` after the freeze: that changes the production digest and requires a new sweep. The final digest must equal the freeze digest even though the receipt-only commit SHA differs.

## 6. Remaining limits and authority

The Gen 3 ancestor-ROM unit failure is environmental: `test_e2e_duo_gen3.py:923–936` deletes its synthetic dump, but `tools/e2e_duo.py:3741–3746` can find a real dump above an in-repo pytest temp directory. Keep it distinct from Gen 2 failures; do not weaken the resolver. README-port and NPC-clause failures are already fixed on master `735dea38` (§1).
Open review work is §2, copy parity, activation/provisioning/bundle checks, and independent review of the frozen cut—not a new G4 signature or playtest gate. SOURCE/MODEL success never substitutes for the PHYSICAL sweep. The owner decisions still needed are **approval to land on master** and **approval to push**. Neither is granted by this runbook; do not invent additional owner gates.
