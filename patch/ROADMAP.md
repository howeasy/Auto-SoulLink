# SLink Companion Patch — Lua→Native Migration Roadmap

Ranked candidates for moving remaining Lua-side functionality into the native patch, from the
full-branch audit (June 2026). Each entry lists what it replaces, the discovery still needed, what
existing infrastructure it reuses, and risk. The proven discovery workflow applies throughout:
headless BizHawk + savestates (`E:/Howard/Bizhawk/GBA/State/slink_*.State`), one-shot
`lua/tests/probe_*.lua` scripts, `patch/tools/disasm.py`, and `build.py`'s self-checked pipeline.

**Already landed** (this branch): per-run feature toggles (native_messages / native_sounds /
battle_calc kill-switch / pc_trade_npc), `OP_MEMORIALIZE` (26,
live-proven), the `EvRing` event-push ring with faint-settled + battle-outcome producers
(live-proven) **+ the Lua fast-path consumers (§3)**, the `slink_battletext_hook` calc-disable
path, ghost **lead extrapolation** (§1), and the **two-instance headless E2E harness**
(`tools/e2e_duo.py` — faint/boxsync/trade/ghost scenarios; retires the manual two-instance gate
for everything except the final visual feel check).

---

## 1. ~~Step-stream ghost motion~~ — DONE differently: LERP **lead extrapolation** (2026-06-11)

**The step ring was REJECTED:** it was designed for the abandoned held-movement driver; the
shipping driver is the clone-model sub-pixel LERP (`drive_ghost` follows broadcast world-px at
constant engine velocity), and a step ring would have meant reverting to engine walks. The actual
residue was the ghost **pausing at a stale sample** until the next ~20 Hz target arrived.
**Shipped fix:** (a) `drive_ghost` extrapolates up to `GHOST_LEAD_CAP_PX=12` past a stale target
in the partner's facing while `mv==1`, never stepping backward along the facing axis (fresh
targets absorb the lead); new `GhostState.leadpx` @ +40, boot-zero = old behavior. (b) Sender at
30 Hz while moving (20 Hz idle). (c) Sender `mv` now means "position actually advancing" — a wall
bump used to broadcast `mv=1` forever and pin the ghost 12 px past the bumper.
**Proven:** `test_live_ghoststutter` (steady ≤1 + jittered-feed ≤2 passes: measured **0** frozen
frames both) and the two-instance `tools/e2e_duo.py --scenario ghost` real-feed metric
(at-target-stall 28 → **0**, behind-stall ≤1). Remaining gate: USER visual feel check.

## 2. ~~Explode-mode native battle control re-enable~~ — CLOSED (2026-07-24): path deleted

The `--native-battle-control` flag, the `native_battle_control_enabled` selector, the
`arm_native_explode` / `pending_force_moves` / `mb_explode_queue` machinery and the abandoned
rampage engine-lock (`LOCK_STATUS2_VALUE`, nil on every Gen 3 profile) are **gone**.  The
Variant-3 menu-skip RAM path is the single production mechanism for both explode and faint.

Rationale: the native controller-pointer swap softlocked in real two-sided play, the Lua path
ships reliably, and carrying two implementations of the same behaviour was the main thing making
the codebase read as unfinished.  `OP_FORCE_FAINT` (2) and `OP_FORCE_MOVE_SLOT` (5) REMAIN in the
ROM — built, headless-validated by `test_live_forcemove.lua`, and reserved in the ABI — so
re-enabling later is a client-side change, not a patch rebuild.  Anyone reviving it needs to
re-derive the action/move-menu controller thunks for the exact RR build (`HandleInputChooseMove`;
literal-pool xrefs to `gMoveSelectionCursor` via `disasm.py`) and gate on a two-instance live run
with real turn execution — the headless one-sided gate only proves the move COMMITS.

## 3. Migrate faint/whiteout consumers onto the EvRing (FAST-PATH LANDED 2026-06-11)

**Landed:** EV_PLAYER_FAINT is now a faint-confirm fast-path (skips the debounce timer under the
same single-pending safety rule as the counter delta; every confirmed faint consumes a ring
credit so credits can't go stale) and EV_OUTCOME==2 accelerates the whiteout declaration
(one-shot, consumed on send). Credits are battle-scoped (reset at battle start + both
battle-end cleanups). The per-frame polls remain the unpatched fallback / safety net.
**Remaining (future):** the authority swap — delete `readFaintCounters` polling + the debounce
timer entirely once the ring has soaked in real runs.

## 4. ~~More EvRing producers: catch / evolution~~ — LANDED 2026-07-24 (save-write DECLINED)

**Shipped:** `EV_PARTY_ADD` (4) and `EV_EVOLVE` (5), both by **pure native polling — no new detour
points**. `drive_events` watches `gPlayerPartyCount` and the six per-slot species (CFRU NO_ENCRYPT:
raw u16 at `mon + 0x20`) and pushes an event on each edge. Seven reads a frame, versus the per-frame
party DECRYPTION the Lua side does today. The latches (`prim`, `pcnt`, `spc[6]`) live in the ring
struct; `prim = 0` (the EWRAM boot default) makes the next frame latch only, so an unpatched or
pre-config session never sees a burst of spurious events — the standard boot-default invariant.
Suppressed while `SwapState.active` (a borrowed party would read as six evolutions) and re-primed
when the real party returns.
**Gate:** `lua/tests/test_live_partyevents.lua`, run by `tests/live/test_lua_gates.py`.
**Consumers (2026-07-25).** Every event the ring produces now has one:
- `EV_PLAYER_FAINT` -> the faint-confirm fast path (skips the debounce timer), `EV_OUTCOME` ->
  accelerates the whiteout declaration. Both from §3, unchanged.
- `EV_FOE_FAINT` -> diagnostics only, deliberately. Nothing SLink enforces depends on a foe faint.
- `EV_PARTY_ADD` / `EV_EVOLVE` -> they **own species-change detection on a patched ROM**, and
  `index_party` reads no species at all there; unpatched ROMs keep the direct read. They also
  feed a cross-check that matches every event against what Lua independently observed and counts
  disagreements (`EV.agree` / `EV.disagree`) — the soak instrument §3's authority swap is waiting
  on. Both paths are free when idle: one integer test per frame.

  **This is the first place the ring measurably paid for itself, and it was not theoretical.**
  The first version polled species every frame *alongside* the ring. That added a 6-slot read per
  frame to the client, and the ghost duo's worst behind-target stall went from **2 frames to 5-7**
  — past the scenario's hard gate of 3. Moving detection onto the ring took it straight back to 2.
  Per-frame Lua work in this client is not free, and `tools/e2e_duo.py --scenario ghost` is a
  sensitive canary for it (`GHOSTSTALLS` in the result file breaks the stalls down by cause).

**A real bug the evolution producer surfaced.** `index_party`'s combat-stats cache was invalidated
on `key ~= previous or level ~= previous`. An evolution keeps the same key (personality/OT are
untouched in Gen 3), and a **stone or trade evolution keeps the level too** — so after any
non-level evolution the cached Atk/Def/Spe/SpA/SpD stayed at their pre-evolution values
indefinitely. Species is now part of the invalidation key. Gated by `test_live_partyevents.lua`,
which asserts the ring fires in exactly that situation (species changes, key and level do not).

**Save-write producer: DECLINED, not deferred.** Its own risk note ("runs near I/O — flag-and-return
only, never block") is the whole problem: it is the only producer in this section that needs a BL
detour into the save path, RR ships no symbol map so the site would have to be found by disassembly,
and the payoff is closing a rare race that Lua already handles by draining pending syncs continuously
while in the overworld. Not worth a detour into the one code path where a mistake corrupts a save.

## 5. ~~Native day/night tint for the ghost~~ — LANDED 2026-07-24 (+ bike/surf/fishing avatars)

**Tint:** `apply_tint` in handlers.c now owns the ghost's palette outright. No RR tint constants were
needed — the ratio is MEASURED from the player's own slot each frame ((live palette RAM) / (unfaded
true colours), summed per channel) and applied to the partner's true colours. Writes UNFADED slot 15
= true colours, FADED slot 15 = tinted (the engine DMAs Faded->RAM), RAM slot 15 = tinted so the
current frame is already right. The roadmap's "coordinate with the Lua writer (remove one side
entirely)" is done: **the Lua tint block in `peer_ghost_npc.lua` is deleted**, so there is exactly
one writer and the off-tick flicker risk is structurally gone.

Recomputed every frame with no dirty-tracking. The Lua version had to signature-gate the recompute
(~80 interpreted ops); in C it is 3 divisions + 48 multiplies, cheaper than the gating would be —
and nothing to get stale. Note the blob links `handlers.o` alone with no libgcc, so `/` on a runtime
value emits `__aeabi_uidiv`; there is a small `udiv()` for this (same reason as `-fno-jump-tables`).

**Bike / surf / fishing avatars:** the ghost now spawns with the PARTNER's own `graphicsId` instead
of a fixed 16x32 stand-in, so the engine allocates the OAM shape/size and tile count their sprite
actually needs — which is exactly what the deferred variants needed (those frames are 32x32 / 16
tiles, and repointing `sprite.images` never changed the OAM geometry). `drive_ghost`'s existing
`gfxId != curGfx` respawn path handles mounting/dismounting; `peer_ghost_npc.lua` re-posts the gfxId
on change and forces an avatar re-forward onto the new sprite slot. The sender already broadcast the
partner's graphicsId — the receiver was discarding it.

**Gate:** `lua/tests/test_live_ghosttint.lua` (forces a known ratio on the player's slot and asserts
slot 15 scales by it, while unfaded keeps the true colours) plus the existing `test_live_ghostavatar`.
**Remaining:** the two-instance VISUAL check — mounting a bike / surfing in front of a real partner
is the only way to confirm the variant sprites read correctly on screen.

## 6. SOULLINK menu entry + in-game info screen (IN PROGRESS — restructured 2026-07-25)

**Was:** "a persistent field HUD (your linked mon + partner's, HP/status, badges) drawn
natively, replacing transient HUD popups for state."

**Now:** a **SOULLINK entry in the game's own START menu** (alongside POKéDEX / POKéMON / BAG /
SAVE / OPTION / EXIT) that opens a dedicated **SLink info screen** rendered from the live run
state. The point is to **remove the reliance on the web dashboard mid-run** — the player checks
the run without leaving the game.

Why this shape rather than a persistent HUD:
- A persistent field HUD competes with map sprites for VRAM/OBJ every frame and has to be
  suppressed in menus, battles, dialogue and cutscenes. A menu screen is drawn on demand, in a
  context the engine already owns, and costs nothing while it is closed.
- The player wants this information *deliberately* ("how is my partner doing?"), not glanced at
  constantly. That is a menu, not a HUD.
- It reuses the infrastructure the patch already has for in-context UI (the multichoice list,
  the party picker, the field message box) rather than inventing a new always-on renderer.

**Content (a GBA screen is ~28 chars x ~14 lines, so this is a real constraint):** linked pairs
with both halves' species/level/HP and alive/dead state, the partner's status, badge counts,
dead zones, and pending actions. Paginated if it does not fit.

### Plan (research + adversarial verification, 2026-07-25)

**Menu entry: take over dead action id 8, don't grow a 14th.** RR reads the menu's description and
action arrays through one base literal with hardcoded offsets and the two ranges abut
(`desc[13]` *is* `act[0].text`), so a 14th id structurally cannot own a description. Id 8 is a
second PLAYER row only `SetUpStartMenu_Link` appends. Four verified ROM word writes, no table
relocation, no instruction re-encoding. Full addresses in `patch/src/ADDRESSES.md` § "§6 SOULLINK
start-menu entry".

**Screen: a sibling of `show_choices_entry`, not an extension of it.** That function already does
the whole job (`CreateWindowFromRect` → `SetStandardWindowBorderStyle` → N ×
`AddTextPrinterParameterized` → `CopyWindowToVram` → `CreateTask`) but hard-rejects `count > 8` and
is option-list shaped. A `show_info_entry` sibling reuses the primitives with a fixed rect, keeps
the engine's input task (A or B closes and tears the window down for free) and adds **zero** new
`drive_ui` code — one new async opcode, `27 SHOW_INFO`, in the exact shape of `OP_SHOW_CHOICES`.

**The seam that makes this gateable:** the menu callback does not draw. It bumps `SI->opened` and
closes the menu; the frame hook notices `opened != drawn` at its existing `on_field()` gate and
runs the screen. So the hook and the screen are independently testable, and the screen still ships
if the hook is ever abandoned.

**Text staging is plain EWRAM, not opcodes** — the same idiom as `MB.write_message` /
`MB.set_battle_calc`. Pushing ~260 B of text through the single-slot mailbox would contend with
ghost/trade/msgbox traffic for no benefit.

### Steps (each gated before the next)

- [x] **0. Prove the EWRAM tail is really free.** `lua/tests/test_live_ewramtail.lua`. Was
      **required**, not ceremony: the region's freeness had only ever been asserted, and the
      literal-pool scan offered to shore it up did not survive verification. PASSES — 700 bytes,
      7 savestates, 5,100 frames, detector self-check per scene, zero writes.
- [x] **1. Menu hook only, nothing draws.** `SlinkInfo` @ `0x0203FD44`, `slink_startmenu_cb`,
      `slink_setup_start_menu`, the four `build.py` word writes. `+153 B` of ROM.
      `lua/tests/test_live_soullinkmenu.lua` PASSES: stock 6-row menu when disabled,
      `[1 2 3 4 5 8 6]` when enabled, callback fires on row 5 and no other row, and does not fire
      at all while disabled. (`lua/tests/test_live_startmenu.lua` pins the menu globals and the
      pre-splice shape independently.)
- [x] **2. The screen.** `show_info_entry` + `run_info()` + opcode 27, driven from staged EWRAM
      lines. `lua/tests/test_live_infoscreen.lua` PASSES. Redesigned to look native after the first
      version drew a plain multichoice list box: the player's own OPTIONS frame, a blue title with a
      right-aligned PAGE hint, a hairline rule, party-menu mon rows with `Lv` glyphs and HP bars on
      FRLG's own colour thresholds, and red for a dead mon. Row kind is derived from the staged
      field count, so the EWRAM contract did not change. Fixed a real bug on the way: the first
      window was 27x14 = 378 tiles against a 352-tile ceiling, overrunning the field message-box
      window.
- [ ] **3. Frame-hook path.** `opened != drawn` opens the screen with no opcode at all, so the row
      works even if the client is mid-round-trip.
- [ ] **4. Real content + pagination.** Lua composes the page from live run state.

**Known gap for step 4:** the client is *not* currently sent the link table. It does receive
`resolved_areas` / `unresolve_area` and a good deal of partner data (the whole partner party via
`replace_rival_team`, a full mon via `apply_trade`, live position/avatar via `ghost_pos`), but
pair-by-pair link state has no command. Step 4 needs a new server→client payload; design it then,
not now.

The invariants below apply in full — in particular each step needs its own headless
`lua/tests/test_live_*.lua` gate before any client wiring, and the boot-zero EWRAM default must
keep an unpatched-Lua session behaving exactly as it does today.

## 7. Area-change / encounter hooks (LOW value today)

Map-change polling is 2 bytes/frame — negligible. Only worth a producer if DexNav/encounter
interception (hard-ROM first-encounter enforcement) becomes a wanted feature; then discover the
wild-encounter init path (`BattleSetup`) and push `{species, area}` events.

---

## Deliberately staying in Lua

- **Server protocol + TCP pump** — the patch has no socket; Lua is the transport.
- **Party snapshot consistency / ordering** — Lua owns cross-frame sequencing and server acks.
- **Game detection + multi-ROM profiles** — the patch is RR-build-specific by design.
- **HUD overlay rendering** — emulator-side drawing; native paths exist where in-game UX wins
  (message box, battle notif) behind the `native_messages` toggle.
- **Box-to-box memorialize** — rare path (mon died while boxed); the Lua scan handles it,
  native `OP_MEMORIALIZE` covers the hot party case.

## Invariants for all native work

- One opcode in flight per frame; ack via the mailbox seq protocol.
- No mutable statics in the ROM blob (no .data/.bss) — all state in explicit EWRAM, documented in
  `ADDRESSES.md`, inside the validated free gaps below `0x0203FFFF`.
- Every EWRAM byte's BOOT DEFAULT (zero) must reproduce today's behaviour (cf. the inverted
  `SLINK_CALC_OFF` semantics) so an unpatched-Lua / pre-config session is never broken.
- Field scripts only via the `on_field()` gate; battle text only in-context (RunTasks / the
  battletext shim) — never from the raw frame hook.
- Each opcode lands with a headless `lua/tests/test_live_*.lua` gate before client wiring; client
  wiring always keeps the Lua fallback for unpatched partners.
