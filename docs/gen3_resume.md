# Gen 3 migration — resume note (2026-09-21, end of session 1)

Read this first after compaction. Authority: the owner-approved plan `docs/gen3/PLAN.md` (rev 5, §6 phases, §14 dispatch, §14.1 gate ledger) and the sole work ledger, the `AGENT_CHECKPOINT` block in the sweep worktree's `docs/gen1_reference/RC_MASTER_GUIDE.md` (`E:/Google Drive/SLink/.claude/worktrees/gen1-rby-code-sweep-8d06e2`). Requirements ledger: `docs/gen3_requirements.md`.

## Where things are

- Worktree `E:/Google Drive/SLink/.claude/worktrees/gen3-migration-planning-5d8e45`, branch `claude/gen3-migration-planning-5d8e45`, pushed to origin on owner authority (2026-09-21) so CI could build the pret symbols. Not merged to master. Base: master `4749a2c`.
- Coordinator: Claude session `92be0738-12a4-4228-b388-eb5fe6f7c779` (Fable 5.1). Codex live thread "Plan Gen3 support" (repo root, `E:/Google Drive/SLink`) is the research/implementation peer; headless Codex persists `gen3-syms`, `gen3-tap` exist (their sandbox cannot run Python: the coordinator runs their checks).
- Owner rulings (G0 signed 2026-09-21): FRLG vanilla + Radical Red only; strangler; battery fixtures; agbcc git pin; admitted companion = what the shipped `SLink-RR.ups` produces (md5 `bf8e94a0…`, patcher pin corrected at `72dffad`); LeafGreen dump placed and verified; keep the two-reviewer G6 precedent; `codex/rr-foundation` tagged `archive/codex/rr-foundation` (local); vanilla FRLG trade NOT in this release; no `sync_pending`/`trade_failed`.

## Gate status

| Gate | Status |
|---|---|
| G0 | SIGNED (PLAN §14.1) |
| G1 | **evidence complete, not yet requested**: hook probe PASS on FR clean + RR companion (`docs/gen3/probes/hooks_*_2026-09-21.txt`), frame-end census (`census_rr_overworld_2026-09-21.txt`: R15 parked in BIOS `0x1C4`, System/ARM), flash domain = `SRAM` 0x20000, six RR duos PASS twice on the old client, golden transcripts committed (`tests/fixtures/gen3/wire/`, 796K, four gzipped), conformance suite 16 passed with the old-client characterization (items 1/14 documented as A19; 29/30 were checker over-assertions; 28 unevidenced). Ask the owner to sign G1 with those receipts. |
| G2 | in progress: packs landed (below); remaining = C2-3c (RR detours), boot-check lane runs, a Haiku spot-check of three pinned sites, the generator report for the owner. |

## Landed this session (planning branch, in order)

P0: `docs/gen3/PLAN.md` (d42088c, 5e9d7ba), `docs/gen3_requirements.md` (3a00150 → Pins filled 4ad934f), `docs/gen3/research/{pins,flash_save,pins_inventory}.md`, `tools/gen3_pins.py`, G0 record `72dffad`.
P1: `lua/tests/probe_gen3_hooks.lua` + `tests/live/test_gen3_probe_gates.py` (79e1e87, receipts 6e064c3), `lua/tests/probe_gen3_frameend_pc.lua` (75903aa, d820052, receipt c363f2d), wire-log tap in `server/server.py` + `tools/e2e_duo.py --wire-log` (b0e0538 → 91c7025 → 8aac4a0 → e643af7; guard PASS ×3, Codex ACCEPT cx-e19e74ac), conformance suite `tests/unit/test_protocol_conformance.py` + `conformance_map.py` (1847c7c → a729205), transcripts committed (a729205), protocol Appendix A19 (ece022d).
P2: pret symbols `data/gen3/pret/` from CI run 35603224233 (20ab8cb; `tools/build_pret_gba_syms.py`, `.github/workflows/gen3-syms.yml`), profiles `data/games/gen3_{frlg,rr}/profile.json` + `tools/gen_gen3_profile.py` (2ef0eb5), engine sites `engine_signals.json` + `docs/gen3_engine_sites.md` + `tools/{pin_gen3_site,gen_gen3_engine_signals}.py` (84d0b6a, a8c32f3: FR/LG 21 kinds pinned, RR 15), write checkpoint packs + `docs/gen3_write_checkpoint.md` (9c6ab37: 67-row writer inventory, idle task allow-list byte-verified in RR), codec `server/adapters/gen3_codec.py` (3bea4be, f7aa76d: RR save layout pinned, `parse_flash` truncation bug fixed), fixtures `tests/fixtures/gen3/rr_town.sav` + `tools/gen3_fixtures.py` (b266f69, d0e8b38: boot-check + make-fr drivers), release runner core `tools/release_lanes.py` + `tools/verify_gen3_release.py` (910dbdd, 8aed5aa, d0e8b38).
Fixes found by the work: `lua/memory_gba.lua` permutation rows 3/4 swapped vs pret (fa9b677, differential test `tests/unit/test_gen3_lua_vs_codec.py`); `server/patcher.py` + `patch/README.md` stale companion md5 (72dffad).

## In flight / uncommitted at compaction

- Nothing. C2-3c landed (09add4e: RR 19 kinds PINNED per artifact; GiveMonToPlayer/SendMonToPC detours followed to their CFRU bodies; SetPlacedMonData edited in place; overworld poison is a verified no-op body on RR so its two rows are un-emitted by design; borrowed_party/nature_change UNVERIFIED with search receipts). `python tools/verify_gen3_release.py --quick`: all four fast lanes PASS (the unit lane now selects by file, never `-k`, because the fail-closed core counts deselection as not-run).

## Next actions (in order)

1. Ask the owner to sign **G1** (receipts above). Record in PLAN §14.1.
3. Lane runs for G2: `python tools/gen3_fixtures.py boot-check --rom patch/build/slink_RR.gba --fixture tests/fixtures/gen3/rr_town.sav --rr` (RR), then `make-fr --rom "E:/Google Drive/SLink/Pokemon - FireRed Version (USA).gba" --out tests/fixtures/gen3/firered_town.sav` (its four intro assumptions are †UNVERIFIED — pin them from `data/gen3/pret/pokefirered.sym`, which the worker did not find); then a `_b` derivation for RR via the now-pinned layout (`derive-b --rr` still refuses: update `tools/gen3_fixtures.py` to use `rr_party_from_save`/`rr_boxes_from_save`, C2-8 finding).
3. Haiku spot-check of three pinned sites against `.sym` + ROM bytes; generator report → owner signs **G2**.
4. Queued out-of-lease (add: RR overworld-poison is a no-op path — the per-artifact coverage table must mark `poison_faint` N/A for RR, not OPEN): `tools/mkstates.py:102` RTC wording; fold `ROM_SPECS` (pin_gen3_site.py) with gen_gen3_write_checkpoint.py's copy; `data/gen3/pret/README.md`; `docs/gen3/research/flash_save.md` §7 bullets superseded by `rr_save_layout.md`; `data/games/gen3_rr/profile.json` `GMAIN_ADDR` fillable (0x030030F0 verified); a "box the last mon" capture to evidence item 28; retire the census probe's two †UNVERIFIED notes (now verified).
5. P3 (shadow observer) opens after G2 per PLAN §6/§14.

## Standing rules that bit this session

Codex headless sandboxes cannot launch Python: always run their checks yourself. The Bash tool breaks on heredocs with odd apostrophe counts: use the Edit/Write tools for code. Shared `server/` changes need `slink-adapter-guard` + a non-author review; the guard blocked once (unguarded tap I/O) and passed after the fix. The fail-closed runner counts a collection-time skip from an unrelated module as a failure: keep lane selectors tight.
