# F1 symlink environment repair, 2026-09-13

Owner explicitly requested "Enable symlinks on this PC" after the [original F1 receipt](F1-host-successor.md) reproduced two WinError 1314 skips. Coordinator Codex `01a09ae0-ad6f-7b01-8753-5e6b71eb1cfa`, host HOUNDOOM, canonical `gen1/rc` at `03955fc`, production `19edbb2`.

The initial non-elevated process token lacked the symbolic-link privilege and the Developer Mode value was absent. Executed the single administrator registry change documented by [Microsoft](https://learn.microsoft.com/en-us/windows/advanced-settings/developer-mode): `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock\AllowDevelopmentWithoutDevLicense`, DWORD `1`. The elevated `reg.exe` helper PID was 19164; it exited and readback at 13:41:29 UTC returned `1`. No other registry/security setting, source, dependency, persistent environment variable or reboot was changed.

Same existing Python 3.12.10, complete test file, under the original non-elevated test environment:

```powershell
& 'C:\Users\howar\AppData\Local\Programs\Python\Python312\python.exe' -m pytest tests/unit/test_http_server_security.py -q -ra -p no:randomly -o addopts= --junitxml=.cache/f1-symlinks-successor.xml
```

Result: **48 passed, zero failures/errors/skips**, no deselection, process exit **0**, console duration **0.90s**. Both actual symlink-escape refusal tests now execute and pass. This clears the specific observed host-capability blocker; it is not a whole-suite, gameplay, pre-human RC or release verdict. The old 46-pass/two-skip receipt remains failed under the no-skip rule.

| Ignored local receipt | Raw SHA256 |
| --- | --- |
| `.cache/f1-symlinks-successor.xml` | `4b38651acdf7c4b7b9d98a3242ffd244b3d83672f586a2f5c923ce846676f427` |
| `.cache/f1-symlinks-successor.txt` (combined stdout/stderr) | `339f9ca5fdbfbbee36ef676b7bff66d197d92552f725ad600a835ff58b95c9c5` |

Writer released. Next owner/action: independent reviewer verifies the changed-condition receipt; coordinator records acceptance and continues the existing C1/N0/D0b assignments. Other F1 import/browser/full-selection checks and final frozen qualification remain open.
