"""Published vanilla ABI2 artifacts shared by pack generators and provisioning."""
import copy
import hashlib
import json
from pathlib import Path

from patch.tools import rom_identity
from patch.tools.make_ups import ups_apply

ROOT=Path(__file__).resolve().parents[1]

# Version-masked identity (owner ruling 2026-10-02, patch/tools/rom_identity.py). A record keeps the EXACT hash of the published
# build and its canonical sibling (the same bytes with the version field zeroed). The exact hashes of earlier builds that were
# proven canonical-equal to it (a version stamp only) are listed beside it; a receipt or pin carrying one of those is the same
# qualified build. Absent list = none.
EQUIVALENT_FIELDS={"rom_sha1":"equivalent_sha1s","payload_sha256":"equivalent_payload_sha256"}


def equivalents(record, field):
    """The earlier exact hashes a record vouches for under `field` ('rom_sha1' or 'payload_sha256')."""
    return tuple(record.get(EQUIVALENT_FIELDS[field]) or ())


def accepts(record, field, value):
    """Is `value` the record's published exact `field`, or an earlier build it lists as canonical-equal? Nothing else is accepted."""
    return value==record[field] or value in equivalents(record, field)


def ups_region(patch, offset, size, base_byte=0xFF):
    """Bytes [offset, offset+size) of the patched ROM, rebuilt from a UPS alone. Only valid for a region that is `base_byte`
    throughout in the base ROM (the builder proves its injection region is free), because a UPS stores XOR deltas."""
    from patch.tools.make_ups import _ups_decode
    pos = _ups_decode(patch, 4)[1]       # source size
    pos = _ups_decode(patch, pos)[1]     # target size
    region = bytearray([base_byte]) * size
    address = 0
    while pos < len(patch) - 12:
        delta, pos = _ups_decode(patch, pos)
        address += delta
        while pos < len(patch) - 12:
            value = patch[pos]
            pos += 1
            if offset <= address < offset + size:
                region[address - offset] ^= value
            address += 1
            if value == 0:
                break
    return bytes(region)


def canonical_problems(row, rom=None, payload=None):
    """Why a record's version-masked identity is not what its own bytes say (empty = consistent). `rom` / `payload` are the exact
    bytes of the published build, when the caller has them."""
    problems = []
    slot, pslot = row.get("version_slot"), row.get("payload_version_slot")
    if not slot or not pslot:
        return ["no version slot recorded"]
    if slot["length"] != rom_identity.FIELD or pslot["length"] != rom_identity.FIELD:
        problems.append("version slot is not the fixed field width")
    spans = row.get("protected_spans") or [{}]
    if "offset" in spans[0] and slot["offset"] != spans[0]["offset"] + pslot["offset"]:
        problems.append("ROM version slot is not the payload slot moved to its ROM address")
    if rom is not None and rom_identity.canonical_sha1(rom, [slot]) != row.get("canonical_sha1"):
        problems.append("canonical_sha1 differs from the published ROM with the field masked")
    if payload is not None and rom_identity.canonical_sha256(payload, [pslot]) != row.get("canonical_payload_sha256"):
        problems.append("canonical_payload_sha256 differs from the payload with the field masked")
    for field, own, width in (("rom_sha1", "equivalent_sha1s", 40), ("payload_sha256", "equivalent_payload_sha256", 64)):
        listed = row.get(own) or []
        if any(not isinstance(h, str) or len(h) != width or set(h) - set("0123456789abcdef") for h in listed):
            problems.append(f"{own} holds something that is not a lowercase hex digest")
        if row.get(field) in listed:
            problems.append(f"{own} lists the published build itself")
    return problems


def published(title, clean, root=ROOT):
    path=Path(root)/"patch/dist/gen3_companions.json"
    if not path.exists():return None
    row=json.loads(path.read_text())["titles"].get(title)
    if not row:return None
    if row.get("production") is not True or row.get("abi")!=2:
        raise ValueError("unpublished native companion manifest")
    if hashlib.sha1(clean).hexdigest()!=row["base_sha1"]:
        raise ValueError("companion base hash differs")
    patch=(path.parent/row["patch"]).read_bytes()
    if hashlib.sha256(patch).hexdigest()!=row["ups_sha256"]:
        raise ValueError("published UPS hash differs")
    rom=ups_apply(clean,patch)
    if hashlib.sha1(rom).hexdigest()!=row["rom_sha1"] or hashlib.sha256(rom).hexdigest()!=row["rom_sha256"]:
        raise ValueError("published companion output differs")
    problems=canonical_problems(row,rom=rom)
    if problems:
        raise ValueError("published companion canonical identity differs: "+"; ".join(problems))
    return rom,row


def artifact(clean_artifact, rom, row):
    out=copy.deepcopy(clean_artifact)
    out.update(production=True,rom_sha1=row["rom_sha1"],rom_md5=row["rom_md5"])
    if row.get("equivalent_sha1s"):
        # earlier stamps of the same canonical build: still on players' cartridges, admitted as this artifact
        out["equivalent_sha1s"]=list(row["equivalent_sha1s"])
    frame=out["sites"]["frame_control"]
    # FR/LG replace CallCallbacks completely, so the old +10 help-call site is
    # unreachable. Observe its real entry (the detour), as Emerald already does.
    entry=frame["function"]["address"]
    frame.update(address=entry,rom_offset=entry-0x08000000,capture_offset=0)
    frame["function"].update(anchor_offset=0,capture_offset=0)
    frame["capture_contract"]="Published native CallCallbacks entry, before the companion services and original callbacks; frame control, not a gameplay event."
    for site in out["sites"].values():
        for item in (site,site.get("context")):
            if item:
                offset=item["rom_offset"];length=len(bytes.fromhex(item["expected_hex"]))
                item["expected_hex"]=rom[offset:offset+length].hex().upper()
    return out


def overlay_randomized(title, clean, randomized):
    result=published(title,clean)
    if result is None:raise ValueError("native companion not published for this title")
    patched,row=result
    if len(randomized)!=len(clean):raise ValueError("randomizer changed companion ROM geometry")
    output=bytearray(randomized)
    for span in row["protected_spans"]:
        start,end=span["offset"],span["offset"]+span["size"]
        if randomized[start:end]!=clean[start:end]:
            raise ValueError(f"randomizer overlaps native companion reservation at {start:#x}")
        output[start:end]=patched[start:end]
    return bytes(output)
