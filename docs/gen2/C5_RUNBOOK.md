# C-5 PHYSICAL runbook: randomized Gen 2 duo cells

The runner is `tools/c5_runner.py`. The plan it serves is `docs/gen2/RANDOMIZER_GATES.md` §2.2. Everything runs
under `F:/slink-work/lanes/g2r-live` (`SLINK_C5_ROOT`), a short non-Drive path that stays inside BizHawk's MAX_PATH
budget.

## One-time inputs

| Input | Where | Override |
|---|---|---|
| UPR jar, pinned in `data/upr_jars.json` | `E:/Google Drive/SLink/.cache/slink-upr/PokeRandoZX.jar` | `SLINK_UPR_JAR` |
| pinned pret builds (lock-checked) | `.../worktrees/mandatory-rom-patch-3fcfda/.cache/gen2-build` | `SLINK_C5_GEN2_BUILD` |
| `gen2-fixtures` (copied into the lane) | the sibling of `gen2-build` | same |
| `pret`, `build-tools`, `downloads` (junctioned into the lane) | `E:/Google Drive/SLink/.cache` | `SLINK_C5_MAIN_CACHE` |

## Commands

```
python tools/c5_runner.py provision      # cc, gs, cg randomized pairs via server.cartridges.provision (the Manager path)
python tools/c5_runner.py prove          # per ROM: file sha1 == contract, Lua admits rand_overlay, beacon control refused,
                                         #          server admits the contract sha1 and refuses the un-randomized overlay
python tools/c5_runner.py list           # the cells: READY, or BLOCKED with the exact gap
python tools/c5_runner.py run            # every READY cell not yet PASS at this code digest; exit 2 while BLOCKED cells remain
python tools/c5_runner.py run --only c5/cc/link c5/gs/link
python tools/c5_runner.py run --ready-only   # exit 0 once every READY cell passes
python tools/c5_runner.py status
python tools/c5_runner.py clean          # drop the lane and the server data dirs the cells kept
```

Until the C-5 harness files (`CARRY` in the runner: the two lua/tests driver files and `tools/gen2_duo_oracles.py`)
are committed, pass `--carry`. It copies this checkout's working copy of each file into the lane. Once HEAD carries
them, drop the flag.

## What a cell does

1. `run` makes one detached lane, `r1`, at `--sha` (default HEAD). It uses the `gen2_final_sweep` recipe: copy
   `gen2-build` and `gen2-fixtures`, junction the rest. Before each cell the lane must have no tracked change other than
   the carried files.
2. The cell runs the lane's own `tools/e2e_duo.py --gen2-artifact overlay` scenario through `c5_runner.py _shim <pair>`.
   The shim changes three things and nothing else:
   - each instance's executed cartridge becomes the provisioned randomized ROM, staged at `patch/build/c5/g2r_<a|b>.gbc`.
     The SaveRAM name comes from that filename. The env gets `SLINK_GEN2_EXEC_SHA1=<randomized sha1>` and
     `SLINK_GEN2_RANDOMIZED=1`.
   - the Manager's `rom_contract.json` and `roms/<a|b>.gbc` are copied into the server's data dir. The server binds each
     hello to the contract sha1 and decodes the ROM-derived tables from those files.
   - e2e_duo's CLIENT-line check expects `rand_overlay`. The `gen2_reconnect` relaunch re-plans A on its randomized
     cart.
   - it sets `gen2_duo_oracles.RANDOMIZED = randomized_from_run(roms/<pair>)`, the oracles' C-5 input. It holds each
     side's contract sha1 and ROM. With it set:
     - `_client_artifact` accepts a `rand_overlay` side only at its own contract sha1, on the overlay binding, with
       production/PHYSICAL_RECEIPTED proof, and judges it as the overlay layout;
     - the gift oracle reads Bill's species from the side's ROM (`server.adapters.gen2_gsc.scan_randomized`);
     - the trade oracle reads the NPCTrades row that still wants Bellsprout from OT 48926.
     With it unset (`None`, the default), every oracle is the old one.
3. Exactly one duo (two EmuHawk) runs at a time. A cell gets one retry, and only for a `gen2_final_sweep.RNG_STALL`
   class. A timeout kills only this runner's own process tree (`taskkill /T /PID`).
4. A cell passes only when e2e_duo exits 0 and every check in `c5_receipt_errors` holds:
   - both sides' CLIENT lines say `artifact_kind: rand_overlay` at their contract sha1 (for `gen2_reconnect`, every A
     launch: initial, same_save and wrong_save);
   - the `DUO_GEN2` headers name the randomized sha1;
   - `RESULT: PASS` and `PYDEC: PASS`;
   - there is one clean `CODE_DIGEST` stamp at the run's digest.
5. Output goes to `out/<digest12>/`: `receipts/c5/duo_<scenario>_<pair>_*` and one
   `c5__<pair>__<scenario>.manifest.json` per PASS cell (schema `gen2-c5-duo-cell-v1`, marker
   `gen2.requirement.C-5`, `evidence_level: PHYSICAL`). The manifest holds the contract, the provisioning record
   (seeds, jar sha256, spec), the receipt sha256s and the SYNTH/HARNESS/NATIVE disclosures. `summary.json` makes runs
   resumable: a cell that PASSed at the same code digest with the same contract sha1s is skipped.

Re-provisioning changes the contract sha1s, so every cell runs again. A jar re-pin (patch 0019) makes `run` refuse
until you re-provision. A change in the Gen 2 CODE_DIGEST scope (`lua/*.lua`, `lua/gen2/**`, `lua/core/**`,
`server/**/*.py`, the Gen 2 packs) gives a new `out/<digest12>/` and a full re-run. lua/tests and tools are outside
the digest.

## Provisioning settings

These are the `gen2_gsc` Manager defaults: wild, starters and trainers random, fastest text. On top of them:
- `statics=random` and `trades=given_and_requested`, so the ROM-derived static, gift, roamer and trade paths differ
  from vanilla;
- `wild_min_catch_rate=5`. The first smoke run's A side threw all 10 Balls at a low-catch-rate randomized Route 29 mon
  (`no Poke Ball left in the pocket`). The cartridge setting is disclosed in each manifest's `provision.spec`.

There are no tutors, because UPR drops them on G/S and the C+G pair would refuse on "same applied settings".

## The lua/tests driver change (applied in the g2-rand worktree, uncommitted; outside the CODE_DIGEST)

The change touches 2 files, +20/-5 lines (also saved as `F:/slink-work/lanes/g2r-live/c5_driver.patch`). It is default-off:
with `SLINK_GEN2_RANDOMIZED` unset, every path is the old one.
- `lua/tests/test_gen2_scripted_gate.lua`:
  - `G.identity` accepts `SLINK_GEN2_RANDOMIZED=1`. EXEC must then be its own sha1, distinct from the overlay and the
    base. It returns `overlay_sha1` and `randomized`.
  - `G.inputs` keeps both.
  - `G.artifact` asks `Artifact.view` for the overlay row's view (`overlay_sha1`), not the executed sha1.
  - the phone-call facts identity compares against the overlay row.
- `lua/tests/duo/duo_gen2_main.lua:261`: the production artifact check also accepts `rand_overlay` when the env is
  randomized.

Why it is needed: without it, `G.identity` refuses EXEC != OVERLAY ("SLINK_GEN2_EXEC_SHA1 differs ..."),
`Artifact.view` refuses a sha1 that is not the binding's (`lua/gen2/artifact.lua:56`), and `duo_gen2_main.lua:261`
fails on `rand_overlay ~= overlay`. Production `lua/gen2/**` is untouched.

## Cells

READY (10/11 PASS at e5b0c5c6):
- `cc/link` (G-a), plus `gs/link` and `cg/link` (G-b);
- `cc/` and `gs/gen2_reconnect` (G-d);
- `cc/` and `gs/gen2_gift` (G-e/G-f): Bill's givepoke, read from each side's ROM;
- `ct/gen2_npc_trade` (G-h): pair `ct` uses `trades=given`, so Kyle still asks for the fixture's Bellsprout;
- `cc/gen2_c5_wrong_rom` (G-c) and `cc/gen2_c5_no_contract` (G-i): refused at hello by the SERVER.

G-c and G-i are explicit-only e2e_duo scenarios (`GEN2_C5_REFUSED`). Their Lua half is
`lua/tests/duo/gen2_c5_refused.lua`; their oracle is `gen2_duo_oracles.c5_refused_oracle`. The orchestration waits
for every admitted side's hello and for every refused side's `admission == "rejected"` before it writes the go-file.
- G-c: B boots cc's B cart, but the served contract names ct's B, another real Manager cart.
- G-i: the run has no `rom_contract.json`.
- The oracle matches the server's text exactly. Observed:
  - G-c B: `this is not the ROM built for player b (sha1 c462e7602032, expected 32a08d4c5bb0)`;
  - G-i A and B: `randomized cartridges for this game must be made by the Manager (this run has no randomized-ROM
    contract)`.
- A refused side receives no command (`SERVER_VERDICT rx=0`), holds no identity and forms no link. The journal holds
  `REJECTED — <reason>`. G-i leaves no links.json at all.

BLOCKED: G-g, the roamer. The overlay client never registers `roamer_party_finalized` or `roamer_box_finalized`:
they are not among the 27 sites proven by `tests/fixtures/gen2/receipts/overlay/<title>.engine_sites.json`. So
`lua/gen2/signals.lua:953-965` cannot classify a roamer catch on any overlay cart, randomized or not. The fix comes
first, as a U1G `roamer` leg that proves those sites. Only after that can an O-33 roamer setup link:
- `wRoamMon<i>` on Route 29, written from the executed ROM's `InitRoamMons` immediates;
- a Repel to block ordinary wilds;
- Master Balls.

## What the verifier does not consume yet

`tools/verify_gen2_release.py` has no C-5 receipt kind. `duo_matrix_errors` and `_receipt_errors` require
`rom_sha1 == the published overlay sha1` for overlay cells (`:1113`), so randomized receipts cannot live in
`tests/gen2_release_requirements.json`. Install the `out/<digest12>/receipts/c5/` files under
`tests/fixtures/gen2/receipts/c5/` only once a reader exists. That reader would be a `--c5` lane, or the
release-evidence lane reading `*.manifest.json` (RANDOMIZER_GATES.md §3.4). Pin their sha256s at the same time.
