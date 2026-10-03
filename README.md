<div align="center">

<img src="server/static/pokeball.svg" width="64" alt="">

# Auto-SoulLink

**Two-player Pokémon Soul Link Nuzlocke automation. No spreadsheets, no honour system.**

<a href="https://github.com/howeasy/Auto-SoulLink/actions/workflows/test.yml"><img alt="tests" src="https://github.com/howeasy/Auto-SoulLink/actions/workflows/test.yml/badge.svg"></a>
<a href="LICENSE"><img alt="MIT licence" src="https://img.shields.io/badge/license-MIT-green"></a>

<br><br>

<img src="docs/images/board.png" width="900" alt="The Soul Link board showing both players, linked Pokémon pairs, and recent run events">

<sub>Both players' teams, every linked pair, and the run's recent events in one place.</sub>

</div>

## Two games, one rule

A Soul Link Nuzlocke is two friends, two copies of the same game, and one rule that makes every decision cost something: **the first Pokémon you each catch in an area become a pair.** Lose one and you lose the other. Choosing a team means choosing pairs that work for both of you.

That's the fun, and the nuisance. SLink takes the nuisance away — it reads both games, does the pairing, and makes the rules happen inside the emulators:

- your first catches in an area are paired the moment both land;
- when one Pokémon drops, **its partner faints in the other game**, live, mid-battle;
- a board and a set of stream overlays tell the story, so you watch instead of score-keeping.

Both games run in **BizHawk**. A Python server holds the Soul Link rules and the browser UI; each emulator runs a generation-specific Lua client that reads its game and reports back.

[Get started](#get-started) · [The rules](#the-rules) · [Games](#games) ·
[Streaming](#streaming) · [Documentation](#documentation)

## One board for the whole run

<img src="docs/images/linked-pairs.png" width="900" alt="Linked Pokémon pairs grouped by in-party, waiting to link, boxed, and fallen">

A **Now** card per player — where they are, what they're fighting, HP and moves — then the pairs sorted into **In party**, **Pending link**, **Split**, **Boxed**, **Linked** and **Fallen**, with the run's event log beside them.

A pending catch is waiting for the other player's catch in that area. If the page ever stops answering, the board says **"Connection lost — retrying…"** instead of quietly showing stale numbers.

## The rules

| Rule | What happens in your run |
|---|---|
| **One encounter per area** | Each player's first eligible catch in the same area becomes a linked pair. |
| **Missed encounter** | Failing to catch your encounter closes that area for both players. |
| **Shared faints** | When one Pokémon faints, SLink faints its linked partner in the other game. |
| **Linked teams** | Both Pokémon in a pair must be in the party together or in the PC together. |
| **Memorial** | Fallen pairs are recorded on the board and moved to the memorial box when the games can safely do so. |
| **Starting the challenge** | Enforcement begins once you have Poké Balls. |

The new-run form also offers **species, gender, and type clauses** where the selected
game supports them. Each option explains what it changes before you start.

## Get started

You need **Python 3.11+**, **BizHawk 2.11+** (Gen 2 runs on 2.9+ too), and a compatible game ROM for each player. **No ROMs are included** — bring your own dumps.
Both players choose games from the same family: Red can link with Blue, for example; a Radical Red run uses Radical Red on both sides.

Install SLink's requirements and start the Manager from the project folder:

```bash
pip install -r requirements.txt
python -m server.manager --host 0.0.0.0
```

Open **http://localhost:8090/** on the machine running the Manager.

Which port is which: **8090** is the Manager (the page above). Each run the Manager starts gets its own dashboard, starting at **8081** and counting up. **8080** is the dashboard of a single run started by hand with `python -m server.server` (its `--http-port` default); the Manager never uses it.

<img src="docs/images/manager-new.png" width="900" alt="Creating a run: choose a name, game family, and optional rules">

1. **Create a run.** Give it a name, choose your game family, and select the rules you want to use. Game preparation and randomizer settings appear where the selected game family supports them.
2. **Download each player's setup.** Open **Launchers** on the run page and download the Player A and Player B setup ZIPs — SLink's Lua runtime with that player's launcher inside. Download the prepared cartridge too if your run made one.
3. **Connect both games.** Each player extracts their setup, opens their game and loads their save in BizHawk, then loads the included launcher in the Lua console.
4. **Play.** Your first catches in the same area form a pair. Keep the board open to follow your teams, encounters, and losses.

For a player on another machine, set **Players connect to** under **Launchers** to an address they can reach, then download the setup again. That player opens their own game in BizHawk; the Manager stays on the host's machine.

> Load your game and save **before** the launcher. If you download only the `.lua`
> launcher instead of the setup ZIP, that player also needs SLink's Lua runtime.

## Games

These game families are offered by the current Manager. Game versions and optional features matter, so use the game's setup options when preparing a run.

| Game family | Pairing |
|---|---|
| **Red, Blue, Yellow** | Two games from this family |
| **PureRed, PureBlue, PureGreen** ([pureRGB](https://github.com/Vortyne/pureRGB)) | Two compatible pureRGB games; separate from vanilla Red/Blue/Yellow |
| **Gold, Silver, Crystal** | Two games from this family |
| **FireRed, LeafGreen** | Two games from this family |
| **Emerald** | Emerald on both sides |
| **Emerald Expansion** | The prebuilt Emerald Expansion reference ROM on both sides. It is built by `tools/build_expansion.py` from the pinned pokeemerald-expansion source (it cannot be built on a Windows host, and no patch exists); no randomizer, no companion patch |
| **Radical Red 4.1** | Radical Red on both sides |

Archipelago builds may run clean, but the Manager doesn't offer them until a client supports them. Gen 4 and Gen 5 work is experimental and isn't offered there either.

Testing is performed with ROMs in **BizHawk emulation**. SLink is in active development; the list above describes available choices, not a completed playthrough of every game. See the [runtime checks](docs/gen1_gen2_runtime_checks.md) and [generation plans](#documentation) for the detailed evidence and remaining work.

## Prepare your games

For game families that support randomization, the Manager can build the pair for you: **the same settings and two different seeds**, one cartridge per player, made from your own copy of Universal Pokémon Randomizer ZX. Your ROMs stay on the machine that prepared them.

The **companion patch is required** for every title that has one (Red/Blue, pureRGB, Gold/Silver/Crystal, FireRed/LeafGreen/Emerald, Radical Red): the Manager patches your cartridge for you with no opt-out, and refuses a pick it cannot patch — and the launcher and server refuse a clean one too, so bypassing the Manager doesn't get you a working run either.

What it adds, inside the game:

| | |
|---|---|
| **SoulLink title** | The SLink wordmark on the game's title screen, with the patch version on the main menu. |
| **The SLINK panel** | An in-game Soul Link panel you can read without leaving the game. |
| **Native trades** | A trade counterparty in the game itself — a receptionist on patched Gen 1 and Gen 2, a Pokémon Center NPC on Gen 3 by default. On Gen 3 the real in-game trade animation plays on both sides, and only a linked mon is ever accepted: your partner's matching half. |

Yellow, Archipelago and the Emerald Expansion have no companion yet and still run clean — the same Soul Link rules, without the panel or the native trades. The new-run form shows which options you can use; they are separate from the core linking rules.

More detail: [pureRGB](docs/purergb/README.md) · [Companion patches](patch/README.md).

## Plan your next battle

<img src="docs/images/calc.png" width="900" alt="The damage calculator alongside both players' live parties">

The bundled damage calculator carries a SLink panel with **both players' live parties**, so you can compare a matchup without retyping the whole team. It uses the selected game's own data where supported.

Gen 3 runs also get an **Upcoming Key Trainers** panel: read a trainer's roster, then open it straight in the calculator before the fight.

## 🪦 What you lost, in order

<img src="docs/images/memorial.png" width="900" alt="A memorial card showing a fallen pair, their encounter area, and the recorded cause of death">

The memorial keeps both Pokémon of every fallen pair together with their encounter area, time of death, and the recorded cause. It lives at `/memorial` on that run's own port, beside the pairs still in play.

The **Timeline** tells the whole run in order — every pair formed, every death, dead zone and burial — and lists the areas still open, so you always know what is still on the table.

If a native trade ends in a state the server can't settle on its own, the board raises a **Trade conflict** banner with a form to settle it by hand: adopt what each side reported, commit the undecided sides, or roll them back.

## Streaming

<img src="docs/images/overlays.png" width="900" alt="A gallery of stream overlays for parties, linked pairs, battles, and the memorial">

Open **Broadcast** to preview overlays and add them to OBS as browser sources. Either player's party, linked pairs, battle cards, gym badges, the event feed, area and encounter trackers, death and attempt counters, and a memorial scroll — all updating from the run as you play.

Optional stream tools include OBS scene changes on run events and a Twitch bot that answers questions such as `!partner`, `!rip`, and `!runstats`. Their setup pages are under Broadcast. These integrations need extra packages:

```bash
pip install "twitchio>=3.0" "simpleobsws>=1.4" psutil
```

## Documentation

| Guide | What you'll find |
|---|---|
| [Technical reference](docs/REFERENCE.md) | Configuration, tools, game support, and how SLink works |
| [Companion patches](patch/README.md) | In-game features and patch setup |
| [pureRGB](docs/purergb/README.md) | Supported builds and pureRGB setup |
| [Runtime checks](docs/gen1_gen2_runtime_checks.md) | What has been exercised in emulation and the limits of that evidence |
| [Gen 2](docs/gen2/) · [Gen 3](docs/gen3/) | Current generation plans and review records |

<details>
<summary><b>For contributors</b></summary>

The game clients read each game in BizHawk; a shared Python server manages the Soul
Link rules and browser UI. Game-specific behavior lives in adapters.

- [Developer reference](docs/REFERENCE.md)
- [Client/server protocol](docs/protocol.md)
- [Testing guide](tests/TESTING.md)

```bash
pytest tests/unit/ -v
```

Emulator tests need their documented game files and fixtures. Passing unit tests
alone doesn't establish that a game or release is ready.

</details>

## Licence and credits

SLink is [MIT licensed](LICENSE). The bundled calculator retains its upstream MIT
licence; the Universal Pokémon Randomizer ZX patches are GPL-3.0. See
[NOTICE.md](NOTICE.md) for component licences and attribution.

No ROMs or savestates are distributed here. Bring your own game dumps.

Built with [BizHawk](https://github.com/TASEmulators/BizHawk), the
[Smogon damage calculator](https://github.com/smogon/damage-calc), and research from
the [pret Pokémon disassemblies](https://github.com/pret).

<sub>Pokémon is a trademark of Nintendo, Creatures Inc. and GAME FREAK Inc.
This is an unaffiliated fan tool.</sub>
