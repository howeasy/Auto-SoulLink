# Gen 1 RBY RC: start here

This entry applies to **every agent type** doing Gen 1 implementation, review, research or evidence work. Root [AGENTS.md](../../AGENTS.md) and [CLAUDE.md](../../CLAUDE.md) point here for compatible runtimes; other agent types must receive this path in their assignment. Transport and model do not change the rules.

1. **Every Gen 1 task:** read [RC_MASTER_GUIDE.md](RC_MASTER_GUIDE.md). It alone holds current status, authority, dependencies, evidence boundaries and next action. Verify its snapshot against Git before acting.
2. **Assigned package:** read that ID and its named prerequisites in the [static package catalog](RC_PACKAGE_CATALOG.md). Its proposed files and Done criteria are reference, not an approval to code; the guide's claim gate controls READY.
3. **Checkout assignment or archive:** read [WORKTREE_REGISTER.md](WORKTREE_REGISTER.md) and verify the exact branch, HEAD, dirty and ignored evidence state before touching a worktree.
4. **Release proof:** read the [388-row manifest](../../tests/gen1_release_requirements.json) and [evaluator](../../tools/verify_gen1_release.py). Registration, collection and a passing component test are distinct from the frozen RC verdict.

Historical detail is available on demand: [A](RC_LANE_A_STATUS.md), [B](RC_LANE_B_STATUS.md), the [native classifier design](NATIVE_RECOVERY_CLASSIFIER_2026-09-12.md), the dated [checklist](RC_CHECKLIST.md), and [archived handoffs](archive/2026-09-13-superseded/README.md). If any historical statement conflicts with current source or a receipt, the coordinator corrects the master guide; it does not open another active queue.
