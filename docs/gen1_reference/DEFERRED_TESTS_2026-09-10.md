# Address pins and deferred tests — 2026-09-10

Read-only validation pass in the Gen 1 sweep worktree (HEAD `79d5172`, 2026-08-30, plus the
uncommitted working set). No emulator was launched and no test was executed; the unit and
integration trees were collected (`--collect-only`), not run. Raw tool output:
`.cache/junit/pins_2026-09-10.log`.

## Job A — address/pin verification (item 7)

### A.1 Static verifier runs

| Tool | Result | Per variant | Exit |
|---|---|---|---|
| `verify_profile_addresses.py --gen1-only` | 600 ok / 0 fail / 0 warn / 0 skip | red 126 OK, blue 126 OK, yellow 138 OK, red_ap 105 OK, blue_ap 105 OK | 0 |
| `verify_profile_addresses.py` (full) | 702 ok / 0 fail / 0 warn / 72 skip | the 72 SKIP rows are the older Gen 2 hex-literal audit, outside the Gen 1 gate | 0 |
| `verify_gen1_constants.py` | 87 OK / 0 FAIL | pokered 29, pokeyellow 29, alchav_pokered 29 (alchav covers red_ap/blue_ap) | 0 |
| `verify_gen1_rom_layout.py` | 37 ok / 0 fail / 0 ROM missing | red 14 ok, blue 14 ok, yellow 8 ok (no companion patch for Yellow), generated_payload 1 ok; AP builds are outside this tool's ROM map | 0 |
| `verify_canonical_sources.py` (static, added) | PASS, 103 checks | source/artifact hash chain | 0 |
| `verify_gen1_release.py --list` | listing only (registered vs MISSING PROOF per stage); not a verdict | — | 0 |
| `verify_gen1_release.py --verify-inputs` | FAIL: `missing prerequisite: emulator (SLINK_EMUHAWK)` and `missing prerequisite: upr-zx-4.6.1 (SLINK_UPR_JAR)` | env-var-only failure: `E:/Howard/Bizhawk/EmuHawk.exe` has the pinned sha256 `f8cdb935…` and `E:/Google Drive/SLink/.cache/upr/PokeRandoZX.jar` has the pinned sha256 `380dc1e6…`; not re-run with the variables set (EmuHawk adjacent-file hashes unverified here) | 1 |

Not run on purpose: `--quick` (executes tests), `--write-inventory` (writes), `verify_portable_ci.py` (runs the suite).

### A.2 Battle-force pinned sites vs pret symbols

Sources used:

* S1 — rgblink symbol files of the pinned builds: `.cache/pret/pokered/pokered.sym`, `.cache/pret/pokered/pokeblue.sym`, `.cache/pret/pokeyellow/pokeyellow.sym`.
* S2 — `data/pret_rom_syms.json` (`bank<<16|addr`) and `data/pret_syms.json` (WRAM/HRAM).
* S3 — direct byte reads of the dumps (worktree-root Red/Blue/Yellow and `patch/build/gen1_*.gb*`), flat = `bank*0x4000 + (pc-0x4000)`, compared with the `expected_hex` in `server/battle_force_authority.py` (`_RB`, `ANCHORS["yellow"]`).
* S4 — `.cache/pret/{pokered,pokeyellow}/engine/battle/core.asm` line numbers quoted in the module docstring.
* AP — `.cache/pret/alchav_pokered/pokered.map` / `pokeblue.map` (rgblink map; the fork has no `.sym`), `data/pret_syms.json["alchav_pokered"]`, and bytes of `patch/build/gen1_red_ap.gb` / `gen1_blue_ap.gb`.

`lua/battle_force_authority.lua` pins nothing itself; it takes sites and addresses from the server-issued authority.

| Site | Variant | Pinned | pret symbol | Bytes (S3) | Verdict |
|---|---|---|---|---|---|
| loop_head | Red/Blue | 0F:4233, `cd434d2115d02ab6ca004721e6cf` | `MainInBattleLoop` 0f:4233 (S1 pokered.sym:6594, pokeblue.sym:6594; S2 `0xF4233`) | match on Red root, Blue root, `gen1_red.gb`, `gen1_blue.gb` | CONFIRMED |
| loop_head | Yellow | 0F:4249, `cd084e2114d02ab6ca1d4721e5cf` | `MainInBattleLoop` 0f:4249 (pokeyellow.sym:6463; S2 `0xF4249`) | match (root and `gen1_yellow.gbc`) | CONFIRMED |
| player_action | Red/Blue | 0F:565E, `afe0f3fadccc3cca0a58afea5fd0` | `ExecutePlayerMove` 0f:565e (sym:6830; S2 `0xF565E`) | match | CONFIRMED |
| player_action | Yellow | 0F:57D0, `afe0f3fadccc3cca7c59afea5ed0` | `ExecutePlayerMove` 0f:57d0 (sym:6720; S2 `0xF57D0`) | match | CONFIRMED |
| return_sites | Red/Blue | 0x4364, 0x4380 | not symbols; both lie inside `MainInBattleLoop` (0x4233–0x43BC; next symbol `HandlePoisonBurnLeechSeed` 0f:43bd) | bytes at 0x4361 and 0x437D are `cd 5e 56` = `call ExecutePlayerMove` (core.asm 429, 442), so both are the return addresses of those calls | CONFIRMED |
| return_sites | Yellow | 0x437A, 0x4396 | inside `MainInBattleLoop` 0x4249–0x43D2 | `cd d0 57` precedes both (core.asm 438, 451) | CONFIRMED |
| poison_tail (in ANCHORS, not in SITES) | R/B 0F:4421 / Y 0F:4437 | inside `HandlePoisonBurnLeechSeed` (0f:43bd / 0f:43d3), before `_DecreaseOwnHP` (0f:443d / 0f:4453) | match: `ld a,[hli]; or [hl]; ret nz; …` | CONFIRMED |
| move_done (in ANCHORS, not in SITES) | R/B 0F:580A / Y 0F:597C | `ExecutePlayerMoveDone` 0f:580a / 0f:597c | match: `xor a; ld [wActionResultOrTookBattleTurn],a; ld b,1; ret` | CONFIRMED |

| Address | Pinned R/B | Pinned Y | S1/S2 R/B | S1/S2 Y | Verdict |
|---|---|---|---|---|---|
| wBattleMonHP | D015 | D014 | d015 | d014 | CONFIRMED |
| wPlayerSelectedMove | CCDC | CCDC | ccdc | ccdc | CONFIRMED |
| wPlayerBattleStatus3 | D064 | D063 | d064 | d063 | CONFIRMED |
| hLoadedROMBank | FFB8 | FFB8 | ffb8 | ffb8 | CONFIRMED by S1; the `data/pret_syms.json` entry belongs to this worktree's uncommitted +704-line HRAM addition (HEAD's copy has no `h*` symbols) |
| wStatusFlags4 (`STATUS_FLAGS_4_ADDR`, `lua/games/gen1_rby.lua:58` / `:268`; not in battle_force_authority) | D72E | D72D | d72e | d72d | CONFIRMED |
| wNumberOfNoRandomBattleStepsLeft (`lua/tests/gen1_playthrough.lua:76` / `:86` only; no profile or server field) | D13C | D13B | d13c | d13b | CONFIRMED |
| remaining ANCHORS addresses: wBattleMonSpecies, wBattleMonDVs, wPartyMon1, wPartyMon1HP, wPartyMon1Status, wPartyMon1OTID, wPartyMon1DVs, wPlayerMonNumber, wIsInBattle, wBattleType, wLinkState, wEnemyMonHP, wActionResultOrTookBattleTurn | as pinned | as pinned | all 13 match | all 13 match | CONFIRMED |

Docstring line citations (S4): `MainInBattleLoop` Red 280 / Yellow 289; `ExecutePlayerMove` 3073 / 3244; `jp z, HandlePlayerMonFainted` Red 437, 450 / Yellow 446, 459 — all correct.

No MISMATCH and no NO SYMBOL AVAILABLE row for Red, Blue or Yellow.

### A.3 Archipelago Red/Blue

* `server/battle_force_authority.py` `ANCHORS` has `red`, `blue` and `yellow` only; `verify_proof` refuses anything else with `JournalError("unsupported title")`, so AP is fail-closed rather than supported. The `red_ap`/`blue_ap` profiles in `lua/games/gen1_rby.lua` carry no battle-force pins either.
* The fork **does relocate the code sites** (alchav map, ROMX bank #15): `MainInBattleLoop` $4231 (−2), `ExecutePlayerMove` $569D (+63), `ExecutePlayerMoveDone` $5847 (+61), `HandlePlayerMonFainted` $46EE (−18), `HandlePoisonBurnLeechSeed` $43B5 (−8), `_DecreaseOwnHP` $4435 (−8). The built AP ROMs (`gen1_red_ap.gb` sha1 `4789c6a7…`, `gen1_blue_ap.gb` sha1 `4d3f8c07…`) carry the same instruction pattern at the relocated PCs (0F:4231 = `cd 3c 4d 21 15 d0 2a b6 ca ee 46 21 e6 cf`; 0F:569D = `af e0 f3 fa dc cc 3c ca 47 58 af ea 5f d0`), and all four vanilla `expected_hex` pins MISMATCH at the vanilla PCs in those ROMs — expected, and harmless while no AP anchor exists.
* WRAM in the fork: wBattleMonHP D015, wPlayerSelectedMove CCDC, wPlayerBattleStatus3 D064, hLoadedROMBank FFB8 and wNumberOfNoRandomBattleStepsLeft D13C are unchanged; wStatusFlags4 is still named `wd72e` there and sits at **D71C** (−18). The AP Lua profile leaves `STATUS_FLAGS_4_ADDR` nil (`tools/verify_profile_addresses.py:538` lists it as unsupported for AP), so the no-battles switch is unavailable on AP.

## Job B — deferred-test inventory (item 9)

### B.1 Where the numbers come from

* `tests/gen1_release_inventory.json` → `checks`: unit 5,756 / integration 148 / live-gates 267 / duo-pairs 45. Written by `tools/verify_gen1_release.py --write-inventory` (collection only). These are exactly the RC_STATUS figures.
* `tests/portable_ci_inventory.json` (schema 1, 94 groups, 10 named resources, 5,904 nodes) holds the same unit+integration node set as the release inventory (verified identical). It is consumed by `tools/portable_ci.py` (pytest plugin) through `tools/verify_portable_ci.py` and described in `docs/portable-ci.md`.
* A node is a **named deferral** when its group has a non-empty `requires` list or a `platforms` list that excludes the host. 21 groups / 443 nodes are gated; on win32 the 2 `windows-junction-security` nodes run and the 2 `linux-symlink-security` nodes are deferred → **5,463 selected / 441 deferred**, matching the doc exactly (Linux mirrors the split).
* Stored evidence: `.cache/portable-ci/worktree-report.json` (2026-09-05, older tree: 3,666 collected / 3,361 selected / 305 deferred, `portable_passed: true`); `docs/gen1_reference/TEMPORAL_INVENTORY.md` quotes 4,465/435 from an intermediate cut.
* **Drift**: `pytest tests/unit tests/integration --collect-only -q` now collects **7,328** nodes (7,177 unit + 151 integration): 1,425 are in neither inventory (largest: `test_gen1_npc_exchange_receipt.py` 169, `test_gen1_static_receipt.py` 140, `test_battle_force_authority.py` 140, `test_gen1_storage.py` 134, `test_gen1_identity_guard.py` 53, `test_gen1_wild_encounter.py` 50) and 1 inventoried node (`test_gen1_grant_receipt.py`) no longer exists. Those files, both inventory JSONs and the RC docs are untracked in this worktree (604 untracked entries), so the "stable cutoff" has no git ref, and `verify_portable_ci.py` would fail on unclassified nodes until the inventory is reviewed.

### B.2 What marks a test deferred

Two independent layers, plus the live/e2e markers:

1. **Inventory layer** (portable lane only): `requires` / `platforms` → node *deselected* before setup; never a skip.
2. **In-test layer** (plain pytest and the release gate): 104 marker lines in `tests/unit`, 0 in `tests/integration` (`grep -rn "skipif\|pytest.skip\|importorskip"`): 22 × `importorskip("lupa")`, 3 × `importorskip("aiohttp")`, 1 × `importorskip("pytest_asyncio")`, about 24 × `pytest.skip()` on a missing file (staged/root ROM, pret clone, JAR, java, `slink_red.gb`, apworld, `pret_rom_syms.json`, SaveRAM fixture), 1 × `skipif(os.name != "nt")`, 1 × symlink-privilege try/except skip, 3 × RR-types skips, 8 × parametrisation-shape skips (client lacks `memorialize`/`dispatch_commands`; ROM type renders no sprite), and 4 string literals inside test bodies (`test_gen1_release_gate.py:55,60`, `test_portable_ci.py:109,120`) that are not skips. Only 8 markers use `reason=`, which is why the `reason=` grep under-counts.
3. `tests/live` (267) and `tests/e2e` (45) are gated by the `live` (`SLINK_LIVE=1`) and `e2e` (`SLINK_E2E=1`) markers in `pytest.ini`, outside the unit/integration inventory.

### B.3 Deferral reasons, counts and prerequisites on this machine (win32)

| # | Inventory group(s) / reason | Nodes | Prerequisite | Present now? | What switches it on |
|---|---|---|---|---|---|
| 1 | real-upr-component, gen1-pinned-upr-pipeline, gen1-reproduced-prepared-admission — real UPR JAR on clean cartridges | 130 | `gen1-clean-staged-roms` + `upr-zx-java` | staged ROMs YES; Java 1.8.0_481 on PATH YES; JAR **NO** in the worktree (`.cache/upr` absent, `SLINK_UPR_JAR` unset); the pinned JAR (sha256 `380dc1e6…`) exists at `E:/Google Drive/SLink/.cache/upr/PokeRandoZX.jar` | `SLINK_UPR_JAR="E:/Google Drive/SLink/.cache/upr/PokeRandoZX.jar"` or copy it to `.cache/upr/` |
| 2 | clean-staged-roms, sept8-manager-prepared-process-portable — staged cartridge bytes | 127 | `gen1-clean-staged-roms` (`patch/build/gen1_red.gb`, `gen1_blue.gb`, `gen1_yellow.gbc`) | YES (SHA-1s verified by rom_layout) | already on for a plain run |
| 3 | clean-root-roms — root cartridge bytes | 102 | `gen1-clean-root-roms` (three dumps at the worktree root) | YES (sha1 `ea9bca…`, `d7037c…`, `cc7d03…`) | on |
| 4 | source-and-rom-profile-checks — effective-profile validator with mutation controls | 21 | `gen1-pinned-sources` + root ROMs | YES | on |
| 5 | gen1-source-oracles — pinned source text as oracle | 19 | `.cache/pret/pokered`, `pokeyellow`, `alchav_pokered` | YES | on |
| 6 | canonical-build-regeneration + sept8-{bootstrap,capture,grant}-canonical | 16 | `gen1-canonical-build-provenance` (`.cache/pret` builds, `.cache/pret-build`, `data/pret_build_provenance.json`) | YES (`verify_canonical_sources.py` PASS, 103 checks) | on |
| 7 | gen1-browser-patch-artifacts — canonical UPS bytes | 7 | staged ROMs + `patch/gen1/build/companion_{red,blue,yellow}/*.ups` | YES | on |
| 8 | patch.canonical-combined-build | 4 | root ROMs + sources + provenance | YES | on |
| 9 | gen1-real-browser-patcher — real browser patch flow | 4 | staged + companion + UPR + `browser-node-playwright` | node v23.11.0 YES; Chrome YES (`C:/Program Files/Google/Chrome/Application/chrome.exe`); Playwright **NO** (no `node_modules/playwright`; `NODE_PATH`, `SLINK_NODE`, `SLINK_CHROMIUM` unset); JAR as row 1 | `npm install playwright` (or `NODE_PATH`) plus `SLINK_UPR_JAR` |
| 10 | rom-versus-source-scanner | 3 | staged + sources | YES | on |
| 11 | installed-apworld-oracle (win32 only) | 3 | `C:/ProgramData/Archipelago/custom_worlds/pokemon_crystal.apworld` | YES (453 KB, 2025-06-21) | on |
| 12 | gen2-source-oracles | 2 | `.cache/pret/pokecrystal`, `pokegold` | YES | on |
| 13 | linux-symlink-security | 2 | Linux, or Windows symlink privilege | **NO** — win32 and `os.symlink` fails (WinError 1314) | run on Linux, or grant `SeCreateSymbolicLinkPrivilege` / Developer Mode |
| 14 | windows-junction-security | 2 | win32 | YES (selected here; deferred on Linux) | — |
| 15 | built-companion-comparison | 1 | staged + `patch/gen1/build/slink_red.gb` | YES (1 MiB, 2026-09-06) | on |

Of the 441 deferred here: 305 have every prerequisite present right now (rows 2–8, 10–12, 15); 134 need only `SLINK_UPR_JAR` (rows 1 and 9; row 9 also needs Playwright); 2 need Linux or the symlink privilege.

In-test layer on this machine (plain `pytest tests/unit`): lupa 2.8 (Lua 5.5), aiohttp 3.14.1, pytest_asyncio 1.3.0, staged and root ROMs, all five pret clones, java, `slink_red.gb`, the Crystal apworld, `data/pret_rom_syms.json`, the six `tests/fixtures/gen1/*.SaveRAM` and `data/games/gen3_frlge/rr_types.json` are all present, so those skips stay silent. Two would fire: the UPR JAR (`test_gen1_rom_scan.py:432`, `test_upr_pipeline.py:33`) and the symlink privilege (`test_http_server_security.py:119`, the documented "2 existing Windows symlink skips"). Parametrisation-shape skips fire by design.

Live/e2e prerequisites (not inventory deferrals): EmuHawk 2.11.1 at `E:/Howard/Bizhawk/EmuHawk.exe` with `config.ini`, sha256 equal to the manifest pin; `SLINK_LIVE`, `SLINK_E2E`, `SLINK_EMUHAWK` and `SLINK_BIZHAWK_CONFIG` unset in this shell (`tools/run_gate.py` defaults to that path; `verify_gen1_release.py` needs the variable). `pokemon_rb.apworld` sha256 matches its pin; `lua/x64/socket-windows-5-4.dll` is present. Network: tests bind ephemeral loopback ports (`tests/conftest.py::_find_free_port`); no fixed-port prerequisite.

## Concerns

* `tools/verify_gen1_release.py:171` — `--verify-inputs` reports the emulator and JAR as missing on env-var absence alone, while both files exist with the pinned hashes and `tools/run_gate.py:30` hard-codes the same EmuHawk path; the message could name the expected path.
* `tests/portable_ci_inventory.json`, `tests/gen1_release_inventory.json` — stale against the tree by +1,425 / −1 nodes, and untracked; the RC_STATUS counts describe the inventory cutoff, not what collects today.
* `data/pret_syms.json` — +704 uncommitted lines (HRAM `h*` symbols for all five repos, including `hLoadedROMBank`); HEAD's copy would not resolve HRAM pins.
* `server/battle_force_authority.py:61-62,76-77` — `poison_tail` and `move_done` are pinned in `ANCHORS` but never issued (`SITES` is loop_head/player_action only); dead pins or a future site, worth a comment either way.
* `tests/unit/test_http_server_security.py:119` — on a Windows host without symlink privilege this node skips, and the strict release gate counts skips as failures, so the unit stage cannot be green here without the privilege (the portable lane sidesteps it by platform).
* `tools/verify_profile_addresses.py` (no flag) — 72 SKIP rows still exit 0; harmless for the Gen 1 gate (`--gen1-only`), but a skip-as-pass path survives in the shared tool.
* `docs/gen1_reference/RC_STATUS_AND_ESTIMATE.md:140` — run-together figures ("Broad5,073/2existing skips;85 final…4,638 portable passes/437 declared deferrals").
* Whole worktree — the server/lua battle-force modules, both inventories, the RC docs and `tools/portable_ci.py` are all untracked on top of an Aug-30 HEAD; nothing audited here is reviewable by commit yet.
