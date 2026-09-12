"""Pinned external UPR invocation and artifact provenance; no generation admission."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

from server.upr_settings import VERSION, load, parse_settings_string

ROOT=Path(__file__).resolve().parents[1]
JAR_SHA256="380dc1e6c704a9a4ed8433e8b7892a149390f8912b9107a2a0e7263cfd71c7d8"
SOURCE_COMMIT="7f00eb866ed35c8fe3963f078b6a2e0979dc2b8c"
BRIDGE=ROOT/"tools/upr/SLinkRandomizer.class"
BRIDGE_PIN=ROOT/"tools/upr/bridge.json"


class UprRunError(ValueError):
    pass


def canonical_seed(value):
    if not isinstance(value,str) or not re.fullmatch(r"0|[1-9][0-9]*",value) or len(value)>15 or int(value)>=1<<48:
        raise UprRunError("seed must be canonical decimal in 0..2^48-1")
    return int(value)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def strict_log(raw):
    try:
        text=raw.decode("utf-8-sig")
    except UnicodeError as error:
        raise UprRunError("UPR log is not valid UTF-8") from error
    fields={}
    for label in ("Randomizer Version","Random Seed","Settings String"):
        found=[line[len(label)+1:].strip() for line in text.splitlines() if line.startswith(label+":")]
        if len(found)!=1 or not found[0]:
            raise UprRunError("UPR log must contain exactly one "+label)
        fields[label]=found[0]
    if fields["Randomizer Version"]!="4.6.1":
        raise UprRunError("UPR log version differs")
    seed=canonical_seed(fields["Random Seed"])
    if not fields["Settings String"].startswith(str(VERSION)):
        raise UprRunError("UPR effective settings version differs")
    settings=parse_settings_string(fields["Settings String"])
    return {"seed":seed,"settings_string":fields["Settings String"],"settings":settings}


def selected_custom_names(jar, *, override=None, source_directory=None):
    """Mirror source precedence, then snapshot exactly the bytes supplied to UPR."""
    if override is not None:
        path=Path(override).resolve()
        return path.read_bytes(),{"kind":"explicit","path":str(path)}
    for path in (Path(jar).resolve().parent/"customnames.rncn",Path(source_directory or Path.cwd()).resolve()/"customnames.rncn"):
        if path.is_file():
            return path.read_bytes(),{"kind":"file","path":str(path)}
    with zipfile.ZipFile(jar) as archive:
        name="com/dabomstew/pkrandom/config/customnames.rncn"
        return archive.read(name),{"kind":"jar-resource","member":name}


def run_pinned(jar,settings,source,directory,*,seed,generation,java="java",custom_names=None,timeout=120):
    """One sequential JVM in a new private directory. Caller validates generation policy.

    Output is a produced candidate, never a semantic/admission approval.
    """
    number=canonical_seed(seed)
    if type(generation) is not int or generation not in (1,2,3):
        raise UprRunError("explicit Gen1/2/3 handler required")
    if not isinstance(settings,bytes):
        raise UprRunError("immutable settings bytes required")
    parsed=load(settings)
    if parsed["version"]!=VERSION:
        raise UprRunError("settings migration is prohibited")
    jar,source,directory=Path(jar).resolve(),Path(source).resolve(),Path(directory).resolve()
    if directory.exists():
        raise UprRunError("new isolated output directory required")
    if not shutil.which(java):
        raise UprRunError("Java runtime unavailable")
    jar_bytes=jar.read_bytes()
    if sha(jar_bytes)!=JAR_SHA256:
        raise UprRunError("official UPR ZX4.6.1 JAR hash differs")
    bridge=BRIDGE.read_bytes()
    pin=json.loads(BRIDGE_PIN.read_text())
    if sha(bridge)!=pin["class_sha256"] or sha((ROOT/"tools/upr/SLinkRandomizer.java").read_bytes().replace(b"\r\n",b"\n"))!=pin["source_sha256"]:
        raise UprRunError("UPR bridge differs from its source/build pin")
    gen1_policy=(ROOT/"tools/upr/SLinkGen1RomHandler.class").read_bytes()
    if sha(gen1_policy)!=pin["gen1_policy_class_sha256"] or sha((ROOT/"tools/upr/SLinkGen1RomHandler.java").read_bytes().replace(b"\r\n",b"\n"))!=pin["gen1_policy_source_sha256"]:
        raise UprRunError("UPR Gen1 policy differs from its source/build pin")
    source_bytes=source.read_bytes()
    if not 0<len(source_bytes)<=64*1024*1024:
        raise UprRunError("unsupported input size")
    names,names_source=selected_custom_names(jar,override=custom_names)
    directory.mkdir(parents=True)
    (directory/"upr.jar").write_bytes(jar_bytes)
    (directory/"SLinkRandomizer.class").write_bytes(bridge)
    (directory/"SLinkGen1RomHandler.class").write_bytes(gen1_policy)
    (directory/"input.rnqs").write_bytes(settings)
    (directory/"customnames.rncn").write_bytes(names)
    # Gen1/2 handlers choose .gbc; Gen3 chooses .gba. No silent filename repair.
    extension=".gba" if generation==3 else ".gbc"
    incoming=directory/("input"+extension)
    output=directory/("randomized"+extension)
    incoming.write_bytes(source_bytes)
    arguments=[java,"-cp",str(directory)+os.pathsep+str(directory/"upr.jar"),"SLinkRandomizer",
               str(directory/"input.rnqs"),str(incoming),str(output),seed,str(directory/"customnames.rncn"),str(generation)]
    try:
        process=subprocess.run(arguments,cwd=directory,capture_output=True,timeout=timeout,check=False)
    except subprocess.TimeoutExpired as error:
        (directory/"stdout.txt").write_bytes(error.stdout or b"")
        (directory/"stderr.txt").write_bytes(error.stderr or b"")
        raise UprRunError("UPR invocation timed out; candidate is incomplete") from error
    (directory/"stdout.txt").write_bytes(process.stdout)
    (directory/"stderr.txt").write_bytes(process.stderr)
    if process.returncode!=0:
        raise UprRunError("UPR bridge failed: "+process.stderr.decode("utf-8","replace")[-600:])
    log=output.with_suffix(output.suffix+".log")
    decoded=strict_log(log.read_bytes())
    if decoded["seed"]!=number:
        raise UprRunError("UPR used a different seed")
    for path,expected in ((directory/"upr.jar",jar_bytes),(directory/"input.rnqs",settings),
                          (incoming,source_bytes),(directory/"customnames.rncn",names),(directory/"SLinkRandomizer.class",bridge),
                          (directory/"SLinkGen1RomHandler.class",gen1_policy)):
        if path.read_bytes()!=expected:
            raise UprRunError("UPR input snapshot changed during invocation")
    final=output.read_bytes()
    manifest={"schema":"slink-upr-run-v1","status":"produced_requires_semantic_scan","source_commit":SOURCE_COMMIT,"generation":generation,
        "jar_sha256":JAR_SHA256,"bridge_sha256":sha(bridge),"settings_sha256":sha(settings),
        "gen1_policy_sha256":sha(gen1_policy) if generation==1 else None,
        "source_sha256":sha(source_bytes),"source_sha1":hashlib.sha1(source_bytes).hexdigest(),"seed":seed,
        "custom_names":{"sha256":sha(names),"selection":names_source},
        "effective_settings_string":decoded["settings_string"],"log_sha256":sha(log.read_bytes()),
        "output":str(output),"output_sha256":sha(final),"output_sha1":hashlib.sha1(final).hexdigest(),"size":len(final)}
    (directory/"provenance.json").write_text(json.dumps(manifest,indent=2)+"\n")
    return manifest


def run_pair_pinned(jar, settings, sources, directory, *, seeds, generations, java="java", custom_names=None, timeout=120):
    """Produce two candidates sequentially with identical inputs and distinct seeds.

    This is reusable generation orchestration, not a pair admission policy.
    A failed second run leaves forensic staging evidence but no pair manifest.
    """
    for name, mapping in (("sources",sources),("seeds",seeds),("generations",generations)):
        if not isinstance(mapping,dict) or set(mapping)!={"a","b"}:
            raise UprRunError("exact a/b "+name+" required")
    if canonical_seed(seeds["a"])==canonical_seed(seeds["b"]):
        raise UprRunError("paired seeds must differ")
    if not isinstance(settings,bytes):
        raise UprRunError("immutable settings bytes required")
    directory=Path(directory).resolve()
    if directory.exists():
        raise UprRunError("new isolated pair directory required")
    names,selection=selected_custom_names(jar,override=custom_names)
    directory.mkdir(parents=True)
    names_path=directory/"customnames.rncn"
    names_path.write_bytes(names)
    players={}
    for player in ("a","b"):
        if names_path.read_bytes()!=names:
            raise UprRunError("pair custom-names snapshot changed")
        players[player]=run_pinned(jar,settings,sources[player],directory/player,seed=seeds[player],
            generation=generations[player],java=java,custom_names=names_path,timeout=timeout)
        if players[player]["custom_names"]["sha256"]!=sha(names):
            raise UprRunError("paired custom-names evidence differs")
    manifest={"schema":"slink-upr-pair-v1","status":"produced_requires_semantic_scan",
        "settings_sha256":sha(settings),"custom_names":{"sha256":sha(names),"selection":selection},"players":players}
    (directory/"pair-provenance.json").write_text(json.dumps(manifest,indent=2)+"\n")
    return manifest
