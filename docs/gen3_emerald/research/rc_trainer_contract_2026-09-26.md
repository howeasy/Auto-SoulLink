# Emerald RC trainer contract (UI lane, checked on master 5313d94e, 2026-09-26)

Owner ruling 2026-09-26: trainer names, Upcoming Key Trainers and the calc Prep tab are
**mandatory for RC**. Source: the UI lane ("GUI notifications"). Line numbers are at master
5313d94e; re-find each by text before building.

**Headline:** templates, dashboard.js and the calc bridge have no Radical Red gate. Every gate is
`if not self._is_rr` inside `server/adapters/gen3_frlge.py` (this lane's file). An empty/None
return hides the panel, so gating is already capability-driven, with inert base defaults at
`server/adapters/base.py:380, 471, 479, 488`.

## 1 Trainer names in battle
- `server.py:2366-2381`: when a battle message carries `trainer_id`, the server calls
  `adapter_for(pid).trainer_info(tid) -> (name, cls)`. A non-empty class sets
  battle_state `opponent_name`/`opponent_class`; otherwise the client's own fields are used.
- The gate is `gen3_frlge.py:495-507`. RR returns `_RR_TRAINERS.get(trainer_id - 1)`: the wire
  id is the raw gTrainers index (Gen 3 lane `e729abdb`). RR rivals return ("", "Rival").
- The client must send `trainer_id` (and `is_trainer_battle`) in battle.

## 2 Upcoming Key Trainers panel
- Built by `_trainer_panel_html(area_id, pid)` (`server.py:931`), called at `:2834`, rendered
  at `_board.html:203` only when non-empty.
- `trainers_for_area(area_id) -> list[int]`: runtime trainer ids, where area_id is the id the
  client reports in `area_enter`. Gate at `gen3_frlge.py:517`.
- `trainer_brief(tid) -> dict | None` (gate at `:576`).
  - Keys: `name`, `class`, `party`, `area`.
  - Optional keys: `level_cap` (int), `fight_label`, `calc_label`, `sprite_url`.
- `milestone_cap_for_fight_label(label) -> int | None` is looked up via hasattr
  (`server.py:994/1033/1085`; gate at `:549`). It only drives the past/current/future
  bucketing, falling back to `brief.level_cap`. Optional for v1.
- Party entries (`server.py:~1130-1145`):
  - required: `species` (calc-format name), `level` (int);
  - optional: `level_offset` (<= 0; effective level = max(1, highest_party_level + offset)),
    `ability`, `item`, `nature`, `moves` (list[str]).
- Grouping: bucketed by (name.title(), cap // 10). Distinct fight_labels in one bucket become
  variants of one row; the same or a missing label gives separate rows.
- `trainer_party(tid)` (`base.py:479`) returns the party alone; the panel reads `brief.party`.

## 3 Calc Prep tab
- `slink_bridge.js:806 _supportsPrepTab()` is true for RR, or when a non-RR game's trainer
  setdex loaded. The setdex comes from `calc_profile()`, which already returns Emerald.js /
  CUSTOMSETDEX_E for emerald.
- Prep lists every setdex trainer. The key (`_buildTrainerIndex`) is the text before " | ",
  trimmed, e.g. "Psychic Edward".
- `brief.calc_label` must EQUAL that key for two links:
  - (a) the dashboard Calc button (`server.py:1205/1258` data-calc-label → `/calc?prep=<label>`);
  - (b) live battles: `server.py:3086 _calc_trainer_label(brief, enemy)` tags enemy mons when
    at least half of the enemy species are in `brief.party`. It strips a leading "*" and a
    trailing " Set N".
- Without `calc_label`, the bridge falls back to matching species and level.

## Build plan (this lane)
1. Generate `data/games/gen3_emerald/trainers.json` from pret pokeemerald (`src/data/trainers.h`,
   `trainer_parties.h`, class names): runtime id = gTrainers index, name, class, party with
   species (calc-format name), level, item and moves (explicit or learnset-derived, as E6 does),
   area (the map with the trainer's object event, mapped to the pack's area ids), key-trainer
   flag, level_cap (gym leader / Elite Four / rival milestones), and `calc_label` joined to the
   Emerald.js key. The E6 checker already resolves 654 unique names; ambiguous ones need
   index-level labels.
2. `gen3_frlge.py`: Emerald branches for `trainer_info` / `trainers_for_area` / `trainer_brief` /
   `trainer_party` (and optionally `milestone_cap_for_fight_label`). All game facts stay in the
   pack. No base.py/server.py change: keep the hasattr.
3. Client: confirm the Gen 3 client reports `trainer_id` from `gTrainerBattleOpponent_A` on
   Emerald (vanilla symbol present in `pokeemerald.sym`), plus `is_trainer_battle`.
4. PHYSICAL: a duo/scripted trainer battle on Emerald shows the name/class and the panel. UI lane
   verifies rendering with mock data after the branch lands.
