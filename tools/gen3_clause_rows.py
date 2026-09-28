"""Gen 3 live rule rows; independent ROM facts, wire and flushed-save oracles.

Carriers follow Gen 1 species/type/PC rows and Gen 2 gender. No emulator entry
point here. SYNTH setup is not a rule verdict; only the native run can qualify.
"""
from __future__ import annotations

import json
import os
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class ClauseUnobserved(RuntimeError):
    """The cartridge took a valid RNG branch that did not exercise the clause."""


def species_facts(rom: bytes, title: str) -> dict:
    """Read the booted title's own species/evolution tables, never adapter expectations.

    Vanilla heads/sizes: pinned per-title .sym. RR heads/16-slot stride:
    gen3_fixtures.py RR-SYNTH ROM derivation. RR's base-stat pointer is read
    from its own profile literal; evolution uses the RR-SYNTH pointer witnesses.
    """
    from server.adapters.gen3_rom_tables import table_symbols
    if title == "radical_red":
        # Companion rebuilds change the whole-image hash. Admission is the
        # production loader's job; these table bindings require the existing
        # RR-SYNTH pointer witnesses, not one historical companion hash.
        p = json.loads((ROOT / "data/games/gen3_rr/profile.json").read_text())["titles"][title]
        anchor = p["_rom_anchors"]["box_level"]
        expected = bytes.fromhex(anchor["expected_hex"])
        if rom[anchor["rom_offset"]:anchor["rom_offset"] + len(expected)] != expected:
            raise ValueError("RR rule tables: box_level pointer anchor changed")
        if any(struct.unpack_from("<I", rom, at)[0] != 0x097CD9B0 for at in (0x42F6C, 0x42FBC, 0x43138)):
            raise ValueError("RR rule tables: evolution pointer witnesses changed")
        names = json.loads((ROOT / "data/games/gen3_frlge/rr_species.json").read_text())
        known = {int(k) for k in names if int(k) > 0}
        count, slots, evo = max(known) + 1, 16, 0x097CD9B0
        stats = struct.unpack_from("<I", rom, 0x1BC)[0]
        if stats != 0x097B98EC:
            raise ValueError("RR rule tables: base-stat pointer changed")
    else:
        symbols = table_symbols(title)
        count = symbols["gSpeciesInfo"]["count"]
        known = set(range(1, min(count, 412)))
        stats, evo, slots = symbols["gSpeciesInfo"]["address"], symbols["gEvolutionTable"]["address"], 5
    parent = {s: s for s in known}

    def root(s):
        while parent[s] != s:
            s = parent[s]
        return s

    for s in known:
        for slot in range(slots):
            method, _, target = struct.unpack_from("<HHH", rom, evo - 0x08000000 + (s * slots + slot) * 8)
            if method and target in known:
                a, b = root(s), root(target)
                parent[max(a, b)] = min(a, b)
    out = {}
    for s in known:
        raw = rom[stats - 0x08000000 + s * 28:stats - 0x08000000 + (s + 1) * 28]
        if len(raw) != 28:
            raise ValueError(f"truncated {title} species {s}")
        out[str(s)] = {"types": [raw[6], raw[7]], "gender_ratio": raw[16], "family": root(s)}
    return out


def same_family(facts, a, b):
    try:
        return facts[str(a)]["family"] == facts[str(b)]["family"]
    except KeyError as exc:
        raise ValueError(f"unproven species {exc.args[0]}") from exc


def gender(facts, species, key):
    ratio = facts[str(species)]["gender_ratio"]
    if ratio == 255:
        return "genderless"
    return "female" if ratio == 254 or (int(key.split(":")[0], 16) & 255) < ratio else "male"


def rows(text, tag):
    return [json.loads(raw) for raw in re.findall(r"^" + re.escape(tag) + r" (\{.*\})$", text or "", re.M)]


def one(text, tag):
    found = rows(text, tag)
    if len(found) != 1:
        raise RuntimeError(f"expected exactly one {tag}, got {len(found)}")
    return found[0]


def release_membership(saved, fixture, released, key_of):
    party, boxes = saved
    fp, fb = fixture
    problems = []
    if [key_of(m) for m in party] != [key_of(m) for m in fp if key_of(m) != released]:
        problems.append("released key remains or a surviving party member changed")
    if {p: key_of(m) for p, m in boxes.items()} != {p: key_of(m) for p, m in fb.items()}:
        problems.append("release changed another box or left a boxed copy")
    return problems


def own_facts(run, inst):
    cache = run.__dict__.setdefault("_clause_facts", {})
    if inst not in cache:
        path = ROOT / run._gen3_rom(inst)
        cache[inst] = species_facts(path.read_bytes(), run._gen3_title(inst))
    return cache[inst]


def orchestrate_clause(run, *, helpers=None):
    import e2e_duo as h
    h = helpers or h  # script entrypoints own distinct __main__ exception classes
    try:
        return _orchestrate_clause(run)
    except h.ClientFinishedEarly:
        # Let the surviving carrier print its exact consequence before cleanup;
        # the existing Gen 1 classifier then judges BOTH RESULT lines.
        if any(h._has_exact_rng_miss(run._read_receipt(i) or "") for i in ("a", "b")):
            raise h.GameRngMiss("clause hunt ended on the game's RNG") from None
        raise


def _orchestrate_clause(run):
    run._gen3_prelude()
    # Gen 1's ordered pending-capture carrier. This also makes the later
    # capturer's gender/type rejection deterministic given the actual two mons.
    run.go()
    pending = run._gen3_mark("a", r"^PENDING_CAPTURE (\{.*\})$", "A's native capture")
    cap = json.loads(pending.group(1))
    if cap.get("area_id") != run._hunt_area:
        raise RuntimeError("A's clause capture is outside the hunt area")
    def confirmed():
        p = (run._status() or {}).get("pending_captures", {}).get(run._hunt_area, {}).get("a") or {}
        return p if p.get("key") == cap["key"] and p.get("species") == cap["species_id"] else None
    run._clause_pending = run.wait_for("server's exact A pending key/species", confirmed, 120)
    run._append_reconnect_marker("b", "A_PENDING " + json.dumps(cap, separators=(",", ":")))
    for inst in ("a", "b"):
        run._gen3_mark(inst, r"^CLAUSE_READY (\S+)$", "clause disposition ready")
    for inst in ("a", "b"):
        run._append_reconnect_marker(inst, "SAVE")


def orchestrate_release(run):
    run._gen3_prelude(link_slot=1)
    run.go(run._gen3_linked_lines())
    # Same native deposit/withdraw/deposit/release sequence as pc_ops_new.
    # Keep B live here: the Gen 3 oracle additionally reads its actual memorial.
    ka, kb = run._link_keys["a"], run._link_keys["b"]
    for tag_a, tag_b, allow in (("DEPOSITED", "MIRROR_DEPOSITED", "ALLOW_WITHDRAW"),
                               ("WITHDRAWN", "MIRROR_WITHDRAWN", "ALLOW_DEPOSIT"),
                               ("SECOND_DEPOSITED", "MIRROR_SECOND_DEPOSITED", "ALLOW_RELEASE")):
        run._gen3_mark("a", rf"^{tag_a} {re.escape(ka)}$", tag_a)
        run._gen3_mark("b", rf"^{tag_b} {re.escape(kb)}$", tag_b)
        run._append_reconnect_marker("a", allow)


def release_oracle(run, results):
    import e2e_duo as h
    run._gen3_flush_boundary()
    run._gen3_one_link("memorial", "release")
    ka, kb = run._link_keys["a"], run._link_keys["b"]
    saved, fixture = run._gen3_saved("a"), run._gen3_fixture_saved("a")
    problems = release_membership(saved, fixture, ka, h.gen3_key)
    # Surviving records, not just their keys, must remain intact (walking may
    # change friendship/HP/PP on A; box contents must remain byte-equivalent).
    was = {h.gen3_key(m): m for m in fixture[0]}
    for mon in saved[0]:
        key = h.gen3_key(mon)
        if key in was:
            changed = h.gen3_consumed_ok(h.gen3_record_diff(was[key], mon, run._gen3_rr,
                h.GEN3_RECORD_MUTABLE | h.GEN3_ACTIVITY_MUTABLE | h.GEN3_TRAINED_MUTABLE), battled=True)
            if changed:
                problems.append(f"release changed surviving {key}: {changed}")
    for pos, mon in fixture[1].items():
        if pos in saved[1] and h.gen3_record_diff(mon, saved[1][pos], run._gen3_rr, set()):
            problems.append(f"release changed unrelated box {pos}")
    problems += h.gen3_memorial_problems("b", run._gen3_saved("b"), run._gen3_fixture_saved("b"),
                                       kb, run._gen3_memorial_box(), rr=run._gen3_rr,
                                       limits=run._gen3_limits("b"))
    source = one(results["a"], "RELEASE_PREIMAGE")
    if source.get("key") != ka or (source.get("source") or {}).get("where") != "box":
        problems.append("release must name the native boxed pre-removal key")
    chains = {
        "a": [h.gen3_tx("party_to_box", ka), h.gen3_tx("box_to_party", ka),
              rf"(?m)^SECOND_DEPOSITED {re.escape(ka)}$", r"(?m)^RELEASE_PREIMAGE ",
              h.gen3_tx("release", ka), rf"(?m)^RELEASED {re.escape(ka)}$"],
        "b": [rf"(?m)^MIRROR_DEPOSITED {re.escape(kb)}$", rf"(?m)^MIRROR_WITHDRAWN {re.escape(kb)}$",
              rf"(?m)^MIRROR_SECOND_DEPOSITED {re.escape(kb)}$", h.gen3_rx("force_faint", kb),
              h.gen3_rx("memorialize", kb), h.gen3_tx("memorialize_done", kb)],
    }
    for inst, chain in chains.items():
        problems += h.gen3_receipt_problems(inst, results[inst], required=chain,
                                            ordered=list(zip(chain, chain[1:], strict=False)))
    if len(re.findall(h.gen3_tx("release", ka), results["a"], re.M)) != 1:
        problems.append("release must be emitted exactly once for A's key")
    deposits = [m.start() for m in re.finditer(h.gen3_tx("party_to_box", ka), results["a"])]
    withdrawals = [m.start() for m in re.finditer(h.gen3_tx("box_to_party", ka), results["a"])]
    if len(deposits) != 2 or len(withdrawals) != 1 or not deposits[0] < withdrawals[0] < deposits[1]:
        problems.append("release needs two native deposits around one withdraw")
    if "RX force_faint" in results["a"] or "RX memorialize" in results["a"]:
        problems.append("the releaser received a death command")
    run._gen3_raise(problems, f"release: native PC removal {ka}; boxed partner {kb} retired and memorial saved")


def capture_rows(results):
    caps = {}
    for inst, text in results.items():
        found = [json.loads(s) for s in re.findall(r"^TX capture \S+ (\{.*\})$", text, re.M)]
        if len(found) != 1:
            raise RuntimeError(f"{inst}: expected one native capture, got {len(found)}")
        caps[inst] = found[0]
    return caps


def wild_facts(title, area):
    directory = "gen3_emerald" if title == "emerald" else "gen3_frlge"
    name = "rr_encounters.json" if title == "radical_red" else title + "_encounters.json"
    data = json.loads((ROOT / "data/games" / directory / name).read_text(encoding="utf-8"))
    table = data.get("encounters", data).get(area)
    if not table:
        raise ValueError(f"no {title} encounter table for {area}")
    methods = ("Day", "Night") if title == "radical_red" else ("Grass",)
    return [e for method in methods for e in table.get(method, [])]


def clause_oracle(run, results):
    import e2e_duo as h
    run._gen3_flush_boundary()
    caps = capture_rows(results)
    pending = getattr(run, "_clause_pending", None) or {}
    a_pending, b_pending = one(results["a"], "PENDING_CAPTURE"), one(results["b"], "A_PENDING")
    if pending.get("key") != caps["a"]["key"] or pending.get("species") != caps["a"]["species_id"]:
        raise RuntimeError("independently observed pending key/species disagree")
    if any(marker.get(k) != caps["a"].get(k) for marker in (a_pending, b_pending) for k in ("key", "species_id", "area_id")):
        raise RuntimeError("pending marker names a different capture")
    if results["b"].find("A_PENDING ") > results["b"].find("CLAUSE_ENCOUNTER "):
        raise RuntimeError("B encountered before the confirmed pending release")
    kind, area = run.cfg["rule_kind"], run._hunt_area
    facts = {inst: own_facts(run, inst) for inst in ("a", "b")}
    problems = []
    for inst, cap in caps.items():
        if cap.get("area_id") != area or str(cap.get("species_id")) not in facts[inst]:
            problems.append(f"{inst}: capture has no title/area facts")
        # Existing capture oracle checks saved identity against the actual
        # capture TX; the engine receipt below binds wild species independently.
        met = rows(results[inst], "CLAUSE_ENCOUNTER")
        if not met or met[-1].get("species") != cap.get("species_id"):
            problems.append(f"{inst}: catch does not match the cartridge's final wild foe")
        table = wild_facts(run._gen3_title(inst), area)
        if not any(e["species_id"] == cap["species_id"] and e["min_level"] <= cap.get("level", -1) <= e["max_level"] for e in table):
            problems.append(f"{inst}: native catch not in this title's wild table")
        throws = len(re.findall(r"^THREW \d+$", results[inst], re.M))
        before = h.gen3_ball_count(run._gen3_fixture_bytes(inst), run._gen3_title(inst))
        after = h.gen3_ball_count(run._gen3_flushed(inst), run._gen3_title(inst))
        if throws < 1 or after != before - throws:
            problems.append(f"{inst}: saved Ball debit does not match the native throws")
    if problems:
        raise RuntimeError("; ".join(problems))
    keys = {i: c["key"] for i, c in caps.items()}
    rx = {i: rows(t, "RULE_RX") for i, t in results.items()}
    rejected = [i for i in ("a", "b") if any(r.get("cmd") == "force_faint" and r.get("key") == keys[i] for r in rx[i])]
    if kind == "species":
        if rejected:
            raise RuntimeError("species reroll produced a rejection")
        if facts["a"][str(caps["a"]["species_id"])]["family"] == facts["b"][str(caps["b"]["species_id"])]["family"]:
            raise RuntimeError("same family was linked")
        run._link_keys = keys
        run.assert_link_gen3_saved(results)
        encounter = rows(results["b"], "CLAUSE_ENCOUNTER")
        rerolls = rows(results["b"], "CLAUSE_REROLL")
        family = facts["a"][str(caps["a"]["species_id"])]["family"]
        for n, e in enumerate(encounter, 1):
            dupe = facts["b"][str(e["species"])]["family"] == family
            if e.get("n") != n or e.get("dupe") != dupe or dupe != (n < len(encounter)):
                problems.append("species encounter order/family decision mismatch")
        if len(rerolls) != len(encounter) - 1:
            problems.append("missing reroll receipt for a duplicate RUN")
        for n, r in enumerate(rerolls, 1):
            if (r.get("n") != n or r.get("species") != encounter[n - 1]["species"]
                    or not re.fullmatch(r"Dupes clause: .+ -- reroll!", r.get("prompt", ""))
                    or not any(x.get("cmd") == "gui_prompt" and x.get("text") == r.get("prompt") for x in rx["b"])):
                problems.append("reroll prompt is missing or names another encounter")
        events = run._reconnect_events()
        if any(e.get("type") == "dead_zone" for e in events):
            problems.append("duplicate RUN created a dead zone")
        if rerolls and not any(e.get("type") == "reroll" for e in events):
            problems.append("server persisted no reroll")
        run._gen3_raise(problems, f"species: alive pair after {len(rerolls)} native rerolls")
        if not rerolls:
            raise ClauseUnobserved("species reroll unobserved")
        return
    expected = (bool(set(facts["a"][str(caps["a"]["species_id"])]["types"]) &
                     set(facts["b"][str(caps["b"]["species_id"])]["types"])) if kind == "type" else
                gender(facts["a"], caps["a"]["species_id"], keys["a"]) in ("male", "female") and
                gender(facts["a"], caps["a"]["species_id"], keys["a"]) == gender(facts["b"], caps["b"]["species_id"], keys["b"]))
    if not expected:
        if rejected:
            raise RuntimeError(f"{kind}: title tables do not justify rejection")
        run._link_keys = keys
        run.assert_link_gen3_saved(results)
        raise ClauseUnobserved(f"{kind} clause unobserved")
    if rejected != ["b"]:
        raise RuntimeError(f"{kind}: later capturer B must be the only rejection, got {rejected}")
    from server.pokemon_data import type_name
    shared = set(facts["a"][str(caps["a"]["species_id"])]["types"]) & set(facts["b"][str(caps["b"]["species_id"])]["types"])
    expected_prompt = ("[x] Type clause: shared " + ", ".join(sorted(type_name(t) for t in shared)) if kind == "type" else
                       "[x] Gender clause: both are " + ("♀" if gender(facts["b"], caps["b"]["species_id"], keys["b"]) == "female" else "♂"))
    for cmd, check in (("gui_prompt", lambda r: r.get("text") == expected_prompt),
                       ("memorialize", lambda r: r.get("key") == keys["b"]),
                       ("play_sound", lambda r: r.get("sound") == 26),
                       ("unresolve_area", lambda r: r.get("area_id") == area)):
        if not any(r.get("cmd") == cmd and check(r) for r in rx["b"]):
            problems.append(f"b: rejection lacks {cmd}")
    if any(r.get("cmd") in ("force_faint", "memorialize", "unresolve_area") for r in rx["a"]):
        problems.append("accepted half received a rejection command")
    if not any(r.get("cmd") == "play_sound" and r.get("sound") == 22 for r in rx["a"]):
        problems.append("accepted half lacks sound 22")
    problems += h.gen3_memorial_problems("b", run._gen3_saved("b"), run._gen3_fixture_saved("b"),
                                       keys["b"], run._gen3_memorial_box(), rr=run._gen3_rr,
                                       limits=run._gen3_limits("b"), captured=caps["b"])
    chain = [h.gen3_tx("capture", keys["b"]), h.gen3_rx("force_faint", keys["b"]),
             rf"(?m)^FORCED_HP0 {re.escape(keys['b'])} ", h.gen3_tx("memorialize_done", keys["b"])]
    problems += h.gen3_receipt_problems("b", results["b"], required=chain, ordered=list(zip(chain, chain[1:], strict=False)))
    saved, fixture = run._gen3_saved("a"), run._gen3_fixture_saved("a")
    boxed = [(p, m) for p, m in saved[1].items() if h.gen3_key(m) == keys["a"]]
    if (len(boxed) != 1 or boxed[0][0][0] == run._gen3_memorial_box()
            or [h.gen3_key(m) for m in saved[0]] != [h.gen3_key(m) for m in fixture[0]]
            or {p: h.gen3_key(m) for p, m in saved[1].items() if h.gen3_key(m) != keys["a"]} !=
               {p: h.gen3_key(m) for p, m in fixture[1].items()}):
        problems.append("accepted catch not quarantined once with original membership intact")
    elif boxed[0][1]["species"] != caps["a"]["species_id"]:
        problems.append("accepted quarantine has the wrong species")
    else:
        problems += h.gen3_record_problems("a quarantine", boxed[0][1], run._gen3_rr, run._gen3_limits("a"))
    status, document = run._status() or {}, run._reconnect_document()
    pending = status.get("pending_captures", {}).get(area, {})
    if set(pending) != {"a"} or pending["a"].get("key") != keys["a"]:
        problems.append("accepted catch missing from server pending captures")
    if status.get("area_states", {}).get(area) != "pending_b" or area not in document.get("retry_areas", {}).get("b", []):
        problems.append("rejected area is not retryable pending_b")
    if any({(r.get("a") or {}).get("key"), (r.get("b") or {}).get("key")} & set(keys.values()) for r in run._links_json()):
        problems.append("rejected captures formed a persisted link")
    run._gen3_raise(problems, f"{kind}: B rejected and memorial saved; A quarantined; area retryable")


# ROM object-event/script proofs are re-decoded by test_gen3_clause_rows.py.
# FR/LG: ViridianForest local6 (5,41), flag342, finditem POKE_BALL x1.
# E: RusturfTunnel local3 (3,1), flag1048, the same native item reward.
BALL_PICKUPS = {
    "firered": (1, 0, 4, 41, 342, "Right"),
    "leafgreen": (1, 0, 4, 41, 342, "Right"),
    "emerald": (24, 4, 3, 2, 1048, "Up"),
}


def ball_gate_seed(seed: bytes, title: str):
    """SYNTH zero-ball setup only. Activation never happens in this builder.

    Existing make-frlg-synth / make-emerald delegate here. The ordinary native
    CONTINUE warp reconstructs objects at the source-proven pickup tile.
    Emerald uses its cave's native encounters; FR/LG use forest grass. The
    existing family builder supplies a healthy fast lead on Emerald.
    """
    from server.adapters import gen3_codec as c
    layout_title = "emerald" if title == "emerald" else "frlg"
    parsed = c.parse_flash(seed, title=layout_title)
    sb1, sb2 = bytearray(parsed["sb1"]), bytearray(parsed["sb2"])
    party = c.party_from_save(seed, title=layout_title)
    if len(party) < 2 or not any(m["hp"] > 0 for m in party[1:]):
        raise ValueError("ball gate requires a healthy reserve for the native pre-ball faint")
    lead = dict(party[0], hp=1, status=0)
    party_at = c.SB1_PARTY_OFFSET_EMERALD if title == "emerald" else c.SB1_PARTY_OFFSET
    sb1[party_at:party_at + c.PARTY_MON_SIZE] = c.encode_party_mon(lead)
    group, num, x, y, flag, _ = BALL_PICKUPS[title]
    ball_at, count, key_at, flags = (0x650, 16, 0xAC, 0x1270) if title == "emerald" else (0x430, 13, 0xF20, 0xEE0)
    xor = int.from_bytes(sb2[key_at:key_at + 2], "little")
    for i in range(count):
        struct.pack_into("<HH", sb1, ball_at + i * 4, 0, xor)
    sb1[flags + flag // 8] &= ~(1 << (flag % 8))
    # SaveBlock1.continueGameWarp; specialSaveWarpFlags bit0, proven builder convention.
    sb1[0x0C:0x14] = struct.pack("<bbbBhh", group, num, -1, 0, x, y)
    sb2[9] |= 1
    objects = {"sb1": sb1, "sb2": sb2, "storage": parsed["storage"]}
    layout, body = c.slot_layout(title=layout_title), bytearray(seed)
    start = parsed["slot"] * c.NUM_SECTORS_PER_SLOT
    for entry in layout:
        sector = next(s for s in parsed["sectors"][start:start + c.NUM_SECTORS_PER_SLOT] if s["id"] == entry["id"])
        chunk = objects[entry["object"]][entry["offset"]:entry["offset"] + entry["size"]]
        base = sector["index"] * c.SECTOR_SIZE
        body[base:base + c.SECTOR_SIZE] = c.write_sector(chunk, entry["id"], parsed["counter"], layout)
    return bytes(body), [f"SYNTH lead HP1/status0, healthy reserve; zero Ball pocket; clear item flag {flag}; CONTINUE warp {group}.{num} ({x},{y}); native faint/pickup/catch pending"]


def rr_ball_gate_seed(seed):
    """Preserve rr_battle's native pre-parcel story, disclose a second owned mon.

    The reserve is copied from the existing native rr_battle2 fixture of the
    same OT, then prepared through the own-ROM family builder. No story flags
    or ball pocket are fabricated/reset on RR.
    """
    import e2e_duo as h
    import gen3_fixtures as fx

    from server.adapters import gen3_codec as c
    party = c.party_from_save(seed, rr=True)
    if len(party) != 1 or h.gen3_ball_count(seed, "radical_red") != 0:
        raise ValueError("RR gate seed must be the one-mon, zero-ball pre-parcel fixture")
    reserve = c.party_from_save((ROOT / "tests/fixtures/gen3/rr_battle2.sav").read_bytes(), rr=True)[1]
    if reserve["ot_id"] != party[0]["ot_id"] or reserve["personality"] == party[0]["personality"] or reserve["hp"] == 0:
        raise ValueError("RR native reserve must be healthy, distinct, and the same OT")
    parsed, body, patches = c.parse_flash(seed, cfru=True), bytearray(seed), {}
    field = fx._rr_field_patcher(fx._rr_write_spans(parsed), patches, "ball gate party")
    field(c.RR_SAVEBLOCK1_ADDR + c.SB1_PARTY_COUNT_OFFSET, bytes([2]))
    field(c.RR_SAVEBLOCK1_ADDR + c.SB1_PARTY_OFFSET, c.encode_party_mon(dict(party[0], hp=1, status=0), rr=True))
    field(c.RR_SAVEBLOCK1_ADDR + c.SB1_PARTY_OFFSET + c.PARTY_MON_SIZE, c.encode_party_mon(reserve, rr=True))
    for offset, value in patches.items():
        body[offset] = value
    manifest = ["SYNTH RR lead HP1/status0, native rr_battle2 reserve copied into party[1]; pre-parcel story/pocket untouched"]
    fx._rr_recompute_touched_checksums(parsed, seed, body, manifest)
    result, family_manifest = family_seed(bytes(body), "radical_red", slot=1, species_pair=(453, 452))
    return result, manifest + family_manifest


def orchestrate_ball_gate(run):
    run._gen3_prelude()
    run.go()
    for inst in ("a", "b"):
        run._gen3_mark(inst, r"^BALL_PRE (\{.*\})$", "native action before first ball")
    status = run._status() or {}
    if any(status.get("players", {}).get(i, {}).get("nuzlocke_active") is not False for i in ("a", "b")):
        raise RuntimeError("server gate opened before native acquisition")
    if run._links_json() or status.get("pending_captures"):
        raise RuntimeError("pre-ball native action resolved an encounter")
    run._ball_pre_status = status
    for inst in ("a", "b"):
        run._append_reconnect_marker(inst, "ACQUIRE")
    for inst in ("a", "b"):
        run._gen3_mark(inst, r"^BALL_FLIP (\{.*\})$", "native first ball")
    run.wait_for("both server gates activated by real bag reads", lambda: all(
        (run._status() or {}).get("players", {}).get(i, {}).get("nuzlocke_active") is True for i in ("a", "b")), 120)
    if run.cfg.get("post_flip_stock") and not run._gen3_rr:
        from gen3_ball_phases import transition
        transition(run)
    else:
        for inst in ("a", "b"):
            run._append_reconnect_marker(inst, "CAPTURE")
    run.assert_link_new()


def ball_gate_oracle(run, results):
    import e2e_duo as h
    run._gen3_flush_boundary()
    phased = run.cfg.get("post_flip_stock") and not run._gen3_rr
    if phased:
        from gen3_ball_phases import verify
        results = verify(run, results)
    problems = []
    pre_status = getattr(run, "_ball_pre_status", None) or {}
    if any(pre_status.get("players", {}).get(i, {}).get("nuzlocke_active") is not False or
           pre_status.get("players", {}).get(i, {}).get("ball_count") != 0 for i in ("a", "b")):
        problems.append("pre-ball server state was not independently observed closed at zero Balls")
    if run._reconnect_document().get("pokeballs_obtained") != {"a": True, "b": True}:
        problems.append("native Ball activation not persisted by server")
    if any((run._status() or {}).get("players", {}).get(i, {}).get("nuzlocke_active") is not True for i in ("a", "b")):
        problems.append("post-ball server gate did not remain active")
    for inst, text in results.items():
        faint = one(text, "BALL_FAINT")
        pre, pickup, flip = one(text, "BALL_PRE"), one(text, "BALL_PICKUP"), one(text, "BALL_FLIP")
        caught = one(text, "BALL_POST_CATCH")
        captures = capture_rows({inst: text})
        cap = captures[inst]
        if cap.get("key") != caught.get("key") or cap.get("area_id") != run._hunt_area:
            problems.append(f"{inst}: post-activation catch not bound to its native area/key")
        initial_bytes = run._ball_phases[inst]["fixture"] if phased else run._gen3_fixture_bytes(inst)
        gate_saved = run._ball_phases[inst]["saved"] if phased else run._gen3_flushed(inst)
        fixture = run._gen3_fixture_saved(inst)
        lead = h.gen3_key(fixture[0][0])
        site = faint.get("site") or {}
        if (faint.get("key") != lead or faint.get("hp") != 0 or faint.get("sent") != 1
                or site.get("party_hp") != 0 or site.get("battler0_slot") != 0 or site.get("counter", 0) < 1):
            problems.append(f"{inst}: pre-ball native faint is not proven for the original lead")
        chain = [h.gen3_tx("faint", lead), r"(?m)^BALL_FAINT ", r"(?m)^BALL_PRE ", r"(?m)^BALL_PICKUP ",
                 r"(?m)^BALL_FLIP ", h.gen3_tx("capture", caught.get("key", "MISSING")), r"(?m)^BALL_POST_CATCH "]
        problems += h.gen3_receipt_problems(inst, text, required=chain, ordered=list(zip(chain, chain[1:], strict=False)))
        hp = rf"(?m)^BALL_NATIVE_HP0 {re.escape(lead)} .*in_battle=1"
        problems += h.gen3_receipt_problems(inst, text, required=[hp], ordered=[(hp, r"(?m)^BALL_FAINT ")])
        log = (Path(run.data_dir) / "slink.log").read_text(encoding="utf-8")
        if f"[{inst}] faint key={lead}" not in log or "faint →" in log:
            problems.append(f"{inst}: server did not receive and suppress the pre-ball faint")
        title = run._gen3_title(inst)
        if not any(e["species_id"] == cap.get("species_id") and e["min_level"] <= cap.get("level", -1) <= e["max_level"]
                   for e in wild_facts(title, run._hunt_area)):
            problems.append(f"{inst}: post-activation catch absent from this title's wild table")
        expected = 10 if title == "radical_red" else 1
        flag = 0x829 if title == "radical_red" else BALL_PICKUPS[title][4]
        if pickup != {"flag": flag, "before": False, "after": True}:
            problems.append(f"{inst}: native reward flag transition missing")
        if not text.index("BALL_PRE ") < text.index("BALL_PICKUP ") < text.index("BALL_FLIP "):
            problems.append(f"{inst}: native gate phases out of order")
        # attempted includes native HUD/panel mailbox bytes on RR. Gate proof is
        # the real zero pocket, closed client/server gate, native faint and absence
        # of capture/death commands below, not a ban on unrelated UI writes.
        if pre.get("balls") != 0 or pre.get("active") is not False:
            problems.append(f"{inst}: pre-ball gate was not closed at zero Balls")
        if flip.get("balls") != expected or flip.get("active") is not True:
            problems.append(f"{inst}: native reward/activation mismatch")
        encounters = re.findall(r"^BALL_PRE_ENCOUNTER species=(\d+) outcome=4$", text, re.M)
        if len(encounters) != 1:
            problems.append(f"{inst}: no native wild RUN before first ball")
        else:
            area = "route_1" if title == "radical_red" else "rusturf_tunnel" if title == "emerald" else "viridian_forest"
            if not any(e["species_id"] == int(encounters[0]) for e in wild_facts(title, area)):
                problems.append(f"{inst}: pre-ball foe is absent from this title's wild table")
        prefix = text.split("BALL_FLIP ")[0]
        if re.search(r"^TX (?:capture|no_catch|release) ", prefix, re.M) or "RX force_faint" in text or "RX memorialize" in text:
            problems.append(f"{inst}: pre-ball action emitted an encounter/death consequence")
        throws = len(re.findall(r"^THREW \d+$", text, re.M))
        if (h.gen3_ball_count(initial_bytes, title) != 0 or throws < 1
                or (phased and h.gen3_ball_count(gate_saved, title) != expected)
                or h.gen3_ball_count(run._gen3_flushed(inst), title) != (20 if phased else expected) - throws):
            problems.append(f"{inst}: independent saved Ball counts disagree")
        codec = h.gen3_codec()
        flag_at = (0x1270 if title == "emerald" else 0xEE0) + flag // 8
        for image, want in ((initial_bytes, 0), (gate_saved, 1)):
            parsed = codec.parse_flash(codec.split_rtc(image)[0], cfru=run._gen3_rr, title=h.gen3_codec_title(title))
            if (parsed["sb1"][flag_at] >> (flag % 8)) & 1 != want:
                problems.append(f"{inst}: saved reward flag does not prove native acquisition")
        saved = run._gen3_saved(inst)
        if ([h.gen3_key(m) for m in saved[0]] != [h.gen3_key(m) for m in fixture[0]] + [caught["key"]]
                or saved[1] != fixture[1]):
            problems.append(f"{inst}: gate test changed owned membership or boxes")
        by_key = {h.gen3_key(m): m for m in saved[0]}
        for before in fixture[0]:
            key = h.gen3_key(before)
            after = by_key.get(key)
            if after is None:
                problems.append(f"{inst}: gate test lost owned {key}")
                continue
            changed = h.gen3_consumed_ok(h.gen3_record_diff(before, after, run._gen3_rr,
                h.GEN3_RECORD_MUTABLE | h.GEN3_ACTIVITY_MUTABLE | h.GEN3_TRAINED_MUTABLE), battled=True)
            if changed:
                problems.append(f"{inst}: gate test changed a record invariant {key}: {changed}")
    if len(run._links_json()) != 1 or any(e.get("type") == "dead_zone" for e in run._reconnect_events()):
        problems.append("post-ball catch did not leave exactly one durable link or produced a dead zone")
    # The accepted link oracle binds both real capture events to the one alive
    # persisted pair, complete saved party/box reads and the native throw debit.
    if problems:
        raise RuntimeError("; ".join(problems))
    run.assert_link_gen3_saved(results, native_ball_grant=0 if phased else 10 if run._gen3_rr else 1)
    run._gen3_raise([], "ball gate: pre-ball native faint suppressed; native reward activates; post-ball real catch/link saved")


def source_rom(title):
    names = {"firered": "Pokemon - FireRed Version (USA).gba", "leafgreen": "Pokemon - LeafGreen Version (USA).gba",
             "emerald": "Pokemon - Emerald Version (USA, Europe).gba", "radical_red": "patch/build/slink_RR.gba"}
    return (Path(os.environ.get("SLINK_GEN3_ROMS", ROOT)) / names[title]).read_bytes()


def family_seed(seed, title, rom=None, *, slot=0, species_pair=None):
    """Disclosed evolved lead; the lower-family wild encounter/RUN remains native.

    Uses the same sector writers as the accepted builders, including surgical
    RR writes. Stats, growth and experience are decoded from this title's ROM.
    """
    import gen3_fixtures as fx

    from server.adapters import gen3_codec as c
    rom = source_rom(title) if rom is None else rom
    facts = species_facts(rom, title)
    # RR Day has base Zigzagoon288; Night has Galarian1222. The paired row
    # stages one evolved half for each distinct ROM family (see family_galar).
    species, lower = species_pair or {"firered": (17, 16), "leafgreen": (17, 16),
                                     "emerald": (287, 286), "radical_red": (289, 288)}[title]
    if species == lower or not same_family(facts, species, lower):
        raise ValueError("family fixture's distinct species are not related in this ROM")
    rr = title == "radical_red"
    layout_title = "emerald" if title == "emerald" else "frlg"
    parsed = c.parse_flash(seed, cfru=rr, title=layout_title)
    party = c.party_from_save(seed, rr=rr, title=layout_title)
    mon = dict(party[slot])
    pack = "gen3_rr" if rr else "gen3_emerald" if title == "emerald" else "gen3_frlg"
    p = json.loads((ROOT / f"data/games/{pack}/profile.json").read_text())["titles"][title]
    base = struct.unpack_from("<I", rom, p["rom"]["CFRU_BASESTATS_PTR"] - 0x08000000)[0] if rr else p["rom"]["BASESTATS_ADDR"]
    entry = rom[base - 0x08000000 + species * 28:base - 0x08000000 + (species + 1) * 28]
    stats = dict(zip(("hp", "attack", "defense", "speed", "sp_attack", "sp_defense"), entry[:6], strict=True))
    exp_count = p["derived"]["EXPERIENCE_TABLE_ENTRY_COUNT"]
    experience = struct.unpack_from("<I", rom, p["rom"]["EXPERIENCE_TABLES_ADDR"] - 0x08000000 + (entry[19] * exp_count + 25) * 4)[0]
    mon.update(species=species, level=25, experience=experience, nickname="FAMILY", status=0,
               **fx._gen3_stats(stats, mon, 25))
    mon.pop("nickname_raw", None)
    mon["hp"] = mon["max_hp"]
    raw = c.encode_party_mon(mon, rr=rr)
    manifest = [f"SYNTH party[{slot}] species {party[slot]['species']}->{species}, level25, own-ROM EXP/stats, HP full, status0, nickname FAMILY; PID/OT/moves retained; native {lower} family"]
    body = bytearray(seed)
    if rr:
        patches = {}
        fx._rr_field_patcher(fx._rr_write_spans(parsed), patches, "family mon")(c.RR_SAVEBLOCK1_ADDR + c.SB1_PARTY_OFFSET + slot * c.PARTY_MON_SIZE, raw)
        for offset, value in patches.items():
            body[offset] = value
        fx._rr_recompute_touched_checksums(parsed, seed, body, manifest)
    else:
        sb1 = bytearray(parsed["sb1"])
        at = (c.SB1_PARTY_OFFSET_EMERALD if title == "emerald" else c.SB1_PARTY_OFFSET) + slot * c.PARTY_MON_SIZE
        sb1[at:at + len(raw)] = raw
        layout, start = c.slot_layout(title=layout_title), parsed["slot"] * c.NUM_SECTORS_PER_SLOT
        for e in layout:
            if e["object"] != "sb1":
                continue
            physical = next(s["index"] for s in parsed["sectors"][start:start + c.NUM_SECTORS_PER_SLOT] if s["id"] == e["id"])
            body[physical * c.SECTOR_SIZE:(physical + 1) * c.SECTOR_SIZE] = c.write_sector(
                sb1[e["offset"]:e["offset"] + e["size"]], e["id"], parsed["counter"], layout)
    return bytes(body), manifest


def family_members(run):
    """Read both actual linked lead records from the disclosed boot fixtures."""
    import e2e_duo as h
    members = []
    for inst in ("a", "b"):
        mon = run._gen3_fixture_saved(inst)[0][0]
        key = h.gen3_key(mon)
        if key != run._link_keys[inst]:
            raise RuntimeError(f"{inst}: family linked key is not the staged lead")
        members.append({"player": inst, "key": key, "species": mon["species"]})
    return members


def family_wild_facts(run, encounter):
    title = run._gen3_title("a")
    if title != "radical_red":
        return wild_facts(title, "route_102" if title == "emerald" else "route_1")
    # RR's Night regional IDs were collapsed by the historical JSON generator.
    # Read the actual booted cartridge's selector/slot tables. Both periods are
    # eligible; this row does not pretend to have proved the runtime RTC hour.
    from rr_rom_encounters import decode_encounters, effective_maps
    # play.map() emits group*256+number (Route 1 is 3.19 -> 787), not
    # the dotted label printed by map metadata.
    if encounter.get("map") != 3 * 256 + 19:
        raise RuntimeError("RR family encounter was not on Route 1 (3.19)")
    decoded = decode_encounters((ROOT / run._gen3_rom("a")).read_bytes())
    return [slot for period in ("Day", "Night") for slot in
            effective_maps(decoded, period)[(3, 19)]["habitats"]["land"]["slots"]]


def family_oracle(run, results):
    import e2e_duo as h
    run._gen3_flush_boundary()
    r = one(results["a"], "FAMILY_ENCOUNTER")
    # Keep the actual species/location in the aggregate run log even for an
    # unobserved attempt; the numbered client receipt is retained too.
    run._pydec_note("FAMILY_ENCOUNTER " + json.dumps(r, sort_keys=True))
    members = family_members(run)
    facts = own_facts(run, "a")
    if not any(e["species_id"] == r["species"] for e in family_wild_facts(run, r)):
        raise RuntimeError("family encounter absent from this title's wild table")
    matching = [m for m in members if same_family(facts, m["species"], r["species"])]
    related = bool(matching)
    member = matching[0] if matching else members[0]
    species, key = member["species"], member["key"]
    problems = []
    if (r.get("owned") != species or r.get("key") != key or r.get("related") != related
            or r.get("player") != member["player"]):
        problems.append("family encounter not bound to the staged cartridge record")
    for inst in ("a", "b"):
        saved, before = run._gen3_saved(inst), run._gen3_fixture_saved(inst)
        if [h.gen3_key(m) for m in saved[0]] != [h.gen3_key(m) for m in before[0]] or saved[1] != before[1]:
            problems.append(f"{inst}: family row changed owned membership")
        for old, new in zip(before[0], saved[0], strict=False):
            if h.gen3_record_diff(old, new, run._gen3_rr, h.GEN3_RECORD_MUTABLE | h.GEN3_ACTIVITY_MUTABLE):
                problems.append(f"{inst}: family row changed record invariants")
        if "RX force_faint" in results[inst] or "RX memorialize" in results[inst] or "TX capture " in results[inst]:
            problems.append(f"{inst}: family row produced a capture/death")
    link = run._gen3_one_link("alive")
    for m in members:
        if (link.get(m["player"]) or {}).get("species") != m["species"]:
            problems.append(f"{m['player']}: saved link species differs from the staged family record")
    if problems:
        raise RuntimeError("; ".join(problems))
    if not related:
        raise ClauseUnobserved("evolution family not encountered")
    if r["species"] == species:
        raise RuntimeError("family row only encountered the exact same species")
    reroll = one(results["a"], "CLAUSE_REROLL")
    if (reroll.get("species") != r["species"] or not re.fullmatch(r"Dupes clause: .+ -- reroll!", reroll.get("prompt", ""))
            or not any(x.get("cmd") == "gui_prompt" and x.get("text") == reroll["prompt"] for x in rows(results["a"], "RULE_RX"))):
        problems.append("no actual family reroll prompt")
    events = run._reconnect_events()
    if not any(e.get("type") == "reroll" for e in events) or any(e.get("type") == "dead_zone" for e in events):
        problems.append("family RUN lacks a durable reroll or dead-zoned the area")
    run._gen3_raise(problems, f"family: native {r['species']} rerolled against distinct owned {species} on {member['player']}; staged link remains alive")
