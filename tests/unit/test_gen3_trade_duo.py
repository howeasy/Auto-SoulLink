"""T5 carrier controls. No emulator is started by these tests."""

import copy
import hashlib
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from lupa import lua54

from tools import gen3_trade_duo as t5

ROOT = Path(__file__).resolve().parents[2]


def test_t5_server_gets_a_real_unique_run_identity_without_an_admission_override():
    from tools.e2e_duo import SCENARIOS, DuoRun

    run = DuoRun.__new__(DuoRun)
    run.cfg = SCENARIOS["native_trade_firered"]
    run.args = SimpleNamespace(server_flags=[], wire_log=False)
    run.tcp_port, run.http_port, run.data_dir = 1, 2, "MODEL-data"
    run._native_candidate = {"nonce": "ab" * 16}
    command = run.server_cmd()
    assert command[command.index("--run-id") + 1] == "t5-" + "ab" * 16
    assert t5.ENV not in " ".join(command)


def test_t5_rows_require_the_explicit_private_game_and_mandatory_oracles():
    from tools.e2e_duo import GAMES, SCENARIOS, evidence_contract, scenario_applies, scenarios_for

    names = ["native_trade_firered", "native_trade_decline_firered"]
    assert scenarios_for("gen3_fr_trade") == names
    assert GAMES["gen3_fr_trade"]["sides"]["b"][0] == "leafgreen"
    assert GAMES["gen3_lg_trade"]["sides"]["a"][0] == "leafgreen"
    assert GAMES["gen3_lg_trade"]["sides"]["b"][0] == "firered"
    assert scenarios_for("gen3_lg_trade") == names
    for name in names:
        assert SCENARIOS[name]["gen3_native_trade"]
        for normal in ("gen3_frlg", "gen3_lgfr", "gen3_rr", "gen3_emerald"):
            assert not scenario_applies(name, normal)
    contract = evidence_contract("gen3_fr_trade")
    assert contract.require_oracle and contract.witness_validator == "check_native_trade_witness"


def test_changed_private_fixture_is_refused_before_seeding(tmp_path):
    from tools.e2e_duo import DuoRun

    path = tmp_path / "private.sav"
    path.write_bytes(b"changed")
    run = DuoRun.__new__(DuoRun)
    run.cfg = {"gen3_native_trade": True}
    run._gen3_fixture_path = lambda side: str(path)
    run._native_candidate = {"fixtures": {"a": {"sha256": "00" * 32}}}
    with pytest.raises(RuntimeError, match="T5 fixture changed"):
        run._gen3_fixture_bytes("a")


def test_new_native_trade_attempt_preserves_the_previous_attempts_battery(monkeypatch, tmp_path):
    from tools import e2e_duo as duo

    monkeypatch.setattr(duo, "BUILD", str(tmp_path / "build"))
    seed = (ROOT / "tests/fixtures/gen3/firered_party_town.sav").read_bytes()
    previous = t5.codec.split_rtc(
        (ROOT / "tests/fixtures/gen3/firered_party_town_b.sav").read_bytes()
    )[0]
    runs = []
    for _ in range(2):
        run = duo.DuoRun(
            "native_trade_firered",
            SimpleNamespace(game="gen3_fr_trade", lane="same-lane", idle_jitter=0),
        )
        run._native_candidate = {"rom": "candidate.gba"}
        run._gen3_fixture_bytes = lambda _side: seed
        runs.append(run)
    old = Path(runs[0]._seed_instance_save("a"))
    old.write_bytes(previous)
    fresh = Path(runs[1]._seed_instance_save("a"))
    assert fresh != old and old.read_bytes() == previous
    assert fresh.read_bytes() == t5.codec.split_rtc(seed)[0]


def test_t5_result_gate_consumes_reload_receipts_instead_of_initial_pass(monkeypatch):
    from tools import e2e_duo as duo

    run = duo.DuoRun.__new__(duo.DuoRun)
    run.scenario = "native_trade_firered"
    run.cfg = duo.SCENARIOS[run.scenario]
    run._read_receipt = lambda side: f"cold reload {side}\nRESULT: PASS\n"
    run.wait_for = lambda desc, predicate, timeout: predicate()
    monkeypatch.setattr(duo, "read_result", lambda *args: "initial\nRESULT: PASS\n")
    assert run.wait_results() == ("cold reload a\nRESULT: PASS\n", "cold reload b\nRESULT: PASS\n")


@pytest.mark.parametrize("stale", [False, True])
def test_candidate_launch_exports_override_only_to_its_owned_emulator(monkeypatch, tmp_path, stale):
    from tests.unit.test_e2e_duo_gen3 import _gba_config
    from tools import e2e_duo as duo

    build = tmp_path / "patch/build"
    build.mkdir(parents=True)
    rom = build / "private.gba"
    rom.write_bytes(b"MODEL ROM")
    save = build / "seed.sav"
    save.write_bytes((ROOT / "tests/fixtures/gen3/firered_party_town.sav").read_bytes())
    for name, value in (
        ("REPO", str(tmp_path)),
        ("BUILD", str(build)),
        ("WT_FWD", tmp_path.as_posix()),
        ("BIZHAWK_CONFIG", str(_gba_config(tmp_path))),
    ):
        monkeypatch.setattr(duo, name, value)
    monkeypatch.delenv(t5.ENV, raising=False)
    launched = []

    def popen(argv, **kwargs):
        launched.append((argv, kwargs))
        return SimpleNamespace(pid=999)

    monkeypatch.setattr(duo.subprocess, "Popen", popen)
    verified = []

    def validate(root, manifest):
        verified.append(manifest)
        if stale:
            raise ValueError("stale T5 private pack digest")

    monkeypatch.setattr(t5, "validate_prepared", validate)
    args = SimpleNamespace(game="gen3_fr_trade", lane="t5model", idle_jitter=0)
    run = duo.DuoRun("native_trade_firered", args)
    run._native_candidate = {
        "nonce": "ab" * 16,
        "journal_path": "patch/build/private/slink_gen3_trade_" + "ab" * 16,
        "path": "patch/build/private.json",
        "manifest_sha1": "12" * 20,
        "rom": "patch/build/private.gba",
        "rom_sha1": hashlib.sha1(rom.read_bytes()).hexdigest(),
        "fixtures": {
            "a": {
                "path": "patch/build/seed.sav",
                "sha256": hashlib.sha256(save.read_bytes()).hexdigest(),
            }
        },
    }
    if stale:
        with pytest.raises(ValueError, match="stale T5"):
            run.launch_instance("a")
        assert launched == [] and not Path(run._gen3_battery_path("a")).exists()
        return
    run.launch_instance("a")
    assert launched[0][1]["env"][t5.ENV] == "ab" * 16
    assert verified == [run._native_candidate]
    assert t5.ENV not in duo.os.environ
    assert Path(run._gen3_battery_path("a")).read_bytes() == save.read_bytes()
    stub = Path(run.stub_path("a")).read_text()
    assert 'native_candidate_manifest = "patch/build/private.json"' in stub
    assert 'game = "gen3_fr_trade"' in stub


@pytest.mark.parametrize("decline", [False, True])
def test_runner_waits_for_initial_exit_then_cold_reloads_both_without_reseeding(decline):
    from tools.e2e_duo import SCENARIOS, DuoRun

    run = DuoRun.__new__(DuoRun)
    run.scenario = "native_trade_decline_firered" if decline else "native_trade_firered"
    run.cfg = SCENARIOS[run.scenario]
    run._native_initial = {}
    run._link_keys, run._phase, run._live_complete = (
        {"a": "KA", "b": "KB"},
        {"a": "initial", "b": "initial"},
        {},
    )
    calls = []
    run._gen3_prelude = lambda **kw: calls.append(("prelude", kw))
    run._gen3_mark = lambda *args: calls.append(("mark", args))
    run._gen3_linked_lines = lambda: {"a": [], "b": []}
    run.go = lambda lines: calls.append(("go", lines))
    run._append_reconnect_marker = lambda *args: calls.append(("release", args))
    run._read_receipt = lambda inst: "RESULT: PASS\n"
    run._reconnect_document = lambda: {"MODEL": "saved server state"}
    run.emu_by_inst = {
        side: SimpleNamespace(wait=lambda **kw: calls.append(("exit", kw))) for side in "ab"
    }

    def wait(desc, predicate, timeout):
        assert not run._live_complete.get(run.scenario)
        assert predicate()

    run.wait_for = wait
    run.launch_instance = lambda side, **kw: calls.append(("launch", side, kw))
    run.orchestrate_native_trade_firered()
    launches = [row for row in calls if row[0] == "launch"]
    assert launches == [
        (
            "launch",
            side,
            {
                "phase": "native_trade_reload",
                "seed": False,
                "expected_key": run._link_keys[side if decline else ("b" if side == "a" else "a")],
            },
        )
        for side in "ab"
    ]
    assert [row[0] for row in calls if row[0] in ("exit", "launch")] == [
        "exit",
        "exit",
        "launch",
        "launch",
    ]
    assert run._native_document == {"MODEL": "saved server state"}
    assert run._live_complete[run.scenario]


def test_v2_native_checkpoint_checks_real_panel_state():
    from tests.unit.test_gen3_safety import World, committed_pack

    cp = committed_pack("firered")
    for anchor in cp["anchors"].values():
        anchor["expected_hex"]["companion"] = anchor["expected_hex"]["clean"]
    base = 0x0201B000
    cp["native"] = {
        "version": "gen3-native-v2",
        "base": base,
        "sig": 0x4B4E4C53,
        "abi": 2,
        "abi_off": 4,
        "opcode_off": 6,
        "status_off": 10,
        "busy": 1,
        "info": base + 0x6E0,
        "info_state_off": 14,
        "info_drawn_off": 6,
        "info_ack_off": 12,
    }
    w = World("firered", "companion", cp)
    w.lua.globals().put(base + 0x6EE, 0, 1)
    assert w.check_reason("native")[0]
    for state in (1, 2, 255):
        w.lua.globals().put(base + 0x6EE, state, 1)
        assert not w.check_reason("native")[0]
    w.lua.globals().put(base + 0x6EE, 0, 1)
    assert w.check_reason("native")[0]


def model_manifest():
    return {
        "schema": t5.SCHEMA,
        "production": False,
        "ready": 0,
        "title": "firered", "carrier_mode": "native",
        "hooks": {"CB2_InitPartyMenu": 0x0811EBD0},
        "carrier": {"state": 0x0201BB40, "size": 380, "control": 0x0201B800,
                    "objects": 0x02036E38, "avatar": 0x02037078, "stride": 36, "local_id": 241,
                    "callback": 0x030030F4, "field_callback": 0x080565B5, "field_lock": 0x03000F9C,
                    "script_status": 0x03000EA8, "script_idle": 2, "party_cursor": 0x0203B0A9},
        "nonce": "ab" * 16,
        "journal_path": "patch/build/private/slink_gen3_trade_" + "ab" * 16,
        "rom_sha1": "cd" * 20,
        "rom_md5": "ef" * 16,
        "source_commit": "00" * 20,
        "manifest_sha1": "12" * 20,
        "source_sha1": {
            path: hashlib.sha1((ROOT / path).read_bytes()).hexdigest() for path in t5.SOURCE_FILES
        },
        "pack_sha1": {
            name: hashlib.sha1(("MODEL " + name).encode()).hexdigest()
            for name in ("profile", "sites", "checkpoint")
        },
        "pack_files": {
            n: f"patch/build/private/{n}.json" for n in ("profile", "sites", "checkpoint")
        },
    }


def model_bound_file(path):
    if path in t5.SOURCE_FILES:
        return (ROOT / path).read_bytes().decode("utf-8")
    return "MODEL " + Path(path).stem


@pytest.mark.parametrize(
    "problem", [None, "env", "production", "ready", "game", "scenario", "hash", "path", "title", "player", "carrier"]
)
def test_only_explicit_runner_context_can_authorize_candidate(problem):
    lua = lua54.LuaRuntime(unpack_returned_tuples=True)
    mod = lua.execute((ROOT / "lua/tests/duo/gen3_trade_candidate.lua").read_text())
    manifest = model_manifest()
    args = {"game": "gen3_fr_trade", "title": "firered", "player": "a", "scenario": "native_trade_firered"}
    env, digest = manifest["nonce"], manifest["rom_sha1"]
    if problem == "env":
        env = ""
    elif problem == "production":
        manifest["production"] = True
    elif problem == "ready":
        manifest["ready"] = 1
    elif problem == "game":
        args["game"] = "gen3_frlg"
    elif problem == "scenario":
        args["scenario"] = "trade_gen3"
    elif problem == "hash":
        digest = "00" * 20
    elif problem == "path":
        manifest["pack_files"]["profile"] = "patch/build/../../data/profile.json"
    elif problem == "title":
        args["title"] = "leafgreen"
    elif problem == "player":
        manifest["player"] = "b"
    elif problem == "carrier":
        manifest["carrier_mode"] = "harness_selection"

    def call():
        return mod.authorize(
            lua.table_from(manifest, recursive=True),
            lua.table_from(args),
            env,
            digest,
            model_bound_file,
            lambda raw: hashlib.sha1(raw.encode()).hexdigest(),
        )

    if problem:
        with pytest.raises(lua54.LuaError):
            call()
    else:
        assert call()


@pytest.mark.parametrize("title", ["firered", "leafgreen"])
def test_private_projection_does_not_override_the_published_cartridge_identity(monkeypatch, title):
    directory = ROOT / f"patch/build/candidate-{title}-trade"
    if not (directory / "probe.gba").exists():
        pytest.skip("T5 private FR candidate build absent")
    rom, receipt = t5.candidate_inputs(ROOT, title)
    # publication retains the tested bytes and adds only the static SoulLink title wordmark (patch/tools/gen3_title.py);
    # the payload, and so every tested behaviour, is the candidate's
    from patch.tools import gen3_title

    published = bytearray(rom)
    gen3_title.apply_title(published, title)
    manifest = json.loads((ROOT / "patch/dist/gen3_companions.json").read_text())["titles"][title]
    slot = manifest["version_slot"]                                          # plus the release stamp (tools/stamp_release.py)
    published[slot["offset"]:slot["offset"] + slot["length"]] = gen3_title.menu_field(manifest["menu_version"])
    projected = t5.private_pack(ROOT, rom, receipt)
    assert receipt["production"] is False
    assert projected["sites"]["titles"][title]["artifacts"]["companion"]["harness_only"] is True
    monkeypatch.setenv(t5.ENV, "ab" * 16)
    lua = lua54.LuaRuntime(unpack_returned_tuples=True)
    entry = lua.execute((ROOT / "lua/gen3/entry.lua").read_text())
    codec = lua.execute((ROOT / "lua/json_codec.lua").read_text())
    result = entry.admit_routed(
        lua.table(
            root=ROOT.as_posix(),
            json=codec,
            rom_hash=hashlib.sha1(published).hexdigest(),
            header_code={"firered": "BPRE", "leafgreen": "BPGE"}[title],
            rom_read=lambda at, n: lua.table(*published[at : at + n]),
        )
    )
    shipped = json.loads((ROOT / "data/games/gen3_frlg/engine_signals.json").read_text())
    public=shipped["titles"][title]["artifacts"]["companion"]
    assert public["production"] is True and not public.get("harness_only")
    assert public["rom_sha1"]==hashlib.sha1(published).hexdigest()
    from tools import gen3_companions as gc
    assert manifest["rom_sha1"]==public["rom_sha1"] and gc.accepts(manifest, "payload_sha256", receipt["payload_sha256"])
    # version-masked identity: the tested candidate and the published build are the same canonical payload, and the published
    # ROM's canonical sha1 is its bytes with the fixed-width version field zeroed
    from patch.tools import rom_identity
    assert manifest["canonical_payload_sha256"]==receipt["canonical_payload_sha256"]
    assert manifest["canonical_sha1"]==rom_identity.canonical_sha1(bytes(published),[manifest["version_slot"]])
    assert result.kind=="companion" and result.admitted_by=="hash"


@pytest.mark.parametrize("title", ["firered", "leafgreen"])
def test_test_only_projection_builds_the_real_client_and_native_binding(monkeypatch, title):
    from tests.unit import test_gen3_entry as entry

    if not (ROOT / f"patch/build/candidate-{title}-trade/probe.gba").exists():
        pytest.skip("T5 private FR candidate build absent")
    monkeypatch.setattr(entry, "lupa", lua54)
    manifest = t5.prepare(ROOT, ROOT / ("patch/build/t5-unit-" + uuid.uuid4().hex), title=title)
    rom = (ROOT / manifest["rom"]).read_bytes()
    world = entry.World(pack="gen3_frlg", title=title, build=False)
    lua = world.lua
    lua.globals().gameinfo = lua.table(getromhash=lambda: manifest["rom_sha1"])
    lua.globals().emu = lua.table(framecount=lambda: 0)
    lua.globals().os.getenv = lambda name: manifest["nonce"] if name == t5.ENV else None
    json_codec = lua.execute((ROOT / "lua/json_codec.lua").read_text())
    module = lua.execute((ROOT / "lua/tests/duo/gen3_trade_candidate.lua").read_text())
    carrier = module.new(
        lua.table(
            wt=ROOT.as_posix(),
            game="gen3_fr_trade",
            title=title,
            player="a",
            scenario="native_trade_firered",
            phase="initial",
            native_manifest_sha1=manifest["manifest_sha1"],
        ),
        json_codec,
        lua.table_from(manifest, recursive=True),
        lambda _: None,
        (ROOT / manifest["path"]).read_bytes().decode("utf-8"),
    )
    carrier.bind_entry(world.Entry)
    world.io.rom_read = lambda at, n: lua.table(*rom[at : at + n])
    admitted = world.Entry.admit_routed(
        lua.table(
            root=ROOT.as_posix(),
            json=json_codec,
            rom_hash=manifest["rom_sha1"],
            header_code={"firered": "BPRE", "leafgreen": "BPGE"}[title],
            rom_read=world.io.rom_read,
        )
    )
    assert admitted.kind == "companion" and admitted.admitted_by == "hash"
    client, parts = entry._production(world, kind="companion", battle_nonce_seed="1234567800000001")
    assert client is not None and parts.native is not None
    assert parts.write_checkpoint.native.version == "gen3-native-v2"
    assert not parts.native.trade_capable(parts.native), (
        "metadata never substitutes for the cartridge beacon"
    )
    client.start(client)
    assert len(world.registered) == len(list(parts.sites.keys())), (
        "startup must arm every projected engine site"
    )
    # The repair must not weaken byte verification. A real byte mismatch still
    # refuses before arming; reverting it permits the same complete startup.
    client.stop(client)
    world.registered.clear()
    original = parts.sites.battle_begin.expected_hex
    parts.sites.battle_begin.expected_hex = f"{int(original[:2], 16) ^ 1:02X}" + original[2:]
    with pytest.raises(lua54.LuaError, match="engine sites differ from the ROM: battle_begin"):
        client.start(client)
    assert world.registered == []
    parts.sites.battle_begin.expected_hex = original
    client.start(client)
    assert len(world.registered) == len(list(parts.sites.keys()))


def test_candidate_receipt_cannot_whitelist_an_unrelated_rom_change(tmp_path):
    source = ROOT / "patch/build/candidate-firered-trade"
    if not (source / "probe.gba").exists():
        pytest.skip("T5 private FR candidate build absent")
    dest = tmp_path / "patch/build/candidate-firered-trade"
    dest.mkdir(parents=True)
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data/gen3_sources.lock.json").write_bytes(
        (ROOT / "data/gen3_sources.lock.json").read_bytes()
    )
    rom = bytearray((source / "probe.gba").read_bytes())
    rom[0x500000] ^= 1
    receipt = json.loads((source / "receipt.json").read_text())
    receipt["sha1"] = hashlib.sha1(rom).hexdigest()
    (dest / "probe.gba").write_bytes(rom)
    (dest / "probe.bin").write_bytes((source / "probe.bin").read_bytes())
    (dest / "receipt.json").write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="pinned clean ROM"):
        t5.candidate_inputs(tmp_path)


def snapshots():
    def snapshot(op=0, seq=12):
        data = bytearray(160)

        def put(at, n, value):
            data[at : at + n] = value.to_bytes(n, "little")

        put(0, 4, 0x4B4E4C53)
        put(4, 2, 2)
        put(6, 2, op)
        put(8, 2, seq)
        put(10, 2, 2)
        put(12, 2, seq)
        put(64, 4, 3)
        put(68, 4, 7)
        put(72, 4, 4)
        data[16] = 1
        put(20, 4, 1)
        put(24, 4, 2)
        put(28, 4, 9)
        data[32:48] = bytes(range(1, 17))
        put(80, 4, 7)
        put(84, 4, 9)
        data[88:104] = data[32:48]
        put(104, 2, 2)
        put(106, 2, 3)
        for i, value in enumerate((11, 12, 12, 12, 12)):
            put(112 + 2 * i, 2, value)
        put(108, 4, 31)
        data[122] = 1
        data[123] = 1
        put(144, 4, 1)
        put(148, 4, 2)
        put(152, 4, 3)
        put(156, 4, 4)
        return data

    prepare, scene, commit, final = snapshot(29, 11), snapshot(21), snapshot(), snapshot()
    commit[108:112] = (3).to_bytes(4, "little")
    commit[122] = 0
    return [prepare, scene, commit, final]


@pytest.mark.parametrize(
    "part,offset",
    [
        (0, 6),
        (1, 8),
        (1, 20),
        (2, 80),
        (2, 88),
        (2, 104),
        (2, 106),
        (2, 108),
        (2, 112),
        (2, 114),
        (3, 72),
        (3, 108),
        (3, 116),
        (3, 118),
        (3, 120),
        (3, 122),
        (3, 123),
        (3, 144),
        (3, 148),
        (3, 152),
        (3, 156),
    ],
)
def test_native_oracle_rejects_each_missing_binding_and_revert_restores_pass(part, offset):
    rows = snapshots()
    assert t5.witness_problems(*map(bytes, rows), (1, 2), (3, 4)) == []
    broken = copy.deepcopy(rows)
    broken[part][offset] ^= 1
    assert t5.witness_problems(*map(bytes, broken), (1, 2), (3, 4))
    assert t5.witness_problems(*map(bytes, rows), (1, 2), (3, 4)) == []


def flash_with_party(seed, party, counter):
    """Independent MODEL saved result: replace the active slot's logical blocks."""
    c = t5.codec
    parsed = c.parse_flash(seed)
    blocks = {name: bytearray(parsed[name]) for name in ("sb1", "sb2", "storage")}
    blocks["sb1"][c.SB1_PARTY_COUNT_OFFSET] = len(party)
    for index, mon in enumerate(party):
        at = c.SB1_PARTY_OFFSET + 100 * index
        blocks["sb1"][at : at + 100] = c.encode_party_mon(mon)
    out = bytearray(seed)
    layout = c.slot_layout()
    sectors = parsed["sectors"][14 * parsed["slot"] : 14 * (parsed["slot"] + 1)]
    for chunk in layout:
        physical = next(row["index"] for row in sectors if row["id"] == chunk["id"])
        data = blocks[chunk["object"]][chunk["offset"] : chunk["offset"] + chunk["size"]]
        out[physical * 4096 : (physical + 1) * 4096] = c.write_sector(
            data, chunk["id"], counter, layout
        )
    assert c.qualify_flash(out)[0]
    return bytes(out)


def model_physical_evidence(tmp_path, decline=False):
    from tools.e2e_duo import gen3_decode

    root = tmp_path
    (root / "patch/build").mkdir(parents=True)
    manifest = {**model_manifest(), "expected_species": 65}
    raw = {
        side: t5.trade_fixture(
            (ROOT / f"tests/fixtures/gen3/firered_party_town{suffix}.sav").read_bytes()
        )
        for side, suffix in (("a", ""), ("b", "_b"))
    }
    fixtures = {side: gen3_decode(data) for side, data in raw.items()}
    saved, initial, reloaded = {}, {}, {}
    document = {
        "links": [
            {
                "a": {"key": t5.key(fixtures["a"][0][1])},
                "b": {"key": t5.key(fixtures["b"][0][1])},
                "status": "alive",
            }
        ],
        "trade_finals": {side: [{"token": "t1", "verdict": "committed"}] for side in "ab"},
    }
    if not decline:
        document["links"][0]["a"], document["links"][0]["b"] = (
            document["links"][0]["b"],
            document["links"][0]["a"],
        )
    for side in "ab":
        peer = "b" if side == "a" else "a"
        before = copy.deepcopy(fixtures[side][0])
        party = copy.deepcopy(before)
        old, incoming = before[1], fixtures[peer][0][1]
        if not decline:
            party[1] = dict(incoming, species=65)
        count = t5.codec.parse_flash(raw[side])["counter"]
        final_save = flash_with_party(raw[side], party, count + (0 if decline else 2))
        saved[side] = gen3_decode(final_save)
        state = {"side": side, "phase": "initial", "frame": 1}
        rows = []

        capture = {"state": state, "rows": rows}

        def append(kind, *, binary=None, capture_=capture, side_=side, **fields):
            state_ = capture_["state"]
            rows_ = capture_["rows"]
            row = {**state_, "kind": kind, **fields}
            if binary is not None:
                path = f"patch/build/t5_{manifest['nonce']}_{side_}_{state_['phase']}_{kind}_{len(rows_)}.bin"
                (root / path).write_bytes(binary)
                row["path"] = path
            rows_.append(row)
            return row

        def override():
            append(
                "override",
                production=False,
                ready=0,
                environment=t5.ENV,
                value=manifest["nonce"],
                rom_sha1=manifest["rom_sha1"],
                source_commit=manifest["source_commit"],
                manifest_sha1=manifest["manifest_sha1"],
                run_lua_sha1=manifest["source_sha1"]["lua/gen3/run.lua"],
                sites_sha1=manifest["pack_sha1"]["sites"],
            )

        override()
        append(
            "boot_party",
            binary=b"".join(t5.codec.encode_party_mon(m) for m in before),
            count=len(before),
            counter=count,
        )
        append("boot", counter=count)
        append("rx", message={"cmd": "config", "run_id": "model-run"})
        from tests.unit.test_gen3_native_carrier_duo import carrier_rows
        for row in carrier_rows(manifest, side, decline):
            row = dict(row)
            kind, witness_bytes = row.pop("kind"), row.pop("raw", None)
            append(kind, binary=witness_bytes, **row)
        if not decline:
            pre, scene, commit, final = snapshots()
            for data in (pre, scene, commit, final):
                for at, value in (
                    (20, old["personality"]),
                    (24, old["ot_id"]),
                    (144, old["personality"]),
                    (148, old["ot_id"]),
                    (152, incoming["personality"]),
                    (156, incoming["ot_id"]),
                ):
                    data[at : at + 4] = value.to_bytes(4, "little")
            append("prepare", binary=pre)
            append("save_entry", ordinal=1)
            append("scene", binary=scene)
            from tests.unit.gen3_trade_journal_model import JournalModel

            runtime = lua54.LuaRuntime(unpack_returned_tuples=True)
            journal_model = JournalModel(
                player=side, rom=manifest["rom_sha1"], ot=f"{old['ot_id']:08X}"
            )
            journal = journal_model(runtime)
            epoch = journal.allocate(journal)
            if side == "b":
                epoch = journal.allocate(journal)
            assert journal.arm(journal, "t1", epoch)
            data = journal_model.data.encode()
            digest = 2166136261
            for byte in data:
                digest = ((digest ^ byte) * 16777619) & 0xFFFFFFFF
            guard = f"SLINK-TRADE-JOURNAL-1\n{len(data)}:{digest:08x}\n".encode()
            path = f"patch/build/t5_{manifest['nonce']}_{side}_initial_guard.bin"
            (root / path).write_bytes(guard)
            append("journal_intent", binary=data, guard=path)
            append("scene_enter", binary=scene)
            append("commit", binary=commit)
            append("evolution", binary=commit)
            append("save_entry", ordinal=2)
        else:
            append("rx", message={"cmd": "msgbox", "text": "Your partner declined."})
        append("flash", binary=final_save, counter=count + (0 if decline else 2))
        append(
            "flush_native",
            binary=bytes(160) if decline else final,
            counter=count + (0 if decline else 2),
        )
        append("flush", binary=final_save, counter=count + (0 if decline else 2), status="returned")
        if not decline:
            append(
                "tx",
                message={
                    "event": "trade_done",
                    "token": "t1",
                    "new_key": t5.key(incoming),
                    "new_species": 65,
                },
            )
            append("rx", message={"cmd": "trade_final", "token": "t1", "verdict": "committed"})
            append("journal", token="t1", ready=True, hidden=False, empty=True)
            append("final", binary=final)
        append(
            "before_reload",
            binary=b"".join(t5.codec.encode_party_mon(m) for m in party),
            count=len(party),
            counter=count + (0 if decline else 2),
        )
        initial[side] = rows
        rows = []
        capture["rows"] = rows
        state["phase"] = "native_trade_reload"
        override()
        append(
            "reloaded",
            binary=b"".join(t5.codec.encode_party_mon(m) for m in party),
            count=len(party),
            counter=count + (0 if decline else 2),
        )
        reloaded[side] = rows
    return root, manifest, initial, reloaded, document, fixtures, saved


def receipt(rows):
    return (
        "HARNESS_ONLY " + t5.DISCLOSURE + "\n" + "\n".join("T5 " + json.dumps(row) for row in rows)
    )


def check_model(model, decline=False):
    root, manifest, initial, reloads, document, fixtures, saved = model
    return t5.physical_problems(
        root,
        manifest,
        {k: receipt(v) for k, v in initial.items()},
        {k: receipt(v) for k, v in reloads.items()},
        document,
        fixtures,
        saved,
        decline=decline,
    )


@pytest.mark.parametrize("decline", [False, True])
def test_complete_physical_oracle_has_positive_and_decline_controls(tmp_path, decline):
    model = model_physical_evidence(tmp_path, decline)
    assert check_model(model, decline) == []


def test_save_site_and_trade_fsm_flushes_in_the_same_frame_are_both_legitimate(tmp_path):
    model = model_physical_evidence(tmp_path)
    rows = model[2]["a"]
    at = next(i for i, r in enumerate(rows) if r["kind"] == "flush")
    duplicate = copy.deepcopy(rows[at - 2 : at + 1])
    rows[at + 1 : at + 1] = duplicate
    assert check_model(model) == []


@pytest.mark.parametrize(
    "fault",
    [
        "commit",
        "native_save",
        "flush",
        "flash",
        "flush_failed",
        "flush_order",
        "final",
        "stored_final",
        "link",
        "reload",
        "evolution",
        "identity",
        "disclosure",
        "later_save",
        "reload_interaction",
        "journal",
        "intent",
    ],
)
def test_each_physical_requirement_has_a_negative_and_revert_control(tmp_path, fault):
    model = model_physical_evidence(tmp_path)
    assert check_model(model) == []
    broken = copy.deepcopy(model)
    _, _, initial, reloads, document, _, saved = broken
    if fault in ("commit", "native_save", "flush", "flash", "final", "journal", "intent"):
        kind = {"native_save": "save_entry", "final": "rx", "intent": "journal_intent"}.get(
            fault, fault
        )
        initial["a"] = [r for r in initial["a"] if r["kind"] != kind]
    elif fault == "flush_order":
        rows = initial["a"]
        row = next(r for r in rows if r["kind"] == "flush")
        rows.remove(row)
        rows.append(row)
    elif fault == "stored_final":
        document["trade_finals"]["a"] = []
    elif fault == "flush_failed":
        next(r for r in initial["a"] if r["kind"] == "flush")["status"] = "failed"
    elif fault == "link":
        document["links"][0]["a"]["key"] = "bad"
    elif fault == "reload":
        reloads["b"] = []
    elif fault == "evolution":
        saved["a"][0][1]["species"] = 64
    elif fault == "identity":
        saved["a"][0][1]["ot_id"] ^= 1
    elif fault == "disclosure":
        initial["a"][0]["production"] = True
    elif fault == "later_save":
        next(r for r in reloads["b"] if r["kind"] == "reloaded")["counter"] += 1
    elif fault == "reload_interaction":
        reloads["a"].append({**reloads["a"][0], "kind": "tx", "message": {"event": "trade_request"}})
    assert check_model(broken)
    assert check_model(model) == []


def test_carrier_text_maps_a_newline_like_the_native_producer():
    # lua/gen3/native.lua encode(): "\n" -> 0xFE; the oracle raised on it (T5 run 2026-09-27)
    from tools.gen3_trade_duo import carrier_text
    assert carrier_text("Trade?\nYes") == "Trade?<$FE>Yes"
