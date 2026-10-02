# Gen 4 resume note

## Checkpoint 10 (2026-10-02 18:40Z) - adoption milestone CLOSED; live re-run at FROZEN `feb6b9c4`; session WRAPPED

**Cut `feb6b9c4`** = the shared NDS adoption (`8a36e6ee`, `36fd0615`, `b4e17db2`) + the hge row-k fixed-frame RTC fix (1200 = measured max 1035 + 165).

**PHYSICAL results at `feb6b9c4`**, all coordinator-verified: combined read back, control-reds missed=[], row o via consume_receipt.

| Cell | Verdict | Receipt (`C:/slink/g4/`) |
|---|---|---|
| Row o HG one / two | PASS / PASS | `g1d-hg1-1400`, `g1d-hg2-1402` |
| Row o hge one / two | PASS / PASS (the first live run of the pack-pinned hge seam) | `g1d-hge1-1403`, `g1d-hge2-1404` |
| HG a–n | FAIL: m (fight timeout); b/f/n OPEN; the rest PASS | `g1dprobeHG-1405/heartgold-aea65d46ec72/combined.txt` |
| hge a–n | FAIL: b (indoor fixture, no battle); f/m/n OPEN; the rest PASS (k now PASS at 1200/1200) | `g1dprobeHGE-1417/heartgold_hge-a5da2f1e3fff/combined.txt` |
| SS a–n | FAIL: b (indoor fixture); f/m/n/o OPEN; the rest PASS | `g1dprobeSS-1425/soulsilver-2f9d94e5ba0f/combined.txt` |
| PERF (f) | OPEN: a foreign Gen 2 EmuHawk was running at the preflight (PIDs 30896 / 32612) | none started |
| Final audit | 44 owned processes all exited; originals unchanged (HG e18a15c7, SS 8b6fbf17, hge a9e4a48b) | `C:/slink/g4/g1-feb6b9c4-final.json` (sha256 55ef363e) |

**What the cut proved:**
- The k fix works physically on all three titles.
- Production residency adoption plus the pinned hge seam: all 4 faint cells PASS.
- No settle or pin faults.

**New defect from the k fix:** waiting to frame 1200 shifts the RNG. On HG the encounter (Cyndaquil Lv5 vs Rattata Lv4, normal) overran the fight leg's 3000-frame budget, so HG m FAIL. Baseline i was unobserved, but the i SAVE/cold-read cases PASS. Enemy-HP movement is UNVERIFIED (no per-turn trace). `max_frames` is a pack value, so it was not changed in this cut.

**Still open:** G1 is NOT qualified or signed.

**NEXT SESSION, in order:**
1. Add per-turn enemy HP + frames-used telemetry to the fight leg; size the budget from the measurement (pack). Then re-run HG m/i.
2. b on hge/SS: a battle route on those fixtures.
3. n: PC withdraw leg (live Right+A trial, G2_PRODUCER_PLAN §6b) + a queued-event-at-close witness.
4. PERF on a quiet machine.
5. C1 live mailbox canary (4 KiB ITCM span), then C2.
6. Owner questions: the FAILURE sound; whether C5 keeps a box arm.

## Checkpoint 9 (2026-10-02, owner: "Do the Gen 4 adoption cut now") - shared NDS adoption cut DONE (SOURCE/MODEL)

- **Commits:**
  - `8a36e6ee` imports the shared stack @`b13c897f` as a file import, not a merge (master 735dea38 is not an ancestor). It is blob-identical, and 604 shared tests pass in this tree.
  - `36fd0615` makes pk4 delegate its cipher to the injected `lua/nds/pkm45_crypto.lua`. `BOUND_MODULES` and the perf `MODULES` bind it.
  - `b4e17db2`:
    - production `hook_binding` / `phase_signals` adopt `residency_contract`: arm = table-active AND full pin; loading refusals counted; latch only after `settle_polls=16`; `may_fire` at context; battle end always disarms.
    - The D7 seam pin is FILE-proven on every build: the hge pack gains addr 35951836 + pin `004a1047`, and the client never mints a pin from RAM. (Codex cx-e7249b41 did the binding; the coordinator did the pack and pk4 halves.)
- **Verified:** gen4+nds suites 2633 passed (coordinator, independent); Codex reports gen4 1611 and nds 617. The only red is the out-of-scope `test_gen3_borrowed_rows` (needs `patch/build/slink_RR.gba`).
- **ALL `aa45dd94` PHYSICAL receipts are STALE at HEAD.** The evidence surface globs `lua/nds/*.lua` and hashes pk4, the binding and the hge pack.
- **Next:** the live re-run at `b4e17db2`: row o ×4, HG/hge/SS a–n, plus the D7 seam on hge, now pinned. It needs an owner go-ahead for the emulator lane and must avoid foreign EmuHawks. The hge k fixed-frame fix should ride in the same cut first (replay staged in `.cache/gen4-next-cut/replay_hge_rtc_frame.py`).

## Checkpoint 8 (2026-10-02 12:25 EDT; owner timebox: stop 13:31 EDT / 17:31Z; final status appended at stop)

### G1 carry-over
- **Current FROZEN cut: `aa45dd94`.**
  - It adds the settle-arm probe: an overlay site is armed only when table-active AND its full pin matches, with HG bound 16 = measured 11 + 5. The measurement is the serial DIAGNOSTIC `C:/slink/g4/g1-settle-HG-1144-serial`: table-active at 7325, ready at +10/+11.
  - It adds the hge `load_arm9_expansion` symbol row.
  - The previous cut `6290dd3a` added: hge census `internal_loads` (async ids 130/131), publish on every aborted attempt, the Windows replace retry, exact pin-site diagnostics, and the row-o fight recipe.
- **HG at `aa45dd94`** (`C:/slink/g4/g1cprobeHG-1201/heartgold-a48971929487/combined.txt`, coordinator-verified): a,c,d,e,g,h,i,j,k,l,m,o PASS; b/f/n OPEN; missed=[]; RESULT OPEN.
  - n's raw per-case case is a coverage FAIL: `static_pc=false/reset=false`, queued-event-at-close not exercised.
  - b: the wrong-overlay collision was not observed.
  - f: PERF, blocked by foreign EmuHawks.
- **Row o, all 4 current PASS at `aa45dd94`** (consume_receipt verified by the coordinator): HG `g1b-hg1-1119` and `g1b-hg2-1122` (from 6290, still current); hge re-runs `g1c-hge1-1222` and `g1c-hge2-1224` (the 6290 hge pair is historical/stale).
- **hge k replay (scratch, not frozen):** `.cache/gen4-next-cut/replay_hge_rtc_frame.py` is red on 977/979 for the next cut.
- **hge at `aa45dd94`** (`C:/slink/g4/g1cprobeHGE-1215/heartgold_hge-08256aad427a/combined.txt`, coordinator-verified): a,c,d,e,g,h,i,j,l PASS; **b FAIL, k FAIL**; f/m/n/o OPEN; missed=[]; RESULT FAIL.
  - c: 20/20 transitions matched, including 129/131 at lag 1.
  - **k FAIL: "RTC compared at different frame counts" (977 vs 979).** The bytes are identical, so this is a harness sampling point that drifts with boot length. Codex's note misreported it as PASS. Next cut: a red-first fixed-frame k sample.
  - b raw FAIL: no own-overlay faint trigger on the indoor fixture.
  - m/n named OPEN: no battle route; PC withdraw unrouted.
- **SS at `aa45dd94`** (`C:/slink/g4/g1cprobeSS-1227/soulsilver-410efd246406/combined.txt`, coordinator-verified; the first SS a–n): a,c,d,e,g,h,i,j,k,l PASS; b FAIL (no battle faint trigger in the indoor subset); f/m/n/o OPEN; missed=[]; RESULT FAIL.
  - k PASS on SS (frames 1025/1025). This supports the hge k drift being a hge boot-length sampling issue.
  - SS row o has never run; it needs SS battle states.
- **b FAILs on hge and SS** share one cause: the prepared indoor fixture has no battle. Row b needs a battle route on those titles (as HG's phase legs have).
- **Historical (do not relabel):**
  - HG `g1bprobeHG-1125` at 6290: n FAIL from the async-load race;
  - hge `g1bprobeHGE-1135` at 6290: c FAIL from the missing symbol;
  - c935: `g1probeHG-1033` and `g1probeHGE-1058`.
- **Production follow-up:** `lua/nds/hook_binding.lua:105-107` has the same async-load exposure ("resident" = table flag alone). The fix comes with the NDS-3 residency-contract adoption (`may_arm` requires `site_confirmed`). First falsifier: an ov12 site armed during the load window.

### Companion (plan C0-C8)
- **C0 DONE** (`9b5c7a25`): pret `ad7a3afa` rebuilds HG and SS byte-identical on hgbox.
- **C1:**
  - census + canary authored (`82edb0f2`);
  - span widened to 4 KiB, ITCM 0x01FFEC00..0x01FFFC00, so the shared ABI arena fits unmodified (`29febbf3`); census PASS on HG/SS/hge;
  - the **live canary run is pending a free lane**. Command in the C1 Sonnet report: `SLINK_LIVE=1 ... pytest tests/live/test_gen4_mailbox.py -m live`. Register a permanent `mailbox` kind in `tools/gen4_evidence.py` (it is currently a setdefault at import).
- **Decisions recorded in FEATURE_BAR:**
  - ScrCmd slot = opcode 1, not 486 (486 is executed by scripts); the opcode-1 gate passed by composition;
  - sound codes: SUCCESS 1501, NOTIFY 1500, BOO 1536 provisional; **FAILURE has no HGSS SE, an owner content choice**;
  - the trade copies the NPC-trade slot-overwrite shape; the box arm is new behaviour;
  - service tick = one `mainTaskQueue` SysTask;
  - C4 panel: HG/SS append an After-main overlay; hge uses the 0x021E5900 slot; the trainer card is a lifecycle template only, its exit is asm;
  - hge start menu, `start_menu.o`, is identical to HG;
  - C2 layout direction: shared ABI + ROM-only boot generation + liveness pair.
- **Owner questions to raise:** the FAILURE sound choice; whether C5 keeps a box arm.

### G3 research
- **The new-game route is fully sourced** (`docs/gen4/research/new_game_route.md`): legs, warps, mom MAP-INIT, YES defaults; a blind A,A,A picks Chikorita.
- **PC withdraw:** the box app is ov14 asm; the dirty signal is a per-box mask. Next step: the live Right+A trial from `G2_PRODUCER_PLAN.md` §6b (assert data+0x2C==8, data+0x30==9).

### Shared NDS (Gen 5, `claude/nds-shared-stack`, local only)
- Commits: 5a7c45f5 (NDS-3), 4cd04812 (NDS-2), 0c680554, e2cb38e4 + 3c252ace (NDS-1), bfafb93b (NDS-4), 5cf43acb (NDS-5). NDS-6 composer in flight.
- All Gen 4 requirements were sent and accepted.
- Later commits: 4ff3e193 (abi asserts) and 9731330a (contract tightening that affects adoption: SitePin decodes the first instruction under the declared isa (`data=True` for literal sites); `continuation` is an absolute RAM address in a pinned container; autoload accessors return an AutoloadBlock).
- **Adopt in ONE Gen 4 cut next session:** pk4.lua -> `pkm45_crypto`; hook_binding -> the residency contract. Then live receipts on HG/SS/hge.

### Stop state (2026-10-02 16:37Z, owner timebox)
- **Nothing in flight.**
  - Codex card cx-b0f03f97 is complete and the lane released; its final audit is `C:/slink/g4/g1-aa45dd94-final.json` (24 cleanup records, originals unchanged).
  - OMP 13112 and 21352 are idle, with all outcomes recorded. No Sonnet running.
  - The only EmuHawk is foreign PID 45616 (Gen 2, gen2_frame_align.lua), untouched; PERF stays blocked while it runs.
- **G1 is NOT qualified and NOT signed.** At `aa45dd94`:
  - HG OPEN; hge FAIL (b, k); SS FAIL (b);
  - all 4 row-o cells PASS;
  - PERF OPEN.
- **Next session, in order:**
  1. **hge k:** fixed-frame RTC sampling. The red-first replay is staged in `.cache/gen4-next-cut/replay_hge_rtc_frame.py`.
  2. **b/n prerequisites:** a battle route for hge/SS b; the PC withdraw leg (live Right+A trial, §6b); a queued-event-at-close witness.
  3. **Shared NDS adoption cut:** pin `claude/nds-shared-stack` head **`b13c897f`** (`C:/slink-wt/nds-shared`; 12 commits over master 735dea38; 563 shared tests; NDS-1..6, with NDS-6 = `tools/nds_companions.py`). It brings the production residency fix. Gen 5's resume note: `docs/gen5/RESUME.md` checkpoint 4. Host composition rows in `server/**` and depth-1 lua stay for the batched G3a window (Gen 2 digest).
  4. **C1 live canary** on the 4 KiB ITCM span (HG/SS/hge), then C2.
  5. **PERF** on a quiet machine.
  6. **Owner questions:** the FAILURE sound; whether C5 keeps a box arm.

### Other
- Spawned chip: the `tests/conftest.py` cross-drive relpath INTERNALERROR (shared file).
- OMP peers 13112 and 21352 are idle with all outcomes recorded. Codex is running hge/row-o/SS until the 17:05Z launch guard.

## Checkpoint 7 (2026-10-02 11:30 EDT, owner timebox: stop 13:31 EDT / 17:31Z)

- **Companion C0 is DONE** (`9b5c7a25`).
  - The pinned pret `ad7a3afa` rebuilds HG `4fcded0e` and SS `f8dc38ea` byte-identical on hgbox; the coordinator re-hashed both.
  - The dumps are in `C:/slink-cache/gen4-pret/`.
  - Consequence: no free static RAM. C1 must ALLOCATE the mailbox; the lead is the ITCM arena tail 0x01FF8620..0x02000000 (FEATURE_BAR, last section).
- **hge identity** (`4b2d4144`):
  - `start_menu.o` is static ARM9 and byte-identical in HG and hge.
  - `gScriptCmdTable` differs only at #208; #486 is Dummy in both.
- **In flight:**
  - Codex: FROZEN `c935530b` G1 runs. The HG aggregate is offline-recovered (`g1probeHG-1033`): a,c,d,e,g,h,i,j,k,l,o PASS; b/f OPEN; m/n FAIL.
  - Sonnet: C1 offline authoring (census + canary live watch).
  - OMP 21352: cx-00760b09 (opcode-486 usage).
  - OMP 13112: cx-23a2453d (sound id mapping).
- **The next FROZEN cut bundles five items:**
  1. hge census `internal_loads` wiring (a harness gap: nothing sets it; PLAN:272);
  2. publish-before-assert, `test_gen4_probe_gates.py:1578`;
  3. a bounded retry for `Path.replace` WinError 5 (`:1274`, `:1280`);
  4. the fight recipe (a Codex diff, landed by the coordinator in the pack);
  5. the HG reset-phase pin mismatch (path requested).
  Then the a–n re-run, and PERF last.
- **Gen 5 shared NDS:** cards 2-3 were reviewed and answered. Adoption waits for committed shas and for the end of the FROZEN runs.

## Checkpoint 6 (2026-10-02 08:50 EDT, recovery after a machine crash, unrelated to the work)

**Owner instruction:** "Stop at the next milestone." The milestone is the **G2 signature package**.

**Post-crash recovery check (coordinator):**
- HEAD is `c6977960`. `git rev-list --objects c8b7a99f..HEAD` shows no missing objects.
- The owner saves and the SYNTH saves in `C:/slink/g4/saves` are intact.
- The guide JSON parses.
- No EmuHawk is running.
- The pre-existing `.git/refs/heads/master (1)` (Drive conflict copy, dated Sep 23) is NOT ours and was left alone. The real master is `735dea38`.

**Committed today (all verified: tests + ruff + `--check`; independent OMP reviews reconciled, each finding fixed or rejected with evidence):**

| Commit | What |
|---|---|
| `997c4977` | Owner rulings: row i persistence-only; row c 0..2 frames |
| `211b1625` + `9d6c8fbf` | SYNTH `party6` / `species` (hge forme ids refused, MAX_MON_NUM 1075) |
| `a11831be` | Pace test fixes |
| `20b03aea` + `3745647c` + `391b7df2` | Acquisition reachability: 61/61 sites `resolved` with cited story gates; CallStd modelled; hge member-3 paths flagged `inherits_unproven` |
| `7dbc1cfc` | hge box dirty flag `0x1E004` (PHYSICAL PCDIFF) |
| `b8150e11` | Pack `battle.d7` |
| `3f5f447d` | SYNTH `place` + pack `field_save` offsets + d7/probe_field review fixes. **Packs FROZEN here.** |
| `12a05f6e` | Receipts bind the evidence surface (`tools/gen4_evidence.py`), not HEAD; PC/hatch receipts carry counter + keys |
| `5dba81b9` | PERF producer bound to the evidence surface |
| `dbec8e7c`, `056dcf71`, `c6977960` | Client `lua/gen4/client.lua` steps 0-6 + review fixes: boolean D7 lease, party signature (792 to 116 reads/frame), fail-closed pre_pump, PartyExtra shift. **Client FROZEN here.** |
| `970b2736` | `protocol_schema` `sync_retrieve_failed.reason` (shared test file; core/gen1/gen2 all send it) |
| docs | `synth_place_save_layout.md` (its SavedMapObject offsets are superseded by `3f5f447d`); `new_game_route.md` (the waitButtonMode note is INVERTED: mode 0 waits for A, mode 1 auto-advances, per OMP cx-fa2be506; starter = 3×A, OVY_61 in the field child slot, trigger tile (8,4)) |

**In flight at the crash: Codex "Gen4 Worker", card cx-42ec6089 Part 3. UNCOMMITTED in the worktree, intact; 315 offline tests green; ruff clean.**
- Files: `tools/gen4_evidence.py`, `tools/gen4_routes.py`, `lua/tests/gen4_route_play.lua`, `lua/tests/probe_gen4_hooks.lua`, `tests/live/test_gen4_probe_gates.py`, `tests/unit/test_gen4_routes.py`.
- Contains:
  - row i persistence and row c 0..2 lag;
  - control publish-before-assert (`control-reds.json`, `combined.txt`);
  - the CONTROL_REDS set assert;
  - the 7-key throttle model;
  - `first_field_live_frame == 1`;
  - a partial route-leg bridge.
- Safety copy: the session scratchpad `codex_part3_wip_postcrash.patch`.

**Next, to reach the milestone:**
1. Codex finishes Part 3 and reports hashes; the coordinator commits. That commit is the FROZEN cut.
2. Codex runs the bound landing re-runs, at most 2 lanes: PC deposit/SAVE/reload, catch and hatch on HG/SS/hge, plus faint on HG/hge (one-mon and 2-mon).
3. The coordinator presents the G2 cell table (`G2_PRODUCER_PLAN.md` §6) for the owner signature, then STOPS.

**G2 SIGNED 2026-10-02** (`docs/gen4/reviews/G2_SIGNATURE_2026-10-02.md`); ruling 35 accepted.
- Landing runs at the frozen cut `c1123171`: 9 G2 cells PASS (see the package).
- **G1 row o:** hge one-mon faint PASS, bound, verified by `consume_receipt` (`C:/slink/g4/g2faintHGE1-0932`).
- **Not run (stopped at the milestone):** HG one-mon and two-mon faint, and hge two-mon faint. Preparation-only lanes `g2faintHG2-route-0932` and `g2faintHGE2-route-0936` are left on disk.
- Codex: all 52 owned PIDs exited and the original saves are unchanged. A running EmuHawk at the stop (PID 41196) is a Gen 2 gate run from another lane; it was left alone.

**Queued after the G2 re-runs** (it touches frozen surface files): OMP cx-3bab37d5's review of `3f5f447d`.
1. **F1 MAJOR:** `place` never writes SavedMapObject `vecY` (+0x2C, the world height restored at `map_object.c:494-496`), and `--height` writes only `currentY`. Either refuse a cross-map place, or write `vecY`, and pin +0x2C in the tests.
2. **F5:** the save_state cite should be `:365-374`.
3. **F3:** derive the FieldSystem-level probe key set instead of hand-listing it.
4. **F2:** the temp-flag branch is dead; the tests should assert reasons.
5. **F4:** pin `bics`/`str` at +0x54/+0x58.
6. **F6:** hgss map_objects 0x2348 IS summable (SOURCE+FILE).
7. **F7:** there is no map-bounds gate.
8. **F8:** read VAR_BASE/NUM_VARS from the pack.
9. **F9:** document that all five Locations are written.

**Also queued (client, G3):** OMP cx-09f09a39's review of `c6977960`.
1. **F1 MAJOR:** the PartyExtra pack gap disables box_mon/party_mon/memorialize-from-party in production. Use a pret-sourced `PERFORMANCE_MAX = 5` plus array bounds instead.
2. **F2:** bound `mons_off + 6*psize <= party_size`, and stride == 5.
3. **F3:** a dropped key_change must be server-visible, not log-only, and needs a larger cap. NOT a HUD notice (owner rule: the HUD is player-facing only).
4. **F4:** test the bounds.
5. **F5:** the write-count test should be against span bytes, with a 6-mon fixture.
6. **F6:** rename the read-budget test, and add a box-pass bound (~1080 reads).
7. **F7:** party analogue of the box flags test.
8. **F8:** on_reset should disarm the hook.
9. **F9:** derive SIG_OFFS from pk4.
10. **F10:** do not queue a "lease already used" event.
11. **F11:** rename the test.

**2026-10-02 afternoon:**
- Step 1 fixes are committed: client r3 `c32ce7d2`, place/pack `c935530b`. **New FROZEN cut: `c935530b`**, which supersedes the c6977960 client freeze noted above.
- Owner: keep HG and SS in the RC (not hge-only). hg-engine cannot build on SoulSilver as-is: the fork's Makefile gates on gamecode IPKE.
- **Queued client minors (OMP cx-c01cf37c):**
  - N2: a PartyExtra `off != base` override needs a cite.
  - N3: `cite` should be validated, not a bare string.
  - N4: delete the unreachable bound.
  - N5: surface or drop the `d7_stray`/`refires` counters.
  - N6: carry `new_species`/`new_nickname` on the queued key_change note.
  - N7: relax the burst-count assertion.
  - **Rejected:** N1, verified against the real hge fork.

**G1 row o COMPLETE at FROZEN `c935530b`** (all verified with consume_receipt by the coordinator), all in `C:/slink/g4/`:

| | One-mon | Two-mon |
|---|---|---|
| HG | `g1hg-one-1018` | `g1hg-two-1022` |
| hge | `g1hge-one-1026` | `g1hge-two-1029` |

Two-mon runs: replacement, slot 1 sent in, slot 0 zero in the save, no whiteout. Next: probe a–n per-case on HG/hge/SS, then PERF last on a quiet machine.

**OWNER RULING 2026-10-02: ROM companion patch REQUIRED for the first Gen 4 RC, at the Gen 1/2 feature bar** (DECISIONS). This adds a companion workstream before G4, re-runs every PHYSICAL receipt on the patched ROMs, and coordinates with the Gen 5 shared NDS companion stack.

**Open owner items:** ruling 35 at G2 (ACCEPTED). Deferred G3 work, not part of the milestone: the live client smoke test; the new-game route card; the physical boot check for `place`; the pack `party_off.extra` geometry the client needs before deposits work in production.


## Checkpoint 5 (2026-10-01, end of the owner-timeboxed session)

- **Worktree/branch:** `.claude/worktrees/gen4-support-framework-dfd5e2` on `claude/gen4-support-framework-dfd5e2`. It merged master `ea9c8a07` at `9033a7be`, and nothing has gone to master or been pushed. A master landing needs its own owner yes. `server/adapters/gen4_codec.py` is `server/**`, so ping Gen 2 at landing.
- **Gates:**
  - **G0** is SIGNED: `docs/gen4/reviews/G0_SIGNATURE_2026-10-01.md`.
  - **G1** is PROVISIONALLY SIGNED (owner: "Consider all signatures signed for now"), recorded in `docs/gen4/reviews/G1_SIGNATURE_2026-10-01.md`. Its open rows are carried as work and were not converted to PASS.
  - The session then worked toward **G2**.
- **Owner rulings and standing rules** are all in `docs/gen4/reviews/DECISIONS_2026-10-01.md`:
  - **D7 latency:** the faint lands at the end of the current turn, using the normal faint animation (the cmd-11 + FAINTED-bit seam; on hge, cmd 9).
  - **Performance:** real play must hold 1x continuously. 1x is the native NDS 59.8261 fps plus host jitter. The design uses zero steady-state exec hooks, polls everything, and arms one on-demand hook for the D7 write.
  - **SYNTH setup** is allowed for any row, provided it is disclosed (sidecar hash) and the behaviour under test runs natively.
  - Up to two concurrent functional emulator lanes are allowed. PERF needs a quiet machine.
- **Owner saves** (backed up in `C:/slink/g4/saves/`):

  | Save | Trainer, TID |
  |---|---|
  | HG base | 26310 |
  | SS | DDDD, 25944 |
  | Pt | TTT, 44361 |
  | hge A | OOO, 630 |
  | hge B | JIII, 31846 |

  D3, D4 and D15 are met. The hge ROM copies are `E:/Google Drive/SLink/hg-engine.nds` and `hg-engine-b.nds` (main checkout root, gitignored; both byte-identical to the pin `cb2dc435`, two names only so BizHawk keeps two saves). The pinned build is also at `.cache/gen4/hge/build-fc5175764983/test.nds`.

### PHYSICAL evidence on this branch

| Item | HG | SS | hge | Commit / receipts |
|---|---|---|---|---|
| Row o, in-battle linked faint, one-mon whiteout | PASS | n/a | PASS | `a15b7d74`, `0f75c938`, regression `ae0995dc` |
| Row o, 2-mon replacement path (SYNTH party2) | PASS | n/a | PASS | `de7fc1b2`, hardening `7a234174`; PASS runs `C:/slink/g4/faint2/heartgold_seam_turnend_p2_201327`, `heartgold_seam_ufce_bit_p2_201242`, `_201440`, `heartgold_hge_seam_turnend_p2_201400`, `heartgold_hge_seam_ufce_bit_p2_201513` (`_201013`/`_201104` were OPEN pre-fix attempts) |
| PC deposit, native SAVE, cold reload (row i box leg, G2 fixtures) | PASS | PASS | PASS | `02705ce5`, `01dd2bb3`, hardening `8db9c26f` |
| Dirty-flag offset (HG 0x12004, hge 0x1E004) | measured | measured | measured | RAM: set by deposit, 0 after SAVE and load. The saved battery keeps 1 (`f426a76b`). |
| Wild capture (SYNTH bag) | PASS | PASS | PASS | `6676a13b`, `2a43bfb6`, `76ec3bac`; `C:/slink/g4/catch/catch_203302`, `catch_hge/catch_203823`, `catch_ss/catch_204123` |
| Egg hatch (SYNTH egg1) | PASS | PASS | PASS | `8db9c26f`, `76ec3bac`; `C:/slink/g4/hatch`, `hatch_hge`, `hatch_ss` |
| 1x performance | 0-hook rows met the rule. The 1-hook row had p99 +2.2 ms, accepted under the G1 signature. | n/a | same | These receipts are refused by the hardened validator (`8b5047c2`), so they need a re-run at the current cut. |
| G1 rows a, c–e, g, h | PASS in the `baseline` case of `C:/slink/g4/probe/shakedown-hg-ac0d70aa43` (cut `abf2b72c`); j–l passed only on the earlier cut `C:/slink/g4/probe/heartgold-0cc5b0ee2c21` | | | All of a–n need a re-run at the landing cut, on HG and hge. |

### Committed G2 client modules

These are offline and lupa-tested, with independent OMP reviews reconciled:

| Module | What it does |
|---|---|
| `lua/nds/hook_binding.lua`, `lua/nds/phase_signals.lua` | Default cap of 1 hook, plus on-demand `request()` |
| `lua/gen4/pk4.lua` | Record format, with torn-read and plausibility guards |
| `lua/gen4/reads.lua` | Zero-hook battle chain, double-read |
| `lua/gen4/poll_events.lua` | Wire events by polling; whiteout = the LOSE latch |
| `lua/gen4/safety.lua` | Checkpoint predicate |
| `lua/gen4/entry.lua` | Hash admission plus anchor floor |

Supporting tools and data:
- Packs: `data/games/gen4_*/profile.json`. They hold battle, enums, route_legs, phase_cases, diagnostic sites and admission anchors.
- G2 data: area map, encounters, trainers, acquisition (HGSS + hge) and names. The hge acquisition proves script bytecode and source-level dispatch (`34efe45f`).
- `tools/gen4_synth_save.py`, with kinds party2, bag and egg1. The bag writer refuses an unverified layout: it checks pocket classes (vanilla from pret, hge from the fork) and contiguity (`36f9cec3`, `8637544c`).
- `tools/gen4_routes.py`, with targets battle, pc and hatch and the Pokégear errand, for HG, SS and hge.
- The producer plan, with its G2 checklist: `docs/gen4/G2_PRODUCER_PLAN.md`.

### Next actions

1. Commit or reconcile anything listed under "In flight at stop" below.
2. Re-run gen4-PERF at the current cut:
   - Set `SLINK_GEN4_<TITLE>_SAVE` and the `_STATE` env vars.
   - Run on a quiet machine, so the run is not concurrent with Gen 3 duo runs.
   - Row f stays OPEN until a bundle binds the current HEAD.
3. **G1 rows a–n.** The HG shakedown at `abf2b72c` (`C:/slink/g4/probe/shakedown-hg-ac0d70aa43`) PASSed a, c, d, e, g and h in its `baseline` case. `patched-rom` (j: ROM hash differs) and `rtc-unpinned` (c: unpinned core settings) are targeted control reds (OMP cx-9265e740). `no-buttons` l FAILs with "buttons-only CONTINUE failed". `party-write` FAILs every row because its CONTINUE never reached the overworld: that is the PC-facing boot defect fixed in `c5cca903`, NOT a control. The wrapper does not yet assert expected control reds. g PASSes in every case. and `profile.rtc` has landed (`5e232930`). Two gaps in the C1-1 gate wrapper (`tests/live/test_gen4_probe_gates.py`) block a full pass:
   - It does not bridge the route tool's legs (`gen4_routes:battle_settled` and the PC legs). Without that, rows b, m and n cannot run.
   - FIXED in `c5cca903` (Codex): the SYNTH identity check now accepts the clone in the party OR the boxes. The same commit stops the probe boot pulsing A/Start once the field is live; a PC-facing save used to open the PC.

   - **Boxed persistence retry at `bf58a7c8`** (Codex, `C:/slink/g4/probe/shakedown-hg-ac0d70aa43/boxed-fix/observation.json` plus a per-case `receipt.txt`):
     - **Boot fix PHYSICAL:** HG reached the overworld (`overworld=true`, boot_frame 1024) in all 5 cases: party-write, no-write, box-write, box-no-dirty and cold-reload.
     - **All four native SAVE traces** ran idle → active 2..7 → idle, with `Save_WriteManFinish` hit once; the newer banks decode coherently.
     - **Row i is a measured FAIL of its oracle premise.** A box write persists across SAVE and reload **even without the dirty flag**: original 70, target 71, with dirty 71, without dirty also 71. The party leg behaves as expected (written 19, no-write 20, cold reload 19).
       - Decide next session whether row i should require the dirty flag at all. A native SAVE appears to write the whole PC regardless.
       - No rerun of the unchanged row i, and no threshold relaxation.
     - **Row c, measured discrepancy:** on PC-derived input, the first residency changes land 2 frames after the pinned `HandleLoadOverlay` causes (id0 at f222 vs 220, id38 at f231 vs 229). `census_ok` allows 0..1. Native-stock baseline c PASSes. Decide whether the tolerance should be 2, from this measurement, not by guess.
   - HG only so far. SS and hge are UNRUN under the HG-only lane grant.

   After the route-leg bridge, run a–n on HG and hge at the landing cut.
4. G2 remainder, per `docs/gen4/G2_PRODUCER_PLAN.md`:
   - The client card: `lua/gen4/client.lua` composing lua/core, with key_change / D11 wiring and the gift_area classifier. Build from the OMP design in `docs/gen4/reviews/CLIENT_DESIGN_PROPOSAL_2026-10-01.md` (steps 0–6, each with a falsifier). N2 is SETTLED (OMP cx-de3446b7, coordinator-verified): a client-side completion latch with no `lua/core` change. The armed hook is a one-frame lease that each `battle_write` call renews, and an unrenewed frame disarms it in `pre_pump`. That covers the core paths that hold or retire an entry without asking the driver (`session.lua:182-192`). See the proposal doc's "N2 research" section.
   - The priority order for the rest is in `G2_PRODUCER_PLAN.md` §6a.
   - SYNTH `place` and `species` kinds for statics and gifts.
5. **Standing rule, the receipt-binding class** (flagged by three OMP reviews: cx-97ce7f50, cx-33981fc1, cx-9661fc31):
   - Already DONE: consumers bind at consumption. That covers `committed_cut` in `test_gen4_probe_gates.py` (`a11d87a0`); faint `consume_receipt` with modules and ROM (`52136900`, `b2784f1b`); and route/catch `verify_receipt` by kind, full module set, script and ROM (`abf2b72c`, `1bbc1f88`).
   - Re-run the lanes at the landing HEAD.
   - **Refinement (OMP cx-50ff7abe):** bind the *evidence surface*, not the repository position. Hash the probe's full dependency set, mirroring `committed_modules()` in `tests/live/test_gen4_perf.py`: `lua/json_codec.lua`, `lua/hook_registry.lua`, `lua/gen4/*`, `lua/nds/*` and the packs it reads. Refuse when any of those changed. `source_head` becomes informational, so a docs-only commit no longer stales receipts while a dependency edit does. Apply this to every consumer: `committed_cut` in `test_gen4_probe_gates.py`, `consume_receipt` in `test_gen4_battle_faint.py`, and `verify_receipt` in `tools/gen4_routes.py`.
   - Catch judge branch tests are done (`abf2b72c`).
   - Receipts on disk from before `1bbc1f88` / `b2784f1b` now read STALE by design: they lack the module sets and the kind binding (some, such as `catch_203302`, already carry title and rom_sha1). That covers `C:/slink/g4/route_pc*`, `catch*`, `hatch*` and `faint*`. Treat them as superseded behaviour evidence until the landing re-run.
   - Tidy-up: hoist `from tools import gen4_pins` to module scope in `tools/gen4_routes.py` (two module identities coexist; OMP cx-421a1f56 N1).
6. **Small pack fixes:** DONE in `49ca5e35`: Pt has its own rtc caveat, the ARM9 byte provenance is labelled and the battle evidence cites its owning structs. Follow-up (OMP cx-b6e028df P5): also pin `VSyncThrottle`/`SuperHawkThrottle` false in `PACE_1X`, if receipts are to claim "clock throttled" exactly.
7. Owner items:
   - Ruling 35: the server force-faints a traded-in mon that breaks an enabled clause. Present it at G2.
   - A separate session asked whether Gen 4 will require a ROM companion patch. No Gen 4 patch exists, and requiring one is an owner decision.

### Workers and peers

- **Codex:** the "Gen4 Worker" thread. An off-task status line was seen once, but the OMP review found no off-task content in its work.
- **OMP:** live peers 27808, 39632 and 5212. **Never** use the Gen 3 SLink-RR* peers.
- **Sonnet subagents:** up to 3.
- **Ledger:** the sole guide is `C:/Users/howar/.claude/hooks/slink/RC_MASTER_GUIDE.md` (the gen4-* cards).

### In flight at stop

Session stopped at the owner timebox (2026-10-01, 22:09 EDT). HEAD is at the end of the `c8b7a99f..` range, below.

- **Nothing in flight.** Codex is frozen and has released the lane. All OMP cards are reconciled, with outcomes recorded. The working tree is clean.
  - The last OMP card, cx-600a3abc (the node-8 path: 0x97 → state 2), is recorded in `G2_PRODUCER_PLAN.md` §6b.
- **EmuHawk:** PID 32580 was running at the stop and is NOT ours. Codex's PIDs all exited, and the coordinator launched none. It was left alone.
- **This session's commits (`c8b7a99f..HEAD`):**
  - pack wording `49ca5e35`
  - pace pins `31c7fa9d` and `b943f588`
  - probe boot fix / boxed SYNTH `c5cca903`
  - `first_field_live_frame` `d15438ef`
  - control-red assertion + boot tests `4e7bf0f9`
  - docs `204d55d7`, `220b93f9`, `bf58a7c8`, `d970ea6e`, `35b786de`
- **Live evidence this session:** `C:/slink/g4/probe/shakedown-hg-ac0d70aa43/boxed-fix/observation.json` (at `bf58a7c8`, HG only). See next action 3.
- **Decisions waiting for the owner or the next session:**
  1. **Row i premise.** A box write persisted WITHOUT the dirty flag. Should row i still require the flag?
  2. **Row c tolerance.** The 2-frame residency lag on PC-derived input against `census_ok` 0..1.
  3. **Ruling 35**, at G2.
  4. **The ROM-patch question** from the other session.
- **Design inputs ready for the client card:** `docs/gen4/reviews/CLIENT_DESIGN_PROPOSAL_2026-10-01.md`:
  - N2 is settled as a client lease, with the guard in the callback; framecount −1 still needs a live confirm.
  - The idle predicate is settled, with no new pack data.
  - F2 is closed.
