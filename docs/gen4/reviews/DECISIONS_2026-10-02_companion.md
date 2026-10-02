# Gen 4 companion decisions, 2026-10-02

- **Companion plan signed.** Owner chose "Approve" for the card order in `docs/gen4/companion/PLAN.md` (`12e306e0`): C0 pret build → C1 mailbox → C2 handshake → C3/C4/C5 → C6 hge in-fork + re-pin → C7 distribution + shared window → C8 patched re-runs. The C0 pass rule: an unmodified rebuild must match the pinned ROM sha1 exactly.
- **C0 build environment.** Owner chose "Install wine on hgbox (Recommended)".
  - The coordinator installed `wine` 9.0 on hgbox (Linux Mint 22.3, 16 cores) via apt, with passwordless sudo, on 2026-10-02.
  - The proprietary Metrowerks `mwccarm` and Nitro SDK archives are fetched from pret's own GitHub workflow assets (`.devcontainer/setup-devcontainer.sh` in the pinned tree), as part of the approved route.
  - `make` verifies `heartgold.us/rom.sha1` = `4fcded0e…`, the same ROM the live lanes use.
  - Open: INSTALL.md names NitroSDK 4.2 while the devcontainer fetches 3.2. Try 4.2 first and fall back to 3.2; the sha1 check is the oracle.

## Owner rulings, 2026-10-02 (late)

- **Trade delivery = PARTY ONLY.** No "deliver to box" arm. Owner: "It should not. In party only."
  - The companion trade copies the native NPC-trade shape (FEATURE_BAR "Full-party decision"): the player picks a party slot (`GetPartySelection`, 255 = cancel), and the received record overwrites it via `Party_SafeCopyMonToSlot_ResetAprijuiceModifiers` (`src/party.c:97`).
  - So a full party cannot arise, and no PC/box commit path, `PCStorage_PlaceMonInFirstEmptySlotInAnyBox` scratch, or `CountPCEmptySpace` gate is built.
  - The shared ABI's box-arm stage length and `SLINK_RB_COMMIT_MUTATES_INPUT` are not exercised by Gen 4.
- **FAILURE sound: PENDING** (owner: "Sound can pend for now"). It stays open, with no substitute chosen. SUCCESS 1501 / NOTIFY 1500 stand, BOO 1536 stays provisional. C3 may ship without code 2 wired, and must say so.
