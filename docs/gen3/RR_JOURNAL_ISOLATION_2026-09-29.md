# Gen 3 duo journal isolation (2026-09-29)

The 5a67e3f6 RR species-clause receipt caught B's new mon after a retry but had no `TX capture`; B also logged repeated trade reload holds with saved/live party-count mismatch. That receipt does not prove the journal caused the missing capture signal. It does expose a harness isolation defect: each `DuoRun` had a fresh server data directory and reseeded battery files, while the production `lua/gen3/run.lua` journal remained at the worktree root, `ROOT/slink_gen3_trade`. `SLINK_STATE_DIR` does not move this journal. The original sealed log and guard were left untouched.

This harness change selects `<DuoRun.data_dir>/slink_gen3_trade` for each ordinary Gen 3 duo **private server data identity**. A and B receive the same path, and reconnect/reset relaunches while that identity is current retain it. A retry creates another `DuoRun` and data directory. The randomized-admission control explicitly changes `data_dir` and starts a new private server mid-`DuoRun`; subsequent launches select that new directory's journal. The existing `duo_gen3_main.lua` composition wrapper intercepts only `trade_journal.file_store` and replaces its `deps.path` before the real guarded store opens; it does not change `run.lua`, file-store durability, seal checks, lock behavior, or production's default path. The runner and Lua receipt log the selected path/scope. RR reset archives now copy the actual run phase's `.log` and `.guard` from that path.

Two established owners remain separate: the native T5 candidate continues to select its validated manifest journal and archive it through its own carrier; the install-root trade-lock probe continues to use its explicitly private `SLINK_JOURNAL_PROBE_ROOT`, which its existing reader and external guard holder both require. These rows receive no ordinary duo override.

Fast RED before the initial isolation change: `python -m pytest -q -p no:cacheprovider tests/unit/test_gen3_duo_journal_isolation.py` returned `2 failed` in 0.43 s. The two-attempt launch test resolved both attempts to `C:/slink-wt/g3-int/slink_gen3_trade`, and the Lua composition helper was absent. Review then found that the helper's probe exemption depended on the scenario name. A rename-control test was RED: `1 failed` in 0.36 s, resolving a `journal_lock_probe=True` row to an ordinary private path. The exemption now reads the existing config flag. Current focused result: `python -m pytest -q -p no:cacheprovider tests/unit/test_gen3_duo_journal_isolation.py` → `8 passed` in 0.43 s. The tests launch two Python attempts with A/B and an A relaunch, check a mid-run private server data-directory change, execute both the real Lua helper and the installed `dofile` interception against a `run.lua` journal-load stand-in, and deliberately misplace the hook to show it would select the production path. They open the real sealed `trade_journal.file_store` through a fake OS file seam and independently decode both journal log/guard pairs. A pending intent remains in attempt 1 while attempt 2 is clean. Absent-override and native-candidate controls preserve their paths. The prior focused neighboring runner/native/reset result was `22 passed, 388 deselected` in 2.17 s; those paths were not changed in this correction.

No emulator or full suite ran here. The captured RR species and whiteout rows remain FAIL until fresh live reruns bind their journal path in the receipts and independently verify the intended capture and battle-faint paths. This checkpoint establishes storage isolation, not the cause of either missing product event.

## Addendum 2026-10-03: one private journal per INSTANCE (A and B no longer share a file or its guard)

The isolation above gave both instances the same `<data_dir>/slink_gen3_trade`. That was inherited from the production default (every run used
`ROOT/slink_gen3_trade`); the change was about separating ATTEMPTS, and no reason is recorded for A and B sharing. Sharing is not
production-faithful and it is not harmless: `trade_journal.lua` takes the file's OS guard on every `read()`, so while one client held it the
other's read raised LOCK_BUSY, `journal:hidden()` answered true although the journal held no record (revision 0), and the other client's
acquisition handling saw "recovery hidden" (the lost-capture of `link_gen3_rand` on Emerald, fixed in the client by 1996ba17). Production has one
journal per player on one machine; two players never contend for one guard.

Now `DuoRun._gen3_duo_journal_path(inst)` is `<data_dir>/slink_gen3_trade_<a|b>`:

- each instance keeps its own path across its relaunch phases (reload, reset) within the same private data identity;
- a new data identity (a new attempt; the randomized-admission control's `randomized_pair` directory) gets new files for both instances;
- the native T5 candidate (manifest-owned path) and the install-root lock probe keep their own paths exactly as before (the function returns None);
- the RR reset archives both instances' `.log` and `.guard` under their own names (`slink_gen3_trade_a.*`, `slink_gen3_trade_b.*`), with the same
  "missing journal" check per file.

No scenario reads the other instance's journal: the Lua wrapper receives `journal_path` per launch (each instance's own stub), and the trade
scenarios only reach the journal through their own client. The native candidate (`tools/gen3_trade_duo.py prepare_pair`) still gives both sides one
manifest-pinned path by design of that carrier; it is out of this change.


**Known shared-file exception (2026-10-03).** The native T5 trade candidate (`tools/gen3_trade_duo.py`, `prepare_pair`) still gives BOTH sides one
manifest-pinned guarded file, `slink_gen3_trade_<nonce>`. That is a deliberate carrier and is left unchanged. Unlike the ordinary duo it can therefore see
the other side's OS guard as a busy read. Since 1996ba17 a busy read HOLDS an acquisition signal (bounded, loud on expiry) instead of dropping it, so the
lost-capture failure cannot occur there either; the contention itself is covered by the client fix, not by the harness.
