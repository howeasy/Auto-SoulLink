# F1 host-capability diagnosis, 2026-09-13

Status: **HOLD for final qualification**; bounded execution receipt, independent review pending. Coordinator/evidence runner Codex `01a09ae0-ad6f-7b01-8753-5e6b71eb1cfa`, host HOUNDOOM, canonical `gen1/rc` at `0e4f8fd` (production `19edbb2`, later changes documentation only).

P0 inputs were accepted before this separately granted execution. Exact command with existing Python 3.12.10:

```powershell
& 'C:\Users\howar\AppData\Local\Programs\Python\Python312\python.exe' -m pytest tests/unit/test_http_server_security.py -q -ra -p no:randomly -o addopts= --junitxml=.cache/f1-host-successor.xml
```

All 48 tests in this file ran or reported skips, no deselection. Process exit **0**, **46 passed, 2 skipped**, console duration **0.95s**. Both skips are `test_calc_rejects_symlink_escape[0/1]`, source `tests/unit/test_http_server_security.py:119`, with **WinError 1314: A required privilege is not held by the client** while creating the temporary file symlink. The two Windows junction cases passed; junction support does not substitute for the skipped symlink cases. The release evaluator requires all expected setup/call/teardown phases passed and rejects skips (`tools/verify_gen1_release.py::validate_pytest_report`). Thus this is an honest failed qualification prerequisite, despite pytest exit 0.

Ignored local evidence, captured once and verified at 13:37 UTC:

| Receipt | Raw SHA256 |
| --- | --- |
| `.cache/f1-host-successor.xml` | `77965f7496432c631d5bd90a7b7fe6df61e6dc8390c8f64d6f65fd581d5f9466` |
| `.cache/f1-host-successor.txt` (combined stdout/stderr) | `3c6daefc325cd72606b85f6bbddc8bad683f8af3434c3f416915080d48ad2867` |

No production/source/test changes, emulator, installation, privilege change or persistent environment setting. Pytest owned its ordinary OS-temp fixtures; output is limited to this report and the two receipts. This verifies these bounded HTTP/security assertions and current symlink inability, not the whole unit/integration selection or any physical gameplay.

Next owner/action: independent reviewer checks receipt and scope; owner supplies a symlink-capable test environment before final F qualification. Do not rerun the unchanged failure or replace its tests with a weaker oracle. C1/N0/D0b work remains independent and continues.
