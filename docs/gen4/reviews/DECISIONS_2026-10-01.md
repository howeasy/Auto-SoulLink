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

## Owner ruling: performance (supersedes the coordinator's row f ruling)

Owner, 2026-10-01: "We need at least 1x full speed FPS constantly. 58 isnt going to cut it."

- **Requirement:** real play must hold 60 fps continuously at 1x with the full client running (hooks plus per-frame Lua reads, session and HUD). It is measured as sustained frame time, not as an average or an unthrottled peak. A configuration that only reaches about 66 fps unthrottled is not acceptable margin.
- **Measured hook cost (HG, `heartgold-0cc5b0ee2c21`, unthrottled, minimal Lua):**

  | Hooks | 0 | 1 | 2 | 3 | 4 | 5 |
  |---|---|---|---|---|---|---|
  | fps | 208.6 | 97.3 | 79.7 | 66.1 | 57.9 | 52.9 |

  The first exec hook alone roughly halves capacity.
- **Design direction (coordinator, serving the requirement):**
  - **Zero registered hooks in steady state, in every phase.** Battle start and end, outcome, own-mon faints, catches and party/box changes are detected by polling RAM: the zero-hook battle chain, HP and result reads, and validated party/box diffs at settle.
  - **On-demand hooks only.** The only hook is the D7 write seam (cmd-11 entry plus the FAINTED bit, PASS at `a15b7d74`). It is registered when a partner faint command is pending in battle, removed after it fires, and limited to one at a time.
  - **Phase-site hooks become fallbacks** that need a measured, full-client 1x receipt before any is armed in production.
- **Row f criterion:** the production configuration sustains 60 fps at 1x under full client load, both with 0 hooks and with the 1 on-demand hook. The probe's multi-hook curve stays as characterization and is not a pass condition.
- **Open:** measure the full-client per-frame cost and whether the exec-hook cost depends on hook count or merely on having any hook registered.

## Coordinator ruling: box-mon setup for row i and the pc phase (owner 2026-10-01: "I am not playing all the way to getting balls. Sorry. Figure it out")

- **Starter-only saves.** The owner supplies saves with the starter only. hge's second save gives D15 a second trainer ID.
- **Setup is SYNTH.** A box-depositable Pokémon comes from a disclosed SYNTH setup step: `tools/gen4_synth_save.py party2`.
  - It clones the starter into party slot 1 with a new PID, a "SYNTH" nickname and re-keyed encryption.
  - It recomputes the newest bank's CRC.
  - It writes lane copies only, with a sidecar recording the hashes.
- **The behaviour under test runs natively from normal inputs:** walk to the Cherrygrove Pokémon Center PC, deposit one mon (box write plus the modified flag), then a native SAVE and a cold reload.
- **Receipts are labelled.** Every receipt that uses this setup carries `setup: SYNTH` and the sidecar hash.
- **Scope:** this does not apply to row o. Row o and the story-gated legs keep PLAN §7's rule against staging party data.

## Coordinator notes for the client card (from poll_events, 4a645ee4)

- **whiteout:** mirror Gen 3's semantics, where the event is sent when the game's blackout fires.
  - **In battle:** the authoritative polled evidence is the battle's LOSE outcome (`bs+0x2420 == 2`, PHYSICAL at `a15b7d74`). It is latched when the battle ends, for non-exempt battle types. The "area change and full heal" confirmation becomes optional corroboration, not a requirement, so a heal point on the loss map is not a missed whiteout.
  - **Out of battle (poison):** use the all-fainted party plus the blackout task. This stays PHYSICAL-OPEN.
- **D11 npc_trade:** the reducer only notes a `slot_replace`. The client card wires `identity:begin_alias` plus `pending.msg`, `box_generation()` and `rescan_boxes()` (MERGE_DRIFT item 2).
- **Before G2 sign-off, the owner needs to see** ruling 35: the server force-faints a traded-in mon that breaks an enabled clause.
- **Capture identity:** the wild mon's OTID at capture needs a PHYSICAL receipt (PID match plus OTID equal to the foe's or the player's).

## Owner ruling: what counts as 1x (2026-10-01)

Owner, replying to the paced HG floor (receipt `heartgold-8355974c3c30`), "Thats fine was regarding the framerate". The owner accepts the native NDS cadence and its host jitter as 1x.

- **Reference:** the native NDS refresh, 33,513,982 Hz / (6 × 355 × 263) = 59.8261 fps, which is a 16.7151 ms period. The earlier wording, no interval longer than 1/60 s, fails by construction and is withdrawn.
- **Measured floor on HG, paced** (`pace_1x`, frameadvance, Stopwatch, 3000 frames):

  | Run | Mean fps | p99 | Max |
  |---|---|---|---|
  | Overworld, no load | 59.826 | 18.11 ms | 20.46 ms |
  | Overworld + full client load | 59.824 | 18.20 ms | 22.21 ms |

  The jitter is host/throttle noise, and it is present without the client.
- **Row f passes (coordinator operationalization of the ruling) when every production row meets all three conditions:**
  - The rows are 0 hooks + load in the overworld and in battle, and 1 on-demand hook + load in battle.
  - The mean fps is within 0.1% of 59.8261 over at least 3000 paced frames.
  - p99 is no more than 1.0 ms above the same session's bare floor.
  - No interval exceeds 2 native periods (33.43 ms), i.e. no visible dropped frame.
- **Recording:** each receipt records the five `PACE_1X` values and the floor it was compared against.
