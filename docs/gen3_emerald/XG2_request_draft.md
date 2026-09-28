# XG2 request: expansion generic reads + adapter (draft, 2026-09-27)

> **SIGNED 2026-09-27 by the owner in chat: "All gates are signed."** (Recorded by the combined Gen 3 coordinator, claude 30c21a7a. This covers every pending Gen 3 gate: G4, G5, EG4, XG1 and XG2. It is not approval of the master landing, which needs its own explicit owner approval, ruling 41.)

- **Branch:** `claude/gen3-exp-x23` (worktree `C:/slink-wt/g3-exp`), base integration `4fa041bf`.
  Local only: not pushed or merged.
- **Plan:** `docs/gen3_emerald/PLAN.md` X2 row ("Generic reads + adapter" → **XG2**).
  **Ledger:** `docs/gen3_emerald/REQUIREMENTS.md` XC-1 (+ the X2 part of XF rows).
- **Frozen cut:** ``7c550558` (code); receipts were taken at the cuts each receipt's IDENTITY line names`. Precondition: XG1 (`docs/gen3_emerald/XG1_request_draft.md`).

## 1 What XG2 signs

- **One record layout, from the pack.** `profile.derived` of the reference build carries the masked
  lanes (species:11, heldItem:10, moves:11, experience:21, pp:7, markings:4, the 12-char nickname
  lanes, pokeball and abilityNum relocated, shinyModifier), generated from the compiler's bitfield
  facts. `lua/gen3/reads.lua`, `server/adapters/gen3_codec.py` (`decode_*_masked`) and the server
  adapter (`EXPANSION_PARTY_LAYOUT`, now read from that block) decode with it. Vanilla packs carry
  none of these keys: their decode is byte-for-byte unchanged.
- **reads == PYDEC** on the expansion build: MODEL (a real fixture's party + box 0 through the real
  reads.lua == gen3_codec) and PHYSICAL on live RAM of ROM 28877d73 (32 mon lines agree on every
  field; the planted flip is caught).
- **Battle geometry from the pack:** reads.lua and the client take `BATTLE_MON_SIZE`/`BATTLE_MON_HP_OFF`
  from the profile (140 / 42 on the expansion build; pret's 0x58 / 0x28 by default).
- **Save layout:** `gen3_codec.TITLE_EXPANSION` (SaveBlock1 15568, PokemonStorage 34144) bound to
  facts.json; its party/box decode refuses without the build's layout.
- **The full adapter contract:** every public `GameRulesAdapter`/`GamePresentationAdapter` method has a
  decided answer (test enumerates base.py); `encounter_table` None is the recorded reference-build
  limit; randomized content is not bound (`rom_content_fingerprint`/`ingest_rom_content` None).
- **The X2-ADAPTER-FIX items** (review cx-7d33cf12) were already fixed in `401974cc` (32-bit OT
  contract = the shared parser, category `.get` → status, debug area catalog without an FR/LG
  fallback) and are covered by `tests/unit/test_gen3_expansion_adapter.py`.
- **e2e decode:** `tools/e2e_duo.py gen3_decode` uses the expansion layout for that title.

**XG2 does NOT sign:** admission/routing (still refused in production); the shinyModifier wire
integration (§6 decision 1); anything in XG3.

## 1a Status

| Commit | What |
|---|---|
| `be2c2fa7` | profile-driven record layout + full adapter contract (red first) |
| `e76b5e8d` | gen3_codec TITLE_EXPANSION flash layout |
| `53210955` | reads.lua/client battle geometry from the profile |
| `7c550558` | reads == PYDEC: comparator for the expansion title, MODEL + live receipt |
| `1df28d00` | e2e_duo expansion decode |

## 2 Per-item status

| Claim | SOURCE | MODEL | PHYSICAL | Evidence |
|---|---|---|---|---|
| layout keys from facts; one representation for Lua/codec/adapter | ✓ | ✓ | ✓ | `test_gen3_expansion_masks.py` (shipped profile), `test_gen3_expansion_adapter.py::test_expansion_party_layout_matches_facts_json_bitfields`; `probes/reads_pydec_exp_2026-09-27.txt` |
| reads == PYDEC | — | ✓ | ✓ | `test_gen3_exp_reads.py::test_reads_equal_pydec_on_the_expansion_fixture`; `probes/reads_pydec_exp_2026-09-27.txt` |
| battle geometry from the profile | ✓ | ✓ | ◐ | `test_gen3_exp_reads.py` (battler stride per title); used live by `probes/duo_x3_whiteout_*` (lose_active read hp/pp) |
| codec expansion save layout | ✓ | ✓ | ✓ | `test_gen3_codec_expansion.py`; every X3 save witness decoded through it (`probes/duo_x3_*_pydec.txt`) |
| adapter contract | ✓ | ✓ | ✓ | `test_gen3_expansion_adapter.py::test_every_base_contract_method_has_a_decided_expansion_answer`; server paired/linked/memorialized/rebuilt live (`probes/duo_x3_*`) |
| FR/LG/RR/E unchanged | — | ✓ | — | full unit suite (§4); generator `--check` byte-identical |

## 3 Defects found and fixed

- The adapter kept a hand-copied layout dict next to a profile that carried the facts in a shape no
  decoder read (`be2c2fa7`).
- reads.lua used pret's BattlePokemon stride for every title (battler ≥ 1 read the wrong memory on
  the expansion build) (`53210955`).
- `gen3_reads_pydec.py` had no expansion title and decoded unmasked (`7c550558`).

## 4 MODEL evidence

- Full unit suite on this cut: `12427 passed, 4366 skipped, exit 0 (`pytest tests/unit`, at `7c550558`, 10:41; plus a B007-only test lint fix committed after)`.
- `python tools/lua_syntax_check.py`: OK. `ruff` clean on every file this lane touched.

## 5 Limits carried forward

- Production still refuses the build (unrouted, profile unadmitted); every live receipt ran through
  the duo driver's TEST-ONLY seam (`gen3_exp` row only, logged `TEST-ONLY admission/route`).
- BoxPokemon.language shares its byte with hiddenNatureModifier:5; reads.lua reports the raw byte
  (no field compares it; no mask added).
- `ability_description` is empty (the extractor supplies names only); sprites use national-dex base
  art, not form art (unchanged from XC).

## 6 Owner decisions

### 1. shinyModifier needs a shared `server/state.py` change — options

**What the game does** (expansion `e8bd1cd7`): `GetBoxMonData(MON_DATA_IS_SHINY)` is
`(GET_SHINY_VALUE(otId, personality) < SHINY_ODDS) ^ boxMon->shinyModifier`
(`src/pokemon.c:2480-2483`); `SetBoxMonData(MON_DATA_IS_SHINY)` stores the modifier that makes the
wanted answer (`:2910-2915`). So a mon can be shiny with a non-shiny PID/OT (modifier 1) or not
shiny with a shiny PID/OT (modifier 0 suppression via `OT_ID_RANDOM_NO_SHINY`, trainer mons only).

**What SLink does now:** `server/state.py:2248` `self.adapter.is_shiny(key)` — key only
(`PID:OTID`). `Gen3ExpansionAdapter.is_shiny(key, shiny_modifier=0)` already implements the XOR, and
`lua/gen3/reads.lua` already decodes `mon.shiny_modifier` (`SHINY_MODIFIER_FIELD`), but the capture
wire event does not carry it and state.py does not pass it.

**When the modifier is nonzero on the reference build** (source at the pin): every nonzero source is
off or unreachable in normal play — `ComputePlayerShinyOdds` rerolls (`src/pokemon.c:868-898`) come
from the Shiny Charm and Lures (no map script or mart gives either: `data/maps` has no
`ITEM_SHINY_CHARM`/`ITEM_*LURE`), chain fishing (`I_FISHING_CHAIN FALSE`) and DexNav
(`DEXNAV_ENABLED FALSE`); `P_FLAG_FORCE_SHINY`/`P_FLAG_FORCE_NO_SHINY` are 0; `UpdateMonPersonality`
has no caller; the other writers are the Battle Frontier (writes refused, §0) and the debug menu
(`DEBUG=0`). **So on the reference build the key-only rule equals the game's `IsShiny` in every
reachable capture.** Hacks onboarded later (X4) routinely enable those features; a charm/lure/chain
reroll then makes a shiny whose key reads non-shiny, and the server would link it instead of applying
the Shiny Clause.

| Option | Change | Cost / risk |
|---|---|---|
| **A. Carry the modifier** | client `capture` (and `party_to_box`/`stats_cache` where a shiny flag matters) sends `shiny_modifier` when the pack decodes it; `base.py` gains `is_shiny_capture(key, msg)` defaulting to `is_shiny(key)`; `state.py:2248` calls it; the expansion adapter XORs; protocol doc row | shared `server/state.py` + `base.py` + `lua/gen3/client.lua`: Gen 2 CODE_DIGEST re-sweep (~2 h), guard + review; vanilla behaviour unchanged by default |
| **B. Key-only, recorded** | none; record "reference build: exact (proof above); onboarded hacks: modifier ignored" as a limit, and make X4's onboarding recipe (TEMPLATES T6) refuse a hack whose config enables a reroll source until A lands | no shared change now; the RC for the reference build is exact; every onboarded hack is gated |
| C. Hybrid | B now, A as the first X4 card | as B, then A's cost at X4 |

**Recommendation:** C — the reference build does not need A to be exact, and A's shared-code cost is
best paid once, with the first hack that needs it, in the same Gen 2 batch as other server changes.

### 2. Accept `tests/fixtures/gen3/exp_*.sav` as disclosed O-33 SYNTH fixtures

The Emerald seed of the same kind transplanted into the build's layout, then CONTINUE + in-game SAVE
on the build itself; only the game's re-save is kept (README section, receipt
`probes/fixtures_exp_2026-09-27.txt`). `exp_center.sav` is an expansion-only kind (the town seed moved
onto the Oldale Center respawn tile) for the Center CPU census.

### 3. Accept `gen3_exp` registered in `Entry.PACKS` (not routed, not admitted)

The E2-ENTRY precedent: the build's hash names its own pack (never gen3_emerald's), `admit_routed`
refuses it as "not yet routed", no `header_code`, and the player zip ships its five pack files
(Entry.admission_table opens every registered pack — the F1 rule). The x1 test that asserted
"not in Entry.PACKS" now asserts this contract.

## 7 How to verify this draft

```sh
source C:/slink-wt/g3-env.sh
python -m pytest -q tests/unit/test_gen3_expansion_masks.py tests/unit/test_gen3_expansion_adapter.py \
  tests/unit/test_gen3_codec_expansion.py tests/unit/test_gen3_exp_reads.py tests/unit/test_gen3_exp_entry.py
python tools/gen3_reads_pydec.py <dump> --title emerald_expansion_28877d73   # the live receipt's dump is inline
```

## Appendix: X3 progress on this cut (feeds XG3; not requested for signature here)

| Row | Result | Receipt |
|---|---|---|
| Probe hooks (P1 a/b/c/d/e/g) | PASS | `probes/hooks_exp_2026-09-27.txt` |
| Frame-end CPU census: outdoors (BIOS IntrWait; hook → IRQ entry R14 0x1F8) and Center (wireless busy-wait) | PASS 1800/1800 idle both | `probes/census_exp_overworld_2026-09-27.txt`, `probes/exp_cpu_irq_bios_2026-09-27.txt`, `probes/census_exp_center_2026-09-27.txt` |
| Generated per-build title syms (`lua/tests/gen3_title_syms_exp_28877d73.lua`, x3 lane) wired through `gen3_title_syms.lua` `for_title`/`sym_path`/`emerald_engine` | used by every duo | — |
| faint_cmd_gen3 (linked faint → memorial) | PASS at `27bd720f` (before the CPU/reads fixes: re-run pending) | `probes/duo_x3_faint_cmd_*` |
| link_gen3 (capture pairing) | PASS attempt 1 at `c1b5c738` | `probes/duo_x3_link_*` |
| whiteout_gen3 (whiteout, rebuild from both PCs, Center landing) | PASS at `53210955` | `probes/duo_x3_whiteout_*` |
| boxsync_gen3 (PC deposit/withdraw mirrored) | PASS at `272d0a0b` (before the CPU/reads fixes: re-run pending) | `probes/duo_x3_boxsync_*` |
| linked_faint_active_gen3 (in-battle P+H) | not run: HOLD fallback (no Perish+hand-off plan for struct Volatiles) | `tests/unit/test_e2e_duo_gen3_exp.py` |
| Observer (shadow) receipts per site kind | not run separately; the duo receipts exercise capture_wild, battle_begin/end, whiteout, save, map_load and the PC diff | — |
