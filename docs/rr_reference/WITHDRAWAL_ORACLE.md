# RR 4.1 withdrawal readback oracle

`lua/rr/withdrawal_oracle.lua` is an **inactive, pure reference helper**. It derives
the expected 100-byte party record from a 58-byte compressed record, selected
pinned-ROM table evidence, and an explicit Default-mode context. It never reads
or writes emulator memory, calls native code, or grants permission to apply/ACK a
command. Existing native conversion and `storage.classify` remain unchanged.

This closes the offline formula gap for the standard stat branch. It does **not**
close S04 release evidence: actual native execution/readback, authoritative context
binding, and receipt integration still need validation.

## Pinned call chain

Base ROM SHA-256:
`679d112cdfe699c2793d82c7e7999ac9dfca9e222ad5a85d4f8f1e457cd0283f`.
All addresses are GBA ROM bus addresses. The tests require this exact ROM and
check selected instruction bytes and pointer literals, not an upstream build.

| Routine | Exact RR address | Relevant behavior |
|---|---|---|
| `CompressedMonToMon` | `0x090B6A24` | Builds a local 80-byte box record, then calls `BoxMonToMon`. |
| `CreateBoxMonFromCompressedMon` | `0x090B6924` | Zeroes 80 bytes, copies represented fields, marks byte `+0x4F` bit 7, unpacks four moves and reconstructs all four PP values. |
| `BoxMonToMon` | `0x0803E774` | Copies 80 bytes; sets status, old HP and old max HP to zero; sets mail index `0xFF`; calculates stats. |
| `CalculateMonStats` entry | `0x0803E47C` | Detour bytes `00 49 08 47 FD 88 07 09` select the actual RR implementation at `0x090788FC`. |
| Actual stat calculator | `0x090788FC` | Reads six IVs/EVs, species, HP, max HP, EXP-derived level and PID-derived nature; selects standard/frontier scaling branches. |
| `GetLevelFromMonExp` | `0x0803E7C4` | Uses species growth byte `+19`, 256 u32 thresholds per growth row, and scans up to level 250. |
| `GetNature` | `0x08042E9C` | Reads personality and returns unsigned PID modulo 25. |
| `ModifyStatByNature` | `0x08043698` | Uses the 25×5 nature table; RR has patched multiply by 9 or 11, u16 truncation, then division by 10. |
| `CalculatePPWithBonus` | `0x0804101C` | Reads move record `+4` at 12-byte stride and applies the slot's two PP-up bits. |

Complete reviewed routine-region hashes provide additional provenance (lengths
include each routine's literal pool where applicable):

| Start / byte length | SHA-256 |
|---|---|
| `0x090B6924 / 0xD0` | `a4f4c177a2085ccbf4f5aa0be343c4ee90ff6a190b5298fec9cbceae6788fcdf` |
| `0x090B6A24 / 0x20` | `c828577b3991ca575b08189acbf098600404d1628b31ccc1aaa5806459b9c323` |
| `0x0803E774 / 0xBC` | `d1d1c44acecb72bcf0241ff8755ab2b47251fcb0461ce77727bbb59746743954` |
| `0x090788FC / 0x34C` | `3b301db4b56c5b93ed5eaef4159a0849c6be96e9dc5d1c1adf022c0d7d3f3732` |
| `0x0804101C / 0x48` | `ae8eda5db489bb8faa3d796f3172d291b97405ace81a70470002094eca8b54a0` |
| `0x08042E9C / 0x18` | `a95d66897b90ef10d1915a765ac38faa9def936e70da45b1d4f6b682d09fb76c` |
| `0x08043698 / 0x60` | `e762b53eb37d8c914c5bc15b7c4c871e02219459fa97880fe52971a1e4928c67` |
| `0x0909AC9A / 0x92` | `16c6be4a69348590be191dfa13d784f0eed97f88c400ecf14f9b5bad9b9d8ccd` |
| `0x0803FD44 / 0x638` | `2846e95c5c21a32630afbf1b3a0dfd65d162b0be8882a1199d6b0339b0e3c340` |

## Exact reconstructed values

The helper takes immutable binary strings and has no dependency on the existing
Lua conversion, storage module, calculator model, or server-cached party stats.

| Input | Compressed offset or ROM source |
|---|---|
| Personality | u32 `+0x00`; nature is `PID % 25`. |
| Species | u16 `+0x1C`; associated 28-byte BaseStats record at `0x097B98EC + 28*species`. |
| EXP | u32 `+0x20`; growth byte is BaseStats `+19`. |
| PP bonuses | byte `+0x24`; two bits per move slot. |
| Four moves | 40 bits at `+0x27..0x2B`; four 10-bit IDs. |
| Six EVs | bytes `+0x2C..0x31`, in HP/Attack/Defense/Speed/Sp. Attack/Sp. Defense order. |
| Six IVs | low 30 bits of u32 `+0x36`, five bits in the same stat order. Upper egg/ability-related bits do not enter stat arithmetic. |
| Growth thresholds | `0x0915514C + growth*1024 + level*4`. |
| Nature modifiers | signed bytes at `0x08252B48 + nature*5 + statIndex-1`, for non-HP indexes 1..5. |
| Base move PP | byte at `0x091521D0 + move*12 + 4`. |

Level is the last contiguous threshold not exceeding EXP in the native scan of
levels 1..250. EXP below threshold 1 produces level 0. The helper reproduces this
behavior rather than accepting it as valid campaign data. In particular, this
routine does not enforce badge caps or clamp to 100. A separate admission/data
policy can reject an invalid level, but must not change the expected native bytes.

For the standard branch, with integer division at the indicated steps:

```text
scaled = floor((2 * base + IV + floor(EV / 4)) * level / 100)
maxHP = min(scaled + level + 10, 65535)
maxHP = 1 for internal species 303 (Shedinja)
raw non-HP stat = (scaled + 5) modulo 65536
neutral stat = raw stat
raised stat = floor(((raw stat * 11) modulo 65536) / 10)
lowered stat = floor(((raw stat * 9) modulo 65536) / 10)
```

The multiplier/divisor differs from unpatched pret's documented `110/100`
intermediate. Preserve RR's integer order. The native u16 intermediate is modeled
even though standard in-domain level/base-stat inputs do not reach its wrap bound.

For slot `i`, `ups = (ppBonuses >> (2*i)) & 3`:

```text
PP = (basePP + floor(basePP * 20 * ups / 100)) modulo 256
```

The builder invokes this for **all four slots**, including move 0; there is no
`move != 0` condition. The pinned RR record 0 has base PP **35**. Thus an empty
move slot reconstructs PP 35, 42, 49 or 56 according to its stored PP-up bits.
An oracle that writes or expects zero for empty-slot PP is incorrect for this
conversion entry point. This says nothing about whether the battle engine can
select the empty move.

## Deliberate reconstruction and preservation

The 80-byte builder preserves compressed bytes `0..27`, growth `+0x1C..0x26`,
the six EV bytes, and misc `+0x32..0x39`. Moves are unpacked without reordering.
It zeroes checksum/padding `+0x1C..0x1F`, growth padding `+0x2B`, contest bytes
`+0x3E..0x43`, and trailing misc `+0x4C..0x4F`, then explicitly sets `+0x4F=0x80`
at `0x090B696A..0x090B6976`. This last marker is a verified RR binary addition
not present in the available CFRU function; its gameplay meaning is not inferred.

`BoxMonToMon` resets status to 0, mail index to 255, and HP/max HP to 0 before
calling the calculator. Consequently withdrawal produces **full HP**, including
HP 1 for Shedinja. Old party HP, status and remaining PP are not represented in
the compressed source. The helper derives the complete 100 bytes for the guarded
empty destination used by SoulLink; it is not a substitute for verifying that
destination's vacancy before execution.

## Mode and modifier boundaries

- **MGM off/on use the same reconstruction formula and stored IV/EV bytes.**
  The actual IV getters at `0x080400C6..0x080400F4` and EV getters at
  `0x08040074..0x0804008A` perform raw reads. The traced stat path has no MGM
  flag read. Do not force IV 31/EV 0 in the oracle. Mode-dependent creation,
  training or migration routines can have changed those stored values earlier;
  their enforcement is outside this withdrawal proof.
- **Nature uses PID.** The traced path does not read a separate mint/nature
  override field. Any earlier nature-changing operation that changes PID is
  naturally reflected by the oracle; the operation itself is not audited here.
- **Held item, selected/hidden ability, OT, friendship and badge level caps do
  not enter this reconstruction path.** They may affect battle calculations or
  EXP acquisition elsewhere. Source fields are still preserved. The helper does
  not import battle ability/item multipliers into stored party stats.
- The RR predicates at `0x0909AC9A`, `0x0909ACCC`, and `0x0909ACFC` check
  expanded flag **0x0930**, then var **0x5018** for formats **13**, **12**, and
  **11** respectively (Average, 350 Cup, Scalemons). These predicates do not
  require `inBattle`. A field callback alone cannot prove standard stat rules.
  The first helper refuses every active-frontier context. The future binding
  must sample the real flag and preserve it through prepare/execute/readback;
  it must not manufacture `frontier_active=false` from the ordinary field owner.
- Bad-egg accessor behavior and zero/placeholder species are refused. Default
  mode must be explicit and MGM must be a known boolean. The helper does not
  establish ROM admission, randomizer exclusion, source legality, stable save
  identity, native reservation ownership, or a complete valid-move domain.

## Testable integration design and remaining evidence

1. Load the exact ROM's BaseStats, growth, nature and move-PP evidence through the
   admitted ROM revision. Bind each species record to its growth row and each
   move to its actual PP byte. Cache immutable ROM evidence, not mutable party
   calculations. Validate allowed species/move domains separately; a 10-bit
   field alone is not proof that an ID names a valid move.
2. During storage preparation, use the immutable source bytes and coherent RR
   context to derive and persist the **exact expected 100-byte destination**.
   Keep `minimal_grinding`, the actual frontier flag, ROM revision, source
   identity, native reservation and context generation associated with it.
   This helper's `context` argument is supplied evidence, not a memory reader.
3. After the existing guarded native entry point executes, require the complete
   destination, source clearing, party count and all unaffected records to match.
   A completion ACK plus positive stat bounds is insufficient. Do not recalculate
   the expectation from a mutated source or changed context after the effect.
4. Preserve existing uncertain-state behavior when the formula context is
   unsupported, evidence is missing, or bytes disagree. Do not fall back to Lua
   reconstruction or use a timer to accept the mutation.
5. Run actual native conversion/readback gates for MGM off/on before S04 closure:
   all nature directions, EV floors, non-perfect stored IVs, Shedinja, level/EXP
   boundaries, PP-up counts including empty slots, ability/item variants and a
   source with status/PP already reduced before deposit. Use captured input and
   actual output bytes; compare them with this independent oracle. Test both
   mode settings even if all legitimately generated MGM records have 31 IV/0 EV.

Offline tests run the real pure Lua helper under Lupa, compare against an
independent Python arithmetic model and hand-computed golden values, and assert
pinned binary anchors. Coverage includes all 25 natures, all six growth rows,
every PP-bonus byte, exact thresholds and one-below values at levels
1/2/49/50/99/100/101/250, Shedinja, zero-level engine behavior, refusal paths and
full reconstructed byte positions. These are **not ARM execution or emulator
tests**. The helper is not called by the production client or `storage.lua`.

One additional test consumes the independently captured field record in
`tests/rr/reference/fixtures/field_party_08_a.json`. Root captured it after actual
Continue-to-field at frame 1657, with MGM on: Treecko 277, level 6, HP/max HP 22,
other stats 12/12/15/14/11, moves 1/43/71/0, PP 35/30/25/35. The oracle exactly
matches the observed stat/status/level/mail tail and PP bytes when supplied its
represented input fields. The raw record SHA-256 is
`b9133a60d0c484c4477aadf5e2acd18082c4ce84b735afa285ed2ec98be2490c`;
the original payload SHA-256 is
`7822e77697f6200a4b3fb84d46f05e2ee2b5862a1859dc3560eae82e410be69a`;
the original source-result SHA-256 is
`ea361ac601b2902b6de66f376e2abb91a8cffb79eefb80ca0d8b60629774fb60`.
Both source-file hashes were independently checked during this review.

This is field-state corroboration, **not a withdrawal gate**. The original field
record has `+0x4F=0`; the withdrawal builder would add `0x80`. The test explicitly
asserts that difference and does not claim complete-byte equality or that native
withdrawal produced the captured record. Its context did not independently
capture the frontier flag, so the standard branch is an offline comparison
assumption, not live context-admission proof.

```powershell
python -m pytest tests/rr/reference/test_withdrawal_oracle.py --rr-repo . --rr-rom 'E:/Google Drive/SLink/patch/build/rr_clean.gba' -q
python -m ruff check tests/rr/reference/test_withdrawal_oracle.py
```

Available source support, read without modification from the asset checkout:

| Source | Relevant lines | SHA-256 |
|---|---|---|
| CFRU `src/pokemon_storage_system.c` | 275–279, 302–319 | `1acb24b7588c6c03edb58ca5608d85ea4cab8db154bffb253d40bbd23f69034d` |
| CFRU `src/build_pokemon.c` | 4426–4551 | `fc91060605b6064ee7b959865d1e507bf3c754f0b4b11c119683180ccbc72ea5` |
| pret `src/pokemon.c` | `BoxMonToMon`, `CalculatePPWithBonus`, `ModifyStatByNature` | `116a470cd9ebfa226aa8d85c2eb63591e176d726837c67baaa1ac6260d50f2ec` |

The pinned binary takes precedence where it differs from these sources, including
the builder marker, 250-level scan, and nature arithmetic patch.
