"""Gen 2 overlay admission (docs/gen2/OVERLAY_ADMISSION.md D1/D3/D4/D5): production admits an ACTIVATED
overlay row through its own proofs, with the identity taken from the admission decision.

No real overlay ROM or sidecar is needed. The overlay cartridge here is the clean image with its last byte
flipped (distinct sha1, same anchors); lua/gen2/artifact.lua is stubbed for the overlay kind (Stream R owns the
real branch, tests/unit/test_gen2_artifacts.py); the overlay receipts are the committed clean receipts relabelled
the way tools/gen2_artifacts.py's capture lane stamps them (kind, binding, executed sha1).
"""
import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.unit.test_gen2_client import EMULATOR, OPEN  # noqa: E402
from tests.unit.test_gen2_entry import World  # noqa: E402

BINDING = "b" * 64
GRANT = "c" * 64
TITLES = ("crystal", "gold", "silver")

# Replaces lua/gen2/artifact.lua for the OVERLAY kind only; clean delegates to the real module.
STUB = r"""
return function(real_path, state)
    local real = dofile(real_path)
    local A = {}
    function A.view(root, json, data, title, row)
        if row.kind ~= "overlay" then return real.view(root, json, data, title, row) end
        if state.no_binding then return nil, "overlay execution binding missing" end
        local headers = {}
        for _, area in pairs(data.area_map) do
            headers[#headers + 1] = {offset=area.source.header_flat, hex=area.source.header_hex}
        end
        return {kind="overlay", rom_sha1=row.sha1, base_sha1=row.base_sha1, binding_sha256=row.binding_sha256,
                sites=data.sites.titles[title].sites, checkpoint=data.checkpoint.titles[title],
                anchors=headers, profile_rom=nil}
    end
    local original = dofile
    dofile = function(path)
        if path:sub(-#"lua/gen2/artifact.lua") == "lua/gen2/artifact.lua" then return A end
        return original(path)
    end
end
"""


def sha1(data):
    return hashlib.sha1(data).hexdigest()


def clean_image(title):
    source = "pokecrystal" if title == "crystal" else "pokegold"
    artifact = json.loads((ROOT / f"data/games/gen2_{title}/profile.json").read_text())["titles"][title]["artifact"]
    return (ROOT / f".cache/gen2-build/{source}/{artifact}.gbc").read_bytes()


def overlay_image(title):
    image = clean_image(title)
    return image[:-1] + bytes([image[-1] ^ 1])


def stamp(receipt, sha, kind="overlay", binding=BINDING):
    """The capture lane's stamp on a receipt and on every run it holds."""
    def one(node):
        node["rom_sha1"], node["artifact_kind"], node["binding_sha256"] = sha, kind, binding
    one(receipt)
    runs = receipt.get("runs")
    for run in (runs.values() if isinstance(runs, dict) else runs or []):
        one(run)
    for row in receipt.get("fixtures", []):          # a fixture-qualification report
        row["provenance"]["rom_sha1"] = sha
    return receipt


def overlay_receipts(title, sha, **kw):
    """overlay path -> relabelled committed clean receipt text."""
    out = {}
    for path in sorted((ROOT / f"data/games/gen2_{title}/receipts").glob("*.json")):
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if path.name.endswith((".engine_sites.json", ".write_window.json")):
            stamp(receipt, sha, **kw)
        elif path.name.endswith(".qualification.json"):
            for row in receipt["fixtures"]:
                row["provenance"]["rom_sha1"] = sha
        out[f"gen2_{title}/receipts/overlay/{path.name}"] = json.dumps(receipt)
    return out


def matrix_text(title, sha, **change):
    matrix = json.loads((ROOT / f"data/games/gen2_{title}/admission.json").read_text(encoding="utf-8"))
    matrix["schema_version"] = 2
    row = next(r for r in matrix["artifacts"] if r["kind"] == "overlay")
    row.pop("grant_fingerprint", None)
    row.update(sha1=sha, selection="SELECTED", status="ADMITTED", binding_sha256=BINDING,
               runtime_gate={"id": "G4", "state": "ADMITTED", "grant_fingerprint": GRANT})
    for key, value in change.items():
        if value is None:
            row.pop(key, None)
        else:
            row[key] = value
    return json.dumps(matrix)


class Overlay:
    """A Lua runtime serving an activated overlay catalog row, overlay receipts and the stubbed view."""

    def __init__(self, title="crystal", image=None, files=None, no_binding=False, receipts=True, **row_change):
        self.title = title
        self.profile = json.loads((ROOT / f"data/games/gen2_{title}/profile.json").read_text())["titles"][title]
        self.image = image or overlay_image(title)
        self.sha = sha1(self.image)
        served = {f"gen2_{title}/admission.json": matrix_text(title, self.sha, **row_change)}
        if receipts:
            served.update(overlay_receipts(title, self.sha))
        served.update(files or {})
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(OPEN)(self.lua.table_from(served))
        self.state = self.lua.table(no_binding=no_binding)
        self.lua.execute(STUB)((ROOT / "lua/gen2/artifact.lua").as_posix(), self.state)
        self.entry = self.lua.eval("dofile")((ROOT / "lua/gen2/entry.lua").as_posix())

    def reader(self):
        return self.lua.eval("function(img) return function(a) return img:byte(a + 1) end end")(self.image)

    def admit_args(self, **extra):
        return self.lua.table(root=ROOT.as_posix(), rom_size=len(self.image), read_rom_u8=self.reader(), **extra)

    def admit(self):
        return self.entry.admit(self.admit_args())

    def build(self, forged_kind=None, title=None):
        emu, io, net, hud, logs, log = self.lua.execute(EMULATOR)(self.image, self.profile["ram"]["hROMBank"])
        io.model_only = False
        io.domains = self.lua.eval('function() return {"ROM", "System Bus", "CartRAM"} end')
        args = self.admit_args(title=title or self.title, io=io, net=net, hud=hud, player="a", log=log)
        if forged_kind is not None:
            args.artifact_kind = forged_kind
        return self.entry.build(args)


def refused(result, *words):
    decision, reason = result if isinstance(result, tuple) else (result, None)
    assert decision is None, "admitted: " + str(dict(decision.items()) if decision else decision)
    for word in words:
        assert word in reason, (word, reason)
    return reason


# --- D1/D5: admission ---------------------------------------------------------------------------

@pytest.mark.parametrize("title", ["crystal", "gold"])
def test_an_activated_overlay_with_its_own_proofs_admits_with_the_actual_sha1_and_kind(title):
    world = Overlay(title)
    decision = world.admit()
    assert not isinstance(decision, tuple), decision
    assert (decision.title, decision.pack, decision.kind, decision.rom_sha1) == (
        title, f"gen2_{title}", "overlay", world.sha)
    assert decision.rom_sha1 != world.profile["rom_sha1"]


def test_an_activated_overlay_composes_production_with_the_decision_identity():
    world = Overlay("crystal")
    parts = world.build()
    assert not isinstance(parts, tuple), parts
    assert parts.production_admitted is True
    assert (parts.artifact_kind, parts.runtime_rom_sha1) == ("overlay", world.sha)
    assert (parts.client.artifact_kind, parts.client.rom_sha1) == ("overlay", world.sha)


@pytest.mark.parametrize("forged", ["clean", "overlay", "ghost"])
def test_a_caller_forged_artifact_kind_cannot_choose_the_composition(forged):
    parts = Overlay("crystal").build(forged_kind=forged)
    assert not isinstance(parts, tuple), parts
    assert (parts.client.artifact_kind, parts.artifact_kind) == ("overlay", "overlay")
    clean = World("crystal")
    args = clean.args()
    args.candidate_only = None
    args.net, args.hud, args.player, args.artifact_kind = clean.lua.table(), clean.lua.table(), "a", forged
    emu, io, net, hud, logs, log = clean.lua.execute(EMULATOR)(clean.image, clean.profile["ram"]["hROMBank"])
    io.model_only = False
    io.domains = clean.lua.eval('function() return {"ROM", "System Bus", "CartRAM"} end')
    prod = clean.entry.build(clean.lua.table(root=ROOT.as_posix(), title="crystal", io=io, net=net, hud=hud,
                                             player="a", log=log, rom_size=len(clean.image),
                                             read_rom_u8=clean.lua.eval("function(io) return function(a) return io.read_u8(a, 'ROM') end end")(io),
                                             artifact_kind=forged))
    assert not isinstance(prod, tuple), prod
    assert (prod.client.artifact_kind, prod.artifact_kind, prod.runtime_rom_sha1) == (
        "clean", "clean", clean.profile["rom_sha1"])
    assert prod.client.trade_live(prod.client) is False


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_clean_still_admits_with_kind_and_sha1(title):
    world = World(title)
    decision = world.entry.admit(world.args())
    assert not isinstance(decision, tuple), decision
    assert (decision.kind, decision.rom_sha1) == ("clean", world.profile["rom_sha1"])


def test_clean_receipt_files_keep_their_paths_and_the_overlay_namespace_is_separate():
    world = World()
    for pack in ("gen2_crystal", "gen2_gold", "gen2_silver"):
        files = world.entry.RECEIPT_FILES[pack]
        title = pack.split("_")[1]
        assert files.clean.engine_sites == f"data/games/gen2_{title}/receipts/{title}.engine_sites.json"
        assert files.overlay.engine_sites == f"data/games/gen2_{title}/receipts/overlay/{title}.engine_sites.json"
        assert files.overlay.write_window == f"data/games/gen2_{title}/receipts/overlay/{title}.write_window.json"
        assert all(path.startswith(f"data/games/gen2_{title}/receipts/overlay/")
                   for path in dict(files.overlay.qualifications.items()).values())
    assert world.entry.RECEIPT_FILES.gen2_silver.clean.write_window.endswith("silver/receipts/gold.write_window.json")
    assert world.entry.RECEIPT_FILES.gen2_silver.overlay.write_window.endswith("overlay/silver.write_window.json")
    assert set(dict(world.entry.RECEIPT_FILES.gen2_silver.overlay.qualifications.items())) == {
        "silver_battle", "silver_town", "silver_synth_grass", "silver_synth_kyle", "silver_synth_bill"}


@pytest.mark.parametrize("change,words", [
    ({"selection": "FUTURE", "status": "BUILT", "runtime_gate": None, "binding_sha256": None}, "selection"),
    ({"selection": "FUTURE"}, "selection"),
    ({"status": "BUILT"}, "status"),
    ({"runtime_gate": None}, "G4"),
    ({"runtime_gate": {"id": "G1", "state": "ADMITTED", "grant_fingerprint": GRANT}}, "G4"),
    ({"runtime_gate": {"id": "G4", "state": "PENDING", "grant_fingerprint": GRANT}}, "G4"),
    ({"runtime_gate": {"id": "G4", "state": "ADMITTED"}}, "grant"),
    ({"runtime_gate": {"id": "G4", "state": "ADMITTED", "grant_fingerprint": "stale"}}, "grant"),
    ({"binding_sha256": None}, "binding"),
    ({"binding_sha256": "not-a-hash"}, "binding"),
])
def test_an_overlay_row_that_is_not_fully_activated_is_refused(change, words):
    refused(Overlay("crystal", **change).admit(), words)


def test_the_clean_g1_grant_never_grants_the_overlay():
    world = Overlay("crystal", runtime_gate=None)
    assert json.loads(matrix_text("crystal", world.sha, runtime_gate=None))["gate"]["state"] == "ADMITTED"
    refused(world.admit(), "G4")


@pytest.mark.parametrize("title", ["crystal", "gold"])
def test_a_missing_overlay_binding_never_falls_back_to_clean(title):
    world = Overlay(title, no_binding=True)
    refused(world.admit(), "binding")
    refused(world.build(), "binding")
    clean = World(title)                       # the clean cartridge is unaffected
    assert not isinstance(clean.entry.admit(clean.args()), tuple)


def test_an_unknown_hash_and_crystal_11_stay_refused_beside_an_activated_overlay():
    world = Overlay("crystal")
    world.image = world.image[:-2] + bytes([world.image[-2] ^ 1, world.image[-1]])   # not the activated sha1
    refused(world.admit(), "unknown")
    eleven = World("crystal", "pokecrystal11")
    refused(eleven.entry.admit(eleven.args()), "BUILD_ONLY")


@pytest.mark.parametrize("missing", ["engine_sites", "write_window", "qualification"])
def test_a_missing_overlay_proof_refuses_the_overlay(missing):
    probe = Overlay("crystal")
    names = {"engine_sites": "crystal.engine_sites.json", "write_window": "crystal.write_window.json",
             "qualification": "crystal_battle.qualification.json"}
    refused(Overlay("crystal", files={f"gen2_crystal/receipts/overlay/{names[missing]}": False}).admit(),
            names[missing] if missing != "qualification" else "qualification")
    assert probe.admit() is not None


def test_a_stale_overlay_proof_that_does_not_bind_the_executed_sha1_is_refused():
    stale = overlay_receipts("crystal", "0" * 40)         # stamped for another overlay build
    refused(Overlay("crystal", files=stale).admit(), "U1")


def test_a_clean_receipt_attached_to_the_overlay_is_refused():
    clean = {}
    for path in (ROOT / "data/games/gen2_crystal/receipts").glob("*.json"):
        clean[f"gen2_crystal/receipts/overlay/{path.name}"] = path.read_text(encoding="utf-8")
    refused(Overlay("crystal", files=clean).admit(), "U1")


def test_a_clean_receipt_with_only_the_kind_forged_is_refused():
    world = Overlay("crystal")
    forged = overlay_receipts("crystal", world.sha, kind="clean")
    refused(Overlay("crystal", files=forged).admit(), "U1")


@pytest.mark.parametrize("stamped_for", ["overlay_sha1", "clean_sha1"])
def test_an_overlay_receipt_attached_to_the_clean_cartridge_is_refused(stamped_for):
    world = World("crystal")
    sha = sha1(overlay_image("crystal")) if stamped_for == "overlay_sha1" else world.profile["rom_sha1"]
    overlay = overlay_receipts("crystal", sha)      # the clean_sha1 variant: only the kind and binding mark it overlay
    served = {path.replace("receipts/overlay/", "receipts/"): text for path, text in overlay.items()}
    world.lua.execute(OPEN)(world.lua.table_from(served))
    refused(world.entry.admit(world.args()), "U1")


def test_a_wrong_binding_on_the_receipts_is_refused():
    receipts = overlay_receipts("crystal", sha1(overlay_image("crystal")), binding="d" * 64)
    refused(Overlay("crystal", files=receipts).admit(), "U1")


# --- candidate clients and the trade gate ---------------------------------------------------------

def test_the_client_refuses_an_artifact_kind_that_is_neither_clean_nor_overlay():
    world = World()
    args = world.args()
    args.net, args.hud, args.player, args.artifact_kind = world.lua.table(), world.lua.table(), "a", "ghost"
    world.io.model_only = True
    args.checkpoint = world.lua.eval("{check=function() return false, 'OPEN' end}")
    result = world.entry.build_candidate(args)
    assert isinstance(result, tuple) and result[0] is None and "artifact_kind" in result[1]


# --- D5: the validators take the selected view ----------------------------------------------------

class Validators:
    def __init__(self, title="crystal"):
        self.title = title
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        load = self.lua.eval("dofile")
        self.S = load((ROOT / "lua/gen2/signals.lua").as_posix())
        self.M = load((ROOT / "lua/gen2_write_safety.lua").as_posix())
        self.codec = load((ROOT / "lua/json_codec.lua").as_posix())
        decode = self.lua.eval("function(c, t) return assert(c.decode(t)) end")
        self.decode = lambda text: decode(self.codec, text)

        def pack(name):
            return self.decode((ROOT / f"data/games/gen2_{title}/{name}").read_text(encoding="utf-8"))
        self.sites, self.checkpoint = pack("engine_signals.json"), pack("write_checkpoint.json")
        self.clean_sha = self.sites.source.rom_sha1
        self.sha = "a" * 40

    def view(self, kind="overlay", sha=None, binding=BINDING, sites=None, checkpoint=None):
        return self.lua.table(kind=kind, rom_sha1=sha or (self.sha if kind == "overlay" else self.clean_sha),
                              base_sha1=self.clean_sha, binding_sha256=binding if kind == "overlay" else None,
                              sites=sites or self.sites.titles[self.title].sites,
                              checkpoint=checkpoint or self.checkpoint.titles[self.title])

    def receipt(self, name, sha=None, **kw):
        text = (ROOT / f"data/games/gen2_{self.title}/receipts/{self.title}.{name}.json").read_text(encoding="utf-8")
        return self.decode(json.dumps(stamp(json.loads(text), sha or self.sha, **kw)))

    def clean_receipt(self, name):
        return self.decode((ROOT / f"data/games/gen2_{self.title}/receipts/{self.title}.{name}.json").read_text(encoding="utf-8"))


def ok(result):
    return not isinstance(result, tuple) and result is not None


def test_engine_site_receipts_prove_only_the_view_they_were_captured_on():
    v = Validators()
    overlay = v.view()
    assert ok(v.S.qualified_sites("crystal", v.sites, v.receipt("engine_sites"), overlay))
    for bad in (v.clean_receipt("engine_sites"),                                     # a clean receipt
                v.receipt("engine_sites", sha="e" * 40),                              # another ROM
                v.receipt("engine_sites", binding="e" * 64),                          # another binding
                v.receipt("engine_sites", kind="clean")):                             # another kind
        assert not ok(v.S.qualified_sites("crystal", v.sites, bad, overlay))
    clean = v.view("clean")
    assert ok(v.S.qualified_sites("crystal", v.sites, v.clean_receipt("engine_sites"), clean))
    assert ok(v.S.qualified_sites("crystal", v.sites, v.clean_receipt("engine_sites")))      # no view = clean pack
    assert not ok(v.S.qualified_sites("crystal", v.sites, v.receipt("engine_sites"), clean))
    assert not ok(v.S.qualified_sites("crystal", v.sites, v.receipt("engine_sites")))


def test_a_v2_union_never_mixes_kinds_or_roms():
    v = Validators()
    text = json.loads((ROOT / "data/games/gen2_crystal/receipts/crystal.engine_sites.json").read_text(encoding="utf-8"))
    assert ok(v.S.qualified_sites("crystal", v.sites, v.decode(json.dumps(stamp(copy.deepcopy(text), v.sha))), v.view()))
    mixed = stamp(text, v.sha)
    mixed["runs"][-1]["rom_sha1"] = v.clean_sha
    assert not ok(v.S.qualified_sites("crystal", v.sites, v.decode(json.dumps(mixed)), v.view()))
    mixed = stamp(json.loads(json.dumps(text)), v.sha)
    mixed["runs"][-1]["artifact_kind"] = "clean"
    assert not ok(v.S.qualified_sites("crystal", v.sites, v.decode(json.dumps(mixed)), v.view()))


def test_engine_site_hits_are_checked_against_the_view_sites_not_the_clean_pack():
    v = Validators()
    assert ok(v.S.qualified_sites("crystal", v.sites, v.receipt("engine_sites"), v.view()))
    moved = v.decode(json.dumps(json.loads((ROOT / "data/games/gen2_crystal/engine_signals.json").read_text(encoding="utf-8"))))
    shipped = json.loads((ROOT / "data/games/gen2_crystal/receipts/crystal.engine_sites.json").read_text(encoding="utf-8"))
    name = shipped["runs"][0]["proven"][0]      # a site the receipt proves: moving it must break the proof
    moved.titles.crystal.sites[name].addr = moved.titles.crystal.sites[name].addr + 1
    assert not ok(v.S.qualified_sites("crystal", v.sites, v.receipt("engine_sites"), v.view(sites=moved.titles.crystal.sites)))


def test_write_window_receipts_prove_only_the_view_they_were_captured_on():
    v = Validators()
    overlay = v.view()
    assert ok(v.M.qualified(v.checkpoint, "crystal", v.receipt("write_window"), overlay))
    for bad in (v.clean_receipt("write_window"), v.receipt("write_window", sha="e" * 40),
                v.receipt("write_window", binding="e" * 64), v.receipt("write_window", kind="clean")):
        assert not ok(v.M.qualified(v.checkpoint, "crystal", bad, overlay))
    assert ok(v.M.qualified(v.checkpoint, "crystal", v.clean_receipt("write_window"), v.view("clean")))
    assert ok(v.M.qualified(v.checkpoint, "crystal", v.clean_receipt("write_window")))
    assert not ok(v.M.qualified(v.checkpoint, "crystal", v.receipt("write_window"), v.view("clean")))


def test_silver_overlay_has_its_own_write_window_and_does_not_reuse_golds():
    v = Validators("silver")
    gold = json.loads((ROOT / "data/games/gen2_silver/receipts/gold.write_window.json").read_text(encoding="utf-8"))
    assert gold["title"] == "gold"
    # O-23 stays clean-only: Gold's window under a Silver clean view still qualifies, never under the overlay view
    assert ok(v.M.qualified(v.checkpoint, "silver", v.decode(json.dumps(gold))))
    assert not ok(v.M.qualified(v.checkpoint, "silver", v.decode(json.dumps(stamp(copy.deepcopy(gold), v.sha))), v.view()))
    own = copy.deepcopy(gold)
    own["title"] = "silver"
    for run in own["runs"].values():
        run["title"] = "silver"
        run["fixture"] = run["fixture"].replace("gold_", "silver_")
    assert ok(v.M.qualified(v.checkpoint, "silver", v.decode(json.dumps(stamp(own, v.sha))), v.view()))


def test_the_checkpoint_admitted_closure_gets_the_executed_sha1():
    v = Validators()
    asked = v.lua.table()
    ownership = v.lua.eval("""function(asked) return {
        capture=function() return 1 end, valid=function() return true end,
        admitted=function(title, sha) asked[#asked + 1] = title .. ':' .. tostring(sha); return false end,
        no_conflicting_owner=function() return true end, mapped_rom_bank=function() return 0 end,
        effective_wram_bank=function() return 1 end} end""")(asked)
    evaluator = v.lua.eval("{check=function() return true end}")
    io = v.lua.eval("{read_u8=function() return 0 end, domain_size=function() return 0x100000 end}")
    for kind, receipt in (("overlay", v.receipt("write_window")),
                                 ("clean", v.clean_receipt("write_window"))):
        checkpoint = v.M.new(v.checkpoint, "crystal", io, evaluator, ownership, receipt, v.view(kind))
        assert checkpoint.covers(checkpoint, "party_hp") is True
        checkpoint.check(checkpoint, "party_hp")
    assert list(asked.values()) == [f"crystal:{v.sha}", f"crystal:{v.clean_sha}"]


def test_fixture_binding_takes_the_view_and_refuses_another_rom_or_kind():
    v = Validators()
    reports = {}
    for path in (ROOT / "data/games/gen2_crystal/receipts").glob("*.json"):
        if path.name.endswith((".engine_sites.json", ".write_window.json")):
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        for row in report.get("fixtures", []):          # a synthetic disclosure has no rows
            row["provenance"]["rom_sha1"] = v.sha
        reports[path.name.split(".")[0]] = report
    lua_reports = v.lua.table_from({k: v.decode(json.dumps(r)) for k, r in reports.items()})
    engine, write = v.receipt("engine_sites"), v.receipt("write_window")
    assert ok(v.S.bind_fixture_qualification(engine, lua_reports, v.view()))
    assert ok(v.M.bind_fixture_qualification(write, lua_reports, v.view()))
    assert not ok(v.S.bind_fixture_qualification(engine, lua_reports, v.view("clean")))
    assert not ok(v.M.bind_fixture_qualification(write, lua_reports, v.view("clean")))
    assert not ok(v.S.bind_fixture_qualification(v.clean_receipt("engine_sites"), lua_reports, v.view()))
    assert not ok(v.M.bind_fixture_qualification(v.clean_receipt("write_window"), lua_reports, v.view()))


# --- the REAL artifact.lua + the REAL committed binding sidecar (review L4/L5) -----------------------------------------
# No stub: the overlay cartridge is the shipped UPS applied to the clean build, the view is lua/gen2/artifact.lua's own
# read of data/games/gen2_<t>/overlay/binding.json pinned by its sha256, and only the overlay RECEIPTS are synthetic (the
# committed clean receipts relabelled the way the capture lane stamps them, which the production validators accept).

# Records what compose hands to its collaborators: write_safety.new(pack, title, io, evaluator, ownership, receipt, view),
# signals.new(options) (spied to refuse after recording) and client.new(params).
SPY = r"""
return function(state)
    local original = dofile
    dofile = function(path)
        local module = original(path)
        local name = path:match("lua/gen2_write_safety%.lua$") and "ws" or path:match("lua/gen2/signals%.lua$") and "signals"
                     or path:match("lua/gen2/client%.lua$") and "client"
        if not name then return module end
        return setmetatable({new=function(...)
            state[name] = table.pack(...)
            if name == "signals" then return nil, "spied" end
            return module.new(...)
        end}, {__index=module})
    end
end
"""


def real_binding_pin(title):
    raw = (ROOT / f"data/games/gen2_{title}/overlay/binding.json").read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(raw).hexdigest()


def real_overlay_image(title):
    from patch.tools.make_ups import ups_apply
    published = json.loads((ROOT / "data/gen2/overlay_provenance.json").read_text(encoding="utf-8"))["outputs"]
    out = next(row for row in published.values() if row["slink_title"] == title)
    image = ups_apply(clean_image(title), (ROOT / out["ups"]["file"]).read_bytes())
    assert sha1(image) == out["sha1"], "the shipped UPS no longer rebuilds the published overlay"
    return image


def real_overlay_files(title, sha, binding):
    """The activated catalog row (real sha1/base/UPS, the real binding pin) and the relabelled overlay receipts."""
    matrix = json.loads((ROOT / f"data/games/gen2_{title}/admission.json").read_text(encoding="utf-8"))
    row = next(r for r in matrix["artifacts"] if r["kind"] == "overlay")
    assert row["sha1"] == sha
    row.pop("grant_fingerprint", None)
    row.update(selection="SELECTED", status="ADMITTED", binding_sha256=binding,
               runtime_gate={"id": "G4", "state": "ADMITTED", "grant_fingerprint": GRANT})
    files = {f"gen2_{title}/admission.json": json.dumps(matrix)}
    files.update(overlay_receipts(title, sha, binding=binding))
    if title == "silver":       # O-23: Silver's CLEAN write window is Gold's; the overlay has its own (never Gold's)
        own = json.loads((ROOT / "data/games/gen2_silver/receipts/gold.write_window.json").read_text(encoding="utf-8"))
        own["title"] = "silver"
        for mode, run in own["runs"].items():
            run["title"] = "silver"
            run["fixture"] = run["fixture"].replace("gold_", "silver_")
            report = json.loads((ROOT / f"data/games/gen2_silver/receipts/{run['fixture']}.qualification.json")
                                .read_text(encoding="utf-8"))          # the run ran on Silver's own qualified fixture
            run["qualification_attempt_id"] = report["attempt_id"]
            if mode in ("town", "battle", "boxes", "battle_faint", "battle_bench"):     # the runs U3 binds by fixture bytes
                run["fixture_sha256"] = report["fixtures"][0]["artifacts"]["fixture"]["sha256"]
        files["gen2_silver/receipts/overlay/silver.write_window.json"] = json.dumps(stamp(own, sha, binding=binding))
    return files


class RealOverlay(Overlay):
    def __init__(self, title):
        self.title = title
        self.profile = json.loads((ROOT / f"data/games/gen2_{title}/profile.json").read_text())["titles"][title]
        self.image = real_overlay_image(title)
        self.sha = sha1(self.image)
        self.binding = real_binding_pin(title)
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(OPEN)(self.lua.table_from(real_overlay_files(title, self.sha, self.binding)))
        self.spied = self.lua.table()
        self.lua.execute(SPY)(self.spied)
        self.entry = self.lua.eval("dofile")((ROOT / "lua/gen2/entry.lua").as_posix())


@pytest.mark.parametrize("title", TITLES)
def test_the_real_overlay_view_admits_and_composes_with_the_decision_identity_for_every_title(title):
    world = RealOverlay(title)
    decision = world.admit()
    assert not isinstance(decision, tuple), decision
    assert (decision.title, decision.pack, decision.kind, decision.rom_sha1, decision.binding_sha256) == (
        title, f"gen2_{title}", "overlay", world.sha, world.binding)
    assert decision.rom_sha1 != world.profile["rom_sha1"]

    parts = world.build()
    assert not isinstance(parts, tuple), parts
    assert parts.production_admitted is True
    assert (parts.artifact_kind, parts.runtime_rom_sha1) == ("overlay", world.sha)
    assert (parts.client.artifact_kind, parts.client.rom_sha1) == ("overlay", world.sha)
    view = parts.view
    assert (view.kind, view.rom_sha1, view.base_sha1, view.binding_sha256) == (
        "overlay", world.sha, world.profile["rom_sha1"], world.binding)
    assert parts.proven_sites is not None and parts.write_scope is not None
    assert all(parts.checkpoint.covers(parts.checkpoint, kind)
               for kind in ("party_hp", "party_collection", "battle_faint", "battle_bench"))

    # D5: the executed view (not the clean pack) reaches the checkpoint and the signals binder
    rawequal = world.lua.eval("rawequal")
    assert rawequal(world.spied.ws[7], view), "write_safety.new did not get the executed view"
    assert world.spied.ws[2] == title
    world.spied.client[1].signals(world.lua.table(capture=world.lua.eval("function() return 1 end"),
                                                  valid=world.lua.eval("function() return true end")))
    options = world.spied.signals[1]
    assert rawequal(options.view, view), "signals.new did not get the executed view"
    assert options.runtime_qualification is not None

    # the production `admitted` observation is exactly (this title, the ACTUAL overlay sha1): neither the clean sha1
    # (what the pack says) nor any other ROM, nor another title
    admitted = world.spied.ws[5].admitted
    assert admitted(title, world.sha) is True
    assert admitted(title, world.profile["rom_sha1"]) is False
    assert admitted(title, "0" * 40) is False
    assert admitted("gold" if title != "gold" else "crystal", world.sha) is False


def test_production_build_refuses_a_requested_title_the_admission_decision_does_not_name():
    world = RealOverlay("crystal")
    assert world.admit().title == "crystal"
    reason = refused(world.build(title="gold"), "admitted title crystal", "requested gold")
    assert "differs" in reason
    assert not isinstance(world.build(title="crystal"), tuple)
    clean = World("gold")                       # the clean cartridge is held to the same rule
    args = clean.args()
    args.candidate_only, args.title = None, "crystal"
    args.net, args.hud, args.player = clean.lua.table(), clean.lua.table(), "a"
    emu, io, net, hud, logs, log = clean.lua.execute(EMULATOR)(clean.image, clean.profile["ram"]["hROMBank"])
    io.model_only = False
    args.io, args.log, args.net, args.hud = io, log, net, hud
    refused(clean.entry.build(args), "differs from the requested")


# --- D5: each validator holds its own guards (the two validators back each other up in compose, so every guard is
# exercised by calling the validator directly, with receipts that are valid in every other respect) ------------------

def lua_view(v, **fields):
    """A view built field by field (nil for None), for shapes Validators.view cannot express."""
    base = {"kind": "overlay", "rom_sha1": v.sha, "base_sha1": v.clean_sha, "binding_sha256": BINDING,
            "sites": v.sites.titles[v.title].sites, "checkpoint": v.checkpoint.titles[v.title]}
    base.update(fields)
    return v.lua.table(**base)


def shipped(v, name, sha=None, **kw):
    """A shipped receipt as a dict, relabelled for an overlay build when `sha` is given."""
    text = (ROOT / f"data/games/gen2_{v.title}/receipts/{v.title}.{name}.json").read_text(encoding="utf-8")
    receipt = json.loads(text)
    return stamp(receipt, sha, **kw) if sha else receipt


def reports(v, sha=None):
    """The shipped fixture-qualification reports; `sha` rewrites the ROM they say they qualified."""
    found = {}
    for path in (ROOT / f"data/games/gen2_{v.title}/receipts").glob("*.json"):
        if path.name.endswith((".engine_sites.json", ".write_window.json")):
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        for row in report.get("fixtures", []) if sha else []:
            row["provenance"]["rom_sha1"] = sha
        found[path.name.split(".")[0]] = v.decode(json.dumps(report))
    return v.lua.table_from(found)


def test_each_validator_refuses_an_overlay_view_that_is_the_clean_rom_or_a_foreign_base():
    v = Validators()
    for label, view, sha in (("the overlay view's ROM is the clean ROM", lua_view(v, rom_sha1=v.clean_sha), v.clean_sha),
                             ("the overlay view is built on another base", lua_view(v, base_sha1="f" * 40), v.sha)):
        engine, write = v.receipt("engine_sites", sha=sha), v.receipt("write_window", sha=sha)
        assert not ok(v.S.qualified_sites("crystal", v.sites, engine, view)), label
        assert not ok(v.M.qualified(v.checkpoint, "crystal", write, view)), label
    assert ok(v.S.qualified_sites("crystal", v.sites, v.receipt("engine_sites"), lua_view(v)))      # the control
    assert ok(v.M.qualified(v.checkpoint, "crystal", v.receipt("write_window"), lua_view(v)))


@pytest.mark.parametrize("binding", [None, "b" * 63, "g" * 64, "B" * 65])
def test_each_validator_refuses_an_overlay_view_whose_binding_is_not_a_sha256(binding):
    v = Validators()
    view = lua_view(v, binding_sha256=binding)
    engine, write = v.receipt("engine_sites", binding=binding), v.receipt("write_window", binding=binding)
    assert not ok(v.S.qualified_sites("crystal", v.sites, engine, view))
    assert not ok(v.M.qualified(v.checkpoint, "crystal", write, view))


def test_each_validator_refuses_a_clean_view_that_is_not_the_pack_rom_or_carries_a_binding():
    v = Validators()
    engine, write = v.clean_receipt("engine_sites"), v.clean_receipt("write_window")
    for label, view in (("a clean view of another ROM", lua_view(v, kind="clean", rom_sha1="a" * 40, binding_sha256=None)),
                        ("a clean view carrying a binding", lua_view(v, kind="clean", rom_sha1=v.clean_sha))):
        assert not ok(v.S.qualified_sites("crystal", v.sites, engine, view)), label
        assert not ok(v.M.qualified(v.checkpoint, "crystal", write, view)), label
    clean = lua_view(v, kind="clean", rom_sha1=v.clean_sha, binding_sha256=None)                  # the control
    assert ok(v.S.qualified_sites("crystal", v.sites, engine, clean))
    assert ok(v.M.qualified(v.checkpoint, "crystal", write, clean))


@pytest.mark.parametrize("field,value", [("artifact_kind", "clean"), ("binding_sha256", "e" * 64)])
def test_a_receipt_is_refused_when_only_its_top_level_or_only_its_runs_name_another_kind_or_binding(field, value):
    v = Validators()
    overlay = lua_view(v)
    for name, qualify in (("write_window", lambda r: v.M.qualified(v.checkpoint, "crystal", r, overlay)),
                          ("engine_sites", lambda r: v.S.qualified_sites("crystal", v.sites, r, overlay))):
        assert ok(qualify(v.decode(json.dumps(shipped(v, name, v.sha))))), name
        top = shipped(v, name, v.sha)
        top[field] = value
        assert not ok(qualify(v.decode(json.dumps(top)))), f"{name}: the receipt itself says {field}={value}"
        runs = shipped(v, name, v.sha)
        for run in runs["runs"].values() if isinstance(runs["runs"], dict) else runs["runs"]:
            run[field] = value
        assert not ok(qualify(v.decode(json.dumps(runs)))), f"{name}: every run says {field}={value}"


def test_fixture_binding_owns_every_run_by_its_rom_kind_and_binding():
    v = Validators()
    overlay, clean_reports, overlay_reports = lua_view(v), reports(v), reports(v, v.sha)
    # each case is consistent with its own reports, so only the ownership of the run by the SELECTED view refuses it
    for name, bind in (("engine_sites", v.S.bind_fixture_qualification), ("write_window", v.M.bind_fixture_qualification)):
        cases = {
            "a clean run": (shipped(v, name), clean_reports),
            "an overlay-stamped run of the clean ROM": (shipped(v, name, v.clean_sha), clean_reports),
            "an overlay run with another binding": (shipped(v, name, v.sha, binding="e" * 64), overlay_reports),
        }
        for label, (receipt, qualification) in cases.items():
            assert not ok(bind(v.decode(json.dumps(receipt)), qualification, overlay)), f"{name}: {label}"
        assert ok(bind(v.decode(json.dumps(shipped(v, name, v.sha))), overlay_reports, overlay)), name          # control


def test_fixture_binding_owns_a_v1_engine_site_receipt_too():
    v = Validators()
    overlay = lua_view(v)
    shipped_runs = shipped(v, "engine_sites")["runs"]
    live = next(run for run in shipped_runs if "synth" not in run["fixture"])
    clean_reports, overlay_reports = reports(v), reports(v, v.sha)
    one = lambda run: v.decode(json.dumps(run))              # noqa: E731  a single run is a v1-shaped receipt
    assert ok(v.S.bind_fixture_qualification(one(live), clean_reports[live["fixture"]], lua_view(
        v, kind="clean", rom_sha1=v.clean_sha, binding_sha256=None)))
    assert ok(v.S.bind_fixture_qualification(one(stamp(copy.deepcopy(live), v.sha)), overlay_reports[live["fixture"]], overlay))
    for label, run, report in (
            ("a clean receipt", live, clean_reports),
            ("an overlay-stamped receipt of the clean ROM", stamp(copy.deepcopy(live), v.clean_sha), clean_reports),
            ("another binding", stamp(copy.deepcopy(live), v.sha, binding="e" * 64), overlay_reports)):
        assert not ok(v.S.bind_fixture_qualification(one(run), report[live["fixture"]], overlay)), label


HELD = r"""
-- A host whose every observation satisfies the checkpoint for one hold, so the evaluation runs all the way through
-- (admitted identity asked at the start AND again at the end of the held execution); `seen` records each sha1 asked.
return function(mem, mapped_bank, executed, seen)
    local io = {read_u8=function(address) return mem[address] or 0 end, domain_size=function() return 0x100000 end}
    return {
        io=io,
        ownership={capture=function() return 1 end, valid=function() return true end,
                   admitted=function(_, sha) seen[#seen + 1] = sha; return sha == executed end,
                   no_conflicting_owner=function() return true end,
                   mapped_rom_bank=function() return mapped_bank end, effective_wram_bank=function() return 1 end},
        evaluator={check=function(_, host, accept) return accept(function(a, d) return host.read_u8(a, d) end) end},
    }
end
"""


def held_memory(facts, which, in_battle=False):
    """System Bus bytes that satisfy every ownership and state predicate of one hold of the checkpoint pack."""
    hold = facts[which]
    owner = hold["ownership_requirements"]
    memory = {owner["rom_bank_shadow"]["address"]: owner["rom_bank_shadow"]["equals"],
              owner["wram_bank_register"]["address"]: owner["effective_wram_bank"],
              owner["serial_control"]["address"]: owner["serial_control"]["value"]}
    memory.update({c["address"]: c["value"] for c in hold["state_predicates"]})
    if in_battle:        # the frame hold needs the overworld predicate wBattleMode to REFUSE
        battle = next(c for c in facts["primary"]["state_predicates"] if c["symbol"] == "wBattleMode")
        memory[battle["address"]] = (battle["value"] + 1) % 256
    return memory, owner["mapped_rom_bank"]


@pytest.mark.parametrize("kind", ["overlay", "clean"])
def test_the_held_checkpoint_asks_for_the_executed_sha1_at_every_site_it_checks_identity(kind):
    v = Validators()
    facts = json.loads((ROOT / "data/games/gen2_crystal/write_checkpoint.json").read_text(encoding="utf-8"))["titles"]["crystal"]
    executed = v.sha if kind == "overlay" else v.clean_sha
    receipt = v.receipt("write_window") if kind == "overlay" else v.clean_receipt("write_window")
    # (write kind, hold, how many times the hold asks: at the start and again before it accepts)
    for write_kind, which, asks in (("party_hp", "primary", 2), ("battle_faint", "battle_hold", 2),
                                    ("battle_bench", "battle_hold", 1)):
        memory, bank = held_memory(facts, which, in_battle=write_kind == "battle_bench")
        seen = v.lua.table()
        host = v.lua.execute(HELD)(v.lua.table_from(memory), bank, executed, seen)
        checkpoint = v.M.new(v.checkpoint, "crystal", host.io, host.evaluator, host.ownership, receipt, v.view(kind))
        assert checkpoint.covers(checkpoint, write_kind) is True, write_kind
        result = checkpoint.check(checkpoint, write_kind)
        assert (result[0] if isinstance(result, tuple) else result) is True, (write_kind, result)
        assert list(seen.values()) == [executed] * asks, (write_kind, list(seen.values()))
    # the identity observation is live: a host that admits some other ROM authorizes nothing
    seen = v.lua.table()
    memory, bank = held_memory(facts, "primary")
    host = v.lua.execute(HELD)(v.lua.table_from(memory), bank, "0" * 40, seen)
    checkpoint = v.M.new(v.checkpoint, "crystal", host.io, host.evaluator, host.ownership, receipt, v.view(kind))
    result = checkpoint.check(checkpoint, "party_hp")
    assert (result[0] if isinstance(result, tuple) else result) is False
