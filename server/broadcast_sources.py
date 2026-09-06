"""Atomic, revisioned saved sources. Run archival never mutates this store."""

import asyncio
import copy
import json
import math
import uuid
from pathlib import Path

from server.broadcast_presets import PRESETS, default_controls
from server.json_files import atomic_write_json
from server.templating import VALID_THEMES


class SourceError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class SourceStore:
    def __init__(self, path, run_lookup):
        self.path = Path(path)
        self.run_lookup = run_lookup
        self.lock = asyncio.Lock()

    def _validate(self, source, *, previous=None, check_run=True):
        if not isinstance(source, dict):
            raise SourceError("A source configuration object is required.")
        if set(source) - {"id", "revision", "name", "run_id", "preset", "players", "layout", "theme", "controls"}:
            raise SourceError("Unsupported source configuration fields.")
        name = source.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise SourceError("Give this source a name of 1–120 characters.")
        run_id, preset = source.get("run_id"), source.get("preset")
        if not isinstance(run_id, str) or not run_id:
            raise SourceError("Choose an explicit source run.")
        if check_run and (previous is None or previous["run_id"] != run_id) and self.run_lookup(run_id) is None:
            raise SourceError("The selected run no longer exists.")
        if not isinstance(preset, str) or preset not in PRESETS:
            raise SourceError("Choose a supported broadcast preset.")
        definition = PRESETS[preset]
        players = source.get("players", ["a"] if ["a"] in definition["player_choices"] else ["a", "b"])
        if players not in definition["player_choices"]:
            raise SourceError("Choose a supported player selection for this preset.")
        layout = source.get("layout", "")
        if layout not in definition["layouts"]:
            raise SourceError("This preset does not support that layout.")
        theme = source.get("theme", "transparent")
        theme = "default" if theme == "dark" else theme
        if not isinstance(theme, str) or theme not in VALID_THEMES:
            raise SourceError("Choose a supported theme.")
        controls = source.get("controls", default_controls(preset))
        if not isinstance(controls, dict) or set(controls) - set(default_controls(preset)):
            raise SourceError("This preset does not support those controls.")
        controls = {**default_controls(preset), **controls}
        for key in ("speed", "pause"):
            if key in controls:
                value = controls[key]
                low, high = (.1, 5) if key == "speed" else (0, 30)
                if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                    raise SourceError(f"{key.capitalize()} must be between {low} and {high}.")
        if "filter" in controls:
            filters = controls["filter"]
            if not isinstance(filters, list) or any(not isinstance(item, str) or item not in definition["event_filters"] for item in filters) or len(filters) != len(set(filters)):
                raise SourceError("Choose supported, unique event filters.")
        return {"name": name.strip(), "run_id": run_id, "preset": preset, "players": list(players),
                "layout": layout, "theme": theme, "controls": copy.deepcopy(controls)}

    def _read(self):
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(document, dict) or set(document) != {"schema", "sources"} or document["schema"] != 1 or not isinstance(document["sources"], list):
                raise ValueError("invalid store")
            seen, result = set(), []
            for source in document["sources"]:
                identifier = source.get("id")
                if not isinstance(identifier, str) or len(identifier) != 32 or any(c not in "0123456789abcdef" for c in identifier) or identifier in seen:
                    raise ValueError("invalid or duplicate source identity")
                if type(source.get("revision")) is not int or source["revision"] < 1:
                    raise ValueError("invalid source revision")
                seen.add(identifier)
                clean = self._validate(source, check_run=False)
                result.append({"id": identifier, "revision": source["revision"], **clean})
            return result
        except FileNotFoundError:
            return []
        except (OSError, ValueError, TypeError, AttributeError, KeyError) as error:
            raise SourceError("Saved broadcast sources could not be read. The original file has been preserved.", 503) from error

    def list(self):
        return self._read()

    def get(self, identifier):
        source = next((item for item in self._read() if item["id"] == identifier), None)
        if source is None:
            raise SourceError("This saved source no longer exists.", 404)
        return source

    def _write(self, sources):
        self._read()  # corruption after an earlier read must not be overwritten
        try:
            atomic_write_json(self.path, {"schema": 1, "sources": sources})
        except OSError as error:
            raise SourceError("Saved sources could not be written. Your previous configuration is retained.", 503) from error

    async def create(self, body):
        async with self.lock:
            if not isinstance(body, dict) or "id" in body or "revision" in body:
                raise SourceError("Source IDs and initial revisions are assigned automatically.")
            sources = self._read()
            source = {"id": uuid.uuid4().hex, "revision": 1, **self._validate(body)}
            sources.append(source)
            self._write(sources)
            return copy.deepcopy(source)

    async def update(self, identifier, body):
        async with self.lock:
            sources = self._read()
            previous = next((source for source in sources if source["id"] == identifier), None)
            if previous is None:
                raise SourceError("This saved source no longer exists.", 404)
            if not isinstance(body, dict) or type(body.get("revision")) is not int or body["revision"] != previous["revision"]:
                raise SourceError("This source changed. Reload its current revision before saving.", 409)
            if "id" in body and body["id"] != identifier:
                raise SourceError("A saved source ID cannot be changed.")
            merged = {**previous, **body}
            clean = self._validate(merged, previous=previous)
            updated = {"id": identifier, "revision": previous["revision"] + 1, **clean}
            sources[sources.index(previous)] = updated
            self._write(sources)
            return copy.deepcopy(updated)

    async def delete(self, identifier, revision):
        async with self.lock:
            sources = self._read()
            current = next((source for source in sources if source["id"] == identifier), None)
            if current is None:
                raise SourceError("This saved source no longer exists.", 404)
            if type(revision) is not int or revision != current["revision"]:
                raise SourceError("This source changed. Reload before deleting it.", 409)
            sources.remove(current)
            self._write(sources)
