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
`clobbered`, `picked_up`).

Every `spec` field is required. If one is missing, `new` asserts.

- `lease`: base address of the frame.
- `party_capacity`: bounds the offer slot, the own slot and the mask (`< 2^capacity`).
- `check(payload, token4)`: returns an error string, or nil when the payload is
  valid. It does no writes. This is where mail/invalid-item refusal goes.
- `stage(payload, preimage16)`: writes the per-game incoming mon. It runs after
  validation and before the frame is published, and receives the frame's
  pre-image (Gen 1 backs it up).

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
  `service_address`.
- **Gen 2** (`lua/gen2/trade_overlay.lua`, P4.3b): the lease is `mailbox + L.OFF_LEASE`,
  owned, so there is no preimage backup. The payload is the 70-byte mon. `check` refuses a
  mail holder or an item this cartridge cannot hold (D3). `stage` writes only incoming OT
  slot 0, its names, `wOTPlayerName`, count 1 and species0 + `$FF`. OT slot 1 holds the
  cartridge's outgoing preimage, and the binder's own permit cannot reach it. The client
  keeps one visit token from the query answer or PROMPT through APPLY. It binds
  `picked_up` at `SlinkTradePromptEntry` and `SlinkTradeApplyPickup`.
