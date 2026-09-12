"""Complete UPR wire layout, reusable independently of generation admission."""
from __future__ import annotations

import base64
import binascii
import json
import struct
from pathlib import Path
from types import MappingProxyType

from server.upr_settings import UprSettingsError, VERSION, load, parse_settings_string

_LAYOUT = json.loads((Path(__file__).resolve().parents[1]/"data/upr_zx_4_6_1_settings.json").read_text())
FIELDS = MappingProxyType(_LAYOUT["fields"])


def decode(data):
    """Reject absent/ambiguous enum selections and nonzero reserved bits."""
    if not isinstance(data, bytes) or len(data) != 51:
        raise UprSettingsError("exact 51-byte settings block required")
    result = {}
    for name, field in FIELDS.items():
        kind = field["kind"]
        bit = lambda position: (data[position[0]] >> position[1]) & 1
        if kind == "enum":
            choices = [choice for choice, position in field["choices"].items() if bit(position)]
            if len(choices) != 1:
                raise UprSettingsError(name+" must select exactly one enum value")
            result[name] = choices[0]
        elif kind == "integer":
            result[name] = sum(bit(position) << i for i, position in enumerate(field["positions"])) + field["bias"]
        elif kind == "boolean":
            result[name] = bool(bit(field["positions"][0]))
        elif any(bit(position) for position in field["positions"]):
            raise UprSettingsError(name+" must remain zero")
    return result


def encode(values):
    names = {name for name, field in FIELDS.items() if field["kind"] != "reserved"}
    if set(values) != names:
        raise UprSettingsError("settings fields differ from the complete catalog")
    data = bytearray(51)
    for name, value in values.items():
        field = FIELDS[name]
        positions = field["positions"]
        if field["kind"] == "enum":
            if value not in field["choices"]:
                raise UprSettingsError("unknown enum selection for "+name)
            byte, bit = field["choices"][value]
            data[byte] |= 1 << bit
            continue
        if field["kind"] == "boolean":
            if type(value) is not bool:
                raise UprSettingsError(name+" must be boolean")
            raw = int(value)
        else:
            if type(value) is not int:
                raise UprSettingsError(name+" must be an integer")
            raw = value-field["bias"]
            if not 0 <= raw < 1 << len(positions):
                raise UprSettingsError(name+" is outside its encoded range")
        for index, (byte, bit) in enumerate(positions):
            data[byte] |= ((raw >> index) & 1) << bit
    return bytes(data)


def settings_file(values, *, rom_name="SLink Gen1 RC", custom_names_crc=0):
    data = encode(values)
    try:
        name = rom_name.encode("ascii")
    except (AttributeError, UnicodeError) as error:
        raise UprSettingsError("ASCII ROM name required") from error
    if len(name) > 255:
        raise UprSettingsError("ROM name exceeds its one-byte length")
    body = data+bytes([len(name)])+name
    raw = body+struct.pack(">II", binascii.crc32(body) & 0xffffffff, custom_names_crc)
    encoded = base64.b64encode(raw)
    return struct.pack(">II", VERSION, len(encoded))+encoded


def read_file(raw):
    parsed = load(raw)
    if parsed["version"] != VERSION:
        raise UprSettingsError("settings migration is prohibited")
    return decode(parsed["data"])


def read_effective(value):
    if not isinstance(value, str) or not value.startswith(str(VERSION)):
        raise UprSettingsError("effective settings version differs")
    return decode(parse_settings_string(value)["data"])
