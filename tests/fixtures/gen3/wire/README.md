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
{"dir": "c2s", "t": 118, "msg": {"event": "hello", "player": "a", "seq": 1, "rom_type": "FRLG_1_0", "party": []}}
{"dir": "s2c", "t": 119, "msg": {"commands": [{"cmd": "noop"}]}}
```

- `dir`: `"c2s"` (client -> server, one JSON object per outbound line, §9 item 1) or `"s2c"`
  (server -> client, one reply line `{"commands": [...]}`).
- `t`: the frame counter (or a monotonic capture-order sequence number if the source doesn't
  expose frames) at which the line crossed the wire -- not the protocol's own `seq` field.
- `msg`: the exact JSON object from that line, verbatim (for `c2s` this is one event per
  `docs/protocol.md` §3.2; for `s2c` this is one reply per §5, a `{"commands": [...]}` object).

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
