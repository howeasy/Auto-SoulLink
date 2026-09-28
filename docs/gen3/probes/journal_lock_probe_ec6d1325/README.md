# RR journal lock contention — development probe

This is a **development physical probe**, not a final-cut qualification. Both EmuHawks used the
private installed root `C:/slink-wt/journal-probe-lane` at source `ec6d1325`; the companion
ROM's SHA-1 was `da579690db7d6933a0952a1f490312842793f71a`. The runner exited 0 on its
first attempt. `manifest.json` gives the SHA-256 and original path of every raw artifact here.

An external PowerShell process (PID 11760) held only the OS-exclusive handle on that root's
`slink_gen3_trade.guard` from 2026-09-28 12:06:36.004Z until 12:06:36.365Z. The controller
waited for the holder process to exit before releasing either client. A and B each recorded an
actual production hidden tick at emulator frame 900, then a visible party tick at frame 990,
without restarting either EmuHawk. Server status independently showed both parties hidden,
then recovered. The RR native trade completed with the linked keys swapped; the sealed raw
journal ended at revision 6, counter 2, and zero records.

The existing Python trade oracle decoded both independent saved flash images, found the
partner's intact record on each side, and verified the server's re-keyed link. Each save-hook
witness matched its flushed battery byte for byte; native pre-save, native post-save, and the
ordinary final save advanced each cartridge's counter from 4 to 7. The RR extension also
matched live RAM in each witness.

**Evidence boundary:** the controlled OS-hold leg physically exercises journal **read**
contention and same-session recovery before an ordinary native trade and terminal retirement.
Forced busy `trade_final`, `native_saved`, and precommit/scene caller retry paths were verified
by unit models and the installed NLua/CLR host seam, not forced in this emulator run. A final-cut
rerun on the integration head remains required. No guard or journal bytes were changed by the
external holder.
