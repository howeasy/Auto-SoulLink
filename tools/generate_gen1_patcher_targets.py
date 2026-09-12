"""Generate browser target fingerprints from checked canonical companion artifacts."""
import hashlib
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from server.gen1_cartridge_profiles import companion_profiles
from server.gen1_upr_scan import LOCK,TITLES
from patch.tools.make_ups import ups_apply


def generate():
    targets={}
    for variant,profile in companion_profiles().items():
        base=(ROOT/LOCK['clean_roms'][TITLES[variant]]['filename']).read_bytes()
        manifest=profile['manifest'];final=(ROOT/manifest['output']).read_bytes()
        patch=(ROOT/manifest['companion']['ups']).read_bytes()
        if (hashlib.sha1(base).hexdigest()!=profile['base_sha1'] or hashlib.sha256(final).hexdigest()!=profile['rom_sha256']
                or hashlib.sha256(patch).hexdigest()!=manifest['companion']['ups_sha256'] or ups_apply(base,patch)!=final):
            raise ValueError('canonical browser artifact differs: '+variant)
        slug='rb-'+variant if variant!='yellow' else 'yellow'
        targets[slug]={'slug':slug,'label':'Pokemon '+variant.capitalize(),'variant':variant,
            'patch':'SLink-'+variant.capitalize()+'.ups','patch_path':manifest['companion']['ups'],
            'base_md5':hashlib.md5(base).hexdigest(),'patched_md5':hashlib.md5(final).hexdigest(),
            'base_sha256':hashlib.sha256(base).hexdigest(),'patched_sha256':profile['rom_sha256'],
            'patch_sha256':manifest['companion']['ups_sha256'],'capabilities':profile['capabilities'],
            'accept':'.gb,.gbc,application/octet-stream','out_name':'Pokemon '+variant.capitalize()+' (SLink companion).gbc',
            'base_hint':'a clean US-English Pokemon '+variant.capitalize()+' dump'}
    return {'schema':'gen1-browser-patcher-targets-v1','targets':targets}


if __name__=='__main__':
    output=ROOT/'data/games/gen1_rby/patcher_targets.json'
    output.write_text(json.dumps(generate(),indent=2)+'\n')
    print(output)
