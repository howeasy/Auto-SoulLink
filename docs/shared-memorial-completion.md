# Staged memorial completion

`linked_death_rules.record_memorial_completion(state, player, key)` records one
already verified physical completion on a detached `StagedSoulLinkState`. It
requires one complete DEAD link and that player's pending memorial obligation.
It removes only that pending key and its usable-party membership. When both
halves are complete, it marks the link MEMORIAL and appends the retired pair to
the staged memorial history. No file or command is emitted.

The generation owns physical evidence, storage limits, save-file receipts,
logical identity consistency and recovery permission. Its journal must commit
the rule/history changes with the exact ACK. Replay must return the original
journal receipt before invoking this helper again; repeated direct calls refuse.
No failed or missing storage proof is promoted to successful retirement.

Portable tests cover both arrival orders, same raw keys across players, one-time
archival and refusal before mutation for missing, alive, incomplete or ambiguous
links. Gen 1 composes this with exact command-bound memorial and save-file proofs.
