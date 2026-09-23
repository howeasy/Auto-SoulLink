# P4 contract map: Gen 1 production contract → Gen 3 FRLG client (card C4-0b)

Research only, HEAD `10cd25f9`. Every claim cites `file:line` at that HEAD. Scope: the
interfaces P4 workers code against. The OLD Gen 3 client's behaviour is inventoried by the
parallel Codex card and is not repeated here. Section 1 summarizes Gen 1, section 2 covers
Gen 3 today, section 3 proposes the interfaces, section 4 covers the harness and release
side, and section 5 is the card cut.

---

## 1. Gen 1 production contract

### 1.1 Composition root: `lua/gen1/entry.lua`

| Piece | Where | Contract |
|---|---|---|
| `Entry.PACKS`, `Entry.PACK_FILES` | `entry.lua:44-54`, `:58-83` | The only place a foundation is named. PACK_FILES holds literal paths because the release manifest is derived from literals (`:55-57`). |
| `Entry.admit(args)` | `:229-266` | sha1 (with a Lua rehash if `indatabase`) → anchors (`:176-219`) → nil + reason. Returns `{pack,title,kind,rom_type,rom_sha1,rehashed,admitted_by}`. |
| `Entry.build(deps)` | `:300-380` | deps = `root, io, net, hud, pack, title, kind, player, rom_sha1, log` (`:8-19`). Loads reads/signals/writes/boxes/rom/trade/panel/safety/client (`:304-308`), wraps io (`bank_safe_io`, `:274-292`), builds `reads_io` (`:335-338`), and builds `box_io` whose cart door re-checks `writes.armed` and logs the write (`:343-358`). Returns `client, parts{profile,sites,reads,writes,boxes,rom,json,panel,box_io,pack}` (`:369-379`). |
| `Entry.bizhawk_deps()` | `:403-421` | The one BizHawk-global adapter: read_u8/read_range/write_u8 with domain, on_bus_exec, unregister, framecount, register, set_register, domains, saveram. |

### 1.2 Bootstrap: `lua/gen1/run.lua`
Self-locates ROOT (`run.lua:9-12`). Reads SLINK_HOST/PORT/PLAYER from globals or env (`:18-20`). Detects the header family (`:24-28`), admits (`:30-36`), and falls back to the named family (`:37-54`). Then `H.init{160,144}` and `C.init` (`:57-58`), `Entry.build` (`:60-64`), `pcall(client:start)`, which refuses by name on failure (`:65-69`). Sets the global `SLINK_GEN1_CLIENT` for gates (`:75`). `onframeend` wraps `frame_end` in a pcall and calls `H.render` (`:77-81`). `onexit` calls `stop` (`:82`).

### 1.3 Client: `lua/gen1/client.lua` (1889 lines; a state machine over injected parts)
- **Parts** are all injected (`client.lua:4-12`, `:135-139`). Tunables: `TICK_INTERVAL=30, VALIDATE_EVERY=60, MAX_INVALID=5` (`:19`).
- **Outbound**: `send(event, fields)` drops the event when disconnected, stamps `event/player/seq`, and JSON-encodes it (`:171-182`).
- **Hello gating** (`frame_end`, `:1804-1826`): a disconnect resets `hello_sent` (`:1808-1811`). Hello requires `game_is_live()` (party readable and not pre-game, `:310-315`) and `in_battle ~= 0 or safety.check(...)`. The version hold is pureRGB-only (`:1816-1821`). Payload: `send_hello` (`:1512-1556`).
- **validate/pause** (`:317-358`, every 60 frames at `:1827`): 5 invalid reads pause writes but NEVER drop queues (`:348-355`). A WRAM clear (player_id 0) resets hello, pending_change, panel and every alias (`:334-347`).
- **Commands** (`handle_command`, `:480-596`): `force_faint/explode` resolve through `find_party_slot`. If the party is unreadable, the command goes to the deferred queue. If in battle, it goes to `pending_battle_writes`. Otherwise it is deferred (`:483-504`). `box_mon/party_mon/memorialize` are always deferred (`:505-508`). The generic handlers (`msgbox, hud_show, play_sound, resolved_areas, unresolve_area, key_change_ack/_rejected, pending_keys, config, game_over, rebuild_*`, the cancel sentinels, `ghost_pos`, unknown) are at `:510-595`. Cancel sentinels: `ack_cancel` (`:361-365`).
- **Deferred FIFO** (`run_deferred`, `:717-822`): one command per frame, and only when `writes_enabled ∧ connected ∧ safety.check` (`:718-720`). Each command runs inside `pcall` with `writes:arm("overworld")` … `disarm` (`:734-820`). Keyed replies: `box_mon_failed` (`:766`), `sync_retrieve_done/_failed` (`:780, :797`), `memorialize_done/_failed` (`:803, :814`). Retry-at-tail happens only for `"party full"` (with a budget, `:783-796`) and `"last party mon"` (`:808-812`). `"last party mon"` after `game_over` is dropped (`:806-807`). `stats_cache` is sent **before** the deposit (`:761`). Gen 3 PLAN R9 wants it after a confirmed deposit (`PLAN.md:57`).
- **Keyed identity / key_change alias** (D-13): `find_party_slot` refuses ambiguity (`:423-440`). `observe_alias` latches `ambiguous`/`lost` (`:394-407`). `alias_departure` is at `:412-416`. `key_change_ack` clears the alias (`:526-532`). `key_change_rejected` turns it into a `retired_alias` (`:533-548`). Every readable frame observes all aliases (`:1852-1858`).
- **Reducer** (`on_signal`, `:910-1250`) maps signal kinds to events: `trainer_battle_start` (`:930`), `no_catch` (`:998`), `faint`/`whiteout` via `emit_faint`/`announce_whiteout` (`:890-908`, `:1010-1017`), acquisition through `pending_change` and `settle_pending_change` (`:1022-1053`, `:1253+`), `party_to_box`/`box_to_party` (`:1069, :1076`), `key_change` (`:1187, :1233`), and `save_witness`, which calls `io.saveram` (`:1244-1245`). Signals are drained under a per-signal pcall (`:1828-1831`). A signal failure latches a HUD banner (`:1836-1845`).
- **tick/safe**: `send_tick` every 30 frames while connected and hello'd (`:1859`, body `:1558-1592`). `safe` is sent once when a battle end is followed by a readable not-in-battle frame (`:1860-1863`, set at `:1009`).
- **Inbound loop**: `net.receive` → `json.decode` → a per-command pcall (`:1864-1876`). Then `trade_tick` and `run_deferred` (`:1877-1879`).
- **HUD** calls go through `hud.show/prompt/set_game_over/set_rebuilding/clear_rebuilding/nuzlocke_start` only (`:512-567`, `:751`, `:1575`). There is no direct `gui.*`.
- **Gen 1-specific, not reusable**: `RIVAL_*` windows and `replace_rival_team` (`:19-86`, `:598-714`), Tower/Silph/demo battles (`:97-108`), `wire_stages` (`:129-133`), `party_from_snapshot` (`:858-885`), APEX/transform (`:1436-1509`), the trade FSM (`:1594-1765`), the panel/SFX codes (`:451-478`), and the pureRGB version hold.

### 1.4 How writes and boxes plug in
- `writes.lua`: `arm(reason, allow?)`/`disarm` (`writes.lua:64-68`). `write_bytes` asserts the window is armed, checks the whole range against allow, validates every byte, logs `{addr,n,why,frame}` (`:70-86`). Operation methods assert their reason, e.g. `faint_active_battler` requires `battle_loop_head` (`:100-105`). `W.active_faint_guard` is pure (`:39-49`).
- `boxes.lua`: `B.new(profile, reads, io)` asserts an armed byte io: `read_range, read_cart, write_bytes, write_cart_bytes` (`boxes.lua:44-50`). Client-facing aliases: `deposit(key, hint)`, `withdraw(key, stats, base, nick)`, and `memorialize(key, hint)`, which accepts both dot and colon calls (`:471-473`, `:534-537`). Each returns `true` or `nil, reason`. The reason strings `"last party mon"` (`:328`, `:490`) and `"party full"` (`:444`) are the FIFO's retry keys.

### 1.5 What should be SHARED (the test: "can Gen 3 bind it unchanged?")

**Constraint**: `lua/gen1/*` is owned by the pureRGB session (memory note), so P4 must not edit it. Shared code is therefore lifted into a new `lua/core/`. Gen 3 binds it first. Gen 1 re-binds in a later card owned by pureRGB, with the Gen 1 lupa suite and the `gen1_new` lanes as the falsifier. Until then the duplication is recorded, not hidden.

| Candidate | Verdict | Argument |
|---|---|---|
| Identity aliases (`client.lua:367-440`, `:526-548`, `:1852-1858`) | **SHARE**: `lua/core/identity.lua` | Needs only `key(m)`, `m.slot`, `m.nickname_bytes` and `m.moves`. Gen 3 reads supply all four: `reads.lua:269`, `:333`, `:242`, `:198-204`. It binds unchanged. |
| Deferred FIFO policy (`:717-822`) | **SHARE**: `lua/core/deferred.lua` | The queue, gate, pcall/disarm, keyed replies and tail-retry are generation-neutral once the executors are injected (§3.3). One deliberate delta: `stats_cache` is snapshotted before the deposit and **sent after** it is confirmed (`PLAN.md:57`, §5.4 `:131`). Gen 1 adopts that when it re-binds. |
| Session shell: send/seq (`:171-182`), receive loop (`:1864-1876`), generic commands (`:510-595` minus trade/panel/rival), `ack_cancel` (`:361-365`), validate/pause (`:317-358`), hello gate (`:1804-1826`), tick/safe cadence (`:1859-1863`), signal drain + failure banner (`:1828-1845`) | **SHARE**: `lua/core/session.lua` | Every generation-specific read goes through the driver table (§3.2). Gen 3's `vanilla FRLG: cancel sentinels, no trade` rule (`PLAN.md:139`) is exactly Gen 1's `ack_cancel`. |
| `signals.lua` | **NO** | Gen 3 already ships its own. Its identity test is the callback address, not `PC`/bank (`gen3/signals.lua:92-100` vs `gen1/signals.lua:339-369`). Only `NULL_GUID`/`hex_of` are duplicated, and those are trivial. |
| `writes.lua` | **NO** | Gen 3's contract differs: a per-frame window, a required allow predicate, and safety revalidated on every write (`gen3/writes.lua:15-45`). |
| `boxes.lua`, `reads.lua`, `rom.lua`, `Entry.admit`/`sha1` | **NO** | Format-specific. Gen 3 deliberately has no Lua rehash (`gen3/entry.lua:30-32`). |
| `run.lua` frame/exit guard | **NO** (about 6 lines) | Copying it is cheaper than adding a seam. |

---

## 2. Gen 3 today (observer mode) and what production must add

| Module | Provides | Cite |
|---|---|---|
| `entry.lua` | `PACKS{gen3_frlg,gen3_rr}` with `rom_type` and `header_code` (`:54-62`). `PACK_FILES` covers profile/sites/checkpoint only (`:66-77`). `BASE_KIND{named=clean}` (`:84`). `admission_table` indexes the sha1 and md5 of every artifact of **every** pack (`:101-115`). `anchor_matches` (`:133-149`). `admit` goes hash → anchors → `header_code` named (`:158-187`). `header_code`/`header_title` (`:191-204`). `build` asserts `mode == "observer"` (`:213-214`), loads safety **only if the file exists** (`:245-246`), and returns `nil, parts{pack,title,kind,artifact_kind,rom_type,rom_hash,profile,sites,write_checkpoint,reads,signals,safety(module),json,mode,log}` (`:248-255`). | entry.lua |
| `reads.lua` | `R.new(profile, io, pointers)` (`:170`). `decode_name` (`:184`), `decode_party_mon`/`decode_box_mon` (`:264-265`), `key` (`:269`), `deref` (`:283-300`), `read_sb1/read_sb2/read_storage` (`:303-307`), `party_base` (`:309-320`), `read_party` (`:322-337`), `read_box(index)` (`:343-381`). Statics: `R.charmap` (`:75`), `R.secure_checksum` (`:130`), `R.expand_compressed_mon` (`:138`), `R.callable` (`:162`). | reads.lua |
| `signals.lua` | `S.new(profile, sites, io, ev, on_fire)` (`:68`). Refuses at load if the ROM bytes differ (`:79-90`). Rejects callback-address mismatches (`:97-100`). Bounded queue (`:107-110`). Rolls back registration on failure (`:130-147`). `drain/status/close` (`:150-166`). `S.KINDS` is **empty**, so every point is raw registers (`:53-63`). | signals.lua |
| `writes.lua` | `W.new{safety, frame, io, log}` (`:10`). Reasons are `overworld, battle_faint, battle_commit, native, memorial_rename` (`:4-5`). `arm(reason, allow)` **requires** allow and calls `safety:snapshot()` plus `safety:check(snap, reason)` (`:15-25`). `write_bytes` re-checks the frame and allow, re-validates safety, and logs (`:26-45`). `write_u16/u32` are little-endian (`:46-55`). | writes.lua |
| `safety.lua` | `S.new(checkpoint_pack, deps, kind)` (`:12`). deps = `io.read_u8/read_u16_le/read_u32_le(addr, domain)` (`:14-19`), `regs()` (`:75`), `native_idle()` (`:94`). `snapshot()` covers the pointer triple (`:33-37`). `check(snapshot)` evaluates every clause and **ignores the reason** (`:42-107`). | safety.lua |
| `shadow_run.lua` | The BizHawk io/ev adapters to copy: `build_io` (`:58-85`), `build_ev` (hook-name prefix, owns its ids, `:92-119`), and admit-then-build (`:208-268`). | shadow_run.lua |

**Production mode must add:**
1. **Three io shapes from one deps.** reads and signals take domain-less `read_u8/u16/u32, read_bytes, rom_read, framecount, register`. safety takes `read_*_le(addr, domain)` with a `"ROM"` domain for anchors (`safety.lua:52`). writes takes `io.write_u8(addr, v, "System Bus")` (`writes.lua:40`). `Entry.build` adapts them; §3.1 has the code.
2. **A reason-aware write policy.** `safety:check` is overworld-only, so `arm("battle_faint")` in battle always refuses. The `gen3_frlg` pack has no battle-loop site (sites list: `data/games/gen3_frlg/engine_signals.json`, 21 kinds, none mid-battle). **P4 default**: every `force_faint/explode` is deferred to the overworld checkpoint, and the in-battle ones land after `battle_end`. This is recorded as a limit. The alternative (a new battle site plus a re-pin) is a G3-scope change. **Decision fork for the coordinator.**
3. **Reads the wire needs and reads.lua lacks**: OT id and name (SB2), badges (SB1 flags), bag/ball count (the SB1 ball pocket XOR the SB2 key), map group/num (SB1 location), battle state (in_battle/type/opponent/enemy party), and optionally stat stages. The profile already carries `SB1_BALL_POCKET_*`, `SB1_FLAGS_OFFSET`, `SB2_ENC_KEY_OFFSET`, `BATTLE_TYPE_ADDR`, `TRAINER_OPPONENT_ADDR` and `ENEMY_*`. It lacks trainer-id/name, location and badge-flag offsets. Those go through `tools/gen_gen3_profile.py` plus the PYDEC twin (`tools/gen3_reads_pydec.py`, `tests/unit/test_gen3_reads_pydec.py`).
4. **Area ids**: `gen3_frlg` ships no area map. The server-side table is `data/games/gen3_frlge/area_map.json`, keyed `"group:num"` (`area_map.json:1-5`). Bind it as a literal `PACK_FILES.gen3_frlg.area_map` so the manifest ships it. Today only the `.lua` area tables ship (`make_release.py:156-159`).
5. **Semantic reducer**: raw register points only (`signals.lua:53-63`). Signal meanings are in `docs/gen3/research/site_capture_points.md`. The Python reference vocabulary and folding (e.g. `pc_deposit` → `pc_move deposit`, begin/end pairing) are in `tools/gen3_shadow_diff.py:26-51`, `:177-200`. The client reducer must match that vocabulary. The G3 carried-forward OPEN kinds (`evolve_species_store`, `trade_done`, `poison_faint`; `G3_request_draft.md:72-74`) must be implemented but cannot be claimed PHYSICAL.
6. `tests/unit/test_gen3_entry.py:291` (`test_build_refuses_a_mode_that_is_not_built_yet`) must flip when production mode lands.

---

## 3. Proposed P4 interfaces

### 3.1 `Entry.build(deps)` production mode (in `lua/gen3/entry.lua`)
```lua
-- deps: root, mode="production", io, ev, net, hud, pack, title, kind, player, log
--   io = { read_u8, read_u16, read_u32, read_bytes, rom_read, framecount, register,
--          write_u8(addr, v) , saveram? }          -- the documented shape + one write sink
Entry.PACK_FILES.gen3_frlg.area_map = "data/games/gen3_frlge/area_map.json"
Entry.ROUTED = { gen3_frlg = true }                   -- P5 adds gen3_rr; read by slink.lua
function Entry.build(deps) -> client, parts            -- parts adds writes, boxes, safety(instance)
  -- safety instance:
  local safety = Safety.new(write_checkpoint, {
      io = { read_u8 = function(a, d) return d == "ROM" and io.rom_read(a, 1)[1] or io.read_u8(a) end,
             read_u16_le = function(a) return io.read_u16(a) end,
             read_u32_le = function(a) return io.read_u32(a) end },
      regs = function() return { R15 = io.register("R15"), CPSR = io.register("CPSR") } end,
      native_idle = function() return true end },     -- gen3_frlg has no native surface
      artifact_kind)
  -- write policy: overworld only on gen3_frlg in P4 (see §2 item 2)
  local policy = { snapshot = function() return safety:snapshot() end,
                   check = function(_, snap, reason)
                       if reason == "overworld" then return safety:check(snap) end
                       return false, "no " .. reason .. " predicate on " .. pack end }
  local writes = Writes.new{ safety = policy, frame = io.framecount,
                             io = { write_u8 = function(a, v) return io.write_u8(a, v) end }, log = deps.log }
  local boxes  = Boxes.new(profile, reads, { read_bytes = io.read_bytes, rom_read = io.rom_read, writes = writes })
  local client = Client.new{ reads, signals_mod = Signals, writes, boxes, safety, net, hud, json, io, ev,
                             profile, sites, area_map, player, rom_type, rom_sha1 = artifact.rom_sha1,
                             foundation = pack, artifact_kind = kind, log }
```
`mode = "observer"` stays byte-for-byte as it is today (the shadow lane depends on it). `lua/gen3/` still names no BizHawk global. The adapter lives in `run.lua`.

### 3.2 `lua/core/session.lua` plus the Gen 3 driver in `lua/gen3/client.lua`
```lua
-- lua/core/session.lua
local Session = { TICK_INTERVAL = 30, VALIDATE_EVERY = 60, MAX_INVALID = 5 }
function Session.new(p) -> self   -- p: net, json, hud, log, tag, player, game, identity, deferred
self.send(event, fields) -> bool          -- seq/player stamping, drop when disconnected
self:validate() -> ok, why                 -- pause-not-drop; game.save_cleared() -> reset hello+aliases
self:handle_command(cmd)                   -- generic set, then game.commands[cmd.cmd], then force_* routing
self:start() ; self:frame_end() ; self:stop()
-- game driver (the ONLY generation seam):
game = {
  frame()                  -> int,
  read_party()             -> party|nil, why,     -- list of decoded mons with .slot
  key(m)                   -> string,
  game_is_live()           -> bool, why,
  save_cleared()           -> bool,               -- Gen1: player_id==0; Gen3: SB2 ptr null/cleared
  hello_ready()            -> bool, why,          -- live AND (in_battle OR checkpoint ok)
  hello_fields()           -> table,              -- merged into the hello envelope
  tick_fields()            -> table|nil,          -- nil = unreadable frame, no tick
  in_battle()              -> bool,
  checkpoint_ok()          -> bool, why,          -- safety:check(safety:snapshot())
  start()                  -> signals instance,   -- builds S.new(...) with sync on_fire handlers
  on_signal(sig),                                  -- the reducer; emits via session.send
  frame_hooks              = { fn, ... },          -- settle_pending_change, etc.
  commands                 = { [name] = fn(cmd) }, -- gen-specific (rival/trade on Gen1; none on FRLG)
  battle_write(cmd)        -> handled?|nil,        -- nil on gen3_frlg P4: force_* always deferred
  on_reset(),
}
```
`lua/gen3/client.lua` exports `Client.new(p) -> session` (the Gen 1 constructor shape). Internally it builds the driver table and returns `Session.new{..., game = driver}`. Required behaviours: `hello` carries `rom_type, foundation, artifact_kind, rom_sha1, ot_id, trainer_name, party, pc_boxes, has_pokeballs, ball_count, badges, area_id, loc_name, writes_enabled, in_battle` (Gen 1 set `:1543-1554`, minus panel/rom_content). Empty lists go through `json.array` (conformance item 1, `conformance_map.py:37-43`). `show_choices/show_menu/choose_mon` use the cancel sentinels and no `trade_request` (`PLAN.md:139`). An unsolicited `apply_trade` writes nothing, because the pack has no `trade` reason (`PLAN.md:236`). Pending holds report their reason and age in the tick HUD line (`PLAN.md:131`).

### 3.3 `lua/core/identity.lua` and `lua/core/deferred.lua`
```lua
local Id = Identity.new{ key = fn }              -- key(m) -> string
Id:find_party_slot(key, party) -> slot, mon, party, why   -- "ambiguous key" | alias reasons
Id:begin_alias(old_key, new_key, mon)  ; Id:ack(old_key) ; Id:reject(old_key, party)
Id:observe(party)  ; Id:departure(key)  ; Id:retired(key) -> alias|nil ; Id:clear()

local Q = Deferred.new{ send, log, hud, identity = Id, memorial_box = int, exec = {
    arm = fn(), disarm = fn(),                  -- the "overworld" window (+allow)
    faint_slot = fn(slot),
    deposit = fn(key, hint) -> true | nil, reason,
    withdraw = fn(key, stats, nickname) -> true | nil, reason,   -- base stats resolved by the executor
    memorialize = fn(key, hint) -> true | nil, reason,
    stats_of = fn(mon) -> {level=, maxHP=},
    rescan = fn() } }
Q:push(cmd) ; Q:size() ; Q:run(gate_ok, game_over)   -- one per frame; retry-at-tail on "party full"/"last party mon"
```

### 3.4 `lua/gen3/boxes.lua` (mirrors the Gen 1 client aliases, `gen1/boxes.lua:534-537`)
```lua
local boxes = B.new(profile, reads, io)   -- io: read_bytes, rom_read, writes (armed; boxes builds allow ranges)
boxes:deposit(key, slot_hint)       -> true | nil, reason
boxes:withdraw(key, stats, nickname) -> true | nil, reason    -- idempotent: key already in party => true
boxes:memorialize(key, slot_hint)   -> true | nil, reason     -- idempotent; optional memorial_rename
boxes:scan()                        -> { {box, slot, key, species_id, nickname, level, moves}, ... }
boxes.memorial_box                  -- 0-based index (value from the Codex old-client inventory)
```
- The reason vocabulary must include exactly `"party full"`, `"last party mon"`, `"key not in party"`, `"key not boxed"` and `"ambiguous duplicate key"`.
- Vanilla moves copy the 80-byte BoxPokemon raw. The encryption key is personality^OTID and the move does not change it. The nickname lives outside the checksummed block. So deposit and memorialize need **no encoder**.
- Withdraw rebuilds the party tail. Level comes from exp plus the growth rate. Stats come from base stats (`BASESTATS_ADDR_BY_GAME_CODE`, `BASESTATS_ENTRY_SIZE`), IVs, EVs and nature = PID % 25. HP starts at max and status is cleared. Removing a party member compacts the party.
- Every write goes through `writes:arm("overworld", allow)`. The allow ranges come from `reads.party_base()` and from `reads.read_storage()` plus the box span. The `gPokemonStoragePtr` relocation is covered by the safety snapshot (`safety.lua:96-102`).

### 3.5 `lua/gen3/run.lua` (mirrors `gen1/run.lua` 1:1)
The steps, in order:
1. Self-locate ROOT and set `package.path`.
2. Read `SLINK_HOST/PORT/PLAYER`.
3. Build `io` from `shadow_run.build_io:58-85` with the real `write_u8(a, v) = memory.write_u8(a, v, "System Bus")` and `saveram = client.saveram`.
4. Build `ev` from `event.on_bus_exec`/`event.unregisterbyid`, with hook names prefixed `SLink-gen3-`.
5. Call `Entry.admit{rom_hash = gameinfo.getromhash(), rom_read, header_code}`. On refusal, give the named reason on the console **and** the HUD.
6. `H.init{screen_w = 240, screen_h = 160}`, then `C.init`.
7. `Entry.build{mode = "production"}`, then `pcall(client:start)`.
8. Set `SLINK_GEN3_CLIENT = client`.
9. `onframeend`: pcall `frame_end`, then `H.render`. `onexit`: `stop`.

No per-frame `console.log` (memory: gate drivers).

### 3.6 Launcher route
```lua
-- lua/slink.lua, after the Gen 1 block (slink.lua:58-82), before game_detect (:84):
do
    local sys_ok, sys = pcall(function() return emu.getsystemid() end)
    if sys_ok and sys == "GBA" then
        local Entry = dofile(_dir .. "gen3/entry.lua")
        local function rom_read(off, n) local t = {} for i = 1, n do t[i] = memory.read_u8(off + i - 1, "ROM") end return t end
        local ok, a = pcall(Entry.admit, { root = _dir .. "..", json = dofile(_dir .. "json_codec.lua"),
            rom_hash = gameinfo.getromhash(), rom_read = rom_read, header_code = Entry.header_code(rom_read) })
        if ok and a and Entry.ROUTED[a.pack] and a.admitted_by ~= "header" then
            -- same 2.11+ guard as the Gen 1 route (slink.lua:73-78)
            dofile(_dir .. "gen3/run.lua"); return
        end
    end
end
```
- `admitted_by ~= "header"` is **required** in P4. RR carries FireRed's header code `BPRE` (`gen3/entry.lua:51-53`), so an unpinned RR build would otherwise be admitted as `firered/named`, sent to the new client, and refused by the site check. That would be a regression for RR players.
- `gen3_rr`, Emerald, AP and header-only cartridges fall through to `game_detect`, which sends them to the old client (`_CLIENT_MAP`, `slink.lua:93-98`).
- `lua/slink_gen3.lua` becomes `dofile(_dir .. "slink.lua")` (today it goes straight to the old client, `slink_gen3.lua:18`), so the route decision lives in one place.

---

## 4. Harness, conformance, release

### 4.1 How the Gen 1 new-client row runs today
- **Registry**: `SCENARIOS` (`e2e_duo.py:60`). The `*_new` entries each carry `games = ("gen1_new",)` and an `oracle` (`:75-186`). `gen1_new` is listed in `OPT_IN_GAMES` (`:208`), so shared scenarios with no `games` key do not leak into it (`scenario_applies`, `:223-235`).
- **Game row**: the `GAMES["gen1_new"]` row sets `main`, `game`, `play`, `rom`, `uses_savestate: False`, `fixture` and `scenario_prefix` (`:912-920`).
- **Battery boot**: the row's `play` module stages the ROM (`:1394-1397`, `:1508-1512`). `gen1_playthrough.write_run_config` runs per instance (`:1429-1435`). `run_gb_gate.seed_saveram` seeds the battery (`:1399-1411`). The stub sets `SLINK_DUO` (`:1440-1484`).
- **Driver**: `duo_gen1_main.lua` builds the real client like `run.lua`, boots the battery, and runs scenarios defined inline as functions (`duo_gen1_main.lua:1-17`, `:518`, e.g. `link_new` at `:602`). The save witness tees the `SLink-gen1-save_witness` hook (`:118-180`, wrapper at `:145-147`).
- **Verdict**: needs PASS on both sides, then `_run_oracle` (`e2e_duo.py:4231`). `_run_oracle` requires an oracle for the `gen1_new` family, runs `check_save_witness` first, then `assert_*_saved` (`:4180-4207`). `check_save_witness` compares the hook-time CartRAM slice `0x498..0x8000` against the flushed SaveRAM, with ordinal and freshness rules (`:4086-4178`).
- **Pytest wrapper**: `tests/e2e/test_duo_gen1_new.py:36-77`.

### 4.2 What the `gen3_frlg` row needs
- **Row**:
  ```python
  GAMES["gen3_frlg"] = {"main": "lua/tests/duo/duo_gen3_main.lua", "game": "gen3_frlg", "play": "gen3_fixtures",
                        "rom": {"a": FR, "b": LG}, "uses_savestate": False,
                        "fixture": {"a": "firered", "b": "leafgreen"},
                        "scenario_prefix": "gen3_", "oracle_required": True}
  ```
  Add the row to `OPT_IN_GAMES`.
- **Generalize three Gen 1 hardwirings** so they dispatch to `play.*`: `launch_instance` (`:1429-1435`), `_seed_instance_save` (`:1399-1411`), and the family gate in `_run_oracle`/`run` (`:4189-4196`, `:4232`). `gen3_fixtures.py` already has `stage_rom` (`:399`), `write_gba_run_config` (`:417`) and `saveram_name` (`:385`). Clean FR/LG batteries are filed under the gamedb name (`tests/fixtures/gen3/README.md` "boot-check").
- **Scenario-name collision** (decision fork): PLAN names the scenarios bare (`PLAN.md:137`), but `faint` and `boxsync` already exist without a `games` key (`e2e_duo.py:61-62`), and `lua/tests/duo/scenario_boxsync.lua` is the old RR driver. **Proposed**: keys `<name>_gen3`, `games = ("gen3_frlg",)`, oracle `assert_<name>_gen3_saved`, and driver files `lua/tests/duo/scenario_gen3_<name>.lua` (the ctx pattern of `duo_main.lua:130-189` plus the prefix resolution of `duo_gb_main.lua:235`). P5 extends each `games` tuple with `gen3_rr`. Update `tests/unit/test_e2e_duo_scenario_selection.py:67-127`.
- **`duo_gen3_main.lua`**, a new file. `duo_main.lua` stays on the old RR client for the `gen3_rr` row (`duo_main.lua:102`). The new file must:
  1. boot the battery and take CONTINUE (the pattern in `lua/tests/gen3_boot_check.lua`);
  2. build the real client exactly like `run.lua`;
  3. tee `SLink-gen3-save` to dump the `SRAM` domain (0x20000; `PLAN.md:112`, P1 row g) inside the hook;
  4. log `MYKEY`, `TX`/`RX` and `RESULT` lines like the Gen 1 driver.
- **`check_save_witness_gen3`** (`PLAN.md:134`) must require all of these:
  - the witness is newer than the attempt start;
  - the flash counter advanced relative to the fixture;
  - the sector set is complete;
  - untouched regions are byte-equal;
  - the decoded party and boxes equal the flushed battery;
  - the RTC suffix is normalized through `gen3_codec` (`split_rtc`, used at `gen3_fixtures.py:529`).
- **Fixtures present** (`tests/fixtures/gen3/`): `firered_town.sav` (FR, **pre-starter, empty party**, `JONN #99DE0D8A`, counter 1, boot-checked; README "firered_town.sav"), `rr_town.sav` and `rr_town_b.sav`.
- **Fixtures missing**: every LeafGreen fixture, every FR/LG `_b` variant, and every FR fixture with a party or a battle position.
  - The LG ROM exists only at the main checkout root (`docs/gen3_requirements.md:23`).
  - Every party scenario (faint_cmd, linked_faint_active, boxsync, whiteout, link, deadzone) needs post-starter saves: `town` saves on encounter-free ground and `battle` saves in grass with Poke Balls (memory: savestate rot rule).
  - The FR scripted-play driver `lua/tests/gen3_scripted_play.lua` (2692 lines) already reaches starter → parcel → Route 1 catch/faint → Viridian PC → save, with `SLINK_GEN3_PLAY_FROM` resume (`:1-40`). A fixture builder can cut saves from its legs. LG shares the FR maps, but its intro and preset names are unverified.
  - **Key-collision risk**: the same inputs on FR and LG may produce the same TID/PID, and the server's key index is flat. The fixture card must assert that the A and B key sets are disjoint; otherwise run `derive-b` on the LG side (vanilla `derive-b` is implemented, README step 5).

### 4.3 Conformance: the transcript half and the World half
- **Transcript half (today)**: `tests/unit/test_protocol_conformance.py` holds only this half: doc-sync meta-tests (`:58-77`), transcript checkers (`:136-415`) and transcript tests (`:420-467`). `conformance_map.py` tags items by layer (`:34`); 37 are `"world"`.
- **Gen 1 has no conformance World half.** Its "World" is the lupa class in `tests/unit/test_gen1_client.py:47-130`: a fake BizHawk and a fake server over the real `Entry.build`, with every sent line validated by `protocol_schema`.
- **Gen 3 World half, proposed**:
  - `tests/unit/gen3_world.py`: a shared fake GBA bus + ROM + ev + net + hud that drives production `Entry.build`. Shape: `test_gen3_entry.py:72-112` plus net/hud/write capture.
  - A new section 3 in `test_protocol_conformance.py` with `_WORLD_TESTS = {item_id: fn}` and a meta-test that every `"world"` item has an entry.
- **Transport items (1-7)**: extend `test_connector_{fragmentation,reconnect}.py` to drive the Gen 3 client's `frame_end` order (pump, then hello; `test_connector_reconnect.py:5-8`).
- **Write-ownership guard** (`PLAN.md:166`):
  - a static test: no `memory.write`/`write_u8|u16|u32` under `lua/gen3/` or `lua/core/` except in `gen3/writes.lua`;
  - a World run with an io sink that asserts every write arrives through `writes` while it is armed.

### 4.4 Release
- **How Gen 1 ships**: `_LUA_GEN1` (`make_release.py:91-102`) is added at `:356` and `:414-416`. The pack data is in `_DATA_GAME_LUA` (`:130-155`). The closure test roots at `_ENTRYPOINTS = [slink.lua, slink_gen1.lua]` (`test_make_release_manifest.py:31`). It derives dofile/require/literal paths (`:33-103`) and asserts the ZIP contains them (`:139-145`).
- **Gen 3 additions**:
  - `_LUA_GEN3 = [run, entry, client, reads, signals, writes, safety, boxes]` (not `shadow_run`) and `_LUA_CORE = [session, identity, deferred]`.
  - `_DATA_GAME_LUA["gen3_frlg"]` and `["gen3_rr"]` = `profile.json, engine_signals.json, write_checkpoint.json`. The `gen3_rr` files ship too because `admit` reads every pack's sites (`gen3/entry.lua:101-115`).
  - `gen3_frlge/area_map.json`.
  - `_ENTRYPOINTS += "lua/slink_gen3.lua"`, plus closure expectations for `lua/gen3/entry.lua`, `lua/core/session.lua` and `data/games/gen3_rr/engine_signals.json`.

---

## 5. Card cut (six cards)

**Can start now in parallel: C4-1, C4-2, C4-3, C4-4 and the fixture half of C4-6.**
- C4-2 and C4-4 code against §3 and integrate after C4-1 and C4-3 land.
- C4-5 starts when C4-2 reaches M1 (World harness plus hello/tick green).
- The C4-6 scenario lanes run after C4-1..C4-4 integrate.

| Card | Exclusive files | Prereqs | First falsifier | Exit evidence |
|---|---|---|---|---|
| **C4-1 Shared core** (Opus) | `lua/core/{session,identity,deferred}.lua`, `tests/unit/test_core_session.py` | none | A fake driver whose `read_party` goes nil for 5 validations: writes pause, queues survive, and one live validation re-enables them (Gen 1 `:348-355` semantics). Also: an aliased key with two evidence matches is refused. | lupa suite green, including tail-retry budget, `game_over` drop, keyed replies, ambiguity latch, and `stats_cache` sent after a confirmed deposit. No `lua/gen1/*` diff. `lua_syntax_check`. |
| **C4-2 Gen 3 client driver + reads** (Opus) | `lua/gen3/client.lua`, `lua/gen3/reads.lua` (additions), `data/games/gen3_frlg/profile.json` via `tools/gen_gen3_profile.py`, `tools/gen3_reads_pydec.py`, `tests/unit/{gen3_world.py,test_gen3_client.py,test_gen3_reads.py,test_gen3_reads_pydec.py}` | codes against C4-1's §3.2/§3.3 surface | World: an injected `faint` signal for a party mon yields exactly one schema-valid `faint` event with the right key. A hello sent before the checkpoint predicate holds must not happen. | M1: World + hello/tick schema-valid. Then: every reducer kind in `gen3_shadow_diff.KINDS` mapped; new reads PYDEC-equal; cancel sentinels; `apply_trade` writes nothing. `ruff`, lupa. |
| **C4-3 Boxes** (Codex) | `lua/gen3/boxes.lua`, `tests/unit/test_gen3_boxes.py` | reads/writes as they are today. New profile fields are requested from C4-2 (e.g. an exp-table address). | Deposit of the last party mon returns `nil, "last party mon"` and the write log is empty. A deposited 80-byte record decodes byte-identical through `gen3_codec`. | Deposit/withdraw/memorialize are idempotent and round-trip through `gen3_codec`. Withdrawn stats equal the codec's calculation. The reason vocabulary is exactly §3.4. All writes are armed `overworld` with allow ranges. |
| **C4-4 Bootstrap + packaging** (Codex/Sonnet) | `lua/gen3/entry.lua` (production mode, `ROUTED`, `area_map`), `lua/gen3/run.lua`, `lua/slink.lua`, `lua/slink_gen3.lua`, `tools/make_release.py`, `tests/unit/test_make_release_manifest.py`, `tests/unit/test_gen3_entry.py`, `server/manager.py` (AP/Emerald labels only), a new `tests/unit/test_slink_route.py` | stubs client/boxes behind §3.1 until C4-1..C4-3 land | Route test: an RR artifact hash, an unknown BPRE hash (header-named) and BPEE must all reach `game_detect`, not `gen3/run.lua`. Build test: `mode = "observer"` output is unchanged. | Production `Entry.build` returns a client (the mode-refusal test is flipped). Manifest closure includes `lua/gen3/*`, `lua/core/*`, and the `gen3_rr`/`gen3_frlg`/area JSONs. `pytest tests/unit -q` green. Gen 1 and Gen 2 route tests unchanged. |
| **C4-5 Conformance World + connector + write guard** (Sonnet) | `tests/unit/test_protocol_conformance.py` (new section 3), `tests/unit/test_connector_{fragmentation,reconnect}.py`, `tests/unit/test_gen3_write_ownership.py` | C4-2 M1 (`gen3_world.py`) | The meta-test fails until every `"world"` item has a test. The static leak test catches a planted `memory.write_u8` in a scratch copy of `lua/gen3/client.lua`. | All 37 world items green (or xfail with an item-level reason from `conformance_map`). Transport items driven by the Gen 3 client. Write ownership proven by static scan plus intercepted sinks. |
| **C4-6 Lane: fixtures + duo + live gates** (Codex, second worktree; the lane is serialized) | `tools/gen3_fixtures.py` (fixture builder from scripted-play legs, LG support), `tests/fixtures/gen3/{firered,leafgreen}_{town,battle}.sav` (+ `_b` if keys collide), `tools/e2e_duo.py` (row, `play` dispatch, `oracle_required`, `assert_*_gen3_saved`, `check_save_witness_gen3`), `lua/tests/duo/duo_gen3_main.lua`, `lua/tests/duo/scenario_gen3_{faint_cmd,linked_faint_active,boxsync,whiteout,link,deadzone,reconnect}.lua`, `tests/e2e/test_duo_gen3.py`, `tests/unit/test_e2e_duo_scenario_selection.py`, `tests/live/test_gen3_gates.py` | The fixtures depend on nothing and start now. The duo runs depend on C4-1..C4-4. | Fixture: `qualify` plus `boot-check` PASS for FR and LG with a non-empty party and disjoint A/B keys. Harness: a `gen3_frlg` scenario with no oracle FAILS (mirrors `:4189-4194`). | Seven FRLG receipts with `SAVE_WITNESS_SHA256`, counter delta and oracle verdict. Wrong-save refusal. Reconnect. Cold-boot admission. Extracted-zip boot on FR. The `gen1_new` and `gen2` lanes re-run unchanged after the `slink.lua` route change. |

**Decision forks to settle before dispatch:**
1. In-battle `force_faint` on FRLG. Default: defer to the checkpoint and record the limit (§2 item 2).
2. Scenario key names. Default: `<name>_gen3` (§4.2).
3. Whether the shared `lua/core/` is born now with Gen 1 re-binding later, or P4 copies. Default: born now. This is the owner's shared-framework goal, and `lua/gen1/` is off-limits in P4.
4. The route guard `admitted_by ~= "header"` (§3.6).
