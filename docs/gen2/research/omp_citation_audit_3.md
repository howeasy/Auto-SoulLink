# gen2-A5 — citation resolver + lease subset check over the rewritten binding plan

**Historical record.** This is a mechanical citation check against `GEN2_BINDING_PLAN.md` frozen at
commit `874b2b2` — it does not judge or restate current facts. Some cited lines quote the
now-retired `gen2_crystal` adapter (`server/adapters/__init__.py`); that adapter was removed at the
P3b.8 cutover (see `_RETIRED_GAME_IDS` in that file). Current Gen 2 is served by `gen2_gsc.py` +
`gen2_codec.py` + `gen2_rom_scan.py`. Treat every "resolves"/citation verdict below as scoped to the
`874b2b2` snapshot, not present-day code.

Frozen input: `git show 874b2b2:docs/gen2/GEN2_BINDING_PLAN.md` (635 lines) and
`git show 874b2b2:docs/gen2/PLAN.md` (293 lines, read for the lease comparison). Neither was
modified. Nothing here judges the plan's logic; it measures whether its citations land and
whether each substep's exclusive files sit inside its phase lease.

## Extractor

Identical engine to gen2-A4 (anchored discriminators, `pokegold`/`Gold` only immediately
before or after the path, `SWEEP`/`gen3-…` only immediately before it, bare basenames looked
up in this worktree first with `.claude`/`.cache`/`build`/`dist`/`node_modules` excluded from
the RELATIVE path so archived worktree copies cannot shadow the live file), plus the lease
check the card adds. Run from the worktree root as `python -c <script>`; exit 0; 256 lines;
throwaway, not committed.

Lease check, in one line: for every substep row of §5, every backticked path in its *Exclusive*
files* cell is tested against (a) the PLAN §6 phase row named in that phase's heading, verbatim,
(b) any brace/star glob in that row, and (c) a `Card lease:` named in the same substep's 5.15
cell. A token with no `/`, no file extension and no `SaveRAM` is classed `n/a` (prose), not a
pass or a fail.

```python
"""Throwaway citation resolver, pass 2 (gen2-A4).  python -c <this>, cwd = the worktree root.

Same engine as gen2-A3 with two additions this pair of documents needs: a `pokecrystal@<sha>` /
`pokegold@<sha>` prefix selects the pret repo, and a bare basename (no "/") is looked up in this
worktree first, exactly as `gen2_crystal_client.lua:539-568` means `lua/clients/...`.
Keyword rule, unchanged and literal: nearest backticked span before the citation that is not a
path, a "§" ref, a number/hex, an sha, a review id, a worktree name or a `repo@sha` pin; a span
holding a code fragment with spaces contributes its last word.
"""
import re, subprocess, pathlib

WT    = pathlib.Path(r"E:\Google Drive\SLink\.claude\worktrees\gen2-planning-kickoff-a18801")
SWEEP = pathlib.Path(r"E:\Google Drive\SLink\.claude\worktrees\gen1-rby-code-sweep-8d06e2")
GEN3  = pathlib.Path(r"E:\Google Drive\SLink\.claude\worktrees\gen3-migration-planning-5d8e45")
PC    = pathlib.Path(r"C:\Users\howar\AppData\Local\Temp\claude\E--Google-Drive-SLink--claude-worktrees-gen2-planning-kickoff-a18801\17c55ba3-97ae-4ed8-ba47-396926dd84c9\scratchpad\pret_head\pokecrystal")
PG    = pathlib.Path(r"C:\Users\howar\AppData\Local\Temp\claude\E--Google-Drive-SLink--claude-worktrees-gen2-planning-kickoff-a18801\17c55ba3-97ae-4ed8-ba47-396926dd84c9\scratchpad\pret_head\pokegold")
REV   = "874b2b2"
DOCS  = [("GEN2_BINDING_PLAN", "874b2b2", "docs/gen2/GEN2_BINDING_PLAN.md")]

def sh(args, cwd):
    r = subprocess.run(args, cwd=str(cwd), capture_output=True, encoding="utf-8", errors="replace")
    return r.stdout or "", r.returncode

_cache = {}
def git_show(rev, path, cwd=WT):
    key = (str(cwd), rev, path)
    if key not in _cache:
        _cache[key] = sh(["git", "show", f"{rev}:{path}"], cwd)
    return _cache[key]

SKIP = {".git", ".claude", ".cache", "node_modules", "__pycache__", "dist", "build"}
EXT = (".asm", ".py", ".lua", ".md", ".json", ".yml", ".cs", ".txt")
def wt_index():
    idx = {}
    for p in WT.rglob("*"):
        rel = p.relative_to(WT)
        if any(part in SKIP for part in rel.parts):   # .claude/.git *inside* the tree
            continue
        if p.is_file() and (p.suffix in EXT or p.name == "Makefile"):
            idx.setdefault(p.name, []).append(str(rel).replace("\\", "/"))
    return {k: sorted(v) for k, v in idx.items()}
IDX = wt_index()

CITE = re.compile(r'(?:(?P<repo>pokecrystal@[0-9a-f]{7}|pokegold@[0-9a-f]{7})\s+)?'
                  r'(?P<path>[A-Za-z0-9_.\-/]*(?:\.(?:asm|py|lua|md|json|yml|cs|txt)|Makefile))'
                  r':(?P<a>\d+)(?:-(?P<b>\d+))?')
CONT_RANGE = re.compile(r'\s*,\s*(\d+)(?:-(\d+))?')
TOKEN      = re.compile(r'`([^`]+)`')
HEXVAL     = re.compile(r'^(0x[0-9A-Fa-f]+|\d+)$')
SHA        = re.compile(r'^[0-9a-f]{7,}(?:…|\.\.\.)?$')
REVIEW_ID  = re.compile(r'^cx-[0-9a-f]+$')
REPO_PIN   = re.compile(r'^(pokecrystal|pokegold)@|^SWEEP$')
WORKTREES  = {"gen3-migration-planning-5d8e45", "gen1-rby-code-sweep-8d06e2"}

def keyword_before(line, pos):
    best = None
    for m in TOKEN.finditer(line[:pos]):
        t = m.group(1).strip()
        if not t or "." in t or "/" in t or ":" in t or t.startswith("§"):
            continue
        if HEXVAL.match(t) or SHA.match(t) or REVIEW_ID.match(t) or REPO_PIN.match(t) or t in WORKTREES:
            continue
        if " " in t:
            w = [x for x in re.split(r'[^A-Za-z0-9_]+', t) if x]
            if not w:
                continue
            t = w[-1]
        best = t
    return best

def pret_candidates(root, path):
    if "/" in path:
        return [path] if (root / path).exists() else []
    return sorted(str(x.relative_to(root)).replace("\\", "/") for x in root.rglob(path) if x.name == path)

rows = []
for tag, rev, docpath in DOCS:
    text, _ = git_show(rev, docpath)
    for ln_no, line in enumerate(text.splitlines(), 1):
        for m in CITE.finditer(line):
            a, b = int(m.group("a")), int(m.group("b") or 0)
            tail = line[m.end():m.end() + 90]
            insts = [(a, b)]
            t = tail
            while True:
                c = CONT_RANGE.match(t)
                if not c: break
                insts.append((int(c.group(1)), int(c.group(2) or 0))); t = t[c.end():]
            for a2, b2 in insts:
                rows.append(dict(doc=tag, docline=ln_no, path=m.group("path"), repo=m.group("repo"),
                                 a=a2, b=b2, line=line, pos=m.start("path")))

def locate(r):
    p = r["path"]
    if r["repo"]:
        return ("pokecrystal" if r["repo"].startswith("pokecrystal") else "pokegold"), [p]
    pre = r["line"][:r["pos"]]
    if p.startswith("gen3-migration-planning-5d8e45/"):
        return "gen3", [p.split("/", 1)[1]]
    if re.search(r'gen3-migration-planning-5d8e45[`\s]*$', pre[-40:]):
        return "gen3", [p]
    if re.search(r'SWEEP[`\s]*$', pre):
        return "SWEEP", [p]
    if p.startswith("research/"):
        return "research", [p]
    if "/" in p:
        return ("worktree", [p]) if ((WT / p).exists() or git_show(REV, p)[1] == 0) else ("pokecrystal", pret_candidates(PC, p))
    if p in IDX:
        return "worktree", IDX[p]
    return "pokecrystal", pret_candidates(PC, p)

def read(label, rel):
    if label == "worktree": return git_show(REV, rel)[0]
    if label == "pokecrystal": return (PC / rel).read_text(encoding="utf-8", errors="replace") if (PC / rel).exists() else ""
    if label == "pokegold":    return (PG / rel).read_text(encoding="utf-8", errors="replace") if (PG / rel).exists() else ""
    if label == "gen3":        return (GEN3 / rel).read_text(encoding="utf-8", errors="replace") if (GEN3 / rel).exists() else ""
    if label == "SWEEP":       return (SWEEP / rel).read_text(encoding="utf-8", errors="replace") if (SWEEP / rel).exists() else ""
    if label == "research":    return (WT / "docs" / "gen2" / rel).read_text(encoding="utf-8", errors="replace") if (WT / "docs" / "gen2" / rel).exists() else ""
    return ""

for r in rows:
    label, cands = locate(r)
    r["root"], r["cands"], r["ambig"] = label, cands, len(cands) > 1
    r["rel"] = cands[0] if cands else r["path"]
    text = read(label, r["rel"]) if cands else ""
    r["exists"], r["nlines"] = bool(text), len(text.splitlines())
    r["resolves"] = bool(text) and r["a"] <= r["nlines"] and (not r["b"] or r["b"] <= r["nlines"])
    r["kw"] = keyword_before(r["line"], r["pos"])
    r["kw_at"], r["kw_near"], r["cited_text"] = "UNKNOWN", "-", ""
    if r["kw"]:
        word = re.compile(r'(?<![A-Za-z0-9_])' + re.escape(r["kw"]) + r'(?![A-Za-z0-9_])')
        for cand in cands:
            t2 = read(label, cand)
            if not t2: continue
            ls = t2.splitlines()
            hi = min(r["b"] or r["a"], len(ls))
            body = " / ".join(l.strip()[:80] for l in ls[r["a"] - 1:hi])
            if any(word.search(l) for l in ls[r["a"] - 1:hi]):
                r["kw_at"], r["cited_text"] = "YES", body
                break
            if r["kw_at"] != "NO":
                near = next((i for i, l in enumerate(ls, 1) if word.search(l)), None)
                decl = next((i for i, l in enumerate(ls, 1)
                             if re.match(r'^\s*' + re.escape(r["kw"]) + r'::?\s*$', l)), None)
                r["kw_at"], r["kw_near"], r["cited_text"] = "NO", \
                    f"{near or '-'}" + (f" (decl {decl})" if decl and decl != near else ""), body
    elif text:
        ls = text.splitlines()
        hi = min(r["b"] or r["a"], len(ls))
        r["cited_text"] = " / ".join(l.strip()[:80] for l in ls[r["a"] - 1:hi])

script_text = git_show("874b2b2", "docs/gen2/GEN2_BINDING_PLAN.md")[0]


PLAN_TEXT = git_show("874b2b2", "docs/gen2/PLAN.md")[0]
PLAN_LINES = PLAN_TEXT.splitlines()
PHASE_RE = re.compile(r'^### (P[0-9a-z]+) — .*?phase lease `docs/gen2/PLAN\.md:(\d+)`', re.M)
PATHISH = re.compile(r'(/|\.(?:py|lua|json|md|yml|asm|txt|lock|ups)$|SaveRAM)')
BRACE = re.compile(r'\{([^}]*)\}')

def glob_to_re(tok):
    res, i = "^", 0
    for m in re.finditer(r'\{([^}]*)\}|\*', tok):
        res += re.escape(tok[i:m.start()])
        res += ".*" if m.group(0) == "*" else "(" + "|".join(re.escape(a) for a in m.group(1).split(",")) + ")"
        i = m.end()
    return re.compile(res + re.escape(tok[i:]) + "$")

def expand(tok):
    out = [tok]
    while True:
        nxt, changed = [], False
        for t in out:
            m = BRACE.search(t)
            if m:
                changed = True
                nxt.extend(BRACE.sub(a, t, count=1) for a in m.group(1).split(","))
            else:
                nxt.append(t)
        out = nxt
        if not changed:
            return out

sections = [(m.group(1), int(m.group(2)), m.start(), m.end()) for m in PHASE_RE.finditer(script_text)]
bounds = [(s[0], s[1], s[3], sections[i+1][2] if i+1 < len(sections) else len(script_text)) for i, s in enumerate(sections)]
lease_rows, phase_anchor = [], []
for phase, plan_line, a, b in bounds:
    body, plan_row = script_text[a:b], PLAN_LINES[plan_line - 1]
    phase_anchor.append((phase, plan_line, plan_row.startswith("| **" + phase), plan_row))
    globs = [(t, glob_to_re(t)) for t in re.findall(r'`([^`]+)`', plan_row) if ("*" in t or "{" in t)]
    for line in body.splitlines():
        if not line.startswith("| **" + phase + "."): continue
        cells = line.replace("\\|", "|").split("|")
        if len(cells) < 5: continue
        substep = cells[1].strip().strip("*").split("*")[0].strip()
        files_cell, card_cell = cells[3], cells[4]
        card_lease = card_cell.split("Card lease:", 1)[1] if "Card lease:" in card_cell else ""
        for tok in re.findall(r'`([^`]+)`', files_cell):
            if not PATHISH.search(tok) or tok.startswith("docs/gen2/PLAN.md"):
                lease_rows.append((phase, substep, tok, "n/a", "prose / section ref")); continue
            variants = expand(tok)
            if all(v in plan_row for v in variants):
                lease_rows.append((phase, substep, tok, "YES", "verbatim in PLAN §6 row")); continue
            hit = ""
            for v in variants:
                for gt, gr in globs:
                    if gr.match(v): hit = gt; break
                if hit: break
            if hit:
                lease_rows.append((phase, substep, tok, "YES", f"covered by PLAN §6 glob `{hit}`")); continue
            if card_lease and any(v in card_lease for v in variants):
                lease_rows.append((phase, substep, tok, "YES", "5.15 card lease")); continue
            lease_rows.append((phase, substep, tok, "NO", ""))

print()
print("==== LEASE CHECK ====")
print("| substep | file | in PLAN §6 phase row | where |")
print("|---|---|---|---|")
for phase, substep, tok, verdict, where in lease_rows:
    print(f"| {substep} | `{tok}` | {verdict} | {where} |")
print()
print("phase anchors:", [(p, ln, ok) for p, ln, ok, _ in phase_anchor])
chk = [r for r in lease_rows if r[3] != "n/a"]
print(f"LEASE tokens={len(lease_rows)} checked={len(chk)} verbatim={sum('verbatim' in r[4] for r in chk)} "
      f"glob={sum('glob' in r[4] for r in chk)} card={sum('card' in r[4] for r in chk)} "
      f"MISS={sum(r[3]=='NO' for r in chk)} prose={len(lease_rows)-len(chk)}")
print("misses:")
for r in chk:
    if r[3] == "NO": print("   ", r[1], "|", r[2])

def markdown(tag):
    out = ["| # | citation | file (root:path) | resolves | keyword | keyword at cited line | nearest occurrence | cited line text |",
           "|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate([x for x in rows if x["doc"] == tag], 1):
        cite = f"`{r['path']}:{r['a']}" + (f"-{r['b']}`" if r["b"] else "`")
        fl = f"`{r['root']}:{r['rel']}`" + (f" **AMBIG({len(r['cands'])})**" if r["ambig"] else "")
        st = "**AMBIG**" if r["ambig"] else ("YES" if r["resolves"] else "**NO**")
        txt = r["cited_text"].replace("|", "\\|")[:58]
        out.append(f"| {i} | {cite} | {fl} | {st} | `{r['kw'] or 'KEYWORD_UNKNOWN'}` | {r['kw_at']} | {r['kw_near']} | {txt} |")
    return "\n".join(out)
print(markdown("GEN2_BINDING_PLAN"))
print()
rs = rows
print(f"TOTAL n={len(rs)} resolved={sum(r['resolves'] for r in rs)} unresolved={sum(not r['resolves'] for r in rs)} "
      f"ambiguous={sum(r['ambig'] for r in rs)} kw_YES={sum(r['kw_at']=='YES' for r in rs)} "
      f"kw_NO={sum(r['kw_at']=='NO' for r in rs)} kw_UNKNOWN={sum(r['kw_at']=='UNKNOWN' for r in rs)}")
print()
print("---- unresolved / ambiguous ----")
for r in rows:
    if not r["resolves"] or r["ambig"]:
        print(f"{r['doc']}:{r['docline']} {r['path']}:{r['a']}-{r['b']} -> {r['root']}:{r['rel']} exists={r['exists']} nlines={r['nlines']} cands={r['cands']}")
print()
print("---- kw_NO rows ----")
for r in rows:
    if r["kw_at"] == "NO":
        print(f"{r['doc']}:{r['docline']} {r['path']}:{r['a']}{'-'+str(r['b']) if r['b'] else ''} | kw={r['kw']} | near={r['kw_near']} | {r['cited_text'][:150]}")
```

## Table

310 citation instances. `keyword` is the nearest backticked identifier before the citation;
`keyword at cited line` is a word-boundary search inside the cited range; `cited line text` is
the range itself, which is the column to read — the keyword column is noise-tolerant by
construction (157 rows are KEYWORD_UNKNOWN because the identifier and the citation sit on
different lines or in different table cells).

| # | citation | file (root:path) | resolves | keyword | keyword at cited line | nearest occurrence | cited line text |
|---|---|---|---|---|---|---|---|
| 1 | `docs/gen2/REVIEW_RECORD.md:15` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| O-1 \| "This will lead into implementation" \| Destinat |
| 2 | `docs/gen2/REVIEW_RECORD.md:16` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| O-2 \| "Include GSC. Crystal is most important but all  |
| 3 | `docs/gen2/REVIEW_RECORD.md:17` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| O-3 \| "Trash Gen2 code once we replace it. Gen1 is can |
| 4 | `docs/gen2/REVIEW_RECORD.md:18` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| O-4 \| "All native feature should exist in first RC" \| |
| 5 | `docs/gen2/REVIEW_RECORD.md:19` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| O-5 \| "Move to fresh upstream HEAD" \| Pins: pokecryst |
| 6 | `docs/gen2/research/archipelago_crystal.md:369-373` | `worktree:docs/gen2/research/archipelago_crystal.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | **Exact clone URL + sha the implementation phase should pi |
| 7 | `docs/gen2/REVIEW_RECORD.md:20` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| O-6 \| "Gen2 new ledger" \| `docs/gen2/gen2_requirement |
| 8 | `docs/gen2/REVIEW_RECORD.md:21` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| O-10 \| "We can inject balls for tests and validation"  |
| 9 | `docs/gen2/REVIEW_RECORD.md:23-24` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| O-12 \| "We can use whatever the local dump is" (Crysta |
| 10 | `docs/gen2/REVIEW_RECORD.md:44` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | afterwards and the wram delta is confined to the `wLinkDat |
| 11 | `lua/clients/gen2_crystal_client.lua:5` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | Forked from the (since-retired) legacy Gen 1 client with G |
| 12 | `lua/slink_gen1.lua:17-18` | `worktree:lua/slink_gen1.lua` | YES | `dofile` | YES | - | local _dir = debug.getinfo(1, "S").source:match("@(.+[/\\] |
| 13 | `docs/gen2/PLAN.md:172` | `worktree:docs/gen2/PLAN.md` | YES | `dofile` | NO | 82 | \| **P3b Client + adapter + codec + harness (rules qualifi |
| 14 | `server/adapters/__init__.py:54-57` | `worktree:server/adapters/__init__.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | # Gen 2. `lua/games/gen2_crystal.lua:rom_type_for_variant` |
| 15 | `server/adapters/__init__.py:64-65` | `worktree:server/adapters/__init__.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | "Gold": "gen2_crystal", "gold": "gen2_crystal", / "Silver" |
| 16 | `lua/games/gen2_crystal.lua:13` | `worktree:lua/games/gen2_crystal.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | M.display_name = "Crystal / Gold / Silver" |
| 17 | `data/wild/johto_grass.asm:341-364` | `pokegold:data/wild/johto_grass.asm` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | def_grass_wildmons NATIONAL_PARK / db 10 percent, 10 perce |
| 18 | `docs/gen2/REVIEW_RECORD.md:40` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - |  |
| 19 | `server/adapters/__init__.py:59-62` | `worktree:server/adapters/__init__.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | # Gold, Silver and Crystal (AP) were MISSING here, and the |
| 20 | `lua/clients/gen2_crystal_client.lua:40` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | NOT YET IMPLEMENTED (Gen 1 has them): trainer_battle_start |
| 21 | `lua/gen1/entry.lua:302-308` | `worktree:lua/gen1/entry.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | local L = function(rel) return dofile(root .. "/" .. rel)  |
| 22 | `lua/gen1/run.lua:14-16` | `worktree:lua/gen1/run.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | local Entry = dofile(ROOT .. "/lua/gen1/entry.lua") / loca |
| 23 | `server/server.py:416-430` | `worktree:server/server.py` | YES | `_handle_trainer_battle_start` | NO | - | from server.adapters import game_id_for_rom_type, get_adap |
| 24 | `docs/protocol.md:432-452` | `worktree:docs/protocol.md` | YES | `game_id` | YES | - | \| `game_id` \| property → str \| abstract \| registry key |
| 25 | `server/adapters/gen1_rby.py:265` | `worktree:server/adapters/gen1_rby.py` | YES | `Gen1Adapter(GameAdapter)` | YES | - | class Gen1Adapter(GameAdapter): |
| 26 | `gen1_purergb.py:66` | `worktree:server/adapters/gen1_purergb.py` | YES | `Gen1PureRGBAdapter(Gen1Adapter)` | YES | - | class Gen1PureRGBAdapter(Gen1Adapter): |
| 27 | `server/adapters/base.py:559` | `worktree:server/adapters/base.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | def gb_status_token(status_cond: int) -> str: |
| 28 | `gen1_rby.py:356-358` | `worktree:server/adapters/gen1_rby.py` | YES | `gb_status_token` | YES | - | def status_token(self, status_cond: int) -> str: / # const |
| 29 | `gen1_rby.py:14` | `worktree:server/adapters/gen1_rby.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - |  |
| 30 | `constants/pokemon_constants.asm:171-174` | `pokecrystal:constants/pokemon_constants.asm` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | const MEWTWO     ; 96 / const MEW        ; 97 / DEF JOHTO_ |
| 31 | `constants/pokemon_constants.asm:273-274` | `pokecrystal:constants/pokemon_constants.asm` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | const CELEBI     ; fb / DEF NUM_POKEMON EQU const_value -  |
| 32 | `gen1_rby.py:472` | `worktree:server/adapters/gen1_rby.py` | YES | `rom_content_fingerprint` | YES | - | def rom_content_fingerprint(self, payload: dict) -> str \| |
| 33 | `lua/gen1/run.lua:15` | `worktree:lua/gen1/run.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | local C = require("connector") |
| 34 | `lua/gen1/entry.lua:371` | `worktree:lua/gen1/entry.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | net = deps.net, json = json, hud = deps.hud, io = bio, |
| 35 | `lua/gen1/entry.lua:303` | `worktree:lua/gen1/entry.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | local json = L("lua/json_codec.lua") |
| 36 | `lua/gen1/run.lua:31` | `worktree:lua/gen1/run.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | root = ROOT, json = dofile(ROOT .. "/lua/json_codec.lua"), |
| 37 | `lua/gen1/run.lua:16` | `worktree:lua/gen1/run.lua` | YES | `sanitize` | NO | - | local H = require("hud") |
| 38 | `lua/gen1/entry.lua:366` | `worktree:lua/gen1/entry.lua` | YES | `sanitize` | YES | - | panel = P.new(profile, panel_io, writes, deps.hud and deps |
| 39 | `lua/slink.lua:83-85` | `worktree:lua/slink.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- No gen1_rby row: the Gen 1 route above returns before t |
| 40 | `docs/FRAMEWORK.md:251-252` | `SWEEP:docs/FRAMEWORK.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| `lua/mailbox.lua` (536) \| header (:1-9): RR companion- |
| 41 | `docs/protocol.md:491-516` | `worktree:docs/protocol.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | ## 8. Gen 3-isms baked into shared code /  / Things a non- |
| 42 | `docs/gen2/PLAN.md:151-161` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| 5.15 \| **Shared-module extraction rule (owner 2026-09- |
| 43 | `lua/gen1/entry.lua:44` | `worktree:lua/gen1/entry.lua` | YES | `Silver` | NO | - | Entry.PACKS = { |
| 44 | `lua/gen1/entry.lua:58` | `worktree:lua/gen1/entry.lua` | YES | `Silver` | NO | - | Entry.PACK_FILES = { |
| 45 | `lua/gen1/entry.lua:133` | `worktree:lua/gen1/entry.lua` | YES | `Silver` | NO | - | function Entry.admission_table(root, json) |
| 46 | `lua/gen1/entry.lua:197` | `worktree:lua/gen1/entry.lua` | YES | `Silver` | NO | - | function Entry.anchor_matches(args, header) |
| 47 | `lua/gen1/entry.lua:229` | `worktree:lua/gen1/entry.lua` | YES | `Silver` | NO | - | function Entry.admit(args) |
| 48 | `lua/gen1/entry.lua:300` | `worktree:lua/gen1/entry.lua` | YES | `Silver` | NO | - | function Entry.build(deps) |
| 49 | `lua/gen1/entry.lua:394` | `worktree:lua/gen1/entry.lua` | YES | `Silver` | NO | - | function Entry.detect_title(read_rom_u8) |
| 50 | `lua/gen1/entry.lua:403` | `worktree:lua/gen1/entry.lua` | YES | `Silver` | NO | - | function Entry.bizhawk_deps() |
| 51 | `lua/gen1/run.lua:1-16` | `worktree:lua/gen1/run.lua` | YES | `"GB"` | NO | - | -- lua/gen1/run.lua — BizHawk entry for the Gen 1 client.  |
| 52 | `lua/gen1/client.lua:135` | `worktree:lua/gen1/client.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | function Client.new(p) |
| 53 | `lua/gen1/reads.lua:1-4` | `worktree:lua/gen1/reads.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- Pure Gen 1 reads over a pret-generated title profile an |
| 54 | `lua/gen1/signals.lua:1-16` | `worktree:lua/gen1/signals.lua` | YES | `EraseBoxes` | NO | - | -- lua/gen1/signals.lua — Gen 1 game events detected from  |
| 55 | `lua/gen1/writes.lua:1-16` | `worktree:lua/gen1/writes.lua` | YES | `wPlayerSelectedMove` | YES | - | -- lua/gen1/writes.lua — every byte the Gen 1 client write |
| 56 | `lua/gen1/boxes.lua:1-11` | `worktree:lua/gen1/boxes.lua` | YES | `SaveBox` | NO | - | -- Gen 1 PC moves. All writes go through the caller's arme |
| 57 | `lua/gen1/rom.lua:1-11` | `worktree:lua/gen1/rom.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- lua/gen1/rom.lua — the two ROM tables the client needs, |
| 58 | `lua/gen1/panel.lua:16` | `worktree:lua/gen1/panel.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | local MAILBOX = 0xDEE2 |
| 59 | `lua/gen1/panel.lua:19` | `worktree:lua/gen1/panel.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | local SFX     = MAILBOX + 7                 -- SLINK_SFX_R |
| 60 | `lua/gen1/panel.lua:24-25` | `worktree:lua/gen1/panel.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | local OFF_ABI, OFF_SFX, OFF_CAPS, OFF_STATE, OFF_PAGE, OFF |
| 61 | `lua/gen1/panel.lua:45-48` | `worktree:lua/gen1/panel.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | P.MAILBOX, P.CAPS, P.STATE, P.PAGE, P.PAGES, P.SFX = MAILB |
| 62 | `lua/gen1/trade_overlay.lua:5-7` | `worktree:lua/gen1/trade_overlay.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | local MAGIC = {0x53, 0x4C, 0x54, 0x31} -- trade_service.as |
| 63 | `lua/gen1_write_safety.lua:14-15` | `worktree:lua/gen1_write_safety.lua` | YES | `-purergb-v1` | NO | - | M.VERSION = "gen1-main-loop-v1" / M.VERSION_PURERGB = "gen |
| 64 | `lua/gen1_write_safety.lua:1-15` | `worktree:lua/gen1_write_safety.lua` | YES | `-purergb-v1` | NO | - | -- A read-only Gen 1 main-thread checkpoint. This does not |
| 65 | `docs/gen2/PLAN.md:149` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| 5.12 \| **Native features on a surveyed mailbox.** Pane |
| 66 | `lua/gen1/panel.lua:19` | `worktree:lua/gen1/panel.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | local SFX     = MAILBOX + 7                 -- SLINK_SFX_R |
| 67 | `lua/gen1/panel.lua:25` | `worktree:lua/gen1/panel.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | local CAP_SFX   = 0x01                      -- SLINK_CAP_S |
| 68 | `lua/gen1/panel.lua:28-34` | `worktree:lua/gen1/panel.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- slink.asm SlinkSfxService: what the request byte may ca |
| 69 | `lua/gen1/panel.lua:144-161` | `worktree:lua/gen1/panel.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | local function post_sfx(code) / if u8(SFX) ~= 0 then retur |
| 70 | `server/adapters/base.py:204` | `worktree:server/adapters/base.py` | YES | `gym_badge_slugs` | NO | 538 | def rival_trainer_ids(self) -> set[int]: |
| 71 | `server/adapters/base.py:220` | `worktree:server/adapters/base.py` | YES | `gym_badge_slugs` | NO | 538 | def party_blob_size(self) -> int: |
| 72 | `server/adapters/base.py:282` | `worktree:server/adapters/base.py` | YES | `gym_badge_slugs` | NO | 538 | def supports_explode_mode(self) -> bool: |
| 73 | `server/adapters/base.py:308` | `worktree:server/adapters/base.py` | YES | `gym_badge_slugs` | NO | 538 | def native_trade_ui(self) -> bool: |
| 74 | `server/adapters/base.py:403` | `worktree:server/adapters/base.py` | YES | `gym_badge_slugs` | NO | 538 | def rom_content_fingerprint(self, payload: dict) -> str \| |
| 75 | `server/adapters/base.py:518` | `worktree:server/adapters/base.py` | YES | `gym_badge_slugs` | NO | 538 | def mons_per_box(self) -> int: |
| 76 | `server/adapters/base.py:529` | `worktree:server/adapters/base.py` | YES | `gym_badge_slugs` | NO | 538 | def memorial_box_index(self) -> int: |
| 77 | `server/adapters/gen1_rby.py:265` | `worktree:server/adapters/gen1_rby.py` | YES | `gym_badge_slugs` | NO | - | class Gen1Adapter(GameAdapter): |
| 78 | `server/adapters/gen1_codec.py:1-13` | `worktree:server/adapters/gen1_codec.py` | YES | `for_foundation` | NO | 782 | """Independent English R/B/Y byte oracle, derived from pre |
| 79 | `server/adapters/gen1_codec.py:457` | `worktree:server/adapters/gen1_codec.py` | YES | `for_foundation` | NO | 782 | def decode_party_mon(b: bytes, *, box: bool = False) -> di |
| 80 | `server/adapters/gen1_codec.py:483` | `worktree:server/adapters/gen1_codec.py` | YES | `for_foundation` | NO | 782 | def encode_party_mon(d: dict) -> bytes: |
| 81 | `server/adapters/gen1_codec.py:606` | `worktree:server/adapters/gen1_codec.py` | YES | `for_foundation` | NO | 782 | def decode_box(sram_box_bytes: bytes) -> list[dict]: |
| 82 | `server/adapters/gen1_codec.py:611` | `worktree:server/adapters/gen1_codec.py` | YES | `for_foundation` | NO | 782 | def key(mon: dict) -> str: |
| 83 | `server/adapters/gen1_codec.py:647` | `worktree:server/adapters/gen1_codec.py` | YES | `for_foundation` | NO | 782 | def sav_checksum(b: bytes) -> int: |
| 84 | `server/adapters/gen1_codec.py:669` | `worktree:server/adapters/gen1_codec.py` | YES | `for_foundation` | NO | 782 | def verify_boxes(sram: bytes) -> dict: |
| 85 | `server/adapters/gen1_codec.py:705` | `worktree:server/adapters/gen1_codec.py` | YES | `for_foundation` | NO | 782 | def calc_stat(base: int, dv: int, stat_exp: int, level: in |
| 86 | `server/adapters/gen1_codec.py:779` | `worktree:server/adapters/gen1_codec.py` | YES | `for_foundation` | NO | 782 | class Gen1Layout: |
| 87 | `server/adapters/gen1_codec.py:941` | `worktree:server/adapters/gen1_codec.py` | YES | `for_foundation` | YES | - | def for_foundation(foundation: str) -> Gen1Layout: |
| 88 | `server/adapters/gen1_purergb.py:66` | `worktree:server/adapters/gen1_purergb.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | class Gen1PureRGBAdapter(Gen1Adapter): |
| 89 | `docs/gen2/REVIEW_RECORD.md:40` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - |  |
| 90 | `lua/gen1/entry.lua:58-83` | `worktree:lua/gen1/entry.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | Entry.PACK_FILES = { / gen1_rby = { / profile = "data/game |
| 91 | `lua/gen1/entry.lua:55-57` | `worktree:lua/gen1/entry.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- Every pack file Entry.build/Entry.admit reads, as liter |
| 92 | `patch/gen1/README.md:20` | `worktree:patch/gen1/README.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | One manifest, `patch/gen1/tools/manifest.py` — 15 spans, R |
| 93 | `patch/gen1/README.md:47-56` | `worktree:patch/gen1/README.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | The request byte at mailbox `+7` carries a **semantic code |
| 94 | `patch/gen1/README.md:42` | `worktree:patch/gen1/README.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | So the patch buys **zero additional rules**. What it buys  |
| 95 | `constants/pokemon_data_constants.asm:101` | `pokecrystal:constants/pokemon_data_constants.asm` | YES | `BOXMON_STRUCT_LENGTH` | YES | - | DEF BOXMON_STRUCT_LENGTH EQU _RS |
| 96 | `constants/pokemon_data_constants.asm:113` | `pokecrystal:constants/pokemon_data_constants.asm` | YES | `BOXMON_STRUCT_LENGTH` | NO | 101 | DEF PARTYMON_STRUCT_LENGTH EQU _RS |
| 97 | `docs/gen2/research/pret_gen2_symbols.md:37` | `worktree:docs/gen2/research/pret_gen2_symbols.md` | YES | `BOXMON_STRUCT_LENGTH` | YES | - | \| `BOXMON_STRUCT_LENGTH` (= end of box-portion) \| pokecr |
| 98 | `docs/gen2/research/pret_gen2_symbols.md:43` | `worktree:docs/gen2/research/pret_gen2_symbols.md` | YES | `BOXMON_STRUCT_LENGTH` | NO | 25 | \| `PARTYMON_STRUCT_LENGTH` \| pokecrystal@7a7881d constan |
| 99 | `server/adapters/gen1_codec.py:35` | `worktree:server/adapters/gen1_codec.py` | YES | `BOXMON_STRUCT_LENGTH` | NO | - | PARTY_MON_SIZE, BOX_MON_SIZE = 44, 33  # constants/pokemon |
| 100 | `server/adapters/gen1_rby.py:335-337` | `worktree:server/adapters/gen1_rby.py` | YES | `party_blob_size` | YES | - | def party_blob_size(self) -> int: / # pokemon_data_constan |
| 101 | `constants/pokemon_data_constants.asm:78` | `pokecrystal:constants/pokemon_data_constants.asm` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | DEF MON_ITEM               rb |
| 102 | `docs/protocol.md:223` | `worktree:docs/protocol.md` | YES | `party` | YES | - | ### 4.1 Party entry (element of `party` in `hello`/`tick`/ |
| 103 | `constants/pokemon_data_constants.asm:106-112` | `pokecrystal:constants/pokemon_data_constants.asm` | YES | `rw` | YES | - | DEF MON_STATS              rw NUM_BATTLE_STATS / rsset MON |
| 104 | `server/adapters/gen1_codec.py:31` | `worktree:server/adapters/gen1_codec.py` | YES | `spc` | YES | - | _STAT_EXP = {"hp": 17, "atk": 19, "def": 21, "spd": 23, "s |
| 105 | `server/adapters/gen1_codec.py:33` | `worktree:server/adapters/gen1_codec.py` | YES | `spc` | YES | - | _STORED_STATS = {"max_hp": 34, "atk": 36, "def": 38, "spd" |
| 106 | `constants/pokemon_data_constants.asm:138` | `pokecrystal:constants/pokemon_data_constants.asm` | YES | `BOX_LENGTH` | NO | 141 | DEF MONS_PER_BOX EQU 20 |
| 107 | `constants/pokemon_data_constants.asm:141` | `pokecrystal:constants/pokemon_data_constants.asm` | YES | `BOX_LENGTH` | YES | - | DEF BOX_LENGTH EQU 1 + MONS_PER_BOX + 1 + (BOXMON_STRUCT_L |
| 108 | `constants/pokemon_data_constants.asm:142` | `pokecrystal:constants/pokemon_data_constants.asm` | YES | `BOX_LENGTH` | NO | 141 | DEF NUM_BOXES EQU 14 |
| 109 | `server/adapters/gen1_codec.py:36` | `worktree:server/adapters/gen1_codec.py` | YES | `BOX_LENGTH` | NO | - | PARTY_CAPACITY, BOX_CAPACITY, BOX_COUNT = 6, 20, 12 |
| 110 | `server/adapters/gen1_rby.py:490-492` | `worktree:server/adapters/gen1_rby.py` | YES | `memorial_box_index` | YES | - | @property / def memorial_box_index(self) -> int: / # const |
| 111 | `ram/sram.asm:177-197` | `pokecrystal:ram/sram.asm` | YES | `sBox14` | YES | - | DEF box_n = 0 / MACRO boxes / rept \1 / DEF box_n += 1 / s |
| 112 | `gen1_codec.py:70` | `worktree:server/adapters/gen1_codec.py` | YES | `sBox14` | NO | - | "box_banks": (0x4000, 0x6000), "all_boxes_checksums": (0x5 |
| 113 | `docs/gen2/REVIEW_RECORD.md:39` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `box_banks` | NO | - | ## Codex "Gen2 Base" |
| 114 | `docs/gen2/research/bizhawk_gambatte_gbc.md:73-82` | `worktree:docs/gen2/research/bizhawk_gambatte_gbc.md` | YES | `rambanks*0x2000` | NO | - | So: **`CartRAM` in BizHawk's memory-domain list is the FUL |
| 115 | `docs/gen2/research/bizhawk_gambatte_gbc.md:255-261` | `worktree:docs/gen2/research/bizhawk_gambatte_gbc.md` | YES | `rambanks*0x2000` | NO | - | ## Open questions /  / - Whether the `CartRAM` domain for  |
| 116 | `engine/menus/save.asm:266-281` | `pokecrystal:engine/menus/save.asm` | YES | `wCurBox` | NO | 53 | _SaveGameData: / ld a, TRUE / ld [wSaveFileExists], a / fa |
| 117 | `engine/menus/save.asm:521-524` | `pokecrystal:engine/menus/save.asm` | YES | `wCurBox` | NO | 53 | SaveBox: / call GetBoxAddress / call SaveBoxAddress / ret |
| 118 | `engine/menus/save.asm:874-973` | `pokecrystal:engine/menus/save.asm` | YES | `wCurBox` | YES | - | GetBoxAddress: / ld a, [wCurBox] / cp NUM_BOXES / jr c, .o |
| 119 | `docs/gen2/REVIEW_RECORD.md:38` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `wCurBox` | NO | 51 |  |
| 120 | `gen1_codec.py:70-71` | `worktree:server/adapters/gen1_codec.py` | YES | `wCurBox` | NO | - | "box_banks": (0x4000, 0x6000), "all_boxes_checksums": (0x5 |
| 121 | `engine/menus/save.asm:360-366` | `pokecrystal:engine/menus/save.asm` | YES | `wSavedAtLeastOnce` | NO | 374 | ErasePreviousSave: / call EraseBoxes / call EraseHallOfFam |
| 122 | `engine/menus/save.asm:181-199` | `pokecrystal:engine/menus/save.asm` | YES | `wSavedAtLeastOnce` | NO | 374 | AskOverwriteSaveFile: / ld a, [wSaveFileExists] / and a /  |
| 123 | `engine/menus/save.asm:470-475` | `pokecrystal:engine/menus/save.asm` | YES | `wSavedAtLeastOnce` | YES | - | HallOfFame_InitSaveIfNeeded: / ld a, [wSavedAtLeastOnce] / |
| 124 | `engine/menus/save.asm:1038-1077` | `pokecrystal:engine/menus/save.asm` | YES | `wSavedAtLeastOnce` | NO | 374 | EraseBoxes: / ld hl, BoxAddresses / ld c, NUM_BOXES / .nex |
| 125 | `docs/gen2/REVIEW_RECORD.md:41` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `wSavedAtLeastOnce` | NO | 54 | ### cx-3569f8d9 — FACT_CHECK gen2-C1 (round 1, 2026-09-21) |
| 126 | `Makefile:169` | `pokecrystal:Makefile` | YES | `C` | NO | 114 | RGBFIXFLAGS += -Cjv -t PM_CRYSTAL -k 01 -l 0x33 -m MBC3+TI |
| 127 | `docs/gen2/research/rom_hashes.md:82-86` | `worktree:docs/gen2/research/rom_hashes.md` | YES | `C` | YES | - | - Internal cartridge title (`rgbfix -t`): `PM_CRYSTAL` (`p |
| 128 | `docs/gen2/research/bizhawk_gambatte_gbc.md:159-180` | `worktree:docs/gen2/research/bizhawk_gambatte_gbc.md` | YES | `C` | NO | 6 | ## 4. DMG vs CGB mode selection (`ConsoleMode`) /  / Sync  |
| 129 | `lua/gen1/entry.lua:274-292` | `worktree:lua/gen1/entry.lua` | YES | `C` | NO | - | local function bank_safe_io(bio, d) / if not d.wram_bank_g |
| 130 | `docs/gen2/research/bizhawk_gambatte_gbc.md:123` | `worktree:docs/gen2/research/bizhawk_gambatte_gbc.md` | YES | `0xD000-0xDFFF` | NO | - | - `0xD000 <= addr < 0xE000` → WRAM bank X, bank-adjusted o |
| 131 | `engine/battle/core.asm:2977-2980` | `pokecrystal:engine/battle/core.asm` | YES | `BATTLERESULT_BOX_FULL` | NO | - | ld a, [wBattleResult] / and BATTLERESULT_BITMASK / add DRA |
| 132 | `engine/items/item_effects.asm:545` | `pokecrystal:engine/items/item_effects.asm` | YES | `BATTLERESULT_BOX_FULL` | NO | 623 | set BATTLERESULT_CAUGHT_CELEBI, [hl] |
| 133 | `engine/items/item_effects.asm:622-623` | `pokecrystal:engine/items/item_effects.asm` | YES | `BATTLERESULT_BOX_FULL` | YES | - | ld hl, wBattleResult / set BATTLERESULT_BOX_FULL, [hl] |
| 134 | `docs/gen2/REVIEW_RECORD.md:42` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `wBattleResult` | NO | 55 |  |
| 135 | `engine/events/whiteout.asm:14` | `pokecrystal:engine/events/whiteout.asm` | YES | `WarpToSpawnPoint` | NO | 20 | special HealParty |
| 136 | `engine/events/whiteout.asm:20` | `pokecrystal:engine/events/whiteout.asm` | YES | `WarpToSpawnPoint` | YES | - | special WarpToSpawnPoint |
| 137 | `docs/gen2/REVIEW_RECORD.md:42` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `WarpToSpawnPoint` | NO | 55 |  |
| 138 | `docs/gen2/PLAN.md:140` | `worktree:docs/gen2/PLAN.md` | YES | `on_bus_exec` | NO | 150 | \| 5.3 \| **Site table from the built ROM, script labels e |
| 139 | `data/wild/johto_grass.asm:341-364` | `pokecrystal:data/wild/johto_grass.asm` | YES | `_SILVER` | NO | - | def_grass_wildmons NATIONAL_PARK / db 10 percent, 10 perce |
| 140 | `docs/gen2/REVIEW_RECORD.md:40` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `_SILVER` | NO | 53 |  |
| 141 | `docs/gen2/research/rom_hashes.md:77` | `worktree:docs/gen2/research/rom_hashes.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - SHA-1: `f4cd194bdee0d04ca4eac29e09b8e4e9d818c133` (`poke |
| 142 | `docs/gen2/research/rom_hashes.md:90` | `worktree:docs/gen2/research/rom_hashes.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - SHA-1: `f2f52230b536214ef7c9924f483392993e226cfb` (`poke |
| 143 | `lua/gen1/entry.lua:133-149` | `worktree:lua/gen1/entry.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | function Entry.admission_table(root, json) / local table_  |
| 144 | `docs/gen2/PLAN.md:32` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| Crystal revision \| Whichever revision the local dump i |
| 145 | `docs/gen2/gen2_requirements.md:139-142` | `worktree:docs/gen2/gen2_requirements.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - |  / Archipelago Crystal beyond profile generation (O-8); pe |
| 146 | `rom_hashes.md:53` | `worktree:docs/gen2/research/rom_hashes.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - SHA-1: `d8b8a3600a465308c9953dfa04f0081c05bdcb94` (`poke |
| 147 | `rom_hashes.md:69` | `worktree:docs/gen2/research/rom_hashes.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - SHA-1: `49b163f7e57702bc939d642a18f591de55d92dae` (`poke |
| 148 | `Makefile:169` | `pokecrystal:Makefile` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | RGBFIXFLAGS += -Cjv -t PM_CRYSTAL -k 01 -l 0x33 -m MBC3+TI |
| 149 | `Makefile:190` | `pokegold:Makefile` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | RGBFIXFLAGS += -cjsv -k 01 -l 0x33 -m MBC3+TIMER+RAM+BATTE |
| 150 | `docs/gen2/research/rom_hashes.md:62-63` | `worktree:docs/gen2/research/rom_hashes.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | Cart-type/RAM/battery flags shared with Silver/Crystal: `- |
| 151 | `docs/gen2/research/rom_hashes.md:83` | `worktree:docs/gen2/research/rom_hashes.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | `RGBFIXFLAGS += -Cjv -t PM_CRYSTAL -k 01 -l 0x33 -m MBC3+T |
| 152 | `ram/sram.asm:6-56` | `pokecrystal:ram/sram.asm` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | SECTION "SRAM Bank 0", SRAM /  / sPartyMail:: / ; sPartyMo |
| 153 | `server/adapters/gen1_codec.py:73` | `worktree:server/adapters/gen1_codec.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | SRAM_SIZE = 0x8000  # layout.link:195-202: four SRAM banks |
| 154 | `docs/gen2/research/bizhawk_gambatte_gbc.md:197-230` | `worktree:docs/gen2/research/bizhawk_gambatte_gbc.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | ## 5. SaveRAM file naming — gamedb hash, not launch path / |
| 155 | `src/BizHawk.Client.Common/config/PathEntryCollectionExtensions.cs:233-244` | `pokecrystal:src/BizHawk.Client.Common/config/PathEntryCollectionExtensions.cs` | **NO** | `KEYWORD_UNKNOWN` | UNKNOWN | - |  |
| 156 | `research/bizhawk_gambatte_gbc.md:208-214` | `research:research/bizhawk_gambatte_gbc.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - `SaveRamAbsolutePath` builds the filename from `game.Fil |
| 157 | `src/BizHawk.Emulation.Common/Database/Database.cs:270-307` | `pokecrystal:src/BizHawk.Emulation.Common/Database/Database.cs` | **NO** | `KEYWORD_UNKNOWN` | UNKNOWN | - |  |
| 158 | `research/bizhawk_gambatte_gbc.md:215-222` | `research:research/bizhawk_gambatte_gbc.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - `game.Name` (what `FilesystemSafeName()` sanitizes) is p |
| 159 | `constants/pokemon_constants.asm:171-174` | `pokecrystal:constants/pokemon_constants.asm` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | const MEWTWO     ; 96 / const MEW        ; 97 / DEF JOHTO_ |
| 160 | `constants/pokemon_constants.asm:223` | `pokecrystal:constants/pokemon_constants.asm` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | const UNOWN      ; c9 |
| 161 | `constants/pokemon_constants.asm:273-274` | `pokecrystal:constants/pokemon_constants.asm` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | const CELEBI     ; fb / DEF NUM_POKEMON EQU const_value -  |
| 162 | `lua/gen1/rom.lua:3` | `worktree:lua/gen1/rom.lua` | YES | `PokedexOrder` | YES | - | --   dex order   PokedexOrder (data/pokemon/dex_order.asm) |
| 163 | `maps/NewBarkTown.asm:8` | `pokecrystal:maps/NewBarkTown.asm` | YES | `SCENE_NEWBARKTOWN_NOOP` | NO | 9 | scene_script NewBarkTownNoop1Scene, SCENE_NEWBARKTOWN_TEAC |
| 164 | `maps/NewBarkTown.asm:292-293` | `pokecrystal:maps/NewBarkTown.asm` | YES | `SCENE_NEWBARKTOWN_NOOP` | NO | 9 | coord_event  1,  8, SCENE_NEWBARKTOWN_TEACHER_STOPS_YOU, N |
| 165 | `maps/ElmsLab.asm:277` | `pokecrystal:maps/ElmsLab.asm` | YES | `SCENE_NEWBARKTOWN_NOOP` | YES | - | setmapscene NEW_BARK_TOWN, SCENE_NEWBARKTOWN_NOOP |
| 166 | `docs/gen2/research/pret_gen2_symbols.md:182-187` | `worktree:docs/gen2/research/pret_gen2_symbols.md` | YES | `SCENE_NEWBARKTOWN_NOOP` | YES | - | - `scene_script NewBarkTownNoop1Scene, SCENE_NEWBARKTOWN_T |
| 167 | `docs/gen2/REVIEW_RECORD.md:37` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `SCENE_NEWBARKTOWN_NOOP` | NO | - | only" (ticket 09). Owner also supplied the AP pin link (ge |
| 168 | `docs/gen2/PLAN.md:168-175` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| **P0 Precondition** \| §0 \| `docs/gen2/spec.md`, `docs |
| 169 | `docs/gen2/PLAN.md:35-40` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | Standing rules (from `docs/purergb/PLAN.md:39-44` and the  |
| 170 | `docs/gen2/REVIEW_RECORD.md:19` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| O-5 \| "Move to fresh upstream HEAD" \| Pins: pokecryst |
| 171 | `docs/gen2/PLAN.md:25` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| Base cut \| master + cherry-picked `80261f3` + `959c578 |
| 172 | `docs/gen2/PLAN.md:152-161` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| 5.15a \| **Bus-exec hook registry → EXTRACT (neutral co |
| 173 | `docs/gen2/PLAN.md:37-38` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | `tools/lua_syntax_check.py`, ruff, the affected release-ru |
| 174 | `docs/gen2/gen2_requirements.md:5-9` | `worktree:docs/gen2/gen2_requirements.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | `4bf0f3b`). A row is **done** only when it carries a SOURC |
| 175 | `docs/gen2/gen2_requirements.md:11-12` | `worktree:docs/gen2/gen2_requirements.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | Nothing in the pre-rewrite Gen 2 code, data, fixtures, tes |
| 176 | `docs/gen2/PLAN.md:130` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | `tests/live/test_gen2_gates.py`, `tests/e2e/test_duo_gen2. |
| 177 | `docs/gen2/PLAN.md:168` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| **P0 Precondition** \| §0 \| `docs/gen2/spec.md`, `docs |
| 178 | `docs/gen2/REVIEW_RECORD.md:105-114` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | Standing note adopted: distinguish a limit described as MO |
| 179 | `docs/gen2/PLAN.md:146` | `worktree:docs/gen2/PLAN.md` | YES | `base` | YES | - | \| 5.9 \| **Admission by sha1 + anchors + a pinned pairing |
| 180 | `docs/gen2/PLAN.md:169` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| **P1 Build recipe + admitted-artifact matrix** \| 5.1;  |
| 181 | `docs/gen2/research/pret_gen2_symbols.md:6` | `worktree:docs/gen2/research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - `E:/Google Drive/SLink/.cache/pret/pokecrystal` (old pin |
| 182 | `docs/gen2/PLAN.md:138` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| 5.1 \| **Pinned builds first.** `data/gen2_sources.lock |
| 183 | `docs/gen2/PLAN.md:32` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| Crystal revision \| Whichever revision the local dump i |
| 184 | `docs/gen2/gen2_requirements.md:139-142` | `worktree:docs/gen2/gen2_requirements.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - |  / Archipelago Crystal beyond profile generation (O-8); pe |
| 185 | `docs/gen2/PLAN.md:259` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| **No provably free WRAM found from source** for the com |
| 186 | `docs/gen2/PLAN.md:170` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| **P2 Data packs, generators, coverage map, read-only re |
| 187 | `docs/gen2/PLAN.md:139` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| 5.2 \| **One profile, three packs.** Gold and Silver sh |
| 188 | `engine/events/whiteout.asm:14` | `pokecrystal:engine/events/whiteout.asm` | YES | `HealParty` | YES | - | special HealParty |
| 189 | `docs/gen2/PLAN.md:140` | `worktree:docs/gen2/PLAN.md` | YES | `HealParty` | YES | - | \| 5.3 \| **Site table from the built ROM, script labels e |
| 190 | `research/omp_symbol_lines.md:139-153` | `research:research/omp_symbol_lines.md` | YES | `wCurBattleMon` | NO | 48 | \| `engine/pokemon/move_mon.asm` \| `TryAddMonToParty` \|  |
| 191 | `events.asm:495` | `pokecrystal:engine/overworld/events.asm` **AMBIG(2)** | **AMBIG** | `CheckAPressOW` | YES | - | call CheckAPressOW |
| 192 | `data/wild/johto_grass.asm:341-364` | `pokegold:data/wild/johto_grass.asm` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | def_grass_wildmons NATIONAL_PARK / db 10 percent, 10 perce |
| 193 | `docs/gen2/PLAN.md:17` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| Titles \| Gold, Silver and Crystal all full admission t |
| 194 | `docs/gen2/PLAN.md:28` | `worktree:docs/gen2/PLAN.md` | YES | `national_park_contest` | NO | 31 | \| Eggs \| A hatched egg is a gift capture (`gift_daycare` |
| 195 | `docs/gen2/PLAN.md:31` | `worktree:docs/gen2/PLAN.md` | YES | `national_park_contest` | YES | - | \| Roamers / contest \| A roaming legendary is an extra ca |
| 196 | `docs/gen2/PLAN.md:159` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| 5.15h \| **Coverage-map validator → EXTRACT (neutral).* |
| 197 | `docs/gen2/PLAN.md:170` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| **P2 Data packs, generators, coverage map, read-only re |
| 198 | `docs/gen2/PLAN.md:146` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| 5.9 \| **Admission by sha1 + anchors + a pinned pairing |
| 199 | `docs/shared_runtime.md:60` | `worktree:docs/shared_runtime.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| Fail-closed release runner \| Nonzero exits, unexplaine |
| 200 | `docs/gen2/REVIEW_RECORD.md:111-114` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `duo-pairs` | NO | - | no fixture step; both Crystal revisions admitted; checkpoi |
| 201 | `docs/gen2/PLAN.md:170` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| **P2 Data packs, generators, coverage map, read-only re |
| 202 | `docs/gen2/PLAN.md:171` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| **P3a Shared change** \| 5.9 pairing contract; any `doc |
| 203 | `docs/gen2/PLAN.md:146` | `worktree:docs/gen2/PLAN.md` | YES | `_ROM_TYPE_TO_FOUNDATION` | YES | - | \| 5.9 \| **Admission by sha1 + anchors + a pinned pairing |
| 204 | `server/adapters/__init__.py:63-66` | `worktree:server/adapters/__init__.py` | YES | `silver` | YES | - | "Crystal": "gen2_crystal", "crystal": "gen2_crystal", / "G |
| 205 | `docs/gen2/PLAN.md:24` | `worktree:docs/gen2/PLAN.md` | YES | `gen2_gsc` | NO | 112 | \| Pairings \| Every Gen 2 pairing admitted (G↔S, G↔G, S↔S |
| 206 | `docs/gen2/gen2_requirements.md:104` | `worktree:docs/gen2/gen2_requirements.md` | YES | `gen2_gsc` | YES | - | \| C-6g \| Pairing: every Gen 2 pairing admitted through o |
| 207 | `docs/protocol.md:491-516` | `worktree:docs/protocol.md` | YES | `artifact_kind` | NO | 93 | ## 8. Gen 3-isms baked into shared code /  / Things a non- |
| 208 | `docs/gen2/PLAN.md:171` | `worktree:docs/gen2/PLAN.md` | YES | `<sha>` | YES | - | \| **P3a Shared change** \| 5.9 pairing contract; any `doc |
| 209 | `docs/gen2/PLAN.md:172` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| **P3b Client + adapter + codec + harness (rules qualifi |
| 210 | `docs/gen2/PLAN.md:158` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| 5.15g \| **Charmap decoder + fixture qualifier → EXTRAC |
| 211 | `server/adapters/gen1_codec.py:19-35` | `worktree:server/adapters/gen1_codec.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | # constants/pokemon_data_constants.asm:28-56; macros/ram.a |
| 212 | `server/adapters/gen1_codec.py:525-534` | `worktree:server/adapters/gen1_codec.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | def decode_name(b: bytes) -> str: / """Decode up to 11 byt |
| 213 | `tools/gen1_fixtures.py:90-145` | `worktree:tools/gen1_fixtures.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | def qualify(sram: bytes, rom: bytes, notes: list[str] \| N |
| 214 | `docs/gen2/PLAN.md:143` | `worktree:docs/gen2/PLAN.md` | YES | `CalcMonStats` | YES | - | \| 5.6 \| **Codec twin before any live lane, with the full |
| 215 | `docs/gen2/PLAN.md:161` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| 5.15j \| **Harness: bind, do not clone.** `tools/run_gb |
| 216 | `lua/tests/gen1_scripted_play.lua:1-6` | `worktree:lua/tests/gen1_scripted_play.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- lua/tests/gen1_scripted_play.lua — standalone scripted  |
| 217 | `tools/run_gb_gate.py:76-151` | `worktree:tools/run_gb_gate.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | GENS = { / "gen1": { / "play": g1, / "saveram_names": { /  |
| 218 | `docs/gen2/PLAN.md:100` | `worktree:docs/gen2/PLAN.md` | YES | `VerifyChecksum` | NO | 228 | \| R6 \| Fixtures from scripted play, town + battle per ti |
| 219 | `docs/gen2/PLAN.md:211-217` | `worktree:docs/gen2/PLAN.md` | YES | `_ot2` | YES | - | - Two saves per title, kinds `town` and `battle`, plus a s |
| 220 | `ElmsLab.asm:243` | `pokecrystal:maps/ElmsLab.asm` | YES | `_ot2` | NO | - | sjump ElmDirectionsScript |
| 221 | `ElmsLab.asm:251-277` | `pokecrystal:maps/ElmsLab.asm` | YES | `_ot2` | NO | - | ElmDirectionsScript: / turnobject PLAYER, UP / opentext /  |
| 222 | `docs/gen2/OPEN_QUESTIONS.md:44` | `worktree:docs/gen2/OPEN_QUESTIONS.md` | YES | `_ot2` | NO | - | \| B-18 \| ~~Release condition of the west-exit lock~~ RES |
| 223 | `docs/gen2/PLAN.md:155` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| 5.15d \| **`Entry.admit` → EXTRACT the decision framewo |
| 224 | `lua/gen1/entry.lua:229-266` | `worktree:lua/gen1/entry.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | function Entry.admit(args) / local table_ = Entry.admissio |
| 225 | `lua/gen1/entry.lua:243-246` | `worktree:lua/gen1/entry.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | if #matches == 1 then / local m = matches[1] / return { pa |
| 226 | `docs/gen2/PLAN.md:150` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| 5.13 \| **Frame-alignment probe before the first site g |
| 227 | `docs/gen2/PLAN.md:152` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| 5.15a \| **Bus-exec hook registry → EXTRACT (neutral co |
| 228 | `lua/gen1/signals.lua:326-396` | `worktree:lua/gen1/signals.lua` | YES | `site` | YES | - | -- Load-time anchor: every site's bytes must be in the ROM |
| 229 | `lua/gen1/signals.lua:6-9` | `worktree:lua/gen1/signals.lua` | YES | `expected_hex` | NO | 329 | -- capture_offset (hook = address + capture_offset), expec |
| 230 | `docs/gen2/PLAN.md:148` | `worktree:docs/gen2/PLAN.md` | YES | `expected_hex` | NO | 69 | \| 5.11 \| **Reads through `System Bus`, hooks with a bank |
| 231 | `lua/gen1/writes.lua:59-85` | `worktree:lua/gen1/writes.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- Open the write window for this frame. `reason` names th |
| 232 | `lua/gen1_write_safety.lua:54-105` | `worktree:lua/gen1_write_safety.lua` | YES | `$D000-$DFFF` | NO | - | -- Verify on every attempt, including after reset or a ROM |
| 233 | `lua/gen1/boxes.lua:6-7` | `worktree:lua/gen1/boxes.lua` | YES | `DelayFrame+5` | NO | - | local BANK_SIZE = 0x2000 -- layout.link:195-202, SRAM bank |
| 234 | `lua/gen1/boxes.lua:26-29` | `worktree:lua/gen1/boxes.lua` | YES | `DelayFrame+5` | NO | - | local function checksum(bytes, first, n) / -- engine/menus |
| 235 | `lua/gen1/boxes.lua:164-258` | `worktree:lua/gen1/boxes.lua` | YES | `DelayFrame+5` | NO | - | local function seal_bank(raw, info) / -- save.asm:312-327, |
| 236 | `docs/gen2/PLAN.md:141` | `worktree:docs/gen2/PLAN.md` | YES | `CartRAM` | NO | 143 | \| 5.4 \| **Checkpoint = execution site + WRAM predicate + |
| 237 | `lua/slink_gen1.lua:17-18` | `worktree:lua/slink_gen1.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | local _dir = debug.getinfo(1, "S").source:match("@(.+[/\\] |
| 238 | `lua/slink.lua:83-85` | `worktree:lua/slink.lua` | YES | `rom_type` | NO | - | -- No gen1_rby row: the Gen 1 route above returns before t |
| 239 | `tests/unit/test_gen1_identity_and_collisions.py:97-100` | `worktree:tests/unit/test_gen1_identity_and_collisions.py` | YES | `rom_type` | NO | - | def test_two_halves_reporting_one_key_is_refused(st): / "" |
| 240 | `docs/protocol.md:502` | `worktree:docs/protocol.md` | YES | `rom_type` | NO | 78 | \| 6 \| `html_render.py:169-196` \| `stat_stages` are 7 sl |
| 241 | `docs/gen2/PLAN.md:160` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| 5.15i \| **Duo oracle/witness orchestration → EXTRACT ( |
| 242 | `tools/e2e_duo.py:4134-4153` | `worktree:tools/e2e_duo.py` | YES | `gen1_new` | YES | - | def _run_oracle(self, results): / """The scenario's post-r |
| 243 | `lua/gen1/signals.lua:103` | `worktree:lua/gen1/signals.lua` | YES | `gen1_new` | NO | - | S.KINDS.save_witness = { |
| 244 | `lua/gen1/client.lua:1237-1238` | `worktree:lua/gen1/client.lua` | YES | `gen1_new` | NO | - | elseif k == "save_witness" then / if io.saveram then pcall |
| 245 | `tools/e2e_duo.py:4040` | `worktree:tools/e2e_duo.py` | YES | `gen1_new` | NO | 67 | def check_save_witness(self, results): |
| 246 | `docs/shared_runtime.md:59` | `worktree:docs/shared_runtime.md` | YES | `gen2_new` | NO | - | \| Post-result oracle registry \| `SCENARIOS[name].oracle` |
| 247 | `docs/gen2/PLAN.md:101` | `worktree:docs/gen2/PLAN.md` | YES | `gen2_new` | NO | 145 | \| R7 \| Duo oracles independent of the client \| **Missin |
| 248 | `docs/gen2/PLAN.md:239-246` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | ## 9a. Rollback /  / A failed gate returns the phase to it |
| 249 | `docs/gen2/PLAN.md:173` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| **P4 Companion overlay** \| 5.12; tickets 14-16 \| `pat |
| 250 | `docs/gen2/PLAN.md:173` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| **P4 Companion overlay** \| 5.12; tickets 14-16 \| `pat |
| 251 | `docs/gen2/REVIEW_RECORD.md:110-112` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `sScratch` | NO | 148 | 18 contradictions (stale Step 0 source of truth; Gold/Silv |
| 252 | `docs/gen2/PLAN.md:157` | `worktree:docs/gen2/PLAN.md` | YES | `sScratch` | NO | 259 | \| 5.15f \| **ABI-3 panel/mailbox → EXTRACT-GB-ONLY with e |
| 253 | `lua/gen1/panel.lua:98-124` | `worktree:lua/gen1/panel.lua` | YES | `sScratch` | NO | - | -- interval; the predicate takes an optional length so it  |
| 254 | `lua/gen1/panel.lua:170-216` | `worktree:lua/gen1/panel.lua` | YES | `sScratch` | NO | - |  / --- Drop queued sounds only: the run switched native so |
| 255 | `lua/gen1/panel.lua:220` | `worktree:lua/gen1/panel.lua` | YES | `sScratch` | NO | - | local function tick() |
| 256 | `lua/gen1/panel.lua:8-10` | `worktree:lua/gen1/panel.lua` | YES | `sScratch` | NO | - | -- All writes go through the injected writes.lua instance  |
| 257 | `docs/gen2/PLAN.md:149` | `worktree:docs/gen2/PLAN.md` | YES | `request_sfx` | NO | - | \| 5.12 \| **Native features on a surveyed mailbox.** Pane |
| 258 | `lua/sfx_arbiter.lua:20` | `worktree:lua/sfx_arbiter.lua` | YES | `request_sfx` | NO | - | -- Pass the caller's own SE constants (they are ROM-profil |
| 259 | `patch/gen1/README.md:52-55` | `worktree:patch/gen1/README.md` | YES | `request_sfx` | NO | - | `Joypad`'s `call _Joypad` (`$01A4`) is pointed at `SlinkJo |
| 260 | `docs/gen2/PLAN.md:149` | `worktree:docs/gen2/PLAN.md` | YES | `request_sfx` | NO | - | \| 5.12 \| **Native features on a surveyed mailbox.** Pane |
| 261 | `docs/protocol.md:497` | `worktree:docs/protocol.md` | YES | `request_sfx` | NO | 328 | \| 1 \| `state.py:718,1177,1186,1259,1332,1364,1385,1409,1 |
| 262 | `server/state.py:554-800` | `worktree:server/state.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | def _handle_trade_request(self, player_id: str, msg: dict) |
| 263 | `server/adapters/base.py:308` | `worktree:server/adapters/base.py` | YES | `native_trade_ui()` | NO | 300 | def native_trade_ui(self) -> bool: |
| 264 | `lua/gen1/trade_overlay.lua:5-7` | `worktree:lua/gen1/trade_overlay.lua` | YES | `native_trade_ui()` | NO | - | local MAGIC = {0x53, 0x4C, 0x54, 0x31} -- trade_service.as |
| 265 | `engine/link/link.asm:1994` | `pokecrystal:engine/link/link.asm` | YES | `AddTempmonToParty` | YES | - | predef AddTempmonToParty |
| 266 | `docs/gen2/PLAN.md:149` | `worktree:docs/gen2/PLAN.md` | YES | `SaveAfterLinkTrade` | YES | - | \| 5.12 \| **Native features on a surveyed mailbox.** Pane |
| 267 | `docs/gen2/gen2_requirements.md:139-142` | `worktree:docs/gen2/gen2_requirements.md` | YES | `SaveAfterLinkTrade` | NO | - |  / Archipelago Crystal beyond profile generation (O-8); pe |
| 268 | `docs/gen2/PLAN.md:173` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| **P4 Companion overlay** \| 5.12; tickets 14-16 \| `pat |
| 269 | `docs/gen2/PLAN.md:175` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| **P6 Manager/UI + release** \| one run family "Gold · S |
| 270 | `docs/gen2/PLAN.md:175` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| **P6 Manager/UI + release** \| one run family "Gold · S |
| 271 | `docs/gen2/PLAN.md:30` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| Manager \| One family "Gold · Silver · Crystal" \| O-16 |
| 272 | `docs/gen2/gen2_requirements.md:137-152` | `worktree:docs/gen2/gen2_requirements.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - |  / ## Not in this release (to be confirmed by the owner) / |
| 273 | `docs/gen2/PLAN.md:175` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| **P6 Manager/UI + release** \| one run family "Gold · S |
| 274 | `docs/gen2/PLAN.md:174` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| **P5 Peer ghost (POST-RC, owner O-13)** \| ticket 17 FE |
| 275 | `docs/gen2/PLAN.md:149` | `worktree:docs/gen2/PLAN.md` | YES | `LoadMapAttributes_SkipObjects` | YES | - | \| 5.12 \| **Native features on a surveyed mailbox.** Pane |
| 276 | `home/map_objects.asm:420-435` | `pokecrystal:home/map_objects.asm` | YES | `FindFirstEmptyObjectStruct` | YES | - | FindFirstEmptyObjectStruct:: / ; Returns the index of the  |
| 277 | `docs/gen2/gen2_requirements.md:137-142` | `worktree:docs/gen2/gen2_requirements.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - |  / ## Not in this release (to be confirmed by the owner) / |
| 278 | `docs/gen2/PLAN.md:23` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| Archipelago \| Documented (`research/archipelago_crysta |
| 279 | `docs/gen2/research/archipelago_crystal.md:369-373` | `worktree:docs/gen2/research/archipelago_crystal.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | **Exact clone URL + sha the implementation phase should pi |
| 280 | `server/adapters/base.py:282` | `worktree:server/adapters/base.py` | YES | `supports_explode_mode` | YES | - | def supports_explode_mode(self) -> bool: |
| 281 | `lua/slink.lua:83-85` | `worktree:lua/slink.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- No gen1_rby row: the Gen 1 route above returns before t |
| 282 | `docs/gen2/PLAN.md:154` | `worktree:docs/gen2/PLAN.md` | YES | `gb_checkpoint` | YES | - | \| 5.15c \| **Checkpoint runner → EXTRACT-GB-ONLY (`gb_che |
| 283 | `server/adapters/gen1_rby.py:490-492` | `worktree:server/adapters/gen1_rby.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | @property / def memorial_box_index(self) -> int: / # const |
| 284 | `server/adapters/base.py:559` | `worktree:server/adapters/base.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | def gb_status_token(status_cond: int) -> str: |
| 285 | `server/adapters/gen1_rby.py:356-358` | `worktree:server/adapters/gen1_rby.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | def status_token(self, status_cond: int) -> str: / # const |
| 286 | `docs/gen2/research/rom_hashes.md:100-106` | `worktree:docs/gen2/research/rom_hashes.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | **Which revision does pret target?** Both — `pokecrystal.g |
| 287 | `docs/gen2/research/rom_hashes.md:148-150` | `worktree:docs/gen2/research/rom_hashes.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - Whether `pokecrystal.gbc` (V1.0) or `pokecrystal11.gbc`  |
| 288 | `rom_hashes.md:102-104` | `worktree:docs/gen2/research/rom_hashes.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | doc in this repo uses when it says "Crystal" without a rev |
| 289 | `data/games/gen1_rby/README.md:18` | `worktree:data/games/gen1_rby/README.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | The duo E2E runs two pairings — **Red/Blue** and **Yellow/ |
| 290 | `docs/gen2/REVIEW_RECORD.md:23` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| O-12 \| "We can use whatever the local dump is" (Crysta |
| 291 | `patch/gen1/README.md:36-43` | `worktree:patch/gen1/README.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | Unlike Gen 3, **Gen 1 needs no patch for correctness**. Ra |
| 292 | `docs/gen2/PLAN.md:173` | `worktree:docs/gen2/PLAN.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| **P4 Companion overlay** \| 5.12; tickets 14-16 \| `pat |
| 293 | `docs/gen2/REVIEW_RECORD.md:27` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| O-16 \| "One family. We can allow C to GS games if its  |
| 294 | `docs/gen1_gen2_runtime_checks.md:186-191` | `worktree:docs/gen1_gen2_runtime_checks.md` | YES | `saveram_dir` | YES | - | The duo E2E runs **two Crystal instances against one dump* |
| 295 | `engine/link/link.asm:1994-2044` | `pokecrystal:engine/link/link.asm` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | predef AddTempmonToParty / ld a, [wPartyCount] / dec a / l |
| 296 | `lua/gen1/client.lua:1422-1496` | `worktree:lua/gen1/client.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- ── APEX CHIP (pureRGB, PLAN A1) and transformations (A2 |
| 297 | `docs/gen2/research/pret_gen2_symbols.md:70` | `worktree:docs/gen2/research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| `sBox14` \| 0xb9e0 \| 0xb9e0 \| pokecrystal@7a7881d ram |
| 298 | `docs/gen2/research/pret_gen2_symbols.md:223` | `worktree:docs/gen2/research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - Not derivable without a build: absolute SRAM bank *numbe |
| 299 | `docs/gen2/REVIEW_RECORD.md:39` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | ## Codex "Gen2 Base" |
| 300 | `docs/gen2/research/bizhawk_gambatte_gbc.md:255-261` | `worktree:docs/gen2/research/bizhawk_gambatte_gbc.md` | YES | `0x2000` | YES | - | ## Open questions /  / - Whether the `CartRAM` domain for  |
| 301 | `docs/gen2/research/bizhawk_gambatte_gbc.md:262-265` | `worktree:docs/gen2/research/bizhawk_gambatte_gbc.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - Whether GBC double-speed mode changes anything about `on |
| 302 | `docs/gen2/research/bizhawk_gambatte_gbc.md:271-275` | `worktree:docs/gen2/research/bizhawk_gambatte_gbc.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - Whether BizHawk's ROM loader classifies a Gold/Silver RO |
| 303 | `docs/gen2/research/pret_gen2_symbols.md:104` | `worktree:docs/gen2/research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - `LostBattle`: pokecrystal@7a7881d engine/battle/core.asm |
| 304 | `docs/gen2/REVIEW_RECORD.md:42` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - |  |
| 305 | `docs/gen2/research/pret_gen2_symbols.md:110` | `worktree:docs/gen2/research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - Link trade: `engine/link/link_trade.asm` (pokecrystal@7a |
| 306 | `docs/gen2/research/pret_gen2_symbols.md:117` | `worktree:docs/gen2/research/pret_gen2_symbols.md` | YES | `TryAddMonToParty` | YES | - | - A generic `GivePokemon` label (as distinct from `GiveEgg |
| 307 | `docs/gen2/research/pret_gen2_symbols.md:91-92` | `worktree:docs/gen2/research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| `wTempWildMon` \| not present in JSON (`None`) \| not p |
| 308 | `docs/gen2/research/pret_gen2_symbols.md:89-90` | `worktree:docs/gen2/research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| `wOtherTrainerClass` \| 0xd22f \| 0xd118 \| JSON only,  |
| 309 | `lua/clients/gen2_crystal_client.lua:40` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | NOT YET IMPLEMENTED (Gen 1 has them): trainer_battle_start |
| 310 | `docs/gen2/REVIEW_RECORD.md:47-55` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - |  / \| # \| Premise (project claim) \| Verdict \| What chan |

TOTAL n=310 resolved=308 unresolved=2 ambiguous=1 kw_YES=49 kw_NO=104 kw_UNKNOWN=157

Unresolved and ambiguous rows:

```text
---- unresolved / ambiguous ----
GEN2_BINDING_PLAN:219 src/BizHawk.Client.Common/config/PathEntryCollectionExtensions.cs:233-244 -> pokecrystal:src/BizHawk.Client.Common/config/PathEntryCollectionExtensions.cs exists=False nlines=0 cands=[]
GEN2_BINDING_PLAN:219 src/BizHawk.Emulation.Common/Database/Database.cs:270-307 -> pokecrystal:src/BizHawk.Emulation.Common/Database/Database.cs exists=False nlines=0 cands=[]
GEN2_BINDING_PLAN:285 events.asm:495-0 -> pokecrystal:engine/overworld/events.asm exists=True nlines=1345 cands=['engine/overworld/events.asm', 'macros/scripts/events.asm']
```

## Lease subset check

Phase headings anchor to PLAN §6 rows that all start with the phase name (verified mechanically:
`[('P0', 168, True), ('P1', 169, True), ('P2', 170, True), ('P3a', 171, True), ('P3b', 172, True), ('P4', 173, True), ('P6', 175, True)]`).

| substep | file | in PLAN §6 phase row | where |
|---|---|---|---|
| P0.1 | `docs/gen2/PLAN.md` | n/a | prose / section ref |
| P0.2 | `docs/gen2/spec.md` | YES | verbatim in PLAN §6 row |
| P0.2 | `docs/gen2/issues/*` | YES | verbatim in PLAN §6 row |
| P0.3 | `docs/gen2/PLAN.md` | n/a | prose / section ref |
| P0.3 | `:184-195` | n/a | prose / section ref |
| P1.1 | `data/gen2_sources.lock.json` | YES | verbatim in PLAN §6 row |
| P1.1 | `tools/build_gen2_syms.py` | YES | verbatim in PLAN §6 row |
| P1.2 | `.github/workflows/gen2-syms.yml` | YES | verbatim in PLAN §6 row |
| P1.3 | `data/games/gen2_{crystal,gold,silver}/admission.json` | YES | covered by PLAN §6 glob `data/games/gen2_*/admission.json` |
| P1.4 | `.map` | n/a | prose / section ref |
| P1.4 | `tools/build_gen2_syms.py` | YES | verbatim in PLAN §6 row |
| P2.1 | `tools/gen_gen2_{profile,species,evos,items,charmap,map_names}.py` | YES | covered by PLAN §6 glob `tools/gen_gen2_*.py` |
| P2.1 | `data/games/gen2_*/` | NO |  |
| P2.1 | `tests/unit/test_gen2_{profile,species,evos}.py` | YES | covered by PLAN §6 glob `tests/unit/test_gen2_{profile,engine_sites,rom_tables,species,evos,encounters,write_checkpoint,admission,coverage_map}.py` |
| P2.1 | `tools/verify_profile_addresses.py` | YES | verbatim in PLAN §6 row |
| P2.2 | `tools/gen_gen2_engine_signals.py` | YES | covered by PLAN §6 glob `tools/gen_gen2_*.py` |
| P2.2 | `data/games/gen2_*/engine_signals.json` | NO |  |
| P2.2 | `docs/gen2/gen2_engine_sites.md` | YES | verbatim in PLAN §6 row |
| P2.2 | `tests/unit/test_gen2_engine_sites.py` | YES | covered by PLAN §6 glob `tests/unit/test_gen2_{profile,engine_sites,rom_tables,species,evos,encounters,write_checkpoint,admission,coverage_map}.py` |
| P2.3 | `tools/gen_gen2_write_checkpoint.py` | YES | covered by PLAN §6 glob `tools/gen_gen2_*.py` |
| P2.3 | `data/games/gen2_*/write_checkpoint.json` | NO |  |
| P2.3 | `tests/unit/test_gen2_write_checkpoint.py` | YES | covered by PLAN §6 glob `tests/unit/test_gen2_{profile,engine_sites,rom_tables,species,evos,encounters,write_checkpoint,admission,coverage_map}.py` |
| P2.4 | `server/adapters/gen2_rom_scan.py` | YES | verbatim in PLAN §6 row |
| P2.4 | `lua/gen2/rom.lua` | YES | verbatim in PLAN §6 row |
| P2.4 | `tools/verify_gen2_rom_layout.py` | YES | verbatim in PLAN §6 row |
| P2.4 | `tests/unit/test_gen2_rom_tables.py` | YES | covered by PLAN §6 glob `tests/unit/test_gen2_{profile,engine_sites,rom_tables,species,evos,encounters,write_checkpoint,admission,coverage_map}.py` |
| P2.5 | `tools/gen_gen2_{area_map,encounters,statics,trainers,admission}.py` | YES | covered by PLAN §6 glob `tools/gen_gen2_*.py` |
| P2.5 | `data/games/gen2_{crystal,gold,silver}/{area_map,encounters,statics,trainers,gifts}.json` | YES | covered by PLAN §6 glob `data/games/gen2_{crystal,gold,silver}/*` |
| P2.5 | `tests/unit/test_gen2_{encounters,admission}.py` | YES | covered by PLAN §6 glob `tests/unit/test_gen2_{profile,engine_sites,rom_tables,species,evos,encounters,write_checkpoint,admission,coverage_map}.py` |
| P2.6 | `docs/gen2/gen2_coverage_map.md` | YES | verbatim in PLAN §6 row |
| P2.6 | `tests/unit/test_gen2_coverage_map.py` | YES | covered by PLAN §6 glob `tests/unit/test_gen2_{profile,engine_sites,rom_tables,species,evos,encounters,write_checkpoint,admission,coverage_map}.py` |
| P2.7 | `tools/verify_gen2_release.py` | YES | verbatim in PLAN §6 row |
| P3a.1 | `server/adapters/__init__.py` | YES | verbatim in PLAN §6 row |
| P3a.1 | `_ROM_TYPE_TO_FOUNDATION` | n/a | prose / section ref |
| P3a.1 | `tests/unit/test_gen2_pairing_matrix.py` | YES | verbatim in PLAN §6 row |
| P3a.1 | `server/adapters/base.py` | YES | verbatim in PLAN §6 row |
| P3a.1 | `server/server.py` | YES | verbatim in PLAN §6 row |
| P3a.2 | `tests/unit/test_protocol_schema.py` | YES | verbatim in PLAN §6 row |
| P3a.2 | `tests/unit/protocol_schema.py` | YES | verbatim in PLAN §6 row |
| P3a.2 | `docs/protocol.md` | YES | verbatim in PLAN §6 row |
| P3b.1 | `server/adapters/gen2_codec.py` | YES | covered by PLAN §6 glob `server/adapters/{gen2_gsc,gen2_codec}.py` |
| P3b.1 | `tests/unit/test_gen2_codec.py` | NO |  |
| P3b.2 | `tools/gen2_fixtures.py` | YES | verbatim in PLAN §6 row |
| P3b.2 | `lua/tests/gen2_scripted_play_*.lua` | YES | covered by PLAN §6 glob `lua/tests/gen2_*.lua` |
| P3b.2 | `tests/fixtures/gen2/{crystal,gold,silver}_{town,battle}.SaveRAM` | YES | covered by PLAN §6 glob `tests/fixtures/gen2/{crystal,gold,silver}_{town,battle}.SaveRAM` |
| P3b.2 | `tests/fixtures/gen2/crystal_{town,battle}_ot2.SaveRAM` | NO |  |
| P3b.2 | `tests/fixtures/gen2/receipts/` | NO |  |
| P3b.3 | `lua/gen2/entry.lua` | YES | covered by PLAN §6 glob `lua/gen2/*` |
| P3b.3 | `lua/gen2/reads.lua` | YES | covered by PLAN §6 glob `lua/gen2/*` |
| P3b.3 | `tests/unit/test_gen2_{entry,reads}.py` | NO |  |
| P3b.4 | `lua/gen2/signals.lua` | YES | covered by PLAN §6 glob `lua/gen2/*` |
| P3b.4 | `tests/unit/test_gen2_signals.py` | NO |  |
| P3b.4 | `tests/live/test_gen2_new_gates.py` | YES | verbatim in PLAN §6 row |
| P3b.5 | `lua/gen2/writes.lua` | YES | covered by PLAN §6 glob `lua/gen2/*` |
| P3b.5 | `lua/gen2/boxes.lua` | YES | covered by PLAN §6 glob `lua/gen2/*` |
| P3b.5 | `lua/gen2_write_safety.lua` | YES | verbatim in PLAN §6 row |
| P3b.5 | `lua/` | YES | verbatim in PLAN §6 row |
| P3b.5 | `lua/gen2/write_safety.lua` | YES | covered by PLAN §6 glob `lua/gen2/*` |
| P3b.5 | `tests/unit/test_gen2_{writes,boxes}.py` | NO |  |
| P3b.6 | `lua/gen2/client.lua` | YES | covered by PLAN §6 glob `lua/gen2/*` |
| P3b.6 | `lua/gen2/run.lua` | YES | covered by PLAN §6 glob `lua/gen2/*` |
| P3b.6 | `lua/slink.lua` | YES | verbatim in PLAN §6 row |
| P3b.6 | `lua/slink_gen2.lua` | NO |  |
| P3b.6 | `lua/gen2/run.lua` | YES | covered by PLAN §6 glob `lua/gen2/*` |
| P3b.6 | `lua/slink_gen1.lua:17-18` | NO |  |
| P3b.6 | `server/adapters/gen2_gsc.py` | YES | covered by PLAN §6 glob `server/adapters/{gen2_gsc,gen2_codec}.py` |
| P3b.6 | `server/adapters/__init__.py` | YES | verbatim in PLAN §6 row |
| P3b.6 | `rom_type` | n/a | prose / section ref |
| P3b.6 | `server/manager.py` | YES | verbatim in PLAN §6 row |
| P3b.6 | `tests/unit/test_gen2_{client,adapter}.py` | NO |  |
| P3b.7 | `tools/e2e_duo.py` | YES | verbatim in PLAN §6 row |
| P3b.7 | `tools/run_gb_gate.py` | YES | verbatim in PLAN §6 row |
| P3b.7 | `tests/e2e/test_duo_gen2_new.py` | YES | verbatim in PLAN §6 row |
| P3b.7 | `tests/live/test_gen2_new_gates.py` | YES | verbatim in PLAN §6 row |
| P3b.7 | `tools/verify_gen2_release.py` | YES | verbatim in PLAN §6 row |
| P3b.7 | `tests/gen2_release_requirements.json` | YES | verbatim in PLAN §6 row |
| P3b.7 | `docs/gen2/gen2_requirements.md` | YES | verbatim in PLAN §6 row |
| P3b.8 | `tools/make_release.py` | YES | verbatim in PLAN §6 row |
| P3b.8 | `tests/unit/test_make_release_manifest.py` | YES | verbatim in PLAN §6 row |
| P4.1 | `patch/gen2/**` | YES | verbatim in PLAN §6 row |
| P4.1 | `tools/build_gen2_companion.py` | YES | verbatim in PLAN §6 row |
| P4.1 | `patch/dist/SLink-{Gold,Silver,Crystal}.ups` | YES | covered by PLAN §6 glob `patch/dist/SLink-{Gold,Silver,Crystal}.ups` |
| P4.2 | `patch/gen2/src/` | YES | covered by PLAN §6 glob `patch/gen2/**` |
| P4.2 | `request_sfx` | n/a | prose / section ref |
| P4.2 | `lua/gen2/panel.lua` | YES | covered by PLAN §6 glob `lua/gen2/{trade_overlay,panel}.lua` |
| P4.2 | `lua/gen2/sound.lua` | NO |  |
| P4.2 | `docs/gen2/PLAN.md:149` | n/a | prose / section ref |
| P4.2 | `tests/live/test_gen2_trade_gates.py` | YES | verbatim in PLAN §6 row |
| P4.3 | `patch/gen2/src/trade_*.asm` | YES | covered by PLAN §6 glob `patch/gen2/**` |
| P4.3 | `lua/gen2/trade_overlay.lua` | YES | covered by PLAN §6 glob `lua/gen2/{trade_overlay,panel}.lua` |
| P4.3 | `lua/gen2/client.lua` | NO |  |
| P4.3 | `tests/live/test_gen2_trade_gates.py` | YES | verbatim in PLAN §6 row |
| P6.1 | `server/manager.py` | YES | verbatim in PLAN §6 row |
| P6.1 | `tools/gen_ui_capabilities.py` | YES | verbatim in PLAN §6 row |
| P6.2 | `README.md` | YES | verbatim in PLAN §6 row |
| P6.2 | `docs/REFERENCE.md` | YES | verbatim in PLAN §6 row |
| P6.2 | `docs/historical/release_notes.md` | YES | verbatim in PLAN §6 row |
| P6.2 | `tools/make_release.py` | YES | verbatim in PLAN §6 row |

```text
LEASE tokens=98 checked=90 verbatim=46 glob=30 card=0 MISS=14 prose=8
misses:
    P2.1 | data/games/gen2_*/
    P2.2 | data/games/gen2_*/engine_signals.json
    P2.3 | data/games/gen2_*/write_checkpoint.json
    P3b.1 | tests/unit/test_gen2_codec.py
    P3b.2 | tests/fixtures/gen2/crystal_{town,battle}_ot2.SaveRAM
    P3b.2 | tests/fixtures/gen2/receipts/
    P3b.3 | tests/unit/test_gen2_{entry,reads}.py
    P3b.4 | tests/unit/test_gen2_signals.py
    P3b.5 | tests/unit/test_gen2_{writes,boxes}.py
    P3b.6 | lua/slink_gen2.lua
    P3b.6 | lua/slink_gen1.lua:17-18
    P3b.6 | tests/unit/test_gen2_{client,adapter}.py
    P4.2 | lua/gen2/sound.lua
    P4.3 | lua/gen2/client.lua
```

## Real defects

**Citation defects — 1.**

| citation | verdict | evidence |
|---|---|---|
| `events.asm:495` (BINDING_PLAN:285, the P2.3 write-checkpoint row) | ambiguous bare basename | matches two pokecrystal files — `engine/overworld/events.asm` (1345 lines) and `macros/scripts/events.asm`. The intent is certain: line 495 of `engine/overworld/events.asm` is `call CheckAPressOW`, exactly what the row claims, and the sibling citation `:483` Gold resolves to the same instruction in pokegold. Path completeness only. |

**Excluded from the defect count, with reasons** (both are unresolved against the roots the
card declares, and both are explained by the document itself):

- `src/BizHawk.Client.Common/config/PathEntryCollectionExtensions.cs:233-244` and
  `src/BizHawk.Emulation.Common/Database/Database.cs:270-307` (BINDING_PLAN:219). The row now
  names the version and the source root ("BizHawk 2.11.1"), anchors each at a research note
  that **does** resolve (`research/bizhawk_gambatte_gbc.md:208-214` and `:215-222`), and marks
  the second "not in any local tree" — which is true: a depth-8 search of the SLink tree
  finds no `Database.cs`, and the sweep worktree's `.cache/bizhawk-save-source/` carries only
  `PathEntryCollectionExtensions.cs`, `FileWriter.cs`, `FileWriteResult.cs`. This is the gen2-A4
  fix applied, not a new miss.

**Lease misses — 8** (the 14 mechanical misses, classified: 3 are pattern-vs-pattern, 1 is a
negation, 1 is a Gen 1 shape reference, 1 is a PLAN prefix elision):

```text
    P3b.1 | tests/unit/test_gen2_codec.py
    P3b.2 | tests/fixtures/gen2/receipts/
    P3b.3 | tests/unit/test_gen2_{entry,reads}.py
    P3b.4 | tests/unit/test_gen2_signals.py
    P3b.5 | tests/unit/test_gen2_{writes,boxes}.py
    P3b.6 | tests/unit/test_gen2_{client,adapter}.py
    P3b.6 | lua/slink_gen2.lua
    P4.3  | lua/gen2/client.lua
```

Evidence: the PLAN P3b row's only `test_gen2_` token is `tests/live/test_gen2_new_gates.py`
(grep of the full 3624-char row for `test_gen2_`), and its only `fixtures/gen2` token is
`tests/fixtures/gen2/{crystal,gold,silver}_{town,battle}.SaveRAM`; there is no `receipts` and no
`slink_gen2.lua` anywhere in it. So five Python unit-test files, the receipts directory and the
launcher shim that P3b's own substeps claim are outside the P3b lease — the doc's own rule at
BINDING_PLAN:227-230 says every substep's files must be a subset. P4.3 is the same shape in the
other direction: it edits "the trade phases of `lua/gen2/client.lua`", a file P3b owns via
`lua/gen2/*` and P4's lease (`patch/gen2/**`, `lua/gen2/{trade_overlay,panel}.lua`) does not name.

The six excluded mechanical misses, for the record:

```text
    P2.1  | data/games/gen2_*/                      — pattern vs PLAN's data/games/gen2_{crystal,gold,silver}/*
    P2.2  | data/games/gen2_*/engine_signals.json   — same
    P2.3  | data/games/gen2_*/write_checkpoint.json — same
    P3b.2 | tests/fixtures/gen2/crystal_{town,battle}_ot2.SaveRAM — PLAN names it as `+ crystal_{town,battle}_ot2.SaveRAM`, prefix elided
    P3b.6 | lua/slink_gen1.lua:17-18                — a Gen 1 shape reference, not an owned file
    P4.2  | lua/gen2/sound.lua                      — the substep says "no `lua/gen2/sound.lua`"; my extractor read the negation
```

## Summary

| | value |
|---|---|
| citations | **310** |
| resolve | **308** |
| unresolved | 2 (both the version-qualified BizHawk pointers, excluded) |
| ambiguous basename | 1 (`events.asm:495`) |
| keyword at cited line | 49 |
| keyword elsewhere / none | 104 / 157 |
| lease tokens (substep files) | 98 (90 path-ish, 8 prose) |
| lease: verbatim / glob-covered | 46 / 30 |
| lease misses | **8** |
| real defects | **9** (1 citation + 8 lease) |

The document's §5.A self-check claims "every substep's files are inside its phase lease"; that
holds for 76 of the 90 path tokens (46 verbatim + 30 by glob) and fails for 8 — all in P3b and
P4.3, and all of one kind: the substeps create Python unit tests (and one receipts directory and
one launcher shim) that the PLAN §6 P3b lease never names. The phase lease and the phase
decomposition disagree; one of the two must move.

DONE gen2-A5: 310 citations, 308 resolve, 9 real defects, 8 lease misses
