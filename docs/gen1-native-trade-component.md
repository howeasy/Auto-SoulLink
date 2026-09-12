# Native RBY trade component evidence

The assembled component in `patch/gen1/src/native_trade.asm` executes the
cartridge's original trade animation and music, removes the selected Pokémon,
appends the received Pokémon, runs native trade evolution, restores the map and
music, and calls the canonical party/dex save routine. It is still unadvertised
and has no production receptionist or command binding.

The expanded real-cartridge run passed all six pytest cases in
`tests/live/test_gen1_native_trade.py`, without skips or deselection:

| Cartridge | Successful trades | Refusals without party/save mutation | Real reset/CONTINUE |
|---|---:|---:|---:|
| Red | 34 | 13 | 1 |
| Blue | 34 | 13 | 1 |
| Yellow | 40 | 14 | 1 |

Successful cases cover party counts 1–6 and every selected slot; incoming
44-byte party data plus 11-byte OT and nickname; four moves with mixed PP-Up
counts; HP/status, DVs and experience; and every canonical trade evolution.
Both nicknamed and default-name evolutions are checked. Expected default names
come from the admitted cartridge's `MonsterNames` table, including padding and
termination. Holding B must not cancel trade evolution.

The matrix also trades byte-identical incoming/outgoing records at party count1,
at the start of a three-member party and at its final slot. The original animation
still runs; equality of party bytes is not a completion receipt. Both codecs now
check collisions within the recipient's retained party/boxes, allowing equal raw
keys across independently validated participants. Logical identity and participant
validation remain separate coordinator responsibilities.

Yellow additionally checks trading its starter at three happiness levels, with
both follower flag states. Happiness/mood, party data, dex data and save checksum
are read back from SRAM. The reset checks reboot the core and use actual
CONTINUE, including Yellow's subsequent canonical walking mood updates.

The test harness enters through an isolated paused-IRQ probe and restores the
original CPU state. This does not establish a production foreground service
hook, receptionist reachability, native partner confirmation, both participants'
native animations, or durable forward recovery. In particular, it is not
Yellow/Yellow trade-completion evidence. Those release requirements remain open.

Separate [interaction component tests](gen1_reference/RECEPTIONIST_TRADE_FLOW.md)
now cover the real receptionist and native partner prompt, and the foreground
service has its own tests without CPU-register redirection.

The [independent result verifier](gen1_reference/TRADE_RESULT_VERIFICATION.md)
now checks every successful party and complete canonical save region. Thirty-three
additional live cases cover move learning during trade evolution. Such evolution
can change a move/PP slot through the original cartridge learning flow; unchanged
moves are not a universal postcondition.

Reproduce locally with the pinned canonical/build/emulator inputs and
`SLINK_LIVE=1`:

```text
python -m pytest tests/live/test_gen1_native_trade.py -q
```

The full local release runner collects this file in its live lane. Its separate
`trade.native-component-oracle` registration describes the limited proof; none
of the production trade requirements is discharged by that registration.

Validated artifacts are retained separately as
`.cache/native-trade-engine-{red,blue,yellow}-{matrix,reset}.json`. Each records
the exact built ROM hash and physical results; running the reset cases no longer
overwrites the matrix evidence. These artifacts and full ROMs remain local.
