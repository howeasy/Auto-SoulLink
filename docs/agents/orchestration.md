# Agent orchestration contract

For SLink engineering work, use this contract at session start, resume and compaction. The active game/worktree guide remains the sole work ledger and grant authority. Explicit owner changes supersede prior task preferences.

- Keep runnable, independent work assigned while capacity is available. Record a concrete dependency or reason for waiting; do not manufacture busywork. Verify worker/process ownership before dispatch.
- Roles, not providers, carry authority; the coordinator may be Claude, Codex or another capable agent. The coordinator orchestrates, validates and integrates. Isolated implementation workers author bounded code; work that depends on accumulated project context goes to the live session that holds it; short bounded checks go to a short-turn worker (currently OMP); independent reviews use an isolated worker that did not author the cut. A repeatedly consulted live peer is contextual support, not a blind reviewer.
- Each implementation records exact exclusive files, source cut, prerequisite, first falsifier, exit evidence and shared-module decision before dispatch. Acknowledgment is required. One writer per shared file and one emulator lane.
- Put reusable lifecycle, transport, state and presentation behavior in shared modules. Game adapters own ROM/data/story specifics. Record the reason for a game-specific implementation; use existing modules before new abstractions.
- Follow applicable skills. For bugs, build a fast red-capable replay of the observed failure before fixing; check the complete bounded state sequence. Review frozen changes independently. Never repeat an unchanged failed live run.
- Update the guide and worktree register at meaningful transitions and before stopping or compaction. Replace stale current status; preserve history separately. Keep SOURCE, MODEL and PHYSICAL evidence distinct; passed local checks are not release readiness.
- Closed owner decisions stay closed unless new evidence or an explicit request reopens them. Current RC routing is Red/Blue; Yellow-specific work is deferred. Scripted normal inputs only, no Computer Use or game-data staging. Route tests request300%;100% is reserved for explicit qualification. Mute is complete and is not a new workstream.
- No push, master merge, parked-worktree deletion or release claim without the required authority/evidence.

## Machine checkpoint

The active guide contains exactly one fenced JSON block between AGENT_CHECKPOINT_START/END markers. It records schema1, updated_at_utc, coordinator_session_id, source_head, live_lane, workers and next_action. Each worker records id, owner, state, exact files, next_action and reuse_decision. States: active, ready, frozen, blocked, done. Blocked entries name their blocker. Completed implementation entries name receipt and independent review references. This block is part of the sole guide, not a separate tracker.

Hooks inject this short contract and check mechanical omissions: stale checkpoint/register, overlapping active file claims, incomplete worker accountability and missing completion receipts. They cannot judge whether work is genuinely useful or an architectural decision is correct; those still require coordinator and independent review. Hooks never auto-stamp, edit the ledger, reset files or silently invent progress. Native hook trust must be approved through the host's supported UI; no trust bypass.
