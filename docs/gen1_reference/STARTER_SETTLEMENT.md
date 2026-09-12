# Stable starter settlement

The durable runtime now joins a proved starter source transaction to a later
complete inventory and commits actual rule and logical-identity updates. It no
longer stops at retaining those two observations separately.

Both players must have initial inventories containing no Pokémon and no starter
completion flag. A starter source is retained immutably even when later engine
batches arrive. Settlement requires the original current admission, a later
owned checkpoint, the cartridge's starter completion flag, and one matching
party member with all authoritative boxes empty. Unknown or ambiguous evidence
refuses settlement. Existing nonempty runs are not imported as fresh starts.

The birth and stable witnesses must agree on key, OT name and nickname. The birth
OT name must match the original save's raw trainer name. Stable HP, level and
stats are retained; the runtime does not write the earlier birth blob back into
the game. Yellow's original post-return `$a3` catch-rate compatibility byte is
required and preserved. The pinned original script and constants verify that
byte and the starter completion flag.

The first qualified starter creates one logical acquisition and pending rule
capture in `oaks_lab`. The second creates one rule link and one logical link.
The two sides may have identical physical keys, including Yellow/Yellow; keys
remain scoped to each player's save. Scripted-grant exemption comes from the
verified source transaction. Species, gender and type clauses do not turn that
validated grant pair into a rejection.

The generation binding uses the shared `record_exempt_party_grant` staged rule
operation. It avoids legacy gift heuristics, unnecessary retrieval commands and
automatic presentation commands. The settlement fills the current party cache
and stats from the stable bytes, changes no cartridge memory, and awards no
Pokéball credit. Rules, identities, source evidence and inventory observation
commit atomically with both empty outboxes. A failed commit leaves no partial
member or link, and exact replay does not create another acquisition.

Restore revalidates the immutable source and stable inventory, the derived
acquisition identity and the logical link origin. The running service also
checks the corresponding original engine and inventory journal events. Later
legitimate trade migrations may change current identities without erasing their
verified origin.

Before the second starter forms the pair, its peer's latest owned inventory is
checked again. A changed identity or missing peer refuses the whole transition;
valid newer peer stats refresh the resulting link and party cache. Immutable
settlement records continue to describe each acquisition's original witness.

This is a functional starter rule/identity binding. The initial-history and
execution blockers remain: it does not release ordinary frames, prove a full
campaign or select recovery/physical command adapters. Other acquisitions,
Pokéball activation and faint/command settlement still need their own bindings.
The next ordinary lifecycle should request stable inventories from relevant
signals rather than reading full SaveRAM every frame.

Unit coverage includes all nine ordered cartridge pairs in both arrival orders,
all optional clauses enabled, identical Yellow/Yellow keys, source replay,
current-level/HP preservation, nonempty-run refusal, malformed inventory and
SQL rollback during paired link formation.

The live integration executes the original starter CALL, `AddPartyMon` and the
post-return script through entry to `TextScriptEnd` in separate R/B, B/Y and Y/Y
emulator invocations. Actual source journals and complete before/after inventories
feed a production-created empty runtime and its normal dispatcher, producing
one paired link. Yellow's final byte and completion flag come from the engine.
Observer-on/off runs preserve complete WRAM, SRAM and frame results.

The live driver uses explicit cloned-core CPU invocation, a test stop before
returning to an unmodeled text caller, and fixture ownership metadata. This is
original-script-to-dispatcher proof, not simultaneous ordinary gameplay or new
TCP/frame authority qualification. Existing actual TCP launcher regressions also
pass; all twelve live cases are recorded in `.cache/starter-live.xml` (71.21s).

The broad suite passes 4,997 tests with the same two Windows symlink skips in
302.77s (`.cache/starter-full.xml`). A subsequent peer-inventory recheck passes
the final 43 focused cases in 47.97s (`.cache/starter-final-targeted.xml`) and all
three paired original-script cases in 28.12s (`.cache/starter-final-pairs.xml`).
Required Ruff and all 261 Lua 5.4 parse checks pass.

The shared three-file helper cut is published as
`085acbe0612bb770d2b1744f41dfbd0961e81cd1` on `codex/shared-party-grants-v1`,
parent `160412c`. Its exact isolated tree passes 3,084 tests with 15 existing skips
and 11 subtests in 37.65s, plus required Ruff and 227 Lua 5.4 parses. GitHub run
34235781319 is green. Gen1 source and inventory policy are outside that shared cut.

The final portable suite passes 4,564 selected tests with 437 declared environment
deferrals in 198.85s (`.cache/starter-portable.json`), with no failed or skipped
selected tests. Collection now contains 4,854 unit, 147 integration, 236 live and
45 duo cases. The 340 requirements have 30 current source pins, 109 stale and
201 missing; these counts are not a release verdict.
