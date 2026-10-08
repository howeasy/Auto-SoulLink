# Polished plain-faint post-copy observer

Design only, 2026-10-07. Reviewed repository cut:
`766935aaec752b0d1a2e3b1d88587b4e7c55bc7b` (`claude/pol-docs3`).
All repository citations below are relative to `F:/slink-work/wt/pol-docs3` at
that cut; `SRC/` means `F:/slink-work/cache/polished/src/`. Proposed interfaces,
rows, cards and acceptance tests are requirements, not implemented behavior.
Only this document is changed. No runtime opt-in or release authority is granted.

## 1. Contract and evidence boundary

The missing producer must emit an internal `kind="observation"`,
`site_id="battle_faint"`, `phase="after_party_copyback"` event, carrying a frozen
`capture={identity,generation,epoch,visit,key,attempt_seq,seq}` and
`battle={slot,hp=0,status=0,link_mode=0,fainted=true}`. The existing consumer also
requires current native FAINTED/HP/status and exact keyed party readback, then
a later **sent** party-bearing HP-zero tick before completion. Neither the
observer nor a successful enqueue completes the obligation
(`lua/gen2/client.lua:1296-1359,1760-1761,1985,2379-2384`).

The current producer at 44C8 provides no binding or FAINTED/status evidence and
has phase `before_party_copyback`; it cannot satisfy that contract
(`lua/gen2/signals.lua:1467-1476`). F2b's positive test constructs the future
witness directly, including a call to the FS clock; that is MODEL evidence,
not a producer (`tests/unit/test_polished_faint_client.py:150-160,181-184`).

The design of record proposes both pre-copy and post-copy observations and
explicitly rejects HP mirrors alone as proof (`docs/polished/PLAIN_FAINT_F2.md:266-298`).
This card implements the merged consumer's narrower requirement: a freshly bound
post-copy witness followed by its later tick. Do not register the pre-copy site
merely to claim the two-site design was implemented. Preserve it as a probe
corroborator; if mandatory pre/post pairing is desired in production, that is an
additional consumer requirement and separate lease, not already enforced by
`FS.observe` (`lua/gen2/client.lua:1331-1359`).

## 2. Exact native witness

The native source calls `FaintUserPokemon` for both sides when first-faint order
is nonzero, restores the saved turn, then calls player copyback and enemy
copyback in sequence (`SRC/engine/battle/core.asm:708-730`). The player-copy
routine has no conditional early return: it resolves `wCurBattleMon`, copies
from `wBattleMonLevel` through the bytes before `wBattleMonMaxHP`, and returns
(`SRC/home/battle.asm:230-240`). This copies level, status, unused and current HP;
it does not copy max HP. Native faint handling clears status and sets
SUBSTATUS2 FAINTED (`SRC/engine/battle/core.asm:2099-2107`).

| Bank:PC | Bytes | Instruction / significance |
|---|---|---|
| 0F:44C7 | F1 | `pop af`, `.no_fainted_mons` symbol |
| 0F:44C8 | E0 D1 | `ldh [hBattleTurn],a`, existing pre-copy site |
| 0F:44CA | CD B0 34 | `call UpdateBattleMonInParty` |
| **0F:44CD** | **CD C3 34** | `call UpdateEnemyMonInParty`; player copy has returned |

Evidence: `data/polished/polished_slink.sym:10452` places the local label at
44C7; `:1103-1104` place the callees at ROM0:34B0 and ROM0:34C3.
`tools/polished_live/faint_probe.py:73-101` independently derives and checks the
CALL encodings and return-site address. Direct PowerShell byte read during this
doc card returned `F1-E0-D1-CD-B0-34-CD-C3-34` from release ROM offset `0x3C4C7`.
`Get-FileHash -Algorithm SHA1` returned
`6930b48af5844d373e3c9130f26d6dd1084cf4ed`, matching
`data/polished_sources.lock.json:9-14`. Source HEAD read with a command-local
safe-directory setting was `3fa43192379df5c3e7b09a08e4d5d79af4f02f42`, also the
lock's source pin. No global Git setting was changed.

Proposed physical site ID: **`battle_faint_copyback_return`**. Its CPU anchor is
bank 15, address 17613 (`0x44CD`), flat offset 246989 (`0x3C4CD`), length 3,
`expected_hex=find_hex="CDC334"`, symbol and sym_anchor
`ResolveFaints.no_fainted_mons`, symbol_offset 6. It is an observation, never a
write window. The existing `battle_faint` and `battle_faint_copyback_call` rows
retain their meanings (`tools/gen_polished_engine_sites.py:146-158`).

Why this witness is useful: on the pinned native control path, reaching 44CD
means the immediately preceding unconditional player-copy CALL returned.
44C8 or 44CA alone cannot prove that. Reaching 44CD is **not faint-only** because
the no-faint path also reaches both calls; require the full captured/native
FAINTED, HP, status, slot and identity predicates. This is a native control-flow
witness, not proof against arbitrary debugger PC injection, visible animation,
audio, or save durability (`SRC/engine/battle/core.asm:715-730`;
`docs/polished/PLAIN_FAINT_F2.md:289-296`).

The recorded F3 run supports callback PC equal to hook PC at 44C8/44CA/44CD,
all in bank 0F, ordered 44AF -> FaintUserPokemon -> 44C8 -> 44CA -> 44CD.
However, its player HP was 159 and FAINTED was clear: it exercised enemy-side
faint, not a player plain-faint completion. This card read the report, not the
original trace (`docs/polished/LIVE_RESULTS.md:720-746`).

## 3. Generated pack change

Hand-edit `tools/gen_polished_engine_sites.py`, then generate the JSON:

1. Add `S("battle_faint_copyback_return", "player_faint",
   "ResolveFaints.no_fainted_mons", "after_party_copyback", ...,
   symbol_offset=None, anchor="ResolveFaints.no_fainted_mons", find_hex="CDC334")`.
   Do not supply a manually trusted PC: `find_in_extent` must find exactly one
   match and derive the offset (`:119-129,352-366,380-401`). For this cut the
   extent is 44C7..<44E3 (clean sym `data/polished/polishedcrystal.sym:10439-10440`);
   a direct ROM scan found one match at flat 3C4CD.
2. Add a `PROOFS` entry encoding `call UpdateEnemyMonInParty` as
   `b"\xCD" + _le(sym["UpdateEnemyMonInParty"][1])`, with a ROM0 assertion.
   Include point symbols `wBattleMode`, `wCurBattleMon`, `wLinkMode`,
   `wBattleMonHP`, `wBattleMonStatus`, `wPlayerSubStatus2`. Existing proof
   generation re-encodes instructions and emits bank/address pairs
   (`:53-70,402-410`). Also assert the immediately preceding three bytes encode
   the ROM0 `UpdateBattleMonInParty` CALL and that this row equals its existing
   copyback-call row plus 3. Finding the enemy CALL alone must not certify a
   reordered or intervening instruction sequence.
3. Regenerate `data/games/polished_crystal/engine_signals.json` with the existing
   wrapper: `CPU_INSTRUCTION`, `RESOLVED`, `OBSERVATION`, `SOURCE_CANDIDATE`,
   `physical_firing="OPEN"`, `runtime_enabled=false`, `runtime_admission="NOT_GRANTED"`,
   `f3_complete=false`. `expected_hex` must be ROM-derived, and its complete
   three-byte span must avoid overlay changes (`:369-430`). The current counts
   53 total / 41 resolved / 12 unresolved become **54 / 42 / 12**
   (`data/games/polished_crystal/engine_signals.json:19-21`).
4. The generator writes/checks **both** engine_signals and write_checkpoint
   (`:519-548`). Adding a SITES/PROOFS row does not change `build_checkpoint`
   (`:434-496`), so with identical ROM/UPS inputs **write_checkpoint must remain
   byte-for-byte unchanged**. Do not add a write gate for this observer. Both
   committed packs currently contain 28 companion overlay spans (PowerShell
   JSON census); that count must remain 28. The test pin is
   `tests/unit/test_gen_polished_engine_sites.py:79-86`, not a site-count pin.
   Any changed span count indicates changed inputs and needs separate review.

Pack verification already covers ROM bytes, overlap, old faint/call anchors,
round-trip generation and unique-match failures
(`tests/unit/test_gen_polished_engine_sites.py:63-107,138-185,213-242`). Add explicit
new-row identity, 54/42/12 census, adjacency, instruction proof and point-symbol
checks there; existing tests use lower-bound counts, not an exact full site set
(`:63-65,89-91`). Test the point pairs against **both** clean and overlay symbols,
including SUBSTATUS2; the generator uses the clean sym (`tools/gen_polished_engine_sites.py:72,522`),
while the composition's profile comes from overlay symbols
(`tools/gen_polished_profile.py:3-7,376-410`).

## 4. Callback producer and private FS binding

### Registration and event identity

Extend only `S.new_polished`'s allowlist with
`battle_faint_copyback_return="after_party_copyback"`. Validate the new row's
status/phase/bytes like the other opted-in battle sites and validate its
instruction proof and every required point pair. Where the profile has the
same symbol, require identical bank/address; required missing row points refuse
registration. Existing battle rows do not currently receive the capture-party
instruction-proof validation, so add this validation specifically for the new
row (`lua/gen2/signals.lua:1348-1366,1396-1410`).

Use the existing `binding:validate` / `binding:register` path with
`capture_offset=0`. It registers System Bus execution at 44CD; callback context
must observe `hROMBank` at FF87 equal to **0F**, PC equal to 44CD, and matching
executed bytes. Wrong-bank hits return before any stamp or FS sequence
allocation (`lua/gen2/signals.lua:1384-1385,1489-1508`;
`lua/gb_hook_binding.lua:36-78`; sym `:70191`).

Keep physical registration ID `battle_faint_copyback_return` for hook ownership,
status and refusals, but deliberately map this one producer's event to
`site_id="battle_faint"` and add `source_site_id="battle_faint_copyback_return"`
for diagnostics. Preserve `phase="after_party_copyback"`. Without that mapping
the current client ignores it (`lua/gen2/client.lua:1760-1761`); do not rename
or repurpose the old pack row. Use the existing DEV batch envelope and evidence
labels (`lua/gen2/signals.lua:1432-1443,1540-1548`).

### Read at callback time, with bank validity

Use **this new row's generated point_symbols**, not capture_party's points or
hard-coded fallback addresses. The required coordinates, independently present
in `data/polished/polished_slink.sym`, are:

| Field | Symbol, bank:address | Decode | Sym line |
|---|---|---|---|
| mode | wBattleMode, 01:D233 | 1 or 2 required | 66193 |
| slot | wCurBattleMon, 01:D0DA | zero-based; occupied party slot | 65872 |
| link_mode | wLinkMode, 00:CEC1 | must be 0 | 65628 |
| hp | wBattleMonHP, 00:C4B8..C4B9 | **big-endian**, first*256+second | 64021 |
| status | wBattleMonStatus, 00:C4B6 | must be 0 | 64017 |
| fainted | wPlayerSubStatus2, 00:C4E2 | `(byte & 0x04) ~= 0` | 64056 |

SUBSTATUS_FAINTED is bit 2 (`SRC/constants/battle_constants.asm:213-217`),
consistent with `lua/gen2/polished_explode.lua:262-268`. Do not use
`wPlayerSubStatus1`. Do not reuse `signals.lua`'s current two-byte `wram` helper:
it returns little-endian (`:1418-1430`), while native HP is big-endian. A zero-only
test hides this mistake; require a nonzero asymmetric-byte red control.

For each read require `io.bank_valid(point.bank,point.addr,length)` before and
after, then validate byte values. This follows the existing guarded-reader
pattern (`lua/gen2/polished.lua:479-488`). In particular, WRAMX slot/mode/party
must be mapped to bank 1; ROM bank 0F alone says nothing about WRAMX validity.
Do not switch banks, write RAM, or change CPU registers to make a read succeed.

The profile currently lacks `wPlayerSubStatus2` (PowerShell/rg field census of
`data/games/polished_crystal/profile.json`), so the proposed point-symbol proof
is necessary; blindly calling existing profile-only `wram` would refuse the
observer (`lua/gen2/signals.lua:1418-1421`). This choice avoids an unrelated
profile-generator/artifact change. The existing settlement reader already has
a separately pinned coordinate (`lua/gen2/polished_explode.lua:81-86,124-125`).

### The client owns the capture clock and attempt selection

Add an optional **client-owned** authority method, proposed name
`authority.capture_faint(battle, held)`, only inside the `settle`/FS branch.
It is passed through the existing signals factory's authority argument, not a
public setter, wire field, dependency-supplied counter, or writable FS reference.
Current authority exposes only epoch capture/validity and is passed to the
factory during start (`lua/gen2/client.lua:1992-2004`).

At the qualified CPU callback, the new binder process branch must:

1. Capture existing operation authority and read all battle fields above.
   Reject unavailable reads, invalid battle/slot, link mode, nonzero HP/status
   or FAINTED clear. Require the optional `capture_faint` function when this
   physical site is requested; missing capability refuses registration.
2. Invoke that function **synchronously**, passing the copied battle snapshot
   and held stamp. It must require not suspended, valid held epoch, current
   battle visit and exactly one current-generation `awaiting` **plain** owner
   whose latest attempt matches slot, epoch and visit. Resolve its logical key
   through the existing keyed party lookup, reject ambiguous/absent/egg or
   changed physical identity, and require actual party HP/status zero. Do not
   replace the attempt's slot/key with whichever mon occupies the slot now.
   These mirror the consumer guards (`lua/gen2/client.lua:1331-1355`) and owner
   identity established at dispatch (`:1223-1252`).
3. Revalidate the accepted save identity with `FS.check_identity(ob)` before
   and after the fresh target reads. Require `ob.identity == a.identity ==
   FS.last_identity`; failure returns no capture and retains the existing
   quarantine behavior (`:1091-1110`). Capture identity from this verified
   owner, generation from `ob.gen`/`FS.gen`, epoch from `a.epoch`/`self.epoch`,
   visit from `a.visit`/`FS.visit`, physical key from `ob.phys` verified against
   the newly decoded mon, and attempt_seq from `a.seq`.
4. Only after successful validation allocate `seq=FS.next_seq()` **now** and
   return a new scalar-only capture table. Require `seq > a.seq` and the
   evidence floor. Attempts, observer and ticks share this exact FS clock
   (`:1026-1029,1231-1233,1301,1348-1349,1372-1389`). Do not use framecount,
   `self.seq`, held generation, or a binder-local counter as the sequence.
5. Freeze capture and battle in one queued DEV batch. Registry capture already
   runs synchronously and deep-copies events (`lua/hook_registry.lua:83-93`).
   No owner/attempt table reference may escape. No field may be filled in or
   refreshed while draining. The existing drain assigns only batch_generation
   from the captured envelope (`lua/gen2/client.lua:2379-2383`); retain that.

The capture method does not call `FS.observe`, complete, arm a permit or send a
message. Consumption remains `FS.observe` followed by the existing later sent
tick, with a fresh native and party readback (`lua/gen2/client.lua:1299-1359`).
No eligible owner means no event; it is not an encounter refusal. Existing
binder refusals count acquisitions only for capture_party (`signals.lua:1511-1519`).

Keep both generation dimensions distinct: batch.generation and capture.epoch
are the client's epoch; capture.generation is FS identity generation. Identity
change increments both and abandons queued batches; suspension raises the
sequence floor; timeline abandonment/lifecycle boundaries quarantine staged
attempts (`client.lua:1372-1389,1405-1434`). `S.new_polished:boundary` currently
preserves queued captures while `abandon` drains them (`signals.lua:1526-1538`).
Do not rely on boundary flushing: test the existing state/epoch rejection even
when an old batch survives until drain. No delayed event gets rebound.

## 5. Composition and vanilla isolation

In `compose_polished` only, compute the opt-in once from
`deps.polished_active_faint == true`. When true, pass
`battle_sites={"battle_faint_copyback_return"}` to `Signals.new_polished` and
supply the same settlement interface already selected for the client. When
false, omit battle_sites exactly as today. The authority method arrives via
`signals(authority)` once Client:start has constructed its authority; no cyclic
client reference is needed (`lua/gen2/entry.lua:827-834,919-935`;
`lua/gen2/client.lua:1992-2005`). Do not add the pre-copy, battle_end, rival or
explode sites here. The hold already has its separate hook.

Existing default assertions must remain unchanged and green:

- `tests/unit/test_polished_sites.py:136-146`: capture_party, checkpoint and
  battle-hold hooks; binder registered_sites exactly capture_party.
- `tests/unit/test_polished_client.py:209-223`: the same allowed default hooks
  and no guest writes.
- `tests/unit/test_polished_battle_sites.py:285-300`: its explicit six-site
  battle request remains the same seven hooks including capture_party. Extending
  the allowlist must not auto-register the new row.

Add a separate enabled-composition assertion: the default three hooks plus
`SLink-gen2-polished:battle_faint_copyback_return` at 44CD, and binder IDs exactly
capture_party plus the new row. Corrupt/missing new row must degrade to the
existing inert binder with diagnostic and **never** turn missing evidence into
completion (`entry.lua:821-834`; `client.lua:1395-1399`).

Vanilla isolation rests on capability absence, not title checks scattered in the
consumer: vanilla composition supplies no active_faint_settlement, so FS and
its proposed authority method are absent; the new registration is confined to
S.new_polished and compose_polished (`client.lua:968-977`;
`entry.lua:923-926`; `signals.lua:1302-1305`). Do not change generic hook binding,
registry, vanilla packs, write permits, protocol or server for this observer.
Keep the interface-absent differential and its leaky-branch red control
(`tests/unit/test_polished_faint_client.py:794-819`). That test is a shared-client
harness comparison; it does not substitute for real Crystal/Gold/Silver ROM
qualification.

## 6. Implementation cards and acceptance tests

Each numbered card is sequential and exclusively owns the listed files for its
lease. Re-pin against the merged predecessor before starting; no overlapping
file leases. Paths are relative to the repository root named above. New test
filenames below are proposals, not existing files. Each card has at most three
files. Generated output is never hand-patched.

| Order | Exclusive files | Work and acceptance |
|---|---|---|
| A | `tests/unit/test_gen_polished_engine_sites.py` | Hand-written red tests for new row, exact counts, adjacent CALLs, proof/points and clean/overlay symbol equality. Preserve 28-span pin and old anchors. |
| B | `tools/gen_polished_engine_sites.py`; `data/games/polished_crystal/engine_signals.json`; `data/games/polished_crystal/write_checkpoint.json` | Hand-written generator; regenerate both artifacts, checkpoint expected no diff. Make A green; generator `--check` and existing determinism/drift controls. |
| C | `lua/gen2/client.lua`; `tests/unit/test_polished_faint_client.py` | Hand-written private capture authority and unit coverage. Test real authority callback, no direct FS clock manufacture in the new positive case. Keep existing consumer contract and vanilla trace controls. |
| D | `lua/gen2/signals.lua`; `tests/unit/test_polished_faint_observer.py` (new) | Hand-written allowlist, point proof/readback, event mapping and synchronous capture. Binder/registry tests with explicit opt-in and stub authority; existing battle-site tests unchanged. |
| E | `lua/gen2/entry.lua`; `tests/unit/test_polished_faint_observer_composition.py` (new) | Hand-written opt-in composition, real binder -> private FS -> consumer -> sent tick test. Enabled/disabled hook census; missing/invalid pack degradation. |
| F | `tools/polished_live/faint_probe.py`; `tools/polished_live/faint_probe.lua`; `tests/unit/test_polished_faint_probe.py` | Only if needed, separately resolve the known fixture/footer and trace-encoding blockers with preservation/counter tests before a granted live lane. No observer implementation belongs in the recorder. |
| G | `docs/polished/LIVE_RESULTS.md`; `docs/polished/FAINT_OBSERVER.md` | After separately granted live execution, record exact receipt paths/hashes, failures and qualification limits. Lane artifacts stay in the separately granted private evidence directory. |

Required red controls (requirements derived from consumer guards at
`client.lua:1331-1355`, lifecycle at `:1372-1434`, and binder at
`signals.lua:1489-1519`):

- Wrong ROM bank at PC 44CD: no event and no FS clock increment. Wrong PC or
  instruction bytes must fail binding; missing/wrong point symbol refuses.
- Wrong WRAMX bank or unavailable byte: no capture. Big-endian test uses HP
  bytes `01 02` (258, not 513); nonzero HP must not complete. FAINTED tests
  distinguish SUBSTATUS1 from SUBSTATUS2 and other bits from bit 2.
- Pre-copy-only 44C8 plus F1-written zero mirrors plus later sent HP-zero tick:
  still awaiting, no COMPLETE. 44CA entry-only is also insufficient.
- Qualified 44CD without FAINTED, with nonzero status, link mode, wrong slot,
  duplicate key, physical replacement, no owner, partial/lost/stale owner,
  Explosion attempt or different visit: no witness/completion.
- Capture for identity A, change to B before draining, including equal-looking
  physical key and same frame: immutable A capture is dropped; cannot complete
  B. Also change identity before the CPU callback but before frame-end polling:
  capture must synchronously refuse/quarantine rather than use cached identity.
- Capture before suspension, resume same identity, then drain: old sequence
  must fail evidence floor. Reset/rewind/abandon with a queued event must not
  transfer it; preserve or explicitly account for the dropped batch.
- Valid same-frame attempt -> callback -> drain -> sent tick: strictly
  increasing shared sequences, one completion, no duplicate write. Callback
  alone, a held/unsent tick, or box-only safe event must not complete. Mutate
  source owner/battle tables after callback to prove queued snapshot immutability.
- Disable the new callback or remove its event: positive composition case must
  fail. Do not inject a handcrafted capture into that end-to-end MODEL test.

Run, in a Python-capable implementation lane, generator `--check` and focused
pytest files from A/C/D/E plus existing `test_polished_battle_sites.py`,
`test_polished_sites.py`, `test_polished_client.py`, `test_polished_plain_faint.py`,
`test_polished_plain_faint_engine.py`, and `test_polished_faint_probe.py` under
`tests/unit/`. These cover pinning, registration, F1/native behavior and probe
oracle separately; report skips and actual counts rather than importing prior
run totals. This document card ran no Python or emulator tests.

## 7. Live evidence plan and open items

Reuse `tools/polished_live/faint_probe.py`: it derives resolve/pre-copy/call/return,
FaintUserPokemon and LostBattle sites from pinned symbols and ROM bytes
(`:30-50,73-104`), checks qualified callback ordering and complete counters, and
labels PASS as recording rather than animation qualification (`:374-444`).
Use a separately granted emulator lane, private fixture/save copies, pinned
ROM/profile/sym/driver/route hashes, normal scripted inputs, and retain all failed
attempts. F2 requires these live prerequisites (`docs/polished/PLAIN_FAINT_F2.md:400-404`).

First reproduce the known callback ordering without producer writes. Then run
a **player** natural faint with positive starting HP, zero post-copy battle and
party HP/status, native player FAINTED set, correct occupied slot and a real
copy-return hit. Cover an enemy-only faint and a no-faint turn as negative
classification cases, and a last-mon/whiteout path to show native control flow
rather than an invented whole-party wipe. The current report provides only the
enemy-side case (`docs/polished/LIVE_RESULTS.md:733-746`).

Finally use the opted-in client in the same pinned lane, retain its real attempt,
callback capture and later sent tick evidence (identity/generation/epoch/visit/key,
attempt_seq < capture.seq < tick sequence), and prove exactly one completion.
The recorder's current PASS does **not** validate the new producer or FS clock;
its return test primarily flags missing natural faint handling for a particular
pre-copy-zero/order-zero path (`tools/polished_live/faint_probe.py:400-405,443-444`).
Keep recorder observation separate from the client writer's permitted actions;
retain wrong-bank hit totals and all failure verdicts. Add instrumentation only
under a separate explicit file lease if existing logs cannot expose this tuple.

**UNVERIFIED / gates:**

- No production producer, private authority method, generated return row or
  enabled composition is implemented by this card. All proposed positives are
  pending; the merged injected witness test is not their proof.
- This card verified release bytes, symbols and source HEAD, but did not apply
  UPS or independently hash/read the overlaid ROM. Future generation and tests
  must re-prove unchanged site bytes against the actual admitted overlay.
- Callback semantics have a documented DEV/SYNTH run, not a fresh trace audit
  here. Player-side zero/FAINTED at 44CD, actual attempt-bound same-frame
  propagation, and later tick completion remain live OPEN.
- The current F3 report records a 32790-byte fixture rejected by a 32768-byte
  check and trace JSON overflow from thousands of wrong-bank callbacks. Its
  successful run used a lane-local encoder-limit change. Resolve/record these
  before reuse; do not silently truncate the authoritative fixture or call a
  modified driver the committed driver (`LIVE_RESULTS.md:706,718-720,746`).
- Original F2 pre/post pairing remains a design/consumer mismatch explicitly
  scoped in section 1. This producer guarantees the merged post-copy contract;
  it does not add a pre-copy latch by implication.
- Real vanilla Crystal/Gold/Silver differential, long-run queue pressure,
  savestate timing and maximum witness delay are unrun here. Observer failure
  must leave pending evidence OPEN/awaiting or quarantined per existing policy,
  never infer success from a deadline (`client.lua:1395-1399`).
- Visible animation/audio, durable save, release/PHYSICAL admission and shared
  PARTIAL disposition/server protocol remain outside this observer's proof
  (`PLAIN_FAINT_F2.md:289-296`; `signals.lua:1540-1548`).
