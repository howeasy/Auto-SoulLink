"""Independent Gen 2 duo oracles: the `gen2_new` family's witness_validator and the
`link` scenario's post-result oracle (docs/gen2/reviews/P3B7_PLAN_CODEX_2026-09-23.md, card H2).

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
    # "oracle_kwargs": {} -- the defaults below already match the shipped C<->C pairing
    # (crystal_battle OT 46401 <-> crystal_battle_ot2 OT 44068 on Route 29).

Both raise RuntimeError (never return False) naming the instance and the exact reason on any
refusal; both return None on success. `validate_pipeline` binds `witness(results)` with zero
kwargs and `oracle(results, **oracle_kwargs)`, so `check_save_witness` takes exactly one
positional argument and every other `link_oracle` parameter besides `results` must be a keyword.

## Per-instance result-text markers this module parses (H1 driver contract, fixed 2026-09-23)

One JSON object on the same line as its tag, in each instance's `results[inst]` text
(`D.result`); the LAST occurrence of a repeated tag wins:

- `SAVE_WITNESS {...}`: frame, save_completed_frame, gate_saves, client_saves, cartram_sha256
  (sha256 of CartRAM[0:0x8000] -- the first 32768 bytes of the flushed file), cartram_bytes
  (32768), saveram_path (absolute, forward slashes), saveram_bytes (32768 + 22 = 32790, the
  22-byte RTC trailer included), flushed_matches (bool, the driver's own claim -- re-verified
  here independently, never trusted alone).
- `CLIENT {...}`: qualification, production_admitted, pack, title ("crystal"/"gold"/"silver"),
  rom_sha1. Only `title` is consumed here, to select the gen2_codec layout.
- `ENGINE_CAPTURE {...}`: frame, site_id, acquisition, area_id, destination, slot, key,
  species_id, level. Cross-checked against the independently PYDEC-decoded flushed party.

`check_save_witness` only needs `SAVE_WITNESS` + `CLIENT` (saveram_path is absolute, so no
runner/data_dir dependency). `link_oracle` additionally needs `ENGINE_CAPTURE`, the two boot
fixtures (committed SaveRAM this scenario always boots from) and the server's persisted
`links.json` under `data_dir`.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_OT_IDS = {"a": 46401, "b": 44068}
DEFAULT_BOOT_SAVERAM = {
    "a": "tests/fixtures/gen2/crystal_battle.SaveRAM",
    "b": "tests/fixtures/gen2/crystal_battle_ot2.SaveRAM",
}

SAVE_WITNESS_FIELDS = ("frame", "save_completed_frame", "gate_saves", "client_saves",
                       "cartram_sha256", "cartram_bytes", "saveram_path", "saveram_bytes",
                       "flushed_matches")
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
    missing = [field for field in fields if field not in marker]
    if missing:
        raise RuntimeError(f"{label} marker missing field(s) {missing}: {marker}")


def _boot_marker(inst, text):
    """SAVE_WITNESS + CLIENT for one instance, validated just enough to resolve a layout."""
    witness = _last_tagged(text, "SAVE_WITNESS")
    if witness is None:
        raise RuntimeError(f"{inst}: missing SAVE_WITNESS marker")
    _require_fields(witness, SAVE_WITNESS_FIELDS, f"{inst} SAVE_WITNESS")
    client = _last_tagged(text, "CLIENT")
    if not client or client.get("title") not in ("crystal", "gold", "silver"):
        raise RuntimeError(f"{inst}: missing/invalid CLIENT title marker: {client}")
    return witness, client


def check_save_witness(results):
    """witness_validator: `witness(results)`, exactly one argument (see module docstring).

    For each of "a"/"b": re-derives the flushed CartRAM hash from the file on disk (never
    trusts the driver's own `flushed_matches` claim alone), requires the save/gate counters
    agree, and requires gen2_codec's independent checksum/primary-backup/marker witness to
    pass. Raises RuntimeError naming the instance and field on any refusal; returns None.
    """
    from server.adapters import gen2_codec as codec

    for inst in ("a", "b"):
        text = (results or {}).get(inst) or ""
        witness, client = _boot_marker(inst, text)

        if witness["cartram_bytes"] != CARTRAM_BYTES:
            raise RuntimeError(f"{inst}: SAVE_WITNESS cartram_bytes={witness['cartram_bytes']}, "
                               f"expected {CARTRAM_BYTES}")
        if witness["saveram_bytes"] != SAVERAM_BYTES:
            raise RuntimeError(f"{inst}: SAVE_WITNESS saveram_bytes={witness['saveram_bytes']}, "
                               f"expected {SAVERAM_BYTES} (CartRAM + 22-byte RTC trailer)")
        gate_saves, client_saves = witness.get("gate_saves"), witness.get("client_saves")
        if not gate_saves or gate_saves != client_saves:
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

        layout = codec.for_foundation(client["title"])
        report = codec.strict_checksum_witness(cartram, layout)
        if not report["valid"]:
            raise RuntimeError(f"{inst}: independent checksum/primary-backup/marker witness "
                               f"refused: {report}")


def _ball_pocket(raw, layout):
    from tools.gen2_fixtures import _saved_field

    count = _saved_field(raw, layout, "wNumBalls", 1)[0]
    pocket = _saved_field(raw, layout, "wBalls", count * 2 + 1)
    return [(pocket[index * 2], pocket[index * 2 + 1]) for index in range(count)]


def link_oracle(results, *, data_dir, area_id="route_29", ot_ids=None, boot_saveram=None):
    """post-result oracle: `oracle(results, **oracle_kwargs)` (see module docstring).

    Compares the two flushed saves (PYDEC via gen2_codec) against the boot fixtures and the
    server's persisted `links.json` under `data_dir`. Refuses: altered links.json, wrong area,
    an unchanged Ball pocket, identical full keys, a missing/torn witness, and a party mon
    without a matching server capture. Raises RuntimeError naming the instance/field on any
    refusal; returns None on success.
    """
    from server.adapters import gen2_codec as codec

    ot_ids = dict(DEFAULT_OT_IDS if ot_ids is None else ot_ids)
    boot_saveram = dict(DEFAULT_BOOT_SAVERAM if boot_saveram is None else boot_saveram)

    decoded = {}
    for inst in ("a", "b"):
        text = (results or {}).get(inst) or ""
        witness, client = _boot_marker(inst, text)
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

        layout = codec.for_foundation(client["title"])
        flushed = Path(witness["saveram_path"]).read_bytes()[:CARTRAM_BYTES]
        boot_path = Path(boot_saveram[inst])
        if not boot_path.is_absolute():
            boot_path = REPO_ROOT / boot_path
        boot = boot_path.read_bytes()[:CARTRAM_BYTES]

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
        if new_mon["ot_id"] != ot_ids[inst]:
            raise RuntimeError(f"{inst}: captured mon OT id {new_mon['ot_id']} != expected "
                               f"{ot_ids[inst]}")
        if capture.get("key") != new_key:
            raise RuntimeError(f"{inst}: ENGINE_CAPTURE key {capture.get('key')!r} disagrees "
                               f"with the flushed save's new party key {new_key!r}")
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

        decoded[inst] = {"key": new_key, "species": new_mon["species_id"], "level": new_mon["level"]}

    if decoded["a"]["key"] == decoded["b"]["key"]:
        raise RuntimeError(f"both sides captured the identical full key {decoded['a']['key']!r}")

    links_path = Path(data_dir) / "links.json"
    if not links_path.is_file():
        raise RuntimeError(f"no links.json under data_dir: {links_path}")
    raw_links_text = links_path.read_text(encoding="utf-8")
    document = json.loads(raw_links_text)
    rows = document.get("links") or []
    matches = [row for row in rows if row.get("area_id") == area_id and row.get("status") == "alive"]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one alive {area_id!r} link in links.json, found "
                           f"{len(matches)}: {matches}")
    row = matches[0]
    for inst in ("a", "b"):
        mon = row.get(inst) or {}
        want = decoded[inst]
        if mon.get("key") != want["key"]:
            raise RuntimeError(f"links.json {inst}.key={mon.get('key')!r} != the flushed save's "
                               f"{want['key']!r} -- altered links.json")
        if mon.get("species") != want["species"] or mon.get("level") != want["level"]:
            raise RuntimeError(f"links.json {inst} species/level {mon.get('species')}/"
                               f"{mon.get('level')} disagrees with the engine capture "
                               f"{want['species']}/{want['level']} -- altered links.json")

    # Nothing else in the persisted document may reference either newly-captured key: a second
    # occurrence would mean the server accepted something the two saves don't show.
    for inst in ("a", "b"):
        occurrences = raw_links_text.count(decoded[inst]["key"])
        if occurrences != 1:
            raise RuntimeError(f"{inst}: key {decoded[inst]['key']} appears {occurrences} times "
                               f"in links.json, expected exactly once (the formed link) -- the "
                               f"server accepted something the saves don't show")
