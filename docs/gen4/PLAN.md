# Gen 4 plan: HeartGold / SoulSilver + hg-engine on the shared framework

> **Status:** DRAFT rev 5 (2026-09-29); G0 remains unsigned.
> - Owner decisions D1-D15 were taken in the planning session.
> - Rev 2 folded in the first adversarial review (OMP G4-REV1 `cx-b646f457`).
> - Rev 3 folded in the research wave (live melonDS probe, offline measurements, R7-R9, wire contract).
> - Rev 4 folds in the second adversarial review (OMP G4-REV2 `cx-03ea7236`: 21 accepted, 1 partly refuted) and decisions D12-D15.
> - Rev 5 incorporates the [full adversarial review](reviews/ADVERSARIAL_REVIEW_2026-09-29.md) at `7da76fbf`, three Sol passes and three reconciled live OMP passes. The owner's amendment request authorizes these documentation corrections, not gate signatures or production implementation.
> - Research record: [research/README.md](research/README.md)
> - Ledger: [`../gen4_requirements.md`](../gen4_requirements.md), rev-5 skeleton; all unrun gate cells remain OPEN
> - Coordinator: Claude (Opus 5.5), worktree `.claude/worktrees/gen4-support-framework-dfd5e2`, branch `claude/gen4-support-framework-dfd5e2`

## 1. Context

SLink supports Gen 1, 2 and 3 on local master (not pushed). Gen 4 exists only as the old polling client:
- `lua/clients/gen4_hgsspt_client.lua`, `lua/memory_nds.lua`, `lua/games/gen4_hgsspt.lua`, `lua/slink_gen4.lua`
- `server/adapters/gen4_hgsspt.py`

It never ran on a real game (tag `archive/gen4-gen5`) and bypasses the shared framework: no admission, no write permit, no checkpoint, and PID-only keys.

The owner wants HGSS and hg-engine on the shared framework, with the Gen 4 foundation shareable with Platinum and D/P later. This is a **rewrite** in the Gen 2 sense ("nothing in the old code is evidence", `docs/gen2/PLAN.md:56-67`), using Gen 3's gate cadence and battery-save harness. Salvaged:
- the PKM crypto, which the new codec re-proves
- the adapter's presentation data

## 2. Owner decisions (2026-09-26) and coordinator defaults

| # | Decision |
|---|---|
| D1 | **Compose now, merge later.** Gen 4 uses `lua/core/{session,deferred,identity}.lua` plus the neutral `lua/hook_registry.lua` / `lua/write_permit.lua`. New code only where nothing exists. It must not duplicate `lua/core`. Gen 4 joins the convergence card's falsifier set (`docs/gen3/PLAN.md:20`). |
| D2 | **hg-engine = the owner's fork** (`E:/Howard/HGEngine_ROMHack/hg-engine`) at a pinned commit. Lanes build it with the fork's own `build-remote.sh` over the key-based `hgbox` ssh alias (never the plaintext passwords in the old AP notes) and pull the `build/*linked.o` symbols back. One generated pack per pinned build. |
| D3 | **Platinum: an emulator-free bind check only.** Generate a Platinum profile from `platinumus.xMAP` and decode a Platinum battery save with the shared codec. The local Platinum save is blank. Until the owner supplies one, the codec half is an OPEN cell (named skip) and the profile half is SOURCE. |
| D4 | **SoulSilver first save: the owner plays SS** to a first save after getting the starter. Until then, SS cells are OPEN (named skip). |
| D5 | **No touch-screen support.** Button-only inputs; G1 row l proves CONTINUE is reachable on buttons. (Measured: HG/hge reach the overworld on A/Start only. An SS **new game** stalls at "Please touch any topic", which is why SS fixtures come from the owner's save, D4.) |
| D6 | **Hooks only where needed** (phase-armed). Gen 1–3 register ~20 byte-pinned exec hooks cheaply on mGBA/Gambatte. The melonDS idle research measured a ~5 ms first-hook cost, then ~2 ms per additional hook; more than 4 missed 60 fps in that sample. Gen 4 composes the shared byte-pinned `hook_registry` **per game phase** (§4.2): hooks exist while their declared phase predicate holds, and overlay-owned sites additionally require owning-overlay residency. Static ARM9 sites use application/task/caller predicates. The target remains 0–1 always-on hooks and ≤3 per phase; G4 proves the actual duplex performance. |
| D7 | **Active linked faint happens immediately, in battle** (parity with Gen 3's mechanism P). The partner's active battler is written in the live battle context (`BattleMon.hp`) so it faints mid-battle. Benched mons faint at the checkpoint. C1-7 must first show how an in-battle HP write is picked up and survives the copy-back. |
| D12 | **D7 is required for the RC; no fallback.** If the in-battle write can't be made reliable, the RC is blocked until it is: the checkpoint path is not an accepted substitute for the active battler. |
| D13 | **Manager New-run form:** HG/SS are re-admitted only at **G4 sign-off**, and hge at its own G4 column sign-off. This keeps the owner ruling of 2026-09-23 ("Gen 4/5 never ran on a real game … must not be listed") in force until then. Lanes use the harness. |
| D14 | **Bug Contest, Safari Zone and roamers:** SOURCE + MODEL evidence plus the zone/area mapping only. Live play of these modes is a recorded limit for the first release (they are story-gated beyond the fixtures). |
| D15 | **hg-engine saves:** the owner plays **two** hg-engine new games to a first save after the starter (distinct trainer IDs, populated party) for the hge↔hge duo. |
| D8 | **hg-engine alongside HG/SS from the start.** Every gate carries an hge artifact column (pack, probes, fixtures, duo). There is no trailing sub-gate. |
| D9 | **Pairings: HG↔SS only** for the first release; hge↔hge for the hge artifact. |
| D10 | **Special modes:** the Bug Contest is its own zone (the kept bug is the catch, at the result); the Safari Zone counts as zone(s), per Safari area; roamers are extra catches; scripted statics/gifts follow the gift-namespace rules. |
| D11 | **Doubles are scenario-tested**, not a recorded limit. Executed NPC exchanges are supported as `key_change{reason:"npc_trade"}`. **Factual count correction, 2026-09-29:** vanilla has 13 NARC records: 10 reachable exchange identities (11 load sites), two loan grants, and one dormant Rapidash record. Loan grants are acquisitions, not fabricated old→new exchanges; same-species Steelix/Pikachu remain real exchanges. Re-derive the hge inventory per build. |

**Coordinator defaults** (recorded as §0 rows; the owner may overrule):

| Topic | Default |
|---|---|
| Companion ROM patch | None in the first release (FR/LG shipped without one) |
| Notifications | HUD only |
| Link trades | None |
| Gen 2 policy carried over | O-15 hatched egg = gift catch (O-17/18 are now D10). Current Gen4 lanes use scripted normal inputs and no game-data staging under the standing orchestration contract; the older O-10 fixture-injection default is not active qualification authority. |
| hge `artifact_kind` | `clean`: the hge build is its own `rom_type` (`heartgold_hge`) and foundation (`gen4_hge`), and "clean" describes it relative to that base. Isolation comes from the foundation row; the specific build is admitted by its pinned hash. No new identity mechanism. |
| `memory_nds.lua` | Frozen for the Gen 5 legacy client. The PK4 crypto copied into `lua/gen4/reads.lua` is the canonical Gen 4 copy, and `memory_nds.lua` is not edited. |
| NPC trades | D11 supersedes the wire-contract note that listed `key_change` as "leave out" for a first duo |

## 3. Verified research (summary; details and citations in `research/`)

- **ROM pins:** HG `4fcded0e…` (IPKE), SS `f8dc38ea…` (IPGE), Pt `ce81046e…` (CPUE). HG and SS equal pret's `rom.sha1`.
- **Symbols:** pret publishes CI **xMAP** linker maps (`pokeheartgold@xmap 40eab3c6`, `pokeplatinum@xmap a2a62d3d`). HG/SS gameplay symbols are identical; their 1234 address differences are confined to ov18, ov74, nitrocrypto and intro/title/menu. Key addresses:

  | Symbol | Address |
  |---|---|
  | `sSaveDataPtr` | 0x021D2228 |
  | `sFieldSysPtr` | 0x021D4158 |
  | `sOverlayRegions` | 0x021D0DF0 |
  | `gSystem` | 0x021D110C |
  | `Encounter_GetResult` | 0x020506F4 |
  | `Task_Blackout` | 0x02052858 |
  | `Party_AddMon` | 0x02074524 |
  | `BtlCmd_TryFaintMon` | 0x0223E22C (ov12) |

  Site bytes can be pinned offline from ndspy images. **Overlays 57/58/70/72 share ov12's address.**
- **The archived probe's `sSaveDataPtr = 0x02111880` is wrong** (it is `main.o _02111868+0x18`).
- **PK4 and save format:** confirmed on the owner's real HG save.
  - Records: 0x88/0xEC; checksum-seeded LCG blocks; PID-seeded party tail.
  - Save banks at 0x0/0x40000, each with a general block (HG 0xF628) and a PC block (+0xF700, 0x12310).
  - Footer magic 0x20060623, CRC-16-CCITT init 0xFFFF.
  - Party at general+0x90.
- **Behaviour:**
  - Field poison floors at 1 HP, so **no poison-faint**.
  - Battle structs are heap-allocated; doubles battler→party is not identity.
  - The battle works on copies that the field copies back.
  - Overworld idle = the game's own `FieldSystem_IsPlayerMovementAllowed` (`unk6C && !isPaused && taskman == NULL`) plus no launched app (`unk0->unk4 == NULL`) and the save driver idle. A new frame is detected by `gSystem.vblankCounter`. The frame-end CPU is the idle thread's `OS_Halt`, so there is no "PC in `OS_WaitIrq`" clause ([research/checkpoint.md](research/checkpoint.md)).
  - Box writes must set `PCStorage+0x12004` bits.
- **hg-engine:**
  - IPKE only; builds on Linux only; header unchanged.
  - Record geometry and crypto are vanilla. Bit changes: 21-bit exp with an ability MSB, 5-bit form. 1075 species (1476 with forms).
  - Save changed: 30 boxes, general 0xFFA0, PC 0x1E4FC at +0x10000. The empty-save scan has two plausible party headers, +0x90 and +0xCAB4; +0x90 is a source candidate, not uniquely confirmed FILE evidence. A populated decoded mon and live dirty-bit persistence remain G2/G4 cells ([research/offline_measurements.md](research/offline_measurements.md)).
  - Its own battle C in ov130 @0x023C4000, auto-loaded with ov12.
  - **Shared vanilla sites:** `Party_AddMon`, `Encounter_GetResult`, `Task_Blackout`, `Get/SetMonData`, `Battle_GetClientPartyMon`, `sOverlayRegions`. Faint/PC/save/give/trade/evolve/`HandleLoadOverlay` are **replaced per build**.
- **melonDS (live research probe, [research/platform.md](research/platform.md)):**
  - Exec hooks work: the callback gets `(addr, val, flags)`, where `val` is the site word (a free byte check); PC = site+4 (Thumb) or +8 (ARM); scope `ARM9 System Bus` or none. Other scopes return a zero GUID and never fire.
  - A live same-address collision between overlays was observed, so residency + `val` checks are both required.
  - **Cost per registered hook: more than 4 can't hold 60 fps** (D6).
  - The frame-end PC is the idle thread's `OS_Halt`, not `OS_WaitIrq`.
  - `gameinfo.getromhash()` = MD5 for gamedb ROMs (HG/SS) and SHA1 for the hge build.
  - SaveRAM files are named after the gamedb name.
  - The RTC is deterministic with `UseRealTime=false`.
- **Battle layout** has source-supported common offsets in HGSS and hge (`BattleSystem+0x30` → ctx, `ctx+0x2D40 + 0xC0*i`, `ctx+0x219C`); ability differs (0x27 u8 vs 0x7A u16). This is geometry evidence, not proof that hge processes a forced faint identically. hge keeps `ScrCmd_GiveMon`; its arm9 is bloated by the `hooks:632-636` misfile. The old offline survival resolver selected ARM9 padding for two ov12 sites: re-resolve by declared image/overlay identity before using those bytes as corroboration.
- **Platinum** has SOURCE schema candidates and OPEN codec/runtime bind cells ([research/platinum_bind.md](research/platinum_bind.md)); a generated profile alone does not prove every module reusable.

## 4. Architecture

### 4.1 Existing shared modules (used through their current APIs; D1)

| Module | Gen 4 use | Change |
|---|---|---|
| `lua/core/session.lua` | Lifecycle via the driver interface (`:16-27`) and existing `session:eligible()` (`:109-110`) | Reuse unchanged unless an independently reviewed shared-contract correction is required. Held battle writes are not connection-gated by the current flush (`:168-189`); the write binding must check eligibility plus save/battle epochs at every arm. Wire sound ids are Gen 3 SE ids; omit `play_sound` in this release. |
| `lua/core/deferred.lua`, `lua/core/identity.lua` | Checkpoint command queue; key aliasing | None |
| `lua/hook_registry.lua` | Registration lifecycle + bounded queue + failure latch. The NDS binding's `context` is adapted to the registry's `capture` callback. Constructor-only registration (`:126-135`) means one registry per armed phase. | Reuse through an NDS phase composite (§4.2), including drain ordering, construction failure, cleanup and status aggregation. The session reads failure fields; the registry exposes `status()`. This is a named lifecycle contract, not merely a field bridge. A generic arm/disarm API belongs to the shared convergence card if needed. |
| `lua/write_permit.lua` | Armed write gate on `ARM9 System Bus` (bounds, `pointer_stable`, same-frame lifetime) | None |
| `lua/hud.lua`, `json_codec`, `connector`/`socket`; tests: `scripted_inputs` + `lua/tests/playlib.lua` | NDS HUD metrics exist (`hud.lua:106,189-191`) | None. The NDS button map and `io.step`/`io.idle` live in the Gen 4 test harness. |
| `lua/token_scanner.lua` | **Not used.** It is a byte scanner (`:15,43`); Gen 4 text is u16 with a 0xFFFF terminator. `gen4/reads` decodes names with the pack charmap in a few lines. | None |
| `lua/admission.lua` | **Not used.** It rehashes the whole artifact (`:88-110,154`), which is unusable at 128-192 MiB. Admission lives in `gen4/entry` on `gameinfo.getromhash()` + anchors, like Gen 3. | None (the reported-digest question goes to the convergence card) |

### 4.2 NDS binding and phase lifecycle

`lua/nds/hook_binding.lua` is the NDS sibling of `lua/gb_hook_binding.lua:1-87`, with the same API. It lives in a subdirectory: a home for Gen 5 later, and outside the top-level `lua/*.lua` Gen 2 code digest.
- `NDS.new(io,cfg)` returns `{validate, context(site,accept), register, unregister, valid_handle}`.
- `NDS.resident(io,tbl,ovy)` is the one residency reader, also used by `in_battle` and the checkpoint.
- Each site declares its owning image (`arm9` or a specific overlay), complete byte extent and `phase`. The generator resolves that image first, then the address; overlapping ARM9/overlay ranges or two overlays sharing an address must never select a binary by address alone.
- `register_hex` is the full registration byte pin; `fire_hex` is exactly four bytes interpreted as the callback's little-endian u32 (normalize unsigned). Static registration validates the full pin; overlay descriptors validate id/range and validate the full pin when resident before arming. A four-byte fire pass does not prove the rest of a trampoline or its branch target.
- **Phase arming (D6), composing the existing registry:**
  - Each pack site carries a `phase`.
  - `lua/nds/phase_signals.lua` owns the phase→registry lifecycle and provides the session's single signals object (`drain`, `close`, failure/handler-error fields). Gen 4 supplies pack phase predicates and event capture; the platform module owns no title facts. Zero-site phases do not construct a registry (the existing registry requires a nonempty array). This module is needed because the registry has no dynamic site API; it composes that registry rather than duplicating it or `lua/core`.
  - The load table is observed one frame late. C1-2 supplies a concrete activation predicate and complete producer/caller coverage for each phase; C1-1 proves first-entry event coverage. No "harmless" load-delay assumption is accepted. Static party/PC sites need application/task predicates and battle/script caller coverage, not a fictional overlay trigger.
  - Drain all queued phase events before removing their registry from the composite, or retain closed registries until drained exactly once. Poll/drain/close ordering is fixed relative to `session.frame_end`, including its pre-pump and post-drain seams. Handle `Registry.new`'s `nil,error,failed_registry` result without throwing out of the frame loop; retain partial cleanup state.
  - Assert `close()` success. On failure, retain/count unremoved handles and the reserved owner, latch a surfaced fault, revoke writes and stop re-arming until recovery is explicitly proved. `status().registered` is cumulative registration, not a live external handle count. Track actual owned handles, including failed-close registries, and assert total ≤4. A global first-fatal latch is valid if it disables all unsafe ENGINE-dependent behavior; per-phase recovery must surface each fault distinctly.
  - Residency is polled, not hooked. hge replaces `HandleLoadOverlay` and its own loads of 129/131 bypass the entry hook, so only the table sees every load.
- **Per-phase site budget** (C1-2 derives the exact table, with counts, at G2):

  | Phase (trigger) | Registered hooks | Polled instead |
  |---|---|---|
  | always | 0 (target) | overlay residency, map, save driver, encounter-scoped outcome latch. Wild loss does not necessarily update `VAR_BATTLE_RESULT`; retain outcome/identity through copy-back and blackout without retaining stale writable pointers. Use a `Task_Blackout` hook only if the latch cannot cover every loss path. |
  | battle (setup/application epoch through encounter end; sites additionally require owning overlay) | ≤3 phase cap, target 2 after producer coverage is derived: catch store / PC-full path and a pinned controller seam if required. Count distinct sites explicitly. Command-11 frame polling requires coverage proof. No assumption that raw HP writes run `BtlCmd_TryFaintMon`. | Reacquired zero-hook pointer chain; local ownership, PID:OTID, selected slots, both HP copies, outcome and script state. The phase predicate covers setup before residency appears and teardown after it disappears. |
  | party/PC applications and non-UI callers (static ARM9) | ≤2 target: PC placement / swap / delete, with explicit application/task/caller coverage | party/box diffs at settle; last-frame queue survives phase exit |
  | field scripts | 0 target | acquisitions and evolution by validated diffs; actual NPC exchange identity evidence distinguishes replacement from loan grants |

- At fire time, in order:
  1. The site's **own** overlay must be active (e.g. hge's ov130 site checks ov130, not ov12) in `sOverlayRegions[MAIN][0..7]`; otherwise drop with nil, because another overlay shares the RAM (the GB wrong-bank case).
  2. The PC must match (the relationship is measured at G1).
  3. The callback's unsigned `val` word must equal `fire_hex` (no extra bus read). An active owning-overlay mismatch latches failure; inactive-overlay hits were already dropped at step 1. Never turn active corruption into a silent drop to make a probe pass.

### 4.3 New Gen 4 layer, shared across titles (`lua/gen4/*`; titles bind with packs only)

| Module | Responsibility |
|---|---|
| `entry.lua` | The only file that names a foundation: `PACKS`, `admit{rom_hash, read_ram, header_code}` (hash first: packs pin **both** MD5 and SHA1, because `getromhash()` returns MD5 for gamedb ROMs and SHA1 otherwise; then static-ARM9 anchors including the vanilla bytes at 0x02000CD0, so an hge ROM is never admitted as vanilla; hge by hash only), `build(deps)` |
| `run.lua` | BizHawk bootstrap: io/ev on `ARM9 System Bus`, HUD 256×192, connector, frame loop (copy of `gen3/run.lua` without the nonce block) |
| `reads.lua` | Re-proved pure-Lua PK4 crypto plus runtime save-array headers, party/PC/trainer/location/badges/balls and u16 names. Reacquire the battle chain each frame; validate application identity, complete ranges, local party ownership and PID:OTID, not species equality alone. Mon key = **PID:OTID**. |
| `safety.lua` | Read-only checkpoint predicate from pack clauses ([research/checkpoint.md](research/checkpoint.md) §5): a new frame by `gSystem.vblankCounter`; `[sFieldSysPtr]` sane with `saveData` equal to `[sSaveDataPtr]`; `unk6C != 0`; `!isPaused`; `taskman == NULL`; no launched app (`unk0->unk4 == NULL`); save driver idle; refuse from battle setup until the encounter task ends. The **in-battle write** for D7 is a separate, narrower gate on the live battle context. |
| `storage.lua` | Deferred executors over the shared permit, preserving encryption representation. Recompute checksum for box-data edits; a party-tail-only HP edit is outside that checksum. Apply the pack's dirty clause (HGSS per-box bit; hge measured G2 flag; Pt whole-save flag in the bind model). D7 writes **both** live BattleMon HP and the corresponding battle-party HP after validating key, ownership, slot, lock flags, epochs and a measured legal seam. Prevalidate both spans together; partial emission is a visible fatal write fault, not rollback or success. Withdraw restores the full required party-tail fields from validated cached stats. |
| `client.lua` | Shared-session driver with NDS phase composite, truthful encounter lifecycle and validated party/box settle passes. `in_battle` covers setup/application/encounter state rather than overlay residency alone. Use the shared reducer if available; otherwise record the temporary generation-layer composition, its exact divergence and named convergence rebind owner before dispatch. No duplication of existing `lua/core` behavior; a `ponytail` note alone does not discharge reuse responsibility. |

#### Active-faint contract (D7/D12)

- The writer uses existing `session:eligible()` plus the current save and encounter epochs at every arm, including a held command. Disconnect, wrong-save reconnect, reset, stale pointers, ambiguous keys, or unavailable local ownership yield no writes. Reset/disconnect behavior and duplicate-command idempotency are explicit model sequences, not inherited assumptions about the shared battle queue.
- Command 11 can still run Future Sight/Perish Song scripts and can be missed by frame sampling. C1-8 must pin a legal execution boundary or prove poll completeness and latency; the selection screen can wait indefinitely. D7's "immediately" is unchanged: record command-to-game-effect frame latency and obtain acceptance of its bound, rather than silently replacing it with "end of a turn".
- Inspect `partyDecrypted`/`boxDecrypted`; refuse locked records unless a separately proved representation-aware path exists. Live `BattleMon.hp` is **s32/full four bytes** (pret `include/battle/battle.h:248`; hge `include/battle.h:905`), while party-tail HP is **u16** (`pokemon_types_def.h:203`). Validate full-width values, both copies and the target key immediately before emission; a low-word-only write/readback cannot prove a 32-bit field. Singles, local doubles/TAG battlers 0/2, and multi local ownership use the game's dispatch semantics; sentinel slot 6 is never writable.
- HP zero alone proves neither the normal faint script nor animation. Independently observe the agreed game faint/replacement/loss behavior while the encounter is live, then the copy-back and native save/reload. Record win, status-only turn, ordinary loss/whiteout, and win with an **NPC** follower separately; native healing can follow the in-battle effect. Any later persistence correction must be independently visible and cannot substitute for D7.
- A held command whose battle ends without a proved in-battle effect is reported as **unfulfilled/interrupted D7**; it must not be lost, falsely acknowledged or silently qualified through the shared deferred fallback. Keep the command's truthful disposition and persistence behavior, with a required scenario failure for missing active effect. D12 is not relaxed by this plan.
- `storage` emits a client/harness diagnostic line `GEN4_BATTLE_FAINT <JSON>`; this is a receipt sink, not a new server wire event or a replacement for the shared `done/hold` disposition. Required fields: source cut, artifact/pack hash, save epoch, encounter id, command/key, client and game frame, controller seam, battler/party slot, selected-index mapping, PID:OTID, representation flags, pointers, both HP before/after values, attempted/completed spans and disposition. Missing, malformed, stale, partial or mismatched receipts fail the harness. A target command/battle-disabled control must go red even if deferred HP and native save later match.

### 4.4 Packs

Packs use Gen 3's three-file layout, so pack schemas stay uniform at convergence. There is **no separate symbol store**: provenance (xMAP commit + sha256, ROM sha1, source commit) lives in the profile, the Gen 2 shape (`server/adapters/gen2_gsc.py:139-143`). Pins go in `data/gen4_sources.lock.json`.

- `data/games/gen4_hgss/{profile,engine_signals,write_checkpoint}.json`: titles `heartgold`/`soulsilver`. The profile holds:
  - `save_ptr`, `fieldsys_ptr`, save-array header geometry, block ids
  - `party_off`, PC geometry, `box_modified_flag_off`
  - `pkm {box_size, party_size, exp_bits:32, ability_msb:null, party_hp_width:2}`, `battle {ctx_off:0x30, mons_off:0x2D40, mon_size:0xC0, selected_off:0x219C, hp_off:0x4C, hp_width:4, hp_signed:true, ability_off:0x27, ability_width:1}`
  - u16 charmap, overlay table + RAM ranges
  - **per-foundation capabilities** (`boxes 18`, `mons_per_box 30`, `memorial_box 17`)
- `data/games/gen4_hgss/{area_map,locations,encounters,trainers,acquisition}.json`: the game data that replaces `data/games/gen4_hgsspt/*`. It comes from the re-pointed `tools/gen_gen4_area_map.py` / `gen_gen4_trainers.py` / `gen_gen4_encounters.py` and the acquisition manifest ([research/data/](research/data/)), read from pokeheartgold JSON, msg banks and NARCs.
- `data/games/gen4_hge/…` (per pinned build): the same shape plus:
  - `exp_bits:21`, `ability_msb`, `battle.ability_off:0x7A, ability_width:2`
  - `boxes 30`, `memorial_box 29`, the measured `box_modified_flag_off`
  - the build commit + map sha256
  - a `tables.json` of species/moves/items/abilities/types from the fork source
- `data/games/gen4_pt/profile.json`: bind check only.
- The generator (`tools/gen_gen4_pack.py`, modes `hgss`/`hge`/`pt`, ndspy on Windows, with a raw-bytes fallback for hge's uncompressed arm9) fails closed when a site's declared image/id/range/full byte extent cannot resolve. Each signal site carries `image`, `overlay_id` where applicable, `register_hex`, four-byte `fire_hex`, phase/activation evidence and build provenance. Replacement addresses come from the pinned hge exports; a historical CHANGED label or ARM9-padding read is not a site pin.
- The acquisition generator joins script sites, C-only producers, NPC-record reachability and runtime species/version branches. The 61 script hits and 13 NPC records are bounded input inventories; unsupported or unresolved producers cannot disappear silently from the coverage map.

### 4.5 Server

| File | Change |
|---|---|
| `server/adapters/gen4_codec.py` (new) | PK4 encode/decode, the u16 charmap from pret, and the 512 KiB save (banks, footer, CRC-16; geometry from the footers, box count from the profile). It shares no code with the Lua, so it is the PYDEC oracle. |
| `server/adapters/gen4_hgsspt.py` (file and game_id `gen4_hgsspt` kept; the new ids are **foundations**, not game ids) | Moves onto the codec. `memorial_box_index`/`mons_per_box` come per foundation (hge 30 boxes → 29). hge tables load from `gen4_hge/tables.json` (never `pokemon_data.py`). Drops `_RP_*`/`_is_rp` and the hand-seeded JSON. Fixes the move split, item table and status token. Gift/egg/daycare sets are regenerated from the acquisition manifest. |
| `server/adapters/__init__.py` | Foundation rows (`_ROM_TYPE_TO_FOUNDATION`, `:165-178`; today a missing row silently falls back to the game_id, `:180-186`): `heartgold`/`soulsilver` → `gen4_hgss`; `heartgold_hge` → `gen4_hge`. Add `heartgold_hge` to `_ROM_TYPE_TO_GAME_ID` (→ `gen4_hgsspt`) and `_VARIANT_LABEL`. Delete the `platinum`/`hgss`/`renegade_platinum` rows (today they would let HG pair with Platinum). |
| Shared hello/pair admission (`server/server.py`) with adapter/pack game policy | Enforce D9's exact title relation in addition to foundation/artifact-kind equality: HG↔SS in both directions and hge↔hge. Reject HG↔HG, SS↔SS, HGSS↔hge, Pt, and retired aliases before state mutation. The common admission code owns enforcement; game policy owns the permitted title pairs. Same-foundation equality alone is insufficient. |
| `server/manager.py` | **D13:** HG/SS are re-admitted to the New-run form only at G4 sign-off, and hge at its G4 column sign-off. The edit reverses `tests/unit/test_manager_option_labels.py:117-122` in that sign-off card, not in G3a. |

### 4.6 Legacy retirement and release manifest

These are the **first-class G3a card**.

- **Delete:**
  - `lua/slink_gen4.lua`, `lua/clients/gen4_hgsspt_client.lua`, `lua/games/gen4_hgsspt.lua`
  - the `lua/game_detect.lua:17` and `:27` rows, `lua/slink.lua:198`'s legacy client-map row, and obsolete Gen 4/Platinum support wording in `game_detect.lua:72-73`
  - `data/games/gen4_hgsspt/**`, **only after** its successors exist in `data/games/gen4_hgss/` (§4.4). This is an exit condition of the data-tools card, checked by test.
  - the Gen 4 rows in `tools/make_release.py`: `:64` in `_LUA_ROOT` and `:337` in `_LAUNCHER_SCRIPTS` (**keeping `slink_gen5.lua`**), `:154`, `:160`, `:302-307`. `:52` is the data-tool row: re-point it, don't delete it.
- **Add:**
  - `_LUA_GEN4` and `_LUA_NDS` rows for `lua/nds/hook_binding.lua` and `lua/nds/phase_signals.lua`
  - `data/games/gen4_hgss/*` in the data rows
  - an NDS block in `lua/slink.lua` before `game_detect`: pinned HG/SS/hge → `gen4/run.lua`; recognized but unpinned Gen 4 is refused by name. Only the explicitly preserved Gen 5 route may fall through; unknown NDS is refused without advertising Platinum runtime support.
- **Retirement check covers product code, packaging, generators, tests, fixtures and registry rows:** every reference to `gen4_hgsspt`, `hgss`, `platinum`, `renegade_platinum`, `gen4_hgsspt_client`, `games/gen4_hgsspt` or `slink_gen4` is assigned a keep/delete/repoint reason. Keep the intentional server file/game-id and bind-only source references. Repoint or remove obsolete Platinum outputs/imports (`gen_gen4_area_map.py:1367` and the legacy adapter data loader) without introducing a Platinum runtime pack. Known test hits include:
  - `tests/unit/test_make_release_manifest.py:136-140, 160-181`
  - `tests/unit/test_slink_route.py:203-207`
  - `tests/unit/test_gen4_adapter.py` (RP tests `:438-444, 512-514`; Platinum/hgss rom_type tests `:67-85, :405-407, :433-436, :464-468, :490-494, :506-509`)
  - `tests/fixtures/ui/capabilities.json` (Gen 4 rows `:556, :593, :680, :978, :1052`, plus a new `heartgold_hge` row with `memorial_box_index: 29`)
- `lua/memory_nds.lua` stays for the Gen 5 legacy client.

### 4.7 Seams kept, not built (YAGNI)

- **Companion mailbox:** attaches where Gen 3's `native.lua` does. The recipe is proven in the owner's AP work (overlay 129 @0x023D8000, `Main()` hook 0x02000CD0, fixed pointer slot; for hge, `.data` exported via `rom_gen.ld`). Don't reuse that work's `ap_perframe` stub, which has a pop-to-pc bug.
- **Touch input.**
- **Gen 5** on `lua/nds/`.

### 4.8 Platinum bind evidence and falsifiers (D3)

D3 stays emulator-free. Profile generation is SOURCE evidence for the generator; a real battery decode is an OPEN codec cell until supplied. Neither proves all runtime modules. Use a Platinum-shaped model to falsify HGSS-specific assumptions without expanding scope:

| Module | Required bind check | Current evidence/limit |
|---|---|---|
| `nds/hook_binding` / phase composite | Different residency address and pack predicates, shared `{id,active}` shape, lifecycle controls | SOURCE candidate; model lifecycle still OPEN |
| `reads` | Table-of-offsets accessor, distinct array ids and chained pointers supplied solely by profile | SOURCE candidate; Pt-shaped model and real save decode OPEN |
| `safety` | Pt process-manager idle clauses; reject HGSS taskman semantics and test required pointer hops | Offsets not yet established; model/runtime reuse OPEN |
| `storage` | Different box base/stride and whole-save dirty clause, including explicit checksum policy | SOURCE candidate; actual dirty-flag offset and model write/readback OPEN |
| `client` | Pack event descriptors/reducer inputs express Pt facts without title switches | SOURCE design seam; Pt-specific event binding OPEN |

A model rejects an unexpressible pointer/dirty/event clause, wrong box stride, or any required title-specific code change. SOURCE schema feasibility is not a runtime PASS. Keep missing offsets named; do not fabricate them from symbol names. Platinum is non-shipping and contributes only its exact bind evidence, never HGSS/hge PHYSICAL qualification.

## 5. Gates

The evidence classes SOURCE, MODEL and PHYSICAL stay distinct. Development reports may name absent input as OPEN/skip; present-but-wrong is FAIL. **A named missing prerequisite never satisfies a required signature or release cell.** The ledger's per-artifact table separates HG, SS, hge and Pt bind scope. C0 pins/ledger preparation precedes the full G0 signature; no later wave is authorized merely because this document was amended.

| Gate | Exit evidence | Owner signs |
|---|---|---|
| **G0 Pins + plan** | This plan; the ledger skeleton (Oracles, Pins, X per-artifact table, F/R/S/W/C/D/N rows with S·M·P cells). `data/gen4_sources.lock.json`: ROM sha1s, xmap commits + xMAP sha256, EmuHawk.exe / `dll/melonDS.wbx.zst` / cores dll sha256 (file hashes; waterbox has no module identity). hge fork commit + `test.nds` sha1 recorded, **not admitted**. | Pins + rulings |
| **G1 Platform + hook mechanism** | Probe rows a-o (§5.1), positive and red-capable negative controls, HG and pinned hge PHYSICAL columns. SS remains OPEN until D4; unpopulated hge input blocks its record/write cells until D15. Re-run research as committed gate receipts. Missing staged build/input is an explicit prerequisite block, never a passing hge column; a rebuild invalidates prior build-bound receipts. | Mechanism on this host; only complete per-artifact cells can be signed |
| **G2 SOURCE facts + codec + fixtures** | Full declared-image registration pins and four-byte fire words resolve for HG/SS/hge; generated acquisitions join script/C producers, NPC reachability and unresolved runtime branches. Independent codec/save-layout controls cover counter wrap, coherent banks, CRC and torn/ambiguous records. HG fixtures boot→native SAVE→cold reload with counter/keys. Hge `party_off`, dirty flag and ability offset each require source/FILE receipts plus a **populated mon decode**; its column is blocked until that input exists. SS fixture cells block on D4. Pt profile generation is SOURCE; Pt save decode remains its own OPEN D3 cell. Every required producer has an independent oracle and physical receipt plan. | Only completed pack/fixture columns; absent hge mon cannot be signed away |
| **G3 Semantics + checkpoint** (observer mode) | `lua/gen4/*` in a lupa world (`tests/unit/gen4_world.py`, modelled on `gen3_world.py`, residency flippable). Protocol conformance (`test_protocol_conformance.py` on the Gen 4 driver, C-0). Scripted play on HG (+SS once available): one positive and one negative receipt per signal kind. Checkpoint: forbidden states (script, menu, battle setup, save in flight, app running) read false with an empty write log; a liveness bound. `reads == PYDEC` on dumped Main RAM. | Each exercised kind PHYSICAL; the rest listed OPEN |
| **G3a Shared + integration card** (∥ G3) | §4.5–4.6 shared admission/routing/manifest changes in **one** exact-file card/one writer; Manager waits for G4 (D13). Full unit suite, Lua syntax, ruff and Gen 1 unit release lane; collect all skip reasons, no skipped required checks. `ALLOWED_SKIPS` is enforced only in its actual release-lane manifest, never by bare pytest; Gen 4 mandatory input absence is not added as an allowed fragment. Adapter guard and independent frozen-diff review; rejected hellos leave `links.json` byte-identical. | Shared diff with exact required-check inventory and convergence disposition |
| **G4 HGSS + hge RC candidate** | Required native writes and exact HG↔SS / SS↔HG / hge↔hge scenario inventory below; independent active-faint oracle, save/cold reload, duplex performance, frozen release ZIP boot and D13 Manager sign-off. Missing D4/D15 inputs block the corresponding signature. | Owner live HG↔SS and hge↔hge sessions after complete required cells |
| **G6 Release** | `tools/verify_gen4_release.py` on `release_lanes.py`: exact required IDs/artifact columns/scenario directions, frozen cut and fixture/build/config hashes, no missing prerequisite, OPEN, skip, xfail, deselection or stale receipt in any **shipped artifact's required cells**. Allowed entries cover only explicit non-shipping/signed-limit scope, never missing mandatory SS/hge inputs. Pt's bind cells remain honestly OPEN if incomplete and do not qualify HGSS/hge. Gen 1/2/3 runners green; convergence rebind/disposition reviewed. One owner-authorized master landing stales Gen 2 digest once: notify/re-sweep. | Owner shipping/tag authority only after complete required evidence; D8 hge columns cannot be postponed into a silent trailing gate |

The critical path is G0 → G1 → G2 → G3 ∥ G3a → G4 → G6, with HG, SS and hge columns in every gate (D8).

### G4 scenario and artifact contract

`tools/e2e_duo.py` adds opt-in Gen 4 rows, NDS SaveRAM paths and `FAMILY_EVIDENCE["gen4_hgss"]` / hge witness bindings to independent `check_save_witness_gen4`; no Gen 1 CartRAM oracle reuse. The manifest pins exact scenario IDs, directions, fixtures and predicates before implementation.

- Required families: link, deadzone, faint_cmd, boxsync, whiteout, reconnect/wrong-save, clauses/shiny, gift/egg.
- **linked_faint_active:** require the §4.3 receipt and independent encounter-bound game effect, both HP readbacks, wrong-battler exclusion, accepted latency, copy-back/heal phase and native save/cold reload. Missing/malformed receipt is FAIL. Disabling the battle operation while preserving deferred writes and receipt production must go red.
- **doubles/TAG and multi ownership:** both local doubles/TAG battlers, switch mapping and AI-partner exclusion; active linked faint in doubles is required by D11.
- **npc_trade key_change:** actual replacement and same-species exchanges, with loan/no-exchange negative controls; no fabricated dormant-record event.

Bug Contest / Safari / roamers retain SOURCE + MODEL semantics and zone mapping. Only live special-mode play is limited by D14. Missing SS/hge saves are OPEN development cells and block G4 sign-off. Hge uses two owner-played saves with distinct OT IDs; each artifact runs the same required scenario inventory unless an explicit owner limit says otherwise.

G4 proves sustained frame delivery and event completeness on both clients through the most expensive battle/PC/save phase. The single-instance idle benchmark is not duplex evidence. Each scenario has an independent oracle and save witness; native writes cover benched faint, active faint, box/party/memorialize and dirty flags. The release ZIP boots HG, SS and hge. D13 Manager re-admission is part of the completed artifact's G4 sign-off card.

### 5.1 G1 probe rows

Files: `lua/tests/probe_gen4_hooks.lua`, `tests/live/test_gen4_probe_gates.py`. Receipts: `PROBE <row> PASS|FAIL|OPEN`. Each negative control is revert-tested once.

| Row | Positive | Negative control |
|---|---|---|
| a static exec | Hits == frames on a per-frame ARM9 function, for ARM and Thumb sites; record the callback address vs `ARM9 r15` | A never-executed address: 0 hits |
| b overlay residency | Pinned HG/SS or hge replacement site fires on the game's faint command with its **own** overlay resident and fire word matched; this does not prove a raw HP write triggers the command | Same-address wrong-overlay hits drop before byte checking; active owning-overlay byte mismatch latches fault. Mutate the full registration pin or trampoline target to reject arming. |
| c reliability / JIT | Census loads, unloads, newly-active IDs and all table transitions separately. Every residency change has a source/receipt-backed cause; compare hook hits only to corresponding vanilla-path loads. Hge internal loads of129/131 have explicit table coverage; record core settings | A load/unload-free window has no corresponding changes; omit one observed load/unload/internal-load cause and the census fails. Historical HG15hits/15new IDs/22transitions and hge16/19/27 remain distinct quantities, not numerical allowances. |
| d write hooks | Record whether the callback sees the byte before or after the store | A host `memory.write` does not fire the callback; a wrong-address watch gets 0 hits |
| e unregister / reset | 0 hits after removal and after savestate reload | A liveness hook left registered keeps firing |
| f overhead | The measured curve holds: unthrottled fps at 0/1/2/3/4 registered hooks matches [research/platform.md](research/platform.md) (≥60 at 4), and real-time play holds 60 fps at the per-phase maximum from §4.2 | A 5th registered hook drops unthrottled fps below the 4-hook value; unregistering it restores that value |
| g domains / registers | Domain sizes and `ARM9 rN` names | A bogus register name is refused, not read as 0 |
| h SaveData | `[0x021D2228]` → SaveData with page signature, loaded-save identity and `[0x021D4158]+0x0C` agreement | Invalid/early-boot pointer or wrong page signature is refused. The archived chain is rejected by symbol provenance; its steady-state alias is not a value-inequality control. |
| i persistence | A host write to a decodable party field at idle overworld → in-game SAVE → `.SaveRAM` (short non-Drive path) → PYDEC sees it | The same run without the write leaves the field unchanged; a box write **without** the modified bit is not persisted |
| j identity | `gameinfo.getromhash()` vs file sha1 (HG/SS/hge) | A 1-byte-patched copy hashes differently |
| k RTC | Two boots with the pinned config read the same RTC | An unpinned config differs (or the row records "RTC not configurable") |
| l buttons only | HG/SS/hge reach CONTINUE with A/Start only (D5) | A run that presses nothing stays at the title |
| m CPU census | ARM9 PC over overworld/menu/battle/save (research: the frame end is the idle thread's `OS_Halt` 0x020D3F64, not `OS_WaitIrq`) | During a save or script the frame-end PC distribution differs |
| n phase arming | Declared predicates/caller coverage arm before the earliest producer and drain the last queued event before removal. Construction/close cost <1frame; actual retained handle count ≤4; fps returns after successful cleanup. Include static PC phases and reset | Pending event at close survives once; failed unregister/construction surfaces a fatal fault with retained handle accounting; re-arm never silently loses owner or exceeds budget. Leaving hooks open exposes measured overhead. |
| o in-battle write (D7/D12) | HG and pinned hge singles, doubles/TAG local0/2 and multi ownership: validate PID:OTID/slot/epoch/flags; write both HP copies at a proved legal seam. Independently observe the required game effect within an explicitly accepted frame bound, then copy-back and native save/cold reload. Separate ordinary win, status turn, wild/trainer loss+whiteout healing, and win with NPC follower; no-heal persistence and native-heal phases have different expected HP | Battle operation disabled with deferred writes/receipt emitter retained must FAIL. Wrong battler/key/sentinel, locked representation, unsafe/missed seam, disconnect/reset/epoch drift or partial batch yields no success. Deliberately write only one HP copy to make the copy-back oracle red. |

## 6. Requirement ledger skeleton (`docs/gen4_requirements.md`)

It carries Gen 3's constructs:
- evidence classes and **Oracles** (`docs/gen3_requirements.md:3-8, :31-37`), with the NDS amendment ENGINE = hook fired **and** overlay resident **and** bytes matched
- **Pins** (`:16-29`)
- an **X per-artifact table** (`:141-148`: artifact | required site kinds | checkpoint liveness | scenario list), with rows HG clean, SS clean, hge `<sha1>`, Pt (bind only)
- rows with an Oracle column and S·M·P cells

| Family | Rows |
|---|---|
| F | xMAP profile; site bytes in HG **and** SS; site/writer inventory; save layout; fixtures; generated data; admission |
| R | PK4 == PYDEC; **mon key PID:OTID**; SaveData via pointer + signature; bag/money/**16 badges in 2 regions**/map/trainer/u16 charmap; battle reads via captured pointers; no hard-coded addresses; gender/shiny/nature |
| S | hook contract (residency + bytes); phase boundary/cleanup; battle lifecycle/outcome latch; faint (doubles/TAG/multi ownership); capture/gift and PC-full; pc_move; whiteout; map; evolution; ten vanilla NPC exchange identities plus two distinct loans/dormant record; save; **poison_faint N/A** (cited); egg hatch; roamers/contest/Safari SOURCE+MODEL and mapping; statics/gifts |
| W | armed gate; checkpoint predicate; benched faint at the checkpoint; **active faint in battle (D7/D12; row o, C1-7/C1-8)**; box/party/memorialize with the modified bit; pause/NACK; write ownership; following-Pokémon consistency W-8g |
| C | C-0 conformance; C-1 hello fields (Gen 3 set) + admission; reconnect/wrong save; dashboard; faults; pairing (`gen4_hgss` vs `gen4_hge` isolated, Pt refused); idempotency |
| D | link; deadzone; linked_faint_active (in battle); faint_cmd; boxsync; whiteout; reconnect; clauses/shiny; gift/egg; doubles; npc_trade |
| Limits (candidate) | Link trades; native panel/text; Pal Park and Pokéwalker (external); Wi-Fi/GTS/Mystery Gift; **live** Bug Contest/Safari/roamer play (D14: S+M + zone mapping only); Explode/Rival Swap (RR only) |

## 7. Cards

Up to 3 subagents run at once, model explicit, plus headless OMP for checks. Exclusive files never overlap. The coordinator alone runs emulator lanes, one at a time, own PIDs only, on short non-Drive paths.

| Card | Model | Exclusive files | First falsifier | Exit |
|---|---|---|---|---|
| C0-1 ledger | Sonnet | `docs/gen4_requirements.md` | A required artifact/row has no independent oracle or an OPEN cell is treated as PASS | Skeleton created by the owner's rev-5 amendment request; expand exact requirements/manifest mappings under a renewed lease before G0. No gate signature implied. |
| C0-2 pins | Haiku | `tools/gen4_pins.py`, `data/gen4_sources.lock.json`, `tests/unit/test_gen4_pins.py` | A 1-byte-flipped ROM copy → FAIL; an absent ROM → named skip | `--json` pin table (ROMs pin both MD5 and SHA1) |
| C0-3 hge build | Sonnet | `tools/gen4_hge_build.py`, `tests/unit/test_gen4_hge_build.py` | A build whose `test.nds` hash ≠ the recorded pin → FAIL; `hgbox` unreachable → named skip | Runs the fork's `build-remote.sh` via the `hgbox` alias; pulls `offsets.ini`, `build/rom_gen.ld` and `nm` of `build/*linked.o` into `.cache/gen4/hge/`; records commit + hashes. Reproducibility is unproven (unpinned devkitARM/armips), so the pin is the output hash. |
| C1-1 platform/phase probes | Opus | `lua/tests/probe_gen4_hooks.lua`, `tests/live/test_gen4_probe_gates.py` | Each negative control can go red, including last-event close and failed cleanup | Rows a–n receipts; C1-8 exclusively supplies row o, consumed as a required input by this gate wrapper |
| C1-2 pack generator (G1 profiles) | Sonnet | `tools/gen_gen4_pack.py`, `data/games/gen4_hgss/profile.json`, `data/games/gen4_hge/profile.json`, `data/games/gen4_pt/profile.json`, `tests/unit/test_gen4_pack.py` | HG/SS symbol mismatch, wrong declared image, bad full pin or fire width goes red | Probe profiles/provenance for each declared artifact, plus exact activation/producer/site counts (§4.2); Pt remains bind-only |
| C1-3 codec | Sonnet | `server/adapters/gen4_codec.py`, `tests/unit/test_gen4_codec.py`, `tests/unit/test_gen4_save_layout.py` | A flipped byte → checksum refusal; a torn slot → refused | HG save decodes; hge geometry parses; Pt skip is named |
| C1-4 fixture infra | Haiku | `tools/gen4_fixtures.py`, `tests/unit/test_gen4_fixtures.py` | A config with no NDS SaveRAM entry → raises; an hge duo with identical OT IDs → refused | Per-run config (`UseRealTime=false`, pinned `InitialTime`, `EnableJIT=false`) + short lane path. SaveRAM is named after the gamedb name for HG/SS and the basename for hge. |
| C1-7 source record | Opus | `docs/gen4/research/battle_faint.md` | Conflating HP replacement with normal faint script, or encrypted with locked plaintext | Source notes completed and corrected in rev5; no broad redispatch. The legal seam, latency, normal game effect and hge equivalent remain named C1-8 dependencies, not completed physical evidence. |
| C1-8 active-faint mechanism | Opus | `lua/tests/probe_gen4_battle_faint.lua` | Two same-species party mons must not let wrong PID:OTID/slot pass; single-copy/deferred-only path fails independent oracle | Row o on HG/hge: prove pointers/local ownership, both representation-aware HP copies, legal seam/poll completeness, accepted latency, game effect and copy-back/heal/cold-reload. Cover command arrival at selection, Future Sight/Perish Song, switch/run, win, loss, NPC follower and interrupted battle. No command11 safety assumption or D12 fallback. |
| G2+ cards | Opus/Sonnet | `lua/nds/hook_binding.lua`, `lua/gen4/*`, `tests/unit/gen4_world.py`, `tests/unit/test_gen4_*.py`, `lua/tests/gen4_*.lua` (walk/scripted play), data tools, the G3a integration set (§4.6), `tools/e2e_duo.py` rows, `tools/verify_gen4_release.py`, `tools/gen4_hge_build.py` | Per card | Per gate |

- Pre-G0 preparation: complete the C0-1 ledger/policy mappings and C0-2 exact pins. Obtain the full G0 signature only with those artifacts; a design-only approval would be a separate explicit owner ruling, not inferred here. This amendment is docs-only authority.
- After G0: C1-2 ∥ C1-3 ∥ C0-3 (no emulator); then C1-4. C1-7's existing source notes are inputs, not a fresh research wave.
- Physical C1-1/C1-8 require generated addresses, pinned build/config and appropriate populated input. One owned emulator lane. Route-development inputs request300%;100% is reserved for explicit qualification. Performance receipts record requested and achieved rates.
- Story-gated NPC-follower/format legs require naturally prepared, hash-pinned saves or scripted normal-input progress. Do not set follower flags, stage party data or fabricate a physical fixture to satisfy row o. The affected cell stays OPEN until its genuine prerequisite exists.
- C1-8 → G1 row o → G3/G4 remains RC-blocking under D12. Phase/lifecycle models may proceed independently, but required active-faint claims cannot advance past a failed mechanism.
- Before any G2+ dispatch, replace its broad inventory row with exact exclusive files, prerequisites, first falsifier and receipt/review owner. No wildcard grants. Shared convergence and integration files have one writer.

## 8. Orchestration

- The Gen 4 lane is registered in `C:/Users/howar/.claude/hooks/slink/WORKTREE_REGISTER.md` and as `gen4_lane_note` + worker cards in the `RC_MASTER_GUIDE.md` checkpoint. The coordinator alone edits both.
- The Gen 2 and Gen 3 coordinators are told about D1 and the single landing.
- Resume note: `docs/gen4/RESUME.md`.
- No push, master merge or tag without owner authority. G-gates are recorded as signed only on an explicit owner yes.
- Owner instruction 2026-09-29: Claude is editing the sole guide; this amendment session leaves guide/register writes paused. Amendment receipts identify exact docs/data changes and independent review for the coordinator's reconciliation; they do not create a second work ledger.

## 9. Verification

- **Standing:** `pytest tests/unit` (full at G3a/G6), `tools/lua_syntax_check.py` (lupa), ruff.
- **G1:** `SLINK_LIVE=1 pytest tests/live/test_gen4_probe_gates.py`.
- **Codec:** `pytest tests/unit/test_gen4_codec.py` on the owner's HG/hge saves (SS/Pt named skips until provided).
- **G3a:** `pytest tests/unit/test_make_release_manifest.py tests/unit/test_slink_route.py tests/unit/test_gen4_adapter.py` inside the full suite, plus `tools/make_release.py` preflight.
- **G4:** `tools/e2e_duo.py --game gen4_hgss --scenario all` (save witness + oracle); then the owner's live HG↔SS Manager session.
- **Non-regression:** the Gen 1/3 release runners, and one Gen 2 re-sweep at the single master landing.
