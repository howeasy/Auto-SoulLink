"""Gen 2 candidate graph and production admission over actual P1 ROMs (O-22: Crystal only)."""

import json
import sys
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


@pytest.mark.parametrize("title", ["gold", "silver"])
def test_built_pending_catalogs_cannot_admit_production(title):
    world = World(title)
    decision, reason = world.entry.admit(world.args())
    assert decision is None and "BUILT" in reason and "PENDING" in reason
    assert world.writes == []


def test_crystal_is_admitted_only_behind_its_shipped_receipts():
    world = World()
    decision = world.entry.admit(world.args())
    assert not isinstance(decision, tuple), decision
    assert (decision.title, decision.pack, decision.kind, decision.rom_sha1) == (
        "crystal", "gen2_crystal", "clean", "f4cd194bdee0d04ca4eac29e09b8e4e9d818c133")
    world.lua.execute("""local original = io.open
        io.open=function(path,mode)
            if path:match('/receipts/crystal%.write_window%.json$') then return nil, 'missing receipt' end
            return original(path,mode)
        end""")
    decision, reason = world.entry.admit(world.args())
    assert decision is None and "write_window" in reason
    assert set(dict(world.entry.RECEIPT_FILES.items())) == {"gen2_crystal"}  # nothing else can be admitted


def test_committed_matrices_admit_crystal_alone_under_o22_and_regenerate():
    gates = {t: json.loads((ROOT / f"data/games/gen2_{t}/admission.json").read_text())["gate"]
             for t in ("crystal", "gold", "silver")}
    assert gates == {"crystal": {"id": "G1", "state": "ADMITTED", "authority": "O-22"},
                     "gold": {"id": "G1", "state": "PENDING"}, "silver": {"id": "G1", "state": "PENDING"}}
    sys.path.insert(0, str(ROOT / "tools"))
    import gen_gen2_admission as generator
    assert generator.main(["--provenance", str(ROOT / "data/gen2/build_provenance.json"), "--check"]) == 0


def test_shipped_receipts_are_the_committed_fixture_bytes_and_decode_alike_in_lua():
    world = World()
    json_codec = world.lua.eval("dofile")((ROOT / "lua/json_codec.lua").as_posix())
    to_python = world.lua.eval("""function(codec, text)
        local function plain(v)
            if v == codec.null then return nil end
            if type(v) ~= "table" then return v end
            local out = {}
            for k, item in pairs(v) do out[k] = plain(item) end
            return out
        end
        return plain(assert(codec.decode(text)))
    end""")

    def python(value):
        if hasattr(value, "items"):
            items = dict(value.items())
            keys = list(items)
            if keys and all(isinstance(k, int) for k in keys):
                return [python(items[k]) for k in sorted(keys)]
            return {k: python(v) for k, v in items.items()}
        return value

    def normal(value):  # Python view of what Lua can represent: no nulls, [] and {} alike
        if isinstance(value, dict):
            out = {k: normal(v) for k, v in value.items() if v is not None}
            return out or []
        if isinstance(value, list):
            return [normal(v) for v in value]
        return value

    files = dict(world.entry.RECEIPT_FILES.gen2_crystal.items())
    paths = [files["engine_sites"], files["write_window"], *dict(files["qualifications"].items()).values()]
    assert len(paths) == 4
    for rel in paths:
        shipped = ROOT / rel
        assert shipped.read_bytes() == (ROOT / "tests/fixtures/gen2/receipts" / shipped.name).read_bytes(), rel
        text = shipped.read_text(encoding="utf-8")
        assert normal(python(to_python(json_codec, text))) == normal(json.loads(text)), rel


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
    world = World("gold")
    result, reason = world.entry.build(world.args())
    assert result is None and "PENDING" in reason
    world = World()
    world.image = bytes([world.image[0] ^ 1]) + world.image[1:]
    result, reason = world.entry.build(world.args())
    assert result is None and "unknown" in reason
    world = World()
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


def test_client_composition_is_model_only_explicit_and_inert_until_start():
    world = World()
    args = world.args()
    args.net, args.hud, args.player = world.lua.table(), world.lua.table(), "a"
    result, reason = world.entry.build_candidate(args)
    assert result is None and "model_only" in reason
    world.io.model_only = True
    result, reason = world.entry.build_candidate(args)
    assert result is None and "checkpoint" in reason
    args.checkpoint = world.lua.eval("{check=function() return false, 'OPEN' end}")
    parts = world.entry.build_candidate(args)
    assert parts.client is not None and parts.client.signals is None
    assert parts.production_admitted is False and parts.runtime_started is False
    assert world.writes == []


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_header_detection_names_each_title_and_nothing_else(title):
    world = World(title)
    assert world.entry.detect_title(lambda address: world.image[int(address)])[0] == title
    detected, header = world.entry.detect_title(lambda address: b"POKEMON RED\0"[int(address) - 0x134])
    assert detected is None and header == "POKEMON RED"
