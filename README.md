# Auto-SoulLink

Automates a **Pokémon Soul Link Nuzlocke** across two simultaneous games in [BizHawk](https://github.com/TASEmulators/BizHawk). Lua clients in each emulator read game RAM every frame, send events over TCP to a Python server, and the server enforces all Soul Link rules automatically — encounter linking, faint propagation, party/box sync, memorial box, and optional clause restrictions.

## Supported Games

| Gen | Games | ROM Variants |
|-----|-------|-------------|
| 1 | Red, Blue, Yellow | US English |
| 2 | Crystal | GBC |
| 3 | FireRed, LeafGreen, Emerald | Vanilla, randomized, Archipelago, Radical Red 4.1 (CFRU) |
| 4 | HeartGold, SoulSilver, Platinum | US |

## Quick Start

```bash
# 1. Install Python deps
pip install -r requirements.txt

# 2. Start the server
python -m server.server

# 3. Open the status page
#    http://localhost:8080/
```

Then load `lua/slink.lua` (auto-detects game) in each BizHawk Lua Console. Edit the launcher script header to set `SLINK_HOST`, `SLINK_PORT`, and `SLINK_PLAYER` (`"a"` or `"b"`).

> Load the script **after** loading your save file. Writes are disabled until SaveBlock validation passes.

## How It Works

```
BizHawk A ─── Lua client ──┐
                            ├── TCP :54321 ──→ Python server ──→ HTTP :8080
BizHawk B ─── Lua client ──┘
```

- **Lua clients** diff RAM each frame and send JSON events only on changes (capture, faint, area change, party move)
- **Server** returns commands in the TCP response (`force_faint`, `box_mon`, `party_mon`, `memorialize`)
- **Status page** updates live via SSE — no refresh needed
- **State** persists to `data/links.json` after every mutation

## Soul Link Rules

| Rule | What happens |
|------|-------------|
| **Encounter linking** | First catch per area by each player → permanently paired |
| **Dead zone** | Either player fails to catch → area locked for both |
| **Faint propagation** | One mon faints → partner is force-fainted instantly |
| **Party sync** | Linked mons must both be in party or both in box |
| **Memorial box** | Dead pairs move to Box 14 automatically |
| **Whiteout** | All party faints → all partner's linked mons faint |
| **Nuzlocke gate** | Rules inactive until player obtains Pokéballs |

### Optional Clauses

| Flag | Effect |
|------|--------|
| `--species-clause` | Rejects same evo family links |
| `--gender-clause` | Rejects same gender links (genderless exempt) |
| `--type-clause` | Rejects links sharing any type |

Shiny bonus pairs are always on — catching a shiny gives the partner an extra Soul Link slot.

## Web Pages

| Path | Description |
|------|-------------|
| `/` | Live status — parties, encounters, linked pairs, badges |
| `/memorial` | Tombstone cards for dead pairs |
| `/debug` | Manual linking, event injection, backup rollback |
| `/stream/*` | OBS overlays (party, links, deaths, areas) |
| `/calc/` | Radical Red damage calculator with live party bridge |

## Run Manager

Orchestrate multiple runs from a single dashboard:

```bash
python -m server.manager --host 0.0.0.0
# Dashboard at http://localhost:8090/
```

## Tests

```bash
pytest tests/unit/ -v        # ~527 tests, no emulator needed
```

## Project Structure

```
lua/
  slink.lua              # Universal entry point (auto-detects game)
  clients/               # Per-game Lua clients
  games/                 # Per-game config (addresses, detection)
  memory_*.lua           # Platform memory helpers (GB, GBA, NDS)
  connector.lua          # Non-blocking TCP wrapper
server/
  server.py              # TCP + HTTP server (aiohttp)
  state.py               # SoulLinkState FSM
  adapters/              # Game-specific adapters (gen1–4)
  pokemon_data.py        # Species, abilities, types, evos
data/
  games/                 # Per-game static data (area maps, items)
calc/                    # Radical Red damage calculator fork
tests/                   # pytest unit tests + BizHawk test scripts
tools/                   # Code generators (area maps, data tables)
```

## Documentation

Full technical reference (memory maps, protocol details, adapter architecture): **[docs/REFERENCE.md](docs/REFERENCE.md)**

## References

- [pret/pokefirered](https://github.com/pret/pokefirered) — FRLG decompilation
- [pret/pokered](https://github.com/pret/pokered) / [pokeyellow](https://github.com/pret/pokeyellow) — Gen 1 decomps
- [pret/pokecrystal](https://github.com/pret/pokecrystal) — Crystal decomp
- [Skeli789/Complete-Fire-Red-Upgrade](https://github.com/Skeli789/Complete-Fire-Red-Upgrade) — CFRU engine
- [BizHawk Lua Functions](https://tasvideos.org/BizHawk/LuaFunctions)
- [funnotbun RR Pokédex](https://funnotbun.github.io/) — Radical Red data
