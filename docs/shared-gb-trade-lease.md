# Shared GB trade lease

`lua/gb_trade_lease.lua` (P4.3c, the O-27 coordinator amendment) holds the GB
trade-lease framing that drives the cartridge-native SLINK TRADE flow: the
16-byte `SLT1` frame, the QUERY / OFFER / PROMPT / APPLY / DONE / RELEASE
commands, generation-then-ack publication, the visit token and the stale-token
refusal. Gen 1 and Gen 2 bind it. Gen 3 does not: its native ops use seq/ack
over EWRAM (`lua/mailbox.lua`).

## Frame

| Offset | Field |
|---|---|
| +0..3 | magic `SLT1` (`53 4C 54 31`) |
| +4 | version (1) |
| +5 | command: 1 QUERY, 2 OFFER, 3 PROMPT, 5 APPLY, 7 DONE, 8 RELEASE |
| +6 | generation (the publisher writes it last) |
| +7 | ack generation |
| +8 | result (offer: 0 accept / 1 decline; DONE: 0..3, 2 = uncertain append) |
| +9 | slot |
| +10 | available |
| +11 | eligibility mask |
| +12..15 | visit token (non-zero) |

## Interface

`Lease.new(spec, io, writes)` returns the lease object (`poll_query`,
`answer_query`, `poll_offer`, `answer_offer`, `arm`, `poll_done`, `release`,
`clobbered`, `observe_entry`, `picked_up`, `hold_consumed`).

The four framing/staging fields below are required. The consumption verifier is optional.

- `lease`: base address of the frame.
- `party_capacity`: bounds the offer slot, the own slot and the mask (`< 2^capacity`).
- `check(payload, token4)`: returns an error string, or nil when the payload is
  valid. It does no writes. This is where mail/invalid-item refusal goes.
- `stage(payload, preimage16)`: writes the per-game incoming mon. It runs after
  validation and before the frame is published, and receives the frame's
  pre-image (Gen 1 backs it up).

The optional `pickup(evidence, expected16)` verifies a binder's native consumption
boundary. It returns true for a bound consumption, false for a poll/no evidence,
or nil plus an error when the native boundary was reached but the request could
not be verified. A thrown verifier error also holds the lease. The latter cases
set `phase="picked_up"` plus `pickup_error`: this is a conservative hold, not a
claim that a physical commit succeeded.

`observe_entry()` records the post-generation-check request boundary while armed,
just before the ROM saves the request on its stack. Foreground/service polls do
not count, including polls refused by caller, movement, publication or generation guards.
Each successful `arm` resets it. For a binder with a consumption verifier, an
armed frame that becomes clobbered after that observation is held as
consumed-but-unwitnessed. It must not be re-staged or withdrawn: the precise
post-restore hook may have been dropped. A matching DONE remains stronger
evidence. Binders without the optional verifier retain their existing
owned-mailbox clobber behavior.

Gen 1 refuses preimage restoration after that boundary and acknowledges withdrawal
with the existing
`trade_done{uncertain=true}` carrier, preserving the native lease and making no
new-key claim while awaiting native completion. After 1800 held frames with missing
consumption evidence, it rescans the party and declares uncertainty exactly once
without any lease write. Late withdrawal and terminal uncertainty show the
player-actionable `TRADE UNCERTAIN - CHECK PARTY` notice. Its armed-too-long tripwire is
a console diagnostic, not an automatic cancellation. Frame holds report the
step and count periodically on the console; hold reasons/counters never go to
the HUD.

`arm(command, own_slot, token4, payload)` checks the command and slot, then
calls `check`. It refuses a zero token, stages, writes the frame, and then
publishes +6. A completion or offer whose token is not this visit's is ignored,
and `release` then refuses it.

`L.OFF_LEASE`/`L.LEASE_SIZE` are `SLINK_OFS_TRADE_LEASE`/`SLINK_TRADE_LEASE_SIZE`
from `patch/gb/slink_abi.inc`. `tests/unit/test_gb_trade_lease.py` fails when
they disagree.

## Binders

- **Gen 1** (`lua/gen1/trade_overlay.lua`): the lease is the borrowed
  serial/map tile union `wSerialPartyMonsPatchList`. The payload is the 44+11+11
  byte mon plus the partner name. `stage` writes enemy slot 0 and
  `wLinkEnemyTrainerName`, and backs the union up after the enemy battle
  struct. It keeps its `arm(command, slot, blob66, name11, token4)` surface and
  `service_address`. `pickup_site` binds the instruction after the ROM's first
  guarded restoration of the borrowed union. The retained stack request and
  restored backup are checked synchronously there. Missing or ambiguous anchors
  disable trading with a console diagnostic while ordinary client signals keep
  running. Service-entry observation supplies the independent fail-closed
  fallback when that precise consumption hit is lost.
- **Gen 2** (`lua/gen2/trade_overlay.lua`, P4.3b): the lease is `mailbox + L.OFF_LEASE`,
  owned, so there is no preimage backup. The payload is the 70-byte mon. `check` refuses a
  mail holder or an item this cartridge cannot hold (D3). `stage` writes only incoming OT
  slot 0, its names, `wOTPlayerName`, count 1 and species0 + `$FF`. OT slot 1 holds the
  cartridge's outgoing preimage, and the binder's own permit cannot reach it. The client
  keeps one visit token from the query answer or PROMPT through APPLY. It binds
  `picked_up` at `SlinkTradePromptEntry` and `SlinkTradeApplyPickup`.

The Gen 1 entry observer runs outside the queued signal failure latch, while retaining bank, PC, ROM-byte and closed-service checks. A previously failed queue therefore cannot hide a subsequent service entry from the conservative lease hold.
