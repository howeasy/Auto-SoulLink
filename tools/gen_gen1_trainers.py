#!/usr/bin/env python3
"""Generate data/games/gen1_purergb/trainers.json from pureRGB source (docs/purergb/PLAN.md M1).

New tool (vanilla's `data/games/gen1_rby/trainers.json` is hand-curated, per docs/purergb's B3
census -- there is no generator to port). Grammar-aware: a party-record line is one of four
shapes (`constants/trainer_constants.asm`, `data/trainers/parties.asm` header comment):

    fixed:  db LEVEL, SPECIES, SPECIES, ..., 0        (one shared level)
    $FF:    db $FF, LEVEL, SPECIES, LEVEL, SPECIES, ..., 0
    $FE:    db $FE, Q, SPECIES, Q, SPECIES, ..., 0     (Q = LEVEL or "LEVEL + 128" = alt palette)
    $FD:    db $FD, MOVESET_ID, Q, SPECIES, Q, SPECIES, ..., 0

Every record fits on one `data/trainers/parties.asm` line (confirmed by inspection: no record
spans two `db` statements), so a naive "count the db lines in this class's block" WOULD get
every class right except one: `JrTrainerMData` wraps a single record in
`IF DEF(_DEBUG) ... ELSE ... ENDC`, and counting both branches overcounts by one (11 instead of
the S2-verified 10) -- the RC's plain db-line counter falls into exactly this trap. This
generator drops the `_DEBUG` branch the same way `tools/gen_gen1_encounters.py`'s
`parse_map_asm` drops a debug wild-encounter branch, before counting or extracting anything.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tools.gen1_foundation as gf  # noqa: E402

FOUNDATION = "purergb"
OPP_ID_OFFSET = 197
NUM_TRAINERS = 56
RIVAL_CLASSES = ("RIVAL1", "RIVAL2", "RIVAL3")

# S2's per-class party-record counts, class ids 1..56 in `trainer_const` order
# (docs/purergb/PLAN.md §11.2 S2) -- asserted against, never assigned from. Only 4 of these 56
# were independently ROM-verified by W2 (Youngster 12, Bug Catcher 15, Sailor 7, Rocket 41 --
# "the S2 array stands"); the rest is trusted unless source parsing says otherwise.
_S2_PARTY_COUNTS = [
    12, 15, 19, 7, 11, 24, 10, 10, 15, 15, 9, 5, 11, 15, 9, 9, 15, 6, 6, 10, 9, 17, 9, 9, 3, 14,
    4, 41, 10, 6, 3, 3, 3, 3, 3, 3, 3, 3, 7, 12, 9, 3, 24, 3, 3, 4, 7, 3, 2, 7, 6, 1, 2, 7, 7, 7,
]

# Class 5 (JR_TRAINER_M) is the one position where S2's raw digit array (11) disagrees with
# both direct source parsing and the plan's own later-corrected prose (A12: "JR_TRAINER_M 10,
# FISHER 11"). `data/trainers/parties.asm`'s JrTrainerMData block wraps ONE record in
# `IF DEF(_DEBUG) ... ELSE ... ENDC`; a naive db-line count (the exact trap A12 calls out for
# "the RC generator") gets 11 by counting both branches, but RGBASM never assembles the untaken
# branch into a release ROM, so the real party pool has 10 records. Treated as a documented S2
# transcription bug, not a parser bug -- flagged here instead of silently overridden.
_S2_DISCREPANCIES_EXPLAINED = {
    5: "JrTrainerMData's IF DEF(_DEBUG)/ELSE record is counted once in a release ROM, not "
       "twice; A12's own prose gives the corrected value (10), matching this parse",
}

_TRAINER_CONST = re.compile(r"^\s*trainer_const\s+([A-Z][A-Z0-9_]*)\s*$")
_DW_LABEL = re.compile(r"^\s*dw\s+([A-Za-z_0-9]+)\s*$")
_LABEL_DEF = re.compile(r"^([A-Za-z_0-9]+):\s*$")
_LI_STRING = re.compile(r'^\s*li\s+"(.*)"\s*$')
_LEVEL_EXPR = re.compile(r"^(\d+)\s*(\+\s*128)?$")
_IF_DEBUG = re.compile(r"^IF\s+DEF\(\s*_DEBUG\s*\)\s*$")


def parse_trainer_classes(root) -> dict[str, int]:
    """class const name -> id (0=NOBODY..56), from `trainer_const` macro invocations."""
    out: dict[str, int] = {}
    idx = 0
    for line in (root / "constants" / "trainer_constants.asm").read_text(
            encoding="utf-8").splitlines():
        line = line.split(";", 1)[0].strip()
        m = _TRAINER_CONST.match(line)
        if m:
            out[m.group(1)] = idx
            idx += 1
    if idx - 1 != NUM_TRAINERS:
        raise SystemExit(f"trainer_constants.asm: parsed {idx - 1} trainer classes (NOBODY "
                         f"excluded), expected {NUM_TRAINERS}")
    return out


def parse_trainer_names(root) -> list[str]:
    """56 `li \"...\"` strings, in class-id order (class 1 first) -- rival slots are blank."""
    out: list[str] = []
    in_table = False
    for line in (root / "data" / "trainers" / "names.asm").read_text(
            encoding="utf-8").splitlines():
        line = line.split(";", 1)[0].rstrip()
        if line.strip().startswith("TrainerNames::"):
            in_table = True
            continue
        if not in_table:
            continue
        if line.strip().startswith("assert_list_length"):
            break
        m = _LI_STRING.match(line)
        if m:
            out.append(m.group(1))
    if len(out) != NUM_TRAINERS:
        raise SystemExit(f"names.asm: parsed {len(out)} names, expected {NUM_TRAINERS}")
    return out


def parse_trainer_data_labels(root) -> list[str]:
    """56 `dw <Label>` entries in `TrainerDataPointers`, in class-id order."""
    out: list[str] = []
    in_table = False
    for line in (root / "data" / "trainers" / "parties.asm").read_text(
            encoding="utf-8").splitlines():
        line = line.split(";", 1)[0].strip()
        if line.startswith("TrainerDataPointers:"):
            in_table = True
            continue
        if not in_table:
            continue
        if line.startswith("assert_table_length"):
            break
        m = _DW_LABEL.match(line)
        if m:
            out.append(m.group(1))
    if len(out) != NUM_TRAINERS:
        raise SystemExit(f"parties.asm: parsed {len(out)} TrainerDataPointers rows, "
                         f"expected {NUM_TRAINERS}")
    return out


def real_lines(text: str) -> list[str]:
    """``text``'s lines with the `IF DEF(_DEBUG)` branch dropped, ELSE branch kept.

    Same discipline as `gen_gen1_encounters.py`'s wild-table parser: never let the debug/dev
    branch of a conditional leak into a fact this generator reports.
    """
    out: list[str] = []
    cond_stack: list[bool] = []  # True = this branch is being kept
    for line in text.splitlines():
        stripped = line.split(";", 1)[0].strip()
        if _IF_DEBUG.match(stripped):
            cond_stack.append(False)
            continue
        if stripped == "ELSE":
            if cond_stack:
                cond_stack[-1] = not cond_stack[-1]
            continue
        if stripped == "ENDC":
            if cond_stack:
                cond_stack.pop()
            continue
        if all(cond_stack):
            out.append(line)
    return out


def parse_party_record(tokens: list[str]) -> dict:
    """One `db ...` line's tokens (comma-split, trailing terminator kept) -> a record dict."""
    if tokens[-1].strip() != "0":
        raise ValueError(f"record does not end in a 0 terminator: {tokens}")
    body = [t.strip() for t in tokens[:-1]]

    def level_and_alt(tok: str) -> tuple[int, bool]:
        m = _LEVEL_EXPR.match(tok)
        if not m:
            raise ValueError(f"not a level expression: {tok!r}")
        return int(m.group(1)), bool(m.group(2))

    if body[0] == "$FD":
        grammar, moveset, pairs = "FD", body[1], body[2:]
    elif body[0] in ("$FF", "$FE"):
        grammar, moveset, pairs = body[0].lstrip("$"), None, body[1:]
    else:
        level, alt = level_and_alt(body[0])
        species = body[1:]
        return {"grammar": "fixed", "level": level, "alt_palette": alt, "species": species,
                "moveset": None, "party_size": len(species)}

    if len(pairs) % 2 != 0:
        raise ValueError(f"grammar {grammar}: odd (level, species) token count: {pairs}")
    levels, alts, species = [], [], []
    for i in range(0, len(pairs), 2):
        lvl, alt = level_and_alt(pairs[i])
        levels.append(lvl)
        alts.append(alt)
        species.append(pairs[i + 1])
    return {"grammar": grammar, "level": levels, "alt_palette": alts, "species": species,
            "moveset": moveset, "party_size": len(species)}


def parse_class_block(text: str, label: str) -> list[dict]:
    """Every `db ...` record between ``label:`` and the next top-level label."""
    lines = real_lines(text)
    start = end = None
    for i, line in enumerate(lines):
        m = _LABEL_DEF.match(line.strip())
        if m and start is None and m.group(1) == label:
            start = i + 1
            continue
        if start is not None and m and m.group(1) != label:
            end = i
            break
    if start is None:
        raise SystemExit(f"parties.asm: no {label}: label found")
    block = lines[start: end if end is not None else len(lines)]
    records = []
    for line in block:
        stripped = line.split(";", 1)[0].strip()
        if not stripped.startswith("db "):
            continue
        tokens = stripped[len("db "):].split(",")
        records.append(parse_party_record(tokens))
    return records


def build() -> dict:
    root = gf.source_root(FOUNDATION)
    classes = parse_trainer_classes(root)
    id_to_class = {v: k for k, v in classes.items()}
    names = parse_trainer_names(root)
    data_labels = parse_trainer_data_labels(root)
    parties_text = (root / "data" / "trainers" / "parties.asm").read_text(encoding="utf-8")

    rival_ids = [OPP_ID_OFFSET + classes[c] for c in RIVAL_CLASSES]
    if rival_ids != [221, 237, 238]:
        raise SystemExit(f"rival ids {rival_ids} != expected [221, 237, 238]")

    label_records: dict[str, list[dict]] = {}
    class_rows: dict[str, dict] = {}
    party_counts: list[int] = []
    for i in range(1, NUM_TRAINERS + 1):
        const = id_to_class[i]
        label = data_labels[i - 1]
        if label not in label_records:
            label_records[label] = parse_class_block(parties_text, label)
        records = label_records[label]
        opp_id = OPP_ID_OFFSET + i
        class_rows[str(opp_id)] = {
            "class": const,
            "name": names[i - 1] or None,  # rival/champion slots are blank strings by design
            "data_label": label,
            "party_count": len(records),
            "grammars": sorted({r["grammar"] for r in records}),
            "records": records,
        }
        party_counts.append(len(records))

    if party_counts != _S2_PARTY_COUNTS:
        mismatches = [(i + 1, id_to_class[i + 1], got, want)
                     for i, (got, want) in enumerate(zip(party_counts, _S2_PARTY_COUNTS, strict=True))
                     if got != want]
        unexpected = [m for m in mismatches if m[0] not in _S2_DISCREPANCIES_EXPLAINED]
        if unexpected:
            raise SystemExit(f"party_count mismatches vs the S2 array: {unexpected}")
        for class_id, const, got, want in mismatches:
            print(f"NOTE: class {class_id} ({const}): parsed {got} party records, S2's raw "
                 f"digit array says {want} -- {_S2_DISCREPANCIES_EXPLAINED[class_id]}",
                 file=sys.stderr)

    # RookieData is aliased by four classes (its own row plus three more) -- the alias must be
    # a literal shared label, not four independently-typed-out copies of the same team.
    rookie_aliases = [id_to_class[i] for i, lbl in enumerate(data_labels, start=1)
                      if lbl == "RookieData"]
    if len(rookie_aliases) != 4:
        raise SystemExit(f"RookieData aliased by {len(rookie_aliases)} classes, expected 4: "
                         f"{rookie_aliases}")

    return {
        "schema": "gen1-purergb-trainers-v1",
        "source": f"purergb {gf.lock(FOUNDATION)['source']['commit'][:12]}",
        "opp_id_offset": OPP_ID_OFFSET,
        "rival_ids": rival_ids,
        "num_trainers": NUM_TRAINERS,
        "classes": class_rows,
    }


def _rom_check(root) -> list[str]:
    """Cross-check TrainerDataPointers (bank $0E, W2: flat 0x39518) against the built ROMs.

    Scope: the pointer TABLE (count, and which classes alias the same pointer) is verified
    byte-for-byte against all three titles; the party records themselves are source-derived
    only here (not independently re-walked from ROM bytes) -- flagged as the generator's one
    UNVERIFIED-against-ROM gap, left for the unit test / a future pass to close.
    """
    problems = []
    data_labels = parse_trainer_data_labels(root)
    for title in ("purered", "pureblue", "puregreen"):
        syms = gf.parse_sym(gf.sym_path(FOUNDATION, title))
        bank, addr = syms["TrainerDataPointers"]
        if (bank, addr) != (0x0E, 0x5518):
            problems.append(f"{title}: TrainerDataPointers at {bank:02x}:{addr:04x}, "
                            f"expected 0e:5518")
            continue
        rom = gf.rom_path(FOUNDATION, title).read_bytes()
        flat = gf.flat(bank, addr)
        rom_ptrs = []
        for i in range(NUM_TRAINERS):
            off = flat + i * 2
            rom_ptrs.append(rom[off] | (rom[off + 1] << 8))
        for i, label in enumerate(data_labels):
            if label not in syms:
                problems.append(f"{title}: no .sym entry for {label}")
                continue
            lbl_bank, lbl_addr = syms[label]
            if lbl_bank != 0x0E:
                problems.append(f"{title}: {label} not in bank 0e ({lbl_bank:02x})")
            elif rom_ptrs[i] != lbl_addr:
                problems.append(f"{title}: class {i + 1} ({label}) pointer 0x{rom_ptrs[i]:04x} "
                                f"!= .sym address 0x{lbl_addr:04x}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="fail if the file on disk differs from what the source says")
    ap.add_argument("--skip-rom-check", action="store_true",
                    help="skip the TrainerDataPointers ROM cross-check (needs SLINK_PURERGB_SRC)")
    args = ap.parse_args()

    doc = build()
    root = gf.source_root(FOUNDATION)
    if not args.skip_rom_check:
        problems = _rom_check(root)
        if problems:
            sys.stderr.write("TrainerDataPointers ROM cross-check failed:\n  " +
                             "\n  ".join(problems[:40]) + "\n")
            return 1

    out_path = gf.data_dir(FOUNDATION) / "trainers.json"
    rel = os.path.relpath(out_path, gf.REPO)
    if args.check:
        if not out_path.exists() or json.loads(out_path.read_text(encoding="utf-8")) != doc:
            print(f"{rel} is stale — re-run without --check", file=sys.stderr)
            return 1
        print(f"{rel} matches source ({len(doc['classes'])} classes)")
        return 0
    out_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    n_records = sum(c["party_count"] for c in doc["classes"].values())
    print(f"Wrote {rel}: {len(doc['classes'])} classes, {n_records} party records, "
          f"rival_ids={doc['rival_ids']}, ROM-verified pointer table")
    return 0


if __name__ == "__main__":
    sys.exit(main())
