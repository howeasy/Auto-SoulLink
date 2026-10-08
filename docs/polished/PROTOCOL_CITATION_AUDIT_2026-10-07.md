# Protocol citation audit — 2026-10-07

Source commit: `87813ee8c41841e93b5134f95437f098b2f790bd` (branch `claude/pol-docs3`). The request named integration `addea4dec`; this checkout is later. All document line numbers and replacement ranges below refer to the checked-out source, not that earlier integration commit.

Method: read `docs/protocol.md`, the four semantic rules in `tests/unit/test_protocol_citations.py`, and the cited source ranges with PowerShell/Node (no Python). Inventory full Python/Lua citations, exclude symbol/event/command/single-field references judged by rules 1–4, and expand comma continuations and bare ranges, including the explicit client/wire/reads/adapter aliases in §8.1. The existence-only rule does not establish semantic correctness and therefore does not exclude Lua references. Counts are **occurrences**, not unique ranges; duplicate occurrences are retained. Shorthand continuations are separate rows because the test's regex does not judge them. Python coverage exclusions were reproduced statically, not by executing the Python AST checker; exact equivalence to that check is **UNVERIFIED**. HTML, Markdown, and external pret-source citations are outside this Python/Lua card.

**654 occurrences: OK 116; DRIFTED 527; GONE 11. Dagger rows: 121 citation occurrences across 43 document lines.** These are this audit's inventory counts, not confirmation of the recalled 269-occurrence audit. “OK” means the original range supports its local cited clause; a dagger can still flag contradictory prose elsewhere in that document row. “DRIFTED” supplies a current supporting range, sometimes in a different file after a module move. “GONE” means the historical referent or orphan range cannot be retained as a current citation. Quotes are excerpts of **what the original cited range contains now**, at most 100 characters; bracketed text denotes a blank or out-of-file range.

**† requires prose repair, not just renumbering.** Where an old list of individual call sites no longer has a one-to-one correspondence, the replacement is explicitly a current representative: collapse that obsolete list, do not mechanically duplicate the representative citation. Such rows are not a mechanical-only repair. Likewise remove orphan legacy-client ranges rather than guessing their original owner. No protocol or production file was changed, and no staging or commit was performed.

**Landing order:** after the box-contract branch lands, re-pin HEAD and re-check every `server/state.py` and `server/server.py` replacement before applying numeric repairs. The table describes the current pre-contract source; it is not authority for a future box acknowledgement contract. No pytest, emulator, native-save, or PHYSICAL qualification was run.

Final verification observed HEAD advance externally to `5f37dacf4bd72ed545264d8fe60695ed81b0974f`. The diff from the source pin contains only `docs/polished/BOX3_STAGE2.md` and `docs/polished/TRADE_PUMP.md`; the audited protocol and source files are unchanged. Node checks confirmed table ordering, replacement file/range bounds, and quote lengths. The two-field row at doc line 320 is included: its mentioned `_enrich_box` is nested inside a method, so rule 1 deliberately does not treat it as a named symbol.

| doc line | original citation | verdict | replacement | quote/qualification |
|---:|---|---|---|---|
| 15 | <code>state.py:119-120</code> | DRIFTED | <code>server/state.py:158-159</code> | <code>nickname: str = ""</code> |
| 23 | <code>server.py:5601-5602</code> | DRIFTED | <code>server/server.py:5713-5714</code> | <code>def build_app(srv):</code> |
| 24 | <code>connector.lua:7-9</code> | OK | <code>lua/connector.lua:7-9</code> | <code>Protocol: newline-delimited JSON.</code> |
| 24 | <code>server.py:2762</code> | DRIFTED | <code>server/server.py:1640</code> | <code>fired.append(("battle_start_new", player_id, {}))</code> |
| 24 | <code>server.py:2914</code> | DRIFTED | <code>server/server.py:1877-1880</code> | <code>"""Add item_name and move_details to PC box entries."""</code> |
| 25 | <code>server.py:2787-2789</code> | DRIFTED | <code>server/server.py:1663-1665</code> | <code>fired.append(("area_enter", player_id, {"area_id": _area_id}))</code> |
| 26 | <code>server.py:1560-1575</code> | DRIFTED | <code>server/server.py:1643-1658</code> | <code>Clients that only need the ping can ignore status events and</code> |
| 26 | <code>server.py:5601-5602</code> | DRIFTED | <code>server/server.py:5713-5714</code> | <code>def build_app(srv):</code> |
| 27 † | <code>connector.lua:51</code> | OK | <code>lua/connector.lua:51</code> | <code>local MAX_LINE        = 4 * 1024 * 1024   -- matches the server's own per-line cap</code> — Only partial receives enforce MAX_LINE; the complete-line path at connector.lua:220-233 has no size check. |
| 27 † | <code>connector.lua:242-247</code> | OK | <code>lua/connector.lua:242-247</code> | <code>elseif #_recv_buf + #partial &gt; MAX_LINE then</code> — Only partial receives enforce MAX_LINE; the complete-line path at connector.lua:220-233 has no size check. |
| 27 † | <code>connector.lua:221-228</code> | OK | <code>lua/connector.lua:221-228</code> | <code>if _drop_until_newline then</code> — Only partial receives enforce MAX_LINE; the complete-line path at connector.lua:220-233 has no size check. |
| 28 | <code>lua/core/session.lua:78-88</code> | DRIFTED | <code>lua/core/session.lua:91-100</code> | <code>local net, json, hud = assert(p.net, "net"), assert(p.json, "json"), assert(p.hud, "hud")</code> |
| 29 † | <code>server.py:1598</code> | DRIFTED | <code>server/server.py:1672</code> | <code>await asyncio.wait_for(q.get(), timeout=3.0)</code> — Blank/oversized inbound lines are skipped without replies (server/server.py:1643-1665). |
| 29 † | <code>server.py:1609</code> | DRIFTED | <code>server/server.py:1831-1832</code> | <code>break</code> — Blank/oversized inbound lines are skipped without replies (server/server.py:1643-1665). |
| 29 † | <code>state.py:715</code> | OK | <code>server/state.py:715</code> | <code>return cmds if cmds else [{"cmd": "noop"}]</code> — Blank/oversized inbound lines are skipped without replies (server/server.py:1643-1665). |
| 30 | <code>server.py:1594-1598</code> | DRIFTED | <code>server/server.py:1666-1673</code> | <code># zombie SSE connections inside Chrome's per-origin pool,</code> |
| 34 | <code>state.py:2-8</code> | OK | <code>server/state.py:2-8</code> | <code>server/state.py — SoulLinkState: Soul Link Nuzlocke finite state machine.</code> |
| 34 | <code>state.py:343-348</code> | DRIFTED | <code>server/state.py:704-715</code> | <code># Latest battle request identity per player (card C5-10): (session nonce, battle</code> |
| 34 | <code>state.py:615-623</code> | DRIFTED | <code>server/state.py:704-715</code> | <code>rb["restored_keys"].add(key)</code> |
| 35 | <code>state.py:715</code> | OK | <code>server/state.py:715</code> | <code>return cmds if cmds else [{"cmd": "noop"}]</code> |
| 35 | <code>server.py:1918</code> | DRIFTED | <code>server/server.py:2620-2625</code> | <code>return f"{label}&#124;{name[:10]}&#124;{level}&#124;BOX&#124;0&#124;B&#124;"</code> |
| 36 | <code>connector.lua:150-154</code> | OK | <code>lua/connector.lua:150-154</code> | <code>--- Call once per frame. Drives:</code> |
| 36 | <code>lua/core/session.lua:361</code> | DRIFTED | <code>lua/core/session.lua:411</code> | <code>-- key_change is still armed for one. Nothing else consumes the rescan (the driver keeps</code> |
| 36 | <code>lua/core/session.lua:406-415</code> | DRIFTED | <code>lua/core/session.lua:456-468</code> | <code>function self:frame_end()</code> |
| 37 | <code>connector.lua:55-57</code> | OK | <code>lua/connector.lua:55-57</code> | <code>local RECONNECT_FRAMES = 30     -- ~0.5 s at 60 fps (initial retry interval)</code> |
| 37 | <code>connector.lua:161-187</code> | OK | <code>lua/connector.lua:161-187</code> | <code>-- ── Reconnect (with exponential backoff) ──────────────────────────────────</code> |
| 37 | <code>connector.lua:78</code> | OK | <code>lua/connector.lua:78</code> | <code>_reconnect_step = RECONNECT_FRAMES  -- reset backoff on success</code> |
| 37 | <code>connector.lua:103</code> | OK | <code>lua/connector.lua:103</code> | <code>_reconnect_step = RECONNECT_FRAMES</code> |
| 38 | <code>connector.lua:134-136</code> | OK | <code>lua/connector.lua:134-136</code> | <code>function M.connected()</code> |
| 38 | <code>connector.lua:92-113</code> | OK | <code>lua/connector.lua:92-113</code> | <code>local function _check_pending_connect()</code> |
| 39 | <code>lua/connector.lua:262-280</code> | OK | <code>lua/connector.lua:262-280</code> | <code>--- Close the socket and schedule a reconnect attempt.</code> |
| 40 | <code>lua/core/session.lua:89-98</code> | DRIFTED | <code>lua/core/session.lua:102-112</code> | <code>}</code> |
| 40 | <code>lua/core/session.lua:78-81</code> | DRIFTED | <code>lua/core/session.lua:91-95</code> | <code>local net, json, hud = assert(p.net, "net"), assert(p.json, "json"), assert(p.hud, "hud")</code> |
| 41 | <code>server.py:2914-2920</code> | DRIFTED | <code>server/server.py:1849-1861</code> | <code>"""Add item_name and move_details to PC box entries."""</code> |
| 41 | <code>state.py:180</code> | DRIFTED | <code>server/state.py:214</code> | <code>return False</code> |
| 47 | <code>lua/core/session.lua:71</code> | DRIFTED | <code>lua/core/session.lua:84</code> | <code>[blank line]</code> |
| 47 | <code>lua/core/session.lua:83</code> | DRIFTED | <code>lua/core/session.lua:96</code> | <code>local self = {</code> |
| 55 | <code>lua/core/session.lua:406-415</code> | DRIFTED | <code>lua/core/session.lua:456-468</code> | <code>function self:frame_end()</code> |
| 55 | <code>lua/gen1/client.lua:1932</code> | DRIFTED | <code>lua/gen1/client.lua:1933</code> | <code>end,</code> |
| 55 | <code>:409 [lua/core/session.lua]</code> | DRIFTED | <code>lua/core/session.lua:459</code> | <code>if self.frame % Session.VALIDATE_EVERY == 0 then self:validate() end</code> |
| 71 | <code>lua/core/session.lua:362-370</code> | DRIFTED | <code>lua/core/session.lua:411-420</code> | <code>-- the census fresh on its own PC triggers), and a scan that CANNOT land -- a null storage</code> |
| 78 | <code>server.py:2829-2865</code> | DRIFTED | <code>server/server.py:2212-2240</code> | <code>if not area_id:</code> |
| 78 | <code>server.py:3234-3234</code> | DRIFTED | <code>server/server.py:2321-2324</code> | <code>"moves":        stats.get("moves", []),</code> |
| 79 | <code>state.py:1831-1838</code> | DRIFTED | <code>server/state.py:2149-2156</code> | <code>area_id=ed["area_id"],</code> |
| 79 | <code>state.py:1916-2085</code> | DRIFTED | <code>server/state.py:2153-2382</code> | <code>from server.adapters import get_adapter</code> |
| 79 | <code>server.py:3237-3258</code> | DRIFTED | <code>server/server.py:2379-2392</code> | <code>if entry:</code> |
| 80 | <code>state.py:1847</code> | DRIFTED | <code>server/state.py:2052</code> | <code>pid: MonInfo(**mon_data)</code> |
| 81 | <code>state.py:1851</code> | DRIFTED | <code>server/state.py:2061</code> | <code># Restore Pokéball gate; default True for both if any links exist</code> |
| 81 | <code>server.py:3235-3239</code> | DRIFTED | <code>server/server.py:2364-2371</code> | <code>}</code> |
| 83 | <code>state.py:1905-1907</code> | DRIFTED | <code>server/state.py:2159-2161</code> | <code># adapter (e.g. Gen 1's Red/Blue/Yellow encounter tables).</code> |
| 84 | <code>server.py:3234-3234</code> | DRIFTED | <code>server/server.py:2358-2359</code> | <code>"moves":        stats.get("moves", []),</code> |
| 85 | <code>server.py:3234-3234</code> | DRIFTED | <code>server/server.py:2360-2361</code> | <code>"moves":        stats.get("moves", []),</code> |
| 85 | <code>server.py:3017-3036</code> | DRIFTED | <code>server/server.py:1935-1952</code> | <code>"a_nickname": e.a.nickname if e.a else "",</code> |
| 86 | <code>server.py:3234-3234</code> | DRIFTED | <code>server/server.py:2362-2363</code> | <code>"moves":        stats.get("moves", []),</code> |
| 86 | <code>server.py:3639-3656</code> | DRIFTED | <code>server/server.py:3730-3750</code> | <code>"enc-table-b":     ("enc_table",      lambda self, r: self._build_enc_table_overlay_context("b")),</code> |
| 87 | <code>state.py:2009-2024</code> | DRIFTED | <code>server/state.py:2062-2067</code> | <code>return state</code> |
| 88 | <code>server.py:3234-3234</code> | DRIFTED | <code>server/server.py:2317-2318</code> | <code>"moves":        stats.get("moves", []),</code> |
| 89 | <code>server.py:3234</code> | DRIFTED | <code>server/server.py:2317</code> | <code>"moves":        stats.get("moves", []),</code> |
| 91 | <code>server.py:2849-2851</code> | DRIFTED | <code>server/server.py:2218-2220</code> | <code>return killer</code> |
| 91 | <code>server.py:1985-2002</code> | DRIFTED | <code>server/server.py:948-966</code> | <code># NAME the dead zones, all of them. They used to be capped at eight because a</code> |
| 96 † | <code>lua/gen3/client.lua:1078-1099</code> | DRIFTED | <code>lua/gen3/client.lua:1243-1264</code> | <code>local ok, why = armed_write("battle_commit", plan, { battler = battler })</code> — The gate permits rand and rand_companion, not only rand (lua/gen3/client.lua:1244). |
| 101 | <code>server.py:3235-3235</code> | DRIFTED | <code>server/server.py:2379-2385</code> | <code>}</code> |
| 103 | <code>server.py:3260-3265</code> | DRIFTED | <code>server/server.py:2393-2399</code> | <code>calc_label = _calc_trainer_label(</code> |
| 105 † | <code>lua/gen2/client.lua:55</code> | DRIFTED | <code>lua/gen2/client.lua:123</code> | <code>-- The U2 write kind whose held checkpoint the hello snapshot and the bench faint wait for.</code> — Panel, sound and trade capabilities are runtime declarations, not fixed false/0 (lua/gen2/client.lua:1855-1873). |
| 105 † | <code>:618-629 [lua/gen2/client.lua]</code> | DRIFTED | <code>lua/gen2/client.lua:1855-1873</code> | <code>self.seeded = true</code> — Panel, sound and trade capabilities are runtime declarations, not fixed false/0 (lua/gen2/client.lua:1855-1873). |
| 111 | <code>server.py:3179-3180</code> | DRIFTED | <code>server/server.py:2183-2184</code> | <code># the build, so an unbuilt calc redirects like a built one.</code> |
| 112 | <code>server.py:3187-3188</code> | DRIFTED | <code>server/server.py:2191-2192</code> | <code>"calc_mode_label": calc_files.mode_label(path),</code> |
| 112 | <code>server.py:1952-1974</code> | DRIFTED | <code>server/server.py:2269-2292</code> | <code>rows.append(f"Badges&#124;{badges}/8")</code> |
| 116 | <code>state.py:1847-1850</code> | DRIFTED | <code>server/state.py:2052-2060</code> | <code>pid: MonInfo(**mon_data)</code> |
| 117 | <code>state.py:1885-1901</code> | DRIFTED | <code>server/state.py:2100-2109</code> | <code>state.is_rr = True</code> |
| 119 | <code>state.py:1874-1883</code> | DRIFTED | <code>server/state.py:2090-2099</code> | <code>state.native_messages = False  # disabled for the RC; see __init__</code> |
| 121 † | <code>server/server.py:1530</code> | DRIFTED | <code>server/server.py:807-837</code> | <code>q.get_nowait()</code> — Unknown kinds are rejected at server/server.py:810-812; CGS routes to gen2_gsc, not the retired adapter. |
| 121 † | <code>server/server.py:721-723</code> | DRIFTED | <code>server/server.py:807-837</code> | <code>notice. The mtime check keeps it to one stat() per hello.</code> — Unknown kinds are rejected at server/server.py:810-812; CGS routes to gen2_gsc, not the retired adapter. |
| 121 † | <code>server/server.py:737-741</code> | DRIFTED | <code>server/server.py:807-837</code> | <code>return {"unreadable": True, "players": {}}</code> — Unknown kinds are rejected at server/server.py:810-812; CGS routes to gen2_gsc, not the retired adapter. |
| 121 † | <code>server/adapters/gen2_gsc.py:606-607</code> | DRIFTED | <code>server/adapters/gen2_gsc.py:685-686</code> | <code>slots = [entry if entry["species"] else times[entry["level"]][daytime] for entry in group[rod]]</code> — Unknown kinds are rejected at server/server.py:810-812; CGS routes to gen2_gsc, not the retired adapter. |
| 121 † | <code>:1763-1764 [server/server.py]</code> | DRIFTED | <code>server/server.py:807-837</code> | <code># A refused hello must leave the run exactly as it found it, so the only</code> — Unknown kinds are rejected at server/server.py:810-812; CGS routes to gen2_gsc, not the retired adapter. |
| 123 | <code>lua/core/session.lua:59-62</code> | DRIFTED | <code>lua/core/session.lua:72-75</code> | <code>-- Which frames a battle write may land on is the driver's safety predicate, never the core's.</code> |
| 123 | <code>:278-282 [lua/core/session.lua]</code> | DRIFTED | <code>lua/core/session.lua:283-288</code> | <code>if c == "force_faint" or c == "force_explode" then return route_force(cmd) end</code> |
| 125 | <code>server.py:2081</code> | DRIFTED | <code>server/server.py:2183-2184</code> | <code>[blank line]</code> |
| 125 | <code>server.py:2112</code> | DRIFTED | <code>server/server.py:2269-2292</code> | <code>return {</code> |
| 133 | <code>state.py:1916-1930</code> | DRIFTED | <code>server/state.py:2171-2183</code> | <code>from server.adapters import get_adapter</code> |
| 138 | <code>state.py:2065-2085</code> | DRIFTED | <code>server/state.py:2279-2296</code> | <code># not be able to grant or revoke anything -- otherwise a spoofed or misdirected hello</code> |
| 139 | <code>state.py:2087-2108</code> | DRIFTED | <code>server/state.py:2305-2326</code> | <code>msg["_rejected"] = True</code> |
| 140 | <code>state.py:2110-2122</code> | DRIFTED | <code>server/state.py:2334-2343</code> | <code># Adopted here: past every identity-lock return above.</code> |
| 141 | <code>state.py:3769-3821</code> | DRIFTED | <code>server/state.py:2351-2380</code> | <code>if not my_mon or not partner_mon:</code> |
| 151 † | <code>lua/core/session.lua:402-404</code> | DRIFTED | <code>lua/core/session.lua:452-455</code> | <code>function self:start()</code> — Core safe is empty, but Gen 3 adds party_hidden while withheld (lua/gen3/client.lua:2255-2263). |
| 151 † | <code>server.py:2499-2500</code> | OK | <code>server/server.py:2499-2500</code> | <code>elif event == "safe":</code> — Core safe is empty, but Gen 3 adds party_hidden while withheld (lua/gen3/client.lua:2255-2263). |
| 155 † | <code>lua/gen1/client.lua:996-998</code> | DRIFTED | <code>lua/gen1/client.lua:997-1001</code> | <code>end</code> — Stats are scoped by player at server/state.py:604; Gen 1 sends before deposit, shared Gen 3 after success. |
| 155 † | <code>lua/core/deferred.lua:159-168</code> | OK | <code>lua/core/deferred.lua:159-168</code> | <code>elseif cmd.cmd == "box_mon" then</code> — Stats are scoped by player at server/state.py:604; Gen 1 sends before deposit, shared Gen 3 after success. |
| 155 † | <code>state.py:385-409</code> | DRIFTED | <code>server/state.py:593-607</code> | <code># re-enabled by deleting this override (here and in load()).</code> — Stats are scoped by player at server/state.py:604; Gen 1 sends before deposit, shared Gen 3 after success. |
| 155 † | <code>server.py:3345-3348</code> | DRIFTED | <code>server/server.py:2473-2476</code> | <code>"connected":    bool(p.get("connected")),</code> — Stats are scoped by player at server/state.py:604; Gen 1 sends before deposit, shared Gen 3 after success. |
| 155 † | <code>state.py:2734-2736</code> | DRIFTED | <code>server/state.py:3481-3484</code> | <code>continue</code> — Stats are scoped by player at server/state.py:604; Gen 1 sends before deposit, shared Gen 3 after success. |
| 155 † | <code>state.py:56</code> | OK | <code>server/state.py:56</code> | <code>SYNC_COMMANDS = ("party_mon", "box_mon", "memorialize")</code> — Stats are scoped by player at server/state.py:604; Gen 1 sends before deposit, shared Gen 3 after success. |
| 155 † | <code>2149-2151 [server/state.py]</code> | DRIFTED | <code>server/state.py:3696-3699</code> | <code>old_size = self.party_size.get(player_id, 0)</code> — Stats are scoped by player at server/state.py:604; Gen 1 sends before deposit, shared Gen 3 after success. |
| 155 † | <code>2256-2258 [server/state.py]</code> | DRIFTED | <code>server/state.py:3794-3797</code> | <code>if not hidden:</code> — Stats are scoped by player at server/state.py:604; Gen 1 sends before deposit, shared Gen 3 after success. |
| 155 † | <code>2354-2356 [server/state.py]</code> | DRIFTED | <code>server/state.py:2893-2897</code> | <code># keys so the auto-rebuild resumes seamlessly.</code> — Stats are scoped by player at server/state.py:604; Gen 1 sends before deposit, shared Gen 3 after success. |
| 163 | <code>lua/gen1/client.lua:533</code> | DRIFTED | <code>lua/gen1/client.lua:999</code> | <code>end</code> |
| 171 | <code>base.py:167-179</code> | DRIFTED | <code>server/adapters/base.py:157-195</code> | <code>"""Return (type1, type2) for a species, or None if unknown.</code> |
| 171 | <code>state.py:1850</code> | DRIFTED | <code>server/state.py:2058-2060</code> | <code>state.mon_stats = state._load_mon_stats(data.get("mon_stats") or {})</code> |
| 171 | <code>state.py:2274</code> | DRIFTED | <code>server/state.py:2453</code> | <code>for c in self.queued_commands[player_id])):</code> |
| 172 | <code>lua/gen3/reads.lua:402</code> | OK | <code>lua/gen3/reads.lua:402</code> | <code>function r.key(mon) return string.format("%08X:%08X", mon.personality, mon.ot_id) end</code> |
| 173 | <code>base.py:638-640</code> | DRIFTED | <code>server/adapters/base.py:739-751</code> | <code>def move_name(self, move_id: int) -&gt; str:</code> — Base documents the two-part default; Gen 1 override is server/adapters/gen1_rby.py:345-349. |
| 173 | <code>gen1_rby.py:439-509</code> | DRIFTED | <code>server/adapters/gen1_rby.py:345-349</code> | <code>return "", ""</code> |
| 173 | <code>state.py:3761-3763</code> | DRIFTED | <code>server/state.py:4175-4190</code> | <code># Partner has no more room. Per Soul Link co-location, both</code> |
| 174 † | <code>state.py:3759-3782</code> | DRIFTED | <code>server/state.py:4175-4190</code> | <code>break</code> — Keys are scoped per player; equal keys across players are not rejected merely for equality (state.py:4180-4189). |
| 175 | <code>state.py:3666-3679</code> | DRIFTED | <code>server/state.py:3846-4089</code> | <code># Ghost-boxed: Lua reports key in party, server thinks it's deposited.</code> |
| 177 | <code>lua/gen3/reads.lua:461-482</code> | OK | <code>lua/gen3/reads.lua:461-482</code> | <code>function r.read_party(occupied)</code> |
| 191 | <code>state.py:353-592</code> | DRIFTED | <code>server/state.py:513-715</code> | <code># for those may the server refuse an identity-less manual rival inject. Clients that never</code> |
| 191 | <code>server.py:3501</code> | DRIFTED | <code>server/server.py:2599-2600</code> | <code>alive, dead = [], []</code> |
| 195 | <code>lua/core/session.lua:362-370</code> | DRIFTED | <code>lua/core/session.lua:411-420</code> | <code>-- the census fresh on its own PC triggers), and a scan that CANNOT land -- a null storage</code> |
| 196 | <code>lua/core/session.lua:52</code> | DRIFTED | <code>lua/core/session.lua:60</code> | <code>-- the key must resolve to one party slot; then, in battle and with a game.battle_write, the</code> |
| 196 | <code>lua/gen3/client.lua:1158-1182</code> | DRIFTED | <code>lua/gen3/client.lua:1326-1350</code> | <code>if party then seed_known(party, "rescan"); rebaseline(party) end</code> |
| 196 | <code>lua/core/session.lua:398-400</code> | DRIFTED | <code>lua/core/session.lua:448-451</code> | <code>last_hold = line</code> |
| 196 | <code>state.py:397-417</code> | DRIFTED | <code>server/state.py:667-703</code> | <code># a_key, b_key, a_label, b_label, link, confirms:{"a":None,"b":None}}. Both players confirm via</code> |
| 196 | <code>server.py:3254-3377</code> | DRIFTED | <code>server/server.py:2501-2613</code> | <code>entry["active"] = em.get("active", False)</code> |
| 196 | <code>lua/gen3/client.lua:1171-1172</code> | DRIFTED | <code>lua/gen3/client.lua:1339-1340</code> | <code>-- accessor the hello census field reads, not a second one that could drift away from it.</code> |
| 196 | <code>lua/gen3/client.lua:317-333</code> | DRIFTED | <code>lua/gen3/client.lua:327-343</code> | <code>local function party_wire(party)</code> |
| 196 | <code>server.py:3299</code> | DRIFTED | <code>server/server.py:2548-2549</code> | <code>"""Slice and reshape _build_status_dict() into the template context</code> |
| 196 | <code>server.py:3308-3327</code> | DRIFTED | <code>server/server.py:2562-2585</code> | <code>mons = []</code> |
| 197 † | <code>lua/gen3/client.lua:606-609</code> | DRIFTED | <code>lua/gen3/client.lua:683-686</code> | <code>log(string.format("ACQ known via=%s key=%s old=%s species=%s (key_change, no capture)", reason, k, t</code> — Gen 3 safe may carry party_hidden (lua/gen3/client.lua:2255-2263). |
| 197 † | <code>lua/core/session.lua:402-404</code> | DRIFTED | <code>lua/core/session.lua:452-455</code> | <code>function self:start()</code> — Gen 3 safe may carry party_hidden (lua/gen3/client.lua:2255-2263). |
| 198 | <code>lua/gen3/client.lua:560-571</code> | DRIFTED | <code>lua/gen3/client.lua:637-650</code> | <code>end</code> |
| 199 | <code>lua/gen3/client.lua:441-486</code> | DRIFTED | <code>lua/gen3/client.lua:490-546</code> | <code>-- loses a required write; the core holds them until the real party returns or the battle</code> |
| 199 | <code>lua/gen3/client.lua:488-500</code> | DRIFTED | <code>lua/gen3/client.lua:548-561</code> | <code>end</code> |
| 199 | <code>lua/gen3/client.lua:1312-1318</code> | DRIFTED | <code>lua/gen3/client.lua:1548-1558</code> | <code>for k, v in pairs(native:hello_fields() or {}) do f[k] = v end</code> |
| 199 | <code>lua/gen3/client.lua:417-428</code> | DRIFTED | <code>lua/gen3/client.lua:443-478</code> | <code>st.known[e.key] = true</code> |
| 199 | <code>lua/gen3/client.lua:383-387</code> | DRIFTED | <code>lua/gen3/client.lua:393-397</code> | <code>end</code> |
| 199 | <code>lua/gen3/client.lua:242-247</code> | DRIFTED | <code>lua/gen3/client.lua:252-257</code> | <code>end</code> |
| 200 | <code>lua/gen3/client.lua:367-372</code> | DRIFTED | <code>lua/gen3/client.lua:377-382</code> | <code>if not st.boxes_ok then return nil end</code> |
| 200 | <code>lua/gen3/client.lua:431-439</code> | DRIFTED | <code>lua/gen3/client.lua:480-488</code> | <code>st.has_pokeballs = true</code> |
| 200 | <code>server.py:2444-2457</code> | OK | <code>server/server.py:2444-2457</code> | <code># Enrich msg with cached battle-state killer info for state machine killfeed tracking.</code> |
| 200 | <code>lua/gen3/client.lua:399-401</code> | DRIFTED | <code>lua/gen3/client.lua:425-427</code> | <code>local function seed_known(party, via)</code> |
| 200 | <code>lua/gen3/client.lua:625-670 (continuation)</code> | DRIFTED | <code>lua/gen3/client.lua:702-829</code> | <code>end</code> |
| 200 | <code>lua/gen3/client.lua:1291-1334 (continuation)</code> | DRIFTED | <code>lua/gen3/client.lua:1527-1592</code> | <code>end</code> |
| 200 | <code>2604-2646 [server/state.py]</code> | DRIFTED | <code>server/state.py:2931-2961</code> | <code>log.info(f"[{player_id}] bonus pair formed — {key[:8]} boxed to sync (shiny in box)")</code> |
| 201 | <code>lua/gen3/client.lua:606-623</code> | DRIFTED | <code>lua/gen3/client.lua:683-701</code> | <code>log(string.format("ACQ known via=%s key=%s old=%s species=%s (key_change, no capture)", reason, k, t</code> |
| 201 | <code>lua/gen3/client.lua:619-622</code> | DRIFTED | <code>lua/gen3/client.lua:695-700</code> | <code>local old = before[m.slot]</code> |
| 202 | <code>lua/gen3/client.lua:1308-1311</code> | DRIFTED | <code>lua/gen3/client.lua:1544-1547</code> | <code>end</code> |
| 202 | <code>state.py:3241-3331</code> | DRIFTED | <code>server/state.py:3247-3337</code> | <code>del self.pending_captures[area_id]</code> |
| 202 | <code>server.py:3336-3340</code> | DRIFTED | <code>server/server.py:2464-2468</code> | <code>"stat_stages":  det.get("stat_stages", []) if det.get("active") else None,</code> |
| 203 | <code>lua/gen3/client.lua:502-535</code> | DRIFTED | <code>lua/gen3/client.lua:563-602</code> | <code>resolve_area()</code> |
| 203 | <code>lua/gen3/client.lua:646-660</code> | DRIFTED | <code>lua/gen3/client.lua:803-823</code> | <code>end</code> |
| 204 | <code>lua/gen3/client.lua:502-535</code> | DRIFTED | <code>lua/gen3/client.lua:563-602</code> | <code>resolve_area()</code> |
| 206 † | <code>lua/gen3/client.lua:540-558</code> | DRIFTED | <code>lua/gen3/client.lua:604-635</code> | <code>-- the signal named an acquisition but every party and boxed key was already known: nothing is repor</code> — Gen 3 emits nature_change too (lua/gen3/client.lua:626-634,1573-1587). |
| 207 | <code>lua/gen3/client.lua:575-604</code> | DRIFTED | <code>lua/gen3/client.lua:652-681</code> | <code>for k, prev in pairs(st.carried) do</code> |
| 208 | <code>lua/gen3/native.lua:1025-1106</code> | DRIFTED | <code>lua/gen3/native.lua:1040-1120</code> | <code>local rr = profile.titles and profile.titles[deps.title or "radical_red"]</code> |
| 208 | <code>lua/gen3/client.lua:1500-1567</code> | DRIFTED | <code>lua/gen3/client.lua:1769-1837</code> | <code>keys[k] = true</code> |
| 209 † | <code>lua/core/deferred.lua:159-168</code> | OK | <code>lua/core/deferred.lua:159-168</code> | <code>elseif cmd.cmd == "box_mon" then</code> — Stats are read before deposit; stats_cache is sent only after success (deferred.lua:161-168). |
| 210 | <code>lua/core/deferred.lua:175-178</code> | OK | <code>lua/core/deferred.lua:175-178</code> | <code>if done then</code> |
| 210 | <code>1740-1741 [lua/core/deferred.lua]</code> | GONE | <code>?</code> | <code>[outside file: 239 lines]</code> — Orphan legacy-client shorthand; no such line in the named shared executor. Remove it. |
| 210 | <code>2490 [lua/core/deferred.lua]</code> | GONE | <code>?</code> | <code>[outside file: 239 lines]</code> — Orphan legacy-client shorthand; no such line in the named shared executor. Remove it. |
| 210 | <code>2505 [lua/core/deferred.lua]</code> | GONE | <code>?</code> | <code>[outside file: 239 lines]</code> — Orphan legacy-client shorthand; no such line in the named shared executor. Remove it. |
| 210 | <code>2395-2410 [server/state.py]</code> | DRIFTED | <code>server/state.py:3829-3844</code> | <code>old_retry = self.retry_areas[player_id]</code> |
| 211 † | <code>lua/core/deferred.lua:179-188</code> | DRIFTED | <code>lua/core/deferred.lua:179-190</code> | <code>elseif reason == "party full" and (cmd.full_retries or 0) &lt; (cmd.full_budget or (#self.items + 1)) t</code> — Retries use a queue-length budget, not a fixed three (lua/core/deferred.lua:179-190). |
| 211 † | <code>1726 [lua/core/deferred.lua]</code> | GONE | <code>?</code> | <code>[outside file: 239 lines]</code> — Orphan legacy-client shorthand; no such line in the named shared executor. Remove it. Retries use a queue-length budget, not a fixed three (lua/core/deferred.lua:179-190). |
| 211 † | <code>1745 [lua/core/deferred.lua]</code> | GONE | <code>?</code> | <code>[outside file: 239 lines]</code> — Orphan legacy-client shorthand; no such line in the named shared executor. Remove it. Retries use a queue-length budget, not a fixed three (lua/core/deferred.lua:179-190). |
| 211 † | <code>2508 [lua/core/deferred.lua]</code> | GONE | <code>?</code> | <code>[outside file: 239 lines]</code> — Orphan legacy-client shorthand; no such line in the named shared executor. Remove it. Retries use a queue-length budget, not a fixed three (lua/core/deferred.lua:179-190). |
| 212 | <code>lua/core/deferred.lua:164-166</code> | OK | <code>lua/core/deferred.lua:164-166</code> | <code>if not done then</code> |
| 213 | <code>lua/core/deferred.lua:196-200</code> | OK | <code>lua/core/deferred.lua:196-200</code> | <code>if done then</code> |
| 214 | <code>lua/core/deferred.lua:208-210</code> | OK | <code>lua/core/deferred.lua:208-210</code> | <code>else</code> |
| 216 | <code>lua/gen3/native.lua:1245-1265</code> | DRIFTED | <code>lua/gen3/native.lua:1264-1279</code> | <code>local reason = status == FAIL and io.read_u16(p.BASE + O.reason) or nil</code> |
| 217 | <code>lua/gen3/native.lua:924-952</code> | DRIFTED | <code>lua/gen3/native.lua:939-967</code> | <code>on_publish=function()</code> |
| 217 | <code>lua/gen3/native.lua:924-952</code> | DRIFTED | <code>lua/gen3/native.lua:939-967</code> | <code>on_publish=function()</code> |
| 219 | <code>lua/gen3/native.lua:953-959</code> | DRIFTED | <code>lua/gen3/native.lua:968-973</code> | <code>for _, option in ipairs(options) do</code> |
| 219 | <code>lua/gen3/native.lua:953-959</code> | DRIFTED | <code>lua/gen3/native.lua:968-973</code> | <code>for _, option in ipairs(options) do</code> |
| 220 | <code>lua/gen3/trade.lua:149-273</code> | OK | <code>lua/gen3/trade.lua:149-273</code> | <code>local function result(t)</code> |
| 221 † | <code>lua/gen3/client.lua:248-252</code> | DRIFTED | <code>lua/gen3/client.lua:258-262</code> | <code>return f(...)</code> — Wide panel now popcounts hello/tick bitmask; it does not consume status count (server.py:1945-1952). |
| 221 † | <code>state.py:776-784</code> | OK | <code>server/state.py:776-784</code> | <code>def _handle_status(self, player_id: str, msg: dict):</code> — Wide panel now popcounts hello/tick bitmask; it does not consume status count (server.py:1945-1952). |
| 221 † | <code>server.py:3006</code> | DRIFTED | <code>server/server.py:1944-1952</code> | <code># its own &lt;details&gt; contracts and stays a Python builder for now.</code> — Wide panel now popcounts hello/tick bitmask; it does not consume status count (server.py:1945-1952). |
| 221 † | <code>server.py:3032-3051</code> | DRIFTED | <code>server/server.py:1944-1952</code> | <code>"b_enc_species": e.encounter_b.species if e.encounter_b else 0,</code> — Wide panel now popcounts hello/tick bitmask; it does not consume status count (server.py:1945-1952). |
| 222 | <code>lua/gen3/client.lua:1799</code> | DRIFTED | <code>lua/gen3/client.lua:2069</code> | <code>-- MAJOR 1 (Codex C5-10 review): the no-epoch case FIRST -- a client attached mid-battle</code> |
| 225 | <code>server.py:3307-3318</code> | DRIFTED | <code>server/server.py:2419-2432</code> | <code>mons = []</code> |
| 225 | <code>server.py:3322-3323</code> | DRIFTED | <code>server/server.py:2438-2439</code> | <code>else:</code> |
| 237 | <code>lua/gen1/client.lua:605-618</code> | DRIFTED | <code>lua/gen1/client.lua:1147-1165</code> | <code>if not party or not slot then</code> |
| 237 | <code>:681 [lua/gen1/client.lua]</code> | DRIFTED | <code>lua/gen1/client.lua:1274-1275</code> | <code>-- A1: the rename is committed server-side; the old key stops being an alias</code> |
| 241 | <code>server/state.py:3193-3225</code> | DRIFTED | <code>server/state.py:3247-3285</code> | <code>self._set_area_state(area_id, AreaStatus.DEAD_ZONE,</code> |
| 241 | <code>state.py:3229-3247</code> | DRIFTED | <code>server/state.py:3286-3313</code> | <code>self.links.append(entry)</code> |
| 241 | <code>lua/gen1/client.lua:552-557</code> | DRIFTED | <code>lua/gen1/client.lua:1054-1069</code> | <code>-- A per-frame SET, not the last code: 26 -&gt; 25 -&gt; 26 in one reply must still</code> |
| 242 | <code>lua/gen1/client.lua:546-547</code> | DRIFTED | <code>lua/gen1/client.lua:1024-1042</code> | <code>if self.config and self.config.native_sounds == true and self.panel:sfx_present() then</code> |
| 245 | <code>server/state.py:3265-3281</code> | DRIFTED | <code>server/state.py:3314-3337</code> | <code>if not self.pokeballs_obtained[player_id]:</code> |
| 251 | <code>lua/gen3/client.lua:297-316</code> | DRIFTED | <code>lua/gen3/client.lua:307-326</code> | <code>-- only while gBattleMons[battler] holds that very mon (reads.battler_holds: in a switch the</code> |
| 251 | <code>:299-303 [lua/gen3/client.lua]</code> | DRIFTED | <code>lua/gen3/client.lua:309-313</code> | <code>-- mon's stages on the incoming one). No stages at all in a link battle, nor while the pack</code> |
| 255 | <code>server.py:3300</code> | DRIFTED | <code>server/server.py:2602-2609</code> | <code>the party overlay expects. One full status-dict build per HTMX poll</code> |
| 256 | <code>server.py:3352-3368</code> | DRIFTED | <code>server/server.py:3438-3465</code> | <code>"""Focus + enemy-focus need body.ov-focus for their shell scaling</code> |
| 257 | <code>state.py:2209-2220</code> | DRIFTED | <code>server/state.py:2184-2200</code> | <code>pt["verdict"][player_id] = "await"</code> |
| 259 | <code>server.py:5244</code> | DRIFTED | <code>server/server.py:5347-5355</code> | <code>and re-deposited to a normal box via party_mon + box_mon.</code> |
| 260 | <code>server.py:2901-2904</code> | OK | <code>server/server.py:2901-2904</code> | <code>sid = d.get("species_id", 0)</code> |
| 262 | <code>server.py:3337</code> | OK | <code>server/server.py:3337</code> | <code>"active":       det.get("active", False),</code> |
| 262 | <code>server.py:2552-2556</code> | OK | <code>server/server.py:2552-2556</code> | <code>elif "enemy_party" in msg:</code> |
| 263 | <code>server.py:1925</code> | OK | <code>server/server.py:1925</code> | <code>tok = self.adapter.status_token(int(det.get("status_cond", 0) or 0))</code> |
| 264 | <code>lua/gen3/reads.lua:675-687</code> | OK | <code>lua/gen3/reads.lua:675-687</code> | <code>function r.read_stat_stages(battler)</code> |
| 268 | <code>server.py:3244</code> | DRIFTED | <code>server/server.py:2429</code> | <code>opp_name  = bs.get("opponent_name", "")</code> |
| 268 | <code>server.py:4185-4186</code> | DRIFTED | <code>server/server.py:2907-2908</code> | <code>async def handle_obs_disconnect(self, request):</code> |
| 269 | <code>server.py:3245</code> | DRIFTED | <code>server/server.py:2430</code> | <code>opp_class = bs.get("opponent_class", "")</code> |
| 269 | <code>server.py:3762-3763</code> | DRIFTED | <code>server/server.py:2905-2906</code> | <code>if last:</code> |
| 271 | <code>base.py:210-224</code> | DRIFTED | <code>server/adapters/base.py:226-240</code> | <code>def rival_trainer_ids(self) -&gt; set[int]:</code> |
| 273 | <code>server.py:3261</code> | DRIFTED | <code>server/server.py:2121</code> | <code>adapter.trainer_brief(tid) if (is_trainer and tid) else None, enemy)</code> |
| 281 | <code>server.py:3478-3484</code> | DRIFTED | <code>server/server.py:2577-2583</code> | <code>return {</code> |
| 283 | <code>2161-2162 [server/server.py]</code> | DRIFTED | <code>server/server.py:2557-2559</code> | <code>return [{"cmd": "noop", "refused": "load_failed"}]</code> |
| 285 | <code>server.py:3434-3442</code> | DRIFTED | <code>server/server.py:2544-2547</code> | <code>"mon":   self._battle_mon_card(det),</code> |
| 286 | <code>server.py:2548-2549</code> | OK | <code>server/server.py:2548-2549</code> | <code>if "enemy_party" in msg:</code> |
| 286 | <code>2516-2527 [server/server.py]</code> | DRIFTED | <code>server/server.py:2444-2454</code> | <code>if bk:</code> |
| 286 | <code>2164-2165 [server/server.py]</code> | DRIFTED | <code>server/server.py:2560-2562</code> | <code>return malformed</code> |
| 287 | <code>2967 [server/server.py]</code> | DRIFTED | <code>server/server.py:1422</code> | <code>self.player_area_id.get(pid, "") or self.player_area.get(pid, "")</code> |
| 289 | <code>3277-3296 [server/server.py]</code> | DRIFTED | <code>server/server.py:3730-3750</code> | <code>self._to_manager(request, "/runs/{id}/timeline")</code> |
| 290 | <code>3277-3296 [server/server.py]</code> | DRIFTED | <code>server/server.py:3730-3750</code> | <code>self._to_manager(request, "/runs/{id}/timeline")</code> |
| 299 | <code>lua/gen3/reads.lua:657-674</code> | OK | <code>lua/gen3/reads.lua:657-674</code> | <code>function r.read_enemy_party()</code> |
| 299 | <code>lua/gen3/client.lua:317-333</code> | DRIFTED | <code>lua/gen3/client.lua:327-343</code> | <code>local function party_wire(party)</code> |
| 303 | <code>2357-2364 [server/server.py]</code> | DRIFTED | <code>server/server.py:2444-2454</code> | <code>self.player_gender[player_id] = gender if type(gender) is int and gender in (0, 1) else None</code> |
| 303 | <code>2651 [server/server.py]</code> | DRIFTED | <code>server/server.py:187</code> | <code>f"☠ Dead zone: {_area_disp}", _area_id)</code> |
| 303 | <code>2655 [server/server.py]</code> | DRIFTED | <code>server/server.py:187</code> | <code>_link = self.state.entry_for(player_id, _faint_key)</code> |
| 304 | <code>2656 [server/server.py]</code> | DRIFTED | <code>server/server.py:188</code> | <code>if _link:</code> |
| 305 † | <code>server.py:1192-1193</code> | DRIFTED | <code>server/server.py:1383-1386</code> | <code>variants = group  # list[(rt_id, brief)]</code> — Calc prefers active=true before hp&gt;0 fallback (server.py:1385-1386); killer selection differs at :2447. |
| 305 † | <code>2658 [server/server.py]</code> | DRIFTED | <code>server/server.py:190</code> | <code>_death = (self.state.queued_death_cmd(_partner, _p_mon.key)</code> — Calc prefers active=true before hp&gt;0 fallback (server.py:1385-1386); killer selection differs at :2447. |
| 305 † | <code>2662 [server/server.py]</code> | DRIFTED | <code>server/server.py:194</code> | <code>_p_nick = (</code> — Calc prefers active=true before hp&gt;0 fallback (server.py:1385-1386); killer selection differs at :2447. |
| 306 | <code>1993-1995 [server/server.py]</code> | DRIFTED | <code>server/server.py:1383-1386</code> | <code>return {"cmd": "link_panel", "rows": rows}</code> |
| 306 | <code>2680 [server/server.py]</code> | DRIFTED | <code>server/server.py:176</code> | <code>_box_key = msg.get("key", "")</code> |
| 307 | <code>server.py:2599-2616</code> | DRIFTED | <code>server/server.py:2925-2946</code> | <code>else:</code> |
| 307 | <code>2663-2668 [server/server.py]</code> | DRIFTED | <code>server/server.py:195-206</code> | <code>_cached.get("nickname") or</code> |
| 308 | <code>server/adapters/gen1_rby.py:475-481</code> | DRIFTED | <code>server/adapters/gen1_rby.py:494-503</code> | <code>lua/gen1/client.lua enemy_party -- wild mons have no party record to read stat</code> |
| 309 | <code>server/adapters/gen1_rby.py:460-474</code> | DRIFTED | <code>server/adapters/gen1_rby.py:479-493</code> | <code>"sets": {"file": "Yellow.js", "var": "CUSTOMSETDEX_Y"}}</code> |
| 313 | <code>lua/gen3/client.lua:335-351</code> | DRIFTED | <code>lua/gen3/client.lua:345-363</code> | <code>local held, stages = stages_of(b, active[m.slot], m)</code> |
| 313 | <code>lua/gen3/client.lua:356-364</code> | DRIFTED | <code>lua/gen3/client.lua:366-375</code> | <code>end</code> |
| 313 | <code>:338-343 [lua/gen3/client.lua]</code> | DRIFTED | <code>lua/gen3/client.lua:348-353</code> | <code>stat_stages = stages,</code> |
| 317 | <code>4652 [server/server.py]</code> | DRIFTED | <code>server/server.py:4597</code> | <code>})</code> |
| 317 | <code>4701 [server/server.py]</code> | DRIFTED | <code>server/server.py:4481</code> | <code>async def handle_debug_set_area_state(self, request):</code> |
| 318 | <code>4702 [server/server.py]</code> | DRIFTED | <code>server/server.py:4605</code> | <code>"""POST /api/debug/set_area_state — manually set an area's state."""</code> |
| 319 | <code>5208-5222 [server/server.py]</code> | DRIFTED | <code>server/server.py:5323-5345</code> | <code>on its newest complete census only; None = that census is missing or stale."""</code> |
| 320 | <code>server.py:2823-2832</code> | DRIFTED | <code>server/server.py:2913-2923</code> | <code>def _area_has_open_encounter(self, area_id: str) -&gt; bool:</code> — Two-field row; _enrich_box copies the entry before enriching it. |
| 322 | <code>server.py:4817-4818</code> | DRIFTED | <code>server/server.py:2920-2922</code> | <code>see SoulLinkState.resolve_trade for how a side's known outcome binds."""</code> |
| 322 | <code>3430-3439 [server/server.py]</code> | DRIFTED | <code>server/server.py:2913-2923</code> | <code>def _battle_slot(self, det: dict) -&gt; dict:</code> |
| 331 | <code>server/ui_capabilities.py:26-30</code> | OK | <code>server/ui_capabilities.py:26-30</code> | <code>"abilities": adapter.supports_abilities(),</code> |
| 344 | <code>lua/gen3/client.lua:1033-1044</code> | DRIFTED | <code>lua/gen3/client.lua:1194-1205</code> | <code>end</code> |
| 344 | <code>lua/core/deferred.lua:116-130</code> | OK | <code>lua/core/deferred.lua:116-130</code> | <code>if #self.items == 0 then self.hold = nil; return false end</code> |
| 344 | <code>lua/core/session.lua:427-436</code> | DRIFTED | <code>lua/core/session.lua:473-484</code> | <code>if sigs and sigs.handler_error then</code> |
| 344 | <code>lua/hud.lua:301</code> | OK | <code>lua/hud.lua:301</code> | <code>duration_frames or 240)</code> |
| 344 | <code>:327 [lua/hud.lua]</code> | OK | <code>lua/hud.lua:327</code> | <code>duration_frames or 300)</code> |
| 348 | <code>state.py:623</code> | DRIFTED | <code>server/state.py:715</code> | <code>log.info(f"[{player_id}] sync_retrieve_failed for {key[:8]}")</code> |
| 348 | <code>server.py:2794</code> | DRIFTED | <code>server/server.py:1672-1677</code> | <code>if event == "box_to_party":</code> |
| 348 | <code>server.py:2476 (continuation)</code> | DRIFTED | <code>server/server.py:1672-1677</code> | <code>self.party_details[player_id].pop(key, None)</code> |
| 348 | <code>server.py:2549 (continuation)</code> | DRIFTED | <code>server/server.py:1672-1677</code> | <code>self.battle_state[player_id]["enemy_party"] = msg["enemy_party"]</code> |
| 349 | <code>state.py:4308</code> | DRIFTED | <code>server/state.py:4291-4345</code> | <code># game's client wouldn't understand it — fall back to the legacy</code> |
| 349 | <code>state.py:3798-3837</code> | DRIFTED | <code>lua/core/session.lua:174-204</code> | <code>for mon in player_picks:</code> |
| 349 | <code>state.py:3859-3887</code> | DRIFTED | <code>server/state.py:4291-4345</code> | <code>reason}, appended to this player's queue so it drains in the same reply.</code> |
| 349 | <code>state.py:2371</code> | DRIFTED | <code>server/state.py:2544-2549</code> | <code>mon = entry.a if player_id == "a" else entry.b</code> — Current capture-rejection representative; collapse the obsolete repeated site list. |
| 349 | <code>state.py:3076</code> | DRIFTED | <code>server/state.py:3233</code> | <code># slot for this area is filled (a second capture in one area is retired on arrival), so what</code> |
| 349 | <code>state.py:3135</code> | DRIFTED | <code>server/state.py:3300</code> | <code>self.queued_commands[player_id].append({"cmd": "unresolve_area", "area_id": area_id})</code> |
| 349 | <code>state.py:1421 (continuation)</code> | DRIFTED | <code>server/state.py:2544-2549</code> | <code>def _trade_evidence(self, player_id: str, party: list, from_hello: bool = False):</code> — Current capture-rejection representative; collapse the obsolete repeated site list. |
| 349 | <code>state.py:1442 (continuation)</code> | DRIFTED | <code>server/state.py:2544-2549</code> | <code>got = [(m["key"], int(m.get("species_id") or 0)) for m in party</code> — Current capture-rejection representative; collapse the obsolete repeated site list. |
| 349 | <code>state.py:1466 (continuation)</code> | DRIFTED | <code>server/state.py:2544-2549</code> | <code>self._save()                                # keep the persisted verdicts current</code> — Current capture-rejection representative; collapse the obsolete repeated site list. |
| 349 | <code>state.py:1520 (continuation)</code> | DRIFTED | <code>server/state.py:2544-2549</code> | <code>commands, so an applying trade comes back UNCERTAIN: every undecided side awaits its next</code> — Current capture-rejection representative; collapse the obsolete repeated site list. |
| 349 | <code>state.py:1596 (continuation)</code> | DRIFTED | <code>server/state.py:2544-2549</code> | <code>if not pt or pt.get("phase") not in ("uncertain", "conflict"):</code> — Current capture-rejection representative; collapse the obsolete repeated site list. |
| 350 | <code>state.py:4308</code> | DRIFTED | <code>server/state.py:4303-4321</code> | <code># game's client wouldn't understand it — fall back to the legacy</code> |
| 350 | <code>state.py:3524-3682</code> | DRIFTED | <code>lua/gen3/client.lua:953-1171</code> | <code>for ident in list(inflight):</code> |
| 350 | <code>state.py:3874-3882</code> | DRIFTED | <code>server/state.py:4303-4321</code> | <code>"""</code> |
| 351 † | <code>state.py:1808-1818</code> | DRIFTED | <code>lua/core/session.lua:279</code> | <code># Arm the post-trade settle window on BOTH sides: the swap is party↔party, so suppress the</code> — Gen 3 sends stats_cache after success and box_mon_failed on failure (deferred.lua:159-171). |
| 351 † | <code>state.py:2738-2805</code> | DRIFTED | <code>lua/core/deferred.lua:159-171</code> | <code>break</code> — Gen 3 sends stats_cache after success and box_mon_failed on failure (deferred.lua:159-171). |
| 351 † | <code>state.py:3186-3194</code> | DRIFTED | <code>server/state.py:3379-3383</code> | <code>log.info(</code> — Gen 3 sends stats_cache after success and box_mon_failed on failure (deferred.lua:159-171). |
| 351 † | <code>state.py:3212-3215</code> | DRIFTED | <code>server/state.py:3375-3379</code> | <code>})</code> — Gen 3 sends stats_cache after success and box_mon_failed on failure (deferred.lua:159-171). |
| 351 † | <code>2047-2048 [server/state.py]</code> | DRIFTED | <code>server/state.py:2787-2793</code> | <code># Deriving it from party[0]'s key makes the lock depend on which mon happens to be</code> — Gen 3 sends stats_cache after success and box_mon_failed on failure (deferred.lua:159-171). |
| 352 † | <code>state.py:1819-1837</code> | DRIFTED | <code>lua/core/session.lua:279</code> | <code>with open(state._links_path) as f:</code> — Party-full retry budget is queue-length based, not fixed three (deferred.lua:179-190). |
| 352 † | <code>state.py:2807-2890</code> | DRIFTED | <code>lua/core/deferred.lua:172-191</code> | <code>partner_cap = self.pending_captures[area_id].get(partner)</code> — Party-full retry budget is queue-length based, not fixed three (deferred.lua:179-190). |
| 352 † | <code>state.py:410-414</code> | DRIFTED | <code>server/state.py:608-616</code> | <code># completes. A trade is a party↔party swap, so no box/party sync is ever legitimately needed</code> — Party-full retry budget is queue-length based, not fixed three (deferred.lua:179-190). |
| 352 † | <code>state.py:514-566</code> | DRIFTED | <code>server/state.py:617-644</code> | <code>"""</code> — Party-full retry budget is queue-length based, not fixed three (deferred.lua:179-190). |
| 353 | <code>state.py:4390</code> | DRIFTED | <code>lua/core/deferred.lua:192-211</code> | <code>Cancels any stale box_mon/party_mon for the same key (they're now dead).</code> |
| 353 | <code>state.py:1838-1851</code> | DRIFTED | <code>lua/core/deferred.lua:192-211</code> | <code>killer=ed.get("killer"),</code> |
| 353 | <code>state.py:2922-2994</code> | DRIFTED | <code>lua/core/deferred.lua:192-211</code> | <code>self.queued_commands[partner].append({</code> |
| 353 | <code>state.py:3909-3978</code> | DRIFTED | <code>lua/core/deferred.lua:192-211</code> | <code># Unknown old key: nothing to migrate (Gen 3 nature change on an unlinked mon).</code> |
| 353 | <code>state.py:3966-3983</code> | DRIFTED | <code>server/state.py:4406-4457</code> | <code>self._propagate_faint(player_id, entry, cause="identity_lost")</code> |
| 353 | <code>state.py:2026-2031</code> | DRIFTED | <code>server/state.py:2256-2276</code> | <code>def _handle_hello(self, player_id: str, msg: dict):</code> |
| 354 | <code>state.py:2377-2378</code> | DRIFTED | <code>lua/core/session.lua:319-323</code> | <code>f"{len(outstanding_picks)} outstanding")</code> |
| 354 | <code>state.py:3165</code> | DRIFTED | <code>server/state.py:4704-4737</code> | <code>[blank line]</code> |
| 354 | <code>2941 [server/state.py]</code> | DRIFTED | <code>server/state.py:4704-4737</code> | <code>if not self.pokeballs_obtained[player_id]:</code> |
| 354 | <code>1115 [server/state.py]</code> | DRIFTED | <code>server/state.py:4704-4737</code> | <code>- "confirming": the PARTNER's accept(YES)/decline(NO) of the offer."""</code> |
| 356 | <code>state.py:2551</code> | DRIFTED | <code>lua/core/session.lua:283-285</code> | <code>"r": 255, "g": 200, "b": 60,</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. |
| 356 | <code>state.py:2385</code> | DRIFTED | <code>server/state.py:2984-2995</code> | <code>for record in records:</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. |
| 356 | <code>state.py:1524 (continuation)</code> | DRIFTED | <code>server/state.py:2984-2995</code> | <code>log.error(f"restored trade {saved.get('token')} names no link; dropped: {saved}")</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. |
| 356 | <code>state.py:1607 (continuation)</code> | DRIFTED | <code>server/state.py:2984-2995</code> | <code>[blank line]</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. |
| 356 | <code>state.py:1734 (continuation)</code> | DRIFTED | <code>server/state.py:2984-2995</code> | <code>if dropped:</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. |
| 358 † | <code>state.py:1796</code> | DRIFTED | <code>lua/core/session.lua:289-290</code> | <code>self.queued_commands[pid].append({"cmd": "play_sound", "sound": 25})   # SE_SUCCESS</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. Gen 1 can map 25 to NOTIFY, not invariably code 1 (lua/gen1/panel.lua:17-20 and sfx_code_for). |
| 358 † | <code>state.py:1122</code> | DRIFTED | <code>server/state.py:1796</code> | <code>choice = 0</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. Gen 1 can map 25 to NOTIFY, not invariably code 1 (lua/gen1/panel.lua:17-20 and sfx_code_for). |
| 358 † | <code>state.py:1236 (continuation)</code> | DRIFTED | <code>server/state.py:1796</code> | <code>if msg.get("ok") is not True:</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. Gen 1 can map 25 to NOTIFY, not invariably code 1 (lua/gen1/panel.lua:17-20 and sfx_code_for). |
| 358 † | <code>state.py:1245 (continuation)</code> | DRIFTED | <code>server/state.py:1796</code> | <code># release this wait, and _execute_trade revalidates the whole pair then.</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. Gen 1 can map 25 to NOTIFY, not invariably code 1 (lua/gen1/panel.lua:17-20 and sfx_code_for). |
| 358 † | <code>state.py:1318 (continuation)</code> | DRIFTED | <code>server/state.py:1796</code> | <code>or pt["b_key"] in self.party_keys["a"]))):</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. Gen 1 can map 25 to NOTIFY, not invariably code 1 (lua/gen1/panel.lua:17-20 and sfx_code_for). |
| 358 † | <code>state.py:1391-1392 (continuation)</code> | DRIFTED | <code>server/state.py:1796</code> | <code>pt.setdefault("hello_only", {})[player_id] = True</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. Gen 1 can map 25 to NOTIFY, not invariably code 1 (lua/gen1/panel.lua:17-20 and sfx_code_for). |
| 358 † | <code>state.py:1423 (continuation)</code> | DRIFTED | <code>server/state.py:1796</code> | <code>outgoing key gone + the incoming key (or ONE unindexed descendant: same OT per the</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. Gen 1 can map 25 to NOTIFY, not invariably code 1 (lua/gen1/panel.lua:17-20 and sfx_code_for). |
| 358 † | <code>state.py:1444 (continuation)</code> | DRIFTED | <code>server/state.py:1796</code> | <code>int(m.get("species_id") or 0))]</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. Gen 1 can map 25 to NOTIFY, not invariably code 1 (lua/gen1/panel.lua:17-20 and sfx_code_for). |
| 358 † | <code>state.py:1468 (continuation)</code> | DRIFTED | <code>server/state.py:1796</code> | <code>if v["a"] == v["b"] == "traded":</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. Gen 1 can map 25 to NOTIFY, not invariably code 1 (lua/gen1/panel.lua:17-20 and sfx_code_for). |
| 358 † | <code>state.py:1522 (continuation)</code> | DRIFTED | <code>server/state.py:1796</code> | <code>index = saved.get("link_index")</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. Gen 1 can map 25 to NOTIFY, not invariably code 1 (lua/gen1/panel.lua:17-20 and sfx_code_for). |
| 358 † | <code>state.py:1598-1599 (continuation)</code> | DRIFTED | <code>server/state.py:1796</code> | <code>return {"phase": pt["phase"], "token": pt["token"], "a_key": pt["a_key"], "b_key": pt["b_key"],</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. Gen 1 can map 25 to NOTIFY, not invariably code 1 (lua/gen1/panel.lua:17-20 and sfx_code_for). |
| 358 † | <code>state.py:1637-1638 (continuation)</code> | DRIFTED | <code>server/state.py:1796</code> | <code>elif v[pid] in ("traded", "none"):</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. Gen 1 can map 25 to NOTIFY, not invariably code 1 (lua/gen1/panel.lua:17-20 and sfx_code_for). |
| 358 † | <code>state.py:1947 (continuation)</code> | DRIFTED | <code>server/state.py:1796</code> | <code>if isinstance(r, dict) and isinstance(r.get("old_key"), str)</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. Gen 1 can map 25 to NOTIFY, not invariably code 1 (lua/gen1/panel.lua:17-20 and sfx_code_for). |
| 358 † | <code>state.py:1953 (continuation)</code> | DRIFTED | <code>server/state.py:1796</code> | <code>rb = saved_rebuild.get(pid)</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. Gen 1 can map 25 to NOTIFY, not invariably code 1 (lua/gen1/panel.lua:17-20 and sfx_code_for). |
| 358 † | <code>state.py:2701 (continuation)</code> | DRIFTED | <code>server/state.py:1796</code> | <code>"cmd": "hud_show",</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. Gen 1 can map 25 to NOTIFY, not invariably code 1 (lua/gen1/panel.lua:17-20 and sfx_code_for). |
| 359 | <code>state.py:2322</code> | DRIFTED | <code>lua/core/session.lua:291-294</code> | <code>else:</code> |
| 359 | <code>state.py:2093-2114</code> | DRIFTED | <code>server/state.py:2318-2326</code> | <code>f"incoming_ot={incoming_ot[:8]}  result=ok")</code> |
| 360 | <code>state.py:2491</code> | DRIFTED | <code>lua/core/session.lua:295-296</code> | <code>})</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. |
| 360 | <code>state.py:2311</code> | DRIFTED | <code>server/state.py:2984-2995</code> | <code>for area_id, status in self.area_states.items():</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. |
| 360 | <code>state.py:1330 (continuation)</code> | DRIFTED | <code>server/state.py:2984-2995</code> | <code>watchdog (_tick_pending_trade) moves a side that never reports to UNCERTAIN: its next</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. |
| 360 | <code>state.py:1380 (continuation)</code> | DRIFTED | <code>server/state.py:2984-2995</code> | <code>return                                      # already decided (a replayed report)</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. |
| 360 | <code>state.py:1529 (continuation)</code> | DRIFTED | <code>server/state.py:2984-2995</code> | <code>pt.setdefault("verdict", {"a": None, "b": None})</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. |
| 360 | <code>state.py:1614 (continuation)</code> | DRIFTED | <code>server/state.py:2984-2995</code> | <code>(a conflict reason such as "holds NEITHER") is never filled: the admin names that side's</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. |
| 360 | <code>state.py:1741 (continuation)</code> | DRIFTED | <code>server/state.py:2984-2995</code> | <code>return</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. |
| 360 | <code>state.py:1867 (continuation)</code> | DRIFTED | <code>server/state.py:2984-2995</code> | <code>if saved_rules:</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. |
| 360 | <code>state.py:1882 (continuation)</code> | DRIFTED | <code>server/state.py:2984-2995</code> | <code>state.artifact_kind = data.get("artifact_kind", "")</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. |
| 363 | <code>state.py:3817</code> | DRIFTED | <code>lua/core/session.lua:324-325</code> | <code>"cmd":  "rebuild_start",</code> |
| 363 | <code>state.py:3628-3632</code> | DRIFTED | <code>server/state.py:3816-3820</code> | <code>- Mons with pending box_mon/party_mon/memorialize (in-flight; reconciling</code> |
| 364 | <code>state.py:3840</code> | DRIFTED | <code>lua/core/session.lua:326-327</code> | <code>self.queued_commands[player_id].append({"cmd": "rebuild_done"})</code> |
| 364 | <code>state.py:3656</code> | DRIFTED | <code>server/state.py:3840</code> | <code>self._expire_inflight(player_id)</code> |
| 365 | <code>state.py:1373-1804</code> | DRIFTED | <code>lua/gen3/client.lua:1769-1837</code> | <code>new_species = int(msg.get("new_species", 0) or 0)</code> |
| 365 | <code>state.py:3690-3713</code> | DRIFTED | <code>lua/gen3/native.lua:1040-1120</code> | <code>if (partner_mon and partner_mon.key not in self.party_keys[partner]</code> |
| 365 | <code>state.py:4466-4529</code> | DRIFTED | <code>server/state.py:4522-4595</code> | <code>is bounded.  Empty input clears the cache (treated as "partner went</code> |
| 366 | <code>state.py:991</code> | DRIFTED | <code>lua/gen3/native.lua:947-967</code> | <code>"cmd": "show_choices", "token": token, "options": ["Trade", "Say hey"], "text": text})</code> |
| 366 | <code>state.py:3376-3384</code> | DRIFTED | <code>lua/gen3/native.lua:1245-1254</code> | <code>c for c in self.queued_commands[partner]</code> |
| 366 | <code>state.py:778-779</code> | DRIFTED | <code>server/state.py:990-991</code> | <code>the overlays read SLinkServer's separate hello/tick badge bitmask; this 0-8 count is</code> |
| 367 | <code>state.py:1104</code> | DRIFTED | <code>lua/gen3/native.lua:939-946</code> | <code>prompt = {"cmd": "show_menu", "token": pt["token"],</code> |
| 367 | <code>state.py:3376-3384</code> | DRIFTED | <code>lua/gen3/native.lua:1245-1254</code> | <code>c for c in self.queued_commands[partner]</code> |
| 367 | <code>state.py:886-888</code> | DRIFTED | <code>server/state.py:1104-1109</code> | <code>self.pending_trade = None</code> |
| 368 | <code>state.py:1081</code> | DRIFTED | <code>lua/gen3/native.lua:968-973</code> | <code>self.queued_commands[player_id].append({"cmd": "choose_mon", "token": pt["token"]})</code> |
| 368 | <code>state.py:3385-3388</code> | DRIFTED | <code>lua/gen3/native.lua:1245-1254</code> | <code>self._save()</code> |
| 368 | <code>state.py:834</code> | DRIFTED | <code>server/state.py:1081</code> | <code># Because the link is only mutated ATOMICALLY in _handle_trade_done (once BOTH sides report), an</code> |
| 368 | <code>606 [server/state.py]</code> | DRIFTED | <code>server/state.py:1081</code> | <code>self.party_size[player_id] = max(0, self.party_size.get(player_id, 0) - 1)</code> |
| 372 † | <code>state.py:853</code> | DRIFTED | <code>lua/gen3/client.lua:1941-1971</code> | <code>pt.setdefault("verdict", {"a": None, "b": None})</code> — Current Gen 3 refuses unavailable durable native trade; no raw-slot fallback (client.lua:1941-1970). |
| 372 † | <code>state.py:3388-3460</code> | DRIFTED | <code>lua/gen3/trade.lua:409-490</code> | <code>"""</code> — Current Gen 3 refuses unavailable durable native trade; no raw-slot fallback (client.lua:1941-1970). |
| 372 † | <code>state.py:1044-1075</code> | DRIFTED | <code>lua/gen3/trade.lua:149-190</code> | <code>try:</code> — Current Gen 3 refuses unavailable durable native trade; no raw-slot fallback (client.lua:1941-1970). |
| 372 † | <code>state.py:1036-1041</code> | DRIFTED | <code>server/state.py:1324-1355</code> | <code>"""The initiator picked a party slot. Enforce the linked-pair invariant: the slot MUST be one</code> — Current Gen 3 refuses unavailable durable native trade; no raw-slot fallback (client.lua:1941-1970). |
| 373 † | <code>state.py:1938-1941</code> | DRIFTED | <code>lua/gen3/client.lua:2069</code> | <code># Restore pending bonus encounters (FIFO queue per player)</code> — Current Gen 3 consumes ghost_pos without rendering (lua/gen3/client.lua:2069). |
| 373 † | <code>state.py:717-750</code> | OK | <code>server/state.py:717-750</code> | <code>def _handle_ghost_pos(self, player_id: str, msg: dict):</code> — Current Gen 3 consumes ghost_pos without rendering (lua/gen3/client.lua:2069). |
| 374 | <code>server.py:1111-1119</code> | DRIFTED | <code>lua/gen3/native.lua:1175-1184</code> | <code>groups.append(bucket)</code> |
| 374 | <code>server.py:153-168</code> | DRIFTED | <code>lua/gen3/native.lua:1122-1173</code> | <code>lines    = [disp + (f" @ {item}" if item else "")]</code> |
| 374 | <code>server.py:1909</code> | DRIFTED | <code>server/server.py:2620-2625</code> | <code>cached = self._mon_cache.get(mon.key, {})</code> |
| 374 | <code>3157-3162 [server/server.py]</code> | DRIFTED | <code>server/server.py:2620-2625</code> | <code>"body_class":   "board mgr",</code> |
| 377 | <code>lua/core/session.lua:304</code> | DRIFTED | <code>lua/core/session.lua:304-308</code> | <code>local a = identity.pending</code> |
| 377 | <code>lua/core/session.lua:374</code> | DRIFTED | <code>lua/core/session.lua:374-375</code> | <code>local published = send("tick", f)</code> |
| 377 | <code>lua/core/session.lua:341</code> | DRIFTED | <code>lua/core/session.lua:341-342</code> | <code>if complete and gen and gen &gt; a.retry_gen then</code> |
| 398 | <code>lua/gb_panel.lua:198-236</code> | DRIFTED | <code>lua/gb_panel.lua:239-276</code> | <code>local pages = math.ceil(n / PAGE_ROWS)</code> |
| 398 | <code>lua/gen1/panel.lua:1-10</code> | OK | <code>lua/gen1/panel.lua:1-10</code> | <code>-- lua/gen1/panel.lua — the Gen 1 binder onto lua/gb_panel.lua (P4.1d): the client paints,</code> |
| 400 | <code>lua/gen1/panel.lua:13-35</code> | OK | <code>lua/gen1/panel.lua:13-35</code> | <code>-- through profile.trade.mailbox (PLAN A4: pureRGB's is linker-placed in the bank-1 tail,</code> |
| 400 | <code>lua/gb_panel.lua:97-106</code> | DRIFTED | <code>lua/gb_panel.lua:126-136</code> | <code>-- interval; the predicate takes an optional length so it answers for either convention.</code> |
| 402 | <code>lua/gb_panel.lua:198-236</code> | DRIFTED | <code>lua/gb_panel.lua:239-276</code> | <code>local pages = math.ceil(n / PAGE_ROWS)</code> |
| 404 † | <code>lua/gb_panel.lua:73-79</code> | DRIFTED | <code>lua/gb_panel.lua:98-108</code> | <code>-- PAGES-then-STATE publication order. The host never needs a line-break code; the ROM's own</code> — Shared allow also admits SFX and optional attribute/text regions (lua/gb_panel.lua:98-108). |
| 404 † | <code>lua/gb_panel.lua:187-196</code> | DRIFTED | <code>lua/gb_panel.lua:218-236</code> | <code>return nil, "panel rows exceed " .. (PAGE_ROWS * MAX_PAGES) .. " (" .. MAX_PAGES .. " pages)"</code> — Shared allow also admits SFX and optional attribute/text regions (lua/gb_panel.lua:98-108). |
| 412 † | <code>state.py:778-779</code> | DRIFTED | <code>server/state.py:990-991</code> | <code>the overlays read SLinkServer's separate hello/tick badge bitmask; this 0-8 count is</code> — UI op timeouts are 2400 frames; 1800 is the sync default (lua/gen3/native.lua:183-197). |
| 412 † | <code>state.py:981-997</code> | DRIFTED | <code>server/state.py:1140-1167</code> | <code># Native multichoice list — the proper menu with labelled options. text is spoken by whoever</code> — UI op timeouts are 2400 frames; 1800 is the sync default (lua/gen3/native.lua:183-197). |
| 412 † | <code>lua/gen3/native.lua:176-182</code> | DRIFTED | <code>lua/gen3/native.lua:183-197</code> | <code>-- post-conditions awaited after an ACK (the rival swap's engine snapshot)</code> — UI op timeouts are 2400 frames; 1800 is the sync default (lua/gen3/native.lua:183-197). |
| 412 † | <code>lua/gen3/native.lua:924-959 (continuation)</code> | DRIFTED | <code>lua/gen3/native.lua:939-973</code> | <code>on_publish=function()</code> — UI op timeouts are 2400 frames; 1800 is the sync default (lua/gen3/native.lua:183-197). |
| 413 | <code>state.py:991</code> | DRIFTED | <code>server/state.py:1161</code> | <code>"cmd": "show_choices", "token": token, "options": ["Trade", "Say hey"], "text": text})</code> |
| 413 | <code>state.py:834</code> | DRIFTED | <code>server/state.py:1071-1082</code> | <code># Because the link is only mutated ATOMICALLY in _handle_trade_done (once BOTH sides report), an</code> |
| 413 | <code>state.py:796-803</code> | DRIFTED | <code>server/state.py:1044-1052</code> | <code>for be in sorted(self.partner_blobs.get(player_id, []), key=lambda e: e.get("slot", 99)):</code> |
| 413 | <code>state.py:805-835</code> | DRIFTED | <code>server/state.py:1071-1082</code> | <code>par_be = next((e for e in par_blobs if e.get("key") == par_mon.key), None)</code> |
| 414 | <code>state.py:886-888</code> | DRIFTED | <code>server/state.py:1104-1109</code> | <code>self.pending_trade = None</code> |
| 414 | <code>state.py:1001-1008</code> | DRIFTED | <code>server/state.py:1184-1210</code> | <code>self.queued_commands[player_id].append({"cmd": "trade_mask", "mask": mask})</code> |
| 416 | <code>state.py:767</code> | DRIFTED | <code>server/state.py:974-975</code> | <code>self.queued_commands[partner].append({</code> |
| 416 | <code>state.py:787</code> | DRIFTED | <code>server/state.py:1040-1043</code> | <code>"""(slot, key, entry, partner_blob) for each of the player's party mons that is one half of a</code> |
| 416 | <code>state.py:789</code> | DRIFTED | <code>server/state.py:1117-1142</code> | <code>mons that may be traded. Sorted by party slot. This is the linked-pair invariant's source set."""</code> |
| 416 | <code>lua/gen3/native.lua:924-959</code> | DRIFTED | <code>lua/gen3/native.lua:939-973</code> | <code>on_publish=function()</code> |
| 416 | <code>588 [server/state.py]</code> | DRIFTED | <code>server/state.py:1117-1142</code> | <code>elif event == "party_to_box":</code> |
| 416 | <code>597 [server/state.py]</code> | DRIFTED | <code>server/state.py:1117-1142</code> | <code># Decrement party_size immediately so box_to_party full-party checks use the current</code> |
| 416 | <code>614 [server/state.py]</code> | DRIFTED | <code>server/state.py:1117-1142</code> | <code>if rb and key in rb.get("queued_keys", []):</code> |
| 432 | <code>state.py:761-765</code> | DRIFTED | <code>server/state.py:965-980</code> | <code>def _notify_hey(self, player_id: str):</code> |
| 433 | <code>:516-523 [server/state.py]</code> | DRIFTED | <code>server/state.py:981-991</code> | <code>Returns commands to send back to player_id (including any queued cross-player commands).</code> |
| 433 | <code>:596-612 [server/state.py]</code> | DRIFTED | <code>server/state.py:1140-1167</code> | <code># Also mark key as no longer in party so subsequent party_to_box decisions are accurate.</code> |
| 434 | <code>state.py:1035-1070</code> | OK | <code>server/state.py:1035-1070</code> | <code>def _handle_mon_chosen(self, player_id: str, msg: dict):</code> |
| 434 | <code>state.py:1250-1267</code> | OK | <code>server/state.py:1250-1267</code> | <code>def _resume_prepared_trade_on_visible_snapshot(self):</code> |
| 435 | <code>:575-577 [server/state.py]</code> | DRIFTED | <code>server/state.py:1101-1109</code> | <code>self._handle_apply_ready(player_id, msg)</code> |
| 435 | <code>:578-580 [server/state.py]</code> | DRIFTED | <code>server/state.py:1101-1109</code> | <code>elif event == "capture":</code> |
| 437 | <code>:625-658 [server/state.py]</code> | DRIFTED | <code>server/state.py:1324-1355</code> | <code>if rb and key in rb.get("queued_keys", []):</code> |
| 437 | <code>:648-653 [server/state.py]</code> | DRIFTED | <code>server/state.py:1324-1355</code> | <code># the command, so a swap in flight does not read as a full party -- so silence</code> |
| 438 | <code>:684-727 [server/state.py]</code> | DRIFTED | <code>server/state.py:1756-1810</code> | <code>if party is not None:</code> |
| 438 | <code>:715-721 [server/state.py]</code> | DRIFTED | <code>server/state.py:1756-1810</code> | <code>return cmds if cmds else [{"cmd": "noop"}]</code> |
| 438 | <code>:724-727 [server/state.py]</code> | DRIFTED | <code>server/state.py:1756-1810</code> | <code>return</code> |
| 441 | <code>state.py:697-704</code> | DRIFTED | <code>server/state.py:699-703</code> | <code># silently breaks until something else forces correction.</code> |
| 441 | <code>state.py:838-868</code> | OK | <code>server/state.py:838-868</code> | <code>TRADE_WATCHDOG_EVENTS = 4000</code> |
| 441 | <code>state.py:1162-1201 (continuation)</code> | DRIFTED | <code>server/state.py:1250-1297</code> | <code>elif choice == 1:                              # SAY HEY → ping the partner</code> |
| 447 | <code>state.py:1035-1070</code> | OK | <code>server/state.py:1035-1070</code> | <code>def _handle_mon_chosen(self, player_id: str, msg: dict):</code> |
| 447 | <code>state.py:1250-1267</code> | OK | <code>server/state.py:1250-1267</code> | <code>def _resume_prepared_trade_on_visible_snapshot(self):</code> |
| 452 | <code>lua/gen3/trade.lua:275-369</code> | OK | <code>lua/gen3/trade.lua:275-369</code> | <code>-- A valid prepare that arrives while the native side is briefly busy (still leaving the</code> |
| 452 | <code>lua/gen3/client.lua:1595-1603</code> | DRIFTED | <code>lua/gen3/client.lua:1864-1872</code> | <code>-- frame baselines at once (a loaded save, or the script starting mid-game). After that a</code> |
| 452 | <code>lua/gen3/run.lua:277-325</code> | OK | <code>lua/gen3/run.lua:277-325</code> | <code>local function lock_cause(err)</code> |
| 452 | <code>lua/gen3/trade.lua:451-461 (continuation)</code> | OK | <code>lua/gen3/trade.lua:451-461</code> | <code>end</code> |
| 453 | <code>lua/gen3/trade.lua:409-490</code> | OK | <code>lua/gen3/trade.lua:409-490</code> | <code>function self:apply(cmd)</code> |
| 453 | <code>lua/gen3/client.lua:1659-1677</code> | DRIFTED | <code>lua/gen3/client.lua:1929-1970</code> | <code>-- battle that never begins; the next trainer's edge must still be announced. A job staged</code> |
| 453 | <code>lua/gen3/client.lua:1914-1932 (continuation)</code> | DRIFTED | <code>lua/gen3/client.lua:2190-2210</code> | <code>-- releasing trade_done. Core gates this HELLO on its field</code> |
| 454 | <code>lua/gen3/trade.lua:149-210</code> | OK | <code>lua/gen3/trade.lua:149-210</code> | <code>local function result(t)</code> |
| 454 | <code>lua/gen3/trade.lua:442-490 (continuation)</code> | OK | <code>lua/gen3/trade.lua:442-490</code> | <code>function self:tick()</code> |
| 455 | <code>lua/gen3/trade.lua:149-190</code> | OK | <code>lua/gen3/trade.lua:149-190</code> | <code>local function result(t)</code> |
| 455 | <code>lua/gen3/client.lua:1611-1652</code> | DRIFTED | <code>lua/gen3/client.lua:1887-1922</code> | <code>return</code> |
| 456 | <code>lua/gen3/client.lua:646-669</code> | DRIFTED | <code>lua/gen3/client.lua:803-827</code> | <code>end</code> |
| 456 | <code>lua/gen3/client.lua:1105-1113 (continuation)</code> | DRIFTED | <code>lua/gen3/client.lua:1270-1278</code> | <code>end</code> |
| 456 | <code>lua/gen3/client.lua:1158-1182 (continuation)</code> | DRIFTED | <code>lua/gen3/client.lua:1326-1350</code> | <code>if party then seed_known(party, "rescan"); rebaseline(party) end</code> |
| 457 | <code>lua/gen3/client.lua:1626-1652</code> | DRIFTED | <code>lua/gen3/client.lua:1895-1922</code> | <code>rescan_boxes()</code> |
| 457 | <code>lua/gen3/client.lua:1720-1756 (continuation)</code> | DRIFTED | <code>lua/gen3/client.lua:1989-2035</code> | <code>-- (a boundary fire counted and dropped, signals.lua:97-100) may have missed the boundary that</code> |
| 469 † | <code>:688-692 [server/state.py]</code> | DRIFTED | <code>server/state.py:1768-1773</code> | <code>log.debug(f"[PARTY] player={player_id}  party_size {old_size} → {len(party)}  (tick/safe)")</code> — No missing-side default is synthesized by _commit_trade; it reads pt.new (state.py:1768-1773). |
| 470 | <code>:698 [server/state.py]</code> | DRIFTED | <code>server/state.py:1764</code> | <code>self._reconcile_party_keys(player_id, party, in_battle=bool(msg.get("in_battle")))</code> |
| 471 | <code>:699-706 [server/state.py]</code> | DRIFTED | <code>server/state.py:1765-1773</code> | <code>if (event in ("hello", "tick", "safe") and "party" in msg and not msg.get("_rejected")</code> |
| 472 | <code>:708-711 [server/state.py]</code> | DRIFTED | <code>server/state.py:1774-1778</code> | <code>self._save()                                 # handed over: no longer owed after a restart</code> |
| 473 | <code>:712-722 [server/state.py]</code> | DRIFTED | <code>server/state.py:1779-1804</code> | <code>for c in cmds</code> |
| 474 | <code>:727 [server/state.py]</code> | DRIFTED | <code>server/state.py:1808-1810</code> | <code>cmd = {</code> |
| 478 | <code>lua/gen3/client.lua:646-660</code> | DRIFTED | <code>lua/gen3/client.lua:803-823</code> | <code>end</code> |
| 478 | <code>lua/gen3/client.lua:1626-1641 (continuation)</code> | DRIFTED | <code>lua/gen3/client.lua:1895-1910</code> | <code>rescan_boxes()</code> |
| 482 | <code>state.py:844-904</code> | OK | <code>server/state.py:844-904</code> | <code>def _tick_pending_trade(self):</code> |
| 496 | <code>state.py:1889-1914</code> | OK | <code>server/state.py:1889-1914</code> | <code>if saved_game_id and state.adapter.game_id != saved_game_id:</code> |
| 496 | <code>server.py:667</code> | DRIFTED | <code>server/server.py:968-1013</code> | <code>[blank line]</code> |
| 496 | <code>4279 [server/state.py]</code> | DRIFTED | <code>server/state.py:4746</code> | <code>if not name:</code> |
| 496 | <code>4059 [server/server.py]</code> | DRIFTED | <code>server/server.py:968-1013</code> | <code>ctx = self._panel_ctx(request, panel="debug", label="Debug")</code> |
| 497 | <code>state.py:2399</code> | DRIFTED | <code>server/state.py:2403</code> | <code>log.info("[%s] cleared retry areas %s on entering %s", player_id,</code> |
| 497 | <code>1990 [server/state.py]</code> | DRIFTED | <code>server/state.py:3100</code> | <code>for pid in ("a", "b"):</code> |
| 497 | <code>2650 [server/state.py]</code> | DRIFTED | <code>server/state.py:2782-2789</code> | <code>label = self._label_from_msg(msg, key)</code> |
| 498 | <code>state.py:2709</code> | DRIFTED | <code>server/state.py:2713</code> | <code># species family in an alive link OR a pending capture in another area.</code> |
| 498 | <code>2373 [server/state.py]</code> | DRIFTED | <code>server/state.py:2818</code> | <code>outstanding_picks.append(mon)</code> |
| 499 | <code>state.py:2424</code> | DRIFTED | <code>server/state.py:2426-2428</code> | <code>"""</code> |
| 500 | <code>state.py:2635</code> | DRIFTED | <code>server/state.py:2635-2641</code> | <code># Gifts/eggs link under the gift namespace so they form a standalone gift</code> |
| 502 | <code>state.py:2710-2737</code> | OK | <code>server/state.py:2710-2737</code> | <code># Don't wait for the partner to catch — reject now, unresolve the area,</code> |
| 502 | <code>2573-2734 [server/state.py]</code> | OK | <code>server/state.py:2573-2734</code> | <code>entry = LinkEntry(area_id=bonus_area_id,</code> |
| 502 | <code>3713-3743 [server/state.py]</code> | DRIFTED | <code>server/state.py:4198-4225</code> | <code>f"(ghost-party — Lua doesn't see it in party)")</code> |
| 503 | <code>state.py:4222-4223</code> | DRIFTED | <code>server/state.py:4228-4229</code> | <code>if entry.b and entry.b.species and self.adapter.evo_family(entry.b.species) == a_base:</code> |
| 503 | <code>server.py:2038</code> | DRIFTED | <code>server/server.py:2121</code> | <code>dirty = False</code> |
| 503 | <code>2267 [server/server.py]</code> | DRIFTED | <code>server/server.py:2121</code> | <code># STOP HERE. Recording the verdict was not enough: control used to fall</code> |
| 504 | <code>state.py:819</code> | OK | <code>server/state.py:819</code> | <code>return (("species_id" not in e or self.adapter.species_types(e["species_id"]) is not None)</code> |
| 504 | <code>3754-3755 [server/state.py]</code> | DRIFTED | <code>server/state.py:4234-4244</code> | <code>partner_size_start = self._linked_party_size(partner)</code> |
| 506 | <code>state.py:2060</code> | OK | <code>server/state.py:2060</code> | <code>incoming_ot = self.adapter.parse_ot_id(first_key)</code> |
| 506 | <code>667-679 [server/adapters/base.py]</code> | DRIFTED | <code>server/adapters/base.py:739-751</code> | <code>Used to work out how many overflow boxes the memorial needs. It was a bare 30</code> |
| 507 | <code>681-695 [server/adapters/base.py]</code> | DRIFTED | <code>server/adapters/base.py:753-767</code> | <code>"""</code> |
| 509 | <code>state.py:4243</code> | OK | <code>server/state.py:4243</code> | <code>shared_names = ", ".join(sorted(self.adapter.type_name(t) for t in shared))</code> |
| 510 | <code>state.py:4632</code> | OK | <code>server/state.py:4632</code> | <code>rival_ids = self.adapter.rival_trainer_ids() if self.adapter else set()</code> |
| 511 | <code>state.py:4492</code> | OK | <code>server/state.py:4492</code> | <code>expected = self.adapter.party_blob_size()</code> |
| 512 | <code>server.py:132</code> | OK | <code>server/server.py:132</code> | <code>has_ability = adapter.supports_abilities()</code> |
| 513 | <code>server.py:1315</code> | DRIFTED | <code>server/server.py:1398</code> | <code># condition pulled from the xlsx ("If Lv ≥ 27", "If Lv ≥ 44", …).</code> |
| 513 | <code>1813 [server/server.py]</code> | DRIFTED | <code>server/server.py:1925</code> | <code># across connections dropped the first message of the next one.</code> |
| 513 | <code>633-653 [server/adapters/base.py]</code> | DRIFTED | <code>server/adapters/base.py:705-725</code> | <code>return ""</code> |
| 514 | <code>server.py:882</code> | DRIFTED | <code>server/server.py:965</code> | <code>"reason": f"the contract names no cartridge for player {player_id}"}</code> |
| 514 | <code>1851 [server/server.py]</code> | DRIFTED | <code>server/server.py:1963</code> | <code>self._client_connections.discard(writer)</code> |
| 515 | <code>server.py:876</code> | DRIFTED | <code>server/server.py:959</code> | <code># pin for this player, exactly. It applies even when the contract also carries a fingerprint</code> |
| 516 | <code>state.py:4307</code> | OK | <code>server/state.py:4307</code> | <code># immediate forceFaint for bench mons).  When off — or when the</code> |
| 522 | <code>server.py:635</code> | DRIFTED | <code>server/server.py:646-654</code> | <code>self._backup_task: asyncio.Task &#124; None = None</code> |
| 523 | <code>server.py:134</code> | OK | <code>server/server.py:134</code> | <code>or adapter.ability_name(detail.get("ability_id", 0), sid)</code> |
| 523 | <code>2739 [server/server.py]</code> | DRIFTED | <code>server/server.py:2905-2906</code> | <code>to OBSController.submit_fired() for priority-ordered scene resolution.</code> |
| 525 | <code>server.py:2444</code> | DRIFTED | <code>server/server.py:2532-2539</code> | <code># Enrich msg with cached battle-state killer info for state machine killfeed tracking.</code> |
| 526 | <code>server.py:137</code> | OK | <code>server/server.py:137</code> | <code>item     = adapter.calc_name("item", adapter.item_name(item_id)) if item_id else ""</code> |
| 526 | <code>2741 [server/server.py]</code> | DRIFTED | <code>server/server.py:2907-2908</code> | <code>Rules are evaluated in list order — the first matching rule per target player</code> |
| 526 | <code>2753 [server/server.py]</code> | DRIFTED | <code>server/server.py:2919-2920</code> | <code>now_battle = self.battle_state[player_id]["in_battle"]</code> |
| 527 | <code>state.py:2914</code> | DRIFTED | <code>server/state.py:2920</code> | <code>else:</code> |
| 527 | <code>server.py:1852</code> | DRIFTED | <code>server/server.py:1935</code> | <code>for player_id, writers in list(self._client_writers.items()):</code> |
| 527 | <code>2748 [server/state.py]</code> | DRIFTED | <code>server/state.py:3198</code> | <code>f"same family as existing {dup_name} — rejecting in {area_id}"</code> |
| 527 | <code>4114 [server/server.py]</code> | DRIFTED | <code>server/server.py:2958-2968</code> | <code>async def handle_obs_triggers(self, request):</code> |
| 532 | <code>server.py:815</code> | DRIFTED | <code>server/server.py:903</code> | <code>return refused</code> |
| 533 | <code>server.py:658</code> | DRIFTED | <code>server/server.py:688-712</code> | <code>"Surfing":    "🌊",</code> |
| 533 | <code>server.py:670-681</code> | DRIFTED | <code>server/server.py:688-712</code> | <code>to the shipped tables would print retail species beside a randomized cartridge,</code> |
| 534 | <code>server.py:1369</code> | DRIFTED | <code>server/server.py:1445-1453</code> | <code>f'&lt;use href="#i-swords"/&gt;&lt;/svg&gt; Upcoming Key Trainers&lt;/summary&gt;'</code> |
| 535 | <code>server.py:972</code> | DRIFTED | <code>server/server.py:1055</code> | <code>per-player data: Gen 2's three titles share one pairing foundation but not one</code> |
| 535 | <code>server.py:981</code> | DRIFTED | <code>server/server.py:1065</code> | <code>and a player whose key matches the run's again drops the adapter it had.</code> |
| 535 | <code>3087 [server/server.py]</code> | DRIFTED | <code>server/server.py:3261</code> | <code># The wild mon a side met but did not catch (dead zones only).</code> |
| 537 | <code>server.py:141</code> | OK | <code>server/server.py:141</code> | <code>name = adapter.move_name(m) if isinstance(m, int) else m</code> |
| 537 | <code>2708 [server/server.py]</code> | DRIFTED | <code>server/server.py:2875</code> | <code>if msg.get("_rejected"):</code> |
| 538 | <code>server/ui_capabilities.py:30</code> | OK | <code>server/ui_capabilities.py:30</code> | <code>"stat_stage_labels": adapter.stat_stage_labels(),</code> |
| 539 | <code>server.py:5044</code> | DRIFTED | <code>server/server.py:5135-5140</code> | <code># Closed clients reconnect and re-hello; no open socket can silently lose events</code> |
| 542 | <code>160 [server/server.py]</code> | DRIFTED | <code>server/server.py:143</code> | <code>lines.append(f"- {m}")</code> |
| 542 | <code>166 [server/server.py]</code> | DRIFTED | <code>server/server.py:133-143</code> | <code>"nature":        nature,</code> |
| 543 | <code>server.py:128</code> | OK | <code>server/server.py:128</code> | <code>species = adapter.calc_species(sid)</code> |
| 544 | <code>server.py:934-936</code> | DRIFTED | <code>server/server.py:1015-1019</code> | <code>message itself, so a client whose first line is a capture (a reconnect after a</code> |
| 544 | <code>manager.py:265</code> | DRIFTED | <code>server/manager.py:289-322</code> | <code>[blank line]</code> |
| 544 | <code>1284 [server/server.py]</code> | DRIFTED | <code>server/server.py:1379</code> | <code># spreadsheet author's stated trigger condition. Falls back</code> |
| 545 | <code>server.py:131</code> | OK | <code>server/server.py:131</code> | <code>nature = adapter.calc_nature(key)</code> |
| 546 | <code>2019 [server/server.py]</code> | DRIFTED | <code>server/server.py:208</code> | <code>self._mon_cache[key] = entry</code> |
| 552 † | <code>server/adapters/__init__.py:42-86</code> | DRIFTED | <code>server/adapters/__init__.py:38-94</code> | <code>"emerald_expansion_28877d73": "gen3_exp",</code> — Unknown/refused ROM types are refused at hello, not silently retained (server.py:1739-1748). |
| 552 † | <code>106-111 [server/adapters/__init__.py]</code> | DRIFTED | <code>server/adapters/__init__.py:126-143</code> | <code>"Red": "Red", "Blue": "Blue", "Yellow": "Yellow",</code> — Unknown/refused ROM types are refused at hello, not silently retained (server.py:1739-1748). |
| 553 | <code>server.py:2156-2165</code> | DRIFTED | <code>server/server.py:2225-2263</code> | <code>log.error("[%s] failed to dispatch %s", player_id, msg.get("event", "unknown"), exc_info=True)</code> |
| 554 | <code>server.py:2162-2163</code> | DRIFTED | <code>server/server.py:2231-2240</code> | <code>malformed = self.state.normalize_party_snapshot(player_id, msg)</code> |
| 554 | <code>server/adapters/__init__.py:24-32</code> | DRIFTED | <code>server/adapters/__init__.py:19-26</code> | <code>"""</code> |
| 555 | <code>state.py:1885-1914</code> | OK | <code>server/state.py:1885-1914</code> | <code>state.is_rr = True</code> |
| 556 | <code>216-218 [server/adapters/__init__.py]</code> | DRIFTED | <code>server/adapters/__init__.py:265-267</code> | <code>"firered_ap": "gen3_frlg", "leafgreen_ap": "gen3_frlg",</code> |
| 566 | <code>state.py:1796</code> | OK | <code>server/state.py:1796</code> | <code>self.queued_commands[pid].append({"cmd": "play_sound", "sound": 25})   # SE_SUCCESS</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. |
| 566 | <code>state.py:2094 (continuation)</code> | DRIFTED | <code>server/state.py:2465</code> | <code># Update trainer name if it changed (e.g. first connect had no name)</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. |
| 566 | <code>state.py:2103 (continuation)</code> | DRIFTED | <code>server/state.py:2465</code> | <code>"trainer_name": incoming_name or player_id.upper(),</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. |
| 566 | <code>state.py:2176 (continuation)</code> | DRIFTED | <code>server/state.py:2465</code> | <code>_e = self.entry_for(player_id, _k)</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. |
| 566 | <code>state.py:2249-2250 (continuation)</code> | DRIFTED | <code>server/state.py:2465</code> | <code>half = entry and (entry.a if player_id == "a" else entry.b)</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. |
| 566 | <code>state.py:2281 (continuation)</code> | DRIFTED | <code>server/state.py:2465</code> | <code>log.warning(f"[{player_id}] hello: {key[:8]} is dead/memorial but in party — re-memorializing")</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. |
| 566 | <code>state.py:2302 (continuation)</code> | DRIFTED | <code>server/state.py:2465</code> | <code>if sid and mon.species != sid:</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. |
| 566 | <code>state.py:2326 (continuation)</code> | DRIFTED | <code>server/state.py:2465</code> | <code>})</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. |
| 566 | <code>state.py:2388 (continuation)</code> | DRIFTED | <code>server/state.py:2465</code> | <code>def _adapter_for(self, player_id: str):</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. |
| 566 | <code>state.py:2464-2465 (continuation)</code> | DRIFTED | <code>server/state.py:2465</code> | <code># Capturing player: shiny sound + prominent GUI prompt</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. |
| 566 | <code>state.py:2509-2510 (continuation)</code> | DRIFTED | <code>server/state.py:2465</code> | <code># ── Pending bonus encounter ─────────────────────────────────────────────────</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. |
| 566 | <code>state.py:2828 (continuation)</code> | DRIFTED | <code>server/state.py:2465</code> | <code>self.party_keys[reject_pid].discard(reject_key)</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. |
| 566 | <code>state.py:2835 (continuation)</code> | DRIFTED | <code>server/state.py:2465</code> | <code># Area stays pending — waiting for the violating player to retry</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. |
| 566 | <code>state.py:3920 (continuation)</code> | DRIFTED | <code>server/state.py:2465</code> | <code>collision = ""</code> — Current representative site; collapse repeated historical site enumeration rather than duplicate this cite. |
| 567 | <code>state.py:777</code> | DRIFTED | <code>server/state.py:989</code> | <code>"""Cache a player's in-game progress (badge count). NOTE: nothing consumes this yet —</code> |
| 568 | <code>state.py:833</code> | DRIFTED | <code>server/state.py:989</code> | <code># while the trade makes NO progress (each trade handler resets it to 0); past this many, abandon.</code> |
| 568 | <code>642 [server/state.py]</code> | DRIFTED | <code>server/state.py:989</code> | <code>"r": 255, "g": 200, "b": 60</code> |
| 569 | <code>state.py:2282</code> | DRIFTED | <code>server/state.py:2461</code> | <code>[blank line]</code> |
| 569 | <code>state.py:1386-1387 (continuation)</code> | DRIFTED | <code>server/state.py:2461</code> | <code># the side cannot vouch (a reset after its commit entry, a native result 2): party evidence</code> |
| 570 | <code>base.py:608-619</code> | DRIFTED | <code>server/adapters/base.py:705-725</code> | <code>Default None.</code> |
| 572 | <code>server.py:3765-3783</code> | DRIFTED | <code>server/server.py:2866-2888</code> | <code>"a": {</code> |
| 573 | <code>state.py:1847-1850</code> | DRIFTED | <code>server/state.py:2052-2060</code> | <code>pid: MonInfo(**mon_data)</code> |
| 574 | <code>state.py:4043-4135</code> | DRIFTED | <code>server/state.py:4459-4518</code> | <code>rb["restored_keys"].add(new_key)</code> |
| 575 † | <code>2678-2683 [server/server.py]</code> | DRIFTED | <code>server/server.py:1935-1952</code> | <code>if event == "party_to_box":</code> — Wide panel popcounts the hello/tick bitmask now (server.py:1945-1952). |
| 575 † | <code>server.py:2991</code> | DRIFTED | <code>server/server.py:1935-1952</code> | <code># What THIS cartridge can do, so a template asks caps.abilities</code> — Wide panel popcounts the hello/tick bitmask now (server.py:1945-1952). |
| 576 | <code>server.py:1992</code> | DRIFTED | <code>server/server.py:948-966</code> | <code>return {"cmd": "link_panel", "rows": [r[:width] for r in compact]}</code> |
| 577 | <code>server.py:4101-4115</code> | GONE | <code>?</code> | <code>new_cfg["connections"][pid] = {</code> — Historical ROM_LABEL reference: label it with a historical revision or remove its line numbers. |
| 578 | <code>state.py:2727-2728</code> | DRIFTED | <code>server/state.py:2890-2902</code> | <code>dup_name = self.adapter.species_name(partner_mon.species)</code> |
| 578 | <code>2131 [server/state.py]</code> | DRIFTED | <code>server/state.py:2890-2902</code> | <code>if not (c.get("cmd") in ("apply_trade", "apply_prepare") and c.get("token") == pt["token"])]</code> |
| 578 | <code>2318-2320 [server/state.py]</code> | DRIFTED | <code>server/state.py:2890-2902</code> | <code>if resolved:</code> |
| 580 | <code>state.py:3813-3818</code> | DRIFTED | <code>server/state.py:4227-4232</code> | <code>labels = [_label(m) for m in player_picks[:3]]</code> |
| 581 | <code>state.py:2265-2324</code> | DRIFTED | <code>server/state.py:2445-2641</code> | <code># Dead/memorial mons in party → re-memorialize (handles script reload case</code> |
| 582 | <code>lua/gen3/reads.lua:19</code> | OK | <code>lua/gen3/reads.lua:19</code> | <code>R.PARTY_MON_SIZE = 100          -- sizeof(struct Pokemon)</code> |
| 583 | <code>server.py:2848</code> | DRIFTED | <code>server/server.py:2236</code> | <code>if not killer:</code> |
| 584 | <code>state.py:3694-3699</code> | DRIFTED | <code>server/state.py:3846-3856</code> | <code>if partner_mon.nickname:</code> |
| 585 | <code>server.py:3419-3427</code> | DRIFTED | <code>server/server.py:2532-2547</code> | <code>active_slots = []</code> |
| 589 | <code>server/adapters/__init__.py:79-81</code> | DRIFTED | <code>server/adapters/__init__.py:85-87</code> | <code># build actually gets a client) is Entry.admit's job at runtime, not this table's --</code> |
| 589 | <code>server/adapters/__init__.py:235-237</code> | DRIFTED | <code>server/adapters/__init__.py:179-181</code> | <code># owns it in server/server.py (PLAN §4.5 row 2).</code> |
| 594 † | <code>:303-306 [lua/gen2/client.lua]</code> | DRIFTED | <code>lua/gen2/client.lua:660-667</code> | <code>-- item-id set because its balls share the one bag list.</code> — Native show_menu is rendered when trade_live and blob/slot supplied; only fallback cancels (client.lua:660-673). |
| 594 † | <code>:412-413 [lua/gen2/client.lua]</code> | DRIFTED | <code>lua/gen2/client.lua:660-667</code> | <code>end</code> — Native show_menu is rendered when trade_live and blob/slot supplied; only fallback cancels (client.lua:660-673). |
| 594 † | <code>:452-453 [server/adapters/gen2_gsc.py]</code> | DRIFTED | <code>server/adapters/gen2_gsc.py:721-723</code> | <code>def decode_party_blob(self, blob, *, species_marker=None):</code> — Native show_menu is rendered when trade_live and blob/slot supplied; only fallback cancels (client.lua:660-673). |
| 595 | <code>lua/hud.lua:69-86</code> | OK | <code>lua/hud.lua:69-86</code> | <code>local function sanitize(s)</code> |
| 595 | <code>:375-380 [lua/gen2/client.lua]</code> | DRIFTED | <code>lua/gen2/client.lua:607-612</code> | <code>if not player then return false, "player unreadable" end</code> |
| 595 | <code>:259-260 [lua/hud.lua]</code> | DRIFTED | <code>lua/hud.lua:296-301</code> | <code>return math.max(left, math.floor((left + right - w) / 2))</code> |
| 595 | <code>:285-286 [lua/hud.lua]</code> | DRIFTED | <code>lua/hud.lua:322-327</code> | <code>end</code> |
| 596 | <code>:482 [lua/gen2/client.lua]</code> | DRIFTED | <code>lua/gen2/client.lua:1694-1698</code> | <code>-- (key fields 1-2) must name exactly one party mon, and its species must descend from the</code> |
| 596 | <code>:525 [lua/gen2/client.lua]</code> | DRIFTED | <code>lua/gen2/client.lua:1739</code> | <code>end</code> |
| 596 | <code>:570 [lua/gen2/client.lua]</code> | DRIFTED | <code>lua/gen2/client.lua:1805-1808</code> | <code>if p.battle_hold then</code> |
| 596 | <code>:154 [lua/gen2/wire.lua]</code> | OK | <code>lua/gen2/wire.lua:154</code> | <code>key = key, slot = mon.slot, species_id = mon.species_id, level = mon.level,</code> |
| 596 | <code>:188 [lua/gen2/wire.lua]</code> | OK | <code>lua/gen2/wire.lua:188</code> | <code>species_id = mon.species_id, level = mon.level, hp = mon.hp, maxHP = mon.max_hp,</code> |
| 596 | <code>:219 [lua/gen2/wire.lua]</code> | OK | <code>lua/gen2/wire.lua:219</code> | <code>box = box_index, slot = mon.slot, key = key, species_id = mon.species_id,</code> |
| 597 | <code>:155 [lua/gen2/wire.lua]</code> | OK | <code>lua/gen2/wire.lua:155</code> | <code>hp = mon.hp, maxHP = mon.max_hp, status_cond = mon.status,</code> |
| 597 | <code>:189 [lua/gen2/wire.lua]</code> | OK | <code>lua/gen2/wire.lua:189</code> | <code>status_cond = mon.status, held_item_id = mon.held_item, active = true,</code> |
| 597 | <code>:472-473 [server/adapters/gen2_gsc.py]</code> | DRIFTED | <code>server/adapters/gen2_gsc.py:743-744</code> | <code>except (ValueError, TypeError):</code> |
| 598 | <code>server/adapters/base.py:578</code> | DRIFTED | <code>server/adapters/base.py:653-661</code> | <code>adapters whose ROM text differs from the calc's names override it.</code> |
| 598 | <code>:529-560 [lua/gen2/reads.lua]</code> | OK | <code>lua/gen2/reads.lua:529-560</code> | <code>function r.read_stat_stages(side)</code> |
| 598 | <code>:24-31 [lua/gen2/wire.lua]</code> | OK | <code>lua/gen2/wire.lua:24-31</code> | <code>--   3. Stat-stage neutral-offset conversion is NOT redone here: unlike Gen 1</code> |
| 598 | <code>:113-122 [lua/gen2/wire.lua]</code> | OK | <code>lua/gen2/wire.lua:113-122</code> | <code>local function stat_stages_of(stages)</code> |
| 598 | <code>:161-165 [lua/gen2/wire.lua]</code> | OK | <code>lua/gen2/wire.lua:161-165</code> | <code>if active and stages ~= nil then</code> |
| 599 | <code>:133 [lua/gen2/reads.lua]</code> | OK | <code>lua/gen2/reads.lua:133</code> | <code>mon.pp[i], mon.pp_ups[i] = packed % 64, math.floor(packed / 64)</code> |
| 599 | <code>:520 [lua/gen2/reads.lua]</code> | OK | <code>lua/gen2/reads.lua:520</code> | <code>for i,packed in ipairs(mon.pp_raw) do mon.pp[i],mon.pp_ups[i] = packed%64,math.floor(packed/64) end</code> |
| 599 | <code>:144-147 [lua/gen2/wire.lua]</code> | OK | <code>lua/gen2/wire.lua:144-147</code> | <code>local pp = four(mon.pp)</code> |
| 599 | <code>:156 [lua/gen2/wire.lua]</code> | OK | <code>lua/gen2/wire.lua:156</code> | <code>moves = moves, pp = pp, pp_ups = pp_ups,</code> |
| 599 | <code>:190 [lua/gen2/wire.lua]</code> | OK | <code>lua/gen2/wire.lua:190</code> | <code>moves = moves, pp = pp, pp_ups = pp_ups,</code> |
| 600 | <code>:620 [lua/gen2/client.lua]</code> | DRIFTED | <code>lua/gen2/client.lua:1857</code> | <code>self.resolved_areas[cmd.area_id] = nil</code> |
| 600 | <code>:179-180 [server/adapters/gen2_gsc.py]</code> | DRIFTED | <code>server/adapters/gen2_gsc.py:333-334</code> | <code>self.title = title</code> |
| 601 | <code>:253-254 [server/adapters/gen2_gsc.py]</code> | DRIFTED | <code>server/adapters/gen2_gsc.py:449-450</code> | <code># Story caller facts remain source candidates, not permission to label a</code> |
| 601 | <code>:81-97 [lua/gen2/wire.lua]</code> | OK | <code>lua/gen2/wire.lua:81-97</code> | <code>-- The 70-byte transfer blob docs/protocol.md S4.1 requires (blob_hex,</code> |
| 602 † | <code>:698-705 [lua/gen2/client.lua]</code> | DRIFTED | <code>lua/gen2/client.lua:1956-1996</code> | <code>--   * the role is the first command of the visit (trade_mask -&gt; proposer, show_menu -&gt; responder);</code> — Native panel exists and wide badge count uses hello/tick bitmask (server.py:1945-1952). |
| 603 † | <code>:629 [lua/gen2/client.lua]</code> | DRIFTED | <code>lua/gen2/client.lua:1866</code> | <code>-- KEY-SCOPE-5: nothing was retired; the alias stays and the change is re-sent after the</code> — Panel hello fields and link_panel handler exist; adapter permits companion panels (gen2_gsc.py:717-730). |
| 603 † | <code>:419-421 [lua/gen2/client.lua]</code> | DRIFTED | <code>lua/gen2/client.lua:681-684</code> | <code>-- timeline the player left may be published on the one they resumed: queued binder batches,</code> — Panel hello fields and link_panel handler exist; adapter permits companion panels (gen2_gsc.py:717-730). |
| 603 † | <code>:449-450 [server/adapters/gen2_gsc.py]</code> | DRIFTED | <code>server/adapters/gen2_gsc.py:729-730</code> | <code>def party_blob_size(self):</code> — Panel hello fields and link_panel handler exist; adapter permits companion panels (gen2_gsc.py:717-730). |
| 603 † | <code>:458-459 [server/adapters/gen2_gsc.py]</code> | DRIFTED | <code>server/adapters/gen2_gsc.py:717-719</code> | <code>return mon</code> — Panel hello fields and link_panel handler exist; adapter permits companion panels (gen2_gsc.py:717-730). |
| 604 | <code>server/server.py:1259-1260</code> | DRIFTED | <code>server/server.py:1481-1483</code> | <code>if ability: meta_bits.append(f'&lt;span class="tr-ability"&gt;{ability}&lt;/span&gt;')   # noqa: E701</code> |
| 604 | <code>:1071-1072 [server/server.py]</code> | DRIFTED | <code>server/server.py:1466-1467</code> | <code>briefs.append((rt_id, brief))</code> |
| 605 | <code>:136 [lua/gen2/wire.lua]</code> | OK | <code>lua/gen2/wire.lua:136</code> | <code>if not is_integer(mon.slot, 0, 5) then return nil, "invalid or missing slot" end</code> |
| 607 | <code>:182-196 [server/adapters/gen2_gsc.py]</code> | DRIFTED | <code>server/adapters/gen2_gsc.py:336-350</code> | <code>_require(profile.get("schema") == "gen2-profile-v1"</code> |
| 608 | <code>:198-203 [server/adapters/gen2_gsc.py]</code> | DRIFTED | <code>server/adapters/gen2_gsc.py:352-357</code> | <code>_require(data.get("schema") == schema, f"{name}: unsupported pack schema")</code> |
| 609 | <code>:81-97 [lua/gen2/wire.lua]</code> | OK | <code>lua/gen2/wire.lua:81-97</code> | <code>-- The 70-byte transfer blob docs/protocol.md S4.1 requires (blob_hex,</code> |
| 610 | <code>server/adapters/__init__.py:73-76</code> | DRIFTED | <code>server/adapters/__init__.py:85-87</code> | <code>#</code> |
| 611 | <code>lua/gen2/signals.lua:422</code> | DRIFTED | <code>lua/gen2/signals.lua:1018-1041</code> | <code>-- A synthetic run binds to its fixture's COMMITTED disclosure (reports[&lt;fixture&gt;], shipped beside t</code> |
| 611 | <code>:567-572 [lua/gen2/client.lua]</code> | DRIFTED | <code>lua/gen2/client.lua:1801-1808</code> | <code>if not party or not slot then self.deferred[#self.deferred + 1] = entry return end</code> |
| 611 | <code>:461 [lua/gen2/signals.lua]</code> | DRIFTED | <code>lua/gen2/signals.lua:908-914</code> | <code>end</code> |
| 612 † | <code>:510-513 [lua/gen2/client.lua]</code> | DRIFTED | <code>lua/gen2/client.lua:255</code> | <code>end</code> — Trainer IDs use class*256+id; tick and trainer_battle_start send them (client.lua:255,1976,2302). |
| 612 † | <code>:701 [lua/gen2/client.lua]</code> | DRIFTED | <code>lua/gen2/client.lua:1975-1977</code> | <code>--     cartridge ending the visit (B, its own timeout, a reset): nothing was committed.</code> — Trainer IDs use class*256+id; tick and trainer_battle_start send them (client.lua:255,1976,2302). |
| 612 † | <code>:492-495 [server/adapters/gen2_gsc.py]</code> | DRIFTED | <code>server/adapters/gen2_gsc.py:763-769</code> | <code>if not isinstance(area_id, str):</code> — Trainer IDs use class*256+id; tick and trainer_battle_start send them (client.lua:255,1976,2302). |
| 613 | <code>:121 [lua/gen2/reads.lua]</code> | OK | <code>lua/gen2/reads.lua:121</code> | <code>held_item=bytes[c.MON_ITEM+1], moves=slice(bytes,c.MON_MOVES,c.NUM_MOVES),</code> |
| 613 | <code>:148 [lua/gen2/wire.lua]</code> | OK | <code>lua/gen2/wire.lua:148</code> | <code>if not is_integer(mon.held_item, 0, 255) then return nil, "invalid or missing held_item" end</code> |
| 613 | <code>:157 [lua/gen2/wire.lua]</code> | OK | <code>lua/gen2/wire.lua:157</code> | <code>held_item_id = mon.held_item, -- gen1 has no held items; see module header point 2</code> |
| 613 | <code>:186 [lua/gen2/wire.lua]</code> | OK | <code>lua/gen2/wire.lua:186</code> | <code>if not is_integer(mon.held_item, 0, 255) then return nil, "invalid or missing held_item" end</code> |
| 613 | <code>:189 [lua/gen2/wire.lua]</code> | OK | <code>lua/gen2/wire.lua:189</code> | <code>status_cond = mon.status, held_item_id = mon.held_item, active = true,</code> |
| 613 | <code>:214 [lua/gen2/wire.lua]</code> | OK | <code>lua/gen2/wire.lua:214</code> | <code>if not is_integer(mon.held_item, 0, 255) then return nil, "invalid or missing held_item" end</code> |
| 613 | <code>:220 [lua/gen2/wire.lua]</code> | OK | <code>lua/gen2/wire.lua:220</code> | <code>level = mon.level, held_item_id = mon.held_item, moves = moves,</code> |
| 613 | <code>:483 [lua/gen2/client.lua]</code> | DRIFTED | <code>lua/gen2/client.lua:1695</code> | <code>-- key's (evolutions.json), so a DV/OT collision never kills another mon. Client.key_identity</code> |
| 613 | <code>:235 [server/adapters/gen2_gsc.py]</code> | DRIFTED | <code>server/adapters/gen2_gsc.py:389-390</code> | <code>self._moves = {row["id"]: row for row in moves}</code> |
| 617 | <code>lua/core/session.lua:301</code> | DRIFTED | <code>lua/core/session.lua:321</code> | <code>-- next complete box census (a census refusal asks for that census now). Console only --</code> |
| 633 | <code>lua/core/session.lua:83-87</code> | DRIFTED | <code>lua/core/session.lua:96-99</code> | <code>local self = {</code> |
| 633 | <code>connector.lua:196</code> | OK | <code>lua/connector.lua:196</code> | <code>local line = _send_queue[1] .. "\n"</code> |
| 634 | <code>lua/core/session.lua:71</code> | DRIFTED | <code>lua/core/session.lua:84</code> | <code>[blank line]</code> |
| 634 | <code>lua/core/session.lua:83 (continuation)</code> | DRIFTED | <code>lua/core/session.lua:96</code> | <code>local self = {</code> |
| 635 | <code>lua/core/session.lua:78-81</code> | DRIFTED | <code>lua/core/session.lua:91-95</code> | <code>local net, json, hud = assert(p.net, "net"), assert(p.json, "json"), assert(p.hud, "hud")</code> |
| 636 | <code>lua/core/session.lua:362-370</code> | DRIFTED | <code>lua/core/session.lua:411-420</code> | <code>-- the census fresh on its own PC triggers), and a scan that CANNOT land -- a null storage</code> |
| 637 | <code>lua/core/session.lua:265-269</code> | DRIFTED | <code>lua/core/session.lua:272-279</code> | <code>else</code> |
| 637 | <code>lua/core/session.lua:309 (continuation)</code> | DRIFTED | <code>lua/core/session.lua:329</code> | <code>end</code> |
| 638 † | <code>connector.lua:242-247</code> | OK | <code>lua/connector.lua:242-247</code> | <code>elseif #_recv_buf + #partial &gt; MAX_LINE then</code> — Only partial-receive overflow is checked; complete-line size is not checked (connector.lua:220-247). |
| 643 | <code>lua/gen3/client.lua:1101-1156</code> | DRIFTED | <code>lua/gen3/client.lua:1266-1324</code> | <code>if battler then</code> |
| 643 | <code>server/adapters/__init__.py:42-86</code> | DRIFTED | <code>server/adapters/__init__.py:38-94</code> | <code>"emerald_expansion_28877d73": "gen3_exp",</code> |
| 644 | <code>state.py:4492-4508</code> | OK | <code>server/state.py:4492-4508</code> | <code>expected = self.adapter.party_blob_size()</code> |
| 645 | <code>state.py:1847-1850</code> | DRIFTED | <code>server/state.py:2052-2060</code> | <code>pid: MonInfo(**mon_data)</code> |
| 646 | <code>lua/gen3/client.lua:1105-1113</code> | DRIFTED | <code>lua/gen3/client.lua:1270-1278</code> | <code>end</code> |
| 648 | <code>lua/core/session.lua:285-298</code> | DRIFTED | <code>lua/core/session.lua:291-318</code> | <code>hud.prompt(cmd.text, r, g, b, f)</code> |
| 652 | <code>lua/gen3/client.lua:1158-1182</code> | DRIFTED | <code>lua/gen3/client.lua:1326-1350</code> | <code>if party then seed_known(party, "rescan"); rebaseline(party) end</code> |
| 652 | <code>lua/core/session.lua:398-400</code> | DRIFTED | <code>lua/core/session.lua:448-451</code> | <code>last_hold = line</code> |
| 655 | <code>server.py:3780-3798</code> | DRIFTED | <code>server/server.py:2866-2888</code> | <code>return {</code> |
| 657 † | <code>lua/core/session.lua:402-404</code> | DRIFTED | <code>lua/core/session.lua:452-455</code> | <code>function self:start()</code> — Gen 3 safe may carry party_hidden through its transport wrapper (client.lua:2255-2263). |
| 661 | <code>lua/gen3/client.lua:560-571</code> | DRIFTED | <code>lua/gen3/client.lua:637-650</code> | <code>end</code> |
| 662 | <code>lua/gen3/client.lua:441-500</code> | DRIFTED | <code>lua/gen3/client.lua:490-561</code> | <code>-- loses a required write; the core holds them until the real party returns or the battle</code> |
| 663 | <code>lua/gen3/client.lua:242-247</code> | DRIFTED | <code>lua/gen3/client.lua:252-257</code> | <code>end</code> |
| 664 | <code>lua/gen3/client.lua:606-623</code> | DRIFTED | <code>lua/gen3/client.lua:683-701</code> | <code>log(string.format("ACQ known via=%s key=%s old=%s species=%s (key_change, no capture)", reason, k, t</code> |
| 665 | <code>lua/core/session.lua:289-290</code> | DRIFTED | <code>lua/core/session.lua:295-296</code> | <code>elseif c == "play_sound" then</code> |
| 666 | <code>lua/gen3/client.lua:367-372</code> | DRIFTED | <code>lua/gen3/client.lua:377-382</code> | <code>if not st.boxes_ok then return nil end</code> |
| 666 | <code>lua/gen3/client.lua:399-401 (continuation)</code> | DRIFTED | <code>lua/gen3/client.lua:425-427</code> | <code>local function seed_known(party, via)</code> |
| 666 | <code>lua/gen3/client.lua:431-439 (continuation)</code> | DRIFTED | <code>lua/gen3/client.lua:480-488</code> | <code>st.has_pokeballs = true</code> |
| 667 † | <code>lua/gen3/client.lua:663-666</code> | DRIFTED | <code>lua/gen3/client.lua:824-827</code> | <code>-- is never announced again, even when its battle_begin refused the carry</code> — Whiteout is emitted from a native whiteout flag, not derived here from all HP reaching zero (client.lua:824-827). |
| 671 † | <code>lua/gen3/client.lua:502-535</code> | DRIFTED | <code>lua/gen3/client.lua:563-602</code> | <code>resolve_area()</code> — Current PC settle checks census membership, not HP&gt;0 (client.lua:563-602). |
| 672 † | <code>lua/core/deferred.lua:159-171</code> | OK | <code>lua/core/deferred.lua:159-171</code> | <code>elseif cmd.cmd == "box_mon" then</code> — stats_cache follows successful deposit, not precedes it (deferred.lua:161-168). |
| 672 † | <code>lua/gen3/boxes.lua:364-400</code> | OK | <code>lua/gen3/boxes.lua:364-400</code> | <code>function self:deposit(key, slot_hint)</code> — stats_cache follows successful deposit, not precedes it (deferred.lua:161-168). |
| 672 † | <code>state.py:567-584</code> | DRIFTED | <code>server/state.py:646-658</code> | <code>self._handle_trade_offer(player_id, msg)</code> — stats_cache follows successful deposit, not precedes it (deferred.lua:161-168). |
| 673 | <code>lua/gen3/boxes.lua:401-429</code> | OK | <code>lua/gen3/boxes.lua:401-429</code> | <code>function self:withdraw(key, stats, nickname)</code> |
| 673 | <code>lua/core/deferred.lua:172-191</code> | OK | <code>lua/core/deferred.lua:172-191</code> | <code>elseif cmd.cmd == "party_mon" then</code> |
| 674 † | <code>lua/gen3/boxes.lua:430-493</code> | OK | <code>lua/gen3/boxes.lua:430-493</code> | <code>function self:memorialize(key, slot_hint)</code> — Last-mon memorial after game_over is dropped without a done/failed reply (deferred.lua:201-206). |
| 674 † | <code>lua/core/deferred.lua:192-211</code> | OK | <code>lua/core/deferred.lua:192-211</code> | <code>elseif cmd.cmd == "memorialize" then</code> — Last-mon memorial after game_over is dropped without a done/failed reply (deferred.lua:201-206). |
| 674 † | <code>2645-2650 [lua/core/deferred.lua]</code> | GONE | <code>?</code> | <code>[outside file: 239 lines]</code> — Orphan legacy client range. Current last-mon handling is lua/core/deferred.lua:201-206. Last-mon memorial after game_over is dropped without a done/failed reply (deferred.lua:201-206). |
| 675 † | <code>lua/core/deferred.lua:74-99</code> | OK | <code>lua/core/deferred.lua:74-99</code> | <code>function Deferred:push(cmd)</code> — Held last-mon memorials and full-party retrievals requeue at tail; strict FIFO needs qualification. |
| 675 † | <code>lua/core/deferred.lua:116-130 (continuation)</code> | OK | <code>lua/core/deferred.lua:116-130</code> | <code>if #self.items == 0 then self.hold = nil; return false end</code> — Held last-mon memorials and full-party retrievals requeue at tail; strict FIFO needs qualification. |
| 675 † | <code>2634-2716 [lua/core/deferred.lua]</code> | GONE | <code>?</code> | <code>[outside file: 239 lines]</code> — Orphan legacy client range. Current push/run are lua/core/deferred.lua:74-99,115-130. Held last-mon memorials and full-party retrievals requeue at tail; strict FIFO needs qualification. |
| 676 | <code>lua/core/deferred.lua:123-130</code> | OK | <code>lua/core/deferred.lua:123-130</code> | <code>local function find(key)</code> |
| 681 | <code>state.py:4314</code> | OK | <code>server/state.py:4314</code> | <code>cmd_name = "force_explode" if explode else "force_faint"</code> |
| 682 | <code>lua/core/session.lua:299-303</code> | DRIFTED | <code>lua/core/session.lua:319-323</code> | <code>elseif c == "key_change_rejected" and RETRYABLE_REJECTIONS[cmd.reason] then</code> |
| 686 | <code>state.py:3666-3679</code> | DRIFTED | <code>server/state.py:3846-4089</code> | <code># Ghost-boxed: Lua reports key in party, server thinks it's deposited.</code> |
| 687 † | <code>lua/gen3/client.lua:540-558</code> | DRIFTED | <code>lua/gen3/client.lua:604-635</code> | <code>-- the signal named an acquisition but every party and boxed key was already known: nothing is repor</code> — Nature changes can alter PID and emit nature_change (client.lua:626-634,1573-1587). |
| 688 † | <code>state.py:3780-3782</code> | DRIFTED | <code>server/state.py:4175-4190</code> | <code>soft informational HUD for the partner.</code> — Equal cross-player keys are permitted; collision check is per-player (state.py:4180-4189). |
| 694 | <code>lua/gen3/native.lua:924-959</code> | DRIFTED | <code>lua/gen3/native.lua:939-973</code> | <code>on_publish=function()</code> |
| 695 | <code>lua/gen3/native.lua:1245-1265</code> | DRIFTED | <code>lua/gen3/native.lua:1264-1279</code> | <code>local reason = status == FAIL and io.read_u16(p.BASE + O.reason) or nil</code> |
| 696 | <code>lua/gen3/trade.lua:149-190</code> | OK | <code>lua/gen3/trade.lua:149-190</code> | <code>local function result(t)</code> |
| 697 | <code>lua/gen3/client.lua:646-660</code> | DRIFTED | <code>lua/gen3/client.lua:803-823</code> | <code>end</code> |
| 698 | <code>lua/gen3/client.lua:1033-1044</code> | DRIFTED | <code>lua/gen3/client.lua:1194-1205</code> | <code>end</code> |
| 702 | <code>lua/gen3/client.lua:575-604</code> | DRIFTED | <code>lua/gen3/client.lua:652-681</code> | <code>for k, prev in pairs(st.carried) do</code> |
| 703 | <code>lua/gen3/native.lua:1025-1106</code> | DRIFTED | <code>lua/gen3/native.lua:1040-1120</code> | <code>local rr = profile.titles and profile.titles[deps.title or "radical_red"]</code> |
| 703 | <code>lua/gen3/client.lua:1500-1567</code> | DRIFTED | <code>lua/gen3/client.lua:1769-1837</code> | <code>keys[k] = true</code> |
| 704 | <code>lua/gen3/client.lua:1500-1567</code> | DRIFTED | <code>lua/gen3/client.lua:1769-1837</code> | <code>keys[k] = true</code> |
| 705 | <code>state.py:695-709</code> | DRIFTED | <code>server/state.py:776-784</code> | <code># in the Lua diff loop — without this, a phantom deposit propagates</code> |
| 714 † | <code>state.py:1865-1870</code> | DRIFTED | <code>server/state.py:2074-2088</code> | <code># saved values take precedence so mid-run restarts honor the original config).</code> — hud_color accepts color/duration AND r/g/b/frames (lua/core/session.lua:72-75). |
| 714 † | <code>lua/core/session.lua:59-62</code> | DRIFTED | <code>lua/core/session.lua:72-75</code> | <code>-- Which frames a battle write may land on is the driver's safety predicate, never the core's.</code> — hud_color accepts color/duration AND r/g/b/frames (lua/core/session.lua:72-75). |
| 714 † | <code>lua/core/session.lua:278-282 (continuation)</code> | DRIFTED | <code>lua/core/session.lua:283-288</code> | <code>if c == "force_faint" or c == "force_explode" then return route_force(cmd) end</code> — hud_color accepts color/duration AND r/g/b/frames (lua/core/session.lua:72-75). |
| 715 † | <code>state.py:567-584</code> | DRIFTED | <code>server/state.py:646-658</code> | <code>self._handle_trade_offer(player_id, msg)</code> — box_mon_failed is sent explicitly (lua/core/deferred.lua:165). |
| 715 † | <code>lua/core/deferred.lua:164-166</code> | OK | <code>lua/core/deferred.lua:164-166</code> | <code>if not done then</code> — box_mon_failed is sent explicitly (lua/core/deferred.lua:165). |
| 716 † | <code>state.py:593-613</code> | DRIFTED | <code>server/state.py:667-703</code> | <code>self._handle_key_change(player_id, msg)</code> — Gen 3 safe can carry party_hidden (lua/gen3/client.lua:2255-2263). |
| 716 † | <code>state.py:4071</code> | DRIFTED | <code>server/state.py:4459-4468</code> | <code>self._propagate_faint(player_id, entry, cause="npc_trade_clause")</code> — Gen 3 safe can carry party_hidden (lua/gen3/client.lua:2255-2263). |
| 716 † | <code>lua/core/session.lua:402-404</code> | DRIFTED | <code>lua/core/session.lua:452-455</code> | <code>function self:start()</code> — Gen 3 safe can carry party_hidden (lua/gen3/client.lua:2255-2263). |
| 717 † | <code>state.py:1847</code> | DRIFTED | <code>server/state.py:2052</code> | <code>pid: MonInfo(**mon_data)</code> — Gen 3 hello sends trainer ot_id when readable (lua/gen3/client.lua:1309-1310). |
| 718 | <code>server.py:2849-2851</code> | DRIFTED | <code>server/server.py:2218-2220</code> | <code>return killer</code> |
| 719 | <code>lua/core/session.lua:309</code> | DRIFTED | <code>lua/core/session.lua:329</code> | <code>end</code> |
| 720 | <code>lua/gen3/client.lua:377-381</code> | DRIFTED | <code>lua/gen3/client.lua:387-391</code> | <code>local function observe_hp(party)</code> |
| 720 | <code>lua/gen3/boxes.lua:278-310</code> | OK | <code>lua/gen3/boxes.lua:278-310</code> | <code>local function party_from_box(box_raw, stats)</code> |
| 721 | <code>state.py:660-667</code> | DRIFTED | <code>server/state.py:752-759</code> | <code>self._handle_memorialize_done(player_id, msg)</code> |
| 722 | <code>state.py:638</code> | DRIFTED | <code>server/state.py:717-750</code> | <code>self.party_keys[partner].discard(partner_mon.key)</code> |
| 722 | <code>lua/gen3/client.lua:1799</code> | DRIFTED | <code>lua/gen3/client.lua:2069</code> | <code>-- MAJOR 1 (Codex C5-10 review): the no-epoch case FIRST -- a client attached mid-battle</code> |
| 723 | <code>server/server.py:1235-1241</code> | DRIFTED | <code>server/server.py:1631-1636</code> | <code>item    = html.escape(str(mon.get("item") or ""))</code> |
| 723 | <code>server.py:1412-1423</code> | DRIFTED | <code>server/server.py:1691-1697</code> | <code># item, ability and calc_stats. Nature stays None -- no client sends an enemy's</code> |
| 723 | <code>server.py:1551-1792</code> | DRIFTED | <code>server/server.py:1625-1866</code> | <code>))</code> |
| 724 | <code>state.py:777</code> | DRIFTED | <code>server/state.py:989</code> | <code>"""Cache a player's in-game progress (badge count). NOTE: nothing consumes this yet —</code> |
| 724 | <code>state.py:587 (continuation)</code> | DRIFTED | <code>server/state.py:989</code> | <code>self._handle_whiteout(player_id, msg)</code> |
| 724 | <code>state.py:675 (continuation)</code> | DRIFTED | <code>server/state.py:989</code> | <code>self.pokeballs_obtained[player_id] = True</code> |
| 725 † | <code>server.py:3006</code> | DRIFTED | <code>server/server.py:1944-1952</code> | <code># its own &lt;details&gt; contracts and stays a Python builder for now.</code> — Wide Badges row uses hello/tick bitmask now (server.py:1945-1952). |
| 725 † | <code>server.py:3051</code> | DRIFTED | <code>server/server.py:1944-1952</code> | <code>},</code> — Wide Badges row uses hello/tick bitmask now (server.py:1945-1952). |
| 727 | <code>lua/core/session.lua:52</code> | DRIFTED | <code>lua/core/session.lua:60</code> | <code>-- the key must resolve to one party slot; then, in battle and with a game.battle_write, the</code> |
| 728 | <code>server.py:2765-2786</code> | DRIFTED | <code>server/server.py:1643-1658</code> | <code>if event == "faint":</code> |
| 729 † | <code>server.py:4154</code> | GONE | <code>server/server.py:1907-1913</code> | <code>"""POST /api/obs/connect — save connection settings for this player and (re)connect."""</code> — Retired helper/lookup; rewrite the row, not just its number. _lp_mon_cell is gone; replacement half() falls back to MonInfo.species (server.py:1907-1913). |
| 729 † | <code>server.py:3895</code> | GONE | <code>server/server.py:1907-1913</code> | <code>p = pending.get(slot_id) or {}</code> — Retired helper/lookup; rewrite the row, not just its number. _lp_mon_cell is gone; replacement half() falls back to MonInfo.species (server.py:1907-1913). |
| 731 | <code>lua/json_codec.lua:192-197</code> | OK | <code>lua/json_codec.lua:192-197</code> | <code>function M.array(value)</code> |
| 731 | <code>lua/gen3/client.lua:307-317</code> | DRIFTED | <code>lua/gen3/client.lua:317-326</code> | <code>local function party_entry(m, active, b)</code> |
| 732 | <code>state.py:2638</code> | DRIFTED | <code>server/state.py:2781-2793</code> | <code>if gift_capture:</code> |
