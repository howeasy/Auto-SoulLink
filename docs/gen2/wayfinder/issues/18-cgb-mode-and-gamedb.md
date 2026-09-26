# CGB vs DMG mode for Gold/Silver in BizHawk

Type: research
Status: resolved
Blocked by: none

## Question

Gold/Silver are dual-mode cartridges; BizHawk's `ConsoleMode.Auto` picks CGB purely from `game.System == "GBC"` (docs/gen2/research/bizhawk_gambatte_gbc.md section 4) and the gamedb classification for their sha1s was not fetched. Confirm from `Assets/gamedb/gamedb_gbx.txt` at BizHawk 2.11.1 how Gold/Silver/Crystal are classified, whether the SaveRAM name is per title, and whether fixtures and duos must pin `ConsoleMode` explicitly.

## Answer

Resolved by research lane R5 (`docs/gen2/research/gamedb_and_encounters.md` §A). BizHawk 2.11.1 `Assets/gamedb/gamedb_gbc.txt` lists all four sha1s with `System=GBC`, status `G`: Gold `Pokemon - Gold Version (USA, Europe)`, Silver `Pokemon - Silver Version (USA, Europe)`, Crystal 1.0 `Pokemon - Crystal Version (USA, Europe)`, Crystal 1.1 `... (Rev A)`. `ConsoleMode.Auto` reads only `game.System`, so all four boot in CGB mode by default; `RomLoader.cs` never inspects the header CGB byte (gamedb hash lookup decides). SaveRAM names follow the gamedb `Name` per title, so Gold/Silver/Crystal never collide with each other; Crystal<->Crystal still needs per-instance `saveram_dir`. The C# `Gambatte.ISaveRam.cs` appends no tail; the measured 22-byte RTC tail is native gambatte behaviour (B-24 stays open for the native citation). Plan: pin `ConsoleMode = GBC` explicitly anyway (PLAN §5.10) so a gamedb miss (not-in-database ROM) cannot silently boot DMG.
