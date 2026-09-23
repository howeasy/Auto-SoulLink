"""2B-OBS: lua/tests/gen3_battle_window_rows.lua + gen3_battle_window_syms.lua on synthetic RAM.

No emulator. The world is the committed FR/LG pack plus a Lua RAM table; the verdict is always
the real lua/gen3/safety.lua. Engine values (controller pointers, symbols, object spans) come from
data/gen3/pret/*.sym/.map, never from the module under test. Each row's first falsifier runs
here: a normal-input state mislabelled as the row's state, a disabled required clause, and zero
samples must never PASS.
"""
import json
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")
ROOT = Path(__file__).resolve().parents[2]
PRET = ROOT / "data/gen3/pret"
TITLES = ["firered", "leafgreen"]
HASHES = {"rom": "r0", "fixture": "f0", "pack": "p0", "source": "s0", "state": "st0"}


def pret_syms(title):
    out = {}
    for line in (PRET / f"poke{title}.sym").read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[1] in ("l", "g"):
            out.setdefault(parts[3], []).append(int(parts[0], 16))
    return out


def text_spans(title):
    out = {}
    for line in (PRET / f"poke{title}.map").read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[0] == ".text" and parts[3].endswith(".o"):
            out[parts[3]] = (int(parts[1], 16), int(parts[1], 16) + int(parts[2], 16))
    return out


_SYMS = {t: pret_syms(t) for t in TITLES}
_SPANS = {t: text_spans(t) for t in TITLES}


def in_object(title, name, obj):
    """The one spelling of `name` inside obj's .text span, Thumb bit set."""
    lo, hi = _SPANS[title][obj]
    hits = [a for a in _SYMS[title][name] if lo <= a < hi]
    assert len(hits) == 1, (title, name, obj, hits)
    return hits[0] | 1


def sym(title, name):
    return _SYMS[title][name][0]


def fn(title, name):
    return sym(title, name) | 1


PLAYER = "src/battle_controller_player.o"
OAK = "src/battle_controller_oak_old_man.o"
DUDE = "src/battle_controller_pokedude.o"


class World:
    """Pack + RAM + real safety, parked at the player's action menu (all seven clauses TRUE)."""

    def __init__(self, title, drop=None, pack_edit=None):
        self.title = title
        pack = json.loads((ROOT / "data/games/gen3_frlg/write_checkpoint.json").read_text())[title]
        if drop:
            pack["battle"]["clauses"] = [c for c in pack["battle"]["clauses"] if c["name"] != drop]
        if pack_edit:
            pack_edit(pack)
        self.pack = pack
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute("""
            mem = {}; rom = {}
            function put(a, v, n) for i=0,n-1 do mem[a+i] = v % 256; v = v // 256 end end
            function read(a, n, domain)
                local src = domain == 'ROM' and rom or mem
                local v = 0
                for i=0,n-1 do v = v + (src[a+i] or 0) * 256^i end
                return math.tointeger(v)
            end
            frame = 100
            deps = {io={read_u8=function(a,d) return read(a,1,d) end,
                        read_u16_le=function(a,d) return read(a,2,d) end,
                        read_u32_le=function(a,d) return read(a,4,d) end},
                    regs=function() return {R15=0x080008AC, CPSR=0x3F} end,
                    frame=function() return frame end}
        """)
        g = self.g = self.lua.globals()
        for anchor in pack["anchors"].values():
            for i, byte in enumerate(bytes.fromhex(anchor["expected_hex"]["clean"])):
                g.rom[anchor["rom_offset"] + i] = byte
        lua_pack = self.lua.table_from(pack, recursive=True)
        safety_mod = self.lua.execute((ROOT / "lua/gen3/safety.lua").read_text(encoding="utf-8"))
        self.safety = safety_mod.new(lua_pack, g.deps, "clean")
        rows = self.lua.execute((ROOT / "lua/tests/gen3_battle_window_rows.lua").read_text(encoding="utf-8"))
        self.R = rows
        self.ctx = rows.bind(lua_pack, title, g.deps, ROOT.as_posix())
        self.set()

    def set(self, main=None, comm=(1, 0, 0, 0), flags=1, ctrl0=None, type_=0x4, maxhp=20, outcome=0,
            cb2=None, in_battle=True, fade=False, tasks=(), party=(0, 1, 0, 0), chosen0=0,
            ret=(0x21, 0, 0, 0), pm=(0, 0, 0), bag_location=0, trainer=0):
        """Write one engine state. Defaults = the parked action menu of a wild single battle."""
        t, put = self.title, self.g.put
        s = _SYMS[t]
        put(s["gBattleMainFunc"][0], fn(t, "HandleTurnActionSelectionState") if main is None else main, 4)
        for i, v in enumerate(comm):
            put(s["gBattleCommunication"][0] + i, v, 1)
        put(s["gBattleControllerExecFlags"][0], flags, 4)
        put(s["gBattlerControllerFuncs"][0], in_object(t, "HandleInputChooseAction", PLAYER)
            if ctrl0 is None else ctrl0, 4)
        put(s["gBattlerControllerFuncs"][0] + 4, fn(t, "OpponentBufferRunCommand"), 4)
        put(s["gBattleTypeFlags"][0], type_, 4)
        put(s["gBattleMons"][0] + 0x2C, maxhp, 2)
        put(s["gBattleOutcome"][0], outcome, 1)
        put(s["gMain"][0] + 4, fn(t, "BattleMainCB2") if cb2 is None else cb2, 4)
        put(s["gMain"][0] + 0x439, 2 if in_battle else 0, 1)
        put(s["gPaletteFade"][0] + 7, 0x80 if fade else 0, 1)
        tb = self.pack["tasks"]
        for i in range(tb["count"]):
            base = tb["address"] + i * tb["struct_size"]
            active = i < len(tasks)
            put(base + tb["func_offset"], tasks[i] if active else 0, 4)
            put(base + tb["is_active_offset"], 1 if active else 0, 1)
        for i, v in enumerate(party):
            put(s["gBattlerPartyIndexes"][0] + 2 * i, v, 2)
        put(s["gChosenActionByBattler"][0], chosen0, 1)
        for i, v in enumerate(ret):
            put(s["gBattleBufferB"][0] + i, v, 1)
        menu_type, action, slot = pm
        put(s["gPartyMenu"][0] + 8, menu_type, 1)
        put(s["gPartyMenu"][0] + 9, slot, 1)
        put(s["gPartyMenu"][0] + 11, action, 1)
        put(s["gPlayerParty"][0] + slot * 100, 0xABCD0000 + slot, 4)
        put(s["gBagMenuState"][0] + 4, bag_location, 1)
        put(s["gTrainerBattleOpponent_A"][0], trainer, 2)

    def sample(self, reason="battle_faint"):
        extra = self.lua.table_from({"map": "3.19", "pos": "12,37"})
        return self.ctx.sample(self.ctx, self.safety, reason, None, extra)

    def run(self, name, states, reason="battle_faint"):
        """Feed one sample per state dict; return (status, why, acc)."""
        acc = self.R.row(self.ctx, name)
        for st in states:
            self.set(**st)
            self.R.feed(acc, self.sample(reason))
        status, why = self.R.verdict(acc)
        return status, why, acc


def p(title, name, obj=PLAYER):
    return in_object(title, name, obj)


# ── named engine states (pret battle_controller_player.c / battle_main.c; values per title) ─
def draw(t):
    return {"ctrl0": p(t, "HandleChooseActionAfterDma3")}


def parked(t):
    return {}


def bag(t, **kw):
    st = {"comm": (2, 0, 0, 0), "ctrl0": p(t, "CompleteWhenChoseItem"), "cb2": fn(t, "CB2_BagMenuRun"),
          "tasks": (fn(t, "Task_BagMenu_HandleInput"),), "bag_location": 5, "chosen0": 1}
    st.update(kw)
    return st


def party_menu(t, **kw):
    st = {"comm": (2, 0, 0, 0), "ctrl0": p(t, "WaitForMonSelection"), "cb2": fn(t, "CB2_UpdatePartyMenu"),
          "tasks": (fn(t, "Task_HandleChooseMonInput"),), "pm": (1, 0, 1), "chosen0": 2}
    st.update(kw)
    return st


def summary(t, **kw):
    st = {"comm": (2, 0, 0, 0), "ctrl0": p(t, "WaitForMonSelection"),
          "cb2": fn(t, "CB2_RunPokemonSummaryScreen"), "pm": (1, 0, 1), "chosen0": 2}
    st.update(kw)
    return st


def committed(t, **kw):
    st = {"flags": 0, "ctrl0": p(t, "PlayerBufferRunCommand")}
    st.update(kw)
    return st


# ── the syms file, proven against the .sym and the linker map ──────────────────────────────
@pytest.fixture(scope="module")
def wsyms():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    return lua.execute((ROOT / "lua/tests/gen3_battle_window_syms.lua").read_text(encoding="utf-8"))


@pytest.mark.parametrize("title", TITLES)
def test_syms_match_sym_and_map(wsyms, title):
    for name, e in wsyms.entries.items():
        if e.object:
            want = in_object(title, e.symbol, e.object) & ~1
        else:
            assert len(_SYMS[title][e.symbol]) == 1, (name, "ambiguous without an object")
            want = sym(title, e.symbol)
        if e.thumb:
            want |= 1
        assert e[title] == want, (name, hex(e[title]), hex(want))
    for short, o in wsyms.objects.items():
        assert tuple(o[title].values()) == _SPANS[title][o.object], short


@pytest.mark.parametrize("title", TITLES)
def test_tutorial_spellings_are_not_the_first_same_named_symbol(wsyms, title):
    first = _SYMS[title]["HandleInputChooseAction"][0] | 1
    assert first == p(title, "HandleInputChooseAction")            # the player's links first
    for key in ("OLDMAN_INPUT_CHOOSE_ACTION", "POKEDUDE_INPUT_CHOOSE_ACTION"):
        assert wsyms.entries[key][title] != first


def test_syms_refuse_other_titles(wsyms):
    with pytest.raises(lupa.LuaError, match="unsupported title"):
        wsyms.for_title("radical_red")


# ── the tuple and the receipt ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("title", TITLES)
def test_parked_tuple_is_all_true_and_receipt_is_complete(title):
    w = World(title)
    s = w.sample()
    assert s.ok is True and len(s.failed) == 0
    assert all(s.t[a] is True for a in "MCFPLHO")
    line = w.ctx.receipt(w.ctx, s, w.lua.table_from({"row": "T1", "hashes": w.lua.table_from(HASHES),
                                                     "state_path": "x.State", "prep": "prep1"}))
    for field in ("title=" + title, "reason=battle_faint", "rom=r0", "fixture=f0", "pack=p0", "source=s0",
                  "state=st0", "state_path=x.State", "prep=prep1", "map=3.19", "pos=12,37", "frame=100",
                  "R15=0x080008AC", "CPSR=0x0000003F", "M=0x08014041:T", "C=0x01:T", "F=0x00000001:T",
                  "P=0x0802E439:T", "L=0x00000000:T", "H=0x0014:T", "O=0x00:T", "permit=true", "failed=-",
                  "type=0x00000004", "trainer=0", "comm=1,0,0,0", "party=0,1,0,0", "outcome=0",
                  "0x0802E439[player:HandleInputChooseAction]"):
        assert field in line, field


def test_receipt_lists_every_failure_sorted_and_refuses_a_missing_hash():
    w = World("firered")
    w.set(comm=(2, 0, 0, 0), flags=0, outcome=4, ctrl0=p("firered", "HandleInputChooseMove"))
    s = w.sample()
    meta = {"row": "x", "hashes": w.lua.table_from(HASHES)}
    line = w.ctx.receipt(w.ctx, s, w.lua.table_from(meta))
    assert ("failed=battle_comm_0,battle_exec_flags_input,battle_input_controller,battle_outcome_open"
            in line)
    assert "C=0x02:F" in line and "O=0x04:F" in line and "M=0x08014041:T" in line
    for missing in HASHES:
        partial = {k: v for k, v in HASHES.items() if k != missing}
        with pytest.raises(lupa.LuaError, match=f"needs the {missing} hash"):
            w.ctx.receipt(w.ctx, s, w.lua.table_from({"row": "x", "hashes": w.lua.table_from(partial)}))


def test_disabled_clause_shows_absent_and_fails_every_row():
    w = World("firered", drop="battle_input_controller")
    line = w.ctx.receipt(w.ctx, w.sample(), w.lua.table_from({"row": "x", "hashes": w.lua.table_from(HASHES)}))
    assert "P=absent" in line
    for spec in w.R.ROWS.values():
        status, why = w.R.verdict(w.R.row(w.ctx, spec.name))
        assert (status, why) == ("FAIL", "pack lacks clause(s) P"), spec.name


# ── zero samples never PASS ─────────────────────────────────────────────────────────────────
def test_every_row_is_unreached_with_no_samples():
    w = World("firered")
    names = [spec.name for spec in w.R.ROWS.values()]
    assert names == ["N1", "N3", "N4", "N5", "N6", "N7", "N8", "N9", "U1", "U2"]
    for name in names:
        assert tuple(w.R.verdict(w.R.row(w.ctx, name))) == ("UNREACHED", "no qualifying sample"), name


@pytest.mark.parametrize("name", ["N1", "N3", "N4", "N5", "N6", "N7", "N8", "N9", "U1", "U2"])
def test_parked_normal_input_is_never_a_row_state(name):
    """The plain parked action menu (permit TRUE) mislabelled as any row: never qualifies."""
    status, _, acc = World("firered").run(name, [parked("firered")] * 120)
    assert status == "UNREACHED" and acc.samples == 0


# ── N1: draw then input ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("title", TITLES)
def test_n1_draw_then_input_passes(title):
    status, why, acc = World(title).run("N1", [draw(title)] * 2 + [parked(title)])
    assert (status, acc.samples, acc.terminals) == ("PASS", 2, 1), why


def test_n1_draw_without_input_is_unreached():
    status, why, _ = World("firered").run("N1", [draw("firered")] * 3)
    assert status == "UNREACHED" and "terminal" in why


def test_n1_draw_admitted_when_p_is_disabled_fails():
    """A P that no longer refuses the draw controller (expect swapped) must be caught."""
    def swap(pack):
        c = next(c for c in pack["battle"]["clauses"] if c["name"] == "battle_input_controller")
        c["expect"] = p("firered", "HandleChooseActionAfterDma3")
    status, why, _ = World("firered", pack_edit=swap).run("N1", [draw("firered"), parked("firered")])
    assert status == "FAIL" and "admitted" in why


def test_n1_refusal_by_another_clause_is_misattributed():
    """P disabled (swapped) while C refuses: refused, but not by P -> FAIL, not PASS."""
    def swap(pack):
        c = next(c for c in pack["battle"]["clauses"] if c["name"] == "battle_input_controller")
        c["expect"] = p("firered", "HandleChooseActionAfterDma3")
    st = dict(draw("firered"), comm=(2, 0, 0, 0))
    status, why, _ = World("firered", pack_edit=swap).run("N1", [st, parked("firered")])
    assert status == "FAIL" and "battle_input_controller did not fail" in why


# ── N3 target / N4 bag / N5 party / N6 summary: held menus, floor 60 ─────────────────────────
@pytest.mark.parametrize("title", TITLES)
def test_n3_target_menu(title):
    target = {"comm": (2, 0, 0, 0), "ctrl0": p(title, "HandleInputChooseTarget")}
    assert World(title).run("N3", [target] * 60)[0] == "PASS"
    assert World(title).run("N3", [target] * 59)[0] == "UNREACHED"          # floor
    move = {"comm": (2, 0, 0, 0), "ctrl0": p(title, "HandleInputChooseMove")}
    assert World(title).run("N3", [move] * 60)[0] == "UNREACHED"            # move menu is not target


@pytest.mark.parametrize("title", TITLES)
def test_n4_battle_bag(title):
    status, why, acc = World(title).run("N4", [bag(title)] * 60)
    assert status == "PASS" and acc.samples == 60, why
    # field bag: not in battle, field location -> not the battle bag
    field = bag(title, in_battle=False, bag_location=0)
    assert World(title).run("N4", [field] * 60)[0] == "UNREACHED"
    # a stale battle location after the battle ended (gMain.inBattle clear)
    assert World(title).run("N4", [bag(title, in_battle=False)] * 60)[0] == "UNREACHED"
    # opening fade: Task_AnimateWin0v still running / palette fade active -> not counted
    fading = bag(title, tasks=(fn(title, "Task_BagMenu_HandleInput"), fn(title, "Task_AnimateWin0v")))
    assert World(title).run("N4", [fading] * 60 + [bag(title, fade=True)] * 60)[1] == "no qualifying sample"
    # unopened bag: the action menu with the cursor on BAG
    assert World(title).run("N4", [{"chosen0": 1}] * 60)[0] == "UNREACHED"


def test_n4_disabled_comm_clause_fails():
    def loosen(pack):
        next(c for c in pack["battle"]["clauses"] if c["name"] == "battle_comm_0")["expect"] = 2
    status, why, _ = World("firered", pack_edit=loosen).run("N4", [bag("firered")] * 60)
    assert status == "FAIL" and "battle_comm_0 did not fail" in why


@pytest.mark.parametrize("title", TITLES)
def test_n5_voluntary_party_menu(title):
    assert World(title).run("N5", [party_menu(title)] * 60)[0] == "PASS"
    # forced send-out after a faint: SEND_OUT action, main func elsewhere -> not voluntary
    forced = party_menu(title, pm=(1, 1, 1), main=fn(title, "RunBattleScriptCommands"))
    assert World(title).run("N5", [forced] * 60)[0] == "UNREACHED"
    # overworld party menu
    assert World(title).run("N5", [party_menu(title, in_battle=False, pm=(0, 0, 1))] * 60)[0] == "UNREACHED"


@pytest.mark.parametrize("title", TITLES)
def test_n6_summary_from_battle_party(title):
    status, why, acc = World(title).run("N6", [summary(title)] * 60)
    assert status == "PASS", why
    assert acc.first.slot_key == 0xABCD0001
    assert World(title).run("N6", [summary(title, in_battle=False, pm=(0, 0, 1))] * 60)[0] == "UNREACHED"
    assert World(title).run("N6", [summary(title, in_battle=False)] * 60)[0] == "UNREACHED"   # stale menu


# ── N7/N8/N9: committed transitions ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("title", TITLES)
def test_n7_switch_commit_until_replacement(title):
    chosen = committed(title, chosen0=2, ret=(0x22, 1, 0, 1), comm=(3, 0, 0, 0))
    seq = [party_menu(title)] * 3 + [chosen] * 5 + [dict(chosen, party=(1, 1, 0, 0))] \
        + [{"party": (1, 1, 0, 0), "chosen0": 2, "ret": (0x22, 1, 0, 1)}]
    w = World(title)
    status, why, acc = w.run("N7", seq)
    assert (status, acc.samples, acc.terminals) == ("PASS", 5, 1), why
    line = w.R.verdict_line(acc)[0]
    assert "from=0 selected=1" in line


def test_n7_only_the_reopened_menu_after_switch_is_unreached():
    after = {"party": (1, 1, 0, 0), "chosen0": 2, "ret": (0x22, 1, 0, 1)}
    assert World("firered").run("N7", [after] * 60)[0] == "UNREACHED"


def test_n7_cancelled_party_menu_is_not_a_commit():
    cancel = committed("firered", chosen0=2, ret=(0x22, 6, 0, 0))     # PARTY_SIZE = cancelled
    status, _, acc = World("firered").run("N7", [cancel] * 10)
    assert status == "UNREACHED" and acc.samples == 0


def test_n7_commit_admitted_fails():
    def swap(pack):
        next(c for c in pack["battle"]["clauses"] if c["name"] == "battle_input_controller")["expect"] = \
            p("firered", "PlayerBufferRunCommand")
        next(c for c in pack["battle"]["clauses"] if c["name"] == "battle_exec_flags_input")["expect"] = 0
    chosen = committed("firered", chosen0=2, ret=(0x22, 1, 0, 1))
    status, why, _ = World("firered", pack_edit=swap).run("N7", [chosen, dict(chosen, party=(1, 1, 0, 0))])
    assert status == "FAIL" and "admitted" in why


@pytest.mark.parametrize("title", TITLES)
def test_n8_item_commit_then_catch(title):
    used = committed(title, chosen0=1, ret=(0x23, 4, 0, 0))
    w = World(title)
    status, why, acc = w.run("N8", [bag(title)] * 2 + [used] * 4 + [dict(used, outcome=7)])
    assert (status, acc.samples) == ("PASS", 4), why
    assert "item=4 ended=outcome=7" in w.R.verdict_line(acc)[0]


def test_n8_bag_closed_without_item_is_unreached():
    none = committed("firered", chosen0=1, ret=(0x23, 0, 0, 0))
    assert World("firered").run("N8", [bag("firered")] * 60 + [none] * 10 + [parked("firered")])[0] == "UNREACHED"


def test_n8_ball_missed_reopens():
    used = committed("firered", chosen0=1, ret=(0x23, 4, 0, 0))
    status, _, acc = World("firered").run("N8", [used] * 3 + [draw("firered")])
    assert status == "PASS" and acc.st.ended == "reopened"


@pytest.mark.parametrize("title", TITLES)
def test_n9_run_commit_then_ran(title):
    ran = committed(title, ret=(0x21, 3, 0, 0))
    status, why, acc = World(title).run("N9", [parked(title)] * 5 + [ran] * 4 + [dict(ran, outcome=4)])
    assert (status, acc.samples, acc.terminals) == ("PASS", 4, 1), why
    assert all(k in acc.first.failed.values() for k in ("battle_exec_flags_input", "battle_input_controller"))


def test_n9_failed_escape_is_not_ended():
    ran = committed("firered", ret=(0x21, 3, 0, 0))
    status, why, _ = World("firered").run("N9", [ran] * 4 + [draw("firered")] + [parked("firered")] * 5)
    assert status == "UNREACHED" and "terminal" in why


def test_n9_only_parked_samples_is_unreached():
    stale = {"ret": (0x21, 3, 0, 0)}        # a stale RUN return at the reopened, parked menu
    assert World("firered").run("N9", [stale] * 60)[0] == "UNREACHED"


# ── U1 old man / U2 Pokedude ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("title", TITLES)
def test_u1_old_man_tutorial(title):
    oak = p(title, "HandleInputChooseAction", OAK)
    status, why, acc = World(title).run("U1", [{"type_": 0x200, "ctrl0": oak}] * 3)
    assert status == "PASS" and acc.samples == 3, why
    # tutorial flag with the PLAYER's same-named controller: not the tutorial
    assert World(title).run("U1", [{"type_": 0x200}] * 3)[0] == "UNREACHED"
    # Oak's controller without the OLD_MAN bit (BATTLE_TYPE_FIRST_BATTLE, the rival fight)
    assert World(title).run("U1", [{"type_": 0x10, "ctrl0": oak}] * 3)[0] == "UNREACHED"


@pytest.mark.parametrize("title", TITLES)
def test_u2_pokedude(title):
    dude = p(title, "HandleInputChooseAction", DUDE)
    status, why, _ = World(title).run("U2", [{"type_": 0x10000, "ctrl0": dude}] * 3)
    assert status == "PASS", why
    # the player's same-named symbol under the POKEDUDE flag: permit TRUE, so counting it would FAIL
    w = World(title)
    w.set(type_=0x10000)
    assert w.sample().ok is True
    assert World(title).run("U2", [{"type_": 0x10000}] * 3)[0] == "UNREACHED"
    assert World(title).run("U2", [{"ctrl0": dude}] * 3)[0] == "UNREACHED"       # no flag


def test_u2_disabled_p_fails():
    def swap(pack):
        next(c for c in pack["battle"]["clauses"] if c["name"] == "battle_input_controller")["expect"] = \
            p("firered", "HandleInputChooseAction", DUDE)
    dude = p("firered", "HandleInputChooseAction", DUDE)
    status, why, _ = World("firered", pack_edit=swap).run("U2", [{"type_": 0x10000, "ctrl0": dude}])
    assert status == "FAIL" and "admitted" in why


def test_wrong_reason_samples_fail():
    status, why, _ = World("firered").run("U1", [{"type_": 0x200,
                                                  "ctrl0": p("firered", "HandleInputChooseAction", OAK)}],
                                          reason="battle_commit")
    assert status == "FAIL" and "not taken for battle_faint" in why
