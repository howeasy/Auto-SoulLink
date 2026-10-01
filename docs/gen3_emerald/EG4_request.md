# EG4 request: Emerald release candidate (2026-09-26)

> **SIGNED 2026-09-27 by the owner in chat: "All gates are signed."** (Recorded by the combined Gen 3 coordinator, claude 30c21a7a. This covers every pending Gen 3 gate: G4, G5, EG4, XG1 and XG2. It is not approval of the master landing, which needs its own explicit owner approval, ruling 41.)

**Status: DRAFT — not signed.** Signing needs an explicit owner "yes" in chat.

- **Branch:** `claude/gen3-emerald-rc2` (local only: not pushed, not on master) =
  the EG4 candidate `claude/gen3-emerald-rc` + the docs sweep + the skip-wording fix + the lane
  (E6 calc, XG0 record, trade contract docs).
- **Cut for this request:** `94c980f3`. **Final cut:** `docs/gen3/probes/fc_SUMMARY_94c980f3_emerald.txt`
  (**24/24 PASS**, every row on attempt 1; receipts committed `d096ce46`). Previous cut `9c96e745`: 23/24 (only `unit_emerald`, on unexcused skips).
- **Plan:** `docs/gen3_emerald/PLAN.md` rows E4/E4b/EG4. **Ledger:** `docs/gen3_emerald/REQUIREMENTS.md`.

## 1 What EG4 signs

Emerald (BPEE, US/EU rev 0) becomes a supported **release-candidate** title on the new Gen 3
client. The four ruling-24 barriers are removed:

| Barrier | Change | Files |
|---|---|---|
| Launcher | The BPEE by-name refusal is gone; the Gen 3 route admits through `Entry.admit_routed` (one gate for `lua/slink.lua` and `lua/gen3/run.lua`; header-only and non-ROUTED packs refused by name) | `lua/slink.lua`, `lua/gen3/entry.lua`, `lua/gen3/run.lua` |
| Routing | `Entry.ROUTED.gen3_emerald = true` | `lua/gen3/entry.lua` |
| Profile | `titles.emerald.admitted = true` (generated) | `tools/gen_gen3_profile.py`, `data/games/gen3_emerald/profile.json` |
| Manager | `gen3_e` leaves `UNADMITTED_GAMES` | `server/manager.py` |

Also in the cut: the duo driver's TEST-ONLY admission seam is deleted (Emerald now runs through
production admission only); the ball-hunt duos use a 20-ball fixture (`emerald_catch{,_b}.sav`);
the Emerald calc trainer sets are checked against pokeemerald (E6: 178 corrections; 654 vendored
mons identity-checked, 343 ambiguous labels left unchecked and counted).

**RC-mandatory, NOT yet built (owner ruling 2026-09-26: "trainer names, Upcoming Key Trainers, the
calc's Prep tab are mandatory for RC"):** Emerald trainer names/classes, the Upcoming Key Trainers
panel and the calc Prep tab. Today these are RR-only: the Emerald adapter returns no trainer data,
and the UI gates the panels to RR. Work: trainer data from pret pokeemerald (trainers.h /
trainer_parties.h, key trainers per area) behind the adapter's trainer surface, the client
reporting the opponent trainer in battle, and a capability-driven UI gate (UI lane). Until these
land, Emerald is not RC-complete; see decision 0 in §5.

**EG4 does NOT sign:** trade (E5, patched-ROM only, built with Gen 3's FR/LG trade, own gate);
doubles / Steven multi-battle hold on hardware; writes inside Pokémon Centers (EW-3);
Frontier/Pyramid/Trainer Hill/Contests/Secret Bases (writes refused); the expansion track (XG*);
master merge or push.

## 2 Evidence

| Row | Status | Evidence |
|---|---|---|
| ED-1 seven duos E↔E | P ✓ | final cut rows 9-15 PASS at `9c96e745` (attempt 1 each; deadzone/link on the 20-ball fixture); `94c980f3` re-cut PASS |
| ED-2 wrong-save refusal, zip boot, final-cut summary | P ✓ | reconnect C-1; `zip_boot_emerald` real boot "gen3_emerald/emerald (clean by hash)", server "admission: admitted"; summary 24/24 at `94c980f3` |
| EW-2 P+H in-battle faint (singles) | P ✓ singles / ◐ doubles | `linked_faint_active` PASS; doubles/Steven hold not exercised |
| EW-1 checkpoint | P ◐ | `checkpoint_emerald` row PASS; Emerald-only forbidden states SOURCE-only |
| ES-1/ES-2 hooks, observer | P ◐ | `probe_gates_emerald`, `shadow_negatives_emerald` (75/75) PASS; rows a-return/b-interior/f OPEN as on FR; trade sites need a link partner |
| EF-10 fixtures | P ✓ | bootcheck town/town_b/battle/battle_b PASS; catch_b boot-checked |
| EC-1..EC-4 | ✓ (EG3) | unchanged |
| Calc (E6) | S/M ✓ | `tests/unit/test_calc_trainer_sets.py` Emerald rows; `emerald_battle.sav` calc_stats row |

Regression: FR/LG and RR final-cut plans unchanged by the cut (RR byte-identical; FR/LG differ only
in cut-sha cache keys).

## 3 Defects found and fixed since EG3

- `lua/gen3/run.lua` admitted without the launcher's ROUTED/header gate (OMP cx-dbabbd62) → `Entry.admit_routed`, red-first lupa tests driving the real `run.lua`.
- deadzone used all three RNG retries on 5 balls → 20-ball catch fixture.
- Emerald.js trainer sets: 169 IVs (wrong IV scale), 7 held items, 2 moves.
- Release-gate skip wording: 15 Emerald skip reasons reworded to the shared forms, the unit_emerald row selects an explicit file list (0 skips at the cut), the dead old-client `gen3_rr` duo row deleted (`eb203ab6`, `ffcce0aa`).
- The release zip did not ship `data/games/gen3_emerald/statics.json`, and the server falls back to empty sets without it (fixed-gift clause bypasses silently lost) → shipped + manifest test (`4b6eddc2`).
- Docs: Emerald described as refused/unadmitted in 13 files → fixed.

## 4 Limits carried forward

- Unknown-hash BPEE whose 21 anchors all hold is admitted as `clean` (the EG3 §2 FR/LG/RR policy). Header-only BPEE is refused.
- Manager options for Emerald equal FR/LG's (keyed on game_id `gen3_frlge`); `battle_calc` "Radical Red only." describes the RR native toggle; the web calc is served for Emerald.
- Legacy `emerald` stub in `data/games/gen3_frlg/profile.json` remains (multi-file deletion card).
- No trade on Emerald until E5 (patched ROM).

## 5 Owner decisions requested

0. Given the RC-mandatory trainer items above: sign EG4 now for admission + the evidence in §2, with the RC label waiting on the trainer items (recommended), or hold EG4 until they land.
1. Keep anchors admission for unknown-hash BPEE (as FR/LG/RR), or make Emerald hash-only (OMP cx-136573c0 F3)? Recommendation: keep anchors (same policy as the signed Gen 3 titles; header-only still refused).
2. Play a live Emerald↔Emerald duo from the Manager on the cut (plan EG4 row).
3. Sign EG4. The candidate then merges into `claude/gen3-emerald`. Before master (separate authority): batch with Gen 2 (server/** changed), tell Gen 3 the pack hashes moved, and have the Gen 1 owner review the two new Gen 1 allow-list fragments (`5d0b8504`) and run the full Gen 1 unit lane.

## 6 How to verify

    git -C C:/slink-wt/em-rc2 log --oneline -1   # 94c980f3 (+ receipts d096ce46)
    python tools/gen3_final_cut.py --cut 94c980f3 --title emerald --lane <lane>
    python -m pytest tests/unit -q -k "gen3 and emerald" -p no:randomly -rs
