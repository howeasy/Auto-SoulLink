"""Private, hash-pinned Gen 2 trade server bootstrap; never a production admission grant.

python -m tools.gen2_trade_lane --manifest ATTEMPT.json -- <server arguments>
The override exists only in this child process and is attributed HARNESS_ONLY_OVERLAY.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCENARIOS = frozenset({"gen2_trade_new", "gen2_trade_decline_new", "gen2_trade_timeout",
                       "gen2_trade_reset_wait", "gen2_trade_reset_commit", "gen2_trade_refuse_item",
                       "gen2_trade_evolve"})
ATTRIBUTION = "HARNESS_ONLY_OVERLAY"
TITLES = {name: title for title in ("crystal", "gold", "silver") for name in (title, title.title())}
TOP_KEYS = {"schema", "run_id", "scenario", "evidence_class", "provenance_sha256", "players"}
PLAYER_KEYS = {"title", "rom_type", "foundation", "artifact_kind", "rom_sha1", "base_sha1", "ups_sha256", "sym_sha256"}
# Native Gen 2 client emissions; query/offer are handled by state.handle_event even
# though server._dispatch's explicit logging list only names menu_result/trade_done.
TRADE_EVENTS = frozenset({"trade_query", "trade_offer", "menu_result", "trade_done"})


def _need(condition, message):
    if not condition:
        raise ValueError(f"{ATTRIBUTION}: {message}")


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _need(key not in result, f"duplicate JSON key {key}")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def _repo_path(root, relative):
    _need(isinstance(relative, str), "artifact path missing")
    path = (root / relative).resolve()
    _need(path.is_relative_to(root), "artifact path escapes repository")
    return path


def validate_manifest(path, *, root=ROOT):
    """Validate an exact manifest (path or dict) against actual published artifacts; return a copy."""
    from patch.tools.make_ups import ups_apply

    root = Path(root).resolve()
    try:
        doc = copy.deepcopy(path) if isinstance(path, dict) else _json(Path(path).read_text(encoding="utf-8"))
        _need(isinstance(doc, dict) and set(doc) == TOP_KEYS, "manifest fields differ")
        _need(doc["schema"] == "gen2-trade-lane-v1" and doc["evidence_class"] == ATTRIBUTION, "schema/attribution differs")
        _need(isinstance(doc["run_id"], str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", doc["run_id"]), "invalid run_id")
        _need(isinstance(doc["scenario"], str) and doc["scenario"] in SCENARIOS, "unknown trade scenario")
        raw = (root / "data/gen2/overlay_provenance.json").read_bytes()
        _need(doc["provenance_sha256"] == hashlib.sha256(raw).hexdigest(), "overlay provenance pin differs")
        provenance = _json(raw)
        lock = _json((root / "data/gen2_sources.lock.json").read_bytes())
        _need(isinstance(doc["players"], dict) and set(doc["players"]) == {"a", "b"}, "expected players a/b")
        checked = {}
        for side, row in doc["players"].items():
            _need(isinstance(row, dict) and set(row) == PLAYER_KEYS, f"{side}: player fields differ")
            title = row["title"]
            _need(isinstance(title, str) and title in ("crystal", "gold", "silver")
                  and isinstance(row["rom_type"], str) and TITLES.get(row["rom_type"]) == title,
                  f"{side}: title/rom_type differs")
            _need(row["foundation"] == "gen2_gsc" and row["artifact_kind"] == "overlay", f"{side}: wrong foundation/kind")
            if title not in checked:
                artifact = f"poke{title}"
                out = provenance["outputs"][artifact]
                source = lock["outputs"][artifact]
                profile = _json((root / f"data/games/gen2_{title}/profile.json").read_bytes())["titles"][title]
                ov = profile["overlay"]
                ups = _repo_path(root, out["ups"]["file"]).read_bytes()
                _need(ov["sym"] == f"{title}_slink.sym", f"{title}: unexpected symbol file")
                symbols = _repo_path(root, "data/gen2/" + ov["sym"]).read_bytes()
                base_repo = "pokecrystal" if title == "crystal" else "pokegold"
                base = _repo_path(root, f".cache/gen2-build/{base_repo}/{source['filename']}").read_bytes()
                _need(hashlib.sha1(base).hexdigest() == source["sha1"] == out["base_sha1"]
                      == profile["rom_sha1"] == ov["base_sha1"], f"{title}: clean base binding differs")
                _need(hashlib.sha256(ups).hexdigest() == out["ups"]["sha256"], f"{title}: published UPS differs")
                _need(hashlib.sha256(symbols).hexdigest() == ov["sym_sha256"] == provenance["symbols"][ov["sym"]],
                      f"{title}: overlay symbols differ")
                _need(hashlib.sha1(ups_apply(base, ups)).hexdigest() == out["sha1"] == ov["rom_sha1"],
                      f"{title}: applied overlay differs")
                _need(isinstance(ov.get("trade"), dict) and ov["trade"], f"{title}: overlay lacks native trade family")
                checked[title] = {"rom_sha1": out["sha1"], "base_sha1": out["base_sha1"],
                                  "ups_sha256": out["ups"]["sha256"], "sym_sha256": ov["sym_sha256"]}
            _need(all(row[key] == value for key, value in checked[title].items()), f"{side}: artifact pin differs")
        return doc
    except (OSError, KeyError, TypeError, AttributeError, RuntimeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{ATTRIBUTION}: malformed or unavailable manifest artifact: {exc}") from exc


def _hello_problem(manifest, player, msg):
    if not isinstance(player, str) or player not in manifest["players"] or msg.get("player") != player:
        return "unknown or contradictory player"
    row = manifest["players"][player]
    rom_type = msg.get("rom_type")
    if not isinstance(rom_type, str) or TITLES.get(rom_type) != row["title"]:
        return "unexpected ROM title"
    if "title" in msg and msg["title"] != row["title"]:
        return "contradictory title"
    if msg.get("foundation") != "gen2_gsc" or msg.get("artifact_kind") != "overlay":
        return "unexpected foundation/artifact kind"
    sha = msg.get("rom_sha1")
    if not isinstance(sha, str) or sha.lower() != row["rom_sha1"]:
        return "missing or mismatched overlay SHA1"
    return None


def install_server_gate(server_module, manifest, *, root=ROOT, audit_path=None):
    """Install on the imported server class, returning an idempotent restoration callback."""
    doc = validate_manifest(manifest, root=root)
    cls = server_module.SLinkServer
    original_decide, original_handle = cls._decide_admission, cls.handle_client
    original_dispatch = cls._dispatch
    state_cls = server_module.SoulLinkState
    original_watchdog = state_cls._tick_pending_trade
    _need(not getattr(original_decide, "_gen2_trade_lane", False), "trade gate already installed")
    # The returned restore callback owns this handle for the server's whole lifetime.
    audit = Path(audit_path).open("x", encoding="utf-8", newline="\n") if audit_path is not None else None  # noqa: SIM115
    audit_seq = 0
    active_dispatches = []

    def watchdog(state):
        result = original_watchdog(state)
        if active_dispatches:
            context = active_dispatches[-1]
            if context["state"] is state and not context["watchdog_observed"]:
                # Source handle_event calls this once, before consuming this message's party.
                context.update(watchdog_observed=True, pending_trade_after_watchdog=pending_trade(state),
                               trade_problem_after_watchdog=copy.deepcopy(state.trade_problem()),
                               trade_last_after_watchdog=copy.deepcopy(state.trade_last))
        return result

    def record(player, message, outcome):
        nonlocal audit_seq
        if audit is None:
            return
        audit_seq += 1
        row = {"seq": audit_seq, "source": "server_dispatch", "evidence_class": ATTRIBUTION,
               "run_id": doc["run_id"], "scenario": doc["scenario"], "player": player,
               "message": message, "outcome": outcome}
        audit.write(json.dumps(row, ensure_ascii=True) + "\n")
        audit.flush()

    def dispatch(self, player, msg):
        event = msg.get("event")
        before = pending_trade(self.state) if audit is not None else None
        original_message = copy.deepcopy(msg) if audit is not None else None
        context = {"state": self.state, "watchdog_observed": False, "pending_trade_after_watchdog": None,
                   "trade_problem_after_watchdog": None, "trade_last_after_watchdog": None}

        def after_dispatch(outcome):
            if audit is None:
                return
            after = pending_trade(self.state)
            middle = context["pending_trade_after_watchdog"]
            phases = {(row or {}).get("phase") for row in (before, middle, after)}
            was = (before or {}).get("verdict") or {}
            now = (after or {}).get("verdict") or {}
            during = (middle or {}).get("verdict") or {}
            into_await = any((now.get(side) == "await" or during.get(side) == "await")
                             and was.get(side) != "await" for side in ("a", "b"))
            observed = (isinstance(event, str) and event in TRADE_EVENTS
                        or event in ("hello", "tick", "safe") and bool(phases & {"applying", "uncertain", "conflict"})
                        or into_await)
            if observed:
                outcome.update(pending_trade_before=before, pending_trade=after,
                               trade_problem=copy.deepcopy(self.state.trade_problem()),
                               trade_last=copy.deepcopy(self.state.trade_last))
                outcome.update({key: value for key, value in context.items() if key != "state"})
                record(player, original_message, outcome)

        if audit is not None:
            active_dispatches.append(context)
        try:
            try:
                commands = original_dispatch(self, player, msg)
            except Exception as exc:
                after_dispatch({"dispatch": "raised", "exception": type(exc).__name__})
                raise
            # Returned does not mean accepted: ignored/no-session messages return too.
            after_dispatch({"dispatch": "returned", "commands": commands})
            return commands
        finally:
            if audit is not None:
                active_dispatches.pop()

    def pending_trade(state):
        pending = state.pending_trade
        # Freeze verdicts before dispatch mutates them; never serialize LinkEntry/blobs.
        fields = ("token", "phase", "a_key", "b_key", "verdict", "problem")
        return copy.deepcopy({key: pending[key] for key in fields if key in pending}) if pending is not None else None

    def decide(self, player, msg):
        problem = _hello_problem(doc, player, msg)
        if problem:
            return {"state": "rejected", "reason": f"{ATTRIBUTION}: {problem}"}
        verdict = dict(original_decide(self, player, msg))
        verdict["reason"] = f"{ATTRIBUTION}: {verdict.get('reason', '')}"
        return verdict

    class Reader:
        # Admission normally runs after handle_client has changed adapter/panel caches.
        # Filter before that boundary, and bind each socket to one exact-manifest player.
        def __init__(self, srv, reader, writer):
            self.srv, self.reader, self.writer = srv, reader, writer
            self.player, self.hello_seen = None, False

        def __getattr__(self, name):
            return getattr(self.reader, name)

        async def readuntil(self, separator=b"\n"):
            while True:
                raw = await self.reader.readuntil(separator)
                try:
                    msg = json.loads(raw)
                except (ValueError, UnicodeError):
                    return raw  # Original malformed-wire handling, without authenticating it.
                if not isinstance(msg, dict):
                    self.hello_seen = False
                    await self.srv._respond(self.writer, [{"cmd": "noop"}])
                    continue
                player = msg.get("player")
                problem = None
                if self.player is not None and player != self.player:
                    problem = "socket player changed"
                elif msg.get("event") == "hello":
                    problem = _hello_problem(doc, player, msg)
                    if problem is None:
                        self.player, self.hello_seen = player, True
                        return raw
                elif (not self.hello_seen or player != self.player or not self.srv.is_admitted(player)
                      or self.srv.state.identity_error.get(player) or player in self.srv._rom_type_rejected):
                    problem = "socket has no accepted manifest hello"
                if problem is None:
                    return raw
                self.hello_seen = False
                if (msg.get("event") == "hello" and isinstance(player, str) and player in doc["players"]
                        and (self.player is None or player == self.player)):
                    self.srv.admission[player] = {"state": "rejected", "reason": f"{ATTRIBUTION}: {problem}"}
                server_module.log.warning("%s: rejected %r: %s", ATTRIBUTION, player, problem)
                await self.srv._respond(self.writer, [{"cmd": "noop"}])

    async def handle(self, reader, writer):
        return await original_handle(self, Reader(self, reader, writer), writer)

    decide._gen2_trade_lane = True
    cls._decide_admission, cls.handle_client, cls._dispatch = decide, handle, dispatch
    state_cls._tick_pending_trade = watchdog

    def restore():
        if cls._decide_admission is decide:
            cls._decide_admission = original_decide
        if cls.handle_client is handle:
            cls.handle_client = original_handle
        if cls._dispatch is dispatch:
            cls._dispatch = original_dispatch
        if state_cls._tick_pending_trade is watchdog:
            state_cls._tick_pending_trade = original_watchdog
        if audit is not None:
            audit.close()
    return restore


def server_arguments(argv):
    """The production main's CLI names, without running a second copy of its module."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=54321)
    parser.add_argument("--http-port", type=int, default=8080)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--run-name", default="")
    for flag, dest in (("reset", "reset"), ("species-clause", "species_lock"), ("gender-clause", "gender_lock"),
                       ("type-clause", "type_lock"), ("explode-mode", "explode_mode"), ("rival-team-swap", "rival_team_swap"),
                       ("overworld-presence", "overworld_presence"), ("native-messages", "native_messages"),
                       ("native-sounds", "native_sounds"), ("verbose", "verbose")):
        parser.add_argument("--" + flag, action="store_true", dest=dest)
    parser.add_argument("--no-battle-calc", action="store_false", dest="battle_calc")
    parser.add_argument("--no-pc-trade-npc", action="store_false", dest="pc_trade_npc")
    parser.add_argument("--manager-port", type=int, default=0)
    return vars(parser.parse_args(argv))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    _need(len(argv) >= 3 and argv[0] == "--manifest" and argv[2] == "--", "expected --manifest PATH -- server arguments")
    doc = validate_manifest(argv[1])
    args = server_arguments(argv[3:])
    _need(args["run_id"] in (None, doc["run_id"]), "server run_id differs from manifest")
    args["run_id"] = doc["run_id"]
    from server import server as server_module

    data_dir = Path(args["data_dir"])
    data_dir.mkdir(parents=True, exist_ok=True)
    restore = install_server_gate(server_module, doc, audit_path=data_dir / "trade_lane_events.jsonl")
    print(f"{ATTRIBUTION} run={doc['run_id']} scenario={doc['scenario']}", flush=True)
    try:
        asyncio.run(server_module.main(**args))
    finally:
        restore()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
