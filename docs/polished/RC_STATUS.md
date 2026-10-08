# Polished Crystal — RC status

Machine-checkable. Everything below is the output of one command:

```
python tools/verify_polished_release.py            # every item
python tools/verify_polished_release.py --list     # ids and kinds, runs nothing
python tools/verify_polished_release.py --only LIVE-PHONE-ENTRY
```

The manifest is `tests/polished_release_requirements.json`; the committed emulator receipts are
`tests/fixtures/polished/receipts/*.json`; the runner is `tools/verify_polished_release.py`.

**Why a separate lane.** `tools/verify_gen2_release.py` is not touched and must not be.
`tests/unit/test_polished_release_guards.py` pins its `TITLES` to `("crystal", "gold", "silver")`
and its `DUO_PAIRS` to vanilla pairings, which is correct: Polished Crystal is a SOLO title with
no vanilla partner, so it has no duo matrix, no second fixture and no per-title live-gate set.
Appending it to `TITLES` would put a partner in every pairing that does not exist.

---

## 1. Verdict: NOT AN RC CANDIDATE

The gate is red, and every red is a real reason. None of them is the verifier being fussy.

| # | Red | Why it is red | Who clears it |
|---|---|---|---|
| 1 | four OPEN items (one CLOSED) | `OPEN-WRITE-PATH`, `OPEN-EXPLODE-RIVAL`, `OPEN-PANEL-PAGES`, `OPEN-IN-GAME-TRADE` are `status: OPEN, blocking_rc: yes`; `OPEN-TITLE-SPLASH` is CLOSED by `LIVE-TITLE-SPLASH` (2026-10-08) | the owning cards; each needs a `closed_by` LIVE receipt to flip |
| 2 | three SOURCE cells red | `gen_polished_engine_sites`, `gen_polished_pack` and `gen_polished_profile` `--check` all fail | see §2 — this is a real commit-consistency defect, not an environment artefact |
| 3 | five LIVE cells STALE | they ran overlay `29ea04c2`; the phone-card commit republished the overlay as `34942315` | re-run those five scenarios on the current overlay |
| 4 | two BUILD cells | a full rgbds build; see §4 | the build host |
| 5 | two MODEL cells red | `test_polished_lua.py` (1 failed), `test_gen_polished_engine_sites.py` (1 failed), `test_polished_rom_tables.py` (1 unexplained skip) | see §2 — the two failures are the same defect as row 2; the skip is a missing clone |

Green today: all 4 MANAGER gates, 4 of 7 SOURCE cells, 4 of 6 MODEL cells, 6 of 11 LIVE cells
(the six bound to `34942315…`), and the RELEASE ZIP.

**MODEL detail.** `MODEL-RELEASE-GUARDS 2/2`, `MODEL-RANDOMIZER 7/7`, `MODEL-PHONE 1/1`,
`MODEL-WRITES 5/5`. The two red cells:

* `test_polished_lua.py` — `1 failed, 23 passed`. The assertion is
  `lock_sha256 658caa2a… == 0585f64c…` — the CRLF artefact of §2.
* `test_gen_polished_engine_sites.py` — `1 failed, 19 passed`, and this one carries **both**
  digests: `lock_sha256 658caa2a… vs 0585f64c…` **and**
  `build_provenance_sha256 f376ca44… vs d590e33a…`. The second half is checkout-independent.
* `test_polished_rom_tables.py` — `SKIPPED [1] …: pokecrystal not cloned:
  F:\slink-work\wt\pol-verify\.cache\gen2-build\pokecrystal`. An unexplained skip, so the cell is
  red: the ROM tables are unverified here. Clone `pokecrystal` and re-run, or record why the
  vanilla clone is not needed for a Polished RC.

---

## 2. The three red SOURCE cells are one real defect

`gen_polished_engine_sites.py --check`, `gen_polished_pack.py --check` and
`gen_polished_profile.py --check` all fail, and all three fail on the same two digests.

The committed packs record:

```
data/games/polished_crystal/engine_signals.json : "lock_sha256": "658caa2aeaae…", "build_provenance_sha256": "f376ca44f94d…"
data/games/polished_crystal/profile.json       : same two values
data/games/polished_crystal/charmap.lua         : same two values
```

The committed files actually hash to:

```
sha256(data/polished_sources.lock.json)          LF form 658caa2aeaae…   CRLF form 0585f64c2e55…
sha256(data/polished/build_provenance.json)       LF and CRLF alike d590e33adf0d…
```

**`build_provenance.json` is the real drift.** It hashes to `d590e33adf0d…` at every commit since
`b2ea20a5`, while all three packs record `f376ca44f94d…`. So the check fails in ANY checkout,
including the canonical one. This is a committed-packs-vs-committed-inputs inconsistency at
`c9f1ad14`, and it is exactly the class of thing the gate exists to catch.

**`polished_sources.lock.json` is a worktree artefact, and it is worth knowing about.** With
`core.autocrlf=true` (this worktree's setting) the working-tree copy is CRLF, so it hashes to
`0585f64c…` instead of its blob's `658caa2a…`. In a checkout that normalises to LF this half of the
diff disappears. So:

* the `lock_sha256` half of these three failures is checkout-dependent — do not report it as drift;
* the `build_provenance_sha256` half is real and must be fixed by re-running the three generators
  (`gen_polished_engine_sites.py`, `gen_polished_pack.py`, `gen_polished_profile.py`) and
  committing what they write.

`tools/check_release_zip.py` already normalises CRLF before hashing (its `_norm`), which is why
the ZIP gate is unaffected. The generators do not.

---

## 3. LIVE: six cells bind to the current overlay, five are STALE

The phone-card commit (`c9f1ad14`) republished the overlay from `29ea04c2…` to `34942315…`.
A receipt binds only to the overlay `data/polished/overlay_provenance.json` publishes today.

Bound and green (`34942315…`):

| item | evidence |
|---|---|
| `LIVE-HELLO-ADMITTED` | `pol-phone/live_stageA/result.txt` + `server.log` |
| `LIVE-HELLO-GATE-FRAME` | `pol-phone/live_stageA/result.txt` + `gate_transitions.log` |
| `LIVE-CAPTURE-PARTY-ONLY` | `pol-phone/live_stageA/result.txt` |
| `LIVE-BOX-CENSUS` | `pol-phone/live_stageA/result.txt` |
| `LIVE-NO-BOX-MON` | `pol-phone/live_stageA/server.log` (`skip quarantine: … client has no box executor`; the string `box_mon` occurs 0 times) |
| `LIVE-PHONE-ENTRY` | `pol-phone/phone/result.txt` — 75 `[ok]`, 0 `[fail]`, `RESULT: PASS pol-phone (0 checks failed) frame 2815` |

STALE (`29ea04c2…`, must be re-run):

| item | evidence | what a re-run has to redo |
|---|---|---|
| `LIVE-R1-MANAGER-PAIR` | `pol-rand/r1_jar/summary.json` | re-randomize the pair from the new overlay |
| `LIVE-R2-RANDOMIZED-BOOT` | `pol-rand/live/r2b/result.txt` (+ `r2a`) | boot, table adoption, the variant-form key |
| `LIVE-R3-REFUSALS` | `pol-rand/r3_swap.out` (+ the three siblings) | both refusal layers against the new beacon |
| `LIVE-RECEPTIONIST-STACK` | `pol-live2/x/explore_B/result.txt` | the trade receptionist frame-wait stack |
| `LIVE-POKEGEAR-MEASUREMENT` | `pol-live2/x/explore_C/result.txt` | the Pokegear icon strip |

The R1/R2/R3 rows bind on `source_overlay_sha1`, not on the booted cartridge's own sha1: a
randomized cartridge can never equal the overlay sha1, so binding on it would be red forever.
The item declares `"bind": "source"` and the receipt carries the overlay it was derived from.

### 2026-10-08: four receipts bound to `68894579` and to a computed code digest

The overlay is now `688945795e2656019247f5aaceb7b1d8791e900a` (title wordmark, `1d750de2e`), so
every receipt above is STALE on the ROM binding. Four new DEV receipts were written against it,
and unlike the older ones they carry the code digest the verifier computes
(`--print-code-digest` = `f8966ea4…`), checked on the run worktree at `2959ee36a`:

| item | evidence | what it does NOT prove |
|---|---|---|
| `LIVE-TITLE-SPLASH` | `pol-rcproof/title/evidence.json`: overlay PASS, clean-ROM control FAIL (15 reasons) on the same judge | DMG; save/main-menu variants |
| `LIVE-WRITES-OVERWORLD` | `pol-writes6889/writes/result.txt`, 45 `[ok]`; a/b/d exact diffs recomputed from `trace.json` | (c) negatives; in-battle/PHYSICAL faint; bank 2 |
| `LIVE-PANEL-PAGES-ROM` | `pol-rcproof/panel/run/result.txt`, C0-C5, 21 `[ok]` | pages from the real host (a scripted writer published them) |
| `LIVE-PANEL-HELLO` | `pol-rcproof/hello/live/wire/wire_a.jsonl:2`: `panel true`, `panel_abi 3` | paging |

`OPEN-TITLE-SPLASH` is CLOSED by `LIVE-TITLE-SPLASH`; the verifier re-checks that closure on every run.

### Every receipt is DEV, and cannot promote itself

The receipt schema accepts `grade: "DEV"` only. A lane author writing a receipt cannot mark their
own run as a PHYSICAL release receipt; that is an owner act and belongs in a different record.
The clients also still self-report `qualification DEV_OVERLAY_SHA1`, `production_admitted false`,
and `signals.lua` names itself unproven on the capture site. The receipts say so rather than
rounding it up.

### `code_digest` is UNRECORDED everywhere, on purpose

A case-insensitive search of all four lane directories for `digest`, a commit id, or `git` finds
nothing: the lanes print the ROM sha1, not the tree. `docs/polished/LIVE_RESULTS.md` names
`78dddd8b`, `e0fd92dd` and `c9f1ad14` for its runs, but a narrative claim is not evidence, so the
receipts carry the explicit string `UNRECORDED` and a note saying which doc made the claim. This
is the one field an RC should insist on next: make the harness print the production code digest
(the way `tools/gen2_code_digest.py` computes it for Gen 2) so a receipt can bind to a tree.

### Run this on the lane host

The receipts are transcriptions. The verifier re-hashes each `evidence_file` and a mismatch is
red — but a file that is **not reachable** is red too, deliberately. On a machine without
`F:/slink-work/lanes`, all eleven LIVE cells read `evidence file not reachable`. That is the gate
working: a transcription nobody can check is not evidence. Run the RC on the lane host.

---

## 4. BUILD: the two rebuild cells do not finish here

Both are full `rgbds` builds of the pinned v3.2.3 ROM and then of the overlay.

* `BUILD-CLEAN-ROM` (`tools/build_polished_syms.py --check`) — runs past the 300 s ceiling of the
  command runner this lane used. The verifier's own budget is 1800 s.
* `BUILD-OVERLAY` (`tools/build_polished_companion.py --check`) — exits 1 in ~3 s with
  `OSError: [WinError 145] The directory is not empty: F:\slink-work\cache\polished\companion-clean\gfx\pokemon\electrode_plain`
  raised from `shutil.rmtree(build_dir)` at `tools/build_polished_syms.py:99`.

That second one is a **Windows filesystem condition in a shared cache**, not a byte comparison:
the tool never reached the comparison. It also means the tool mutates shared state outside the
worktree (`F:/slink-work/cache/polished/companion-clean`), which two lanes cannot do at once.
Run these two on the build host, sequentially, and clear the cache first if the rmtree races again.

---

## 5. What the OPEN list is protecting

| item | Manager row it is bound to | why it blocks an RC |
|---|---|---|
| `OPEN-WRITE-PATH` | none (no Manager option governs the write sink) | overworld half live on `68894579` (`LIVE-WRITES-OVERWORLD`) and `supports_box_mon` is True since `8c1b841e2`; still no in-battle (active battler) / PHYSICAL faint receipt and no (c) negatives under a real battle |
| `OPEN-EXPLODE-RIVAL` | `explode_mode`, `rival_team_swap` | both writers exist as pure Lua modules and neither is wired |
| `OPEN-TITLE-SPLASH` | none | **CLOSED** 2026-10-08 by `LIVE-TITLE-SPLASH` |
| `OPEN-PANEL-PAGES` | none | ROM half (C0-C5, scripted host) and hello `panel=true` live on `68894579`; real-host paging (server `link_panel` -> lua `panel:hold` -> ROM) not yet run live |
| `OPEN-IN-GAME-TRADE` | `pc_trade_npc` | the receptionist stack is measured, but no dispatch is armed; the native path stops at `Special_WaitForLinkedFriend` |

Where an item names a Manager row, the verifier cross-checks that the row is **still refused**.
If someone flips `OPTION_SUPPORT['explode_mode']['gen2_polished']` to `ok=True` while
`OPEN-EXPLODE-RIVAL` still reads `OPEN`, that is a disagreement and the item goes red. Where an
item has no Manager row the check is silent rather than invented — `overworld_presence` has no
`gen2_polished` cell at all, and binding the title splash to it would assert something the
Manager never claimed.

---

## 6. Owner decisions this RC still needs

1. **Re-run the five stale LIVE scenarios on `34942315`,** or record a signed disposition that
   they do not need re-running. The five are listed in §3.
2. **Re-run the three generators** whose `--check` is red and commit what they write, or record
   why `build_provenance.json` is allowed to move under the packs. See §2 — this one is a defect,
   not a judgement call.
3. **Decide the write path.** Without `OPEN-WRITE-PATH` there is no Soul Link: a linked mon
   cannot be fainted on the partner's behalf. Every other OPEN item is polish by comparison.
4. **Say whether DEV evidence is acceptable for an RC.** The gate does not decide this. It
   refuses to let a receipt call itself PHYSICAL, and it prints the grade in every row, but the
   call is the owner's.
5. **Make the harness print the production code digest.** Without it no receipt can bind to a
   tree, and every one of these eleven carries `code_digest: UNRECORDED`.

---

## 7. Reproducing

```
python tools/verify_polished_release.py --list
python tools/verify_polished_release.py --only SRC-ENGINE-SITES --only LIVE-PHONE-ENTRY
python -m pytest tests/unit/test_verify_polished_release.py -q      # 49 tests, the rules
```

The lane host must have `F:/slink-work/lanes`, `F:/slink-work/cache/polished/release`,
`F:/slink-work/cache/polished/src` and the pinned jar at
`F:/slink-work/cache/polished/jar/PokeRandoZX.jar` for the cells that read them.
