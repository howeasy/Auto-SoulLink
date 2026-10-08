"""Polished rand_overlay admission end to end (the Polished counterpart of Gen 2's R3 + R6 beacon).

A Manager-randomized Polished cartridge (server.cartridges.provision: the companion overlay, then the UPR forms jar,
then rom_contract.json with each player's rom_sha1) has a sha1 in no catalog. lua/gen2/polished.lua P.admit admits it
only as rand_overlay when the ROM is the pinned size, holds the patch-0020 overlay anchors ($0070 bridge, $0DA8
lead-in, $7E:4000 service prologue) and its overlay beacon (data/games/polished_crystal/overlay/beacon.json,
tools/gen_polished_beacon.py) re-hashes. The server binds the hello's rehashed rom_sha1 to the contract's per-player
pin (gen2_polished.rom_contract_by_sha1, the generic server.py branch). Qualification stays DEV_OVERLAY_SHA1.

Everything runs on REAL bytes: the pinned release (absent skips, wrong sha1 fails), the overlay from the published
UPS, and two cartridges the real pipeline made with the PINNED forms jar ($SLINK_POLISHED_UPR_JAR, default
F:/slink-work/cache/polished/jar/PokeRandoZX.jar, sha256 in data/upr_jars.json; absent skips). The jar trust check is
REAL; POLISHED_RANDOMIZER_ENABLED, describe_rom's Polished "not ready" flag and cartridges.companion_admitted's
Polished hold are overridden for this fixture only (Manager gates outside this card).

RED CONTROLS (each turns a test here red): skip the server's contract sha1 compare (server.py `got_sha1 != want_sha1`);
drop the beacon call in P.rand_overlay_intact; drop the P.RAND_ANCHORS check there; drop the size check there; make
P.admit's anchors-mode eligible return true without P.rand_overlay_intact (any sha1 admits).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from server import cartridges, upr_pipeline as P, upr_settings as U
from server.adapters.gen2_polished import Gen2PolishedAdapter, scan_randomized
from server.upr_polished_write_domain import audit
from tests.unit.test_mixed_foundations import _session
from tests.unit.test_polished_client import _entry, _memory, _mons, _rig, _run
from tests.unit.test_polished_lua import CLEAN_ROM, PROFILE, REPO, ROOT, _pair, _real

lupa = pytest.importorskip("lupa")

JAR = Path(os.environ.get("SLINK_POLISHED_UPR_JAR", "F:/slink-work/cache/polished/jar/PokeRandoZX.jar"))
OVERLAY_SHA1 = PROFILE["source"]["overlay_sha1"]
COMPANION = "needs the SLink companion patch"


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    """A real randomized pair through server.cartridges.provision, plus the release randomized with no overlay."""
    release, overlay = _real()
    if not JAR.is_file() or shutil.which("java") is None:
        pytest.skip(f"dev forms jar or java absent: {JAR}")
    run = tmp_path_factory.mktemp("polished_rand_run")
    settings = run / "settings.rnqs"
    settings.write_bytes(U.build_spec(dict(U.default_spec(U.FAMILY_POLISHED), wild="area", starters="random",
                                           trainers="unchanged"), family=U.FAMILY_POLISHED))
    describe = P.describe_rom

    def offered(path, jar_fork):                                 # describe_rom still marks Polished "not ready"
        info = describe(path, jar_fork)
        return dict(info, clean=True) if info.get("family") == P.FAMILY_POLISHED else info

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(P, "POLISHED_RANDOMIZER_ENABLED", True)
        mp.setattr(P, "describe_rom", offered)
        admitted = cartridges.companion_admitted                 # cartridges.py still holds the Polished companion
        mp.setattr(cartridges, "companion_admitted",
                   lambda info: info.get("variant") == P.POLISHED_VARIANT or admitted(info))
        result = cartridges.provision(str(run), {"a": str(CLEAN_ROM), "b": str(CLEAN_ROM)}, companion=True,
                                      randomize={"settings_path": str(settings)}, jar=str(JAR))
        clean_out = run / "clean_randomized.gbc"
        P.randomize(str(JAR), str(settings), str(CLEAN_ROM), str(clean_out))
    contract = json.loads((run / "rom_contract.json").read_text(encoding="utf-8"))
    roms = {pid: (run / "roms" / f"{pid}.gbc").read_bytes() for pid in "ab"}
    for pid in "ab":
        assert result["players"][pid]["kind"] == "rand_companion"
        assert hashlib.sha1(roms[pid]).hexdigest() == contract["players"][pid]["rom_sha1"]
    return {"run": run, "release": release, "overlay": overlay, "roms": roms, "contract": contract,
            "clean_rand": clean_out.read_bytes()}


def _admit(rom: bytes):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    reader = lua.eval("function(s) return function(a) return s:byte(a + 1) end end")(rom)
    deps = lua.table_from({"root": ROOT, "rom_size": len(rom), "read_rom_u8": reader, "title": "polished"})
    return _pair(_entry(lua).admit_polished(deps))


def _flip(rom: bytes, offset: int) -> bytes:
    out = bytearray(rom)
    out[offset] ^= 0x01
    return bytes(out)


# ── (a) the pinned overlay is unchanged ──────────────────────────────────────

def test_the_pinned_overlay_still_admits_as_overlay():
    decision, why = _admit(_real()[1])
    assert why is None, why
    assert (decision.kind, decision.admitted_by, decision.rom_sha1) == ("overlay", "sha1", OVERLAY_SHA1)
    assert decision.qualification == "DEV_OVERLAY_SHA1" and decision.overlay_sha1 is None


# ── (b) real UPR outputs admit as rand_overlay ───────────────────────────────

@pytest.mark.parametrize("pid", ["a", "b"])
def test_a_real_randomized_cartridge_admits_as_rand_overlay(made, pid):
    rom = made["roms"][pid]
    decision, why = _admit(rom)
    assert why is None, why
    assert (decision.kind, decision.admitted_by, decision.title) == ("rand_overlay", "anchors", "polished")
    assert decision.rom_sha1 == made["contract"]["players"][pid]["rom_sha1"] != OVERLAY_SHA1
    assert decision.overlay_sha1 == OVERLAY_SHA1 and decision.qualification == "DEV_OVERLAY_SHA1"
    assert decision.foundation == "gen2_polished"


def test_upr_wrote_data_only_and_the_capture_site_holds(made):
    """UPR writes data tables, never code: no overlay span, bank $7E or header byte moved, and the one engine site
    the client binds (engine_signals capture_party, 03:652B) keeps its expected bytes on both cartridges."""
    site = json.loads((REPO / "data/games/polished_crystal/engine_signals.json").read_text(encoding="utf-8"))
    site = site["titles"]["polished_crystal"]["sites"]["capture_party"]
    at = site["bank"] * 0x4000 + site["addr"] - 0x4000
    want = bytes.fromhex(site["expected_hex"])
    assert made["overlay"][at:at + len(want)] == want                  # positive control on the overlay itself
    for rom in made["roms"].values():
        report = audit(made["overlay"], rom)
        assert report["changed"] > 1000, "the pair was not randomized"
        assert report["header"] == report["ups_hits"] == report["bank7e_hits"] == []
        assert rom[at:at + len(want)] == want
    assert made["roms"]["a"] != made["roms"]["b"]


# ── (c) every broken fact refuses, with a reason ─────────────────────────────

BEACON_ONLY = [0x70 + 10, 0x16A, 0x1F8000 + 40]  # overlay bytes past the anchors: only the beacon covers them. 0x14E (the GB global checksum) is MASKED out of the beacon since the title slice (a re-stamped version perturbs it); 0x16A is the main-menu hook operand, a hashed overlay byte


@pytest.mark.parametrize("offset", BEACON_ONLY)
def test_a_flipped_overlay_byte_refuses_on_the_beacon(made, offset):
    decision, why = _admit(_flip(made["roms"]["a"], offset))
    assert decision is None and "unknown artifact SHA-1" in why and "overlay beacon mismatch" in why, why


@pytest.mark.parametrize("offset", [0x70, 0xDA8 + 3, 0x1F8000 + 15])
def test_a_flipped_anchor_byte_refuses_as_no_companion(made, offset):
    decision, why = _admit(_flip(made["roms"]["a"], offset))
    assert decision is None and "unknown artifact SHA-1" in why and COMPANION in why, why


@pytest.mark.parametrize("shape", ["padded", "truncated"])
def test_a_wrong_size_rom_refuses(made, shape):
    rom = made["roms"]["a"]
    rom = rom + b"\xff" * 0x4000 if shape == "padded" else rom[:-0x4000]
    decision, why = _admit(rom)
    assert decision is None and "ROM size does not match" in why, why


def test_the_randomized_release_without_the_overlay_refuses(made):
    assert audit(made["release"], made["clean_rand"])["changed"] > 1000
    decision, why = _admit(made["clean_rand"])
    assert decision is None and "unknown artifact SHA-1" in why and COMPANION in why, why


# ── the composed client on a randomized cartridge ────────────────────────────

def _client(made, pid):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    deps, io, log = _rig(lua, made["roms"][pid], _memory(_mons()))
    deps["player"] = pid
    parts, why = _pair(_entry(lua).build(deps))
    assert why is None, why
    parts.client.start(parts.client)
    _run(io, parts.client, 20)
    hellos = [json.loads(line) for line in log.sent.values() if json.loads(line)["event"] == "hello"]
    assert len(hellos) == 1, list(log.lines.values())
    return parts, hellos[0], log


def test_a_randomized_cartridge_composes_a_dev_grade_client(made):
    parts, hello, log = _client(made, "a")
    sha = made["contract"]["players"]["a"]["rom_sha1"]
    assert parts.artifact_kind == "rand_overlay" and parts.runtime_rom_sha1 == sha
    assert parts.qualification == "DEV_OVERLAY_SHA1" and parts.production_admitted is False
    assert (hello["artifact_kind"], hello["rom_sha1"], hello["rom_type"]) == ("rand_overlay", sha, "polished_crystal")
    assert hello["companion_abi"] == 3 and len(log.writes) == 0
    # the capture site (an engine site) plus the client two PC holds: the overworld frame wait and the battle hold
    assert set(log.hooks.values()) == {"SLink-gen2-polished:capture_party", "SLink-gen2-checkpoint",
                                       "SLink-gen2-battle-hold", "SLink-gen2-polished:battle_faint_copyback_return",
                                       "SLink-gen2-polished:battle_faint", "SLink-gen2-polished:whiteout_before_heal",
                                       "SLink-gen2-polished:rival_swap_gate"}
    assert not any("engine sites refused" in line for line in log.lines.values())


# ── (d) the real server admits the pair and enforces the contract pin ────────

def _data_dir(made, tmp_path, contract):
    shutil.copytree(made["run"] / "roms", tmp_path / "roms")
    if contract is not None:
        (tmp_path / "rom_contract.json").write_text(json.dumps(contract), encoding="utf-8")
    return str(tmp_path)


@pytest.mark.asyncio
async def test_the_real_server_admits_the_randomized_pair_and_adopts_its_tables(made, tmp_path):
    from server.server import SLinkServer
    srv = SLinkServer(data_dir=_data_dir(made, tmp_path, made["contract"]))
    sessions = [await _session(srv) for _ in "ab"]          # one connection per player
    try:
        for pid, (send, _close) in zip("ab", sessions, strict=True):
            await send(_client(made, pid)[1])
            assert srv.admission[pid]["state"] == "admitted", srv.admission
            adopted = srv._player_adapters[pid]
            mine = Gen2PolishedAdapter(artifact_kind="rand_overlay")
            mine.use_rom_encounters(scan_randomized(made["roms"][pid]))
            assert adopted._rom_adopted and adopted._tables == mine._tables
            assert adopted._tables != Gen2PolishedAdapter(artifact_kind="overlay")._tables
        assert srv._player_adapters["a"]._tables != srv._player_adapters["b"]._tables
        assert srv.state.rom_type == "polished_crystal" and srv.state.artifact_kind == "rand_overlay"
        assert srv.adapter.game_id == "gen2_polished" and srv.adapter.randomized is True
    finally:
        for _send, close in sessions:
            await close()


@pytest.mark.asyncio
async def test_a_hello_whose_sha1_is_not_the_contract_pin_is_refused(made, tmp_path):
    from server.server import SLinkServer
    swapped = json.loads(json.dumps(made["contract"]))
    swapped["players"]["a"]["rom_sha1"] = made["contract"]["players"]["b"]["rom_sha1"]
    srv = SLinkServer(data_dir=_data_dir(made, tmp_path, swapped))
    send, close = await _session(srv)
    try:
        await send(_client(made, "a")[1])
        assert srv.admission["a"]["state"] == "rejected"
        assert "not the ROM built for player a" in srv.admission["a"]["reason"]
        assert not srv.state.rom_type and not srv.state.artifact_kind
    finally:
        await close()


@pytest.mark.asyncio
async def test_a_randomized_hello_with_no_contract_is_refused(made, tmp_path):
    from server.server import SLinkServer
    srv = SLinkServer(data_dir=_data_dir(made, tmp_path, None))
    send, close = await _session(srv)
    try:
        await send(_client(made, "a")[1])
        assert srv.admission["a"]["state"] == "rejected"
        assert "made by the Manager" in srv.admission["a"]["reason"]
    finally:
        await close()


def test_the_beacon_is_current_and_the_anchors_are_the_pipelines():
    """The generator's --check (absent release skips) and the Lua anchors equal upr_pipeline's overlay signature."""
    import tools.gen_polished_beacon as G
    if not CLEAN_ROM.is_file():
        pytest.skip("pinned Polished release ROM absent")
    assert G.main(["--rom", str(CLEAN_ROM), "--check"]) == 0
    overlay = _real()[1]
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    anchors = lua.eval(f'dofile("{ROOT}/lua/gen2/polished.lua")').RAND_ANCHORS
    assert P._is_slink_polished_overlay(overlay)
    stripped = bytearray(overlay)
    for anchor in anchors.values():
        assert overlay[anchor.offset:anchor.offset + len(anchor.hex) // 2].hex() == anchor.hex
        stripped[anchor.offset] ^= 0x01
        assert not P._is_slink_polished_overlay(bytes(stripped))           # each Lua anchor is one the pipeline reads
        stripped[anchor.offset] ^= 0x01
