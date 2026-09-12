# Initial inventory enrollment

`gen1_run_config.create_runtime` creates an empty, owned run and its checked
held-service launchers. It rejects existing journals/configuration and legacy
rule files; exclusive journal creation closes the check/create race. It does not
populate game rules from a test-provided party or from legacy HELLO data.

An opted-in generated client waits for the existing verified overworld checkpoint,
owns the fixed-frame hold, admits metadata, then reads the full pinned save-source
geometry and CartRAM. The initial observation and detector baseline are published
atomically in the existing client journal. Context/frame changes during capture
or publication fail closed; replay uses the same event rather than generating a
new initial state. A replacement physical context cannot reuse the old baseline.

The server verifies the admitted cartridge/context/host/save identity and derives
the inventory from complete bytes. Parties may be empty before the starter. The
active box is read from WRAM; initialized inactive boxes come from their actual
SRAM slots. Uninitialized inactive storage is not mistaken for live inventory.
Duplicate physical keys across party and boxes are rejected. Box records remain
exact raw witnesses; no party stat tail is invented for them.

The initial record and admission binding remain immutable and are revalidated
when the state is restored, including by stopped-run readers. Identity contexts
are bound, but no Pokémon member, acquisition, link, encounter area, party-rule
cache or Pokéball credit is inferred from the inventory. An explicit persistent
blocker remains until gameplay/history and execution policy are qualified. This
is enrollment evidence, not import of an arbitrary in-progress game or permission
to release ordinary gameplay.

The current client display-name codec is mirrored for admission comparison, with
the exact raw name bytes retained in the source record. Its existing fallback
rendering for some glyphs is not promoted to a new raw identity definition.

The implementation reuses shared journals, state stores, admission, identity
registry, recovery barriers and launcher-file checks. RBY layout and inventory
interpretation remain in generation modules. No new generic framework or emulator
write path is introduced.

Initial live qualification used downloaded launchers on Y/Y,R/B,B/Y and actual
memory observations. Older held-only test saves had inconsistent party XP; the
new test prepares valid physical save fixtures before boot while keeping server
bootstrap empty. The test TCP listener now uses production's4MiB line limit.
Strict codec validation and production transport limits were not weakened.

The complete launcher regression passes6 cases in27.83s, including all three
enrollment pairings, existing held command delivery and bundle mismatch refusal.
Each enrolled client remains at the same frame with unchanged WRAM and SRAM.
Evidence: `.cache/initial-observation-launchers.xml`. Thirty targeted inventory,
factory, replay, persisted-state and atomic client-observer tests pass. The
full suite passes4833 tests with the same two Windows symlink skips in219.75s
(`.cache/initial-enrollment-full.xml`). Required bug-class Ruff checks pass and
258 project Lua files parse under explicit Lua5.4. Inventory now contains
4688unit/147integration/230live/45duo cases.335 requirements have25 current source
pins,109 stale and201 missing; this is integrity accounting, not release approval.

The [temporal inventory continuation](TEMPORAL_INVENTORY.md) adds an ordered,
atomic checkpoint stream and validated inventory differences. The held launcher
still fixes its initial frame. Temporal gameplay and rule execution are not
qualified by that evidence-only stream.

Remaining: connect temporal acquisition/faint/storage observations and their
physical executors, qualify paired reconciliation/ordinary stepping and controlled
recovery, then expose the completed lifecycle through normal Manager startup.
The optional Claude review connector failed twice before producing a review;
no independent peer verdict is claimed for this cut.
