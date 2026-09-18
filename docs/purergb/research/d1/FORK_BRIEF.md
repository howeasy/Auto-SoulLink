# pureRGB fork of UPR ZX 4.6.1 — implementation brief

Sources cited as `upr_Gen1RomHandler.java:N` / `upr_Gen1Constants.java:N` are the
verbatim scratch copies of tag `7f00eb86`:
`...\27f97123.../scratchpad\upr_Gen1RomHandler.java` and `upr_Gen1Constants.java`.
`Randomizer.java:N`, `AbstractRomHandler.java:N`, `AbstractGBRomHandler.java:N`
were fetched fresh from
`raw.githubusercontent.com/Ajarmar/universal-pokemon-randomizer-zx/7f00eb86.../src/com/dabomstew/pkrandom/...`
during this pass (line numbers below match that fetch). `pure.ini:N` is
`...\2eefad46.../scratchpad\workers\w2\upr_pure_entries_v2.ini`.

## 0. The single most important fact this pass found

`savingRom()` (`upr_Gen1RomHandler.java:403-406`) is:

```java
public void savingRom() {
    savePokemonStats();
    saveMoves();
}
```

That's the **entire** unconditional collateral surface baked into every save
— `AbstractGBRomHandler.saveRomFile` (`AbstractGBRomHandler.java:71-72`) calls
`savingRom()` then writes `rom[]` straight to disk, no other hook exists.
`writeCheckValueToROM` is a no-op in the base class
(`AbstractRomHandler.java:7490-7492`, "do nothing") and Gen1RomHandler never
overrides it, so it is harmless. Everything else the task brief worried about
(`setTrainers`, `setTMMoves`, `setStaticPokemon`, `setStarters`, misc tweaks)
is already gated behind a `Settings` enum in `Randomizer.java` and is a
**no-op unless that specific category is turned on** — confirmed by grepping
every `romHandler.set*`/`randomize*` call site in `Randomizer.java` (starters
`:261`, trainers `:451-464`, statics `:532`, wild `:575`, TMs `:322`, field
items `:630`; all `switch`/`if` on a `*Mod` enum or boolean checkbox). The one
exception: `randomizeIntroPokemon()` is called completely unconditionally at
`Randomizer.java:671`, right before `saveRomFile` — no gate at all.

So "lossless with everything off" only has **two** unconditional call paths
to fix (`savePokemonStats`/`saveMoves` and `randomizeIntroPokemon`), plus
whatever those two touch that isn't a pure re-serialization of unchanged
fields. Everything conditional only needs to become **field-scoped** (not
disabled) the moment its category is turned on, because the owner's allowed
list includes wild/starters/statics/trainers(species+level)/TMs/field items.

## Patch 1 — `LosslessMode` flag + the two unconditional writers

**New INI key:** `LosslessMode=1` on `[PureRed (U)]`/`[PureBlue (U)]`/
`[PureGreen (U)]`; absent (defaults to `0`/false via `RomEntry.getValue`,
`upr_Gen1RomHandler.java:126-131`) for every vanilla entry — zero behavior
change for Red/Blue/Yellow/etc.

**1a. `savePokemonStats()` (`upr_Gen1RomHandler.java:744-768`)**
Currently unconditionally: rewrites every name (`745-752`), every base-stat
record incl. Mew (`753-764`), then calls `writeEvosAndMovesLearnt(true, null)`
(`767`) which re-derives evolutions from the live `Pokemon.evolutionsFrom`
list. As long as the in-memory `Pokemon` model round-trips byte-for-byte from
`loadBasicPokeStats`/`readPokemonNames`/`populateEvolutions`, this
re-serialization is a no-op on disk — **except** for the non-dex-species bug
in Patch 2 below, which corrupts data on *every* save regardless of
`LosslessMode`. No change needed to `savePokemonStats()` itself once Patch 2
is applied; do **not** gate it behind `LosslessMode` (it must still run to
apply stat/name randomization when those categories are enabled — note
neither is on the owner's allowed list, so in practice pureRGB's UI should
simply never expose base-stat/name/type/ability randomization for these
entries; that's a `Settings`/GUI-layer concern, not a `RomEntry` one, and out
of scope for this handler-level brief).

**1b. `Randomizer.randomizeIntroPokemon()` call (`Randomizer.java:671`) and
the method itself (`upr_Gen1RomHandler.java:2239-2246`)**
`pure.ini:94-96` sets `IntroPokemonOffset=N/A`, `IntroCryOffset=N/A`,
`PikachuEvoJumpOffset=N/A`. The INI loader's `parseRIInt` (`upr_Gen1RomHandler.java:291-304`)
cannot parse `"N/A"`: it hits the `catch (NumberFormatException)` branch,
prints a warning, and **returns `0`** — so `romEntry.getValue("IntroPokemonOffset")`
resolves to `0` and `randomizeIntroPokemon()` would write two bytes into
`rom[0]`/`rom[0]` (the ROM header) on every single save, for every pure
entry. This is a live corruption bug the moment the INI ships as drafted, not
merely a lossless nicety.
Fix: add a boolean check in `randomizeIntroPokemon()`:
```java
public void randomizeIntroPokemon() {
    if (!romEntry.hasIntroPokemon()) return;   // new RomEntry helper, see below
    ...
}
```
`RomEntry.hasIntroPokemon()` = `entries.containsKey("IntroPokemonOffset")`
(track presence before the "or 0" default kicks in — `getValue` at
`upr_Gen1RomHandler.java:126-131` needs a sibling `hasValue(String key)` that
returns `entries.containsKey(key)` without mutating the map). Loader change:
in `loadROMInfo()`'s generic key branch (`upr_Gen1RomHandler.java:238-256`),
treat the literal string `"N/A"` as "do not put a key" instead of falling
into `parseRIInt`. Vanilla entries keep the key present → `hasIntroPokemon()`
true → unchanged behavior. This same `hasValue`/`N/A` convention should be
reused for `PCPotionOffset=FORBIDDEN` and `TextDelayFunctionOffset=FORBIDDEN`
(`pure.ini:100-101`) — those two feed `miscTweaksAvailable()`
(`upr_Gen1RomHandler.java:2084-2113`), see 1d below.

**Test:** load a pure ROM, call `savingRom()` + a stubbed
`randomizeIntroPokemon()` skip, diff output vs input — must be byte-identical
(after Patch 2 is also applied; before it, the non-dex moveset pointers will
still differ every time, see below).

**1c. `setTrainers()` collateral (`upr_Gen1RomHandler.java:1339-1401`)**
Two unconditional side-effects *inside* the method, which only runs when the
user enables trainer-species/level randomization (an allowed category) but
still writes outside "species/level bytes only":
- `rom[romEntry.getValue("ExtraTrainerMovesTableOffset")] = (byte) 0xFF;`
  (`:1389`) — unconditionally disables the whole custom-AI-moveset table.
- champion/rival jump NOP at `GymLeaderMovesTableOffset - 0x44`
  (`:1392-1399`, guarded only by `!isYellow()`) — patches code, not data.
`pure.ini:82` explicitly says `GymLeaderMovesTableOffset` "must NOT be
NOP-patched (per task spec)".
**New INI keys:** `TrainerCollateralWritesEnabled=1` (default; vanilla
untouched) — pure entries set `0`. Wrap both blocks:
```java
if (romEntry.getValue("TrainerCollateralWritesEnabled") != 0) {
    rom[romEntry.getValue("ExtraTrainerMovesTableOffset")] = (byte) 0xFF;
    if (!isYellow()) { ...nop... }
}
```
Since `getValue` defaults missing keys to `0` (`:127-129`), a vanilla INI
that doesn't define the new key would silently disable this — so vanilla
entries must gain an explicit `TrainerCollateralWritesEnabled=1` line (small,
mechanical INI edit), or the default should be inverted to "enabled unless
key present and 0"; recommend the explicit-line approach, it's less
error-prone than an inverted default.

**1d. `setTMMoves()` gym-leader-move write (`upr_Gen1RomHandler.java:1714-1723`)**
Writes 8 bytes at `GymLeaderMovesTableOffset` (trainer AI move data, not a
"TM move byte") whenever TM move randomization runs — matches the given fact
"TM randomization writes gym leader moves". New key
`GymLeaderTMWriteEnabled=1` default; pure entries `0`; guard the
`if (!romEntry.isYellow())` block at `:1715-1723` with
`&& romEntry.getValue("GymLeaderTMWriteEnabled") != 0`.

**1e. `setStarters()` Pokédex-injection (`upr_Gen1RomHandler.java:872-935`,
gated by `romEntry.getValue("PatchPokedex") > 0`)** — this branch writes a
freshly-assembled Z80 routine (`rom[pkDexOnOffset] = GBConstants.gbZ80Jump`,
etc., `:907-935`) into ROM whenever starters are randomized: a code tweak,
not a data write, and explicitly banned by "must never apply any vanilla
code tweak". Fix: simply never set `PatchPokedex=1` in the pure INI
(`pure.ini` doesn't currently define it, and `getValue` defaults absent keys
to `0` — `:127-129` — so this branch is **already inert for pure entries as
drafted**; no code change needed, just confirm the key stays absent/`0` and
add a comment in the INI so nobody "helpfully" turns it on later).

**1f. Misc tweaks (`upr_Gen1RomHandler.java:2084-2141`)** — every tweak in
`applyMiscTweak`/`miscTweaksAvailable` is a direct code write or IPS patch by
definition (`BW_EXP_PATCH`, `NERF_X_ACCURACY`, `FIX_CRIT_RATE`,
`FASTEST_TEXT`, `RANDOMIZE_PC_POTION`, `ALLOW_PIKACHU_EVOLUTION`,
`LOWER_CASE_POKEMON_NAMES`, `UPDATE_TYPE_EFFECTIVENESS`,
`RANDOMIZE_CATCHING_TUTORIAL`). All are opt-in via GUI checkboxes fed by
`miscTweaksAvailable()`, so they're never touched unless clicked — but the
owner's "must never apply any vanilla code tweak" rule means pure entries
must not even **offer** them. Fix:
```java
public int miscTweaksAvailable() {
    if (romEntry.getValue("LosslessMode") != 0) return 0;
    ... existing logic ...
}
```
at `upr_Gen1RomHandler.java:2084`. Vanilla entries (no `LosslessMode` key →
`getValue` returns `0`) are unaffected.

## Patch 2 — base-stat stride, `NonDexMonsBaseStats`, and the moveset-pointer corruption bug

**The bug (verified, severe, unconditional):** `writeEvosAndMovesLearnt`
(`upr_Gen1RomHandler.java:2664-2858`) walks **internal ids** `i = 1..pkmnCount`
(`InternalPokemonCount`, `:2681,2701`). For any `i` where
`pokeRBYToNumTable[i] == 0` — i.e. any internal id whose `PokedexOrder` byte
is 0 — the code treats it as a "null entry" (`:2705-2713`) and collapses
**all** such ids onto one shared 2-byte `{0,0}` pointer
(`nullEntryPointer`, first one wins, `:2707-2713`). `pokeRBYToNumTable` is
populated purely from the `PokedexOrder` table in `loadPokedexOrder`
(`:367-379`) with no notion of "this dex-0 id is actually a real, distinct
species with its own moveset/evolution record." pureRGB's 13
`NonDexMonsBaseStats` internal ids (`MISSINGNO $B5`, `ARMORED_MEWTWO $AE`,
`POWERED_HAUNTER $AF`, `HARDENED_ONIX $AC`, `FLOATING_MAGNETON $38`,
`FLOATING_WEEZING $92`, four `SPIRIT_*`, `WINTER_DRAGONAIR $5E`,
`VOLCANIC_MAGMAR $34`) all have `PokedexOrder` = their base species' dex or 0
per the task's given facts, so **every one of them falls into this branch**
— their real evolution+moveset bytes get overwritten with the shared null
entry on the very first save, lossless or not. This is a P0: it breaks the
byte-identical requirement unconditionally (it fires inside `savePokemonStats`
→ `writeEvosAndMovesLearnt(true, null)`, `:767`, which runs on every save per
Patch 1).

**Fix — `NonDexSpecies[]` INI key + verbatim-copy path:**
Add `NonDexSpecies=[0xB5, 0xAE, 0xAF, 0xAC, 0x38, 0x92, 0x1F, 0x56, 0x73, 0x32,
0x86, 0x5E, 0x34]` (internal ids, hex, parsed the same way as
`StarterOffsets1` — reuse the existing `[...]`-bracket array-parsing branch
at `upr_Gen1RomHandler.java:238-250`, no parser change needed) to the pure
entries. New `RomEntry` field `Set<Integer> nonDexInternalIds` populated from
`arrayEntries.get("NonDexSpecies")` in `loadedRom()` or lazily via
`romEntry.arrayEntries`. In `writeEvosAndMovesLearnt`, change the branch at
`:2705`:
```java
if (pokeRBYToNumTable[i] == 0) {
    if (isNonDexInternalId(i)) {
        // verbatim copy — this internal id has no Pokemon object, but its
        // record must survive unchanged (same bytes as the writeEvos==false /
        // movesets==null "copy old" paths at :2721-2728 and :2751-2762)
        int srcOffset = oldDataOffset;
        while (rom[srcOffset] != 0x00) {
            int method = rom[srcOffset] & 0xFF;
            srcOffset += (method == 2) ? 4 : 3;
        }
        srcOffset++;
        while (rom[srcOffset] != 0x00) { srcOffset += 2; }
        srcOffset++; // include the moves terminator
        writeData = Arrays.copyOfRange(rom, oldDataOffset, srcOffset);
    } else if (nullEntryPointer == -1) {
        writeData = new byte[] { 0, 0 };
        setNullEntryPointerHere = true;
    } else {
        writeWord(pointerTable, (i - 1) * 2, nullEntryPointer);
    }
}
```
(the evolution-copy and moveset-copy loops here are the same byte-walking
logic already proven correct at `:2721-2728`/`:2751-2762`; this just applies
it to a wider id range instead of only "real" Pokemon.) This makes the
write byte-identical to the read for these 13 ids in all cases — it's the
minimal fix that satisfies "lossless" without modeling them as first-class
`Pokemon` objects at all, since the owner's whitelist has no category that
would ever legitimately want to rewrite their movesets/evolutions anyway.

**Base stats:** `NonDexMonsBaseStats` (13 records × `baseStatsEntrySize`=0x1C,
confirmed `Gen1Constants.baseStatsEntrySize = 0x1C`,
`upr_Gen1Constants.java:37`) live at their own table offset, entirely
separate from `PokemonStatsOffset`. `loadPokemonStats`/`savePokemonStats`
(`upr_Gen1RomHandler.java:718-768`) only ever touch
`pokeStatsOffset + (i-1)*0x1C` for `i = 1..pokedexCount` (dex order) plus the
one Mew special-case (`:727-728,736,756-764`) — they never read or write the
`NonDexMonsBaseStats` region at all, by construction, so those 13 records'
*stat bytes* are already safe/lossless by omission. **No handler patch
needed for base stats themselves** — only the moveset/evolution pointer bug
above needs fixing. (New INI key `NonDexStatsOffset` from the task's proposed
list is not actually required unless a future pass wants to expose these 13
as randomizable Pokemon — out of scope per the owner's allowed-category
list; note this as a scope decision, not an oversight.)

**`pokeNumToRBYTable`/`pokeRBYToNumTable` and dex-0 (MISSINGNO) crash risk:**
`loadPokedexOrder` (`:367-379`) leaves `pokeRBYToNumTable[i] = 0` for MISSINGNO
and any dex-0 internal id — by design, this is meant to mean "no such
Pokemon." But `pokes[]` is allocated as `new Gen1Pokemon[pokedexCount + 1]`
(`:719`) and the load loop only fills indices `1..pokedexCount` (`:724-732`)
— **`pokes[0]` is always `null`**. Any code path that does
`pokes[pokeRBYToNumTable[x]]` where `x` is MISSINGNO's internal id
(`$B5`) — e.g. wild-encounter reads at `:1048` (Sea Routes, per the given
fact that MISSINGNO appears there) or a static read via `StaticPokemon.getPokemon`
(`:1592`) — silently produces a **null `Pokemon`** inside an `Encounter`/
`StaticEncounter`. The first randomizer pass, GUI list render, or log-print
that calls `.number`/`.name` on that null Pokemon NPEs. This is UNVERIFIED
whether it triggers in practice for pureRGB's specific Sea Routes table (I
did not get to build/run a probe), but the code path is confirmed live at
the cited lines and the given facts confirm MISSINGNO appears in a wild
table and as a static.
**Fix:** give `pokes[0]` a real sentinel object. In `loadPokemonStats`
(`:718-742`), after allocating `pokes`, add:
```java
pokes[0] = new Gen1Pokemon();
pokes[0].number = 0;
pokes[0].name = "MISSINGNO";
```
and make sure `getPokemon()`/`getPokemonInclFormes()` (`:1233-1240`, which
return `pokemonList = Arrays.asList(pokes)` built at `:359` from the same
array) **exclude index 0** so it's never offered as a randomization target —
change `pokemonList` construction to `Arrays.asList(pokes).subList(1, pokes.length)`
or filter nulls/index-0 explicitly. This keeps MISSINGNO readable/writable
(round-trips its own byte, `pokeNumToRBYTable[0]` naturally stays unset/`0`
so nothing ever maps back to internal id 0 incorrectly) without ever handing
it to the randomizer as a real species choice.

## Patch 3 — pointer-table names (`loadMoveNames`/`ItemNames`)

`readMoveNames()` (`upr_Gen1RomHandler.java:408-417`) and `loadItemNames()`
(`:2274-2303`) both assume **sequential, back-to-back, length-prefixed
strings** starting at a single offset (`offset += lengthOfStringAt(offset,
false) + 1`, `:414`; the `while` terminator-scan variant at `:2289-2292`).
pureRGB's `MoveNameJumpTable`/`ItemNameJumpTable` are **pointer tables**
(array of 2-byte pointers, one per move/item, pointing to scattered string
data) — confirmed as a given fact and flagged `POINTER TABLE` in
`pure.ini:51-52`. Reading sequentially from `MoveNamesOffset`/`ItemNamesOffset`
as a flat blob will read whatever bytes happen to be there (likely the
pointer table itself, decoded as garbled text) — wrong data, not a crash.

Every call site that needs a fix: `loadMoves()` (`:420`, via `readMoveNames()`),
`getTrainerNames`/`getTrainerClassesForText`/`getTrainerClassNames` do **not**
depend on this (they use `readVariableLengthString`/`lengthOfStringAt`
directly against `TrainerClassNamesOffsets`, a genuinely sequential table —
unaffected), `setTMMoves()`'s TM-text substitution (`:1726`, re-calls
`readMoveNames()` to look up move names for TM description text), and
`loadItemNames()` (`:2274-2303`, used everywhere item names are displayed/
diffed).

**Minimal, correct-scope fix given the task's constraints:** the task brief
itself already scoped this out — `pure.ini:51-52` comments say "not in this
pass's scope" / "same caveat" and mark these read-only. Recommend exactly
that for the fork: add `NamesArePointerTables=1` (new key; default `0`,
vanilla untouched) and make `readMoveNames()`/`loadItemNames()` **read-only
placeholders** for pure entries — i.e., detect the flag and skip attempting
to parse real names, instead synthesizing `"Move %d"`/`"Item %d"` labels so
the GUI has *something* to show, while refusing any randomization category
that depends on writing a *new* name back (there is no `saveMoveNames`/
`saveItemNames` in this handler at all — move/item **names** are never
written by the randomizer, only move/item **stats** — so this is purely a
display-correctness issue, not a lossless-safety issue; leaving it
`UNVERIFIED`/best-effort is acceptable). If real names are wanted later, the
correct reader is:
```java
int ptr = readWord(jumpTableOffset + (index - 1) * 2);
int nameOffset = calculateOffset(bankOf(jumpTableOffset), ptr);
String name = readVariableLengthString(nameOffset, false);
```
(mirrors the existing pointer-deref pattern already used for
`PokemonMovesetsTableOffset` at `:1521-1522` and `TrainerDataTableOffset` at
`:1274-1275` — same `readWord` + `calculateOffset` idiom, just applied per
move/item index instead of per Pokemon/trainer-class).
`loadPokemonNames`/`MonsterNames` needs **no change** — it's fixed-width
(`PokemonNamesLength=10`, confirmed `pure.ini:19` and read via
`readFixedLengthString(offs + (i-1)*nameLength, nameLength)`,
`upr_Gen1RomHandler.java:812-821`), not a pointer table.

## Patch 4 — Trainers: 56-class table, `$FF`/`$FE`/`$FD` grammar, single-`TrainerNames` table

**Class count is hardcoded in Java, not the INI — this is the real blocker.**
`Gen1Constants.trainerClassCount = 47` (`upr_Gen1Constants.java:46`) and
`Gen1Constants.tclassesCounts = {21, 47}` (`upr_Gen1Constants.java:54`) are
`static final` fields shared by **every** Gen1 `RomEntry** — Red, Blue,
Yellow, and any fork all read the same Java constant. `getTrainers()`/
`setTrainers()` both do `int traineramount = Gen1Constants.trainerClassCount;`
(`upr_Gen1RomHandler.java:1269, 1341`), and `getTrainerNames`/
`setTrainerNames`/`getTrainerClassesForText`/`getTrainerClassNames` all loop
`Gen1Constants.tclassesCounts[1]` times (`:1927, 1950, 1966, 1995, 2005`
respectively). pureRGB has 56 classes (confirmed, `pure.ini:79`: "56 classes
total (vanilla has 47) -> Gen1Constants.trainerClassCount must become 56 for
this fork"), so simply changing the `static final` breaks vanilla Red/Blue/
Yellow.
**Fix:** move both to `RomEntry`-scoped INI keys:
`TrainerClassCount=56` (new key; parsed via the existing scalar branch,
`upr_Gen1RomHandler.java:252-255`) and `TrainerRecordGrammars` →
practically this is just `TClassesCounts=[21,56]` per entry (reusing the
existing bracket-array parser at `:239-250`). Every one of the five call
sites above changes from `Gen1Constants.trainerClassCount`/
`Gen1Constants.tclassesCounts[1]` to `romEntry.getValue("TrainerClassCount")`/
`romEntry.arrayEntries.get("TClassesCounts")[1]`. Vanilla INI entries gain
explicit `TrainerClassCount=47` / `TClassesCounts=[21,47]` lines (mechanical,
preserves current behavior exactly since it's the same numbers, just
INI-sourced instead of Java-sourced).

**`singularTrainers`** (`upr_Gen1Constants.java:56`, vanilla indices
`28,32,33,34,35,36,37,38,39,43,45,46` into the 47-class table) drives which
class-slots get an individual `TrainerNames` entry vs. share the class name
(`getTrainerNames`/`setTrainerNames`/`getTrainerClassNames`,
`:1946-1975, 1988-2014`). pureRGB's single 56-entry `TrainerNames` table
(`pure.ini:85-92`, confirmed one table not two, with Rival1/Rival2/Champion
slots as intentionally-blank strings) almost certainly needs a **different**
index set for its 56-slot layout — this is `UNVERIFIED` (would need the
actual pureRGB trainer-class ordering, which wasn't in the provided sources).
Same fix pattern: `singularTrainers` becomes `romEntry.arrayEntries.get("SingularTrainerClasses")`
instead of a shared static list.

**`TrainerClassNamesOffsets` single-table branch already exists and works** —
verified: `getTrainerClassNames()` (`:1989-2014`) already branches on
`offsets.length == 2` (two-table, vanilla) vs. the `else` single-table case
(`:2003-2012`); `getTrainerNames()`/`setTrainerNames()`/
`getTrainerClassesForText()` already use `offsets[offsets.length - 1]`
generically (`:1926, 1949, 1965`), so they already work whether `offsets`
has length 1 or 2. **No code change needed here** — `pure.ini:92`'s
`TrainerClassNamesOffsets=[0xEB071]` (a length-1 array) already routes
correctly through existing logic, *provided* `TrainerClassCount`/
`TClassesCounts[1]` above are fixed to 56 (these loops are bounded by that
constant, not by the offsets array).

**`tagTrainersRB`/`tagTrainersYellow`/`tagTrainersUniversal`**
(`upr_Gen1Constants.java:150-255`) hardcode `(classNum, occurrenceNumber)` →
tag ("GYM1", "RIVAL3-2", etc.) pairs by **class number**, assuming vanilla's
class-number-to-role mapping. Called unconditionally from `getTrainers()`
(`upr_Gen1RomHandler.java:1320-1325`). If pureRGB's 56-class table assigns
different class numbers to gyms/rivals/E4 than vanilla's 47-class table
(near-certain, since 9 extra classes had to be inserted somewhere), every tag
will land on the wrong trainer. This only affects the "special" handling
UPR's higher-level randomizer uses for things like "keep gym 1 easy" logic —
it doesn't corrupt ROM bytes, but it does mean per-entry override or a
pureRGB-specific `tagTrainersPureRGB(trs)` method is needed; `UNVERIFIED`
which classes moved without the actual pureRGB trainer table dump. Given the
owner's allowed category is "trainers (species/levels only)" with no
gym-specific special-casing requirement stated, the safe minimal move is:
add a `TrainerTaggingDisabled=1` INI key and skip the
`tagTrainersUniversal`/`tagTrainersRB`/`tagTrainersYellow` calls entirely for
pure entries (`upr_Gen1RomHandler.java:1320-1325`) rather than risk
mis-tagging — the randomizer's core species/level swap does not require tags.

**`$FF`/`$FE`/`$FD` party-record grammar:** the given facts describe pureRGB
adding `$FE` (level|alt-palette-bit per mon) and `$FD` (custom-moveset-id,
then level, then species...) prefixes in addition to vanilla's `$FF`
(special/individual levels, `:1294-1304`) and implicit fixed-level
(`:1305-1315`) forms. **This is a real parser gap**: `getTrainers()`/
`setTrainers()` (`:1293-1316`, `1361-1382`) only branch on
`dataType == 0xFF` vs. else, and the else branch assumes the first byte is a
flat level shared by the whole party with no per-mon variation. Any `$FE`/
`$FD` record would be misparsed as a garbage "fixed level" byte and the
following bytes misread as species. Fix requires extending both loops with
new branches for `0xFE`/`0xFD`, but the exact grammar (byte order, how the
alt-palette bit is packed, how a custom-moveset id maps to a fourth data
table) was **not present in the provided sources** — this needs the actual
pureRGB party-data disassembly before a patch can be written; flagging as
`UNVERIFIED — needs pureRGB source, not derivable from UPR alone`. The
owner's "species/level bytes only" constraint means whatever parser is
written must preserve the `$FE` palette bit and the `$FD` custom-moveset-id
byte verbatim (read them into the `TrainerPokemon` model as opaque extra
data, or store them in a side-table keyed by trainer/slot) and only ever
overwrite the species byte (+ level byte where present) — never the
palette-bit or moveset-id bytes, or lossless breaks the moment any trainer
in the pure ROI has one of these records.

## Patch 5 — Statics

`StaticPokemon` (`upr_Gen1RomHandler.java:1582-1611`) already supports
multiple `speciesOffsets` per record (`setPokemon` loops all of them,
`:1595-1599`) and the INI parser already supports multi-value
`Species=[0x..,0x..]`/`Level=[0x..,0x..]` arrays in one `StaticPokemon{}`
line (`parseStaticPokemon`, `:267-289`) — **no handler change needed** for
the "both wCurOpponent-style and wEngagedTrainerClass-style offsets are
plain immediates" fact; they're both just `rom[offset] = (byte) species`
writes regardless of which WRAM cell they eventually feed, exactly as
`pure.ini:141-148` already concludes.

**Real bug found: `setStaticPokemon()` only ever writes `levelOffsets[0]`.**
`upr_Gen1RomHandler.java:1628-1640`:
```java
sp.setPokemon(this, se.pkmn);       // loops ALL speciesOffsets — correct
sp.setLevel(rom, se.level, 0);      // hardcoded index 0 — bug
```
For the linked Zapdos pair (`pure.ini:136,163`: roof `species@0x1ab63
level@0x1ab68` + floor object-table `species@0x1edae level@0x1edaf`,
explicitly "LINKED... should be patched together"), if authored as **one**
`StaticPokemon{}` record with `Species=[0x1ab63,0x1edae]
Level=[0x1ab68,0x1edaf]`, `setPokemon` correctly writes the same species to
both offsets, but `setLevel(rom, se.level, 0)` only writes `levelOffsets[0]`
(`0x1ab68`) — `0x1edaf` (the floor copy) keeps its **old** level forever,
even when static Pokémon randomization is on. Not a lossless bug (bytes only
diverge when statics are randomized, an allowed category) but a real
data-consistency bug for exactly the case the ini calls out.
**Fix:** in `setStaticPokemon()` (`:1628-1640`), replace the single
`sp.setLevel(rom, se.level, 0)` with:
```java
for (int lvlIdx = 0; lvlIdx < sp.levelOffsets.length; lvlIdx++) {
    sp.setLevel(rom, se.level, lvlIdx);
}
```
(`StaticPokemon.setLevel`, `:1608-1610`, already takes an index and just does
`rom[levelOffsets[i]] = (byte) level;` — trivial to loop.) This also means
the two linked Zapdos entries and the Mewtwo/Articuno/Moltres/Magmar/Cloyster
`wEngagedTrainerClass`-style entries from `pure.ini:135-148` should each be
**one** `StaticPokemon{}` record (species+level immediate pair), not
requiring any further code change beyond this loop fix.

**Ghost Marowak** (`StaticPokemonGhostMarowak{}`, `pure.ini:149`) already has
dedicated parsing (`upr_Gen1RomHandler.java:176-179`, populates
`ghostMarowakOffsets`) and a dedicated read site in `getEncounters()`
(`:1016-1019`) — no change needed, offsets are just new numbers.

**Double-encoded Zapdos** — see above; the "double encoding" *is* the
roof-trigger-immediate + floor-object-table pair, already covered by the
multi-offset `StaticPokemon{}` fix.

## Patch 6 — Fishing

Current `getEncounters()`/`setEncounters()` (`upr_Gen1RomHandler.java:1065-1088`,
`1174-1188`) hardcode: **old rod = exactly 1 pair** at
`oldRodOffset+1`(species)/`+2`(level); **good rod = exactly 2 pairs**
(`grSlot` 0,1) at `goodRodOffset + grSlot*2`. pureRGB's layout per the given
facts is **two old-rod pairs** and **good rod land+ocean, 4 pairs each**
(using the new `GoodRodMonsOcean=0xDF32` offset already in `pure.ini:39`,
alongside land at `GoodRodOffset=0xDF28`). Both loop bounds are literals in
Java, not INI-driven, so this needs real code changes:
```java
// old rod — was single Encounter, becomes a loop of OldRodPairCount
int oldRodPairCount = romEntry.getValue("OldRodPairCount"); // new key, default 1
for (int r = 0; r < oldRodPairCount; r++) {
    Encounter enc = new Encounter();
    enc.level = rom[oldRodOffset + r*2 + 2] & 0xFF;
    enc.pokemon = pokes[pokeRBYToNumTable[rom[oldRodOffset + r*2 + 1] & 0xFF]];
    oldRodSet.encounters.add(enc);
}
```
and for good rod, loop `GoodRodPairCount` (new key, default 2) over
`GoodRodOffset` for land **and again** over `GoodRodMonsOcean` for ocean,
producing two separate `EncounterSet`s ("Good Rod Fishing (Land)"/"(Ocean)")
instead of the current single set. Mirror the same shape in `setEncounters()`
(`:1174-1188`). New INI keys: `OldRodPairCount=1` (default; pure=`2`),
`GoodRodPairCount=2` (default; pure=`4`), `GoodRodMonsOcean=0` (default `0`
→ treated as absent/disabled; pure sets the real offset already drafted).
Super rod (`:1089-1138`, `1190-1224`) is **unchanged** for pure entries per
`pure.ini:40` ("RE-CONFIRMED: matches UPR's own grammar, no delta") — no
patch needed there.

## Patch 7 — Map names (5-byte internal rows) and hidden items (4 entry points)

**Map names:** `loadMapNames()` internal-name loop
(`upr_Gen1RomHandler.java:2443-2470`) steps `mapNameTableOffset += 4` per
row (`:2469`) — external-name loop above it (`:2434-2440`, 3-byte stride,
pointer at `+1`) is untouched and already byte-for-byte matches pureRGB per
`pure.ini:44-45` ("byte-for-byte match of UPR's reader"). Fix: new INI key
`MapNameInternalRowSize=4` (default; pure=`5`), change line `:2469` from
`mapNameTableOffset += 4;` to
`mapNameTableOffset += romEntry.getValue("MapNameInternalRowSize");`. Row
layout otherwise identical (`maxMap` at `+0`, name pointer at `+2`) per
`pure.ini:47` — only the stride changes, the extra trailing byte (a
"wild-data map id") is simply skipped over, never read or written, so this
is purely additive/safe.

**Hidden items:** `getItemOffsets()` (`upr_Gen1RomHandler.java:2473-2524`)
matches a single `hiRoutine` value by equality at `:2497` and `:2514`:
```java
if (calculateOffset(rom[spclOffset + 3] & 0xFF, readWord(spclOffset + 4)) == hiRoutine) {
    itemOffs.add(spclOffset + 2);
}
```
pureRGB has 4 valid entry points 8 bytes apart (`HiddenItems`/`HiddenItems2/
3/5`, confirmed `pure.ini:110-116`); any hidden-item record whose target is
`HiddenItems2/3/5` is silently skipped today, meaning those items are never
offered to (or written by) field-item randomization. Fix: new INI key
`HiddenItemRoutineEntries=[0x77352,0x7735A,0x77362,0x7736A]` (array, parsed
via the existing bracket-array branch, `:239-250`); replace both equality
checks (`:2497`, `:2514`) with a membership test against
`romEntry.arrayEntries.get("HiddenItemRoutineEntries")` (a `Set<Integer>` for
O(1) lookup, built once in `loadedRom()`). Keep the singular
`HiddenItemRoutine` key too, defaulting `HiddenItemRoutineEntries` to a
one-element array `[HiddenItemRoutine]` when absent, so vanilla entries (one
entry point) need no INI edits at all — pure code adds the array-or-fallback
logic, vanilla behavior is bit-identical.
The Itemfinder-only `HiddenItemCoords` mechanism (`pure.ini:117-122`) is
confirmed genuinely out of scope (no `item` field to randomize) — no patch,
leave alone as the ini already recommends.

## Patch 8 — Detection

`checkRomEntry` (`upr_Gen1RomHandler.java:381-400`) matches on ROM header
title text (`romSig`, not shown in the excerpts read but referenced at
`:387,394`) + `version` + `nonJapanese` + `crcInHeader`
(read from the cartridge header at `GBConstants.crcOffset`,
`:385`) — exact-CRC entries are preferred, falling back to `-1` ("any CRC")
entries. `pure.ini:15,177,190` set `CRCInHeader=0x929B` / `0xCC68` / `0xC775`
for the three pure entries; these are distinct from vanilla's per-entry CRCs
(not in the provided excerpt of `gen1_offsets.ini`, so I could not directly
diff against vanilla Red's `0x929B`-vs-something-else — **UNVERIFIED**: I
could not confirm no collision because the vanilla `gen1_offsets.ini` file
itself wasn't in the provided sources, only referenced by the task prompt's
own aside "vanilla Red CRCInHeader vs 0x929B etc." which reads as the task
author already having checked this. Recommend the verification step in
Patch 9 explicitly re-derive and diff all `CRCInHeader` values across the
full `gen1_offsets.ini` (vanilla + pure) before merging, as a 5-minute grep,
since `checkRomEntry`'s first loop (`:386-391`) returns the **first** match
and silently mis-detects a ROM if two entries share `romName`+`version`+
`nonJapanese`+`crcInHeader`.

## Patch 9 — Verification plan

**(a) Byte-identical load→save, all settings off.** Build a tiny JUnit (or a
standalone `main`) that: loads each of the 3 pure ROMs, calls
`loadedRom()`, immediately calls `savingRom()` with zero randomization
categories touched (i.e. don't call any `randomize*`/`set*` — just exercise
the load→save round trip UPR does for a no-op run), and diffs `rom[]` against
the original file byte-for-byte. This must be **exactly** the test the owner
described. It will fail today for two reasons found in this pass: (1)
`randomizeIntroPokemon()` writing `rom[0]` because of the `N/A` parsing bug
(Patch 1b) — fails immediately, corrupts the header; (2) the non-dex
moveset-pointer collapse (Patch 2) — fails on any pure ROM that has
`NonDexMonsBaseStats` entries, which is all three. Once both are fixed, this
test is the actual lossless gate; run it in CI on every pure-INI or
Gen1RomHandler change.

**(b) Per-category diff allowlists.** For each allowed category, run with
*only* that category randomized and assert every byte that changed falls
inside a precomputed allowlist of ranges:
- wild encounters: `WildDataPointers`-derived grass/water/rod tables only
  (the ranges `getEncounters()` reads, `:1013-1141` plus the Patch 6
  land/ocean split) — species+level bytes only, never the rate byte or table
  structure.
- starters: exactly the `StarterOffsets1/2/3` sites (`pure.ini:67-71`,
  **including** the cosmetic sites the ini flags as "NOT byte-verified" —
  those must either be added to `StarterOffsets{1,2,3}` arrays so UPR writes
  them consistently, or explicitly excluded from the allowlist and left
  stale, which would be a starter/title-screen mismatch bug; recommend
  including them and verifying byte-for-byte before merge, since a
  half-updated starter (party correct, title screen still shows the old
  species) is a visible regression).
- statics: exactly the offsets in every `StaticPokemon{}`/
  `StaticPokemonGhostMarowak{}` record.
- trainers: with `TrainerCollateralWritesEnabled=0` and
  `GymLeaderTMWriteEnabled=0` (Patch 1c/1d), only species (+level where the
  `$FF` form allows per-mon levels) bytes inside the trainer party records
  the class/index loop touches (`:1361-1382`).
- TMs: `TMMovesOffset` (50 bytes) plus TM description text bytes
  (`tmTexts`, `:1725-1731`) — **not** `GymLeaderMovesTableOffset` once Patch
  1d lands.
- field items: exactly the offsets `getItemOffsets()` (Patch 7's fixed
  version) returns, both map-table items and the 4-entry-point hidden items.

Build this allowlist as a small Python/Java script that takes two ROM
buffers + a list of `(start,len)` ranges and asserts `diff_ranges ⊆
allowlist`; reuse it as the shared harness for all six categories.

**(c) Vanilla regression.** Run the existing UPR Gen1 test/CI suite (if any
exists in the ZX repo — not confirmed present in the provided sources,
`UNVERIFIED`) against real Red/Blue/Yellow ROMs after every patch above,
since Patches 1c/1d/1f/4/6/7 all touch shared code paths
(`setTrainers`, `setTMMoves`, `miscTweaksAvailable`, `getTrainers/setTrainers`
class-count plumbing, fishing, map names, hidden items) that vanilla entries
also execute. Every new INI key in this brief is designed to default to the
exact current vanilla behavior when absent (`RomEntry.getValue` defaults
missing keys to `0`, `upr_Gen1RomHandler.java:126-131`) or to require an
explicit same-value line be added to vanilla's INI (Patch 4's
`TrainerClassCount`/`TClassesCounts`) — grep the diff of
`gen1_offsets.ini` after this change and confirm every vanilla `[RomEntry]`
section gained only mechanical same-value lines, never a behavior-changing
one.

## Summary of new INI keys

| Key | Default (vanilla, absent) | Pure value | Consumed by |
|---|---|---|---|
| `LosslessMode` | `0` | `1` | `miscTweaksAvailable` (Patch 1f) |
| `TrainerCollateralWritesEnabled` | `1` (needs explicit vanilla line) | `0` | `setTrainers` (Patch 1c) |
| `GymLeaderTMWriteEnabled` | `1` (needs explicit vanilla line) | `0` | `setTMMoves` (Patch 1d) |
| `NonDexSpecies[]` | absent → empty set | 13 internal ids | `writeEvosAndMovesLearnt` (Patch 2) |
| `NamesArePointerTables` | `0` | `1` | `readMoveNames`/`loadItemNames` (Patch 3, read-only placeholder) |
| `TrainerClassCount` | needs explicit `47` line | `56` | `getTrainers`/`setTrainers` (Patch 4) |
| `TClassesCounts[]` | needs explicit `[21,47]` line | `[21,56]` | trainer-name loops (Patch 4) |
| `SingularTrainerClasses[]` | needs explicit vanilla-index line | `UNVERIFIED` new indices | `getTrainerNames`/`setTrainerNames`/`getTrainerClassNames` (Patch 4) |
| `TrainerTaggingDisabled` | `0` | `1` | `getTrainers` (Patch 4, safety valve) |
| `OldRodPairCount` | `1` | `2` | fishing (Patch 6) |
| `GoodRodPairCount` | `2` | `4` | fishing (Patch 6) |
| `GoodRodMonsOcean` | `0` (absent) | real offset (already drafted) | fishing (Patch 6) |
| `MapNameInternalRowSize` | `4` | `5` | `loadMapNames` (Patch 7) |
| `HiddenItemRoutineEntries[]` | `[HiddenItemRoutine]` (fallback) | 4 entry points | `getItemOffsets` (Patch 7) |

`BaseStatsEntrySize`/`NonDexStatsOffset` from the task's suggested key list
were evaluated and found **not needed**: `baseStatsEntrySize` is already a
shared constant equal to pureRGB's actual stride (0x1C = 35, confirmed
`upr_Gen1Constants.java:37` against the given fact), and the
`NonDexMonsBaseStats` table is never touched by existing code so needs no
offset key unless a future pass wants to randomize those 13 records (a scope
decision, not a gap).

## Items marked UNVERIFIED

1. Exact `$FE`/`$FD` trainer-party grammar (byte order, palette-bit packing,
   custom-moveset-id table) — needs pureRGB disassembly, not present in
   provided sources (Patch 4).
2. Which of pureRGB's 56 trainer classes correspond to gyms/E4/rivals for
   `tagTrainersRB`/`tagTrainersYellow`/`singularTrainers` re-indexing — same
   reason (Patch 4). Recommended interim fix (`TrainerTaggingDisabled`) does
   not require this.
3. Whether `CRCInHeader` values collide between pure and vanilla entries in
   the *full* `gen1_offsets.ini` — only the pure-entry excerpt was provided
   (Patch 8).
4. Whether the ZX repo has an existing Gen1 automated test suite to run for
   regression (Patch 9c) — not present in provided sources.
5. Whether wild-encounter/static reads for MISSINGNO ($B5) actually execute
   in a live pureRGB randomizer run today (vs. only being a latent null-object
   risk) — flagged as a code-path-confirmed, execution-unconfirmed risk in
   Patch 2's `pokes[0]` section.
