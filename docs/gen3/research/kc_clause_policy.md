# KC-CLAUSE: NPC exchange policy requires an owner ruling

Reviewed 2026-09-27 in `C:/slink-wt/g3-kcc`, branch `claude/gen3-kc-clause`, at
`26fa0e1f5956330561d45170e1fdfd57f0164e42`. **No generation rechecks clauses on this
post-exchange migration. Gen 3 already uses the Gen 1/2 path.** Implementation stops here as
assigned: no new rule, production edit, or policy-asserting regression test was introduced.
The observed behavior is pair preservation; whether that should override an enabled clause
needs an explicit owner decision.

## Established facts

- Gen 1 sends `key_change` with `reason="npc_trade"` and the received species after readback:
  `lua/gen1/client.lua:124-127,1591-1621`.
- Gen 2 recognizes the completed exchange in `lua/gen2/signals.lua:761-766`, then sends the
  same reason/new species through `lua/gen2/client.lua:1217-1223`.
- Gen 3 already uses this same path (`lua/gen3/client.lua:472-487`).
- Shared `_handle_key_change` explicitly preserves an NPC-traded pair, performs identity/census
  collision checks, then replaces the key and optional species without a species/gender/type
  clause check (`server/state.py:3397-3423,3467-3517,3519-3540,3606-3625`). No generation branch
  adds such a check. `server/server.py:2378-2380,2490-2494,2582-2598` only delegates, migrates
  accepted presentation, and logs the result.
- `_check_link_violation` has only two production call sites: shiny-bonus formation
  (`server/state.py:2104`) and ordinary pair formation (`:2380`). Capture duplicate prevention
  is `:2271-2316`; wild-encounter rerolls start at `:2558`. The evolution-family check in
  `_is_trade_descendant` (`:1137-1145`) recognizes a native Soul Link trade outcome; it is not
  an NPC-trade species/dupes-clause check.
- The documented species rule rejects shared evolution families and duplicate captures,
  force-fainting the violating capture while leaving its area open (`docs/REFERENCE.md:797`;
  `README.md:184-185`; `server/manager.py:148`). This defines acquisition outcomes, not the
  consequence of a completed NPC exchange on an existing pair. `docs/gen1_requirements.md:114`
  says evolution/NPC migration keeps the link. The randomized design explicitly queues this
  unresolved policy (`docs/gen3/research/randomized_gen3_design.md:220-223`).
- A generic identity rejection is not a cartridge rollback: these reports are emitted after
  the exchange. Reusing `_check_link_violation` directly on an existing indexed link would
  also reject its own keys before reaching the clauses (`server/state.py:3709-3715`), and
  the family scan includes the current alive pair (`:3732-3749`). A future mutation validator
  must distinguish the current pair from another conflicting pair.

## MODEL evidence (no emulator)

An in-memory protocol dispatch probe exercised Red, Blue, Yellow, PureRed, Crystal, Gold,
Silver, FireRed, LeafGreen, Emerald and RR with `species_lock=True`, unique keys, fresh box
censuses, and received species resolved through each selected adapter. On each title:

1. Bulbasaur becomes Charmander beside a linked Charmander.
2. Bulbasaur becomes Charmeleon beside a linked Charmander (same family).
3. Bulbasaur becomes Squirtle while a different alive pair already holds Squirtle.

All **33** changes were acknowledged as migrated and kept the pair ALIVE, with no death or
rejection commands, including subsequent ticks. All **33** subsequent duplicate-capture
controls were refused, proving the rule was enabled. Raw model rows: `.cache/kcc-model.json`.
These are characterization results, not a newly approved policy or physical qualification.

## Owner choices to report (not implemented)

- Explicitly grandfather completed exchanges: adopt the actual received identity and keep the
  existing link; define clauses as acquisition/pair-creation checks and document the exception.
- Enforce clauses continuously: adopt the actual identity first, then retire the newly
  violating pair under a dedicated rule consequence. Specify which pair loses on a duplicate,
  and whether type/gender changes and other species-changing events have the same treatment.
- Prevent a disallowed NPC trade before it commits: a new client/engine preflight mechanism;
  refusing the later key-change report alone cannot undo the game transaction.

Recommendation: obtain the owner decision and apply it consistently across generations. Do
not invent a Gen 3-only penalty or silently treat a species conflict as identity loss.

## Verification / exit

```text
python -m pytest tests/unit -q -p no:randomly -n 4 --dist=loadfile
15365 passed, 515 skipped in 938.22s (0:15:38)
Exit code: 0
```

Full output: `.cache/kcc-full-unit.txt`; SHA-256
`e78e87576e3fa2b10d71e5f40999d0851e1c5089bd900422332924e58ab8d874`. Local ignored ROM/build/fixture
prerequisites were copied from the verified lane and SHA-256 compared. No emulator ran.
This is a clean baseline and characterization receipt, not evidence that post-exchange clause
enforcement exists. No production file changed. After the owner selects a policy, add its
red-first controls across Gen 1/2/3 before implementation; do not infer a penalty from the
existing capture-retry behavior or reuse identity-loss retirement for a species conflict.
