# Pokéball activation and linked-death settlement

The engine observer now records successful ball deliveries into the bag. This
uses the original `AddItemToInventory_` return after it restores HL and the item
quantity, preserving the success carry flag. The complete return sequence is
pinned from each cartridge. BizHawk exposes H and L separately; the probe reads
those registers to identify the bag destination.

Purchases, gifts and PC withdrawals use this common routine. PC deposits,
failed/full-bag deliveries and non-ball items do not activate the rule. Bag
geometry is validated, including count, quantities and terminator. Duplicate
stacks are legal: the cartridge can split a quantity across stacks at 99.
Master, Ultra, Great and Poké Balls activate; Safari Balls are excluded.

Activation and faint signals share the same ordered engine journal. The first
proved delivery gives that player permanent Pokéball credit. An earlier faint
in the same batch stays suppressed, and pre-ball suppression preserves the
starter's party ownership. This binding observes delivery after instrumentation
starts; it does not invent earlier activation history from HELLO or an arbitrary
save. Initial-history and ordinary startup qualification remain separate work.

An active faint must identify a complete rule link whose logical members agree
with the identity registry. One atomic commit marks the pair dead, records the
cause/time/initiator, creates both memorial obligations and publishes one peer
`force_faint` command. Poison remains identified as poison. An already-dead
pair cannot produce another command when the partner's engine reports its faint.
Activation of both players also updates the existing run-over condition without
emitting unqualified UI commands.

The shared `linked_death_rules` operation owns staged rule bookkeeping. Gen1
owns source and logical-identity validation, command binding and receipt checks.
The new Gen1 path refuses Explode Mode until its physical receipt binding is
qualified; it does not silently substitute ordinary fainting.

The acknowledgement must name the original command and sequence and prove the
exact party HP change and active battle HP mirror. A valid ACK refreshes the
peer's observed party cache and clears only that command. Both memorial
obligations and the death recovery hold remain. No save, storage move or revival
is inferred. Bad receipts, reused labels on unrelated commands and SQL failures
cannot partially advance rules or physical completion.

Controlled live tests execute the original inventory routine on R/B/Y for bag
success, split stacks, PC destination, full bag and non-ball delivery. Observer-on
and observer-off runs have identical WRAM, SRAM and frame outcomes. The existing
prepared-command executor also persists intent before a real party/battle HP
write, verifies its readback and replays without another frame. These tests use
explicit CPU/register setup and fixture write authority; they are not a new
production execution grant.

The [held faint authority continuation](HELD_FAINT_AUTHORITY.md) now selects the
exact pending faint adapter in generated initial-observation launchers using a
single-use server permit and fixed-frame overworld proof. Ordinary frames and
other physical adapters remain unavailable.
Memorial execution, save/recovery, other acquisition predicates and ordinary
gameplay remain required for RC. Actor post-handler storage evidence must also
be reconciled; the entry signal itself is not a claim that storage completed.

The first focused rule/receipt run passed 34 cases; the final suite adds rollback,
command-origin and H/L-register tests. Fifteen live regressions pass in 80.47s
(`.cache/faint-live.xml`), including all three new cartridge cases, starter pairs,
engine signals and actual held launchers including Yellow/Yellow. The new kernel
lane alone passes three cases in 12.59s (`.cache/ball-live.xml`).

The broad run passes 5,040 tests with the same two Windows symlink skips in
393.43s (`.cache/faint-full.xml`). A later shared-cut check exposed a dependency
on the unpublished Gen1 `find_link` method. The helper now uses explicit
player-scoped matching and refuses ambiguity. Its final Gen1/observer focused
set passes 50 tests in 98.54s (`.cache/faint-final-targeted.xml`); required Ruff
and all 262 Lua 5.4 parses pass.

The corrected three-file shared cut is `6d85974f340f4688c1f9becac1cd1699b26b2b29`
on `codex/shared-linked-death-v1`, parent `085acbe`. Its exact isolated tree
passes 3,088 tests with 15 existing skips and 11 subtests in 34.89s, plus required
Ruff and 227 Lua 5.4 parses. The initially failing candidate was not published.
GitHub run 34241400677 is green for that exact commit.

The final portable suite passes 4,606 selected tests with 437 declared environment
deferrals in 282.19s (`.cache/faint-portable.json`), with no failed or skipped
selected tests. Collection contains 4,896 unit, 147 integration, 239 live and 45
duo cases. The 342 requirements have 32 current source pins, 109 stale and 201
missing. These counts remain evidence accounting, not release approval.
