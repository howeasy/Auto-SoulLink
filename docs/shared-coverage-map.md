# Shared coverage-map contract

`tools/coverage_map.py` is a neutral first-consumer module. Gen 2 supplies the
first binding; this is a CREATE, with no Gen 1 implementation to extract or
rebind. A later binder supplies its own obligations, artifact pins, and receipt
reader and runs the same contract controls. The module does not import a game,
launch a lane, inspect emulator state, infer exemptions, or sign a gate.

## Interface and policy ownership

```python
from tools.coverage_map import Obligation, validate_coverage

report = validate_coverage(
    document,
    obligations={"example:event": Obligation(("SOURCE", "PHYSICAL"))},
    artifacts={"selected-build": "<current SHA1 or SHA256>"},
    inputs={"requirements": "<current document SHA256>"},
    read_receipt=lambda relative_path: evidence_store.read_bytes(relative_path),
    mode="mapping",
)
```

The caller owns the obligation inventory and required evidence layers. Names
are opaque: no prefix, generation, or familiar row ID earns an exemption.
`Obligation(required_layers, artifact_ids=None)` requires every supplied artifact
unless the caller explicitly supplies a narrower `artifact_ids` tuple. Required
layers are nonempty and drawn from SOURCE, MODEL, PHYSICAL. MODEL may be recorded
as supplementary evidence; it cannot satisfy SOURCE or PHYSICAL. Other
supplemental layers must be declared as required by the caller.

Artifact values may be existing digest strings (the caller asserts a built,
current artifact) or explicit target descriptors described below. A target can
be planned without a digest; that supports mapping only, never CLOSED evidence.

The caller also owns artifact admission, exclusions, oracle semantics, complete
scenario branches, and review of whether a mapping actually proves the prose
requirement. Artifact hashes identify the supplied builds; they do not grant
runtime admission. Policy must come from the binder's reviewed contract, not
from the map being checked. Empty policies and unknown artifact IDs refuse.
Before any PHYSICAL closure, the binder must cover its relevant runtime/source,
profile, patch, and fixture fingerprints in artifact/input policy. A source-ROM
catalog alone is not a complete runtime evidence policy; the initial P2 inventory
does not claim that later policy or any physical closure.

`validate_coverage` returns a JSON-compatible report with `ok`,
`mapping_complete`, `evidence_complete`, `unmapped`, `unbuilt_artifacts`, required-layer `open` lists,
and `errors`. Invalid caller policy raises `ValueError`; invalid map/receipt
data returns `ok: false`. It performs no writes. Receipt access is injected.

## Three distinct checks

| Mode | Required result | What it does not establish |
|---|---|---|
| `inventory` | All declared rows exist exactly once; pins, applicability, claimed mappings, and any CLOSED receipts validate | UNMAPPED rows and OPEN evidence remain permitted |
| `mapping` | Inventory passes and zero rows are UNMAPPED; explicit planned target slots are permitted | Unbuilt artifacts and unrun PHYSICAL evidence remain OPEN; this is mapping completeness only |
| `closure` | Mapping passes and every required evidence layer has a matching CLOSED receipt | Receipt bookkeeping is not independent validation of the receipt's factual truth or owner gate acceptance |

Missing or extra rows, invented MODEL-only exemptions, stale input/artifact
pins, incomplete mapped fields, and contradictory CLOSED claims fail in every
mode. A missing receipt fails even if another evidence layer is still OPEN.
The tool reports no physical execution from an inventory/mapping result.
`tools/release_lanes.py` remains the separate execution and release-verdict
mechanism; this module does not reproduce that core.

## Embedded map schema

The Markdown artifact has exactly one JSON fence between
`<!-- COVERAGE_MAP_START -->` and `<!-- COVERAGE_MAP_END -->`. Duplicate JSON
keys or duplicate marked blocks refuse. Human prose outside that block is
explanatory; the JSON is the machine-readable map.

```json
{
  "schema_version": 1,
  "input_sha256": {"requirements": "<raw input SHA256>"},
  "rows": [
    {
      "id": "example:event",
      "required_layers": ["SOURCE", "PHYSICAL"],
      "mapping": {"status": "UNMAPPED", "reason": "Awaiting the owning lane's oracle and controls."},
      "evidence": {
        "SOURCE": {"status": "OPEN", "reason": "No source receipt bound."},
        "PHYSICAL": {"status": "OPEN", "reason": "Not run."}
      }
    }
  ]
}
```

There is no `NOT_APPLICABLE` claim that a row can grant itself. Its
`required_layers` must exactly match injected policy. Optional MODEL evidence
may be added without changing required layers. CLOSED evidence on an UNMAPPED
row is rejected.

A MAPPED object requires every field below. Text fields must be nonempty;
human review still determines whether they are specific and sufficient.

```json
{
  "status": "MAPPED",
  "stimulus": {"kind": "NATURAL", "description": "The exact player-driven event and preconditions."},
  "artifacts": {"selected-build": "<current digest>"},
  "positive_control": "The independently observable known-positive case.",
  "refusal_control": "The independently observable case that must refuse or remain silent.",
  "oracle": "The independent observation and required comparison.",
  "receipt_marker": "stable-observation-marker",
  "lane": "owning-lane"
}
```

Stimulus kind is NATURAL, COMMAND, SOURCE, or MODEL. NATURAL engine observations
and COMMAND executor observations remain different mappings. PHYSICAL
obligations require NATURAL or COMMAND, and a receipt is bound to the whole
mapping, so a command/model receipt cannot silently replace a natural one.
The artifact set must exactly cover the obligation's injected artifact scope.
An explicit future target can be MAPPED without being built. A clean artifact's
digest is never substituted for that future target's unknown digest.

## Planned artifact targets and evidence eligibility

A caller can inject an artifact catalog such as:

```python
artifacts = {
    "source-build": "<current source SHA1 or SHA256>",
    "future-target": {
        "state": "PLANNED", "digest": None,
        "base_artifact": "source-build", "base_digest": "<same current source digest>",
    },
}
obligations = {
    "example:native-feature": Obligation(("SOURCE", "PHYSICAL"), ("future-target",)),
}
```

The row's `mapping.artifacts` contains the exact descriptor for `future-target`.
The base is an already pinned artifact in the injected catalog, with matching
digest. It establishes known lineage, not a claim that the target has been built
or that this is its complete future build manifest. The base must be a digest
string; this bounded schema does not recursively infer chains of planned builds.

Only `PLANNED` with `digest: null` or `BUILT` with a valid digest is accepted.
Missing/stale bases, a planned descriptor carrying a digest, a built descriptor
without a digest, or an unsupported state refuse. The map cannot change the
descriptor, replace it with its base, or drop a required target: artifact scope
comes from the injected `Obligation`, not from the row's own claim.

Inventory and mapping modes accept an explicit planned descriptor and report its
ID in `unbuilt_artifacts`. Closure mode refuses it. **Every CLOSED claim against
it also refuses in every mode and every evidence layer**, including SOURCE and
MODEL; a proof about the existing base belongs to a separately scoped obligation.

After an actual build, the caller supplies a `BUILT` target descriptor with its
real digest, and the row is rebound to that exact descriptor. Previous receipts
cannot transfer: their artifact descriptors and whole-mapping digest are stale.
New matching receipts remain subject to every normal row/layer/input/control
check. `BUILT` never implies runtime admission or physical qualification.

## Receipt contract

A CLOSED evidence entry has only `status: "CLOSED"` and a `receipt` object with
`path` and `sha256`. Paths use forward slashes, are relative to the evidence
root, and cannot contain a parent traversal, drive, or absolute path. The CLI
also rejects resolved paths outside the evidence root, including symlinks.

The receipt is a JSON object with these required fields:

```json
{
  "schema_version": 1,
  "obligation_id": "example:event",
  "layer": "PHYSICAL",
  "verdict": "PASS",
  "input_sha256": {"requirements": "<current raw input SHA256>"},
  "mapping_sha256": "<mapping_sha256(mapping)>",
  "artifacts": {"selected-build": "<current digest>"},
  "lane": "owning-lane",
  "marker": "stable-observation-marker",
  "controls": {"positive": "PASS", "refusal": "PASS"}
}
```

The file's actual SHA256 must match the reference before its contents are
trusted. Required fields must match the current row, layer, input pins,
artifact pins, lane, and marker. Skipped, missing, failed, stale, or wrong-layer
claims do not close a layer. Extra receipt fields may retain the actual command,
source citations, observations, independent oracle outputs, and recorded limits.
Receipt authors/reviewers remain responsible for those facts; a self-written
JSON `PASS` does not become physical evidence merely because this validator
accepts its structure. The producer uses the exported `mapping_sha256` helper:
SHA256 of UTF-8 JSON with sorted keys, compact separators, and `ensure_ascii=False`.

## Generic Markdown/CLI adapter

The public validator accepts arbitrary injected policies. The optional CLI
provides a small adapter for existing Markdown contracts:

* `requirements_from_markdown` reads tables with `id`, `Requirement`, `Oracle`,
  `S`, `M`, and `P` columns, creating `requirement:<id>` identifiers. A P cell
  other than `—` requires SOURCE+PHYSICAL. A `—` P cell must explicitly declare
  either `— (SOURCE-only, P = —)` or `— (MODEL-only by design)` in the Oracle
  cell. No row-ID list or blank-cell heuristic supplies an exemption.
* `protocol_from_markdown` enumerates numbered assertions in the selected
  section, including letter suffixes, as `protocol:<section>.<number>`. Its
  layers are supplied by the caller. A binder needing per-assertion policy uses
  the public validator with its reviewed obligation mapping; this CLI does not
  invent assertion-specific exceptions.
* `--artifact-policy` selects a JSON file. `--artifact-collection` selects a
  dotted object path, `--artifact-digest-field` names the digest field, and
  repeated `--artifact-id` flags explicitly select current artifacts. This
  adapter does not infer admission from a catalog's other fields. If a selected
  base explicitly has a `state` field, it must be `BUILT`; an expected hash on an
  explicitly unbuilt row does not qualify it as a built base.
* Repeated `--planned-target SLOT=BASE` flags explicitly declare future targets
  using selected pinned bases. Repeated
  `--target-binding OBLIGATION[,OBLIGATION]=TARGET[,TARGET]` flags inject the exact
  target scope for those obligations. Other obligations retain the original
  selected base scope. Unknown/duplicate bindings, unknown bases, and unused
  target declarations refuse. Target definitions and bindings are never taken
  from the map itself. The flags are binder policy and require review.

The CLI's added flags declare only PLANNED targets. A future binder that closes
built derived artifacts supplies the reviewed BUILT catalog and obligation scope
through the public validator interface (or separately extends the generic CLI
catalog adapter). No flag can invent a built target hash.

All four file paths are explicit. The three normative files are read as bytes
and their raw SHA256s become `requirements`, `protocol`, and `artifact_policy`
input pins. A changed document or lock must be reviewed and rebound; formatting
changes also alter raw pins. No missing input is skipped. The map itself is
read-only. `--receipt-root` defaults to the current directory.

```text
python tools/coverage_map.py --map PATH --requirements PATH --protocol PATH
  --protocol-section SECTION --protocol-layers SOURCE PHYSICAL
  --artifact-policy PATH --artifact-collection COLLECTION --artifact-digest-field FIELD
  --artifact-id ID [--artifact-id ID ...] --mode inventory|mapping|closure
  [--planned-target SLOT=BASE ...]
  [--target-binding OBLIGATION[,OBLIGATION]=TARGET[,TARGET] ...]
  [--receipt-root PATH]
```

Exit 0 means only the requested mode succeeded. Exit 1 means missing/invalid
inputs or a failed requested check; argument errors exit 2. JSON stdout reports
which mappings/layers remain open. `tests/unit/test_gen2_coverage_map.py` contains
neutral contract controls parameterized with two unrelated binder identities,
plus generic Markdown/CLI controls; none requires a ROM or emulator.
