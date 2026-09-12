# Source-qualified engine signals

The durable client now installs read-only engine hooks after initial inventory
acknowledgement. Their source sites, banked addresses and expected ROM bytes are
generated from the pinned Red, Blue and Yellow builds. Installation checks the
flat ROM anchors; each callback checks its loaded bank, PC, instruction bytes,
final ROM hash and owned context before retaining a complete party witness.

The hooks cover these specific sources:

| Signal | Source | Interpretation |
| --- | --- | --- |
| Battle faint | `RemoveFaintedPlayerMon` entry | The active battle HP is zero; identify the original party slot, including when Transform changed the battle species. This entry also covers simultaneous knockouts. |
| Poison faint | `ApplyOutOfBattlePoisonDamage.noBorrow` after the zero-HP branch | The identified party member has zero HP and is still poisoned, before the original status clear and faint message. |
| Starter call/return | The census-verified `AddPartyMon` call in Oak's Lab and its return | Match an empty-party call to the completed first-mon append, with the same source context, stack, species, map and expected level. |

The bounded buffer holds at most 32 signals and never evicts old evidence. Engine
callbacks read memory only; they do not write files, advance frames or send
network traffic. At an owned held frame boundary, `flush()` publishes the complete
batch and sequence baseline atomically through the existing client journal. A
callback error, overflow or uncertain storage publication fails closed. The
execution owner must persist each frame's signals before authorizing another
frame. This obligation is not fulfilled by merely installing the hooks.

The server checks the admitted source/hash/context, exact batch order, source
site, complete party codec and save identity. It retains starter calls across
batches and pairs each return with its call. Event, latest aggregate and audit
record commit together; exact retries do not create another transaction. Restore
recomputes the evidence, and the running service checks the matching journal
record and event receipt.

The [starter settlement continuation](STARTER_SETTLEMENT.md) now joins proved
starter records to stable inventories and commits logical acquisitions and rule
links. Engine signal records by themselves still create no identity member, capture,
link, physical command or ordinary execution permission. Battle-source evidence
also does not distinguish a natural knockout from an already-commanded faint;
the command/rule binding must do that. The existing initial-history blocker stays.

The starter return witness proves the append, not completion of the enclosing
script. Yellow writes its starter's catch-rate/held-item compatibility byte and
updates starter/follower state after the observed return. Settlement must join
this source transaction to the later stable inventory, preserve those cartridge
changes, and check all authoritative boxes for collisions. Other gifts, Game
Corner purchases, NPC exchanges, wild/static encounters and the Pokéball rule
gate still need their own signal predicates. The acquisition census remains
explicitly `runtime_ready=false`.

The generated held launcher installs the observer but still fixes its first
frame. Normal gameplay and reset/recovery are not enabled by this change. A
replacement context cannot reuse the original admission's signal stream, and
unflushed evidence lost with a process requires recovery rather than silent
continuation.

The 57 focused tests pass in 7.55s (`.cache/signals-final-targeted.xml`). They cover
all nine ordered pairs, source predicates, Transform identity, call/return across
batches, replay, corruption, buffer faults and atomic publication. The generated
source check requires the pinned local sources and legal ROMs; it is not silently
counted as portable CI coverage.

Nine live checks pass in 39.83s (`.cache/signals-live.xml`): three original-routine
cases, one per title, plus all six held launcher regressions including Y/Y and
mixed titles. A subsequent stronger three-title differential passes in 12.64s
(`.cache/signals-diff-live.xml`), comparing observer-on/off execution for battle
faint, poison faint and starter append, followed by original `HealParty`. All
nine scenarios preserve complete WRAM/SRAM and frame outcomes, and the faint
evidence survives healing.

These live tests use an explicitly cloned core, test-only CPU invocation, an
original starter CALL with a test stop after its return, and fixture ownership.
They qualify the source observer mechanism, not natural campaign coverage or
production frame/recovery authority. Next: stable inventory-to-identity/rule
settlement, further encounter/activation signals, then paired ordinary execution
and physical command closure.

The full unit/integration suite passes 4,956 tests with the same two Windows
symlink skips in 268.50s (`.cache/signals-full.xml`). Required Ruff checks pass,
all 261 project Lua files parse under Lua 5.4, and the generator reproduces its
artifacts through both direct-script and module invocation. This continuation
reuses shared journals and atomic records; it adds no new shared framework and
does not publish a separate generic helper cut.

The portable suite passes 4,522 selected tests with 436 declared environment
deferrals in 159.69s (`.cache/signals-portable.json`), with no failed or skipped
selected tests. The release inventory now includes the three new live nodes:
4,811 unit, 147 integration, 233 live and 45 duo cases. The 338 requirements have
28 current source pins, 109 stale and 201 missing. These counts remain evidence
accounting, not RC approval.
