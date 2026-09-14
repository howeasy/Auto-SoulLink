"""Revalidate a local prepared pair before using its exact cartridge metadata.

Two shapes share one class so every `isinstance(..., PreparedCartridges)` gate and the
persisted `prepared_artifacts` relative-path readback (gen1_run_config) keep working:

* ``slink-gen1-prepared-artifacts-v1``: a UPR-randomized pair, re-reproduced on every open.
* ``slink-gen1-canonical-companion-pair-v1``: the canonical companion pair, derived inside the
  run from the players' admitted CLEAN cartridges by the installed catalog spans and pinned to
  the catalog's final hashes (`stage_canonical_pair`). No UPR, no seeds, no randomized
  provenance; `unpatched_rom`/`patch` are unavailable and `prepared_targets` presents nothing.
"""
from __future__ import annotations
import copy
import hashlib
import json
import tempfile
from pathlib import Path

from patch.tools.make_ups import ups_apply,ups_create
from server.gen1_admission import CONTRACT_SCHEMA,cartridge_metadata,clean_profiles
from server.gen1_cartridge_profiles import companion_profiles
from server.gen1_companion_patch import apply_to_candidate
from server.patch_plan import PatchSpan,apply_spans
from server.gen1_upr_policy import validate_file,verify_effective
from server.gen1_upr_scan import LAYOUT
from server.protocol import canonical_json,decode_frame,digest
from server.upr_runner import BRIDGE_PIN,JAR_SHA256,SOURCE_COMMIT,canonical_seed,run_pinned,strict_log


CANONICAL_SCHEMA="slink-gen1-canonical-companion-pair-v1"
SPAN_OPTIONS={"protected":((0x100,0x150),),"bank_size":0x4000}


def content_identity(semantic_profile,manifest_sha256,generation):
    """Hash a location-free view of a reproduced-UPR pair's content for content_profile_hash.

    `generation` is upr_runner.py's per-player record, which carries `"output": str(output)`
    — an absolute path unique to the run directory it was prepared in. Byte-identical
    ROM+settings+seed prepared into two different run directories must still compare equal
    here, or a resumed run is wrongly refused as a cartridge mismatch (gen1_run_config.py's
    "resumed run must use the predecessor cartridge pair" check). Every other field of
    `generation` (settings/seed/output hashes etc.) still participates.
    """
    return digest({"semantic_profile":semantic_profile,"manifest_sha256":manifest_sha256,
        "generation":{k:v for k,v in generation.items() if k!="output"}})


def _companion_from_clean(rom):
    """The canonical companion for one admitted clean cartridge, or a ValueError."""
    clean=clean_profiles()
    sha1=hashlib.sha1(rom).hexdigest()
    variant=next((v for v,p in clean.items() if p["final_rom_sha1"]==sha1),None)
    if variant is None or hashlib.sha256(rom).hexdigest()!=clean[variant]["rom_sha256"]:
        raise ValueError("canonical companion pair requires the admitted clean cartridge")
    installed=companion_profiles()[variant];manifest=installed["manifest"]
    spans=[PatchSpan(row["offset"],bytes.fromhex(row["before_hex"]),bytes.fromhex(row["after_hex"]),row["label"])
           for row in manifest["companion"]["spans"]]
    final=apply_spans(rom,spans,**SPAN_OPTIONS)
    if (hashlib.sha256(final).hexdigest()!=installed["rom_sha256"] or hashlib.sha1(final).hexdigest()!=installed["final_rom_sha1"]
            or installed["final_rom_sha1"]!=manifest["final_sha1"]):
        raise ValueError("installed companion spans do not reproduce the canonical artifact")
    return variant,installed,final


def stage_canonical_pair(directory,clean_paths):
    """Derive and pin the canonical companion pair inside a run from two clean cartridges.

    Writes ``final/<player>/slink_<variant>.gb`` + ``manifest.json`` and ``prepared-artifacts.json``
    under ``directory`` (which must be inside the run: gen1_run_config.configure_runtime). Returns the
    directory. Never accepts a patched or unknown input; never reads the build tree.
    """
    if not isinstance(clean_paths,dict) or set(clean_paths)!={"a","b"}:raise ValueError("both players' clean cartridges required")
    directory=Path(directory).resolve()
    if directory.exists() and any(directory.iterdir()):raise ValueError("canonical pair directory must be empty")
    players={}
    for player,source in clean_paths.items():
        rom=Path(source).read_bytes()
        variant,installed,final=_companion_from_clean(rom)
        target=directory/"final"/player;target.mkdir(parents=True,exist_ok=True)
        rom_name=f"slink_{variant}.gb";(target/rom_name).write_bytes(final)
        manifest=copy.deepcopy(installed["manifest"]);manifest["output"]=f"final/{player}/{rom_name}"
        encoded=json.dumps(manifest,sort_keys=True,separators=(",",":")).encode()
        (target/"manifest.json").write_bytes(encoded)
        players[player]={"variant":variant,"rom":manifest["output"],"rom_sha1":installed["final_rom_sha1"],
            "rom_sha256":installed["rom_sha256"],"manifest":f"final/{player}/manifest.json",
            "manifest_sha256":hashlib.sha256(encoded).hexdigest(),"content_profile_hash":installed["content_profile_hash"]}
    published={"schema":CANONICAL_SCHEMA,"status":"canonical_requires_runtime_admission","runtime_ready":False,"players":players}
    # The descriptor is published last and atomically: a partial stage has no descriptor and
    # PreparedCartridges refuses the directory, so a run is never created over half a pair.
    index=directory/"prepared-artifacts.json";temporary=index.with_suffix(".tmp")
    temporary.write_text(json.dumps(published,sort_keys=True,indent=1),encoding="utf-8");temporary.replace(index)
    PreparedCartridges(directory)  # readback proof before the caller publishes the run
    return directory


class PreparedCartridges:
    """Local production evidence, rechecked and reproduced on each open.

    This provides cartridge admission facts only. It grants no physical, ordinary
    or recovery execution. External imports do not acquire seed provenance by
    supplying a candidate JSON file to this constructor.
    """
    def __init__(self,directory,*,java="java"):
        self.directory=Path(directory).resolve()
        def path(relative):
            if not isinstance(relative,str):raise ValueError("prepared artifact path required")
            result=(self.directory/relative).resolve()
            if not result.is_relative_to(self.directory):raise ValueError("prepared artifact leaves its directory")
            return result
        def read_json(relative):return decode_frame(path(relative).read_bytes())
        published=read_json("prepared-artifacts.json")
        if isinstance(published,dict) and published.get("schema")==CANONICAL_SCHEMA:
            self.provenance="canonical_companion";self._init_canonical(published,path);return
        self.provenance="reproduced_upr"
        if (set(published)!={"schema","status","settings_sha256","custom_names_sha256","players","runtime_ready"}
                or published["schema"]!="slink-gen1-prepared-artifacts-v1" or published["status"]!="prepared_requires_runtime_admission"
                or published["runtime_ready"] is not False or not isinstance(published["players"],dict)
                or set(published["players"])!={"a","b"}):
            raise ValueError("complete prepared RBY pair required")
        generated=read_json("generation/pair-provenance.json")
        if generated.get("schema")!="slink-upr-pair-v1" or set(generated.get("players",{}))!={"a","b"}:
            raise ValueError("complete paired generation provenance required")
        pin=json.loads(BRIDGE_PIN.read_text())
        self._profiles={};self._roms={};self._manifests={};self._unpatched={};self._patches={}
        settings=path("generation/a/input.rnqs").read_bytes();validate_file(settings)
        names=path("generation/customnames.rncn").read_bytes()
        sha=lambda value:hashlib.sha256(value).hexdigest()
        if (path("generation/b/input.rnqs").read_bytes()!=settings or sha(settings)!=published["settings_sha256"]
                or sha(settings)!=generated.get("settings_sha256") or sha(names)!=published["custom_names_sha256"]
                or sha(names)!=generated.get("custom_names",{}).get("sha256")):
            raise ValueError("paired settings/custom-names snapshots differ")
        seeds=[];clean=clean_profiles()
        reproduction=Path(tempfile.mkdtemp(prefix=".reproduced-",dir=self.directory))
        for player,entry in published["players"].items():
            if set(entry)!={"variant","seed","rom","rom_sha1","rom_sha256","candidate","candidate_sha256"}:
                raise ValueError("prepared player descriptor differs")
            report=read_json(entry["candidate"]);run=generated["players"][player]
            seeds.append(canonical_seed(entry["seed"]))
            if digest(report)!=entry["candidate_sha256"] or report.get("generation")!=run or run.get("seed")!=entry["seed"]:
                raise ValueError("prepared candidate/generation binding differs")
            for name,expected in (("upr.jar",JAR_SHA256),("SLinkRandomizer.class",pin["class_sha256"]),
                                  ("SLinkGen1RomHandler.class",pin["gen1_policy_class_sha256"]),
                                  ("input.rnqs",sha(settings)),("customnames.rncn",sha(names))):
                if sha(path(f"generation/{player}/{name}").read_bytes())!=expected:
                    raise ValueError("prepared generation input hash differs: "+name)
            if (run.get("schema")!="slink-upr-run-v1" or run.get("status")!="produced_requires_semantic_scan"
                    or run.get("source_commit")!=SOURCE_COMMIT or run.get("settings_sha256")!=sha(settings)
                    or run.get("custom_names",{}).get("sha256")!=sha(names)
                    or run.get("jar_sha256")!=JAR_SHA256 or run.get("bridge_sha256")!=pin["class_sha256"]
                    or run.get("gen1_policy_sha256")!=pin["gen1_policy_class_sha256"] or run.get("generation")!=1):
                raise ValueError("prepared generator version differs")
            original=path(f"generation/{player}/input.gbc").read_bytes()
            candidate_path=path(f"generation/{player}/randomized.gbc")
            candidate=candidate_path.read_bytes();log=path(f"generation/{player}/randomized.gbc.log").read_bytes()
            if (Path(run["output"]).resolve()!=candidate_path or sha(candidate)!=run["output_sha256"]
                    or hashlib.sha1(candidate).hexdigest()!=run.get("output_sha1") or len(candidate)!=run.get("size")
                    or sha(original)!=run["source_sha256"] or hashlib.sha1(original).hexdigest()!=run.get("source_sha1")
                    or sha(log)!=run["log_sha256"]):
                raise ValueError("prepared source/output/log hashes differ")
            decoded=strict_log(log)
            if decoded["seed"]!=seeds[-1] or decoded["settings_string"]!=run["effective_settings_string"]:
                raise ValueError("prepared log seed/settings differ")
            repeated=run_pinned(path(f"generation/{player}/upr.jar"),settings,path(f"generation/{player}/input.gbc"),
                reproduction/player,seed=entry["seed"],generation=1,java=java,
                custom_names=path(f"generation/{player}/customnames.rncn"))
            if (Path(repeated["output"]).read_bytes()!=candidate or repeated["effective_settings_string"]!=run["effective_settings_string"]):
                raise ValueError("prepared candidate does not reproduce from its exact claimed seed/settings")
            final,expected=apply_to_candidate(original,candidate,settings=settings)
            variant=expected["variant"]
            from server.adapters.gen1_rom_scan import scan_pokedex_order
            dex=scan_pokedex_order(original);cfg=LAYOUT["profiles"][variant]["settings"]
            starters=[dex[original[cfg[f"StarterOffsets{i}"][0]]] for i in range(1,3 if variant=="yellow" else 4)]
            verify_effective(settings,decoded["settings_string"],starters)
            encoded=ups_create(candidate,final)
            manifest=expected["manifest"]
            manifest["output"]=entry["rom"]
            manifest["companion"].update(ups=f"final/{player}/companion.ups",ups_sha256=sha(encoded))
            expected.update(manifest_sha256=digest(manifest),generation=run,preparation_root=str(self.directory))
            if (canonical_json(expected)!=canonical_json(report) or entry["variant"]!=variant
                    or entry["rom_sha1"]!=expected["final_sha1"] or entry["rom_sha256"]!=sha(final)
                    or path(entry["rom"]).read_bytes()!=final or path(manifest["companion"]["ups"]).read_bytes()!=encoded
                    or ups_apply(candidate,encoded)!=final):
                raise ValueError("prepared final artifact/manifest/profile differs")
            profile={"schema":"gen1-rby-scanned-companion-content-v1","variant":variant,
                "final_rom_sha1":expected["final_sha1"],"patch_version":3,"party_codec":clean[variant]["party_codec"],
                "capabilities":expected["capabilities"],"content_profile_hash":content_identity(
                    expected["semantic_profile"],expected["manifest_sha256"],run)}
            self._profiles[player]=profile;self._roms[player]=final;self._manifests[player]=manifest
            self._unpatched[player]=candidate;self._patches[player]=encoded
        if seeds[0]==seeds[1]:raise ValueError("prepared paired seeds must differ")

    def _init_canonical(self,published,path):
        """Re-verify the staged canonical pair against its descriptor AND the installed catalog."""
        if (set(published)!={"schema","status","runtime_ready","players"} or published["status"]!="canonical_requires_runtime_admission"
                or published["runtime_ready"] is not False or not isinstance(published["players"],dict)
                or set(published["players"])!={"a","b"}):
            raise ValueError("complete canonical companion pair required")
        self._profiles={};self._roms={};self._manifests={};self._unpatched={};self._patches={}
        companions=companion_profiles()
        for player,entry in published["players"].items():
            if (not isinstance(entry,dict) or set(entry)!={"variant","rom","rom_sha1","rom_sha256","manifest","manifest_sha256","content_profile_hash"}
                    or entry["variant"] not in companions):
                raise ValueError("canonical player descriptor differs")
            installed=companions[entry["variant"]]
            # Exact player-scoped paths: an aliased descriptor pointing both players at one file
            # would pass every hash check while erasing the per-player artifact distinction.
            if (entry["rom"]!=f"final/{player}/slink_{entry['variant']}.gb" or entry["manifest"]!=f"final/{player}/manifest.json"):
                raise ValueError("canonical companion artifact path differs from its player")
            final=path(entry["rom"]).read_bytes();encoded=path(entry["manifest"]).read_bytes()
            manifest=decode_frame(encoded)
            expected=copy.deepcopy(installed["manifest"]);expected["output"]=entry["rom"]
            if (hashlib.sha1(final).hexdigest()!=installed["final_rom_sha1"] or hashlib.sha256(final).hexdigest()!=installed["rom_sha256"]
                    or entry["rom_sha1"]!=installed["final_rom_sha1"] or entry["rom_sha256"]!=installed["rom_sha256"]
                    or entry["content_profile_hash"]!=installed["content_profile_hash"]
                    or hashlib.sha256(encoded).hexdigest()!=entry["manifest_sha256"]
                    or canonical_json(manifest)!=canonical_json(expected)):
                raise ValueError("canonical companion artifact/manifest differs from the installed catalog")
            self._profiles[player]=copy.deepcopy(installed);self._roms[player]=final;self._manifests[player]=manifest

    def contract(self):
        return {"schema":CONTRACT_SCHEMA,"players":{p:cartridge_metadata(value) for p,value in self._profiles.items()}}

    def validate_contract(self,contract):
        if canonical_json(contract)!=canonical_json(self.contract()):raise ValueError("contract differs from the revalidated prepared pair")
        return copy.deepcopy(contract["players"])

    def manifest(self,player):return copy.deepcopy(self._manifests[player])
    def rom(self,player):return self._roms[player]
    def unpatched_rom(self,player):
        if player not in self._unpatched:raise ValueError("canonical companion pair has no unpatched randomized artifact")
        return self._unpatched[player]
    def patch(self,player):
        if player not in self._patches:raise ValueError("canonical companion pair has no distributable patch")
        return self._patches[player]
