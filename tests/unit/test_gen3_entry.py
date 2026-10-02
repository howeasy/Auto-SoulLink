"""gen3-P3-C3-1 (MODEL): the Gen 3 composition root, driven under lupa exactly as a
bootstrap drives it.

`lua/gen3/entry.lua` is loaded and `Entry.build` is called over a fake BizHawk io/ev pair;
the ROM is a sparse table seeded from the pack's own `engine_signals.json`, so no cartridge
dump is needed. This module also carries the shared harness (`World`, `lua_to_py`) that
`test_gen3_reads.py` and `test_gen3_signals.py` import.
"""
from __future__ import annotations

import json
import pathlib
import shutil

import lupa
import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
ENTRY = (REPO / "lua" / "gen3" / "entry.lua").as_posix()
GEN3_LUA = REPO / "lua" / "gen3"
FIXTURES = REPO / "tests" / "fixtures" / "gen3"

PACKS = {
    "gen3_frlg": REPO / "data" / "games" / "gen3_frlg",
    "gen3_rr": REPO / "data" / "games" / "gen3_rr",
    # Registered in Entry.PACKS/Entry.PACK_FILES (E2-ENTRY) and, as of EG4, also in
    # Entry.ROUTED (see test_gen3_emerald_entry.py); Entry.artifacts()/admission_table() open
    # it unconditionally regardless, so the anchor- and hash-coverage tests below must
    # exercise it too (F4/F13).
    "gen3_emerald": REPO / "data" / "games" / "gen3_emerald",
    # X3: registered (not routed, not admitted); one directory per onboarded expansion build
    "gen3_exp": REPO / "data" / "games" / "gen3_exp" / "28877d73",
}


def pack_json(pack: str, name: str) -> dict:
    return json.loads((PACKS[pack] / name).read_text(encoding="utf-8"))


def sites_of(pack: str, title: str, kind: str) -> dict:
    titles = pack_json(pack, "engine_signals.json")["titles"]
    if title not in titles:
        return {}          # an unadmitted title ships no artifact at all
    return titles[title]["artifacts"][kind]["sites"]


def artifact_of(pack: str, title: str, kind: str) -> dict:
    return pack_json(pack, "engine_signals.json")["titles"][title]["artifacts"][kind]


def profile_of(pack: str, title: str) -> dict:
    return pack_json(pack, "profile.json")["titles"][title]


def seed_rom(sites: dict, header_code: str = "BPRE") -> dict[int, int]:
    """A sparse ROM: every site's expected bytes at its rom_offset, plus the GBA header."""
    rom = {0xA0 + i: ord(c) for i, c in enumerate("POKEMON FIRE")}
    rom.update({0xAC + i: ord(c) for i, c in enumerate(header_code)})
    for site in sites.values():
        for i, byte in enumerate(bytes.fromhex(site["expected_hex"])):
            rom[site["rom_offset"] + i] = byte
    return rom


def lua_to_py(value):
    """Recursively convert a lupa table into a list (1..n dense) or a dict."""
    if lupa.lua_type(value) != "table":
        return value
    items = list(value.items())
    keys = [k for k, _ in items]
    if not keys:
        return []          # Lua cannot tell an empty list from an empty map
    if all(isinstance(k, int) for k in keys) and sorted(keys) == list(
            range(1, len(keys) + 1)):
        return [lua_to_py(value[i]) for i in range(1, len(keys) + 1)]
    return {k: lua_to_py(v) for k, v in items}


class World:
    """Fake BizHawk for lua/gen3: a sparse ROM, a sparse bus and a fake event registrar."""

    def __init__(self, pack="gen3_rr", title="radical_red", kind="clean", rom=None,
                 build=True, on_fire=None):
        self.pack, self.title, self.kind = pack, title, kind
        self.sites = sites_of(pack, title, "clean" if kind == "named" else kind)
        self.profile = profile_of(pack, title) if title in pack_json(
            pack, "profile.json")["titles"] else {}
        self.rom = seed_rom(self.sites) if rom is None else dict(rom)
        self.bus: dict[int, int] = {}
        self.frame = 0
        self.regs = {"R13": 0x03007F00, "R15": 0, "CPSR": 0x6000003F}
        self.hooks: dict[str, tuple] = {}
        self.registered: list[str] = []
        self.unregistered: list[str] = []
        self.next_id = 1
        self.id_hook = None          # optional callable(index) -> id, to forge a bad one
        self.logs: list[str] = []
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        L = self.lua
        self.io = L.table(
            read_u8=lambda a: self._read(int(a), 1),
            read_u16=lambda a: self._read(int(a), 2),
            read_u32=lambda a: self._read(int(a), 4),
            read_bytes=self._read_bytes,
            rom_read=self._rom_read,
            framecount=lambda: self.frame,
            register=lambda name: self.regs.get(str(name), 0),
        )
        self.ev = L.table(on_bus_exec=self._on_bus_exec, unregister=self._unregister)
        self.Entry = L.eval(f'dofile("{ENTRY}")')
        self.Reads = L.eval(f'dofile("{(GEN3_LUA / "reads.lua").as_posix()}")')
        self.client = self.parts = None
        if build:
            self.client, self.parts = self.Entry.build(self.deps(on_fire=on_fire))

    def deps(self, **over):
        table = {"root": REPO.as_posix(), "io": self.io, "ev": self.ev, "pack": self.pack,
                 "title": self.title, "kind": self.kind, "mode": "observer",
                 "log": lambda t: self.logs.append(str(t))}
        table.update({k: v for k, v in over.items() if v is not None})
        return self.lua.table(**table)

    # -- BizHawk fakes -----------------------------------------------------------------
    def _read(self, addr, size):
        return sum(self.bus.get(addr + i, 0) << (8 * i) for i in range(size))

    def _read_bytes(self, addr, length):
        addr = int(addr)
        return self.lua.table(*[self.bus.get(addr + i, 0) for i in range(int(length))])

    def _rom_read(self, offset, length):
        offset = int(offset)
        return self.lua.table(*[self.rom.get(offset + i, 0) for i in range(int(length))])

    def _on_bus_exec(self, fn, addr, name):
        index = len(self.registered)
        hid = self.id_hook(index) if self.id_hook else f"id-{self.next_id:04d}"
        self.next_id += 1
        self.hooks[str(name)] = (fn, int(addr))
        self.registered.append(str(hid))
        return hid

    def _unregister(self, hid):
        self.unregistered.append(str(hid))

    # -- helpers -----------------------------------------------------------------------
    def poke(self, addr: int, data: bytes) -> None:
        for i, byte in enumerate(data):
            self.bus[addr + i] = byte

    def fire(self, kind: str, address=None):
        fn, addr = self.hooks[f"SLink-gen3-{kind}"]
        fn(addr if address is None else address)


def test_admission_by_hash_covers_every_shipped_artifact():
    world = World(build=False)
    for pack, title, kinds in (("gen3_frlg", "firered", ["clean"]),
                               ("gen3_frlg", "leafgreen", ["clean"]),
                               ("gen3_rr", "radical_red", ["clean", "companion"]),
                               ("gen3_emerald", "emerald", ["clean"])):
        for kind in kinds:
            artifact = artifact_of(pack, title, kind)
            for digest in ("rom_sha1", "rom_md5"):
                got = lua_to_py(world.Entry.admit(world.lua.table(
                    root=REPO.as_posix(), json=world.lua.eval(
                        f'dofile("{(REPO / "lua" / "json_codec.lua").as_posix()}")'),
                    rom_hash=artifact[digest].upper())))
                assert got["admitted_by"] == "hash"
                assert (got["pack"], got["title"], got["kind"]) == (pack, title, kind)


def _admit(world, **args):
    json_codec = world.lua.eval(
        f'dofile("{(REPO / "lua" / "json_codec.lua").as_posix()}")')
    table = {"root": REPO.as_posix(), "json": json_codec}
    table.update(args)
    return world.Entry.admit(world.lua.table(**table))


@pytest.mark.parametrize("title,code", [("firered", "BPRE"), ("leafgreen", "BPGE")])
def test_admission_by_anchors_when_the_hash_is_unknown(title, code):
    world = World(pack="gen3_frlg", title=title, build=False)
    got = lua_to_py(_admit(world, rom_hash="00" * 20, rom_read=world._rom_read,
                           header_code=code))
    assert got["admitted_by"] == "anchors"
    assert (got["pack"], got["title"], got["kind"]) == ("gen3_frlg", title, "rand")
    assert got["rom_type"] == title


@pytest.mark.parametrize("kind", ["clean", "companion"])
def test_rr_anchor_admission_keeps_its_existing_kind(kind):
    world = World(pack="gen3_rr", title="radical_red", kind=kind, build=False)
    got = lua_to_py(_admit(world, rom_hash="00" * 20, rom_read=world._rom_read))
    assert got["kind"] == kind and got["admitted_by"] == "anchors"


def test_rand_routes_through_the_single_gate_and_uses_clean_sites():
    world = World(pack="gen3_frlg", title="firered", build=False)
    codec = world.lua.eval(f'dofile("{(REPO / "lua/json_codec.lua").as_posix()}")')
    args = world.lua.table(root=REPO.as_posix(), json=codec,
        rom_hash="00" * 20, rom_read=world._rom_read, header_code="BPRE")
    # the bare admission still names the artifact; the LAUNCHER gate refuses a clean rand build
    # (patch-first, owner 2026-10-02: FireRed requires the companion)
    assert world.Entry.admit(args).kind == "rand"
    got, why = world.Entry.admit_routed(args)
    assert got is None and "needs the SLink companion patch" in why
    world.kind = "rand"
    _observer, parts = world.Entry.build(world.deps())
    assert parts.kind == "rand" and parts.artifact_kind == "clean"


def test_admission_by_anchors_when_the_hash_is_unknown_for_emerald():
    """F4: mirrors test_admission_by_anchors_when_the_hash_is_unknown above -- a seeded Emerald
    ROM with an unrecognized hash still admits by anchors alone (E2-ENTRY:
    Entry.artifacts()/anchor_matches() open gen3_emerald unconditionally; since EG4 it is also
    in Entry.ROUTED, same as gen3_frlg/gen3_rr)."""
    world = World(pack="gen3_emerald", title="emerald", build=False)
    got = lua_to_py(_admit(world, rom_hash="00" * 20, rom_read=world._rom_read,
                           header_code="BPEE"))
    assert got["admitted_by"] == "anchors"
    assert (got["pack"], got["title"], got["kind"]) == ("gen3_emerald", "emerald", "rand")
    assert got["rom_type"] == "emerald"


def test_anchors_alone_separate_every_shipped_artifact():
    """The shipped packs are mutually discriminating: a ROM seeded from one artifact's
    sites matches that artifact and no other. This is what makes the anchor pass a real
    admission test rather than a coin flip."""
    world = World(build=False)
    every = [(pack, title, kind)
             for pack in PACKS
             for title, tv in pack_json(pack, "engine_signals.json")["titles"].items()
             for kind in tv["artifacts"]]
    for pack, title, kind in every:
        rom = seed_rom(sites_of(pack, title, kind))

        def rom_read(offset, length, rom=rom):
            return world.lua.table(*[rom.get(int(offset) + i, 0)
                                     for i in range(int(length))])

        matches = lua_to_py(world.Entry.anchor_matches(world.lua.table(
            root=REPO.as_posix(), rom_read=rom_read,
            json=world.lua.eval(
                f'dofile("{(REPO / "lua" / "json_codec.lua").as_posix()}")'))))
        assert [(m["pack"], m["title"], m["kind"]) for m in matches] == [(pack, title, kind)]


def test_admission_table_refuses_a_duplicate_digest(tmp_path):
    """G5-ADMIT-HARDEN: two artifact rows sharing one digest must be a hard error at table
    build, naming both rows -- not a silent last-write-wins (Lua's pairs() order is
    unspecified, so the row that silently won would be nondeterministic)."""
    # PACKS (F4/F13) now includes gen3_emerald itself -- Entry.artifacts() opens every pack in
    # Entry.PACKS unconditionally, so the doctored tmp_path tree needs it too, and this loop
    # already covers it (no separate copytree call for it).
    for source in PACKS.values():
        shutil.copytree(source, tmp_path / source.relative_to(REPO))
    doctored = tmp_path / "data" / "games" / "gen3_frlg" / "engine_signals.json"
    blob = json.loads(doctored.read_text(encoding="utf-8"))
    dupe = blob["titles"]["firered"]["artifacts"]["clean"]["rom_sha1"]
    blob["titles"]["leafgreen"]["artifacts"]["clean"]["rom_sha1"] = dupe
    doctored.write_text(json.dumps(blob), encoding="utf-8")

    world = World(pack="gen3_frlg", title="firered", build=False)
    json_codec = world.lua.eval(
        f'dofile("{(REPO / "lua" / "json_codec.lua").as_posix()}")')
    with pytest.raises(lupa.LuaError) as excinfo:
        world.Entry.admission_table(tmp_path.as_posix(), json_codec)
    message = str(excinfo.value)
    assert "duplicate" in message and dupe in message
    assert "gen3_frlg/firered/clean" in message and "gen3_frlg/leafgreen/clean" in message


def test_admission_table_has_no_duplicate_digest_in_the_shipped_packs():
    """Guard the committed artifact data itself (data/games/gen3_frlg and gen3_rr
    engine_signals.json), not just the code path above: `admission_table` now raises on the
    first duplicate digest it finds, so simply building it over the real, unmodified packs
    IS the assertion that none of their rom_sha1/rom_md5 pins collide."""
    world = World(build=False)
    json_codec = world.lua.eval(
        f'dofile("{(REPO / "lua" / "json_codec.lua").as_posix()}")')
    table = lua_to_py(world.Entry.admission_table(REPO.as_posix(), json_codec))
    assert len(table) > 0


@pytest.mark.parametrize("other_pack,other_title", (("gen3_frlg", "leafgreen"), ("gen3_emerald", "emerald")))
def test_admission_refuses_an_ambiguous_rom(tmp_path, other_pack, other_title):
    """Two artifacts that pin the same bytes cannot be told apart, so admission refuses
    instead of picking one. The shipped packs are not ambiguous (see the test above), so
    the branch is exercised against a doctored copy of the pack tree."""
    # PACKS (F4/F13) now includes gen3_emerald itself -- Entry.artifacts() opens every pack in
    # Entry.PACKS unconditionally, so the doctored tmp_path tree needs it too, and this loop
    # already covers it (no separate copytree call for it).
    for source in PACKS.values():
        shutil.copytree(source, tmp_path / source.relative_to(REPO))
    doctored = tmp_path / "data" / "games" / other_pack / "engine_signals.json"
    blob = json.loads(doctored.read_text(encoding="utf-8"))
    source = json.loads((PACKS["gen3_frlg"] / "engine_signals.json").read_text(encoding="utf-8"))
    blob["titles"][other_title]["artifacts"]["clean"]["sites"] = \
        source["titles"]["firered"]["artifacts"]["clean"]["sites"]
    doctored.write_text(json.dumps(blob), encoding="utf-8")

    world = World(pack="gen3_frlg", title="firered", build=False)
    rom = seed_rom(sites_of("gen3_frlg", "firered", "clean"))
    got, why = _admit(world, root=tmp_path.as_posix(), rom_hash="ff" * 20,
                      header_code="BPRE",
                      rom_read=lambda o, n: world.lua.table(
                          *[rom.get(int(o) + i, 0) for i in range(int(n))]))
    assert got is None
    assert "ambiguous" in why
    assert "gen3_frlg/firered/clean" in why and f"{other_pack}/{other_title}/clean" in why


def test_named_family_fallback_by_header_code():
    """An unknown FireRed build whose bytes match nothing still routes to the vanilla pack
    by its header code, as kind `named`; the site check refuses it later if it really is a
    different game."""
    world = World(pack="gen3_frlg", title="firered", build=False)
    blank = {0xAC + i: ord(c) for i, c in enumerate("BPGE")}
    got = lua_to_py(_admit(world, rom_hash="ab" * 20, header_code="BPGE",
                           rom_read=lambda o, n: world.lua.table(
                               *[blank.get(int(o) + i, 0) for i in range(int(n))])))
    assert got["admitted_by"] == "header"
    assert (got["pack"], got["title"], got["kind"]) == ("gen3_frlg", "leafgreen", "named")


def test_admission_refuses_an_unknown_cartridge():
    world = World(build=False)
    got, why = _admit(world, rom_hash="cd" * 20, header_code="AXVE")
    assert got is None
    assert "AXVE" in why and "not an admitted Gen 3 cartridge" in why


def test_header_code_and_title_come_from_the_gba_header():
    world = World(build=False)
    assert str(world.Entry.header_code(world._rom_read)) == "BPRE"
    assert str(world.Entry.header_title(world._rom_read)) == "POKEMON FIRE"


@pytest.mark.parametrize("pack,title,kind", [
    ("gen3_frlg", "firered", "clean"),
    ("gen3_frlg", "leafgreen", "clean"),
    ("gen3_rr", "radical_red", "clean"),
    ("gen3_rr", "radical_red", "companion"),
])
def test_build_wires_reads_and_signals_for_every_artifact(pack, title, kind):
    world = World(pack=pack, title=title, kind=kind)
    assert world.client is None, "observer mode has no client until P4"
    parts = world.parts
    assert parts.pack == pack and parts.title == title and parts.kind == kind
    assert parts.mode == "observer"
    assert parts.reads is not None and parts.signals is not None
    assert parts.profile.ram is not None
    assert len(world.registered) == len(world.sites)
    assert parts.rom_type == {"firered": "firered", "leafgreen": "leafgreen",
                              "radical_red": "firered_rr"}[title]


def test_build_maps_the_named_kind_onto_the_clean_artifact():
    world = World(pack="gen3_frlg", title="firered", kind="named")
    assert world.parts.artifact_kind == "clean"
    assert world.parts.kind == "named"


def test_build_refuses_and_arms_nothing_when_a_site_is_not_in_the_rom():
    sites = sites_of("gen3_rr", "radical_red", "clean")
    rom = seed_rom(sites)
    rom[sites["save"]["rom_offset"]] ^= 0xFF
    world = World(rom=rom, build=False)
    with pytest.raises(lupa.LuaError) as excinfo:
        world.Entry.build(world.deps())
    assert "engine sites differ from the ROM" in str(excinfo.value)
    assert "save" in str(excinfo.value)
    assert world.registered == [], "a refused build must arm nothing"


def test_build_refuses_a_mode_that_is_not_a_gen3_build_mode():
    world = World(build=False)
    with pytest.raises(lupa.LuaError, match="not a Gen 3 build mode"):
        world.Entry.build(world.deps(mode="shadow"))


# ── production mode (P4 C4-2b) ─────────────────────────────────────────────────────────

def _production(world, **over):
    L = world.lua
    world.io.write_u8 = lambda a, v: None
    net = L.table(connected=lambda: False, pump=lambda: None, send=lambda line: None,
                  receive=lambda: None)
    hud = L.table(show=lambda *a: None, prompt=lambda *a: None)
    return world.Entry.build(world.deps(mode="production", net=net, hud=hud, player="a", **over))


@pytest.mark.parametrize("pack,title,kind", [
    ("gen3_frlg", "firered", "clean"),
    ("gen3_frlg", "leafgreen", "clean"),
    ("gen3_rr", "radical_red", "clean"),
    ("gen3_rr", "radical_red", "companion"),
    ("gen3_emerald", "emerald", "clean"),
])
def test_production_build_returns_a_client_and_arms_no_hook_until_start(pack, title, kind):
    world = World(pack=pack, title=title, kind=kind, build=False)
    client, parts = _production(world)
    assert client is not None and parts.mode == "production"
    assert parts.writes is not None and parts.policy is not None and parts.safety is not None
    assert world.registered == [], "signals are built by client:start(), not by the build"
    client.start(client)
    assert len(world.registered) == len(world.sites)


def test_production_start_refuses_by_name_when_a_site_is_not_in_the_rom():
    sites = sites_of("gen3_frlg", "firered", "clean")
    rom = seed_rom(sites)
    rom[sites["faint"]["rom_offset"]] ^= 0xFF
    world = World(pack="gen3_frlg", title="firered", rom=rom, build=False)
    client, _ = _production(world)
    with pytest.raises(lupa.LuaError, match="engine sites differ from the ROM: faint"):
        client.start(client)
    assert world.registered == []


def test_production_refuses_a_read_only_io():
    world = World(pack="gen3_frlg", title="firered", build=False)
    with pytest.raises(lupa.LuaError, match="production io needs write_u8"):
        world.Entry.build(world.deps(mode="production"))


def test_each_reason_reaches_safety_check_with_the_real_pack_clauses():
    """C4-7: the policy is a pass-through. Every reason evaluates the PACK's own clause set (the
    refusal names a clause that only exists in the pack), and the args reach the guard."""
    world = World(pack="gen3_frlg", title="firered", build=False)
    _, parts = _production(world)
    policy = parts.policy
    ok, why = policy.check(policy, world.lua.table(), "overworld")
    assert ok is False and "anchor" in why          # the preamble ran, so safety was reached
    for reason in ("battle_faint", "battle_commit"):
        ok, why = policy.check(policy, world.lua.table(), reason)
        assert ok is False
        # safety's own refusal: either a pack clause name or its anchor preamble -- never the
        # old entry.lua stub ("no <reason> predicate ... yet (C4-B)"), which no longer exists.
        assert "safety.lua" in why and "C4-B" not in why, why
    ok, why = policy.check(policy, world.lua.table(), "memorial_rename")
    assert ok is False and "unknown write reason" in why


def test_an_overworld_and_a_battle_refusal_hold():
    """The client treats a refusal as a HOLD: the pack clauses decide, and the guard is
    fail-closed on a missing battler (so an explode cannot write until the client passes one)."""
    world = World(pack="gen3_frlg", title="firered")
    _, parts = _production(world)
    policy = parts.policy
    # seed the checkpoint's own ROM anchors, or safety refuses in its preamble and the clauses
    # under test are never evaluated
    anchors = pack_json("gen3_frlg", "write_checkpoint.json")["firered"]["anchors"]
    for a in anchors.values():
        hexs = a["expected_hex"]["clean"]
        for i in range(a["length"]):
            world.rom[a["rom_offset"] + i] = int(hexs[i * 2:i * 2 + 2], 16)
    # seed the battle clause set in the fake bus so only the guard decides
    guard = parts.write_checkpoint["battle"]["commit_guard"]
    for slot in range(4):                       # the guard shares gBattleCommunication with
        world.poke(guard["address"] + slot, b"\0")   # battle_comm_0, so seed it FIRST
    clauses = world.lua.eval("function(p) return p.battle.clauses end")(parts.write_checkpoint)
    for i in range(1, len(clauses) + 1):
        c = clauses[i]
        value = 1 if c["compare"] == "nonzero" else c["expect"]
        world.poke(c["address"] + (c["offset"] or 0), int(value).to_bytes(c["width"], "little"))
    ok, why = policy.check(policy, world.lua.table(), "battle_commit")
    assert ok is False and "battler" in why                     # fail-closed without args
    # the guard accepts a valid battler (checked at the safety seam; the policy pass-through is
    # asserted above and in test_gen3_safety.py)
    ok, why = parts.safety.check(parts.safety, world.lua.table(), "battle_commit",
                                 world.lua.eval("function() return { battler = 1 } end")())
    assert ok is True, why
    ok, why = policy.check(policy, world.lua.table(), "overworld")
    assert ok is False, "an overworld arm inside the fake world must still refuse (no real state)"


def _seed_native_world(world, busy=None):
    """An RR companion production client with its checkpoint ROM anchors and mailbox seeded.

    `busy` = None (idle), "opcode" or "status". The mailbox words come from the pack's own native
    block, so this cannot drift from what lua/gen3/native.lua reads.
    """
    checkpoint = pack_json("gen3_rr", "write_checkpoint.json")["radical_red"]
    for a in checkpoint["anchors"].values():
        hexs = a["expected_hex"]["companion"]
        for i in range(a["length"]):
            world.rom[a["rom_offset"] + i] = int(hexs[i * 2:i * 2 + 2], 16)
    n = checkpoint["native"]
    world.poke(n["base"], n["sig"].to_bytes(4, "little"))
    world.poke(n["base"] + n["abi_off"], n["abi"].to_bytes(2, "little"))
    world.poke(n["base"] + n["opcode_off"], b"\x00\x00")
    world.poke(n["base"] + n["status_off"], b"\x02\x00")           # ST_OK, not ST_BUSY
    world.poke(n["info"] + n["info_drawn_off"], b"\x01")
    world.poke(n["info"] + n["info_ack_off"], b"\x01")
    if busy == "opcode":
        world.poke(n["base"] + n["opcode_off"], (16).to_bytes(2, "little"))   # OP_SET_ENEMY_PARTY
    elif busy == "status":
        world.poke(n["base"] + n["status_off"], n["busy"].to_bytes(2, "little"))
    return n


def test_one_native_instance_answers_safety_the_client_and_the_part():
    """Codex REV2 hold (C4-7 addendum): the client's service, Safety's native_idle and the writes
    policy must all read the SAME native part. An idle mailbox answers "not busy" in all three; a
    busy one refuses in all three -- if entry.lua had left Safety's closure nil (the reported
    bug), Safety would keep reporting idle while the real part was busy.
    """
    world = World(pack="gen3_rr", title="radical_red", kind="companion", build=False)
    client, parts = _production(world)
    assert parts.native_present is True, "an RR companion production build must own a native part"
    _seed_native_world(world)

    # positive control: the idle mailbox accepts everywhere
    assert parts.native.idle(parts.native) is True
    ok, why = parts.safety.check(parts.safety, None, "native")
    assert ok is True, why
    assert list(parts.safety.last_clauses.values()) == []

    for busy in ("opcode", "status"):
        _seed_native_world(world, busy=busy)
        assert parts.native.idle(parts.native) is False, busy
        ok, why = parts.safety.check(parts.safety, None, "native")
        assert ok is False and "mailbox" in str(why), why
        assert list(parts.safety.last_clauses.values()) == ["native_idle"], busy
        # the client's own gate refuses too -- and its refusal now names the native clause
        # (in the fake world the pointer snapshot is nil, so the durable evidence is the safety
        # seam; checkpoint_ok returning false is the client-side half)
        assert client.driver.checkpoint_ok(client.driver)[0] is False, busy
        parts.safety.check(parts.safety, None, "overworld")
        clauses = list(parts.safety.last_clauses.values())
        assert "native" in clauses, (busy, clauses)


@pytest.mark.parametrize("busy", ["opcode", "status"])
def test_a_busy_mailbox_makes_the_overworld_checkpoint_refuse_only_for_native(busy):
    """The delta: with the rest of the fake overworld in the state the harness leaves it, the
    ONLY clause a busy mailbox adds to `checkpoint_ok`'s refusal is "native" -- which is what
    proves the client and Safety share the instance."""
    world = World(pack="gen3_rr", title="radical_red", kind="companion", build=False)
    client, parts = _production(world)
    _seed_native_world(world)
    parts.safety.check(parts.safety, None, "overworld")
    idle = list(parts.safety.last_clauses.values())
    _seed_native_world(world, busy=busy)
    parts.safety.check(parts.safety, None, "overworld")
    busy_clauses = list(parts.safety.last_clauses.values())
    assert set(busy_clauses) - set(idle) == {"native"}, (idle, busy_clauses)
    assert set(idle) - set(busy_clauses) == set(), (idle, busy_clauses)


def test_a_native_reply_reaches_the_wire_through_the_production_build():
    """C4-2f: Entry's native `send` is the dot call client.send(event, fields). A native-owned
    prompt refused by an absent companion answers with its sentinel, and that line reaches
    net.send through the production build (the colon form passed the session as the event)."""
    world = World(pack="gen3_rr", title="radical_red", kind="companion", build=False)
    L = world.lua
    world.io.write_u8 = lambda a, v: None
    lines = []
    net = L.table(connected=lambda: True, pump=lambda: None, send=lambda line: lines.append(str(line)),
                  receive=lambda: None)
    hud = L.table(show=lambda *a: None, prompt=lambda *a: None)
    client, parts = world.Entry.build(world.deps(mode="production", net=net, hud=hud, player="a"))
    assert parts.native is not None
    client.hello_sent, client.writes_enabled = True, True
    client.handle_command(client, L.table(cmd="show_menu", token="tk", text="?"))
    replies = [json.loads(line) for line in lines]
    assert [(m["event"], m["token"], m["choice"]) for m in replies] == [("menu_result", "tk", 0)]


def test_build_refuses_an_unadmitted_title():
    world = World(pack="gen3_frlg", title="firered_ap", build=False)
    with pytest.raises(lupa.LuaError, match="unadmitted Gen 3 title"):
        world.Entry.build(world.deps())


def test_build_refuses_an_unknown_pack_and_title():
    world = World(build=False)
    with pytest.raises(lupa.LuaError, match="unknown pack"):
        world.Entry.build(world.deps(pack="gen3_bogus"))
    with pytest.raises(lupa.LuaError, match="unknown title"):
        world.Entry.build(world.deps(title="quartz"))


def test_pack_files_exist_and_are_the_only_named_foundation():
    """Every path in Entry.PACK_FILES ships; the release manifest derives from them."""
    world = World(build=False)
    files = lua_to_py(world.Entry.PACK_FILES)
    assert set(files) == set(PACKS) | {"gen3_emerald"}
    for pack, entries in files.items():
        for key, rel in entries.items():
            assert (REPO / rel).exists(), f"{pack}.{key} -> missing {rel}"
