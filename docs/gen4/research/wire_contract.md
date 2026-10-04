# Wire contract for a Gen 4 client on `lua/core/session.lua`

Source: a Claude Explore extraction, 2026-09-26. It follows the code where `docs/protocol.md` is stale.

Citations are to the files below:
- `docs/protocol.md`
- `tests/unit/protocol_schema.py`, `test_protocol_conformance.py`, `conformance_map.py`, `gen3_world.py`
- `lua/core/*.lua`, `lua/gen3/client.lua`
- `server/server.py`, `server/state.py`
- `server/adapters/{base,__init__,gen4_hgsspt}.py`

## Envelope and hello

**Envelope.** Every line is `{"event","player","seq",...}`, and `seq`/`player` are stamped by the session (`session.lua:78-88`). The server replies `noop{refused}` in these cases:

| Refusal | Cause |
|---|---|
| `duplicate` | a repeated `seq` |
| `no_hello` | an event before hello |
| `superseded` | an older connection for the same player |

**Hello.**
- Required: `rom_type` (HG/SS: `heartgold`/`soulsilver`) and `party` (list; each entry needs `key`).
- Send on every hello (or never): `ot_id` (int; the lock stores `str(ot_id)`, so omitting it after the lock is set → WRONG SAVE) and `trainer_name`.
- Also send: `has_pokeballs`, `badges` (Johto mask), `kanto_badges`, `ball_count`, `area_id`, `loc_name`, `in_battle`, `pc_boxes`, `artifact_kind:"clean"`.
- `foundation` is optional and never trusted: if present it must equal the server-derived value.
- There is no protocol-version field.

**Refusal order** (`server.py:1597-1640, 2083-2103`; `state.py:1681-1700`): unknown `rom_type` → mixed games / foundation / artifact kind → ROM contract → WRONG SAVE.

**An accepted hello** returns `resolved_areas`, `config`, `dead_keys` and any re-queued commands (`state.py:1885-1958`).

## Periodic messages

- **`tick`** every 30 frames, all fields optional: `area_id`, `loc_name`, `in_battle`, `is_trainer_battle`, `trainer_id`, `enemy_party` (`[]` outside battle; the first wild tick needs `[0].species_id` for the dupes clause), `has_pokeballs`, `party`, `pc_boxes`, `badges`, `kanto_badges`, `ball_count`, `trainer_name`.
- **`safe{}`** once after each battle.

## Events (client → server; the minimum set for a first duo)

| Event | Fields | Notes |
|---|---|---|
| `area_enter` | `area_id`, `loc_name` | |
| `capture` | `key`, `area_id`, `species_id`, `level`, `hp`, `maxHP`, `nickname`, `held_item_id`, `is_egg`, `gift?`, `in_box?`, `stats?` | Eggs count as gifts except in a daycare |
| `faint` | `key`, `area_id` | Never for a zero the client wrote itself |
| `no_catch` | `area_id`, `species_id`, `level` | |
| `whiteout` | `{}` | Exactly once |
| `party_to_box` | `key`, `stats` | Player-initiated moves only |
| `box_to_party` | `key`, `area_id` | Player-initiated moves only |
| deferred replies | | From `core/deferred.lua` given Gen 4 executors: `stats_cache`, `box_mon_failed`, `sync_retrieve_done`/`_failed`, `memorialize_done{box}`/`_failed` |

**Not wire events:** `mon_given`, `battle_begin`, `battle_end`, `evolution`, `save`, `pc_move` are internal signal kinds. The legacy Gen 4 `hatch` event is unknown to the server; hatches go out as `capture{is_egg…}`.

**D11 correction (2026-09-29):** executed NPC exchanges send `key_change{old_key,new_key,reason:"npc_trade"}` with replacement evidence and shared identity alias handling. Vanilla has ten authored exchange identities, two loan grants and a dormant record; equal species does not mean equal identity. Loans use acquisition policy, without a fabricated old key or a new `npc_loan` wire event/reason. Hge reachability is derived per build.

**Leave out for a first duo:** native link trades, rival swap, `status`, `ghost_pos`, `release`, `pc_boxes_generation`, server wire `battle_identity`, `trade_prepare`, `panel`, `sfx`. Local encounter IDs in diagnostic receipts are not a new server event.

## Commands (server → client)

- **Handled by the session core** (`session.lua:265-311`):
  - `force_faint` (immediate, battle-held or deferred)
  - `box_mon` / `party_mon` / `memorialize` (always deferred)
  - HUD prompts, `config`, `game_over`, `rebuild_*`, `resolved_areas`, `noop`
- **Prompt commands** (`show_choices` etc.) get cancel sentinels.
- **Never sent to a Gen 4 run** on the current adapter: `force_explode`, `replace_rival_team`, `link_panel`, `apply_trade`/`apply_prepare` (`party_blob_size()` is 0), `trade_mask`.
- **Keying.** Commands are keyed by mon `key`, prompts by `token`. There are no command ids. `force_faint` must be idempotent (the lost-faint repair re-sends it).

### Held active-faint commands and diagnostic receipts

The shared session consumes `battle_write` dispositions, not a returned arbitrary receipt. Gen 4 uses the existing `session:eligible()` and explicit save/encounter epochs at every write arm; connection, hello, reset and key ambiguity cannot be left to the current held-queue flush. Test hold→disconnect→legal seam, wrong-save reconnect, reset and duplicate-command sequences with no unintended bytes.

The proposed client/harness diagnostic line is `GEN4_BATTLE_FAINT <JSON>`, with the exact fields and independent game-effect oracle specified in [PLAN.md §4.3](../PLAN.md). It is emitted through the existing diagnostic sink and consumed by the harness; no server wire schema is expanded. Missing/malformed/stale/partial receipt is FAIL. Receipt and saved HP alone do not prove the game's in-battle effect. Disabling the battle operation while preserving deferred writes and the receipt producer must make G4 red.

Capture setup/application state through encounter end; overlay residency alone can lag and route an active command to the deferred queue. If the battle ends before the required effect, report an unfulfilled/interrupted D7 command and retain truthful disposition/persistence evidence. Do not qualify it as D7 through the checkpoint path or silently relax D12. Observe native copy-back and healing separately from any later persistence correction.

## Mon key and snapshot shape

**Key.** `"%08X:%08X"` = PID:OTID, where the 32-bit OTID is `SID<<16|TID` (`protocol_schema.py:20`, `base.py:667-695`). Evolution and hatching keep the key.

**Party entry.**
- Required: `key`, `slot`, `species_id` (national dex), `nickname` (decoded string), `level`, `hp`, `maxHP`.
- Optional: `status_cond`, `moves`, `pp`, `pp_ups`, `held_item_id`, `ability_id`, `form`, `active`, `stat_stages[7]` (ATK..EVA, 0-12; Gen 4 has an 8-entry array including HP, so drop HP).

**Box entry.** `box`, `slot`, `key`, `species_id`, `nickname`, `held_item_id`, `moves`, `level?`.

**Driver mon records** must also carry `nickname_bytes` and `moves` for `core/identity.lua` (`:34`) and `core/deferred.lua` (`:64`).

## Conformance suite

- `test_protocol_conformance.py` is Gen 3-only today: wire fixtures in `tests/fixtures/gen3/wire/`, `gen3_world` artifacts, a hard-coded 200-hex `blob_hex` (`:184, :580`), and the Gen 3 OT format (`:619-629`).
- Gen 4 needs a sibling `test_gen4_protocol_conformance.py` reusing `protocol_schema`/`conformance_map`, plus a Gen 4 world. The schema validators are generation-neutral.

## Gen 3 assumptions a Gen 4 client trips over

1. **Foundation rows:** missing for HG/SS/hge (planned in G3a). Until then, omit `foundation`.
2. **Sound ids:** Gen 3 SE ids; the session plays 26 on `game_over`. The Gen 4 driver makes `play_sound` a no-op or maps ids.
3. **`ot_id`:** must be sent consistently (see Hello above).
4. **`party_blob_size()` = 0:** blobs are ignored and trades are off. Fine for the first release.
5. **Display:** `_party_snapshot` drops `pp_ups`/`form` (`server.py:1969-1989`), so Gen 4 form sprites won't reach the dashboard. This is a later adapter/server item.
6. **Badges:** `badges` = Johto mask, `kanto_badges` = Kanto mask.
7. **Boxes:** memorial box 17 for HGSS, 30 mons per box; hge (30 boxes) needs a per-foundation value.
8. **Text:** nicknames are decoded from 16-bit text in the client, with the raw bytes kept as `nickname_bytes`. The HUD sanitises server text.
9. **Empty lists:** use `json.array`, so they go out as `[]`, not `{}`.
