"""P4.1f: lua/gen2/panel.lua, the Gen 2 binder onto lua/gb_panel.lua, under lupa.

Pins: every address comes from the profile's generated overlay block, which equals the pinned
data/gen2/<title>_slink.sym; an unpatched cartridge and a stale mailbox read ABSENT and never
paint; a live one with CAP_PANEL paints tiles + the CGB attrmap; the Lua constants equal
patch/gb/slink_abi.inc and patch/gen2/src/slink.asm.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import shutil
import sys

import lupa
import pytest

from tests.unit.test_gb_panel import _abi

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import gen_gen2_profile  # noqa: E402
from rgbds_symbols import parse_symbols  # noqa: E402

PANEL = (REPO / "lua" / "gen2" / "panel.lua").as_posix()
PERMIT = (REPO / "lua" / "write_permit.lua").as_posix()
SLINK_ASM = REPO / "patch" / "gen2" / "src" / "slink.asm"
TITLES = ("crystal", "gold", "silver")
PROVENANCE = json.loads((REPO / "data/gen2/overlay_provenance.json").read_text())
ARTIFACT = {"crystal": "pokecrystal", "gold": "pokegold", "silver": "pokesilver"}
CAP_PANEL = 0x02


def profile(title):
    return json.loads((REPO / f"data/games/gen2_{title}/profile.json").read_text())["titles"][title]


class Cart:
    """WRAM + the P4.1c service, stepped one frame at a time."""

    def __init__(self, title, patched=True, caps=CAP_PANEL, cookie=0xA5):
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.P = self.lua.eval(f'dofile("{PANEL}")')
        self.prof = profile(title)
        ram = self.prof["overlay"]["ram"]
        self.mb, self.tm, self.am = ram["wSlinkMailbox"], ram["wTilemap"], ram["wAttrmap"]
        self.mem = bytearray(0x10000)          # Init cleared WRAM: the clean cartridge's view
        self.frame, self.patched, self.caps, self.cookie, self.running = 0, patched, caps, cookie, True
        self.writes: list[tuple[int, list[int]]] = []
        io = self.lua.table(read_u8=lambda a, d=None: self.mem[int(a)], framecount=lambda: self.frame,
                            write_u8=self._write_u8)
        self.w = self.P.writes(io, self.lua.eval(f'dofile("{PERMIT}")'))
        charmap = self.lua.eval(f'dofile("{(REPO / f"data/games/gen2_{title}/charmap.lua").as_posix()}")')
        self.panel = self.P.new(self.lua.table_from(self.prof, recursive=True), charmap, io, self.w,
                                lambda s: str(s))

    def _write_u8(self, addr, value, domain=None):
        assert domain == "System Bus"
        self.mem[int(addr)] = int(value)
        if self.writes and self.writes[-1][0] + len(self.writes[-1][1]) == int(addr):
            self.writes[-1][1].append(int(value))
        else:
            self.writes.append((int(addr), [int(value)]))

    def service_rom(self):
        """slink.asm SlinkService: header repair, caps, the sampled counter (+1 per frame here)."""
        mb = self.mb
        self.mem[mb:mb + 5] = b"SLNK\x03"
        self.mem[mb + 8] = self.caps
        self.mem[mb + 31] = self.cookie
        counter = (self.mem[mb + 5] | self.mem[mb + 6] << 8) + 1
        self.mem[mb + 5], self.mem[mb + 6] = counter & 0xFF, counter >> 8 & 0xFF

    def step(self, n=1):
        for _ in range(n):
            self.frame += 1
            if self.patched and self.running:
                self.service_rom()
            res = self.panel.service(self.panel)
            assert res is True, res

    def open_panel(self):
        """The patch's CLOSED (>= 1 frame, Codex's rule) -> AWAIT."""
        self.mem[self.mb + 9] = 0
        self.step()
        self.mem[self.mb + 9] = 1
        self.writes.clear()
        self.step()


def hold(c):
    assert c.panel.hold(c.panel, c.lua.table("AB@#", "C"))


# -- presence: ABSENT on clean, PRESENT on the overlay, stale -> not fresh --------------------

@pytest.mark.parametrize("title", TITLES)
def test_unpatched_cartridge_reads_absent_and_refuses_to_paint(title):
    c = Cart(title, patched=False)
    hold(c)
    c.step(5)
    c.mem[c.mb + 9] = 1                        # ordinary WRAM that happens to read AWAIT
    c.step(5)
    assert not c.panel.fresh(c.panel) and not c.panel.present(c.panel) and not c.panel.sfx_present(c.panel)
    assert c.writes == []


@pytest.mark.parametrize("title", TITLES)
def test_patched_cartridge_reads_present_and_paints_tiles_then_cgb_attrs(title):
    c = Cart(title)
    hold(c)
    c.step(2)
    assert c.panel.fresh(c.panel) and c.panel.present(c.panel)
    c.open_panel()
    mb = c.mb
    assert [a for a, _ in c.writes] == [c.tm, c.am, mb + 11, mb + 9]
    tiles, attrs = c.writes[0][1], c.writes[1][1]
    # "AB@#": '@' ($50 terminator) and '#' ($54 POKé control) are never tiles
    assert tiles[:5] == [0x80, 0x81, 0x7F, 0x7F, 0x7F] and tiles[20] == 0x82 and len(tiles) == 360
    assert attrs == [0] * 360                  # Codex P4.1e: SCGB_DIPLOMA neutral palette 0
    assert c.mem[mb + 9] == 2


@pytest.mark.parametrize("title", TITLES)
def test_caps_without_panel_bit_is_fresh_but_never_paints(title):
    """P4.1c ships caps = 0: the service is live (fresh) but the panel is ABSENT for painting."""
    c = Cart(title, caps=0)
    hold(c)
    c.step(2)
    assert c.panel.fresh(c.panel) and not c.panel.present(c.panel)
    c.open_panel()
    assert c.writes == []


def test_stale_mailbox_from_last_session_is_not_fresh():
    """Reset's 32-DelayFrame window / New Game: every byte says SLNK v3 + PANEL, but the counter
    never moves, so it is last session's mailbox and must not paint."""
    c = Cart("crystal")
    c.service_rom()
    c.running = False
    hold(c)
    c.step(3)
    c.mem[c.mb + 9] = 1
    c.step(3)
    assert not c.panel.fresh(c.panel) and not c.panel.present(c.panel)
    assert c.writes == []


def test_counter_stall_past_stall_window_goes_stale_again():
    c = Cart("gold")
    c.step(2)
    assert c.panel.fresh(c.panel)
    c.running = False
    c.step(int(c.P.STALL))
    assert c.panel.fresh(c.panel)              # within the window
    c.step()
    assert not c.panel.fresh(c.panel)


@pytest.mark.parametrize("fault", ["cookie", "version"])
def test_moving_counter_without_cookie_or_version_is_not_fresh(fault):
    c = Cart("silver", cookie=0x00 if fault == "cookie" else 0xA5)
    if fault == "version":
        orig = c.service_rom
        c.service_rom = lambda: (orig(), c.mem.__setitem__(c.mb + 4, 2))
    c.step(5)
    assert not c.panel.fresh(c.panel)


def test_await_already_up_when_the_service_turns_fresh_is_never_painted():
    c = Cart("crystal")
    hold(c)
    c.mem[c.mb + 9] = 1                        # AWAIT of unknown age
    c.step(5)
    assert c.writes == []


def test_profile_without_overlay_block_binds_nothing():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    P = lua.eval(f'dofile("{PANEL}")')
    prof = dict(profile("crystal"))
    del prof["overlay"]
    panel, why = P.new(lua.table_from(prof, recursive=True), lua.table(), lua.table(), lua.table(), None)
    assert panel is None and "overlay" in why


def test_panel_window_refuses_outside_wram0_and_outside_allow():
    c = Cart("crystal")
    c.w.arm(c.w, "panel", c.lua.eval("function(a, n) return true end"))
    with pytest.raises(lupa.LuaError, match="domain bounds"):
        c.w.write_bytes(c.w, 0xD000, c.lua.table(1))
    c.w.arm(c.w, "overworld", c.lua.eval("function(a, n) return true end"))
    with pytest.raises(lupa.LuaError, match="domain bounds"):
        c.w.write_bytes(c.w, c.tm, c.lua.table(1))
    c.w.arm(c.w, "panel", c.panel.allow)
    with pytest.raises(lupa.LuaError, match="window"):
        c.w.write_bytes(c.w, c.mb + 8, c.lua.table(1))      # caps is the ROM's
    c.w.disarm(c.w)


# -- Lua constants == slink_abi.inc / slink.asm -------------------------------------------------

def _asm_consts():
    return {k: int(v[1:], 16) if v.startswith("$") else int(v)
            for k, v in re.findall(r"^DEF\s+(\w+)\s+EQU\s+(\$[0-9a-fA-F]+|\d+)\s*$", SLINK_ASM.read_text(), re.M)}


def _mismatches(P, abi, asm):
    want = {
        "ABI_VERSION": abi["SLINK_ABI_VERSION"], "OFF_COUNTER": abi["SLINK_OFS_FRAME_COUNTER"],
        # slink.asm: SLINK_SAMPLE_VALID = wSlinkMailbox + SLINK_PUBLIC_SIZE + 1, PUBLIC = core + lease
        "OFF_COOKIE": abi["SLINK_CORE_SIZE"] + abi["SLINK_TRADE_LEASE_SIZE"] + 1,
        "COOKIE": asm["SLINK_SAMPLE_COOKIE"],
    }
    return [k for k, v in want.items() if P[k] != v]


def test_gen2_panel_constants_equal_slink_abi_inc_and_service_asm():
    P = lupa.LuaRuntime().eval(f'dofile("{PANEL}")')
    assert _mismatches(P, _abi(), _asm_consts()) == []


def test_constant_probe_catches_a_drift():
    """Known-positive control: a shifted lease size moves the cookie."""
    P = lupa.LuaRuntime().eval(f'dofile("{PANEL}")')
    assert _mismatches(P, dict(_abi(), SLINK_TRADE_LEASE_SIZE=15), _asm_consts()) == ["OFF_COOKIE"]


def test_cookie_fits_every_title_mailbox():
    sizes = {int(m.group(1), 16) for t in TITLES for m in re.finditer(
        r"SECTION: \$[0-9a-f]+-\$[0-9a-f]+ \(\$([0-9a-f]+) bytes\) \[\"SLink Mailbox\"\]",
        (REPO / f"data/gen2/{t}_slink.map").read_text())}
    P = lupa.LuaRuntime().eval(f'dofile("{PANEL}")')
    assert sizes and all(s > P.OFF_COOKIE for s in sizes)


# -- the pinned-sym derivation -------------------------------------------------------------------

@pytest.mark.parametrize("title", TITLES)
def test_overlay_block_equals_the_pinned_slink_sym_and_admission_row(title):
    ov = profile(title)["overlay"]
    raw = (REPO / "data/gen2" / ov["sym"]).read_bytes()
    assert ov["sym"] == f"{title}_slink.sym"
    assert ov["sym_sha256"] == hashlib.sha256(raw).hexdigest() == PROVENANCE["symbols"][ov["sym"]]
    syms = parse_symbols(raw.decode())
    assert ov["ram"] == {name: syms[name].address for name in gen_gen2_profile.OVERLAY_RAM}
    assert all(syms[name].bank == 0 for name in ov["ram"])
    out = PROVENANCE["outputs"][ARTIFACT[title]]
    row = next(r for r in json.loads((REPO / f"data/games/gen2_{title}/admission.json").read_text())["artifacts"]
               if r["kind"] == "overlay")
    assert row["status"] == "BUILT" and row["selection"] == "FUTURE"
    assert ov["rom_sha1"] == row["sha1"] == out["sha1"] != ov["base_sha1"]
    assert ov["md5"] == row["md5"] == out["md5"]


def _overlay_root(tmp_path):
    (tmp_path / "data/gen2").mkdir(parents=True)
    for name in ["overlay_provenance.json", *PROVENANCE["symbols"]]:
        shutil.copy(REPO / "data/gen2" / name, tmp_path / "data/gen2" / name)
    return tmp_path


class _Ctx:
    artifact = "pokecrystal"
    lock = json.loads((REPO / "data/gen2_sources.lock.json").read_text())


def test_overlay_block_refuses_a_sym_that_is_not_the_pinned_one(tmp_path):
    root = _overlay_root(tmp_path)
    assert gen_gen2_profile.overlay_block(_Ctx, "crystal", root)["ram"] == profile("crystal")["overlay"]["ram"]
    sym = root / "data/gen2/crystal_slink.sym"
    sym.write_text(sym.read_text().replace("00:cfd8 wSlinkMailbox", "00:cfd0 wSlinkMailbox"))
    with pytest.raises(ValueError, match="differs from overlay provenance"):
        gen_gen2_profile.overlay_block(_Ctx, "crystal", root)


def test_null_overlay_build_has_no_overlay_block(tmp_path):
    root = _overlay_root(tmp_path)
    prov = json.loads((root / "data/gen2/overlay_provenance.json").read_text())
    out = prov["outputs"]["pokecrystal"]
    out.update(identical_to_clean=True, sha1=out["base_sha1"])
    (root / "data/gen2/overlay_provenance.json").write_text(json.dumps(prov))
    assert gen_gen2_profile.overlay_block(_Ctx, "crystal", root) is None


# -- the client hook (lua/gen2/client.lua P4.1f block, composed by entry.lua in production) -------

def _service(w, state, frames=1, caps=CAP_PANEL):
    """The P4.1c service as the ROM runs it once per frame, plus the patch's panel state byte."""
    mb = w.profile["overlay"]["ram"]["wSlinkMailbox"]
    for _ in range(frames):
        state["counter"] = (state["counter"] + 1) & 0xFFFF
        w.emu.poke("System Bus", mb, w.lua.table_from(
            [0x53, 0x4C, 0x4E, 0x4B, 3, state["counter"] & 0xFF, state["counter"] >> 8, 0, caps]))
        w.emu.poke("System Bus", mb + 31, w.lua.table_from([0xA5]))
        w.frames(1)


def test_production_client_on_a_clean_cartridge_advertises_no_panel():
    from tests.unit.test_gen2_client import World
    w = World("crystal", production=True)
    hello = w.hello()
    w.frames(5)
    assert hello["panel"] is False and hello["panel_abi"] == 0 and hello["sfx"] is False
    tm = w.profile["overlay"]["ram"]["wTilemap"]
    assert not [x for x in w.written() if tm <= x[0] < tm + 360]


def test_production_client_holds_link_panel_rows_and_paints_on_the_await_transition():
    from tests.unit.test_gen2_client import World
    w = World("crystal", production=True)
    ram = w.profile["overlay"]["ram"]
    mb, tm, am = ram["wSlinkMailbox"], ram["wTilemap"], ram["wAttrmap"]
    state = {"counter": 0}
    _service(w, state, 3)
    hello = w.hello()
    assert hello["panel"] is True and hello["panel_abi"] == 3 and hello["sfx"] is False
    w.reply({"cmd": "link_panel", "rows": ["SOUL LINK", "PAIRED"]})
    _service(w, state, 2)                                    # rows held; CLOSED observed
    before = len(w.written())
    w.emu.poke("System Bus", mb + 9, w.lua.table_from([1]))  # the patch: CLOSED -> AWAIT
    _service(w, state, 1)
    painted = w.written()[before:]
    assert painted, w.logs.values()
    addrs = {x[0] for x in painted}
    assert tm in addrs and am in addrs and mb + 9 in addrs
    assert w.io.read_u8(mb + 9) == 2                        # STAGED published


# -- P4.2b: the SE table and the request_sfx path (gb_panel + lua/sfx_arbiter.lua) -----------------

CAP_SFX, CAP_SFX_NOTIFY = 0x01, 0x04
CAPS_FULL = CAP_PANEL | CAP_SFX | CAP_SFX_NOTIFY      # sfx.asm with SLINK_PANEL_ENABLED
SFX_ASM = REPO / "patch" / "gen2" / "src" / "sfx.asm"


@pytest.mark.parametrize("caps, success", [(CAPS_FULL, 4), (CAP_PANEL | CAP_SFX, 1)])
def test_server_ids_map_to_the_gen2_semantic_codes(caps, success):
    c = Cart("crystal", caps=caps)
    c.step(2)
    code = lambda sid: c.panel.sfx_code_for(c.panel, sid)
    assert [code(25), code(26), code(22), code(95)] == [success, 2, 3, 1]
    assert code(7) is None and code(193) is None and code(0) is None


def test_se_table_and_ranks_use_named_constants_never_literals():
    """Review-red falsifier: a literal SE id or code in the binding instead of the named constant
    (lua/sfx_arbiter.lua:20). Rank values are priorities, not ids, so only rank KEYS are checked."""
    src = pathlib.Path(PANEL).read_text(encoding="utf-8")
    table = src.split("P.SFX_CODE_FOR_GEN3_ID = {", 1)[1].split("}", 1)[0]
    ranks = src.split("P.SFX_RANKS = {", 1)[1].split("}", 1)[0]
    pairs = re.findall(r"\[([^\]]+)\]\s*=\s*([^,]+)", table)
    assert len(pairs) == 4 and all(re.fullmatch(r"P\.SE_[A-Z]+", k.strip()) and re.fullmatch(r"P\.SFX_[A-Z]+", v.strip())
                                   for k, v in pairs), pairs
    keys = re.findall(r"\[([^\]]+)\]", ranks)
    assert keys and all(re.fullmatch(r"P\.SFX_[A-Z]+", k.strip()) for k in keys), keys
    P = lupa.LuaRuntime().eval(f'dofile("{PANEL}")')
    assert (P.SFX_SUCCESS, P.SFX_FAILURE, P.SFX_BOO, P.SFX_NOTIFY) == (1, 2, 3, 4)


def test_semantic_codes_equal_the_abi_and_the_service_sound_table():
    abi = _abi()
    P = lupa.LuaRuntime().eval(f'dofile("{PANEL}")')
    assert (P.SFX_SUCCESS, P.SFX_FAILURE, P.SFX_BOO, P.SFX_NOTIFY) == (
        abi["SLINK_SFX_SUCCESS"], abi["SLINK_SFX_FAILURE"], abi["SLINK_SFX_BOO"], abi["SLINK_SFX_NOTIFY"])
    sounds = re.search(r"^\.sounds\s*\n\s*db\s+(.+)$", SFX_ASM.read_text(), re.M).group(1)
    assert [s.strip() for s in sounds.split(",")] == ["SFX_ITEM", "SFX_WRONG", "SFX_BUMP", "SFX_READ_TEXT_2"]


def test_one_cue_per_frame_the_failure_wins_and_posts_on_service():
    c = Cart("gold", caps=CAPS_FULL)
    c.step(2)
    p = c.panel
    assert p.request_sfx(p, 1) and p.request_sfx(p, 2) and p.request_sfx(p, 1)
    assert c.mem[c.mb + 7] == 0                # nothing posted until service()
    c.writes.clear()
    c.step()
    assert c.writes == [(c.mb + 7, [2])]
    c.mem[c.mb + 7] = 0                        # the ROM played it
    c.writes.clear()
    c.step(3)
    assert c.writes == []                      # the losing cues were dropped, not deferred


def test_unknown_code_and_non_sfx_cartridge_are_refused_and_never_written():
    c = Cart("silver", caps=CAP_PANEL)         # live, but no SFX bit
    c.step(2)
    p = c.panel
    assert not p.sfx_present(p) and p.request_sfx(p, 1) is False
    c2 = Cart("silver", caps=CAPS_FULL)
    c2.step(2)
    assert c2.panel.request_sfx(c2.panel, 5) is False and c2.panel.request_sfx(c2.panel, 0) is False
    c.writes.clear(); c2.writes.clear()
    c.step(2); c2.step(2)
    assert c.writes == [] and c2.writes == [] and c2.mem[c2.mb + 7] == 0


def test_clear_sfx_drops_the_pending_cue():
    c = Cart("crystal", caps=CAPS_FULL)
    c.step(2)
    assert c.panel.request_sfx(c.panel, 2)
    c.panel.clear_sfx(c.panel)
    c.writes.clear()
    c.step(2)
    assert c.writes == []


def _service_sfx(w, state, frames=1, caps=CAPS_FULL):
    """_service, but leaving the host-owned request byte +7 alone (the ROM consumes it)."""
    mb = w.profile["overlay"]["ram"]["wSlinkMailbox"]
    for _ in range(frames):
        state["counter"] = (state["counter"] + 1) & 0xFFFF
        w.emu.poke("System Bus", mb, w.lua.table_from(
            [0x53, 0x4C, 0x4E, 0x4B, 3, state["counter"] & 0xFF, state["counter"] >> 8]))
        w.emu.poke("System Bus", mb + 8, w.lua.table_from([caps]))
        w.emu.poke("System Bus", mb + 31, w.lua.table_from([0xA5]))
        w.frames(1)


def test_production_client_advertises_sfx_and_posts_the_mapped_code():
    from tests.unit.test_gen2_client import World
    w = World("gold", production=True)
    mb = w.profile["overlay"]["ram"]["wSlinkMailbox"]
    state = {"counter": 0}
    _service_sfx(w, state, 3)
    hello = w.hello()
    assert hello["sfx"] is True and hello["panel"] is True
    w.reply({"cmd": "config", "native_sounds": True})
    _service_sfx(w, state, 2)
    w.reply({"cmd": "play_sound", "sound": 7})              # no Gen 2 sound: dropped, never sent
    _service_sfx(w, state, 3)
    assert not [x for x in w.written() if x[0] == mb + 7]
    w.reply({"cmd": "play_sound", "sound": 26})
    _service_sfx(w, state, 3)
    assert [x for x in w.written() if x[0] == mb + 7] and w.io.read_u8(mb + 7) == 2


def test_production_client_native_sounds_off_posts_nothing():
    from tests.unit.test_gen2_client import World
    w = World("crystal", production=True)
    mb = w.profile["overlay"]["ram"]["wSlinkMailbox"]
    state = {"counter": 0}
    _service_sfx(w, state, 3)
    assert w.hello()["sfx"] is True
    w.reply({"cmd": "config", "native_sounds": False})
    w.reply({"cmd": "play_sound", "sound": 26})
    _service_sfx(w, state, 4)
    assert not [x for x in w.written() if x[0] == mb + 7]


def test_production_client_live_panel_without_sfx_bit_says_sfx_false():
    from tests.unit.test_gen2_client import World
    w = World("crystal", production=True)
    state = {"counter": 0}
    _service_sfx(w, state, 3, caps=CAP_PANEL)
    hello = w.hello()
    assert hello["panel"] is True and hello["sfx"] is False
