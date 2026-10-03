# Gen 4 companion plan (HG/SS + hg-engine), draft 2026-10-02

**Status:** a draft for coordinator review and owner sign-off. Nothing here is built. Facts come from `FEATURE_BAR.md` (cited as FB) and repo files. Anything not yet proven is marked UNKNOWN.

**Authority:** `docs/gen4/reviews/DECISIONS_2026-10-01.md`, the owner rulings of 2026-10-02:
- the companion is REQUIRED for the first RC at the Gen 1/2 bar;
- trade is in the minimum;
- two artifacts;
- no peer ghost and no native message boxes;
- the shared NDS stack with Gen 5 has the go-ahead.

## 1. Scope

**IN (the four required features, FB table):**

| # | Feature | Gen 4 shape (FB) |
|---|---|---|
| 1 | Beacon + ABI + capability handshake, with liveness | Mailbox in a proven-free NDS span, with a cookie and a moving counter (Gen 2 model). Everything else depends on it |
| 2 | Native sound codes, capability-gated | A semantic-code table plus one service on the field task frame; a reserved SE handle polled via `NNS_SndPlayerReadDriverTrackInfo` (FB, sound section) |
| 3 | START-menu SLINK row + native info panel, capability-gated | Repurpose the dead `START_MENU_ACTION_7` or `RETIRE` slot in `src/start_menu.c`, plus a panel overlay cloned from the trainer-card OverlayManager shape (FB, items 3-4) |
| 4 | Receptionist trade | The host stages encrypted blobs (`lua/gen4/pk4.lua` `encrypt_party`); the ROM commits with `Party_SafeCopyMonToSlot_ResetAprijuiceModifiers`; the branch is the `std_nurse_joy` common script (FB, items 3-4) |

**OUT:**
- peer ghost and native message boxes (owner deferrals, `server/manager.py:189`);
- battle calc;
- phone-call names (HGSS has no surface; the panel is the substitute);
- the version string (optional, not planned);
- the checkpoint/safe-write evaluator stays host-side (`lua/gen4/safety.lua`);
- Platinum, and the Gen 1 `CAP_TRADE` inconsistency (`patch/gen1/src/slink.asm:163-164`, another lane's issue; Gen 4 MUST advertise `CAP_TRADE`).

## 2. Architecture

**Two artifacts (owner ruling), one design:**
- **A. HG/SS.** Patch the PINNED pret `pokeheartgold` source (`data/gen4_sources.lock.json`, pin `ad7a3afa`; see the `reference_gen4_pret_pinned_tree` memory) with a new overlay plus hooks, then rebuild. The output is distributable as a diff against the pinned vanilla dumps. This is the Gen 2 model: `tools/build_gen2_companion.py` copies `patch/gen2/src/*` into a fresh pinned checkout, builds, writes `patch/dist/*.ups` via `patch/tools/make_ups.py`, and records provenance. The pret tree is never edited in place; the build runs in a cache directory, like `.cache/gen2-build`. There is no slack in vanilla HG/SS (FB, build shape), so appending bytes is not an option.
- **B. hge.** A `src/slink/` overlay module plus one `hooks` line inside the owner's hg-engine fork (a SLink branch), built by the fork's own make. There is no post-build patch (FB). The result is a NEW pinned hge build; the current pin is `cb2dc435`. The build runs on the owner's `hgbox` (`tools/gen4_hge_build.py`, ssh, outputs under `.cache/gen4/hge/build-<commit12>/`). Whether the box is reachable for the C6 build is UNKNOWN.

**Layers:**

| Layer | Path | Owns |
|---|---|---|
| Shared NDS | `patch/src/nds/common/` + `tools/nds_*` | ABI header, producers, byte-preserving ROM span writer, pin/receipt schema. Gen 5 leads cards 1-3 (writer, ABI/producer extraction, PK45 cipher plus residency injection); Gen 4 reviews and co-owns |
| Per-title | `patch/src/nds/gen4/` | HG/SS pret overlay source, hge overlay source, mailbox placement, sound-code table, panel, trade commit. Game facts only |
| Build | `tools/build_gen4_companion.py` (new, modelled on `build_gen2_companion.py`) | Pinned checkout copy, overlay apply, make, `main.elf`, diff, provenance |
| Host | `lua/gen4/client.lua`, plus a Gen 4 panel/trade host | Beacon read, capability gating, blob staging and the lease state machine, panel payload |

**Shared vs game-specific.**
- **Shared:** lifecycle (probe, handshake, bounded hold, reset latch), transport, state and presentation. These generalize `lua/gb_panel.lua`, `lua/gb_trade_lease.lua`, `lua/gb_checkpoint.lua` and `docs/shared-gb-*.md`. The GB `patch/gb/slink_abi.inc` is the ABI precedent; the NDS ABI header lives in `patch/src/nds/common/`.
- **Game-specific:** mailbox address, SE ids, the start-menu and overlay integration, the trade commit and std script, save and record layout.
- **Host reuse rule:** extend the GB-shaped modules only if Gen 4 can bind them without touching Gen 1/2 behaviour. Otherwise add `lua/nds/panel.lua` and `lua/nds/trade_lease.lua` beside `lua/nds/hook_binding.lua` and keep the GB files untouched. Any edit to `lua/*.lua`, `lua/core/**` or `server/**` stales the Gen 2 digest, so it goes into the single shared window (C7).

**Gen 3 precedent for trade:** `patch/src/handlers.c` stages an opcode plus blob; Gen 4 follows that shape (FB item 4). The cipher is never re-implemented in the ROM.

## 3. Ordered cards

Order follows FB. One change: the pret build (C0) is first because `main.elf` is the only way to close the mailbox question, and C1 is gated on it. Cards C2-C5 share one mailbox and ABI, so C2 must land before the others. C3, C4 and C5 can run in parallel after C2 and share nothing except the ABI header.

The "Shared?" column marks a touch of `lua/*.lua`, `lua/core/**` or `server/**`. "S/M/P" is the exit-evidence class (SOURCE, MODEL, PHYSICAL).

| Card | Exclusive files | Prereq | First falsifier | Exit evidence | Shared? |
|---|---|---|---|---|---|
| **C0** pret pinned build | `tools/build_gen4_pret.py` (new), `data/gen4/pret_build_provenance.json`, a `.cache/gen4/pret-build/` copy | G0 pins; toolchain UNKNOWN | An unmodified build whose ROM sha1 differs from the pinned vanilla dump (fails the card) | S: byte-identical HG and SS ROMs, `main.elf` with section headers and arena-Lo, a recorded build duration and toolchain pins | No |
| **C1** mailbox proof | `tools/gen4_mailbox_census.py` (new, cf. `tools/gen2_mailbox_census.py`), `lua/tests/probe_gen4_mailbox.lua`, `tests/live/test_gen4_mailbox.py`, receipts | C0 for HG/SS; the hge build for hge; G1 hook rows d, h, n | A control address that the game is known to write must trip the watch (known-positive control) | S: ELF gap and arena table. P: a write-watch over boot, field, battle, menu and SAVE with zero foreign writes on HG, SS and hge. Output: ONE accepted address per artifact, or "no address, escalate" | No (lua/tests only) |
| **C2** beacon, caps, liveness | `patch/src/nds/common/abi.h` (Gen 5 card 2 owns, Gen 4 co-owns), `patch/src/nds/gen4/beacon.*`, `lua/gen4/companion.lua` (new) | C1, shared cards 1-2 | Boot with the patch and then New Game: a stale cookie must NOT read as live (Gen 2 liveness rule) | S: ABI bytes in the built ELF. M: lupa world for cookie, counter and capability gating. P: hello and caps read live on HG, SS and hge | No (new gen4-only file). `lua/gen4/client.lua` hookup is deferred to C7 only if it touches shared state, UNKNOWN |
| **C3** sound | `patch/src/nds/gen4/sound.*`, `tests/unit/test_gen4_sound_codes.py` | C2 | A code written to the mailbox while the field task is inactive must not play, and a held code must expire (bounded hold) | S: code table and `PlaySE` call site. P: audible and trace-verified SE on all three artifacts (success, failure, boo, notify). Open: the SE id choice is a content decision | No |
| **C4** START panel | `patch/src/nds/gen4/start_menu_hook.*`, `patch/src/nds/gen4/panel_overlay.*`, panel-payload layout in the ABI | C2; C1 for any new RAM | The start menu in a save without the capability must not show the SLINK row (capability-gated); the row at fixed display slots 7/8 (`ACTION_9`/`_10`) must stay unmoved | S: `sStartMenuActions` bytes and the cleared inhibit bit. M: payload round trip. P: a screenshot of the panel on the top screen and the touch screen, plus the menu closing without a leak, on HG, SS and hge | No |
| **C5** trade | `patch/src/nds/gen4/trade_*`, `lua/nds/trade_lease.lua` (or an extended `gb_trade_lease.lua`), the `std_nurse_joy` branch | C2, C4 panel for UX; the shared PK45 cipher (card 3) | An unmodified save plus a staged blob with a bad checksum must be refused, and a partial commit must leave the party byte-identical | S: confirmed std dispatch, commit offsets. M: lease state machine and blob round trip. P: duo exchange on HG-HG, SS-SS and hge-hge with the native SAVE and a cold-reload witness (`tools/e2e_duo.py` row). (Box delivery dropped: owner ruling 2026-10-02, trade is PARTY-ONLY; see C5_TRADE_SPEC.md) | Possibly (host lease). Batched into C7 if so |
| **C6** hge in-fork module + rebuild + re-pin | The fork: `src/slink/`, one `hooks` line (SLink branch); in SLink: `data/gen4_sources.lock.json` and `tools/gen4_hge_build.py` | C2-C5 source in a stable form; owner's fork access | A fresh build whose `test.nds` sha1 is not reproducible (the tool's own finding) | S: build sha1, the new pin. P: C1-C5 receipts on the new hge | No |
| **C7** distribution + admission | `server/patcher.py` (`TARGETS`), `server/manager.py` (`COMPANION_TITLES`, D13), `patch/dist/SLink-HeartGold.ups` and `SLink-SoulSilver.ups`, hge distributable, `tools/verify_gen4_release.py` rows, `tests/unit/test_manager_option_labels.py` | C1-C6; G3a window | A ROM patched with the UPS differs from the build output (round-trip), or the Manager lists HG/SS before the G4 sign-off | S/M: round-trip UPS, unit tests, Gen 1/2/3 lanes green. The one batched shared diff | **YES**, the single shared window for all of `lua/*.lua`, `lua/core`, `server/**` |
| **C8** PHYSICAL re-run | Receipt files only | C7 | A receipt bound to a vanilla sha1 must fail verification on a patched ROM (it forces a re-run) | P: every G1-G4 PHYSICAL receipt re-run on the patched HG, SS and hge | No |

**Batching rule:** every shared-code edit (a possible `lua/gen4/client.lua` hookup, `lua/nds/*` if shared, `server/**`) lands once in C7, together with the Gen 2 notification and the ~2 h re-sweep (`feedback_ping_gen2_before_server_changes`). New `lua/gen4/*` and `lua/nds/*` files that touch nothing shared can land earlier.

**Why not parallelize C6 early:** the hge fork must carry the stable overlay source. Doing C6 before C2-C5 settle would force a re-pin per card.

## 4. Gates fed

| Gate | What the companion contributes | Owner signs |
|---|---|---|
| G3 | C2 liveness, C3 and C4 host behaviour in the lupa world (MODEL); the checkpoint stays host-side and unchanged | Each exercised kind PHYSICAL |
| G3a | The C7 shared diff is a G3a item (§4.5-4.6 of `docs/gen4/PLAN.md`), but admission waits for G4 (D13) | The shared diff with the required-check inventory |
| G4 | The patched artifacts boot, trade and show the panel. The scenario inventory is re-run on patched ROMs (C8). The release ZIP boots HG, SS and hge with the patch composed | Owner live HG-SS and hge-hge sessions |
| G6 | `tools/verify_gen4_release.py` requires the companion cells (C1-C5, C8) as required IDs per artifact, with no OPEN or skip in a shipped artifact's cells | Tag authority |

G0-G2 stay valid on the pinned vanilla images (owner ruling). Build-bound receipts are invalidated by a rebuild or re-pin (G1 text).

## 5. Open questions and risks

1. **Mailbox unproven (FB).** The 15 ARM9 gaps are candidates, not heap. Risks: symbol-less statics inside a gap, hge's heap and BSS changes, SDK `os_irq` data near the largest gap. A single address may not work on all three artifacts; the fallback is per-artifact addresses (the Gen 2 precedent, `slink_mailbox_crystal.asm` and `..._goldsilver.asm`). UNKNOWN until C1.
2. **Pret build toolchain and duration: UNKNOWN.** C0 may find a non-reproducible ROM (compiler pin, the BLZ-compressed ARM9, overlay compression). If C0 cannot reproduce the pinned dumps byte for byte, the "diff against the dumps" distribution is not valid and needs an owner decision. This is the largest schedule risk.
3. ~~**Box delivery (FB)**~~ CLOSED by the owner ruling (2026-10-02): the trade is PARTY-ONLY (slot overwrite), so a full party cannot arise. The companion ScrCmd is opcode 1 (FEATURE_BAR "Script command slot").
4. **`std_nurse_joy` dispatch:** the reachability generator's CallStd resolution (`3745647c`, `sScriptBankMapping`) suggests ONE std script in common-script member 3. Confirmed on pret only; hge's script bank is UNKNOWN. Confirm before C5.
5. **hge overlay-1 identity:** hge does not hook the start menu, so it is the vanilla binary and one C4 site should serve both. Re-prove against the hge sha1; hge's overlay 1 may differ. UNKNOWN. HG/SS ARM9 is BLZ-compressed and hge's is raw (shared-writer constraints).
6. **hge in-fork dependency:** the owner's fork and `hgbox` are required for C6. A repin invalidates build-bound receipts.
7. **Shared-stack timing:** Gen 5 leads cards 1-3. If those slip, C2 cannot use the shared ABI. Fallback: a Gen 4-private header, accepted by the owner, migrated later. This is a plan risk, not a decision made here.
8. **Hook-budget interaction:** the companion's ROM-side code must not add BizHawk exec hooks. The owner's 1x ruling allows zero steady-state hooks and one on-demand hook (the D7 write seam), so the host reads the mailbox by polling only. The polling cost is measured with the row f method (`DECISIONS_2026-10-01.md`, performance) before the companion ships.
9. **Sound content:** the SE ids for the four semantic codes are a content choice. The owner or coordinator should pick them, since FB leaves it open.

## 6. What the owner signs

- **Now:** this plan's card order and the C0 pass criterion (a byte-identical rebuild).
- **After C1:** the accepted mailbox address per artifact, or an escalation if none is proven.
- **At C6:** the new hge pin.
- **At G4:** the live sessions on patched ROMs.
- **At G6:** the release and tag.
