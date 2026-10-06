# Polished `memorialize` executor: behaviour spec (DESIGN OF RECORD, NOT IMPLEMENTED)

Source: headless Codex review cx-2b0d0fbe (2026-10-06), claims re-checked by the coordinator against `docs/polished/NEWBOX.md:239-243`,
`lua/gen2/polished_boxes.lua:33,95-105,284-302`, `lua/gen2/client.lua:1136-1160`, `server/state.py:4431-4456`. Today the executor refuses by name
(`polished_overworld.lua` ~:831-838); nothing here changes `supports_box_mon()`.

## Settled without an owner answer
Memorial box = **box 20** (index 19): NEWBOX 6.2 says `Set M = 20` and asks for a ruling only "if a different box is meant"; `gen2_polished.py`
`memorial_box_index()` returns 19 and `B.MEMORIAL_BOX = 20`. The "owner ruling open" comments and the executor's refusal text are stale.

## PARTY-origin (a dead, non-egg party key)
Resolve the alias as the other commands do; require the hold, a complete census and an unambiguous key; refuse mail on the removed slot or any later
slot (mail SRAM is not shifted). Count 1 -> `nil, "last party mon"` BEFORE any write (count-based, as vanilla `boxes.lua:575-582`; do not add a
"healthy survivor" rule, that is the separate parity decision in RC_TRACKER item 5). Pick the FIRST EMPTY slot of box 20 (holes included; ordinary
deposit excludes box 20). Allocate a FRESH pokedb entry (unflagged and unreferenced by gameplay AND backup records, bank 1 then 2), stage and verify,
publish flag/Banks/Entries and verify, compact the party, verify. An interrupted attempt with a published memorial copy is reconciled only by exact
encoded content + identity (never by key alone). **No HP is stored:** `entry_from_party` excludes status (+32) and HP (+34..35).

## BOX-origin (a boxed key in boxes 1-19)
REUSE the same `(bank, entry)`: no allocation, no re-encode, no flag change. Publish the destination Banks bit and Entries pointer in box 20, verify,
THEN clear and verify the source. The helper `B.memorialize` does both in one batch, so a silently dropped destination write could be followed by the
source delete: the executor must stage the destination read-back first. Already only in box 20 -> verified no-op success (even when box 20 is full);
missing everywhere -> `nil, "key not in party or boxes"`; ambiguous -> refuse.

## Client-facing returns (the client concatenates a truthy 2nd value: `true, <table>` raises, `true, <string>` queues a settle and withholds `memorialize_done`)
Success or verified already-buried: bare `true`. `nil, "last party mon"` (the only memorial retry; dropped after game over). `nil, "memorial box full"`
(normalise the helper's `box full`). `nil, "no free pokedb entry: native save required"`. Everything else `nil, <string>`. Extend `O.client_boxes` to
`memorialize`.

## Resurrection by native withdraw
The savemon holds no HP, and native `SetTempPartyMonData` sets HP = MaxHP: withdrawing a buried mon from the PC revives it at full HP. The
executor's own withdraw scans every box including 20. **Owner product question (the only one):** should box 20 prohibit ordinary SLink retrieval (refuse in
the executor and reject DEAD/MEMORIAL keys server-side; native PC withdrawals are still detected, force-fainted and re-buried by the existing state
code, `state.py:3429-3439,3553-3600`), with a narrowly authorised path for non-dead quarantine relocation (`server/server.py:5299-5318` queues
`party_mon` then `box_mon`), or may retrieval stay allowed with later enforcement?

## Durability
Gameplay edits are volatile until a native save (the party reverts with them; backup records are untouched, do NOT edit them). Bare `true` means
verified gameplay completion. `_handle_memorialize_failed` finalises the pending obligation and may mark the pair MEMORIAL even though the mon stayed
where it was, so a memorial refusal is not a no-op for the server. Test ack -> reset -> reconnect for both origins; strict "both games safe before
either moves" coordination is NOT established by the current queue drain (`client.lua:955-976`, `state.py:704-715`).

## Minimum composed-Rig tests (each with a red control)
Party burial (first hole, exact compaction, one done, no settle); boxed burial across both banks (same entry reused, only destination/source
metadata change; red: allocate a new entry); publication safety (a dropped destination write never deletes the source); last-party/rebuild refusal with
zero writes and retry after retrieval; egg/mail/fainted-survivor pins; full memorial box and allocation/backup-reference protection; already-buried
no-op and exact-duplicate reconcile (red: key-only); the real `run_box` emits done with no concat error and no settle (red: return a table, then a
string); unsafe checkpoint/save in progress/bad checksum/incomplete census write nothing; save/reset/reconnect; box-20 retrieval policy once ruled;
byte-cut and silent-write faults never produce a false done (needs the three-outcome contract, BOX_WRITE_CONTRACT.md).
