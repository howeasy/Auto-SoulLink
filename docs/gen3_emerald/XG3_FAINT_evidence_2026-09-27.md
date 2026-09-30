# XG3-FAINT on the expansion reference build

The wild `linked_faint_active_gen3` row passed on the clean `codex/close-exp`
cut `c9c215f7` with ROM SHA1 `28877d733492299599f2b8fff50493109d72653c`.
The duo used a private state directory and the server's logged test-only route;
production registration and `Entry.ROUTED` remain closed. This receipt does not
qualify trainer, doubles, whiteout, Explode, or the separate XG3-SITES census.

| Evidence | Bound result |
| --- | --- |
| SOURCE/COMPILER | Expansion source `e8bd1cd7` `include/pokemon.h` and `src/battle_end_turn.c:994-1014` place Perish in `BattlePokemon.volatiles`; the compiler probe gives BattlePokemon size 140, Volatiles offset 84, Perish flag byte +10 mask `0x80`, timer byte +30 mask `0x0c`. `data/battle_scripts_1.s:3486-3492` updates both HP words and calls `tryfaintmon`. |
| ROM/MODEL | `PlayerBufferExecCompleted|1 = 0x0805A209` is bound by the reference ROM's `SetControllerToPlayer` store sequence and literal pool. The generated checkpoint admits exactly the three Perish head writes, comm write and controller handoff. Expansion pack, safety, generator and client regressions were green before the live run. |
| PHYSICAL | [A receipt](probes/xg3_faint_c9c215f7_a.txt), [B receipt](probes/xg3_faint_c9c215f7_b.txt), and [Python save oracle](probes/xg3_faint_c9c215f7_pydec.txt) are copied verbatim from the clean run. Both clients and PYDEC passed. The independently dumped save bytes matched the save-site hashes on both sides (`match=true`). |

B's linked lead received `force_faint` while active. The client wrote the five-entry
Perish plan at frame 14912, then the controller slot moved from `0x0805A209` to
`0x08059DB1` in one frame. At frame 15395, the engine showed battle and party HP 0,
the Perish flag cleared, no input and no SLink HP write. The expansion's pinned
`Cmd_tryfaintmon` hook read battler 0 and the player faint counter rising 0 to 1.
The game sent out slot 1. Both memorials were read independently from the saved
cartridges, each exactly once in box 13.

A's normal-input battle has an in-battle raw party-HP-zero watcher before its
`TX faint` and no prior SLink write or force command. Its natural faint did not
produce the `Cmd_tryfaintmon` completion marker on this run, so this receipt does
not qualify that engine site for all faint paths. The oracle uses A's ordered raw
HP witness plus independent save readback for this row. At each actual successful
memorial write, the test-only driver sampled the keyed party mon's raw HP/maxHP;
both samples were 0/20. The saved `BoxPokemon.hpLost` low 14 bits equal 20, and
the adjacent high bits remain unchanged. The source rule is
`src/pokemon.c:2541-2546` (`hpLost = maxHP - hp`).

Run: `python tools/e2e_duo.py --game gen3_exp --scenario linked_faint_active_gen3 --lane xg3-faint-prewrite1 --idle-jitter 37 --keep-data`.
The committed Python receipt identifies the exact source cut and input hashes.
The current generated checkpoint's `open.battle_handoff` text still describes the
pre-live state; this document records the later bounded wild-row result.
