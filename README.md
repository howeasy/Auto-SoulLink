# Auto-SoulLink

Automates a **Pokémon Soul Link Nuzlocke** across two simultaneous games in [BizHawk](https://github.com/TASEmulators/BizHawk). Lua clients in each emulator read game RAM every frame, send events over TCP to a Python server, and the server enforces all Soul Link rules automatically — encounter linking, faint propagation, party/box sync, memorial box, and optional clause restrictions.

## Supported Games

| Gen | Games | ROM Variants | Status |
|-----|-------|-------------|--------|
| 3 | FireRed, LeafGreen, Emerald | Vanilla, randomized, Archipelago, Radical Red 4.1 (CFRU) | **✅ Stable** |
| 1 | Red, Blue, Yellow | US English | ⚠️ Experimental |
| 2 | Crystal | GBC | ⚠️ Experimental |
| 4 | HeartGold, SoulSilver, Platinum | US | ⚠️ Experimental |
| 5 | Black, White, Black 2, White 2 | — | ⚠️ Experimental |

> **Note:** Only Gen 3 has been extensively tested in live gameplay. Gen 1, 2, 4, and 5 have unit tests and Lua clients but limited real-world testing.

## Quick Start

```bash
# 1. Install Python deps
pip install -r requirements.txt

# 2. Start the Run Manager
python -m server.manager --host 0.0.0.0

# 3. Open the dashboard
#    http://localhost:8090/
```

From the dashboard:

1. **Create a run** — pick a name and enable any clause rules (species, gender, type)
2. **Start the run** — the manager launches a server instance automatically
3. **Download launcher scripts** — click the Player A / Player B download buttons
4. **Load in BizHawk** — open each downloaded `.lua` file in a BizHawk Lua Console (one per emulator instance). The script auto-detects the game and connects to the server — no editing required.

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
| `/stream/*` | OBS overlays — party, links, linked-party, boxed-links, deaths, attempts, areas, events, badges |
| `/calc/` | Radical Red damage calculator with live party bridge |

## Twitch Bot

The built-in Twitch chat bot lets viewers query Soul Link run state with commands like `!rip`, `!runstats`, and `!partner`.

> **Requires twitchio 3.x** — the old IRC-based integration is discontinued by Twitch. This uses EventSub WebSocket.

### Bot Account Options

You have two setups to choose from:

| | **Option A — Broadcaster account** | **Option B — Separate bot account** |
|-|---|---|
| Accounts needed | 1 (your existing account) | 2 (yours + a new bot account, e.g. "MySLinkBot") |
| Messages appear as | Your channel name | The bot account name |
| Difficulty | Simpler | Recommended for stream |

Both options use the **exact same code and token setup** — the only difference is which Twitch account you authorize in step 2.

### Setup

1. **Register a Twitch Developer app** (on your own account) at [dev.twitch.tv/console](https://dev.twitch.tv/console) → Register Your Application.
   - Name: anything (e.g. "MySLink Bot"), Category: Chat Bot, Client Type: Confidential
   - **OAuth Redirect URL: `https://twitchtokengenerator.com/`** ← required so twitchtokengenerator can complete the auth flow
   - Copy the **Client ID**. Click **New Secret** and copy the **Client Secret**.

2. **Get tokens for the BOT account** at [twitchtokengenerator.com](https://twitchtokengenerator.com):
   - **Option A:** stay logged into your normal Twitch account.
   - **Option B:** open an incognito window and log in as the bot account first, then go to twitchtokengenerator.
   - Select **Custom Scope Token**, paste your **Client ID** (same for both options)
   - Enable scopes: `user:read:chat` `user:write:chat` `user:bot` `channel:bot`
   - Click Generate Token and authorize **as the bot account**, copy the **Access Token** and **Refresh Token**.

3. **Set environment variables** before starting the server or manager:

   ```cmd
   :: Windows cmd.exe — no spaces around =, no quotes
   set TWITCH_ACCESS_TOKEN=bot_access_token        ← from twitchtokengenerator (bot account)
   set TWITCH_REFRESH_TOKEN=bot_refresh_token      ← from twitchtokengenerator (bot account)
   set TWITCH_CLIENT_SECRET=your_client_secret     ← from dev.twitch.tv/console → your app → New Secret
   python -m server.manager
   ```

   ```powershell
   # PowerShell
   $env:TWITCH_ACCESS_TOKEN = "bot_access_token"   # from twitchtokengenerator (bot account)
   $env:TWITCH_REFRESH_TOKEN = "bot_refresh_token" # from twitchtokengenerator (bot account)
   $env:TWITCH_CLIENT_SECRET = "your_client_secret" # from dev.twitch.tv/console → your app → New Secret
   python -m server.manager
   ```

4. **Configure via the Twitch Bot page** (`/twitch`):
   - **Channel**: your broadcaster channel name (where viewers type commands)
   - **Client ID**: from dev.twitch.tv/console (same app as step 1)
   - Click **Save Config** and **Reconnect**. The status panel shows connection state and any errors.

### Commands

| Command | Description |
|---------|-------------|
| `!soullink` | Plain-English Soul Link rules |
| `!clauses` | Active clause rules (species/gender/type) |
| `!rip` | Most recent death with killer detail |
| `!runstats` | Attempt #, alive/dead counts, oldest pair |
| `!alltime` | Cross-run aggregate: attempts, deaths, shinies |
| `!lastrun` | How the previous run ended |
| `!attempts` | Current attempt number |
| `!partner <name>` | Look up a mon's Soul Link partner by nickname |
| `!area <name>` | Look up an area's link status |

---

## Run Manager

Orchestrate multiple runs from a single dashboard:

```bash
python -m server.manager --host 0.0.0.0
# Dashboard at http://localhost:8090/
```

## Tests

```bash
pytest tests/unit/ -v        # 647 tests, no emulator needed
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
  adapters/              # Game-specific adapters (gen1–5)
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
