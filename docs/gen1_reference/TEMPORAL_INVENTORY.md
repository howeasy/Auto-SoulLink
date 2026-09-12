# Temporal inventory checkpoint evidence

The owned initial observer can now publish subsequent held checkpoints through
the durable RBY runtime. The generated held-service launcher still fixes its
frame and does not start ordinary gameplay. A future execution binding must own
each later checkpoint before this observer can run there.

The shared `lua/observation_stream.lua` keeps one checkpoint in flight, waits for
the initial ACK, and publishes its event and baseline together. The exact ACK
advances the sequence and predecessor operation ID. A failed or uncertain store
publication cannot silently advance the detector. The binding verifies physical
ownership and checkpoint stability before and after publication. Callback
references are captured at construction, and callback values are detached.

The server accepts only the next sequence from the original admitted physical
context, at an increasing frame, with complete validated source bytes. It refuses
replacement contexts, mismatched hosts, malformed inventories and outstanding
physical command obligations. It commits the event, latest state and append-only
audit record in one SQLite transaction. Exact replay returns the previous result.
State restoration recomputes the latest difference; the running service also
checks its matching audit record and event receipt. The latest aggregate retains
two checkpoints per player; older checkpoints remain in journal audit history.

`server/keyed_inventory.py` is a reusable bounded comparison of unique keyed
records. It returns additions, removals and matched before/after rows in stable
order. Generation adapters must first validate completeness, physical context and
record encoding. This helper does not infer logical identity from a key or guess
that an addition/removal is an evolution or trade.

The RBY adapter uses the existing full-source inventory decoder. It reads the
active box from WRAM and initialized inactive boxes from both SRAM banks, refuses
duplicate keys and lost storage initialization, and compares keys across party
slot changes. It records movements, changed bytes and party HP falling from
positive to zero. Boxed records stay raw; no party stat tail is manufactured.

These differences are evidence. They do not establish acquisition causes, link
history, a natural faint versus a commanded effect, or a successful storage
command. Existing nonempty rosters remain unqualified; the initial-history blocker
is retained. No new rule events, identity members, links or physical commands are
created by checkpoint enrollment.

The [engine signal continuation](ENGINE_SIGNALS.md) now supplies read-only,
source-qualified battle/poison faint hooks and paired starter-call evidence.
It is wired into the held client and server journal; it does not settle rules.

The next required work is the remaining bounded signal observer and source predicates for
acquisition/battle transitions, their rule and identity binding, command receipt
closure, and paired ordinary execution/recovery. Full save-source checkpoints
are not intended as a per-frame battle observer: a Pokémon can faint and be
healed during blackout between overworld checkpoints. That transition needs
continuous bounded battle evidence, not inference from these endpoints.

The broad run passed 4,896 tests with the same two Windows symlink skips in
250.81s (`.cache/temporal-full.xml`). A later shared callback guard also refuses
journal-baseline changes during sampling. The final focused set passes 95 tests
in 23.26s (`.cache/temporal-final-targeted.xml`); the final six live launcher
regressions pass in 30.77s (`.cache/temporal-final-live.xml`). Required Ruff checks
pass and all 259 Lua files parse under explicit Lua 5.4. Targeted tests include
all nine ordered RBY pairs, simulated Lua-to-server decoding on each title,
cross-slot fainting, box movement/switching, replay, context/sequence refusal and
atomic publication failure. Live launcher regression verifies that the existing
held launch behavior remains held; it is not live temporal gameplay proof.

The five-file reusable cut is published as
`160412c9221885aeef18dbb560ceb7b6d9d762e6` on
`codex/shared-observation-checkpoints-v1`, parent `77c7562`. Its exact isolated
tree passes 3,076 tests with 15 existing skips and 11 subtests in 40.74s, plus
227 Lua 5.4 parses and required Ruff. GitHub run 34222370021 is green. No RBY
runtime policy is included in that cut.

Collection contains 4,753 unit, 147 integration, 230 live and 45 duo nodes.
The 336 requirements have 26 current source pins, 109 stale and 201 missing.
Two source-only address-guard nodes introduced by the earlier native/full-save
gates were missing portable classifications; both now join the existing portable
address-guard group. These counts are evidence accounting, not release approval.
The final portable run passes 4,465 selected tests with 435 declared environment
deferrals in 129.94s (`.cache/temporal-portable.json`). It has no failed or skipped
selected tests and is separate from full release qualification.
