# Shared actual-byte admission

`lua/admission.lua` implements PLAN 5.15d: byte acquisition, SHA-1, bounded anchor
comparison, candidate evaluation, unique-match enforcement and a detached,
immutable decision. It knows no game, header title, bank layout, pack path,
admitted revision or artifact-kind relationship. Those facts are binder inputs.

## Interface

`Admission.new(policy):admit(request)` returns a decision or `nil, reason`.
Every callback below is required; an omitted callback fails construction.

| Policy callback | Required result |
| --- | --- |
| `acquire(request)` | `{bytes=string}` or `{size=positive_integer, read_u8=function(offset)}` over the actual artifact. A provided size must agree with a provided byte string. |
| `catalog(request, artifact)` | Plain dense array of binder-owned candidates. |
| `hashes(candidate)` | Plain dense array of valid SHA-1 strings; comparison is case-insensitive. |
| `eligible(candidate, mode, request, artifact)` | Explicit `true`, or refusal plus optional reason. Owns admission/gate/title/revision policy. |
| `anchors(candidate, mode, request, artifact)` | Plain dense array of `{offset, hex}` spans required by that candidate. |
| `kind(candidate, mode, request, artifact)` | Approved nonempty kind string, or refusal plus optional reason. |
| `describe(candidate, kind, mode, request, artifact)` | Acyclic plain decision fields, detached by the core before proof fields are added. |

`allow_unknown_hash` defaults to **false**. Only the exact boolean `true` enables
anchor fallback. Modes are `sha1` and `anchors`; mode and kind derivation are not
inferred from title names or missing fields. A known catalog hash rejected by
policy never escapes through unknown-hash fallback.

The `artifact` view contains immutable `bytes`, `size`, `sha1`, and
`read_u8(offset)`. Callbacks must be read-only and inspect this snapshot, not an
earlier reported hash or a live reader. The binder owns acquisition bounds and
the source of the actual bytes. Every acquired byte must be an integer 0..255.

Admission always hashes actual bytes. No database or reported hash grants a
fast path. After exactly one eligible candidate survives its required anchors,
the core obtains descriptive fields, reacquires the artifact and requires exact
byte equality with the first snapshot. Changed/unavailable bytes, malformed
anchors, a missing kind, no eligible candidate or multiple eligible candidates
refuse. An acceptance is a decision about those acquisitions, not a perpetual
guarantee that the host will never replace the artifact later.

The core reserves `rom_sha1`, `rehashed=true`, `admitted_by` and `kind`. A
description cannot override those proof fields or mutate the binder's catalog.
The returned decision and its nested data reject ordinary Lua assignment and
have no aliases to mutable source tables. Read fields normally, iterate with
`pairs`, and use `#` for arrays. This read-only interface is not a Lua sandbox;
privileged raw/debug primitives are outside its contract.

`Admission.sha1(read_u8, size)` exposes the extracted, game-neutral FIPS 180-4
implementation. `Admission.anchors_match(anchors, artifact, mode)` exposes the
same bounded span validator for diagnostics: it returns true/false for matching
bytes and raises on malformed inputs. `mode` is required. Anchor fallback needs
at least one nonempty span; exact hash mode may explicitly require no additional
spans. Diagnostic anchor comparison alone is not an admission decision.

## Binder responsibilities

Gen 1 owns its profile/admission catalogs, header interpretation, named-family
and randomized/overlay policies, required engine/checkpoint spans and kind
mapping. Its Entry module binds this factory in the same extraction cut. The
shared default does not inherit Gen 1's randomized admission. Requiring actual
acquisition even when a reported hash is known, rejecting duplicate eligible
candidates, and returning immutable decisions are deliberate refusal/contract
changes. Valid cartridge classification remains binder-owned.

Gen 2's `lua/gen2/entry.lua` names all 15 current generated artifacts for each
selected title as literal `PACK_FILES` paths. It preserves the shared flat area
map format and validates each map row's source/identity and ROM header anchor.
It consumes no legacy Crystal item-name, species-type or gender-ratio JSON.

Crystal 1.0, Gold and Silver are `SELECTED`/`BUILT` with their G1 gate now
`ADMITTED` (owner ruling O-22; `data/games/gen2_crystal/admission.json:9-13`,
`data/games/gen2_gold/admission.json:9-13`). `Entry.admit` (`lua/gen2/entry.lua:220-268`)
accepts a candidate only when the gate reads `ADMITTED` **and** its shipped
PHYSICAL receipts re-validate now (`proofs()`, `:199`); the gate is the grant,
never the proof. `Entry.build` (`:458-465`) therefore *can* return a production
runtime (`production_admitted=true`, `qualification="PHYSICAL_RECEIPTED"`,
`:424-429`) for those three titles. Crystal 1.1 remains `BUILD_ONLY` and stays
refused.

`Entry.build_candidate` is a separate explicit source/model composition method.
It requires `candidate_only=true`, selected title/root, explicit ROM/read/write
IO and the write binder's full ownership policy. It verifies the selected ROM
hash and source anchors, constructs only the existing reads, writes and
ROM-reader modules, then rechecks ROM size/hash before exposing the graph.
It returns `production_admitted=false`,
`runtime_started=false`, no client and an unarmed writer. It does not register
hooks, open a transport, run an emulator or qualify any ownership window.

## Verification and integration

Neutral tests cover standard hash vectors, actual-byte recomputation, explicit
unknown-hash opt-in, malformed/empty/wrong anchors, ambiguous candidates,
ineligible known hashes, changed acquisition bytes, deep immutable results and
description/catalog isolation. Gen 2 tests use actual P1 ROMs and current packs
to prove source-candidate composition and production refusal. These are
SOURCE/MODEL checks; they do not grant PHYSICAL or runtime admission evidence.

Gen 1's sole composition owner rebinds Entry and closes the player-bundle
manifest in this same cut; integration requires its existing admission, Entry
and launcher-closure checks plus independent review. The affected physical
rebind lanes remain `live-new-gates`, `duo-pairs`, `inspect-purergb` and
`duo-pairs-purergb`. Sharing the module transfers none of their evidence to Gen 2.
Rollback restores the Gen 1 Entry binding and shared-module bundle entry
together, with no launcher referring to an omitted module.
