# Staged linked deaths

`server/linked_death_rules.py:record_linked_death` updates a detached
`StagedSoulLinkState` after the generation binding has proved an actor's faint,
current identity and complete link. The binding supplies cause, level, timestamp
and its qualified partner command (`force_faint` or `force_explode`).

Before Pokéball activation, the operation does nothing, including preserving
party ownership. An already dead pair also produces no new effect. A new active
death marks the pair dead, records its cause/time/initiator, removes its usable
party keys and adds both memorial obligations. It returns one partner command
for the caller to publish atomically with the state.

The helper emits no sound, dialogue, storage or game-over commands. It creates
no physical receipt and makes no claim that either Pokémon has been moved or
saved. `update_run_over` records the existing run-over condition without UI
effects: both players activated, a real pair existed, no live links and no
pending captures remain.

Generation code owns source validation, logical identity checks, command IDs,
receipt verification and recovery holds. In Gen1, only the force-faint receipt
binding is selected by the new death settlement route. Explode Mode remains
held pending its own qualified receipt policy. Importing this helper grants no
frames or memory-write authority in any generation.
