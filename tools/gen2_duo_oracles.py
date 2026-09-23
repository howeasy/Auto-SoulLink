"""Independent Gen 2 duo witness, link and faint-propagation oracles (H2/H5).

`faint_oracle` decodes immutable LINK_SAVE images and final native saves, requires
A's production battle_faint plus a DEAD server pair and force_faint issuance, and
verifies B's measured checkpoint, permit spans and exact status/HP byte delta.
`on_verified`, when supplied to either scenario oracle, receives the decoded
{a, b, area, titles, status} facts only after every check passes; return stays None.
Gen 2 case/title and boot-file SHA-256 bindings are mandatory, including when the
runner supplies qualified per-side OT IDs and boot fixtures.

Both functions are PLAIN, testable without an emulator or a DuoRun instance. Codex wires them
into tools/e2e_duo.py as thin bound-method wrappers, because tools/duo_oracle_pipeline.py
resolves `EvidenceContract` callbacks via `getattr(owner, name)` -- the registered name must be
a real method on the runner:

    # tools/e2e_duo.py, on the DuoRun class:
    def check_gen2_save_witness(self, results):
        return gen2_duo_oracles.check_save_witness(results)

    def assert_gen2_link_saved(self, results, **kwargs):
        return gen2_duo_oracles.link_oracle(results, data_dir=self.data_dir, **kwargs)

    FAMILY_EVIDENCE["gen2_new"] = EvidenceContract("check_gen2_save_witness", require_oracle=True)
    # SCENARIOS["link"] (gen2_new family) row: "oracle": "assert_gen2_link_saved",
    # "oracle_kwargs": {} -- {} is correct for EVERY title pairing (C<->C, G<->S, C<->G, O-16):
    # no shared title is supplied by the caller. Each side's
    # title/fixture/expected-OT are derived from that side's OWN result-text markers (below), so the
    # same static oracle_kwargs row serves every GAMES pairing without per-lane configuration.

Both raise RuntimeError (never return False) naming the instance and the exact reason on any
refusal; both return None on success. `validate_pipeline` binds `witness(results)` with zero
kwargs and `oracle(results, **oracle_kwargs)`, so `check_save_witness` takes exactly one
positional argument and every other `link_oracle` parameter besides `results` must be a keyword.

## Per-instance result-text markers this module parses (H1 driver contract, fixed 2026-09-23)

One JSON object on the same line as its tag, in each instance's `results[inst]` text
(`D.result`); the LAST occurrence of a repeated tag wins:

- `DUO_GEN2 {...}`: player, scenario, attempt, case, title, rom_sha1, fixture_sha256. `case` names
  the committed boot fixture 1:1 (tests/fixtures/gen2/<case>.SaveRAM, e.g. "gold_battle") -- this
  is where a title's boot save comes from when the caller does not override it.
- `SAVE_WITNESS {...}`: frame, save_completed_frame, gate_saves, client_saves, cartram_sha256
  (sha256 of CartRAM[0:0x8000] -- the first 32768 bytes of the flushed file), cartram_bytes
  (32768), saveram_path (absolute, forward slashes), saveram_bytes (32768 + 22 = 32790, the
  22-byte RTC trailer included), flushed_matches (bool, the driver's own claim -- re-verified
  here independently, never trusted alone).
- `CLIENT {...}`: qualification, production_admitted, pack, title ("crystal"/"gold"/"silver"),
  rom_sha1. `title` selects the gen2_codec layout for THIS side only -- Gold/Silver/Crystal never
  share a layout even when they share an area id (route_29 is title-independent, the party/save
  struct offsets are not).
- `HELLO {...}`: frame, ot_id. The client's own trainer id, reported at connect time before any
  capture -- this is where a title's expected captured-mon OT id comes from when the caller does
  not override it (a self-caught wild mon's OT is always its own trainer's id).
- `RECEIPT {...}`: PASS-only; schema, header, title, rom_sha1, ... . Cross-checked against
  CLIENT/DUO_GEN2 when present; never required, since a FAIL run has no RECEIPT line.
- `ENGINE_CAPTURE {...}`: frame, site_id, acquisition, area_id, destination, slot, key,
  species_id, level. Cross-checked against the independently PYDEC-decoded flushed party.

### Per-side title, never a caller argument

Neither function accepts a `title` parameter. Each side's title is derived from that instance's
OWN markers and cross-checked for internal agreement (`_boot_marker`): DUO_GEN2.title must equal
CLIENT.title (same rom_sha1), and RECEIPT.title/rom_sha1 must agree too when a RECEIPT line is
present. A mismatch is refused, never silently resolved by trusting one marker over another --
this catches a driver that started the wrong title's client, or mixed up which side's result text
is which, independently of the H1 driver's own `SLINK_GEN2_TITLE` self-check. The two sides may
be different titles (Gold<->Silver, Crystal<->Gold, owner ruling O-16): `for_foundation` is called
per instance with ITS OWN cross-checked title, never a shared/assumed one.

`ot_ids` and `boot_saveram` accept the runner's qualified per-instance preflight data.
Standalone callers may omit them and derive them from HELLO.ot_id / DUO_GEN2.case;
either path requires the marker's fixture_sha256 to match the complete boot file.

`check_save_witness` only needs `SAVE_WITNESS` + `CLIENT` + `DUO_GEN2` (saveram_path is absolute,
so no runner/data_dir dependency). `link_oracle` additionally needs `HELLO`, `ENGINE_CAPTURE`, the
two boot fixtures (committed SaveRAM this scenario always boots from) and the server's persisted
`links.json` under `data_dir`.

### Removed guard: "OT ids must differ" (H2b carry, see git log -p / commit 23fbc80e)

An earlier revision refused up front when the (then caller-supplied) `ot_ids` mapping had equal
values for "a" and "b". That guard validated the CALLER'S input, not any observed evidence, so a
mistaken-but-harmless ot_ids argument would abort the oracle before it read a single byte of
either save -- and conversely proved nothing about whether the two sides actually caught the same
mon, since the DECODED saves were never consulted. It was removed once the real invariant already
had a fitting check a few lines later: `decoded["a"]["key"] == decoded["b"]["key"]`, which compares
the two INDEPENDENTLY PYDEC-decoded full identity keys (DV:OT:species) and refuses if they match.
That check is grounded in the flushed saves themselves, catches the identical-capture case the old
guard was trying to catch, and (unlike the old guard) still works now that ot_ids is normally
derived per side from each instance's own HELLO marker rather than supplied as one shared mapping.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

SAVE_WITNESS_FIELDS = ("frame", "save_completed_frame", "gate_saves", "client_saves",
                       "cartram_sha256", "cartram_bytes", "saveram_path", "saveram_bytes",
                       "flushed_matches")
DUO_GEN2_FIELDS = ("case", "title", "rom_sha1", "fixture_sha256")
CARTRAM_BYTES = 0x8000
SAVERAM_BYTES = CARTRAM_BYTES + 22  # 22-byte RTC trailer, outside the equality (P3b.7 plan)


def _last_tagged(text, tag):
    """The last `TAG {json}` line's parsed payload, or None if the tag never appears."""
    lines = [line for line in (text or "").splitlines() if line.startswith(tag + " ")]
    if not lines:
        return None
    payload = lines[-1][len(tag) + 1:]
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"malformed {tag} marker {payload!r}: {exc}") from exc


def _require_fields(marker, fields, label):
    if not isinstance(marker, dict):
        raise RuntimeError(f"{label} marker must be an object")
    missing = [field for field in fields if field not in marker]
    if missing:
        raise RuntimeError(f"{label} marker missing field(s) {missing}: {marker}")
    for field in fields:
        value = marker[field]
        if value is None:
            raise RuntimeError(f"{label} {field} cannot be null")
        if field in ("rom_sha1", "fixture_sha256", "cartram_sha256"):
            length = 40 if field == "rom_sha1" else 64
            if not isinstance(value, str) or re.fullmatch(rf"[0-9a-fA-F]{{{length}}}", value) is None:
                raise RuntimeError(f"{label} {field} must be a {length}-hex hash")
        if field in ("case", "title", "saveram_path") and (not isinstance(value, str) or not value):
            raise RuntimeError(f"{label} {field} must be nonempty text")


def _fixture_path(case):
    """The committed boot fixture for a DUO_GEN2 `case` name, e.g. "gold_battle" ->
    tests/fixtures/gen2/gold_battle.SaveRAM (every gen2_new duo case is named after its fixture
    1:1, lua/tests/duo/duo_gen2_main.lua LAUNCH CONTRACT)."""
    return REPO_ROOT / "tests/fixtures/gen2" / f"{case}.SaveRAM"


def _duo_marker(inst, text):
    """DUO_GEN2 marker for this instance: case/title/rom_sha1, required."""
    duo = _last_tagged(text, "DUO_GEN2")
    if duo is None:
        raise RuntimeError(f"{inst}: missing DUO_GEN2 marker")
    _require_fields(duo, DUO_GEN2_FIELDS, f"{inst} DUO_GEN2")
    from tools.gen2_fixtures import BY_NAME
    spec = BY_NAME.get(duo["case"])
    if spec is None or spec.title != duo["title"]:
        raise RuntimeError(f"{inst}: inconsistent title markers: case {duo['case']!r} does not belong to title {duo['title']!r}")
    return duo


def _boot_marker(inst, text):
    """SAVE_WITNESS + CLIENT for one instance, plus this instance's title cross-checked across
    its OWN markers (DUO_GEN2 always, RECEIPT when present) -- never a caller-supplied title.
    Returns (witness, client, title)."""
    witness = _last_tagged(text, "SAVE_WITNESS")
    if witness is None:
        raise RuntimeError(f"{inst}: missing SAVE_WITNESS marker")
    _require_fields(witness, SAVE_WITNESS_FIELDS, f"{inst} SAVE_WITNESS")
    client = _last_tagged(text, "CLIENT")
    if not client or client.get("title") not in ("crystal", "gold", "silver"):
        raise RuntimeError(f"{inst}: missing/invalid CLIENT title marker: {client}")
    title = client["title"]
    _require_fields(client, ("title", "rom_sha1"), f"{inst} CLIENT")

    duo = _duo_marker(inst, text)
    if duo["title"] != title or duo["rom_sha1"] != client.get("rom_sha1"):
        raise RuntimeError(f"{inst}: DUO_GEN2 title/rom_sha1 {duo['title']!r}/{duo['rom_sha1']!r} "
                           f"disagrees with CLIENT {title!r}/{client.get('rom_sha1')!r} -- "
                           f"inconsistent title markers")

    receipt = _last_tagged(text, "RECEIPT")
    if receipt is not None and (receipt.get("title") != title
                                or receipt.get("rom_sha1") != client.get("rom_sha1")):
        raise RuntimeError(f"{inst}: RECEIPT title/rom_sha1 {receipt.get('title')!r}/"
                           f"{receipt.get('rom_sha1')!r} disagrees with CLIENT/DUO_GEN2 "
                           f"{title!r}/{client.get('rom_sha1')!r} -- inconsistent title markers")

    return witness, client, title


def _hello_ot_id(inst, text):
    hello = _last_tagged(text, "HELLO")
    if not hello or not isinstance(hello.get("ot_id"), int):
        raise RuntimeError(f"{inst}: missing/invalid HELLO ot_id marker: {hello}")
    return hello["ot_id"]


def check_save_witness(results):
    """witness_validator: `witness(results)`, exactly one argument (see module docstring).

    For each of "a"/"b": derives this side's own title (cross-checked across its DUO_GEN2/CLIENT/
    RECEIPT markers), re-derives the flushed CartRAM hash from the file on disk (never trusts the
    driver's own `flushed_matches` claim alone), requires the save/gate counters agree, and
    requires gen2_codec's independent checksum/primary-backup/marker witness to pass. Raises
    RuntimeError naming the instance and field on any refusal; returns None.
    """
    _check_save_witness(results, ("a", "b"))


def _check_save_witness(results, instances):
    from server.adapters import gen2_codec as codec

    for inst in instances:
        text = (results or {}).get(inst) or ""
        witness, _client, title = _boot_marker(inst, text)

        if witness["cartram_bytes"] != CARTRAM_BYTES:
            raise RuntimeError(f"{inst}: SAVE_WITNESS cartram_bytes={witness['cartram_bytes']}, "
                               f"expected {CARTRAM_BYTES}")
        if witness["saveram_bytes"] != SAVERAM_BYTES:
            raise RuntimeError(f"{inst}: SAVE_WITNESS saveram_bytes={witness['saveram_bytes']}, "
                               f"expected {SAVERAM_BYTES} (CartRAM + 22-byte RTC trailer)")
        gate_saves, client_saves = witness.get("gate_saves"), witness.get("client_saves")
        if type(gate_saves) is not int or type(client_saves) is not int or gate_saves < 1 or gate_saves != client_saves:
            raise RuntimeError(f"{inst}: gate_saves={gate_saves} != client_saves={client_saves} "
                               f"(a save the client attempted was refused, or none landed) "
                               f"-- torn witness")
        if witness["flushed_matches"] is not True:
            raise RuntimeError(f"{inst}: SAVE_WITNESS flushed_matches={witness['flushed_matches']!r}"
                               f" -- the driver itself reports its dump disagreed with the file")
        sha = witness["cartram_sha256"]
        if not (isinstance(sha, str) and re.fullmatch(r"[0-9a-fA-F]{64}", sha)):
            raise RuntimeError(f"{inst}: SAVE_WITNESS cartram_sha256 is not a 64-hex sha256: {sha!r}")

        path = Path(witness["saveram_path"])
        if not path.is_file():
            raise RuntimeError(f"{inst}: SAVE_WITNESS saveram_path does not exist: {path}")
        blob = path.read_bytes()
        if len(blob) != witness["saveram_bytes"]:
            raise RuntimeError(f"{inst}: flushed save is {len(blob)} bytes, SAVE_WITNESS claims "
                               f"{witness['saveram_bytes']} -- torn save")
        cartram = blob[:CARTRAM_BYTES]
        computed = hashlib.sha256(cartram).hexdigest()
        if computed.lower() != sha.lower():
            raise RuntimeError(f"{inst}: independently recomputed sha256 {computed} does not "
                               f"match the driver's reported {sha} -- torn/mismatched witness")

        layout = codec.for_foundation(title)
        report = codec.strict_checksum_witness(cartram, layout)
        if not report["valid"]:
            raise RuntimeError(f"{inst}: independent checksum/primary-backup/marker witness "
                               f"refused: {report}")


def _ball_pocket(raw, layout):
    from tools.gen2_fixtures import _saved_field

    count = _saved_field(raw, layout, "wNumBalls", 1)[0]
    pocket = _saved_field(raw, layout, "wBalls", count * 2 + 1)
    return [(pocket[index * 2], pocket[index * 2 + 1]) for index in range(count)]


def _pair_oracle(results, *, data_dir, area_id="route_29", ot_ids=None, boot_saveram=None,
                 status="alive", snapshots=None):
    """post-result oracle: `oracle(results, **oracle_kwargs)` (see module docstring).

    Compares the two flushed saves (PYDEC via gen2_codec, each decoded with ITS OWN side's
    cross-checked title/layout) against the boot fixtures and the server's persisted
    `links.json` under `data_dir`. Refuses: a title/rom_sha1 marker mismatch, a checksum-invalid
    flushed or boot save, altered links.json, wrong area, an unchanged Ball pocket, identical
    full keys, a missing/torn witness, and a party mon without a matching server capture. Raises
    RuntimeError naming the instance/field on any refusal; returns None on success.

    `ot_ids`/`boot_saveram` are optional per-instance override dicts (unit-test escape hatch,
    see module docstring); a side missing from either mapping derives its own expected OT id
    from its HELLO marker and its own boot fixture from its DUO_GEN2 `case`.
    """
    from server.adapters import gen2_codec as codec

    ot_ids = dict(ot_ids) if ot_ids else {}
    boot_saveram = dict(boot_saveram) if boot_saveram else {}

    decoded = {}
    for inst in ("a", "b"):
        text = (results or {}).get(inst) or ""
        witness, _client, title = _boot_marker(inst, text)
        duo = _duo_marker(inst, text)
        capture = _last_tagged(text, "ENGINE_CAPTURE")
        if capture is None:
            raise RuntimeError(f"{inst}: missing ENGINE_CAPTURE marker")
        if capture.get("site_id") != "capture_party_finalized":
            raise RuntimeError(f"{inst}: ENGINE_CAPTURE site_id={capture.get('site_id')!r}, "
                               f"expected 'capture_party_finalized'")
        if capture.get("acquisition") != "wild" or capture.get("destination") != "party":
            raise RuntimeError(f"{inst}: ENGINE_CAPTURE acquisition/destination = "
                               f"{capture.get('acquisition')!r}/{capture.get('destination')!r}, "
                               f"expected 'wild'/'party'")
        if capture.get("area_id") != area_id:
            raise RuntimeError(f"{inst}: ENGINE_CAPTURE area_id={capture.get('area_id')!r}, "
                               f"expected {area_id!r}")

        layout = codec.for_foundation(title)
        path = snapshots[inst] if snapshots else witness["saveram_path"]
        flushed = Path(path).read_bytes()[:CARTRAM_BYTES]
        flushed_report = codec.strict_checksum_witness(flushed, layout)
        if not flushed_report["valid"]:
            raise RuntimeError(f"{inst}: flushed save fails the independent checksum/primary-"
                               f"backup/marker witness: {flushed_report}")

        boot_path = Path(boot_saveram[inst]) if inst in boot_saveram else _fixture_path(duo["case"])
        if not boot_path.is_absolute():
            boot_path = REPO_ROOT / boot_path
        boot_bytes = boot_path.read_bytes()
        boot = boot_bytes[:CARTRAM_BYTES]
        boot_report = codec.strict_checksum_witness(boot, layout)
        if not boot_report["valid"]:
            raise RuntimeError(f"{inst}: boot fixture {boot_path} fails the independent checksum/"
                               f"primary-backup/marker witness: {boot_report}")
        if hashlib.sha256(boot_bytes).hexdigest().lower() != duo["fixture_sha256"].lower():
            raise RuntimeError(f"{inst}: DUO_GEN2 fixture_sha256 differs from the selected boot fixture hash")

        boot_party = codec.decode_saved_party(boot, layout, copy_name="primary")["mons"]
        new_party = codec.decode_saved_party(flushed, layout, copy_name="primary")["mons"]
        boot_keys = [codec.key(mon) for mon in boot_party]
        new_keys = [codec.key(mon) for mon in new_party]
        if len(new_keys) != len(boot_keys) + 1:
            raise RuntimeError(f"{inst}: party has {len(new_keys)} mon(s), expected exactly one "
                               f"more than the boot fixture's {len(boot_keys)}: {new_keys}")
        if new_keys[:len(boot_keys)] != boot_keys:
            raise RuntimeError(f"{inst}: existing party mons changed identity: "
                               f"{new_keys[:len(boot_keys)]} != {boot_keys}")
        new_mon = new_party[-1]
        new_key = new_keys[-1]
        expected_ot = ot_ids[inst] if inst in ot_ids else _hello_ot_id(inst, text)
        if new_mon["ot_id"] != expected_ot:
            raise RuntimeError(f"{inst}: captured mon OT id {new_mon['ot_id']} != expected "
                               f"{expected_ot}")
        if capture.get("key") != new_key:
            raise RuntimeError(f"{inst}: ENGINE_CAPTURE key {capture.get('key')!r} disagrees "
                               f"with the flushed save's new party key {new_key!r}")
        if capture.get("species_id") != new_mon["species_id"] or capture.get("level") != new_mon["level"]:
            raise RuntimeError(f"{inst}: ENGINE_CAPTURE species/level differs from decoded capture")
        caught_lines = [line for line in text.splitlines() if line.startswith("CAUGHT ")]
        if not caught_lines or caught_lines[-1][len("CAUGHT "):] != new_key:
            raise RuntimeError(f"{inst}: CAUGHT line {caught_lines[-1:] or None} does not name "
                               f"the flushed save's new party key {new_key!r}")

        before_pocket, after_pocket = _ball_pocket(boot, layout), _ball_pocket(flushed, layout)
        before_total = sum(qty for _item, qty in before_pocket)
        after_total = sum(qty for _item, qty in after_pocket)
        if after_total >= before_total:
            raise RuntimeError(f"{inst}: Ball pocket did not decrease: {before_pocket} -> "
                               f"{after_pocket} -- unchanged Ball pocket")

        decoded[inst] = {"key": new_key, "species": new_mon["species_id"], "level": new_mon["level"], "title": title}

    if decoded["a"]["key"] == decoded["b"]["key"]:
        raise RuntimeError(f"both sides captured the identical full key {decoded['a']['key']!r}")

    links_path = Path(data_dir) / "links.json"
    if not links_path.is_file():
        raise RuntimeError(f"no links.json under data_dir: {links_path}")
    raw_links_text = links_path.read_text(encoding="utf-8")
    document = json.loads(raw_links_text)
    rows = document.get("links") or []
    statuses = {status} if isinstance(status, str) else set(status)
    matches = [row for row in rows if row.get("area_id") == area_id and row.get("status") in statuses]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one {status} {area_id!r} link in links.json, found "
                           f"{len(matches)}: {matches}")
    row = matches[0]
    for inst in ("a", "b"):
        mon = row.get(inst) or {}
        want = decoded[inst]
        if mon.get("key") != want["key"]:
            raise RuntimeError(f"links.json {inst}.key={mon.get('key')!r} != the flushed save's "
                               f"{want['key']!r} -- altered links.json")
        # Death-time level may differ after A's sacrifice battles. The link proof
        # compares capture-time levels; the faint proof binds final identity/HP instead.
        if mon.get("species") != want["species"] or status == "alive" and mon.get("level") != want["level"]:
            raise RuntimeError(f"links.json {inst} species/level {mon.get('species')}/"
                               f"{mon.get('level')} disagrees with the engine capture "
                               f"{want['species']}/{want['level']} -- altered links.json")

    # Nothing else in the persisted document may reference either newly-captured key: a second
    # occurrence would mean the server accepted something the two saves don't show. `mon_stats` is
    # excluded: it is per-mon bookkeeping keyed by every party mon's key (starters included), not an
    # acceptance (first physical C<->C duo 2026-09-23: the only other hit was mon_stats).
    bookkeeping = {"mon_stats"} | ({"pending_memorials"} if status != "alive" else set())
    accepted_text = json.dumps({k: v for k, v in document.items() if k not in bookkeeping})
    for inst in ("a", "b"):
        occurrences = accepted_text.count(decoded[inst]["key"])
        if occurrences != 1:
            raise RuntimeError(f"{inst}: key {decoded[inst]['key']} appears {occurrences} times "
                               f"in links.json, expected exactly once (the formed link) -- the "
                               f"server accepted something the saves don't show")
    return decoded, row, document


def _verified_facts(decoded, area_id, status):
    return {"a": decoded["a"]["key"], "b": decoded["b"]["key"], "area": area_id,
            "titles": "/".join(decoded[inst]["title"] for inst in ("a", "b")), "status": status}


def link_oracle(results, *, data_dir, area_id="route_29", ot_ids=None, boot_saveram=None, on_verified=None):
    """Require the independently decoded captures to form one alive server pair."""
    decoded, _, _ = _pair_oracle(results, data_dir=data_dir, area_id=area_id, ot_ids=ot_ids, boot_saveram=boot_saveram)
    if on_verified is not None:
        on_verified(_verified_facts(decoded, area_id, "alive"))


def _faint_need(condition, reason):
    if not condition:
        raise RuntimeError(f"faint: {reason}")


def _one_marker(text, tag):
    lines = [line for line in text.splitlines() if line.startswith(tag + " ")]
    _faint_need(len(lines) == 1, f"exactly one {tag} marker required")
    value = _last_tagged(text, tag)
    _faint_need(isinstance(value, dict), f"{tag} must be an object")
    return value


def _frame(row, field="frame"):
    value = row.get(field)
    _faint_need(type(value) is int and value >= 0, f"invalid {field}")
    return value


def _hex_bytes(value, size, label):
    _faint_need(isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]*", value) is not None
                and len(value) == size * 2, f"invalid {label} bytes")
    return bytes.fromhex(value)


def _faint_checkpoint(write, layout):
    """Check measured PC/bank, both anchors in both domains, caller and state predicates."""
    pack = json.loads((REPO_ROOT / f"data/games/gen2_{layout.title}/write_checkpoint.json").read_text())
    primary = pack["titles"][layout.title]["primary"]
    point = write["checkpoint"]
    _faint_need(isinstance(point, dict), "checkpoint observation missing")
    for field, expected in (("pc", primary["execution_before"]["pc"]),
                            ("hrom_bank", primary["execution_before"]["bank"])):
        _faint_need(type(point.get(field)) is int and point[field] == expected, f"checkpoint {field} differs")
    anchor = primary["anchors"]["ow_player_input"]["expected_hex"]
    _faint_need(_hex_bytes(point.get("anchor_hex"), len(anchor) // 2, "anchor") == bytes.fromhex(anchor),
                "mapped checkpoint anchor differs")
    anchors = point.get("anchors")
    _faint_need(isinstance(anchors, dict) and set(anchors) == set(primary["anchors"]),
                "checkpoint anchors missing or unrecognized")
    for name, source in primary["anchors"].items():
        observed = anchors[name]
        _faint_need(isinstance(observed, dict), f"checkpoint anchor {name} missing")
        expected = bytes.fromhex(source["expected_hex"])
        for domain in ("rom_hex", "mapped_hex"):
            _faint_need(_hex_bytes(observed.get(domain), len(expected), f"anchor {name}/{domain}") == expected,
                        f"checkpoint anchor {name}/{domain} differs")
    owner = primary["ownership_requirements"]
    svbk, sc = point.get("svbk"), point.get("sc")
    _faint_need(type(svbk) is int and 0 <= svbk <= 7
                and (svbk or 1) == owner["effective_wram_bank"], "checkpoint WRAM bank differs")
    serial = owner["serial_control"]
    _faint_need(type(sc) is int and 0 <= sc <= 255 and sc & serial["mask"] == serial["value"],
                "checkpoint serial owner active")
    stack = primary["caller_stack"]
    sp = point.get("sp")
    _faint_need(type(sp) is int and stack["minimum_sp"] <= sp
                and sp + stack["required_read_bytes"] <= stack["exclusive_stack_end"], "checkpoint SP outside stack")
    raw = _hex_bytes(point.get("stack_hex"), stack["required_read_bytes"], "caller stack")
    for word in stack["required_words"]:
        at = word["offset_from_sp"]
        _faint_need(int.from_bytes(raw[at:at + 2], word["endianness"]) == word["value"], "checkpoint caller differs")
    state = point.get("state")
    _faint_need(isinstance(state, dict), "checkpoint state missing")
    for predicate in primary["state_predicates"]:
        value = state.get(predicate["symbol"])
        _faint_need(predicate["operator"] == "masked_equal" and type(value) is int
                    and 0 <= value < 1 << (8 * predicate["width"])
                    and value & predicate["mask"] == predicate["value"],
                    f"checkpoint predicate {predicate['symbol']} refused")


def _faint_write(write, layout, linked, final, key):
    from server.adapters import gen2_codec as codec

    slot = write.get("slot")
    _faint_need(type(slot) is int and 0 <= slot < len(linked), "B write slot invalid")
    _faint_need(write.get("ok") is True and not write.get("error") and write.get("kind") == "party_hp"
                and write.get("key") == key and codec.key(linked[slot]) == key, "B write ownership/result differs")
    _faint_checkpoint(write, layout)
    n = layout.party_size * layout.constants["PARTY_LENGTH"]
    before = _hex_bytes(write.get("before_party_hex"), n, "before party")
    after = _hex_bytes(write.get("after_party_hex"), n, "after party")
    for index, mon in enumerate(linked):
        start = index * layout.party_size
        _faint_need(before[start:start + layout.party_size].hex() == mon["raw_hex"], "B write preimage differs from LINK_SAVE")
        _faint_need(after[start:start + layout.party_size].hex() == final[index]["raw_hex"], "B saved party differs from write readback")
    expected = bytearray(before)
    start = slot * layout.party_size
    status, hp = layout.constants["MON_STATUS"], layout.constants["MON_HP"]
    expected[start + status] = 0
    expected[start + hp:start + hp + 2] = bytes(2)
    _faint_need(after == bytes(expected), "B write changed bytes outside target HP/status")
    log = write.get("log")
    _faint_need(isinstance(log, list) and len(log) == 2, "B write must carry exactly two permit spans")
    profile = layout.profile["titles"][layout.title]
    for index, (offset, length) in enumerate(((status, 1), (hp, 2)), 1):
        row = log[index - 1]
        expected = {"domain": "System Bus", "addr": layout.addresses["wPartyMon1"] + start + offset,
                    "n": length, "why": "overworld", "status": "written", "completed": length,
                    "attempted": length, "batch_index": index, "batch_size": 2,
                    "site": "lua/gen2/entry.lua production", "evidence": "U2 PHYSICAL receipt",
                    "title": layout.title, "artifact": profile["artifact"], "rom_sha1": profile["rom_sha1"]}
        _faint_need(isinstance(row, dict) and all(type(row.get(k)) is type(v) and row[k] == v
                    for k, v in expected.items()) and not row.get("error"), "B permit span/provenance differs")


def _faint_oracle(results, *, data_dir, area_id, ot_ids, boot_saveram):
    from server.adapters import gen2_codec as codec

    check_save_witness(results)
    stages, snapshots, parties = {}, {}, {}
    for inst in ("a", "b"):
        text = results[inst]
        witness, client, title = _boot_marker(inst, text)
        _faint_need(client.get("production_admitted") is True, f"{inst}: not the production client")
        _faint_need(type(witness.get("gate_saves")) is int and type(witness.get("client_saves")) is int,
                    f"{inst}: save counters must be integers")
        if inst == "a":
            _faint_need(isinstance(client.get("registered_sites"), list)
                        and "battle_faint" in client["registered_sites"], "A production signals lack battle_faint")
        layout = codec.for_foundation(title)
        _faint_need(client.get("rom_sha1") == layout.profile["titles"][title]["rom_sha1"], f"{inst}: wrong ROM pin")
        stage = _one_marker(text, "LINK_SAVE")
        _faint_need(type(stage.get("gate_saves")) is int and type(stage.get("client_saves")) is int
                    and stage["gate_saves"] == stage["client_saves"] >= 1
                    and witness["gate_saves"] > stage["gate_saves"]
                    and witness["client_saves"] > stage["client_saves"], f"{inst}: final save counters are not newer than LINK_SAVE")
        _faint_need(_frame(stage, "save_completed_frame") <= _frame(stage)
                    and _frame(stage, "save_completed_frame") < _frame(witness, "save_completed_frame"),
                    f"{inst}: final save completion is not newer than LINK_SAVE")
        raw = Path(stage["saveram_path"]).read_bytes()
        _faint_need(stage.get("saveram_bytes") == len(raw) == SAVERAM_BYTES
                    and stage.get("cartram_bytes") == CARTRAM_BYTES
                    and hashlib.sha256(raw[:CARTRAM_BYTES]).hexdigest() == stage.get("cartram_sha256"),
                    f"{inst}: LINK_SAVE size/hash differs")
        _faint_need(codec.strict_checksum_witness(raw[:CARTRAM_BYTES], layout)["valid"], f"{inst}: LINK_SAVE checksum refused")
        linked = codec.decode_saved_party(raw[:CARTRAM_BYTES], layout, copy_name="primary")["mons"]
        saved = Path(witness["saveram_path"]).read_bytes()[:CARTRAM_BYTES]
        final = codec.decode_saved_party(saved, layout, copy_name="primary")["mons"]
        _faint_need(_frame(stage) < _frame(witness, "save_completed_frame") <= _frame(witness), f"{inst}: save chronology differs")
        stages[inst], snapshots[inst], parties[inst] = stage, stage["saveram_path"], (layout, linked, final, witness)
    decoded, row, document = _pair_oracle(results, data_dir=data_dir, area_id=area_id, ot_ids=ot_ids,
                                         boot_saveram=boot_saveram, status=("dead", "memorial"), snapshots=snapshots)
    _faint_need(row.get("cause") == "battle" and row.get("initiating_player") == "a" and row.get("killed_at"),
                "server death is not A's battle faint")
    for inst in ("a", "b"):
        _, linked, final, _ = parties[inst]
        key = decoded[inst]["key"]
        old_keys, new_keys = [codec.key(m) for m in linked], [codec.key(m) for m in final]
        _faint_need(len(set(old_keys)) == len(old_keys) and sorted(old_keys) == sorted(new_keys), f"{inst}: party identity changed")
        old, new = linked[old_keys.index(key)], final[new_keys.index(key)]
        _faint_need(stages[inst].get("key") == key and old["hp"] > 0 and new["hp"] == 0, f"{inst}: linked mon did not go alive to HP zero")
        if inst == "b":
            _faint_need(old_keys == new_keys, "B party order changed")
            for before, after in zip(linked, final, strict=True):
                expected = bytearray.fromhex(before["raw_hex"])
                if codec.key(before) == key:
                    expected[parties[inst][0].constants["MON_STATUS"]] = 0
                    at = parties[inst][0].constants["MON_HP"]
                    expected[at:at + 2] = bytes(2)
                _faint_need(after["raw_hex"] == expected.hex()
                            and all(after[field] == before[field] for field in ("ot_raw_hex", "nickname_raw_hex", "species_marker")),
                            "B other mons or target non-HP/status bytes changed")
    a_key, b_key = decoded["a"]["key"], decoded["b"]["key"]
    faint, sent = _one_marker(results["a"], "ENGINE_FAINT"), _one_marker(results["a"], "FAINT_SENT")
    _faint_need(faint.get("site_id") == "battle_faint" and faint.get("cause") == "battle"
                and faint.get("key") == sent.get("key") == a_key, "A faint event/key/cause differs")
    _faint_need(type(faint.get("slot")) is int and 0 <= faint["slot"] < len(parties["a"][2])
                and codec.key(parties["a"][2][faint["slot"]]) == a_key
                and type(sent.get("seq")) is int and sent["seq"] >= 0, "A faint slot/sequence invalid")
    _faint_need(_frame(stages["a"]) < _frame(faint) <= _frame(sent)
                <= _frame(parties["a"][3], "save_completed_frame"), "A faint chronology differs")
    _faint_need(not any(line.startswith("PARTY_HP_WRITE ") for line in results["a"].splitlines()), "A used a harness/permit faint instead of battle")
    writes = [(index, json.loads(line.removeprefix("PARTY_HP_WRITE ")))
              for index, line in enumerate(results["b"].splitlines()) if line.startswith("PARTY_HP_WRITE ")]
    _faint_need(1 <= len(writes) <= 2 and all(isinstance(row, dict) for _, row in writes),
                "one write and at most one idempotent repeat required")
    command = f"RX force_faint key={b_key}"
    commands = [index for index, line in enumerate(results["b"].splitlines()) if line == command]
    _faint_need(len(writes) <= len(commands) <= 2, "B lacks force_faint receipt or repeats exceed the lane budget")
    layout, linked, final, witness = parties["b"]
    previous = None
    for ordinal, (position, write) in enumerate(writes):
        _faint_need(commands[ordinal] < position, "B write precedes force_faint receipt")
        if previous is None:
            _faint_need(_frame(stages["b"]) < _frame(write) <= _frame(witness, "save_completed_frame"), "B write chronology differs")
        _faint_write(write, layout, linked if previous is None else final, final, b_key)
        if previous is not None:
            _faint_need(_frame(write) >= _frame(previous) and write["slot"] == previous["slot"]
                        and bytes.fromhex(write["before_party_hex"]) == bytes.fromhex(previous["after_party_hex"])
                        and bytes.fromhex(write["after_party_hex"]) == bytes.fromhex(write["before_party_hex"]),
                        "B repeat is not idempotent")
        previous = write
    log = (Path(data_dir) / "server.log").read_text(encoding="utf-8", errors="replace")
    issued = re.search(r"\[a\] faint → force_faint b:" + re.escape(b_key) + r"(?:\s|$)", log)
    _faint_need(issued, "server did not issue force_faint to B")
    if row["status"] == "memorial":
        # Gen 2 NACKs unsupported memorialization. The server finalizes the dead
        # pair anyway; require that ordered transition rather than accepting a
        # bare MEMORIAL claim or implying that a native box write succeeded.
        end = log.find(f"pair in {area_id} marked memorial (with failed memorialization)", issued.end())
        _faint_need(end >= 0, "server lacks failed-memorial transition after death")
        pending = document.get("pending_memorials")
        _faint_need(isinstance(pending, dict), "server memorial pending state missing")
        for inst in ("a", "b"):
            key = decoded[inst]["key"]
            pattern = rf"\[{inst}\] memorialize_failed key=" + re.escape(key[:8]) + r"(?:\s|$)"
            ack = re.search(pattern, log[issued.end():end])
            _faint_need(ack and isinstance(pending.get(inst), list) and key not in pending[inst],
                        f"server lacks settled {inst} memorial NACK after death")
    return _verified_facts(decoded, area_id, row["status"])


def faint_oracle(results, *, data_dir, area_id="route_29", ot_ids=None, boot_saveram=None, on_verified=None):
    """PYDEC death proof plus source-checked synchronous production party_hp write evidence."""
    try:
        facts = _faint_oracle(results, data_dir=data_dir, area_id=area_id, ot_ids=ot_ids, boot_saveram=boot_saveram)
        if on_verified is not None:
            on_verified(facts)
    except (KeyError, TypeError, ValueError, OSError, IndexError) as exc:
        raise RuntimeError(f"faint evidence missing or malformed: {exc}") from exc


def _admit_need(condition, reason):
    if not condition:
        raise RuntimeError(f"admit_wrong_rom: {reason}")


def _admit_markers(results, admitted, refused):
    _admit_need({admitted, refused} == {"a", "b"}, "explicit admitted/refused roles must be distinct")
    lock = json.loads((REPO_ROOT / "data/gen2_sources.lock.json").read_text())
    wrong_pin = lock["outputs"]["pokecrystal11"]["sha1"]
    heads = {}
    for inst, role in ((admitted, "admitted"), (refused, "refused")):
        text = results[inst]
        head, receipt = _one_marker(text, "DUO_GEN2"), _one_marker(text, "RECEIPT")
        _admit_need(head.get("player") == inst and head.get("scenario") == "gen2_admit_wrong_rom"
                    and head.get("expect_admission", "admitted") == role, f"{inst}: header role/scenario differs")
        for field in ("player", "scenario", "attempt", "title", "rom_sha1"):
            _admit_need(field in head and receipt.get(field) == head[field], f"{inst}: receipt {field} differs")
        _admit_need(receipt.get("schema") == "gen2-duo-admit-wrong-rom-v1"
                    and receipt.get("expect_admission") == role, f"{inst}: receipt role/schema differs")
        verdicts = [line for line in text.splitlines() if line.startswith("RESULT:")]
        _admit_need(len(verdicts) == 1 and re.match(r"^RESULT: PASS(?:\s|$)", verdicts[0]), f"{inst}: no sole PASS verdict")
        heads[inst] = head
    text = results[refused]
    head = heads[refused]
    _admit_need(head.get("title") == "crystal" and head.get("rom_sha1") == wrong_pin,
                "refused input must be pinned Crystal 1.1")
    for tag in ("CLIENT", "BOOTED", "MYKEY", "HELLO", "HELLO_AGAIN", "TX", "SAVE_WITNESS", "HOLD", "ENGINE_CAPTURE"):
        _admit_need(not any(line.startswith(tag + " ") for line in text.splitlines()), f"refused half printed {tag}")
    refusal, quiet, cart = (_one_marker(text, tag) for tag in ("ADMISSION_REFUSED", "NO_TRAFFIC", "CARTRAM_UNCHANGED"))
    _admit_need(refusal.get("client") is False and refusal.get("rom_sha1") == wrong_pin
                and isinstance(refusal.get("console"), str)
                and ("refused (production admission)" in refusal["console"] or "not a Gen 2 cartridge" in refusal["console"]),
                "refusal lacks pinned ROM or production refusal line")
    _admit_need(type(quiet.get("tx")) is int and quiet["tx"] == 0
                and type(quiet.get("frames")) is int and quiet["frames"] >= 600
                and _frame(quiet) >= _frame(refusal) + quiet["frames"], "refused hold/traffic differs")
    _admit_need(text.index("ADMISSION_REFUSED ") < text.index("NO_TRAFFIC ") < text.index("CARTRAM_UNCHANGED "),
                "refused marker chronology differs")
    receipt = _one_marker(text, "RECEIPT")
    _admit_need(receipt.get("refusal") == refusal and receipt.get("cartram_sha256") == cart.get("after"),
                "refused receipt evidence differs")
    text = results[admitted]
    witness, client, title = _boot_marker(admitted, text)
    from tools.gen2_source_data import load_context
    _admit_need(client.get("production_admitted") is True
                and client.get("rom_sha1") == load_context(title, root=REPO_ROOT).source_record()["rom_sha1"],
                "admitted half lacks production/pinned ROM")
    hello, hold = _one_marker(text, "HELLO"), _one_marker(text, "HOLD")
    _one_marker(text, "BOOTED")
    _admit_need(not any(line.startswith(("HELLO_AGAIN ", "ADMISSION_REFUSED ", "ENGINE_CAPTURE ")) for line in text.splitlines()),
                "admitted half rehelloed/refused/captured")
    _admit_need(type(hold.get("hellos")) is int and hold["hellos"] == 1
                and type(hold.get("frames")) is int and hold["frames"] >= 600
                and _frame(hold) >= _frame(hello) + hold["frames"]
                and _frame(witness, "save_completed_frame") > _frame(hold), "admitted hold/save chronology differs")
    return heads, cart


def check_admit_wrong_rom_witness(results, *, boot_saveram, refused_saveram, admitted="a", refused="b"):
    """Only the admitted role saves; the refused role must retain its independent seed image."""
    try:
        _heads, cart = _admit_markers(results, admitted, refused)
        _check_save_witness(results, (admitted,))
        boot = Path(boot_saveram[refused]).read_bytes()
        final = Path(refused_saveram).read_bytes()
        digest = hashlib.sha256(boot[:CARTRAM_BYTES]).hexdigest()
        _admit_need(len(boot) == len(final) == SAVERAM_BYTES and boot[:CARTRAM_BYTES] == final[:CARTRAM_BYTES],
                    "refused disk CartRAM differs from seed")
        _admit_need(cart.get("before") == cart.get("after") == digest, "refused CartRAM markers differ from seed")
    except (KeyError, TypeError, ValueError, OSError, IndexError) as exc:
        raise RuntimeError(f"admit_wrong_rom evidence missing or malformed: {exc}") from exc


def admit_wrong_rom_oracle(results, *, data_dir, before, after, boot_saveram, refused_saveram,
                            admitted="a", refused="b", on_verified=None):
    """Prove no refused server identity/traffic or save change, with one admitted native save."""
    from server.adapters import gen2_codec as codec

    try:
        check_admit_wrong_rom_witness(results, boot_saveram=boot_saveram, refused_saveram=refused_saveram,
                                      admitted=admitted, refused=refused)
        duo = _duo_marker(admitted, results[admitted])
        witness, _, title = _boot_marker(admitted, results[admitted])
        seed = Path(boot_saveram[admitted]).read_bytes()
        saved = Path(witness["saveram_path"]).read_bytes()
        _admit_need(hashlib.sha256(seed).hexdigest() == duo["fixture_sha256"], "admitted fixture hash differs")
        layout = codec.for_foundation(title)
        _admit_need(codec.strict_checksum_witness(seed[:CARTRAM_BYTES], layout)["valid"], "admitted seed checksum invalid")
        old = codec.decode_saved_party(seed[:CARTRAM_BYTES], layout, copy_name="primary")["mons"]
        new = codec.decode_saved_party(saved[:CARTRAM_BYTES], layout, copy_name="primary")["mons"]
        _admit_need(old and new == old, "admitted party changed during passive hold")
        hello_ot = _hello_ot_id(admitted, results[admitted])
        for label, snapshot in (("before", before), ("after", after)):
            players = snapshot["status"]["players"]
            live = snapshot["raw"]["_live"]["connected_players"]
            doc, events = snapshot["links"], snapshot["events"]
            _admit_need(isinstance(live, dict) and refused not in live and admitted in live,
                        f"{label}: refused player row or admitted row missing")
            active = players[admitted]
            # RESULT is followed by client.exit(); the final poll may see a closed
            # socket. The admission record and saved identity survive that close.
            _admit_need((label == "after" or active.get("connected") is True)
                        and active.get("admission") == "admitted"
                        and not active.get("identity_error"), f"{label}: admitted public status differs")
            idle = players.get(refused, {})
            _admit_need(not any(idle.get(field) for field in ("connected", "party_keys", "trainer_name", "current_area_id", "identity_error")),
                        f"{label}: refused public player adopted state")
            identities = doc["player_identity"]
            _admit_need(refused not in identities and str(identities[admitted]["ot_id"]) == str(hello_ot),
                        f"{label}: server identity lock differs")
            _admit_need(isinstance(events, list) and all(isinstance(row, dict) for row in events)
                        and not any(row.get("player") == refused for row in events), f"{label}: refused server event")
            hellos = [row for row in events if row.get("type") == "hello" and row.get("player") == admitted]
            _admit_need(len(hellos) == 1 and hellos[0].get("text", "").startswith("Connected ("),
                        f"{label}: missing sole accepted hello")
            _admit_need(doc["links"] == [] and doc.get("pending_captures", {}) == {}, f"{label}: unexpected link/capture")
        _admit_need(before["links"] == after["links"], "links.json changed across passive hold")
        _admit_need(before["events"] == after["events"], "server events changed across passive hold")
        for name in ("links", "events"):
            disk = json.loads((Path(data_dir) / f"{name}.json").read_text(encoding="utf-8"))
            _admit_need(disk == after[name], f"persisted {name} differs from final snapshot")
        if on_verified is not None:
            wrong = _one_marker(results[refused], "DUO_GEN2")
            on_verified({admitted: "admitted", refused: "refused", "area": "none", "status": "refused",
                         "titles": "/".join(title if side == admitted else "crystal" for side in ("a", "b")),
                         f"rom_{refused}": wrong["rom_sha1"]})
    except (KeyError, TypeError, ValueError, OSError, IndexError) as exc:
        raise RuntimeError(f"admit_wrong_rom evidence missing or malformed: {exc}") from exc


def _reconnect_need(condition, reason):
    if not condition:
        raise RuntimeError(f"reconnect: {reason}")


def _reconnect_pass(text):
    rows = [line for line in text.splitlines() if line.startswith("RESULT:")]
    _reconnect_need(len(rows) == 1 and re.match(r"^RESULT: PASS(?:\s|$)", rows[0]), "missing sole PASS verdict")


def _reconnect_head(text, player):
    from tools.gen2_source_data import load_context

    head, client = _one_marker(text, "DUO_GEN2"), _one_marker(text, "CLIENT")
    _duo_marker(player, text)
    _reconnect_need(head.get("player") == player and head.get("scenario") == "gen2_reconnect",
                    "player/scenario differs")
    pin = load_context(head["title"], root=REPO_ROOT).source_record()["rom_sha1"]
    _reconnect_need(head["rom_sha1"] == client.get("rom_sha1") == pin
                    and client.get("title") == head["title"] and client.get("production_admitted") is True,
                    "production client/title/ROM pin differs")
    _one_marker(text, "HELLO")
    _reconnect_need(not any(line.startswith("HELLO_AGAIN ") for line in text.splitlines()), "duplicate hello")
    return head


def _reconnect_receipt(text, head, phase):
    receipt = _one_marker(text, "RECEIPT")
    _reconnect_need(receipt.get("schema") == "gen2-duo-reconnect-v1" and receipt.get("phase") == phase,
                    "receipt schema/phase differs")
    for field in ("player", "scenario", "attempt", "case", "title", "rom_sha1", "fixture_sha256"):
        _reconnect_need(receipt.get(field) == head.get(field), f"receipt {field} differs")
    return receipt


def check_reconnect_witness(results, *, initial_results, relaunch_results, staged_saves):
    """Initial captures must save; only the two explicitly bound relaunch phases omit saving."""
    try:
        _reconnect_need(set(relaunch_results) == set(staged_saves) == {"same_save", "wrong_save"}, "both relaunches required")
        _reconnect_need(results["a"] == relaunch_results["wrong_save"] and results["b"] == initial_results["b"],
                        "final results do not name wrong-save A and held B")
        check_save_witness(initial_results)
        for inst in ("a", "b"):
            text = initial_results[inst]
            head = _reconnect_head(text, inst)
            ready, save, capture = (_one_marker(text, tag) for tag in ("RECONNECT_READY", "SAVE_WITNESS", "ENGINE_CAPTURE"))
            _reconnect_need(ready.get("phase") == "initial" and ready.get("player") == inst
                            and ready.get("key") == capture.get("key") and _frame(ready) >= _frame(save)
                            and text.index("SAVE_WITNESS ") < text.index("RECONNECT_READY "), "initial ready/save binding differs")
            if inst == "a":
                _reconnect_need(not any(line.startswith(("RESULT:", "RECEIPT ")) for line in text.splitlines()),
                                "initial A must be killed before verdict")
            else:
                _reconnect_pass(text)
                _reconnect_receipt(text, head, "initial")
                stayed = _one_marker(text, "B_STAYED")
                _reconnect_need(stayed.get("hellos") == 1 and stayed.get("force_faint") == stayed.get("box_mon") == 0
                                and _frame(stayed) >= _frame(ready), "B did not stay quiet")
                suffix = text[text.index("RECONNECT_READY "):]
                _reconnect_need(not re.search(r"^RX (?:force_faint|box_mon)(?:\s|$)", suffix, re.M), "B received a mutation command")
        original = _duo_marker("a", initial_results["a"])
        for phase in ("same_save", "wrong_save"):
            text = relaunch_results[phase]
            _reconnect_pass(text)
            head = _reconnect_head(text, "a")
            _one_marker(text, "BOOTED")
            back, hello = _one_marker(text, "RECONNECT_HELLO"), _one_marker(text, "HELLO")
            receipt = _reconnect_receipt(text, head, phase)
            _reconnect_need(head["title"] == original["title"] and head["case"] == f"{head['title']}_battle",
                            "relaunch title/battle case differs")
            seed = Path(staged_saves[phase]).read_bytes()
            _reconnect_need(head["fixture_sha256"] == hashlib.sha256(seed).hexdigest(), "staged save fingerprint differs")
            _reconnect_need(back.get("phase") == phase and back.get("hellos") == 1
                            and back.get("linked") is (phase == "same_save")
                            and back.get("ot_id") == hello.get("ot_id") and _frame(back) >= _frame(hello),
                            "relaunch hello/phase differs")
            for field in ("expected_key", "linked", "ot_id"):
                _reconnect_need(receipt.get(field) == back.get(field), f"relaunch receipt {field} differs")
            _reconnect_need(not any(line.startswith(("SAVE_WITNESS ", "ENGINE_CAPTURE ", "RECONNECT_READY ")) for line in text.splitlines()),
                            "relaunch unexpectedly played/saved")
            _reconnect_need(not re.search(r"^RX (?:force_faint|box_mon)(?:\s|$)", text, re.M), "A relaunch received mutation command")
            if phase == "wrong_save":
                hud = _one_marker(text, "WRONG_SAVE_HUD")
                target = "[x] WRONG SAVE: slot A"
                messages = [json.loads(line[len("RX_TEXT "):]) for line in text.splitlines() if line.startswith("RX_TEXT ")]
                _reconnect_need(hud.get("text") == target and _frame(hud) >= _frame(back)
                                and any(isinstance(row, dict) and row.get("cmd") == "hud_show" and row.get("text") == target
                                        and _frame(row) >= _frame(hello) for row in messages), "wrong-save HUD missing or early")
            else:
                _reconnect_need(not any(line.startswith("WRONG_SAVE_HUD ") for line in text.splitlines()), "same save refused")
    except (KeyError, TypeError, ValueError, OSError, IndexError, AttributeError) as exc:
        raise RuntimeError(f"reconnect evidence missing or malformed: {exc}") from exc


def reconnect_oracle(results, *, data_dir, initial_results, relaunch_results, boot_saveram,
                     staged_saves, relaunch_saves, snapshots, on_verified=None):
    """Independent saved identities and unchanged links across a kill and both required reconnects."""
    from server.adapters import gen2_codec as codec
    from tests.live.test_gen2_new_gates import qualified_identity
    from tools.gen2_fixtures import _saved_field

    try:
        check_reconnect_witness(results, initial_results=initial_results, relaunch_results=relaunch_results,
                                 staged_saves=staged_saves)
        decoded, _, document = _pair_oracle(initial_results, data_dir=data_dir, boot_saveram=boot_saveram)
        title, linked_key = decoded["a"]["title"], decoded["a"]["key"]
        layout = codec.for_foundation(title)
        witness = _one_marker(initial_results["a"], "SAVE_WITNESS")
        initial_raw = Path(witness["saveram_path"]).read_bytes()
        original_ot = int.from_bytes(_saved_field(initial_raw, layout, "wPlayerID", 2), "big")
        _reconnect_need(_hello_ot_id("a", initial_results["a"]) == original_ot, "initial trainer OT differs from save")
        for phase in ("same_save", "wrong_save"):
            seed, flushed = Path(staged_saves[phase]).read_bytes(), Path(relaunch_saves[phase]).read_bytes()
            _reconnect_need(len(seed) == len(flushed) == SAVERAM_BYTES, "relaunch save size differs")
            _reconnect_need(codec.strict_checksum_witness(seed[:CARTRAM_BYTES], layout)["valid"]
                            and codec.strict_checksum_witness(flushed[:CARTRAM_BYTES], layout)["valid"], "relaunch checksum refused")
            old = codec.decode_saved_party(seed[:CARTRAM_BYTES], layout, copy_name="primary")["mons"]
            new = codec.decode_saved_party(flushed[:CARTRAM_BYTES], layout, copy_name="primary")["mons"]
            ot = int.from_bytes(_saved_field(seed, layout, "wPlayerID", 2), "big")
            _reconnect_need(old and old == new and ot == int.from_bytes(_saved_field(flushed, layout, "wPlayerID", 2), "big"),
                            "relaunch saved party/trainer changed")
            back = _one_marker(relaunch_results[phase], "RECONNECT_HELLO")
            _reconnect_need(back["expected_key"] == linked_key and back["ot_id"] == ot,
                            "relaunch marker identity differs from decoded save")
            keys = [codec.key(mon) for mon in new]
            if phase == "same_save":
                _reconnect_need(seed == initial_raw and ot == original_ot and linked_key in keys, "same-save seed lost initial linked image")
            else:
                qualified_ot = qualified_identity(f"{title}_battle_ot2", seed, repo=REPO_ROOT)
                _reconnect_need(qualified_ot == ot != original_ot and linked_key not in keys,
                                "wrong-save seed is not qualified other-OT battle input")
        _reconnect_need(set(snapshots) == {"initial", "disconnected", "same_save", "before_wrong", "wrong_save"},
                        "all five server snapshots required")
        baseline = snapshots["initial"]
        identities = baseline["links"]["player_identity"]
        _reconnect_need(str(identities["a"]["ot_id"]) == str(original_ot), "initial server identity differs")
        for inst in ("a", "b"):
            hellos = [row for row in baseline["events"] if row.get("type") == "hello" and row.get("player") == inst]
            _reconnect_need(len(hellos) == 1 and hellos[0].get("text", "").startswith("Connected ("),
                            "initial server needs exactly one accepted hello per side")
        # mon_stats is a display cache refreshed by hello/tick, not encounter/identity state.
        # Reconnect may flush the latest cache; every persisted rule field must stay fixed.
        rule_state = {key: value for key, value in baseline["links"].items() if key != "mon_stats"}
        for phase, snap in snapshots.items():
            players = snap["status"]["players"]
            _reconnect_need(players["b"].get("connected") is True and not players["b"].get("identity_error"), "B disconnected or rejected")
            _reconnect_need(snap["links"]["links"] == baseline["links"]["links"]
                            and snap["links"]["player_identity"] == identities
                            and snap["links"].get("pending_captures", {}) == baseline["links"].get("pending_captures", {}),
                            f"{phase}: link/identity/pending changed")
            _reconnect_need({key: value for key, value in snap["links"].items() if key != "mon_stats"} == rule_state,
                            f"{phase}: persisted rule state changed")
            if phase in ("disconnected", "before_wrong"):
                _reconnect_need(players["a"].get("connected") is False, f"{phase}: A never disconnected")
            elif phase == "wrong_save":
                _reconnect_need("Identity mismatch for slot A" in players["a"].get("identity_error", ""), "wrong-save server rejection absent")
            else:
                _reconnect_need(players["a"].get("connected") is True and not players["a"].get("identity_error")
                                and linked_key in players["a"].get("party_keys", []), f"{phase}: A link not adopted")
        _reconnect_need(snapshots["disconnected"]["events"] == baseline["events"], "events changed while disconnected")
        for old_phase, new_phase, text in (("initial", "same_save", "Connected ("),
                                          ("before_wrong", "wrong_save", "REJECTED — wrong save/slot")):
            old, new = snapshots[old_phase]["events"], snapshots[new_phase]["events"]
            _reconnect_need(isinstance(old, list) and isinstance(new, list) and len(new) == len(old) + 1 and new[1:] == old,
                            f"{new_phase}: event history changed beyond one hello")
            row = new[0]
            _reconnect_need(row.get("player") == "a" and row.get("type") == "hello"
                            and (row.get("text", "").startswith(text) if new_phase == "same_save" else row.get("text") == text),
                            f"{new_phase}: missing expected server hello")
        _reconnect_need(snapshots["same_save"]["events"] == snapshots["before_wrong"]["events"], "events changed between relaunches")
        _reconnect_need(snapshots["before_wrong"]["links"] == snapshots["wrong_save"]["links"], "wrong save changed persisted state")
        _reconnect_need(document == snapshots["wrong_save"]["links"], "final links differ from wrong-save snapshot")
        disk_events = json.loads((Path(data_dir) / "events.json").read_text(encoding="utf-8"))
        _reconnect_need(disk_events == snapshots["wrong_save"]["events"], "final events differ from wrong-save snapshot")
        if on_verified is not None:
            on_verified(_verified_facts(decoded, "route_29", "alive"))
    except (KeyError, TypeError, ValueError, OSError, IndexError, AttributeError, AssertionError) as exc:
        raise RuntimeError(f"reconnect evidence missing or malformed: {exc}") from exc


def soft_reset_oracle(results, *, data_dir, before, after, boot_saveram, on_verified=None):
    """Both native saves preserve the party; one WRAM-clear reset produces one same-OT rehello."""
    from server.adapters import gen2_codec as codec
    from tools.gen2_fixtures import _saved_field
    from tools.gen2_source_data import load_context

    def need(condition, reason):
        if not condition:
            raise RuntimeError(f"soft_reset: {reason}")

    try:
        check_save_witness(results)
        titles, identities = {}, {}
        reset_tags = ("HELLO_AT_CHECKPOINT", "CHORD_GATE", "CHORD", "RESET_SEEN", "HELLO_CLEARED",
                      "WRITES_PAUSED", "REBOOTED", "WRITES_RESUMED", "HELLO_AGAIN", "REHELLO", "NO_WRITES_IN_WINDOW")
        for inst in ("a", "b"):
            text = results[inst]
            _reconnect_pass(text)
            head = _one_marker(text, "DUO_GEN2")
            witness, client, title = _boot_marker(inst, text)
            hello, receipt, booted = (_one_marker(text, tag) for tag in ("HELLO", "RECEIPT", "BOOTED"))
            need(head.get("player") == inst and head.get("scenario") == "gen2_soft_reset", "player/scenario differs")
            need(client.get("production_admitted") is True
                 and head["rom_sha1"] == load_context(title, root=REPO_ROOT).source_record()["rom_sha1"], "production/pinned ROM differs")
            need(receipt.get("schema") == "gen2-duo-soft-reset-v1" and receipt.get("input_mode") == "normal_buttons"
                 and receipt.get("harness_write_scopes") == [], "receipt schema/input/write scopes differ")
            for field in ("player", "scenario", "attempt", "case", "title", "rom_sha1", "fixture_sha256"):
                need(receipt.get(field) == head.get(field), f"{inst}: receipt {field} differs")
            for field, value in (("hello", hello), ("client", client), ("save", witness), ("booted", booted)):
                need(receipt.get(field) == value, f"{inst}: receipt {field} evidence differs")
            need(not any(line.startswith(("ENGINE_CAPTURE ", "PARTY_HP_WRITE ")) for line in text.splitlines()), "capture/write during passive reset")
            layout = codec.for_foundation(title)
            seed, final = Path(boot_saveram[inst]).read_bytes(), Path(witness["saveram_path"]).read_bytes()
            need(len(seed) == SAVERAM_BYTES and hashlib.sha256(seed).hexdigest() == head["fixture_sha256"], "boot fixture hash/size differs")
            need(codec.strict_checksum_witness(seed[:CARTRAM_BYTES], layout)["valid"], "boot checksum refused")
            old = codec.decode_saved_party(seed[:CARTRAM_BYTES], layout, copy_name="primary")["mons"]
            new = codec.decode_saved_party(final[:CARTRAM_BYTES], layout, copy_name="primary")["mons"]
            ot = int.from_bytes(_saved_field(seed, layout, "wPlayerID", 2), "big")
            need(old and old == new, "saved party changed across passive reset")
            need(ot == int.from_bytes(_saved_field(final, layout, "wPlayerID", 2), "big") == hello.get("ot_id"), "saved/hello trainer identity differs")
            titles[inst], identities[inst] = title, ot
            if inst == "a":
                rows = {tag: _one_marker(text, tag) for tag in reset_tags}
                # Main's HELLO_AGAIN can arrive during CONTINUE before REBOOTED is logged.
                ordered = ("HELLO", "HELLO_AT_CHECKPOINT", "CHORD_GATE", "CHORD", "RESET_SEEN",
                           "HELLO_CLEARED", "WRITES_PAUSED", "REBOOTED", "WRITES_RESUMED", "REHELLO",
                           "NO_WRITES_IN_WINDOW", "SAVE_WITNESS")
                need(all(text.index(left + " ") < text.index(right + " ") for left, right in zip(ordered, ordered[1:], strict=False)),
                     "reset markers out of order")
                at, chord, reset = rows["HELLO_AT_CHECKPOINT"], rows["CHORD"], rows["RESET_SEEN"]
                need(at.get("writes_enabled") is True and at.get("hellos") == 1 and at.get("ot_id") == ot,
                     "reset did not start admitted with writes enabled")
                need(type(chord.get("frames")) is int and chord["frames"] == 4
                     and _frame(rows["CHORD_GATE"]) <= _frame(chord), "native chord differs")
                for tag, start, low, high in (("RESET_SEEN", chord, 30, 60), ("HELLO_CLEARED", reset, 0, 180),
                                             ("WRITES_PAUSED", reset, 180, 420), ("WRITES_RESUMED", reset, 0, None)):
                    row = rows[tag]
                    delta = _frame(row) - _frame(start)
                    need(type(row.get("delta")) is int and row["delta"] == delta
                         and delta >= low and (high is None or delta <= high), f"{tag}: measured delta outside reset window")
                again, rehello, resumed = rows["HELLO_AGAIN"], rows["REHELLO"], rows["WRITES_RESUMED"]
                need(again.get("n") == rehello.get("hellos") == 2 and again.get("ot_id") == rehello.get("ot_id") == ot,
                     "reset rehello count/identity differs")
                need(_frame(rows["WRITES_PAUSED"]) <= _frame(again) <= _frame(rehello)
                     and _frame(rows["REBOOTED"]) <= _frame(resumed) <= _frame(rehello)
                     and _frame(witness, "save_completed_frame") > _frame(rehello), "resume/rehello/save chronology differs")
                need(type(rows["NO_WRITES_IN_WINDOW"].get("writes")) is int and rows["NO_WRITES_IN_WINDOW"]["writes"] == 0,
                     "write in reset window")
                for field, tag in (("reset", "RESET_SEEN"), ("paused", "WRITES_PAUSED"), ("rehello", "REHELLO")):
                    need(receipt.get(field) == rows[tag], f"receipt {field} differs")
            else:
                need(not any(line.startswith(tuple(tag + " " for tag in reset_tags)) for line in text.splitlines()), "idle partner reset/rehelloed")
                idle = _one_marker(text, "IDLE_PARTNER")
                need(idle.get("hellos") == 1 and receipt.get("idle") == idle
                     and _frame(hello) <= _frame(idle) < _frame(witness, "save_completed_frame"), "idle partner hold/save differs")
        for label, snapshot in (("before", before), ("after", after)):
            document = snapshot["links"]
            need(document["links"] == [] and document.get("pending_captures", {}) == {}, "unexpected link/capture")
            for inst in ("a", "b"):
                player = snapshot["status"]["players"][inst]
                need((label != "before" or player.get("connected") is True) and not player.get("identity_error"),
                     f"{label}: missing initial connection/rejected {inst}")
                need(str(document["player_identity"][inst]["ot_id"]) == str(identities[inst]), f"{label}: server trainer identity differs")
                hellos = [row for row in snapshot["events"] if row.get("type") == "hello" and row.get("player") == inst]
                count = 2 if label == "after" and inst == "a" else 1
                need(len(hellos) == count and all(row.get("text", "").startswith("Connected (") for row in hellos),
                     f"{label}: accepted hello count differs")
        need(before["links"] == after["links"], "persisted rules/identity changed across reset")
        need(isinstance(before["links_bytes"], bytes) and before["links_bytes"] == after["links_bytes"]
             and json.loads(before["links_bytes"]) == before["links"], "links.json bytes changed across reset")
        need(len(after["events"]) == len(before["events"]) + 1 and after["events"][1:] == before["events"]
             and after["events"][0].get("player") == "a" and after["events"][0].get("type") == "hello",
             "event history changed beyond one A rehello")
        for name in ("links", "events"):
            need(json.loads((Path(data_dir) / f"{name}.json").read_text(encoding="utf-8")) == after[name], f"final {name} differs from snapshot")
        need((Path(data_dir) / "links.json").read_bytes() == after["links_bytes"], "final links.json bytes differ")
        if on_verified is not None:
            on_verified({"a": "reset", "b": "idle", "area": "none", "titles": "/".join(titles[inst] for inst in ("a", "b")),
                         "status": "unchanged"})
    except (KeyError, TypeError, ValueError, OSError, IndexError, AttributeError) as exc:
        raise RuntimeError(f"soft_reset evidence missing or malformed: {exc}") from exc
