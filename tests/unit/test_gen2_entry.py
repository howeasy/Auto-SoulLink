"""Gen 2 candidate graph and production-admission refusals over actual P1 ROMs."""

import json
from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
PACK_FILES = {
    "admission.json", "area_map.json", "charmap.lua", "encounter_tables.json", "engine_signals.json",
    "evolutions.json", "gifts.json", "items.json", "map_names.json", "moves.json", "profile.json",
    "species_index.json", "static_encounters.json", "trainers.json", "write_checkpoint.json",
}


class World:
    def __init__(self, title="crystal", artifact=None):
        self.title = title
        self.profile = json.loads((ROOT / f"data/games/gen2_{title}/profile.json").read_text())["titles"][title]
        source = "pokecrystal" if title == "crystal" else "pokegold"
        self.image = (ROOT / f".cache/gen2-build/{source}/{artifact or self.profile['artifact']}.gbc").read_bytes()
        self.bus = bytearray(65536)
        self.bus[self.profile["ram"]["wPartySpecies"]] = 255
        self.writes = []
        self.rom_reads = 0
        self.replace_after_hash = False
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.entry = self.lua.eval("dofile")((ROOT / "lua/gen2/entry.lua").as_posix())
        self.io = self.lua.eval("""function(read, range, emit, size)
            return {read_u8=function(a,d) return read(a,d) end,
                read_range=function(a,n,d) return range(a,n,d) end,
                write_u8=function(a,v,d) return emit(a,v,d) end,
                bank_valid=function(b,a,n) return b==0 or b==1 end,
                domain_size=function(d) return size(d) end, cart_ram_linear=true}
        end""")(self.read, self.read_range, lambda *args: self.writes.append(args), self.size)
        self.policy = self.lua.eval("""{
            authorize=function() return false end, pointer_stable=function() return true end,
            lifetime={capture=function() return 1 end, valid=function() return true end},
            provenance=function() return {site='MODEL only'} end
        }""")

    def size(self, domain):
        return len(self.image) if domain == "ROM" else 0x8000 if domain == "CartRAM" else 65536

    def read(self, address, domain):
        if domain == "ROM":
            self.rom_reads += 1
            if self.replace_after_hash and self.rom_reads == len(self.image) + 1:
                self.image = self.image[:-1] + bytes([self.image[-1] ^ 1])
        return self.image[int(address)] if domain == "ROM" else self.bus[int(address)]

    def read_range(self, address, length, domain):
        data = self.image if domain == "ROM" else self.bus
        return self.lua.table_from(list(data[int(address):int(address) + int(length)]))

    def args(self):
        return self.lua.table(root=ROOT.as_posix(), title=self.title, io=self.io,
                              rom_size=len(self.image), rom_sha1=self.profile["rom_sha1"],
                              read_rom_u8=self.lua.eval("function(read) return function(a) return read(a,'ROM') end end")(self.read),
                              candidate_only=True, write_policy=self.policy)


def test_all_current_generated_pack_files_are_literal_entry_dependencies():
    world = World()
    for title in ("crystal", "gold", "silver"):
        paths = set(dict(world.entry.PACK_FILES[f"gen2_{title}"].items()).values())
        assert paths == {f"data/games/gen2_{title}/{name}" for name in PACK_FILES}


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_built_pending_catalogs_cannot_admit_production(title):
    world = World(title)
    decision, reason = world.entry.admit(world.args())
    assert decision is None and "BUILT" in reason and "PENDING" in reason
    assert world.writes == []


def test_crystal_revision11_remains_build_only():
    world = World("crystal", "pokecrystal11")
    decision, reason = world.entry.admit(world.args())
    assert decision is None and "BUILD_ONLY" in reason


def test_reported_known_hash_cannot_hide_different_actual_bytes():
    world = World()
    world.image = bytes([world.image[0] ^ 1]) + world.image[1:]
    decision, reason = world.entry.admit(world.args())
    assert decision is None and "unknown" in reason


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_candidate_build_wires_existing_read_write_rom_modules_without_activation(title):
    world = World(title)
    parts = world.entry.build_candidate(world.args())
    assert parts.profile.title == title
    assert parts.production_admitted is False and parts.runtime_started is False
    assert parts.client is None and parts.writes.armed is None and world.writes == []
    assert parts.reads.read_party().count == 0
    assert parts.rom.base_stats(1).hp == 45


def test_production_build_stays_closed_and_candidate_build_is_explicit():
    world = World()
    result, reason = world.entry.build(world.args())
    assert result is None and "PENDING" in reason
    args = world.args()
    args.candidate_only = None
    result, reason = world.entry.build_candidate(args)
    assert result is None and "candidate_only" in reason
    assert world.writes == []


def test_candidate_graph_refuses_a_different_rom_before_composition():
    world = World("gold", "pokesilver")
    result, reason = world.entry.build_candidate(world.args())
    assert result is None and "ROM" in reason
    assert world.writes == []


def test_missing_current_pack_file_refuses_candidate_graph():
    world = World()
    world.lua.execute("""local original = io.open
        io.open=function(path,mode)
            if path:match('/gen2_crystal/items.json$') then return nil, 'missing model input' end
            return original(path,mode)
        end""")
    result, reason = world.entry.build_candidate(world.args())
    assert result is None and "items.json" in reason


def test_candidate_graph_refuses_rom_replacement_after_initial_hash():
    world = World()
    world.replace_after_hash = True
    result = world.entry.build_candidate(world.args())
    assert isinstance(result, tuple) and result[0] is None and "changed" in result[1]
    assert world.writes == []
