# Gen 4 companion decisions, 2026-10-02

- **Companion plan signed.** Owner chose "Approve" for the card order in `docs/gen4/companion/PLAN.md` (`12e306e0`): C0 pret build → C1 mailbox → C2 handshake → C3/C4/C5 → C6 hge in-fork + re-pin → C7 distribution + shared window → C8 patched re-runs. The C0 pass rule: an unmodified rebuild must match the pinned ROM sha1 exactly.
- **C0 build environment.** Owner chose "Install wine on hgbox (Recommended)".
  - The coordinator installed `wine` 9.0 on hgbox (Linux Mint 22.3, 16 cores) via apt, with passwordless sudo, on 2026-10-02.
  - The proprietary Metrowerks `mwccarm` and Nitro SDK archives are fetched from pret's own GitHub workflow assets (`.devcontainer/setup-devcontainer.sh` in the pinned tree), as part of the approved route.
  - `make` verifies `heartgold.us/rom.sha1` = `4fcded0e…`, the same ROM the live lanes use.
  - Open: INSTALL.md names NitroSDK 4.2 while the devcontainer fetches 3.2. Try 4.2 first and fall back to 3.2; the sha1 check is the oracle.
