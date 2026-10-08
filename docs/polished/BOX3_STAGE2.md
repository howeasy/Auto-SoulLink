# BOX3 Stage 2: Polished client write outcomes

Status: DESIGN ONLY; capability OFF. MUST statements and new field/API names below specify future behavior, not implemented behavior. No runtime edits, test execution, staging or commits belong to this card.

## 1. Evidence cut

Read 2026-10-07. Local HEAD is `87813ee8c41841e93b5134f95437f098b2f790bd`, branch `claude/pol-docs3`, initially clean (direct Git queries). The request's integration label `addea4dec` is not this checkout's HEAD. Unprefixed citations refer to this checkout. `S1:` refers to the separate `F:/slink-work/wt/pol-box3` tree, read at HEAD `401b79b3d87d2ab686be185279eb92646ded3352` (direct Git query with command-local safe.directory). That differs from the recalled Stage 1 cut; ancestry, review acceptance and merge status are UNVERIFIED here. Do not assume it is integrated. In classifier tables, shortened filenames identify the same files under `lua/gen2/` or `docs/polished/` cited in the surrounding paragraphs.

Authority: `docs/polished/BOX_WRITE_CONTRACT.md:14-47,49-74`. S1 specifies integer-one negotiation, three commands including memorialize, result/ack, terminal idempotence, unresolved holds and persistence (`S1:docs/protocol.md:165-218,763`; `S1:server/state.py:797-929,2272-2310,2437-2458,5209-5211`). Its focused tests manufacture results directly (`S1:tests/unit/test_box_write_contract_state.py:125-161`), not through the Lua classifier.

Current composition is `Overworld.boxes` -> `Overworld.client_boxes` -> shared Gen 2 client (`lua/gen2/entry.lua:909-943`). The adapter currently converts withdraw metadata success to bare true and normalizes `party full` (`lua/gen2/polished_overworld.lua:998-1016`). Memorial execution is uncomposed (`:852-859`).

## 2. Classifier contract at O.client_boxes

Add a negotiated structured-result method; retain legacy method shapes when disabled. Never infer outcome from true/nil, exception text, a key list, or permit success. A wrapper around today's executor cannot recover local staged coordinates, planned bytes and options after an exception: expose a side-effect-free plan and operation evidence from the executor/reader (`lua/gen2/polished_overworld.lua:499-525,698-736`; `lua/gen2/polished_boxes.lua:305-340,362-365`).

Before any mutator, freeze player/save/ROM identity, client lifetime/checkpoint generation, write_id, wire key/cmd, resolved physical key/alias, source/destination box/slot/bank/entry/addresses, FULL party bytes/count, touched raw allocation/Banks/Entries metadata and neighbouring bits, both copies' references, source/sealed entry/checksum, exact planned postimage, live rebuild options, reconstructed record/OT/nickname and permit-log cursor. Expose allocation choice BEFORE stage_entry emits; allocation checks gameplay AND backup references (`lua/gen2/polished_boxes.lua:323-340`). Planning failure performs no write.

Mark attempted BEFORE the first potentially emitting method; record emission_started immediately before the underlying write. Receipts locate possible mutation, not successful I/O: the permit increments attempted before emit and appends its receipt after the span returns/throws, so a swallowed write can report written (`lua/write_permit.lua:135-149`). Prefer Polished-specific instrumentation; a shared permit change needs a separate shared-owner card.

After success OR failure, obtain fresh readback in a valid hold with unchanged identity/options/context: full party/count, complete gameplay census, raw touched metadata, exact sealed entry/checksum, and backup references when proving scratch is unreferenced. Verify every other active party mon and neighbouring metadata bit. A lost hold permits later read-only reclassification only under the same context; until then UNCERTAIN. Existing write_party_block compares bytes (`lua/gen2/polished_overworld.lua:340-355`), while deposit's final checks are count/key/location (`:561-581`) and withdraw's target checks are narrower than whole-party proof (`:824-841`).

Precedence: identity/context lost after possible emission -> UNCERTAIN; otherwise exact postimage -> PROVED_COMPLETE; otherwise fresh safe preimage -> PROVED_NOT_COMPLETE; else UNCERTAIN. A genuinely new attempt refused before any emission may prove NOT_COMPLETE from control-flow evidence, without inventing an unread party_count. This exception cannot settle an earlier unresolved ID. Missing expected source, ambiguous identity or inconsistent initial state stays UNCERTAIN: definite failure can itself change server membership (`S1:server/state.py:897-911`).

### 2.1 Deposit / box_mon

Existing sequence: non-egg party match, count >1, no mail at/after removal; choose non-memorial destination; stage sealed entry; publish allocation/Banks/Entries; compact record/OT/nickname arrays, count last (`lua/gen2/polished_overworld.lua:458-558,413-429,340-355`; `lua/gen2/polished_boxes.lua:362-379`). Keep the batch's count-only last-mon policy (`docs/polished/BOX_WRITE_CONTRACT.md:63-64`).

| Boundary | Required evidence | Outcome |
|---|---|---|
| Before emission | Unique expected source and safe prestate, verified guard refusal (egg exclusion/mail/last mon/full storage), no emission | NOT_COMPLETE; count only if freshly proved. Missing/duplicate source -> UNCERTAIN. Guards: `polished_overworld.lua:458-489`. |
| D1 staged only | Full party preimage; reference/allocation/Banks/Entries metadata unchanged; staged bytes unallocated and unreferenced in BOTH copies | NOT_COMPLETE despite changed unused scratch bytes; no recovery write (`BOX_WRITE_CONTRACT.md:38`; `polished_boxes.lua:323-340`). |
| D2 publication | Same safe preimage as D1 | NOT_COMPLETE. Flag-only/Banks-only, invalid reference, published duplicate, unexplained neighbour change -> UNCERTAIN (`BOX_WRITE_CONTRACT.md:39`; `polished_overworld.lua:517-555`). |
| D3 compaction / D4 late readback | Exact planned whole-party/count, all survivors intact, original removed; planned pointer/bank/allocation and checksum-valid exact sealed entry; other metadata unchanged | COMPLETE with proved count and source stats. Mixed/torn arrays -> UNCERTAIN even if count/key look right; fresh safe preimage instead -> NOT_COMPLETE (`BOX_WRITE_CONTRACT.md:40-41`). |

No automatic deposit repair/retry after ambiguous publication or compaction. A wholly swallowed write is NOT_COMPLETE only with safe-preimage proof; a partial swallowed write is COMPLETE only if the complete postimage nevertheless matches. Emission started plus unreadable readback, or identity change mid-write, is inherently UNCERTAIN with available evidence. Refusal prose saying “party untouched” is not proof (`BOX_WRITE_CONTRACT.md:30-35`; `lua/write_permit.lua:135-149`).

### 2.2 Withdraw / party_mon

Freeze source entry/options and reconstructed 48-byte record + 11-byte OT + 11-byte nickname. Existing guards exclude boxed eggs/mail, reject duplicate party keys and verify checksum. Writes append record/OT/nick then count, clear source Entries then Banks; pokedb entry/allocation are retained (`lua/gen2/polished_overworld.lua:688-765,785-841`). Do not add allocation cleanup.

| Boundary | Required evidence | Outcome/action |
|---|---|---|
| Guard-only | Unique source retained, safe party prestate, no emission; egg/mail/full-party/rebuild refusal established at guard | NOT_COMPLETE, not inferred from text (`polished_overworld.lua:691-707,734-735`). |
| W1 before count | Count and ALL active party bytes preimage, source entry/pointer/Banks/allocation preimage; only planned inactive append bytes may differ | NOT_COMPLETE. Record the inactive-tail exception; do not claim raw equality (`BOX_WRITE_CONTRACT.md:42`). Active-byte difference -> UNCERTAIN. |
| W1 count landed, both places | Exact planned appended full-party image/count, source intact, identity/options/context unchanged | UNCERTAIN until bounded same-ID source cleanup proves complete postimage; then COMPLETE. Never re-append. Existing both-places comparison works even with full party (`polished_overworld.lua:732-745`; `BOX_WRITE_CONTRACT.md:43`). |
| W2 Entries zero, Banks unfinished | Planned full party, retained source coordinates, Entries zero, unchanged sealed entry, all other metadata planned; only Banks cleanup remains | Fresh narrow permit may finish ONLY planned Banks bit; full fresh proof -> COMPLETE; failure/unreadability -> UNCERTAIN (`BOX_WRITE_CONTRACT.md:44`; `polished_overworld.lua:785-841`). |
| W3 late readback | Exact full-party/count postimage, source Entries zero, planned whole Banks byte, entry/allocation retained, complete census | COMPLETE even after executor refusal; source absence alone never suffices (`BOX_WRITE_CONTRACT.md:45`). |

Cleanup is a bounded continuation of the original attempt, not redelivery execution. Require retained exact context and a valid fresh permit; no retry-until-success loop.

The no-box idempotent branch accepts a unique non-egg party mon but refuses HP 0 (`lua/gen2/polished_overworld.lua:671-686`). Preserve that dead guard. A SAME-ID terminal duplicate replays its frozen result without executing or checking today's HP: later death is separate intent, not reversal of past completion. An unresolved ID needs retained exact postimage evidence even if no box contains its key. A NEW ID unexpectedly finding only a healthy party copy is UNCERTAIN pending reconciliation, not proof from the legacy shortcut. A genuinely new no-write dead refusal with safe state proved is NOT_COMPLETE and must never re-add the dead key. Existing tests distinguish an already DEAD server link from a still-ALIVE link whose failed retrieval re-boxes its partner (`tests/unit/test_polished_state_roundtrip.py:213-256`); test retained death ordering rather than assume it.

### 2.3 Memorialize

Current executor refuses without mutation (`lua/gen2/polished_overworld.lua:852-859`). With verified source/safe prestate, a negotiated attempt is NOT_COMPLETE; never send legacy memorialize_failed or retire its death obligation. Keep B uncomposed pending policy. Park an uncomposed refusal until composition changes, and capacity-blocked last-mon retry until a capacity-changing event, rather than cycling fresh IDs every tick. This needs server follow-up: S1 immediately queues another memorial on NOT_COMPLETE (`S1:server/state.py:908-922`).

Future box-origin B freezes source and memorial destination. COMPLETE requires destination pointer/bank to the exact same valid entry, source Entries cleared, full party unchanged and unrelated metadata/allocation untouched. Current lower-level move writes destination Banks, destination Entries, source Entries; source Banks is NOT cleared (`lua/gen2/polished_boxes.lua:284-302`). Plan that exact postimage. NOT_COMPLETE requires intact source and unpublished destination/metadata preimage; partial publication, both references, or missing source without proved destination -> UNCERTAIN. No automatic memorial repair is authorized here.

Future party-origin B uses exact memorial entry/publication plus planned full compaction and survivor preservation (D1-D4 evidence), with approved burial-specific guards. A last-party rule is not a blanket healthy-survivor rule. Its exact executor plan/guards remain UNVERIFIED until B is authored. COMPLETE applies existing server memorial completion once; NOT_COMPLETE alone retains pending_memorials; only named last-party/run-over may retire it (`docs/polished/BOX_WRITE_CONTRACT.md:63-74`; `S1:server/state.py:893-911`).

## 3. Capability and client route

Proposed `box_write_contract_enabled` defaults false/absent for EVERY generation, including Polished. Only production Polished composition may explicitly enable it after classifier, owed-slot and reset-handshake evidence passes. Require admitted Polished identity and a composed version-1 adapter; ROM type or global config alone is insufficient. Add integer `box_write_contract=1` to hello only under that gate (`lua/gen2/client.lua:1855-1875`; `lua/gen2/entry.lua:909-943`). Include proposed lifetime field below. S1 requires exact integer one and accepted identity (`S1:server/state.py:2437-2443`; `S1:tests/unit/test_box_write_contract_state.py:446-452`). Old server/no recovery handshake means no writes, not legacy fallback.

Preserve write_id and session/recovery fields at admission: today's deferred copy keeps only cmd/key/nickname/arrival (`lua/gen2/client.lua:594-603`). Deduplicate before enqueue by player/identity/ID and validate cmd/key. After physical-key/name resolution and FS.guard_box, branch to the negotiated adapter BEFORE stats_cache or legacy settlement/success/failure (`lua/gen2/client.lua:1572-1598`). Store wire and physical keys separately. Untagged/invalid command while enabled writes nothing, sends no keyed legacy reply, and awaits protocol synchronization; never invent an ID.

Negotiated results replace stats_cache, box_mon_failed, sync_retrieve_done/failed, memorialize_done/failed. Stats belong in the result; COMPLETE needs proved integer party_count 0..6 (nonzero withdrawal); UNCERTAIN carries no speculative count/stats (`S1:docs/protocol.md:172-203`). HUD/rescan effects are once-only. Capability OFF must retain identical legacy hello/wire/queue behavior. No Gen 1/3 source, vanilla Gen 2 executor, shared hello-session or generic owed-report change is required by this design; prove isolation by tests (`BOX_WRITE_CONTRACT.md:18,46-47`).

## 4. Owed slot, liveness and reset

### 4.1 Uninterrupted lifetime

One unresolved slot per player, not per key. States: WAITING (no emission), EXECUTING, RESULT_OWED, UNCERTAIN_ACKED, TERMINAL_ACKED. Store frozen context/result, outcome and local-effects-applied flags. Duplicate matching ID/tuple in WAITING does not enqueue again; executing duplicate does nothing; result-known duplicate resends without execution. Changed tuple for same ID is protocol error preserving hold. Different ID cannot overwrite unresolved slot.

Send result immediately, after each successfully sent same-identity hello, and every regular connected tick until matching box_write_ack ID AND outcome. Use current tick cadence (`lua/gen2/client.lua:2421`), not per-frame retries. Config/noop/unrelated line/legacy ack cannot clear it; stale UNCERTAIN ack cannot clear a newer terminal result. UNCERTAIN ack stops that payload's retries but DOES NOT free the slot or mutation/publication hold. Later proof under same ID creates a new owed terminal payload. Terminal ack frees active slot but retains lifetime tuple/result tombstone so late commands cannot execute again. Initially retain tombstones for the session; bounded eviction needs an explicit server retirement fence. S1 supports terminal replay and refuses reversal (`S1:server/state.py:838-882`).

Mutation/publication hold starts at EXECUTING and continues through result ack/UNCERTAIN. Omit authoritative party/census fields, never substitute empty arrays; hold party/box/trade writes and retain intent. WAITING must allow prerequisite F2b work (section 5). Protocol heartbeats and result replay must work without readable snapshots. Current hello requires a party snapshot (`lua/gen2/client.lua:1842-1844,1857-1861`); capable recovery needs a withheld-snapshot mode matched by server hold semantics (`S1:docs/protocol.md:193-203`).

### 4.2 Lost-initial-response gap: required server amendment

S1 iterates queued_commands, persists identity before returning a command, then removes delivered items from the queue (`S1:server/state.py:803-835`). Its redelivery test explicitly requeues (`S1:tests/unit/test_box_write_contract_state.py:305-317`). That proves ID reuse, NOT automatic replay after the first command or result is lost.

Server MUST store immutable original command, player/save identity, write_id, issuing client lifetime, delivery status, result/outcome, publication status and retained intent. For no-result rows, each accepted hello/tick schedules at most one resend of that stored command under SAME ID even with empty queued_commands. Timeout never creates a new ID. Result arrival stops ordinary command resend; client replay repairs lost ack, which is sent only after persistence/publication. UNCERTAIN recovery announcements bypass mutator filters as protocol-only messages, never as write authorization. Persist before first delivery (`S1:server/state.py:829-835,864-929,5209-5211`).

### 4.3 Reset/fresh-client handshake: new, not in S1

Under this task's persistence constraint, BizHawk restart preserves only ROM/save on the client side. Lua slot/result/preimage/write_id do not survive; WRAM mailbox is not durable (`BOX_WRITE_CONTRACT.md:55-59`). Server journal supplies durable operation identity, NOT cartridge proof. No new client disk journal or ROM/save format is authorized.

Propose capable hello `box_write_session`: a collision-resistant opaque lifetime token, rotated on Lua startup and detected reset/savestate/new-game boundary. Exact randomness provider is UNVERIFIED and must be selected/tested before enabling; rewindable framecount is insufficient. Socket reconnect with uninterrupted Lua/game state retains it. Continuity loss invalidates byte proof and freezes the old slot. Existing reset and identity hooks are entry points (`lua/gen2/client.lua:1762-1763,1915-1925`); complete savestate/rewind coverage remains UNVERIFIED.

Add `box_write_resume{session,pending?}` server command after identity-accepted hello and before new mutations. Pending contains server ID/key/cmd/outcome/original issuing session. This command NEVER executes writes. No pending means session admitted, not proof of save durability. Client holds writes/publication until resume. A normal startup hello may carry a valid snapshot but server withholds it if old operation exists. An identity-only recovery hello with explicit withholding must still obtain pending identity when party reads fail; server must not interpret absence as empty party.

While waiting for resume, client retransmits capable hello on its regular connected tick with the same session; server repeats the idempotent resume response before ordinary command delivery. Do not let a lost resume create another startup deadlock. If server has a terminal row while client retains an owed terminal result, client replays that result and obtains its ack even when resume has no unresolved pending row. Session admission and result acknowledgement are distinct.

Matching retained live context: resend known result or keep one WAITING entry. Different lifetime or absent local context: reconstruct only tuple and report UNCERTAIN, reason `client reset: operation evidence lost`; NEVER execute, even if current census resembles success/preimage. Ack retains recovery hold. S1 server reload already converts unknown operations to UNCERTAIN (`S1:server/state.py:2298`; tests `S1:tests/unit/test_box_write_contract_state.py:381-402`). Older journal rows lacking session metadata are recovery-only.

Ordinary tagged commands carry accepted issuing session and are issued only after resume. Mismatched-session delivery is rejected pending resume. This distinguishes a new first delivery from an old unresolved ID after restart. A fresh server with lost journal cannot reconstruct vanished operation history from ROM/save: fail closed, explicit operator recovery. A server-persisted terminal result is not reopened/reversed by client reset or lost ack. Boot census revealing rollback of volatile completion needs separate native-save reconciliation; Stage 2 does not claim automatic terminal rollback repair. Unresolved reset closure needs pinned before/after saves, operation-linked byte proof and explicit recovery under original ID; until then visible UNCERTAIN is correct (`BOX_WRITE_CONTRACT.md:55-59`; `S1:docs/protocol.md:205-218`).

## 5. F2b and memorial ownership

FS remains sole faint-settlement owner. guard_box finds unsettled death, requeues and sends no reply (`lua/gen2/client.lua:1444-1452,1578`). This is WAITING, not NOT_COMPLETE. Preserve write_id; collapse duplicates. Let F2b finish BEFORE box emission or a blanket unresolved-slot gate deadlocks its own prerequisite. After emission, later faint/memorial/PC/trade mutation waits with intent retained. Read-only result replay bypasses execution guards. run_deferred also schedules quiet/revived deaths, so coordinate with F2b owner (`lua/gen2/client.lua:1457-1484`).

Identity/reset must quarantine the old box slot, not transfer its evidence or erase it with drop_held; current invalidation clears aliases/dead state and drops held commands (`lua/gen2/client.lua:1915-1925`). Return to original accepted identity recovers original server row; wrong-save cannot settle (`S1:server/state.py:845-848`).

Negotiated memorial COMPLETE bypasses memorial_done's legacy wire event while applying local bookkeeping once. That helper clears dead keys/alias and sends memorialize_done (`lua/gen2/client.lua:1545-1549`); failure may clear dead keys (`:1661-1665`). Neither occurs on UNCERTAIN/NOT_COMPLETE. Polished no-op settle methods are not save witnesses (`lua/gen2/polished_overworld.lua:857-859`). B ships directly on three outcomes after policy approval (`BOX_WRITE_CONTRACT.md:70-74`).

## 6. Verification plan: execution OPEN

No Python or emulator runs in this design card. Source is SOURCE evidence; proposed tests supply MODEL evidence; restart/native-save claims need separate PHYSICAL receipts. No existing pass count is claimed.

Use real composed Rig and real SoulLinkState. Base bridge records both players, but drain ignores returned commands and advances a batch cursor (`tests/unit/polished_state_rig.py:87-122`). Adapt RoundTripBridge's deep unchanged-command delivery, per-event cursor and actual party-bearing ticks (`tests/unit/test_polished_state_roundtrip2.py:75-138`). Add explicit drop/reconnect schedules and two Rigs for partner physical claims. Exercise ordinary withdrawal AND production-started rebuild, not only synthetic open rebuild. Mutant injection exists (`tests/unit/polished_state_rig.py:55-72`; red control `test_polished_state_roundtrip.py:175-205`).

Every row asserts wire, byte-write count, full cartridge arrays/metadata, BOTH players' keys/counts/inflight/queues/rebuild, journal and owed state. Run the same safety oracle against good and mutant code; the mutant must fail it.

| Test | Scenario/oracle | Red control |
|---|---|---|
| T1 | OFF isolation Gen 1/vanilla Gen 2/Gen 3/Polished; enabled untagged writes nothing; queue preserves ID | Remove capability gate or strip ID |
| T2 | D1 scratch, W1 pre-count, egg/mail/count/full guards, both-copy references; no membership invention | All refusals classified negative; ignore backup |
| T3 | Throw after exact D4/W3 postimage; W2 cleanup; complete once, no compensation/double count | Trust executor boolean/receipt |
| T4 | Both places/full party, torn target, no-box shortcut, HP0 with death processed and still queued | Remove byte/dead guard; execute duplicate |
| T5 FIRST falsifier | Every compaction byte/count cut, swallowed writes, unreadable post-read, identity switch; mixed state held, no retry/compensation/torn publication | Legacy NACK or count/key-only proof |
| T6 | FS-owned target waits once, later intent retained, conflicting tick/census/stats/keyed ack/expiry/trade/partner PC blocked; uncertain ack holds | Clear slot on any ack; publish empty party; faint through hold |
| T7 | Wrong ID/key/cmd/player/session, terminal reversal/late command, changed rebuild options | Key-only dedup, tombstone eviction, changed-option cleanup |
| T8 | Lose first command with EMPTY server queue, first result, ack separately; hello/tick retries use one ID/one execution; fresh Lua from save at every cut, fresh State from journal | Disable timer/resend/resume; unknown ID treated new |
| T9 | Memorial refusal retains death, no busy retry; future box then party-origin exact proof; last-mon/run-over exception | Legacy failure or premature dead-key clear |

S1 focused tests remain prerequisites, including reload/save-failure replay and retained-hello amendments; reading them is not a pass (`S1:tests/unit/test_box_write_contract_state.py:381-405,455-471,681-803`). Register session/resume/recovery/withheld-hello schema and conformance. Discovered registry files are listed in cards below; internals are UNVERIFIED here.

PHYSICAL gate: private before/after native saves and byte receipts for stage/publish/compaction/append/pointer boundaries; Lua reload, soft reset, BizHawk restart, savestate, server restart, disconnect and wrong-save hello. Show unresolved reset reappears under original ID with zero writes. Prove native-save durability separately. Capability remains OFF until required reset detection/handshake evidence exists.

## 7. Exclusive cards and order

Proposed leases only; this card edits this document alone. Each row <=3 exact files; overlaps are sequential with explicit handoff. One polished_overworld writer. Shared-code cards need owner notice and Gen 3-first checks, then other generations (`BOX_WRITE_CONTRACT.md:68-69`). Local CLAUDE.md was absent; broader owner rules are UNVERIFIED and must be checked at assignment.

| Order/card | Exclusive files | Deliverable |
|---|---|---|
| 0 rulings | None | Accept/pin amended S1, F/G and memorial policy; F2b seam agreement; token provider. |
| 1 D red | `tests/unit/polished_state_rig.py`; NEW `tests/unit/test_polished_box_contract_roundtrip.py`; NEW `tests/unit/test_polished_box_contract_recovery.py` | Real T5 red first, then transport/classifier oracles. |
| 2 S replay (SHARED) | `server/state.py`; `docs/protocol.md`; `tests/unit/test_box_write_contract_state.py` | Empty-queue replay, session/resume, withheld recovery hello, memorial retry parking, safe journal migration; owner notice, Gen 3 first. |
| 3 S registry (SHARED) | `tests/unit/protocol_schema.py`; `tests/unit/test_protocol_schema.py`; `tests/unit/test_protocol_conformance.py` | Read owners/content before editing; new fields/command/isolation. |
| 4 S citations (shared protocol) | `tests/unit/test_protocol_citations.py`; `docs/protocol.md` | Citation/assertion 48 checks after registry; no renumbering. |
| 5 A evidence | `lua/gen2/polished_overworld.lua`; `lua/gen2/polished_boxes.lua`; NEW `tests/unit/test_polished_box_classifier.py` | Pure plan, emission capture, byte classifier, bounded withdrawal cleanup; legacy shapes preserved. |
| 6 A client (shared Gen 2/F2b notice) | `lua/gen2/client.lua`; `lua/gen2/entry.lua`; NEW `lua/gen2/polished_box_contract.lua` | Slot/tombstones, ID queue, resume/reset, resend, publication gates, Polished-only default OFF. |
| 7 D green | `tests/unit/polished_state_rig.py`; `tests/unit/test_polished_box_contract_roundtrip.py`; `tests/unit/test_polished_box_contract_recovery.py` | Real round trips/red controls after S+A; sequential handoff from 1. |
| 8 B box origin | `lua/gen2/polished_overworld.lua`; `lua/gen2/polished_boxes.lua`; NEW `tests/unit/test_polished_memorial_box_contract.py` | Approved memorial plan/classifier; A green and policy required. |
| 9 B party origin | `lua/gen2/polished_overworld.lua`; NEW `tests/unit/test_polished_memorial_party_contract.py`; `tests/unit/test_polished_box_contract_roundtrip.py` | Full compaction/guards/F2b/pending proof; after box-origin green. |
| 10 qualify/enable | `lua/gen2/entry.lua`; `docs/polished/BOX3_STAGE2.md` | Owner-approved model/physical evidence, explicit Polished opt-in; coordinator assigns separate frozen-digest lease. |

Any needed shared write_permit/hello_session/owed_reports change gets a separate <=3-file owner card with Gen 3-first checks. Digest generator/output paths and release procedure were not read: UNVERIFIED, do not expand these leases. Record exact executable commands/results in the execution cards; this design card has no Python. Source/model success alone cannot substitute for required reset/save evidence.
