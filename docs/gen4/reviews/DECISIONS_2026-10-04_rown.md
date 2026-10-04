# Gen 4 decision, 2026-10-04: row n caller scope for G1

Owner ruling, answered directly in the Gen 4 coordinator session.

**Question.** Row n (PC storage invariants) currently witnesses the deposit caller only. Should G1 sign-off require all four PC callers (deposit, delete-by-index, withdraw, release)?

**Ruling: deposit only for G1.**

- G1 signs on the deposit case.
- Delete-by-index, withdraw and release stay explicit row n OPEN at G1 and become required at a later gate.
- Withdraw is first. It is implemented and green offline: two-A keyboard path on claude/gen4-withdraw, ae602fcf.
- This narrows the G1 bar only. It does not drop the other callers from scope.
