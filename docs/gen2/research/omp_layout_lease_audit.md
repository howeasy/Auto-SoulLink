# gen2-A6 — target layout vs phase leases

Frozen input: `git show effcb6f:docs/gen2/PLAN.md` (295 lines). Nothing was modified. §4's
fenced layout block is expanded into concrete paths; §6's third column is each phase's
exclusive-files lease; `git ls-tree -r --name-only effcb6f` (1095 files) answers 'does it exist'.

## Extractor

Rules that matter for reading the tables:

- **Continuation lines.** §4's brace lists wrap across lines (`data/games/gen2_…{` … `species,…,charmap}.json`,
  and the `tools/{…}` group). A line is joined to the previous one only while the running brace
  count is unbalanced; brace expansion is cartesian and innermost-first, so
  `tools/{build_gen2_syms.py, gen_gen2_{…}.py, …}` expands correctly.
- **`|` inside a backticked token is an alternation with a shared stem:** `data/gen2/*.sym|.map`
  yields `data/gen2/*.sym` and `data/gen2/*.map` (an extension-only alternative inherits the
  previous alternative's stem). The PLAN writes these escaped as `\|` precisely so the markdown
  table survives, so cells are split on unescaped pipes only.
- **§4 ends with an ellipsis** (`tests/unit/test_gen2_{entry,…,codec,...}.py`). It is carried as
  `tests/unit/test_gen2_*.py` for membership tests and reported separately as OPEN-ENDED, because
  an open set cannot be compared mechanically.
- **Prefix elision.** §4 and the P3b lease both write the `_ot2` fixtures as
  `+ crystal_{town,battle}_ot2.SaveRAM` after a path that already carries the directory. A lease
  token without `/` also matches a layout path by suffix, and that match is labelled
  `suffix-elided` so it is never confused with a literal one.
- **Excluded, not paths:** `/to-spec`, `/to-tickets` (skill names), `rom.lua` (an exclusion inside
  P3b's `lua/gen2/*` parenthetical), `panel.lua` (shorthand for `lua/gen2/panel.lua`).

Run from the worktree root as `python -c <script>`; exit 0; throwaway, not committed.

```python
"""Throwaway layout-vs-lease auditor (gen2-A6).  python -c <this>, cwd = the worktree root."""
import re, subprocess, pathlib

WT = pathlib.Path(r"E:\Google Drive\SLink\.claude\worktrees\gen2-planning-kickoff-a18801")
def git(*args):
    r = subprocess.run(["git"] + list(args), cwd=str(WT), capture_output=True, encoding="utf-8", errors="replace")
    if r.stdout is None:
        r = subprocess.run(["git"] + list(args), cwd=str(WT), capture_output=True)
        return (r.stdout or b"").decode("utf-8", "replace")
    return r.stdout or ""

REV = "effcb6f"
PLAN = git("show", f"{REV}:docs/gen2/PLAN.md")
LINES = PLAN.splitlines()
EXISTING = set(git("ls-tree", "-r", "--name-only", REV).splitlines())
REPO_FILES = set(git("ls-tree", "-r", "--name-only", "HEAD").splitlines())

BRACE_INNER = re.compile(r'\{([^{}]*)\}')
def expand(tok):
    out = [tok]
    while True:
        nxt, changed = [], False
        for t in out:
            m = BRACE_INNER.search(t)
            if m:
                changed = True
                nxt.extend(BRACE_INNER.sub(a, t, count=1) for a in m.group(1).split(","))
            else:
                nxt.append(t)
        out = nxt
        if not changed:
            return [t for t in out if "..." not in t]

def glob_re(tok):
    res, i = "^", 0
    for m in re.finditer(r'\{([^{}]*)\}|\*', tok):
        res += re.escape(tok[i:m.start()])
        res += ".*" if m.group(0) == "*" else "(" + "|".join(re.escape(a) for a in m.group(1).split(",")) + ")"
        i = m.end()
    return re.compile(res + re.escape(tok[i:]) + "$")

# ── 1. §4 layout ────────────────────────────────────────────────────────────────
i4 = next(i for i, l in enumerate(LINES) if l.startswith("## 4."))
fence = [i for i in range(i4, i4 + 40) if LINES[i].strip() == "```"]
block = "\n".join(LINES[fence[0] + 1:fence[1]])
block = re.sub(r'\([^)]*\)', ' ', block)                       # drop prose parentheticals
block = BRACE_INNER.sub(lambda m: "{" + m.group(0)[1:-1].replace(" ", "") + "}", block)  # no spaces in braces
# a line continues the previous one only while the brace count is unbalanced
logical, buf = [], ""
for ln in block.splitlines():
    ln = ln.rstrip()
    if not ln.strip():
        continue
    if buf and buf.count("{") > buf.count("}"):
        buf += ln.strip()
    else:
        if buf:
            logical.append(buf)
        buf = ln.strip()
if buf:
    logical.append(buf)
raw_tokens = [t.strip() for ln in logical for t in re.split(r'\s{2,}|\s\+\s', ln) if t.strip()]
layout, layout_open = [], []
for t in raw_tokens:
    if "/" not in t and layout:
        d = layout[-1][0].rsplit("/", 1)[0] + "/"          # prefix-elided continuation (the _ot2 pair)
        t = d + t
    if "..." in t:
        glob = re.sub(r'\{[^}]*\}', "*", t).replace(",...", "*")
        layout_open.append((t, glob))
        continue
    for e in expand(t):
        layout.append((t, e.replace(" ", "")))
paths = sorted({e for _, e in layout})
glob_entries = sorted({e for e in paths if "*" in e})
ELLIPSIS = ['tests/unit/test_gen2_*.py']
print("LAYOUT TOKENS:", paths + glob_entries)

# ── 2. §6 phase leases ──────────────────────────────────────────────────────────
PHASE_RE = re.compile(r'\*\*(P[0-9a-z]+)\b')
i6 = next(i for i, l in enumerate(LINES) if l.startswith("## 6."))
leases = []
for l in LINES[i6:i6 + 20]:
    if not l.startswith("| **"):
        continue
    cells = re.split(r'(?<!\\)\|', l)
    cells = [c.replace("\\|", "|") for c in cells]
    if len(cells) < 4:
        continue
    m = PHASE_RE.search(cells[1])
    if not m:
        continue
    for tok in re.findall(r'`([^`]+)`', cells[3]):
        if "|" in tok and "/" in tok:
            pfx = tok.rsplit("/", 1)[0] + "/"
            alts = []
            for a in tok[len(pfx):].split("|"):
                a = a.strip()
                if a.startswith(".") and alts:
                    a = alts[-1].rsplit(".", 1)[0] + a     # *.sym|.map -> *.sym, *.map
                alts.append(a)
            alts = [pfx + a for a in alts]
        else:
            alts = [tok]
        for alt in alts:
            leases.append((m.group(1), alt))

EXCLUDE_TOKEN = {"/to-spec", "/to-tickets", "rom.lua", "panel.lua", ".map"}

def lease_matchers():
    out = []
    for phase, tok in leases:
        if tok in EXCLUDE_TOKEN:
            continue
        if "*" in tok or "{" in tok:
            out.append((phase, tok, glob_re(tok), True))
        else:
            out.append((phase, tok, None, False))
    return out
MATCH = lease_matchers()

def phases_for(path, sample=False):
    hit = []
    for phase, tok, rx, isg in MATCH:
        if tok == path:
            continue
        if "/" not in tok:
            if rx is None and path.endswith("/" + tok):
                hit.append((phase, tok, "suffix-elided"))
            elif rx is not None and rx.match(path.rsplit("/", 1)[-1]):
                hit.append((phase, tok, "suffix-elided (glob)"))
    if hit:
        return hit
    for phase, tok, rx, isg in MATCH:
        if rx is None:
            if tok == path:
                hit.append((phase, tok, "verbatim"))
        else:
            if rx.match(path):
                hit.append((phase, tok, "glob-vs-glob" if sample else "glob-covered"))
    # a glob layout path is matched against lease globs by a generated sample
    return hit

rows = []
for p in paths:
    isglob = "*" in p
    sample = p.replace("*", "SAMPLE")
    hit = phases_for(sample if isglob else p, sample=isglob)
    ph = sorted({h[0] for h in hit})
    verdict = "ORPHAN" if not ph else ("SINGLE" if len(ph) == 1 else "DUPLICATE")
    rows.append((p, ph, verdict, hit, isglob))
for tok, glob in layout_open:
    hit = phases_for(glob.replace("*", "SAMPLE"), sample=True)
    ph = sorted({h[0] for h in hit})
    rows.append((glob + "   (from ellipsis `" + tok + "`)", ph,
                 "ORPHAN" if not ph else ("SINGLE" if len(ph) == 1 else "DUPLICATE"), hit, True))

print("==== LAYOUT -> LEASE ====")
print("| # | §4 path | phase(s) | verdict | how |")
print("|---|---|---|---|---|")
for i, (p, ph, verdict, hit, isglob) in enumerate(rows, 1):
    how = "; ".join(f"{h[0]}:{h[2]}" for h in hit) or "-"
    print(f"| {i} | `{p}` | {', '.join(ph) if ph else '-'} | {verdict} | {how} |")
n_paths = len(rows)
orph = [r for r in rows if r[2] == "ORPHAN"]
dup = [r for r in rows if r[2] == "DUPLICATE"]
print()
print(f"layout entries={n_paths} (of which globs={len(glob_entries)}) orphan={len(orph)} duplicate={len(dup)}")

# ── 3. lease -> layout ──────────────────────────────────────────────────────────
print()
print("==== LEASE -> LAYOUT ====")
print("| # | phase | lease token | in §4 | exists at effcb6f | verdict |")
print("|---|---|---|---|---|---|")
undeclared = []
for phase, tok in leases:
    if tok in EXCLUDE_TOKEN:
        print(f"| - | {phase} | `{tok}` | n/a | n/a | EXCLUDED (not a path) |")
        continue
    if "/" not in tok and "." not in tok:
        print(f"| - | {phase} | `{tok}` | n/a | n/a | PROSE |")
        continue
    if "*" in tok or "{" in tok:
        rx = glob_re(tok)
        in4 = any(rx.match(e) for e in paths) or any(rx.match(g) for g in glob_entries)
        ex = any(rx.match(f) for f in EXISTING)
    else:
        in4 = (tok in paths or any(glob_re(g).match(tok) for g in glob_entries)
               or any(glob_re(g).match(tok) for g in ELLIPSIS))
        ex = tok in EXISTING
    verdict = "declared" if (in4 or ex) else "UNDECLARED"
    if verdict == "UNDECLARED":
        undeclared.append((phase, tok))
    print(f"| | {phase} | `{tok}` | {'YES' if in4 else 'NO'} | {'YES' if ex else 'NO'} | {verdict} |")
print()
print(f"lease tokens={len(leases)} undeclared={len(undeclared)}")
for u in undeclared:
    print("   UNDECLARED:", u[0], u[1])

# ── 4. cutover inventory ────────────────────────────────────────────────────────
print()
print("==== CUTOVER ====")
cut = "\n".join(LINES[fence[1] + 1:i6])
i_rep = next(i for i, l in enumerate(LINES) if "**REPLACE" in l)
i_rem = next(i for i, l in enumerate(LINES) if "**REMOVE" in l)
i_end = next(i for i in range(i_rem, len(LINES)) if not LINES[i].strip())
def near(pat, text):
    m = re.search(pat, text, re.S)
    return m.group(0) if m else ""
replace_txt = LINES[i_rep].split("**REPLACE", 1)[1].split("**REMOVE")[0]
remove_txt = "\n".join(LINES[i_rem:i_end])
def toks(txt):
    out = []
    for t in re.findall(r'`([^`]+)`', txt):
        if t.startswith("Gen 2 rows"):
            continue
        out.extend(expand(t))
    return out
rep, rem = toks(replace_txt), toks(remove_txt)
print("-- REPLACE")
print("| path | exists at effcb6f | in §4 | leased |")
print("|---|---|---|---|")
rep_miss = []
for t in rep:
    isg = "*" in t
    ex = any(glob_re(t).match(f) for f in EXISTING) if isg else (t in EXISTING)
    in4 = (any(glob_re(t).match(e) for e in paths + glob_entries) if isg else
           (t in paths or any(glob_re(g).match(t) for g in glob_entries)))
    lea = bool(phases_for(t.replace("*", "SAMPLE"), sample=isg))
    if not (ex and in4 and lea):
        rep_miss.append((t, ex, in4, lea))
    print(f"| `{t}` | {'YES' if ex else 'NO'} | {'YES' if in4 else 'NO'} | {'YES' if lea else 'NO'} |")
print()
print("-- REMOVE")
print("| path | exists at effcb6f |")
print("|---|---|")
rem_miss = []
for t in rem:
    isg = "*" in t or "{" in t
    ex = any(glob_re(t).match(f) for f in EXISTING) if isg else (t in EXISTING)
    if not ex:
        rem_miss.append(t)
    print(f"| `{t}` | {'YES' if ex else 'NO'} |")
print()
print(f"cutover: replace={len(rep)} remove={len(rem)} replace_misses={len(rep_miss)} remove_misses={len(rem_miss)}")
for m in rem_miss:
    print("   REMOVE-MISS:", m)
# extra: gen2 artefacts present at the cut that no list mentions
stale = [f for f in sorted(EXISTING) if re.search(r'(gen2|crystal)', f, re.I)
         and f.split("/")[0] in ("lua", "tools", "server", "tests", "data", "patch")
         and not any(glob_re(t).match(f) for t in rem + rep + glob_entries + paths)]
print()
print("gen2-named files at effcb6f not covered by any cutover/§4 token:", len(stale))
for s in stale[:40]:
    print("   ", s)
```

## Layout → lease

96 expanded entries: 94 concrete paths, 1 glob (`patch/gen2/src/*.asm`) and 1 open-ended ellipsis
entry. `phase(s)` lists every lease that covers the path (verbatim, by a lease glob, or by the
suffix rule).

| # | §4 path | phase(s) | verdict | how |
|---|---|---|---|---|
| 1 | `data/games/gen2_crystal/admission.json` | P1, P2, P4 | DUPLICATE | P1:glob-covered; P2:glob-covered; P4:glob-covered |
| 2 | `data/games/gen2_crystal/area_map.json` | P2 | SINGLE | P2:glob-covered |
| 3 | `data/games/gen2_crystal/charmap.json` | P2 | SINGLE | P2:glob-covered |
| 4 | `data/games/gen2_crystal/encounters.json` | P2 | SINGLE | P2:glob-covered |
| 5 | `data/games/gen2_crystal/engine_signals.json` | P2, P4 | DUPLICATE | P2:glob-covered; P4:glob-covered |
| 6 | `data/games/gen2_crystal/evos.json` | P2 | SINGLE | P2:glob-covered |
| 7 | `data/games/gen2_crystal/items.json` | P2 | SINGLE | P2:glob-covered |
| 8 | `data/games/gen2_crystal/profile.json` | P2, P4 | DUPLICATE | P2:glob-covered; P4:glob-covered |
| 9 | `data/games/gen2_crystal/species.json` | P2 | SINGLE | P2:glob-covered |
| 10 | `data/games/gen2_crystal/statics.json` | P2 | SINGLE | P2:glob-covered |
| 11 | `data/games/gen2_crystal/trainers.json` | P2 | SINGLE | P2:glob-covered |
| 12 | `data/games/gen2_crystal/write_checkpoint.json` | P2, P4 | DUPLICATE | P2:glob-covered; P4:glob-covered |
| 13 | `data/games/gen2_gold/admission.json` | P1, P2, P4 | DUPLICATE | P1:glob-covered; P2:glob-covered; P4:glob-covered |
| 14 | `data/games/gen2_gold/area_map.json` | P2 | SINGLE | P2:glob-covered |
| 15 | `data/games/gen2_gold/charmap.json` | P2 | SINGLE | P2:glob-covered |
| 16 | `data/games/gen2_gold/encounters.json` | P2 | SINGLE | P2:glob-covered |
| 17 | `data/games/gen2_gold/engine_signals.json` | P2, P4 | DUPLICATE | P2:glob-covered; P4:glob-covered |
| 18 | `data/games/gen2_gold/evos.json` | P2 | SINGLE | P2:glob-covered |
| 19 | `data/games/gen2_gold/items.json` | P2 | SINGLE | P2:glob-covered |
| 20 | `data/games/gen2_gold/profile.json` | P2, P4 | DUPLICATE | P2:glob-covered; P4:glob-covered |
| 21 | `data/games/gen2_gold/species.json` | P2 | SINGLE | P2:glob-covered |
| 22 | `data/games/gen2_gold/statics.json` | P2 | SINGLE | P2:glob-covered |
| 23 | `data/games/gen2_gold/trainers.json` | P2 | SINGLE | P2:glob-covered |
| 24 | `data/games/gen2_gold/write_checkpoint.json` | P2, P4 | DUPLICATE | P2:glob-covered; P4:glob-covered |
| 25 | `data/games/gen2_silver/admission.json` | P1, P2, P4 | DUPLICATE | P1:glob-covered; P2:glob-covered; P4:glob-covered |
| 26 | `data/games/gen2_silver/area_map.json` | P2 | SINGLE | P2:glob-covered |
| 27 | `data/games/gen2_silver/charmap.json` | P2 | SINGLE | P2:glob-covered |
| 28 | `data/games/gen2_silver/encounters.json` | P2 | SINGLE | P2:glob-covered |
| 29 | `data/games/gen2_silver/engine_signals.json` | P2, P4 | DUPLICATE | P2:glob-covered; P4:glob-covered |
| 30 | `data/games/gen2_silver/evos.json` | P2 | SINGLE | P2:glob-covered |
| 31 | `data/games/gen2_silver/items.json` | P2 | SINGLE | P2:glob-covered |
| 32 | `data/games/gen2_silver/profile.json` | P2, P4 | DUPLICATE | P2:glob-covered; P4:glob-covered |
| 33 | `data/games/gen2_silver/species.json` | P2 | SINGLE | P2:glob-covered |
| 34 | `data/games/gen2_silver/statics.json` | P2 | SINGLE | P2:glob-covered |
| 35 | `data/games/gen2_silver/trainers.json` | P2 | SINGLE | P2:glob-covered |
| 36 | `data/games/gen2_silver/write_checkpoint.json` | P2, P4 | DUPLICATE | P2:glob-covered; P4:glob-covered |
| 37 | `data/gen2/pokecrystal.map` | P1 | SINGLE | P1:glob-covered |
| 38 | `data/gen2/pokecrystal.sym` | P1 | SINGLE | P1:glob-covered |
| 39 | `data/gen2/pokecrystal11.map` | P1 | SINGLE | P1:glob-covered |
| 40 | `data/gen2/pokecrystal11.sym` | P1 | SINGLE | P1:glob-covered |
| 41 | `data/gen2/pokegold.map` | P1 | SINGLE | P1:glob-covered |
| 42 | `data/gen2/pokegold.sym` | P1 | SINGLE | P1:glob-covered |
| 43 | `data/gen2/pokesilver.map` | P1 | SINGLE | P1:glob-covered |
| 44 | `data/gen2/pokesilver.sym` | P1 | SINGLE | P1:glob-covered |
| 45 | `data/gen2_sources.lock.json` | P1 | SINGLE | P1:verbatim |
| 46 | `docs/gen2/gen2_engine_sites.md` | P2 | SINGLE | P2:verbatim |
| 47 | `docs/gen2/gen2_requirements.md` | P3b | SINGLE | P3b:verbatim |
| 48 | `lua/gen2/boxes.lua` | P3b | SINGLE | P3b:glob-covered |
| 49 | `lua/gen2/client.lua` | P3b, P4 | DUPLICATE | P3b:glob-covered; P4:verbatim |
| 50 | `lua/gen2/entry.lua` | P3b | SINGLE | P3b:glob-covered |
| 51 | `lua/gen2/panel.lua` | P3b, P4 | DUPLICATE | P3b:glob-covered; P4:glob-covered |
| 52 | `lua/gen2/reads.lua` | P3b | SINGLE | P3b:glob-covered |
| 53 | `lua/gen2/rom.lua` | P2, P3b | DUPLICATE | P2:verbatim; P3b:glob-covered |
| 54 | `lua/gen2/run.lua` | P3b | SINGLE | P3b:glob-covered |
| 55 | `lua/gen2/signals.lua` | P3b | SINGLE | P3b:glob-covered |
| 56 | `lua/gen2/trade_overlay.lua` | P3b, P4 | DUPLICATE | P3b:glob-covered; P4:glob-covered |
| 57 | `lua/gen2/writes.lua` | P3b | SINGLE | P3b:glob-covered |
| 58 | `lua/gen2_write_safety.lua` | P3b | SINGLE | P3b:verbatim |
| 59 | `patch/dist/SLink-Crystal.ups` | P4 | SINGLE | P4:glob-covered |
| 60 | `patch/dist/SLink-Gold.ups` | P4 | SINGLE | P4:glob-covered |
| 61 | `patch/dist/SLink-Silver.ups` | P4 | SINGLE | P4:glob-covered |
| 62 | `patch/gen2/README.md` | P6 | SINGLE | P6:suffix-elided |
| 63 | `patch/gen2/src/*.asm` | P4 | SINGLE | P4:glob-vs-glob |
| 64 | `patch/gen2/tools/build.py` | P4 | SINGLE | P4:glob-covered |
| 65 | `server/adapters/gen2_codec.py` | P3b | SINGLE | P3b:glob-covered |
| 66 | `server/adapters/gen2_gsc.py` | P3b | SINGLE | P3b:glob-covered |
| 67 | `server/adapters/gen2_rom_scan.py` | P2 | SINGLE | P2:verbatim |
| 68 | `tests/e2e/test_duo_gen2_new.py` | P3b | SINGLE | P3b:verbatim |
| 69 | `tests/fixtures/gen2/crystal_battle.SaveRAM` | P3b | SINGLE | P3b:glob-covered |
| 70 | `tests/fixtures/gen2/crystal_battle_ot2.SaveRAM` | P3b | SINGLE | P3b:suffix-elided (glob) |
| 71 | `tests/fixtures/gen2/crystal_town.SaveRAM` | P3b | SINGLE | P3b:glob-covered |
| 72 | `tests/fixtures/gen2/crystal_town_ot2.SaveRAM` | P3b | SINGLE | P3b:suffix-elided (glob) |
| 73 | `tests/fixtures/gen2/gold_battle.SaveRAM` | P3b | SINGLE | P3b:glob-covered |
| 74 | `tests/fixtures/gen2/gold_town.SaveRAM` | P3b | SINGLE | P3b:glob-covered |
| 75 | `tests/fixtures/gen2/receipts/` | P3b | SINGLE | P3b:glob-covered |
| 76 | `tests/fixtures/gen2/silver_battle.SaveRAM` | P3b | SINGLE | P3b:glob-covered |
| 77 | `tests/fixtures/gen2/silver_town.SaveRAM` | P3b | SINGLE | P3b:glob-covered |
| 78 | `tests/gen2_release_requirements.json` | P3b | SINGLE | P3b:verbatim |
| 79 | `tests/live/test_gen2_new_gates.py` | P3b | SINGLE | P3b:verbatim |
| 80 | `tools/build_gen2_syms.py` | P1 | SINGLE | P1:verbatim |
| 81 | `tools/gen2_fixtures.py` | P3b | SINGLE | P3b:verbatim |
| 82 | `tools/gen_gen2_admission.py` | P2 | SINGLE | P2:glob-covered |
| 83 | `tools/gen_gen2_area_map.py` | P2 | SINGLE | P2:glob-covered |
| 84 | `tools/gen_gen2_charmap.py` | P2 | SINGLE | P2:glob-covered |
| 85 | `tools/gen_gen2_encounters.py` | P2 | SINGLE | P2:glob-covered |
| 86 | `tools/gen_gen2_engine_signals.py` | P2 | SINGLE | P2:glob-covered |
| 87 | `tools/gen_gen2_evos.py` | P2 | SINGLE | P2:glob-covered |
| 88 | `tools/gen_gen2_items.py` | P2 | SINGLE | P2:glob-covered |
| 89 | `tools/gen_gen2_profile.py` | P2 | SINGLE | P2:glob-covered |
| 90 | `tools/gen_gen2_species.py` | P2 | SINGLE | P2:glob-covered |
| 91 | `tools/gen_gen2_statics.py` | P2 | SINGLE | P2:glob-covered |
| 92 | `tools/gen_gen2_trainers.py` | P2 | SINGLE | P2:glob-covered |
| 93 | `tools/gen_gen2_write_checkpoint.py` | P2 | SINGLE | P2:glob-covered |
| 94 | `tools/verify_gen2_release.py` | P2, P3b | DUPLICATE | P2:verbatim; P3b:verbatim |
| 95 | `tools/verify_gen2_rom_layout.py` | P2 | SINGLE | P2:verbatim |
| 96 | `tests/unit/test_gen2_*.py   (from ellipsis `tests/unit/test_gen2_{entry,reads,signals,writes,boxes,client,profile,engine_sites,codec,...}.py`)` | - | ORPHAN | - |

```text
layout entries=96 (94 concrete + 1 glob + 1 ellipsis)   SINGLE=78   DUPLICATE=17   ORPHAN=1
```

The single ORPHAN is the open-ended ellipsis entry itself (`tests/unit/test_gen2_*.py`), which no
lease can match by construction — **there are no concrete orphans.**

## Lease → layout (undeclared)

83 lease tokens (two excluded as non-paths). A token is *declared* if it appears in §4's layout
(including through the ellipsis), or if a file of that path exists at `effcb6f`.

| # | phase | lease token | in §4 | exists at effcb6f | verdict |
|---|---|---|---|---|---|
| | P0 | `docs/gen2/spec.md` | NO | NO | UNDECLARED |
| | P0 | `docs/gen2/issues/*` | NO | NO | UNDECLARED |
| - | P0 | `/to-spec` | n/a | n/a | EXCLUDED (not a path) |
| - | P0 | `/to-tickets` | n/a | n/a | EXCLUDED (not a path) |
| | P0 | `docs/gen2/PLAN.md` | NO | YES | declared |
| | P1 | `data/gen2_sources.lock.json` | YES | NO | declared |
| | P1 | `tools/build_gen2_syms.py` | YES | NO | declared |
| | P1 | `data/gen2/*.sym` | YES | NO | declared |
| | P1 | `data/gen2/*.map` | YES | NO | declared |
| | P1 | `.github/workflows/gen2-syms.yml` | NO | NO | UNDECLARED |
| | P1 | `tests/unit/test_gen2_build.py` | YES | NO | declared |
| | P1 | `data/games/gen2_*/admission.json` | YES | NO | declared |
| | P1 | `tools/build_pret_syms.py` | NO | YES | declared |
| | P2 | `data/games/gen2_{crystal,gold,silver}/*` | YES | YES | declared |
| | P2 | `tools/gen_gen2_*.py` | YES | YES | declared |
| | P2 | `tools/verify_gen2_rom_layout.py` | YES | NO | declared |
| | P2 | `docs/gen2/gen2_engine_sites.md` | YES | NO | declared |
| | P2 | `docs/gen2/gen2_coverage_map.md` | NO | NO | UNDECLARED |
| | P2 | `server/adapters/gen2_rom_scan.py` | YES | NO | declared |
| | P2 | `lua/gen2/rom.lua` | YES | NO | declared |
| | P2 | `tools/verify_gen2_release.py` | YES | NO | declared |
| | P2 | `tools/release_lanes.py` | NO | NO | UNDECLARED |
| - | P2 | `910dbdd` | n/a | n/a | PROSE |
| | P2 | `tests/unit/test_gen2_{profile,engine_sites,rom_tables,species,evos,encounters,write_checkpoint,admission,coverage_map}.py` | NO | NO | UNDECLARED |
| | P2 | `tools/gen2_coverage_map.py` | NO | NO | UNDECLARED |
| | P2 | `docs/shared-coverage-map.md` | NO | NO | UNDECLARED |
| | P2 | `tools/verify_profile_addresses.py` | NO | YES | declared |
| | P3a | `server/adapters/__init__.py` | NO | YES | declared |
| - | P3a | `_ROM_TYPE_TO_FOUNDATION` | n/a | n/a | PROSE |
| | P3a | `server/adapters/base.py` | NO | YES | declared |
| - | P3a | `pairing_kind` | n/a | n/a | PROSE |
| | P3a | `server/server.py` | NO | YES | declared |
| | P3a | `tests/unit/test_protocol_schema.py` | NO | YES | declared |
| | P3a | `tests/unit/protocol_schema.py` | NO | YES | declared |
| | P3a | `tests/unit/test_gen2_pairing_matrix.py` | YES | NO | declared |
| | P3a | `docs/protocol.md` | NO | YES | declared |
| | P3b | `lua/gen2/*` | YES | NO | declared |
| - | P3b | `rom.lua` | n/a | n/a | EXCLUDED (not a path) |
| | P3b | `lua/gen2_write_safety.lua` | YES | NO | declared |
| | P3b | `lua/slink.lua` | NO | YES | declared |
| | P3b | `server/adapters/{gen2_gsc,gen2_codec}.py` | YES | NO | declared |
| | P3b | `server/adapters/__init__.py` | NO | YES | declared |
| | P3b | `server/manager.py` | NO | YES | declared |
| | P3b | `tools/gen2_fixtures.py` | YES | NO | declared |
| | P3b | `tools/run_gb_gate.py` | NO | YES | declared |
| | P3b | `tools/e2e_duo.py` | NO | YES | declared |
| | P3b | `lua/tests/gen2_*.lua` | NO | YES | declared |
| | P3b | `tests/fixtures/gen2/{crystal,gold,silver}_{town,battle}.SaveRAM` | YES | YES | declared |
| | P3b | `crystal_{town,battle}_ot2.SaveRAM` | NO | NO | UNDECLARED |
| | P3b | `tests/fixtures/gen2/receipts/**` | YES | NO | declared |
| | P3b | `tests/unit/test_gen2_{codec,entry,reads,signals,writes,boxes,client,adapter,fixtures}.py` | NO | YES | declared |
| | P3b | `tests/live/test_gen2_new_gates.py` | YES | NO | declared |
| | P3b | `tests/e2e/test_duo_gen2_new.py` | YES | NO | declared |
| | P3b | `tools/verify_gen2_release.py` | YES | NO | declared |
| | P3b | `tests/gen2_release_requirements.json` | YES | NO | declared |
| | P3b | `docs/gen2/gen2_requirements.md` | YES | YES | declared |
| | P3b | `tools/make_release.py` | NO | YES | declared |
| | P3b | `tests/unit/test_make_release_manifest.py` | NO | YES | declared |
| | P4 | `patch/gen2/**` | YES | NO | declared |
| | P4 | `tools/build_gen2_companion.py` | NO | NO | UNDECLARED |
| | P4 | `patch/dist/SLink-{Gold,Silver,Crystal}.ups` | YES | NO | declared |
| | P4 | `data/gen2/*_slink.sym` | NO | NO | UNDECLARED |
| | P4 | `data/gen2/map` | NO | NO | UNDECLARED |
| | P4 | `data/games/gen2_*/{profile,engine_signals,write_checkpoint,admission}.json` | YES | NO | declared |
| | P4 | `lua/gen2/{trade_overlay,panel}.lua` | YES | NO | declared |
| - | P4 | `panel.lua` | n/a | n/a | EXCLUDED (not a path) |
| | P4 | `lua/sfx_arbiter.lua` | NO | YES | declared |
| | P4 | `lua/gen2/client.lua` | YES | NO | declared |
| | P4 | `tests/unit/test_gen2_client.py` | YES | NO | declared |
| | P4 | `server/patcher.py` | NO | YES | declared |
| | P4 | `tests/live/test_gen2_trade_gates.py` | NO | NO | UNDECLARED |
| | P4 | `tests/unit/test_gen2_overlay.py` | YES | NO | declared |
| | P5 | `patch/gen2/src/ghost*.asm` | NO | NO | UNDECLARED |
| | P5 | `lua/gen2/ghost.lua` | NO | NO | UNDECLARED |
| | P5 | `tests/live/test_gen2_ghost_gates.py` | NO | NO | UNDECLARED |
| | P5 | `tests/unit/test_gen2_ghost.py` | YES | NO | declared |
| | P5 | `docs/gen2/research/peer_ghost_design.md` | NO | YES | declared |
| | P6 | `README.md` | NO | YES | declared |
| | P6 | `docs/REFERENCE.md` | NO | YES | declared |
| | P6 | `tools/make_release.py` | NO | YES | declared |
| | P6 | `docs/historical/release_notes.md` | NO | YES | declared |
| | P6 | `server/manager.py` | NO | YES | declared |
| | P6 | `tools/gen_ui_capabilities.py` | NO | YES | declared |

```text
lease tokens=83 undeclared=16
   UNDECLARED: P0 docs/gen2/spec.md
   UNDECLARED: P0 docs/gen2/issues/*
   UNDECLARED: P1 .github/workflows/gen2-syms.yml
   UNDECLARED: P2 docs/gen2/gen2_coverage_map.md
   UNDECLARED: P2 tools/release_lanes.py
   UNDECLARED: P2 tests/unit/test_gen2_{profile,engine_sites,rom_tables,species,evos,encounters,write_checkpoint,admission,coverage_map}.py
   UNDECLARED: P2 tools/gen2_coverage_map.py
   UNDECLARED: P2 docs/shared-coverage-map.md
   UNDECLARED: P3b crystal_{town,battle}_ot2.SaveRAM
   UNDECLARED: P4 tools/build_gen2_companion.py
   UNDECLARED: P4 data/gen2/*_slink.sym
   UNDECLARED: P4 data/gen2/map
   UNDECLARED: P4 tests/live/test_gen2_trade_gates.py
   UNDECLARED: P5 patch/gen2/src/ghost*.asm
   UNDECLARED: P5 lua/gen2/ghost.lua
   UNDECLARED: P5 tests/live/test_gen2_ghost_gates.py
```

## Cutover list check

```text
==== CUTOVER ====
-- REPLACE
| path | exists at effcb6f | in §4 | leased |
|---|---|---|---|
| `tests/fixtures/gen2/crystal_town.SaveRAM` | YES | YES | YES |
| `tests/unit/test_gen2_adapter.py` | YES | NO | YES |
| `data/games/gen2_crystal/*` | YES | YES | YES |

-- REMOVE
| path | exists at effcb6f |
|---|---|
| `tests/fixtures/gen2/crystal_town.SaveRAM` | YES |
| `tests/unit/test_gen2_adapter.py` | YES |
| `data/games/gen2_crystal/*` | YES |
| `lua/clients/gen2_crystal_client.lua` | YES |
| `lua/memory_gb.lua` | YES |
| `lua/games/gen2_crystal.lua` | YES |
| `lua/games/gen2_crystal_trainers.lua` | YES |
| `lua/gen2_crystal_locations.lua` | YES |
| `lua/gen2_crystal_areas.lua` | YES |
| `lua/tests/gen2_playthrough.lua` | YES |
| `tools/gen2_playthrough.py` | YES |
| `server/adapters/gen2_crystal.py` | YES |
| `tests/unit/test_gen2_ap_addresses.py` | YES |
| `tests/unit/test_gen2_ball_items.py` | YES |
| `tests/live/test_gen2_gates.py` | YES |
| `tests/e2e/test_duo_gen2.py` | YES |
| `tools/verify_profile_addresses.py` | YES |
```

Sixteen of the 17 REMOVE paths exist and every one of them is a real file at `effcb6f`; the
seventeenth is the prose item "the Gen 2 rows of `tools/verify_profile_addresses.py`", whose file
exists (the rows, not the file, are what goes).

### Files the cutover lists do NOT mention (my own check, beyond the card's four steps)

`git ls-tree` at `effcb6f` filtered to `lua/`, `tools/`, `server/`, `tests/`, `data/`, `patch/` and
matched against every cutover token and every §4 path leaves **15 Gen 2 files that no list
removes and no list keeps**:

```text
    lua/slink_gen2.lua                     <- §5.11b says "no `lua/slink_gen2.lua` shim exists or is created"; it exists, 18 lines, unlisted
    lua/tests/probe_gen2_boot.lua          \
    lua/tests/probe_gen2_safestate.lua      | 14 probes/drivers the binding plan's §1 says are
    lua/tests/probe_gen2_save.lua           | "DELETE with their client" — the PLAN's REMOVE
    lua/tests/test_gen2_enemy_moves.lua     | list names only gen2_playthrough.lua
    lua/tests/test_gen2_force_faint.lua     |
    lua/tests/test_gen2_memory.lua          |
    lua/tests/test_gen2_memory_gate.lua     |
    lua/tests/test_gen2_moves.lua           |
    lua/tests/test_gen2_profile_audit.lua   |
    lua/tests/test_gen2_server.lua          |
    lua/tests/test_gen2_sfx.lua             |
    lua/tests/test_gen2_stat_stages.lua     |
    lua/tests/test_gen2_trainer_info.lua    |
    lua/tests/test_gen2_writes_gate.lua    /
```

## Summary

| check | result |
|---|---|
| §4 layout entries | 96 (94 concrete, 1 glob, 1 ellipsis) |
| ORPHAN | 1 — the ellipsis entry; 0 concrete |
| DUPLICATE | 17 |
| lease tokens examined | 83 (2 excluded as non-paths) |
| UNDECLARED | 16 |
| REPLACE paths | 3, all existing; 1 not literal in §4 (ellipsis-covered) |
| REMOVE paths | 17, all existing at effcb6f |
| cutover misses | 1, and it is the ellipsis case above |
| unlisted Gen 2 files at the cut | 15 |

What the three defect classes mean for /to-tickets:

1. **17 duplicates.** Twelve are the pack JSONs (`profile`, `engine_signals`, `write_checkpoint`,
   `admission` × three titles), where P2 owns the pack and P4 adds an overlay block to the same
   file; `admission.json` is also P1's matrix file, so it carries three phases. Plus
   `lua/gen2/{rom,panel,trade_overlay,client}.lua` (P2/P3b and P3b/P4) and
   `tools/verify_gen2_release.py` (P2 skeleton, P3b lanes filled). None is a contradiction — each
   is a scoped edit inside another phase's file — but the lease column cannot express it, and
   §7's "one writer per shared file" rule has to be applied by hand for every one of them.
2. **16 undeclared lease tokens.** Nine are files the rewrite creates that §4 never lists —
   `.github/workflows/gen2-syms.yml`, `docs/gen2/gen2_coverage_map.md`, `tools/release_lanes.py`,
   `tools/gen2_coverage_map.py`, `docs/shared-coverage-map.md`, `tools/build_gen2_companion.py`,
   `data/gen2/*_slink.sym|.map`, `tests/live/test_gen2_trade_gates.py`, and P5's
   `patch/gen2/src/ghost*.asm` + `lua/gen2/ghost.lua` + `tests/live/test_gen2_ghost_gates.py` and
   P0's `docs/gen2/spec.md` + `docs/gen2/issues/*`. Some are explainable (P0/P5 sit outside the
   rewrite's layout; `release_lanes.py` arrives with the pinned base cut), but
   `tools/build_gen2_companion.py`, the `_slink` symbol/map pair and the trade-gate test are P4
   deliverables that §4's own layout should carry.
3. **The cutover leaves 15 files behind**, including the shim §5.11b explicitly says is not
   created. This is the inverse of the card's check and the one with teeth: the post-deletion
   tree keeps Gen 2 probes that the binding plan says are deleted with their client.

DONE gen2-A6: 96 layout paths, 1 orphans, 17 duplicates, 16 undeclared, 1 cutover misses
