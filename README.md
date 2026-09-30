<div align="center">

<img src="server/static/pokeball.svg" width="64" alt="">

# Auto-SoulLink

**Automated rules and live tracking for two-player Pokémon Soul Link runs.**

<a href="https://github.com/howeasy/Auto-SoulLink/actions/workflows/test.yml"><img alt="tests" src="https://github.com/howeasy/Auto-SoulLink/actions/workflows/test.yml/badge.svg"></a>
<a href="LICENSE"><img alt="MIT licence" src="https://img.shields.io/badge/license-MIT-green"></a>

<br><br>

<img src="docs/images/board.png" width="900" alt="The Soul Link board showing both players, linked Pokémon pairs, and recent run events">

<sub>Both players' teams, every linked pair, and the run's recent events in one place.</sub>

</div>

In a Soul Link Nuzlocke, two people play their own Pokémon games with linked teams.
Your first catches in the same area become a pair. If one Pokémon faints, its partner
is lost too. Choosing a team means choosing pairs that work for both players.

**SLink keeps those rules in sync while you play.** It links your catches, applies
partner faints, keeps party and PC changes together, and records lost pairs in a
memorial. Both games run in **BizHawk**, with a shared board you can open in your browser.

[Get started](#get-started) · [The rules](#the-rules) · [Games](#games) ·
[Streaming](#streaming) · [Documentation](#documentation)

## Follow the whole run

<img src="docs/images/linked-pairs.png" width="900" alt="Linked Pokémon pairs grouped by in-party, waiting to link, boxed, and fallen">

The board shows where each player is, what's happening in battle, and which Pokémon
belong together. Pairs are grouped into **in party**, **pending**, **boxed**, and **fallen**.
A pending catch is waiting for the other player's catch in that area.

You can see both halves of a pair together, check the run's recent events, and look
back at earlier losses without keeping a separate tracking sheet.

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

You'll need **Python 3.11+**, **BizHawk 2.11+**, and a compatible game ROM for each player.
No ROMs are included. Both players choose games from the same family: Red can link
with Blue, for example; a Radical Red run uses Radical Red on both sides.

Install SLink's requirements and start the Manager from the project folder:

```bash
pip install -r requirements.txt
python -m server.manager --host 0.0.0.0
```

Open **http://localhost:8090/** on the machine running the Manager.

<img src="docs/images/manager-new.png" width="900" alt="Creating a run: choose a name, game family, and optional rules">

1. **Create a run.** Give it a name, choose your game family, and select the rules you
   want to use. Game preparation and randomizer settings appear where the selected
   game family supports them.
2. **Download each player's setup.** Open **Launchers** on the run page and download
   the Player A and Player B setup ZIPs. Each includes the SLink runtime and that
   player's launcher. Download the prepared game files too if your run made them.
3. **Connect both games.** Each player extracts their setup, opens their game and
   loads their save in BizHawk, then loads the included launcher in the Lua console.
4. **Play.** Your first catches in the same area form a pair. Keep the board open to
   follow your teams, encounters, and losses.

For a player on another machine, set **Players connect to** under **Launchers** to
an address they can reach, then download the setup again. That player opens their
own game in BizHawk; the Manager stays on the host's machine.

> Load your game and save **before** the launcher. If you download only the `.lua`
> launcher instead of the setup ZIP, that player also needs SLink's Lua runtime.

## Games

These game families are offered by the current Manager. Game versions and optional
features matter, so use the game's setup options when preparing a run.

| Game family | Pairing |
|---|---|
| **Red, Blue, Yellow** | Two games from this family |
| **PureRed, PureBlue, PureGreen** ([pureRGB](https://github.com/Vortyne/pureRGB)) | Two compatible pureRGB games; separate from vanilla Red/Blue/Yellow |
| **Gold, Silver, Crystal** | Two games from this family |
| **FireRed, LeafGreen** | Two games from this family |
| **Emerald** | Emerald on both sides |
| **Radical Red 4.1** | Radical Red on both sides |
| **Archipelago Red/Blue** | Compatible Archipelago builds |

Archipelago FireRed/LeafGreen is disabled in this checkout's new-run form.
Gen 4 and Gen 5 work is experimental and isn't offered there yet.

Testing is performed with ROMs in **BizHawk emulation**. SLink is in active development;
the list above describes available choices, not a completed playthrough of every game.
See the [runtime checks](docs/gen1_gen2_runtime_checks.md) and
[generation plans](#documentation) for the detailed evidence and remaining work.

## Prepare your games

For game families that support randomization, the Manager can build a pair with
**the same settings and different seeds**. Choose encounters, trainers, items, and
difficulty settings in the form. The available settings keep both games compatible
with the Soul Link rules.

Optional **companion patches** add game-specific features such as in-game run panels
and native Soul Link trades. Availability depends on the title; the new-run form
shows which options you can use. They are separate from the core linking rules.

More detail: [pureRGB](docs/purergb/README.md) · [Companion patches](patch/README.md).

## Plan your next battle

<img src="docs/images/calc.png" width="900" alt="The damage calculator alongside both players' live parties">

The bundled damage calculator can load Pokémon from either player's current party,
so you can compare matchups without retyping the whole team. It uses the selected
game's data where supported.

Radical Red also has an **Upcoming Key Trainers** panel: review a trainer's team
and open it in the calculator before the fight.

## Remember the pairs you lost

<img src="docs/images/memorial.png" width="900" alt="A memorial card showing a fallen pair, their encounter area, and the recorded cause of death">

The memorial keeps both Pokémon together with their encounter area, time of death,
and the recorded cause. It gives you a history of the run's losses alongside the
pairs still in play.

## Streaming

<img src="docs/images/overlays.png" width="900" alt="A gallery of stream overlays for parties, linked pairs, battles, and the memorial">

Open **Broadcast** to preview overlays and add them to OBS as browser sources.
Show either player's party, linked pairs, battle information, badges, recent events,
or the memorial. The overlays update from the run as you play.

Optional stream tools include OBS scene changes on run events and a Twitch bot
that answers questions such as `!partner`, `!rip`, and `!runstats`. Their setup pages
are under Broadcast. These integrations need extra packages:

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
