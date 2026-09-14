# HS-3 launcher dialogs

`tools/launch_bizhawk.py` previously let every refusal from `prepare()`/`launch()`
(`server/bizhawk_launch.py`) escape as a raw Python traceback, and silently `return 0`d on any
dialog cancellation with no feedback at all. A human who double-clicks a shortcut to this script
never sees a terminal, so both were invisible failures. This lands the smallest fix that makes
every exit path visible without changing what `prepare()`/`launch()` refuse.

Owner: this worker (HS-3). Canonical checkout
`E:/Google Drive/SLink/.claude/worktrees/gen1-rby-code-sweep-8d06e2`, branch `gen1/rc`, HEAD
`67e9e49` at dispatch. Touched exactly the files the card allowed: `tools/launch_bizhawk.py`,
new `tests/unit/test_launch_bizhawk_dialogs.py`, and this report. `server/bizhawk_launch.py` was
**not** touched — no error type there needed a `.message` attribute; every refusal is already a
plain single-line `ValueError`, so matching `str(exc).splitlines()[0]` against a substring table
was enough. No git commit/stash/checkout was run.

## What changed

- Wrapped the manifest-load / `prepare()` / `launch()` call in one `try/except Exception`. Any
  exception now shows a `messagebox.showerror("SLink launcher", ...)` with the exception's first
  line plus a hint (see table below), also still prints the full traceback to stderr, and exits 1.
- Both dialog-cancellation points (choosing `manifest`/`rom`/`emuhawk`, and the first-launch
  resume-save picker) now `messagebox.showinfo("SLink launcher", "Launch cancelled")` and exit 0
  instead of returning 0 silently.
- On success, prints one line to stdout before blocking on `process.wait()`:
  `SLink: EmuHawk started for player <p> (run <id>); keep this window open [pid <pid>]` — no
  modal, since a modal here would block the emulator's own message loop.
- Headless safety: `tkinter`/`tkinter.messagebox` are imported once at module scope and swallowed
  into `None` on `ImportError`; a single `_dialog()` helper wraps every `tk.Tk()` construction and
  `messagebox.*` call in its own `try/except Exception` (catches `ImportError`-as-`None` and a
  real `TclError` from a missing display alike) and falls back to `print(..., file=sys.stderr)`.
  The file-picker branch checks the same way before opening a `Tk()` root at all, so a headless
  run without CLI args prints "no display available" and exits 1 instead of raising.
- `prepare()`/`launch()` behavior is untouched — same checks, same refusal messages, same return
  shape. `main()`'s success path still calls `process.wait()` and returns its exit code, so the
  one pre-existing test that drives `main()` end-to-end
  (`test_launch_tool_passes_the_resume_save_through_to_prepare` in
  `tests/unit/test_bizhawk_launch.py`) needed no change and still passes.

## Hint table

| Known message substring (case-insensitive) | Hint shown |
|---|---|
| `ROM differs from the admitted final cartridge` | Pick the FINAL admitted cartridge for your player; the Manager run page shows its SHA1. |
| `emulator executable differs from the qualified host` | Pick the EmuHawk.exe recorded when this run was qualified. |
| `resume` (covers every resume/`.SaveRAM` refusal: no contract, wrong name, wrong digest, wrong size, already-played) | Pick the .SaveRAM you last played in the previous run. |
| anything else | See the terminal for details. |

## Tests (`tests/unit/test_launch_bizhawk_dialogs.py`)

Fakes `tk`/`messagebox`/`filedialog`/`prepare`/`launch` at the module attribute seam `tools.launch_bizhawk` already exposed (the same seam the pre-existing `test_bizhawk_launch.py::test_launch_tool_passes_the_resume_save_through_to_prepare` uses) — no real Tk window is ever created.

1. `test_known_prepare_error_shows_hint_and_exits_1` — wrong-cartridge `ValueError` → `showerror` with message + hint, exit 1.
2. `test_known_emulator_error_shows_its_own_hint` — wrong-emulator `ValueError` from `launch()` → its own hint.
3. `test_unknown_error_falls_back_to_generic_hint` — an unmapped exception → message + "See the terminal for details."
4. `test_dialog_cancellation_shows_info_and_exits_0` — cancelling the manifest file picker → `showinfo("SLink launcher","Launch cancelled")`, exit 0.
5. `test_success_prints_started_line_with_pid` — successful launch → stdout line with player, run id, and `[pid 4242]`.
6. `test_tk_unavailable_falls_back_to_stderr_without_raising` — `tk`/`messagebox` both `None` (simulated `ImportError`) → error text on stderr, no exception, exit 1.
7. `test_no_display_for_dialogs_reports_and_exits_1_without_raising` — no CLI args and no `tk`/`filedialog` → "no display available" on stderr, exit 1, no exception.

## Verification

```
$ python -m pytest tests/unit/test_launch_bizhawk_dialogs.py tests/unit/test_bizhawk_launch.py -q -o addopts= -p no:cacheprovider
............................                                             [100%]
28 passed in 0.54s

$ python -m pytest tests/unit/ -q -o addopts= -p no:cacheprovider
<see full-suite run below>

$ ruff check tools/launch_bizhawk.py tests/unit/test_launch_bizhawk_dialogs.py
All checks passed!

$ git diff --stat -- tools/launch_bizhawk.py
 tools/launch_bizhawk.py | 125 +++++++++++++++++++++++++++++++++++++-----------
 1 file changed, 97 insertions(+), 28 deletions(-)

$ git status --porcelain -- tools/launch_bizhawk.py tests/unit/test_launch_bizhawk_dialogs.py server/bizhawk_launch.py
 M tools/launch_bizhawk.py
?? tests/unit/test_launch_bizhawk_dialogs.py
```

(`server/bizhawk_launch.py` shows no `M` — confirmed untouched.)

sha256 of the two files this worker wrote:

```
baeb224b28c6b10473f6fdeb03ce9e08bb4493c79612b9bfb9cc69d6807da7de  tools/launch_bizhawk.py
72cf4468d07a329db102f3da065e687bfd8b9a8817d74ef36b4686eb4b8430eb  tests/unit/test_launch_bizhawk_dialogs.py
```

## Deviations from the card

- The card's step 1 hint wording said "wrong cartridge", "wrong emulator", "save-related
  messages" (plural) — implemented as one substring `resume` that catches every resume/SaveRAM
  refusal (`no resume contract`, wrong name, wrong digest, wrong size, already-played), rather
  than enumerating each message string, since they all legitimately want the same hint.
- `server/bizhawk_launch.py` was not touched, per the card's "only if an error type needs a
  message attribute — prefer not": every raised exception there is already a plain `ValueError`
  with a `str()` matching its message, so no change was needed.
- pid is reported as a bracketed suffix `[pid <pid>]` on the same success line rather than a
  separate line; the card left the exact placement open ("include it").
