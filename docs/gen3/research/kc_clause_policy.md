# KC-CLAUSE: owner ruling 35

Owner decision: 2026-09-27, recorded in `docs/gen3/G4_request_draft.md` §6.
Implementation branch: `claude/gen3-kc-clause`. Integration `a5084489` was merged first
at `13ff6c98`; no master merge or push is part of this card.

## Decision and behavior

An NPC exchange has already changed the cartridge. Accept the new key/species first, then
validate the resulting alive pair against the run's enabled species/evolution-family, gender
and type clauses. A violation retires **only the pair that changed**, with the dedicated
cause `npc_trade_clause` (shown as **NPC trade clause violation** on the memorial).

- The ordinary identity/census collision preflight still runs before migration. A genuine key
  collision remains a separate identity-safety refusal; a clause failure is never disguised
  as identity loss.
- `_check_link_mutation_violation` delegates to the capture-time clause validator with the
  current entry excluded from its own key and existing-family lookup. It still checks the
  two members against each other and checks other alive links on both players.
- Clauses are independently opt-in. Genderless/unknown-gender exemptions and adapter-provided
  family/type/gender facts are the same as at capture time. Dead other links do not block.
  Capture-time fixed-gift handling is unchanged; this validator handles the later NPC exchange.
- The received mon is still healthy, unlike a normal faint report: queue its force-faint
  explicitly under the **new** key, then use `_propagate_faint` to retire the pair and queue
  the partner's faint plus both memorials. ACK precedes the new death commands; faint precedes
  burial. Non-battle retirement does not trigger Explode Mode.
- Preserve the resolved encounter area and all other pairs. Do not unresolve an area, open a
  capture retry, or penalize the older pair whose family caused the conflict.
- This applies to `reason="npc_trade"` on the shared Gen 1/2/3 path. Ordinary evolution,
  nature changes and native Soul Link trade settlement are not expanded by this ruling.

Implementation anchors: `server/state.py` `_handle_key_change`,
`_check_link_mutation_violation`, `_check_link_violation`, `_propagate_faint`;
`server/templates/_macros.html` `tombstone`.

## Why an owner decision was needed

The first, documentation-only card (`d20f8b80`, source base `26fa0e1f`) correctly stopped:
all generations migrated NPC identities without rechecking clauses. The source descriptions
below are historical at that base, not claims about the implementation after ruling 35:

- Gen 1 emits after readback (`lua/gen1/client.lua:124-127,1591-1621`); Gen 2 recognizes the
  finished exchange (`lua/gen2/signals.lua:761-766`) and emits the same reason/species
  (`lua/gen2/client.lua:1217-1223`); Gen 3 uses the same event (`lua/gen3/client.lua:472-487`).
- The old migration preserved the pair (`server/state.py:3397-3423,3519-3540,3606-3625`).
  `_check_link_violation` was called only for bonus/ordinary pair creation (`:2104,2380`);
  duplicate captures and encounter rerolls were separate (`:2271-2316,2558`).
- Existing rules described capture rejection and area retry (`docs/REFERENCE.md:797`), while
  `docs/gen1_requirements.md:114` described migration keeping the link. The randomized design
  explicitly queued the unresolved policy (`docs/gen3/research/randomized_gen3_design.md:220-223`).
- Directly checking an already-indexed pair would find its own keys/family as duplicates
  (`server/state.py:3709-3715,3732-3749`). The mutation exclusion addresses that trap.

The original 33 MODEL cases (11 titles × same species / same family / other alive link)
all stayed ALIVE, while all 33 duplicate-capture controls were refused. Ruling 35 turned those
33 characterizations into red-first falsifiers: all failed before the implementation and pass
afterward. Raw historical rows remain locally at `.cache/kcc-model.json`.

## Verification map

`tests/unit/test_state_npc_trade_clauses.py` covers Red, Blue, Yellow, PureRed,
Crystal, Gold, Silver, FireRed, LeafGreen, Emerald and RR:

| Contract | Control |
|---|---|
| Accept identity, retire changed pair, retain other pair and area | 33 original species/family cases; both new/current keys receive faint then memorial, ACK is retained |
| Enabled rules only | Species disabled; valid families/self exclusion; enabled/disabled type and gender; unknown/genderless exemptions |
| Correct player and live-link scope | Player B exchange, same-player duplicate, dead other pair ignored |
| Durable/idempotent result | Named cause/species survive reload; replay does not retire again |
| User-visible explanation | Killfeed cause and memorial text say NPC trade clause violation |

Targeted run: **493 passed in 6.08s** (105 new mutation controls, existing state/key-change,
memorial acknowledgement and accessibility tests). Source-citation and whitespace checks pass.
This is SOURCE/MODEL work; no emulator or physical qualification is claimed.

The documentation-only baseline was **15365 passed, 515 skipped in 938.22s**, exit 0,
recorded in `.cache/kcc-full-unit.txt` (SHA-256
`e78e87576e3fa2b10d71e5f40999d0851e1c5089bd900422332924e58ab8d874`).
The implementation's full-suite receipt follows after its final run.


## Combined verification cut

Clause implementation: `556d0c5f9e190448a8206984c471a6db388726f7`.
T4-R4 (`4229d7d8` plus Emerald-control receipt `234aa086`) was merged at `7ddf6920`
after the integration merge. The sole conflict was protocol prose/citation offsets: retain
integration's FR/LG + Emerald wording and ruling 35, add R4's hidden-party contract, then
reanchor source citations. No behavior was invented during resolution.

The merged focused run passed **623 tests in 7.41s**. Three further interaction controls
(FR, Emerald, RR) prove that a hidden NPC report is refused before identity migration or
clause retirement; with those included, the two card-specific files pass **238 tests in
5.15s** (108 mutation controls and 130 recovery controls). The final full suite will cover
this combined cut, including the additional Emerald hidden-empty-hello control.


## Final implementation receipt — 2026-09-27

Production/test cut: `46c2f7568a103a1e33a3acfff656f7e5feef193d` (includes R4 and the
additional Emerald hidden-empty-hello control). Source stayed unchanged during verification.

The first four-worker run ended **1 failed, 15615 passed, 606 skipped in 1105.84s**:
`test_direct_generator_cli_check_without_pythonpath[gifts]` exceeded its existing 90-second
subprocess limit. Neither that test nor `tools/gen_gen2_gifts.py` changed. Running all three
generator CLI checks in isolation passed **3 tests in 103.24s**, with the same per-check limit.
The failure remains recorded in `.cache/kcc-r35-full-unit.txt`.

The full rerun reduced concurrency; no assertion, timeout or selected test was weakened:

```text
python -m pytest tests/unit -q -p no:randomly -n 2 --dist=loadfile
15616 passed, 606 skipped in 1914.68s (0:31:54)
Exit code: 0
```

Output: `.cache/kcc-r35-final-full-unit.txt`; SHA-256
`4615369fec6c3a79ae4a12c7940155e090689ae7dda821f8c0046ce372202b47`.
Prerequisites used the existing pinned local Gen 1/2/3 ROM/build/pret inputs, trusted UPR JAR,
and the same environment bindings as the T4 receipts. The 606 skips are reported as skips,
not physical qualification. No emulator ran and no client/native/READY files were changed.
Final protocol source-citation checks and `git diff --check` pass.
