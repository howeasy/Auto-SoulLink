"""Published vanilla ABI2 artifacts shared by pack generators and provisioning."""
import copy
import hashlib
import json
from pathlib import Path

from patch.tools.make_ups import ups_apply

ROOT=Path(__file__).resolve().parents[1]


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
    return rom,row


def artifact(clean_artifact, rom, row):
    out=copy.deepcopy(clean_artifact)
    out.update(production=True,rom_sha1=row["rom_sha1"],rom_md5=row["rom_md5"])
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
