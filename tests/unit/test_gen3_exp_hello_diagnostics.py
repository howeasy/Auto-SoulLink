"""Log-only HELLO observations preserve the production call path and timeout verdict."""
import json
import re
from pathlib import Path

import lupa
import pytest

from tools import e2e_duo

ROOT = Path(__file__).resolve().parents[2]


def _watch_model(*, setup="", log_failure=False, journal=None, arm=True):
    source = (ROOT / "lua/tests/duo/duo_gen3_main.lua").read_text()
    start = re.search(r"local function install_hello_watch\(", source)
    assert start, "HELLO diagnostics installer absent"
    end = re.search(r"^end$", source[start.start():], re.M)
    body = source[start.start():start.start() + end.end()]
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute('''
        calls={live=0,ready=0,snapshot=0,check=0,extra=0}; logs={}; mode=false
        safety={last_clauses={"cpu"}}
        policy={snapshot=function(self)
            calls.snapshot=calls.snapshot+1;return {gSaveBlock1Ptr=0x02025000},"snapshot reason"
        end,check=function(self,snap,reason,args)
            assert(reason=="overworld" and snap.gSaveBlock1Ptr==0x02025000)
            calls.check=calls.check+1;return mode,"CPU outside parked checkpoint"
        end}
        drv={game_is_live=function(arg)
            calls.live=calls.live+1;return true,"live reason",arg
        end,hello_ready=function(arg)
            calls.ready=calls.ready+1
            drv.game_is_live(arg)
            local snap=policy:snapshot()
            local ok,why=policy:check(snap,"overworld")
            return ok,why,arg
        end}
        session={driver=drv,state={frozen=false,baselined=true},hello_sent=false,hello_visible=false}
        parts={policy=policy,safety=safety}
        extras=function()calls.extra=calls.extra+1;return {in_battle=false,location={map_group=0,map_num=26}}end
        emit=function(doc)logs[#logs+1]=doc end
    ''')
    lua.execute(setup)
    if log_failure:
        lua.execute('emit=function()error("diagnostic sink failed")end')
    install = lua.execute(body + "\nreturn install_hello_watch")
    watch = install(lua.globals().session, lua.globals().parts, lua.table_from(journal) if journal is not None else None,
                    lua.globals().extras, lua.globals().emit, 2)
    if arm:
        watch.arm(0)
        lua.execute("logs={}")  # Other tests inspect post-arm gate observations.
    return lua, watch


def test_preboot_calls_are_cached_and_arming_starts_a_fresh_bounded_window():
    lua, watch = _watch_model(arm=False)
    for index in range(12):
        lua.globals().mode = bool(index % 2)
        lua.globals().drv.hello_ready("preboot")
    assert len(lua.globals().logs) == 0
    watch.arm(500)
    doc = lua.globals().logs[1]
    assert doc.phase == "await-start" and doc.samples == 0 and doc.hello_ready is True
    assert doc.start_frame == doc.sample_frame == 500
    assert doc.hello_sent is doc.hello_visible is False
    for name in ("live", "ready", "snapshot", "check"):
        assert lua.globals().calls[name] == 12
    for _ in range(3):
        lua.globals().drv.hello_ready("postboot")
    assert len(lua.globals().logs) == 3  # cached start plus the first two post-arm checks
    assert watch.count == 3 and watch.changes == 0


def test_real_await_predicate_samples_after_300_frames_not_300_iterations():
    lua, watch = _watch_model(arm=False)
    lua.globals().drv.hello_ready("cached refusal")
    watch.arm(1000)
    lua.globals().hello_watch = watch
    lua.execute('''
        seen_tx={}; hello_wait_iterations=0; frame=1000; frame_reads=0; advances=0
        emu={framecount=function()frame_reads=frame_reads+1;return frame end,
             frameadvance=function()advances=advances+1 end}
    ''')
    source = (ROOT / "lua/tests/duo/duo_gen3_main.lua").read_text()
    boot = source.index('log(fmt("booted frame=')
    match = re.search(r'if not ctx\.wait_until\((function\(\).*?\nend), 120, "the client\'s hello"', source[boot:], re.S)
    assert match, "bounded post-boot HELLO wait predicate absent"
    predicate = lua.execute("return " + match[1])
    for _ in range(1000):
        assert predicate() is None
    assert len(lua.globals().logs) == 1
    lua.globals().frame = 1299
    assert predicate() is None and len(lua.globals().logs) == 1
    lua.globals().frame = 1300
    assert predicate() is None
    assert len(lua.globals().logs) == 2 and lua.globals().logs[2].phase == "await-300"
    assert lua.globals().logs[2].sample_frame == 1300
    lua.globals().frame = 1400
    for _ in range(600):
        predicate()
    assert len(lua.globals().logs) == 2
    for name in ("live", "ready", "snapshot", "check"):
        assert lua.globals().calls[name] == 1
    assert lua.globals().advances == 0


def test_installer_is_expansion_only_and_armed_after_boot_before_the_wait():
    source = (ROOT / "lua/tests/duo/duo_gen3_main.lua").read_text()
    assert re.search(r'if D\.game == "gen3_exp" then\n    local raw_structs = [^\n]+\n    hello_watch = install_hello_watch\(', source)
    boot = source.index('log(fmt("booted frame=')
    arm = source.index("if hello_watch then hello_watch.arm(emu.framecount()) end")
    wait = source.index("if not ctx.wait_until(function()", boot)
    assert boot < arm < wait


def _lua_value(lua, value):
    if isinstance(value, dict):
        return lua.table_from({key: _lua_value(lua, item) for key, item in value.items()})
    if isinstance(value, list):
        return lua.table_from([_lua_value(lua, item) for item in value])
    return value


def _raw_model():
    source = (ROOT / "lua/tests/duo/duo_gen3_main.lua").read_text()
    start = source.index("local function hello_raw_snapshot(")
    end = re.search(r"^end$", source[start:], re.M)
    body = source[start:start + end.end()]
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    raw = lua.execute(body + "\nreturn hello_raw_snapshot")
    facts = json.loads((ROOT / "data/games/gen3_exp/28877d73/facts.json").read_text())["structs"]
    structs = {name: facts[name] for name in ("Main", "Task", "PaletteFadeControl")}
    symbols = {"by_name": {"gMain": {"address": 100, "size": structs["Main"]["size"]},
                            "gTasks": {"address": 200, "size": 2 * structs["Task"]["size"]},
                            "gPaletteFade": {"address": 500, "size": structs["PaletteFadeControl"]["size"]},
                            "sGlobalScriptContextStatus": {"address": 600, "size": 1},
                            "sLockFieldControls": {"address": 601, "size": 1}},
               "by_address": {0x08000100: ["CB2_Test"], 0x08000200: ["Task_Fishing"]}}
    return lua, raw, body, _lua_value(lua, symbols), _lua_value(lua, structs)


def test_raw_words_resolve_exact_symbols_without_zero_or_mirror_guesses():
    lua, raw, _, symbols, structs = _raw_model()
    bytes_ = {204: 1, 244: 1, 515: 0x80, 600: 2, 601: 0}
    words = {100: 0, 104: 0x0A000101, 200: 0x08000201, 240: 0x08000100}
    got = raw(lambda a: bytes_.get(a, 0), lambda a: 65535 if a == 208 else 2,
              lambda a: words.get(a, 0), symbols, structs)
    assert got.callback1.raw == 0 and got.callback1.match == "zero" and len(got.callback1.names) == 0
    assert got.callback2.raw == 0x0A000101 and got.callback2.match == "unresolved"
    assert len(got.callback2.names) == 0  # never translate an unproved bank mirror
    assert got.tasks[1].func.raw == 0x08000201 and got.tasks[1].func.names[1] == "Task_Fishing"
    assert got.tasks[1].func.match == "thumb-bit-stripped" and got.tasks[1].tStep == -1
    assert got.tasks[1].data0_raw == 65535 and got.tasks[2].tStep is None
    assert got.sGlobalScriptContextStatus.raw == 2 and got.sLockFieldControls.raw == 0
    assert len(got.gPaletteFade.bytes) == 24 and got.gPaletteFade.active_word == 0x80
    assert got.gPaletteFade.active_mask == "0x80"


def test_raw_reads_and_two_b_screenshots_use_the_actual_bounded_sample_callback():
    lua, _, body, symbols, structs = _raw_model()
    lua.globals().hello_symbols, lua.globals().raw_structs = symbols, structs
    lua.execute('''
        D={player="b",scenario="rock"}; cp={}; seen_tx={}; shots=0
        reader={read_battle=function()return {in_battle=false}end,
                read_location=function()return {map_group=0,map_num=26}end}
        G={pos=function()return 18,102 end,shot=function()shots=shots+1;error("screenshot unavailable")end}
        memory={read_u8=function()return 0 end,read_u16_le=function()return 0 end,read_u32_le=function()return 0 end}
    ''')
    source = (ROOT / "lua/tests/duo/duo_gen3_main.lua").read_text()
    match = re.search(r'hello_watch = install_hello_watch\(session, battle_parts, hello_journal, (function\(phase\).*?)\n    end, function\(doc\)', source, re.S)
    assert match
    extra = lua.execute(body + "\nreturn " + match[1] + "\nend")
    assert extra("await-start").map_x == 18 and lua.globals().shots == 1
    lua.globals().D.player = "a"
    extra("await-300")
    assert lua.globals().shots == 1
    lua.globals().D.player = "b"
    doc = extra("await-300")
    assert doc.map_y == 102 and lua.globals().shots == 2
    lua.globals().seen_tx.hello = 1
    extra("await-300")
    assert lua.globals().shots == 2


def test_watch_captures_actual_results_without_extra_gate_calls():
    lua, watch = _watch_model()
    assert lua.globals().drv.hello_ready("kept") == (False, "CPU outside parked checkpoint", "kept")
    for name in ("live", "ready", "snapshot", "check"):
        assert lua.globals().calls[name] == 1
    doc = lua.globals().logs[1]
    assert doc.hello_ready is False and doc.game_is_live is True
    assert doc.policy_ok is False and doc.policy_why == "CPU outside parked checkpoint"
    assert doc.snapshot.gSaveBlock1Ptr == 0x02025000 and doc.refusal_clauses[1] == "cpu"
    assert doc.frozen is False and doc.baselined is True
    assert doc.party_hidden == doc.journal_busy == doc.journal_failure == "unavailable"
    watch.timeout()
    assert lua.globals().logs[2].phase == "timeout"
    for name in ("live", "ready", "snapshot", "check"):
        assert lua.globals().calls[name] == 1


def test_watch_logging_is_bounded_and_reports_verdict_changes():
    lua, watch = _watch_model()
    for _ in range(10):
        lua.globals().drv.hello_ready("same")
    assert len(lua.globals().logs) == 2
    lua.globals().mode = True
    lua.globals().drv.hello_ready("changed")
    assert len(lua.globals().logs) == 3 and lua.globals().logs[3].phase == "change"
    for index in range(20):
        lua.globals().mode = bool(index % 2)
        lua.globals().drv.hello_ready("bounded")
    assert len(lua.globals().logs) == 4  # first N plus at most N changed verdicts
    watch.timeout()
    assert len(lua.globals().logs) == 5


def test_timeout_before_any_hello_call_reports_unavailable_without_sampling_gates():
    lua, watch = _watch_model()
    watch.timeout()
    doc = lua.globals().logs[1]
    assert doc.samples == 0 and doc.phase == "timeout"
    assert doc.hello_ready == doc.game_is_live == doc.policy_ok == doc.snapshot == "unavailable"
    assert doc.hello_why == doc.live_why == "not called"
    for name in ("live", "ready", "snapshot", "check"):
        assert lua.globals().calls[name] == 0


def test_watch_preserves_original_exceptions_and_ignores_log_failures():
    lua, _ = _watch_model(log_failure=True)
    assert lua.globals().drv.hello_ready("kept") == (False, "CPU outside parked checkpoint", "kept")
    assert lua.globals().calls.ready == lua.globals().calls.live == 1
    lua.execute('drv.game_is_live=function()error("production gate raised")end')
    with pytest.raises(lupa.LuaError, match="production gate raised"):
        lua.globals().drv.hello_ready("kept")


def test_exposed_false_flags_are_not_replaced_by_unavailable():
    lua, _ = _watch_model(journal={"busy": False, "failure": False}, setup='''
        extras=function()return {party_hidden=false,in_battle=false,wire_event="tick",wire_seq=7}end
    ''')
    lua.globals().drv.hello_ready("kept")
    doc = lua.globals().logs[1]
    assert doc.journal_busy is doc.journal_failure is doc.party_hidden is False
    assert doc.wire_event == "tick" and doc.wire_seq == 7


def test_unreached_policy_is_unavailable_and_nil_return_arity_is_preserved():
    lua, watch = _watch_model(setup='''
        drv.game_is_live=function()calls.live=calls.live+1;return nil,"party unreadable",nil end
        drv.hello_ready=function()calls.ready=calls.ready+1;return drv.game_is_live()end
    ''')
    result = lua.eval('table.pack(drv.hello_ready())')
    assert result.n == 3 and result[1] is None and result[2] == "party unreadable" and result[3] is None
    doc = lua.globals().logs[1]
    assert doc.policy_ok == doc.snapshot == "unavailable"
    assert lua.globals().calls.snapshot == lua.globals().calls.check == 0
    watch.timeout()
    assert lua.globals().calls.live == lua.globals().calls.ready == 1


def test_wait_connected_timeout_logs_cached_actual_players_and_reraises(capsys):
    run = e2e_duo.DuoRun.__new__(e2e_duo.DuoRun)
    observed = {"players": {"a": {"connected": True, "last_event": "tick"},
                            "b": {"connected": False, "last_event": "hello"}}}
    status_calls = []
    run._status = lambda: status_calls.append(True) or observed
    failure = TimeoutError("original connection timeout")
    def wait(desc, predicate, timeout):
        assert desc == "both players hello'd" and timeout == 120
        assert predicate() is None
        raise failure
    run.wait_for = wait
    with pytest.raises(TimeoutError) as raised:
        run.wait_connected()
    assert raised.value is failure and len(status_calls) == 1
    line = next(line for line in capsys.readouterr().out.splitlines() if "CONNECT_TIMEOUT " in line)
    actual = json.loads(line.split("CONNECT_TIMEOUT ", 1)[1])
    assert actual == observed


def test_wait_connected_success_retains_the_original_path(capsys):
    run = e2e_duo.DuoRun.__new__(e2e_duo.DuoRun)
    run._status = lambda: {"players": {"a": {"connected": True}, "b": {"connected": True}}}
    run.wait_for = lambda desc, predicate, timeout: predicate()
    run.wait_connected()
    assert capsys.readouterr().out == "[duo] both players connected\n"


def test_expansion_helper_screenshots_are_distinct_for_rows_and_players():
    from lupa import LuaRuntime
    source = (ROOT / "lua/tests/duo/duo_gen3_main.lua").read_text()
    body = re.search(r"(?ms)^local function namespace_shots\(module, scenario, player\).*?^end$", source).group()
    lua = LuaRuntime(unpack_returned_tuples=True)
    namespace = lua.execute(body + "\nreturn namespace_shots")
    seen = []
    for row, player in (("fish", "a"), ("fish", "b"), ("rock", "a")):
        module = lua.table_from({"shot": seen.append})
        namespace(module, row, player).shot("stuck")
    assert seen == ["fish_a_stuck", "fish_b_stuck", "rock_a_stuck"]
    module = lua.table_from({"shot": seen.append})
    namespace(module, "fish", "b").shot("fish_b_hello_stuck")
    assert seen[-1] == "fish_b_hello_stuck"
    assert 'if D.game=="gen3_exp" then\n    dofile=function(path)' in source
