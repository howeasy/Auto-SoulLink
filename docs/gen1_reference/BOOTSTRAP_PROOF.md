# Normal New Game evidence

`gen_gen1_bootstrap_sites.py` pins the normal `StartNewGame` entry and the
instruction after `StartNewGameDebug` calls `OakSpeech`. Source and clean ROM
bytes verify the debug-bit reset, clear of `wPlayerName..wBoxDataEnd`, empty-list
initialization, and normal name selection for Red, Blue, and Yellow.

`gen1_bootstrap_observer.lua` must be installed before New Game. Its scope is the
physical instance and context generation; a trainer identity does not exist yet.
The hooks read only, pair the entry/return stack and advancing frame, and reject
reentry, restart, changed context, or missing normal entry. Publication requires
a held boundary. The module neither acquires an emulator host nor grants frames.

`gen1_bootstrap_receipt.py` compares the initialization-owned identity, party,
current box, and Pokedex bytes to the first enrollment source. Both inventories
must still be empty, with no seen/owned species or initialized box history.
Map-entry sprites and unrelated volatile bytes are not incorrectly required to
remain fixed. SRAM is not inferred from empty WRAM: a prior save may still occupy
the cartridge, and an initial save with file proof remains separate work.

Thirty-three focused cases pass, including wrong site/bank/stack/context,
same-frame or future-frame witnesses, changed inventory, old storage history,
and observer lifecycle failures. The replacement original-engine gate boots
with a private empty battery-save file and drives the normal title/menu/intro
with button inputs. It uses no CPU jumps, cartridge writes, or injected stop.
Red, Blue, and Yellow pass (3 cases, 28.92 seconds), including actual bedroom
movement. Full WRAM/SRAM and frame outcomes agree with the observer disabled
and enabled, as do all 24 screenshot pairs. Original source save fixture hashes
are unchanged. Screenshots were visually inspected, including the title,
dialogue, bedroom, and movement in all three titles.

An earlier direct-routine gate was a false positive: entering New Game from an
already-running overworld produced garbled graphics despite equal memory in
observer-on/off runs. A separate injected-stop bug also corrupted fixture RAM
before it was corrected. The user requested screenshots, which exposed the
remaining visual defect. That gate's startup qualification is withdrawn and its
CPU/write shortcuts have been removed. Memory equality alone is insufficient
for a visual lifecycle claim. The replacement evidence is
`.cache/bootstrap-normal-menu-screenshots.xml` and
`.cache/bootstrap-screenshot-review.html`.

This primitive is not yet wired into the launcher or used to clear the initial
history hold. Bounded ordinary frames require one host owner, observer ownership
that remains valid inside an authorized frame, held publication between steps,
server-owned frame accounting, and attribution of authorized cartridge writes.

## Bounded observation follow-up

The production entry now supplies separate stable `source_owned` and held
`owned` readers to initial observation. Engine hooks use the stable reader;
inventory sampling, publication, and held writes retain their held reader and
the existing frame restriction. Both readers must name the same identity when
the source observer is constructed. The default remains compatible with held
callers that supply only `owned`.

The composed Lua hook tests reproduce the old failure as a negative control,
prove capture while the modeled host is running and publication only after it
is held, and retain refusal on identity/ROM change. Forty focused observation,
launcher, and runtime-client cases pass.

The real normal-menu bootstrap also passes through the existing bounded host
owner (Red 3,636 steps, Blue 3,655, Yellow 3,723). Three selected live cases pass
in 55.84 seconds; the three ordinary baseline test nodes were deselected in
this focused invocation. Each bounded case internally compares to an ordinary
baseline, including byte-identical screenshots, memory, and frame count. A
foreign authority token cannot advance an extra frame. These tests use an
explicit test authority token; server-backed ordinary frame accounting and
the complete production engine/inventory lifecycle remain unfinished. This
is not a full release-lane result.

The ten existing downloaded-launcher live regressions also pass after this
callback change (48.11 seconds), preserving pending commands, initial enrollment,
permitted faint execution, and withheld-permission refusal under the fixed hold.
