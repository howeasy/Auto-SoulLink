"""Independent T2/A2 receipt + saved-state oracle (FRLG, singles only).

Call after the runner's normal check_save_witness_gen3: that check binds dump paths, ordinals,
mtime and flush completion to THIS attempt. Pass the actual hook/flushed/seed bytes here, never
parsed hash claims. verify also calls check_gen3_witness for counter/sector/hash verification.
Pass helpers=sys.modules[__name__] from e2e_duo when it runs as __main__, preserving its marker
collector instead of importing a second runner instance. No runner registration lives here.

READY/LANDED need samples, active_hex (88 raw bytes encoded as176 hex digits), in_battle and
target_hp, serialized by the carrier from its independent snapshot. T2 additionally emits EXIT
after LANDED with outcome1. samples counts distinct observed frames, NOT a declared sample floor.
force_faint has no ACK: unrelated/stale PC ACKs are forbidden, not treated as write evidence.
B is idle/no-save: its completed-write count and flushed flash are checked; this does not claim
an independent zero-attempt/live-RAM proof for B.
"""
import re

from server.adapters import gen3_codec as codec

CASES = {"trainer_bench": (1, 102, "battle_faint", 1), "active_end": (0, 0, "overworld", 4)}
B_EXPECTATIONS = {"no_save": True, "completed_writes": 0, "flushed_flash": "unchanged", "result": "PASS"}
B_FORBIDDEN = (
    r"(?m)^RX (?:force_faint|force_explode|box_mon|party_mon|memorialize)(?:\s|$)",
    r"(?m)^TX (?:capture|faint|whiteout|party_to_box|box_to_party|stats_cache|sync_retrieve_done|memorialize_done) ",
    r"(?m)^(?:SAVE_WITNESS_DUMP\b|READY_BATTLE_WINDOW\b|BATTLE_WINDOW_)",
    r"(?m)^RESULT: FAIL\b",
)


class NotSubject(RuntimeError):
    """Nonqualifying trial; only a proved first-attempt T2 loss permits one retry."""

    def __init__(self, message, *, retry=False):
        super().__init__(message)
        self.retry = retry


def _helpers(module):
    if module is not None:
        return module
    from tools import e2e_duo
    return e2e_duo


def forbidden_sets(key, *, helpers=None):
    """Export the actor/idle-peer forbidden patterns for integration and reporting."""
    h = _helpers(helpers)
    a = [h.gen3_rx(cmd, key) for cmd in ("force_explode", "box_mon", "party_mon", "memorialize")]
    a += [h.gen3_tx(event, key) for event in ("faint", "stats_cache", "sync_retrieve_done", "memorialize_done")]
    a += [r"(?m)^TX whiteout ", r"(?m)^RESULT: FAIL\b"]
    return {"a": tuple(a), "b": B_FORBIDDEN}


def _require(condition, message):
    if not condition:
        raise RuntimeError(message)


def _line(text, prefix):
    lines = [s for s in text.splitlines() if s == prefix or s.startswith(prefix + " ")]
    _require(len(lines) == 1, f"expected exactly one {prefix}, got {len(lines)}")
    return lines[0]


def _fields(line):
    pairs = re.findall(r"(?:^|\s)([a-z_]+)=([^\s]+)", line)
    result = dict(pairs)
    _require(len(result) == len(pairs), "duplicate receipt fields")
    return result


def _number(fields, name):
    value = fields.get(name, "")
    _require(re.fullmatch(r"[0-9]+", value) is not None, f"missing/invalid {name}")
    return int(value)


def _stage(text, name, case, key):
    line = _line(text, name)
    prefix = f"{name} {case} {key}"
    _require(line == prefix or line.startswith(prefix + " "), f"wrong case/key for {name}")
    return _fields(line)


def _pattern(name, case, key):
    return r"(?m)^" + re.escape(f"{name} {case} {key}") + r"(?=\s|$)"


def classify_failure(*, case, key, receipts, attempt=1, helpers=None):
    """For early-finish integration: return NOT_SUBJECT facts or None (ordinary failure).

    This never returns PASS. T2's label alone is insufficient: prove its fresh in-battle bench
    write precedes the outcome2 loss. Pre-READY preparation failures cannot earn a retry.
    """
    h = _helpers(helpers)
    a, b = receipts.get("a", ""), receipts.get("b", "")
    try:
        terminal = _line(a, "RESULT:")
        ready = _stage(a, "READY_BATTLE_WINDOW", case, key)
        _require(not h.gen3_receipt_problems("b", b, forbidden=B_FORBIDDEN[:-1]), "unrelated B activity")
        if "RESULT: FAIL" in b:
            _require(_line(b, "RESULT:").startswith("RESULT: FAIL (battle-window partner did not PASS"),
                     "unrelated B failure")
        if case == "active_end" and terminal.startswith("RESULT: FAIL (NOT_SUBJECT active_end:"):
            _require(_number(ready, "in_battle") == 1 and _number(ready, "target_hp") > 0,
                     "invalid A2 start")
            _require("BATTLE_WINDOW_EXIT_INPUT" not in a and "BATTLE_WINDOW_LANDED" not in a,
                     "A2 already entered its subject phase")
            return {"status": "NOT_SUBJECT", "retry": False, "reason": terminal}
        if case != "trainer_bench" or not terminal.startswith("RESULT: FAIL (T2_RNG_LOSS:"):
            return None
        landed = _stage(a, "BATTLE_WINDOW_LANDED", case, key)
        exited = _stage(a, "BATTLE_WINDOW_EXIT", case, key)
        _line(a, "RX force_faint")  # duplicates cannot earn an RNG retry
        prep = _fields(_line(a, "PREP_LEVEL"))
        _require(_number(prep, "floor") >= 13 and _number(prep, "after") >= _number(prep, "floor")
                 and prep.get("hp") == "full" and prep.get("status") == "none", "unprepared RNG trial")
        _require(_number(ready, "trainer") == _number(landed, "trainer_id") == 102
                 and _number(ready, "slot") == _number(landed, "slot") == 1, "wrong RNG subject")
        _require(_number(ready, "in_battle") == _number(landed, "in_battle") == 1
                 and _number(ready, "target_hp") > 0 and _number(landed, "target_hp") == 0
                 and _number(landed, "hp") == 0 and _number(landed, "len") == 2
                 and landed.get("reason") == "battle_faint"
                 and landed.get("address", "").lower() == "0x0202433e", "unproved bench write")
        _require(_number(ready, "frame") < _number(landed, "frame") < _number(exited, "frame")
                 and _number(exited, "outcome") == 2
                 and 0 < _number(ready, "samples") < _number(landed, "samples"), "loss predates observation")
        _require(re.fullmatch(r"[0-9a-fA-F]{176}", ready.get("active_hex", "")) is not None
                 and ready["active_hex"].lower() == landed.get("active_hex", "").lower(), "active record changed")
        chain = [r"(?m)^PREP_LEVEL ", _pattern("READY_BATTLE_WINDOW", case, key), h.gen3_rx("force_faint", key),
                 _pattern("BATTLE_WINDOW_LANDED", case, key), _pattern("BATTLE_WINDOW_EXIT", case, key),
                 r"(?m)^RESULT: FAIL \(T2_RNG_LOSS:"]
        problems = h.gen3_receipt_problems("a", a, required=chain,
                                         forbidden=forbidden_sets(key, helpers=h)["a"][:-2],
                                         ordered=list(zip(chain, chain[1:], strict=False)))
        _require(not problems, "; ".join(problems))
        return {"status": "NOT_SUBJECT", "retry": type(attempt) is int and attempt == 1, "reason": terminal}
    except (RuntimeError, KeyError, TypeError):
        return None


def verify(*, case, key, receipts, fixture, witness, flushed, peer_fixture, peer_flushed, helpers=None, attempt=1):
    """Return verified facts, or raise RuntimeError/NotSubject. All images are actual bytes."""
    _require(case in CASES, "unknown battle-window case")
    _require(re.fullmatch(r"[0-9A-F]{8}:[0-9A-F]{8}", key) is not None, "invalid keyed identity")
    _require(set(receipts) == {"a", "b"}, "both side receipts required")
    a, b = receipts["a"], receipts["b"]
    classification = classify_failure(case=case, key=key, receipts=receipts, attempt=attempt, helpers=helpers)
    if classification is not None:
        raise NotSubject(classification["reason"], retry=classification["retry"])
    for side, text in receipts.items():
        terminal = _line(text, "RESULT:")
        _require(terminal.startswith("RESULT: PASS "), f"{side}: no terminal PASS")
    h = _helpers(helpers)
    slot, trainer, reason, outcome = CASES[case]
    ready = _stage(a, "READY_BATTLE_WINDOW", case, key)
    landed = _stage(a, "BATTLE_WINDOW_LANDED", case, key)
    exited = _stage(a, "BATTLE_WINDOW_EXIT", case, key)
    saved = _stage(a, "BATTLE_WINDOW_SAVED", case, key)
    dump = _fields(_line(a, "SAVE_WITNESS_DUMP"))
    _require(_line(a, "RX force_faint").startswith(f"RX force_faint key={key}"), "wrong force_faint RX")
    chain = [_pattern("READY_BATTLE_WINDOW", case, key), h.gen3_rx("force_faint", key)]
    if case == "active_end":
        held = _stage(a, "BATTLE_WINDOW_HELD", case, key)
        _stage(a, "BATTLE_WINDOW_EXIT_INPUT", case, key)
        _require(_number(held, "frames") >= 120 and _number(held, "attempted") == 0, "active hold not proved")
        chain += [_pattern(n, case, key) for n in ("BATTLE_WINDOW_HELD", "BATTLE_WINDOW_EXIT_INPUT",
                                                   "BATTLE_WINDOW_EXIT", "BATTLE_WINDOW_LANDED")]
    else:
        chain += [_pattern(n, case, key) for n in ("BATTLE_WINDOW_LANDED", "BATTLE_WINDOW_EXIT")]
        prep = _fields(_line(a, "PREP_LEVEL"))
        _require(_number(prep, "floor") >= 13 and _number(prep, "after") >= _number(prep, "floor")
                 and _number(prep, "after") >= _number(prep, "before")
                 and prep.get("hp") == "full" and prep.get("status") == "none", "preparation level floor not proved")
        chain.insert(0, r"(?m)^PREP_LEVEL ")
    chain += [r"(?m)^SAVE_WITNESS_DUMP ", _pattern("BATTLE_WINDOW_SAVED", case, key), r"(?m)^RESULT: PASS "]
    forbidden = forbidden_sets(key, helpers=h)
    problems = h.gen3_receipt_problems("a", a, required=chain, forbidden=forbidden["a"],
                                     ordered=list(zip(chain, chain[1:], strict=False)))
    problems += h.gen3_receipt_problems("b", b, required=[r"(?m)^WRITES 0$", r"(?m)^RESULT: PASS "],
                                      forbidden=forbidden["b"])
    _require(not problems, "; ".join(problems))
    _require(_line(b, "WRITES") == "WRITES 0", "idle peer wrote")
    _require(_number(ready, "slot") == _number(landed, "slot") == _number(saved, "slot") == slot,
             "wrong original target slot")
    _require(_number(ready, "trainer") == trainer, "wrong trainer id")
    _require(_number(ready, "in_battle") == 1 and _number(ready, "target_hp") > 0, "READY is not a living battle target")
    _require(landed.get("reason") == reason and _number(landed, "len") == 2
             and _number(landed, "hp") == _number(landed, "target_hp") == _number(saved, "hp") == 0,
             "wrong landed write reason/length/HP")
    _require(landed.get("address", "").lower() == f"0x{0x02024284 + slot * 100 + 0x56:08x}", "wrong HP address")
    rf, lf, ef, df = (_number(x, "frame") for x in (ready, landed, exited, dump))
    rs, ls = _number(ready, "samples"), _number(landed, "samples")
    _require(rs > 0 and 0 < ls - rs <= lf - rf + 1 and lf > rf, "zero/inconsistent observed samples")
    for record in (ready, landed):
        _require(re.fullmatch(r"[0-9a-fA-F]{176}", record.get("active_hex", "")) is not None,
                 "missing full active record")
    _require(_number(exited, "outcome") == outcome, "wrong battle exit outcome")
    if case == "trainer_bench":
        _require(_number(landed, "trainer_id") == 102, "wrong landed trainer id")
        _require(_number(landed, "in_battle") == 1 and lf < ef, "T2 landed after battle exit")
        _require(ready["active_hex"].lower() == landed["active_hex"].lower(), "active record changed at bench write")
    else:
        _require(_number(landed, "in_battle") == 0 and rf < ef <= lf, "A2 landed before battle exit")
        _require(ls - rs >= _number(held, "frames") and ef - rf >= _number(held, "frames"), "active hold has too few samples")
    _require(df >= max(lf, ef) and _number(dump, "bytes") == codec.FLASH_SIZE
             and _number(dump, "saves") == 1, "wrong save boundary/ordinal")
    facts = h.check_gen3_witness(witness, flushed, fixture, saves=1, rr=False)
    _require(_number(dump, "counter") == facts["counter"][1], "dump counter differs from actual save")
    party, boxes = h.gen3_decode(flushed, rr=False)
    original, _ = h.gen3_decode(fixture, rr=False)
    keys = [h.gen3_key(m) for m in party]
    old_keys = [h.gen3_key(m) for m in original]
    _require(old_keys.count(key) == 1 and len(old_keys) > slot and old_keys[slot] == key
             and original[slot]["hp"] == _number(ready, "target_hp"), "fixture/READY identity or HP differs")
    _require(not any(h.gen3_key(m) == key for m in boxes.values()), "target has a boxed copy")
    _require(keys.count(key) == 1 and keys == old_keys and keys[slot] == key, "saved target missing/duplicated/moved")
    _require(party[slot]["hp"] == 0 and party[slot]["max_hp"] > 0 and party[slot]["checksum_ok"] is True,
             "saved target healed or invalid")
    _require(codec.split_rtc(peer_flushed)[0] == codec.split_rtc(peer_fixture)[0], "idle peer battery changed")
    return {"case": case, "key": key, "slot": slot, "observed_samples": ls - rs,
            "active_unchanged": True if case == "trainer_bench" else None, "witness": facts}
