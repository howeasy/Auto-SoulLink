import re, json, os

BUILD = r"C:\Users\howar\AppData\Local\Temp\claude\E--Google-Drive-SLink--claude-worktrees-recursing-hopper-86c382\27f97123-cfa0-473c-aed8-f288963eedeb\scratchpad\build"
OUT = os.path.dirname(os.path.abspath(__file__))
TITLES = ["red", "blue", "green"]
FILES = {t: f"poke{t}" for t in TITLES}

def parse_summary(lines):
    out = {}
    for line in lines:
        m = re.match(r"\s*(\w+):\s*(\d+) bytes used / (\d+) free(?: in (\d+) banks)?", line)
        if m:
            out[m.group(1)] = {
                "used": int(m.group(2)), "free": int(m.group(3)),
                "banks": int(m.group(4)) if m.group(4) else None,
            }
    return out

def get_block(lines, start_pat, end_pats):
    out = []
    capture = False
    for line in lines:
        if re.match(start_pat, line):
            capture = True
            continue
        if capture and any(re.match(p, line) for p in end_pats):
            break
        if capture:
            out.append(line.rstrip("\n"))
    return out

def empties(block_lines):
    return [l.strip() for l in block_lines if "EMPTY" in l]

result = {}
for t in TITLES:
    path = os.path.join(BUILD, FILES[t] + ".map")
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    # SUMMARY block: lines 2..8ish, until blank line
    summary_lines = []
    started = False
    for line in lines:
        if line.startswith("SUMMARY:"):
            started = True
            continue
        if started:
            if line.strip() == "":
                break
            summary_lines.append(line)
    summary = parse_summary(summary_lines)

    rom0 = get_block(lines, r"^ROM0 bank #0:", [r"^ROMX bank #1:"])
    romx_3d = get_block(lines, r"^ROMX bank #61:", [r"^ROMX bank #62:", r"^SRAM bank"])
    has_3e = any(re.match(r"^ROMX bank #62:", l) for l in lines)
    has_3f = any(re.match(r"^ROMX bank #63:", l) for l in lines)
    wram0 = get_block(lines, r"^WRAM0 bank #0:", [r"^WRAMX bank #1:"])
    wramx1 = get_block(lines, r"^WRAMX bank #1:", [r"^WRAMX bank #2:"])
    wramx2 = get_block(lines, r"^WRAMX bank #2:", [r"^HRAM bank"])
    hram = get_block(lines, r"^HRAM bank #0:", [r"^$"])

    result[t] = {
        "summary": summary,
        "rom0_empty": empties(rom0),
        "romx_3d_empty": empties(romx_3d),
        "romx_3e_present": has_3e,
        "romx_3f_present": has_3f,
        "wram0_empty": empties(wram0) or ["(none -- fully used)"],
        "wramx_bank1_empty": empties(wramx1),
        "wramx_bank2_empty": empties(wramx2),
        "hram_empty": empties(hram) or ["(none -- fully used)"],
    }

with open(os.path.join(OUT, "map_summary.json"), "w") as f:
    json.dump(result, f, indent=2)

print(json.dumps(result, indent=2))
