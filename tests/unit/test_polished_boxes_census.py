"""C-BOX (docs/polished/CLIENT.md): the READ-ONLY newbox census composed into the Polished client.

lua/gen2/polished.lua P.census wraps lua/gen2/polished_boxes.lua read_boxes as the client box readers and
lua/gen2/entry.lua compose_polished wires it, so `hello` carries `pc_boxes` + a non-null `pc_boxes_generation`
when, and only when, a real save is mapped and all 20 boxes decoded. The proof is in process: a synthetic
CartRAM + WRAM image (the geometry is NEWBOX.md's, written out by hand in test_polished_boxes.py and here, not
derived from the module under test) behind a domain-aware io, the real client's own hello line.

UNPROVEN without a cartridge (these tests cannot settle them): that BizHawk's Gambatte "WRAM" domain is the flat
bank*0x1000 image the Gen 2 live gates already rely on for vanilla Crystal, and that Polished never leaves a
referenced pokedb entry unflagged. The census therefore fails CLOSED on every surprise.

RED CONTROLS (each behaviour names the mutation of lua/gen2/polished.lua that must turn its test red):
  zero image / version   delete the `version ~= SAVE_VERSION` refusal            -> test_an_all_zero_image_is_not_a_census
  save checksum          delete the `sum ~= ...sChecksum...` refusal             -> test_a_save_whose_checksum_fails_is_not_a_census
  unflagged pointer      delete the `#snap.unflagged > 0` refusal                -> test_a_pointer_with_a_clear_flag_is_not_a_census
  bad egg                delete the `#snap.bad_eggs > 0` refusal                 -> test_a_corrupted_entry_makes_the_census_incomplete
  native save running    delete the wGameLogicPaused refusal                     -> test_a_running_native_save_withholds_the_census
  linear CartRAM         delete the `io.cart_ram_linear ~= true` refusal         -> test_the_io_must_declare_the_flat_images
  wire slot / box        make `copy.slot = mon.slot` (1-based)                   -> test_a_deposited_mon_enumerates_with_the_right_key_and_level
Applied and reverted by hand when this file was written (each went red on exactly the named test): zero image,
save checksum, unflagged pointer, bad egg and wire slot. Not mutation-run: the native-save and linear-CartRAM guards.
"""
from __future__ import annotations

import json
import random

import pytest

from server.adapters import polished_codec as pc
from tests.unit.test_mixed_foundations import _refused, _session
from tests.unit.test_polished_boxes import (
    FLAG_FLAT,
    PAUSED_FLAT,
    WRITING_BACKUP_FLAT,
    Image,
    box_flat,
    codec_key,
    random_entry,
)
from tests.unit.test_polished_client import OT_ID, _memory, _mons
from tests.unit.test_polished_lua import ROOT, _pair, _real, _sym, load_variants

lupa = pytest.importorskip("lupa")

# flat CartRAM offsets of the save anchors: bank*0x2000 + addr - 0xA000, by hand from the .sym (checked below)
VERSION_AT, GAME_AT, GAME_END, CHECKSUM_AT = 0x0BE2, 0x2008, 0x2B83, 0x2D0D


def seal_save(img, seed=5):
    """A real-looking save: sSaveVersion 00 0A (big-endian) and sChecksum = 16-bit byte sum of sGameData."""
    cart = img.mem["CartRAM"]
    cart[VERSION_AT:VERSION_AT + 2] = b"\x00\x0a"
    cart[GAME_AT:GAME_END] = random.Random(seed).randbytes(GAME_END - GAME_AT)
    resum(img)


def resum(img):
    cart = img.mem["CartRAM"]
    cart[CHECKSUM_AT:CHECKSUM_AT + 2] = (sum(cart[GAME_AT:GAME_END]) & 0xFFFF).to_bytes(2, "little")


def hatched(rng, egg=False):
    """A sealed random entry with its is-egg bit (form byte bit 6) set as asked."""
    raw = bytearray(random_entry(rng))
    raw[21] = (raw[21] | 0x40) if egg else (raw[21] & ~0x40)
    return pc.seal(bytes(raw))


def deposited(seed=11):
    """A valid save with six mons: box 3 slot 5 (bank 1 e7), box 1 slot 1 (bank 2 e1, 9-bit species possible),
    box 20 slot 20 (memorial, bank 2 e207 section C), a B-section and a C-section entry, and box 12 slot 9."""
    rng, img, planted = random.Random(seed), Image(), {}
    seal_save(img)
    for box, slot, d, e in ((3, 5, 1, 7), (1, 1, 2, 1), (20, 20, 2, 207), (7, 2, 1, 170), (7, 3, 1, 196), (12, 9, 2, 168)):
        entry = hatched(rng)
        img.plant(box, slot, d, e, entry)
        planted[box, slot] = entry
    return img, planted


class Rig:
    """polished.lua P.census over an Image behind the production io shape (read_u8 with a domain, domain_size)."""

    def __init__(self, img, *, linear=True, sram=0x8000, wram=0x8000):
        self.img, self.logs = img, []
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        fn = self.lua.eval("function(f) return function(...) return f(...) end end")
        self.P = load_variants(self.lua, self.lua.eval(f'dofile("{ROOT}/lua/gen2/polished.lua")'))
        self.B = self.lua.eval(f'dofile("{ROOT}/lua/gen2/polished_boxes.lua")')
        fields = {"read_u8": fn(img.read), "domain_size": fn(lambda d: sram if d == "CartRAM" else wram)}
        if linear:
            fields["cart_ram_linear"] = True
        self.io = self.lua.table_from(fields)
        self.census, why = _pair(self.P.census(self.B, self.io, None, fn(self.logs.append)))
        assert self.census is not None, why

    def walk(self):
        """What client.lua rescan_boxes does: boxes 0..19 through read_storage_box. (boxes, why)."""
        before, boxes = self.img.snap(), []
        assert self.census.read_current_box_num() == -1
        for index in range(20):
            result, why = _pair(self.census.read_storage_box(index))
            if result is None:
                assert self.img.snap() == before  # a census never writes
                return None, why
            for mon in result["mons"].values():
                boxes.append((index, mon["slot"], mon["key"], mon["level"], mon["species_id"], mon["held_item"],
                              tuple(mon["moves"].values())))
        assert self.img.snap() == before
        return boxes, None


def expected(planted):
    out = []
    for (box, slot), entry in sorted(planted.items()):
        decoded = pc.decode_savemon(entry, name_decoder=None)
        out.append((box - 1, slot - 1, codec_key(entry), entry[28], decoded["species_id"], entry[1], tuple(entry[2:6])))
    return out


# ── the coordinates are the pinned .sym's ────────────────────────────────────

def test_every_census_coordinate_is_the_overlay_sym():
    sym = _sym()
    rig = Rig(Image())
    coords = rig.P.newbox_coords()
    labels = list(rig.B.COORD_LABELS.values()) + ["sSaveVersion", "sGameData", "sGameDataEnd", "sChecksum"]
    for label in labels:
        assert (coords[label][1], coords[label][2]) == sym[label], label
    for flat, label in ((VERSION_AT, "sSaveVersion"), (GAME_AT, "sGameData"), (GAME_END, "sGameDataEnd"),
                        (CHECKSUM_AT, "sChecksum"), (PAUSED_FLAT, "wGameLogicPaused"), (WRITING_BACKUP_FLAT, "sWritingBackup")):
        bank, addr = sym[label]
        assert flat == (bank * 0x2000 + addr - 0xA000 if label[0] == "s" else addr - 0xC000), label
    assert (sym["wPokeDB1UsedEntries"], sym["wPokeDB2UsedEntries"]) == ((2, 0xD8B7), (2, 0xD8D1))
    assert FLAG_FLAT == {1: 2 * 0x1000 + 0x8B7, 2: 2 * 0x1000 + 0x8D1}


# ── a real deposited mon enumerates (RED: slot/box off by one) ───────────────

def test_a_deposited_mon_enumerates_with_the_right_key_and_level():
    img, planted = deposited()
    boxes, why = Rig(img).walk()
    assert why is None, why
    assert sorted(boxes) == expected(planted)
    assert len(boxes) == 6 and {b[0] for b in boxes} == {0, 2, 6, 11, 19}      # box 20 -> index 19 (memorial_box_index)


def test_the_valid_empty_save_is_a_complete_empty_census():
    """The control that keeps the guards honest: an empty but REAL save is a census (zero mons), not a refusal."""
    img = Image()
    seal_save(img)
    assert Rig(img).walk() == ([], None)


# ── fail closed (RED: each guard deleted) ────────────────────────────────────

def test_an_all_zero_image_is_not_a_census():
    boxes, why = Rig(Image()).walk()
    assert boxes is None and "sSaveVersion 0000" in why


def test_a_save_whose_checksum_fails_is_not_a_census():
    img, _ = deposited()
    img.mem["CartRAM"][GAME_AT + 100] ^= 0x01            # one flipped game byte: sums disagree
    boxes, why = Rig(img).walk()
    assert boxes is None and "checksum" in why
    resum(img)
    assert Rig(img).walk()[1] is None                    # re-sealed: counts again


def test_a_corrupted_entry_makes_the_census_incomplete():
    img, planted = deposited()
    entry = bytearray(planted[3, 5])
    entry[5] ^= 0x01                                     # one data bit: the game shows a Bad Egg
    img.put(1, 7, bytes(entry))
    boxes, why = Rig(img).walk()
    assert boxes is None and "Bad Egg" in why


def test_a_pointer_with_a_clear_flag_is_not_a_census():
    """A wrong WRAM mapping reads every flag as clear. polished_boxes.lua alone reports such a slot as an empty one
    (the game shows it empty); the census refuses instead, because the engine never leaves a referenced entry
    unflagged."""
    img, _ = deposited()
    img.flag(1, 7, on=False)
    rig = Rig(img)
    snap = rig.B.new(rig.P.newbox_coords(), rig.io, rig.P.mon_key).read_boxes("gameplay")
    assert snap.complete and len(snap.unflagged) == 1     # the module alone: an empty slot, still "complete"
    boxes, why = rig.walk()
    assert boxes is None and "clear WRAM flag" in why


def test_a_corrupt_pointer_makes_the_census_incomplete():
    img, _ = deposited()
    img.mem["CartRAM"][box_flat(9) + 3] = 208            # entry index beyond 207
    boxes, why = Rig(img).walk()
    assert boxes is None and "incomplete" in why


def test_a_running_native_save_withholds_the_census():
    img, _ = deposited()
    img.mem["WRAM"][PAUSED_FLAT] = 1
    assert "native save" in Rig(img).walk()[1]
    img.mem["WRAM"][PAUSED_FLAT] = 0
    img.mem["CartRAM"][WRITING_BACKUP_FLAT] = 1
    assert "backup save" in Rig(img).walk()[1]
    img.mem["CartRAM"][WRITING_BACKUP_FLAT] = 0
    assert Rig(img).walk()[1] is None


def test_the_io_must_declare_the_flat_images():
    img, _ = deposited()
    assert "linear CartRAM" in Rig(img, linear=False).walk()[1]
    assert "32 KiB" in Rig(img, sram=0x2000).walk()[1]
    assert "32 KiB" in Rig(img, wram=0x2000).walk()[1]


def test_one_scan_per_pass_and_the_refusal_is_logged_once():
    rig = Rig(Image())                                     # all zero: refused
    for _ in range(3):
        for index in range(20):
            assert _pair(rig.census.read_storage_box(index))[0] is None
    assert len(rig.logs) == 1 and "withheld" in rig.logs[0]
    img, _ = deposited()
    counted, original = {"n": 0}, img.read
    img.read = lambda off, dom: (counted.__setitem__("n", counted["n"] + 1), original(off, dom))[1]
    rig = Rig(img)
    rig.census.read_storage_box(5)                         # no scan starts above box 0
    assert counted["n"] == 0


# ── the real client: hello carries the census ────────────────────────────────

HARNESS = """
return function(rom, mem, image)
    local log = {hooks={}, writes={}, sent={}, lines={}}
    local io = {frame=0, cart_ram_linear=true}
    function io.read_u8(a, d)
        if d == "ROM" then return rom:byte(a + 1) end
        if d == "CartRAM" or d == "WRAM" then return image(a, d) end
        return mem[a] or 0
    end
    function io.read_range(a, n, d) local out = {} for i = 1, n do out[i] = io.read_u8(a + i - 1, d) end return out end
    function io.write_u8(a, v, d) log.writes[#log.writes + 1] = a end
    function io.bank_valid() return true end
    function io.domain_size(d) return d == "ROM" and #rom or 0x8000 end
    function io.framecount() return io.frame end
    function io.on_bus_exec(fn, addr, name) log.hooks[#log.hooks + 1] = name return #log.hooks end
    function io.unregister() end
    function io.register() return 0 end
    local net = {connected=function() return true end, pump=function() end, receive=function() return nil end,
                 send=function(line) log.sent[#log.sent + 1] = line return true end}
    local hud = {show=function() end, nuzlocke_start=function() end, sanitize=function(s) return s end}
    local deps = {root=ROOTDIR, title="polished", io=io, net=net, hud=hud, player="a", rom_size=#rom,
                  read_rom_u8=function(a) return rom:byte(a + 1) end,
                  log=function(t) log.lines[#log.lines + 1] = t end}
    return deps, io, log
end
"""


@pytest.fixture(scope="module")
def overlay_rom():
    return _real()[1]


def _hello(overlay_rom, img):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    mem = _memory(_mons())
    deps, io, log = lua.execute(HARNESS.replace("ROOTDIR", json.dumps(ROOT)))(
        overlay_rom, lua.table_from(mem), lambda a, d: img.read(a, d))
    parts, why = _pair(lua.eval(f'dofile("{ROOT}/lua/gen2/entry.lua")').build(deps))
    assert why is None, why
    before = img.snap()
    parts.client.start(parts.client)
    for _ in range(80):
        io.frame += 1
        parts.client.frame_end(parts.client)
    hellos = [json.loads(line) for line in log.sent.values() if json.loads(line)["event"] == "hello"]
    assert len(hellos) == 1, list(log.lines.values())
    # C-WRITE r2: the composition also hooks the overworld HOLD site (25:51BF, SLink-gen2-checkpoint);
# the hook registers nothing on its own and writes nothing without a command.
    # C-EXPLODE: the composition also hooks the battle hold (0f:416A, SLink-gen2-battle-hold): the explode PC hold, nothing written on its own.
    assert set(log.hooks.values()) <= {'SLink-gen2-polished:capture_party', 'SLink-gen2-checkpoint', 'SLink-gen2-battle-hold'} and len(log.writes) == 0 and img.snap() == before    # read only, nothing hooked
    return hellos[0], parts


def test_hello_carries_the_census_with_a_generation(overlay_rom):
    img, planted = deposited()
    hello, _ = _hello(overlay_rom, img)
    assert hello["pc_boxes_generation"] >= 1
    got = sorted((e["box"], e["slot"], e["key"], e["level"], e["species_id"], e["held_item_id"], tuple(e["moves"]))
                 for e in hello["pc_boxes"])
    assert got == expected(planted)


def test_a_boxed_egg_is_in_the_census_but_not_on_the_wire(overlay_rom):
    """The client omits eggs from pc_boxes as it does from the party (no egg wire shape in protocol.md)."""
    img, planted = deposited()
    egg = hatched(random.Random(3), egg=True)
    img.plant(15, 1, 1, 50, egg)
    assert len(Rig(img).walk()[0]) == 7
    hello, _ = _hello(overlay_rom, img)
    assert "pc_boxes_generation" in hello
    assert sorted(e["key"] for e in hello["pc_boxes"]) == sorted(codec_key(e) for e in planted.values())


def test_hello_has_no_census_for_an_all_zero_image(overlay_rom):
    """The all-zero SRAM/WRAM image (a wrong mapping, a blank cartridge) must not become a complete empty census."""
    hello, _ = _hello(overlay_rom, Image())
    assert hello["pc_boxes"] == [] and "pc_boxes_generation" not in hello


def test_hello_has_no_census_when_one_entry_is_corrupt(overlay_rom):
    img, planted = deposited()
    entry = bytearray(planted[12, 9])
    entry[3] ^= 0x10
    img.put(2, 168, bytes(entry))
    hello, _ = _hello(overlay_rom, img)
    assert "pc_boxes_generation" not in hello and hello["pc_boxes"] == []


def test_hello_has_a_valid_empty_census_generation(overlay_rom):
    img = Image()
    seal_save(img)
    hello, _ = _hello(overlay_rom, img)
    assert hello["pc_boxes"] == [] and hello["pc_boxes_generation"] >= 1


@pytest.mark.asyncio
async def test_the_real_server_takes_the_census(overlay_rom, tmp_path):
    from server.server import SLinkServer
    img, planted = deposited()
    hello, _ = _hello(overlay_rom, img)
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        reply = await send(hello)
        assert not _refused(reply) and srv.is_admitted("a"), srv.state.identity_error
        keys = {codec_key(e) for e in planted.values()}
        assert {e["key"] for e in srv.pc_boxes["a"]} == keys
        assert srv.adapter.memorial_box_index == 19 and {e["box"] for e in srv.pc_boxes["a"]} >= {19}
    finally:
        await close()


# ── the wire entry ───────────────────────────────────────────────────────────

def test_the_box_wire_entry_spans_twenty_boxes_and_refuses_eggs():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    P = load_variants(lua, lua.eval(f'dofile("{ROOT}/lua/gen2/polished.lua")'))
    mon = lua.table_from({"species_id": 0x123, "form": 3, "gender": "male", "shiny": False, "dv_bytes": 0x123456,
                          "ot_id": OT_ID, "level": 50, "held_item": 7, "slot": 19, "nickname": "X",
                          "moves": lua.table_from([1, 2, 3, 4])})
    entry, why = _pair(P.wire.box_entry(mon, 19))
    assert why is None and (entry["box"], entry["slot"], entry["held_item_id"], entry["nickname"]) == (19, 19, 7, "X")
    assert _pair(P.wire.box_entry(mon, 20))[0] is None
    mon["is_egg"] = True
    assert "egg" in _pair(P.wire.box_entry(mon, 0))[1]
