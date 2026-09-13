# F1 retirement fixture successor

Source: canonical `gen1/rc`, production `15727ec`, documentation HEAD `edcbf60` at corrected execution. Scope is only `tests/unit/test_gen1_no_catch_retirement_flow.py`; no production, shared helper, Lua, manifest, dependency, emulator, or commit change. This supports `protocol.unit` only and is MODEL ONLY evidence.

The original assigned file reproduced all three title-pair failures with `python -m pytest tests/unit/test_gen1_no_catch_retirement_flow.py -q -ra -p no:randomly -o addopts= --junitxml=.cache/f1-retirement-successor.xml`: `3 failed in 12.30s`, each at the later retirement write ACK with `JournalError: one exact pending retirement obligation required`. The fixture had selected an intervening HUD command with no `acquisition_id`. This red output was displayed before the named R1 receipt files were replaced by the first candidate's green run; the full-unit `.cache/f1-unit-successor.txt` independently records the same three errors.

The first candidate ACKed HUD through `acknowledge_hud` before the head `retirement_observe`. Independent Spec review rejected it: that helper dispatches directly and bypasses `Gen1Runtime`'s oldest-pending guard. Its passing 115-case R1 XML/text are preserved below as **rejected evidence**, not acceptance of the fixture.

The corrected fixture asserts the complete A queue is `retirement_observe, hud_notice`, ACKs the retirement read first, then asserts `hud_notice, acquisition_retire`. It ACKs that HUD head through the public `runtime.process` session path, which enforces Gen 1 FIFO, then asserts only `acquisition_retire` remains. It also settles the sole B HUD head through that path before durable reopen. The retirement commands retain the captured key and stored acquisition ID. No pending command is discarded and no validator changes. The existing test still checks source provenance, raw cartridge image/archive bytes, wrong-file-hash atomic refusal, idempotent ACK, memorial identity, inventory attribution, durable reopen, journal verification, and empty queues.

Corrected R2 red/green: the first guarded-order attempt exposed three durable-reopen failures because B's HUD remained pending. After asserting and ACKing its sole head, the assigned file passed 3/3 in 17.09s. Final command: `python -m pytest tests/unit/test_gen1_no_catch_retirement_flow.py tests/unit/test_gen1_retirement_runtime.py tests/unit/test_gen1_hud_feedback.py tests/unit/test_gen1_wild_encounter.py -q -ra -p no:randomly -p no:cacheprovider -o addopts= --junitxml=.cache/f1-retirement-r2.xml` with combined output in `.cache/f1-retirement-r2.txt`. Result: **115 passed in 43.92s; 0 failures, 0 errors, 0 skips**, no selection flags. `python -m ruff check tests/unit/test_gen1_no_catch_retirement_flow.py` and `git diff --check` pass. Other agents' disjoint files were left untouched.

Rejected R1 SHA256, retained without modification:

- Test file: `84B611CB7C639024B78CB981DFC90D66B25569444D747D57845C3824D57BEE7F`
- JUnit XML: `F7AC50E8EF09E820C9295DA5CBACFE7BAA3FD8C5C3DA69767EBF4B41D928C99C`
- Combined text: `32EF97B9564335A1A8379D08F955C45C6F8A052D473EF90DD4CCC49EE9D2B194`

Corrected R2 SHA256:

- Test file: `04C83E1642626420FC98FCDB7D5991DD1FB30D1125A1F42EB3B7EC79240688B9`
- JUnit XML: `59B1863AA24C9E2CD2AE323B82B7D7F24FACE01800338FC01F0E13D2D389E13A`
- Combined text: `AD587224521949F785E866DDDD901001F39C7CED30FCC4887AC1CDF2CA7E52D3`

The corrected result establishes the modeled fixture and adjacent contracts, not original-engine execution, saved-file physical recovery, complete F1, or a release verdict. Sole test/report ownership is released for independent Spec re-review.
