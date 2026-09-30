Exact private-pack JSON captured from the coordinator's 2026-09-27 15:57 UTC
T5 attempt on `c1debdfd`. These are intentionally stale/lowercase inputs, not
current admission data. `receipt.json` pins the original bytes; `.gitattributes`
preserves their line endings. No ROM or save is included.

The tests replay the named startup failure, require stale-manifest refusal,
then regenerate over a copy of this existing directory and verify all 21 hooks.
