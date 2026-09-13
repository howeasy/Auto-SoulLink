# Issue tracker: Gen 1 RC repository ledger

For Gen 1 work, start at [the universal entry](../gen1_reference/README.md). [RC_MASTER_GUIDE.md](../gen1_reference/RC_MASTER_GUIDE.md) is the sole current status, work ledger and dispatch authority. [The package catalog](../gen1_reference/RC_PACKAGE_CATALOG.md) supplies static scope; [the worktree register](../gen1_reference/WORKTREE_REGISTER.md) records checkout ownership. Exact requirements remain in tests/gen1_release_requirements.json.

When a skill says "fetch a ticket," read the card's current guide entry, named dispatch/spec and prerequisites. When it says "publish," the coordinator records the bounded claim in the guide and may write a self-contained brief under docs/gen1_reference/dispatch; link the brief from the guide. Keep blocking edges, literal requirement IDs, exact exclusive files, source cut and positive/refusal exits. A static brief or triage label grants no work.

Only the coordinator approves READY/ACTIVE, reserves files/live lanes, accepts reviewed receipts and updates the guide/register. Implementers acknowledge the exact grant and return their Git/diff/check/evidence handoff. A missing prerequisite remains WAIT/HOLD; an agent cannot authorize itself.

Use to-spec/to-tickets for a newly accepted bounded design, implement/tdd at its agreed public seams, code-review for independent Standards and Spec passes, and handoff when moving work between contexts. Reuse accepted research and completed cards. Repository authority overrides generic automatic-ready defaults.

The GitHub remote does not authorize another RC queue, issue creation, publication, push or merge. Other games/UI retain their own owners; discover their tracker within their authorized scope.

For this RC, Gen1-Collab2 handles context-sensitive Claude work. OMP DeepSeek Flash v4.1 handles short bounded turns; live OMP uses relevant coordination context, while independent work uses isolated workers after a verified transport handshake. Every transport follows the same guide claim, acknowledgment, exclusive-file and receipt-review rules. Current agent/session IDs and assignments belong only in the guide.
