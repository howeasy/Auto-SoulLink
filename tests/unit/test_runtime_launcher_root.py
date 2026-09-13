"""Execute rendered launchers with real Lua/files and a modeled .NET host boundary."""

import hashlib
import json
from pathlib import Path

import pytest
from lupa.lua54 import LuaError, LuaRuntime

from server.runtime_launcher import file_bundle, render_launcher


class LauncherHost:
    """Supply .NET crypto/dialog APIs and a child process's environment to Lua."""

    def __init__(self, environment=None):
        self.lua = LuaRuntime(encoding=None, unpack_returned_tuples=True)
        self.dialogs = 0
        self.reads = []
        table = self.lua.table_from

        def read_bytes(path):
            resolved = Path(path.decode("utf-8")).resolve()
            self.reads.append(resolved)
            return resolved.read_bytes()

        def utf8_text(_, data):
            return data.decode("utf-8").encode("utf-8")

        def dialog():
            self.dialogs += 1
            return table({b"ShowDialog": lambda _: 0, b"Dispose": lambda _: None})

        types = {
            b"System.IO.File": table({b"ReadAllBytes": read_bytes}),
            b"System.Security.Cryptography.SHA256": table({
                b"Create": lambda: table({
                    b"ComputeHash": lambda _, data: hashlib.sha256(data).digest(),
                    b"Dispose": lambda _: None,
                }),
            }),
            b"System.BitConverter": table({
                b"ToString": lambda data: data.hex("-").upper().encode("ascii"),
            }),
            b"System.Text.UTF8Encoding": lambda *_: table({
                b"GetString": utf8_text, b"GetBytes": utf8_text,
            }),
            b"System.Windows.Forms.FolderBrowserDialog": dialog,
            b"System.Windows.Forms.DialogResult": table({b"OK": 1}),
        }
        self.lua.globals().luanet = table({
            b"load_assembly": lambda _: None, b"import_type": types.__getitem__,
        })
        self.lua.globals().os.getenv = (environment or {}).get

    def run(self, script, configuration, *, root_hint=None):
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(render_launcher(
            configuration, host="127.0.0.1", port=9000, root_hint=root_hint,
        ), encoding="utf-8")
        return self.lua.execute(b"return dofile(...)", str(script).encode("utf-8"))


def installation(root):
    (root / "lua").mkdir(parents=True)
    (root / "lua/slink.lua").write_bytes(
        b"TEST_ENTRY_ENTERED=true\r\n"
        b"return SLINK_ROOT,SLINK_RUNTIME_LAUNCH_JSON,dofile(SLINK_ROOT..'lua/dependency.lua')\r\n"
    )
    (root / "lua/dependency.lua").write_bytes(b"return 'checked dependency'\r\n")
    (root / "payload.bin").write_bytes(b"\x00\xff\r\n")
    return {
        "run_id": "a" * 32, "player": "b", "generation": "gen1",
        "files": file_bundle(root, ["lua/slink.lua", "lua/dependency.lua", "payload.bin"]),
        "client_storage_root": "C:\\Private Runs\\player b", "optional": None,
    }


def test_private_launcher_uses_environment_installation_without_folder_dialog(tmp_path):
    root = tmp_path / "SLink installation with spaces"
    configuration = installation(root)
    script = tmp_path / "private" / "run" / "player b" / "emulator" / "launcher.lua"
    host = LauncherHost({b"SLINK_ROOT": (str(root).replace("/", "\\") + "\\").encode()})

    selected, encoded, dependency = host.run(script, configuration)

    assert host.dialogs == 0
    assert selected.decode() == root.as_posix() + "/"
    assert json.loads(encoded) == {**configuration, "host": "127.0.0.1", "port": 9000}
    assert dependency == b"checked dependency"
    assert (script.parent / "slink_path.cfg").read_text() == root.as_posix() + "/"


@pytest.mark.parametrize("selected_by", ["hint", "environment"])
@pytest.mark.parametrize("tampered", ["lua/slink.lua", "lua/dependency.lua", "payload.bin"])
def test_tampered_closure_refuses_before_entry_or_cache_replacement(tmp_path, selected_by, tampered):
    root = tmp_path / "tampered installation"
    configuration = installation(root)
    alternative = tmp_path / "valid alternative installation"
    installation(alternative)
    (root / tampered).write_bytes(b"return 'untrusted bytes'\n")
    script = alternative / "private" / "launcher.lua"
    script.parent.mkdir()
    cache = script.parent / "slink_path.cfg"
    previous_cache = (alternative.as_posix() + "/\n").encode()
    cache.write_bytes(previous_cache)
    environment = alternative if selected_by == "hint" else root
    host = LauncherHost({b"SLINK_ROOT": str(environment).encode()})

    with pytest.raises(LuaError, match="SLink client files differ from this launcher: " + tampered):
        host.run(script, configuration, root_hint=str(root) if selected_by == "hint" else None)

    assert host.lua.globals().TEST_ENTRY_ENTERED is None
    assert host.dialogs == 0
    assert cache.read_bytes() == previous_cache
    assert host.reads and all(path.is_relative_to(root) for path in host.reads)


@pytest.mark.parametrize("preferred", ["hint", "environment"])
def test_launcher_prefers_hint_then_environment_over_a_stale_cache(tmp_path, preferred):
    root = tmp_path / "selected installation"
    configuration = installation(root)
    stale = tmp_path / "stale installation"
    installation(stale)
    (stale / "payload.bin").write_bytes(b"wrong closure")
    script = stale / "private" / "launcher.lua"
    script.parent.mkdir()
    cache = script.parent / "slink_path.cfg"
    cache.write_text(stale.as_posix() + "/")
    environment = stale if preferred == "hint" else root
    host = LauncherHost({b"SLINK_ROOT": str(environment).encode()})

    selected, _, _ = host.run(
        script, configuration, root_hint=str(root) if preferred == "hint" else None,
    )

    assert Path(selected.decode()) == root
    assert host.dialogs == 0
    assert cache.read_text() == root.as_posix() + "/"


@pytest.mark.parametrize("environment", [None, "", "missing installation"])
@pytest.mark.parametrize("fallback", ["cache", "relative"])
def test_absent_or_invalid_environment_preserves_existing_fallback(tmp_path, environment, fallback):
    root = tmp_path / "fallback installation"
    configuration = installation(root)
    script = (root if fallback == "relative" else tmp_path / "private") / "one/two/three/launcher.lua"
    script.parent.mkdir(parents=True)
    cache = script.parent / "slink_path.cfg"
    if fallback == "cache":
        cache.write_text(root.as_posix() + "/")
    value = str(tmp_path / environment) if environment else environment
    host = LauncherHost({} if value is None else {b"SLINK_ROOT": value.encode()})

    selected, encoded, _ = host.run(script, configuration)

    assert Path(selected.decode()).resolve() == root
    assert host.dialogs == 0
    assert json.loads(encoded) == {**configuration, "host": "127.0.0.1", "port": 9000}
