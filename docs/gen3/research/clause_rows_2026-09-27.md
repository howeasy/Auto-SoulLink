# CLAUSE-ROWS-G3

Branch: `codex/gen3-clause-rows`, based on integration
`1ec32e80fe4314c7a1ca7b88bf9adccaf656afcd`.

**SOURCE / MODEL implementation. No emulator was launched for this card.**
Every row below still needs the coordinator's native run, save witness and
independent flushed-save oracle. A successful fixture builder is setup evidence.

| Row | Native carrier and required result | Pairings |
|---|---|---|
| `species_clause_gen3` | A catches and becomes server-confirmed pending; B RUNs notified duplicates, then catches another family. Require the actual reroll branch, alive pair and saved catches. | FR/LG, LG/FR, E/E, RR/RR |
| `species_family_gen3` | Disclosed evolved lead and staged server link. A encounters a **different species** in that family and RUNs after the real dupes prompt. The original link and saved records survive. | all four; explicitly selected |
| `gender_clause_gen3` | Ordered native catches. Own-ROM PID/gender ratio explains B's rejection; keyed HP-zero, memorial, prompt, sounds and retryable area; A stays quarantined. | all four |
| `type_clause_gen3` | Same carrier; own-ROM types must explain the exact shared-type prompt and saved disposition. | all four |
| `ball_gate_gen3` | Native wild KO and RUN at zero balls cause no Soul Link death. Native reward activates both gates; then real catches form one alive link and save. Pocket, reward flag, native faint site and server receipts are required. | all four |
| `release_gen3` | A natively DEPOSITs/WITHDRAWs/DEPOSITs/RELEASEs. B mirrors the moves and its boxed partner reaches the memorial after release. A's released key is absent from every saved location. | all four |

The reference carriers are Gen 1 `species_clause_new`, `type_clause_new` and
`pc_ops_new`, plus Gen 2 gender/clause and pre-ball encounter controls. Release
keeps B connected to verify its saved memorial. A boxed record has no HP field:
`lua/core/session.lua` drops `force_faint` for a key absent from the party, then
the queued memorial command moves it. This row claims that actual boxed
consequence, not an invented boxed HP-zero write.

The ball row covers the complete gate flow requested by the coordinator:
native pre-ball faint (not a Soul Link death), pre-ball RUN (not a dead zone),
native activation, then actual catch/link/save. It reuses `ctx.lose_active`,
the existing forced-party `send_out`, normal RUN and `scenario_gen3_link.lua`.
Both server receipt of each faint and absence of propagated death are checked;
the final link oracle requires exactly the two real post-activation catches.

## Title facts and setup

`tools/gen3_clause_rows.py` reads species types, gender ratios and evolution
families directly from the booted title's ROM. FR/LG/E use their own `.sym`
table heads. RR uses its base-stat pointer and the existing RR-SYNTH evolution
table/16-slot derivation (`tools/gen3_fixtures.py`). Pointer/reader anchors are
required; a historical companion whole-image hash is not substituted for the
production loader's current admission. The encounter oracle reads the respective
`firered_encounters.json`, `leafgreen_encounters.json`,
`emerald_encounters.json` or `rr_encounters.json`.

The family setup replaces A's lead with Pidgeotto (FR/LG), Mightyena (E), or
Bibarel (RR), retaining PID/OT/moves. Level 25, EXP, stats, healthy HP, status and
nickname are disclosed SYNTH edits. Expected wild relatives are Pidgey,
Poochyena and Bidoof, respectively. All stats/EXP come from that ROM. An
unrelated first foe is an unobserved branch, never family qualification.

Every ball setup has an HP1 lead and a healthy Lv25 reserve. The reserve's
species/stats/EXP use the same own-ROM builder described above; the fast reserve
supports native escape after the pre-ball KO. No ball or reward flag is written
during the behavior under test. The setup and native rewards are:

* FR/LG: zero-ball seed at Viridian Forest `1.0 (4,41)`, next to local object 6
  at `(5,41)`, item flag 342. The native script grants **one** Poke Ball.
* E: zero-ball seed with Mudkip and a healthy evolved reserve at Rusturf Tunnel
  `24.4 (3,2)`, next to local object 3 at `(3,1)`, flag 1048. Native script grants
  **one** Poke Ball. The tunnel's native encounters support the pre-ball RUN.
* RR: zero-ball `rr_battle.sav` supplies the original pre-parcel story. The
  disclosed setup copies the same-OT native reserve from `rr_battle2.sav` and
  prepares its own-ROM stats; story flags/vars and the ball pocket stay intact.
  The existing
  `gen3_rr_battle_fixture.lua` parcel route now exports an already-booted helper
  helper reports the native reward, waits for the runner's capture release,
  and catches the first encounter on its return to Route 1. A setup flee must
  not consume that first legal encounter. RR's decoded script grants **ten**
  Poke Balls and sets dex flag `0x829`, not vanilla's five-ball reward
  (`rr_fixture_route_2026-09-24.md`). Its original standalone fixture workflow
  still proceeds through catch/save.

The FR/LG/E item scripts decode to
`1a008004001a01800100090102` (`finditem ITEM_POKE_BALL, 1; end`), from each ROM's
map-event pointer. Source tests reuse `rr_ingame_trades.py`'s event parser with
the title's own map-group head and `gba_map.py` for approach/pace geometry.
RR's forest item-ball object was examined, but no approach was established from
the decoded geometry; the already proven parcel path avoids a guessed route.
No shop or intro RAM binding was added. New reads use existing title bindings
and the existing profile-backed party, enemy and SaveBlock readers.

`EMERALD_RULE_KINDS` names builder-only fixtures. It does not add unbuilt saves
to the registry of committed native Emerald fixtures or weaken those tests.
The coordinator must run `make-emerald` to produce their native re-saves.

## Coordinator commands

Run in the integrated checkout after merging this branch and preparing that
checkout's admitted ROM/companion artifacts. These are PowerShell commands.
FR/LG/RR synth builders below do not launch an emulator. The two Emerald
builders **do**, and belong to the coordinator's emulator lane.

```powershell
$env:SLINK_GEN3_ROMS = 'E:/Google Drive/SLink'
$env:SLINK_PRET_EMERALD_SRC = 'E:/Google Drive/SLink/.cache/pret/pokeemerald'
$env:SLINK_PRET_EMERALD = $env:SLINK_PRET_EMERALD_SRC

foreach ($title in @('firered', 'leafgreen')) {
    foreach ($kind in @('ball_gate', 'family')) {
        python tools/gen3_fixtures.py make-frlg-synth --title $title --kind $kind --seed "tests/fixtures/gen3/${title}_party_battle.sav" --out "tests/fixtures/gen3/${title}_party_${kind}_synth.sav"
        if ($LASTEXITCODE) { throw "SYNTH failed: $title $kind" }
    }
}
python tools/gen3_fixtures.py make-rr-synth --kind family --seed tests/fixtures/gen3/rr_battle2.sav --out tests/fixtures/gen3/rr_family_synth.sav
if ($LASTEXITCODE) { throw 'RR family SYNTH failed' }
python tools/gen3_fixtures.py make-rr-synth --kind ball_gate --seed tests/fixtures/gen3/rr_battle.sav --out tests/fixtures/gen3/rr_ball_gate_synth.sav
if ($LASTEXITCODE) { throw 'RR ball gate SYNTH failed' }
python tools/gen3_fixtures.py derive-b --rr tests/fixtures/gen3/rr_ball_gate_synth.sav tests/fixtures/gen3/rr_ball_gate_synth_b.sav
if ($LASTEXITCODE) { throw 'RR ball gate B derivation failed' }

foreach ($kind in @('family', 'ball_gate')) {
    python tools/gen3_fixtures.py make-emerald --kind $kind --rom 'E:/Google Drive/SLink/Pokemon - Emerald Version (USA, Europe).gba' --out "tests/fixtures/gen3/emerald_${kind}.sav"
    if ($LASTEXITCODE) { throw "Emerald native re-save failed: $kind" }
}
python tools/gen3_fixtures.py derive-b --title emerald tests/fixtures/gen3/emerald_ball_gate.sav tests/fixtures/gen3/emerald_ball_gate_b.sav
if ($LASTEXITCODE) { throw 'Emerald gate B derivation failed' }

$rows = @('species_clause_gen3', 'species_family_gen3', 'gender_clause_gen3', 'type_clause_gen3', 'ball_gate_gen3', 'release_gen3')
foreach ($game in @('gen3_frlg', 'gen3_lgfr', 'gen3_emerald', 'gen3_rr')) {
    foreach ($row in $rows) {
        python tools/e2e_duo.py --game $game --scenario $row --keep-data
        if ($LASTEXITCODE) { throw "Native row needs attention: $game $row" }
    }
}
```

Existing catch/battle/PC fixtures supply the other rows and B's family control.
No new B family fixture is needed. Eight whole-run attempts cover species/family
branch observation; type/gender and ball gate allow three. Existing Gen 1 cause/consequence
classification handles failed catches. Missing symbols, bad ACKs, corrupt
saves, incorrect prompts or failed readbacks remain FINAL. Exhausted
`ClauseUnobserved` stays a failure. Each attempt starts a fresh server/seed and
uses the existing idle jitter.

The vanilla gate pickup grants one real Ball. Its failed throw is the existing
`hunt ended out-of-balls` RNG class, with the unchanged two whole-run retries.
An exhausted three-attempt run remains FAIL; this card does not add balls or
call an unsuccessful catch qualification. RR's own reward is ten Balls.

## Verification receipts

Red controls and focused receipts are retained under the author's
`C:/slink-wt/g3-clauses/.cache/clauses-*.log`; they are MODEL evidence only.
The initial full gate found six capture-model extractor failures after the
backward-compatible optional `already_hunted` catch argument was introduced.
The extractor now follows the function boundary and adds a control proving an
observed encounter is not hunted again. All newly added own-ROM/source controls
ran with `SLINK_GEN3_ROMS` set; none was substituted by an emulator claim.
All six touched/new Lua files compile with Lupa. Ruff and `git diff --check`
are part of the final gate. The final full-unit receipt is recorded in the
peer handoff after completion.

Final gate (default pytest temp, no emulator):
`python -m pytest tests/unit -q -p no:randomly --tb=short --junitxml=.cache/clauses-full-final.xml`
completed with **11,999 passed, 4,395 skipped, zero failures** in 631.73 seconds.
The 83 card/capture-driver controls all executed without skips. Focused gate:
678 passed / seven existing optional skips. Receipts:
`.cache/clauses-full-final.{log,xml}` and `.cache/clauses-final-verification.json`.
