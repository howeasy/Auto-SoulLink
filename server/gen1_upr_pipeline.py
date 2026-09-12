"""Produce checked Gen1 final artifacts without granting runtime admission."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path

from patch.tools.make_ups import ups_apply,ups_create
from server.gen1_companion_patch import apply_to_candidate
from server.gen1_upr_policy import validate_file,verify_effective
from server.gen1_upr_scan import LAYOUT,LOCK,TITLES
from server.json_files import atomic_write_json
from server.protocol import digest
from server.upr_runner import UprRunError,run_pair_pinned


def _write_new(path,data):
    with path.open("xb") as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())
    if path.read_bytes()!=data:raise UprRunError("final artifact file readback differs")


def prepare_pair(jar,settings,sources,directory,*,seeds,java="java",custom_names=None):
    """Complete generation/scan/patch/readback; commit one manifest last.

    Only the future run owner can adopt this evidence into a runtime contract.
    A prepared directory is never silently replaced or treated as a resumed job.
    """
    validate_file(settings)
    if not isinstance(sources,dict) or set(sources)!={"a","b"}:
        raise UprRunError("exact a/b clean source paths required")
    directory=Path(directory).resolve()
    if directory.exists():raise UprRunError("new final preparation directory required")
    originals={p:Path(path).read_bytes() for p,path in sources.items()}
    variants={}
    for player,raw in originals.items():
        sha1=hashlib.sha1(raw).hexdigest()
        variant=next((v for v,t in TITLES.items() if LOCK["clean_roms"][t]["sha1"]==sha1),None)
        if variant is None:raise UprRunError("pinned canonical clean R/B/Y source required for "+player)
        variants[player]=variant
    generated=run_pair_pinned(jar,settings,sources,directory/"generation",seeds=seeds,
        generations={"a":1,"b":1},java=java,custom_names=custom_names)
    players={}
    for player,run in generated["players"].items():
        original=originals[player];variant=variants[player]
        if run["source_sha256"]!=hashlib.sha256(original).hexdigest():raise UprRunError("source changed during preparation")
        candidate=Path(run["output"]).read_bytes()
        if hashlib.sha256(candidate).hexdigest()!=run["output_sha256"]:raise UprRunError("produced candidate changed before scan")
        from server.adapters.gen1_rom_scan import scan_pokedex_order
        dex=scan_pokedex_order(original);cfg=LAYOUT["profiles"][variant]["settings"]
        starters=[dex[original[cfg[f"StarterOffsets{i}"][0]]] for i in range(1,3 if variant=="yellow" else 4)]
        verify_effective(settings,run["effective_settings_string"],starters)
        final,report=apply_to_candidate(original,candidate,settings=settings)
        target=directory/"final"/player;target.mkdir(parents=True)
        rom=target/("SLink-"+variant.capitalize()+".gbc")
        patch=target/"companion.ups"
        encoded=ups_create(candidate,final)
        if ups_apply(candidate,encoded)!=final:raise UprRunError("generated companion UPS differs")
        _write_new(rom,final);_write_new(patch,encoded)
        report["manifest"]["output"]=rom.relative_to(directory).as_posix()
        report["manifest"]["companion"].update(ups=patch.relative_to(directory).as_posix(),ups_sha256=hashlib.sha256(encoded).hexdigest())
        report["manifest_sha256"]=digest(report["manifest"])
        report["generation"]=run
        report["preparation_root"]=str(directory)
        atomic_write_json(target/"candidate.json",report)
        players[player]={"variant":variant,"seed":run["seed"],"rom":rom.relative_to(directory).as_posix(),
            "rom_sha1":report["final_sha1"],"rom_sha256":report["final_sha256"],
            "candidate":(target/"candidate.json").relative_to(directory).as_posix(),"candidate_sha256":digest(report)}
    result={"schema":"slink-gen1-prepared-artifacts-v1","status":"prepared_requires_runtime_admission",
        "settings_sha256":generated["settings_sha256"],"custom_names_sha256":generated["custom_names"]["sha256"],
        "players":players,"runtime_ready":False}
    atomic_write_json(directory/"prepared-artifacts.json",result)
    return result
