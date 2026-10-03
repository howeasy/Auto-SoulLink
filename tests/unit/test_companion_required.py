"""Patch-first (owner 2026-10-02): the SLink companion patch is REQUIRED for Red/Blue, pureRGB,
FireRed/LeafGreen/Emerald and Radical Red (and Crystal/Gold/Silver: test_companion_required_gen2.py).
A clean cartridge is refused by the launcher (Lua) and by the server at the hello; Yellow, Archipelago
builds and the Emerald Expansion stay admitted clean.

Three layers, each tested on its own so a regression in one cannot hide behind another:
  1. the adapter's `companion_refusal(hello)` (a class lookup the server asks before any state moves),
  2. the server's hello seam (a refused hello leaves a HUD line + identity_error, nothing else),
  3. each generation's Lua launcher gate, run under lupa.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os

import pytest

from server.adapters import adapter_class_for_rom_type
from server.server import SLinkServer

lupa = pytest.importorskip("lupa", reason="lupa is needed to execute the launchers")

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
REASON = "needs the SLink companion patch"


def _refusal(hello):
    cls = adapter_class_for_rom_type(hello["rom_type"])
    assert cls is not None, hello
    return cls.companion_refusal(hello)


# ── 1. the adapters ────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rom_type", ["Red", "Blue", "red", "blue"])
def test_gen1_rby_refuses_a_cartridge_with_no_companion_mailbox(rom_type):
    for hello in ({"rom_type": rom_type, "artifact_kind": "clean", "panel": False},
                  {"rom_type": rom_type, "artifact_kind": "named", "panel": False},
                  {"rom_type": rom_type, "artifact_kind": "rand"},                 # no panel field at all
                  {"rom_type": rom_type, "artifact_kind": "clean", "panel": None}):
        assert REASON in _refusal(hello) and "Manager or /patcher" in _refusal(hello), hello


@pytest.mark.parametrize("rom_type", ["Red", "Blue", "red", "blue"])
@pytest.mark.parametrize("kind", ["named", "clean", "rand"])
def test_gen1_rby_admits_a_cartridge_that_reports_the_mailbox(rom_type, kind):
    assert _refusal({"rom_type": rom_type, "artifact_kind": kind, "panel": True}) is None


def test_patched_never_changes_the_callers_artifact_kind():
    from tests.unit.companion_evidence import patched
    for rom_type in ("red", "firered", "emerald", "firered_rr"):
        assert patched({"rom_type": rom_type, "artifact_kind": "clean"})["artifact_kind"] == "clean", rom_type
    # pureRGB's evidence IS the kind: a clean pure hello must stay clean (and be refused), never be upgraded
    assert patched({"rom_type": "purered", "artifact_kind": "clean"})["artifact_kind"] == "clean"
    assert patched({"rom_type": "purered"})["artifact_kind"] == "overlay"


def test_a_patched_red_still_pairs_with_a_clean_yellow():
    """pairing_kind keeps mapping named -> clean on purpose: Yellow stays admitted clean and a patched
    Red/Blue (kind named) must keep linking with it, the family rule (Red, Blue and Yellow share one run)."""
    from server.adapters.gen1_rby import Gen1Adapter
    assert Gen1Adapter.pairing_kind("named") == Gen1Adapter.pairing_kind("clean") == "clean"


@pytest.mark.parametrize("rom_type", ["PureRed", "PureBlue", "PureGreen", "purered", "pureblue", "puregreen"])
def test_purergb_refuses_clean_and_admits_the_overlay(rom_type):
    for kind in ("clean", "rand", "named"):
        assert REASON in _refusal({"rom_type": rom_type, "artifact_kind": kind, "panel": True}), kind
    assert REASON in _refusal({"rom_type": rom_type})                               # absent kind == clean
    for kind in ("overlay", "rand_overlay"):
        assert _refusal({"rom_type": rom_type, "artifact_kind": kind}) is None, kind


GEN3 = {"firered": 2, "leafgreen": 2, "emerald": 2, "firered_rr": 1}   # title -> the ABI its pack pins
KINDS = ("clean", "named", "rand", "companion", "rand_companion", "overlay", None)


@pytest.mark.parametrize("rom_type", GEN3)
@pytest.mark.parametrize("kind", KINDS)
def test_gen3_without_the_cartridges_own_evidence_is_refused_whatever_kind_it_declares(rom_type, kind):
    """Review F1/F2: the gate asks the CARTRIDGE (the hello's companion_abi, published only when its own
    companion mailbox is live), never the launcher's artifact_kind. A randomized cartridge declares `rand` on
    the wire with or without the companion, so `rand` and `companion` carry no weight on their own."""
    hello = {"rom_type": rom_type} if kind is None else {"rom_type": rom_type, "artifact_kind": kind}
    assert REASON in _refusal(hello)


@pytest.mark.parametrize("rom_type,abi", GEN3.items())
@pytest.mark.parametrize("kind", KINDS)
def test_gen3_with_the_pinned_abi_is_admitted_for_every_kind_including_randomized(rom_type, abi, kind):
    hello = {"rom_type": rom_type, "companion_abi": abi}
    if kind is not None:
        hello["artifact_kind"] = kind
    assert _refusal(hello) is None


@pytest.mark.parametrize("rom_type,abi", GEN3.items())
@pytest.mark.parametrize("bad", [0, 3, True, "2", None, 1.0])
def test_gen3_evidence_must_be_the_exact_pinned_abi(rom_type, abi, bad):
    if bad == abi:
        pytest.skip("that value is the pinned ABI")
    assert REASON in _refusal({"rom_type": rom_type, "artifact_kind": "companion", "companion_abi": bad})


def test_gen3_radical_red_and_the_rest_pin_different_abis():
    # pack-driven: the number comes from each pack's profile.json native.ABI, not from the title name
    assert _refusal({"rom_type": "firered_rr", "companion_abi": 2}) is not None
    assert _refusal({"rom_type": "firered", "companion_abi": 1}) is not None
    from server.adapters import gen3_frlge
    assert [gen3_frlge._companion_abi(p) for p in ("gen3_frlg", "gen3_emerald", "gen3_rr")] == [2, 2, 1]
    assert gen3_frlge._companion_abi("gen3_missing") is None   # a pack with no profile pins nothing: refuse


@pytest.mark.parametrize("hello", [
    {"rom_type": "Yellow", "artifact_kind": "clean"}, {"rom_type": "yellow", "artifact_kind": "named"},
    {"rom_type": "red_ap", "artifact_kind": "clean"}, {"rom_type": "blue_ap", "artifact_kind": "clean"},
    {"rom_type": "firered_ap", "artifact_kind": "clean"}, {"rom_type": "leafgreen_ap", "artifact_kind": "clean"},
])
def test_the_exempt_titles_stay_admitted_clean(hello):
    assert _refusal(hello) is None


def test_the_emerald_expansion_adapter_inherits_the_rule_but_is_not_listed():
    # Unrouted today (adapter_class_for_rom_type is None), so ask the class itself: it subclasses
    # Gen3Adapter, and its rom_type must not be in the companion set -- the Gen 3 lane flips it later.
    from server.adapters.gen3_expansion import Gen3ExpansionAdapter
    hello = {"rom_type": "emerald_expansion_28877d73", "artifact_kind": "clean"}
    assert Gen3ExpansionAdapter.companion_refusal(hello) is None


@pytest.mark.parametrize("rom_type", ["heartgold", "platinum", "pokemon_black", "pokemon_white_2"])
def test_gen4_and_gen5_are_untouched(rom_type):
    cls = adapter_class_for_rom_type(rom_type)
    assert cls is None or cls.companion_refusal({"rom_type": rom_type, "artifact_kind": "clean"}) is None


def test_the_default_is_inert():
    from server.adapters.base import GameRulesAdapter
    assert GameRulesAdapter.companion_refusal({"rom_type": "anything", "artifact_kind": "clean"}) is None


# ── 2. the server's hello seam ─────────────────────────────────────────────────────────────

async def _session(srv):
    tcp = await asyncio.start_server(srv.handle_client, "127.0.0.1", 0)
    port = tcp.sockets[0].getsockname()[1]
    r, w = await asyncio.open_connection("127.0.0.1", port)

    async def send(msg):
        w.write((json.dumps(msg) + "\n").encode())
        await w.drain()
        return json.loads(await asyncio.wait_for(r.readline(), 20))   # a loaded CI/dev box

    async def close():
        w.close()
        tcp.close()
        await tcp.wait_closed()
    return send, close


def _hello(rom_type, **extra):
    return {"event": "hello", "player": "a", "rom_type": rom_type, "trainer_name": "Alice",
            "ot_id": "30B8", "has_pokeballs": True, **extra}


@pytest.mark.asyncio
async def test_a_clean_companion_title_is_refused_at_the_hello_and_a_patched_one_clears_it(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        reply = await send(_hello("red", artifact_kind="clean", panel=False))
        assert any(c.get("cmd") == "hud_show" and "COMPANION" in c.get("text", "") for c in reply["commands"])
        assert REASON in srv.state.identity_error["a"] and "Manager or /patcher" in srv.state.identity_error["a"]
        assert not srv.state.rom_type, "a refused hello must not commit the run to the cartridge"
        # nothing else gets through while the refusal stands
        await send({"event": "area_enter", "player": "a", "area_id": "route_1"})
        assert "route_1" not in srv.state.area_states
        # the patched cartridge (it reports the mailbox) connects
        await send(_hello("red", artifact_kind="named", panel=True))
        assert not srv.state.identity_error.get("a")
        assert srv.state.rom_type == "red"
    finally:
        await close()


@pytest.mark.asyncio
@pytest.mark.parametrize("rom_type,kind", [("emerald", "clean"), ("firered_rr", "clean"), ("firered", "clean"),
                                           ("purered", "clean"), ("purered", "rand"), ("blue", "rand")])
async def test_every_family_is_refused_by_the_server_when_clean(tmp_path, rom_type, kind):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        await send(_hello(rom_type, artifact_kind=kind))
        assert REASON in srv.state.identity_error["a"]
        assert not srv.state.rom_type
    finally:
        await close()


@pytest.mark.asyncio
async def test_a_companion_hello_carrying_another_packs_abi_is_refused_on_the_wire(tmp_path):
    """Firered pins ABI 2; a hello that says "companion" with Radical Red's ABI 1 is cross-pack evidence."""
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        reply = await send(_hello("firered", artifact_kind="companion", companion_abi=1))
        assert any(c.get("cmd") == "hud_show" and "COMPANION" in c.get("text", "") for c in reply["commands"])
        assert REASON in srv.state.identity_error["a"]
        assert not srv.state.rom_type
    finally:
        await close()


@pytest.mark.asyncio
@pytest.mark.parametrize("rom_type", ["firered", "leafgreen", "emerald"])
async def test_a_randomized_gen3_hello_needs_the_mailbox_evidence_on_the_wire(tmp_path, rom_type):
    """Review F1: randomized-clean used to be admitted (`rand` passed the adapter). With no companion_abi the
    hello is rejected for the companion; with the cartridge's mailbox evidence it gets past this gate (the
    randomized-ROM content binding is a separate, later check; Radical Red cannot be randomized at all)."""
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        await send(_hello(rom_type, artifact_kind="rand"))
        assert REASON in srv.state.identity_error["a"] and not srv.state.rom_type
        await send(_hello(rom_type, artifact_kind="rand", companion_abi=GEN3[rom_type]))
        assert REASON not in (srv.state.identity_error.get("a") or "")
    finally:
        await close()


@pytest.mark.asyncio
@pytest.mark.parametrize("rom_type", ["yellow", "red_ap", "firered_ap"])
async def test_an_exempt_clean_title_connects(tmp_path, rom_type):
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        await send(_hello(rom_type, artifact_kind="clean"))
        assert not srv.state.identity_error.get("a")
        assert srv.state.rom_type == rom_type
    finally:
        await close()


@pytest.mark.parametrize("rom_type", ["red", "purered", "emerald", "firered_rr"])
def test_a_hello_that_skips_the_socket_is_refused_by_admission_too(tmp_path, rom_type):
    """`_dispatch` is reachable without handle_client (tests, tools); the transactional admission seam
    holds the same rule, so a clean hello is rejected there and leaves the run untouched."""
    srv = SLinkServer(data_dir=str(tmp_path))
    commands = srv._dispatch("a", _hello(rom_type, artifact_kind="clean", panel=False))
    assert commands == [{"cmd": "noop", "refused": "admission"}]
    assert srv.admission["a"]["state"] == "rejected" and REASON in srv.admission["a"]["reason"]
    assert not srv.state.rom_type and not srv.state.artifact_kind


# ── 2b. the Gen 3 client's evidence: the cartridge's own mailbox, never the launcher's claim ────────────

def _native(pack):
    import pathlib
    profile = json.loads((pathlib.Path(_REPO) / "data" / "games" / pack / "profile.json").read_text(encoding="utf-8"))
    return profile["native"]


@pytest.mark.parametrize("pack,title", [("gen3_frlg", "firered"), ("gen3_rr", "radical_red")])   # the test World has no Emerald pack
@pytest.mark.parametrize("kind", ["clean", "companion"])
def test_gen3_hello_publishes_companion_abi_only_from_the_cartridges_own_live_mailbox(pack, title, kind):
    """Review F1/F2: companion_abi is read from RAM (signature at native.BASE, ABI at BASE+4), so it is absent on a
    cartridge with no mailbox whatever artifact kind the launcher named, and present on a patched one."""
    from tests.unit.test_gen3_client import A, B, live
    nat = _native(pack)
    w = live(pack, title, kind, pids=(A, B))
    assert w.client.driver.hello_fields().companion_abi is None, "no mailbox yet: no evidence"
    w.poke_int(nat["BASE"], nat["SIG"], 4)
    assert w.client.driver.hello_fields().companion_abi is None, "the signature alone is not the ABI"
    w.poke_int(nat["BASE"] + 4, nat["ABI"] + 1, 2)
    assert w.client.driver.hello_fields().companion_abi is None, "another ABI is not this pack's companion"
    w.poke_int(nat["BASE"] + 4, nat["ABI"], 2)
    assert w.client.driver.hello_fields().companion_abi == nat["ABI"]
    assert "companion_abi" not in w.client.driver.tick_fields(), "the evidence is hello-time only"
    w.poke_int(nat["BASE"], nat["SIG"] ^ 1, 4)
    assert w.client.driver.hello_fields().companion_abi is None, "a wrong signature withdraws the evidence"


def test_gen3_companion_live_never_raises_and_reads_nothing_without_a_native_block():
    lua, native = _lua("lua/gen3/native.lua")
    io = lua.eval("{read_u32 = function() error('unreadable') end, read_u16 = function() error('unreadable') end}")
    nat = lua.table(BASE=0x02030000, SIG=0x4B4E4C53, ABI=2)
    assert native.companion_live(nat, io) is None                 # an unreadable bus is no evidence
    assert native.companion_live(None, io) is None                # a pack with no native block
    assert native.companion_live(lua.table(BASE=1, SIG=2), io) is None   # no pinned ABI


# ── 3. the Lua launchers ───────────────────────────────────────────────────────────────────

def _lua(rel):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    return lua, lua.eval(f'dofile("{os.path.join(_REPO, rel).replace(chr(92), "/")}")')


def _pair(result):
    """lupa hands back a bare value for a one-value return and a tuple for `nil, reason`."""
    return result if isinstance(result, tuple) else (result, None)


BANK_3F = 0x3F * 0x4000                         # ROM offset of the bank the companion module lives in
WRITER = bytes([0x3E, 0x53, 0xEA, 0xE2, 0xDE])   # ld a,"S" / ld [$DEE2],a: the beacon writer inject.py emits
PATCHED, STOCK = ("writer", 0x1234), ("none", 0)


def _rom_reader(kind):
    """A synthetic 1 MiB image; `kind` PATCHED has the beacon writer somewhere inside bank $3F."""
    image = bytearray(0x100000)
    what, where = kind
    if what == "writer":
        image[BANK_3F + where:BANK_3F + where + 5] = WRITER
    elif what == "wrong_mailbox":
        image[BANK_3F + where:BANK_3F + where + 5] = bytes([0x3E, 0x53, 0xEA, 0xEA, 0xDE])
    elif what == "other_bank":
        image[0x3E * 0x4000 + where:0x3E * 0x4000 + where + 5] = WRITER
    return lambda addr: image[int(addr)] if 0 <= int(addr) < len(image) else 0


def _gen1_routed_stub(admit_result, family="red", hook=PATCHED):
    """Entry.admit_routed with Entry.admit stubbed: `admit_result` is a row, a refusal string or None."""
    lua, entry = _lua("lua/gen1/entry.lua")
    entry.admit = lua.eval("""function(row) return function()
        if type(row) == 'table' then return row end
        return nil, row or 'no row' end end""")(lua.table_from(admit_result) if isinstance(admit_result, dict)
                                                  else admit_result)
    logs = []
    args = lua.table(rom_sha1="ABCDEF", header="POKEMON RED", family=family, log=lambda t: logs.append(t),
                     read_rom_u8=_rom_reader(hook) if hook else None)
    return _pair(entry.admit_routed(args))


def test_gen1_a_companion_refusal_is_final_never_retried_as_the_named_family():
    # Entry.admit refused a pinned clean Red; the header says red, so the OLD launcher booted it by header.
    admitted, why = _gen1_routed_stub(f"this red cartridge {REASON}; prepare it through the Manager or /patcher")
    assert admitted is None and REASON in why and "no admission row" not in why


@pytest.mark.parametrize("family", ["red", "blue"])
@pytest.mark.parametrize("hook", [STOCK, ("other_bank", 0x20), None])
def test_gen1_launcher_refuses_a_stock_vanilla_cartridge_that_boots_by_header(family, hook):
    """A patched Red/Blue is in no sha1 table and boots as the named family; a stock or randomized-stock
    one has no admission row either. The beacon writer in ROM bank $3F is what tells them apart (the
    runtime beacon is only in WRAM after frames run; an admission decision at frame 0 cannot see it)."""
    admitted, why = _gen1_routed_stub(None, family=family, hook=hook)
    assert admitted is None and REASON in why and family in why, (hook, why)


@pytest.mark.parametrize("family", ["red", "blue"])
def test_gen1_an_unpinned_pure_overlay_is_not_told_to_patch_its_red_cartridge(family):
    """Review F6: a pureRGB overlay writes its beacon to ITS mailbox ($DEEA, not the vanilla $DEE2). Reaching the
    named-family path unpinned, it must be refused for what it is, not told to patch a "red" cartridge."""
    admitted, why = _gen1_routed_stub(None, family=family, hook=("wrong_mailbox", 0x20))   # writer to $DEEA
    assert admitted is None and "pureRGB overlay build" in why and REASON not in why, why


def test_gen1_launcher_named_fallback_boots_a_patched_vanilla_header_and_still_refuses_unknown():
    admitted, _ = _gen1_routed_stub(None, family="blue")
    assert admitted.kind == "named" and admitted.title == "blue" and admitted.rom_sha1 == "abcdef"
    admitted, why = _gen1_routed_stub(None, family="yellow", hook=STOCK)       # Yellow needs no patch
    assert admitted.kind == "named" and admitted.title == "yellow"
    admitted, why = _gen1_routed_stub(None, family="green")           # an unpinned pureRGB: never booted by header
    assert admitted is None and "no row" in why


def test_gen1_launcher_admits_a_row_it_did_not_refuse():
    admitted, why = _gen1_routed_stub({"title": "purered", "kind": "overlay", "pack": "p"})
    assert admitted is not None and admitted.title == "purered" and why is None


def test_gen1_beacon_detector_on_synthetic_bytes():
    _, entry = _lua("lua/gen1/entry.lua")
    for where in (0, 0x1234, 0x4000 - 5):                              # anywhere in the bank, both ends included
        assert entry.has_companion_beacon(_rom_reader(("writer", where))) is True, where
    assert entry.has_companion_beacon(_rom_reader(STOCK)) is False
    assert entry.has_companion_beacon(_rom_reader(("wrong_mailbox", 0x20))) is False   # another mailbox address
    assert entry.has_companion_beacon(_rom_reader(("wrong_mailbox", 0x20)), 0xDEEA) is True   # the overlay's
    assert entry.has_companion_beacon(_rom_reader(("other_bank", 0x20))) is False
    assert entry.has_companion_beacon(None) is False


def test_gen1_beacon_detector_on_the_real_roms():
    """The coordinator's expectation table, on real bytes (skipped when a dump is absent): clean Red/Blue and
    the clean pureRGB titles are refused; the companion Red/Blue and the pureRGB overlays are allowed."""
    from patch.tools.make_ups import ups_apply
    from tests.unit.test_gen1_purergb_client import _real_rom
    _, entry = _lua("lua/gen1/entry.lua")
    for title in ("red", "blue"):
        clean = _vanilla(title)
        with open(os.path.join(_REPO, "patch", "dist", f"SLink-RB-{title.capitalize()}.ups"), "rb") as fh:
            patched = ups_apply(clean, fh.read())
        assert entry.has_companion_beacon(lambda a, c=clean: c[int(a)]) is False, title
        assert entry.has_companion_beacon(lambda a, p=patched: p[int(a)]) is True, title
    for title in ("purered", "pureblue", "puregreen"):
        # a pure ROM never reaches this probe (sha1 / overlay rows decide); pinned here so the answer is
        # recorded: clean pure has no vanilla writer, and the overlay carries it at its own mailbox ($DEEA)
        clean, overlay = _real_rom("clean", title), _real_rom("overlay", title)
        assert entry.has_companion_beacon(lambda a, c=clean: c[int(a)], 0xDEEA) is False, title
        assert entry.has_companion_beacon(lambda a, o=overlay: o[int(a)], 0xDEEA) is True, title


def _gen1_real(rom_bytes):
    """The REAL Entry.admit_routed over real cartridge bytes (the gates the player's BizHawk runs)."""
    lua, entry = _lua("lua/gen1/entry.lua")
    codec = lua.eval(f'dofile("{os.path.join(_REPO, "lua/json_codec.lua").replace(chr(92), "/")}")')
    read = lambda addr: rom_bytes[int(addr)]  # noqa: E731
    family = entry.detect_title(read)
    args = lua.table(root=_REPO.replace("\\", "/"), json=codec, rom_sha1=hashlib.sha1(rom_bytes).hexdigest(),
                     header=entry.header_title(read), family=family, read_rom_u8=read, rom_size=len(rom_bytes),
                     log=lambda t: None)
    admitted, why = _pair(entry.admit_routed(args))
    # an Admission decision is an immutable proxy; copy its public pairs
    copy = lua.eval("function(v) local out = {} for k, x in pairs(v) do out[k] = x end return out end")
    return (dict(copy(admitted).items()) if admitted else None), why


def _vanilla(title):
    from tests.unit.test_gen1_purergb_client import _real_rom
    return _real_rom("vanilla", title)             # skips when the clean dump is absent


@pytest.mark.parametrize("title", ["red", "blue"])
def test_gen1_real_clean_red_and_blue_are_refused_the_patched_ones_boot(title):
    from patch.tools.make_ups import ups_apply
    clean = _vanilla(title)
    admitted, why = _gen1_real(clean)
    assert admitted is None and REASON in why and title in why
    # randomized-clean: same code, different data tables; no admission row, no hook
    admitted, why = _gen1_real(clean[:0x40000] + bytes(b ^ 0x5A for b in clean[0x40000:0x40040]) + clean[0x40040:])
    assert admitted is None and REASON in why
    with open(os.path.join(_REPO, "patch", "dist", f"SLink-RB-{title.capitalize()}.ups"), "rb") as fh:
        patched = ups_apply(clean, fh.read())
    admitted, why = _gen1_real(patched)
    assert why is None and admitted["kind"] == "named" and admitted["title"] == title


@pytest.mark.skipif(not os.path.isfile(os.path.join(_REPO, "patch", "build", "gen1_red_ap.gb")),
                    reason="Archipelago Red build absent (patch/build/gen1_red_ap.gb)")
def test_gen1_real_archipelago_red_is_not_booted_by_the_launcher():
    """Archipelago is permitted by policy but Gen 1 has no AP client profile: it has no admission row and no
    companion beacon, so the header-named fallback no longer boots it either (the Manager lists no AP game)."""
    with open(os.path.join(_REPO, "patch", "build", "gen1_red_ap.gb"), "rb") as fh:
        admitted, why = _gen1_real(fh.read())
    assert admitted is None and REASON in why


def test_gen1_real_yellow_stays_admitted_clean():
    admitted, why = _gen1_real(_vanilla("yellow"))
    assert why is None and admitted["title"] == "yellow"


@pytest.mark.parametrize("title", ["red", "blue", "green"])
def test_gen1_real_pure_clean_is_refused_and_the_overlay_is_admitted(title):
    from tests.unit.test_gen1_purergb_client import _randomized, _real_rom
    pure = f"pure{title}"
    admitted, why = _gen1_real(_real_rom("clean", pure))
    assert admitted is None and REASON in why, why
    admitted, why = _gen1_real(_randomized(_real_rom("clean", pure)))         # randomized-clean
    assert admitted is None, "a randomized-clean pureRGB cartridge must not boot"
    if title != "green":    # Red/Blue reach the named fallback, which names the companion; Green has none
        assert REASON in why, why
    admitted, why = _gen1_real(_real_rom("overlay", pure))
    assert why is None and admitted["kind"] == "overlay" and admitted["title"] == pure
    admitted, why = _gen1_real(_randomized(_real_rom("overlay", pure)))       # randomized, then patched
    assert why is None and admitted["kind"] == "rand_overlay" and admitted["title"] == pure


def test_gen1_a_missing_overlay_catalog_fails_closed():
    """pureRGB is admitted only through an admission_overlay.json row; if that catalog cannot be read the
    launcher refuses (never falls back to the clean rows or to the named family for a pure header)."""
    lua, entry = _lua("lua/gen1/entry.lua")
    boom = lua.eval("{decode = function() error('catalog unreadable') end}")
    args = lua.table(root=_REPO.replace("\\", "/"), json=boom, rom_sha1="00", header="POKEMON GREEN",
                     family="green", read_rom_u8=_rom_reader(PATCHED), rom_size=0x100000)
    admitted, why = _pair(entry.admit_routed(args))
    assert admitted is None and why


def test_gen1_run_lua_asks_the_routed_gate_not_the_bare_admit():
    with open(os.path.join(_REPO, "lua/gen1/run.lua"), encoding="utf-8") as fh:
        text = fh.read()
    assert "Entry.admit_routed(" in text and "Entry.admit(" not in text


def test_gen3_launcher_refuses_clean_companion_titles_and_admits_the_companion():
    lua, entry = _lua("lua/gen3/entry.lua")

    def run(kind, pack, title):
        entry.admit = lua.eval("""function(kind, pack, title) return function()
            return {pack=pack, title=title, kind=kind, admitted_by="hash", rom_type=title} end end""")(kind, pack, title)
        return _pair(entry.admit_routed(lua.table(header_code="BPRE")))

    for pack, title in (("gen3_frlg", "firered"), ("gen3_frlg", "leafgreen"),
                        ("gen3_emerald", "emerald"), ("gen3_rr", "radical_red")):
        for kind in ("clean", "rand"):
            admitted, why = run(kind, pack, title)
            assert admitted is None and REASON in why and title in why, (pack, kind)
        for kind in ("companion", "rand_companion"):
            admitted, why = run(kind, pack, title)
            assert admitted is not None and admitted.kind == kind and why is None, (pack, kind)


def test_gen3_expansion_is_not_a_companion_title():
    lua, entry = _lua("lua/gen3/entry.lua")
    packs = {k: dict(v.items()) for k, v in entry.PACKS.items()}
    assert {p for p, d in packs.items() if d.get("companion_required")} == {"gen3_frlg", "gen3_rr", "gen3_emerald"}
    assert "gen3_exp" in packs and not packs["gen3_exp"].get("companion_required")


def test_gen3_real_clean_and_companion_hashes_through_the_launcher_gate():
    """admit_routed over the real catalog: each pinned clean hash is refused with the companion reason,
    each companion hash is admitted. (Entry.admit stays catalog-faithful; admit_routed is the one gate.)"""
    from tests.unit.test_gen3_entry import artifact_of
    lua, entry = _lua("lua/gen3/entry.lua")
    codec = lua.eval(f'dofile("{os.path.join(_REPO, "lua/json_codec.lua").replace(chr(92), "/")}")')
    root = _REPO.replace("\\", "/")
    for pack, title in (("gen3_frlg", "firered"), ("gen3_frlg", "leafgreen"), ("gen3_emerald", "emerald"),
                        ("gen3_rr", "radical_red")):
        admitted, why = _pair(entry.admit_routed(lua.table(root=root, json=codec,
                                                           rom_hash=artifact_of(pack, title, "clean")["rom_sha1"])))
        assert admitted is None and REASON in why, (pack, title, why)
        admitted, why = _pair(entry.admit_routed(lua.table(
            root=root, json=codec, rom_hash=artifact_of(pack, title, "companion")["rom_sha1"])))
        assert why is None and admitted.kind == "companion", (pack, title, why)
