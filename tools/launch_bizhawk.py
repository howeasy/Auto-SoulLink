"""Launch the admitted cartridge with private per-run/player saves and config."""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from server.bizhawk_launch import launch, prepare, validate_manifest
from server.runtime_lease import RuntimeLease


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path)
    parser.add_argument('--rom',type=Path)
    parser.add_argument('--emuhawk',type=Path)
    parser.add_argument('--base-config',type=Path)
    parser.add_argument('--root',type=Path,default=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'SLink/clients')
    args=parser.parse_args()
    gui=None
    if not all((args.manifest,args.rom,args.emuhawk)):
        import tkinter as tk
        from tkinter import filedialog
        gui=tk.Tk();gui.withdraw()
        for field,title,patterns in (
                ('manifest','Choose the downloaded launch.json',[('Launch manifest','*.json')]),
                ('rom','Choose your cartridge',[('Cartridge','*.gb *.gbc *.gba')]),
                ('emuhawk','Choose EmuHawk.exe',[('EmuHawk','EmuHawk.exe')])):
            if getattr(args,field) is None:
                chosen=filedialog.askopenfilename(title=title,filetypes=patterns)
                if not chosen:gui.destroy();return 0
                setattr(args,field,Path(chosen))
        gui.destroy()
    spec=json.loads(args.manifest.read_text(encoding='utf-8'))
    validate_manifest(spec)
    home=(args.root.resolve()/spec['run_id']/spec['player']).resolve()
    if not home.is_relative_to(args.root.resolve()):raise ValueError('player launch directory leaves its owned root')
    home.mkdir(parents=True,exist_ok=True)
    # Hold the player lease before preparation and until the process exits.
    with RuntimeLease(home/'.process.lock'):
        plan=prepare(args.root,spec,rom=args.rom,launcher=args.manifest.with_name('launcher.lua'),
                     base_config=args.base_config or args.emuhawk.with_name('config.ini'))
        return launch(plan,args.emuhawk).wait()


if __name__=='__main__':raise SystemExit(main())
