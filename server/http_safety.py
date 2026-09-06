"""Browser request protections shared by the run server and manager.

SLink also has native HTTP callers (test tools and the calculator bridge), so
requests without browser-origin headers remain supported. Explicit browser
provenance must establish the same origin, including the port. Fetch Metadata
alone is insufficient for the documented plain-HTTP LAN setup.
"""

import ipaddress
from urllib.parse import urlsplit

from aiohttp import web

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def local_operator(request) -> bool:
    """Local file access requires both a loopback peer and a local Host."""
    try:
        peer = ipaddress.ip_address(request.remote or "")
        peer_local = peer.is_loopback or bool(getattr(peer, "ipv4_mapped", None) and peer.ipv4_mapped.is_loopback)
        parsed = urlsplit("http://" + request.host)
        host = parsed.hostname
        if parsed.username is not None or parsed.password is not None or parsed.path or parsed.query or parsed.fragment:
            return False
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            return False
        if not peer_local or not host:
            return False
        if host.rstrip(".").lower() == "localhost":
            return True
        address = ipaddress.ip_address(host)
        return address.is_loopback or bool(getattr(address, "ipv4_mapped", None) and address.ipv4_mapped.is_loopback)
    except (ValueError, AttributeError):
        return False


def _origin(value: str, *, referer: bool = False) -> tuple[str, str, int] | None:
    """Parse a browser origin without accepting credentials or opaque URLs."""
    if not value or any(ord(char) <= 32 or ord(char) == 127 for char in value):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        if not referer and (parsed.path or parsed.query or parsed.fragment):
            return None
        port = parsed.port
        if port is None:
            port = 443 if parsed.scheme == "https" else 80
        if not 1 <= port <= 65535:
            return None
        return parsed.scheme, parsed.hostname.lower(), port
    except ValueError:
        return None


def _same_origin_request(request: web.Request) -> bool:
    site = request.headers.get("Sec-Fetch-Site")
    if site is not None and site not in {"same-origin", "same-site", "none"}:
        return False

    origin = request.headers.get("Origin")
    referer = request.headers.get("Referer")
    if origin is not None or referer is not None:
        # Origin takes precedence; an opaque/malformed Origin must not be
        # rescued by an apparently safe Referer. Ignore forwarded host headers.
        source = _origin(origin) if origin is not None else _origin(referer, referer=True)
        target = _origin(f"{request.scheme}://{request.host}")
        return source is not None and target is not None and source == target

    if site == "same-origin":
        return True
    if site is not None:
        # 'same-site' includes other ports/subdomains; 'none' is not proof of
        # same-origin provenance for a mutation.
        return False
    # Preserve headerless native callers, but don't misclassify incomplete
    # browser Fetch Metadata as a native request.
    return not any(name.lower().startswith("sec-fetch-") for name in request.headers)


@web.middleware
async def csrf_protection(request: web.Request, handler):
    """Reject cross-origin browser mutations before any handler side effects."""
    if request.method not in _SAFE_METHODS and not _same_origin_request(request):
        return web.json_response(
            {"ok": False, "error": "Cross-origin requests are not allowed"},
            status=403,
            headers={"Cache-Control": "no-store"},
        )
    return await handler(request)


@web.middleware
async def theme_cache(request: web.Request, handler):
    """Revalidate themed HTML and partition caches by the theme cookie.

    The HTML route families share theme rendering, so cover them centrally.
    Leave JSON, files and already-started streams to their own cache policy.
    Preserve stricter existing cache directives and unrelated Vary tokens.
    """
    response = await handler(request)
    if not response.prepared and response.content_type == "text/html":
        cache = ", ".join(response.headers.getall("Cache-Control", []))
        if "no-cache" not in {token.strip().lower() for token in cache.split(",")}:
            response.headers["Cache-Control"] = f"{cache}, no-cache" if cache else "no-cache"
        vary = ", ".join(response.headers.getall("Vary", []))
        tokens = {token.strip().lower() for token in vary.split(",")}
        if "cookie" not in tokens and "*" not in tokens:
            response.headers["Vary"] = f"{vary}, Cookie" if vary else "Cookie"
    return response
