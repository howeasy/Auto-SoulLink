# Browser patcher RC checkpoint

The browser now offers the checked current Red/Blue panel+trade and Yellow
trade-only companions. The former claim that Yellow had no possible companion
has been removed. Gen1 pages do not advertise native messages, peer ghost,
Battle Calc or event SFX. The Radical Red target remains separate.

`tools/generate_gen1_patcher_targets.py` derives the public target fingerprints
from the actual canonical inputs, final artifacts and UPS bytes. The server
cross-checks that catalog against the installed companion profiles and refuses
changed patch files. The browser verifies the full input, patch and output
SHA-256 before making a download available. MD5 remains a displayed convenience.
It refuses wrong titles, modified/reapplied ROMs and a mismatched final fingerprint.

An already reproduced run can supply `run-a` and `run-b` targets through the
shared patch-route provider. `server/gen1_patcher_targets.py` owns the Gen1
presentation binding; the source ROM and patch bytes remain immutable values
from `PreparedCartridges`. This accepts only each exact pre-patch UPR artifact,
including separate Yellow/Yellow seeds. The global Manager patcher serves clean
targets; per-run patch pages can also expose their own prepared targets.

The shared browser UPS decoder now checks variable-integer bounds, source/output
sizes, XOR span bounds and terminators. It cannot allocate an unbounded result
from a malformed patch. A file-selection generation prevents an older async
fetch/hash from publishing a stale ROM. Final-hash mismatch is a refusal, not a
warning followed by a download. Real browser testing found that button CSS
overrode the hidden attribute; scoped hidden styling and clearing stale hrefs
now remove the previous download reliably.

Evidence: `.cache/browser-patcher-final.xml`, 21 pytest passes in13.89s.
The four actual browser cases contain31 scenarios:16 canonical/refusal/codec
checks plus5 each for combined UPR R/B,B/Y,Y/Y. File selection, actual patch fetch,
apply and download all run in Chrome152.0.7977.77 with Playwright1.62.1; every
download matches its exact final SHA-256. There are no page exceptions or ROM
uploads. Screenshots were reviewed. Browser profiles, downloads and logs stay
under the test's worktree staging directory. The runner records browser/Node/
Playwright versions and browser executable SHA-256 in its final report.

Run the required local browser lane with Node and Playwright available through
normal module resolution or `NODE_PATH`. Set `SLINK_CHROMIUM` to an installed
Chrome/Chromium executable, or install the browser matching Playwright. Tests
do not skip when required browser prerequisites are missing.

Remaining: final packaging/asset manifest and full integrated release run.
The browser result does not enable ordinary gameplay or production trade/recovery
authority. The current generated RBY launcher still uses held-service mode.
