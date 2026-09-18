import re, sys, os

BUILD = r"C:\Users\howar\AppData\Local\Temp\claude\E--Google-Drive-SLink--claude-worktrees-recursing-hopper-86c382\27f97123-cfa0-473c-aed8-f288963eedeb\scratchpad\build"
P = r"C:\Users\howar\AppData\Local\Temp\claude\E--Google-Drive-SLink--claude-worktrees-recursing-hopper-86c382\27f97123-cfa0-473c-aed8-f288963eedeb\scratchpad\purergb"

def flat(bank, addr):
    if bank == 0:
        return addr
    return bank*0x4000 + (addr - 0x4000)

def load_sym(fn=os.path.join(BUILD,"pokered.sym")):
    syms = {}  # name -> (bank,addr)
    by_addr = []  # list of (bank,addr,name) sorted
    with open(fn) as f:
        for line in f:
            line=line.strip()
            if not line or line.startswith(';'):
                continue
            m = re.match(r'^([0-9a-fA-F]+):([0-9a-fA-F]+)\s+(\S+)', line)
            if m:
                bank=int(m.group(1),16); addr=int(m.group(2),16); name=m.group(3)
                syms[name]=(bank,addr)
                by_addr.append((bank,addr,name))
    return syms, by_addr

def rom_bytes(fn=os.path.join(BUILD,"pokered.gbc")):
    with open(fn,'rb') as f:
        return f.read()

def hx(b):
    return ' '.join('%02X'%x for x in b)

def dump(rom, off, n=16):
    return hx(rom[off:off+n])

def find_pattern(rom, pattern, start=0, end=None):
    """pattern: list of ints or None (wildcard)"""
    if end is None: end = len(rom)
    n = len(pattern)
    results = []
    for i in range(start, end-n):
        ok = True
        for j,p in enumerate(pattern):
            if p is not None and rom[i+j] != p:
                ok = False
                break
        if ok:
            results.append(i)
    return results

if __name__ == "__main__":
    syms, by_addr = load_sym()
    rom = rom_bytes()
    print("loaded", len(syms), "syms,", len(rom), "rom bytes")
