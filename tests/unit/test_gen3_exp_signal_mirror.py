"""EXP-ROM-MIRROR: the expansion's script handlers run at their 0x0A ROM-mirror alias.

Every `callnative` that requests effects stores `func + ROM_SIZE` (asm/macros/event.inc:273-283;
ROM_SIZE = 0x2000000, constants/gba_constants.inc:33) and every gScriptCmdTable entry is 0x0A-prefixed,
so ScrCmd_createmon -> ... -> GiveScriptedMonToPlayer executes at 0x0A1C2EDC, not 0x081C2EDC. Exec hooks
match the exact PC, so the pack lists `mirror_offsets` per site and lua/gen3/signals.lua hooks both
aliases. Vanilla packs carry no such key and must keep exactly one hook per site.
"""
import json
import os
import struct
from pathlib import Path

import lupa
import pytest

ROOT = Path(__file__).resolve().parents[2]
GEN3_LUA = ROOT / "lua/gen3"
ARTIFACTS = Path(os.environ.get("SLINK_EXPANSION_ARTIFACTS", ROOT / ".cache/expansion-output/reference"))
TITLE = "emerald_expansion_28877d73"
MIRROR = 0x02000000
HEX = "AABBCCDD"
ADDR = 0x08123456


class Fake:
    """Drives lua/gen3/signals.lua directly with a synthetic site and a recording registrar."""

    def __init__(self, **site_extra):
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.hooks = []  # (fn, addr, name)
        self.bus = bytes.fromhex(HEX)
        site = {"address": ADDR, "capture_offset": 4, "expected_hex": HEX, "rom_offset": 0x123456,
                "mode": "thumb", "point": []}
        site.update(site_extra)
        L = self.lua
        io = L.table(rom_read=lambda off, n: L.table(*self.bus[: int(n)]),
                     read_bytes=lambda a, n: L.table(*self.bus[: int(n)]),
                     read_u8=lambda a: 0, read_u16=lambda a: 0, read_u32=lambda a: 0,
                     framecount=lambda: 7, register=lambda n: 0)
        ev = L.table(on_bus_exec=self._reg, unregister=lambda h: None)
        mod = L.eval(f'dofile("{(GEN3_LUA / "signals.lua").as_posix()}")')
        lua_site = L.table(**{k: (L.table(*v) if isinstance(v, list) else v) for k, v in site.items()})
        self.sig = mod.new(L.table(), L.table(kind=lua_site), io, ev)

    def _reg(self, fn, addr, name):
        self.hooks.append((fn, int(addr), str(name)))
        return f"id-{len(self.hooks)}"

    def fire(self, addr):
        for fn, a, _ in self.hooks:
            if a == addr:
                fn(addr)
                return
        # a callback delivered at an address nothing was registered at: use the first hook's fn
        self.hooks[0][0](addr)

    def status(self):
        return dict(self.sig.status(self.sig))

    def drain(self):
        return [dict(s) for s in self.sig.drain(self.sig).values()]


HOOK = ADDR + 4


def test_a_mirrored_site_registers_both_aliases_and_the_mirror_fires_canonically():
    f = Fake(mirror_offsets=[MIRROR])
    assert sorted(a for _, a, _ in f.hooks) == [HOOK, HOOK + MIRROR]
    assert len({n for _, _, n in f.hooks}) == 2, "hook names stay distinguishable"
    assert f.status()["registered"] == 2
    f.fire(HOOK + MIRROR)
    got = f.drain()
    assert len(got) == 1
    assert got[0]["address"] == HOOK, "the signal keeps the canonical 0x08 address"
    assert got[0]["callback_address"] == HOOK + MIRROR, "the real PC is recorded"
    assert f.status()["rejected"] == 0
    f.fire(HOOK)
    assert [s["callback_address"] for s in f.drain()] == [HOOK]


def test_an_unrelated_callback_is_rejected_and_counted_even_on_a_mirrored_site():
    f = Fake(mirror_offsets=[MIRROR])
    f.fire(HOOK + 2)
    f.fire(HOOK + 2 * MIRROR)
    assert f.drain() == []
    assert f.status()["rejected"] == 2
    assert f.status().get("failed") is None


def test_a_site_without_mirror_offsets_is_hooked_once_and_rejects_the_alias():
    f = Fake()
    assert [a for _, a, _ in f.hooks] == [HOOK]
    assert f.status()["registered"] == 1
    f.hooks[0][0](HOOK + MIRROR)
    assert f.drain() == []
    assert f.status()["rejected"] == 1
    f.fire(HOOK)
    assert len(f.drain()) == 1


@pytest.mark.parametrize("bad", ["notatable", 7, ["x"], [-1], [0], [1, "2"]])
def test_a_malformed_mirror_offsets_fails_named_and_arms_nothing(bad):
    """A pack with a broken alias list must be a named refusal BEFORE arming, so the existing
    rollback path is never reached and no hook exists to leak."""
    with pytest.raises(Exception, match="mirror_offsets must be a list of positive numbers"):
        Fake(mirror_offsets=bad)


def test_a_missing_mirror_offsets_key_is_still_the_plain_old_path():
    f = Fake()
    assert [a for _, a, _ in f.hooks] == [HOOK]
    assert f.status()["registered"] == 1


def _packs():
    out = {}
    for name in ("gen3_frlg", "gen3_rr", "gen3_emerald"):
        pack = json.loads((ROOT / f"data/games/{name}/engine_signals.json").read_text(encoding="utf-8"))
        out[name] = pack
    return out


def _all_sites(pack):
    for title in pack["titles"].values():
        for artifact in title["artifacts"].values():
            yield from artifact["sites"].items()


def test_the_expansion_pack_mirrors_every_site():
    pack = json.loads((ROOT / "data/games/gen3_exp/28877d73/engine_signals.json").read_text(encoding="utf-8"))
    sites = pack["titles"][TITLE]["artifacts"]["clean"]["sites"]
    assert sites
    for kind, site in sites.items():
        assert site["mirror_offsets"] == [MIRROR], kind
    assert "ROM_SIZE" in pack["mirror_contract"] and "gba_constants.inc:33" in pack["mirror_contract"]


def test_vanilla_packs_are_neutral_by_shape():
    for name, pack in _packs().items():
        count = 0
        for kind, site in _all_sites(pack):
            count += 1
            assert "mirror_offsets" not in site, (name, kind)
            assert "pairing" not in site, (name, kind)
            if kind == "hatch":
                assert site["point"] == ["R5"], (name, kind)
        assert count and "mirror_contract" not in pack, name


def test_rom_witness_the_beldum_script_calls_a_0x0a_mirrored_createmon():
    gba, sym = ARTIFACTS / "pokeemerald.gba", ARTIFACTS / "pokeemerald.sym"
    if not (gba.is_file() and sym.is_file()):
        pytest.skip("reference expansion ROM absent")
    rom = gba.read_bytes()
    syms = {}
    for line in sym.read_text().splitlines():
        parts = line.split()
        if len(parts) == 4:
            syms[parts[3]] = int(parts[0], 16)
    script = syms["MossdeepCity_StevensHouse_EventScript_GiveBeldum"]
    createmon = syms["ScrCmd_createmon"]
    assert script == 0x082C8300 and createmon == 0x081FDEC8
    body = rom[script - 0x08000000:script - 0x08000000 + 0x34]
    at = body.index(b"\x23\xc9\xde\x1f\x0a")  # SCR_OP_CALLNATIVE + operand
    operand = struct.unpack("<I", body[at + 1:at + 5])[0]
    assert operand == (createmon | 1) + MIRROR == 0x0A1FDEC9
    # the whole command table is mirrored, not just this call
    table = syms["gScriptCmdTable"] - 0x08000000
    ptrs = struct.unpack("<231I", rom[table:table + 231 * 4])
    assert all(p >> 24 == 0x0A for p in ptrs)
