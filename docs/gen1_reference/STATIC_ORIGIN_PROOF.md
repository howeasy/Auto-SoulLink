# Static battle origin proof and capture attribution

`server/gen1_static_receipt.validate` turns two read-only witnesses into a source-qualified
fact naming which static encounter started a wild battle; `attribute` joins a decoded
ItemUseBall capture fact (`gen1_capture_receipt.decode_capture`) to that origin and returns
the title-neutral id `static:<logical_event_id>`. `validate_end` turns a third witness, the
battle's end, into a `static_battle_end` fact, and `server/gen1_static_lifecycle.py` keeps
at most one live origin per player: consumed once by the first capture inside its own
battle, invalidated by the battle's end otherwise. Nothing here settles rules, ordinals or
identity. Ghost Marowak and the unidentified GHOST are classified as excluded and every
Pokémon Tower map is refused outright.

Evidence classes used below: **source-cited** (pinned pret text, `.cache/pret/pokered` @
405b624 for Red/Blue, `.cache/pret/pokeyellow` @ 0a08515 for Yellow), **ROM-byte-verified**
(the generator asserts the clean cartridge bytes and pins them as `expected_hex`),
**synthetic fixture** (every test witness; no emulator ran).

## How a static battle starts (source-cited)

A battle begins when the overworld loop finds `wCurOpponent` non-zero
(`home/overworld.asm:64-66`, `:128-130`) and runs `.newBattle` → `NewBattle` → `farjp
InitBattle` (`:321-322`, `:362-371`). `InitBattle` reads `wCurOpponent`; non-zero goes to
`InitOpponent`, which copies it into `wCurPartySpecies` and `wEnemyMonSpecies2`
(`engine/battle/core.asm:6642-6651`; Yellow `engine/battle/init_battle.asm:1-10`).
`InitBattleCommon` calls `InitBattleVariables` (Safari type only on Safari Zone maps,
`init_battle_variables.asm:30-37`), then `sub OPP_ID_OFFSET ; jp c, InitWildBattle`
(`core.asm:6674-6676`; Yellow `init_battle.asm:33-35`). `InitWildBattle` writes
`wIsInBattle := 1` and calls `LoadEnemyMonData`, which builds the enemy from
`wEnemyMonSpecies2` and `wCurEnemyLevel` (`core.asm:6695-6698`; Yellow `init_battle.asm:60-63`).
`EndOfBattle` zeroes `wIsInBattle`, `wBattleType` and `wCurOpponent`
(`end_of_battle.asm:47-53`; Yellow `:51-57`).

Two writers set the operands for catchable statics:

- **Script statics** (Route 12/16 Snorlax): the map script writes both bytes itself,
  `ld a, SNORLAX ; ld [wCurOpponent], a ; ld a, 30 ; ld [wCurEnemyLevel], a`
  (`scripts/Route12.asm:33-36`, `scripts/Route16.asm:33-36`, identical text in Yellow).
- **Object statics** (Mewtwo, Articuno, Zapdos, Moltres, 6 Voltorb, 2 Electrode): the
  object record is `db TRAINER | text_id, species, level` (`macros/scripts/maps.asm:16-25`);
  `LoadSprite` copies species/level into `wMapSpriteExtraData` at map load
  (`home/overworld.asm:2206-2219`; Yellow `:2245-2258`). Talking to the sprite runs
  `DisplayTextID`, which sets `wSpriteIndex := hTextID` (`home/text_script.asm:22-23`,
  `ASSERT hSpriteIndex == hTextID` at `:4`); the text handler calls `TalkToTrainer` →
  `EngageMapTrainer`, which indexes `wMapSpriteExtraData` by `wSpriteIndex - 1` into
  `wEngagedTrainerClass/Set` (`home/trainers.asm:90-126`, `:327-339`); `StartTrainerBattle`
  → `InitBattleEnemyParameters` writes `wCurOpponent` and, for class `< OPP_ID_OFFSET`,
  `wCurEnemyLevel` at `.noTrainer` (`home/trainers.asm:172-183`, `:233-244`). Text ids are
  `const_def 1` in object order (`macros/scripts/maps.asm:261-263`), so `wSpriteIndex`
  equals the census `object_index`; the generator asserts `TRAINER | object_index` on every
  record byte.

`began` alone never names a static: fishing also writes `wCurOpponent`
(`engine/items/item_effects.asm:1872-1877`; Yellow `:2087-2092`), and random encounters
write only `wCurEnemyLevel`/`wEnemyMonSpecies2` (`wild_encounters.asm:76-80`; the generator
asserts the file never mentions `wCurOpponent`).

## How a static battle ends (source-cited)

Every battle leaves through exactly one routine. `InitBattleCommon` runs `call StartBattle`
and then, unconditionally, `callfar EndOfBattle` (`engine/battle/core.asm:6763-6764`; Yellow
`engine/battle/init_battle.asm:130-131`, `callfar StartBattle` there). The generator asserts
that this `callfar` (`21 <EndOfBattle> 06 04 CD <Bankswitch>`) occurs exactly once in each
clean ROM, so no other code reaches `EndOfBattle`, and `StartBattle` returns for every way a
battle can end:

| Ending | Source (Red/Blue; Yellow lines in parentheses) | `wBattleResult` at `EndOfBattle` |
|---|---|---|
| enemy KO (wild win) | `HandleEnemyMonFainted` → `FaintEnemyPokemon` writes `xor a ; ld [wBattleResult], a` (`core.asm:816-817`; Y `:825-826`), then `ld a, [wIsInBattle] ; dec a ; ret z` (`:711-713`) | `$00` |
| player loss / blackout | `RemoveFaintedPlayerMon` writes `ld a, $1 ; ld [wBattleResult], a` (`:1030-1031`; Y `:1043-1044`); `HandlePlayerMonFainted`/`HandleEnemyMonFainted` → `HandlePlayerBlackOut` ends `call ClearScreen ; scf ; ret` (`:1132-1165`; Y `:1171-1204`). The overworld writes `wIsInBattle := $ff` only afterwards (`home/overworld.asm:354-356`; Y `:316-318`) | `$01` |
| RUN (also Poké Doll/flight via `wEscapedFromBattle`) | `TryRunningFromBattle.canEscape` → `.playSound ; ld [wBattleResult], a` with `a = $2` (`:1584-1611`; Y `:1625-1652`); `MainInBattleLoop` `ret c` / `ret nz` (`:305-309`; Y `:314-318`) | `$02` (`$00` for a wild mon that fled) |
| capture | `.returnAfterCapturingMon`: `ld a, $2 ; ld [wBattleResult], a ; scf ; ret` (`:2288-2295`; Y `:2392-2399`) | `$02` |
| **ball breaks free** | `.returnAfterUsingItem_NoCapture`: `call GBPalNormal ; and a ; ret` — carry clear, back to the battle loop (`:2282-2286`; Y `:2386-2390`) | **not a battle end**: `EndOfBattle` is not reached, nothing is witnessed, the origin stays live |

`wBattleResult` is `$00` win / `$01` lose / `$02` draw (`ram/wram.asm:999-1002`; Y `:1174-1177`),
zeroed by `InitBattleVariables` (`init_battle_variables.asm:6`). A capture and a successful
RUN both write `$02`, so the result byte alone cannot tell them apart; the lifecycle never
needs to — a capture is proved by its own receipt, and any end invalidates whatever was not
consumed. At `EndOfBattle`'s entry (`end_of_battle.asm:1-4`: `ld a, [wLinkState] ; cp
LINK_STATE_BATTLING`, `serial_constants.asm:25` = `$04`) `wBattleResult` is final and
`wIsInBattle`, `wCurOpponent`, `wCurEnemyLevel`, `wBattleType` are still intact;
`.resetVariables` (`:46-53`; Y `:50-57`) clears them. That entry is the single `battle_end`
witness (ROM-byte-verified):

| Anchor | R/B | Yellow |
|---|---|---|
| `battle_end` PC = `EndOfBattle` | `04:77AA` `FA 2B D1 FE 04` | `04:7765` `FA 2A D1 FE 04` |
| `.reset` = `EndOfBattle.resetVariables` | `04:7813` `AF EA 83D0 EA 2AC0 EA 57D0 EA 5AD0 EA 5FD0 EA 59D0` | `04:77DD` `AF EA 82D0 EA 2AC0 EA 56D0 EA 59D0 EA 5ED0 EA 58D0` |
| `.call` = `call(far) StartBattle ; callfar EndOfBattle` | `0F:7030` `CD 1E41 21 AA77 06 04 CD D635` | `3D:613A` `21 2741 06 0F CD 843E 21 6577 06 04 CD 843E` |

The observer publishes the `end` witness only while a `began` receipt is live (the end of a
random encounter is nobody's), and clears `live` on publication; which static it closes is
decided by the server from order, not carried in the receipt.

## Census and sites (`tools/gen_gen1_static_sites.py` → `static_sites.json`, Lua mirror)

Every `catchable_static` row of `acquisition_sources.json` becomes a site; every
`uncatchable_script_battle` row becomes an excluded id with a reason. The generator asserts
the pinned source text (`GUARDS`, `INIT_GUARDS`), then the clean ROM bytes, and `--check`
fails on any drift. The 14 ids are identical across Red, Blue and Yellow (asserted), so
`static_id == source_id`.

| Kind | Sites | Arm witness (ROM-byte-verified) | Species / level bytes |
|---|---|---|---|
| script | `static:route12_snorlax`, `static:route16_snorlax` | write block `3E 84 EA <wCurOpponent> 3E 1E EA <wCurEnemyLevel>` at the census `entry`; PC = entry+10 (`3E xx EA <wToggleableObjectIndex>`) — R/B `16:5639`, `16:5979`; Y `16:54D5`, `16:5815` | entry+1 / entry+6 |
| object | 12 (Cerulean Cave B1F, Power Plant ×9, Seafoam B4F, Victory Road 2F) | shared `InitBattleEnemyParameters.noTrainer+3` (`ret`, `C9`) — R/B `00:32EE`, Y `00:328A`; 24-byte routine pinned; identity = (`wCurMap`, `wSpriteIndex`) | object record +1 / +2 |

Shared `began` witness: `InitWildBattle+5`, after `3E 01 EA <wIsInBattle>` — R/B `0F:6F90`
(`CD <LoadEnemyMonData>`), Y `3D:6081` (`21 <LoadEnemyMonData> 06 0F CD <Bankswitch>`).
Also pinned: `InitBattle` entry `FA <wCurOpponent> A7 28`, `IsGhostBattle` bytes
(`cp $8E`, `cp $95`, `ld b, $48`), from which `tower_map_ids = 142..148` is derived and
checked against the census.

## Receipt (`rby-static-origin-receipt-v1`)

`schema`, `source_sha256` (= `static_sites.json` sha256), `variant`, `context_generation`,
`physical_instance`, `final_sha1`, `source_id`, and two witnesses `{frame, pc, bank, sp,
point}`:

- `arm` — PC at the site's arm address/bank.
- `began` — PC at the title's `began` address/bank; `began.frame >= arm.frame`.

`point` = `{map_id, cur_opponent, cur_level, enemy_species2, battle_flag, battle_type,
sprite_index, engaged_class, engaged_set, battle_result, trainer_hex (11), player_id_hex (2)}`
read from `wCurMap, wCurOpponent, wCurEnemyLevel, wEnemyMonSpecies2, wIsInBattle,
wBattleType, wSpriteIndex, wEngagedTrainerClass, wEngagedTrainerSet, wBattleResult,
wPlayerName, wPlayerID`. `lua/gen1_static_observer.lua` produces exactly this from bus-exec
hooks (one per Snorlax arm, one shared object arm resolved by map + sprite index, one
`began`, one `battle_end`); a `began` with no open arm publishes nothing.

The battle-end receipt shares the header (`schema` … `final_sha1`) and carries one witness,
`end`, at the title's `battle_end` address/bank — no `source_id`, `arm` or `began`. Both
receipt shapes travel in the observer's single ordered `pending` list; they are told apart by
`'end' in receipt`.

`validate_end` proves: pins and context; the witness sits at `EndOfBattle` in bank 4; the
save identity; `battle_flag ∈ {1 wild, 2 trainer}` (never 0 or the overworld's later `$ff`);
`battle_result ∈ {0, 1, 2}`. Fact: `{kind: 'static_battle_end', static_id: null, map_id,
battle_flag, battle_type, species_index (wCurOpponent), level (wCurEnemyLevel),
battle_result, frame, receipt_digest}`.

## What the decoder proves

- Pins and context match; `source_id` is a site (excluded ids refuse with their reason).
- Both witnesses belong to the admitted save (identity) and sit on the site's map; the
  `began` map is not a Pokémon Tower floor (refused first, with its own message).
- Arm: `wIsInBattle == 0` (written from the overworld). Object sites additionally require
  `sprite_index == object_index`, `engaged_class == cur_opponent`, `engaged_set == cur_level`.
- Began: `wIsInBattle == 1`, `wBattleType == BATTLE_TYPE_NORMAL`, `cur_opponent` and
  `cur_level` unchanged from arm, `enemy_species2 == cur_opponent`.
- Species is the pinned clean operand or its admitted `rom_bytes` override at exactly the
  pinned species offset, `1 <= species < OPP_ID_OFFSET`; level is the pinned value.

Fact: `{kind: 'static_origin', static_id, source_id, static_kind, object_index,
species_index, level, map_id, battle_type, arm_frame, began_frame, frame (= began),
receipt_digest}`.

## What is read, not proved

`sprite_index`, `engaged_class`, `engaged_set` are carried for script sites but not
checked (the Snorlax scripts never consult them). Which of two same-species same-level
objects (Power Plant Voltorbs) was engaged rests on the observer's `wSpriteIndex` reading;
species and level cannot tell them apart. The battle's enemy struct is not read here; the
capture receipt proves it.

## Exclusions (source-cited)

- `script-battle:ghost-marowak` — `scripts/PokemonTower6F.asm:36-39` writes
  `RESTLESS_SOUL` (= `MAROWAK`, `constants/pokemon_constants.asm:209`; Yellow `:212`) at
  level 30 on `POKEMON_TOWER_6F`. `ItemUseBall` sets the can't-be-caught value when
  `wCurMap == POKEMON_TOWER_6F` and `wEnemyMonSpecies2 == RESTLESS_SOUL`
  (`item_effects.asm:169-175`; Yellow `:181-187`). UPR's `ghost` static record rewrites the
  script operand and both engine compares together (asserted), so the species byte is not a
  stable discriminator; the map is. Refused by id and by map.
- `script-battle:unidentified-tower-ghost` — `IsGhostBattle` (`core.asm:3309-3324`; Yellow
  `:3480-3495`): wild battle, `POKEMON_TOWER_1F <= wCurMap <= POKEMON_TOWER_7F`
  (`map_constants.asm:228,234`), no `SILPH_SCOPE` (`item_constants.asm:84`). `ItemUseBall`
  refuses it (`item_effects.asm:151-153`; Yellow `:153-155`); `InitWildBattle` shows the
  GHOST sprite for it (`core.asm:6700-6723`). No catchable static lives on a tower map;
  every tower `began` map is refused with a specific message.
- `script-battle:old-man-tutorial` — `BATTLE_TYPE_OLD_MAN` (`scripts/ViridianCity.asm:75-80`;
  Yellow `:98-107`); `ItemUseBall` jumps to `.oldManCaughtMon` and never delivers
  (`item_effects.asm:155-164`). Refused by id and by `battle_type != NORMAL`.
- `script-battle:oak-pikachu` (Yellow) — `BATTLE_TYPE_PIKACHU` (`scripts/PalletTown.asm:143-148`),
  treated as the old man battle by `ItemUseBall` (Yellow `item_effects.asm:157-177`).

## Handoff API

```python
from server.gen1_static_receipt import validate, attribute, DATA, SCHEMA

fact = validate(receipt, variant=..., identity=save_identity, context_generation=...,
                physical_instance=..., final_sha1=..., rom_bytes=None)   # -> static_origin fact
static_id = attribute(capture_fact, fact, variant=...)                  # -> 'static:<id>'
```

`attribute` requires `capture_fact` from `decode_capture` (keys `kind == 'capture'`,
`map_id`, `battle_type`, `species_index`, `level`, `call_frame`), the same map, a delivering
battle type (`capture_sites.delivering_battle_types`) equal to the origin's (`NORMAL`), the
origin's species and level, and `call_frame >= origin.frame`. It does not prove same-battle
continuity; the lifecycle does.

```python
from server.gen1_static_receipt import validate_end
from server.gen1_static_lifecycle import COMPONENT, stage, verify_state, open, consume, close, new_row, record_key

end = validate_end(receipt, variant=..., identity=..., context_generation=..., physical_instance=..., final_sha1=...)
staged = stage(document_or_row, player, facts, frame_origin, variant=None)
# -> {'records': [{'namespace': 'gen1-static-origins', 'key': record_key(player), 'value': row}],
#     'attributions': {capture_key: static_id}}
verify_state(document['components']['gen1-static-origins'])   # {player: row}
```

`stage` applies decoded `{kind, fact, source_ref: {event, index}}` rows **in list order** (no
buffering, no re-sort): `static_origin` → `open`, `capture` → `consume`, `static_battle_end`
→ `close`, `grant` skipped (root may pass its whole decoded acquisition list). Every
`source_ref.event` must equal `frame_origin`. Given a document, the component row is created
on demand and the variant read from `gen1-initial-observations`; given a bare row, `variant`
is required. Only the detached target is mutated.

Lifecycle rules (`row = {origins: [...], attributions: {key: static_id}}`, each origin
`{static_id, fact, source_ref, state, capture, end, superseded_by}`):

- `open(row, origin_fact, source_ref)`: appends a `live` origin. If one is already live it
  becomes `superseded` (recorded with `superseded_by`), never refused: battles do not nest,
  so a second `began` means the earlier battle ended unobserved (reset, state load) and the
  new battle's evidence is real. A superseded origin never attributes anything.
- `consume(row, capture_fact, source_ref, *, variant) -> static_id | None`: eligible origins
  are the live one and an `ended` one whose end frame is `>= call_frame` (root may list the
  end before the capture of the same bundle; both land in the same consumed range). The first
  eligible origin that `attribute` accepts becomes `consumed` with `{source_ref, key,
  call_frame}` and `attributions[key] = static_id`; anything else returns `None` (an ordinary
  wild capture). A key already attributed is refused. Consumed once: a second matching
  capture finds no eligible origin.
- `close(row, end_fact, source_ref)`: the live origin becomes `ended` with `{source_ref,
  frame, battle_result}` whatever the result (win, loss, RUN, or a capture already consumed);
  nothing live is a no-op. A ball that breaks free produces no end fact and so neither
  consumes nor closes (source above).
- `verify_state(component)`: re-derives every invariant on restore — ≤ 1 live origin per
  player, state ⇔ resolution fields, every `source_ref` a valid event reference of that
  player, `began_frame <= capture.call_frame <= end.frame`, `attributions` exactly the
  consumed origins' keys (an attribution to a static never opened, or a consumed row
  without its `source_ref`, is refused).

## UPR operands

Only the species byte each arm reads is mutable: `entry+1` for the Snorlax scripts, the
object record's species byte for objects. Each is asserted to lie in exactly one non-ghost
`upr_layout.profiles[variant].statics` record whose `Level` list is exactly the site's level
byte (`gen_gen1_grant_sites.static_record`). Level bytes are never claimed by UPR and the
decoder refuses a `rom_bytes` key naming one. A checked ROM byte is required for any
non-clean species; with it, a randomized slot that became Marowak is still a Power Plant
static (only the Tower is refused).

## Evidence

- `tests/unit/test_gen1_static_receipt.py` (140): every site × 3 titles; cross-title id
  and operand identity; 35 hostile receipts; every excluded id with its reason; all 7 tower
  maps; object identity by sprite index; UPR override rules; `attribute` against real
  `decode_capture` facts (party and boxed) and 14 refusals; `validate_end` per title × win /
  lose / draw / trainer and 16 hostile end receipts (wrong PC, wrong bank, result byte out of
  range, out of battle, `$ff` marker, shape mixing); regeneration `--check`, sha256, Lua
  mirror, census cross-check, ROM-byte anchors incl. `battle_end`/`reset`/`call` and the
  single-call proof, UPR record cross-check.
- `tests/unit/test_gen1_static_observer.py` (21): observer receipts equal the decoder
  fixtures byte for byte and validate; three objects through one hook; `began` without arm
  publishes nothing; `battle_end` published once per live origin and validated, not for a
  random encounter's end, filtered by bank, latching on moved bytes, hold discipline with the
  raw result byte left to the decoder; moved anchors (incl. the `callfar`) refuse construction.
- `tests/unit/test_gen1_static_lifecycle.py` (29): consume once (3 titles); flee / KO / loss
  then a matching wild capture → `None`; ball break-free leaves the origin live; end listed
  before capture in one bundle; capture before its origin is not attributed; re-arm after
  close; two opens supersede; a Yellow/Yellow pair through `stage` on a document; grants
  skipped, foreign frame / player / variant refused; 14 corrupted-row `verify_state` faults.

## Limitations

- Synthetic fixtures only; no live engine run produced a receipt.
- Same-battle continuity is proved only by order: `attribute` alone would still join a
  later same-map, same-species, same-level wild capture; `gen1_static_lifecycle` closes that
  with the `battle_end` witness. A battle that ends unobserved (emulator reset or state load
  mid-battle: no `EndOfBattle`) leaves its origin live until the next `began` supersedes it;
  a matching wild capture in between would attribute. Frame monotonicity across a state
  load is root's concern, not checked here.
- `wBattleResult == $02` is written by both a capture and a successful RUN; the end fact
  carries it raw and the lifecycle does not branch on it.
- The Voltorb/Electrode duplicates are told apart only by the observer's `wSpriteIndex`.
- Not wired: the observer is not in the client, neither receipt kind is in runtime
  dispatch, `stage`/`verify_state` are not called from `gen1_frame_acquisitions` /
  `gen1_runtime_state`, and no reserved file was changed.
