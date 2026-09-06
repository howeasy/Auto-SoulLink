# Shared BizHawk SaveRAM persistence

lua/platform_saveram.lua writes through the source-pinned host SaveRAM API,
checks its actual destination, explicitly flushes the resulting file handle to
disk and compares the complete file bytes with caller-supplied expected bytes.
It has no generation addresses, codec, network, journal or frame actuator.

The current live caller is the RBY native trade client integration. Other
generations can reuse it with their complete host SaveRAM serialization and
their own cartridge/save validation. RBY evidence does not qualify RTC trailers,
mGBA save media or other generations' storage policy.

## API

    local file = require("platform_saveram").new({
        profile = "gambatte",
        path = admitted_isolated_save_path,
        authorize = current_private_save_authority,
    })
    local receipt = file:flush(complete_expected_hex)

The constructor uses the frozen platform_execution supported_profile metadata;
it does not instantiate or change the execution hold. It verifies the host
version, executable and core assembly, retains the exact core object, and
requires the emulator UI thread. The surrounding control owner remains
responsible for the complete admitted host/native-module profile, exclusive
process ownership, memory-read validity and reset/load/rewind interception.

authorize must verify current private execution/save authority. It is called
before path resolution and before/after persistence. It is not a remote JSON
permission. The caller supplies the Manager-owned isolated path; the adapter
resolves the host's actual normal SaveRAM path and refuses a mismatch before
calling the write API. It never chooses an autosave or arbitrary fallback path.

flush accepts bounded uppercase complete-file hex, not a party slice. It
requires a successful actual write with the expected final path, then opens
that file exclusively, calls Flush(true), closes it and checks full readback.
The frame count and physical owner must remain unchanged. The returned
slink-saveram-file-v1 receipt includes path, SHA256, byte length, host profile,
frame, flushed=true and readback=true. Its command/transaction binding and
durable publication belong to the caller. A file error must preserve the
pending command and hold; this adapter cannot authorize retrying a native effect.

## Pinned host basis

BizHawk 2.11.1 source commit bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5:

- MainForm.FlushSaveRAM selects the normal/movie-aware save path, calls
  CloneSaveRam and returns FileWriter.Write. Its default success result when
  SaveRAM is absent is insufficient; this adapter also checks Paths.Final.
- EmuClientApi.SaveRam discards FileWriteResult, so the adapter calls the typed
  MainForm method and inspects its result.
- FileWriter writes/replaces the destination; it does not call Flush(true).
  The adapter therefore adds the explicit file-handle flush and full readback.
- PathEntryExtensions.SaveRamAbsolutePath is used directly to resolve the same
  destination as the host. There is no guessed ROM-filename mapping in the API.

Private Config and result Paths are read through reflection on the pinned
host. No fields or methods are patched. The typed MainForm call avoids the
known NLua repeated-instance method-resolution issue. Reflective property/field
lookups and value reads also use explicit signatures: a real repeated-flush test
exposed that issue after an initially successful save.

Local pinned source copies are in .cache/bizhawk-save-source. Their SHA256s:
FileWriter.cs 315aaf7c8b1a8bbfd8a58544de0d3e25c67dedeef0a528177c805562911aa4df;
FileWriteResult.cs a619e0824848f4fd751aa6a861acd9151278303c0d5ece4857eac02e5936e209;
PathEntryCollectionExtensions.cs d45a08967f6cbd0ce8ada8aa8ac4fc35fabe0b9f3870fc2e44e18128c1374e7a.

## Current qualification

The final native client/paired run passed18 live tests in155.25 seconds: six RBY
animation/result/replay cases, three Yellow interruption cases, and two actual
emulator processes for each of the nine ordered RBY pairs. Successful native
paths exercise repeated file flushes, reject a different configured destination
and reject changed expected bytes. Each paired result independently reads both
distinct actual save files before coordinator ownership migration/release.
The two pre-execution interruption cases produce no file receipt or native frames.
Full unit/integration passed4,015 with the same two Windows symlink privilege skips;
227 Lua files parsed. These results do not qualify production control/selection,
Gen2/RTC serialization or mGBA storage.
