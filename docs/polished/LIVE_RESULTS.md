# Polished Crystal client: first live results (2026-10-04)

The first live run of the Polished client (`lua/gen2/polished.lua` via `compose_polished`) on a running cartridge.
The owner authorised two runs on 2026-10-04: "Polished hello + catch + box census" and "Polished trade stack
fingerprint". **These runs are DEV evidence only. They are not PHYSICAL receipts for the gate system.** Receipt
generation is the coordinator's call.

## Setup

| item | value |
|---|---|
| ROM | overlay built by `tools/build_polished_companion.py` (cached `F:/slink-work/cache/polished/companion-overlay/polishedcrystal-3.2.3.gbc`), staged as `F:/slink-work/lanes/pol-live/rom/pol_overlay.gbc`; sha1 `29ea04c24a46d9210c899355fe752f32d2880de8` = `data/polished/overlay_provenance.json` output.sha1 (checked by the harness before every launch) |
| control ROM | release `polishedcrystal-3.2.3.gbc`, sha1 `6930b48af5844d373e3c9130f26d6dd1084cf4ed` (provenance base_sha1); map-corruption controls only, no client |
| emulator | EmuHawk 2.11.1 (`E:/Howard/Bizhawk`), per-run config copy (`gen1_playthrough.write_run_config`, rewind off, CGB mode, RTC pinned), SaveRAM in the lane dir |
| server | `python -m server.server` subprocess on free local ports, private `--data-dir`, `--wire-log`; `rom_contract.json` = `{"players": {"a": {"rom_sha1": <overlay sha1>}}}` (exercises `rom_contract_by_sha1`) |
| drivers | `tools/polished_live/harness.py` (`setup`, `control`, `live`), `pol_lib.lua`, `setup.lua`, `control.lua`, `live.lua` |
| facts | addresses from `data/polished/polished_slink.sym`; the capture site from `data/games/polished_crystal/engine_signals.json`; map/tileset/collision/menu facts from the pinned source (`F:/slink-work/cache/polished/companion-overlay`, commit 3fa43192). Screenshots only confirmed what the RAM already showed |
| evidence dir | `F:/slink-work/lanes/pol-live/` (`run3_stage14_ok/`, `run5_stage23/`, `live/` = run 6, `control_*`, `setup_*`, `bad_poke_runs/`) |

Every EmuHawk was killed by its own recorded PID (`taskkill /T /F /PID`). At most two instances ran at once.

### Entry path (finding 1)

`lua/game_detect.lua` is **never reached** for a Game Boy cartridge. The real path is:

1. the Gen 2 block in `lua/slink.lua`;
2. `lua/gen2/entry.lua` `Entry.detect_title`, where header `PKPCRYSTAL` maps to title `polished`;
3. `lua/gen2/run.lua`;
4. `Entry.build`, which routes `title == "polished"` to `Entry.admit_polished` / `compose_polished`.

The Polished header is already routed, so no change to `slink.lua` or `game_detect.lua` is needed. The live driver
dofiles the real `lua/slink.lua`. Client log line:
`[SLink-gen2] polished_crystal/polished overlay PRODUCTION (DEV_OVERLAY_SHA1) player a -> 127.0.0.1:<port> (rom 29ea04c2)`.

### SYNTH save (O-33, disclosed)

`harness.py setup` / `setup.lua` builds the fixture `fixture/polished_overlay_warp.SaveRAM` (sha256
`75c7a5dc30126f746567202cfb39fe583dfa04eb226063560541f6cbd29f36b8`).

- **NATIVE:** cold boot, title, NEW GAME, initial options left at defaults (B), Elm's speech, and the clock, gender
  and name prompts (A presses; the player is named `Aaaaaaa`, ID `$D1C2`). Then the arrival in
  `PLAYERS_HOUSE_2F` (frame 3044), and START -> SAVE -> YES (`SaveGameData` ran). The save checks out:
  `sSaveVersion $000A`, checksum `$13E4` computed = stored.
- **SYNTH (WRAM writes between those two native steps):**
  - **Party:** `wPartyCount` = 5, five party structs, OT names and nicknames. The mons are level-50 CROBAT,
    JOLTEON, GOLDUCK, NIDOKING and DODRIO: base stats from `data/pokemon/base_stats/*.asm`, DV 15 (HP DV 14-i),
    move TACKLE, OT ID/name copied from the save's own `wPlayerID`/`wPlayerName`.
  - **Bag:** `wNumBalls`/`wBalls` = 99 POKE_BALL.
  - **Position:** the engine's own warp, the same bytes `Script_warp` writes (`engine/overworld/scripting.asm:2180`).
    That is `wMapGroup` 24, `wMapNumber` 3 (ROUTE_29), `wXCoord` 48, `wYCoord` 12 (COLL_LONG_GRASS in
    `Route29.ablk`), `wDefaultSpawnpoint` = $FF, `hMapEntryMethod` = MAPSETUP_WARP ($F1) and `wMapStatus` = 1. The
    overworld loop then ran MAPSETUP_WARP natively, landing at frame 3129, before the save.
- The game rewrote the synthetic form byte (1 -> 0) before the save. Party keys end `:00`/`:40`.

### Map-corruption investigation (owner screenshot)

The first runs used a **bare** position poke (the four position bytes only, no map setup). Route 29 rendered
corrupt. Controls, each without any SLink Lua:

| control | Route 29 header after CONTINUE | encounter | `continue.png` sha256 |
|---|---|---|---|
| overlay ROM, bare poke | tileset 1, 30x9 (before the save it was still the bedroom's: tileset 11, 4x3) | none, 0 steps in 8000 frames | `5886d43b...` |
| release ROM, bare poke | same | none, 0 steps | `5886d43b...` (pixel-identical) |
| overlay ROM, engine warp | tileset 1, 30x9 | yes, 10 steps / 377 frames | `7936ded0...` |
| release ROM, engine warp | tileset 1, 30x9 | yes, 6 steps / 313 frames | `7936ded0...` (pixel-identical) |

**Cause:** the bare poke. The overlay and the client are excluded: both ROMs behave identically, and the setup and
control drivers never load the client. The poke-mode fixtures are byte-identical across the two ROMs (`0ec53ea3...`).
Every stage result below comes from the engine-warp fixture. The poke runs are archived under `bad_poke_runs/` and
count for nothing except the observations that do not depend on the map: Stage 1 admission and the Stage 4 shape,
both re-taken on the warp fixture.

**Client writes.** `live.lua` wraps every `memory.write*` function before `lua/slink.lua` loads, and the driver
itself writes nothing in the live run. Result: **0 Lua-originated writes** in runs 5 and 6. `panel_writes.log` is
empty, and the client registers exactly one hook (`SLink-gen2-polished:capture_party`).

## STAGE 1: hello admitted. PASS

```
python tools/polished_live/harness.py live   (POL_STAGES=14: run 3; POL_STAGES=23: run 5)
```

Run 3 (EmuHawk PID 42868, server PID 48120). `Entry.build` hashed the ROM; `lua/slink.lua` returned after 8.5 s CPU.

| frame | event |
|---|---|
| 208 | `TitleScreenMain` |
| 220 | `MainMenu` |
| **286** | **hello sent** |
| 336 | overworld first takes input on ROUTE_29 |

Hello fields:

```
rom_type polished_crystal  foundation gen2_polished  artifact_kind overlay
rom_sha1 29ea04c24a46d9210c899355fe752f32d2880de8  companion_abi 3  panel false
party 5 [169:EFFFFF:D1C2:0A9:00 135:DFFFFF:D1C2:087:00 55:CFFFFF:D1C2:037:40 34:BFFFFF:D1C2:022:00 85:AFFFFF:D1C2:055:40]
pc_boxes []  pc_boxes_generation 2  area route_29 / Route 29  ot_id 53698  trainer_name Aaaaaaa
```

Server log (`run3_stage14_ok/server.log`):

```
[a] admission: admitted — cartridge sha1 matches the contract
[a] hello rom=polished_crystal area='route_29' party=5
[a] Identity locked: Aaaaaaa (OT 53698)
Adapter switched to gen2_polished (rom_type=polished_crystal)
[a] route polished_crystal -> gen2_polished (production)
```

`/api/status` `players.a.party_details` decodes every slot correctly (species, level 50, HP, nickname, moves).

**Observation S1-a.** The hello went out at frame 286. That is from the CONTINUE / main-menu screen, after
`TryLoadSaveFile` filled WRAM and 50 frames before the overworld took input. `hello_unheld` counts "party readable
plus 8 stable polls" as a live game. This is the same trap as the Gen 1 note (`reference_bizhawk_gate_drivers`:
"party readable is not in the game"). The identity and party are the save's, so the hello is correct in content but
not in timing.

**Observation S1-b.** The client logs `writes ENABLED` and `nuzlocke ACTIVE (pokeballs already in bag at startup)`.
It made no write attempt (see above).

## STAGE 2: wild catch. PASS

Run 5 (EmuHawk PID 16196, server PID 48180), fixture `polished_overlay_warp.SaveRAM`. The probe is a read-only
`event.on_bus_exec` on System Bus $652B, the same address the client hooks, from the pack: bank 3, flat `0xE52B`,
expected `D7084513FA09D1`.

| battle | what happened | capture site (bank 3) |
|---|---|---|
| escape (negative control) | Pidgey; B (cursor to Run, `menu.asm .b_button`) then A; `BattleMenu_Run` ran once | **0 hits** |
| party catch | Pidgey Lv3; throw 1 failed (frame 2768), throw 2 failed (frame 3600), throw 3 caught (frame 4432) | **0, 0, 1** |
| box catch (Stage 3) | full party: `PokeBallEffect.SendToPC` ran | **0 hits** |

- Hits of $652B in any other bank: 0 for the whole run.
- The hit: **frame 5334, hROMBank $03, PC $652B, SP $C0CF**. At the hit `wPartyCount` was already 6 and the last
  slot's species byte was already 16. The `inc [hl]` and the record copy precede the site, as `signals.lua` assumes.
- **Frame alignment:** the per-frame end-of-frame poll first saw `wPartyCount` 6 after the frame that contained the
  hit. It is labelled 5335 only because the poll runs after `frameadvance`, so this is the same frame as the hit.
- The client emitted `capture` in the same frame window (labelled 5335, +1):
  `{"event":"capture","key":"AE7343:D1C2:010:00","species_id":16,"level":3,"hp":16,"maxHP":16,"area_id":"route_29","in_box":false,"nickname":"Pidgey",...}`
- Server:
  ```
  [a] capture key=AE7343:D1C2:010:00 lv=3 area='route_29'
  [PENDING] route_29 player=a action=add
  ```
  `/api/status` `pending_captures` =
  `{"route_29": {"a": {"key": "AE7343:D1C2:010:00", "species": 16, "level": 3, ...}}}`.
- `signals:status()`: registered `["capture_party"]`, refusals `{}`, drops `{}`, `physical_status` OPEN.

**Observation S2-a.** The server then quarantined the catch (`quarantine: AE7343:D → box (pending link)`) and
queued `box_mon`. The client answered `box_mon_failed reason="Gen 2 box executor not composed"`. The server logged
`unknown event 'box_mon_failed'` and then `box_mon_failed ... party model restored`. A Polished solo catch with no
partner therefore always produces this refusal round trip.

**Observation S2-b.** Battle text prompts never hit `BlinkCursor` (00:086b). The driver advanced battle text with a
90-frame idle fallback (B). Driver detail only.

## STAGE 3: box arrival and census. PARTIAL

The PC deposit UI was not driven. The box arrival used the **native** catch-to-box path instead: with a full party,
`PokeBallEffect.SendToPC` ran at the catch. Not a SYNTH box fixture.

- The catch reached box 1. The capture site did **not** fire (0 hits); correct, since a box catch must not report as
  `capture_party`.
- **FAIL: the client never rescanned the census after the box arrival.** All 269 ticks and the hello carry
  `pc_boxes []` with `pc_boxes_generation 2`. This held after the catch and after a native START -> SAVE as well.
  - Root cause (`lua/gen2/client.lua`): rescans run only on `pending_rescan` or while `box_complete` is false
    (around line 1834).
  - The Polished composition produces no event that sets `pending_rescan`. There is no `capture_box` site, no
    battle-end observation (no `pending_safe`), no PC events, and `read_current_box_num()` returns -1.
  - So after a complete first scan the census is frozen until the next hello.
- **The census itself reads the box mon correctly.** Run 6 (EmuHawk PID 35060, server PID 9748) rebooted from run
  5's flushed SaveRAM (`fixture/polished_overlay_after_run5.SaveRAM`, sha256 `11b283cd...`). Its hello carried
  `pc_boxes = [{"box":0,"slot":0,"key":"A35D6B:D1C2:010:00","species_id":16,"level":2,"nickname":"Pidgey","moves":[33,0,0,0]}]`
  with **`pc_boxes_generation 1`**, and the party Pidgey `AE7343:D1C2:010:00` in slot 6. The run's one FAIL line
  is the driver's "5-mon party" check, which does not apply to that save.
- **Save-time refusal (NEWBOX section 7):** `wGameLogicPaused` was nonzero on 62 sampled end-of-frames during the
  native save. No census scan happened in that window because of the rescan gap above. The `native save running`
  refusal was therefore **not exercised live**; no `polished box census withheld` line appears in `slink_lua.log`.
- The PC-open refusal is not observable: there is no PC-open predicate (NEWBOX section 7).

## STAGE 4: frame-wait stack fingerprint. MEASURED (read-only)

**Not at the receptionist.** The receptionist is in a Pokemon Center 2F, which this save cannot reach cheaply.
Instead: an exec probe on `SlinkDelayFrameBridge` (ROM0 $0070, called from DelayFrame's 7-byte lead-in), sampled
only on frames where `OWPlayerInput` ran (the idle overworld on ROUTE_29). 300 samples, hROMBank $25, SVBK 1,
**SP = $C0DE** every time. Raw `sp+0..sp+31` (run 3, warp fixture):

```
ab0d c251 00fe 86d6 4446 22d1 6b51 e250 1400 018a 6114 0012 0f00 5843 1400 0177   x283
ab0d c251 20fe 86d6 4446 22d1 6b51 e250 1400 018a 6114 0012 0f00 5843 1400 0177   x17
```

Run 1 (poke fixture) showed the same words, except `sp+8..9` = `3e00` instead of `4446`.

| offset | word | resolves to (sym + ROM bytes) |
|---|---|---|
| sp+0 | $0DAB | `DelayFrame+3`: return from `call SlinkDelayFrameBridge` (cd 70 00) |
| sp+2 | $51C2 (bank $25) | `NextOverworldFrame.gfx_done+6`: return from **`call z, DelayFrame`** (`cc a8 0d` at 25:51BF) |
| sp+4..11 | `00fe/20fe`, `86d6`, `3e00/4446`, `22d1` | pushed registers. **sp+4 (F) and sp+8..9 vary**: not usable in a fingerprint |
| sp+12 | $516B (bank $25) | `HandleMap+0x15`: return from `call NextOverworldFrame` (cd 85 51) |
| sp+14 | $50E2 (bank $25) | `OverworldLoop.loop+9` |
| sp+16 | $0014 | `FarCall+4` (rst FarCall frame) |

So Polished's idle-overworld chain is **OverworldLoop -> HandleMap -> NextOverworldFrame -> DelayFrame ->
bridge**. There is no `DelayFrames` link. This corrects the TRADE.md 8.3 scan, which looked only for `call DelayFrames` (`cd a1 0d`): `NextOverworldFrame`
does reach `DelayFrame` directly through a `call z`. The vanilla `sp+12/14/16` constants cannot carry over. The
bytes above are what a `SlinkTradeDispatch`-equivalent would see one call deeper, offset by its own return address.

## Commands

```
python tools/polished_live/harness.py setup                      # POL_KIND=overlay|clean, POL_POSMODE=warp|poke
python tools/polished_live/harness.py control                    # no client: header + screenshot + encounter
POL_STAGES=1234 python tools/polished_live/harness.py live       # POL_FIXTURE=<SaveRAM> to boot another save
```
