"""Gen 1 foundations: where a generator finds a foundation's symbols, source and ROMs.

A *foundation* is a Gen 1 code base SLink generates game facts from: pret's pokered
(vanilla red/blue/yellow) or Vortyne's pureRGB (purered/pureblue/puregreen). Every
tools/gen_gen1_*.py takes ``--foundation`` and resolves paths through this module so
no generator hard-codes data/pret or data/games/gen1_rby.

Env overrides (an existing checkout or build dir; nothing is cloned here):
    SLINK_PURERGB_SRC   pureRGB checkout at the locked commit (default .cache/purergb)
    SLINK_PURERGB_ROMS  dir holding the built pokered/pokeblue/pokegreen.gbc (default = SRC)
    SLINK_PRET_SRC      pret/pokered checkout (default .cache/pret/pokered)
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess

REPO = pathlib.Path(__file__).resolve().parent.parent

FOUNDATIONS: dict[str, dict] = {
    "pret": {
        "data_dir": "data/games/gen1_rby",
        "sym_dir": "data/pret",
        # title -> (sym file, built ROM file, source repo key)
        "titles": {
            "red": ("pokered.sym", "pokered.gbc", "pokered"),
            "blue": ("pokeblue.sym", "pokeblue.gbc", "pokered"),
            "yellow": ("pokeyellow.sym", "pokeyellow.gbc", "pokeyellow"),
        },
        "source_env": "SLINK_PRET_SRC",
        "source_default": ".cache/pret/pokered",
        "roms_env": "SLINK_PRET_ROMS",
        "lock": None,
    },
    "purergb": {
        "data_dir": "data/games/gen1_purergb",
        "sym_dir": "data/purergb",
        "titles": {
            "purered": ("pokered.sym", "pokered.gbc", "purergb"),
            "pureblue": ("pokeblue.sym", "pokeblue.gbc", "purergb"),
            "puregreen": ("pokegreen.sym", "pokegreen.gbc", "purergb"),
        },
        "source_env": "SLINK_PURERGB_SRC",
        "source_default": ".cache/purergb",
        "roms_env": "SLINK_PURERGB_ROMS",
        "lock": "data/purergb_sources.lock.json",
    },
    # The SLink companion overlay built over pureRGB (tools/build_purergb_overlay.py): the same
    # source family and data dir, its own .sym/.map (data/purergb/*_slink.*), ROMs (the overlay
    # build tree) and lock (the overlay provenance, which carries `source` + `outputs` in the
    # lock's shape). Generators write its pack files with the `_overlay` suffix (out_path).
    "purergb_overlay": {
        "family": "purergb",
        "data_dir": "data/games/gen1_purergb",
        "sym_dir": "data/purergb",
        "titles": {
            "purered": ("purered_slink.sym", "pokered.gbc", "purergb"),
            "pureblue": ("pureblue_slink.sym", "pokeblue.gbc", "purergb"),
            "puregreen": ("puregreen_slink.sym", "pokegreen.gbc", "purergb"),
        },
        "source_env": "SLINK_PURERGB_OVERLAY_SRC",
        "source_default": ".cache/purergb-overlay",
        "roms_env": "SLINK_PURERGB_OVERLAY_ROMS",
        "lock": "data/purergb/overlay_provenance.json",
        "out_suffix": "_overlay",
    },
}

_SYM = re.compile(r"^([0-9A-Fa-f]{2,3}):([0-9A-Fa-f]{4}) (\S+)$")


def foundation(name: str) -> dict:
    if name not in FOUNDATIONS:
        raise SystemExit(f"unknown foundation {name!r}; one of {sorted(FOUNDATIONS)}")
    return FOUNDATIONS[name]


def data_dir(name: str) -> pathlib.Path:
    return REPO / foundation(name)["data_dir"]


def family(name: str) -> str:
    """The source family a foundation derives from ("purergb" for both pure kinds)."""
    return foundation(name).get("family", name)


def with_kind(name: str, kind: str) -> str:
    """`--kind overlay` on a generator selects the `<foundation>_overlay` foundation."""
    return name if kind == "clean" else f"{name}_{kind}"


def out_path(name: str, filename: str) -> pathlib.Path:
    """A generator's output in the data dir, suffixed for a non-clean kind (profile_overlay.json)."""
    stem, ext = filename.rsplit(".", 1)
    return data_dir(name) / f"{stem}{foundation(name).get('out_suffix', '')}.{ext}"


def sym_path(name: str, title: str) -> pathlib.Path:
    return REPO / foundation(name)["sym_dir"] / foundation(name)["titles"][title][0]


def parse_sym(path: pathlib.Path) -> dict[str, tuple[int, int]]:
    """{symbol: (bank, addr)} from an rgblink .sym file (locals included)."""
    out: dict[str, tuple[int, int]] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _SYM.match(line.strip())
        if m:
            out[m.group(3)] = (int(m.group(1), 16), int(m.group(2), 16))
    return out


def flat(bank: int, addr: int) -> int:
    return addr if addr < 0x4000 else bank * 0x4000 + (addr - 0x4000)


def lock(name: str) -> dict | None:
    f = foundation(name)
    return json.loads((REPO / f["lock"]).read_text(encoding="utf-8")) if f["lock"] else None


def source_root(name: str) -> pathlib.Path:
    """The foundation's source checkout; for a locked foundation HEAD must equal the lock."""
    f = foundation(name)
    root = pathlib.Path(os.environ.get(f["source_env"]) or (REPO / f["source_default"]))
    if not root.is_dir():
        raise SystemExit(f"{name} source checkout not found at {root} (set {f['source_env']})")
    lk = lock(name)
    if lk:
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
        if head != lk["source"]["commit"]:
            raise SystemExit(f"{name} source at {root} is {head[:12]}, lock wants {lk['source']['commit'][:12]}")
    return root


def rom_path(name: str, title: str) -> pathlib.Path:
    f = foundation(name)
    roms = pathlib.Path(os.environ.get(f["roms_env"]) or source_root(name))
    p = roms / f["titles"][title][1]
    if not p.is_file():
        raise SystemExit(f"built ROM for {name}/{title} not found at {p} (set {f['roms_env']})")
    return p


def read_source(name: str, rel: str) -> str:
    return (source_root(name) / rel).read_text(encoding="utf-8", errors="replace")


def assert_source(name: str, rel: str, needle: str) -> None:
    """Fail loudly when the pinned source no longer contains the text a site row was derived from."""
    if needle not in read_source(name, rel):
        raise SystemExit(f"source assert failed: {name}:{rel} lacks {needle!r}")


if __name__ == "__main__":  # ponytail: smallest self-check
    import sys
    n = sys.argv[1] if len(sys.argv) > 1 else "purergb"
    for t in foundation(n)["titles"]:
        syms = parse_sym(sym_path(n, t))
        print(t, len(syms), "symbols; OverworldLoop", syms.get("OverworldLoop"))
    print("source", source_root(n))
