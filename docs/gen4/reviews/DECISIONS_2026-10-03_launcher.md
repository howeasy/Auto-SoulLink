# Gen 4 decisions, 2026-10-03: player launcher and the G3a switch-over

Overlord ruling, relayed for the owner. It accepts the Gen 4 coordinator's option (b).

## Finding

- `lua/slink_gen4.lua:18` dofiles the LEGACY `lua/clients/gen4_hgsspt_client.lua`.
- The rewritten client (`lua/gen4/entry.lua`, `lua/gen4/client.lua` and modules) has no composition root yet: `lua/gen4/run.lua` does not exist.
- Every G1/G2 cut so far loads `lua/gen4/*` through test drivers, never through the player launcher:
  - `lua/tests/probe_gen4_hooks.lua` and `lua/tests/probe_gen4_battle_faint.lua` dofile the modules;
  - the route lanes use the scripted `lua/tests/gen4_route_play.lua`.
- So the evidence covers the rewritten modules, not the path a player launches.

## Rulings

1. **Not in the current freeze.** The owner wants the current release landed fast.
2. **Now, off the Gen 2 digest:** author `lua/gen4/run.lua`, the composition root (`lua/gen4/**` is outside the Gen 2 digest scope). Add a unit test that it composes `entry.admit_routed` -> client.
3. **G3a launcher and server parts** land in the FIRST batched Gen 2 digest window after the current release lands, without waiting for G1 sign-off. These are the `docs/gen4/PLAN.md` §4.6 items:
   - the `lua/slink.lua` NDS block;
   - the `game_detect` rows;
   - deleting `lua/slink_gen4.lua`, the legacy client and `lua/games/gen4_hgsspt.lua`;
   - the `tools/make_release.py` rows.
4. **G4 gate condition:** G4 sign-off requires a qualifying cut launched through the player path:
   - a launcher-resolution test: `lua/slink.lua` NDS block -> `lua/gen4/run.lua` -> `entry.admit_routed` -> client;
   - plus an end-to-end duo row started via `slink.lua`.
   Module-level gate evidence alone does not satisfy G4.
5. **Until G3a lands,** README/RESUME state that the player launcher runs the legacy client and that Gen 4 is pre-release on this branch.

## Why this lives here and not in PLAN.md

`docs/gen4/PLAN.md` is pinned byte-for-byte by the requirements binding (`tests/gen4_requirements.json` `input_sha256.plan`) at the owner's G0 signature (`5eb1e1fe`). Rule 4 is recorded here as a binding G4 condition. It is folded into PLAN §5 (the G4 row) at the next owner-signed re-pin, so this note never silently re-pins a signed input.
