# pokeemerald-expansion record layout: field-by-field status

XR-2 (review cx-fcdc11c5, following up XR-1 commit b40153c4). Source:
rh-hideout/pokeemerald-expansion tag `expansion/1.17.0`, commit
`e8bd1cd7b03fc032ea37e3ecd38b379b5d01a1e7`, `include/pokemon.h`. Every layout
key here is additive (`server/adapters/gen3_codec.py`'s `decode_party_mon_masked`
/ `decode_box_mon_masked`, `lua/gen3/reads.lua`'s `R.new`); absent = vanilla,
byte-for-byte unchanged. `tests/fixtures/gen3/expansion_layout_e8bd1cd7.json`
is the single source of truth these two decoders and their test suite
(`tests/unit/test_gen3_expansion_masks.py`) read the layout from; the shipped
pack will instead come from X1-PROBE's compiler facts
(`data/games/gen3_exp/<build>/facts.json`, `claude/gen3-emerald-x1`).

| Field | Vanilla location | Expansion location | Status | Cite |
|---|---|---|---|---|
| species | Growth+0, u16 (whole lane) | Growth+0 bits 0-10 (`species:11`), `teraType:5` in bits 11-15 | **decoded** (`MON_SPECIES_MASK`) | `include/pokemon.h#L134` |
| heldItem | Growth+2, u16 (whole lane) | Growth+2 bits 0-9 (`heldItem:10`), 6 unused bits above | **decoded** (`MON_ITEM_MASK`) | `#L136-137` |
| move1..4 | Attacks+0/2/4/6, u16 each (whole lane) | bits 0-10 each (`moveN:11`), evolutionTracker/hyperTrained/unused bits above | **decoded** (`MON_MOVE_MASK`) | `#L150-159` |
| experience | Growth+4, u32 (whole lane) | bits 0-20 (`experience:21`); bits 21-28 are `nickname11:8`, bits 29-31 unused | **decoded** (`EXPERIENCE_MASK`, first-class key since XR-2 F2 -- no longer inferred from `NICKNAME_EXTRA`) | `#L138-140` |
| nickname (11th/12th char) | not present (10-char array only) | `nickname11:8` at Growth+4 bits 21-28; `nickname12:8` at Growth+10 bits 6-13 | **decoded** (`NICKNAME_EXTRA.chars`) | `#L139`, `#L143-144` |
| pokeball | Misc+2 (met u16) bits 11-14 | **moved** to Growth+10 bits 0-5 (`pokeball:6`) | **decoded** (`POKEBALL_FIELD`, XR-2 F5) | `#L143` |
| dynamaxLevel | not present | Misc+2 (met u16) bits 11-14 -- the vanilla record's OLD pokeball slot | **NOT handled** -- decoding this bit-lane as `pokeball` for an expansion record (no `POKEBALL_FIELD` set) reads dynamaxLevel garbage, not a ball; no `DYNAMAX_LEVEL_FIELD` key exists | `#L192` |
| abilityNum | IVs word (Misc+4) bit 31, 1 bit | **moved** to ribbons word (Misc+8) bits 29-30, 2 bits | **decoded** (`ABILITY_NUM_FIELD`, XR-2 F5) | `#L221` |
| gigantamaxFactor | not present | IVs word (Misc+4) bit 31 -- the vanilla record's OLD ability_num slot | **NOT handled** -- decoding bit31-of-IVs as `ability_num` for an expansion record (no `ABILITY_NUM_FIELD` set) reads gigantamaxFactor garbage, not the ability slot; no `GIGANTAMAX_FACTOR_FIELD` key exists | `#L201` |
| isShadow | not present | ribbons word (Misc+8) bit 27 | **NOT handled** -- no decoded field; `ribbons` continues to return the whole raw 32-bit word (unchanged pre/post XR-1, always included isShadow/abilityNum/modernFatefulEncounter mixed in on FR/LG too) | `#L219` |
| ribbons (individual flags) | packed into the ribbons word per-bit | unchanged bit assignments for the 12 single-bit ribbons + 5 tiered ribbons | **NOT handled** -- `ribbons` is decoded as the raw word, not `MON_DATA_RIBBONS`'s reassembled value (see `src/pokemon.c` `GetBoxMonData3` `case MON_DATA_RIBBONS`, which explicitly re-packs cool/beauty/cute/smart/tough at different bit positions than their storage order); this was already true before XR-1 | `src/pokemon.c#L2352-2371` |
| PP (pp1..4) | Attacks+8..11, whole byte each | bits 0-6 each (`ppN:7`); bit 7 is a `hyperTrained*` flag | **decoded** (`PP_MASK`, XR-2 F5) | `#L160-167` |
| hyperTrained (HP/Attack) | not present | Attacks+6 (move4 u16 lane) bits 14/15 | **already masked away** -- covered by `MON_MOVE_MASK` on the move4 lane (bits above `move4:11` are already stripped), no separate field needed |  `#L156-159` |
| hyperTrained (Def/Speed/SpAtk/SpDef) | not present | Attacks+8..11 bit 7 of each PP byte | **NOT decoded as a field** -- stripped by `PP_MASK` but not surfaced individually | `#L160-167` |
| markings | BoxPokemon+0x1B, whole byte | bits 0-3 (`markings:4`); bits 4-7 are `compressedStatus:4` | **decoded** (`MARKINGS_MASK`, XR-2 F5) | `#L272-273` |
| compressedStatus | not present | BoxPokemon+0x1B bits 4-7 | **NOT handled** -- no decoded field; `UncompressStatus` semantics (Pokerus-adjacent) are out of scope | `#L273` |
| unknown / hpLost | BoxPokemon+0x1E, whole u16 | bits 0-13 (`hpLost:14`); bit 14 `shinyModifier:1`; bit 15 unused | `unknown` **unchanged** (still the raw u16, not masked to hpLost); `shiny_modifier` **decoded as an extra field only** (`SHINY_MODIFIER_FIELD`, XR-2 F5) | `#L275-276` |

## Product gap: expansion shinyModifier-shiny is invisible to the server

`decode_party_mon_masked`/`decode_box_mon_masked` can now decode
`shiny_modifier` when a pack sets `SHINY_MODIFIER_FIELD`, but nothing
downstream reads it. The server's shiny rule
(`server/adapters/gen3_frlge.py` `Gen3FrlgeAdapter.is_shiny`, ~L423-426) is
`(tid ^ sid ^ p_upper ^ p_lower) < 8` -- the classic Gen 3 PID/OTID formula,
computed from the `PERSONALITY:OTID` key alone. `GetBoxMonData3`'s
`MON_DATA_IS_SHINY` case in the expansion ROM
(`src/pokemon.c#L2480-2484`) is `(shinyValue < SHINY_ODDS) ^ shinyModifier`:
a mon whose PID/OTID pair is NOT naturally shiny, but whose `shinyModifier`
bit is set (e.g. by a shiny charm / event flag the expansion tracks
per-mon rather than per-PID), reads as shiny in-game but would NOT be
flagged shiny by this codebase's key-based rule.

This is a real behavioural gap for any expansion-based pack, not a bug in
XR-1/XR-2: per the card brief, the server is deliberately NOT changed here.
Fixing it means either (a) making the shiny check consult the decoded
per-mon `shiny_modifier` field when the layout provides it, or (b) accepting
that expansion-forced shinies are cosmetic-only in this client until a
follow-up card. Flagging here so it is not lost.

## Encoder scope (XR-2 F1)

`encode_party_mon`/`encode_box_mon` are NOT layout-aware and only round-trip
vanilla (10-byte-nickname, unmasked) records, exactly as before XR-1. Passing
them a masked-decode dict whose `nickname_raw` is 12 bytes now raises
`ValueError: expansion nickname: encoder not layout-aware (...)` instead of
silently resizing the record (the bug XR-1 shipped: `bytearray` slice
assignment with a mismatched length resizes rather than erroring). There is
no `encode_party_mon_masked` -- nothing in this codebase writes expansion
records yet, so building an inverse encoder was out of scope; the refusal is
the safe placeholder until one is needed.
