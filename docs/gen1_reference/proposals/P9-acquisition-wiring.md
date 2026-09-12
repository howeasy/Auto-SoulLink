# P9: the acquisition call site decides through the shared rule engine

Status: patch ready, applies cleanly (`git apply docs/gen1_reference/proposals/P9-acquisition-wiring.patch`).
Verified in a scratch copy of the worktree: with the patch, `test_gen1_acquisition_runtime.py`,
`test_gen1_frame_acquisitions.py`, `test_gen1_gift_areas.py` and `test_gen1_adapter.py` show
155 passed and exactly the five failures the worktree already has today (three assert the
pre-Sept-9 `boxed_deferred` outcome or a stale pairs list, two in `test_gen1_frame_acquisitions`
assert the same policy or an older frame-authority precondition; see the ledger). No new
failure. ruff clean. This is handoff item 2 applied to the second call site.

## What changes

`server/gen1_acquisition_runtime.py`: the `record_disposition(...)` call (the adapter over
`capture_rules` and `party_grant_rules`) becomes `_decide_through_engine(...)`, a small helper
in the same module:

```python
def _decide_through_engine(rules, player, area, mon, stable, *, exempt):
    partner = "b" if player == "a" else "a"
    peer = rules.pending_captures.get(area, {}).get(partner)
    violation = None
    if peer is not None and not rules.adapter.is_fixed_species_gift(area):
        halves = {player: mon, partner: peer}
        found = rules._check_link_violation(halves["a"], halves["b"])    # the same shared check the engine runs
        if found is not None:
            violation = list(found)
    masks = copy.deepcopy(rules.party_keys)
    activated = dict(rules.pokeballs_obtained)
    rules.handle_event(player, capture_event(key=mon.key, area_id=area, species_id=mon.species, level=mon.level,
                                             nickname=mon.nickname or "", gift=False,
                                             in_box=stable["location"] == "box"))
    rules.queued_commands = {"a": [], "b": []}
    rules.party_keys = masks
    rules.pokeballs_obtained = activated
    linked = rules.find_link(player, mon.key)
    if linked is not None and linked.status != LinkStatus.ALIVE:
        linked = None
    return {"linked": linked, "violation": violation}
```

`server/adapters/gen1_rby.py`: `"celadon_mansion_roof"` joins `_FIXED_SPECIES_GIFTS`.

## Why each line is there

- **`gift=False` with the area `area_of` already produced.** `area_of` maps grants to
  `gift_<area>` or to their pairing id before this point; the engine re-applies
  `gift_link_area` only for `gift=True`, which would prefix a pairing id a second time
  (`gift_grant:game_corner_purchase#1`). Real gift areas still map through the engine's own
  `_is_gift_capture` unchanged, so the engine and the RC record name the same area.
- **Three RBY adapter policies stay around the engine, as the parallel module kept them.**
  Usability is published only by the proved physical disposition (the party mask is restored;
  the storage runtime schedules quarantine and linked jobs from `pending_captures` and the
  acquisition tokens, `server/gen1_storage_runtime.py:278,356-423`, not from commands). Ball
  activation comes only from the `bag_received` engine signal (the flag is restored). The
  engine's queued `box_mon`, `party_mon`, sounds and prompts are drained because Gen 1
  executes physical disposition through those jobs; the executor map of handoff item 4
  replaces the drain.
- **The violation message is computed with the engine's own shared check** so the RC record
  and the recovery hold keep working exactly as today. The engine's consequence for a
  violation (force-faint the offender, memorialize, reopen the area, retry) is the standard
  the owner chose; it is queued and, for now, drained, because a rule-initiated `force_faint`
  has no `death_id` and the held executor only accepts death-bound faints. That executor
  change belongs to item 4; until then the constraint hold stays as the visible consequence.
- **Eevee is a fixed-species gift.** The parallel rule exempted every scripted grant from the
  clauses wholesale; the standard exempts only fixed-species gifts. With species lock on, two
  Eevees from Celadon Mansion were therefore refused by the engine until the adapter declared
  what is true: no player choice is involved. Magikarp and Lapras were already declared. The
  Yellow-only Bulbasaur, Charmander and Squirtle gifts and the Yellow starter are the same
  case and should be added when their area ids are confirmed against `_MAP_ID_TO_AREA`.

## What this exposes about the parallel module

`party_grant_rules.record_exempt_party_grant` and `capture_rules.record_clause_checked_acquisition`
are now unused by this call site. `test_gen1_acquisition_runtime.py` still calls
`record_clause_checked_acquisition` directly in one test, and `gen1_starter_settlement.py:126`
still calls `record_exempt_party_grant`; both go with the starter wiring
(`capture_event(..., gift=True, area_id="intro")`, handoff item 2).

## Verification

```bash
python -m pytest tests/unit/test_gen1_acquisition_runtime.py tests/unit/test_gen1_frame_acquisitions.py tests/unit/test_gen1_gift_areas.py tests/unit/test_gen1_adapter.py -q
ruff check server/gen1_acquisition_runtime.py server/adapters/gen1_rby.py
```
