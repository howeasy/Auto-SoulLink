# P14: starters are under the clauses in every generation; Yellow/Yellow is the one exemption

Status: owner decision 2026-09-11 ("Starters should not be exempt from clauses", "Yellow-Yellow is
exempt"). One patch plus one new test file. The patch applies after P13 (it replaces P13's `oaks_lab`
line in the adapter) and after P10 (it adds one argument at the run-config line P10 touches), so it
does not apply to the bare worktree; the full sequence P1, P7, P8, P12, P9, P10, P10-verifiers,
P10-free-run-live, P11, P13, P14 was re-verified in a scratch git repository seeded with the worktree
originals. Verified in the scratch copy: 62 tests across the starter settlement suite and the new
clause suite, ruff clean on the CI selection. This resolves the decision flagged in P13 ("Two
behaviours", item 1) and open decision 1 of `GEN3_BINDING_PLAN.md`.

## The rule

Gen 3 already applies the clauses to starters (`intro` is not in `server/adapters/gen3_frlge.py:48-52`),
so nothing changes there. Gen 1 now does the same at the shared engine, through the adapter's
fixed-species policy: the lab is a fixed-species gift only when both cartridges are Yellow.

| Pairing | Starters | Species and type lock | Result |
| --- | --- | --- | --- |
| Yellow / Yellow | Pikachu and Pikachu, no choice on either side | exempt (fixed-species gift, the engine's own definition) | link |
| Yellow / Red or Blue (either order) | Pikachu against a chosen Kanto starter | applied; Pikachu shares no family or type with Bulbasaur, Charmander or Squirtle | link, always satisfiable |
| Red or Blue / Red or Blue | different choices | applied; the three starters share no type | link |
| Red or Blue / Red or Blue | the same choice | applied | the second starter is rejected (`Species clause: both are Bulbasaur`) |

The pair is known to the run: both variants are in the paired contract. The adapter learns it at
run creation (`get_adapter(..., peer_rom_type=...)`) and again on restore (`bind_peer` from the
validated contract, because `from_document` rebuilds the adapter from the primary variant alone).
When no partner has been declared the clauses apply, which is the standard's default.

## What the patch changes (`P14-starters-under-clauses.patch`, 6 files, 12 hunks)

| File | Change |
| --- | --- |
| `server/adapters/gen1_rby.py` | `peer_rom_type` in `__init__`, `bind_peer()`, and `is_fixed_species_gift`: `oaks_lab` is fixed-species only for Yellow/Yellow; the P13 flag comment is replaced by the decision |
| `server/gen1_run_config.py` | `create_runtime` passes `peer_rom_type=profiles['b']['variant']` |
| `server/gen1_runtime_state.py` | after the contract check, `self.rules.adapter.bind_peer(expected["b"]["variant"])` |
| `server/gen1_engine_bridge.py` | `starter_grant` returns `(link, rejection)`; the rejection is read from the commands the engine returns to the caller (its own) and queues for the partner, before the drain; the memorial obligation for the rejected starter is released as `no_catch` does for a retired catch |
| `server/gen1_starter_settlement.py` | component schema `rby-starter-settlement-v2` with a `rejection` record (player, key, member_id, reason, at); `settle_ready` records it; `verify_state` checks it against the rule state (no link, key unusable, lab pending for the rejected player, retry area set, the partner's starter still pending); the unused `peer` value P13 left is removed |
| `tests/unit/test_gen1_starter_settlement.py` | the pairing test now covers all four outcomes: exempt link (Yellow/Yellow), link (mixed and different choices), rejection (same choice) in both settlement orders, with reopen and verifier pass |

New file `tests/unit/test_gen1_starter_clauses.py` (19 tests): the adapter truth table over the nine
pairings, case and AP handling, `bind_peer`, other fixed-species gifts unaffected, run creation and
reopen declaring the pair, and the bridge outcomes (distinct link, identical rejection with the exact
rule state, Yellow/Yellow exempt, mixed pairs never colliding).

## What happens on a rejection, and what does not yet

The engine's standard path runs (`server/state.py:1597-1630`): the rejected starter is force-fainted
and booked for memorial, the lab stays pending for the rejected player with the area marked for
retry, the partner's starter stays pending, and no link forms. The RC records the rejection on the
settlement component and its verifier holds the run to that state on every reopen.

The physical consequence (faint and burial of the rejected starter) is not executed by this patch.
As with every command the bridges drain, it belongs to the executor map of handoff item 4: the
natural executor is the existing retirement job with a new cause kind (`starter_clause`, source =
the settlement record), and that job must decide what a party of one becomes. In practice a rejected
starter means a new game for that player, and since the run binds each save identity at admission
(`gen1_runtime_state.py`, "RBY saved identity requires explicit reconciliation/migration"), it
means a new run for both. Gen 3 ends the same way today (the fainted, buried starter leaves an empty
party). The rule is avoidable by choosing different starters, which is what the clause is for; the
free-run loop could tell the second player which starters are allowed before they choose, which is a
HUD command on the durable path and therefore also item 4 work.

## Not changed

- The legacy server path (`server/server.py:2660-2675`) builds the Gen 1 adapter from the first
  hello's `rom_type` only, so on that path starters are under the clauses for every pairing,
  Yellow/Yellow included. The release runtime is the durable one. If root wants the exemption on
  the legacy path as well, `self.state.adapter.bind_peer(rom_type)` on the second hello is one line.
- The Gen 3 adapter and `server/state.py`: no shared-module change was needed. The engine already
  asks the adapter, and the adapter already owns cartridge semantics.
- Test inventory: the pairing test was renamed and a test file added, so root regenerates the
  release-gate inventory (`python tools/verify_gen1_release.py --write-inventory`) as for P11.

## Verification

```bash
python -m pytest tests/unit/test_gen1_starter_clauses.py tests/unit/test_gen1_starter_settlement.py -q
ruff check --select E9,F6,F7,F81,F82,F841,F401 server/adapters/gen1_rby.py server/gen1_run_config.py server/gen1_runtime_state.py server/gen1_engine_bridge.py server/gen1_starter_settlement.py tests/unit/test_gen1_starter_clauses.py tests/unit/test_gen1_starter_settlement.py
```

Scratch-copy result: 62 passed. Gen 1 unit run over the scratch copy with every patch applied (`python -m pytest tests/unit -k "gen1 or test_state or gen3_adapter or semantic_events or engine_bridge"`): 4,801 passed, 7 skipped, 5 failed in 850 s, the five failures being exactly the pre-existing acquisition-policy tests of the 2026-09-10 broad run (`test_gen1_acquisition_runtime` x3, `test_gen1_frame_acquisitions` x2: `exempt_grant` vs `boxed_deferred`, identity missing from pairs, physical commands before ordinary frame authority); evidence `.cache/junit/p14_gen1_unit.{xml,log}`.
