# Phase 9-smoke — runtime sanity check after gen1-gen2-parity migration

**Phase 10 superseded the bulk of the original Phase 9 manual audit.** Static address correctness is now automated:

```
python tools/build_pret_syms.py       # once per pret upstream change (~30s)
python tools/verify_profile_addresses.py    # exit 0 means all addresses match pret
pytest tests/unit/test_profile_addresses.py # CI-friendly gate
```

What remains is a focused 30–60 minute runtime sanity check covering behaviors that no amount of static analysis can validate: server state-machine reactions, status-page rendering, AP-ROM detection, and the Gen 3 regression spot-check. The original day-long Phase 0 address-audit per ROM is gone.

**Setup**
- BizHawk with Gambatte (GB/GBC) core for Gen 1/2 ROMs (Crystal, Gold, Silver — same `lua/clients/gen2_crystal_client.lua` for all three).
- BizHawk with mGBA core for Gen 3 regression check.
- SLink server running: `python -m server.server --host 127.0.0.1 --port 54321`.
- A second player (or yourself with two clients) may be required for soul-link partner events.

**Gold/Silver coverage** (Phase 11): every address in the gold / silver profile blocks of `lua/games/gen2_crystal.lua` is verified against pret/pokegold via the same Phase 10 pipeline. The runtime smoke checks below apply to Crystal, Gold, AND Silver — you may want to spot-check on one of each.

**How to load a diagnostic Lua script in BizHawk**
1. Tools → Lua Console → Open Script…
2. Navigate to `lua/tests/<script>.lua`
3. The script prints to the Lua Console immediately. Use F-keys per the script's header comment.

The per-phase `lua/tests/test_gen{1,2}_*.lua` scripts shipped during Phases 0–8 are still there if you want to spot-check anything that the Phase 10 verifier can't reach (struct offsets, render-side rendering, etc.). They're optional reference material.

---

## 1. Memorialize routing (Gen 1 + Gen 2)

**What's automated**: Phase 10 verified that `M.depositMemorialMon` writes to the correct memorial-box CartRAM offset (Gen 1 Box 12, Gen 2 Box 14).

**What still needs live confirmation**: Did the dispatcher actually call `depositMemorialMon` instead of `depositPartyMon`? (Lua-side wiring, not addresses.)

**Verification (~5 min per gen)**:
1. Load Red or Crystal in BizHawk. Run the regular SLink client.
2. Catch a starter, soul-link with partner B's starter.
3. Faint your linked mon (use struggle, force_faint, etc.). Server fires `memorialize` for B's partner.
4. Open the PC. **Expected:** B's deceased mon is in **Box 12 (Gen 1)** or **Box 14 (Gen 2)**, not the active box.
5. **FAIL** if the mon ended up in the currently-active PC box.

---

## 2. Egg-gift classification (Gen 2 only)

**Why not static**: The state machine's response to is_egg + area_id combinations is runtime behavior, not an address. Could be unit-tested with mocks but currently isn't.

**Verification (~10 min)**:

A. **Wild capture on Route 34 grass**: was a false-positive gift before Phase 1.
- Catch a wild mon on Route 34 with Pokéballs.
- Server should activate the Pokéball gate + queue a `box_mon` quarantine if partner B hasn't caught on Route 34 yet.
- **FAIL** if the capture is silently classified as a gift.

B. **Mystery Egg from Mr. Pokemon (Route 30)** — classified as gift.
- Receive Mystery Egg from Mr. Pokemon's house; walk back to Elm and let it join your party.
- Server should NOT activate Pokéball gate, NOT quarantine to box. Egg = gift.
- **FAIL** if the egg gets quarantined.

C. **Daycare-bred egg on Route 34** — NOT a gift.
- Deposit a compatible breed pair at the Day-Care Man. Walk steps until he has an egg ready. Accept.
- Server SHOULD activate Pokéball gate (if not yet active) and queue `box_mon`.
- **FAIL** if the egg is misclassified as gift.

D. **Box pickup of an existing egg** — sanity.
- Move an existing egg from party to PC, then back to party.
- Server should not spuriously fire `capture(gift=true)`.

---

## 3. Status page rendering

**Why not static**: Server renders HTML/JS templates that only a browser confirms.

**Verification (~10 min, both gens)**:
1. Run the regular SLink client + server.
2. Open `http://localhost:8080/`.
3. Engage a wild Pokemon. Confirm:
   - Party panel shows the active slot with **Moves(N)** badge — expanding reveals 1–4 moves with name + colored PP bar.
   - Enemy panel shows the same Moves(N).
   - Stat-stage badges appear after using Growl / Sand Attack / Defense Curl (e.g., **−1 ATK**, **+1 DEF**).
4. Engage Brock / Falkner. Enemy panel header should read "**Leader Brock**" / "**Leader Falkner**" (class + name).
5. Open `http://localhost:8080/stream/enc-table-a`. Walk into Route 1 (Gen 1) or Route 29 (Gen 2). Overlay should populate with species + rates.
6. **FAIL** if any of: Moves(N) doesn't render, badges don't update, trainer name is missing, encounter overlay stays blank on a covered route.

---

## 4. Archipelago variant detection

**Requires**: AP-patched ROMs. Skip this section if you don't have them.

### 4.1 Pokemon Red/Blue Archipelago (Alchav, official)
1. Patch a vanilla Red/Blue with `.apred` / `.apblue` via the Archipelago client.
2. Load in BizHawk. Run the SLink client.
3. Server log should report `variant=red_ap` / `blue_ap`. Status page header shows "Red (AP)" / "Blue (AP)".
4. **FAIL** if it reports plain `red` / `blue` (seed-name detection at 0xFFDB failed).

### 4.2 Pokemon Crystal Archipelago (gerbiljames fork)
1. Apply the gerbiljames Archipelago-Crystal patch. Load in BizHawk.
2. Server should report `variant=crystal_ap`; status page shows "Crystal (AP)".
3. **FAIL** if it reports plain `crystal` (ROM title at 0x134 isn't "AP_CRYSTAL" — fork may have changed).

### 4.3 Vanilla regression
Load plain Red / Blue / Yellow / Crystal. Server should report the vanilla variant name, not `*_ap`. **FAIL** if any vanilla ROM is misclassified as AP (false positive on the 0xFFDB heuristic).

---

## 5. SFX dispatch discovery (optional — Phase 7 feature)

Phase 7 ships with SFX dispatch **disabled by default** (`sfx_dispatch_addr=nil` in both profiles). Audio output is the only way to verify; no static analysis reaches this.

If you want to enable in-game SFX on capture/faint/whiteout/gift events:
1. Load `lua/tests/test_gen{1,2}_sfx.lua` in BizHawk. In a quiet area (music off if possible), press F1–F4 to write candidate SFX IDs to candidate dispatch addresses.
2. If you hear the expected sound effect, note which key + address combination worked.
3. Edit the profile to set `sfx_dispatch_addr` and `sfx_ids = {capture=..., faint=..., whiteout=..., gift=...}`.
4. Restart the regular SLink client — SFX should now auto-play on those events.

**If no F-key combination triggers a sound**: the dispatch protocol is more complex than a single-byte write (likely involves writing to multiple channel registers in sequence). Phase 7 stays disabled; no failure — it's future work.

---

## 6. Gen 3 regression spot-check (run LAST)

The migration didn't touch Gen 3 code, but `server/server.py` got a one-line widening of the opponent_class fallback path. Confirm that didn't change Gen 3 behavior.

1. Load Pokemon FireRed (vanilla or RR) in BizHawk with mGBA.
2. Start a new game, walk 10 paces, open `http://localhost:8080/`.
3. Status page + overlays should look identical to pre-migration baseline.

**FAIL** if anything looks visually different from before.

---

## What changed vs the original Phase 9 (pre-Phase-10)

| Original Phase 9 section | Status |
|---|---|
| 0.1–0.4 Profile address audit (R/B/Y/Crystal, all bytes) | **Replaced by `pytest tests/unit/test_profile_addresses.py`** |
| 1.1 Memorialize routing address verification | **Replaced** (memorial-box offsets are pret symbols) |
| 1.2 Egg-gift classification scenarios | **Still manual** (above, section 2) |
| 2.1/2.2 Stat-stage addresses | **Replaced** (caught a 66-byte Crystal bug, a 1-byte Yellow bug — both fixed) |
| 3.3/3.4 Move/PP addresses | **Replaced** (struct base addresses pret-verified; offsets covered by unit tests) |
| 4 Enemy moves/PP addresses | **Replaced** |
| 5 Trainer class/id addresses | **Replaced** (caught a wTrainerClass vs wOtherTrainerClass mixup) |
| 6 Encounter overlay rendering | **Still manual** (above, section 3) |
| 7 SFX dispatch | **Still manual / optional** (above, section 5) |
| 8 AP variant detection | **Still manual** (above, section 4) |
| Gen 3 regression | **Still manual** (above, section 6) |

Estimated time: **30–60 minutes** for sections 1–3 + 6. Sections 4 and 5 are optional and depend on whether you have AP ROMs / want SFX enabled.
