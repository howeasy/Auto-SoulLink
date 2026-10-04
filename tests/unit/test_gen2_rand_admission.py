"""R3 (owner "open C-5"): runtime admission of a randomized SLink companion Gen 2 cartridge (rand_overlay).

lua/gen2/entry.lua admits an unknown sha1 only by its activated overlay row's anchors, the companion pins
(Entry.COMPANION_PINS at the binding's builder_substitutions) and the overlay beacon (every overlay-changed byte);
a randomized clean cartridge is refused for the missing companion. The server binds the hello to the contract's rom_sha1 (server.py `rom_contract_by_sha1`).

The randomized cartridge here is SYNTH (disclosed): the real overlay (the clean pret build + patch/dist/SLink-<T>.ups)
with every Johto grass species byte of the first wild entry rewritten, the way UPR's wild randomization writes them;
docs/gen2/RANDOMIZER.md proved UPR never writes an anchor, an overlay hunk or the header. Clean builds absent skip;
a clean build at the wrong sha1 fails.
"""
import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime

from patch.tools.make_ups import ups_apply
from server.adapters import get_adapter
from server.server import SLinkServer

ROOT = Path(__file__).resolve().parents[2]
ROM_TYPE = {"crystal": "Crystal", "gold": "Gold", "silver": "Silver"}
PINNED_ABI = 3   # data/games/gen2_*/profile.json overlay.abi
_GS_PINS = {"DelayFrame": 0x032E, "MainMenuJoypadLoop": 0x5B0A}
COMPANION_PINS = {"crystal": {"DelayFrame": 0x045A, "MainMenuJoypadLoop": 0x49DE4}, "gold": _GS_PINS, "silver": _GS_PINS}


def _binding(title):
    return json.loads((ROOT / f"data/games/gen2_{title}/overlay/binding.json").read_text(encoding="utf-8"))


def _clean(title):
    profile = json.loads((ROOT / f"data/games/gen2_{title}/profile.json").read_text())["titles"][title]
    source = "pokecrystal" if title == "crystal" else "pokegold"
    path = ROOT / f".cache/gen2-build/{source}/{profile['artifact']}.gbc"
    if not path.is_file():
        pytest.skip(f"pinned Gen 2 build absent: {path}")
    image = path.read_bytes()
    assert hashlib.sha1(image).hexdigest() == profile["rom_sha1"], f"{path} is not the pinned build"
    return image


def _overlay(title):
    image = ups_apply(_clean(title), (ROOT / f"patch/dist/SLink-{title.capitalize()}.ups").read_bytes())
    assert hashlib.sha1(image).hexdigest() == _binding(title)["rom_sha1"], "UPS output is not the bound overlay"
    return image


def _anchor_bytes(title):
    """Every flat offset an admission anchor reads (sites, checkpoint, map headers) -- a SYNTH edit must avoid them."""
    binding, taken = _binding(title), set()
    spans = [(s["rom_offset"], s["expected_hex"]) for s in binding["sites"].values()]
    spans += [(a["rom_offset"], a["expected_hex"]) for a in binding["checkpoint"]["primary"]["anchors"].values()]
    spans += [(a["offset"], a["hex"]) for a in binding["header_anchors"]]
    for offset, hexed in spans:
        taken.update(range(offset, offset + len(hexed) // 2))
    return taken


def _randomize(image, title):
    """SYNTH wild randomization: the first JohtoGrassWildMons entry's 21 species bytes (map, rates, 3x7 level/species)."""
    out, flat = bytearray(image), _binding(title)["profile_rom"]["JohtoGrassWildMons"]["flat"]
    edits = [flat + 5 + 2 * slot + 1 for slot in range(21)]
    assert not set(edits) & _anchor_bytes(title)
    for offset in edits:
        out[offset] = out[offset] % 251 + 1
    assert bytes(out) != image
    return bytes(out)


def _admit(image):
    lua = LuaRuntime(unpack_returned_tuples=True)
    entry = lua.eval("dofile")((ROOT / "lua/gen2/entry.lua").as_posix())
    reader = lua.eval("function(img) return function(a) return img:byte(a + 1) end end")(image)
    result = entry.admit(lua.table(root=ROOT.as_posix(), rom_size=len(image), read_rom_u8=reader))
    return result if isinstance(result, tuple) else (result, None)


# --- Lua: rand_overlay admission --------------------------------------------------------------------------------

def test_companion_pins_are_the_bound_substitutions_at_their_overlay_symbols():
    """Entry.COMPANION_PINS (flat offsets) == data/gen2/<title>_slink.sym for every builder_substitutions symbol,
    and that sym is the one the binding pins."""
    lua = LuaRuntime(unpack_returned_tuples=True)
    entry = lua.eval("dofile")((ROOT / "lua/gen2/entry.lua").as_posix())
    for title in ("crystal", "gold", "silver"):
        binding = _binding(title)
        raw = (ROOT / f"data/gen2/{title}_slink.sym").read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(raw).hexdigest() == binding["sym_sha256"]
        symbols = {}
        for line in raw.decode().splitlines():
            parts = line.split()
            if len(parts) == 2 and ":" in parts[0]:
                bank, addr = (int(x, 16) for x in parts[0].split(":"))
                symbols.setdefault(parts[1], addr if bank == 0 else bank * 0x4000 + addr - 0x4000)
        pins = dict(entry.COMPANION_PINS[title].items())
        edits = binding["builder_substitutions"]
        assert edits and {e["symbol"] for e in edits} == set(pins)
        for edit in edits:
            assert pins[edit["symbol"]] == symbols[edit["symbol"]], (title, edit["symbol"])
            assert edit["after_hex"] != edit["before_hex"]


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_anchors_admit_a_randomized_overlay_with_an_unknown_sha1(title):
    overlay = _overlay(title)
    image = _randomize(overlay, title)
    decision, why = _admit(image)
    assert why is None, why
    assert (decision.kind, decision.title, decision.admitted_by) == ("rand_overlay", title, "anchors")
    assert decision.rom_sha1 == hashlib.sha1(image).hexdigest() != hashlib.sha1(overlay).hexdigest()
    assert decision.overlay_sha1 == hashlib.sha1(overlay).hexdigest()
    assert decision.binding_sha256 is not None
    exact, why = _admit(overlay)                                      # the overlay itself stays a sha1 admit
    assert why is None and (exact.kind, exact.admitted_by) == ("overlay", "sha1")


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_a_randomized_clean_cartridge_is_refused_for_the_companion(title):
    image = _randomize(_clean(title), title)
    decision, why = _admit(image)
    assert decision is None
    assert "unknown artifact SHA-1" in why and "needs the SLink companion patch" in why and title in why


@pytest.mark.parametrize("pick", ["pin", "site", "checkpoint", "header"])
def test_a_randomized_overlay_with_a_flipped_anchor_byte_is_refused(pick):
    binding, image = _binding("crystal"), bytearray(_randomize(_overlay("crystal"), "crystal"))
    offset = {"pin": 0x045A + 1,                                      # DelayFrame: call SlinkDelayFrameBridge
              "site": next(iter(binding["sites"].values()))["rom_offset"],
              "checkpoint": next(iter(binding["checkpoint"]["primary"]["anchors"].values()))["rom_offset"],
              "header": binding["header_anchors"][0]["offset"]}[pick]
    image[offset] ^= 0x01
    decision, why = _admit(bytes(image))
    assert decision is None and "unknown artifact SHA-1" in why, why


def test_a_randomized_overlay_under_another_titles_header_is_refused():
    image = bytearray(_randomize(_overlay("crystal"), "crystal"))
    image[0x134:0x13F] = b"POKEMON_GLD"
    decision, why = _admit(bytes(image))
    assert decision is None and "unknown artifact SHA-1" in why, why


def test_a_truncated_randomized_overlay_is_refused():
    """A short flat ROM domain must refuse, not admit on the anchors it happens to cover (review F-2)."""
    image = _randomize(_overlay("crystal"), "crystal")
    decision, why = _admit(image[:len(image) // 2])
    assert decision is None and "unknown artifact SHA-1" in why, why


def _beacon(title):
    return json.loads((ROOT / f"data/games/gen2_{title}/overlay/beacon.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_a_clean_rom_with_only_the_two_hook_pins_is_refused_by_the_beacon(title):
    """Review F-1 (cx-63dc558a): the two hook pins are 7 of the overlay's ~9k changed bytes. The overlay beacon
    (tools/gen_gen2_beacon.py) re-hashes every one, so pins alone no longer admit."""
    image = bytearray(_randomize(_clean(title), title))
    for edit in _binding(title)["builder_substitutions"]:
        offset, after = COMPANION_PINS[title][edit["symbol"]], bytes.fromhex(edit["after_hex"])
        image[offset:offset + len(after)] = after
    decision, why = _admit(bytes(image))
    assert decision is None, decision
    assert "unknown artifact SHA-1" in why and "overlay beacon mismatch" in why and title in why, why


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
@pytest.mark.parametrize("where", ["first", "middle", "last"])
def test_a_randomized_overlay_with_a_flipped_beacon_byte_is_refused(title, where):
    """Any byte the overlay changed, not only an anchor or a pin: the first, the largest span's middle, the last."""
    spans = _beacon(title)["spans"]
    big = max(spans, key=lambda s: s["length"])
    offset = {"first": spans[0]["offset"], "middle": big["offset"] + big["length"] // 2,
              "last": spans[-1]["offset"] + spans[-1]["length"] - 1}[where]
    image = bytearray(_randomize(_overlay(title), title))
    image[offset] ^= 0x01
    decision, why = _admit(bytes(image))
    assert decision is None and "unknown artifact SHA-1" in why and "overlay beacon mismatch" in why, why


# --- server: the hello binds the contract's rom_sha1 -----------------------------------------------------------

SHA_A, SHA_B = "a" * 40, "b" * 40


def _server(tmp_path):
    (tmp_path / "rom_contract.json").write_text(json.dumps({
        "upr_version": "4.6.1", "settings_sha256": "0" * 64, "categories": ["wild"],
        "players": {"a": {"fingerprint": "", "rom_sha1": SHA_A, "seed": "1"},
                    "b": {"fingerprint": "", "rom_sha1": SHA_B, "seed": "2"}}}))
    return SLinkServer(data_dir=str(tmp_path))


def _hello(player="a", sha=SHA_A, kind="rand_overlay", **extra):
    msg = {"event": "hello", "player": player, "rom_type": "Crystal", "artifact_kind": kind,
           "companion_abi": PINNED_ABI, "trainer_name": "Alice", "ot_id": "30B8", "has_pokeballs": True,
           "party": [], "rom_sha1": sha}
    msg.update(extra)
    return {k: v for k, v in msg.items() if v is not None}


@pytest.mark.parametrize("sha,state,words", [
    (SHA_A, "admitted", "matches"),
    (SHA_A.upper(), "admitted", "matches"),
    (SHA_B, "rejected", "not the ROM built for player a"),          # the partner's cartridge
    ("c" * 40, "rejected", "not the ROM built for player a"),
    (None, "rejected", "did not report its cartridge sha1"),
    ("", "rejected", "did not report its cartridge sha1"),
])
def test_the_server_binds_a_gen2_hello_to_the_contracts_rom_sha1(tmp_path, sha, state, words):
    srv = _server(tmp_path)
    srv.adapter = get_adapter("gen2_gsc", rom_type="Crystal")
    verdict = srv._decide_admission("a", _hello(sha=sha))
    assert verdict["state"] == state and words in verdict["reason"], verdict


def test_a_contract_with_no_sha1_for_the_player_refuses(tmp_path):
    srv = _server(tmp_path)
    srv.adapter = get_adapter("gen2_gsc", rom_type="Crystal")
    srv._rom_contract["players"]["a"] = {"fingerprint": "", "rom_sha1": "", "seed": "1"}
    verdict = srv._decide_admission("a", _hello())
    assert verdict["state"] == "rejected" and "names no cartridge" in verdict["reason"]


def test_a_contracted_run_refuses_the_unrandomized_overlay(tmp_path):
    """The plain overlay's sha1 is not the cartridge the Manager built: refused by the same sha1 pin."""
    srv = _server(tmp_path)
    srv.adapter = get_adapter("gen2_gsc", rom_type="Crystal")
    verdict = srv._decide_admission("a", _hello(sha=_binding("crystal")["rom_sha1"], kind="overlay"))
    assert verdict["state"] == "rejected" and "not the ROM built" in verdict["reason"]


def test_a_randomized_hello_without_a_contract_is_refused(tmp_path):
    """No contract means nothing vouches for a rand_overlay cartridge (the sha1 pin is the only binding)."""
    srv = SLinkServer(data_dir=str(tmp_path))
    srv.adapter = get_adapter("gen2_gsc", rom_type="Crystal")
    verdict = srv._decide_admission("a", _hello())
    assert verdict["state"] == "rejected" and "made by the Manager" in verdict["reason"], verdict


async def _session(srv):
    tcp = await asyncio.start_server(srv.handle_client, "127.0.0.1", 0)
    r, w = await asyncio.open_connection("127.0.0.1", tcp.sockets[0].getsockname()[1])

    async def send(msg):
        w.write((json.dumps(msg) + "\n").encode())
        await w.drain()
        return json.loads(await asyncio.wait_for(r.readline(), 3))

    async def close():
        w.close()
        tcp.close()
        await tcp.wait_closed()
    return send, close


@pytest.mark.asyncio
async def test_a_matching_rand_overlay_hello_commits_a_randomized_companion_run(tmp_path):
    srv = _server(tmp_path)
    send, close = await _session(srv)
    try:
        await send(_hello())
        assert srv.admission["a"]["state"] == "admitted", srv.admission
        assert srv.state.rom_type == "Crystal" and srv.state.artifact_kind == "rand_overlay"
        assert srv.adapter.randomized is True
        assert srv.adapter.supports_info_panel() and srv.adapter.native_trade_ui()
    finally:
        await close()


@pytest.mark.asyncio
async def test_a_rand_overlay_hello_with_the_wrong_sha1_commits_nothing(tmp_path):
    srv = _server(tmp_path)
    send, close = await _session(srv)
    try:
        await send(_hello(sha=SHA_B))
        assert srv.admission["a"]["state"] == "rejected"
        assert "not the ROM built for player a" in srv.admission["a"]["reason"]
        assert not srv.state.rom_type and not srv.state.artifact_kind and not srv.state.player_identity
    finally:
        await close()
