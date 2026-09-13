# D0b: Resolve the clean same-run resume design

This is a **research-only dispatch brief**, not an implementation specification. Current authority/status remains in [the master guide](../RC_MASTER_GUIDE.md). The coordinator sends this path with an assignee/session and confirms the read-only claim. No tests, emulators, code or schema writes are assigned.

## Question and blocking edges

Can a normally saved, cleanly exited selected run gain fresh physical ownership and resume its existing logical run while retaining current identity, rollback, pending-write and native-trade refusals?

Research can begin before the owner decides P2a. Implementation remains blocked by P2a's explicit clean-idle re-enrollment policy, the N0 product launch result, a frozen D0 reporting boundary, a reviewed design/falsifier and coordinator file handoff. P2b/R4 concerns partial native trade after process loss and is a separate decision.

## Start, facts and read scope

Canonical checkout: `E:/Google Drive/SLink/.claude/worktrees/gen1-rby-code-sweep-8d06e2` on `gen1/rc`; source reference `df38453`. Confirm actual HEAD and docs-only divergence. Use the current user-assigned coordinator and assignment channel recorded in the master guide; the former coordinator's session is not a prerequisite for this research.

Current facts: `server/gen1_service_continuity.py::verify` requires original admitted metadata/context; `lua/gen1_client_entry.lua::start` creates new physical/context nonces on restart. Existing owned SaveRAM preparation does not grant server re-enrollment. Current reattach is a held physical/lease summary, not a full new-run adoption record. Read those files plus `server/gen1_runtime.py`, `server/gen1_native_progress.py`, `server/bizhawk_launch.py`, `tests/unit/test_gen1_service_continuity.py` and `test_gen1_native_reattach_integration.py`. Follow only required imports/data and pinned save/CONTINUE assembly under `.cache/pret` and `data/pret_sources.lock.json`.

Downstream manifest obligations include literal `gameplay.red.reconnect`, `gameplay.blue.reconnect`, `gameplay.yellow.reconnect` and `manager.blue.blue.same-hash`/`manager.yellow.yellow.same-hash`; this research closes none. A future implementation may support them and deep multi-session campaign routes but must select its exact proof claim.

## Deliver one decision-ready report

Permitted output only: `docs/gen1_reference/reviews/D0b-design-<assignment-id>.md`, or return its body if filesystem writes are unavailable. Coordinator owns the guide/catalog. The report must contain:

1. A current call/data ownership map from ordinary save through shutdown, product bundle relaunch, HELLO, held observation and authority decision, with source functions/lines. Distinguish TCP reconnect from script/process restart.
2. The exact present refusal path and the smallest proposed executable reproduction using real new admission/context metadata. A unit test merely changing a reported PID is not proof of an actual bundle relaunch. Describe the test; do not run/write it here.
3. A proposed definition of “acknowledged idle checkpoint”: which source snapshot, actual on-disk flush/readback, per-player/both-player synchronization and durable commit establish it. Every proposed field needs a producer, persistence location, consumer and tamper/rollback check. Label all design choices as hypotheses.
4. Decide which state is authoritative for source/file/lease high-water and whether it shares the rollback domain it claims to detect. Explain retention of immutable initial identity versus new lineage, and allowed epoch/cursor/frame changes.
5. Resolve or enumerate separately: staggered peer exit/relaunch, server restart, source/bundle updates, completed native history, competing old process, pending commands/trade, older/wrong SaveRAM, unwitnessed save and partial checkpoint persistence. Missing owner policy stays explicit.
6. The smallest reversible implementation slice, proposed exact files, positive/refusal oracle, required physical receipt and explicit blockers. Prefer existing interfaces; propose a new seam only with evidence the current one cannot express the claim.

Research Done means the coordinator can accept/reject a specific design or ask one policy question without reconstructing this conversation. It does not mean resume works. Missing authority/evidence leaves the proposed implementation on HOLD.

## Suggested skills

`codebase-design` helps evaluate the chosen interface; `domain-modeling` helps resolve the clean-idle/identity vocabulary; `research` supplies a bounded primary-source gap. After design acceptance, `to-spec` and `to-tickets` produce one buildable vertical slice with explicit blockers; `implement`/`tdd` and `code-review` are later implementation tools. Preserve the repository's current tracker and exact source-file requirements when adapting their defaults.
