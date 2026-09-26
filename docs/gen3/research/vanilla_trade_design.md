# Vanilla Gen 3 trade (FR/LG + Emerald): design (E5, gate EG5)

_Design only. No code was changed by this card. Branch `claude/gen3-emerald-trade` at `798b6c80`.
Every file:line is at that commit unless it says otherwise. pret citations are the `.cache/pret`
checkouts (`pokefirered`, `pokeemerald`). Scope: `docs/gen3_emerald/PLAN.md:58` (decision 6) and
`:74` (row E5). This supersedes the "not in this release" ruling for FR/LG
(`docs/gen3/PLAN.md:13`, `:239`) only if the owner signs EG5. See decision D1._

## 0. Findings that shape the design (read these first)

1. **The server already has a rollback-capable trade FSM, and no change to it is needed.** The
   PLAN's "watchdog force-commits with inferred keys" (`docs/gen3/PLAN.md:160`, `:240`) is stale.
   The current flow is: `trade_request` → `show_choices` → `choose_mon` → partner `show_menu` →
   **prepare round** (`apply_prepare`/`apply_ready`, used only when both hellos declare
   `trade_prepare`, `server/state.py:388-390, 426-428, 1008-1030`) → `apply_trade` to both sides →
   each side reports `trade_done` → `_settle_trade`. The settle rules are: both sides traded
   means commit, both sides none means roll back, and anything else is a sticky `conflict`
   surfaced to a human (`state.py:1186-1240`). The watchdog asks a silent side to
   `withdraw_trade` and then waits for party evidence. It never guesses an outcome
   (`state.py:701-743`, evidence `:1147-1184`). A fresh hello from a side that never reported is
   taken as evidence right away (`state.py:1786-1795`). An admin settles a conflict with
   `POST /api/debug/resolve_trade` (`server/server.py:4656`, `state.py:1290-1343`). The same stale
   wording sits in the client comment at `lua/gen3/client.lua:1328-1332` ("the server watchdog's
   inferred-key commit"). That comment and the PLAN lines should be corrected (D11).
2. **The Gen 3 adapter is already on the server-driven menu path.** `native_trade_ui()` defaults
   to False (`server/adapters/base.py:331-345`), and `gen3_frlge.py` does not override it. So
   FR/LG/Emerald already receive `show_choices`/`choose_mon`/`show_menu`/`apply_trade`, exactly
   as RR does. Today the new client answers those prompts with cancel sentinels
   (`lua/core/session.lua:55-56, 273-276`) because no part handles them. It also refuses
   `apply_trade` (`lua/gen3/client.lua:1515-1521`) and has no handler for
   `apply_prepare`/`withdraw_trade` (they fall to "unhandled command", `session.lua:309`).
3. **A vanilla trade is a verbatim copy of a 100-byte record plus a friendship reset.** FR
   (`pokefirered/src/trade_scene.c:1054-1082`) and Emerald (`pokeemerald/src/trade.c:3102-3130`)
   are identical here. Each game SWAPs the `struct Pokemon`, sets friendship 70 unless the mon is
   an egg, clears or gives mail, and sets the Pokédex seen/caught flags (FR `:1032-1044`,
   E `:3079-3091`). The XOR key is the mon's own `personality ^ otId`, so the partner's raw party
   record decrypts correctly on our cartridge, and the OT id/name travel unchanged (this is
   correct provenance). `struct Pokemon` has the same layout in both games (FR
   `include/pokemon.h:128-141`, E `:219-232`, mail byte at +0x55). The mail items are 121-132 in
   both (FR `include/constants/items.h:125-136`, E `:139-150`), and `MAIL_NONE` is 0xFF. Trade
   evolution runs from the trade scene, so a scene-less write does not evolve (D3).
4. **The server's party blob is the raw RAM record.** The client sends `blob_hex` from the RAM
   party (`lua/gen3/client.lua:259`). The adapter takes 100-byte blobs
   (`server/adapters/gen3_frlge.py:462-465`). The server captures both blobs at `mon_chosen`
   (`state.py:917-918`), so the blob that gets traded is the one from that moment (limit L3).
5. **Pairing is same-game only.** Emerald pairs only with Emerald
   (`server/adapters/__init__.py:165-171`), and FR pairs with LG. There is no cross-title trade.
6. **Every GBA field button does something in FR or Emerald, except a standing B.** FR opens the
   Help System on L or R (`pokefirered/src/help_system_util.c:47-53`). SELECT uses the
   registered item in both games (FR `field_control_avatar.c:292`, E `:188`). In FR, a B press
   is recorded but never consumed in the field (`field_control_avatar.c:85, 119`). In Emerald,
   B only triggers dive-emerge underwater (`:153`). Running needs B plus a direction (FR
   `field_player_avatar.c:516`, E `:658`). On Emerald's Acro Bike, B while standing starts a
   cosmetic wheelie (`pokeemerald/src/bike.c:293-309`). So a "hold B while standing" trigger
   is harmless, but the prompt itself still has to **mask** the pad: A, B and the D-pad all
   act in the field.
7. **Emerald has free-walking reduced parties and FR/LG does not.** In Emerald,
   `ReducePlayerPartyToSelectedMons` (`src/script_pokemon_util.c:209-227`) runs inside Frontier
   facilities, and `LoadPlayerParty` restores the party on exit (`src/frontier_util.c:2430`,
   `src/battle_pyramid.c:1446`). A trade written into that temporary party would be undone
   when the party is restored, which duplicates a mon. FR/LG's reductions are script-scoped
   (`data/maps/SevenIsland_House_Room1/scripts.inc:87-99`, cable club `data/scripts/cable_club.inc:288`),
   and the overworld predicate already refuses there (script context, link clauses in
   `data/games/gen3_frlg/write_checkpoint.json` `predicates`).

## 1. UX (player-facing only)

**Start.** The player holds **B for 90 frames (1.5 s)** while standing still on an overworld
checkpoint frame. The session must be eligible, the player must not be in battle, no trade or
prompt can be in flight, and `trade_blocked` must be false. The client then sends
`trade_request{}` once. On-foot/bike status is not checked (finding 6). There is no hold counter
on the HUD. The trigger is D2.

**Prompts.** All text goes through `hud.lua` `sanitize()`. While a prompt is open, the game's pad
is masked (§4.3):

| Server command | Shown as | Keys | Reply | Idle timeout |
|---|---|---|---|---|
| `show_choices{options}` (initiator) | header `LINK MENU`, options `Trade` / `Say hey` (the server's `text` names OAK, `state.py:830-838`, so the client drops it, D8) | Up/Down, A = pick, B = cancel | `menu_result{choice=i}`, B → 127 | 1800 f → 127 |
| `choose_mon` (initiator) | party list, `NICKNAME  Lv NN`, one row per slot | Up/Down, A, B | `mon_chosen{slot}`, B → 7 | 1800 f → 7 |
| `show_menu{text}` (partner) | the server text (`Trade your X for Y?`), `YES` / `NO` | Up/Down, A, B | `menu_result{choice=1}` for YES, else 0 | 1800 f → 0 |

- The server already enforces eligibility. It re-prompts with `Pick a linked POKeMON!` up to 3
  times (`state.py:903-912`), so the picker does not grey out any rows.
- `show_choices`/`choose_mon` open at once, because the initiator has just triggered from a
  checkpoint. If they arrive off-checkpoint, the client answers the cancel sentinel at once
  (`docs/protocol.md:348, 350`).
- The partner's `show_menu` can arrive mid-battle or in a menu. It is **buffered for up to 1800
  frames** until a checkpoint holds, then shown. If no checkpoint comes, the client answers 0
  (declined). The protocol text says "immediate" (`docs/protocol.md:349`). The server has no
  timer of its own apart from the ~4000-event watchdog (`state.py:696`). This is D7.
- After YES (partner), or after `apply_ready ok` (both sides), the player is **held** with the
  HUD line `Trading...` and the pad masked. The hold lasts until that side's write lands or
  900 frames pass (§3).
- The server's own messages are unchanged and already player-facing: `Trade offer sent -
  waiting for partner...`, `Traded X for Y!`, `Trade canceled.`, `Trade did not go through.`,
  and `TRADE ERROR - party mismatch.` (`state.py:932-933, 1204-1205, 1214-1215, 1474`). The client
  adds one line after its own completed write: `Save the game to keep the trade.` (L2).
- Client error lines stay player-level: `Trade stopped - check your party.` for the uncertain
  case. There are no counters, tokens or reason codes on screen. Diagnostics go to the console
  once per event.

## 2. The write

- **Arm reason: a new `trade` reason** (D9). It is added to `lua/gen3/writes.lua:4-5`. In
  `lua/gen3/safety.lua:481-489` it dispatches as: the **unchanged overworld clause set**
  (`overworld(snapshot)`, the EG3/G3-signed predicate) **plus** one clause that the title's
  `trade` block exists in the checkpoint pack. A missing block is refused by name, and that
  refusal is the disabled-foundation guard (`docs/gen3/PLAN.md:241`). RR's pack gets no block,
  so RR clean and companion behave exactly as today. The overworld predicate's link clauses
  (`link_callback`, `link_players_received`, `link_transferring`) and the Emerald Frontier,
  contest and multi-battle inventory (`docs/gen3_emerald/write_checkpoint.md:124-140, 255-270`)
  apply unchanged.
- **Allow range:** exactly `[PARTY_BASE + 100*slot, +100)`. `PARTY_BASE` comes from
  `data/games/gen3_frlg/profile.json:160, 377` (FR/LG) and `data/games/gen3_emerald/profile.json:168`.
  It is a fixed EWRAM address, so no save-pointer clause is needed (`safety.lua:159-161`).
  `slot < gPlayerPartyCount` is re-read at arm time. The party count is **not** written.
- **Record built before arm (validate-before-first-byte):**
  1. The token matches a prepare this client answered `ok` (§3). Otherwise the `apply_trade` is
     ignored: nothing is written and nothing is sent. This keeps
     `test_apply_trade_on_frlg_writes_nothing_and_replies_nothing`
     (`tests/unit/test_gen3_client.py:953-958`) green.
  2. `old_key` resolves to exactly one party slot (`session.identity:find_party_slot`, as the RR
     FSM does at `client.lua:1505-1507`).
  3. The incoming blob is 100 hex bytes. `reads.decode_party_mon` (`lua/gen3/reads.lua:276`)
     must give `checksum_ok == true`, a non-zero species, `is_bad_egg == 0`, a held item outside
     121-132, and a mail byte of 0xFF. Its key (`reads.key`, `:281`) must not already be in the
     party.
  4. The client applies TradeMons' one mutation: if `is_egg == 0`, set Growth.friendship = 70.
     It decrypts with `personality ^ otId`, sets the byte, recomputes the checksum
     (`R.secure_checksum`, `reads.lua:138`), writes it at +0x1C, and re-encrypts. The code for
     this already exists inline in `boxes.lua:170-191`. `reads.lua:129` `xor_words` is exported
     as `R.xor_words`, so it is reused rather than copied. The Pokédex flags are **not** set (D4).
     OT, met data and every other byte are copied verbatim.
  5. The built record is decoded again. It must round-trip with the same key, `checksum_ok`, and
     friendship 70.
- **Write:** in the frame-end callback, on a frame whose checkpoint holds, the sequence is
  `writes:arm("trade", allow)`, then `write_bytes(PARTY_BASE+100*slot, record)` (100 bytes,
  with the policy re-checked right before the first byte, `writes.lua:37-40`), then `disarm`.
  The provenance line reads `[SLink-gen3] write trade 0x<addr> +100 frame N`
  (`lua/gen3/entry.lua:295-297`). `st.trade_apply.posted = true` is set immediately before
  arm, which freezes party diffing the way a native post does (`client.lua:559-568`).
- **Readback and report** reuse the RR FSM's reporting: `trade_readback`/`trade_report`
  (`client.lua:1344-1406`). They find the partner key by key, send
  `trade_done{token, slot, new_key, new_species}`, migrate the local key, purge queued box
  moves for either key, open the settle window, and rebaseline. No `key_change` is sent
  (`docs/protocol.md` §6.5).

## 3. Client FSM (one trade at a time; rollback by construction)

States live in `lua/gen3/trade.lua`, apart from the apply record, which reuses
`st.trade_apply`. Reusing it means the existing gates hold unchanged: box moves wait
(`client.lua:926-928`), a `trade_request` is dropped while the record is set (`:1691-1694`), and
the party-diff freeze applies.

| State | Entered by | Exits |
|---|---|---|
| IDLE | — | trigger → `trade_request`; prompt command → MENU / PICK / CONFIRM_WAIT |
| MENU / PICK | `show_choices` / `choose_mon` at a checkpoint | A → reply → IDLE; B / timeout / disconnect / reset → sentinel (if connected) → IDLE |
| CONFIRM_WAIT | partner `show_menu` | a checkpoint holds → CONFIRM; 1800 f → `menu_result 0` → IDLE |
| CONFIRM | shown | YES → `menu_result 1` → HOLD; NO / B / timeout → 0 → IDLE |
| HOLD (masked) | YES, or `apply_ready ok` | the write reported, 900 f, disconnect or reset → unmask. Unmasking never cancels a pending apply |
| PREPARED{token} | `apply_prepare`: at a checkpoint (wait ≤ 600 f) with `old_key` unique, the own record valid by rule 3 (checksum, no mail, not a bad egg), no other trade in flight → `apply_ready{ok=true}` + HOLD; otherwise `ok=false` | `apply_trade` with the token → WAIT; disconnect / reset / 3600 f → forgotten |
| WAIT | `apply_trade` (PREPARED token) | the next checkpoint frame → WRITE; `withdraw_trade` → `trade_done{new_key=old_key}` (a certain none); disconnect or reset → **forgotten, nothing sent** (the reconnect hello decides, `state.py:1786-1795`) |
| WRITE | checkpoint frame | validation fails → `trade_done{new_key=old_key}`; checkpoint refused at arm → no byte, stay in WAIT; sink throws with `attempted > 0` → UNCERTAIN; OK → READBACK |
| READBACK | same frame | partner key in the party → `trade_done` traded; old key still there → none; unreadable → retry, backstop 6000 f (`client.lua:184`) → UNCERTAIN |
| UNCERTAIN | above | `trade_done{token, uncertain:true}` once. The next tick snapshot is the evidence (`state.py:1114-1123`). HUD error line |

**Each side validates its own outgoing record at prepare** (rule 3 applied to itself). The
partner's apply-time check of that same record then passes unless the bytes were corrupted, so
a one-sided "none" at apply cannot come from ordinary data.

### 3.1 Failure matrix (server protocol unchanged)

| Event | Client | Server outcome | Cartridges |
|---|---|---|---|
| Timeout or B at any prompt | sentinel | slot freed (`state.py:896-899, 969-970`) | untouched |
| Partner declines or never reaches a checkpoint | `menu_result 0` | "declined" to both (`:995-1000`) | untouched |
| Either side cannot take the apply at prepare (off-checkpoint, mail, bad record, a trade in flight) | `apply_ready ok=false` | both canceled before any apply (`:1026-1029`) | untouched |
| Pair no longer valid at confirm | — | `_trade_unavailable` cancels (`:1040-1054`) | untouched |
| Disconnect before `applying` | prompts closed, unmasked | watchdog frees the slot (`:737-743`) | untouched |
| Disconnect or reset in WAIT (nothing written) | forget | the hello's party shows the old key → `none` | this side untouched; the partner may have traded → **conflict** (L1) |
| Disconnect after the write, before `trade_done` goes out | nothing owed (the session drops sends while offline, `session.lua:78-82`) | the hello's party shows the partner key → `traded` → commit | consistent |
| `withdraw_trade` (watchdog) in WAIT | a certain none | settle | as above (L1) |
| Incoming record fails validation at apply | none | settle; conflict if the partner traded | this side untouched (L1) |
| Checkpoint lost between the check and the first byte | no byte (`writes.lua:37-40` re-checks) | — | untouched; retried |
| Sink throws part-way | UNCERTAIN | evidence; a checksum-bad record makes "holds NEITHER" a conflict | surfaced, never guessed |
| Power-off mid-write | not possible: the 100 bytes are written inside one Lua callback between two emulated frames, so the CPU never sees a partial record | — | — |
| Reset or power-off **after** a committed trade, before an in-game save | — | committed | that cartridge reverts to its last save (L2) |

**The watchdog "force-commit" limit is gone for this path.** The server never commits without
two `traded` verdicts (finding 1). What remains are three recorded limits:

- **L1** A one-sided apply (one side wrote, the other was withdrawn, reset or failed validation)
  becomes a board-visible `conflict` that a human settles with `resolve_trade`. It is never
  silent. The HOLD window makes it rare, because both sides are frozen at a verified checkpoint
  from `apply_ready` until the write.
- **L2** Like every SLink RAM write and today's RR silent swap, a trade survives only if the
  player saves in-game. The vanilla link trade saves both games itself. We do not trigger a save
  (D6).
- **L3** The traded record is the one captured at `mon_chosen` (`state.py:917-918`). EXP or HP
  the initiator gains while waiting for the partner is not carried. RR has the same limit.

## 4. Shared vs game-specific

### 4.1 Modules (reuse first)

| Piece | Where | Why there |
|---|---|---|
| Menu slot: title, rows, cursor, footer; persistent until closed; all text through `sanitize()` | `lua/hud.lua` (+`H.menu(title, rows, cursor)`, `H.close_menu()`, drawn in `H.render`, `H.clear` resets it) | The PLAN names a controller over `hud.lua` (`docs/gen3/PLAN.md:239`). The prompt queue dedups by text, so it cannot hold a moving cursor (`hud.lua:276-286`) |
| Prompt/input controller: edge-detected pad, cursor, A/B, idle timeout, mask while open, one prompt at a time | **`lua/core/prompt.lua` (new, generation-neutral)** | Nothing Gen 3-specific. Gen 1 Yellow and Gen 2 clean can bind it later (project goal: shared runtime) |
| Trigger, UI state machine, prepare/withdraw answers, record build/validate | **`lua/gen3/trade.lua` (new)** | Gen 3 record format (XOR/checksum, TradeMons rules) |
| Apply lifecycle (WAIT/readback/report/purge/settle) | `lua/gen3/client.lua` (existing RR FSM, one new `post_write` branch beside `post_stage`) | Reuse. The RR path is unchanged when `native` is present |
| `trade` arm reason | `lua/gen3/writes.lua`, `lua/gen3/safety.lua` | One gate. The clause set delegates to overworld |
| Pad io | `lua/gen3/run.lua` (`pad_read`, `pad_mask`), `lua/gen3/entry.lua` (passes `pad`, `wc.trade` into `Client.new`, `entry.lua:353-373`) | Only production binds BizHawk. The observer (`shadow_run.lua:126`) gets none, so it never masks |
| Server | **no change** | §0 finding 1 |

### 4.2 Per-title pack rows (the only per-title data; FR, LG and Emerald bind the same code)

`write_checkpoint.json`, one block per title:

```json
"trade": {"version": "gen3-trade-v1", "blocked_maps": [], "_src": "…"}
```

- `firered`, `leafgreen`: `blocked_maps: []`, sourced to finding 7 (reductions are
  script-scoped).
- `emerald`: `blocked_maps` = every `BattleFrontier_*` map plus the three Battle Tent map sets
  (`FallarborTown_BattleTent*`, `SlateportCity_BattleTent*`, `VerdanturfTown_BattleTent*`) as
  `[group, num]` pairs from pret `include/constants/map_groups.h`, generated rather than hand
  typed (D10). In a blocked map the client sends `trade_blocked: true` on its tick (existing
  field, `state.py:541-542`, `docs/protocol.md:274`). The server then has no eligible pair
  (`state.py:652-653`), and the trigger is suppressed. A borrowed party (`st.frozen`,
  `client.lua:352-368`) also sets `trade_blocked`.
- No `profile.json` change: `PARTY_BASE`/`PARTY_COUNT_ADDR` already exist for all three titles.
- `radical_red`: **no `trade` block**. RR keeps `native.lua`, and RR clean stays refused.

### 4.3 Pad masking (PHYSICAL fact to establish first)

While a prompt is open or HOLD is on, each frame the client calls `pad_mask()` =
`joypad.set{all 10 buttons = false}` and reads `pad_read()` = `joypad.getimmediate()` (the
physical pad, not the overridden input). This pair of BizHawk semantics is **unverified**.
Phase P0 probes it with a known-positive control: unmasked, a held Down moves the avatar; masked,
the same hold leaves it in place while `getimmediate` still reports Down. If the probe fails,
the fallback is D2's alternative trigger plus a field-control lock write. That fallback is out
of scope until the probe says so. The duo drives prompts through a teed `pad_read`
(`duo_gen3_main.lua` already tees seams, `:7-12`), so the owner's EG5 play is the only evidence
for the real pad.

## 5. Test plan

**Unit (lupa)**. These tests are new. Each assertion gets a revert control: remove the guard and
the test fails (see `feedback_verify_the_probe_first`).

- `tests/unit/test_core_prompt.py` (prompt.lua against a fake pad and HUD): cursor wrap; A
  selects only on a press edge, so a B or A held from the trigger does not auto-fire; B gives the
  sentinel; the idle timeout gives the sentinel; the mask is called on every open frame and
  never after close, including after an error thrown in the callback (pcall); a second prompt
  gets its sentinel at once; all text reaches `H.menu` sanitized.
- `tests/unit/test_gen3_vanilla_trade.py` over `tests/unit/gen3_world.py` (it gains the pad seam
  and the Emerald artifact row; `PACK_DIRS`/`ARTIFACTS` are at `:26-35`). It is parametrized over
  **firered, leafgreen, emerald**:
  - trigger: B held 90 f at a checkpoint sends exactly one `trade_request`; the control cases
    send none: released at 89 f, in battle, a prompt open, `trade_blocked`, checkpoint refused.
  - happy path, both halves in one World per side: replies in order, `apply_ready ok`, exactly
    **one** armed write with reason `trade`, 100 bytes at `PARTY_BASE+100*slot`, and **no other**
    write. The written bytes equal `gen3_codec.encode_party_mon(decoded partner record with
    friendship=70)` (Python twin, `server/adapters/gen3_codec.py:318-324`). Party count is
    unchanged. `trade_done.new_key` is the partner key. No `key_change` or `capture` is sent.
  - egg record: friendship untouched (TradeMons control).
  - rollback/abort controls: decline; each prompt timeout; prepare off-checkpoint beyond 600 f →
    `ok=false`; outgoing mail → `ok=false`; incoming checksum-bad → no byte + none; an
    unsolicited `apply_trade` (no prepare) → nothing written or sent; `withdraw_trade` in WAIT →
    none, no byte; `withdraw_trade` after the write → readback; disconnect in WAIT → forgotten,
    no byte after reconnect; reset in WAIT → forgotten; safety refusal at arm → no byte, written
    on the next good frame; sink throws after k bytes → `uncertain:true` exactly once.
  - disabled foundation: an RR clean or RR companion pack with no `trade` block refuses the
    `trade` reason by name. The existing `test_prompts_without_a_native_part_get_the_cancel_sentinels`
    (`test_gen3_client.py:961-970`, RR) stays green.
  - Emerald: a `blocked_maps` location → `trade_blocked: true` on tick and no trigger.
- `tests/unit/test_gen3_writes.py` / `test_gen3_write_checkpoint.py`: `trade` is a known reason;
  the `trade` block schema; the `gen3_rr` pack has no block.

**Duo** (`tools/e2e_duo.py`; driver `lua/tests/duo/scenario_gen3_trade_vanilla.lua` under
`duo_gen3_main.lua`):

- `trade_vanilla_gen3`, games `("gen3_frlg", "gen3_emerald")`, targets FR `town`
  (`firered_party_town{,_b}.sav`), Emerald `pc` (`emerald_pc{,_b}.sav`). The prelude is
  `_gen3_prelude(link_slot=1)` (the `whiteout_gen3` precedent, `tools/e2e_duo.py:6836-6841`),
  disclosed as a synthetic setup. A holds B, picks Trade and slot 1. B answers YES. Both write,
  and both save through the existing in-game save flow. The oracle is
  `assert_trade_vanilla_gen3_saved`, modelled on `assert_trade_new` (`:5863-5919`). It checks:
  - `links.json` halves swapped;
  - **each side's saved flash** (`gen3_codec.party_from_save(image, title=…)`) holds the partner
    key at the traded slot with the party count unchanged;
  - the received record's OT id/name equal the partner's `player_identity`, friendship is 70,
    the checksum is valid, and every other secure/tail byte equals the partner's pre-trade
    fixture record;
  - exactly one schema-valid `trade_done` per side, whose `new_key` equals the incoming key;
  - exactly one `write trade 0x… +100` receipt per side;
  - `check_save_witness_gen3` passes first.
- `trade_vanilla_decline_gen3` (negative control, both titles): B answers NO. The oracle
  mirrors `assert_trade_decline_saved` (`:5921-`): no `RX apply_trade`, no `write trade` line,
  links and both saved parties unchanged.
- Oracle revert checks: the trade oracle must FAIL on the decline run's saves, and the decline
  oracle must FAIL on the trade run's.

**Owner EG5 play**: a real-pad trade on FR↔FR and E↔E, plus one cancel. This is the only
masking evidence.

## 6. Files, claims and phases (each phase demoable in BizHawk)

| Phase | Files (exclusive claim unless marked shared) | Demo / falsifier | Est. |
|---|---|---|---|
| **P0 probe** | `lua/tests/probe_gen3_pad_mask.lua` (new); Emerald `blocked_maps` generator rows in `tools/gen_gen3_profile.py` or a small `tools/gen_gen3_trade_block.py` (new) | the masking probe with its known-positive control; the map list regenerated byte-identically | ¼ |
| **P1 prompts** | `lua/core/prompt.lua` (new), `lua/hud.lua` (**shared**: one additive commit, batched, Gen 2 lane pinged because it stales Gen 2 receipts), `lua/gen3/trade.lua` (trigger + UI), `lua/gen3/client.lua` (MENU_CMDS fallback `:1538-1548`, `trade_blocked` on the tick `:988-1000`), `lua/gen3/run.lua`, `lua/gen3/entry.lua`, `tests/unit/test_core_prompt.py`, `tests/unit/gen3_world.py` (pad seam) | Two BizHawk instances: B-hold → menu → Say hey reaches the partner; Trade → pick → the partner sees YES/NO; NO declines. **`trade_prepare` is not declared yet**, so a YES reaches the RR-style refusal and the server settles it as none (L1 wording in the demo notes) | ½ |
| **P2 executor** | `lua/gen3/trade.lua` (prepare/withdraw/record), `lua/gen3/client.lua` (`post_write`, `C.apply_prepare`, `C.withdraw_trade`, hello `trade_prepare`, `:949-985`), `lua/gen3/writes.lua`, `lua/gen3/safety.lua`, `lua/gen3/reads.lua` (export `xor_words`), `data/games/gen3_frlg/write_checkpoint.json`, `data/games/gen3_emerald/write_checkpoint.json`, `tools/make_release.py` (`_LUA_GEN3` += `trade.lua`, `_LUA_CORE` += `prompt.lua`, `:115-133`), `tests/unit/test_gen3_vanilla_trade.py`, `tests/unit/test_gen3_writes.py`, `tests/unit/test_gen3_write_checkpoint.py` | A full manual trade FR↔FR and E↔E, then save and reload with the mon present; the unit suite with every control | ¾ |
| **P3 duo + docs** | `tools/e2e_duo.py` (2 rows, orchestrate, 2 oracles), `lua/tests/duo/scenario_gen3_trade_vanilla.lua` (new), `lua/tests/duo/duo_gen3_main.lua` (pad tee), `tests/unit/test_e2e_duo_gen3.py` (rows), `docs/protocol.md` (Gen 3 vanilla sources on the §5/§6 rows, the `show_menu` buffering note), `docs/gen3/PLAN.md` (§0 row note + stale watchdog lines, D1/D11), `docs/gen3_emerald/PLAN.md` gate ledger | `trade_vanilla_gen3` and `trade_vanilla_decline_gen3` PASS on FR and Emerald, with oracle revert checks | ¾ + live |

The total is about **2¼ sessions** (the Emerald PLAN budgets 2, `:74`, `:98`). The standing gates
for each phase are the unit suite, `tools/lua_syntax_check.py` (lupa 5.5), ruff and the affected
duo lane. No shared `server/` file is touched, so no adapter guard is needed. `lua/hud.lua` and
`lua/core/*` do count as shared Lua (Gen 2 receipts).

## 7. Owner decisions (each with a recommendation)

1. **D1 Does FR/LG ship it in the Gen 3 RC?** `docs/gen3/PLAN.md:13` says no, while the Emerald
   PLAN says it is new work for FRLG too (`docs/gen3_emerald/PLAN.md:98`). **Recommend:** yes,
   one EG5 signature for both. The pack `trade` block is the per-title switch, so FR/LG can be
   left without the block if the Gen 3 RC must ship first.
2. **D2 Trigger.** **Recommend:** hold B for 1.5 s while standing in the field (finding 6). The
   alternatives are a host-keyboard hotkey (`input.get()`, not visible to the game but awkward
   for pad players) or the Center 2F cable-club attendant (more pins, and native dialogue mixes
   in).
3. **D3 Trade evolution** (Kadabra, Machoke, Graveler, Haunter and the item evolvers). **Recommend:**
   none in the RC. The mon arrives unevolved and the HUD says nothing. A later card could evolve
   it natively.
4. **D4 Pokédex seen/caught for the received species** (TradeMons does set them). **Recommend:**
   skip in the RC. It needs save-pointer writes across two blocks plus Spinda/Unown handling.
   It is a recorded deviation.
5. **D5 Mail holders.** **Recommend:** refuse at prepare (`ok=false`). The player's line is
   `Take the MAIL off to trade.`. Stripping mail is the alternative.
6. **D6 Reset before saving after a trade (L2).** **Recommend:** accept it as the recorded limit
   (the RR/SLink norm) and show the HUD nudge. The alternatives are a client-side redo after a
   soft reset, or holding `trade_done` until the in-game save (more conflicts, longer held
   events).
7. **D7 Partner confirm while busy.** **Recommend:** buffer up to 30 s for a checkpoint, then
   decline. The protocol-literal alternative is to decline at once.
8. **D8 The server `show_choices` text names OAK** (`state.py:830-838`). **Recommend:** the client
   shows its own neutral header, with no server change. The alternative is a shared-server diff
   (guard plus independent review) that makes the text title-neutral.
9. **D9 Arm reason.** **Recommend:** a new `trade` reason that delegates to the unchanged
   overworld clause set plus the pack-block clause. This gives distinct provenance receipts and
   a pack-level guard. The alternative is to reuse `overworld` with a client capability flag.
10. **D10 Emerald blocked maps.** **Recommend:** all Battle Frontier and Battle Tent maps
    (conservative, generated from pret). The narrower alternative is only the free-walk
    reduced-party maps (Pyramid floors, Pike rooms).
11. **D11 Stale docs.** **Recommend:** a docs-only fix marking `docs/gen3/PLAN.md:160, :240` and the
    comment at `lua/gen3/client.lua:1328-1332` as superseded by the evidence-based settle
    (`state.py:701-743, 1186-1240`). This should be batched with P3.
