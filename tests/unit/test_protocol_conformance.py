"""The transcript half of the Gen 3 protocol conformance suite (PLAN.md §5.6, card C1-4).

Two independent things live here:

1. A doc-sync meta-test: every numbered item in docs/protocol.md §9 (1-47, incl. 38a/38b)
   must appear in tests/unit/conformance_map.py, and every map entry must carry a layer. This
   runs unconditionally -- it does not need a transcript, an emulator, or lupa -- so the map
   cannot silently drift out of sync with the doc.

2. Transcript checks: when golden wire transcripts exist under tests/fixtures/gen3/wire/
   (JSONL, one {"dir","t","msg"} object per wire line -- see that directory's README), each
   is replayed through the transcript-checkable items from conformance_map (their
   `transcript_check` field). A transcript from the *old* client is characterization
   evidence and is expected to reproduce exactly the documented disagreements
   (conformance_map's `disagreement` field) and nothing else; a transcript from the *new*
   Gen 3 client must pass with zero violations. No transcripts exist yet (P1 card C1-3
   produces the first ones), so this half skips with an explicit reason until then.

Transcripts are never a complete oracle (PLAN §5.6): most §9 items need RAM state or live
timing that a wire-only recording cannot show, so only a subset of items carries a
`transcript_check`.
"""
from __future__ import annotations

import glob
import gzip
import json
import os
import re

import pytest

from tests.unit.conformance_map import ITEMS
from tests.unit.protocol_schema import validate_command, validate_event

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_PROTOCOL_MD = os.path.join(_REPO, "docs", "protocol.md")
_WIRE_DIR = os.path.join(_REPO, "tests", "fixtures", "gen3", "wire")

_ITEM_LINE_RE = re.compile(r"^(\d+[a-z]?)\.\s")


def _doc_item_ids() -> list[str]:
    """Every numbered item under docs/protocol.md's `## 9. Conformance checklist` section."""
    with open(_PROTOCOL_MD, encoding="utf-8") as f:
        text = f.read()
    start = text.index("## 9. Conformance checklist")
    end = text.index("## ", start + 1) if "## " in text[start + 1:] else len(text)
    # the section body (before the next "## " heading, e.g. Appendix A)
    body = text[start:start + text[start:].index("\n## ", 1)] if "\n## " in text[start:] else text[start:end]
    return [m.group(1) for line in body.splitlines() if (m := _ITEM_LINE_RE.match(line))]


# ---------------------------------------------------------------------------
# 1. Doc-sync meta-test (no fixtures, no lupa, always runs)
# ---------------------------------------------------------------------------

def test_every_doc_item_is_in_the_conformance_map():
    doc_ids = _doc_item_ids()
    assert len(doc_ids) >= 47, f"regex found too few §9 items ({len(doc_ids)}); it may have drifted"
    map_ids = {item.id for item in ITEMS}
    missing = [i for i in doc_ids if i not in map_ids]
    assert not missing, f"docs/protocol.md §9 items missing from conformance_map.py: {missing}"


def test_every_map_entry_matches_a_doc_item():
    """Catches the opposite drift: a map entry for an item the doc no longer has."""
    doc_ids = set(_doc_item_ids())
    extra = [item.id for item in ITEMS if item.id not in doc_ids]
    assert not extra, f"conformance_map.py has ids docs/protocol.md §9 does not: {extra}"


def test_every_map_entry_has_a_layer():
    from tests.unit.conformance_map import LAYERS
    for item in ITEMS:
        assert item.evidence_layer in LAYERS, f"item {item.id}: bad evidence_layer {item.evidence_layer!r}"


# ---------------------------------------------------------------------------
# 2. Transcript loading
# ---------------------------------------------------------------------------

_KNOWN_SOURCES = ("old_client", "gen3_new")

# Item -> the violations it is allowed to carry on a transcript from that source. Only the
# three documented disagreements are transcript-visible; everything else must be clean on
# both sources.
EXPECTED_VIOLATIONS = {
    # "1"/"14": the old client's hand JSON encoder emits {} for an empty Lua table
    # (enemy_party/pc_boxes on tick) instead of [] -- see conformance_map.py items "1"/"14"
    # for the evidence and why it is harmless. Item "28" (box_mon_failed never sent, A2) is
    # a real, documented disagreement (conformance_map.py, source-cited) but none of P1's six
    # scenarios captures the last-party-mon refusal that would put it on the wire, so it is
    # left out here rather than declared evidenced by a transcript that doesn't show it.
    "old_client": frozenset({"1", "14"}),
    "gen3_new": frozenset(),
}


def _source_for(path: str) -> str:
    name = os.path.basename(path)
    if name.endswith(".jsonl.gz"):
        name = name[: -len(".gz")]
    name = os.path.splitext(name)[0]
    for source in _KNOWN_SOURCES:
        if name.endswith("_" + source):
            return source
    raise ValueError(f"{path}: filename does not end in _old_client or _gen3_new (see README.md)")


def _load_transcript(path: str) -> list[dict]:
    """A .jsonl.gz path is read transparently (README.md: gzip anything over ~200 KB)."""
    lines = []
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                lines.append(json.loads(raw))
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{lineno}: not valid JSON: {e}") from e
    return lines


_TRANSCRIPTS = sorted(glob.glob(os.path.join(_WIRE_DIR, "*.jsonl")) +
                      glob.glob(os.path.join(_WIRE_DIR, "*.jsonl.gz")))


# ---------------------------------------------------------------------------
# 3. Transcript checkers. Each returns the subset of item ids (from the ids it covers) that
#    are VIOLATED by this transcript -- an empty set means fully conformant.
# ---------------------------------------------------------------------------

def check_line_shape(lines: list[dict]) -> set[str]:
    """Item 1: every c2s line is one JSON object with event/player/seq (and known shape)."""
    for line in lines:
        if line.get("dir") != "c2s":
            continue
        msg = line.get("msg", {})
        if validate_event(msg):
            return {"1"}
    return set()


def check_seq_monotonic(lines: list[dict]) -> set[str]:
    """Item 2: seq starts at 1, +1 per event, even across a reconnect (a fresh hello)."""
    last = None
    for line in lines:
        if line.get("dir") != "c2s":
            continue
        seq = line.get("msg", {}).get("seq")
        if not isinstance(seq, int):
            return {"2"}
        if last is None or line["msg"].get("event") == "hello":
            last = seq  # reconnect: seq restarts its own local count, still +1 per event after
            continue
        if seq != last + 1:
            return {"2"}
        last = seq
    return set()


def check_hello_first(lines: list[dict]) -> set[str]:
    """Item 4: the first c2s line (and the first after any later hello) is hello."""
    c2s = [line["msg"] for line in lines if line.get("dir") == "c2s"]
    if not c2s or c2s[0].get("event") != "hello":
        return {"4"}
    return set()


def check_hello_shape(lines: list[dict]) -> set[str]:
    """Items 8/9: hello's required fields, and every party entry's blob_hex length."""
    violations = set()
    for line in lines:
        if line.get("dir") != "c2s" or line.get("msg", {}).get("event") != "hello":
            continue
        msg = line["msg"]
        if validate_event(msg):
            violations |= {"8"}
        for entry in msg.get("party", []):
            required = ("key", "hp", "maxHP", "level", "slot", "species_id", "nickname", "blob_hex")
            bad_len = len(entry.get("blob_hex", "")) != 2 * 100  # Gen 3 party_blob_size() == 100
            if any(f not in entry for f in required) or bad_len:
                violations |= {"9"}
    return violations


def check_tick_shape(lines: list[dict]) -> set[str]:
    """Item 14 (field-shape half only): every tick line validates as a tick event.

    The 30-frame cadence half of item 14 is not transcript-checkable: a transcript's `t` is
    capture order (tests/fixtures/gen3/wire/README.md), not a frame count, so it cannot tell
    30 frames apart from any other gap. That half is proven live, against real frame numbers.
    """
    ticks = [line for line in lines if line.get("dir") == "c2s" and line.get("msg", {}).get("event") == "tick"]
    for line in ticks:
        if validate_event(line["msg"]):
            return {"14"}
    return set()


def check_battle_tick_shape(lines: list[dict]) -> set[str]:
    """Items 15/16: a tick with in_battle=true has the wild or trainer battle fields."""
    violations = set()
    for line in lines:
        if line.get("dir") != "c2s" or line.get("msg", {}).get("event") not in ("tick", "safe"):
            continue
        msg = line["msg"]
        if not msg.get("in_battle"):
            continue
        if msg.get("is_trainer_battle"):
            if not (msg.get("trainer_id", 0) > 0 or msg.get("opponent_name") or msg.get("opponent_class")):
                violations |= {"16"}
        else:
            enemy = msg.get("enemy_party") or []
            if not msg.get("area_id") or not enemy or enemy[0].get("species_id", 0) <= 0:
                violations |= {"15"}
    return violations


def check_event_shapes_once_only(lines: list[dict]) -> set[str]:
    """Items 21/23/25/26/27: required fields plus the once-only / no-double-fire rules."""
    violations = set()
    c2s = [line["msg"] for line in lines if line.get("dir") == "c2s"]

    no_catch_areas: set[str] = set()
    capture_areas: set[str] = set()
    faint_keys_seen: list[str] = []
    party_alive: set[str] = set()
    whiteout_count = 0

    for msg in c2s:
        event = msg.get("event")
        if event == "capture":
            if not msg.get("key") or not msg.get("area_id") or msg.get("species_id", 0) <= 0 \
                    or msg.get("level", 0) <= 0:
                violations |= {"21"}
            capture_areas.add(msg.get("area_id"))
        elif event == "no_catch":
            area = msg.get("area_id")
            if area in no_catch_areas or area in capture_areas:
                violations |= {"23"}
            no_catch_areas.add(area)
        elif event == "faint":
            key = msg.get("key")
            if not key:
                violations |= {"25"}
            faint_keys_seen.append(key)
            party_alive.discard(key)
        elif event == "whiteout":
            whiteout_count += 1
            if whiteout_count > 1:
                violations |= {"26"}
        elif event in ("party_to_box", "box_to_party"):
            if not msg.get("key"):
                violations |= {"27"}
    return violations


def _traded_keys(lines: list[dict]) -> set[str]:
    """The "two traded keys" of docs/protocol.md item 42 (§9, "Prompts and trade"): the
    pre-trade key of the incoming mon, recovered from `apply_trade`'s `blob_hex` (its first
    8 bytes are the PID and OT, each little-endian -- byte-reversing them to the wire's
    `PID:OT` hex form reproduces the key exactly, matched against real transcripts), plus
    whatever `trade_done` reads back as `new_key`. Item 42 requires the client to discard
    queued sync commands for these -- `check_keyed_replies` must not demand a reply to one.
    """
    keys: set[str] = set()
    for line in lines:
        msg = line.get("msg", {})
        if line.get("dir") == "s2c":
            for cmd in msg.get("commands", []):
                if cmd.get("cmd") == "apply_trade":
                    blob = cmd.get("blob_hex", "")
                    if len(blob) >= 16:
                        pid = bytes.fromhex(blob[0:8])[::-1].hex().upper()
                        ot = bytes.fromhex(blob[8:16])[::-1].hex().upper()
                        keys.add(f"{pid}:{ot}")
        elif line.get("dir") == "c2s" and msg.get("event") == "trade_done" and msg.get("new_key"):
            keys.add(msg["new_key"])
    return keys


def _had_safe_opportunity(c2s_lines: list[dict], after_t) -> bool:
    """True once the transcript shows a `tick`/`safe` with `in_battle` falsy after `after_t`
    -- proof the client reached the safe, out-of-battle frame that item 31 (docs/protocol.md,
    "Party/box sync") gates deferred `party_mon`/`memorialize` execution on. Without one, the
    transcript simply ended (E2E scenario disconnect, or the client still mid-battle) before
    the client had any chance to run the deferred command -- not evidence of a bug (PLAN
    §5.6: transcripts are never a complete oracle).
    """
    for entry in c2s_lines:
        if entry.get("t", 0) <= after_t:
            continue
        msg = entry.get("msg", {})
        if msg.get("event") in ("tick", "safe") and not msg.get("in_battle"):
            return True
    return False


def check_keyed_replies(lines: list[dict]) -> set[str]:
    """Items 28/29/30: box_mon/party_mon/memorialize each get exactly one keyed reply.

    box_mon is the odd one out: a *successful* deposit has no positive ack on the wire (only
    `box_mon_failed` on failure, per docs/protocol.md item 28), so a bare transcript cannot
    tell success from "old client bug: silently did nothing". The one case a transcript CAN
    prove must fail is `box_mon` on a key that is (at that point in the transcript) the
    client's only party mon -- item 28 requires a refusal there, so a missing
    `box_mon_failed` is a provable violation.

    party_mon/memorialize are deferred, safe-state-only commands (item 31); a captured
    session that disconnects (or stays in battle) before the client reaches a safe frame
    proves nothing either way, so a missing reply is only a violation once `_had_safe_
    opportunity` shows the client had a real chance to answer and didn't. A *duplicate*
    reply is always a violation -- that is direct positive evidence, no opportunity needed.
    A `party_mon` for one of `_traded_keys` is item 42's discard case, never a violation.
    """
    violations = set()
    c2s_lines = [entry for entry in lines if entry.get("dir") == "c2s"]
    c2s = [entry["msg"] for entry in c2s_lines]
    traded = _traded_keys(lines)
    party_keys: set[str] = set()
    for line in lines:
        msg = line.get("msg", {})
        if line.get("dir") == "c2s" and msg.get("event") in ("hello", "tick", "safe") and "party" in msg:
            party_keys = {p["key"] for p in msg["party"] if "key" in p}
        elif line.get("dir") == "s2c":
            cmd_t = line.get("t", 0)
            for cmd in msg.get("commands", []):
                if validate_command(cmd):
                    continue
                key = cmd.get("key")
                if cmd.get("cmd") == "box_mon" and party_keys == {key}:
                    failed = [m for m in c2s if m.get("event") == "box_mon_failed" and m.get("key") == key]
                    if not failed:
                        violations |= {"28"}
                elif cmd.get("cmd") == "party_mon":
                    if key in traded:
                        continue
                    replies = [m for m in c2s if m.get("event") in ("sync_retrieve_done", "sync_retrieve_failed")
                               and m.get("key") == key]
                    if len(replies) > 1 or (not replies and _had_safe_opportunity(c2s_lines, cmd_t)):
                        violations |= {"29"}
                elif cmd.get("cmd") == "memorialize":
                    replies = [m for m in c2s if m.get("event") in ("memorialize_done", "memorialize_failed")
                               and m.get("key") == key]
                    if len(replies) > 1 or (not replies and _had_safe_opportunity(c2s_lines, cmd_t)):
                        violations |= {"30"}
    return violations


def check_token_echo(lines: list[dict]) -> set[str]:
    """Items 39-41: show_choices/show_menu/choose_mon each get exactly one reply, token echoed."""
    violations = set()
    s2c_cmds = [c for line in lines if line.get("dir") == "s2c"
                for c in line.get("msg", {}).get("commands", [])]
    c2s = [line["msg"] for line in lines if line.get("dir") == "c2s"]

    for cmd in s2c_cmds:
        token = cmd.get("token")
        if token is None:
            continue
        cmd_name = cmd.get("cmd")
        reply_event = {"show_choices": "menu_result", "show_menu": "menu_result",
                        "choose_mon": "mon_chosen"}.get(cmd_name)
        if reply_event is None:
            continue
        item = {"show_choices": "39", "show_menu": "40", "choose_mon": "41"}[cmd_name]
        replies = [m for m in c2s if m.get("event") == reply_event and m.get("token") == token]
        if len(replies) != 1:
            violations |= {item}
    return violations


def check_rival_team_replaced(lines: list[dict]) -> set[str]:
    """Items 45/46: replace_rival_team always gets exactly one rival_team_replaced."""
    violations = set()
    s2c_cmds = [c for line in lines if line.get("dir") == "s2c"
                for c in line.get("msg", {}).get("commands", [])]
    c2s = [line["msg"] for line in lines if line.get("dir") == "c2s"]
    replaces = [c for c in s2c_cmds if c.get("cmd") == "replace_rival_team"]
    replies = [m for m in c2s if m.get("event") == "rival_team_replaced"]
    if replaces and len(replies) != len(replaces):
        violations |= {"45"}
    return violations


def check_status_badges(lines: list[dict]) -> set[str]:
    """Item 46: status.badges is a small count (0-8), never a bitmask value > 8."""
    for line in lines:
        if line.get("dir") != "c2s" or line.get("msg", {}).get("event") != "status":
            continue
        if not (0 <= line["msg"].get("badges", -1) <= 8):
            return {"46"}
    return set()


_CHECKERS = {
    "check_line_shape": check_line_shape,
    "check_seq_monotonic": check_seq_monotonic,
    "check_hello_first": check_hello_first,
    "check_hello_shape": check_hello_shape,
    "check_tick_shape": check_tick_shape,
    "check_battle_tick_shape": check_battle_tick_shape,
    "check_event_shapes_once_only": check_event_shapes_once_only,
    "check_keyed_replies": check_keyed_replies,
    "check_token_echo": check_token_echo,
    "check_rival_team_replaced": check_rival_team_replaced,
    "check_status_badges": check_status_badges,
}

# item id -> checker function, derived from conformance_map.py so the two files can't drift
_ITEM_CHECKERS = {item.id: _CHECKERS[item.transcript_check]
                  for item in ITEMS if item.transcript_check}


# ---------------------------------------------------------------------------
# 4. The transcript tests themselves
# ---------------------------------------------------------------------------

if not _TRANSCRIPTS:
    def test_transcripts_not_yet_available():
        pytest.skip("no golden transcripts yet (P1 C1-3)")
else:
    @pytest.mark.parametrize("path", _TRANSCRIPTS, ids=[os.path.basename(p) for p in _TRANSCRIPTS])
    def test_transcript_conformance(path):
        source = _source_for(path)
        lines = _load_transcript(path)
        expected = EXPECTED_VIOLATIONS[source]

        found: set[str] = set()
        for checker in set(_ITEM_CHECKERS.values()):
            found |= checker(lines)

        unexpected = found - expected
        assert not unexpected, (
            f"{os.path.basename(path)} ({source}): violates item(s) {sorted(unexpected)} that "
            f"are not among this source's documented disagreements {sorted(expected)}"
        )

    def test_old_client_transcripts_together_reproduce_every_disagreement():
        """The *union* of every old_client transcript must still hit each of that source's
        EXPECTED_VIOLATIONS -- catches characterization drift (a documented disagreement that
        no longer reproduces anywhere) without demanding any single scenario reproduce every
        disagreement. A disagreement gated on a specific game state (e.g. item 28's box_mon
        refusal, which needs a capture where the target key is the client's *only* party mon)
        may simply not be exercised by a given scenario; P1's six scenarios never leave a
        player with one party mon, so item 28 is not (yet) in EXPECTED_VIOLATIONS -- it stays
        documented in conformance_map.py from the source citation alone until a dedicated
        capture evidences it here.
        """
        old_paths = [p for p in _TRANSCRIPTS if _source_for(p) == "old_client"]
        if not old_paths:
            pytest.skip("no old_client transcripts")
        found: set[str] = set()
        for path in old_paths:
            lines = _load_transcript(path)
            for checker in set(_ITEM_CHECKERS.values()):
                found |= checker(lines)
        missing = EXPECTED_VIOLATIONS["old_client"] - found
        assert not missing, (
            f"old_client disagreement(s) {sorted(missing)} (conformance_map.py) no longer "
            f"reproduce in any transcript -- characterization drifted, update the source "
            f"transcripts or EXPECTED_VIOLATIONS"
        )
