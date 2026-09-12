# Independent native trade-result checks

server/gen1_trade_result.py derives legal recipient results from the exact
supplied ROM's evolution methods, learnsets and default names, together with
the canonical party codec's immutable type, base-stat, growth and PP facts.
Its expected SHA-1 binds the parser to that artifact; it does not admit the
artifact or replace the complete UPR semantic/provenance gate.

The policy verifies removal of the selected outgoing slot, preservation/order
of retained members, append of the incoming member, recipient evolution,
recomputed stats, preserved HP damage, default-name changes and native move
learning. Equal cross-player raw keys remain permitted when the recipient's
retained party and boxes are collision-free.

## Evolution can learn a move

The pinned evolution routine calls LearnMoveFromLevelUp after CalcStats and
before SetPartyMonTypes and final dex updates. A matching current-level move
is learned automatically into an empty slot. With four moves, the player can
decline or select a non-HM move to replace. The learned move receives its base
PP and no PP Ups; other PP bytes remain unchanged. An already-known move
keeps its remaining PP and does not open the learning routine.

Actual R/B/Y tests now cover a level29 Haunter becoming Gengar and learning
Hypnosis, all four replacement slots, declining, a known move with depleted
PP, an attempted HM replacement followed by a legal selection, and learning
levels for the other three canonical trade evolutions. The original cartridge
routines perform every choice and mutation; no move is injected as the result.
There are eleven such cases per title.

The model follows the incoming species' original evolution-entry sequence:
a non-trade entry or unmet trade level ends that mon's pass. This also permits
reading method changes from a caller-supplied artifact without claiming that
the artifact is an approved randomization. Broader UPR qualification remains
required before production use.

The pure arithmetic lives in server/stat_experience.py, separate from any
cartridge memory layout. Its RBY use is cross-checked against the independent
existing formula and actual cartridge evolution results.

## Save readback

The live gate supplies the complete before/after canonical save region,
the complete live party storage, previous owned/seen bytes, live save player
ID/name, and Yellow's previous happiness/mood. Geometry comes from the
packaged canonical symbols.

The independent checker requires:

- Valid before/after region lengths and canonical checksums.
- All404 live party-storage bytes equal the saved party section.
- Count/species terminator and every occupied saved44+11+11 record agree with
  the verified post-trade party.
- Exactly the expected incoming/evolved species' owned/seen bits are added;
  every other bit, including padding, is preserved.
- Save player ID/name agree with the admitted identity inputs, independently
  of either Pokémon's original trainer.
- Yellow's canonical starter detection and trade happiness/mood effects.
  Starter detection uses species, save player ID and exactly the first five
  raw OT-name bytes; it does not use the DVs or compare only visible text.
- All main/sprite/current-box data outside the canonical party/dex/Pikachu/
  checksum write ranges remain unchanged.

These are CartRAM readback checks. They do not prove a host SaveRAM-file flush,
process-kill recovery, native execution, or an atomic paired transaction.
SavePartyAndDexData is a partial save routine; the coordinator still needs a
qualified full-save/initialization policy matching the vanilla pre-trade save
flow. No new SRAM layout or persistent cartridge marker was introduced.

The result policy deliberately does not return an animation/completion ACK.
Even an exact party/save poststate can be indistinguishable from a prestate
for identical data. The runtime must require operation-bound native completion
evidence and durable receipt publication before committing link ownership.

## Qualification

The read-only policy has62 portable unit cases, including corrected-checksum
save tampering, wrong identity, wrong dex changes, unrelated save writes,
Yellow happiness boundaries, malformed rule tables and local key collisions.

The complete native gate passed9 live tests in445.81 seconds with the new
independent party/save checks enabled: the existing108 successful/40 refused
matrix,33 learning cases, and three actual reset/CONTINUE cases.

Production command/receipt binding, paired coordination, complete save-file
durability and forward recovery remain open.
