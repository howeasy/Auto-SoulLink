"""Pure structural application of installed companion bytes to audited RBY input."""
import copy
import hashlib

from server.gen1_cartridge_profiles import companion_profiles
from server.gen1_upr_scan import scan_candidate,scan_generated
from server.patch_plan import PatchSpan,apply_spans
from server.protocol import digest


def apply_to_candidate(original,candidate,*,settings=None):
    scan=lambda data:scan_candidate(original,data) if settings is None else scan_generated(original,data,settings)
    before=scan(candidate)
    variant=before["profile"]["variant"]
    installed=companion_profiles()[variant]
    manifest=installed["manifest"]
    spans=[PatchSpan(row["offset"],bytes.fromhex(row["before_hex"]),bytes.fromhex(row["after_hex"]),row["label"])
           for row in manifest["companion"]["spans"]]
    options={"protected":((0x100,0x150),),"bank_size":0x4000}
    canonical=apply_spans(original,spans,**options)
    if hashlib.sha256(canonical).hexdigest()!=installed["rom_sha256"]:
        raise ValueError("installed companion spans do not reproduce their canonical artifact")
    final=apply_spans(candidate,spans,**options)
    reverse=[PatchSpan(row.offset,row.after,row.before,row.label) for row in spans]
    unpatched=apply_spans(final,reverse,**options)
    if unpatched!=candidate:raise ValueError("structural patch reversal differs")
    after=scan(unpatched)
    if before!=after:raise ValueError("post-patch semantic scan differs")
    final_sha1=hashlib.sha1(final).hexdigest();final_sha256=hashlib.sha256(final).hexdigest()
    actual=copy.deepcopy(manifest)
    actual.update(base_sha1=before["candidate_sha1"],final_sha1=final_sha1,output=None)
    actual["companion"].update(schema="gen1-structural-companion-v1",
        base_sha256=before["candidate_sha256"],final_sha256=final_sha256,ups=None,ups_sha256=None)
    report={"schema":"slink-gen1-structural-candidate-v1",
        "status":"final_artifact_requires_boot_and_runtime_qualification","variant":variant,
        "source_clean_sha1":hashlib.sha1(original).hexdigest(),"input_sha1":before["candidate_sha1"],
        "input_sha256":before["candidate_sha256"],"final_sha1":final_sha1,"final_sha256":final_sha256,
        "size":len(final),"capabilities":copy.deepcopy(installed["capabilities"]),
        "semantic_profile":before["profile"],"semantic_profile_sha256":digest(before["profile"]),
        "semantic_audit":before,"final_semantic_audit":after,
        "installed_companion_manifest_sha256":installed["manifest_sha256"],"manifest":actual,
        "manifest_sha256":digest(actual),"runtime_ready":False}
    return final,report
