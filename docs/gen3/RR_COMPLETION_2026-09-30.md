# Radical Red completion — 2026-10-01

> **Update 2026-10-03 (patch-first):** the RR clean rows `linked_faint_active_clean_gen3` and `faint_cmd_clean_gen3` are retired and `native_absent_gen3` is now the clean-RR refusal proof, so the RR plan is 39 rows, not 41. The 41/41 record below stays as history; see [RR_CLEAN_ROWS_CONVERSION_2026-10-03.md](RR_CLEAN_ROWS_CONVERSION_2026-10-03.md).

RR passed the complete **41/41-row plan** at `aab6fb325780e8a4a94b1b33d0f04c74749a51d5`. The qualified source is integrated into local `master`; this delivery adds documentation and retained evidence only. No push or release publication was performed.

## Qualification

| Evidence | Result | Receipt |
|---|---|---|
| Complete frozen RR plan | **41/41 PASS**, no carried or cached rows | [Exact-cut summary](probes/fc_SUMMARY_aab6fb32_rr.txt) |
| SOURCE/MODEL quick gate | **5,180 passed, zero skips/failures**, all five lanes | [Gate output](probes/source_quick_aab6fb32.txt) |
| Player ZIP build/check/boot | PASS; 182 verified members; extracted ZIP booted RR on the new client | [ZIP check](probes/fc_rr_zip_check_aab6fb32.txt), [boot](probes/fc_zip_boot_radicalred_aab6fb32.txt) |

The quick gate executes SOURCE/MODEL checks only; emulator qualification comes from the separate 41-row cut.

All 41 receipts passed `gen3_final_cut.fc_check` with the exact full source SHA, successful final exit and clean tracked tree. The plan includes all applicable explicit feature/recovery scenarios, Nature Changer and the three School borrowed-party controls. The opcode row reports 27 passed and 12 skipped under its existing deferred-case policy; 41/41 does not claim those cases executed. The owner-signed Mega, ghost and native-text scope is unchanged. Expansion remains paused and production admission refused. FRLG/Emerald historical cuts and a full Gen1/Gen3 release-gate invocation are not re-qualified by this RR run.

## Completed changes and bounded evidence

- RR plan selection now includes the previously omitted gift, hatch, evolution, NPC-trade, species-family and shiny-bonus rows, plus all three explicit trade recovery controls. All ran at this cut.
- Nature Changer has ROM-bound paired PID capture points and a native-input carrier. [Its receipt](probes/fc_nature_change_gen3_rr_as_a_aab6fb32.txt) proves one engine identity mutation, visible census generation 4→5, same-pair retry, migration ACK, alive link and independent saved PID. Shared core/server correction `1c15e3d9` retains retry credit while hidden/disconnected and returns keyed retryable hidden-party rejections without identity mutation. Hidden-window withholding is proved by cross-wire MODEL tests, not by this particular physical run.
- School own-team preview, opponent-team preview and full battle have source-bound prewrite begin and completed-restore points. [Own preview](probes/fc_borrowed_party_menu_gen3_rr_as_a_aab6fb32.txt) and [opponent preview](probes/fc_borrowed_party_opponent_gen3_rr_as_a_aab6fb32.txt) prove zero loan-party client writes during the held window, then native restoration and saved own HP0 from a queued server command. These are command/persistence controls, not natural faint qualification. [Battle](probes/fc_borrowed_party_battle_gen3_rr_as_a_aab6fb32.txt) proves native play, restored own records and one alive link. B is idle/no-save in these three rows; its unchanged saved records are baseline comparison, not a fresh save witness.
- The borrowed battle oracle accepts only the ROM-derived native-heal PP value for empty move slots. Occupied PP and every other saved field remain strict. The new behavior shares the existing lifecycle, transport, state and write gates; RR modules supply ROM facts.
- RR field poison is N/A on the admitted `MOVS r0,#0; BX lr` no-mutation path. This source fact does not waive FR/LG poison coverage. Nature/School companion receipts do not claim other borrowed routes or clean-ROM physical execution.

The bounded implementation cuts received nonauthor Sol and OMP reviews. All three live OMP peers contributed final evidence, archive and cleanup checks. Archive review `cx-b044f897` was reconciled; per-side witness validation was independently checked by the coordinator with an isolated missing-B negative. Final receipt reconciliation is recorded in the orchestration ledger.

## Retained attempts

The summary's attempt column counts final-cut process attempts; nested duo RNG attempts are retained inside each row receipt. Gift and hatch each used the runner's one allowed contention retry. Species preflight and gender-clause unobserved attempts remained within their existing bounded policies; no threshold or guard was relaxed.

The first `aab6fb32` faint-command run passed gameplay but failed the tracked-clean gate because optional `--wire-log` rewrote two committed goldens. Its [rejected receipt](probes/rejected_wire_output_faint_cmd_gen3_rr_as_a_aab6fb32.txt) is retained verbatim. Its 32-member evidence archive has SHA-256 `b383d5d2aefcaf2aec350a90ccc617ef178a3af5b9d6963508d3362a1c818d9d`. After archiving, exactly those two generated files were restored. Optional wire logging was omitted uniformly for row7 onward; reset rows retain their private wire automatically. The clean-tree gate was unchanged, and the corrected-argv faint-command run passed. Historical goldens are not claimed as traffic from no-wire rows.

Earlier Nature, menu and battle failures are retained alongside the separate 8fa699a9 six-feature, ab5021df Nature, 3008cd9b preview and 3ff4932d borrowed passes. These historical cuts do not fill any current row. The earlier e1e2adbd 28+3 delivery and its 4,223-member archive remain recorded in [the prior preservation record](RR_FINISH_PRESERVATION_2026-09-30.json).

## Local delivery and preservation

The tested package is `dist/SLink-player-g4-aab6fb32.zip` in main. [The preservation record](RR_COMPLETE_PRESERVATION_2026-10-01.json) lists hashes for the qualified archive, prior failure/pass archives, 82 retained receipt files, control scripts/logs and the package. The qualified archive contains 1,364 payload members plus its manifest, passed CRC verification, and has SHA-256 `1b8b4e4fabc5ba13f8f1578a2a19aa8aff3ac6c821f22074016277b46b0dd978`. Supplemental build outputs are explicitly contextual; current qualification comes from receipt-bound artifacts.

Source and evidence are committed in local main at `47f520d8`. Task cleanup was **blocked by automatic approval review**, which rejected the removal command with “blocked by policy” before execution. `C:/slink-wt/rr-complete`, its Git registration/metadata and merged `codex/rr-complete` branch remain; there is no unmerged work. All five cache junction objects and their targets remain untouched. The original planning worktree, other lanes, shared cache targets and main's two foreign untracked files are preserved. Prior Windows-blocked rr-finish residue remains documented in the earlier preservation record; no ACL or policy bypass is authorized.
