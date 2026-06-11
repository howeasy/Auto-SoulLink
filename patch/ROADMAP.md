# SLink Companion Patch — Lua→Native Migration Roadmap

Ranked candidates for moving remaining Lua-side functionality into the native patch, from the
full-branch audit (June 2026). Each entry lists what it replaces, the discovery still needed, what
existing infrastructure it reuses, and risk. The proven discovery workflow applies throughout:
headless BizHawk + savestates (`E:/Howard/Bizhawk/GBA/State/slink_*.State`), one-shot
`lua/tests/probe_*.lua` scripts, `patch/tools/disasm.py`, and `build.py`'s self-checked pipeline.

**Already landed** (this branch): per-run feature toggles (native_messages / native_sounds /
battle_calc kill-switch / pc_trade_npc / native_battle_control), `OP_MEMORIALIZE` (26,
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

## 2. Explode-mode native battle control re-enable (MEDIUM)

**Replaces:** the Variant-3 menu-skip RAM writes + per-frame reinforce (`pending_explosions`,
gen3_frlge_client.lua §force_explode). `NATIVE_BATTLE_CONTROL_ENABLED=false` after a live softlock.
**Discovery:** re-derive the action/move-menu controller thunk addresses for this exact RR build
(`HandleInputChooseMove` path; literal-pool xrefs to `gMoveSelectionCursor` via `disasm.py`), then
re-validate `OP_FORCE_MOVE_SLOT` with `slink_actionmenu.State` / `slink_movemenu.State`.
**Risk:** the original open-menu softlock — requires byte-exact addresses; keep Variant-3 as the
permanent fallback.
**Gate:** two-instance live run with real turn execution (USER).

## 3. Migrate faint/whiteout consumers onto the EvRing (FAST-PATH LANDED 2026-06-11)

**Landed:** EV_PLAYER_FAINT is now a faint-confirm fast-path (skips the debounce timer under the
same single-pending safety rule as the counter delta; every confirmed faint consumes a ring
credit so credits can't go stale) and EV_OUTCOME==2 accelerates the whiteout declaration
(one-shot, consumed on send). Credits are battle-scoped (reset at battle start + both
battle-end cleanups). The per-frame polls remain the unpatched fallback / safety net.
**Remaining (future):** the authority swap — delete `readFaintCounters` polling + the debounce
timer entirely once the ring has soaked in real runs.

## 4. More EvRing producers: catch / evolution / save-write (MEDIUM-HIGH)

**Replaces:** per-frame party decryption for capture sniffing (`index_party` species/PID polling)
and the post-save reconcile races.
**Discovery (per producer):**
- *Catch:* hook or poll `gPlayerPartyCount`/box insert path — possibly pure native polling of
  count + last-slot PID (no detour), same pattern as the faint producer.
- *Evolution:* `EvolutionScene` / trade-evo completion — find one BL site via `disasm.py`; or
  native-poll species-changed per slot (cheap in C).
- *Save-write:* `gSaveBlock2Ptr` write path / save task — one BL hook so Lua can drain pending
  syncs before the save commits.
**Risk:** save hook runs near I/O — flag-and-return only, never block.

## 5. Native day/night tint for the ghost (MEDIUM)

**Replaces:** peer_ghost_npc.lua's tint derivation + palette writes (now signature-gated, so the
steady-state cost is already small — this is polish).
**Discovery:** RR/CFRU's tint engine (`ApplyPaletteFade`/day-night blend) — find the blend constants
or the per-frame tint state so `drive_ghost` can apply the ratio natively when stamping slot 15.
**Risk:** flicker if applied off-tick; coordinate with the Lua writer (remove one side entirely).

## 6. Native link-status screen (HIGH effort, UX-transformative)

**New:** a persistent field HUD (your linked mon + partner's, HP/status, badges) drawn natively
(window system / `run_choices`-style infrastructure), replacing transient HUD popups for state.
**Discovery:** field window templates + VRAM budget (`gWindowTemplates`, `CopyWindowToVram`),
layout probes via screenshots. **Risk:** VRAM/OBJ conflicts with map sprites; script reentrancy.

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
