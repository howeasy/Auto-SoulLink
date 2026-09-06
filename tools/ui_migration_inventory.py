"""Offline UI migration inventory; never import/start either application.

Read literal route registrations and overlay declarations, and hash reviewed
mockup inputs. Output is planning evidence, not proof of rendering or runtime
admission. Unresolved registrations are reported with a nonzero exit status.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROUTE_FILES = {
    "run": "server/server.py",
    "manager": "server/manager.py",
    "patcher": "server/patcher.py",
    "static": "server/templating.py",
}
MOCKUP_INPUTS = (
    "docs/ui_mockup_brief.md",
    "server/static/mockups/a/index.html",
    "server/static/mockups/a/mockup.css",
    "server/static/mockups/a/mockup.js",
    "server/static/mockups/a/fonts.css",
    "server/static/mockups/fixtures/gen3.json",
    "server/static/mockups/fixtures/gen1.json",
    "server/static/mockups/fixtures/capabilities.json",
    "server/static/mockups/fixtures/runs.json",
    "tests/unit/test_mockup_fixtures.py",
    "tools/gen_ui_capabilities.py",
    "tools/inject_full_mocks.py",
)
SELECTED_FONTS = {"Jersey 20", "IBM Plex Sans"}


def literal(node, names):
    """Resolve constants and references only; no eval/import/function calls."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id in names:
        return names[node.id]
    if isinstance(node, (ast.List, ast.Tuple)):
        return [literal(item, names) for item in node.elts]
    if isinstance(node, ast.Dict) and all(key is not None for key in node.keys):
        return {literal(key, names): literal(value, names)
                for key, value in zip(node.keys, node.values, strict=True)}
    raise ValueError(f"nonliteral declaration: {ast.unparse(node)}")


def read_catalog(source):
    names = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        else:
            continue
        if not isinstance(target, ast.Name) or value is None:
            continue
        try:
            names[target.id] = literal(value, names)
        except ValueError:
            if target.id == "OVERLAYS":
                raise
    overlays = names.get("OVERLAYS")
    if not isinstance(overlays, list) or not overlays:
        raise ValueError("OVERLAYS must be a nonempty literal list")
    slugs = [row["slug"] for row in overlays]
    if len(set(slugs)) != len(slugs):
        raise ValueError("duplicate overlay slug")
    return overlays


def read_routes(source, filename):
    routes, mounts, unresolved = [], [], []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "router" and node.func.attr.startswith("add_")):
            continue
        operation = node.func.attr[4:]
        location = {"source": filename, "line": node.lineno}
        try:
            if any(keyword.arg is None for keyword in node.keywords):
                raise ValueError("registration options require explicit keywords")
            if operation == "route":
                method, path = literal(node.args[0], {}), literal(node.args[1], {})
                handler = ast.unparse(node.args[2])
            elif operation in {"get", "post", "put", "patch", "delete", "head", "options"}:
                method, path = operation.upper(), literal(node.args[0], {})
                handler = ast.unparse(node.args[1])
            elif operation == "static":
                mounts.append({**location, "path": literal(node.args[0], {})})
                continue
            else:
                raise ValueError(f"unsupported router registration: {operation}")
            if not isinstance(path, str) or not path.startswith("/") or not isinstance(method, str):
                raise ValueError("expected literal method and absolute route path")
            methods = [method]
            if operation == "get":
                allow_head = next((literal(kw.value, {}) for kw in node.keywords
                                   if kw.arg == "allow_head"), True)
                if not isinstance(allow_head, bool):
                    raise ValueError("allow_head must be a literal boolean")
                if allow_head:
                    methods.append("HEAD")
            routes.append({**location, "method": method, "served_methods": methods,
                           "path": path, "handler": handler})
        except (ValueError, IndexError) as exc:
            unresolved.append({**location, "expression": ast.unparse(node), "reason": str(exc)})
    return routes, mounts, unresolved


def file_record(root, relative, *, binary=False):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"input escapes checkout: {relative}")
    data = path.read_bytes() if binary else path.read_text(encoding="utf-8").encode("utf-8")
    return {"path": relative, "sha256": hashlib.sha256(data).hexdigest(),
            "hash_format": "bytes" if binary else "utf8-normalized-newlines", "bytes": len(data)}


def revision(root):
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                            check=True, capture_output=True, text=True)
    return result.stdout.strip()


def snapshot(repo, mockup_repo=None):
    parts, mounts, unresolved, inputs = {}, {}, [], []
    for name, filename in ROUTE_FILES.items():
        parts[name], mounts[name], failures = read_routes(
            (repo / filename).read_text(encoding="utf-8"), filename)
        inputs.append(file_record(repo, filename))
        unresolved.extend(failures)
    catalog_path = "server/overlay_catalog.py"
    overlays = read_catalog((repo / catalog_path).read_text(encoding="utf-8"))
    inputs.append(file_record(repo, catalog_path))
    # This one reviewed table registration expands the literal catalog. Other
    # dynamic registrations remain unresolved. Runtime parity below is tested
    # against build_app, so a changed registry cannot silently lose routes.
    run_source = (repo / ROUTE_FILES["run"]).read_text(encoding="utf-8")
    registrations = [node for node in ast.walk(ast.parse(run_source))
                     if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                     and node.func.id == "register_legacy_routes"]
    if registrations:
        inputs.append(file_record(repo, "server/broadcast_render.py"))
    for call in registrations:
        for overlay in overlays:
            if overlay["slug"] == "all":
                continue
            for suffix in ("", "/fragment"):
                parts["run"].append({"source": ROUTE_FILES["run"], "line": call.lineno,
                                     "method": "GET", "served_methods": ["GET", "HEAD"],
                                     "path": "/stream/" + overlay["slug"] + suffix,
                                     "handler": "register_legacy_routes"})
    services = {}
    for service in ("run", "manager"):
        rows = parts[service] + parts["patcher"]
        identities = [(method, row["path"]) for row in rows for method in row["served_methods"]]
        if len(set(identities)) != len(identities):
            raise ValueError(f"duplicate {service} route")
        services[service] = sorted(rows, key=lambda row: (row["path"], row["method"]))
    run_gets = {row["path"] for row in services["run"] if row["method"] == "GET"}
    overlay_pairs = []
    for overlay in overlays:
        slug = overlay["slug"]
        if slug == "all":
            continue  # synthetic gallery entry; never invent /stream/all
        page = f"/stream/{slug}"
        overlay_pairs.append({"slug": slug, "page": page, "fragment": page + "/fragment",
                              "both_registered": page in run_gets and page + "/fragment" in run_gets})
    result = {
        "schema": "slink-ui-migration-inventory-v1", "source_commit": revision(repo),
        "evidence": "static declarations; no app startup, rendering, or admission verification",
        "composition": "Each service calls setup_patcher_routes and setup_templating; runtime parity is tested separately.",
        "routes": services, "static_mounts": mounts["static"], "unresolved_routes": unresolved,
        "overlays": overlays, "overlay_route_pairs": overlay_pairs, "inputs": inputs,
    }
    changes = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain", "--", *[row["path"] for row in inputs]],
        check=True, capture_output=True, text=True,
    )
    result["modified_source_inputs"] = changes.stdout.splitlines()
    if mockup_repo is not None:
        records = [file_record(mockup_repo, relative) for relative in MOCKUP_INPUTS]
        css = (mockup_repo / "server/static/mockups/a/fonts.css").read_text(encoding="utf-8")
        fonts = []
        for block in re.findall(r"@font-face\s*\{([^}]+)\}", css):
            family = re.search(r"font-family:\s*['\"]([^'\"]+)['\"]", block)
            if family is None or family[1] not in SELECTED_FONTS:
                continue
            for url in re.findall(r"url\(['\"]?(/static/fonts/[^)'\"]+)['\"]?\)", block):
                fonts.append({"family": family[1], **file_record(mockup_repo, "server" + url, binary=True)})
        if {font["family"] for font in fonts} != SELECTED_FONTS:
            raise ValueError("selected production font declarations are missing")
        fixtures = {}
        for game in ("gen3", "gen1"):
            data = json.loads((mockup_repo / f"server/static/mockups/fixtures/{game}.json").read_text(encoding="utf-8"))
            fixtures[game] = {"top_level_keys": sorted(data), "players": {
                pid: {"keys": sorted(player), "rom_type": player.get("rom_type"),
                      "party_details_count": len(player["party_details"]),
                      "pc_boxes_count": len(player["pc_boxes"])}
                for pid, player in data["players"].items()}}
        result["mockup"] = {"source_commit": revision(mockup_repo), "inputs": records,
                            "selected_fonts": fonts, "fixture_shapes": fixtures}
    return result


def compare(before, after):
    def route_keys(document):
        return {f"{service} {method} {row['path']}" for service, rows in document["routes"].items()
                for row in rows for method in row["served_methods"]}

    old_routes, new_routes = route_keys(before), route_keys(after)
    old_overlays = {row["slug"]: row for row in before["overlays"]}
    new_overlays = {row["slug"]: row for row in after["overlays"]}
    return {
        "route_patterns_removed": sorted(old_routes - new_routes),
        "route_patterns_added": sorted(new_routes - old_routes),
        "overlays_changed": sorted(slug for slug in old_overlays.keys() | new_overlays.keys()
                                   if old_overlays.get(slug) != new_overlays.get(slug)),
        "static_mounts_changed": ["static_mounts"] if [r["path"] for r in before["static_mounts"]]
        != [r["path"] for r in after["static_mounts"]] else [],
        "mockup_changed": ["mockup"] if before.get("mockup") != after.get("mockup") else [],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--mockup-repo", type=Path)
    parser.add_argument("--compare", type=Path, help="Compare contract surfaces; exit 1 on differences")
    parser.add_argument("--output", type=Path, help="Explicit output file; otherwise print JSON")
    args = parser.parse_args(argv)
    try:
        current = snapshot(args.repo, args.mockup_repo)
        missing = [row["slug"] for row in current["overlay_route_pairs"] if not row["both_registered"]]
        code = 2 if current["unresolved_routes"] or missing else 0
        output = current
        if args.compare:
            differences = compare(json.loads(args.compare.read_text(encoding="utf-8")), current)
            output = {"source_commit": current["source_commit"], "differences": differences,
                      "modified_source_inputs": current.get("modified_source_inputs", []),
                      "unresolved_routes": current["unresolved_routes"], "missing_overlay_routes": missing}
            code = max(code, int(any(differences.values())))
        encoded = json.dumps(output, indent=2, ensure_ascii=False) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded, encoding="utf-8", newline="\n")
        else:
            print(encoded, end="")
        return code
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        print(f"UI inventory failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
