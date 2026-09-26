# Gen 4 plan: HeartGold / SoulSilver + hg-engine on the shared framework

> **Status:** DRAFT rev 2, for the owner's G0 signature (2026-09-26). The owner decisions D1-D5 were taken in the planning session. Rev 2 folds in the verified findings of the adversarial plan review OMP G4-REV1 `cx-b646f457`.
> - Research record: [research/README.md](research/README.md)
> - Ledger: [`../gen4_requirements.md`](../gen4_requirements.md) (card C0-1)
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
| D5 | **No touch-screen support.** Button-only inputs; G1 row l proves CONTINUE is reachable on buttons. |

**Coordinator defaults** (recorded as §0 rows; the owner may overrule):

| Topic | Default |
|---|---|
| Companion ROM patch | None in the first release (FR/LG shipped without one) |
| Notifications | HUD only |
| Link trades | None |
| Gen 2 rulings carried over | O-10 ball injection into fixtures; O-15 hatched egg = gift catch; O-17/18 roamers = extra catches, the Bug Contest is its own zone |
| First duo pairing | **HG(A) ↔ SS(B)**; no `_b` re-keyer yet |
| Doubles active faint | Decided at G3: a scenario or a recorded limit |
| **Linked-faint timing** | A benched mon faints at the checkpoint. An active battler is applied after battle end, because the field copies the battle's party, profile and bag back over the save (`src/battle/battle_setup.c:425-434`, [research/checkpoint.md](research/checkpoint.md)). An in-battle prompt faint (like Gen 3's mechanism P) would be a post-G4 card. |
| hge `artifact_kind` | Chosen from the **existing** six kinds (`server/server.py:456`); isolation comes from the foundation row. No new identity mechanism. |

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
  - Overworld idle = `FieldSystem.taskman == NULL` plus no app and no save in flight; the CPU parks at `OS_WaitIrq` (`src/main.c:122`).
  - Box writes must set `PCStorage+0x12004` bits.
- **hg-engine:**
  - IPKE only; builds on Linux only; header unchanged.
  - Record geometry and crypto are vanilla. Bit changes: 21-bit exp with an ability MSB, 5-bit form. 1075 species (1476 with forms).
  - Save changed: 30 boxes, general 0xFFA0, PC 0x1E4FC at +0x10000.
  - Its own battle C in ov130 @0x023C4000, auto-loaded with ov12.
  - **Shared vanilla sites:** `Party_AddMon`, `Encounter_GetResult`, `Task_Blackout`, `Get/SetMonData`, `Battle_GetClientPartyMon`, `sOverlayRegions`. Faint/PC/save/give/trade/evolve/`HandleLoadOverlay` are **replaced per build**.
- **melonDS:** `on_bus_exec` is present, registers are `ARM9 rN`, and the domains are known. **Exec hooks on overlay code are unmeasured.**

## 4. Architecture

### 4.1 Existing shared modules (used through their current APIs; D1)

| Module | Gen 4 use | Change |
|---|---|---|
| `lua/core/session.lua` | Lifecycle via the driver interface (`:16-27`) | None. Wire sound ids are Gen 3 SE ids (`:24`); the Gen 4 driver omits `play_sound` in the first release. |
| `lua/core/deferred.lua`, `lua/core/identity.lua` | Checkpoint command queue; key aliasing | None |
| `lua/hook_registry.lua` | Registration lifecycle + bounded queue; the binding supplies `validate/context/register/unregister/valid_handle` (`:104-107`) | None. `session.lua:377-384` reads `sigs.failure/handler_error` as fields while the registry exposes `status()` (`:47-51`): about 10 lines of bridge in `gen4/client.start()`, marked `ponytail:`, handed to the convergence card. |
| `lua/write_permit.lua` | Armed write gate on `ARM9 System Bus` (bounds, `pointer_stable`, same-frame lifetime) | None |
| `lua/hud.lua`, `json_codec`, `connector`/`socket`; tests: `scripted_inputs` + `lua/tests/playlib.lua` | NDS HUD metrics exist (`hud.lua:106,189-191`) | None. The NDS button map and `io.step`/`io.idle` live in the Gen 4 test harness. |
| `lua/token_scanner.lua` | **Not used.** It is a byte scanner (`:15,43`); Gen 4 text is u16 with a 0xFFFF terminator. `gen4/reads` decodes names with the pack charmap in a few lines. | None |
| `lua/admission.lua` | **Not used.** It rehashes the whole artifact (`:88-110,154`), which is unusable at 128-192 MiB. Admission lives in `gen4/entry` on `gameinfo.getromhash()` + anchors, like Gen 3. | None (the reported-digest question goes to the convergence card) |

### 4.2 New NDS-platform module

`lua/nds/hook_binding.lua` is the NDS sibling of `lua/gb_hook_binding.lua:1-87`, with the same API. It lives in a subdirectory: a home for Gen 5 later, and outside the top-level `lua/*.lua` Gen 2 code digest.
- `NDS.new(io,cfg)` returns `{validate, context(site,accept), register, unregister, valid_handle}`.
- `NDS.resident(io,tbl,ovy)` is the one residency reader, also used by `in_battle` and the checkpoint.
- At registration, static sites must match `expected_hex`. Overlay sites get a shape check (id, and the address inside that overlay's RAM range).
- At fire time, in order:
  1. The overlay must be active in `sOverlayRegions[MAIN][0..7]`; otherwise drop with nil, because another overlay shares the RAM (the GB wrong-bank case).
  2. The PC must match (the relationship is measured at G1).
  3. The bus bytes must equal the pin; a mismatch latches failure.

### 4.3 New Gen 4 layer, shared across titles (`lua/gen4/*`; titles bind with packs only)

| Module | Responsibility |
|---|---|
| `entry.lua` | The only file that names a foundation: `PACKS`, `admit{rom_hash, read_ram, header_code}` (hash first, then static-ARM9 anchors including the vanilla bytes at 0x02000CD0, so an hge ROM is never admitted as vanilla; hge by hash only), `build(deps)` |
| `run.lua` | BizHawk bootstrap: io/ev on `ARM9 System Bus`, HUD 256×192, connector, frame loop (copy of `gen3/run.lua` without the nonce block) |
| `reads.lua` | Pure-Lua PK4 crypto (from `memory_nds.lua:35-441`) plus save-chain reads: `[sSaveDataPtr]` → array headers → party/PC/trainer/location/badges/balls; u16 text via the pack charmap; battle reads from pointers captured at hooks, range-checked. Mon key = **PID:OTID** (`server/adapters/base.py:687-691`). |
| `safety.lua` | Read-only checkpoint predicate from pack clauses ([research/checkpoint.md](research/checkpoint.md) §5): CPU parked in `OS_WaitIrq`, `[sFieldSysPtr]` sane with `saveData` equal to `[sSaveDataPtr]`, `taskman == NULL`, no app, no save in flight, refuse from battle setup until the encounter task ends |
| `storage.lua` | Deferred executors (deposit, withdraw, memorialize, faint_slot) over `write_permit`: re-encrypt + checksum; OR `1<<box` into `PCStorage+0x12004`; withdraw rebuilds the party tail from server-cached stats |
| `client.lua` | `core/session` driver: signals set flags, a settle pass diffs party/boxes, hello/tick fields (Gen 3 C-1 field set), `in_battle` = battle overlay resident. Reducer modelled on `gen3/client.lua:350-561`: lifted into `lua/core` if convergence lands first, else copied with a `ponytail:` note. |

### 4.4 Packs

Packs use Gen 3's three-file layout, so pack schemas stay uniform at convergence. There is **no separate symbol store**: provenance (xMAP commit + sha256, ROM sha1, source commit) lives in the profile, the Gen 2 shape (`server/adapters/gen2_gsc.py:139-143`). Pins go in `data/gen4_sources.lock.json`.

- `data/games/gen4_hgss/{profile,engine_signals,write_checkpoint}.json`: titles `heartgold`/`soulsilver`. The profile holds:
  - `save_ptr`, `fieldsys_ptr`, save-array header geometry, block ids
  - party/PC geometry, `pkm {box_size, party_size, exp_bits:32, ability_msb:null}`
  - u16 charmap, overlay table + RAM ranges
  - **per-foundation capabilities** (`boxes 18`, `mons_per_box 30`, `memorial_box 17`)
- `data/games/gen4_hge/…` (per pinned build): the same shape, plus `exp_bits:21`, `ability_msb`, `boxes 30`, `memorial_box 29`, the build commit + map sha256, and a `tables.json` of species/moves/items/abilities/types from the fork source.
- `data/games/gen4_pt/profile.json`: bind check only.
- The generator (`tools/gen_gen4_pack.py`, modes `hgss`/`hge`/`pt`, ndspy on Windows) fails closed when a site's bytes don't resolve.

### 4.5 Server

| File | Change |
|---|---|
| `server/adapters/gen4_codec.py` (new) | PK4 encode/decode, the u16 charmap from pret, and the 512 KiB save (banks, footer, CRC-16; geometry from the footers, box count from the profile). It shares no code with the Lua, so it is the PYDEC oracle. |
| `server/adapters/gen4_hgsspt.py` (kept, game_id unchanged) | Moves onto the codec. `memorial_box_index`/`mons_per_box` come per foundation (hge 30 boxes → 29). hge tables load from `gen4_hge/tables.json` (never `pokemon_data.py`). Drops `_RP_*`/`_is_rp` and the hand-seeded JSON. Fixes the move split, item table and status token. Gift/egg/daycare sets are regenerated from the acquisition manifest. |
| `server/adapters/__init__.py` | Foundation rows: `heartgold`/`soulsilver` → `gen4_hgss`; `heartgold_hge` → `gen4_hge`. Delete the `platinum`/`hgss`/`renegade_platinum` rows (today they would let HG pair with Platinum). |
| `server/manager.py` | Re-admit HGSS to the New-run form (Gen 4/5 were removed by UI commit d8a62085; `tests/unit/test_manager_option_labels.py:119-124` enforces the removal). hge is admitted at G5. |

### 4.6 Legacy retirement and release manifest

These are the **first-class G3a card**.

- **Delete:**
  - `lua/slink_gen4.lua`, `lua/clients/gen4_hgsspt_client.lua`, `lua/games/gen4_hgsspt.lua`
  - the `lua/game_detect.lua:17` and `:27` rows
  - `data/games/gen4_hgsspt/**` (after the data tools are re-pointed)
  - the Gen 4 rows in `tools/make_release.py` (`:52, :64` in `_LUA_ROOT` and `:337` in `_LAUNCHER_SCRIPTS`, **keeping `slink_gen5.lua`**; `:154`, `:160`, `:302-307`)
- **Add:**
  - `_LUA_GEN4` and an `_LUA_NDS` row for `lua/nds/hook_binding.lua`
  - `data/games/gen4_hgss/*` in the data rows
  - an NDS block in `lua/slink.lua` before `game_detect` (like Gen 3's block at `:125-186`): admitted ROM → `gen4/run.lua`; an unpinned Gen 4 header is refused by name; anything else falls through (Gen 5 only)
- **Tests moved in the same card:**
  - `tests/unit/test_make_release_manifest.py:136-140, 160-181` (closure + existence)
  - `tests/unit/test_slink_route.py:203-207`
  - `tests/unit/test_gen4_adapter.py:438-444, 512-514`
  - `tests/fixtures/ui/capabilities.json` (Gen 4 rows)
- `lua/memory_nds.lua` stays for the Gen 5 legacy client.

### 4.7 Seams kept, not built (YAGNI)

- **Companion mailbox:** attaches where Gen 3's `native.lua` does. The recipe is proven in the owner's AP work (overlay 129 @0x023D8000, `Main()` hook 0x02000CD0, fixed pointer slot; for hge, `.data` exported via `rom_gen.ld`). Don't reuse that work's `ap_perframe` stub, which has a pop-to-pc bug.
- **Touch input.**
- **Gen 5** on `lua/nds/`.

### 4.8 Platinum bind falsifiers (D3)

Each module counts as shared only if Platinum can bind it with a pack alone. It fails that test if:
- `nds/hook_binding`: Platinum's residency table isn't a flat `{id, active}` array.
- `reads`: a read needs a pointer chain the profile can't express.
- `safety`: a predicate needs more than one pointer hop.
- `storage`: a runtime checksum update is needed.
- `client`: a needed event has no hookable site.

## 5. Gates

The evidence classes SOURCE, MODEL and PHYSICAL stay distinct. Absent input → named skip; present-but-wrong → FAIL (`tests/TESTING.md:538-564`). **Per-artifact cells** (X table in the ledger) keep the HG, SS, hge and Pt differences honest.

| Gate | Exit evidence | Owner signs |
|---|---|---|
| **G0 Pins + plan** | This plan; the ledger skeleton (Oracles, Pins, X per-artifact table, F/R/S/W/C/D/N rows with S·M·P cells). `data/gen4_sources.lock.json`: ROM sha1s, xmap commits + xMAP sha256, EmuHawk.exe / `dll/melonDS.wbx.zst` / cores dll sha256 (file hashes; waterbox has no module identity). hge fork commit + `test.nds` sha1 recorded, **not admitted**. | Pins + rulings |
| **G1 Platform + hook mechanism** | Probe rows a-m (§5.1), each with a positive and a negative control, PHYSICAL on HG (save copy). SS rows are OPEN until D4. hge rows a/b/g/h/j for information. MODEL: the codec decodes the HG save. | Mechanism works on this host (not semantics or write safety) |
| **G2 SOURCE facts + codec + fixtures** | **Gating:** packs generated, with every `expected_hex` found in the ndspy images of HG **and** SS (both ROMs are present); the acquisition manifest and encounter/area/trainer data regenerated; codec + save-layout checks (newest slot by counter, CRC, torn/duplicate refused, hge geometry); HG fixtures qualified and boot-checked (CONTINUE → save → reload, counter +1, same party keys); the Platinum profile generated from `platinumus.xMAP` by the same generator with no Gen 4 code change. **OPEN until owner input (named skips):** SS fixture qualify/boot-check (D4); Platinum save decode (D3). Coverage map: every signal kind maps to a site **and** a PHYSICAL receipt plan; the oracle is the ledger, not the generator. | The packs as pinned facts |
| **G3 Semantics + checkpoint** (observer mode) | `lua/gen4/*` in a lupa world (`tests/unit/gen4_world.py`, modelled on `gen3_world.py`, residency flippable). Protocol conformance (`test_protocol_conformance.py` on the Gen 4 driver, C-0). Scripted play on HG (+SS once available): one positive and one negative receipt per signal kind. Checkpoint: forbidden states (script, menu, battle setup, save in flight, app running) read false with an empty write log; a liveness bound. `reads == PYDEC` on dumped Main RAM. | Each exercised kind PHYSICAL; the rest listed OPEN |
| **G3a Shared + integration card** (∥ G3) | The §4.6 changes + the `__init__.py` foundation rows + the `manager.py` re-admission, in **one** card with **one writer**. Gate: **full** `pytest tests/unit`, `tools/lua_syntax_check.py`, ruff, the Gen 1 unit lane (`tools/verify_gen1_release.py`; new Gen 4 skip reasons must match the fragments already allowed there, or fail), `slink-adapter-guard` + one independent review; the rejected-hello matrix leaves `links.json` byte-identical. | The shared diff |
| **G4 HGSS RC candidate** | Writes live: benched faint at the checkpoint, the active battler after battle end, box/party/memorialize with the modified-flag bit. Duo rows HG↔SS / SS↔HG in `tools/e2e_duo.py`: an `OPT_IN_GAMES` tuple (so the rows don't silently run every non-opt-in scenario, `:452, :467-488`), `FAMILY_EVIDENCE["gen4_hgss"]` → `check_save_witness_gen4` (NDS SaveRAM, not the Gen 1 CartRAM range at `:991-998`), NDS paths. Scenarios: link, deadzone, linked_faint_active, faint_cmd, boxsync, whiteout, reconnect/wrong-save, clauses/shiny, gift/egg. Each has an oracle, save witness first. The release zip from `tools/make_release.py` boots HG and SS. | Owner plays a live HG↔SS duo from the Manager |
| **G5 hg-engine sub-gate** | Pinned fork build via hgbox → `test.nds` sha1 + nm syms (`build/*linked.o`, `offsets.ini`). `gen4_hge` pack: shared vanilla sites plus per-build sites for the replaced ones ([research/hg_engine.md](research/hg_engine.md) §4). G1 rows a/b/g/h/j re-run on hge. hge fixtures (30-box geometry). hge↔hge duo set. `heartgold_hge` admitted in the Manager. Every rebuild reopens its F/S/W receipts. | Build sha1 + a play session |
| **G6 Release** | `tools/verify_gen4_release.py` (on `release_lanes.py`) full run, zero unexplained skips. Gen 1/2/3 runners green on the shared core. Gen 4 lands on master once, with owner authority: that single landing stales the Gen 2 digest (`server/**/*.py`, `lua/*.lua`), so notify the Gen 2 coordinator and run one re-sweep. | Tag; hge ships only if G5 is signed |

The critical path is G0 → G1 → G2 → G3 ∥ G3a → G4 → G6. G5 branches after G4; its no-emulator prep (build, syms, pack, codec geometry) runs in parallel from G2.

### 5.1 G1 probe rows

Files: `lua/tests/probe_gen4_hooks.lua`, `tests/live/test_gen4_probe_gates.py`. Receipts: `PROBE <row> PASS|FAIL|OPEN`. Each negative control is revert-tested once.

| Row | Positive | Negative control |
|---|---|---|
| a static exec | Hits == frames on a per-frame ARM9 function, for ARM and Thumb sites; record the callback address vs `ARM9 r15` | A never-executed address: 0 hits |
| b overlay residency | `BtlCmd_TryFaintMon` fires on a faint, with ov12 active and bytes == pin | Field play with ov57/58/70/72 at that RAM: every hit has ov12 inactive or mismatched bytes, and is dropped |
| c reliability / JIT | `HandleLoadOverlay` hits == `sOverlayRegions` transitions; core sync settings recorded | A load-free window: 0 hits and no transitions |
| d write hooks | Record whether the callback sees the byte before or after the store | A host `memory.write` does not fire the callback; a wrong-address watch gets 0 hits |
| e unregister / reset | 0 hits after removal and after savestate reload | A liveness hook left registered keeps firing |
| f overhead | 60 fps at real time with 0/1/~15 sites | A deliberately expensive callback measurably drops fps (the probe can see a cost) |
| g domains / registers | Domain sizes and `ARM9 rN` names | A bogus register name is refused, not read as 0 |
| h SaveData | `[0x021D2228]` → SaveData, confirmed by the page signature; `[0x021D4158]+0x0C` agrees | The archived `[0x02000BA8]+0x20` chain is not accepted as `sSaveDataPtr` |
| i persistence | A host write to a decodable party field at idle overworld → in-game SAVE → `.SaveRAM` (short non-Drive path) → PYDEC sees it | The same run without the write leaves the field unchanged; a box write **without** the modified bit is not persisted |
| j identity | `gameinfo.getromhash()` vs file sha1 (HG/SS/hge) | A 1-byte-patched copy hashes differently |
| k RTC | Two boots with the pinned config read the same RTC | An unpinned config differs (or the row records "RTC not configurable") |
| l buttons only | HG/SS/hge reach CONTINUE with A/Start only (D5) | A run that presses nothing stays at the title |
| m CPU census | ARM9 PC over overworld/menu/battle/save; the idle PC lies in `OS_WaitIrq` | During a save or script the PC is outside the park range |

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
| S | hook contract (residency + bytes); battle begin/end; faint (doubles mapping); capture/mon_given (party and the PC-full path); pc_move; whiteout; map_load; evolution (menu = save party; post-battle = setup copy); NPC trade; save; **poison_faint N/A** (cited); egg hatch; roamers S-14g; Bug Contest S-15g (catch at the result); Safari S-16g; statics/gifts S-17g |
| W | armed gate; checkpoint predicate; benched faint; active faint after battle end; box/party/memorialize with the modified bit; pause/NACK; write ownership; following-Pokémon consistency W-8g |
| C | C-0 conformance; C-1 hello fields (Gen 3 set) + admission; reconnect/wrong save; dashboard; faults; pairing (`gen4_hgss` vs `gen4_hge` isolated, Pt refused); idempotency |
| D | link; deadzone; linked_faint_active; faint_cmd; boxsync; whiteout; reconnect; clauses/shiny; gift/egg; doubles (or a limit) |
| Limits (candidate) | Link trades; native panel/text; Pal Park and Pokéwalker (external); Wi-Fi/GTS/Mystery Gift; roamer/contest/safari PHYSICAL (story-gated, S+M only); Explode/Rival Swap (RR only); in-battle prompt active faint (post-G4) |

## 7. Cards

Up to 3 subagents run at once, model explicit, plus headless OMP for checks. Exclusive files never overlap. The coordinator alone runs emulator lanes, one at a time, own PIDs only, on short non-Drive paths.

| Card | Model | Exclusive files | First falsifier | Exit |
|---|---|---|---|---|
| C0-1 ledger | Sonnet | `docs/gen4_requirements.md` | OMP: a row without an oracle or an S·M·P cell | Ledger skeleton committed (research and PLAN are already the coordinator's) |
| C0-2 pins | Haiku | `tools/gen4_pins.py`, `data/gen4_sources.lock.json`, `tests/unit/test_gen4_pins.py` | A 1-byte-flipped ROM copy → FAIL; an absent ROM → named skip | `--json` pin table |
| C1-1 probes | Opus | `lua/tests/probe_gen4_hooks.lua`, `tests/live/test_gen4_probe_gates.py` | Each negative control can go red (revert-tested) | Rows a-m receipts |
| C1-2 pack generator (G1 subset) | Sonnet | `tools/gen_gen4_pack.py`, `data/games/gen4_hgss/profile.json`, `tests/unit/test_gen4_pack.py` | An HG/SS gameplay symbol mismatch → red; a site byte mismatch → red | Profile with probe addresses + provenance |
| C1-3 codec | Sonnet | `server/adapters/gen4_codec.py`, `tests/unit/test_gen4_codec.py`, `tests/unit/test_gen4_save_layout.py` | A flipped byte → checksum refusal; a torn slot → refused | HG save decodes; hge geometry parses; Pt skip is named |
| C1-4 fixture infra | Haiku | `tools/gen4_fixtures.py`, `tests/unit/test_gen4_fixtures.py` | A config with no NDS SaveRAM entry → raises | Per-run config + short lane path |
| G2+ cards | Opus/Sonnet | `lua/nds/hook_binding.lua`, `lua/gen4/*`, `tests/unit/gen4_world.py`, `tests/unit/test_gen4_*.py`, `lua/tests/gen4_*.lua` (walk/scripted play), data tools, the G3a integration set (§4.6), `tools/e2e_duo.py` rows, `tools/verify_gen4_release.py`, `tools/gen4_hge_build.py` | Per card | Per gate |

Wave 1 is C1-1 ∥ C1-2 ∥ C1-3; C0-1, C0-2 and C1-4 take the next slots. Emulator rows need C1-2's addresses.

## 8. Orchestration

- The Gen 4 lane is registered in `C:/Users/howar/.claude/hooks/slink/WORKTREE_REGISTER.md` and as `gen4_lane_note` + worker cards in the `RC_MASTER_GUIDE.md` checkpoint. The coordinator alone edits both.
- The Gen 2 and Gen 3 coordinators are told about D1 and the single landing.
- Resume note: `docs/gen4/RESUME.md`.
- No push, master merge or tag without owner authority. G-gates are recorded as signed only on an explicit owner yes.

## 9. Verification

- **Standing:** `pytest tests/unit` (full at G3a/G6), `tools/lua_syntax_check.py` (lupa), ruff.
- **G1:** `SLINK_LIVE=1 pytest tests/live/test_gen4_probe_gates.py`.
- **Codec:** `pytest tests/unit/test_gen4_codec.py` on the owner's HG/hge saves (SS/Pt named skips until provided).
- **G3a:** `pytest tests/unit/test_make_release_manifest.py tests/unit/test_slink_route.py tests/unit/test_gen4_adapter.py` inside the full suite, plus `tools/make_release.py` preflight.
- **G4:** `tools/e2e_duo.py --game gen4_hgss --scenario all` (save witness + oracle); then the owner's live HG↔SS Manager session.
- **Non-regression:** the Gen 1/3 release runners, and one Gen 2 re-sweep at the single master landing.
