# G1 signature, 2026-10-01 (provisional blanket signature)

**Owner, 2026-10-01:** "Consider all signatures signed for now"

The signature is recorded as given, as an explicit owner yes. It is provisional ("for now"), and it covers every signature pending at that moment:

- **G1:** platform and hook-mechanism receipts, PLAN §5.1 rows a–o, on HG and the pinned hge build.
- **Performance margin:** acceptance of the one on-demand faint-hook row. Its mean and max pass the owner's 1x rule, but its p99 is +2.2 ms (HG) and +2.6 ms (hge) over the bare floor. That is above the coordinator's +1.0 ms margin (`docs/gen4/reviews/DECISIONS_2026-10-01.md`), and no frame exceeds 33.43 ms.

## Evidence state at signature (the signature does not convert OPEN to PASS)

| Row | State |
|---|---|
| o, in-battle linked faint | PHYSICAL PASS on HG (`a15b7d74`, regression `ae0995dc`) and hge (`0f75c938`), one-mon, with the normal faint animation. The 2-mon replacement path (SYNTH, owner-allowed) is live in progress (C1-8D, `488b3dcf`). |
| f, 1x performance | 0-hook rows PASS on HG and hge (HG `heartgold-8355974c3c30`, hge `heartgold_hge-69a401df3d4b`). The 1-hook row is accepted by this signature. |
| a, c, d, e, g, h, j, k, l | PASS on HG on an earlier probe cut. Those receipts are not bound to the current cut (OMP cx-97ce7f50 BLOCKER), so a re-run on the frozen cut and on hge is still owed. |
| b, m, n | Pack recipes and phase cases exist (`052e1e67`, `3ec5a0c6`, `f891ad9f`); never run live. |
| i, box save | SYNTH tool `13844937` and PC route `edf3d5f4`; live in progress. |

Open G1 work continues as normal work under G2. If any of it fails, it is reported to the owner as a regression against this provisional signature.
