# Phase 5 pair board

The run page now uses the reviewed Track A composition: fixed player columns,
one row per link, the bond between the halves, inward-facing HP bars, foes beneath
the fighting player, and an “at stake” label beside the partner. Jersey 20 is the
default. The log remains beside the board at wide widths and below it otherwise.
The old split/combined views are retired.

The board includes Now, In party, Pending link, Split, Boxed, Unlinked, Linked,
Fallen, and Log. Empty, disconnected, stale, rejected, stopped, and persisted-only
states have explicit rendering scenarios. Unknown HP remains unknown. Fallen and
stopped records do not display live HP. Stopped projections omit Now, battles,
party placement, runtime readiness, and effective feature claims.

## Correctness and refinements

- Membership joins use `state.party_keys`. The hydrated split test exposed that
  the inherited `_get_party_ordered` emitted cache keys instead; a boxed mon with
  a stale detail therefore appeared in party. The corrected helper uses cached
  slots only for ordering, retains members whose details are missing, and is used
  only by status serialization and the read-only Debug roster picker.
- Unlinked active mons and caught halves of failed encounters remain visible.
  Doubles retain the full observed opposing side without claiming a specific
  target. When the player's active mon is unknown, its observed foes stay under
  that player's Now card with an explicit explanation.
- Risk compares the weaker raw HP ratio against 35%. Display rounding cannot
  change the result. If the partner's HP is unknown, a known low half can still
  flag risk, but the board does not invent a pair percentage.
- Shared HP rendering uses high above 50%, medium above 20%, and low otherwise.
  The party and linked-party overlays use this same policy. Missing HP no longer
  becomes a fainted mon, and shared stat-stage rendering accepts adapter labels.
- Below 760 px each pair has explicit rows in Player A → bond → Player B order.
  Each half gains a readable player label. The rail becomes a horizontal header
  at phone widths. Player labels and selected tabs retain contrast across themes.
- Setup uses friendly cartridge names and “Game family.” It shows requested
  settings separately from each player's reported availability. Unavailable
  explanations retain full row opacity. Classic and Pixelify preferences remain
  supported alongside Jersey 20 and IBM Plex Sans.

## Debug and refresh

Debug is a native modal drawer outside the refresh target. Opening moves focus
to Close; Tab and Shift+Tab wrap inside; Escape and backdrop closing restore focus
to the invoking control. The backtick shortcut ignores text-entry controls.
Runtime operation decisions independently disable unavailable actions and explain
why. Feature readiness never grants mutation permission.

The page has one two-second coordinator. Embedded Debug consumes its status and
does not open another SSE connection or timer. Standalone Debug retains its
compatibility behavior. Encounter/move disclosures use stable run/player/mon
identities and survive refresh. The status embedded in HTML uses script-safe JSON.
Calc remains a new tab with its selected `?slink=` base and real SSE bridge.

## Preserved evidence and assets

Production font declarations and the board composition were promoted before
removing mockups and Track B from this branch. The reviewed source worktree was
not changed or pruned. Status/capability/run fixtures now live under
`tests/fixtures/ui/status`; archived inputs and Phase 4 comparison captures remain
under `tests/fixtures/ui`.

Eighteen width/theme screenshots, a setup screenshot, and browser check records
are preserved in [the review fixtures](../../tests/fixtures/ui/review/phase5/manifest.json).
They use isolated synthetic data, not admitted cartridges. The matrix covers Gen 3
then Gen 1 at 700, 1100, and 1600 px in default, light, and Funtastic Grape. Every
capture passed pair-overlap, page-overflow, and rail-overflow checks. Keyboard
review covered Setup, encounter expansion, and Debug in all three themes; Gen 1's
19 unavailable mutation controls were disabled with readable explanations.

Final local validation: **3808 passed / 3 skipped** in the full unit/integration
suite; **3503 passed / 308 named deferrals** in the portable lane, with zero
selected skips or xfails. The three local skips remain the optional unbuilt Red
companion component and two Windows file-symlink privilege cases. Canonical input
verification passed before testing; private inputs are not part of this change.

The explicit portable inventory replaces retired view tests with board and
scenario contracts: 77 reviewed additions and 37 removals, with all 308 named
resource/platform deferrals preserved. Six Node checks cover DOM text safety,
embedded Debug coordination, the real calculator bundle, and platform-safe asset
copying. Required Ruff and all 216 Lua parses pass.
The SVG composition guard now recognizes both supported Jinja quoting styles.

Manager run selection/lifecycle controls, the final shared destinations, saved
broadcast sources, and the verified randomizer workflow remain later phases.
This board validation does not complete emulator E2E or cartridge release gates.
