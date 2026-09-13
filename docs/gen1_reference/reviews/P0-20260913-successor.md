# P0-20260913-successor input and static receipt

Status: original invocation HOLD; separately authorized configured invocation PASS at 13:30 UTC; coordinator acceptance pending. Evidence level: SOURCE/INPUT only. This receipt does not establish collection, suite execution, original-engine gameplay, final-host readiness, or release qualification.

## Assignment and source

- Runner: Codex `/root/p0_preflight`, host `HOUNDOOM`, Windows NT `10.0.26200.0`; coordinator Codex task `01a09ae0-ad6f-7b01-8753-5e6b71eb1cfa` (`/root`).
- Checkout: `E:/Google Drive/SLink/.claude/worktrees/gen1-rby-code-sweep-8d06e2`, branch `gen1/rc`. Initial clean HEAD `b06d796ab87e6b7ae7b1022d403b5c5dd9c84e7b`; activation `18446b11b6f966764f28f145a5b8826d57428691`. Production reference `19edbb2`; handoff `3b8bf48`. The dispatch's historical `df38453` was explicitly superseded by the coordinator.
- Read AGENTS.md, universal README, RC_MASTER_GUIDE.md, WORKTREE_REGISTER.md, P0 brief, P0 catalog row, evaluator, manifest and input pins before bounded work. Acknowledgment preceded coordinator ACTIVE confirmation. Applied `writing-for-agents`; this was the already scoped P0 inspection under the recorded ask-matt routing adaptation, with no new planning or implementation grant.
- Coordinator-only documentation advanced through `bcfbef978478715711801591b9ee58b5d655e36e` and `5b176fc06e83654405ed42e8b072b4584549a3d7`. Observed intervening diffs touch guide/register only. No source difference or unrelated dirt was observed before this report was created.
- Sole runner output is this file. No source, manifest, inventory, dependency, privilege, emulator, guide/register edits or commits. Filesystem reads and hash calculations were performed in PowerShell. Python execution was limited to version identification and the expressly granted evaluator invocation(s) below. No suite, collection, installation or ROM derivation was run.

## Original process environment and exact invocation

Resolved existing interpreter: `C:/Users/howar/AppData/Local/Programs/Python/Python312/python.exe`; `--version` returned `Python 3.12.10`.

UTC start `2026-09-13T13:11:04.5354665Z`, end `2026-09-13T13:11:04.7280789Z` (approximately 0.193 seconds including process setup/capture). CWD is the assigned checkout. Exact command:

```text
C:/Users/howar/AppData/Local/Programs/Python/Python312/python.exe tools/verify_gen1_release.py --verify-inputs
```

Exit code **1**. Exact stdout, including final CRLF, represented losslessly as a JSON string:

```json
"FAIL: missing prerequisite: emulator (SLINK_EMUHAWK)\r\nFAIL: missing prerequisite: upr-zx-4.6.1 (SLINK_UPR_JAR)\r\n"
```

Exact stderr: `""` (zero characters). All four prerequisite overrides (`SLINK_EMUHAWK`, `SLINK_UPR_JAR`, `SLINK_JAVA`, `SLINK_AP_APWORLD`) were unset. The two missing configuration values do not establish that the installed artifacts are absent. The runner did not infer fallback locations or change the environment during this invocation.

`tools/verify_gen1_release.py:388` reads/validates the manifest and input pins, invokes `prerequisite_problems`, and returns at the `--verify-inputs` branch before inventory reads, report-directory creation or any test/check dispatch. Its eight fixture/artifact pins all passed: six R/B/Y battle/town SaveRAM files and `patch/build/gen1_red_ap.gb`, `gen1_blue_ap.gb`. `derived_inputs` records derivation provenance but is not independently reconstructed by this branch. Proof implementation/supporting-source hashes, canonical source validation and collection are separate later checks.

## Eight prerequisite outcomes

Absolute paths below use `R = E:/Google Drive/SLink/.claude/worktrees/gen1-rby-code-sweep-8d06e2`. The evaluator resolves worktree-local entries with containment checks; configured and external entries may live outside the worktree. Executables additionally use `shutil.which`. Java was resolved from PATH to the path below; the PowerShell application lookup agreed. There is no Java hash/version/runtime compatibility check in this policy.

| ID | Original resolved path | Required policy / actual digest | Original outcome |
| --- | --- | --- | --- |
| legal-rom.red | `R/Pokemon - Red Version (USA, Europe) (SGB Enhanced).gb` | SHA1 `ea9bcae617fdf159b045185467ae58b2e4a48b9a`, actual equals pin | PASS |
| legal-rom.blue | `R/Pokemon - Blue Version (USA, Europe) (SGB Enhanced).gb` | SHA1 `d7037c83e1ae5b39bde3c30787637ba1d4c48ce2`, actual equals pin | PASS |
| legal-rom.yellow | `R/Pokemon - Yellow Version (USA, Europe).gbc` | SHA1 `cc7d03262ebfaf2f06772c1a480c7d9d5f4a38e1`, actual equals pin | PASS |
| emulator | Unresolved: unset `SLINK_EMUHAWK`, no manifest fallback | SHA256 `f8cdb93551a544f680bf3876d9d8d72643859e7a44a23b04e1a25b92e48f80cd`, plus eight adjacent SHA256 pins | HOLD: no evaluated executable or adjacent paths |
| upr-zx-4.6.1 | Unresolved: unset `SLINK_UPR_JAR`, no manifest fallback | SHA256 `380dc1e6c704a9a4ed8433e8b7892a149390f8912b9107a2a0e7263cfd71c7d8` | HOLD: no evaluated path |
| java | `C:/Program Files (x86)/Common Files/Oracle/Java/java8path/java.exe` | Executable lookup and file presence only; no pin | PASS under presence policy |
| archipelago-world | `C:/ProgramData/Archipelago/lib/worlds/pokemon_rb.apworld` | SHA256 `14617b81e41ca26d49d2ea889f904a4443ceae1020c5de748a202457580b8cf6`, actual equals pin | PASS |
| luasocket-windows-5.4-x64 | `R/lua/x64/socket-windows-5-4.dll` | SHA256 `47ebef934e70acfe5bdb438ccbb2c8e3f8ac57d8acc833e5b1bd445ba5e2f378`, actual equals pin | PASS |

Seven entries require pins; Java does not. The evaluator continues to adjacent hashes even after a main executable hash mismatch, but skips the entire entry when its configured value or file is absent (`prerequisite_problems`, lines 164–211). An emulator pin pass would bind bytes, not prove launch or core behavior.

## Manifest and execution boundary

Current manifest: **388 total, 224 registered, 164 empty**; 387 non-human rows with 163 empty, plus one empty human row. There are 15 checks and eight prerequisites. Registration is not passing proof.

| Stage | Total | Registered | Empty |
| --- | ---: | ---: | ---: |
| canonical-validation | 12 | 12 | 0 |
| unit-protocol | 117 | 117 | 0 |
| live-memory | 54 | 53 | 1 |
| single-player | 60 | 0 | 60 |
| live-duos | 12 | 7 | 5 |
| ordered-contracts | 18 | 18 | 0 |
| manager-isolation | 4 | 2 | 2 |
| patch-browser | 42 | 2 | 40 |
| trade-receptionist | 68 | 13 | 55 |
| human-session | 1 | 0 | 1 |

Exact unit/integration argv are `{python} -m pytest tests/unit -q -p no:randomly -ra` and `{python} -m pytest tests/integration -q -p no:randomly -ra`. Both select whole directories, including other generations/shared code. `run_check` adds the release evidence plugin, report/token arguments and isolated `--basetemp`; it inherits the process environment, with empty per-check environment overrides for these two lanes. `pytest.ini` adds `--strict-markers` and strict asyncio mode. `PYTEST_ADDOPTS`, `PYTEST_PLUGINS`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD`, `PYTHONPATH`, `SLINK_PRET_DIR`, `SLINK_PRET_YELLOW_DIR`, `SLINK_NODE` were unset during inspection. Default third-party plugin autoload remains possible. Only `tests/conftest.py` exists in the selected tree; it contains no skip hook, isolates data paths and starts a real TCP server when requested.

## Static skip census and classification

The appendix enumerates every matching skip/importorskip/skipif/xfail site in the complete selected unit/integration directories, including helper files. No unit/integration suite or collection was executed. Actual collection and imported-plugin behavior remain unmeasured. Searches also checked `SkipTest`, unittest skip forms, import exceptions and collection hooks; no additional test-level skip mechanism was found. The following classification covers the enumerated sites; ordinary prose containing “skip” is not a deferral.

**Required imports.** All `pytest.importorskip("lupa")` sites require an importable Lua runtime for the registered lane; aiohttp sites require aiohttp, and `test_routes_smoke.py:14` additionally requires pytest_asyncio. These are dependencies, not an authorized release exemption. Existing Python312 site-packages directories and distribution names show lupa 2.8, aiohttp 3.14.1, pytest_asyncio 1.3.0 and pytest 9.0.3 installed on disk. Importability, binary loading and Lua implementation/version were not executed or proved. Many selected tests import these packages directly, so missing imports can produce collection errors instead of skips. The release validator rejects either. The appendix lists every conditional import site; it does not imply conditional imports are the only dependencies.

**Required ROMs/artifacts and generated data.** `test_gen1_admission`, `test_gen1_rom_content`, `test_gen1_rom_scan`, `test_gen1_injector`, `test_gen1_patch_validation`, `test_upr_pipeline` and `test_patcher_routes` require the separate `patch/build/gen1_red.gb`, `gen1_blue.gb`, `gen1_yellow.gbc` paths, not just the three root prerequisite ROMs. All three exist. Injector also requires `patch/gen1/build/slink_red.gb`, which exists. Patcher's `_bytes` checks both the clean input and `patcher.patch_path(slug)` UPS payload, so its “ROMs” skip message also covers a missing patch. Presence alone is not a hash/content pass. The six SaveRAM requirements in `test_gen1_fixtures` passed input pins. `test_pret_rom_syms` requires `data/pret_rom_syms.json` (present) and the root ROMs (pinned pass). `test_gen1_upr_roots`, `test_gen1_native_continuity_seam`, `test_manager_prepared_gen1`, and integration `test_gen1_canonical_pair` use clean-root/lock-derived files; their R/B/Y root presence is established.

**Required pret/AP sources.** `test_gen1_canonical_moves_trainers_types`, `test_gen1_generated_maps_fishing`, `test_gen1_ghost_battles`, `test_gen1_items`, `test_gen1_panel_tiles`, `test_gen1_rom_scan`, `test_gen1_statics_and_trades`, `test_gen1_upr_roots`, and `test_gen2_ball_items` guard source availability. Direct local `.cache/pret/{pokered,pokeyellow,pokegold,pokecrystal}` directories exist. Upward-search helpers find local R/Y first; encounter generator also accepts `SLINK_PRET_DIR`/`SLINK_PRET_YELLOW_DIR` overrides, both unset. Required map/item constants in R/Y and pokered charmap, item names, battle core/end-of-battle files were individually present. Gen2 AP's hardcoded `C:/ProgramData/Archipelago/custom_worlds/pokemon_crystal.apworld` exists and is distinct from the pinned R/B AP prerequisite. This census did not execute source/hash oracles, read AP contents, or rebuild sources.

**Required UPR and Java availability.** `tests/conftest.py:111` searches `SLINK_UPR_JAR`, root `PokeRandoZX.jar`, root `tools/PokeRandoZX.jar`, then six upward `.cache/upr/PokeRandoZX.jar` candidates. Thus a unit test can find a JAR even while the release prerequisite remains missing because the latter has no fallback. `test_gen1_rom_scan.py:442` specifically checks `shutil.which("java")` and launches literal `java`; it does not honor `SLINK_JAVA`. PATH Java exists in this environment. No Java/JAR process ran under this census. `test_upr_pipeline` has JAR and clean-ROM skip branches; remaining pipeline failures are hard errors, not blanket optional tests.

**Intentional source-shape conditions.** `test_client_acks.py:41,55` skips clients lacking memorialize handler/done text; `test_client_upvalue_scope.py:78,123,128` skips clients without top-level dispatch/parser functions. Static matching against all five current client files found all required constructs; none of these skip predicates is currently true. Their future firing would still fail the release gate. No dependency installation changes these source-shape conditions.

**Conditional sprite/data behavior.** `test_sprite_html_contract.py:39,51` skips empty `sprite_html(25)` output; `test_routes_smoke.py:195` skips empty `sprite_html(1)` for its Gen1/Gen3-RR fixtures. Gen1/Gen2/Gen4/Gen5 methods return HTML for the tested positive IDs; Gen3 also has national-ID/data mapping conditions. Runtime output was not evaluated. `_adapters` additionally catches construction exceptions and omits failed adapters, and Gen5 registration catches ImportError; these are silent coverage omissions rather than pytest skips and must be considered against frozen inventory. `test_gen3_adapter.py:1078,1088,1098` skips for missing RR types or no RR-versus-NatDex difference. Its `data/games/gen3_frlge/rr_types.json` exists; effective imported mapping and comparison outcome were not executed. These conditions concern fixture/adapter behavior, not a generic missing-package remedy.

**Host capability.** `test_http_server_security.py:119` catches symlink-creation OSError and skips two root-index cases. P0 did not create a symlink or alter privileges; current capability is unknown. Its separate Windows junction test at line 125 skips on non-Windows. This host is Windows, so that platform predicate is false, but junction creation and assertions were not executed. A junction pass would not erase a symlink skip. The frozen release lane rejects all skips, including intentional platform skips.

**Refusal-oracle child probes.** Strings in `test_gen1_release_gate.py:55–60` and `test_portable_ci.py:109–120` intentionally create nested child pytest skip/xfail/xpass/collection-skip cases in temporary directories. The outer tests assert those outcomes are rejected; these are necessary negative controls, not outer-lane skip allowances. No actual top-level xfail marker was found in the selected directories.

**Imported live helpers.** Three selected unit modules (`test_gen1_free_service_speed_policy`, `test_gen1_free_service_error_gate`, `test_gen1_free_service_credit_name`) import constants/functions from `tests/live/test_gen1_free_service.py`; that module imports `publish` from `tests/live/test_gen1_bootstrap_launcher.py`. Both live modules define module `pytestmark` with `skipif(SLINK_LIVE != "1")` at lines 65 and 31 respectively. Constructing those marks during import does not skip the selected unit helpers or collect the live tests; the unit files do not import their `pytestmark` or their test functions. Their direct aiohttp and tool imports remain real import dependencies. `tools/verify_canonical_sources.py:19` falls back from a package-relative to top-level `build_pret_syms` import; that is an import-layout fallback, not a skip. P0 did not call any imported live helper or emulator function.

**Other required execution inputs.** Integration browser tests hard-assert Node (`SLINK_NODE` or PATH), import aiohttp directly and invoke `tests/browser/gen1_patcher.cjs`, which requires Playwright and launches Chromium (`SLINK_CHROMIUM` or Playwright executable path). Missing runtime produces failures, not skips. P0 did not launch/verify these runtimes. `tests/conftest.py`'s live_server startup also fails after its 10-second deadline rather than skipping. These requirements demonstrate why a green eight-input check would not prove unit/integration readiness.

## Known caps and prior measured receipts

Configured outer timeout caps: unit **3600s**, integration **3600s**, live-gates **14400s**, duo-pairs **43200s**. Other checks default to 3600s in `run_check`. These are termination limits, not duration estimates. Inner examples: real UPR scanner subprocess 600s; integration browser communicate 120s and its JS deadline 100s; TCP test server start 10s/teardown wait 5s; release-gate refusal child probes 30s. No new scenario timing was measured.

Read existing `.cache/gen1-release/20260912T114305Z-68603bee/automation.json`, SHA256 `6aa84e4211045872b85cc229848ec75c904642aad0a94d0965727511dc6bc871`. This historical **quick** diagnostic reports unit **956.922s**, process exit 0 but release check failed for two `test_calc_rejects_symlink_escape[0/1]` skips and source drift; integration **92.516s**, process exit 1/check failed with four browser-test failures and source drift. These are old failed-lane timings, not current-source or final-host forecasts. No live/duo duration is established by this quick receipt. Recursive cache discovery also found synthetic nested evaluator reports with zero-second stub checks; those are excluded from timing evidence.

Existing affected-subsystem XML `.cache/architecture-combined.xml`, SHA256 `db31e3d887a1a76429a7cb92dd7a4bd4ad2d06fad68adbffa9cce5eec78bb3ac`, records 640 tests, zero failures/errors/skips and **155.309s** XML suite time, timestamp `2026-09-13T08:37:09.431819-04:00`. The architecture closeout quotes 155.34s console elapsed. This selected model regression is narrower than full unit/integration and provides no campaign/trade duration.

## Outstanding facts and next owner

The coordinator has not designated this host as the final RC machine. Final-host availability/exclusive runtime schedule, live-gate/duo full duration, new scenario/human-route budgets, current symlink capability, import/runtime/browser health, frozen inventory drift, and final full non-quick result remain unknown. No runtime input pass can close those facts. Coordinator independently verifies this receipt and records acceptance/HOLD; any environment repair or suite/live execution requires its own exact grant. Owner P1/P2 choices remain separate from P0.

Additional static presence check resolved the three patcher targets to `patch/gen1/build/companion_blue/SLink-Blue.ups`, `companion_red/SLink-Red.ups`, and `companion_yellow/SLink-Yellow.ups`; all exist. This closes their skip-on-missing-path question only, without evaluating patch content.

## Exact static site appendix

The following source-line census includes nested negative-control source strings. Interpret it using the classifications above; this is a source census, not collected test counts.
```text
tests/integration\test_gen1_canonical_pair.py:22:pytestmark = pytest.mark.skipif(not all(p.is_file() for p in CLEAN.values()), reason="legal clean RBY cartridges required")
tests/unit\test_client_acks.py:41:        pytest.skip(f"{client} does not implement memorialize")
tests/unit\test_client_acks.py:55:        pytest.skip(f"{client} does not implement memorialize")
tests/unit\test_client_upvalue_scope.py:78:        pytest.skip(f"{client} has no top-level `local function dispatch_commands`")
tests/unit\test_client_upvalue_scope.py:123:        pytest.skip(f"{client} has no top-level `local function dispatch_commands`")
tests/unit\test_client_upvalue_scope.py:128:        pytest.skip(f"{client} has no top-level `local function parse_command_list`")
tests/unit\test_connector_fragmentation.py:27:lupa = pytest.importorskip("lupa", reason="lupa is needed to execute connector.lua")
tests/unit\test_gen1_archipelago.py:48:    lupa = pytest.importorskip("lupa", reason="lupa needed to execute the Lua under test")
tests/unit\test_gen1_archipelago.py:82:    lupa = pytest.importorskip("lupa")
tests/unit\test_gen1_archipelago.py:140:    lupa = pytest.importorskip("lupa")
tests/unit\test_gen1_admission.py:36:        pytest.skip(f"{_ROMS[title]} not present")
tests/unit\test_gen1_canonical_moves_trainers_types.py:34:    pytest.skip("pokered/pokeyellow not cloned — run tools/build_pret_syms.py", allow_module_level=True)
tests/unit\test_gen1_fixtures.py:34:        pytest.skip(f"{os.path.basename(path)} not present (fixtures are gitignored)")
tests/unit\test_gen1_force_faint_battle.py:28:lupa = pytest.importorskip("lupa")
tests/unit\test_gen1_generated_maps_fishing.py:43:pytestmark = pytest.mark.skipif(
tests/unit\test_gen1_ghost_battles.py:29:lupa = pytest.importorskip("lupa")
tests/unit\test_gen1_ghost_battles.py:61:        pytest.skip(f"{decomp} not cloned — run tools/build_pret_syms.py")
tests/unit\test_gen1_ghost_battles.py:75:        pytest.skip(f"{decomp} not cloned — run tools/build_pret_syms.py")
tests/unit\test_gen1_injector.py:51:        pytest.skip("clean Red dump not present (ROMs are gitignored)")
tests/unit\test_gen1_injector.py:95:        pytest.skip("slink_red.gb not built — `python patch/gen1/tools/build.py`")
tests/unit\test_gen1_native_continuity_seam.py:29:pytestmark = pytest.mark.skipif(not CLEAN.is_file(), reason="legal clean Yellow cartridge required")
tests/unit\test_gen1_items.py:42:        pytest.skip("pokered not cloned — run tools/build_pret_syms.py")
tests/unit\test_gen1_no_hardcoded_addresses.py:25:lupa = pytest.importorskip("lupa")
tests/unit\test_gen1_observation_loop.py:15:pytest.importorskip("lupa")
tests/unit\test_gen1_panel_pages.py:19:lupa = pytest.importorskip("lupa")
tests/unit\test_gen1_panel_tiles.py:23:lupa = pytest.importorskip("lupa")
tests/unit\test_gen1_panel_tiles.py:78:        pytest.skip("pokered not cloned — run tools/build_pret_syms.py")
tests/unit\test_gen1_patch_validation.py:27:        pytest.skip("user-supplied clean Red ROM required")
tests/unit\test_gen1_pregame_guard.py:25:lupa = pytest.importorskip("lupa")
tests/unit\test_gen1_release_gate.py:55:    ("def test_case():\n    print('999 passed')\n    pytest.skip('allowed skip')\n", [], False),
tests/unit\test_gen1_release_gate.py:56:    ("@pytest.mark.xfail\ndef test_case():\n    assert False\n", [], False),
tests/unit\test_gen1_release_gate.py:57:    ("@pytest.mark.xfail(strict=False)\ndef test_case():\n    assert True\n", [], False),
tests/unit\test_gen1_release_gate.py:60:    ("pytest.skip('collection skip', allow_module_level=True)\n", [], False),
tests/unit\test_gen1_rival_swap_explode.py:43:    lupa = pytest.importorskip("lupa")
tests/unit\test_gen1_rom_content.py:24:lupa = pytest.importorskip("lupa", reason="lupa is needed to execute the Gen 1 game module")
tests/unit\test_gen1_rom_content.py:43:        pytest.skip(f"{path} not present")
tests/unit\test_gen1_rom_scan.py:77:        pytest.skip(f"{path} not present — the scanner has nothing to read")
tests/unit\test_gen1_rom_scan.py:85:        pytest.skip(f"{d} not present — cannot build the independent oracle")
tests/unit\test_gen1_rom_scan.py:432:            pytest.skip("PokeRandoZX.jar not found — put it in .cache/upr/ or set "
tests/unit\test_gen1_rom_scan.py:442:            pytest.skip("java not on PATH")
tests/unit\test_gen1_rom_scan.py:448:            pytest.skip(f"{src} not present")
tests/unit\test_gen1_safe_state.py:21:    lupa = pytest.importorskip("lupa")
tests/unit\test_gen1_sram_boxes.py:23:lupa = pytest.importorskip("lupa")
tests/unit\test_gen1_statics_and_trades.py:24:lupa = pytest.importorskip("lupa")
tests/unit\test_gen1_statics_and_trades.py:76:        pytest.skip("pokered not cloned — run tools/build_pret_syms.py")
tests/unit\test_gen1_statics_and_trades.py:88:        pytest.skip("pokered not cloned")
tests/unit\test_gen1_stat_formula.py:24:lupa = pytest.importorskip("lupa", reason="lupa is needed to execute the Gen 1 game module")
tests/unit\test_gen1_upr_roots.py:25:        pytest.skip(f"{path} not present")
tests/unit\test_gen1_upr_roots.py:28:        pytest.skip(f"{pret} not present")
tests/unit\test_gen2_ap_addresses.py:27:lupa = pytest.importorskip("lupa")
tests/unit\test_gen2_ap_addresses.py:45:        pytest.skip(f"pokemon_crystal.apworld not installed at {APWORLD}")
tests/unit\test_gen2_ball_items.py:25:lupa = pytest.importorskip("lupa")
tests/unit\test_gen2_ball_items.py:97:        pytest.skip(f"{game} not cloned — run tools/build_pret_syms.py")
tests/unit\test_gen1_withdraw_and_explode.py:26:lupa = pytest.importorskip("lupa")
tests/unit\test_gen3_adapter.py:1078:            pytest.skip("RR types not loaded")
tests/unit\test_gen3_adapter.py:1088:            pytest.skip("RR types not loaded")
tests/unit\test_gen3_adapter.py:1098:        pytest.skip("No RR type changes found vs NatDex fallback")
tests/unit\test_manager_prepared_gen1.py:107:    if not clean.is_file():pytest.skip('legal clean Yellow cartridge required')
tests/unit\test_manager_http_hardening.py:178:    lupa = pytest.importorskip("lupa")
tests/unit\test_manager_http_hardening.py:202:    lupa = pytest.importorskip("lupa")
tests/unit\test_manager_launcher.py:14:lupa = pytest.importorskip("lupa")
tests/unit\test_http_server_security.py:119:        pytest.skip(f"Creating symlinks is unavailable: {exc}")
tests/unit\test_http_server_security.py:125:@pytest.mark.skipif(os.name != "nt", reason="Windows junction regression")
tests/unit\test_http_server_security.py:242:    lupa = pytest.importorskip("lupa")
tests/unit\test_overlay_catalog.py:11:aiohttp = pytest.importorskip("aiohttp")
tests/unit\test_portable_ci.py:109:        body = "def test_portable():\n    pytest.skip('unavailable')\n"
tests/unit\test_portable_ci.py:111:        body = "@pytest.mark.xfail(reason='known failure', strict=False)\ndef test_portable():\n    "
tests/unit\test_portable_ci.py:120:        body = "pytest.skip('unavailable module', allow_module_level=True)\n" + body
tests/unit\test_patcher_routes.py:20:aiohttp = pytest.importorskip("aiohttp")
tests/unit\test_patcher_routes.py:169:                pytest.skip(f"{os.path.basename(path)} not present (ROMs are gitignored)")
tests/unit\test_pret_rom_syms.py:39:        pytest.skip("data/pret_rom_syms.json missing — "
tests/unit\test_pret_rom_syms.py:69:        pytest.skip(f"{ROM_FILES[game]} not present (ROMs are gitignored)")
tests/unit\test_rom_type_routing.py:22:lupa = pytest.importorskip("lupa")
tests/unit\test_routes_smoke.py:13:aiohttp = pytest.importorskip("aiohttp")
tests/unit\test_routes_smoke.py:14:pytest_asyncio = pytest.importorskip("pytest_asyncio")
tests/unit\test_routes_smoke.py:195:        pytest.skip("this generation renders no sprites")
tests/unit\test_sprite_html_contract.py:39:        pytest.skip(f"{rom_type} renders no sprite at all")
tests/unit\test_sprite_html_contract.py:51:        pytest.skip(f"{rom_type} renders no sprite at all")
tests/unit\test_upr_pipeline.py:33:        pytest.skip("PokeRandoZX.jar not found — put it in .cache/upr/ or set SLINK_UPR_JAR")
tests/unit\test_upr_pipeline.py:46:            pytest.skip(f"{p} not present")
tests/unit\test_upr_pipeline.py:235:            pytest.skip(f"{path} not present (ROMs are gitignored)")
```

## Configured invocation under P0-config extension

Coordinator READY `5b176fc`, acknowledged before ACTIVE `0637566`; latest observed HEAD at execution `a250d5c821bc03b7e94c9de1e7d2e96aaa8d3e77`. The same recorded interpreter and exact argv ran once with two environment values set only in the child ProcessStartInfo:

```text
SLINK_EMUHAWK=E:/Howard/Bizhawk/EmuHawk.exe
SLINK_UPR_JAR=E:/Google Drive/SLink/.cache/upr/PokeRandoZX.jar
```

UTC start `2026-09-13T13:30:11.4750115Z`, end `2026-09-13T13:30:11.6989428Z` (approximately 0.224 seconds including process setup/capture). Exit code **0**. Exact stdout including final CRLF:

```json
"OK: required input and runtime hashes match\r\n"
```

Exact stderr: `""`. No persistent or parent-process environment change. This result verifies all eight prerequisite policies and the eight fixture/artifact file pins for this configured invocation. The original unset-environment failure above remains part of the receipt. No third invocation was made.

The newly resolved executable and JAR paths now pass their existing SHA256 pins (listed in the eight-entry table). All other paths/policies remain as listed there. The following adjacent files were also individually hashed; every actual SHA256 equals the existing pin:

| Absolute path | Expected and actual SHA256 | Outcome |
| --- | --- | --- |
| `E:/Howard/Bizhawk/dll/BizHawk.Emulation.Cores.dll` | `444bc157418e9b5df5d07e987fc7ad1d2d1c6993676f5b864368027cb4f054d5` | PASS |
| `E:/Howard/Bizhawk/dll/BizHawk.Emulation.Common.dll` | `f557d94912b12bde18413b60d25b3e61332b7bbfc7184349d1289d6ba9f350ee` | PASS |
| `E:/Howard/Bizhawk/dll/BizHawk.Client.Common.dll` | `cf4b643c6911d3c85c5d113caecd4b9e5803264dd0356a73b30ce8cd417bd1f8` | PASS |
| `E:/Howard/Bizhawk/dll/BizHawk.Common.dll` | `15ebdf860bc1d8d9efcaabefe1df69de0b24f31d431b558621df353882f386b9` | PASS |
| `E:/Howard/Bizhawk/dll/NLua.dll` | `f413017bfc7a37dfcaeb6e6c24812fd12ceb2b4b107a066512ed28c13010b234` | PASS |
| `E:/Howard/Bizhawk/dll/nlua/NLua.dll` | `51c65e05123879958e62c764f3c088d63e71e9aadcb65b1e2a426cd7d5a1b015` | PASS |
| `E:/Howard/Bizhawk/dll/lua54.dll` | `4786e0df4caf120e3bedf0b6dda260525df2187c66ded220a21a53ace76b0501` | PASS |
| `E:/Howard/Bizhawk/dll/libgambatte.dll` | `320d615454af44bbe586bcb53afa14a64e834a4156c0d4a731d59cda30ce0722` | PASS |

## Frozen runner handoff

UTC: `2026-09-13T13:32:12.2591298Z`; branch `gen1/rc`, HEAD `fd7a3e8c9f1f1e7843a77157b8f9ab4924cb835b`. Sole dirty path at runner completion: this untracked report; no runner commit. Subsequent observed coordinator diffs from the activation cut are guide/register documentation only. Writer ownership is released for independent coordinator review.

Source bytes inspected (raw SHA256, checkout EOL-sensitive):

| Input | SHA256 |
| --- | --- |
| tests/gen1_release_requirements.json | `cf05e855c997e7db0cce08b1632ea4f6705a92f0ae85bb4acadf09b4eb34cb61` |
| tests/gen1_release_inputs.json | `75f081a717a0123aede6eeafd64530bea27302dd8093429d9d57b9de4145e7f2` |
| tools/verify_gen1_release.py | `c6c3eda791a035de642ca6b400fbb8166252ce9c2353689816cbbd3e7399f7c8` |

Next owner/action: coordinator independently checks both exact process receipts, eight input policies and static census, then records P0 acceptance/HOLD. Remaining runtime questions belong to separately granted F1 or scenario work.
