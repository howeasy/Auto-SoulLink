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


def check_battle_id_echo(lines: list[dict]) -> set[str]:
    """Item 45a (card C5-10, hardened per Codex's review): every s2c `replace_rival_team` that
    carries a battle identity must carry one THIS client announced for that battle -- the full
    per-player (session, battle_id, trainer_id) triple -- and a client that declared
    `battle_identity: true` in hello must see both fields on every rival command. A transcript is
    one connection, so the announced identities are that player's own. Transcripts captured before
    the field existed have neither declarations nor ids and pass silently."""
    violations: set[str] = set()
    announced: list[tuple] = []
    declared = False
    for line in lines:
        msg = line.get("msg") or {}
        if line.get("dir") == "c2s":
            if msg.get("event") == "hello" and msg.get("battle_identity") is True:
                declared = True
            elif (msg.get("event") == "trainer_battle_start"
                  and isinstance(msg.get("battle_id"), int)
                  and isinstance(msg.get("session"), str)):
                announced.append((msg["session"], msg["battle_id"], msg.get("trainer_id")))
        elif line.get("dir") == "s2c":
            for command in msg.get("commands", []):
                if command.get("cmd") != "replace_rival_team":
                    continue
                has_session, has_battle_id = "session" in command, "battle_id" in command
                if has_session != has_battle_id:
                    violations.add("45a")          # a half-identity is never legal
                elif has_session:
                    triple = (command.get("session"), command.get("battle_id"),
                              command.get("trainer_id"))
                    if triple not in announced:
                        violations.add("45a")
                elif declared:
                    violations.add("45a")          # a declared client must get both fields
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
    "check_battle_id_echo": check_battle_id_echo,
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


# =============================================================================================
# 3. World half (P4 card C4-5, docs/gen3/research/p4_gen1_contract_map.md §4.3): every item
#    tagged evidence_layer == "world" in conformance_map.py (8-38, 38a, 38b -- payload/
#    admission logic, the semantic reducer, the deaths/keys rules), driven through the
#    PRODUCTION lua/gen3/entry.lua build via tests/unit/gen3_world.py (a fake GBA bus + fake
#    server; every sent line is schema-checked at send time by World._send).
#
#    Independent of tests/unit/test_gen3_client.py (card C4-2b's own suite over the same
#    harness): this file is a SEPARATE, independently-authored check -- it does not import or
#    reuse that file's test bodies -- so a bug that file's own author didn't think to exercise
#    has a second chance to surface here. A genuine client defect found this way is reported
#    (xfail, with the evidence in the docstring), never silently patched around: this card's
#    charter is to be an independent check of the client, not its author.
# =============================================================================================
from tests.unit.conformance_map import ITEMS as _ITEMS  # noqa: E402
from tests.unit.gen3_world import ARTIFACTS, World, key_of, mon_record  # noqa: E402

_OT = 0x0000ABCD
_A, _B, _C = 0x11111111, 0x22222222, 0x33333333
_KA, _KB, _KC = key_of(_A, _OT), key_of(_B, _OT), key_of(_C, _OT)
_FOE = mon_record(0x77777777, 0x1234, species=19, level=3)


def _party(*pids, hp=20):
    return [mon_record(p, _OT, species=4 + i, nickname=f"MON{i}", hp=hp) for i, p in enumerate(pids)]


def _live(pack="gen3_frlg", title="firered", kind=None, pids=(_A, _B), frames=60):
    w = World(pack, title, kind)
    w.set_party(_party(*pids))
    w.step_to(frames)
    return w


_WORLD_TESTS: dict[str, object] = {}


def world_item(*item_ids):
    """Registers the decorated test function against one or more conformance_map item ids."""
    def deco(fn):
        for item_id in item_ids:
            assert item_id not in _WORLD_TESTS, f"duplicate World test registered for item {item_id!r}"
            _WORLD_TESTS[item_id] = fn
        return fn
    return deco


def test_every_world_item_has_a_world_test():
    """The meta-test: every conformance_map item tagged 'world' has an entry in _WORLD_TESTS
    (an xfail with an item-level reason counts -- see item 11 below -- but the entry itself
    must exist; a genuinely unexercisable item would need an explicit skip entry, none exist
    today)."""
    world_ids = {item.id for item in _ITEMS if item.evidence_layer == "world"}
    missing = sorted(world_ids - set(_WORLD_TESTS))
    assert not missing, f"conformance items tagged 'world' with no World test: {missing}"


# ── 8/9: hello shape, on every admitted artifact ────────────────────────────────────────────

@world_item("8", "9")
def test_world_hello_carries_the_required_fields_on_every_artifact():
    for pack, title, kind in ARTIFACTS:
        w = World(pack, title, kind)
        w.set_party(_party(_A, _B))
        w.set_balls(3)
        w.step_to(60)
        (hello,) = w.events("hello")
        assert hello["rom_type"] and isinstance(hello["party"], list), (pack, title, kind)
        assert isinstance(hello.get("has_pokeballs"), bool), (pack, title, kind)
        assert isinstance(hello.get("badges"), int), (pack, title, kind)
        for entry in hello["party"]:
            for field in ("key", "hp", "maxHP", "level", "slot", "species_id", "nickname", "blob_hex"):
                assert field in entry, (pack, title, kind, field)
            assert len(entry["blob_hex"]) == 200, (pack, title, kind, entry["blob_hex"])


@pytest.fixture(autouse=True)
def _battle_nonce(monkeypatch):
    """The battle request nonce is minted by the bootstrap (lua/gen3/run.lua) and consumed through
    $SLINK_GEN3_BATTLE_NONCE, the documented seam; the lupa harness builds Entry directly, so
    without this the client fails closed (no identity, no capability) and every rival test would
    refuse. A test that needs distinct sessions overrides the value itself."""
    monkeypatch.setenv("SLINK_GEN3_BATTLE_NONCE", "0000BEEF")


# ── 45a: the battle request identity (card C5-10) ───────────────────────────────────────────

@world_item("45a")
def test_world_battle_identity_is_minted_per_battle_and_guards_the_swap():
    """The client's half of the contract: `trainer_battle_start` announces a session nonce and a
    per-battle counter, and `replace_rival_team` is refused (`stale_battle_id`, nothing written)
    unless it carries both for the battle the client is in."""
    w = World("gen3_rr", "radical_red", "companion")
    w.set_party(_party(_A, _B))
    w.set_balls(3)
    w.step_to(60)
    w.enter_battle([_FOE], trainer_id=42)
    w.step(61)                      # the same warm-up test_gen3_client.py's own event test uses
    (start,) = w.events("trainer_battle_start")
    assert isinstance(start["session"], str) and 0 < len(start["session"]) <= 16, start
    assert start["battle_id"] == 1, start
    before = list(w.writes)
    w.command(cmd="replace_rival_team", trainer_id=42, n=1, blobs_hex=["00" * 100])
    w.step()
    (reply,) = w.events("rival_team_replaced")
    assert reply["error"] == "stale_battle_id", reply
    assert w.writes == before, "a refused swap must write nothing"


# ── 10: ot_id present, or derivable from party[0].key ───────────────────────────────────────

@world_item("10")
def test_world_ot_id_is_present_or_derivable_from_the_party_key():
    for pack, title, kind in ARTIFACTS:
        w = World(pack, title, kind)
        w.set_party(_party(_A, _B))
        w.step_to(60)
        (hello,) = w.events("hello")
        if "ot_id" in hello:
            assert hello["ot_id"] == _OT, (pack, title, kind)
        else:
            pid_hex, ot_hex = hello["party"][0]["key"].split(":")
            assert int(ot_hex, 16) == _OT, (pack, title, kind, "ot_id not derivable from party[0].key")


# ── 11: hello omits party contents when not loaded / borrowed ──────────────────────────────

@world_item("11")
def test_world_hello_omits_party_when_borrowed():
    """The not-loaded half of item 11 holds structurally: game_is_live() gates hello_ready()
    entirely (client.lua:598-605, 616-621), so no hello -- let alone one with a party -- is
    ever sent before the save is loaded (see test_world_tick_is_periodic_..., which checks a
    pre-game save sends no hello at all). This test is the borrowed half.
    """
    w = _live()
    w.enter_battle([_FOE], active=(0,))
    w.step()
    w.set_party([mon_record(0x99999999, 0x5555, species=7, hp=20)])  # a partner's party in RAM
    w.fire("map_load")     # any signal with a flag, so settle() actually runs update_frozen
    w.step()
    assert w.client.state.frozen is True
    w.connected = False
    w.step()
    w.connected = True
    w.step()
    (hello,) = w.events("hello")[-1:]
    assert hello["party"] == [], (
        "hello sent the borrowed party instead of [] on a mid-battle reconnect: "
        f"{[m['key'] for m in hello['party']]}")


# ── 12: WRONG SAVE toast, either field spelling, no crash ──────────────────────────────────

@world_item("12")
def test_world_wrong_save_toast_accepts_either_field_spelling_without_crashing():
    w = _live()
    w.command(cmd="hud_show", text="[x] WRONG SAVE", color=[255, 60, 60], duration=300)
    w.command(cmd="hud_show", text="[x] WRONG SAVE", r=255, g=60, b=60, frames=300)
    w.step()
    shows = [h for h in w.hud if h[0] == "show" and "WRONG SAVE" in h[1]]
    assert len(shows) == 2


# ── 13: resolved_areas + config booleans applied ────────────────────────────────────────────

@world_item("13")
def test_world_resolved_areas_and_config_booleans_are_applied():
    w = _live()
    w.command(cmd="resolved_areas", areas=["route_1", "route_2"])
    w.command(cmd="config", battle_calc=True, native_messages=False)
    w.step()
    assert w.client.seeded is True
    assert w.client.resolved_areas["route_1"] is True
    assert w.client.resolved_areas["route_2"] is True
    assert w.client.config.battle_calc is True
    assert w.client.config.native_messages is False
    w.command(cmd="resolved_areas", areas=[])           # an empty list is still applied
    w.step()
    assert w.client.seeded is True
    assert w.client.resolved_areas["route_1"] is None


# ── 14: tick is periodic (every 30 frames) with required fields ────────────────────────────

@world_item("14")
def test_world_tick_is_periodic_every_30_frames_with_required_fields():
    for pack, title, kind in ARTIFACTS:
        w = World(pack, title, kind)
        w.set_party(_party(_A, _B))
        w.set_balls(2)
        w.step_to(29)
        assert w.events("tick") == [], (pack, title, kind, "a tick fired before frame 30")
        w.step()                                          # frame 30
        assert len(w.events("tick")) == 1, (pack, title, kind)
        w.step_to(59)
        assert len(w.events("tick")) == 1, (pack, title, kind, "a tick fired off-cadence")
        w.step()                                          # frame 60
        ticks = w.events("tick")
        assert len(ticks) == 2, (pack, title, kind)
        for field in ("has_pokeballs", "area_id", "loc_name", "in_battle", "badges"):
            assert field in ticks[-1], (pack, title, kind, field)
        assert ticks[-1]["enemy_party"] == [], (pack, title, kind)


def test_world_no_hello_before_the_save_is_loaded():
    w = World()
    w.set_trainer(0)
    w.step(100)
    assert w.events("hello") == []


# ── 15/16: battle tick shape (wild / trainer) ───────────────────────────────────────────────

@world_item("15")
def test_world_wild_battle_tick_has_enemy_party_and_a_known_area():
    w = _live()
    w.enter_battle([_FOE])
    w.step_to(w.frame + 31)
    battle_ticks = [t for t in w.events("tick") if t["in_battle"]]
    assert battle_ticks
    t = battle_ticks[-1]
    assert t["is_trainer_battle"] is False
    assert t["area_id"]
    assert t["enemy_party"] and t["enemy_party"][0]["species_id"] > 0


@world_item("16")
def test_world_trainer_battle_tick_has_a_positive_trainer_id():
    w = _live()
    w.enter_battle([_FOE], trainer_id=7)
    w.step_to(w.frame + 31)
    battle_ticks = [t for t in w.events("tick") if t["in_battle"]]
    t = battle_ticks[-1]
    assert t["is_trainer_battle"] is True and t["trainer_id"] == 7


# ── 17: status_cond bit layout; pp_bonuses present alongside moves ─────────────────────────

@world_item("17")
def test_world_status_cond_and_pp_bonuses_are_present_alongside_moves():
    w = World()
    poisoned = mon_record(_A, _OT, species=4, hp=20)
    poisoned["status"] = 0x08          # PSN: Gen 3's native status1 layout IS the wire layout,
    w.set_party([poisoned])            # docs/protocol.md item 17 / §8-5 -- no translation needed
    w.step_to(60)
    (hello,) = w.events("hello")
    entry = hello["party"][0]
    assert entry["status_cond"] == 0x08
    assert "moves" in entry and "pp_bonuses" in entry


# ── 18: pc_boxes 0-based box/slot; memorial box index ───────────────────────────────────────

@world_item("18")
def test_world_pc_boxes_entries_are_0_based_and_the_memorial_box_is_named():
    w = World()
    w.set_party(_party(_A))
    w.set_box(2, 5, mon_record(_B, _OT, species=7))
    w.step_to(60)
    (hello,) = w.events("hello")
    entry = [e for e in hello["pc_boxes"] if e["key"] == _KB][0]
    assert entry["box"] == 2 and entry["slot"] == 5
    assert w.parts.boxes is not None
    assert w.parts.boxes.memorial_box == (w.d.get("BOXES_PER_STORE", 1) - 1)


# ── 19: safe once after battle, field-less ──────────────────────────────────────────────────

@world_item("19")
def test_world_safe_is_sent_once_after_battle_and_carries_no_extra_fields():
    w = _live()
    w.enter_battle([_FOE])
    w.step(5)
    w.leave_battle()
    w.step()
    (safe,) = w.events("safe")
    assert set(safe) == {"event", "player", "seq"}


# ── 20: area_enter on map change, known/empty area_id ───────────────────────────────────────

@world_item("20")
def test_world_area_enter_fires_once_per_map_change_with_a_known_or_empty_area_id():
    w = _live()
    w.set_location(1, 0)
    w.fire("map_load")
    w.step()
    (first,) = w.events("area_enter")
    assert first["area_id"] == "viridian_forest"
    w.fire("map_load")                 # the same map again: no re-fire
    w.step()
    assert len(w.events("area_enter")) == 1
    w.set_location(99, 99)             # an unmapped location: empty, not a crash
    w.fire("map_load")
    w.step()
    assert w.events("area_enter")[-1]["area_id"] == ""


# ── 21: capture required fields ─────────────────────────────────────────────────────────────

@world_item("21")
def test_world_capture_has_the_required_fields():
    w = _live(pids=(_A, _B))
    w.set_party(_party(_A, _B, _C))
    w.fire("mon_given")
    w.step()
    (cap,) = w.events("capture")
    assert cap["key"] == _KC and cap["area_id"] and cap["species_id"] > 0 and cap["level"] > 0


# ── 22: pre-pokeball capture uses area_id="intro" ───────────────────────────────────────────

@world_item("22")
def test_world_a_pre_pokeball_capture_uses_the_intro_area_id():
    w = World()
    w.set_location(0, 0)               # data/games/gen3_frlge/area_map.json: "0:0" -> "intro"
    w.set_party([])
    w.step_to(60)
    w.set_party(_party(_A))
    w.fire("mon_given")
    w.step()
    (cap,) = w.events("capture")
    assert cap["area_id"] == "intro"


# ── 23: no_catch once per unresolved area, never after a capture ──────────────────────────

@world_item("23")
def test_world_no_catch_fires_once_per_unresolved_area_and_never_after_a_capture():
    w = _live()
    w.set_balls(3)
    w.step(30)
    w.enter_battle([_FOE])
    w.step(30)
    w.leave_battle(outcome=4)          # ran: unresolved
    w.step()
    assert len(w.events("no_catch")) == 1
    w.enter_battle([_FOE])             # a second failed battle in the SAME, now-resolved area
    w.step(30)
    w.leave_battle(outcome=4)
    w.step()
    assert len(w.events("no_catch")) == 1, "no_catch re-fired for an already-resolved area"

    w2 = _live()
    w2.set_balls(3)
    w2.step(30)
    w2.enter_battle([_FOE])
    w2.set_party(_party(_A, _B, _C))
    w2.fire("capture_wild")
    w2.fire("mon_given")
    w2.step()
    assert w2.events("capture")
    w2.leave_battle(outcome=7)         # caught
    w2.step()
    assert w2.events("no_catch") == [], "no_catch fired after a capture in the same battle"


# ── 24: unresolve_area re-arms no_catch ─────────────────────────────────────────────────────

@world_item("24")
def test_world_unresolve_area_re_arms_no_catch():
    w = _live()
    w.set_balls(3)
    w.set_location(3, 19)              # route_1, World's default
    w.enter_battle([_FOE])
    w.step(30)
    w.leave_battle(outcome=4)
    w.step()
    assert len(w.events("no_catch")) == 1
    w.command(cmd="unresolve_area", area_id="route_1")
    w.step()
    w.enter_battle([_FOE])
    w.step(30)
    w.leave_battle(outcome=4)
    w.step()
    assert len(w.events("no_catch")) == 2


# ── 25: faint once per real transition, never for a commanded zero ─────────────────────────

@world_item("25")
def test_world_faint_fires_once_per_real_transition_and_never_for_a_commanded_zero():
    w = _live()
    w.set_party([mon_record(_A, _OT, species=4), mon_record(_B, _OT, species=5, hp=0)])
    w.fire("faint")
    w.step()
    (f,) = w.events("faint")
    assert f["key"] == _KB
    w.fire("faint")                    # the same transition again: no re-fire
    w.step()
    assert len(w.events("faint")) == 1
    w.battle_ok = True
    w.enter_battle([_FOE], active=(0,))
    w.command(cmd="force_faint", key=_KA)
    w.step()
    w.fire("faint")
    w.step()
    assert [e["key"] for e in w.events("faint")] == [_KB], "a commanded zero was reported"


# ── 26: whiteout exactly once ────────────────────────────────────────────────────────────────

@world_item("26")
def test_world_whiteout_fires_exactly_once_per_whiteout():
    w = _live()
    w.fire("whiteout")
    w.fire("whiteout")
    w.step()
    assert len(w.events("whiteout")) == 1
    w.fire("whiteout")
    w.step()
    assert len(w.events("whiteout")) == 2


# ── 27: party_to_box / box_to_party for real, non-commanded moves ─────────────────────────

@world_item("27")
def test_world_party_to_box_and_box_to_party_fire_for_real_pc_moves():
    w = _live(pids=(_A, _B))
    w.set_party(_party(_A))
    w.set_box(0, 0, mon_record(_B, _OT, species=5))
    w.fire("pc_deposit")
    w.step()
    (dep,) = w.events("party_to_box")
    assert dep["key"] == _KB
    w.set_box(0, 0, None)
    w.set_party(_party(_A, _B))
    w.fire("pc_withdraw")
    w.step()
    assert [e["key"] for e in w.events("box_to_party")] == [_KB]


# ── deferred command double: items 27 (suppression half)/28/29/30/31/32 ────────────────────

class _FakeBoxes:
    """A box-mover double with lua/gen3/boxes.lua's own contract (true | nil, reason):
    idempotent deposit/withdraw (a key already on the "wrong" side of the move is a no-op
    success, matching boxes.lua's `if mon then ... return true end` /
    `if not mon then if boxed then return true end ... end`) and the "last party mon" refusal.
    These items are about the SESSION/DEFERRED contract (FIFO, one-per-frame, safe-state
    gating, stats_cache ordering, keyed idempotent acks) -- lua/core/session.lua and
    lua/core/deferred.lua (P4 card C4-1) -- not boxes.lua's byte math, which is boxes.lua's own
    card (C4-3, tests/unit/test_gen3_boxes.py). The real production boxes.lua IS used
    separately below for item 28's refuse-the-last-party-mon claim, which needs no ROM
    species/PP-Up data (the refusal returns before any of that is read).
    """

    def __init__(self, party_keys):
        self.calls: list[tuple[str, str]] = []
        self.party = set(party_keys)
        self.boxed: set[str] = set()
        self.memorial: set[str] = set()

    def table(self, L):
        def deposit(_self, key, *_rest):
            key = str(key)
            self.calls.append(("deposit", key))
            if key not in self.party:
                return (True, None) if key in self.boxed else (None, "key not in party")
            if len(self.party) <= 1:
                return None, "last party mon"
            self.party.discard(key)
            self.boxed.add(key)
            return True, None

        def withdraw(_self, key, *_rest):
            key = str(key)
            self.calls.append(("withdraw", key))
            if key in self.party:
                return True, None
            if key not in self.boxed:
                return None, "key not boxed"
            self.boxed.discard(key)
            self.party.add(key)
            return True, None

        def memorialize(_self, key, *_rest):
            key = str(key)
            self.calls.append(("memorialize", key))
            if key in self.memorial:
                return True, None
            self.boxed.discard(key)
            self.party.discard(key)
            self.memorial.add(key)
            return True, None

        return L.table(deposit=deposit, withdraw=withdraw, memorialize=memorialize, memorial_box=13)


def _boxed_world(pack="gen3_frlg", title="firered", kind=None, pids=(_A, _B)):
    keys = [key_of(p, _OT) for p in pids]
    fake = _FakeBoxes(keys)
    w = World(pack, title, kind, boxes=fake.table)
    w.set_party(_party(*pids))
    w.step_to(60)
    return w, fake


@world_item("28")
def test_world_box_mon_deposits_when_safe_sends_stats_cache_first_and_refuses_the_last_mon():
    w, fake = _boxed_world()
    w.command(cmd="box_mon", key=_KB)
    w.step()
    assert fake.calls == [("deposit", _KB)]
    (cache,) = w.events("stats_cache")
    assert cache["key"] == _KB and w.events("box_mon_failed") == []
    w.fire("pc_deposit")               # a later PC signal: our own move is not re-reported
    w.step()
    assert w.events("party_to_box") == []

    w2 = _live(pids=(_A,))             # the REAL production boxes.lua; no ROM data needed here
    w2.command(cmd="box_mon", key=_KA)
    w2.step()
    assert w2.writes == []
    assert w2.events("box_mon_failed")[0]["reason"] == "last party mon"
    assert w2.events("stats_cache") == []


@world_item("29")
def test_world_party_mon_withdraws_when_safe_and_acks_an_already_present_key_as_done():
    w, fake = _boxed_world(pids=(_A, _B))
    w.command(cmd="box_mon", key=_KB)
    w.step()
    w.command(cmd="party_mon", key=_KB)
    w.step()
    assert ("withdraw", _KB) in fake.calls
    assert [e["key"] for e in w.events("sync_retrieve_done")] == [_KB]
    assert w.events("sync_retrieve_failed") == []
    w.command(cmd="party_mon", key=_KB)  # already present: acked as done, no crash
    w.step()
    assert len(w.events("sync_retrieve_done")) == 2


@world_item("30")
def test_world_memorialize_moves_when_safe_and_names_the_memorial_box():
    w, fake = _boxed_world(pids=(_A, _B))
    w.command(cmd="memorialize", key=_KB)
    w.step()
    (done,) = w.events("memorialize_done")
    assert done["key"] == _KB and done["box"] == 13
    assert w.events("memorialize_failed") == []
    assert fake.calls == [("memorialize", _KB)]


# ── 31: deferred FIFO, one/frame, safe-state only, opposing keys converge ─────────────────

@world_item("31")
def test_world_deferred_commands_run_fifo_one_per_frame_only_while_safe():
    w, fake = _boxed_world(pids=(_A, _B, _C))
    w.break_checkpoint()
    w.command(cmd="box_mon", key=_KB)
    w.command(cmd="box_mon", key=_KC)
    w.step(5)
    assert fake.calls == [], "a deferred command ran while the checkpoint did not hold"
    w.overworld_safe()
    w.step()
    assert fake.calls == [("deposit", _KB)], "more than one command ran in a single frame"
    w.step()
    assert fake.calls == [("deposit", _KB), ("deposit", _KC)]

    w.command(cmd="party_mon", key=_KB)  # opposing box_mon/party_mon for one key: net converges
    w.step()
    assert fake.party == {_KA, _KB}
    assert w.events("sync_retrieve_done")[-1]["key"] == _KB


# ── 32: commands on an unknown key are silent no-ops ────────────────────────────────────────

@world_item("32")
def test_world_commands_for_an_unknown_key_are_silent_no_ops():
    w, fake = _boxed_world()
    unknown = key_of(0xDEADBEEF, _OT)
    w.command(cmd="force_faint", key=unknown)
    w.command(cmd="box_mon", key=unknown)
    w.step(2)
    assert fake.calls == [("deposit", unknown)]     # attempted, gracefully refused
    assert w.writes == []
    assert w.events("box_mon_failed")[0]["key"] == unknown


# ── 33/34/35: deaths ─────────────────────────────────────────────────────────────────────────

@world_item("33")
def test_world_force_faint_on_a_benched_mon_lands_immediately_with_no_faint_report():
    w = _live()
    w.battle_ok = True
    w.enter_battle([_FOE], active=(0,))
    w.command(cmd="force_faint", key=_KB)
    w.step()
    assert w.party_hp(1) == 0
    w.step(30)
    w.fire("faint")
    w.step()
    assert w.events("faint") == []


@world_item("34")
def test_world_force_explode_is_handled_at_least_as_force_faint_on_vanilla_frlg():
    """FRLG now commits the same engine Explosion contract; HP remains the engine's to change.
    A later switch-out still lands the established linked bench-faint rule."""
    w = _live()
    w.battle_ok = True
    w.enter_battle([_FOE], active=(0,))
    w.command(cmd="force_explode", key=_KA)
    w.step(3)
    assert w.writes and w.client.battle_pending_count(w.client) == 1
    assert w._read(0x03004FE0, 4) == 0x0802E33D and w._read(0x02023DC4, 2) == 153
    assert w._read(w.ram["BATTLE_MONS_ADDR"] + 0x24, 1) == 5 and w.party_hp(0) == 20
    w.set_active([1])
    w.battle_ok = True  # the engine has returned from the hand-off to a new parked menu
    w.step()
    assert w.party_hp(0) == 0
    # RR (owner ruling 19, G5-EXPLODE-HANDOFF): force_faint on the active battler is mechanism
    # P+H, and force_explode's menu skip now ends in the same hand-off, so Explosion is committed
    # on the same frame, with no press: at least as force_faint.
    w = _live("gen3_rr", "radical_red", "companion")
    w.battle_ok = True
    w.enter_battle([_FOE], active=(0,))
    w.command(cmd="force_explode", key=_KA)
    w.step()
    assert w._read(0x03004FE0, 4) == 0x0802E33D and w._read(0x02023DC4, 2) == 153   # committed + handed off
    assert w._read(0x02023E82, 1) == 3 and w.party_hp(0) == 20
    w = _live("gen3_rr", "radical_red", "companion")
    w.battle_ok = True
    w.enter_battle([_FOE], active=(0,))
    w.command(cmd="force_faint", key=_KA)
    w.step()
    assert w._read(0x03004FE0, 4) == 0x0802E33D and w.party_hp(0) == 20   # P+H committed


@world_item("35")
def test_world_game_over_sets_persistent_hud_state_and_ticks_keep_running():
    w = _live()
    before = len(w.events("tick"))
    w.command(cmd="game_over")
    w.step()
    assert w.client.game_over is True
    assert any(h[0] == "game_over" for h in w.hud)
    w.step(31)
    assert len(w.events("tick")) > before


# ── 36/37/38/38a/38b: keys ───────────────────────────────────────────────────────────────────

@world_item("36")
def test_world_keys_are_stable_across_a_box_party_move_and_a_reconnect():
    w, fake = _boxed_world(pids=(_A, _B))
    w.command(cmd="box_mon", key=_KB)
    w.step()
    w.command(cmd="party_mon", key=_KB)
    w.step()
    assert w.events("sync_retrieve_done")[-1]["key"] == _KB
    w.connected = False
    w.step()
    w.connected = True
    w.step()
    (hello,) = w.events("hello")[-1:]
    assert {m["key"] for m in hello["party"]} == {_KA, _KB}


@world_item("37")
def test_world_a_same_mon_key_change_is_reported_with_no_spurious_move_events():
    w = _live(pids=(_A, _B))
    w.fire("trade_begin")
    w.step()
    w.set_party([mon_record(_A, _OT), mon_record(_C, 0x9999, species=122)])
    w.fire("trade_done")
    w.step()
    (kc,) = w.events("key_change")
    assert kc["old_key"] == _KB and kc["new_key"] == key_of(_C, 0x9999)
    assert w.events("capture") == [] and w.events("party_to_box") == [] and w.events("box_to_party") == []


@world_item("38")
def test_world_the_two_halves_of_a_link_produce_distinct_keys():
    """A shape-level check only: two independent saves with distinct PID/OT naturally never
    collide. Real-fixture collision avoidance (the same inputs on FR vs LG producing the same
    TID/PID) is C4-6's fixture card, not this World harness's concern
    (docs/gen3/research/p4_gen1_contract_map.md §4.2)."""
    wa = World(player="a")
    wa.set_party(_party(_A, _B))
    wa.step_to(60)
    wb = World(player="b")
    wb.set_party([mon_record(0x44444444, 0x5555, species=1)])
    wb.step_to(60)
    ka = {m["key"] for m in wa.events("hello")[0]["party"]}
    kb = {m["key"] for m in wb.events("hello")[0]["party"]}
    assert ka.isdisjoint(kb)


@world_item("38a")
def test_world_key_change_ack_and_rejected_each_answer_a_key_change_once():
    w = _live(pids=(_A, _B))
    w.fire("trade_begin")
    w.step()
    w.set_party([mon_record(_A, _OT), mon_record(_C, 0x9999, species=122)])
    w.fire("trade_done")
    w.step()
    (kc,) = w.events("key_change")
    w.command(cmd="key_change_ack", old_key=kc["old_key"], new_key=kc["new_key"], migrated=True)
    w.step(30)
    assert len(w.events("key_change")) == 1        # resolved: not re-sent once acked

    w2 = _live(pids=(_A, _B))
    w2.fire("trade_begin")
    w2.step()
    w2.set_party([mon_record(_A, _OT), mon_record(0xAAAAAAAA, 0x9999, species=122)])
    w2.fire("trade_done")
    w2.step()
    (kc2,) = w2.events("key_change")
    w2.command(cmd="key_change_rejected", old_key=kc2["old_key"], new_key=kc2["new_key"],
               reason="collision")
    w2.step(5)
    assert any(h[0] == "show" and "IDENTITY CHANGE REFUSED" in h[1] for h in w2.hud)


@world_item("38b")
def test_world_a_repeated_key_change_ack_is_idempotent_and_does_not_crash():
    w = _live(pids=(_A, _B))
    w.fire("trade_begin")
    w.step()
    w.set_party([mon_record(_A, _OT), mon_record(_C, 0x9999, species=122)])
    w.fire("trade_done")
    w.step()
    (kc,) = w.events("key_change")
    w.command(cmd="key_change_ack", old_key=kc["old_key"], new_key=kc["new_key"], migrated=True)
    w.step()
    w.command(cmd="key_change_ack", old_key=kc["old_key"], new_key=kc["new_key"], migrated=False)
    w.step(5)                                       # no crash, nothing re-sent
    assert len(w.events("key_change")) == 1


# ── Emerald rows of the per-artifact World items (docs/gen3_emerald/PLAN.md E3, EG3 exit) ──────
# Since EG4 (ruling 24), the production Entry admits Emerald directly, so these rows run the
# REAL production client over a tmp copy of lua/ + the Emerald pack (test_gen3_emerald_client.py's
# pattern) -- a tmp copy only so PACK_DIRS/ENTRY can be redirected without touching the shipped
# tree. They replay the per-artifact bodies above with ARTIFACTS narrowed to the Emerald
# cartridge.

@pytest.fixture
def _emerald_admitted(tmp_path, monkeypatch):
    import shutil

    from tests.unit import gen3_world as gw
    shutil.copytree(gw.REPO / "lua", tmp_path / "lua")
    pack_dir = tmp_path / "data" / "games" / "gen3_emerald"
    shutil.copytree(gw.REPO / "data" / "games" / "gen3_emerald", pack_dir)
    monkeypatch.setattr(gw, "REPO", tmp_path)
    monkeypatch.setattr(gw, "ENTRY", (tmp_path / "lua" / "gen3" / "entry.lua").as_posix())
    monkeypatch.setitem(gw.PACK_DIRS, "gen3_emerald", pack_dir)
    monkeypatch.setitem(globals(), "ARTIFACTS", [("gen3_emerald", "emerald", "clean")])


@pytest.mark.parametrize("body", [test_world_hello_carries_the_required_fields_on_every_artifact,
                                  test_world_ot_id_is_present_or_derivable_from_the_party_key,
                                  test_world_tick_is_periodic_every_30_frames_with_required_fields],
                         ids=["8-9_hello", "10_ot_id", "14_tick"])
def test_world_rows_on_emerald(_emerald_admitted, body):
    body()
