"""Twitch chat bot for SLink Soul Link Nuzlocke tracker.

Requires twitchio>=2.0,<3.0:  pip install twitchio>=2.0,<3.0

Configuration (non-sensitive fields) lives in data/twitch_bot.json.
The OAuth token MUST be set via the TWITCH_OAUTH_TOKEN environment variable.
It is NEVER written to any file or logged.

Commands:
  !soullink  — plain-English Soul Link rules
  !clauses   — active clause rules
  !rip       — most recent death
  !runstats  — current run summary
  !alltime   — cross-run aggregate (reads data/runs/*/links.json)
  !lastrun   — previous run outcome
  !attempts  — current attempt number
  !partner <name>  — look up a mon's Soul Link partner by nickname
  !area <name>     — look up an area's link status
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from glob import glob

log = logging.getLogger(__name__)

_SOUL_LINK_RULES = (
    "Soul Link Nuzlocke: (1) First encounter per area is permanently linked with partner's first encounter. "
    "(2) If one linked mon faints, its partner also faints. "
    "(3) If either player fails to catch in an area, BOTH lose that slot (dead zone). "
    "(4) Both linked mons must be in the party together or the PC together."
)


def _area_display(area_id: str) -> str:
    if not area_id:
        return ""
    if area_id.startswith("_bonus_"):
        return "Bonus Pair"
    return area_id.replace("_", " ").title()


def _load_run_links(data_dir: str, run_id: str) -> list[dict]:
    """Load links list from a run's links.json. Returns [] on error."""
    path = os.path.join(data_dir, "runs", run_id, "links.json")
    try:
        with open(path) as f:
            return json.load(f).get("links", [])
    except Exception:
        return []


def _load_all_runs(data_dir: str) -> list[dict]:
    """Load run registry, with a directory scan fallback."""
    reg_path = os.path.join(data_dir, "runs", "registry.json")
    if os.path.exists(reg_path):
        try:
            with open(reg_path) as f:
                return json.load(f).get("runs", [])
        except Exception:
            pass
    runs_dir = os.path.join(data_dir, "runs")
    found = []
    for path in sorted(glob(os.path.join(runs_dir, "*", "links.json"))):
        run_dir = os.path.dirname(path)
        run_id = os.path.basename(run_dir)
        found.append({"run_id": run_id, "run_name": run_id})
    return found


async def build_reply_standalone(cmd: str, arg: str, srv, data_dir: str) -> str:
    """Build a command reply without a running bot instance. Used for /api/bot/preview."""
    bot = _ReplyHelper(srv, data_dir)
    return await bot.build_reply(cmd, arg)


class _ReplyHelper:
    """Pure logic helper — builds command reply strings from server state."""

    def __init__(self, srv, data_dir: str):
        self._srv = srv
        self._data_dir = data_dir

    async def build_reply(self, cmd: str, arg: str) -> str:
        try:
            d = self._srv._build_status_dict()
        except Exception:
            d = {}

        if cmd == "soullink":
            return _SOUL_LINK_RULES

        if cmd == "clauses":
            rules = d.get("rules", {})
            parts = [
                "Species " + ("✓" if rules.get("species_lock") else "✗"),
                "Gender " + ("✓" if rules.get("gender_lock") else "✗"),
                "Type " + ("✓" if rules.get("type_lock") else "✗"),
            ]
            return "Active clauses: " + " · ".join(parts)

        if cmd == "rip":
            kf = d.get("killfeed", [])
            if not kf:
                return "No deaths yet PogChamp"
            k = kf[0]
            a_name = k.get("a_nickname") or k.get("a_species_name") or "?"
            b_name = k.get("b_nickname") or k.get("b_species_name") or "?"
            area = k.get("area_display") or _area_display(k.get("area_id", ""))
            cause = k.get("cause") or "fainted"
            killer = k.get("killer", "")
            out = f"{a_name} & {b_name}"
            if area:
                out += f" @ {area}"
            out += f" — {cause}"
            if killer:
                out += f" by {killer}"
            return out

        if cmd == "runstats":
            links = d.get("links", [])
            alive = sum(1 for l in links if l.get("status") == "alive")
            dead = sum(1 for l in links if l.get("status") != "alive")
            shinies = sum(1 for l in links if l.get("a_shiny") or l.get("b_shiny"))
            bk = d.get("bonus_keys", {})
            shinies += len(bk.get("a", [])) + len(bk.get("b", []))
            attempts = d.get("attempts_count", 0)
            oldest = next((l for l in links if l.get("status") == "alive"), None)
            out = f"Attempt #{attempts} · {alive} alive · {dead} dead · {shinies} {'shiny' if shinies == 1 else 'shinies'}"
            if oldest:
                o_name = oldest.get("a_nickname") or oldest.get("a_species_name") or "?"
                o_level = oldest.get("a_level", "")
                o_area = _area_display(oldest.get("area_id", ""))
                out += f" · oldest link: {o_name}"
                if o_level:
                    out += f" Lv{o_level}"
                if o_area:
                    out += f" @ {o_area}"
            return out

        if cmd == "alltime":
            runs = await asyncio.to_thread(_load_all_runs, self._data_dir)
            if not runs:
                return "No multi-run history yet (run manager not used)"
            total_attempts = len(runs)
            total_deaths = 0
            total_shinies = 0
            best_run_name = None
            best_alive = -1
            for run in runs:
                links = await asyncio.to_thread(_load_run_links, self._data_dir, run.get("run_id", ""))
                alive = sum(1 for l in links if l.get("status") == "alive")
                dead = sum(1 for l in links if l.get("status") != "alive")
                shiny_count = sum(1 for l in links if l.get("a_shiny") or l.get("b_shiny"))
                total_deaths += dead
                total_shinies += shiny_count
                if alive > best_alive:
                    best_alive = alive
                    best_run_name = run.get("run_name") or run.get("run_id") or "?"
            return (f"{total_attempts} attempts · best: {best_run_name} ({best_alive} links) · "
                    f"all-time deaths: {total_deaths} · shinies: {total_shinies}")

        if cmd == "lastrun":
            runs = await asyncio.to_thread(_load_all_runs, self._data_dir)
            current_run_id = getattr(self._srv, "_run_id", None)
            past = [r for r in runs if r.get("run_id") != current_run_id]
            if not past:
                return "No previous run found"
            last = past[-1]
            links = await asyncio.to_thread(_load_run_links, self._data_dir, last.get("run_id", ""))
            alive = sum(1 for l in links if l.get("status") == "alive")
            dead = sum(1 for l in links if l.get("status") != "alive")
            name = last.get("run_name") or last.get("run_id") or "previous run"
            return f"{name}: {alive} alive links, {dead} dead"

        if cmd == "attempts":
            return f"Attempt #{d.get('attempts_count', 0)}"

        if cmd == "partner":
            if not arg:
                return "Usage: !partner <nickname>"
            needle = arg.lower()
            for link in d.get("links", []):
                a_name = (link.get("a_nickname") or link.get("a_species_name") or "").lower()
                b_name = (link.get("b_nickname") or link.get("b_species_name") or "").lower()
                area = link.get("area_display") or _area_display(link.get("area_id", ""))
                status = link.get("status", "alive")
                if needle == a_name:
                    partner = link.get("b_nickname") or link.get("b_species_name") or "?"
                    partner_level = link.get("b_level", "")
                    own_level = link.get("a_level", "")
                    me = (link.get("a_nickname") or link.get("a_species_name") or arg).upper()
                    return (f"{me} (A{' Lv'+str(own_level) if own_level else ''}) ↔ {partner.upper()} "
                            f"(B{' Lv'+str(partner_level) if partner_level else ''})"
                            f"{' @ '+area if area else ''} — {'alive ✓' if status == 'alive' else 'dead ✗'}")
                if needle == b_name:
                    partner = link.get("a_nickname") or link.get("a_species_name") or "?"
                    partner_level = link.get("a_level", "")
                    own_level = link.get("b_level", "")
                    me = (link.get("b_nickname") or link.get("b_species_name") or arg).upper()
                    return (f"{me} (B{' Lv'+str(own_level) if own_level else ''}) ↔ {partner.upper()} "
                            f"(A{' Lv'+str(partner_level) if partner_level else ''})"
                            f"{' @ '+area if area else ''} — {'alive ✓' if status == 'alive' else 'dead ✗'}")
            return f"No mon named '{arg}' found in linked pairs"

        if cmd == "area":
            if not arg:
                return "Usage: !area <area name>"
            needle = arg.lower().replace(" ", "_")
            area_states = d.get("area_states", {})
            links = d.get("links", [])
            match_id = None
            for area_id in area_states:
                if needle in area_id.lower():
                    match_id = area_id
                    break
            if not match_id:
                return f"Area '{arg}' not found"
            state = area_states[match_id]
            display = _area_display(match_id)
            for link in links:
                if link.get("area_id") == match_id:
                    a_name = link.get("a_nickname") or link.get("a_species_name") or "?"
                    b_name = link.get("b_nickname") or link.get("b_species_name") or "?"
                    a_level = link.get("a_level", "")
                    b_level = link.get("b_level", "")
                    status = link.get("status", "alive")
                    return (f"{display}: {state} — {a_name.upper()}"
                            f"(A{' Lv'+str(a_level) if a_level else ''}) ↔ {b_name.upper()}"
                            f"(B{' Lv'+str(b_level) if b_level else ''}) {'alive ✓' if status == 'alive' else 'dead ✗'}")
            return f"{display}: {state}"

        return f"Unknown command: !{cmd}"


class SLinkChatBot(_ReplyHelper):
    """Twitch chat bot for SLink. Requires twitchio>=2.0,<3.0."""

    def __init__(self, srv, data_dir: str, cfg: dict, token: str):
        super().__init__(srv, data_dir)
        self._cfg = cfg
        self._token = token
        self._channel = cfg.get("channel", "").lstrip("#")
        self._prefix = cfg.get("prefix", "!")
        self._cooldown = int(cfg.get("command_cooldown_sec", 5))
        self._last_cmd_ts: dict[str, float] = {}
        self._tio_bot = None

    async def start(self):
        """Construct twitchio Bot and run it."""
        from twitchio.ext import commands as tio_commands

        channel = self._channel
        prefix = self._prefix
        token = self._token
        helper = self

        class _TioBot(tio_commands.Bot):
            def __init__(self):
                super().__init__(token=token, prefix=prefix, initial_channels=[channel])

            async def event_ready(self):
                log.info(f"Twitch bot ready as {self.nick} in #{channel}")

            async def event_message(self, message):
                if message.echo:
                    return
                content = (message.content or "").strip()
                if not content.startswith(prefix):
                    return
                now = time.monotonic()
                last = helper._last_cmd_ts.get(channel, 0)
                if now - last < helper._cooldown:
                    return
                parts = content[len(prefix):].split(None, 1)
                cmd = parts[0].lower() if parts else ""
                arg = parts[1] if len(parts) > 1 else ""
                reply = await helper.build_reply(cmd, arg)
                if reply:
                    helper._last_cmd_ts[channel] = now
                    try:
                        await message.channel.send(reply)
                    except Exception as e:
                        log.warning(f"Twitch bot send error: {e}")
                        return
                    entry = {"ts": datetime.utcnow().isoformat(),
                             "text": f"[#{channel}] {reply}"}
                    helper._srv._bot_activity.append(entry)
                    if len(helper._srv._bot_activity) > 50:
                        helper._srv._bot_activity = helper._srv._bot_activity[-50:]

        self._tio_bot = _TioBot()
        await self._tio_bot.start()
