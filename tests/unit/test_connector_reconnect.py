"""lua/connector.lua:263 M.disconnect() must not let a pre-drop event outlive the connection.

WHY THIS EXISTS. M.disconnect() reset _send_offset/_recv_buf but left _send_queue intact.
An event queued the same frame the socket died survived into the NEW connection and was
flushed by pump() (connector.lua:195-202) before the client got a chance to queue its
reconnect hello -- every real client calls net.pump() first and only then (re)sends hello
in the same frame_end, e.g. lua/gen1/client.lua:929-941 and
lua/clients/gen3_frlge_client.lua:1912-1937. Since server/server.py:1235-1240 answers any
pre-hello event on a connection with a `noop` + WARNING, that stale event was not merely
reordered ahead of hello -- it was silently dropped by the server anyway, just later and
with a same log noise. Clearing _send_queue in disconnect() drops it locally instead, and a
new connection starts with hello first by construction.

Checked before writing the fix: connector.lua itself is the only caller of M.disconnect()
(on the send-error and receive-error branches) and the only reader of _send_queue --
no other lua/ file touches either, so nothing relies on the queue surviving a drop.
"""
from __future__ import annotations

import json
import os

import pytest

lupa = pytest.importorskip("lupa", reason="lupa is needed to execute connector.lua")

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_CONNECTOR = os.path.join(_REPO, "lua", "connector.lua")

# A minimal non-fragmenting mock: sends succeed in one shot except when `fail_send` is set,
# which reports a hard "closed" error the way a dead peer does -- the SAME error shape
# connector.lua's own send-error branch (`M.send error ... "` -- disconnecting") handles by
# calling M.disconnect(), so the test drops the socket through connector.lua's real code
# path rather than by calling c.disconnect() itself.
_HARNESS = r"""
local M = {}
M.sent = {}
M.closed = false
M.fail_send = false

local sock = {}
sock.__index = sock

function sock:settimeout(_) end
function sock:connect(_, _) return 1 end          -- loopback: connects immediately
function sock:close() M.closed = true end
function sock:getpeername() return "127.0.0.1", 1 end

function sock:send(data, i)
    if M.fail_send then return nil, "closed" end
    i = i or 1
    local rest = data:sub(i)
    table.insert(M.sent, rest)
    return #data
end

function sock:receive(_) return nil, "timeout", "" end

M.new = function() return setmetatable({}, sock) end
return M
"""


def _lua_env():
    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    g = rt.globals()

    mock = rt.execute(_HARNESS)
    g.console = rt.table_from({"log": lambda s: None})

    fake_socket = rt.table_from({"socket": rt.table_from({"tcp4": lambda: mock.new()})})
    rt.execute(
        'local fake = ...; package.preload["socket"] = function() return fake end',
        fake_socket,
    )

    with open(_CONNECTOR, encoding="utf-8") as f:
        src = f.read()
    connector = rt.execute(src)
    return rt, connector, mock


def _sent_events(rt, mock):
    n = len(mock.sent)
    blob = "".join(mock.sent[i] for i in range(1, n + 1))
    return [json.loads(s) for s in blob.split("\n") if s]


def test_stale_pre_drop_event_does_not_jump_the_reconnect_hello():
    rt, c, mock = _lua_env()
    c.init("127.0.0.1", 1)
    c.pump()
    assert c.connected()

    # Queued the instant before the peer goes away -- exactly what a client's frame_end can
    # do the same frame the connection dies.
    c.send(json.dumps({"event": "tick", "seq": 1}))

    # Drop the socket via connector.lua's own send-error path, not c.disconnect() directly.
    mock.fail_send = True
    c.pump()
    assert not c.connected(), "a hard send error must drive pump() into disconnect()"

    # Reconnect.
    mock.fail_send = False
    c.init("127.0.0.1", 1)
    assert c.connected()

    # Mirror every real client's frame_end order: pump() first, THEN queue the reconnect
    # hello in the same frame (lua/gen1/client.lua:929-941); the hello itself goes out on
    # the frame's OWN next pump(), same as production.
    c.pump()
    c.send(json.dumps({"event": "hello", "seq": 0}))
    c.pump()

    events = _sent_events(rt, mock)
    assert events, "nothing was sent on the new connection"
    assert events[0]["event"] == "hello", (
        f"hello must be the first thing the new connection sends, got {events!r} -- "
        "a pre-drop event survived disconnect() and jumped ahead of it")
    assert not any(e.get("event") == "tick" for e in events), (
        "the stale pre-drop event must not survive a disconnect() at all")


# ── the Gen 3 production client over the SAME connector (P4 card C4-5) ─────────────────────
#
# lua/gen3/client.lua's frame_end (via lua/core/session.lua:274-286) does net.pump() THEN
# hello, the exact order this file already proves connector.lua enforces for a hand-driven
# c.send/c.pump script above. This exercises it through the REAL client -- the production
# lua/gen3/entry.lua build, not a stand-in -- so a regression in either connector.lua's
# disconnect() or session.lua's frame_end ordering shows up here even if the other's own tests
# stay green. tests/unit/gen3_world.py's World wires its own stub `net` with no hook to swap in
# a real connector (a read-only file for this card, docs/gen3/research/p4_gen1_contract_map.md
# §4.3: "if it lacks a hook you need, report it" -- filed as a follow-up rather than edited
# here), so this builds the smallest real client directly against lua/gen3/entry.lua,
# reusing gen3_world.py's own pack-loading helpers and pointer/predicate offsets.

from tests.unit.gen3_world import ROM_BASE, SB1_ADDR, SB2_ADDR, pack_json  # noqa: E402


def _gen3_client_over(rt, net):
    """A minimal, live gen3_frlg/firered production client (empty party) whose net is the
    given connector.lua instance -- built on the SAME LuaRuntime as `net` (lupa refuses to mix
    tables from two runtimes)."""
    L = rt
    repo_posix = _REPO.replace("\\", "/")               # embedded in Lua string literals below

    profile = pack_json("gen3_frlg", "profile.json")["titles"]["firered"]
    sites = pack_json("gen3_frlg", "engine_signals.json")["titles"]["firered"]["artifacts"]["clean"]["sites"]
    wc = pack_json("gen3_frlg", "write_checkpoint.json")["firered"]

    rom: dict[int, int] = {}
    for site in sites.values():
        for i, b in enumerate(bytes.fromhex(site["expected_hex"])):
            rom[site["rom_offset"] + i] = b
    for anchor in wc["anchors"].values():
        for i, b in enumerate(bytes.fromhex(anchor["expected_hex"]["clean"])):
            rom[anchor["rom_offset"] + i] = b

    bus: dict[int, int] = {}
    regs = {"R13": 0x03007F00, "R15": 0, "CPSR": 0}
    frame = [0]

    def poke_int(addr, value, width):
        for i in range(width):
            bus[addr + i] = (value >> (8 * i)) & 0xFF

    def byte(addr):
        if addr >= ROM_BASE:
            return rom.get(addr - ROM_BASE, 0)
        return bus.get(addr, 0)

    io_ = L.table(
        read_u8=lambda a: byte(int(a)),
        read_u16=lambda a: byte(int(a)) | (byte(int(a) + 1) << 8),
        read_u32=lambda a: sum(byte(int(a) + i) << (8 * i) for i in range(4)),
        read_bytes=lambda a, n: L.table(*[byte(int(a) + i) for i in range(int(n))]),
        rom_read=lambda off, n: L.table(*[rom.get(int(off) + i, 0) for i in range(int(n))]),
        framecount=lambda: frame[0], register=lambda name: regs.get(str(name), 0),
        write_u8=lambda a, v, *_: bus.__setitem__(int(a), int(v)),
        saveram=lambda: None,
    )
    hooks: dict[str, tuple] = {}
    ev = L.table(
        on_bus_exec=lambda fn, addr, name: (hooks.__setitem__(str(name), (fn, int(addr))),
                                            f"id-{len(hooks)}")[1],
        unregister=lambda i: None,
    )
    hud = L.table(show=lambda *a: None, prompt=lambda *a: None, set_game_over=lambda: None,
                  set_rebuilding=lambda t: None, clear_rebuilding=lambda: None,
                  nuzlocke_start=lambda *a: None)
    Entry = rt.eval(f'dofile("{repo_posix}/lua/gen3/entry.lua")')
    client, _parts = Entry.build(L.table(
        root=repo_posix, mode="production", io=io_, ev=ev, net=net, hud=hud,
        pack="gen3_frlg", title="firered", kind="clean", player="a",
        rom_sha1="ab" * 20, log=lambda t: None,
    ))

    ptrs = wc["pointers"]
    poke_int(ptrs["gSaveBlock1Ptr"]["address"], SB1_ADDR, 4)
    poke_int(ptrs["gSaveBlock2Ptr"]["address"], SB2_ADDR, 4)
    poke_int(ptrs["gPokemonStoragePtr"]["address"], profile["ram"]["POKEMON_STORAGE_BASE"], 4)
    d = profile["derived"]
    if "SB2_OT_ID_OFFSET" in d:
        poke_int(SB2_ADDR + d["SB2_OT_ID_OFFSET"], 0xABCD, 4)
    poke_int(profile["ram"]["PARTY_COUNT_ADDR"], 0, 1)
    for p in wc["predicates"].values():
        poke_int(p["address"] + p["offset"], p["expect"], p["width"])
    cpu = wc["cpu"]
    regs["R15"] = cpu["pc_min"]
    regs["CPSR"] = cpu["mode"] | (cpu["thumb"] << 5)
    client.start(client)

    def step():
        frame[0] += 1
        client.frame_end(client)

    return client, step


def test_gen3_client_frame_end_sends_hello_first_after_a_reconnect_via_connector():
    """The REAL Gen 3 production client, driven through lua/connector.lua's own send-error
    disconnect path (exactly test_stale_pre_drop_event_does_not_jump_the_reconnect_hello's
    drop mechanism above), must never let a reconnect's first line be anything but hello, and
    the event queued the instant before the drop must not survive it -- proven end to end
    through session.lua's real frame_end (pump, then hello), not a hand-authored call order.
    """
    rt, c, mock = _lua_env()
    c.init("127.0.0.1", 1)                      # the bootstrap's one-time C.init (run.lua)
    client, step = _gen3_client_over(rt, c)

    step()                                      # connect: hello queued
    step()                                      # pump flushes the queued hello
    assert c.connected()
    first = _sent_events(rt, mock)
    assert first and first[0]["event"] == "hello"

    mock.fail_send = True
    # nothing is queued again until the next tick (TICK_INTERVAL=30, lua/core/session.lua):
    # step to it so pump() actually attempts a send and hits the hard error.
    for _ in range(40):
        step()
        if not c.connected():
            break
    assert not c.connected(), "a hard send error must drive pump() into disconnect()"

    mock.fail_send = False
    c.init("127.0.0.1", 1)                      # a bootstrap's own reconnect call (run.lua
                                                 # calls C.init() once at boot; the client's
                                                 # frame_end never redials on its own)
    step()                                      # pump (nothing queued yet) then hello queued
    step()                                      # pump flushes the reconnect hello

    events = _sent_events(rt, mock)
    hello_indices = [i for i, e in enumerate(events) if e["event"] == "hello"]
    assert len(hello_indices) == 2, f"expected exactly two hellos (one per connection): {events!r}"
    after_reconnect = events[hello_indices[1]:]
    assert after_reconnect[0]["event"] == "hello", (
        f"the new connection's first line was not hello: {after_reconnect!r}")
