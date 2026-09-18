# P3 — CLIENT_BRIEF.md line citations refreshed against bbcd037

Scope: every line-number reference in `docs/purergb/research/d3/CLIENT_BRIEF.md` (1170 lines), resolved against the Gen 1 client as it exists at **bbcd037**. Read-only; no other file is touched.

**Why bbcd037 is the right target, and why the current worktree is the same tree.**

```
$ git log --oneline -1 bbcd037
bbcd037 docs(gen1): resume note -- merged to local master 24fdb06 ...
$ git diff --stat bbcd037 HEAD -- lua/        # empty -> lua/ is identical at bbcd037 and at HEAD
$ cd gen1-master-release-plan-6b4279 && git rev-parse HEAD
bbcd037f07fe3486a8e7fa6714d9e7b80a2f3691     # the d3 worktree is itself at bbcd037
$ diff -rq lua/gen1 <this worktree>/lua/gen1  # no output -> byte-identical
```

So `CLIENT_BRIEF.md` was written against `W/lua/gen1/*`, and `W`'s tree and this worktree's tree are the same bytes at bbcd037: **the file contents the brief read are the file contents today**, and only line-number drift could show up. It does not: every citation below resolves, except one whose prose is wrong about the mechanism (table 1, row 19).

**Columns.** `brief citation` = the reference as written (bare `line NNN` references are shown as `file:line`, using the enclosing section's file, with a parenthetical when my resolution differs from that file). `current` = the resolved location at bbcd037. Text is the first 80 characters of the anchor line, verbatim. `status`: **SAME** = the code at that location still is what the brief describes; **MOVED** = the described code lives elsewhere; **CHANGED** = the location is right but the code differs from the description; **GONE** = not found.

## 1. Explicit `file.lua:NNN` citations (30)

| brief citation | current at bbcd037 | current line text (first 80) | status | note |
|---|---|---|---|---|
| `client.lua:87` | `client.lua:87` | `local BALL_ITEMS = { [1] = true, [2] = true, [3] = true, [4] = true } -- MASTER.` | **SAME** | `local BALL_ITEMS = { [1]..[4] }` — the four vanilla ball ids, verbatim. |
| `client.lua:543` | `client.lua:543` | `                local base = species and self.rom and self.rom.base_stats_for(sp` | **SAME** | `self.rom.base_stats_for(species)` — the 28-byte-stride caller. |
| `client.lua:628` | `client.lua:628` | `                self.battle = { frame = sig.frame, wild = pt.cur_opponent < 200,` | **SAME** | `wild = pt.cur_opponent < 200` — the trainer threshold. |
| `client.lua:927` | `client.lua:927` | `            in_battle = battle and battle.in_battle ~= 0 or false, rom_content =` | **SAME** | Inside `send_hello`'s payload table (line 927 is `in_battle = battle and ...`), which is what `reads.read_battle()` feeds. |
| `client.lua:960` | `client.lua:960` | `    local TRADE_DISPATCH = { 0x21, 0x00, 0x4C, 0x06, 0x3F } -- receptionist hook` | **SAME** | `local TRADE_DISPATCH = { 0x21, 0x00, 0x4C, 0x06, 0x3F }` with the `0x29C3` comment. |
| `client.lua:996` | `client.lua:996` | `            if io.read_u8(0x29C3 + i - 1, "ROM") ~= b then return false end` | **SAME** | `io.read_u8(0x29C3 + i - 1, "ROM")` — the receptionist hook byte check. |
| `client.lua:1092-1093` | `client.lua:1092-1093` | `                    local party = current_party()` | **SAME** | `local party = current_party()` / `local received = party and party[#party]` — the native-trade apply readback. |
| `client.lua:1137` | `client.lua:1137` | `            local svc = self.trade.service_address and self.trade.service_addres` | **SAME** | The `service_address()` fallback `or { bank = 0x3F, addr = 0x4500 }`. |
| `reads.lua:194` | `reads.lua:194` | `        local capacity = math.floor((a.wPlayerMoney - a.wBagItems - 1) / 2)` | **SAME** | `local capacity = math.floor((a.wPlayerMoney - a.wBagItems - 1) / 2)`. |
| `reads.lua:244-250` | `reads.lua:244-250` | `        -- constants/trainer_constants.asm:1: trainer class = opponent - 200.` | **SAME** | Line 244 is the `opponent - 200` comment, 245 reads `wCurOpponent`, 249-250 carry the two `>= 200` literals. |
| `reads.lua:248-255` | `reads.lua:248-255` | `        return {in_battle = io.read_u8(a.wIsInBattle), type = io.read_u8(a.wBatt` | **SAME** | `read_battle`'s returned table, ending with `result`/`link_state`. |
| `reads.lua:255` | `reads.lua:255` | `                result = io.read_u8(a.wBattleResult), link_state = io.read_u8(a.` | **SAME** | `link_state = io.read_u8(a.wLinkState)` inside that return table. |
| `rom.lua:10` | `rom.lua:10` | `local Rom = { RECORD = 28, GROWTH = 19 }` | **SAME** | `local Rom = { RECORD = 28, GROWTH = 19 }`. |
| `rom.lua:18` | `rom.lua:18` | `        if type(internal) ~= "number" or internal < 1 or internal > 190 then ret` | **SAME** | `internal < 1 or internal > 190` — the vanilla internal-index bound. |
| `rom.lua:30-31` | `rom.lua:30-31` | `        return { dex = r[0], hp = r[1], attack = r[2], defense = r[3], speed = r` | **SAME** | The record table; `growth_rate = r[Rom.GROWTH]` on line 31 (GROWTH = 19). |
| `rom.lua:37` | `rom.lua:37` | `        if type(dex) ~= "number" or dex < 1 or dex > 151 then return nil, "dex o` | **SAME** | `dex < 1 or dex > 151` — the vanilla dex bound. |
| `signals.lua:38` | `signals.lua:38` | `        return hl == ram.wNumBagItems and carry and item >= 1 and item <= 4` | **SAME** | `... and item >= 1 and item <= 4` — the ball filter. |
| `signals.lua:119` | `signals.lua:119` | `    return { in_battle = io.read_u8(ram.wIsInBattle, "System Bus"),` | **SAME** | `in_battle = io.read_u8(ram.wIsInBattle, "System Bus")` in `acquisition_point`. |
| `signals.lua:140-147` | `signals.lua:140-147` | `local function storage_point(io, ram)` | **CHANGED** | Location is right, the brief's prose is wrong: `storage_point` does not read `wBoxData` (that symbol is absent from `signals.lua` and from the profile, which has `wBoxDataStart`/`wBoxDataEnd`). The box block comes from `block_len(ram, "Box")`, i.e. the `wBoxMonNicks - wBoxMonOT` delta. Line 146 is `box = io.read_range(ram.wBoxCount, block_len(ram, "Box"), "System Bus")`. |
| `signals.lua:172-179` | `signals.lua:172-179` | `S.KINDS.npc_trade = {` | **SAME** | `S.KINDS.npc_trade` — reads `wInGameTradeGiveMonSpecies`/`wInGameTradeReceiveMonSpecies`/`wWhichPokemon` (the brief's `ram.wInGameTradeGiveMonSpecies` name matches line 175). |
| `signals.lua:184-223` | `signals.lua:184-223` | `function S.new(profile, sites, io, on_fire)` | **SAME** | `S.new` through the end of `fire`'s on_fire dispatch (the range's last lines are 220-223). |
| `signals.lua:220-223` | `signals.lua:220-223` | `            if on_fire[kind] then` | **SAME** | `if on_fire[kind] then local hok, herr = pcall(on_fire[kind], signal) ...` — synchronous, inside the hook. |
| `entry.lua:99-101` | `entry.lua:99-101` | `    if name:find("RED", 1, true) then return "red" end` | **SAME** | The three `name:find("RED"|"BLUE"|"YELLOW", 1, true)` returns. |
| `run.lua:26` | `run.lua:26` | `local rom_sha1 = (gameinfo and gameinfo.getromhash and gameinfo.getromhash() or ` | **SAME** | `gameinfo.getromhash()` lowercased. |
| `run.lua:39` | `run.lua:39` | `console.log(string.format("[SLink-gen1] %s player %s -> %s:%d (rom %s)", title, ` | **SAME** | The `console.log` with `title`, `player`, host/port and `rom_sha1:sub(1,8)`. |
| `panel.lua:14` | `panel.lua:14` | `local MAILBOX = 0xDEE2` | **SAME** | `local MAILBOX = 0xDEE2`. |
| `trade_overlay.lua:27-30` | `trade_overlay.lua:27-30` | `function T.service_address()` | **SAME** | `T.service_address()` returning `{bank = 0x3F, addr = 0x4500}` on line 29. |
| `gen1_write_safety.lua:39-40` | `gen1_write_safety.lua:39-40` | `            or not rom_matches(p.delay_frame, {0x3E, 1, 0xE0, p.vblank_flag % 25` | **SAME** | The 8-byte `DelayFrame` literal `{0x3E, 1, 0xE0, vblank_flag, 0x76, 0xF0, vblank_flag, 0xA7}`. |
| `gen1_write_safety.lua:62` | `gen1_write_safety.lua:62` | `        if resume ~= p.delay_frame + 5` | **SAME** | `if resume ~= p.delay_frame + 5`. |
| `gen1_write_safety.lua:63` | `gen1_write_safety.lua:63` | `            or (caller ~= p.overworld_loop + 3 and caller ~= p.overworld_loop_le` | **SAME** | `or (caller ~= p.overworld_loop + 3 and caller ~= p.overworld_loop_less_delay + 3)`. |

## 2. Bare `line NNN` references resolved to Lua (85 distinct)

Deduplicated by (file, range); a reference repeated in several sections appears once. Six rows are re-attributed: the brief's prose names a different file than the enclosing section, and those rows carry the parenthetical.

| brief citation | current at bbcd037 | current line text (first 80) | status | note |
|---|---|---|---|---|
| `boxes.lua:362-382` | `boxes.lua:362-382` | `    local function rebuild(entry, base)` | **SAME** | `rebuild(entry, base)`. |
| `boxes.lua:383-406` | `boxes.lua:383-406` | `    local function encode_nickname(name)` | **SAME** | `encode_nickname`. |
| `boxes.lua:389` | `boxes.lua:389-389` | `            local glyph = reads.decode_name({b})` | **SAME** | `local glyph = reads.decode_name({b})` — the reverse map really is injected. |
| `boxes.lua:408` | `boxes.lua:408-408` | `    function self.party_mon(key, base_stats, nickname, stats)` | **SAME** | `function self.party_mon(key, base_stats, nickname, stats)`. |
| `boxes.lua:440` | `boxes.lua:440-440` | `        blob, why = rebuild(original, base_stats)` | **SAME** | `blob, why = rebuild(original, base_stats)`. |
| `boxes.lua:442` | `boxes.lua:442-442` | `        local nick = original.nick` | **SAME** | `local nick = original.nick`. |
| `boxes.lua:444` | `boxes.lua:444-444` | `            nick, why = encode_nickname(nickname)` | **SAME** | `nick, why = encode_nickname(nickname)`. |
| `client.lua:96` | `client.lua:96-96` | `local MOVE_BOX_TO_PARTY, MOVE_PARTY_TO_BOX, MOVE_DAYCARE_TO_PARTY, MOVE_PARTY_TO` | **SAME** | `local MOVE_BOX_TO_PARTY, MOVE_PARTY_TO_BOX, MOVE_DAYCARE_TO_PARTY, MOVE_PARTY_TO_DAYCARE = 0, 1, 2, 3`. |
| `client.lua:128` | `client.lua:128-128` | `        player = p.player, rom_type = p.rom_type, rom_sha1 = p.rom_sha1,` | **SAME** | `player = p.player, rom_type = p.rom_type, rom_sha1 = p.rom_sha1,` in the constructor. |
| `client.lua:193-200` | `client.lua:193-200` | `    local function enemy_party(battle)` | **SAME** | `enemy_party(battle)`. |
| `client.lua:202-207` | `client.lua:202-207` | `    local function ball_count()` | **SAME** | `ball_count()`. |
| `client.lua:219-239` | `client.lua:219-239` | `    function self:rescan_boxes()` | **SAME** | `self:rescan_boxes()` (the box_cache/rescan pair the apex handler must reuse). |
| `client.lua:312-392` | `client.lua:312-392` | `    function self:handle_command(cmd)` | **SAME** | `self:handle_command(cmd)`. |
| `client.lua:390` | `client.lua:390-390` | `            log("[SLink-gen1] unknown command " .. tostring(c))` | **SAME** | `log("[SLink-gen1] unknown command " .. tostring(c))`. |
| `client.lua:515` | `client.lua:515-515` | `        local safe, why = safety.check(ws_profile, io)` | **SAME** | `local safe, why = safety.check(ws_profile, io)` inside `run_deferred`. |
| `client.lua:633` | `client.lua:633-633` | `                if not self.battle.wild then send("trainer_battle_start", { trai` | **SAME** | `if not self.battle.wild then send("trainer_battle_start", { trainer_id = pt.cur_opponent ...`. |
| `client.lua:684-697` | `client.lua:684-697` | `        elseif k == "add_party_mon" or k == "capture_box" then` | **SAME** | The `add_party_mon`/`capture_box` branch (684) through the `$80` suppression (688) to 697. |
| `client.lua:690` | `client.lua:690-690` | `            elseif self.pending_change and self.pending_change.kind == "npc_trad` | **SAME** | `elseif self.pending_change and self.pending_change.kind == "npc_trade" then`. |
| `client.lua:698-719` | `client.lua:698-719` | `        elseif k == "move_mon" then` | **SAME** | The `move_mon` branch. |
| `client.lua:720-785` | `client.lua:720-785` | `        elseif k == "remove_pokemon" then` | **SAME** | The `remove_pokemon` branch. |
| `client.lua:791-794` | `client.lua:791-794` | `        elseif k == "npc_trade" then` | **SAME** | The `npc_trade` branch entry through the `pending_change` assignment. |
| `client.lua:794` | `client.lua:794-794` | `            if key then self.pending_change = { kind = "npc_trade", frame = sig.` | **SAME** | `if key then self.pending_change = { kind = "npc_trade", frame = sig.frame, slot = ...`. |
| `client.lua:810-847` | `client.lua:810-847` | `        if pc.kind == "acquire" then` | **SAME** | `settle_pending_change`'s `acquire` branch. |
| `client.lua:816` | `client.lua:816-816` | `                for _, m in ipairs(party) do if not self.known_keys[mon_key(m)] ` | **SAME** | The `for _, m in ipairs(party) do if not self.known_keys[mon_key(m)] then found = m` new-mon heuristic. |
| `client.lua:848-860` | `client.lua:848-860` | `        elseif pc.kind == "evolution" or pc.kind == "npc_trade" then` | **SAME** | The `evolution`/`npc_trade` settle branch. |
| `client.lua:858` | `client.lua:858-858` | `            elseif self.frame - pc.frame > 300 then` | **SAME** | `elseif self.frame - pc.frame > 300 then` — the cancel timeout. |
| `client.lua:870-902` | `client.lua:870-902` | `    function self:on_battle_loop_head(sig)` | **SAME** | `self:on_battle_loop_head(sig)` — the template for the new on-fire handlers. |
| `client.lua:905-933` | `client.lua:905-933` | `    function self:send_hello()` | **SAME** | `self:send_hello()`. |
| `client.lua:923` | `client.lua:923-923` | `            rom_type = self.rom_type, party = party or arr({}), ot_id = reads.re` | **SAME** | `rom_type = self.rom_type, party = party or arr({}), ot_id = ...` — the hello payload. |
| `client.lua:924-925` | `client.lua:924-925` | `            trainer_name = reads.read_player_name(), has_pokeballs = self.has_po` | **SAME** | `trainer_name`/`has_pokeballs` (924) and `ball_count`/`badges`/`area_id` (925) in the payload. |
| `client.lua:946-953` | `client.lua:946-953` | `        send(event or "tick", {` | **SAME** | `send_tick`'s payload table (`send(event or "tick", {` … `})`). |
| `client.lua:994-999` | `client.lua:994-999` | `    function self:trade_patch_present()` | **SAME** | `self:trade_patch_present()`. |
| `client.lua:1131-1148` | `client.lua:1131-1148` | `    function self:start()` | **SAME** | `self:start()`. |
| `client.lua:1168-1171` | `client.lua:1168-1171` | `        if connected and not self.hello_sent and game_is_live()` | **SAME** | `frame_end`'s hello gate: `if connected and not self.hello_sent and game_is_live()` … `end`. |
| `client.lua:1169` | `client.lua:1169-1169` | `           and (reads.read_battle().in_battle ~= 0 or safety.check(ws_profile, i` | **SAME** | `and (reads.read_battle().in_battle ~= 0 or safety.check(ws_profile, io)) then`. |
| `client.lua:86 (brief prose: "signals.lua's battle_loop_head/opponent_point points")` | `signals.lua:86-86` | `                 link_state = io.read_u8(ram.wLinkState, "System Bus"),` | **SAME** | `link_state = io.read_u8(ram.wLinkState, "System Bus")` inside `battle_point`. |
| `client.lua:101 (same sentence)` | `signals.lua:101-101` | `             link_state = io.read_u8(ram.wLinkState, "System Bus") }` | **SAME** | The same read inside `opponent_point`. |
| `client.lua:105-111 (brief prose: "signals.lua's S.KINDS.battle_end point")` | `signals.lua:105-111` | `S.KINDS.battle_end = {` | **SAME** | `S.KINDS.battle_end`'s point, including `p.result = io.read_u8(ram.wBattleResult, ...)` on 108. |
| `client.lua:268 (brief prose: "mirroring read_save_file_status's one-liner shape")` | `reads.lua:268-268` | `    function r.read_save_file_status() return io.read_u8(a.wSaveFileStatus) end ` | **SAME** | `function r.read_save_file_status() return io.read_u8(a.wSaveFileStatus) end`. |
| `signals.lua:46-70 (brief prose: "entry.lua's reads_io/box_io construction")` | `entry.lua:46-70` | `    local bio = deps.io` | **SAME** | `local reads_io = {` (48) through `local box_io = {` (54) and its `write_cart_bytes` door (to 70). |
| `signals.lua:48-51 (brief prose: "entry.lua's reads_io")` | `entry.lua:48-51` | `    local reads_io = {` | **SAME** | The `reads_io` table (System-Bus reads with no domain argument). |
| `entry.lua:26` | `entry.lua:26-26` | `Entry.ROM_TYPE = { red = "Red", blue = "Blue", yellow = "Yellow" }` | **SAME** | `Entry.ROM_TYPE = { red = "Red", blue = "Blue", yellow = "Yellow" }`. |
| `entry.lua:28-88` | `entry.lua:28-88` | `function Entry.build(deps)` | **SAME** | `function Entry.build(deps)` … `end`. |
| `entry.lua:39-44` | `entry.lua:39-44` | `    local profile = assert(load_json(json, root .. "/data/games/gen1_rby/profile` | **SAME** | The two `data/games/gen1_rby/...json` pack paths (line 39 profile, line 44 statics). |
| `entry.lua:90-103` | `entry.lua:90-103` | `-- Title from the cartridge header (ROM $0134..$0143): "POKEMON RED"/"POKEMON BL` | **SAME** | The `detect_title` comment (90) through `function Entry.detect_title(read_rom_u8)` (91) to `end` (103). |
| `entry.lua:91` | `entry.lua:91-91` | `function Entry.detect_title(read_rom_u8)` | **SAME** | `function Entry.detect_title(read_rom_u8)`. |
| `gen1_write_safety.lua:6-71` | `gen1_write_safety.lua:6-71` | `function M.check(profile, io)` | **SAME** | `function M.check(profile, io)` … `end`. |
| `gen1_write_safety.lua:9` | `gen1_write_safety.lua:9-9` | `        if type(p) ~= "table" or p.version ~= M.VERSION then` | **SAME** | `if type(p) ~= "table" or p.version ~= M.VERSION then` (the version gate; `M.VERSION` is declared on line 4). |
| `gen1_write_safety.lua:41-42` | `gen1_write_safety.lua:41-42` | `            or not rom_matches(p.overworld_loop, instruction(0xCD, p.delay_frame` | **SAME** | The `overworld_loop`/`overworld_loop_less_delay` `instruction(0xCD, p.delay_frame)` checks. |
| `panel.lua:15` | `panel.lua:15-15` | `local BEACON  = { 0x53, 0x4C, 0x4E, 0x4B }  -- 'SLNK', rewritten every VBlank` | **SAME** | `local BEACON  = { 0x53, 0x4C, 0x4E, 0x4B }  -- 'SLNK', rewritten every VBlank`. |
| `panel.lua:16-20` | `panel.lua:16-20` | `local ABI     = MAILBOX + 4` | **SAME** | `ABI`/`CAPS`/`STATE`/`PAGE`/`PAGES`, all `MAILBOX + n`. |
| `reads.lua:6-8` | `reads.lua:6-8` | `-- The three runs below are pokered/constants/charmap.asm:92-117,126-151,187-196` | **SAME** | The charmap-source comment (`pokered/constants/charmap.asm:92-117,126-151,187-196`). |
| `reads.lua:9-28` | `reads.lua:9-28` | `local EXTRA = {` | **SAME** | `local EXTRA = {` … `}`. |
| `reads.lua:30-35` | `reads.lua:30-35` | `local function glyph(b)` | **SAME** | `local function glyph(b)` … `end`. |
| `reads.lua:56` | `reads.lua:56-56` | `            if bytes[i] == 0x50 then break end -- constants/charmap.asm:12, @ te` | **SAME** | `if bytes[i] == 0x50 then break end -- constants/charmap.asm:12, @ terminator`. |
| `reads.lua:190-206` | `reads.lua:190-206` | `    function r.read_bag()` | **SAME** | `r.read_bag()` … `end`. |
| `reads.lua:242-256` | `reads.lua:242-256` | `    function r.read_battle()` | **SAME** | `r.read_battle()` … `end`. |
| `reads.lua:249-250` | `reads.lua:249-250` | `                cur_opponent = opponent, is_trainer = opponent >= 200,` | **SAME** | The two `opponent >= 200` literals. |
| `rom.lua:17-25` | `rom.lua:17-25` | `    function self.natdex(internal)` | **SAME** | `self.natdex`. |
| `rom.lua:27-46` | `rom.lua:27-46` | `    local function record_at(flat)` | **SAME** | `record_at` (27-32) and `self.base_stats` (36-46), incl. the `dex == 151 and rom.MewBaseStats` branch on 40. |
| `rom.lua:49-53` | `rom.lua:49-53` | `    function self.base_stats_for(internal)` | **SAME** | `self.base_stats_for(internal)`. |
| `rom.lua:77-140` | `rom.lua:77-140` | `    function self.rom_content()` | **SAME** | `self.rom_content()` … `end`. |
| `rom.lua:110-112` | `rom.lua:110-112` | `        local old = assert(rom.ItemUseOldRod, "ItemUseOldRod symbol required").f` | **SAME** | `local old = assert(rom.ItemUseOldRod, ...).flat + 6` (110) and the `payload.old_rod = hex_bytes(old + 1, 2)` (112). |
| `rom.lua:114` | `rom.lua:114-114` | `        payload.good_rod = hex_bytes(assert(rom.GoodRodMons, "GoodRodMons symbol` | **SAME** | `payload.good_rod = hex_bytes(assert(rom.GoodRodMons, ...).flat, 4)`. |
| `rom.lua:116-138` | `rom.lua:116-138` | `        if rom.SuperRodFishingSlots then` | **SAME** | The `if rom.SuperRodFishingSlots then` branch through its `end`. |
| `rom.lua:116` | `rom.lua:116-116` | `        if rom.SuperRodFishingSlots then` | **SAME** | `if rom.SuperRodFishingSlots then`. |
| `run.lua:19-33` | `run.lua:19-33` | `local deps = Entry.bizhawk_deps()` | **SAME** | `local deps = Entry.bizhawk_deps()` through the `Client.new({...})` call. |
| `run.lua:44-48` | `run.lua:44-48` | `event.onframeend(function()` | **SAME** | `event.onframeend(function() ... end)`. |
| `run.lua:49` | `run.lua:49-49` | `event.onexit(function() pcall(function() client:stop() end) end)` | **SAME** | `event.onexit(function() pcall(function() client:stop() end) end)`. |
| `signals.lua:29-179` | `signals.lua:29-179` | `S.KINDS = {}` | **SAME** | `S.KINDS = {}` through the last kind's `}`. |
| `signals.lua:35-36` | `signals.lua:35-36` | `        local hl = io.register("H") * 256 + io.register("L")` | **SAME** | The `io.register("H")`/`io.register("F")` reads — the register-read precedent. |
| `signals.lua:37` | `signals.lua:37-37` | `        local item = io.read_u8(ram.wCurItem, "System Bus")` | **SAME** | `local item = io.read_u8(ram.wCurItem, "System Bus")`. |
| `signals.lua:41-43` | `signals.lua:41-43` | `        return { item = io.read_u8(ram.wCurItem, "System Bus"),` | **SAME** | `bag_received`'s point table. |
| `signals.lua:67-68` | `signals.lua:67-68` | `S.KINDS.starter_begin = { point = battle_point }` | **SAME** | `S.KINDS.starter_begin`/`starter_end`, both `{ point = battle_point }`. |
| `signals.lua:202-226` | `signals.lua:202-226` | `    local function fire(kind, site)` | **SAME** | `local function fire(kind, site)` … `end` (bank/PC/byte re-verification). |
| `signals.lua:228-233` | `signals.lua:228-233` | `    for kind, site in pairs(sites) do` | **SAME** | The hook-registration loop. |
| `signals.lua:231` | `signals.lua:231-231` | `        assert(id, "engine signal registration failed: " .. kind)` | **SAME** | `assert(id, "engine signal registration failed: " .. kind)` — the truthy check the brief flags. |
| `signals.lua:257-271` | `signals.lua:257-271` | `function S.bizhawk_io()` | **SAME** | `function S.bizhawk_io()` … `end`. |
| `slink.lua:58-73` | `slink.lua:58-73` | `-- ── Gen 1 route ──────────────────────────────────────────────────────────────` | **SAME** | The `── Gen 1 route ──` comment (58) through the route body's `end` (73). |
| `trade_overlay.lua:5` | `trade_overlay.lua:5-5` | `local MAGIC = {0x53, 0x4C, 0x54, 0x31} -- trade_service.asm:173-185; receptionis` | **SAME** | `local MAGIC = {0x53, 0x4C, 0x54, 0x31} -- 'SLT1'`. |
| `trade_overlay.lua:5-6` | `trade_overlay.lua:5-6` | `local MAGIC = {0x53, 0x4C, 0x54, 0x31} -- trade_service.asm:173-185; receptionis` | **SAME** | `MAGIC` (5) and `local VERSION, QUERY, OFFER, PROMPT, APPLY, DONE, RELEASE = 1, 1, 2, 3, 5, 7, 8` (6). |
| `trade_overlay.lua:40` | `trade_overlay.lua:40-40` | `    local overlay = assert(ram.wSerialPartyMonsPatchList)` | **SAME** | `local overlay = assert(ram.wSerialPartyMonsPatchList)`. |
| `writes.lua:57-73` | `writes.lua:57-73` | `    function self:arm(reason, allow)` | **SAME** | `self:arm(reason, allow)` … `end` — the allow predicate the brief contrasts with `write_bytes`. |
| `writes.lua:63-73` | `writes.lua:63-73` | `    function self:write_bytes(addr, bytes)` | **SAME** | `self:write_bytes(addr, bytes)` … `end` — the function that has no range check. |
| `writes.lua:87-92` | `writes.lua:87-92` | `    function self:faint_active_battler(slot)` | **SAME** | `self:faint_active_battler(slot)` … `end` — the validation pattern to mirror. |

## 3. Bare `line NNN` references resolved to Python tests (23 distinct)

These are the brief's "extend this test" references; they sit in sections about a `.lua` file but name `W/tests/unit/*.py` tests. All 23 land on the named test.

| brief citation (as written) | current at bbcd037 | current line text (first 80) | status |
|---|---|---|---|
| `entry.lua:69 (prose: `test_the_three_titles_are_recognised`)` | `test_gen1_entry.py:69-69` | `def test_the_three_titles_are_recognised(entry, title, expected):` | **SAME** |
| `entry.lua:73 (`test_an_unrelated_title_returns_nil_and_the_header_text`)` | `test_gen1_entry.py:73-73` | `def test_an_unrelated_title_returns_nil_and_the_header_text(entry):` | **SAME** |
| `entry.lua:84 (`test_the_real_dumps_report_their_own_title`)` | `test_gen1_entry.py:84-84` | `def test_the_real_dumps_report_their_own_title(entry, title):` | **SAME** |
| `entry.lua:91 (`test_rom_type_strings_are_the_ones_the_server_routes_on`)` | `test_gen1_entry.py:91-91` | `def test_rom_type_strings_are_the_ones_the_server_routes_on(entry):` | **SAME** |
| `reads.lua:229-232 (the seed dict; `wNumBagItems`/`wBagItems`/`wPlayerMoney`)` | `test_gen1_reads.py:229-232` | `        "wCurrentBoxNum": (0x8B,), "wNumBagItems": (2,),` | **SAME** |
| `reads.lua:231 (`oracle.encode_name("RED")`)` | `test_gen1_reads.py:231-231` | `        "wPlayerID": (0x12, 0x34), "wPlayerName": tuple(oracle.encode_name("RED"` | **SAME** |
| `reads.lua:234 (`original["battle"]["is_trainer"]`)` | `test_gen1_reads.py:234-234` | `        "wIsInBattle": (2,), "wBattleType": (0,), "wCurOpponent": (202,),` | **SAME** |
| `reads.lua:264 (`test_ancillary_reads_and_all_addresses_follow_shifted_profile`)` | `test_gen1_reads.py:264-264` | `def test_ancillary_reads_and_all_addresses_follow_shifted_profile(title):` | **SAME** |
| `reads.lua:275-276 (`is_trainer` / `trainer_class == 2`)` | `test_gen1_reads.py:275-276` | `    assert original["battle"]["is_trainer"]` | **SAME** |
| `gen1_write_safety.lua:90 (`test_every_title_has_a_verified_checkpoint`)` | `test_gen1_safe_state.py:90-90` | `def test_every_title_has_a_verified_checkpoint(title):` | **SAME** |
| `gen1_write_safety.lua:134 (`test_the_cpu_must_be_parked_in_the_verified_loop`)` | `test_gen1_safe_state.py:134-134` | `def test_the_cpu_must_be_parked_in_the_verified_loop():` | **SAME** |
| `gen1_write_safety.lua:147 (`test_a_changed_cartridge_is_never_trusted_from_cache`)` | `test_gen1_safe_state.py:147-147` | `def test_a_changed_cartridge_is_never_trusted_from_cache():` | **SAME** |
| `panel.lua:246 (`test_every_write_lands_inside_the_allow_set`)` | `test_gen1_panel.py:246-246` | `def test_every_write_lands_inside_the_allow_set():` | **SAME** |
| `panel.lua:279 (`test_present_abi_and_awaiting_read_the_mailbox`)` | `test_gen1_panel.py:279-279` | `def test_present_abi_and_awaiting_read_the_mailbox():` | **SAME** |
| `client.lua:567 (`test_active_force_faint_waits_for_the_battle_loop_head`)` | `test_gen1_client.py:567-567` | `def test_active_force_faint_waits_for_the_battle_loop_head(world):` | **SAME** |
| `client.lua:583 (`test_hello_waits_for_the_overworld_checkpoint_not_the_main_menu`)` | `test_gen1_client.py:583-583` | `def test_hello_waits_for_the_overworld_checkpoint_not_the_main_menu(world):` | **SAME** |
| `client.lua:645 (`test_a_battle_write_queued_before_a_pause_still_lands_at_the_loop_head`)` | `test_gen1_client.py:645-645` | `def test_a_battle_write_queued_before_a_pause_still_lands_at_the_loop_head(world` | **SAME** |
| `writes.lua:75 (`test_nothing_is_written_without_an_armed_window`)` | `test_gen1_writes.py:75-75` | `def test_nothing_is_written_without_an_armed_window():` | **SAME** |
| `writes.lua:106 (`test_active_battler_faint_needs_the_loop_head_and_hits_both_structs`)` | `test_gen1_writes.py:106-106` | `def test_active_battler_faint_needs_the_loop_head_and_hits_both_structs():` | **SAME** |
| `writes.lua:122 (`test_active_faint_guard_rules`)` | `test_gen1_writes.py:122-122` | `def test_active_faint_guard_rules():` | **SAME** |
| `writes.lua:149 (`test_enemy_party_is_validated_completely_before_any_byte_lands`)` | `test_gen1_writes.py:149-149` | `def test_enemy_party_is_validated_completely_before_any_byte_lands():` | **SAME** |
| `trade_overlay.lua:88 (`test_query_mask_token_and_ack_order`)` | `test_gen1_trade_overlay.py:88-88` | `def test_query_mask_token_and_ack_order(title):` | **SAME** |
| `trade_overlay.lua:133 (`test_arm_stages_enemy_preimage_and_publishes_generation_last`)` | `test_gen1_trade_overlay.py:133-133` | `def test_arm_stages_enemy_preimage_and_publishes_generation_last(command):` | **SAME** |

## 4. New vanilla assumptions in the client files that the brief does not mention

Each was found by reading the files for literals/symbols the brief never names (substring search over all 1170 brief lines), then confirmed at the line.

| # | where | what the code assumes | why it matters for pureRGB |
|---|---|---|---|
| 1 | `signals.lua:132-138` (`block_len`, used at 145-146) | The party and box snapshot lengths are **derived from WRAM symbol arithmetic**: `w<X>MonNicks - w<X>Count` plus `w<X>MonNicks - w<X>MonOT`, i.e. count + species list + 44-byte structs + OT block + nickname block are one contiguous run. | The brief parametrises the 28-byte stride and the charmap but never this. A pureRGB WRAM section reorder (or any symbol inserted between those three) silently changes the snapshot length; nothing validates it. |
| 2 | `signals.lua:48`, `:169`, `:177`, and the comment at `client.lua:578` | A hardcoded `404`-byte party block on three reads (battle point, evolve point, npc_trade point). | Same class as `rom.lua:10`'s `28`: a vanilla constant that must become `profile.derived` (PLAN §4 row 12 keeps 404 for pureRGB, but as data, not a literal — the brief never lists it). |
| 3 | `signals.lua:43` | `bag = io.read_range(ram.wNumBagItems, 42, ...)` — the 42-byte bag snapshot, i.e. the vanilla 20-slot bag. | PLAN §4 row 6 has the pureRGB bag at **30 slots / 62 bytes**; the brief covers the `read_bag` capacity formula (`reads.lua:194`) but not this second copy of the same assumption. |
| 4 | `signals.lua:150-155` and `:161-162` | `wMoveMonType` compared against the vanilla 0/1/2/3 encoding, and `wRemoveMonFromBox` as the party-vs-box discriminator. | Never mentioned. S1's RAM table resolves `wMoveMonType` and `wRemoveMonFromBox` to the **same byte, `$CF95`**, in pureRGB (they are never live at once) — the code must keep that invariant explicit rather than assume two distinct addresses. |
| 5 | `panel.lua:43-49` (`_tile_for`) | A **third, independent charmap**: A-Z `0x80+`, a-z `0xA0+`, 0-9 `0xF6+`, `'/'` `0xF3`, `'-'` `0xE3`. | The brief's row 18 covers `reads.lua`'s `EXTRA`/`glyph()` and `boxes.lua`'s `encode_nickname` ("the two must be generated from the same table", brief line 239) — this is a third copy in `panel.lua` that a pureRGB charmap change must also regenerate, or the panel paints wrong glyphs. |
| 6 | `client.lua:209-216` (`pc_boxes_wire`) and `:218-239` (`rescan_boxes`) | The PC wire/scan geometry: twelve boxes, `box/slot/key/species_id/nickname/level/moves` per entry. | `pc_boxes_wire` appears **0 times** in the brief (which cites `rescan_boxes` once, line 1108, only as "already present" for the apex handler). The box count/stride is a foundation fact. |
| 7 | `client.lua:225` (`io.read_range(0, 0x8000, "CartRAM")`) and `entry.lua:52-54` (`write_cart_bytes`) | A flat 32 KiB SRAM image (`CartRAM` domain, `0x8000` bytes) plus a hand-written `write_cart_bytes` door that bypasses `writes:write_bytes`. | `CartRAM` / `0x8000` appear **0 times** in the brief. §6.3 handles the flat *WRAM* read domain and §7.2 the WRAM BANK write gate; the SRAM door is the sibling case, and it is the one that rewrites a whole box bank. |

## 5. What did not move

- The three commits the card named as possible sources of new client literals — `947a577`, `94f0058`, `0fce67c` — **do not touch `lua/gen1/*`, `lua/gen1_write_safety.lua` or `lua/slink.lua`**: `947a577` and `94f0058` touch `lua/tests/*` only, `0fce67c` touches `server/server.py` + `tests/unit/test_party_snapshot_dispatch.py` (`git show --stat`). Zero client literals came from them.
- No citation in the brief resolves to a **MOVED** or **GONE** location. The single correction is `signals.lua:140-147`'s description (table 1, row 19).

---

Counts: citations 138 (30 explicit + 85 bare-Lua + 23 test) | SAME 137 | MOVED 0 | CHANGED 1 | GONE 0 | NEW assumptions 7.
