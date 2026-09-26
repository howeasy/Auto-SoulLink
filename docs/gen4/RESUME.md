# Gen 4 resume note

## Checkpoint 1 (2026-09-26): planning complete, awaiting G0

- **Worktree:** `.claude/worktrees/gen4-support-framework-dfd5e2`
- **Branch:** `claude/gen4-support-framework-dfd5e2`, based on master `1d02702f`, not pushed.
- **Coordinator:** Claude (Opus 5.5).
- **Plan:** [PLAN.md](PLAN.md) rev 2. The owner took decisions D1-D5 in the planning session. The plan was reviewed adversarially by OMP `cx-b646f457`; all 19 findings are folded in.
- **Research:** [research/](research/README.md). Seven files, each citing pret / hg-engine / xMAP / a real save.
- **Nothing is running.** No emulator lane is held and no code has been written.

### Next action

Ask the owner to sign G0: the pins and §0 rulings in PLAN.md §2 and §5. After that, dispatch wave 1 (PLAN.md §7):

| Card | Model |
|---|---|
| C1-1 probes | Opus |
| C1-2 pack generator | Sonnet |
| C1-3 codec | Sonnet |

C0-1 (ledger, Sonnet), C0-2 (pins, Haiku) and C1-4 (fixture infra, Haiku) take the next slots.

### Owner inputs outstanding

- A **SoulSilver** first save after getting the starter (D4). It unblocks the SS cells of G1 and G2.
- A **Platinum** first save (D3). The local `AutoSaveRAM` is blank, and the save unblocks the Pt codec bind cell.
- **G0 signature.**

### Local inputs (gitignored or outside the repo)

| Input | Location |
|---|---|
| HG ROM | `E:/Howard/Bizhawk/Pokemon - HeartGold Version (USA).nds` (also `E:/Howard/HGEngine_ROMHack/`) |
| SS ROM, Pt ROM | repo root of the main checkout |
| HG battery save | `E:/Howard/Bizhawk/NDS/SaveRAM/Pokemon - HeartGold Version (USA).SaveRAM`. Early game, party = Cyndaquil L5. **Work on copies only.** |
| hge saves | `E:/Howard/Bizhawk/NDS/SaveRAM/patched hge ap.SaveRAM` has footers; `baseline hge noap.AutoSaveRAM.SaveRAM` is empty |
| xMAPs | `.cache/gen4/xmap/{heartgold,soulsilver}us.xMAP` (sha256 in research/README.md). Re-fetch from `raw.githubusercontent.com/pret/pokeheartgold/40eab3c6…/` |
| pokeheartgold source | `E:/Howard/hgss_archipelago-master/.tooling/pokeheartgold` @ad7a3afa |
| hg-engine fork | `E:/Howard/HGEngine_ROMHack/hg-engine` @fc5175764 (build: `./build-remote.sh` via ssh alias `hgbox`) |

**Tooling:** `ndspy` and `bsdiff4` are installed. There is no local ARM toolchain, Docker or WSL.

## History

- 2026-09-26: planning session. Research cards R1-R6, AP prior-art study, legacy audit, two Plan agents, adversarial review.
