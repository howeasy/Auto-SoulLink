# Polished Crystal RC status

## Freeze 5f4732 — 2026-10-08

This is the current receipt rebind, not release approval. Product cut `e0dc44314`, driver-only fix `d51f3e9c3`, shipped overlay `fe8c57e1034059331ccf25d232ff757d675363b2`.

Code digest: `5f4732503c4ae4820b253fef3b7fc0870a3edf11b62be70868dffba874aa95f1`. Receipt/docs changes preserve it. Every live receipt is DEV; SYNTH setup and unproven scope remain explicit.

## Current receipt gate

| ID | Result | Detail |
|---|---|---|
| LIVE-HELLO-ADMITTED | PASS | live/hello-admitted 2026-10-08 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=5f4732503c4a |
| LIVE-HELLO-GATE-FRAME | PASS | live/hello-gate-frame 2026-10-08 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=5f4732503c4a |
| LIVE-CAPTURE-PARTY-ONLY | PASS | live/capture-party-only 2026-10-08 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=5f4732503c4a |
| LIVE-BOX-CENSUS | PASS | live/box-census-refresh 2026-10-08 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=5f4732503c4a |
| LIVE-R1-MANAGER-PAIR | PASS | r1/manager-randomized-pair 2026-10-08 grade=DEV rom=8af3b5a0 src=fe8c57e1 digest=5f4732503c4a |
| LIVE-R2-RANDOMIZED-BOOT | FAIL | STALE: overlay the cartridge was derived from 29ea04c24a46d9210c899355fe752f32d2880de8 but data/polished/overlay_provenance.json publishes fe8c57e1034059331ccf25d232ff757d675363b2 — re-run this scenario on the current overlay; overlay_provenance_sha256 is 'UNRECORDED': a receipt must record the sha256 of the provenance it was written against; STALE: code_digest UNRECORDED is not the 5f4732503c4a computed from the current code_digest_files — re-run this scenario; expected check "the server presents the executed player's own cartridge table" is not recorded as PASS; expected check 'native party grew by exactly one at the variant capture hook, before client quarantine' is not recorded as PASS; expected check 'observation-only leg has zero Lua writes; variant-catch quarantine writes are retained separately and do not count as write-path qualification' is not recorded as PASS |
| LIVE-R3-REFUSALS | PASS | r3/refusals 2026-10-08 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=5f4732503c4a |
| LIVE-PHONE-ENTRY | PASS | phone/slink-contact-stage-1 2026-10-08 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=5f4732503c4a |
| LIVE-RECEPTIONIST-STACK | PASS | explore/B-trade-receptionist-stack 2026-10-08 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=5f4732503c4a |
| LIVE-POKEGEAR-MEASUREMENT | PASS | explore/C-pokegear-icon-strip 2026-10-08 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=5f4732503c4a |
| LIVE-TITLE-SPLASH | PASS | title/wordmark-vs-clean-control 2026-10-08 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=5f4732503c4a |
| LIVE-WRITES-OVERWORLD | PASS | writes/overworld-faint-deposit-withdraw 2026-10-08 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=5f4732503c4a |
| LIVE-PANEL-PAGES-ROM | PASS | panel/c0-c5-scripted-host 2026-10-08 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=5f4732503c4a |
| LIVE-PANEL-HELLO | PASS | live/hello-panel-true 2026-10-08 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=5f4732503c4a |
| LIVE-PANEL-HOST-PAGING | PASS | panel/real-host-paging 2026-10-08 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=5f4732503c4a |
| LIVE-RIVAL-SWAP | PASS | rival/client-server-native-gate 2026-10-08 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=5f4732503c4a |
| LIVE-EXPLODE-EXPLODE | PASS | explode-live/explode 2026-10-08 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=5f4732503c4a |
| LIVE-EXPLODE-ACTIVE-FAINT | PASS | explode-live/active-faint 2026-10-08 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=5f4732503c4a |
| LIVE-EXPLODE-BENCH-FAINT | PASS | explode-live/bench-faint 2026-10-08 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=5f4732503c4a |
| LIVE-SHIPPED-TRADE | PASS | trade/shipped-native-commit-cold-continue 2026-10-08 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=5f4732503c4a |
| LIVE-DUO-NATURAL-FAINT | PASS | duo/play-faint-natural 2026-10-08 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=5f4732503c4a |
| LIVE-DUO-NATURAL-WHITEOUT | PASS | duo/play-whiteout-natural 2026-10-08 grade=DEV rom=fe8c57e1 src=fe8c57e1 digest=5f4732503c4a |
| OPEN-WRITE-PATH | FAIL | closed_by 'LIVE-DUO-NATURAL-FAINT' is not a LIVE item that PASSes in this run: closing needs a real receipt |
| OPEN-MEMORIALIZE | FAIL | closed_by 'LIVE-WRITES-OVERWORLD' is not a LIVE item that PASSes in this run: closing needs a real receipt |
| OPEN-EXPLODE-RIVAL | FAIL | closed_by 'LIVE-RIVAL-SWAP' is not a LIVE item that PASSes in this run: closing needs a real receipt |
| OPEN-TITLE-SPLASH | FAIL | closed_by 'LIVE-TITLE-SPLASH' is not a LIVE item that PASSes in this run: closing needs a real receipt |
| OPEN-PANEL-PAGES | FAIL | closed_by 'LIVE-PANEL-HOST-PAGING' is not a LIVE item that PASSes in this run: closing needs a real receipt |
| OPEN-IN-GAME-TRADE | FAIL | closed_by 'LIVE-SHIPPED-TRADE' is not a LIVE item that PASSes in this run: closing needs a real receipt |

## Source, build, model and release

Final `python -B tools/verify_polished_release.py --no-release` is pending clearance of the other source/build worker. No concurrent shared-cache build is authorized. RELEASE ZIP is excluded by that command and needs a separate gate.

## Frozen behavior and limits

- Shipped trade commit is enabled; normal launcher and two-sided native commit/server re-key/cold CONTINUE passed in shipped-002. shipped-001 FAIL is retained; a driver-only responder-entry guard fixed premature input. No power-loss/general rollback matrix is claimed.
- Explode Mode and Rival Team Swap are enabled. Rival evidence covers RIVAL0/id3 with a scripted second identity. The three commanded Explosion/faint lanes use TEST HOST commands; they are not natural partner-event evidence.
- Natural faint S2n and whiteout S4n are separate required receipts with disclosed HP=1 conditioning. S4n proves whiteout event sent and partner death via per-mon faint; `whiteout_handler_proved=false`.
- Memorialize party/box origin to box20/index19 is RC parity best-effort, with exact diffs and controls. No persistent owed-burial/three-outcome recovery or save/reset durability is claimed.
- Randomized boot R2 leg b remains failed/pending triage; its historical receipt has not been restamped. Native full-party preparation is freshly hashed and its six keys match the box-census reload.
- Panel-host trace covers every advertised page (1..4), row widths <=16 and staged/rendered equality. Title proof includes the clean-ROM failing control; CGB fresh boot only.

## Reproduce

```powershell
python -B tools/verify_polished_release.py --print-code-digest
python -B tools/verify_polished_release.py --no-release
python -B -m pytest tests/unit/test_verify_polished_release.py -q
```

The manifest is `tests/polished_release_requirements.json`. Receipt evidence paths must remain reachable on the lane host; hashes are verified at judgment time. Full --no-release output, when recorded below, remains a partial run and cannot authorize a release.
