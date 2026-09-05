"""Encode untrusted display strings in generated Lua source."""

import re


def lua_comment(value: str) -> str:
    """Keep comment text on one printable line."""
    return re.sub(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]", " ", value)


def lua_string(value: str) -> str:
    """Return one quoted UTF-8 Lua string, including hostile control bytes."""
    escaped = []
    for byte in value.encode("utf-8"):
        if byte in (34, 92):
            escaped.append("\\" + chr(byte))
        elif 32 <= byte < 127:
            escaped.append(chr(byte))
        else:
            escaped.append(f"\\{byte:03d}")
    return '"' + "".join(escaped) + '"'
