# Setup and onboarding flow

Source: OMP research report `cx-119fd772` (SECOND_OPINION, read-only, repo at master a9bdce38).

## Summary

The biggest onboarding failure is not ROM identification. It is the handoff between the
Manager, the launcher stub and a complete SLink runtime. `README.md:26` tells remote players to
get a full checkout, while the Manager serves only a `.lua` stub
(`server/manager.py:406-475,1003-1019`). A player ZIP builder already exists
(`tools/make_release.py:3-10,198-285`) but no Manager route exposes it. Fix packaging and
connection visibility before building a broad ROM-checking wizard.

The report's own strongest doubt: no real two-machine Windows setup was run, so which failure
players hit first (missing runtime, firewall, wrong IP) is inference. The repo proves the paths
exist, not their frequency.

## Key findings

### 1. Today's setup path and where a newcomer gets stuck

Actual path:

1. Host installs Python dependencies and BizHawk, supplies ROMs, starts the Manager or the
   standalone server (`README.md:19-39`).
2. Host creates a run and optionally prepares Gen 1 cartridges
   (`server/templates/manager.html:43-124`; `server/manager.py:885-903`).
3. Manager allocates a game TCP port and an internal HTTP port and starts a child server
   (`server/manager.py:377-401,505-557`).
4. Host shares the Manager or run URL.
5. Player installs BizHawk, loads ROM and save, loads a launcher in the Lua Console, and waits
   (`README.md:56-63`; `server/templates/_board.html:181-195`).
6. Both players catch in the same area to create the first row (`_board.html:192-193`).

Stop points, highest first (the report calls the first four rows release blockers):

| Stage | Stop point | Evidence | Importance |
|---|---|---|---|
| Launcher/runtime | The downloaded `.lua` is a stub that looks for `lua/slink.lua`, then opens a folder picker. A remote player with only the launcher cannot start. | `server/manager.py:406-475`; `docs/REFERENCE.md:199-201` | Critical |
| Player ZIP | A complete, tested player ZIP exists but has no Manager route. | `tools/make_release.py:3-10,397-472`; `tests/unit/test_make_release_manifest.py:1-11,139-168`; `server/manager.py:1702-1727` | Critical |
| Wrong host/IP | Launcher host comes from the browser `Host` header; a launcher downloaded via `localhost` points at `127.0.0.1`. | `server/manager.py:1003-1016`; `tools/make_release.py:219-230` | Critical |
| Version | Docs say BizHawk 2.9+, but the Gen 1 entry refuses anything below 2.11. | `README.md:24`; `tools/make_release.py:208-213`; `lua/slink.lua:59-78` | Critical |
| Game choice | Experimental games sit beside proven ones in the run form. | `server/manager.py:61-75`; `README.md:7-17`; `docs/REFERENCE.md:5-15,89-115` | Critical |
| ROM privacy | "Add file…" uploads the ROM to the Manager and writes it under `roms/`; it is not a local check. | `server/static/randomizer.js:230-245`; `server/manager.py:1282-1330` | Critical |
| Network/firewall | No scoped firewall rule, TCP test, or LAN-versus-WAN guidance. | `README.md:30-39`; `lua/connector.lua:176-181` | Critical |
| Connection waiting | "Waiting for hello" does not tell apart launcher not loaded, TCP failure, game not loaded, wrong core, or rejection. | `_board.html:109-131,171-195`; `server/board.py:203-206` | Critical |
| Host prerequisites | Python version, install, working directory not explained. | `README.md:19-28`; `docs/REFERENCE.md:135-144` | High |
| Emulator install | BizHawk download, Windows prerequisite installer, "do not mix versions" absent. | `README.md:23-24`; [BizHawk installation instructions](https://github.com/TASEmulators/BizHawk#installing) | High |
| Core | Gen 1 needs Gambatte; pureRGB needs GBC Console Mode; no preflight. | `docs/REFERENCE.md:139-140`; `docs/gen1_requirements.md:20-21`; `lua/slink.lua:59-76` | High |
| Save order | "Save first, launcher second" is stated without the why or what "writes disabled" means. | `README.md:60-63`; `docs/REFERENCE.md:199-201` | High |
| Run creation | Compatibility errors surface only at hello. | `server/manager.py:194-225`; `server/templates/manager.html:53-89` | High |
| Gen 1 cartridges | Host-side provisioning not explained. | `_cartridges.html:11-34`; `server/manager.py:1274-1280` | High |
| Ports | Manager `:8090`, standalone `:8080`, game TCP from `54321`. | `README.md:30-39`; `server/manager.py:273-275,390-401` | High |
| Lua Console UI | No consistent `Script → Open Script…`, `▶` running, `⏹` stopped. | `README.md:60`; [BizHawk Lua Console instructions](https://github.com/TASEmulators/BizHawk#running-lua-scripts) | High |
| Script before game | Scripts start at once; SLink's entry returns with no game; no recovery step. | [BizHawk Lua Functions](https://tasvideos.org/BizHawk/LuaFunctions); `lua/slink.lua:59-78`; `lua/gen1/run.lua:25-27` | High |
| Extension/core | A `.gbc` renamed `.gb` can run in the wrong mode. | `README.md:277-282`; `server/manager.py:88-92`; `server/cartridges.py:56-66` | High |
| Missing DLL | `socket-windows-5-4.dll` hint buried in the generated guide. | `tools/make_release.py:210-213,270-285`; `README.md:28` | High |
| Wrong save/ROM | Terse banners, no expected hash or repair action. | `_board.html:92-93`; `server/server.py:491-550,1641-1692` | High |
| Randomizer | Checks jar presence, not Java version, memory, fork or antivirus/path problems. | `server/static/randomizer.js:264-280`; `server/upr_pipeline.py:69-100`; UPR [Java requirements](https://github.com/Ajarmar/universal-pokemon-randomizer-zx/wiki/About-Java) | High |
| Companion patch | Patch-only options selectable without checking both players have it. | `server/manager.py:125-161`; `_patcher_panel.html:65-91` | High |
| Data dir | Locked or synced data dir reported only after the run starts. | `_board.html:91-93`; `server/manager.py:287-299` | Medium |
| Public exposure | No player auth or token on the launcher route; timestamp run IDs; broad GET APIs. | `server/manager.py:895-903,1003-1019,1702-1727` (inference) | High if public |

### 2. The launcher/package contract is the largest concrete defect

`README.md:26` requires a full checkout; `tools/make_release.py:3-10` and `:198-285` describe a
player ZIP with runtime, data and guide and no Python; `tests/unit/test_make_release_manifest.py:139-168`
checks the runtime and LuaSocket DLL are packed; yet `server/manager.py:1702-1727` serves only
the launcher and ROMs. The generated guide still says `:8080` (`tools/make_release.py:219-230`).
A player can follow the visible steps and still be unable to run. P0, confidence high.

### 3. A browser-only ROM check works, but not over plain LAN HTTP

The in-browser patcher already reads the file with `file.arrayBuffer()` and never sends it
(`server/static/patcher.js:263-267`; `server/patcher.py:8-15`), computing MD5 and UPS CRC
locally (`server/static/patcher.js:58-116`). "Add file…" does the opposite
(`randomizer.js:237-245`; `manager.py:1282-1330`).

- MDN lists SHA-1, SHA-256, SHA-384 and SHA-512 for `SubtleCrypto.digest()`, not MD5. MD5 needs
  a local JS implementation such as the patcher's.
  [MDN SubtleCrypto digest](https://developer.mozilla.org/en-US/docs/Web/API/SubtleCrypto/digest)
- `SubtleCrypto` needs a secure context. `http://localhost` qualifies; `http://192.168.x.x`
  normally does not. [W3C Web Crypto](https://w3c.github.io/webcrypto/),
  [MDN Secure Contexts](https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Secure_Contexts)
- `digest()` does not stream; the whole file is read into memory.
  [MDN Blob.arrayBuffer](https://developer.mozilla.org/en-US/docs/Web/API/Blob/arrayBuffer)
- SHA-1 is for compatibility, not security. [NIST Hash Functions](https://csrc.nist.gov/projects/hash-functions)

Policy: SHA-256 as the primary new catalogue field; keep SHA-1 because admission uses it; MD5
only for legacy patcher fingerprints; never fall back to uploading; use a worker or incremental
hash for large Gen 4/5 files. P0 for privacy once HTTPS and runtime delivery exist.

### 4. ROM identity data covers Gen 1, not every game

Known-good SHA-1s exist for vanilla Red, Blue, Yellow (`data/pret_rom_syms.json:2-3,12554-12555,25106-25107`;
`data/games/gen1_rby/profile.json:541,1085,1624`) and pureRGB
(`data/games/gen1_purergb/profile.json:603,1209,1815`; `data/games/gen1_purergb/admission.json:2-28`).
Randomized outputs are checked against the run's cartridge contract
(`server/cartridges.py:145-154`; `server/server.py:513-550`). So the wizard needs two checks: a
static known-good manifest, and a per-run contract check. A universal "valid ROM" label would
mislead for Gen 2-5 until byte-level manifests exist; header detection is a warning only.

### 5. Connection state is too coarse for a useful waiting screen

`connected` is set on any message, before hello admission (`server/server.py:1211-1218`);
non-hello events are dropped until hello (`server/server.py:1315-1325`); the board shows
"waiting for hello" (`_board.html:171-172`); `admission_reason` exists only after hello
(`server/server.py:513-550`). Proposed states:

```text
not_started → launcher_downloaded → runtime_ready → tcp_connecting → tcp_connected
→ waiting_for_game → hello_received → admitted → live
```

Each state carries `last_seen`, system, ROM SHA-1, script version, admission and a
`next_action`. The client needs a non-mutating diagnostic or a `ready:false` hello so "TCP up,
no game" differs from "no TCP". Do not show a player green until admitted.

### 6. Advanced options and unsupported games appear too early

The run selector lists every family, including Gen 4/5 (never run on a real game,
`README.md:14-15`), Emerald (incomplete area tables, `README.md:9-10`; `docs/REFERENCE.md:5-10`)
and Gen 2 AP (`README.md:13-14`; `docs/REFERENCE.md:89-115`), beside proven paths
(`server/manager.py:61-75`). Default to a plain run; put companion, randomizer and experimental
choices behind "Advanced setup" and show missing prerequisites before creation.

### 7. Comparable onboarding

- Archipelago: layered install, host, game guide, connect (server, port, slot, password); the
  Red/Blue guide covers BizHawk version, prerequisite installer, Lua core, AutoSaveRAM, "Run in
  background", exact Lua Console steps and reconnecting.
  [Archipelago general setup](https://archipelago.gg/tutorial/Archipelago/setup_en),
  [Archipelago Pokémon Red/Blue setup](https://archipelago.gg/tutorial/Pokemon%20Red%20and%20Blue/setup_en).
  Its BizHawk client waits for the connector, checks script version, reads ROM hash and system ID,
  and reports wrong ROM or no handler:
  [Archipelago BizHawk client source](https://github.com/ArchipelagoMW/Archipelago/blob/main/worlds/_bizhawk/context.py),
  [connector implementation notes](https://github.com/ArchipelagoMW/Archipelago/blob/main/worlds/_bizhawk/README.md).
- BizHawk: [BizHawk installation](https://github.com/TASEmulators/BizHawk#installing),
  [ROM indicator](https://github.com/TASEmulators/BizHawk#identifying-a-good-rom),
  [core selection](https://github.com/TASEmulators/BizHawk#selecting-and-configuring-cores),
  [Lua scripts](https://github.com/TASEmulators/BizHawk#running-lua-scripts),
  [SaveRAM](https://github.com/TASEmulators/BizHawk#in-game-saves) (manual flush; auto flush is
  described as unreliable).
- Randomizers: [Archipelago Pokémon options](https://archipelago.gg/games/Pokemon%20Red%20and%20Blue/player-options),
  [UPR ZX v4.6.1 release](https://github.com/Ajarmar/universal-pokemon-randomizer-zx/releases/tag/v4.6.1),
  [UPR Java guide](https://github.com/Ajarmar/universal-pokemon-randomizer-zx/wiki/About-Java)
  (Java 8+ 64-bit, 4 GB, antivirus and protected-directory failures). Pattern: basic defaults,
  explicit advanced branch, local prerequisite check, generated artifact, exact download.
- RetroAchievements: deterministic preflight, no ROM hosting, how to see a ROM hash.
  [RetroAchievements emulator setup](https://docs.retroachievements.org/developer-docs/emulator-setup-for-developers.html),
  [RetroAchievements emulator support](https://docs.retroachievements.org/general/emulator-support-and-issues.html),
  [RetroAchievements FAQ](https://docs.retroachievements.org/general/faq.html).
  Copy the checklist and ROM posture, not the account system.

### 8. UX guidance supports a guided, resumable flow

[NN/g Wizards](https://www.nngroup.com/articles/wizards/),
[NN/g Error-Message Guidelines](https://www.nngroup.com/articles/error-message-guidelines/),
[WCAG error identification](https://www.w3.org/WAI/WCAG22/Understanding/error-identification.html),
[labels and instructions](https://www.w3.org/WAI/WCAG22/Understanding/labels-or-instructions.html),
[status messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html).

## Proposed player wizard (condensed)

Each step has empty, loading, success and error copy. Announce only state transitions through a
polite live region; use an alert region for blocking errors; never colour alone.

0. **Run and player.** "Player A · Red / Blue · host `192.168.1.50` · game TCP `54322`." Error:
   run stopped, ask the host.
1. **BizHawk preflight.** Guided confirmation (the browser cannot detect a desktop install),
   verified later by the client: version, core, AutoSaveRAM or manual flush, one emulator per
   player. Link: [Download BizHawk](https://github.com/TASEmulators/BizHawk/releases/latest).
   Errors: too old (install 2.11+); wrong core (Gambatte for Gen 1; GBC Console Mode for pureRGB).
2. **Check the ROM locally.** "Check your ROM without uploading it." Outcomes: recognized clean
   dump; known mismatch (region, revision, patch or randomizer output); wrong family; insecure page
   ("open over HTTPS or localhost; your ROM was not uploaded"); unsupported browser; too large;
   unknown generation ("compatibility is unverified").
3. **Optional prepared cartridge or companion.** Host still preparing; ready; wrong cartridge.
   Do not call MD5 a security check.
4. **Download the player runtime.** Whole ZIP, not only the `.lua`. Errors: package unavailable;
   launcher cannot find runtime; LuaSocket DLL missing (`lua/x64/socket-windows-5-4.dll`).
5. **Load the game, then the script.** Two checkboxes. `Tools → Lua Console`,
   `Script → Open Script…`, keep the console open. Recovery copy for script-before-game and a
   stopped script.
6. **Live waiting.** No launcher; TCP connecting; TCP up but no game; game recognized; rejected;
   both live; no pair yet ("this is normal"); wrong save ("SLink will not silently adopt a
   different trainer identity").
7. **Ready.** First eligible catch in the same area creates a pair; a miss makes a dead zone.

## Recommendations

**P0**

1. Add `GET /api/runs/{run_id}/player-pack/{player}` returning a ZIP from the existing
   `tools/make_release.py` manifest, with the run's real host, TCP port, player and URL injected.
   Put "Download Player A setup" beside the launcher link.
2. Fix the generated guide's hard-coded `:8080`; label the game TCP port separately. State that the
   `.lua` is a launcher, not the client.
3. Test the real path: build ZIP, extract to a clean folder, load a real ROM, load the extracted
   launcher, observe hello.
4. Add the connection state machine on the existing `/api/runs/{run_id}/live` polling
   (`server/manager.py:1727`), with one concrete next action per blocking error.
5. Generate README, player guide, Manager copy and launcher comments from one source: BizHawk 2.11+
   for Gen 1 (do not imply the same evidence for other gens), Gambatte, GBC Console Mode for
   pureRGB, Windows prerequisite, game before script, exact Lua Console path, `▶`/`⏹`, manual
   SaveRAM flush, no savestates during a run, never only the launcher.

**P1**

6. ROM checker behind HTTPS: a generated manifest (id, title, family, size, sha1, sha256, optional
   md5, required core) plus a per-run contract; `<input type="file">`, `file.arrayBuffer()`, local
   SHA-256 and SHA-1, never `/api/roms`, feature-detect `isSecureContext` and `crypto.subtle`.
7. Network diagnostics: show host, game TCP port and player; block completion when a remote browser
   got a `localhost` launcher; on TCP failure suggest `Test-NetConnection` and a Private-profile
   firewall rule, never disabling Defender.
   [Microsoft Test-NetConnection](https://learn.microsoft.com/en-us/powershell/module/nettcpip/test-netconnection),
   [Microsoft firewall guidance](https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/configure-with-command-line)
8. Gate advanced setup (companion, randomizer, cartridge prep, Rival Swap, Overworld Presence,
   native UI/audio, experimental gens) with explicit prerequisite checklists.

**P2**

9. One support matrix drives all setup copy.
10. Browser test: select a fixture, confirm SHA-1/SHA-256, assert no ROM request is made.
11. Clean-directory package boot test; remote smoke scenarios (wrong host, wrong port, firewall,
    wrong core, script-before-game, missing DLL, wrong save, rejected randomized cartridge).
12. "Copy diagnostics" button (run, player, host/port, client version, system/core, last error;
    never ROM bytes or saves).
13. Keep public exposure off by default; internet hosting needs HTTPS, auth, per-player tokens and
    rate limiting first.

## Where the report expects disagreement

- Do not lead with a universal ROM checker: Gen 1 coverage only, and plain-HTTP LAN URLs block
  `SubtleCrypto`.
- Do not reuse `/api/roms` for a remote player's file.
- Do not keep every game in the default selector.
- A green card is not "connected"; separate transport, recognition, hello and admission.
- Do not start with a large visual wizard; the player ZIP and diagnostics remove more blockers.

## Unverified and open

- No remote Windows/BizHawk session run; firewall, reverse-proxy Host-header behaviour and failure
  frequency unverified.
- No deployed endpoint for `SLink-player-*.zip`; its operational availability is unverified.
- No SHA-256 known-good manifest exists; Gen 2-5 byte-level manifests not found.
- A BizHawk API for the active core name was not established (`emu.getsystemid()` exists).
- A fresh player ZIP was not built and booted.
- No auth or public deployment tested; treat the current routes as unsafe for internet exposure.
- "Every stop point" means every path found in the named files, not every possible user error.

## Validation

6/6 accepted. A Sonnet validator confirmed: the Manager serves only a Lua stub; the player ZIP
from `make_release.py` is not exposed by any route; the launcher host comes from the Host header;
the README says a full checkout is needed; the README says 2.9+ while `slink.lua` refuses below
2.11; MDN's digest has no MD5 and needs a secure context.
