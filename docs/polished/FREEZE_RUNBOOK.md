# Polished RC freeze re-run runbook (2026-10-09)

A plan, not a result or release authorisation. Run from the **single frozen integration checkout**, not from the old lane worktrees. This inventory covers all **15 LIVE ids** in `tests/polished_release_requirements.json` at `3061ca581`, plus the pending writer/duo/trade evidence. Do not re-stamp an old receipt: re-run its scenario on the frozen code, judge the new bytes, then bind the new evidence.

Commands below are PowerShell. Every evidence destination is fresh under `$F`; retained input paths are explicit. Run each command block with `Reset-PolEnv` as shown: environment from a previous randomized/control case must not leak into an overlay run. Inputs outside the repo are prerequisites, not files shipped to players.

Concurrency labels: **BUILD ALONE** means no other process may use the Polished build caches. **CLIENT SERIAL** means one client-driver job at a time in this checkout: `lua/slink.lua:19` truncates the shared root `slink_lua.log`, so private emulator/SaveRAM paths alone do not make these jobs evidence-isolated. A duo job owns two EmuHawks internally; do not split its halves. **PRIVATE** jobs may overlap one another and one CLIENT SERIAL job after the build is frozen, with distinct output lanes. Do not run tests concurrently with BUILD ALONE. Always stop only the PIDs a driver started; never kill by image name or delete through `.cache` junctions.

1. **Finish fixes, then reserve and record the cut.** No active writer may change runtime, pack, assembly or provenance files after this point. Owner rulings: retire `LIVE-NO-BOX-MON`; in-battle negatives are unit/model-covered; only PHYSICAL natural in-battle faint S2n remains for `OPEN-WRITE-PATH`; S4n accepts whiteout event sent plus all partners dying through per-mon faint (`_handle_whiteout` stays unit-covered). Explode echo fix, capability/Manager flips, trade COMPLETE path and panel readability must be settled before their final runs. Retained examples are DEV, not PHYSICAL qualifications.

   ```powershell
   $PY = 'E:/Google Drive/SLink/.venv/Scripts/python.exe'
   $env:SLINK_WORK_ROOT = 'F:/slink-work'
   $env:PYTEST_DEBUG_TEMPROOT = 'F:/slink-work/tmp'
   $cut = (git rev-parse --short=12 HEAD).Trim()
   $F = "F:/slink-work/lanes/pol-freeze-$cut"
   if (Test-Path $F) { throw 'Choose a fresh freeze attempt; retain the old evidence' }
   New-Item -ItemType Directory $F | Out-Null
   function Reset-PolEnv { Get-ChildItem Env:POL_* | Remove-Item }
   $base = 'F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.gbc'
   $fixture = 'F:/slink-work/lanes/g2int-live/pol/fixture/polished_overlay_warp.SaveRAM'
   $fixtureB = 'F:/slink-work/lanes/pol-ident/B.SaveRAM'
   git status --short --branch
   git rev-parse HEAD
   Get-FileHash -Algorithm SHA256 $fixture,$fixtureB
   ```

   Base release SHA1 is `6930b48af5844d373e3c9130f26d6dd1084cf4ed`; the common fixture SHA256 is `75c7a5dc30126f746567202cfb39fe583dfa04eb226063560541f6cbd29f36b8`. SYNTH ancestry: five level-50 mons, 99 balls and engine-warp position, followed by native SAVE. B is the disclosed second-trainer derivative (`derive_save.py`), not independently played. Current retained overlay is `688945795e2656019247f5aaceb7b1d8791e900a`; read final provenance rather than assuming it survives a new build.

2. **BUILD ALONE: reproduce the clean/overlay build, before any emulator or unit shard.** Shared-cache concurrent private builds previously made BUILD-OVERLAY fail; do not run these alongside another build. If source/provenance must be published, complete that separately before recording the final cut. Assembly/item-table edits require a rebuild, not hand-edited hashes. Version remains `0.1.0` unless the owner changes that ruling.

   ```powershell
   & $PY tools/build_polished_syms.py --check
   & $PY tools/build_polished_companion.py --check --version 0.1.0
   ```

   The verifier's exact BUILD-CLEAN-ROM command is the manifest authority if it changes; check it before executing. Pass requires clean reproduction, overlay byte/span checks, UPS round trip and published sym/map/provenance consistency. A nonzero exit is not permission to repeat an unchanged failed run.

3. **Prepare artifacts and executable pins before the final freeze.** Re-derive beacon/profile/engine sites (the engine-sites generator also writes `write_checkpoint.json`), then commit any resulting artifact changes. A changed trade item table must precede the overlay build. After all changes, record the final HEAD and both digest/provenance hashes, then start the receipt runs. Do not patch a driver pin while receipt jobs are already running.

   ```powershell
   & $PY tools/gen_polished_beacon.py --check
   & $PY tools/gen_polished_profile.py --check
   & $PY tools/gen_polished_engine_sites.py --check
   & $PY tools/gen_polished_pack.py --check
   & $PY tools/gen_polished_forms.py --check
   & $PY tools/gen_polished_script_sites.py --check
   & $PY tools/gen_upr_polished_ini.py --check
   & $PY tools/polished_pin_audit.py
   & $PY tools/verify_polished_release.py --print-code-digest
   Get-FileHash -Algorithm SHA256 data/polished/overlay_provenance.json
   ```

   `title_check.py`, `writes_run.py`, `rival_swap_live.py`, `explode_live.py`, `duo.py` and the trade test driver carry literal overlay pins. The rival route's calibration also binds its overlay. If the freeze rebuild changes the ROM, re-pin/recalibrate first and freeze again; an old route is not a new receipt.

4. **Unit qualification, no emulator.** If shared state/protocol changed, run Gen 3 first, then Gen 1/Gen 2 checks before the full shards. This is the checked-in six-process runner, not a hand-kept file/count recipe.

   ```powershell
   & $PY -m pytest tests/unit -k gen3 -q
   & $PY -m pytest tests/unit -k gen1 -q
   & $PY -m pytest tests/unit -k gen2 -q
   & $PY tools/run_unit_shards.py --shards 6 --out "$F/unit"
   ```

   Evidence: `$F/unit/s1.log` through `s6.log`, file lists and `failures.txt`. These may run concurrently with PRIVATE jobs only if the selected tests do not write a shared build cache; conservative schedule is to finish shards first. Skips are disclosed, never counted as live proof.

5. **CLIENT SERIAL: LIVE-HELLO-ADMITTED, LIVE-HELLO-GATE-FRAME and LIVE-PANEL-HELLO, one shared hello-only run.** The new tree-owned wrapper replaces `F:/slink-work/lanes/pol-rcproof/hello_run.py`: apply the committed UPS, then use `harness.cmd_live` with stage 1. Real server, real client, common SYNTH fixture, no scripted partner.

   ```powershell
   Reset-PolEnv
   & $PY tools/polished_live/hello_live.py --lane "$F/hello" --base $base --fixture $fixture --dry-run
   & $PY tools/polished_live/hello_live.py --lane "$F/hello" --base $base --fixture $fixture
   ```

   New primary evidence: `$F/hello/live/result.txt` for LIVE-HELLO-ADMITTED and LIVE-HELLO-GATE-FRAME; `$F/hello/live/wire/wire_a.jsonl` for LIVE-PANEL-HELLO. Retain `server.log`, `gate_transitions.log`, `sent.jsonl` and `syms.json`. Existing receipt bindings are `pol-phone/live_stageA/result.txt` (both old hello ids) and `pol-rcproof/hello/live/wire/wire_a.jsonl` (panel hello). Judge actual hello `panel=true`, ABI, ROM rehash, admitted server contract and frame ordering; stage 1's PASS alone does not assert panel capability.

6. **CLIENT SERIAL: LIVE-CAPTURE-PARTY-ONLY and LIVE-BOX-CENSUS, shared native catch run.** Requires the frozen companion-overlay cache produced by the build; harness stages that ROM and checks provenance. Native Route 29 input, common SYNTH fixture, real client/server.

   ```powershell
   Reset-PolEnv
   $env:POL_KIND='overlay'; $env:POL_LANE="$F/capture"
   $env:POL_FIXTURE=$fixture; $env:POL_STAGES='1234'; $env:POL_RUNNAME='live_stageA'
   & $PY tools/polished_live/harness.py live
   ```

   Preflight ownership: the zero-write assertion and current quarantine/full-party setup repair are **owned by g2p-legacy** (Codex Polished-2, worktree `pol-legacy`). The command above is the current invocation, not permission to repeat the unchanged incompatible run.

   New primary evidence for both: `$F/capture/live_stageA/result.txt`; retain `server.log`, `sent.jsonl`, wire and census records. Existing binding for both is `F:/slink-work/lanes/pol-phone/live_stageA/result.txt`. **Pre-freeze driver blocker:** `live.lua:444` still requires zero Lua-originated writes. Current box quarantine may legitimately write/deposit the first catch, which also changes the full-party catch setup. The capture/census driver must be adapted to current product behavior before this invocation can qualify these rows; do not disable box capability or suppress the failure merely to rebind an old receipt.

7. **LIVE-R1-MANAGER-PAIR: Manager HTTP proof, no emulator.** Run its three modes sequentially; isolate the Manager's data directory. The current fork jar is `F:/slink-work/cache/polished/jar/PokeRandoZX.jar`; the old trusted-jar control is hardcoded by the driver to `E:/Google Drive/SLink/.cache/slink-upr/PokeRandoZX.jar` (must still be the older non-Polished jar, not silently replaced).

   ```powershell
   Reset-PolEnv
   $env:POL_LANE="$F/random"
   $env:POL_JAR='F:/slink-work/cache/polished/jar/PokeRandoZX.jar'
   & $PY tools/polished_live/manager_r1.py jar
   & $PY tools/polished_live/manager_r1.py nojar
   & $PY tools/polished_live/manager_r1.py oldjar
   $r1 = Get-Content "$F/random/r1_jar/summary.json" -Raw | ConvertFrom-Json
   $mgr = "$F/random/r1_jar/mgr/$($r1.run_id)"
   ```

   New primary evidence: `$F/random/r1_jar/summary.json`; controls `r1_nojar/summary.json`, `r1_oldjar/summary.json`, calls, downloaded cartridges and contract. Existing binding: `F:/slink-work/lanes/pol-rand/r1_jar/summary.json`. Driver exit 0 is not an oracle: inspect HTTP statuses, trusted/fork/Polished fields, source overlay, both downloads and contract SHA1s. Nojar mode clears the env but can still discover a jar by other search paths: verify actual refusal. Run before R2/R3. It can overlap PRIVATE emulator jobs, not a build that republishes its source artifacts.

8. **PRIVATE: regenerate R2's two SYNTH fixtures on the fresh R1 cartridge, not on an old randomized ROM.** Historical retained inputs are `F:/slink-work/lanes/pol-rand/s29/fixture/polished_rand_warp.SaveRAM` and `.../s30/fixture/polished_rand_warp.SaveRAM`; their old encounter tables do not determine the new pair's target. The checked-in setup supports `POL_POS`.

   ```powershell
   Reset-PolEnv
   $env:POL_KIND='rand'; $env:POL_MGR_RUN=$mgr; $env:POL_PLAYER='a'
   $env:POL_LANE="$F/random/s29"; $env:POL_POS='24,3,48,12'
   $env:POL_FIXTURE="$F/random/s29/fixture/polished_rand_warp.SaveRAM"
   & $PY tools/polished_live/harness.py setup
   $env:POL_LANE="$F/random/s30"; $env:POL_POS='26,1,11,48'
   $env:POL_FIXTURE="$F/random/s30/fixture/polished_rand_warp.SaveRAM"
   & $PY tools/polished_live/harness.py setup
   ```

   Native intro/CONTINUE/save surrounds SYNTH party, balls and engine warp; retain both setup `synth.json` files and fixture hashes. Own private SaveRAM directories allow the two setups to run concurrently in separate shells after R1; the block above is the simpler serial schedule.

   R2 fixture regeneration/variant-target selection and the capture zero-write incompatibility are **owned by g2p-legacy** (Codex Polished-2, worktree `pol-legacy`). The retained/current invocations below stay visible until that card supplies the compatible freeze inputs.

9. **CLIENT SERIAL: LIVE-R2-RANDOMIZED-BOOT, two legs.** R2a observes adoption and five fled encounters. R2b catches a variant and proves its key/form and server presentation. The shown historical target `53,2` (Alolan Persian) is executable **only if the freshly generated ROM a's Route 30 encounter table contains it**. R1 uses new random seeds; inspect that cartridge's table and choose a present variant/map before freezing this input specification. Do not run an unchanged 30-encounter hunt for an absent target.

   ```powershell
   Reset-PolEnv
   $env:POL_KIND='rand'; $env:POL_MGR_RUN=$mgr; $env:POL_PLAYER='a'
   $env:POL_LANE="$F/random/live"; $env:POL_EXPECT_KIND='rand_overlay'
   $env:POL_FIXTURE="$F/random/s29/fixture/polished_rand_warp.SaveRAM"
   $env:POL_RUNNAME='r2a'; $env:POL_STAGES='15'; $env:POL_ENCOUNTERS='5'
   $env:POL_MAP='24,3'; $env:POL_HEADER='1,30,9'; $env:POL_WALK='46,51'
   & $PY tools/polished_live/harness.py live
   $env:POL_FIXTURE="$F/random/s30/fixture/polished_rand_warp.SaveRAM"
   $env:POL_RUNNAME='r2b'; $env:POL_STAGES='16'; $env:POL_HUNT='30'
   $env:POL_MAP='26,1'; $env:POL_HEADER='1,13,27'; $env:POL_WALK='9,12'; $env:POL_TARGET='53,2'
   & $PY tools/polished_live/harness.py live
   ```

   New primary evidence: `$F/random/live/r2b/result.txt`; secondary r2a result, both encounters.jsonl, server adoption/table output and wire. Existing binding: `F:/slink-work/lanes/pol-rand/live/r2b/result.txt`. SYNTH fixture, native encounter/catch, no synthetic species substitution. Same capture zero-write/setup incompatibility as step 6 must be resolved before R2b qualification. This LIVE item binds the **source overlay**; executed randomized SHA1 must also be recorded, not made equal to the overlay.

10. **CLIENT SERIAL: LIVE-R3-REFUSALS, four cases; no standalone all-cases oracle.** Real harness plus inspected client/server/wire output. The explicit preparation below copies fresh ROM a, XORs one byte at `0x14E` or `0x1F8028`, and records changed offsets and SHA1s; never alter the Manager ROM. These offsets are historical beacon targets: confirm against frozen beacon data before making mutants. The lane-local preparation is specified here because there is no checked-in R3 all-cases producer/judge.

    ```powershell
    Reset-PolEnv
    $prepareMutants = @'
    import hashlib, json, sys
    from pathlib import Path
    source, out = Path(sys.argv[1]), Path(sys.argv[2])
    data = source.read_bytes()
    out.mkdir(parents=True, exist_ok=False)
    rows = []
    for name, offset in (("flip14e", 0x14E), ("flip1f8028", 0x1F8028)):
        mutated = bytearray(data)
        mutated[offset] ^= 1
        path = out / (name + ".gbc")
        path.write_bytes(mutated)
        rows.append({"path": str(path), "offset": offset, "old": data[offset],
                     "new": mutated[offset], "sha1": hashlib.sha1(mutated).hexdigest()})
    (out / "mutants.json").write_text(json.dumps({"source": str(source),
        "source_sha1": hashlib.sha1(data).hexdigest(), "mutations": rows}, indent=2))
    '@
    & $PY -c $prepareMutants "$mgr/roms/a.gbc" "$F/random/r3/input"
    $env:POL_KIND='overlay'; $env:POL_LANE="$F/random/r3/clean"
    $env:POL_FIXTURE=$fixture; $env:POL_STAGES='1'; $env:POL_RUNNAME='live'
    & $PY tools/polished_live/harness.py live 2>&1 | Tee-Object "$F/random/r3_clean.out"
    $env:POL_KIND='rand'; $env:POL_MGR_RUN=$mgr; $env:POL_PLAYER='a'; $env:POL_EXPECT_KIND='rand_overlay'
    $env:POL_FIXTURE="$F/random/s29/fixture/polished_rand_warp.SaveRAM"
    $env:POL_LANE="$F/random/r3/swap"; $env:POL_SWAP='1'
    & $PY tools/polished_live/harness.py live 2>&1 | Tee-Object "$F/random/r3_swap.out"
    Remove-Item Env:POL_SWAP
    $env:POL_LANE="$F/random/r3/flip14e"; $env:POL_ROM="$F/random/r3/input/flip14e.gbc"
    $env:POL_ROM_SHA1=(Get-FileHash -Algorithm SHA1 $env:POL_ROM).Hash.ToLower()
    & $PY tools/polished_live/harness.py live 2>&1 | Tee-Object "$F/random/r3_flip14e.out"
    $env:POL_LANE="$F/random/r3/flip1f8028"; $env:POL_ROM="$F/random/r3/input/flip1f8028.gbc"
    $env:POL_ROM_SHA1=(Get-FileHash -Algorithm SHA1 $env:POL_ROM).Hash.ToLower()
    & $PY tools/polished_live/harness.py live 2>&1 | Tee-Object "$F/random/r3_flip1f8028.out"
    ```

    New primary evidence: `$F/random/r3_swap.out`; bind all three control transcripts, `input/mutants.json` and wire/log files as secondary evidence. Existing binding: `F:/slink-work/lanes/pol-rand/r3_swap.out`. Clean overlay must admit; swapped contract must server-refuse; altered beacons must client-refuse with no hello. Harness FAIL on an intentionally refused boot is expected recording, not automatically a failed refusal oracle or a PASS. Manual judgment of the four outcomes is still required; no tree-owned all-cases oracle currently completes this receipt by itself.

11. **LIVE-PHONE-ENTRY: historical driver exists, but no current qualifying driver. Do not execute unchanged.** Its reproducible historical invocation is below for the owning repair card. `run_phone_ab.py:17-18` ignores caller POL_LANE and always uses `F:/slink-work/lanes/pol-panel2`; `phone.lua:111` asserts the removed `SLink is linked.` text. This receipt's expectation also names that removed text. It needs an owner-approved obligation/driver cutover, not re-pinning or a fake current PASS.
    Phone text-oracle and fixed-POL_LANE repairs are **owned by g2p-legacy** (Codex Polished-2, worktree `pol-legacy`). Preserve the current invocation below for that owner; this card changes neither driver.


    ```powershell
    Reset-PolEnv
    $env:POL_KIND='overlay'; $env:POL_FIXTURE=$fixture
    $env:POL_ROM_UPS=(Resolve-Path patch/dist/SLink-Polished.ups).Path
    $env:POL_DRIVER='tools/polished_live/phone.lua'; $env:POL_RUNNAME="freeze-phone-$cut"
    & $PY tools/polished_live/run_phone_ab.py
    ```

    Historical-driver output would be `F:/slink-work/lanes/pol-panel2/freeze-phone-$cut/result.txt` (cannot select `$F` without a driver change). Existing receipt binds `F:/slink-work/lanes/pol-phone/phone/result.txt`. SYNTH Pokegear flags and phone-list A/B matrix, native list/submenu/buttons/native-contact control. **Must run alone** after repair if it still has its fixed shared lane. Panel C0-C5 below is not a replacement for the full phone matrix by assumption.

12. **PRIVATE: LIVE-RECEPTIONIST-STACK, exploration B.** Common SYNTH fixture; SYNTH event 33 (`EVENT_GAVE_MYSTERY_EGG_TO_ELM`) plus engine warp to POKECENTER_2F (20:1) at (5,3), then native receptionist input and stack sampling. No real trade/commit proof; it is the old measured stack obligation, not OPEN-IN-GAME-TRADE closure.

    ```powershell
    Reset-PolEnv
    $env:POL_KIND='overlay'; $env:POL_LANE="$F/explore"; $env:POL_FIXTURE=$fixture; $env:POL_EXPLORE='B'
    & $PY tools/polished_live/harness.py explore
    ```

    New primary evidence: `$F/explore/explore_B/result.txt`; retain stacks.json, route, screenshots and symbol resolution. Existing binding: `F:/slink-work/lanes/pol-live2/x/explore_B/result.txt`. Uses frozen shared overlay cache read-only.

13. **PRIVATE: LIVE-POKEGEAR-MEASUREMENT, exploration C.** Common SYNTH fixture and disclosed Pokegear setup. The same lane is safe only sequentially; choose separate `$F/explore-c` for concurrency.

    ```powershell
    Reset-PolEnv
    $env:POL_KIND='overlay'; $env:POL_LANE="$F/explore-c"; $env:POL_FIXTURE=$fixture; $env:POL_EXPLORE='C'
    & $PY tools/polished_live/harness.py explore
    ```

    New primary evidence: `$F/explore-c/explore_C/result.txt`; retain icon tile/OAM/stack evidence. Existing binding: `F:/slink-work/lanes/pol-live2/x/explore_C/result.txt`. Native UI measurement, not real-host panel paging.

14. **PRIVATE: LIVE-TITLE-SPLASH.** Fresh boot with no SaveRAM; tool owns separate overlay and clean-control EmuHawks sequentially. Both use the same judge; clean control must fail the wordmark oracle while overlay passes.

    ```powershell
    Reset-PolEnv
    & $PY tools/polished_live/title_check.py --lane "$F/title" --base $base
    ```

    New primary evidence: `$F/title/evidence.json`; existing binding `F:/slink-work/lanes/pol-rcproof/title/evidence.json`. CGB entrance/settled/menu snapshots only, not DMG or alternate save/menu states. Closes OPEN-TITLE-SPLASH only when this LIVE row passes in the same verifier run.

15. **CLIENT SERIAL: LIVE-WRITES-OVERWORLD.** Common SYNTH fixture; driver invokes real Client:handle_command (TEST HOST), not partner-driven kills. Unset scope reducers. In-battle (c) negatives remain explicitly NOT RUN live and owner-accepted as unit/model-covered.

    ```powershell
    Reset-PolEnv
    $env:POL_KIND='overlay'; $env:POL_LANE="$F/writes"; $env:POL_FIXTURE=$fixture
    & $PY tools/polished_live/writes_run.py
    ```

    New primary evidence: `$F/writes/writes/result.txt`; secondary `trace.json`, exact recomputed party/CartRAM/allocation differences and permit bounds for (a) bench force_faint, (b) box_mon, (d) party_mon. Existing binding `F:/slink-work/lanes/pol-writes6889/writes/result.txt`. Bank-1/one-mon proof, not persistence or a natural in-battle faint.

16. **PRIVATE: LIVE-PANEL-PAGES-ROM, ROM half against scripted host.** Stages the committed UPS, not a mutable cached overlay. Common SYNTH fixture plus Pokegear flags/phone-list setup; C0-C5 protocol/paging/close and bounded mailbox spans.

    ```powershell
    Reset-PolEnv
    $env:POL_KIND='overlay'; $env:POL_LANE="$F/panel-rom"; $env:POL_FIXTURE=$fixture
    & $PY tools/polished_live/run_pol_panel.py
    ```

    New primary evidence `$F/panel-rom/run/result.txt`; secondary panel.json/screenshots. Existing binding `F:/slink-work/lanes/pol-rcproof/panel/run/result.txt`. No real server; does not substitute for host paging.

17. **CLIENT SERIAL: LIVE-PANEL-HOST-PAGING.** Common SYNTH fixture; Pokegear flags/list writes; scripted TCP second identity derived from the save, normal hello/tick/capture events; one real native Route 29 catch by A; real server link_panel -> client hold/stage -> ROM pages. Include the compact/readable 16-glyph row oracle, not only equality with already-truncated text.

    ```powershell
    Reset-PolEnv
    $env:POL_FIXTURE=$fixture
    & $PY tools/polished_live/panel_host_live.py --lane "$F/panel-host" --timeout 2400
    ```

    New primary evidence `$F/panel-host/run/oracle.json`; retain result, wire, persisted links/status, page text and permits. Existing binding `F:/slink-work/lanes/pol-panelhost/run/oracle.json`; readability follow-up is `F:/slink-work/lanes/pol-panelfix/run/oracle.json`, not yet a replacement receipt by editing its hash.

18. **CLIENT SERIAL: rival swap, pending OPEN-EXPLODE-RIVAL evidence (not yet a LIVE id).** Exactly the `calib-68894579` route; SYNTH scene-only fixture plus scripted second trainer; native feedback navigation, real client/server trainer event and swap consumer. Do not use `--fixed-route` for the normal qualified replay.

    ```powershell
    Reset-PolEnv
    & $PY tools/polished_live/rival_swap_live.py --fixture 'F:/slink-work/lanes/pol-rival-live/fixture/rival.SaveRAM' --disclosure 'F:/slink-work/lanes/pol-rival-live/out/disclosure.json' --route 'F:/slink-work/lanes/pol-rival-live/out/calib-68894579/synth-o562jtrj/probe/route.json' --out "$F/rival" --frames 18000 --timeout 600
    ```

    Evidence is `$F/rival/synth-<allocated>/receipt.json`, trace/result/wire and partner/input declarations; allocation is printed by the driver. Current retained PASS `F:/slink-work/lanes/pol-explode2/rival/synth-90mk5ijy/receipt.json`. Dry-run with the same arguments plus `--dry-run` before an emulator grant; a mismatched overlay calibration requires a new route before the freeze.

19. **PRIVATE: explode_live's three cases, pending writer evidence (not yet LIVE ids).** Each invocation allocates a new owned lane and uses direct Entry.build rather than the shared launcher log. SYNTH fixture/logical link; TEST HOST handle_command; native wild route/action/faint. Not server capability/partner qualification.

    ```powershell
    Reset-PolEnv
    & $PY tools/polished_live/explode_live.py --case explode --fixture $fixture --route tools/polished_live/routes/faint_f3_route.json --lane "$F/explode" --timeout 600 --run
    & $PY tools/polished_live/explode_live.py --case active-faint --fixture $fixture --route tools/polished_live/routes/faint_f3_route.json --lane "$F/explode" --timeout 600 --run
    & $PY tools/polished_live/explode_live.py --case bench-faint --fixture $fixture --route tools/polished_live/routes/faint_f3_route.json --lane "$F/explode" --timeout 600 --run
    ```

    Evidence per case: `$F/explode/<case>-<allocated>/probe/oracle.json`, result.txt, input.json and trace.json. They may run concurrently with unique allocations after fixes/build freeze; the block is serial for clarity. Current retained active/bench PASS files are under `F:/slink-work/lanes/pol-explode2/explode/{active-faint-ee5f2c0cb766,bench-faint-4dc72c955269}/probe/oracle.json`. An explode recording PASS is not enough: inspect Python oracle and absence of commanded-death echo. Do not rerun a known echo failure until the fix lands.

20. **CLIENT SERIAL: duo S2n and S4n, separate jobs with two own EmuHawks each.** Native catches/paired link; SYNTH HP=1 conditioning and weak-action setup disclosed by the driver, then native battle faint/copyback/whiteout. Do not replace these with the HP=0/reconnect controls or call SYNTH-conditioned deaths unqualified PHYSICAL evidence.

    ```powershell
    Reset-PolEnv
    $env:POL_KIND='overlay'; $env:POL_DUO_LANE="$F/duo-s2n"; $env:POL_DUO_DEADLINE='900'
    & $PY tools/polished_live/duo.py --scenario faint-natural --distinct-identities --fixture-a $fixture --fixture-b $fixtureB
    $env:POL_DUO_LANE="$F/duo-s4n"
    & $PY tools/polished_live/duo.py --scenario whiteout-natural --distinct-identities --fixture-a $fixture --fixture-b $fixtureB
    ```

    Evidence: `$F/duo-s2n/play-faint-natural/evidence.json` and `$F/duo-s4n/play-whiteout-natural/evidence.json`, both sides' result/trace, wire, server log and SYNTH disclosures. Prior launches used `F:/slink-work/lanes/pol-live/fixture/polished_overlay_warp.SaveRAM` (same disclosed fixture) and `pol-ident/B.SaveRAM`; verify bytes instead of trusting aliases. S2n needs owner PHYSICAL qualification separately. S4n bar is whiteout event sent plus all linked partners dying via per-mon faint; it does not prove `_handle_whiteout` caused the deaths.

21. **BUILD ALONE, then a reserved trade job: trade_duo_live + native-save/cold CONTINUE.** This runner is hardcoded to `F:/slink-work/lanes/pol-tradeduo/{disabled,enabled,client}`. Coordinate with its owner: do not overwrite the retained builds/private client tree while that lane is active. Its two isolated build preparations must be sequential and match the frozen source. Enabled trade is a separately authorised TEST build, never published as the shipped UPS/profile.

    ```powershell
    & $PY tools/build_polished_companion.py --version 0.1.0 --test-output 'F:/slink-work/lanes/pol-tradeduo/disabled'
    & $PY tools/build_polished_companion.py --version 0.1.0 --test-trade-enable --test-output 'F:/slink-work/lanes/pol-tradeduo/enabled'
    Reset-PolEnv
    & $PY tools/polished_live/trade_duo_live.py --fixture 'F:/slink-work/lanes/pol-svclive/apply-done1/attempt-0003/sram_overlay/pol overlay.SaveRAM' --name "freeze-$cut" --timeout 600
    ```

    Evidence: `F:/slink-work/lanes/pol-tradeduo/freeze-$cut/verdict.json`, manifest.json (both ROM identities/gate diff), before saves, state-after-trade.json, wire, durable-a/b.json and a/b g2 cold-ready snapshots. The runner does cold reload **only if both trades finish**; missing cold evidence is NOT_RUN, not PASS. SYNTH receptionist fixture, derived B identity and one server link seeded through normal state events; native client/receptionist/commit/save afterward. Trade COMPLETE fixes must land first. Shipped overlay's commit-disabled hash and enabled test hash differ: this test cannot satisfy a shipped-ROM-bound LIVE item by inventing equality. Owner must decide shipped enablement and the receipt contract before OPEN-IN-GAME-TRADE can close. No distinct trade LIVE item currently exists.

22. **Rebind only judged new evidence, after all jobs finish.** Receipt writer records final HEAD/source hashes, `--print-code-digest`, provenance SHA256, executed ROM SHA1 (or source-overlay binding for R1/R2/R3), the new primary path/size/SHA256, secondary evidence and exact observed PASS checks. Preserve grade DEV; PHYSICAL is an owner act. Keep failed attempts; never overwrite their evidence or promote a recording PASS over a red oracle. `LIVE-PHONE-ENTRY` and the capture/R2/R3 gaps above must be fixed/disposed by their owners, not silently omitted. Any later digest-scoped edit revokes the cut and requires re-running affected receipts. Manifest/receipt/doc changes themselves are outside its code_digest_files.

23. **BUILD ALONE: final verifier, including BUILD-OVERLAY, then owner decision.** All emulators/private builds must have finished so the full gate cannot race their caches. First list confirms the LIVE census and closure ids; targeted runs are diagnostic only. Full verifier consumes every receipt and re-hashes its evidence; CLOSED needs its closing LIVE item to PASS in the same run.

    ```powershell
    Reset-PolEnv
    & $PY tools/verify_polished_release.py --list
    & $PY tools/verify_polished_release.py --json | Tee-Object "$F/verifier.json"
    ```

    `--only` and `--no-release` are not release verdicts; red is honest. Keep the six-shard logs, build logs and final verifier JSON with this cut. Vanilla Gen 2/C-5 qualification remains a separate gate (`docs/gen2/C5_RUNBOOK.md`), not implied by Polished solo/duo receipts. Owner ruling remains keep local: no master merge, push, release or lane deletion is authorised by a green runbook invocation.
