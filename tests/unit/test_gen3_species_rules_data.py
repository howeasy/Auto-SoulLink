"""RF-3: committed normalization facts are checked even without private ROMs."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from server.adapters.gen3_rom_tables import FRLG_ZERO_SECOND_ABILITY_SPECIES

ROOT = Path(__file__).resolve().parents[2]
FACTS = ROOT / "data/games/gen3_frlg/species_rules.json"


def test_committed_original_empty_ability_slots_have_pinned_provenance_and_anchors():
    facts = json.loads(FACTS.read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "data/gen3_sources.lock.json").read_text(encoding="utf-8"))
    assert facts["schema"] == 1
    assert facts["source"] == lock["source"]
    assert facts["record_size"] == 28 and facts["second_ability_offset"] == 23
    slots = facts["zero_second_ability_species"]
    assert slots == sorted(set(slots)) and len(slots) == 284
    assert {0, 1, 410, 411} <= set(slots)             # NONE, Bulbasaur, Deoxys, EGG
    assert not {19, 333} & set(slots)                # Rattata: RUN_AWAY/GUTS; Vibrava: two LEVITATE
    assert frozenset(slots) == FRLG_ZERO_SECOND_ABILITY_SPECIES
    assert set(facts["titles"]) == {"firered", "leafgreen"}
    for title, evidence in facts["titles"].items():
        assert evidence["rom_sha1"] == lock["outputs"][f"poke{title}"]["sha1"]
        assert evidence["species_count"] == 412
        sym = ROOT / "data/gen3/pret" / f"poke{title}.sym"
        assert evidence["symbols_sha256"] == hashlib.sha256(sym.read_bytes()).hexdigest()
        assert len(evidence["species_info_sha256"]) == 64


def test_generated_facts_match_both_pinned_dumps():
    from tests.unit.test_gen3_rom_ingest import _clean
    from tools.gen_gen3_species_rules import build

    assert build({title: _clean(title) for title in ("firered", "leafgreen")}) == json.loads(
        FACTS.read_text(encoding="utf-8"))


@pytest.mark.parametrize("fault,marker", (
    ("missing_file", "FileNotFoundError"),
    ("missing_pin", "symbols_sha256"),
    ("short_pin", "species_info_sha256"),
    ("truncated_slots", "zero_second_ability_species"),
    ("duplicated_slots", "zero_second_ability_species"),
))
def test_frlg_rule_facts_are_required_at_import(fault, marker):
    # A subprocess isolates the import without replacing the module held by other tests.
    script = '''
import io, json
from pathlib import Path
path = Path('data/games/gen3_frlg/species_rules.json')
facts = json.loads(path.read_text())
original = Path.open
def opened(self, *args, **kwargs):
    if self.as_posix().endswith('data/games/gen3_frlg/species_rules.json'):
        if FAULT == 'missing_file':
            raise FileNotFoundError('FR/LG species_rules fixture absent')
        if FAULT == 'missing_pin':
            del facts['titles']['firered']['symbols_sha256']
        elif FAULT == 'short_pin':
            facts['titles']['leafgreen']['species_info_sha256'] = 'abc'
        elif FAULT == 'truncated_slots':
            facts['zero_second_ability_species'] = facts['zero_second_ability_species'][:-1]
        else:
            facts['zero_second_ability_species'] = [0, 1, 1] + facts['zero_second_ability_species'][3:]
        return io.StringIO(json.dumps(facts))
    return original(self, *args, **kwargs)
Path.open = opened
import server.adapters.gen3_rom_tables
'''
    result = subprocess.run([sys.executable, "-c", "FAULT=" + repr(fault) + "\n" + script],
                            cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0, "a broken FR/LG species_rules.json silently survived import"
    assert marker in result.stderr
