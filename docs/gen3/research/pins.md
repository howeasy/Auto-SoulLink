# Gen 3 G0 source pins (research)

Compiled by worker `gen3-P0-C0-2`. Every fact below is either a URL (fetched via `gh api`/GitHub
REST) or a `file:line` in this worktree. Nothing here edits, builds, or runs anything; PLAN.md
§2, §5.2, §5.8, §6 (P0/P2), §11 named the obligations this note answers.

## 1. pret/pokefirered

- **Current `master` commit**: `c75f352304d529f6ba92d4f74b9cf8b5c3810788`, authored
  2026-08-04T03:21:32Z. Source: `gh api repos/pret/pokefirered/commits/master` (default branch
  confirmed `master` via `gh api repos/pret/pokefirered --jq .default_branch`).
- **`.sym`/`.map` build targets — confirmed, the repo's own Makefile produces both**:
  `MAP := $(ROM:.gba=.map)` and `SYM := $(ROM:.gba=.sym)` at
  `https://raw.githubusercontent.com/pret/pokefirered/master/Makefile:52-53`; the `syms: $(SYM)`
  target at `Makefile:208`; the link step passes `-Map ../../$(MAP)` at `Makefile:387`; the `$(SYM)`
  recipe depends on `$(ELF)` at `Makefile:398`. So `pokefirered.sym` / `pokefirered.map` (and the
  `_rev1` variants, since `ROM` is per-build) are ordinary build products, not something that needs
  a separate tool.
- **Toolchain** (`INSTALL.md`, `https://raw.githubusercontent.com/pret/pokefirered/master/INSTALL.md`):
  - **Default (`make`)**: **agbcc**, pret's own patched GCC — cloned from `github.com/pret/agbcc`,
    built with `./build.sh`, then `./install.sh ../pokefirered` copies it into the pokefirered tree
    (INSTALL.md "Installation" step 2). This is *not* devkitARM.
  - **Alternate (`make modern`)**: devkitARM's `arm-none-eabi-gcc`, installed via the devkitPro
    pacman GBA-dev package (`gba-dev`). INSTALL.md gives OS-specific install paths but names no
    exact devkitARM/devkitPro **version** anywhere in the file — it only says "install `gba-dev`
    via devkitPro pacman," which always resolves to whatever devkitARM release the pacman repo
    currently serves. No version pin exists in this repo for devkitARM.
  - A `TOOLCHAIN=<path>` override is also documented (`make TOOLCHAIN="/path/to/toolchain"`),
    requiring `bin`, `lib`, `include`, `arm-none-eabi` subdirectories for the `modern` target.
  - agbcc's own current `master` commit (for provenance if it is pinned instead): `da598c1d918402c42c0c0d7128ba14567f3175e9`,
    2026-01-20T22:00:45Z (`gh api repos/pret/agbcc/commits/master`).
- **FireRed/LeafGreen sha1s documented by the repo itself** — `README.md` and the four `.sha1`
  files at repo root, quoted exactly:
  - `firered.sha1` → `41cb23d8dccc8ebd7c649cd8fbb58eeace6e2fdc  pokefirered.gba`
  - `firered_rev1.sha1` → `dd5945db9b930750cb39d00c84da8571feebf417  pokefirered_rev1.gba`
  - `leafgreen.sha1` → `574fa542ffebb14be69902d1d36f1ec0a4afd71e  pokeleafgreen.gba`
  - `leafgreen_rev1.sha1` → `7862c67bdecbe21d1d69ce082ce34327e1c6ed5e  pokeleafgreen_rev1.gba`
  - (repo also ships `firered_switch.sha1`/`leafgreen_switch.sha1` for the NSO re-release, not
    relevant here.)
  - `README.md` repeats the same four sha1s next to no-intro Datomatic links, e.g.:
    `**pokefirered.gba** ... sha1: 41cb23d8dccc8ebd7c649cd8fbb58eeace6e2fdc` and
    `**pokeleafgreen.gba** ... sha1: 574fa542ffebb14be69902d1d36f1ec0a4afd71e`.
  - **Revision matrix**: the non-`_rev1` sha1s (`41cb23d8...` FR, `574fa542...` LG) are the ones
    labelled plain "FireRed"/"LeafGreen" — this is **US 1.0**; `_rev1` is the 1.1 revision. The
    repo has no separate "US" qualifier in the filename, but the four-way split (FR/LG × base/rev1)
    plus the well-known no-intro naming (`Pokemon - FireRed Version (USA) (Rev 0/1)`) is the
    standard identification for these sha1s; I did not independently cross-check the no-intro DB
    page contents (Datomatic link fetch not attempted — mark this cross-check †UNVERIFIED, though
    the sha1 values themselves are directly quoted from the pret repo, which is the primary source
    the plan actually needs).
  - Repo build targets confirm the same revision split: `make` / `make leafgreen` build the base
    (1.0) ROMs; `make firered_rev1` / `make leafgreen_rev1` build 1.1 (INSTALL.md "Build
    pokeleafgreen and REV1").

## 2. Build recipe outline (Windows), mirrored against `tools/build_purergb_syms.py`

Read: `tools/build_purergb_syms.py` (full, 256 lines), `tools/_build_tools_bootstrap.py` (full,
411 lines), `data/purergb_sources.lock.json` (full). `tools/build_pret_syms.py` (450 lines) exists
in this tree but is the **Gen 1** pret/pokered driver (RGBDS, not devkitARM/agbcc) — same pattern,
different toolchain; there is no `build_pret_gba_syms.py` yet (P2 file list in PLAN.md §6 names it
as something to *create*).

**How pureRGB pins today** (the closest existing precedent, `tools/build_purergb_syms.py:1-256`):
1. `data/purergb_sources.lock.json` names an exact `source.commit` (git sha) + `source.tag`, a
   `rgbds_version`, a `w64devkit_version`, and per-output `sha1`/`header_crc`/`crc32`/`title`
   expectations (`data/purergb_sources.lock.json:1-35`).
2. `verify_source()` clones/reuses the repo, refuses a dirty tree, `git checkout <commit>`, and
   hard-asserts `rev-parse HEAD == commit` (`tools/build_purergb_syms.py:75-100`).
3. `_build_tools_bootstrap.ensure_rgbds(version)` / `ensure_w64devkit()` resolve toolchains in a
   fixed order: `SLINK_*_BIN` env override (trusted as-is) → an already-extracted
   `.cache/build-tools/<name>-<version>/` → (RGBDS only) a version-matching binary already on
   `PATH` → Windows auto-download of a **pinned URL + sha256 + byte size**, extracted into
   `.cache/build-tools/` (`tools/_build_tools_bootstrap.py:204-350`). RGBDS pins two versions
   (`v1.0.1`, `v1.0.3`) each with `url`/`sha256`/`size`
   (`tools/_build_tools_bootstrap.py:50-61`); w64devkit pins one 7z SFX with the same three fields
   (`:65-68`). Both are verified by content sha256 after download, not just by size
   (`_download_and_verify`, `:119-152`).
2. `make -j4 <lock["make_targets"]>` is run with `PATH` prefixed by both bin dirs
   (`tools/build_purergb_syms.py:151-160`); on mismatch/failure nothing is published.
3. Every output ROM is sha1-checked against the lock; on any mismatch the run raises and
   **publishes nothing** (`:166-184`) — "a locked build is either exactly reproduced or it does not
   count" (module docstring, `:6-9`).
4. On match, `.sym`/`.map` files are copied to `data/purergb/`, each hashed (sha256), and a
   `build_provenance.json` is written recording source commit, per-tool binary sha256s (not just
   version strings — `_toolchain_record`, `:111-125`), the exact `make` command, per-ROM facts
   (sha1/md5/header_crc/crc32/title, `_rom_facts`, `:128-135`), and per-symbol-file sha256
   (`:213-221`).
5. `--check` mode rebuilds and diffs against the *committed* `.sym`/`.map`, publishing nothing —
   drift-detection without touching the committed artifacts (`:191-204`).

**Equivalent pin set for pokefirered (agbcc + optionally devkitARM), by analogy**:
- A `data/pret_pokefirered_sources.lock.json` naming: `source.commit` = the pinned pret/pokefirered
  sha (P0 should pin the exact commit at sign-off, e.g. `c75f352304d529f6ba92d4f74b9cf8b5c3810788`
  as of this research, not "current master" — master moves), `agbcc.commit` (pret/agbcc sha, e.g.
  `da598c1d918402c42c0c0d7128ba14567f3175e9` as of this research), and per-ROM sha1 expectations
  (the four `.sha1` values quoted in §1).
- **agbcc has no numbered "version"** the way RGBDS/w64devkit do — it is pinned by git commit only,
  same as pureRGB's own `source.commit`. It ships as C source (`build.sh`/`install.sh`), not a
  prebuilt binary archive, so there is **no sha256-of-a-download** to pin the way RGBDS/w64devkit
  get one; the pin is the git commit + a reproducibility check on the built compiler binary
  (sha256 of the built `bin/agbcc*` after `build.sh`, recorded in provenance the way pureRGB
  records toolchain binary sha256 today, `_toolchain_record`).
- **devkitARM is the harder case**: INSTALL.md never pins a devkitARM/devkitPro-pacman version —
  `make modern` always builds against whatever devkitARM the pacman repo currently serves. There is
  no `RGBDS_PINS`-style `{version: {url, sha256, size}}` table to write for devkitARM from
  primary-source data in this repo; devkitPro's pacman-based distribution model (a rolling repo,
  not tagged release zips) does not fit `_build_tools_bootstrap`'s "download one exact URL, verify
  one sha256" pattern without first picking a devkitPro pacman package version and mirroring it,
  which was not attempted in this research pass (out of scope for a citation-only pass; would need
  its own verification against devkitpro.org's pacman package index).
  - **Recommendation, stated as the plan's own fallback**: use the **agbcc path** (`make`, not
    `make modern`) as the default build, since it *is* commit-pinnable exactly like pureRGB's own
    `source.commit`, with no unpinned rolling dependency. If devkitARM specifically is required
    (e.g. to match a `modern`-built reference), PLAN.md §11's own risk row already names the
    fallback: **"No pret/pokefirered or devkitARM under `.cache/pret`" → "P2 `build_pret_gba_syms.py`
    with pinned toolchain (pureRGB precedent); else committed `.sym/.map` with sha256 provenance"**
    (`docs/gen3/PLAN.md:238`). That fallback is directly usable here: commit `pokefirered.sym` /
    `pokefirered.map` (built once, by hand, on a host with a known devkitARM or agbcc install) into
    the tree with a `build_provenance.json`-style record (builder host, toolchain binary sha256s,
    ROM sha1 that resulted, git commit of pokefirered/agbcc used) — the same shape pureRGB already
    uses for its *published* `data/purergb/*.sym/.map` (`tools/build_purergb_syms.py:206-227`), just
    without requiring devkitARM's install to itself be reproducibly pinned.

## 3. CFRU and Radical Red

- **Repo**: `https://github.com/Skeli789/Complete-Fire-Red-Upgrade`, default branch `master`,
  current commit `b637a27898b14e25dd24d0f69a3e302f0069deb8` (2025-01-24T16:13:37Z,
  `gh api repos/Skeli789/Complete-Fire-Red-Upgrade/commits/master`). Description (from the GitHub
  API): "A complete upgrade for FireRed, including an upgraded Battle Engine."
- **`BPRE.ld`** lives at repo root:
  `https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/master/BPRE.ld`. Read in full
  (2069 lines). It is exactly what the plan needs it to be: a flat GNU-ld symbol-assignment script
  mapping **vanilla FireRed (BPRE) symbol names to fixed ROM/RAM addresses**, e.g.
  `AGBAssert = 0x81E3B14 | 1;`, `vsprintf_fr = 0x81E5FD4 | 1;`, `GetEreaderTrainerFrontSpriteId =
  0x80E7420 | 1;` (Thumb functions carry the `| 1` low-bit tag), plus RAM addresses for CFRU's own
  new globals (`gBattleSandsStreaks = 0x202682C;`, `gFollowerState = 0x203B818;`, etc.) and raw
  IO register addresses (`DMA0_SRC = 0x40000B0;`). A sibling `linker.ld` also exists in the repo
  tree (`gh api repos/Skeli789/Complete-Fire-Red-Upgrade/git/trees/master`) — not read in this pass,
  presumed to be the actual `-T` link script that `include`s `BPRE.ld`'s symbol table, but that
  inclusion relationship was not confirmed by reading `linker.ld` itself (†UNVERIFIED).
- **Radical Red vs CFRU**: community sourcing (PokeCommunity threads, GameBrew wiki — not primary
  in the sense of a signed statement from RR's author, but the closest available) describes Radical
  Red as "a difficulty hack with additional features that utilizes the Complete FireRed Upgrade
  engine and Dynamic Pokemon Expansion" (search result summary, no single authoritative page
  quoted verbatim per the copyright limit). This matches the plan's own framing (PLAN.md: "RR is a
  CFRU-based hack with a modified build").
  - **RR has no public source — supported, not proven, by absence**: `gh search repos "radical red
    pokemon"` returned zero repository results. No `github.com/*/RadicalRed`-shaped source tree was
    found. This is negative evidence (nothing found), not a citable statement that no source exists
    anywhere; treat the plan's "RR has no public source" claim as **plausible/consistent with this
    search but not independently confirmed by a primary source**, and list it under §5 below.
- **RR base md5, cited from this tree** (not independently re-derived — that would need the actual
  RR ROM, out of scope for this research pass): `patch/tools/build.py:90` —
  `RR_MD5 = "8529f3a45d32bce4da637976fcf269d4"`, enforced at `patch/tools/build.py:195-196`
  (`if not args.no_verify_md5 and src_md5 != RR_MD5: sys.exit(...)`). Cross-referenced against
  `server/patcher.py:71-72`: `"base_md5": "8529f3a45d32bce4da637976fcf269d4"`, `"patched_md5":
  "8dcffce7659be02474dfa0f876639f8a"` — matches PLAN.md §6/P0's named pins exactly (RR 4.1 base
  md5 `8529f3a4…`, companion md5 `8dcffce7…`), confirming those figures are live in this tree, not
  stale.

## 4. BizHawk 2.11.1 + mGBA, and the `event.on_bus_exec` timing issue (#3801)

- **Release tag**: `2.11.1`, `target_commitish: release`, published `2026-05-01T13:49:04Z`
  (`gh api repos/TASEmulators/BizHawk/releases/tags/2.11.1`). The tag's commit is
  `bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5` (`gh api repos/TASEmulators/BizHawk/git/refs/tags/2.11.1`).
- **mGBA submodule commit at that tag**: `submodules/mgba` = `94b1578f8545d8ad17bb4036dba908612d5731e2`
  on `TASEmulators/mgba`, branch `bizhawk-0.11` per `.gitmodules`
  (`gh api repos/TASEmulators/BizHawk/git/trees/2.11.1` tree entry for `submodules/mgba`;
  `gh api repos/TASEmulators/BizHawk/contents/.gitmodules?ref=2.11.1`).
- **Issue #3801** (`https://github.com/TASEmulators/BizHawk/issues/3801`), title `[GBA]
  event.on_bus_exec is apparently fired *after* instruction is executed, not before`. **State:
  closed**, `closed_at: 2026-03-03T11:41:40Z`, closed by commit
  `946326796c9d63ce015caaf3029cd5bbcceb3657` whose message is `Fix address passed to mgba exec
  callback` / `Fixes #3801` (authored 2026-03-03T11:39:58Z). Comparing that fix commit against the
  `2.11.1` tag (`gh api repos/TASEmulators/BizHawk/compare/2.11.1...946326796c9d63ce015caaf3029cd5bbcceb3657`)
  returns `ahead_by: 0, behind_by: 144` — i.e. the fix commit is an **ancestor** of the `2.11.1`
  release, 144 commits behind it. **The fix is included in BizHawk 2.11.1.** The issue thread
  itself (comments) frames the root cause as ARM pipeline/prefetch PC attribution (mGBA's
  `_ARMPCAddress` compensating two instructions), not a simple off-by-one, and one commenter
  demonstrates the workaround address offset that the shipped fix formalizes.
- **`git show codex/rr-foundation:docs/rr_reference/BIZHAWK_MGBA_CALLBACKS.md`** (read as a git
  object in this worktree, read-only, full file read to line ~260 covering the relevant sections):
  it independently pins the **installed host's** BizHawk to commit
  `bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5` — **which this research confirms is exactly the
  `2.11.1` tag commit** — and the installed `mgba.dll` to mGBA commit
  `94b1578f8545d8ad17bb4036dba908612d5731e2` — **which this research confirms is exactly the
  submodule pin at that tag**. Both pins in that doc still match current upstream state; nothing in
  it is stale against this research pass. Its stated contract (exact-address-only read/write/exec
  callbacks; wildcards/masks rejected; execute callback reports
  `_ARMPCAddress(cpu) + _ARMInstructionLength(cpu)`, i.e. the **next** instruction address, matching
  the #3801 fix's framing; watchpoints span `[address, address+1)` with overlap/interior-byte loss
  documented; DMA/system write origin is dropped by the bridge) is presented there as directly
  read from the pinned mGBA/BizHawk source files (`bizinterface.c`, `memory-debugger.c`,
  `MGBAMemoryCallbackSystem.cs`, etc., each with a line-anchored GitHub URL and a source-fingerprint
  sha256 table) plus a live capability probe run on the installed binaries. This research did not
  re-run that probe or re-fetch every cited source line; it is recorded here as a **consistent,
  independently-corroborated pin** (the two commit hashes match), not fully re-verified line by
  line.

## 5. NOT VERIFIED

- **No-intro Datomatic cross-check** for the FR/LG US 1.0 sha1 identification (§1): the pret
  README's sha1 values were read directly from the repo, but the Datomatic pages themselves
  (linked from that README) were not fetched to independently confirm the "(USA) (Rev 0)" labelling
  — the US-1.0 identification here rests on pret's own base/`_rev1` file-naming split, not on an
  independently fetched no-intro record.
- **`linker.ld` in CFRU**: not read; its relationship to `BPRE.ld` (does it `INCLUDE BPRE.ld`, or
  is `BPRE.ld` used standalone) is inferred from filename convention, not confirmed by content.
- **"Radical Red has no public source"**: supported only by a `gh search repos` miss (negative
  evidence) plus the plan's own prior assertion; no statement from RR's author or a definitive
  "source: closed" notice was located and quoted.
- **devkitARM exact version/URL/sha256 pin**: INSTALL.md pins no version; devkitPro's pacman
  distribution model was not investigated further (e.g. querying devkitpro.org's pacman package
  index for a specific `gba-dev`/`devkitARM` build) — recorded as a gap, not filled, per §2's
  recommendation to prefer the agbcc path or the committed-`.sym`/`.map` fallback instead.
- **agbcc reproducible-build sha256**: agbcc's `master` commit is pinned above, but no build was
  run in this research pass to record what sha256 its compiled binary produces — that would be a
  P2 provenance-generation step, not something a citation-only pass can produce.
- **RR 4.1 exact "4.1" versioning inside the binary/patch**: this research did not independently
  verify that the md5 `8529f3a4…`/`8dcffce7…` pair in `patch/tools/build.py`/`server/patcher.py`
  corresponds specifically to "RR 4.1" as opposed to some other RR point release — that mapping is
  taken on the strength of the existing in-tree comments/names, not re-derived from an RR release
  page.
