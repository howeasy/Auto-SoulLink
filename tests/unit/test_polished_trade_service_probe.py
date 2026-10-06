"""Synthetic consumer-visible service traces; no emulator, server or SLink client.

Six positive cases, independently corrupted publications/ownership/restoration,
runner pure parts, and actual Lua mock callbacks/serialization (no live emulator).
"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("trade_service_probe", ROOT / "tools/polished_live/trade_service_probe.py")
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)

SITES = {name: {"bank": 0x7E, "addr": 0x4500 + i * 16} for i, name in enumerate(P.HOOKS)}
SITES["SlinkTradeEntry"] = {"bank": 0x7E, "addr": 0x4480}
SITES["GetScriptByte"] = {"bank": 0x25, "addr": 0x4100}
SITES["Script_endtext"] = {"bank": 0x25, "addr": 0x4200}
SITES["service_return"] = {"bank": 0x7E, "addr": 0x4680}


def attach_accounting(trace):
    counts = {name: {"total": 0, "qualified": 0, "wrong_pc": 0, "wrong_banks": {},
                     "wrong_bank_samples": 0} for name in SITES}
    for e in trace:
        name = e.get("hook_site")
        if name not in counts:
            continue
        c = counts[name]
        c["total"] += 1
        if not e["matched"]:
            key = str(e["bank"])
            c["wrong_banks"][key] = c["wrong_banks"].get(key, 0) + 1
            c["wrong_bank_samples"] += 1
        elif e["qualified"]:
            c["qualified"] += 1
        else:
            c["wrong_pc"] += 1
    for e in trace:
        if e["kind"] in ("final", "complete"):
            e.update(hook_sites=copy.deepcopy(SITES), hook_counts=copy.deepcopy(counts),
                     wrong_bank_sample_limit=16, completed=True, driver_errors=0)
    return trace


class Trace:
    """Fixture author, not an emulator: explicit ROM/host stores build the evidence chain."""

    def __init__(self, case):
        self.case = case
        self.events = []
        self.frame = 100
        self.lease = [0] * 16
        self.record = [1] + [0] * 47
        self.record[31] = 50
        self.ot = [0x80] + [0x53] * 7 + [1, 2, 3]
        self.nick = [0x90] + [0x53] * 10
        self.own0 = P._checksum(self.record + self.ot + self.nick)
        self.ot0 = P._checksum([0] * 70)
        self.ot1 = self.ot0
        self.tx = None

    def add(self, kind, **fields):
        e = {"kind": kind, "ord": len(self.events) + 1, "frame": self.frame, "pc": 0x4480,
             "sp": 0xC0CE, "bank": 0x7E, "vblank": 0, "link": 0, "running": 1, "stack": 0,
             "count": 5, "party_sum": "01234567", "ot_tail_sum": "89abcdef",
             "own0_sum": self.own0, "ot0_sum": self.ot0, "ot1_sum": self.ot1,
             "lease": self.lease.copy(), "sbank": 0x24, "spos": 0x762C, "x": 5, "y": 3}
        if kind in P.HOOK_KINDS:
            name = P.HOOK_KINDS[kind]
            site = SITES[name]
            e.update(hook_site=name, hook_addr=site["addr"], pc=site["addr"], bank=site["bank"],
                     matched=True, qualified=True)
        if kind == "service_entry":
            e.update(return_addr=SITES["service_return"]["addr"], return_bank=SITES["service_return"]["bank"])
        e.update(fields)
        self.events.append(e)
        return e

    def tick(self, n=1):
        self.frame += n

    def write(self, owner, offset, value):
        before = self.lease.copy()
        self.lease[offset] = value
        fields = {"offset": offset, "value": value, "before": before}
        if owner == "host":
            fields["tx"] = self.tx
        self.add(owner + "_write", **fields)

    def begin(self, tx):
        self.tick()
        self.tx = tx
        self.add("host_begin", tx=tx, pump="onframeend")

    def end(self):
        self.add("host_end", tx=self.tx)
        self.tx = None

    def publish_query(self):
        self.tick()
        for offset, value in enumerate(P.MAGIC):
            self.write("rom", offset, value)
        for offset, value in ((5, 1), (10, 0), (11, 0), (7, 0), (6, 1)):
            self.write("rom", offset, value)

    def query_reply(self):
        self.begin("query")
        values = [1, 0 if self.case == "no-eligible" else 1] + P.TOKEN
        for offset, value in enumerate(values, 10):
            self.write("host", offset, value)
        self.write("host", 7, self.lease[6])
        self.end()

    def publish_offer(self):
        self.tick()
        self.ot1 = self.own0
        for offset, value in ((9, 0), (8, 255), (5, 2), (7, 1), (6, 2)):
            self.write("rom", offset, value)

    def offer_reply(self):
        self.begin("offer")
        self.write("host", 8, 1 if self.case == "offer-reject" else 0)
        self.write("host", 7, self.lease[6])
        self.end()

    def apply(self):
        self.begin("apply")
        ot = [0x81] + [0x53] * 7 + self.ot[8:]
        sender = [0x81] + [0x53] * 10
        nick = [0x80] * 11 if self.case == "apply-invalid" else self.nick
        payload = self.record + ot + nick
        for symbol, data in (("wOTPartyMon1", self.record), ("wOTPartyMonOTs", ot),
                             ("wOTPartyMonNicknames", nick), ("wOTPlayerName", sender)):
            for i, v in enumerate(data):
                self.add("host_stage_write", tx="apply", symbol=symbol, offset=i, value=v, old=0)
        self.ot0 = P._checksum(payload)
        self.add("staged", tx="apply", staged_sum=self.ot0, invalid=self.case == "apply-invalid",
                 record=bytes(self.record).hex(), ot=bytes(ot).hex(), nick=bytes(nick).hex(),
                 sender=bytes(sender).hex(), source_record=bytes(self.record).hex(),
                 source_ot=bytes(self.ot).hex(), source_nick=bytes(self.nick).hex())
        for offset, value in enumerate(P.MAGIC + [5, 2, 2, 255, 0, 1, 0] + P.TOKEN):
            self.write("host", offset, value)
        self.write("host", 6, 3)
        self.end()
        self.tick()
        self.write("rom", 7, 3)  # pickup ACK precedes incoming validation, not DONE

    def done(self):
        self.tick()
        self.write("rom", 8, 1)
        for offset, value in enumerate(P.MAGIC):
            self.write("rom", offset, value)
        for offset, value in enumerate(P.TOKEN, 12):
            self.write("rom", offset, value)
        for offset, value in ((9, 0), (5, 7), (6, 3), (7, 3)):
            self.write("rom", offset, value)
        self.begin("release")
        self.write("host", 5, 8)
        self.end()

    def close(self):
        self.tick()
        self.add("close")
        for offset in (5, 10, 11):
            self.write("rom", offset, 0)
        self.add("service_return", sp=0xC0D0, ret_sp=0xC0CE)
        self.add("gsb", bank=0x25, sbank=0x2D, spos=0x7595)
        self.add("endtext", bank=0x25, sbank=0x2D, spos=0x7596)
        self.tick(40)
        self.add("final", running=0)
        self.add("move_start", running=0)
        self.tick(24)
        self.add("move_end", running=0, y=4)
        self.add("complete", running=0, y=4, case=self.case)


def good_trace(case):
    t = Trace(case)
    t.add("setup", case=case, synth=True, token=P.TOKEN)
    t.add("service_entry")
    t.publish_query()
    if case == "query-timeout":
        t.tick(600)
    else:
        t.query_reply()
    if case not in ("no-eligible", "query-timeout"):
        t.tick()
        t.add("party_menu")
        t.add("answer", which="party", btn="B" if case == "cancel-menu" else "A", slot=0)
        if case != "cancel-menu":
            t.add("answer", which="confirm", btn="A")
            t.publish_offer()
            t.offer_reply()
            if case.startswith("apply-"):
                t.apply()
                if case == "apply-done1":
                    t.done()
    t.close()
    return attach_accounting(t.events)


def mutate(trace, kind, **fields):
    out = copy.deepcopy(trace)
    next(e for e in out if e["kind"] == kind).update(fields)
    return out


def rekind(trace, old, new, **fields):
    """Turn the first `old` event into a `new`-kind event (mutate's own `kind` parameter selects, never sets)."""
    out = copy.deepcopy(trace)
    e = next(e for e in out if e["kind"] == old)
    e.update(fields)
    e["kind"] = new
    return out


def renumber(trace):
    for i, e in enumerate(trace, 1):
        e["ord"] = i
    return trace


def missing(trace, kind):
    return renumber([e for e in copy.deepcopy(trace) if e["kind"] != kind])


def open_lease(trace):
    out = copy.deepcopy(trace)
    next(e for e in out if e["kind"] == "final")["lease"][5] = 2
    return out


def done_zero(trace):
    out = copy.deepcopy(trace)
    event = copy.deepcopy(next(e for e in out if e["kind"] == "close"))
    event.update(kind="done_observed", result=0)
    event["lease"][5], event["lease"][8] = 7, 0
    i = next(i for i, e in enumerate(out) if e["kind"] == "close")
    out.insert(i, event)
    return renumber(out)


def generation_early(trace):
    out = copy.deepcopy(trace)
    indices = [i for i, e in enumerate(out) if e["kind"] == "rom_write" and e["lease"][5] == 1]
    i_gen = next(i for i in indices if out[i]["offset"] == 6)
    i_ack = next(i for i in indices if out[i]["offset"] == 7)
    # One defect: swap the final generation/ACK stores and recompute their actual images.
    old = out[i_ack]["before"].copy()
    gen, ack = out[i_gen], out[i_ack]
    gen["before"] = old.copy()
    old[6] = gen["value"]
    gen["lease"] = old.copy()
    ack["before"] = old.copy()
    old[7] = ack["value"]
    ack["lease"] = old.copy()
    out[i_ack], out[i_gen] = gen, ack
    return renumber(out)


@pytest.mark.parametrize("case", P.CASES)
def test_each_good_scenario_passes(case):
    ok, reasons = P.evaluate(case, good_trace(case))
    assert ok, reasons


DEFECTS = (
    ("unbalanced RET", lambda t: mutate(t, "service_return", ret_sp=0xC0CA), "return SP != entry SP"),
    ("party changed", lambda t: mutate(t, "final", party_sum="deadbeef"), "party/OT/nickname checksum changed"),
    ("lease open", open_lease, "lease not closed"),
    ("no endtext", lambda t: missing(t, "endtext"), "endtext: expected exactly once"),
    ("false success", done_zero, "DONE result 0"),
    ("generation early", generation_early, "ROM generation written before payload"),
    ("no movement", lambda t: mutate(t, "move_end", y=3), "player did not move"),
    ("VBlank leaked", lambda t: mutate(t, "final", vblank=1), "final vblank != 0"),
    ("link mode leaked", lambda t: mutate(t, "final", link=1), "final link != 0"),
    ("observation overflow", lambda t: rekind(t, "move_start", "gsb_overflow"), "gsb_overflow"),
    ("early exit", lambda t: missing(t, "complete"), "complete: expected exactly once"),
)


@pytest.mark.parametrize("case", P.CASES)
@pytest.mark.parametrize("_label,defect,reason", DEFECTS, ids=[d[0] for d in DEFECTS])
def test_each_single_defect_fails_for_its_own_reason(case, _label, defect, reason):
    ok, reasons = P.evaluate(case, defect(good_trace(case)))
    assert not ok
    assert any(reason in failure for failure in reasons), reasons


@pytest.mark.parametrize("case", [c for c in P.CASES if c != "query-timeout"])
def test_host_cannot_answer_rom_owned_frame(case):
    trace = good_trace(case)
    begin = next(e for e in trace if e["kind"] == "host_begin")
    begin["lease"][7] = begin["lease"][6]  # already ACKed: ROM owns next native action
    ok, reasons = P.evaluate(case, trace)
    assert not ok
    assert any("host wrote while ROM-owned" in r for r in reasons)


def test_timeout_host_cannot_write_unsolicited():
    trace = good_trace("query-timeout")
    e = copy.deepcopy(trace[-1])
    e.update(kind="host_begin", tx="query")
    trace.append(e)
    ok, reasons = P.evaluate("query-timeout", renumber(trace))
    assert not ok
    assert any("host wrote while ROM-owned" in r for r in reasons)


@pytest.mark.parametrize("case", P.CASES)
def test_missing_symbol_fails_closed(case):
    trace = rekind(good_trace(case), "move_start", "missing_symbol", symbol="SlinkTradeEntry")
    ok, reasons = P.evaluate(case, trace)
    assert not ok
    assert any("missing_symbol" in r for r in reasons)


def test_offer_reject_must_not_publish_done():
    trace = good_trace("offer-reject")
    e = copy.deepcopy(next(e for e in trace if e["kind"] == "close"))
    e.update(kind="rom_write", offset=7, value=2)
    e["lease"] = P.MAGIC + [7, 2, 2, 1, 0, 1, 1] + P.TOKEN
    e["before"] = e["lease"].copy()
    e["before"][7] = 1
    i = next(i for i, event in enumerate(trace) if event["kind"] == "close")
    trace.insert(i, e)
    ok, reasons = P.evaluate("offer-reject", renumber(trace))
    assert not ok
    assert any("ROM publication order" in r and "done" in r for r in reasons)


@pytest.mark.parametrize("case", ["no-eligible", "query-timeout"])
def test_ineligible_or_unanswered_query_must_not_open_menu(case):
    trace = good_trace(case)
    e = copy.deepcopy(next(e for e in trace if e["kind"] == "close"))
    e["kind"] = "party_menu"
    trace.insert(next(i for i, event in enumerate(trace) if event["kind"] == "close"), e)
    ok, reasons = P.evaluate(case, renumber(trace))
    assert not ok
    assert any("party menu: expected 0" in r for r in reasons)


def test_query_timeout_must_not_close_early():
    trace = good_trace("query-timeout")
    query_frame = next(e["frame"] for e in trace if e["kind"] == "rom_write" and e["offset"] == 6)
    for e in trace:
        if e["frame"] > query_frame:
            e["frame"] -= 100
    ok, reasons = P.evaluate("query-timeout", trace)
    assert not ok
    assert any("QUERY timeout did not wait 600" in r for r in reasons)


@pytest.mark.parametrize("case", ["apply-done1", "apply-invalid"])
def test_apply_staging_must_not_touch_snapshot_slot(case):
    trace = good_trace(case)
    e = next(e for e in trace if e["kind"] == "host_stage_write" and e["symbol"] == "wOTPartyMon1")
    e["offset"] = 48
    ok, reasons = P.evaluate(case, trace)
    assert not ok
    assert any("staging escaped OT slot 0" in r for r in reasons)


def test_apply_requires_validated_decline_result_not_uncertain():
    trace = good_trace("apply-done1")
    for e in trace:
        if e["lease"][5] == 7:
            e["lease"][8] = 2
    ok, reasons = P.evaluate("apply-done1", trace)
    assert not ok
    assert any("APPLY must publish matching DONE result 1" in r for r in reasons)


def test_apply_invalid_must_really_have_no_name_terminator():
    trace = good_trace("apply-invalid")
    staged = next(e for e in trace if e["kind"] == "staged")
    staged["nick"] = bytes([0x80] * 10 + [0x53]).hex()
    ok, reasons = P.evaluate("apply-invalid", trace)
    assert not ok
    assert any("incoming name still has a terminator" in r for r in reasons)


@pytest.mark.parametrize("trace", [None, [], [{}], ["not an event"]])
def test_malformed_trace_is_not_evidence(trace):
    assert not P.evaluate("offer-reject", trace)[0]


@pytest.mark.parametrize("argv", [[], ["--case", "unknown"], ["--case", "offer-reject", "--timeout", "0"],
                                  ["--case", "offer-reject", "--timeout", "-5"],
                                  ["--case", "offer-reject", "--timeout", "NaN"]])
def test_invalid_runner_arguments_fail(argv):
    with pytest.raises(SystemExit):
        P.parse_args(argv)


def provenance(tmp_path, base="1" * 40, output="2" * 40):
    path = tmp_path / "data/polished/overlay_provenance.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"base_sha1": base, "output": {"sha1": output}}), encoding="utf-8")
    return path


def test_plan_reads_current_provenance_not_a_pinned_digest(tmp_path):
    path = provenance(tmp_path)
    args = P.parse_args(["--case", "apply-done1", "--timeout", "12", "--dry-run"])
    first = P.plan(args, repo=tmp_path, work=tmp_path / "lanes")
    assert first["base_sha1"] == "1" * 40
    assert first["expected_overlay_sha1"] == "2" * 40
    path.write_text(json.dumps({"base_sha1": "a" * 40, "output": {"sha1": "b" * 40}}), encoding="utf-8")
    second = P.plan(args, repo=tmp_path, work=tmp_path / "lanes")
    assert second["expected_overlay_sha1"] == "b" * 40
    assert second["lane"] == str(tmp_path / "lanes/apply-done1")
    assert second["timeout"] == 12
    assert "no cable partner, server, SLink client" in second["disclosure"]
    assert second["cleanup"] == "harness.launch finally kills only its own EmuHawk PID"


@pytest.mark.parametrize("base,output", [(None, "2" * 40), ("1" * 40, "bad"), ("z" * 40, "2" * 40)])
def test_malformed_provenance_fails(base, output, tmp_path):
    with pytest.raises(ValueError, match="provenance"):
        P.read_provenance(provenance(tmp_path, base, output))


def test_dry_run_has_no_staging_or_emulator_side_effects(tmp_path, monkeypatch, capsys):
    provenance(tmp_path)
    original = P.plan
    monkeypatch.setattr(P, "plan", lambda args: original(args, repo=tmp_path, work=tmp_path / "lanes"))
    assert P.main(["--case", "query-timeout", "--dry-run"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["service_budget_frames"] == 700
    assert printed["expected_overlay_sha1"] == "2" * 40
    assert not (tmp_path / "lanes").exists()


def test_symbols_keep_missing_optional_service_hooks_absent(tmp_path):
    path = tmp_path / "probe.sym"
    path.write_text("7e:4480 SlinkTradeEntry\n01:d28b wOTPartyMon1\n; ignored\n", encoding="utf-8")
    assert P.read_symbols(path) == {"SlinkTradeEntry": [0x7E, 0x4480], "wOTPartyMon1": [1, 0xD28B]}


def test_lua55_loads_driver_without_running_it():
    from lupa.lua55 import LuaRuntime

    lua = LuaRuntime(unpack_returned_tuples=True)
    compile_only = lua.eval("function(source) local f, why = load(source, '@trade_service_probe.lua'); return f ~= nil, why end")
    ok, why = compile_only((ROOT / "tools/polished_live/trade_service_probe.lua").read_text(encoding="utf-8"))
    assert ok, why


@pytest.mark.parametrize("field,value", [
    ("total", 2), ("qualified", 2), ("wrong_pc", 1), ("wrong_banks", {"9": 1}),
    ("wrong_bank_samples", 1), ("total", True),
])
def test_missing_or_overstated_hook_counter_fails(field, value):
    trace = good_trace("cancel-menu")
    for e in trace:
        if e["kind"] in ("final", "complete"):
            e["hook_counts"]["SlinkTradeEntry"][field] = value
    assert not P.evaluate("cancel-menu", trace)[0]
    for e in trace:
        if e["kind"] in ("final", "complete"):
            del e["hook_counts"]["SlinkTradeEntry"][field]
    assert not P.evaluate("cancel-menu", trace)[0]


def test_hook_sites_checked_against_symbols_and_observed_continuation():
    trace = good_trace("cancel-menu")
    symbols = {name: [site["bank"], site["addr"]] for name, site in SITES.items()}
    assert P.evaluate("cancel-menu", trace, symbols)[0]
    symbols["GetScriptByte"][1] += 1
    assert not P.evaluate("cancel-menu", trace, symbols)[0]
    for e in trace:
        if e["kind"] in ("final", "complete"):
            e["hook_sites"]["service_return"]["addr"] += 1
    assert not P.evaluate("cancel-menu", trace)[0]


def test_bad_pc_sample_does_not_satisfy_native_lifecycle():
    trace = good_trace("cancel-menu")
    entry = next(e for e in trace if e["kind"] == "service_entry")
    entry.update(kind="wrong_pc", pc=entry["pc"] + 1, qualified=False)
    attach_accounting(trace)
    ok, reasons = P.evaluate("cancel-menu", trace)
    assert not ok
    assert any("service_entry: expected exactly once" in reason for reason in reasons)
    assert any("wrong_pc" in reason for reason in reasons)


def mock_driver(encoder="good", case="cancel-menu", rom0=False):
    """Run the actual driver in a paused Lua coroutine; invoke its registered CPU callbacks."""
    from lupa.lua55 import LuaRuntime

    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().mock_case = case
    lua.execute(r'''
        callbacks, frame_end, writes, exited = {}, nil, {}, false
        current_bank, current_pc, current_sp, current_frame = 0x7e, 0x4480, 0xc0ce, 100
        captured_trace = nil
        script_bank, script_pos = 0, 0
        local names = {
            "SlinkTradeEntry", "SlinkTradeClose", "SlinkTradeCheckHeader", "Script_endtext",
            "GetScriptByte", "SelectTradeOrDayCareMon", "YesNoBox", "NoYesBox",
            "Special_TryQuickSave", "SlinkTradeTimeoutGate", "OWPlayerInput",
            "SetInitialOptions.joypad_loop", "wSlinkMailbox", "hVBlank", "hScriptBank",
            "hScriptPos", "hMapEntryMethod"
        }
        L = {SYM={}, hits={}, hit={}, ids={}, RUN="mock", failures=0, json={}}
        for i, name in ipairs(names) do L.SYM[name] = {0x7e, 0x4500 + i * 16} end
        L.SYM.SlinkTradeEntry = {0x7e, 0x4480}
        L.SYM.GetScriptByte = {0x25, 0x4100}
        L.rombank = function() return current_bank end
        L.bus = function(a)
            if a == current_sp then return 0x80 end
            if a == current_sp + 1 then return 0x46 end
            if a == L.SYM.hScriptBank[2] then return script_bank end
            if a == L.SYM.hScriptPos[2] then return script_pos & 0xff end
            if a == L.SYM.hScriptPos[2] + 1 then return script_pos >> 8 end
            return 0
        end
        L.rw = function(name)
            if name == "wMapWidth" then return 8 end
            if name == "wMapHeight" then return 4 end
            if name == "wXCoord" then return 5 end
            if name == "wYCoord" then return 3 end
            return 0
        end
        L.wbytes = function(_, _, n) local t = {} for i = 1, n do t[i] = 0 end return t end
        L.ww, L.log, L.idle = function() end, function() end, function() end
        L.to_overworld, L.ow_idle = function() return true end, function() return true end
        L.check = function(_, ok) if not ok then L.failures = L.failures + 1 end end
        L.finish = function() exited = true error("mock-finished", 0) end
        L.frame = function() coroutine.yield("frame") end
        L.pulse = L.frame
        client = {speedmode=function() end}
        emu = {framecount=function() return current_frame end,
               getregister=function(name)
                   if name == "PC" then return current_pc end
                   if name == "SP" then return current_sp end
               end}
        event = {
            on_bus_exec=function(fn, _, name) callbacks[name:sub(5)] = fn return name end,
            on_bus_write=function() end,
            onframeend=function(fn) frame_end = fn end
        }
        memory = {write_u8=function() end}
        os.getenv = function(name)
            if name == "SLINK_ROOT" then return "mock-root" end
            if name == "POL_CASE" then return mock_case end
            if name == "POL_FRAME_CAP" then return "12000" end
        end
        local lease = {OFF_LEASE=0, LEASE_SIZE=16, new=function() return {} end}
        dofile = function(path) if path:find("pol_lib", 1, true) then return L else return lease end end
        io.open = function()
            return {write=function(_, text) assert(type(text) == "string") writes[#writes+1] = text end,
                    close=function() end}
        end
        L.json.encode = function(trace)
            captured_trace = trace
            return primary_encode(trace)
        end
    ''')
    def convert(value):
        from lupa.lua55 import lua_type

        if lua_type(value) != "table":
            return value
        keys = list(value.keys())
        if keys and all(type(k) is int for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
            return [convert(value[i]) for i in range(1, len(keys) + 1)]
        return {str(k): convert(value[k]) for k in keys}

    if encoder == "good":
        lua.globals().primary_encode = lambda trace: json.dumps(convert(trace))
    elif encoder == "nil":
        lua.execute("primary_encode = function() return nil, 'encoder unavailable' end")
    else:
        lua.execute('primary_encode = function() error(\'bad "encoder"\\nthrow\') end')
    if rom0:
        lua.execute("L.SYM.OWPlayerInput = {0, 0x1234}")
    source = (ROOT / "tools/polished_live/trade_service_probe.lua").read_text(encoding="utf-8")
    lua.globals().driver_source = source
    lua.execute('thread = coroutine.create(assert(load(driver_source, "@trade_service_probe.lua")))')
    assert lua.eval("coroutine.resume(thread)") == (True, "frame")
    return lua, convert


def fire(lua, name, bank=None, pc=None):
    site = lua.globals().L.SYM[name]
    lua.globals().current_bank = site[1] if bank is None else bank
    lua.globals().current_pc = site[2] if pc is None else pc
    lua.globals().callbacks[name]()


def stop_driver(lua):
    lua.globals().current_frame = 12001
    lua.execute("stop_ok, stop_reason = pcall(frame_end)")
    assert lua.globals().exited
    assert not lua.globals().stop_ok
    return json.loads(lua.globals().writes[1])


def test_actual_lua_bounds_wrong_bank_samples_per_site_and_keeps_qualified_evidence():
    from tools.polished_live.faint_probe import validate_hook_counts

    lua, _ = mock_driver()
    for name in ("GetScriptByte", "SlinkTradeEntry"):
        for i in range(7001):
            fire(lua, name, bank=8 + i % 2)
        fire(lua, name)
    # The native entry installed its dynamic continuation; it gets the same bounded accounting.
    for i in range(7001):
        lua.globals().current_bank = 8 + i % 2
        lua.globals().current_pc = 0x4680
        lua.globals().callbacks.service_return()
    lua.globals().current_bank = 0x7E
    lua.globals().current_pc = 0x4680
    lua.globals().callbacks.service_return()
    trace = stop_driver(lua)
    final = next(e for e in trace if e["kind"] == "final")
    for name, kind in (("GetScriptByte", "gsb"), ("SlinkTradeEntry", "service_entry"),
                       ("service_return", "service_return")):
        counts = final["hook_counts"][name]
        assert counts == {"total": 7002, "qualified": 1, "wrong_pc": 0,
                          "wrong_banks": {"8": 3501, "9": 3500}, "wrong_bank_samples": 16}
        assert sum(e.get("hook_site") == name and e["kind"] == "wrong_bank" for e in trace) == 16
        rows = [e for e in trace if e["kind"] == kind]
        assert len(rows) == 1 and rows[0]["qualified"] is True
        assert "party_sum" in rows[0] and len(rows[0]["lease"]) == 16
    assert not validate_hook_counts(trace, final, final["hook_sites"])


@pytest.mark.parametrize("encoder", ["nil", "throw"])
def test_actual_lua_encoder_failure_writes_readable_minimal_trace_and_finishes(encoder):
    lua, _ = mock_driver(encoder)
    for _ in range(7001):
        fire(lua, "GetScriptByte", bank=9)
    fire(lua, "GetScriptByte")
    trace = stop_driver(lua)
    assert trace[0]["kind"] == "driver_error"
    final = trace[-1]
    assert final["kind"] == "final" and final["completed"] is False
    assert final["driver_errors"] == 2  # deadline + serializer failure
    assert final["hook_counts"]["GetScriptByte"]["total"] == 7002
    assert final["hook_counts"]["GetScriptByte"]["wrong_bank_samples"] == 16
    assert not P.evaluate("cancel-menu", trace)[0]


def test_actual_lua_wrong_pc_never_enters_native_service():
    lua, _ = mock_driver()
    fire(lua, "SlinkTradeEntry", pc=0x4481)
    assert lua.globals().callbacks.service_return is None
    trace = stop_driver(lua)
    row = next(e for e in trace if e["kind"] == "wrong_pc")
    assert row["matched"] is True and row["qualified"] is False
    assert "party_sum" in row and not any(e["kind"] == "service_entry" for e in trace)


def test_actual_lua_wrong_bank_does_not_consume_gsb_protected_capacity():
    lua, _ = mock_driver()
    for _ in range(7001):
        fire(lua, "GetScriptByte", bank=9)
    for _ in range(4000):
        fire(lua, "GetScriptByte")
    fire(lua, "GetScriptByte", pc=0x4101)
    trace = stop_driver(lua)
    assert sum(e["kind"] == "gsb" for e in trace) == 4000
    assert sum(e["kind"] == "gsb_overflow" for e in trace) == 1
    final = next(e for e in trace if e["kind"] == "final")
    assert final["hook_counts"]["GetScriptByte"]["wrong_pc"] == 1
    assert final["completed"] is False


@pytest.mark.parametrize("case", P.CASES)
def test_compressed_wrong_bank_claims_keep_native_and_byte_staging_proof(case):
    trace = good_trace(case)
    samples = []
    for name, site in SITES.items():
        for _ in range(16):
            e = copy.deepcopy(trace[0])
            e.update(kind="wrong_bank", hook_site=name, hook_addr=site["addr"], pc=site["addr"],
                     bank=9, matched=False, qualified=False)
            samples.append(e)
        for e in trace:
            if e["kind"] in ("final", "complete"):
                counts = e["hook_counts"][name]
                counts["total"] += 7001
                counts["wrong_banks"] = {"9": 7001}
                counts["wrong_bank_samples"] = 16
    trace[1:1] = samples
    renumber(trace)
    ok, reasons = P.evaluate(case, trace)
    assert ok, reasons


def test_actual_lua_rom0_matches_any_bank_shadow_but_still_checks_pc():
    lua, _ = mock_driver(rom0=True)
    fire(lua, "OWPlayerInput", bank=9)
    fire(lua, "OWPlayerInput", bank=8, pc=0x1235)
    trace = stop_driver(lua)
    final = next(e for e in trace if e["kind"] == "final")
    assert final["hook_counts"]["OWPlayerInput"] == {
        "total": 2, "qualified": 1, "wrong_pc": 1, "wrong_banks": {}, "wrong_bank_samples": 0,
    }
    assert sum(e["kind"] == "OWPlayerInput" for e in trace) == 1
    assert sum(e["kind"] == "wrong_pc" for e in trace) == 1


@pytest.mark.parametrize("encoder", ["nil", "throw"])
def test_actual_lua_completed_dump_encoder_failure_also_finishes(encoder):
    lua, _ = mock_driver(encoder, case="query-timeout")
    fire(lua, "YesNoBox")
    fire(lua, "YesNoBox")
    fire(lua, "Special_TryQuickSave")
    lua.globals().script_bank = 0x24
    lua.globals().script_pos = 0x7616
    fire(lua, "GetScriptByte")
    fire(lua, "SlinkTradeEntry")
    lua.globals().current_bank = 0x7E
    lua.globals().current_pc = 0x4680
    lua.globals().callbacks.service_return()
    for _ in range(100):
        lua.eval("coroutine.resume(thread)")
        if lua.globals().exited:
            break
    assert lua.globals().exited
    trace = json.loads(lua.globals().writes[1])
    final = trace[-1]
    assert final["completed"] is False and final["driver_errors"] == 1
    assert final["hook_counts"]["SlinkTradeEntry"]["qualified"] == 1
    assert final["hook_counts"]["service_return"]["qualified"] == 1
    assert trace[0]["kind"] == "driver_error"
    assert not P.evaluate("query-timeout", trace)[0]


def test_actual_lua_gsb_bad_pc_keeps_full_diagnostics_and_consumes_capacity():
    lua, _ = mock_driver()
    fire(lua, "GetScriptByte", pc=0x4101)
    for _ in range(3999):
        fire(lua, "GetScriptByte")
    fire(lua, "GetScriptByte")
    trace = stop_driver(lua)
    wrong = [e for e in trace if e["kind"] == "wrong_pc"]
    assert len(wrong) == 1 and wrong[0]["hook_site"] == "GetScriptByte"
    assert wrong[0]["matched"] is True and wrong[0]["qualified"] is False
    assert "party_sum" in wrong[0] and len(wrong[0]["lease"]) == 16
    assert sum(e["kind"] == "gsb" for e in trace) == 3999
    assert sum(e["kind"] == "gsb_overflow" for e in trace) == 1


def test_actual_lua_callback_snapshot_failure_records_driver_error_and_finishes():
    lua, _ = mock_driver()
    lua.execute('L.wbytes = function() error("unreadable snapshot") end')
    lua.execute('callback_ok, callback_reason = pcall(callbacks.SlinkTradeEntry)')
    assert lua.globals().exited and not lua.globals().callback_ok
    trace = json.loads(lua.globals().writes[1])
    assert any(e["kind"] == "driver_error" for e in trace)
    final = next(e for e in trace if e["kind"] == "final")
    assert final["completed"] is False and final["driver_errors"] == 2
    assert final["hook_counts"]["SlinkTradeEntry"]["total"] == 1
    assert not P.evaluate("cancel-menu", trace)[0]
