# Gen 4 requirements — rev5 skeleton

Created by the owner's 2026-09-29 amendment request. Design: [Gen4 PLAN rev5](gen4/PLAN.md). Review cut: `7da76fbf`; review receipt: [adversarial review](gen4/reviews/ADVERSARIAL_REVIEW_2026-09-29.md). This is the requirement/evidence specification, not a worker ledger. The sole current grants/checkpoint remain in the coordinator's RC guide.

**All gate signatures are OPEN.** The amendment adds specifications and corrects research data; it does not execute production, MODEL, PHYSICAL or release gates. C0-1 still needs exact runner/test bindings and prerequisite pins before full G0 approval.

## Evidence and verdict rules

- S = SOURCE facts with pinned checkout/image provenance. FILE measurements identify exact bytes/ROM/save hash and method; they support the bounded source/layout claim, not live behavior.
- M = executed model/independent codec evidence. P = executed game/host evidence with the full bounded sequence and independent oracle. Research PHYSICAL is identified as research and is not a signed gate receipt.
- OPEN = missing or unrun required evidence; FAIL = a contradicted predicate or rejected present input. PASS needs an immutable receipt and independent review on the same cut. A named input skip remains OPEN and blocks its required artifact cell. No automatic PASS from reviewer agreement.
- N/A requires a source/owner-scope citation. D14 limits only special-mode **live** play; SOURCE+MODEL and mapping remain required. D3 is a non-shipping, emulator-free Pt bind; its real-save decode remains OPEN until provided.
- Every actual ENGINE receipt includes the owning overlay/image, full registration pin, four-byte fire word, site/frame and matched identity. Inactive wrong-overlay hits are dropped before byte comparison; an active-owner mismatch is a fault.

## Pins required before G0

The canonical implementation artifact is `data/gen4_sources.lock.json` (C0-2, not yet created). It must contain HG/SS/Pt SHA1+MD5/header, hge source/build SHA1+MD5 and exported-symbol hashes, xMAP commits/file SHA256/source correspondence, EmuHawk/melonDS/core file SHA256, exact battery/fixture/config hashes and generated-pack hashes. Source citation checkouts are explicitly separate from the newer xMAP origin. A one-byte ROM flip, changed config/build or missing input must invalidate the dependent verdict.

The bounded research pins are indexed in [research/README](gen4/research/README.md). They are input leads, not a substitute for the generated lock or a gate signature.

## X per-artifact obligations

| Artifact | Required site/image facts | Checkpoint/liveness | Required scenarios | Current blocker/evidence |
|---|---|---|---|---|
| HG clean | Declared ARM9/overlay pins; exact phase producer coverage | Field checkpoint plus legal in-battle two-copy seam and all refusal states | All D rows below, HG→SS | Generated pins/codec/clients/fixtures/gate runs OPEN |
| SS clean | Title-specific bytes asserted against HG; same ownership/persistence proofs | Same cells, independently exercised on SS | All D rows below, SS→HG | D4 owner save and all unrun gate cells OPEN |
| Hge `cb2dc435196d09c8c9209bf037240ed834f4cea1` candidate | Per-build replacement exports; correct ov12/130 image selection and extended data | Populated mon, actual dirty bit and hge legal battle mechanism | All D rows below, hge→hge | D15 two populated/distinct-trainer saves; generated packs/mechanism/duo OPEN |
| Pt bind only | Generated profile and different SOURCE/schema/model shape | Pt-shaped MODEL clauses; no runtime checkpoint qualification claimed | Profile bind and independent real-save decode only | Missing real save/offsets/model evidence OPEN; PHYSICAL N/A under D3 |

HG↔SS and SS↔HG plus hge↔hge are the exact permitted relation under D9. Same-foundation equality is not the full pairing policy. No new hash is admitted by this skeleton; a new hge build reopens build-bound cells.

## Required rows and independent oracles

Rows tagged HG/SS/hge apply independently to each artifact; scenario directions and hge build identity are part of the receipt. All statuses below are initial gate statuses, even when research already supplies useful SOURCE notes.

| ID | Requirement / scope | S | M | P | Oracle and first falsifier |
|---|---|---|---|---|---|
| F-1 | Lock/pins/tool/config provenance; HG/SS/hge, Pt-bind | OPEN | OPEN | OPEN | Independent file hashes; one-byte ROM/build/config change invalidates dependent receipt |
| F-2 | Declared image, replacement addresses and full registration/fire pins; HG/SS/hge | OPEN | OPEN | OPEN | Explicit image/id/extent lookup; expanded ARM9 overlapping ov12 cannot resolve to padding |
| F-3 | Save arrays, footer/bank/counter/CRC geometry; HG/SS/hge | OPEN | OPEN | OPEN | Independent codec and native cold reload; torn/coherence/counter-wrap controls |
| F-4 | Script+C acquisition producers and NPC reachability; HG/SS/hge | OPEN | OPEN | OPEN | Joined source inventory; removing C-only producer cannot pass on unchanged61 script hits |
| F-5 | Generated area/encounter/trainer/type/item/move tables; HG/SS/hge | OPEN | OPEN | OPEN | Independent source comparison, version/runtime branches retained; missing producer or wrong ID fails |
| F-6 | Qualified exact native battery fixtures; HG/SS/hge | OPEN | OPEN | OPEN | Continue→native SAVE→cold reload, counter/keys; missing save or identical hge trainers refuses qualification |
| F-7 | Pt profile/schema and real-save codec bind | OPEN | OPEN | N/A D3 | Different geometry/dirty/pointer clauses; real decode stays OPEN on blank save |
| R-1 | PK4 blocks/tail, shuffle, encryption flags and checksum; HG/SS/hge | OPEN | OPEN | OPEN | Lua versus independent codec; flipped box byte and locked-tail mismatch refused |
| R-2 | PID:OTID, slot/owner and duplicate ambiguity; HG/SS/hge | OPEN | OPEN | OPEN | Same-species/different-key wrong battler fails; sentinel6 never writable |
| R-3 | Loaded-save/SaveData/application pointer identity; HG/SS/hge | OPEN | OPEN | OPEN | Reacquired/range-checked chain plus save identity; early boot/epoch drift refuses |
| R-4 | Bag/balls/money/16badges/map/trainer/u16 names; HG/SS/hge | OPEN | OPEN | OPEN | Independent raw RAM/codec/source oracle; wrong-width/unknown fields fail visibly |
| R-5 | Battle geometry, local doubles/TAG0/2 and multi partner; HG/SS/hge | OPEN | OPEN | OPEN | Selected-slot and key match both copies; AI partner or wrong slot is excluded |
| R-6 | Hge populated-party/ability/dirty offsets | OPEN | OPEN | OPEN | Populated FILE decode and mutation/native persistence; two empty header candidates do not pass |
| S-1 | Hook callback/domain/residency/PC/pin contract; HG/SS/hge | OPEN | OPEN | OPEN | G1a–g controls; zero GUID, wrong overlay and active byte mismatch distinguished |
| S-2 | Phase activation, first/last event, drain/cleanup/fault lifecycle; HG/SS/hge | OPEN | OPEN | OPEN | G1n; queued last event survives once, failed unregister retains counted handles and surfaces fault |
| S-3 | Encounter begin/end/outcome identity through copy-back/blackout; HG/SS/hge | OPEN | OPEN | OPEN | Win→wild loss and consecutive losses; stale VAR cannot fabricate/miss outcome |
| S-4 | Capture/gift/starter/egg/daycare/PC-full attribution; HG/SS/hge | OPEN | OPEN | OPEN | Producer-shaped acquisition events and independent native readback; client writes never count as natural catches |
| S-5 | PC move/evolution/map/save settlement; HG/SS/hge | OPEN | OPEN | OPEN | Natural-input complete sequences, party/box/readback; boundary event cannot disappear at close |
| S-6 | Actual NPC exchange key_change and loan grants; HG/SS/hge | OPEN | OPEN | OPEN | Vanilla10 exchanges/2loans/1dormant; same-species exchange changes key; loans/dormant emit no false alias |
| S-7 | Field poison floor1/no natural poison faint; HG/SS | OPEN | OPEN | N/A cited source | Source/model floor1 behavior; reaching1 is not a faint event; hge source policy separately derived |
| S-8 | Contest result catch / Safari areas / extra roamer / static-gift policy; HG/SS/hge | OPEN | OPEN | LIMIT D14 | Kept bug counts at result, zone mapping and producer-shaped models; live limit does not erase semantic rows |
| W-1 | Field checkpoint forbidden states and liveness; HG/SS/hge | OPEN | OPEN | OPEN | No bytes in script/menu/save/app/setup-to-encounter-end; valid idle eventually reachable |
| W-2 | Both HP copies (live s32/4bytes, party u16/2bytes), legal seam, flags and measured latency; HG/SS/hge | OPEN | OPEN | OPEN | G1o independent game effect and full-width readback; single-copy/low-word-only/deferred-only paths fail, command11 alone not safety proof |
| W-3 | Eligibility/save+encounter epochs/held command/idempotency; HG/SS/hge | OPEN | OPEN | OPEN | Hold→disconnect/reset/wrong-save→seam has no bytes/success; duplicate commands apply one effect |
| W-4 | Partial batch fault and diagnostic receipt completeness; HG/SS/hge | OPEN | OPEN | OPEN | Failed second span revokes writes, missing/malformed/stale receipt fails; no rollback claim |
| W-5 | Native copy-back/healing/death persistence; HG/SS/hge | OPEN | OPEN | OPEN | No-heal win, status turn, loss+whiteout, NPC-follower win; pre-heal effect and later persistence separately observed |
| W-6 | Deposit/withdraw/memorialize/benched faint, dirty flag; HG/SS/hge | OPEN | OPEN | OPEN | Native SAVE/cold reload of records/stats/box bits; dirty-bit omission or incomplete tail goes red |
| W-7 | Following-Pokémon consistency; HG/SS/hge | OPEN | OPEN | OPEN | Natural follower/party behavior after writes; do not confuse walking mon with NPC-trainer healing flag |
| C-0 | Driver/protocol conformance using shared schema | OPEN | OPEN | OPEN | Gen4 world and sibling conformance runner; borrowed Gen3 blob fixtures cannot pass wrong shapes |
| C-1 | Hello/tick fields/admission/exact D9 pair relation | OPEN | OPEN | OPEN | Rejected title/foundation/artifact/save matrix leaves links.json byte-identical |
| C-2 | Reconnect/queue alias/fault and identity liveness | OPEN | OPEN | OPEN | Old/new keys, ambiguous twins and reset sequences; no stale command resumes on a new epoch |
| C-3 | Packaging/legacy retirement/Manager D13/convergence | OPEN | OPEN | OPEN | Whole-product keep/delete/repoint inventory, ZIP boot, frozen shared-diff review and completed artifact before listing |
| N-1 | HUD/fault truth and duplex frame delivery; HG/SS/hge | OPEN | OPEN | OPEN | Both clients in expensive battle/PC/save phase; idle64fps sample cannot stand in for measured duplex behavior |
| D-1 | link | OPEN | OPEN | OPEN | Paired acquisition and independent native records, both HGSS directions and hge pair |
| D-2 | deadzone | OPEN | OPEN | OPEN | Natural forbidden-zone sequence, independent acquisition/state readback |
| D-3 | linked_faint_active | OPEN | OPEN | OPEN | Mandatory client receipt+game observation+copy-back/heal+cold reload; D7-disabled control fails |
| D-4 | faint_cmd | OPEN | OPEN | OPEN | Keyed benched/native write persists; natural faint echoes suppressed |
| D-5 | boxsync | OPEN | OPEN | OPEN | Natural move/last-phase event and independent box/party native save witness |
| D-6 | whiteout | OPEN | OPEN | OPEN | Encounter-bound loss exactly once, native heal/outcome/death-state witnesses |
| D-7 | reconnect/wrong-save | OPEN | OPEN | OPEN | Old held command cannot mutate wrong save or pass an interrupted active-faint receipt |
| D-8 | clauses/shiny | OPEN | OPEN | OPEN | Natural encounters and independent species/key/clause results |
| D-9 | gift/egg | OPEN | OPEN | OPEN | Correct gift namespace/daycare/hatch identity, producer and native record evidence |
| D-10 | doubles/TAG/multi ownership | OPEN | OPEN | OPEN | Both local battlers/wrong-owner controls and required doubles active-faint scenario |
| D-11 | NPC exchange/loan classification | OPEN | OPEN | OPEN | Actual replacement, same-species alias and loan/no-exchange negative controls |

The implementation manifest must bind these family rows to exact executable check/scenario IDs without silently collapsing missing variants. Each scenario needs a SOURCE/MODEL oracle specification and an actual PHYSICAL receipt per required artifact/direction; the three initial OPEN cells do not imply a model check exists yet.

## Release completeness and signed limits

G6 rejects a required cell that is absent, OPEN, skipped, deselected, xfailed, stale or lacks a prerequisite/independent oracle. A lower-level exit0 is insufficient. Remove the SS save, one hge trainer fixture, a doubles/NPC scenario or a required direction: verdict must fail. Allowed entries cover only explicit non-shipping or signed-limit scope and stay visible in the manifest.

D3 Pt runtime is out of shipping scope; its bind cells keep their actual statuses. D14 live contest/Safari/roamer play is limited; their source/model/zone mapping is still required. Native link trades, panel/text, Pal Park/Pokéwalker and external distribution/Wi-Fi/GTS are the documented candidate limits from PLAN; no new waiver is inferred. No master landing, push, tag or shipping authority follows from this skeleton.
