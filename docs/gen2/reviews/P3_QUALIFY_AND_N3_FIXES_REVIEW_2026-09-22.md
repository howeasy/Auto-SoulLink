# R3 review: fixture qualification (cfbcbba) + N3 fixes (acde60f)

Reviewer: independent, not the author (card gen2-R3, 2026-09-22). Findings only; no code changed.
Sources: pokecrystal `7a7881d0` (C), pokegold `656583c9` (G), `data/gen2/*.sym`.
Worktree `codex/gen2-foundation` at `acde60f`.

Summary: 0 CRITICAL, 1 HIGH, 3 MEDIUM, 3 LOW, 2 INFO.

Both commits do what they claim. No path found where a boot, re-save or reload callback passes
while the game did something else. The GAME witness is bound to the stage fingerprint, the ROM
sha1, the exact booted CartRAM hash and the flushed re-save hash. PYDEC reads only emulator-flushed
bytes. Qualify mode performs no Lua memory write. The problems are in the re-save byte oracle: it
misses CartRAM that Gold/Silver (and in one case Crystal) rewrite, so it refuses for the wrong
reason, and it compares nothing inside the save spans. The N3-4 pre-hello queue can also replay
events into a different save identity.

## Findings

### R3-1 HIGH, CONFIRMED (source), live refusal PLAUSIBLE (likely): Gold/Silver SRAM window stack is written but not in SAVE_WRITES

- Where: `tools/gen2_fixtures.py:85-90` (`SAVE_WRITES`), `:482` `save_write_spans`, `:575` post-oracle stray check.
- Source: in Gold/Silver the menu window stack lives in CartRAM bank 0, `sWindowStackBottom 00:b800 .. sWindowStackTop 00:bfff`
  (flat `0x1800-0x1FFF`; G `ram/sram.asm` "SRAM Window Stack"; `data/gen2/pokegold.sym:30347-30348`, silver `:30346-30347`).
  `_PushWindow` opens SRAM bank 0 and writes the menu header plus tile backups there (G `engine/menus/menu.asm:438-470`).
  `ClearWindowData` zeroes `$BFFE-$BFFF` (G `home/menu.asm:712-735`), called from `StartMenu` (G `engine/menus/start_menu.asm:14`)
  and `MainMenu` (G `engine/menus/main_menu.asm:269`). Continue's `LoadStandardMenuHeader` (G `engine/menus/intro_menu.asm:254`)
  and SaveMenu with its yes/no boxes push windows as well. Crystal moved the stack to WRAM (`wWindowStack`, C `home/menu.asm:768-778`),
  so this affects Gold and Silver only.
- Failure scenario: the route's first save takes `AskOverwriteSaveFile .erase` with no second prompt. Qualification shows
  `AlreadyASaveFileText` at the same stack depth, and the save-info box shows a different play TIME. So the tile backups
  written into `$B800-$BFFF` very probably differ from the candidate. `unexpected_resave_bytes` then reports a stray run and
  `post_oracle` refuses all four Gold/Silver fixtures. The commit's own live assumption already expects this kind of report
  ("a stray-byte refusal on a real run means a missing source span").
- Repro (scratch pytest, passes): `save_write_spans("gold"|"silver")` covers no byte of `0x1800-0x1FFF`.
  Flipping `0x1FFE` gives `unexpected_resave_bytes == [(0x1FFE, 0x1FFF)]`.
- Fix direction: add `("sWindowStackBottom", ("sWindowStackTop", 1))` to a Gold/Silver-only list, next to `SAVE_WRITES_CRYSTAL`,
  with the citations above. This is scratch UI state, not save data, so exempting it hides nothing.

### R3-2 MEDIUM, PLAUSIBLE: Crystal `ClearsScratch` rewrites `sScratch[0:$20]` on every boot

- Where: `tools/gen2_fixtures.py:85-90`.
- Source: C `home/init.asm:98` calls `ClearsScratch` (`:205-213`) on every `Init`, which zeroes 32 bytes at `sScratch` (00:a000, flat `0x0000-0x001F`).
  Gold has no such routine. In both games `sScratch` is written by `DecompressRequest2bpp` (C `home/gfx.asm:121-133`),
  which `LoadBattleAnimGFX` calls (C `engine/battle_anims/helpers.asm:105-122`) for battle animations, including the send-out animation.
- Failure scenario: the battle route runs from wild battles (`lua/tests/gen2_scripted_play.lua:159`). Once one wild battle has
  happened, the candidate's `sScratch` holds decompressed graphics. The qualification boot then zeroes the first 32 bytes, so the
  re-save diff reports `$0000-$001F`. This would refuse `crystal_battle` and `crystal_battle_ot2` whenever the route met an encounter.
  Town fixtures and Gold/Silver are not affected.
- Repro: flipping `0x0000` or `0x001F` in Crystal gives a stray run.
- Fix direction: add `("sScratch", ("sScratch", 0x20))` for Crystal, citing `home/init.asm:205-213`. A scratch area, not save data.

### R3-3 MEDIUM, CONFIRMED: the re-save oracle checks nothing inside the save spans

- Where: `tools/gen2_fixtures.py:560-580` (`post_oracle_stage`).
- The allowed spans cover all of `sGameData` (primary and every backup copy), so any change inside the game data passes the byte
  diff. Inside the spans, `post_oracle` compares only `player_id` and `identity_key`. It does not compare the re-saved Ball pocket
  (`ball_items`), location/position, or party raw bytes against the original. Those are only linked through GAME witnesses read
  after the save, and the Ball pocket is not linked at all. PLAN 5.6 asks the oracle to assert "the expected scenario delta and
  untouched-region preservation". Only the second half is implemented.
- Failure scenario: a CONTINUE + re-save that loses or changes the O-10 Ball pocket, money or event flags (for example a bad
  load path or a harness regression) still yields a PASS. Its output `resave:fixture` is the artifact the chain hands forward.
- Repro: a changed `wNumBalls` byte at its primary offset (Crystal and Gold) is not flagged: `unexpected_resave_bytes == []`.
- Fix direction: in `post_oracle`, require `saved[k] == original[k]` for `location`, `position`, `ball_items` and `party_raw_hex`.
  Better still, diff the decoded game-data copies byte for byte, allowing only a source-listed set of fields a CONTINUE + save
  legitimately changes (game timer, `wRTC`/StageRTCTimeForSave bytes, options NO_TEXT_SCROLL, and so on).

### R3-4 MEDIUM, CONFIRMED (model): held pre-hello messages survive an identity change and a rewind, then replay into the new session

- Where: `lua/gen2/client.lua:81-88` (hold), `:236-246` (only `boundary()` clears the queue), `:622-625` (`on_invalidate` does not), `:701-705` (flush).
- `hello_session` invalidates itself on `identity_changed`, `identity_unavailable` and `disconnected` (`lua/hello_session.lua`), but
  `self.held` is only cleared by `boundary()`, which runs on `soft_reset`/`new_game`/`continue_confirmed` or a validate-time OT 0.
  Loading a BizHawk savestate fires none of those sites, and `clock_rewind = "keep"`.
- Failure scenario A (identity): a poison faint on save A (OT 0x1234) is held. A savestate of save B (OT 0x5678) is loaded before
  the first hello. The hello then goes out as OT 0x5678, and the held `faint` for A's key follows it. Repro: `test_n3_4_held_events_survive_an_identity_change` passes (the faint key is A's).
- Failure scenario B (same identity, LOW on its own): a pre-hello capture is held, then a savestate rewinds to before the battle.
  The hello party lacks the mon, and the held `capture` still resolves the area. Repro: `test_n3_4_held_capture_replays_after_a_same_identity_rewind`.
- Before this fix these messages reached the server before any session existed (the N3-4 defect). Now they reach it inside a
  session they do not belong to, so the queue opens a new hole rather than just closing the old one.
- Fix direction: clear `self.held` in `on_invalidate` for every reason except `disconnected`, or tag each held entry with the
  hello-session generation/identity and drop entries that do not match at flush. Also drop the queue when the frame clock
  rewinds. Clearing on `identity_changed` alone covers scenario A.
- Checked and correct: flush order (held messages first, then this frame's drained events, all after the hello in the same
  `frame_end`); no caller retries on the `false` return, so nothing is double-sent (only `send_hello` reads it); the cap drops
  the newest entry and logs it (see R3-7).

### R3-5 LOW, CONFIRMED: Python accepts the Lua-computed GAME verdict booleans without cross-checking the recorded site hits

- Where: `tools/gen2_fixtures.py:467-480`, `:628-651`.
- `validate_game_witness` trusts `continue_selected` / `native_load_completed` / `rtc_validated` as written by
  `lua/tests/test_gen2_scripted_gate.lua:649-653`. It never re-derives them from `site_hits`. It also never checks
  `site_hits.restart_clock == 0`, `site_hits.erase_save == 0`, `same_save_file >= 1` for the re-save, `save_success_counter == 0`
  for boot/reload, `harness_write_scopes == []`, `input_mode == "normal_buttons"`, or `qualified is False`. Today the gate asserts
  all of these before it writes the witness, so there is no hole now. But a regression in the gate (for example a removed Lua
  assert) would pass through the "independent" Python stage unnoticed.
- Fix direction: re-derive the three booleans in `validate_game_witness` from `site_hits`, and assert the stage-specific counters and scopes.

### R3-6 LOW, CONFIRMED: the re-saved image's map/position and party are only transitively tied to the original

- Where: `tools/gen2_fixtures.py:560-575`.
- The chain is: re-save GAME witness (WRAM read after the save) equals original, and reload witness equals re-saved PYDEC.
  Nothing compares `saved["location"/"position"/"party_raw_hex"]` with `original` directly. That makes the result depend on WRAM
  not changing between the save and the witness read. This is part of R3-3's fix. It is listed separately because it costs
  three equality checks.

### R3-7 LOW, PLAUSIBLE: pre-hello queue overflow silently loses a server-needed event

- Where: `lua/gen2/client.lua:82-84`.
- At 64 entries the newest message is dropped with only a log line. If it is a `capture`/`faint`/`party_to_box`, the server never
  sees it and nothing on the HUD says so. The hello snapshot covers presence but not transitions (area resolution, death cause).
  64 is generous for the checkpoint wait, so this is unlikely in practice.
- Fix direction: on overflow, show a HUD line as the N3-3 path does, or set a flag that forces a full rescan after the hello.

### I-1 INFO: register fakes vs BizHawk 2.11.1

- The fakes (`tests/unit/test_gen2_client.py` EMULATOR, `test_gen2_signals` Registers) expose `PC SP A B C D E F H L` and raise
  on any other name. PLAN A15 (`docs/purergb/PLAN.md:413`) also lists `ROM0 BANK`, `ROMX BANK`, `VRAM BANK`, `SRAM BANK`,
  `WRAM BANK`. Nothing in `lua/gen2/signals.lua` reads those through `io.register` (banks go through `io.bank_valid`), so the
  omission is harmless. The fake is stricter than the emulator: my understanding, not verified here, is that
  `emu.getregister` returns 0 rather than nil for an unknown name. That makes the "unavailable single is a refusal" branch
  (`signals.lua:254-261`) reachable only in fakes, which is fine.
- Latent: `register()` enforces `0..255` for every name, so a future guard on `PC`/`SP` would always refuse. None exists today
  (guards use `B`, `DE`, flags `C`/`Z`; code uses `A`, `E`, `F`, `HL`).

### I-2 INFO: docstring

- `tools/gen2_fixtures.py:613` `_boot_stage` says "Cold boot the candidate". It is a warm boot of the candidate SaveRAM
  (`COLD=0`, `_gen2_plan` warm descriptor).

## Checked and found correct

cfbcbba (qualification):
- Boot/resave/reload binding: witness `stage`, `stage_fingerprint` (the fixture_qualification digest binds attempt, fixture,
  chain, artifacts and previous receipts), `rom_sha1 == provenance`, `cartram_sha256 ==` PYDEC hash of the exact snapshot bytes
  (digest taken before the first emulated frame, `test_gen2_scripted_gate.lua` `G.qualify`). The witness file is deleted before
  each run on both sides. Reload is bound to the resave fingerprint plus the `after` hash, and re-validated in `post_oracle`
  against `resave:fixture`.
- "Landed elsewhere": map group/number and x/y from `reads.read_map` (wMapGroup, wMapNumber, wYCoord, wXCoord) are compared with
  PYDEC `_saved_field` of the same symbols (`validate_game_witness:478-479`).
- "Rejected the clock": `RestartClock` is counted, and any hit refuses (driver every step, gate at the end). `.Check2Pass` is
  reached only when `Continue_CheckRTC_RestartClock` returns nc (C `intro_menu.asm:444-457`, G `:328-341`).
- "ErasePreviousSave / other branch": `.yoursavefile` is the only same-player path (C `save.asm:181-203`, G `:169-191`). The
  overwrite text is shared with `_AnotherSaveFileText`, so the driver correctly tells the branches apart by the site hit, never
  by the screen. `erase_save == 0` is asserted. Gen 2 has one save slot. `SaveBox` writes the `wCurBox` slot, which
  `save_write_spans` takes from the original image.
- Load path: a corrupt primary would make `TryLoadSaveFile.backup` rewrite the primary silently (C `save.asm:613-628`), but the
  strict PYDEC witness on the same bytes refuses such a candidate first. `Continue_MobileAdapterMenu`/`_SaveData` do not run
  without an adapter.
- SAVE_WRITES spans that exist, against both layouts (spans computed for crystal and gold): options + check value 1, `sGameData`,
  checksum + check value 2, `sBox`, the backup options/check values, every `layout.regions` backup (Crystal one span; Gold/Silver
  five), `sStackTop`, `sPartyMail..sMysteryGiftData` (primary mail and mailboxes are rewritten by `RestorePartyMonMail` on load,
  backups by `BackupPartyMonMail`), `sMysteryGiftItem..+4` (Backup/RestoreMysteryGift), `sRTCStatusFlags` (SaveRTC /
  RecordRTCStatus), and Crystal `sGSBallFlag`/`sGSBallFlagBackup`/`sBattleTowerChallengeState`. `sCrystalData`/`sCrystalFlags` are
  correctly absent (written only by `_SaveData` via ErasePreviousSave or mobile). Gold's `sRTCHaltCheckValue` is correctly absent
  (debug room only).
- 32790/32768: `cart_ram` enforces exactly 32790 and compares the first 32768. The Lua `G.flush` asserts the length and the
  CartRAM hash. The RTC trailer is carried to the emulator (the full file is staged) but never compared.
- No Lua memory write in qualify mode: `G.qualify` never wires `o10_handler` and `Qualify.run` takes no request callback
  (`sim.writes == []` asserted in `test_gen2_scripted_gate.py:757,778`).
- PYDEC independence: `inspect_candidate` reads only BizHawk-flushed files and the staged candidate. The Lua witness supplies
  only compared values (party raw hex over the same `wPartyCount..wPartyMonNicknamesEnd` range, map, position, hashes).

acde60f (N3 fixes):
- N3-1: pairs are composed from singles (`signals.lua:254-261`) for every register guard in all three packs (`DE`, `B`, flags)
  and the evolution `HL`. No pair name reaches `io.register`.
- N3-2: supersede applies to operation starts and `change_box_begin` only, within one held operation (the latches are retired
  on `operation_changed`). The completion re-checks count, compaction and identity against the newest snapshot and consumes it
  once. I found no path that attributes a completion to a superseded attempt or publishes twice. A second completion without a
  start still hits the pre-existing hard assert, unchanged.
- N3-3: the counter is monotonic and read as a delta between `wild_ready` and `battle_end` in engine order. `battle_end`'s own
  `clear("failure")` runs before its observation is stamped, so a capture latch retired by the end of the battle is counted.
  Capture starts have no guards, so no silent guard refusal skips the count. A final-guard mismatch retires the latch through
  `invalidated`, which is counted. A client-side key/egg refusal sets `capture_refused`. Resets clear `self.battle`, and a
  rebuilt binder can only cause over-withholding (fail safe). The missed-throw control still reaches `no_catch`.
- N3-4 ordering and the reset/reload drop are as described (R3-4 covers what is not cleared).

## Tests run (one at a time, no xdist, no EmuHawk)

- `tests/unit/test_gen2_fixtures.py`: 56 passed
- `tests/unit/test_gen2_client.py`: 29 passed
- `tests/unit/test_gen2_signals.py`: 91 passed
- `tests/unit/test_gen2_scripted_gate.py`: 34 passed
- `tests/unit/test_gen2_scripted_play.py`: 27 passed
- `tests/unit/test_fixture_qualification.py`: 13 passed
- Reviewer reproductions (scratch `test_r3_repro.py`, outside the repo, importing `tools.gen2_fixtures` and the
  `test_gen2_client.World` harness): 5 passed, each asserting the defective behaviour: R3-1 (gold + silver), R3-2, R3-3,
  R3-4 A and B.
