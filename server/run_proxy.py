"""Explicit, same-origin run routing. Private execution APIs are never proxied."""

import asyncio
import gzip
import html
import re
import zlib
from html.parser import HTMLParser
from urllib.parse import quote, unquote, urlsplit

import aiohttp
from aiohttp import web
from multidict import CIMultiDict
from yarl import URL

# This is deliberately independent of the run router: adding a server endpoint
# does not make it public through the manager. Review new entries explicitly.
GET_PATHS = frozenset((
    "/", "/api/status", "/api/ui-state", "/api/events", "/api/calc/mons", "/memorial", "/debug",
    "/broadcast", "/tools",
    "/twitch", "/obs", "/calc", "/calc/", "/stream", "/stream/",
    "/api/bot/status", "/api/debug/backups", "/api/debug/manual_link_data", "/api/debug/raw_state",
    "/api/obs/status", "/api/obs/areas", "/api/obs/scenes/a", "/api/obs/scenes/b",
    "/launcher/a", "/launcher/b",
))
POST_PATHS = frozenset((
    "/api/attempts", "/api/reset", "/api/inject_link", "/api/inject_link_by_slot",
    *("/api/debug/" + name for name in ("clear_pending", "inject_event", "queue_command", "revive",
        "rollback", "set_area_state", "set_pokeballs", "unlink")),
    *("/api/bot/" + name for name in ("config", "disable", "enable", "preview", "reload")),
    *("/api/obs/" + name for name in ("config", "connect", "disconnect", "test", "triggers")),
))
OVERLAYS = frozenset(("area-encounter", "areas", "attempts", "badges-a", "badges-b", "boxed-links",
    "deaths", "enc-table-a", "enc-table-b", "encounters", "enemy-focus-a", "enemy-focus-b",
    "enemy-trainer-a", "enemy-trainer-b", "events", "focus-a", "focus-b", "linked-party", "links",
    "party-a", "party-b", "stream-memorial", "ticker"))
HOP_HEADERS = frozenset(("connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
                         "te", "trailer", "transfer-encoding", "upgrade"))


def allowed(method, path):
    if "\\" in path or "\x00" in path or any(part in (".", "..") for part in path.split("/")):
        return False
    if method == "POST":
        return path in POST_PATHS
    if method not in ("GET", "HEAD"):
        return False
    if path in GET_PATHS:
        return True
    if path.startswith(("/calc/", "/static/")):
        return True
    parts = path.strip("/").split("/")
    return (len(parts) in (2, 3) and parts[0] == "stream" and parts[1] in OVERLAYS
            and (len(parts) == 2 or parts[2] == "fragment"))


def run_base(run_id):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", run_id):
        raise web.HTTPBadRequest(text="Invalid run identifier")
    return "/runs/" + run_id


def upstream(run):
    port = run.get("http_port")
    if type(port) is not int or not 1 <= port <= 65535:
        raise web.HTTPServiceUnavailable(text="Run HTTP address is unavailable")
    return f"http://127.0.0.1:{port}"


def prefix_url(value, base):
    if not value or not value.startswith("/") or value.startswith("//"):
        return value
    path = urlsplit(value).path
    if path.startswith("/static/"):
        return value  # shared versioned application assets
    if allowed("GET", path) or allowed("POST", path):
        return base + value
    return value


class _PrefixHTML(HTMLParser):
    """Rewrite URL attributes only; never edit script, JSON or text contents."""
    ATTRS = frozenset(("href", "src", "action", "formaction", "hx-get", "hx-post", "hx-put", "hx-delete"))

    def __init__(self, base):
        super().__init__(convert_charrefs=False)
        self.base, self.parts = base, []

    def handle_starttag(self, tag, attrs):
        self._tag(tag, attrs, False)

    def handle_startendtag(self, tag, attrs):
        self._tag(tag, attrs, True)

    def _tag(self, tag, attrs, closed):
        # Retain original markup byte-for-byte unless a URL actually changes.
        changed = [(key, prefix_url(value, self.base) if key in self.ATTRS else value) for key, value in attrs]
        if changed == attrs:
            self.parts.append(self.get_starttag_text())
            return
        self.parts.append("<" + tag + "".join(" " + key + ("" if value is None else '="' + html.escape(value, quote=True) + '"')
                                              for key, value in changed) + ("/>" if closed else ">"))

    def handle_endtag(self, tag):
        self.parts.append("</" + tag + ">")

    def handle_data(self, data):
        self.parts.append(data)

    def handle_entityref(self, name):
        self.parts.append("&" + name + ";")

    def handle_charref(self, name):
        self.parts.append("&#" + name + ";")

    def handle_comment(self, data):
        self.parts.append("<!--" + data + "-->")

    def handle_decl(self, decl):
        self.parts.append("<!" + decl + ">")


def prefix_html(value, base):
    parser = _PrefixHTML(base)
    parser.feed(value)
    parser.close()
    return "".join(parser.parts)


def end_to_end_headers(headers):
    exclude = HOP_HEADERS | {name.strip().lower() for name in headers.get("Connection", "").split(",")}
    return CIMultiDict((key, value) for key, value in headers.items() if key.lower() not in exclude)


async def relay(request, run, path, *, base=""):
    if not allowed(request.method, path) or unquote(path) != path:
        raise web.HTTPNotFound()
    raw_query = request.raw_path.partition("?")[2]
    target = URL(upstream(run) + quote(path, safe="/!$&'()*+,-.:;=@_~") + ("?" + raw_query if raw_query else ""), encoded=True)
    headers = end_to_end_headers(request.headers)
    # Browser Host and Origin stay paired for upstream CSRF checks. A browser
    # cannot choose an upstream host, port, private path, or internal header.
    for name in list(headers):
        if name.lower().startswith(("x-slink-", "x-forwarded-")):
            headers.popall(name, None)
    headers["Accept-Encoding"] = "identity"
    if base:
        headers["X-SLink-Target-Run"] = run["run_id"]
    timeout = aiohttp.ClientTimeout(total=None if path == "/api/events" else 30, sock_connect=3,
                                     sock_read=None if path == "/api/events" else 30)
    response = None
    try:
        async with request.app["proxy_session"].request(
            request.method, target, headers=headers, data=request.content if request.can_read_body else None,
            allow_redirects=False, auto_decompress=False, timeout=timeout,
        ) as remote:
            if base and remote.headers.get("X-SLink-Run-Id") != run["run_id"]:
                raise ValueError("Run response identity does not match")
            outgoing = end_to_end_headers(remote.headers)
            outgoing["X-SLink-Run-Id"] = run["run_id"]
            if base and "Location" in outgoing:
                outgoing["Location"] = prefix_url(outgoing["Location"], base)
            if base and remote.content_type == "text/html" and request.method != "HEAD" and remote.status not in (204, 304):
                body = await remote.read()
                encoding = outgoing.get("Content-Encoding", "identity")
                if encoding == "gzip":
                    body = gzip.decompress(body)
                elif encoding == "deflate":
                    body = zlib.decompress(body)
                elif encoding != "identity":
                    raise ValueError("unsupported upstream HTML encoding")
                body = prefix_html(body.decode(remote.charset or "utf-8"), base).encode("utf-8")
                # The rewrite is deterministic within this immutable run URL,
                # so the upstream validator remains valid for revalidation.
                for name in ("Content-Encoding", "Content-Length"):
                    outgoing.popall(name, None)
                outgoing["Content-Type"] = "text/html; charset=utf-8"
                return web.Response(body=body, headers=outgoing, status=remote.status)
            if base and remote.content_type == "text/html" and request.method == "HEAD":
                outgoing.popall("Content-Length", None)
            response = web.StreamResponse(status=remote.status, headers=outgoing)
            await response.prepare(request)
            async for chunk in remote.content.iter_any():
                await response.write(chunk)
            await response.write_eof()
            return response
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
        if response is not None and response.prepared:
            response.force_close()
            return response
        raise web.HTTPBadGateway(text="This run is unavailable. Its selected address has not changed.") from error
    except ConnectionResetError:
        if response is not None:
            response.force_close()
            return response
        raise
