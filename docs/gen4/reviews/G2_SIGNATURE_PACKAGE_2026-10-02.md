# G2 signature package: Gen 4 (HGSS + hg-engine), 2026-10-02

- **Gate:** G2 "SOURCE facts + codec + fixtures" (`docs/gen4/PLAN.md:243`). Owner signs "only completed pack/fixture columns; absent hge mon cannot be signed away".
- **Frozen cut:** `c1123171`. Later commits are docs only.
- **Branch:** `claude/gen4-support-framework-dfd5e2`.
- **Not done:** nothing is pushed or merged to master, and **this package is not a signature**. G2 is signed only on an explicit owner yes.

## Cell table

**Physical cells** are PHYSICAL receipts bound to the evidence surface (`tools/gen4_evidence.py`; the probe, route, Lua modules and packs are hashed and checked against the committed blobs). The coordinator independently re-ran `verify_receipt` on every one (PASS).

| Clause | HG | SS | hge | Pt | Evidence |
|---|---|---|---|---|---|
| Registration pins + 4-byte fire words | DONE (SOURCE) | DONE (SOURCE) | DONE (SOURCE) | n/a (bind check) | pack `--check` against pinned ROM sha1s; red-capable mutation table `test_gen4_pack.py:124-140,193` |
| Acquisitions join producers, **NPC reachability**, unresolved branches | DONE | DONE (shared scripts) | DONE (NARC member proof) | n/a | `20b03aea`, `3745647c`, `391b7df2`: 61/61 sites `reachability.status = resolved` with cited story gates; CallStd modelled; the one hge path through the differing common-script member is flagged `inherits_unproven` |
| Codec / save-layout controls (wrap, coherent banks, CRC, torn/ambiguous) | DONE | DONE | DONE | DONE | `test_gen4_save_layout.py:86-113` |
| Fixtures: boot → native SAVE → cold reload, counter + keys | **PASS** | **PASS** | **PASS** | n/a | see "Physical receipts" below |
| Egg hatch (native) | **PASS** | **PASS** | **PASS** | n/a | see "Physical receipts" below |
| Wild capture (V1), battery-decoded mon | **PASS** | **PASS** | **PASS** | n/a | see "Physical receipts" below |
| hge `party_off`, dirty flag, ability + populated mon | n/a | n/a | DONE | n/a | `5514d94d`, `d52cc4c7`; dirty flag `0x1E004` measured (`7dbc1cfc`); populated hge saves present (D15) |
| Pt profile SOURCE + save decode (D3) | n/a | n/a | n/a | DONE (non-shipping) | `663c5f3d`; owner Pt save decodes |
| Every required producer has an oracle + physical receipt plan | DONE | DONE | DONE | n/a | `G2_PRODUCER_PLAN.md` §2-§6b; SYNTH tooling `bag`/`egg1`/`party2`/`party6`/`species`/`place` |

**Physical receipts** (all in `C:/slink/g4/`; PC and hatch show save counter 1 → 2 → 2 with keys retained):

| Cell | HG | SS | hge |
|---|---|---|---|
| Fixtures (PC deposit, SAVE, reload) | `landing-c112-pc-hg-0905` | `g2pcSS-pg-0909` | `g2pcHGE-pg-0915` |
| Egg hatch | `g2hatchHG-0910` | `g2hatchSS-0915` | `g2hatchHGE-0920` |
| Wild capture | `g2catchHG-0922` | `g2catchSS-0929` | `g2catchHGE-0929` |

## Disclosures

- **SYNTH setup.** Owner standing rule: party2, egg1 and the bag are disclosed SYNTH inputs, each with a sidecar hash. The behaviour under test (deposit, SAVE, reload, hatch, capture) ran natively.
- **SS PC route.** The first SS attempt (`landing-c112-pc-ss-0905`) failed with RESYNC_LOOP and is preserved. The passing run used the documented Pokégear-errand recipe; it was not an unchanged retry.
- **Stale plan wording.** `PLAN.md:243` still says "SS fixture cells block on D4", and `PLAN.md:31` says the Pt save is blank. Both are stale: D4 and D3 inputs exist and decode.

## Carried, not G2 cells

- **G1 carry-over:** rows a–n on the frozen cut (HG/hge), row f PERF re-run, and row o faint receipts at the new cut (two in flight at stop).
- **G3 queue** (recorded in `RESUME.md` checkpoint 6):
  - client review fixes (OMP cx-09f09a39, incl. the PartyExtra gap) and `place` fixes (OMP cx-3bab37d5, incl. vecY);
  - the live client smoke;
  - PC withdraw/release legs;
  - the new-game route.
- **Owner item for this gate:** ruling 35. The server force-faints a traded-in mon that breaks an enabled clause.
