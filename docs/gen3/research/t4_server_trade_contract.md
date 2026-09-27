# T4 server contract for durable Gen 3 trade

Agreed with Emerald-2 on 2026-09-27; implementation base `cd5c1697` (integration).
T4-R2 review corrections below supersede R1 validation and persistence details.
The combined Gen 3 orchestrator assigned T4 to `claude/gen3-t4-server` in
`C:/slink-wt/g3-t4`. That assignment supersedes the older design's Emerald-lane server lease.

Authority: [patched trade design](patched_trade_design.md) §§3–5 and
[per-title bindings](patched_trade_bindings.md). This is SOURCE/MODEL work. Gen 3 apply is
unreachable in the current production binding: `lua/gen3/native.lua:135` returns literal
false from `trade_capable`. Every target's `SLINK_TARGET_READY` remains zero. Neither this
server change nor passing MODEL tests qualifies a producer or a physical durable trade.

## Existing lifecycle retained

The line citations in this section refer to the **base `cd5c1697`**, so the original behavior
can be checked with `git show cd5c1697:<path>` after implementation shifts the lines.

| Step | Existing behavior / Gen 3 mapping |
|---|---|
| Offer, choose, confirm, prepare | `server/state.py:816-1038` sequences menus; both clients must declare `trade_prepare` to take the paired prepare round. Gen 3 declares it from `trade:capable()` (`lua/gen3/client.lua:1032`), which remains false with READY=0. |
| Apply | `_execute_trade` sends each side the incoming blob, outgoing key, slot and token, then persists applying (`server/state.py:1059-1095`). No link half changes at dispatch. |
| Result | Gen 3 checks commit, scene/evolution, post-save and final-result milestones plus final identity (`lua/gen3/trade.lua:82-205`; producer `patch/src/trade_targets/abi.h:81-98,200-210`). Before possible commit it reports unchanged; afterward a failure is uncertain. No raw-swap success. |
| Paired settlement | `_handle_trade_done` rejects stale tokens; `_settle_trade` commits only both traded, rolls back both unchanged, and exposes conflicts (`server/state.py:1097-1220`). Either side still `None`/`await` prevents settlement, including when both sides are `hello_only`. |
| Reset evidence | `after_reset:true` sets `hello_only`; ticks cannot settle that side (`server/state.py:1118-1130,1147-1158`). This gate is necessary, but the server cannot establish the client's reload provenance. |
| Persistence and admin | `_trade_to_json` / `_restore_trade` preserve applying/uncertain/conflict; applying restores as uncertain (`server/state.py:1235-1265`). `resolve_trade` respects known verdicts and drops undelivered APPLY before resolving (`:1291-1336`). |

Gen 3 keeps `native_trade_ui=False`: its menus are server-sequenced. The full Gen 1/2 native
query/offer/eligible-mask protocol remains unchanged.

## A. Admin resolution does not authorize unsaved RAM

At the base cut, admin `resolve_trade` queued no terminal client command. T4-R3 now adds
a bookkeeping-only `trade_final` receipt; it does not clear a reload/hidden barrier. There **is** a server-driven lease
command, `withdraw_trade`, in the applying watchdog (`server/state.py:715-720` at the base;
Gen 1 `lua/gen1/client.lua:2128-2135`, Gen 2 `lua/gen2/client.lua:799-807`). Admin resolution
deliberately does not reuse it. Withdrawal can cancel an unpicked APPLY; it cannot make an
already committed but unsaved party durable.

Gen 1 and Gen 2 have no `trade_cleared`/forget equivalent from the server. Native result 2
holds their lease until reset (`lua/gen1/client.lua:2160-2167`, `lua/gen2/client.lua:848-854`).
Their local `trade_forget` runs at a reset/visit boundary and declares post-commit uncertainty.
T4 adds **no clear/forget command**.

An admin can resolve an `await` + `hello_only` side as traded, committing the server link while
the client still holds a possibly unsaved lease. That remains an explicit human decision,
not a durability witness. T4 keeps the server's snapshot barrier until a later visible hello;
the client must independently keep its local barrier until a qualified reload and ordered
uncertainty declaration. Resolution never lifts either barrier by itself.

Emerald-2 confirmed that local report retirement can complete even after the server resolved
the token: the existing client allows reload evidence after sending the owed uncertainty,
without consulting the server's pending-trade slot. This is transport ordering, not a save
acknowledgement (`lua/gen3/client.lua:1451-1466`, `lua/owed_reports.lua:31-48` at the base).

## B. A withheld party is not an empty party

The demonstrated defect was **hello**: the client sends an empty party while frozen or
trade-hidden (`lua/gen3/client.lua:999,1031` at the base); state rebuilds keys/size/blobs as empty
(`server/state.py:1737-1760`) and presentation follows (`server/server.py:2263-2265`). This
causes a hard trade outage: `_eligible_trade_pairs` requires both cached blobs and an empty
cache leads to mask 0 / "No linked pair in your party to trade". It is not just a display bug.
Current hidden ticks already omit party/census, and safe is snapshot-free; those are not
additional existing empty-snapshot defects.

Agreed marker: **`party_hidden: true`**. It means no authoritative party or box snapshot,
including both a borrowed party (`st.frozen`) and a trade durability barrier. Retain the last
trusted keys, size, blobs, slots, census counts and presentation cache. Do not reconcile
missing mons, infer faints, ingest attached boxes or treat a retained box census as fresh.
Hidden hello still performs admission and explicit trainer identity checks. A fresh server
has no full trusted snapshot to retain and must not invent one from a pending trade.

The consumer also rejects authority from accidentally attached snapshot fields on a marked
tick/safe, as agreed with Emerald-2. An unmarked snapshot-free safe/tick leaves the hidden
state latched. For a borrowed-party episode a later visible snapshot can restore freshness;
for declared trade recovery only a later visible **hello** can do so. Preserved caches never
make a new trade eligible while either side is hidden. This intentionally retains the outage
until trustworthy data returns, while avoiding destruction of the last good view.

## C. Outstanding leases precede reconnect evidence

Agreed hello field:

```json
{"trade_outstanding": [{"token": "t7", "epoch": 17}]}
```

Omit when empty. Each token is a nonempty string and each epoch is an integral JSON number
in `1..4294967295`. T4-R2 accepts integral floats, including `1.0` and `4294967295.0`, and
normalizes them to Python integers. Booleans, fractions, non-finite numbers, zero, negatives,
strings and overflow leave the slot connected but **hidden and unrecovered**, with a board
warning; they do not create an identity rejection. Wrong-save/missing-explicit-identity and
unsupported-foundation refusals remain separate. The server treats epoch as an **opaque lease identity**:
it records equality for duplicate declarations and performs no numeric ordering inference.

After admission and save-identity acceptance, a matching applied token becomes uncertain
with `hello_only` before snapshots are considered. Every declaration-bearing hello, including
repeats and declarations for already resolved tokens, withholds its snapshots. A stale token
cannot change another pending trade's verdict or epoch bookkeeping. The matching side's
undelivered APPLY is discarded; the journal never creates a traded/unchanged verdict.
Per-side `recovery_epochs` remains in the pending-trade record for duplicate bookkeeping.
T4-R2 also persists independent `trade_recovery` rows (`pending`, `hidden`, `problem`) in
`links.json`, so barriers survive admin resolution and declarations for older tokens. Hidden
borrowed snapshots persist too. Gen 1/2 do not gain this field. A corrupt recovery row stays
hidden; an accepted visible hello clears and persists recovery state. Known verdicts/conflicts
are retained. A later visible hello supplies evidence through the existing paired classifier.
A concrete terminal `trade_done`, whether traded or unchanged, cannot bypass a hidden, pending
recovery, or hello-only barrier: the opted-in Gen 3 side stays `await` until that hello.

A refused Gen 3 hello must not tick the trade watchdog or drain earlier queued APPLY commands.
Identity and recovery validation precede both. Base/Gen 1/Gen 2 retain their existing ordering.

### Client prerequisites at the T4 base

At the T4 base, `trade_epoch` was a per-VM connection counter, starting at zero and incremented on
hello (`lua/gen3/client.lua:82,990-995` at the base); `uncertain_records`, `owed`, and `retired`
were only Lua tables (`lua/gen3/trade.lua:23`). They did **not** satisfy this contract.
Emerald-2 agreed to the following counterpart requirements; this card makes no client edits:

- Allocate a durable monotonic nonzero u32 lease epoch, retaining the originating value across
  reconnect and VM restart. `lua/gen3/run.lua:126-185` (`next_session_counter`) is the local
  allocator precedent; native `session_epoch` is a separate domain unless explicitly bound.
  Never wrap, reset to 1, or silently substitute the current connection counter.
- Persist the cartridge/player/run-bound lease **before** the first scene-publication attempt
  that might commit. Writing only after `declare_uncertain` leaves a crash-during-commit gap.
  Missing, corrupt, ambiguous or exhausted required storage must fail closed.
- Emit the hidden marker at the appropriate hello/tick/safe seam and the outstanding list on
  hello before any RAM publication; omit outstanding only after recovery is qualified.
- Prove that durable save data was reloaded before releasing the barrier. Current reset/OT-loss
  and frame-rollback callbacks only mark `reload_seen`; neither an arbitrary savestate load
  nor a falling frame counter proves a battery reload. Emerald-2 reproduced an unsaved received
  identity being published after changing only the model frame counter. Its receipt is
  `C:/slink-wt/em-t3/.cache/t4_contract_frame_rollback_model.json` (peer MODEL evidence).

The server cannot infer these facts from a journal or visible hello. The combined feature
must stay disabled until the paired client and producer prerequisites qualify.

## Implementation and verification map

`GameRulesAdapter.supports_trade_recovery()` defaults false. `Gen3Adapter` opts in for the
known FR/LG/Emerald/RR bindings, including the AP spellings for server protocol handling only;
this enables neither client admission nor native capability. An expansion/unbound Gen 3
adapter refuses the extension by name instead of silently ignoring it.
`SoulLinkState.party_snapshot_withheld`, `_declare_trade_outstanding`, `_handle_hello`, and
the presentation/census guards implement B/C. Settlement and admin outcome rules stay intact.

`tests/unit/test_gen3_trade_server.py` exercises protocol dispatch and persistence:

| Requirement | Control |
|---|---|
| B: retain party/display; attached hidden data is unavailable | `test_hidden_snapshot_preserves_last_good_party_and_display`, `test_hidden_borrowed_party_is_not_a_faint_and_snapshot_free_safe_keeps_it_hidden` |
| B: stale cache never authorizes a new trade | `test_preserved_cache_cannot_authorize_a_second_trade_while_hidden` |
| C: declaration before evidence, duplicate, stale token, restart | `test_outstanding_hello_declares_before_any_party_evidence`, `test_stale_token_cannot_declare_the_new_pending_trade_uncertain`, `test_outstanding_journal_survives_server_restart_without_inventing_a_snapshot` |
| C: malformed report withholds snapshots; wrong-save hello is refused; neither dispatches APPLY | `test_invalid_epoch_holds_snapshot_without_refusing_identity`, `test_malformed_journal_is_not_an_empty_recovery`, `test_refused_recovery_hello_cannot_tick_or_modify_the_pending_trade` |
| C: queued APPLY cannot replay into recovery | `test_recovery_does_not_deliver_an_apply_that_was_still_queued` |
| A / paired settlement | `test_admin_resolution_does_not_release_hidden_ram_or_send_forget`, `test_both_hello_only_sides_need_separate_visible_hellos` |
| Gen 1/2 unchanged | `test_gen1_gen2_trade_bytes_ignore_the_gen3_recovery_extension` plus existing trade/hello suites |

Red-first observations: three hidden-snapshot failures; declaration-bearing hello classified
its attached RAM as traded; three rejected-hello watchdog failures; malformed recovery drained
a queued APPLY; valid recovery also drained that APPLY. Each passed after its corresponding fix.

A separate replay loaded **both original server/state modules from `git show cd5c1697` in
memory**, then compared the same `_legacy_trace` against T4 with a fixed clock. Protocol replies
plus persisted `links.json` were byte-identical for all five titles:

| Title | Bytes | SHA-256 |
|---|---:|---|
| Red | 4143 | `de705d998450c32d8ed98ed9237d062785845ea8fb469f41e85a52a01064e9c1` |
| Blue | 4144 | `726963ba57293349dbd8d13833c7ea085a0c0b36e90335494f1136012bd057f5` |
| Crystal | 4747 | `1e6fe480932824916a725aeffabb17bd723560550d0065ddd134b1601ad9297e` |
| Gold | 4744 | `c7ee09e9303daee0ba4015a6aeaa12307fd9411c835a3cce15c7bac7f43b6d27` |
| Silver | 4746 | `722e813ce49f2b2bcce35ae9baaf7d29e22feaefb07c454f9edef2690c905e02` |

Targeted trade, Gen 1/2, Gen 3 client, hello and citation regressions: **233 passed in 25.92s**.

## R1 completion receipt — 2026-09-27

Implementation: `2a8f1f0501abe21cd00c62b428c1b22687effb01`, based on `cd5c1697`.
The source stayed unchanged during the full run. The follow-up receipt also repairs one
watchdog sentence in `docs/protocol.md`; shifted source citations passed the targeted checker.

```text
python -m pytest tests/unit -q -p no:randomly -n 4 --dist=loadfile
15428 passed, 362 skipped in 993.61s (0:16:33)
Exit code: 0
```

The full run used Python 3.12, pytest-xdist 3.8.0 (four workers), the pinned local ROMs and
these local prerequisite bindings:

```text
SLINK_PRET_SRC=E:/Google Drive/SLink/.cache/pret/pokered
SLINK_PRET_FIRERED_SRC=E:/Google Drive/SLink/.cache/pret/pokefirered
SLINK_PURERGB_SRC=E:/Google Drive/SLink/.cache/purergb
SLINK_RGBDS_BIN=E:/Google Drive/SLink/.cache/build-tools/rgbds-v1.0.3/bin
SLINK_GEN3_RAND_ROMS=C:/slink-wt/rand_roms
SLINK_UPR_JAR=E:/Google Drive/SLink/.cache/slink-upr/PokeRandoZX.jar
PYTHONPATH=C:/slink-wt/g3-rfix/.cache/rf1-test-deps
```

Ignored ROM/build/fixture prerequisites were copied into this worktree and SHA-256 compared
to the originals. Clean FR SHA-1: `41cb23d8dccc8ebd7c649cd8fbb58eeace6e2fdc`; clean LG:
`574fa542ffebb14be69902d1d36f1ec0a4afd71e`. No ROM, client or producer changes were committed.
Full output is retained locally at `.cache/t4-full-unit.txt`. The 362 skips are reported as
skips, not qualification. No emulator ran for this card. Gen 2's prior physical receipts remain
stale after shared-server changes; the compatibility replay does not renew those receipts.

## T4-R2 adversarial-review corrections

All fixes are additive commits after R1 (`2a8f1f05`, `58c4fe29`), not amendments.

| Finding | Decision / control |
|---|---|
| Concrete terminal report bypassed recovery | `test_barred_terminal_report_waits_for_visible_hello`: journal, hidden-only and hello-only barriers, each for traded and unchanged reports; all six failed before the fix. The guard uses `supports_trade_recovery()` so the accepted Gen 1/2 report path stays byte-identical. |
| Barrier vanished after admin resolution or an older token | `test_hidden_barrier_survives_restart_without_a_matching_pending_trade`: all three red cases (admin resolution, old token, borrowed party) now retain the independent persisted barrier and clear it durably on a later visible hello. |
| Malformed optional field rejected the slot | `test_malformed_recovery_stays_connected_hidden_and_visible_on_board`, invalid-epoch and malformed-journal controls: keep the identity accepted, withhold snapshots/APPLY, journal uncertainty, persist the warning, and render a party-withheld banner. |
| Lua numeric encoding | `test_integral_float_epoch_is_accepted_and_persisted_as_an_integer`: accept integral in-range JSON floats; booleans and non-integral/non-finite numbers remain unusable recovery information. |
| Hidden hello reissued memorial writes | `test_hidden_hello_does_not_requeue_memorial_writes`: requeue only after visibility returns. |
| Abandonment left queued APPLY | `test_abandoned_prepare_drops_queued_apply_commands_for_its_token`: the opted-in watchdog purges both apply opcodes for its token; unrelated commands remain. Gen 1/2 cleanup behavior is unchanged. |
| AP/expansion silently ignored the extension | AP spellings consume it; expansion refuses it by name. Controls: `test_ap_adapter_consumes_recovery_extension`, `test_expansion_adapter_refuses_unsupported_recovery_extension_by_name`. No admission/READY changes. |
| Misleading partner-facing message | `test_partner_confirm_names_the_withheld_party` and the new-trade eligibility control now say party withheld, rather than claiming the mon vanished. |
| Legacy rejected-hello compatibility | The five-title byte replay now runs both ordinary and wrong-save/rejected-hello sequences. |

The optional server debug-clear endpoint was not added: a later valid visible hello remains
the recovery-release path. Admin resolution never sends a client-forget command. The durable
client journal and qualified reload prerequisites remain OPEN; all READY gates are unchanged.

R2 targeted run: **197 passed in 6.78s** (trade, shared state, Gen 1/2, Gen 3 client, hello,
and board controls); separate final citation checks pass. The new T4 file contains 61 controls.
The extended replay loaded the original `cd5c1697` modules and matched T4-R2 byte-for-byte
for all ten title/sequence combinations. Normal-sequence hashes remain in the R1 table above;
wrong-save/rejected-hello sequence receipts are:

| Title | Bytes | SHA-256 |
|---|---:|---|
| Red | 4458 | `a5af105e3403c80f6c6461398d635965e72dd2b0ac45f44a2163d3b05468be22` |
| Blue | 4459 | `35f942d9b96ad61236e6a954dc4f7e1b4c1e0d980dacb3783efb51881bb7ae9b` |
| Crystal | 5062 | `3704688e02e1a36f12e815f2a0f471fd3ce1f8e22ee54a536576e6b45a2ff7cd` |
| Gold | 5059 | `401051be4090e7f99122869cb0253d0aadfd29d206c16ac083f63eaf053e2b2d` |
| Silver | 5061 | `d46e948859ead03b7b1c34b725f68a3769402f10601fa303e201c1687a3d9c91` |

R2 implementation: `f78c1b064c7f0118b33e8b9f9d2c69c9bb202af8`.
Macro-import follow-up: `ca98393e742785813a037c7ef18a7ac3f0eca9f5`.


R2 first full run at `f78c1b06`: **3 failed, 15449 passed, 362 skipped in 902.40s**.
All three failures were existing accessibility tests importing `_board.html` macros without
`status`. The new banner called `status.players.items()` during that import. A separate
follow-up guards the banner with `status is defined and status.players is defined`; no test
was weakened. Accessibility + existing trade banners + T4 controls: **90 passed in 3.90s**.
The required full rerun is recorded separately; the failing output remains in
`.cache/t4-r2-full-unit.txt`.


## R2 final completion receipt — 2026-09-27

The full rerun used the same prerequisite bindings as the R1 receipt above and the source at
`ca98393e`. Neither the original R1 implementation nor its receipt was amended.

```text
python -m pytest tests/unit -q -p no:randomly -n 4 --dist=loadfile
15452 passed, 362 skipped in 891.96s (0:14:51)
Exit code: 0
```

Full output: `.cache/t4-r2-final-full-unit.txt`.
SHA-256: `0faa7ecafa8aa37d39f247676b73923eb265568817cd70fd8a9e6fe442ee1645`.
The first failed full-run output is retained separately. Final targeted controls: 61 in the
T4 test file; 197 trade/state/client/board tests; 90 accessibility/banner/T4 tests after the
macro-import fix. Final source-citation and whitespace checks pass. No client/producer or READY
change was made, and no physical trade qualification is claimed.


## T4-R3: finalized-token bookkeeping

Added on the coordinator's 2026-09-27 instruction after T4-R2; Emerald-2 consumes this shape.

- TCP `config` adds `run_id` only for `supports_trade_recovery()` adapters, passing through
  the server's existing `_run_id`. An unmanaged server sends an empty string; it does not
  invent a shared or random identity. The client must require a nonempty ID before binding
  a durable journal. This is the existing run label, not a new reset/rollback nonce.
- `trade_final {token, epoch?, verdict}` is one-way bookkeeping, not a native write command.
  Natural paired settlement uses `committed` / `rolled_back`; a direct split uses `split`;
  explicit admin resolution uses `resolved` regardless of its selected link outcome.
- Each side retains its newest **256** final tokens and verdicts in `links.json.trade_finals`.
  The terminal record is added before the settlement save. Receipts are queued only after
  a successful save, never on an unpersisted final. Unknown/evicted/malformed records do not
  become final merely because the client asks about them.
- A recovery hello listing a known-final token receives that side's receipt with its validated,
  normalized epoch echoed. The run's `config` precedes final receipts. Repeated declarations
  coalesce duplicate receipts. Wrong-save hellos do not receive queued or replayed finals.
- Neither remembering nor sending a final changes `party_hidden`, `trade_recovery_pending`,
  `hello_only`, or a pending trade's verdict. An old final receipt cannot settle a new trade.
  The client may retire the journal's bookkeeping entry, but must retain any separately
  required durable reload barrier until independently qualified recovery.
- Gen 1/2 emit no `run_id` extension or `trade_final`, persist no final ledger, and retain
  identical command/state bytes. All ten normal/rejected-hello replays still match the original
  `cd5c1697` modules and the hashes in the R1/R2 tables above.

R3 controls in `test_gen3_trade_server.py`: configuration opt-in and unmanaged identity;
committed/rolled-back/admin/direct-split receipts; epoch-preserving restart replay without
barrier release; per-side retention/eviction; save failure suppressing premature receipts;
wrong-save and old-token isolation; and one-way command/schema validation. The protocol
schema exposes the new config field and command and the already-agreed recovery hello fields.
Client/native/READY files remain unchanged. Full verification follows in the R3 receipt.

R3 targeted verification: **269 passed in 6.24s** across trade/state/client, wire schema,
hello, board and accessibility tests. Final source citations and whitespace checks pass;
the full suite will be recorded against the committed R3 cut.


## R3 completion receipt — 2026-09-27

Implementation: `2cf0c3b276cbf71015914c237cfb175f34de28b4`. The full run used the same
pinned local prerequisite bindings as R1/R2, with source unchanged throughout:

```text
python -m pytest tests/unit -q -p no:randomly -n 4 --dist=loadfile
15469 passed, 362 skipped in 911.62s (0:15:11)
Exit code: 0
```

Full output: `.cache/t4-r3-full-unit.txt`; SHA-256
`28e618abce4232923f75e8614d98b6c3adf691f8b80c30900415f556558677f3`.
The T4 test file now has 78 controls; the combined targeted suite passed 269 tests.
Both normal and rejected-hello traces remain byte-identical to `cd5c1697` for all five GB
titles; managed-run config controls separately verify omission of `run_id` for Gen 1/2.
No client/producer/READY change or physical qualification is part of this card.


## T3-R5 client counterpart — SOURCE / MODEL

`lua/gen3/trade_journal.lua` now owns the persistent intent and independent local reload barrier.
`trade.lua` allocates a durable originating u32 epoch and commits the bound intent before it can
queue a scene. Dispatch rechecks that intent. The older connection counter remains only a
readiness/dispatch fence; it is not exported as the persisted originating epoch.

The journal is bound to exact cartridge SHA1, player, server `config.run_id`, and trainer OT.
The client never manufactures a run identity. A missing/empty run ID cannot authorize durable
trade. On a connection that previously received a run identity, pending reports, terminal
receipts and fresh trade eligibility wait for the new connection's config; an unresolved record is not rebound to a
new run. A first hidden hello can request config without publishing RAM. The next hello carries
matching `trade_outstanding` entries before any recovery evidence.

Storage uses an append-only sequence of canonical, length/checksum-framed snapshots, plus a
separate guard seal. An OS-exclusive guard handle serializes writers; the log and guard are each
flushed with `FileStream.Flush(true)` before an allocation or intent returns. A missing member,
partial append, bad frame, invalid/duplicate record, mismatched rollback, or mismatched seal is a
named failure, never an empty recovered journal. Initial provisioning is allowed only when a
new guard is created and no log exists; the guard is permanent. Removing all journal artifacts
is an operator reset outside automatic recovery. The counter never wraps past 0xFFFFFFFF.
Intent creation rechecks conflicting cartridge/player leases inside that storage lock, so two
already-prepared processes cannot authorize separate runs using stale readiness state.

The NLua/.NET adapter in `run.lua` fails closed if its required host APIs are unavailable. The
real adapter has been exercised in a fresh host process and a second process, including the
configured battery-path builder. This is host MODEL evidence, not an emulator trade receipt.

### Qualified reload criterion

A falling frame counter, arbitrary savestate load, reset callback, TCP reply, and `trade_final`
are insufficient. After at least two observed frames with cleared save-block pointers and an
empty party, the client requires a stable, live overworld readback that matches the on-disk
battery selected by EmuHawk's own `PathEntryExtensions.SaveRamAbsolutePath`:

1. Two identical battery reads, with an exact 0x20000 body and optional 16-byte RTC suffix.
2. A complete checksummed 14-section save slot with unique section IDs and one counter; no
   partially corrupt slot is accepted. Slot selection handles the 0xFFFFFFFF-to-zero wrap and
   refuses conflicting equal-counter save blocks.
3. Stable live save-block pointers, save counter, trainer OT, party count, and every active
   party-record byte, matching that selected save. The cartridge hash is bound into the proof.
4. An ordered uncertainty declaration on the accepted connection, followed by a later visible
   hello. Qualified bytes alone do not lift the barrier before the declaration is sent.

The counter/layout bindings are separately pinned for FireRed, LeafGreen and Emerald and
checked against their committed symbols. **RR remains unqualified for this reload reader**;
FR's counter/layout is never borrowed. A future RR binding needs its own source/ROM proof.

The verifier reads the existing battery file; it does not call `client.saveram()` to manufacture
its proof. Movies are refused by the battery-path adapter. The published path is derived using
the loaded cartridge name, system, and the emulator's configured Save RAM location.

Both a journal hold and a borrowed/frozen party emit `party_hidden:true`; the common marker is
intentional. Borrowed-only episodes have no `trade_outstanding` record. Hello/tick suppress party
and census evidence, and the Gen 3 transport marks snapshot-free `safe` messages. Unrecovered
party RAM cannot generate faint/capture/PC evidence or authorize ordinary party writes.

`trade_final` is bookkeeping only. Its run-bound token and optional epoch must match; repeats
are idempotent. A final received before reload remains a durable tombstone with its local
barrier intact. The entry is retired only when both the server's final and local durability
conditions hold. Restart re-establishes uncertainty for an unretired entry.

All production `trade_capable()`/READY holds remain in force. No ROM producer or native ABI was
changed, and this work provides no physical durable-trade or power-loss qualification.

Primary host API sources used for the adapter:

- [Pinned BizHawk path builder](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Client.Common/config/PathEntryCollectionExtensions.cs)
- [NLua CLR bridge](https://github.com/NLua/NLua)
- [BizHawk Lua API](https://tasvideos.org/Bizhawk/LuaFunctions): `client.saveram` flushes save RAM;
  it is not evidence that a battery reload occurred.

### T3-R5 verification receipt — 2026-09-27

Source cut: `37c925dffb3e855372b3965ded1e2b6c3bb223c9` on `codex/t3-r5`, worktree `C:/slink-wt/em-t3`.
It includes implementation `bc88810f552551e0a99a2f792d120e0064993036`, T4 base merge
`10b7507132e9a97961ca941c1467aab804aa714b`, and T4-R3 merge
`7f487ec8acbf6d045e56d418c7cd5dcc6207d214` (counterpart `2cf0c3b276cbf71015914c237cfb175f34de28b4`).
Integration starting point was `76fd930a524c532a1831747d260964bb14043c51`.

Focused final run: **121 passed, zero failures/errors/skips**. It covers the journal, native
FSM, production-client/real-server recovery wire, real NLua host adapter, and protocol citations.
Full `tests/unit` run on the source cut: **11,725 passed, 4,261 skipped, zero failures/errors**,
exit 0, 535.69 seconds. Skips remain skips; this is no release or physical qualification.
The journal, recovery wire, bootstrap and FSM controls executed without skips.

The new controls caught two additional failures before the final source cut: accepting a
terminal receipt before reconnecting to the correct run, and stale prepared processes arming
different runs for the same cartridge/player. Both controls pass after their fixes. An older
boot observation also cannot qualify a later intent; a new boot episode must reach the verifier.

Raw receipts are under `.cache/` in that worktree; SHA256 pins:

| Receipt | Result | SHA256 |
| --- | --- | --- |
| `.cache/t3-r5-trade-red.xml` | 0 passed / 4 failed | `5678f54a0c8a53e590dcb2eb5874f670fc89e8269fbd2b072e2e8dd4f1ac118f` |
| `.cache/t3-r5-trade-first.xml` | 30 passed / 0 failed | `737a3983b021b64ea1195d592c7ac701b141a945bccf309cf92ec7828e8c1f7c` |
| `.cache/t3-r5-observation-red.xml` | 0 passed / 1 failed | `c1e82ae3cf4abf0b0e04566187e639ee2e815625d0904b42be42c1b1116aa3c0` |
| `.cache/t3-r5-observation-green.xml` | 38 passed / 0 failed | `070e61462b4f541d800d2935999d2dd76635c7d03e84d9e6d56cb8a49c90cdc0` |
| `.cache/t3-r5-reconfirm-red.xml` | 13 passed / 1 failed | `ce1afb7c36eff4a203fb66603ae6e00146e193c9071af2fa87be057530f39625` |
| `.cache/t3-r5-reconfirm-green.xml` | 111 passed / 0 failed | `8027624497d34727d44cad343f823a1fda096aa3ba19c84971aaebf36247bd81` |
| `.cache/t3-r5-stale-writer-red.xml` | 50 passed / 1 failed | `eb3e4559b2abf11f3dffd2201aef7f10d28d9d247cab5b6c4e4781b387ee092d` |
| `.cache/t3-r5-final-targeted.xml` | 121 passed / 0 failed | `a97403a27300153414f56c9c7ef42be8b9ef3358fa21e2e2229df1ad62cc3b05` |
| `.cache/t3-r5-host-adapter.xml` | 1 passed / 0 failed | `d835c4feb14612a7318ce22237b42fe4779cd26cd263e091a305f0b10f19a79d` |
| `.cache/t3-r5-full.xml` | 11,725 passed / 4,261 skipped | `62d743b70974e402846a00f3eebef2f782118bc40d9a15e9b49b2dc206c4fd52` |
| `.cache/t3-r5-full.log` | exit 0 | `8541d645c831a72ddedc210add8c2f5a8e6467b4aadf55631fc062de6eb74dca` |

Other final checks: scoped Python Ruff, five Lua chunk parses, and `git diff --check` pass.
Production `lua/gen3/native.lua:146` still returns false from `trade_capable()`; the FR, LG,
Emerald and RR target headers still contain `SLINK_TARGET_READY 0u`.

Host adapter: installed BizHawk `2.11.1+bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5` with NLua.
Two separate PowerShell/NLua processes persisted epoch 1, recovered its intent, and allocated
epoch 2; the actual configured Save RAM path builder was executed. EmuHawk was not launched.
NLua DLL SHA256: `f413017bfc7a37dfcaeb6e6c24812fd12ceb2b4b107a066512ed28c13010b234`.

No emulator/native-trade, physical battery-reload, power-loss, or frame-overhead qualification
was performed. Reload equality covers the selected save counter, trainer OT and active party;
it does not prove equality of every PC/storage byte. RR reload layout remains unqualified.
Complete deletion of both durable journal artifacts remains the explicit operator-reset limit
described above. None of these checks lifts a production readiness hold.

Full command: `python -m pytest tests/unit -q -p no:randomly --tb=short --basetemp=.cache/t3-r5-full-tmp --junitxml=.cache/t3-r5-full.xml`

The run used `SLINK_GEN3_ROMS=E:/Google Drive/SLink`,
`SLINK_GEN3_RAND_ROMS=C:/slink-wt/rand_roms`,
`SLINK_UPR_JAR=E:/Google Drive/SLink/.cache/slink-upr/PokeRandoZX.jar`,
`SLINK_PRET_FIRERED_SRC=E:/Google Drive/SLink/.cache/pret/pokefirered`,
`SLINK_PRET_EMERALD_SRC=E:/Google Drive/SLink/.cache/pret/pokeemerald`, and
`SLINK_HOST_GCC=E:/Google Drive/SLink/.cache/build-tools/w64devkit-2.10.0/w64devkit/bin/gcc.exe`.
The final receipt commit changes this document only; runtime and test source remain at the tested cut.

## T3-R6 review corrections — SOURCE / MODEL

The native `save_success` milestone now calls the host SaveRAM API through `pcall` before it
can release an intent via `native_saved`. An unavailable API, exception, or explicit false
return keeps the journal entry and requires qualified reload, even if an authoritative final
has already arrived. Duplicate native save milestones do not trigger another flush. The
ordinary `f.save` observer is independent of this protocol callback; the client MODEL reproduced
a complete native success with no observer flush before this correction. Player HUD text is
unchanged. A permanent journal failure logs its original reason to the console once and remains
fail-closed for that journal instance.

A config without `run_id` now revokes the existing journal binding just like an empty ID;
failed rebinding also leaves reports and finals withheld. Every bind invalidates previously
qualified reload evidence. Server-supplied run IDs and tokens must be nonempty printable ASCII,
with named bind/arm refusals before any journal write. Originating epochs are canonical JSON
integers, including integral-float API inputs; the restart and wire round-trip tests cover the
integer/string identity used by recovery declarations.

The rollback claim is deliberately limited to **mismatched rollback**. A mutually consistent
older log and guard pair passes local validation; no local seal can distinguish that pair from
the latest state without an external freshness authority. The MODEL counterexample at
`.cache/t3-r6-paired-rollback.json` restores both genesis files after an intent and observes an
empty journal and reused epoch. This limitation applies to restore/sync rollback as well as
deliberate rollback; the journal is not a freshness or anti-tampering guarantee.

The journal remains at the existing install-root path for this correction. Silently switching
to a battery-adjacent path would orphan existing pending intents and could provision a new empty
journal. Co-location alone also does not make save/journal backup or sync atomic. A future path
change needs explicit migration preserving existing records and a defined restore policy.

The host test now mirrors the native DLL search setup in
[pinned EmuHawk Program.cs](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Client.EmuHawk/Program.cs#L125-L160).
The old PATH-only harness passed in Codex's PowerShell 7.6.5/.NET 10.0.11 but failed in the
WindowsApps 7.6.6/.NET 10.0.12 host with `Could not load native lua methods`; both were x64 and
used the same managed NLua assembly. `SetDllDirectoryW` fixes that loader difference. The test
executes both discovered hosts, verifies the actual managed NLua and native Lua DLL paths and
Lua 5.4, and still exercises two fresh processes against the actual file adapter. An installed
runtime that fails to load remains a test failure, never a blanket skip.

### T3-R6 verification receipt — 2026-09-27

Tested source cut: `6cbff82bf116c42ec3f38b16e577215e326eefdf` on `codex/t3-r5`, based on
`a92ad55c2d40a97c5d88c279597dea802e33009d`. The receipt commit changes this document only.
Related suite: **509 passed, zero failures/errors/skips**, including both real PowerShell hosts.
Full `tests/unit`: **11,809 passed, 4,205 skipped, zero failures/errors**, exit 0,
798.52 seconds. All 140 direct trade/journal/recovery/host controls ran without skips;
both PATH-selected and WindowsApps PowerShell hosts passed. Full-suite skips remain unexecuted evidence.

Each implementation correction was observed failing before its fix:

| Control | Red result | Receipt SHA256 |
| --- | --- | --- |
| WindowsApps NLua host | 1 failed / 1 passed | `56315aa4e5f11e6a1646c11961efebcd605eec8c9107dcd098ed0def4633db96` |
| SaveRAM before retirement | 4 failed / 0 passed | `e83cff384cc13c19fb1ec603cff7f2de7373caebd489966d844e3616db414468` |
| Permanent fault console logging | 2 failed / 0 passed | `b02ade3bbd04716ec12781c0cac0e0561058db3faadb375757a6e509af220103` |
| Missing run / expired proof | 3 failed / 0 passed | `8a5b550f117431838cb6c3e07b8d79ba77d9328db7aec1eeef3b8e49d0d822c6` |
| Printable ASCII identifiers | 14 failed / 1 passed | `da59b603bb0e450f3b7c8729c7574512abe65d3c04656c42da4226716e914647` |
| Integer epoch round trip | 1 failed / 1 passed | `2676d175036b5fdc684f3a843c2cf53ca1f359603de3f9bb4099db84dd5af193` |

All rows pass in the related and full suites. Item 6 is a documented detection limit,
not a claimed rollback-detection implementation: `.cache/t3-r6-paired-rollback.json`
reproduces acceptance of a mutually consistent older file pair and epoch reuse.

Final raw receipts in `C:/slink-wt/em-t3/.cache/`:

- `t3-r6-related.xml`: `f532a65043904f203a2aff28b903ec25a9bf768bccef657aa146c1a176258b5a`.
- `t3-r6-full.xml`: `1f1311eaea3f528b0a436e0481a7d5d9fb1d5071c6ea593ed3c751a53e8c77ee`.
- `t3-r6-full.log`: `00f9df09b24ca61ae11975b5f9aafdb995195bc9cb102ad3ccb42af7df33ba70`.

The machine-readable ledger is `.cache/t3-r6-receipt.json`. Native loader evidence used
`E:/Howard/Bizhawk/dll/NLua.dll` SHA256 `f413017bfc7a37dfcaeb6e6c24812fd12ceb2b4b107a066512ed28c13010b234`
and `lua54.dll` SHA256 `4786e0df4caf120e3bedf0b6dda260525df2187c66ded220a21a53ace76b0501`.

Full command: `python -m pytest tests/unit -q -p no:randomly --tb=short --basetemp=.cache/t3-r6-full-tmp --junitxml=.cache/t3-r6-full.xml`.
Environment: every assignment in `C:/slink-wt/g3-env.sh`, plus
`SLINK_EXPANSION_SRC=C:/slink-wt/g3-xc4/.cache/expansion/e8bd1cd7b03fc032ea37e3ecd38b379b5d01a1e7`
and `SLINK_HOST_GCC=E:/Google Drive/SLink/.cache/build-tools/w64devkit-2.10.0/w64devkit/bin/gcc.exe`.

Scoped Ruff, five Lua parses, and `git diff --check` pass. Production `trade_capable()`
still returns false, all four `SLINK_TARGET_READY` values remain zero, and no emulator was launched.
This is SOURCE/MODEL and host-runtime verification, not physical trade or power-loss qualification.
