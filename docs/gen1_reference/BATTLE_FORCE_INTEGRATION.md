# Battle force-faint: production integration proposal (Gen 1 R/B/Y)

Status: PROPOSAL for root review. No production file was edited. Every trace claim below
cites `file:line` in this worktree (2026-09-09). Prototype background: `BATTLE_FORCE_FAINT_WINDOW.md`
§9 (authority split, lines 284-360), §10-§11 (live qualification, 362-447).

Goal: an ADMITTED death in `gen1-faint-settlement` whose `deaths[death_id].phase == 'pending_faint'`
(`server/gen1_faint_runtime.py:173`) gets bounded execution of the battle instruction authority while
ordinary grants/commands are held, by riding the frame ledger, the one bounded owner and the frame
journal that already exist. No second owner, no unbounded bypass, `held_write_permit` untouched.

---

## 0. Trace: how the live client runs today

### 0.1 One bounded owner, one step at a time

* The owner is `platform_bounded_execution.new{owner_id=instance,…}` created once in
  `lua/gen1_client_entry.lua:65-69`; its `authorize` callback routes `phase=="ordinary"` scopes to
  `self.frames:authorize(scope, checkpoint)` (`:66-68`).
* `step_one(authority)` (`lua/platform_bounded_execution.lua:91-129`) verifies the hold and the expected
  frame (`:96`), calls `options.authorize(authority, {frame=before, owner_id, steps})` (`:100`), releases
  the hold for exactly one `StepRunLoop_Core` (`:108-111`), re-acquires it, asserts `framecount==before+1`
  (`:115`), increments its private step counter (`:118`) and returns
  `{before, after, owner_id, step=steps, user_paused}` (`:120`). `set_held(false)` is not exposed (`:130-133`).
* The client's `host.status()` wrapper (`lua/gen1_client_entry.lua:70-75`) reports
  `physical_stop_verified = bounded.host.physical_stop_verified and not failed and framecount==expected_frame`.
  Every "held" closure in the entry uses exactly this field (`:48`, `:130`).

### 0.2 How a frame request leaves the client and how the grant returns

* `durable_runtime.service` builds each control heartbeat and asks
  `operation_execution.request(binding, control)` for an optional operation packet
  (`lua/durable_runtime.lua:358-366`); the entry's router tries native, then held commands, then
  `self.frames:request` (`lua/gen1_client_entry.lua:188-201`).
* `gen1_frame_client:request` (`lua/gen1_frame_client.lua:176-211`) refuses when not admitted/held, when
  progress is not idle, when `commands_pending()` or the outbox is non-empty (`:179-183`). It builds
  `evidence={schema="rby-frame-request-v1", boundary, sequence}` (`:197`), a scope
  `{operation_id=nonce, operation_digest=sha{event="frame_grant",evidence}, context_generation,
  binding_digest, phase="ordinary"}` (`:199-200`), sets `p.active={scope, evidence, before=p.frame, steps=0,
  signals=[], request_started}` (+ `acquisitions=[]`, `:201-202`), persists, and returns
  `{window=self.window:challenge(), evidence}` (`:208-210`). The client window allows at most 120 frames /
  1000 ms (`:157`); the server grants 60 / 1000 (`server/gen1_frame_control.py:88`).
* The control response's `operation_execution` is handed to `operation_execution.accept(grant, binding)`
  (`lua/durable_runtime.lua:291-294`) → entry `accept` → `self.frames:accept(packet)`
  (`lua/gen1_client_entry.lua:202-213`). `frames:accept` calls `self.window:accept(packet)` (`:224`), which
  whitelists exactly `{schema, challenge, scope, frames, ttl_ms, proof_digest}`
  (`lua/execution_window.lua:97-98`) and verifies `proof_digest==sha(p.active.evidence)`
  (`lua/gen1_frame_client.lua:159`); then `p.active.grant`/`deadline` are persisted (`:229-230`).

### 0.3 How the owner steps frames inside the window

`gen1_frame_client:step` (`lua/gen1_frame_client.lua:302-353`), called every service tick from
`gen1_client_entry.lua:266`:

1. closes the range instead of stepping if commands/events are pending, close was requested, the
   deadline is near, or the window is exhausted (`:312-320`);
2. `options.step_one(copy(p.active.scope))` (`:326`, wired to `self.bounded.step_one` at
   `gen1_client_entry.lua:139`), asserts one frame advanced (`:327`);
3. peeks engine signals (`:328`), prepares acquisition receipts (`:329-330`), then
   `p.frame=before+1; p.active.steps+=1` (`:331`), appends signals (≤32, `:332-333`) and acquisition rows
   (≤16, `:334-338`) to `p.active`;
4. `save(baseline)` BEFORE draining hooks — the physical return is durable before the next step (`:340`);
5. auto-closes the range when a signal/acquisition landed or the window is spent (`:345-349`).

`authorize(selected, checkpoint)` (`:237-249`) is the per-step gate inside `step_one`: it requires an
active grant, `p.frame==checkpoint.frame`, no pending commands/events (`:241-242`), persisted signals
(`:243-244`), and spends one window credit (`:248`).

### 0.4 What `frame_complete` carries

`close_range` (`lua/gen1_frame_client.lua:250-285`): `bundle={boundary, inventory|null, engine_signals|null}`
(+ `acquisitions` copied from `active.acquisitions`, `:266-267`; + `native_checkpoint`, `:268-272`);
`receipt={schema="slink-frame-progress-receipt-v1", sequence, scope, before=active.before, after=p.frame,
steps=active.steps, observations_digest=sha(bundle)}` (`:273-274`); event `{event="frame_complete",
receipt, bundle}` (`:275`) is published through `options.observe` → `runtime:observe` (`:277-281`,
`gen1_client_entry.lua:137`), progress goes `queued` and returns to `idle` only on the durable ACK
(`acknowledge_event`, `:13-20`). Inventory is captured only when `memory.isPartyWriteSafe()`
(`gen1_client_entry.lua:151-155`), i.e. never inside a battle (`lua/memory_gb.lua:723-736`;
server mirror `server/gen1_held_faint.py:29` requires `BATTLE_FLAG_ADDR==0`).

### 0.5 Server: issuance, ledger, return, provenance

* Control routing: `server/gen1_runtime.py:380-391` sends `phase=='ordinary'` windows to
  `gen1_frame_control.issue_for_control`; everything else (held faint etc.) to
  `gen1_execution_authority.issue_for_control` with `verify_operation_execution=gen1_held_faint.verify`
  (`server/gen1_run_config.py:92,130`).
* `issue_for_control` (`server/gen1_frame_control.py:14-92`): evidence shape (`:18-25`), refuses while
  native-borrowed (`:28-29`); returns **None** if `document['active_trade']`, if **any player has any pending
  command** (`:47`), if **any barrier blocker is not the initial hold** (`:48`), or if **any player has
  obtained Poké Balls** (`:51-54`, "Initial network integration is intentionally bounded to pre-ball
  gameplay"). Then enrolls on sequence 1 (`:56-64`), checks boundary vs ledger (`:65-67`), scope vs
  admitted binding (`:70-80`), sequence continuity (`:81-85`), builds
  `VerifiedExecutionWindow(scope, digest(evidence), 60, 1000, digest(document))` (`:88`) and returns
  `grant(...)['frame_window']` (`:91-92`).
* `grant` (`server/gen1_frame_journal.py:355-410`): fresh paired connections (`:359-366`), admission match
  (`:367-372`), replay returns `old.result` (`:373-375`), **refuses when `runtime.journal.pending_ids(player)`
  is non-empty** (`:376-377`), issues the window (`:391`), `reserve`s the ledger (`:392`;
  `gen1_frame_runtime.reserve:158-180` → `frame_progress.reserve:119-141`, `limit=frame+frames` `:135`),
  stores `proof` fields (`:393-399`) and persists result
  `{"ack","frame_window","ordinary_execution":False}` (`:400-410`) into namespaces `COMPONENT` and
  `GRANTS` (`:307-311`).
* `returned` (`:413-527`): shape (`:420-425`), `complete(document, player, receipt, bundle)` (`:427`;
  `gen1_frame_runtime.complete:183-218` → `bundle_boundary` key set `{boundary?, inventory, engine_signals}
  ∪ {acquisitions, native_checkpoint}` `:66-68`, `observations_digest==digest(bundle)` `:207-210`, every
  signal frame `covers(closed, frame)` `:212-215`, `pending_observation={closed, bundle_digest}` `:217`).
  With `settle_observations=True` (always for network events, `server/gen1_runtime.py:289-292`) it stages
  engine signals, inventory, acquisitions (`:484-495`), encounters, storage, native checkpoint, sets
  `observations_settled` (`:509`) and clears `pending_observation` (`:515`); `_persist` adds the `RETURNS`
  record keyed by `previous_digest[:32]` (`:312-316`).
* `retained_return` (`:130-156`) re-derives a closed range from its `RETURNS` record and original grant;
  `verify_journal` (`:159-281`) reproduces every grant/complete result, including one digest per settled
  component (acquisition pattern `:243-248`, native checkpoint `:273-277`).
* Acquisition rows: `gen1_frame_acquisitions.stage` (`server/gen1_frame_acquisitions.py:93-168`) runs once
  per consumed `frame_complete`, decodes `bundle['acquisitions']` (`:102-111`) and `verify_frames`
  (`:44-91`) requires each row's final witness frame inside the closed range (`:57`) and earlier witnesses
  inside retained prior windows (`:71-90`). This is the pattern the instruction row copies.

### 0.6 The death and today's overworld path

* `settle` (`server/gen1_faint_runtime.py:96-192`) creates
  `deaths[death_id]={player, engine_record, index, link_id, members, key, peer, peer_key, at,
  phase:'pending_faint', receipt_event:None}` (`:162-175`; `deferred` optional, `:176-185`), queues the
  `force_faint` command `{cmd, death_id, key, nickname}` for the peer (`:187`) and adds a barrier blocker
  `REASON` (`:188-190`). Deaths need `pokeballs_obtained[player]` (`:122`).
* The peer's `gen1_held_faint` (Lua) only requests a permit when `safe()` = `isPartyWriteSafe() and
  physical_stop_verified` (`lua/gen1_held_faint.lua:38-40`, `:128`); the server verifier
  `gen1_held_faint.verify` (`server/gen1_held_faint.py:43-75`) demands `death.phase=='pending_faint'`
  (`:63`), the overworld checkpoint (`:65`, `:16-40`), `battle_flag==0` (`:71`) and returns a
  `VerifiedHeldWrite` (`:75`). An already-zero target is a proven no-op receipt
  (`lua/gen1_force_faint_executor.lua:43-44`; `lua/gen1_held_faint.lua:105`) and
  `verify_force_faint` accepts `before==after` with HP already `0000` (`server/gen1_command_receipts.py:75-80`).
* `acknowledge` (`server/gen1_faint_runtime.py:195-272`) is the ONLY transition out of `pending_faint`:
  `pending_faint → pending_memorial` (`:229-232`), party/rules refresh from `receipt.after` (`:233-248`),
  memorial scheduling (`:250-254`). `verify_state` pins phases (`:347-355`) and that `receipt_event` is
  None iff phase in `{pending_issue, pending_faint}` (`:352-354`); `verify_journal` pins exactly one
  physical obligation per death (`:502-507`) whose outcome is None while `pending_faint` (`:511-513`).

### 0.7 The prototype authority (what already exists, unwired)

* Server generic: `instruction_authority.issue` (`server/instruction_authority.py:52-70`) needs
  `request={schema, challenge, scope}` with `scope==proof.scope` and a measured `hook_frame_offset`;
  `verify_envelope` (`:73-107`) checks challenge/owner (`:80-81`), `frame`/`step` equality (`:82-83`),
  `held is False` (`:84-85`), returns `None` for an unreached row (`:87-90`); `verify_footprint` (`:110-127`).
* Server R/B/Y: `battle_force_authority.prepare(player, command, binding, death, member, host, *, variant)`
  (`server/battle_force_authority.py:155-174`), `issue` (`:177-181`, `HOOK_FRAME_OFFSET=0` pinned live,
  `:51-55`), `verify_evidence` → `{'outcome': fainted|benched|refused|not_reached, 'site', 'reason'}`
  (`:184-210`), `member_of(key, slot)` (`:95-100`).
* Lua generic executor `instruction_executor.new{owner_id, held, binding}` (`lua/instruction_executor.lua:16-19`):
  `arm(authority)` asserts schema/uses/held/owner/binding (`:60-61`), unused challenge (`:62`), step > last
  (`:64`), `held()==true` (`:65`), `frame==emu.framecount()` (`:66`), registers the bus-exec hooks once
  (`:68-72`); the hook fires only at `authority.frame+hook_frame_offset` (`:27`), pinned bank/PC/bytes
  (`:28-31`), `held()==false` (`:32`), consumes on first site (`:42`); `finish()` asserts the hold and exactly
  one frame (`:80-81`), returns the row (or a `not_reached` row, `:84-88`) and marks
  `used[challenge]=true; last_step=step` (`:90`).
* Lua R/B/Y binding `battle_force_authority.new{owner_id, held}` (`lua/battle_force_authority.lua:42-44`).
* The live gate proves the per-step pattern under the real owner: `arm → owner.step_one → finish` each
  frame (`lua/tests/test_gen1_battle_force_gate.lua:83-96`, `held()` = `owner.status().host.physical_stop_verified`, `:67`).

---

## 1. Turning the pending death into an instruction authority (server, at frame issuance)

Place: `gen1_frame_control.issue_for_control`, after the sequence check (`server/gen1_frame_control.py:81-85`)
and before `semantic=` (`:86`). New helper (R/B/Y binding file, so `gen1_frame_control` stays thin):

```python
# server/battle_force_authority.py
def pending_instruction(runtime, document, player, binding, ledger, frame_operation_id):
    """The one-use authority for the oldest pending force_faint of `player`, or None.
    None when: no pending command; oldest pending is not force_faint; its death is not
    'pending_faint' / already carries 'enforcement'; peer_key is not in the party roster."""
```

| `prepare(...)` arg | Supplied by | Where it already lives |
|---|---|---|
| `player` | the requesting session | `issue_for_control(runtime, player, request)` (`gen1_frame_control.py:14`) |
| `command` | `runtime.journal.command(player, pending[0])`, `pending=runtime.journal.pending_ids(player)` | `server/protocol_journal.py:421-433`, `:451-459`; flat body `{cmd, death_id, key, nickname}` (`gen1_faint_runtime.py:369-378`) |
| `binding` | `runtime.gate.sessions[player].metadata["control_binding"]` | already read at `gen1_frame_control.py:74` |
| `death` | `document['components']['gen1-faint-settlement']['deaths'][body['death_id']]` | `gen1_faint_runtime.py:162-175` |
| `member` | `member_of(death['peer_key'], slot)`; `slot` = the `location=='party'` row with `key==peer_key` in `inventory(entry['observation']['source'], save_identity)` where `entry = document['components']['gen1-inventory-observations'][player]` (fallback: `gen1-initial-observations[player]['observation']`) | `server/gen1_initial_observation.py:49-75` (rows `{location, box, slot, key, blob_hex, …}`, `:68-69`); component `server/gen1_inventory_observation.py:12,30-31`; `member_of` `battle_force_authority.py:95-100` |
| `host` | `{'owner_id': initial['metadata']['gen1_metadata']['physical_instance'], 'frame': ledger['frame'], 'step': ledger['steps'] + 1}` | same owner id the held faint pins (`server/gen1_held_faint.py:92`) and the boundary host carries (`gen1_frame_runtime.py:43-46`); ledger = `entry['ledger']` (`gen1_frame_control.py:65-66`) |
| `variant` | `initial['metadata']['gen1_metadata']['cartridge']['variant']` | as `gen1_held_faint.py:66` |

Then, in the same helper:

```python
challenge = digest({'frame_grant': frame_operation_id, 'death_id': body['death_id']})[:32]   # deterministic: replay reproduces it
proof = prepare(player, command, binding, death, member, host, variant=variant)
return issue({'schema': generic.SCHEMA, 'challenge': challenge, 'scope': dict(proof.scope)}, proof)
```

Semantics: one authority per frame grant, bound to `(owner_id, frame=ledger.frame, step=ledger.steps+1)`,
the command scope `phase='battle_force_faint'` (`command_scope`, `server/operation_scope.py:16-22`), and the
member's stable identity bytes. `step` is derivable from `frame` (`step = frame - anchor.frame + 1`), which
is what makes the per-frame derivation in §2 exact.

---

## 2. Reaching the client without a round trip per frame

### 2.1 Wire: one `instruction` on the frame grant

* `grant(runtime, player, operation, message, proof, *, instruction=None)`
  (`server/gen1_frame_journal.py:355`): when `instruction` is not None the persisted result becomes
  `{"ack":"ACK","frame_window":…, "ordinary_execution":False, "instruction": authority}`. Replay
  (`:373-375`) returns it unchanged; `_grant_value` reproduces it (see §2.4).
* `issue_for_control` returns `{**result['frame_window'], 'instruction': result['instruction']}` when present
  (`gen1_frame_control.py:91-92`). Nothing else on the control response changes, so `durable_runtime.lua`
  is untouched.
* Client `gen1_frame_client:accept(packet)` (`lua/gen1_frame_client.lua:212-231`): before
  `self.window:accept(packet)` (`:224`, strict whitelist `execution_window.lua:97-98`) pop
  `packet.instruction`; assert `instruction.schema=="slink-instruction-authority-v1"`,
  `instruction.frame==p.frame`, `instruction.owner_id==options.host.status().owner_id`,
  `instruction.step==options.native_host.status().steps+1` (`native_host` is the bounded owner,
  `gen1_client_entry.lua:136`; `status().steps` at `platform_bounded_execution.lua:143`); persist
  `p.active.instruction={authority=instruction, armed=0, reached=JSON.null}` alongside `p.active.grant`.

### 2.2 Client arming, once per stepped frame, same challenge

In `step` (`lua/gen1_frame_client.lua:302-353`), around `:326`:

```lua
local ins=p.active.instruction
local exec=ins and ins.reached==JSON.null and options.instruction and options.instruction()
if exec then
    local f=p.frame
    exec.arm({...ins.authority, frame=f, step=ins.authority.step+(f-ins.authority.frame)})   -- copy with per-frame frame/step
end
assert(options.step_one(copy(p.active.scope)))                     -- existing :326
assert(emu.framecount()==before+1,...)                              -- existing :327
if exec then
    local row=exec.finish()
    ins.armed=ins.armed+1
    if row.site~=JSON.null then ins.reached=copy(row); self.close_requested=true end   -- one mutation, close early like a signal (:345-349)
end
```

The existing `save(baseline)` at `:340` persists `ins.armed`/`ins.reached` before drain — the evidence is
durable the same way signals are. `authorize(selected, checkpoint)` (`:237-249`) gets one extra line:
if an authority is armed, `assert(armed.frame==checkpoint.frame and armed.step==checkpoint.steps+1)` —
the owner's own step counter (`platform_bounded_execution.lua:100`) is the cross-check.

Executor change required (one line): `finish()` marks `used[challenge]` only when the row reached a site
(`lua/instruction_executor.lua:90` → `if evidence.site~=JSON.null then used[...]=true end`). Everything else
(`step>last_step`, hold at arm/finish, exactly one frame, one consumption per challenge) already holds per
derived frame. `battle_force_authority.lua` unchanged.

### 2.3 Return: minimal exact evidence in the bundle

`close_range` (`:266-267`): when `active.instruction` exists,

```
bundle.instruction = {
  schema    = "slink-instruction-window-evidence-v1",
  challenge = active.instruction.authority.challenge,
  first     = active.before,                 -- first armed frame == receipt.before
  armed     = active.instruction.armed,      -- frames armed with this challenge: 0..receipt.steps
  reached   = <slink-instruction-evidence-v1 row> | null   -- the single reached row (site != null)
}
```

Why this form and not one row per frame: every unreached row is fully implied — `not_reached` rows carry
no state (`instruction_authority.py:87-90`) — so `armed` + `first` reconstruct them exactly, and the one
reached row is the only thing with bytes in it. Bounded: one row per window, whatever `steps` is (≤60).
It is inside `bundle`, so `receipt.observations_digest=sha(bundle)` (`:274`) already binds it and
`complete()`'s digest check (`gen1_frame_runtime.py:207-210`) already verifies it.

### 2.4 Server checks root must add

* `gen1_frame_runtime.bundle_boundary` (`:66-68`): admit `'instruction'` in the optional key set; shape
  `set(row)=={schema, challenge, first, armed, reached}`, `schema` exact, ints ≥ 0, `reached` None or dict.
* `battle_force_authority.verify_window(authority, instruction, closed)` → `verify_evidence` verdict
  `{'outcome','site','reason','frame','step'}`:
  `instruction['challenge']==authority['challenge']`; `first==closed['receipt']['before']==authority['frame']`;
  `0<=armed<=closed['receipt']['steps']`; `reached is None ⇒ armed==steps, outcome 'not_reached'`;
  `reached ⇒ reached['frame']==first+armed-1` (the reached frame is the last armed one) and
  `verify_evidence({**authority, 'frame': reached['frame'], 'step': authority['step']+armed-1}, reached)`.
  Coverage is thus `covers(closed, reached['frame']+1)` by construction (`frame_progress.covers:212-216`,
  `before < f+1 <= after`).
* `gen1_frame_journal.returned` (`:427-431`): after `complete()`, `original=_original_grant(runtime, player,
  closed['grant']['scope']['operation_id'])[1]['result'].get('instruction')`;
  `(bundle.get('instruction') is None) != (original is None)` → `JournalError('frame instruction evidence
  differs from its grant')`; else `verdict=gen1_faint_runtime.enforce(...)` (§3) and
  `result['instruction_outcome']=verdict['outcome']`, plus `result['instruction_digest']=digest(death['enforcement'])`
  when `fainted|benched`.
* `_grant_value` (`:63-102`): when `value['result']` has `instruction`, require
  `battle_force_authority.verify_issued(authority, command=runtime.journal.command(player,
  authority['scope']['operation_id']), scope_binding={context_generation, binding_digest} from
  proof.scope, ledger=previous['ledger'])`: scope reproduces via `command_scope(command, …,
  phase='battle_force_faint')`; `frame==ledger['frame']`, `step==ledger['steps']+1`,
  `challenge==digest({'frame_grant': operation_id, 'death_id': body['death_id']})[:32]`,
  `proof_digest==digest({'death_id','key','member'(4 fields),'host','variant'})` (the exact `proof` dict of
  `prepare`, `battle_force_authority.py:172`), `uses==1`, `held is False`, `binding==BINDING`,
  `sites==sites(variant)`, `addresses==ANCHORS[variant]['addresses']`, `hook_frame_offset==HOOK_FRAME_OFFSET`;
  then `expected_result['instruction']=authority`. `_checked_record` (`:38-46`) needs no new key —
  the authority rides `result`.
* `verify_journal` frame_complete branch (`:197-277`): mirror the acquisition clause (`:243-248`) —
  if the original grant carried `instruction` or the bundle has one: recompute `verify_window`,
  `expected_result['instruction_outcome']`, and when fainted/benched require
  `deaths[death_id]['enforcement']['origin']==event_reference.make(player, operation_id, message)`
  (`server/event_reference.py:21-25`) and `expected_result['instruction_digest']=digest(enforcement)`.
* Required result keys: `instruction_outcome` present iff the grant carried an authority;
  `instruction_digest` present iff `instruction_outcome in {'fainted','benched'}`.

---

## 3. Ownership / authority invariants (state them; most already hold)

1. Same owner: `authority.owner_id == initial.gen1_metadata.physical_instance == boundary.host.owner_id`
   (`gen1_frame_runtime.py:43-46`, `gen1_held_faint.py:92`); the executor refuses any other owner
   (`instruction_executor.lua:61`) and the server refuses evidence from another (`instruction_authority.py:80-81`).
   The executor never touches the hold: it registers bus-exec hooks (`:68-72`) and writes only inside the
   frame the owner released; a hook while held latches (`:32`, `:54`).
2. Steps come from the owner's counter: `authority.step = ledger.steps+1`, per-frame
   `step_f = step + (f-frame)`; client asserts `== bounded.status().steps+1` at accept and `==
   checkpoint.steps+1` inside `authorize`. Invariant to confirm live: `ledger.frame-anchor.frame ==
   bounded.status().steps` at all times (owner created at `gen1_client_entry.lua:65` before enrollment;
   native frames go through the same owner, `:136,:165`, and are folded into the ledger).
3. Hold verified at arm and finish for every stepped frame (`instruction_executor.lua:65,:80`); exactly one
   frame between (`:81`); one consumption per challenge (`:42`, `:90` as amended); frame equality per arm (`:66`).
4. `held_write_permit` untouched: no `VerifiedHeldWrite`, no `slink-held-write-permit-v1` packet;
   `gen1_held_faint.verify` keeps `battle_flag==0` (`server/gen1_held_faint.py:71`). Already pinned by
   `tests/unit/test_battle_force_bypass_and_fallback.py:283` (`instruction modules never touch the permit`).
5. Death lifecycle owner stays `gen1_faint_runtime`. Recommended (minimal): **the phase stays
   `pending_faint`**; a verified `fainted|benched` row records
   `death['enforcement'] = {origin, frame, step, site, outcome, evidence_digest}` (optional key, like
   `deferred`, `verify_state:315,356-384`). The transition `pending_faint → pending_memorial` remains
   `acknowledge()` (`:229-232`), reached when the peer's overworld held faint finds HP already `0000` and
   ACKs the proven no-op (`gen1_force_faint_executor.lua:43-44`, `gen1_command_receipts.py:75-80`) — the
   same receipt shape acknowledge needs for party/rules refresh (`:233-248`) and memorial scheduling
   (`:250-254`). Reasons: acknowledge needs the overworld `receipt.after` party snapshot the battle row
   cannot supply (inventory is null in battle, `gen1_client_entry.lua:153`), and the one-obligation invariant
   (`verify_journal:502-513`) holds unchanged.
   Alternative if root wants an explicit phase: `battle_enforced` (receipt_event None, command outcome None),
   accepted alongside `pending_faint` in `verify_state:347-355`, `verify_journal:511`, `acknowledge:229`,
   `gen1_held_faint.verify:63`, `schedule_deferred` untouched — six touch points instead of two.
6. Re-issue: `pending_instruction` returns an authority whenever the oldest pending command is a force_faint
   with a `pending_faint` death without `enforcement`; `refused`/`not_reached` windows therefore re-issue on
   the next request automatically. `fainted|benched` stops issuance (`enforcement` present).
7. Bypass paths (RUN, Poké Doll, capture) never reach a site (`BATTLE_FORCE_FAINT_WINDOW.md:333-344`); the
   window returns `not_reached`, the battle ends, the peer reaches the overworld checkpoint and the existing
   `gen1_held_faint` path settles the death unchanged.
8. Ordinary/native exclusivity: no authority while native-borrowed or in a trade (`gen1_frame_control.py:28-29,:46`).

---

## 4. Blockers and unknowns (honest)

0. **Frames are not issued at all in the state a death exists.** `issue_for_control` returns None once any
   player has Poké Balls (`server/gen1_frame_control.py:51-54`), while any command is pending for either
   player (`:47`), or while any barrier blocker is not the initial hold (`:48`); `grant` refuses pending
   commands too (`gen1_frame_journal.py:376-377`). A death requires `pokeballs_obtained` (`gen1_faint_runtime.py:122`)
   and adds a `REASON` blocker (`:188-190`) plus a pending command. Root policy needed: (a) lift the
   pre-ball gate; (b) in `:47` and `grant:376` allow a pending set consisting only of `force_faint`
   commands whose deaths are `pending_faint` (and, for the requesting player, the instruction names
   `pending[0]`); (c) in `:48` allow blockers equal to `gen1_faint_runtime.REASON` for deaths in
   `pending_faint`. Any other pending command or blocker keeps today's refusal (memorial phase stays held).
   Whether the killer's side (player without the pending command) also keeps stepping is a policy choice;
   the ledger is per-player so either works.
1. **Client freeze on pending commands (likely a live deadlock today).** `commands_pending()`
   (`lua/gen1_frame_client.lua:146-150`) blocks `request` (`:183`), `authorize` (`:242`) and `step`
   (`:312-319`) while ANY inbox command lacks an outcome. A force_faint delivered while the peer is in a
   battle can never become ready (`safe()` needs `isPartyWriteSafe()`, `lua/gen1_held_faint.lua:38-40,:128`),
   and no frame can advance to leave the battle. Fix inside this proposal: `commands_pending()` ignores
   entries whose wrapper `body.cmd=="force_faint"` (`gen1_runtime.unwrap`, `lua/gen1_runtime.lua:38-44`);
   ordering is preserved because the router tries the held-command service first (`gen1_client_entry.lua:196-199`)
   and it takes over as soon as `safe()` is true.
2. **Executor one-use rule** (`lua/instruction_executor.lua:90`) must become "used when reached", or every
   frame after the first would need a distinct challenge. One line; the negative tests at
   `tests/unit/test_battle_force_authority.py:476` (`a_finished_challenge_cannot_be_rearmed`) must be split
   into reached (still refused) vs not_reached (re-arm allowed for a later frame).
3. **Owner step counter vs ledger** (§3.2) is asserted, not yet measured across a native handoff.
4. **Stale slot**: the member slot comes from the last settled inventory row; a party reorder inside the
   range that entered the battle is not observed (inventory null in battle). `decide()` refuses safely
   ("party slot is not the linked mon", `battle_force_authority.py:134-137`) and the window re-issues with
   the same slot until the battle ends → overworld fallback. In-battle Gen 1 has no party reorder.
5. **Unverified live branch**: the active-mon write at `ExecutePlayerMove+0` (`player_action`) under
   `step_one` — proven only under the harness owner (`BATTLE_FORCE_FAINT_WINDOW.md:442-447`). `loop_head`,
   benched and Transform branches are live-verified under the bounded owner (§11).
6. Fail-closed coupling: an executor latch (`instruction_executor.lua:54`) makes the next `arm` throw inside
   `step`'s pcall → `self.failed` → the frame client stops (`:351`). Consistent with the rest of the client;
   root should decide whether a latched executor should instead drop the authority and report it.
7. Crash after `step_one` but before `save` (`:326-340`) loses a reached row after the bytes landed: the
   existing "physical frame differs" assertion (`:112`) already fails the client; a later window refuses
   `already fainted`; the overworld no-op ACK still settles the death. No new hazard, but a lost row.
8. The `instruction` field on the grant is not covered by the client's `proof_digest` check (`:159`); the
   client trusts the authenticated control response as it does for the window itself, and the executor's
   structural asserts plus the accept-time frame/owner/step checks bound what it will arm.
9. Bundle size: one ~700-byte row per window; no limit is approached (`acquisitions` already allows 16 rows).
10. `HOOK_FRAME_OFFSET=0` is pinned for BizHawk 2.11.1 Gambatte only (`battle_force_authority.py:51-55`).

---

## 5. Minimum diff list (root's files) and tests

| File | Function | Add | ~lines |
|---|---|---|---|
| `server/battle_force_authority.py` | new `pending_instruction`, `verify_issued`, `verify_window` | §1, §2.4 | 65 |
| `server/gen1_frame_control.py` | `issue_for_control` `:47-54` | relaxed pending/blocker gates (policy), lift pre-ball gate; call `pending_instruction`, pass to `grant`, merge into returned `frame_window` | 15 |
| `server/gen1_frame_journal.py` | `grant` `:355,:376-377,:408`; `_grant_value` `:95-100`; `returned` `:427-431,:509`; `verify_journal` `:273-277` | `instruction=` kwarg; pending relaxation; result key; `verify_issued`; `enforce` call + `instruction_outcome`/`instruction_digest`; replay clause | 40 |
| `server/gen1_frame_runtime.py` | `bundle_boundary` `:66-68` | admit + shape-check `bundle['instruction']` | 8 |
| `server/gen1_faint_runtime.py` | new `enforce(runtime, stage, document, player, operation, message, closed, authority)`; `verify_state` `:315,:356`; `verify_journal` `:502-513` | record `enforcement` once; optional-key validation (`event_reference.validate(origin)`); resolve origin to a `frame_complete` of `death['peer']` whose result `instruction_digest==digest(enforcement)` | 40 |
| `lua/instruction_executor.lua` | `finish` `:90` | mark used only when reached | 1 |
| `lua/gen1_frame_client.lua` | `commands_pending` `:146-150`; `accept` `:224`; `authorize` `:248`; `step` `:326-327`; `close_range` `:266-267` | force_faint exemption; pop/validate/persist `instruction`; step/frame cross-check; arm/finish; `bundle.instruction` | 35 |
| `lua/gen1_client_entry.lua` | `begin` after `:69`; `Frames.new` `:135`; `close` `:293` | `self.instruction=require("battle_force_authority").new{owner_id=instance, held=function()return self.host.status().physical_stop_verified==true end}`; `instruction=function()return self.instruction end`; `self.instruction.close()` | 5 |
| `server/gen1_launcher.py` `:20` | file manifest | ship `lua/instruction_executor.lua`, `lua/battle_force_authority.lua` | 1 |

Unchanged: `server/instruction_authority.py`, `lua/battle_force_authority.lua`, `server/gen1_held_faint.py`,
`server/held_write_permit.py`, `lua/held_write_permit.lua`, `lua/durable_runtime.lua`, `lua/control_service.lua`,
`lua/platform_bounded_execution.lua`, `lua/execution_window.lua`, `server/frame_progress.py`.

Tests root should expect (unit unless noted):

* `test_battle_force_authority.py`: `verify_window` — not_reached (`armed==steps`), reached at the last armed
  frame, reached not last → refused, `armed>steps` → refused, `first!=before` → refused, foreign challenge →
  refused; `pending_instruction` — oldest pending force_faint + `pending_faint` death + party slot → authority
  with `frame/step/challenge` as specified; None when boxed, when `enforcement` present, when oldest pending
  is another command; `verify_issued` refuses a tampered `frame`, `step`, `member`, `sites`, `challenge`.
* `test_gen1_frame_control.py` / `test_gen1_frame_journal.py`: grant carries `instruction` and replays it
  byte-identical; `_grant_value` refuses a mutated authority; `returned` refuses `bundle.instruction`
  without a grant authority and vice versa; `verify_journal` reproduces `instruction_outcome` and
  `instruction_digest`; a pending non-force_faint command still refuses grants; pending force_faint with
  `pending_faint` death is granted (both players per the policy chosen).
* `test_gen1_faint_runtime.py`: `enforce` records `enforcement` once and refuses a second row; refused /
  not_reached windows leave the death untouched and the next request re-issues; `acknowledge` still moves
  `pending_faint → pending_memorial` with `enforcement` present (no-op receipt); `verify_state` accepts /
  refuses the `enforcement` shape.
* `test_battle_force_bypass_and_fallback.py`: a window whose battle ended by RUN returns `not_reached` and
  the overworld `gen1_held_faint.verify` path is what settles the death.
* Lua (`lua/tests`, lupa): executor re-arms the same challenge after `not_reached`, refuses after reached;
  frame-client `commands_pending` exemption; bundle `instruction` shape.
* Live/duo (`tests/live/test_gen1_battle_force.py` extension): death delivered while the peer is mid-battle →
  frames keep stepping → `fainted` row in the closing bundle → black-out → overworld no-op ACK → memorial;
  and the still-open `player_action` active write under `step_one`.
