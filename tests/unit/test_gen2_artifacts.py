"""Artifact execution views: public generation and Lua admission boundaries."""

import hashlib
import json
from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]

from tools.gen2_source_data import SourceVerificationUnavailable  # noqa: E402


def _no_infra(call, *args, **kwargs):
    """Run a source-touching call, treating "git could not answer" as a skip rather than a lane red.

    tools/gen2_source_data._git now refuses that case as SourceVerificationUnavailable instead of
    folding it into the plain ValueError that means "the source changed" (F3). This completes the
    split on the test side: a lane whose git could not be reached skips, so this file's result no
    longer depends on whether the pinned checkout happened to answer when asked. A genuine
    integrity failure is still an ordinary ValueError and still fails.
    """
    try:
        return call(*args, **kwargs)
    except SourceVerificationUnavailable as exc:
        pytest.skip(f"git could not verify the pinned source (infrastructure, not a source "
                    f"verdict): {exc}")


TITLES = ("crystal", "gold", "silver")
ANCHORS = {"crystal": 388, "gold": 368, "silver": 368}
GBC = ROOT / ".cache/gen2-build/pokegold/pokegold.gbc"


def _data():
    return {
        "sites": {"titles": {"crystal": {"sites": {"capture": {"expected_hex": "aa"}}}}},
        "checkpoint": {"titles": {"crystal": {"primary": {"anchors": {}}}}},
        "profile": {"titles": {"crystal": {"rom_sha1": "a" * 40}}},
        "area_map": {"257": {"source": {"header_flat": 32, "header_hex": "dd"}}},
    }


def _binding():
    return {"schema": "gen2-overlay-binding-v1", "title": "crystal", "kind": "overlay",
            "rom_sha1": "b" * 40, "base_sha1": "a" * 40, "ups_sha256": "c" * 64,
            "sym_sha256": "d" * 64, "map_sha256": "e" * 64,
            "sites": {"capture": {"expected_hex": "bb"}},
            "checkpoint": {"primary": {"anchors": {}}},
            "header_anchors": [{"offset": 16, "hex": "cc"}],
            "profile_rom": {"BaseData": {"bank": 1, "addr": 16384, "flat": 16384}}}


def _view(tmp_path, row, binding=None, *, newline="\n", data=None):
    if binding is not None:
        path = tmp_path / "data/games/gen2_crystal/overlay/binding.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = (json.dumps(binding, sort_keys=True, indent=2) + "\n").replace("\n", newline).encode()
        path.write_bytes(raw)
        row.setdefault("binding_sha256", hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest())
    lua = LuaRuntime(unpack_returned_tuples=True)
    module = lua.eval("dofile")((ROOT / "lua/gen2/artifact.lua").as_posix())
    codec = lua.eval("dofile")((ROOT / "lua/json_codec.lua").as_posix())
    result = module.view(tmp_path.as_posix(), codec, lua.table_from(data or _data(), recursive=True),
                         "crystal", lua.table_from(row, recursive=True))
    return result if isinstance(result, tuple) else (result, None)


# ── order independence and cost ────────────────────────────────────────────────────────
# The pinned checkout is verified by several git spawns per load. One verified SourceContext per
# title per test keeps the file fast AND removes the load-order sensitivity that made the whole-file
# run fail while the same test passed alone.
@pytest.fixture
def shared():
    """One verified SourceContext per test: fewer git spawns, and no load-order sensitivity.

    F3. The fixture proves the pinned checkout answers BEFORE any test body runs, so a lane whose git
    could not be reached skips here instead of surfacing as a red somewhere further down -- which is
    what made the whole-file run fail on test_check_mode while the same test passed alone. An
    integrity failure is not this: it stays a hard ValueError and still fails.
    """
    from tools.gen2_source_data import load_context, shared_contexts
    with shared_contexts():
        _no_infra(load_context, "gold", root=ROOT)
        yield


def test_clean_view_keeps_the_existing_facts(tmp_path):
    view, why = _view(tmp_path, {"kind": "clean", "sha1": "a" * 40})
    assert why is None and view.kind == "clean"
    assert view.rom_sha1 == "a" * 40 and view.base_sha1 == "a" * 40
    assert view.sites.capture.expected_hex == "aa" and view.binding_sha256 is None
    assert view.anchors[1].offset == 32 and view.anchors[1].hex == "dd"


def test_verified_overlay_view_selects_its_own_executed_bytes(tmp_path):
    view, why = _view(tmp_path, {"kind": "overlay", "sha1": "b" * 40, "base_sha1": "a" * 40},
                      _binding())
    assert why is None, why
    assert view.kind == "overlay" and view.rom_sha1 == "b" * 40
    assert view.sites.capture.expected_hex == "bb"
    assert view.anchors[1].offset == 16 and view.profile_rom.BaseData.flat == 16384


@pytest.mark.parametrize("change,reason", [
    ({"binding_sha256": "0" * 64}, "sha256 differs"),
    ({"sha1": "f" * 40}, "ROM/base sha1 differs"),
    ({"base_sha1": "f" * 40}, "ROM/base sha1 differs"),
])
def test_overlay_view_refuses_a_binding_not_owned_by_the_row(tmp_path, change, reason):
    row = {"kind": "overlay", "sha1": "b" * 40, "base_sha1": "a" * 40, **change}
    view, why = _view(tmp_path, row, _binding())
    assert view is None and reason in why


def test_overlay_view_never_falls_back_when_sidecar_is_missing(tmp_path):
    view, why = _view(tmp_path, {"kind": "overlay", "sha1": "b" * 40,
                               "base_sha1": "a" * 40, "binding_sha256": "0" * 64})
    assert view is None and "sidecar missing" in why


def test_overlay_digest_is_the_canonical_lf_binding_on_windows(tmp_path):
    view, why = _view(tmp_path, {"kind": "overlay", "sha1": "b" * 40,
                               "base_sha1": "a" * 40}, _binding(), newline="\r\n")
    assert why is None and view.sites.capture.expected_hex == "bb"


def test_overlay_cannot_switch_base_facts_even_if_row_and_binding_agree(tmp_path):
    binding = _binding()
    binding["base_sha1"] = "f" * 40
    view, why = _view(tmp_path, {"kind": "overlay", "sha1": "b" * 40,
                               "base_sha1": "f" * 40}, binding)
    assert view is None and "base differs from clean facts" in why


# ── F2: the published-sidecar test must be able to FAIL ─────────────────────────────────
# The committed sidecar is currently byte-identical to the clean pack, so an assertion phrased in
# clean-pack values passes on a view that never opened the sidecar -- exactly the fallback D3 forbids.
# These tests perturb a COPY of the committed sidecar and assert on the perturbed value, which only a
# real sidecar read can produce.
def _perturb(title, mutate):
    binding = json.loads((ROOT / f"data/games/gen2_{title}/overlay/binding.json").read_text(
        encoding="utf-8").replace("\r\n", "\n"))
    mutate(binding)
    return binding, (json.dumps(binding, sort_keys=True, indent=2) + "\n").encode()


def _pack(title):
    directory = ROOT / f"data/games/gen2_{title}"
    return {name: json.loads((directory / f"{file}.json").read_text(encoding="utf-8")) for name, file in (
        ("sites", "engine_signals"), ("checkpoint", "write_checkpoint"),
        ("profile", "profile"), ("area_map", "area_map"))}


def _stage(tmp_path, title, binding, raw):
    path = tmp_path / f"data/games/gen2_{title}/overlay/binding.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def _lua_view(root, data, title, row):
    """Drive the REAL lua/gen2/artifact.lua and return its raw result (table, or (nil, why))."""
    lua = LuaRuntime(unpack_returned_tuples=True)
    module = lua.eval("dofile")((ROOT / "lua/gen2/artifact.lua").as_posix())
    codec = lua.eval("dofile")((ROOT / "lua/json_codec.lua").as_posix())
    return module.view(str(root), codec, lua.table_from(data, recursive=True), title,
                        lua.table_from(row, recursive=True))


@pytest.mark.parametrize("title", TITLES)
def test_published_sidecar_loads_through_the_actual_lua_view(tmp_path, title, shared):
    """The COMMITTED sidecar serves cleanly, staged under tmp so the view reads the file it hashes."""
    raw = (ROOT / f"data/games/gen2_{title}/overlay/binding.json").read_bytes().replace(b"\r\n", b"\n")
    binding = json.loads(raw)
    _stage(tmp_path, title, binding, raw)
    row = {"kind": "overlay", "sha1": binding["rom_sha1"], "base_sha1": binding["base_sha1"],
           "binding_sha256": hashlib.sha256(raw).hexdigest()}
    result = _lua_view(tmp_path, _pack(title), title, row)
    assert not isinstance(result, tuple), result
    assert result.kind == "overlay" and len(result.anchors) == ANCHORS[title]
    assert result.binding_sha256 == row["binding_sha256"]


@pytest.mark.parametrize("title", TITLES)
def test_a_perturbed_sidecar_is_refused_by_the_row_pin(tmp_path, title):
    """A sidecar whose bytes no longer match the catalog row's binding_sha256 must refuse."""
    def mutate(binding):
        site = sorted(binding["sites"])[0]
        binding["sites"][site]["expected_hex"] = "deadbeef"
    binding, raw = _perturb(title, mutate)
    _stage(tmp_path, title, binding, raw)
    original = hashlib.sha256(
        (ROOT / f"data/games/gen2_{title}/overlay/binding.json").read_bytes().replace(b"\r\n", b"\n")
    ).hexdigest()
    row = {"kind": "overlay", "sha1": binding["rom_sha1"], "base_sha1": binding["base_sha1"],
           "binding_sha256": original}
    result = _lua_view(tmp_path, _pack(title), title, row)
    assert isinstance(result, tuple) and "sha256 differs" in result[1]


@pytest.mark.parametrize("title", TITLES)
def test_a_perturbed_sidecar_is_what_the_view_serves(tmp_path, title):
    """And when the row pins the PERTURBED bytes, the view must serve the perturbed fact.

    This assertion cannot be satisfied by the clean pack: `deadbeef` appears nowhere in it, which is
    the property the previous version of this test lacked.
    """
    def mutate(binding):
        site = sorted(binding["sites"])[0]
        binding["sites"][site]["expected_hex"] = "deadbeef"
    binding, raw = _perturb(title, mutate)
    _stage(tmp_path, title, binding, raw)
    site = sorted(binding["sites"])[0]
    row = {"kind": "overlay", "sha1": binding["rom_sha1"], "base_sha1": binding["base_sha1"],
           "binding_sha256": hashlib.sha256(raw).hexdigest()}
    view = _lua_view(tmp_path, _pack(title), title, row)
    assert not isinstance(view, tuple), view
    assert view.sites[site].expected_hex == "deadbeef"
    # The clean fallback cannot satisfy it: prove the same assertion fails on a clean-pack view.
    clean = _lua_view(tmp_path, _pack(title), title, {"kind": "clean", "sha1": binding["rom_sha1"]})
    assert not isinstance(clean, tuple), clean
    assert clean.sites[site].expected_hex != "deadbeef", (
        "the clean pack must NOT contain the sentinel, or this test cannot detect a clean fallback")


# ── F1: a changed site byte is proved by a source operand, or generation refuses ──────────
@pytest.mark.parametrize("site,offset", [("npc_trade_begin", 1034858), ("poison_faint", 329344)])
def test_a_republished_wildcard_operand_byte_refuses(monkeypatch, shared, site, offset):
    """The F1 exploit: `1 << PSN` / `NPCTRADE_GIVEMON` style operands are carried by the ROM, never
    proved by the source. Flipping one in a NEW publication must refuse, not be recorded as a
    reassembly."""
    if not GBC.is_file():
        pytest.skip("locked pokegold.gbc input absent")
    from patch.tools.make_ups import ups_create
    from tools.gen2_artifacts import generate_binding
    from tools.gen2_source_data import load_overlay_context

    ctx = load_overlay_context("gold", root=ROOT)
    image = bytearray(ctx.rom)
    image[offset] ^= 0xFF
    ups = ups_create(ctx.base.rom, bytes(image))
    publication = json.loads((ROOT / "data/gen2/overlay_provenance.json").read_bytes())
    out = publication["outputs"][ctx.artifact]
    out["sha1"] = hashlib.sha1(image).hexdigest()
    out["ups"]["sha256"] = hashlib.sha256(ups).hexdigest()
    provenance_path = (ROOT / "data/gen2/overlay_provenance.json").resolve()
    ups_path = (ROOT / out["ups"]["file"]).resolve()
    original = Path.read_bytes

    def supplied(path):
        if path.resolve() == provenance_path:
            return json.dumps(publication).encode()
        if path.resolve() == ups_path:
            return ups
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", supplied)
    with pytest.raises(ValueError, match="constant-expression operand carried by the ROM"):
        generate_binding("gold", root=ROOT)


@pytest.mark.parametrize("kind", ["site", "header"])
def test_a_new_publication_cannot_repin_unexplained_execution_bytes(monkeypatch, shared, kind):
    if not GBC.is_file():
        pytest.skip("locked pokegold.gbc input absent")
    from patch.tools.make_ups import ups_create
    from tools.gen2_artifacts import generate_binding
    from tools.gen2_source_data import load_overlay_context

    ctx = load_overlay_context("gold", root=ROOT)
    directory = ROOT / "data/games/gen2_gold"
    if kind == "site":
        pack = json.loads((directory / "engine_signals.json").read_text())
        address = pack["titles"]["gold"]["sites"]["battle_faint"]["rom_offset"]
    else:
        # The header's byte 6 is outside the area generator's scalar checks.
        # The artifact boundary still must refuse it rather than adopt a new pin.
        areas = json.loads((directory / "area_map.json").read_text())
        address = areas["257"]["source"]["header_flat"] + 6
    image = bytearray(ctx.rom)
    image[address] ^= 1
    ups = ups_create(ctx.base.rom, bytes(image))
    publication = json.loads((ROOT / "data/gen2/overlay_provenance.json").read_bytes())
    out = publication["outputs"][ctx.artifact]
    out["sha1"] = hashlib.sha1(image).hexdigest()
    out["ups"]["sha256"] = hashlib.sha256(ups).hexdigest()
    provenance_path = (ROOT / "data/gen2/overlay_provenance.json").resolve()
    ups_path = (ROOT / out["ups"]["file"]).resolve()
    original = Path.read_bytes

    def supplied(path):
        if path.resolve() == provenance_path:
            return json.dumps(publication).encode()
        if path.resolve() == ups_path:
            return ups
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", supplied)
    with pytest.raises(ValueError, match="unexplained"):
        generate_binding("gold", root=ROOT)


def test_a_symbol_operand_change_is_accepted_and_names_its_symbol(shared):
    """Positive control for the F1 guard, against REAL provenance derived from the pinned source.

    `battle_faint`'s published window contains `ld a, [wCurBattleMon]`, so bytes 1-2 are a
    symbol-resolved operand. A change there is what a genuine symbol move looks like: it must be
    accepted, and the recorded reason must name the SYMBOL that verified it.
    """
    if not GBC.is_file():
        pytest.skip("locked pokegold.gbc input absent")
    import tools.gen_gen2_engine_signals as G
    from tools.gen2_artifacts import _site_change_reasons
    from tools.gen2_source_data import load_overlay_context

    ctx = load_overlay_context("gold", root=ROOT)
    specs = G.read_specs(ROOT / G.SPEC_PATH)
    binding = json.loads((ROOT / "data/games/gen2_gold/overlay/binding.json").read_text(encoding="utf-8"))
    site = "battle_faint"
    before_hex = binding["sites"][site]["expected_hex"]
    verify = _site_change_reasons(ctx, specs)
    after = bytearray(bytes.fromhex(before_hex))
    after[1] ^= 0xFF   # low byte of the wCurBattleMon operand
    reason = verify(f"/{site}", before_hex, bytes(after).hex())
    assert "wCurBattleMon" in reason, reason
    assert "reassembled" not in reason, "the canned reason must be gone, not merely supplemented"


def test_a_wildcard_change_is_refused_by_the_same_verifier(shared):
    """The negative half of the positive control, same real provenance, same code path."""
    if not GBC.is_file():
        pytest.skip("locked pokegold.gbc input absent")
    import tools.gen_gen2_engine_signals as G
    from tools.gen2_artifacts import _site_change_reasons
    from tools.gen2_source_data import load_overlay_context

    ctx = load_overlay_context("gold", root=ROOT)
    specs = G.read_specs(ROOT / G.SPEC_PATH)
    binding = json.loads((ROOT / "data/games/gen2_gold/overlay/binding.json").read_text(encoding="utf-8"))
    site = "poison_faint"
    before_hex = binding["sites"][site]["expected_hex"]
    after = bytearray(bytes.fromhex(before_hex))
    after[1] ^= 0xFF   # the MON_STATUS constant-expression operand
    with pytest.raises(ValueError, match="constant-expression operand carried by the ROM"):
        _site_change_reasons(ctx, specs)(f"/{site}", before_hex, bytes(after).hex())


def test_a_nested_guard_change_refuses_rather_than_being_reassembled(shared):
    """A changed nested guard prelude has no per-byte source provenance: refuse, do not relabel."""
    if not GBC.is_file():
        pytest.skip("locked pokegold.gbc input absent")
    import tools.gen_gen2_engine_signals as G
    from tools.gen2_artifacts import _site_change_reasons
    from tools.gen2_source_data import load_overlay_context

    ctx = load_overlay_context("gold", root=ROOT)
    specs = G.read_specs(ROOT / G.SPEC_PATH)
    with pytest.raises(ValueError, match="byte-identical"):
        _site_change_reasons(ctx, specs)("/battle_faint/guards/x", "aa", "bb")


# ── F3: a git that could not answer is infrastructure, not a source verdict ──────────────
class _Result:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_git_that_produced_no_diagnostic_is_infrastructure(monkeypatch):
    from tools import gen2_source_data
    monkeypatch.setattr(gen2_source_data.subprocess, "run",
                        lambda *a, **k: _Result(128, "", ""))
    with pytest.raises(gen2_source_data.SourceVerificationUnavailable) as caught:
        gen2_source_data._git(ROOT, "status", "--porcelain")
    assert "INFRASTRUCTURE" in str(caught.value)
    assert not isinstance(caught.value, gen2_source_data.SourceUnavailable)


def test_git_that_reported_a_failure_stays_an_integrity_failure(monkeypatch):
    from tools import gen2_source_data
    monkeypatch.setattr(gen2_source_data.subprocess, "run",
                        lambda *a, **k: _Result(128, "", "fatal: not a git repository"))
    with pytest.raises(ValueError) as caught:
        gen2_source_data._git(ROOT, "status", "--porcelain")
    assert not isinstance(caught.value, gen2_source_data.SourceVerificationUnavailable)
    assert "not a git repository" in str(caught.value)


def test_git_spawn_failure_is_infrastructure(monkeypatch):
    from tools import gen2_source_data
    def boom(*a, **k):
        raise FileNotFoundError(2, "git missing")
    monkeypatch.setattr(gen2_source_data.subprocess, "run", boom)
    with pytest.raises(gen2_source_data.SourceVerificationUnavailable):
        gen2_source_data._git(ROOT, "status")


@pytest.mark.parametrize("diagnostic", [
    "fatal: could not lock config file .git/config: File exists",
    "error: cannot lock ref 'refs/heads/master': Unable to create '...lock': File exists",
    "fatal: index file smaller than expected",
    "error: unable to write new index file: No space left on device",
    "fatal: too many open files",
])
def test_git_lock_and_resource_complaints_are_infrastructure(monkeypatch, diagnostic):
    """git saying it could not DO THE JOB is infrastructure, not a statement about the source.

    A busy shared lane -- several agents and test runs against one checkout -- produces exactly
    these, and none of them is a verdict that the source changed.
    """
    from tools import gen2_source_data
    monkeypatch.setattr(gen2_source_data.subprocess, "run",
                        lambda *a, **k: _Result(128, "", diagnostic))
    with pytest.raises(gen2_source_data.SourceVerificationUnavailable):
        gen2_source_data._git(ROOT, "status", "--porcelain")


@pytest.mark.parametrize("diagnostic", [
    "fatal: not a git repository (or any of the parent directories): .git",
    "fatal: bad object HEAD",
])
def test_git_content_and_repository_complaints_stay_integrity(monkeypatch, diagnostic):
    """These are about the checkout itself, so they keep failing closed as a plain ValueError."""
    from tools import gen2_source_data
    monkeypatch.setattr(gen2_source_data.subprocess, "run",
                        lambda *a, **k: _Result(128, "", diagnostic))
    with pytest.raises(ValueError) as caught:
        gen2_source_data._git(ROOT, "status", "--porcelain")
    assert not isinstance(caught.value, gen2_source_data.SourceVerificationUnavailable)


def test_check_mode_reports_infrastructure_apart_from_a_stale_binding(monkeypatch, capsys):
    """Fails closed, but not with the message a real stale binding produces."""
    from tools import gen2_artifacts
    from tools.gen2_source_data import SourceVerificationUnavailable

    def unavailable(*a, **k):
        raise SourceVerificationUnavailable(ROOT, ("status", "--porcelain"))
    monkeypatch.setattr(gen2_artifacts, "load_overlay_context", unavailable)
    assert gen2_artifacts.main(["--root", str(ROOT), "--title", "gold", "--check"]) == 2
    err = capsys.readouterr().err
    assert "infrastructure" in err
    assert "binding missing or stale" not in err


# ── generation determinism and the published bytes ───────────────────────────────────────
@pytest.mark.parametrize("raw", [b"", b"abc", bytes(range(256)), b"x" * 65537],
                         ids=["empty", "abc", "binary", "large"])
def test_shared_sha256_hashes_actual_bytes(raw):
    lua = LuaRuntime(unpack_returned_tuples=True)
    admission = lua.eval("dofile")((ROOT / "lua/admission.lua").as_posix())
    assert admission.sha256 is not None, "shared admission SHA-256 is not implemented"
    reader = lua.eval("function(read) return function(i) return read(i) end end")(
        lambda i: raw[int(i)])
    assert admission.sha256(reader, len(raw)) == hashlib.sha256(raw).hexdigest()


def test_gold_binding_generation_is_deterministic_and_resolves_execution_bytes(shared):
    if not GBC.is_file():
        pytest.skip("locked pokegold.gbc input absent")
    from tools import gen2_artifacts

    binding = _no_infra(gen2_artifacts.generate_binding, "gold", root=ROOT)
    # The published identity, not a magic number: data/games/gen2_gold/overlay/binding.json
    # (rom_sha1) and data/gen2/overlay_provenance.json (outputs.pokegold.sha1) both carry this
    # digest, and `--check` below proves generation reproduces the committed binding.
    assert binding["rom_sha1"] == "51b076ac7eba099a273ff7aff5c64ccb790825dd"
    assert binding["base_sha1"] == "d8b8a3600a465308c9953dfa04f0081c05bdcb94"
    assert binding["sites"]["battle_faint"]["symbol"] == "UpdateFaintedPlayerMon"
    assert binding["changes"] == [], "the published overlay changes no site byte"
    assert gen2_artifacts.render(binding) == gen2_artifacts.render(
        _no_infra(gen2_artifacts.generate_binding, "gold", root=ROOT))


@pytest.mark.parametrize("ext", ["sym", "map"])
def test_present_overlay_symbols_or_map_with_wrong_hash_are_not_skipped(monkeypatch, shared, ext):
    if not GBC.is_file():
        pytest.skip("locked pokegold.gbc input absent")
    from tools.gen2_source_data import load_overlay_context

    target = (ROOT / f"data/gen2/gold_slink.{ext}").resolve()
    original = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda path: original(path) + b"tampered"
                        if path.resolve() == target else original(path))
    with pytest.raises(ValueError, match="differs from pinned"):
        load_overlay_context("gold", root=ROOT)


def test_overlay_source_context_reconstructs_the_published_gold_rom(shared):
    if not GBC.is_file():
        pytest.skip("locked pokegold.gbc input absent")
    from tools.gen2_source_data import load_overlay_context

    ctx = load_overlay_context("gold", root=ROOT)
    assert hashlib.sha1(ctx.rom).hexdigest() == "51b076ac7eba099a273ff7aff5c64ccb790825dd"
    assert ctx.symbol("wPartyMon1") == ctx.base.symbol("wPartyMon1")
    assert ctx.source_record() == ctx.base.source_record()


def test_check_mode_accepts_the_published_bytes(shared):
    if not GBC.is_file():
        pytest.skip("locked pokegold.gbc input absent")
    from tools.gen2_artifacts import main
    assert _no_infra(main, ["--root", str(ROOT), "--title", "gold", "--check"]) == 0


def test_check_mode_refuses_a_stale_binding(monkeypatch, capsys, shared):
    if not GBC.is_file():
        pytest.skip("locked pokegold.gbc input absent")
    from tools.gen2_artifacts import main

    target = (ROOT / "data/games/gen2_gold/overlay/binding.json").resolve()
    original = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda path: original(path) + b"tampered"
                        if path.resolve() == target else original(path))
    assert _no_infra(main, ["--root", str(ROOT), "--title", "gold", "--check"]) == 1
    assert "binding missing or stale" in capsys.readouterr().err
