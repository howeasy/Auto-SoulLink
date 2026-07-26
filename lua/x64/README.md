# lua/x64/

Holds the LuaSocket native DLL that BizHawk's Lua needs in order to open a TCP
socket. Without it the client cannot talk to the server at all.

## Nothing to do

  socket-windows-5-4.dll   (BizHawk 2.9+ / Lua 5.4)

**This file is already in the repository** — it is committed and not gitignored,
so a fresh clone has everything it needs. Earlier revisions of this README (and
of `docs/REFERENCE.md` and `tests/TESTING.md`) said it was excluded and told you
to copy it out of an Archipelago install. That was wrong, and it read as a hard
blocker to anyone who did not have Archipelago.

## If it ever goes missing

Any Archipelago release ships the same DLL at
`<Archipelago>\data\lua\x64\socket-windows-5-4.dll`
(https://github.com/ArchipelagoMW/Archipelago/releases), or restore it with:

    git checkout -- lua/x64/socket-windows-5-4.dll
