# N0-root-successor candidate handoff

2026-09-13 14:03 UTC; implementer `/root/n0_root_impl`, host HOUNDOOM; coordinator Codex task `01a09ae0-ad6f-7b01-8753-5e6b71eb1cfa`. Candidate is frozen for independent Standards/Spec review. The implementer has not reviewed, accepted, committed or integrated it.

## Claim and checkout

The [nine-part N0-root claim](../RC_MASTER_GUIDE.md#n0-root-successor-implementation-claim--ready) supports N0 and `manager.yellow.yellow.same-hash`. It closes neither the physical launch card nor that requirement. Exact checkout: `E:/Google Drive/SLink/.claude/worktrees/gen1-rby-code-sweep-8d06e2`, branch `gen1/rc`. ACK was clean HEAD `207b8da49f15044db14f1f0b3b8c68efefd42017`; ACTIVE grant was committed at `95584e62cd834bc3479a18608af42392ef189ab4`. Final checked documentation HEAD is `51c339dad0a9d703c26717c4707599d673068a3d`; production baseline remains `19edbb2` plus this uncommitted candidate.

Exclusive changed files are `server/runtime_launcher.py`, new `tests/unit/test_runtime_launcher_root.py`, and this report. The assigned ignored receipts are `.cache/n0-root-successor.txt` and `.cache/n0-root-successor.xml`. No other source, test, guide, register, dependency, root-master or emulator change was made. Pytest used owned fixtures below `C:/Users/howar/AppData/Local/Temp/pytest-of-howar/`; no persistent runtime fixture was introduced.

The installed ask-matt configuration routes this bounded claim to implement/TDD at the already accepted rendered-output seam. TDD test/mocking guidance and writing-for-agents were read. The coordinator owns the independent review, frozen full-suite assignment and eventual commit; the generic implement defaults do not grant those steps to this author.

## Source change and execution boundary

`server/bizhawk_launch.py:107` supplies the child `SLINK_ROOT`. The old rendered launcher never consumed it. Five added lines at `server/runtime_launcher.py:85` read that environment after a valid explicit hint and before cache/relative/dialog discovery. Nonempty values normalize backslashes and trailing separators before the existing entrypoint-existence check; empty/missing/invalid values continue through existing fallbacks. The existing full closure hash loop, cache write and checked entry execution remain unchanged.

The tests call public `file_bundle` and `render_launcher`, write the unmodified generated script, and execute it with `lupa.lua54.LuaRuntime` through real `dofile`. Lua `debug.getinfo`, `io`, script loading and entry/dependency execution use real temporary files. Only the process environment and .NET crypto/UTF8/dialog boundary are modeled. SHA256 uses Python hashlib over actual bytes; the UTF8 adapter decodes strictly. The fixture entry returns the root, launch JSON and an executed dependency. It is a minimal checked-client fixture, not the production game client.

The first case places the script four private directory levels away from the temp parent, separate from an installation with spaces. It supplies a Windows backslash environment path with a trailing separator, no hint and no cache. Positive assertions require exact root normalization/configuration, dependency execution, zero constructed dialogs and the written root cache.

## Red, green and regression receipts

Python: `C:/Users/howar/AppData/Local/Programs/Python/Python312/python.exe`, 3.12.10; direct Lua runtime check returned `Lua 5.4`. `PYTHONDONTWRITEBYTECODE=1` was process-local throughout tests. Complete new-file command at each step:

```text
python -m pytest tests/unit/test_runtime_launcher_root.py -q -ra -p no:randomly -p no:cacheprovider -o addopts=
```

1. **Old-code red before any production edit:** 1 failed, exit 1, 0.33s. Actual rendered Lua failed with `SLink project folder is unavailable` at launcher line 31. The first fixture path was `C:/Users/howar/AppData/Local/Temp/pytest-of-howar/pytest-2306/test_private_launcher_uses_env0`. This supported the missing-environment premise.
2. **First green after environment lookup:** 1 passed, exit 0, 0.24s.
3. Precedence regression: 3 passed, 0.26s. Fallback regression: 9 passed, 0.30s.
4. While adding refusal cases, two positive assertions were accidentally inserted into the refusal test: 6 failed with `NameError`, 9 passed, 0.50s. The trace is retained. This was a test-authoring error, not additional product-red evidence. Restoring those assertions to the positive test produced **15 passed**, exit 0, 0.41s.

The final complete focused command used the two accepted P0 child-process environment values `SLINK_EMUHAWK=E:/Howard/Bizhawk/EmuHawk.exe` and `SLINK_UPR_JAR=E:/Google Drive/SLink/.cache/upr/PokeRandoZX.jar`:

```text
python -m pytest tests/unit/test_runtime_launcher_root.py tests/unit/test_runtime_launch_core.py tests/unit/test_runtime_launcher_closure.py tests/unit/test_gen1_launcher.py tests/unit/test_gen1_launch_bundle.py tests/unit/test_bizhawk_launch.py tests/unit/test_manager_launcher.py -q -ra -p no:randomly -p no:cacheprovider -o addopts= --junitxml=.cache/n0-root-successor.xml
```

**67 passed, exit 0, 2.88s; zero failures, errors, skips, xfails or deselections.** XML contains 67 cases: new root 15, shared core 13, closure 1, Gen1 launcher 19, bundle 2, BizHawk launch 13, Manager launcher 4. Raw combined output retains each earlier red/green execution separately. Ruff on the two source/test files passed; `git diff --check` exited 0 (only Git's LF-to-CRLF advisory).

The 15 new cases cover hint before environment, environment before stale cache/relative roots, absent/empty/nonexistent environment with cache and three-parent fallback, and six tamper refusals (entry/dependency/binary, selected by hint/environment). Every tamper case verifies no entry execution, no dialog, byte-identical existing cache, and no hash reads from the available valid alternative installation.

## Frozen identities

SHA256 values below hash raw bytes, except the explicitly identified Git source/diff streams.

| Item | SHA256 |
| --- | --- |
| Baseline `git show 19edbb2:server/runtime_launcher.py` (LF) | `a7a45d41da7aa215f0a35a8c9e07d0896290c2ed81cfc89d50d218cd8d3c4269` |
| Candidate `server/runtime_launcher.py` | `8444a3aa3b2de6ff401babef3c23a0e9a90629dd60f1cb9a966395a179ef94e1` |
| New `tests/unit/test_runtime_launcher_root.py` | `ff410dced32da7f368f24e12d4f1166beb95262b2cee8a612bf4c48c9c69a0ad` |
| `git diff --binary HEAD -- server/runtime_launcher.py` stdout | `9dbd3b9678793281f3bb53ffd1ac8ecc1a6cd9a85e1b035978c517a0c5d82a94` |
| `.cache/n0-root-successor.xml` | `c56ca93cd55e85bcc730e28a91545a63a385ca17d3532bed743a85ba8fa7090d` |
| `.cache/n0-root-successor.txt` | `bb986decd5ff07f56b838a890ff59c1ebfc53903f0f96841be54db789b194c13` |

## Evidence limits and next ownership

**MODEL ONLY.** Actual Lua execution validates the renderer against modeled .NET/process boundaries. No actual CLI subprocess, BizHawk environment bridge, production client startup, held enrollment, gameplay or physical file receipt was executed. The renderer's production import sites are `server/gen1_launcher.py:5,78` and `server/manager.py:728,736`; a repository source search found no direct Gen2/Gen3 renderer consumer. The generic checked-closure machinery and legacy Manager launch path are unchanged and covered by the assigned shared/Manager tests; this is not Gen2/Gen3 gameplay qualification.

Next owner: coordinator freezes these file/receipt hashes and assigns independent Standards and Spec review. After reconciling findings, the coordinator controls integration and the separate full suite. Actual CLI physical N0 evidence, manifest proof refresh and release acceptance remain separately owned and open. Writer ownership is released with this frozen handoff.
