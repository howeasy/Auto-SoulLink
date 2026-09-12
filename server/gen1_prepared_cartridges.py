"""Revalidate a local prepared pair before using its exact cartridge metadata."""
from __future__ import annotations
import copy
import hashlib
import json
import tempfile
from pathlib import Path

from patch.tools.make_ups import ups_apply,ups_create
from server.gen1_admission import CONTRACT_SCHEMA,cartridge_metadata,clean_profiles
from server.gen1_companion_patch import apply_to_candidate
from server.gen1_upr_policy import validate_file,verify_effective
from server.gen1_upr_scan import LAYOUT
from server.protocol import canonical_json,decode_frame,digest
from server.upr_runner import BRIDGE_PIN,JAR_SHA256,SOURCE_COMMIT,canonical_seed,run_pinned,strict_log


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
                "capabilities":expected["capabilities"],"content_profile_hash":digest({
                    "semantic_profile":expected["semantic_profile"],"manifest_sha256":expected["manifest_sha256"],
                    "generation":run})}
            self._profiles[player]=profile;self._roms[player]=final;self._manifests[player]=manifest
            self._unpatched[player]=candidate;self._patches[player]=encoded
        if seeds[0]==seeds[1]:raise ValueError("prepared paired seeds must differ")

    def contract(self):
        return {"schema":CONTRACT_SCHEMA,"players":{p:cartridge_metadata(value) for p,value in self._profiles.items()}}

    def validate_contract(self,contract):
        if canonical_json(contract)!=canonical_json(self.contract()):raise ValueError("contract differs from the revalidated prepared pair")
        return copy.deepcopy(contract["players"])

    def manifest(self,player):return copy.deepcopy(self._manifests[player])
    def rom(self,player):return self._roms[player]
    def unpatched_rom(self,player):return self._unpatched[player]
    def patch(self,player):return self._patches[player]
