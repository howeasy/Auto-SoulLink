# Gen 4 research record (2026-09-26)

These notes come from the Gen 4 planning session (coordinator: Claude, worktree `gen4-support-framework-dfd5e2`).
The plan built on them is [`../PLAN.md`](../PLAN.md).

Every table row carries its evidence class:
- **SOURCE**: a file:line in a pinned pret or hg-engine checkout, or an xMAP.
- **FILE**: measured offline on a real ROM or battery save.
- **REPORTED**: taken from an independent reviewer's reply and not re-checked by the coordinator.

The coordinator re-checked the load-bearing citations in each card. The spot checks are listed per file.

## How the research was done

| Card | Worker | Scope | Outcome |
|---|---|---|---|
| Explore: legacy Gen 4 audit | Claude Explore | old `gen4_hgsspt` client, `memory_nds.lua`, adapter | [prior_art.md](prior_art.md) §1 |
| Explore: shared framework seams | Claude Explore | `lua/core`, Layer A modules, Gen 3 binding, adapter contract | [../PLAN.md](../PLAN.md) architecture |
| Explore: Gen 3 plan + test infra | Claude Explore | gates, ledger families, fixtures, runners | [../PLAN.md](../PLAN.md) gates |
| Explore: owner's AP HGSS injection | Claude Explore | `E:/Howard/hgss_archipelago-{vanilla,hgengine,master}` | [prior_art.md](prior_art.md) §3 |
| G4-R1 `cx-9e50c1ce` | OMP headless | PK4 record, party, PC, flash save, profile | [pk4_and_save.md](pk4_and_save.md) (27 accepted / 0 rejected) |
| G4-R2 `cx-1fa4562d` | OMP headless | engine sites per Soul Link event | [engine_sites.md](engine_sites.md) (18 / 0) |
| G4-R3 `cx-a2bd6e6a` | OMP headless | hg-engine delta vs vanilla | [hg_engine.md](hg_engine.md) (20 / 0) |
| G4-R4 `cx-0d075ef7` | OMP headless | acquisition paths, data sources | [acquisition.md](acquisition.md) (30 / 0) |
| G4-R5 `cx-e3501ded` | OMP headless | which vanilla sites survive in hg-engine | [hg_engine.md](hg_engine.md) §4 (26 / 0) |
| G4-R6 `cx-8f1d0eff` | OMP headless | checkpoint / battle copy-back | [checkpoint.md](checkpoint.md) (13 / 0) |
| G4-R7 `cx-2fe25ca0` | OMP headless | battle struct offsets, idle clauses, save driver | [engine_sites.md](engine_sites.md), [checkpoint.md](checkpoint.md) (corrections) |
| G4-R9 `cx-d11ad936` | OMP headless | hge battle layout vs vanilla | [hg_engine.md](hg_engine.md) §4b |
| G4-R8 `cx-5e4819dc` | OMP headless | Platinum bind falsifiers | [platinum_bind.md](platinum_bind.md) |
| Plan agents (2) | Claude Plan | architecture; phasing/gates | [../PLAN.md](../PLAN.md) |

## Pinned inputs

| Input | Pin |
|---|---|
| HeartGold (USA) | sha1 `4fcded0e2713dc03929845de631d0932ea2b5a37`, header `IPKE`, equal to pokeheartgold `heartgold.us/rom.sha1` |
| SoulSilver (USA) | sha1 `f8dc38ea20c17541a43b58c5e6d18c1732c7e582`, header `IPGE`, equal to pokeheartgold `soulsilver.us/rom.sha1` |
| Platinum (USA) | sha1 `ce81046eda7d232513069519cb2085349896dec7`, header `CPUE` |
| hg-engine fork build (recorded, not admitted) | `E:/Howard/HGEngine_ROMHack/hg-engine` commit `fc5175764`, `build_output/test.nds` sha1 `cb2dc435196d09c8c9209bf037240ed834f4cea1` |
| pret/pokeheartgold `xmap` branch | commit `40eab3c65e0e4f46f6edd90540709aa9950ca07e` (built from master `9d8b7591f09b65804da2fb2dfd56f320633e0d36`) |
| `heartgoldus.xMAP` | sha256 `39397e4c16f4fe907870ab8dac450a469a8ce9ce225eb98852771ff59fe877df` (11646615 B) |
| `soulsilverus.xMAP` | sha256 `4ce745d56b34762300025279748b3ea3626bc2e87c0540e0a649388b758d07b2` (11646721 B) |
| pret/pokeplatinum `xmap` branch | commit `a2a62d3d8966ffe5953a5ffca1cd4f8a45e79e61`; `platinumus.xMAP` sha256 `c3b3451b4815a646514bf9d456062e644d83010f996eaff17abf8d2fe667e72a` (12107496 B) |
| pokeplatinum source clone (shallow, `.cache/gen4/pokeplatinum`) | `c248fb3f8cc9934ded800e489567c5c0eeee92eb` |
| hg-engine build symbol exports (`.cache/gen4/hge/`) | `offsets.ini`, `build/rom_gen.ld` and `arm-none-eabi-nm` of 21 `build/*linked.o`, pulled read-only from `hgbox:~/git/hg-engine`, whose `test.nds` sha1 == `cb2dc435…` (the pinned build) |
| pokeheartgold source clone used for citations | `E:/Howard/hgss_archipelago-master/.tooling/pokeheartgold` @ `ad7a3afa` (older than the xmap build; line numbers refer to this clone) |

Local copies of the two HGSS xMAPs are in `.cache/gen4/xmap/` (gitignored).

## Files

- [sources_and_symbols.md](sources_and_symbols.md): xMAP symbol source, HG vs SS, key addresses, overlay sharing
- [pk4_and_save.md](pk4_and_save.md): record crypto, party/PC, flash save format, profile fields
- [engine_sites.md](engine_sites.md): where each Soul Link event happens in the engine
- [acquisition.md](acquisition.md): gifts, statics, roamers, trades, contest/safari/Pal Park, data sources
- [hg_engine.md](hg_engine.md): hg-engine record/save/battle deltas and site survival
- [checkpoint.md](checkpoint.md): write checkpoint facts (battle copy-back, overworld idle, CPU park)
- [platform.md](platform.md): BizHawk/melonDS configuration facts and live probe results
- [platinum_bind.md](platinum_bind.md): D3 bind check at SOURCE level (what the profile schema must express)
- [wire_contract.md](wire_contract.md): the message contract a Gen 4 client on `lua/core/session.lua` must meet
- [prior_art.md](prior_art.md): legacy Gen 4 code audit, archived melonDS probe (and its error), the owner's AP HGSS injection
