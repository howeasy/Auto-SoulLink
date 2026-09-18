"""Audit every pret symbol the vanilla overlay sources reference: is it exported (::) in pureRGB?"""
import re, pathlib, subprocess

OLD = pathlib.Path(r"C:\Users\howar\AppData\Local\Temp\claude\E--Google-Drive-SLink--claude-worktrees-recursing-hopper-86c382\27f97123-cfa0-473c-aed8-f288963eedeb\scratchpad")
W = pathlib.Path(r"E:\Google Drive\SLink\.claude\worktrees\gen1-master-release-plan-6b4279")
P = OLD / "purergb"

defs = (W / "patch/gen1/src/trade_defs.inc").read_text(encoding="utf-8", errors="replace")
syms = set()
for m in re.finditer(r"^DEF\s+(\w+)\s+EQU\s+(\S+)", defs, re.M):
    val = m.group(2)
    if re.match(r"^[A-Za-z_]\w*$", val):
        syms.add(val)
pat = re.compile(r"\b([whs][A-Z]\w+)\b")
for f in ["trade_defs.inc", "slink.asm", "trade_service.asm", "native_trade.asm", "trade_receptionist.asm", "trade_ui.asm", "trade_prompt.asm"]:
    t = (W / "patch/gen1/src" / f).read_text(encoding="utf-8", errors="replace")
    syms.update(pat.findall(t))
syms = sorted(s for s in syms if not s.startswith(("Slink", "SLINK")))

src = subprocess.run(["grep", "-rn", "-E", r"^[A-Za-z_][A-Za-z0-9_]*::?", "--include=*.asm", "."], cwd=P, capture_output=True, text=True, errors="replace").stdout
defmap = {}
for line in src.splitlines():
    m = re.match(r"^\./([^:]+):(\d+):(\w+)(::?)", line)
    if m:
        defmap.setdefault(m.group(3), []).append((m.group(1), m.group(2), m.group(4)))
symfile = (OLD / "build/pokered.sym").read_text(encoding="utf-8", errors="replace")
addr = {m.group(3): m.group(1) + ":" + m.group(2) for m in re.finditer(r"^([0-9a-f]{2}):([0-9a-f]{4}) (\S+)", symfile, re.M)}
missing, local, exported = [], [], []
for s in syms:
    d = defmap.get(s)
    if not d:
        missing.append((s, addr.get(s)))
        continue
    kinds = {k for _, _, k in d}
    (exported if "::" in kinds else local).append((s, d[0][0], d[0][1], addr.get(s)))
print("referenced pret symbols:", len(syms))
print("exported (::):", len(exported))
print("FILE-LOCAL (:) ->")
for x in local:
    print("  ", x)
print("NOT DEFINED in pureRGB source ->")
for x in missing:
    print("  ", x)
out = OLD.parent.parent / "2eefad46-f87d-42d5-a71b-d9e3807a4bb1" / "scratchpad" / "export_audit.txt"
out.write_text("\n".join(["exported:"] + [str(x) for x in exported] + ["local:"] + [str(x) for x in local] + ["missing:"] + [str(x) for x in missing]), encoding="utf-8")
