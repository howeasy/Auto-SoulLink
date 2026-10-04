# QUEUE: the server's committed run artifact_kind depends on which hello lands first

Status: **needs-triage** (owner). Opened 2026-10-03 from the final-cut rows `frlgcr_admit_randomized_{frlg,emerald}` (cut d5a26da9).

## What happens

`server/server.py:2271-2284` commits the run's `artifact_kind` from the FIRST hello of a run (declared kind, replaced by the
adapter's `pairing_kind_for` result when that differs). A later hello is only compared against it (`_mixed_games_error`,
`gen3_frlge.pairing_kind` maps `companion` to `clean`).

So the same pair of cartridges records different committed kinds by timing:
- the plain companion partner first: committed `companion`;
- the clean-equivalent randomized cartridge first (hello kind `rand`, content pairing `clean`): committed `clean`.

Evidence: in `fc_frlgcr_admit_randomized_frlg_d5a26da9.txt` and `fc_frlgcr_admit_randomized_emerald_d5a26da9.txt` the companion hello landed first
(gap to the other side's hello 0.43 s on FR/LG, 0.19 s on Emerald), so `equivalent_pair` saw `gen3_rand_effective_kind = companion`,
while the oracle then demanded `clean`. An equivalent cartridge first would have committed `clean`.

## Why it matters

Harmless for admission today: both kinds are one pairing class and nothing else reads the committed kind to refuse a cartridge.
Misleading under the patch-required policy: the run record (`state.artifact_kind`, status, notes) can say `clean` for a run in which
every cartridge carried the companion, and `companion` for another run of the same two carts.

## Done on the harness side (this change set)

The `equivalent_pair` oracle accepts the pairing class `{clean, companion}` (`GEN3_EQUIVALENT_PAIRING_KINDS`), and keeps `rand` for the
pair leg. The wording is "effective pairing class clean (committed kind clean or companion, by hello order); unknown-hash companion
admitted by anchors + mailbox".

## Not done on purpose

A server change (commit the pairing class, or a dedicated "all carts carry the companion" flag) edits `server/**`, which stales Gen 2's
CODE_DIGEST (about a 2 h re-sweep). Batch it with the next server window and ping Gen 2 first.
