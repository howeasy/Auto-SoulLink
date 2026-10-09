"""Gen 2 candidate graph and production admission over actual P1 ROMs (O-22: Crystal only)."""

import copy
import json
import sys
from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime

from tests.unit.test_gen2_physical_receipts import validate

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
def test_a_clean_cartridge_is_never_admitted_the_companion_is_required(title):
    """Patch-first (owner 2026-10-02). Every clean row is SELECTED/BUILT under an ADMITTED G1 with shipped
    PHYSICAL receipts, and the launcher still refuses it: only an activated overlay row (G4) is admitted.
    This replaces the O-22 tests that pinned Crystal/Gold/Silver admitting behind their clean receipts."""
    world = World(title)
    decision, reason = world.entry.admit(world.args())
    assert decision is None and world.writes == []
    assert "needs the SLink companion patch" in reason and "Manager or /patcher" in reason
    assert title in reason
    assert set(dict(world.entry.RECEIPT_FILES.items())) == {"gen2_crystal", "gen2_gold", "gen2_silver"}


def test_committed_matrices_admit_all_three_under_o22_and_regenerate():
    gates = {t: json.loads((ROOT / f"data/games/gen2_{t}/admission.json").read_text())["gate"]
             for t in ("crystal", "gold", "silver")}
    assert gates == {"crystal": {"id": "G1", "state": "ADMITTED", "authority": "O-22"},
                     "gold": {"id": "G1", "state": "ADMITTED", "authority": "O-22"},
                     "silver": {"id": "G1", "state": "ADMITTED", "authority": "O-22+O-23"}}
    sys.path.insert(0, str(ROOT / "tools"))
    import gen_gen2_admission as generator
    assert generator.main(["--provenance", str(ROOT / "data/gen2/build_provenance.json"),
                           # P4.1f: the overlay rows are BUILT from the SLink companion build receipt
                           "--overlay-provenance", str(ROOT / "data/gen2/overlay_provenance.json"),
                           "--check"]) == 0


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

    paths = []
    for pack in world.entry.RECEIPT_FILES.values():
        files = dict(pack.clean.items())   # D4: the clean proofs; the overlay namespace is tests/unit/test_gen2_overlay_admission.py
        paths += [files["engine_sites"], files["write_window"], *dict(files["qualifications"].items()).values()]
    # + gold_battle_errand.qualification.json (the Gold U1 fixture's report); card U1G: + silver_town and the nine
    # synthetic-fixture disclosures, which are committed beside their SaveRAM (tests/fixtures/gen2/<name>.synth.json)
    assert len(paths) == 24
    for rel in paths:
        shipped = ROOT / rel
        source = ROOT / ("tests/fixtures/gen2" if shipped.name.endswith(".synth.json") else "tests/fixtures/gen2/receipts")
        if shipped.name.endswith((".engine_sites.json", ".write_window.json")):
            # the final sweep re-stamped the evidence copy with CODE_DIGEST; the shipped copy is production data
            # inside that digest, so it is refreshed only in the post-RC re-sweep (POST_RC_CARDS MASTER-MERGE).
            # Until then the two must prove the same sites; every other shipped file stays byte-identical.
            runs = lambda r: (lambda x: list(x.values()) if isinstance(x, dict) else x)(r.get("runs", [r]))
            proven = lambda r: sorted({s for run in runs(r) for s in (run.get("proven") or [])})
            evidence = json.loads((source / shipped.name).read_text(encoding="utf-8"))
            assert proven(json.loads(shipped.read_text(encoding="utf-8"))) == proven(evidence), rel
        else:
            assert shipped.read_bytes() == (source / shipped.name).read_bytes(), rel
        text = shipped.read_text(encoding="utf-8")
        assert normal(python(to_python(json_codec, text))) == normal(json.loads(text)), rel


def _overlay_structure(receipt, kind):
    """Stable artifact/fixture identity and authority coordinates, not measured run values."""
    top = {key: value for key, value in receipt.items() if key not in {"runs", "code_digest"}}
    identity = (
        "schema", "title", "artifact_kind", "rom_sha1", "binding_sha256", "pack_commit",
        "fixture", "attempt_id", "qualification_attempt_id", "evidence_level", "result",
        "core_mode", "input_mode", "harness_write_scopes",
    )
    if kind == "engine_sites":
        return top, [
            {
                "identity": {key: run.get(key) for key in (
                    *identity, "pack_specs_sha256", "fixture_sha256", "proven", "negatives", "bank_check",
                )},
                "sites": {
                    name: {key: site.get(key) for key in ("bank", "addr", "pc", "expected_hex")}
                    for name, site in run["sites"].items()
                },
            }
            for run in receipt["runs"]
        ]
    # Reset/reload fixtures are run-generated saves; their hashes must bind within each
    # complete proof, not equal another capture's independently generated save.
    return top, {mode: {key: run.get(key) for key in identity}
                 for mode, run in receipt["runs"].items()}


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_shipped_overlay_proofs_preserve_the_post_freeze_authority(title):
    """OVERLAY_ADMISSION_NEXT.md §2: after the sweep compare semantic coverage;
    never refresh production copies merely to fix equality. Both full raw proofs must
    qualify and bind before comparing their authority; qualifications/disclosures stay exact.
    """
    entry = LuaRuntime(unpack_returned_tuples=True).eval("dofile")((ROOT / "lua/gen2/entry.lua").as_posix())
    overlay = entry.RECEIPT_FILES[f"gen2_{title}"].overlay
    for rel in overlay.qualifications.values():
        shipped = ROOT / rel
        captured = ROOT / "tests/fixtures/gen2" / (
            "" if shipped.name.endswith(".synth.json") else "receipts/overlay"
        ) / shipped.name
        assert shipped.read_bytes() == captured.read_bytes(), rel
    for kind in ("engine_sites", "write_window"):
        shipped_path = ROOT / overlay[kind]
        captured_path = ROOT / "tests/fixtures/gen2/receipts/overlay" / shipped_path.name
        shipped = json.loads(shipped_path.read_text(encoding="utf-8"))
        captured = json.loads(captured_path.read_text(encoding="utf-8"))
        assert "code_digest" not in shipped, shipped_path
        shipped_authority, why = validate(kind, title, shipped, artifact="overlay")
        assert shipped_authority is not None, f"{shipped_path}: {why}"
        captured_authority, why = validate(kind, title, captured, artifact="overlay")
        assert captured_authority is not None, f"{captured_path}: {why}"
        assert shipped_authority == captured_authority, kind
        assert _overlay_structure(shipped, kind) == _overlay_structure(captured, kind), kind


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
@pytest.mark.parametrize("kind,reason", [
    ("engine_sites", "wrong-bank decoy did not fire raw and reject every hit by bank"),
    ("write_window", "no accepted checkpoint hold"),
])
def test_tampered_shipped_overlay_measurements_cannot_authorize_runtime(title, kind, reason):
    """Equal coordinates cannot excuse a failed raw negative control or checkpoint witness."""
    path = ROOT / f"data/games/gen2_{title}/receipts/overlay/{title}.{kind}.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    authority, why = validate(kind, title, receipt, artifact="overlay")
    assert authority is not None, why
    tampered = copy.deepcopy(receipt)
    if kind == "engine_sites":
        decoy = tampered["runs"][0]["decoy"]
        decoy["bank_rejects"] = decoy["raw"] - 1
    else:
        tampered["runs"]["town"]["liveness"]["accepted"] = 0
    assert _overlay_structure(tampered, kind) == _overlay_structure(receipt, kind)
    authority, why = validate(kind, title, tampered, artifact="overlay")
    assert authority is None
    assert reason in why


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
    world = World("crystal", "pokecrystal11")
    result, reason = world.entry.build(world.args())
    assert result is None and "BUILD_ONLY" in reason
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
