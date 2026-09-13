# RC planning review evidence

Static review record, 2026-09-13. Current assignments/status belong to [the master guide](../RC_MASTER_GUIDE.md). This records what the reviewers actually checked and what remains unknown; it grants no work authority.

## W0 source and manifest review

Source baseline `df38453`; document consolidation `666b44e` and later fact/design corrections `71549b8`/`3019cae`. Three read-only audits covered native/recovery (`memory_boundary_fix`), C storage (`free_loop_perf_audit`), and D/E manifest mapping (`manifest_campaign`). Claude adversarial tasks `cx-8a08454a` and `cx-2c0d29c6` challenged the integrated plan. Their session messages were inputs; the checkable evidence is the repository source below.

| Checked finding | Primary evidence and incorporated consequence |
| --- | --- |
| 388 requirements, 224 registered, 164 empty; 15 checks, eight prerequisites | [Manifest](../../../tests/gen1_release_requirements.json). D1–D20 expand to all 60 gameplay IDs, E to all 40 artifact/browser empties, T to 55 trade empties; five duo, two Manager, Yellow PC and human make the remaining nine. Set expansion had zero missing/duplicate IDs. Every gameplay ID has two text-speed values. |
| Registered component/legacy proofs do not establish selected gameplay | The 13 registered trade rows cite standalone/fixture tests, while seven registered duo rows use `tests/e2e/test_duo_gen1.py` and `tools/e2e_duo.py`. Existing all-nine umbrellas cannot be closed by bounded Y/Y+R/B proof. F0 reviews assertion bases rather than relabeling them. |
| Actual product launch was not exercised by selected-fresh smoke | `tests/live/test_gen1_native_selected_fresh.py::checked_downloads` calls `prepare`; the live jobs invoke `run_gate`. `server/bizhawk_launch.py::launch` and `tools/launch_bizhawk.py` remain a separate physical N0 claim. |
| Reattach summary cannot supply the complete proposed recovery evidence | `lua/gen1_native_reattach.lua::read` records overlay/PC/SP/bank/limited host and lease summary. `server/gen1_native_reattach_runtime.py::classify` holds non-idle states. This motivated separate R0 pure decisions, R0b evidence, R1 rebind and R2 forward packages. |
| New physical context is not existing same-run resume | `server/gen1_service_continuity.py::verify` compares initial physical metadata and context; `lua/gen1_client_entry.lua::start` generates fresh nonces. D0b clean resume remains proposed and separate from R4 interrupted-trade replacement. |
| Multi-link whiteout is a source defect; ID ownership crosses two modules | `server/gen1_whiteout.py::settle_whiteout` rejects remaining collateral force commands; `server/gen1_faint_runtime.py` owns death IDs and durable peer-command phases. C1 cannot be scoped to whiteout alone. |
| C2 is parked modeled behavior, not merged migration support | Clean parked branch `f8325dc` on old base `4b28727`, especially `gen1_storage_runtime.py` and `WHITEOUT_REBUILD_HANDOFF_2026-09-12.md`, proposes `rebuild_holds` and legacy/changed-survivor refusal. C2 must re-review against current HUD/source. |
| Yellow deposit is not a blanket prohibition | Pinned `pokeyellow/engine/pokemon/bills_pc.asm` and `home/pikachu.asm`; `lua/games/gen1_rby.lua::prepareDeposit` allows normal following, refuses disabled/sleeping following, applies happiness/mood effect. The old broad guide wording was corrected. |
| Several short card descriptions had omitted required oracle detail | Manifest descriptions supplied Game Corner success ordinals; mixed-title Yellow starter retirement; full rods/areas; all active move/PP slots; battle/menu-busy partners; five-minute pre-COMMIT expiry; one-sided verified recovery; serial overlay/enemy staging. Catalog exits were expanded to retain those exact obligations. |
| Final proof must be executed on one unchanged cut | `tools/verify_gen1_release.py::main/run_check/complete_human` requires current registered assertions, all checks, no skips/drift, collection inventory and later human attestation. Pre-freeze receipts remain development evidence. |

## Fresh-session test

At documentation HEAD `fd18449`, a new `cold_start_audit` agent received **no conversation history** (`fork_turns=none`). Its only project entry was the canonical checkout's `AGENTS.md`. It followed the pointers and performed source/Git reads only. No tests, emulator, writes, worktree changes or outside messages ran.

It correctly identified canonical `gen1/rc`, code cut `df38453`, newer documentation-only commits, root `master`, all 388/224/164 counts, the source-versus-physical proof boundary, coordinator-only claims, the P0 inspection steps and exact RC/human finish lines. It produced an executable P0 brief and correctly refused to treat D0b as an implementation-ready capability. It did **not** inspect historical gameplay receipts and therefore did not certify their reported passes.

The audit found these actionable gaps:

- Java has executable presence only; seven of eight manifest prerequisites have hash pins. The guide/catalog now state this actual policy.
- P0 static/input inspection and F1 unit/integration execution needed separate scope. The [P0 brief](../dispatch/P0-preflight.md) excludes suites/install/privilege changes; F1's later assignment must expressly include suite commands and outputs.
- Coordinator identity, receipt location, interpreter/host discovery and allowed writes must travel in the assignment. A catalog row alone is insufficient. The P0 and [D0b research](../dispatch/D0b-research.md) briefs contain those fields and preserve coordinator-only activation.
- Historical evidence paths must be resolved under the canonical RC checkout because `.cache` is ignored; missing evidence needs verified transfer, not an invented path or rerun.
- “W0 done” needed this durable record so the successor can retrieve its findings. Source mapping remains reusable; a card's unresolved design still needs its own first falsifier.
- D0b has real unanswered questions: clean save/flush acknowledgment, both-player synchronization, authoritative high-water, rollback domain, fresh identity lineage, staggered exits, source/bundle updates, and pending/previous native work. These remain research outputs/owner choices, explicitly listed in its brief.

The observed result supports **confident navigation and bounded research from a fresh session**. It does not establish that every catalog card can be implemented without further design. The coordinator must supply a complete authorized ticket for implementation.

The same auditor then read the corrected entry/guide and the new P0/D0b briefs. Its follow-up verdict was **PASS for assigned P0 execution and D0b research**, with no material missing project context for either task. The dispatch still supplies the actual assignee, current base HEAD and unique output identity. The second pass involved document reads only and did not promote D0b to implementation-ready.

## Ask Matt routing result

The locally installed `ask-matt` skill and its phase-boundary reference were read, followed by `setup-matt-pocock-skills`, `to-spec`, `to-tickets`, `handoff`, `domain-modeling`, and `writing-for-agents` for suitability. No skill was installed and no external tracker was created.

| Situation | Applicable skill and boundary |
| --- | --- |
| Current documentation and entry pointers | `writing-for-agents`: keep steps/current authority in the guide and disclose static catalog/source detail through conditional pointers. |
| An unresolved design becomes agreed and source-checked | `to-spec`: synthesize that card's decision into a buildable spec; reuse the existing manifest/guide for the project-level contract. |
| Dispatch to a fresh implementation session | `to-tickets`: one self-contained vertical slice with explicit blocking edges. Preserve the existing guide as custom tracker and retain exact file/source pins required by the owner; its default automatic `ready-for-agent` label cannot override coordinator approval. |
| Transfer to another agent type or host | `handoff`: portable entry/assignment references and suggested skills. Refer to durable repo artifacts rather than copy the whole conversation. |
| A concrete failing code path | `diagnosing-bugs`, then `implement`/`tdd` as appropriate, followed by `code-review` against the agreed spec and fixed source cut. |
| A specific unresolved interface or overloaded term | `codebase-design` or `domain-modeling` inside that card; the current task does not justify a new project-wide architecture survey or glossary. |

The setup/spec/ticket skills' default GitHub tracker, new global doc layout, broad interviews and automatic readiness are not adopted: the owner already selected a durable repository queue, exact paths and coordinator approval. This is a recorded adaptation to existing project authority, not a claim that their default setup was run. Skills guide execution; available tools and verified repo artifacts remain the evidence.
