"""T5 private FireRed trade inputs and independent physical-evidence oracles.

No emulator is launched here. Candidate admission is a HARNESS_ONLY projection;
the ordinary production pack and the producer's production:false receipt stay
unchanged. Only e2e_duo's explicit candidate row exports the override nonce.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import struct
import subprocess
import uuid
from pathlib import Path

from server.adapters import gen3_codec as codec
from server.adapters.gen3_rom_tables import decode_rom_tables
from tools.gen_gen3_profile import native_abi

ENV = "SLINK_DUO_FR_TRADE_CANDIDATE"
DISCLOSURE = "candidate admission only; native NPC/chooser/offer evidence required"
SCHEMA = "slink-frlg-native-carrier-v3"
ROM_BASE = 0x08000000
SOURCE_FILES = (
    "tools/gen3_trade_duo.py",
    "tools/e2e_duo.py",
    "lua/gen3/run.lua",
    "lua/gen3/entry.lua",
    "lua/gen3/client.lua",
    "lua/gen3/reads.lua",
    "lua/core/session.lua",
    "lua/owed_reports.lua",
    "lua/gen3/signals.lua",
    "lua/gen3/native.lua",
    "lua/gen3/safety.lua",
    "lua/gen3/writes.lua",
    "lua/gen3/trade.lua",
    "lua/gen3/trade_journal.lua",
    "lua/gen3/rom_content.lua",
    "lua/tests/duo/gen3_trade_candidate.lua",
    "lua/tests/duo/gen3_trade_driver.lua",
    "lua/tests/duo/duo_gen3_main.lua",
    "lua/tests/duo/scenario_gen3_native_trade.lua",
    "data/games/gen3_frlg/profile.json",
    "data/games/gen3_frlg/engine_signals.json",
    "data/games/gen3_frlg/write_checkpoint.json",
    "patch/src/trade_targets/abi.h",
    "patch/src/trade_targets/native_carrier.h",
    "patch/src/trade_targets/carrier_producer.h",
    "patch/src/trade_targets/firered.h",
    "patch/src/trade_targets/leafgreen.h",
    "data/gen3/pret/pokefirered.sym",
    "data/gen3/pret/pokeleafgreen.sym",
)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha1_file(root: Path, relative: str) -> str:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("T5 integrity path escaped the lane")
    return hashlib.sha1(path.read_bytes()).hexdigest()


def validate_prepared(root: Path, manifest: dict) -> None:
    """Refuse stale/tampered files before any emulator can consume them."""
    if manifest.get("schema") != SCHEMA:
        raise ValueError("stale T5 manifest: regenerate private packs")
    if set(manifest.get("source_sha1", {})) != set(SOURCE_FILES):
        raise ValueError("stale T5 manifest: missing source digests")
    if set(manifest.get("pack_sha1", {})) != {"profile", "sites", "checkpoint"}:
        raise ValueError("stale T5 manifest: missing pack digests")
    if _sha1_file(root, manifest["path"]) != manifest.get("manifest_sha1"):
        raise ValueError("stale T5 manifest digest")
    for path, expected in manifest["source_sha1"].items():
        if _sha1_file(root, path) != expected:
            raise ValueError(f"stale T5 source digest: {path}")
    for name, expected in manifest["pack_sha1"].items():
        if _sha1_file(root, manifest["pack_files"][name]) != expected:
            raise ValueError(f"stale T5 private pack digest: {name}")
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if head != manifest.get("source_commit"):
        raise ValueError("stale T5 source commit: regenerate private packs")


def candidate_inputs(root: Path, title: str = "firered") -> tuple[bytes, dict]:
    """Verify the existing private build; never weaken build.py's clean-ROM gate."""
    if title not in ("firered", "leafgreen"):
        raise ValueError("unsupported native carrier title")
    directory = root / f"patch/build/candidate-{title}-trade"
    receipt = read_json(directory / "receipt.json")
    rom = (directory / "probe.gba").read_bytes()
    if (
        receipt.get("status") != "UNQUALIFIED_TRADE_CANDIDATE"
        or receipt.get("target") != title
        or receipt.get("production") is not False
        or receipt.get("ready") != 0
        or receipt.get("mode") != "trade"
        or receipt.get("capabilities") != 23
        or not receipt.get("carrier_bindings")
    ):
        raise ValueError(f"not a non-production READY0 {title} native carrier candidate")
    pin = read_json(root / "data/gen3_sources.lock.json")["outputs"]["poke" + title]["sha1"]
    if receipt.get("base_sha1") != pin or receipt.get("sha1") != hashlib.sha1(rom).hexdigest():
        raise ValueError("candidate/base ROM hash mismatch")
    payload = (directory / "probe.bin").read_bytes()
    if not payload or len(payload) > 0x14000 or len(payload) != receipt.get("payload_bytes"):
        raise ValueError("candidate payload extent mismatch")
    # build.py patches panel pointer placeholders in the emitted ROM; probe.bin
    # remains the linked template. The final receipt hashes the patched payload.
    entry = int.from_bytes(bytes.fromhex(receipt["replacement"])[4:8], "little") & ~1
    start = entry - ROM_BASE
    if (
        start < 0
        or start + len(payload) > len(rom)
        or sha256(rom[start : start + len(payload)]) != receipt["payload_sha256"]
    ):
        raise ValueError("candidate payload hash mismatch")
    for row in [
        receipt,
        receipt["frame_detour"],
        *receipt["trade_detours"],
        *receipt["panel_detours"],
    ]:
        address = row.get("address", row.get("detour"))
        replacement = bytes.fromhex(row["replacement"])
        if (
            address is None
            or rom[address - ROM_BASE : address - ROM_BASE + len(replacement)] != replacement
        ):
            raise ValueError("candidate detour receipt differs from ROM")
    code = {"firered": b"BPRE", "leafgreen": b"BPGE"}[title]
    if len(rom) != 0x1000000 or rom[0xAC:0xB0] != code or rom[0xBC] != 0:
        raise ValueError(f"candidate is not the pinned {title} format")
    from patch.tools.build import target_spec

    spec = target_spec(title)
    expected = {
        spec[name]: bytes.fromhex(spec[name + "_BYTES"])
        for name in ("HEAP_INIT", "TRADE_MON", "EVO_GETTER")
    }
    expected[spec["FRAME_ENTRY"]] = bytes.fromhex(spec["FRAME_BYTES"])
    expected[spec["PANEL_NORMAL_MENU"]] = bytes.fromhex(spec["PANEL_NORMAL_BYTES"])
    for field, table in (
        ("PANEL_ACTION_REFS", "PANEL_ACTION_TABLE"),
        ("PANEL_DESC_REFS", "PANEL_DESC_TABLE"),
    ):
        expected.update(
            {int(at, 0): spec[table].to_bytes(4, "little") for at in spec[field].split(",")}
        )
    rows = [receipt, receipt["frame_detour"], *receipt["trade_detours"], *receipt["panel_detours"]]
    if (
        start != spec["CODE_CANDIDATE"] - ROM_BASE
        or receipt["arena_candidate"] != spec["ARENA_CANDIDATE"]
        or {r.get("address", r.get("detour")) for r in rows} != set(expected)
        or len(rows) != len(expected)
    ):
        raise ValueError("candidate patch closure differs from the source-bound build recipe")
    restored = bytearray(rom)
    restored[start : start + len(payload)] = b"\xff" * len(payload)
    for row in rows:
        address = row.get("address", row.get("detour"))
        original = bytes.fromhex(row["original"])
        if original != expected[address] or len(bytes.fromhex(row["replacement"])) != len(original):
            raise ValueError("candidate original bytes differ from source-bound detour")
        at = address - ROM_BASE
        restored[at : at + len(original)] = original
    if hashlib.sha1(restored).hexdigest() != pin:
        raise ValueError("undoing the exact build spans did not recover the pinned clean ROM")
    return rom, receipt


def private_pack(root: Path, rom: bytes, receipt: dict) -> dict[str, dict]:
    """A deliberately test-only admission projection, outside shipped data/games.

    The source receipt remains production:false. The projection exercises the
    real production constructor with explicit production metadata only after
    the duo-only loader validates its nonce and the cartridge digest. A fresh
    production Entry never reads these paths, even if ENV is set.
    """
    title = receipt["target"]
    profile = read_json(root / "data/games/gen3_frlg/profile.json")
    abi = native_abi()
    c = abi["constants"]
    base = receipt["arena_candidate"]
    native = {
        "ABI": c["SLINK_ABI_VERSION"],
        "SIG": c["SLINK_SIGNATURE"],
        "BASE": base,
        "abi_v2": abi,
    }
    native.update(
        {
            name.removeprefix("SLINK_"): value
            for name, value in c.items()
            if name.startswith("SLINK_OP_")
        }
    )
    for name, offset in (
        ("BLOB_BUF", "SLINK_BLOB_OFFSET"),
        ("TEXT_BUF", "SLINK_TEXT_OFFSET"),
        ("MENU_BUF", "SLINK_MENU_OFFSET"),
        ("INFO", "SLINK_INFO_OFFSET"),
    ):
        native[name] = base + c[offset]
    profile["native"] = native
    sites = read_json(root / "data/games/gen3_frlg/engine_signals.json")
    artifact = copy.deepcopy(sites["titles"][title]["artifacts"]["clean"])
    artifact.update(
        production=True,
        harness_only=True,
        source_production=False,
        rom_sha1=hashlib.sha1(rom).hexdigest(),
        rom_md5=hashlib.md5(rom).hexdigest(),
    )
    for site in artifact["sites"].values():
        start = site["rom_offset"]
        # signals.lua compares its uppercase hex_of() result verbatim at both
        # startup and fire time; preserve the shipped pack's canonical encoding.
        site["expected_hex"] = (
            rom[start : start + len(bytes.fromhex(site["expected_hex"]))].hex().upper()
        )
    sites["titles"][title]["artifacts"] = {"companion": artifact}
    checkpoint = read_json(root / "data/games/gen3_frlg/write_checkpoint.json")
    cp = checkpoint[title]
    for anchor in cp["anchors"].values():
        start = anchor["rom_offset"]
        anchor["expected_hex"]["companion"] = rom[start : start + anchor["length"]].hex().upper()
    cp["native"] = {
        "version": "gen3-native-v2",
        "base": base,
        "sig": native["SIG"],
        "abi": 2,
        "abi_off": 4,
        "opcode_off": 6,
        "status_off": 10,
        "busy": 1,
        "info": native["INFO"],
        "info_state_off": c["SLINK_INFO_STATE_FIELD"],
    }
    return {"profile": profile, "sites": sites, "checkpoint": checkpoint}


def trade_fixture(seed: bytes, *, species: int = 64) -> bytes:
    """SYNTH: change slot 1 to a trade-evolving species, retaining PID/OT/genome.

    No story, map, trainer identity, box, or other party record is changed. The
    level/experience and moves are retained; the native evolution recomputes
    stats. The fixture and this limited edit are disclosed in the manifest.
    """
    parsed = codec.parse_flash(seed)
    sb1 = bytearray(parsed["sb1"])
    if sb1[codec.SB1_PARTY_COUNT_OFFSET] < 2:
        raise ValueError("trade fixture needs party slot 1")
    at = codec.SB1_PARTY_OFFSET + codec.PARTY_MON_SIZE
    mon = codec.decode_party_mon(sb1[at : at + codec.PARTY_MON_SIZE])
    if not mon["checksum_ok"] or mon["is_egg"] or mon["is_bad_egg"]:
        raise ValueError("trade fixture slot 1 is ineligible")
    mon.update(species=species, held_item=0, mail=255, ability_num=0)
    sb1[at : at + codec.PARTY_MON_SIZE] = codec.encode_party_mon(mon)
    body, layout = bytearray(seed), codec.slot_layout()
    for entry in layout:
        if entry["object"] != "sb1":
            continue
        sectors = parsed["sectors"][
            parsed["slot"] * codec.NUM_SECTORS_PER_SLOT : (parsed["slot"] + 1)
            * codec.NUM_SECTORS_PER_SLOT
        ]
        physical = next(s["index"] for s in sectors if s["id"] == entry["id"])
        chunk = sb1[entry["offset"] : entry["offset"] + entry["size"]]
        body[physical * codec.SECTOR_SIZE : (physical + 1) * codec.SECTOR_SIZE] = (
            codec.write_sector(chunk, entry["id"], parsed["counter"], layout)
        )
    ok, why = codec.qualify_flash(body)
    if not ok:
        raise ValueError(f"SYNTH trade fixture does not qualify: {why}")
    return bytes(body)


def prepare(root: Path, directory: Path, *, title="firered", player=None, nonce=None, journal_path=None) -> dict:
    rom, receipt = candidate_inputs(root, title)
    directory = directory.resolve()
    if not directory.is_relative_to((root / "patch/build").resolve()):
        raise ValueError("private duo inputs must stay inside this lane's patch/build")
    directory.mkdir(parents=True, exist_ok=True)
    pack_files = {}
    for name, value in private_pack(root, rom, receipt).items():
        path = directory / (name + ".json")
        path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        pack_files[name] = path.relative_to(root).as_posix()
    pack_files.update(
        area_map="data/games/gen3_frlge/area_map.json",
        locations="data/games/gen3_frlge/gen3_frlge_locations.lua",
    )
    tables = decode_rom_tables(rom, title)
    evolution = [row for row in tables["evolutions"][64] if row[0] == 5]  # pret EVO_TRADE
    if len(evolution) != 1:
        raise ValueError("candidate lacks the unique Kadabra trade evolution")
    manifest = {
        "schema": SCHEMA,
        "production": False,
        "ready": 0,
        "title": title,
        "player": player,
        "carrier_mode": "native",
        "nonce": nonce or uuid.uuid4().hex,
        "rom_sha1": receipt["sha1"],
        "rom_md5": hashlib.md5(rom).hexdigest(),
        "rom": f"patch/build/candidate-{title}-trade/probe.gba",
        "pack_files": pack_files,
        "receipt_sha256": sha256(
            (root / f"patch/build/candidate-{title}-trade/receipt.json").read_bytes()
        ),
        "native": private_pack(root, rom, receipt)["profile"]["native"],
        "fixture_disclosure": f"SYNTH clean-derived {title} saves; only slot 1 species/held item/mail/ability changed",
        "expected_species": evolution[0][2],
        "fixtures": {},
    }
    manifest["journal_path"] = journal_path or (
        (directory / ("slink_gen3_trade_" + manifest["nonce"])).relative_to(root).as_posix()
    )
    manifest["pack_sha1"] = {
        name: _sha1_file(root, pack_files[name]) for name in ("profile", "sites", "checkpoint")
    }
    manifest["source_sha1"] = {path: _sha1_file(root, path) for path in SOURCE_FILES}
    manifest["source_commit"] = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    symbols = {}
    for line in (root / f"data/gen3/pret/poke{title}.sym").read_text().splitlines():
        fields = line.split()
        if fields and fields[-1] in (
            "TradeMons",
            "TrySavingData",
            "DoInGameTradeScene",
            "TradeEvolutionScene",
            "CB2_InitPartyMenu",
            "gPartyMenu",
        ):
            symbols.setdefault(fields[-1], int(fields[0], 16))
    detour = next(
        row for row in receipt["trade_detours"] if row["symbol"] == "slink_native_trade_gate"
    )
    if detour["address"] != symbols["TradeMons"]:
        raise ValueError("trade detour differs from pret TradeMons")
    manifest["hooks"] = {
        "TradeMons_body": symbols["TradeMons"] + 8,
        "TrySavingData": symbols["TrySavingData"],
        "DoInGameTradeScene": symbols["DoInGameTradeScene"],
        "TradeEvolutionScene": symbols["TradeEvolutionScene"],
        "CB2_InitPartyMenu": symbols["CB2_InitPartyMenu"],
    }
    manifest["party_count"] = private_pack(root, rom, receipt)["profile"]["titles"][title][
        "ram"
    ]["PARTY_COUNT_ADDR"]
    from patch.tools.build import target_spec

    spec = target_spec(title)
    carrier_source = (root / "patch/src/trade_targets/native_carrier.h").read_text()
    state_offset = re.search(r"#define NC_STATE .*NT_BASE\+(0x[0-9A-Fa-f]+)u", carrier_source)
    if not state_offset:
        raise ValueError("native carrier state is not source-bound")
    base = receipt["arena_candidate"]
    manifest["carrier"] = {
        "state": base + int(state_offset[1], 16), "size": 380,
        "control": base + native_abi()["constants"]["SLINK_CONTROL_OFFSET"],
        "objects": spec["CARRIER_OBJECTS"], "avatar": spec["CARRIER_AVATAR"],
        "stride": spec["CARRIER_STRIDE"], "local_id": spec["CARRIER_LOCAL_ID"],
        "callback": spec["GMAIN"] + 4, "field_callback": spec["FIELD_CALLBACK"],
        "field_lock": spec["FIELD_LOCK"], "script_status": spec["SCRIPT_STATUS"],
        "script_idle": spec["SCRIPT_IDLE"],
        "party_cursor": symbols["gPartyMenu"] + 9,  # pinned pret include/party_menu.h:15
    }
    for side, suffix in (("a", ""), ("b", "_b")):
        source = root / f"tests/fixtures/gen3/{title}_party_town{suffix}.sav"
        data = trade_fixture(source.read_bytes())
        destination = directory / (side + ".sav")
        destination.write_bytes(data)
        manifest["fixtures"][side] = {
            "path": destination.relative_to(root).as_posix(),
            "sha256": sha256(data),
            "source_sha256": sha256(source.read_bytes()),
        }
    path = directory / "manifest.json"
    path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    manifest["path"] = path.relative_to(root).as_posix()
    manifest["manifest_sha1"] = _sha1_file(root, manifest["path"])
    validate_prepared(root, manifest)
    return manifest


def prepare_pair(root: Path, directory: Path, titles: dict[str, str]) -> dict:
    if set(titles) != {"a", "b"} or set(titles.values()) != {"firered", "leafgreen"}:
        raise ValueError("native carrier duo requires both FR and LG")
    nonce = uuid.uuid4().hex
    journal = (directory.resolve() / ("slink_gen3_trade_" + nonce)).relative_to(root.resolve()).as_posix()
    players = {
        side: prepare(root, directory / side, title=title, player=side, nonce=nonce, journal_path=journal)
        for side, title in titles.items()
    }
    return {"nonce": nonce, "players": players,
            "fixtures": {side: manifest["fixtures"][side] for side, manifest in players.items()}}


def player_manifest(manifest: dict, side: str) -> dict:
    """A pair carries independently bound manifests; standalone fixtures keep one."""
    return manifest["players"][side] if "players" in manifest else manifest


def decode_witness(raw: bytes) -> dict:
    """Independent read of mailbox + witness (0xA0 bytes), never Lua's decoded table."""
    if len(raw) != 0xA0:
        raise ValueError("native snapshot must contain the 80-byte mailbox and 80-byte witness")

    def word(offset, width):
        return int.from_bytes(raw[offset : offset + width], "little")

    return {
        "signature": word(0, 4),
        "abi": word(4, 2),
        "opcode": word(6, 2),
        "seq": word(8, 2),
        "status": word(10, 2),
        "ack": word(12, 2),
        "reason": word(14, 2),
        "args": raw[16:48],
        "capabilities": word(64, 4),
        "epoch": word(68, 4),
        "phase": word(72, 4),
        "w_epoch": word(80, 4),
        "visit": word(84, 4),
        "token": raw[88:104],
        "revision": word(104, 2),
        "flags": word(106, 2),
        "bits": word(108, 4),
        "sequences": struct.unpack_from("<5H", raw, 112),
        "result": raw[122],
        "save": raw[123],
        "old": (word(144, 4), word(148, 4)),
        "received": (word(152, 4), word(156, 4)),
    }


def witness_problems(
    request: bytes, scene: bytes, commit: bytes, final: bytes, old: tuple, incoming: tuple
) -> list[str]:
    """Bind real engine commit and durable final to the two host publications."""
    try:
        pre, apply, entered, done = map(decode_witness, (request, scene, commit, final))
    except (ValueError, TypeError) as exc:
        return [str(exc)]
    problems = []
    if pre["opcode"] != 29 or apply["opcode"] != 21 or pre["seq"] == apply["seq"]:
        problems.append("native PREPARE/SCENE publications missing or sequences reused")
    args = pre["args"]
    if args != apply["args"] or struct.unpack_from("<II", args, 4) != old or not any(args[16:32]):
        problems.append("native request identity differs")
    for name, w in (("commit", entered), ("final", done)):
        if (
            w["signature"] != 0x4B4E4C53
            or w["abi"] != 2
            or not w["capabilities"] & 1
            or w["epoch"] != pre["epoch"]
            or not pre["epoch"]
            or w["w_epoch"] != pre["epoch"]
            or w["visit"] != int.from_bytes(args[12:16], "little")
            or not w["visit"]
            or w["token"] != args[16:32]
            or w["old"] != old
            or not w["revision"]
            or w["revision"] % 2
            or w["flags"] != 3
            or w["sequences"][0] != pre["seq"]
            or w["sequences"][1] != apply["seq"]
        ):
            problems.append(f"{name}: unbound/incoherent native witness")
    if entered["bits"] != 3 or entered["result"] != 0:
        problems.append("real TradeMons entry did not follow PRE_SAVE + COMMIT")
    if (
        done["bits"] != 31
        or done["result"] != 1
        or done["save"] != 1
        or done["phase"] != 4
        or done["received"] != incoming
        or done["sequences"][1:] != (apply["seq"],) * 4
        or done["opcode"] != 0
        or done["seq"] != apply["seq"]
        or done["ack"] != apply["seq"]
        or done["status"] != 2
    ):
        problems.append("native final lacks bound commit/scene/post-save/received identity")
    return problems


def events(text: str, side: str, phase: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        if line.startswith("T5 "):
            row = json.loads(line[3:])
            if (
                row.get("side") != side
                or row.get("phase") != phase
                or type(row.get("frame")) is not int
                or row["frame"] < 0
            ):
                raise ValueError("T5 receipt side/phase/frame mismatch")
            rows.append(row)
    if any(after["frame"] < before["frame"] for before, after in zip(rows, rows[1:], strict=False)):
        raise ValueError("T5 emulator frame count rolled back within a process")
    return rows


def evidence_file(root: Path, row: dict, nonce: str, side: str, phase: str) -> bytes:
    path = row.get("path", "")
    prefix = f"patch/build/t5_{nonce}_{side}_{phase}_"
    if (
        not isinstance(path, str)
        or not path.startswith(prefix)
        or not re.fullmatch(r"[\w/.-]+", path)
    ):
        raise ValueError("T5 evidence filename is not owned by this side/phase/run")
    resolved = (root / path).resolve()
    if not resolved.is_relative_to((root / "patch/build").resolve()):
        raise ValueError("T5 evidence escaped the lane")
    return resolved.read_bytes()


def party_records(raw: bytes, count: int) -> list[dict]:
    if not isinstance(count, int) or count < 1 or count > 6 or len(raw) != count * 100:
        raise ValueError("T5 party readback extent/count mismatch")
    rows = [codec.decode_party_mon(raw[i : i + 100]) for i in range(0, len(raw), 100)]
    if any(not m["checksum_ok"] or not m["has_species"] or m["is_bad_egg"] for m in rows):
        raise ValueError("T5 party readback has invalid records")
    return rows


def journal_state(body: bytes, guard: bytes) -> dict:
    """Read the sealed append-only journal independently of its Lua consumer."""
    magic = b"SLINK-TRADE-JOURNAL-1\n"

    def fnv(data):
        value = 2166136261
        for byte in data:
            value = ((value ^ byte) * 16777619) & 0xFFFFFFFF
        return f"{value:08x}".encode()

    if (
        not body.startswith(magic)
        or guard != magic + str(len(body)).encode() + b":" + fnv(body) + b"\n"
    ):
        raise ValueError("journal guard/body seal differs")
    at, previous = len(magic), None
    while at < len(body):
        head = re.match(rb"([1-9][0-9]*):([0-9a-f]{8}):", body[at:])
        if not head:
            raise ValueError("torn journal framing")
        count = int(head[1])
        start = at + head.end()
        end = start + count
        encoded = body[start:end]
        if len(encoded) != count or body[end : end + 1] != b"\n" or fnv(encoded) != head[2]:
            raise ValueError("torn journal frame seal")
        state = json.loads(encoded)
        if (
            state.get("schema") != 1
            or type(state.get("revision")) is not int
            or type(state.get("counter")) is not int
            or not isinstance(state.get("records"), list)
        ):
            raise ValueError("invalid journal state")
        if previous is None:
            if state != {"schema": 1, "revision": 0, "counter": 0, "records": []}:
                raise ValueError("missing journal genesis")
        elif (
            state["revision"] != previous["revision"] + 1
            or not previous["counter"] <= state["counter"] <= previous["counter"] + 1
        ):
            raise ValueError("journal sequence rollback")
        previous, at = state, end + 1
    if previous is None:
        raise ValueError("empty journal")
    return previous


def key(mon: dict) -> str:
    return f"{mon['personality']:08X}:{mon['ot_id']:08X}"


def carrier_text(text: str) -> str:
    """The server text as the native carrier stores it: lua/gen3/native.lua encode() writes a
    newline as the FR line-break byte 0xFE, which the name codec only takes as its <$FE> escape."""
    return codec.decode_name(codec.encode_name(text.replace("\n", "<$FE>"), 256))


def carrier_problems(rows: list[dict], manifest: dict, side: str, read, *, decline=False,
                     trade_epoch=None, trade_token=None) -> list[str]:
    """Decode native ownership/text/counter bytes and correlate actual server wire messages."""
    problems = []
    ops = (22, 20) if side == "a" else (17,)
    c = manifest["carrier"]

    def one(kind, op=None):
        matches = [r for r in rows if r["kind"] == kind and (op is None or r.get("op") == op)]
        if len(matches) != 1:
            raise ValueError(f"expected one native carrier {kind}/{op}, got {len(matches)}")
        return matches[0]

    def ui(row):
        raw = read(row)
        if len(raw) != 547:
            raise ValueError("native carrier snapshot extent differs")
        native = decode_witness(raw[:160])
        epoch, seq, opcode, active = struct.unpack_from("<IHHB", raw, 160)
        return native, (epoch, seq, opcode, active), raw[170:426], raw[426:538], raw[540:]

    try:
        epochs = []
        for kind in ("ui_post", "ui_enter", "ui_done"):
            if len([r for r in rows if r["kind"] == kind]) != len(ops):
                raise ValueError(f"native carrier {kind} count differs")
        if len([r for r in rows if r["kind"] == "chooser_entry"]) != (1 if side == "a" else 0):
            raise ValueError("native chooser engine entry count differs")
        for op in ops:
            posted, entered, finished = (one(kind, op) for kind in ("ui_post", "ui_enter", "ui_done"))
            p, _, _, _, _ = ui(posted)
            e, owner, text, choices, _ = ui(entered)
            f, retired, _, _, field = ui(finished)
            binding = (p["epoch"], p["seq"], op)
            epochs.append(p["epoch"])
            if any(v["signature"] != 0x4B4E4C53 or v["abi"] != 2 or v["capabilities"] != 23 for v in (p, e, f)):
                raise ValueError(f"native carrier {op} cartridge ABI/capabilities differ")
            if (not p["epoch"] or p["opcode"] != op or owner != (*binding, 1)
                or retired != (*binding, 0) or e["epoch"] != p["epoch"] or f["epoch"] != p["epoch"]
                or e["seq"] != p["seq"] or f["seq"] != p["seq"]
                or e["status"] != 1 or e["opcode"] != 0 or f["status"] != 2
                or f["opcode"] != 0 or f["ack"] != p["seq"]):
                raise ValueError(f"native carrier {op} ownership/ACK binding differs")
            if struct.unpack_from("<I", field)[0] != c["field_callback"] or field[4:6] != bytes([0, c["script_idle"]]):
                raise ValueError(f"native carrier {op} ACK preceded safe field return")
            command = {22: "show_choices", 20: "choose_mon", 17: "show_menu"}[op]
            incoming = [r for r in rows if r["kind"] == "rx" and r.get("message", {}).get("cmd") == command]
            if len(incoming) != 1:
                raise ValueError(f"server {command} missing/duplicated")
            msg = incoming[0]["message"]
            if trade_token is not None and msg.get("token") != trade_token:
                raise ValueError("native carrier belongs to another server trade token")
            if op == 17 or (op == 22 and msg.get("text")):
                expected = carrier_text(msg.get("text", ""))
                if b"\xff" not in text or codec.decode_name(text) != expected:
                    raise ValueError(f"native carrier {op} text differs from server command")
            if op == 22:
                with_text = int(bool(msg.get("text")))
                if p["args"][0] != with_text or read(entered)[169] != with_text:
                    raise ValueError("native choices text-display flag differs")
                options = msg.get("options", [])
                if choices[0] != len(options) or not options:
                    raise ValueError("native choices count differs")
                strings = choices[1:].split(b"\xff")
                if len(strings) <= len(options) or [codec.decode_name(part) for part in strings[:len(options)]] != options:
                    raise ValueError("native choices differ from server command")
            event, field_name = ("mon_chosen", "slot") if op == 20 else ("menu_result", "choice")
            result = 1 if op == 20 else 0 if op == 22 or decline else 1
            raw_done = read(finished)
            outgoing = [r for r in rows if r["kind"] == "tx" and r["message"].get("event") == event
                        and r["message"].get("token") == msg.get("token")]
            if (raw_done[48] != result or len(outgoing) != 1 or not msg.get("token")
                or outgoing[0]["message"].get(field_name) != result):
                raise ValueError(f"native carrier {op} result/wire answer differs")
            if not rows.index(incoming[0]) < rows.index(posted) < rows.index(entered) < rows.index(finished) < rows.index(outgoing[0]):
                raise ValueError(f"native carrier {op} wire/ownership order differs")
            if op == 20:
                chooser = one("chooser_entry")
                _, chosen_owner, _, _, chosen_field = ui(chooser)
                if (chosen_owner != (*binding, 1)
                    or struct.unpack_from("<I", chosen_field)[0] != manifest["hooks"]["CB2_InitPartyMenu"] | 1
                    or not rows.index(posted) < rows.index(chooser) < rows.index(finished)):
                    raise ValueError("native chooser engine entry missing or foreign")
        if len(set(epochs)) != 1:
            raise ValueError("native carrier epoch changed between UI operations")
        if trade_epoch is not None and epochs[0] != trade_epoch:
            raise ValueError("native carrier belongs to another native trade epoch")
        if side == "a":
            edge = one("npc_edge")
            raw = read(edge)
            if len(raw) != 614 or c["stride"] != 36:
                raise ValueError("native NPC snapshot extent differs")
            old_epoch, before, epoch, after = (*struct.unpack_from("<II", raw), *struct.unpack_from("<II", raw, 16))
            if old_epoch != epoch or epoch != epochs[0] or ((after-before)&0xFFFFFFFF) != 1 or raw[24] != 1:
                raise ValueError("native NPC counter/CONTROL epoch differs")
            objects, player = raw[32:608], raw[613]
            npcs = [i for i in range(16) if objects[i*36]&1 and objects[i*36+8] == c["local_id"]]
            if player >= 16 or len(npcs) != 1:
                raise ValueError("native NPC/player object missing")
            p, n = objects[player*36:(player+1)*36], objects[npcs[0]*36:(npcs[0]+1)*36]
            px, py = struct.unpack_from("<hh", p, 16)
            nx, ny = struct.unpack_from("<hh", n, 16)
            delta = {1: (0, 1), 2: (0, -1), 3: (-1, 0), 4: (1, 0)}.get(p[24]&15)
            if not (p[0]&0x80 and p[0]&1 and p[9:11] == n[9:11] and delta == (nx-px, ny-py)):
                raise ValueError("native NPC edge lacks idle player facing its active object")
            requests = [r for r in rows if r["kind"] == "tx" and r["message"].get("event") == "trade_request"]
            if len(requests) != 1 or not rows.index(edge) < rows.index(requests[0]) < rows.index(one("ui_post", 22)):
                raise ValueError("trade_request did not follow the native NPC edge")
        one("native_carrier_complete")
    except (ValueError, KeyError, IndexError, TypeError, struct.error) as exc:
        problems.append(str(exc))
    return problems


def completed_flushes(rows: list[dict], read, *, decline=False, before=None) -> list[tuple]:
    """Associate each host call with its own flash/native/file snapshots.

    The ordinary save-site handler flushes PREPARE and post-save too. Only a
    durable native outcome before trade_done qualifies for a successful trade;
    repeated legitimate flushes must not be mistaken for additional game saves.
    """
    out = []
    limit = rows.index(before) if before is not None else len(rows)
    for index, row in enumerate(rows[:limit]):
        if row.get("kind") != "flush":
            continue
        if (
            index < 2
            or rows[index - 1].get("kind") != "flush_native"
            or rows[index - 2].get("kind") != "flash"
        ):
            raise ValueError("host flush is missing its paired flash/native snapshots")
        native, flash = rows[index - 1], rows[index - 2]
        witness = decode_witness(read(native))
        if decline or (
            witness["bits"] == 31
            and witness["result"] == 1
            and witness["save"] == 1
            and witness["phase"] == 4
        ):
            out.append((row, flash, native))
    return out


def physical_problems(
    root: Path,
    manifest: dict,
    texts: dict,
    reloads: dict,
    document: dict,
    fixtures: dict,
    saved: dict,
    *,
    decline: bool,
) -> list[str]:
    """Native/host/wire/save/reload evidence, independently decoded from files.

    fixtures/saved are Python-decoded (party, boxes), never a Lua RESULT claim.
    A disk read at host-flush return prevents a later manual SAVE/exit flush
    from repairing an otherwise false success.
    """
    problems = []
    keys = {side: key(fixtures[side][0][1]) for side in "ab"}
    expected = {side: keys[side if decline else ("b" if side == "a" else "a")] for side in "ab"}
    journal_epochs = []
    links = [
        row
        for row in document.get("links", [])
        if {(row.get("a") or {}).get("key"), (row.get("b") or {}).get("key")} == set(keys.values())
    ]
    if (
        len(links) != 1
        or links[0].get("status") != "alive"
        or any((links[0].get(side) or {}).get("key") != expected[side] for side in "ab")
    ):
        problems.append("links.json did not retain/migrate exactly the traded pair")
    for side in "ab":
        cart = player_manifest(manifest, side)
        peer = "b" if side == "a" else "a"
        try:
            initial = events(texts[side], side, "initial")
            after = events(reloads[side], side, "native_trade_reload")
            if any(r["kind"] in {"npc_edge", "ui_post", "prepare", "scene", "commit", "save_entry"}
                   or (r["kind"] == "tx" and r.get("message", {}).get("event") in {"trade_request", "trade_done"})
                   for r in after):
                problems.append(f"{side}: cold reload started another native interaction/save")
            for rows, text in ((initial, texts[side]), (after, reloads[side])):
                override = [r for r in rows if r["kind"] == "override"]
                if (
                    len(override) != 1
                    or override[0].get("production") is not False
                    or override[0].get("ready") != 0
                    or override[0].get("environment") != ENV
                    or override[0].get("value") != manifest["nonce"]
                    or override[0].get("rom_sha1") != cart["rom_sha1"]
                    or override[0].get("source_commit") != cart["source_commit"]
                    or override[0].get("manifest_sha1") != cart["manifest_sha1"]
                    or override[0].get("run_lua_sha1")
                    != cart["source_sha1"]["lua/gen3/run.lua"]
                    or override[0].get("sites_sha1") != cart["pack_sha1"]["sites"]
                    or DISCLOSURE not in text
                ):
                    problems.append(f"{side}: HARNESS_ONLY admission/carrier disclosure missing")

            def one(kind, rows=initial):
                found = [r for r in rows if r["kind"] == kind]
                if len(found) != 1:
                    raise ValueError(f"expected exactly one {kind}, got {len(found)}")
                return found[0]

            def read(row, phase="initial", side_=side):
                return evidence_file(root, row, manifest["nonce"], side_, phase)

            terminal = [r for r in initial if r["kind"] == "tx" and r["message"].get("event") == "trade_done"]
            carrier_epoch = None if decline else decode_witness(read(one("prepare")))["epoch"]
            carrier_token = terminal[0]["message"].get("token") if len(terminal) == 1 else None
            problems.extend(f"{side} carrier: {problem}"
                            for problem in carrier_problems(initial, cart, side, read, decline=decline,
                                                            trade_epoch=carrier_epoch, trade_token=carrier_token))
            if not decline and any(initial.index(r) >= initial.index(one("prepare"))
                                   for r in initial if r["kind"] == "ui_done"):
                problems.append(f"{side}: native PREPARE preceded completion of carrier UI")

            baseline, before, reloaded = (
                one("boot_party"),
                one("before_reload"),
                one("reloaded", after),
            )
            baseline_party = party_records(read(baseline), baseline["count"])
            before_party = party_records(read(before), before["count"])
            reload_party = party_records(read(reloaded, "native_trade_reload"), reloaded["count"])
            want_keys = [
                expected[side] if key(m) == keys[side] else key(m) for m in fixtures[side][0]
            ]
            for name, party in (
                ("before reload", before_party),
                ("cold reload", reload_party),
                ("SaveRAM", saved[side][0]),
            ):
                if [key(m) for m in party] != want_keys:
                    problems.append(f"{side}: {name} party differs from expected trade identities")
            for named_key in keys.values():
                occurrences = sum(key(m) == named_key for pid in "ab" for m in saved[pid][0])
                occurrences += sum(
                    key(m) == named_key for pid in "ab" for m in saved[pid][1].values()
                )
                if occurrences != 1:
                    problems.append(
                        f"saved {named_key} exists {occurrences} times across both cartridges"
                    )
            txs = [r for r in initial if r["kind"] == "tx"]
            done = [r for r in txs if r["message"].get("event") == "trade_done"]
            flushes = completed_flushes(
                initial, read, decline=decline, before=done[0] if len(done) == 1 else None
            )
            if not flushes:
                raise ValueError("no qualifying host flush before trade_done")
            flush, flash, flush_native = flushes[-1]
            qualified, why = codec.qualify_flash(read(flush))
            if not qualified:
                problems.append(f"{side}: host-flush save is not complete/checksummed: {why}")
            if (
                flush.get("status") != "returned"
                or codec.split_rtc(read(flush))[0] != read(flash)
                or initial.index(flash) > initial.index(flush)
            ):
                problems.append(f"{side}: host flush file differs from the live flash image")
            flashed = codec.parse_flash(read(flush))
            boot = one("boot")
            if flashed["counter"] != boot["counter"] + (0 if decline else 2):
                problems.append(
                    f"{side}: host-flush file lacks the exact native save counter delta"
                )
            if before["counter"] != flashed["counter"] or reloaded["counter"] != flashed["counter"]:
                problems.append(f"{side}: a later save was needed before/after cold reload")
            disk_party = codec.party_from_save(read(flush))
            if [key(m) for m in disk_party] != want_keys:
                problems.append(
                    f"{side}: file at host-flush return did not contain traded identities"
                )
            if decline:
                if any(
                    r["kind"] == "rx"
                    and r["message"].get("cmd") in ("apply_prepare", "apply_trade")
                    for r in initial
                ):
                    problems.append(f"{side}: server attempted native apply after decline")
                if (
                    baseline_party != before_party
                    or before_party != reload_party
                    or read(baseline) != read(before)
                    or read(before) != read(reloaded, "native_trade_reload")
                    or done
                    or any(
                        r["kind"] in ("prepare", "scene", "commit", "save_entry") for r in initial
                    )
                ):
                    problems.append(
                        f"{side}: decline changed party or entered native mutation/save"
                    )
                if side == "a" and not any(
                    r["kind"] == "rx" and r.get("message", {}).get("cmd") == "msgbox"
                    and "declined" in r["message"].get("text", "") for r in initial
                ):
                    problems.append("a: server decline/cancel acknowledgement absent")
            else:
                prepare, scene, commit, final = map(one, ("prepare", "scene", "commit", "final"))
                scene_enter, evolution = one("scene_enter"), one("evolution")
                for hook in (scene_enter, evolution):
                    observed = decode_witness(read(hook))
                    if (
                        observed["token"] != decode_witness(read(commit))["token"]
                        or observed["w_epoch"] != decode_witness(read(commit))["w_epoch"]
                    ):
                        problems.append(
                            f"{side}: engine scene/evolution hook belongs to another transaction"
                        )
                old = fixtures[side][0][1]
                incoming = fixtures[peer][0][1]
                problems.extend(
                    f"{side}: {p}"
                    for p in witness_problems(
                        read(prepare),
                        read(scene),
                        read(commit),
                        read(final),
                        (old["personality"], old["ot_id"]),
                        (incoming["personality"], incoming["ot_id"]),
                    )
                )
                problems.extend(
                    f"{side} flush: {problem}"
                    for problem in witness_problems(
                        read(prepare),
                        read(scene),
                        read(commit),
                        read(flush_native),
                        (old["personality"], old["ot_id"]),
                        (incoming["personality"], incoming["ot_id"]),
                    )
                )
                saves = [r for r in initial if r["kind"] == "save_entry"]
                if len(saves) != 2 or not (
                    initial.index(prepare)
                    < initial.index(saves[0])
                    < initial.index(scene)
                    < initial.index(scene_enter)
                    < initial.index(commit)
                    < initial.index(evolution)
                    < initial.index(saves[1])
                    < initial.index(flush)
                ):
                    problems.append(f"{side}: native pre-save/commit/post-save/flush order differs")
                if (
                    len(done) != 1
                    or done[0]["message"].get("new_key") != expected[side]
                    or initial.index(done[0]) < initial.index(flush)
                ):
                    problems.append(
                        f"{side}: trade_done preceded durable host flush or names wrong identity"
                    )
                token = done[0]["message"].get("token") if len(done) == 1 else None
                intent = one("journal_intent")
                sealed = journal_state(read(intent), read({"path": intent.get("guard", "")}))
                records = [
                    r
                    for r in sealed["records"]
                    if r.get("token") == token
                    and r.get("binding", {}).get("player") == side
                    and r.get("binding", {}).get("rom_sha1") == cart["rom_sha1"]
                    and r.get("final") == ""
                    and type(r.get("epoch")) is int
                    and r["epoch"] > 0
                ]
                configs = [
                    r["message"]
                    for r in initial
                    if r["kind"] == "rx" and r["message"].get("cmd") == "config"
                ]
                if len(records) == 1:
                    journal_epochs.append(records[0]["epoch"])
                    binding = records[0]["binding"]
                    if (
                        not configs
                        or not configs[-1].get("run_id")
                        or binding.get("run_id") != configs[-1]["run_id"]
                        or binding.get("ot_id") != f"{old['ot_id']:08X}"
                    ):
                        problems.append(f"{side}: journal intent belongs to another run/trainer")
                if len(records) != 1 or initial.index(intent) > initial.index(commit):
                    problems.append(f"{side}: no sealed write-ahead intent before native commit")
                journal = one("journal")
                if (
                    journal.get("token") != token
                    or journal.get("ready") is not True
                    or journal.get("hidden") is not False
                    or journal.get("empty") is not True
                ):
                    problems.append(
                        f"{side}: client journal did not reconcile the committed result"
                    )
                finals = [
                    r
                    for r in initial
                    if r["kind"] == "rx"
                    and r["message"].get("cmd") == "trade_final"
                    and r["message"].get("token") == token
                    and r["message"].get("verdict") == "committed"
                ]
                stored = document.get("trade_finals", {}).get(side, [])
                if len(finals) != 1 or not any(
                    r.get("token") == token and r.get("verdict") == "committed" for r in stored
                ):
                    problems.append(f"{side}: server committed final not received and persisted")
                for name, party in (
                    ("native", before_party),
                    ("reloaded", reload_party),
                    ("saved", saved[side][0]),
                    ("flush", disk_party),
                ):
                    got = next((m for m in party if key(m) == expected[side]), {})
                    if got.get("species") != cart["expected_species"]:
                        problems.append(
                            f"{side}: {name} receipt did not evolve to the ROM's trade target"
                        )
                    if any(
                        got.get(field) != incoming.get(field)
                        for field in ("personality", "ot_id", "ot_name", "ivs", "nickname")
                    ):
                        problems.append(
                            f"{side}: {name} changed received immutable identity/genome"
                        )
        # Only genuine unreadable/missing evidence is an oracle finding. KeyError /
        # TypeError / IndexError here are a harness bug (a renamed field, a malformed
        # row), and swallowing them reported "unreadable evidence" instead of failing.
        except (OSError, ValueError) as exc:
            problems.append(f"{side}: unreadable/missing T5 evidence: {exc}")
    if not decline and (len(journal_epochs) != 2 or len(set(journal_epochs)) != 2):
        problems.append("both clients did not own distinct sealed journal epochs")
    return problems
