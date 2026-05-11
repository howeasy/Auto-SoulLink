# lua/x64/

This directory must contain the LuaSocket native DLL for BizHawk.

## Required file

  socket-windows-5-4.dll   (BizHawk 2.9 / Lua 5.4)

## How to get it

Copy from your Archipelago installation:

  <Archipelago>\data\lua\x64\socket-windows-5-4.dll

If you do not have Archipelago installed, download from:
  https://github.com/ArchipelagoMW/Archipelago/releases
  (any release; the DLL is in data/lua/x64/ inside the install directory)

## Why it is not committed

Binary DLLs are excluded from the repository via .gitignore.
