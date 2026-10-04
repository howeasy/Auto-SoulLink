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

---

# Run 2 (2026-10-04, later): hello gate, census rescan, receptionist stack, Pokegear strip

These are DEV results, not PHYSICAL receipts. The ROM and the emulator are the same as in run 1: the overlay sha1
`29ea04c2...` is checked before every launch. The fixture is run 1's `polished_overlay_warp.SaveRAM` (sha256
`75c7a5dc...`), copied into the new lane `F:/slink-work/lanes/pol-live2/`. The client code is this tree at
`78dddd8b`, which includes the hello gate (`read_overworld_gate`) and `c442a248` (census rescan, `supports_box_mon`).

| run | what | EmuHawk PID | server PID | evidence |
|---|---|---|---|---|
| A1 | `POL_STAGES=123 harness.py live` | 53384 | 51724 | `runA1/`, `runA1.out` |
| A2 | the same, after a driver fix (see Stage A) | 49088 | 45044 | `live/`, `runA2.out` |
| B | `POL_EXPLORE=B harness.py explore` (no client, no server) | 50920 | none | `x/explore_B/` (`resolved.txt`), `runB1.out` |
| C | `POL_EXPLORE=C harness.py explore` (no client, no server) | 55084 | none | `x/explore_C/` (`pokegear.json`, `pokegear_card0..3.png`), `runC1.out` |

Every EmuHawk was killed by its own recorded PID, and at most two ran at once (A2 overlapped B, then C). Every
PID was checked as gone afterwards. New driver pieces:
- `live.lua`: gate-byte transition log and the Stage 3 census evidence.
- `explore.lua`: Stages B and C.
- `harness.py`: an `explore` command and `resolve()`. `resolve()` names each stack word from the sym and checks
  that the ROM bytes before it are a `call`/`rst`.

## STAGE A: hello gate and box-census rescan. PASS (A2: 0 failed checks)

**Hello timing.** Identical in both runs. `gate_transitions.log` is written only when one of `wMapStatus`,
`wScriptRunning`, `wGameLogicPaused`, `wLinkMode` or `wBattleMode` changes.

| frame | event |
|---|---|
| 2 .. 335 | `wMapStatus=0`, running=false (title, main menu, CONTINUE) |
| 208 / 220 | `TitleScreenMain` / `MainMenu` (last hit) |
| 335 | first `OWPlayerInput` exec hit |
| 336 | end of frame: `wMapStatus=2`, script 0, pause 0, link 0. `read_overworld_gate().running` first reads true |
| **343** | **hello on the wire** (gate plus the 8 stable polls of `hello_unheld`) |

The hello now leaves after the first idle overworld frame instead of at frame 286 from the CONTINUE screen
(run 1, S1-a), so S1-a is fixed. Its content matches run 1: party 5, `pc_boxes []`, generation 2, `route_29`,
OT 53698.

**Box census after a native box catch, without a reboot.** The party was full (5 SYNTH mons plus the Pidgey
caught in Stage 2), so the catch ran `PokeBallEffect.SendToPC` and hit the capture site 0 times.

| run | `wBattleMode` 1 -> 0 (end of frame) | first tick carrying the box mon | delay |
|---|---|---|---|
| A2 | 7609 | 7620: generation 7, `pc_boxes` 1 (`box 0 slot 0`, Pidgey, species 16) | +11 frames |
| A1 | 7257 | 7320: generation 7, `pc_boxes` 1 | +63 frames (`wMapStatus` was 1, the map reload, until 7293) |

- The other battle ends re-armed the census the same way:
  - A1: the escape battle cleared at 1460, census at 1500; the party catch cleared at 3274, census at 3330.
  - A2: the party catch cleared at 4282 (map reload until 4318), census at 4320.
- The 1800-frame periodic rescan also fired as designed:
  - A1: 360 -> 5130 -> 6930 -> 9120.
  - A2: 1470 -> 3270.
- The server's `/api/status` `players.a.pc_boxes` carried the box Pidgey (A1 last snapshot), so run 1's FAIL
  (census frozen until the next hello) is fixed.
- Driver note: A1 logged one FAIL. My Stage 3 check started counting census generations *after* the battle had
  already ended, so it skipped the box-carrying one (gen 7 at 7320) and measured the next periodic one (+1826).
  This was fixed in `live.lua` (the mark is now taken before the catch), and A2 passed the same check at -26
  frames from the first overworld input (+11 from the battle-mode clear).

**Server log for the solo catch.** A1 and A2 show the same thing.

```
[a] capture key=0D2D60:D1C2:010:.. lv=3 area='route_29'
[PENDING] route_29 player=a action=add ...
[a] skip quarantine: 0D2D60:D (client has no box executor)
```

There are no `box_mon` commands (`recv.jsonl`: every reply after the first config batch is `noop`), no
`box_mon_failed`, and no `unknown event`. Run 1's S2-a round trip is gone.

The rest matches run 1:
- Capture site: 1 hit in bank 3 at PC $652B, SP $C0CF; `wPartyCount` changed in the same frame; `capture` was
  emitted on hit +1.
- Escape and failed throws: 0 hits.
- The native save held `wGameLogicPaused` for 62 frames.
- 0 Lua-originated writes, 0 panel write attempts.

SYNTH in Stage A: none beyond the run 1 fixture.

## STAGE B: trade receptionist stack. MEASURED (read-only), up to the native link wait

**Facts from the source.**
- `POKECENTER_2F` is map group 20 #1 (`constants/map_constants.asm:431-432`, 8x4).
- The trade receptionist is `object_event 5, 2, ... LinkReceptionistScript_Trade` (`maps/PokeCenter2F.asm:21`).
- The player's talking square is (5,3), where `Script_LeftCableTradeCenter` walks the player.
- The script's first command is `checkevent EVENT_GAVE_MYSTERY_EGG_TO_ELM`. The ROM at 24:7601 reads
  `33 21 00 d2 ...`, so the flag is event $21 = 33, which is `wEventFlags` byte 4 bit 1.

**SYNTH (disclosed).**
- `wEventFlags+4` $00 -> $02, which sets EVENT_GAVE_MYSTERY_EGG_TO_ELM. Without it the receptionist only says
  `Script_TradeCenterClosed`.
- The engine warp to 20:1 (5,3) with the `Script_warp` bytes (`wDefaultSpawnpoint` $FF, `hMapEntryMethod` $F1,
  `wMapStatus` 1). MAPSETUP_WARP landed natively at frame 477 with tileset 14 and an 8x4 header.

Everything after that was native input: Up to face the receptionist, then A presses. A answered YES at the
trade prompt; no other button was used.

| frame | milestone |
|---|---|
| 819 | `FixPlayerEVsAndStats`: the script got past `checkevent` |
| 1003 | `YesNoBox` (trade prompt), answered YES |
| 1024 | `CheckPartyForMail` (no mail) -> `Special_SetBitsForLinkTradeRequest` -> "Please wait." |
| 1039 -> 1552 | `Special_WaitForLinkedFriend`: 513 frames of serial polling, then `.done` (timeout, no cable) |
| after | `.FriendNotReady` text, then `endtext`; overworld again. `Special_TryQuickSave` never ran (no save was written) |

The native link-trade entry is as far as a cartridge with no partner can go: `WaitForLinkedFriend` is the
first link-dependent step, and `TryQuickSave` (TRADE.md's branch point at `:99-101`) comes after it.

**Stack at `SlinkDelayFrameBridge` entry, per phase** (at most 300 samples per phase; raw `sp+0..31` in
`x/explore_B/stacks.json`; names from `resolve()`):

1. **Idle Pokemon Center overworld** (the known-positive control, 300 samples). SP $C0DE, hROMBank $25. This is
   byte-for-byte run 1's Route 29 chain: `0DAB DelayFrame+3` / `25:51C2 NextOverworldFrame.gfx_done+6` / pushed
   registers / `25:516B HandleMap+0x15` / `25:50E2 OverworldLoop.loop+9` / `0014 FarCall+4`. Only sp+4 (F)
   varies. The probe still reads what run 1 read.
2. **Native link wait** (`Special_WaitForLinkedFriend`, 300 samples, 3 distinct). SP $C0DC, hROMBank $0A,
   SVBK 1. **Only sp+2 varies.**

   | offset | word | resolves to |
   |---|---|---|
   | sp+0 | $0DAB | `DelayFrame+3` (return from `call SlinkDelayFrameBridge`) |
   | sp+2 | $4D5F (x298) / $4D1D / $4D20 | `0A: Special_WaitForLinkedFriend.not_done+0xf` (the loop's `call DelayFrame`); the two singles are the lead-in `call DelayFrame`s |
   | sp+4 | $2698 | `_ReturnFarCall` (the script `special` reaches bank $0A through FarCall) |
   | sp+6..11 | `1403 2500 000F` | FarCall-saved registers (`2500` carries the caller bank $25) |
   | sp+12 | $62B5 (bank $25) | `ScriptEvents.loop+9`: return from the `wScriptMode` dispatch call (`cd 00 63`, the mode jumptable that reaches `RunScriptCommand`) |
   | sp+14 | $515F (bank $25) | `HandleMap+9`: return from `call MapEvents` (`cd 77 51`). `MapEvents` tail-jumps (`jmp ScriptEvents`, `events.asm:112`), so it leaves no frame |
   | sp+16 | $50E2 (bank $25) | `OverworldLoop.loop+9` |
   | sp+18 | $0014 | `FarCall+4` |

   Bytes: `ab0d 5f4d 9826 0314 0025 0f00 b562 5f51 e250 1400 018a 6114 0012 0f00 5843 1400`.
3. **YES/NO prompt** (21 samples, 6 distinct; the main one is x15). SP $C0DC, hROMBank $25:
   `0DAB` / `0DA4 SFXDelayFrames+3` / `1947 HandleYesNoMenu+0x23` / `0120` / `18EC PlaceYesNoBox+6` /
   `25:65E5 Script_yesorno+3` / `25:62B5 ScriptEvents.loop+9` / `25:515F HandleMap+9` /
   `25:50E2 OverworldLoop.loop+9` / `0014`.
4. **Talk start** (A press, 6 samples). SP $C0D6:
   `0DAB` / `0DA4 SFXDelayFrames+3` / `25:53E9 PlayTalkObject+0xe` / `D69F` / `25:540F TryObjectEvent+0x24` / ... /
   `25:53D0 CheckAPressOW+8` / `25:53B7 OWPlayerInput+0x10` / `25:5238 PlayerEvents+0x22` /
   `25:517F MapEvents+8` / `25:515F HandleMap+9` / `25:50E2` / `0014`.
5. **Text printing inside the script** ("script" and "after_wait", 249 samples). 167 distinct stacks, SP from
   $C0C2 to $C0DE across banks $01/$05/$09/$0A/$21/$24/$25. DelayFrame is reached through `PrintLetterDelay`,
   `PromptText`/`ButtonSound`, `SafeUpdateSprites`, `_SafeCopyTilemapAtOnce` and others. **Not
   fingerprintable.**

**What this means for the trade hook (input for TRADE.md 8.3).**
- Inside the receptionist script, every frame wait sits under the same bank-$25 tail:
  `ScriptEvents.loop+9 ($62B5) -> HandleMap+9 ($515F) -> OverworldLoop.loop+9 ($50E2) -> FarCall+4 ($0014)`.
- The idle overworld instead has `HandleMap+0x15 ($516B)` at the same depth.
- Above that tail, the frames depend on which special or text routine is waiting. Only the
  `WaitForLinkedFriend` loop is stable: 1 of 32 bytes varies.
- A dispatch that runs from a script `special`/`callasm` would see `_ReturnFarCall` plus the `$62B5/$515F/$50E2`
  tail at a fixed offset under its own frame. That is measurable. The idle-overworld constants
  (`$516B` at sp+12) do not hold anywhere inside the script.

## STAGE C: Pokegear icon strip. MEASURED (read-only)

**SYNTH (disclosed):** `wPokegearFlags` $00 -> $87 (POKEGEAR_OBTAINED_F plus the MAP, RADIO and PHONE card bits).
The EXPN bit 3 was left clear. Everything else was native:
- START menu items `1,2,7,3,4,5,6`, with POKEGEAR (id 7) on row 3; `PokeGear` ran at frame 523.
- Right presses moved card to card. Each card was read in its joypad state (`wJumptableIndex` 01 / 04 / 0A / 0E)
  after a 90-frame dwell.

Rows 0-1 of `wTilemap` (`00:C1A0`) for each card. Columns 0-7 are identical in all four:

```
row 0  cols 0-7:  56 57 | 50 51 | 54 55 | 52 53      (Pokegear, Map, Phone, Radio top halves)
row 1  cols 0-7:  66 67 | 60 61 | 64 65 | 62 63      (lower halves = top + $10, the .PlacePokegearCardIcon shape)
```

| card | `wJumptableIndex` | row 0 cols 8-19 | row 1 cols 8-19 | attr rows 0-1 (cols 8-19) | cursor (`wSpriteAnim1` XCOORD + XOFFSET) |
|---|---|---|---|---|---|
| 0 clock | $01 | `f7 f7 f7 f7 40 7f..7f 41` | `f7 f7 f7 f7 7f 92 b6 a8 b3 a2 a7 f0` (" Switch>") | all 0 | $10 + $00 = 16 |
| 1 map | $04 | `44 91 ae b4 b3 a4 7f e2 e9 7f 7f 7f` (landmark name) | `7f` x12 | all 0 | $10 + $10 = 32 |
| 2 phone | $0A | `06 07 07 .. 07 17` (card frame) | `16 f7 .. f7 68 69 16` (signal bars $68/$69) | pal 1 from col 8 | $10 + $20 = 48 |
| 3 radio | $0E | `06 07 07 .. 07 17` | `16 f7 f7 6c f7 6d 6e f7 6f f7 f7 16` | pal 1 from col 8 | $10 + $30 = 64 |

The arrow's XOFFSET is `card << 4` (`AnimatePokegearModeIndicatorArrow`), so a card 4 lands at 64 + 16 = 80.
**Columns 8-9 of rows 0-1 are drawn by every native card:** the clock border ($f7), the map's landmark name
(starting at column 8), and the phone and radio card frames ($06/$07/$16 with palette 1). A fifth icon at
column 8 therefore collides with each card's own tilemap. The coordinator's `ld bc,$8` note understates this:
widening the black bar alone is not enough, because the card layouts start at column 8. The screenshots
(`pokegear_card2.png`: the phone frame's top-left corner sits right after the Radio icon) only confirm this.

**Tile ids in $50-$7F.** Usage is the union of each card's full 360-byte tilemap, sampled 4 times per card.
VRAM is the bank 0 tile data at `vTiles2 + id*16`, dumped in the radio state.

| ids | in a tilemap | VRAM content |
|---|---|---|
| $50-$57 | yes (icons) | Pokegear gfx |
| **$58** | **yes** (radio card) | Pokegear gfx |
| **$59** | no | inked Pokegear gfx |
| $5A | yes | |
| $5B | no | inked Pokegear gfx |
| $5C-$75 | yes ($60-$67 icon lower halves, **$68-$6B phone signal bars**, $6C-$75 radio) | |
| **$76-$7E** | no | **not Pokegear gfx at all**: the built `gfx/pokegear/pokegear.2bpp` is 608 bytes = 38 tiles ($50-$75), because the Makefile passes `--trim-whitespace` (`Makefile:228`). These ids keep whatever the previous screen left in VRAM (non-blank, map-dependent) |
| $7F | yes (blank fill) | blank |

VRAM bank 1 tiles $50-$7F read all zero (`Pokegear_LoadGFX` calls `ClearVBank1`). No attribute in rows 0-1 sets
the bank bit.

**Verdict on $58/$59: NOT usable as an icon pair.**
- $58 is drawn by the radio card.
- `.PlacePokegearCardIcon` puts the lower half at top + $10, so a $58 icon's lower pair would be $68/$69, the
  phone signal bars (`.PlacePhoneBars`, seen live in the phone card's row 1).
- No pair of adjacent ids in $50-$75 has both itself and its +$10 pair free.

The free ids are $59 and $5B (inked but unreferenced, 2 tiles, not adjacent) and $76-$7E (9 ids, not written by
the Pokegear load, so an SLink icon would need its own 4-tile load into them). With the native placement shape,
lower halves at $86+ would fall in vTiles1 (font). So a fifth icon needs one of the following: its own tile load
plus a placement routine that is not top+$10, or the VRAM-bank-1 route (the bank is empty during the Pokegear;
the icon tiles would go in bank 1 and the attribute bank bit would be set). That is a design call for
POKEGEAR_SLOT.md. Not checked: the Kanto and Orange map views, radio tuning redraws, and bank 1 content in
states other than radio.

## Run 2 commands

```
POL_LANE=F:/slink-work/lanes/pol-live2 POL_STAGES=123 python tools/polished_live/harness.py live
POL_LANE=F:/slink-work/lanes/pol-live2/x POL_EXPLORE=B python tools/polished_live/harness.py explore   # B or C
```

---

# Run 3 (2026-10-04, evening): a Manager-randomized cartridge, end to end

These are DEV results, not PHYSICAL receipts. The owner authorised live Polished randomization runs. The tree is
`e0fd92dd` (the Manager offers Polished randomization) plus this run's driver additions. The jar is the pinned forms
jar `F:/slink-work/cache/polished/jar/PokeRandoZX.jar` (sha256 `f3a10dd7...`, `data/upr_jars.json`). Lane:
`F:/slink-work/lanes/pol-rand/`. Every EmuHawk was killed by its own recorded PID, at most two ran at once (only the
two setups overlapped), and every PID was checked as gone afterwards. Duplicate ROM copies and SaveRAM scratch dirs
were deleted after the runs. The Manager's own run directory and the fixtures were kept.

| run | what | EmuHawk PID | server / Manager PID | evidence |
|---|---|---|---|---|
| R1 | `manager_r1.py jar` (jar installed) | none | Manager 56412 | `r1_jar/` (`calls.jsonl`, `summary.json`, `mgr/run_20261004_211320/`) |
| R1 | `manager_r1.py nojar` / `oldjar` | none | Manager 49968 / 4744 | `r1_nojar/`, `r1_oldjar/` |
| setup | SYNTH fixture on ROM a, Route 29 / Route 30 | 49788 / 55244 | none | `s29/`, `s30/` |
| R2a | ROM a, Route 29: hello + 5 encounters | 15080 | 47864 | `live/r2a/` |
| R2b | ROM a, Route 30: hunt + catch the variant form | 56360 | 36624 | `live/r2b/` |
| R3 | clean overlay / swapped contract / flipped 0x14E / flipped $1F8028 | 53280 / 53708 / 51244 / 56920 | 31528 / 44856 / 54724 / 35744 | `r3/{clean,swap,flip14e,flip1f8028}/` |

New driver pieces:
- `manager_r1.py`: the real `python -m server.manager` on a private port and `--data-dir`, driven only over HTTP.
- `harness.py`: `POL_KIND=rand` (`POL_MGR_RUN`, `POL_PLAYER`, `POL_ROM`/`POL_ROM_SHA1`, `POL_SWAP`, `POL_POS`,
  `POL_RUNNAME`). The server's data dir is the Manager run's own `rom_contract.json` + `roms/a.gbc`, `roms/b.gbc`.
- `live.lua`: `POL_MAP`/`POL_HEADER`/`POL_WALK`/`POL_EXPECT_KIND`, plus stage 5 (fled encounters, read from
  `wEnemyMon*`) and stage 6 (hunt one species/form and catch it).

## STAGE R1: the Manager path. PASS

The Manager ran with `SLINK_UPR_JAR` = the pinned jar. Calls and responses, all over HTTP (`r1_jar/calls.jsonl`):

| call | result |
|---|---|
| `GET /api/roms` | lists `Polished Crystal 3.2.3 · clean dump` (`F:/slink-work/cache/polished/release`, clean true, family `gen2_polished`). The overlay is in no ROM dir, so the pick is the release with the companion on (the Manager's UX path) |
| `GET /api/randomizer/status?rom_a=&rom_b=` | `ok`, `jar_trusted`, `jar_fork`, `jar_polished` all true. `jar_entries` lists only the Gen 1 sections, no Polished one |
| `POST /api/runs/new {game: gen2_polished}` | `run_20261004_211320` |
| `GET /runs/{id}/randomizer` | 200 (`randomizer_page.html`) |
| `POST /api/runs/{id}/cartridges` | 200 in 1.24 s. Body: `companion: true, randomize: true` and spec wild random, starters random, statics random, trainers random + rival keeps starter, trades `given_and_requested` (forms are always in the pool) |
| `GET /api/runs/{id}/rom/a`, `/b` | 2 MiB each, sha1 `0d75313f20ec83ad1827b9cf66a6b7202793db86` / `21ed1c1cf86c14ec9f496ce119874ae9569b32fc` = the contract pins |

The cartridges response:
- `source_sha1 29ea04c2...` (the overlay: `cartridges.py` applied the UPS to the release first), `base_kind overlay`.
- `write_domain {changed 8629, ups_bytes 107}`.
- Seeds `4246104770686` / `178042112491888`.
- Summary: "wild encounters random, starters random, static encounters random, trainer teams random, rival keeps their
  starter, in-game trades random given and requested".

`rom_contract.json`: `upr_version 4.6.1-slink3`, `categories [starters, statics, trainers, wild]` (trades are not a
contract category; the UPR log shows the In-Game Trades section randomized), fingerprint `""`, per-player
`rom_sha1` + seed.

**Route 29 grass on ROM a** (`polished_rom_scan.Rom(..., pinned=False).wild()`, identical in morn/day/nite):
`170 L2, 208 L2, 156 L3, 252 L3, 124 L2, 204 L3, 53 form 2 L3` (Alolan Persian, effective species 305). The vanilla
overlay has `16, 161, 16, 161, 19, 187, 187` by day and `163, 19, ...` by night. Route 30 (26:1) on ROM a has the same
Alolan Persian in slot 2 (30 %).

**Without the jar** (no `SLINK_UPR_JAR`; `find_upr_jar()` finds nothing from this worktree):
- The picker is unchanged.
- The status shows `jar ""`, `jar_found false`, `ok false`.
- `POST cartridges` returns **400 `missing: jar`**.

**With an older trusted fork jar** (`.cache/slink-upr/PokeRandoZX.jar`, 0015, sha256 `db4bc65c...`):
- The status shows `jar_trusted`, `jar_fork` and **`ok` true, while `jar_polished` is false**.
- `POST cartridges` returns 400 with `POLISHED_JAR_REFUSAL` ("Polished Crystal randomization needs SLink's UPR fork
  jar with a Polished Crystal entry for this cartridge's header checksum ...").

**Status page text (`server/static/randomizer.js`):**
- Any fork jar is described as "SLink fork jar (vanilla + pureRGB + FireRed / LeafGreen + Emerald + Polished
  Crystal)" (`:117`). That includes the 0015 jar, which cannot randomize Polished.
- The randomize refusal line then says "Randomizing Polished Crystal needs the current SLink fork jar (patches
  0016-0021)." (`:377-379`, on `jar_polished`).
- Not rendered in a browser: these strings and the API fields are the evidence.

## STAGE R2: live boot of the randomized cartridge. PASS, with one presentation gap

**Entry and server.** The entry path is the real one: `lua/slink.lua` -> `gen2/entry.lua` -> `run.lua`. The server
is `python -m server.server` with `--data-dir` = a copy of the Manager run (`rom_contract.json` + `roms/a.gbc`,
`roms/b.gbc`), the shape the Manager launches. The harness checks the ROM's sha1 against the contract pin before
every launch.

**SYNTH (O-33, disclosed).** The run 1 recipe, run on ROM a itself (`harness.py setup`).
- NATIVE: cold boot, intro, START -> SAVE.
- SYNTH, as WRAM writes between those steps: the five-mon party (CROBAT 169, JOLTEON 135, GOLDUCK 55, NIDOKING 34,
  DODRIO 85, all existing species; base stats are not randomized by this spec), 99 Poke Balls, and the position by
  the engine warp bytes (`Script_warp`'s `wDefaultSpawnpoint $FF`, `hMapEntryMethod $F1`, `wMapStatus 1`).
- Fixtures:
  - `s29`: 24:3 (48,12). sha256 `94b394d1...`, checksum `$13E4`, the same as run 1's overlay fixture.
  - `s30`: 26:1 ROUTE_30 (11,48). sha256 `942c07f1...`. (11,48) is TALL_GRASS in `maps/Route30.ablk` x8..13 under
    `johto_traditional_collision.asm`, and no trainer's sight line reaches row 48 (`maps/Route30.asm`).
  - MAPSETUP_WARP landed natively in both, with tileset 1 and 30x9 / 13x27 headers.

**Admission.**
- Client log: `[SLink-gen2] polished_crystal/polished rand_overlay PRODUCTION (DEV_OVERLAY_SHA1) player a ->
  127.0.0.1:<port> (rom 0d75313f)`.
- Parts: kind `rand_overlay`, qualification `DEV_OVERLAY_SHA1`, `production_admitted false`, `runtime_rom_sha1` =
  the contract pin.
- Hello: `artifact_kind rand_overlay`, `rom_sha1 0d75313f...`, abi 3, party 5, area `route_29` (R2a) /
  `route_30` (R2b).
- Hello timing: frame 343, after the gate (first `OWPlayerInput` 335, gate running 336).
- Server: `admission: admitted — cartridge sha1 matches the contract`, `route polished_crystal -> gen2_polished
  (production)`, `using this cartridge's own encounter tables (8 areas)`.
- **0 Lua-originated writes** in both runs (`memory.write*` wrapped before `slink.lua`). One hook:
  `capture_party`.

**Adoption: Route 29, 5 encounters, all fled** (`live/r2a/encounters.jsonl`, species = `wEnemyMonSpecies` | bit 5 of
`wEnemyMonForm` << 3):

| # | species | form byte | level | ROM a slot |
|---|---|---|---|---|
| 1 | 170 | $01 | 2 | slot 1 (170 L2) |
| 2 | 170 | $01 | 2 | slot 1 |
| 3 | 170 | $81 | 2 | slot 1 |
| 4 | 170 | $81 | 2 | slot 1 |
| 5 | 156 | $01 | 3 | slot 3 (156 L3) |

None of these is a vanilla Route 29 species. The engine gives the table's NO_FORM (0) as PLAIN_FORM (1); $80 is the
gender bit. Capture-site hits: 0 for every fled battle. The server's `/api/status` `players.a.encounter_table`
(route_29) is ROM a's table, slot for slot, ending in `{"species_id": 53, "form": 2, "name": "Persian (Alolan)",
"effective_species_id": 305, "rate": 2}`.

**Variant form: Route 30** (`live/r2b`).
- The first encounter was **species 53, form byte $02, Lv3**: the Alolan Persian of ROM a's slot 2.
- One throw caught it.
- Capture site: **1 hit, bank $03, PC $652B, SP $C0CF**, `wPartyCount` already 6 at the hit.
- New party slot: personality byte 2 = $02 (the form), DVs `39068D`.
- Client `capture`: `{"key":"39068D:D1C2:035:02","species_id":53,"level":3,"area_id":"route_30","in_box":false,...}`.
  **The key carries the form** (`:02`).
- Server: `capture key=39068D:D1C2:035:02 lv=3 area='route_30'`, `[PENDING] route_30 player=a action=add ...
  species=53`, `skip quarantine (client has no box executor)`.
- `/api/status` `pending_captures.route_30.a.key` = that key.
- The server's Route 30 table reads `(97) Hypno, (53, 2) Persian (Alolan) eff 305, Heracross, Girafarig, Scizor,
  Ivysaur, Yanmega`.

**GAP (product, not worked around): the caught variant is not presented as its effective species.**
- `pending_captures` and `party_details` show `species_id 53`, `species_name "Persian"` and the Kanto Persian sprite.
- No field anywhere carries the form or the effective species 305. `effective_species` appears in no shared server
  file.
- Causes:
  - `server/server.py:2903` calls `adapter.species_name(sid)` without the `form` it reads on the line before.
    `Gen2PolishedAdapter.species_name(species_id, form=0)` would name it.
  - The client's capture and party details carry no `form` field: the form is only inside the key.
- What this means: wherever the shared state goes by `species_id`, an Alolan Persian counts as a Persian. The owner's
  ruling is that a variant form is a different mon.

**Minor.** The `(8 areas)` in `server.py`'s adoption log line counts the 8 top-level keys of `scan_randomized`
(title, wild, fishing, ...), not areas.

## STAGE R3: refusals. PASS

All four use stage 1 only; the fixture is run 1's overlay fixture (clean) or `s29` (the rest).

| case | client | server |
|---|---|---|
| clean overlay `29ea04c2`, overlay contract | `overlay PRODUCTION (DEV_OVERLAY_SHA1) ... (rom 29ea04c2)`, hello at 343 | `admission: admitted — cartridge sha1 matches the contract` |
| ROM a with the pair's pins swapped (`POL_SWAP=1`) | admits `rand_overlay` and sends its hello (the client cannot know the contract) | **`admission: rejected — this is not the ROM built for player a (sha1 0d75313f20ec, expected 21ed1c1cf86c)`**; every reply is `{"cmd": "noop", "refused": "admission"}` |
| ROM a, byte 0x14E flipped ($72 -> $73), sha1 `87f75ccd...` | **`polished cartridge refused (production admission): unknown artifact SHA-1 87f75ccd...: its Polished SLink companion overlay is modified or incomplete (overlay beacon mismatch); prepare it through the Manager or /patcher`**; no client, no connection | no hello |
| ROM a, byte $1F8028 flipped ($C6 -> $C7), sha1 `26d62ad1...` | the same refusal, `overlay beacon mismatch` | no hello |

The flipped ROMs were temp copies under `r3/` and were deleted after the runs. The Manager's `roms/a.gbc` was never
touched.

## Run 3 commands

```
python tools/polished_live/manager_r1.py [jar|nojar|oldjar]
POL_KIND=rand POL_MGR_RUN=<lane>/r1_jar/mgr/<run> POL_LANE=<lane>/s30 POL_POS=26,1,11,48 python tools/polished_live/harness.py setup
POL_KIND=rand POL_MGR_RUN=... POL_FIXTURE=<fixture> POL_RUNNAME=r2b POL_EXPECT_KIND=rand_overlay POL_STAGES=16 \
  POL_MAP=26,1 POL_HEADER=1,13,27 POL_WALK=9,12 POL_TARGET=53,2 python tools/polished_live/harness.py live
# R3: POL_SWAP=1 (swapped pins) | POL_ROM=<flipped copy> POL_ROM_SHA1=<its sha1> (client refusal)
```

## Phone card SLink contact, Stage 1 (2026-10-04, DEV evidence). PASS

Overlay `34942315bb3e62189a56dabbcb9cef6dd3e9a9f5` (`docs/polished/PHONE_SLOT.md` "Stage 1 implementation"). The harness's
`stage_rom` checks it against `overlay_provenance.json` before every launch. Lane `F:/slink-work/lanes/pol-phone`. The
fixture is run 1's `polished_overlay_warp.SaveRAM` (sha256 `75c7a5dc...36b8`, on ROUTE_29, reached by the engine's own
warp when it was built), booted with CONTINUE (native).

**Phone run** (EmuHawk PID 49748, driver `lanes/pol-phone/drv/phone.lua` through the harness's own `launch`; 75 checks,
0 failed). SYNTH, each logged in `phone/result.txt`: `wPokegearFlags` $00 -> $87, and `wPhoneList` set per scenario
while in the overworld. Everything else is scripted native input: START -> POKEGEAR -> Right to the Phone card.

| scenario | `wPhoneList` | rows read from `wTilemap` | SLink entry |
|---|---|---|---|
| s0, 0 native | `0000000000` | `SLink:` / `   Soul Link`, then the native `----------` filler | ok |
| s1, Mom | `0100000000` | Mom, SLink | ok |
| s4, Mom/Elm/Joey/Wade | `09c0000000` | 4 natives. The 5th Down scrolls natively (cursor 3, scroll 1): Elm, Joey, Wade, SLink | ok, cursor/scroll 3/1 kept |
| s3, Mom/Elm/Joey | `0940000000` | Mom, Elm, Joey, SLink | ok, then delete + native call |

Each entry check: A on the row opens `PokegearPhoneContactSubmenu` with **Call/Cancel only (no Delete)**. Call reaches
`SlinkPhone_CallGate`, and the text box reads `SLink is linked.`. `MakePhoneCallFromPokegear` is **not** entered,
`wCurCaller` is untouched, `wPokegearPhoneSelectedPerson` = 38 (the virtual id) and `wPhoneList` is unchanged. B returns
to state $0A with the native "Whom do you want to call?", the cursor/scroll are unchanged and `▶` sits on the SLink row.
s3 then deletes Joey natively: the submenu offers Delete, the YES/NO prompt appears, YES gives `wPhoneList`
`0900000000`, and the list redraws as Mom, Elm, SLink, with exactly one SLink row and `wNumSetBits` 3. A real call to
Mom still enters `MakePhoneCallFromPokegear` (`wCurCaller` 1) and hangs up back to the Phone card. Screenshots
`phone/s*_*.png`; tilemaps and hits are in `phone/phone.json`.

**Existing stages on the new overlay** (`harness.py live`, stages 1234, EmuHawk PID 52952, server PID 31112; 0 checks
failed): admitted as `DEV_OVERLAY_SHA1`. The hello leaves at frame 343, after the first idle overworld frame (335) and the
gate (336), never from the main menu. The capture site fired exactly once on the party catch (bank 3), the box catch
reached the PC without firing it, the box census followed the battle end (-24 frames), and there were no Lua-originated
memory writes. Output: `pol-phone/live_stageA/`, `pol-phone/live_stageA.out`.

Not proven live: the entry text is fixed (no host/link status exists in the core mailbox); an incoming call ringing while
the Pokegear is open was not exercised; only English text and the CGB palette were seen. The first phone run (same
build) failed one driver expectation only. It expected an SLink row on s4's first screen, but the 5th row is below the
fold until the scroll. The driver was corrected; the ROM was not changed.
