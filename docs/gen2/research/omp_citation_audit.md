# gen2-A3 — citation resolver for the Gen 2 plan

Mechanical resolution of every `<path>:<line>` / `<path>:<a>-<b>` citation in the two frozen
files. Nothing here judges the plan; it measures whether each citation lands.

**Frozen inputs** (`git show`, read-only): `docs/gen2/PLAN.md` (265 lines) and
`docs/gen2/gen2_requirements.md` (152 lines), both at `f1a69f3`.

**Roots used.** `gen3-migration-planning-5d8e45 <path>` or `gen3-migration-planning-5d8e45/<path>`
-> the Gen 3 worktree; `SWEEP <path>` -> `gen1-rby-code-sweep-8d06e2` (the SWEEP word must sit
immediately before the path — an earlier SWEEP on the same line does not transfer); `research/<f>`
-> `docs/gen2/research/` at HEAD; anything else that exists in this worktree at the plan's stated
revision `4bf0f3b` -> this worktree read through `git show 4bf0f3b:`; everything else -> pret,
`pokecrystal` at the clone pinned by the plan unless the words immediately before/after the
citation say pokegold/Gold. A bare basename is searched in the pret repo (exact case).

## Extractor

Run from the worktree root as `python -c <script>`; exit 0. It is throwaway and is not committed.

```python
"""Throwaway citation resolver (gen2-A3).  python -c <this>, cwd = the worktree root.

Rule for the keyword column, applied literally per the card: the nearest backticked span
before the citation that is not itself a path, a "§" reference, a number or hex value, a
sha, a review id or a worktree name; if that span holds a code fragment with spaces, its
last word is taken. If nothing survives the filter the row is KEYWORD_UNKNOWN.
"""
import re, subprocess, pathlib

WT    = pathlib.Path(r"E:\Google Drive\SLink\.claude\worktrees\gen2-planning-kickoff-a18801")
SWEEP = pathlib.Path(r"E:\Google Drive\SLink\.claude\worktrees\gen1-rby-code-sweep-8d06e2")
GEN3  = pathlib.Path(r"E:\Google Drive\SLink\.claude\worktrees\gen3-migration-planning-5d8e45")
PC    = pathlib.Path(r"C:\Users\howar\AppData\Local\Temp\claude\E--Google-Drive-SLink--claude-worktrees-gen2-planning-kickoff-a18801\17c55ba3-97ae-4ed8-ba47-396926dd84c9\scratchpad\pret_head\pokecrystal")
PG    = pathlib.Path(r"C:\Users\howar\AppData\Local\Temp\claude\E--Google-Drive-SLink--claude-worktrees-gen2-planning-kickoff-a18801\17c55ba3-97ae-4ed8-ba47-396926dd84c9\scratchpad\pret_head\pokegold")
REV   = "4bf0f3b"   # the revision PLAN.md declares for bare worktree paths
DOCS  = [("PLAN", "f1a69f3", "docs/gen2/PLAN.md"),
         ("REQ",  "f1a69f3", "docs/gen2/gen2_requirements.md")]

def sh(args, cwd):
    r = subprocess.run(args, cwd=str(cwd), capture_output=True, encoding="utf-8", errors="replace")
    if r.stdout is None:
        r = subprocess.run(args, cwd=str(cwd), capture_output=True)
        return (r.stdout or b"").decode("utf-8", "replace"), r.returncode
    return r.stdout, r.returncode

_cache = {}
def git_show(rev, path, cwd):
    key = (str(cwd), rev, path)
    if key not in _cache:
        _cache[key] = sh(["git", "show", f"{rev}:{path}"], cwd)
    return _cache[key]

CITE       = re.compile(r'(?P<path>[A-Za-z0-9_.\-/]+\.(?:asm|py|lua|md|json|yml)):(?P<a>\d+)(?:-(?P<b>\d+))?')
CONT_RANGE = re.compile(r'\s*,\s*(\d+)(?:-(\d+))?')
CONT_BARE  = re.compile(r'`:(\d+)(?:-(\d+))?`')
TOKEN      = re.compile(r'`([^`]+)`')
HEXVAL     = re.compile(r'^(0x[0-9A-Fa-f]+|\d+)$')
SHA        = re.compile(r'^[0-9a-f]{7,}(?:…|\.\.\.)?$')
REVIEW_ID  = re.compile(r'^cx-[0-9a-f]+$')
WORKTREES  = {"gen3-migration-planning-5d8e45", "gen1-rby-code-sweep-8d06e2"}

def keyword_before(line, pos):
    best = None
    for m in TOKEN.finditer(line[:pos]):
        t = m.group(1).strip()
        if not t or "." in t or "/" in t or ":" in t or t.startswith("§"):
            continue
        if HEXVAL.match(t) or SHA.match(t) or REVIEW_ID.match(t) or t in WORKTREES:
            continue
        if " " in t:
            words = [w for w in re.split(r'[^A-Za-z0-9_]+', t) if w]
            if not words:
                continue
            t = words[-1]
        best = t
    return best

def pret_candidates(root, path):
    if "/" in path:
        return [path] if (root / path).exists() else []
    return sorted(str(x.relative_to(root)).replace("\\", "/") for x in root.rglob(path) if x.name == path)

rows = []
for tag, rev, docpath in DOCS:
    text, _ = git_show(rev, docpath, WT)
    for ln_no, line in enumerate(text.splitlines(), 1):
        for m in CITE.finditer(line):
            a, b = int(m.group("a")), int(m.group("b") or 0)
            tail = line[m.end():m.end() + 80]
            pre = line[:m.start()]
            gold0 = bool(re.search(r'(?:pokegold|Gold)\s*`?\s*$', pre[-25:]))
            insts = [(a, b, gold0)]
            t = tail
            while True:
                c = CONT_RANGE.match(t)
                if not c: break
                insts.append((int(c.group(1)), int(c.group(2) or 0), gold0)); t = t[c.end():]
            c = CONT_BARE.search(tail)
            if c:
                after = tail[c.end():c.end() + 12]
                insts.append((int(c.group(1)), int(c.group(2) or 0), bool(re.search(r'Gold', after))))
            for a2, b2, gold in insts:
                rows.append(dict(doc=tag, docline=ln_no, path=m.group("path"), a=a2, b=b2,
                                 gold=gold, line=line, pos=m.start()))

def locate(r):
    p, pre = r["path"], r["line"][:r["pos"]]
    if p.startswith("gen3-migration-planning-5d8e45/"):
        rel = p.split("/", 1)[1]
        return "gen3", [rel], lambda x: (GEN3 / x).read_text(encoding="utf-8", errors="replace") if (GEN3 / x).exists() else None
    if re.search(r'gen3-migration-planning-5d8e45[`\s]*$', pre[-40:]):
        return "gen3", [p], lambda x: (GEN3 / x).read_text(encoding="utf-8", errors="replace") if (GEN3 / x).exists() else None
    if re.search(r'SWEEP[`\s]*$', pre):
        return "SWEEP", [p], lambda x: (SWEEP / x).read_text(encoding="utf-8", errors="replace") if (SWEEP / x).exists() else None
    if p.startswith("research/"):
        return "research", [p], lambda x: (WT / "docs" / "gen2" / x).read_text(encoding="utf-8", errors="replace") if (WT / "docs" / "gen2" / x).exists() else None
    if (WT / p).exists() or git_show(REV, p, WT)[1] == 0:
        return "worktree", [p], lambda x: git_show(REV, x, WT)[0]
    root, label = (PG, "pokegold") if r["gold"] else (PC, "pokecrystal")
    return label, pret_candidates(root, p), lambda x: (root / x).read_text(encoding="utf-8", errors="replace") if (root / x).exists() else None

for r in rows:
    label, cands, read = locate(r)
    r["root"], r["cands"], r["ambig"] = label, cands, len(cands) > 1
    r["rel"] = cands[0] if cands else r["path"]
    text = read(r["rel"]) if cands else None
    r["exists"], r["nlines"] = text is not None, len(text.splitlines()) if text else 0
    r["resolves"] = bool(text) and r["a"] <= r["nlines"] and (not r["b"] or r["b"] <= r["nlines"])
    r["kw"] = keyword_before(r["line"], r["pos"])
    r["kw_at"], r["kw_near"], r["kw_hit_file"] = "UNKNOWN", "-", "-"
    if r["kw"]:
        word = re.compile(r'(?<![A-Za-z0-9_])' + re.escape(r["kw"]) + r'(?![A-Za-z0-9_])')
        for cand in cands:
            t2 = read(cand)
            if not t2: continue
            ls = t2.splitlines()
            hi = min(r["b"] or r["a"], len(ls))
            if any(word.search(ls[i - 1]) for i in range(r["a"], hi + 1)):
                r["kw_at"], r["kw_hit_file"] = "YES", cand
                break
            if r["kw_at"] != "NO":
                near = next((i for i, l in enumerate(ls, 1) if word.search(l)), None)
                decl = next((i for i, l in enumerate(ls, 1)
                             if re.match(r'^\s*' + re.escape(r["kw"]) + r'::?\s*$', l)), None)
                tag = f"{near or '-'}" + (f" (decl {decl})" if decl and decl != near else "")
                r["kw_at"], r["kw_near"], r["kw_hit_file"] = "NO", tag, cand

W = 44
print(f"{'doc:ln':<8}{'citation':<{W}}{'root:file':<{W}}{'res':<6}{'keyword':<26}{'kw@':<8}nearest")
for r in rows:
    cite = f"{r['path']}:{r['a']}" + (f"-{r['b']}" if r["b"] else "")
    fl = f"{r['root']}:{r['rel']}" + (f"  AMBIG({len(r['cands'])})" if r["ambig"] else "")
    st = "AMBIG" if r["ambig"] else ("YES" if r["resolves"] else "NO")
    print(f"{r['doc']+':'+str(r['docline']):<8}{cite:<{W}}{fl:<{W}}{st:<6}"
          f"{str(r['kw'] or 'KEYWORD_UNKNOWN'):<26}{r['kw_at']:<8}{r['kw_near']}")
print()
n = len(rows)
print(f"n={n} resolved={sum(r['resolves'] for r in rows)} unresolved={sum(not r['resolves'] for r in rows)} "
      f"ambiguous={sum(r['ambig'] for r in rows)}")
print(f"kw_at_cited={sum(r['kw_at']=='YES' for r in rows)} kw_NO={sum(r['kw_at']=='NO' for r in rows)} "
      f"kw_UNKNOWN={sum(r['kw_at']=='UNKNOWN' for r in rows)}")
print(f"misses={sum((not r['resolves']) or r['kw_at']=='NO' for r in rows)}")
print("unresolved:", sorted({f"{r['root']}:{r['path']}:{r['a']}-{r['b']}" for r in rows if not r["resolves"]}))
print("ambiguous cands:", sorted({(r["path"], tuple(r["cands"])) for r in rows if r["ambig"]}))
print("keyword-rule artifacts left in:", sorted({r["kw"] for r in rows if r["kw"] and (SHA.match(r["kw"]) or REVIEW_ID.match(r["kw"]) or r["kw"] in WORKTREES)}))

print()
print("---- kw_NO detail (cited-line text, for judging rule artifacts) ----")
for r in rows:
    if r["kw_at"] != "NO":
        continue
    label, cands, read = r["root"], r["cands"], None
    path = r["rel"]
    if r["root"] == "worktree": text = git_show(REV, path, WT)[0]
    elif r["root"] == "pokecrystal": text = (PC / path).read_text(encoding="utf-8", errors="replace")
    elif r["root"] == "pokegold": text = (PG / path).read_text(encoding="utf-8", errors="replace")
    elif r["root"] == "gen3": text = (GEN3 / path).read_text(encoding="utf-8", errors="replace")
    elif r["root"] == "SWEEP": text = (SWEEP / path).read_text(encoding="utf-8", errors="replace")
    else: text = (WT / "docs" / "gen2" / path).read_text(encoding="utf-8", errors="replace")
    ls = text.splitlines()
    hi = min(r["b"] or r["a"], len(ls))
    body = " / ".join(l.strip()[:88] for l in ls[r["a"] - 1:hi])
    print(f"{r['doc']}:{r['docline']} {r['path']}:{r['a']}{'-'+str(r['b']) if r['b'] else ''} "
          f"| kw={r['kw']} | near={r['kw_near']} | {body[:220]}")
print()
print("---- absence-asserting cites (plan says the thing is NOT there) ----")
print("server/server.py:491-511 contains 'pairing_kind':",
      "pairing_kind" in git_show(REV, "server/server.py", WT)[0])
print("server/adapters/base.py:126-173 (worktree) contains 'pairing_kind':",
      "pairing_kind" in git_show(REV, "server/adapters/base.py", WT)[0])
```

## Table

`file` is the resolved root plus path. `keyword` is the nearest backticked identifier before the
citation (the card's rule), skipping tokens that are themselves paths, §-refs, numbers/hex, sha
fragments, `cx-…` review ids or worktree names; a backticked *code fragment* with spaces
contributes its last word. `keyword at cited line` is a word-boundary search inside the cited
line/range of the resolved file. `nearest occurrence` is the first line of that file holding the
keyword when it is not at the cited line (`(decl N)` marks the first real declaration line when
that differs from the first mention).

| # | citation | file (root:path) | resolves | keyword | keyword at cited line | nearest occurrence |
|---|---|---|---|---|---|---|
| 1 | `docs/gen1_gen2_runtime_checks.md:205-213` | `worktree:docs/gen1_gen2_runtime_checks.md` | YES | `battle` | NO | 33 |
| 2 | `docs/purergb/PLAN.md:39-44` | `worktree:docs/purergb/PLAN.md` | YES | `*KEYWORD_UNKNOWN*` | UNKNOWN | - |
| 3 | `docs/gen1_requirements.md:3-11` | `worktree:docs/gen1_requirements.md` | YES | `*KEYWORD_UNKNOWN*` | UNKNOWN | - |
| 4 | `lua/tests/gen2_playthrough.lua:283-298` | `worktree:lua/tests/gen2_playthrough.lua` | YES | `*KEYWORD_UNKNOWN*` | UNKNOWN | - |
| 5 | `gen3-migration-planning-5d8e45/docs/gen3/PLAN.md:23-38` | `gen3:docs/gen3/PLAN.md` | YES | `*KEYWORD_UNKNOWN*` | UNKNOWN | - |
| 6 | `lua/gen1/entry.lua:301-328` | `worktree:lua/gen1/entry.lua` | YES | `*KEYWORD_UNKNOWN*` | UNKNOWN | - |
| 7 | `research/pret_gen2_symbols.md:10-11` | `research:research/pret_gen2_symbols.md` | YES | `rom_sha1` | YES | - |
| 8 | `lua/tests/gen2_playthrough.lua:22-40` | `worktree:lua/tests/gen2_playthrough.lua` | YES | `*KEYWORD_UNKNOWN*` | UNKNOWN | - |
| 9 | `lua/tests/gen2_playthrough.lua:283-298` | `worktree:lua/tests/gen2_playthrough.lua` | YES | `*KEYWORD_UNKNOWN*` | UNKNOWN | - |
| 10 | `docs/gen1_gen2_runtime_checks.md:193` | `worktree:docs/gen1_gen2_runtime_checks.md` | YES | `*KEYWORD_UNKNOWN*` | UNKNOWN | - |
| 11 | `docs/shared_runtime.md:59` | `SWEEP:docs/shared_runtime.md` | **NO** | `*KEYWORD_UNKNOWN*` | UNKNOWN | - |
| 12 | `docs/gen1_gen2_runtime_checks.md:174-177` | `worktree:docs/gen1_gen2_runtime_checks.md` | YES | `*KEYWORD_UNKNOWN*` | UNKNOWN | - |
| 13 | `research/pret_gen2_symbols.md:10` | `research:research/pret_gen2_symbols.md` | YES | `*KEYWORD_UNKNOWN*` | UNKNOWN | - |
| 14 | `docs/purergb/PLAN.md:49` | `worktree:docs/purergb/PLAN.md` | YES | `*KEYWORD_UNKNOWN*` | UNKNOWN | - |
| 15 | `engine/events/whiteout.asm:14` | `pokecrystal:engine/events/whiteout.asm` | YES | `HealParty` | YES | - |
| 16 | `item_effects.asm:548-556` | `pokecrystal:engine/items/item_effects.asm` | YES | `SendMonIntoBox` | NO | 612 |
| 17 | `item_effects.asm:609-632` | `pokecrystal:engine/items/item_effects.asm` | YES | `SendMonIntoBox` | YES | - |
| 18 | `core.asm:2656-2688` | `pokecrystal:engine/battle/core.asm` **AMBIG(3)** | **AMBIG** | `UpdateFaintedPlayerMon` | YES | - |
| 19 | `engine/overworld/events.asm:495` | `pokecrystal:engine/overworld/events.asm` | YES | `CheckAPressOW` | YES | - |
| 20 | `engine/overworld/events.asm:483` | `pokegold:engine/overworld/events.asm` | YES | `CheckAPressOW` | YES | - |
| 21 | `lua/gen1_write_safety.lua:23-109` | `worktree:lua/gen1_write_safety.lua` | YES | `wBattleMode` | NO | - |
| 22 | `constants/pokemon_data_constants.asm:77-101` | `pokecrystal:constants/pokemon_data_constants.asm` | YES | `EraseBoxes` | NO | - |
| 23 | `save.asm:526-537` | `pokecrystal:engine/menus/save.asm` | YES | `CalcMonStats` | NO | - |
| 24 | `save.asm:583-594` | `pokecrystal:engine/menus/save.asm` | YES | `CalcMonStats` | NO | - |
| 25 | `save.asm:495-536` | `pokegold:engine/menus/save.asm` | YES | `CalcMonStats` | NO | - |
| 26 | `save.asm:596-640` | `pokecrystal:engine/menus/save.asm` | YES | `TryLoadSaveFile` | YES | - |
| 27 | `save.asm:26-37` | `pokecrystal:engine/menus/save.asm` | YES | `SaveAfterLinkTrade` | YES | - |
| 28 | `maps/ElmsLab.asm:274-277` | `pokecrystal:maps/ElmsLab.asm` | YES | `ElmDirectionsScript` | NO | 185 (decl 251) |
| 29 | `docs/gen1_requirements.md:51` | `worktree:docs/gen1_requirements.md` | YES | `ElmDirectionsScript` | NO | - |
| 30 | `docs/shared_runtime.md:59` | `SWEEP:docs/shared_runtime.md` | **NO** | `gen2_new` | UNKNOWN | - |
| 31 | `docs/gen1_gen2_runtime_checks.md:186-191` | `worktree:docs/gen1_gen2_runtime_checks.md` | YES | `saveram_dir` | YES | - |
| 32 | `server/server.py:491-511` | `worktree:server/server.py` | YES | `pairing_kind` | NO | - |
| 33 | `server/adapters/base.py:309` | `gen3:server/adapters/base.py` | YES | `game_id` | NO | 73 |
| 34 | `lua/gen1/entry.lua:229-266` | `worktree:lua/gen1/entry.lua` | YES | `crystal_ap` | NO | - |
| 35 | `lua/gen1/signals.lua:11-13` | `worktree:lua/gen1/signals.lua` | YES | `hLoadedROMBank` | YES | - |
| 36 | `home/joypad.asm:1-6` | `pokecrystal:home/joypad.asm` | YES | `reti` | YES | - |
| 37 | `engine/menus/start_menu.asm:513-519` | `pokecrystal:engine/menus/start_menu.asm` | YES | `DelayFrame` | YES | - |
| 38 | `engine/link/link.asm:1994` | `pokecrystal:engine/link/link.asm` | YES | `AddTempmonToParty` | YES | - |
| 39 | `engine/link/link.asm:1998` | `pokecrystal:engine/link/link.asm` | YES | `AddTempmonToParty` | NO | 1994 |
| 40 | `docs/gen1_requirements.md:21` | `worktree:docs/gen1_requirements.md` | YES | `on_bus_exec` | YES | - |
| 41 | `server/adapters/base.py:126-173` | `worktree:server/adapters/base.py` | YES | `is_shiny` | YES | - |
| 42 | `tests/unit/test_gen1_identity_and_collisions.py:97-100` | `worktree:tests/unit/test_gen1_identity_and_collisions.py` | YES | `*KEYWORD_UNKNOWN*` | UNKNOWN | - |
| 43 | `tools/gen1_fixtures.py:240` | `worktree:tools/gen1_fixtures.py` | YES | `_ot2` | NO | - |
| 44 | `maps/ElmsLab.asm:274-277` | `pokecrystal:maps/ElmsLab.asm` | YES | `ElmDirectionsScript` | NO | 185 (decl 251) |
| 45 | `maps/NewBarkTown.asm:292-293` | `pokecrystal:maps/NewBarkTown.asm` | YES | `SCENE_NEWBARKTOWN_TEACHER_STOPS_YOU` | YES | - |
| 46 | `ElmsLab.asm:182` | `pokecrystal:maps/ElmsLab.asm` | YES | `*KEYWORD_UNKNOWN*` | UNKNOWN | - |
| 47 | `marts.asm:40-44` | `pokecrystal:data/items/marts.asm` | YES | `*KEYWORD_UNKNOWN*` | UNKNOWN | - |
| 48 | `ElmsLab.asm:498-508` | `pokecrystal:maps/ElmsLab.asm` | YES | `5` | YES | - |
| 49 | `docs/gen1_requirements.md:3-7` | `worktree:docs/gen1_requirements.md` | YES | `*KEYWORD_UNKNOWN*` | UNKNOWN | - |
| 50 | `docs/gen1_requirements.md:9` | `worktree:docs/gen1_requirements.md` | YES | `*KEYWORD_UNKNOWN*` | UNKNOWN | - |
| 51 | `docs/gen1_requirements.md:26-32` | `worktree:docs/gen1_requirements.md` | YES | `*KEYWORD_UNKNOWN*` | UNKNOWN | - |
| 52 | `constants/pokemon_constants.asm:171-274` | `pokecrystal:constants/pokemon_constants.asm` | YES | `*KEYWORD_UNKNOWN*` | UNKNOWN | - |
| 53 | `tools/gen1_fixtures.py:240` | `worktree:tools/gen1_fixtures.py` | YES | `red_town_ot2` | NO | - |
| 54 | `maps/ElmsLab.asm:498-508` | `pokecrystal:maps/ElmsLab.asm` | YES | `battle` | NO | 851 |
| 55 | `engine/menus/save.asm:596-640` | `pokecrystal:engine/menus/save.asm` | YES | `battle` | NO | 417 |
| 56 | `data/wild/johto_grass.asm:341-364` | `pokecrystal:data/wild/johto_grass.asm` | YES | `*KEYWORD_UNKNOWN*` | UNKNOWN | - |
| 57 | `item_effects.asm:548-550` | `pokecrystal:engine/items/item_effects.asm` | YES | `SendMonIntoBox` | NO | 612 |
| 58 | `item_effects.asm:609-618` | `pokecrystal:engine/items/item_effects.asm` | YES | `SendMonIntoBox` | YES | - |
| 59 | `whiteout.asm:14` | `pokecrystal:engine/events/whiteout.asm` | YES | `HealParty` | YES | - |
| 60 | `save.asm:266-281` | `pokecrystal:engine/menus/save.asm` | YES | `SaveBox` | YES | - |
| 61 | `save.asm:470-475` | `pokecrystal:engine/menus/save.asm` | YES | `wSavedAtLeastOnce` | YES | - |
| 62 | `save.asm:360-366` | `pokecrystal:engine/menus/save.asm` | YES | `EraseBoxes` | YES | - |
| 63 | `docs/gen1_requirements.md:161-190` | `worktree:docs/gen1_requirements.md` | **NO** | `*KEYWORD_UNKNOWN*` | UNKNOWN | - |

## Summary

- **63 citation instances** extracted from the two files, from 58 citing lines; comma-
  continuations (`:548-556, 609-632`) and the `Crystal` / `:483` `Gold` form are expanded into
  separate rows. 25 rows come from `PLAN.md`, 38 from `gen2_requirements.md`.
- **60 resolve** (file exists at the resolved root and the line/range is inside it), **3 do not**, 
  **1 is ambiguous**.
- **22 rows** have the keyword at the cited line; **19** have it elsewhere in the same file; **22**
  have no identifier in the citing span (KEYWORD_UNKNOWN — a limit of the same-line rule, not a
  defect).
- **misses = 22** (3 unresolved + 19 keyword-elsewhere).

### The three unresolved citations

| citation | root | why |
|---|---|---|
| `SWEEP docs/shared_runtime.md:59` (PLAN §2 and §5.8) | `gen1-rby-code-sweep-8d06e2` | no `docs/shared_runtime.md` anywhere in that worktree (its `docs/` holds `FRAMEWORK.md` and a `shared-*.md` family, but not that name). The second root does exist: `SWEEP docs/gen1_reference/GEN3_BINDING_PLAN.md` is present. |
| `docs/gen1_requirements.md:161-190` (REQ "Recorded limits") | this worktree | the file is **189 lines** at both `4bf0f3b` and HEAD, so line 190 is one past the end. |

### The one ambiguous citation

`core.asm:2656-2688` (PLAN §5.3, faint site) is a bare basename matching three pokecrystal files: 
`engine/battle/core.asm`, `engine/battle_anims/core.asm`, `engine/sprite_anims/core.asm`. The
keyword `UpdateFaintedPlayerMon` **is** present in `engine/battle/core.asm` at the cited lines, so
the intent is unambiguous in practice; the path is not.

### Keyword-elsewhere rows — read the cited text before treating any as a defect

```text
---- kw_NO detail (cited-line text, for judging rule artifacts) ----
PLAN:22 docs/gen1_gen2_runtime_checks.md:205-213 | kw=battle | near=33 | - **A Gen 2 playthrough — deliberately not bought.** Gen 2's fixture parks indoors, beca / New Bark Town's west exit is script-locked until Elm hands over a starter; there is no g / fixture and so no `playthrough`, `dead
PLAN:132 item_effects.asm:548-556 | kw=SendMonIntoBox | near=612 | ld a, [wPartyCount] / cp PARTY_LENGTH / jr z, .SendToPC /  / xor a ; PARTYMON / ld [wMonType], a / call ClearSprites /  / predef TryAddMonToParty
PLAN:133 lua/gen1_write_safety.lua:23-109 | kw=wBattleMode | near=- | function M.check(profile, io) / local ok, safe, reason = pcall(function() / local p = profile and profile.write_safe / local pure = type(p) == "table" and p.version == M.VERSION_PURERGB / if type(p) ~= "table" or (p.vers
PLAN:134 constants/pokemon_data_constants.asm:77-101 | kw=EraseBoxes | near=- | DEF MON_SPECIES            rb / DEF MON_ITEM               rb / DEF MON_MOVES              rb NUM_MOVES / DEF MON_OT_ID              rw / DEF MON_EXP                rb 3 / DEF MON_STAT_EXP           rw NUM_EXP_STATS / rs
PLAN:135 save.asm:526-537 | kw=CalcMonStats | near=- | SaveChecksum: / ld hl, sGameData / ld bc, sGameDataEnd - sGameData / ld a, BANK(sGameData) / call OpenSRAM / call Checksum / ld a, e / ld [sChecksum + 0], a / ld a, d / ld [sChecksum + 1], a / call CloseSRAM / ret
PLAN:135 save.asm:583-594 | kw=CalcMonStats | near=- | SaveBackupChecksum: / ld hl, sBackupGameData / ld bc, sBackupGameDataEnd - sBackupGameData / ld a, BANK(sBackupGameData) / call OpenSRAM / call Checksum / ld a, e / ld [sBackupChecksum + 0], a / ld a, d / ld [sBackupChec
PLAN:135 save.asm:495-536 | kw=CalcMonStats | near=- | SaveBackupChecksum: / ld a, BANK(sBackupPlayerData3) / call OpenSRAM / ld hl, sBackupPlayerData3 / ld bc, wPlayerData3End - wPlayerData3 / call Checksum / push de / ld hl, sBackupPokemonData / ld bc, wPokemonDataEnd - wP
PLAN:135 save.asm:596-640 | kw=CalcMonStats | near=- | TryLoadSaveFile: / call VerifyChecksum / jr nz, .backup / call LoadPlayerData / call LoadPokemonData / call LoadBox / farcall RestorePartyMonMail / farcall RestoreGSBallFlag / farcall RestoreMysteryGift / call ValidateBa
PLAN:135 save.asm:26-37 | kw=CalcMonStats | near=- | SaveAfterLinkTrade: / call PauseGameLogic / farcall StageRTCTimeForSave / farcall BackupMysteryGift / call SavePokemonData / call SaveChecksum / call SaveBackupPokemonData / call SaveBackupChecksum / farcall BackupPartyM
PLAN:136 maps/ElmsLab.asm:274-277 | kw=ElmDirectionsScript | near=185 (decl 251) | setevent EVENT_GOT_A_POKEMON_FROM_ELM / setevent EVENT_RIVAL_CHERRYGROVE_CITY / setscene SCENE_ELMSLAB_AIDE_GIVES_POTION / setmapscene NEW_BARK_TOWN, SCENE_NEWBARKTOWN_NOOP
PLAN:136 docs/gen1_requirements.md:51 | kw=ElmDirectionsScript | near=- | | F-6 | Fixtures re-qualified: each `tests/fixtures/gen1/*.SaveRAM` passes the game's ow
PLAN:138 server/server.py:491-511 | kw=pairing_kind | near=- | def _mixed_games_error(self, player_id: str, rom_type: str, artifact_kind: str) -> str: / """Why this hello cannot join the committed run, or "" when it can: the run is / locked to one game_id (variants of one game -- Re
PLAN:138 server/adapters/base.py:309 | kw=game_id | near=73 | def pairing_kind(kind: str) -> str:
PLAN:138 lua/gen1/entry.lua:229-266 | kw=crystal_ap | near=- | function Entry.admit(args) / local table_ = Entry.admission_table(args.root, args.json) / local sha = (args.rom_sha1 or ""):lower() / local hit = table_[sha] / local rehashed = false / if (not hit or args.indatabase) and
PLAN:141 engine/link/link.asm:1998 | kw=AddTempmonToParty | near=1994 | callfar EvolvePokemon
PLAN:153 tools/gen1_fixtures.py:240 | kw=_ot2 | near=- | if args.target == "town_ot2" and ot == DEFAULT_OT:
PLAN:195 maps/ElmsLab.asm:274-277 | kw=ElmDirectionsScript | near=185 (decl 251) | setevent EVENT_GOT_A_POKEMON_FROM_ELM / setevent EVENT_RIVAL_CHERRYGROVE_CITY / setscene SCENE_ELMSLAB_AIDE_GIVES_POTION / setmapscene NEW_BARK_TOWN, SCENE_NEWBARKTOWN_NOOP
REQ:54 tools/gen1_fixtures.py:240 | kw=red_town_ot2 | near=- | if args.target == "town_ot2" and ot == DEFAULT_OT:
REQ:54 maps/ElmsLab.asm:498-508 | kw=battle | near=851 | AideScript_GiveYouBalls: / opentext / writetext AideText_GiveYouBalls / promptbutton / getitemname STRING_BUFFER_4, POKE_BALL / scall AideScript_ReceiveTheBalls / giveitem POKE_BALL, 5 / writetext AideText_ExplainBalls /
REQ:54 engine/menus/save.asm:596-640 | kw=battle | near=417 | TryLoadSaveFile: / call VerifyChecksum / jr nz, .backup / call LoadPlayerData / call LoadPokemonData / call LoadBox / farcall RestorePartyMonMail / farcall RestoreGSBallFlag / farcall RestoreMysteryGift / call ValidateBa
REQ:72 item_effects.asm:548-550 | kw=SendMonIntoBox | near=612 | ld a, [wPartyCount] / cp PARTY_LENGTH / jr z, .SendToPC
REQ:89 save.asm:360-366 | kw=wSavedAtLeastOnce | near=374 | ErasePreviousSave: / call EraseBoxes / call EraseHallOfFame / call EraseLinkBattleStats / call EraseMysteryGift / call SaveData / call EraseBattleTowerStatus
```

Two of those 19 are not defects at all:

- `server/server.py:491-511` with keyword `pairing_kind` — the sentence *asserts absence* ("The
  `pairing_kind` hook is NOT on master at `4bf0f3b`"). Verified: the string `pairing_kind` does not
  occur anywhere in `server/server.py` at `4bf0f3b`, and the cited range is `_mixed_games_error`,
  which is what the sentence says it compares.
- `server/adapters/base.py:309` keyword `game_id` — the row was resolved in the **Gen 3** worktree,
  where line 309 is literally `def pairing_kind(kind: str) -> str:`, i.e. the citation is exact and
  the keyword column is an artifact of the preceding clause.

Others are plainly the rule picking a topic word, a review id or a value (`battle`, `EraseBoxes`,
`CalcMonStats`, `wBattleMode`, `crystal_ap`, `5`); the cited text in the block above shows those
citations land on the SaveChecksum / box-struct / Aide-gives-balls / admission code the sentences
describe. Two are worth a second look rather than a shrug:

- `maps/ElmsLab.asm:274-277` (cited twice, PLAN §5.7 and §8) — the range is the tail of
  `ElmDirectionsScript` (`setevent … / setscene … / setmapscene NEW_BARK_TOWN, …`). The label
  itself is at **251** and its first mention at **185**; the range contains neither. The citation
  points at the release commands, not the label, which is what the sentence claims.
- `engine/link/link.asm:1998` — the keyword `AddTempmonToParty` occurs at **1994**, four lines
  earlier; 1998 is `callfar EvolvePokemon`. The sibling citation `link.asm:1994` is exact.
- `tools/gen1_fixtures.py:240` — keyword `_ot2` (PLAN) / `red_town_ot2` (REQ): the cited line reads
  `if args.target == "town_ot2" and ot == DEFAULT_OT:`. `town_ot2` is a substring; the
  word-boundary search rejects it because the character before `_ot2` is a letter, and
  `red_town_ot2` (the fixture name the REQ sentence uses) is not on that line at all.

### Method caveats

- Worktree files are read at `4bf0f3b`, the revision the plan's preamble declares. For
  `docs/gen1_requirements.md` the line count is the same (189) at `4bf0f3b` and HEAD, so the
  unresolved row is not a revision artifact.
- `research/` notes are read from the filesystem (HEAD), since the plan calls them live notes;
  `core.asm` and the two `ElmsLab.asm` rows were reported from the pokecrystal clone as the brief
  requires. `data/wild/johto_grass.asm:341-364` resolves in the pokecrystal clone.
- The extractor only sees the two frozen files, so a citation that resolves here is not evidence
  that the cited line supports the claim — that is the coordinator's read.

DONE gen2-A3: 63 citations, 60 resolve, 22 keyword at cited line, 22 misses
