"""Address-free, run-bound launchers with a checked local client-file closure."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath

from server.lua_literals import lua_comment, lua_string

# A composed generation service includes observation, held-write and native
# adapters. Keep one explicit bounded closure without merging reusable modules.
MAX_CLIENT_FILES = 128


def _relative(name):
    if not isinstance(name, str) or not name or any(ord(char) < 32 for char in name):
        raise ValueError("client bundle path required")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name or path.as_posix() != name or name == ".":
        raise ValueError("client bundle paths must stay within their root")
    return path


def file_bundle(root, paths):
    root = Path(root).resolve()
    if not paths or len(paths) > MAX_CLIENT_FILES or len(set(paths)) != len(paths):
        raise ValueError("bounded unique client-file closure required")
    result = []
    for name in sorted(paths):
        _relative(name)
        path = (root/name).resolve()
        if not path.is_relative_to(root):
            raise ValueError("client bundle file escapes its root")
        raw = path.read_bytes()
        if not 0 < len(raw) <= 8*1024*1024:
            raise ValueError("client bundle file has an unsupported size")
        kind = "utf8_lf" if path.suffix in {".lua", ".json"} else "raw"
        encoded = raw.decode("utf-8").replace("\r\n", "\n").encode("utf-8") if kind == "utf8_lf" else raw
        result.append({"path": name, "sha256": hashlib.sha256(encoded).hexdigest(), "encoding": kind})
    return result


def player_resume(resume, player):
    """The run record's resume field, narrowed to what one player's client must prove: the predecessor
    run and the digest of the save it last acknowledged, under the named projection. None stays None."""
    if resume is None:
        return None
    required = resume.get("required") if isinstance(resume, dict) else None
    entry = required.get(player) if isinstance(required, dict) else None
    if (not isinstance(resume.get("from_run"), str) or not resume["from_run"] or not isinstance(entry, dict)
            or not isinstance(entry.get("digest"), str) or not re.fullmatch(r"[0-9a-f]{64}", entry["digest"])
            or not isinstance(entry.get("projection"), str) or not entry["projection"]):
        raise ValueError("complete resume contract for this player required")
    return {"from_run": resume["from_run"], "required_digest": entry["digest"], "projection": entry["projection"]}


def render_launcher(configuration, *, host, port, name="SLink", root_hint=None, resume=None):
    if (not isinstance(configuration, dict) or not re.fullmatch(r"[0-9a-f]{32}", configuration.get("run_id", ""))
            or configuration.get("player") not in ("a", "b") or not configuration.get("files")):
        raise ValueError("complete run/player launch configuration required")
    if (not isinstance(host, str) or not 1 <= len(host) <= 255 or re.search(r"[\s\x00-\x1f]", host)
            or type(port) is not int or not 1 <= port <= 65535):
        raise ValueError("valid runtime endpoint required")
    configuration = {**configuration, "host": host, "port": port}
    if resume is not None:
        configuration["resume"] = player_resume(resume, configuration["player"])
    files = []
    if not isinstance(configuration["files"], list) or not 1 <= len(configuration["files"]) <= MAX_CLIENT_FILES:
        raise ValueError("bounded client-file closure required")
    seen = set()
    for entry in configuration["files"]:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "encoding"}:
            raise ValueError("complete client file descriptor required")
        _relative(entry["path"])
        if entry["path"] in seen or entry["encoding"] not in {"utf8_lf", "raw"} or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            raise ValueError("invalid or duplicate client file descriptor")
        seen.add(entry["path"])
        files.append("{"+",".join(lua_string(entry[key]) for key in ("path", "sha256", "encoding"))+"}")
    if "lua/slink.lua" not in seen:
        raise ValueError("the universal entrypoint must be included in the checked closure")
    encoded = json.dumps(configuration, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    replacements = {"@NAME@": lua_comment(name), "@ROOT@": lua_string(root_hint) if root_hint else "nil",
                    "@FILES@": ",\n    ".join(files), "@CONFIG@": lua_string(encoded)}
    return re.sub(r"@(?:NAME|ROOT|FILES|CONFIG)@", lambda match: replacements[match[0]], _TEMPLATE)


_TEMPLATE = r'''-- SLink run-bound launcher: @NAME@
-- Connects the configured durable client. Gameplay remains held until qualified.
local root=@ROOT@
local script_dir=((debug.getinfo(1,"S") or {}).source or ""):match("@(.+[/\\])") or ""
local cache_path=script_dir.."slink_path.cfg"
local function valid(path)
    if type(path)~="string" or path=="" then return false end
    local file=io.open(path.."lua/slink.lua","r")
    if file then file:close();return true end
    return false
end
if root then root=root:gsub("\\","/"):gsub("/*$", "/")end
if not valid(root)then root=nil end
if not root then
    local environment=os.getenv("SLINK_ROOT")
    if environment and environment~="" then environment=environment:gsub("\\","/"):gsub("/*$", "/")end
    if valid(environment)then root=environment end
end
if not root then
    local file=io.open(cache_path,"r")
    if file then local cached=file:read("*l");file:close();if valid(cached)then root=cached end end
end
if not root then
    for _,relative in ipairs({"","../","../../","../../../"})do
        if valid(script_dir..relative)then root=script_dir..relative;break end
    end
end
if not root then
    luanet.load_assembly("System.Windows.Forms")
    local Dialog=luanet.import_type("System.Windows.Forms.FolderBrowserDialog")
    local Result=luanet.import_type("System.Windows.Forms.DialogResult")
    local dialog=Dialog();dialog.Description="Select the SLink project folder";dialog.ShowNewFolderButton=false
    if dialog:ShowDialog()==Result.OK then root=tostring(dialog.SelectedPath):gsub("\\","/").."/"end
    dialog:Dispose()
end
assert(valid(root),"SLink project folder is unavailable")
luanet.load_assembly("System")
local File=luanet.import_type("System.IO.File")
local Hash=luanet.import_type("System.Security.Cryptography.SHA256")
local Bits=luanet.import_type("System.BitConverter")
local Encoding=luanet.import_type("System.Text.UTF8Encoding")
local utf8=Encoding(false,true)
local files={
    @FILES@
}
for _,entry in ipairs(files)do
    local bytes=File.ReadAllBytes(root..entry[1])
    if entry[3]=="utf8_lf" then
        local text=tostring(utf8:GetString(bytes)):gsub("\r\n","\n")
        bytes=utf8:GetBytes(text)
    end
    local hash=Hash.Create()
    local actual=tostring(Bits.ToString(hash:ComputeHash(bytes))):gsub("-",""):lower()
    hash:Dispose()
    assert(actual==entry[2],"SLink client files differ from this launcher: "..entry[1]..". Update the client or download a new launcher.")
end
local file=io.open(cache_path,"w");if file then file:write(root);file:close()end
SLINK_ROOT=root
SLINK_RUNTIME_LAUNCH_JSON=@CONFIG@
return dofile(root.."lua/slink.lua")
'''
