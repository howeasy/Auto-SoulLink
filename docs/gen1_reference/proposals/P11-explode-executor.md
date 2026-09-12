# P11: `force_explode` executor, as built (Gen 1 R/B/Y)

Status: patch ready, `git apply --check docs/gen1_reference/proposals/P11-explode-executor.patch`
passes from the sweep worktree root (2026-09-11). Built in a scratch copy of the worktree from the
accepted design `P5-explode-executor.md`; nothing in the worktree was edited, the two new files
(`tests/unit/test_battle_force_explode.py`, this note) were added in place. Verified in the scratch
copy: `python -m pytest tests/unit/test_battle_force_authority.py tests/unit/test_battle_force_explode.py
tests/unit/test_battle_force_bypass_and_fallback.py tests/unit/test_gen1_battle_driver_pins.py -q`
= 283 passed (202 before, 81 new; the 140 faint-binding tests unchanged in number and all green),
`python tools/lua_syntax_check.py` = 301 files OK, `ruff check` clean on every touched Python file.
The live gate has NOT been run here; section 6 gives the command.

## 1. What it is

A second binding of the one-instruction write authority, name `rby-battle-force-explode`
(`battle_force_authority.EXPLODE`), sharing the faint binding's two pinned sites, its 18-field
snapshot, its `prepare`/`issue`/`verify_evidence` lifecycle and every refusal, and differing only
in what the ACTIVE linked mon gets written. No new pins, no held write, `held_write_permit`
untouched (`tests/unit/test_battle_force_bypass_and_fallback.py::test_instruction_modules_never_touch_the_held_write_permit`
still passes on the patched modules).

| Site (bank $0F) | R/B | Y | Explode decision for the ACTIVE linked mon |
| --- | --- | --- | --- |
| `loop_head` = `MainInBattleLoop+0` | `4233` | `4249` | not transformed: `wBattleMonMoves[0..3] = $99`, `wBattleMonPP[0..3] = 5` (8 bytes), outcome `explode_armed`; transformed: refused `transformed battle mon keeps the copied moveset`, nothing written |
| `player_action` = `ExecutePlayerMove+0` | `565E` | `57D0` | `wActionResultOrTookBattleTurn == 0`: `wPlayerSelectedMove = $99` (1 byte), outcome `explode_armed`; otherwise refused `turn already taken` |
| either | | | benched linked mon: the faint binding's party write (HP `0000`, status `00`), outcome `benched`; every faint refusal applies first, same reason, same order |

Outcomes: `explode_armed`, `benched`, `refused`, `not_reached`. `explode_armed` is not terminal
(P5 section 2): sleep, freeze, paralysis, confusion or a RUN can still stop the move that turn, so
the caller re-issues while the death stays `pending_faint`; the re-arm is idempotent, before equals
after and the footprint still verifies (unit test
`test_re_arming_after_the_loop_head_write_is_idempotent_...`). The self-KO is the engine's own
`ExplodeEffect` (zeroes the user's HP and status even on a miss), so HP is never in the footprint
and the ordinary `battle_faint` signal follows for that key.

## 2. Addresses, with their source

| Symbol | R/B | Yellow | Source |
| --- | --- | --- | --- |
| `wBattleMonMoves` | `D01C` | `D01B` | `.cache/pret/pokered/pokered.sym`, `pokeblue.sym`, `.cache/pret/pokeyellow/pokeyellow.sym`; `data/pret_syms.json`; `lua/games/gen1_rby.lua` `BATTLE_MON_MOVES_ADDR` (:205, :378) |
| `wBattleMonPP` | `D02D` | `D02C` | same `.sym` files; `BATTLE_MON_PP_ADDR` (:206, :379) |
| `wPlayerSelectedMove` | `CCDC` | `CCDC` | already in `ANCHORS`; `PLAYER_SELECTED_MOVE_ADDR` (:201, :375) |
| `EXPLOSION` | `$99` (153) | `$99` | `constants/move_constants.asm:161` in both trees; `lua/memory_gb.lua:815` `MOVE_EXPLOSION = 153` |

Both symbols now live in `ANCHORS[variant]['addresses']`, so the existing pin
`test_anchor_bytes_and_addresses_match_sym_and_clean_rom` checks them against the `.sym` files on
every run; `test_battle_force_explode.py` adds the battle-struct layout (`moves = species + 8`,
`PP = species + 25`) and the engine text the binding relies on: the confirm's re-derivation
(`ld a, [wCurrentMenuItem] / ld hl, wBattleMonMoves / ... / ld [wPlayerSelectedMove], a`), the
`and PP_MASK / jr z, .noPP` refusal, `GetCurrentMove` loading `wPlayerSelectedMove` with no
membership check, `ExecutePlayerMove`'s `jp nz, ExecutePlayerMoveDone` on a used turn,
`ExplodeEffect` zeroing `wBattleMonHP`, and `DecrementPP` indexing by `wPlayerMoveListIndex`.
Red and Yellow sources are text-identical at every one of these lines.

## 3. Byte footprint the server verifies

* `loop_head`, active, not transformed (R/B addresses; Yellow one lower for the `D0xx` bytes):
  `D01C..D01F := 99 99 99 99`, `D02D..D030 := 05 05 05 05`, in that order, eight rows of
  `{address, before_hex, after_hex}`. All four slots because the menu re-derives the move from the
  chosen slot; PP 5 so no slot is refused. `wPlayerSelectedMove` is not written here (the menu
  overwrites it), and no party mirror (a switch-out makes the mon benched, and the next window
  applies the benched write).
* `player_action`, active: `CCDC := 99`, one row. When the loop-head write already landed, the menu
  put `$99` there itself and the row reads `before 99, after 99`.
* benched: the faint binding's three party bytes, unchanged.

The snapshot gained `moves_hex` and `pp_hex` (8 hex chars each, `SLOT_FIELDS`), for BOTH bindings,
so `verify_footprint` knows the before-bytes of every explode address; `state()` in the faint tests
and the Lua `snapshot()` carry them. The faint binding's decision, write sets and outcomes are
untouched; only the snapshot shape grew from 16 to 18 fields (rows recorded by rounds 1-3 in
`.cache/battle-force-*` predate the two fields and are history, not evidence for the new module).

`verify_evidence` refuses (unit-tested): one changed byte, a move slot left alone, a missing PP or
move write, a ninth (HP) write, a wrong address (the DVs after the slots), a readback that differs
from the snapshot, the eight-byte set claimed at the action site or the one-byte set at the loop
head, the faint footprint under the explode authority and the reverse, a relabelled site, a foreign
binding name, a 4-char or upper-case `moves_hex`/`pp_hex`, a missing slot field.

## 4. How the server selects the binding

The command names its binding: `prepare()` maps `body['cmd']` through
`BINDINGS = {'force_faint': BINDING, 'force_explode': EXPLODE}` and refuses anything else
(`battle instruction authority serves force_faint and force_explode only`); the proof carries the
name, `issue()` fills the site table from it (`sites(variant, proof.binding)`), and
`verify_evidence` decides with `authority['binding']`. `sites()` and `decide()` take a `binding`
argument defaulting to the faint binding; `prepare`/`issue` take none, because a separately chosen
binding could disagree with the command (P5 section 4 chose the same). The scope digests the
command body, so an explode proof cannot be issued against the faint command's scope
(`test_the_command_selects_the_binding_and_the_challenge_rules_are_unchanged`).

Upstream, when Explode Mode is on and the adapter's client handles the command, the shared rule
engine already queues `force_explode` instead of `force_faint` (`server/state.py:2687-2702`,
`server/adapters/base.py:267`), and `gen1_faint_runtime.settle` selects that one physical command
as the death's command (`:161`). The future `pending_instruction` (`BATTLE_FORCE_INTEGRATION.md`
section 1) hands that command to `prepare`, and nothing else has to choose. Two things stand in the
way today and are not part of this patch: `gen1_faint_runtime.py:126-127` still raises for
`explode_mode` (P7 drops it), and the client/server wiring of section 7.

On the Lua side `battle_force_authority.new{owner_id, held, name}` selects the binding the executor
serves (`name` defaults to the faint binding); the executor refuses an authority for the other
binding at arm (`for this owner and binding`), each binding registers its own hooks, and one
challenge ledger rule applies to both (unit-tested).

## 5. Tests added

* `tests/unit/test_battle_force_explode.py` (81 tests, new file): source pins per title; the
  footprints and the untouched faint site table; `decide()` for active / benched / transformed /
  not-linked / used-turn at both sites for red, blue and yellow, each next to the faint binding's
  verdict; server verification of the exact footprint and the refusals of section 3; command-to-
  binding selection, scope, window and hook-convention rules; the Lua executor writing exactly the
  eight or one bytes with HP untouched, idempotent re-arm, benched / transformed / used-turn
  branches matching the server, cross-binding arm refusal and a one-use five-frame window settled
  by `verify_window` as `explode_armed`.
* `tests/unit/test_battle_force_authority.py` (patched helpers only): `state()` carries the two
  slot fields, `before_bytes()` the eight addresses, `evidence()` a `binding=` keyword, the Lua
  `load()` seeds the slots, one `match` string follows the widened `prepare` message.
* `lua/tests/test_gen1_battle_force_gate.lua`: scenario `explode_first` (selected only by
  `scenarios=["explode_first"]`; the default full battle excludes it like `fight_first`). The
  explode executor `XE` is armed for the linked Squirtle from the walk on, so the wild battle's
  first `MainInBattleLoop+0`, before its first menu, is the loop-head site and the eight-byte write
  lands before any menu (a stray battle left by the probe walk is ended by RUN first, with the
  non-linked member). Checks: loop-head row with the eight-byte footprint and the slots reading
  `99999999` / `05050505`; 30 menu frames `not_reached` only; FIGHT, screenshot
  `explode_first_after_write` (the move menu, EXPLOSION in every slot), commit slot 1;
  `ExecutePlayerMove+0` row with the one-byte no-op write and `selected_move == $99` in its
  snapshot (the re-derivation, observed); then the engine: party slot 0 HP `0000` and the wild mon's
  HP lower than before (`s.engine`), screenshot `explode_first_fainted`; the tail takes the next
  mon / RUN as `fight_first` does. Explosion's accuracy is 255/256 in Gen 1, so the enemy-damage
  check can fail one run in 256 while the self-KO still lands.
* `tests/live/test_gen1_battle_force.py::test_active_linked_mon_explodes_under_the_explode_binding`
  (red, blue, yellow): runs that scenario, verifies every row with the server (the input spec now
  carries `explode_sites = auth.sites(variant, auth.EXPLODE)`), and asserts `explode_armed` at
  BOTH sites, the loop-head row's eight `(address, after)` pairs per title, `selected_move_at_execute
  == $99`, slot 0 HP `0000`, enemy HP dropped, SRAM unchanged.

## 6. Live gate command (not run here)

From the worktree root, with the two-mon fixtures built by `tools/gen1_battle_fixture.py` under
`.cache/battle-fixtures/` and BizHawk configured as for `fight_first`:

```bash
git apply docs/gen1_reference/proposals/P11-explode-executor.patch
SLINK_LIVE=1 python -m pytest "tests/live/test_gen1_battle_force.py::test_active_linked_mon_explodes_under_the_explode_binding" -q --junitxml=.cache/junit/explode_first.xml
```

Each run leaves `.cache/battle-force-<title>-*/` with `result.json`, `summary.json` (outcomes,
`engine`, `loop_head_row`, `write_rows`), `gate.log` and the screenshots. The unchanged
`fight_first` and full-battle tests must stay green on the patched gate (they run the faint
binding through the same `step()`; `explode_first` never runs unless selected).

Note on applying: the prototype files are untracked in the sweep worktree and two of them are
CRLF; the patch is LF like P7/P8/P9 and applies through this host's `core.autocrlf=true`
(`git apply --check` passes; a round trip reproduces the scratch content exactly modulo line
endings, git re-emitting the rewritten files as CRLF). Python, Lua and pytest are indifferent.

## 7. Not done (the short-hold wiring of handoff item 5)

* The client-side executor map that arms this binding from a pending `force_explode`: accepting the
  instruction on the frame grant, `Battle.new{name = authority.binding}` per binding, `arm ->
  step_one -> finish` every stepped frame, the rows in the bundle (`BATTLE_FORCE_INTEGRATION.md`
  sections 2-3). Nothing in `gen1_client_entry.lua`, `gen1_frame_*`, `gen1_runtime.py` or
  `gen1_faint_runtime.py` was touched.
* Server `pending_instruction` at `gen1_frame_control.issue_for_control` (section 1 of the same
  note), the `enforcement` record on the death, and the re-issue rule that treats `explode_armed`
  as re-issuable and only `benched` (or the faint signal) as closing.
* P7 (`gen1_faint_runtime.py:126-127`), and `gen1_held_faint` / `gen1_command_receipts` accepting
  `force_explode` as the same overworld receipt for the out-of-battle fallback (P5 sections 5-6).
* The live rows themselves: the peer runs section 6.

Divergences from P5, deliberate: a transformed active mon is refused at `loop_head` (P5 armed it);
the explode binding only ever rewrites the linked mon's own moveset, and the committed turn is still
coerced at `player_action`, so the death lands within the turn either way. The gate arms the explode
executor during the walk instead of after the first menu, because a loop head only fires once per
turn and the first one is the only deterministic one before any move is spent.


## 7. Live results (peer, 2026-09-11, scratch copy with P11 applied, one step_one per frame)

| Title | Result dir | loop_head | player_action | Checks | SRAM diff | Time |
| --- | --- | --- | --- | --- | --- | --- |
| Red | `.cache/battle-force-red-d4gava5l` | `explode_armed` at frame 4383 (moveset and PP rewritten) | `explode_armed` at 4495; `wPlayerSelectedMove` already `$99` (the engine re-derived Explosion from the rewritten moveset, so the write confirmed rather than changed it) | 7/7 | 0 | 18.2 s |
| Blue | `.cache/battle-force-blue-37ovtf17` | `explode_armed` at 3904 | `explode_armed` at 4015 | all | 0 | 11.2 s |
| Yellow | `.cache/battle-force-yellow-2ye70vfw` | `explode_armed` at 3960 | `explode_armed` at 4246 | all | 0 | 12.2 s |

Every row server-verified, hook frame equal to the stepped frame (offset 0). `explode_first_fainted.png`
on Red shows `Enemy PIDGEY fainted!`: the original engine executed Explosion. JUnit files:
`.cache/junit/explode_first_{red,blue,yellow}.xml`, one test each, 0 failures. The result
directories were copied into the worktree `.cache` from the scratch copy.
