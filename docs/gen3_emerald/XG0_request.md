# XG0 request — expansion reference build (draft, 2026-09-26)

## 1 What XG0 signs

The source/config/toolchain identity and two-clean-build reproducibility of the
`expansion/1.17.0` reference artifact. This gate does not sign runtime admission,
struct offsets, generated packs, save compatibility, or emulator qualification.

## 1a Status at checkpoint X0

Worktree `C:/slink-wt/em-x`, branch `claude/gen3-emerald-x`, base
`798b6c80c5e359cfc08963ed3f53e76f26bef070`. The final commit is identified in the
worker report; this draft and its evidence ship together in that commit.

Source: `rh-hideout/pokeemerald-expansion@e8bd1cd7b03fc032ea37e3ecd38b379b5d01a1e7`,
resolved with `git ls-remote` and verified against both cloned HEAD and tag.
All 23 `include/config/*.h` files are SHA-256 pinned in
`data/gen3_exp_sources.lock.json`.

The reference host is Linux Mint 22.3 (Ubuntu noble), SSH alias `hgbox` (a label,
not credentials). ARM GCC is package `gcc-arm-none-eabi` version
`15:13.2.rel1-2`, reporting `13.2.1 20231009`. The lock includes its binary hash,
host GCC and make identities, distro release, and package versions including
libpng-dev. All requested packages were already installed; no apt installation
was necessary. See `probes/x0_linux_toolchain_2026-09-26.txt`.

Both clean Linux builds PASS: ROM SHA1
`28877d733492299599f2b8fff50493109d72653c`, MD5
`83bde8deeaa27453b12545b9cfffe3a6`, 33,554,432 bytes. Worker elapsed times
162.386 s and 148.240 s (including clone/preflight). ELF/map/sym SHA-256s also
match. Both source checkouts remain clean. See `probes/x0_build_repro_2026-09-26.txt`
and its two full JSON receipts.

## 2 Per-item status

| Item | SOURCE | MODEL | PHYSICAL | Evidence |
|---|---|---|---|---|
| Source and config pins | verified | — | — | `data/gen3_exp_sources.lock.json` |
| Compiler/host identity | verified, gate pending | — | — | lock; Linux toolchain receipt |
| XF-1 two clean builds, same ROM SHA1 | verified | — | — | `probes/x0_build_repro_2026-09-26.txt` |
| Offline receipt refusal checks | — | 16 passed | — | `tests/unit/test_build_expansion.py` |
| Native Windows support | unsupported | — | — | Windows toolchain and failure receipts |

Host execution proves tooling behavior, not game PHYSICAL qualification.

## 3 Defects found and fixed

The new wrapper was absent: the initial test run failed collection with
`FileNotFoundError: tools/build_expansion.py`. Offline lock/receipt integrity,
artifact tampering, missing receipt, dependency refusal, and output containment
checks now pass.

Native Windows could build the verified portable zlib/libpng static libraries,
but required one host-tool portability patch at upstream
[`tools/preproc/c_file.cpp:210`](https://github.com/rh-hideout/pokeemerald-expansion/blob/e8bd1cd7b03fc032ea37e3ecd38b379b5d01a1e7/tools/preproc/c_file.cpp#L210).
The coordinator authorized `%ld` → `%zu`. A 64-bit CRT probe and byte-exact
compound-string declaration probe passed; exact before/after lines and hashes
are retained in `probes/x0_toolchain_2026-09-26.txt`.

The next native failure was
[`map_data_rules.mk:42`](https://github.com/rh-hideout/pokeemerald-expansion/blob/e8bd1cd7b03fc032ea37e3ecd38b379b5d01a1e7/map_data_rules.mk#L42):
CreateProcess error 87 on a roughly 40K-character expanded mapjson invocation.
Full output is in `probes/x0_windows_build_failure_2026-09-26.txt`. The coordinator
redirected the build to Linux; **neither the Windows patch nor its wrapper
workarounds are used in the reference build**. The unused bootstrap additions
were removed. Upstream source is built unmodified on Linux.

## 4 MODEL evidence

`python -m pytest tests/unit/test_build_expansion.py -q`: 16 passed.
`python -m ruff check tools/build_expansion.py tests/unit/test_build_expansion.py`:
All checks passed. Tests use synthetic artifacts, without network or compiler use.
Verbatim output: `probes/x0_checks_2026-09-26.txt`. Both real output directories
also pass local `--check`.
`--check` validates the exact lock digest, receipt metadata, file sets, sizes,
SHA-256s and ROM SHA1/MD5. It does not rerun the compiler or prove reproducibility.

## 5 Limits carried forward

- Compiler status remains provisional until the owner signs XG0.
- Native Windows is unsupported. Its successful host probes do not qualify xPack
  for expansion builds. There is no Windows-versus-Linux ROM hash cross-check.
- Two builds on one pinned VM are a repeatability control, not independent
  reproduction on another Linux machine. No second Linux-host cross-check exists.
- ROM and `.elf/.map/.sym` outputs stay under ignored `.cache/expansion-output/`;
  no ROM is committed or published. Remote runs remain under
  `~/slink-exp/<source-sha>/<unique-run>/`.
- The wrapper refuses tool/package/distro drift. Repinning requires renewed
  two-build evidence. Remote builds use a process deadline and remote `timeout`;
  output receipts are transferred last.
- X1 offsets/data generation and all game runtime gates remain separate work.

## 6 Owner decisions

Coordinator directions received 2026-09-26:

1. "go with the portable native route, as a bounded experiment" — attempted;
   evidence retained, no system installs.
2. "Authorized: ONE explicit, recorded host-tool source patch" — tested on
   Windows; historical evidence only, excluded from the Linux reference build.
3. "the reference build moves to the owner's Linux VM" and "The owner authorized
   apt-installing the upstream packages on the VM" — Linux used; missing-package
   set empty, so no apt transaction was executed.

Requested at XG0: sign the Linux compiler/source/config pin and completed
repeatability evidence; acknowledge native Windows unsupported and the absence
of an independent second-host build. No runtime/admission approval is requested.

## 7 How to verify this draft

From the assigned worktree (SSH alias must already be configured):

```powershell
python -m pytest tests/unit/test_build_expansion.py -q
python -m ruff check tools/build_expansion.py tests/unit/test_build_expansion.py
python tools/build_expansion.py --host hgbox --output .cache/expansion-output/verify-a
python tools/build_expansion.py --host hgbox --output .cache/expansion-output/verify-b
python tools/build_expansion.py --check --output .cache/expansion-output/verify-a
python tools/build_expansion.py --check --output .cache/expansion-output/verify-b
```

Choose unused output directories. Compare `rom.sha1` in both `receipt.json` files;
the exact commands and recorded hashes for this card are in the repro receipt.
