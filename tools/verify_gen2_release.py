#!/usr/bin/env python3
"""Gen 2 release manifest over the shared fail-closed release_lanes runner.

--list describes obligations without executing or qualifying them. --quick runs the
source/MODEL frontier; --lane runs only the named obligations. Neither is a release
verdict. Fixtures, companion builds, cartridge gates, the non-link duo scenarios and final
evidence closure are deliberately unimplemented P3b/P4/P6 bindings and fail when requested,
even if a file with the future name happens to exist.

--duo-matrix (the duo-link lane) checks the release duo matrix of
tests/gen2_release_requirements.json: C<->C, G<->S and C<->G, every scenario the pairing
registers in tools/e2e_duo.py, each with its post-result oracle and pinned PASS receipts.
A missing pair, scenario, oracle or receipt is RED, never green. Enabling them requires their reviewed
implementation and prerequisite/receipt contracts, not removing a missing-input check.

--new-gates (a live-new-gates precondition) checks the committed U1 engine-site, U2 write-window
(Silver via O-23) and fixture-qualification receipts of tests/gen2_live_gate_requirements.json against
their pinned sha256 and their production Lua validators (reusing tests/unit/test_gen2_physical_receipts.py's
`validate()`, never re-deriving PASS). It runs with no emulator; a gap there fails live-new-gates before
the lane spawns EmuHawk. R-1/R-2/R-3/R-4/R-5g still need a fresh SLINK_LIVE=1 run of the live inspect
gate on real hardware, which the lane runs directly once this check is clean.

Every executing lane checks its declared input paths before spawning a command. The
source/data tools then verify hashes and provenance themselves. Missing scripts, data,
dependencies and pytest skips are failures. This manifest grants no evidence-cell or
artifact-admission status; the P3b machine ledger is not generated here.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import release_lanes
from release_lanes import Lane

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_PY = sys.executable
TITLES = ("crystal", "gold", "silver")
REQUIREMENT_IDS = (
    "F-1", "F-2", "F-3", "F-4", "F-5", "F-6", "F-7g",
    "R-1", "R-2", "R-3", "R-4", "R-5g",
    "S-1", "S-2", "S-3", "S-4", "S-5", "S-6", "S-7", "S-8", "S-9g", "S-10g",
    "W-1", "W-2", "W-3", "W-4", "W-5", "W-6", "W-7",
    "C-0", "C-1", "C-2", "C-3", "C-4", "C-5", "C-6g",
    "D-1", "D-2", "D-3", "D-5", "D-6", "D-7", "D-11", "D-12", "D-13", "D-14",
    "T-1", "T-2", "T-3", "T-4", "N-1", "N-2", "N-3",
)
# These rows remain mapped. This is a scope description, not a signed disposition.
CONDITIONAL_OR_DEFERRED = {
    "W-3": "conditional Explode Mode; owner enablement or signed disabled disposition",
    "W-4": "conditional rival swap; owner enablement or signed disabled disposition",
    "C-5": "conditional randomized admission; no admission without an enabling ruling",
    "D-11": "conditional duo behavior follows W-3/W-4",
    "N-3": "post-G6 ghost artifact and its separate G5 qualification",
}

_GENERATORS = (
    ("species-generated", "species", ("F-5",)),
    ("evos-generated", "evos", ("F-5",)),
    ("items-generated", "items", ("F-5",)),
    ("moves-generated", "moves", ("F-5",)),
    ("charmap-generated", "charmap", ("R-1",)),
    ("map-names-generated", "map_names", ("F-7g",)),
    ("engine-sites-generated", "engine_signals", ("F-2", "F-3")),
    ("checkpoint-generated", "write_checkpoint", ("R-4", "W-6")),
    ("area-map-generated", "area_map", ("F-7g", "S-8", "S-9g", "S-10g")),
    ("encounters-generated", "encounters", ("F-4", "F-7g", "S-9g", "S-10g")),
    ("statics-generated", "statics", ("S-8",)),
    ("trainers-generated", "trainers", ("R-3",)),
    ("admission-generated", "admission", ("F-7g", "C-1", "C-6g")),
)


def _pytest(path: str) -> list[str]:
    return [_PY, "-m", "pytest", path, "-q", "-p", "no:randomly", "-rs"]


LANES = [
    Lane("unit", _pytest("tests/unit"), why="SOURCE/MODEL tests; no cartridge proof"),
    Lane("source-build", [_PY, "tools/build_gen2_syms.py", "--check"],
         why="rebuild four pinned ROMs and compare the published lock, symbols and maps"),
    Lane("rom-layout", [_PY, "tools/verify_gen2_rom_layout.py"],
         why="built-ROM bytes, banks and independently decoded tables; SOURCE only"),
    Lane("lua-parse", [_PY, "tools/lua_syntax_check.py"],
         why="parse the production Lua files; MODEL only"),
    *[Lane(f"profile-generated-{title}",
           [_PY, "tools/gen_gen2_profile.py", "--title", title, "--check"],
           why=f"{title} profile against its locked source/build; SOURCE only")
      for title in TITLES],
    *[Lane(name, [_PY, f"tools/gen_gen2_{tool}.py", "--check"],
           why="all three title packs regenerated from pinned facts; SOURCE only")
      for name, tool, _ids in _GENERATORS],
    Lane("coverage-map", [
        _PY, "tools/coverage_map.py", "--map", "docs/gen2/gen2_coverage_map.md",
        "--requirements", "docs/gen2/gen2_requirements.md", "--protocol", "docs/protocol.md",
        "--protocol-section", "9", "--protocol-layers", "SOURCE", "PHYSICAL",
        "--artifact-policy", "data/gen2_sources.lock.json", "--artifact-collection", "outputs",
        "--artifact-digest-field", "sha1", "--artifact-id", "pokecrystal",
        "--artifact-id", "pokegold", "--artifact-id", "pokesilver",
        # Mapping may name future targets; these flags confer no evidence eligibility.
        # Native and post-RC ghost scope is game policy, never inferred by the validator.
        "--planned-target", "crystal_overlay=pokecrystal",
        "--planned-target", "crystal_ghost=pokecrystal",
        "--planned-target", "gold_overlay=pokegold",
        "--planned-target", "gold_ghost=pokegold",
        "--planned-target", "silver_overlay=pokesilver",
        "--planned-target", "silver_ghost=pokesilver",
        "--target-binding", (
            "requirement:C-3,requirement:T-1,requirement:T-2,requirement:T-3,requirement:T-4,"
            "requirement:N-1,requirement:N-2,protocol:9.39,protocol:9.40,protocol:9.41,"
            "protocol:9.42,protocol:9.43,protocol:9.47=crystal_overlay,gold_overlay,silver_overlay"
        ),
        "--target-binding", "requirement:N-3=crystal_ghost,gold_ghost,silver_ghost",
        "--mode", "mapping",
    ],
         why="P2 mapping completeness only; unrun PHYSICAL obligations remain OPEN"),
    Lane("fixtures", [_PY, "tools/gen2_fixtures.py", "--qualify"],
         why="UNIMPLEMENTED P3b: eight played saves, independent codec and boot/reload chains"),
    Lane("patch-build", [_PY, "tools/build_gen2_companion.py", "--check"],
         why="UNIMPLEMENTED P4: reproducible overlays and reopened artifact obligations"),
    Lane("live-gates", _pytest("tests/live/test_gen2_trade_gates.py"),
         env={"SLINK_LIVE": "1"},
         why="UNIMPLEMENTED P4: panel/sound and transient receipts on qualified overlays"),
    Lane("live-new-gates", _pytest("tests/live/test_gen2_new_gates.py"),
         env={"SLINK_LIVE": "1"},
         why="PHYSICAL receipts: the U1 engine-site, U2 write-window (Silver via O-23) and fixture"
             " qualification rows of tests/gen2_live_gate_requirements.json are bound and pinned by"
             " sha256 (new_gates_errors, no emulator); a gap there fails the lane before it spawns"
             " EmuHawk. R-1/R-2/R-3/R-4/R-5g have no committed receipt and still need a fresh"
             " SLINK_LIVE=1 run of the live inspect gate (lua/tests/gen2_inspect_gate.lua) on real"
             " hardware; client-conformance (P3b.6/P3b.7) stays a separate later card"),
    Lane("live-trade-gates", _pytest("tests/live/test_gen2_trade_gates.py"),
         env={"SLINK_LIVE": "1"},
         why="UNIMPLEMENTED P4: native trade, held items, refusal and exact-record reload"),
    Lane("duo-link", [_PY, "tools/verify_gen2_release.py", "--duo-matrix"],
         why="PHYSICAL receipts: the C-C, G-S and C-G link matrix of tests/gen2_release_requirements.json;"
             " a missing pair, scenario, oracle or receipt is red"),
    Lane("duo-pairs", _pytest("tests/e2e/test_duo_gen2_new.py"),
         env={"SLINK_E2E": "1", "SLINK_LIVE": "1"},
         why="UNIMPLEMENTED P3b/P4: the C-C and G-S rules/trade scenarios beyond link (link is"
             " duo-link's matrix); independent oracles"),
    Lane("release-evidence", [],
         why="UNIMPLEMENTED P6: signed applicability, all artifact receipts and two-person review"),
]

REQUIREMENTS = {
    "unit": ["F-1", "F-2", "F-4", "F-5", "R-1", "R-2", "C-0", "C-4", "D-13"],
    "source-build": ["F-1"],
    "rom-layout": ["F-2", "F-3", "F-4"],
    "lua-parse": ["C-4"],
    **{f"profile-generated-{title}": ["F-1"] for title in TITLES},
    **{name: list(ids) for name, _tool, ids in _GENERATORS},
    "coverage-map": list(REQUIREMENT_IDS),
    "fixtures": ["F-6", "S-7"],
    "patch-build": ["F-2", "F-3", "W-6", "C-1", "T-1", "N-1", "N-2"],
    "live-gates": ["C-3", "N-1", "N-2"],
    "live-new-gates": [
        "F-2", "F-3", "F-6", "R-1", "R-2", "R-3", "R-4", "R-5g",
        "S-1", "S-2", "S-3", "S-4", "S-5", "S-6", "S-7", "S-8", "S-9g", "S-10g",
        "W-1", "W-2", "W-5", "W-6", "W-7", "C-1",
    ],
    "live-trade-gates": ["T-1", "T-2", "T-3", "T-4"],
    "duo-link": ["D-1", "C-6g"],
    "duo-pairs": [
        "F-6", "S-2", "S-3", "S-5", "S-6", "S-7", "S-8", "S-9g", "S-10g",
        "W-5", "W-7", "C-2", "C-6g", "D-1", "D-2", "D-3", "D-5", "D-6", "D-7",
        "D-12", "D-14", "T-3", "T-4",
    ],
    "release-evidence": list(REQUIREMENT_IDS),
}

UNIMPLEMENTED = {
    "fixtures": "P3b fixture qualifier, eight played fixtures and GAME/PYDEC reload evidence",
    "patch-build": "P4 companion build command and patched-artifact qualification",
    "live-gates": "P4 panel/sound gate and transient-receipt contract",
    "live-trade-gates": "P4 trade and held-item persistence/refusal gates",
    "duo-pairs": ("P3b.7 scenarios beyond link (ball_gate, boxed_capture, faints, poison, whiteout,"
                  " pc_ops, changebox, clauses, shiny_bonus, reconnect, soft_reset, evolution,"
                  " npc_trade, gift, egg_hatch, admit_wrong_rom) are not registered in"
                  " tools/e2e_duo.py; P4 trade"),
    "release-evidence": "P3b machine ledger plus P6 applicability/artifact/receipt evaluation",
}
# --quick is source/MODEL feedback, including the P2 coverage map once bound. All
# later-phase obligations stay in the full manifest; omitting them grants no release verdict.
_SLOW = {"fixtures", "patch-build", "live-gates", "live-new-gates",
         "live-trade-gates", "duo-link", "duo-pairs", "release-evidence"}
ALLOWED_SKIPS = ()
_REQUIRED_LANES = frozenset(REQUIREMENTS)
_REQUIRED_MAPPINGS = {name: frozenset(ids) for name, ids in REQUIREMENTS.items()}

_SOURCE_INPUTS = (
    "data/gen2_sources.lock.json", "data/gen2/build_provenance.json",
    *(f"data/gen2/{artifact}.{suffix}"
      for artifact in ("pokecrystal", "pokecrystal11", "pokegold", "pokesilver")
      for suffix in ("sym", "map")),
    *(f".cache/gen2-build/{repo}/{filename}"
      for repo, filename in (("pokecrystal", "pokecrystal.gbc"),
                             ("pokecrystal", "pokecrystal11.gbc"),
                             ("pokegold", "pokegold.gbc"),
                             ("pokegold", "pokesilver.gbc"))),
)
PREREQUISITES = {
    "unit": ("tests/unit",),
    "source-build": _SOURCE_INPUTS,
    "rom-layout": _SOURCE_INPUTS,
    "lua-parse": ("lua",),
    **{f"profile-generated-{title}": _SOURCE_INPUTS for title in TITLES},
    **{name: _SOURCE_INPUTS for name, _tool, _ids in _GENERATORS},
    "coverage-map": ("docs/gen2/gen2_coverage_map.md", "docs/gen2/gen2_requirements.md",
                     "docs/protocol.md", "data/gen2_sources.lock.json"),
    "fixtures": tuple(
        f"tests/fixtures/gen2/{name}.SaveRAM"
        for name in (*(f"{title}_{kind}" for title in TITLES for kind in ("town", "battle")),
                     "crystal_town_ot2", "crystal_battle_ot2", "gold_battle_ot2")
    ),
    "patch-build": _SOURCE_INPUTS,
    "live-gates": (),
    "live-new-gates": ("tests/gen2_live_gate_requirements.json", "tests/fixtures/gen2/receipts"),
    "live-trade-gates": (),
    "duo-link": ("tests/gen2_release_requirements.json", "tools/e2e_duo.py",
                 "data/gen2_sources.lock.json"),
    "duo-pairs": (),
    "release-evidence": ("tests/gen2_release_requirements.json",),
}


DUO_MATRIX = "tests/gen2_release_requirements.json"
# The release matrix itself, (initiator, partner) per O-16. Pinned here so that deleting a row
# from the JSON cannot shrink the matrix silently.
DUO_PAIRS = (("crystal", "crystal"), ("crystal", "gold"), ("gold", "silver"))
DUO_REQUIRED_SCENARIOS = frozenset({"link"})


# Codex's H5 PYDEC format (review O16 F1): "PYDEC: PASS a=<key> b=<key> area=<id>
# titles=<a-title>/<b-title> status=<alive|dead|memorial>" -- link ends alive; gen2_faint ends dead, or
# memorial once the Gen 2 memorialize NACK lets the server finish the pair (owner, via Codex H5).
SCENARIO_END_STATUS = {"link": {"alive"}, "gen2_faint": {"dead", "memorial"}}


def _fixture_sha256(root: Path, fixture: str) -> str | None:
    try:
        return hashlib.sha256((root / "tests/fixtures/gen2" / f"{fixture}.SaveRAM").read_bytes()).hexdigest()
    except OSError:
        return None


def _engine_capture_key(lines: list[str]) -> str | None:
    line = next((one for one in lines if one.startswith("ENGINE_CAPTURE ")), None)
    if not line:
        return None
    try:
        return json.loads(line[len("ENGINE_CAPTURE "):]).get("key")
    except ValueError:
        return None


def _pydec_tokens(lines: list[str]) -> dict | None:
    line = next((one for one in lines if one.startswith("PYDEC: PASS ")), None)
    if line is None:
        return None
    tokens = {}
    for part in line[len("PYDEC: PASS "):].split():
        key, sep, value = part.partition("=")
        if sep:
            tokens[key] = value
    return tokens


def _pydec_cell_errors(lines: list[str], scenario: str, axes: dict, capture_keys: dict,
                       lock: dict | None = None) -> list[str]:
    """The pydec receipt names its own cell, not just a bare PASS (review O16 F1)."""
    tokens = _pydec_tokens(lines)
    if not tokens:
        return ["pydec receipt does not name this cell"]
    want = {"a": capture_keys.get("a"), "b": capture_keys.get("b"),
            "titles": f"{axes['initiator']}/{axes['partner']}",
            "status": SCENARIO_END_STATUS.get(scenario)}
    if scenario == "gen2_admit_wrong_rom":
        want = {"scenario": scenario, "a": "admitted", "b": "refused", "area": "none",
                "titles": f"{axes['initiator']}/crystal", "status": "refused",
                "rom_b": (lock or {}).get("pokecrystal11", {}).get("sha1", "")}
    elif scenario == "gen2_soft_reset":
        want = {"scenario": scenario, "a": "reset", "b": "idle", "area": "none",
                "titles": f"{axes['initiator']}/{axes['partner']}", "status": "unchanged"}
    errors = [f"pydec receipt does not name this cell: {key}={tokens.get(key)!r}, want {value!r}"
              for key, value in want.items()
              if value is not None and not (tokens.get(key) in value if isinstance(value, set) else tokens.get(key) == value)]
    if not tokens.get("area"):
        errors.append("pydec receipt does not name this cell: area= is empty or missing")
    return errors


def _refused_receipt_errors(lines: list[str], rom_sha1: str | None) -> list[str]:
    """Only H7's B half may replace a save with pinned no-client/no-traffic evidence."""
    rows = {}
    for tag in ("DUO_GEN2", "ADMISSION_REFUSED", "NO_TRAFFIC", "CARTRAM_UNCHANGED", "RECEIPT"):
        bodies = [line[len(tag) + 1:] for line in lines if line.startswith(tag + " ")]
        if len(bodies) != 1:
            return [f"b refused receipt requires exactly one {tag}"]
        try:
            rows[tag] = json.loads(bodies[0])
        except ValueError:
            return [f"b refused receipt has malformed {tag}"]
        if not isinstance(rows[tag], dict):
            return [f"b refused receipt has malformed {tag}"]
    errors = []
    forbidden = ("CLIENT", "BOOTED", "HELLO", "HELLO_AGAIN", "TX", "HOLD", "SAVE_WITNESS", "ENGINE_CAPTURE")
    if any(line.split(" ", 1)[0] in forbidden for line in lines):
        errors.append("b refused receipt contains admitted-client activity")
    refusal, quiet, cart, receipt = (rows[tag] for tag in
                                    ("ADMISSION_REFUSED", "NO_TRAFFIC", "CARTRAM_UNCHANGED", "RECEIPT"))
    console = refusal.get("console")
    if (not rom_sha1 or refusal.get("rom_sha1") != rom_sha1 or refusal.get("client") is not False
            or not isinstance(console, str) or "refused" not in console):
        errors.append("b refused receipt has no pinned admission refusal")
    if quiet.get("tx") != 0 or type(quiet.get("frames")) is not int or quiet["frames"] < 600:
        errors.append("b refused receipt has no 600-frame traffic-free hold")
    digest = cart.get("before")
    if (not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)
            or cart.get("after") != digest):
        errors.append("b refused receipt has no unchanged CartRAM digest")
    tags = list(rows)
    positions = [next(i for i, line in enumerate(lines) if line.startswith(tag + " ")) for tag in tags]
    if positions != sorted(positions):
        errors.append("b refused receipt markers out of order")
    head = rows["DUO_GEN2"]
    if (receipt.get("schema") != "gen2-duo-admit-wrong-rom-v1"
            or any(receipt.get(key) != head.get(key) for key in
                   ("player", "scenario", "attempt", "title", "rom_sha1", "expect_admission"))):
        errors.append("b refused receipt does not bind its header")
    return errors


def _reconnect_receipt_errors(root: Path, proof: dict, axes: dict, lock: dict) -> list[str]:
    """Bind all reconnect legs and immutable staged bytes; only killed initial A lacks RESULT."""
    def need(condition, why):
        if not condition:
            raise ValueError(why)

    def pinned(entry, binary=False):
        raw = (root / entry["path"]).read_bytes()
        if not binary:
            raw = raw.replace(b"\r\n", b"\n")
        need(hashlib.sha256(raw).hexdigest() == entry["sha256"], f"{entry['path']}: sha256 differs")
        return raw

    def one(lines, tag):
        bodies = [line[len(tag) + 1:] for line in lines if line.startswith(tag + " ")]
        need(len(bodies) == 1, f"expected one {tag}")
        row = json.loads(bodies[0])
        need(isinstance(row, dict), f"malformed {tag}")
        return row

    def position(lines, tag):
        return next(i for i, line in enumerate(lines) if line.startswith(tag + " "))

    try:
        receipts = proof["receipts"]
        legs = {side: pinned(receipts[side]).decode("utf-8").splitlines()
                for side in ("a", "b", "a_same_save", "a_wrong_save", "pydec")}
        stages = proof["staged_saves"]
        seeds = {phase: pinned(stages[phase], binary=True) for phase in ("same_save", "wrong_save")}
        wrong_case = f"{axes['initiator']}_battle_ot2"
        need(stages["wrong_save"]["case"] == wrong_case, "wrong-save fixture case differs")
        need(hashlib.sha256(seeds["wrong_save"]).hexdigest() == _fixture_sha256(root, wrong_case),
             "wrong-save staged bytes differ from fixture")
        need(seeds["same_save"] != seeds["wrong_save"], "relaunch seeds are identical")
        keys = {side: one(legs[side], "ENGINE_CAPTURE")["key"] for side in ("a", "b")}
        need(all(isinstance(key, str) and key for key in keys.values()), "missing capture keys")
        for side in ("a", "b", "a_same_save", "a_wrong_save"):
            lines = legs[side]
            player = "b" if side == "b" else "a"
            phase = side[2:] if side.startswith("a_") else "initial"
            title = axes["partner"] if player == "b" else axes["initiator"]
            case = axes["fixtures"][player] if phase == "initial" else f"{title}_battle"
            fingerprint = (_fixture_sha256(root, case) if phase == "initial"
                           else hashlib.sha256(seeds[phase]).hexdigest())
            head = one(lines, "DUO_GEN2")
            want = {"player": player, "scenario": "gen2_reconnect", "title": title, "case": case,
                    "rom_sha1": lock[f"poke{title}"]["sha1"], "fixture_sha256": fingerprint}
            need(fingerprint and all(head.get(key) == value for key, value in want.items()),
                 f"{side}: header does not bind its fixture and ROM")
            verdicts = [line for line in lines if line.startswith("RESULT:")]
            need(not verdicts if side == "a" else
                 len(verdicts) == 1 and verdicts[0].split()[1:2] == ["PASS"], f"{side}: wrong RESULT contract")
            need(one(lines, "CLIENT").get("production_admitted") is True, f"{side}: no production client")
            one(lines, "BOOTED")
            one(lines, "HELLO")
            need(not any(line.startswith("HELLO_AGAIN ") for line in lines), f"{side}: repeated hello")
            if phase == "initial":
                save, ready = one(lines, "SAVE_WITNESS"), one(lines, "RECONNECT_READY")
                need(ready.get("key") == keys[player] and ready.get("phase") == "initial"
                     and ready.get("player") == player, f"{side}: wrong RECONNECT_READY")
                need(position(lines, "RECONNECT_READY") > position(lines, "SAVE_WITNESS"), "ready before save")
                if player == "a":
                    seed = seeds["same_save"]
                    need(len(seed) == save.get("saveram_bytes") == 32790, "same-save stage length differs")
                    snapshot_entry = (proof.get("witness_snapshots") or {}).get("a")
                    if snapshot_entry is not None or hashlib.sha256(seed[:32768]).hexdigest() != save.get("cartram_sha256"):
                        from server.adapters import gen2_codec as codec
                        from tools.gen2_duo_oracles import normalized_gameplay_cartram

                        need(snapshot_entry is not None, "same-save scratch change lacks authenticated witness snapshot")
                        baseline = pinned(snapshot_entry, binary=True)
                        need(len(baseline) in (32768, 32790)
                             and hashlib.sha256(baseline[:32768]).hexdigest() == save.get("cartram_sha256"),
                             "same-save witness snapshot does not bind initial raw CartRAM digest")
                        layout = codec.for_foundation(title)
                        need(normalized_gameplay_cartram(seed, layout) == normalized_gameplay_cartram(baseline, layout),
                             "same-save stage changed bytes outside native scratch")
                    need(not any(line.startswith("RECEIPT ") for line in lines), "killed initial A has receipt")
                else:
                    stayed = one(lines, "B_STAYED")
                    need(stayed.get("hellos") == 1 and stayed.get("force_faint") == 0
                         and stayed.get("box_mon") == 0, "B did not stay connected unchanged")
                    need(position(lines, "B_STAYED") > position(lines, "RECONNECT_READY"), "B_STAYED early")
                    tail = lines[position(lines, "RECONNECT_READY") + 1:]
                    need(not any(line.startswith(("RX force_faint", "RX box_mon")) for line in tail),
                         "B received destructive command")
            else:
                need(not any(line.startswith(("SAVE_WITNESS ", "ENGINE_CAPTURE ", "RECONNECT_READY ",
                                               "RX force_faint", "RX box_mon")) for line in lines),
                     f"{side}: relaunch emitted capture/save or destructive command")
                back = one(lines, "RECONNECT_HELLO")
                need(back.get("phase") == phase and back.get("expected_key") == keys["a"]
                     and back.get("linked") is (phase == "same_save") and back.get("hellos") == 1,
                     f"{side}: reconnect identity mismatch")
                need(position(lines, "RECONNECT_HELLO") > position(lines, "HELLO"), "reconnect before hello")
                if phase == "wrong_save":
                    hud = one(lines, "WRONG_SAVE_HUD")
                    received = [(i, json.loads(line[len("RX_TEXT "):])) for i, line in enumerate(lines)
                                if line.startswith("RX_TEXT ")]
                    wrong = [i for i, value in received if isinstance(value, dict)
                             and value.get("cmd") == "hud_show" and value.get("text") == "[x] WRONG SAVE: slot A"]
                    need(hud.get("text") == "[x] WRONG SAVE: slot A" and wrong, "missing wrong-save rejection HUD")
                    need(min(wrong) > position(lines, "HELLO")
                         and position(lines, "WRONG_SAVE_HUD") > position(lines, "RECONNECT_HELLO"), "HUD early")
                else:
                    need(not any(line.startswith("WRONG_SAVE_HUD ") for line in lines), "same save refused")
            if side != "a":
                receipt = one(lines, "RECEIPT")
                need(receipt.get("schema") == "gen2-duo-reconnect-v1" and receipt.get("phase") == phase
                     and all(receipt.get(key) == head.get(key) for key in (*want, "attempt")),
                     f"{side}: receipt does not bind header/phase")
                if phase != "initial":
                    need(receipt.get("expected_key") == keys["a"] and receipt.get("linked") is (phase == "same_save"),
                         f"{side}: receipt identity mismatch")
        tokens = _pydec_tokens(legs["pydec"])
        want = {"scenario": "gen2_reconnect", **keys, "area": "route_29", "status": "alive",
                "titles": f"{axes['initiator']}/{axes['partner']}"}
        need(tokens and all(tokens.get(key) == value for key, value in want.items()), "pydec does not bind reconnect cell")
        need(sum(line.startswith("PYDEC:") for line in legs["pydec"]) == 1, "ambiguous pydec verdict")
    except (KeyError, TypeError, ValueError, AttributeError, OSError, RuntimeError, StopIteration) as exc:
        return [f"reconnect proof invalid: {exc}"]
    return []


def _soft_reset_receipt_errors(lines: list[str], side: str) -> list[str]:
    """Check reset observations without inventing an ENGINE occurrence for the WRAM-clear path."""
    def need(condition, why):
        if not condition:
            raise ValueError(why)

    def one(tag):
        rows = [(i, line[len(tag) + 1:]) for i, line in enumerate(lines) if line.startswith(tag + " ")]
        need(len(rows) == 1, f"expected one {tag}")
        index, body = rows[0]
        row = json.loads(body)
        need(isinstance(row, dict), f"malformed {tag}")
        return index, row

    try:
        tags = ("DUO_GEN2", "CLIENT", "BOOTED", "HELLO", "SAVE_WITNESS", "RECEIPT")
        marks = {tag: one(tag) for tag in tags}
        a_only = ("HELLO_AT_CHECKPOINT", "CHORD_GATE", "CHORD", "RESET_SEEN", "HELLO_CLEARED",
                  "WRITES_PAUSED", "REBOOTED", "WRITES_RESUMED", "HELLO_AGAIN", "REHELLO", "NO_WRITES_IN_WINDOW")
        if side == "a":
            marks.update({tag: one(tag) for tag in a_only})
        else:
            need(not any(line.split(" ", 1)[0] in a_only for line in lines), "idle B emitted reset/rehello marker")
            marks["IDLE_PARTNER"] = one("IDLE_PARTNER")

        def value(tag):
            return marks[tag][1]

        def after(later, earlier):
            need(marks[later][0] > marks[earlier][0], f"{later} before {earlier}")
            if "frame" in value(later) and "frame" in value(earlier):
                need(type(value(later)["frame"]) is int and type(value(earlier)["frame"]) is int
                     and value(later)["frame"] >= value(earlier)["frame"], f"{later} frame before {earlier}")

        def delta(tag, start, low, high):
            row, baseline = value(tag), value(start)
            need(type(row.get("frame")) is int and type(baseline.get("frame")) is int
                 and type(row.get("delta")) is int and row["delta"] == row["frame"] - baseline["frame"]
                 and low <= row["delta"] <= high, f"{tag} inconsistent/out-of-bounds delta")

        need(value("CLIENT").get("production_admitted") is True, "no production client")
        need(not any(line.startswith(("ENGINE_CAPTURE ", "ENGINE_SOFT_RESET ")) for line in lines),
             "soft reset receipt must not substitute an engine occurrence")
        hello, save, receipt, head = (value(tag) for tag in ("HELLO", "SAVE_WITNESS", "RECEIPT", "DUO_GEN2"))
        need(type(hello.get("ot_id")) is int and 0 < hello["ot_id"] <= 65535, "hello has no live OT")
        digest = save.get("cartram_sha256")
        need(save.get("flushed_matches") is True and save.get("cartram_bytes") == 32768
             and isinstance(digest, str) and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
             and type(save.get("gate_saves")) is int and save["gate_saves"] >= 1
             and type(save.get("client_saves")) is int and save["client_saves"] >= 1, "incomplete native save")
        after("RECEIPT", "SAVE_WITNESS")
        need(receipt.get("schema") == "gen2-duo-soft-reset-v1"
             and all(receipt.get(key) == head.get(key) for key in
                     ("player", "scenario", "attempt", "case", "title", "rom_sha1", "fixture_sha256"))
             and receipt.get("hello") == hello and receipt.get("save") == save
             and receipt.get("client") == value("CLIENT"), "receipt does not bind its markers/header")
        if side == "a":
            at = value("HELLO_AT_CHECKPOINT")
            need(at.get("hellos") == 1 and at.get("writes_enabled") is True
                 and at.get("ot_id") == hello["ot_id"], "reset checkpoint not initially admitted")
            for later, earlier in (("HELLO_AT_CHECKPOINT", "HELLO"), ("CHORD_GATE", "HELLO_AT_CHECKPOINT"),
                    ("CHORD", "CHORD_GATE"), ("RESET_SEEN", "CHORD"), ("HELLO_CLEARED", "RESET_SEEN"),
                    ("WRITES_PAUSED", "RESET_SEEN"), ("REBOOTED", "HELLO_CLEARED"), ("REBOOTED", "WRITES_PAUSED"),
                    ("WRITES_RESUMED", "REBOOTED"), ("HELLO_AGAIN", "WRITES_PAUSED"), ("REHELLO", "REBOOTED"),
                    ("REHELLO", "HELLO_AGAIN"), ("NO_WRITES_IN_WINDOW", "REHELLO"),
                    ("SAVE_WITNESS", "NO_WRITES_IN_WINDOW")):
                after(later, earlier)
            need(type(value("CHORD").get("frames")) is int and value("CHORD")["frames"] >= 1, "empty chord")
            delta("RESET_SEEN", "CHORD", 30, 60)
            delta("HELLO_CLEARED", "RESET_SEEN", 0, 180)
            delta("WRITES_PAUSED", "RESET_SEEN", 180, 420)
            resumed = value("WRITES_RESUMED")
            need(type(resumed.get("delta")) is int
                 and resumed["delta"] == resumed["frame"] - value("RESET_SEEN")["frame"], "resume delta differs")
            need(value("HELLO_AGAIN").get("n") == value("REHELLO").get("hellos") == 2
                 and value("HELLO_AGAIN").get("ot_id") == value("REHELLO").get("ot_id") == hello["ot_id"],
                 "rehello count or OT differs")
            need(value("NO_WRITES_IN_WINDOW").get("writes") == 0, "writes occurred in reset window")
            need(type(save.get("save_completed_frame")) is int
                 and save["save_completed_frame"] > value("REHELLO")["frame"], "save completed before rehello")
            need(receipt.get("reset") == value("RESET_SEEN") and receipt.get("paused") == value("WRITES_PAUSED")
                 and receipt.get("rehello") == value("REHELLO"), "receipt reset detail differs")
        else:
            need(value("IDLE_PARTNER").get("hellos") == 1, "idle partner hello count differs")
            after("IDLE_PARTNER", "HELLO")
            after("SAVE_WITNESS", "IDLE_PARTNER")
            need(receipt.get("idle") == value("IDLE_PARTNER"), "receipt idle detail differs")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        return [f"{side} soft-reset receipt invalid: {exc}"]
    return []


def _clause_cell_errors(legs: dict, scenario: str, axes: dict) -> list[str]:
    """Only observed clause branches qualify; bind the PYDEC facts to the saved driver evidence."""
    kind = scenario.removeprefix("gen2_").removesuffix("_clause")

    def need(condition, why):
        if not condition:
            raise ValueError(why)

    def rows(side, tag):
        found = [(i, json.loads(line[len(tag) + 1:])) for i, line in enumerate(legs[side])
                 if line.startswith(tag + " ")]
        need(all(isinstance(row, dict) for _, row in found), f"malformed {side} {tag}")
        return found

    def one(side, tag):
        found = rows(side, tag)
        need(len(found) == 1, f"expected one {side} {tag}")
        return found[0]

    try:
        caps = {side: one(side, "ENGINE_CAPTURE")[1] for side in ("a", "b")}
        receipts = {}
        verdicts = {}
        for side in ("a", "b"):
            cap, head = caps[side], one(side, "DUO_GEN2")[1]
            save_at, save = one(side, "SAVE_WITNESS")
            receipt_at, receipt = one(side, "RECEIPT")
            receipts[side] = receipt
            need(one(side, "CLIENT")[1].get("production_admitted") is True, "clause client not admitted")
            need(cap.get("area_id") == "route_29" and isinstance(cap.get("key"), str) and cap["key"], "wrong capture area/key")
            need(receipt_at > save_at and receipt.get("schema") == f"gen2-duo-{kind}-clause-v1"
                 and receipt.get("save") == save and receipt.get("capture") == cap and receipt.get("key") == cap["key"]
                 and receipt.get("species_id") == cap.get("species_id")
                 and all(receipt.get(key) == head.get(key) for key in
                         ("player", "scenario", "attempt", "case", "title", "rom_sha1", "fixture_sha256")),
                 "clause receipt does not bind header/capture/final save")
            need(type(save.get("gate_saves")) is int and save["gate_saves"] >= 2
                 and type(save.get("client_saves")) is int and save["client_saves"] >= 2
                 and save.get("flushed_matches") is True and save.get("cartram_bytes") == 32768,
                 "clause final second native save missing")
            digest = save.get("cartram_sha256")
            need(isinstance(digest, str) and len(digest) == 64
                 and all(c in "0123456789abcdef" for c in digest), "clause final save digest missing")
            last_tag = "LINKED" if kind == "species" else "CLAUSE_VERDICT"
            outcome_at, outcome = one(side, last_tag)
            need(save_at > outcome_at and type(save.get("save_completed_frame")) is int
                 and type(outcome.get("frame")) is int and save["save_completed_frame"] > outcome["frame"],
                 "clause final save precedes outcome")
            if kind != "species":
                cc_at, cc = one(side, "CLAUSE_CAPTURE")
                need(cc_at < outcome_at and all(cc.get(key) == cap.get(key) for key in ("key", "species_id", "area_id")),
                     "clause capture differs from engine")
                verdict = outcome.get("verdict")
                verdicts[side] = verdict
                need(verdict in ("rejected", "partner_rejected") and receipt.get("verdict") == verdict
                     and receipt.get("clause") == kind and receipt.get("path") == "clause_observed",
                     "clause rejection unobserved")
                if verdict == "rejected":
                    mon_at, mon = one(side, "REJECTED_MON")
                    ack_at, ack = one(side, "MEMORIAL_ACK")
                    writes = rows(side, "PARTY_HP_WRITE")
                    need(writes and all(value.get("key") == cap["key"] and value.get("ok") is True
                                        and at < mon_at for at, value in writes), "rejected mon lacks successful production write")
                    need(ack_at < mon_at < save_at and mon.get("key") == ack.get("key") == cap["key"]
                         and save["save_completed_frame"] > mon["frame"], "rejected ending not saved")
                    ending = mon.get("ending")
                    need(receipt.get("ending") == ending and (
                        ending == "dead" and ack.get("event") == "memorialize_failed"
                        and mon.get("in_party") is True and mon.get("hp") == 0 or
                        ending == "memorial" and ack.get("event") == "memorialize_done"
                        and mon.get("in_party") is False and mon.get("box") == ack.get("box") == 13),
                        "rejected ending disagrees with memorial acknowledgement")
                else:
                    need(not rows(side, "REJECTED_MON"), "partner marked rejected")
        tokens = _pydec_tokens(legs["pydec"])
        want = {"scenario": scenario, "a": caps["a"]["key"], "b": caps["b"]["key"], "area": "route_29",
                "titles": f"{axes['initiator']}/{axes['partner']}", "clause": kind}
        if kind != "species":
            need(sorted(verdicts.values()) == ["partner_rejected", "rejected"], "clause requires one rejected half")
            rejected = next(side for side in verdicts if verdicts[side] == "rejected")
            want.update(status="clause_observed", rejected=rejected, ending=receipts[rejected]["ending"])
        else:
            pending_at, pending = one("a", "PENDING_CAPTURE")
            need(pending_at > one("a", "ENGINE_CAPTURE")[0] and pending_at < one("a", "LINKED")[0]
                 and all(pending.get(key) == caps["a"].get(key) for key in ("key", "species_id", "area_id"))
                 and receipts["a"].get("role") == receipts["a"].get("path") == "pending", "invalid pending capture")
            ap_at, ap = one("b", "A_PENDING")
            need(ap.get("species_id") == caps["a"]["species_id"] != caps["b"]["species_id"], "reroll does not bind partner species")
            encounters, rerolls = rows("b", "ENCOUNTER"), rows("b", "REROLL")
            need(len(encounters) >= 2 and len(rerolls) == len(encounters) - 1, "species reroll unobserved")
            need(receipts["b"].get("role") == "reroller" and receipts["b"].get("path") == "reroll_observed"
                 and receipts["b"].get("rerolls") == len(rerolls)
                 and receipts["b"].get("dupe_species") == ap["species_id"], "species receipt does not bind rerolls")
            for i, (at, encounter) in enumerate(encounters):
                dupe = i < len(rerolls)
                species = ap["species_id"] if dupe else caps["b"]["species_id"]
                need(at > ap_at and encounter.get("n") == i + 1 and encounter.get("dupe") is dupe
                     and encounter.get("species_id") == species, "encounter species/order differs")
                if dupe:
                    rr_at, rr = rerolls[i]
                    need(at < rr_at < encounters[i + 1][0] and rr.get("n") == i + 1
                         and rr.get("species_id") == species, "reroll order/species differs")
                    prompt = rr.get("prompt")
                    # Native intro can prompt before ENCOUNTER; never reuse the prior battle's prompt.
                    prompt_start = ap_at if i == 0 else rerolls[i - 1][0]
                    need(isinstance(prompt, str) and prompt.startswith("Dupes clause: ") and prompt.endswith(" -- reroll!")
                         and any(prompt_start < rx_at < rr_at and rx.get("cmd") == "gui_prompt" and rx.get("text") == prompt
                                 for rx_at, rx in rows("b", "RX_TEXT")), "reroll lacks observed server prompt")
            need(encounters[-1][0] < one("b", "ENGINE_CAPTURE")[0], "catch precedes final encounter")
            want.update(status="alive", rerolls=str(len(rerolls)))
        need(tokens and all(tokens.get(key) == value for key, value in want.items()), "pydec does not bind observed clause cell")
    except (KeyError, TypeError, ValueError, AttributeError, StopIteration) as exc:
        return [f"clause proof invalid: {exc}"]
    return []


def _memorial_receipt_errors(lines: list[str], side: str) -> list[str]:
    """Box records have no HP: memorial qualification needs the actual HP-zero party preimage."""
    def need(condition, why):
        if not condition:
            raise ValueError(why)

    def one(tag):
        found = [(i, json.loads(line[len(tag) + 1:])) for i, line in enumerate(lines)
                 if line.startswith(tag + " ")]
        need(len(found) == 1, f"expected one {tag}")
        need(isinstance(found[0][1], dict), f"malformed {tag}")
        return found[0]

    try:
        pre_at, pre = one("MEMORIAL_PREIMAGE")
        ack_at, ack = one("MEMORIAL_ACK")
        save_at, save = one("SAVE_WITNESS")
        _, cap = one("ENGINE_CAPTURE")
        _, head = one("DUO_GEN2")
        from server.adapters import gen2_codec as codec

        layout = codec.for_foundation(head["title"])
        mon = codec.decode_party_mon(bytes.fromhex(pre["raw_hex"]), layout,
            species_marker=pre["species_marker"], ot=bytes.fromhex(pre["ot_raw_hex"]),
            nickname=bytes.fromhex(pre["nickname_raw_hex"]))
        need(codec.key(mon) == pre.get("key") == cap.get("key") and mon["hp"] == 0
             and mon["species_id"] == cap.get("species_id") and not mon["is_egg"],
             "preimage is not the captured HP-zero party mon")
        need(type(pre.get("slot")) is int and 0 <= pre["slot"] < layout.constants["PARTY_LENGTH"],
             "preimage party slot invalid")
        need(ack.get("event") == "memorialize_done" and ack.get("key") == cap["key"]
             and type(ack.get("box")) is int and ack["box"] == layout.constants["NUM_BOXES"] - 1 == 13,
             "successful Box 14 memorial acknowledgement missing")
        need(pre_at < ack_at < save_at and type(pre.get("frame")) is int and type(ack.get("frame")) is int
             and type(save.get("save_completed_frame")) is int
             and pre["frame"] <= ack["frame"] < save["save_completed_frame"], "preimage/ack/final-save chronology differs")
        for i, line in enumerate(lines):
            if line.startswith("PARTY_HP_WRITE "):
                write = json.loads(line[len("PARTY_HP_WRITE "):])
                need(i < pre_at and type(write.get("frame")) is int and write["frame"] <= pre["frame"],
                     "HP write after memorial preimage")
    except (KeyError, TypeError, ValueError, AttributeError, OSError) as exc:
        return [f"{side} memorial receipt invalid: {exc}"]
    return []


def _receipt_errors(root: Path, proof: dict, scenario: str, axes: dict, lock: dict) -> list[str]:
    """One registered proof: pinned bytes, PASS verdicts, and headers naming this exact cell."""
    if scenario == "gen2_reconnect":
        return _reconnect_receipt_errors(root, proof, axes, lock)
    errors = []
    receipts = proof.get("receipts") or {}
    titles = {"a": axes["initiator"], "b": axes["partner"]}
    capture_keys = {}
    legs = {}
    for side in ("a", "b", "pydec"):
        entry = receipts.get(side)
        if not entry:
            errors.append(f"{side} receipt not registered")
            continue
        path = root / entry["path"]
        if not path.is_file():
            errors.append(f"{side} receipt {entry['path']} missing")
            continue
        raw = path.read_bytes().replace(b"\r\n", b"\n")
        if hashlib.sha256(raw).hexdigest() != entry.get("sha256"):
            errors.append(f"{side} receipt {entry['path']} sha256 differs from its pin")
            continue
        lines = raw.decode("utf-8", errors="replace").splitlines()
        legs[side] = lines
        prefix = "PYDEC:" if side == "pydec" else "RESULT:"
        verdicts = [line.split()[1:2] for line in lines if line.startswith(prefix)]
        if not verdicts or any(verdict != ["PASS"] for verdict in verdicts):
            errors.append(f"{side} receipt has no {prefix} PASS verdict, or a non-PASS one")
        if side == "pydec":
            errors.extend(_pydec_cell_errors(lines, scenario, axes, capture_keys, lock))
            continue
        capture_keys[side] = _engine_capture_key(lines)
        title = titles[side]
        lock_key = f"poke{title}"
        refused = scenario == "gen2_admit_wrong_rom" and side == "b"
        if refused:
            title, lock_key = "crystal", "pokecrystal11"
        if lock_key not in lock:
            errors.append(f"{side}: axes title {title!r} has no {lock_key!r} entry in "
                          f"data/gen2_sources.lock.json")
            continue
        want = {"player": side, "scenario": scenario, "case": axes["fixtures"][side], "title": title,
                "rom_sha1": lock[lock_key].get("sha1"),
                "fixture_sha256": _fixture_sha256(root, axes["fixtures"][side])}
        if refused:
            want = {"player": side, "scenario": scenario, "title": title,
                    "rom_sha1": lock[lock_key].get("sha1"), "expect_admission": "refused"}
        headers = [line[len("DUO_GEN2 "):] for line in lines if line.startswith("DUO_GEN2 ")]
        try:
            header = json.loads(headers[0]) if len(headers) == 1 else None
        except ValueError:
            header = None
        if not isinstance(header, dict) or any(header.get(key) != value for key, value in want.items()):
            errors.append(f"{side} receipt header does not name {want}")
        if refused:
            errors.extend(_refused_receipt_errors(lines, lock[lock_key].get("sha1")))
        elif not any(line.startswith("SAVE_WITNESS ") for line in lines):
            errors.append(f"{side} receipt has no SAVE_WITNESS line")
        if scenario == "gen2_soft_reset":
            errors.extend(_soft_reset_receipt_errors(lines, side))
    if scenario in ("gen2_species_clause", "gen2_type_clause", "gen2_gender_clause"):
        errors.extend(_clause_cell_errors(legs, scenario, axes))
    tokens = _pydec_tokens(legs.get("pydec", [])) or {}
    memorial_sides = ()
    if scenario == "gen2_faint" and tokens.get("status") == "memorial":
        memorial_sides = ("a", "b")
    elif scenario in ("gen2_type_clause", "gen2_gender_clause") and tokens.get("ending") == "memorial":
        memorial_sides = (tokens.get("rejected"),)
    for side in memorial_sides:
        errors.extend(_memorial_receipt_errors(legs.get(side, []), side))
    return errors


def duo_matrix_errors(root: Path | None = None, duo=None) -> list[str]:
    """Every gap in the release duo matrix, one message per gap; [] only when fully receipted.

    Registry side (tools/e2e_duo.py): every Gen 2 pairing is declared, every scenario it
    registers is in the matrix, and each has a post-result oracle under a require_oracle
    evidence contract. Evidence side: each cell has pinned PASS receipts for its own pair."""
    root = ROOT if root is None else root
    if duo is None:
        import e2e_duo as duo
    doc = json.loads((root / DUO_MATRIX).read_text(encoding="utf-8"))
    lock = json.loads((root / "data/gen2_sources.lock.json").read_text(encoding="utf-8"))["outputs"]
    rows = [row for row in doc.get("requirements", []) if row.get("stage") == "live-duos"]
    errors = []
    # .get(): a malformed row (missing "axes"/"initiator"/etc.) surfaces as a pairs mismatch here,
    # never a crash -- the per-row loop below gives it its own dedicated "malformed row" message too.
    pairs = sorted((((row.get("axes") or {}).get("initiator"), (row.get("axes") or {}).get("partner"))
                   for row in rows), key=str)  # str key: a malformed row's None must not crash the sort
    if pairs != sorted(DUO_PAIRS):
        errors.append(f"release matrix pairs {pairs} != required {sorted(DUO_PAIRS)}")
    declared = {row.get("axes", {}).get("pairing") for row in rows}
    errors.extend(f"{game}: Gen 2 duo pairing in tools/e2e_duo.py is not in the release matrix"
                  for game in duo.GAMES
                  if duo.scenario_family(game) == "gen2_new" and game not in declared)
    for row in rows:
        try:
            rid, axes = row["id"], row["axes"]
            game, scenarios = axes["pairing"], axes.get("scenarios") or []
            missing_required = DUO_REQUIRED_SCENARIOS - set(scenarios)
            if missing_required:
                errors.append(f"{rid}: required scenario(s) {sorted(missing_required)} not declared")
            registered = []
            if game not in duo.GAMES or duo.scenario_family(game) != "gen2_new":
                errors.append(f"{rid}: pairing {game} is not a gen2_new row in tools/e2e_duo.py")
            else:
                registered = duo.scenarios_for(game)
                if duo.GAMES[game].get("fixture") != axes["fixtures"]:
                    errors.append(f"{rid}: tools/e2e_duo.py {game} fixtures "
                                  f"{duo.GAMES[game].get('fixture')} != matrix {axes['fixtures']}")
                try:
                    if not duo.evidence_contract(game).require_oracle:
                        errors.append(f"{rid}: {game} evidence contract does not require an oracle")
                except RuntimeError as exc:
                    errors.append(f"{rid}: {exc}")
                errors.extend(f"{rid}: registered scenario {name} is not in the release matrix"
                              for name in registered if name not in scenarios)
            # F4 (review O16): a scenario proof-listed twice, or naming a scenario axes.scenarios
            # never declared, is reported -- a dict comprehension would silently keep only one.
            proof_list = row.get("proofs", [])
            proof_names = [proof.get("scenario") for proof in proof_list]
            dupes = sorted({name for name in proof_names if proof_names.count(name) > 1}, key=str)
            if dupes:
                errors.append(f"{rid}: duplicate proof scenario(s) {dupes}")
            undeclared = sorted({name for name in proof_names if name not in scenarios}, key=str)
            if undeclared:
                errors.append(f"{rid}: proof scenario(s) {undeclared} not declared in axes.scenarios")
            proofs = {}
            for proof in proof_list:
                proofs.setdefault(proof.get("scenario"), proof)
            for name in scenarios:
                cell = f"{rid}/{name}"
                if name not in registered:
                    errors.append(f"{cell}: scenario not registered for {game} in tools/e2e_duo.py")
                else:
                    oracle = duo.SCENARIOS[name].get("oracle")
                    if not oracle or not callable(getattr(duo.DuoRun, oracle, None)):
                        errors.append(f"{cell}: no post-result oracle ({oracle!r})")
                if name not in proofs:
                    errors.append(f"{cell}: no receipt registered (an empty proof is a release blocker)")
                    continue
                errors.extend(f"{cell}: {problem}"
                              for problem in _receipt_errors(root, proofs[name], name, axes, lock))
        except (KeyError, TypeError, AttributeError) as exc:
            # F5 (review O16): a malformed row is its own red gap, never an uncaught crash that
            # takes the whole matrix (and every other row's real gaps) down with it.
            cell = row.get("id", "<row without id>") if isinstance(row, dict) else "<malformed row>"
            errors.append(f"{cell}: malformed row: {exc!r}")
    return errors


def _duo_matrix_main() -> int:
    errors = duo_matrix_errors()
    for error in errors:
        print(f"RED  {error}")
    if errors:
        print(f"duo matrix: {len(errors)} gap(s); a missing pair/scenario/oracle/receipt is not a pass")
        return 1
    print("duo matrix: every pair x scenario cell RECEIPTED")
    return 0


NEW_GATES = "tests/gen2_live_gate_requirements.json"


def _new_gate_receipt(root: Path, entry: dict) -> tuple[dict | None, str | None]:
    """The receipt at entry['path'], loaded only after its bytes match entry['sha256'] (CRLF->LF)."""
    path = root / entry["path"]
    if not path.is_file():
        return None, f"{entry['path']} missing"
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(raw).hexdigest() != entry.get("sha256"):
        return None, f"{entry['path']} sha256 differs from its pin"
    return json.loads(raw.decode("utf-8")), None


def _qualification_row_errors(root: Path, fixture: str, receipt: dict) -> list[str]:
    """A committed *.qualification.json report: passed, and still binding the staged fixture's bytes.

    `physical_qualification` is never true on ANY qualification report by design (tools/gen2_fixtures.py
    qualify()/qualification_report(): "the report never claims physical qualification" -- it always
    stamps False pending a separate coordinator sign-off), so it is not a pass/fail signal here."""
    errors = []
    if not receipt.get("passed") or receipt.get("errors"):
        errors.append("fixture qualification receipt is not a passed run")
    rows = receipt.get("fixtures") or []
    if not rows or rows[0].get("name") != fixture or not rows[0].get("passed"):
        errors.append(f"qualification report does not confirm {fixture} passed")
        return errors
    saveram = root / "tests/fixtures/gen2" / f"{fixture}.SaveRAM"
    want = (rows[0].get("artifacts") or {}).get("fixture", {}).get("sha256")
    if not saveram.is_file():
        errors.append(f"{fixture}.SaveRAM missing")
    elif want and hashlib.sha256(saveram.read_bytes()).hexdigest() != want:
        errors.append(f"{fixture}.SaveRAM does not match the bytes its qualification receipt covers")
    return errors


def _overlay_gate_errors(root: Path, title: str, receipt: dict, schema: str, what: str) -> list[str]:
    """A PHYSICAL PASS of `schema` on the overlay build that is published NOW (data/gen2/overlay_provenance.json),
    from the committed fixture's bytes. A rebuilt overlay makes the receipt stale until the gate is re-run."""
    errors = []
    if (receipt.get("schema") != schema or receipt.get("result") != "PASS"
            or receipt.get("evidence_level") != "PHYSICAL" or receipt.get("title") != title):
        errors.append(f"{what} receipt is not a PHYSICAL PASS for {title}")
    provenance = root / "data/gen2/overlay_provenance.json"
    outputs = json.loads(provenance.read_text(encoding="utf-8"))["outputs"] if provenance.is_file() else {}
    published = next((row.get("sha1") for row in outputs.values() if row.get("slink_title") == title), None)
    if published is None or receipt.get("overlay_sha1") != published:
        errors.append(f"{what} receipt proves another overlay build than the published one")
    fixture, want = receipt.get("fixture"), receipt.get("fixture_sha256")
    # Both present first: a missing fixture and a missing hash must not compare None == None.
    if (not isinstance(fixture, str) or not fixture or not isinstance(want, str) or not want
            or _fixture_sha256(root, fixture) != want):
        errors.append(f"{what} receipt does not bind the committed fixture's bytes")
    return errors


def _panel_gate_row_errors(root: Path, title: str, receipt: dict) -> list[str]:
    """P4.1g (tests/live/test_gen2_panel_gate.py): the overlay gate binding plus a positive minimum-SP margin."""
    errors = _overlay_gate_errors(root, title, receipt, "gen2-panel-gate-v1", "panel gate")
    margin = (receipt.get("minimum_sp") or {}).get("margin_bytes")
    if type(margin) is not int or margin <= 0:
        errors.append("panel gate receipt has no positive minimum-SP margin")
    return errors


# P4.2c (tests/live/test_gen2_sfx_gate.py): every context the plan names (N-2), each played in its deadline.
SFX_GATE_CONTEXTS = ("idle_1", "idle_2", "idle_3", "idle_4", "movement", "transition", "start_menu", "text",
                     "battle_anim", "battle_menu")


def _sfx_gate_row_errors(root: Path, title: str, receipt: dict) -> list[str]:
    """P4.2c: the overlay gate binding, every sound context PASS within its deadline (the transition held
    through its fade, the battle's worst no-service stretch in bound) and the reset drop."""
    errors = _overlay_gate_errors(root, title, receipt, "gen2-sfx-gate-v1", "sfx gate")
    contexts, deadline = receipt.get("contexts") or {}, receipt.get("deadline_frames")
    for name in SFX_GATE_CONTEXTS:
        c = contexts.get(name) or {}
        played, posted = c.get("played"), c.get("posted")
        start = c.get("fade_end") if name == "transition" else posted
        if (c.get("result") != "PASS" or type(deadline) is not int or type(played) is not int
                or type(start) is not int or not 0 <= played - start <= deadline):
            errors.append(f"sfx gate context {name} did not play within its deadline")
    gap = (contexts.get("battle_anim") or {}).get("battle_service_gap")
    if type(gap) is not int or type(deadline) is not int or not 0 < gap <= deadline:
        errors.append("sfx gate battle worst-case service gap is missing or past the deadline")
    reset = receipt.get("reset") or {}
    if (reset.get("result") != "PASS" or reset.get("pending_at_entry") is not True
            or reset.get("played_id") is not None or reset.get("on_channel") is not None):
        errors.append("sfx gate reset did not drop a pending request")
    return errors


def new_gates_errors(root: Path | None = None, receipt_validate=None) -> list[str]:
    """Every gap in the live-new-gates lane's non-emulator evidence: U1 engine-site, U2 write-window
    (Silver via O-23) and fixture-qualification receipts, each pinned by sha256. An empty proof is a
    release blocker. R-1/R-2/R-3/R-4/R-5g are NOT covered here -- they have no committed receipt and
    still need a fresh live run (see tests/gen2_live_gate_requirements.json's scope=).

    engine_sites/write_window rows are handed to tests/unit/test_gen2_physical_receipts.py's own
    `validate()` (N18) instead of re-deriving PASS through the Lua modules a second time; that function
    is also what makes the Silver-via-O-23 row red the moment Gold's and Silver's checkpoint rows
    differ (M.qualified compares receipt.checkpoint against Silver's own pack)."""
    root = ROOT if root is None else root
    path = root / NEW_GATES
    if not path.is_file():
        return [f"{NEW_GATES} missing"]
    if receipt_validate is None:
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from tests.unit.test_gen2_physical_receipts import validate as receipt_validate
    doc = json.loads(path.read_text(encoding="utf-8"))
    errors = []
    for row in doc.get("requirements", []):
        rid, axes, kind = row["id"], row["axes"], row["axes"]["kind"]
        proofs = row.get("proofs") or []
        if not proofs:
            errors.append(f"{rid}: no receipt registered (an empty proof is a release blocker)")
            continue
        for proof in proofs:
            entry = (proof.get("receipts") or {}).get("receipt")
            if not entry:
                errors.append(f"{rid}: receipt not registered")
                continue
            receipt, why = _new_gate_receipt(root, entry)
            if receipt is None:
                errors.append(f"{rid}: {why}")
            elif kind in ("engine_sites", "write_window"):
                proven, why = receipt_validate(kind, axes["title"], receipt)
                if proven is None:
                    errors.append(f"{rid}: {why}")
            elif kind == "qualification":
                errors.extend(f"{rid}: {e}" for e in _qualification_row_errors(root, axes["fixture"], receipt))
            elif kind == "panel_gate":
                errors.extend(f"{rid}: {e}" for e in _panel_gate_row_errors(root, axes["title"], receipt))
            elif kind == "sfx_gate":
                errors.extend(f"{rid}: {e}" for e in _sfx_gate_row_errors(root, axes["title"], receipt))
            else:
                errors.append(f"{rid}: no validator for receipt kind {kind!r}")
    return errors


def _new_gates_main() -> int:
    errors = new_gates_errors()
    for error in errors:
        print(f"RED  {error}")
    if errors:
        print(f"new gates: {len(errors)} gap(s); a missing/edited/unproven receipt is not a pass")
        return 1
    print("new gates: every engine-site, write-window and qualification receipt bound and PHYSICAL")
    return 0


def manifest_errors() -> list[str]:
    """Check declarations, not file availability or evidence qualification."""
    names = [lane.name for lane in LANES]
    errors = []
    if len(names) != len(set(names)):
        errors.append("duplicate lane names")
    if set(names) != _REQUIRED_LANES:
        errors.append("missing or unexpected required lanes")
    if set(REQUIREMENTS) != set(names) or set(PREREQUISITES) != set(names):
        errors.append("lane requirements/prerequisites do not match the manifest")
    for name in names:
        ids = REQUIREMENTS.get(name, [])
        if not ids or len(ids) != len(set(ids)) or set(ids) != _REQUIRED_MAPPINGS.get(name):
            errors.append(f"{name}: missing, duplicate or unexpected requirement mapping")
    if not set(names) >= _SLOW or not set(names) >= set(UNIMPLEMENTED):
        errors.append("unknown slow/unimplemented lane")
    for lane in LANES:
        if not lane.argv and lane.name not in UNIMPLEMENTED:
            errors.append(f"{lane.name}: no executable binding")
        if lane.is_pytest:
            options = lane.argv[lane.argv.index("pytest") + 1:]
            if any(arg in ("-k", "-m") or arg.startswith(("--deselect", "-k="))
                   for arg in options):
                errors.append(f"{lane.name}: pytest deselection is not lane coverage")
    return errors


def run_lane(lane: Lane, quiet: bool) -> tuple[bool, str]:
    """Bind prerequisites and zero skip exemptions; share execution and accounting."""
    if lane.name in UNIMPLEMENTED:
        return False, f"UNIMPLEMENTED: {UNIMPLEMENTED[lane.name]}"
    if lane.name == "live-new-gates":
        gaps = new_gates_errors()
        if gaps:
            return False, "; ".join(gaps)
    if lane.name not in PREREQUISITES:
        return False, "undeclared lane prerequisites"
    paths = list(PREREQUISITES[lane.name])
    if lane.is_pytest:
        paths.extend(arg.split("::", 1)[0] for arg in lane.argv if arg.startswith("tests/"))
    elif len(lane.argv) >= 2:
        paths.append(lane.argv[1])
    missing = [path for path in paths if not (ROOT / path).exists()]
    if missing:
        return False, "missing prerequisites: " + ", ".join(dict.fromkeys(missing))
    try:
        return release_lanes.run_lane(lane, quiet, ALLOWED_SKIPS)
    except OSError as exc:
        return False, f"cannot execute lane: {exc}"


def main(argv: list[str] | None = None) -> int:
    given = sys.argv[1:] if argv is None else argv
    if given == ["--duo-matrix"]:
        return _duo_matrix_main()
    if given == ["--new-gates"]:
        return _new_gates_main()
    errors = manifest_errors()
    if errors:
        print("Gen 2 manifest invalid: " + "; ".join(errors), file=sys.stderr)
        return 1
    return release_lanes.run_gate(
        title="Gen 2 release gate", lanes=LANES, requirements=REQUIREMENTS,
        slow=_SLOW, run_lane=run_lane, description=__doc__, argv=argv,
    )


if __name__ == "__main__":
    sys.exit(main())
