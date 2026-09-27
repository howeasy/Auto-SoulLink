"""Disclosed post-FLIP stock, only between exited native-save phases."""
import hashlib
import json
import shutil
from pathlib import Path


def stock_save(image, title, quantity=20):
    import e2e_duo as h

    from server.adapters import gen3_codec as c
    if title not in ("firered", "leafgreen", "emerald") or quantity != 20:
        raise ValueError("post-flip stock only supports the reviewed FR/LG/E 20-ball setup")
    layout_title = h.gen3_codec_title(title)
    ok, why = c.qualify_flash(image, title=layout_title)
    if not ok or h.gen3_ball_count(image, title) != 1:
        raise ValueError(f"post-flip source must be a native one-ball save: {why}")
    p = c.parse_flash(image, title=layout_title)
    pocket, count, key_at = (0x650, 16, 0xAC) if title == "emerald" else (0x430, 13, 0xF20)
    xor = int.from_bytes(p["sb2"][key_at:key_at+2], "little")
    hits = [pocket + i*4 + 2 for i in range(count)
            if int.from_bytes(p["sb1"][pocket+i*4:pocket+i*4+2], "little") == 4
            and (int.from_bytes(p["sb1"][pocket+i*4+2:pocket+i*4+4], "little") ^ xor) == 1]
    if len(hits) != 1:
        raise ValueError("native first acquisition was not exactly one Poke Ball")
    logical = hits[0]
    entry = next(e for e in c.slot_layout(title=layout_title) if e["object"] == "sb1"
                 and e["offset"] <= logical < e["offset"] + e["size"])
    sector = next(s for s in p["sectors"][14*p["slot"]:14*(p["slot"]+1)] if s["id"] == entry["id"])
    base = sector["index"] * c.SECTOR_SIZE
    at, check = base + logical - entry["offset"], base + c.OFF_SECTOR_CHECKSUM
    body = bytearray(image)
    body[at:at+2] = (quantity ^ xor).to_bytes(2, "little")
    body[check:check+2] = c.sector_checksum(body[base:base+entry["size"]], entry["size"]).to_bytes(2, "little")
    manifest = {"label": "SYNTH post-flip stock", "title": title, "before": 1, "after": quantity,
                "quantity_offset": at, "checksum_offset": check,
                "source_sha256": hashlib.sha256(image).hexdigest(),
                "sha256": hashlib.sha256(body).hexdigest()}
    return bytes(body), manifest


def transition(run):
    """Save/witness/exit first; archive it; only then construct and boot phase 2."""
    import e2e_duo as h
    from gen3_clause_rows import BALL_PICKUPS

    from server.adapters import gen3_codec as c
    original = {i: run._gen3_fixture_bytes(i) for i in ("a", "b")}
    for i in ("a", "b"):
        run._append_reconnect_marker(i, "SAVE_GATE")
    a, b = run.wait_results()
    results = {"a": a, "b": b}
    if any(h.classify_gen1_result(text) != "PASS" for text in results.values()):
        raise RuntimeError("native ball gate phase did not pass")
    run.check_save_witness_gen3(results)  # includes process-exit/flush and hook-file comparison
    phases, fixtures = {}, {}
    for i in ("a", "b"):
        title = run._gen3_title(i)
        image = run._gen3_flushed(i)
        flag = BALL_PICKUPS[title][4]
        parsed = c.parse_flash(image, title=h.gen3_codec_title(title))
        base = 0x1270 if title == "emerald" else 0xEE0
        if not (parsed["sb1"][base+flag//8] & (1 << (flag % 8))):
            raise RuntimeError(f"{i}: native phase-1 pickup flag is not saved")
        prefix = Path(h.BUILD) / f"ball_gate_{run.game}_{run.lane}_{run.attempt}_{i}"
        native_path, stock_path = Path(str(prefix)+"_native.sav"), Path(str(prefix)+"_stock.sav")
        native_path.write_bytes(image)
        Path(str(prefix)+"_native.txt").write_text(results[i], encoding="utf-8")
        witness = h.SAVE_WITNESS_DUMP_RE.findall(results[i])[-1][0]
        witness_path = Path(str(prefix)+"_native_witness.bin")
        shutil.copyfile(witness, witness_path)
        stocked, manifest = stock_save(image, title)
        stock_path.write_bytes(stocked)
        Path(str(prefix)+"_stock.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
        phases[i] = {"fixture": original[i], "saved": image, "witness": witness_path.read_bytes(),
                     "receipt": results[i], "stock": stocked, "manifest": manifest}
        fixtures[i] = str(stock_path)
        run._pydec_note(json.dumps(manifest, sort_keys=True))
        Path(run.go_files[i]).unlink(missing_ok=True)
    run._ball_phases, run._gen3_phase_fixtures = phases, fixtures
    # Declare both forthcoming phases before constructing either stub. A's
    # partner path must not point at B's already-completed phase-1 receipt.
    run._phase = {**getattr(run, "_phase", {}), "a": "post_flip", "b": "post_flip"}
    for i in ("a", "b"):
        run.launch_instance(i, phase="post_flip", seed=True)
    run._gen3_prelude()
    run.go()


def verify(run, results):
    """Validate immutable phase1 and exact stock recipe again before final verdict."""
    import e2e_duo as h
    from gen3_clause_rows import one
    phases = getattr(run, "_ball_phases", None)
    if not phases or set(phases) != {"a", "b"}:
        raise RuntimeError("missing native phase-1 ball-gate evidence")
    combined = {}
    for i, phase in phases.items():
        title = run._gen3_title(i)
        h.check_gen3_witness(phase["witness"], phase["saved"], phase["fixture"], saves=1,
                            title=h.gen3_codec_title(title))
        stock, manifest = stock_save(phase["saved"], title)
        if stock != phase["stock"] or manifest != phase["manifest"] or stock != run._gen3_fixture_bytes(i):
            raise RuntimeError(f"{i}: phase-2 seed differs from disclosed post-flip stock")
        if one(results[i], "BALL_STOCK_READY") != {"balls": 20, "active": True}:
            raise RuntimeError(f"{i}: phase-2 stock was not read back by the client")
        combined[i] = phase["receipt"] + "\n" + results[i]
    return combined
