"""Twitch chat bot for SLink Soul Link Nuzlocke tracker.

Requires twitchio>=3.0:  pip install "twitchio>=3.0"

twitchio 3.x uses Twitch EventSub (WebSocket) — NOT the old IRC protocol.
You MUST register your own Twitch Developer app and use your own Client ID.
The old IRC-based tokens (chat:read / chat:edit) no longer work.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ONE-TIME SETUP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You have two options: use your broadcaster account as the bot (simple),
or use a dedicated second Twitch account as the bot (recommended for stream).

OPTION A — Broadcaster account as bot (simpler, one account)
  The bot posts as your own channel account.
  Viewers will see messages from "YourName: No deaths yet PogChamp", etc.

OPTION B — Separate bot account (recommended)
  Create a second Twitch account (e.g. "MySLinkBot").
  The bot posts as that account.
  Viewers see "MySLinkBot: No deaths yet PogChamp".

Both options use the SAME steps below. The only difference is which
Twitch account you are logged into when generating tokens in step 2.

1. Register a Twitch Developer app (do this once, on YOUR account):
   https://dev.twitch.tv/console → Register Your Application
   - Name: anything (e.g. "MySLink Bot")
   - OAuth Redirect URL: https://twitchtokengenerator.com/  ← required for token generation
   - Category: Chat Bot
   - Client Type: Confidential
   → Copy the Client ID.  Click "New Secret" and copy the Client Secret.

2. Get tokens for the BOT account at:
   https://twitchtokengenerator.com
   - OPTION A: stay logged into your normal Twitch account
   - OPTION B: open an incognito window and log in as your bot account first
   - Select "Custom Scope Token"
   - Paste your Client ID (from step 1 — same for both options)
   - Enable these scopes:
       user:read:chat     — read messages from chat
       user:write:chat    — send messages to chat
       user:bot           — identify this account as a bot
       channel:bot        — allow the bot in the broadcaster's channel
   - Click Generate Token and authorize AS THE BOT ACCOUNT.
   → Copy the Access Token and Refresh Token.

3. Set environment variables BEFORE starting the server/manager:

   Windows cmd.exe (no spaces around =, no quotes):
     set TWITCH_ACCESS_TOKEN=bot_access_token_here        <- from twitchtokengenerator (bot account)
     set TWITCH_REFRESH_TOKEN=bot_refresh_token_here      <- from twitchtokengenerator (bot account)
     set TWITCH_CLIENT_SECRET=your_client_secret_here     <- from dev.twitch.tv/console → New Secret
     python -m server.manager

   PowerShell:
     $env:TWITCH_ACCESS_TOKEN = "bot_access_token_here"   # from twitchtokengenerator (bot account)
     $env:TWITCH_REFRESH_TOKEN = "bot_refresh_token_here" # from twitchtokengenerator (bot account)
     $env:TWITCH_CLIENT_SECRET = "your_client_secret_here" # from dev.twitch.tv/console → New Secret
     python -m server.manager

4. On the /twitch page:
   - Channel: your broadcaster channel name (where chat commands will be read)
   - Client ID: from dev.twitch.tv/console (same app as step 1)
   - Click Save Config, then Reconnect.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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


def _format_cause(cause: str) -> str:
    """Convert raw cause strings to human-readable labels."""
    return {"battle": "KO'd in battle", "dead_zone": "dead zone", "whiteout": "wiped out"}.get(cause, cause or "fainted")


def _format_killer(killer) -> str:
    """Format a killer dict (or string) as a human-readable string."""
    if not killer:
        return ""
    if not isinstance(killer, dict):
        return str(killer)
    sp = killer.get("species_name") or f"Species #{killer.get('species', '?')}"
    lv = killer.get("level", "")
    lv_str = f" Lv{lv}" if lv else ""
    if killer.get("is_trainer"):
        tc = killer.get("trainer_class", "")
        tn = killer.get("trainer_name", "")
        prefix = f"{tc} {tn}".strip() or "Trainer"
        return f"{prefix}'s {sp}{lv_str}"
    return f"wild {sp}{lv_str}"


def _get_runs_dir(data_dir: str) -> str:
    """Return the directory that contains run subdirs and registry.json.

    When run standalone: data_dir is 'data/', runs live at 'data/runs/'.
    When run via manager: data_dir is 'data/runs/<run_id>/', runs live at 'data/runs/'.
    """
    # Standalone: data_dir/runs/registry.json exists
    candidate = os.path.join(data_dir, "runs")
    if os.path.exists(os.path.join(candidate, "registry.json")) or os.path.isdir(candidate):
        return candidate
    # Manager mode: data_dir is itself a run dir inside the runs directory
    parent = os.path.dirname(data_dir.rstrip("/\\"))
    if os.path.isdir(parent):
        return parent
    return candidate


def _run_display_name(run: dict) -> str:
    """Return a human-readable run name from a registry entry."""
    return run.get("name") or run.get("run_name") or run.get("run_id") or "?"


def _load_run_links(runs_dir: str, run_id: str) -> list[dict]:
    """Load links list from a run's links.json. Returns [] on error."""
    path = os.path.join(runs_dir, run_id, "links.json")
    try:
        with open(path) as f:
            return json.load(f).get("links", [])
    except Exception:
        return []


def _load_all_runs(data_dir: str) -> list[dict]:
    """Load run registry, with a directory scan fallback."""
    runs_dir = _get_runs_dir(data_dir)
    reg_path = os.path.join(runs_dir, "registry.json")
    if os.path.exists(reg_path):
        try:
            with open(reg_path) as f:
                return json.load(f).get("runs", [])
        except Exception:
            pass
    found = []
    for path in sorted(glob(os.path.join(runs_dir, "*", "links.json"))):
        run_dir = os.path.dirname(path)
        run_id = os.path.basename(run_dir)
        found.append({"run_id": run_id, "name": run_id})
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
            cause = _format_cause(k.get("cause", ""))
            killer_str = _format_killer(k.get("killer"))
            out = f"RIP {a_name} & {b_name}"
            if area:
                out += f" @ {area}"
            out += f" — {cause}"
            if killer_str:
                out += f" by {killer_str}"
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
            runs_dir = _get_runs_dir(self._data_dir)
            total_attempts = len(runs)
            total_deaths = 0
            total_shinies = 0
            best_run_name = None
            best_alive = -1
            for run in runs:
                links = await asyncio.to_thread(_load_run_links, runs_dir, run.get("run_id", ""))
                alive = sum(1 for l in links if l.get("status") == "alive")
                dead = sum(1 for l in links if l.get("status") != "alive")
                shiny_count = sum(1 for l in links if l.get("a_shiny") or l.get("b_shiny"))
                total_deaths += dead
                total_shinies += shiny_count
                if alive > best_alive:
                    best_alive = alive
                    best_run_name = _run_display_name(run)
            return (f"{total_attempts} attempts · best: {best_run_name} ({best_alive} links) · "
                    f"all-time deaths: {total_deaths} · shinies: {total_shinies}")

        if cmd == "lastrun":
            runs = await asyncio.to_thread(_load_all_runs, self._data_dir)
            current_run_id = getattr(self._srv, "_run_id", None)
            past = [r for r in runs if r.get("run_id") != current_run_id]
            if not past:
                return "No previous run found"
            last = past[-1]
            runs_dir = _get_runs_dir(self._data_dir)
            links = await asyncio.to_thread(_load_run_links, runs_dir, last.get("run_id", ""))
            alive = sum(1 for l in links if l.get("status") == "alive")
            dead = sum(1 for l in links if l.get("status") != "alive")
            name = _run_display_name(last)
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
    """Twitch chat bot for SLink. Requires twitchio>=3.0 (EventSub, not IRC)."""

    def __init__(self, srv, data_dir: str, cfg: dict,
                 access_token: str, refresh_token: str = "",
                 client_id: str = "", client_secret: str | None = None):
        super().__init__(srv, data_dir)
        self._cfg = cfg
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._client_id = client_id or cfg.get("client_id", "")
        self._client_secret = client_secret
        self._channel = cfg.get("channel", "").lstrip("#")
        self._prefix = cfg.get("prefix", "!")
        self._cooldown = int(cfg.get("command_cooldown_sec", 5))
        self._nick = cfg.get("nick", "").lower().strip()
        self._last_cmd_ts: dict[str, float] = {}
        self._tio_bot = None

    async def start(self):
        """Validate token, then build and run the twitchio 3.x bot."""
        import aiohttp as _aiohttp
        from twitchio import eventsub as _eventsub
        from twitchio.ext import commands as tio_commands

        access_token = self._access_token
        refresh_token = self._refresh_token
        client_id = self._client_id
        client_secret = self._client_secret
        channel = self._channel
        prefix = self._prefix
        helper = self

        # ── Step 1: Validate token against Twitch and resolve bot user ID ──
        async with _aiohttp.ClientSession() as _session:
            async with _session.get(
                "https://id.twitch.tv/oauth2/validate",
                headers={"Authorization": f"OAuth {access_token}"},
            ) as _resp:
                if _resp.status != 200:
                    body = await _resp.text()
                    raise RuntimeError(
                        f"Token rejected by Twitch ({_resp.status}): {body.strip()}. "
                        "Ensure scopes user:read:chat user:write:chat user:bot channel:bot are granted."
                    )
                _data = await _resp.json()

        bot_user_id = str(_data.get("user_id", ""))
        bot_login = _data.get("login", self._nick or "?")
        scopes = set(_data.get("scopes", []))
        log.info(f"Twitch token valid for {bot_login} (id={bot_user_id}), scopes={scopes}")

        needed = {"user:read:chat", "user:write:chat"}
        missing = needed - scopes
        if missing:
            log.warning(f"Twitch bot: token missing recommended scopes: {missing}")

        if not bot_user_id:
            raise RuntimeError("Token validation returned no user_id — is the token valid?")

        # ── Step 2: Commands component ──────────────────────────────────────
        class _SLinkCommands(tio_commands.Component):
            def _check_cooldown(self_comp) -> bool:
                now = time.monotonic()
                last = helper._last_cmd_ts.get(channel, 0)
                if now - last < helper._cooldown:
                    return False
                helper._last_cmd_ts[channel] = now
                return True

            async def _reply(self_comp, ctx: tio_commands.Context, cmd: str, arg: str = ""):
                def _log(text: str):
                    entry = {"ts": datetime.utcnow().isoformat(), "text": text}
                    helper._srv._bot_activity.append(entry)
                    if len(helper._srv._bot_activity) > 50:
                        helper._srv._bot_activity = helper._srv._bot_activity[-50:]

                if not self_comp._check_cooldown():
                    _log(f"⏱ cooldown: !{cmd} ignored")
                    return
                reply = await helper.build_reply(cmd, arg)
                if not reply:
                    _log(f"dbg: empty reply for !{cmd}")
                    return
                try:
                    # Use token_for=bot_user_id so the user access token is used
                    # (not the app token, which requires additional broadcaster permissions)
                    await ctx.channel.send_message(
                        sender=bot_user_id,
                        message=reply,
                        token_for=bot_user_id,
                    )
                    _log(f"[#{channel}] {reply}")
                except Exception as exc:
                    err = f"{type(exc).__name__}: {exc}"
                    log.error(f"Twitch send_message failed for !{cmd}: {err}")
                    helper._srv._bot_last_error = f"Send failed: {err}"
                    _log(f"⚠ send failed !{cmd}: {err}")

            @tio_commands.command()
            async def soullink(self_comp, ctx: tio_commands.Context):
                await self_comp._reply(ctx, "soullink")

            @tio_commands.command()
            async def clauses(self_comp, ctx: tio_commands.Context):
                await self_comp._reply(ctx, "clauses")

            @tio_commands.command()
            async def rip(self_comp, ctx: tio_commands.Context):
                await self_comp._reply(ctx, "rip")

            @tio_commands.command()
            async def runstats(self_comp, ctx: tio_commands.Context):
                await self_comp._reply(ctx, "runstats")

            @tio_commands.command()
            async def alltime(self_comp, ctx: tio_commands.Context):
                await self_comp._reply(ctx, "alltime")

            @tio_commands.command()
            async def lastrun(self_comp, ctx: tio_commands.Context):
                await self_comp._reply(ctx, "lastrun")

            @tio_commands.command()
            async def attempts(self_comp, ctx: tio_commands.Context):
                await self_comp._reply(ctx, "attempts")

            @tio_commands.command()
            async def partner(self_comp, ctx: tio_commands.Context, *, name: str = ""):
                await self_comp._reply(ctx, "partner", name)

            @tio_commands.command()
            async def area(self_comp, ctx: tio_commands.Context, *, name: str = ""):
                await self_comp._reply(ctx, "area", name)

        # ── Step 3: Bot ─────────────────────────────────────────────────────
        class _TioBot(tio_commands.Bot):
            def __init__(self_bot):
                super().__init__(
                    client_id=client_id,
                    client_secret=client_secret,
                    bot_id=bot_user_id,
                    prefix=prefix,
                )

            async def setup_hook(self_bot):
                await self_bot.add_token(access_token, refresh_token)
                broadcaster_users = await self_bot.fetch_users(logins=[channel])
                if not broadcaster_users:
                    raise ValueError(f"Twitch channel '{channel}' not found")
                broadcaster_id = str(broadcaster_users[0].id)
                sub = _eventsub.ChatMessageSubscription(
                    broadcaster_user_id=broadcaster_id,
                    user_id=bot_user_id,
                )
                await self_bot.subscribe_websocket(sub)
                await self_bot.add_component(_SLinkCommands())

            async def event_ready(self_bot):
                log.info(f"Twitch bot ready as {bot_login} in #{channel}")
                entry = {"ts": datetime.utcnow().isoformat(),
                         "text": f"✓ Connected as {bot_login} in #{channel}"}
                helper._srv._bot_activity.append(entry)
                if len(helper._srv._bot_activity) > 50:
                    helper._srv._bot_activity = helper._srv._bot_activity[-50:]
                helper._srv._bot_last_error = ""

            async def event_message(self_bot, payload):
                # Log incoming commands to activity for diagnostics
                txt = getattr(payload, "text", "") or ""
                if txt.startswith(prefix):
                    entry = {"ts": datetime.utcnow().isoformat(),
                             "text": f"← {txt[:120]}"}
                    helper._srv._bot_activity.append(entry)
                    if len(helper._srv._bot_activity) > 50:
                        helper._srv._bot_activity = helper._srv._bot_activity[-50:]
                # Skip shared-chat messages from other channels
                if getattr(payload, "source_broadcaster", None) is not None:
                    return
                # Process commands for all messages, including from the bot's own account.
                # twitchio's default event_message skips self-messages to prevent loops,
                # but our bot responses are plain text (never start with !) so no loop risk.
                # This also handles the common case where bot and broadcaster are the same account.
                await self_bot.process_commands(payload)

            async def event_command_error(self_bot, payload):
                err = str(payload.exception)
                log.error(f"Twitch command error: {err}", exc_info=payload.exception)
                helper._srv._bot_last_error = f"Command error: {err}"
                entry = {"ts": datetime.utcnow().isoformat(), "text": f"⚠ cmd error: {err}"}
                helper._srv._bot_activity.append(entry)
                if len(helper._srv._bot_activity) > 50:
                    helper._srv._bot_activity = helper._srv._bot_activity[-50:]

            async def event_error(self_bot, payload):
                err = str(payload.error)
                log.error(f"Twitch bot error: {err}")
                helper._srv._bot_last_error = f"Error: {err}"
                entry = {"ts": datetime.utcnow().isoformat(), "text": f"⚠ {err}"}
                helper._srv._bot_activity.append(entry)
                if len(helper._srv._bot_activity) > 50:
                    helper._srv._bot_activity = helper._srv._bot_activity[-50:]

        async with _TioBot() as bot_instance:
            helper._tio_bot = bot_instance
            await bot_instance.start()
