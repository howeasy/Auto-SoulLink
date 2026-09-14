"""HS-3: launch_bizhawk.py must never show a naked traceback to a human who double-clicks it."""
import json

import tools.launch_bizhawk as tool


class FakeRoot:
    def withdraw(self):pass
    def destroy(self):pass


class FakeTk:
    """Stands in for the `tkinter` module: `.Tk()` never opens a real window."""
    def Tk(self):
        return FakeRoot()


class FakeMessagebox:
    def __init__(self):
        self.calls=[]

    def showerror(self,title,message):
        self.calls.append(('showerror',title,message))

    def showinfo(self,title,message):
        self.calls.append(('showinfo',title,message))


class FakeProcess:
    def __init__(self,pid=4242,exit_code=0):
        self.pid=pid
        self._exit_code=exit_code

    def wait(self):
        return self._exit_code


def no_gui(monkeypatch):
    """Route every dialog through fakes instead of a real display."""
    monkeypatch.setattr(tool,'tk',FakeTk())
    messagebox=FakeMessagebox()
    monkeypatch.setattr(tool,'messagebox',messagebox)
    return messagebox


def manifest_path(tmp_path,spec=None):
    path=tmp_path/'launch.json'
    path.write_text(json.dumps(spec or {'run_id':'a'*32,'player':'a'}))
    return path


def argv(tmp_path,manifest,extra=()):
    return ['launch_bizhawk','--manifest',str(manifest),'--rom',str(tmp_path/'game.gb'),
            '--emuhawk',str(tmp_path/'EmuHawk.exe'),'--root',str(tmp_path/'clients'),*extra]


def test_known_prepare_error_shows_hint_and_exits_1(tmp_path,monkeypatch):
    messagebox=no_gui(monkeypatch)
    monkeypatch.setattr(tool,'validate_manifest',lambda spec:None)
    def refuse(*a,**k):
        raise ValueError('ROM differs from the admitted final cartridge')
    monkeypatch.setattr(tool,'prepare',refuse)
    monkeypatch.setattr(tool.sys,'argv',argv(tmp_path,manifest_path(tmp_path)))
    assert tool.main()==1
    assert len(messagebox.calls)==1
    kind,title,body=messagebox.calls[0]
    assert kind=='showerror' and title=='SLink launcher'
    assert 'ROM differs from the admitted final cartridge' in body
    assert 'FINAL admitted cartridge' in body


def test_known_emulator_error_shows_its_own_hint(tmp_path,monkeypatch):
    messagebox=no_gui(monkeypatch)
    monkeypatch.setattr(tool,'validate_manifest',lambda spec:None)
    monkeypatch.setattr(tool,'prepare',lambda *a,**k:{'ok':1})
    def refuse(*a,**k):
        raise ValueError('emulator executable differs from the qualified host')
    monkeypatch.setattr(tool,'launch',refuse)
    monkeypatch.setattr(tool.sys,'argv',argv(tmp_path,manifest_path(tmp_path)))
    assert tool.main()==1
    _,_,body=messagebox.calls[0]
    assert 'qualified host' in body and 'EmuHawk.exe recorded when this run was qualified' in body


def test_unknown_error_falls_back_to_generic_hint(tmp_path,monkeypatch):
    messagebox=no_gui(monkeypatch)
    monkeypatch.setattr(tool,'validate_manifest',lambda spec:None)
    def refuse(*a,**k):
        raise RuntimeError('disk caught fire')
    monkeypatch.setattr(tool,'prepare',refuse)
    monkeypatch.setattr(tool.sys,'argv',argv(tmp_path,manifest_path(tmp_path)))
    assert tool.main()==1
    _,_,body=messagebox.calls[0]
    assert 'disk caught fire' in body and 'See the terminal for details.' in body


def test_dialog_cancellation_shows_info_and_exits_0(tmp_path,monkeypatch):
    messagebox=no_gui(monkeypatch)
    class CancelFileDialog:
        def askopenfilename(self,**kwargs):
            return ''
    monkeypatch.setattr(tool,'filedialog',CancelFileDialog())
    monkeypatch.setattr(tool.sys,'argv',['launch_bizhawk'])
    assert tool.main()==0
    assert messagebox.calls==[('showinfo','SLink launcher','Launch cancelled')]


def test_success_prints_started_line_with_pid(tmp_path,monkeypatch,capsys):
    no_gui(monkeypatch)
    monkeypatch.setattr(tool,'validate_manifest',lambda spec:None)
    monkeypatch.setattr(tool,'prepare',lambda *a,**k:{'ok':1})
    monkeypatch.setattr(tool,'launch',lambda plan,exe:FakeProcess(pid=4242,exit_code=0))
    monkeypatch.setattr(tool.sys,'argv',argv(tmp_path,manifest_path(tmp_path)))
    assert tool.main()==0
    out=capsys.readouterr().out
    assert 'SLink: EmuHawk started for player a (run '+'a'*32 in out
    assert 'keep this window open' in out and '[pid 4242]' in out


def test_tk_unavailable_falls_back_to_stderr_without_raising(tmp_path,monkeypatch,capsys):
    monkeypatch.setattr(tool,'tk',None)
    monkeypatch.setattr(tool,'messagebox',None)
    monkeypatch.setattr(tool,'validate_manifest',lambda spec:None)
    def refuse(*a,**k):
        raise ValueError('ROM differs from the admitted final cartridge')
    monkeypatch.setattr(tool,'prepare',refuse)
    monkeypatch.setattr(tool.sys,'argv',argv(tmp_path,manifest_path(tmp_path)))
    assert tool.main()==1
    err=capsys.readouterr().err
    assert 'ROM differs from the admitted final cartridge' in err


def test_no_display_for_dialogs_reports_and_exits_1_without_raising(monkeypatch,capsys):
    monkeypatch.setattr(tool,'tk',None)
    monkeypatch.setattr(tool,'filedialog',None)
    monkeypatch.setattr(tool.sys,'argv',['launch_bizhawk'])
    assert tool.main()==1
    err=capsys.readouterr().err
    assert 'no display available' in err
