# gen2-A4 — citation resolver, second pass (GEN2_STANDARD_COMPARISON + GEN2_BINDING_PLAN)

Machine resolution of every `<path>:<line>` / `<path>:<a>-<b>` citation in the two frozen
documents. It measures whether a citation lands; it does not judge the claims.

**Frozen inputs** (`git show`, read-only): `docs/gen2/GEN2_STANDARD_COMPARISON.md` (220 lines)
and `docs/gen2/GEN2_BINDING_PLAN.md` (510 lines), both at `3a91a97`. Neither was modified.

**Roots.** Identical to gen2-A3, with two additions this pair needs: a `pokecrystal@<sha>` /
`pokegold@<sha>` prefix before the path selects the pret clone, and a bare basename with no `/`
is looked up in this worktree first (these documents write `gen2_crystal_client.lua:539-568`
meaning `lua/clients/...`). Worktree files are read at `3a91a97` via `git show`. `.git`, `.claude`,
`.cache`, `build`, `dist`, `node_modules` are excluded from the basename index, so archived
worktree copies under `.claude/worktrees-archive/` cannot shadow the live file (they did on the
first pass, and resolving them would have been wrong).

## Extractor

Run from the worktree root as `python -c <script>`; exit 0. Throwaway, not committed.

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
REV   = "3a91a97"
DOCS  = [("GEN2_STANDARD_COMPARISON", "3a91a97", "docs/gen2/GEN2_STANDARD_COMPARISON.md"),
         ("GEN2_BINDING_PLAN",        "3a91a97", "docs/gen2/GEN2_BINDING_PLAN.md")]

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

def markdown(tag):
    out = ["| # | citation | file (root:path) | resolves | keyword | keyword at cited line | nearest occurrence | cited line text |",
           "|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate([x for x in rows if x["doc"] == tag], 1):
        cite = f"`{r['path']}:{r['a']}" + (f"-{r['b']}`" if r["b"] else "`")
        fl = f"`{r['root']}:{r['rel']}`" + (f" **AMBIG({len(r['cands'])})**" if r["ambig"] else "")
        st = "**AMBIG**" if r["ambig"] else ("YES" if r["resolves"] else "**NO**")
        txt = r["cited_text"].replace("|", "\\|")[:58]
        out.append(f"| {i} | {cite} | {fl} | {st} | `{r['kw'] or 'KEYWORD_UNKNOWN'}` | "
                   f"{r['kw_at']} | {r['kw_near']} | {txt} |")
    return "\n".join(out)

print(markdown("GEN2_STANDARD_COMPARISON"))
print()
print(markdown("GEN2_BINDING_PLAN"))
print()
for tag in ("GEN2_STANDARD_COMPARISON", "GEN2_BINDING_PLAN"):
    rs = [r for r in rows if r["doc"] == tag]
    print(f"{tag}: n={len(rs)} resolved={sum(r['resolves'] for r in rs)} "
          f"unresolved={sum(not r['resolves'] for r in rs)} ambiguous={sum(r['ambig'] for r in rs)} "
          f"kw_YES={sum(r['kw_at']=='YES' for r in rs)} kw_NO={sum(r['kw_at']=='NO' for r in rs)} "
          f"kw_UNKNOWN={sum(r['kw_at']=='UNKNOWN' for r in rs)}")
n = len(rows)
print(f"TOTAL n={n} resolved={sum(r['resolves'] for r in rows)} "
      f"unresolved={sum(not r['resolves'] for r in rows)} ambiguous={sum(r['ambig'] for r in rows)} "
      f"kw_YES={sum(r['kw_at']=='YES' for r in rows)} kw_NO={sum(r['kw_at']=='NO' for r in rows)} "
      f"kw_UNKNOWN={sum(r['kw_at']=='UNKNOWN' for r in rows)}")
print()
print("---- unresolved / ambiguous ----")
for r in rows:
    if not r["resolves"] or r["ambig"]:
        print(f"{r['doc']}:{r['docline']} {r['path']}:{r['a']}-{r['b']} -> {r['root']}:{r['rel']} "
              f"exists={r['exists']} nlines={r['nlines']} cands={r['cands']}")
print()
print("---- kw_NO rows (cited text) ----")
for r in rows:
    if r["kw_at"] == "NO":
        print(f"{r['doc']}:{r['docline']} {r['path']}:{r['a']}{'-'+str(r['b']) if r['b'] else ''} "
              f"| kw={r['kw']} | near={r['kw_near']} | {r['cited_text'][:190]}")
```

## Table: GEN2_STANDARD_COMPARISON

`file` is the resolved root plus path; `keyword` is the nearest backticked identifier before the
citation (paths, §-refs, numbers/hex, shas, `cx-…` ids, worktree names and `repo@sha` pins are
skipped; a backticked code fragment contributes its last word). `keyword at cited line` is a
word-boundary search inside the cited range of the resolved file and is **noise-tolerant by
design** — with 33 table rows per behaviour, the nearest backticked token is often the previous
clause's identifier. `cited line text` is the cited range itself, which is the thing to read.

| # | citation | file (root:path) | resolves | keyword | keyword at cited line | nearest occurrence | cited line text |
|---|---|---|---|---|---|---|---|
| 1 | `tests/live/test_gen2_gates.py:43-48` | `worktree:tests/live/test_gen2_gates.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | GATES = { / "lua/tests/test_gen2_memory_gate.lua": "town", |
| 2 | `tests/e2e/test_duo_gen2.py:50` | `worktree:tests/e2e/test_duo_gen2.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | SCENARIOS = ("faint", "boxsync", "memorialize") |
| 3 | `lua/tests/gen2_playthrough.lua:283-298` | `worktree:lua/tests/gen2_playthrough.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- Write a level-5 Totodile into slot 0 rather than drivin |
| 4 | `docs/gen1_requirements.md:5-7` | `worktree:docs/gen1_requirements.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | (real cartridge in BizHawk, judged by an oracle that is no |
| 5 | `gen2_crystal_client.lua:801-978` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | local function diff_party() / local count = M.getPartyCoun |
| 6 | `lua/gen1/signals.lua:1-18` | `worktree:lua/gen1/signals.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- lua/gen1/signals.lua — Gen 1 game events detected from  |
| 7 | `gen2_crystal_client.lua:539-568` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `rom_content` | NO | - | local evt = { / event = "hello", / game_id = G.game_id, /  |
| 8 | `server/adapters/base.py:403-415` | `worktree:server/adapters/base.py` | YES | `rom_content_fingerprint` | YES | - | def rom_content_fingerprint(self, payload: dict) -> str \| |
| 9 | `gen2_crystal_client.lua:256-267` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | if c.cmd == "force_faint" and c.key then / if writes_enabl |
| 10 | `lua/memory_gb.lua:833-837` | `worktree:lua/memory_gb.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | function M.forceFaint(slot) / local base = M.PARTY_BASE_AD |
| 11 | `lua/memory_gb.lua:812-832` | `worktree:lua/memory_gb.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | --- Kill a party mon. Writes the party struct AND, when th |
| 12 | `gen2_crystal_client.lua:964-972` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `species_id` | NO | 428 | if post_battle_frames == 1 and not captured_this_battle an |
| 13 | `lua/games/gen2_crystal.lua:228` | `worktree:lua/games/gen2_crystal.lua` | YES | `nil` | YES | - | SFX_DISPATCH_ADDR       = nil, |
| 14 | `lua/memory_gb.lua:672-677` | `worktree:lua/memory_gb.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- A whole party mon as raw bytes, for handing the partner |
| 15 | `research/pret_gen2_symbols.md:25-43` | `research:research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| `MON_SPECIES` \| pokecrystal@7a7881d constants/pokemon_ |
| 16 | `server/adapters/gen2_crystal.py:160-167` | `worktree:server/adapters/gen2_crystal.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | then wPartyMonNicknames), so a faithful copy is this compo |
| 17 | `research/pret_gen2_symbols.md:36-41` | `research:research/pret_gen2_symbols.md` | YES | `MON_HP` | YES | - | \| `MON_LEVEL` \| pokecrystal@7a7881d constants/pokemon_da |
| 18 | `docs/gen1_requirements.md:79` | `worktree:docs/gen1_requirements.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| W-1 \| `force_faint` on a benched mon (overworld): part |
| 19 | `lua/memory_gb.lua:698-726` | `worktree:lua/memory_gb.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- The party-only stats a box struct cannot hold, read BEF |
| 20 | `gen2_crystal_client.lua:1282-1296` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- Read the party-only tail BEFORE depositing. Gen 2's 32- |
| 21 | `lua/gen1/boxes.lua:26` | `worktree:lua/gen1/boxes.lua` | YES | `SaveChecksum` | NO | - | local function checksum(bytes, first, n) |
| 22 | `lua/gen1/boxes.lua:168-199` | `worktree:lua/gen1/boxes.lua` | YES | `SaveChecksum` | NO | - | raw[info.individual + slot] = checksum(raw, slot * d.sram_ |
| 23 | `research/pret_gen2_symbols.md:72-76` | `research:research/pret_gen2_symbols.md` | YES | `SaveChecksum` | YES | - | \| `MONS_PER_BOX` \| 20 \| 20 \| pokecrystal@7a7881d const |
| 24 | `lua/gen1/boxes.lua:476` | `worktree:lua/gen1/boxes.lua` | YES | `B9E0` | NO | - | local memorial = box_count - 1 -- sBox12: ram/sram.asm:44- |
| 25 | `gen2_crystal_client.lua:700` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `B9E0` | NO | - | local MEMORIAL_BOX_INDEX = 13 |
| 26 | `lua/memory_gb.lua:1413` | `worktree:lua/memory_gb.lua` | YES | `B9E0` | NO | - | mem_off = 0x79E0 |
| 27 | `docs/gen2/REVIEW_RECORD.md:39` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `B9E0` | NO | 52 | ## Codex "Gen2 Base" |
| 28 | `research/pret_gen2_symbols.md:70` | `research:research/pret_gen2_symbols.md` | YES | `B9E0` | NO | - | \| `sBox14` \| 0xb9e0 \| 0xb9e0 \| pokecrystal@7a7881d ram |
| 29 | `lua/gen1/boxes.lua:213` | `worktree:lua/gen1/boxes.lua` | YES | `0` | NO | 9 | if not current.initialized then return nil, "saved boxes n |
| 30 | `lua/gen1/boxes.lua:239` | `worktree:lua/gen1/boxes.lua` | YES | `0` | NO | 9 | function self.ensure_boxes_initialised() |
| 31 | `docs/gen1_gen2_runtime_checks.md:147-151` | `worktree:docs/gen1_gen2_runtime_checks.md` | YES | `0` | NO | 58 | * Carried forward from the pre-rewrite client, because the |
| 32 | `docs/gen2/REVIEW_RECORD.md:38` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `0` | NO | 32 |  |
| 33 | `docs/gen2/REVIEW_RECORD.md:41` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `0` | NO | 32 | ### cx-3569f8d9 — FACT_CHECK gen2-C1 (round 1, 2026-09-21) |
| 34 | `lua/games/gen2_crystal.lua:144-148` | `worktree:lua/games/gen2_crystal.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- party_struct tail (pret macros/ram.asm): Atk +0x26, Def |
| 35 | `research/pret_gen2_symbols.md:42` | `research:research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| `MON_STATS` (ATK/DEF/SPD/SAT/SDF, 5×`rw`) \| pokecrysta |
| 36 | `lua/games/gen2_crystal.lua:136` | `worktree:lua/games/gen2_crystal.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | held_item_offset     = 0x01,    -- held item (new in Gen 2 |
| 37 | `gen2_crystal_client.lua:433-435` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | if mon.held_item and mon.held_item > 0 then / entry.held_i |
| 38 | `gen2_crystal_client.lua:657-660` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- Gen 2: include held item if present / if mon.held_item  |
| 39 | `docs/gen1_requirements.md:50` | `worktree:docs/gen1_requirements.md` | YES | `CHIKORITA` | NO | - | \| F-5 \| Evolution families from pret `evos_moves.asm` (G |
| 40 | `research/pret_gen2_symbols.md:191` | `research:research/pret_gen2_symbols.md` | YES | `CHIKORITA` | YES | - | Internal species IDs run `const_def 1` through `NUM_POKEMO |
| 41 | `lua/games/gen2_crystal.lua:20-25` | `worktree:lua/games/gen2_crystal.lua` | YES | `CHIKORITA` | NO | - | function M.toNatDex(species_id) / if species_id >= 1 and s |
| 42 | `lua/games/gen2_crystal.lua:595-610` | `worktree:lua/games/gen2_crystal.lua` | YES | `g*256+n` | NO | - | function M.resolve_area(mapGroup, mapNumber) / if not M._a |
| 43 | `research/rom_hashes.md:82-86` | `research:research/rom_hashes.md` | YES | `$FF70` | NO | - | - Internal cartridge title (`rgbfix -t`): `PM_CRYSTAL` (`p |
| 44 | `research/bizhawk_gambatte_gbc.md:159-195` | `research:research/bizhawk_gambatte_gbc.md` | YES | `$FF70` | NO | - | ## 4. DMG vs CGB mode selection (`ConsoleMode`) /  / Sync  |
| 45 | `gen2_crystal_client.lua:1056-1066` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `$FF70` | NO | - | -- WRAM bank safety check: Crystal uses WRAM banks (SVBK r |
| 46 | `research/bizhawk_gambatte_gbc.md:60-82` | `research:research/bizhawk_gambatte_gbc.md` | YES | `0x2000` | YES | - | ### 1a. CartRAM layout — flat, not the current 8 KB bank w |
| 47 | `docs/gen1_requirements.md:20` | `worktree:docs/gen1_requirements.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| Clean ROM SHA-1 \| Red `ea9bcae617fdf159b045185467ae58b |
| 48 | `research/rom_hashes.md:52-98` | `research:research/rom_hashes.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | ### Pokémon Gold (US) — `pokegold.gbc` / - SHA-1: `d8b8a36 |
| 49 | `research/rom_hashes.md:108-129` | `research:research/rom_hashes.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | ## `data/pret_syms.json` — no `rom_sha1` field /  / The br |
| 50 | `research/bizhawk_gambatte_gbc.md:91-136` | `research:research/bizhawk_gambatte_gbc.md` | YES | `"WRAM"` | YES | - | ## 2. `event.on_bus_exec` / `on_bus_read` / `on_bus_write` |
| 51 | `research/bizhawk_gambatte_gbc.md:138-157` | `research:research/bizhawk_gambatte_gbc.md` | YES | `"WRAM"` | NO | 39 | ## 3. Frame alignment inside `on_bus_exec` /  / `docs/gen1 |
| 52 | `lua/gen1/entry.lua:89-228` | `worktree:lua/gen1/entry.lua` | YES | `"anchors"` | YES | - | -- ── admission ────────────────────────────────────────── |
| 53 | `docs/gen1_requirements.md:96` | `worktree:docs/gen1_requirements.md` | YES | `rom_content_fingerprint` | YES | - | \| C-5 \| Randomized cartridge admission: hello carries `r |
| 54 | `lua/games/gen2_crystal.lua:540-556` | `worktree:lua/games/gen2_crystal.lua` | YES | `POKEMON_SLV` | YES | - | function M.detect() / -- Crystal is GBC-only; Gold/Silver  |
| 55 | `server/adapters/base.py:403-415` | `worktree:server/adapters/base.py` | YES | `None` | YES | - | def rom_content_fingerprint(self, payload: dict) -> str \| |
| 56 | `docs/protocol.md:101` | `worktree:docs/protocol.md` | YES | `None` | NO | 33 | \| 0 \| Any non-`hello` event from a player with a standin |
| 57 | `research/rom_hashes.md:52-98` | `research:research/rom_hashes.md` | YES | `None` | NO | - | ### Pokémon Gold (US) — `pokegold.gbc` / - SHA-1: `d8b8a36 |
| 58 | `lua/gen1/client.lua:1513-1535` | `worktree:lua/gen1/client.lua` | YES | `rom_content` | YES | - | local rom_content / if self.rom and self.rom.rom_content t |
| 59 | `gen2_crystal_client.lua:539-568` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `rom_content` | NO | - | local evt = { / event = "hello", / game_id = G.game_id, /  |
| 60 | `lua/memory_gb.lua:765` | `worktree:lua/memory_gb.lua` | YES | `rom_content` | NO | - | function M.readPlayerId() |
| 61 | `server/adapters/gen2_crystal.py:286-294` | `worktree:server/adapters/gen2_crystal.py` | YES | `rom_content` | NO | - | def parse_ot_id(self, key: str) -> str: / """Extract OT ID |
| 62 | `docs/protocol.md:106` | `worktree:docs/protocol.md` | YES | `rom_content` | NO | 91 | \| 3 \| First hello with an OT locks `player_identity[pid] |
| 63 | `tests/unit/test_gen2_adapter.py:114-127` | `worktree:tests/unit/test_gen2_adapter.py` | YES | `parse_ot_id` | YES | - | def test_parse_ot_id_normal(adapter): / assert adapter.par |
| 64 | `lua/gen1/writes.lua:1-8` | `worktree:lua/gen1/writes.lua` | YES | `OverworldLoop` | NO | - | -- lua/gen1/writes.lua — every byte the Gen 1 client write |
| 65 | `lua/memory_gb.lua:634-639` | `worktree:lua/memory_gb.lua` | YES | `0` | YES | - | function M.isInOverworld() / if M.isInBattle() then return |
| 66 | `lua/games/gen2_crystal.lua:83-93` | `worktree:lua/games/gen2_crystal.lua` | YES | `0` | NO | 24 | -- isInOverworld() reads; Gen 1's equivalent really is wJo |
| 67 | `gen2_crystal_client.lua:1258` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `wTextboxFlags` | NO | - | if writes_enabled and box_safe and M.isInOverworld() and # |
| 68 | `lua/gen1/signals.lua:141-143` | `worktree:lua/gen1/signals.lua` | YES | `wild_begin` | YES | - | S.KINDS.battle_begin = { point = opponent_point } / S.KIND |
| 69 | `docs/gen1_engine_sites.md:198` | `worktree:docs/gen1_engine_sites.md` | YES | `wild_begin` | NO | - | ## 3. Site table |
| 70 | `gen2_crystal_client.lua:1162-1178` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `wBattleMode` | NO | 390 | if raw_in_battle then / battle_on_count = battle_on_count  |
| 71 | `lua/memory_gb.lua:608-619` | `worktree:lua/memory_gb.lua` | YES | `wBattleMode` | NO | - | function M.isInBattle() / -- Per pret/pokered & pret/pokec |
| 72 | `docs/protocol.md:166` | `worktree:docs/protocol.md` | YES | `level` | NO | 57 | ### 3.2 Event table |
| 73 | `lua/gen1/signals.lua:141` | `worktree:lua/gen1/signals.lua` | YES | `replace_rival_team` | NO | - | S.KINDS.battle_begin = { point = opponent_point } |
| 74 | `docs/protocol.md:166` | `worktree:docs/protocol.md` | YES | `replace_rival_team` | NO | 183 | ### 3.2 Event table |
| 75 | `gen2_crystal_client.lua:40-43` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `replace_rival_team` | YES | - | NOT YET IMPLEMENTED (Gen 1 has them): trainer_battle_start |
| 76 | `docs/gen1_engine_sites.md:198` | `worktree:docs/gen1_engine_sites.md` | YES | `wBattleResult` | NO | 146 | ## 3. Site table |
| 77 | `lua/gen1/signals.lua:143` | `worktree:lua/gen1/signals.lua` | YES | `wBattleResult` | NO | 146 | S.KINDS.battle_end = { |
| 78 | `gen2_crystal_client.lua:1189-1194` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `pending_safe` | YES | - | elseif in_battle and battle_off_count >= BATTLE_DEBOUNCE_F |
| 79 | `docs/gen2/REVIEW_RECORD.md:42` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `wBattleResult` | NO | 55 |  |
| 80 | `lua/gen1/signals.lua:175-180` | `worktree:lua/gen1/signals.lua` | YES | `_AddPartyMon` | NO | - | S.KINDS.add_party_mon = { point = acquisition_point } / S. |
| 81 | `docs/gen1_requirements.md:67` | `worktree:docs/gen1_requirements.md` | YES | `_AddPartyMon` | YES | - | \| S-2 \| Route 1 wild encounter: `battle_start(wild, spec |
| 82 | `gen2_crystal_client.lua:829-835` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `in_battle` | YES | - | -- ── New mon detection (captures) / for slot, mon in pair |
| 83 | `docs/gen1_requirements.md:67` | `worktree:docs/gen1_requirements.md` | YES | `is_egg` | NO | - | \| S-2 \| Route 1 wild encounter: `battle_start(wild, spec |
| 84 | `docs/gen1_engine_sites.md:198` | `worktree:docs/gen1_engine_sites.md` | YES | `SendNewMonToBox` | NO | 215 | ## 3. Site table |
| 85 | `lua/gen1/signals.lua:176` | `worktree:lua/gen1/signals.lua` | YES | `SendNewMonToBox` | NO | - | S.KINDS.capture_box = { point = acquisition_point } |
| 86 | `docs/gen1_requirements.md:167` | `worktree:docs/gen1_requirements.md` | YES | `SendNewMonToBox` | NO | 68 | S-3 (party full → box), S-5/D-10 (Moon Stone / NPC-trade k |
| 87 | `gen2_crystal_client.lua:680-697` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `all_known_keys` | YES | - | local function scan_current_box() / -- Scan the current ac |
| 88 | `docs/protocol.md:166` | `worktree:docs/protocol.md` | YES | `in_box` | NO | 176 | ### 3.2 Event table |
| 89 | `lua/gen1/signals.lua:57` | `worktree:lua/gen1/signals.lua` | YES | `AddItemToInventory_` | NO | 37 | S.KINDS.bag_received = { |
| 90 | `docs/gen1_requirements.md:67` | `worktree:docs/gen1_requirements.md` | YES | `AddItemToInventory_` | NO | - | \| S-2 \| Route 1 wild encounter: `battle_start(wild, spec |
| 91 | `gen2_crystal_client.lua:1227-1232` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `countPokeballs()` | NO | 545 | if not nuzlocke_active and M.hasPokeballs() then / nuzlock |
| 92 | `lua/memory_gb.lua:572-601` | `worktree:lua/memory_gb.lua` | YES | `countPokeballs()` | YES | - | function M.hasPokeballs() / local count = M.read_u8(M.BAG_ |
| 93 | `lua/games/gen2_crystal.lua:28-53` | `worktree:lua/games/gen2_crystal.lua` | YES | `LIGHT_BALL` | YES | - | -- DERIVED, not transcribed: these are exactly the items p |
| 94 | `lua/gen1/writes.lua:36-49` | `worktree:lua/gen1/writes.lua` | YES | `active_faint_guard` | YES | - | -- Guard for W-2 (pure; caller passes the reads). Returns  |
| 95 | `lua/gen1/signals.lua:110-112` | `worktree:lua/gen1/signals.lua` | YES | `active_faint_guard` | NO | - | -- MainInBattleLoop+0: the only instant the engine judges  |
| 96 | `lua/gen1/client.lua:754-756` | `worktree:lua/gen1/client.lua` | YES | `active_faint_guard` | NO | 1386 | -- has no force_faint NACK. / log("[SLink-gen1] " .. cmd.c |
| 97 | `lua/memory_gb.lua:833-837` | `worktree:lua/memory_gb.lua` | YES | `active_faint_guard` | NO | - | function M.forceFaint(slot) / local base = M.PARTY_BASE_AD |
| 98 | `gen2_crystal_client.lua:256-267` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `active_faint_guard` | NO | - | if c.cmd == "force_faint" and c.key then / if writes_enabl |
| 99 | `lua/memory_gb.lua:812-832` | `worktree:lua/memory_gb.lua` | YES | `active_faint_guard` | NO | - | --- Kill a party mon. Writes the party struct AND, when th |
| 100 | `research/pret_gen2_symbols.md:94` | `research:research/pret_gen2_symbols.md` | YES | `HandlePlayerMonFaint` | YES | - | Wild-battle entry / result-write routines: `WinTrainerBatt |
| 101 | `docs/gen1_requirements.md:79` | `worktree:docs/gen1_requirements.md` | YES | `force_faint` | YES | - | \| W-1 \| `force_faint` on a benched mon (overworld): part |
| 102 | `lua/memory_gb.lua:833-837` | `worktree:lua/memory_gb.lua` | YES | `force_faint` | NO | - | function M.forceFaint(slot) / local base = M.PARTY_BASE_AD |
| 103 | `research/pret_gen2_symbols.md:38` | `research:research/pret_gen2_symbols.md` | YES | `force_faint` | NO | - | \| `MON_STATUS` \| pokecrystal@7a7881d constants/pokemon_d |
| 104 | `lua/gen1/signals.lua:96-100` | `worktree:lua/gen1/signals.lua` | YES | `wWhichPokemon` | YES | - | S.KINDS.poison_faint = { point = function(io, ram) / local |
| 105 | `gen2_crystal_client.lua:842-874` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `nuzlocke_active` | YES | - | -- ── Faint detection: HP drops from > 0 to 0 / if nuzlock |
| 106 | `engine/events/poisonstep.asm:1` | `pokecrystal:engine/events/poisonstep.asm` | YES | `nuzlocke_active` | NO | - | DoPoisonStep:: |
| 107 | `engine/overworld/events.asm:912` | `pokecrystal:engine/overworld/events.asm` | YES | `nuzlocke_active` | NO | - | farcall DoPoisonStep |
| 108 | `research/pret_gen2_symbols.md:105` | `research:research/pret_gen2_symbols.md` | YES | `nuzlocke_active` | NO | - | - Poison overworld step: `DoPoisonStep::` at pokecrystal@7 |
| 109 | `lua/gen1/signals.lua:108` | `worktree:lua/gen1/signals.lua` | YES | `rebuild_done` | NO | - | S.KINDS.blackout = { point = battle_point } |
| 110 | `lua/gen1/client.lua:605-618` | `worktree:lua/gen1/client.lua` | YES | `rebuild_done` | NO | 565 | end /  / function self:replace_rival_team(cmd) / local bat |
| 111 | `docs/protocol.md:209-220` | `worktree:docs/protocol.md` | YES | `rebuild_done` | YES | - | ### 3.4 `whiteout` → rebuild sequence /  / The client can  |
| 112 | `gen2_crystal_client.lua:785-798` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `whiteout_sent` | YES | - | local function check_whiteout(cur_party, count) / if not n |
| 113 | `docs/gen2/REVIEW_RECORD.md:42` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `WarpToSpawnPoint` | NO | 55 |  |
| 114 | `lua/gen1/signals.lua:230` | `worktree:lua/gen1/signals.lua` | YES | `key_change` | NO | - | -- Evolution_PartyMonLoop, AFTER `ld a,[wLoadedMonSpecies] |
| 115 | `docs/gen1_requirements.md:38` | `worktree:docs/gen1_requirements.md` | YES | `key_change` | YES | - | Audit 2026-09-14 (HEAD 48f09ef): 3 cells corrected — S-4 M |
| 116 | `docs/gen1_requirements.md:38` | `worktree:docs/gen1_requirements.md` | YES | `key_change` | YES | - | Audit 2026-09-14 (HEAD 48f09ef): 3 cells corrected — S-4 M |
| 117 | `gen2_crystal_client.lua:816-827` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `·` | NO | - | -- ── Evolution detection: same slot, different key, same  |
| 118 | `docs/gen1_requirements.md:38` | `worktree:docs/gen1_requirements.md` | YES | `·` | YES | - | Audit 2026-09-14 (HEAD 48f09ef): 3 cells corrected — S-4 M |
| 119 | `docs/protocol.md:166` | `worktree:docs/protocol.md` | YES | `nature_change` | NO | 182 | ### 3.2 Event table |
| 120 | `docs/gen1_requirements.md:70` | `worktree:docs/gen1_requirements.md` | YES | `RemovePokemon` | NO | 38 | \| S-5 \| Moon Stone evolution → `key_change{old,new}`; va |
| 121 | `engine/events/npc_trade.asm:1` | `pokecrystal:engine/events/npc_trade.asm` | YES | `RemovePokemon` | NO | - | NPCTrade:: |
| 122 | `research/pret_gen2_symbols.md:109` | `research:research/pret_gen2_symbols.md` | YES | `RemovePokemon` | NO | - | - In-game (NPC) trade: `NPCTrade::` at pokecrystal@7a7881d |
| 123 | `lua/gen1/signals.lua:189-219` | `worktree:lua/gen1/signals.lua` | YES | `wRemoveMonFromBox` | YES | - | -- nothing here may read both from one hook. / local funct |
| 124 | `docs/protocol.md:203-208` | `worktree:docs/protocol.md` | YES | `wRemoveMonFromBox` | NO | - | ### 3.3 Gen 1 boxed RELEASE: recorded protocol gap /  / A  |
| 125 | `gen2_crystal_client.lua:876-961` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `wRemoveMonFromBox` | NO | - | -- ── party_to_box: key disappeared from party outside bat |
| 126 | `lua/memory_gb.lua:642-645` | `worktree:lua/memory_gb.lua` | YES | `getCurrentBoxNum` | YES | - | function M.getCurrentBoxNum() / if not M.CURRENT_BOX_NUM_A |
| 127 | `docs/protocol.md:166` | `worktree:docs/protocol.md` | YES | `box_mon_failed` | NO | 150 | ### 3.2 Event table |
| 128 | `lua/gen1/boxes.lua:213` | `worktree:lua/gen1/boxes.lua` | YES | `memorialize_failed` | NO | - | if not current.initialized then return nil, "saved boxes n |
| 129 | `lua/gen1/boxes.lua:468-511` | `worktree:lua/gen1/boxes.lua` | YES | `memorialize_failed` | NO | - | function self.memorialize(key, colon_key, slot_hint) / --  |
| 130 | `lua/gen1/boxes.lua:168-199` | `worktree:lua/gen1/boxes.lua` | YES | `memorialize_failed` | NO | - | raw[info.individual + slot] = checksum(raw, slot * d.sram_ |
| 131 | `lua/memory_gb.lua:1407-1497` | `worktree:lua/memory_gb.lua` | YES | `depositMemorialMon` | YES | - | function M.depositMemorialMon(slot) / local mem_off = M.pr |
| 132 | `research/pret_gen2_symbols.md:76` | `research:research/pret_gen2_symbols.md` | YES | `SaveChecksum` | YES | - | **Box checksum: none.** `SaveChecksum` covers only `sGameD |
| 133 | `gen2_crystal_client.lua:1251-1256` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `SaveChecksum` | NO | - | -- Defer every box operation while the MEMORIAL box is the |
| 134 | `docs/gen2/REVIEW_RECORD.md:41` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `0` | NO | 32 | ### cx-3569f8d9 — FACT_CHECK gen2-C1 (round 1, 2026-09-21) |
| 135 | `research/pret_gen2_symbols.md:36-41` | `research:research/pret_gen2_symbols.md` | YES | `SaveBox` | NO | 175 | \| `MON_LEVEL` \| pokecrystal@7a7881d constants/pokemon_da |
| 136 | `docs/gen1_requirements.md:79` | `worktree:docs/gen1_requirements.md` | YES | `SaveBox` | NO | - | \| W-1 \| `force_faint` on a benched mon (overworld): part |
| 137 | `docs/gen1_requirements.md:67` | `worktree:docs/gen1_requirements.md` | YES | `level` | YES | - | \| S-2 \| Route 1 wild encounter: `battle_start(wild, spec |
| 138 | `docs/gen1_engine_sites.md:198` | `worktree:docs/gen1_engine_sites.md` | YES | `level` | NO | 204 | ## 3. Site table |
| 139 | `gen2_crystal_client.lua:964-972` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `level` | NO | 170 | if post_battle_frames == 1 and not captured_this_battle an |
| 140 | `docs/protocol.md:166` | `worktree:docs/protocol.md` | YES | `level` | NO | 57 | ### 3.2 Event table |
| 141 | `tests/e2e/test_duo_gen2.py:24-29` | `worktree:tests/e2e/test_duo_gen2.py` | YES | `species_id` | NO | - | NOT RUN HERE, and stated rather than silently absent: play |
| 142 | `docs/gen1_requirements.md:124-128` | `worktree:docs/gen1_requirements.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| T-1 \| Receptionist menu at all 12 Centers + Indigo; CA |
| 143 | `docs/gen2/REVIEW_RECORD.md:18` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| O-4 \| "All native feature should exist in first RC" \| |
| 144 | `research/pret_gen2_symbols.md:110` | `research:research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - Link trade: `engine/link/link_trade.asm` (pokecrystal@7a |
| 145 | `docs/gen1_requirements.md:124` | `worktree:docs/gen1_requirements.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| T-1 \| Receptionist menu at all 12 Centers + Indigo; CA |
| 146 | `lua/games/gen2_crystal.lua:210-239` | `worktree:lua/games/gen2_crystal.lua` | YES | `sfx_ids` | YES | - | -- Phase 7: Sound-effect dispatch. wMusicID at 0xC2BD per  |
| 147 | `lua/memory_gb.lua:1335-1366` | `worktree:lua/memory_gb.lua` | YES | `sfx_ids` | YES | - | function M.playSfx(event_name) / if not M.SFX_DISPATCH_ADD |
| 148 | `docs/gen1_requirements.md:60` | `worktree:docs/gen1_requirements.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| R-4 \| Title screen never validates (`wPlayerID==0 && p |
| 149 | `docs/gen1_requirements.md:84` | `worktree:docs/gen1_requirements.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| W-6 \| Writes gate pauses after 5 consecutive validatio |
| 150 | `docs/gen1_requirements.md:92-93` | `worktree:docs/gen1_requirements.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| C-1 \| Hello identity: `ot_id` = `wPlayerID`; a save wi |
| 151 | `gen2_crystal_client.lua:1084-1104` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `nuzlocke_active` | YES | - | if frame_count % 60 == 0 then / local ok, reason = M.valid |
| 152 | `lua/memory_gb.lua:841-873` | `worktree:lua/memory_gb.lua` | YES | `nuzlocke_active` | NO | - | function M.validateROM() / local partyCount = M.getPartyCo |
| 153 | `lua/hud.lua:69` | `worktree:lua/hud.lua` | YES | `GLYPH_MAP` | NO | 36 | local function sanitize(s) |
| 154 | `lua/hud.lua:86` | `worktree:lua/hud.lua` | YES | `GLYPH_MAP` | NO | 36 | H.sanitize = sanitize |
| 155 | `lua/hud.lua:259-260` | `worktree:lua/hud.lua` | YES | `GLYPH_MAP` | NO | 36 | function H.show(text, r, g, b, duration_frames) / text = s |
| 156 | `lua/hud.lua:285-286` | `worktree:lua/hud.lua` | YES | `GLYPH_MAP` | NO | 36 | function H.prompt(text, r, g, b, duration_frames) / text = |
| 157 | `lua/hud.lua:333` | `worktree:lua/hud.lua` | YES | `GLYPH_MAP` | NO | 36 | rebuild_text = sanitize(text or "REBUILDING TEAM") |
| 158 | `lua/hud.lua:359` | `worktree:lua/hud.lua` | YES | `GLYPH_MAP` | NO | 36 | nuzlocke_start_text   = sanitize(text or "Nuzlocke Start!" |
| 159 | `gen2_crystal_client.lua:216-220` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `GLYPH_MAP` | NO | - | HUD.init({screen_w = 160, screen_h = 144, hud_x = 2, hud_y |
| 160 | `docs/gen1_requirements.md:51` | `worktree:docs/gen1_requirements.md` | YES | `2` | YES | - | \| F-6 \| Fixtures re-qualified: each `tests/fixtures/gen1 |
| 161 | `lua/tests/gen2_playthrough.lua:283-298` | `worktree:lua/tests/gen2_playthrough.lua` | YES | `town` | NO | 29 | -- Write a level-5 Totodile into slot 0 rather than drivin |
| 162 | `docs/gen1_gen2_runtime_checks.md:205-210` | `worktree:docs/gen1_gen2_runtime_checks.md` | YES | `town` | NO | 33 | - **A Gen 2 playthrough — deliberately not bought.** Gen 2 |
| 163 | `docs/gen2/REVIEW_RECORD.md:37` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `SCENE_NEWBARKTOWN_NOOP` | NO | - | only" (ticket 09). Owner also supplied the AP pin link (ge |
| 164 | `research/pret_gen2_symbols.md:180-187` | `research:research/pret_gen2_symbols.md` | YES | `SCENE_NEWBARKTOWN_NOOP` | YES | - | The west-exit-blocking teacher NPC is driven by `SCENE_NEW |
| 165 | `docs/gen1_gen2_runtime_checks.md:26-40` | `worktree:docs/gen1_gen2_runtime_checks.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | missing ROM, jar or emulator fails the gate rather than sh |
| 166 | `tests/live/test_gen2_gates.py:43-48` | `worktree:tests/live/test_gen2_gates.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | GATES = { / "lua/tests/test_gen2_memory_gate.lua": "town", |
| 167 | `docs/gen1_requirements.md:38` | `worktree:docs/gen1_requirements.md` | YES | `gen1_new` | YES | - | Audit 2026-09-14 (HEAD 48f09ef): 3 cells corrected — S-4 M |
| 168 | `docs/gen1_requirements.md:58` | `worktree:docs/gen1_requirements.md` | YES | `gen1_new` | NO | 38 | \| R-2 \| Stats pass the known-positive control (recompute |
| 169 | `tests/e2e/test_duo_gen2.py:5-29` | `worktree:tests/e2e/test_duo_gen2.py` | YES | `saveram_dir` | YES | - | THE SAME CARTRIDGE ON BOTH SIDES, which Gen 1 could not do |
| 170 | `tests/e2e/test_duo_gen2.py:50` | `worktree:tests/e2e/test_duo_gen2.py` | YES | `saveram_dir` | NO | 9 | SCENARIOS = ("faint", "boxsync", "memorialize") |
| 171 | `research/bizhawk_gambatte_gbc.md:197-229` | `research:research/bizhawk_gambatte_gbc.md` | YES | `returncode` | NO | - | ## 5. SaveRAM file naming — gamedb hash, not launch path / |
| 172 | `docs/gen1_requirements.md:5-7` | `worktree:docs/gen1_requirements.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | (real cartridge in BizHawk, judged by an oracle that is no |
| 173 | `docs/gen2/REVIEW_RECORD.md:20` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| O-6 \| "Gen2 new ledger" \| `docs/gen2/gen2_requirement |
| 174 | `docs/gen1_requirements.md:46` | `worktree:docs/gen1_requirements.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| F-1 \| Every address in the generated profile names a p |
| 175 | `docs/gen1_requirements.md:155` | `worktree:docs/gen1_requirements.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | Durable runtime / paired checkpoints / recover; whiteout-r |
| 176 | `lua/games/gen2_crystal.lua:252-469` | `worktree:lua/games/gen2_crystal.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | gold = { / -- Party (pret/pokegold wPartyCount / wPartyMon |
| 177 | `docs/gen1_gen2_runtime_checks.md:174-177` | `worktree:docs/gen1_gen2_runtime_checks.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | **Crystal only, and stated rather than silently skipped.** |
| 178 | `data/wild/johto_grass.asm:341-364` | `pokecrystal:data/wild/johto_grass.asm` | YES | `true` | NO | - | def_grass_wildmons NATIONAL_PARK / db 10 percent, 10 perce |
| 179 | `docs/gen2/REVIEW_RECORD.md:40` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `true` | NO | - |  |
| 180 | `docs/gen1_requirements.md:30` | `worktree:docs/gen1_requirements.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - **GAME** — the game itself: `TryLoadSaveFile` returns 2  |
| 181 | `docs/gen1_requirements.md:57-58` | `worktree:docs/gen1_requirements.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| R-1 \| Party/box/name decode == PYDEC on raw dumps from |
| 182 | `docs/gen1_requirements.md:159` | `worktree:docs/gen1_requirements.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | `data/games/gen1_rby/{engine_signals,continue_sites,write_ |
| 183 | `gen2_crystal_client.lua:108-140` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `json_encode` | YES | - | local _json_esc = {['\\']='\\\\', ['"']='\\"', ['\n']='\\n |
| 184 | `docs/gen1_gen2_runtime_checks.md:6-11` | `worktree:docs/gen1_gen2_runtime_checks.md` | YES | `io` | YES | - | (commit `ca17a26`): `lua/slink_gen1.lua` `dofile`s `lua/ge |
| 185 | `research/bizhawk_gambatte_gbc.md:231-253` | `research:research/bizhawk_gambatte_gbc.md` | YES | `io` | YES | - | ## 6. What Gen 1's client already does (for Gen 2 to match |
| 186 | `gen2_crystal_client.lua:79-101` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `io` | NO | - | local _src = debug.getinfo(1, "S").source:match([=[@(.+[/\ |
| 187 | `docs/gen1_requirements.md:81` | `worktree:docs/gen1_requirements.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| W-3 \| `force_explode`: all four move/PP slots, battle  |
| 188 | `gen2_crystal_client.lua:40-43` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | NOT YET IMPLEMENTED (Gen 1 has them): trainer_battle_start |
| 189 | `lua/memory_gb.lua:647-670` | `worktree:lua/memory_gb.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- ═══ Rival Team Swap ═══ / -- wCurOpponent = trainer cla |
| 190 | `gen2_crystal_client.lua:33-38` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | │  stats_cache    — the party-only tail, sent on deposit.  |
| 191 | `gen2_crystal_client.lua:310-318` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- Carry c.stats through. The Gen 2 box struct is 32 bytes |
| 192 | `gen2_crystal_client.lua:1282-1296` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- Read the party-only tail BEFORE depositing. Gen 2's 32- |
| 193 | `lua/games/gen2_crystal.lua:144-148` | `worktree:lua/games/gen2_crystal.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- party_struct tail (pret macros/ram.asm): Atk +0x26, Def |
| 194 | `lua/tests/gen2_playthrough.lua:290-294` | `worktree:lua/tests/gen2_playthrough.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | --   +20 status  +21 unused  +22 HP(BE)  +24 maxHP  +26 At |
| 195 | `lua/games/gen2_crystal.lua:83-93` | `worktree:lua/games/gen2_crystal.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- isInOverworld() reads; Gen 1's equivalent really is wJo |
| 196 | `lua/games/gen2_crystal.lua:28-53` | `worktree:lua/games/gen2_crystal.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- DERIVED, not transcribed: these are exactly the items p |
| 197 | `lua/games/gen2_crystal.lua:210-239` | `worktree:lua/games/gen2_crystal.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- Phase 7: Sound-effect dispatch. wMusicID at 0xC2BD per  |
| 198 | `gen2_crystal_client.lua:1349-1408` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | if ok then / console.log("[SLink-Crystal]   ↳ party_mon OK |
| 199 | `tests/e2e/test_duo_gen2.py:5-10` | `worktree:tests/e2e/test_duo_gen2.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | THE SAME CARTRIDGE ON BOTH SIDES, which Gen 1 could not do |
| 200 | `research/bizhawk_gambatte_gbc.md:197-229` | `research:research/bizhawk_gambatte_gbc.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | ## 5. SaveRAM file naming — gamedb hash, not launch path / |
| 201 | `lua/games/gen2_crystal.lua:472-514` | `worktree:lua/games/gen2_crystal.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- ═══ Archipelago variant ═══════════════════════════════ |
| 202 | `lua/gen1/entry.lua:187-191` | `worktree:lua/gen1/entry.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | if not slice_ok(site.rom_offset, site.expected_hex) then r |
| 203 | `item_effects.asm:548-550` | `pokecrystal:engine/items/item_effects.asm` | YES | `PokeBallEffect` | NO | 17 (decl 212) | ld a, [wPartyCount] / cp PARTY_LENGTH / jr z, .SendToPC |
| 204 | `item_effects.asm:556` | `pokecrystal:engine/items/item_effects.asm` | YES | `PokeBallEffect` | NO | 17 (decl 212) | predef TryAddMonToParty |
| 205 | `item_effects.asm:612` | `pokecrystal:engine/items/item_effects.asm` | YES | `PokeBallEffect` | NO | 17 (decl 212) | predef SendMonIntoBox |
| 206 | `move_mon.asm:3` | `pokecrystal:engine/pokemon/move_mon.asm` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | TryAddMonToParty: |
| 207 | `move_mon.asm:942` | `pokecrystal:engine/pokemon/move_mon.asm` | YES | `SendMonIntoBox` | YES | - | SendMonIntoBox: |
| 208 | `core.asm:2607` | `pokecrystal:engine/battle/core.asm` **AMBIG(3)** | **AMBIG** | `KEYWORD_UNKNOWN` | UNKNOWN | - | HandlePlayerMonFaint: |
| 209 | `core.asm:2915` | `pokecrystal:engine/battle/core.asm` **AMBIG(3)** | **AMBIG** | `LostBattle` | YES | - | LostBattle: |
| 210 | `poisonstep.asm:1` | `pokecrystal:engine/events/poisonstep.asm` | YES | `DoPoisonStep` | YES | - | DoPoisonStep:: |
| 211 | `npc_trade.asm:1` | `pokecrystal:engine/events/npc_trade.asm` | YES | `DoPoisonStep` | NO | - | NPCTrade:: |
| 212 | `move_mon.asm:1121` | `pokecrystal:engine/pokemon/move_mon.asm` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | GiveEgg:: |
| 213 | `research/pret_gen2_symbols.md:94-116` | `research:research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | Wild-battle entry / result-write routines: `WinTrainerBatt |
| 214 | `docs/gen2/REVIEW_RECORD.md:42` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - |  |
| 215 | `research/pret_gen2_symbols.md:110` | `research:research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - Link trade: `engine/link/link_trade.asm` (pokecrystal@7a |
| 216 | `research/rom_hashes.md:52-98` | `research:research/rom_hashes.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | ### Pokémon Gold (US) — `pokegold.gbc` / - SHA-1: `d8b8a36 |
| 217 | `research/rom_hashes.md:148-150` | `research:research/rom_hashes.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - Whether `pokecrystal.gbc` (V1.0) or `pokecrystal11.gbc`  |
| 218 | `docs/gen2/REVIEW_RECORD.md:42` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - |  |
| 219 | `docs/gen2/REVIEW_RECORD.md:40` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - |  |
| 220 | `research/rom_hashes.md:148-150` | `research:research/rom_hashes.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - Whether `pokecrystal.gbc` (V1.0) or `pokecrystal11.gbc`  |
| 221 | `research/pret_gen2_symbols.md:110` | `research:research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - Link trade: `engine/link/link_trade.asm` (pokecrystal@7a |
| 222 | `research/pret_gen2_symbols.md:262` | `research:research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | 4. Link-trade mon-exchange/write routine — not located; `e |
| 223 | `docs/gen1_requirements.md:21` | `worktree:docs/gen1_requirements.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| Emulator \| BizHawk 2.11.1 (Gambatte core); inside `eve |
| 224 | `research/bizhawk_gambatte_gbc.md:138-157` | `research:research/bizhawk_gambatte_gbc.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | ## 3. Frame alignment inside `on_bus_exec` /  / `docs/gen1 |
| 225 | `research/bizhawk_gambatte_gbc.md:262-265` | `research:research/bizhawk_gambatte_gbc.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - Whether GBC double-speed mode changes anything about `on |
| 226 | `research/bizhawk_gambatte_gbc.md:257-261` | `research:research/bizhawk_gambatte_gbc.md` | YES | `0x2000` | YES | - | - Whether the `CartRAM` domain for a live Gold/Silver/Crys |
| 227 | `research/pret_gen2_symbols.md:70` | `research:research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| `sBox14` \| 0xb9e0 \| 0xb9e0 \| pokecrystal@7a7881d ram |
| 228 | `research/pret_gen2_symbols.md:223` | `research:research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - Not derivable without a build: absolute SRAM bank *numbe |
| 229 | `docs/gen2/REVIEW_RECORD.md:39` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | ## Codex "Gen2 Base" |
| 230 | `research/bizhawk_gambatte_gbc.md:271-275` | `research:research/bizhawk_gambatte_gbc.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - Whether BizHawk's ROM loader classifies a Gold/Silver RO |
| 231 | `research/pret_gen2_symbols.md:147` | `research:research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | **Open question**: I did not find or read an `OverworldLoo |
| 232 | `research/pret_gen2_symbols.md:261` | `research:research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | 3. The "in the overworld, no script running" idiom (`Overw |
| 233 | `research/pret_gen2_symbols.md:10` | `research:research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - `data/pret_syms.json` — mtime 2026-09-21 14:26, keys pre |
| 234 | `research/pret_gen2_symbols.md:272` | `research:research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | 14. `data/pret_syms.json` build provenance — the file has  |
| 235 | `research/rom_hashes.md:108-129` | `research:research/rom_hashes.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | ## `data/pret_syms.json` — no `rom_sha1` field /  / The br |
| 236 | `research/pret_gen2_symbols.md:117` | `research:research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - A generic `GivePokemon` label (as distinct from `GiveEgg |
| 237 | `research/pret_gen2_symbols.md:264` | `research:research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | 6. A generic `GivePokemon` routine distinct from `GiveEgg` |
| 238 | `gen2_crystal_client.lua:909-912` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | if in_box then / send({event = "party_to_box", key = key}, |

## Table: GEN2_BINDING_PLAN

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
| 13 | `server/adapters/__init__.py:54-57` | `worktree:server/adapters/__init__.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | # Gen 2. `lua/games/gen2_crystal.lua:rom_type_for_variant` |
| 14 | `server/adapters/__init__.py:64-65` | `worktree:server/adapters/__init__.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | "Gold": "gen2_crystal", "gold": "gen2_crystal", / "Silver" |
| 15 | `lua/games/gen2_crystal.lua:13` | `worktree:lua/games/gen2_crystal.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | M.display_name = "Crystal / Gold / Silver" |
| 16 | `data/wild/johto_grass.asm:341-364` | `pokegold:data/wild/johto_grass.asm` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | def_grass_wildmons NATIONAL_PARK / db 10 percent, 10 perce |
| 17 | `docs/gen2/REVIEW_RECORD.md:40` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - |  |
| 18 | `server/adapters/__init__.py:59-62` | `worktree:server/adapters/__init__.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | # Gold, Silver and Crystal (AP) were MISSING here, and the |
| 19 | `lua/clients/gen2_crystal_client.lua:40` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | NOT YET IMPLEMENTED (Gen 1 has them): trainer_battle_start |
| 20 | `lua/gen1/entry.lua:302-308` | `worktree:lua/gen1/entry.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | local L = function(rel) return dofile(root .. "/" .. rel)  |
| 21 | `lua/gen1/run.lua:14-16` | `worktree:lua/gen1/run.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | local Entry = dofile(ROOT .. "/lua/gen1/entry.lua") / loca |
| 22 | `server/server.py:416-430` | `worktree:server/server.py` | YES | `_handle_trainer_battle_start` | NO | - | from server.adapters import game_id_for_rom_type, get_adap |
| 23 | `docs/protocol.md:432-452` | `worktree:docs/protocol.md` | YES | `game_id` | YES | - | \| `game_id` \| property → str \| abstract \| registry key |
| 24 | `server/adapters/gen1_rby.py:265` | `worktree:server/adapters/gen1_rby.py` | YES | `Gen1Adapter(GameAdapter)` | YES | - | class Gen1Adapter(GameAdapter): |
| 25 | `gen1_purergb.py:66` | `worktree:server/adapters/gen1_purergb.py` | YES | `Gen1PureRGBAdapter(Gen1Adapter)` | YES | - | class Gen1PureRGBAdapter(Gen1Adapter): |
| 26 | `server/adapters/base.py:559` | `worktree:server/adapters/base.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | def gb_status_token(status_cond: int) -> str: |
| 27 | `gen1_rby.py:356-358` | `worktree:server/adapters/gen1_rby.py` | YES | `gb_status_token` | YES | - | def status_token(self, status_cond: int) -> str: / # const |
| 28 | `gen1_rby.py:14` | `worktree:server/adapters/gen1_rby.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - |  |
| 29 | `constants/pokemon_constants.asm:171-174` | `pokecrystal:constants/pokemon_constants.asm` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | const MEWTWO     ; 96 / const MEW        ; 97 / DEF JOHTO_ |
| 30 | `constants/pokemon_constants.asm:273-274` | `pokecrystal:constants/pokemon_constants.asm` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | const CELEBI     ; fb / DEF NUM_POKEMON EQU const_value -  |
| 31 | `gen1_rby.py:472` | `worktree:server/adapters/gen1_rby.py` | YES | `rom_content_fingerprint` | YES | - | def rom_content_fingerprint(self, payload: dict) -> str \| |
| 32 | `lua/gen1/run.lua:15` | `worktree:lua/gen1/run.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | local C = require("connector") |
| 33 | `lua/gen1/entry.lua:371` | `worktree:lua/gen1/entry.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | net = deps.net, json = json, hud = deps.hud, io = bio, |
| 34 | `lua/gen1/entry.lua:303` | `worktree:lua/gen1/entry.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | local json = L("lua/json_codec.lua") |
| 35 | `lua/gen1/run.lua:31` | `worktree:lua/gen1/run.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | root = ROOT, json = dofile(ROOT .. "/lua/json_codec.lua"), |
| 36 | `lua/gen1/run.lua:16` | `worktree:lua/gen1/run.lua` | YES | `sanitize` | NO | - | local H = require("hud") |
| 37 | `lua/gen1/entry.lua:366` | `worktree:lua/gen1/entry.lua` | YES | `sanitize` | YES | - | panel = P.new(profile, panel_io, writes, deps.hud and deps |
| 38 | `lua/slink.lua:83-85` | `worktree:lua/slink.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- No gen1_rby row: the Gen 1 route above returns before t |
| 39 | `docs/FRAMEWORK.md:251-252` | `SWEEP:docs/FRAMEWORK.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| `lua/mailbox.lua` (536) \| header (:1-9): RR companion- |
| 40 | `docs/protocol.md:491-516` | `worktree:docs/protocol.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | ## 8. Gen 3-isms baked into shared code /  / Things a non- |
| 41 | `lua/gen1/entry.lua:44` | `worktree:lua/gen1/entry.lua` | YES | `Silver` | NO | - | Entry.PACKS = { |
| 42 | `lua/gen1/entry.lua:58` | `worktree:lua/gen1/entry.lua` | YES | `Silver` | NO | - | Entry.PACK_FILES = { |
| 43 | `lua/gen1/entry.lua:133` | `worktree:lua/gen1/entry.lua` | YES | `Silver` | NO | - | function Entry.admission_table(root, json) |
| 44 | `lua/gen1/entry.lua:197` | `worktree:lua/gen1/entry.lua` | YES | `Silver` | NO | - | function Entry.anchor_matches(args, header) |
| 45 | `lua/gen1/entry.lua:229` | `worktree:lua/gen1/entry.lua` | YES | `Silver` | NO | - | function Entry.admit(args) |
| 46 | `lua/gen1/entry.lua:300` | `worktree:lua/gen1/entry.lua` | YES | `Silver` | NO | - | function Entry.build(deps) |
| 47 | `lua/gen1/entry.lua:394` | `worktree:lua/gen1/entry.lua` | YES | `Silver` | NO | - | function Entry.detect_title(read_rom_u8) |
| 48 | `lua/gen1/entry.lua:403` | `worktree:lua/gen1/entry.lua` | YES | `Silver` | NO | - | function Entry.bizhawk_deps() |
| 49 | `lua/gen1/run.lua:1-16` | `worktree:lua/gen1/run.lua` | YES | `"GB"` | NO | - | -- lua/gen1/run.lua — BizHawk entry for the Gen 1 client.  |
| 50 | `lua/gen1/client.lua:135` | `worktree:lua/gen1/client.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | function Client.new(p) |
| 51 | `lua/gen1/reads.lua:1-4` | `worktree:lua/gen1/reads.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- Pure Gen 1 reads over a pret-generated title profile an |
| 52 | `lua/gen1/signals.lua:1-16` | `worktree:lua/gen1/signals.lua` | YES | `EraseBoxes` | NO | - | -- lua/gen1/signals.lua — Gen 1 game events detected from  |
| 53 | `lua/gen1/writes.lua:1-16` | `worktree:lua/gen1/writes.lua` | YES | `wPlayerSelectedMove` | YES | - | -- lua/gen1/writes.lua — every byte the Gen 1 client write |
| 54 | `lua/gen1/boxes.lua:1-11` | `worktree:lua/gen1/boxes.lua` | YES | `SaveBox` | NO | - | -- Gen 1 PC moves. All writes go through the caller's arme |
| 55 | `lua/gen1/rom.lua:1-11` | `worktree:lua/gen1/rom.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- lua/gen1/rom.lua — the two ROM tables the client needs, |
| 56 | `lua/gen1/panel.lua:16` | `worktree:lua/gen1/panel.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | local MAILBOX = 0xDEE2 |
| 57 | `lua/gen1/panel.lua:19` | `worktree:lua/gen1/panel.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | local SFX     = MAILBOX + 7                 -- SLINK_SFX_R |
| 58 | `lua/gen1/panel.lua:24-25` | `worktree:lua/gen1/panel.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | local OFF_ABI, OFF_SFX, OFF_CAPS, OFF_STATE, OFF_PAGE, OFF |
| 59 | `lua/gen1/panel.lua:45-48` | `worktree:lua/gen1/panel.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | P.MAILBOX, P.CAPS, P.STATE, P.PAGE, P.PAGES, P.SFX = MAILB |
| 60 | `lua/gen1/trade_overlay.lua:5-7` | `worktree:lua/gen1/trade_overlay.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | local MAGIC = {0x53, 0x4C, 0x54, 0x31} -- trade_service.as |
| 61 | `lua/gen1_write_safety.lua:14-15` | `worktree:lua/gen1_write_safety.lua` | YES | `-purergb-v1` | NO | - | M.VERSION = "gen1-main-loop-v1" / M.VERSION_PURERGB = "gen |
| 62 | `lua/gen1_write_safety.lua:1-15` | `worktree:lua/gen1_write_safety.lua` | YES | `-purergb-v1` | NO | - | -- A read-only Gen 1 main-thread checkpoint. This does not |
| 63 | `lua/gen1/panel.lua:19` | `worktree:lua/gen1/panel.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | local SFX     = MAILBOX + 7                 -- SLINK_SFX_R |
| 64 | `lua/gen1/panel.lua:25` | `worktree:lua/gen1/panel.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | local CAP_SFX   = 0x01                      -- SLINK_CAP_S |
| 65 | `lua/gen1/panel.lua:28-34` | `worktree:lua/gen1/panel.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- slink.asm SlinkSfxService: what the request byte may ca |
| 66 | `lua/gen1/panel.lua:144-161` | `worktree:lua/gen1/panel.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | local function post_sfx(code) / if u8(SFX) ~= 0 then retur |
| 67 | `server/adapters/base.py:204` | `worktree:server/adapters/base.py` | YES | `gym_badge_slugs` | NO | 538 | def rival_trainer_ids(self) -> set[int]: |
| 68 | `server/adapters/base.py:220` | `worktree:server/adapters/base.py` | YES | `gym_badge_slugs` | NO | 538 | def party_blob_size(self) -> int: |
| 69 | `server/adapters/base.py:282` | `worktree:server/adapters/base.py` | YES | `gym_badge_slugs` | NO | 538 | def supports_explode_mode(self) -> bool: |
| 70 | `server/adapters/base.py:308` | `worktree:server/adapters/base.py` | YES | `gym_badge_slugs` | NO | 538 | def native_trade_ui(self) -> bool: |
| 71 | `server/adapters/base.py:403` | `worktree:server/adapters/base.py` | YES | `gym_badge_slugs` | NO | 538 | def rom_content_fingerprint(self, payload: dict) -> str \| |
| 72 | `server/adapters/base.py:518` | `worktree:server/adapters/base.py` | YES | `gym_badge_slugs` | NO | 538 | def mons_per_box(self) -> int: |
| 73 | `server/adapters/base.py:529` | `worktree:server/adapters/base.py` | YES | `gym_badge_slugs` | NO | 538 | def memorial_box_index(self) -> int: |
| 74 | `server/adapters/gen1_rby.py:265` | `worktree:server/adapters/gen1_rby.py` | YES | `gym_badge_slugs` | NO | - | class Gen1Adapter(GameAdapter): |
| 75 | `server/adapters/gen1_codec.py:1-13` | `worktree:server/adapters/gen1_codec.py` | YES | `for_foundation` | NO | 782 | """Independent English R/B/Y byte oracle, derived from pre |
| 76 | `server/adapters/gen1_codec.py:457` | `worktree:server/adapters/gen1_codec.py` | YES | `for_foundation` | NO | 782 | def decode_party_mon(b: bytes, *, box: bool = False) -> di |
| 77 | `server/adapters/gen1_codec.py:483` | `worktree:server/adapters/gen1_codec.py` | YES | `for_foundation` | NO | 782 | def encode_party_mon(d: dict) -> bytes: |
| 78 | `server/adapters/gen1_codec.py:606` | `worktree:server/adapters/gen1_codec.py` | YES | `for_foundation` | NO | 782 | def decode_box(sram_box_bytes: bytes) -> list[dict]: |
| 79 | `server/adapters/gen1_codec.py:611` | `worktree:server/adapters/gen1_codec.py` | YES | `for_foundation` | NO | 782 | def key(mon: dict) -> str: |
| 80 | `server/adapters/gen1_codec.py:647` | `worktree:server/adapters/gen1_codec.py` | YES | `for_foundation` | NO | 782 | def sav_checksum(b: bytes) -> int: |
| 81 | `server/adapters/gen1_codec.py:669` | `worktree:server/adapters/gen1_codec.py` | YES | `for_foundation` | NO | 782 | def verify_boxes(sram: bytes) -> dict: |
| 82 | `server/adapters/gen1_codec.py:705` | `worktree:server/adapters/gen1_codec.py` | YES | `for_foundation` | NO | 782 | def calc_stat(base: int, dv: int, stat_exp: int, level: in |
| 83 | `server/adapters/gen1_codec.py:779` | `worktree:server/adapters/gen1_codec.py` | YES | `for_foundation` | NO | 782 | class Gen1Layout: |
| 84 | `server/adapters/gen1_codec.py:941` | `worktree:server/adapters/gen1_codec.py` | YES | `for_foundation` | YES | - | def for_foundation(foundation: str) -> Gen1Layout: |
| 85 | `server/adapters/gen1_purergb.py:66` | `worktree:server/adapters/gen1_purergb.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | class Gen1PureRGBAdapter(Gen1Adapter): |
| 86 | `docs/gen2/REVIEW_RECORD.md:40` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - |  |
| 87 | `lua/gen1/entry.lua:58-83` | `worktree:lua/gen1/entry.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | Entry.PACK_FILES = { / gen1_rby = { / profile = "data/game |
| 88 | `lua/gen1/entry.lua:55-57` | `worktree:lua/gen1/entry.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- Every pack file Entry.build/Entry.admit reads, as liter |
| 89 | `patch/gen1/README.md:20` | `worktree:patch/gen1/README.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | One manifest, `patch/gen1/tools/manifest.py` — 15 spans, R |
| 90 | `patch/gen1/README.md:47-56` | `worktree:patch/gen1/README.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | The request byte at mailbox `+7` carries a **semantic code |
| 91 | `patch/gen1/README.md:42` | `worktree:patch/gen1/README.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | So the patch buys **zero additional rules**. What it buys  |
| 92 | `constants/pokemon_data_constants.asm:101` | `pokecrystal:constants/pokemon_data_constants.asm` | YES | `BOXMON_STRUCT_LENGTH` | YES | - | DEF BOXMON_STRUCT_LENGTH EQU _RS |
| 93 | `constants/pokemon_data_constants.asm:113` | `pokecrystal:constants/pokemon_data_constants.asm` | YES | `BOXMON_STRUCT_LENGTH` | NO | 101 | DEF PARTYMON_STRUCT_LENGTH EQU _RS |
| 94 | `docs/gen2/research/pret_gen2_symbols.md:37` | `worktree:docs/gen2/research/pret_gen2_symbols.md` | YES | `BOXMON_STRUCT_LENGTH` | YES | - | \| `BOXMON_STRUCT_LENGTH` (= end of box-portion) \| pokecr |
| 95 | `docs/gen2/research/pret_gen2_symbols.md:43` | `worktree:docs/gen2/research/pret_gen2_symbols.md` | YES | `BOXMON_STRUCT_LENGTH` | NO | 25 | \| `PARTYMON_STRUCT_LENGTH` \| pokecrystal@7a7881d constan |
| 96 | `server/adapters/gen1_codec.py:35` | `worktree:server/adapters/gen1_codec.py` | YES | `BOXMON_STRUCT_LENGTH` | NO | - | PARTY_MON_SIZE, BOX_MON_SIZE = 44, 33  # constants/pokemon |
| 97 | `server/adapters/gen1_rby.py:335-337` | `worktree:server/adapters/gen1_rby.py` | YES | `party_blob_size` | YES | - | def party_blob_size(self) -> int: / # pokemon_data_constan |
| 98 | `constants/pokemon_data_constants.asm:78` | `pokecrystal:constants/pokemon_data_constants.asm` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | DEF MON_ITEM               rb |
| 99 | `docs/protocol.md:223` | `worktree:docs/protocol.md` | YES | `party` | YES | - | ### 4.1 Party entry (element of `party` in `hello`/`tick`/ |
| 100 | `constants/pokemon_data_constants.asm:106-112` | `pokecrystal:constants/pokemon_data_constants.asm` | YES | `rw` | YES | - | DEF MON_STATS              rw NUM_BATTLE_STATS / rsset MON |
| 101 | `server/adapters/gen1_codec.py:31` | `worktree:server/adapters/gen1_codec.py` | YES | `spc` | YES | - | _STAT_EXP = {"hp": 17, "atk": 19, "def": 21, "spd": 23, "s |
| 102 | `server/adapters/gen1_codec.py:33` | `worktree:server/adapters/gen1_codec.py` | YES | `spc` | YES | - | _STORED_STATS = {"max_hp": 34, "atk": 36, "def": 38, "spd" |
| 103 | `constants/pokemon_data_constants.asm:138` | `pokecrystal:constants/pokemon_data_constants.asm` | YES | `BOX_LENGTH` | NO | 141 | DEF MONS_PER_BOX EQU 20 |
| 104 | `constants/pokemon_data_constants.asm:141` | `pokecrystal:constants/pokemon_data_constants.asm` | YES | `BOX_LENGTH` | YES | - | DEF BOX_LENGTH EQU 1 + MONS_PER_BOX + 1 + (BOXMON_STRUCT_L |
| 105 | `constants/pokemon_data_constants.asm:142` | `pokecrystal:constants/pokemon_data_constants.asm` | YES | `BOX_LENGTH` | NO | 141 | DEF NUM_BOXES EQU 14 |
| 106 | `server/adapters/gen1_codec.py:36` | `worktree:server/adapters/gen1_codec.py` | YES | `BOX_LENGTH` | NO | - | PARTY_CAPACITY, BOX_CAPACITY, BOX_COUNT = 6, 20, 12 |
| 107 | `server/adapters/gen1_rby.py:490-492` | `worktree:server/adapters/gen1_rby.py` | YES | `memorial_box_index` | YES | - | @property / def memorial_box_index(self) -> int: / # const |
| 108 | `ram/sram.asm:177-197` | `pokecrystal:ram/sram.asm` | YES | `sBox14` | YES | - | DEF box_n = 0 / MACRO boxes / rept \1 / DEF box_n += 1 / s |
| 109 | `gen1_codec.py:70` | `worktree:server/adapters/gen1_codec.py` | YES | `sBox14` | NO | - | "box_banks": (0x4000, 0x6000), "all_boxes_checksums": (0x5 |
| 110 | `docs/gen2/REVIEW_RECORD.md:39` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `box_banks` | NO | - | ## Codex "Gen2 Base" |
| 111 | `docs/gen2/research/bizhawk_gambatte_gbc.md:73-82` | `worktree:docs/gen2/research/bizhawk_gambatte_gbc.md` | YES | `rambanks*0x2000` | NO | - | So: **`CartRAM` in BizHawk's memory-domain list is the FUL |
| 112 | `docs/gen2/research/bizhawk_gambatte_gbc.md:255-261` | `worktree:docs/gen2/research/bizhawk_gambatte_gbc.md` | YES | `rambanks*0x2000` | NO | - | ## Open questions /  / - Whether the `CartRAM` domain for  |
| 113 | `engine/menus/save.asm:266-281` | `pokecrystal:engine/menus/save.asm` | YES | `wCurBox` | NO | 53 | _SaveGameData: / ld a, TRUE / ld [wSaveFileExists], a / fa |
| 114 | `engine/menus/save.asm:521-524` | `pokecrystal:engine/menus/save.asm` | YES | `wCurBox` | NO | 53 | SaveBox: / call GetBoxAddress / call SaveBoxAddress / ret |
| 115 | `engine/menus/save.asm:874-973` | `pokecrystal:engine/menus/save.asm` | YES | `wCurBox` | YES | - | GetBoxAddress: / ld a, [wCurBox] / cp NUM_BOXES / jr c, .o |
| 116 | `docs/gen2/REVIEW_RECORD.md:38` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `wCurBox` | NO | 51 |  |
| 117 | `gen1_codec.py:70-71` | `worktree:server/adapters/gen1_codec.py` | YES | `wCurBox` | NO | - | "box_banks": (0x4000, 0x6000), "all_boxes_checksums": (0x5 |
| 118 | `engine/menus/save.asm:360-366` | `pokecrystal:engine/menus/save.asm` | YES | `wSavedAtLeastOnce` | NO | 374 | ErasePreviousSave: / call EraseBoxes / call EraseHallOfFam |
| 119 | `engine/menus/save.asm:181-199` | `pokecrystal:engine/menus/save.asm` | YES | `wSavedAtLeastOnce` | NO | 374 | AskOverwriteSaveFile: / ld a, [wSaveFileExists] / and a /  |
| 120 | `engine/menus/save.asm:470-475` | `pokecrystal:engine/menus/save.asm` | YES | `wSavedAtLeastOnce` | YES | - | HallOfFame_InitSaveIfNeeded: / ld a, [wSavedAtLeastOnce] / |
| 121 | `engine/menus/save.asm:1038-1077` | `pokecrystal:engine/menus/save.asm` | YES | `wSavedAtLeastOnce` | NO | 374 | EraseBoxes: / ld hl, BoxAddresses / ld c, NUM_BOXES / .nex |
| 122 | `docs/gen2/REVIEW_RECORD.md:41` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `wSavedAtLeastOnce` | NO | 54 | ### cx-3569f8d9 — FACT_CHECK gen2-C1 (round 1, 2026-09-21) |
| 123 | `Makefile:169` | `pokecrystal:Makefile` | YES | `C` | NO | 114 | RGBFIXFLAGS += -Cjv -t PM_CRYSTAL -k 01 -l 0x33 -m MBC3+TI |
| 124 | `docs/gen2/research/rom_hashes.md:82-86` | `worktree:docs/gen2/research/rom_hashes.md` | YES | `C` | YES | - | - Internal cartridge title (`rgbfix -t`): `PM_CRYSTAL` (`p |
| 125 | `docs/gen2/research/bizhawk_gambatte_gbc.md:159-180` | `worktree:docs/gen2/research/bizhawk_gambatte_gbc.md` | YES | `C` | NO | 6 | ## 4. DMG vs CGB mode selection (`ConsoleMode`) /  / Sync  |
| 126 | `lua/gen1/entry.lua:274-292` | `worktree:lua/gen1/entry.lua` | YES | `C` | NO | - | local function bank_safe_io(bio, d) / if not d.wram_bank_g |
| 127 | `docs/gen2/research/bizhawk_gambatte_gbc.md:123` | `worktree:docs/gen2/research/bizhawk_gambatte_gbc.md` | YES | `0xD000-0xDFFF` | NO | - | - `0xD000 <= addr < 0xE000` → WRAM bank X, bank-adjusted o |
| 128 | `engine/battle/core.asm:2977-2980` | `pokecrystal:engine/battle/core.asm` | YES | `BATTLERESULT_BOX_FULL` | NO | - | ld a, [wBattleResult] / and BATTLERESULT_BITMASK / add DRA |
| 129 | `engine/items/item_effects.asm:545` | `pokecrystal:engine/items/item_effects.asm` | YES | `BATTLERESULT_BOX_FULL` | NO | 623 | set BATTLERESULT_CAUGHT_CELEBI, [hl] |
| 130 | `engine/items/item_effects.asm:622-623` | `pokecrystal:engine/items/item_effects.asm` | YES | `BATTLERESULT_BOX_FULL` | YES | - | ld hl, wBattleResult / set BATTLERESULT_BOX_FULL, [hl] |
| 131 | `docs/gen2/REVIEW_RECORD.md:42` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `wBattleResult` | NO | 55 |  |
| 132 | `engine/events/whiteout.asm:14` | `pokecrystal:engine/events/whiteout.asm` | YES | `WarpToSpawnPoint` | NO | 20 | special HealParty |
| 133 | `engine/events/whiteout.asm:20` | `pokecrystal:engine/events/whiteout.asm` | YES | `WarpToSpawnPoint` | YES | - | special WarpToSpawnPoint |
| 134 | `docs/gen2/REVIEW_RECORD.md:42` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `WarpToSpawnPoint` | NO | 55 |  |
| 135 | `data/wild/johto_grass.asm:341-364` | `pokecrystal:data/wild/johto_grass.asm` | YES | `_SILVER` | NO | - | def_grass_wildmons NATIONAL_PARK / db 10 percent, 10 perce |
| 136 | `docs/gen2/REVIEW_RECORD.md:40` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `_SILVER` | NO | 53 |  |
| 137 | `docs/gen2/research/rom_hashes.md:77` | `worktree:docs/gen2/research/rom_hashes.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - SHA-1: `f4cd194bdee0d04ca4eac29e09b8e4e9d818c133` (`poke |
| 138 | `docs/gen2/research/rom_hashes.md:90` | `worktree:docs/gen2/research/rom_hashes.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - SHA-1: `f2f52230b536214ef7c9924f483392993e226cfb` (`poke |
| 139 | `lua/gen1/entry.lua:133-149` | `worktree:lua/gen1/entry.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | function Entry.admission_table(root, json) / local table_  |
| 140 | `rom_hashes.md:53` | `worktree:docs/gen2/research/rom_hashes.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - SHA-1: `d8b8a3600a465308c9953dfa04f0081c05bdcb94` (`poke |
| 141 | `rom_hashes.md:69` | `worktree:docs/gen2/research/rom_hashes.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - SHA-1: `49b163f7e57702bc939d642a18f591de55d92dae` (`poke |
| 142 | `Makefile:169` | `pokecrystal:Makefile` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | RGBFIXFLAGS += -Cjv -t PM_CRYSTAL -k 01 -l 0x33 -m MBC3+TI |
| 143 | `Makefile:190` | `pokegold:Makefile` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | RGBFIXFLAGS += -cjsv -k 01 -l 0x33 -m MBC3+TIMER+RAM+BATTE |
| 144 | `docs/gen2/research/rom_hashes.md:62-63` | `worktree:docs/gen2/research/rom_hashes.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | Cart-type/RAM/battery flags shared with Silver/Crystal: `- |
| 145 | `docs/gen2/research/rom_hashes.md:83` | `worktree:docs/gen2/research/rom_hashes.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | `RGBFIXFLAGS += -Cjv -t PM_CRYSTAL -k 01 -l 0x33 -m MBC3+T |
| 146 | `ram/sram.asm:6-56` | `pokecrystal:ram/sram.asm` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | SECTION "SRAM Bank 0", SRAM /  / sPartyMail:: / ; sPartyMo |
| 147 | `server/adapters/gen1_codec.py:73` | `worktree:server/adapters/gen1_codec.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | SRAM_SIZE = 0x8000  # layout.link:195-202: four SRAM banks |
| 148 | `docs/gen2/research/bizhawk_gambatte_gbc.md:197-230` | `worktree:docs/gen2/research/bizhawk_gambatte_gbc.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | ## 5. SaveRAM file naming — gamedb hash, not launch path / |
| 149 | `PathEntryCollectionExtensions.cs:233-244` | `pokecrystal:PathEntryCollectionExtensions.cs` | **NO** | `KEYWORD_UNKNOWN` | UNKNOWN | - |  |
| 150 | `Database.cs:270-307` | `pokecrystal:Database.cs` | **NO** | `KEYWORD_UNKNOWN` | UNKNOWN | - |  |
| 151 | `constants/pokemon_constants.asm:171-174` | `pokecrystal:constants/pokemon_constants.asm` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | const MEWTWO     ; 96 / const MEW        ; 97 / DEF JOHTO_ |
| 152 | `constants/pokemon_constants.asm:223` | `pokecrystal:constants/pokemon_constants.asm` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | const UNOWN      ; c9 |
| 153 | `constants/pokemon_constants.asm:273-274` | `pokecrystal:constants/pokemon_constants.asm` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | const CELEBI     ; fb / DEF NUM_POKEMON EQU const_value -  |
| 154 | `lua/gen1/rom.lua:3` | `worktree:lua/gen1/rom.lua` | YES | `PokedexOrder` | YES | - | --   dex order   PokedexOrder (data/pokemon/dex_order.asm) |
| 155 | `maps/NewBarkTown.asm:8` | `pokecrystal:maps/NewBarkTown.asm` | YES | `SCENE_NEWBARKTOWN_NOOP` | NO | 9 | scene_script NewBarkTownNoop1Scene, SCENE_NEWBARKTOWN_TEAC |
| 156 | `maps/NewBarkTown.asm:292-293` | `pokecrystal:maps/NewBarkTown.asm` | YES | `SCENE_NEWBARKTOWN_NOOP` | NO | 9 | coord_event  1,  8, SCENE_NEWBARKTOWN_TEACHER_STOPS_YOU, N |
| 157 | `maps/ElmsLab.asm:277` | `pokecrystal:maps/ElmsLab.asm` | YES | `SCENE_NEWBARKTOWN_NOOP` | YES | - | setmapscene NEW_BARK_TOWN, SCENE_NEWBARKTOWN_NOOP |
| 158 | `docs/gen2/research/pret_gen2_symbols.md:182-187` | `worktree:docs/gen2/research/pret_gen2_symbols.md` | YES | `SCENE_NEWBARKTOWN_NOOP` | YES | - | - `scene_script NewBarkTownNoop1Scene, SCENE_NEWBARKTOWN_T |
| 159 | `docs/gen2/REVIEW_RECORD.md:37` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `SCENE_NEWBARKTOWN_NOOP` | NO | - | only" (ticket 09). Owner also supplied the AP pin link (ge |
| 160 | `docs/gen2/REVIEW_RECORD.md:19` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| O-5 \| "Move to fresh upstream HEAD" \| Pins: pokecryst |
| 161 | `docs/gen2/research/pret_gen2_symbols.md:6` | `worktree:docs/gen2/research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - `E:/Google Drive/SLink/.cache/pret/pokecrystal` (old pin |
| 162 | `rom_hashes.md:123-125` | `worktree:docs/gen2/research/rom_hashes.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | `rom_sha1` key exists in the file ... `tools/build_pret_sy |
| 163 | `rom_hashes.md:110-119` | `worktree:docs/gen2/research/rom_hashes.md` | YES | `pokeyellow` | YES | - | The brief asked to check `data/pret_syms.json`'s `pokecrys |
| 164 | `data/games/gen1_rby/README.md:8-10` | `worktree:data/games/gen1_rby/README.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | is not. Every profile address is checked against the pret  |
| 165 | `lua/gen1/entry.lua:58-83` | `worktree:lua/gen1/entry.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | Entry.PACK_FILES = { / gen1_rby = { / profile = "data/game |
| 166 | `docs/gen2/REVIEW_RECORD.md:38` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - |  |
| 167 | `lua/gen1/writes.lua:1-16` | `worktree:lua/gen1/writes.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- lua/gen1/writes.lua — every byte the Gen 1 client write |
| 168 | `lua/gen1/signals.lua:6-9` | `worktree:lua/gen1/signals.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- capture_offset (hook = address + capture_offset), expec |
| 169 | `engine/items/item_effects.asm:212` | `pokecrystal:engine/items/item_effects.asm` | YES | `PokeBallEffect` | YES | - | PokeBallEffect: |
| 170 | `engine/pokemon/move_mon.asm:3` | `pokecrystal:engine/pokemon/move_mon.asm` | YES | `TryAddMonToParty` | YES | - | TryAddMonToParty: |
| 171 | `engine/battle/core.asm:2607-2654` | `pokecrystal:engine/battle/core.asm` | YES | `HandlePlayerMonFaint` | YES | - | HandlePlayerMonFaint: / call FaintYourPokemon / ld hl, wEn |
| 172 | `engine/pokemon/move_mon.asm:1121` | `pokecrystal:engine/pokemon/move_mon.asm` | YES | `GiveEgg` | YES | - | GiveEgg:: |
| 173 | `docs/gen2/research/pret_gen2_symbols.md:96-118` | `worktree:docs/gen2/research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | ## 4. Capture /  / `PokeBallEffect` at pokecrystal@7a7881d |
| 174 | `lua/gen1/entry.lua:403` | `worktree:lua/gen1/entry.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | function Entry.bizhawk_deps() |
| 175 | `lua/gen1/entry.lua:413` | `worktree:lua/gen1/entry.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | on_bus_exec = function(fn, addr, name, d) return event.on_ |
| 176 | `docs/gen2/research/bizhawk_gambatte_gbc.md:109-133` | `worktree:docs/gen2/research/bizhawk_gambatte_gbc.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | **Callback address IS the CPU-bus (System Bus) address, an |
| 177 | `docs/protocol.md:491-516` | `worktree:docs/protocol.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | ## 8. Gen 3-isms baked into shared code /  / Things a non- |
| 178 | `lua/gen1/panel.lua:8-10` | `worktree:lua/gen1/panel.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- All writes go through the injected writes.lua instance  |
| 179 | `lua/gen1/panel.lua:32-33` | `worktree:lua/gen1/panel.lua` | YES | `SFX_CODE_FOR_GEN3_ID` | YES | - | -- The server speaks Gen 3 SE numbers (docs/protocol.md pl |
| 180 | `patch/gen1/README.md:52-55` | `worktree:patch/gen1/README.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | `Joypad`'s `call _Joypad` (`$01A4`) is pointed at `SlinkJo |
| 181 | `lua/sfx_arbiter.lua:20` | `worktree:lua/sfx_arbiter.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- Pass the caller's own SE constants (they are ROM-profil |
| 182 | `docs/protocol.md:497` | `worktree:docs/protocol.md` | YES | `sanitize` | NO | - | \| 1 \| `state.py:718,1177,1186,1259,1332,1364,1385,1409,1 |
| 183 | `lua/gen1/trade_overlay.lua:5-7` | `worktree:lua/gen1/trade_overlay.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | local MAGIC = {0x53, 0x4C, 0x54, 0x31} -- trade_service.as |
| 184 | `server/state.py:554-800` | `worktree:server/state.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | def _handle_trade_request(self, player_id: str, msg: dict) |
| 185 | `server/adapters/base.py:308` | `worktree:server/adapters/base.py` | YES | `native_trade_ui()` | NO | 300 | def native_trade_ui(self) -> bool: |
| 186 | `docs/shared_runtime.md:35` | `SWEEP:docs/shared_runtime.md` | **NO** | `gen1_rby` | UNKNOWN | - |  |
| 187 | `data/wild/johto_grass.asm:341-364` | `pokegold:data/wild/johto_grass.asm` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | def_grass_wildmons NATIONAL_PARK / db 10 percent, 10 perce |
| 188 | `docs/shared_runtime.md:60` | `SWEEP:docs/shared_runtime.md` | **NO** | `KEYWORD_UNKNOWN` | UNKNOWN | - |  |
| 189 | `docs/FRAMEWORK.md:252` | `SWEEP:docs/FRAMEWORK.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| `lua/peer_ghost_npc.lua` (207) \| header (:1-19): engin |
| 190 | `docs/gen2/research/archipelago_crystal.md:369-373` | `worktree:docs/gen2/research/archipelago_crystal.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | **Exact clone URL + sha the implementation phase should pi |
| 191 | `server/adapters/base.py:282` | `worktree:server/adapters/base.py` | YES | `supports_explode_mode` | YES | - | def supports_explode_mode(self) -> bool: |
| 192 | `lua/slink.lua:83-85` | `worktree:lua/slink.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- No gen1_rby row: the Gen 1 route above returns before t |
| 193 | `server/adapters/gen1_rby.py:490-492` | `worktree:server/adapters/gen1_rby.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | @property / def memorial_box_index(self) -> int: / # const |
| 194 | `server/adapters/base.py:559` | `worktree:server/adapters/base.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | def gb_status_token(status_cond: int) -> str: |
| 195 | `server/adapters/gen1_rby.py:356-358` | `worktree:server/adapters/gen1_rby.py` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | def status_token(self, status_cond: int) -> str: / # const |
| 196 | `docs/gen2/research/rom_hashes.md:100-106` | `worktree:docs/gen2/research/rom_hashes.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | **Which revision does pret target?** Both — `pokecrystal.g |
| 197 | `docs/gen2/research/rom_hashes.md:148-150` | `worktree:docs/gen2/research/rom_hashes.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - Whether `pokecrystal.gbc` (V1.0) or `pokecrystal11.gbc`  |
| 198 | `rom_hashes.md:102-104` | `worktree:docs/gen2/research/rom_hashes.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | doc in this repo uses when it says "Crystal" without a rev |
| 199 | `data/games/gen1_rby/README.md:18` | `worktree:data/games/gen1_rby/README.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | The duo E2E runs two pairings — **Red/Blue** and **Yellow/ |
| 200 | `docs/gen2/REVIEW_RECORD.md:23` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| O-12 \| "We can use whatever the local dump is" (Crysta |
| 201 | `patch/gen1/README.md:36-43` | `worktree:patch/gen1/README.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | Unlike Gen 3, **Gen 1 needs no patch for correctness**. Ra |
| 202 | `docs/gen1_gen2_runtime_checks.md:186-191` | `worktree:docs/gen1_gen2_runtime_checks.md` | YES | `saveram_dir` | YES | - | The duo E2E runs **two Crystal instances against one dump* |
| 203 | `engine/link/link.asm:1994-2044` | `pokecrystal:engine/link/link.asm` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | predef AddTempmonToParty / ld a, [wPartyCount] / dec a / l |
| 204 | `lua/gen1/client.lua:1422-1496` | `worktree:lua/gen1/client.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | -- ── APEX CHIP (pureRGB, PLAN A1) and transformations (A2 |
| 205 | `docs/gen2/research/pret_gen2_symbols.md:70` | `worktree:docs/gen2/research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| `sBox14` \| 0xb9e0 \| 0xb9e0 \| pokecrystal@7a7881d ram |
| 206 | `docs/gen2/research/pret_gen2_symbols.md:223` | `worktree:docs/gen2/research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - Not derivable without a build: absolute SRAM bank *numbe |
| 207 | `docs/gen2/REVIEW_RECORD.md:39` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | ## Codex "Gen2 Base" |
| 208 | `docs/gen2/research/bizhawk_gambatte_gbc.md:255-261` | `worktree:docs/gen2/research/bizhawk_gambatte_gbc.md` | YES | `0x2000` | YES | - | ## Open questions /  / - Whether the `CartRAM` domain for  |
| 209 | `docs/gen2/research/bizhawk_gambatte_gbc.md:262-265` | `worktree:docs/gen2/research/bizhawk_gambatte_gbc.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - Whether GBC double-speed mode changes anything about `on |
| 210 | `docs/gen2/research/bizhawk_gambatte_gbc.md:271-275` | `worktree:docs/gen2/research/bizhawk_gambatte_gbc.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - Whether BizHawk's ROM loader classifies a Gold/Silver RO |
| 211 | `docs/gen2/research/pret_gen2_symbols.md:104` | `worktree:docs/gen2/research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - `LostBattle`: pokecrystal@7a7881d engine/battle/core.asm |
| 212 | `docs/gen2/REVIEW_RECORD.md:42` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - |  |
| 213 | `docs/gen2/research/pret_gen2_symbols.md:110` | `worktree:docs/gen2/research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | - Link trade: `engine/link/link_trade.asm` (pokecrystal@7a |
| 214 | `docs/gen2/research/pret_gen2_symbols.md:117` | `worktree:docs/gen2/research/pret_gen2_symbols.md` | YES | `TryAddMonToParty` | YES | - | - A generic `GivePokemon` label (as distinct from `GiveEgg |
| 215 | `docs/gen2/research/pret_gen2_symbols.md:91-92` | `worktree:docs/gen2/research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| `wTempWildMon` \| not present in JSON (`None`) \| not p |
| 216 | `docs/gen2/research/pret_gen2_symbols.md:89-90` | `worktree:docs/gen2/research/pret_gen2_symbols.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | \| `wOtherTrainerClass` \| 0xd22f \| 0xd118 \| JSON only,  |
| 217 | `lua/clients/gen2_crystal_client.lua:40` | `worktree:lua/clients/gen2_crystal_client.lua` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - | NOT YET IMPLEMENTED (Gen 1 has them): trainer_battle_start |
| 218 | `docs/gen2/REVIEW_RECORD.md:47-55` | `worktree:docs/gen2/REVIEW_RECORD.md` | YES | `KEYWORD_UNKNOWN` | UNKNOWN | - |  / \| # \| Premise (project claim) \| Verdict \| What chan |

## Real defects

Filter: unresolved citations and ambiguous basenames, plus wording near-misses that a reader
would trip on. Keyword-column noise is excluded by construction. **Six rows, four distinct
issues.**

| # | citation | verdict | evidence |
|---|---|---|---|
| 1 | `SWEEP docs/shared_runtime.md:35` (GEN2_BINDING_PLAN:318) | **missing file** | No `docs/shared_runtime.md` anywhere in `gen1-rby-code-sweep-8d06e2`; its `docs/` holds `FRAMEWORK.md`, `REFERENCE.md` and the `shared-*.md` family (`shared-durable-runtime-contract.md`, `shared-execution-window.md`, `shared-event-snapshot.md`, `shared-executor-native-contract.md`, `shared-client-journal-composition.md`, `shared-atomic-records-contract.md`, `shared-bounded-execution.md`, …). Same defect as the two `SWEEP docs/shared_runtime.md:59` cites found in `PLAN.md` in gen2-A3 — this is the 3rd occurrence. |
| 2 | `SWEEP docs/shared_runtime.md:60` (GEN2_BINDING_PLAN:336) | **missing file** | Same file; 4th occurrence across the planning set. The sentence hangs the "no `game_id` branch in the FSM" argument on it. |
| 3 | `PathEntryCollectionExtensions.cs:233-244` (GEN2_BINDING_PLAN:213) | **no root named (but the lines are real)** | The file is not in this worktree, the gen3 worktree, or either pret clone — it is a BizHawk source file. It *does* exist at `<sweep>/.cache/bizhawk-save-source/PathEntryCollectionExtensions.cs`, and lines 233-244 are `SaveRamAbsolutePath(this PathEntryCollection …)`, i.e. exactly the claim. The adjacent `docs/gen2/research/bizhawk_gambatte_gbc.md:197-230`, which carries the same fact, resolves. Fix: name the root (path + sha) or drop the parenthetical. |
| 4 | `Database.cs:270-307` (GEN2_BINDING_PLAN:213) | **missing file** | No `Database.cs` under `E:/Google Drive/SLink` to depth 8 (`find … -iname Database.cs` → empty), and the sweep cache dir holds only `FileWriteResult.cs`, `FileWriter.cs`, `PathEntryCollectionExtensions.cs`. This one is genuinely unverifiable from the repo. |
| 5 | `core.asm:2607` (GEN2_STANDARD_COMPARISON:150) | **ambiguous basename** | Bare `core.asm` matches three pokecrystal files: `engine/battle/core.asm`, `engine/battle_anims/core.asm`, `engine/sprite_anims/core.asm`. Intent is certain — line 2607 of `engine/battle/core.asm` is `HandlePlayerMonFaint`, and the sibling cite in the same sentence names that routine — but the path does not identify a file. `:2915` (`LostBattle`) has the same shape. |
| 6 | `core.asm:2915` (GEN2_STANDARD_COMPARISON:150) | **ambiguous basename** | Same as #5. |

Wording near-miss, listed for completeness and not counted above:

- `maps/NewBarkTown.asm:8` (GEN2_BINDING_PLAN:215) is `scene_script NewBarkTownNoop1Scene,
  SCENE_NEWBARKTOWN_TEACHER_STOPS_YOU`; the `SCENE_NEWBARKTOWN_NOOP` binding the same sentence
  names is on line **9**. `:8-9` would cover the pair; `:8` alone shows only the gating scene.

Two rows that look like defects in the keyword column but are not, so nobody "fixes" them:

- `engine/events/whiteout.asm:14` — keyword `WarpToSpawnPoint` is at line 20, but line 14 is
  `special HealParty` and the sentence claims exactly that ordering (`HealParty` **before**
  `WarpToSpawnPoint`); the two-number cite `:14,20` is correct.
- `constants/pokemon_data_constants.asm:101,113` and `:138,141,142` — the keyword column attaches
  one name to the whole cite list. Verified against the file: `BOXMON_STRUCT_LENGTH`=101,
  `PARTYMON_STRUCT_LENGTH`=113, `MONS_PER_BOX`=138, `BOX_LENGTH`=141, `NUM_BOXES`=142. Every
  number is right for its name.

## Summary

| | GEN2_STANDARD_COMPARISON | GEN2_BINDING_PLAN | total |
|---|---|---|---|
| citations | 238 | 218 | **456** |
| resolve | 238 | 214 | **452** |
| unresolved | 0 | 4 | **4** |
| ambiguous basename | 2 | 0 | **2** |
| keyword at cited line | 51 | 37 | 88 |
| keyword elsewhere in the file | 102 | 66 | 168 |
| no identifier in the citing span | 85 | 115 | 200 |

- The 200 `KEYWORD_UNKNOWN` rows are a limit of the same-line rule (these documents put the
  identifier and the citation on different lines, or inside a table cell with no backticked
  identifier at all), not evidence of a bad citation. `cited line text` is printed for every row
  so those can be read directly.
- The 168 `keyword elsewhere` rows include the 102+66 rule artifacts described above; the
  printed text is the honest column. Sampling them found no wrong line: e.g.
  `lua/gen1/boxes.lua:476` is `local memorial = box_count - 1 -- sBox12: ram/sram.asm:44-49`,
  `engine/events/poisonstep.asm:1` is `DoPoisonStep::`, and `maps/NewBarkTown.asm:292-293` is the
  two `coord_event 1,8` / `1,9` lines.
- `GEN2_STANDARD_COMPARISON` resolves every citation it makes; its only defect is the
  path-completeness of the two bare `core.asm` cites.

DONE gen2-A4: 456 citations, 452 resolve, 6 real defects
