"""Compile SLink's small Java8 bridge against a user-supplied pinned UPR JAR."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def build(jar,javac):
    source=ROOT/"tools/upr/SLinkRandomizer.java"
    gen1_source=ROOT/"tools/upr/SLinkGen1RomHandler.java"
    if hashlib.sha256(Path(jar).read_bytes()).hexdigest()!="380dc1e6c704a9a4ed8433e8b7892a149390f8912b9107a2a0e7263cfd71c7d8":
        raise ValueError("official UPR ZX4.6.1 required")
    compiler=shutil.which(str(javac)) or str(javac)
    output=ROOT/"tools/upr"
    subprocess.run([compiler,"-encoding","UTF-8","-source","8","-target","8","-g:none","-cp",str(jar),"-d",str(output),str(source),str(gen1_source)],check=True)
    raw=(output/"SLinkRandomizer.class").read_bytes()
    if raw[:4]!=bytes.fromhex("cafebabe") or int.from_bytes(raw[6:8],"big")!=52:
        raise ValueError("Java8 class output required")
    pin={"schema":"slink-upr-bridge-v1","source_sha256":hashlib.sha256(source.read_bytes().replace(b"\r\n",b"\n")).hexdigest(),
         "class_sha256":hashlib.sha256(raw).hexdigest(),"class_version":52,
         "gen1_policy_source_sha256":hashlib.sha256(gen1_source.read_bytes().replace(b"\r\n",b"\n")).hexdigest(),
         "gen1_policy_class_sha256":hashlib.sha256((output/"SLinkGen1RomHandler.class").read_bytes()).hexdigest(),
         "compiler_sha256":hashlib.sha256(Path(compiler).read_bytes()).hexdigest(),
         "compiler_version":subprocess.check_output([compiler,"-version"],stderr=subprocess.STDOUT,text=True).strip()}
    (output/"bridge.json").write_text(json.dumps(pin,indent=2)+"\n")
    print(json.dumps(pin,indent=2))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar",required=True)
    parser.add_argument("--javac",default=os.getenv("SLINK_JAVAC","javac"))
    options=parser.parse_args()
    build(Path(options.jar).resolve(),options.javac)
