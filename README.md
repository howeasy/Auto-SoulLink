# Auto-SoulLink

Automates a **Pokémon Soul Link Nuzlocke** across two simultaneous games in [BizHawk](https://github.com/TASEmulators/BizHawk). Lua clients in each emulator read game RAM every frame, send events over TCP to a Python server, and the server enforces all Soul Link rules automatically — encounter linking, faint propagation, party/box sync, memorial box, and optional clause restrictions.

## Supported Games

| Gen | Games | ROM Variants | Status |
|-----|-------|-------------|--------|
| 3 | FireRed, LeafGreen | Vanilla, randomized, Archipelago, Radical Red 4.1 (CFRU) | **✅ Stable** |
| 3 | Emerald | Vanilla | ⚠️ Experimental — RAM profile is complete, but the area/location name tables are not generated, so area resolution falls back to FireRed and is wrong |
| 1 | Red, Blue, Yellow | US English | ⚠️ Partially verified — mechanisms proven on real cartridges, no full playthrough |
| 1 | PureRed, PureBlue, PureGreen ([pureRGB](https://github.com/Vortyne/pureRGB) v2.7.6) | The pinned build only (admitted by ROM sha1); optional SLink companion overlay; randomized pairs via the SLink fork of UPR ZX | ⚠️ Same evidence bar as Red/Blue — the same duo harness runs on PureRed↔PureBlue, PureRed↔PureGreen and the overlay pairing (`docs/purergb/PLAN.md` §13.1) |
| 2 | Crystal | GBC | ⚠️ Partially verified — Crystal only, mechanisms proven on a real cartridge, no full playthrough |
| 4 | HeartGold, SoulSilver, Platinum | Vanilla, Renegade Platinum | ⚠️ Experimental — never run against a real game |
| 5 | Black, White, Black 2, White 2 | US | ⚠️ Experimental — never run against a real game |

> **Note:** Only Gen 3 has been extensively tested in live gameplay. **Gen 1 is verified end to end for the rules, on Route 1:** the rewritten client's duo harness (`tools/e2e_duo.py`, game `gen1_new`) runs eighteen scenarios — `link_new`, `deadzone_new`, `linked_faint_bench_new`, `linked_faint_active_new`, `reconnect_new`, `ball_gate_new`, `trade_new`, `soft_reset_new`, `trade_decline_new`, `explode_new`, `pc_ops_new`, `changebox_new`, `whiteout_new`, `type_clause_new`, `species_clause_new`, `poison_new`, `rival_swap_new`, `admit_randomized_new` — of which four (`link_new`, `ball_gate_new`, `deadzone_new`, `species_clause_new`) inject nothing: both cartridges walk real grass, meet real wild Pokémon and throw real Poké Balls, and the server pairs the captures by area — so encounter linking, the Poké Ball gate, the dead zone and the species clause all have live PASS evidence (`docs/gen1_requirements.md` D-1..D-4). What Gen 1 has NOT done is play more than one area: the scripted warp is undrivable from Lua, so the other 38 encounter areas rest on a generated oracle cross-checked against the ROM by a second independent path. `python tools/verify_gen1_release.py` runs the whole Gen 1 lane set fail-closed, where a skipped test counts as a failure. **Gen 2 is partially verified:** faint propagation, party/box sync and memorialize execute against a real Crystal cartridge, but it has never been played through a run — New Bark Town's west exit is script-locked until Elm hands over a starter, so there is no grass fixture to walk. Gen 2 coverage is Crystal only — Gold, Silver and Archipelago Crystal have no ROM dump to gate against. Gens 4 and 5 have full feature parity with Gen 3 (moves/PP, stat stages, doubles, forms, egg detection, stream overlays) and pass their unit-test suites, but have **never run against a real game** — treat them as experimental. Gen 4 doubles + stat-stage battle-struct addresses are read-only-scannable via `lua/tests/test_gen4_battlers_count.lua` + `test_gen4_stat_stages.lua` and need a one-time live capture to populate the profile. Gen 5 has the same shape via `lua/tests/test_gen5_block_b.lua` and `lua/tests/test_gen5_doubles.lua`. Gen 1/2 runtime checks live in `docs/gen1_gen2_runtime_checks.md`.

## Before you start

| You need | Notes |
|---|---|
| **Python 3.11+** | `pip install -r requirements.txt` |
| **BizHawk 2.9+** | Two instances, one per player. Savestates are version-locked — a state written by a different BizHawk stops the emulator on a modal dialog. |
| **Two ROMs** | One per player. Both players must run the same **game family** — Red and Blue link, FireRed and LeafGreen link; a Radical Red run needs Radical Red on both sides. |
| **A full checkout, on both machines** | The launcher scripts are small stubs that `dofile` the real client out of this repo, so a remote friend needs the repo too — sending them just the `.lua` will not work. |

The LuaSocket DLL is **already committed** at `lua/x64/socket-windows-5-4.dll`. There is nothing to download.

## Which server am I running?

There are two ways to run SLink, and they listen on different ports. Picking the wrong URL is the most common first-run confusion.

| | Command | Open | Use when |
|---|---|---|---|
| **Manager** | `python -m server.manager --host 0.0.0.0` | `http://localhost:8090/` | The UI. Create runs, start and stop them, watch the board, build a randomized pair, pin a run for the stream overlays. Each run it spawns gets its own server starting at **8081**, but you never need to open it: the Manager shows every run's board on its own port. |
| **Single server** | `python -m server.server` | `http://localhost:8080/` | One run, started by hand, no Manager. The same board. |

Both listen for the game clients on TCP **54321** (the Manager gives each spawned run its own TCP port). If a port is taken, the server says so and suggests a free one instead of printing a traceback.

The board is one page: both players' current position and fight at the top, then every linked pair as a row — A's half, the bond, B's half — sorted into *in party*, *pending*, *split*, *boxed* and *fallen*, with the event log beside it. Boxes and the memorial are zones of that page, not other pages.

## Quick Start

```bash
# 1. Install Python deps
pip install -r requirements.txt

# 2. Start the Run Manager
python -m server.manager --host 0.0.0.0

# 3. Open the dashboard
#    http://localhost:8090/
```

From the Manager:

1. **New run** — name it, pick the game family (or leave *Detect when players connect*), tick any clauses or options. On Red · Blue · Yellow or PureRed · PureBlue · PureGreen the form has a **Cartridges** step — each player's cartridge (the ones in the SLink folder are already listed and the first two of the run's family are picked; *Add file…* takes one from anywhere) and **SLink companion** (the native Cable Club trade, the START-menu SLINK panel and the native sounds patched in — optional, the Lua HUD does the same job on screen; greyed for Yellow, which has no companion build) — followed by a **Randomizer** section whose *Randomize* switch unfolds the settings (same settings, different seeds). **Create run** starts its server and makes the cartridges.
2. **Download the cartridges and the launchers** — the empty board's first step offers *Player A · .gb* / *Player B · .gb* when the run made them, then *Player A · .lua* / *Player B · .lua*; both are also under *Launchers ▾* in the run header, and on the run's **Cartridges** page. A randomized run admits no other cartridge; a companion-only run admits any cartridge of its family.
3. **Load in BizHawk** — each player loads their cartridge (or their own, when the run made none), then the launcher in the Lua console (one per emulator). It finds the game and connects; the player's card on the board turns green.
4. **Catch something** — the first catch both of you make in the same area starts the board.

> Load the script **after** loading your save file. Writes are disabled until SaveBlock validation passes.

> The theme picker in the rail swaps the palette (default / Funtastic grape / jungle / fire / ice / watermelon / smoke / light / transparent). The choice is persisted in `localStorage` + a `slink-theme` cookie so it survives page loads and applies on the first byte (no FOUC).

## How It Works

```
BizHawk A ─── Lua client ──┐
                            ├── TCP :54321 ──→ Python server ──→ HTTP :8080
BizHawk B ─── Lua client ──┘
```

- **Lua clients** diff RAM each frame and send JSON events only on changes (capture, faint, area change, party move)
- **Server** returns commands in the TCP response (`force_faint`, `box_mon`, `party_mon`, `memorialize`; plus `force_explode` / `replace_rival_team` for the RR run augmentations)
- **Web UI** is Jinja2 templates served by aiohttp, swapped in-place by HTMX (idiomorph) every ~2 s, with small Alpine.js widgets for the theme picker
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

### Optional Run Augmentations (Radical Red)

Opt-in per-run rules — passed as CLI flags (or toggled in the Run Manager's new-run form) and **only active on Radical Red**; vanilla / Archipelago / Emerald fall back to default behavior.

| Flag | Effect |
|------|--------|
| `--explode-mode` | On a linked partner's death, the surviving mon is coerced into using **Explosion** mid-battle (server emits a `force_explode` command) instead of a silent force-faint |
| `--rival-team-swap` | On a rival battle, the rival's team is replaced live with the **partner run's current party** (server emits `replace_rival_team`; requires the companion patch) |
| `--overworld-presence` | **Peer ghost** — your partner walks your overworld as a live NPC with their own avatar and 1:1 movement (requires the companion patch) |

Per-run **native UI & audio toggles** (also in the Run Manager's new-run form; all require the companion patch, none change Soul Link rules): `--native-messages` (notifications as native in-game text boxes instead of the Lua HUD), `--native-sounds` (notification sounds via the game's own audio engine), `--no-battle-calc` (hide the bundled in-battle damage calculator, shown by default), `--no-pc-trade-npc` (disable Radical Red's Pokémon-Center trade NPC, on by default and only active while Overworld Presence is off; Gen 1 trades at the Cable Club receptionist — the cartridge's own counter on the companion patch / pureRGB overlay, the Lua HUD otherwise — which has no switch).

## Web Pages

Everything lives on the **Manager** (`python -m server.manager`, port 8090): the rail lists your runs; each run has its board (`/runs/{id}`), its damage calculator (`/runs/{id}/calc/normal.html`) and its debug tools (`/runs/{id}/debug`); **Broadcast** is the overlay gallery with the pinned run's Twitch bot (`/broadcast/twitch`) and OBS scene triggers (`/broadcast/obs`); **Tools** is the patcher and the randomizer. A run started by the Manager redirects its own pages there, so you never land in the run server's chrome. The pages below are what the per-run server renders on its own port when run standalone (`python -m server.server`):

| Path | Description |
|------|-------------|
| `/` | Live status — parties (split or combined linked-pair view), encounters, linked pairs, area states, enemy battle info, and an **Upcoming Key Trainers** panel (RR: next gym leaders/rivals vs party level, with an "Open in Calc" button). HTMX morph swap every 2 s preserves scroll/`<details open>` state. |
| `/memorial` | Tombstone cards for dead pairs, polled via HTMX |
| `/obs` | OBS scene trigger configuration (the same panel as the Manager's `/broadcast/obs`) — per-player WebSocket connections, draggable priority rules, area-group filter (`group:routes`, `group:caves`, …) |
| `/twitch` | Twitch bot configuration and activity log (the same panel as the Manager's `/broadcast/twitch`) |
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
| `/patcher` | In-browser companion-ROM patcher — applies `SLink-RR.ups` to a clean Radical Red ROM client-side (nothing uploaded). Also served on the Manager port (8090). |

## pureRGB (Gen 1)

[pureRGB](https://github.com/Vortyne/pureRGB) is supported as a second Gen 1 foundation (`game_id gen1_purergb`) beside vanilla Red/Blue/Yellow, from **exactly one pinned release** (v2.7.6, commit `7e7a4653`; `data/purergb_sources.lock.json`). Build the three cartridges from source with `python tools/build_purergb_syms.py` (RGBDS 1.0.3 + w64devkit, pinned by sha256; the build must reproduce the release ROMs byte for byte or nothing is published) or apply the upstream `.bps` to a clean Red/Blue dump — either way the client admits a cartridge by its **full ROM sha1** (`data/games/gen1_purergb/admission.json`), never by the header (PureRed/PureBlue keep the `POKEMON RED`/`BLUE` header), so an older or newer pureRGB version is refused, not mis-profiled. Every game fact — engine hook bytes, the overworld write checkpoint, 190 species incl. the 13 forms/spirits and MissingNo, pureRGB's own typings, evolutions, 78 encounter areas, trainers, items, charmap — is generated from the pinned source and verified against the built ROMs (`data/games/gen1_purergb/`). Rules are the vanilla rules; two pureRGB-specific identity events are handled as `key_change`: script transformations (Volcano Magmar, Diamond Mine Onix, …) and the **APEX CHIP** (which maxes DVs — a same-species/same-OT duplicate would collide, so the client restores the DVs and the run refuses the collision). A pureRGB run pairs **only with pureRGB** (a vanilla↔pure hello is refused as MIXED GAMES), needs BizHawk in **GBC console mode** (DMG/SGB unsupported), and Explode Mode works through pureRGB's own rule (EXPLOSION self-KOs below ⅓ HP; the client puts the battler there first).

**Companion overlay.** The native trade + START-menu SLINK panel are a **source overlay** linked into the pureRGB build (`patch/gen1/purergb/`, `python tools/build_purergb_overlay.py`) and shipped as `patch/dist/SLink-Pure{Red,Blue,Green}.ups` over the pinned pure ROM (also in the `--with-patch` release bundle). The overlay build additionally refuses a *colliding* APEX CHIP use before the chip is consumed. A clean pure save loads on the overlay build unchanged. The build tools leave the three pinned cartridges in `.cache/purergb/` and the overlays in `.cache/purergb-overlay-staged/`; the Manager's randomizer finds both there.

**Where to read more.** `docs/purergb/CHANGELOG.md` (everything that shipped, by area, with the evidence and the known limits), `docs/REFERENCE.md` (the Gen 1 · pureRGB bullet), `docs/purergb/PLAN.md` (the plan and its gate ledger).

**Randomized pairs.** The Manager's randomizer runs pureRGB through the SLink fork of UPR ZX 4.6.1 (`python tools/build_upr_fork.py --bootstrap` → `.cache/slink-upr/PokeRandoZX.jar`, `4.6.1-slink3` — the pipeline refuses an older fork revision): a lossless handler (an untouched pure ROM round-trips byte-identically), pure INI entries generated from the pinned symbols, and every code-patching tweak off (pureRGB has instant text natively); one tweak is allowed, lower-case names, a data write the fork re-cases byte-for-byte over the name table. The run then admits only the two prepared cartridges (fingerprint + full sha1 from the contract).

## Companion Patch (Radical Red)

An optional UPS patch (`patch/`) injects native SLink support into the Radical Red ROM. It enables the **peer ghost** (Overworld Presence), **native trade** (talk-to-partner / PC trade NPC), **in-battle notifications**, **native message boxes and sounds**, the bundled **Battle Calc** damage display, the native Rival Team Swap path, and a **Soul Link entry in the game's own START menu** that opens a native run summary — linked pairs with both halves' HP, status and level, dead zones and badges — so you can check the run without leaving the game. Build it with `patch/tools/build.py`; apply it in the browser at `/patcher` (or download the `.ups` from `/companion/SLink-RR.ups`). See [patch/README.md](patch/README.md) for the full feature list and opcode reference.

## OBS Scene Triggers

Automatically switch OBS scenes based on game events. Configure from the Manager's **Broadcast → OBS** (`/broadcast/obs`) or the run's `/obs` page.

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

Orchestrate multiple runs from a single page:

```bash
python -m server.manager --host 0.0.0.0
# http://localhost:8090/          the first running run's board
# http://localhost:8090/new       create a run: game family first, options greyed with reasons
# http://localhost:8090/runs/<id> a run's board (live, or what it persisted once stopped)
# http://localhost:8090/broadcast the overlay gallery
# http://localhost:8090/tools     the patcher and the Gen 1 randomized-pair builder
```

**Cartridges (Gen 1).** A Red · Blue · Yellow or PureRed · PureBlue · PureGreen run makes each player's cartridge from what was picked and hands it out (`server/cartridges.py`; the run's *Cartridges* page rebuilds it). The picker lists every `.gb`/`.gbc` in the SLink folder, `roms/`, `patch/build/` and the `.cache/purergb*` build folders, each named for what it is — *Red · clean dump*, *PureBlue · pinned pureRGB v2.7.6 build*, *PureBlue · SLink companion overlay (native trade, START-menu panel, native sounds)* — and greys what the run cannot start from (anything already modified) or cannot take (a run's game names its family: vanilla dumps on a pureRGB run, and the reverse, are refused by name before anything is spent). *Add file…* is the browser's own file dialog; the file lands in `roms/` (gitignored).

- **SLink companion** puts the native Cable Club trade and the START-menu SLINK panel on the cartridge. Vanilla Red/Blue: the published UPS (`patch/dist/SLink-RB-*.ups`) on a clean dump, or — when randomizing — the structural injector (`patch/gen1/tools/inject.py`) *after* the randomizer, since a UPS is bound to one exact source. pureRGB: the companion is the overlay build (`patch/dist/SLink-Pure*.ups` on the pinned build, checked against `admission_overlay.json`; picking a built overlay uses it as-is), made *before* randomizing — the SLink fork randomizes it as an overlay. Yellow has no companion build (no free WRAM for the mailbox) and plays with the Lua HUD. The patch is optional either way; without it the client falls back to the HUD.
- **Randomize** builds one randomized cartridge per player — same settings, different seeds — from your own copy of Universal Pokémon Randomizer ZX (put `PokeRandoZX.jar` in the SLink folder or `.cache/upr/`, pick it with *Pick…*, or set `SLINK_UPR_JAR`; Java must be on `PATH`; pureRGB needs the SLink fork jar). Choose what to randomize and how hard — wild/static/trainer modes, level curves (−50…+50 %), fully-evolved-from-level, similar strength, rival keeps starter, minimum catch rate, TM compatibility, field items and the misc tweaks. The run then admits only those two cartridges (`rom_contract.json` binds each player's *final* cartridge: content fingerprint and full sha1). Types, evolutions, movesets, base stats, EXP curves and in-game trades are never randomized, so the species and type clauses mean the same thing on both; the full list is `server/upr_settings.py::OPTIONS`.

Downloads: `slink_<run>_a` / `_b` from the empty board, *Launchers ▾* or the Cartridges page, with the source's extension — `.gb` for a Red/Blue dump, `.gbc` for Yellow and pureRGB. Keep it: BizHawk picks the system by the extension for a ROM its database does not know, so a pureRGB cartridge renamed `.gb` runs on the DMG core in mono.

*Presets and settings files.* *Save* keeps the randomizer's settings by name on this Manager (`data/runs/presets.json`); *Export .rnqs* / *Import .rnqs…* speak UPR's own settings file — the one its GUI opens and the one each run keeps (*the settings file (.rnqs)* on the randomizer page) — so two players can trade settings. An imported file goes through the pipeline's own gates: a file that randomizes types is refused by name, not silently read as "unchanged".

## Tests

```bash
pytest tests/unit/ -v                          # ~1600 tests, no emulator needed
pytest tests/ -q                               # + integration (~1700)

# Headless BizHawk gates — drive a real emulator
SLINK_LIVE=1 pytest tests/live/ -q             # 65 gates: Gen 3 (39), Gen 1 (24), Gen 2 (2)

# Two-instance end-to-end: two emulators + a real server
SLINK_E2E=1 SLINK_LIVE=1 pytest tests/e2e/ -q  # 27 runs across Gen 3, Gen 1 and Gen 2
```

The live gates and duo scenarios need BizHawk and the ROMs. Gen 3 also needs
current savestates (`python tools/mkstates.py`); Gen 1 and Gen 2 boot from
committed battery saves instead, so nothing to rebuild after an emulator
upgrade. Everything skips cleanly when a ROM or fixture is missing. See
[tests/TESTING.md](tests/TESTING.md).

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
  templates/             # Jinja2 templates: the shell (_rail, panel_page, dashboard, manager), the panels (_*_panel), stream/*
  static/                # CSS, JS, fonts, vendor bundles (htmx, alpine, idiomorph)
    themes/              # default + 6 Funtastic palettes + light/transparent stubs
  templating.py          # aiohttp-jinja2 setup, theme cookie resolver, no-cache middleware
  calc_files.py          # The damage calculator's files (dist/src resolution), shared by both apps
  overlay_catalog.py     # Stream overlay registry (URLs, layouts, query params)
  patcher.py             # /patcher page + /companion/SLink-RR.ups routes (both ports)
patch/                   # Companion ROM patch (C sources, mailbox handlers, build.py, dist .ups)
data/
  games/                 # Per-game static data (area maps, items)
  obs_config.json        # OBS connection + trigger rule config
calc/                    # Radical Red damage calculator + live bridge (rendered via Jinja shell)
tests/                   # unit + integration (~1700), live BizHawk gates (tests/live/), two-instance E2E (tests/e2e/)
  fixtures/gen1, gen2    # committed battery saves the GB duo runs boot from
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
