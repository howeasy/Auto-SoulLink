# Canonical companion candidates and held admission

`tools/build_gen1_companion.py` builds exact canonical R/B panel+native trade and
Yellow trade-only candidates. SFX is false, as permitted by the locked scope when
its safe main-thread gate is not proven. Whole ROMs and generated UPS files remain
under the ignored local build directory. No UPR or external modified ROM is admitted
by this builder or the resulting catalog.

The builder reuses the existing panel/native assembly and UPS codec. A shared
checked write-set helper validates all preimages, ranges and exclusive sections
before constructing the combined bytes. Every original header byte at0100–014F
and the one-megabyte image size is preserved. R/B reserve4000–44FF of bank3F for
the existing panel/hook; the native service starts at4500. Yellow gets no panel or
permanent WRAM mailbox. Its native bank3B artifact remains trade-only.

Both generated catalogs retain base/final SHA1/SHA256, canonical source/codec
identity, explicit capabilities, the full native manifest and its hash, exact
write spans and UPS hash. The Lua catalog decodes canonical JSON so null manifest
fields and array/object kinds match Python exactly. A source/catalog check rebuilds
the artifacts and rejects any drift.

`gen1_cartridge_profiles` and `gen1_runtime_profiles` select only exact installed
clean or canonical companion identities for the durable metadata path. Legacy
admission remains clean-only. An explicitly prepared held-service launcher can
now admit these candidates and verify its27-file closure. The launcher continues
to withhold ordinary and native-recovery execution. Compiled feature presence is
not a runtime readiness grant.

The Gen1 runtime also now uses the unchanged shared RuntimeLease from36821a1 before
journal mutation, retaining it until connections/journal close. A competing server
refuses without changing the committed revision; independent read-only journal/WAL
inspection remains possible.

## Evidence and remaining RC requirements

All nine combined-cartridge pairings passed real receptionist/partner decisions,
both original animations, both exact save-file proofs and complete logical/rule
migration. Two actual generated-launcher pairs (R/B and Y/Y) admitted the exact
companions while held. Two R/B panel cases passed native START entry, fallback,
two-page staging, B return and unchanged party/SaveRAM, with no native trade call.
The panel driver waits for fresh B edges after restoration; CLOSED is published
before the restored START menu can consume input.

These are combined candidates, not completion of the locked final ABI-3 panel
specification. The existing compatibility panel layout and page behavior are still
present. The specified odd/even staging and ACK generations, three-transfer guard,
A wrap,180-frame missing-data closure and canary/recovery checks remain RC work.
The native paired tests still use explicit bootstrap/preparation/host fixtures and
controlled file transport. Ordinary/bounded native authority, production controller
selection, real timing/closure/recovery, approved UPR/provenance, browser patching
and the remaining release matrix are open. No capability flag substitutes for them.

Existing RGBDS STRSUB deprecation notices in the panel charmap generator are
recorded as cleanup; they do not change the reproduced payload bytes. Further
refactors and presentation polish remain deferred unless required for the RC.

Companion/admission cutoff:4,280 unit/integration tests passed with2 existing Windows symlink skips in98.66s; 13 combined-artifact live cases passed (9native pairs,2held launcher pairs,2panel smoke cases), followed by5 held-launcher regressions on the final entry/lease code (including the2companion pairs). Parsed240 project Lua files plus the frozen v1 reader fixture. Evidence:.cache/companion-final.xml,.cache/companion-live.xml,.cache/companion-panel2.xml,.cache/companion-held-final.xml. Shared patch-plan6369c0b is published; RuntimeLease36821a1 is reused unchanged. Both participants must expose native trade and the canonical codec; unpatched participants refuse. Final panel ABI behavior, ordinary/bounded native authority and UPR/publication remain open.
