"""Disclosed shiny setup plus native capture/bonus-pair qualification.

The setup does not prove natural shiny generation. It changes only personality
at a parked wild action menu; normal inputs and production readers/handlers
must perform capture, shiny exception, bonus linking and saved readback.
"""
from __future__ import annotations

import hashlib
import json
import re

from server.adapters import gen3_codec as c
from server.pokemon_data import pid_otid_shiny


def prepare_shiny(raw, *, rr, trainer_otid):
    mon = c.decode_party_mon(raw, rr=rr)
    if (not mon["species"] or not mon["hp"] or mon["is_bad_egg"] or mon["is_egg"]
            or not mon["has_species"] or (not rr and not mon["checksum_ok"])
            or c.encode_party_mon(mon, rr=rr) != raw):
        raise ValueError("shiny setup requires a valid losslessly decoded native wild record")
    if mon["ot_id"] != trainer_otid:
        raise ValueError("wild record OT differs from the already-native captured trainer identity")
    old = mon["personality"]
    # Keep the low byte (gender and ability parity), and the complete nature.
    # Four-byte PID change requires vanilla substruct permutation/XOR re-encoding.
    pid = None
    for low in range(old & 255, 65536, 256):
        for shiny in range(8):
            high = (trainer_otid & 65535) ^ (trainer_otid >> 16) ^ low ^ shiny
            candidate = low | (high << 16)
            if candidate != old and candidate % 25 == old % 25:
                pid = candidate
                break
        if pid is not None:
            break
    if pid is None:
        raise ValueError("no shiny PID preserving nature/gender/ability")
    after = c.encode_party_mon(dict(mon, personality=pid), rr=rr)
    decoded = c.decode_party_mon(after, rr=rr)
    if (not pid_otid_shiny(pid, trainer_otid)
            or {k: v for k, v in decoded.items() if k != "personality"}
            != {k: v for k, v in mon.items() if k != "personality"}):
        raise ValueError("shiny setup changed another decoded field")
    return after, {
        "label": "SYNTH wild PID before native capture", "before": raw.hex(), "after": after.hex(),
        "before_key": f"{old:08X}:{trainer_otid:08X}", "after_key": f"{pid:08X}:{trainer_otid:08X}",
        "before_sha256": hashlib.sha256(raw).hexdigest(), "after_sha256": hashlib.sha256(after).hexdigest(),
        "species": mon["species"], "level": mon["level"], "rr": rr,
    }


def _pair(row, a, b, area):
    return (row.get("status") == "alive" and row.get("area_id") == area
            and (row.get("a") or {}).get("key") == a and (row.get("b") or {}).get("key") == b)


def orchestrate(run):
    from gen3_clause_rows import one
    run._gen3_prelude()
    run.go()
    run.assert_link_new()
    first = {i: one(run._read_receipt(i), "SHINY_BASELINE") for i in ("a", "b")}
    run._shiny_initial = run._reconnect_document()
    run._shiny_first = first
    for i in ("a", "b"):
        run._append_reconnect_marker(i, "BASE_LINKED")
    marker = run._gen3_mark("a", r"^SHINY_PREIMAGE (\{.*\})$", "native wild preimage")
    preimage = json.loads(marker[1])
    _, packet = prepare_shiny(bytes.fromhex(preimage["raw"]), rr=run._gen3_rr,
                              trainer_otid=int(first["a"]["key"].split(":")[1], 16))
    if packet["before_key"] != preimage["key"] or packet["species"] != preimage["species"]:
        raise RuntimeError("native shiny setup preimage metadata disagrees")
    run._shiny_packet = packet
    run._pydec_note("SYNTH_SHINY_SETUP " + json.dumps(packet, sort_keys=True))
    run._append_reconnect_marker("a", "SHINY_SETUP " + json.dumps(packet, sort_keys=True))
    shiny = json.loads(run._gen3_mark("a", r"^SHINY_CAUGHT (\{.*\})$", "native shiny catch")[1])
    if shiny["key"] != packet["after_key"]:
        raise RuntimeError("native shiny catch differs from the disclosed setup")

    def pending():
        try:
            doc = run._reconnect_document()
        except (OSError, json.JSONDecodeError):
            return None
        if (shiny["key"] in doc.get("bonus_keys", {}).get("a", [])
                and doc.get("pending_bonus", {}).get("b") == [shiny["key"]]):
            return doc
        return None
    run._shiny_pending = run.wait_for("persisted shiny bonus entitlement", pending, 120)
    run._pydec_note("SHINY_PENDING " + json.dumps({k: run._shiny_pending.get(k) for k in
                                                  ("bonus_keys", "pending_bonus", "area_states", "links")}, sort_keys=True))
    run._append_reconnect_marker("b", "BONUS_GO")
    bonus = json.loads(run._gen3_mark("b", r"^BONUS_CAUGHT (\{.*\})$", "native bonus-partner catch")[1])
    area = "_bonus_" + shiny["key"].split(":")[0]
    run.wait_for("actual second capture forms a bonus pair", lambda: next(
        (row for row in run._links_json() if _pair(row, shiny["key"], bonus["key"], area)), None), 120)
    run._shiny_second = {"a": shiny, "b": bonus}
    for i in ("a", "b"):
        run._append_reconnect_marker(i, "BONUS_LINKED")
    for i in ("a", "b"):
        run._gen3_mark(i, r"^SHINY_READY (\{.*\})$", "both captures physically present")
    for i in ("a", "b"):
        run._append_reconnect_marker(i, "SAVE")


def server_problems(initial, pending, final, first, second, area):
    ka, kb = first["a"]["key"], first["b"]["key"]
    sa, sb = second["a"]["key"], second["b"]["key"]
    problems = []
    if any(cap.get("area_id") != area for cap in (*first.values(), *second.values())):
        problems.append("shiny exception did not occur in the already-linked area")
    for label, doc, count in (("initial", initial, 1), ("pending", pending, 1), ("final", final, 2)):
        links = doc.get("links", [])
        if len(links) != count or not any(_pair(row, ka, kb, area) for row in links):
            problems.append(f"{label}: ordinary link changed or wrong link count")
        if doc.get("area_states", {}).get(area) != "linked":
            problems.append(f"{label}: original area resolution changed")
    if (pending.get("bonus_keys", {}).get("a") != [sa]
            or pending.get("pending_bonus", {}).get("b") != [sa]
            or pending.get("pending_bonus", {}).get("a")):
        problems.append("shiny capture did not persist exactly one partner entitlement")
    if (not any(_pair(row, sa, sb, "_bonus_" + sa.split(":")[0])
                and (row.get("a") or {}).get("is_shiny") is True for row in final.get("links", []))
            or any(final.get("pending_bonus", {}).get(i) or final.get("bonus_keys", {}).get(i) for i in ("a", "b"))):
        problems.append("bonus pair absent or entitlement was not consumed exactly once")
    if not pid_otid_shiny(*(int(s, 16) for s in sa.split(":"))):
        problems.append("A's exception key is not shiny")
    if pid_otid_shiny(*(int(s, 16) for s in sb.split(":"))):
        problems.append("B's next capture was another shiny, not the ordinary bonus partner")
    return problems


def saved_oracle(run, results):
    import e2e_duo as h
    from gen3_clause_rows import one
    run._gen3_flush_boundary()
    first, second = run._shiny_first, run._shiny_second
    problems = server_problems(run._shiny_initial, run._shiny_pending, run._reconnect_document(),
                               first, second, run._hunt_area)
    packet = one(results["a"], "SYNTH_SHINY_APPLIED")
    _, independently_rebuilt = prepare_shiny(bytes.fromhex(packet["before"]), rr=run._gen3_rr,
                                             trainer_otid=int(first["a"]["key"].split(":")[1], 16))
    if packet != run._shiny_packet or packet != independently_rebuilt or packet["after_key"] != second["a"]["key"]:
        problems.append("shiny setup manifest or native capture disagrees with its byte recipe")
    for i in ("a", "b"):
        captures = [json.loads(raw) for raw in re.findall(r"^TX capture \S+ (\{.*\})$", results[i], re.M)]
        if captures != [first[i], second[i]] or any(cap.get("gift") or cap.get("is_egg") for cap in captures):
            problems.append(f"{i}: expected exactly two production wild captures in order")
        if "RX force_faint" in results[i] or "RX memorialize" in results[i]:
            problems.append(f"{i}: native shiny/bonus exception was rejected")
        if re.search(h.gen3_rx("box_mon", second[i]["key"]), results[i]):
            problems.append(f"{i}: shiny/bonus capture was quarantined")
        saved, before = run._gen3_saved(i), run._gen3_fixture_saved(i)
        wanted = [h.gen3_key(m) for m in before[0]] + [first[i]["key"], second[i]["key"]]
        if [h.gen3_key(m) for m in saved[0]] != wanted or saved[1] != before[1]:
            problems.append(f"{i}: saved ownership is not exactly fixture plus the two native captures")
        by_key = {h.gen3_key(m): m for m in saved[0]}
        for mon in saved[0]:
            problems += h.gen3_record_problems(f"{i}: saved {h.gen3_key(mon)}", mon,
                                               run._gen3_rr, run._gen3_limits(i))
        for cap in (first[i], second[i]):
            mon = by_key.get(cap["key"], {})
            if (mon.get("species") != cap["species_id"] or mon.get("level") != cap["level"]
                    or not mon.get("hp") or mon.get("is_egg") or mon.get("is_bad_egg")):
                problems.append(f"{i}: caught record is missing, dead or inconsistent")
            for wire, field in (("held_item_id", "held_item"), ("nickname", "nickname")):
                if cap.get(wire) is not None and mon.get(field) != cap[wire]:
                    problems.append(f"{i}: saved catch {field} differs from native capture TX")
        for old in before[0]:
            new = by_key.get(h.gen3_key(old))
            if new is not None:
                changed = h.gen3_consumed_ok(h.gen3_record_diff(old, new, run._gen3_rr,
                    h.GEN3_RECORD_MUTABLE | h.GEN3_ACTIVITY_MUTABLE | h.GEN3_TRAINED_MUTABLE), battled=True)
                if changed:
                    problems.append(f"{i}: original record invariants changed: {changed}")
        baseline = h.gen3_ball_count(run._gen3_fixture_bytes(i), run._gen3_title(i))
        final = h.gen3_ball_count(run._gen3_flushed(i), run._gen3_title(i))
        throws = len(re.findall(r"^THREW \d+$", results[i], re.M))
        if throws < 2 or final != baseline - throws:
            problems.append(f"{i}: saved Ball debit does not match the native throws")
        run._pydec_note(f"SHINY_BALLS side={i} baseline={baseline} final={final} throws={throws}")
    run._gen3_raise(problems, "shiny exception: native catch bypassed linked area; next native partner catch formed and saved the bonus pair")
