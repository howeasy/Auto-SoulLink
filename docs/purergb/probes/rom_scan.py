"""Free-space scan of the three built pureRGB ROMs (BPS-applied release builds)."""
import hashlib
import pathlib

here = pathlib.Path(__file__).parent
for name in ("purered_2.7.6.gbc", "pureblue_2.7.6.gbc", "puregreen_2.7.6.gbc"):
    data = (here / name).read_bytes()
    print(f"== {name} size={len(data):#x} sha1={hashlib.sha1(data).hexdigest()}")
    nbanks = len(data) // 0x4000
    # per-bank: last nonzero byte + count of zero bytes + all-zero
    for b in range(nbanks):
        bank = data[b * 0x4000:(b + 1) * 0x4000]
        stripped = bank.rstrip(b"\x00")
        last = len(stripped) - 1
        if not stripped:
            print(f"  bank {b:02X}: ALL ZERO")
        elif len(bank) - len(stripped) >= 0x100 or b == 0:
            print(f"  bank {b:02X}: last nonzero {last:#06x}, free tail {len(bank) - len(stripped):#x} bytes")
    # ROM0 zero runs >= 16
    rom0 = data[:0x4000]
    runs = []
    i = 0
    while i < len(rom0):
        if rom0[i] == 0:
            j = i
            while j < len(rom0) and rom0[j] == 0:
                j += 1
            if j - i >= 16:
                runs.append((i, j - 1, j - i))
            i = j
        else:
            i += 1
    print("  ROM0 zero runs >=16:", ", ".join(f"{a:#06x}-{b:#06x} ({n})" for a, b, n in runs))
    # also 0xFF runs in ROM0 (rgbfix pads with 0x00 by default via -p 0x00)
    print("  header title:", data[0x134:0x144].rstrip(b"\x00"), "cgb", hex(data[0x143]), "cart", hex(data[0x147]), "rom", hex(data[0x148]), "ram", hex(data[0x149]))
