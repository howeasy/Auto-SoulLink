# Polished box commands: the three-outcome write contract (DESIGN OF RECORD, NOT IMPLEMENTED)

Source: Polished Codex peer review cx-ec39f73b (2026-10-06), re-checked by the coordinator against `server/state.py:527-534,593-608,617-658`
and `docs/protocol.md` 2.6. Status: **proposal; needs an owner go** because it changes shared `server/state.py` and `docs/protocol.md`
numbering and must pass a Gen 1/Gen 3 regression pass first. Companion: the gap list in `RC_TRACKER.md` (item 3). The simple client
contract fix (bare `true` on success, `party full` retry) already landed with `O.client_boxes` (commit 4bda8793d); this document is the rest.

## The problem
`box_mon` / `party_mon` can fail AFTER bytes changed. Today every refusal becomes `box_mon_failed` / `sync_retrieve_failed`, and the server
assumes the move did not happen (restores the party model, drops the rebuild key, re-boxes the partner). Deposit stages the entry, publishes
flag/Banks/Entries, compacts the party block, writes the count last; withdraw appends record/OT/nick, count last, clears Entries then Banks.
A late read-back refusal can follow a move that completed; a compaction cut can tear OTHER party slots. A census key list cannot tell.

## Contract (one new event, opt-in)
- Event `box_write_result{key, cmd, write_id, outcome, reason?, party_count?, stats?}`; `cmd` is `box_mon` or `party_mon`; `outcome` is exactly
  `PROVED_COMPLETE`, `PROVED_NOT_COMPLETE` or `UNCERTAIN`. No `box_mon_done` (protocol.md documents its absence).
- Negotiated: the Polished hello declares `box_write_contract:1`; the server then tags each command with an opaque `write_id` (stable across
  redelivery, new per attempt). An untagged command makes the Polished client write NOTHING. Gen 1/3 and vanilla Gen 2 are untouched.
- For an opted-in operation the result REPLACES every legacy emission including the pre-execution `stats_cache` (the generic keyed ack and the
  optimistic discard happen before the executor runs): stats ride in the result. The server validates ID/key/cmd/player BEFORE the generic ack.
- PROVED_COMPLETE: deposit discards the key; withdraw adds it and marks the rebuild key restored; `party_size` = the proved count; no partner
  compensation. PROVED_NOT_COMPLETE: restore/discard the key, then the existing definite-failure side effects once. UNCERTAIN: add/discard
  nothing, do not touch the rebuild plan, no partner re-box, suppress further mutating commands for the key AND any party mutation / authoritative
  party publication from that client until a proved terminal disposition; retain later death/memorial intent. Terminal results are idempotent,
  never reversible; UNCERTAIN may resolve once to a terminal under the SAME id. Gate at the enqueue/model handlers AND at delivery.
- Owed result: a narrow client slot retransmits the last result after reconnect until `box_write_ack{write_id, outcome}`; no repeated writes.
- New protocol assertion 48 (after 47); qualify assertions 3, 28/29/31 by cross-reference; do not renumber.

## Classifier (client, Polished-only seam `O.client_boxes`)
Capture before the first write: id/key/cmd, source and destination coordinates, the FULL party block and count, the touched box metadata and
sealed entry, the planned exact postimage, the live rebuild options, the permit-log start. Mark attempted before the first mutator. After a
failure, inside a valid hold: reread the complete boxes, the exact party block/count, the touched pointer/Banks/allocation bytes and entry
checksum; read the operation's permit receipts (they locate possible mutation, they do not prove I/O). COMPLETE needs the exact planned
postimage with every other active mon untouched; NOT_COMPLETE needs the source present, the destination unpublished and the party preimage
intact; everything else is UNCERTAIN (never inferred from the refusal text, never auto-repaired for deposit).
| point | evidence | outcome |
|---|---|---|
| D1 staged only | party exact, no reference/allocation change | NOT_COMPLETE |
| D2 publish | metadata at preimage / flag-only, Banks-only, duplicate or invalid reference | NOT_COMPLETE / UNCERTAIN |
| D3 compaction | full planned party+box postimage / any torn or mixed array | COMPLETE / UNCERTAIN |
| D4 late readback | fresh postimage / fresh safe preimage / else | COMPLETE / NOT_COMPLETE / UNCERTAIN |
| W1 pre-count | active party and source exact | NOT_COMPLETE |
| W1 count landed | exact appended slot + source retained: bounded both-places reconcile (same id, same context); torn slot | COMPLETE after reconcile / UNCERTAIN |
| W2 Entries/Banks | Entries 0 with a valid party: finish only the planned Banks cleanup under a fresh permit, verify | COMPLETE; else UNCERTAIN |
| W3 late readback | exact postimage | COMPLETE (never inferred from the source box being absent) |
Hook: in `client.lua` `run_box`, after the physical key/name resolution and BEFORE `stats_cache`, route `box_mon`/`party_mon` through the wrapper
when it advertises the capability and return; the vanilla `lua/gen2/boxes.lua` contract is unchanged.

## Minimum tests (each connects the real Rig client output to `State.handle_event`; a red control each)
T1 legacy isolation + untagged writes nothing; T2 safe negatives (D1, W1 pre-count); T3 late COMPLETE (D4, W2 k72) no NACK compensation and no double
effects; T4 withdraw k71 both-places incl. a full party, torn slot stays UNCERTAIN; T5 deposit compaction byte cut -> UNCERTAIN, no retry, no partner
command, no torn party published; T6 hold closure against tick/census/stats_cache/other keyed events/expiry/partner PC events; T7 identity and
replay (wrong id/key/cmd, old terminal, reversal); T8 reconnect/result loss with an owed-result resend.

## Not covered (named)
Emulator reset, power loss, savestate load, script reload and server restart are not recoverable from in-process context: a fail-closed
unresolved marker must survive a reconnect, never silently become NOT_COMPLETE; closing it needs pinned before/after native-save copies, a
durable operation identity or reconstructible evidence, a fresh boot census, byte readback and cut/reload tests across each write boundary. A
WRAM mailbox byte cannot supply this. Native-save durability is separate from volatile logical completion.
