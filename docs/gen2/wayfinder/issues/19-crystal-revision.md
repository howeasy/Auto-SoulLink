# Crystal 1.0 vs 1.1 admission

Type: grilling
Status: resolved
Blocked by: 11

## Question

pret builds both `pokecrystal.gbc` (1.0, sha1 f4cd194b..) and `pokecrystal11.gbc` (1.1, sha1 f2f52230..); the local dump is one of them (unhashed yet). Admit both revisions with separate site tables, or one? The AP fork accepts both base hashes (archipelago_crystal.md). Owner decision after ticket 11 reports which revision the local dump is.

## Answer

RULED by the owner 2026-09-21 (O-12): use whatever revision the local dump is; P1 hashes it against `roms.sha1` and the other revision becomes a recorded limit.
