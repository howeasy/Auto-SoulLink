# LIVE_WRITES — card POL-LIVE-WRITES (integrated overlay `deebb100`)

**Status 2026-10-05: LIVE (a), (b) and (d) PASS on the integrated overlay; (c) negatives NOT RUN.**
Command: `POL_STOP_AFTER_D=1 python tools/polished_live/writes_run.py` -> `RESULT: PASS pol-live-writes (0 checks failed)`
(overlay `6e43f8d9`, fixture `75c7a5dc`; driver commit `d385e10e7`). (d) is the Polished withdraw executor
(`party_mon`) against a real cartridge: it is **bank 1 only** (the entry was in pokedb bank 1, so the Banks bit
starts and ends 0 and (d3c) proves "no other bit moved", not a bank-2 transition), one mon, one fixture.
Everything below the table is the earlier boot-only record, kept as history. The older text claiming a/b/c "NOT RUN"
applies to run 1 only.

| artifact | sha |
|---|---|
| staged ROM `lanes/pol-livew/rom/pol_writes.gbc` | sha1 `deebb1004d4f6123667d5d9e061ad0bf867ac021` (= `lanes/g2int-ov/drv/mkrom.py`'s figure; `writes_run.py` refuses otherwise) |
| run log `lanes/pol-livew/writes/result.txt` | sha256 `eb6c7c04a1f5ecded09d8aab52f2679a6c54d21561d7adf040ad7da397a6b39f` |

Reproduce: `python tools/polished_live/writes_run.py`.

## What PASSED

```
[ok] the composition has the overworld write path
[ok] the composition has the box executor
parts: pack polished_crystal kind overlay sha1 deebb1004d4f6123667d5d9e061ad0bf867ac021;
       overworld writer=true boxes=true
```

The merged Polished write path is really composed by the real entry path on the integrated
overlay: `lua/gen2/entry.lua` `compose_polished` returns
`overworld={checkpoint=…, writes=…, boxes=…, census=…, coords=…}` (`entry.lua:904`) and hands the
client `writes=explode.writes, boxes=boxes, safety=explode.safety` (`entry.lua:880`). That is the
fact this card most needed established before any command could be queued, and it is established.

## What did NOT run, and why

```
[writes] CONTINUE did not reach the overworld after 2502 frames:
         {"battle":0,"map":0,"party":0,"paused":0,"saved":0,"script":0,"xsav":0}
[FAIL] CONTINUE did not reach the overworld
RESULT: FAIL aborted (1 checks failed) frame 2502
```

Every gate byte is zero at frame 2502: `wSavedAtLeastOnce = 0`, `wSaveFileExists = 0`,
`wPartyCount = 0`, `wMapStatus = 0`. **The save was not read** — the cartridge booted as a fresh
new game, which is the state the coordinator's screenshot showed (the Options screen looping). With
no save there is no party, so no `force_faint` key, no box deposit and no meaningful negative
control.

| check | result | evidence |
|---|---|---|
| composition has the overworld writer + box executor | **PASS** | `result.txt` lines above; `entry.lua:880,904` |
| (a) `force_faint` on a non-active slot: HP 0/0, status 0, count unchanged, EXACT diff (+ wrong-set control) | **PASS** | `result.txt` (a1)-(a5c) |
| (b) `box_mon`: slot removed, Entries pointer set, pokedb 49 B written + allocation flag moved, checksum verifies | **PASS** | (b0b)-(b5); the Banks bit is the bank SELECTOR (0 = bank 1), not an occupied flag |
| (c) negatives: no write while in a battle / while a script runs | **NOT RUN** | gate pokes wedge the frame loop; needs a real battle |
| (d) `party_mon` withdraw: appended last, HP == MaxHP, status 0, Entries $01->$00, pokedb entry + flag UNCHANGED, EXACT diff, other mons identical, wrong-set control fails | **PASS** | (d0)-(d6), (d5c) |

## Two harness defects found and fixed (both from the coordinator's screenshot)

1. **The client was dialing a TCP server that did not exist.** The real client connects on
   `start`, so `connector.lua` retried forever and the boot never settled. Fixed: `writes_run.py`
   now starts the harness's own server exactly as `harness.cmd_live` does
   (`server.server` on a free port with a `rom_contract.json` pinning the staged sha1), passes
   `SLINK_HOST`/`SLINK_PORT` to the driver, and kills **only its own server PID** in a `finally`.
2. **The ROM stem / SaveRAM name.** `harness.SAVE_NAME` is `"pol overlay.SaveRAM"`, which is not
   derived from the staged ROM. `writes_run.py` now copies the fixture as `<rom stem>.SaveRAM`
   and prints the name it used. **This fix did not resolve the boot** — see below.

Also added per the card's instruction: a hard frame cap that calls `L.finish`
(`POL_FRAME_CAP`, default 4500), a 2500-frame abort on the overworld, and the emulator is killed
only by the PID `harness.launch` started. `Get-Process EmuHawk` was checked after every run.

## The remaining blocker, stated exactly

**The fixture save does not load into `pol_writes.gbc`, and I did not establish why.** What I
know:

- The source fixture exists and is copied: `F:/slink-work/lanes/g2int-ov/live/sram_overlay/pol overlay.SaveRAM`
  → `lanes/pol-livew/fixture/pol_writes.SaveRAM`, sha256 printed by the runner.
- The ROM is byte-identical to the one that produced that save (same sha1 `deebb100…`), so a
  hash-keyed save name should match.
- Neither the harness's name (`pol overlay.SaveRAM`) nor the stem-derived name (`pol_writes.SaveRAM`)
  produced `wSaveFileExists = 1`.

**What would settle it, in order of cost:** (1) take the SaveRAM file that `harness.py live` itself
used in a *passing* run — `lanes/pol-livew` has none, so copy the one the integrated live run used
under its exact run dir and re-stage with that filename; (2) dump `BizHawk``'s resolved save name
at boot (the harness's `write_run_config` + a one-line log of `client.getgameinfo()`/the save path)
rather than guessing the stem; (3) as a control, run `harness.py live` in this lane — if *that*
also fails to reach the overworld, the fixture is the problem, not this driver.

## Notes for whoever picks it up

- The command path **is** drivable exactly as the card hoped: `Client:handle_command`
  (`lua/gen2/client.lua:535`) is public, handles `force_faint` (`:545`) and dispatches
  `box_mon` through `defer_held` → `run_box` (`:1088`). No client change is needed — the blocker is
  the fixture, not the API.
- `writes.lua` reads party keys from the client's own read path
  (`parts.reads:read_party(true)` + `parts.wire.mon_key`) precisely so no hello/TCP peer is needed
  for the command itself.
- The write tap covers the same `memory.write_*` list `live.lua` uses, so "only the declared bytes"
  will be measured once the boot works.