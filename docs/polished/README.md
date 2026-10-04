# docs/polished — index

Polished Crystal **v3.2.3** support: the SLink companion overlay, the pack, the ROM tables, and
the reverse-engineering record behind them.

**Reconciliation rule for this directory.** These documents were written one after another and
later ones overturned earlier statements. Nothing is deleted. Every superseded statement keeps its
original wording and carries a visible `SUPERSEDED (see X §n)` marker plus a one-line correction,
so a reader can see what was believed, when it was believed, and what replaced it.

Start at **[README](#1-documents)**, then the document your question needs. If two documents
disagree, **the later one wins** and the earlier one carries the marker.

## 1. Documents

| Doc | Purpose | Status | Authoritative for | Superseded |
|---|---|---|---|---|
| `ENGINE_SITES.md` | Engine signal sites and write checkpoints, vanilla→Polished mapping | current, reconciled | the site **inventory** and verdicts; §2's `battle_faint`/`trainer_ready` rows and §9 risks 2 and 4 are **marked superseded** | §2 `trainer_ready` (`.partyloop` is not the party build), §2 `battle_faint` (located at `0f:44ca`), §9 risk 2, §9 risk 4 |
| `BATTLE_FLOW.md` | `battle_faint` boundary, `battle_hold` oracles, write windows | current, reconciled | the faint boundary `0f:44ca`, the two hold oracles, the hold point before `call DetermineMoveOrder` | the `DetermineMoveOrder` priority UNVERIFIED note and the `wCurOTMon == $FF` rival gate are **marked superseded** (see `EXPLODE_RIVAL.md` §6–§7) |
| `EXPLODE_RIVAL.md` | Explode Mode and Rival Team Swap writers | **current, newest for battle writes** | `wCurPlayerMove` IS read via `GetBattleVarAddr`'s `BATTLE_VARS_MOVE` (§6); the rival gate is the PC at `0f:47dd` with the commit at `0f:47cc` and last consumption at `0f:480d` (§7); the trainer send-out copy site from ROM bytes (§10) | §1 is explicitly overturned by its own §6 |
| `HOOKS.md` | Companion overlay hook/edit sites and native symbols | current | the hook inventory (§2), the native symbol table (§3), where new code may be INCLUDEd (§4); §8 is the settled frame-hook correction | none outstanding — §9 records the reconciliation check that found none |
| `RAM.md` | RAM/structure map, Polished vs vanilla pokecrystal | current | symbol tables (§1), struct layouts (§2), species/badge encoding (§3); carries its own coordinator corrections (`CaughtLevel +29` / `CaughtLocation +30`, Kanto badge bits 4/5 swapped) | not edited by this pass; see [Mismatch](#4-mismatch) |
| `NEWBOX.md` | PC storage ("newbox") reader/writer spec | current | SRAM map (§1), box slot → pokedb entry (§2), per-entry checksum (§3), SLink operations (§6); 20 boxes, 20 entries per box | §8 carries the `docs/newbox_format.md` errata |
| `ROMTABLES.md` | ROM-side tables (wild/tree/fishing/roamers/statics) | current | the table addresses and record layouts | — |
| `CLIENT.md` | The Polished Lua client composition | current | client-side reads, profile/charmap wiring | — |
| `UPR_HANDLER.md` | The SLink fork of Pokémon Unbound Randomizer for Polished | current | what the randomizer may rewrite, and what it must not | — |
| `ACQUISITION_RULES.md` | Soul Link facts for Polished-only acquisition paths | current, **facts only — no decisions** | Wonder Trade, eggs, the 9 NPC trades, formed statics, swarms, and which identity mutations break a link key | — |

### The four markers added in this pass

1. `ENGINE_SITES.md` §2 `trainer_ready`: `.partyloop` is the **boss-trainer happiness walk**; the
   enemy party is built by `farcall ReadTrainerParty` at `core.asm:8040` (`BATTLE_FLOW.md` F5,
   `EXPLODE_RIVAL.md` §10).
2. `ENGINE_SITES.md` §2 `battle_faint`: located at **`0f:44ca`**, ROM-verified (`BATTLE_FLOW.md` §1).
3. `ENGINE_SITES.md` §9 risks 2 and 4: the `battle_hold` checkpoint is **not** blocked
   (`LostBattle` `0f:4ff6`, `HasPlayerFainted` `00:3684`), and `expected_hex` is now generated.
4. `BATTLE_FLOW.md`: `DetermineMoveOrder` **does** read `wCurPlayerMove`, and the rival gate is the
   **PC at `0f:47dd`**, not `wCurOTMon == $FF` (`EXPLODE_RIVAL.md` §6–§7).

## 2. Generated data

| File | Produced by | Check |
|---|---|---|
| `data/polished/polishedcrystal.sym` / `.map` | `tools/build_polished_syms.py` | `python tools/build_polished_syms.py --check` |
| `data/polished/polished_slink.sym` / `.map` | `tools/build_polished_companion.py` | `python tools/build_polished_companion.py --check` |
| `data/polished/build_provenance.json` | `tools/build_polished_syms.py` | as above |
| `data/polished/overlay_provenance.json` | `tools/build_polished_companion.py` | as above |
| `data/polished/upr_polished_entries.ini` | `tools/gen_upr_polished_ini.py` | `python tools/gen_upr_polished_ini.py --check` |
| `data/polished/script_sites.json` | `tools/gen_polished_script_sites.py` | `python tools/gen_polished_script_sites.py --check` |
| `data/polished/free_space.txt` | `tools/build_polished_syms.py` | as above |
| `data/games/polished_crystal/*.json`, `charmap.lua` | `tools/gen_polished_pack.py` | `python tools/gen_polished_pack.py --check` |
| `data/games/polished_crystal/profile.json` | `tools/gen_polished_profile.py` | `python tools/gen_polished_profile.py --check` |
| `data/games/polished_crystal/engine_signals.json`, `write_checkpoint.json` | `tools/gen_polished_engine_sites.py` | `python tools/gen_polished_engine_sites.py --check` |

`ENGINE_SITES.md` §2 and §9 and `BATTLE_FLOW.md` are **human documents**: they describe the sites
and windows; the generated JSON is the artefact the runtime reads.

## 3. UPR patches

`patch/upr/` applies in order. `0016`–`0018` are the Polished ones:

| Patch | Adds |
|---|---|
| `0016-slink-Polished-Crystal-3.2.3-handler-cut-1.patch` | the Polished Crystal 3.2.3 ROM handler |
| `0017-slink-Polished-Crystal-wild-encounters.patch` | the eight wild-encounter tables |
| `0018-slink-Polished-Crystal-trainers-starters-statics-trades.patch` | trainer parties, starters, statics and the in-game trades |

`0001`–`0015` are the earlier pure/pureRGB overlays and are unrelated to Polished.
`tools/gen_upr_polished_ini.py` renders the offsets section UPR consumes; see `UPR_HANDLER.md`.

## 4. Mismatch

**`RAM.md:72` — `wTextboxFlags` bank.** RAM.md records `01:CFF4` in *both* the vanilla and the
Polished column and marks it `same`; `data/polished/polishedcrystal.sym:65521` places
`wTextboxFlags` at **`00:cff4`**. The address matches, the **bank does not**. RAM.md was outside this
pass's scope and is **not** edited here; a one-line correction is warranted. Every other symbol
sampled from RAM.md's tables (72 rows matched by exact name) agrees with the `.sym` — including the
row-43 control `wCurPlayerMove` vanilla `00:C6E3` → Polished `00:C540`.

## 5. Machine-checkable citations

Each entry names an absolute path, a line and an exact substring on that line.

```json CLAIMS
[
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 65521,
  "expect": "00:cff4 wTextboxFlags"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/RAM.md",
  "line": 72,
  "expect": "| `wTextboxFlags` | `01:CFF4` | `wTextboxFlags` | `01:CFF4` | same |"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/RAM.md",
  "line": 186,
  "expect": "| CaughtLevel | (+29, packed with time) | +29 |"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/RAM.md",
  "line": 187,
  "expect": "| CaughtLocation (`CaughtGender` alias) | +30 | +30 |"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/RAM.md",
  "line": 350,
  "expect": "Kanto swaps bits 4/5"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/RAM.md",
  "line": 43,
  "expect": "| `wCurPlayerMove` | `00:C6E3` | `wCurPlayerMove` | `00:C540` | moved |"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 64052,
  "expect": "00:c540 wCurPlayerMove"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 70054,
  "expect": "00:ff8f hVBlankOccurred"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 70139,
  "expect": "00:ffd7 hDelayFrameLY"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 70046,
  "expect": "00:ff85 hScriptVar"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 70047,
  "expect": "00:ff87 hROMBank"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 49220,
  "expect": "00:b208 sBackupGameData"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 49229,
  "expect": "01:a007 sCheckValue1"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 49237,
  "expect": "01:ad0d sChecksum"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/ENGINE_SITES.md",
  "line": 45,
  "expect": "**SUPERSEDED (see BATTLE_FLOW.md F5, EXPLODE_RIVAL.md \u00a710):**"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/ENGINE_SITES.md",
  "line": 42,
  "expect": "**SUPERSEDED (see BATTLE_FLOW.md \u00a71):** the replacement was located"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/ENGINE_SITES.md",
  "line": 185,
  "expect": "`data/games/polished_crystal/engine_signals.json`, generated by"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/ENGINE_SITES.md",
  "line": 173,
  "expect": "**SUPERSEDED (see BATTLE_FLOW.md \u00a71\u2013\u00a72):** the counterpart is located"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/BATTLE_FLOW.md",
  "line": 162,
  "expect": "> **UNVERIFIED (SUPERSEDED \u2014 see EXPLODE_RIVAL.md \u00a76):**"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/BATTLE_FLOW.md",
  "line": 192,
  "expect": "**SUPERSEDED (see EXPLODE_RIVAL.md \u00a77):** the paragraph below treats"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/BATTLE_FLOW.md",
  "line": 240,
  "expect": "**SUPERSEDED (EXPLODE_RIVAL.md \u00a76): the priority read is confirmed"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/BATTLE_FLOW.md",
  "line": 241,
  "expect": "**SUPERSEDED (EXPLODE_RIVAL.md \u00a77): the gate is the PC at `0f:47dd`"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/BATTLE_FLOW.md",
  "line": 237,
  "expect": "**SUPERSEDED: address is ROM-verified**"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/BATTLE_FLOW.md",
  "line": 257,
  "expect": "**Both are now answered \u2014 see `EXPLODE_RIVAL.md` \u00a76"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/EXPLODE_RIVAL.md",
  "line": 247,
  "expect": "## 6. CORRECTION \u2014 turn ordering **does** read `wCurPlayerMove`"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/EXPLODE_RIVAL.md",
  "line": 323,
  "expect": "## 7. Rival window \u2014 the closing edge"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/EXPLODE_RIVAL.md",
  "line": 421,
  "expect": "## 10. The trainer send-out copy site \u2014 proven from ROM bytes"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/HOOKS.md",
  "line": 775,
  "expect": "## 9. Reconciliation pass (2026-10-04, cx-e1bb41ed)"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/HOOKS.md",
  "line": 778,
  "expect": "**No statement in HOOKS.md required a supersession marker**"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/NEWBOX.md",
  "line": 15,
  "expect": "### 1.1 Box metadata: 20 records, two copies"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/ACQUISITION_RULES.md",
  "line": 12,
  "expect": "## 0. What \"acquisition\" means here, and the vanilla baseline"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/CLIENT.md",
  "line": 1,
  "expect": "# Polished Crystal client \u2014 what it takes to make the Lua client RUN"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/ROMTABLES.md",
  "line": 1,
  "expect": "# Polished Crystal 3.2.3 \u2014 ROM encounter tables vs `lua/gen2/rom.lua`"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/UPR_HANDLER.md",
  "line": 1,
  "expect": "# UPR handler for Polished Crystal 3.2.3 \u2014 design"
 }
]
```
