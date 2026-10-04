"""`lua/slink.lua`'s NDS block: the Gen 4 route (G3a; docs/gen4/reviews/DECISIONS_2026-10-03_launcher.md).

The launcher's only observable is the path it dofile's, so `lua/slink.lua` runs under lupa with
BizHawk's globals stubbed and the assertions are on that path -- the technique (and the stub set)
of `tests/unit/test_slink_route.py`. `lua/gen4/entry.lua`, `lua/gen4/client.lua` and
`lua/json_codec.lua` are dofile'd for REAL, and `game_detect` is required for real too, so
admission, the vanilla ARM9 anchor check, the by-name refusal and the Gen 5 fall-through are the
shipped logic rather than a restatement of it. Every other dofile target is recorded and skipped,
so no client ever starts.

Cartridges are MODELS, as in `tests/unit/test_gen4_entry_lua.py`: the pinned digest and header code
come from the packs' own `titles.<t>.rom`, and the ARM9 RAM image is built from the very site and
admission-anchor bytes `Entry.anchor_failure` compares. The NDS header copy (ROM offset 0 -> main
RAM 0x027FFE00, GBATEK "DS Cartridge Header") is modelled the same way, and BizHawk's "Main RAM"
domain -- base 0x02000000, which is why the legacy Gen 5 module reads 0x3FFE0C
(`lua/games/gen5_bw.lua:77,103`) -- is modelled on top of it, so the header the launcher reads and
the code the Gen 5 detector reads are the same four bytes.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa", reason="lupa is needed to execute the launcher")

_REPO = Path(__file__).resolve().parents[2]
_LUA = (_REPO / "lua").as_posix()
_SLINK = f"{_LUA}/slink.lua"
_GEN4_RUN = "lua/gen4/run.lua"
_GEN5_CLIENT = "lua/clients/gen5_bw_client.lua"
_OLD_GEN4_CLIENT = "lua/clients/gen4_hgsspt_client.lua"  # deleted with the G3a cutover

HEADER_COPY = 0x027FFE00          # GBATEK: the NDS boot copies the cart header to main RAM here
MAIN_RAM_BASE = 0x02000000        # so BizHawk's "Main RAM" domain address A is DS address BASE + A
_BANNER = "-- ── Gen 4 route"     # the NDS block's own banner; the red control cuts on it
_TAIL = "-- Detect which game is loaded"

_DOCS = {
    pack: json.loads((_REPO / f"data/games/{pack}/profile.json").read_text(encoding="utf-8"))
    for pack in ("gen4_hgss", "gen4_hge", "gen4_pt")
}
HG = _DOCS["gen4_hgss"]["titles"]["heartgold"]
SS = _DOCS["gen4_hgss"]["titles"]["soulsilver"]
HGE = _DOCS["gen4_hge"]["titles"]["heartgold_hge"]
PT = _DOCS["gen4_pt"]["titles"]["platinum"]


def _put(image: dict[int, int], addr: int, hex_bytes: str) -> None:
    for i, byte in enumerate(bytes.fromhex(hex_bytes)):
        image[addr + i] = byte


def _arm9_vanilla(title: dict) -> dict[int, int]:
    """Every ARM9 byte run entry.lua compares for a vanilla (HG/SS) title: the arm9 sites and the
    pack's own admission anchors, keyed by RAM address. Built from the pack, so the anchor check
    the route depends on is the real one."""
    image: dict[int, int] = {}
    for site in title.get("sites", {}).values():
        if site.get("image") == "arm9" and site.get("register_hex") and site.get("address"):
            _put(image, site["address"], site["register_hex"])
    for anchor in title.get("admission_anchors", []):
        _put(image, anchor["address"], anchor["hex"])
    return image


def _run_launcher(rom_hash: str, header_code: str, ram: dict[int, int] | None = None,
                  bizhawk: str = "2.11.1", loaded: list[str] | None = None,
                  launcher_source: str | None = None) -> list[str]:
    """Run `lua/slink.lua` against a modelled NDS cartridge; return the repo-relative paths it
    dofile'd. Pass `loaded` to keep the list when the launcher refuses (the error leaves dofile)."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    g = lua.globals()
    g.package.path = f"{_LUA}/?.lua;{_LUA}/?/init.lua;" + g.package.path
    if loaded is None:
        loaded = []

    ram = dict(ram or {})
    for i, byte in enumerate(header_code.encode("ascii")):
        ram[HEADER_COPY + 0x0C + i] = byte          # the header copy the boot leaves in main RAM
    rom = bytes(0x200)                              # no NDS route reads ROM bytes; a guard, not a cartridge

    def read_u8(addr, domain=None):
        if domain == "ARM9 System Bus":
            return ram.get(addr, 0)
        if domain == "Main RAM":
            # the 4 MiB main RAM mirrors through 0x02000000-0x02FFFFFF: legacy Gen 5 reads the header copy at
            # domain offset 0x3FFE0C, which is DS address 0x027FFE0C folded into the first window
            return ram.get(addr + MAIN_RAM_BASE, ram.get(addr + MAIN_RAM_BASE + 0x400000, 0))
        return rom[addr] if 0 <= addr < len(rom) else 0

    def read_u32_le(addr, domain=None):
        b = [read_u8(addr + i, domain) for i in range(4)]
        return b[0] | (b[1] << 8) | (b[2] << 16) | (b[3] << 24)

    def norm(path: str) -> str:
        return os.path.relpath(os.path.normpath(path), str(_REPO)).replace("\\", "/")

    real_dofile = g.dofile
    _REAL_TARGETS = ("gen4/entry.lua", "gen4/client.lua", "json_codec.lua")

    def fake_dofile(path):
        rel = norm(path)
        loaded.append(rel)
        if rel.endswith(_REAL_TARGETS):
            return real_dofile(path)
        return None

    g.dofile = fake_dofile
    g.emu = lua.table_from({"getsystemid": lambda: "NDS"})
    g.client = lua.table_from({"getversion": lambda: bizhawk})
    g.gameinfo = lua.table_from({"getromhash": lambda: rom_hash})  # md5 or sha1; both are pinned
    g.memory = lua.table_from({"read_u8": read_u8, "read_u32_le": read_u32_le})
    g.console = lua.table_from({"log": lambda *a: None})
    # Only the console-tee's own log file is stubbed away (it would truncate slink_lua.log in the
    # repo root); admission reads the real pack JSON through io.open, so everything else is real.
    real_io_open = g.io.open

    def fake_io_open(path, *a):
        if str(path).endswith("slink_lua.log"):
            return None
        return real_io_open(path, *a)

    g.io.open = fake_io_open

    if launcher_source is None:
        real_dofile(_SLINK)
    else:
        # The chunk name carries the real path, so the launcher's own _dir (package.path, the
        # dofile'd targets, the log path) is the one it has in BizHawk.
        lua.eval("function(s, n) return assert(load(s, n))() end")(launcher_source, "@" + _SLINK)
    return loaded


def _without_nds_block() -> str:
    """`lua/slink.lua` with the Gen 4 route block removed (its banner up to the game_detect seam)."""
    src = Path(_SLINK).read_text(encoding="utf-8")
    start, end = src.index(_BANNER), src.index(_TAIL)
    assert start < end
    return src[:start] + src[end:]


def _no_client_was_loaded(loaded: list[str]) -> None:
    assert _GEN4_RUN not in loaded, loaded
    assert _GEN5_CLIENT not in loaded, loaded
    assert _OLD_GEN4_CLIENT not in loaded, loaded


# ── a pinned Gen 4 cartridge reaches lua/gen4/run.lua ─────────────────────────

@pytest.mark.parametrize("title", [HG, SS], ids=["heartgold", "soulsilver"])
def test_a_pinned_heartgold_or_soulsilver_reaches_the_gen4_client(title):
    """HGSS is the vanilla pack: admission is the pinned digest AND the static-ARM9 anchors."""
    loaded = _run_launcher(title["rom"]["md5"], title["rom"]["header_code"], _arm9_vanilla(title))
    assert _GEN4_RUN in loaded, loaded


@pytest.mark.parametrize("key", ["md5", "sha1"])
def test_hg_admits_by_either_pinned_digest(key):
    """BizHawk's getromhash() is the md5 for gamedb ROMs and the sha1 otherwise, so both pin."""
    loaded = _run_launcher(HG["rom"][key], HG["rom"]["header_code"], _arm9_vanilla(HG))
    assert _GEN4_RUN in loaded, loaded


def test_the_hg_engine_build_is_routed_by_hash_alone():
    """The hge pack ships no ARM9 admission anchors (its arm9 entries are redirected), so its
    admission is the digest -- and a cartridge with no ARM9 image at all must still be routed."""
    loaded = _run_launcher(HGE["rom"]["sha1"], HGE["rom"]["header_code"])
    assert _GEN4_RUN in loaded, loaded


def test_only_one_client_is_ever_loaded_for_an_admitted_gen4_cartridge():
    loaded = _run_launcher(HG["rom"]["sha1"], HG["rom"]["header_code"], _arm9_vanilla(HG))
    clients = [p for p in loaded if p.endswith("/run.lua") or p.startswith("lua/clients/")]
    assert clients == [_GEN4_RUN], f"expected exactly one client, got {clients}"


def test_an_old_bizhawk_on_an_admitted_gen4_cartridge_is_refused():
    with pytest.raises(lupa.LuaError, match="too old"):
        _run_launcher(HG["rom"]["sha1"], HG["rom"]["header_code"], _arm9_vanilla(HG), bizhawk="2.9.1")


# ── refusals, by name, before game_detect ────────────────────────────────────

@pytest.mark.parametrize("header", [HG["rom"]["header_code"], SS["rom"]["header_code"],
                                    HGE["rom"]["header_code"]], ids=["IPKE", "IPGE", "IPKE-hge"])
def test_a_recognised_but_unpinned_gen4_cartridge_is_refused_by_name(header):
    """Hash-first admission: a Gen 4 header with no pinned digest is an unpinned build and is
    refused here. The legacy client that used to catch it is deleted, and game_detect holds no
    Gen 4 module any more, so there is nothing to fall through to."""
    loaded: list[str] = []
    with pytest.raises(lupa.LuaError, match=r"Unsupported Gen 4 cartridge \(header " + header
                                             + r"\):.*unpinned build"):
        _run_launcher("f" * 32, header, loaded=loaded)
    _no_client_was_loaded(loaded)


def test_an_hg_hash_behind_a_wrong_header_is_refused_rather_than_routed():
    """A pinned digest whose header does not match the pinned title: entry.lua names both."""
    loaded: list[str] = []
    with pytest.raises(lupa.LuaError,
                       match="header IPGE does not match the pinned heartgold header IPKE"):
        _run_launcher(HG["rom"]["sha1"], "IPGE", _arm9_vanilla(HG), loaded=loaded)
    _no_client_was_loaded(loaded)


def test_platinum_is_refused_by_name_and_is_never_offered_as_supported():
    """The Platinum pack is bind-only (D3): its cartridge is named as refused, and the supported
    list that follows never advertises it."""
    loaded: list[str] = []
    with pytest.raises(lupa.LuaError,
                       match=r"Unsupported Gen 4 cartridge \(header CPUE\).*bind-only") as err:
        _run_launcher(PT["rom"]["md5"], PT["rom"]["header_code"], loaded=loaded)
    refusal, _, supported = str(err.value).partition("Supported on NDS:")
    assert "bind-only" in refusal and "Platinum" not in supported, str(err.value)
    assert "HeartGold, SoulSilver and the hg-engine HeartGold build" in supported
    _no_client_was_loaded(loaded)


def test_an_unknown_nds_cartridge_is_refused_without_advertising_platinum():
    """No Gen 4 header and no Gen 5 code: game_detect refuses it by name, and the message names
    only the routes that exist."""
    loaded: list[str] = []
    with pytest.raises(lupa.LuaError, match="No game module matched the loaded ROM") as err:
        _run_launcher("f" * 32, "ZZZZ", loaded=loaded)
    message = str(err.value)
    assert "Platinum" not in message and "platinum" not in message, message
    assert "Black / White / Black 2 / White 2" in message, message
    _no_client_was_loaded(loaded)


# ── the preserved Gen 5 route, and the red control ────────────────────────────

def test_gen5_bw_still_falls_through_to_game_detect():
    """Black's code pins no Gen 4 header, so the NDS block declines it and game_detect -- the only
    registry left -- routes it to the legacy Gen 5 client, unchanged."""
    loaded = _run_launcher("f" * 32, "IRBO")
    assert _GEN5_CLIENT in loaded, loaded
    assert _GEN4_RUN not in loaded, loaded


def test_removing_the_nds_block_stops_heartgold_from_reaching_the_gen4_client():
    """Red control: with the Gen 4 route deleted, a pinned HG cartridge is no longer routed -- it
    falls through to a registry that holds no Gen 4 module and is refused there."""
    loaded: list[str] = []
    with pytest.raises(lupa.LuaError, match="No game module matched the loaded ROM"):
        _run_launcher(HG["rom"]["sha1"], HG["rom"]["header_code"], _arm9_vanilla(HG),
                      loaded=loaded, launcher_source=_without_nds_block())
    assert _GEN4_RUN not in loaded, loaded
