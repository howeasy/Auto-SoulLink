# HS-4 — in-game lifecycle notices (implementation spec)

Status: accepted (coordinator, 2026-09-14). Source: Gen1-CodexPeer task cx-a9c9e6cd at `f717ec9`,
read-only. READY WAIT(R5b-2 round 2 frozen: it owns `lua/gen1_client_entry.lua` and adds the
replaceable checkpoint-status surface this card reuses).

## (1) Design
- A client-local REPLACEABLE lifecycle line driven by server-authored read-only lifecycle state,
  plus a durable server-authored "death applied" toast. A purely server-command solution cannot
  show the pre-admission wait and would add pending commands to the very release gate it describes.
- Existing notices: `build_notice(kind, surface, text, r, g, b, frames)` →
  `{cmd: "hud_notice", schema: "slink-gen1-hud-notice-v1", kind, surface, text, r, g, b, frames,
  issued_at, expires_at}`; Lua validates and draws/receipts immediately
  (`server/gen1_hud_feedback.py:103-122`; `lua/gen1_hud_service.lua:42-49,160-179`).
- Server lifecycle projection: derive per-player enrollment-settled from the SAME
  initial/bootstrap/initial-save receipt or resumed-enrollment predicates `_service_release_ready`
  uses; expose `{own_settled, peer_settled, peer_label, both_ready}` on the authenticated
  control/status path. Do not emit from `_service_release_ready` itself (repeatedly evaluated
  predicate, `server/gen1_runtime.py:294-309`). Admitted/online ≠ enrolled.
- Death applied: after `verify_force_faint_receipt` succeeds and the phase becomes
  `pending_memorial`, append a notice to BOTH players in the SAME ACK journal commit, behind the
  physical commands, naming the affected player's label (never an ambiguous "partner");
  cover the instruction-based faint ACK path too (`server/gen1_faint_runtime.py:286-287,302-311,
  328-345`). Replay must not queue another toast.

## (2) Kinds and strings
- Add kind `lifecycle` to both validators (`gen1_hud_feedback.py:18`;
  `gen1_hud_service.lua:41-43`); never mislabel status as `violation`/`link_pending`.
- Persistent `hud_state` accepts only `mode=game_over` (`gen1_hud_feedback.py:125-139`;
  `lua/hud.lua:354-358`) — not a general status mechanism; reuse R5b-2 round 2's replaceable
  checkpoint-status surface.
- Strings (≤30 ASCII; labels normalized/truncated BEFORE assembly; A/B fallback labels):
  `SLink: reach first checkpoint`, `SLink: save verification`, `SLink: connected; wait B`,
  `SLink: both players ready`, `SLink: checkpoint pending`, `SLink: checkpoint saved`,
  `SLink: abandoned: <reason≤12>`, `B: death applied`. `compact_text` caps at 30 and the HUD also
  fits pixel width (`lua/hud.lua:215-230`).
- Waiting/pending line persists until replaced; ready/saved toasts expire after 180 frames. Never
  queue the wait text every tick (`H.present` is FIFO, `hud.lua:215-237`). Clear/recompute on
  disconnect, VM restart and lifecycle change; never persist a stale "ready".

## (3) Client-local startup draw
- After `M.start` succeeds, beside the console log at `lua/gen1_client_entry.lua:679-682`:
  `service.overlay.present({surface="hud", text="SLink: reach first checkpoint", r=255, g=220,
  b=100, frames=180})` — `H.present` draws now, including while held (`H.show` only queues).
  Replace it with the shared R5b status setter when available; a held-screen state change must
  draw immediately (`client_entry.lua:527-528`). "Both players ready" only from server
  `both_ready`; "saved" only for the journal-confirmed checkpoint; "abandoned" only from the server
  result.

## (4) Tests
- Extend `tests/unit/test_gen1_hud_feedback.py` schema/bounds (:108-156) and the real ACK/replay
  pattern (:465+): one durable notice after a valid force_faint receipt, none on a bad receipt, none
  on replay, both recipients name the affected side.
- lupa local-surface test (`tests/unit/test_shared_hud_transients.py:5-11` setup): startup line
  visible while held, replacement removes stale text, no FIFO growth, long/non-ASCII labels fit; A
  settled/B absent, B arrives with initial-save pending, both settled, disconnect, resume Continue,
  checkpoint upload-vs-confirmation, abandoned reason. Test the production client integration.

## (5) Files / falsifier
`server/gen1_hud_feedback.py`, `lua/gen1_hud_service.lua` (kind); `server/gen1_runtime.py` +
the control/status response seam (read-only enrollment projection); `server/gen1_faint_runtime.py`
(both ACK paths); `lua/gen1_client_entry.lua`; `lua/hud.lua` only if the R5b setter has not
supplied it; tests. Falsifier: a player sees ready/saved/death-applied before the verified server
transition, or a stale wait line after it. No new HUD framework; no reuse of game_over state.
