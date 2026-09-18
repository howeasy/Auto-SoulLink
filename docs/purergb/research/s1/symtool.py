import re, sys, json, os

BUILD = r"C:\Users\howar\AppData\Local\Temp\claude\E--Google-Drive-SLink--claude-worktrees-recursing-hopper-86c382\27f97123-cfa0-473c-aed8-f288963eedeb\scratchpad\build"
TITLES = ["red", "blue", "green"]
FILES = {t: f"poke{t}" for t in TITLES}

def load_sym(path):
    """Return dict label -> (bank,addr) and dict (bank,addr)->[labels] and locals resolved to Parent.local"""
    sym = {}
    cur_parent = None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(";"):
                continue
            m = re.match(r"^([0-9A-Fa-f]+):([0-9A-Fa-f]+)\s+(\S+)", line)
            if not m:
                continue
            bank = int(m.group(1), 16)
            addr = int(m.group(2), 16)
            label = m.group(3)
            if label.startswith("."):
                if cur_parent:
                    full = cur_parent + label
                else:
                    full = label
            else:
                cur_parent = label
                full = label
            sym[full] = (bank, addr)
    return sym

def rom_offset(bank, addr):
    if addr < 0x4000:
        return addr
    return bank * 0x4000 + (addr - 0x4000)

def load_rom(path):
    with open(path, "rb") as f:
        return f.read()

class Title:
    def __init__(self, name):
        self.name = name
        base = FILES[name]
        self.sym = load_sym(os.path.join(BUILD, base + ".sym"))
        self.rom = load_rom(os.path.join(BUILD, base + ".gbc"))

    def resolve(self, label, offset=0):
        if label not in self.sym:
            return None
        bank, addr = self.sym[label]
        # offset may cross into next bank only if small; assume same bank (typical for code)
        eff_addr = addr + offset
        eff_bank = bank
        # if addr overflows 0x4000-0x7FFF window (bank area), it stays same bank unless spills past 0x8000
        rom_off = rom_offset(bank, addr) + offset
        return {
            "symbol": label,
            "bank": bank,
            "address": addr,
            "eff_address": eff_addr,
            "offset": offset,
            "rom_offset": rom_off,
        }

    def bytes_at(self, rom_off, n=8):
        return self.rom[rom_off:rom_off+n]

def hexstr(b):
    return " ".join(f"{x:02X}" for x in b)

if __name__ == "__main__":
    titles = {t: Title(t) for t in TITLES}
    for t in TITLES:
        print(t, len(titles[t].sym), "symbols")
