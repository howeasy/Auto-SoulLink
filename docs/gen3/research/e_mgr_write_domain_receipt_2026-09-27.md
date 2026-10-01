# E-MGR: audited Emerald Manager randomization (2026-09-27)

SOURCE and MODEL receipt for `codex/emerald-mgr`, source cut `aabba561ff9dd5f8807f56b8a4f04a8b756bac2e`.
The card began at `07c529bd` and merged the coordinator's integration `95ce7c81` as `f677341c`.
The feature is `dc41d16f`; `aabba561` corrects the complete source range for the roamer rewrite.

## Result

The Manager identifies pinned English revision-0 Emerald, exposes the existing randomizer form,
and provisions two `.gba` files with separate seeds and a contract over the final files.
Both outputs were admitted by the real server hello path using reports made by the actual Lua
ROM collector. This is MODEL evidence, not a physical Manager-produced-cartridge run.

Full `tests/unit`: **11,680 passed, 4,261 skipped, zero failures and zero errors**, exit 0,
591.32 seconds. The command was:

```text
python -m pytest tests/unit -q -p no:randomly --tb=short --basetemp=.cache/e-mgr-full-final-tmp --junitxml=.cache/e-mgr-full-final.xml
```

The environment supplied `SLINK_GEN3_ROMS`, `SLINK_UPR_JAR`, `SLINK_GEN3_RAND_ROMS`,
`SLINK_PRET_FIRERED_SRC`, `SLINK_PRET_EMERALD_SRC` and `SLINK_HOST_GCC` from the verified local
inputs. The fixed-seed Java probe used the repository's SHA256-verified Temurin JDK 17 bootstrap.
Full stdout/JUnit paths and hashes, per-module counts, exact settings and output hashes are in
[the machine-readable receipt](../probes/e_mgr_model_receipt_2026-09-27.json).

## Model and refusal boundary

The shared `server/upr_gen3_write_domain.py` now selects a separate Emerald model:
`data/games/gen3_emerald/upr_write_domains.json` (SHA256 `b0ecebcefedd103eebebae5893b13ec0431c8be22fb4eca81b16a6fe1f1f238b`).
Its 43 domains derive from the fork's `[Emerald (U)]` INI, its IPS patches and Emerald handler
branches, the clean ROM, and `pokeemerald.sym`. The FR/LG model remains byte-for-byte unchanged.

- Fork JAR SHA256: `28292b595a411e78beef851e0cd5017a5d4ff592eca9a1db3f8939b0f7ab6e56`.
- Clean Emerald SHA1: `f3ae088181bf583e55daf962a92bb46f4f1d07b7`.
- pret Emerald: `c65e93f20a5275ab03b07d6f6411096a82a60ffd`; the model records the symbol-file SHA256.
- Emerald baseline: two intro species words; the unconditional first-battle IPS; the roamer
  instruction/constant rewrite; originally empty ability-2 fill; speed-forme Deoxys normalization.
- Emerald-specific writes: three starter words; Steven's separate three partner records; both
  catching-tutorial operands; two-byte Pickup entries; Emerald's national-dex script pointer.
- Free space is the verified 0xFF suffix `0xE40000..0x1000000`, still **packed** from its start
  with the shared maximum gap of five unchanged bytes. Fixed IPS writes do not authorize gaps.
- TM-held and regular field-item sites retain separate membership tests.
- All nine rule-bearing forbidden domains remain naming-only. Frontier, Pyramid, Trainer Hill,
  Contest and Secret Base domains are never enabled. A pinned-source census found 920 constant
  array names in 33 facility source files; all 996 matching ROM symbols (including conservative
  duplicate-name matches) are outside every allowed span.
- Emerald uses the FR/LG ruling-31 envelope except `balance_static_levels`: the fork offers that
  tweak only for FR/LG, so Emerald refuses it by name. Gen 1-only tweaks and rule changes remain
  refused. A stock/unmodelled JAR and missing model are refused; the companion stays unavailable.

The seeded audit module passed all **78** rows, including **54** per-option writing cases,
all-options and baseline controls, a named mutation in each forbidden domain, packed-space
falsifiers, and required JAR/model checks. Every enabled isolation domain must still receive
its own changed byte, and every run must have zero stray bytes. No random rerun or identity
exception was introduced.

## Output evidence

The E-RAND-LIVE scratch allowed ROM changed **13,038 bytes, 0 stray**. Its widest control changed
**23,622 bytes**, with **10,478 stray**, all named: base stats 2,289; types 724; abilities 505;
level-up movesets 5,248; evolutions 250; egg moves 1,462. None was unattributed.

The final full gate produced this Manager pair, with identical effective settings and different
seeds. Each output had zero stray writes, intact engine/checkpoint anchors, unchanged normalized
species rules/evolutions, and matching final-file contract hashes.

| Player | Seed | Final ROM SHA1 | Semantic fingerprint SHA256 |
|---|---:|---|---|
| A | 249204072617971 | `f1f1c9f6cc191081e9d0a8a9d95eb7b6f5c88112` | `b87d6f7646efb733aca3e2ae11359d0c62cc35d81324cf2e14ea4acb8fdd439f` |
| B | 261944579878916 | `a46c073b4a54cc2b258eeff8e219310e415d8212` | `8b1738f97c529283c11c929af0afe5201ffb01005365a33cbef47be8984324a2` |

The contract is retained under `C:/slink-wt/em-t3/.cache/e-mgr-full-final-tmp/manager_emerald_pair0`. ROMs stay in ignored test scratch storage;
no ROM was committed. The receipt records both SHA1 and SHA256, log/settings hashes, and the
server's persisted title/kind/identity state.

## Verification trail

- `.cache/e-mgr-model-red.xml`: unsupported Emerald builder/family falsifiers before implementation.
- `.cache/e-mgr-pipeline-red.xml`: Manager identification/provisioning/visibility falsifiers.
- `.cache/e-mgr-related.xml`: 636 passed, 194 skipped; all 78 Emerald audit and 9 Manager pipeline rows ran.
- `.cache/e-mgr-full.xml`: the first complete run retained 11,661 passed / 4,257 skipped / four
  failures from integration's FR/LG-only trainer-probe roster. The coordinator's `259a2e34`
  restored the per-title probe. This branch merged that integration fix instead of duplicating it.
- `.cache/e-mgr-merge-check.xml`: 100 passed, 1 skipped after the merge.
- `.cache/e-mgr-full-final.xml`: final complete green gate at the source cut above.

Scope limits remain those of the FR/LG standard: the audit checks ranges, not every value or
pointer target, and tightness is per domain rather than per component. Physical E-MGR admission
and gameplay, native v2, and companion qualification are separate cards. Unit skips are not passes.
