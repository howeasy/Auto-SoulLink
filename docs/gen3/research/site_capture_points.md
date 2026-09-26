# Gen 3 capture-time semantic points (R7)

2026-09-21; research only. This is a proposal for snapshots/reduction, not an implemented signals schema or physical qualification. No pack/code edits. `sites` below refers to `docs/gen3_engine_sites.md`; `.sym` means `data/gen3/pret/pokefirered.sym` (pret c75f352). FR means the firered artifact, not Emerald/AP. RR clean and companion share the cited layout; bind the correct artifact's code bytes independently.

## Identity primitives and evidence

Use these typed primitives in the table; every address is sourced here rather than repeated as an unexplained literal.

| Primitive | Capture-time read / validity | Evidence |
|---|---|---|
| K(pointer) | u32le PID at +0, u32le OTID at +4; format `%08X:%08X`. Both normal and compressed headers preserve these bytes. Do not infer valid occupancy from arbitrary readable bytes. | `lua/gen3/reads.lua:138-146,228-244,267-269` |
| P(slot) | Require integer slot in current party count and <6; record at profile.ram.PARTY_BASE + slot*100. FR/RR base0x02024284, count u8 at0x02024029. Read whole record immediately if species/HP validation is needed. | .sym:158,161; `lua/games/gen3_frlge.lua:199-200`; `lua/gen3/reads.lua:308-321` |
| B(box,slot), FR | Validate box<14, slot<30; dereference gPokemonStoragePtr u32 at0x03005010, then profile BOX_DATA_OFFSET + (box*30+slot)*80. K reads the unencrypted header; species requires codec decoding. | .sym:811; `lua/gen3/reads.lua:343-374`; FR profile derived geometry |
| B(box,slot), RR | Validate box<25, slot<30; profile.derived.CFRU_BOX_BASES[box+1] + slot*58. Never substitute the FR storage pointer/stride. | `data/games/gen3_rr/profile.json:142-173`; `lua/gen3/reads.lua:348-355` |
| battler identity | u8 active at0x02023BC4; u16 party index at0x02023BCE+2*b; u8 position at0x02023BD6+b; side = position &1. Validate b against count and array limit before indexing, then K(P(slot)) only for qualified player ownership. | .sym:77,80,81; RR profile `lua/games/gen3_frlge.lua:209-210`; GetBattlerSide .sym:5149, position helper :5150 |
| fainted/attacker/target | u8 gBattlerFainted0x02023D6D; attacker0x02023D6B; target0x02023D6C. These have distinct lifetimes; do not substitute one for another. | .sym:98-100; pinned pret `src/battle_script_commands.c:2920-2930` |
| battle metadata | u32 type0x02022B4C; u8 outcome0x02023E8A; results base0x03004F90, player/opponent faint counters +0/+1 u8. | .sym:68,131,800; RR profile `lua/games/gen3_frlge.lua:206-212,375-376` |
| map | Dereference title-selected gSaveBlock1Ptr; u8 group at SB1+4, number at+5. FR pointer variable0x03005008; RR0x03003840. Require sane pointer and valid map values, not a stale pre-relocation pointer. | .sym:809; RR `lua/games/gen3_frlge.lua:256`; `lua/tests/gen3_boot_check.lua:120-136` |
| save counter | u32 gSaveCounter at0x03005390 is a RAM diagnostic, not a durable save proof. Actual witness reads selected valid flash slots and completion state. | .sym:848; `docs/gen3_engine_sites.md:298-316`; `docs/gen3/research/rr_save_layout.md:144-155` |
| FR PC origin | u8 sCursorArea0x02039820, sCursorPosition0x02039821, sIsMonBeingMoved0x02039822, sMovingMonOrigBoxId0x02039823, sMovingMonOrigBoxPos0x02039824. Current box from storage object's current-box field. Moving record is `gStorage->movingMon`; its exact pointer/offset must be independently pinned, not guessed. | .sym:315-319; pret `src/pokemon_storage_system_data.c:625-682,716-733` |

**Ownership caution:** “battler parity = player” is not the API contract. Resolve `gBattlerPositions[b] & 1` and the party-index mapping, plus battle-type/tag/borrowed-party exclusions. Even a player-side partner in a special battle may not belong to this player's persistent party. RR PC-origin globals and gStorage layout are not proved from the FR symbols by this note: mark missing layout facts OPEN and refuse semantic classification until bound.

## All 23 kinds: FR versus RR capture requirements

`reg` = u32 from emu.getregister (not a callback argument). H = source/byte contract sufficient to design a read, M = correlation/live snapshot still needed, OPEN = no justified binding. H never means release/live qualified. A key of `-` below means no mon identity; do not fabricate a PID from unrelated registers.

| Kind | FR read at existing capture | RR read at artifact capture | Key / filter / confidence |
|---|---|---|---|
| frame_control | CPU/frame only | Same | Liveness STATUS only, no reducer event/key. H; sites:58-76 |
| battle_begin | battle type and map snapshot; optional pre-init party keys | Same profile-bound reads | key `-`; establish battle lifecycle before relocation. Do not read initialized battle mons at entry. H/M; sites:78-96 |
| battle_end | outcome u8, type u32, battle lifecycle | Same | key `-`; close matched battle. Capture after inBattle clear, so do NOT demand inBattle==true. H; sites:98-116 |
| faint | At vanilla post-player-counter capture, read active battler, position, party index, K(P(slot)), battle HP/results. R7/R8 are active-address pointers, not battler IDs. | Old Cmd_tryfaintmon pin is displaced. For cleanup-complete0x0909EED2 use active RAM and P mapping; animation-entry0x080215A0 needs argument resolution or a post-assignment hook (discussion below). Retain special-case19/FF23 sources only with valid artifact/capture qualification. | Mon key; player ownership, HP-zero transition/dedupe, not counter delta alone (saturation). FR H, RR M. sites:118-136; `rr_faint_repin.md` R5; census v2/v3:2-4 |
| capture_wild | reg R0 result; best identity from paired GiveMonToPlayer/SendMonToPC snapshot. Alternative source record is enemy-party index for attacker XOR side as the actual vanilla call specifies. Do not assume last party slot without validating result/count. | Replacement capture0x0907DD88: reg R0 result, reg R4 source mon pointer -> K(R4), completed placement via paired helper snapshot. | Same acquired mon key; distinguish party/PC/failure; only emit on success and once with mon_given. FR M, RR H/M; sites:138-156; `rr_opcode_table_audit.md`, capture re-pin; pret battle_script_commands.c:9617-9645 |
| mon_given | reg R0 result, reg R6 source mon pointer -> K(R6) before pop; destination from party/PC helper context | reg R0 result, reg R4 source -> K(R4); on party success R5 is post-increment party count, candidate slot R5-1 verified against K(P(slot)) | Same mon identity, classify catch/gift using caller/lifecycle, not an arbitrary 'gift=true' at every helper fire. H/M; sites:158-186 |
| pc_move | SendMonToPC reg R0 result, R5 box/R6 slot, R8 source pointer; validate only on result1 | RR common return0x090B6EA0: R0 result, R4 box/R5 slot, R7 source -> K(R7); compare K(B(box,slot)) on success | This is **acquisition to storage**, not a general user PC deposit. Correlate capture/gift; do not emit reducer pc_move(deposit) solely from this hook. H/M; sites:188-216 |
| whiteout | map/type/lifecycle; party may already be healed | Same | key `-`; dedupe per loss lifecycle, not enumerate healed mons as fainted. H; sites:218-236 |
| map_load | u8 group/number from current SB1 pointer at completion | Same, RR SB1 pointer binding | Carry group/number plus adapter-derived **wire area_id** as key. Numeric packed map ID is not equal to old client's string area ID. H/M; sites:238-256; reducer:78-86 |
| evolve_species_store | reg R9 mon pointer -> K; decode species from same record, reg R4 task pointer as lifecycle token | Same register contract is only SOURCE-pinned for existing RR row; require live register validity. RR codec fixed order/unencrypted; FR decrypts/permutates. | Key is normally unchanged PID:OTID; species from decoded record, no engine GetMonData invocation from observer. Not final evolution completion. M; sites:258-276; reads.lua:228-252 |
| trade_done | reg R7 received-mon pointer -> new key; reg R9 player slot; match trade_begin old key | Same pinned TradeMons register contract, validate vs K(P(R9)); native silent replacement fallback bypasses this site | Reducer key = received **new_key**; carry old_key/slot separately. Do not use old key because a buggy old wire completion did. Not final scene completion. H/M; sites:278-296 |
| save | reg R0 status==1, reg R5 save type==0; optional RAM counter | Same, RR extension save remains separate persistence obligation | key `-`, counter extra scalar, not key (wire no key). No full-save event on other types/error. H; sites:298-316 |
| poison_faint | reg R4 mon; u16 new HP at reg R13 stack pointer, paired old HP>0 from poison_hp_before. K(R4) | N/A: RR replacement disables this field effect; old tails excluded | Player-party key; validate pointer maps to current party and pair invocation, not just frame. FR H/M, RR N/A; sites:318-336,520-548 |
| borrowed_party | N/A RR-specific | OPEN: no pinned begin/restore address or snapshot layout. Need before/after full party keys plus a unique lifecycle marker; profile backup-address existence alone is insufficient. | No invented mon/slot key. Set event key `-` only after reducer lifecycle semantics agreed; snapshots preserve individual keys. OPEN; sites:338-347 |
| nature_change | N/A RR-specific | OPEN: must capture old PID/OTID **before** mutation and new afterward for same proven record; cannot reconstruct old PID from final record. | Match wire old/new identity contract; do not synthesize key from similarity. OPEN; sites:349-358 |
| pc_deposit | reg R0 success==1, reg R6 destination box; compiler-shifted R4 slot needs decoded-width confirmation; use paired pc_box_place R6/R7 for unambiguous destination snapshot instead of guessing a shift. K(B(destination)) | Same higher-level row requires success and destination correlation; RR B uses compressed bases. Origin layout still OPEN. | Emit pc_move action=deposit only if origin is proven party, not carried box mon. H for destination via pair, M/OPEN for provenance; sites:360-378; pret storage_data.c:658-682 |
| pc_withdraw | reg R6==14 party sentinel, reg R7 destination party slot; K(P(R7)); FR moving-origin globals to distinguish box->party from party shuffle | reg R6==25, reg R7 party slot at0x08092FF8; K(P(R7)); RR moving-origin facts need binding | Emit pc_move action=withdraw only on proven box origin. A party-to-party placement is not withdrawal. M; sites:380-409 |
| pc_box_place | reg R6 box<14, R7 slot<30; K(B(R6,R7)); require box branch because party branch shares epilogue | reg R6<25/R7<30 at0x08093020; compressed B | Deposit only with party origin; box-to-box moves are not in current reducer action vocabulary. Deduplicate nested pc_deposit. M; sites:410-438 |
| pc_release_begin | Before purge: cursor area/position, moving flag/origin; capture K of selected or carried mon. Moving record offset remains to pin. | Same conceptual pre-removal snapshot; do NOT reuse FR origin globals without RR evidence | Retain immutable pending old key and locator, no reducer release yet. M/OPEN; sites:440-458; pret storage_data.c:716-733 |
| pc_release | Pair prior release_begin by ordered invocation/context; capture no key from erased destination. R0/result not an identity substitute | Same | Emit pc_move action=release with pre-removal key after successful applicable removal; carried-mon branch can just clear a flag. M; sites:460-478 |
| trade_evolve_species_store | reg R8 mon -> K/species; reg R4 task token; trade-begin lease correlation | Same source-pinned register contract, RR decoder | Fold into trade lifecycle; ordinary evolve_species_store publication only if reducer semantics explicitly permit it. M; sites:480-498 |
| trade_begin | reg R0 player slot, reg R1 enemy slot; K(P(R0)), optional incoming K(enemy); copy before either side overwritten | Same; slot validate and persistent-party ownership; native partner staging must be known | Retain old_key and slot; do not emit a second independent trade_done. H/M; sites:500-518 |
| poison_hp_before | reg R0 old HP, reg R4 mon pointer/K, invocation ordinal | N/A RR disabled | Pair with poison_faint by mon pointer and ordered call/iteration, not frame only. H/M; sites:520-548 |

The table deliberately does not invent RR storage-origin or borrowed/nature layouts. Missing provenance means **no semantic event**, not a locator substituted for a known-mon key. FR/LG independently bind their own code offsets; the data above describes FR and the specified RR artifacts only.

## Which faint identity is valid, and when?

At **0x080215A0** the animation function has not yet resolved its script argument. Pinned pret `src/battle_script_commands.c:2920-2930` tests controller-idle, calls GetBattlerForBattleScript(script[1]), assigns gActiveBattler, then emits animation. Therefore the entry's gActiveBattler may be stale. gBattlerFainted is valid only when the script argument actually selects that identity; attacker/target variants select other globals. Pinned CFRU faint-script variants are documented in `rr_faint_repin.md` R5 (fainting_battle_scripts.s:23-28,44-49,60-67). The census's recommendation to always read gBattlerFainted is not a general semantic proof (`docs/gen3/probes/census_rr_faint_v2v3_2026-09-21.txt:4`).

Direct companion bytes at ROM0x000215B4 decode `4C08 7020`: load active-battler address then **store selected R0 to gActiveBattler at0x080215B6**. The next instruction **0x080215B8** is a better candidate for identity snapshot: selection is committed and controller-idle branch was taken. Its delivery is UNVERIFIED here; it is not an authorized silent relocation of the pack. At existing entry, alternatively record script pointer+argument and relevant battler globals and implement the complete GetBattlerForBattleScript mapping from pinned source; do not call game code to resolve it.

At **0x0909EED2** cleanup completion, R5 research traces script cursor advancement after active-battler assignment at0x0909E980; read gActiveBattler plus position/party slot immediately. This later lifecycle witness need not equal counter-commit timing. Both animation and cleanup were observed seven times in census v3, but all those faints were opponents; player-side correctness remains unqualified (`census_rr_faint_v2v3_2026-09-21.txt:2-4`). The proposed FF23 player-counter join being silent in that run is not contradictory to a zero player-faint counter. Do not infer that either interior is dead from an opponent-only control.

## Register timing and minimum point schema

The exec callback supplies an address; registers require injected `io.register(name)` backed by **emu.getregister**, and RAM must be read synchronously in the hook before the engine continues (`lua/gen3/signals.lua:17-27,60-63,93-125`). raw_r15 is separately observed as the next instruction; it is not a replacement for the callback address. Instruction timing must be checked for each new store/call-return site; avoid register meanings that apply only before a pop once that pop has executed.

Recommended `point` payload (JSON-serializable scalars, optional fields absent when inapplicable):

```json
{
  "key": "PID8HEX:OTID8HEX",
  "old_key": "PID8HEX:OTID8HEX",
  "new_key": "PID8HEX:OTID8HEX",
  "mon_address": 0,
  "battler": 0,
  "position": 0,
  "side": 0,
  "party_slot": 0,
  "box": 0,
  "box_slot": 0,
  "origin_box": 0,
  "origin_slot": 0,
  "action": "deposit",
  "result": 0,
  "old_hp": 1,
  "hp": 0,
  "species": 1,
  "map_group": 0,
  "map_number": 0,
  "area_id": "wire-compatible-area-id",
  "save_type": 0,
  "save_counter": 0,
  "battle_type": 0,
  "outcome": 0,
  "lifecycle_id": 1,
  "identity_valid": true
}
```

This is a **union example, not defaults**: never fill absent data with zero or manufacture valid keys. For non-mon events explicitly normalize to key `-`; unavailable mon identity is a rejected/OPEN snapshot, not key `-` admitted as a valid mon. Mandatory minimum per mon event is key plus enough typed locator/result/side evidence to validate that key. The reducer does not need every diagnostic register, but preserve raw registers in separate debug payload when testing capture contracts.

Two existing interfaces need coordinator-owned changes outside this research lease:

1. signals currently puts generic per-kind values in **signal.point**, while shadow_run forwards only scalar **top-level** fields, dropping nested tables. Filling point alone will still produce empty key (`lua/gen3/signals.lua:60-63,111-120`; `lua/gen3/shadow_run.lua:299` onward, scalar-only field loop). Promote explicitly validated semantic fields to the emitted record, or teach the logger to serialize/flatten the point under an agreed schema. Preserve capture frame, sink/player and monotonic t; no poll-time substitute.
2. `tools/gen3_shadow_diff.py:25-38,78-86,158-180` supports fourteen semantic kinds, not all23 raw kinds. It aliases PC actions for wire events but does not accept raw `pc_withdraw`, `trade_begin`, `pc_box_place`, `trade_evolve_species_store`, `poison_hp_before` as SHADOW kinds. Add a stateful semantic normalizer before emission: raw nested hooks pair/dedupe into the correct supported event. `pc_move` needs deposit/withdraw/release; SendMonToPC acquisition is not automatically one of these actions. frame_control remains STATUS. For map events, emit the wire area_id string as key; a numeric group*256+number would falsely differ from the old client even for the same map.

## Required falsifiers / NOT VERIFIED

* Capture field samples while hooks are live: compare header identity at the exact named locator, reject invalid slot/side/result, and show enemy faints never produce a player key. Test double/tag/borrowed battles separately; parity shortcuts are not qualification.
* Catch with free party slot, full party, storage failure; compare source/destination identity and nested-helper deduplication. RR free-slot insertion is not guaranteed to be the old count; use the selected source/header and actual destination.
* PC deposit, party shuffle, box rearrangement, withdrawal and release require origin/identity before mutation. Confirm RR frontend fields and the compiler-shifted deposit-slot register before enabling those rows.
* Trade/evolution hooks must preserve old identity before replacement; post-only observation cannot recover it. Poison pairing must survive multiple mons in one frame. Save event is not a flash durability oracle.
* No code or pack edit, emulator, Python or tests in this card. Source register contracts above remain subject to physical capture validation. OPEN rows are explicit missing evidence, not permission to guess addresses.
