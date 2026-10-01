# Gen 4 decisions, 2026-10-01

## Owner rulings (AskUserQuestion, 2026-10-01)

**D7 latency: end of the current turn.** The owner chose "End of current turn (Recommended)". This refines D7's "immediately, in battle" for the case where the partner's faint arrives while the player is at the move-selection screen.
- **Write point:** the linked active mon's two HP copies are written at the pinned seam, which is the first instruction of `BattleControllerPlayer_TurnEnd` (0x0224A958, ov12, Thumb; the same address in hge). The seam runs before the game's EXP, win/lose and replacement sweeps.
- **Timing:** when the command arrives at the selection screen, the faint lands after the player's choice and the turn have played out.
- **Required evidence:** command-to-effect frame latency is still recorded in the row o receipt.
- **Still in force:** D12 (no fallback) applies, so a missing in-battle effect cannot pass through a deferred write.
- Source: [battle_faint_seam.md](../research/battle_faint_seam.md).

**Faint presentation: try for the normal faint animation.** The owner chose "Try for it (Recommended)".
- **Primary scenario for C1-8:** use controller command 11 entry (0x0224A70C), setting the game's FAINTED bit (ctx+0x213C) so that the normal faint subscript runs. Do not set the bit at TurnEnd entry, because TurnEnd never consumes it and the flag would carry into the next turn.
- **Fallback:** the HP-only TurnEnd write remains the qualified fallback mechanism if the animation path misbehaves. Both scenarios need the independent oracle.

## Coordinator ruling: row f (performance)

- **Measurement:** on HG, receipt `heartgold-0cc5b0ee2c21` with no foreign PIDs, frame rate by number of registered hooks:

  | Hooks | 0 | 1 | 2 | 3 | 4 | 5 |
  |---|---|---|---|---|---|---|
  | fps | 208.6 | 97.3 | 79.7 | 66.1 | 57.9 | 52.9 |

- **Budget is unchanged:** D6 sets the production budget at 0 always-on hooks and at most 3 hooks per armed phase. Never more than 3 are registered at once, and 3 measures 66 fps, which clears 60.
- **The fourth hook is probe-only:** the C1-1/C1-2b phase cases use a fourth hook as an independent raw-observer oracle. Its cost does not count against the production budget.
- **Row f's criterion becomes:** at least 60 fps at the pack's production cap (3), and an observed failure above it (4 hooks at 57.9) as the red control. This keeps D6 as written and does not reopen it.
- **Risk:** the margin at 3 hooks is about 10% on this machine. The pack target of 2 per phase (79.7 fps) remains the design goal. A slower host will need its own measurement.

## Coordinator ruling: box-mon setup for row i and the pc phase (owner 2026-10-01: "I am not playing all the way to getting balls. Sorry. Figure it out")

- **Starter-only saves.** The owner supplies saves with the starter only. hge's second save gives D15 a second trainer ID.
- **Setup is SYNTH.** A box-depositable Pokémon comes from a disclosed SYNTH setup step: `tools/gen4_synth_save.py party2`.
  - It clones the starter into party slot 1 with a new PID, a "SYNTH" nickname and re-keyed encryption.
  - It recomputes the newest bank's CRC.
  - It writes lane copies only, with a sidecar recording the hashes.
- **The behaviour under test runs natively from normal inputs:** walk to the Cherrygrove Pokémon Center PC, deposit one mon (box write plus the modified flag), then a native SAVE and a cold reload.
- **Receipts are labelled.** Every receipt that uses this setup carries `setup: SYNTH` and the sidecar hash.
- **Scope:** this does not apply to row o. Row o and the story-gated legs keep PLAN §7's rule against staging party data.
