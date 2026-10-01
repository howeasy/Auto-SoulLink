"""lua/gen4/entry.lua: hash-first admission, the vanilla ARM9 anchors, admit_routed, build.

Real packs (data/games/gen4_{hgss,hge,pt}/profile.json) supply the pinned md5/sha1 and the anchor
bytes. The ROM images are MODELS: a fake ARM9 RAM keyed by address, laid out from the HG pack's
arm9 site bytes (vanilla) and, for hge, with the hge pack's redirected entry bytes
(`replaces.vanilla_entry_hex`) over the arm9 functions hge replaces (FILE evidence in the pack).
"""

from __future__ import annotations

import json
from pathlib import Path

import lupa
import pytest

ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "lua/gen4/entry.lua"
DOC = {p: json.loads((ROOT / f"data/games/gen4_{p}/profile.json").read_text(encoding="utf-8"))
       for p in ("hgss", "hge", "pt")}
HG = DOC["hgss"]["titles"]["heartgold"]
SS = DOC["hgss"]["titles"]["soulsilver"]
HGE = DOC["hge"]["titles"]["heartgold_hge"]
PT = DOC["pt"]["titles"]["platinum"]


HOOK_SITE = 0x02000CD0  # hg-engine's Main() hook: the one anchor hge overwrites


def arm9_vanilla() -> dict[int, bytes]:
    img = {s["address"]: bytes.fromhex(s["register_hex"]) for s in HG["sites"].values()
           if s["image"] == "arm9" and s.get("register_hex")}
    img.update({a["address"]: bytes.fromhex(a["hex"]) for a in HG["admission_anchors"]})  # FILE bytes entry.lua compares
    return img


def arm9_hge() -> dict[int, bytes]:
    img = arm9_vanilla()
    for s in HGE["sites"].values():
        r = s.get("replaces")
        if r and r["vanilla_image"] == "arm9":
            img[r["vanilla_address"]] = bytes.fromhex(r["vanilla_entry_hex"])
    img[HOOK_SITE] = bytes.fromhex(HGE["admission_check"]["hge_hex"])
    return img


def test_hge_image_behind_an_hg_hash_is_refused_by_the_hook_site_anchor(env):
    """Only the 0x02000CD0 anchor differs for hge among the pack anchors, so that is what refuses it."""
    assert HGE["admission_check"]["address"] == HOOK_SITE
    image = arm9_vanilla()
    image[HOOK_SITE] = arm9_hge()[HOOK_SITE]
    row, why = env.admit(HG["rom"]["sha1"], "IPKE", image)
    assert HG["admission_anchors"][0]["address"] == HOOK_SITE  # the refusal names anchor [1] = the hook site
    assert row is None and "admission_anchors[1] does not match" in why


def test_models_actually_differ():
    """The hge model must differ from vanilla on the anchors, or the refusal tests prove nothing."""
    assert sum(arm9_hge()[a] != b for a, b in arm9_vanilla().items()) >= 5


class Env:
    def __init__(self, src: str | None = None):
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        load = self.lua.eval("function(s, n) return assert(load(s, n))() end")
        self.entry = load(src if src is not None else ENTRY.read_text(encoding="utf-8"), "=entry")
        self.json = self.lua.eval(f'dofile("{(ROOT / "lua/json_codec.lua").as_posix()}")')

    def ram(self, image: dict[int, bytes]):
        def read(addr, n):
            for a, b in image.items():
                if a <= addr and addr + n <= a + len(b):
                    return self.lua.table_from(list(b[addr - a : addr - a + n]))
            return None
        return self.lua.eval("function(f) return function(a, n) return f(a, n) end end")(read)  # a real Lua function

    def args(self, rom_hash, header, image=None, **extra):
        t = {"root": ROOT.as_posix(), "json": self.json, "rom_hash": rom_hash, "header_code": header}
        if image is not None:
            t["read_ram"] = self.ram(image)
        t.update(extra)
        return self.lua.table_from(t)

    def admit(self, *a, **k):
        return self.entry.admit(self.args(*a, **k))

    def admit_routed(self, *a, **k):
        return self.entry.admit_routed(self.args(*a, **k))


@pytest.fixture(scope="module")
def env():
    return Env()


def fields(row):
    return {k: row[k] for k in ("pack", "title", "rom_type", "admitted_by")}


# -- admission ------------------------------------------------------------------------------
@pytest.mark.parametrize("key", ["md5", "sha1"])
def test_hg_admitted_by_md5_and_sha1(env, key):
    row = env.admit(HG["rom"][key], "IPKE", arm9_vanilla())
    assert fields(row) == {"pack": "gen4_hgss", "title": "heartgold", "rom_type": "heartgold", "admitted_by": "hash"}


def test_hash_is_case_insensitive(env):
    assert env.admit(HG["rom"]["sha1"].upper(), "IPKE", arm9_vanilla())["title"] == "heartgold"


def test_ss_admitted(env):
    row = env.admit(SS["rom"]["sha1"], "IPGE", arm9_vanilla())
    assert (row["pack"], row["title"]) == ("gen4_hgss", "soulsilver")


@pytest.mark.parametrize("key", ["md5", "sha1"])
def test_hge_admitted_by_hash_only(env, key):
    # no read_ram at all: hge never runs the vanilla anchors
    assert fields(env.admit(HGE["rom"][key], "IPKE")) == {
        "pack": "gen4_hge", "title": "heartgold_hge", "rom_type": "heartgold_hge", "admitted_by": "hash"}


def test_hge_rom_is_never_admitted_as_vanilla(env):
    # an hge image behind the vanilla HG hash (mislabelled / mis-hashed): the anchors refuse it
    row, why = env.admit(HG["rom"]["sha1"], "IPKE", arm9_hge())
    assert row is None and "anchor check failed" in why and "vanilla" in why


def test_hge_with_vanilla_header_and_unknown_hash_is_unpinned(env):
    row, why = env.admit("0" * 40, "IPKE", arm9_hge())
    assert row is None and "unpinned build" in why and "never assumed vanilla" in why


def test_unknown_hash_with_vanilla_bytes_is_still_refused(env):
    # a patched/unknown build whose anchors happen to be vanilla is not admitted by anchors
    row, why = env.admit("f" * 40, "IPKE", arm9_vanilla())
    assert row is None and "unpinned build" in why


def test_empty_hash_refused(env):
    row, why = env.admit("", "IPKE", arm9_vanilla())
    assert row is None and "unpinned" in why


def test_platinum_is_bind_only(env):
    for key in ("md5", "sha1"):
        row, why = env.admit(PT["rom"][key], "CPUE", arm9_vanilla())
        assert row is None and "bind-only" in why


def test_header_must_match_the_pinned_title(env):
    row, why = env.admit(HG["rom"]["sha1"], "IPGE", arm9_vanilla())
    assert row is None and "header IPGE" in why


def test_vanilla_needs_read_ram_and_unreadable_ram_refuses(env):
    assert "needs read_ram" in env.admit(HG["rom"]["sha1"], "IPKE")[1]
    row, why = env.admit(HG["rom"]["sha1"], "IPKE", {})  # nothing resident (ARM9 not loaded yet)
    assert row is None and "unreadable" in why


def test_single_anchor_byte_flip_refuses(env):
    image = arm9_vanilla()
    addr = next(iter(image))
    image[addr] = bytes([image[addr][0] ^ 1]) + image[addr][1:]
    row, why = env.admit(HG["rom"]["sha1"], "IPKE", image)
    assert row is None and "does not match" in why


def test_pack_admission_anchors_are_enforced(env):
    # the pack gap (no 0x02000CD0 bytes yet): when a pack carries `admission_anchors` they are checked
    doc = json.loads(json.dumps(DOC["hgss"]))
    doc["titles"]["heartgold"]["admission_anchors"] = [{"address": 0x02000CD0, "hex": "deadbeef"}]
    packs = env.lua.table_from({"gen4_hgss": env.json.decode(json.dumps(doc)),
                                "gen4_hge": env.json.decode(json.dumps(DOC["hge"])),
                                "gen4_pt": env.json.decode(json.dumps(DOC["pt"]))})
    image = arm9_vanilla()
    row, why = env.admit(HG["rom"]["sha1"], "IPKE", image, packs=packs)
    assert row is None and "admission_anchors[1]" in why
    image[0x02000CD0] = bytes.fromhex("deadbeef")
    assert env.admit(HG["rom"]["sha1"], "IPKE", image, packs=packs)["title"] == "heartgold"


def test_duplicate_digest_is_a_hard_error(env):
    doc = json.loads(json.dumps(DOC["hge"]))
    doc["titles"]["heartgold_hge"]["rom"]["sha1"] = HG["rom"]["sha1"]
    packs = env.lua.table_from({"gen4_hgss": env.json.decode(json.dumps(DOC["hgss"])),
                                "gen4_hge": env.json.decode(json.dumps(doc)),
                                "gen4_pt": env.json.decode(json.dumps(DOC["pt"]))})
    with pytest.raises(lupa.LuaError, match="duplicate sha1"):
        env.admit(HG["rom"]["sha1"], "IPKE", arm9_vanilla(), packs=packs)


def test_header_code_reads_0x0c(env):
    rom = env.lua.eval('function(off, n) assert(off == 0x0C and n == 4); return {73, 80, 75, 69} end')
    assert env.entry.header_code(rom) == "IPKE"


# -- the launcher gate ---------------------------------------------------------------------
def test_admit_routed_passes_routed_packs(env):
    assert env.admit_routed(HG["rom"]["sha1"], "IPKE", arm9_vanilla())["pack"] == "gen4_hgss"
    assert env.admit_routed(HGE["rom"]["sha1"], "IPKE")["pack"] == "gen4_hge"


def test_admit_routed_refuses_an_unrouted_pack_and_passes_admit_refusals_through(env):
    routed = env.entry.ROUTED
    routed["gen4_hge"] = None
    try:
        row, why = env.admit_routed(HGE["rom"]["sha1"], "IPKE")
        assert row is None and "not yet routed" in why
        # a direct admit() is NOT the launcher gate: it still admits (proves the gate is the wrapper)
        assert env.admit(HGE["rom"]["sha1"], "IPKE")["pack"] == "gen4_hge"
    finally:
        routed["gen4_hge"] = True
    row, why = env.admit_routed("0" * 40, "IPKE", arm9_hge())
    assert row is None and "unpinned" in why


# -- build ---------------------------------------------------------------------------------
def test_build_binds_the_per_title_modules(env):
    mem = bytearray(0x400000)

    def rd(size):
        return lambda a: int.from_bytes(mem[a - 0x02000000 : a - 0x02000000 + size], "little")

    parts = env.entry.build(env.lua.table_from({
        "root": ROOT.as_posix(), "pack": "gen4_hge", "title": "heartgold_hge",
        "mem": env.lua.table_from({"u8": rd(1), "u16": rd(2), "u32": rd(4)}),
        "encounter_active": lambda: False,
    }))
    assert (parts["pack"], parts["title"]) == ("gen4_hge", "heartgold_hge")
    assert env.lua.eval("function(p) return p.reads.pk4 == p.pk4 and p.pk4 ~= nil end")(parts)
    for k in ("safety", "nds", "phase_signals"):
        assert parts[k] is not None
    assert parts["nds"]["new"] is not None and parts["phase_signals"]["new"] is not None
    assert parts["safety"].checkpoint(parts["safety"])[1] == "no_new_frame"


def test_build_refuses_platinum_and_unknown_packs(env):
    base = {"root": ROOT.as_posix(), "title": "platinum", "mem": env.lua.table_from({}),
            "encounter_active": lambda: False}
    with pytest.raises(lupa.LuaError, match="bind-only"):
        env.entry.build(env.lua.table_from({**base, "pack": "gen4_pt"}))
    with pytest.raises(lupa.LuaError, match="unknown pack"):
        env.entry.build(env.lua.table_from({**base, "pack": "gen4_nope"}))


# -- revert tests: each guard is load-bearing -----------------------------------------------
def _mutate(old: str, new: str) -> str:
    src = ENTRY.read_text(encoding="utf-8")
    assert src.count(old) == 1, old
    return src.replace(old, new)


def test_revert_anchor_guard_goes_red():
    mutant = Env(_mutate("if row.anchors then", "if false then"))
    row = mutant.admit(HG["rom"]["sha1"], "IPKE", arm9_hge())
    assert row is not None and row["title"] == "heartgold"  # mutant admits hge as vanilla; the real one refuses


def test_revert_routed_guard_goes_red():
    mutant = Env(_mutate("if not Entry.ROUTED[admitted.pack] then", "if false then"))
    mutant.entry.ROUTED["gen4_hge"] = None
    assert mutant.admit_routed(HGE["rom"]["sha1"], "IPKE") is not None  # the real one refuses (test above)


def test_revert_bind_only_guard_goes_red():
    mutant = Env(_mutate("if row.bind_only then", "if false then"))
    row = mutant.admit(PT["rom"]["sha1"], "CPUE", arm9_vanilla())
    assert row is not None and row["pack"] == "gen4_pt"  # mutant admits Platinum; the real one refuses (D3)
