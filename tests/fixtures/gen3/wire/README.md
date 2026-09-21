# Gen 3 wire transcripts

Golden wire transcripts consumed by `tests/unit/test_protocol_conformance.py`. Empty today --
card C1-3 (P1) produces the first fixtures here by capturing `tools/e2e_duo.py --wire-log`
output from real duo runs (both the old `lua/games/gen3_frlge.lua` client and the new
`lua/gen3/*` client). Until then, the conformance suite's transcript half skips with the
reason `"no golden transcripts yet (P1 C1-3)"`.

## Format

One file per captured session: newline-delimited JSON (JSONL), one object per wire line, in
the order it crossed the socket:

```json
{"dir": "meta", "t": 1, "msg": {"event": "_connect"}}
{"dir": "c2s", "t": 2, "msg": {"event": "hello", "player": "a", "seq": 1, "rom_type": "FRLG_1_0", "party": []}}
{"dir": "s2c", "t": 3, "req": 2, "msg": {"commands": [{"cmd": "noop"}]}}
{"dir": "meta", "t": 4, "msg": {"event": "_disconnect"}}
```

- `dir`: `"c2s"` (client -> server, one JSON object per outbound line, §9 item 1), `"s2c"`
  (server -> client, one reply line `{"commands": [...]}`), or `"meta"` (a connection-boundary
  marker, not a wire line -- see below).
- `t`: **capture order**, a per-file monotonic counter starting at 1, shared across both
  directions and across every connection that ever writes to this file -- never the frame
  counter and never the protocol's own `seq` field (which restarts on reconnect and only
  exists on `c2s` lines). Use `t` only to order rows within a file; it is not a frame count
  and successive values are not 30 apart even across `tick` lines.
- `req` (replies only): the `t` of the `c2s` line this reply answers, when the tap could
  determine one. Absent on `meta` lines and on a `c2s`/`meta` line's own record.
- `msg`: the exact JSON object from that line, verbatim (for `c2s` this is one event per
  `docs/protocol.md` §3.2; for `s2c` this is one reply per §5, a `{"commands": [...]}`
  object; for `meta` this is `{"event": "_connect"}` or `{"event": "_disconnect"}`).
- `raw`/`msg: null` (c2s only): a line that parsed as JSON but was not an object (e.g. a bare
  `42` or `[1, 2]`) -- not valid protocol, so it is recorded as `{"raw": <line, truncated to
  1 KiB>, "msg": null}` instead of being read like an event.

One player's file (`wire_a.jsonl` / `wire_b.jsonl`) can hold more than one connection's lines:
the server keeps that file's handle and `t` counter open for the life of the process, so a
reconnect's lines land in the same file, bracketed by a `_disconnect` from the old connection
and a `_connect` from the new one. A line the tap could not attribute to a real player id
(`a`/`b`) goes to a third, bounded file, `wire_rejected.jsonl` (capped, then silently
dropped) -- never promoted to a golden transcript by `tools/e2e_duo.py --wire-log`.

## Naming

`<scenario>_<player>_<source>.jsonl`, e.g. `catch_wild_a_gen3_new.jsonl`.

- `scenario`: what the session exercises (`catch_wild`, `pc_deposit`, `trade`, `whiteout`, ...).
- `player`: `a` or `b`, matching the `player` field on every line in the file.
- `source`: `old_client` (today's `lua/games/gen3_frlge.lua` + `lua/gen3/client.lua` under the
  old tree) or `gen3_new` (the P4/P5 rewrite). The conformance suite treats these differently:
  an `old_client` transcript is *characterization* evidence and is expected to reproduce
  exactly the documented disagreements (`docs/protocol.md` Appendix A / `conformance_map.py`
  `disagreement` field) and nothing else; a `gen3_new` transcript must pass every
  transcript-checkable item with zero violations.
