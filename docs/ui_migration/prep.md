# UI migration preparation packet

This packet prepares the approved migration while Phase 0 is closed. It adds no
production behavior and does not import the mockup or an in-flight runtime into
the UI checkout. See [the approved plan](../ui_migration_plan.md) and
[the consumer agreement](../ui_projection_contract.md).

## Baseline and repeatable inventory

`baseline.json` captures the tested HTTP-hardening source at `965cc12664b1c9b5ee27d8fc4a97a5cf06a6b065`
and reviewed mockup inputs at `121fb1c95b636e73e5e54315b41c2d5127c83244`.
The source files, fixtures, and selected fonts carry hashes; text hashes normalize
newlines so Windows and Linux checkouts agree. Font hashes preserve exact bytes.

The recorded source declares **91 run routes** and **20 manager routes**, including
their patcher registrations but excluding the shared static mount. Expanding
implicit HEAD handlers gives **160 run method/path pairs** and **33 manager pairs**.
Both applications additionally mount `/static/` with GET/HEAD. The inventory tests
compare the declarations against both actual routers without constructing a game
server, opening a socket, or invoking application startup.

There are **23 real overlay slugs**, each with a page and fragment route, plus the
synthetic `all` gallery entry. Do not turn the handoff's approximate "25" or a
route-count total into a compatibility guarantee; keep the exact method/path set.

From a checkout with this tool, PowerShell:

```powershell
python tools/ui_migration_inventory.py --mockup-repo '..\soul-link-ui-mockups-40f67b' --output '.cache\ui-current.json'
python tools/ui_migration_inventory.py --mockup-repo '..\soul-link-ui-mockups-40f67b' --compare 'docs\ui_migration\baseline.json'
pytest tests/unit/test_ui_migration_inventory.py -q
```

`--repo` can inspect another explicitly selected checkout. The command defaults to
stdout; only `--output` writes a report. Exit 0 means the inspected declarations
are resolved (and a comparison matches), 1 means contract differences, and 2 means
unresolved/missing input or overlay routes. Inspect differences; do not regenerate
the baseline merely to make them disappear. No server, emulator, ROM, network
access, or production data directory is needed.

Comparisons describe registered **method/path patterns**, not every concrete URL
accepted by a parameterized route. For example, replacing a fixed patch URL with
`/companion/{name}` can preserve the old request URL. Confirm that compatibility
through the handler and route tests rather than treating every pattern removal
as a broken bookmark.

The parser deliberately reads literal registrations and catalog declarations,
not arbitrary Python. Dynamic/table-driven registration must be reported as
unresolved and the auditor adapted when that refactor actually lands. Its
composition assumption is the current pair of shared setup helpers; runtime
parity tests guard that assumption. The report does **not** prove output markup,
HTTP statuses, state hydration, freshness, admission, or release readiness. Phase
1's behavior/DOM guards still have to be implemented after the handoff.

## Phase 0 handoff checklist

- [ ] Gen1 owner identifies the integrated commit and explicitly opens the frozen
  runtime/API handoff. Foundation-only `654c7c7` and `e110592` do not satisfy this.
- [ ] Record the agreed integration base, incoming commit IDs, clean/dirty state,
  and owner of every checkout involved. Never merge another agent's dirty tree.
- [ ] Reconcile Track A PR #1 and its shared HTTP/Lua/JSON helpers; preserve the
  Gen1 script-safe JSON helper, cartridge labels, patcher targets, and immutable
  cartridge binding. Retain legacy companion URL aliases.
- [ ] Obtain actual expected/admitted per-player identity and provenance fields,
  capability evidence, observation-age meaning, and durable recovery fields.
  Keep proposed names out of the public producer until this agreement exists.
- [ ] Confirm the source for stopped-run summaries and restore/rollback behavior;
  renderer code must not replay commands, load live state with side effects, or
  reconstruct authoritative dead/memorial membership from party absence.
- [ ] Obtain the verified UPR catalog/publisher boundary and final-output contract.
  The six UI categories are not the complete scanner/allowlist contract.
- [ ] Integrate the mockup commit after resolving actual conflicts. For the mock
  injector, use Gen1's structure while preserving PC boxes, pending captures,
  low HP, HOLD, and single-socket behavior. Use isolated ports/data directories.
- [ ] Re-run the inventory and inspect new/removed paths, controls, and source
  hashes. Rehydrate and regenerate fixtures from the integrated serializer.
- [ ] Run Gen3 verification first, then other-gen checks, and record the evidence
  before beginning equivalent rendering extraction.

The Gen1 owner reiterated on 2026-09-05 that default runtime/producer integration
remains unfinished. Its new receiver-specific recovery component evidence does
not open this checklist. RR has the consumer agreement and can independently
work on context/native storage; presentation integration still waits for Phase 3.

An offline comparison of the current, **unfrozen** Gen1 tree found the expected
manager additions `/api/runs/{run_id}/cartridges` and `/randomize`, the shared
`/companion/{name}` pattern, and broader encounter-gallery descriptions. The
patch handler still accepts the RR filename through its target registry, so the
pattern replacement does not by itself remove `/companion/SLink-RR.ups`. Both
manager and server source inputs remain modified in that tree. Recheck these
observations against the eventual published handoff; they are not a frozen API.

## Compatibility and extraction map

| Surface | Current owner/entry point | Migration obligation |
|---|---|---|
| Dashboard/status | `SLinkServer._build_status_dict`, `_build_status_html`, `_handle_dashboard_template` | Build a detached context; preserve both views and normalized DOM through Phase 4. Selectors alone do not establish equivalence. |
| Fragile widgets | `SLinkServer._encounter_html`, `_trainer_panel_html`; `_macros.html` | Keep trusted HTML fields explicit; scan retained Python and templates for token regressions. Pass adapter stat-stage labels when reusing macros. |
| OBS fragments | `_render_stream_overlay`, party/battle context helpers, stream `_base.html` | Preserve page/fragment pairs, query controls, and image identity. Pass the resolved URL prefix rather than rewriting HTML strings. |
| Manager lifecycle | `RunManager`, `_spawn_run`, registry helpers | Serialize lifecycle updates after awaits; keep reads off reconciliation/write paths during polling. Preserve Track A corruption refusal. |
| Calc | `handle_calc_files`, `handle_calc_mons`, `slink_bridge.js` | Preserve shared assets, existing `?slink=` target, and real run SSE. HTTP availability is not telemetry freshness. |
| Debug | `_DEBUG_HTML`, run `/api/debug/*` handlers | Drawer changes presentation only; retain handler paths and coordinator semantics. Replace unsafe DOM insertion, not just the Python string wrapper. |
| Patcher/randomizer | Incoming target registry, immutable contract publisher, local inspection | Consume the incoming verified pipeline; do not revive the legacy fingerprint gate or change admitted ROM bytes after hashing. |

### Existing URL and preference obligations

- Preserve all run `/api/*` paths recorded in the inventory. E2E specifically uses
  `/api/status`, `/api/inject_link`, `/api/debug/set_pokeballs`, and
  `/api/debug/queue_command`; fixture tooling also uses `/api/reset` and
  `/api/attempts`. The final engine harness must exercise these paths.
- Retain `/stream/{slug}` and `/stream/{slug}/fragment`, including theme aliases,
  layout, speed, pause, and event filters. Keep `/stream` and `/stream/` gallery
  compatibility when Broadcast becomes the navigation destination.
- Preserve launcher TCP settings and existing downloaded launchers. New manager
  HTTP binding must not change TCP binding or allocation.
- Keep existing theme/font readers: `slink-theme` (localStorage and cookie),
  `slink-font`, `slink-sidebar-collapsed`, and `slink-stream-rail-collapsed`.
- Retire the split/combined control in Phase 5 without deleting arbitrary browser
  storage. `slink-lp-view` can become inert.
- Preserve encounter expansion using the current `slink-details-open:` convention
  through extraction. The board may reset it once with a run/player namespace;
  expansion and focus must never transfer to another selected run.
- Keep Calc's `slink_prep_trainer`, `slink_prep_encounter`, `slink_bridge_pos`, and
  `slink_bridge_collapsed` compatibility. Two Calc tabs bound to different runs
  must not apply each other's run-specific prep selection.
- localStorage is origin-scoped: retaining a key name does not migrate values
  from an old per-run port. Do not claim automatic cross-port migration. Theme
  cookies and existing manager preferences provide the currently available input.

### Assets to promote before removal

| Input in mockup checkout | Destination/handling |
|---|---|
| Four `server/static/mockups/fixtures/*.json` captures | Move under `tests/fixtures/ui/`, retarget tests/generators/docs, and regenerate after the integrated serializer changes. Keep their origin/hash evidence. |
| `a/index.html`, `a/mockup.css`, `a/mockup.js` | Port reviewed composition; preserve the original commit as the visual reference. Do not copy mockup capability shortcuts into runtime policy. |
| `a/fonts.css` Jersey 20 declarations + two `jersey-20-*.woff2` files | Promote into production font declarations before removing mockups. Retain both declared subsets. |
| IBM Plex Sans declarations + two `ibm-plex-sans-*.woff2` files | Promote for the distinct Broadcast typography; keep it scoped away from board Jersey typography. |
| Existing production fonts, vendor scripts, theme CSS | Preserve referenced assets; remove candidates only after a final reference scan. |
| `ui/track-b/`, built `mockups/b/`, mockup controls | Retire after the board ships and all test/generator/font consumers have moved. |

The existing fixture test constructs a module-scoped `SLinkServer(data_dir=None)`;
make its isolation explicit before using it as a guard. Status JSON alone cannot
hydrate the legacy renderer's extra state indexes, caches, and pending memorials.

The 700 px overlap is concrete: `mockup.css` assigns all `.mk-pair` children
`grid-row: 1`, while the narrow rule changes columns without resetting that row;
the bond also has an inline column assignment. The production port must reset
both placements and order A -> bond -> B, including nested foe content. Preserve
the desktop geometry and add player labels only where stacking removes ownership
by column. Keep unavailable explanations out of `.off-unavailable` opacity, and
implement Debug focus containment/restoration and accessible selected states.

## Overlay preset coverage map

The exact legacy sizes, layouts, and control values are in `baseline.json`. Some
size/layout arrays have different lengths: never pair them by array index. Define
and verify explicit preset size/layout mappings during Phase 7B.

| Legacy slugs | Shared preset responsibility | Content/controls that must survive |
|---|---|---|
| `party-a`, `party-b` | Player party | Ordered members, species/nickname, levels, HP/status; default, horizontal and thin layouts. |
| `links` | Linked pairs | Both halves, area, alive/dead membership; all four layouts. |
| `linked-party` | Active paired team | Both-in-party membership, both HP bars, bond/area; default and thin layouts. |
| `boxed-links` | Stored/split linked pairs | Authoritative membership; vertical variants, scroll speed and pause. |
| `enemy-focus-a`, `enemy-focus-b` | Active foes | Wild/trainer states, doubles, HP/status, stat stages, moves and live PP. |
| `enemy-trainer-a`, `enemy-trainer-b` | Full enemy trainer team | Full observed team distinct from active foes; hidden in wild battle; speed/pause. |
| `focus-a`, `focus-b` | Active player battle mon | Effective battle form/stats, HP/status, stat stages, four moves and PP. |
| `deaths` | Pair counters | Alive/dead counts from authoritative state, not party absence. |
| `attempts` | Attempt counter | Existing editable counter endpoint and display. |
| `stream-memorial` | Memorial feed | Both halves, death ordering/metadata and scrolling. |
| `badges-a`, `badges-b` | Player badges | Adapter-specific badge count/order and earned state, including 16-badge cases. |
| `areas` | Rule-area totals | Linked/dead-zone/pending counts and supported horizontal layout. |
| `events` | Event feed | Per-player event identity, event filters, and ordering. |
| `encounters` | Encounter summary | Encounter/shiny totals and last linked pair. |
| `ticker` | Event marquee | Same semantic events with independent speed and filters. |
| `enc-table-a`, `enc-table-b` | Player encounter guidance | Correct cartridge, physical map/floor/time/method, rates/levels; scrolling. |
| `area-encounter` | Current rule-area state | Linked pair, pending captures or dead zone; preserve distinction from physical encounter-table location. |
| `all` | Gallery-only overview | Preview real presets; no synthetic stream route. |

## Acceptance scenarios to prepare after the handoff

These are required assertions, not passed tests. The R/B and RR captures are
starting inputs only; they do not cover the entire table.

| ID | Scenario | Required observation |
|---|---|---|
| B01 | Populated RR and R/B captures | Stable A/bond/B ownership, matching pair counts, correct sprites/labels, ability/item presentation driven by data/capabilities. |
| B02 | Empty, never-connected, stopped and archived runs | No borrowed data; stopped summaries have no live Now/HP/battle or inferred party/box placement. |
| B03 | Disconnect, pause, missing age, and age crossing the stale threshold without a tick | Separate labels; age advances with no SSE subscribers; HTTP polling cannot make telemetry fresh. |
| B04 | Each player fights a different pair; both fight the same pair; doubles | Foes remain beneath their owner; partners are at stake; no invented attack-target pairing. |
| B05 | Pending capture, split pair, unlinked active mon, unlinked box mon | No duplicate membership; unlinked is not falsely pending; stable identities across zones. |
| B06 | Dead/memorial member absent from party; one-sided dead-zone catch | Preserve authoritative death and the caught half; never reinterpret absence as alive-boxed. |
| B07 | Unknown HP and exact 20%, 35%, 50% boundaries, including 34.6% | Unknown stays unknown; raw ratios determine color/risk and rounding is display-only. |
| B08 | Long names, safe literal markup characters, all three themes, 700/1100/1600 px | No overlapping rows or clipped essential labels; visible focus and readable unavailable-option reasons. |
| B09 | Open encounters/Debug, two polls, reconnect, reload, and selected-run change | Preserve appropriate expansion/focus; drawer traps/restores focus; no state inherited from another run. |
| C01 | Supported/requested/ready/effective/unknown combinations | Independent feature gates; requested setting survives paused/not-ready state; ghost/PC-NPC exclusivity comes from backend. |
| C02 | All nine ordered R/B/Y pairs, including Y/Y | Expected and admitted variant/hash/profile/codec/patch facts remain per player; no first-HELLO inference. |
| C03 | Pending/uncertain physical effect and retained journal receipt | No success/resume inferred from connected, queued, save_failed, or receipt retention alone. |
| C04 | Current RR battle observation differs from prep estimate | Observed moves/items/abilities/form/stats win; unknown differs from none; missing field inputs remain uncertain. |
| C05 | Calc percentage and KO examples | Percentage uses max HP; KO uses current HP; no Gen1 Battle Calc support inferred from UI availability. |
| C06 | Physical map/floor/time/method differs from grouped SoulLink area | Use correct per-player encounter table, valid rates, and no NONE entries or concatenated probability totals. |
| C07 | Newly decoded RR species lacks a canonical external name | Display verified ROM label or explicit unknown; never invent a species name. |
| S01 | Two named sources bound to different games, manager restart, stop/delete one run | Targets remain independent; unavailable source never follows another run or the legacy pin. |
| S02 | Retarget while an old fragment request is in flight; change layout/theme | Revision rejects old content; already-open OBS source updates its binding and shell. |
| S03 | Rules from two runs target one OBS endpoint; config update fails for one executor | Manager ordering is deterministic; stale revision/failure visible; no rule run guessed during import. |
| S04 | Board polling, several source polls, and Calc SSE concurrently | All refresh after first paint; URL prefix/query preserved; only dummy manager SSE removed. |
| R01 | Both clean sources, dirty B, missing Java/JAR, wrong file/player | Preflight occurs before either invocation; errors do not publish or mutate a binding. |
| R02 | All UI category selections and effective side effects | Preserve the full catalog/effective evidence, evolution families/targets, grants/statics, and serialization effects. |
| R03 | Official preparation versus imported ROM provenance | Record clean input/JAR/customnames/effective settings/seeds/output/profile/final scan; imported seed/settings remain unverified when appropriate. |
| R04 | Partial second-player failure, duplicate submit, publish failure, restart | No partial success or silent reroll; recoverable artifacts and consistent registry/contract; lifecycle locks respected. |
| R05 | Download both final files, swapped/modified file, rerandomize after binding | Actual TCP admission of final bytes; wrong files refused; immutable binding uses a fresh run. |

For C02, use the incoming owner's verified Yellow capabilities (currently described
as trade-only companion, without native panel/SFX), not the older mockup or legacy
documentation. This is an incoming acceptance requirement, not evidence that the
default runtime already supplies it.

### Evidence to attach to each phase

Record the tested commit, input hashes, selected generation/variant pair, actual
commands and exit status, missing prerequisites/skips, and screenshots with
viewport/theme/state labels. Screenshots prove appearance; in-process tests prove
their exercised contracts; actual admission/gameplay needs the appropriate live
harness. Keep these evidence categories separate.

Before Phase 4 removes the legacy generator, compare normalized DOM from the same
hydrated state and retain both old views. Before Phase 5 removes controls/assets,
retarget their tests and verify the approved board refinements. Before Phase 6/7
ships prefixes/sources, keep two polls and retarget races in the acceptance run.
Before Phase 8 completes, run the real JAR and actual downloaded-file admission.

## Outstanding work

The code/runtime gate remains closed. No production board, source CRUD, manager
proxy, OBS arbitration, randomizer UI, or Phase 1 dashboard guard has been
implemented by this prep packet. The packet reduces rediscovery and supplies
verifiable inputs for those phases when the handoff arrives.
