# Gen 4 rev5 amendment receipt — 2026-09-29

Authorization: owner requested “Make the amendments” following the [adversarial review](ADVERSARIAL_REVIEW_2026-09-29.md). Base `c4dd4df0acb56ee3fc0d5d1db6502983508facbd`; reviewed production cut remains `7da76fbf`. This receipt records documentation and research-data amendments only. G0 and all unrun gate signatures remain OPEN.

## Exact scope and reuse decision

Coordinator exclusively edited `docs/gen4/PLAN.md`, `RESUME.md`, research `README.md`, `platform.md`, `platinum_bind.md`, `sources_and_symbols.md`, `wire_contract.md`, the new `docs/gen4_requirements.md`, and this receipt.

Sol battle editor exclusively edited research `battle_faint.md`, `battle_pointer.md`, `checkpoint.md`, `engine_sites.md`, `hg_engine.md`, `pk4_and_save.md`. Sol acquisition editor exclusively edited research `acquisition.md`, `offline_measurements.md` and data `acquisition_manifest.json`, `npc_trades.json`, `hge_site_survival.json`. Both acknowledged their exact leases; no overlapping writers or emulator lanes. The owner kept guide/register edits paused with Claude; neither worker nor coordinator modified them during this amendment.

No production module was added or changed. The plan reuses shared session/deferred/identity/registry/permit/transport/HUD behavior. The necessary NDS phase composite owns platform lifecycle; pack predicates, ROM facts and permitted title pairs remain game policy. Generic queue/admission changes, if required later, belong in shared modules under the single reviewed integration card.

## Accepted finding disposition

| Review finding | Amendment | Remaining evidence |
|---|---|---|
| F1 two-copy conflict | Plan/storage recipe and notes require both identity-checked HP copies; partial batch is fatal, not rollback | Model and actual game effect/copy-back OPEN |
| F2 command11 timing/poll gap | Candidate seam is explicitly unproved; transition census/exec boundary and accepted latency required | Physical seam/latency OPEN; D7/D12 unchanged |
| F3 representation | Lock flags inspected, unconditional XOR removed; tail/box checksum rules separate | Representation-aware model/control OPEN |
| F4 false active-faint proof | Mandatory diagnostic format plus independent encounter-bound game effect; disabled battle operation must fail even with deferred writes/receipt | G1/G4 oracle runs OPEN |
| F5 outcome/heal lifetime | Encounter-scoped outcome survives teardown; wild VAR gap, native whiteout heal and NPC-follower win heal separated | Natural-input outcomes/healing/cold reload OPEN |
| F6 eligibility/epochs | Existing session eligibility plus save/battle epoch checked at every arm; held disconnect/reset/duplicate sequences named | Model/runtime sequence OPEN |
| F7 phase lifecycle | NDS composite specifies activation/caller coverage, drain-before-drop, nil/partial-construction handling, close failure and real handle count | First/last-event and fault controls OPEN |
| F8 release completeness | Exact shipped-artifact rows/directions; missing required SS/hge inputs cannot be allowed skips; Pt scope kept honest | Manifest/runner and all signatures OPEN |
| F9 prerequisites | C0 ledger skeleton created, pins/check bindings precede G0; completed C1-7 source not redispatched; C1-1 a–n /C1-8 o assigned | C0-2 generated lock/check inventory/G0 still OPEN |
| F10 NPC reachability | Raw13 records preserved; ten exchanges, two loans, one dormant; same-species replacements retained | Source inventory metadata; generated/runtime catalogue OPEN |
| F11 wrong-image bytes | Declared ov12/ov130 remeasurement with pinned hge SHA1; historical ARM9 zeros retained; result site's matching prefix bounded | FILE prefix/replacement evidence; live mechanism OPEN |
| Further corrections | TAG local0/2, census quantities, pin widths, ambiguous empty save, duplex load, Pt model, receipt transport, legacy retirement and convergence disposition | Unrun/source-only limitations remain named |

During final source checking another width error was corrected: live BattleMon HP is **signed32/full4bytes** (pret `include/battle/battle.h:248`, hge `include/battle.h:905`), party HP is **u16/2bytes** (`pokemon_types_def.h:203`). The pack schema and readback controls now require exact widths and reject a stale high half. This is SOURCE evidence, not an executed write.

The new requirement skeleton explicitly initializes SOURCE/MODEL/PHYSICAL cells and artifact obligations as OPEN. It does not claim production runners/check bindings exist. Story-gated probe inputs use natural saves/scripted normal inputs; no follower-flag or game-data staging is authorized. Existing D14 live limits and D3 emulator-free scope are preserved.

## Verification and independent review

- All research JSON parsed successfully. Recursive comparison with `c4dd4df0` confirmed original acquisition/script and NPC-record values were preserved; classification fields are additive. The61 script hits and13 raw NPC records remain intact.
- Coordinator independently reproduced the two corrected ov12 16-byte prefixes from `ndspy`'s explicitly selected overlay12 on hge SHA1 `cb2dc435196d09c8c9209bf037240ed834f4cea1`. The faint entry is patched; the result site's prefix matches, without claiming full-function semantics. The ov130 replacement remains a separate FILE site/PHYSICAL-open cell.
- Current probe save SHA256 hashes were independently checked and match the corresponding named HG/AP-named hge files; each path is identified, without claiming historic or future fixture qualification.
- Markdown links/table structure, exact inventory classifications, shared wording and diff whitespace are checked before commit. No unit suite, emulator, build, deployment, master merge, push or tag is part of this amendment.
- Isolated Sol reviewer `amendment_independent_review`, which authored none of this cut, checked staged tree `fb4c5f529cdb1f8714a8fd83cc7f990ababc1b32` / diff SHA256 `5be436089849f45a0dadd9a958939f17ff7b78ac3ad0ae802cc47c77df633376`. It found two stale sentences: D6 needed phase predicates for static sites, and the hge note described historical padding as current measurements. Both were repaired; HP widths, classifications, gate ordering, required cells and evidence limits otherwise aligned. The narrow repair check ACCEPTED staged tree `407dddada2758e1a9f3c9275be6642be32129092`; no remaining issue was reported. Only this receipt status was updated afterward.

Next action: under the sole guide's coordinator grants, finish exact C0 check/manifest bindings and generated pins, obtain full G0 authority, then proceed to the bounded pack/codec/build preparation and C1-8 mechanism experiment. No further broad research wave is implied.
