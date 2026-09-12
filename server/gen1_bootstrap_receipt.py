"""Read-only normal New Game evidence; never releases a recovery hold itself."""

import hashlib
import json
from pathlib import Path

from server.gen1_full_save import image, layout
from server.gen1_initial_observation import display_name
from server.gen1_native_trade_receipts import _bytes
from server.gen1_party_codec import PartyCodec, PartyCodecError
from server.protocol import digest
from server.protocol_journal import JournalError
from server.verified_content_cache import verified_content_cache

DATA = json.loads(
    (Path(__file__).resolve().parents[1] / "data/games/gen1_rby/bootstrap_sites.json").read_text()
)
SCHEMA = "rby-bootstrap-receipt-v1"


def validation_dependencies():
    """Read current codec bytes and source layouts before every cached proof."""
    from server import gen1_party_codec

    return {'bootstrap': DATA, 'layouts': {variant: layout(variant) for variant in ('red', 'blue', 'yellow')},
            'codec_sha256': hashlib.sha256(gen1_party_codec.DATA_PATH.read_bytes()).hexdigest()}


def projection(source):
    """Project only initialization-owned fields; map-entry sprites may change."""
    image(source)
    variant = source["variant"]
    regions = layout(variant)["regions"]
    fields = {name: _bytes(source["fields"][name], row["length"]) for name, row in regions.items()}
    result = {}
    for name, row in DATA["titles"][variant]["fields"].items():
        owners = [
            (key, region)
            for key, region in regions.items()
            if region["address"] <= row["address"]
            and row["address"] + row["length"] <= region["address"] + region["length"]
        ]
        if len(owners) != 1:
            raise JournalError("bootstrap field lacks one source-defined owner")
        key, region = owners[0]
        offset = row["address"] - region["address"]
        result[name] = fields[key][offset : offset + row["length"]].hex().upper()
    return result


@verified_content_cache(dependencies=validation_dependencies)
def validate(
    receipt, *, variant, identity, context_generation, physical_instance, final_sha1, source, frame
):
    """Require an observed normal entry/return and the same still-empty enrollment.

    This proves no starter has been silently adopted. SRAM is intentionally not
    inferred from empty WRAM: an initial save and its file receipt remain separate.
    """
    if not isinstance(variant, str) or variant not in DATA["titles"]:
        raise JournalError("RBY bootstrap variant required")
    required = {
        "schema",
        "source_sha256",
        "variant",
        "context_generation",
        "physical_instance",
        "final_sha1",
        "begin",
        "end",
    }
    if not isinstance(receipt, dict) or set(receipt) != required:
        raise JournalError("complete bootstrap receipt required")
    if (
        receipt["schema"] != SCHEMA
        or receipt["source_sha256"] != DATA["sha256"]
        or receipt["variant"] != variant
        or receipt["context_generation"] != context_generation
        or receipt["physical_instance"] != physical_instance
        or receipt["final_sha1"] != final_sha1
    ):
        raise JournalError("bootstrap source or physical context differs")
    if type(frame) is not int or not 0 <= frame <= 2**53 - 1:
        raise JournalError("bootstrap enrollment frame required")
    for kind in ("begin", "end"):
        event = receipt[kind]
        keys = {"frame", "pc", "bank", "sp"} | ({"point"} if kind == "end" else set())
        if not isinstance(event, dict) or set(event) != keys:
            raise JournalError("complete bootstrap execution witness required")
        site = DATA["titles"][variant]["sites"][kind]
        for key, low, high in [
            ("frame", 0, frame),
            ("pc", 0, 65535),
            ("bank", 0, 255),
            ("sp", 0, 65535),
        ]:
            if type(event[key]) is not int or not low <= event[key] <= high:
                raise JournalError("invalid bootstrap CPU/frame witness")
        if event["pc"] != site["address"] or event["bank"] != site["bank"]:
            raise JournalError("bootstrap execution site differs")
    begin, end = receipt["begin"], receipt["end"]
    if begin["sp"] != end["sp"] or begin["frame"] >= end["frame"]:
        raise JournalError("bootstrap entry/return stack or frame differs")
    if not isinstance(source, dict) or source.get("variant") != variant:
        raise JournalError("bootstrap enrollment cartridge differs")
    actual = projection(source)
    if end["point"] != actual:
        raise JournalError("bootstrap inventory or identity changed before enrollment")
    for name in ("party", "box"):
        if not actual[name].startswith("00FF"):
            raise JournalError("bootstrap requires empty party and current box")
    if actual["owned"] != "00" * 19 or actual["seen"] != "00" * 19 or actual["current_box"] != "00":
        raise JournalError("bootstrap contains prior monster or storage history")
    name = bytes.fromhex(actual["trainer"])
    try:
        PartyCodec(variant)._name(name, "bootstrap trainer")
    except PartyCodecError as error:
        raise JournalError(str(error)) from error
    if not display_name(name) or identity != {
        "ot_id": actual["player_id"],
        "trainer_name": display_name(name),
    }:
        raise JournalError("bootstrap trainer differs from admission")
    return {
        "schema": "rby-bootstrap-proof-v1",
        "receipt_digest": digest(receipt),
        "enrollment_source_digest": digest(source),
        "frame": frame,
        "entry_frame": begin["frame"],
        "return_frame": end["frame"],
    }
