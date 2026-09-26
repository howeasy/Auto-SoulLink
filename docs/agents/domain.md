# Domain docs

**Single-context layout.** One `CONTEXT.md` at the repo root plus `docs/adr/` for
hard-to-reverse decisions. Both are created lazily — neither exists yet, and that is the expected
state, not an omission to fix. This repo is one domain (Soul Link across generations), so there is
no `CONTEXT-MAP.md` and no per-package contexts.

## What goes where

- **`CONTEXT.md`** — the glossary. A term earns an entry when it is overloaded, when it means
  something narrower here than in general use, or when two lanes have used it differently.
- **`docs/adr/NNN-<slug>.md`** — one decision per file, for choices that are expensive to reverse:
  a wire-format change, an admission rule, where a shared module's seam sits.
- **Neither** is the place for how something currently works. That belongs in `docs/REFERENCE.md`,
  `.github/copilot-instructions.md` or the module's own doc, all of which are swept for accuracy.

## Terms this repo already overloads

These are the live candidates for `CONTEXT.md`'s first entries, recorded here so the knowledge is
not lost while that file does not exist:

- **verified** — means three different things and the distinction is load-bearing:
  *unit-green* (no emulator), *live/PHYSICAL* (ran on a real cartridge and left a receipt), and
  *ADMITTED* (an owner signed a gate). "On master" is a fourth thing and implies none of the others.
- **BUILT vs ADMITTED** — an artifact can exist, hash-match its pin and still not be admitted.
  Gen 2's overlays are BUILT with G4 unsigned.
- **absent vs wrong** — an input that is missing is a skip; an input that is present but not the
  pinned build is a failure. See the rule in `tests/TESTING.md`; conflating them is how a stale
  artifact reads as green.
- **receipt** — a committed artifact proving a live run happened, not a log. If it is not pinned
  and re-checkable, it is not a receipt.
- **lane** — two senses, and they get confused: a *release lane* (a check inside
  `verify_<gen>_release.py`) and a *work lane* (an agent session owning a generation).
- **foundation** — a ROM family sharing a codec and data pack (`gen1_rby`, `gen1_purergb`,
  `gen2_gsc`), which is not the same as a title.

## When to write an ADR

When a decision would be expensive to undo and someone will later ask "why is it like this?" — and
when the answer is not obvious from the code. A decision recorded in a commit message is usually
enough; an ADR is for the ones a commit message cannot hold.
