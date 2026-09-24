# SLink client ↔ server wire protocol

**Status:** normative. Extracted from the trusted reference implementation at commit `7f52df8`:

| Layer | File | Role |
|---|---|---|
| Framing (client) | `lua/connector.lua` | non-blocking LuaSocket, newline-delimited JSON |
| Framing + admission + display (server) | `server/server.py` | `SLinkServer.handle_client`, `_dispatch`, status/HTML builders |
| Rules engine (server) | `server/state.py` | `SoulLinkState.handle_event` and every `_handle_*` |
| Adapter hooks | `server/adapters/base.py`, `server/adapters/__init__.py` | per-generation knobs the protocol relies on |
| Reference client | `lua/clients/gen3_frlge_client.lua` | the only client this document treats as correct |

**Authority.** Where the Gen 3 client and the server disagree, the server wins. Every such disagreement is marked **⚠ DISAGREEMENT** inline and collected in [Appendix A](#appendix-a--disagreements-and-ambiguities). `lua/gen1/client.lua` and `lua/clients/gen2_crystal_client.lua` were deliberately not consulted.

**Conventions.** `file:line` cites the line where the behaviour is implemented. Field types: `str`, `int`, `bool`, `list[T]`, `hex` (lowercase hex string), `key` (mon key string, format per §3.1). "MUST/SHOULD/MAY" are RFC-2119. All indices are **0-based** unless stated. The two players are `"a"` and `"b"`; the "partner" is the other one (`state.py:84-85`).

---

## 1. Transport

| Property | Value | Cite |
|---|---|---|
| Carrier | TCP, one connection per client, server is `asyncio.start_server` | `server.py:8478-8479` |
| Framing | one JSON object per line, `\n` terminated, both directions | `connector.lua:7-9`, `server.py:2417`, `server.py:2557` |
| Encoding | UTF-8; server decodes with `errors="replace"` and `.strip()`s the line; blank lines are ignored | `server.py:2436-2438` |
| Max inbound line (server) | 4 MiB (`limit=4*1024*1024`); an over-long line is drained to the next `\n`, logged, and the connection stays up. **No reply is sent for the dropped line.** | `server.py:2420-2435`, `server.py:8472-8479` |
| Max inbound line (client) | 4 MiB (`MAX_LINE`); an over-long server line is discarded and the reader resyncs at the next `\n` | `connector.lua:51`, `connector.lua:242-247`, `connector.lua:221-228` |
| Client → server envelope | `{"event": "<type>", "player": "a"\|"b", "seq": N, ...fields}` — `send()` stamps `seq` and `player` on every event | `gen3_frlge_client.lua:1047-1060` |
| Server → client envelope | **exactly one line per inbound line**: `{"commands": [ {...}, {...} ]}`. Never fewer than one element: an empty queue is `[{"cmd":"noop"}]` | `server.py:1401`, `server.py:1412`, `state.py:459` |
| Reply on malformed JSON | `{"commands":[{"cmd":"noop"}]}` | `server.py:1397-1401` |
| Reply on unknown `player` | `{"commands":[{"cmd":"noop"}]}`; `player` MUST be `"a"` or `"b"` (`VALID_PLAYERS`) | `server.py:79` (the set), `server.py:1410` (the check in `handle_client`), `server.py:1412` (the noop reply) |
| Reply on duplicate `seq` | `{"commands":[{"cmd":"noop"}]}` — the event is **not processed** | `server.py:1558-1565` |
| ACK/NACK envelope | **None.** There is no per-event ack. Command receipt is implicit (the reply line). Command *execution* is acknowledged only for the deferred commands via dedicated events (§5). | — |
| Delivery model | Commands for the sender are returned in the reply to the event that produced them. Commands for the *partner* are queued in `queued_commands[partner]` and flushed in the reply to the partner's **next event of any type** (ticks included). | `state.py:2-8`, `state.py:239-244`, `state.py:376-384` |
| Reply order | FIFO in queue order; server.py may append one `link_panel` after the state's list | `state.py:459`, `server.py:1720` |
| Client pump cadence | once per emulated frame: `C.pump()` flushes the send queue and reads all complete lines; the client then drains `C.receive()` until nil and dispatches each reply | `connector.lua:150-154`, `gen3_frlge_client.lua:1912-1913`, `gen3_frlge_client.lua:1967-1977` |
| Reconnect | non-blocking connect with exponential backoff: first retry after 30 frames (~0.5 s), doubling to a 1800-frame (~30 s) cap; reset to 30 on success | `connector.lua:55-57`, `connector.lua:161-187`, `connector.lua:78`, `connector.lua:103` |
| `C.connected()` | `true` iff the socket is open **and** the non-blocking connect has completed (probed by a zero-length send). During an in-progress connect it is `false`. | `connector.lua:134-136`, `connector.lua:92-113` |
| On disconnect (client) | socket closed; partial-send offset, partial-receive buffer and oversize flag reset; backoff reset. **The unsent `_send_queue` is cleared** so stale events cannot precede the next connection's hello. This does not claim the received `_line_queue` is cleared. | `lua/connector.lua:262-280` |
| Events while disconnected | `send()` refuses to enqueue when `not C.connected()`: the event is **dropped** with a console log. Nothing is buffered for later. | `gen3_frlge_client.lua:1048-1051` |
| On disconnect (server) | `connected_players[pid].connected = False`; **queued commands survive** and are delivered on the next event after reconnect | `server.py:2542-2548`, `state.py:125` |

### 1.1 `seq` semantics

| Rule | Cite |
|---|---|
| `seq` is a per-client monotonically increasing `int` starting at 1 for the process lifetime; it does **not** reset on TCP reconnect (only on script reload) | `gen3_frlge_client.lua:1044`, `gen3_frlge_client.lua:1052` |
| The duplicate-event counter is **per connection**, not per player: `last_seq` is a local of `handle_client`, so it is born with the socket and dies with it. An event with `seq <= last_seq` is dropped as a duplicate of one seen on *this* connection; a new connection starts from `-1` by construction, so a client that restarts and counts from 1 again is never mistaken for a duplicate. | `server/server.py:1359-1594` (the per-connection locals), `server.py:1359-1594` (the guard) |
| A connection is **ignored until it says hello**: any non-`hello` event on a connection whose hello has not been accepted is answered `noop`, with one WARNING per connection. The per-slot identity gate in `_dispatch` is the second line. | `server/server.py:1855-2303`, `server.py:1855-2303` |
| ⚠ RETIRED 2026-09-17 (`0629736`) — kept so the history reads straight: the server used to keep `_last_seq[player]` and treat `seq <= 1 and last > 10` as a client restart, which trapped a client that restarted after sending ≤ 10 events (its first events, `hello` included, were silently dropped) and forced a conformance harness to never reuse a server instance across "restarts". `reconnect_new`'s wrong-save leg hit exactly that trap live. The heuristic is deleted and the constraint no longer exists — a harness may reuse a server across restarts freely. | `0629736`; `server/server.py:1098-1101` |
| Omitting `seq` (`-1` default) disables the guard for that message | `server/server.py:1558-1565` |

### 1.2 Client-side response parsing (reference behaviour)

The Gen 3 client has **no JSON decoder**; `parse_command_list` is a pattern scraper (`gen3_frlge_client.lua:241-358`). Consequences a spec-conformant server already honours and a new client MUST also tolerate:

- Nested objects are only understood for `stats` (`{level,maxHP,attack,defense,speed,spAtk,spDef}`) (`:264-275`). ⚠ `pp1..pp4` inside `stats` are **not** extracted although the client itself sends them (`:1624-1628`, `:3719-3722`).
- String arrays are understood for `rows`, `areas`, `blobs_hex`, `options` (`:258-262`, `:309-315`, `:319-325`, `:332-336`).
- `text` has JSON `\n` unescaped to a real newline (`:283`).
- Booleans are read for the five `config` fields only (`:244-248`, `:338-342`).
- Any command with a recognised `cmd` but missing required companion fields (e.g. `box_mon` without `key`) falls to the "unknown command" log branch (`:1037-1038`).

A new client MAY use a real JSON decoder; it MUST NOT depend on field order.

---

## 2. Session lifecycle

### 2.1 `hello`

Sent on every TCP (re)connect edge (`gen3_frlge_client.lua:1915-1945`). The server treats **every** `hello` as a fresh session start for that player (`state.py:1003-1264`).

| Field | Type | Required | Gen 3 sends | Server reads | Cite |
|---|---|---|---|---|---|
| `event` | `"hello"` | yes | yes | dispatch | `state.py:309` |
| `player` | `"a"\|"b"` | yes | yes | `handle_client` | `server.py:1410` |
| `seq` | int | SHOULD | yes | dup guard | `server.py:1560` |
| `rom_type` | str | yes (routing) | yes | adapter selection, set-once commit, `is_rr = rom_type.endswith("_rr")` | `server.py:2478-2511`, `server.py:2853-2856` |
| `party` | list[PartyEntry] (§4.1) | yes (may be `[]`) | yes | identity, `party_size`, `party_keys`, blobs, hp==0 faints, display backfill, `party_details` seed | `state.py:876-883`, `state.py:951-1048`, `server.py:2883-2902` |
| `ot_id` | str | SHOULD | **no** | identity lock (preferred over key-derived OT) | `state.py:892` |
| `trainer_name` | str | SHOULD | yes | identity display name, committed once per run | `state.py:896`, `server.py:2863-2870` |
| `has_pokeballs` | bool | SHOULD | yes | nuzlocke gate; `None` + non-empty party ⇒ `True` (legacy) | `state.py:940-942` |
| `ball_count` | int | optional | yes | dashboard | `server.py:2857-2858` |
| `badges` | int **bitmask** (bit i = gym i+1) | optional | yes | dashboard, badges overlay, compact `link_panel` popcount | `server.py:2859-2860`, `server.py:2647-2652` |
| `kanto_badges` | int bitmask (second region, Gen 4) | optional | no | badges overlay bits 8-15 | `server.py:2861-2862`, `server.py:5951-5953` |
| `battle_identity` | bool | optional | yes | capability declaration (card C5-10b): this client mints and enforces the battle request identity, so an identity-less manual rival inject may be refused for it. Absent or `false` = the client does not speak the protocol and keeps the pre-card behaviour. Never inferred from anything else. | `state.py:985-1000` |
| `area_id` | str | optional | yes | `player_area_id` | `server.py:2849-2850` |
| `loc_name` | str | optional | yes | `player_area` (display) | `server.py:2849` |
| `writes_enabled` | bool | optional | yes | **ignored by server** | — |
| `panel` / `panel_abi` | bool / int | optional | no | per-cartridge native-panel capability; absent ⇒ adapter default (`info_panel_width()==0`) | `server.py:2483-2485`, `server.py:1781-1799` |
| `sfx` | bool | optional | no | per-cartridge native-sound capability (Gen 1 companion mailbox caps bit 0); carried like `panel` | `server.py` hello handler |
| `rom_content` | dict (adapter-defined) | required only under a `rom_contract.json` | no | admission fingerprint + per-player encounter tables | `server.py:1739-1758`, `server.py:2873-2874` |
| `rom_sha1` | str (40 hex, any case) | SHOULD | no | compared to the contract's `rom_sha1` for this player when both exist; mismatch ⇒ rejected (§2.2 step 1) | `_decide_admission` |
| `artifact_kind` | str (`clean` \| `overlay` \| `rand` \| `rand_overlay` \| `named` \| `companion`) | optional, default `"clean"` | no | committed once per run beside `rom_type`; a later hello of another *pairing* kind is refused (§2.2 step 1') | `_mixed_games_error` |
| `foundation` | str (pack id, e.g. `gen3_frlg` \| `gen3_rr` \| `gen1_rby` \| `gen1_purergb`) | optional — omit the key, or send the derived string | no | **never trusted**: the server derives the foundation from `rom_type` and refuses a hello that declares anything else. Absent (key missing) ⇒ derived, so a client that does not send it is unaffected; **present** ⇒ validated, and `null`/`""`/`false`/`0`/`[]`/`{}` are refused, not treated as absent | `foundation_for_rom_type` |
| `pc_boxes` | list[BoxEntry] (§4.4) | optional | no (tick only) | `pc_boxes`, memorial contamination scan | `server.py:2875-2881` |
| `in_battle`, `is_trainer_battle`, `enemy_party` | as in tick | optional | no | seed `battle_state` | `server.py:2904-2909` |

### 2.2 Admission and identity (in order)

| Step | Rule | Outcome | Cite |
|---|---|---|---|
| 0 | Any non-`hello` event from a player with a standing `identity_error` → `[noop]`, not processed | blocked | `server.py:2800-2801` |
| 0' | Any non-`hello` event from a player not admitted (only matters when `rom_contract.json` exists; a run without a contract admits everyone) → `[noop]` | blocked | `server.py:2808-2809`, `server.py:1761-1779` |
| 1 | ROM contract check (`_decide_admission`): rejected if the contract is unreadable, names no fingerprint for this player, the contract's `rom_sha1` and the hello's `rom_sha1` both exist and differ, the hello has no `rom_content`, the adapter raises on it, or the fingerprint differs. `rom_content_fingerprint()` returning `None` admits. No contract ⇒ admitted. | rejected ⇒ **`[noop]` returned, state untouched** | `server.py:712-758`, `server.py:712-758` |
| 1' | Pairing (`_mixed_games_error`, in `handle_client` **before** the per-cartridge capability updates and the adapter reselection, so a refused hello changes nothing). The run is locked to one **foundation** — a pack, not a `game_id`: `firered`/`leafgreen` ⇒ `gen3_frlg`, `firered_rr` ⇒ `gen3_rr`, and elsewhere the `game_id` itself (`gen1_rby` vs `gen1_purergb`). The foundation is **derived** from `rom_type` via `foundation_for_rom_type()`, and the check is **fail-closed on every input**: a `rom_type` that is absent, empty, non-string or unrecognized is refused (it used to be skipped, which let a hello with no `rom_type` past the lock entirely), and an invalid retry does not clear a standing rejection. The hello's own `foundation` is optional but **absent is not empty**: omit the key and it is derived; send it and it must be the derived string, so `null`, `""`, `false`, `0`, `[]`, `{}` and any other value are refused. A non-string `artifact_kind` is refused likewise. It is also locked to one **pairing kind**: each foundation's adapter class normalizes the declared `artifact_kind` through `GameRulesAdapter.pairing_kind()` (default `named → clean`; `Gen3Adapter` adds `companion → clean`, since both patches are per cartridge). The **committed** kind is the declared one — `set_artifact_kind` is unaffected, so pureRGB `clean` vs `overlay` stays refused. Variants of one foundation (Red beside Blue, FireRed beside LeafGreen, companion RR beside clean RR) pair. Reply is only `hud_show{text:"[x] MIXED GAMES", color:[255,0,0], duration:600}`; `identity_error[pid]` is set and every later event gets `[noop]` until a conforming hello. | rejected | `server.py` `_mixed_games_error`, `adapters/__init__.py` `foundation_for_rom_type` |
| 2 | Identity: `incoming_ot = msg.ot_id` else `adapter.parse_ot_id(party[0].key)`; empty party and no `ot_id` ⇒ no identity check at all | — | `state.py:892-895` |
| 3 | First hello with an OT locks `player_identity[pid] = {ot_id, trainer_name or "A"/"B"}` and persists | locked | `state.py:929-936` |
| 4 | Later hello with a different OT: `identity_error[pid]` set, `msg["_rejected"]=True`, the reply is **only** `hud_show{text:"[x] WRONG SAVE: slot A", color:[255,0,0], duration:600}`, and `_handle_hello` returns before touching party state | rejected | `state.py:1003-1264` |
| 5 | Matching OT clears `identity_error` and may refresh `trainer_name` | ok | `state.py:919-927` |

⚠ DISAGREEMENT: the WRONG SAVE `hud_show` uses `color`/`duration`, not the `r,g,b,frames` every other `hud_show` uses. The Gen 3 parser only reads `r,g,b,frames` (`gen3_frlge_client.lua:299-302`), so this toast renders white for 300 frames. A new client SHOULD accept both spellings.

**What a rejected client must do:** keep the connection, display the toast, and stop expecting any state effect until it sends a `hello` whose OT matches. Every other event will get `[noop]` (`server.py:1868`). Under a ROM-contract rejection the client gets `[noop]` even for the hello and the dashboard shows `admission_reason` (`server.py:1876`).

### 2.3 What `hello` does on the server (accepted path)

| Effect | Cite |
|---|---|
| `party_size[pid] = len(party)`; blob cache refreshed (`_ingest_party_blobs`) | `state.py:3045-3089` |
| `_has_helld.add(pid)`; **partner removed from `_has_helld`** so partner-side `box_mon` becomes optimistic until the partner hellos | `state.py:1124` |
| `party_keys[pid] = {key for entries with maxHP > 0}` minus DEAD/MEMORIAL keys | `state.py:951-959` |
| Re-quarantine: any pending (unlinked) capture found in the party gets `box_mon` re-queued, unless that would leave zero alive mons | `state.py:1124` |
| Any party entry with `hp == 0` whose key is an ALIVE link, if `pokeballs_obtained[pid]`, is treated as a faint that happened offline → `_propagate_faint` (partner gets `force_faint`/`force_explode`) | `state.py:2907-2951` |
| Every key in `pending_memorials[pid]` gets `memorialize` re-queued (dedup against queue) | `state.py:1153` |
| Any DEAD/MEMORIAL key present in the party gets `memorialize` + `hud_show "[x] Dead in party -> grave"` | `state.py:1166` |
| Nickname/species back-fill into `LinkEntry.MonInfo` from the snapshot | `state.py:1027-1048` |
| **Always** `resolved_areas{areas:[...]}` (LINKED + DEAD_ZONE areas + areas where this player has a pending capture; may be `[]`) | `state.py:1050-1068` |
| **Always** `config{overworld_presence, native_messages, native_sounds, battle_calc, pc_trade_npc}` | `state.py:1070-1082` |
| Re-arm an interrupted whiteout rebuild (`party_mon` × outstanding + `rebuild_start`) | `state.py:2515-2567` |
| `game_over` if `run_over` | `state.py:1263-1264` |
| server.py: commit `rom_type` once, commit `trainer_name` once, ingest `rom_content`, seed `party_details`/`battle_state`, `_cache_mon_info` | `server.py:1735-1775` |

Nothing else is "replayed": there is no event log replay. Pending commands queued for this player while offline are simply included in the hello reply (they were never removed from `queued_commands`).

### 2.4 `tick` / `safe` shared handling

`handle_event` treats `safe` and `tick` identically (`state.py:354-374`): if `has_pokeballs is True` the gate opens; if `party` is present, `party_size` is updated, blobs are re-ingested and `_reconcile_party_keys` runs. `_reconcile_party_keys` (`state.py:2362-2453`) repairs `party_keys` toward the snapshot and may queue `party_mon` to the partner for a ghost-boxed linked mon. It is suppressed during an active rebuild, during a trade in phase `applying`, and for `_trade_settle_ticks[pid]` (=12) ticks after a trade commits (`state.py:2362-2453`, `state.py:303`, `state.py:303`).

⚠ DISAGREEMENT: the Gen 3 `safe` event carries **no fields** (`gen3_frlge_client.lua:4123`) although `_ingest_party_blobs`' docstring says blobs ride "every hello / tick / safe" (`state.py:3045`). `safe` is therefore, in practice, only a queue flush that marks "the client is in the overworld again". server.py logs it and nothing more (`server.py:3018-3019`). A new client MAY send `safe` without a party.

### 2.5 `stats_cache`

`{event:"stats_cache", key, stats}` — sent by the client **immediately before** executing a `box_mon` deposit (`gen3_frlge_client.lua:1631-1632`). Server: `mon_stats[key] = stats`; if the key is in `party_keys`, `party_size -= 1` and the key is discarded (`state.py:281-294`). server.py drops the key from `party_details` (`server.py:2983-2986`). Both `key` and `stats` MUST be truthy or the event is a no-op. The cached `stats` is echoed verbatim in later `party_mon` commands for that key (`state.py:1597-1599`, `state.py:45` (SYNC_COMMANDS), `2149-2151`, `2256-2258`, `2354-2356`).

---

### 2.6 Keyed sync-command lifetime

**Shipped (`server/state.py:59`, `state.py:165`, `state.py:2319-2352`).** A keyed `party_mon`, `box_mon` or `memorialize` remains in flight after its reply leaves the server until a matching keyed acknowledgement resolves it or `SYNC_INFLIGHT_RECONCILES` (= 6) reconciler passes expire the window. `SoulLinkState.sync_inflight` tracks `(key, cmd) -> passes_remaining` per player (`state.py:165`); `_arm_inflight` seeds the window at `SYNC_INFLIGHT_RECONCILES` when `handle_event` drains and clears the player's outbound queue (`state.py:380-388` calls `state.py:2319-2323`); `_ack_inflight` clears every in-flight entry for a key the instant any event carrying that key arrives (`state.py:315`, `state.py:2325-2329`); `_expire_inflight` spends one pass only when `_reconcile_party_keys` actually reconciles, not on a pass it skips for a rebuild or trade (`state.py:2331-2342`, called at `state.py:2348`). Reply delivery is not execution. While the command is queued or in flight, `_has_pending_command` (`state.py:2344-2352`) makes reconciliation treat the target's transient party/box placement as still-pending rather than a player move — consulted at `state.py:2408`, `state.py:2431` and `state.py:2446. Expiry permits reconciliation again; it is not a success acknowledgement or a delivery guarantee.

The existing keyed responses are `sync_retrieve_done` / `sync_retrieve_failed` for retrieval, `box_mon_failed` for failed deposit, and `memorialize_done` / `memorialize_failed` for memorial handling (`handle_event`'s reply branches at `server/state.py:369-419` for the first two; `_handle_memorialize_done`/`_handle_memorialize_failed` at `state.py:2993-3043`). `stats_cache` currently updates cached stats and the party model (`state.py:318-330`); it is sent before the Gen 1 deposit (`lua/gen1/client.lua:533`), not proof of successful deposit, but because it carries the target `key` it still acks that key's in-flight window through the generic `_ack_inflight` path (`server/state.py:2325-2329`). Do not invent a `box_mon_done` event.

## 3. Client → server events

### 3.1 Mon key

| Property | Rule | Cite |
|---|---|---|
| Who computes it | **the client**; the server treats it as an opaque string except via `adapter.parse_ot_id`, `adapter.is_shiny`, `adapter.gender_from_key`, `adapter.is_valid_mon_key` | `base.py:161-173`, `state.py:895`, `state.py:1165` |
| Gen 3 format | `"%08X:%08X"` = `personality:otId`, uppercase hex, 8+8 digits | `memory_gba.lua:635-639`, `gen3_frlge_client.lua:1086` |
| Gen 1/2 format (adapter contract) | three segments `DVs:OTID:species` (`DDDD:TTTT:SS`), OT = middle segment | `base.py:546-548`, `gen1_rby.py:408-420`, `state.py:2501-2503` |
| Uniqueness | not guaranteed for Gen 1; the server refuses (force-faints) a capture whose key already indexes a live link, and both halves of a pair MUST have distinct keys | `state.py:2499-2522` |
| Stability | MUST be stable across party↔box moves and across reconnects; MUST change only via `key_change` (or a trade, §6) | `state.py:2406-2419` |

`species_id` on the wire is the **game-internal** species id (CFRU id for RR, internal index for Gen 1). The adapter converts with `to_national_dex`/`species_name` (`base.py:393-395`, `gen3_frlge.py:573-574`, `gen1_rby.py:429-431`). `level` is the displayed level (int). Slots are 0-based (`slot=i`, `gen3_frlge_client.lua:1295`).

### 3.2 Event table

Dispatch order and the full accepted set: `state.py:249-353`. Anything else is logged and answered with the queue flush (`server.py:3117`).

| `event` | Required fields | Optional fields | Gen 3 trigger | Server effect | Notes / traps |
|---|---|---|---|---|---|
| `hello` | `rom_type:str`, `party:list` | see §2.1 | TCP connect edge `gen3:1915-1945` | §2.2–2.3 | Always answered with `resolved_areas` + `config`. |
| `tick` | — (all optional) | `has_pokeballs:bool`, `party`, `area_id`, `loc_name`, `in_battle:bool`, `is_trainer_battle:bool`, `trainer_id:int`, `opponent_name:str`, `opponent_class:str`, `enemy_party:list`, `is_doubles:bool`, `pc_boxes:list`, `ball_count:int`, `badges:int bitmask`, `kanto_badges`, `trainer_name:str` | every 30 frames (~0.5 s) `gen3:1477`, `gen3:4126-4372` | state: gate, `party_size`, blobs, reconcile `state.py:354-374`; server.py: dashboard state, `battle_state`, dupes-clause check on wild-battle start, `party_details` **replaced** from `party` — all in `server.py`: `_dispatch`'s tick branch (`server.py:2075-2156`) plus the `event == "tick"` `party_details` refresh at `server.py:2177-2178`; `battle_state` and the wild-battle-start dupes check at `server.py:2090-2148` (this range moved from the old `3020-3143` numbering) | `party` omitted while a borrowed party is in RAM (`gen3:4143-4145`). `enemy_party` MUST be `[]` when not in battle to clear stale foes (`gen3:4342`, `server.py`: the in-battle-exit reset in `_dispatch`, `server.py:2095-2101`). The **first** tick with `in_battle=true` MUST carry `area_id` and `enemy_party[0].species_id` for the dupes-at-battle-start prompt (`server.py`: `_dispatch`, `server.py:2129-2148`). |
| `safe` | — | same as tick | first overworld frame after a battle (`pending_safe`) `gen3:2971,2984,4120-4124` | same as tick | Gen 3 sends `{event:"safe"}` only. |
| `area_enter` | `area_id:str` | `loc_name:str` | `loc ~= prev_loc` (any map change) `gen3:2718-2722` | ignored if `area_id==""` or `is_gift_area`; else UNSEEN→PENDING_{partner}, PENDING_{self}→PENDING_BOTH; `_save` `state.py:3333-3421`; server.py: `player_area`, event log `server.py`: `_dispatch`'s `area_enter` branch `server.py:1975-1987` | Gen 3 sends it for every location change even with `area_id=""` (town). `area_id` strings are adapter-namespace snake_case (`route_1`, `oaks_lab`, `intro`, `gift_<g>_<n>`). |
| `capture` | `key`, `area_id` | `species_id:int`, `level:int`, `hp:int`, `maxHP:int`, `nickname:str`, `held_item_id:int`, `is_egg:bool`, `gift:bool`, `in_box:bool`, `stats:dict` | (a) new key in party during/after battle `gen3:3584-3593`; (b) new key in a box post-battle `gen3:3911-3973`, `3981-4081`; (c) new key outside battle after 45-frame buffer, `gift=true` `gen3:3859-3879`; (d) post-freeze recovery `gen3:3256-3265`, `3340-3344` | `_handle_capture` `state.py:1296-1782`: gift detection, shiny clause, bonus pairing, DZ/LINKED/second-capture rejection (`force_faint`+`memorialize`+SE 26+`hud_show`), species clause (`force_faint`+`gui_prompt "[x] Dup X"`+`unresolve_area`), pending add, **quarantine `box_mon`** if `!in_box && party_size>=1 && !gift`, stats cache, link formation (`msgbox "X and Y linked!"`, SE 25 both, `party_mon` both if both parties < 6) or first-capture (`hud_show ">> Got X"` to partner) | `key` and `area_id` MUST be non-empty or the event is dropped. `species_id` MUST be sent for the species clause. `stats` absent ⇒ server builds `{level,maxHP}` from top-level (`state.py:1503-1512`). `in_box=true` MUST be set when the catch landed in the PC (party full) so the server does not queue a redundant `box_mon`. A capture before `has_pokeballs` uses `area_id="intro"` in Gen 3 (`gen3:3620-3621`). |
| `faint` | `key` | `area_id` | party HP >0→0 in overworld `gen3:3683`; in battle after 3-frame debounce / faint-counter / EvRing confirm `gen3:3772,3783,3794` | `party_keys.discard`; ignored if `!pokeballs_obtained`; if key is an ALIVE link → `_propagate_faint`: partner gets `force_faint` (or `force_explode` if `explode_mode && adapter.supports_explode_mode()`) + `play_sound 26`, both get `memorialize`, entry DEAD, `_check_game_over` `state.py:2907-2951`, `2604-2646` | server.py enriches killer from cached `battle_state.enemy_party` (first foe with hp>0) and `_level` from `party_details` `server.py:2954-2968`. A client MUST NOT re-report the HP=0 it wrote itself for a `force_faint` (`gen3:3667-3672`). |
| `no_catch` | `area_id` | `species_id:int`, `level:int` | wild battle ended, nothing caught, area unresolved, 90-frame grace elapsed `gen3:4085-4106` | ignored for gift areas / resolved areas / own pending capture; suppressed with `unresolve_area` if a clause retry is pending for either player; **species-clause reroll** (`gui_prompt "Dupes clause: X -- reroll!"` + `unresolve_area`) if `species_lock` and `species_id` is in a family already held; else area → DEAD_ZONE, `LinkEntry(status=DEAD, cause="dead_zone")`, SE 26 + `msgbox "<Area> is a dead zone!"` to both, partner's pending capture gets `force_faint`+`memorialize`, `_check_game_over` `state.py:3273-3306` | `species_id`/`level` MUST be sent: without `species_id` the reroll can never fire and a legitimate dupe encounter dead-zones the area. The client MUST mark the area resolved locally before sending (`gen3:4091`) and un-mark on `unresolve_area`. |
| `whiteout` | — | — | all previously-alive party mons at HP 0 and a real faint (or EvRing LOSS) confirmed `gen3:3803-3815` | plan rebuild from boxed alive pairs (`party_mon`s + `rebuild_start` to self, `party_mon`s + `hud_show` to partner), then for every ALIVE link whose half is in `party_keys[pid]`: partner `force_faint`, DEAD/`cause="whiteout"`, `memorialize` both; `party_keys[pid].clear()`; `hud_show "[x] PC empty"` + `game_over` both if nothing to rebuild `state.py:2072-2154` | server.py zeroes all `party_details` hp `server.py:2974-2978`. |
| `party_to_box` | `key` | `stats:dict` | known key vanished from party outside battle, HP>0, after 5-frame buffer `gen3:3697-3727`, `3819-3838` | cache stats, `party_size -= 1`, discard key; if key is an ALIVE link and partner's half is in their party (or partner hasn't hello'd) → cancel pending `party_mon` for it, queue `box_mon` to partner, discard from partner's `party_keys` `state.py:2156-2202` | MUST NOT be sent for keys the client moved itself on server command (`sync_written_keys`, `gen3:3711`). |
| `box_to_party` | `key` | `area_id`, `nickname` | known key reappeared in party after 5-frame buffer `gen3:3594-3611`, `3840-3857` | rebuild path confirm; quarantine enforcement (`box_mon` + `hud_show "[!] X: unlinked"`); dead/memorial → `memorialize` + `hud_show`; partner party logically full (≥6 counting pending `box_mon`s) → `box_mon` back + `hud_show "[!] X: re-boxed"`; else add key, queue `party_mon{key,nickname?,stats?}` to partner (cancelling pending `box_mon`) `state.py:2204-2310` | Partner's key is **not** added to `party_keys` until their `sync_retrieve_done`. |
| `key_change` | `old_key`, `new_key` | `reason:str`, `new_species:int`, `new_nickname:str` | RR Nature Changer: disappeared+appeared keys with equal `otId:species:level:nickname` signature `gen3:3438-3557` | **validate → accept \| reject → mutate** (`_handle_key_change`). Accept: migrate `old→new` in `_key_index`/MonInfo (incl. `encounter_a/b`), pending captures, `party_keys`, `mon_stats`, `bonus_keys`, `pending_memorials`, queued commands (`key` and `old_key` fields) + in-flight ids, `pending_bonus`, `partner_blobs`, `rebuild_pending`, `pending_trade`, then the presentation caches (`party_details`, `_mon_cache`, `pc_boxes`); update `species`/`nickname` if given; reply `key_change_ack{migrated:true}`. If the old key's link is already DEAD/MEMORIAL the death is re-queued under the new key (`force_faint` + `memorialize`, deduped). Replay (already migrated) or an `old_key` referenced nowhere: `key_change_ack{migrated:false}`, no mutation. Reject when `new_key` is load-bearing — a different ALIVE link, or present in any live structure of either player or in a party / non-memorial box of the presentation caches — with `key_change_rejected{reason}` and **nothing migrated**; the old key's link is then retired `cause="identity_lost"` (partner `force_faint`, both memorialized). A DEAD/MEMORIAL index hit is accepted (buried keys are reusable; `KEY COLLISION` logged). | `reason` vocabulary: `nature_change` (default when absent; Gen 3 never sends it), `evolution`, `npc_trade`, `trade_undo`, `transform`, `apex_chip`; unknown values are still accepted. Only server.py's event-feed text branches on it (`new_species is not None`→"evolved", `reason=="trade_undo"`→"trade reverted", else "nature/ability changed"). **MUST NOT** be sent for a trade (§6.5). A client that keeps an old→new alias until acknowledged drops it on `key_change_ack` and reverts to the old key on `key_change_rejected`. |
| `trainer_battle_start` | `trainer_id:int`, `battle_id:int`, `session:hex` | — | in battle, non-wild, non-borrowed, same id for 2 consecutive frames, once per battle `gen3:2317-2343` | if `trainer_id ∈ adapter.rival_trainer_ids()` and `rival_team_swap` and partner has blobs → `replace_rival_team` `state.py:3087-3145` | `trainer_id` MUST be a JSON int > 0 (`isinstance(int)` check). `session` + `battle_id` are the client's battle request identity (card C5-10): `session` is a nonce minted once per client PROCESS, `battle_id` a counter incremented on every battle-begin signal. The server stores the pair (with `trainer_id`) and echoes it on every command belonging to that battle. Both are OPTIONAL on the wire — Gen 1, Gen 2 and old Gen 3 clients never send them, and the server then stores nothing and echoes nothing. A malformed pair (a boolean, fractional or out-of-range counter; a non-hex or >16-char nonce) is a protocol violation, never coerced away. The NEW Gen 3 client REQUIRES both on `replace_rival_team`. The nonce is what makes a client restart safe: a restarted client's counter 1 is not the previous session's counter 1. |
| `rival_team_replaced` | `trainer_id:int`, `species_ids:list[int]` | `error:str` | after `replace_rival_team` settles `gen3:2443-2451`, `814-826`, `850-852` | `error` ⇒ `hud_show "Rival Swap failed: <error>"`; else log `state.py:3225-3249` | Gen 3 error values: `not_in_battle`, `patch_required`, `patch_failed`, `patch_timeout`, `stage_failed`, decode messages, and `stale_battle_id` (the command's `session`/`battle_id` is missing, malformed, from another client session, or not the battle the client is in — nothing was written). |
| `stats_cache` | `key`, `stats` | — | before deposit `gen3:1631` | §2.5 | |
| `sync_retrieve_done` | `key` | — | after `party_mon` succeeded **or** the mon was already in the party `gen3:1679-1680`, `1740-1741`, `2490`, `2505` | `party_keys.add`; rebuild bookkeeping, `rebuild_done` when complete `state.py:369-377`, `2389-2404` | ACK for `party_mon`. |
| `sync_retrieve_failed` | `key` | — | party full after 3 retries / no stats / write failed `gen3:1707`, `1726`, `1745`, `2508` | discard key; drop from rebuild; **re-box the partner's linked half** (`box_mon` + `hud_show "[!] X: re-boxed"`) `state.py:378-405` | NACK for `party_mon`. |
| `box_mon_failed` | `key` | `reason:str` | **never sent by Gen 3** | restore key to `party_keys`, `party_size += 1`, `_save` `state.py:3333-3421` | ⚠ DISAGREEMENT: the server discards the key the moment it queues `box_mon`; a client that cannot deposit and does not send this leaves the server's party model one mon short (`gen3:1653-1656` only logs). A new client MUST send it on deposit failure. |
| `memorialize_done` | `key` | `box:int` | after the mon is in the memorial box `gen3:1770` | discard from `pending_memorials`+`party_keys`; when both halves are done → `LinkStatus.MEMORIAL` + `memorial.json` `state.py:2993-3016` | `box` is ignored by the server. |
| `memorialize_failed` | `key` | `reason:str` | Lua path failed `gen3:1829` | treated as done for pair-status purposes `state.py:3018-3043` | |
| `trade_request` | — | — | talk to ghost / PC-NPC when no UI or trade in flight `gen3:2167-2171`, `2185-2190` | §6.1 | Silently ignored while a trade is pending. |
| `menu_result` | `token:str`, `choice:int` | — | poll of `show_menu`/`show_choices` `gen3:2193-2201`, immediate cancel `901-933` | §6.2/6.3 | |
| `mon_chosen` | `token:str`, `slot:int` | — | poll of `choose_mon` `gen3:2202-2205`, immediate cancel `934-946` | §6.2 | `slot` 0-5; anything else = cancel (Gen 3 uses 7). |
| `trade_done` | `new_key:str`, `new_species:int` | `token:str`, `slot:int` | after the trade scene / silent swap `gen3:657-670` | §6.4 | Empty `token` accepted for compat; a wrong token is ignored. |
| `status` | `badges:int` **count 0-8** | — | every ~300 frames when the badge count changed `gen3:2285-2295` | `player_badges[pid]` (SoulLinkState) clamp 0-8 `state.py:520-528` | ⚠ Different from `hello`/`tick.badges` (bitmask, SLinkServer). The wide `link_panel` "Badges" row reads this count (`server.py:2629`); the 20-column layout popcounts the bitmask instead (`server.py:2647-2652`). |
| `ghost_pos` | `mg,mn,x,y,f,gfx,mv,run,an:int`, `imgs,anim:int`, `pcol:hex[≤64]` | — | ~20 Hz in overworld when patched `gen3:2151-2158` | relayed to partner as `ghost_pos` cmd, coalesced to one in queue; dropped when `overworld_presence` off `state.py:461-494` | Non-int field ⇒ sample dropped. ⚠ Comment mismatch: client says `x,y` are world pixels (`gen3:2153`), server/parser say tile coords (`state.py:471`, `gen3:285`). Pass-through ints either way. |
| `peer_interact` | — | — | legacy, not sent by Gen 3 | `msgbox "<name> says hey!"` to partner if presence on `state.py:496-503` | |

Fields the server reads from **enrichment-only** paths (server.py, not state.py): `capture.hp/level/maxHP/nickname/species_id/held_item_id|held_item/ability_id|ability` → `party_details` (`server.py:2933-2944`); `faint.key` → `party_details[key].hp=0` (`server.py:2948-2949`).

---

### 3.3 Gen 1 boxed RELEASE: recorded protocol gap

A Bill's PC RELEASE of a boxed linked mon is **not on the wire**. The rewritten client distinguishes a standalone boxed removal from the removal completing WITHDRAW, logs `RELEASE_SEEN key=... box=...`, and emits no event (`lua/gen1/client.lua:750-761`). A `party_to_box` for a mon that was never in the party would be false. There is no `release` event in this contract.

The pair therefore stays **ALIVE with a phantom boxed half** in server state; the surviving half is not automatically retired. This is a documented shared-protocol gap, not proof of complete PC-release synchronization (`docs/gen1_requirements.md:155-157`; `tools/e2e_duo.py:150-156`). A box snapshot or local log marker is not a release acknowledgement. Preserve the distinction between DEPOSIT/WITHDRAW synchronization and this RELEASE limitation.

### 3.4 `whiteout` → rebuild sequence

The client can emit the final per-mon `faint` followed immediately by one `whiteout`, before `battle_end` and the engine's blackout/heal path; the blackout hook only supplies `whiteout` if it has not already been sent (`lua/gen1/client.lua:605-618`, `:681`). Do not require a `whiteout` death cause on links already retired by their preceding faint events.

1. `_handle_whiteout` plans against surviving ALIVE links whose two halves are boxed. It excludes pending/unlinked captures (`server/state.py:2457-2484`, `_alive_pc_mons`) and caps picks by the partner's available party room (`state.py:2486-2513`, `_plan_rebuild`).
2. For the whited-out player, enqueue `party_mon` for each chosen key, then `rebuild_start{text,keys}`; for the partner, enqueue corresponding `party_mon` commands then the informational `hud_show` (`server/state.py:2515-2567`, `_queue_rebuild_commands`). These are per-player queues, not a globally ordered cross-socket stream.
3. Rebuild retrievals are queued before any additional force-faint/memorial commands produced by this whiteout handler (`server/state.py:2020-2050` queues the rebuild before `state.py:2054-2072` force-faints and memorializes). Earlier per-mon faints may already have queued memorials. Gen 1 appends a last-mon-blocked memorial to the deferred tail so a later retrieval can unblock it (`lua/gen1/client.lua:552-557`).
4. At each cartridge's safe write checkpoint, `party_mon` yields keyed `sync_retrieve_done` or `sync_retrieve_failed` (`lua/gen1/client.lua:546-547`). The server adds confirmed keys, records rebuild completion, or drops failed keys and may re-box the partner (`server/state.py:369-405`).
5. Once every queued key for that player's rebuild has resolved, send `rebuild_done` and clear `rebuild_pending[player]` (`server/state.py:2569-2584`, `_maybe_finish_rebuild`). This banner completion is not itself a bilateral barrier: physical proof requires both sides' retrieval acknowledgements and saved-state readback (`prep/PLAN_v3.9.md:494-505`).

With no rebuildable pair, the game-over path applies; the whiteout handler handles retired party links with no picks and also invokes the shared game-over check (`server/state.py:2085-2101`). Rebuild does not resurrect DEAD/MEMORIAL links. A release-created phantom boxed half remains a separate limit, not a guaranteed rebuild candidate on the cartridge.

## 4. Snapshot shapes

### 4.1 Party entry (element of `party` in `hello`/`tick`/`safe`)

Built by `build_party_snapshot` (`gen3_frlge_client.lua:1186-1314`, fields at `1294-1307`).

| Field | Type | Required | Server consumer | Cite |
|---|---|---|---|---|
| `key` | key | **MUST** | `party_keys` (`m["key"]` — a missing key raises `KeyError` in `_handle_hello` and kills the connection coroutine), `_reconcile_party_keys`, blobs, `party_details` (skipped if falsy) | `state.py:1003`, `state.py:2362`, `server.py:2899` |
| `maxHP` | int | MUST | hello: only `maxHP > 0` entries count as party members; HP bars | `state.py:1101`, `server.py:2990-3006` |
| `hp` | int | MUST | hello offline-faint detection (`hp == 0`), alive set for re-quarantine; HP bars | `state.py:1113`, `state.py:1127-1138` |
| `level` | int | MUST | `partner_blobs.level`, display back-fill, `_resolve_level`, killfeed level | `state.py:3085`, `server.py:4709` |
| `slot` | int 0-5 | SHOULD | `partner_blobs.slot` (trade `apply_trade.slot`), party ordering (`999` fallback) | `state.py:3083`, `server.py:4707` |
| `species_id` | int (game-internal) | SHOULD | display back-fill into MonInfo, blobs, sprites, names, types | `state.py:1182`, `server.py:2460-2463` |
| `nickname` | str | SHOULD | MonInfo back-fill, HUD labels, dashboard | `state.py:1176-1191` |
| `active` | bool | SHOULD (battle) | active-battler marker, `stat_stages` shown only when true, doubles inference on foes | `server.py:3011-3012`, `server.py:2934`, `server.py:2126-2128` |
| `status_cond` | int (Gen 3 `status1` layout) | SHOULD | `status_icon_html` (dashboard) and `adapter.status_token` (`link_panel`) | `server.py:3010`, `server.py:1645`, `html_render.py:150-166` |
| `stat_stages` | list[7] of int 0-12, 6 = neutral, order ATK,DEF,SPD,SATK,SDEF,ACC,EVA; `nil`/absent when not active | optional | `stat_stages_html(stages, adapter.stat_stage_labels())` — `int(raw)-6` | `html_render.py:169-196`, `server.py:3011`, `memory_gba.lua:437-446` |
| `moves` | list[4] int move ids | optional | `move_details` via `adapter.move_data` | `server.py:2421-2447` |
| `pp` | list[4] int | optional | `current_pp` | `server.py:2439-2446` |
| `pp_bonuses` | int (2 bits/move, Gen 3) **or** `pp_ups: list[4]` (Gen 4) | optional | max PP scaling `base + base*ups//5` | `server.py:2428-2444` |
| `held_item_id` (legacy alias `held_item`) | int | optional | `adapter.item_name` | `server.py:2890`, `server.py:3798-3799` |
| `ability_id` (legacy alias `ability`) | int | optional | `adapter.ability_name` (hidden when `!supports_abilities()`) | `server.py:2891`, `server.py:3389-3390` |
| `form` | int | optional (Gen 4+) | sprite form | `server.py:2461-2463` |
| `blob_hex` | hex, **exactly `adapter.party_blob_size()*2` chars** | MUST for trade / rival swap | `_ingest_party_blobs` — wrong length or non-hex ⇒ entry silently dropped from `partner_blobs` ⇒ that mon is never trade-eligible and rival swap says "no cached party blobs" | `state.py:3045-3089`, `base.py:204-218` |

Gen 3 does **not** send `ot`, `nature`, `gender` or `pp_ups` in the party entry; `gender` is derived server-side from `adapter.gender_from_key(key, species_id)` (`server.py:2892`).

### 4.2 `tick` top-level fields (beyond `party`)

| Field | Type | Meaning | Consumer |
|---|---|---|---|
| `has_pokeballs` | bool | nuzlocke gate; only `True` has an effect | `state.py:431` |
| `ball_count` | int | dashboard | `server.py:2076-2077` |
| `area_id`, `loc_name` | str | current area / display location | `server.py:3094-3100` |
| `in_battle` | bool | battle edge detection; `false` clears `trainer_id/opponent_*/enemy_party/is_doubles` | `server.py:2091-2101` |
| `is_trainer_battle` | bool | wild vs trainer; suppresses dupes check | `server.py:2102-2103`, `2130-2131` |
| `trainer_id` | int | `adapter.trainer_info(tid)` → opponent name/class; if the adapter returns no class, `opponent_name`/`opponent_class` from the tick are accepted instead | `server.py:2104-2118` |
| `opponent_name`, `opponent_class` | str | non-RR fallback for trainer display and killfeed | `server.py:3057-3064` |
| `enemy_party` | list[FoeEntry] (§4.3); `[]` when not in battle | battle panel, killer enrichment, dupes check (`[0].species_id`) | `server.py:2120-2121`, `2485-2496`, `2133-2134` |
| `is_doubles` | bool | doubles chip; if absent, inferred from >1 `active` foe | `server.py:2122-2128`, `2936` |
| `pc_boxes` | list[BoxEntry] (§4.4), full cache every tick | box table, memorial contamination scan, `_mon_cache` | `server.py:2084-2089` |
| `badges` | int bitmask | 8 gym circles, badges overlay, compact panel popcount | `server.py:2078-2079`, `3270-3289` |
| `kanto_badges` | int bitmask | second-region badges (Gen 4) | `server.py:2080-2081`, `3270-3289` |
| `trainer_name` | str | dashboard | `server.py:2082-2083` |

`money` and `frame` are **not** part of the protocol (nothing sends or reads them).

### 4.3 Foe entry (element of `enemy_party`)

Gen 3 builds it from `M.readEnemyParty()` (`memory_gba.lua:1541-1577`) overlaid with live `gBattleMons` data (`gen3_frlge_client.lua:4162-4340`).

| Field | Type | Consumer | Cite |
|---|---|---|---|
| `species_id` | int | name, sprite, types, killer species, dupes | `server.py:2490-2495`, `3001`, `2134` |
| `level` | int | display, killer level | `server.py:2024`, `3004` |
| `hp`, `maxHP` | int | HP bar; "active foe" for killer = first with `hp > 0` | `server.py:3946-3947`, `2957` |
| `active` | bool | active marker, stat stages, doubles inference | `server.py:2934`, `2126` |
| `ability_id`, `held_item_id`, `status_cond`, `stat_stages`, `moves`, `pp`, `pp_bonuses`/`pp_ups`, `form`, `key` | as §4.1 | battle panel | `server.py:3949-3951`, `3436-3473`, `3977` |

### 4.4 Box entry (element of `pc_boxes`)

Built by `scan_next_boxes` (`gen3_frlge_client.lua:1409-1467`, entry at `1451-1460`): the client scans a few boxes per tick and always sends the **full accumulated cache**.

| Field | Type | Consumer | Cite |
|---|---|---|---|
| `box` | int, 0-based box index | memorial contamination (`box == adapter.memorial_box_index`), display `box+1` | `server.py:4637`, `4645`, `4694` |
| `slot` | int, 0-based | display `slot+1`, logs | `server.py:4658`, `4695` |
| `key` | key | `_cache_mon_info`, dead-in-regular-box re-memorialize, level fallbacks | `server.py:1735-1775`, `8066-8079` |
| `species_id`, `nickname` | int, str | display | `server.py:8023-8025`, `4386` |
| `level` | int | optional; falls back through `mon_stats` → link entry → `party_details` → `_mon_cache` | `server.py:4709-4728` |
| `held_item_id`, `ability_id`, `moves` | | box table | `server.py:4390-4391`, `3423-3432` |

There is **no** "active box index" on the wire.

### 4.5 What the status builders read (adapter-relevant summary)

| Builder | Reads | Adapter calls |
|---|---|---|
| `_build_status_dict` `server.py:2407-2652` | `connected_players`, `player_area(_id)`, `ball_count`, `badges`, `kanto_badges`, `trainer_name`, `pc_boxes`, `party_details` (ordered by `slot`), `battle_state`, `identity_error`, `admission`, links/killfeed/pending/bonus | `species_name`, `sprite_html(sid, form)`, `ability_name(aid, sid)`, `move_data`, `area_display_name`, `gym_badge_slugs(rom_type)`, `encounter_table` + `sprite_src` via `adapter_for(pid)` |
| `_handle_dashboard_template` `server.py:2672-2688` | the dict above; per mon: `nickname, species_id, gender, sprite_html, active, level, held_item_id, ability_name/id, move_details, hp, maxHP, status_cond, stat_stages` | `supports_abilities`, `stat_stage_labels` (`server/ui_capabilities.py:26-30`), `gender_from_key`, `item_name`, `ability_description`, `species_types`/`type_name`, `memorial_box_index`, `trainer_info` |
| `_build_link_panel` `server.py:1606-1722` | links, `party_details` (`species_id, nickname, level, hp, maxHP, status_cond`), `_mon_cache`, `area_states`, `SoulLinkState.player_badges` (count) or `SLinkServer.player_badges` (bitmask) | `area_display_name`, `species_name`, `status_token`, `info_panel_width`, `supports_info_panel` |
| `_build_party_overlay_context` `server.py:2854-2900` | `party_keys` order, `party_details` `hp,maxHP,species_id,species_name,nickname,level,sprite_html,status_cond,stat_stages,active` | — |
| `_build_badges_overlay_context` `server.py:3270-3289` | `badges` bits 0-7, `kanto_badges` bits 0-7 for slugs 8+ | `gym_badge_slugs` |
| `_check_memorial_box_contamination` `server.py:4598-4697` | `pc_boxes[].box/key/nickname/species_id/slot` | `memorial_box_index`, `species_name` |
| `_memorial_box_indices` `server.py:4544-4568` | dead count | `memorial_box_index`, `mons_per_box` |

`status_icon_html` (`html_render.py:150-166`) decodes `status_cond` with the Gen 3 bit layout directly (SLP bits 0-2, TOX 0x80, PSN 0x08, BRN 0x10, FRZ 0x20, PAR 0x40). A client for a generation with a different layout MUST translate to this layout on the wire (see §8).

---

## 5. Server → client commands

Every command is a JSON object with `cmd`. Fields are listed exhaustively. "Obligation": **immediate** = act on receipt; **deferred** = the client MUST hold it until its own safe-state predicate is true (Gen 3: overworld, no sync cooldown, post-battle grace over, EOB settled, no party freeze, no native op in flight — `gen3_frlge_client.lua:2603-2611`, `2634-2635`) and execute in FIFO order, one per frame (`:2636-2716`). Colour fields `r,g,b` are 0-255; `frames` is a display duration at 60 fps (client default 300 when absent, `:972`).

| `cmd` | Fields | Obligation | ACK event | NACK event | May drop? | Gen 3 handling | Server follow-up / cite |
|---|---|---|---|---|---|---|---|
| `noop` | — | ignore | — | — | yes | `:1037` (silent) | `state.py:384`, `server.py:2443,2449,2522` |
| `force_faint` | `key`, `nickname` | **immediate** if the mon is benched/out of battle (write HP=0, suppress the resulting local faint); **deferred until switch-out or battle end** if it is the active battler — this is the reference (old) client's behaviour (line 11). **On the new Gen 3 client, FR/LG singles instead apply this immediately, no held window, via mechanism P+H** (engine Perish KO + controller hand-off; doubles still hold) (owner rulings 15-16, `docs/gen3/G4_request_draft.md` §6, 2026-09-23/24; built `1b3943e3`/`39bcc4f8`/`66595498`/`9719b519`/`375cb963`/`cdc571f1`, review fixes `4a91daeb`/`9e227101`); RR gets parity at G5 | none (server already marked the pair DEAD) | none | **no** | `state.py:2926`, deferred flush `state.py:2544-2583` | `state.py:2604-2626` (partner half), rejections `state.py:1257,1362,1383,1407,1461,1537`, DZ `state.py:1909`, whiteout `state.py:1968` |
| `force_explode` | `key`, `nickname` | as `force_faint`, but an active battler is coerced into Explosion (RR); bench = immediate HP=0. **On the new Gen 3 client, RR's Explode keeps its hold** (`battle.commit_hold`) **but its commit plan now ends in the same `battle.handoff` tail as P, so it fires immediately again without a press, as on the old RR client** (owner ruling 19, `docs/gen3/G4_request_draft.md` §6 item 19, 2026-09-24; G5) | none | none | no | `state.py:2926`, settle `state.py:2345-2428` | only when `explode_mode && adapter.supports_explode_mode()` `state.py:2619-2622` |
| `box_mon` | `key` | deferred; idempotent (no-op if the key is already boxed or unknown); MUST refuse to deposit the last party mon | `stats_cache` before the write (informational) | **`box_mon_failed{key,reason}`** on failure | no | `state.py:857-867`, `exec_box_mon state.py:1601-1668` (⚠ never sends `box_mon_failed`) | server pre-discards the key and decrements `party_size` at queue time (`state.py:2019-2027`, `2047-2048`); cancels an opposing pending `party_mon` `state.py:2043-2046` |
| `party_mon` | `key`, `nickname?`, `stats?` (`{level,maxHP,attack,defense,speed,spAtk,spDef,pp1..pp4?}`) | deferred; idempotent (already in party ⇒ still ACK) | **`sync_retrieve_done{key}`** | **`sync_retrieve_failed{key}`** (party full after retries, no stats, write failed) | no | `state.py:868-882`, `exec_party_mon state.py:1670-1748` | server adds the key to `party_keys` only on ACK (`state.py:295-299`); on NACK re-boxes the partner's half (`state.py:304-331`) |
| `memorialize` | `key` | deferred; move the (dead) mon to the memorial box; MUST NOT empty the party — block until a `party_mon` lands, or drop if `game_over` was received | **`memorialize_done{key,box}`** | **`memorialize_failed{key,reason}`** | only when game over and it is the last party mon (`state.py:2983`) | `state.py:883-896`, `exec_memorialize state.py:1781-1832`, blocking `state.py:2639-2675` | `state.py:2669-2680`; re-queued on every hello until acked (`state.py:1002-1007`) |
| `game_over` | — | immediate: persistent HUD, sound; also unblocks dropping the last-mon `memorialize` | none | none | no | `state.py:1263-1264` | `state.py:1998`, `2941`, `1115` |
| `msgbox` | `text`, `fb?` (`"prompt"`), `r?,g?,b?,frames?` | immediate: native in-game box when safe, else centre prompt (`fb=="prompt"`) or HUD line | none | none | yes (display only) | `:897-900`, `try_native_box :705-719` | 17 sites in state.py (links, dead zones, shiny, trade texts) |
| `gui_prompt` | `text`, `r,g,b,frames` | immediate: momentous overworld prompt (dupes/clause reroll); native box when safe else centre prompt | none | none | display only | `state.py:1410` | `state.py:1261,1465,1548,1669` |
| `hud_show` | `text`, `r?,g?,b?,frames?` (⚠ WRONG SAVE variant: `color:[r,g,b]`, `duration`) | immediate HUD line | none | none | display only | `:971-972` | 14 sites in state.py + `:910-915` |
| `play_sound` | `sound:int` (Gen 3 SE id: 25 SE_SUCCESS, 26 SE_FAILURE, 22 SE_BOO, 95 SE_SHINY). Gen 1 maps 25/95→1, 26→2, 22→3 and writes the code to the companion mailbox `+7` when `config.native_sounds` and the cartridge's `sfx` capability both hold (`lua/gen1/panel.lua request_sfx`; the ROM picks the per-bank sound) | immediate | none | none | yes | `state.py:850`; gen1 `client.lua play_sound` | `state.py:718,1177,1186,1259,1332-1333,1364,1385,1409,1463,1539-1540,1578-1579,1878,1884,2623` |
| `resolved_areas` | `areas:list[str]` | immediate: mark each area resolved locally; set the "seeded" flag (hello reply carries it even when empty) | none | none | no | `state.py:1211` | `state.py:1050-1068` |
| `unresolve_area` | `area_id` | immediate: clear the local resolved mark so the encounter is available again | none | none | no | `state.py:1350` | `state.py:1200,1271,1321,1470,1555,1676,1798,1813` |
| `config` | `overworld_presence, native_messages, native_sounds, battle_calc, pc_trade_npc : bool` | immediate; sent in every hello reply | none | none | no | `state.py:1226` | `state.py:1076-1082` |
| `rebuild_start` | `text`, `keys:list[key]` | immediate: show persistent REBUILDING banner | (completes via the `party_mon` ACK/NACKs) | | no | `state.py:2557` | `state.py:2376-2380` |
| `rebuild_done` | — | immediate: clear banner | none | none | no | `state.py:2580` | `state.py:2400` |
| `replace_rival_team` | `trainer_id:int`, `n:int`, `blobs_hex:list[hex]`, `source:"auto"\|"manual"`, `session:hex?`, `battle_id:int?` | immediate, in battle only | **`rival_team_replaced{trainer_id,species_ids}`** | `rival_team_replaced{...,error}` | no (must NACK) | `state.py:806-854`, settle `state.py:2430-2453` | `state.py:3052-3100` |
| `show_choices` | `token`, `options:list[str]`, `text` | immediate: native multichoice; if impossible reply cancel at once | `menu_result{token, choice}` (0-based index) | `menu_result{token, choice:127}` | no (must reply) | `state.py:606`, poll `state.py:2193-2201` | `state.py:522-523` |
| `show_menu` | `token`, `text` | immediate: native YES/NO; if impossible reply `0` at once | `menu_result{token, choice}` (1 = yes) | `menu_result{token, choice:0}` | no | `state.py:699`, poll `state.py:2193-2201` | `state.py:578-580` |
| `choose_mon` | `token` | immediate: native party picker; if impossible reply cancel at once | `mon_chosen{token, slot}` (0-5) | `mon_chosen{token, slot:7}` | no | `state.py:676`, poll `state.py:2202-2205` | `state.py:555`, `606` |
| `apply_trade` | `slot:int`, `blob_hex:hex`, `old_key:key`, `token` | deferred until the field is clear; locate the mon by `old_key` (slot is a snapshot), stage + run the trade scene, or fall back to a faithful slot write | **`trade_done{token, slot, new_key, new_species}`** | (none — `trade_done` with the pre-trade key is the "nothing changed" signal; watchdog force-completes) | **no** | `state.py:569`, state machine `state.py:2211-2283`, `emit_trade_done state.py:657-670` | `state.py:648-653` |
| `ghost_pos` | `mg,mn,x,y,f,gfx,mv,run,an,imgs,anim:int`, `pcol:hex` | immediate, render peer ghost | none | none | yes (ephemeral, coalesced) | `state.py:967-970` | `state.py:461-494` |
| `link_panel` | `rows:list[str]` (`label\|name\|level\|hp\|barpx\|state\|status` or plain text; empty label = continues pair) | immediate: stage into native panel; sent only when content changed and `_player_has_panel(pid)` | none | none | yes | `server.py:980-988`, `info_stage server.py:183-195` | `server.py:1720`, `3150-3155` |
| `pending_sync` | `message` | — | | | | `:855-856` | ⚠ **never emitted by the server** (dead client branch) |
| `key_change_ack` | `old_key`, `new_key`, `migrated:bool` | immediate: drop any old→new alias; `migrated:false` = the server had nothing under `old_key` (replay, or an unlinked mon) | none (one-way) | none | yes (Gen 3 ignores unknown commands, §1.2) | not handled | `_handle_key_change`, same reply as the event |
| `key_change_rejected` | `old_key`, `new_key`, `reason:str` | immediate: the server still knows the mon as `old_key`; the client MUST NOT re-send the change (the pair is being retired `identity_lost`, a `force_faint` for the partner and `memorialize` for both follow) | none (one-way) | none | yes | not handled | `_handle_key_change`, same reply as the event |

There is no `hud` command; the name is `hud_show`.

### 5.0 Gen 1 LINK PANEL mailbox (Red/Blue companion patch)

`link_panel{rows}` is a server payload, not permission to write whenever it arrives. The client holds sanitized, pre-rendered pages; the cartridge owns the screen, whites it out, draws a fallback and requests staging (`lua/gen1/panel.lua:1-10`, `:100-131`). This is separate from the native SLINK TRADE overlay ABI.

The mailbox base is `$DEE2`: offsets `+0..3` are `SLNK`, `+4` ABI, `+8` capabilities (`CAP_PANEL = $02`), `+9` state (`CLOSED=0`, `AWAIT=1`, `STAGED=2`), `+10` requested zero-based page (patch → client), and `+11` page count (client → patch; zero means one to the patch). Presence requires the beacon and capability bit, not an ABI-number guess (`lua/gen1/panel.lua:13-35`, `:83-95`).

Only an **observed non-AWAIT → AWAIT transition** arms a staging opportunity: CLOSED → AWAIT on open or STAGED → AWAIT on a page turn. First attachment to an already-AWAIT mailbox has unknown age and MUST NOT paint. A persistent AWAIT does not renew the deadline (`lua/gen1/panel.lua:145-164`).

Each page is 18 rows × 20 tiles (360 bytes), up to eight pages. The client accepts staging at elapsed frames ≤60 from its observed transition and refuses later staging; the patch's fallback timeout is 90 frames. The narrow `panel` write window permits only the title's `wTileMap` range plus state/page-count bytes (`lua/gen1/panel.lua:65-70`, the `allow` predicate). Write all tiles, then page count, then publish STAGED **last** (`:134-141`, `self:stage()`).

Rows arriving too late remain held for a future valid open/page transition, never paint over an already revealed fallback. The patch can retain AWAIT after timeout, so the client deadline is mandatory (`docs/gen1_requirements.md:160-162`). Yellow duo/trade/panel is outside this release's scope because the mailbox space is unavailable (`:157-158`); do not infer capability from generation alone.

### 5.1 Prompt token handshake

| Flow | Server sends | Client replies | Codes | Timeouts |
|---|---|---|---|---|
| Action menu | `show_choices{token, options:["Trade","Say hey"], text}` `state.py:522-523` | `menu_result{token, choice}` | `choice` = 0-based option index; **127 (0x7F) = cancel/B**; anything not 0 or 1 aborts silently `state.py:596-612` | client `MENU_TIMEOUT=1860` frames then cancel `gen3:535`, `2196`; server watchdog §6.6 |
| Party pick | `choose_mon{token}` `state.py:606`, re-prompt `state.py:555` | `mon_chosen{token, slot}` | `slot` 0-5 valid; `<0` or `>5` = cancel (Gen 3 sends **7**) `state.py:537-544`; ineligible slot ⇒ `msgbox "Pick a linked POKeMON!"` + new `choose_mon` (same token), max 3 re-prompts then `msgbox "Trade canceled."` `state.py:546-556` | same |
| Yes/No confirm | `show_menu{token, text}` `state.py:578-580` | `menu_result{token, choice}` | `1` = yes/accept; **anything else = decline** (Gen 3 sends 0 on cancel/failure) `state.py:616-623` | same |

Tokens are `"t<N>"` (`state.py:511`). A reply with a non-matching token is ignored (`state.py:531`, `588`). Only the initiator's `menu_result`/`mon_chosen` count in phases `menu`/`choosing`; only the partner's `menu_result` counts in `confirming` (`state.py:533`, `597`, `614`). The client MUST reply exactly once per prompt, immediately with the cancel code when it cannot render the prompt (unpatched, in battle, another prompt in flight — `gen3:905-946`).

---

## 6. Trade sub-protocol

State lives in `SoulLinkState.pending_trade` (one slot for the whole run, `state.py:530`). Only **linked pairs** may be traded: the initiator's mon must be one half of an ALIVE link **and** both halves must have cached blobs, i.e. both mons are in their owners' parties with valid `blob_hex` (`_eligible_trade_pairs`, `state.py:530-550`).

### 6.1 Phases

| Phase | Entered by | Server → initiator (I) | Server → partner (P) | Exit |
|---|---|---|---|---|
| (none) | — | — | — | `trade_request` from either player while `pending_trade is None` `state.py:505-509` |
| `menu` | `trade_request` | `show_choices{token, ["Trade","Say hey"], text}`; `text` = `"OAK: Took you long enough.\n<P> is waiting. Make it quick."` when presence off, else `"<P> is right here!\nWhat will you do?"` `:516-523` | — | `menu_result` from I: 0 → `choosing` (or abort with `msgbox "No linked pair in your party to trade."` if nothing eligible); 1 → abort + `msgbox "<I> says hey!"` to P; else abort `:596-612` |
| `choosing` | choice 0 | `choose_mon{token}` `:606` | — | `mon_chosen` from I: cancel → `msgbox "Trade canceled."`; ineligible → re-prompt ×3; eligible → `confirming` `:526-581` |
| `confirming` | eligible pick | `hud_show "Trade offer sent - waiting for partner..."` (600 frames) `:575-577` | `show_menu{token, "Trade your <P's mon> for <I's mon>?"}` `:578-580` | `menu_result` from P: 1 → `_execute_trade`; else `msgbox "Your partner declined the trade."` to I and `"Trade declined."` to P `:613-623` |
| `applying` | `_execute_trade` `:625-658` | `apply_trade{slot:a_slot, blob_hex:b_blob, old_key:a_key, token}` to **a** | `apply_trade{slot:b_slot, blob_hex:a_blob, old_key:b_key, token}` to **b** `:648-653` | both `trade_done` received → `_commit_trade`; or watchdog force-commit |
| committed | `_commit_trade` `:684-727` | `play_sound 25` + `msgbox "Traded <gives> for <gets>!"` to both `:715-721` | same | `pending_trade=None`, `_trade_settle_ticks = {a:12, b:12}` `:724-727` |

`_execute_trade` **re-validates** before dispatch: the link must still be ALIVE and both keys still in their `party_keys`; otherwise both get `msgbox "Trade canceled - a POKeMON is\nno longer available."` and the slot is freed (`state.py:749-790`).

### 6.2 `apply_trade` client obligations

1. Buffer it; wait for a clear field (no script/menu/native box, no prompt in flight) — `gen3:2221-2242`.
2. Re-locate the mon by `old_key` (party may have been reordered since `mon_chosen`); fall back to `slot` only if the key is absent — `relocate_trade_slot :678-695`.
3. Replace that party slot with the decoded `blob_hex` (native trade scene preferred; silent faithful write as fallback) — `:2231-2281`.
4. Read back the slot and send `trade_done{token, slot, new_key, new_species}` (`emit_trade_done :657-670`). `new_species` captures a trade evolution.
5. Freeze party diffing during the apply and for a settle window after (`party_diff_ok` includes `not pending_trade_apply`, `:3392`; `POST_UNFREEZE_SETTLE` `:3436`).
6. Defer all `box_mon`/`party_mon`/`memorialize` while the trade is in flight, then **purge** any that target the old or new key (`:2634`, `:3423-3429`).

### 6.3 `_handle_trade_done` (`state.py:792-814`)

Accepts only in phase `applying`; ignores a mismatching non-empty `token`; buffers `(new_key, new_species)` per side; commits when **both** sides have reported. Nothing about the link is mutated before that, so a half-completed trade is never observable.

### 6.4 `_commit_trade` (`state.py:816-859`)

| Step | Cite |
|---|---|
| A side that never reported gets `new_key` = the pre-trade key of the mon it received (`a` ← `b_key`, `b` ← `a_key`), species unchanged | `:688-692` |
| `entry.a, entry.b = entry.b, entry.a` (the MonInfo objects move with the data) | `:698` |
| Old keys popped from `_key_index`; each half's `key` (and `species` if non-zero) patched from the readback | `:699-706` |
| `party_keys`: a drops `a_key`, adds `entry.a.key`; b likewise | `:708-711` |
| `_key_index` re-pointed at the new keys; `_save`; jingle + msgbox both | `:712-722` |
| Settle window armed | `:727` |

### 6.5 What the client MUST NOT do

- **MUST NOT send `key_change` for either traded key.** The server has already re-keyed the link from `trade_done`; a `key_change{old:a_key,new:new_key}` would pop the entry from `_key_index` under the new key and re-index it wrongly. The Gen 3 client handles the swap as a local key migration only (`pending_trade_migration`, `gen3_frlge_client.lua:3405-3419`, comment at `:3406-3409`).
- MUST NOT emit `capture` for the received mon or `party_to_box` for the traded-away mon (`:3412-3413`, `:3435`).
- MUST NOT execute sync commands for the swapped keys queued during the trade (`:3423-3429`).

### 6.6 Watchdog (`state.py:477-503`)

`pending_trade["age"]` increments on **every** `handle_event` call from either player (ticks, ghost_pos included) and resets to 0 on each trade handler that makes progress. When `age > TRADE_WATCHDOG_EVENTS (4000)`: phase `applying` ⇒ `_commit_trade` with fallbacks (the clients will swap anyway since queued commands survive reconnects); any other phase ⇒ the slot is silently freed. At ~4 events/s (two clients ticking) that is roughly 15–20 minutes without ghost traffic; far less with it.

---

## 7. Adapter contract (`server/adapters/base.py`)

`GameRulesAdapter` (state machine) + `GamePresentationAdapter` (display) = `GameAdapter`. Abstract methods MUST be implemented; the rest have defaults.

### 7.1 Rules (`GameRulesAdapter`)

| Member | Signature | Default | Purpose | Used at | Cite |
|---|---|---|---|---|---|
| `game_id` | property → str | abstract | registry key, persisted in `links.json` | `state.py:2971`, `800-819`; `server.py:2495` | `base.py:73-75` |
| `is_gift_area` | `(area_id) -> bool` | abstract | gift/static areas: no `area_enter` state, no `no_catch`, no quarantine; MUST recognise the `gift_` prefix | `state.py:1123`, `1143`, `1778`; `gift_link_area` | `base.py:78-84` |
| `is_fixed_species_gift` | `(area_id) -> bool` | `False` | bypass species/gender/type clauses for forced-species gifts | `state.py:1423`, `1526` | `base.py:86-98` |
| `is_daycare_area` | `(area_id) -> bool` | `False` | daycare eggs are not gifts | `state.py:1145`; `gift_link_area` | `base.py:100-109` |
| `gift_link_area` | `(area_id) -> str` | `area_id` if gift/daycare else `f"gift_{area_id}"` | namespace under which a gift caught in a wild area links | `state.py:1349` | `base.py:111-125` |
| `is_egg_pickup_area` | `(area_id) -> bool` | `startswith("egg_")` | (declared; not called by state.py at this commit) | — | `base.py:127-140` |
| `evo_family` | `(species_id) -> int` | abstract | species clause family key | `state.py:1424-1450`, `1701-1759`, `1818-1862`, `2526-2556` | `base.py:143-148` |
| `gender_from_key` | `(key, species_id) -> "male"\|"female"\|"genderless"` | abstract | gender clause (`genderless` never violates); dashboard gender | `state.py:2560-2561`; `server.py:2892`, `3775` | `base.py:151-157` |
| `species_types` | `(species_id) -> (t1,t2)\|None` | abstract | type clause; type badges | `state.py:2567-2568`; `html_render.py:65` | `base.py:160-165` |
| `is_shiny` | `(key) -> bool` | abstract | shiny clause (bonus mons) | `state.py:1314` (`self.adapter.is_shiny` in `_handle_capture`; the standalone helper at `state.py:107` is legacy, per its own docstring) | `base.py:168-175` |
| `parse_ot_id` | `(key) -> str` | `GameAdapter`: second `:` segment of a 2-part key | identity lock fallback when hello lacks `ot_id` | `state.py:895` | `base.py:178-184`, `550-562` |
| `is_valid_mon_key` | `(key) -> bool` | `GameAdapter`: two hex segments ≤ 8 digits | validation (dashboard APIs) | — | `base.py:187-189`, `564-578` |
| `species_name` | `(species_id) -> str` | abstract | every HUD/msgbox label, logs | pervasive | `base.py:192-197` |
| `type_name` | `(type_id) -> str` | abstract | type clause message, badges | `state.py:2575` | `base.py:200-202` |
| `rival_trainer_ids` | `() -> set[int]` | `set()` | rival-team-swap trigger set | `state.py:2839` | `base.py:204-218` |
| `party_blob_size` | `() -> int` | `0` (= do not cache blobs) | byte length every `blob_hex` MUST decode to; gates trade eligibility and rival swap | `state.py:2760` | `base.py:220-234` |
| `supports_abilities` | `() -> bool` | `True` | hide Ability columns | `server.py:3736` | `base.py:236-246` |
| `status_token` | `(status_cond) -> "SLP"\|"PSN"\|"BRN"\|"FRZ"\|"PAR"\|"TOX"\|""` | `""` | native `link_panel` status field (helper `gb_status_token` for GB layouts) | `server.py:2604`, `4230` | `base.py:248-254`, `516-536` |
| `info_panel_width` | `() -> int` | `0` | 0 = no native panel width concept (Gen 3 fallback: panel on adapter's say-so); ≤20 ⇒ compact rows | `server.py:1798`, `2640-2679` | `base.py:256-264` |
| `supports_info_panel` | `() -> bool` | `False` | veto for `link_panel` | `server.py:1792` | `base.py:266-280` |
| `supports_explode_mode` | `() -> bool` | `False` | `force_explode` instead of `force_faint` | `state.py:2619-2621` | `base.py:282-295` |

### 7.2 Presentation (`GamePresentationAdapter`)

| Member | Signature | Default | Used at | Cite |
|---|---|---|---|---|
| `sprite_html` | `(species_id, form=0) -> str` | abstract | `server.py:1621-1629` → everywhere sprites render | `base.py:350-357` |
| `ability_name` | `(ability_id, species_id=0) -> str` | abstract | `server.py:3390`, `3953` | `base.py:360-366` |
| `ability_description` | `(ability_id) -> str` | abstract | `server.py:3805`, `3954` | `base.py:369-371` |
| `trainer_info` | `(trainer_id) -> (name, class)`; `("","")` if unknown | abstract | `server.py:3053-3056` (tick `trainer_id`) | `base.py:374-380` |
| `item_name` | `(item_id) -> str` | abstract | `server.py:3799`, `3955` | `base.py:383-385` |
| `area_display_name` | `(area_id) -> str` | abstract | dead-zone text `state.py:1876`; panel, dashboard | `base.py:388-390` |
| `to_national_dex` | `(species_id) -> int` | abstract | `sprite_src` default | `base.py:393-395`, `445-446` |
| `gender_symbol` | `(gender) -> str` | abstract | dashboard | `base.py:398-400` |
| `form_sprite_id` | `(species_id) -> int\|None` | abstract | forms | `base.py:403-405` |
| `form_sprite_url` | `(species_id, form=0) -> str\|None` | `None` | Gen 4+ forms | `base.py:407-418` |
| `rom_content_fingerprint` | `(payload) -> str\|None`; MUST raise on malformed | `None` | admission `server.py:1746` | `base.py:420-432` |
| `ingest_rom_content` | `(payload) -> tables\|None`; MUST raise on malformed | `None` | `server.py:1652`; adapter also needs `use_rom_encounters(tables)` for per-player adoption `server.py:1663-1675` | `base.py:434-450` |
| `encounter_table` | `(area_id) -> {method: [ {name, species_id, rate, min_level, max_level} ]}\|None` | `None` | encounter panel `server.py:2244-2266`, `1813+` | `base.py:452-463` |
| `trainers_for_area` / `trainer_party` / `trainer_brief` | see file | `[]` / `[]` / synthesised | Upcoming Trainers panel `server.py:1896+` | `base.py:465-471` |
| `sprite_src` | `(species_id) -> url` | PokeAPI by national dex | encounter panel | `base.py:496-507` |
| `move_name` / `move_data` | `(move_id) -> str` / `-> {name,type_id,type_name,power,accuracy,pp,split}\|None` | `""` / `None` | move tables `server.py:3401`, calc paste | `base.py:509-514` |
| `stat_stage_labels` | `() -> list[str]` (7 slots; `""` blanks a slot) | `["ATK","DEF","SPD","SATK","SDEF","ACC","EVA"]` | `server.py:3870`, `3967` | `base.py:524-532` |
| `mons_per_box` | property → int | `30` | memorial overflow box count `server.py:7966` | `base.py:535-543` |
| `memorial_box_index` | property → int (0-based; `-1` = none) | `-1` | contamination scan, memorial contents | `base.py:546-553` |
| `gym_badge_slugs` | `(rom_type) -> [(pokeapi_id, name)]` | Kanto 1-8 | badges overlay | `base.py:555-573` |

### 7.3 Routing (`server/adapters/__init__.py`)

| Step | Rule | Cite |
|---|---|---|
| `hello.rom_type` → `game_id` via `_ROM_TYPE_TO_GAME_ID` (unknown ⇒ `None` ⇒ adapter unchanged, silently) | `__init__.py:38-67`, `90-95` |
| Adapter switched only while `state.rom_type` is unset; later hellos with a different `rom_type` are logged and ignored | `server.py:2490-2511` |
| `is_rr = rom_type.endswith("_rr")`; `get_adapter(game_id, is_rr=..., rom_type=...)` — adapters MUST accept `**kwargs` | `server.py:2494-2496`, `__init__.py:20-28` |
| `rom_type` persisted; on reload the saved `game_id` re-resolves the adapter with `rom_type` | `state.py:793-819` |
| Human label: `variant_label(rom_type)` (`__init__.py:70-100`); ⚠ `server.py:3720-3734` keeps a second, incomplete `ROM_LABEL` map for the dashboard header | |

---

## 8. Gen 3-isms baked into shared code

Things a non-Gen-3 client/adapter must neutralise on the wire, or that should become adapter hooks.

| # | Where | What | Impact on another generation | Mitigation today |
|---|---|---|---|---|
| 1 | `state.py:718,1177,1186,1259,1332,1364,1385,1409,1463,1539-1540,1578-1579,1878,1884,2623` | `play_sound` ids are Gen 3 SE numbers (25 success, 26 failure, 22 boo, 95 shiny) | meaningless on GB | Gen 1 binds them in the client (`panel.lua SFX_CODE_FOR_GEN3_ID` → mailbox codes 1-3; the ROM owns the per-bank sound ids); Gen 2 has no binding |
| 2 | `state.py:521` | `"OAK: Took you long enough..."` in the trade action-menu text when `overworld_presence` is off (assumes the RR PC trade NPC is Prof. Oak) | wrong speaker on other games | none; client may re-render |
| 3 | `state.py:554`, `642` | `POKeMON` (FR charmap spelling) in msgbox text | cosmetic | route through the client's text sanitiser |
| 4 | `state.py:1173,1327-1328` | `"Pokémon"` (non-ASCII é) fallback when `species_id` is 0 | HUD mangling on BizHawk | always send `species_id` |
| 5 | `html_render.py:150-166` | `status_icon_html` decodes `status_cond` with the Gen 3 `status1` layout (dashboard); only `link_panel` uses `adapter.status_token` | a client whose RAM layout differs MUST send `status_cond` re-encoded to: SLP = bits 0-2 counter, PSN 0x08, BRN 0x10, FRZ 0x20, PAR 0x40, TOX 0x80 (GB layout already matches for SLP/PSN/BRN/FRZ/PAR, `base.py:516-527`) | encode on the wire |
| 6 | `html_render.py:169-196` | `stat_stages` are 7 slots, raw 0-12 with **6 = neutral** | Gen 1 stat mods are 1-13 with 7 neutral; client MUST subtract 1 and blank/omit slots per `adapter.stat_stage_labels()` | encode on the wire; adapter blanks labels |
| 7 | `server.py:3392-3410` | PP-Up encoding accepts `pp_bonuses` (packed u8) or `pp_ups` (list) | Gen 1 stores PP-Ups in the PP byte's top 2 bits — client must split into `pp` and `pp_ups` | send `pp_ups` |
| 8 | `state.py:892-895`, `base.py:610-622` | identity fallback parses OT from `party[0].key` with the 2-part default | a 3-part key MUST override `parse_ot_id`; better: send `ot_id` in hello | Gen 1 adapter overrides `gen1_rby.py:318-319` |
| 9 | `state.py:2740-2784` | blob validation by `party_blob_size()` | default 0 disables trade + rival swap entirely | adapter override (Gen 1: 66) |
| 10 | `server.py:2629` vs `2647-2652` | wide `link_panel` "Badges" row reads the `status` event count; compact rows popcount the hello/tick bitmask | a client without `status` shows 0/8 in the wide layout | send `status{badges:count}` or use width ≤ 20 |
| 11 | `server.py:1798` | absent `panel` capability ⇒ panel sent iff `info_panel_width()==0` | a Gen with width > 0 gets **no** panel unless hello carries `panel:true` | send `panel`/`panel_abi` |
| 12 | `server.py:3720-3734` | dashboard `ROM_LABEL` lacks Gen 2/5 and AP-Gen 1 labels | header falls back to raw `rom_type` | use `variant_label` (`adapters/__init__.py:98-100`) |
| 13 | `state.py:1590-1591`, `2131`, `2318-2320` | party capacity hardcoded 6 | correct for every supported generation | — |
| 14 | `state.py` `MonInfo.species` vs wire `species_id`; `_build_status_dict` links expose `a_species` while `_lp_mon_cell` looks up `lnk["a_species_id"]` (`server.py:2407`) | server-internal naming drift; the fallback never hits | none needed on the wire: **always** `species_id` |
| 15 | `state.py:2559-2564` | gender clause via `gender_from_key`; a `genderless` result never violates | Gen 1 adapter returns `genderless` — clause inert, no wire impact | — |
| 16 | `state.py:1162-1219` | shiny clause via `adapter.is_shiny(key)` | Gen 1 adapter returns `False` — inert | — |
| 17 | `gen3_frlge_client.lua:835`, `953` | client hardcodes 100-byte blobs | client-side only; a new client checks its own adapter size | — |
| 18 | `server.py:2494` | `is_rr` inferred from `rom_type` suffix `_rr` | none for other gens | — |
| 19 | `state.py:2440-2445` | `key_change.new_species`/`new_nickname` exist **for** non-Gen-3 evolution (key embeds species) | Gen 1 MUST send `key_change{old_key,new_key,new_species,new_nickname?,reason:"evolution"}` on evolution because its key changes; Gen 3 never does (key is PID:OT) | documented hook |
| 20 | `server.py:3057-3064` | `opponent_name`/`opponent_class` on tick accepted only when `adapter.trainer_info` returns no class | documented hook for generations without a trainer table | send both on trainer battles |

---

## 9. Conformance checklist

Assertions for `tests/unit/test_protocol_conformance.py`: a lupa-driven fake server (mock socket, as in `tests/unit/test_connector_fragmentation.py`) drives the client and inspects the lines it writes and the RAM writes it performs. Each item names the cite that makes it normative.

**Transport**

1. Every outbound line is a single JSON object terminated by exactly one `\n`, with `event:str`, `player ∈ {"a","b"}`, `seq:int` (`gen3:1052`, `connector.lua:196`).
2. `seq` starts at 1 on script load and increases by exactly 1 per event, across TCP reconnects (`gen3:1044,1052`; `server.py:1558-1565`).
3. The client sends **nothing** while `C.connected()` is false and does not buffer events for later (`gen3:1048-1051`).
4. On connect (and every reconnect) the first line is `hello` (`gen3:1917-1945`).
5. The client tolerates a reply of `{"commands":[{"cmd":"noop"}]}` for any event and a reply carrying commands it does not know (logs, does not crash) (`gen3:1037-1038`).
6. A server line > 4 MiB is discarded and the next line still parses (`connector.lua:242-247`).
7. Field order in a reply is irrelevant to the client.

**hello**

8. `hello` carries `rom_type` ∈ `_ROM_TYPE_TO_GAME_ID` keys, `party:list`, `has_pokeballs:bool`, `trainer_name:str`, `badges:int` bitmask (`gen3:1939-1945`; `__init__.py:38-67`).
9. Every `party` entry has `key`, `hp`, `maxHP`, `level`, `slot`, `species_id`, `nickname`, `blob_hex` with `len == 2*party_blob_size()` (`state.py:952`, `2768-2769`).
10. A new client SHOULD send `ot_id`; if it does not, `adapter.parse_ot_id(party[0].key)` must yield the save's trainer id (`state.py:892-895`).
11. `hello` omits `party` contents (sends `[]`) when the save is not loaded or the party is borrowed (`gen3:1930-1932`).
12. After a `hud_show` whose text starts with `[x] WRONG SAVE`, the client renders it (accepting `color`/`duration` **or** `r,g,b,frames`) and does not crash (`state.py:401`).
13. The client applies `resolved_areas` (including an empty list) and sets its seeded flag; `config` booleans are applied (`gen3:989-1020`).

**tick / snapshots**

14. `tick` is periodic (Gen 3: every 30 frames) and carries `has_pokeballs`, `area_id`, `loc_name`, `in_battle`, `badges`, `trainer_name`; `party` when the save is valid and not borrowed; `enemy_party` (`[]` outside battle); `pc_boxes` when the party diff is trustworthy (`gen3:4126-4372`).
15. The first tick after a wild battle starts has `in_battle=true`, `is_trainer_battle=false`, non-empty `area_id`, and `enemy_party[0].species_id > 0` (`server.py`: the wild-battle-start dupes block inside `_dispatch`, gated on `_enc_species` — `:2129-2148` at `99c70d9c`; the block moved from `:3074-3093`, which is why this cites the function).
16. In a trainer battle the tick has `is_trainer_battle=true` and `trainer_id>0`, or `opponent_name`/`opponent_class` (`server.py`: `_dispatch`'s tick branch — `is_trainer_battle` at `:2102-2103`, the `trainer_id` → `adapter.trainer_info` resolution that fills `opponent_name`/`opponent_class` at `:2104-2121`; the range moved from `:3049-3064`, which is why this cites the function).
17. `status_cond` uses the §8-5 bit layout; `stat_stages` is a 7-list with 6 = neutral present only for `active` mons; `pp_ups` or `pp_bonuses` present when `moves` are (`html_render.py:150-196`, `server.py:3392-3410`).
18. `pc_boxes` entries have 0-based `box`/`slot`, `key`, `species_id`, `nickname`; the memorial box index used by the client equals `adapter.memorial_box_index` (`server.py`: `_memorial_box_indices`, `:4544-4568`).
19. `safe` is sent on the first overworld frame after a battle (`gen3:4120-4124`).

**Encounter events**

20. `area_enter{area_id, loc_name}` fires on map change; `area_id` is a known adapter id or `""` (`gen3:2718-2722`).
21. `capture` has non-empty `key` and `area_id`, `species_id>0`, `level>0`; `in_box=true` iff the mon landed in the PC; `gift=true` for out-of-battle acquisitions; `is_egg` present (`gen3:3589-3593`, `3869-3873`, `3970-3973`).
22. Before `has_pokeballs`, an out-of-battle capture uses `area_id="intro"` (`gen3:3620-3621`).
23. `no_catch{area_id, species_id, level}` fires once per unresolved wild battle with no catch, never for gift areas, never twice for the same area, and never after a `capture` in that battle (`gen3:4085-4106`).
24. `unresolve_area{area_id}` re-arms `no_catch`/encounter HUD for that area (`gen3:1021-1023`).
25. `faint{key}` fires once per HP >0→0 transition of a party mon and **not** for HP the client zeroed itself on `force_faint`/`force_explode` (`gen3:3664-3686`).
26. `whiteout` fires exactly once when every previously-alive party mon is at 0 HP after a real faint (`gen3:3809-3815`).

**Party/box sync**

27. `party_to_box{key, stats}` fires for a key that left the party outside battle with HP>0 and was **not** moved by the client on server command; `box_to_party{key}` for a known key that re-entered (`gen3:3711`, `3830`, `3849`).
28. On `box_mon{key}` the client deposits when safe, sends `stats_cache{key,stats}` first, refuses when the key is the last party mon, and sends `box_mon_failed{key,reason}` when the deposit did not happen (`gen3:1601-1668`; `state.py:332-345`).
29. On `party_mon{key,stats?}` the client withdraws when safe and replies with exactly one of `sync_retrieve_done{key}` / `sync_retrieve_failed{key}`; an already-present mon is acked as done (`gen3:1670-1748`).
30. On `memorialize{key}` the client moves the mon to the memorial box when safe and replies with exactly one of `memorialize_done{key,box}` / `memorialize_failed{key,reason}`; it never empties the party unless `game_over` was received (`gen3:1781-1832`, `2645-2650`).
31. Deferred commands execute FIFO, at most one per frame, only in the client's safe state; opposing `box_mon`/`party_mon` for one key cancel each other; duplicate `memorialize` is deduped (`gen3:857-896`, `2634-2716`).
32. Commands referencing an unknown key are no-ops that do not crash the client (`gen3:1660-1667`).

**Deaths**

33. `force_faint{key}` on a benched/out-of-battle mon writes HP=0 within the same frame; on the active battler it is applied at switch-out or battle end; neither path emits `faint` for that key (`gen3:741-802`, `2544-2583`) — this is the reference (old) client. **On the new Gen 3 client, FR/LG singles apply the active-battler write immediately via mechanism P+H instead of holding for switch-out/battle end** (owner rulings 15-16, `docs/gen3/G4_request_draft.md` §6, 2026-09-23/24; doubles keep the hold; RR gets parity at G5, ruling 19 for Explode).
34. `force_explode` is handled at least as `force_faint` (a client for a generation whose adapter returns `supports_explode_mode()==False` never receives it) (`state.py:2926`).
35. `game_over` sets a persistent HUD state and does not stop ticks (`gen3:1024-1028`).

**Keys**

36. Keys are stable across box↔party moves, reconnects, and nickname/held-item changes (`state.py:2406-2419`).
37. A same-mon key change (nature change, evolution on generations whose key embeds species) is reported as `key_change{old_key,new_key,new_species?,new_nickname?,reason}` and produces no `capture`/`party_to_box`/`box_to_party` for either key (`gen3:3438-3557`).
38. Both halves of any link the client can produce have distinct keys (`state.py:2520-2522`).
38a. Every `key_change` is answered in the same reply by exactly one `key_change_ack{old_key,new_key,migrated}` or `key_change_rejected{old_key,new_key,reason}`; a client that aliases old→new until acknowledged resolves the alias on either (`_handle_key_change`).
38b. A `key_change` re-sent after a reconnect is idempotent (`migrated:false`, nothing mutated); a rejected one mutates nothing on the server, including the presentation caches (`server.py` migrates them only after acceptance).

**Prompts and trade**

39. `show_choices` → one `menu_result{token,choice}` where `choice` is the 0-based index or 127; `show_menu` → one `menu_result{token,choice}` with 1 = yes, 0 = no; `choose_mon` → one `mon_chosen{token,slot}` 0-5 or 7; the token is echoed verbatim; the cancel code is sent immediately when the prompt cannot be shown (`gen3:901-946`, `2193-2209`).
40. Two prompts are never in flight at once; a second `trade_request` is not sent while a prompt or trade is pending (`gen3:2167`, `2187`).
41. `apply_trade{slot,blob_hex,old_key,token}` results in exactly one `trade_done{token,slot,new_key,new_species}` where `new_key` is read back from the slot that held `old_key` (`gen3:657-670`, `678-695`).
42. After a trade the client emits **no** `key_change`, `capture`, or `party_to_box` for the two traded keys, and discards queued sync commands for them (`gen3:3405-3429`).
43. During `apply_trade` the client does not execute `box_mon`/`party_mon`/`memorialize` (`gen3:2634`).

**Misc**

44. `trainer_battle_start{trainer_id:int>0}` fires once per trainer battle, never for wild or borrowed battles (`gen3:2317-2343`).
45. `replace_rival_team` always produces one `rival_team_replaced{trainer_id, species_ids, error?}` (`gen3:806-854`, `2434-2453`).
45a. `replace_rival_team` echoes the `session` nonce and `battle_id` counter of the battle it belongs to (when the client announced an identity), and the new Gen 3 client refuses a missing, malformed, other-session or mismatched pair with `rival_team_replaced{error:"stale_battle_id"}`, writing nothing (`state.py:3052-3110`, `lua/gen3/client.lua:860-890`). A manual inject with no stored identity is refused server-side **for a client that declared `battle_identity: true` in its hello**; a client that never declared it (Gen 1, Gen 2, the old Gen 3 RR client) keeps the pre-card behaviour and gets a command with no identity fields. Old clients that never send an identity keep today's behaviour throughout.
46. `status{badges:int 0-8}` is a count, not a bitmask (`state.py:445-453`).
47. All on-screen text from `msgbox`/`gui_prompt`/`hud_show` passes through the client's text sanitiser (non-ASCII in server strings, §8-3/4).

---

## Appendix A — Disagreements and ambiguities

| # | Topic | Server | Gen 3 client | Resolution for new clients |
|---|---|---|---|---|
| A1 | WRONG SAVE toast fields | `hud_show{color:[r,g,b], duration}` `state.py:910-915` | parser reads only `r,g,b,frames` `gen3:299-302` → white/300 | accept both spellings |
| A2 | `box_mon_failed` | handled, restores party model `state.py:332-345` | never sent; deposit failure only logged `gen3:1653-1656` | MUST send on failure |
| A3 | `safe` payload | `safe` treated like `tick` (may carry `party`) `state.py:354-374`; blobs doc claims "hello / tick / safe" `state.py:2743` | `{event:"safe"}` only `gen3:4123` | fields optional |
| A4 | `ot_id` in hello | preferred `state.py:892` | never sent → OT parsed from `party[0].key` | send `ot_id` |
| A5 | `panel` capability | read at hello `server.py:2483-2485`; absent ⇒ `info_panel_width()==0` | never sent (works because Gen 3 width is 0) | any gen with width > 0 MUST send `panel:true` to get `link_panel` |
| A6 | `pending_sync` command | never emitted | handled `gen3:855-856` | dead; ignore |
| A7 | `party_mon.stats.pp1..pp4` | echoed verbatim from `stats_cache` | client sends them (`gen3:1624-1628`) but its parser drops them (`gen3:264-275`) | optional; a client may restore PP from them |
| A8 | `peer_interact` | handled `state.py:421-428` | not sent (replaced by `trade_request`) | legacy; not required |
| A9 | `ghost_pos.x/y` units | comment says tile coords `state.py:399` | comment says world pixels `gen3:2153`; parser comment says tiles `gen3:285` | opaque ints relayed unchanged; patch-defined |
| A10 | ~~`seq` restart heuristic~~ **RETIRED 2026-09-17 (`0629736`)** | the heuristic (`restart recognised only if seq<=1 and last>10`) is deleted; the counter is a per-connection local and a connection is ignored until it says hello — `server/server.py:1095-1101`, `server.py:1230-1241`, `server.py:1359-1594` | client restarts at 1 regardless — which is now simply correct | **no divergence left.** The old resolution ("a harness must not reuse a server across restarts with ≤10 prior events, or must send ≥ `last` events first") described a constraint that no longer exists; a harness may reuse a server across restarts freely. Row kept, not deleted, so the history reads straight |
| A11 | Trade text | `"OAK: ..."`, `POKeMON` `state.py:521,554,642` | rendered verbatim | cosmetic; not generation-neutral |
| A12 | `link_panel` Badges row | wide layout: `status` count `server.py:2629`; compact: bitmask popcount `server.py:2652` | Gen 3 sends `status` | generation-dependent |
| A13 | Badge field semantics | `hello/tick.badges` bitmask (SLinkServer) vs `status.badges` count (SoulLinkState) | both sent correctly | do not confuse them |
| A14 | Tick interval | comment "every 60 frames" `gen3:26` | `TICK_INTERVAL = 30` `gen3:1477` | 30 frames is the reference behaviour |
| A15 | Oversize inbound line | server drops it **without** a reply `server.py:2420-2435` | client's `pending_labels` FIFO would then be off by one (cosmetic logging only) | never send > 4 MiB |
| A16 | `_lp_mon_cell` link fallback | reads `lnk["a_species_id"]` `server.py:3774` while links dict has `a_species` `server.py:3522` | — | server-internal; harmless |
| A18 | `key_change` acknowledgement | `key_change_ack` / `key_change_rejected` appended to the sender's reply (§3.2, §5) | not handled (unknown commands are ignored, §1.2) — Gen 3's local migration is unconditional, so a rejection leaves the client and server disagreeing on the key until the pair is retired | a new client keeps an old→new alias until acknowledged; Gen 3's key never collides in practice (PID:OT), so the rejection path is a Gen 1 / pureRGB concern |
| A19 | Empty lists on the wire | reads `enemy_party` / `pc_boxes` with `or []` and iterates, so an empty object is folded silently | the hand JSON encoder (`gen3:204-240`) emits `{}` for an empty Lua table, so every out-of-battle `tick` carries `"enemy_party": {}` and `"pc_boxes": {}` (conformance items 1/14; characterized 2026-09-21 on the six RR duo transcripts, `tests/fixtures/gen3/wire/`) | a new client binds `lua/json_codec.lua` and always sends `[]` for an empty list |
| A17 | Capture quarantine count | uses `party_size` at event time (`state.py:1495`), which may already include the new mon if a tick preceded the capture | client sends capture before the next tick in practice | send `capture` promptly, before the next `tick` |
