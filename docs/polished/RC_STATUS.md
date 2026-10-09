# Polished Crystal RC status

## Freeze 856f39 — 2026-10-09

This is the current receipt rebind, not release approval. Product cut `d9876fb9d` (freeze #1 `609f4fc72` + test fallout fixes `a735da98e` + trade result-2 fix `b0f9d8dbd`), driver-only fix `c6b12daff` (`POL_BATTLE_FRAMES`), receipts `f44b6463c` (21) and `80ff2daf2` (R2), integration merge `94e3b2364`. Shipped overlay `fe8c57e1034059331ccf25d232ff757d675363b2`.

Code digest: `856f3995f0bdfc87a1bc080d2249a1e33afcea28627c811a012cb1c8b90c32f9`. Receipt/docs/driver changes preserve it. Every live receipt is DEV; SYNTH setup and unproven scope remain explicit. Evidence root: `F:/slink-work/lanes/pol-freeze2`.

## Full verifier (`--no-release`)

| ID | Result | Detail |
|---|---|---|
| BUILD-CLEAN-ROM | PASS | exit 0 (259s)  [polished] built .sym equals the release .sym \| [polished] --check: build reproduces the committed .sym/.map byte-for-byte |
| BUILD-OVERLAY | PASS | exit 0 (537s)  [polished-companion] moved clean symbols: none; new symbols: ['SlinkDelayFrameBridge', 'SlinkDelayFrameBridgeEnd', 'SlinkMainMenuLoopBridge', 'SlinkMainMenuLoopBridgeEnd', 'SlinkPanel', 'SlinkPanel.WaitForButton', 'SlinkPanel.WaitForStage', 'SlinkPanel.close', 'SlinkPanel.nostage', 'S |
| LIVE-BOX-CENSUS | PASS | live/box-census-refresh 2026-10-09 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=856f3995f0bd |
| LIVE-CAPTURE-PARTY-ONLY | PASS | live/capture-party-only 2026-10-09 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=856f3995f0bd |
| LIVE-DUO-NATURAL-FAINT | PASS | duo/play-faint-natural 2026-10-09 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=856f3995f0bd |
| LIVE-DUO-NATURAL-WHITEOUT | PASS | duo/play-whiteout-natural 2026-10-09 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=856f3995f0bd |
| LIVE-EXPLODE-ACTIVE-FAINT | PASS | explode-live/active-faint 2026-10-09 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=856f3995f0bd |
| LIVE-EXPLODE-BENCH-FAINT | PASS | explode-live/bench-faint 2026-10-09 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=856f3995f0bd |
| LIVE-EXPLODE-EXPLODE | PASS | explode-live/explode 2026-10-09 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=856f3995f0bd |
| LIVE-HELLO-ADMITTED | PASS | live/hello-admitted 2026-10-09 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=856f3995f0bd |
| LIVE-HELLO-GATE-FRAME | PASS | live/hello-gate-frame 2026-10-09 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=856f3995f0bd |
| LIVE-PANEL-HELLO | PASS | live/hello-panel-true 2026-10-09 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=856f3995f0bd |
| LIVE-PANEL-HOST-PAGING | PASS | panel/real-host-paging 2026-10-09 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=856f3995f0bd |
| LIVE-PANEL-PAGES-ROM | PASS | panel/c0-c5-scripted-host 2026-10-09 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=856f3995f0bd |
| LIVE-PHONE-ENTRY | PASS | phone/slink-contact-stage-1 2026-10-09 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=856f3995f0bd |
| LIVE-POKEGEAR-MEASUREMENT | PASS | explore/C-pokegear-icon-strip 2026-10-09 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=856f3995f0bd |
| LIVE-R1-MANAGER-PAIR | PASS | r1/manager-randomized-pair 2026-10-09 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=856f3995f0bd |
| LIVE-R2-RANDOMIZED-BOOT | PASS | r2/randomized-boot-adopt-form-key 2026-10-09 grade=DEV rom=c4af8082 src=fe8c57e1 digest=856f3995f0bd |
| LIVE-R3-REFUSALS | PASS | r3/refusals 2026-10-09 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=856f3995f0bd |
| LIVE-RECEPTIONIST-STACK | PASS | explore/B-trade-receptionist-stack 2026-10-09 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=856f3995f0bd |
| LIVE-RIVAL-SWAP | PASS | rival/client-server-native-gate 2026-10-09 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=856f3995f0bd |
| LIVE-SHIPPED-TRADE | PASS | trade/shipped-native-commit-cold-continue 2026-10-09 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=856f3995f0bd |
| LIVE-TITLE-SPLASH | PASS | title/wordmark-vs-clean-control 2026-10-09 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=856f3995f0bd |
| LIVE-WRITES-OVERWORLD | PASS | writes/overworld-faint-deposit-withdraw 2026-10-09 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=856f3995f0bd |
| MGR-COMPANION-GATE | PASS | polished-crystal target serves overlay md5 a0a52f4036df13619b9daa403114af4d |
| MGR-JAR-PIN | PASS | jar f3a10dd744ff pinned, byte-exact and trusted (SLink fork, built 2026-10-04 (patches 0001-0021; PokeRandoZX.jar)) |
| MGR-PICKER-GATE | PASS | picker lists 'gen2_polished' and the run form offers it |
| MGR-RANDOMIZER-FLAG | PASS | POLISHED_RANDOMIZER_ENABLED is True |
| MODEL-CLIENT | PASS | 5/5 files green |
| MODEL-DATA | FAIL | 6/7 files green |
| MODEL-PHONE | PASS | 1/1 files green |
| MODEL-RANDOMIZER | PASS | 7/7 files green |
| MODEL-RELEASE-GUARDS | PASS | 2/2 files green |
| MODEL-WRITES | PASS | 5/5 files green |
| OPEN-EXPLODE-RIVAL | PASS | status=CLOSED by LIVE-RIVAL-SWAP |
| OPEN-IN-GAME-TRADE | PASS | status=CLOSED by LIVE-SHIPPED-TRADE |
| OPEN-MEMORIALIZE | PASS | status=CLOSED by LIVE-WRITES-OVERWORLD |
| OPEN-PANEL-PAGES | PASS | status=CLOSED by LIVE-PANEL-HOST-PAGING |
| OPEN-TITLE-SPLASH | PASS | status=CLOSED by LIVE-TITLE-SPLASH |
| OPEN-WRITE-PATH | PASS | status=CLOSED by LIVE-DUO-NATURAL-FAINT |
| REL-PLAYER-ZIP | PASS | not executed (run_release=False) |
| SRC-BEACON | PASS | exit 0 (0s) |
| SRC-ENGINE-SITES | PASS | exit 0 (0s)  F:\slink-work\wt\g2-int\data\games\polished_crystal\engine_signals.json and F:\slink-work\wt\g2-int\data\games\polished_crystal\write_checkpoint.json are current |
| SRC-FORMS | PASS | exit 0 (0s)  F:\slink-work\wt\g2-int\data\games\polished_crystal\forms_index.json is current |
| SRC-PACK | PASS | exit 0 (3s)  verified map_names.json (441532 bytes) \| verified area_map.json (261215 bytes) |
| SRC-PROFILE | PASS | exit 0 (0s)  Polished profile is current (SOURCE only) |
| SRC-SCRIPT-SITES | PASS | exit 0 (1s)  [polished-script-sites] reproduces every artifact |
| SRC-UPR-INI | PASS | exit 0 (0s)  F:\slink-work\wt\g2-int\data\polished\upr_polished_entries.ini is current |

Exit code 1. GATE FAILED — 0 manifest error(s), 1 item(s): MODEL-DATA

MODEL-DATA's one non-pass was an absent input, not a red: `test_polished_rom_tables.py:198` skips when the pinned clean Crystal ROM is missing from the worktree's own `.cache/gen2-build/pokecrystal`, and this worktree had none. After copying the pinned ROM (sha1 `f4cd194b`, matching `data/gen2_sources.lock.json`) into that ignored path, `--only MODEL-DATA` passed 7/7 files (`F:/slink-work/lanes/pol-freeze2/verify/only_model_data.txt`). That is a partial re-run; a single clean full `--no-release` with the ROM present is still owed.
Output: `F:/slink-work/lanes/pol-freeze2/verify/no_release.txt`. RELEASE ZIP is excluded by `--no-release` and needs a separate gate.

Full unit suite at the cut (6 shards): 27307 passed, 1 failed, 1553 skipped. The one failure is `tests/unit/test_gen3_expansion_wild_rom.py::test_compiled_wild_table_matches_source_set_zero_and_keeps_duplicate_headers`, a known Gen 3 expansion red outside Polished.

## Frozen behavior and limits

- Native trade result-2 (uncertain after APPLY) now reports `trade_done` after_reset with the vanilla HUD line (`b0f9d8dbd`).
- Shipped trade commit is enabled; normal launcher and two-sided native commit/server re-key/cold CONTINUE passed in shipped-002. shipped-001 FAIL is retained; a driver-only responder-entry guard fixed premature input. No power-loss/general rollback matrix is claimed.
- Explode Mode and Rival Team Swap are enabled. Rival evidence covers RIVAL0/id3 with a scripted second identity. The three commanded Explosion/faint lanes use TEST HOST commands; they are not natural partner-event evidence.
- Natural faint S2n and whiteout S4n are separate required receipts with disclosed HP=1 conditioning. S4n proves whiteout event sent and partner death via per-mon faint; `whiteout_handler_proved=false`.
- Memorialize party/box origin to box20/index19 is RC parity best-effort, with exact diffs and controls. No persistent owed-burial/three-outcome recovery or save/reset durability is claimed.
- Randomized boot R2: both freeze #2 leg-b attempts at the old hard-coded 9000-frame catch-battle guard aborted mid-battle (native capture RNG, no product hold; retained, not bound). The bound run used driver-only `c6b12daff` with `POL_BATTLE_FRAMES=40000` at the same digest and caught 101 form 4 with the capture site firing once. Receipt line 327 says "qualified capture-site hit": read it as observed, not PHYSICAL-qualified. R2/R3 use the retained Manager pair A 8af3b5a0 / B c4af8082, not the fresh R1 cartridges. Native full-party preparation is freshly hashed and its six keys match the box-census reload.
- Panel-host trace covers every advertised page (1..4), row widths <=16 and staged/rendered equality. Title proof includes the clean-ROM failing control; CGB fresh boot only.

## Reproduce

```powershell
python -B tools/verify_polished_release.py --print-code-digest
python -B tools/verify_polished_release.py --no-release
python -B -m pytest tests/unit/test_verify_polished_release.py -q
```

The manifest is `tests/polished_release_requirements.json`. Receipt evidence paths must remain reachable on the lane host; hashes are verified at judgment time. Full --no-release output, when recorded below, remains a partial run and cannot authorize a release.
