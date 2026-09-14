"""Launch the admitted cartridge with private per-run/player saves and config."""
import argparse
import json
import os
import sys
import traceback
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from server.bizhawk_launch import launch, prepare, validate_manifest  # noqa: E402
from server.runtime_lease import RuntimeLease  # noqa: E402

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox
except ImportError:
    tk=filedialog=messagebox=None

TITLE='SLink launcher'
# ponytail: flat substring->hint table; add a row here when prepare()/launch() grows a new
# refusal message a human launching by double-click needs steering on.
HINTS=(
    ('ROM differs from the admitted final cartridge',
     'Pick the FINAL admitted cartridge for your player; the Manager run page shows its SHA1.'),
    ('emulator executable differs from the qualified host',
     'Pick the EmuHawk.exe recorded when this run was qualified.'),
    ('resume','Pick the .SaveRAM you last played in the previous run.'),
)


def _hint_for(message):
    lowered=message.lower()
    for needle,hint in HINTS:
        if needle.lower() in lowered:
            return hint
    return None


def _dialog(kind,title,message):
    """Show a Tk dialog; fall back to stderr when Tk is unavailable or there is no display."""
    try:
        if tk is None or messagebox is None:
            raise RuntimeError('tkinter unavailable')
        root=tk.Tk()
        root.withdraw()
        getattr(messagebox,kind)(title,message)
        root.destroy()
    except Exception:
        print(f'{title}: {message}',file=sys.stderr)


def _report_error(exc):
    message=(str(exc).splitlines() or [exc.__class__.__name__])[0]
    hint=_hint_for(message) or 'See the terminal for details.'
    _dialog('showerror',TITLE,f'{message}\n\n{hint}')
    traceback.print_exc()


def _tk_root():
    if tk is None or filedialog is None:
        raise RuntimeError('tkinter unavailable')
    root=tk.Tk()
    root.withdraw()
    return root


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path)
    parser.add_argument('--rom',type=Path)
    parser.add_argument('--emuhawk',type=Path)
    parser.add_argument('--base-config',type=Path)
    parser.add_argument('--root',type=Path,default=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'SLink/clients')
    parser.add_argument('--resume-save',type=Path,help='the .SaveRAM the predecessor run last acknowledged (resumed runs only)')
    args=parser.parse_args()
    if not all((args.manifest,args.rom,args.emuhawk)):
        try:
            gui=_tk_root()
        except Exception:
            print(f'{TITLE}: no display available; pass --manifest/--rom/--emuhawk directly.',file=sys.stderr)
            return 1
        for field,title,patterns in (
                ('manifest','Choose the downloaded launch.json',[('Launch manifest','*.json')]),
                ('rom','Choose your cartridge',[('Cartridge','*.gb *.gbc *.gba')]),
                ('emuhawk','Choose EmuHawk.exe',[('EmuHawk','EmuHawk.exe')])):
            if getattr(args,field) is None:
                chosen=filedialog.askopenfilename(title=title,filetypes=patterns)
                if not chosen:
                    gui.destroy()
                    _dialog('showinfo',TITLE,'Launch cancelled')
                    return 0
                setattr(args,field,Path(chosen))
        gui.destroy()
    try:
        spec=json.loads(args.manifest.read_text(encoding='utf-8'))
        validate_manifest(spec)
        home=(args.root.resolve()/spec['run_id']/spec['player']).resolve()
        if not home.is_relative_to(args.root.resolve()):
            raise ValueError('player launch directory leaves its owned root')
        if spec.get('resume') and args.resume_save is None and not any((home/'SaveRAM').glob('*')):
            # First launch of a resumed run: the private save directory is empty until the player's own
            # save is imported; prepare() verifies it against the acknowledged digest before copying.
            gui=_tk_root()
            chosen=filedialog.askopenfilename(title='Choose the save you last played in the previous run',
                                               filetypes=[('BizHawk SaveRAM','*.SaveRAM')])
            gui.destroy()
            if not chosen:
                _dialog('showinfo',TITLE,'Launch cancelled')
                return 0
            args.resume_save=Path(chosen)
        home.mkdir(parents=True,exist_ok=True)
        # Hold the player lease before preparation and until the process exits.
        with RuntimeLease(home/'.process.lock'):
            plan=prepare(args.root,spec,rom=args.rom,launcher=args.manifest.with_name('launcher.lua'),
                         base_config=args.base_config or args.emuhawk.with_name('config.ini'),resume_save=args.resume_save)
            process=launch(plan,args.emuhawk)
    except Exception as exc:
        _report_error(exc)
        return 1
    pid=getattr(process,'pid',None)
    suffix=f' [pid {pid}]' if pid is not None else ''
    print(f"SLink: EmuHawk started for player {spec['player']} (run {spec['run_id']}); keep this window open{suffix}")
    return process.wait()


if __name__=='__main__':
    raise SystemExit(main())
