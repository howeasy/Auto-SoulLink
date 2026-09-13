# D0-S scripted selected idle — physical PASS

Run run_20260913_195515_9e4d11, runtime609393fa512a849ea3b5f2ae318baafb, began 2026-09-13 19:55:15 UTC on HOUNDOOM. Source/test cut6283d58, invocation HEAD e7161be, product behavior15727ec. The tracked idle coroutine ran with input_mode=scripted-normal-buttons, launch_mode=scripted-selected-launcher and limit480. Unified session19551 completed exit0 (tool55b47e).

Both fresh Yellow games completed New Game using the Lua button script. There was no human input, Computer Use, OS input, test RAM/register/SaveRAM/savestate staging, or restored performance-memory probe. The script inspected menu state read-only and supplied joypad buttons on the existing client's owned boot-frame calls.

## Physical assertions

- Both drivers reported input-stopped at emulator frame3501 after3500 driven boot frames; the wrapper cleared inputs and restored only its own hooks.
- Both native reattach records were released/clean with held host identities matched to the captured EmuHawk processes. Both initial observations, bootstrap records and checked initial-save ACKs were present.
- Service was current and both command queues empty at the audited boundary. Normal observation counts were zero, expected for an unchanged idle bedroom.
- Both separate private game.SaveRAM files were32768 bytes, matched their flushed/readback receipts and each player's own prepared initial-save image. Both happened to have SHA256 `abdc79629f72608bc0936a334a9e4af0880dbedd05d19eaf1a3a4c93bca53ea6`; equal hashes do not substitute for separate paths/ownership. Root independently reread both files after exit and compared them with prepared() from a checked read_journal snapshot (tool66d6ca, exit0).
- The unchanged downloaded launcher and ROM passed product preparation checks. The test host substituted only --lua=scripted_new_game.lua and recorded wrapper SHA256 `cd8c8e3d7128749332ab6c15bc8ba8c96c6c82a2b9231212d392e5b30045ad61`, launcher hashes, actual argv and private environment.
- Captured helpers48720/47228 and EmuHawk14640/37336 all exited; survivors, unknown-survivor state and resource-cleanup errors were empty. Root's post-run census found no EmuHawk. Original config before/after remained SHA256 `92ca34c62c4db6ed25df2edc4bd1e1c519790c1f3a894623570eb99d914592d6`.

## Frozen receipts and limits

Summary .cache/d0-s-scripted-summary.json SHA256 `ffa5cf5118affa9e598d726e26c42b042f4e80eae9c94ae63e08572ac22eaaab`; console .cache/d0-s-scripted-console.txt SHA256 `e0f2a9cd97c8b659143e6a78d8ad8f1041ec497f8f2fce53dd1fbb7cde6b2bf1`. The summary contains enrollment.document, enrollment.players (private plans/driver markers), enrollment.evidence (checked events/files/service/queues), source/input hashes and cleanup.

This is controlled-scripted selected-launcher evidence. It is not the product-CLI invocation; that baseline remains the separate accepted N0 R2 receipt. It does not qualify FPS, ordinary observation traffic, first-ball activation, native trade/recovery, the title matrix, reset/cross-write sentinels, or release readiness. No manifest row was registered or closed by this run.
