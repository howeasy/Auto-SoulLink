#!/usr/bin/env python3
"""Generate the Polished Crystal v3.2.3 (standard build) data pack from the pinned source.

One tool, one pack: data/games/polished_crystal/{species_index,moves,items,evolutions,trainers,
encounter_tables,static_encounters,gifts,map_names}.json + charmap.lua.  Mirrors the vanilla
tools/gen_gen2_*.py packs (same key names where the concept exists) and adds Polished-only fields
(species `form`/`ext`, extra item pockets, wild Orange Islands/LEVEL_FROM_BADGES, tr_mon extras).

    python tools/gen_polished_pack.py            # write every file, then run the self-checks
    python tools/gen_polished_pack.py --check    # byte-compare the committed files, then self-check
    python tools/gen_polished_pack.py --only moves,items

Source: the pinned checkout (default $SLINK_WORK_ROOT/cache/polished/src, override with --src or
POLISHED_SRC), required to be clean at the commit in data/polished_sources.lock.json.  The standard
build defines none of FAITHFUL / MONOCHROME / DEBUG, so `if DEF(X)` blocks are skipped.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import json
import operator
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rgbds_symbols import parse_symbols  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/games/polished_crystal"
GENERATOR = "tools/gen_polished_pack.py"
DEFINED: set[str] = set()  # standard build: no FAITHFUL / MONOCHROME / DEBUG
SRC = Path(os.environ.get("POLISHED_SRC") or
           Path(os.environ.get("SLINK_WORK_ROOT", "F:/slink-work")) / "cache/polished/src")
UNPARSED: list[str] = []  # source constructs seen but not modelled; reported by main()


# ----------------------------------------------------------------------------- source access
def require(cond, msg):
    if not cond:
        raise ValueError(msg)


def note(msg):
    if msg not in UNPARSED:
        UNPARSED.append(msg)


_cache: dict[str, str] = {}


def read(rel: str) -> str:
    if rel not in _cache:
        _cache[rel] = (SRC / rel).read_text(encoding="utf-8").replace("\r\n", "\n")
    return _cache[rel]


def strip_comment(line: str) -> str:
    q = esc = False
    for i, ch in enumerate(line):
        if ch == '"' and not esc:
            q = not q
        if ch == ";" and not q:
            return line[:i].strip()
        esc = ch == "\\" and not esc
    return line.strip()


def lines(rel: str, macros: bool = False) -> list[tuple[int, str]]:
    """(1-based line, text) of code lines, comments stripped, inactive if/else blocks dropped.

    MACRO..ENDM bodies are skipped unless macros=True.  Only `if [!]DEF(NAME)` is evaluated;
    other `if`s are transparent (their body is kept) and tracked so endc pairs correctly."""
    out, stack, in_macro = [], [], False
    for n, raw in enumerate(read(rel).splitlines(), 1):
        s = strip_comment(raw)
        if not s:
            continue
        if re.match(r"MACRO\??\s", s):
            in_macro = True
            if not macros:
                continue
        if s == "ENDM":
            in_macro = False
            if not macros:
                continue
        if in_macro and not macros:
            continue
        m = re.fullmatch(r"if\s+(!?)DEF\((\w+)\)", s, re.I)
        if m:
            stack.append(["def", (m[2] in DEFINED) != bool(m[1]), False])
            continue
        if re.match(r"if\s", s, re.I):
            stack.append(["other", True, False])
            continue
        if s.lower() == "else":
            top = stack[-1]
            if top[0] == "def":
                top[1] = not top[1]
            continue
        if re.match(r"elif\s", s, re.I):
            stack[-1][1] = True  # no elif on a DEF() chain in the data files read here
            continue
        if s.lower() == "endc":
            stack.pop()
            continue
        if all(e[1] for e in stack):
            out.append((n, s))
    require(not stack, f"{rel}: unterminated if")
    return out


def source_ref(rel: str, n: int) -> str:
    return f"polishedcrystal@{LOCK['source']['commit']} {rel}:{n}"


def split_args(s: str) -> list[str]:
    parts, depth, q, cur = [], 0, False, ""
    for ch in s:
        if ch == '"':
            q = not q
        if not q:
            if ch in "([":
                depth += 1
            elif ch in ")]":
                depth -= 1
            elif ch == "," and depth == 0:
                parts.append(cur.strip())
                cur = ""
                continue
        cur += ch
    if cur.strip() or parts:
        parts.append(cur.strip())
    return parts


# ----------------------------------------------------------------------------- expressions
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod, ast.BitOr: operator.or_, ast.BitAnd: operator.and_, ast.BitXor: operator.xor,
        ast.LShift: operator.lshift, ast.RShift: operator.rshift}


def ev(expr: str, env: dict) -> int:
    e = expr.strip()
    e = re.sub(r"\b0+([1-9]\d*|0)\b", r"\1", e)  # RGBDS decimals may carry leading zeros
    e = re.sub(r"\$([0-9a-fA-F]+)", r"0x\1", e)
    e = re.sub(r"(?<![\w)])%([01]+)\b", r"0b\1", e)
    e = re.sub(r"\bpercent\b", "* 255 // 100", e)
    e = re.sub(r"(?<![/])/(?![/])", "//", e)
    e = e.replace("<<", " << ").replace(">>", " >> ")

    def visit(n):
        if isinstance(n, ast.Constant) and type(n.value) is int:
            return n.value
        if isinstance(n, ast.Name):
            if n.id in env:
                return env[n.id]
            raise ValueError(f"unresolved name {n.id!r} in {expr!r}")
        if isinstance(n, ast.UnaryOp):
            v = visit(n.operand)
            return {ast.USub: -v, ast.UAdd: v, ast.Invert: ~v}[type(n.op)]
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](visit(n.left), visit(n.right))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("HIGH", "LOW"):
            v = visit(n.args[0])
            return (v >> 8) & 255 if n.func.id == "HIGH" else v & 255
        raise ValueError(f"unsupported expression {expr!r}")

    try:
        return visit(ast.parse(e, mode="eval").body)
    except SyntaxError as exc:
        raise ValueError(f"bad expression {expr!r}") from exc


def parse_consts(rel, env=None, hooks=None, only_lines=None) -> dict[str, int]:
    """const_def/const/const_skip/const_next/shift_const/DEF .. EQU|=/rsreset+rb/rw subset."""
    env = dict(env or {})
    hooks = hooks or {}
    cur, step, rs = 0, 1, 0
    for n, s in (only_lines if only_lines is not None else lines(rel)):
        env["const_value"], env["_RS"], env["const_inc"] = cur, rs, step
        op, _, rest = s.partition(" ")
        rest = rest.strip()
        if op in hooks:
            cur = hooks[op](rest, env, cur) or cur
        elif op == "const_def":
            a = split_args(rest) if rest else ["0"]
            cur = ev(a[0], env)
            step = ev(a[1], env) if len(a) > 1 else 1
        elif op == "const_next":
            cur = ev(rest, env)
        elif op == "const_skip":
            cur += step * (ev(rest, env) if rest else 1)
        elif op in ("const", "shift_const"):
            if re.fullmatch(r"\w+", rest):
                require(rest not in env or env[rest] == cur, f"{rel}:{n} duplicate const {rest}")
                env[rest] = cur if op == "const" else 1 << cur
                cur += step
        elif op == "rsreset":
            rs = 0
        elif op == "rsset":
            rs = ev(rest, env)
        else:
            m = re.fullmatch(r"(?i)DEF\s+(\w+)\s+(rb|rw)\s*(.*)", s)
            if m:
                env[m[1]] = rs
                try:
                    rs += (1 if m[2] == "rb" else 2) * (ev(m[3], env) if m[3] else 1)
                except ValueError:
                    rs += 1 if m[2] == "rb" else 2  # offsets after an unresolved array are not used by this tool
                continue
            m = re.fullmatch(r"(?i)DEF\s+(\w+)\s*(?:EQUS?|=)\s*(.+)", s)
            if m and not m[2].lstrip().startswith('"'):
                with contextlib.suppress(ValueError):  # forward refs to names defined elsewhere are fine
                    env[m[1]] = ev(m[2], env)
    env.pop("const_value", None)
    env.pop("_RS", None)
    env.pop("const_inc", None)
    return env


def rawstr(token: str) -> str:
    """'rawchar "Foo@@@"' / 'li "Foo"' operand -> python str (no terminator padding)."""
    m = re.fullmatch(r'"((?:\\.|[^"\\])*)"', token.strip())
    require(m, f"not a string literal: {token}")
    return m[1]


# ----------------------------------------------------------------------------- provenance
LOCK = json.loads((ROOT / "data/polished_sources.lock.json").read_text(encoding="utf-8"))
SYM_PATH = ROOT / "data/polished/polishedcrystal.sym"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_block() -> dict:
    rom = LOCK["outputs"]["polishedcrystal"]
    return {"evidence_level": "SOURCE", "repo": LOCK["source"]["url"], "tag": LOCK["source"]["tag"],
            "commit": LOCK["source"]["commit"], "rom_sha1": rom["sha1"], "sym_sha256": sha256(SYM_PATH),
            "map_sha256": sha256(ROOT / "data/polished/polishedcrystal.map"),
            "lock_sha256": sha256(ROOT / "data/polished_sources.lock.json"),
            "build_provenance_sha256": sha256(ROOT / "data/polished/build_provenance.json"),
            "build": "polishedcrystal-3.2.3.gbc (standard: no FAITHFUL/MONOCHROME/DEBUG)",
            "generator": GENERATOR}


def verify_source() -> None:
    def git(*a):
        r = subprocess.run(["git", "-C", str(SRC), *a], capture_output=True, text=True)
        require(r.returncode == 0, f"git {' '.join(a)} failed in {SRC}: {r.stderr.strip()}")
        return r.stdout.strip()

    require(git("rev-parse", "HEAD") == LOCK["source"]["commit"], "source HEAD differs from the locked commit")
    require(not git("status", "--porcelain", "--untracked-files=no"), "pinned source tree is dirty")
    prov = json.loads((ROOT / "data/polished/build_provenance.json").read_text(encoding="utf-8"))
    require(sha256(SYM_PATH) == prov["symbols"]["polishedcrystal.sym"], "sym differs from build_provenance")
    require(sha256(ROOT / "data/polished/polishedcrystal.map") == prov["symbols"]["polishedcrystal.map"],
            "map differs from build_provenance")


def pack(schema: str, base: str | None, body: dict) -> dict:
    head = {"schema": schema, "generator": GENERATOR, "source": source_block(), "title": "polished_crystal"}
    if base:
        head["base_schema"] = base
    return {**head, **body}


# ----------------------------------------------------------------------------- shared constants
class C:
    """Lazily parsed shared constant tables."""
    _c: dict = {}

    @classmethod
    def get(cls, name):
        if name not in cls._c:
            cls._c[name] = getattr(cls, "_" + name)()
        return cls._c[name]

    @staticmethod
    def _pokemon():
        # ext_const_def/ext_const are form-value macros, handled via hooks
        def ext_def(rest, env, cur):
            a = split_args(rest)
            env["ext_const_value"] = ev(a[0], env) if a else 0
            if len(a) > 1:
                env[a[1]] = env["ext_const_value"]
                env["ext_const_value"] += 1

        def ext_const(rest, env, cur):
            env[rest] = env["ext_const_value"]
            env["ext_const_value"] += 1
            return cur + 1  # const_skip

        env = parse_consts("constants/pokemon_constants.asm",
                           hooks={"ext_const_def": ext_def, "ext_const": ext_const})
        return env

    @staticmethod
    def _species_ids():
        """name -> species id (1..NUM_SPECIES), from the first const block only."""
        out, cur = {}, 0
        for _, s in lines("constants/pokemon_constants.asm"):
            if s.startswith("const_def"):
                cur = int(s.split()[1])
            elif s.startswith("const_skip"):
                cur += 1
            elif m := re.fullmatch(r"const (\w+)", s):
                out[m[1]] = cur
                cur += 1
            elif s.startswith("DEF NUM_SPECIES"):
                break
        return out

    @staticmethod
    def _types():
        return parse_consts("constants/type_constants.asm")

    @staticmethod
    def _items():
        return parse_consts("constants/item_constants.asm")

    @staticmethod
    def _moves():
        return {k: v for k, v in parse_consts("constants/move_constants.asm").items()
                if not k.startswith(("ANIM_", "BATTLEANIM_"))}

    @staticmethod
    def _data():
        return parse_consts("constants/pokemon_data_constants.asm", env=C.get("pokemon"))

    @staticmethod
    def _abilities():
        return parse_consts("constants/ability_constants.asm")

    @staticmethod
    def _tmhm():
        def add(prefix, const):
            def hook(rest, env, cur):
                if prefix:
                    env[prefix + rest] = cur
                env["__tmhm_value__"] += 1  # add_tmnum
                return cur + 1 if const else cur
            return hook

        return parse_consts("constants/tmhm_constants.asm", hooks={
            "add_tm": add("TM_", True), "add_hm": add("HM_", True), "add_mt": add("", False)})

    @staticmethod
    def _text():
        return parse_consts("constants/text_constants.asm")


def invert(d: dict[str, int]) -> dict[int, str]:
    out = {}
    for k, v in d.items():
        out.setdefault(v, k)
    return out


def human(const: str) -> str:
    return const.replace("_", " ")


# ----------------------------------------------------------------------------- species
STATS6 = ("hp", "attack", "defense", "speed", "special_attack", "special_defense")


def base_rows():
    """BaseData rows in table order -> [(include path, lineno, tag)] where tag is the trailing comment."""
    out = []
    for n, raw in enumerate(read("data/pokemon/base_stats.asm").splitlines(), 1):
        m = re.match(r'\s*INCLUDE "(data/pokemon/base_stats/[^"]+)"\s*(?:;\s*(.*))?$', raw)
        if m:
            out.append((m[1], n, (m[2] or "").strip()))
    return out


def parse_base_file(path: str, env: dict) -> dict:
    ls = lines(path)
    require(len(ls) >= 9, f"{path}: short base stats")
    row = {}
    ev_yield = {}
    for n, s in ls:
        op, _, rest = s.partition(" ")
        a = split_args(rest)
        if op == "db" and "stats" not in row and len(a) == 6:
            row["stats"] = [ev(x, env) for x in a]
        elif op == "db" and "types" not in row and len(a) == 2 and all(x in env for x in a):
            row["types"] = a
        elif op == "db" and "catch" not in row:
            row["catch"] = ev(a[0], env)
        elif op == "db" and "exp" not in row:
            row["exp"] = ev(a[0], env)
        elif op == "db" and "items" not in row:
            row["items"] = a
        elif op == "dn" and "gender" not in row:
            row["gender"], row["hatch"] = a
        elif op == "abilities_for":
            row["abilities"] = a[1:]
        elif op == "db" and "growth" not in row:
            row["growth"] = a[0]
        elif op == "dn" and "eggs" not in row:
            row["eggs"] = a
        elif op == "ev_yield":
            toks = rest.split()
            for v, st in zip(toks[::2], toks[1::2], strict=True):
                ev_yield[st] = int(v)
        elif op == "tmhm":
            row["tmhm"] = a
        else:
            note(f"base stats {path}:{n}: {s}")
    row["ev_yield"] = ev_yield
    return row


def build_species():
    pk = C.get("pokemon")
    ids = C.get("species_ids")
    dat = C.get("data")
    types = C.get("types")
    items = C.get("items")
    abil = C.get("abilities")
    num_species, egg = pk["NUM_SPECIES"], pk["EGG"]
    require(num_species == 0x123 and egg == 255, "species constants changed")
    require(max(ids.values()) == num_species, "NUM_SPECIES disagrees with the const block")
    env = {**pk, **types, **items, **abil, **{k: v for k, v in dat.items() if isinstance(v, int)}}
    # gender ratio constants use `percent`
    names_rows = [(n, rawstr(split_args(s.partition(" ")[2])[0])) for n, s in lines("data/pokemon/names.asm")
                  if s.startswith("rawchar")]
    require(len(names_rows) == num_species + 1, "PokemonNames must have NUM_SPECIES+1 rows")
    names = [t.rstrip("@") for _, t in names_rows]
    rows = base_rows()
    require(len(rows) == num_species + pk["NUM_VARIANT_FORMS"], "BaseData row count != NUM_SPECIES + NUM_VARIANT_FORMS")
    id_to_const = invert(ids)
    cache = {}

    def decode(path, n, tag):
        if path not in cache:
            cache[path] = parse_base_file(path, env)
        b = cache[path]
        t = b["types"]
        return {
            "base_stats": dict(zip(STATS6, b["stats"], strict=True)),
            "types": t, "type_ids": [types[x] for x in t],
            "catch_rate": b["catch"], "base_exp": b["exp"],
            "held_item_ids": [items[x] for x in b["items"]], "held_items": b["items"],
            "gender_ratio": ev(b["gender"], env), "gender_ratio_const": b["gender"],
            "egg_cycles": ev(b["hatch"], env), "egg_cycles_const": b["hatch"],
            "growth_rate": b["growth"], "growth_rate_id": env[b["growth"]],
            "egg_groups": b["eggs"], "egg_group_ids": [env[x] for x in b["eggs"]],
            "abilities": b["abilities"], "ability_ids": [abil[x] for x in b["abilities"]],
            "ev_yield": b["ev_yield"], "tmhm_moves": b["tmhm"],
            "source": source_ref("data/pokemon/base_stats.asm", n), "stats_file": path,
        }

    species, egg_obj = {}, None
    for idx in range(1, num_species + 1):
        path, n, tag = rows[idx - 1]
        if idx == egg:
            egg_obj = {"index": egg, "name": names[idx], "classification": "egg", "national_dex": None,
                       "stats_file": path}
            continue
        if idx == egg + 1:  # 0x100 is a hole in the species space; BaseData keeps a second EGG row
            continue
        d = decode(path, n, tag)
        species[str(idx)] = {"const": id_to_const[idx], "name": names[idx],
                             "national_dex": idx if idx <= 251 else None, "classification": "ordinary",
                             "form": 0, "base_index": idx, **d}
    # forms: cosmetic (no BaseData row) then variants (BaseData rows after NUM_SPECIES)
    cos_tab, var_tab = [], []
    cur = None
    for n, s in lines("data/pokemon/variant_forms.asm"):
        if s.endswith(":"):
            cur = cos_tab if s.startswith("CosmeticSpecies") else var_tab
        elif s.startswith("dp "):
            a = split_args(s[3:])
            cur.append((n, a[0], a[1]))
    require(len(cos_tab) == pk["NUM_COSMETIC_FORMS"] and len(var_tab) == pk["NUM_VARIANT_FORMS"],
            "form tables disagree with NUM_COSMETIC_FORMS/NUM_VARIANT_FORMS")
    forms = []
    for i, (n, sp, fm) in enumerate(cos_tab):
        forms.append({"ext": num_species + 1 + i, "kind": "cosmetic", "species": ids[sp], "species_const": sp,
                      "form": ev(fm, pk), "form_const": fm, "base_index": ids[sp],
                      "source": source_ref("data/pokemon/variant_forms.asm", n)})
    for i, (_, sp, fm) in enumerate(var_tab):
        path, bn, tag = rows[num_species + i]
        ext = num_species + 1 + i  # BaseData / EvosAttacks index
        forms.append({"ext": ext, "pic_ext": num_species + 1 + len(cos_tab) + i, "kind": "variant",
                      "species": ids[sp], "species_const": sp, "form": ev(fm, pk), "form_const": fm,
                      "base_index": ext, "name": names[ids[sp]], "classification": "ordinary",
                      **decode(path, bn, tag)})
    require(len({(f["species"], f["form"]) for f in forms}) == len(forms), "duplicate species/form pair")
    return pack("polished-species-v1", "gen2-species-v1", {
        "index_to_national": {k: v["national_dex"] for k, v in species.items() if v["national_dex"]},
        "species": species, "egg": egg_obj,
        "forms": forms,
        "form_constants": {k: v for k, v in pk.items() if k.endswith("_FORM") or k in ("NO_FORM", "PLAIN_FORM")},
        "encoding": {"species_bits": 9, "low_byte": "Species byte", "ext_bit": "EXTSPECIES bit 5 of the form byte (0x20)",
                     "form_bits": "FORM bits 0-4 (0x1f)", "gender_bit": 0x80, "is_egg_bit": 0x40,
                     "base_index_rule": "species id for plain; variant rows at NUM_SPECIES+1+i (BaseData/EvosAttacks); "
                                        "cosmetic forms have no BaseData row (base_index = parent species)"},
        "constants": {"NUM_SPECIES": num_species, "NUM_POKEMON": pk["NUM_POKEMON"], "EGG": egg,
                      "NUM_UNIQUE_POKEMON": pk["NUM_UNIQUE_POKEMON"], "NUM_EXT_POKEMON": pk["NUM_EXT_POKEMON"],
                      "NUM_COSMETIC_FORMS": pk["NUM_COSMETIC_FORMS"], "NUM_VARIANT_FORMS": pk["NUM_VARIANT_FORMS"]},
        "invalid_indices": [0, egg + 1],
        "national_dex_note": "ids 1..251 are national dex numbers (as in Gen 2); ids >251 have no national_dex here "
                             "(not derivable from the pinned source)",
        "tables": {"names": {"symbol": "PokemonNames", "entries": len(names), "source": "data/pokemon/names.asm"},
                   "base_data": {"symbol": "BaseData", "entries": len(rows)}},
        "source_files": ["constants/pokemon_constants.asm", "constants/pokemon_data_constants.asm",
                         "data/pokemon/base_stats.asm", "data/pokemon/base_stats/*.asm",
                         "data/pokemon/names.asm", "data/pokemon/variant_forms.asm"]})


# ----------------------------------------------------------------------------- moves
def build_moves():
    mv = C.get("moves")
    types = C.get("types")
    eff = parse_consts("constants/move_effect_constants.asm")
    rawtype = invert({k: v for k, v in types.items() if k.isupper() and k not in ("NUM_TYPES", "SPECIAL_TYPES")})
    cats = {"PHYSICAL": 0, "SPECIAL": 1, "STATUS": 2}
    num = mv["NUM_ATTACKS"]
    require(num == 255 and mv["NO_MOVE"] == 0 and mv["STRUGGLE"] == 255, "move constants changed")
    names_ls = [(n, rawstr(s.split(None, 1)[1])) for n, s in lines("data/moves/names.asm") if s.startswith("li ")]
    require(len(names_ls) == num, "MoveNames row count != NUM_ATTACKS")
    rows = [(n, split_args(s.split(None, 1)[1])) for n, s in lines("data/moves/moves.asm") if s.startswith("move ")]
    require(len(rows) == num, "Moves row count != NUM_ATTACKS")
    env = {**types, **eff, **cats, **mv}
    moves = []
    for i, ((nn, name), (n, a)) in enumerate(zip(names_ls, rows, strict=True), 1):
        require(len(a) == 8, f"moves.asm:{n} needs 8 fields")
        require(mv[a[0]] == i, f"moves.asm:{n} row {a[0]} is not move id {i}")
        power, acc, pp, chance = ev(a[2], env), ev(a[4], env), ev(a[5], env), ev(a[6], env)
        tid, cat = ev(a[3], env), ev(a[7], env)
        moves.append({"id": i, "constant": a[0], "internal_name": a[0], "name": name, "native_name": name,
                      "animation": i, "effect": ev(a[1], env), "effect_constant": a[1], "power": power,
                      "type": rawtype[tid].title(), "type_id": tid, "type_constant": a[3],
                      "split": ("Physical", "Special", "Status")[cat], "category_id": cat,
                      "accuracy": -1 if acc < 0 else acc, "accuracy_percent": None if acc < 0 else acc,
                      "accuracy_byte": 255 if acc < 0 else acc,
                      "never_misses": acc < 0, "pp": pp, "effect_chance": chance, "effect_chance_percent": chance,
                      "effect_chance_byte": chance,
                      "source": source_ref("data/moves/moves.asm", n), "name_source": source_ref("data/moves/names.asm", nn)})
    tm = C.get("tmhm")
    tm_moves = [(n, s.split(None, 1)[1]) for n, s in lines("data/moves/tmhm_moves.asm")
                if s.startswith("db ") and s.split(None, 1)[1] in mv]
    return pack("polished-moves-v1", "gen2-moves-v1", {
        "tables": {"names": {"symbol": "MoveNames", "rows": num}, "moves": {"symbol": "Moves", "rows": num, "record_size": 8}},
        "split_source": {"rule": "explicit category column in the move macro (PHYSICAL/SPECIAL/STATUS)",
                         "files": ["constants/type_constants.asm", "data/moves/moves.asm"]},
        "moves": moves, "sentinels": {"0": "NO_MOVE"},
        "tmhm": [{"num": i, "kind": "TM" if i <= tm["NUM_TMS"] else "HM" if i <= tm["NUM_TMS"] + tm["NUM_HMS"] else "TUTOR",
                  "move": m, "move_id": mv[m], "source": source_ref("data/moves/tmhm_moves.asm", n)}
                 for i, (n, m) in enumerate(tm_moves, 1)],
        "constants": {"NUM_ATTACKS": num, "NUM_TMS": tm["NUM_TMS"], "NUM_HMS": tm["NUM_HMS"], "NUM_TUTORS": tm["NUM_TUTORS"]},
        "note": "id 255 is STRUGGLE (a real move); there is no CANNOT_MOVE sentinel in this table"})


# ----------------------------------------------------------------------------- items
def build_items():
    it = C.get("items")
    idc = parse_consts("constants/item_data_constants.asm")
    num = it["NUM_ITEMS"]
    require(num == 254 and idc["NUM_POCKETS"] == 6, "item constants changed")
    id_to_const = invert({k: v for k, v in it.items() if k.isupper() and not k.startswith(("NAM_", "NUM_", "FIRST_"))
                          and 0 <= v <= num})
    # key item / apricorn / wing / candy / special spaces: re-run the const blocks section-wise
    allv = lines("constants/item_constants.asm")

    def block(start_marker, end_marker):
        a = next(i for i, raw in enumerate(read("constants/item_constants.asm").splitlines(), 1)
                 if raw.startswith(start_marker))
        b = next((i for i, raw in enumerate(read("constants/item_constants.asm").splitlines(), 1)
                  if i > a and end_marker and raw.startswith(end_marker)), 10**9)
        return [(n, s) for n, s in allv if a < n < b]

    def only_consts(ls):
        got = parse_consts(None, only_lines=ls)
        return {k: v for k, v in got.items() if not k.startswith(("NAM_", "NUM_", "CHARMS_"))}

    keyc = only_consts(block("; key item ids", "; Alphabetical order"))
    apri = only_consts(block("; APRICORN_BOX contents", "; WING_CASE"))
    wing = only_consts(block("; WING_CASE contents", "; CANDY_JAR"))
    candy = only_consts(block("; CANDY_JAR contents", "; key item ids"))
    spec = only_consts(block("; special items ids", "\x00"))
    # attributes
    pockets = invert({k: v for k, v in idc.items() if k in ("ITEM", "MEDICINE", "BALL", "TM_HM", "BERRIES", "KEY_ITEM")})
    attr = []
    key_attr = []
    which = None
    for n, s in lines("data/items/attributes.asm"):
        if s == "ItemAttributes:":
            which = attr
        elif s == "KeyItemAttributes:":
            which = key_attr
        elif s.startswith("item_attribute ") or s.startswith("key_item_attribute "):
            which.append((n, split_args(s.split(None, 1)[1])))
    require(len(attr) == num and len(key_attr) == it["NUM_KEY_ITEMS"], "item attribute row counts disagree")
    names = [rawstr(s.split(None, 1)[1]) for n, s in lines("data/items/names.asm") if s.startswith("li ")]
    require(len(names) == num + 1, "ItemNames must have NUM_ITEMS+1 rows")
    key_names = [rawstr(s.split(None, 1)[1]) for n, s in lines("data/items/key_names.asm") if s.startswith("li ")]
    require(len(key_names) == it["NUM_KEY_ITEMS"] + 1, "KeyItemNames must have NUM_KEY_ITEMS+1 rows")
    env = {**C.get("data"), **parse_consts("constants/battle_constants.asm"), **C.get("types"), **it, **idc}
    items = {}
    ball_ids, mail_ids, berry_ids = [], [], []
    for i in range(1, num + 1):
        n, a = attr[i - 1]
        price, held, param, pocket = ev(a[0], env), ev(a[1], env), ev(a[2], env), ev(a[3], env)
        f, b = ev(a[4], env), ev(a[5], env)
        const = id_to_const[i]
        items[str(i)] = {"constant": const, "native_name": names[i], "name": names[i], "placeholder": False,
                         "price": price, "held_effect": held, "parameter_byte": param & 255, "parameter": param, "permissions": None,
                         "pocket": pockets[pocket], "pocket_id": pocket, "key_item": False,
                         "ball": pocket == idc["BALL"], "tm_hm": None, "field_menu": f, "battle_menu": b,
                         "mail": it["FIRST_MAIL"] <= i < it["FIRST_MAIL"] + it["NUM_MAILS"],
                         "source": source_ref("data/items/attributes.asm", n)}
        if pocket == idc["BALL"]:
            ball_ids.append(i)
        if items[str(i)]["mail"]:
            mail_ids.append(i)
        if pocket == idc["BERRIES"]:
            berry_ids.append(i)
    key_items = {}
    ckey = invert(keyc)
    for i in range(1, it["NUM_KEY_ITEMS"] + 1):
        n, a = key_attr[i - 1]
        key_items[str(i)] = {"constant": ckey[i], "name": key_names[i], "selectable": ev(a[0], env),
                             "field_menu": ev(a[1], env), "battle_menu": ev(a[2], env),
                             "is_charm": i >= it["CHARMS_START"],
                             "source": source_ref("data/items/attributes.asm", n)}

    def named(consts, rel, label):
        nm = [rawstr(s.split(None, 1)[1]) for n, s in lines(rel) if s.startswith("li ")]
        inv = invert(consts)
        lo = min(consts.values())
        out = {}
        for k, name in enumerate(nm):
            out[str(lo + k)] = {"constant": inv.get(lo + k), "name": name}
        return out

    pocket_cap = {"ITEM": idc["MAX_ITEMS"], "MEDICINE": idc["MAX_MEDICINE"], "BALL": idc["MAX_BALLS"],
                  "BERRIES": idc["MAX_BERRIES"], "KEY_ITEM": it["NUM_KEY_ITEMS"], "PC": idc["MAX_PC_ITEMS"]}
    tm = C.get("tmhm")
    return pack("polished-items-v1", "gen2-items-v1", {
        "tables": {"names": {"symbol": "ItemNames", "rows": num + 1},
                   "attributes": {"symbol": "ItemAttributes", "rows": num, "record_size": idc["ITEMATTR_STRUCT_LENGTH"]},
                   "key_attributes": {"symbol": "KeyItemAttributes", "rows": it["NUM_KEY_ITEMS"]}},
        "items": items,
        "key_items": key_items,
        "tm_hm": {"NUM_TMS": tm["NUM_TMS"], "NUM_HMS": tm["NUM_HMS"], "NUM_TUTORS": tm["NUM_TUTORS"],
                  "moves_file": "moves.json#tmhm", "note": "TMs/HMs are a flag array (wTMsHMs), not item ids"},
        "apricorns": named(apri, "data/items/apricorn_names.asm", "apricorn"),
        "wings": named(wing, "data/items/wing_names.asm", "wing"),
        "candies": named(candy, "data/items/exp_candy_names.asm", "candy"),
        "special_items": named(spec, "data/items/special_names.asm", "special"),
        "pockets": {"ids": {str(k): v for k, v in pockets.items()}, "capacity": pocket_cap,
                    "max_item_stack": idc["MAX_ITEM_STACK"],
                    "wram": {"ITEM": "wItems/wNumItems", "MEDICINE": "wMedicine/wNumMedicine", "BALL": "wBalls/wNumBalls",
                             "BERRIES": "wBerries/wNumBerries", "KEY_ITEM": "wKeyItems/wNumKeyItems (id-only, $ff-terminated)",
                             "TM_HM": "wTMsHMs flag array"}},
        "sentinels": {"0": {"constant": "NO_ITEM", "name": names[0]}, "255": {"constant": "ITEM_FROM_MEM"}},
        "ball_ids": ball_ids, "mail_ids": mail_ids, "berry_ids": berry_ids,
        "constants": {"NUM_ITEMS": num, "NUM_KEY_ITEMS": it["NUM_KEY_ITEMS"], "NUM_POKE_BALLS": it["NUM_POKE_BALLS"],
                      "NUM_BERRIES": it["NUM_BERRIES"], "FIRST_BERRY": it["FIRST_BERRY"], "NUM_MAILS": it["NUM_MAILS"],
                      "FIRST_MAIL": it["FIRST_MAIL"], "NUM_STONES": it["NUM_STONES"], "FIRST_STONE": it["FIRST_STONE"],
                      "NUM_POCKETS": idc["NUM_POCKETS"]},
        "note": "ball_ids includes NO_ITEM-aliased PARK_BALL only as id 0 sentinel (not listed); 'permissions' has no "
                "Polished equivalent"})


# ----------------------------------------------------------------------------- evolutions
def build_evolutions():
    pk = C.get("pokemon")
    ids = C.get("species_ids")
    dat = C.get("data")
    items = C.get("items")
    moves = C.get("moves")
    lm = parse_consts("constants/landmark_constants.asm")
    env = {**pk, **items, **{k: v for k, v in dat.items() if isinstance(v, int)}}
    methods = {k[7:]: v for k, v in dat.items() if k.startswith("EVOLVE_") and isinstance(v, int)}
    blocks, cur = {}, None
    for n, s in lines("data/pokemon/evos_attacks.asm"):
        if s.startswith("evos_attacks "):
            cur = s.split()[1] + "EvosAttacks"
            require(cur not in blocks, f"duplicate evos block {cur}")
            blocks[cur] = []
        elif s.startswith("evo_data "):
            blocks[cur].append((n, split_args(s[len("evo_data "):])))
        elif re.fullmatch(r"\w+EvosAttacks:", s):  # hand-placed label: the evolved mon's block, no evolutions
            cur = s[:-1]
            blocks[cur] = []
    labels = [m[1] for _, s in lines("data/pokemon/evos_attacks_pointers.asm") if (m := re.fullmatch(r"dw (\w+)", s))]
    require(len(labels) == len(base_rows()), "EvosAttacksPointers row count != BaseData row count")
    require(set(labels) == set(blocks), "evos pointer/label inventory mismatch")
    num_species = pk["NUM_SPECIES"]
    happy = dat.get("HAPPINESS_TO_EVOLVE")
    rows_by, edges = {}, {}
    for idx, label in enumerate(labels, 1):
        out = []
        for n, a in blocks[label]:
            m = a[0].removeprefix("EVOLVE_")
            require(m in methods, f"{label}: unknown evolve method {a[0]}")
            args = a[1:]
            second = None
            if m in ("STAT", "HOLDING"):
                second, args = args[1], [args[0]] + args[2:]
            param, tail = args[0], args[1:]
            require(1 <= len(tail) <= 2, f"{label}: unsupported evo_data shape {a}")
            target = ids[tail[0]]
            tform = ev(tail[1], env) if len(tail) == 2 else pk["PLAIN_FORM"]
            row = {"method": m, "method_id": methods[m], "target": target, "target_const": tail[0],
                   "target_form": tform, "target_form_const": tail[1] if len(tail) == 2 else "PLAIN_FORM"}
            if m == "LEVEL":
                row["minimum_level"] = ev(param, env)
            elif m == "ITEM":
                row.update(item=param, item_id=items[param])
            elif m == "TRADE":
                row.update(held_item=param, held_item_id=items[param])
            elif m == "HAPPINESS":
                row.update(time=param, time_id=dat[param], minimum_happiness=happy)
            elif m == "CRIT":
                row.update(time=param, time_id=dat[param])
            elif m == "STAT":
                row.update(minimum_level=ev(param, env), comparison=second, comparison_id=dat[second])
            elif m == "HOLDING":
                row.update(held_item=param, held_item_id=items[param], time=second, time_id=dat[second])
            elif m == "LOCATION":
                row.update(landmark=param, landmark_id=lm[param])
            elif m == "MOVE":
                row.update(move=param, move_id=moves[param])
            elif m == "PARTY":
                row.update(party_species=param, party_species_id=ids[param])
            else:
                row["param"] = param
                note(f"evolution method {m} parameter kept raw ({label})")
            row["source"] = source_ref("data/pokemon/evos_attacks.asm", n)
            out.append(row)
        if out:
            rows_by[str(idx)] = out
            edges[idx] = sorted({r["target"] for r in out})
    # family: union-find over species ids (form-agnostic), lowest species id is the family root
    parent = {sid: sid for sid in range(1, num_species + 1)}

    def find(x):
        while x != parent[x]:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for idx, tg in edges.items():
        sp = idx if idx <= num_species else None
        if sp is None:  # variant row: species is the form-table species
            continue
        for t in tg:
            a, b = find(sp), find(t)
            parent[max(a, b)] = min(a, b)
    forms = build_species_forms_index()
    for idx, tg in edges.items():
        if idx > num_species:
            sp = forms[idx]
            for t in tg:
                a, b = find(sp), find(t)
                parent[max(a, b)] = min(a, b)
    return pack("polished-evolutions-v1", "gen2-evolutions-v1", {
        "evolutions": {str(i): t for i, t in edges.items()},
        "family": {str(s): find(s) for s in parent if s not in (255, 256)},
        "methods": rows_by,
        "key": "BaseData/EvosAttacks index: species id (1..NUM_SPECIES) or NUM_SPECIES+1+i for variant rows "
               "(see species_index.json forms[].ext); target_form NO_FORM(0)=keep pre-evo form",
        "method_ids": methods,
        "tables": {"pointers": {"symbol": "EvosAttacksPointers", "entries": len(labels), "record_size": 2}},
        "source_files": ["constants/pokemon_constants.asm", "constants/pokemon_data_constants.asm",
                         "data/pokemon/evos_attacks_pointers.asm", "data/pokemon/evos_attacks.asm"]})


def build_species_forms_index():
    """variant ext index -> parent species id (cheap re-derivation, no stats parse)."""
    ids, pk = C.get("species_ids"), C.get("pokemon")
    tab = []
    cur = None
    for _, s in lines("data/pokemon/variant_forms.asm"):
        if s.endswith(":"):
            cur = s.startswith("VariantSpecies")
        elif s.startswith("dp ") and cur:
            tab.append(ids[split_args(s[3:])[0]])
    return {pk["NUM_SPECIES"] + 1 + i: sp for i, sp in enumerate(tab)}


# ----------------------------------------------------------------------------- ROM cross-check
ROM_PATH = Path(os.environ.get("SLINK_WORK_ROOT", "F:/slink-work")) / "cache/polished/release/polishedcrystal-3.2.3.gbc"
_rom = {}


def rom():
    if "d" not in _rom:
        data = ROM_PATH.read_bytes()
        require(hashlib.sha1(data).hexdigest() == LOCK["outputs"]["polishedcrystal"]["sha1"], "ROM sha1 differs from the lock")
        _rom["d"] = data
        _rom["sym"] = parse_symbols(SYM_PATH.read_text(encoding="utf-8"))
    return _rom["d"], _rom["sym"]


def rom_at(symbol, size):
    data, sym = rom()
    s = sym[symbol]
    off = s.bank * 0x4000 + s.address - 0x4000 if s.bank else s.address
    return data[off:off + size]


# ----------------------------------------------------------------------------- trainers
def display_name(t: str) -> str:
    return t.replace("<PK><MN>", "Pokémon").replace("#", "Poké")


def spread(text: str, default: int) -> dict:
    stats = {"HP": "hp", "ATK": "attack", "DEF": "defense", "SPE": "speed", "SAT": "special_attack", "SDF": "special_defense"}
    out = dict.fromkeys(stats.values(), default)
    for part in split_args(text):
        m = re.fullmatch(r"(\d+)\s+(\w+)", part.strip())
        require(m, f"bad DV/EV spread {text!r}")
        name = m[2].upper()
        if name == "ALL":
            out = dict.fromkeys(stats.values(), int(m[1]))
        else:
            require(name in stats, f"bad stat {name!r}")
            out[stats[name]] = int(m[1])
    return out


def build_trainers():
    items, moves = C.get("items"), C.get("moves")
    ids = C.get("species_ids")
    pk, dat = C.get("pokemon"), C.get("data")
    nat = parse_consts("constants/nature_constants.asm")
    tdc = parse_consts("constants/trainer_data_constants.asm")

    def trainerclass(rest, env, cur):
        env[rest] = env["__trainer_class__"]
        env["__trainer_class__"] += 1
        return 1  # const_def 1: instance constants restart at 1

    env = parse_consts("constants/trainer_constants.asm", hooks={"trainerclass": trainerclass})
    num_classes = env["NUM_TRAINER_CLASSES"]
    classes = {}  # const -> class id (only trainerclass lines)
    ordinal = 0
    for _, s in lines("constants/trainer_constants.asm"):
        if m := re.fullmatch(r"trainerclass (\w+)", s):
            classes[m[1]] = ordinal
            ordinal += 1
    require(classes["TRAINER_NONE"] == 0 and ordinal > num_classes, "trainer class numbering changed")
    pic_only = {k: v for k, v in classes.items() if v > num_classes}  # fossil/meteorite/silhouette pics, no party
    classes = {k: v for k, v in classes.items() if v <= num_classes}
    id_to_class = invert(classes)
    class_names = [rawstr(s.split(None, 1)[1]) for _, s in lines("data/trainers/class_names.asm") if s.startswith("li ")]
    require(len(class_names) == num_classes, "TrainerClassNames row count != NUM_TRAINER_CLASSES")
    groups = [m[1] for _, s in lines("data/trainers/party_pointers.asm") if (m := re.fullmatch(r"dba (\w+)", s))]
    ino = [s for _, s in lines("data/trainers/party_pointers.asm") if s.startswith("dbw ")]
    require(ino == ["dbw BANK(@), wInverGroup"], "unexpected non-dba TrainerGroups rows")
    inver_class = classes["INVER"]
    groups.insert(inver_class - 1, "PsychicInverGroup")  # runtime-built in WRAM (wInverGroup)
    require(len(groups) == num_classes, "TrainerGroups row count != NUM_TRAINER_CLASSES")
    # DVS_HP_* named spreads (standard branch of data/trainers/macros.asm)
    hp_dvs = {m[1]: m[2] for _, s in lines("data/trainers/macros.asm")
              if (m := re.fullmatch(r'DEF (DVS_HP_\w+)\s+EQUS "([^"]*)"', s))}
    species_rows = build_species()
    ab_by = {(int(k), 0): v["abilities"] for k, v in species_rows["species"].items()}
    for f in species_rows["forms"]:
        if f["kind"] == "variant":
            ab_by[(f["species"], f["form"])] = f["abilities"]
    env_ev = {**pk, **dat, **items, **moves, **C.get("types")}
    classes_out = {"0": "Nobody"}
    parties, named = {}, {}
    cur_class, cur_tr, mon = None, None, None
    seq = {}

    def finish():
        nonlocal cur_tr
        if cur_tr is None:
            return
        cur_tr["empty_party"] = not cur_tr["party"]  # a few unused trainers carry no mons
        require(len(cur_tr["party"]) <= (7 if cur_tr["runtime_party_source"] == "RANDOM_6_OF_POOL" else 6),
                f"{cur_tr['name_raw']} ({cur_tr['source']}): party size")
        flags = 0
        for mn in cur_tr["party"]:
            flags |= ((mn["item"] is not None) << tdc["TRNTYPE_ITEM"] | (mn["evs"] is not None) << tdc["TRNTYPE_EVS"]
                      | (mn["dvs"] is not None) << tdc["TRNTYPE_DVS"]
                      | (mn["gender"] is not None) << tdc["TRNTYPE_PERSONALITY"]
                      | (mn["nickname"] is not None) << tdc["TRNTYPE_NICKNAME"]
                      | (mn["moves"] is not None) << tdc["TRNTYPE_MOVES"])
        cur_tr["trainer_type"] = flags
        cur_tr = None

    def party_lines():
        for n, s in lines("data/trainers/parties.asm"):
            if m := re.fullmatch(r'INCLUDE "([^"]+)"', s):
                if m[1] == "data/trainers/psychic_inver.asm":
                    for n2, s2 in lines(m[1]):
                        yield m[1], n2, s2
            else:
                yield "data/trainers/parties.asm", n, s

    for rel, n, s in party_lines():
        op, _, rest = s.partition(" ")
        if op in ("SECTION", "ENDSECTION", "pushc", "popc", "assert") or re.fullmatch(r"\w+Group:", s):
            continue
        if op == "def_trainer_class":
            finish()
            cur_class = classes[rest.strip()]
            seq[cur_class] = 0
            if cur_class:
                parties[str(cur_class)] = {}
                named[str(cur_class)] = {}
            continue
        if op == "def_trainer":
            finish()
            a = split_args(rest)
            seq[cur_class] += 1
            inst = seq[cur_class]
            ident = None if re.fullmatch(r"\d+", a[0]) else a[0]
            require(ev(a[0], env) == inst, f"parties.asm:{n}: trainer constant {a[0]} != party index {inst}")
            raw = rawstr(a[1])
            cur_tr = {"name_raw": raw, "name": display_name(raw), "trainer_type": 0, "party": [],
                      "source": source_ref(rel, n), "id": inst, "class_id": cur_class,
                      "trainer_id": cur_class * 256 + inst,
                      "constant": ident,
                      "runtime_party_source": "RANDOM_6_OF_POOL" if rel.endswith("psychic_inver.asm") else "ROM_TABLE"}
            parties[str(cur_class)][str(inst)] = cur_tr
            named[str(cur_class)][str(inst)] = cur_tr["name"]
        elif op == "tr_mon":
            a = split_args(rest)
            level = ev(a[0], env_ev)
            nick = None
            rest_a = a[1:]
            if rest_a[0].startswith('"'):
                nick, rest_a = rawstr(rest_a[0]), rest_a[1:]
            sp_tok, _, item_tok = rest_a[0].partition(" @ ")
            sp_tok, item_tok = sp_tok.strip(), item_tok.strip()
            fexpr = rest_a[1] if len(rest_a) > 1 else None
            fbyte = ev(fexpr, env_ev) if fexpr else 0
            has_gender = bool(fexpr) and ("MALE" in fexpr or "FEMALE" in fexpr)
            mon = {"level": level, "species": ids[sp_tok], "species_const": sp_tok,
                   "item": items[item_tok] if item_tok else None, "item_const": item_tok or None,
                   "moves": None, "form": fbyte & dat["FORM_MASK"],
                   "gender": ("FEMALE" if fbyte & dat["FEMALE"] else "MALE") if has_gender else None,
                   "form_expr": fexpr, "nickname": nick, "dvs": None, "evs": None, "ability": None,
                   "ability_slot": None, "nature": None, "shiny": False, "hidden_power_type": None}
            cur_tr["party"].append(mon)
        elif op == "tr_extra":
            for tok in split_args(rest):
                if tok == "SHINY":
                    mon["shiny"] = True
                elif "NAT_" + tok in nat:
                    mon["nature"] = tok
                else:
                    mon["ability"] = tok
                    key = (mon["species"], mon["form"])
                    ab = ab_by.get(key if key in ab_by else (mon["species"], 0))
                    mon["ability_slot"] = ab.index(tok) + 1 if ab and tok in ab else None
        elif op == "tr_dvs":
            txt = hp_dvs.get(rest.strip(), rest)
            mon["dvs"] = spread(txt, 15)
            mon["dvs_const"] = rest.strip() if rest.strip() in hp_dvs else None
        elif op == "tr_evs":
            mon["evs"] = spread(rest, 0)
        elif op == "tr_moves":
            out = []
            for t in split_args(rest):
                if t.startswith("HP_"):
                    mon["hidden_power_type"] = t[3:]
                    out.append(moves["HIDDEN_POWER"])
                else:
                    out.append(moves[t])
            mon["moves"] = out + [0] * (4 - len(out))
            if mon["hidden_power_type"] and mon["dvs"] is None:
                mon["dvs"] = spread(hp_dvs["DVS_HP_" + mon["hidden_power_type"]], 15)
                mon["dvs_const"] = "DVS_HP_" + mon["hidden_power_type"] + " (implied by the HP_ move)"
        elif op == "end_trainer":
            finish()
        else:
            note(f"{rel}:{n}: {s}")
    finish()
    seen = [ln.partition(" ")[0] for _, _, ln in party_lines()]
    got_tr = sum(len(v) for v in parties.values())
    got_mon = sum(len(t["party"]) for v in parties.values() for t in v.values())
    require((seen.count("def_trainer"), seen.count("tr_mon")) == (got_tr, got_mon),
            "trainer/mon counts differ from an independent count of the active source lines")
    for cid in range(1, num_classes + 1):
        classes_out[str(cid)] = display_name(class_names[cid - 1])
        require(str(cid) in parties, f"class {id_to_class[cid]} has no party block")
    # ROM check: TrainerGroups dba entries <-> class order (class id <-> Group label)
    table = rom_at("TrainerGroups", 3 * num_classes)
    sym = rom()[1]
    for cid, label in enumerate(groups, 1):
        if cid == inver_class:
            continue  # dbw BANK(@), wInverGroup: filled at runtime, not a ROM address
        bank, addr = table[3 * (cid - 1)], int.from_bytes(table[3 * (cid - 1) + 1:3 * cid], "little")
        require((bank, addr) == (sym[label].bank, sym[label].address), f"TrainerGroups[{cid}] ROM != sym {label}")
    return pack("polished-trainers-v1", "gen2-trainers-v1", {
        "classes": classes_out, "named_trainers": named,
        "class_constants": {str(v): k for k, v in classes.items()},
        "pic_only_classes": pic_only,
        "class_groups": {str(i): g for i, g in enumerate(groups, 1)},
        "class_names_raw": {str(i): n for i, n in enumerate(class_names, 1)},
        "id_packing": "trainer_id = class_id * 256 + instance (wOtherTrainerClass/wOtherTrainerID)",
        "rival_classes": {k: classes[k] for k in ("RIVAL0", "RIVAL1", "RIVAL2", "LYRA1", "LYRA2")},
        "parties": parties,
        "constants": {"NUM_TRAINER_CLASSES": num_classes},
        "open_obligations": ["BattleTower_and_link_parties", "runtime_trainer_dispatch_and_battle_completion"]})


# ----------------------------------------------------------------------------- maps
def map_constants():
    """MAP_CONST -> {group, number, width, height, order}; group ids start at 1 (newgroup)."""
    out, group, number, order = {}, 0, 0, 0
    for n, s in lines("constants/map_constants.asm"):
        if s == "newgroup":
            group += 1
            number = 0
        elif s.startswith("map_const "):
            a = split_args(s[len("map_const "):])
            number += 1
            order += 1
            require(a[0] not in out, f"duplicate map const {a[0]}")
            out[a[0]] = {"group": group, "number": number, "width": int(a[1]), "height": int(a[2]), "line": n}
        elif not (s.startswith(("const_def", "DEF ", "assert", "if ", "endc")) or s.startswith("; ")):
            note(f"map_constants.asm:{n}: {s}")
    require(len({(v["group"], v["number"]) for v in out.values()}) == len(out), "map ids are not unique")
    return out


def level_fields(token, env):
    v = ev(token, env)
    lfb = env["LEVEL_FROM_BADGES"]
    if v > 100:  # LEVEL_FROM_BADGES + N is resolved at runtime from BadgeBaseLevels[badges] + N
        return {"level": None, "level_raw": v, "level_from_badges_offset": v - lfb}
    return {"level": v}


# ----------------------------------------------------------------------------- encounters
def parse_wild(rel, kind, maps, ids, env):
    recs, cur, rates, mons = [], None, None, []
    per = {"grass": 21, "water": 3}[kind]
    times = ("morning", "day", "night") if kind == "grass" else ("all",)
    table = rel.split("/")[-1].removesuffix(f"_{kind}.asm").title() + ("Grass" if kind == "grass" else "Water") + "WildMons"
    for n, s in lines(rel):
        op, _, rest = s.partition(" ")
        if op == f"def_{kind}_wildmons":
            cur, rates, mons = (rest.strip(), n), [], []
        elif op == "db" and cur and rates is not None and not rates:
            rates = [(ev(x, env), x) for x in split_args(rest)]
            require(len(rates) == len(times), f"{rel}:{n} rate count")
        elif op == "wildmon":
            a = split_args(rest)
            mons.append({"species": ids[a[1]], "form": ev(a[2], env) if len(a) > 2 else env["PLAIN_FORM"],
                         **level_fields(a[0], env), "species_const": a[1]})
        elif op == f"end_{kind}_wildmons":
            require(len(mons) == per, f"{rel}:{cur[1]} expected {per} wildmons, got {len(mons)}")
            m = maps[cur[0]]
            for i, t in enumerate(times):
                recs.append({"table": table, "map_const": cur[0], "map_group": m["group"], "map_number": m["number"],
                             "time": t, "rate": rates[i][0], "rate_expr": rates[i][1],
                             "slots": mons[i * (per // len(times)):(i + 1) * (per // len(times))],
                             "source": source_ref(rel, cur[1])})
            cur = None
        elif s == "db -1":
            continue
        elif op not in ("INCLUDE",):
            note(f"{rel}:{n}: {s}")
    require(cur is None, f"{rel}: unterminated table")
    keys = [(r["map_group"], r["map_number"], r["time"]) for r in recs]
    require(len(keys) == len(set(keys)), f"{rel}: duplicate map/time")
    return recs


def build_encounters():
    maps = map_constants()
    ids = C.get("species_ids")
    dat, pk = C.get("data"), C.get("pokemon")
    env = {**pk, **{k: v for k, v in dat.items() if isinstance(v, int)}, **C.get("items"), **C.get("moves")}
    wild = {"grass": [], "water": []}
    for kind in ("grass", "water"):
        for region in ("johto", "kanto", "orange", "swarm"):
            wild[kind] += parse_wild(f"data/wild/{region}_{kind}.asm", kind, maps, ids, env)
    vals = [ev(s.split(None, 1)[1], env) for _, s in lines("data/wild/probabilities.asm") if s.startswith("db ")]
    gp, wp = vals[:dat["NUM_GRASSMON"]], vals[dat["NUM_GRASSMON"]:]  # GrassMonProbTable then WaterMonProbTable
    require(len(gp) == dat["NUM_GRASSMON"] and gp[-1] == 100 and len(wp) == dat["NUM_WATERMON"] and wp[-1] == 100,
            "wild slot probability tables malformed")
    wild["grass_probabilities"] = [{"threshold": t, "slot_index": i} for i, t in enumerate(gp)]
    wild["water_probabilities"] = [{"threshold": t, "slot_index": i} for i, t in enumerate(wp)]
    wild["badge_base_levels"] = [ev(s.split(None, 1)[1], env) for _, s in lines("data/wild/badge_base_levels.asm")
                                 if s.startswith("db ")]
    wild["level_from_badges"] = env["LEVEL_FROM_BADGES"]

    # headbutt / rock smash
    sets_c = {k: v for k, v in dat.items() if k.startswith("TREEMON_SET_") and isinstance(v, int)}
    tmaps, cur = {"TreeMonMaps": [], "RockMonMaps": []}, None
    for n, s in lines("data/wild/treemon_maps.asm"):
        if s.endswith(":"):
            cur = s[:-1]
        elif s.startswith("treemon_map "):
            a = split_args(s[len("treemon_map "):])
            m = maps[a[0]]
            tmaps[cur].append({"map_const": a[0], "map_group": m["group"], "map_number": m["number"],
                               "set_id": sets_c[a[1]], "source": source_ref("data/wild/treemon_maps.asm", n)})
    labels = [m[1] for _, s in lines("data/wild/treemons.asm") if (m := re.fullmatch(r"dw (\w+)", s))]
    require(len(labels) == dat["NUM_TREEMON_SETS"] + 1 and labels[-1] == "TreeMonSet_City",
            "TreeMons pointer table changed (NUM_TREEMON_SETS + one trailing unused dw)")
    labels = labels[:dat["NUM_TREEMON_SETS"]]
    parts, cur_labels = {}, []
    in_tab = False
    for _, s in lines("data/wild/treemons.asm"):
        if re.fullmatch(r"TreeMonSet_\w+:", s):
            if in_tab:
                cur_labels, in_tab = [], False
            cur_labels.append(s[:-1])
            parts[s[:-1]] = None
        elif s.startswith("tree_mon ") or s == "db -1":
            if not in_tab:
                in_tab = True
                blk = [[]]
                for lbl in cur_labels:
                    parts[lbl] = blk
            if s == "db -1":
                blk.append([])
            else:
                a = split_args(s[len("tree_mon "):])
                row = {"weight": ev(a[0], env), "species": ids[a[1]], "species_const": a[1],
                       "form": ev(a[2], env) if len(a) == 4 else pk["PLAIN_FORM"], "level": ev(a[-1], env)}
                blk[-1].append(row)
    tsets = []
    for sid, label in enumerate(labels):
        blk = [p for p in parts[label] if p]
        rock = sid == sets_c["TREEMON_SET_ROCK"]
        require(len(blk) == (1 if rock else 2), f"{label}: expected {1 if rock else 2} tables")
        require(all(sum(r["weight"] for r in p) == 100 for p in blk), f"{label}: weights must sum to 100")
        tsets.append({"set_id": sid, "label": label, "kind": "rock_smash" if rock else "headbutt",
                      "common": blk[0], "rare": [] if rock else blk[1]})
    # asleep tree mons by time of day
    asleep, cur = {}, []
    for _, s in lines("data/wild/treemons_asleep.asm"):
        if s.startswith("."):
            cur.append(s[1:].rstrip(":"))
        elif s.startswith("dp "):
            for c in cur:
                asleep.setdefault(c, []).append(ids[s[3:].strip()])
        elif s == "db 0":
            cur = []
    unown_sets = {}
    cur = None
    for _, s in lines("data/wild/unlocked_unowns.asm"):
        if s.startswith(".Set_"):
            cur = s[:-1]
        elif s.startswith("unown_set ") and cur:
            unown_sets[cur[1:]] = split_args(s[len("unown_set "):])
    tree = {"headbutt_maps": tmaps["TreeMonMaps"], "rock_smash_maps": tmaps["RockMonMaps"], "sets": tsets,
            "asleep_by_time": asleep}

    # fishing
    fg = parse_consts("constants/map_data_constants.asm")
    fish_const = {k: v for k, v in fg.items() if k.startswith("FISHGROUP_") and k != "NUM_FISHGROUPS"}
    headers, tabs, cur = [], {}, None
    for n, s in lines("data/wild/fish.asm"):
        if s.startswith("fishgroup "):
            headers.append((n, split_args(s[len("fishgroup "):])))
        elif re.fullmatch(r"\.\w+:", s):
            cur = s[:-1]
            tabs.setdefault(cur, [])
        elif s.startswith("fishentry "):
            a = split_args(s[len("fishentry "):])
            form = ev(a[2], env) if len(a) == 4 else pk["PLAIN_FORM"]
            row = {"threshold": ev(a[0], env), "species": 0 if a[1] == "0" else ids[a[1]], "form": form,
                   "level": ev(a[-1], env)}
            if a[1] == "0":
                row["time_dependent"] = True  # corsola morn/day, staryu eve/night (engine, see fish.asm comments)
            tabs[cur].append(row)
    # consecutive labels alias one table: the entries are stored on the last label of a run
    seq, run = [], []
    for _, s in lines("data/wild/fish.asm"):
        if re.fullmatch(r"\.\w+:", s):
            run.append(s[:-1])
        elif s.startswith("fishentry ") and run:
            seq.append(run)
            run = []
    alias = {}
    for r in seq:
        for lbl in r[:-1]:
            alias[lbl] = r[-1]
    groups = []
    for gi, (n, a) in enumerate(headers):
        g = {"group_id": gi, "const": next(k for k, v in fish_const.items() if v == gi) if gi in fish_const.values() else None,
             "bite_threshold": ev(a[0], env), "bite_or_item_threshold": ev(a[1], env),
             "source": source_ref("data/wild/fish.asm", n)}
        for method, ptr in zip(("old", "good", "super"), a[2:], strict=True):
            rows = tabs[alias.get(ptr, ptr)]
            require(rows and rows[-1]["threshold"] == 255 and all(rows[i]["threshold"] < rows[i + 1]["threshold"]
                                                                    for i in range(len(rows) - 1)),
                    f"fish table {ptr} thresholds")
            g[method] = rows
            g[method + "_label"] = ptr
        groups.append(g)
    require(len(groups) == dat["NUM_FISHGROUPS"] if "NUM_FISHGROUPS" in dat else True, "fish group count")
    fish_maps = []
    for n, s in lines("data/wild/fishmon_maps.asm"):
        if s.startswith("fishmon_map "):
            a = split_args(s[len("fishmon_map "):])
            m = maps[a[0]]
            fish_maps.append({"map_const": a[0], "map_group": m["group"], "map_number": m["number"],
                              "group_id": fg[a[1]], "group_const": a[1],
                              "source": source_ref("data/wild/fishmon_maps.asm", n)})

    # roamers
    graph = []
    for n, s in lines("data/wild/roammon_maps.asm"):
        if s.startswith("roam_map "):
            a = split_args(s[len("roam_map "):])
            o = maps[a[0]]
            graph.append({"map_const": a[0], "map_group": o["group"], "map_number": o["number"],
                          "destinations": [{"map_const": x, "map_group": maps[x]["group"], "map_number": maps[x]["number"]}
                                           for x in a[1:]], "source": source_ref("data/wild/roammon_maps.asm", n)})
    require(len(graph) == dat["NUM_ROAMMON_MAPS"], "roam map count != NUM_ROAMMON_MAPS")
    src = lines("engine/overworld/wildmons.asm")
    start = next(i for i, (_, s) in enumerate(src) if s == "InitRoamMons:")
    init, val, fld = {}, None, {"Species": "species", "Level": "level", "MapGroup": "map_group", "MapNumber": "map_number"}
    for _, s in src[start + 1:]:
        if m := re.fullmatch(r"ld a, (\w+)", s):
            t = m[1]
            val = (maps[t[6:]]["group"] if t.startswith("GROUP_") else maps[t[4:]]["number"] if t.startswith("MAP_")
                   else ids[t] if t in ids else ev(t, env))
        elif s == "inc a":
            val += 1  # RAIKOU + 1 == ENTEI (asserted in the source)
        elif m := re.fullmatch(r"ld \[wRoamMon([12])(Species|Level|MapGroup|MapNumber)\], a", s):
            init.setdefault(int(m[1]), {})[fld[m[2]]] = val
        elif s == "ret":
            break
    require(len(init) == 2 and all(set(v) == set(fld.values()) for v in init.values()), "roamer init incomplete")

    # bug-catching contest
    contest = []
    for n, s in lines("data/wild/bug_contest_mons.asm"):
        if s.startswith("contest_mon "):
            a = split_args(s[len("contest_mon "):])
            row = {"weight": ev(a[0], env), "species": ids[a[1]], "species_const": a[1], "min_level": ev(a[2], env),
                   "max_level": ev(a[3], env), "source": source_ref("data/wild/bug_contest_mons.asm", n)}
            contest.append(row)
    require(sum(r["weight"] for r in contest) == 100, "contest weights must sum to 100")
    return pack("polished-encounter-tables-v1", "gen2-encounter-tables-v1", {
        "wild": wild, "tree": tree,
        "fishing": {"groups": groups, "map_groups": fish_maps, "time_groups": [],
                    "note": "species 0 rows are engine time-of-day picks (time_dependent=true)"},
        "roamers": {"initial": [init[1], init[2]], "maps": graph},
        "contest": {"area_id": "national_park_contest", "slots": contest, "fallback": None,
                    "note": "ContestMons is a plain weighted list; no -1 fallback row in Polished"},
        "unlocked_unown_sets": unown_sets,
        "policy": {"ordinary_area": "shared_across_times_and_methods", "contest_area": "national_park_contest",
                   "roamer_area": "legend_<species>", "roamer_consumes_ordinary_area": False,
                   "egg_hatch_area": "gift_daycare", "acquisition_events": "NOT_ESTABLISHED_BY_TABLES"},
        "inventory": {"complete": ["grass", "water", "grass_swarms", "water_swarms", "orange_islands", "headbutt_slots",
                                   "rock_smash_slots", "fishing", "roamer_initialization_and_map_graph", "contest",
                                   "asleep_tree_mons", "unown_letter_sets", "badge_base_levels"],
                      "open": ["map_areas:not generated here (area_map is a separate pack)",
                               "flee_rules", "runtime_encounter_selection_and_acquisition_qualification"]}})


# ----------------------------------------------------------------------------- map headers / names
def map_headers():
    """CamelCase map label -> header row, paired in order with map_constants() per group."""
    consts = map_constants()
    by_group: dict[int, list[tuple[str, dict]]] = {}
    for k, v in consts.items():
        by_group.setdefault(v["group"], []).append((k, v))
    out, group, idx = {}, None, 0
    pointers = [m[1] for _, s in lines("data/maps/maps.asm") if (m := re.fullmatch(r"dw (MapGroup\d+)", s))]
    require(len(pointers) == len(by_group), "MapGroupPointers count != map constant groups")
    for n, s in lines("data/maps/maps.asm"):
        if m := re.fullmatch(r"(MapGroup\d+):", s):
            group, idx = int(m[1][8:]), 0
        elif s.startswith("map ") and group:
            a = split_args(s[4:])
            require(len(a) == 8, f"maps.asm:{n}: map header needs 8 fields")
            const, c = by_group[group][idx]
            require(a[0].replace("_", "").upper() == const.replace("_", ""), f"maps.asm:{n}: {a[0]} vs {const}")
            out[a[0]] = {"label": a[0], "const": const, "group": group, "number": c["number"], "width": c["width"],
                         "height": c["height"], "tileset": a[1], "environment": a[2], "sign": a[3], "landmark": a[4],
                         "music": a[5], "no_phone": a[6], "palette": a[7], "line": n}
            idx += 1
    require(all(len(v) == sum(1 for m in out.values() if m["group"] == g) for g, v in by_group.items()),
            "map header rows != map constants per group")
    return out


def build_map_names():
    heads = map_headers()
    lmc = parse_consts("constants/landmark_constants.asm")
    entries, texts = [], {}
    for n, s in lines("data/maps/landmarks.asm"):
        if m := re.fullmatch(r"landmark\s+(-?\d+),\s*(-?\d+),\s*(\w+)", s):
            entries.append((int(m[1]) + 8, int(m[2]) + 16, m[3], n))
        elif m := re.fullmatch(r'(\w+):\s+rawchar\s+("(?:\\.|[^"\\])*")', s):
            texts[m[1]] = rawstr(m[2])
    require(len(entries) == lmc["NUM_LANDMARKS"], "landmark count != NUM_LANDMARKS")
    places = {}
    for i, (x, y, label, n) in enumerate(entries):
        t = texts[label]
        require(t.endswith("@"), f"{label}: landmark text lacks the @ terminator")
        raw = t[:-1]
        places[str(i)] = {"label": label, "native_name": raw, "name": raw.replace("¯", " "), "x": x, "y": y,
                          "source": source_ref("data/maps/landmarks.asm", n)}
    maps = {}
    for h in sorted(heads.values(), key=lambda r: (r["group"], r["number"])):
        lid = lmc[h["landmark"]]
        maps[f"{h['group']}:{h['number']}"] = {
            "group": h["group"], "number": h["number"], "encoded_id": h["group"] * 256 + h["number"],
            "constant": h["const"], "width_blocks": h["width"], "height_blocks": h["height"],
            "name": human(h["const"]), "name_origin": "source constant humanization", "source_label": h["label"],
            "landmark_id": lid, "landmark_const": h["landmark"], "landmark_name": places[str(lid)]["name"],
            "native_landmark_name": places[str(lid)]["native_name"], "tileset": h["tileset"],
            "environment": h["environment"], "music": h["music"], "source": source_ref("data/maps/maps.asm", h["line"])}
    require(len({m["encoded_id"] for m in maps.values()}) == len(maps), "encoded map ids are not unique")
    groups = len({h["group"] for h in heads.values()})
    return pack("polished-map-names-v1", "gen2-map-names-v1", {
        "key_format": "group:number", "maps": maps, "landmarks": places,
        "landmark_constants": {k: v for k, v in lmc.items() if k != "NUM_LANDMARKS"} | {"NUM_LANDMARKS": lmc["NUM_LANDMARKS"]},
        "sentinels": {"0:0": "MAPGROUP_NONE/MAP_NONE"},
        "constants": {"NUM_MAP_GROUPS": groups, "NUM_MAPS": len(maps)}})


# ----------------------------------------------------------------------------- statics / gifts / trades
def map_script_files():
    return sorted(p.name for p in (SRC / "maps").glob("*.asm"))


def script_events():
    """Every grant/static op in maps/*.asm with its owning script label: [(rel, line, script, op, args)]."""
    out = []
    for fname in map_script_files():
        rel = f"maps/{fname}"
        glob_label, label = None, None
        for n, s in lines(rel):
            m = re.fullmatch(r"([A-Za-z_]\w*)::?", s)
            if m:
                glob_label = label = m[1]
                continue
            m = re.fullmatch(r"(\.\w+):", s)
            if m:
                label = f"{glob_label}{m[1]}"
                continue
            op, _, rest = s.partition(" ")
            if op in ("givepoke", "giveegg", "givepokemail", "loadwildmon", "special", "loadvar", "startbattle",
                      "catchtutorial", "reloadmapafterbattle", "trade", "loadtrainer"):
                out.append((rel, n, label, op, split_args(rest)))
    return out


def label_text(rel, label):
    """rawchar text following `Label:` in a map file (for named-trainer gift nick/OT)."""
    ls = lines(rel)
    for i, (_, s) in enumerate(ls):
        if s == f"{label}:" and i + 1 < len(ls) and ls[i + 1][1].startswith("rawchar"):
            return rawstr(split_args(ls[i + 1][1].split(None, 1)[1])[0]).rstrip("@")
    return None


def where(rel, heads):
    label = Path(rel).stem
    h = heads.get(label)
    return {"map_name": label, "map_group": h["group"] if h else None, "map_number": h["number"] if h else None}


def build_gifts_statics():
    ids = C.get("species_ids")
    pk, dat = C.get("pokemon"), C.get("data")
    items, moves = C.get("items"), C.get("moves")
    env = {**pk, **{k: v for k, v in dat.items() if isinstance(v, int)}, **items, **moves,
           **parse_consts("constants/misc_constants.asm"), **parse_consts("constants/battle_constants.asm"),
           **parse_consts("constants/nature_constants.asm")}
    heads = map_headers()
    events = script_events()
    gifts, statics, callers = [], [], []
    last_gift = None
    for i, (rel, n, script, op, a) in enumerate(events):
        base = {"id": f"{Path(rel).stem}:{script}:{n}", **where(rel, heads), "source": source_ref(rel, n), "script": script,
                "applicability": {"titles": ["polished_crystal"], "selected": True,
                                  "basis": "source occurrence (standard build); runtime reachability OPEN"}}
        if op == "givepoke":
            if len(a) >= 3:  # macros/scripts/events.asm: _NARG >= 3 =>  is the form
                form_tok, lvl, rest = a[1], a[2], a[3:]
            else:
                form_tok, lvl, rest = "PLAIN_FORM", a[1], a[2:]
            fv = ev(form_tok, env)
            g = {**base, "operation": "givepoke", "arguments": a, "kind": "scripted_grant", "species": ids[a[0]],
                 "species_const": a[0], "form": fv & dat["FORM_MASK"], "form_expr": form_tok,
                 "gender": ("FEMALE" if fv & dat["FEMALE"] else "MALE") if "MALE" in form_tok else None,
                 "level": ev(lvl, env), "item": ev(rest[0], env) if rest else 0, "ball": ev(rest[1], env) if len(rest) > 1 else env["POKE_BALL"],
                 "special_move": ev(rest[2], env) if len(rest) > 2 else 0, "named_trainer": len(rest) > 3,
                 "finalization": "OPEN", "success": "OPEN"}
            if len(rest) > 3:
                g.update(nickname_label=rest[3], nickname=label_text(rel, rest[3]), ot_name_label=rest[4],
                         ot_name=label_text(rel, rest[4]), ot_id=ev(rest[5], env))
            gifts.append(g)
            last_gift = g
        elif op == "givepokemail":
            if last_gift is not None and last_gift["script"] == script:
                last_gift["mail_label"] = a[0]
            else:
                note(f"{rel}:{n}: givepokemail without a preceding givepoke in the same script")
        elif op == "giveegg":
            ftok = a[1] if len(a) > 1 else "PLAIN_FORM"
            gifts.append({**base, "operation": "giveegg", "arguments": a, "kind": "scripted_egg", "species": ids[a[0]],
                          "species_const": a[0], "form": ev(ftok, env) & dat["FORM_MASK"], "form_expr": ftok,
                          "finalization": "OPEN", "success": "OPEN"})
        elif op == "loadwildmon":
            ftok, lvl = (a[1], a[2]) if len(a) == 3 else ("PLAIN_FORM", a[1])
            btypes, kind = [], None
            for rel2, _, _, op2, a2 in events[i + 1:i + 12]:
                if rel2 != rel or op2 == "reloadmapafterbattle":
                    break
                if op2 == "loadvar" and a2[0] == "VAR_BATTLETYPE":
                    btypes.append(a2[1])
                elif op2 == "catchtutorial":
                    kind, btypes = "tutorial", [a2[0]]
                    break
                elif op2 == "startbattle":
                    kind = "scripted_trap_battle" if "BATTLETYPE_TRAP" in btypes else "scripted_wild_battle"
                    break
            if kind is None:
                note(f"{rel}:{n}: loadwildmon with no startbattle/catchtutorial within 11 script ops")
            statics.append({**base, "species": ids[a[0]], "species_const": a[0], "form": ev(ftok, env) & dat["FORM_MASK"],
                            "form_expr": ftok, "level": ev(lvl, env), "kind": kind or "UNCLASSIFIED",
                            "battle_type": [f"loadvar VAR_BATTLETYPE, {b}" for b in btypes],
                            "runtime_battle_type": ev(btypes[-1], env) if btypes else None,
                            "capture_success": "OPEN", "finalization": "OPEN"})
        elif op == "special" and a[0] in ("GiveOddEgg", "WonderTrade"):
            callers.append({**base, "operation": "special", "arguments": a, "target": a[0],
                            "kind": "dynamic_egg_reception" if a[0] == "GiveOddEgg" else "dynamic_wonder_trade",
                            "finalization": "OPEN", "success": "OPEN"})
    # object-event trade callers
    for fname in map_script_files():
        rel = f"maps/{fname}"
        for n, s in lines(rel):
            m = re.search(r"OBJECTTYPE_COMMAND,\s*trade,\s*(NPC_TRADE_\w+)", s)
            if m:
                callers.append({"id": f"{Path(rel).stem}:object_event:{n}", **where(rel, heads), "source": source_ref(rel, n),
                                "operation": "trade", "arguments": [m[1]], "kind": "npc_exchange", "trade_const": m[1],
                                "finalization": "OPEN", "success": "OPEN"})
    # npc trades table
    nt = parse_consts("constants/npc_trade_constants.asm")
    trades, cur = [], None
    ls = lines("data/events/npc_trades.asm")
    raw_lines = read("data/events/npc_trades.asm").splitlines()
    comments = {}
    for i, raw in enumerate(raw_lines, 1):
        if m := re.match(r"; (NPC_TRADE_\w+)", raw):
            comments[i] = m[1]
    cur, blocks = None, []
    for n in range(1, len(raw_lines) + 1):
        if n in comments:
            cur = {"const": comments[n], "line": n, "rows": []}
            blocks.append(cur)
    # assign code lines to the preceding comment block
    starts = [b["line"] for b in blocks] + [10 ** 9]
    for n, s in ls:
        for b, end in zip(blocks, starts[1:], strict=True):
            if b["line"] < n < end:
                b["rows"].append((n, s))
    require(len(blocks) == nt["NUM_NPC_TRADES"], "NPC_TRADE blocks != NUM_NPC_TRADES")
    for tid, b in enumerate(blocks):
        require(nt[b["const"]] == tid, f"{b['const']} is not trade id {tid}")
        r = [s for _, s in b["rows"] if not s.startswith("assert")]
        require(len(r) == 7 and r[0].startswith("db TRADE_DIALOGSET"), f"{b['const']}: unsupported trade block")
        want = split_args(r[1][3:])
        give = split_args(r[2][3:])
        nick = rawstr(r[3].split(None, 1)[1]).rstrip("@")
        db = split_args(r[4][3:])
        otid = ev(r[5].split(None, 1)[1], env)
        otname = rawstr(split_args(r[6].split(None, 1)[1])[0]).rstrip("@")
        gv = ev(give[1], env)
        pers = ev(db[3], env)
        trades.append({"trade_id": tid, "trade_const": b["const"], "kind": "npc_exchange",
                       "requested_species": ids[want[0]], "requested_species_const": want[0],
                       "requested_form": ev(want[1], env) & dat["FORM_MASK"],
                       "offered_species": ids[give[0]], "offered_species_const": give[0],
                       "offered_form": gv & dat["FORM_MASK"], "offered_gender": "FEMALE" if gv & dat["FEMALE"] else "MALE",
                       "nickname": nick, "dvs": [ev(x, env) for x in db[:3]], "personality": pers,
                       "personality_expr": db[3], "ball": ev(db[4], env), "item": ev(db[5], env),
                       "ot_id": otid, "ot_name": otname, "dialog_set": r[0].split()[1],
                       "source": source_ref("data/events/npc_trades.asm", b["line"])})
    # odd eggs
    odd_c = parse_consts("data/events/odd_eggs.asm")
    thr, in_probs = [], False
    for _, s in lines("data/events/odd_eggs.asm"):
        if s == "OddEggProbabilities:":
            in_probs = True
        elif s == "OddEggs:":
            in_probs = False
        elif in_probs and s.startswith("db "):
            thr.append(ev(s[3:], env))
    odd_env = {**env, **parse_consts("constants/nature_constants.asm")}
    odd, mystri, cur, start = [], [], None, False
    target = odd
    for n, s in lines("data/events/odd_eggs.asm"):
        if s == "OddEggs:":
            start = True
        elif s == "MystriEgg:":
            target = mystri
        elif start and s.startswith("dp "):
            a = split_args(s[3:])
            cur = {"species": ids[a[0]], "species_const": a[0], "form": ev(a[1], odd_env) & dat["FORM_MASK"],
                   "is_egg": bool(ev(a[1], odd_env) & dat["IS_EGG_MASK"]),
                   "source": source_ref("data/events/odd_eggs.asm", n)}
            target.append(cur)
        elif start and s.startswith("db ") and cur is not None:
            a = split_args(s[3:])
            if "moves" not in cur:
                cur["moves"] = [ev(x, odd_env) for x in a]
            elif "dvs" not in cur:
                cur["dvs"] = [ev(x, odd_env) for x in a]
            else:
                cur["personality_expr"] = s[3:]
                cur["personality"] = ev(s[3:], odd_env)
    require(len(odd) == len(thr) == odd_c["NUM_ODD_EGGS"], f"odd eggs {len(odd)} / thresholds {len(thr)} != NUM_ODD_EGGS")
    for r, t in zip(odd, thr, strict=True):
        r["threshold"] = t
    gifts_pack = pack("polished-gifts-v1", "gen2-gifts-v1", {
        "gifts": gifts, "npc_trades": trades,
        "odd_eggs": {"applicable": True, "record_length": odd_c["ODD_EGG_LENGTH"], "records": odd,
                      "mystri_egg": mystri[0] if mystri else None},
        "caller_inventory": callers,
        "policies": {"egg_reception_is_capture": False, "hatch_area_id": "gift_daycare"},
        "debug_only_excluded": "if DEF(DEBUG) script blocks (e.g. PlayersHouse2F debug gifts) are not in the standard build",
        "open_obligations": ["wonder_trade_tables:data/events/wonder_trade/*", "source_script_reachability",
                             "success_identity_finalization_and_durability"]})
    statics_pack = pack("polished-static-encounters-v1", "gen2-static-encounters-v1", {
        "encounters": statics,
        "open_obligations": ["runtime_script_reachability", "capture_success_and_finalization"]})
    return gifts_pack, statics_pack


# ----------------------------------------------------------------------------- charmap
def build_charmap():
    """The raw `no_ngrams` charmap (font-level bytes the tables use) plus the n-gram/compression extras."""
    cur, enc, ngram, extra = None, {}, {}, {}
    aliases = {}
    for n, s in lines("constants/charmap.asm"):
        if s.startswith("newcharmap "):
            cur = s.split()[1].rstrip(",")
            continue
        if s.startswith("setcharmap"):
            cur = s.split()[1]
            continue
        m = re.fullmatch(r'(charmap|ctxtmap)\s+("(?:\\.|[^"\\])*")\s*,\s*(\$[0-9a-fA-F]+|\d+)(?:\s*,\s*\d+)?', s)
        if not m:
            continue
        tok, val = json.loads(m[2]), ev(m[3], {})
        target = {"no_ngrams": enc, "compressing": extra, "default": ngram}[cur]
        require(tok not in target, f"charmap {cur}: duplicate token {tok!r}")
        target[tok] = val
        if cur == "no_ngrams":
            aliases.setdefault(val, []).append({"text": tok, "line": n})
    require(enc.get("@") == 0x53, "default text terminator '@' must be $53 in Polished")
    primary = {}
    for b, rows in aliases.items():
        primary[b] = rows[0]["text"]
    text = C.get("text")
    return pack("polished-charmap-v1", "gen2-charmap-v1", {
        "scope": "no_ngrams charmap (raw byte text used by name tables); n-gram/compression charmaps listed separately; "
                 "raw bytes remain authoritative",
        "terminator": enc["@"], "encoding": enc,
        "glyphs": {i: primary.get(i, f"<${i:02X}>") for i in range(256)},
        "aliases": aliases, "excluded_named_charmaps": ["compressing", "default"],
        "context_dependent_bytes": sorted(b for b, rows in aliases.items() if len(rows) > 1),
        "compressing_extras": extra, "ngrams": ngram,
        "lengths": {k.lower(): v for k, v in text.items() if k.endswith("_LENGTH")}})


def render_lua(document: dict) -> bytes:
    def render(value, depth=0):
        if isinstance(value, dict):
            entries = [(f"[{key}]" if type(key) is int else f"[{json.dumps(key, ensure_ascii=False)}]", val)
                       for key, val in value.items()]
        elif isinstance(value, list):
            entries = [(f"[{i}]", val) for i, val in enumerate(value, 1)]
        elif isinstance(value, bool):
            return "true" if value else "false"
        elif value is None:
            return "nil"
        else:
            return json.dumps(value, ensure_ascii=False)
        indent = "  " * (depth + 1)
        return "{\n" + "".join(f"{indent}{k} = {render(v, depth + 1)},\n" for k, v in entries) + "  " * depth + "}"
    return ("-- GENERATED native text facts; raw bytes remain authoritative.\nreturn " + render(document) + "\n").encode("utf-8")


# ----------------------------------------------------------------------------- self-checks (also run by `__main__`)
def encode(text: str, enc: dict[str, int]) -> bytes:
    toks = sorted(enc, key=lambda t: (-len(t), t))
    out = bytearray()
    while text:
        t = next((t for t in toks if text.startswith(t)), None)
        require(t is not None, f"unmapped text near {text!r}")
        out.append(enc[t])
        text = text[len(t):]
    return bytes(out)


def check_charmap(doc):
    enc = doc["encoding"]
    require(doc["terminator"] == 0x53 == enc["@"], "'@' must be $53")
    require(doc["lengths"]["name_length"] == 11, "NAME_LENGTH changed")
    return enc


def check_species(doc, enc):
    c = doc["constants"]
    sp = doc["species"]
    require(len(sp) == c["NUM_POKEMON"], "species rows != NUM_POKEMON")
    require(sorted(int(k) for k in sp) == [i for i in range(1, c["NUM_SPECIES"] + 1) if i not in (c["EGG"], c["EGG"] + 1)],
            "species ids must be 1..NUM_SPECIES minus EGG and the unused 0x100")
    var = [f for f in doc["forms"] if f["kind"] == "variant"]
    cos = [f for f in doc["forms"] if f["kind"] == "cosmetic"]
    require(len(cos) == c["NUM_COSMETIC_FORMS"] and len(var) == c["NUM_VARIANT_FORMS"], "form counts")
    require([f["ext"] for f in var] == list(range(c["NUM_SPECIES"] + 1, c["NUM_SPECIES"] + 1 + len(var))), "variant ext indices")
    require([f["ext"] for f in cos] == list(range(c["NUM_SPECIES"] + 1, c["NUM_SPECIES"] + 1 + len(cos))), "cosmetic ext indices")
    # ROM: PokemonNames order == species ids; BaseData rows == base stats / types / abilities
    names = rom_at("PokemonNames", 10 * (c["NUM_SPECIES"] + 1))
    for k, v in sp.items():
        i = int(k)
        want = encode(v["name"], enc) + bytes([enc["@"]]) * (10 - len(encode(v["name"], enc)))
        require(names[i * 10:(i + 1) * 10] == want, f"PokemonNames[{i}] ROM != {v['name']!r}")
    dat = C.get("data")
    size = dat["BASE_TMHM"] + (C.get("tmhm")["NUM_TM_HM_TUTOR"] + 7) // 8
    base = rom_at("BaseData", size * (c["NUM_SPECIES"] + c["NUM_VARIANT_FORMS"]))
    rows = {int(k): v for k, v in sp.items()} | {f["ext"]: f for f in var}
    for idx, v in rows.items():
        rec = base[(idx - 1) * size:idx * size]
        stats = [v["base_stats"][k] for k in STATS6]
        require(list(rec[:6]) == stats, f"BaseData[{idx}] stats ROM != source")
        require([rec[dat["BASE_TYPE_1"]], rec[dat["BASE_TYPE_2"]]] == v["type_ids"], f"BaseData[{idx}] types")
        require(rec[dat["BASE_CATCH_RATE"]] == v["catch_rate"] and rec[dat["BASE_EXP"]] == v["base_exp"], f"BaseData[{idx}] catch/exp")
        require(list(rec[dat["BASE_ABILITY_1"]:dat["BASE_ABILITY_1"] + 3]) == v["ability_ids"], f"BaseData[{idx}] abilities")
        require(rec[dat["BASE_GROWTH_RATE"]] == v["growth_rate_id"], f"BaseData[{idx}] growth")
    return len(rows)


def check_moves(doc, cm):
    enc = {**cm["encoding"], **cm["compressing_extras"], **cm["ngrams"]}  # `default` charmap: n-grams apply (longest match)
    mv = doc["moves"]
    require(len(mv) == doc["constants"]["NUM_ATTACKS"] == 255, "move rows")
    require([m["id"] for m in mv] == list(range(1, 256)), "move ids")
    table = rom_at("Moves", 8 * len(mv))
    for m in mv:
        rec = bytes([m["animation"], m["effect"], m["power"], m["type_id"], m["accuracy_byte"], m["pp"],
                     m["effect_chance_byte"], m["category_id"]])
        require(table[(m["id"] - 1) * 8:m["id"] * 8] == rec, f"Moves[{m['id']}] ROM != source")
    blob = b"".join(encode(m["name"], enc) + bytes([enc["@"]]) for m in mv)
    require(rom_at("MoveNames", len(blob)) == blob, "MoveNames ROM != source")
    require(len(doc["tmhm"]) == doc["constants"]["NUM_TMS"] + doc["constants"]["NUM_HMS"] + doc["constants"]["NUM_TUTORS"], "tmhm rows")


def check_items(doc, enc):
    items = doc["items"]
    require(len(items) == doc["constants"]["NUM_ITEMS"] == 254, "item rows")
    raw = rom_at("ItemNames", 4000)
    first = raw.index(bytes([enc["@"]]))  # row 0 (NO_ITEM / Park Ball) name
    pos = first + 1
    for i in range(1, 255):
        n = encode(items[str(i)]["name"], enc) + bytes([enc["@"]])
        require(raw[pos:pos + len(n)] == n, f"ItemNames[{i}] ROM != {items[str(i)]['name']!r}")
        pos += len(n)
    idc = parse_consts("constants/item_data_constants.asm")
    size = idc["ITEMATTR_STRUCT_LENGTH"]
    attrs = rom_at("ItemAttributes", size * 254)
    for i in range(1, 255):
        it = items[str(i)]
        rec = attrs[(i - 1) * size:i * size]
        require(int.from_bytes(rec[:2], "little") == it["price"] and rec[2] == it["held_effect"]
                and rec[3] == it["parameter_byte"] and rec[4] == it["pocket_id"]
                and rec[5] == (it["field_menu"] << 4 | it["battle_menu"]), f"ItemAttributes[{i}] ROM != source")
    require(len(doc["key_items"]) == doc["constants"]["NUM_KEY_ITEMS"], "key item rows")
    require(all(items[str(b)]["pocket"] == "BALL" for b in doc["ball_ids"]), "ball_ids")


def check_evolutions(doc):
    labels = [m[1] for _, s in lines("data/pokemon/evos_attacks_pointers.asm") if (m := re.fullmatch(r"dw (\w+)", s))]
    table = rom_at("EvosAttacksPointers", 2 * len(labels))
    sym = rom()[1]
    for i, label in enumerate(labels):
        require(int.from_bytes(table[2 * i:2 * i + 2], "little") == sym[label].address, f"EvosAttacksPointers[{i + 1}] ROM != sym {label}")
    require(all(int(k) in range(1, len(labels) + 1) for k in doc["methods"]), "evolution row index out of range")
    require(set(doc["methods"]) == set(doc["evolutions"]), "evolutions/methods keys differ")


def check_trainers(doc):
    consts = doc["class_constants"]
    require(consts["0"] == "TRAINER_NONE" and len(consts) == doc["constants"]["NUM_TRAINER_CLASSES"] + 1, "class_constants")
    # TrainerClassNames order comments name the class at each row: class id <-> constant must agree
    for i, raw in enumerate((r for r in read("data/trainers/class_names.asm").splitlines() if r.strip().startswith("li ")), 1):
        m = re.search(r";\s*(\w+)\s*$", raw)
        require(m and consts[str(i)] == m[1], f"TrainerClassNames row {i} comment != class {consts[str(i)]}")
    require(len(doc["classes"]) == len(consts), "classes/class_constants sizes differ")
    for cid, d in doc["parties"].items():
        for inst, t in d.items():
            require(t["trainer_id"] == int(cid) * 256 + int(inst) and t["class_id"] == int(cid), f"trainer id {cid}:{inst}")
    r = doc["rival_classes"]
    require(r == {"RIVAL0": 27, "RIVAL1": 28, "RIVAL2": 29, "LYRA1": 30, "LYRA2": 31}, "rival class ids moved")
    return sum(len(d) for d in doc["parties"].values())


def check_encounters(doc):
    w = doc["wild"]
    require(rom_at("GrassMonProbTable", 7) == bytes(r["threshold"] for r in w["grass_probabilities"]), "GrassMonProbTable ROM")
    require(rom_at("WaterMonProbTable", 3) == bytes(r["threshold"] for r in w["water_probabilities"]), "WaterMonProbTable ROM")
    require(rom_at("BadgeBaseLevels", 17) == bytes(w["badge_base_levels"]), "BadgeBaseLevels ROM")
    require(all(len(r["slots"]) == (7 if r in w["grass"] else 3) for r in w["grass"] + w["water"]), "slot counts")
    require(len(doc["roamers"]["maps"]) == 16 and len(doc["fishing"]["groups"]) == 15, "roam/fish tables")


def check_gifts(doc, ids):
    require(len(doc["npc_trades"]) == 9 and len(doc["odd_eggs"]["records"]) == 10, "trade/odd-egg tables")
    consts = {t["trade_const"] for t in doc["npc_trades"]}
    called = {c["trade_const"] for c in doc["caller_inventory"] if c["operation"] == "trade"}
    require(called <= consts, "trade caller names an unknown NPC_TRADE")
    require(all(1 <= g["species"] <= 291 for g in doc["gifts"]), "gift species range")
    return sorted(consts - called)


def check_map_names(doc):
    require(len({m["encoded_id"] for m in doc["maps"].values()}) == len(doc["maps"]), "map ids must be unique")
    n = doc["constants"]["NUM_MAP_GROUPS"]
    table = rom_at("MapGroupPointers", 2 * n)
    sym = rom()[1]
    for g in range(1, n + 1):
        require(int.from_bytes(table[2 * (g - 1):2 * g], "little") == sym[f"MapGroup{g}"].address, f"MapGroupPointers[{g}] ROM != sym")


# ----------------------------------------------------------------------------- CLI
def json_bytes(doc: dict) -> bytes:
    return (json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


KINDS = ("charmap", "species", "moves", "items", "evolutions", "trainers", "encounters", "statics", "gifts", "maps")


def build_all(only):
    docs, checks = {}, {}
    need = lambda k: only is None or k in only  # noqa: E731
    cm = build_charmap()
    enc = check_charmap(cm)
    if need("charmap"):
        docs["charmap.lua"] = render_lua(cm)
    if need("species"):
        d = build_species()
        checks["species"] = f"{check_species(d, enc)} BaseData rows ROM-verified"
        docs["species_index.json"] = json_bytes(d)
    if need("moves"):
        d = build_moves()
        check_moves(d, cm)
        checks["moves"] = "Moves + MoveNames ROM-verified"
        docs["moves.json"] = json_bytes(d)
    if need("items"):
        d = build_items()
        check_items(d, enc)
        checks["items"] = "ItemNames + ItemAttributes ROM-verified"
        docs["items.json"] = json_bytes(d)
    if need("evolutions"):
        d = build_evolutions()
        check_evolutions(d)
        checks["evolutions"] = "EvosAttacksPointers ROM-verified"
        docs["evolutions.json"] = json_bytes(d)
    if need("trainers"):
        d = build_trainers()
        checks["trainers"] = f"{check_trainers(d)} trainers; TrainerGroups ROM-verified"
        docs["trainers.json"] = json_bytes(d)
    if need("encounters"):
        d = build_encounters()
        check_encounters(d)
        checks["encounters"] = "probability/badge tables ROM-verified"
        docs["encounter_tables.json"] = json_bytes(d)
    if need("statics") or need("gifts"):
        g, st = build_gifts_statics()
        uncalled = check_gifts(g, C.get("species_ids"))
        checks["gifts"] = f"trades without a map caller: {uncalled}"
        if need("gifts"):
            docs["gifts.json"] = json_bytes(g)
        if need("statics"):
            docs["static_encounters.json"] = json_bytes(st)
    if need("maps"):
        d = build_map_names()
        check_map_names(d)
        checks["maps"] = "MapGroupPointers ROM-verified"
        docs["map_names.json"] = json_bytes(d)
    return docs, checks


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="compare against the committed files instead of writing")
    ap.add_argument("--only", help="comma list of: " + ",".join(KINDS))
    ap.add_argument("--src", type=Path, help="pinned polishedcrystal checkout")
    args = ap.parse_args(argv)
    global SRC
    if args.src:
        SRC = args.src
    only = set(args.only.split(",")) if args.only else None
    if only and not only <= set(KINDS):
        ap.error(f"unknown kind(s): {sorted(only - set(KINDS))}")
    try:
        verify_source()
        docs, checks = build_all(only)
        for name, data in docs.items():
            path = OUT / name
            if args.check:
                require(path.is_file() and path.read_bytes() == data, f"{path}: stale or missing")
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
    except (ValueError, OSError, KeyError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    for k, v in checks.items():
        print(f"  check {k}: {v}")
    for name, data in docs.items():
        print(f"  {'verified' if args.check else 'wrote'} {name} ({len(data)} bytes)")
    for u in UNPARSED:
        print(f"  UNPARSED: {u}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
