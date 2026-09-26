# Shared duo evidence pipeline

`tools/duo_oracle_pipeline.py` owns evidence-stage validation and result transport.
It contains no game IDs, save offsets, marker formats, or game-state rules.

Each scenario family must register an explicit `EvidenceContract` in
`tools/e2e_duo.py`'s `FAMILY_EVIDENCE`:

| Field | Meaning |
|---|---|
| `witness_validator: str \| None` | Method on the runner that validates the save witness; `None` declares no witness stage. |
| `require_oracle: bool` | Require the scenario's `oracle` method name. Optional `oracle_kwargs` supplies its keyword arguments. |

`gen1_new` requires `check_save_witness` followed by a scenario oracle. The Gen 1
and pureRGB launch aliases resolve to that same family contract. Legacy
`gen2_crystal` and `gen3_rr` explicitly use empty contracts. An unregistered
family is an error; it does not inherit the legacy verdict path.

`validate_pipeline(owner, contract, scenario)` resolves the declared callbacks
and binds their argument signatures before processes launch. Validation runs
again before the verdict, so changing or dropping a required binding cannot
turn two client `RESULT: PASS` lines into a successful required-evidence verdict.

`run_pipeline` passes the original results to the witness validator, then to the
scenario oracle with its declared keyword arguments. A raised exception or an
explicit `False` result fails the stage and prevents subsequent stages from
running. Existing callbacks returning `None` on success retain that convention.
The neutral layer does not reinterpret logs or rewrite evidence receipts.

The injected Gen 1 validator remains in `e2e_duo.py`: its `[0x498:0x8000]` save
slice, byte comparison, emitted receipt text, and zero-save skip policy remain
Gen 1 rules. They are not defaults for other families. A future `gen2_new`
contract must bind its own witness validator and each scenario's post-result
oracle; its validator must reject missing save markers. H2 owns those Gen 2
facts and validators. H0 supplies the seam and test descriptors, not a runnable
Gen 2 driver or admission authority.

Unit tests at this seam are MODEL evidence: they exercise missing bindings,
stage ordering, failure propagation, and preservation of injected validator
behavior. They do not prove native saving, cold reload, or an end-to-end duo.
Those require the separately owned PHYSICAL lane and its game-specific oracle.
