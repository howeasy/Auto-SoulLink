# GIFT-EGG-ROWS-G3

SOURCE and MODEL only. No emulator was launched for this card. A generated seed
is disclosed setup, not a native gift/hatch result or a live qualification.

## Owner rule and production behavior

O-15 (`docs/gen2/PLAN.md`, `GEN2_BINDING_PLAN.md`) applies to Gen 3: an egg is
not an acquisition at GiveEgg. Native hatch publishes exactly one
`capture{gift=true,is_egg=false,area_id="gift_daycare",key=<hatchling key>}`.
Booted eggs and withdrawn boxed eggs stay pending. `mon_given` does not acquire
an egg whose hatch has not completed. The hatch hook reads the completed mon
at fire time, checks the aligned party pointer, secure egg/Bad Egg bits and
checksum, and carries the reset epoch. The server's existing gift namespace
and clause hooks handle the event; no shared server title branch was added.

## Native gift facts

| Title | Object and setup | Native result | Native completion flag |
|---|---|---|---|
| FireRed | Route4 PokemonCenter 1F, map 16.0, seller object 2 at (1,3); stand (1,4), face Up | Magikarp 129, level 5, price 500 | `0249` |
| LeafGreen | Its own map head `08352688`; same object/tile; script `0816F73B` | Magikarp 129, level 5, price 500 | `0249` |
| Radical Red | Its own map object script `0904C03D`, first offer; stand (1,4), face Up | Magikarp 129, level 5, price 500 | **`098E`**, not vanilla's flag |
| Emerald | Mossdeep Steven's House 14.7, ball object 2 at (4,3); stand (3,3), face Right | Beldum 398, level 5 | `012A`; hides object via `03C8` |

FR/LG source: pret pokefirered `c75f352304d529f6ba92d4f74b9cf8b5c3810788`,
`data/maps/Route4_PokemonCenter_1F/{map.json,scripts.inc}` and both checked-in
`.sym` files. FR script `0816F75F`; LG independently `0816F73B`.

Emerald source: pret pokeemerald `c65e93f20a5275ab03b07d6f6411096a82a60ffd`,
`data/maps/MossdeepCity_StevensHouse/{map.json,scripts.inc}`:72-129. The ball
script has no champion check. Visibility is flag `03C8`; the unrelated Dive
scene runs only when `VAR_STEVENS_HOUSE_STATE (40C6)==1`. The seed clears that
state and unhides the ball; it does not claim the champion story was played.
Beldum needs one interaction and no battle. The cheaper existing Wynaut egg
leg remains an egg-receipt observer, not this non-egg gift acquisition row.

RR SOURCE is the admitted RR ROM, not a vanilla script assumption. Its first
offer tests flag `098E`, checks/removes 500, issues `givemon 129,5`, and sets
`098E`. The subsequent 75,000 shiny offer is a different branch and is not
used. `tools/gen3_gift_egg_rows.py` pins each title's own first 0x120 script
bytes and map-object pointer; a mismatch fails before launch. The same module
checks the stand/walk tiles with the title's ROM geometry.

RR flag **098E is extended**. `GetFlagAddr` at `0806E5C0` detours to
`09042DEC`, which calls `090B8FB0`. Its literal pool at `090B8FE4/E8/EC`
holds `FFFFF700`, `00000FFF`, `0203B174`: flags 0900..18FF map to
`0203B174 + (flag-0900)/8`. Thus 098E is byte **0203B185**, mask **40**.
The reviewed RR serializer maps that byte to active section 0 + **0F35**
(parasite piece at 0F24 plus 11); it is outside the native section checksum.
The builder, native flag witness and independent saved-flag oracle all use
this proven mapping. They do **not** index past vanilla SB1.flags into vars.
ROM hashes cover the detour and resolver body; the existing save-layout ROM
gate checks the serializer. A red/green falsifier starts this extended byte
at FF and requires BF after setup while the SB1 variable byte stays unchanged.
RR's own money script still passes SB1+0290; GetMoney reads SB2+0F20 as its XOR
key (`0806C172..17A`, `0809FD58..68`, independently decoded on RR).

## Hatch sites and RR difference

The production engine pack now includes `hatch`, at
`AddHatchedMonToParty+0xAA`, immediately after `CalculateMonStats`, before stack
unwind, with the completed mon in R5. Effective hooks:

| Title/artifact | Hook | Source |
|---|---|---|
| FireRed / LeafGreen, independently | `08046E0A` | own `.sym`; `src/daycare.c`:1639-1678 |
| Emerald | `08071562` | own `.sym`; `src/egg_hatch.c`:358-397 |
| RR clean / companion, independently | `08046E0A` | own in-place body at `08046D60`, caller BL `080471D4`, entry/tail/boundary byte pins |

RR's `CreatedHatchedMon` **is replaced**: `08046BFC` detours to `090881F0`.
Its CreateMon arguments at `090882A4..090882BC` set R2=1; the callable literal
at `0908839C` is `0803DA55`. RR hatches at level **1**, versus vanilla level 5.
The RR-specific body SHA-256, detour and native step checker are independently
pinned by the row's facts loader. Never infer the callee's behavior from the
unchanged outer return sequence.

The fixture adds a disclosed egg cloned from the title's own decoded, owned
lead, with a distinct non-shiny PID, both egg bits set and friendship/cycles
0. Normal walking reaches the next engine cycle check. The daycare step
counter is deliberately untouched: no unproven RAM address is needed. The
walk uses two adjacent indoor floor tiles (FR/LG/RR 16.0 (3,6)-(4,6);
Emerald 14.7 (3,5)-(4,5)). The driver witnesses the title's native hatch scene,
presses B through text/nickname NO, then reads the same owned key as a non-egg.

## Evidence and boundaries

Both rows require a native engine signal, one actual production capture TX,
one alive persisted link, native SAVE-site witness, process flush, and decoded
saved records. Gift additionally checks the native completion flag and seller
price. Hatch checks the saved egg bits, identity/species, inherited moves/IVs,
level, party/box membership and surviving lead. Native walking may adjust the
lead's friendship and its checksum; other control fields remain invariant.

`gift_gen3` enables all three clauses to exercise the fixed-gift exemption.
MODEL tests also check that shiny gifts enter the bonus path first and that a
pending bonus pairing still enforces clauses. No shiny was manufactured during
a native row and MODEL coverage is not a PHYSICAL shiny-branch claim.

Tests run the production client over fake RAM, load real generated Lua stubs
in Lupa (including nested own-title facts), execute the input carrier in Lupa,
and falsify saved-flash oracles. Invalid pointers/Bad Eggs/reset-era hooks,
wrong scripts/callbacks, early acquisition, duplicate capture, absent scene,
unwalked hatch, or an egg still in flash cannot qualify the row.

Final gate on the corrected cut (including CLAUSE-FIX parent `bb15fb02`):
**12320 passed, 4361 optional skips, zero failures**, 568.28 seconds. All 77
card controls, 36 Emerald pack controls, 20 release/retry controls and 10
catch-driver controls ran without skips. Receipts are
`.cache/gift-egg-corrected-full.log` and `.cache/gift-egg-corrected-full.xml`.
Default pytest temporary directories and retention on failure were used.
Ruff and `gen_gen3_engine_signals.py --check` passed; protocol citation checks
passed within the full gate. SOURCE/MODEL still does not qualify native play.

## Fixtures and exact coordinator commands

`tests/fixtures/gen3/gift_egg_synth_manifest.json` lists all 12 offline SYNTH
fixtures, input/output SHA-256s and edits. They have not been re-saved by an
emulator. They follow the existing FR/RR offline CONTINUE-warp convention.
RR edits change only reviewed native span bytes and touched checksums, keeping
unrelated bytes and extension sectors unchanged. The gift additionally clears
the one reviewed extended flag bit in the parasite payload, as disclosed above.

To regenerate a fixture (substitute title, own ROM and the corresponding town
seed; Emerald/RR B uses its `_town_b.sav` and `_synth_b.sav`):

```powershell
python tools/gen3_gift_egg_rows.py --title firered --kind gift --rom 'E:/Google Drive/SLink/Pokemon - FireRed Version (USA).gba' --seed tests/fixtures/gen3/firered_party_town.sav --out tests/fixtures/gen3/firered_party_gift_synth.sav
python tools/gen3_gift_egg_rows.py --title firered --kind hatch --rom 'E:/Google Drive/SLink/Pokemon - FireRed Version (USA).gba' --seed tests/fixtures/gen3/firered_party_town.sav --out tests/fixtures/gen3/firered_party_hatch_synth.sav
```

With the normal admitted companion artifacts staged in the integration worktree,
run these commands **sequentially in the coordinator's single emulator lane**:

```powershell
python tools/e2e_duo.py --game gen3_frlg --scenario gift_gen3
python tools/e2e_duo.py --game gen3_lgfr --scenario gift_gen3
python tools/e2e_duo.py --game gen3_emerald --scenario gift_gen3
python tools/e2e_duo.py --game gen3_rr --scenario gift_gen3
python tools/e2e_duo.py --game gen3_frlg --scenario egg_hatch_gen3
python tools/e2e_duo.py --game gen3_lgfr --scenario egg_hatch_gen3
python tools/e2e_duo.py --game gen3_emerald --scenario egg_hatch_gen3
python tools/e2e_duo.py --game gen3_rr --scenario egg_hatch_gen3
```

No row injects a server link or substitutes saved flags for the native result.
Actual native play, save/reload persistence and PHYSICAL qualification remain
for those live runs.
