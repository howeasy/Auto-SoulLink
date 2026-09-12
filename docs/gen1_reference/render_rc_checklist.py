"""Render docs/gen1_reference/RC_CHECKLIST.md from tests/gen1_release_requirements.json.

Usage: python render_rc_checklist.py <worktree> <out.md> [<list-output.txt>]

The manifest is the truth; this page is a render of it. When a list-output file (the text
printed by ``python tools/verify_gen1_release.py --list``) is given, the render is checked
against it row by row and the script fails if the two disagree.
"""
import json
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path

worktree = Path(sys.argv[1])
out = Path(sys.argv[2])
list_output = Path(sys.argv[3]) if len(sys.argv) > 3 else None

manifest = json.loads((worktree / "tests" / "gen1_release_requirements.json").read_text(encoding="utf-8"))
head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=worktree, capture_output=True,
                      text=True, check=True).stdout.strip()

# Closure plan per stage, from CODEX_HANDOFF_2026-09-10.md item 7 (the manifest closure table).
CLOSURE = {
    "canonical-validation": "7e umbrella registrations",
    "unit-protocol": "7e umbrella registrations",
    "live-memory": "7e umbrella registrations",
    "single-player": "7a natural-play drivers on the free-run loop (after handoff item 5)",
    "live-duos": "7b existing duo runner on the production loop",
    "ordered-contracts": "7b one parametrized HELLO-order contract test",
    "manager-isolation": "7b existing duo runner on the production loop",
    "patch-browser": "7d UPR categories per title, browser E2E (needs playwright), panel and SFX gates",
    "trade-receptionist": "7c register the passing nine-pair live matrix per title; add busy-queued and recovery rows",
    "human-session": "7g full gate run green, then the staged human session (--complete-human)",
}

rows_by_stage = {}
for row in manifest["requirements"]:
    rows_by_stage.setdefault(row["stage"], []).append(row)

counts = Counter((r["stage"], bool(r["proofs"])) for r in manifest["requirements"])
total_reg = sum(v for (s, ok), v in counts.items() if ok)
total_missing = sum(v for (s, ok), v in counts.items() if not ok)


def cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def proof_cell(row):
    if not row["proofs"]:
        return ""
    parts = []
    seen = set()
    for proof in row["proofs"]:
        label = proof.get("check", "")
        source = proof.get("source", "")
        key = (label, source)
        if key in seen:
            continue
        seen.add(key)
        parts.append(f"`{label}` ({source})" if source else f"`{label}`")
    return "; ".join(parts)


lines = []
lines.append("# Gen 1 release checklist")
lines.append("")
lines.append(f"Rendered {date.today().isoformat()} from `tests/gen1_release_requirements.json` "
             f"(schema `{manifest.get('schema', '?')}`) at worktree HEAD `{head}`. The manifest is the "
             "truth and `tools/verify_gen1_release.py` is the gate; this page is a render of the "
             "same rows so the status of the release fits on one screen. Regenerate with:")
lines.append("")
lines.append("```bash")
lines.append("python docs/gen1_reference/render_rc_checklist.py . docs/gen1_reference/RC_CHECKLIST.md")
lines.append("```")
lines.append("")
lines.append("A row is `registered` when the manifest lists at least one reviewed executable proof for it "
             "and `MISSING PROOF` otherwise, exactly as `python tools/verify_gen1_release.py --list` "
             "prints it. Registered is not passed: the full gate run decides that. The closure column "
             "names the plan item in `CODEX_HANDOFF_2026-09-10.md` section 2, item 7, that closes the "
             "missing rows of the stage.")
lines.append("")
lines.append("## Summary by stage")
lines.append("")
lines.append("| Stage | Description | Registered | Missing | Closure plan |")
lines.append("| --- | --- | ---: | ---: | --- |")
for stage in manifest["stages"]:
    sid = stage["id"]
    lines.append(f"| `{sid}` | {cell(stage['description'])} | {counts[(sid, True)]} | "
                 f"{counts[(sid, False)]} | {CLOSURE.get(sid, '')} |")
lines.append(f"| **total** | {len(manifest['requirements'])} requirements, {len(manifest['stages'])} stages | "
             f"**{total_reg}** | **{total_missing}** | |")
lines.append("")
lines.append("## Requirements")
lines.append("")
for stage in manifest["stages"]:
    sid = stage["id"]
    rows = rows_by_stage.get(sid, [])
    lines.append(f"### `{sid}`: {cell(stage['description'])}")
    lines.append("")
    lines.append(f"{counts[(sid, True)]} registered, {counts[(sid, False)]} missing. "
                 f"Closure: {CLOSURE.get(sid, '')}.")
    lines.append("")
    lines.append("| # | Requirement | Description | Status | Proof (check, source) |")
    lines.append("| ---: | --- | --- | --- | --- |")
    for index, row in enumerate(rows, 1):
        status = "registered" if row["proofs"] else "**MISSING PROOF**"
        description = cell(row.get("description", ""))
        axes = row.get("axes")
        if axes:
            description += " (axes: " + cell(", ".join(map(str, axes))) + ")"
        lines.append(f"| {index} | `{row['id']}` | {description} | {status} | {proof_cell(row)} |")
    lines.append("")

if manifest.get("adopted_decisions"):
    lines.append("## Adopted decisions recorded in the manifest")
    lines.append("")
    for item in manifest["adopted_decisions"]:
        if isinstance(item, dict):
            lines.append("- " + "; ".join(f"{k}: {cell(v)}" for k, v in item.items()))
        else:
            lines.append("- " + cell(item))
    lines.append("")

out.write_text("\n".join(lines) + "\n", encoding="utf-8")

if list_output is not None:
    expected = {}
    for line in list_output.read_text(encoding="utf-8").splitlines():
        if line.startswith("  ") and ": " in line:
            rid, status = line.strip().rsplit(": ", 1)
            expected[rid] = status
    rendered = {r["id"]: ("registered" if r["proofs"] else "MISSING PROOF") for r in manifest["requirements"]}
    if expected != rendered:
        diff = {k: (expected.get(k), rendered.get(k)) for k in set(expected) | set(rendered)
                if expected.get(k) != rendered.get(k)}
        print("MISMATCH against --list output:", diff)
        sys.exit(1)
    print(f"checked against --list output: {len(expected)} rows agree")

print(f"wrote {out} : {total_reg} registered / {total_missing} missing over {len(manifest['requirements'])} rows")
