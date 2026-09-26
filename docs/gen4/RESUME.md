# Gen 4 resume note

## Checkpoint 2 (2026-09-26): research complete, plan rev 4, awaiting G0

- **Worktree:** `.claude/worktrees/gen4-support-framework-dfd5e2`
- **Branch:** `claude/gen4-support-framework-dfd5e2`, based on master `1d02702f`, not pushed.
- **Coordinator:** Claude (Opus 5.5).
- **Plan:** [PLAN.md](PLAN.md) **rev 4**. Owner decisions **D1-D15**, all taken 2026-09-26. Two adversarial reviews are folded in: OMP `cx-b646f457` on rev 2, OMP `cx-03ea7236` on rev 3.
- **Research:** [research/](research/README.md) holds SOURCE, FILE and live PHYSICAL research (the research probe, not gate evidence), plus data JSON.
- **Nothing is running.** No emulator lane is held and no production code has been written.

### Next action

Get the owner's **G0 signature** (an explicit yes). Then dispatch wave 1 (PLAN.md §7):

| Card | Model |
|---|---|
| C1-2 pack generator | Sonnet |
| C1-3 codec | Sonnet |
| C1-7 in-battle faint research | Opus |

C1-7 → C1-8 → probe row o is RC-blocking under D12.

### Owner inputs outstanding

- **SoulSilver** first save (D4)
- **Platinum** first save (D3)
- **Two hg-engine** first saves with a populated party and distinct trainer IDs (D15)
- **G0 signature**
- Later: push/merge authority at landing

### Local inputs (gitignored or outside the repo)

| Input | Location |
|---|---|
| HG ROM | `E:/Howard/Bizhawk/Pokemon - HeartGold Version (USA).nds` |
| SS ROM, Pt ROM | root of the main checkout |
| hge build | `E:/Howard/HGEngine_ROMHack/hg-engine/build_output/test.nds` (sha1 `cb2dc435…`); its symbols in `.cache/gen4/hge/` (pulled read-only from `hgbox`) |
| HG save | `E:/Howard/Bizhawk/NDS/SaveRAM/Pokemon - HeartGold Version (USA).SaveRAM` (copies only) |
| xMAPs | `.cache/gen4/xmap/` (HG, SS, Pt) |
| pokeplatinum clone | `.cache/gen4/pokeplatinum` |
| offline scripts | `.cache/gen4/offline/` |
| research probe lane | `C:/slink/g4/probe/` (scripts, logs, ROM/save copies) |
| pokeheartgold source | `E:/Howard/hgss_archipelago-master/.tooling/pokeheartgold` @ad7a3afa |

**Tooling:** `ndspy` and `bsdiff4` are installed. There is no local ARM toolchain; hge builds run through the `hgbox` ssh alias (key-based).

## History

- **Checkpoint 1 (2026-09-26):** planning complete; plan rev 2, D1-D5.
- **Research wave (2026-09-26):**
  - OMP R1-R9
  - Explore: legacy audit, framework seams, Gen 3 process, AP prior art, wire contract
  - Sonnet offline measurements
  - Opus live melonDS probe
  - Plan revs 3-4 with D6-D15
