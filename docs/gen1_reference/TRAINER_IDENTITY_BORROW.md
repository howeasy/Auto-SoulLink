# Source-qualified RBY trainer-name identity

`lua/gen1_identity_guard.lua` is a read-only witness. It grants no frames, writes,
commands, or identity replacement authority. `gen1_client_entry` installs it only
for ordinary-frame launchers. Native runtime accepts an explicit `identity_check`
callback from that owner; without the callback its original strict name check
remains. Both paths continue to read the ROM hash and player ID freshly.

The original cartridge temporarily copies `wPlayerName` to
`wLinkEnemyTrainerName` (also `wGrassRate`) in `DisplayBattleMenu`, replaces it
with `OLD MAN` (R/B/Y) or `PROF.OAK` (Yellow), then restores the name in
`ItemUseBall.oldManBattle`. These are 11-byte copies, including bytes after the
text terminator. The guard preserves those exact original bytes and admits only
the generated literal's exact bytes during the observed tutorial interval.

`tools/gen_gen1_identity_sites.py --check` reproduces the source/ROM bindings from
pinned pret trees. Generated data contains the original call/return sites, ROM
bytes, literal bytes, CopyData instruction range, and RAM addresses. At install,
the guard checks the ROM call/return anchors, CopyData and literals. Bus hooks
check the executing bank, PC and bytes; copy starts check HL, DE and BC. A borrow
requires the immediately observed original-name backup and a completed copy.
Oak additionally requires Pallet Town, no party yet, and the original
`SCRIPT_PALLETTOWN_AFTER_PIKACHU_BATTLE` state. The backup must stay unchanged.

Every partial name must be a copied prefix of the destination followed by the
uncopied original suffix. That check additionally requires the exact CopyData
call stack, call/return PC, or VBlank interrupt entry whose saved PC and return
stack point into that invocation. No broad battle-type exception is used.
Context changes, save-state loads, Lua exit, altered backups and unexpected
names latch refusal. Restoring the original name closes the interval.

Original external-clock trade animation uses `Trade_SwapNames`; this module does
not admit it. The production native path uses original internal-clock animation,
whose pinned function sequence does not call `Trade_SwapNames`. External-clock
identity borrowing would require separate explicit native command ownership and
source-copy qualification before enabling that path.

Evidence: `.cache/gen1-identity-guard.xml` records 96 passing focused tests across
the guard, native injection, launcher and input-only route. Guard cases include
all partial lengths, return-stack forgery, identity/context/lifecycle mutation,
source operand checks, all four tutorial/variant cases, and strict native fallback.
These are source/model checks, not live cartridge qualification. The cold Yellow
route previously reached the intact original Oak/Pikachu display and stopped on
the old strict-name assertion at frame 5219; its evidence is in
`.cache/cold-native-launcher-8mlxv_94`.

The guarded cold Yellow/Yellow reruns in `.cache/cold-native-launcher-2o91mfjp`
and `.cache/cold-native-launcher-03kuvxcx` both completed the actual tutorial and
original-name restoration for both players. The second reached real starter
acquisition, paired server settlement and the original rival battle. It stopped
at player b frame 13942 on an unanswered ordinary grant response deadline; it did
not reach receptionist/trade and is a failed whole-route gate. Client source
closure and the original blank SaveRAM files remained unchanged.

The conspicuous cyan/purple lab floor was separately checked using unchanged
Yellow ROM SHA-1 `cc7d03262ebfaf2f06772c1a480c7d9d5f4a38e1`, normal New Game
inputs and `emu.frameadvance`, without the launcher or held writes. Evidence is
in `.cache/cold-lab-reference-evidence`. Oak's lab uses DOJO (Gym graphics), not
the tileset named Lab. The untouched reference has the same palette and exact
floor pixels. Only 188 of 23040 pixels differ from the production lab screenshot,
all confined to the player/rival sprite rectangle `(49,63)-(79,76)`.
