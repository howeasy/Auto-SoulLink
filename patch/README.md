# SLink companion patches

The companion patch puts SLink inside the game itself: the SLINK panel and messages, in-game trades
between linked Pokémon, sounds, and the SoulLink title screen. Every game below that has a patch
**requires** it. A clean cartridge of those games is refused, with a message telling you to patch it.

## Which games need it

| | Games |
|---|---|
| **Patch required** | Red, Blue · PureRed, PureBlue, PureGreen · Gold, Silver, Crystal · FireRed, LeafGreen, Emerald · Radical Red |
| Played clean | Yellow · Emerald Expansion |

## Get a patched cartridge

- **Run Manager (recommended).** When you create a run, the Manager patches each player's cartridge for
  you, after randomizing it if you chose that.
- **In the browser.** Open `/patcher` on the run server (port 8080) or the Manager (port 8090), pick
  your clean ROM and download the patched one. Nothing is installed.
- **By hand.** Apply `patch/dist/SLink-<Game>.ups` to the matching clean ROM with any UPS patcher
  (Flips, RomPatcher.js, …).

A patched game opens on a **SoulLink** title screen and shows the patch version on the New Game /
Continue menu. If your menu shows `dev` on Red/Blue, pureRGB or a Gen 3 game, the cartridge is from an
earlier build: prepare a fresh one.

## Check your ROM

Start from an unmodified dump. Radical Red is built for one exact release:

| | md5 |
|---|---|
| Radical Red, clean | `8529f3a45d32bce4da637976fcf269d4` |
| Radical Red, patched | `b9b8304c0c189bfbe54e9fc8df33c486` |

| Patch | Clean ROM md5 | Patched ROM md5 |
|---|---|---|
| `SLink-RB-Red.ups` | `3d45c1ee9abd5738df46d2bdda8b57dc` | `c5c715cda8b0fa178ab30f4fd9e4d821` |
| `SLink-RB-Blue.ups` | `50927e843568814f7ed45ec4f944bd8b` | `cc5d142b0d1c4df8b5e155ded2894e84` |

If your clean ROM's md5 doesn't match, the patch won't apply. Use the matching dump.

## Options per run

Set these in the Manager's **New run** form.

| Option | Default | What it does |
|---|---|---|
| Native Sounds | Off | Plays run event sounds through the game |
| Battle Calc | On | Radical Red: shows the damage of the highlighted move in battle |
| PC Trade NPC | On | Gen 3: a trader in each Pokémon Center for swapping linked Pokémon with your partner |
| Phone Calls | On | Gold/Silver/Crystal: your Pokégear rings for a new link, a dead zone or a fallen Pokémon |

Building or changing the patches: see [DEVELOPER.md](DEVELOPER.md).
