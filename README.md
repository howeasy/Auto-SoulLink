# Auto-SoulLink

Automates a **Pokémon Soul Link Nuzlocke** across two simultaneous games in [BizHawk](https://github.com/TASEmulators/BizHawk). Lua clients in each emulator read game RAM every frame, send events over TCP to a Python server, and the server enforces all Soul Link rules automatically — encounter linking, faint propagation, party/box sync, memorial box, and optional clause restrictions.

## Supported Games

| Gen | Games | ROM Variants | Status |
|-----|-------|-------------|--------|
| 3 | FireRed, LeafGreen, Emerald | Vanilla, randomized, Archipelago, Radical Red 4.1 (CFRU) | **✅ Stable** |
| 1 | Red, Blue, Yellow | US English | ⚠️ Experimental |
| 2 | Crystal | GBC | ⚠️ Experimental |
| 4 | HeartGold, SoulSilver, Platinum | Vanilla, Renegade Platinum | ⚠️ Experimental |
| 5 | Black, White, Black 2, White 2 | US | ⚠️ Experimental |

> **Note:** Only Gen 3 has been extensively tested in live gameplay. Gens 1, 2, 4, and 5 have full feature parity with Gen 3 (moves/PP, stat stages, doubles, forms, egg detection, stream overlays) and pass their unit-test suites, but live-play coverage is limited — treat them as experimental. Gen 4 doubles + stat-stage battle-struct addresses are read-only-scannable via `lua/tests/test_gen4_battlers_count.lua` + `test_gen4_stat_stages.lua` and need a one-time live capture to populate the profile. Gen 5 has the same shape via `lua/tests/test_gen5_block_b.lua` and `lua/tests/test_gen5_doubles.lua`. Gen 1/2 runtime checks live in `docs/gen1_gen2_runtime_checks.md`.

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
| `/` | Live status — parties, encounters, linked pairs, area states, enemy battle info |
| `/memorial` | Tombstone cards for dead pairs, live-updating via SSE |
| `/obs` | OBS scene trigger configuration — per-player WebSocket connections, draggable priority rules |
| `/twitch` | Twitch bot configuration and activity log |
| `/debug` | Manual linking, event injection, state toggles, backup rollback |
| `/stream/` | Stream overlay index — preview and configure all overlays |
| `/stream/party-a`, `/stream/party-b` | Party cards with HP bars, moves, held item, status ailments, stat stage icons |
| `/stream/links` | Linked pairs with both mons side-by-side |
| `/stream/linked-party` | Party filtered to only linked mons |
| `/stream/deaths` | Death feed with sprites and cause |
| `/stream/encounters` | Encounter log per area |
| `/stream/enc-table-a`, `/stream/enc-table-b` | Wild encounter rate table for current area (RR/CFRU) |
| `/stream/areas` | Area link state grid |
| `/stream/focus-a`, `/stream/focus-b` | Active battle mon — large sprite, moves, type matchups |
| `/stream/enemy-focus-a`, `/stream/enemy-focus-b` | Active enemy mon(s) — large sprite, moves, live PP. Singles or doubles. |
| `/stream/enemy-trainer-a`, `/stream/enemy-trainer-b` | Trainer's full team — PARTY-style autoscroll. |
| `/stream/ticker` | Scrolling event ticker |
| `/stream/badges` | Badge display |
| `/stream/stream-memorial` | Memorial wall for stream |
| `/calc/` | Radical Red damage calculator with live party bridge |

## OBS Scene Triggers

Automatically switch OBS scenes based on game events. Configure from the `/obs` page.

### Setup

1. In OBS, enable **Tools → WebSocket Server Settings** (obs-websocket v5, OBS 28+). Set a port (default 4455) and optional password.
2. Open `/obs` on the status page, enter the host/port/password for each player's OBS instance, and click **Connect**.
3. Add trigger rules: choose an event, which player triggers it, which OBS to target, and the scene to switch to.

### Trigger Events

| Event | When it fires |
|-------|--------------|
| `battle_start` | Any battle begins |
| `wild_battle_start` | Wild encounter starts |
| `trainer_battle_start` | Trainer battle starts |
| `battle_start_new` | Battle in an area with an open encounter slot |
| `battle_end` | Battle ends (returned to overworld) |
| `area_enter` | Player enters any area |
| `area_enter_new` | Player enters an area with an open encounter slot |
| `capture` | A Pokémon is caught |
| `shiny` | A shiny is caught |
| `faint` | Own mon faints |
| `link_death` | Partner's linked mon faints |
| `whiteout` | Full party wipe |
| `linked` | Area becomes fully linked |
| `dead_zone` | Area becomes a dead zone |
| `party_to_box` | Mon moved to PC |
| `box_to_party` | Mon retrieved from PC |
| `memorialize_done` | Dead pair memorialized |
| `run_over` | No usable pairs remain |

### Priority

Rules are evaluated **top to bottom** — when multiple events fire in the same frame, the highest-ranked rule wins per player. Drag the ⠿ handle to reorder. Changes save automatically.

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
pytest tests/unit/ -v        # 1056 tests, no emulator needed
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
  obs_controller.py      # OBS WebSocket scene trigger integration
  twitch_bot.py          # Twitch chat bot (twitchio 3.x)
  pokemon_data.py        # Species, abilities, types, evos
data/
  games/                 # Per-game static data (area maps, items)
  obs_config.json        # OBS connection + trigger rule config
calc/                    # Radical Red damage calculator + live bridge
tests/                   # pytest unit tests (1056) + BizHawk test scripts
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
